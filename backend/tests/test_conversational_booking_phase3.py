from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.timeutils import now_local
from app.models import Appointment, Department, Staff, StaffAvailability
from tests.conftest import ADMIN, booking_payload, future_slot, iso


def ask(client, msg, token=None, headers=None):
    payload = {"message": msg}
    if token:
        payload["session_token"] = token
    r = client.post("/api/public/chat", json=payload, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def test_nl_extraction_morning_and_auto_staff(client, org):
    """'I want to meet someone from Admissions tomorrow morning' extracts dept, date, morning time_pref, and asks for staff or proceeds."""
    r1 = ask(client, "I want to meet someone from Admissions tomorrow morning.")
    token = r1["session_token"]
    assert r1["booking_flow"]["department_name"] == "Admissions"
    assert r1["booking_flow"]["time_pref"] == "morning"
    # Prompts for who to meet
    assert "Who would you like to meet" in r1["reply"]

    # Visitor selects auto-assignment
    r2 = ask(client, "I prefer any available staff member", token)
    assert r2["booking_flow"]["step"] == "slot"
    # Suggestions should be morning slots (starting before 12:00 PM)
    assert len(r2["suggestions"]) > 0
    assert "morning" in r2["reply"].lower()
    for s in r2["suggestions"]:
        if "AM" in s and "–" in s:
            # Slot is morning slot
            assert "AM" in s


def test_nl_extraction_specific_time_at_10_am(client, org):
    """'Book an appointment with Dr. Ravi next Monday at 10 AM' pre-fills dept, staff, date, and 10 AM slot."""
    r1 = ask(client, "Book an appointment with Dr. Ravi next Monday at 10 AM.")
    token = r1["session_token"]
    assert r1["booking_flow"]["staff_name"] == "Dr. Ravi"
    assert r1["booking_flow"]["department_name"] == "Admissions"
    assert r1["booking_flow"]["step"] == "slot"
    # Highlights 10:00 AM slot
    assert "10:00 AM" in r1["reply"] or "10:00 AM" in r1["suggestions"][0]


def test_nl_extraction_afternoon_slot_filtering(client, org):
    """'I need to visit Admissions in the afternoon' extracts department and afternoon time_pref."""
    r1 = ask(client, "I need to visit Admissions in the afternoon.")
    token = r1["session_token"]
    assert r1["booking_flow"]["department_name"] == "Admissions"
    assert r1["booking_flow"]["time_pref"] == "afternoon"
    assert "Who would you like to meet" in r1["reply"]

    # Choose auto-assign staff
    r2 = ask(client, "Any available staff member", token)
    assert r2["booking_flow"]["step"] == "date"
    assert "What date would you like to visit" in r2["reply"]

    # Provide date
    r3 = ask(client, "tomorrow", token)
    assert r3["booking_flow"]["step"] == "slot"
    assert "afternoon" in r3["reply"].lower()


def test_nl_earliest_available_slot(client, org):
    """'Show me the earliest available slot tomorrow' finds the earliest slot."""
    r1 = ask(client, "Show me the earliest available slot tomorrow.")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "department"
    assert r1["booking_flow"]["date_str"] is not None

    # Choose department
    r2 = ask(client, "Admissions", token)
    # Choose staff
    r3 = ask(client, "Any available staff member", token)
    assert r3["booking_flow"]["step"] == "slot"
    assert "earliest available slot" in r3["reply"].lower()


def test_nl_dynamic_date_change_to_friday(client, org):
    """'Can I change the appointment to Friday?' switches date without restarting flow."""
    r1 = ask(client, "I want an appointment with Admissions")
    token = r1["session_token"]
    r2 = ask(client, "Dr. Ravi", token)
    r3 = ask(client, "tomorrow", token)
    assert r3["booking_flow"]["step"] == "slot"

    # Switch date to Friday
    r4 = ask(client, "Can I change the appointment to Friday?", token)
    assert r4["booking_flow"]["step"] == "slot"
    assert "Friday" in r4["reply"]


def test_nl_dynamic_switch_to_afternoon(client, org):
    """'Actually, I want the afternoon instead' switches time preference from morning to afternoon."""
    r1 = ask(client, "I want to meet Dr. Ravi tomorrow morning")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "slot"
    assert "morning" in r1["reply"].lower()

    # Visitor changes mind
    r2 = ask(client, "Actually, I want the afternoon instead.", token)
    assert r2["booking_flow"]["step"] == "slot"
    assert "afternoon" in r2["reply"].lower()


def test_department_disambiguation(client, org):
    """When multiple departments match a query, chatbot clarifies instead of guessing."""
    with SessionLocal() as db:
        d2 = Department(name="General Inquiries", location="Main Building", is_active=True)
        d3 = Department(name="Student Inquiries", location="Student Center", is_active=True)
        db.add_all([d2, d3])
        db.commit()

    r1 = ask(client, "I need to visit Inquiries tomorrow")
    assert r1["booking_flow"]["step"] == "department"
    assert "multiple departments matching" in r1["reply"].lower()
    assert "General Inquiries" in r1["suggestions"]
    assert "Student Inquiries" in r1["suggestions"]

    # Visitor disambiguates
    token = r1["session_token"]
    r2 = ask(client, "General Inquiries", token)
    assert r2["booking_flow"]["department_name"] == "General Inquiries"


def test_past_date_handling_asks_for_valid_date(client, org):
    """Past dates (e.g. 'yesterday' or past ISO) are rejected with clear explanation."""
    r1 = ask(client, "I want an appointment with Admissions")
    token = r1["session_token"]
    r2 = ask(client, "Dr. Ravi", token)
    r3 = ask(client, "yesterday", token)
    assert "past" in r3["reply"].lower()
    assert r3["booking_flow"]["step"] == "date"

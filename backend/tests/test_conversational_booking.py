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


def test_conversational_booking_full_guest_flow(client, org):
    """Complete conversational booking flow from intent detection to database persistence."""
    # Step 1: Intent detection
    r1 = ask(client, "I want to book an appointment")
    token = r1["session_token"]
    assert "Which department" in r1["reply"]
    assert r1["booking_flow"]["step"] == "department"

    # Step 2: Department selection
    r2 = ask(client, "Admissions", token)
    assert "Who would you like to meet" in r2["reply"]
    assert r2["booking_flow"]["step"] == "staff"

    # Step 3: Staff selection
    r3 = ask(client, "Dr. Ravi", token)
    assert "What date would you like to visit" in r3["reply"]
    assert r3["booking_flow"]["step"] == "date"

    # Step 4: Date selection (natural language 'tomorrow')
    r4 = ask(client, "tomorrow", token)
    assert "available time slots" in r4["reply"].lower()
    assert r4["booking_flow"]["step"] == "slot"
    assert len(r4["suggestions"]) > 0

    # Step 5: Slot selection
    slot_to_pick = r4["suggestions"][0]  # e.g. "09:00 AM – 09:30 AM"
    r5 = ask(client, slot_to_pick, token)
    assert "full name" in r5["reply"].lower()
    assert r5["booking_flow"]["step"] == "visitor_name"

    # Step 6: Visitor name
    r6 = ask(client, "Aarav Sharma", token)
    assert "phone number" in r6["reply"].lower()
    assert r6["booking_flow"]["step"] == "visitor_phone"

    # Step 7: Visitor phone
    r7 = ask(client, "+919876543210", token)
    assert "email address" in r7["reply"].lower()
    assert r7["booking_flow"]["step"] == "visitor_email"

    # Step 8: Visitor email
    r8 = ask(client, "aarav@example.com", token)
    assert "purpose" in r8["reply"].lower()
    assert r8["booking_flow"]["step"] == "visitor_purpose"

    # Step 9: Purpose
    r9 = ask(client, "Campus admission enquiry", token)
    assert "review your appointment" in r9["reply"].lower()
    assert r9["booking_flow"]["step"] == "confirmation"
    assert "Aarav Sharma" in r9["reply"]

    # Step 10: Confirmation
    r10 = ask(client, "Confirm", token)
    assert "APT-" in r10["reply"]
    assert "Pending Staff Approval" in r10["reply"]
    assert r10["action"] == "booking_completed"

    # Verify database persistence
    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.visitor.has(full_name="Aarav Sharma"))).scalar_one()
        assert appt.status == "pending"
        assert appt.staff.full_name == "Dr. Ravi"
        assert appt.department.name == "Admissions"
        assert appt.purpose == "Campus admission enquiry"
        assert appt.slot_key is not None


def test_conversational_booking_auto_staff_and_initial_entity_extraction(client, org):
    """Initial message with department and date pre-fills flow; 'Any available staff' auto-assigns."""
    # User provides department & date in initial prompt
    r1 = ask(client, "Can I meet someone in Admissions tomorrow?")
    token = r1["session_token"]
    assert r1["booking_flow"]["department_name"] == "Admissions"
    assert "Who would you like to meet" in r1["reply"]

    # User chooses auto-assign staff
    r2 = ask(client, "Any available staff member", token)
    assert r2["booking_flow"]["step"] == "slot"
    assert len(r2["suggestions"]) > 0

    # Pick slot
    slot_choice = r2["suggestions"][0]
    r3 = ask(client, slot_choice, token)
    assert r3["booking_flow"]["step"] == "visitor_name"

    # Fill name & phone
    r4 = ask(client, "Meera Patel", token)
    r5 = ask(client, "+919876543211", token)
    # Skip email
    r6 = ask(client, "skip", token)
    assert r6["booking_flow"]["email"] is None
    # Purpose
    r7 = ask(client, "Course details consultation", token)
    assert r7["booking_flow"]["step"] == "confirmation"

    # Confirm
    r8 = ask(client, "Confirm", token)
    assert "APT-" in r8["reply"]
    assert "Pending Staff Approval" in r8["reply"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.visitor.has(full_name="Meera Patel"))).scalar_one()
        assert appt.status == "pending"
        assert appt.staff.full_name in ("Dr. Ravi", "Ms. Priya")


def test_conversational_booking_registered_user(client, org, admin_h):
    """Logged in user booking auto-links user_id and pre-fills visitor name and phone."""
    r1 = ask(client, "Book me a meeting with Dr. Ravi", headers=admin_h)
    token = r1["session_token"]
    assert r1["booking_flow"]["staff_name"] == "Dr. Ravi"
    assert r1["booking_flow"]["step"] == "date"

    # Select date
    r2 = ask(client, "tomorrow", token, headers=admin_h)
    assert r2["booking_flow"]["step"] == "slot"

    # Pick slot
    slot_choice = r2["suggestions"][0]
    r3 = ask(client, slot_choice, token, headers=admin_h)
    # Since admin user is logged in, name & phone/email are pre-filled! Skips to purpose
    assert r3["booking_flow"]["step"] == "visitor_purpose"
    assert "Test Admin" in r3["reply"]

    # Provide purpose
    r4 = ask(client, "Annual administrative review", token, headers=admin_h)
    assert r4["booking_flow"]["step"] == "confirmation"

    # Confirm
    r5 = ask(client, "Confirm", token, headers=admin_h)
    assert "APT-" in r5["reply"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.purpose == "Annual administrative review")).scalar_one()
        assert appt.user_id is not None
        assert appt.user.email == ADMIN[0]


def test_conversational_booking_cancellation(client, org):
    """Visitor can cancel an active booking flow and resume ordinary chat."""
    r1 = ask(client, "I want to book an appointment")
    token = r1["session_token"]
    assert r1["booking_flow"]["step"] == "department"

    # Cancel
    r2 = ask(client, "cancel", token)
    assert "cancelled the appointment booking" in r2["reply"]
    assert r2["booking_flow"] is None

    # Normal FAQ works immediately after cancellation
    r3 = ask(client, "Where can I park my vehicle?", token)
    assert "main gate" in r3["reply"]
    assert r3["intent"] == "faq"


def test_conversational_booking_change_step_navigation(client, org):
    """Visitor can navigate backwards to change date or department during the flow."""
    r1 = ask(client, "I want to book an appointment")
    token = r1["session_token"]
    r2 = ask(client, "Admissions", token)
    r3 = ask(client, "Dr. Ravi", token)
    r4 = ask(client, "tomorrow", token)
    assert r4["booking_flow"]["step"] == "slot"

    # Change date
    r5 = ask(client, "change date", token)
    assert r5["booking_flow"]["step"] == "date"
    assert "What date would you like" in r5["reply"]

    # Change staff
    r6 = ask(client, "change staff", token)
    assert r6["booking_flow"]["step"] == "staff"
    assert "Who would you like to meet" in r6["reply"]


def test_conversational_booking_slot_conflict_409_handling(client, org):
    """If chosen slot gets occupied before confirmation, chatbot gracefully explains and refreshes slots."""
    r1 = ask(client, "I want an appointment with Admissions", None)
    token = r1["session_token"]
    r2 = ask(client, "Dr. Ravi", token)
    r3 = ask(client, "tomorrow", token)

    slot_to_book = r3["suggestions"][0]
    r4 = ask(client, slot_to_book, token)
    r5 = ask(client, "Conflict Visitor", token)
    r6 = ask(client, "+919876543222", token)
    r7 = ask(client, "skip", token)
    r8 = ask(client, "Urgent consultation", token)
    assert r8["booking_flow"]["step"] == "confirmation"

    # Simulate a competing visitor booking the exact same slot first
    competing = client.post(
        "/api/public/appointments",
        json=booking_payload(
            org["staff_ids"][0],
            datetime.fromisoformat(r8["booking_flow"]["slot_start"]),
            name="Competing Visitor",
            phone="+919000000099",
        ),
    )
    assert competing.status_code == 201

    # First visitor now confirms their booking
    r9 = ask(client, "Confirm", token)
    assert "just taken by another visitor" in r9["reply"]
    assert r9["booking_flow"]["step"] == "slot"
    # Visitor's details are preserved
    assert r9["booking_flow"]["full_name"] == "Conflict Visitor"
    assert r9["booking_flow"]["phone"] == "+919876543222"


def test_conversational_booking_duplicate_confirm_protection(client, org):
    """Repeating confirmation does not create duplicate appointments."""
    r1 = ask(client, "Book me a meeting with Ms. Priya tomorrow")
    token = r1["session_token"]
    slot_choice = r1["suggestions"][0]
    ask(client, slot_choice, token)
    ask(client, "Duplicate Test", token)
    ask(client, "+919876543233", token)
    ask(client, "skip", token)
    ask(client, "Duplicate prevention check", token)
    r_first_confirm = ask(client, "Confirm", token)
    assert "APT-" in r_first_confirm["reply"]

    # Visitor clicks or sends Confirm a second time
    r_second_confirm = ask(client, "Confirm", token)
    assert "already recorded" in r_second_confirm["reply"] or "APT-" in r_second_confirm["reply"]

    with SessionLocal() as db:
        count = db.execute(
            select(Appointment).where(Appointment.visitor.has(full_name="Duplicate Test"))
        ).scalars().all()
        assert len(count) == 1


def test_ambiguous_appointment_query_clarifies_intent(client, org):
    """Ambiguous 'appointment' queries ask for clarification rather than assuming booking."""
    r = ask(client, "appointment?")
    assert r["intent"] == "clarification"
    assert "Are you looking to book an appointment" in r["reply"]


def test_session_state_recovery_endpoint(client, org):
    """GET /api/public/chat recovers conversation and active booking flow."""
    r1 = ask(client, "I want an appointment with Admissions")
    token = r1["session_token"]

    # Query GET /api/public/chat
    r_get = client.get("/api/public/chat", params={"session_token": token})
    assert r_get.status_code == 200
    data = r_get.json()
    assert data["session_token"] == token
    assert data["booking_flow"]["step"] == "staff"
    assert data["booking_flow"]["department_name"] == "Admissions"


def test_session_isolation_between_visitors(client, org):
    """Different session tokens operate in complete isolation."""
    r_a = ask(client, "I want an appointment with Admissions")
    token_a = r_a["session_token"]

    r_b = ask(client, "What are your working hours?")
    token_b = r_b["session_token"]

    assert token_a != token_b
    assert r_a["booking_flow"] is not None
    assert r_b["booking_flow"] is None

    # Advance session A
    ask(client, "Dr. Ravi", token_a)
    # Session B still has no booking flow
    r_b_check = client.get("/api/public/chat", params={"session_token": token_b}).json()
    assert r_b_check["booking_flow"] is None

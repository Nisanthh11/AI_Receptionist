import concurrent.futures
from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.timeutils import now_local
from app.models import Appointment, Department, Staff, StaffAvailability
from tests.conftest import booking_payload, future_slot, iso


def book(client, staff_id, start, **kw):
    return client.post("/api/public/appointments", json=booking_payload(staff_id, start, **kw))


def test_slots_structure_and_details(client, org):
    """Available slots are returned with rich item details (start_at, end_at, is_available, reason)."""
    sid = org["staff_ids"][0]
    day = future_slot(3).date()
    r = client.get("/api/public/slots", params={"staff_id": sid, "date": day.isoformat()})
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["staff_id"] == sid
    assert data["date"] == day.isoformat()
    assert data["slot_minutes"] == 30
    assert len(data["slots"]) == 16
    assert len(data["all_slots"]) == 16

    first = data["all_slots"][0]
    assert first["is_available"] is True
    assert first["reason"] == "available"
    assert first["staff_id"] == sid
    assert first["staff_name"] == "Dr. Ravi"
    assert "09:00:00" in first["start_at"]
    assert "09:30:00" in first["end_at"]


def test_department_level_slot_aggregation(client, org):
    """Department slots aggregate availability across active staff members."""
    dept_id = org["dept_id"]
    s1, s2 = org["staff_ids"][0], org["staff_ids"][1]
    day = future_slot(3).date()
    start_time = future_slot(3, 10, 0)

    # Initially both staff free
    r = client.get("/api/public/slots", params={"department_id": dept_id, "date": day.isoformat()})
    assert r.status_code == 200
    assert len(r.json()["slots"]) == 16

    # Book Dr. Ravi for 10:00
    r_book1 = book(client, s1, start_time, name="Person One", phone="+919000000001")
    assert r_book1.status_code == 201

    # Department query: 10:00 is STILL available because Ms. Priya is free
    r_dept = client.get("/api/public/slots", params={"department_id": dept_id, "date": day.isoformat()})
    assert r_dept.status_code == 200
    assert iso(start_time) in r_dept.json()["slots"]
    slot_10 = next(s for s in r_dept.json()["all_slots"] if "10:00:00" in s["start_at"])
    assert slot_10["is_available"] is True
    assert slot_10["staff_name"] == "Ms. Priya"

    # Book Ms. Priya for 10:00
    r_book2 = book(client, s2, start_time, name="Person Two", phone="+919000000002")
    assert r_book2.status_code == 201

    # Now 10:00 is fully booked across the department
    r_dept2 = client.get("/api/public/slots", params={"department_id": dept_id, "date": day.isoformat()})
    assert iso(start_time) not in r_dept2.json()["slots"]
    slot_10_after = next(s for s in r_dept2.json()["all_slots"] if "10:00:00" in s["start_at"])
    assert slot_10_after["is_available"] is False
    assert slot_10_after["reason"] == "booked"


def test_cancelled_appointment_frees_slot(client, org, admin_h):
    """Cancelled appointments release their slot back to available state."""
    sid = org["staff_ids"][0]
    slot_time = future_slot(3, 14, 0)
    day = slot_time.date()

    r = book(client, sid, slot_time)
    assert r.status_code == 201

    # Check slot is occupied
    r_slots = client.get("/api/public/slots", params={"staff_id": sid, "date": day.isoformat()}).json()
    assert iso(slot_time) not in r_slots["slots"]
    item = next(s for s in r_slots["all_slots"] if "14:00:00" in s["start_at"])
    assert item["is_available"] is False
    assert item["reason"] == "booked"

    # Cancel via admin
    with SessionLocal() as db:
        appt_id = db.execute(select(Appointment.id).where(Appointment.staff_id == sid, Appointment.start_at == slot_time)).scalar_one()
    r_cancel = client.post(f"/api/admin/appointments/{appt_id}/cancel", json={"reason": "Testing release"}, headers=admin_h)
    assert r_cancel.status_code == 200

    # Slot should now be available again
    r_slots_after = client.get("/api/public/slots", params={"staff_id": sid, "date": day.isoformat()}).json()
    assert iso(slot_time) in r_slots_after["slots"]
    item_after = next(s for s in r_slots_after["all_slots"] if "14:00:00" in s["start_at"])
    assert item_after["is_available"] is True
    assert item_after["reason"] == "available"


def test_staff_working_hours_and_breaks(client):
    """Breaks and non-working days are respected with accurate reasons."""
    with SessionLocal() as db:
        dept = Department(name="Dentistry", is_active=True)
        dentist = Staff(full_name="Dr. Smith", designation="Dentist", is_active=True)
        # Works only on Wednesdays (weekday 2): 09:00-12:00 and 13:00-16:00 (12:00-13:00 is lunch break)
        dentist.availability = [
            StaffAvailability(weekday=2, start_time=time(9, 0), end_time=time(12, 0)),
            StaffAvailability(weekday=2, start_time=time(13, 0), end_time=time(16, 0)),
        ]
        dept.staff.append(dentist)
        db.add(dept)
        db.commit()
        dentist_id = dentist.id

    # Find next Wednesday at least 1 day ahead
    today = now_local().date()
    days_until_wed = (2 - today.weekday()) % 7
    if days_until_wed <= 0:
        days_until_wed += 7
    wednesday = today + timedelta(days=days_until_wed)

    r_wed = client.get("/api/public/slots", params={"staff_id": dentist_id, "date": wednesday.isoformat()}).json()
    assert len(r_wed["slots"]) == 12  # 6 slots in morning (9-12), 6 slots in afternoon (13-16)

    # 12:00 should be marked break
    slot_break = next(s for s in r_wed["all_slots"] if "12:00:00" in s["start_at"])
    assert slot_break["is_available"] is False
    assert slot_break["reason"] == "break"

    # Next Sunday (day off)
    sunday = wednesday + timedelta(days=(6 - wednesday.weekday()))
    r_sun = client.get("/api/public/slots", params={"staff_id": dentist_id, "date": sunday.isoformat()}).json()
    assert r_sun["slots"] == []
    assert r_sun["all_slots"] == []


def test_invalid_and_out_of_range_dates(client, org):
    """Past dates, dates beyond maximum horizon, and bad requests are properly handled."""
    sid = org["staff_ids"][0]
    today = now_local().date()

    # Neither staff_id nor department_id provided
    assert client.get("/api/public/slots", params={"date": today.isoformat()}).status_code == 400

    # Non-existent staff_id
    assert client.get("/api/public/slots", params={"staff_id": 99999, "date": today.isoformat()}).status_code == 404

    # Non-existent department_id
    assert client.get("/api/public/slots", params={"department_id": 99999, "date": today.isoformat()}).status_code == 404

    # Staff member doesn't belong to specified department
    assert client.get("/api/public/slots", params={"staff_id": sid, "department_id": 99999, "date": today.isoformat()}).status_code == 400

    # Yesterday returns empty slots
    yesterday = (today - timedelta(days=1)).isoformat()
    r_past = client.get("/api/public/slots", params={"staff_id": sid, "date": yesterday}).json()
    assert r_past["slots"] == []

    # 200 days ahead (beyond max_booking_days_ahead) returns empty slots
    far_ahead = (today + timedelta(days=200)).isoformat()
    r_far = client.get("/api/public/slots", params={"staff_id": sid, "date": far_ahead}).json()
    assert r_far["slots"] == []

    # Booking in past is rejected
    past_dt = now_local() - timedelta(days=2)
    r_book_past = book(client, sid, past_dt)
    assert r_book_past.status_code == 400

    # Booking far ahead is rejected
    far_dt = future_slot(200, 10, 0)
    r_book_far = book(client, sid, far_dt)
    assert r_book_far.status_code == 400


def test_slot_occupied_before_submission_gracefully_rejected(client, org):
    """When a slot becomes occupied just before submission, backend rejects with 409 and clean error message."""
    sid = org["staff_ids"][0]
    slot_time = future_slot(3, 15, 0)

    # First booking succeeds
    r1 = book(client, sid, slot_time, name="Visitor A", phone="+919000000011")
    assert r1.status_code == 201

    # Second booking for the same slot is rejected
    r2 = book(client, sid, slot_time, name="Visitor B", phone="+919000000012")
    assert r2.status_code == 409
    assert "taken" in r2.json()["detail"].lower()


def test_concurrent_booking_collision_prevention(client, org):
    """Simultaneous booking attempts for the same slot serialize safely: one succeeds, one gets 409."""
    sid = org["staff_ids"][0]
    slot_time = future_slot(3, 16, 0)

    results = []

    def attempt_booking(phone, name):
        with SessionLocal() as db:
            from fastapi.testclient import TestClient
            from app.main import app
            with TestClient(app) as local_client:
                r = local_client.post(
                    "/api/public/appointments",
                    json=booking_payload(sid, slot_time, name=name, phone=phone),
                )
                results.append((r.status_code, r.text))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(attempt_booking, "+919000000021", "Competitor One")
        f2 = executor.submit(attempt_booking, "+919000000022", "Competitor Two")
        f1.result()
        f2.result()

    status_codes = [res[0] for res in results]
    assert 201 in status_codes
    assert 409 in status_codes

    with SessionLocal() as db:
        appts = db.execute(select(Appointment).where(Appointment.staff_id == sid, Appointment.start_at == slot_time)).scalars().all()
        assert len(appts) == 1


def test_auto_assign_staff_by_department(client, org):
    """Booking by department_id without staff_id automatically assigns an available staff member."""
    dept_id = org["dept_id"]
    slot_time = future_slot(3, 11, 30)

    # Book 1: auto assigns first available staff member
    p1 = booking_payload(staff_id=0, start=slot_time, name="Auto Visitor 1", phone="+919000000031")
    del p1["staff_id"]
    p1["department_id"] = dept_id
    r1 = client.post("/api/public/appointments", json=p1)
    assert r1.status_code == 201, r1.text
    assert r1.json()["staff_name"] in ("Dr. Ravi", "Ms. Priya")

    # Book 2 at same time: auto assigns second staff member
    p2 = booking_payload(staff_id=0, start=slot_time, name="Auto Visitor 2", phone="+919000000032")
    del p2["staff_id"]
    p2["department_id"] = dept_id
    r2 = client.post("/api/public/appointments", json=p2)
    assert r2.status_code == 201, r2.text
    assert r2.json()["staff_name"] in ("Dr. Ravi", "Ms. Priya")
    assert r2.json()["staff_name"] != r1.json()["staff_name"]

    # Book 3 at same time: both staff are now occupied -> 409 Conflict
    p3 = booking_payload(staff_id=0, start=slot_time, name="Auto Visitor 3", phone="+919000000033")
    del p3["staff_id"]
    p3["department_id"] = dept_id
    r3 = client.post("/api/public/appointments", json=p3)
    assert r3.status_code == 409

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.timeutils import now_local
from app.models import Appointment, Staff, Visitor
from tests.conftest import booking_payload, future_slot, iso


def book(client, staff_id, start, **kw):
    return client.post("/api/public/appointments", json=booking_payload(staff_id, start, **kw))


def count_appointments():
    with SessionLocal() as db:
        return len(db.execute(select(Appointment)).scalars().all())


def test_slots_listing_excludes_booked_and_past(client, org):
    sid = org["staff_ids"][0]
    day = future_slot(3).date()
    r = client.get("/api/public/slots", params={"staff_id": sid, "date": day.isoformat()})
    assert r.status_code == 200
    slots = r.json()["slots"]
    assert len(slots) == 16  # 09:00-17:00 in 30 minute slots
    assert book(client, sid, future_slot(3, 10)).status_code == 201
    after = client.get("/api/public/slots", params={"staff_id": sid, "date": day.isoformat()}).json()["slots"]
    assert len(after) == 15 and "T10:00:00" not in " ".join(after)
    yesterday = (now_local().date() - timedelta(days=1)).isoformat()
    assert client.get("/api/public/slots", params={"staff_id": sid, "date": yesterday}).json()["slots"] == []


def test_successful_booking_is_persisted_and_pending(client, org):
    r = book(client, org["staff_ids"][0], future_slot(3, 10))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending" and body["reference_code"].startswith("APT-")
    assert count_appointments() == 1


def test_public_booking_response_has_no_visitor_details(client, org):
    r = book(client, org["staff_ids"][0], future_slot(3, 10), name="Unique Visitor Name", phone="+919000011111", email="secret@visitor.example")
    text = r.text
    for private in ("Unique Visitor Name", "9000011111", "secret@visitor.example"):
        assert private not in text
    assert set(r.json()) == {"reference_code", "status", "start_at", "end_at", "staff_name", "department_name", "message"}


def test_double_booking_same_slot_is_rejected(client, org):
    sid, start = org["staff_ids"][0], future_slot(3, 11)
    assert book(client, sid, start).status_code == 201
    r = book(client, sid, start, name="Someone Else", phone="+919000000002")
    assert r.status_code == 409
    assert count_appointments() == 1


def test_same_time_different_staff_is_allowed(client, org):
    start = future_slot(3, 11)
    assert book(client, org["staff_ids"][0], start).status_code == 201
    assert book(client, org["staff_ids"][1], start, name="Other Person", phone="+919000000003").status_code == 201


def test_visitor_cannot_hold_two_overlapping_appointments(client, org):
    start = future_slot(3, 11)
    assert book(client, org["staff_ids"][0], start).status_code == 201
    assert book(client, org["staff_ids"][1], start).status_code == 409


def test_cancelled_slot_can_be_rebooked(client, org, admin_h):
    sid, start = org["staff_ids"][0], future_slot(3, 12)
    ref = book(client, sid, start).json()
    with SessionLocal() as db:
        appt_id = db.execute(select(Appointment.id)).scalar_one()
    assert client.post(f"/api/admin/appointments/{appt_id}/cancel", json={"reason": "Visitor asked"}, headers=admin_h).status_code == 200
    assert book(client, sid, start, name="Next Person", phone="+919000000004").status_code == 201


def test_database_unique_slot_key_backstop(org):
    """Even if application checks were bypassed, the DB refuses two active bookings for one staff slot."""
    sid, start = org["staff_ids"][0], future_slot(3, 14)
    with SessionLocal() as db:
        v = Visitor(full_name="V", phone="+919000000009")
        db.add(v)
        db.flush()
        dept_id = db.get(Staff, sid).department_id
        for ref in ("APT-AAAAAAA1", "APT-AAAAAAA2"):
            db.add(Appointment(reference_code=ref, visitor_id=v.id, staff_id=sid, department_id=dept_id, start_at=start,
                               end_at=start + timedelta(minutes=30), purpose="x", slot_key=f"{sid}|{start:%Y%m%d%H%M}"))
        with pytest.raises(IntegrityError):
            db.commit()


@pytest.mark.parametrize("make_start,why", [
    (lambda: now_local() - timedelta(days=1), "past"),
    (lambda: now_local() + timedelta(minutes=5), "inside lead time"),
    (lambda: future_slot(200, 10), "too far ahead"),
    (lambda: future_slot(3, 10, 15), "off the slot grid"),
    (lambda: future_slot(3, 7, 0), "before availability"),
    (lambda: future_slot(3, 17, 0), "after availability"),
])
def test_invalid_times_are_rejected_by_server(client, org, make_start, why):
    r = book(client, org["staff_ids"][0], make_start())
    assert r.status_code in (400, 409), f"{why}: {r.text}"
    assert count_appointments() == 0


def test_inactive_staff_cannot_be_booked(client, org):
    with SessionLocal() as db:
        db.get(Staff, org["staff_ids"][0]).is_active = False
        db.commit()
    assert book(client, org["staff_ids"][0], future_slot(3, 10)).status_code == 404


@pytest.mark.parametrize("override", [{"full_name": "A"}, {"phone": "abc"}, {"purpose": ""}, {"full_name": "<script>x</script>"}, {"email": "nope"}])
def test_input_validation(client, org, override):
    r = book(client, org["staff_ids"][0], future_slot(3, 10), **override)
    assert r.status_code == 422 and count_appointments() == 0


def test_no_success_reported_when_commit_fails(org, monkeypatch):
    """A failing COMMIT must produce an error response and leave nothing behind."""
    from fastapi.testclient import TestClient
    from app.main import app

    def boom(self):
        raise RuntimeError("simulated database failure")

    with TestClient(app, raise_server_exceptions=False) as c:
        monkeypatch.setattr(Session, "commit", boom)
        r = c.post("/api/public/appointments", json=booking_payload(org["staff_ids"][0], future_slot(3, 10)))
        monkeypatch.undo()
    assert r.status_code == 500
    assert "reference_code" not in r.text and "Traceback" not in r.text and "simulated" not in r.text
    assert count_appointments() == 0
    with SessionLocal() as db:
        assert db.execute(select(Visitor)).scalars().all() == []


def test_lookup_requires_matching_phone_and_reference(client, org):
    ref = book(client, org["staff_ids"][0], future_slot(3, 10)).json()["reference_code"]
    ok = client.post("/api/public/appointments/lookup", json={"reference_code": ref.lower(), "phone": "+91 98765 43210"})
    assert ok.status_code == 200 and ok.json()["reference_code"] == ref
    wrong_phone = client.post("/api/public/appointments/lookup", json={"reference_code": ref, "phone": "+919999999999"})
    unknown = client.post("/api/public/appointments/lookup", json={"reference_code": "APT-ZZZZZZZZ", "phone": "+919876543210"})
    assert wrong_phone.status_code == unknown.status_code == 404
    assert wrong_phone.json() == unknown.json()


def test_status_workflow_and_invalid_transitions(client, org, admin_h):
    book(client, org["staff_ids"][0], future_slot(3, 10))
    with SessionLocal() as db:
        aid = db.execute(select(Appointment.id)).scalar_one()
    url = f"/api/admin/appointments/{aid}/status"
    assert client.patch(url, json={"status": "completed"}, headers=admin_h).status_code == 409  # pending -> completed
    assert client.patch(url, json={"status": "bogus"}, headers=admin_h).status_code == 422
    assert client.patch(url, json={"status": "confirmed"}, headers=admin_h).json()["status"] == "confirmed"
    assert client.patch(url, json={"status": "completed"}, headers=admin_h).status_code == 409  # future appointment
    assert client.patch(url, json={"status": "cancelled", "reason": "no show"}, headers=admin_h).status_code == 200
    assert client.patch(url, json={"status": "confirmed"}, headers=admin_h).status_code == 409  # terminal


def test_past_confirmed_appointment_can_be_completed(client, org, admin_h):
    with SessionLocal() as db:
        v = Visitor(full_name="Past Visitor", phone="+919000000010")
        db.add(v)
        db.flush()
        sid = org["staff_ids"][0]
        start = now_local() - timedelta(hours=2)
        a = Appointment(reference_code="APT-PASTPAST", visitor_id=v.id, staff_id=sid, department_id=db.get(Staff, sid).department_id,
                        start_at=start, end_at=start + timedelta(minutes=30), purpose="x", status="confirmed")
        db.add(a)
        db.commit()
        aid = a.id
    r = client.patch(f"/api/admin/appointments/{aid}/status", json={"status": "completed"}, headers=admin_h)
    assert r.status_code == 200 and r.json()["status"] == "completed"


def test_reschedule_validates_conflicts_and_updates(client, org, admin_h):
    sid = org["staff_ids"][0]
    book(client, sid, future_slot(3, 10))
    book(client, sid, future_slot(3, 11), name="Second Person", phone="+919000000005")
    with SessionLocal() as db:
        ids = [a.id for a in db.execute(select(Appointment).order_by(Appointment.start_at)).scalars()]
    url = f"/api/admin/appointments/{ids[0]}/reschedule"
    assert client.post(url, json={"start_at": iso(future_slot(3, 11))}, headers=admin_h).status_code == 409
    assert client.post(url, json={"start_at": iso(future_slot(3, 10, 20))}, headers=admin_h).status_code == 400
    ok = client.post(url, json={"start_at": iso(future_slot(4, 15))}, headers=admin_h)
    assert ok.status_code == 200 and ok.json()["start_at"].startswith(future_slot(4, 15).strftime("%Y-%m-%dT15:00"))
    assert book(client, sid, future_slot(3, 10), name="Third Person", phone="+919000000006").status_code == 201  # old slot freed


def test_admin_search_and_filters_and_privacy(client, org, admin_h, desk_h):
    book(client, org["staff_ids"][0], future_slot(3, 10), name="Searchable Person")
    book(client, org["staff_ids"][1], future_slot(4, 10), name="Another Person", phone="+919000000007")
    assert client.get("/api/admin/appointments").status_code == 401
    r = client.get("/api/admin/appointments", params={"q": "searchable"}, headers=desk_h)
    assert r.json()["total"] == 1 and r.json()["items"][0]["visitor"]["full_name"] == "Searchable Person"
    assert client.get("/api/admin/appointments", params={"status": "pending"}, headers=admin_h).json()["total"] == 2
    assert client.get("/api/admin/appointments", params={"status": "confirmed"}, headers=admin_h).json()["total"] == 0
    assert client.get("/api/admin/appointments", params={"status": "nonsense"}, headers=admin_h).status_code == 422
    day = future_slot(4).date().isoformat()
    assert client.get("/api/admin/appointments", params={"date_from": day, "date_to": day}, headers=admin_h).json()["total"] == 1

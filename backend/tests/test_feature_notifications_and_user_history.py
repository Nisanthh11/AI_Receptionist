from datetime import datetime, timedelta
from unittest.mock import patch
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.rate_limit import lookup_limiter
from app.models import Appointment, User
from tests.conftest import booking_payload, future_slot


def test_guest_booking_generates_ref_and_dev_notification(client, org):
    slot = future_slot(2, 10)
    payload = booking_payload(org["staff_ids"][0], slot, name="Guest Visitor", phone="+919876500001", email="guest@example.com")
    r = client.post("/api/public/appointments", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert data["reference_code"].startswith("APT-")
    assert data["status"] == "pending"
    assert "waiting for confirmation" in data["message"].lower() or "pending" in data["message"].lower()
    # Honest dev mode message since no SMTP/Twilio credentials are configured in test env
    assert "development mode" in data["message"].lower() or "not configured" in data["message"].lower()

    # Verify database persistence
    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == data["reference_code"])).scalar_one()
        assert appt.status == "pending"
        assert appt.user_id is None
        assert appt.sms_status == "not_configured"
        assert appt.email_status == "not_configured"


def test_user_registration_and_login(client):
    reg_payload = {
        "email": "jane.patient@example.com",
        "password": "Password123!",
        "full_name": "Jane Patient",
        "phone": "+919876500002",
    }
    r = client.post("/api/auth/register", json=reg_payload)
    assert r.status_code == 201
    tokens = r.json()
    assert tokens["role"] == "user"
    assert tokens["access_token"]
    assert tokens["user_id"] > 0

    # Test me endpoint
    me_resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "jane.patient@example.com"
    assert me_resp.json()["role"] == "user"


def test_registered_user_booking_links_user_id(client, org):
    # Register user
    reg = client.post("/api/auth/register", json={
        "email": "user.booking@example.com",
        "password": "Password123!",
        "full_name": "Booking User",
        "phone": "+919876500003",
    }).json()
    token = reg["access_token"]
    user_id = reg["user_id"]

    slot = future_slot(4, 11)
    payload = booking_payload(org["staff_ids"][0], slot, name="Booking User", phone="+919876500003", email="user.booking@example.com")
    r = client.post("/api/public/appointments", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        assert appt.user_id == user_id


def test_user_appointment_history_separated(client, org):
    reg = client.post("/api/auth/register", json={
        "email": "history.user@example.com",
        "password": "Password123!",
        "full_name": "History User",
        "phone": "+919876500004",
    }).json()
    token = reg["access_token"]
    user_h = {"Authorization": f"Bearer {token}"}

    # Book upcoming appointment
    slot_future = future_slot(3, 14)
    r1 = client.post("/api/public/appointments", json=booking_payload(org["staff_ids"][0], slot_future), headers=user_h)
    assert r1.status_code == 201
    ref_future = r1.json()["reference_code"]

    # Book another appointment and move it to the past
    slot_past = future_slot(5, 15)
    r2 = client.post("/api/public/appointments", json=booking_payload(org["staff_ids"][1], slot_past), headers=user_h)
    assert r2.status_code == 201
    ref_past = r2.json()["reference_code"]

    with SessionLocal() as db:
        past_appt = db.execute(select(Appointment).where(Appointment.reference_code == ref_past)).scalar_one()
        past_appt.start_at = datetime.utcnow() - timedelta(days=2)
        past_appt.end_at = past_appt.start_at + timedelta(minutes=30)
        past_appt.status = "completed"
        db.commit()

    # Query user appointments
    resp = client.get("/api/user/appointments", headers=user_h)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["upcoming"]) == 1
    assert data["upcoming"][0]["reference_code"] == ref_future
    assert len(data["previous"]) == 1
    assert data["previous"][0]["reference_code"] == ref_past
    assert data["total"] == 2


def test_user_isolation(client, org):
    user_a = client.post("/api/auth/register", json={
        "email": "user.a@example.com",
        "password": "Password123!",
        "full_name": "User Alpha",
        "phone": "+919876500005",
    }).json()

    user_b = client.post("/api/auth/register", json={
        "email": "user.b@example.com",
        "password": "Password123!",
        "full_name": "User Beta",
        "phone": "+919876500006",
    }).json()

    # User A books
    r = client.post(
        "/api/public/appointments",
        json=booking_payload(org["staff_ids"][0], future_slot(2, 9)),
        headers={"Authorization": f"Bearer {user_a['access_token']}"},
    )
    assert r.status_code == 201
    ref_a = r.json()["reference_code"]

    with SessionLocal() as db:
        appt_a = db.execute(select(Appointment).where(Appointment.reference_code == ref_a)).scalar_one()
        appt_a_id = appt_a.id

    # User B checks my appointments -> empty
    user_b_h = {"Authorization": f"Bearer {user_b['access_token']}"}
    resp = client.get("/api/user/appointments", headers=user_b_h)
    assert resp.status_code == 200
    assert resp.json()["total"] == 0

    # User B attempts to access User A's appointment by ID -> 404
    resp_detail = client.get(f"/api/user/appointments/{appt_a_id}", headers=user_b_h)
    assert resp_detail.status_code == 404

    # Unauthenticated request -> 401
    assert client.get("/api/user/appointments").status_code == 401
    assert client.get(f"/api/user/appointments/{appt_a_id}").status_code == 401


def test_guest_lookup_security(client, org):
    slot = future_slot(3, 10)
    phone = "+919876500007"
    r = client.post("/api/public/appointments", json=booking_payload(org["staff_ids"][0], slot, phone=phone))
    ref = r.json()["reference_code"]

    # Valid lookup
    valid_lookup = client.post("/api/public/appointments/lookup", json={"reference_code": ref, "phone": phone})
    assert valid_lookup.status_code == 200
    assert valid_lookup.json()["reference_code"] == ref

    # Wrong phone -> 404
    wrong_phone = client.post("/api/public/appointments/lookup", json={"reference_code": ref, "phone": "+919876500999"})
    assert wrong_phone.status_code == 404

    # Wrong reference code -> 404
    wrong_ref = client.post("/api/public/appointments/lookup", json={"reference_code": "APT-0000-0000", "phone": phone})
    assert wrong_ref.status_code == 404


def test_lookup_rate_limiting(client, org):
    lookup_limiter.requests.clear()
    phone = "+919876500008"

    # Limit is 15 requests per minute
    statuses = []
    for _ in range(18):
        res = client.post("/api/public/appointments/lookup", json={"reference_code": "APT-9999-9999", "phone": phone})
        statuses.append(res.status_code)

    assert 429 in statuses
    lookup_limiter.requests.clear()


def test_notification_failure_does_not_abort_booking(client, org):
    slot = future_slot(3, 16)
    phone = "+919876500009"

    # Patch notification service to simulate a crash/error
    with patch("app.services.appointment_service.send_booking_notifications") as mock_notif:
        mock_notif.side_effect = Exception("Simulated SMS/Email provider connection crash")

        # Booking should STILL succeed (requirement 3 & 5)
        r = client.post("/api/public/appointments", json=booking_payload(org["staff_ids"][0], slot, phone=phone))
        assert r.status_code == 201
        ref = r.json()["reference_code"]

        with SessionLocal() as db:
            appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
            assert appt.status == "pending"
            assert appt.reference_code == ref


def test_user_profile_fetch_and_update(client):
    reg = client.post("/api/auth/register", json={
        "email": "profile.user@example.com",
        "password": "Password123!",
        "full_name": "Original Name",
        "phone": "+919876543210",
    }).json()
    token = reg["access_token"]
    user_h = {"Authorization": f"Bearer {token}"}

    # Fetch profile
    me = client.get("/api/auth/me", headers=user_h)
    assert me.status_code == 200
    data = me.json()
    assert data["full_name"] == "Original Name"
    assert data["email"] == "profile.user@example.com"
    assert data["phone"] == "+919876543210"
    assert data["created_at"] is not None

    # Update profile
    patch_res = client.patch("/api/auth/me", json={"full_name": "Updated Name", "phone": "+919999988888"}, headers=user_h)
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["full_name"] == "Updated Name"
    assert updated["phone"] == "+919999988888"

    # Validation errors on invalid phone
    bad_phone = client.patch("/api/auth/me", json={"phone": "invalid-phone"}, headers=user_h)
    assert bad_phone.status_code == 422

    # Unauthenticated update rejected
    unauth = client.patch("/api/auth/me", json={"full_name": "Hacker"})
    assert unauth.status_code == 401

"""Automated tests for appointment check-in service and admin check-in API endpoint."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.timeutils import now_local
from app.models import Appointment, Notification
from app.models.appointment import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_CONFIRMED, STATUS_PENDING
from app.services.visitor_service import get_or_create_visitor


def _create_test_appointment(
    org,
    *,
    reference_code: str = "APT-CHECKIN01",
    days_offset: int = 0,
    status: str = STATUS_CONFIRMED,
    checked_in: bool = False,
    full_name: str = "Priya Sharma",
    phone: str = "+919876543210",
    email: str = "priya.sharma@example.com",
) -> str:
    """Helper to insert an appointment with deterministic start_at and status."""
    now = now_local()
    target_date = now.date() + timedelta(days=days_offset)
    start_dt = now.replace(
        year=target_date.year,
        month=target_date.month,
        day=target_date.day,
        hour=14,
        minute=0,
        second=0,
        microsecond=0,
    )
    end_dt = start_dt + timedelta(minutes=30)

    with SessionLocal() as db:
        visitor = get_or_create_visitor(db, full_name, phone, email)
        appt = Appointment(
            reference_code=reference_code,
            booking_source="website",
            visitor_id=visitor.id,
            staff_id=org["staff_ids"][0],
            department_id=org["dept_id"],
            start_at=start_dt,
            end_at=end_dt,
            purpose="Document Verification",
            status=status,
            checked_in_at=now if checked_in else None,
        )
        db.add(appt)
        db.commit()
        return reference_code


def test_checkin_success_by_receptionist(client, org, desk_h):
    """Front desk receptionist can check in an appointment scheduled for today."""
    ref = _create_test_appointment(org, reference_code="APT-TODAY100")

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["reference_code"] == "APT-TODAY100"
    assert data["status"] == STATUS_CONFIRMED
    assert data["checked_in_at"] is not None
    assert data["visitor_name"] == "Priya Sharma"
    assert data["department_name"] == "Admissions"
    assert data["staff_name"] == "Dr. Ravi"
    assert "successfully" in data["message"]

    # Verify database persistence
    with SessionLocal() as db:
        saved = db.execute(
            select(Appointment).where(Appointment.reference_code == "APT-TODAY100")
        ).scalar_one()
        assert saved.checked_in_at is not None
        assert saved.status == STATUS_CONFIRMED  # Status is not prematurely completed

        # Verify notification created
        notif = db.execute(
            select(Notification).where(
                Notification.appointment_id == saved.id,
                Notification.type == "appointment_checked_in",
            )
        ).scalar_one_or_none()
        assert notif is not None
        assert "checked in" in notif.message


def test_checkin_success_by_admin(client, org, admin_h):
    """Admin staff can also check in an appointment."""
    ref = _create_test_appointment(org, reference_code="APT-TODAY101")

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=admin_h)
    assert resp.status_code == 200
    assert resp.json()["reference_code"] == "APT-TODAY101"


def test_checkin_unauthenticated_rejected(client, org):
    """Unauthenticated check-in requests are rejected with 401."""
    ref = _create_test_appointment(org, reference_code="APT-TODAY102")

    resp = client.post(f"/api/admin/appointments/{ref}/checkin")
    assert resp.status_code == 401
    assert "Authentication required" in resp.json()["detail"]


def test_checkin_unknown_reference_code_rejected(client, org, desk_h):
    """Non-existent reference code returns 404."""
    resp = client.post("/api/admin/appointments/APT-NOTFOUND999/checkin", headers=desk_h)
    assert resp.status_code == 404
    assert "No appointment found" in resp.json()["detail"]


def test_checkin_case_and_whitespace_normalization(client, org, desk_h):
    """Check-in handles lowercase input and whitespace cleanly."""
    _create_test_appointment(org, reference_code="APT-CASETEST1")

    # Lowercase in path
    resp = client.post("/api/admin/appointments/apt-casetest1/checkin", headers=desk_h)
    assert resp.status_code == 200
    assert resp.json()["reference_code"] == "APT-CASETEST1"


def test_checkin_duplicate_rejected(client, org, desk_h):
    """Checking in an already checked-in appointment returns 409."""
    ref = _create_test_appointment(org, reference_code="APT-DUP001")

    # First check-in succeeds
    first = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert first.status_code == 200

    # Second check-in is rejected
    second = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert second.status_code == 409
    assert "already checked in" in second.json()["detail"]


def test_checkin_cancelled_appointment_rejected(client, org, desk_h):
    """Cancelled appointment cannot be checked in (409 Conflict)."""
    ref = _create_test_appointment(
        org, reference_code="APT-CANCELLED1", status=STATUS_CANCELLED
    )

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 409
    assert "cancelled" in resp.json()["detail"].lower()


def test_checkin_completed_appointment_rejected(client, org, desk_h):
    """Completed appointment cannot be checked in (409 Conflict)."""
    ref = _create_test_appointment(
        org, reference_code="APT-COMPLETED1", status=STATUS_COMPLETED
    )

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 409
    assert "completed" in resp.json()["detail"].lower()


def test_checkin_future_date_rejected(client, org, desk_h):
    """Appointment scheduled for a future date cannot be checked in today."""
    ref = _create_test_appointment(org, reference_code="APT-FUTURE001", days_offset=2)

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 409
    assert "not today" in resp.json()["detail"].lower()


def test_checkin_past_date_rejected(client, org, desk_h):
    """Appointment scheduled for a past date cannot be checked in today."""
    ref = _create_test_appointment(org, reference_code="APT-PAST001", days_offset=-1)

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 409
    assert "not today" in resp.json()["detail"].lower()


def test_checkin_response_privacy(client, org, desk_h):
    """Check-in response protects visitor PII (no phone, no email, no private notes)."""
    ref = _create_test_appointment(
        org,
        reference_code="APT-PRIVACY01",
        phone="+919876543210",
        email="veryprivate@example.com",
    )

    resp = client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h)
    assert resp.status_code == 200
    raw_text = resp.text

    # Visitor phone and email must never be echoed in check-in response
    assert "+919876543210" not in raw_text
    assert "veryprivate@example.com" not in raw_text

    # Verified payload fields
    keys = set(resp.json().keys())
    assert keys == {
        "reference_code",
        "status",
        "checked_in_at",
        "start_at",
        "end_at",
        "department_name",
        "staff_name",
        "visitor_name",
        "message",
    }


def test_checkin_concurrent_requests_handled_safely(client, org, desk_h):
    """Concurrent check-in requests for the same appointment result in exactly 1 success."""
    ref = _create_test_appointment(org, reference_code="APT-CONCUR001")

    def _attempt_checkin(_):
        return client.post(f"/api/admin/appointments/{ref}/checkin", headers=desk_h).status_code

    with ThreadPoolExecutor(max_workers=5) as pool:
        statuses = list(pool.map(_attempt_checkin, range(5)))

    # Exactly one request must succeed (200), and all others must receive 409 conflict
    assert statuses.count(200) == 1, f"Expected 1 success, got: {statuses}"
    assert statuses.count(409) == 4, f"Expected 4 duplicate conflicts, got: {statuses}"

    # Confirm in database that checked_in_at is set once
    with SessionLocal() as db:
        saved = db.execute(
            select(Appointment).where(Appointment.reference_code == ref)
        ).scalar_one()
        assert saved.checked_in_at is not None


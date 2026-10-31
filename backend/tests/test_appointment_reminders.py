"""Tests for Part B: Reliable automatic appointment reminders."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import Appointment, AppointmentReminder
from app.models.appointment import (
    REMINDER_STATUS_CANCELLED,
    REMINDER_STATUS_FAILED,
    REMINDER_STATUS_PENDING,
    REMINDER_STATUS_SENT,
    REMINDER_STATUS_SKIPPED,
    REMINDER_TYPE_2H,
    REMINDER_TYPE_24H,
)
from app.services import appointment_service as svc
from app.services.notification_service import BaseEmailProvider
from app.services.reminder_service import (
    cancel_pending_reminders,
    handle_reschedule,
    process_due_reminders,
    schedule_reminders,
)
from tests.conftest import booking_payload, future_slot


class MockEmailProvider(BaseEmailProvider):
    def __init__(self, succeed: bool = True):
        self.succeed = succeed
        self.sent_emails: list[dict] = []

    def send(self, to_email: str, subject: str, text_body: str, html_body: str | None = None) -> tuple[bool, str]:
        if self.succeed:
            self.sent_emails.append({
                "to": to_email,
                "subject": subject,
                "text": text_body,
                "html": html_body,
            })
            return True, "sent"
        return False, "smtp_connection_failed"


def test_reminders_scheduled_on_confirmation(client, admin_h, org):
    """Pending appointments receive no reminders; confirming creates 24h and 2h reminders."""
    slot = future_slot(days_ahead=3, hour=11, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        assert appt.status == "pending"
        reminders = db.execute(select(AppointmentReminder).where(AppointmentReminder.appointment_id == appt.id)).scalars().all()
        assert len(reminders) == 0

    # Confirm via admin
    r_conf = client.patch(f"/api/admin/appointments/{appt.id}/status", headers=admin_h, json={"status": "confirmed"})
    assert r_conf.status_code == 200, r_conf.text

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        assert appt.status == "confirmed"
        reminders = db.execute(select(AppointmentReminder).where(AppointmentReminder.appointment_id == appt.id)).scalars().all()
        assert len(reminders) == 2
        r_types = {r.reminder_type: r for r in reminders}
        assert REMINDER_TYPE_24H in r_types
        assert REMINDER_TYPE_2H in r_types

        # Verify exact schedule intervals
        assert r_types[REMINDER_TYPE_24H].scheduled_for == appt.start_at - timedelta(hours=24)
        assert r_types[REMINDER_TYPE_2H].scheduled_for == appt.start_at - timedelta(hours=2)
        assert r_types[REMINDER_TYPE_24H].status == REMINDER_STATUS_PENDING
        assert r_types[REMINDER_TYPE_2H].status == REMINDER_STATUS_PENDING


def test_no_reminders_delivered_for_cancelled_or_completed(client, admin_h, org):
    """Cancelled and completed appointments do not have reminders delivered."""
    slot = future_slot(days_ahead=3, hour=14, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor2@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()

    # Confirm
    client.patch(f"/api/admin/appointments/{appt.id}/status", headers=admin_h, json={"status": "confirmed"})

    # Cancel
    client.post(f"/api/admin/appointments/{appt.id}/cancel", headers=admin_h, json={"reason": "Customer requested"})

    with SessionLocal() as db:
        reminders = db.execute(select(AppointmentReminder).where(AppointmentReminder.appointment_id == appt.id)).scalars().all()
        assert all(r.status == REMINDER_STATUS_CANCELLED for r in reminders)

        # Attempt to process due reminders with mock email provider at future time
        mock_ep = MockEmailProvider(succeed=True)
        due_time = appt.start_at - timedelta(hours=10)
        delivered = process_due_reminders(db, now=due_time, email_provider=mock_ep)
        assert delivered == 0
        assert len(mock_ep.sent_emails) == 0


def test_rescheduled_appointments_use_new_time(client, admin_h, org):
    """Rescheduled appointments cancel old reminders and schedule new ones for the new time."""
    old_slot = future_slot(days_ahead=3, hour=10, minute=0)
    new_slot = future_slot(days_ahead=4, hour=15, minute=0)

    p = booking_payload(org["staff_ids"][0], old_slot, email="visitor3@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()

    # Confirm
    client.patch(f"/api/admin/appointments/{appt.id}/status", headers=admin_h, json={"status": "confirmed"})

    # Reschedule
    client.post(f"/api/admin/appointments/{appt.id}/reschedule", headers=admin_h, json={"start_at": new_slot.isoformat()})

    with SessionLocal() as db:
        reminders = db.execute(
            select(AppointmentReminder).where(AppointmentReminder.appointment_id == appt.id)
            .order_by(AppointmentReminder.id.asc())
        ).scalars().all()

        # Should have 2 cancelled reminders (for old_slot) and 2 pending reminders (for new_slot)
        cancelled = [r for r in reminders if r.status == REMINDER_STATUS_CANCELLED]
        pending = [r for r in reminders if r.status == REMINDER_STATUS_PENDING]

        assert len(cancelled) == 2
        assert all(r.appointment_start_at == old_slot for r in cancelled)
        assert len(pending) == 2
        assert all(r.appointment_start_at == new_slot for r in pending)
        assert any(r.reminder_type == REMINDER_TYPE_24H and r.scheduled_for == new_slot - timedelta(hours=24) for r in pending)
        assert any(r.reminder_type == REMINDER_TYPE_2H and r.scheduled_for == new_slot - timedelta(hours=2) for r in pending)


def test_reminder_delivery_success_and_email_content(client, admin_h, org):
    """Successful reminder delivery records 'sent' status and sends appropriately styled email."""
    slot = future_slot(days_ahead=2, hour=10, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor4@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt_id = appt.id

    client.patch(f"/api/admin/appointments/{appt_id}/status", headers=admin_h, json={"status": "confirmed"})

    mock_ep = MockEmailProvider(succeed=True)

    with SessionLocal() as db:
        # Simulate time arriving at 24h reminder window
        now_24h = slot - timedelta(hours=23, minutes=50)
        delivered = process_due_reminders(db, now=now_24h, email_provider=mock_ep)
        assert delivered == 1

        # Check provider received 1 email
        assert len(mock_ep.sent_emails) == 1
        sent = mock_ep.sent_emails[0]
        assert sent["to"] == "visitor4@example.com"
        assert f"Appointment Reminder — {ref}" in sent["subject"]
        assert ref in sent["text"]
        assert "Admissions" in sent["text"]
        assert "Confirmed" in sent["text"]

        # Check DB updated
        rem_24h = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt_id,
                AppointmentReminder.reminder_type == REMINDER_TYPE_24H,
            )
        ).scalar_one()
        assert rem_24h.status == REMINDER_STATUS_SENT
        assert rem_24h.sent_at is not None
        assert rem_24h.attempts == 1

        # Check 2h reminder is still pending
        rem_2h = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt_id,
                AppointmentReminder.reminder_type == REMINDER_TYPE_2H,
            )
        ).scalar_one()
        assert rem_2h.status == REMINDER_STATUS_PENDING

        # Now simulate time arriving at 2h window
        now_2h = slot - timedelta(hours=1, minutes=55)
        delivered_2 = process_due_reminders(db, now=now_2h, email_provider=mock_ep)
        assert delivered_2 == 1
        assert len(mock_ep.sent_emails) == 2
        sent_2 = mock_ep.sent_emails[1]
        assert f"Upcoming Appointment in 2 Hours — {ref}" in sent_2["subject"]

        db.refresh(rem_2h)
        assert rem_2h.status == REMINDER_STATUS_SENT
        assert rem_2h.sent_at is not None


def test_reminder_already_sent_is_not_sent_again(client, admin_h, org):
    """Idempotent delivery: a reminder already sent is never re-sent."""
    slot = future_slot(days_ahead=2, hour=10, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor5@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt_id = appt.id

    client.patch(f"/api/admin/appointments/{appt_id}/status", headers=admin_h, json={"status": "confirmed"})

    mock_ep = MockEmailProvider(succeed=True)

    with SessionLocal() as db:
        now_24h = slot - timedelta(hours=23)
        # First execution
        c1 = process_due_reminders(db, now=now_24h, email_provider=mock_ep)
        assert c1 == 1
        assert len(mock_ep.sent_emails) == 1

        # Second execution at the exact same or slightly later time
        c2 = process_due_reminders(db, now=now_24h + timedelta(minutes=10), email_provider=mock_ep)
        assert c2 == 0
        assert len(mock_ep.sent_emails) == 1


def test_smtp_failure_retry_and_max_retries(client, admin_h, org):
    """SMTP failures back off and retry up to max_retries, marking failed on final attempt."""
    slot = future_slot(days_ahead=2, hour=12, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor6@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt_id = appt.id

    client.patch(f"/api/admin/appointments/{appt_id}/status", headers=admin_h, json={"status": "confirmed"})

    failing_ep = MockEmailProvider(succeed=False)
    test_settings = Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="secret-key-that-is-at-least-32-chars-long",
        reminder_max_retries=3,
        reminder_retry_backoff_seconds=30,
    )

    with SessionLocal() as db:
        now = slot - timedelta(hours=23)

        # Attempt 1 -> fails, remains pending with backoff
        process_due_reminders(db, now=now, settings=test_settings, email_provider=failing_ep)
        rem = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt_id,
                AppointmentReminder.reminder_type == REMINDER_TYPE_24H,
            )
        ).scalar_one()
        assert rem.status == REMINDER_STATUS_PENDING
        assert rem.attempts == 1
        assert "smtp_connection_failed" in rem.last_error

        # Attempt 2 -> advance past backoff
        process_due_reminders(db, now=now + timedelta(seconds=35), settings=test_settings, email_provider=failing_ep)
        db.refresh(rem)
        assert rem.status == REMINDER_STATUS_PENDING
        assert rem.attempts == 2

        # Attempt 3 -> reaches max_retries, marks failed
        process_due_reminders(db, now=now + timedelta(seconds=70), settings=test_settings, email_provider=failing_ep)
        db.refresh(rem)
        assert rem.status == REMINDER_STATUS_FAILED
        assert rem.attempts == 3


def test_missing_email_skipped_safely(client, admin_h, org):
    """If visitor has no email address, reminder is marked skipped with clear reason."""
    slot = future_slot(days_ahead=2, hour=10, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email=None)
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt_id = appt.id

    client.patch(f"/api/admin/appointments/{appt_id}/status", headers=admin_h, json={"status": "confirmed"})

    mock_ep = MockEmailProvider(succeed=True)

    with SessionLocal() as db:
        now = slot - timedelta(hours=23)
        delivered = process_due_reminders(db, now=now, email_provider=mock_ep)
        assert delivered == 0
        rem = db.execute(
            select(AppointmentReminder).where(
                AppointmentReminder.appointment_id == appt_id,
                AppointmentReminder.reminder_type == REMINDER_TYPE_24H,
            )
        ).scalar_one()
        assert rem.status == REMINDER_STATUS_SKIPPED
        assert "no email" in rem.last_error.lower()


def test_restart_scheduler_does_not_duplicate_jobs(client, admin_h, org):
    """Calling schedule_reminders repeatedly does not create duplicate entries."""
    slot = future_slot(days_ahead=3, hour=10, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor7@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt.status = "confirmed"
        db.commit()

        # Schedule multiple times
        res1 = schedule_reminders(db, appt)
        res2 = schedule_reminders(db, appt)
        res3 = schedule_reminders(db, appt)

        all_reminders = db.execute(
            select(AppointmentReminder).where(AppointmentReminder.appointment_id == appt.id)
        ).scalars().all()
        assert len(all_reminders) == 2


def test_admin_api_visibility_and_manual_trigger(client, admin_h, org):
    """Admin appointment detail includes reminder status and manual trigger works."""
    slot = future_slot(days_ahead=2, hour=10, minute=0)
    p = booking_payload(org["staff_ids"][0], slot, email="visitor8@example.com")
    r = client.post("/api/public/appointments", json=p)
    assert r.status_code == 201, r.text
    ref = r.json()["reference_code"]

    with SessionLocal() as db:
        appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
        appt_id = appt.id

    client.patch(f"/api/admin/appointments/{appt_id}/status", headers=admin_h, json={"status": "confirmed"})

    # Check admin GET appointment includes reminders array
    r_detail = client.get(f"/api/admin/appointments/{appt_id}", headers=admin_h)
    assert r_detail.status_code == 200, r_detail.text
    detail = r_detail.json()
    assert "reminders" in detail
    assert len(detail["reminders"]) == 2
    assert detail["reminders"][0]["status"] == "pending"

    # Test manual trigger endpoint
    r_proc = client.post("/api/admin/appointments/reminders/process", headers=admin_h)
    assert r_proc.status_code == 200
    assert "processed" in r_proc.json()

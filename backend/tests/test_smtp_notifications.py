"""Automated unit and integration tests for SMTP email notifications with mocked SMTP.

Guarantees:
- Real emails are NEVER sent during automated testing (smtplib is fully mocked).
- SMTP connection lifecycle (STARTTLS, authentication, MIME building, delivery) is strictly validated.
- Robust handling of Google App Password spacing formats.
- Delivery failure gracefully preserves appointments with accurate error status.
- Status transition emails (Request received, Confirmed, Rescheduled, Cancelled) are strictly validated.
- Duplicate prevention (idempotent status updates, editing unrelated fields like notes) is verified.
"""
from datetime import datetime, timedelta
import smtplib
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models import Appointment
from app.services.notification_service import (
    DevelopmentEmailProvider,
    SMTPEmailProvider,
    format_appointment_email,
    format_cancellation_email,
    format_confirmation_email,
    format_rescheduled_email,
    get_email_provider,
)
from tests.conftest import booking_payload, future_slot


def get_message_body(msg) -> str:
    """Helper to extract decoded text content from multipart or singlepart EmailMessage/MIMEMultipart."""
    parts = []
    if msg.is_multipart():
        for part in msg.get_payload():
            payload = part.get_payload(decode=True)
            if payload:
                parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


@pytest.fixture
def test_smtp_settings():
    return Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="a" * 32,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="rurallearn.project@gmail.com",
        smtp_password="mockedapppassword",
        smtp_from_email="rurallearn.project@gmail.com",
        app_name="AI Receptionist",
    )


def test_smtp_provider_tls_success_and_password_cleaning():
    """Test that SMTPEmailProvider connects via STARTTLS, strips spaces from Google App Password, and sends message."""
    mock_server = MagicMock()
    mock_smtp_cls = MagicMock(return_value=mock_server)
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", mock_smtp_cls):
        # User may paste Google App Password with 4-char space grouping: 'abcd efgh ijkl mnop'
        provider = SMTPEmailProvider(
            host="smtp.gmail.com",
            port=587,
            from_email="rurallearn.project@gmail.com",
            user="rurallearn.project@gmail.com",
            password="abcd efgh ijkl mnop",
            use_tls=True,
            use_ssl=False,
            timeout=10,
            display_name="AI Receptionist",
        )

        assert provider.password == "abcdefghijklmnop"
        assert provider.user == "rurallearn.project@gmail.com"

        ok, status = provider.send(
            to_email="visitor@example.com",
            subject="Test Subject",
            text_body="Plain text body",
            html_body="<p>HTML body</p>",
        )

        assert ok is True
        assert status == "sent"

        # Verify SMTP server lifecycle
        mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
        assert mock_server.starttls.called
        mock_server.login.assert_called_once_with("rurallearn.project@gmail.com", "abcdefghijklmnop")
        assert mock_server.send_message.called

        # Inspect sent email message
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["Subject"] == "Test Subject"
        assert sent_msg["To"] == "visitor@example.com"
        assert "rurallearn.project@gmail.com" in sent_msg["From"]
        assert "AI Receptionist" in sent_msg["From"]


def test_smtp_provider_error_handling_returns_failed():
    """Test that SMTP network/authentication errors are safely caught and return (False, 'failed')."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Invalid credentials")

    with patch("smtplib.SMTP", return_value=mock_server):
        provider = SMTPEmailProvider(
            host="smtp.gmail.com",
            port=587,
            from_email="rurallearn.project@gmail.com",
            user="rurallearn.project@gmail.com",
            password="badpassword",
        )
        ok, status = provider.send(
            to_email="visitor@example.com",
            subject="Test Subject",
            text_body="Plain text body",
        )
        assert ok is False
        assert status == "failed"


def test_get_email_provider_fallback_when_password_empty():
    """Ensure get_email_provider falls back to DevelopmentEmailProvider if password is empty/missing."""
    settings_no_pwd = Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="a" * 32,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="rurallearn.project@gmail.com",
        smtp_password="",  # Missing password
    )
    prov = get_email_provider(settings_no_pwd)
    assert isinstance(prov, DevelopmentEmailProvider)


def test_get_email_provider_returns_smtp_when_configured():
    """Ensure get_email_provider returns SMTPEmailProvider when password is provided."""
    settings_ready = Settings(
        database_url="sqlite:///:memory:",
        jwt_secret_key="a" * 32,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        smtp_user="rurallearn.project@gmail.com",
        smtp_password="validapppassword",
        app_name="AI Receptionist",
    )
    prov = get_email_provider(settings_ready)
    assert isinstance(prov, SMTPEmailProvider)
    assert prov.host == "smtp.gmail.com"
    assert prov.port == 587
    assert prov.password == "validapppassword"
    assert prov.display_name == "AI Receptionist"


def test_email_formatting_templates(org):
    """Verify that email templates format subjects, statuses, and badges accurately."""
    with SessionLocal() as db:
        appt = db.execute(select(Appointment).order_by(Appointment.id.desc())).scalars().first()
        if not appt:
            return

        # 1. Request Received template
        sub1, txt1, htm1 = format_appointment_email(appt, "AI Receptionist")
        assert f"Appointment Request Received - {appt.reference_code}" == sub1
        assert "Pending Staff Approval" in txt1
        assert "Pending Approval" in htm1

        # 2. Confirmation template
        sub2, txt2, htm2 = format_confirmation_email(appt, "AI Receptionist")
        assert f"Your Appointment Is Confirmed - {appt.reference_code}" == sub2
        assert "has been confirmed" in txt2
        assert "Confirmed" in htm2

        # 3. Rescheduled template
        sub3, txt3, htm3 = format_rescheduled_email(appt, "AI Receptionist")
        assert f"Your Appointment Has Been Rescheduled - {appt.reference_code}" == sub3
        assert "rescheduled to a new date and time" in txt3

        # 4. Cancellation template
        sub4, txt4, htm4 = format_cancellation_email(appt, "AI Receptionist", reason="Doctor unavailable")
        assert f"Appointment Cancelled - {appt.reference_code}" == sub4
        assert "Doctor unavailable" in txt4
        assert "Doctor unavailable" in htm4
        assert "Cancelled" in htm4


def test_guest_booking_sends_one_request_received_email(client, org, test_smtp_settings):
    """Requirement 1: Guest booking sends exactly one request-received email."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(3, 10)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Guest Requester",
                    phone="+919876543201",
                    email="guest.requester@example.com",
                )
                r = client.post("/api/public/appointments", json=payload)
                assert r.status_code == 201
                ref = r.json()["reference_code"]

                # Exactly one email sent
                assert mock_server.send_message.call_count == 1
                sent_msg = mock_server.send_message.call_args[0][0]
                assert sent_msg["Subject"] == f"Appointment Request Received - {ref}"
                assert sent_msg["To"] == "guest.requester@example.com"
                assert "Pending Staff Approval" in get_message_body(sent_msg)

                with SessionLocal() as db:
                    appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
                    assert appt.status == "pending"
                    assert appt.user_id is None
                    assert appt.email_status == "sent"


def test_registered_user_booking_sends_one_request_received_email(client, org, test_smtp_settings):
    """Requirement 2: Registered user booking sends one request-received email linked to user."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    reg = client.post("/api/auth/register", json={
        "email": "reg.user@example.com",
        "password": "Password123!",
        "full_name": "Registered User",
        "phone": "+919876543202",
    }).json()
    token = reg["access_token"]
    user_id = reg["user_id"]

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(3, 11)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Registered User",
                    phone="+919876543202",
                    email="reg.user@example.com",
                )
                r = client.post("/api/public/appointments", json=payload, headers={"Authorization": f"Bearer {token}"})
                assert r.status_code == 201
                ref = r.json()["reference_code"]

                # Exactly one email sent
                assert mock_server.send_message.call_count == 1
                sent_msg = mock_server.send_message.call_args[0][0]
                assert sent_msg["Subject"] == f"Appointment Request Received - {ref}"
                assert sent_msg["To"] == "reg.user@example.com"

                with SessionLocal() as db:
                    appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
                    assert appt.user_id == user_id
                    assert appt.status == "pending"
                    assert appt.email_status == "sent"


def test_pending_to_confirmed_sends_one_confirmation_email(client, org, admin_h, test_smtp_settings):
    """Requirement 3: Pending to Confirmed transition sends exactly one confirmation email."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(3, 12)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Confirm Visitor",
                    phone="+919876543203",
                    email="confirm.visitor@example.com",
                )
                book_res = client.post("/api/public/appointments", json=payload)
                assert book_res.status_code == 201
                ref = book_res.json()["reference_code"]

                with SessionLocal() as db:
                    appt_id = db.execute(select(Appointment.id).where(Appointment.reference_code == ref)).scalar_one()

                # Reset mock call count from initial booking
                mock_server.send_message.reset_mock()

                # Admin marks as confirmed
                patch_res = client.patch(f"/api/admin/appointments/{appt_id}/status", json={"status": "confirmed"}, headers=admin_h)
                assert patch_res.status_code == 200
                assert patch_res.json()["status"] == "confirmed"

                # Confirmation email was dispatched once
                assert mock_server.send_message.call_count == 1
                sent_msg = mock_server.send_message.call_args[0][0]
                assert sent_msg["Subject"] == f"Your Appointment Is Confirmed - {ref}"
                assert sent_msg["To"] == "confirm.visitor@example.com"
                body = get_message_body(sent_msg)
                assert "has been confirmed" in body
                assert ref in body

                with SessionLocal() as db:
                    appt = db.execute(select(Appointment).where(Appointment.id == appt_id)).scalar_one()
                    assert appt.status == "confirmed"
                    assert appt.email_status == "sent"


def test_editing_unrelated_fields_does_not_resend_confirmation(client, org, admin_h, test_smtp_settings):
    """Requirement 4: Editing unrelated appointment fields (like notes) does not resend confirmation."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(3, 14)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Unrelated Visitor",
                    phone="+919876543204",
                    email="unrelated.visitor@example.com",
                )
                book_res = client.post("/api/public/appointments", json=payload)
                ref = book_res.json()["reference_code"]

                with SessionLocal() as db:
                    appt_id = db.execute(select(Appointment.id).where(Appointment.reference_code == ref)).scalar_one()

                # Confirm appointment
                client.patch(f"/api/admin/appointments/{appt_id}/status", json={"status": "confirmed"}, headers=admin_h)

                # Reset mock calls after confirmation
                mock_server.send_message.reset_mock()

                # Admin updates notes on the already confirmed appointment
                update_notes_res = client.patch(
                    f"/api/admin/appointments/{appt_id}/status",
                    json={"status": "confirmed", "notes": "Visitor requested wheelchair access."},
                    headers=admin_h,
                )
                assert update_notes_res.status_code == 200

                # Crucial assertion: ZERO emails sent when editing notes
                assert mock_server.send_message.call_count == 0

                with SessionLocal() as db:
                    appt = db.execute(select(Appointment).where(Appointment.id == appt_id)).scalar_one()
                    assert appt.notes == "Visitor requested wheelchair access."
                    assert appt.status == "confirmed"


def test_repeating_same_status_update_does_not_send_duplicate_emails(client, org, admin_h, test_smtp_settings):
    """Requirement 5: Repeating the same status update does not send duplicate emails."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(3, 15)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Duplicate Check Visitor",
                    phone="+919876543205",
                    email="dup.visitor@example.com",
                )
                book_res = client.post("/api/public/appointments", json=payload)
                ref = book_res.json()["reference_code"]

                with SessionLocal() as db:
                    appt_id = db.execute(select(Appointment.id).where(Appointment.reference_code == ref)).scalar_one()

                # First confirm: sends 1 confirmation email
                mock_server.send_message.reset_mock()
                r1 = client.patch(f"/api/admin/appointments/{appt_id}/status", json={"status": "confirmed"}, headers=admin_h)
                assert r1.status_code == 200
                assert mock_server.send_message.call_count == 1

                # Repeat confirm: MUST NOT send another email
                mock_server.send_message.reset_mock()
                r2 = client.patch(f"/api/admin/appointments/{appt_id}/status", json={"status": "confirmed"}, headers=admin_h)
                assert r2.status_code == 200
                assert mock_server.send_message.call_count == 0


def test_email_failure_does_not_lose_appointment_or_corrupt_status(client, org, admin_h, test_smtp_settings):
    """Requirement 6: Email failure does not lose the appointment or corrupt its status."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server
    mock_server.send_message.side_effect = smtplib.SMTPException("SMTP Server Unreachable")

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(4, 10)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Resilient Visitor",
                    phone="+919876543206",
                    email="resilient.visitor@example.com",
                )
                # Booking succeeds despite email failure
                r = client.post("/api/public/appointments", json=payload)
                assert r.status_code == 201
                ref = r.json()["reference_code"]

                with SessionLocal() as db:
                    appt = db.execute(select(Appointment).where(Appointment.reference_code == ref)).scalar_one()
                    assert appt.status == "pending"
                    assert appt.email_status == "failed"
                    appt_id = appt.id

                # Now admin confirms with failing SMTP
                patch_res = client.patch(f"/api/admin/appointments/{appt_id}/status", json={"status": "confirmed"}, headers=admin_h)
                assert patch_res.status_code == 200
                assert patch_res.json()["status"] == "confirmed"

                # Appointment in database is reliably Confirmed, not lost or corrupted
                with SessionLocal() as db:
                    appt_after = db.execute(select(Appointment).where(Appointment.id == appt_id)).scalar_one()
                    assert appt_after.status == "confirmed"
                    assert appt_after.email_status == "failed"


def test_reschedule_and_cancellation_notifications(client, org, admin_h, test_smtp_settings):
    """Requirement 7: Rescheduling and cancellation notifications."""
    mock_server = MagicMock()
    mock_server.__enter__.return_value = mock_server

    with patch("smtplib.SMTP", return_value=mock_server):
        with patch("app.services.notification_service.get_settings", return_value=test_smtp_settings):
            with patch("app.services.appointment_service.get_settings", return_value=test_smtp_settings):
                slot = future_slot(4, 11)
                payload = booking_payload(
                    org["staff_ids"][0],
                    slot,
                    name="Reschedule Visitor",
                    phone="+919876543207",
                    email="resched.visitor@example.com",
                )
                book_res = client.post("/api/public/appointments", json=payload)
                ref = book_res.json()["reference_code"]

                with SessionLocal() as db:
                    appt_id = db.execute(select(Appointment.id).where(Appointment.reference_code == ref)).scalar_one()

                # Reschedule appointment
                new_slot = future_slot(4, 14)
                mock_server.send_message.reset_mock()
                resched_res = client.post(
                    f"/api/admin/appointments/{appt_id}/reschedule",
                    json={"start_at": new_slot.isoformat()},
                    headers=admin_h,
                )
                assert resched_res.status_code == 200

                # Reschedule email was sent
                assert mock_server.send_message.call_count == 1
                sent_msg = mock_server.send_message.call_args[0][0]
                assert sent_msg["Subject"] == f"Your Appointment Has Been Rescheduled - {ref}"
                body = get_message_body(sent_msg)
                assert "rescheduled to a new date and time" in body

                # Cancel appointment
                mock_server.send_message.reset_mock()
                cancel_res = client.post(
                    f"/api/admin/appointments/{appt_id}/cancel",
                    json={"reason": "Emergency maintenance"},
                    headers=admin_h,
                )
                assert cancel_res.status_code == 200

                # Cancellation email was sent
                assert mock_server.send_message.call_count == 1
                cancel_msg = mock_server.send_message.call_args[0][0]
                assert cancel_msg["Subject"] == f"Appointment Cancelled - {ref}"
                cancel_body = get_message_body(cancel_msg)
                assert "Emergency maintenance" in cancel_body
                assert "Cancelled" in cancel_body

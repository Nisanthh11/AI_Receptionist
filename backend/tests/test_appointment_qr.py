"""Unit and integration tests for appointment QR code generation and privacy guarantees."""
import base64
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Appointment
from app.services.qr_service import generate_appointment_qr_data_url
from tests.conftest import booking_payload, future_slot


def test_qr_service_generates_valid_png_data_uri():
    """Verify QR generator returns a valid base64-encoded PNG image data URI."""
    ref = "APT-QRTEST01"
    data_url = generate_appointment_qr_data_url(ref)

    assert data_url.startswith("data:image/png;base64,")
    encoded_b64 = data_url.removeprefix("data:image/png;base64,")
    raw_png = base64.b64decode(encoded_b64)

    # Standard PNG file header magic bytes
    assert raw_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw_png) > 50


def test_qr_service_empty_or_none_input_fallback():
    """Invalid or empty references return empty string without raising exceptions."""
    assert generate_appointment_qr_data_url("") == ""
    assert generate_appointment_qr_data_url("   ") == ""
    assert generate_appointment_qr_data_url(None) == ""


def test_qr_service_error_handling_fallback():
    """Exceptions during QR generation are caught and return empty string safely."""
    with patch("segno.make", side_effect=RuntimeError("Engine failure")):
        result = generate_appointment_qr_data_url("APT-ERR01")
        assert result == ""


def test_booking_api_returns_qr_code(client, org):
    """POST /api/public/appointments includes a valid QR code in the booking result."""
    slot = future_slot(3, 10)
    payload = booking_payload(
        org["staff_ids"][0],
        slot,
        name="Sunita Rao",
        phone="+919876543299",
        email="sunita@example.com",
    )
    resp = client.post("/api/public/appointments", json=payload)
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert "qr_code" in data
    assert data["qr_code"] is not None
    assert data["qr_code"].startswith("data:image/png;base64,")

    # Verify PNG magic bytes
    raw_png = base64.b64decode(data["qr_code"].removeprefix("data:image/png;base64,"))
    assert raw_png[:8] == b"\x89PNG\r\n\x1a\n"

    # Verify existing fields remain available
    assert data["reference_code"].startswith("APT-")
    assert data["status"] == "pending"
    assert data["staff_name"] == "Dr. Ravi"
    assert data["department_name"] == "Admissions"


def test_lookup_api_returns_qr_code(client, org):
    """POST /api/public/appointments/lookup includes the QR code for status checks."""
    slot = future_slot(3, 11)
    book_resp = client.post(
        "/api/public/appointments",
        json=booking_payload(
            org["staff_ids"][0], slot, name="Kiran V", phone="+919876543298"
        ),
    )
    ref = book_resp.json()["reference_code"]

    lookup_resp = client.post(
        "/api/public/appointments/lookup",
        json={"reference_code": ref, "phone": "+919876543298"},
    )
    assert lookup_resp.status_code == 200
    data = lookup_resp.json()
    assert "qr_code" in data
    assert data["qr_code"].startswith("data:image/png;base64,")


def test_qr_generation_failure_preserves_successful_booking(client, org):
    """If QR generation fails, the appointment is still safely saved and returned."""
    slot = future_slot(3, 12)
    payload = booking_payload(
        org["staff_ids"][0], slot, name="Fallback Visitor", phone="+919876543297"
    )

    with patch(
        "app.api.public.generate_appointment_qr_data_url", return_value=""
    ):
        resp = client.post("/api/public/appointments", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["qr_code"] is None
        assert data["reference_code"].startswith("APT-")

    # Verify appointment is still recorded in DB
    with SessionLocal() as db:
        saved = db.execute(
            select(Appointment).where(Appointment.reference_code == data["reference_code"])
        ).scalar_one_or_none()
        assert saved is not None


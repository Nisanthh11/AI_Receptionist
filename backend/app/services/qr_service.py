"""Appointment QR code generation service.

Generates privacy-preserving, high-contrast QR codes for appointments using Segno.
Contains only opaque appointment identifiers without exposing visitor PII, staff
credentials, or authorization secrets.
"""
from __future__ import annotations

import logging
from typing import Any

import segno

logger = logging.getLogger(__name__)


def generate_appointment_qr_data_url(
    reference_code: str,
    *,
    scale: int = 6,
    border: int = 2,
    error_correction: str = "M",
) -> str:
    """Generates a base64-encoded PNG data URI for an appointment reference code.

    Privacy & Security Rules:
    - Encodes ONLY the clean reference code (e.g. 'APT-1A2B3C4D').
    - Never includes visitor PII (name, phone, email, notes).
    - Never includes database IDs, secrets, or check-in authorization tokens.
    - Safe fallback: returns empty string if reference_code is invalid or generation fails.
    """
    ref = (reference_code or "").strip().upper()
    if not ref:
        return ""

    try:
        qr = segno.make(ref, error=error_correction)
        return qr.png_data_uri(scale=scale, border=border)
    except Exception as exc:
        logger.error("Failed to generate QR code for reference '%s': %s", ref, exc)
        return ""


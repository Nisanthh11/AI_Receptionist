from __future__ import annotations

import pytest
from app.core.database import SessionLocal
from app.models.appointment import Appointment
from app.services.chat_service import to_speech_text


def test_to_speech_text_formatting():
    """Verify markdown, links, codes, and emojis are formatted cleanly for voice synthesis."""
    raw = "Your appointment is confirmed! Reference code is **APT-1A2B3C4D**. Call +91-98765-43210. Visit [Website](http://example.com) - thanks! 😊"
    speech = to_speech_text(raw)
    assert "**" not in speech
    assert "😊" not in speech
    assert "[" not in speech
    assert "]" not in speech
    assert "APT-1A2B3C4D" not in speech
    assert "A P T dash 1 A 2 B 3 C 4 D" in speech
    assert "Website" in speech


def test_voice_session_creation(client, org):
    """Voice session init should return greeting, speech_text, and ready status."""
    res = client.post("/api/voice/session")
    assert res.status_code == 200
    data = res.json()
    assert "session_token" in data
    assert data["status"] == "ready"
    assert "Hello" in data["display_text"]
    assert len(data["speech_text"]) > 0


def test_voice_turn_general_faq(client, org):
    """User asks a question via voice turn and receives spoken answer."""
    sess_res = client.post("/api/voice/session")
    token = sess_res.json()["session_token"]

    turn_res = client.post(
        "/api/voice/turn",
        json={"session_token": token, "transcript": "Where can I park my vehicle?"},
    )
    assert turn_res.status_code == 200
    data = turn_res.json()
    assert "Park near the main gate" in data["reply_text"]
    assert "main gate" in data["speech_text"].lower()
    assert data["transfer_to_human"] is False


def test_voice_turn_human_escalation(client, org):
    """User requests a human receptionist; voice service signals transfer_to_human."""
    sess_res = client.post("/api/voice/session")
    token = sess_res.json()["session_token"]

    turn_res = client.post(
        "/api/voice/turn",
        json={"session_token": token, "transcript": "Can I please speak with a human receptionist right now?"},
    )
    assert turn_res.status_code == 200
    data = turn_res.json()
    assert data["transfer_to_human"] is True
    assert "reception" in data["speech_text"].lower() or "connect" in data["speech_text"].lower()


def test_voice_turn_conversational_booking_flow(client, org, admin_h):
    """Voice conversation books an appointment, persisting booking_source='browser_voice'."""
    sess_res = client.post("/api/voice/session")
    token = sess_res.json()["session_token"]

    def _turn(msg: str):
        r = client.post(
            "/api/voice/turn",
            json={"session_token": token, "transcript": msg, "channel": "browser_voice"},
        )
        assert r.status_code == 200, r.text
        return r.json()

    # Step 1: Intent
    r1 = _turn("I want to book an appointment")
    assert r1["booking_flow"]["step"] == "department"

    # Step 2: Department
    r2 = _turn("Admissions")
    assert r2["booking_flow"]["step"] == "staff"

    # Step 3: Staff
    r3 = _turn("Dr. Ravi")
    assert r3["booking_flow"]["step"] == "date"

    # Step 4: Date
    r4 = _turn("tomorrow")
    assert r4["booking_flow"]["step"] == "slot"
    assert "Available times include" in r4["speech_text"]

    # Step 5: Slot
    slot_to_pick = r4["suggestions"][0]
    r5 = _turn(slot_to_pick)
    assert r5["booking_flow"]["step"] == "visitor_name"

    # Step 6: Name
    r6 = _turn("John Voice")
    assert r6["booking_flow"]["step"] == "visitor_phone"

    # Step 7: Phone
    r7 = _turn("+919876543210")
    assert r7["booking_flow"]["step"] == "visitor_email"

    # Step 8: Email
    r8 = _turn("john.voice@example.com")
    assert r8["booking_flow"]["step"] == "visitor_purpose"

    # Step 9: Purpose
    r9 = _turn("Campus consultation")
    assert r9["booking_flow"]["step"] == "confirmation"

    # Step 10: Confirmation
    r10 = _turn("yes, please confirm")
    assert r10["action"] == "booking_completed"
    assert "recorded" in r10["reply_text"].lower() or "reference" in r10["reply_text"].lower()
    assert "A P T dash" in r10["speech_text"]

    # Verify in DB that booking_source is browser_voice and visitor is John Voice
    with SessionLocal() as db:
        appt = db.query(Appointment).filter(Appointment.booking_source == "browser_voice").first()
        assert appt is not None
        assert appt.booking_source == "browser_voice"
        assert appt.visitor.full_name == "John Voice"

    # Verify admin channel filter API retrieves it
    admin_res = client.get("/api/admin/appointments?booking_source=browser_voice", headers=admin_h)
    assert admin_res.status_code == 200
    admin_items = admin_res.json()["items"]
    assert any(a["visitor"]["full_name"] == "John Voice" for a in admin_items)


def test_voice_turn_validation_and_end(client, org):
    """Test session termination, reprompt on empty speech, and schema validation."""
    sess_res = client.post("/api/voice/session")
    token = sess_res.json()["session_token"]

    # Empty turn message returns polite reprompt
    r_empty = client.post("/api/voice/turn", json={"session_token": token, "transcript": "   "})
    assert r_empty.status_code == 200
    assert "repeat" in r_empty.json()["speech_text"].lower() or "hear" in r_empty.json()["speech_text"].lower()

    # Missing required field gives 422
    r_bad = client.post("/api/voice/turn", json={"transcript": "hello"})
    assert r_bad.status_code == 422

    # End session
    r_end = client.post("/api/voice/end", json={"session_token": token})
    assert r_end.status_code == 200
    assert r_end.json()["status"] == "ended"

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest
from app.core.database import SessionLocal
from app.models.appointment import Appointment
from app.telephony.twilio_adapter import TwilioVoiceAdapter


def test_twilio_adapter_methods(org):
    adapter = TwilioVoiceAdapter()
    with SessionLocal() as db:
        # Incoming call generates valid TwiML
        twiml = adapter.handle_incoming_call(
            caller_number="+919876543210",
            call_id="CA_unit_test_01",
            db=db,
        )
        root = ET.fromstring(twiml)
        assert root.tag == "Response"
        assert root.find("Say") is not None
        gather = root.find("Gather")
        assert gather is not None
        assert "/api/telephony/turn?session_token=" in gather.attrib["action"]
        assert gather.attrib["input"] == "speech"

        # Human transfer generates TwiML Dial
        transfer_xml = adapter.generate_human_transfer(
            destination_number="+919876543200",
            message="Please hold while I connect you with front desk reception.",
        )
        t_root = ET.fromstring(transfer_xml)
        assert t_root.find("Say") is not None
        dial = t_root.find("Dial")
        assert dial is not None
        assert dial.find("Number").text == "+919876543200"


def test_telephony_incoming_webhook(client, org):
    """Telephony incoming call webhook starts a session and returns initial TwiML."""
    res = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAtestcall001", "From": "+919876543210"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    assert "application/xml" in res.headers["content-type"]
    root = ET.fromstring(res.text)
    assert root.tag == "Response"
    gather = root.find("Gather")
    assert gather is not None
    assert "/api/telephony/turn?session_token=" in gather.attrib["action"]


def test_telephony_turn_speech_query(client, org):
    """Incoming speech input returns spoken answer and prompts for next turn."""
    inc_res = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAtestcall002", "From": "+919876543210"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    root = ET.fromstring(inc_res.text)
    gather_action = root.find("Gather").attrib["action"]

    turn_res = client.post(
        gather_action,
        data={"CallSid": "CAtestcall002", "SpeechResult": "Where can I park my vehicle?"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert turn_res.status_code == 200
    assert "application/xml" in turn_res.headers["content-type"]
    turn_root = ET.fromstring(turn_res.text)
    say_text = turn_root.find("Say").text
    assert "main gate" in say_text.lower()


def test_telephony_turn_human_transfer(client, org):
    """User asks for a human; telephony adapter dials receptionist extension."""
    inc_res = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAtestcall003", "From": "+919876543210"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    root = ET.fromstring(inc_res.text)
    gather_action = root.find("Gather").attrib["action"]

    turn_res = client.post(
        gather_action,
        data={"CallSid": "CAtestcall003", "SpeechResult": "Transfer me to a human receptionist please"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert turn_res.status_code == 200
    turn_root = ET.fromstring(turn_res.text)
    dial = turn_root.find("Dial")
    assert dial is not None
    assert dial.find("Number") is not None


def test_telephony_booking_persists_telephone_source(client, org, admin_h):
    """Booking through telephony channel creates appointment with booking_source='telephone'."""
    inc_res = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAtestcall004", "From": "+919876543210"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    action = ET.fromstring(inc_res.text).find("Gather").attrib["action"]

    def _telephony_turn(curr_action: str, speech: str) -> str:
        r = client.post(
            curr_action,
            data={"CallSid": "CAtestcall004", "SpeechResult": speech},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200, r.text
        parsed = ET.fromstring(r.text)
        gather_el = parsed.find("Gather")
        return gather_el.attrib["action"] if gather_el is not None else ""

    # Follow the full conversational state machine through speech:
    a1 = _telephony_turn(action, "I want to book an appointment")
    a2 = _telephony_turn(a1, "Admissions")
    a3 = _telephony_turn(a2, "Dr. Ravi")
    a4 = _telephony_turn(a3, "tomorrow")
    a5 = _telephony_turn(a4, "09:00 AM")
    a6 = _telephony_turn(a5, "Caller Bob")
    a7 = _telephony_turn(a6, "+919876543212")
    a8 = _telephony_turn(a7, "caller.bob@example.com")
    a9 = _telephony_turn(a8, "General inquiry")

    # Final confirmation turn
    final_res = client.post(
        a9,
        data={"CallSid": "CAtestcall004", "SpeechResult": "yes, confirm appointment"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert final_res.status_code == 200
    final_root = ET.fromstring(final_res.text)
    say_text = final_root.find("Say").text
    assert "reference" in say_text.lower() or "recorded" in say_text.lower() or "received" in say_text.lower()
    assert final_root.find("Hangup") is not None

    # Verify DB appointment has booking_source == 'telephone' and visitor name 'Caller Bob'
    with SessionLocal() as db:
        appt = db.query(Appointment).filter(Appointment.booking_source == "telephone").first()
        assert appt is not None
        assert appt.booking_source == "telephone"
        assert appt.visitor.full_name == "Caller Bob"

    # Verify admin channel filter API retrieves it
    admin_res = client.get("/api/admin/appointments?booking_source=telephone", headers=admin_h)
    assert admin_res.status_code == 200
    assert any(a["visitor"]["full_name"] == "Caller Bob" for a in admin_res.json()["items"])


def test_telephony_status_callback(client):
    """Status callback cleans up call session."""
    res = client.post(
        "/api/telephony/status?session_token=sess-dummy",
        data={"CallSid": "CAtestcall005", "CallStatus": "completed"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "recorded"
    assert res.json()["call_status"] == "completed"


def test_telephony_cancellation_by_reference_code(client, org):
    """Caller can cancel an existing appointment over the phone by quoting reference code."""
    # First book an appointment
    inc_res = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAcancel01", "From": "+919876543220"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    action = ET.fromstring(inc_res.text).find("Gather").attrib["action"]

    def _telephony_turn(curr_action: str, speech: str) -> str:
        r = client.post(
            curr_action,
            data={"CallSid": "CAcancel01", "SpeechResult": speech},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        assert r.status_code == 200, r.text
        parsed = ET.fromstring(r.text)
        gather_el = parsed.find("Gather")
        return gather_el.attrib["action"] if gather_el is not None else ""

    a1 = _telephony_turn(action, "book appointment")
    a2 = _telephony_turn(a1, "Admissions")
    a3 = _telephony_turn(a2, "Dr. Ravi")
    a4 = _telephony_turn(a3, "tomorrow")
    a5 = _telephony_turn(a4, "09:00 AM")
    a6 = _telephony_turn(a5, "Alice Smith")
    a7 = _telephony_turn(a6, "+919876543220")
    a8 = _telephony_turn(a7, "skip")
    a9 = _telephony_turn(a8, "Consultation")
    fin = client.post(
        a9,
        data={"CallSid": "CAcancel01", "SpeechResult": "confirm"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert fin.status_code == 200
    with SessionLocal() as db:
        appt = db.query(Appointment).filter(Appointment.booking_source == "telephone").first()
        assert appt is not None
        ref_code = appt.reference_code

    # New call from the caller requesting cancellation with reference code
    call2 = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAcancel02", "From": "+919876543220"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    action2 = ET.fromstring(call2.text).find("Gather").attrib["action"]

    cancel_turn = client.post(
        action2,
        data={"CallSid": "CAcancel02", "SpeechResult": f"Please cancel my appointment {ref_code}"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert cancel_turn.status_code == 200
    cancel_xml = ET.fromstring(cancel_turn.text)
    gather_el = cancel_xml.find("Gather")
    assert gather_el is not None
    next_action = gather_el.attrib["action"]

    # Confirm cancellation
    confirm_turn = client.post(
        next_action,
        data={"CallSid": "CAcancel02", "SpeechResult": "yes, cancel it"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert confirm_turn.status_code == 200
    confirm_xml = ET.fromstring(confirm_turn.text)
    say_text = "".join(confirm_xml.itertext())
    assert "cancelled" in say_text.lower()
    assert confirm_xml.find("Hangup") is not None

    with SessionLocal() as db:
        updated = db.query(Appointment).filter(Appointment.reference_code == ref_code).first()
        assert updated.status == "cancelled"
        assert updated.slot_key is None
        assert "telephone" in (updated.cancelled_reason or "").lower()


def test_telephony_silence_escalation(client, org):
    """Multiple silences escalate from reprompt to graceful termination or human transfer."""
    inc = client.post(
        "/api/telephony/incoming",
        data={"CallSid": "CAsilence01", "From": "+919876543230"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    action = ET.fromstring(inc.text).find("Gather").attrib["action"]

    # 1st silence -> reprompt
    s1 = client.post(action, data={"CallSid": "CAsilence01", "SpeechResult": ""})
    assert s1.status_code == 200
    root1 = ET.fromstring(s1.text)
    assert root1.find("Gather") is not None
    assert "repeat" in "".join(root1.itertext()).lower()

    # 2nd silence -> reprompt
    s2 = client.post(action, data={"CallSid": "CAsilence01", "SpeechResult": "   "})
    assert s2.status_code == 200
    root2 = ET.fromstring(s2.text)
    assert root2.find("Gather") is not None

    # 3rd silence -> max silence reached: transfers to reception or hangs up
    s3 = client.post(action, data={"CallSid": "CAsilence01", "SpeechResult": ""})
    assert s3.status_code == 200
    root3 = ET.fromstring(s3.text)
    assert root3.find("Dial") is not None or root3.find("Hangup") is not None


def test_telephony_failed_transfer_webhook(client):
    """Twilio /transfer-status callback gracefully handles busy/failed receptionist transfer."""
    res = client.post(
        "/api/telephony/transfer-status",
        data={"CallSid": "CAtransferfail01", "DialCallStatus": "busy"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    assert root.find("Hangup") is not None
    assert "unable to take your call" in "".join(root.itertext()).lower()


def test_telephony_signature_validation(client, monkeypatch):
    """Validates X-Twilio-Signature verification behavior when enabled."""
    import base64, hashlib, hmac
    from app.core.config import get_settings
    from app.telephony.twilio_adapter import validate_twilio_request

    auth_token = "secret-twilio-token-12345"
    url = "http://testserver/api/telephony/status"
    params = {"CallSid": "CAtestsign", "CallStatus": "completed"}

    # Generate genuine HMAC signature
    valid_sig = validate_twilio_request(auth_token, url, params, "dummy")
    assert not valid_sig  # dummy is invalid

    data = url + "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    genuine_sig = base64.b64encode(hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1).digest()).decode("utf-8")
    assert validate_twilio_request(auth_token, url, params, genuine_sig)

    # Enable signature validation in settings
    settings = get_settings()
    monkeypatch.setattr(settings, "twilio_validate_signature", True)
    monkeypatch.setattr(settings, "twilio_auth_token", auth_token)

    # Request without header should be rejected 403
    r_no_sig = client.post("/api/telephony/status", data=params)
    assert r_no_sig.status_code == 403

    # Request with invalid header should be rejected 403
    r_bad_sig = client.post("/api/telephony/status", data=params, headers={"X-Twilio-Signature": "invalid-sig"})
    assert r_bad_sig.status_code == 403


def test_telephony_config_endpoint(client):
    """GET /api/telephony/config returns structured status without exposing secrets."""
    res = client.get("/api/telephony/config")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "twilio"
    assert "ready_for_live_calls" in data
    assert "auth_token" not in data

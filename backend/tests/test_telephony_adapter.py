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

"""Unit and integration tests for VoiceLink Call Event API endpoint (POST /api/telephony/voicelink/events)."""
from __future__ import annotations

import logging
import pytest
from app.core.config import get_settings
from app.telephony.voicelink_adapter import _mask_phone
from app.api.telephony_voicelink import normalize_voicelink_call_event, VoiceLinkCallEvent


def test_mask_phone_utility():
    """Validates phone-number masking for privacy-compliant logging."""
    # Standard 10-12 digit numbers
    assert _mask_phone("+919876543210") == "+91****10"
    assert _mask_phone("9876543210") == "987****10"
    assert _mask_phone("+17372508034") == "+17****34"

    # Short numbers / extensions
    assert _mask_phone("1234") == "****"
    assert _mask_phone("12") == "****"

    # Empty / None
    assert _mask_phone(None) == "none"
    assert _mask_phone("") == "none"


def test_normalize_voicelink_call_event_aliases():
    """Verifies normalization of common VoiceLink parameter aliases and synonyms for backward compatibility."""
    # Case 1: Standard parameter mapping with event_type, unique_id, customer_number, virtual_number
    data1 = {
        "event_type": "in-progress",
        "unique_id": "vl_call_101",
        "customer_number": "+919876543210",
        "virtual_number": "+918012345678",
        "call_type": "inbound",
        "duration": "125",
        "hangup_cause": "NORMAL_CLEARING",
        "recording_path": "https://storage.voicelink.in/rec/101.wav",
    }
    event1 = normalize_voicelink_call_event(data1)
    assert event1.event == "answered"  # in-progress synonym
    assert event1.call_id == "vl_call_101"
    assert event1.customer_number == "+919876543210"
    assert event1.virtual_number == "+918012345678"
    assert event1.call_type == "inbound"
    assert event1.duration == 125
    assert event1.hangup_cause == "NORMAL_CLEARING"
    assert event1.recording_path == "https://storage.voicelink.in/rec/101.wav"

    # Case 2: Status, call_id, from, did, direction, billsec, disconnect_reason, recording_url
    data2 = {
        "status": "hangup",
        "call_id": "vl_call_202",
        "from": "+919123456789",
        "did": "+918099998888",
        "direction": "INBOUND",
        "billsec": "45.8",
        "disconnect_reason": "USER_BUSY",
        "recording_url": "https://storage.voicelink.in/rec/202.wav",
    }
    event2 = normalize_voicelink_call_event(data2)
    assert event2.event == "completed"  # hangup synonym
    assert event2.call_id == "vl_call_202"
    assert event2.customer_number == "+919123456789"
    assert event2.virtual_number == "+918099998888"
    assert event2.call_type == "inbound"
    assert event2.duration == 46  # 45.8 rounded
    assert event2.hangup_cause == "USER_BUSY"
    assert event2.recording_path == "https://storage.voicelink.in/rec/202.wav"


def test_normalize_voicelink_exact_documented_fields():
    """Verifies normalization of the exact fields documented by VoiceLink India."""
    exact_payload = {
        "event": "call.completed",
        "callId": "vl_call_exact_001",
        "fromNumber": "+919876543210",
        "toNumber": "+918012345678",
        "direction": "inbound",
        "callStatus": "completed",
        "duration": 58,
        "recordingUrl": "https://storage.voicelink.in/recordings/call_exact_001.mp3",
        "customParameters": {
            "campaignId": "camp_99",
            "agent": "virtual_receptionist",
        },
    }

    event = normalize_voicelink_call_event(exact_payload)
    assert event.event == "call.completed"
    assert event.original_event == "call.completed"
    assert event.call_id == "vl_call_exact_001"
    assert event.customer_number == "+919876543210"
    assert event.virtual_number == "+918012345678"
    assert event.call_type == "inbound"
    assert event.call_status == "completed"
    assert event.duration == 58
    assert event.recording_path == "https://storage.voicelink.in/recordings/call_exact_001.mp3"
    assert event.custom_parameters == {"campaignId": "camp_99", "agent": "virtual_receptionist"}


def test_events_endpoint_each_documented_event_name(client, monkeypatch):
    """Verifies that all 4 documented VoiceLink events receive HTTP 200 with correct event acknowledgment."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "")

    documented_events = [
        ("call.initiated", "ringing"),
        ("call.answered", "in_progress"),
        ("call.ended", "ended"),
        ("call.completed", "completed"),
    ]

    for evt_name, c_status in documented_events:
        payload = {
            "event": evt_name,
            "callStatus": c_status,
            "callId": f"id_{evt_name.replace('.', '_')}",
            "fromNumber": "+919876543210",
            "toNumber": "+918012345678",
            "direction": "inbound",
            "duration": 30 if "ended" in evt_name or "completed" in evt_name else 0,
            "recordingUrl": "https://storage.voicelink.in/rec.mp3" if "completed" in evt_name else None,
        }
        res = client.post("/api/telephony/voicelink/events", json=payload)
        assert res.status_code == 200, f"Failed for event {evt_name}"
        data = res.json()
        assert data["status"] == "ok"
        # Critical verification: event must match the event name, NOT the callStatus
        assert data["event"] == evt_name
        assert data["call_status"] == c_status
        assert data["call_id"] == payload["callId"]
        assert data["customer_number"] == "+91****10"
        assert data["virtual_number"] == "+91****78"


def test_events_endpoint_auth_enforcement_and_methods(client, monkeypatch):
    """Enforces authentication when VOICELINK_WEBHOOK_SECRET is set via header, bearer, and query params."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "secret-key-xyz-789")

    payload = {
        "event": "call.initiated",
        "callId": "call_test_auth_01",
        "fromNumber": "+919876543210",
        "toNumber": "+918012345678",
        "callStatus": "ringing",
    }

    # 1. Missing auth credentials -> 401
    res_no_auth = client.post("/api/telephony/voicelink/events", json=payload)
    assert res_no_auth.status_code == 401
    assert res_no_auth.json()["detail"] == "Unauthorized"

    # 2. Invalid auth token -> 401
    res_bad_auth = client.post(
        "/api/telephony/voicelink/events",
        json=payload,
        headers={"x-voicelink-secret": "wrong-secret-token"},
    )
    assert res_bad_auth.status_code == 401

    # 3. Valid X-VoiceLink-Secret header -> 200
    res_header = client.post(
        "/api/telephony/voicelink/events",
        json=payload,
        headers={"x-voicelink-secret": "secret-key-xyz-789"},
    )
    assert res_header.status_code == 200
    assert res_header.json()["status"] == "ok"
    assert res_header.json()["event"] == "call.initiated"
    assert res_header.json()["call_id"] == "call_test_auth_01"

    # 4. Valid Authorization: Bearer header -> 200
    res_bearer = client.post(
        "/api/telephony/voicelink/events",
        json=payload,
        headers={"authorization": "Bearer secret-key-xyz-789"},
    )
    assert res_bearer.status_code == 200
    assert res_bearer.json()["event"] == "call.initiated"

    # 5. Valid query param (?token=...) -> 200
    res_query = client.post(
        "/api/telephony/voicelink/events?token=secret-key-xyz-789",
        json=payload,
    )
    assert res_query.status_code == 200
    assert res_query.json()["event"] == "call.initiated"

    # 6. Valid query param (?secret=...) -> 200
    res_query_secret = client.post(
        "/api/telephony/voicelink/events?secret=secret-key-xyz-789",
        json=payload,
    )
    assert res_query_secret.status_code == 200


def test_events_endpoint_production_unconfigured_secret_rejected(client, monkeypatch):
    """Rejects event webhooks in production if VOICELINK_WEBHOOK_SECRET is unconfigured."""
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "")

    payload = {"event": "call.answered", "callId": "call_prod_01"}
    res = client.post("/api/telephony/voicelink/events", json=payload)
    assert res.status_code == 401


def test_events_endpoint_json_payload_handling(client, monkeypatch):
    """Accepts valid JSON payloads with documented VoiceLink fields."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "")

    payload = {
        "event": "call.completed",
        "callId": "vl-json-exact-001",
        "fromNumber": "+919876543210",
        "toNumber": "+918012345678",
        "direction": "inbound",
        "callStatus": "completed",
        "duration": 42,
        "recordingUrl": "https://storage.voicelink.in/rec/exact-001.mp3",
        "customParameters": {"dept": "cardiology"},
    }
    res = client.post("/api/telephony/voicelink/events", json=payload)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["event"] == "call.completed"
    assert body["call_id"] == "vl-json-exact-001"
    assert body["customer_number"] == "+91****10"
    assert body["virtual_number"] == "+91****78"
    assert body["duration"] == 42
    assert body["call_status"] == "completed"
    assert body["recording_url"] == "https://storage.voicelink.in/rec/exact-001.mp3"
    assert body["received"] is True


def test_events_endpoint_form_payload_handling(client, monkeypatch):
    """Accepts valid application/x-www-form-urlencoded payloads."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "")

    form_data = {
        "event": "call.completed",
        "callId": "vl-form-exact-002",
        "fromNumber": "+919123456789",
        "toNumber": "+918099887766",
        "direction": "inbound",
        "callStatus": "completed",
        "duration": "72",
        "recordingUrl": "https://storage.voicelink.in/rec/form-002.mp3",
    }
    res = client.post(
        "/api/telephony/voicelink/events",
        data=form_data,
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["event"] == "call.completed"
    assert body["call_id"] == "vl-form-exact-002"
    assert body["customer_number"] == "+91****89"
    assert body["virtual_number"] == "+91****66"
    assert body["duration"] == 72
    assert body["call_status"] == "completed"
    assert body["recording_url"] == "https://storage.voicelink.in/rec/form-002.mp3"
    assert body["received"] is True


def test_events_endpoint_malformed_payload_rejection(client, monkeypatch):
    """Rejects malformed JSON, empty bodies, and non-object payloads with 400 Bad Request."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "")

    # 1. Invalid JSON syntax
    res1 = client.post(
        "/api/telephony/voicelink/events",
        content="{\"event\": invalid-syntax",
        headers={"content-type": "application/json"},
    )
    assert res1.status_code == 400

    # 2. JSON array instead of object
    res2 = client.post(
        "/api/telephony/voicelink/events",
        json=[{"event": "call.initiated"}],
    )
    assert res2.status_code == 400

    # 3. Missing event/status field
    res3 = client.post(
        "/api/telephony/voicelink/events",
        json={"callId": "call_without_event", "fromNumber": "+919876543210"},
    )
    assert res3.status_code == 400
    assert "Missing required event field" in res3.json()["detail"]


def test_events_logging_masks_phone_and_never_leaks_secret(client, monkeypatch, caplog):
    """Verifies that call event logging masks phone numbers and never logs the webhook secret."""
    settings = get_settings()
    secret = "super-secret-telephony-token-999"
    monkeypatch.setattr(settings, "voicelink_webhook_secret", secret)

    customer_phone = "+919876543210"
    virtual_did = "+918012345678"

    payload = {
        "event": "call.initiated",
        "callId": "call_audit_logger_01",
        "fromNumber": customer_phone,
        "toNumber": virtual_did,
        "callStatus": "ringing",
    }

    with caplog.at_level(logging.INFO):
        res = client.post(
            "/api/telephony/voicelink/events",
            json=payload,
            headers={"x-voicelink-secret": secret},
        )
        assert res.status_code == 200

    all_logs = " ".join([rec.message for rec in caplog.records])

    # 1. Full customer phone must NEVER appear in logs
    assert customer_phone not in all_logs
    # 2. Full virtual DID must NEVER appear in logs
    assert virtual_did not in all_logs
    # 3. Secret must NEVER appear in logs
    assert secret not in all_logs
    # 4. Masked phone number must be present
    assert "+91****10" in all_logs

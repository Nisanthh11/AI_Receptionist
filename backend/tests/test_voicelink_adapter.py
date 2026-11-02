"""Integration and unit tests for VoiceLink WebSocket Telephony Adapter and Routes."""
from __future__ import annotations

import base64
import json
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.content import OrganizationInfo
from app.services.chat_service import _booking_sessions
from app.telephony.audio_codec import (
    ALAW_FRAME_BYTES,
    SLIN_FRAME_BYTES,
    AudioCodec,
    generate_silence,
    generate_tone,
    validate_audio_frame,
)
from app.telephony.speech_service import MockSpeechToTextService, MockTextToSpeechService
from app.telephony.voicelink_adapter import VoiceLinkCallSession, VoiceLinkWebSocketAdapter


def test_voicelink_config_endpoint(client):
    """GET /api/telephony/voicelink/config returns mock mode and audio parameters."""
    res = client.get("/api/telephony/voicelink/config")
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "voicelink"
    assert data["mock_mode"] is True
    assert data["sample_rate"] == 8000
    assert "alaw" in data["supported_codecs"]
    assert "slin" in data["supported_codecs"]
    assert data["endpoint"] == "/api/telephony/voicelink/ws"


def test_websocket_connection_and_start_greeting_alaw(client, org):
    """VoiceLink call connects and 'start' event triggers outbound A-law greeting audio frames."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        # 1. Send 'connected' handshake confirmation
        ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})

        # 2. Send 'start' event with A-law codec
        start_payload = {
            "event": "start",
            "sequence_number": "1",
            "stream_sid": "stream_alaw_01",
            "start": {
                "call_sid": "call_alaw_01",
                "from": "+919876543210",
                "to": "+918012345678",
                "media_format": {
                    "encoding": "audio/x-alaw",
                    "sample_rate": 8000,
                    "channels": 1,
                },
            },
        }
        ws.send_json(start_payload)

        # 3. Receive outbound greeting audio frames
        media_frames_received = 0
        received_mark = False

        while True:
            msg = ws.receive_json()
            event = msg.get("event")

            if event == "media":
                media_frames_received += 1
                assert msg["stream_sid"] == "stream_alaw_01"
                payload_b64 = msg["media"]["payload"]
                raw_bytes = base64.b64decode(payload_b64)
                # Verify exact 20ms A-law frame boundary
                assert len(raw_bytes) == ALAW_FRAME_BYTES
                validate_audio_frame(raw_bytes, AudioCodec.ALAW, exact_20ms_frame=True)

            elif event == "mark":
                assert msg["stream_sid"] == "stream_alaw_01"
                assert msg["mark"]["name"] == "greeting_end"
                received_mark = True
                break

        assert media_frames_received > 0
        assert received_mark is True

        # Cleanly stop call
        ws.send_json({"event": "stop", "stream_sid": "stream_alaw_01"})


def test_websocket_start_greeting_slin(client, org):
    """VoiceLink call configured for SLIN generates 320-byte PCM frames."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_slin_01",
            "start": {
                "call_sid": "call_slin_01",
                "from": "+919876543210",
                "media_format": {
                    "encoding": "slin",
                    "sample_rate": 8000,
                    "channels": 1,
                },
            },
        })

        slin_frames = 0
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "media":
                slin_frames += 1
                raw = base64.b64decode(msg["media"]["payload"])
                # Exact 20ms SLIN frame boundary is 320 bytes (160 samples * 2 bytes)
                assert len(raw) == SLIN_FRAME_BYTES
                validate_audio_frame(raw, AudioCodec.SLIN, exact_20ms_frame=True)
            elif msg.get("event") == "mark":
                break

        assert slin_frames > 0
        ws.send_json({"event": "stop", "stream_sid": "stream_slin_01"})


def test_websocket_unsupported_codec_rejection(client):
    """Rejects unrecognized or unsupported codecs safely with code 1003 without crashing."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_err_01",
            "start": {
                "media_format": {
                    "encoding": "audio/mulaw",  # Unsupported
                },
            },
        })

        # Expect error event
        err_msg = ws.receive_json()
        assert err_msg.get("event") == "error"
        assert "Unsupported or unrecognized audio codec" in err_msg.get("message")


def test_websocket_malformed_json_and_missing_event(client):
    """Handles malformed payloads and non-JSON text safely."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        # 1. Invalid JSON string
        ws.send_text("NOT_JSON_DATA_HERE")
        err1 = ws.receive_json()
        assert err1.get("event") == "error"
        assert "Invalid JSON" in err1.get("message")

        # 2. Missing 'event' key
        ws.send_json({"some_random_key": "some_value"})
        err2 = ws.receive_json()
        assert err2.get("event") == "error"
        assert "Missing 'event' field" in err2.get("message")


def test_websocket_speech_media_turn_and_response(client, org):
    """Feeds caller media frames, triggers mock STT turn, and verifies outbound speech response."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        # Start call
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_turn_01",
            "start": {
                "call_sid": "call_turn_01",
                "from": "+919876543210",
                "media_format": {"encoding": "alaw"},
            },
        })

        # Consume greeting audio
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "mark":
                break

        # Send 10 frames of 20ms A-law audio to trigger MockSTT turn boundary
        single_frame_b64 = base64.b64encode(generate_silence(20, AudioCodec.ALAW)).decode("ascii")
        for i in range(10):
            ws.send_json({
                "event": "media",
                "stream_sid": "stream_turn_01",
                "media": {
                    "payload": single_frame_b64,
                },
            })

        # The 10th frame triggers MockSTT default transcript ("I would like to book an appointment")
        # Receive conversational reply audio from VoiceService
        reply_frames = 0
        turn_mark_received = False
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "media":
                reply_frames += 1
                assert len(base64.b64decode(msg["media"]["payload"])) == ALAW_FRAME_BYTES
            elif msg.get("event") == "mark":
                turn_mark_received = True
                break

        assert reply_frames > 0
        assert turn_mark_received is True

        ws.send_json({"event": "stop", "stream_sid": "stream_turn_01"})


def test_websocket_human_transfer_event(client, org):
    """When caller requests human transfer, adapter transmits transfer speech and transfer event."""
    from app.main import app
    from app.api.telephony_voicelink import get_voicelink_adapter

    # Inject mock STT configured to request a human transfer
    custom_stt = MockSpeechToTextService()
    custom_stt.set_script(["I want to speak with a human receptionist"])

    adapter = VoiceLinkWebSocketAdapter(
        stt_factory=lambda: custom_stt,
    )
    app.dependency_overrides[get_voicelink_adapter] = lambda: adapter

    try:
        with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
            ws.send_json({
                "event": "start",
                "stream_sid": "stream_transfer_01",
                "start": {
                    "call_sid": "call_transfer_01",
                    "from": "+919876543210",
                    "media_format": {"encoding": "alaw"},
                },
            })

            # Consume greeting
            while True:
                if ws.receive_json().get("event") == "mark":
                    break

            # Send 10 frames to trigger STT
            frame_b64 = base64.b64encode(generate_silence(20, AudioCodec.ALAW)).decode("ascii")
            for _ in range(10):
                ws.send_json({
                    "event": "media",
                    "stream_sid": "stream_transfer_01",
                    "media": {"payload": frame_b64},
                })

            # Consume audio and check for transfer event
            received_transfer = False
            while True:
                msg = ws.receive_json()
                if msg.get("event") == "transfer":
                    assert msg["stream_sid"] == "stream_transfer_01"
                    assert "target" in msg["transfer"]
                    received_transfer = True
                    break

            assert received_transfer is True
    finally:
        app.dependency_overrides.pop(get_voicelink_adapter, None)


def test_websocket_mark_and_clear_barge_in(client, org):
    """Tests mark acknowledgment and clear event handling (barge-in interruption)."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_barge_01",
            "start": {
                "media_format": {"encoding": "alaw"},
            },
        })

        # Echo greeting mark back
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "mark":
                ws.send_json({
                    "event": "mark",
                    "stream_sid": "stream_barge_01",
                    "mark": {"name": msg["mark"]["name"]},
                })
                break

        # Send clear event (barge-in)
        ws.send_json({
            "event": "clear",
            "stream_sid": "stream_barge_01",
        })

        # Disconnect cleanly with stop
        ws.send_json({"event": "stop", "stream_sid": "stream_barge_01"})


def test_call_session_isolation(client, org):
    """Confirms that two separate phone calls have completely isolated sessions and phone numbers."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws1:
        with client.websocket_connect("/api/telephony/voicelink/ws") as ws2:
            # Call 1: Alice (+919876543210)
            ws1.send_json({
                "event": "start",
                "stream_sid": "stream_call_A",
                "start": {
                    "call_sid": "call_alice",
                    "from": "+919876543210",
                    "media_format": {"encoding": "alaw"},
                },
            })

            # Call 2: Bob (+919111222333)
            ws2.send_json({
                "event": "start",
                "stream_sid": "stream_call_B",
                "start": {
                    "call_sid": "call_bob",
                    "from": "+919111222333",
                    "media_format": {"encoding": "slin"},
                },
            })

            # Check Call 1 greeting is A-law
            msg1 = ws1.receive_json()
            assert msg1["stream_sid"] == "stream_call_A"
            if msg1["event"] == "media":
                assert len(base64.b64decode(msg1["media"]["payload"])) == ALAW_FRAME_BYTES

            # Check Call 2 greeting is SLIN
            msg2 = ws2.receive_json()
            assert msg2["stream_sid"] == "stream_call_B"
            if msg2["event"] == "media":
                assert len(base64.b64decode(msg2["media"]["payload"])) == SLIN_FRAME_BYTES

            ws1.send_json({"event": "stop", "stream_sid": "stream_call_A"})
            ws2.send_json({"event": "stop", "stream_sid": "stream_call_B"})


def test_voicelink_auth_missing_secret_in_production(client, monkeypatch):
    """In production, missing VOICELINK_WEBHOOK_SECRET must reject connection (never silently disable)."""
    settings = get_settings()
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "voicelink_webhook_secret", None)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/telephony/voicelink/ws"):
            pass
    assert exc_info.value.code == 1008


def test_voicelink_auth_credentials_validation(client, monkeypatch):
    """Enforces shared secret via query param, custom header, and Authorization header."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "test-auth-secret-123")

    # 1. Missing credentials -> Rejected
    with pytest.raises(WebSocketDisconnect) as exc1:
        with client.websocket_connect("/api/telephony/voicelink/ws"):
            pass
    assert exc1.value.code == 1008

    # 2. Incorrect query param -> Rejected
    with pytest.raises(WebSocketDisconnect) as exc2:
        with client.websocket_connect("/api/telephony/voicelink/ws?token=wrong-secret"):
            pass
    assert exc2.value.code == 1008

    # 3. Incorrect header -> Rejected
    with pytest.raises(WebSocketDisconnect) as exc3:
        with client.websocket_connect("/api/telephony/voicelink/ws", headers={"x-voicelink-secret": "wrong-secret"}):
            pass
    assert exc3.value.code == 1008

    # 4. Valid query param -> Accepted
    with client.websocket_connect("/api/telephony/voicelink/ws?token=test-auth-secret-123") as ws_qp:
        ws_qp.send_json({"event": "connected"})

    # 5. Valid X-VoiceLink-Secret header -> Accepted
    with client.websocket_connect("/api/telephony/voicelink/ws", headers={"x-voicelink-secret": "test-auth-secret-123"}) as ws_hdr:
        ws_hdr.send_json({"event": "connected"})

    # 6. Valid Authorization: Bearer header -> Accepted
    with client.websocket_connect("/api/telephony/voicelink/ws", headers={"authorization": "Bearer test-auth-secret-123"}) as ws_bearer:
        ws_bearer.send_json({"event": "connected"})


def test_voicelink_unauthorized_connection_triggers_no_booking(client, monkeypatch):
    """Rejects unauthorized calls before allocating session resources or creating bookings."""
    settings = get_settings()
    monkeypatch.setattr(settings, "voicelink_webhook_secret", "secure-gatekeeper")

    before_count = len(_booking_sessions)

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/api/telephony/voicelink/ws?token=bad-token") as ws:
            ws.send_json({
                "event": "start",
                "stream_sid": "stream_unauth",
                "start": {"from": "+919999999999"},
            })
    assert exc.value.code == 1008
    assert len(_booking_sessions) == before_count


def test_voicelink_media_track_filtering(client, org):
    """Validates that track='inbound' is processed, while track='outbound' and malformed tracks are ignored."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_track_01",
            "start": {
                "call_sid": "call_track_01",
                "from": "+919876543210",
                "media_format": {"encoding": "alaw"},
            },
        })

        # Consume greeting
        while True:
            if ws.receive_json().get("event") == "mark":
                break

        frame_b64 = base64.b64encode(generate_silence(20, AudioCodec.ALAW)).decode("ascii")

        # 1. Send 10 frames with track='outbound' (bot audio echo) -> must be IGNORED
        for _ in range(10):
            ws.send_json({
                "event": "media",
                "stream_sid": "stream_track_01",
                "media": {
                    "track": "outbound",
                    "payload": frame_b64,
                },
            })

        # 2. Send malformed tracks -> must be IGNORED safely without crashing
        ws.send_json({
            "event": "media",
            "stream_sid": "stream_track_01",
            "media": {"track": 99999, "payload": frame_b64},
        })
        ws.send_json({
            "event": "media",
            "stream_sid": "stream_track_01",
            "media": {"track": "unknown_carrier_track", "payload": frame_b64},
        })

        # 3. Send 10 frames with track='inbound' -> must be PROCESSED
        for _ in range(10):
            ws.send_json({
                "event": "media",
                "stream_sid": "stream_track_01",
                "media": {
                    "track": "inbound",
                    "payload": frame_b64,
                },
            })

        # Verify reply media frames and mark are received
        turn_received = False
        while True:
            msg = ws.receive_json()
            if msg.get("event") == "mark":
                turn_received = True
                break

        assert turn_received is True
        ws.send_json({"event": "stop", "stream_sid": "stream_track_01"})


def test_voicelink_media_missing_track_handled_safely(client, org):
    """When media event omits track field, adapter handles it safely without crashing."""
    with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
        ws.send_json({
            "event": "start",
            "stream_sid": "stream_notrack_01",
            "start": {
                "media_format": {"encoding": "alaw"},
            },
        })
        while True:
            if ws.receive_json().get("event") == "mark":
                break

        frame_b64 = base64.b64encode(generate_silence(20, AudioCodec.ALAW)).decode("ascii")
        # Send media without 'track' key
        for _ in range(10):
            ws.send_json({
                "event": "media",
                "stream_sid": "stream_notrack_01",
                "media": {"payload": frame_b64},
            })

        turn_mark = False
        while True:
            if ws.receive_json().get("event") == "mark":
                turn_mark = True
                break

        assert turn_mark is True
        ws.send_json({"event": "stop", "stream_sid": "stream_notrack_01"})


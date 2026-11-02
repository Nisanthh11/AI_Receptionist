"""VoiceLink Telephony WebSocket router.

Provides an isolated, authenticated WebSocket endpoint for real-time VoiceLink telephony calls
at /api/telephony/voicelink/ws.
"""
from __future__ import annotations

import hmac
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import SessionLocal
from app.telephony.voicelink_adapter import VoiceLinkWebSocketAdapter, _mask_phone

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telephony/voicelink", tags=["VoiceLink Telephony"])


def get_voicelink_adapter() -> VoiceLinkWebSocketAdapter:
    """Dependency provider for VoiceLink adapter."""
    return VoiceLinkWebSocketAdapter()


def verify_voicelink_auth(websocket: WebSocket, settings: Settings | None = None) -> bool:
    """Verifies authentication credentials for incoming VoiceLink WebSocket connections.

    Supports multiple carrier authentication methods without guessing:
    1. Query parameters (?token=... or ?secret=...)
    2. Header: X-VoiceLink-Secret
    3. Header: Authorization (Bearer <token> or raw token)

    Security rules:
    - In production environments (production, prod, staging), authentication is mandatory.
      If VOICELINK_WEBHOOK_SECRET is unconfigured in production, connections are rejected.
    - If VOICELINK_WEBHOOK_SECRET is configured (in any environment), it is strictly enforced
      using constant-time comparison (hmac.compare_digest).
    - In local development mode without a configured secret, connections are permitted
      to facilitate local offline testing.
    """
    cfg = settings or get_settings()
    env = (cfg.environment or "").strip().lower()
    is_production = env in ("production", "prod", "staging")
    configured_secret = (cfg.voicelink_webhook_secret or "").strip()

    # Rule 1: Never silently disable authentication in production
    if is_production and not configured_secret:
        logger.error(
            "Rejected VoiceLink WebSocket connection: VOICELINK_WEBHOOK_SECRET "
            "is not configured in production environment '%s'.",
            env,
        )
        return False

    # Rule 2: Enforce secret if configured
    if configured_secret:
        # Extract token from query params or headers
        token = websocket.query_params.get("token") or websocket.query_params.get("secret")

        if not token:
            token = websocket.headers.get("x-voicelink-secret")

        if not token:
            auth_header = websocket.headers.get("authorization")
            if auth_header:
                clean_auth = auth_header.strip()
                if clean_auth.lower().startswith("bearer "):
                    token = clean_auth[7:].strip()
                else:
                    token = clean_auth

        if not token:
            logger.warning("Rejected VoiceLink WebSocket connection: missing authentication credentials.")
            return False

        if not hmac.compare_digest(token.strip(), configured_secret):
            logger.warning("Rejected VoiceLink WebSocket connection: invalid authentication token.")
            return False

        return True

    # Rule 3: Development / local test mode without secret
    logger.debug("VoiceLink WebSocket authentication unconfigured; allowing in development mode.")
    return True


def verify_voicelink_http_auth(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Verifies authentication credentials for VoiceLink HTTP webhook endpoints.

    Supports:
    1. Header: X-VoiceLink-Secret
    2. Header: Authorization (Bearer <token> or raw token)
    3. Query parameters (?token=... or ?secret=...)

    Security rules:
    - In production environments (production, prod, staging), authentication is mandatory.
      If VOICELINK_WEBHOOK_SECRET is unconfigured in production, requests are rejected with 401.
    - If VOICELINK_WEBHOOK_SECRET is configured (in any environment), it is strictly enforced
      using constant-time comparison (hmac.compare_digest).
    - In local development mode without a configured secret, requests are permitted
      to facilitate local offline testing.
    - Secrets are never logged or returned in responses.
    """
    cfg = settings or get_settings()
    env = (cfg.environment or "").strip().lower()
    is_production = env in ("production", "prod", "staging")
    configured_secret = (cfg.voicelink_webhook_secret or "").strip()

    # Rule 1: Never silently disable authentication in production
    if is_production and not configured_secret:
        logger.error(
            "Rejected VoiceLink HTTP request: VOICELINK_WEBHOOK_SECRET "
            "is not configured in production environment '%s'.",
            env,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # Rule 2: Enforce secret if configured
    if configured_secret:
        # 1. Check custom header
        token = request.headers.get("x-voicelink-secret")

        # 2. Check Authorization header
        if not token:
            auth_header = request.headers.get("authorization")
            if auth_header:
                clean_auth = auth_header.strip()
                if clean_auth.lower().startswith("bearer "):
                    token = clean_auth[7:].strip()
                else:
                    token = clean_auth

        # 3. Check query parameters
        if not token:
            token = request.query_params.get("token") or request.query_params.get("secret")

        if not token:
            logger.warning("Rejected VoiceLink HTTP request: missing authentication credentials.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        if not hmac.compare_digest(token.strip(), configured_secret):
            logger.warning("Rejected VoiceLink HTTP request: invalid authentication token.")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

        return

    # Rule 3: Development / local test mode without secret
    logger.debug("VoiceLink HTTP authentication unconfigured; allowing in development mode.")


@dataclass
class VoiceLinkCallEvent:
    """Normalized call event model mapping VoiceLink webhook parameter variations."""

    event: str
    original_event: str | None = None
    call_id: str | None = None
    customer_number: str | None = None
    virtual_number: str | None = None
    call_type: str | None = None
    duration: int | None = None
    hangup_cause: str | None = None
    recording_path: str | None = None
    call_status: str | None = None
    custom_parameters: dict[str, Any] = field(default_factory=dict)
    raw_payload: dict[str, Any] = field(default_factory=dict)


def _find_field(data: dict[str, Any], aliases: list[str]) -> Any:
    """Finds the first non-empty value matching any alias, case-insensitively."""
    for key in aliases:
        if key in data and data[key] is not None and str(data[key]).strip() != "":
            return data[key]
    alias_lower = {a.lower().replace("-", "_"): a for a in aliases}
    for k, v in data.items():
        if v is not None and str(v).strip() != "":
            cleaned_k = k.lower().replace("-", "_").strip()
            if cleaned_k in alias_lower:
                return v
    return None


def _parse_duration(val: Any) -> int | None:
    """Safely converts duration strings or numbers to integer seconds."""
    if val is None or val == "":
        return None
    try:
        return int(round(float(str(val).strip())))
    except (ValueError, TypeError):
        return None


def normalize_voicelink_call_event(data: dict[str, Any]) -> VoiceLinkCallEvent:
    """Normalizes VoiceLink parameter mapping variations into a consistent structure."""
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed event payload: expected JSON object or form mapping",
        )

    # 1. Event / Status
    # Check primary event keys first. Do not interpret callStatus/status as event type when event is present.
    raw_event = _find_field(data, ["event", "event_type", "eventType", "action"])
    if not raw_event or not str(raw_event).strip():
        # Fallback to status-based event keys only if no explicit event field was supplied
        raw_event = _find_field(data, ["status", "call_status", "callStatus", "call_state", "type"])

    if not raw_event or not str(raw_event).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required event field (e.g. event, event_type, or status)",
        )

    raw_event_str = str(raw_event).strip()
    clean_event = raw_event_str.lower().replace("-", "_").replace(" ", "_")

    event_synonyms = {
        # Documented VoiceLink dot-notation event types
        "call.initiated": "call.initiated",
        "call.answered": "call.answered",
        "call.ended": "call.ended",
        "call.completed": "call.completed",
        # Common synonyms for backward compatibility
        "initiate": "initiated",
        "initiated_call": "initiated",
        "ring": "ringing",
        "answer": "answered",
        "in_progress": "answered",
        "hangup": "completed",
        "call_ended": "completed",
        "ended": "completed",
        "terminated": "completed",
        "disconnect": "completed",
        "disconnected": "completed",
        "missed": "no_answer",
        "unanswered": "no_answer",
        "error": "failed",
    }
    normalized_event = event_synonyms.get(clean_event, clean_event)

    # 2. Call ID (normalize callId -> call_id)
    raw_call_id = _find_field(data, ["callId", "call_id", "unique_id", "call_sid", "uuid", "session_id", "id"])
    call_id = str(raw_call_id).strip() if raw_call_id is not None else None

    # 3. Customer / Caller Number (normalize fromNumber -> customer_number)
    raw_customer = _find_field(data, ["fromNumber", "from_number", "customer_number", "from", "caller_id", "source", "caller_number", "cli", "phone_number"])
    customer_number = str(raw_customer).strip() if raw_customer is not None else None

    # 4. Virtual Number / DID (normalize toNumber -> virtual_number)
    raw_virtual = _find_field(data, ["toNumber", "to_number", "virtual_number", "did", "to", "destination", "called_number", "callee_number"])
    virtual_number = str(raw_virtual).strip() if raw_virtual is not None else None

    # 5. Call Type / Direction (normalize direction -> call_type)
    raw_type = _find_field(data, ["direction", "call_type", "call_direction", "callType"])
    call_type = str(raw_type).strip().lower() if raw_type is not None else None

    # 6. Call Status
    raw_status = _find_field(data, ["callStatus", "call_status", "status", "call_state", "state"])
    call_status = str(raw_status).strip().lower() if raw_status is not None else None

    # 7. Duration
    raw_duration = _find_field(data, ["duration", "billsec", "call_duration", "talk_time"])
    duration = _parse_duration(raw_duration)

    # 8. Hangup Cause
    raw_cause = _find_field(data, ["hangup_cause", "disconnect_reason", "cause", "reason", "hangup_reason"])
    hangup_cause = str(raw_cause).strip() if raw_cause is not None else None

    # 9. Recording Path / URL (normalize recordingUrl -> recording_path)
    raw_rec = _find_field(data, ["recordingUrl", "recording_url", "recording_path", "recording", "record_url"])
    recording_path = str(raw_rec).strip() if raw_rec is not None else None

    # 10. Custom Parameters
    raw_custom = data.get("customParameters")
    if raw_custom is None:
        raw_custom = data.get("custom_parameters")
    if raw_custom is None:
        raw_custom = data.get("customParams")
    if raw_custom is None:
        raw_custom = data.get("custom_params")

    custom_parameters: dict[str, Any] = {}
    if isinstance(raw_custom, dict):
        custom_parameters = raw_custom
    elif isinstance(raw_custom, str) and raw_custom.strip():
        try:
            parsed_custom = json.loads(raw_custom.strip())
            if isinstance(parsed_custom, dict):
                custom_parameters = parsed_custom
        except Exception:
            pass

    return VoiceLinkCallEvent(
        event=normalized_event,
        original_event=raw_event_str,
        call_id=call_id,
        customer_number=customer_number,
        virtual_number=virtual_number,
        call_type=call_type,
        duration=duration,
        hangup_cause=hangup_cause,
        recording_path=recording_path,
        call_status=call_status,
        custom_parameters=custom_parameters,
        raw_payload=data,
    )


async def _extract_request_payload(request: Request) -> dict[str, Any]:
    """Extracts payload data from JSON, Form-data, or raw body."""
    content_type = (request.headers.get("content-type") or "").lower()

    if "application/json" in content_type:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Malformed JSON: expected object",
                )
            return body
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid JSON payload: {exc}",
            )

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        try:
            form = await request.form()
            return dict(form)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid form payload: {exc}",
            )

    # Fallback: attempt JSON first, then form parsing
    try:
        raw_body = await request.body()
        if not raw_body or not raw_body.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty request payload",
            )
        parsed = json.loads(raw_body.decode("utf-8"))
        if isinstance(parsed, dict):
            return parsed
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON: expected object",
        )
    except HTTPException:
        raise
    except Exception:
        try:
            form = await request.form()
            if form:
                return dict(form)
        except Exception:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported or malformed request payload",
        )


@router.post("/events", dependencies=[Depends(verify_voicelink_http_auth)])
async def voicelink_call_events(request: Request) -> dict[str, Any]:
    """Receives and processes VoiceLink Call Event API webhooks.

    Accepts both JSON and application/x-www-form-urlencoded payloads.
    Normalizes field aliases, logs events safely with masked phone numbers,
    and returns a standard HTTP 200 JSON acknowledgment.
    """
    raw_data = await _extract_request_payload(request)
    event = normalize_voicelink_call_event(raw_data)

    logger.info(
        "VoiceLink call event received: event=%s, status=%s, call_id=%s, customer=%s, virtual=%s, duration=%s",
        event.event,
        event.call_status or "none",
        event.call_id or "none",
        _mask_phone(event.customer_number),
        _mask_phone(event.virtual_number),
        event.duration if event.duration is not None else "none",
    )

    response_data: dict[str, Any] = {
        "status": "ok",
        "event": event.event,
        "call_id": event.call_id,
        "customer_number": _mask_phone(event.customer_number),
        "virtual_number": _mask_phone(event.virtual_number),
        "duration": event.duration,
        "received": True,
    }
    if event.call_status is not None:
        response_data["call_status"] = event.call_status
    if event.recording_path is not None:
        response_data["recording_url"] = event.recording_path

    return response_data


@router.websocket("/ws")
async def voicelink_websocket_endpoint(
    websocket: WebSocket,
    adapter: VoiceLinkWebSocketAdapter = Depends(get_voicelink_adapter),
) -> None:
    """Bi-directional WebSocket endpoint handling VoiceLink phone calls.

    Receives standard VoiceLink events (connected, start, media, mark, stop)
    and transmits 8 kHz mono audio responses.
    """
    settings = get_settings()
    if not verify_voicelink_auth(websocket, settings):
        await websocket.close(code=1008, reason="Unauthorized")
        return

    with SessionLocal() as db:
        await adapter.handle_connection(websocket, db)


@router.get("/config")
def get_voicelink_status():
    """Returns the operational status of the VoiceLink integration."""
    settings = get_settings()
    env = (settings.environment or "").strip().lower()
    is_prod = env in ("production", "prod", "staging")
    auth_enforced = bool(settings.voicelink_webhook_secret or is_prod)
    is_mock = (settings.stt_provider == "mock" and settings.tts_provider == "mock")

    return {
        "provider": "voicelink",
        "mock_mode": is_mock,
        "stt_provider": settings.stt_provider,
        "tts_provider": settings.tts_provider,
        "endpoint": "/api/telephony/voicelink/ws",
        "events_endpoint": "/api/telephony/voicelink/events",
        "supported_codecs": ["alaw", "slin"],
        "sample_rate": 8000,
        "channels": 1,
        "frame_duration_ms": 20,
        "auth_enforced": auth_enforced,
        "auth_configured": bool(settings.voicelink_webhook_secret),
    }

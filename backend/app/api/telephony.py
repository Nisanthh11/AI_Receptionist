"""Telephony webhook endpoints for real telephone calls.

Receives standard telephony webhooks (such as Twilio Voice, Telnyx, or SIP trunk gateways),
processes speech turns via the VoiceService, and returns valid TwiML XML responses.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.telephony.twilio_adapter import TwilioVoiceAdapter, validate_twilio_request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telephony", tags=["Telephony Voice Agent"])


def get_telephony_adapter() -> TwilioVoiceAdapter:
    return TwilioVoiceAdapter()


async def verify_telephony_signature(request: Request) -> None:
    """Verifies cryptographic X-Twilio-Signature header when enabled in configuration."""
    settings = get_settings()
    if not settings.twilio_validate_signature:
        return

    signature = request.headers.get("X-Twilio-Signature")
    if not signature:
        logger.warning("Rejected telephony request without X-Twilio-Signature header.")
        raise HTTPException(status_code=403, detail="Missing signature header")

    form_data = await request.form()
    params = {k: str(v) for k, v in form_data.items()}
    url = str(request.url)
    if not validate_twilio_request(settings.twilio_auth_token or "", url, params, signature):
        logger.warning("Rejected telephony request with invalid X-Twilio-Signature.")
        raise HTTPException(status_code=403, detail="Invalid request signature")


@router.post("/incoming", response_class=Response, dependencies=[Depends(verify_telephony_signature)])
async def incoming_telephone_call(
    request: Request,
    From: str = Form(default=""),
    CallSid: str = Form(default=""),
    db: Session = Depends(get_db),
    adapter: TwilioVoiceAdapter = Depends(get_telephony_adapter),
):
    """Webhook invoked by telephony provider when an ordinary phone call arrives."""
    logger.info("Incoming telephone call received: CallSid=%s, From=%s", CallSid, From)
    try:
        twiml_xml = adapter.handle_incoming_call(caller_number=From, call_id=CallSid, db=db)
        return Response(content=twiml_xml, media_type="application/xml")
    except Exception as exc:
        logger.error("Error processing incoming telephone call %s: %s", CallSid, exc, exc_info=True)
        db.rollback()
        return Response(content=adapter.generate_error_fallback(), media_type="application/xml")


@router.post("/turn", response_class=Response, dependencies=[Depends(verify_telephony_signature)])
async def process_telephone_turn(
    request: Request,
    From: str = Form(default=""),
    CallSid: str = Form(default=""),
    SpeechResult: str = Form(default=""),
    session_token: str | None = Query(default=None),
    db: Session = Depends(get_db),
    adapter: TwilioVoiceAdapter = Depends(get_telephony_adapter),
):
    """Webhook invoked by telephony provider when caller speech has been recognized."""
    logger.info("Telephone speech turn: CallSid=%s, Speech='%s'", CallSid, SpeechResult)
    try:
        twiml_xml = adapter.handle_speech_input(
            call_id=CallSid,
            caller_number=From,
            speech_text=SpeechResult,
            session_token=session_token,
            db=db,
        )
        return Response(content=twiml_xml, media_type="application/xml")
    except Exception as exc:
        logger.error("Error processing speech turn for CallSid=%s: %s", CallSid, exc, exc_info=True)
        db.rollback()
        return Response(content=adapter.generate_error_fallback(), media_type="application/xml")


@router.post("/transfer-status", response_class=Response, dependencies=[Depends(verify_telephony_signature)])
async def telephone_transfer_status(
    DialCallStatus: str = Form(default=""),
    CallSid: str = Form(default=""),
    adapter: TwilioVoiceAdapter = Depends(get_telephony_adapter),
):
    """Webhook callback triggered when bridging call to the human reception desk completes or fails."""
    logger.info("Human transfer status for CallSid=%s: DialCallStatus=%s", CallSid, DialCallStatus)
    if DialCallStatus in ("completed", "answered"):
        return Response(content='<?xml version="1.0" encoding="UTF-8"?>\n<Response><Hangup/></Response>', media_type="application/xml")

    # If the human transfer failed (busy, no-answer, failed, canceled)
    twiml_xml = adapter.handle_failed_transfer(call_id=CallSid, dial_status=DialCallStatus)
    return Response(content=twiml_xml, media_type="application/xml")


@router.post("/status", dependencies=[Depends(verify_telephony_signature)])
async def telephone_call_status(
    CallSid: str = Form(default=""),
    CallStatus: str = Form(default=""),
    session_token: str | None = Query(default=None),
    adapter: TwilioVoiceAdapter = Depends(get_telephony_adapter),
):
    """Webhook invoked on call status changes (e.g. completed, busy, no-answer)."""
    logger.info("Telephone call status change: CallSid=%s, Status=%s", CallSid, CallStatus)
    if CallStatus in ("completed", "canceled", "failed", "busy", "no-answer"):
        adapter.handle_call_ended(call_id=CallSid, session_token=session_token)
    return {"status": "recorded", "call_status": CallStatus}


@router.get("/config")
def get_telephony_configuration():
    """Returns the current telephone configuration status (secrets are masked)."""
    settings = get_settings()
    has_sid = bool(settings.twilio_account_sid and not settings.twilio_account_sid.startswith("REPLACE"))
    has_token = bool(settings.twilio_auth_token and not settings.twilio_auth_token.startswith("REPLACE"))
    has_number = bool(settings.telephony_phone_number)

    return {
        "provider": settings.telephony_provider,
        "phone_number": settings.telephony_phone_number or "Not configured",
        "webhook_url": settings.telephony_webhook_url or "Not configured",
        "account_sid_configured": has_sid,
        "auth_token_configured": has_token,
        "signature_validation_active": settings.twilio_validate_signature,
        "transfer_destination": settings.telephony_reception_transfer_number or "Default from DB",
        "tts_voice": settings.telephony_voice,
        "tts_language": settings.telephony_language,
        "ready_for_live_calls": has_sid and has_token and has_number,
    }

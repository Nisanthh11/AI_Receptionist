"""Telephony webhook endpoints for real telephone calls.

Receives standard telephony webhooks (such as Twilio Voice, Telnyx, or SIP trunk gateways),
processes speech turns via the VoiceService, and returns valid TwiML XML responses.
"""
from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, Form, Query, Request, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.telephony.twilio_adapter import TwilioVoiceAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telephony", tags=["Telephony Voice Agent"])


def get_telephony_adapter() -> TwilioVoiceAdapter:
    return TwilioVoiceAdapter()


@router.post("/incoming", response_class=Response)
async def incoming_telephone_call(
    request: Request,
    From: str = Form(default=""),
    CallSid: str = Form(default=""),
    db: Session = Depends(get_db),
    adapter: TwilioVoiceAdapter = Depends(get_telephony_adapter),
):
    """Webhook invoked by telephony provider when an ordinary phone call arrives."""
    logger.info("Incoming telephone call received: CallSid=%s, From=%s", CallSid, From)
    twiml_xml = adapter.handle_incoming_call(caller_number=From, call_id=CallSid, db=db)
    return Response(content=twiml_xml, media_type="application/xml")


@router.post("/turn", response_class=Response)
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
    twiml_xml = adapter.handle_speech_input(
        call_id=CallSid,
        caller_number=From,
        speech_text=SpeechResult,
        session_token=session_token,
        db=db,
    )
    return Response(content=twiml_xml, media_type="application/xml")


@router.post("/status")
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

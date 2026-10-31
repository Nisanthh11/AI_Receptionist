"""Public Voice Agent API for browser-based voice interactions.

Provides session initialization, turn-by-turn conversational speech processing,
and human escalation with rate limiting and privacy protection.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import get_optional_current_user
from app.core.rate_limit import RateLimiter
from app.models.user import User
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/voice", tags=["Voice Agent"])

# Public rate limiter for voice turns: max 30 turns per minute per IP
_voice_limiter = RateLimiter(max_requests=30, window_seconds=60)


def rate_limit_voice(request: Request) -> None:
    client_ip = request.client.host if request.client else "127.0.0.1"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    _voice_limiter.check(f"voice_{client_ip}")


def get_voice_service() -> VoiceService:
    return VoiceService()


class VoiceSessionStartRequest(BaseModel):
    session_token: str | None = Field(default=None, max_length=64)
    channel: str = Field(default="browser_voice", max_length=20)


class VoiceSessionStartResponse(BaseModel):
    session_token: str
    display_text: str
    speech_text: str
    status: str = "ready"
    suggestions: list[str] = [
        "I'd like to book an appointment",
        "What are your working hours?",
        "Which departments do you have?",
    ]


class VoiceTurnRequest(BaseModel):
    session_token: str = Field(..., min_length=8, max_length=64)
    transcript: str = Field(..., min_length=1, max_length=1000)
    channel: str = Field(default="browser_voice", max_length=20)


class VoiceTurnResponse(BaseModel):
    session_token: str
    reply_text: str
    speech_text: str
    intent: str
    booking_flow: dict[str, Any] | None = None
    suggestions: list[str] = []
    transfer_to_human: bool = False
    is_final: bool = False
    action: str | None = None


class VoiceEndRequest(BaseModel):
    session_token: str = Field(..., min_length=8, max_length=64)


@router.post("/session", response_model=VoiceSessionStartResponse, dependencies=[Depends(rate_limit_voice)])
def start_voice_session(
    payload: VoiceSessionStartRequest | None = None,
    db: Session = Depends(get_db),
    service: VoiceService = Depends(get_voice_service),
    current_user: User | None = Depends(get_optional_current_user),
):
    """Initializes or resumes a voice session, providing greeting and voice capabilities."""
    req = payload or VoiceSessionStartRequest()
    display_text, speech_text = service.get_greeting(db, channel=req.channel)

    # Initialize session through voice handler with empty message to assign session token
    result = service.handle_turn(
        db,
        transcript="",
        session_token=req.session_token,
        channel=req.channel,
        current_user=current_user,
    )

    return VoiceSessionStartResponse(
        session_token=result.session_token,
        display_text=display_text,
        speech_text=speech_text,
        status="ready",
    )


@router.post("/turn", response_model=VoiceTurnResponse, dependencies=[Depends(rate_limit_voice)])
def process_voice_turn(
    payload: VoiceTurnRequest,
    db: Session = Depends(get_db),
    service: VoiceService = Depends(get_voice_service),
    current_user: User | None = Depends(get_optional_current_user),
):
    """Processes a user speech transcript and returns spoken and visual responses."""
    result = service.handle_turn(
        db,
        transcript=payload.transcript,
        session_token=payload.session_token,
        channel=payload.channel,
        current_user=current_user,
    )

    return VoiceTurnResponse(
        session_token=result.session_token,
        reply_text=result.reply_text,
        speech_text=result.speech_text,
        intent=result.intent,
        booking_flow=result.booking_flow,
        suggestions=result.suggestions,
        transfer_to_human=result.transfer_to_human,
        is_final=result.is_final,
        action=result.action,
    )


@router.post("/end")
def end_voice_session(payload: VoiceEndRequest):
    """Ends the active voice session gracefully."""
    return {"status": "ended", "session_token": payload.session_token}

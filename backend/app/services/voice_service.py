"""Voice service orchestrating spoken AI interactions for browser and telephony channels.

Builds upon the existing ChatService and AppointmentService, ensuring shared state,
identical slot calculation, and concurrency protection, while providing natural speech text,
human transfer handling, and channel attribution.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import OrganizationInfo
from app.models.user import User
from app.services.chat_service import (
    BookingSession,
    ChatReply,
    ChatService,
    HybridGeminiResponder,
    _booking_sessions,
    to_speech_text,
)

logger = logging.getLogger(__name__)

# Patterns indicating the caller wishes to reach a human front-desk staff member
_HUMAN_TRANSFER_PATTERN = re.compile(
    r"\b(human|representative|operator|real person|person|agent|receptionist|staff member|"
    r"speak to someone|talk to someone|connect me|transfer me|manager)\b",
    re.I,
)


@dataclass
class VoiceTurnResult:
    session_token: str
    reply_text: str
    speech_text: str
    intent: str
    booking_flow: dict[str, Any] | None = None
    suggestions: list[str] = field(default_factory=list)
    transfer_to_human: bool = False
    is_final: bool = False
    action: str | None = None


class VoiceService:
    """Orchestrator for voice-driven receptionist conversations."""

    def __init__(self, chat_service: ChatService | None = None):
        self.chat_service = chat_service or ChatService(HybridGeminiResponder())

    def get_greeting(self, db: Session, channel: str = "browser_voice") -> tuple[str, str]:
        """Returns (display_text, speech_text) for the initial call greeting."""
        org_name = None
        info = db.get(OrganizationInfo, "organization_name")
        if info and info.value:
            org_name = info.value

        if org_name:
            display = f"Hello! Thank you for calling {org_name}. I am your virtual receptionist. I can help you book an appointment, find departments, or answer common questions. How can I assist you today?"
        else:
            display = "Hello! Thank you for calling reception. I am your virtual receptionist. I can help you book an appointment, find departments, or answer common questions. How can I assist you today?"

        speech = to_speech_text(display)
        return display, speech

    def handle_turn(
        self,
        db: Session,
        transcript: str,
        session_token: str | None = None,
        channel: str = "browser_voice",
        current_user: User | None = None,
    ) -> VoiceTurnResult:
        """Processes a spoken turn from the user and returns speech-optimized responses."""
        clean_transcript = (transcript or "").strip()

        # If caller sent empty audio or silence during an ongoing call, politely reprompt
        if not clean_transcript and session_token:
            reprompt = "I'm sorry, I didn't catch that. Could you please repeat?"
            return VoiceTurnResult(
                session_token=session_token,
                reply_text=reprompt,
                speech_text=reprompt,
                intent="silence",
                transfer_to_human=False,
                is_final=False,
                suggestions=["I'd like to book an appointment", "What are your working hours?"],
            )

        # 1. Check for human transfer intent
        if clean_transcript and _HUMAN_TRANSFER_PATTERN.search(clean_transcript):
            logger.info("Caller requested human transfer on channel %s: '%s'", channel, clean_transcript)
            transfer_msg = (
                "Certainly. I am transferring your call to our front desk reception team now. "
                "Please hold on while I connect you."
            )
            return VoiceTurnResult(
                session_token=session_token or "",
                reply_text=transfer_msg,
                speech_text=to_speech_text(transfer_msg),
                intent="human_transfer",
                transfer_to_human=True,
                is_final=True,
                suggestions=["Call ended", "Start over"],
            )

        # 2. Process turn via the shared FSM chat engine
        token, reply = self.chat_service.handle(
            db, clean_transcript, session_token, current_user=current_user
        )

        # 3. Ensure booking_source is tagged on the active session
        session = _booking_sessions.get(token)
        if session:
            session.booking_source = channel

        # 4. Generate clean, spoken-friendly text
        speech_text = to_speech_text(reply.text)

        # 5. Format speech specifically for slot options if in the slot selection phase
        if reply.booking_flow and reply.booking_flow.get("step") == "slot":
            slots = session.available_slots if session else []
            if slots:
                spoken_slots = [
                    s["start_at"].strftime("%I:%M %p") for s in slots[:4]
                ]
                if len(spoken_slots) > 1:
                    slot_phrase = ", ".join(spoken_slots[:-1]) + f", or {spoken_slots[-1]}"
                else:
                    slot_phrase = spoken_slots[0]
                speech_text = (
                    f"Available times include {slot_phrase}. "
                    f"Which time would you prefer?"
                )

        # 6. Check if session completed
        is_final = bool(reply.action == "booking_completed")

        return VoiceTurnResult(
            session_token=token,
            reply_text=reply.text,
            speech_text=speech_text,
            intent=reply.intent,
            booking_flow=reply.booking_flow,
            suggestions=reply.suggestions,
            transfer_to_human=False,
            is_final=is_final,
            action=reply.action,
        )

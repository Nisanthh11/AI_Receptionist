"""Abstract base class for telephony adapters (SIP, Twilio, Telnyx, FreeSWITCH).

Separates provider-specific telephony protocols from the core voice and appointment services.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTelephonyAdapter(ABC):
    """Abstract interface defining required telephony integration capabilities."""

    @abstractmethod
    def handle_incoming_call(self, caller_number: str, call_id: str, db: Any) -> str:
        """Invoked when an incoming phone call is connected. Returns provider call instructions (e.g. TwiML/TeXML)."""
        pass

    @abstractmethod
    def handle_speech_input(
        self,
        call_id: str,
        caller_number: str,
        speech_text: str,
        session_token: str | None,
        db: Any,
    ) -> str:
        """Invoked when speech recognition from the telephony gateway completes a turn."""
        pass

    @abstractmethod
    def handle_call_ended(self, call_id: str, session_token: str | None) -> None:
        """Invoked when the caller hangs up or disconnects."""
        pass

    @abstractmethod
    def generate_human_transfer(self, destination_number: str, message: str) -> str:
        """Generates instructions to bridge/dial the caller to a human receptionist phone line."""
        pass

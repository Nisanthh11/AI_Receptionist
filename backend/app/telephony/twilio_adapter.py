"""Twilio Voice / SIP Telephony Adapter.

Generates standard TwiML XML payloads for incoming telephone calls and speech turns,
bridging PSTN calls to the core VoiceService and AppointmentService with channel='telephone'.
"""
from __future__ import annotations

import logging
from xml.sax.saxutils import escape as xml_escape
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import OrganizationInfo
from app.services.chat_service import _booking_sessions
from app.services.voice_service import VoiceService
from app.telephony.base import BaseTelephonyAdapter

logger = logging.getLogger(__name__)

# In-memory mapping of CallSid -> session_token
_call_session_map: dict[str, str] = {}


class TwilioVoiceAdapter(BaseTelephonyAdapter):
    """Twilio Voice adapter translating telephony webhooks into VoiceService turns and TwiML XML."""

    def __init__(self, voice_service: VoiceService | None = None):
        self.voice_service = voice_service or VoiceService()

    def get_session_token_for_call(self, call_sid: str) -> str | None:
        return _call_session_map.get(call_sid)

    def bind_call_session(self, call_sid: str, session_token: str) -> None:
        _call_session_map[call_sid] = session_token

    def handle_incoming_call(self, caller_number: str, call_id: str, db: Session) -> str:
        """Handles an incoming PSTN call webhook, creating a voice session and returning TwiML."""
        display_text, speech_text = self.voice_service.get_greeting(db, channel="telephone")

        # Create session turn with empty transcript to establish token and channel
        result = self.voice_service.handle_turn(
            db,
            transcript="",
            session_token=None,
            channel="telephone",
        )
        self.bind_call_session(call_id, result.session_token)

        # Pre-fill caller's phone number into the booking session if available
        session = _booking_sessions.get(result.session_token)
        if session and caller_number:
            session.phone = caller_number.strip()

        # Build initial TwiML greeting with speech gather
        safe_speech = xml_escape(speech_text)
        action_url = f"/api/telephony/turn?session_token={result.session_token}"

        twiml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="Polly.Joanna" language="en-US">{safe_speech}</Say>\n'
            f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" actionOnEmptyResult="true">\n'
            f'        <Say voice="Polly.Joanna" language="en-US">I am listening. Please speak now.</Say>\n'
            f'    </Gather>\n'
            f'    <Say voice="Polly.Joanna" language="en-US">I did not hear anything. If you would like to speak with someone, please stay on the line.</Say>\n'
            f'    <Redirect method="POST">{action_url}</Redirect>\n'
            f'</Response>'
        )
        return twiml

    def handle_speech_input(
        self,
        call_id: str,
        caller_number: str,
        speech_text: str,
        session_token: str | None,
        db: Session,
    ) -> str:
        """Processes caller speech input received via telephony webhook and generates next TwiML turn."""
        token = session_token or self.get_session_token_for_call(call_id)

        clean_speech = (speech_text or "").strip()
        if not clean_speech:
            # Empty speech or timeout: ask to repeat
            prompt = "I'm sorry, I could not hear your response clearly. Could you please repeat that?"
            action_url = f"/api/telephony/turn?session_token={token or ''}"
            return (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<Response>\n'
                f'    <Say voice="Polly.Joanna" language="en-US">{xml_escape(prompt)}</Say>\n'
                f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" />\n'
                f'</Response>'
            )

        # Process turn through VoiceService
        result = self.voice_service.handle_turn(
            db,
            transcript=clean_speech,
            session_token=token,
            channel="telephone",
        )
        if token and result.session_token:
            self.bind_call_session(call_id, result.session_token)

        # Check for human transfer escalation
        if result.transfer_to_human:
            org_phone = "+910000000000"
            phone_row = db.get(OrganizationInfo, "contact_phone")
            if phone_row and phone_row.value:
                org_phone = phone_row.value
            return self.generate_human_transfer(org_phone, result.speech_text)

        # Check if booking completed / call final
        safe_response = xml_escape(result.speech_text)
        if result.is_final:
            return (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<Response>\n'
                f'    <Say voice="Polly.Joanna" language="en-US">{safe_response}</Say>\n'
                f'    <Say voice="Polly.Joanna" language="en-US">Thank you for calling. Have a wonderful day. Goodbye.</Say>\n'
                f'    <Hangup/>\n'
                f'</Response>'
            )

        # Otherwise continue turn-taking with next Gather
        action_url = f"/api/telephony/turn?session_token={result.session_token}"
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="Polly.Joanna" language="en-US">{safe_response}</Say>\n'
            f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" />\n'
            f'    <Say voice="Polly.Joanna" language="en-US">Are you still there? Please let me know how I can help.</Say>\n'
            f'</Response>'
        )

    def handle_call_ended(self, call_id: str, session_token: str | None) -> None:
        """Cleans up internal session mapping when call is terminated."""
        _call_session_map.pop(call_id, None)
        logger.info("Telephony call %s disconnected cleanly.", call_id)

    def generate_human_transfer(self, destination_number: str, message: str) -> str:
        """Bridges the caller to the front desk reception phone line."""
        safe_msg = xml_escape(message)
        safe_dest = xml_escape(destination_number)
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="Polly.Joanna" language="en-US">{safe_msg}</Say>\n'
            f'    <Dial timeout="20">\n'
            f'        <Number>{safe_dest}</Number>\n'
            f'    </Dial>\n'
            f'</Response>'
        )

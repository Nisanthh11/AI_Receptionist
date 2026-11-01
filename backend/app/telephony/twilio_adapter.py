"""Twilio Voice / SIP Telephony Adapter.

Generates standard TwiML XML payloads for incoming telephone calls and speech turns,
bridging PSTN calls to the core VoiceService and AppointmentService with channel='telephone'.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
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
# In-memory tracking of consecutive silences per CallSid
_call_silence_map: dict[str, int] = {}


def validate_twilio_request(
    auth_token: str,
    url: str,
    params: dict[str, str],
    signature: str,
) -> bool:
    """Validates the X-Twilio-Signature header using standard HMAC-SHA1.

    Matches Twilio's official webhook signing specification:
    1. Full destination URL of the webhook request.
    2. Sort POST parameters alphabetically by key.
    3. Concatenate each key and value without delimiters to the URL.
    4. Compute HMAC-SHA1 with the Auth Token and compare Base64 digest.
    """
    if not auth_token or not signature:
        return False
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params.keys()))
    mac = hmac.new(auth_token.encode("utf-8"), data.encode("utf-8"), hashlib.sha1)
    computed = base64.b64encode(mac.digest()).decode("utf-8")
    return hmac.compare_digest(computed, signature)


class TwilioVoiceAdapter(BaseTelephonyAdapter):
    """Twilio Voice adapter translating telephony webhooks into VoiceService turns and TwiML XML."""

    def __init__(self, voice_service: VoiceService | None = None):
        self.voice_service = voice_service or VoiceService()
        self.settings = get_settings()

    @property
    def voice(self) -> str:
        return self.settings.telephony_voice or "Polly.Joanna"

    @property
    def language(self) -> str:
        return self.settings.telephony_language or "en-US"

    def get_session_token_for_call(self, call_sid: str) -> str | None:
        return _call_session_map.get(call_sid)

    def bind_call_session(self, call_sid: str, session_token: str) -> None:
        _call_session_map[call_sid] = session_token

    def handle_incoming_call(self, caller_number: str, call_id: str, db: Session) -> str:
        """Handles an incoming PSTN call webhook, creating a voice session and returning TwiML."""
        _call_silence_map[call_id] = 0
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
            f'    <Say voice="{self.voice}" language="{self.language}">{safe_speech}</Say>\n'
            f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" actionOnEmptyResult="true">\n'
            f'        <Say voice="{self.voice}" language="{self.language}">I am listening. Please speak now.</Say>\n'
            f'    </Gather>\n'
            f'    <Say voice="{self.voice}" language="{self.language}">I did not hear anything. If you would like to speak with someone, please stay on the line.</Say>\n'
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
            # Increment silence counter
            silence_count = _call_silence_map.get(call_id, 0) + 1
            _call_silence_map[call_id] = silence_count

            action_url = f"/api/telephony/turn?session_token={token or ''}"

            if silence_count >= 3:
                logger.info("Caller %s silent 3 consecutive turns. Escalating or disconnecting.", call_id)
                # Escalate to human reception if configured, otherwise end call
                dest = self.settings.telephony_reception_transfer_number
                if not dest:
                    phone_row = db.get(OrganizationInfo, "contact_phone")
                    if phone_row and phone_row.value:
                        dest = phone_row.value

                if dest:
                    msg = "I haven't heard a response. Connecting you to front desk reception now."
                    return self.generate_human_transfer(dest, msg)

                return (
                    f'<?xml version="1.0" encoding="UTF-8"?>\n'
                    f'<Response>\n'
                    f'    <Say voice="{self.voice}" language="{self.language}">I have not heard a response. Thank you for calling. Have a great day. Goodbye.</Say>\n'
                    f'    <Hangup/>\n'
                    f'</Response>'
                )

            # 1st or 2nd silence: ask politely to repeat
            prompt = "I'm sorry, I could not hear your response clearly. Could you please repeat that?"
            return (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<Response>\n'
                f'    <Say voice="{self.voice}" language="{self.language}">{xml_escape(prompt)}</Say>\n'
                f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" />\n'
                f'</Response>'
            )

        # Reset silence counter upon receiving valid speech
        _call_silence_map[call_id] = 0

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
            org_phone = self.settings.telephony_reception_transfer_number or "+910000000000"
            phone_row = db.get(OrganizationInfo, "contact_phone")
            if phone_row and phone_row.value:
                org_phone = phone_row.value
            return self.generate_human_transfer(org_phone, result.speech_text)

        # Check if booking/cancellation completed / call final
        safe_response = xml_escape(result.speech_text)
        if result.is_final:
            return (
                f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<Response>\n'
                f'    <Say voice="{self.voice}" language="{self.language}">{safe_response}</Say>\n'
                f'    <Say voice="{self.voice}" language="{self.language}">Thank you for calling. Have a wonderful day. Goodbye.</Say>\n'
                f'    <Hangup/>\n'
                f'</Response>'
            )

        # Otherwise continue turn-taking with next Gather
        action_url = f"/api/telephony/turn?session_token={result.session_token}"
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="{self.voice}" language="{self.language}">{safe_response}</Say>\n'
            f'    <Gather input="speech" action="{action_url}" method="POST" timeout="4" speechTimeout="auto" />\n'
            f'    <Say voice="{self.voice}" language="{self.language}">Are you still there? Please let me know how I can help.</Say>\n'
            f'</Response>'
        )

    def handle_call_ended(self, call_id: str, session_token: str | None) -> None:
        """Cleans up internal session mapping when call is terminated."""
        _call_session_map.pop(call_id, None)
        _call_silence_map.pop(call_id, None)
        logger.info("Telephony call %s disconnected cleanly.", call_id)

    def generate_human_transfer(self, destination_number: str, message: str) -> str:
        """Bridges the caller to the front desk reception phone line."""
        safe_msg = xml_escape(message)
        safe_dest = xml_escape(destination_number)
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="{self.voice}" language="{self.language}">{safe_msg}</Say>\n'
            f'    <Dial action="/api/telephony/transfer-status" method="POST" timeout="20">\n'
            f'        <Number>{safe_dest}</Number>\n'
            f'    </Dial>\n'
            f'</Response>'
        )

    def handle_failed_transfer(self, call_id: str, dial_status: str) -> str:
        """Generates friendly spoken recovery TwiML when the receptionist line cannot be reached."""
        logger.warning("Human transfer call for %s ended with DialCallStatus=%s", call_id, dial_status)
        msg = (
            "Our front desk reception is currently unable to take your call. "
            "Please visit our online portal or try calling back during our office hours. "
            "Thank you for calling. Goodbye."
        )
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="{self.voice}" language="{self.language}">{xml_escape(msg)}</Say>\n'
            f'    <Hangup/>\n'
            f'</Response>'
        )

    def generate_error_fallback(self, message: str | None = None) -> str:
        """Generates graceful spoken response if an unexpected database or system exception occurs."""
        fallback = message or (
            "We are experiencing a momentary system difficulty. "
            "Please try calling back shortly, or visit our website to manage your appointment. "
            "Thank you for your patience. Goodbye."
        )
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<Response>\n'
            f'    <Say voice="{self.voice}" language="{self.language}">{xml_escape(fallback)}</Say>\n'
            f'    <Hangup/>\n'
            f'</Response>'
        )

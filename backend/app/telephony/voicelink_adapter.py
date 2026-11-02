"""VoiceLink WebSocket Telephony Adapter.

Processes bidirectional WebSocket voice streams from VoiceLink India, bridging
telephony audio frames (8 kHz A-law and SLIN) to VoiceService and AppointmentService
using provider-independent speech processing abstractions.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.content import OrganizationInfo
from app.services.chat_service import _booking_sessions
from app.services.voice_service import VoiceService, VoiceTurnResult
from app.telephony.audio_codec import (
    ALAW_FRAME_BYTES,
    SLIN_FRAME_BYTES,
    AudioCodec,
    AudioCodecError,
    InvalidAudioFrameError,
    UnsupportedCodecError,
    chunk_audio_frames,
    normalize_codec,
    validate_audio_frame,
)
from app.telephony.speech_service import (
    MockSpeechToTextService,
    MockTextToSpeechService,
    SpeechToTextService,
    SynthesisResult,
    TextToSpeechService,
    TranscriptionResult,
    get_speech_to_text_service,
    get_text_to_speech_service,
)

logger = logging.getLogger(__name__)


def _mask_phone(phone: str | None) -> str:
    """Masks phone numbers for safe, privacy-compliant logging."""
    if not phone:
        return "none"
    clean = str(phone).strip()
    if len(clean) <= 4:
        return "****"
    return clean[:3] + "****" + clean[-2:]


@dataclass
class VoiceLinkCallSession:
    """Encapsulates state, buffers, and services for a single isolated phone call."""

    call_sid: str | None = None
    stream_sid: str | None = None
    caller_number: str | None = None
    callee_number: str | None = None
    codec: AudioCodec = AudioCodec.ALAW
    session_token: str | None = None
    is_active: bool = False
    is_greeting_sent: bool = False
    silence_count: int = 0
    buffered_inbound_chunks: list[bytes] = field(default_factory=list)
    pending_marks: set[str] = field(default_factory=set)

    # Isolated speech service instances per call
    stt_service: SpeechToTextService = field(default_factory=MockSpeechToTextService)
    tts_service: TextToSpeechService = field(default_factory=MockTextToSpeechService)

    def start_call(
        self,
        stream_sid: str,
        call_sid: str | None,
        caller: str | None,
        callee: str | None,
        codec: AudioCodec,
    ) -> None:
        self.stream_sid = stream_sid
        self.call_sid = call_sid
        self.caller_number = caller
        self.callee_number = callee
        self.codec = codec
        self.is_active = True
        self.silence_count = 0
        self.buffered_inbound_chunks.clear()
        self.pending_marks.clear()

    def cleanup(self) -> None:
        """Cleans up internal session buffers and resets speech state."""
        self.is_active = False
        self.buffered_inbound_chunks.clear()
        self.pending_marks.clear()
        if self.stt_service:
            self.stt_service.reset()


class VoiceLinkWebSocketAdapter:
    """Adapter translating VoiceLink WebSocket events to VoiceService turns."""

    def __init__(
        self,
        voice_service: VoiceService | None = None,
        stt_factory: Callable[[], SpeechToTextService] | None = None,
        tts_factory: Callable[[], TextToSpeechService] | None = None,
    ):
        self.voice_service = voice_service or VoiceService()
        self.settings = get_settings()
        self.stt_factory = stt_factory or (lambda: get_speech_to_text_service(self.settings))
        self.tts_factory = tts_factory or (lambda: get_text_to_speech_service(self.settings))

    async def handle_connection(self, websocket: WebSocket, db: Session) -> None:
        """Manages the full lifecycle of a VoiceLink WebSocket call."""
        await websocket.accept()

        session = VoiceLinkCallSession(
            stt_service=self.stt_factory(),
            tts_service=self.tts_factory(),
        )

        logger.info("VoiceLink WebSocket connection accepted.")

        try:
            while True:
                message_text = await websocket.receive_text()
                await self.handle_message(message_text, session, websocket, db)
                if not session.is_active and session.is_greeting_sent and not session.pending_marks:
                    # Call finished and no pending playback
                    break
        except WebSocketDisconnect:
            logger.info(
                "VoiceLink WebSocket disconnected (call_sid=%s, stream_sid=%s).",
                session.call_sid or "unknown",
                session.stream_sid or "unknown",
            )
        except Exception as exc:
            logger.error("Error in VoiceLink WebSocket handler: %s", exc, exc_info=True)
        finally:
            session.cleanup()

    async def handle_message(
        self,
        raw_message: str,
        session: VoiceLinkCallSession,
        websocket: WebSocket,
        db: Session,
    ) -> None:
        """Parses and dispatches a single incoming VoiceLink WebSocket event."""
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("Rejected non-JSON VoiceLink message: %s", exc)
            await self._send_error(websocket, session.stream_sid, "Invalid JSON payload")
            return

        if not isinstance(data, dict):
            logger.warning("Rejected malformed VoiceLink event: expected JSON object.")
            await self._send_error(websocket, session.stream_sid, "Malformed event object")
            return

        event_name = data.get("event")
        if not event_name or not isinstance(event_name, str):
            logger.warning("VoiceLink message missing 'event' field.")
            await self._send_error(websocket, session.stream_sid, "Missing 'event' field")
            return

        # Event dispatching
        if event_name == "connected":
            await self._handle_connected(data, session, websocket)
        elif event_name == "start":
            await self._handle_start(data, session, websocket, db)
        elif event_name == "media":
            await self._handle_media(data, session, websocket, db)
        elif event_name == "mark":
            await self._handle_mark(data, session, websocket)
        elif event_name == "clear":
            await self._handle_clear(data, session, websocket)
        elif event_name == "stop":
            await self._handle_stop(data, session, websocket)
        else:
            logger.warning("Ignored unsupported VoiceLink event: '%s'", event_name)

    async def _handle_connected(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
    ) -> None:
        """Handles the initial carrier handshake confirmation."""
        logger.debug("VoiceLink 'connected' event received: protocol=%s", data.get("protocol"))

    async def _handle_start(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
        db: Session,
    ) -> None:
        """Handles the 'start' call event, setting up metadata, codec, and greeting."""
        start_obj = data.get("start")
        if not isinstance(start_obj, dict):
            start_obj = data

        stream_sid = data.get("stream_sid") or start_obj.get("stream_sid")
        if not stream_sid:
            logger.warning("VoiceLink 'start' event missing 'stream_sid'.")
            await self._send_error(websocket, None, "Missing stream_sid in start event")
            return

        call_sid = start_obj.get("call_sid") or data.get("call_sid")
        caller = start_obj.get("from") or data.get("from")
        callee = start_obj.get("to") or data.get("to")

        # Determine audio codec from media_format
        media_format = start_obj.get("media_format") or data.get("media_format") or {}
        raw_encoding = None
        if isinstance(media_format, dict):
            raw_encoding = media_format.get("encoding")
        elif isinstance(media_format, str):
            raw_encoding = media_format

        # Default to A-law if unspecified, but validate explicitly
        try:
            codec = normalize_codec(raw_encoding or AudioCodec.ALAW.value)
        except UnsupportedCodecError as err:
            logger.error("Rejected call start with unsupported codec: %s", err)
            await self._send_error(websocket, stream_sid, str(err))
            await websocket.close(code=1003)
            return

        # Initialize session state
        session.start_call(
            stream_sid=stream_sid,
            call_sid=call_sid,
            caller=caller,
            callee=callee,
            codec=codec,
        )

        logger.info(
            "VoiceLink call started: call_sid=%s, stream_sid=%s, caller=%s, codec=%s",
            session.call_sid or "unknown",
            session.stream_sid,
            _mask_phone(session.caller_number),
            session.codec.value,
        )

        # Generate initial virtual receptionist greeting
        display_text, speech_text = self.voice_service.get_greeting(db, channel="voicelink_telephony")

        # Initialize session turn in VoiceService
        result = self.voice_service.handle_turn(
            db=db,
            transcript="",
            session_token=None,
            channel="voicelink_telephony",
        )
        session.session_token = result.session_token

        # Pre-bind caller phone number into booking state machine
        booking_sess = _booking_sessions.get(result.session_token)
        if booking_sess and session.caller_number:
            booking_sess.phone = str(session.caller_number).strip()

        # Synthesize greeting speech into audio
        synthesis = await session.tts_service.synthesize(speech_text, codec=session.codec)

        # Transmit synthesized audio in exact 20ms frames
        await self._send_audio_frames(websocket, session.stream_sid, synthesis.audio_bytes, session.codec)

        # Emit completion mark
        mark_id = "greeting_end"
        session.pending_marks.add(mark_id)
        await self._send_mark(websocket, session.stream_sid, mark_id)
        session.is_greeting_sent = True

    async def _handle_media(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
        db: Session,
    ) -> None:
        """Processes inbound caller audio frames, feeds STT, and generates voice responses."""
        if not session.is_active or not session.stream_sid:
            logger.warning("Received 'media' event on inactive or uninitialized call.")
            return

        media_obj = data.get("media")
        if not isinstance(media_obj, dict):
            logger.warning("Malformed 'media' event: missing 'media' dictionary.")
            return

        # Track validation: In VoiceLink / Twilio Media Streams, "inbound" is caller-to-bot audio.
        # "outbound" represents bot speech echoed back by the carrier and must be ignored.
        track = media_obj.get("track")
        if track is not None:
            if not isinstance(track, str):
                logger.warning("Malformed 'track' field in media event: expected string, got %s", type(track).__name__)
                return
            clean_track = track.strip().lower()
            if clean_track == "outbound":
                logger.debug("Ignored outbound media track chunk to prevent audio feedback loop.")
                return
            elif clean_track != "inbound":
                logger.warning("Ignored unrecognized media track: '%s'", clean_track)
                return
        else:
            logger.debug("Media event omitted track field; defaulting to inbound.")

        payload_b64 = media_obj.get("payload")
        if not payload_b64 or not isinstance(payload_b64, str):
            logger.warning("Malformed 'media' event: missing base64 'payload'.")
            return

        try:
            audio_bytes = base64.b64decode(payload_b64)
        except Exception as exc:
            logger.warning("Failed to decode base64 audio payload: %s", exc)
            return

        try:
            validate_audio_frame(audio_bytes, session.codec)
        except InvalidAudioFrameError as err:
            logger.warning("Invalid audio frame received for codec %s: %s", session.codec.value, err)
            return

        # Feed chunk to Speech-to-Text service
        stt_result = await session.stt_service.transcribe_chunk(audio_bytes, session.codec)

        # When an utterance boundary is recognized:
        if stt_result is not None and stt_result.text and stt_result.text.strip():
            clean_speech = stt_result.text.strip()
            logger.info(
                "VoiceLink recognized speech (call_sid=%s): '%s'",
                session.call_sid or "unknown",
                clean_speech,
            )
            await self._process_turn_response(clean_speech, session, websocket, db)

    async def _process_turn_response(
        self,
        speech_text: str,
        session: VoiceLinkCallSession,
        websocket: WebSocket,
        db: Session,
    ) -> None:
        """Invokes VoiceService and transmits the synthesized response back to caller."""
        turn_result = self.voice_service.handle_turn(
            db=db,
            transcript=speech_text,
            session_token=session.session_token,
            channel="voicelink_telephony",
        )
        session.session_token = turn_result.session_token

        # Check for human front desk transfer
        if turn_result.transfer_to_human:
            dest = self.settings.telephony_reception_transfer_number
            if not dest:
                phone_row = db.get(OrganizationInfo, "contact_phone")
                if phone_row and phone_row.value:
                    dest = phone_row.value
            target_number = dest or "+910000000000"

            # Speak transfer notification
            synthesis = await session.tts_service.synthesize(turn_result.speech_text, codec=session.codec)
            await self._send_audio_frames(websocket, session.stream_sid, synthesis.audio_bytes, session.codec)

            # Send transfer event
            logger.info(
                "Transferring VoiceLink call %s to human reception %s",
                session.call_sid or "unknown",
                _mask_phone(target_number),
            )
            await self._send_transfer(websocket, session.stream_sid, target_number)
            session.is_active = False
            return

        # Regular conversational response
        synthesis = await session.tts_service.synthesize(turn_result.speech_text, codec=session.codec)
        await self._send_audio_frames(websocket, session.stream_sid, synthesis.audio_bytes, session.codec)

        # Mark turn playback
        mark_id = f"turn_{turn_result.intent}"
        session.pending_marks.add(mark_id)
        await self._send_mark(websocket, session.stream_sid, mark_id)

        # If booking or cancellation is complete, conclude the call
        if turn_result.is_final:
            goodbye = "Thank you for calling. Have a wonderful day. Goodbye."
            gb_synth = await session.tts_service.synthesize(goodbye, codec=session.codec)
            await self._send_audio_frames(websocket, session.stream_sid, gb_synth.audio_bytes, session.codec)
            session.is_active = False

    async def _handle_mark(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
    ) -> None:
        """Handles receipt of mark echo from VoiceLink confirming audio playback completion."""
        mark_obj = data.get("mark") or {}
        name = mark_obj.get("name") if isinstance(mark_obj, dict) else str(mark_obj)
        if name:
            session.pending_marks.discard(name)
            logger.debug("VoiceLink mark acknowledged: %s", name)

    async def _handle_clear(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
    ) -> None:
        """Handles clear event when caller interrupts playback (barge-in)."""
        logger.debug("VoiceLink clear received for stream %s", session.stream_sid)
        session.pending_marks.clear()
        if session.stt_service:
            session.stt_service.reset()

    async def _handle_stop(
        self,
        data: dict[str, Any],
        session: VoiceLinkCallSession,
        websocket: WebSocket,
    ) -> None:
        """Handles stop event when call terminates."""
        logger.info(
            "VoiceLink stop received (call_sid=%s, stream_sid=%s).",
            session.call_sid or "unknown",
            session.stream_sid or "unknown",
        )
        session.cleanup()

    async def _send_audio_frames(
        self,
        websocket: WebSocket,
        stream_sid: str,
        audio_data: bytes,
        codec: AudioCodec,
    ) -> None:
        """Chunks and sends outbound audio in exact 20ms frames matching VoiceLink spec."""
        chunks = chunk_audio_frames(audio_data, codec=codec, frame_duration_ms=20)
        for chunk in chunks:
            validate_audio_frame(chunk, codec=codec, exact_20ms_frame=True)
            payload_b64 = base64.b64encode(chunk).decode("ascii")
            await websocket.send_json({
                "event": "media",
                "stream_sid": stream_sid,
                "media": {
                    "payload": payload_b64,
                },
            })
            if self.settings.voicelink_pacing_delay_ms > 0:
                await asyncio.sleep(self.settings.voicelink_pacing_delay_ms / 1000.0)

    async def _send_mark(self, websocket: WebSocket, stream_sid: str, mark_name: str) -> None:
        """Sends a synchronization mark event to VoiceLink."""
        await websocket.send_json({
            "event": "mark",
            "stream_sid": stream_sid,
            "mark": {
                "name": mark_name,
            },
        })

    async def _send_clear(self, websocket: WebSocket, stream_sid: str) -> None:
        """Sends a clear event to flush VoiceLink audio playback buffer."""
        await websocket.send_json({
            "event": "clear",
            "stream_sid": stream_sid,
        })

    async def _send_transfer(self, websocket: WebSocket, stream_sid: str, target_number: str) -> None:
        """Sends a call transfer instruction to VoiceLink."""
        await websocket.send_json({
            "event": "transfer",
            "stream_sid": stream_sid,
            "transfer": {
                "target": target_number,
            },
        })

    async def _send_error(self, websocket: WebSocket, stream_sid: str | None, message: str) -> None:
        """Sends a safe, structured error message over the WebSocket."""
        try:
            payload: dict[str, Any] = {
                "event": "error",
                "message": message,
            }
            if stream_sid:
                payload["stream_sid"] = stream_sid
            await websocket.send_json(payload)
        except Exception:
            pass


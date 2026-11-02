"""Speech Processing Abstraction and Concrete Implementations for VoiceLink.

Defines abstract base classes for Speech-to-Text (STT) and Text-to-Speech (TTS)
services operating on 8 kHz mono telephony audio (A-law and SLIN). Includes:
1. Deterministic mock implementations for local testing without external API keys or costs.
2. Concrete Groq Whisper STT (whisper-large-v3-turbo) via REST with VAD buffering.
3. Concrete Deepgram Aura TTS (/v1/speak) via REST with 8 kHz transcoding.
4. Factory functions enforcing fail-fast validation for production provider configuration.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.telephony.audio_codec import (
    AudioCodec,
    alaw_to_slin,
    calculate_duration_ms,
    calculate_frame_energy,
    chunk_audio_frames,
    generate_tone,
    normalize_codec,
    slin_to_alaw,
    slin_to_wav_bytes,
    validate_audio_frame,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# Speech Result Data Structures
# ==============================================================================


@dataclass
class TranscriptionResult:
    """Result of speech-to-text recognition."""

    text: str
    confidence: float = 1.0
    is_final: bool = True
    language: str = "en-US"
    duration_ms: int = 0


@dataclass
class SynthesisResult:
    """Result of text-to-speech synthesis."""

    audio_bytes: bytes
    codec: AudioCodec
    sample_rate: int = 8000
    channels: int = 1
    duration_ms: int = 0


# ==============================================================================
# Abstract Service Interfaces
# ==============================================================================


class SpeechToTextService(ABC):
    """Abstract interface for transcribing telephony caller audio."""

    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult:
        """Transcribes a complete utterance buffer into text."""
        pass

    @abstractmethod
    async def transcribe_chunk(
        self,
        chunk: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult | None:
        """Streams an audio chunk (e.g. 20ms frame).

        Returns partial/final result if an utterance boundary is reached,
        or None if more audio is needed.
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Resets streaming buffers and turn counters between conversational turns."""
        pass


class TextToSpeechService(ABC):
    """Abstract interface for synthesizing receptionist responses into telephony audio."""

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> SynthesisResult:
        """Synthesizes text into 8 kHz mono audio in the specified codec (ALAW or SLIN)."""
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> AsyncIterator[bytes]:
        """Synthesizes text and yields discrete 20ms frames for real-time streaming."""
        pass


# ==============================================================================
# Deterministic Mock Implementations (Local, Offline, Zero Cost)
# ==============================================================================


class MockSpeechToTextService(SpeechToTextService):
    """Offline STT implementation for automated testing.

    Allows tests to inject predictable transcripts via set_script() or
    add_script_turn(), while validating incoming audio frame formats and lengths.
    """

    def __init__(self, default_transcript: str = "I would like to book an appointment"):
        self.default_transcript = default_transcript
        self._script: list[str] = []
        self._buffered_chunks: list[bytes] = []
        self._total_bytes_received: int = 0
        self._last_codec: AudioCodec | None = None

    def set_script(self, transcripts: list[str]) -> None:
        """Sets a sequence of transcripts to be returned on consecutive turns."""
        self._script = list(transcripts)

    def add_script_turn(self, transcript: str) -> None:
        """Appends a transcript to the end of the script queue."""
        self._script.append(transcript)

    @property
    def total_bytes_received(self) -> int:
        return self._total_bytes_received

    @property
    def buffered_chunk_count(self) -> int:
        return len(self._buffered_chunks)

    async def transcribe(
        self,
        audio_data: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult:
        normalized = normalize_codec(codec)
        validate_audio_frame(audio_data, normalized)

        self._total_bytes_received += len(audio_data)
        self._last_codec = normalized
        duration = calculate_duration_ms(audio_data, normalized)

        # Pop next script entry or fall back to default
        if self._script:
            text = self._script.pop(0)
        else:
            text = self.default_transcript

        logger.debug(
            "MockSTT transcribed %d bytes (%s) -> '%s'",
            len(audio_data),
            normalized.value,
            text,
        )
        return TranscriptionResult(
            text=text,
            confidence=0.98,
            is_final=True,
            language="en-US",
            duration_ms=duration,
        )

    async def transcribe_chunk(
        self,
        chunk: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult | None:
        normalized = normalize_codec(codec)
        validate_audio_frame(chunk, normalized)

        self._buffered_chunks.append(chunk)
        self._total_bytes_received += len(chunk)
        self._last_codec = normalized

        # Simulate turn boundary every 10 frames (~200ms)
        if len(self._buffered_chunks) >= 10:
            total_audio = b"".join(self._buffered_chunks)
            self._buffered_chunks.clear()
            return await self.transcribe(total_audio, normalized)

        return None

    def reset(self) -> None:
        self._buffered_chunks.clear()


class MockTextToSpeechService(TextToSpeechService):
    """Offline TTS implementation for automated testing.

    Generates valid, well-formed 8 kHz mono audio (A-law or SLIN) matching the
    length and structure of the input text, without any external network dependency.
    """

    def __init__(self, tone_frequency_hz: float = 440.0):
        self.tone_frequency_hz = tone_frequency_hz
        self.synthesized_calls: list[tuple[str, AudioCodec]] = []

    async def synthesize(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> SynthesisResult:
        normalized = normalize_codec(codec)
        clean_text = (text or "").strip()

        # Duration estimated realistically based on word count: ~250ms per word (min 100ms)
        word_count = max(1, len(clean_text.split())) if clean_text else 1
        duration_ms = min(5000, max(100, word_count * 250))

        # Generate valid 8 kHz audio tone for the calculated duration
        audio_data = generate_tone(
            frequency_hz=self.tone_frequency_hz,
            duration_ms=duration_ms,
            codec=normalized,
            amplitude=0.3,
        )

        self.synthesized_calls.append((clean_text, normalized))
        logger.debug(
            "MockTTS synthesized '%s' -> %d bytes (%s, %dms)",
            clean_text[:40],
            len(audio_data),
            normalized.value,
            duration_ms,
        )

        return SynthesisResult(
            audio_bytes=audio_data,
            codec=normalized,
            sample_rate=8000,
            channels=1,
            duration_ms=duration_ms,
        )

    async def synthesize_stream(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> AsyncIterator[bytes]:
        result = await self.synthesize(text, codec, voice=voice)
        frames = chunk_audio_frames(result.audio_bytes, result.codec, frame_duration_ms=20)
        for frame in frames:
            yield frame


# ==============================================================================
# Production Providers (Groq Whisper STT & Deepgram Aura TTS)
# ==============================================================================


class GroqWhisperSpeechToTextService(SpeechToTextService):
    """Production Speech-to-Text provider using Groq Whisper API (whisper-large-v3-turbo).

    Buffers streaming telephony audio frames (8 kHz A-law or SLIN), uses Voice Activity
    Detection (RMS energy threshold) to detect utterance boundaries, constructs an in-memory
    44-byte RIFF WAV container, and transcribes via Groq REST API.
    """

    GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-large-v3-turbo",
        client: httpx.AsyncClient | None = None,
        vad_threshold: float = 300.0,
        vad_silence_frames: int = 35,
        timeout_seconds: float = 10.0,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("Groq API key must not be empty.")
        self.api_key = api_key.strip()
        self.model = model
        self._client = client
        self.vad_threshold = vad_threshold
        self.vad_silence_frames = vad_silence_frames
        self.timeout_seconds = timeout_seconds

        # Utterance buffering state
        self._speech_frames: list[bytes] = []
        self._silence_frames_count: int = 0
        self._is_speech_active: bool = False
        self._total_bytes_received: int = 0
        self._last_codec: AudioCodec | None = None

    @property
    def is_speech_active(self) -> bool:
        return self._is_speech_active

    @property
    def buffered_frame_count(self) -> int:
        return len(self._speech_frames)

    async def transcribe(
        self,
        audio_data: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult:
        normalized = normalize_codec(codec)
        validate_audio_frame(audio_data, normalized)

        if not audio_data:
            return TranscriptionResult(text="", confidence=0.0, duration_ms=0)

        # Ensure 16-bit linear PCM at 8 kHz mono for RIFF WAV
        if normalized == AudioCodec.ALAW:
            slin_pcm = alaw_to_slin(audio_data)
        else:
            slin_pcm = audio_data

        duration = calculate_duration_ms(audio_data, normalized)
        wav_bytes = slin_to_wav_bytes(slin_pcm)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        files = {
            "file": ("audio.wav", wav_bytes, "audio/wav"),
        }
        data = {
            "model": self.model,
            "response_format": "json",
            "temperature": "0",
        }

        try:
            if self._client is not None:
                resp = await self._client.post(
                    self.GROQ_TRANSCRIPTION_URL,
                    headers=headers,
                    files=files,
                    data=data,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(
                        self.GROQ_TRANSCRIPTION_URL,
                        headers=headers,
                        files=files,
                        data=data,
                    )

            if resp.status_code == 200:
                result_data = resp.json()
                transcript = (result_data.get("text") or "").strip()
                logger.info(
                    "Groq Whisper transcribed %d ms audio -> '%s'",
                    duration,
                    transcript[:60],
                )
                return TranscriptionResult(
                    text=transcript,
                    confidence=0.95 if transcript else 0.0,
                    is_final=True,
                    language="en",
                    duration_ms=duration,
                )
            elif resp.status_code == 429:
                logger.warning("Groq Whisper API rate limited (HTTP 429).")
                return TranscriptionResult(text="", confidence=0.0, duration_ms=duration)
            else:
                logger.error(
                    "Groq Whisper API error (status=%d, message=%s)",
                    resp.status_code,
                    resp.text[:200],
                )
                return TranscriptionResult(text="", confidence=0.0, duration_ms=duration)
        except httpx.TimeoutException:
            logger.warning("Groq Whisper API request timed out after %.1fs", self.timeout_seconds)
            return TranscriptionResult(text="", confidence=0.0, duration_ms=duration)
        except Exception as exc:
            logger.error("Groq Whisper transcription exception: %s", exc)
            return TranscriptionResult(text="", confidence=0.0, duration_ms=duration)

    async def transcribe_chunk(
        self,
        chunk: bytes,
        codec: AudioCodec | str,
    ) -> TranscriptionResult | None:
        normalized = normalize_codec(codec)
        validate_audio_frame(chunk, normalized)

        energy = calculate_frame_energy(chunk, normalized)
        self._last_codec = normalized
        self._total_bytes_received += len(chunk)

        if energy >= self.vad_threshold:
            # Active speech detected
            self._is_speech_active = True
            self._silence_frames_count = 0
            self._speech_frames.append(chunk)

            # Cap maximum utterance buffer at 15 seconds (750 frames) to bound memory
            if len(self._speech_frames) >= 750:
                logger.info("VAD max utterance buffer reached (15s); forcing transcription.")
                utterance_audio = b"".join(self._speech_frames)
                self.reset()
                return await self.transcribe(utterance_audio, normalized)
            return None
        else:
            # Silence or low-energy background
            if self._is_speech_active:
                self._silence_frames_count += 1
                self._speech_frames.append(chunk)

                if self._silence_frames_count >= self.vad_silence_frames:
                    # End of utterance reached
                    speech_frames_count = len(self._speech_frames) - self._silence_frames_count
                    if speech_frames_count < 10:
                        logger.debug(
                            "Discarded brief noise spike (%d speech frames) below minimum utterance length.",
                            speech_frames_count,
                        )
                        self.reset()
                        return None

                    # Trim excess trailing silence frames beyond 10 frames (200ms padding)
                    excess_silence = self._silence_frames_count - 10
                    frames_to_send = (
                        self._speech_frames[:-excess_silence]
                        if excess_silence > 0
                        else self._speech_frames
                    )
                    utterance_audio = b"".join(frames_to_send)
                    self.reset()
                    return await self.transcribe(utterance_audio, normalized)
            # Leading silence is dropped
            return None

    def reset(self) -> None:
        self._speech_frames.clear()
        self._silence_frames_count = 0
        self._is_speech_active = False


class DeepgramAuraTextToSpeechService(TextToSpeechService):
    """Production Text-to-Speech provider using Deepgram Aura API (/v1/speak).

    Synthesizes conversational text into raw 16-bit linear PCM (linear16, 8000 Hz, mono)
    and transcodes to ITU-T G.711 A-law when required by telephony carriers.
    """

    DEEPGRAM_SPEAK_URL = "https://api.deepgram.com/v1/speak"

    def __init__(
        self,
        api_key: str,
        model: str = "aura-asteria-en",
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 10.0,
    ):
        if not api_key or not api_key.strip():
            raise ValueError("Deepgram API key must not be empty.")
        self.api_key = api_key.strip()
        self.model = model
        self._client = client
        self.timeout_seconds = timeout_seconds

    async def synthesize(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> SynthesisResult:
        normalized = normalize_codec(codec)
        clean_text = (text or "").strip()
        if not clean_text:
            return SynthesisResult(
                audio_bytes=b"",
                codec=normalized,
                sample_rate=8000,
                channels=1,
                duration_ms=0,
            )

        selected_model = voice or self.model
        params = {
            "model": selected_model,
            "encoding": "linear16",
            "sample_rate": "8000",
            "container": "none",
        }
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json",
        }
        json_body = {"text": clean_text}

        try:
            if self._client is not None:
                resp = await self._client.post(
                    self.DEEPGRAM_SPEAK_URL,
                    params=params,
                    headers=headers,
                    json=json_body,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    resp = await client.post(
                        self.DEEPGRAM_SPEAK_URL,
                        params=params,
                        headers=headers,
                        json=json_body,
                    )

            if resp.status_code != 200:
                logger.error(
                    "Deepgram Aura TTS error (status=%d, message=%s)",
                    resp.status_code,
                    resp.text[:200],
                )
                raise RuntimeError(f"Deepgram TTS API returned HTTP {resp.status_code}")

            raw_pcm16 = resp.content

            # Strip RIFF WAV container header if unexpectedly returned by server or proxy
            if raw_pcm16.startswith(b"RIFF") and len(raw_pcm16) >= 44 and raw_pcm16[8:12] == b"WAVE":
                logger.debug("Stripped unexpected 44-byte WAV container header from Deepgram response.")
                raw_pcm16 = raw_pcm16[44:]

            validate_audio_frame(raw_pcm16, AudioCodec.SLIN)

            if normalized == AudioCodec.ALAW:
                audio_bytes = slin_to_alaw(raw_pcm16)
            else:
                audio_bytes = raw_pcm16

            duration = calculate_duration_ms(audio_bytes, normalized)
            logger.info(
                "Deepgram Aura synthesized '%s' -> %d bytes (%s, %dms)",
                clean_text[:40],
                len(audio_bytes),
                normalized.value,
                duration,
            )
            return SynthesisResult(
                audio_bytes=audio_bytes,
                codec=normalized,
                sample_rate=8000,
                channels=1,
                duration_ms=duration,
            )
        except httpx.TimeoutException:
            logger.error("Deepgram Aura TTS request timed out after %.1fs", self.timeout_seconds)
            raise RuntimeError("Deepgram TTS request timed out")
        except Exception as exc:
            logger.error("Deepgram Aura TTS synthesis failed: %s", exc)
            raise

    async def synthesize_stream(
        self,
        text: str,
        codec: AudioCodec | str,
        voice: str | None = None,
    ) -> AsyncIterator[bytes]:
        result = await self.synthesize(text, codec, voice=voice)
        frames = chunk_audio_frames(result.audio_bytes, result.codec, frame_duration_ms=20)
        for frame in frames:
            yield frame


# ==============================================================================
# Provider Factory Functions (Fail-Fast Validation)
# ==============================================================================


def get_speech_to_text_service(
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> SpeechToTextService:
    """Factory creating the configured Speech-to-Text service.

    Fails fast with ValueError if a real provider is chosen but its API key is missing.
    Never silently falls back to mock speech in production.
    """
    cfg = settings or get_settings()
    provider = (cfg.stt_provider or "mock").strip().lower()

    if provider == "mock":
        return MockSpeechToTextService()
    elif provider == "groq":
        key = (cfg.groq_api_key or "").strip()
        if not key:
            raise ValueError(
                "GROQ_API_KEY environment variable is required when STT_PROVIDER='groq'. "
                "Configure GROQ_API_KEY or set STT_PROVIDER='mock'."
            )
        return GroqWhisperSpeechToTextService(
            api_key=key,
            client=client,
            vad_threshold=cfg.voicelink_vad_silence_threshold,
            vad_silence_frames=cfg.voicelink_vad_silence_frames,
        )
    else:
        raise ValueError(f"Unsupported STT provider '{provider}'. Supported: 'mock', 'groq'")


def get_text_to_speech_service(
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> TextToSpeechService:
    """Factory creating the configured Text-to-Speech service.

    Fails fast with ValueError if a real provider is chosen but its API key is missing.
    Never silently falls back to mock speech in production.
    """
    cfg = settings or get_settings()
    provider = (cfg.tts_provider or "mock").strip().lower()

    if provider == "mock":
        return MockTextToSpeechService()
    elif provider == "deepgram":
        key = (cfg.deepgram_api_key or "").strip()
        if not key:
            raise ValueError(
                "DEEPGRAM_API_KEY environment variable is required when TTS_PROVIDER='deepgram'. "
                "Configure DEEPGRAM_API_KEY or set TTS_PROVIDER='mock'."
            )
        return DeepgramAuraTextToSpeechService(
            api_key=key,
            model=cfg.deepgram_tts_model,
            client=client,
        )
    else:
        raise ValueError(f"Unsupported TTS provider '{provider}'. Supported: 'mock', 'deepgram'")

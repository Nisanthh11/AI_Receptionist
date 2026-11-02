"""Offline Unit Tests for Groq Whisper STT, Deepgram Aura TTS, and Speech Factories.

Tests provider validation, fail-fast configuration checks, audio packaging,
VAD utterance buffering, and offline HTTP mocking using httpx.MockTransport.
Strictly offline: zero external network calls, zero costs.
"""
from __future__ import annotations

import asyncio
import io
import wave
import httpx
import pytest

from app.core.config import Settings
from app.telephony.audio_codec import (
    AudioCodec,
    calculate_frame_energy,
    generate_silence,
    generate_tone,
    slin_to_wav_bytes,
)
from app.telephony.speech_service import (
    DeepgramAuraTextToSpeechService,
    GroqWhisperSpeechToTextService,
    MockSpeechToTextService,
    MockTextToSpeechService,
    SynthesisResult,
    TranscriptionResult,
    get_speech_to_text_service,
    get_text_to_speech_service,
)
from app.telephony.voicelink_adapter import VoiceLinkCallSession, VoiceLinkWebSocketAdapter


def _run_async(coro):
    """Executes an async test coroutine using the standard library event loop."""
    return asyncio.run(coro)


# ==============================================================================
# Factory Configuration & Fail-Fast Tests
# ==============================================================================


def test_speech_factories_default_mock():
    """Confirms default configuration instantiates mock speech services."""
    settings = Settings(
        stt_provider="mock",
        tts_provider="mock",
    )
    stt = get_speech_to_text_service(settings)
    tts = get_text_to_speech_service(settings)

    assert isinstance(stt, MockSpeechToTextService)
    assert isinstance(tts, MockTextToSpeechService)


def test_stt_factory_groq_missing_key_raises_error():
    """Confirms selecting Groq STT without GROQ_API_KEY fails fast with ValueError."""
    settings = Settings(
        stt_provider="groq",
        groq_api_key=None,
    )
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is required"):
        get_speech_to_text_service(settings)

    # Empty string also rejected
    settings_empty = Settings(
        stt_provider="groq",
        groq_api_key="   ",
    )
    with pytest.raises(ValueError, match="GROQ_API_KEY environment variable is required"):
        get_speech_to_text_service(settings_empty)


def test_tts_factory_deepgram_missing_key_raises_error():
    """Confirms selecting Deepgram TTS without DEEPGRAM_API_KEY fails fast with ValueError."""
    settings = Settings(
        tts_provider="deepgram",
        deepgram_api_key=None,
    )
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY environment variable is required"):
        get_text_to_speech_service(settings)

    settings_empty = Settings(
        tts_provider="deepgram",
        deepgram_api_key="   ",
    )
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY environment variable is required"):
        get_text_to_speech_service(settings_empty)


def test_factories_unsupported_provider_raises_error():
    """Confirms unrecognized provider names raise explicit errors."""
    settings = Settings(
        stt_provider="unsupported_provider",
        tts_provider="unsupported_provider",
    )
    with pytest.raises(ValueError, match="Unsupported STT provider"):
        get_speech_to_text_service(settings)

    with pytest.raises(ValueError, match="Unsupported TTS provider"):
        get_text_to_speech_service(settings)


def test_factories_valid_keys_return_concrete_instances():
    """Confirms valid API keys instantiate concrete service classes."""
    settings = Settings(
        stt_provider="groq",
        groq_api_key="gsk_test_mock_groq_key_12345",
        tts_provider="deepgram",
        deepgram_api_key="dg_test_mock_deepgram_key_67890",
    )
    stt = get_speech_to_text_service(settings)
    tts = get_text_to_speech_service(settings)

    assert isinstance(stt, GroqWhisperSpeechToTextService)
    assert stt.api_key == "gsk_test_mock_groq_key_12345"
    assert isinstance(tts, DeepgramAuraTextToSpeechService)
    assert tts.api_key == "dg_test_mock_deepgram_key_67890"


# ==============================================================================
# Groq Whisper STT Provider Tests (Offline with MockTransport)
# ==============================================================================


def test_groq_whisper_transcribe_success_slin():
    """Confirms Groq Whisper packages SLIN audio into valid WAV and parses response."""
    captured_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        # Verify headers
        assert request.headers.get("authorization") == "Bearer mock_groq_key"
        # Return OpenAI-compatible Groq transcription JSON
        return httpx.Response(
            status_code=200,
            json={"text": "I would like to book a dental checkup tomorrow at 2 PM"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_groq_key",
        client=client,
    )

    # 1 second of SLIN 440 Hz audio (16000 bytes = 8000 samples)
    audio = generate_tone(frequency_hz=440.0, duration_ms=1000, codec=AudioCodec.SLIN)

    async def run_test():
        res = await stt.transcribe(audio, codec=AudioCodec.SLIN)
        assert res.text == "I would like to book a dental checkup tomorrow at 2 PM"
        assert res.confidence > 0.9
        assert res.duration_ms == 1000

    _run_async(run_test())
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req.method == "POST"
    assert "audio/transcriptions" in str(req.url)


def test_groq_whisper_transcribe_success_alaw():
    """Confirms Groq Whisper transcodes A-law to 16-bit PCM before building WAV."""
    captured_payloads = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(request.content)
        return httpx.Response(
            status_code=200,
            json={"text": "Cancel my appointment"},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_groq_key",
        client=client,
    )

    # 500 ms of A-law audio (4000 bytes)
    alaw_audio = generate_tone(frequency_hz=440.0, duration_ms=500, codec=AudioCodec.ALAW)

    async def run_test():
        res = await stt.transcribe(alaw_audio, codec=AudioCodec.ALAW)
        assert res.text == "Cancel my appointment"
        assert res.duration_ms == 500

    _run_async(run_test())
    assert len(captured_payloads) == 1
    # Check that multipart payload contains WAV header: 'RIFF' and 'WAVE'
    body = captured_payloads[0]
    assert b"RIFF" in body
    assert b"WAVE" in body


def test_groq_whisper_handles_rate_limit_and_server_error():
    """Confirms HTTP 429 and 500 return empty transcription result without crashing."""
    status_to_return = [429]

    def mock_handler(request: httpx.Request) -> httpx.Response:
        code = status_to_return[0]
        return httpx.Response(
            status_code=code,
            json={"error": {"message": f"Error code {code}"}},
        )

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    stt = GroqWhisperSpeechToTextService(api_key="mock_key", client=client)
    audio = generate_tone(440.0, 200, AudioCodec.SLIN)

    async def run_test():
        # Test 429
        status_to_return[0] = 429
        r1 = await stt.transcribe(audio, AudioCodec.SLIN)
        assert r1.text == ""
        assert r1.confidence == 0.0

        # Test 500
        status_to_return[0] = 500
        r2 = await stt.transcribe(audio, AudioCodec.SLIN)
        assert r2.text == ""
        assert r2.confidence == 0.0

    _run_async(run_test())


def test_groq_whisper_handles_network_timeout():
    """Confirms network timeout returns empty transcript gracefully."""

    def mock_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Read timed out")

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    stt = GroqWhisperSpeechToTextService(api_key="mock_key", client=client)
    audio = generate_tone(440.0, 200, AudioCodec.SLIN)

    async def run_test():
        res = await stt.transcribe(audio, AudioCodec.SLIN)
        assert res.text == ""
        assert res.confidence == 0.0

    _run_async(run_test())


# ==============================================================================
# VAD & Utterance Buffering Tests
# ==============================================================================


def test_groq_whisper_vad_buffering_and_silence_boundary():
    """Confirms VAD detects speech, buffers frames, and triggers transcription on silence."""
    transcriptions_called = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        transcriptions_called.append(True)
        return httpx.Response(status_code=200, json={"text": "Hello receptionist"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_key",
        client=client,
        vad_threshold=200.0,
        vad_silence_frames=5,  # 5 frames of silence = trigger
    )

    # High energy frame (sine wave at 0.5 amplitude has RMS ~11500)
    speech_frame = generate_tone(frequency_hz=440.0, duration_ms=20, codec=AudioCodec.ALAW, amplitude=0.5)
    # Silence frame (standard ITU-T A-law 0xD5 has RMS 0.0)
    silence_frame = generate_silence(duration_ms=20, codec=AudioCodec.ALAW)

    async def run_test():
        # 1. Leading silence: ignored
        res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)
        assert res is None
        assert not stt.is_speech_active
        assert stt.buffered_frame_count == 0

        # 2. Feed 15 active speech frames (~300ms)
        for _ in range(15):
            res = await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)
            assert res is None
        assert stt.is_speech_active
        assert stt.buffered_frame_count == 15

        # 3. Feed 4 silence frames: boundary not yet reached (silence_frames threshold = 5)
        for _ in range(4):
            res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)
            assert res is None

        # 4. Feed 5th silence frame: triggers end of utterance
        res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)
        assert res is not None
        assert res.text == "Hello receptionist"
        # State should be reset after triggering
        assert not stt.is_speech_active
        assert stt.buffered_frame_count == 0

    _run_async(run_test())
    assert len(transcriptions_called) == 1


def test_groq_whisper_vad_discards_sub_200ms_noise_spike():
    """Confirms short noise transients (< 10 frames = 200ms) are discarded without API call."""
    api_called = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        api_called.append(True)
        return httpx.Response(status_code=200, json={"text": "noise"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_key",
        client=client,
        vad_threshold=200.0,
        vad_silence_frames=3,
    )

    speech_frame = generate_tone(440.0, 20, AudioCodec.ALAW, amplitude=0.5)
    silence_frame = generate_silence(20, AudioCodec.ALAW)

    async def run_test():
        # Only 2 speech frames (40ms, below 10 frames min threshold)
        await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)
        await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)

        # Then 3 silence frames to trigger boundary
        await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)
        await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)
        res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)

        # Must be discarded as noise spike: res is None and no API call made
        assert res is None

    _run_async(run_test())
    assert len(api_called) == 0


# ==============================================================================
# Deepgram Aura TTS Provider Tests (Offline with MockTransport)
# ==============================================================================


def test_deepgram_aura_synthesize_slin():
    """Confirms Deepgram Aura requests raw linear16 at 8 kHz mono and returns SLIN."""
    captured_requests = []
    # 320 bytes = 20ms of 16-bit linear PCM
    mock_pcm_audio = b"\x00\x00" * 160

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        assert request.headers.get("authorization") == "Token mock_deepgram_key"
        assert request.url.params.get("encoding") == "linear16"
        assert request.url.params.get("sample_rate") == "8000"
        assert request.url.params.get("container") == "none"
        return httpx.Response(status_code=200, content=mock_pcm_audio)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    tts = DeepgramAuraTextToSpeechService(
        api_key="mock_deepgram_key",
        model="aura-asteria-en",
        client=client,
    )

    async def run_test():
        res = await tts.synthesize("Hello, welcome to our clinic.", codec=AudioCodec.SLIN)
        assert res.codec == AudioCodec.SLIN
        assert res.audio_bytes == mock_pcm_audio
        assert res.sample_rate == 8000
        assert res.duration_ms == 20

    _run_async(run_test())
    assert len(captured_requests) == 1


def test_deepgram_aura_synthesize_alaw_transcoding():
    """Confirms Deepgram Aura automatically transcodes linear16 to A-law."""
    # 3200 bytes of 16-bit PCM = 1600 samples = 200ms
    mock_pcm = generate_tone(440.0, 200, AudioCodec.SLIN)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=mock_pcm)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    tts = DeepgramAuraTextToSpeechService(
        api_key="mock_deepgram_key",
        client=client,
    )

    async def run_test():
        res = await tts.synthesize("Your appointment is confirmed.", codec=AudioCodec.ALAW)
        assert res.codec == AudioCodec.ALAW
        # A-law has 1 byte per sample (1600 bytes for 200ms)
        assert len(res.audio_bytes) == 1600
        assert res.duration_ms == 200

    _run_async(run_test())


def test_deepgram_aura_empty_text():
    """Confirms synthesizing empty or whitespace text returns empty audio without API call."""
    api_called = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        api_called.append(True)
        return httpx.Response(status_code=200, content=b"")

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_test():
        res1 = await tts.synthesize("", AudioCodec.ALAW)
        assert res1.audio_bytes == b""
        assert res1.duration_ms == 0

        res2 = await tts.synthesize("    ", AudioCodec.SLIN)
        assert res2.audio_bytes == b""
        assert res2.duration_ms == 0

    _run_async(run_test())
    assert len(api_called) == 0


def test_deepgram_aura_handles_api_error_and_timeout():
    """Confirms HTTP 400/500 and timeouts raise descriptive RuntimeError."""

    def mock_error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=401, json={"err_code": "INVALID_AUTH"})

    transport = httpx.MockTransport(mock_error_handler)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_error_test():
        with pytest.raises(RuntimeError, match="Deepgram TTS API returned HTTP 401"):
            await tts.synthesize("Test error", AudioCodec.ALAW)

    _run_async(run_error_test())

    def mock_timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Timeout")

    t2 = httpx.MockTransport(mock_timeout_handler)
    c2 = httpx.AsyncClient(transport=t2)
    tts2 = DeepgramAuraTextToSpeechService(api_key="mock_key", client=c2)

    async def run_timeout_test():
        with pytest.raises(RuntimeError, match="Deepgram TTS request timed out"):
            await tts2.synthesize("Test timeout", AudioCodec.ALAW)

    _run_async(run_timeout_test())


def test_deepgram_aura_synthesize_stream_yields_20ms_frames():
    """Confirms synthesize_stream yields discrete 20ms frames."""
    # 60ms of audio (960 bytes SLIN = 3 frames of 320 bytes)
    mock_pcm = generate_tone(440.0, 60, AudioCodec.SLIN)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=mock_pcm)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_test():
        frames = []
        async for frame in tts.synthesize_stream("Streaming audio test", AudioCodec.SLIN):
            frames.append(frame)
        assert len(frames) == 3
        for f in frames:
            assert len(f) == 320  # Exact 20ms SLIN frame

    _run_async(run_test())


# ==============================================================================
# WAV Container Integrity Check
# ==============================================================================


def test_slin_to_wav_bytes_header_compliance():
    """Validates that slin_to_wav_bytes produces a fully compliant standard RIFF/WAVE file."""
    # 100ms of audio (1600 bytes = 800 samples)
    slin_data = generate_tone(440.0, 100, AudioCodec.SLIN)
    wav_bytes = slin_to_wav_bytes(slin_data, sample_rate=8000)

    # Validate with standard library wave module
    buf = io.BytesIO(wav_bytes)
    with wave.open(buf, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 8000
        assert wf.getnframes() == 800
        frames = wf.readframes(800)
        assert frames == slin_data


def test_groq_whisper_vad_discards_transient_with_default_35_silence_frames():
    """Confirms short click (2 frames) followed by default 35 silence frames is discarded."""
    api_called = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        api_called.append(True)
        return httpx.Response(status_code=200, json={"text": "noise"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_key",
        client=client,
        vad_threshold=200.0,
        vad_silence_frames=35,  # Default 35 frames (700ms)
    )

    speech_frame = generate_tone(440.0, 20, AudioCodec.ALAW, amplitude=0.5)
    silence_frame = generate_silence(20, AudioCodec.ALAW)

    async def run_test():
        # 2 frames of speech (40ms)
        await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)
        await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)

        # 35 frames of silence
        res = None
        for _ in range(35):
            res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)

        # Must be discarded without any Groq API request
        assert res is None
        assert len(api_called) == 0

    _run_async(run_test())


def test_groq_whisper_vad_trims_excess_trailing_silence():
    """Confirms 35 frames of trailing silence is trimmed to 10 frames (200ms) before API call."""
    captured_payloads = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(request.content)
        return httpx.Response(status_code=200, json={"text": "Yes I want that slot"})

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)

    stt = GroqWhisperSpeechToTextService(
        api_key="mock_key",
        client=client,
        vad_threshold=200.0,
        vad_silence_frames=35,
    )

    speech_frame = generate_tone(440.0, 20, AudioCodec.ALAW, amplitude=0.5)
    silence_frame = generate_silence(20, AudioCodec.ALAW)

    async def run_test():
        # 15 frames of speech (300ms)
        for _ in range(15):
            await stt.transcribe_chunk(speech_frame, AudioCodec.ALAW)

        # 35 frames of silence
        res = None
        for _ in range(35):
            res = await stt.transcribe_chunk(silence_frame, AudioCodec.ALAW)

        assert res is not None
        assert res.text == "Yes I want that slot"
        assert res.duration_ms == 500  # 15 speech + 10 silence = 25 frames * 20ms = 500ms (trimmed from 1000ms!)

    _run_async(run_test())
    assert len(captured_payloads) == 1


def test_deepgram_aura_strips_unexpected_wav_header():
    """Confirms Deepgram TTS strips unexpected 44-byte WAV header without crashing."""
    raw_slin = generate_tone(440.0, 40, AudioCodec.SLIN)
    wav_container = slin_to_wav_bytes(raw_slin)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=wav_container)

    transport = httpx.MockTransport(mock_handler)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_test():
        res = await tts.synthesize("Test with header", AudioCodec.SLIN)
        assert res.audio_bytes == raw_slin
        assert res.duration_ms == 40

    _run_async(run_test())


def test_chunk_audio_frames_pads_final_partial_frame():
    """Confirms partial audio frames are padded with digital silence to exact 20ms frames."""
    from app.telephony.audio_codec import chunk_audio_frames, validate_audio_frame, ALAW_FRAME_BYTES

    # 50 bytes of A-law audio (partial frame, less than 160 bytes)
    partial_audio = b"\xaa" * 50
    chunks = chunk_audio_frames(partial_audio, AudioCodec.ALAW, frame_duration_ms=20)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert len(chunk) == ALAW_FRAME_BYTES
    assert chunk[:50] == b"\xaa" * 50
    # Remaining 110 bytes must be ITU-T A-law silence (0xD5)
    assert chunk[50:] == b"\xd5" * 110
    # Validates cleanly under exact_20ms_frame check
    validate_audio_frame(chunk, AudioCodec.ALAW, exact_20ms_frame=True)


# ==============================================================================
# Non-Fallback & Failure Handling Verification Tests
# ==============================================================================


def test_real_stt_provider_does_not_fallback_to_mock_on_groq_failure():
    """Confirms Groq STT failure returns empty text and NEVER falls back to mock transcripts."""
    def mock_500_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, json={"error": "Internal Server Error"})

    transport = httpx.MockTransport(mock_500_handler)
    client = httpx.AsyncClient(transport=transport)
    stt = GroqWhisperSpeechToTextService(api_key="mock_key", client=client)

    audio = generate_tone(440.0, 200, AudioCodec.SLIN)

    async def run_test():
        res = await stt.transcribe(audio, AudioCodec.SLIN)
        # Must be empty - never fallback to "I would like to book an appointment"
        assert res.text == ""
        assert res.confidence == 0.0
        assert "book" not in res.text.lower()

    _run_async(run_test())


def test_real_tts_provider_does_not_fallback_to_mock_on_deepgram_failure():
    """Confirms Deepgram TTS failure raises RuntimeError and NEVER falls back to mock tones."""
    def mock_500_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=500, content=b"Server error")

    transport = httpx.MockTransport(mock_500_handler)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_test():
        with pytest.raises(RuntimeError, match="Deepgram TTS API returned HTTP 500"):
            await tts.synthesize("Hello world", AudioCodec.ALAW)

    _run_async(run_test())


def test_groq_connection_error_handling():
    """Confirms httpx.ConnectError in Groq STT returns empty text safely without crashing."""
    def mock_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused by target host")

    transport = httpx.MockTransport(mock_connect_error)
    client = httpx.AsyncClient(transport=transport)
    stt = GroqWhisperSpeechToTextService(api_key="mock_key", client=client)
    audio = generate_tone(440.0, 200, AudioCodec.SLIN)

    async def run_test():
        res = await stt.transcribe(audio, AudioCodec.SLIN)
        assert res.text == ""
        assert res.confidence == 0.0

    _run_async(run_test())


def test_deepgram_connection_error_handling():
    """Confirms httpx.ConnectError in Deepgram TTS raises descriptive error safely."""
    def mock_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Failed to reach api.deepgram.com")

    transport = httpx.MockTransport(mock_connect_error)
    client = httpx.AsyncClient(transport=transport)
    tts = DeepgramAuraTextToSpeechService(api_key="mock_key", client=client)

    async def run_test():
        with pytest.raises(Exception):
            await tts.synthesize("Hello", AudioCodec.ALAW)

    _run_async(run_test())


# ==============================================================================
# Security & Secret Masking Verification Tests
# ==============================================================================


def test_voicelink_config_endpoint_reports_real_providers_without_exposing_secrets(client, monkeypatch):
    """Verifies /config reports real providers and auth status without leaking secrets."""
    import app.api.telephony_voicelink as tv

    test_settings = Settings(
        stt_provider="groq",
        tts_provider="deepgram",
        groq_api_key="gsk_super_secret_groq_key_9999",
        deepgram_api_key="dg_super_secret_deepgram_key_8888",
        voicelink_webhook_secret="ultra_secret_webhook_token_7777",
        environment="production",
    )
    monkeypatch.setattr(tv, "get_settings", lambda: test_settings)

    res = client.get("/api/telephony/voicelink/config")
    assert res.status_code == 200
    data = res.json()

    # Diagnostic metadata must be correct
    assert data["provider"] == "voicelink"
    assert data["mock_mode"] is False
    assert data["stt_provider"] == "groq"
    assert data["tts_provider"] == "deepgram"
    assert data["auth_configured"] is True
    assert data["auth_enforced"] is True

    # Critical security assertion: raw secrets MUST NEVER be present in the response
    assert "gsk_super_secret" not in res.text
    assert "dg_super_secret" not in res.text
    assert "ultra_secret" not in res.text


def test_websocket_full_call_with_mocked_real_providers(client, org):
    """End-to-end WebSocket call executing real Groq STT and Deepgram TTS with offline MockTransport."""
    import base64
    from app.main import app
    from app.api.telephony_voicelink import get_voicelink_adapter
    from app.telephony.audio_codec import ALAW_FRAME_BYTES

    # 1. Mock Groq STT handler
    def mock_groq_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, json={"text": "I would like to book an appointment"})

    # 2. Mock Deepgram TTS handler (returns 320 bytes of 16-bit PCM = 20ms audio)
    raw_linear16_pcm = b"\x00\x00" * 160

    def mock_deepgram_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code=200, content=raw_linear16_pcm)

    groq_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_groq_handler))
    deepgram_client = httpx.AsyncClient(transport=httpx.MockTransport(mock_deepgram_handler))

    stt_svc = GroqWhisperSpeechToTextService(
        api_key="mock_groq_key",
        client=groq_client,
        vad_threshold=200.0,
        vad_silence_frames=5,  # 5 silence frames to trigger boundary in test
    )
    tts_svc = DeepgramAuraTextToSpeechService(
        api_key="mock_dg_key",
        client=deepgram_client,
    )

    custom_adapter = VoiceLinkWebSocketAdapter(
        stt_factory=lambda: stt_svc,
        tts_factory=lambda: tts_svc,
    )
    app.dependency_overrides[get_voicelink_adapter] = lambda: custom_adapter

    try:
        with client.websocket_connect("/api/telephony/voicelink/ws") as ws:
            # Send handshake
            ws.send_json({"event": "connected", "protocol": "Call", "version": "1.0.0"})

            # Start call (codec A-law)
            ws.send_json({
                "event": "start",
                "stream_sid": "stream_real_prov_01",
                "start": {
                    "call_sid": "call_real_prov_01",
                    "from": "+919876543210",
                    "media_format": {"encoding": "alaw"},
                },
            })

            # Consume greeting audio and mark
            while True:
                msg = ws.receive_json()
                if msg.get("event") == "mark":
                    break

            # Send 12 speech frames (240ms speech > 200ms min threshold)
            speech_b64 = base64.b64encode(generate_tone(440.0, 20, AudioCodec.ALAW, amplitude=0.5)).decode("ascii")
            for _ in range(12):
                ws.send_json({
                    "event": "media",
                    "stream_sid": "stream_real_prov_01",
                    "media": {"payload": speech_b64, "track": "inbound"},
                })

            # Send 5 silence frames to trigger VAD end-of-utterance boundary
            silence_b64 = base64.b64encode(generate_silence(20, AudioCodec.ALAW)).decode("ascii")
            for _ in range(5):
                ws.send_json({
                    "event": "media",
                    "stream_sid": "stream_real_prov_01",
                    "media": {"payload": silence_b64, "track": "inbound"},
                })

            # Expect bot reply synthesized via mocked Deepgram
            reply_frames = 0
            while True:
                msg = ws.receive_json()
                if msg.get("event") == "media":
                    reply_frames += 1
                    assert len(base64.b64decode(msg["media"]["payload"])) == ALAW_FRAME_BYTES
                elif msg.get("event") == "mark":
                    break

            assert reply_frames > 0

            # Hang up call
            ws.send_json({"event": "stop", "stream_sid": "stream_real_prov_01"})
    finally:
        app.dependency_overrides.pop(get_voicelink_adapter, None)





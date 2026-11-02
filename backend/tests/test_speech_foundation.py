"""Unit tests for telephony audio codec utilities and mock speech processing services."""
from __future__ import annotations

import asyncio
import pytest

from app.telephony.audio_codec import (
    ALAW_FRAME_BYTES,
    FRAME_DURATION_MS,
    SLIN_FRAME_BYTES,
    TELEPHONY_SAMPLE_RATE,
    AudioCodec,
    AudioCodecError,
    InvalidAudioFrameError,
    UnsupportedCodecError,
    alaw_to_slin,
    calculate_duration_ms,
    chunk_audio_frames,
    generate_silence,
    generate_tone,
    normalize_codec,
    slin_to_alaw,
    validate_audio_frame,
)
from app.telephony.speech_service import (
    MockSpeechToTextService,
    MockTextToSpeechService,
    SynthesisResult,
    TranscriptionResult,
)


def _run_async(coro):
    """Executes an async test coroutine using the standard library event loop."""
    return asyncio.run(coro)


# ==============================================================================
# Audio Codec & Validation Tests
# ==============================================================================


def test_normalize_codec_valid_variants():
    """Confirms all standard alias strings for A-law and SLIN normalize correctly."""
    assert normalize_codec("alaw") == AudioCodec.ALAW
    assert normalize_codec("audio/alaw") == AudioCodec.ALAW
    assert normalize_codec("audio/x-alaw") == AudioCodec.ALAW
    assert normalize_codec("pcma") == AudioCodec.ALAW
    assert normalize_codec("g711a") == AudioCodec.ALAW
    assert normalize_codec(AudioCodec.ALAW) == AudioCodec.ALAW

    assert normalize_codec("slin") == AudioCodec.SLIN
    assert normalize_codec("slin16") == AudioCodec.SLIN
    assert normalize_codec("audio/l16") == AudioCodec.SLIN
    assert normalize_codec("pcm") == AudioCodec.SLIN
    assert normalize_codec("pcm16") == AudioCodec.SLIN
    assert normalize_codec(AudioCodec.SLIN) == AudioCodec.SLIN


def test_normalize_codec_unsupported_rejection():
    """Explicitly rejects unknown or unsupported codecs without guessing."""
    unsupported = ["audio/mulaw", "mulaw", "opus", "mp3", "aac", "slin8", "", "unknown"]
    for codec in unsupported:
        with pytest.raises(UnsupportedCodecError) as exc_info:
            normalize_codec(codec)
        assert "Unsupported or unrecognized audio codec" in str(exc_info.value)


def test_validate_audio_frame_slin_alignment():
    """SLIN frames must be 16-bit aligned (even byte count)."""
    # 320 bytes = 160 samples (exact 20ms) -> OK
    validate_audio_frame(b"\x00" * 320, AudioCodec.SLIN, exact_20ms_frame=True)

    # Odd byte count -> Rejected
    with pytest.raises(InvalidAudioFrameError) as exc:
        validate_audio_frame(b"\x00" * 319, AudioCodec.SLIN)
    assert "even byte count" in str(exc.value)

    # Inexact 20ms frame when exact requested -> Rejected
    with pytest.raises(InvalidAudioFrameError) as exc:
        validate_audio_frame(b"\x00" * 640, AudioCodec.SLIN, exact_20ms_frame=True)
    assert "must be exactly 320 bytes" in str(exc.value)


def test_validate_audio_frame_alaw_length():
    """A-law frames must match 1 byte per sample."""
    # 160 bytes = 160 samples (exact 20ms) -> OK
    validate_audio_frame(b"\xd5" * 160, AudioCodec.ALAW, exact_20ms_frame=True)

    # Inexact 20ms frame when exact requested -> Rejected
    with pytest.raises(InvalidAudioFrameError) as exc:
        validate_audio_frame(b"\xd5" * 150, AudioCodec.ALAW, exact_20ms_frame=True)
    assert "must be exactly 160 bytes" in str(exc.value)


def test_codec_non_interchangeability():
    """A-law frame size (160 bytes) is invalid as an exact 20ms SLIN frame (needs 320 bytes)."""
    alaw_frame = b"\xd5" * ALAW_FRAME_BYTES
    with pytest.raises(InvalidAudioFrameError):
        validate_audio_frame(alaw_frame, AudioCodec.SLIN, exact_20ms_frame=True)


def test_alaw_slin_transcoding_roundtrip():
    """Verifies pure Python ITU-T G.711 A-law encoding and decoding roundtrip."""
    # Generate 100ms 440Hz tone in SLIN (16-bit PCM)
    original_slin = generate_tone(440.0, 100, AudioCodec.SLIN)
    assert len(original_slin) == 1600  # 100ms * 8 samples/ms * 2 bytes = 1600 bytes

    # Convert SLIN -> ALAW
    alaw = slin_to_alaw(original_slin)
    assert len(alaw) == 800  # 800 samples * 1 byte = 800 bytes

    # Convert ALAW -> SLIN
    reconstructed_slin = alaw_to_slin(alaw)
    assert len(reconstructed_slin) == len(original_slin)

    # Empty conversion handling
    assert alaw_to_slin(b"") == b""
    assert slin_to_alaw(b"") == b""


def test_chunk_audio_frames():
    """Verifies audio frame chunking into 20ms packets for WebSocket streaming."""
    # 60ms of SLIN = 3 frames of 320 bytes
    slin_audio = generate_tone(500.0, 60, AudioCodec.SLIN)
    slin_chunks = chunk_audio_frames(slin_audio, AudioCodec.SLIN, frame_duration_ms=20)
    assert len(slin_chunks) == 3
    for chunk in slin_chunks:
        assert len(chunk) == SLIN_FRAME_BYTES

    # 40ms of A-law = 2 frames of 160 bytes
    alaw_audio = generate_silence(40, AudioCodec.ALAW)
    alaw_chunks = chunk_audio_frames(alaw_audio, AudioCodec.ALAW, frame_duration_ms=20)
    assert len(alaw_chunks) == 2
    for chunk in alaw_chunks:
        assert len(chunk) == ALAW_FRAME_BYTES


def test_calculate_duration_ms():
    """Verifies accurate millisecond calculation from audio byte counts."""
    # 8000 Hz, 1 channel: 160 samples = 20ms
    assert calculate_duration_ms(b"\xd5" * 160, AudioCodec.ALAW) == 20
    assert calculate_duration_ms(b"\x00" * 320, AudioCodec.SLIN) == 20
    assert calculate_duration_ms(b"\xd5" * 8000, AudioCodec.ALAW) == 1000
    assert calculate_duration_ms(b"\x00" * 16000, AudioCodec.SLIN) == 1000


def test_silence_generation():
    """Generates standard G.711 A-law digital zero (0xD5) and SLIN zero (0x00)."""
    silence_alaw = generate_silence(20, AudioCodec.ALAW)
    assert len(silence_alaw) == 160
    assert silence_alaw == b"\xd5" * 160

    silence_slin = generate_silence(20, AudioCodec.SLIN)
    assert len(silence_slin) == 320
    assert silence_slin == b"\x00\x00" * 160


# ==============================================================================
# Mock Speech-to-Text & Text-to-Speech Service Tests
# ==============================================================================


def test_mock_stt_default_and_scripted_turns():
    """Tests MockSpeechToTextService scripted queue and fallback behaviors."""
    async def _test():
        stt = MockSpeechToTextService(default_transcript="Default fallback speech")
        audio_frame = generate_silence(100, AudioCodec.ALAW)

        # 1. Without script: returns default transcript
        res1 = await stt.transcribe(audio_frame, AudioCodec.ALAW)
        assert isinstance(res1, TranscriptionResult)
        assert res1.text == "Default fallback speech"
        assert res1.confidence == 0.98
        assert res1.is_final is True
        assert res1.duration_ms == 100

        # 2. With script: returns queued transcripts in order
        stt.set_script([
            "Hello, I want to book an appointment",
            "Cardiology department please",
        ])
        res2 = await stt.transcribe(audio_frame, AudioCodec.ALAW)
        assert res2.text == "Hello, I want to book an appointment"

        res3 = await stt.transcribe(audio_frame, AudioCodec.ALAW)
        assert res3.text == "Cardiology department please"

        # 3. Exhausted script falls back to default
        res4 = await stt.transcribe(audio_frame, AudioCodec.ALAW)
        assert res4.text == "Default fallback speech"

    _run_async(_test())


def test_mock_stt_streaming_chunks():
    """Tests chunked streaming audio ingestion in MockSpeechToTextService."""
    async def _test():
        stt = MockSpeechToTextService()
        stt.set_script(["Streaming turn finished"])

        chunk = generate_silence(20, AudioCodec.SLIN)

        # Send 9 frames: should return None (buffering)
        for _ in range(9):
            result = await stt.transcribe_chunk(chunk, AudioCodec.SLIN)
            assert result is None

        assert stt.buffered_chunk_count == 9

        # 10th frame triggers turn completion
        result = await stt.transcribe_chunk(chunk, AudioCodec.SLIN)
        assert result is not None
        assert result.text == "Streaming turn finished"
        assert stt.buffered_chunk_count == 0

        # Reset clears buffers
        await stt.transcribe_chunk(chunk, AudioCodec.SLIN)
        assert stt.buffered_chunk_count == 1
        stt.reset()
        assert stt.buffered_chunk_count == 0

    _run_async(_test())


def test_mock_stt_validates_audio_format():
    """MockSTT enforces codec validation on incoming audio."""
    async def _test():
        stt = MockSpeechToTextService()
        with pytest.raises(UnsupportedCodecError):
            await stt.transcribe(b"dummy", "unsupported_codec")

        with pytest.raises(InvalidAudioFrameError):
            await stt.transcribe(b"\x00" * 3, AudioCodec.SLIN)  # odd bytes invalid for SLIN

    _run_async(_test())


def test_mock_tts_synthesize_alaw_and_slin():
    """Tests MockTextToSpeechService synthesis in both A-law and SLIN formats."""
    async def _test():
        tts = MockTextToSpeechService(tone_frequency_hz=440.0)

        # 1. Synthesize in A-law
        res_alaw = await tts.synthesize("Welcome to our clinic", AudioCodec.ALAW)
        assert isinstance(res_alaw, SynthesisResult)
        assert res_alaw.codec == AudioCodec.ALAW
        assert res_alaw.sample_rate == 8000
        assert res_alaw.channels == 1
        assert len(res_alaw.audio_bytes) > 0
        # Every byte in A-law is 1 sample; verify duration matches byte count
        assert calculate_duration_ms(res_alaw.audio_bytes, AudioCodec.ALAW) == res_alaw.duration_ms

        # 2. Synthesize in SLIN
        res_slin = await tts.synthesize("Welcome to our clinic", AudioCodec.SLIN)
        assert res_slin.codec == AudioCodec.SLIN
        assert len(res_slin.audio_bytes) % 2 == 0
        assert calculate_duration_ms(res_slin.audio_bytes, AudioCodec.SLIN) == res_slin.duration_ms

        # 3. Verify call tracking
        assert len(tts.synthesized_calls) == 2
        assert tts.synthesized_calls[0] == ("Welcome to our clinic", AudioCodec.ALAW)
        assert tts.synthesized_calls[1] == ("Welcome to our clinic", AudioCodec.SLIN)

    _run_async(_test())


def test_mock_tts_synthesize_stream_frames():
    """Tests that synthesize_stream yields discrete, well-formed 20ms frames."""
    async def _test():
        tts = MockTextToSpeechService()

        # Stream in A-law: each frame must be exactly 160 bytes
        alaw_frames = [frame async for frame in tts.synthesize_stream("Testing speech audio stream", AudioCodec.ALAW)]
        assert len(alaw_frames) > 0
        for frame in alaw_frames:
            assert len(frame) == ALAW_FRAME_BYTES
            validate_audio_frame(frame, AudioCodec.ALAW, exact_20ms_frame=True)

        # Stream in SLIN: each frame must be exactly 320 bytes
        slin_frames = [frame async for frame in tts.synthesize_stream("Testing speech audio stream", AudioCodec.SLIN)]
        assert len(slin_frames) > 0
        for frame in slin_frames:
            assert len(frame) == SLIN_FRAME_BYTES
            validate_audio_frame(frame, AudioCodec.SLIN, exact_20ms_frame=True)

    _run_async(_test())

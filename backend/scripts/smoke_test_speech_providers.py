"""Live API smoke test for Groq Whisper STT and Deepgram Aura TTS.

Validates real cloud connectivity and credentials for:
1. Deepgram Aura TTS: synthesizes a tiny 4-word phrase ("Hello, welcome to reception.")
2. Groq Whisper STT: transcribes the synthesized audio back to text

CRITICAL SAFETY RULES:
- Never prints, logs, or reveals secret API keys.
- Completely isolated: no database writes, no appointment bookings, no telephone calls, no WebSockets.
- Does not fall back to mock speech; reports real provider responses and HTTP status.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import get_settings
from app.telephony.audio_codec import AudioCodec, generate_tone, validate_audio_frame
from app.telephony.speech_service import (
    DeepgramAuraTextToSpeechService,
    GroqWhisperSpeechToTextService,
    get_speech_to_text_service,
    get_text_to_speech_service,
)


def _mask_key(key: str | None) -> str:
    """Masks API keys for safe, privacy-compliant terminal output."""
    if not key or not str(key).strip():
        return "[NOT CONFIGURED]"
    clean = str(key).strip()
    if len(clean) <= 8:
        return f"[SET, length={len(clean)}]"
    return f"{clean[:4]}...{clean[-4:]} (length={len(clean)})"


def _clean_err(msg: str, keys: list[str]) -> str:
    """Removes any accidental presence of API keys from error messages."""
    text = str(msg)
    for k in keys:
        if k and len(k) > 6 and k in text:
            text = text.replace(k, "[REDACTED_API_KEY]")
    return text


async def run_smoke_test() -> int:
    print("=" * 68)
    print("AI RECEPTIONIST - LIVE SPEECH PROVIDER SMOKE TEST")
    print("=" * 68)

    settings = get_settings()
    groq_key = (settings.groq_api_key or "").strip()
    deepgram_key = (settings.deepgram_api_key or "").strip()
    sensitive_keys = [groq_key, deepgram_key, settings.voicelink_webhook_secret or ""]

    print(f"STT_PROVIDER configured in .env   : {settings.stt_provider}")
    print(f"TTS_PROVIDER configured in .env   : {settings.tts_provider}")
    print(f"GROQ_API_KEY                     : {_mask_key(groq_key)}")
    print(f"DEEPGRAM_API_KEY                 : {_mask_key(deepgram_key)}")
    print(f"DEEPGRAM_TTS_MODEL               : {settings.deepgram_tts_model}")
    print("-" * 68)

    # Pre-flight check
    has_errors = False
    if settings.stt_provider != "groq":
        print(f"[ERROR] STT_PROVIDER is '{settings.stt_provider}', expected 'groq'.")
        has_errors = True
    if not groq_key:
        print("[ERROR] GROQ_API_KEY is not configured in backend/.env.")
        has_errors = True

    if settings.tts_provider != "deepgram":
        print(f"[ERROR] TTS_PROVIDER is '{settings.tts_provider}', expected 'deepgram'.")
        has_errors = True
    if not deepgram_key:
        print("[ERROR] DEEPGRAM_API_KEY is not configured in backend/.env.")
        has_errors = True

    if has_errors:
        print("-" * 68)
        print("RESULT: FAILED - Configuration error before making any network requests.")
        return 1

    tts_service = get_text_to_speech_service(settings)
    stt_service = get_speech_to_text_service(settings)

    if not isinstance(tts_service, DeepgramAuraTextToSpeechService):
        print(f"[ERROR] TTS service resolved to {type(tts_service).__name__}, not DeepgramAuraTextToSpeechService.")
        return 1
    if not isinstance(stt_service, GroqWhisperSpeechToTextService):
        print(f"[ERROR] STT service resolved to {type(stt_service).__name__}, not GroqWhisperSpeechToTextService.")
        return 1

    # --------------------------------------------------------------------------
    # Step 1: Deepgram Aura Text-to-Speech Test
    # --------------------------------------------------------------------------
    phrase = "Hello, welcome to reception."
    print("\n[1/2] Testing Deepgram Aura Text-to-Speech...")
    print(f"      Request text  : '{phrase}' (28 characters)")
    print(f"      Target codec  : ITU-T G.711 A-law (8 kHz mono)")
    print(f"      Target model  : {settings.deepgram_tts_model}")
    print("      Sending request to Deepgram API...")

    tts_audio: bytes | None = None
    start_t = time.perf_counter()
    try:
        synth_result = await tts_service.synthesize(phrase, codec=AudioCodec.ALAW)
        latency_tts = (time.perf_counter() - start_t) * 1000.0

        validate_audio_frame(synth_result.audio_bytes, AudioCodec.ALAW)
        tts_audio = synth_result.audio_bytes

        print(f"      [PASS] Deepgram TTS succeeded in {latency_tts:.1f} ms!")
        print(f"      Audio size    : {len(synth_result.audio_bytes):,} bytes")
        print(f"      Audio duration: {synth_result.duration_ms} ms (~{synth_result.duration_ms / 1000.0:.1f}s)")
        print(f"      Audio codec   : {synth_result.codec.value} (8000 Hz, 1 channel)")
    except Exception as exc:
        latency_tts = (time.perf_counter() - start_t) * 1000.0
        err_clean = _clean_err(str(exc), sensitive_keys)
        print(f"      [FAIL] Deepgram TTS failed after {latency_tts:.1f} ms:")
        print(f"             {type(exc).__name__}: {err_clean}")
        has_errors = True

    # --------------------------------------------------------------------------
    # Step 2: Groq Whisper Speech-to-Text Test
    # --------------------------------------------------------------------------
    print("\n[2/2] Testing Groq Whisper Speech-to-Text...")
    if tts_audio and len(tts_audio) > 0:
        audio_to_transcribe = tts_audio
        audio_source_desc = "real Deepgram synthesized audio from Step 1"
    else:
        # Fallback to tiny 1-second synthetic audio tone if Step 1 failed
        audio_to_transcribe = generate_tone(frequency_hz=440.0, duration_ms=1000, codec=AudioCodec.ALAW)
        audio_source_desc = "synthetic 1000ms audio sample (TTS audio was unavailable)"

    print(f"      Audio source  : {audio_source_desc}")
    print(f"      Audio size    : {len(audio_to_transcribe):,} bytes ({AudioCodec.ALAW.value})")
    print(f"      Target model  : whisper-large-v3-turbo")
    print("      Sending request to Groq API...")

    start_t = time.perf_counter()
    try:
        trans_result = await stt_service.transcribe(audio_to_transcribe, codec=AudioCodec.ALAW)
        latency_stt = (time.perf_counter() - start_t) * 1000.0

        print(f"      [PASS] Groq Whisper STT succeeded in {latency_stt:.1f} ms!")
        print(f"      Recognized    : '{trans_result.text}'")
        print(f"      Confidence    : {trans_result.confidence}")
        print(f"      Language      : {trans_result.language}")
    except Exception as exc:
        latency_stt = (time.perf_counter() - start_t) * 1000.0
        err_clean = _clean_err(str(exc), sensitive_keys)
        print(f"      [FAIL] Groq Whisper STT failed after {latency_stt:.1f} ms:")
        print(f"             {type(exc).__name__}: {err_clean}")
        has_errors = True

    # --------------------------------------------------------------------------
    # Summary
    # --------------------------------------------------------------------------
    print("\n" + "=" * 68)
    if not has_errors:
        print("OVERALL SMOKE TEST RESULT: PASSED")
        print("Both Deepgram Aura TTS and Groq Whisper STT are active and working.")
        print("=" * 68)
        return 0
    else:
        print("OVERALL SMOKE TEST RESULT: FAILED")
        print("One or more speech providers failed. Check error messages above.")
        print("=" * 68)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_smoke_test())
    sys.exit(exit_code)


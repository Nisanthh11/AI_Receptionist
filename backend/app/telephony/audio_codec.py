"""Telephony Audio Codec Utilities for VoiceLink & PSTN Audio Streams.

Provides pure Python ITU-T G.711 A-law encoding and decoding, signed linear PCM
(SLIN / 16-bit PCM at 8 kHz mono) manipulation, validation, and framing without
depending on the removed Python 3.13 standard library audioop module.
"""
from __future__ import annotations

import io
import math
import struct
import wave
from enum import Enum
from typing import Final

# Telephony Audio Constants
TELEPHONY_SAMPLE_RATE: Final[int] = 8000
TELEPHONY_CHANNELS: Final[int] = 1
FRAME_DURATION_MS: Final[int] = 20
SAMPLES_PER_FRAME: Final[int] = 160  # (8000 samples/sec * 0.02 sec)

# Frame sizes for standard 20ms telephony frames
ALAW_FRAME_BYTES: Final[int] = 160  # 160 samples * 1 byte/sample
SLIN_FRAME_BYTES: Final[int] = 320  # 160 samples * 2 bytes/sample (16-bit)


class AudioCodec(str, Enum):
    """Supported telephony audio formats."""

    ALAW = "alaw"  # ITU-T G.711 A-law, 8 kHz, 8-bit mono
    SLIN = "slin"  # Signed Linear PCM, 8 kHz, 16-bit little-endian mono


class AudioCodecError(ValueError):
    """Base error for audio codec validation and conversion failures."""


class UnsupportedCodecError(AudioCodecError):
    """Raised when an unrecognized or unsupported audio codec is requested."""


class InvalidAudioFrameError(AudioCodecError):
    """Raised when an audio frame has an invalid size or structure for its codec."""


# ==============================================================================
# ITU-T G.711 A-law Pure Python Lookup Tables (No audioop dependency)
# ==============================================================================

_SEG_A_END = [0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF]


def _compute_linear2alaw(pcm_val: int) -> int:
    """Encodes a single 16-bit signed PCM sample (-32768 to 32767) into an 8-bit A-law byte."""
    if pcm_val >= 0:
        mask = 0xD5  # Sign bit = 1, even bits inverted
    else:
        mask = 0x55  # Sign bit = 0, even bits inverted
        pcm_val = -pcm_val - 1

    if pcm_val < 0:
        pcm_val = 0
    elif pcm_val > 32767:
        pcm_val = 32767

    pcm_val >>= 3  # Convert 16-bit to 13-bit representation

    seg = 8
    for i in range(8):
        if pcm_val <= _SEG_A_END[i]:
            seg = i
            break

    if seg >= 8:
        return 0x7F ^ mask
    else:
        aval = (pcm_val >> 1) if seg == 0 else ((pcm_val >> seg) & 0x0F)
        aval |= seg << 4
        return aval ^ mask


def _compute_alaw2linear(a_val: int) -> int:
    """Decodes a single 8-bit A-law byte (0 to 255) into a 16-bit signed PCM sample."""
    a_val ^= 0x55
    t = (a_val & 0x0F) << 4
    seg = (a_val & 0x70) >> 4
    if seg == 0:
        t += 8
    elif seg == 1:
        t += 0x108
    else:
        t += 0x108
        t <<= seg - 1
    return t if (a_val & 0x80) else -t


# Precompute tables at module initialization for O(1) per-sample execution speed
# ALAW_TO_LINEAR_TABLE: maps uint8 (0..255) -> int16 (-32768..32767)
ALAW_TO_LINEAR_TABLE: Final[list[int]] = [_compute_alaw2linear(b) for b in range(256)]

# LINEAR_TO_ALAW_TABLE: maps int16 (-32768..32767) via offset (+32768) -> uint8
LINEAR_TO_ALAW_TABLE: Final[bytes] = bytes(_compute_linear2alaw(i - 32768) for i in range(65536))


# ==============================================================================
# Public Codec Functions
# ==============================================================================


def normalize_codec(raw_codec: str | AudioCodec) -> AudioCodec:
    """Normalizes and validates an audio codec string into AudioCodec enum.

    A-law and SLIN are NOT interchangeable. Any unsupported or ambiguous codec
    triggers an UnsupportedCodecError rather than a fallback guess.
    """
    if isinstance(raw_codec, AudioCodec):
        return raw_codec

    cleaned = (raw_codec or "").strip().lower()

    # Match A-law variations
    if cleaned in ("alaw", "audio/alaw", "audio/x-alaw", "pcma", "g711a", "g711_alaw"):
        return AudioCodec.ALAW

    # Match SLIN (Signed Linear 16-bit PCM, 8 kHz mono)
    if cleaned in ("slin", "slin16", "audio/l16", "pcm", "pcm16", "raw_pcm", "linear16"):
        return AudioCodec.SLIN

    raise UnsupportedCodecError(
        f"Unsupported or unrecognized audio codec: '{raw_codec}'. "
        f"VoiceLink integration strictly requires '{AudioCodec.ALAW.value}' or '{AudioCodec.SLIN.value}'."
    )


def validate_audio_frame(
    data: bytes,
    codec: AudioCodec | str,
    exact_20ms_frame: bool = False,
) -> None:
    """Explicitly verifies frame length and byte alignment for the given codec.

    Enforces that A-law (1 byte per sample) and SLIN (2 bytes per sample) cannot
    be accidentally mixed or misidentified.
    """
    normalized = normalize_codec(codec)

    if not isinstance(data, (bytes, bytearray)):
        raise InvalidAudioFrameError(f"Audio frame must be bytes or bytearray, got {type(data).__name__}.")

    byte_len = len(data)

    if normalized == AudioCodec.SLIN:
        # 16-bit PCM must have an even number of bytes
        if byte_len % 2 != 0:
            raise InvalidAudioFrameError(
                f"SLIN audio data must have an even byte count (16 bits per sample). Received {byte_len} bytes."
            )
        if exact_20ms_frame and byte_len != SLIN_FRAME_BYTES:
            raise InvalidAudioFrameError(
                f"Exact 20ms SLIN frame must be exactly {SLIN_FRAME_BYTES} bytes. Received {byte_len} bytes."
            )

    elif normalized == AudioCodec.ALAW:
        # A-law is 1 byte per sample
        if exact_20ms_frame and byte_len != ALAW_FRAME_BYTES:
            raise InvalidAudioFrameError(
                f"Exact 20ms A-law frame must be exactly {ALAW_FRAME_BYTES} bytes. Received {byte_len} bytes."
            )


def alaw_to_slin(alaw_data: bytes) -> bytes:
    """Converts 8-bit G.711 A-law audio bytes into 16-bit signed linear PCM (SLIN) bytes.

    Input: 8 kHz mono A-law (1 byte / sample).
    Output: 8 kHz mono signed 16-bit PCM little-endian (2 bytes / sample).
    """
    validate_audio_frame(alaw_data, AudioCodec.ALAW)
    if not alaw_data:
        return b""

    sample_count = len(alaw_data)
    # Fast unpack and pack via precomputed O(1) table
    table = ALAW_TO_LINEAR_TABLE
    samples = [table[b] for b in alaw_data]
    return struct.pack(f"<{sample_count}h", *samples)


def slin_to_alaw(slin_data: bytes) -> bytes:
    """Converts 16-bit signed linear PCM (SLIN) bytes into 8-bit G.711 A-law audio bytes.

    Input: 8 kHz mono signed 16-bit PCM little-endian (2 bytes / sample).
    Output: 8 kHz mono A-law (1 byte / sample).
    """
    validate_audio_frame(slin_data, AudioCodec.SLIN)
    if not slin_data:
        return b""

    sample_count = len(slin_data) // 2
    samples = struct.unpack(f"<{sample_count}h", slin_data)
    table = LINEAR_TO_ALAW_TABLE
    return bytes(table[s + 32768] for s in samples)


def chunk_audio_frames(
    audio_data: bytes,
    codec: AudioCodec | str,
    frame_duration_ms: int = FRAME_DURATION_MS,
) -> list[bytes]:
    """Splits an audio byte stream into discrete frames of the requested duration.

    Default is 20ms frames (160 bytes for A-law, 320 bytes for SLIN).
    Any trailing remainder smaller than a full frame is discarded or kept according
    to standard streaming packetization rules.
    """
    normalized = normalize_codec(codec)
    samples_per_chunk = int(TELEPHONY_SAMPLE_RATE * (frame_duration_ms / 1000.0))

    if normalized == AudioCodec.ALAW:
        chunk_bytes = samples_per_chunk
    else:  # SLIN
        chunk_bytes = samples_per_chunk * 2

    chunks: list[bytes] = []
    total_len = len(audio_data)

    for offset in range(0, total_len, chunk_bytes):
        chunk = audio_data[offset : offset + chunk_bytes]
        if len(chunk) == chunk_bytes:
            chunks.append(chunk)
        elif len(chunk) > 0:
            # Pad final partial frame with digital silence to guarantee complete audio playback
            # and exact 20ms frame validation compliance
            pad_len = chunk_bytes - len(chunk)
            silence_fill = (
                b"\xd5" * pad_len
                if normalized == AudioCodec.ALAW
                else b"\x00" * pad_len
            )
            chunks.append(chunk + silence_fill)

    return chunks


def calculate_duration_ms(data: bytes, codec: AudioCodec | str) -> int:
    """Calculates playback duration in milliseconds for an 8 kHz mono audio buffer."""
    normalized = normalize_codec(codec)
    validate_audio_frame(data, normalized)

    if normalized == AudioCodec.ALAW:
        sample_count = len(data)
    else:
        sample_count = len(data) // 2

    return int((sample_count / TELEPHONY_SAMPLE_RATE) * 1000)


def generate_silence(duration_ms: int, codec: AudioCodec | str) -> bytes:
    """Generates digital silence for the requested duration and codec.

    For SLIN: 0x0000 16-bit PCM values.
    For A-law: 0xD5 (standard ITU-T G.711 A-law digital zero).
    """
    normalized = normalize_codec(codec)
    sample_count = int(TELEPHONY_SAMPLE_RATE * (duration_ms / 1000.0))

    if normalized == AudioCodec.ALAW:
        return b"\xd5" * sample_count
    else:
        return b"\x00\x00" * sample_count


def generate_tone(
    frequency_hz: float,
    duration_ms: int,
    codec: AudioCodec | str,
    amplitude: float = 0.5,
) -> bytes:
    """Generates a synthetic sine tone at 8 kHz mono in pure Python.

    Useful for telephone beeps, prompts, and local mock testing without external TTS.
    """
    normalized = normalize_codec(codec)
    sample_count = int(TELEPHONY_SAMPLE_RATE * (duration_ms / 1000.0))

    # Clamp amplitude between 0.0 and 1.0
    amp = max(0.0, min(1.0, amplitude)) * 32767.0
    angular_freq = 2.0 * math.pi * frequency_hz / TELEPHONY_SAMPLE_RATE

    samples = [int(amp * math.sin(angular_freq * i)) for i in range(sample_count)]
    slin_bytes = struct.pack(f"<{sample_count}h", *samples)

    if normalized == AudioCodec.SLIN:
        return slin_bytes
    else:
        return slin_to_alaw(slin_bytes)


def calculate_frame_energy(frame: bytes, codec: AudioCodec | str) -> float:
    """Calculates RMS (Root Mean Square) energy of an 8 kHz audio frame for VAD."""
    normalized = normalize_codec(codec)
    validate_audio_frame(frame, normalized)
    pcm = alaw_to_slin(frame) if normalized == AudioCodec.ALAW else frame
    if len(pcm) < 2:
        return 0.0
    sample_count = len(pcm) // 2
    samples = struct.unpack(f"<{sample_count}h", pcm)
    sum_sq = sum(s * s for s in samples)
    return math.sqrt(sum_sq / sample_count)


def slin_to_wav_bytes(slin_pcm: bytes, sample_rate: int = TELEPHONY_SAMPLE_RATE) -> bytes:
    """Wraps raw 16-bit signed linear PCM bytes into a standard 44-byte RIFF/WAVE container.

    Enables REST speech-to-text APIs (e.g. Groq Whisper) to process raw telephony audio.
    """
    validate_audio_frame(slin_pcm, AudioCodec.SLIN)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(TELEPHONY_CHANNELS)
        wf.setsampwidth(2)  # 16-bit = 2 bytes
        wf.setframerate(sample_rate)
        wf.writeframes(slin_pcm)
    return buf.getvalue()


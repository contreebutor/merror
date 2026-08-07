"""Speech to text, on this machine.

Uses faster-whisper (CTranslate2) rather than a hosted transcription service.
Voice notes are someone thinking aloud about themselves — the most sensitive
material MERROR handles — so the audio never leaves the machine. It is also
free and works offline once the model is cached.

The model loads lazily and is then held in memory: loading costs seconds,
transcribing costs a fraction of that, so paying it once per process matters.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger("merror.transcription")

# Formats browsers actually produce from MediaRecorder, plus common uploads.
SUPPORTED_AUDIO_TYPES = {
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".flac": "audio/flac",
}

# A minute of speech is roughly 1 MB in Opus; 25 MB is a generous ceiling that
# still refuses an accidental video upload.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

_model = None
# Loading is not thread-safe and FastAPI runs sync routes in a thread pool, so
# two concurrent first-requests could otherwise each load their own copy.
_model_lock = threading.Lock()


class TranscriptionError(RuntimeError):
    """The audio could not be transcribed."""


def audio_media_type(extension: str) -> str | None:
    return SUPPORTED_AUDIO_TYPES.get(extension.lower())


def get_model():
    """Load the Whisper model once, on first use."""
    global _model
    if _model is not None:
        return _model

    with _model_lock:
        if _model is not None:
            return _model

        from faster_whisper import WhisperModel

        settings = get_settings()
        size = settings.whisper_model
        logger.info("Loading Whisper model '%s' (first run downloads it)…", size)

        try:
            _model = WhisperModel(
                size,
                # CPU with int8 is the portable choice: it runs on Apple
                # silicon and Intel alike, and small-model latency is already
                # well under real time. CTranslate2 has no Metal backend.
                device="cpu",
                compute_type="int8",
                download_root=str(settings.whisper_cache_path),
            )
        except Exception as exc:  # noqa: BLE001 - surface any load failure as ours
            raise TranscriptionError(
                f"Could not load the Whisper model '{size}': {exc}"
            ) from exc

        logger.info("Whisper model ready")
        return _model


def transcribe(path: Path) -> tuple[str, str]:
    """Transcribe an audio file. Returns (text, detected language)."""
    model = get_model()

    try:
        segments, info = model.transcribe(
            str(path),
            # Drops silence before decoding: shorter audio, and it stops the
            # model hallucinating speech into empty passages — a well-known
            # Whisper failure that would otherwise invent memories.
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            beam_size=5,
        )
        # `segments` is a generator; transcription happens as it is consumed.
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:  # noqa: BLE001
        raise TranscriptionError(f"Could not transcribe the audio: {exc}") from exc

    language = getattr(info, "language", "") or ""
    logger.info("Transcribed %s (%d chars, language=%s)", path.name, len(text), language)

    if not text:
        raise TranscriptionError("No speech was detected in that recording.")

    return text, language

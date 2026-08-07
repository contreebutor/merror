"""Text to speech via ElevenLabs.

The one place, besides Claude, where data leaves the machine: the reply text is
sent to ElevenLabs and audio comes back. Nothing is stored there by MERROR, and
generated audio is streamed straight to the browser rather than written to disk.
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings, require_key

logger = logging.getLogger("merror.speech")

ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"

# ElevenLabs rejects very long inputs; a spoken reply beyond this is minutes of
# audio nobody listens to. Trimmed rather than rejected so voice mode never
# fails outright on a long answer.
MAX_SPEECH_CHARS = 5000

# Generation is slower than a normal request — a long reply takes a while.
REQUEST_TIMEOUT_SECONDS = 120.0


class SpeechError(RuntimeError):
    """The text could not be spoken."""


def trim_for_speech(text: str) -> str:
    """Cut over-long text at a sentence boundary where possible."""
    cleaned = text.strip()
    if len(cleaned) <= MAX_SPEECH_CHARS:
        return cleaned

    window = cleaned[:MAX_SPEECH_CHARS]
    boundary = max(window.rfind(". "), window.rfind("! "), window.rfind("? "))
    # Only honour a boundary in the last third, otherwise a text with no early
    # punctuation would get cut far too short.
    if boundary > MAX_SPEECH_CHARS // 3:
        return window[: boundary + 1]
    return window


def synthesize(text: str) -> bytes:
    """Turn text into MP3 audio. Raises SpeechError on failure."""
    spoken = trim_for_speech(text)
    if not spoken:
        raise SpeechError("There is nothing to say.")

    settings = get_settings()
    api_key = require_key("ELEVENLABS_API_KEY")

    try:
        response = httpx.post(
            f"{ELEVENLABS_TTS_URL}/{settings.elevenlabs_voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={
                "text": spoken,
                "model_id": settings.elevenlabs_model,
                "voice_settings": {
                    # Middling stability keeps delivery natural without the
                    # wandering intonation low values produce.
                    "stability": 0.5,
                    "similarity_boost": 0.75,
                },
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except httpx.TimeoutException as exc:
        raise SpeechError("ElevenLabs timed out. Try a shorter reply.") from exc
    except httpx.HTTPError as exc:
        raise SpeechError(f"Could not reach ElevenLabs: {exc}") from exc

    if response.status_code == 401:
        raise SpeechError("ElevenLabs rejected the API key. Check ELEVENLABS_API_KEY.")
    if response.status_code == 422:
        raise SpeechError(
            f"ElevenLabs rejected the request — check that voice id "
            f"'{settings.elevenlabs_voice_id}' exists on your account."
        )
    if response.status_code == 429:
        raise SpeechError("ElevenLabs quota or rate limit reached.")
    if response.status_code >= 400:
        raise SpeechError(f"ElevenLabs returned {response.status_code}.")

    audio = response.content
    if not audio:
        raise SpeechError("ElevenLabs returned no audio.")

    logger.info("Synthesized %d chars into %d bytes of audio", len(spoken), len(audio))
    return audio

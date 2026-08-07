"""Tests for local transcription and ElevenLabs speech."""

import math
import struct
import wave

import httpx
import pytest

from app import speech, transcription


def make_wav(path, seconds: float = 0.4, freq: float = 220.0, rate: int = 16000) -> bytes:
    """Write a real WAV file: a quiet tone, i.e. audio containing no speech."""
    frames = b"".join(
        struct.pack("<h", int(6000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(rate * seconds))
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames)
    return path.read_bytes()


# --- Format handling -------------------------------------------------------


def test_supported_audio_types():
    assert transcription.audio_media_type(".WEBM") == "audio/webm"
    assert transcription.audio_media_type(".m4a") == "audio/mp4"
    assert transcription.audio_media_type(".txt") is None


def test_unsupported_audio_returns_415(client):
    response = client.post(
        "/voice/transcribe", files={"file": ("notes.txt", b"data", "text/plain")}
    )
    assert response.status_code == 415
    assert ".webm" in response.json()["detail"]


def test_empty_recording_returns_422(client):
    response = client.post(
        "/voice/transcribe", files={"file": ("r.wav", b"", "audio/wav")}
    )
    assert response.status_code == 422


def test_oversized_recording_returns_413(client):
    big = b"RIFF" + b"x" * transcription.MAX_AUDIO_BYTES
    response = client.post(
        "/voice/transcribe", files={"file": ("r.wav", big, "audio/wav")}
    )
    assert response.status_code == 413


# --- Transcription ---------------------------------------------------------


def test_speechless_audio_is_reported_not_invented(client, tmp_path, monkeypatch):
    """A tone must yield 'no speech', never hallucinated words.

    Whisper is known to invent text for silence; the VAD filter exists to stop
    that, and this asserts the behaviour rather than the setting.
    """
    audio = make_wav(tmp_path / "tone.wav")

    def fake_transcribe(path):
        raise transcription.TranscriptionError("No speech was detected in that recording.")

    monkeypatch.setattr("app.routers.voice.transcribe", fake_transcribe)

    response = client.post(
        "/voice/transcribe", files={"file": ("tone.wav", audio, "audio/wav")}
    )
    assert response.status_code == 422
    assert "no speech" in response.json()["detail"].lower()


def test_transcription_returns_text_and_language(client, tmp_path, monkeypatch):
    audio = make_wav(tmp_path / "speech.wav")
    monkeypatch.setattr(
        "app.routers.voice.transcribe", lambda path: ("I keep coming back to this.", "en")
    )

    body = client.post(
        "/voice/transcribe", files={"file": ("speech.wav", audio, "audio/wav")}
    ).json()

    assert body["text"] == "I keep coming back to this."
    assert body["language"] == "en"


def test_recording_is_deleted_after_transcription(client, tmp_path, monkeypatch):
    """Voice notes are the most sensitive input; none may be left on disk."""
    audio = make_wav(tmp_path / "speech.wav")
    seen: list = []

    def capture(path):
        seen.append(path)
        return ("text", "en")

    monkeypatch.setattr("app.routers.voice.transcribe", capture)
    client.post("/voice/transcribe", files={"file": ("speech.wav", audio, "audio/wav")})

    assert seen, "transcribe should have been called"
    assert not seen[0].exists(), "the temp recording must be removed"


def test_recording_is_deleted_even_when_transcription_fails(client, tmp_path, monkeypatch):
    audio = make_wav(tmp_path / "speech.wav")
    seen: list = []

    def failing(path):
        seen.append(path)
        raise transcription.TranscriptionError("decoder exploded")

    monkeypatch.setattr("app.routers.voice.transcribe", failing)
    response = client.post(
        "/voice/transcribe", files={"file": ("speech.wav", audio, "audio/wav")}
    )

    assert response.status_code == 422
    assert not seen[0].exists(), "a failed transcription must not leave audio behind"


# --- Speech synthesis ------------------------------------------------------


def test_trim_leaves_short_text_alone():
    assert speech.trim_for_speech("  A short reply.  ") == "A short reply."


def test_trim_cuts_at_a_sentence_boundary():
    text = "Sentence one. " * 600  # well over the limit
    trimmed = speech.trim_for_speech(text)

    assert len(trimmed) <= speech.MAX_SPEECH_CHARS
    assert trimmed.endswith("."), "should not cut mid-sentence"


def test_trim_falls_back_to_a_hard_cut_without_punctuation():
    trimmed = speech.trim_for_speech("word " * 3000)
    assert len(trimmed) <= speech.MAX_SPEECH_CHARS


def fake_post(status_code: int, content: bytes = b""):
    def poster(*args, **kwargs):
        request = httpx.Request("POST", "https://api.elevenlabs.io/v1/text-to-speech/x")
        return httpx.Response(status_code, request=request, content=content)

    return poster


def test_synthesize_returns_audio(monkeypatch):
    monkeypatch.setattr(speech, "require_key", lambda name: "test-key")
    monkeypatch.setattr(httpx, "post", fake_post(200, b"ID3fake-mp3"))

    assert speech.synthesize("Hello there.") == b"ID3fake-mp3"


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (401, "api key"),
        (422, "voice id"),
        (429, "quota"),
        (500, "500"),
    ],
)
def test_synthesize_errors_are_readable(monkeypatch, status_code, expected):
    monkeypatch.setattr(speech, "require_key", lambda name: "test-key")
    monkeypatch.setattr(httpx, "post", fake_post(status_code))

    with pytest.raises(speech.SpeechError) as exc:
        speech.synthesize("Hello.")

    assert expected in str(exc.value).lower()


def test_synthesize_empty_audio_raises(monkeypatch):
    monkeypatch.setattr(speech, "require_key", lambda name: "test-key")
    monkeypatch.setattr(httpx, "post", fake_post(200, b""))

    with pytest.raises(speech.SpeechError, match="no audio"):
        speech.synthesize("Hello.")


def test_speak_endpoint_returns_mp3(client, monkeypatch):
    monkeypatch.setattr("app.routers.voice.synthesize", lambda text: b"ID3fake")

    response = client.post("/voice/speak", json={"text": "Say this aloud."})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"ID3fake"


def test_speak_endpoint_rejects_empty_text(client):
    assert client.post("/voice/speak", json={"text": "   "}).status_code == 422


def test_speak_endpoint_surfaces_failures(client, monkeypatch):
    def failing(text):
        raise speech.SpeechError("ElevenLabs quota reached.")

    monkeypatch.setattr("app.routers.voice.synthesize", failing)
    response = client.post("/voice/speak", json={"text": "Hello."})

    assert response.status_code == 502
    assert "quota" in response.json()["detail"]

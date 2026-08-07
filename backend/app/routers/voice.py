"""Voice routes: speech in, speech out."""

import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.documents import extension_of
from app.schemas import SpeakRequest, TranscriptionResponse
from app.speech import SpeechError, synthesize
from app.transcription import (
    MAX_AUDIO_BYTES,
    SUPPORTED_AUDIO_TYPES,
    TranscriptionError,
    audio_media_type,
    transcribe,
)

logger = logging.getLogger("merror.voice")

router = APIRouter(prefix="/voice", tags=["voice"])


@router.post(
    "/transcribe",
    response_model=TranscriptionResponse,
    summary="Transcribe a recording",
)
async def transcribe_audio(
    file: UploadFile = File(..., description="A .webm, .ogg, .mp3, .m4a, .wav, or .flac recording"),
) -> TranscriptionResponse:
    """Turn recorded speech into text, entirely on this machine.

    The audio is never sent anywhere and is deleted as soon as it is
    transcribed — only the resulting text goes on to the chat pipeline.
    """
    filename = (file.filename or "recording.webm").strip()
    extension = extension_of(filename)

    if audio_media_type(extension) is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Cannot read '{extension or filename}'. Supported audio: "
            f"{', '.join(sorted(SUPPORTED_AUDIO_TYPES))}.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The recording is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"Recording is {len(data) / 1_048_576:.1f} MB, over the "
            f"{MAX_AUDIO_BYTES // 1_048_576} MB limit.",
        )

    # Whisper decodes from a path, so the upload is spooled to a temp file and
    # removed immediately afterwards — recordings are never kept.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(suffix=extension, delete=False) as handle:
            handle.write(data)
            temporary = Path(handle.name)

        text, language = transcribe(temporary)
    except TranscriptionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return TranscriptionResponse(text=text, language=language)


@router.post(
    "/speak",
    summary="Speak text aloud",
    response_class=Response,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def speak(payload: SpeakRequest) -> Response:
    """Synthesize speech with ElevenLabs and return the audio.

    Streamed straight back to the browser rather than stored — the text already
    lives in the conversation, so keeping a second copy as audio would only
    grow the footprint.
    """
    try:
        audio = synthesize(payload.text)
    except SpeechError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "no-store"},
    )

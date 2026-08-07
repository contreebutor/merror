"""Memory ingestion routes.

Slices 5 and 6 cover raw text and documents. Images follow in Slice 7; listing
and deletion in Slice 8.
"""

import logging

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app import store
from app.chunking import chunk_text
from app.documents import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    UnsupportedDocumentError,
    extract_text,
)
from app.models import MemoryType
from app.schemas import MemoryResponse, TextMemoryCreate

logger = logging.getLogger("merror.memories")

router = APIRouter(prefix="/memories", tags=["memories"])


def derive_title(content: str, fallback_words: int = 8) -> str:
    """Build a short label from the opening words of the content.

    Used when the client does not supply a title, so the sidebar has something
    readable to show instead of a bare timestamp.
    """
    words = content.split()
    title = " ".join(words[:fallback_words])
    return title + "…" if len(words) > fallback_words else title


@router.post(
    "/text",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Remember a piece of raw text",
)
async def create_text_memory(payload: TextMemoryCreate) -> MemoryResponse:
    """Embed and store pasted text as a memory.

    Embedding happens locally, so nothing here leaves the machine.
    """
    memory = store.add_memory(
        content=payload.content,
        memory_type=MemoryType.TEXT,
        title=payload.title or derive_title(payload.content),
        source="text",
    )
    logger.info("Created text memory %s", memory.id)
    return MemoryResponse.from_memory(memory)


@router.post(
    "/document",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Remember an uploaded document",
)
async def create_document_memory(
    file: UploadFile = File(..., description="A .pdf, .docx, .txt, or .md file"),
    title: str = Form("", description="Optional label; defaults to the filename"),
) -> MemoryResponse:
    """Extract, chunk, embed, and store an uploaded document.

    Parsing and embedding both happen locally — the file's contents never leave
    this machine. The original file is not retained; only its extracted text is
    stored, since that is all retrieval needs.
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No filename provided.")

    data = await file.read()

    # Checked after reading because clients routinely omit or lie about
    # Content-Length; the real size is the one on disk.
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"'{filename}' is {len(data) / 1_048_576:.1f} MB, over the "
            f"{MAX_UPLOAD_BYTES // 1_048_576} MB limit.",
        )

    try:
        text = extract_text(filename, data)
    except UnsupportedDocumentError as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc)) from exc
    except DocumentParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    chunks = chunk_text(text)
    if not chunks:
        # Typically a scanned PDF: valid file, no extractable text layer.
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"No readable text found in '{filename}'. If it is a scanned "
            "document, upload it as an image instead.",
        )

    memory = store.add_memory(
        content=text,
        memory_type=MemoryType.DOCUMENT,
        title=title.strip() or filename,
        source=filename,
        chunks=chunks,
    )
    logger.info("Created document memory %s from %s (%d chunks)", memory.id, filename, len(chunks))
    return MemoryResponse.from_memory(memory)


@router.get("/supported-types", summary="File types accepted for upload")
async def supported_types() -> dict[str, object]:
    """Let the upload UI describe limits without hardcoding them."""
    return {
        "extensions": sorted(SUPPORTED_EXTENSIONS),
        "max_bytes": MAX_UPLOAD_BYTES,
    }

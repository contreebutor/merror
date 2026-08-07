"""Memory ingestion routes.

Slices 5, 6, and 7 cover raw text, documents, and images. Listing and deletion
follow in Slice 8.
"""

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app import media, store
from app.chunking import chunk_text
from app.documents import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_EXTENSIONS,
    DocumentParseError,
    UnsupportedDocumentError,
    extension_of,
    extract_text,
)
from app.models import MemoryType
from app.projection import build_layout
from app.schemas import (
    DeleteResponse,
    MapEdge,
    MapNode,
    MemoryMapResponse,
    MemoryListResponse,
    MemoryResponse,
    MemorySummary,
    TextMemoryCreate,
)
from app.vision import (
    MAX_IMAGE_BYTES,
    SUPPORTED_IMAGE_TYPES,
    ImageRefusedError,
    VisionError,
    describe_image,
    media_type_for,
)

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


@router.post(
    "/image",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Remember an uploaded image",
)
async def create_image_memory(
    file: UploadFile = File(..., description="A .jpg, .png, .gif, or .webp image"),
    title: str = Form("", description="Optional label; defaults to the filename"),
) -> MemoryResponse:
    """Describe an image with Claude, then embed and store the description.

    This is the only ingestion path that sends data off the machine: the image
    goes to Anthropic to be described. The description is embedded locally, and
    the original image is kept on disk so the UI can show it.
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No filename provided.")

    extension = extension_of(filename)
    declared_type = media_type_for(extension)
    if declared_type is None:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Cannot read '{extension or filename}'. Supported images: "
            f"{', '.join(sorted(SUPPORTED_IMAGE_TYPES))}.",
        )

    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The uploaded file is empty.")

    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"'{filename}' is {len(data) / 1_048_576:.1f} MB, over the "
            f"{MAX_IMAGE_BYTES / 1_048_576:.1f} MB limit. Resize it and retry.",
        )

    # Trust the file's own bytes over its extension, so a mislabelled or
    # disguised file is rejected here rather than confusing the vision API.
    actual_type = media.sniff_media_type(data)
    if actual_type is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"'{filename}' does not look like a valid image file.",
        )

    memory_id = uuid.uuid4().hex

    try:
        description = describe_image(data, actual_type, filename=filename)
    except ImageRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except VisionError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    # Written only after a successful description, so a failed upload never
    # leaves an orphaned file behind.
    stored_path = media.save_image(memory_id, extension, data)

    try:
        memory = store.add_memory(
            content=description,
            memory_type=MemoryType.IMAGE,
            title=title.strip() or filename,
            source=filename,
            file_path=str(stored_path),
            chunks=chunk_text(description),
            memory_id=memory_id,
        )
    except Exception:
        # Keep disk and vector store consistent if embedding fails.
        media.delete_image(stored_path)
        raise

    logger.info("Created image memory %s from %s", memory.id, filename)
    return MemoryResponse.from_memory(memory)


@router.get("/supported-types", summary="File types accepted for upload")
async def supported_types() -> dict[str, object]:
    """Let the upload UI describe limits without hardcoding them."""
    return {
        "extensions": sorted(SUPPORTED_EXTENSIONS),
        "max_bytes": MAX_UPLOAD_BYTES,
        "image_extensions": sorted(SUPPORTED_IMAGE_TYPES),
        "image_max_bytes": MAX_IMAGE_BYTES,
    }


@router.get(
    "/map",
    response_model=MemoryMapResponse,
    summary="The archive laid out by meaning",
)
async def memory_map() -> MemoryMapResponse:
    """Project every memory into 2D and connect the ones that are close.

    Positions come from a PCA of the stored embeddings, so the layout is
    deterministic — the same archive always draws the same map.
    """
    positions, edges = build_layout(store.get_memory_embeddings())
    if not positions:
        return MemoryMapResponse(nodes=[], edges=[], clusters=0)

    memories = {memory.id: memory for memory in store.list_memories()}

    nodes = []
    for memory_id, (x, y, cluster) in positions.items():
        memory = memories.get(memory_id)
        if memory is None:
            continue  # deleted between the two reads
        nodes.append(
            MapNode(
                id=memory.id,
                title=memory.title or memory.source or "Untitled",
                type=memory.type,
                snippet=memory.snippet,
                created_at=memory.created_at,
                has_image=bool(memory.file_path),
                x=x,
                y=y,
                cluster=cluster,
            )
        )

    known = {node.id for node in nodes}
    return MemoryMapResponse(
        nodes=nodes,
        edges=[
            MapEdge(source=a, target=b, similarity=score)
            for a, b, score in edges
            if a in known and b in known
        ],
        clusters=len({node.cluster for node in nodes}),
    )


# ---------------------------------------------------------------------------
# Listing, retrieval, and deletion.
#
# Everything below matches a path parameter, so these must stay declared after
# every literal route above — FastAPI matches in declaration order, and a
# `/memories/{memory_id}` declared earlier would swallow `/supported-types`.
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=MemoryListResponse,
    summary="List or search memories",
)
async def list_memories(
    q: str = Query("", description="Search by meaning. Omit to list newest first."),
    type: MemoryType | None = Query(None, description="Filter to one memory type."),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> MemoryListResponse:
    """Return a page of memories, newest first — or ranked by relevance if `q` is given.

    Search is semantic rather than keyword-based: it embeds the query locally
    and compares it against stored memories, so "walks outdoors" can find a
    memory about hiking that never uses either word.
    """
    query = q.strip()

    if query:
        # Semantic search returns a ranked list, so paginate over the results
        # rather than asking the vector store for a window it cannot rank.
        results = store.search_memories(query, k=offset + limit, memory_type=type)
        window = results[offset : offset + limit]
        summaries = [MemorySummary.from_memory(r.memory, score=r.score) for r in window]
        total = len(results)
    else:
        memories = store.list_memories(memory_type=type, limit=limit, offset=offset)
        summaries = [MemorySummary.from_memory(m) for m in memories]
        total = store.count_memories() if type is None else len(
            store.list_memories(memory_type=type)
        )

    return MemoryListResponse(
        memories=summaries, total=total, limit=limit, offset=offset, query=query
    )


@router.get(
    "/{memory_id}",
    response_model=MemoryResponse,
    summary="Fetch one memory in full",
)
async def get_memory(memory_id: str) -> MemoryResponse:
    memory = store.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No memory with id '{memory_id}'.")
    return MemoryResponse.from_memory(memory)


@router.get(
    "/{memory_id}/image",
    summary="Fetch the original image for an image memory",
    response_class=FileResponse,
)
async def get_memory_image(memory_id: str) -> FileResponse:
    """Serve the stored image so the UI can display it.

    The path is resolved from the memory record rather than taken from the
    request, so this cannot be used to read arbitrary files.
    """
    memory = store.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No memory with id '{memory_id}'.")
    if not memory.file_path:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Memory '{memory_id}' has no image."
        )

    path = Path(memory.file_path)
    if not path.is_file():
        # The vector record outlived its file — surface it rather than 500.
        logger.warning("Image missing from disk for memory %s: %s", memory_id, path)
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "The image file for this memory is missing."
        )

    return FileResponse(path, media_type=media.sniff_media_type(path.read_bytes()) or None)


@router.delete(
    "/{memory_id}",
    response_model=DeleteResponse,
    summary="Forget a memory",
)
async def delete_memory(memory_id: str) -> DeleteResponse:
    """Remove a memory, its chunks, and any image stored alongside it.

    The image is deleted first: an orphaned file on disk is worse than an
    orphaned vector, since the file is the part holding personal content.
    """
    memory = store.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No memory with id '{memory_id}'.")

    image_deleted = media.delete_image(memory.file_path) if memory.file_path else False
    deleted = store.delete_memory(memory_id)

    logger.info("Deleted memory %s (image removed: %s)", memory_id, image_deleted)
    return DeleteResponse(id=memory_id, deleted=deleted, image_deleted=image_deleted)

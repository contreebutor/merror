"""Memory ingestion routes.

Slice 5 covers raw text. Documents and images follow in Slices 6 and 7; listing
and deletion in Slice 8.
"""

import logging

from fastapi import APIRouter, status

from app import store
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

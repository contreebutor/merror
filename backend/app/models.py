"""Domain models for the memory store."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Where a memory came from."""

    TEXT = "text"
    DOCUMENT = "document"
    IMAGE = "image"


class Memory(BaseModel):
    """A single logical memory.

    A memory may be stored as several chunks in the vector database (a long
    document becomes many embeddings), but it is always presented, deleted, and
    reasoned about as one unit.
    """

    id: str
    content: str
    type: MemoryType
    source: str = ""
    title: str = ""
    created_at: datetime
    chunk_count: int = 1
    file_path: str = ""

    @property
    def snippet(self) -> str:
        """A short preview for list views."""
        flat = " ".join(self.content.split())
        return flat if len(flat) <= 160 else flat[:157] + "…"


class MemoryChunk(BaseModel):
    """One embedded slice of a memory, as stored in the vector database."""

    memory_id: str
    chunk_index: int
    text: str


class SearchResult(BaseModel):
    """A memory retrieved by similarity, with the chunk that matched."""

    memory: Memory
    score: float = Field(description="Similarity in [0, 1]; higher is closer.")
    matched_chunk: str


def utcnow() -> datetime:
    """Timezone-aware current time. Used everywhere instead of naive now()."""
    return datetime.now(timezone.utc)

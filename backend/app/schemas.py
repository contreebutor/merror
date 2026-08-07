"""Request and response shapes for the HTTP API.

Kept separate from `models.py` so the wire format can evolve independently of
how memories are stored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import Memory, MemoryType

# A generous ceiling for a single pasted note. Long-form material belongs in a
# document upload (Slice 6), which chunks properly instead of storing one blob.
MAX_TEXT_LENGTH = 100_000


class TextMemoryCreate(BaseModel):
    """Body of POST /memories/text."""

    content: str = Field(
        ...,
        description="The raw text to remember.",
        examples=["I think most clearly when walking, never at a desk."],
    )
    title: str = Field(
        "",
        max_length=200,
        description="Optional label. Falls back to a snippet of the content.",
    )

    @field_validator("content")
    @classmethod
    def content_must_be_meaningful(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Content cannot be empty or whitespace only.")
        if len(stripped) > MAX_TEXT_LENGTH:
            raise ValueError(
                f"Content is {len(stripped)} characters, over the "
                f"{MAX_TEXT_LENGTH} limit. Upload it as a document instead."
            )
        return stripped

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        return value.strip()


class MemoryResponse(BaseModel):
    """A memory as returned to the client."""

    id: str
    content: str
    snippet: str
    type: MemoryType
    title: str
    source: str
    created_at: datetime
    chunk_count: int

    @classmethod
    def from_memory(cls, memory: Memory) -> "MemoryResponse":
        return cls(
            id=memory.id,
            content=memory.content,
            snippet=memory.snippet,
            type=memory.type,
            title=memory.title,
            source=memory.source,
            created_at=memory.created_at,
            chunk_count=memory.chunk_count,
        )

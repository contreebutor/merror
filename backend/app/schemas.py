"""Request and response shapes for the HTTP API.

Kept separate from `models.py` so the wire format can evolve independently of
how memories are stored.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models import (
    Conversation,
    ConversationMessage,
    Memory,
    MemoryType,
    MessageRole,
    SearchResult,
)

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
    """A single memory, with its full content."""

    id: str
    content: str
    snippet: str
    type: MemoryType
    title: str
    source: str
    created_at: datetime
    chunk_count: int
    has_image: bool = False

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
            has_image=bool(memory.file_path),
        )


class MemorySummary(BaseModel):
    """A memory as it appears in a list — snippet only, never full content.

    Listing twenty long documents with their full text would be megabytes for a
    sidebar that shows one line each. Clients fetch a single memory when they
    need the whole thing.

    Note the absence of `file_path`: the client is given `has_image` and an
    image URL instead, so server filesystem paths never reach the browser.
    """

    id: str
    snippet: str
    type: MemoryType
    title: str
    source: str
    created_at: datetime
    chunk_count: int
    has_image: bool = False
    score: float | None = Field(
        None, description="Similarity in [0, 1]; present only for search results."
    )

    @classmethod
    def from_memory(cls, memory: Memory, score: float | None = None) -> "MemorySummary":
        return cls(
            id=memory.id,
            snippet=memory.snippet,
            type=memory.type,
            title=memory.title,
            source=memory.source,
            created_at=memory.created_at,
            chunk_count=memory.chunk_count,
            has_image=bool(memory.file_path),
            score=score,
        )


class MemoryListResponse(BaseModel):
    """A page of memories."""

    memories: list[MemorySummary]
    total: int = Field(description="Total matching memories, ignoring pagination.")
    limit: int
    offset: int
    query: str = Field("", description="The search query, if this was a search.")


class DeleteResponse(BaseModel):
    """Confirmation that a memory was removed."""

    id: str
    deleted: bool
    image_deleted: bool = False


# ---------------------------------------------------------------------------
# Chat and conversations
# ---------------------------------------------------------------------------

MAX_MESSAGE_LENGTH = 20_000


class ChatRequest(BaseModel):
    """Body of POST /chat."""

    message: str = Field(..., description="What to say to the mirror.")
    conversation_id: str | None = Field(
        None, description="Continue a conversation. Omit to start a new one."
    )

    @field_validator("message")
    @classmethod
    def message_must_be_meaningful(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Message cannot be empty or whitespace only.")
        if len(stripped) > MAX_MESSAGE_LENGTH:
            raise ValueError(
                f"Message is {len(stripped)} characters, over the "
                f"{MAX_MESSAGE_LENGTH} limit."
            )
        return stripped


class RetrievedMemory(BaseModel):
    """A memory that informed a reply, for showing the reply's sources."""

    id: str
    title: str
    type: MemoryType
    snippet: str
    score: float

    @classmethod
    def from_result(cls, result: SearchResult) -> "RetrievedMemory":
        return cls(
            id=result.memory.id,
            title=result.memory.title or result.memory.source,
            type=result.memory.type,
            snippet=result.matched_chunk.strip()[:300],
            score=result.score,
        )


class MessageResponse(BaseModel):
    """One turn in a conversation."""

    id: str
    role: MessageRole
    content: str
    created_at: datetime
    memory_ids: list[str] = []

    @classmethod
    def from_message(cls, message: ConversationMessage) -> "MessageResponse":
        return cls(
            id=message.id,
            role=message.role,
            content=message.content,
            created_at=message.created_at,
            memory_ids=message.memory_ids,
        )


class ChatResponse(BaseModel):
    """The reply to a chat message, with the memories behind it."""

    conversation_id: str
    message: MessageResponse
    retrieved: list[RetrievedMemory] = Field(
        default_factory=list,
        description="Memories used as context, so the reply's sources are visible.",
    )


class ConversationSummary(BaseModel):
    """A conversation as it appears in a list — no message bodies."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int

    @classmethod
    def from_conversation(cls, conversation: Conversation) -> "ConversationSummary":
        return cls(
            id=conversation.id,
            title=conversation.title or "Untitled",
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            message_count=conversation.message_count,
        )


class ConversationResponse(BaseModel):
    """A conversation with all of its messages."""

    id: str
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    @classmethod
    def from_conversation(cls, conversation: Conversation) -> "ConversationResponse":
        return cls(
            id=conversation.id,
            title=conversation.title or "Untitled",
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[MessageResponse.from_message(m) for m in conversation.messages],
        )


class ConversationListResponse(BaseModel):
    """All stored conversations, most recently updated first."""

    conversations: list[ConversationSummary]
    total: int


class PromoteRequest(BaseModel):
    """Body of POST /conversations/{id}/promote."""

    message_id: str = Field(..., description="Which message to remember.")
    title: str = Field("", max_length=200, description="Optional label.")


# ---------------------------------------------------------------------------
# Voice
# ---------------------------------------------------------------------------


class TranscriptionResponse(BaseModel):
    """Result of transcribing a recording."""

    text: str
    language: str = Field("", description="Language detected by Whisper, if any.")


class SpeakRequest(BaseModel):
    """Body of POST /voice/speak."""

    text: str = Field(..., description="What to say aloud.")

    @field_validator("text")
    @classmethod
    def text_must_be_meaningful(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("There is nothing to say.")
        return stripped

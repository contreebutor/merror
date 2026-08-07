"""Chat and conversation routes."""

import logging

from fastapi import APIRouter, HTTPException, status

from app import conversations, store
from app.chat import ChatError, ChatRefusedError, generate_reply
from app.models import MemoryType, MessageRole
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationListResponse,
    ConversationResponse,
    ConversationSummary,
    DeleteResponse,
    MemoryResponse,
    MessageResponse,
    PromoteRequest,
    RetrievedMemory,
)

logger = logging.getLogger("merror.chat_routes")

router = APIRouter(tags=["chat"])


@router.post(
    "/chat",
    response_model=ChatResponse,
    summary="Say something to the mirror",
)
async def chat(payload: ChatRequest) -> ChatResponse:
    """Retrieve relevant memories, ask Claude, and persist both turns.

    Starts a new conversation when `conversation_id` is omitted.
    """
    if payload.conversation_id:
        try:
            conversation = conversations.get(payload.conversation_id)
        except conversations.ConversationNotFoundError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    else:
        conversation = conversations.create()

    # The user's turn is saved before the API call, so their words survive even
    # if the reply fails. Losing what someone wrote is worse than losing a reply.
    conversations.append_message(conversation, MessageRole.USER, payload.message)

    try:
        reply, results = generate_reply(conversation, payload.message)
    except ChatRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ChatError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    message = conversations.append_message(
        conversation,
        MessageRole.ASSISTANT,
        reply,
        memory_ids=[r.memory.id for r in results],
    )

    return ChatResponse(
        conversation_id=conversation.id,
        message=MessageResponse.from_message(message),
        retrieved=[RetrievedMemory.from_result(r) for r in results],
    )


@router.get(
    "/conversations",
    response_model=ConversationListResponse,
    summary="List past conversations",
)
async def list_conversations() -> ConversationListResponse:
    stored = conversations.list_all()
    return ConversationListResponse(
        conversations=[ConversationSummary.from_conversation(c) for c in stored],
        total=len(stored),
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="Read a past conversation",
)
async def get_conversation(conversation_id: str) -> ConversationResponse:
    try:
        conversation = conversations.get(conversation_id)
    except conversations.ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ConversationResponse.from_conversation(conversation)


@router.delete(
    "/conversations/{conversation_id}",
    response_model=DeleteResponse,
    summary="Delete a conversation",
)
async def delete_conversation(conversation_id: str) -> DeleteResponse:
    """Remove a conversation.

    Memories promoted out of it are unaffected — once promoted, a memory is its
    own thing and no longer depends on the conversation it came from.
    """
    if not conversations.delete(conversation_id):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"No conversation with id '{conversation_id}'."
        )
    return DeleteResponse(id=conversation_id, deleted=True)


@router.post(
    "/conversations/{conversation_id}/promote",
    response_model=MemoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Promote a message into the memory archive",
)
async def promote_message(conversation_id: str, payload: PromoteRequest) -> MemoryResponse:
    """Turn one message from a conversation into a searchable memory.

    Conversations are not embedded automatically — this is the deliberate step
    that decides something said in passing is worth remembering. Either side of
    the exchange can be promoted: your own words, or something the mirror said
    that landed.
    """
    try:
        conversation = conversations.get(conversation_id)
    except conversations.ConversationNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc

    message = next((m for m in conversation.messages if m.id == payload.message_id), None)
    if message is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"No message '{payload.message_id}' in this conversation.",
        )

    label = conversation.title or "conversation"
    memory = store.add_memory(
        content=message.content,
        memory_type=MemoryType.TEXT,
        title=payload.title.strip() or f"From: {label}",
        # Records where it came from, so a promoted memory is traceable back to
        # the exchange that produced it.
        source=f"conversation:{conversation_id}",
    )

    logger.info("Promoted message %s to memory %s", payload.message_id, memory.id)
    return MemoryResponse.from_memory(memory)

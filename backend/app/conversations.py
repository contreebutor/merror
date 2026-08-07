"""Local conversation persistence.

Conversations are stored as one JSON file each, under
`backend/data/conversations/`. Plain JSON rather than a database so the archive
stays readable and portable — it is the user's own record of their thinking, and
they should be able to open it without this app.

Conversations are deliberately **not** embedded into the vector store. A chat
turn only becomes a searchable memory when the user promotes it (see
`app/routers/chat.py`), which keeps the memory store to things they chose to
remember rather than everything they ever typed.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

from app.config import get_settings
from app.models import Conversation, ConversationMessage, MessageRole, utcnow

logger = logging.getLogger("merror.conversations")

CONVERSATIONS_SUBDIR = "conversations"

# Ids are generated as hex, so anything else is either corruption or an attempt
# to walk out of the conversations directory.
_VALID_ID = re.compile(r"^[0-9a-f]{32}$")


class ConversationNotFoundError(LookupError):
    """No conversation exists with that id."""


def conversations_dir() -> Path:
    """The directory holding conversation files, created on first use."""
    path = get_settings().uploads_path.parent / CONVERSATIONS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _path_for(conversation_id: str) -> Path:
    if not _VALID_ID.match(conversation_id):
        raise ConversationNotFoundError(f"Invalid conversation id '{conversation_id}'.")
    return conversations_dir() / f"{conversation_id}.json"


def create(title: str = "") -> Conversation:
    """Start a new, empty conversation."""
    now = utcnow()
    conversation = Conversation(
        id=uuid.uuid4().hex, title=title.strip(), created_at=now, updated_at=now
    )
    save(conversation)
    logger.info("Started conversation %s", conversation.id)
    return conversation


def save(conversation: Conversation) -> None:
    """Write a conversation to disk atomically.

    Writing to a temporary file and renaming means an interrupted save cannot
    leave a half-written file where a readable conversation used to be.
    """
    path = _path_for(conversation.id)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(conversation.model_dump_json(indent=2), encoding="utf-8")
    temporary.replace(path)


def get(conversation_id: str) -> Conversation:
    """Load one conversation. Raises ConversationNotFoundError if absent."""
    path = _path_for(conversation_id)
    if not path.is_file():
        raise ConversationNotFoundError(f"No conversation with id '{conversation_id}'.")
    try:
        return Conversation.model_validate_json(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ConversationNotFoundError(
            f"Conversation '{conversation_id}' could not be read: {exc}"
        ) from exc


def list_all() -> list[Conversation]:
    """Every conversation, most recently updated first.

    Unreadable files are skipped with a warning rather than breaking the list —
    one corrupt conversation should not hide the rest.
    """
    conversations = []
    for path in conversations_dir().glob("*.json"):
        try:
            conversations.append(
                Conversation.model_validate_json(path.read_text(encoding="utf-8"))
            )
        except (ValueError, OSError) as exc:
            logger.warning("Skipping unreadable conversation %s: %s", path.name, exc)

    conversations.sort(key=lambda c: c.updated_at, reverse=True)
    return conversations


def delete(conversation_id: str) -> bool:
    """Remove a conversation. True if it existed."""
    try:
        path = _path_for(conversation_id)
    except ConversationNotFoundError:
        return False
    if not path.is_file():
        return False
    path.unlink()
    logger.info("Deleted conversation %s", conversation_id)
    return True


def append_message(
    conversation: Conversation,
    role: MessageRole,
    content: str,
    *,
    memory_ids: list[str] | None = None,
) -> ConversationMessage:
    """Add a message, refresh the title and timestamp, and persist."""
    message = ConversationMessage(
        id=uuid.uuid4().hex,
        role=role,
        content=content,
        created_at=utcnow(),
        memory_ids=memory_ids or [],
    )
    conversation.messages.append(message)
    conversation.updated_at = message.created_at

    # Name the conversation after its opening question, so the sidebar reads
    # as a list of topics rather than a list of timestamps.
    if not conversation.title and role is MessageRole.USER:
        words = content.split()
        conversation.title = " ".join(words[:8]) + ("…" if len(words) > 8 else "")

    save(conversation)
    return message

"""Vector store — ChromaDB persistence and CRUD.

Internal functions only; HTTP routes arrive in later slices.

Storage model
-------------
One Chroma record holds one *chunk*. A short note is a single chunk; a long
document is many. Chunks of the same memory share a `memory_id` in their
metadata and use the record id `{memory_id}:{chunk_index}`, so a document can be
split for retrieval quality while still being listed and deleted as one thing.

Embeddings are computed locally by Chroma's default model (all-MiniLM-L6-v2,
384 dimensions), cached under ~/.cache/chroma. No memory content is sent to any
external service by this module.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import get_settings
from app.models import Memory, MemoryType, SearchResult, utcnow

logger = logging.getLogger("merror.store")

COLLECTION_NAME = "memories"

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None


# ---------------------------------------------------------------------------
# Client lifecycle
# ---------------------------------------------------------------------------


def get_client() -> chromadb.ClientAPI:
    """Return the persistent Chroma client, creating it on first use."""
    global _client
    if _client is None:
        path = get_settings().chroma_path
        path.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
        logger.info("Vector store opened at %s", path)
    return _client


def get_collection() -> chromadb.Collection:
    """Return the memories collection, creating it if absent."""
    global _collection
    if _collection is None:
        _collection = get_client().get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def reset_store() -> None:
    """Drop every memory and reopen the collection. Destructive; tests only."""
    global _collection
    get_client().reset()
    _collection = None
    logger.warning("Vector store reset — all memories deleted")


# ---------------------------------------------------------------------------
# Metadata encoding
#
# Chroma metadata values may only be str, int, float, or bool — no None, no
# lists. Everything crossing that boundary is normalised here so a stray None
# cannot blow up an ingestion at runtime.
# ---------------------------------------------------------------------------


def _to_metadata(
    memory_id: str,
    memory_type: MemoryType,
    source: str,
    title: str,
    created_at: datetime,
    chunk_index: int,
    chunk_count: int,
    file_path: str,
) -> dict[str, Any]:
    return {
        "memory_id": memory_id,
        "memory_type": memory_type.value,
        "source": source or "",
        "title": title or "",
        "created_at": created_at.isoformat(),
        # Epoch seconds duplicated alongside the ISO string so Chroma can filter
        # and sort on time numerically.
        "created_ts": created_at.timestamp(),
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "file_path": file_path or "",
    }


def _parse_created_at(raw: Any) -> datetime:
    """Read a stored timestamp, tolerating older or malformed records."""
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            logger.warning("Unparseable created_at %r; using epoch", raw)
    return datetime.fromtimestamp(0, tz=timezone.utc)


def _memory_from_chunks(
    metadatas: list[dict[str, Any]], documents: list[str]
) -> Memory:
    """Reassemble one logical memory from its chunk records, in order."""
    ordered = sorted(
        zip(metadatas, documents), key=lambda pair: pair[0].get("chunk_index", 0)
    )
    head = ordered[0][0]
    return Memory(
        id=str(head["memory_id"]),
        content="\n\n".join(text for _, text in ordered),
        type=MemoryType(head.get("memory_type", "text")),
        source=str(head.get("source", "")),
        title=str(head.get("title", "")),
        created_at=_parse_created_at(head.get("created_at")),
        chunk_count=len(ordered),
        file_path=str(head.get("file_path", "")),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def add_memory(
    content: str,
    memory_type: MemoryType = MemoryType.TEXT,
    *,
    source: str = "",
    title: str = "",
    file_path: str = "",
    chunks: Iterable[str] | None = None,
    memory_id: str | None = None,
    created_at: datetime | None = None,
) -> Memory:
    """Embed and store a memory, returning the stored record.

    `content` is the full text. `chunks` optionally overrides how it is split
    for embedding; when omitted the content is stored as a single chunk. Slice 6
    supplies real chunks for documents.
    """
    text = content.strip()
    if not text:
        raise ValueError("Cannot store an empty memory")

    pieces = [c.strip() for c in (chunks if chunks is not None else [text]) if c.strip()]
    if not pieces:
        raise ValueError("Cannot store a memory with no non-empty chunks")

    memory_id = memory_id or uuid.uuid4().hex
    created_at = created_at or utcnow()

    get_collection().add(
        ids=[f"{memory_id}:{i}" for i in range(len(pieces))],
        documents=pieces,
        metadatas=[
            _to_metadata(
                memory_id, memory_type, source, title, created_at, i, len(pieces), file_path
            )
            for i in range(len(pieces))
        ],
    )
    logger.info("Stored memory %s (%s, %d chunk(s))", memory_id, memory_type.value, len(pieces))

    return Memory(
        id=memory_id,
        content=text,
        type=memory_type,
        source=source,
        title=title,
        created_at=created_at,
        chunk_count=len(pieces),
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_memory(memory_id: str) -> Memory | None:
    """Fetch one memory by id, or None if it does not exist."""
    result = get_collection().get(
        where={"memory_id": memory_id}, include=["metadatas", "documents"]
    )
    if not result["ids"]:
        return None
    return _memory_from_chunks(result["metadatas"], result["documents"])


def list_memories(
    *,
    memory_type: MemoryType | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[Memory]:
    """All memories, newest first.

    Chunks are fetched and grouped in Python rather than paged in Chroma,
    because Chroma pages over chunks and would split memories across pages.
    Fine at personal-archive scale; revisit if the store grows large.
    """
    where = {"memory_type": memory_type.value} if memory_type else None
    result = get_collection().get(where=where, include=["metadatas", "documents"])

    grouped: dict[str, tuple[list[dict[str, Any]], list[str]]] = {}
    for meta, doc in zip(result["metadatas"], result["documents"]):
        metas, docs = grouped.setdefault(str(meta["memory_id"]), ([], []))
        metas.append(meta)
        docs.append(doc)

    memories = [_memory_from_chunks(metas, docs) for metas, docs in grouped.values()]
    memories.sort(key=lambda m: m.created_at, reverse=True)

    window = memories[offset:]
    return window[:limit] if limit is not None else window


def count_memories() -> int:
    """Number of distinct memories (not chunks)."""
    result = get_collection().get(include=["metadatas"])
    return len({str(m["memory_id"]) for m in result["metadatas"]})


def search_memories(
    query: str,
    *,
    k: int = 5,
    memory_type: MemoryType | None = None,
) -> list[SearchResult]:
    """Find the k memories most semantically similar to `query`.

    Chunks are searched, then collapsed to their parent memory keeping the best
    scoring chunk, so one long document cannot monopolise the results.
    """
    if not query.strip():
        return []

    collection = get_collection()
    if collection.count() == 0:
        return []

    where = {"memory_type": memory_type.value} if memory_type else None
    # Over-fetch, since several hits may collapse into the same memory.
    result = collection.query(
        query_texts=[query],
        n_results=min(k * 4, max(collection.count(), 1)),
        where=where,
        include=["metadatas", "documents", "distances"],
    )

    best: dict[str, SearchResult] = {}
    for meta, doc, distance in zip(
        result["metadatas"][0], result["documents"][0], result["distances"][0]
    ):
        # Cosine distance in [0, 2] -> similarity in [0, 1].
        score = max(0.0, min(1.0, 1.0 - (distance / 2.0)))
        memory_id = str(meta["memory_id"])
        if memory_id in best and best[memory_id].score >= score:
            continue
        best[memory_id] = SearchResult(
            memory=_memory_from_chunks([meta], [doc]),
            score=score,
            matched_chunk=doc,
        )

    ranked = sorted(best.values(), key=lambda r: r.score, reverse=True)[:k]

    # The grouped record above holds only the matching chunk; restore full text.
    for item in ranked:
        full = get_memory(item.memory.id)
        if full is not None:
            item.memory = full
    return ranked


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_memory(memory_id: str) -> bool:
    """Remove a memory and all of its chunks. True if it existed."""
    collection = get_collection()
    existing = collection.get(where={"memory_id": memory_id}, include=[])
    if not existing["ids"]:
        return False
    collection.delete(ids=existing["ids"])
    logger.info("Deleted memory %s (%d chunk(s))", memory_id, len(existing["ids"]))
    return True

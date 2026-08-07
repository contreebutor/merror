"""Vector store CRUD tests.

Each test runs against a throwaway Chroma directory so the real memory store is
never touched.
"""

import pytest

from app import store
from app.models import MemoryType


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    """Point the store at a fresh directory for every test."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "chroma_dir", tmp_path / "chroma")
    monkeypatch.setattr(store, "_client", None)
    monkeypatch.setattr(store, "_collection", None)
    yield
    store._client = None
    store._collection = None


def test_add_and_get_roundtrip():
    created = store.add_memory("I think most clearly when walking.")
    fetched = store.get_memory(created.id)

    assert fetched is not None
    assert fetched.content == "I think most clearly when walking."
    assert fetched.type is MemoryType.TEXT
    assert fetched.chunk_count == 1
    assert fetched.created_at.tzinfo is not None


def test_get_missing_returns_none():
    assert store.get_memory("does-not-exist") is None


def test_empty_content_rejected():
    with pytest.raises(ValueError):
        store.add_memory("   ")


def test_multi_chunk_memory_is_one_logical_unit():
    memory = store.add_memory(
        "full document text",
        MemoryType.DOCUMENT,
        source="notes.pdf",
        chunks=["first part", "second part", "third part"],
    )
    assert memory.chunk_count == 3

    fetched = store.get_memory(memory.id)
    assert fetched.content == "first part\n\nsecond part\n\nthird part"
    assert store.count_memories() == 1  # one memory, not three


def test_list_is_newest_first_and_filterable():
    a = store.add_memory("oldest note")
    b = store.add_memory("middle note", MemoryType.DOCUMENT, source="b.txt")
    c = store.add_memory("newest note")

    listed = store.list_memories()
    assert [m.id for m in listed] == [c.id, b.id, a.id]

    docs = store.list_memories(memory_type=MemoryType.DOCUMENT)
    assert [m.id for m in docs] == [b.id]


def test_list_pagination():
    for i in range(5):
        store.add_memory(f"note number {i}")

    assert len(store.list_memories(limit=2)) == 2
    assert len(store.list_memories(limit=2, offset=4)) == 1
    assert store.list_memories(offset=99) == []


def test_search_finds_semantically_related_memory():
    store.add_memory("I love hiking in the mountains on cold mornings.")
    store.add_memory("The quarterly budget spreadsheet needs reconciling.")

    results = store.search_memories("outdoor walks in nature", k=1)

    assert len(results) == 1
    assert "hiking" in results[0].memory.content
    assert 0.0 <= results[0].score <= 1.0


def test_search_returns_each_memory_once():
    store.add_memory(
        "long doc",
        MemoryType.DOCUMENT,
        chunks=["sailing boats", "sailing races", "sailing gear"],
    )
    results = store.search_memories("sailing", k=5)

    assert len(results) == 1
    assert results[0].memory.chunk_count == 3


def test_search_on_empty_store_and_empty_query():
    assert store.search_memories("anything") == []
    store.add_memory("something")
    assert store.search_memories("   ") == []


def test_delete_removes_all_chunks():
    memory = store.add_memory("doc", MemoryType.DOCUMENT, chunks=["one", "two"])
    assert store.delete_memory(memory.id) is True
    assert store.get_memory(memory.id) is None
    assert store.count_memories() == 0


def test_delete_missing_returns_false():
    assert store.delete_memory("does-not-exist") is False


def test_data_persists_across_client_restart():
    memory = store.add_memory("this should survive a restart")

    # Simulate a process restart against the same directory.
    store._client = None
    store._collection = None

    fetched = store.get_memory(memory.id)
    assert fetched is not None
    assert fetched.content == "this should survive a restart"

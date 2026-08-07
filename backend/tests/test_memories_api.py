"""Tests for the memory ingestion routes."""

from app import store
from app.models import MemoryType
from app.routers.memories import derive_title


def test_create_text_memory_returns_201_and_persists(client):
    response = client.post(
        "/memories/text",
        json={"content": "I think most clearly when walking, never at a desk."},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "text"
    assert body["content"] == "I think most clearly when walking, never at a desk."
    assert body["chunk_count"] == 1
    assert body["id"]

    # Confirm it really landed in the store, not just echoed back.
    stored = store.get_memory(body["id"])
    assert stored is not None
    assert stored.type is MemoryType.TEXT


def test_explicit_title_is_kept(client):
    response = client.post(
        "/memories/text",
        json={"content": "Some reflection about mornings.", "title": "Morning ritual"},
    )
    assert response.json()["title"] == "Morning ritual"


def test_title_is_derived_when_absent(client):
    response = client.post(
        "/memories/text",
        json={"content": "one two three four five six seven eight nine ten"},
    )
    assert response.json()["title"] == "one two three four five six seven eight…"


def test_content_is_trimmed(client):
    response = client.post("/memories/text", json={"content": "  padded note  "})
    assert response.json()["content"] == "padded note"


def test_empty_content_rejected(client):
    for bad in ["", "   ", "\n\t "]:
        response = client.post("/memories/text", json={"content": bad})
        assert response.status_code == 422, f"expected 422 for {bad!r}"


def test_missing_content_field_rejected(client):
    assert client.post("/memories/text", json={}).status_code == 422


def test_oversized_content_rejected(client):
    response = client.post("/memories/text", json={"content": "x" * 100_001})
    assert response.status_code == 422
    assert "document" in response.text.lower()


def test_snippet_truncates_long_content(client):
    response = client.post("/memories/text", json={"content": "word " * 200})
    snippet = response.json()["snippet"]
    assert len(snippet) <= 160
    assert snippet.endswith("…")


def test_stored_memory_is_searchable(client):
    client.post("/memories/text", json={"content": "I love sailing at dawn."})
    client.post("/memories/text", json={"content": "Reconcile the budget spreadsheet."})

    results = store.search_memories("boats on the water", k=1)
    assert "sailing" in results[0].memory.content


def test_derive_title_handles_short_content():
    assert derive_title("just three words") == "just three words"
    assert derive_title("a b c d e f g h i") == "a b c d e f g h…"

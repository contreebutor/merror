"""Tests for the memory ingestion routes."""

from app import store
from app.models import MemoryType
from app.routers.memories import derive_title
from tests.helpers import make_docx, make_empty_pdf, make_pdf


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


# --- Document upload -------------------------------------------------------


def upload(client, filename: str, data: bytes, **form):
    return client.post(
        "/memories/document",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )


def test_upload_txt_creates_document_memory(client):
    response = upload(client, "journal.txt", b"A quiet morning thought.")

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "document"
    assert body["source"] == "journal.txt"
    assert body["title"] == "journal.txt"
    assert "quiet morning" in body["content"]

    assert store.get_memory(body["id"]).type is MemoryType.DOCUMENT


def test_upload_pdf(client):
    data = make_pdf(["Reflections written on a train.", "The window was cold."])
    body = upload(client, "train.pdf", data).json()

    assert "Reflections written on a train." in body["content"]


def test_upload_docx_including_tables(client):
    data = make_docx(["Meeting notes."], table_rows=[["topic", "outcome"]])
    body = upload(client, "notes.docx", data).json()

    assert "Meeting notes." in body["content"]
    assert "topic | outcome" in body["content"]


def test_explicit_title_overrides_filename(client):
    body = upload(client, "a.txt", b"Some content here.", title="My Journal").json()
    assert body["title"] == "My Journal"


def test_long_document_is_chunked(client):
    text = "\n\n".join(f"Paragraph {i}. " + "reflective content. " * 40 for i in range(20))
    body = upload(client, "long.txt", text.encode()).json()

    assert body["chunk_count"] > 1, "a long document should split into chunks"
    assert store.count_memories() == 1, "chunks must stay one logical memory"


def test_chunked_document_is_searchable_by_inner_content(client):
    text = "\n\n".join(
        [
            "Opening section about ordinary things. " * 20,
            "A distinctive passage about lighthouses on rocky coasts. " * 10,
            "Closing section about ordinary things. " * 20,
        ]
    )
    upload(client, "essay.txt", text.encode())

    results = store.search_memories("lighthouse by the sea", k=1)
    assert results, "chunked document should be retrievable"
    assert "lighthouse" in results[0].matched_chunk.lower()


def test_unsupported_type_returns_415(client):
    response = upload(client, "photo.png", b"\x89PNG\r\n")
    assert response.status_code == 415
    assert ".pdf" in response.json()["detail"]


def test_corrupt_pdf_returns_422(client):
    response = upload(client, "broken.pdf", b"%PDF-1.4 nonsense")
    assert response.status_code == 422


def test_scanned_pdf_returns_helpful_422(client):
    response = upload(client, "scan.pdf", make_empty_pdf())
    assert response.status_code == 422
    assert "image" in response.json()["detail"].lower()


def test_empty_file_returns_422(client):
    assert upload(client, "empty.txt", b"").status_code == 422


def test_whitespace_only_file_returns_422(client):
    assert upload(client, "blank.txt", b"   \n\n  \t ").status_code == 422


def test_oversized_upload_returns_413(client):
    response = upload(client, "huge.txt", b"x" * (25 * 1024 * 1024 + 1))
    assert response.status_code == 413
    assert "MB" in response.json()["detail"]


def test_failed_upload_stores_nothing(client):
    upload(client, "photo.png", b"data")
    upload(client, "broken.pdf", b"%PDF nonsense")
    assert store.count_memories() == 0


def test_supported_types_endpoint(client):
    body = client.get("/memories/supported-types").json()
    assert ".pdf" in body["extensions"]
    assert body["max_bytes"] == 25 * 1024 * 1024

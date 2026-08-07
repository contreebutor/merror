"""Tests for the memory ingestion routes."""

from pathlib import Path

from app import store
from app.models import MemoryType
from app.routers.memories import derive_title
from tests.helpers import (
    make_docx,
    make_empty_pdf,
    make_gif,
    make_jpeg,
    make_pdf,
    make_png,
    refusal_response,
    text_response,
)


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
    assert ".png" in body["image_extensions"]


# --- Image upload ----------------------------------------------------------


def upload_image(client, filename: str, data: bytes, **form):
    return client.post(
        "/memories/image",
        files={"file": (filename, data, "application/octet-stream")},
        data=form,
    )


def test_upload_image_describes_embeds_and_stores(client, fake_vision):
    fake_vision(text_response("A sunlit desk with an open notebook and cold coffee."))

    response = upload_image(client, "desk.png", make_png())

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "image"
    assert body["source"] == "desk.png"
    assert "sunlit desk" in body["content"]

    # The description — not the raw bytes — is what got embedded.
    stored = store.get_memory(body["id"])
    assert stored.type is MemoryType.IMAGE
    assert "notebook" in stored.content


def test_original_image_is_saved_locally(client, fake_vision):
    fake_vision(text_response("A photograph."))
    data = make_png()

    body = upload_image(client, "photo.png", data).json()
    stored_path = Path(store.get_memory(body["id"]).file_path)

    assert stored_path.is_file()
    assert stored_path.read_bytes() == data, "image must be stored byte-identical"
    assert stored_path.stem == body["id"], "filename derives from the memory id"


def test_image_memory_is_searchable_by_description(client, fake_vision):
    fake_vision(text_response("A golden retriever asleep on a porch in summer."))
    upload_image(client, "dog.png", make_png())

    results = store.search_memories("my pet sleeping outdoors", k=1)
    assert results
    assert results[0].memory.type is MemoryType.IMAGE


def test_all_supported_image_formats_accepted(client, fake_vision):
    fake_vision(text_response("An image."))

    for name, data in [("a.png", make_png()), ("b.jpg", make_jpeg()), ("c.gif", make_gif())]:
        assert upload_image(client, name, data).status_code == 201, name


def test_explicit_title_overrides_filename_for_images(client, fake_vision):
    fake_vision(text_response("An image."))
    body = upload_image(client, "IMG_4821.png", make_png(), title="Kitchen window").json()
    assert body["title"] == "Kitchen window"


def test_non_image_extension_returns_415(client, fake_vision):
    client_stub = fake_vision(text_response("unused"))

    response = upload_image(client, "notes.pdf", make_pdf(["text"]))

    assert response.status_code == 415
    assert client_stub.messages.calls == [], "must not call the API for a rejected type"


def test_disguised_file_returns_422(client, fake_vision):
    # A PDF renamed to .png must be caught by content sniffing, not sent onward.
    client_stub = fake_vision(text_response("unused"))

    response = upload_image(client, "sneaky.png", make_pdf(["I am a PDF"]))

    assert response.status_code == 422
    assert "does not look like a valid image" in response.json()["detail"]
    assert client_stub.messages.calls == []


def test_empty_image_returns_422(client, fake_vision):
    fake_vision(text_response("unused"))
    assert upload_image(client, "empty.png", b"").status_code == 422


def test_oversized_image_returns_413(client, fake_vision):
    from app.vision import MAX_IMAGE_BYTES

    fake_vision(text_response("unused"))
    response = upload_image(client, "huge.png", b"\x89PNG\r\n\x1a\n" + b"x" * MAX_IMAGE_BYTES)

    assert response.status_code == 413
    assert "MB" in response.json()["detail"]


def test_refused_image_returns_422_and_stores_nothing(client, fake_vision):
    fake_vision(refusal_response(category="privacy"))

    response = upload_image(client, "private.png", make_png())

    assert response.status_code == 422
    assert store.count_memories() == 0
    assert not any(client_images().iterdir()), "no image file should be left behind"


def test_api_failure_returns_502_and_stores_nothing(client, fake_vision):
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    fake_vision(anthropic.APIConnectionError(request=request))

    response = upload_image(client, "photo.png", make_png())

    assert response.status_code == 502
    assert store.count_memories() == 0
    assert not any(client_images().iterdir())


def client_images():
    """The temp images directory for the current test."""
    from app import media

    return media.images_dir()

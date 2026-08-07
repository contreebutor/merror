"""Tests for listing, retrieving, and deleting memories."""

from pathlib import Path

from app import store
from app.models import MemoryType
from tests.helpers import make_png, text_response


def seed(client, notes: list[str]) -> list[str]:
    """Create text memories and return their ids, oldest first."""
    return [
        client.post("/memories/text", json={"content": note}).json()["id"] for note in notes
    ]


# --- Listing ---------------------------------------------------------------


def test_empty_store_lists_nothing(client):
    body = client.get("/memories").json()
    assert body == {"memories": [], "total": 0, "limit": 50, "offset": 0, "query": ""}


def test_list_returns_newest_first(client):
    ids = seed(client, ["oldest note", "middle note", "newest note"])

    body = client.get("/memories").json()

    assert [m["id"] for m in body["memories"]] == list(reversed(ids))
    assert body["total"] == 3


def test_list_returns_snippets_not_full_content(client):
    client.post("/memories/text", json={"content": "word " * 500})

    item = client.get("/memories").json()["memories"][0]

    assert "content" not in item, "list must not carry full content"
    assert len(item["snippet"]) <= 160


def test_list_never_exposes_filesystem_paths(client, fake_vision):
    fake_vision(text_response("A photo of the sea."))
    client.post("/memories/image", files={"file": ("sea.png", make_png(), "image/png")})

    item = client.get("/memories").json()["memories"][0]

    assert item["has_image"] is True
    assert "file_path" not in item, "server paths must not reach the client"


def test_list_pagination(client):
    seed(client, [f"note number {i}" for i in range(5)])

    page = client.get("/memories?limit=2&offset=2").json()

    assert len(page["memories"]) == 2
    assert page["total"] == 5, "total counts all matches, not just this page"
    assert page["limit"] == 2 and page["offset"] == 2


def test_list_filters_by_type(client):
    client.post("/memories/text", json={"content": "a plain note"})
    client.post("/memories/document", files={"file": ("d.txt", b"document text here")})

    body = client.get("/memories?type=document").json()

    assert body["total"] == 1
    assert body["memories"][0]["type"] == "document"


def test_invalid_type_rejected(client):
    assert client.get("/memories?type=nonsense").status_code == 422


def test_pagination_bounds_enforced(client):
    assert client.get("/memories?limit=0").status_code == 422
    assert client.get("/memories?limit=500").status_code == 422
    assert client.get("/memories?offset=-1").status_code == 422


# --- Search ----------------------------------------------------------------


def test_search_ranks_by_meaning_not_keywords(client):
    client.post("/memories/text", json={"content": "I love hiking in the mountains."})
    client.post("/memories/text", json={"content": "The quarterly budget needs review."})

    body = client.get("/memories?q=outdoor walks in nature").json()

    assert body["query"] == "outdoor walks in nature"
    assert "hiking" in body["memories"][0]["snippet"]
    assert 0.0 <= body["memories"][0]["score"] <= 1.0


def test_plain_list_has_no_scores(client):
    seed(client, ["a note"])
    assert client.get("/memories").json()["memories"][0]["score"] is None


def test_search_respects_type_filter(client):
    client.post("/memories/text", json={"content": "sailing boats at dawn"})
    client.post("/memories/document", files={"file": ("s.txt", b"sailing boats at dusk")})

    body = client.get("/memories?q=sailing&type=document").json()

    assert all(m["type"] == "document" for m in body["memories"])


def test_whitespace_query_is_treated_as_no_query(client):
    seed(client, ["a note"])
    body = client.get("/memories?q=%20%20").json()
    assert body["query"] == ""
    assert body["total"] == 1


# --- Single memory ---------------------------------------------------------


def test_get_one_returns_full_content(client):
    long_text = "unique marker. " * 100
    memory_id = client.post("/memories/text", json={"content": long_text}).json()["id"]

    body = client.get(f"/memories/{memory_id}").json()

    assert body["content"].startswith("unique marker.")
    assert len(body["content"]) > 160


def test_get_missing_memory_returns_404(client):
    assert client.get("/memories/does-not-exist").status_code == 404


def test_supported_types_is_not_shadowed_by_the_id_route(client):
    """Route order regression: a literal path must win over `/{memory_id}`."""
    response = client.get("/memories/supported-types")

    assert response.status_code == 200
    assert "extensions" in response.json(), "was captured as a memory id"


# --- Images ----------------------------------------------------------------


def test_get_image_returns_the_original_bytes(client, fake_vision):
    fake_vision(text_response("A photograph."))
    data = make_png(4, 4)
    memory_id = client.post(
        "/memories/image", files={"file": ("photo.png", data, "image/png")}
    ).json()["id"]

    response = client.get(f"/memories/{memory_id}/image")

    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/png"


def test_get_image_for_text_memory_returns_404(client):
    memory_id = seed(client, ["just text"])[0]
    response = client.get(f"/memories/{memory_id}/image")

    assert response.status_code == 404
    assert "no image" in response.json()["detail"].lower()


def test_get_image_when_file_vanished_returns_404(client, fake_vision):
    fake_vision(text_response("A photograph."))
    memory_id = client.post(
        "/memories/image", files={"file": ("photo.png", make_png(), "image/png")}
    ).json()["id"]

    Path(store.get_memory(memory_id).file_path).unlink()

    response = client.get(f"/memories/{memory_id}/image")
    assert response.status_code == 404, "a missing file must 404, not 500"


# --- Deletion --------------------------------------------------------------


def test_delete_removes_memory(client):
    memory_id = seed(client, ["forget me"])[0]

    body = client.delete(f"/memories/{memory_id}").json()

    assert body == {"id": memory_id, "deleted": True, "image_deleted": False}
    assert client.get(f"/memories/{memory_id}").status_code == 404
    assert store.count_memories() == 0


def test_delete_removes_all_chunks_of_a_document(client):
    text = "\n\n".join(f"Paragraph {i}. " + "content. " * 40 for i in range(15))
    memory_id = client.post(
        "/memories/document", files={"file": ("long.txt", text.encode())}
    ).json()["id"]
    assert store.get_memory(memory_id).chunk_count > 1

    client.delete(f"/memories/{memory_id}")

    assert store.count_memories() == 0
    assert store.search_memories("Paragraph 3") == [], "chunks must not survive"


def test_delete_also_removes_the_image_file(client, fake_vision):
    fake_vision(text_response("A photograph."))
    memory_id = client.post(
        "/memories/image", files={"file": ("photo.png", make_png(), "image/png")}
    ).json()["id"]
    path = Path(store.get_memory(memory_id).file_path)
    assert path.exists()

    body = client.delete(f"/memories/{memory_id}").json()

    assert body["image_deleted"] is True
    assert not path.exists(), "personal image data must not survive deletion"


def test_delete_missing_memory_returns_404(client):
    assert client.delete("/memories/does-not-exist").status_code == 404


def test_delete_is_not_idempotent_silently(client):
    memory_id = seed(client, ["once"])[0]

    assert client.delete(f"/memories/{memory_id}").status_code == 200
    assert client.delete(f"/memories/{memory_id}").status_code == 404


def test_deleting_one_memory_leaves_others_intact(client):
    ids = seed(client, ["keep me", "delete me", "keep me too"])

    client.delete(f"/memories/{ids[1]}")

    remaining = client.get("/memories").json()
    assert remaining["total"] == 2
    assert {m["id"] for m in remaining["memories"]} == {ids[0], ids[2]}


def test_deleted_memory_is_not_searchable(client):
    memory_id = client.post(
        "/memories/text", json={"content": "A distinctive memory about lighthouses."}
    ).json()["id"]

    client.delete(f"/memories/{memory_id}")

    assert store.search_memories("lighthouse", k=5) == []


def test_delete_then_list_by_type(client, fake_vision):
    fake_vision(text_response("An image."))
    client.post("/memories/text", json={"content": "a note"})
    image_id = client.post(
        "/memories/image", files={"file": ("p.png", make_png(), "image/png")}
    ).json()["id"]

    client.delete(f"/memories/{image_id}")

    assert client.get("/memories?type=image").json()["total"] == 0
    assert client.get("/memories?type=text").json()["total"] == 1
    assert store.get_memory(image_id) is None
    assert MemoryType.IMAGE not in {
        m.type for m in store.list_memories()
    }

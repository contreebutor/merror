"""Tests for the 2D memory map."""

import numpy as np

from app import projection, store
from app.models import MemoryType


def unit(*values: float) -> list[float]:
    vector = np.asarray(values, dtype=np.float64)
    return list(vector / np.linalg.norm(vector))


# --- Maths -----------------------------------------------------------------


def test_normalise_makes_rows_unit_length():
    normalised = projection.normalise(np.array([[3.0, 4.0], [0.0, 2.0]]))
    assert np.allclose(np.linalg.norm(normalised, axis=1), 1.0)


def test_normalise_survives_a_zero_vector():
    """A zero row would divide by zero and poison the whole layout with NaN."""
    normalised = projection.normalise(np.array([[0.0, 0.0], [1.0, 0.0]]))
    assert not np.isnan(normalised).any()


def test_pca_puts_the_widest_spread_on_the_first_axis():
    # Points varying mostly along one direction.
    points = np.array([[float(i), 0.05 * float(i % 3), 0.0] for i in range(30)])
    projected = projection.pca_2d(points)

    assert projected[:, 0].var() > projected[:, 1].var()


def test_layout_is_deterministic():
    """The same archive must always draw the same map."""
    embeddings = {
        f"m{i}": unit(np.sin(i), np.cos(i), np.sin(i * 2), np.cos(i * 3)) for i in range(20)
    }

    first_positions, first_edges = projection.build_layout(embeddings)
    second_positions, second_edges = projection.build_layout(embeddings)

    assert first_positions == second_positions
    assert sorted(first_edges) == sorted(second_edges)


def test_layout_fits_inside_the_unit_square():
    embeddings = {f"m{i}": unit(np.sin(i), np.cos(i), float(i % 4)) for i in range(25)}

    positions, _ = projection.build_layout(embeddings)

    for x, y, _ in positions.values():
        assert -1.0001 <= x <= 1.0001
        assert -1.0001 <= y <= 1.0001


def test_scale_handles_identical_points():
    """Identical embeddings have no extent; scaling must not divide by zero."""
    scaled = projection.scale_to_unit_square(np.ones((5, 2)))
    assert not np.isnan(scaled).any()


# --- Degenerate archives ---------------------------------------------------


def test_empty_archive():
    positions, edges = projection.build_layout({})
    assert positions == {} and edges == []


def test_single_memory_sits_at_the_origin():
    positions, edges = projection.build_layout({"only": unit(1.0, 0.0, 0.0)})
    assert positions == {"only": (0.0, 0.0, 0)}
    assert edges == []


def test_two_memories_are_placed_apart():
    positions, _ = projection.build_layout(
        {"a": unit(1.0, 0.0), "b": unit(0.0, 1.0)}
    )
    assert len(positions) == 2
    assert positions["a"][0] != positions["b"][0]


def test_two_similar_memories_are_linked():
    _, edges = projection.build_layout({"a": unit(1.0, 0.02), "b": unit(1.0, 0.03)})
    assert len(edges) == 1


def test_two_unrelated_memories_are_not_linked():
    _, edges = projection.build_layout({"a": unit(1.0, 0.0), "b": unit(0.0, 1.0)})
    assert edges == []


# --- Clustering and edges --------------------------------------------------


def test_clustering_separates_two_groups():
    """Two tight, well-separated groups should not share a cluster."""
    embeddings = {}
    for i in range(8):
        embeddings[f"left{i}"] = unit(1.0, 0.01 * i, 0.0, 0.0)
        embeddings[f"right{i}"] = unit(0.0, 0.0, 1.0, 0.01 * i)

    positions, _ = projection.build_layout(embeddings)

    left = {positions[f"left{i}"][2] for i in range(8)}
    right = {positions[f"right{i}"][2] for i in range(8)}
    assert left.isdisjoint(right), "distinct groups must get distinct clusters"


def test_edges_are_undirected_and_deduplicated():
    embeddings = {f"m{i}": unit(1.0, 0.01 * i, 0.005 * i) for i in range(10)}

    _, edges = projection.build_layout(embeddings)
    pairs = [(a, b) for a, b, _ in edges]

    assert len(pairs) == len(set(pairs)), "no duplicate edges"
    assert all((b, a) not in pairs for a, b in pairs), "no mirrored duplicates"


def test_edges_never_link_a_memory_to_itself():
    embeddings = {f"m{i}": unit(1.0, 0.01 * i) for i in range(6)}
    _, edges = projection.build_layout(embeddings)
    assert all(a != b for a, b, _ in edges)


def test_suggested_cluster_count_grows_with_size():
    assert projection.suggest_cluster_count(3) == 1
    assert projection.suggest_cluster_count(50) >= 2
    assert projection.suggest_cluster_count(10_000) <= 8


# --- Store integration -----------------------------------------------------


def test_embeddings_are_averaged_per_memory():
    """A multi-chunk document is one point, not several."""
    store.add_memory("short note")
    store.add_memory("doc", MemoryType.DOCUMENT, chunks=["part one", "part two", "part three"])

    embeddings = store.get_memory_embeddings()

    assert len(embeddings) == 2, "one vector per memory, not per chunk"
    assert all(len(vector) == 384 for vector in embeddings.values())


def test_map_endpoint_on_an_empty_archive(client):
    body = client.get("/memories/map").json()
    assert body == {"nodes": [], "edges": [], "clusters": 0}


def test_map_endpoint_places_every_memory(client):
    for text in [
        "I love hiking in the mountains at dawn.",
        "Long walks along the coast clear my head.",
        "The quarterly budget needs reconciling.",
        "Expense reports are due on Friday.",
    ]:
        client.post("/memories/text", json={"content": text})

    body = client.get("/memories/map").json()

    assert len(body["nodes"]) == 4
    assert body["clusters"] >= 1
    for node in body["nodes"]:
        assert -1.0001 <= node["x"] <= 1.0001
        assert -1.0001 <= node["y"] <= 1.0001
        assert node["title"] and node["snippet"]


def test_map_edges_reference_real_nodes(client):
    for text in ["sailing at dawn", "sailing at dusk", "budget spreadsheet"]:
        client.post("/memories/text", json={"content": text})

    body = client.get("/memories/map").json()
    ids = {node["id"] for node in body["nodes"]}

    for edge in body["edges"]:
        assert edge["source"] in ids and edge["target"] in ids
        assert 0.0 <= edge["similarity"] <= 1.0


def test_map_drops_deleted_memories(client):
    first = client.post("/memories/text", json={"content": "keep me"}).json()["id"]
    second = client.post("/memories/text", json={"content": "delete me"}).json()["id"]

    client.delete(f"/memories/{second}")
    body = client.get("/memories/map").json()

    assert [node["id"] for node in body["nodes"]] == [first]


def test_map_is_not_shadowed_by_the_id_route(client):
    """Route order regression: /memories/map must not be read as an id."""
    response = client.get("/memories/map")
    assert response.status_code == 200
    assert "nodes" in response.json()


def test_edge_threshold_adapts_to_the_archive():
    """A fixed constant links everything or nothing; the cut must be relative."""
    # A tightly-themed archive: all pairs are close.
    tight = np.full((6, 6), 0.8)
    # A scattered one: all pairs are distant.
    scattered = np.full((6, 6), 0.05)

    assert projection.edge_threshold(tight) > projection.edge_threshold(scattered)


def test_edge_threshold_never_falls_below_the_floor():
    """An archive of unrelated notes should draw no links at all."""
    unrelated = np.full((8, 8), -0.2)
    assert projection.edge_threshold(unrelated) >= projection.EDGE_SIMILARITY_FLOOR


def test_realistic_archive_draws_some_but_not_all_edges():
    """The map should show structure without becoming a hairball."""
    embeddings = {}
    for i in range(6):
        embeddings[f"outdoors{i}"] = unit(1.0, 0.05 * i, 0.02 * i, 0.0)
    for i in range(6):
        embeddings[f"admin{i}"] = unit(0.0, 0.02 * i, 1.0, 0.05 * i)

    _, edges = projection.build_layout(embeddings)
    possible = len(embeddings) * (len(embeddings) - 1) // 2

    assert 0 < len(edges) < possible, f"got {len(edges)} of {possible} possible edges"

"""Projecting the memory archive into two dimensions.

The map answers "what shape is my archive?" — which memories sit near each
other in meaning, and where the clusters are.

Implemented directly on numpy rather than with scikit-learn or UMAP:

- **No new dependency.** numpy already ships with ChromaDB; PCA and k-means are
  a few dozen lines each.
- **Deterministic.** The same archive always produces the same layout. UMAP and
  t-SNE are stochastic, so a map you revisit would be rearranged every time —
  disorienting for something meant to become familiar.
- **Fast.** Exact SVD on a few thousand points is milliseconds.

The trade-off is honest: PCA separates clusters less crisply than UMAP. At
personal-archive scale that is a fair price for a stable, dependency-free map.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger("merror.projection")

# Beyond this many neighbours the map turns into a hairball rather than a shape.
MAX_EDGES_PER_NODE = 3

# Only draw an edge between memories that are genuinely close in meaning.
EDGE_SIMILARITY_THRESHOLD = 0.45


def normalise(vectors: np.ndarray) -> np.ndarray:
    """Scale each row to unit length.

    The store compares memories by cosine distance, so normalising first means
    Euclidean distance in the projected plane approximates the similarity the
    rest of the app uses. Without this, long documents drift outward purely
    because their vectors are larger.
    """
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def pca_2d(vectors: np.ndarray) -> np.ndarray:
    """Project vectors onto their two principal components."""
    centred = vectors - vectors.mean(axis=0, keepdims=True)

    # SVD rather than an eigendecomposition of the covariance matrix: it is
    # numerically better behaved and avoids forming a 384x384 matrix.
    _, _, components = np.linalg.svd(centred, full_matrices=False)
    projected = centred @ components[:2].T

    # Sign is arbitrary in SVD, which would flip the map between runs on
    # near-symmetric data. Pin it: the largest-magnitude coordinate on each
    # axis is always positive.
    for axis in range(projected.shape[1]):
        column = projected[:, axis]
        if column[np.argmax(np.abs(column))] < 0:
            projected[:, axis] = -column

    return projected


def scale_to_unit_square(points: np.ndarray) -> np.ndarray:
    """Fit the layout into [-1, 1] on both axes, preserving aspect ratio."""
    if len(points) == 0:
        return points

    centred = points - points.mean(axis=0, keepdims=True)
    extent = np.abs(centred).max()
    # A single point, or several identical ones, has no extent to scale by.
    if extent < 1e-9:
        return np.zeros_like(centred)
    return centred / extent


def kmeans(points: np.ndarray, k: int, *, iterations: int = 60) -> np.ndarray:
    """Cluster points, deterministically. Returns a label per point.

    Seeds are chosen farthest-first rather than at random, so the result
    depends only on the data — the same archive always colours the same way.
    """
    if k <= 1 or len(points) <= k:
        return np.zeros(len(points), dtype=int)

    # Farthest-first seeding: start from the point nearest the centre, then
    # repeatedly take whichever point is furthest from every seed so far.
    centre = points.mean(axis=0)
    seeds = [int(np.argmin(np.linalg.norm(points - centre, axis=1)))]
    while len(seeds) < k:
        distances = np.min(
            np.linalg.norm(points[:, None, :] - points[seeds][None, :, :], axis=2), axis=1
        )
        seeds.append(int(np.argmax(distances)))

    centroids = points[seeds].copy()
    labels = np.zeros(len(points), dtype=int)

    for _ in range(iterations):
        distances = np.linalg.norm(points[:, None, :] - centroids[None, :, :], axis=2)
        new_labels = np.argmin(distances, axis=1)
        if np.array_equal(new_labels, labels):
            break  # converged
        labels = new_labels
        for index in range(k):
            members = points[labels == index]
            if len(members):
                centroids[index] = members.mean(axis=0)

    return labels


def suggest_cluster_count(count: int) -> int:
    """How many clusters to look for in an archive of this size."""
    if count < 6:
        return 1
    return int(min(8, max(2, round(count**0.5 / 1.3))))


def nearest_neighbours(
    vectors: np.ndarray, *, per_node: int = MAX_EDGES_PER_NODE
) -> list[tuple[int, int, float]]:
    """Find close pairs, as (index, index, similarity) with index_a < index_b.

    Computed on the full-dimensional vectors, not the 2D projection: two
    memories can land near each other on the plane by accident of flattening,
    and an edge should mean actual similarity.
    """
    if len(vectors) < 2:
        return []

    # Rows are unit length, so the dot product is cosine similarity.
    similarity = vectors @ vectors.T
    np.fill_diagonal(similarity, -np.inf)

    edges: dict[tuple[int, int], float] = {}
    take = min(per_node, len(vectors) - 1)

    for index in range(len(vectors)):
        # argpartition finds the top-k without sorting the whole row.
        candidates = np.argpartition(similarity[index], -take)[-take:]
        for other in candidates:
            score = float(similarity[index, other])
            if score < EDGE_SIMILARITY_THRESHOLD:
                continue
            key = (min(index, int(other)), max(index, int(other)))
            edges[key] = max(edges.get(key, 0.0), score)

    return [(a, b, score) for (a, b), score in edges.items()]


def build_layout(
    embeddings: dict[str, list[float]],
) -> tuple[dict[str, tuple[float, float, int]], list[tuple[str, str, float]]]:
    """Lay out memories in 2D and connect the close ones.

    Returns positions keyed by memory id as (x, y, cluster), plus edges as
    (id, id, similarity).
    """
    ids = list(embeddings)
    if not ids:
        return {}, []

    vectors = normalise(np.asarray([embeddings[key] for key in ids], dtype=np.float64))

    # One or two points have no variance to project; place them by hand.
    if len(ids) == 1:
        return {ids[0]: (0.0, 0.0, 0)}, []
    if len(ids) == 2:
        similarity = float(vectors[0] @ vectors[1])
        positions = {ids[0]: (-0.6, 0.0, 0), ids[1]: (0.6, 0.0, 0)}
        edges = (
            [(ids[0], ids[1], similarity)]
            if similarity >= EDGE_SIMILARITY_THRESHOLD
            else []
        )
        return positions, edges

    points = scale_to_unit_square(pca_2d(vectors))
    labels = kmeans(points, suggest_cluster_count(len(ids)))

    positions = {
        memory_id: (float(points[i, 0]), float(points[i, 1]), int(labels[i]))
        for i, memory_id in enumerate(ids)
    }
    edges = [(ids[a], ids[b], score) for a, b, score in nearest_neighbours(vectors)]

    logger.info(
        "Laid out %d memories into %d clusters with %d edges",
        len(ids),
        len(set(labels.tolist())),
        len(edges),
    )
    return positions, edges

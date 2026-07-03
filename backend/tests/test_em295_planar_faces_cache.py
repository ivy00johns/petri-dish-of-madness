"""EM-295 (W29) — planar_faces is memoized per graph, keyed by a structural
signature, so it is not recomputed from scratch on every agent-turn perception +
zone action. The cache MUST be transparent: identical to a fresh computation,
self-invalidating on any node/edge change, and never serialized (determinism).
"""
from __future__ import annotations

from petridish.engine.citygraph import (
    CityGraph, CityNode, CityEdge, classic_grid, apply_build_road,
    apply_demolish_road, planar_faces, _planar_faces_uncached, _faces_signature,
)


def _faces_key(faces):
    """A comparable projection of a face list (Face is not hashable)."""
    return [(f.boundary, f.poly, f.centroid, f.area) for f in faces]


# ── the cache is transparent: identical to a fresh computation ────────────────

def test_cached_faces_identical_to_fresh():
    g = classic_grid(1337)
    fresh = _planar_faces_uncached(g)
    cached = planar_faces(g)
    assert _faces_key(cached) == _faces_key(fresh)
    # The 5x5 grid encloses 25 blocks.
    assert len(cached) == 25


def test_second_call_returns_the_same_cached_object():
    g = classic_grid(1337)
    first = planar_faces(g)
    second = planar_faces(g)
    # A cache HIT returns the very same list object (no recompute).
    assert second is first


# ── the signature self-invalidates on any node/edge change ────────────────────

def test_cache_invalidates_when_an_edge_is_added():
    g = classic_grid(1337)
    before = planar_faces(g)
    ok, _reason, _info = apply_build_road(g, "n:12:12", "east")
    assert ok
    after = planar_faces(g)
    # A structural change ⇒ a fresh result (NOT the stale cached object), and it
    # matches a from-scratch computation on the mutated graph.
    assert after is not before
    assert _faces_key(after) == _faces_key(_planar_faces_uncached(g))


def test_cache_invalidates_when_an_edge_is_demolished():
    g = classic_grid(1337)
    n_before = len(planar_faces(g))
    edge_id = g.edges[0].id
    ok, _reason, _info = apply_demolish_road(g, edge_id)
    assert ok
    after = planar_faces(g)
    assert _faces_key(after) == _faces_key(_planar_faces_uncached(g))
    # Tearing down a perimeter edge merges the block into the outer face.
    assert len(after) == n_before - 1


def test_cache_invalidates_when_a_node_moves():
    g = classic_grid(1337)
    _ = planar_faces(g)
    # Nudge a node's coordinate: same ids, different geometry ⇒ different faces.
    g.nodes[0].x += 0.5
    after = planar_faces(g)
    assert _faces_key(after) == _faces_key(_planar_faces_uncached(g))


def test_signature_is_order_independent():
    g = classic_grid(1337)
    sig = _faces_signature(g)
    shuffled = CityGraph(seed=g.seed, nodes=list(reversed(g.nodes)),
                         edges=list(reversed(g.edges)))
    assert _faces_signature(shuffled) == sig


# ── the cache is never serialized (determinism / snapshot byte-identity) ──────

def test_cache_is_not_serialized():
    g = classic_grid(1337)
    _ = planar_faces(g)                       # populate the cache
    assert getattr(g, "_faces_cache", None) is not None
    d = g.to_dict()
    assert "_faces_cache" not in d
    # A round-trip drops the cache; the restored graph recomputes identically.
    restored = CityGraph.from_dict(d)
    assert getattr(restored, "_faces_cache", None) is None
    assert _faces_key(planar_faces(restored)) == _faces_key(planar_faces(g))


def test_empty_graph_still_returns_empty_without_caching_attr():
    g = CityGraph(seed=1, nodes=[], edges=[])
    assert planar_faces(g) == []
    # The cheap guard returns before attaching a cache to an edgeless graph.
    assert getattr(g, "_faces_cache", None) is None

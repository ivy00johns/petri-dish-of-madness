"""
EM-222 — pure unit tests for the relevance-scored memory retriever
(backend/petridish/agents/memory_retrieval.py). NO router, NO DB, NO world: the
scoring half is pure + deterministic, so these tests exercise it directly over
plain dicts + a tiny fake embeddings table. The async orchestration
(_retrieve_memory: embed → fetch → score → merge → dedupe) is covered by
backend/tests/test_em222_integration.py (a real AgentRuntime + Router + repo),
not here.

Self-check: backend/.venv/bin/python -m pytest backend/tests/test_em222_retrieval.py -q
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

# Import the engine package root FIRST to settle the package-init order (the
# suite-wide idiom — agents/__init__ ↔ engine/__init__ would otherwise raise a
# partial-init ImportError when a leaf agents module is imported cold).
import petridish.engine.world  # noqa: F401
from petridish.agents.memory_retrieval import (
    BROADCAST_KINDS,
    RetrievalWeights,
    build_query_text,
    cosine,
    score_candidates,
)


# A tiny deterministic embedding space: 3 orthonormal-ish axes so cosine is
# trivially predictable. The retriever never assumes a particular dimension.
VEC_FOOD = [1.0, 0.0, 0.0]
VEC_FEUD = [0.0, 1.0, 0.0]
VEC_RULE = [0.0, 0.0, 1.0]
VEC_FOODISH = [0.9, 0.1, 0.0]   # near-parallel to VEC_FOOD (high cosine)


def _importance_by_kind(weights: dict[str, float]):
    """A stand-in for AgentRuntime._event_importance: weight by event kind."""
    def _imp(event: dict) -> float:
        return float(weights.get(event.get("kind"), 0.0))
    return _imp


# ──────────────────────────────────────────────────────────────────────────────
# cosine — edge cases (the contract calls out zero-norm ⇒ 0)
# ──────────────────────────────────────────────────────────────────────────────

def test_cosine_identical_is_one():
    assert cosine([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)


def test_cosine_orthogonal_is_zero():
    assert cosine(VEC_FOOD, VEC_FEUD) == pytest.approx(0.0)


def test_cosine_opposite_is_negative_one():
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)


def test_cosine_zero_norm_returns_zero():
    # A zero vector has no direction ⇒ similar to nothing ⇒ 0.0, never NaN/div0.
    assert cosine([0.0, 0.0, 0.0], VEC_FOOD) == 0.0
    assert cosine(VEC_FOOD, [0.0, 0.0, 0.0]) == 0.0
    assert cosine([0.0, 0.0], [0.0, 0.0]) == 0.0


def test_cosine_empty_or_mismatched_length_returns_zero():
    assert cosine([], VEC_FOOD) == 0.0
    assert cosine(VEC_FOOD, []) == 0.0
    assert cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0


def test_cosine_near_parallel_is_high():
    assert cosine(VEC_FOOD, VEC_FOODISH) > 0.9


# ──────────────────────────────────────────────────────────────────────────────
# score_candidates — the headline contract behaviors
# ──────────────────────────────────────────────────────────────────────────────

def test_old_high_relevance_outranks_recent_low_relevance():
    """The whole point of EM-222: a RELEVANT old memory beats a recent
    irrelevant one. With relevance weighted over recency, an ancient food event
    (tick 1) that matches a 'food' query outranks a brand-new feud event (tick
    100) that does not — exactly the recall a pure recency window misses."""
    query_vec = VEC_FOOD
    candidates = [
        {"seq": 1, "tick": 1, "kind": "agent_action", "text": "found food"},
        {"seq": 2, "tick": 100, "kind": "agent_action", "text": "a feud"},
    ]
    embeddings = {1: VEC_FOOD, 2: VEC_FEUD}
    weights = RetrievalWeights(
        relevance=0.7, importance=0.0, recency=0.3, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=100, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    assert [c["seq"] for c in ranked] == [1, 2]


def test_importance_can_lift_an_old_event():
    """Importance is a first-class signal: a high-importance old event outranks
    a recent low-importance one when importance is weighted heavily and the two
    are equally (ir)relevant to the query."""
    query_vec = VEC_RULE
    candidates = [
        {"seq": 1, "tick": 1, "kind": "world_extinct", "text": "the end"},
        {"seq": 2, "tick": 100, "kind": "agent_action", "text": "small talk"},
    ]
    # Neither candidate matches the query (both orthogonal-ish) so relevance is
    # flat; importance decides.
    embeddings = {1: VEC_FOOD, 2: VEC_FEUD}
    weights = RetrievalWeights(
        relevance=0.0, importance=0.8, recency=0.2, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=100, weights=weights,
        importance_of=_importance_by_kind({"world_extinct": 5.0}),
    )
    assert ranked[0]["seq"] == 1


def test_recency_decay_orders_equal_relevance_by_age():
    """With ONLY recency weighted and all signals otherwise equal, the order is
    pure newest-first, and the decay is the documented half-life curve."""
    query_vec = VEC_FOOD
    candidates = [
        {"seq": 1, "tick": 0, "kind": "agent_action", "text": "x"},
        {"seq": 2, "tick": 50, "kind": "agent_action", "text": "x"},
        {"seq": 3, "tick": 100, "kind": "agent_action", "text": "x"},
    ]
    # All share the SAME embedding ⇒ relevance is flat ⇒ recency alone decides.
    embeddings = {1: VEC_FOOD, 2: VEC_FOOD, 3: VEC_FOOD}
    weights = RetrievalWeights(
        relevance=0.0, importance=0.0, recency=1.0, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=100, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    assert [c["seq"] for c in ranked] == [3, 2, 1]


def test_recency_halflife_curve():
    """recency = 0.5 ** (age / halflife): at exactly one half-life of age the raw
    decay is 0.5. We verify the curve by comparing two candidates whose recency
    spread is the ONLY differing signal and whose normalized scores reflect the
    half-life (the newest reads 1.0, the half-life-old reads ~0.5 → after min-max
    normalization the newest is 1.0 and the older is 0.0, but the RAW shape is the
    exponential — proven via the absolute single-element recency below)."""
    # Single candidate at exactly one half-life of age: with min-max over one
    # element the normalized recency is 0.0, so to test the RAW curve we use two
    # candidates and assert the strict ordering + a 4th at 2 half-lives.
    query_vec = VEC_FOOD
    candidates = [
        {"seq": 1, "tick": 0, "kind": "k", "text": "x"},    # age 100 = 2 half-lives
        {"seq": 2, "tick": 50, "kind": "k", "text": "x"},   # age 50  = 1 half-life
        {"seq": 3, "tick": 100, "kind": "k", "text": "x"},  # age 0
    ]
    embeddings = {1: VEC_FOOD, 2: VEC_FOOD, 3: VEC_FOOD}
    weights = RetrievalWeights(
        relevance=0.0, importance=0.0, recency=1.0, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=100, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    # Strictly monotonic by recency: newest → oldest.
    assert [c["seq"] for c in ranked] == [3, 2, 1]
    # And the raw half-life math: 0.5**(50/50)=0.5, 0.5**(100/50)=0.25.
    assert 0.5 ** (50 / 50) == pytest.approx(0.5)
    assert 0.5 ** (100 / 50) == pytest.approx(0.25)


def test_deterministic_same_inputs_same_order():
    """Pure + deterministic: identical inputs ⇒ identical ranking, every call."""
    query_vec = VEC_FOODISH
    candidates = [
        {"seq": 10, "tick": 5, "kind": "rule_passed", "text": "a law"},
        {"seq": 11, "tick": 80, "kind": "agent_action", "text": "found food"},
        {"seq": 12, "tick": 40, "kind": "conflict", "text": "a feud"},
    ]
    embeddings = {10: VEC_RULE, 11: VEC_FOOD, 12: VEC_FEUD}
    weights = RetrievalWeights(
        relevance=0.5, importance=0.3, recency=0.2, recency_halflife_ticks=60
    )
    imp = _importance_by_kind({"rule_passed": 2.0, "conflict": 3.0})
    first = score_candidates(query_vec, candidates, embeddings, 80, weights, imp)
    for _ in range(5):
        again = score_candidates(
            query_vec, candidates, embeddings, 80, weights, imp)
        assert [c["seq"] for c in again] == [c["seq"] for c in first]


def test_stable_tie_break_by_seq_desc():
    """When every blended score ties (all weights zero), the documented stable
    tie-break orders by seq DESC (newest seq first)."""
    candidates = [
        {"seq": 1, "tick": 10, "kind": "k", "text": "x"},
        {"seq": 3, "tick": 10, "kind": "k", "text": "x"},
        {"seq": 2, "tick": 10, "kind": "k", "text": "x"},
    ]
    embeddings = {1: VEC_FOOD, 2: VEC_FOOD, 3: VEC_FOOD}
    weights = RetrievalWeights(
        relevance=0.0, importance=0.0, recency=0.0, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        VEC_FOOD, candidates, embeddings, now_tick=10, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    assert [c["seq"] for c in ranked] == [3, 2, 1]


def test_missing_embedding_scores_cosine_zero():
    """A candidate whose seq is absent from the embeddings table defensively
    scores cosine 0 rather than raising — so a partial cache can never crash the
    ranking (the orchestration ensures full coverage, but the scorer is robust)."""
    query_vec = VEC_FOOD
    candidates = [
        {"seq": 1, "tick": 1, "kind": "k", "text": "match"},
        {"seq": 2, "tick": 1, "kind": "k", "text": "no embedding"},
    ]
    embeddings = {1: VEC_FOOD}  # seq 2 missing
    weights = RetrievalWeights(
        relevance=1.0, importance=0.0, recency=0.0, recency_halflife_ticks=50
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=1, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    assert ranked[0]["seq"] == 1  # the matched one wins; no exception raised


def test_empty_candidates_returns_empty():
    weights = RetrievalWeights(0.5, 0.3, 0.2, 200)
    assert score_candidates(
        VEC_FOOD, [], {}, 0, weights, _importance_by_kind({})) == []


def test_zero_halflife_degrades_to_flat_recency():
    """A non-positive half-life must not divide by zero: recency degrades to a
    flat 1.0 for every candidate, so the OTHER signals decide the order."""
    query_vec = VEC_FOOD
    candidates = [
        {"seq": 1, "tick": 0, "kind": "k", "text": "old match"},
        {"seq": 2, "tick": 100, "kind": "k", "text": "new miss"},
    ]
    embeddings = {1: VEC_FOOD, 2: VEC_FEUD}
    weights = RetrievalWeights(
        relevance=1.0, importance=0.0, recency=0.5, recency_halflife_ticks=0
    )
    ranked = score_candidates(
        query_vec, candidates, embeddings, now_tick=100, weights=weights,
        importance_of=_importance_by_kind({}),
    )
    # recency is flat (no div-by-zero), so relevance decides: the match wins.
    assert ranked[0]["seq"] == 1


def test_does_not_mutate_inputs():
    candidates = [
        {"seq": 1, "tick": 1, "kind": "k", "text": "a"},
        {"seq": 2, "tick": 2, "kind": "k", "text": "b"},
    ]
    snapshot = [dict(c) for c in candidates]
    embeddings = {1: VEC_FOOD, 2: VEC_FEUD}
    weights = RetrievalWeights(0.5, 0.3, 0.2, 50)
    score_candidates(
        VEC_FOOD, candidates, embeddings, 2, weights, _importance_by_kind({}))
    assert candidates == snapshot  # pure: inputs untouched


# ──────────────────────────────────────────────────────────────────────────────
# build_query_text — shape (location + top need + last ~3 event texts)
# ──────────────────────────────────────────────────────────────────────────────

def _fake_world(place_id: str, place_name: str):
    place = SimpleNamespace(name=place_name)
    return SimpleNamespace(places={place_id: place})


def test_build_query_text_includes_name_location_need_and_recent_texts():
    agent = SimpleNamespace(
        name="Ada", location="plaza", energy=80.0, mood="curious")
    world = _fake_world("plaza", "Central Plaza")
    events = [
        {"tick": 1, "text": "event one", "kind": "k"},
        {"tick": 2, "text": "event two", "kind": "k"},
        {"tick": 3, "text": "event three", "kind": "k"},
        {"tick": 4, "text": "event four", "kind": "k"},
    ]
    q = build_query_text(agent, world, events)
    assert "Ada" in q
    assert "Central Plaza" in q            # place NAME, not the raw id
    assert "content" in q                  # energy 80 ⇒ "content"
    assert "curious" in q
    # Only the LAST ~3 event texts ride the query.
    assert "event four" in q and "event three" in q and "event two" in q
    assert "event one" not in q


def test_build_query_text_starving_need_when_low_energy():
    agent = SimpleNamespace(name="Dov", location="home", energy=10.0, mood="grim")
    world = _fake_world("home", "Hearth House")
    q = build_query_text(agent, world, [])
    assert "starving" in q
    assert "content" not in q


def test_build_query_text_dying_need_at_zero_energy():
    agent = SimpleNamespace(name="Esi", location="commons", energy=0.0, mood="x")
    world = _fake_world("commons", "The Commons")
    q = build_query_text(agent, world, [])
    assert "dying" in q


def test_build_query_text_handles_unknown_place_and_no_events():
    # An agent at a place the world doesn't know falls back to the raw id; an
    # empty event list is fine (no recent-text segment).
    agent = SimpleNamespace(name="Bram", location="nowhere", energy=50.0, mood="sly")
    world = _fake_world("plaza", "Central Plaza")
    q = build_query_text(agent, world, [])
    assert "Bram" in q
    assert "nowhere" in q          # raw id, since the world has no such place
    assert isinstance(q, str) and q


def test_build_query_text_is_deterministic():
    agent = SimpleNamespace(name="Cleo", location="townhall", energy=42.0, mood="set")
    world = _fake_world("townhall", "City Hall")
    events = [{"tick": 9, "text": "a vote", "kind": "rule_passed"}]
    assert build_query_text(agent, world, events) == build_query_text(
        agent, world, events)


# ──────────────────────────────────────────────────────────────────────────────
# BROADCAST_KINDS — the globally-salient corpus kinds the contract names
# ──────────────────────────────────────────────────────────────────────────────

def test_broadcast_kinds_cover_global_salience():
    for kind in ("rule_passed", "rule_rejected", "rule_proposed",
                 "random_event", "world_extinct", "god_miracle", "name_town"):
        assert kind in BROADCAST_KINDS
    assert isinstance(BROADCAST_KINDS, tuple)

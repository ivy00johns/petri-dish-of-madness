"""
EM-222 Lane A (infra) gate — the embedding seam + persistence.

Contract: contracts/em222-memory-retrieval.md §1 (embedding seam) + §2
(persistence). Design: docs/superpowers/specs/2026-06-19-em222-memory-retrieval-design.md.

Everything here is deterministic and offline: the MockProvider produces
network-free embeddings, and the repo runs against an in-memory SQLite DB
(conftest pins EM_DB_PATH=:memory:). No network, no real LLM, no embed proxy.

Three groups, mirroring the Lane A invariants:
  1. MOCK EMBED   — determinism + fixed dims + L2-norm; shared tokens raise cosine.
  2. ROUND-TRIP   — put/get event embeddings survives a float32 pack/unpack.
  3. CANDIDATES   — fetch_memory_candidates filters on actor OR target OR kind,
                    newest-first, bounded by limit.
"""
from __future__ import annotations

import math

import pytest

from petridish.config.loader import ModelProfile
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.base import ProviderError
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _new_run(repo: SQLiteRepository) -> int:
    return repo.start_run("{}")


# ──────────────────────────────────────────────────────────────────────────────
# Group 1: MockProvider.embed — determinism, dims, L2-norm, cosine signal
# ──────────────────────────────────────────────────────────────────────────────

async def test_mock_embed_deterministic_same_text_identical_vector():
    """Same text ⇒ byte-identical vector (no clock, no PYTHONHASHSEED drift)."""
    mock = MockProvider()
    [v1] = await mock.embed(["the market is profitable today"])
    [v2] = await mock.embed(["the market is profitable today"])
    assert v1 == v2

    # A second fresh instance must agree — determinism is content-only.
    [v3] = await MockProvider().embed(["the market is profitable today"])
    assert v1 == v3


async def test_mock_embed_default_dim_is_1024():
    """Default embed_dim is 1024 (bge-m3 width); ctor arg overrides it."""
    [v] = await MockProvider().embed(["hello world"])
    assert len(v) == 1024

    [v_small] = await MockProvider(embed_dim=64).embed(["hello world"])
    assert len(v_small) == 64


async def test_mock_embed_is_l2_normalized():
    """A non-empty text's vector has unit L2 norm; an empty text is zero-norm."""
    [v] = await MockProvider().embed(["foraging at the commons park"])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0, rel_tol=1e-6)

    [zero] = await MockProvider().embed([""])
    assert math.isclose(math.sqrt(sum(x * x for x in zero)), 0.0, abs_tol=1e-9)


async def test_mock_embed_shared_tokens_raise_cosine():
    """Texts sharing tokens have HIGHER cosine than unrelated texts."""
    mock = MockProvider()
    base, related, unrelated = await mock.embed([
        "the market is profitable",          # base
        "the market profits are good",       # shares market/the
        "willow pond ducks and reeds",       # disjoint vocabulary
    ])
    assert _cosine(base, related) > _cosine(base, unrelated)


async def test_mock_embed_order_and_count_match_inputs():
    """One vector per input, in order — a per-text passthrough."""
    texts = ["alpha", "beta", "gamma"]
    vecs = await MockProvider(embed_dim=32).embed(texts)
    assert len(vecs) == 3
    # Re-embedding one text alone matches its slot in the batch (no cross-talk).
    [solo] = await MockProvider(embed_dim=32).embed(["beta"])
    assert vecs[1] == solo


# ──────────────────────────────────────────────────────────────────────────────
# Group 1b: Router.embed routing + has_embeddings
# ──────────────────────────────────────────────────────────────────────────────

async def test_router_embed_routes_to_embed_profile_override():
    """Router.embed routes to the injected `embed` adapter; has_embeddings True."""
    embed_mock = MockProvider(embed_dim=128)
    profile = ModelProfile(name="embed", adapter="openai", model_id="bge-m3")
    router = Router(
        profiles=[profile],
        adapter_overrides={"embed": embed_mock},
        cache_enabled=False,
    )
    assert router.has_embeddings is True

    vecs = await router.embed(["a query about the plaza"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 128
    # Routed to the embed lane, not a chat lane: matches the mock directly.
    [direct] = await embed_mock.embed(["a query about the plaza"])
    assert vecs[0] == direct


async def test_router_without_embed_profile_has_no_embeddings_and_raises():
    """No `embed` profile ⇒ has_embeddings False and embed() raises clearly."""
    profile = ModelProfile(name="mock", adapter="mock", model_id="mock")
    router = Router(profiles=[profile], cache_enabled=False)
    assert router.has_embeddings is False
    with pytest.raises(ProviderError):
        await router.embed(["anything"])


# ──────────────────────────────────────────────────────────────────────────────
# Group 2: repo put/get float32 round-trip
# ──────────────────────────────────────────────────────────────────────────────

def test_event_embeddings_float32_round_trip():
    """put_event_embeddings → get_event_embeddings survives the float32 pack."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    # Seed events so the FK target (events.seq) exists for each embedding.
    seq_a = repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": "x"}, 1)
    seq_b = repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": "y"}, 2)

    vec_a = [0.5, -0.25, 0.125, 0.0]
    vec_b = [1.0, 2.0, 3.0, 4.0]
    repo.put_event_embeddings([
        (seq_a, "bge-m3", 4, vec_a),
        (seq_b, "bge-m3", 4, vec_b),
    ])

    got = repo.get_event_embeddings(run_id, [seq_a, seq_b])
    assert set(got.keys()) == {seq_a, seq_b}
    # float32 is exact for these dyadic-rational values.
    assert got[seq_a] == pytest.approx(vec_a, abs=1e-6)
    assert got[seq_b] == pytest.approx(vec_b, abs=1e-6)
    repo.close()


def test_get_event_embeddings_returns_only_cached_subset():
    """Misses are absent (not zero-filled); empty seqs ⇒ empty dict."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    seq_a = repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": "x"}, 1)
    seq_b = repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": "y"}, 2)
    repo.put_event_embeddings([(seq_a, "bge-m3", 2, [0.6, 0.8])])

    got = repo.get_event_embeddings(run_id, [seq_a, seq_b])
    assert seq_a in got and seq_b not in got
    assert repo.get_event_embeddings(run_id, []) == {}
    repo.close()


def test_put_event_embeddings_upserts_in_place():
    """Re-putting the same seq overwrites (embedded once, re-indexable)."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    seq = repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": "x"}, 1)
    repo.put_event_embeddings([(seq, "bge-m3", 3, [1.0, 0.0, 0.0])])
    repo.put_event_embeddings([(seq, "bge-m3", 3, [0.0, 1.0, 0.0])])
    got = repo.get_event_embeddings(run_id, [seq])
    assert got[seq] == pytest.approx([0.0, 1.0, 0.0], abs=1e-6)
    repo.close()


def test_put_event_embeddings_empty_is_noop():
    """Empty rows ⇒ no rows written, no error."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    repo.put_event_embeddings([])
    assert repo.get_event_embeddings(run_id, [1, 2, 3]) == {}
    repo.close()


# ──────────────────────────────────────────────────────────────────────────────
# Group 3: fetch_memory_candidates — actor OR target OR broadcast kind
# ──────────────────────────────────────────────────────────────────────────────

_BROADCAST = ("random_event", "world_extinct", "god_miracle")


def _seed_corpus(repo: SQLiteRepository, run_id: int) -> dict[str, int]:
    """A small mixed corpus; returns label -> seq for assertions."""
    seqs = {}
    seqs["own"] = repo.save_event(
        run_id, {"kind": "say", "actor_id": "ada", "text": "I will work"}, 1)
    seqs["targeted"] = repo.save_event(
        run_id, {"kind": "economy", "actor_id": "bram", "target_id": "ada",
                 "text": "bram gives ada credits"}, 2)
    seqs["broadcast"] = repo.save_event(
        run_id, {"kind": "random_event", "actor_id": None,
                 "text": "a meteor streaks overhead"}, 3)
    # Noise: neither involves ada, nor a broadcast kind.
    seqs["noise"] = repo.save_event(
        run_id, {"kind": "say", "actor_id": "cleo", "target_id": "dov",
                 "text": "cleo greets dov"}, 4)
    return seqs


def test_fetch_candidates_includes_actor_target_and_broadcast():
    """Returns the agent's own + targeted + broadcast events; excludes noise."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    seqs = _seed_corpus(repo, run_id)

    rows = repo.fetch_memory_candidates(run_id, "ada", _BROADCAST, limit=50)
    got_seqs = {r["seq"] for r in rows}
    assert seqs["own"] in got_seqs
    assert seqs["targeted"] in got_seqs
    assert seqs["broadcast"] in got_seqs
    assert seqs["noise"] not in got_seqs
    # Shape: {seq, tick, kind, text}; text never None.
    for r in rows:
        assert set(r.keys()) == {"seq", "tick", "kind", "text"}
        assert r["text"] is not None
    repo.close()


def test_fetch_candidates_newest_first_and_limit():
    """ORDER BY seq DESC, bounded by limit (the newest slice)."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    seqs = _seed_corpus(repo, run_id)

    rows = repo.fetch_memory_candidates(run_id, "ada", _BROADCAST, limit=50)
    ordered = [r["seq"] for r in rows]
    assert ordered == sorted(ordered, reverse=True)  # newest-first

    # limit=1 keeps only the highest-seq match (the broadcast, seq 3).
    top = repo.fetch_memory_candidates(run_id, "ada", _BROADCAST, limit=1)
    assert [r["seq"] for r in top] == [seqs["broadcast"]]
    repo.close()


def test_fetch_candidates_run_scoped():
    """Another run's events never leak into this run's candidates."""
    repo = SQLiteRepository(":memory:")
    run_a = _new_run(repo)
    run_b = _new_run(repo)
    repo.save_event(run_a, {"kind": "say", "actor_id": "ada", "text": "run A"}, 1)
    other = repo.save_event(run_b, {"kind": "say", "actor_id": "ada", "text": "run B"}, 1)

    rows = repo.fetch_memory_candidates(run_a, "ada", _BROADCAST, limit=50)
    assert other not in {r["seq"] for r in rows}
    assert all(r["text"] != "run B" for r in rows)
    repo.close()


def test_fetch_candidates_empty_broadcast_kinds_tolerated():
    """No broadcast kinds ⇒ the kind clause is dropped; actor/target still match."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    seqs = _seed_corpus(repo, run_id)

    rows = repo.fetch_memory_candidates(run_id, "ada", (), limit=50)
    got_seqs = {r["seq"] for r in rows}
    assert seqs["own"] in got_seqs
    assert seqs["targeted"] in got_seqs
    assert seqs["broadcast"] not in got_seqs  # no broadcast kinds given
    repo.close()


def test_fetch_candidates_text_may_be_empty_string():
    """A null event.text surfaces as '' (never None)."""
    repo = SQLiteRepository(":memory:")
    run_id = _new_run(repo)
    repo.save_event(run_id, {"kind": "say", "actor_id": "ada", "text": None}, 1)
    rows = repo.fetch_memory_candidates(run_id, "ada", _BROADCAST, limit=50)
    assert rows and rows[0]["text"] == ""
    repo.close()

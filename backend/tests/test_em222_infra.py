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
from petridish.providers.adapters import OpenAICompatibleAdapter
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


# ──────────────────────────────────────────────────────────────────────────────
# Group 4: OpenAICompatibleAdapter.embed — out-of-order `index` reorder + errors
#
# The proxy may return the embeddings `data` list in any order; the adapter
# MUST realign each vector to its INPUT text position via the `index` field
# (otherwise memory A gets memory B's embedding and the whole ranking is
# poisoned). We monkeypatch the HTTP seam (_post_with_retry) so no network is
# touched and we control the exact response body.
# ──────────────────────────────────────────────────────────────────────────────

def _embed_adapter() -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        profile="embed", base_url="http://localhost:3001/v1",
        api_key="", model_id="bge-m3", color="#777",
    )


def _patch_embed_response(monkeypatch, body: dict) -> None:
    """Replace the adapter HTTP seam so embed() consumes `body` directly."""
    async def _fake_post(client, url, headers, payload, profile):
        return body, None
    monkeypatch.setattr(
        "petridish.providers.adapters._post_with_retry", _fake_post
    )


async def test_embed_reorders_out_of_order_index_to_input_order(monkeypatch):
    """The proxy returns the `data` list SHUFFLED (index 2, 0, 1). The adapter
    sorts by `index`, so the returned vectors line up with the INPUT text order
    — vec[0] is text 0's embedding, etc. (A regression here silently swaps one
    memory's embedding for another's.)"""
    body = {
        "data": [
            {"index": 2, "embedding": [0.0, 0.0, 1.0]},   # belongs to text[2]
            {"index": 0, "embedding": [1.0, 0.0, 0.0]},   # belongs to text[0]
            {"index": 1, "embedding": [0.0, 1.0, 0.0]},   # belongs to text[1]
        ]
    }
    _patch_embed_response(monkeypatch, body)
    adapter = _embed_adapter()
    vecs = await adapter.embed(["text-zero", "text-one", "text-two"])
    assert vecs == [
        [1.0, 0.0, 0.0],   # text 0
        [0.0, 1.0, 0.0],   # text 1
        [0.0, 0.0, 1.0],   # text 2
    ]


async def test_embed_malformed_response_raises_provider_error(monkeypatch):
    """A response missing the `embedding` key (or `data` entirely) is a malformed
    completion — the adapter raises ProviderError (the documented behavior; the
    Router/retriever then degrade to blind recency rather than caching garbage)."""
    # Missing the `embedding` key inside a data item.
    _patch_embed_response(monkeypatch, {"data": [{"index": 0}]})
    adapter = _embed_adapter()
    with pytest.raises(ProviderError):
        await adapter.embed(["x"])

    # Missing the `data` list entirely (e.g. an error envelope leaked through).
    _patch_embed_response(monkeypatch, {"error": "bad request"})
    with pytest.raises(ProviderError):
        await adapter.embed(["x"])


async def test_embed_empty_data_returns_empty_list(monkeypatch):
    """An empty `data` list is well-formed (zero inputs / zero vectors) — it
    yields [], never an error: the shape is valid, just empty."""
    _patch_embed_response(monkeypatch, {"data": []})
    adapter = _embed_adapter()
    assert await adapter.embed([]) == []


# ──────────────────────────────────────────────────────────────────────────────
# Group 5: chat-lane EXCLUSION — the embed model must never serve chat.
#
# Two independent guarantees:
#   (a) build_world/casting (loader._pad_agents) never assigns an agent the
#       `embed` profile — rr_lanes excludes it. We force round-robin (every
#       padded agent must pick a lane, with `embed` the ONLY other non-mock
#       profile available) and assert no agent.profile == 'embed'.
#   (b) Router._pick_detour_candidate never returns `embed` even when it is the
#       only otherwise-"healthy" non-home lane (a sick home lane must NOT detour
#       chat traffic onto the embeddings model).
# ──────────────────────────────────────────────────────────────────────────────

def test_casting_never_assigns_embed_profile_to_an_agent():
    """_pad_agents round-robins padded agents across non-mock chat lanes; the
    `embed` profile is excluded from rr_lanes, so no agent is ever cast onto it
    — even when `embed` is the ONLY non-mock profile besides the chat lane."""
    from petridish.config.loader import _pad_agents, AgentConfig, PlaceConfig

    profiles = [
        ModelProfile(name="lane", adapter="openai", model_id="m"),
        ModelProfile(name="embed", adapter="openai", model_id="bge-m3"),
        ModelProfile(name="mock", adapter="mock", model_id="mock"),
    ]
    places = [PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    # One hand-listed agent + pad to 8 → 7 padded agents each pick a lane.
    seed = [AgentConfig(name="Ada", personality="", profile="lane",
                        location="plaza")]
    # Persona cards WITHOUT a usable suggested_profile force the round-robin
    # _pick_profile path (the one that consults rr_lanes).
    personas = [{"name": f"P{i}", "personality": "", "suggested_profile": ""}
                for i in range(10)]

    padded = _pad_agents(seed, agent_count=8, places=places,
                         profiles=profiles, personas=personas)
    assert len(padded) == 8
    assert all(a.profile != "embed" for a in padded), (
        "casting must never assign the embeddings lane to an agent"
    )
    # The round-robin actually used the chat lane (not just mock fallback),
    # proving `embed` was a candidate that got correctly skipped.
    assert any(a.profile == "lane" for a in padded)


def test_pick_detour_candidate_never_returns_embed_lane():
    """A sick home chat lane must never detour onto the embeddings model, even
    when `embed` is the only other available non-mock lane: _pick_detour_candidate
    skips `embed` explicitly (EM-222), returning None instead."""
    profiles = [
        # `home` is the (sick) chat lane; api_key_env satisfied so available().
        ModelProfile(name="home", adapter="openai", model_id="m",
                     api_key_env="EM222_FAKE_KEY"),
        ModelProfile(name="embed", adapter="openai", model_id="bge-m3",
                     api_key_env="EM222_FAKE_KEY"),
    ]
    import os
    os.environ["EM222_FAKE_KEY"] = "x"
    try:
        router = Router(
            profiles=profiles,
            adapter_overrides={"home": MockProvider(), "embed": MockProvider()},
            cache_enabled=False,
        )
        # Sicken the home lane: enough error demerits to cross sick_threshold.
        for _ in range(5):
            router.note_lane_error("home")
        assert router.lane_sick("home") is True
        # `embed` is the only other available non-mock lane — and it must be
        # excluded, so there is NO healthy candidate.
        assert router._pick_detour_candidate("home") is None, (
            "the embeddings lane must never be a chat detour substitute"
        )
    finally:
        os.environ.pop("EM222_FAKE_KEY", None)

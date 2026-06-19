"""
EM-222 — end-to-end integration tests for AgentRuntime._retrieve_memory (the
async orchestration the pure scorer + the infra seam plug into).

These tests build a REAL AgentRuntime + Router + SQLiteRepository wired exactly
as the live loop wires them (set_run_context(repo, run_id), events persisted via
the repo so fetch_memory_candidates returns them, plus the agent's in-memory
buffer seeded). The embed lane is a deterministic MockProvider (injected via
adapter_overrides={"embed": ...} OR the conftest's EM_EMBED_MOCK), so the whole
embed → fetch → score → merge pipeline runs offline and reproducibly.

They lock the verify-pass behaviors, NOT tautologies:
  1. MERGE de-dupes a recent in-memory tail event (no seq) that ALSO scores as a
     DB candidate (the HIGH bug: a recent event rendered twice). Tick-ascending.
  2. EMBED-ONCE: the 2nd retrieval of the same agent embeds no already-seen event
     (the misses are persisted on pass 1; pass 2 is a pure cache hit).
  3. FALLBACK: a raising embed lane ⇒ blind-recency slice, degraded flag set,
     warning logged ONCE.
  4. CIRCUIT-BREAKER: inside the cooldown embed is NOT called at all; once the
     tick advances past retry_tick, embed is attempted again (the probe).
  5. BACKGROUND tier ⇒ exactly recent_events[-window:], embed NEVER called.
  6. GATES: enabled=False / no repo / has_embeddings=False ⇒ blind, embed never
     called.
  7. DECISION TRACE: _perceived_context(memory_events=merged) reflects the
     RETRIEVED set, not the blind window.

Self-check:
  backend/.venv/bin/python -m pytest backend/tests/test_em222_integration.py -q

House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

import logging

import pytest

import petridish.engine.world  # noqa: F401  (settle package-init order first)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import ModelProfile, WorldParams, MemoryRetrievalParams
from petridish.agents.runtime import (
    AgentRuntime,
    _perceived_context,
    _effective_memory_window,
)
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.base import ProviderError
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures — a real World + AgentRuntime + Router(embed mock) + :memory: repo.
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        memory_window=12,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _world(tick: int = 100, *, memory_retrieval=None) -> World:
    places = [
        PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceState(id="market", name="Market Hall", x=697, y=303, kind="work"),
    ]
    params = _params()
    if memory_retrieval is not None:
        params.memory_retrieval = memory_retrieval
    agent = AgentState(
        id="ada", name="Ada", personality="Pragmatic engineer.",
        profile="lane", location="market", energy=80.0, credits=20,
        cadence_tier="protagonist", mood="curious",
    )
    world = World(params=params, places=places, agents=[agent])
    world.tick = tick
    return world


class SpyEmbedMock(MockProvider):
    """A MockProvider that COUNTS embed calls (the spy for embed-once + circuit
    breaker) and can be flipped to raise (the fallback spy). Each call records
    the batch length so we can prove which pass embedded what."""

    def __init__(self, *, embed_dim: int = 64):
        super().__init__(embed_dim=embed_dim)
        self.calls = 0
        self.batches: list[int] = []
        self.raise_now = False

    async def embed(self, texts):
        self.calls += 1
        self.batches.append(len(texts))
        if self.raise_now:
            raise ProviderError("embed", None, "embed lane down")
        return await super().embed(texts)


def _runtime(world: World, embed: SpyEmbedMock | None = None):
    """A wired (router, runtime, repo, embed-spy) tuple. The chat lane is a plain
    MockProvider; the embed lane is the SpyEmbedMock so we can count calls."""
    embed = embed or SpyEmbedMock()
    profiles = [
        ModelProfile(name="lane", adapter="openai", model_id="m", color="#fff"),
        ModelProfile(name="embed", adapter="openai", model_id="bge-m3"),
    ]
    router = Router(
        profiles=profiles,
        adapter_overrides={"lane": MockProvider(), "embed": embed},
        cache_enabled=False,
    )
    router.reassign("ada", "lane")
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    runtime = AgentRuntime(world, router)
    runtime.set_run_context(repo, run_id)
    return router, runtime, repo, run_id, embed


def _persist(repo: SQLiteRepository, run_id: int, event: dict, tick: int) -> int:
    """Persist one event so fetch_memory_candidates returns it; returns its seq."""
    return repo.save_event(run_id, event, tick)


# ──────────────────────────────────────────────────────────────────────────────
# 1. MERGE — no duplicate (tick, kind, text); tick-ascending
# ──────────────────────────────────────────────────────────────────────────────

async def test_merge_dedupes_recent_tail_that_is_also_a_db_candidate():
    """THE high bug: a recent in-memory tail event carries NO seq, while the SAME
    event also surfaces as a high-scoring DB candidate (with a seq). Seq-dedupe
    alone would render it TWICE — once from the scored top-K (with seq), once
    from the tail (no seq). The content key (tick, kind, text) collapses the
    overlap. The merged list must be deduped AND tick-ascending."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]

    # Persist DB candidates (these come back with seqs from fetch_memory_candidates).
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada",
                            "text": "the market is profitable"}, 10)
    overlap_seq = _persist(repo, run_id, {"kind": "say", "actor_id": "ada",
                                          "text": "I will work the forge today"}, 90)
    _persist(repo, run_id, {"kind": "economy", "actor_id": "ada",
                            "text": "earned credits at work"}, 50)

    # recent_events is the agent's in-memory tail — these carry NO seq. The LAST
    # one is byte-for-byte the same (tick, kind, text) as the persisted DB
    # candidate at tick 90 — that is the duplicate the bug rendered twice.
    recent_events = [
        {"tick": 88, "kind": "say", "text": "a quiet morning"},
        {"tick": 89, "kind": "say", "text": "off to the market"},
        {"tick": 90, "kind": "say", "text": "I will work the forge today"},
    ]

    merged = await runtime._retrieve_memory(agent, world, recent_events)

    # No (tick, kind, text) duplicate survives the merge.
    keys = [(e.get("tick"), e.get("kind"), e.get("text", "")) for e in merged]
    assert len(keys) == len(set(keys)), f"duplicate rendered: {keys}"
    # The overlapping event appears EXACTLY once.
    overlap_key = (90, "say", "I will work the forge today")
    assert keys.count(overlap_key) == 1

    # Tick-ascending (oldest → newest), matching the blind-recency block's order.
    ticks = [int(e.get("tick", 0) or 0) for e in merged]
    assert ticks == sorted(ticks), f"not tick-ascending: {ticks}"

    # The merge actually ran the retrieval path (embed was consulted, not blind).
    assert embed.calls >= 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. EMBED-ONCE — the 2nd retrieval re-embeds nothing already seen
# ──────────────────────────────────────────────────────────────────────────────

async def test_embed_once_second_pass_is_pure_cache_hit():
    """Pass 1 embeds the query + the candidate MISSES and PERSISTS them. Pass 2
    finds every candidate already cached, so it embeds only the query — never an
    already-seen event again (the embed-once invariant). Proven on the embed-call
    batch sizes AND on get_event_embeddings covering all candidate seqs."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]

    seqs = [
        _persist(repo, run_id, {"kind": "say", "actor_id": "ada",
                                "text": f"event number {i}"}, i)
        for i in range(1, 6)
    ]
    recent_events = [{"tick": 100, "kind": "say", "text": "now"}]

    # Pass 1: query (1 text) + the 5 candidate misses (1 batch of 5).
    await runtime._retrieve_memory(agent, world, recent_events)
    calls_after_first = embed.calls
    # The query embed + one miss-batch of all 5 candidates.
    assert 5 in embed.batches, "pass 1 must embed the candidate misses"
    # Every candidate seq is now cached.
    cached = repo.get_event_embeddings(run_id, seqs)
    assert set(cached.keys()) == set(seqs), "pass 1 must persist all candidate vecs"

    # Pass 2: NO new miss-batch — only the query is embedded again.
    embed.batches.clear()
    await runtime._retrieve_memory(agent, world, recent_events)
    assert embed.calls == calls_after_first + 1, (
        "pass 2 must add exactly one embed call (the query), no re-embed of seen events"
    )
    # The only batch on pass 2 is the single-text query — never a 5-batch re-embed.
    assert all(n == 1 for n in embed.batches), (
        f"pass 2 re-embedded already-seen events: batches={embed.batches}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 3. FALLBACK — embed raises ⇒ blind recency, degraded flag, warning logged once
# ──────────────────────────────────────────────────────────────────────────────

async def test_fallback_to_blind_recency_when_embed_raises(caplog):
    """A ProviderError out of router.embed must never kill the turn: the
    retriever returns the blind-recency window slice, flips
    _memory_retrieval_degraded True, and logs the degradation WARNING exactly
    once (per the contract: logged once, then degraded silently)."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]
    embed.raise_now = True

    _persist(repo, run_id, {"kind": "say", "actor_id": "ada", "text": "history"}, 5)
    # 14 recent events so the window slice (last 12) is observably a TAIL, not all.
    recent_events = [
        {"tick": t, "kind": "say", "text": f"recent {t}"} for t in range(1, 15)
    ]

    with caplog.at_level(logging.WARNING, logger="petridish.agents.runtime"):
        out = await runtime._retrieve_memory(agent, world, recent_events)
        # A SECOND failing retrieval must not log the warning again.
        out2 = await runtime._retrieve_memory(agent, world, recent_events)

    window = _effective_memory_window(agent, params=world.params)
    assert out == recent_events[-window:], "fallback must be the blind-recency slice"
    assert runtime._memory_retrieval_degraded is True
    # out2, still within cooldown, is also blind recency (see the circuit-breaker test).
    assert out2 == recent_events[-window:]

    degrade_logs = [
        r for r in caplog.records if "memory retrieval degraded" in r.getMessage()
    ]
    assert len(degrade_logs) == 1, (
        f"degradation must log exactly ONCE per run, got {len(degrade_logs)}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 4. CIRCUIT-BREAKER — cooldown skips embed entirely; a later tick probes again
# ──────────────────────────────────────────────────────────────────────────────

async def test_circuit_breaker_skips_embed_during_cooldown_then_probes():
    """After a failure arms the cooldown (_memory_retrieval_retry_tick >
    world.tick), the next call — still inside the cooldown — returns blind
    recency WITHOUT touching router.embed at all (the breaker is OPEN). Once
    world.tick advances past retry_tick, embed is attempted again (the recovery
    probe). 25-tick cooldown is the runtime constant."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada", "text": "history"}, 5)
    recent_events = [{"tick": 100, "kind": "say", "text": "now"}]

    # First call FAILS → arms the cooldown.
    embed.raise_now = True
    await runtime._retrieve_memory(agent, world, recent_events)
    assert runtime._memory_retrieval_degraded is True
    retry_tick = runtime._memory_retrieval_retry_tick
    assert retry_tick > world.tick, "a failure must arm a forward cooldown"

    # Heal the lane, but stay INSIDE the cooldown: the breaker is OPEN, so embed
    # must not be called at all (a down proxy can't stall every protagonist turn).
    embed.raise_now = False
    calls_before = embed.calls
    world.tick = retry_tick - 1
    out = await runtime._retrieve_memory(agent, world, recent_events)
    window = _effective_memory_window(agent, params=world.params)
    assert out == recent_events[-window:], "cooldown must return blind recency"
    assert embed.calls == calls_before, (
        "embed must NOT be called while the circuit breaker is open (cooldown)"
    )

    # Advance PAST the cooldown → the probe attempts embed again.
    world.tick = retry_tick + 1
    out2 = await runtime._retrieve_memory(agent, world, recent_events)
    assert embed.calls > calls_before, "past the cooldown, embed is probed again"
    # The healthy probe recovered the breaker.
    assert runtime._memory_retrieval_degraded is False
    assert out2  # a real retrieved set


# ──────────────────────────────────────────────────────────────────────────────
# 5. BACKGROUND tier — exactly the blind window; embed NEVER called
# ──────────────────────────────────────────────────────────────────────────────

async def test_background_tier_is_blind_recency_and_never_embeds():
    """A background-tier agent keeps its EM-161 blind-recency diet regardless of
    retrieval being enabled — returns exactly recent_events[-effective_window:]
    (the background window shrinks to 8) and router.embed is NEVER called."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]
    agent.cadence_tier = "background"
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada", "text": "history"}, 5)
    recent_events = [
        {"tick": t, "kind": "say", "text": f"recent {t}"} for t in range(1, 15)
    ]

    out = await runtime._retrieve_memory(agent, world, recent_events)

    window = _effective_memory_window(agent, params=world.params)
    assert window == 8, "background window shrinks to 8 (EM-161)"
    assert out == recent_events[-window:]
    assert embed.calls == 0, "background tier must never touch the embed lane"


# ──────────────────────────────────────────────────────────────────────────────
# 6. GATES — disabled / no repo / no embed profile ⇒ blind, embed never called
# ──────────────────────────────────────────────────────────────────────────────

async def test_disabled_retrieval_is_blind_and_never_embeds():
    """memory_retrieval.enabled=False ⇒ every tier keeps blind recency; embed
    is never called (byte-identical pre-EM-222)."""
    world = _world(tick=100, memory_retrieval=MemoryRetrievalParams(enabled=False))
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada", "text": "history"}, 5)
    recent_events = [{"tick": t, "kind": "say", "text": f"r{t}"} for t in range(1, 15)]

    out = await runtime._retrieve_memory(agent, world, recent_events)
    window = _effective_memory_window(agent, params=world.params)
    assert out == recent_events[-window:]
    assert embed.calls == 0


async def test_no_run_context_is_blind_and_never_embeds():
    """No set_run_context (repo/run_id None) ⇒ nothing to retrieve from; the
    retriever falls back to blind recency and never embeds — the run.py/api/test
    callers that wire no repo behave exactly as pre-EM-222."""
    world = _world(tick=100)
    _router, runtime, repo, _run_id, embed = _runtime(world)
    runtime.set_run_context(None, None)  # detach the repo/run handles
    agent = world.agents["ada"]
    recent_events = [{"tick": t, "kind": "say", "text": f"r{t}"} for t in range(1, 15)]

    out = await runtime._retrieve_memory(agent, world, recent_events)
    window = _effective_memory_window(agent, params=world.params)
    assert out == recent_events[-window:]
    assert embed.calls == 0


async def test_no_embed_profile_is_blind_and_never_embeds():
    """has_embeddings False (no `embed` profile on the router) ⇒ blind recency;
    the embed lane is never reached because there is none."""
    world = _world(tick=100)
    # A router with NO embed profile — has_embeddings is False.
    chat_mock = MockProvider()
    profiles = [ModelProfile(name="lane", adapter="openai", model_id="m")]
    router = Router(profiles=profiles,
                    adapter_overrides={"lane": chat_mock}, cache_enabled=False)
    router.reassign("ada", "lane")
    assert router.has_embeddings is False
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    runtime = AgentRuntime(world, router)
    runtime.set_run_context(repo, run_id)
    agent = world.agents["ada"]
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada", "text": "history"}, 5)
    recent_events = [{"tick": t, "kind": "say", "text": f"r{t}"} for t in range(1, 15)]

    out = await runtime._retrieve_memory(agent, world, recent_events)
    window = _effective_memory_window(agent, params=world.params)
    assert out == recent_events[-window:]


# ──────────────────────────────────────────────────────────────────────────────
# 7. DECISION TRACE — _perceived_context reflects the RETRIEVED set
# ──────────────────────────────────────────────────────────────────────────────

async def test_decision_trace_reflects_retrieved_memory_not_blind_window():
    """On the LLM path the trace memory must mirror the RETRIEVED set the model
    actually saw (merged top-K + tail), passed through _perceived_context's
    memory_events= param — NOT the blind-recency window. The retrieved set
    pulls in an OLD relevant event that the blind window (recent tail only) would
    never include, so the two traces are observably different."""
    world = _world(tick=100)
    _router, runtime, repo, run_id, embed = _runtime(world)
    agent = world.agents["ada"]

    # An OLD, query-relevant DB event the recent tail does NOT contain.
    _persist(repo, run_id, {"kind": "say", "actor_id": "ada",
                            "text": "the market is profitable and busy"}, 3)
    recent_events = [
        {"tick": t, "kind": "say", "text": f"recent chatter {t}"}
        for t in range(90, 101)
    ]

    merged = await runtime._retrieve_memory(agent, world, recent_events)

    # The retrieved set is NOT just the recent tail — it surfaced the old event.
    merged_texts = {e.get("text") for e in merged}
    assert "the market is profitable and busy" in merged_texts, (
        "retrieval should surface the old relevant event the tail lacks"
    )

    # The trace built from memory_events=merged mirrors merged EXACTLY.
    _perceived, memory = _perceived_context(
        agent, world, recent_events, world.params, memory_events=merged,
    )
    trace_texts = [m["text"] for m in memory["memories"]]
    assert trace_texts == [e.get("text", "") for e in merged]
    assert memory["window"] == len(merged)

    # The BLIND trace (no memory_events) is the tail-only window — and it does
    # NOT contain the old retrieved event, proving the two traces differ.
    _p2, blind = _perceived_context(agent, world, recent_events, world.params)
    blind_texts = [m["text"] for m in blind["memories"]]
    assert "the market is profitable and busy" not in blind_texts
    assert trace_texts != blind_texts

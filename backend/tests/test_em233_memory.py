"""EM-233 — Memory consolidation ("sleep") + soul entries (Wave M1).

Two additive cognition pieces on AgentState:

  (a) `soul: list[str]` — a tiny IMMUTABLE set of identity anchors (seeded from a
      persona at spawn if configured, capped at `soul_cap`). NEVER summarized,
      injected into EVERY prompt as a conditional block (empty list ⇒ no block ⇒
      the em161 lawful-citizen golden stays byte-identical).

  (b) Consolidation ("sleep") — at a beliefs count ceiling (`consolidate_at`) the
      world deterministically rolls the OLDEST beliefs into ONE digest line (a
      structured rollup, NO LLM in v1), replacing them. Hooked at the round
      boundary (`_start_new_round`); emits a `memory` event.

Invariants pinned here:
  * EM-155 — `soul` is additive: serialized in to_dict ONLY when non-empty and
    restored defensively (absent → [], capped at soul_cap). A soulless agent
    round-trips byte-identically to the pre-EM-233 dict.
  * em161 golden — the prompt gets NO soul block while `soul == []`, so the
    lawful-citizen golden stays byte-identical. The block appears only when set.
  * config-absent = default — a world.yaml WITHOUT a `memory` block consolidates
    at the dataclass defaults via the `_memory_param` accessor (no KeyError).
  * determinism — consolidation is pure: a fixed belief list always rolls up to
    the byte-identical digest; no random/clock.
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, MemoryParams, _parse_memory


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _world(agents, params=None):
    return World(params=params or _params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    from petridish.agents.runtime import _assemble_context
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── (a) soul: dataclass + defaults ───────────────────────────────────────────

def test_soul_defaults_empty():
    a = _agent()
    assert a.soul == []


def test_empty_soul_omitted_from_to_dict():
    a = _agent()
    d = a.to_dict()
    assert "soul" not in d


def test_soul_serialized_when_set():
    a = _agent(soul=["I never break a promise.", "The forge is my home."])
    d = a.to_dict()
    assert d["soul"] == ["I never break a promise.", "The forge is my home."]


def test_soul_snapshot_round_trip_byte_identical():
    p = _params()
    a = _agent(soul=["I protect the weak.", "I owe Bram my life."])
    w = _world([a], params=p)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=p)
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2["agents"], sort_keys=True) == \
           json.dumps(snap1["agents"], sort_keys=True)
    assert restored.agents["dot"].soul == ["I protect the weak.", "I owe Bram my life."]


def test_soulless_agent_dict_has_no_soul_key():
    # The byte-identical guarantee: a default agent's dict is unchanged.
    a = _agent()
    snap = _world([a]).to_snapshot()
    for ad in snap["agents"]:
        assert "soul" not in ad


def test_from_snapshot_absent_soul_restores_empty():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad.pop("soul", None)
    restored = World.from_snapshot(snap, params=p)
    assert restored.agents["dot"].soul == []


def test_from_snapshot_soul_capped_at_soul_cap():
    # A restored soul longer than soul_cap is truncated (defensive restore).
    p = _params()
    p.memory = MemoryParams(soul_cap=3)
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad["soul"] = ["a", "b", "c", "d", "e"]
    restored = World.from_snapshot(snap, params=p)
    assert restored.agents["dot"].soul == ["a", "b", "c"]


def test_from_snapshot_soul_garbage_coerced():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad["soul"] = "not a list"
    restored = World.from_snapshot(snap, params=p)
    assert restored.agents["dot"].soul == []


# ── (a) soul: seeding ────────────────────────────────────────────────────────

def test_seed_soul_caps_entries():
    p = _params()
    p.memory = MemoryParams(soul_cap=3)
    a = _agent()
    w = _world([a], params=p)
    w.seed_soul(a, ["one", "two", "three", "four", "five"])
    assert a.soul == ["one", "two", "three"]


def test_seed_soul_skips_blank_entries():
    a = _agent()
    w = _world([a])
    w.seed_soul(a, ["  ", "real anchor", ""])
    assert a.soul == ["real anchor"]


def test_seed_soul_is_immutable_after_first_seed():
    # Soul is seeded once; a second seed call is a no-op (immutability).
    a = _agent()
    w = _world([a])
    w.seed_soul(a, ["first identity"])
    w.seed_soul(a, ["a different identity"])
    assert a.soul == ["first identity"]


# ── (a) soul: prompt injection ───────────────────────────────────────────────

def test_prompt_has_no_soul_block_when_empty():
    a = _agent()  # no soul
    s = _sys(a, _world([a]))
    assert "WHO YOU ARE" not in s
    assert "soul" not in s.lower()


def test_prompt_injects_soul_block_when_set():
    a = _agent(soul=["I never abandon a friend.", "The harvest is sacred."])
    s = _sys(a, _world([a]))
    assert "I never abandon a friend." in s
    assert "The harvest is sacred." in s


# ── (b) consolidation: firing + determinism ──────────────────────────────────

def test_consolidate_noop_below_ceiling():
    p = _params()
    p.memory = MemoryParams(consolidate_at=10)
    a = _agent(beliefs=[f"belief {i}" for i in range(5)])
    w = _world([a], params=p)
    fired = w.consolidate_memory(a)
    assert fired is None
    assert len(a.beliefs) == 5  # untouched


def test_consolidate_fires_at_ceiling_and_replaces_oldest():
    p = _params()
    p.memory = MemoryParams(consolidate_at=8, consolidate_keep_recent=4)
    beliefs = [f"belief {i}" for i in range(10)]  # > 8
    a = _agent(beliefs=list(beliefs))
    w = _world([a], params=p)
    evt = w.consolidate_memory(a)
    assert evt is not None
    assert evt["kind"] == "memory"
    # the 4 most-recent beliefs survive verbatim, plus ONE digest line at front
    assert a.beliefs[-4:] == beliefs[-4:]
    assert len(a.beliefs) == 5  # 1 digest + 4 recent
    # the digest references how many were folded (10 - 4 = 6)
    assert "6" in a.beliefs[0]


def test_consolidation_is_deterministic():
    p = _params()
    p.memory = MemoryParams(consolidate_at=8, consolidate_keep_recent=4)
    beliefs = [f"belief {i}" for i in range(12)]
    a1 = _agent(id="a1", beliefs=list(beliefs))
    a2 = _agent(id="a2", beliefs=list(beliefs))
    w = _world([a1, a2], params=p)
    w.consolidate_memory(a1)
    w.consolidate_memory(a2)
    assert a1.beliefs == a2.beliefs  # byte-identical rollup


def test_repeated_consolidation_keeps_belief_list_bounded():
    p = _params()
    p.memory = MemoryParams(consolidate_at=8, consolidate_keep_recent=4)
    a = _agent(beliefs=[])
    w = _world([a], params=p)
    for i in range(40):
        a.beliefs.append(f"event {i}")
        w.consolidate_memory(a)
    # never grows unbounded past the ceiling
    assert len(a.beliefs) <= p.memory.consolidate_at


def test_digest_never_touches_soul():
    p = _params()
    p.memory = MemoryParams(consolidate_at=8, consolidate_keep_recent=4)
    a = _agent(soul=["My soul is fixed."], beliefs=[f"b{i}" for i in range(10)])
    w = _world([a], params=p)
    w.consolidate_memory(a)
    assert a.soul == ["My soul is fixed."]  # NEVER summarized


# ── (b) consolidation: round-boundary hook ───────────────────────────────────

def test_round_boundary_consolidates_and_parks_event():
    p = _params()
    p.memory = MemoryParams(consolidate_at=8, consolidate_keep_recent=4)
    a = _agent(beliefs=[f"belief {i}" for i in range(12)])
    w = _world([a], params=p)
    w.pending_spawn_events.clear()
    w._start_new_round()
    # consolidation ran for the over-ceiling agent at the round boundary
    assert len(a.beliefs) <= p.memory.consolidate_at
    kinds = [e.get("kind") for e in w.pending_spawn_events]
    assert "memory" in kinds


def test_round_boundary_no_event_when_under_ceiling():
    p = _params()
    p.memory = MemoryParams(consolidate_at=20)
    a = _agent(beliefs=[f"belief {i}" for i in range(5)])
    w = _world([a], params=p)
    w.pending_spawn_events.clear()
    w._start_new_round()
    assert [e for e in w.pending_spawn_events if e.get("kind") == "memory"] == []


# ── config parse ─────────────────────────────────────────────────────────────

def test_parse_memory_absent_returns_defaults():
    d = _parse_memory(None)
    assert isinstance(d, MemoryParams)
    assert d.consolidate_at == MemoryParams().consolidate_at
    assert d.soul_cap == MemoryParams().soul_cap


def test_parse_memory_reads_overrides_and_falls_back_per_key():
    d = _parse_memory({"consolidate_at": 30, "soul_cap": "garbage"})
    assert d.consolidate_at == 30
    assert d.soul_cap == MemoryParams().soul_cap


def test_memory_param_accessor_absent_block_is_noop_defaults():
    p = _params()
    p.memory = None  # simulate an absent block
    w = _world([_agent()], params=p)
    assert w._memory_param("consolidate_at", 20) == 20
    # consolidation with an absent block uses the engine literal defaults
    a = w.agents["dot"]
    a.beliefs = [f"b{i}" for i in range(50)]
    w.consolidate_memory(a)  # must not raise
    assert len(a.beliefs) <= MemoryParams().consolidate_at


def test_embedded_yaml_and_world_yaml_have_memory_block():
    # Both the embedded default and the on-disk world.yaml carry the block, with
    # values matching the dataclass (the R2 mirror invariant).
    from petridish.config.loader import EMBEDDED_WORLD_YAML
    import yaml
    embedded = yaml.safe_load(EMBEDDED_WORLD_YAML)
    assert "memory" in embedded["world"]
    d = MemoryParams()
    assert embedded["world"]["memory"]["consolidate_at"] == d.consolidate_at
    assert embedded["world"]["memory"]["soul_cap"] == d.soul_cap

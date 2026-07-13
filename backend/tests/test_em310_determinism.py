# backend/tests/test_em310_determinism.py
"""EM-310 — Chimera Twins determinism golden (EM-155).

The twin link is ADDITIVE agent state. With no twins (the default) a world is
BYTE-IDENTICAL to pre-EM-310: no `twin` key on any agent, and the snapshot
round-trips byte-identically. A world holding a LINKED twin pair ALSO round-
trips byte-identically (a fork/replay resumes the exact same pair), and a
second snapshot hop stays identical (fork-of-a-fork). Defensive restore drops a
malformed/garbage twin link without crashing or growing.
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _agent(aid: str, name: str, profile: str = "mock") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile=profile,
                      location="plaza", energy=80.0, credits=20)


def _world() -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=_params(), places=places,
                 agents=[_agent("vesper_a", "Vesper", "gemini"),
                         _agent("vesper_b", "Vesper II", "llama")])


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


def _agent_snap(snap: dict, aid: str) -> dict:
    return next(a for a in snap["agents"] if a["id"] == aid)


# ── default (no twins): inert + byte-identical ───────────────────────────────

def test_default_world_agents_have_no_twin_key():
    snap = _world().to_snapshot()
    for agent in snap["agents"]:
        assert "twin" not in agent, "an unlinked agent must carry no twin key"


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


# ── linked twin pair: byte-identical round-trip ──────────────────────────────

def _twinned_world() -> World:
    w = _world()
    assert w.link_twins("vesper_a", "vesper_b", group="Vesper") is True
    return w


def test_link_twins_cross_links_the_pair():
    w = _twinned_world()
    a, b = w.agents["vesper_a"], w.agents["vesper_b"]
    assert a.twin == {"group": "Vesper", "of": "vesper_b", "model": "gemini"}
    assert b.twin == {"group": "Vesper", "of": "vesper_a", "model": "llama"}


def test_twinned_world_emits_twin_key_only_on_the_pair():
    snap = _twinned_world().to_snapshot()
    assert _agent_snap(snap, "vesper_a")["twin"]["of"] == "vesper_b"
    assert _agent_snap(snap, "vesper_b")["twin"]["of"] == "vesper_a"


def test_twinned_world_round_trips_byte_identical():
    w = _twinned_world()
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_twinned_world_restores_the_link():
    w = _twinned_world()
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    a, b = restored.agents["vesper_a"], restored.agents["vesper_b"]
    assert a.twin == {"group": "Vesper", "of": "vesper_b", "model": "gemini"}
    assert b.twin == {"group": "Vesper", "of": "vesper_a", "model": "llama"}


def test_twin_survives_a_second_hop():
    # Fork-of-a-fork: two snapshot hops stay byte-identical (replay safety).
    w = _twinned_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


# ── link_twins guards ────────────────────────────────────────────────────────

def test_link_twins_rejects_missing_or_self():
    w = _world()
    assert w.link_twins("vesper_a", "nope", group="X") is False
    assert w.link_twins("vesper_a", "vesper_a", group="X") is False
    for agent in w.agents.values():
        assert agent.twin is None


# ── defensive restore (tampered links never crash / never grow) ──────────────

def test_restore_drops_garbage_twin_links():
    w = _twinned_world()
    snap = w.to_snapshot()
    # blank peer id, non-dict, missing 'of' — all fail-safe to None.
    _agent_snap(snap, "vesper_a")["twin"] = {"group": "Vesper", "of": "",
                                             "model": "gemini"}
    _agent_snap(snap, "vesper_b")["twin"] = "not-a-dict"
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["vesper_a"].twin is None
    assert restored.agents["vesper_b"].twin is None
    # the garbage twin key is absent again on re-emit (byte-stable / never grows).
    re_snap = restored.to_snapshot()
    assert "twin" not in _agent_snap(re_snap, "vesper_a")
    assert "twin" not in _agent_snap(re_snap, "vesper_b")


def test_restore_coerces_partial_twin_link():
    w = _world()
    snap = w.to_snapshot()
    # only `of` present — group/model default to "" (valid, minimal link).
    _agent_snap(snap, "vesper_a")["twin"] = {"of": "vesper_b"}
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["vesper_a"].twin == {
        "group": "", "of": "vesper_b", "model": ""}

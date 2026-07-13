"""EM-317 — The Prophecy Board.

The determinism golden (EM-155) + the feature behavior. Two guarantees carry the
byte-identity law:

  * Flag OFF (the default): a world is BYTE-IDENTICAL to pre-EM-317 — no
    `prophecies` snapshot key (even after a rejected post), no 🔮 omen prompt
    line, and resolve_prophecies() is a no-op. The default snapshot round-trips
    byte-identically.
  * Flag ON + a POPULATED board (pending + resolved prophecies, all three
    predicates, with baselines) round-trips byte-identically across two snapshot
    hops, so a fork/replay resolves every prophecy the exact same way.

Plus the enum-predicate resolution (deterministic projection over durable world
state — convictions / building status / relationship trust), the per-run cap,
the one-line perception hard-cap, and defensive restore.

CRITICAL: petridish.engine.world must be imported BEFORE petridish.agents.runtime
to avoid the engine↔agents circular import (the settlements-golden lesson).
"""
import copy
import json

import pytest

from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState, Building,
)
from petridish.agents.runtime import _assemble_context
from petridish.config.loader import (
    WorldParams, ProphecyBoardParams, _parse_prophecy_board,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

def _params(prophecy_board=None) -> WorldParams:
    p = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )
    if prophecy_board is not None:
        p.prophecy_board = prophecy_board
    return p


def _agent(aid: str, name: str) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location="market", energy=80.0, credits=20)


def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza",  name="Plaza",  x=0,  y=0,  kind="social",
                   district="civic"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work",
                   district="market"),
    ]


def _world(params=None) -> World:
    return World(params=params or _params(), places=_places(),
                 agents=[_agent("ada", "Ada"), _agent("bram", "Bram")])


def _on(**kw) -> World:
    return _world(_params(ProphecyBoardParams(enabled=True, **kw)))


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True, default=str)


def _sys(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── config: defaults OFF + defensive parse ────────────────────────────────────

def test_default_params_ship_disabled():
    assert ProphecyBoardParams().enabled is False
    assert _world().prophecy_board_enabled() is False


def test_parse_prophecy_board_defensive():
    assert _parse_prophecy_board(None) == ProphecyBoardParams()
    assert _parse_prophecy_board({}) == ProphecyBoardParams()
    assert _parse_prophecy_board("junk") == ProphecyBoardParams()
    assert _parse_prophecy_board({"enabled": True}).enabled is True
    assert _parse_prophecy_board({"enabled": 0}).enabled is False
    # numeric keys fall back individually + never crash
    got = _parse_prophecy_board({"enabled": True, "cap": "x", "horizon_min": 3,
                                 "horizon_max": 2, "reconcile_trust": -5})
    assert got.cap == ProphecyBoardParams().cap
    # horizon_min held ≤ horizon_max; reconcile_trust clamps to ≥ 1
    assert got.horizon_min <= got.horizon_max
    assert got.reconcile_trust == 1


# ── flag OFF ⇒ byte-identical world surface (the golden) ──────────────────────

def test_flag_off_snapshot_is_byte_identical_even_after_rejected_post():
    w = _world()
    baseline = _dumps(w.to_snapshot({}))
    # posting on a disabled board raises and mutates nothing
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agents_reconcile",
                               {"agent_a": "ada", "agent_b": "bram"}, 20)
    assert _dumps(w.to_snapshot({})) == baseline
    assert "prophecies" not in w.to_snapshot({})


def test_flag_off_resolution_is_a_noop():
    w = _world()
    assert w.resolve_prophecies() == []
    assert w.active_prophecy_omen() is None


def test_flag_off_prompt_is_byte_identical():
    w = _world()
    sys = _sys(w.agents["ada"], w)
    assert "OMEN" not in sys
    assert "🔮" not in sys


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot({})
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot({})) == _dumps(snap)


def test_flag_on_but_empty_board_is_still_byte_identical():
    # ON is not enough — a board with NO prophecy adds no key, no omen line.
    off = _dumps(_world().to_snapshot({}))
    on = _dumps(_on().to_snapshot({}))
    assert on == off
    assert "prophecies" not in _on().to_snapshot({})
    assert _sys(_on().agents["ada"], _on()) == _sys(_world().agents["ada"], _world())


# ── posting: the on-surface god event + the one omen line ─────────────────────

def test_post_emits_on_surface_god_event():
    w = _on()
    evt = w.post_prophecy_as_god("agents_reconcile",
                                 {"agent_a": "ada", "agent_b": "bram"}, 30)
    assert evt["kind"] == "prophecy_posted"
    assert evt["actor_type"] == "god"
    assert evt["turn_id"] is None
    assert evt["payload"]["deadline_tick"] == w.tick + 30
    assert evt["payload"]["predicate"] == "agents_reconcile"
    assert "🔮" in evt["text"]
    # the board now carries exactly one pending prophecy
    assert len(w.prophecies) == 1
    assert w.prophecies[0]["status"] == "pending"


def test_omen_injects_exactly_one_line_and_hard_caps_to_newest():
    w = _on()
    w.post_prophecy_as_god("agents_reconcile",
                           {"agent_a": "ada", "agent_b": "bram"}, 30)
    w.post_prophecy_as_god("building_falls", {"district": "market"}, 40)
    sys = _sys(w.agents["ada"], w)
    # exactly ONE omen block, and it is the NEWEST prophecy (building_falls)
    assert sys.count("=== 🔮 AN OMEN ===") == 1
    assert "a building will fall in the market quarter" in sys
    assert "make peace" not in sys           # the older omen is suppressed
    assert "ticks remain" in sys             # the live countdown rides the line


# ── enum-predicate resolution (deterministic state projection) ────────────────

def test_agent_convicted_fulfilled_then_idempotent():
    w = _on()
    w.post_prophecy_as_god("agent_convicted", {"agent_id": "bram"}, 50)
    assert w.resolve_prophecies() == []           # not yet convicted
    w.agents["bram"].crime_status = "jailed"      # a guilty verdict lands
    events = w.resolve_prophecies()
    assert len(events) == 1
    assert events[0]["kind"] == "prophecy_resolved"
    assert events[0]["payload"]["fulfilled"] is True
    assert "FULFILLED" in events[0]["text"]
    assert w.prophecies[0]["status"] == "fulfilled"
    assert w.resolve_prophecies() == []           # resolved once, never again


def test_agent_convicted_broken_when_countdown_elapses():
    w = _on()
    w.post_prophecy_as_god("agent_convicted", {"agent_id": "bram"}, 10)
    w.tick = 10                                    # deadline reached, still free
    events = w.resolve_prophecies()
    assert len(events) == 1
    assert events[0]["payload"]["fulfilled"] is False
    assert "BROKEN" in events[0]["text"]
    assert w.prophecies[0]["status"] == "broken"


def test_building_falls_is_baseline_aware():
    w = _on()
    # a building already destroyed in the district BEFORE the omen must not count
    w.buildings["old"] = Building(id="old", name="Old", location="market",
                                  kind="generic", status="destroyed")
    w.post_prophecy_as_god("building_falls", {"district": "market"}, 50)
    assert w.resolve_prophecies() == []            # the pre-existing ruin is baseline
    # a NEW building falls in the district ⇒ fulfilled
    w.buildings["mkt"] = Building(id="mkt", name="Stall", location="market",
                                  kind="generic", status="destroyed")
    events = w.resolve_prophecies()
    assert len(events) == 1 and events[0]["payload"]["fulfilled"] is True


def test_building_falls_wrong_district_does_not_fire():
    w = _on()
    w.post_prophecy_as_god("building_falls", {"district": "market"}, 5)
    # a building falls in a DIFFERENT district
    w.buildings["civ"] = Building(id="civ", name="Court", location="plaza",
                                  kind="generic", status="destroyed")
    w.tick = 5
    events = w.resolve_prophecies()
    assert events[0]["payload"]["fulfilled"] is False


def test_agents_reconcile_fulfilled_when_mutual_trust_crosses():
    w = _on(reconcile_trust=20)
    ada, bram = w.agents["ada"], w.agents["bram"]
    ada.relationships["bram"] = RelationshipState(type="rival", trust=-10)
    bram.relationships["ada"] = RelationshipState(type="rival", trust=-10)
    w.post_prophecy_as_god("agents_reconcile",
                           {"agent_a": "ada", "agent_b": "bram"}, 50)
    # one side warms but the other stays cold ⇒ NOT reconciled (weaker edge wins)
    ada.relationships["bram"].trust = 40
    assert w.resolve_prophecies() == []
    bram.relationships["ada"].trust = 25           # both sides now warm
    events = w.resolve_prophecies()
    assert len(events) == 1 and events[0]["payload"]["fulfilled"] is True


# ── validation (all ValueError → api 422) ─────────────────────────────────────

def test_post_rejects_bad_input():
    w = _on()
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("free_text_nonsense", {}, 20)      # unknown predicate
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agent_convicted", {"agent_id": "ghost"}, 20)
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("building_falls", {"district": "nowhere"}, 20)
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agents_reconcile",
                               {"agent_a": "ada", "agent_b": "ada"}, 20)   # same soul
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agent_convicted", {"agent_id": "ada"}, 1)  # horizon < min


def test_post_rejects_already_true_predicate():
    w = _on(reconcile_trust=20)
    ada, bram = w.agents["ada"], w.agents["bram"]
    ada.relationships["bram"] = RelationshipState(type="friend", trust=50)
    bram.relationships["ada"] = RelationshipState(type="friend", trust=50)
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agents_reconcile",
                               {"agent_a": "ada", "agent_b": "bram"}, 20)
    w.agents["bram"].crime_status = "jailed"
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("agent_convicted", {"agent_id": "bram"}, 20)


def test_per_run_cap_is_enforced():
    w = _on(cap=2)
    w.post_prophecy_as_god("building_falls", {"district": "market"}, 20)
    w.post_prophecy_as_god("building_falls", {"district": "civic"}, 20)
    with pytest.raises(ValueError):
        w.post_prophecy_as_god("building_falls", {"district": "market"}, 20)


# ── the determinism golden: a populated board round-trips byte-identical ───────

def _populated_world() -> World:
    w = _on(cap=8)
    w.tick = 3
    # a RESOLVED prophecy (fulfilled) stays on the board
    w.post_prophecy_as_god("agent_convicted", {"agent_id": "bram"}, 40)
    w.agents["bram"].crime_status = "jailed"
    w.resolve_prophecies()
    # a PENDING prophecy with a captured baseline. NOTE the explicit position:
    # a position-less building would be re-placed by the F1 derive-on-load
    # migration, muddying the round-trip — the prophecy state under test is what
    # we want to isolate, so the fixture building carries its own coordinates.
    w.buildings["old"] = Building(id="old", name="Old", location="market",
                                  kind="generic", status="destroyed",
                                  position=(1.5, -2.5))
    w.tick = 7
    w.post_prophecy_as_god("building_falls", {"district": "market"}, 30)
    # a PENDING reconcile prophecy
    ada, bram = w.agents["ada"], w.agents["bram"]
    ada.relationships["bram"] = RelationshipState(type="rival", trust=-5)
    bram.relationships["ada"] = RelationshipState(type="rival", trust=-5)
    w.post_prophecy_as_god("agents_reconcile",
                           {"agent_a": "ada", "agent_b": "bram"}, 60)
    return w


def test_populated_board_round_trips_byte_identical():
    w = _populated_world()
    snap1 = w.to_snapshot({})
    assert "prophecies" in snap1 and len(snap1["prophecies"]) == 3
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params(
        ProphecyBoardParams(enabled=True, cap=8)))
    assert _dumps(restored.to_snapshot({})) == _dumps(snap1)


def test_populated_board_survives_a_second_hop():
    # fork-of-a-fork: two snapshot hops stay byte-identical (replay safety).
    w = _populated_world()
    snap1 = w.to_snapshot({})
    p = _params(ProphecyBoardParams(enabled=True, cap=8))
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=p)
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot({})), params=p)
    assert _dumps(hop2.to_snapshot({})) == _dumps(snap1)


def test_resolution_continues_after_restore():
    # a pending prophecy restored from snapshot still resolves against the
    # baseline it carried (the building_falls baseline must survive the hop).
    w = _populated_world()
    p = _params(ProphecyBoardParams(enabled=True, cap=8))
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot({})), params=p)
    # a NEW building falls in the market district after the restore ⇒ fulfilled
    restored.buildings["mkt"] = Building(id="mkt", name="Stall", location="market",
                                         kind="generic", status="destroyed")
    events = restored.resolve_prophecies()
    kinds = [e["payload"]["predicate"] for e in events]
    assert "building_falls" in kinds
    fired = next(e for e in events if e["payload"]["predicate"] == "building_falls")
    assert fired["payload"]["fulfilled"] is True


# ── defensive restore (tampered snapshots never crash / never grow) ───────────

def test_restore_drops_garbage_prophecy_rows():
    w = _on()
    snap = w.to_snapshot({})
    snap["prophecies"] = [
        {"id": "prophecy-0-0", "predicate": "building_falls",
         "params": {"district": "market"}, "baseline": {"destroyed": 0},
         "tick": 0, "deadline_tick": 10, "status": "pending", "omen": "x",
         "resolved_tick": None},
        {"id": "", "predicate": "building_falls"},          # blank id → dropped
        {"id": "p2", "predicate": "not_a_predicate"},        # bad predicate → dropped
        "not-a-dict",                                        # non-dict → dropped
    ]
    restored = World.from_snapshot(snap, params=_params(
        ProphecyBoardParams(enabled=True)))
    assert [p["id"] for p in restored.prophecies] == ["prophecy-0-0"]
    assert restored.prophecies[0]["status"] == "pending"

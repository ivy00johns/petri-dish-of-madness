# backend/tests/test_em259_determinism.py
"""EM-258/EM-259 — the stage-C determinism golden (EM-155).

The combat/endgame layer must leave a war-disabled world BYTE-IDENTICAL
(muster/clash/siege fail closed with ZERO state change), a mid-combat war
world must round-trip byte-identically (casualties, exhaustion, war bands,
belligerent markers, a besieged building), and clash must be a pure
f(snapshot, city_seed): a world restored from a snapshot resolves the SAME
clash to the SAME outcome — the fork/replay guarantee the seeded contest
exists for.
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=20)


def _world(war: bool = True) -> World:
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    places = [
        PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance"),
        PlaceState(id="plaza", name="Plaza", x=1, y=0, kind="social"),
    ]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if war:
        w.params.war = {"enabled": True}
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram", "cyn"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── war disabled: the verbs leave no trace ────────────────────────────────────

def test_disabled_war_verbs_fail_closed_with_zero_state_change():
    w = _world(war=False)
    before = _dumps(w.to_snapshot())
    assert w.action_muster(w.agents["ada"])["kind"] == "parse_failure"
    assert w.action_clash(w.agents["ada"],
                          w.agents["dot"])["kind"] == "parse_failure"
    assert w.action_siege(w.agents["ada"], "bld_x")["kind"] == "parse_failure"
    w.advance_war()
    assert _dumps(w.to_snapshot()) == before
    assert w.pending_spawn_events == []


# ── mid-combat world: byte-identical round-trip ───────────────────────────────

def _mid_combat_world() -> World:
    """A war caught mid-swing: bands mustered, a casualty taken, exhaustion
    accrued, a besieged building, belligerent + exiled markers set."""
    w = _world()
    w.tick = 9
    war = w.open_war(FA, FB, "avenge the market")
    w.factions[FA]["war_band"] = ["ada", "bram"]
    w.factions[FB]["war_band"] = ["dot"]
    war.casualties = ["eli"]
    war.exhaustion = {FA: 12, FB: 47}
    w.grievances = {f"{FB}->{FA}": 55}
    w.agents["eli"].alive = False
    w.agents["ada"].crime_status = "belligerent"
    w.agents["bram"].crime_status = "belligerent"
    w.agents["dot"].crime_status = "belligerent"
    # position pinned explicitly: EM-268 derive-on-load would otherwise ADD
    # one on restore (ratified behavior, orthogonal to the war layer).
    w.buildings["bld_keep"] = Building(
        id="bld_keep", name="Dot's Keep", kind="generic", location="townhall",
        owner_id="dot", status="damaged", health=60, position=(1.0, 2.0))
    return w


def test_mid_combat_world_round_trips_byte_identical():
    w = _mid_combat_world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_mid_combat_world_survives_a_second_hop():
    w = _mid_combat_world()
    snap = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap)


# ── clash is a pure f(snapshot, city_seed) ────────────────────────────────────

def test_restored_world_resolves_the_same_clash():
    """Fork/replay: the SAME clash from a restored snapshot lands the SAME
    swing, winner, damage, and post-fight world — byte-identically."""
    w1 = _mid_combat_world()
    snap = w1.to_snapshot()
    w2 = World.from_snapshot(copy.deepcopy(snap), params=_params())
    w2.params.war = {"enabled": True}            # config rides beside the snap
    e1 = w1.action_clash(w1.agents["ada"], w1.agents["dot"])
    e2 = w2.action_clash(w2.agents["ada"], w2.agents["dot"])
    assert e1["payload"] == e2["payload"]
    assert _dumps(w1.to_snapshot()) == _dumps(w2.to_snapshot())


def test_advance_war_is_replay_stable():
    """The round boundary from the same snapshot parks the same events and
    lands the same world — including an auto-resolution settlement."""
    w1 = _mid_combat_world()
    war1 = next(iter(w1.wars.values()))
    war1.exhaustion = {FA: 12, FB: 99}           # FB collapses this round
    snap = w1.to_snapshot()
    w2 = World.from_snapshot(copy.deepcopy(snap), params=_params())
    w2.params.war = {"enabled": True}
    e1 = w1.advance_war()
    e2 = w2.advance_war()
    assert e1 == e2
    assert [e["kind"] for e in e1] == ["war_exhausted", "exiled"]
    assert _dumps(w1.to_snapshot()) == _dumps(w2.to_snapshot())

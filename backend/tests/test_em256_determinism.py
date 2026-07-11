# backend/tests/test_em256_determinism.py
"""EM-256/EM-257 — the war determinism golden (EM-155).

With war disabled (the default) a world is BYTE-IDENTICAL to pre-EM-256: no
wars/grievances snapshot keys, no faction war keys, crime bookkeeping and the
round boundary unchanged — and the default snapshot round-trips
byte-identically. A POPULATED war world (an active war with combat ledgers,
live grievances, a mustered war_band, an exiled loser leader, an open
declare_war proposal) also round-trips byte-identically, so a fork/replay
resumes the exact same war state — including a vote in flight.
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
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


def _world(war: bool = False) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    w = World(params=_params(), places=places,
              agents=[_a("ada"), _a("bram"), _a("dot"), _a("eli")])
    if war:
        w.params.war = {"enabled": True}
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── default world: inert + byte-identical (war disabled by default) ──────────

def test_default_world_snapshot_has_no_war_keys():
    snap = _world().to_snapshot()
    assert "wars" not in snap
    assert "grievances" not in snap
    for f in (snap.get("factions") or {}).values():
        assert "war_band" not in f and "treasury_pledged" not in f


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_disabled_war_stays_inert_through_crime_and_rounds():
    """The em161-golden guarantee at the behavior level: with war disabled, a
    cross-faction crime plus a round boundary leave the snapshot free of every
    war key (nothing accrues, nothing decays, nothing emits)."""
    w = _world()
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    w._register_crime(w.agents["dot"], "steal", "ada", 10)
    w.advance_war()
    snap = w.to_snapshot()
    assert "wars" not in snap and "grievances" not in snap
    kinds = [e["kind"] for e in w.pending_spawn_events]
    assert "grievance_accrued" not in kinds


# ── populated war world: byte-identical round-trip ────────────────────────────

def _war_world() -> World:
    w = _world(war=True)
    w.tick = 11
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram"], "war_band": ["ada"],
             "treasury_pledged": 10},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    war = w.open_war(FA, FB, "avenge the market")
    war.casualties = ["eli"]
    war.exhaustion = {FA: 15, FB: 40}
    w.grievances = {f"{FA}->{FB}": 30, f"{FB}->{FA}": 70}
    w.agents["dot"].crime_status = "exiled"            # the loser leader
    w.agents["dot"].notoriety = 10
    # A vote IN FLIGHT (the EM-257 lane mid-flight — payload must survive).
    ok, reason, rule = w.action_propose_rule(
        w.agents["dot"], "peace_treaty", "we yield", war_id=war.id,
        reparations=30)
    assert ok, reason
    w.action_vote(w.agents["dot"], rule.id, True)
    return w


def test_populated_war_world_round_trips_byte_identical():
    w = _war_world()
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_mid_flight_war_survives_a_second_hop():
    w = _war_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


def test_restored_war_world_resumes_the_same_vote():
    """A forked run finishes the SAME in-flight peace vote to the SAME
    outcome — the replay guarantee the payload-pinned electorate exists for."""
    w = _war_world()
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    restored.params.war = {"enabled": True}
    rule = next(r for r in restored.rules.values()
                if r.effect == "peace_treaty")
    ok, reason, status = restored.action_vote(
        restored.agents["eli"], rule.id, True)
    assert ok and status == "active"                  # 2/2 of FB ≥ ceil(0.7·2)
    war = next(iter(restored.wars.values()))
    assert war.status == "settled"
    assert restored.agents["dot"].crime_status == "exiled"

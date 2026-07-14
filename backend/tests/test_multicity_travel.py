"""EM-109/EM-110 — multi-city keystone (backend-core): a deterministic genesis
home city, the travel_to state machine (off-board → migrate → rejoin), a
traveling agent's byte-identical snapshot round-trip, and the free-scale
guarantee that in-transit agents take 0 scheduled turns. Settlements OFF stays
byte-identical to pre-EM-110.

Realized entirely on the EM-269 Settlement primitive — NO new cities table.
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import json
import math

from petridish.engine.world import (World, AgentState, PlaceState,
                                     TRAVEL_SPEED, TRAVEL_MIN_TICKS)
from petridish.config.loader import WorldParams, SettlementParams


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


# Two well-separated clusters: a plaza cluster (genesis, near world origin) and a
# far ridge cluster, so nearest-settlement partitioning is unambiguous.
_PLACES = [
    PlaceState(id="plaza",   name="Plaza",   x=500, y=500, kind="social"),
    PlaceState(id="well",    name="Well",    x=520, y=460, kind="social"),
    PlaceState(id="market",  name="Market",  x=560, y=520, kind="work"),
    PlaceState(id="ridge",   name="Ridge",   x=900, y=900, kind="social"),
    PlaceState(id="orchard", name="Orchard", x=860, y=880, kind="wild"),
    PlaceState(id="farm",    name="Farm",    x=900, y=820, kind="work"),
]

_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve"]


def _agents(n=5, at="plaza"):
    return [AgentState(id=chr(ord("a") + i), name=_NAMES[i], personality="",
                       profile="mock", location=at, energy=80.0, credits=20)
            for i in range(n)]


def _world(enabled=True, seed_genesis=True, n=5):
    w = World(params=_params(enabled),
              places=[copy.copy(p) for p in _PLACES],
              agents=_agents(n))
    if seed_genesis:
        w.seed_genesis_settlement()
    return w


def _found_second(w, agent_id="a", place="ridge", name="Ridgehold"):
    """Grow a 2nd settlement in the far cluster via the real founding verb."""
    w.agents[agent_id].location = place
    evt = w.action_found_settlement(w.agents[agent_id], name)
    assert evt["kind"] == "settlement_founded", evt
    return evt["payload"]["settlement_id"]


# ── (a) genesis settlement seeded deterministically when ON ────────────────────

def test_genesis_seeded_when_on():
    w = _world()
    assert len(w.settlements) == 1
    sid = next(iter(w.settlements))
    s = w.settlements[sid]
    assert sid.startswith("stl_")                    # seeded id, never uuid4
    assert s["founder_id"] == "genesis"
    # centered at the civic center (plaza → world origin), NOT logical coords
    assert s["center"] == (0.0, 0.0)
    # every seed agent homes to genesis + is a loose member (sorted-id order)
    assert s["members"] == ["a", "b", "c", "d", "e"]
    for a in w.agents.values():
        assert a.home_settlement_id == sid
        assert a.in_transit_to is None and a.transit_arrival_tick is None


def test_genesis_id_is_replay_stable_across_runs():
    a, b = _world(), _world()                        # same default city_seed
    assert list(a.settlements) == list(b.settlements)
    assert a.settlements == b.settlements
    assert {i: ag.home_settlement_id for i, ag in a.agents.items()} == \
           {i: ag.home_settlement_id for i, ag in b.agents.items()}


def test_genesis_is_idempotent():
    w = _world()
    before = json.dumps(w.to_snapshot({}).get("settlements"), sort_keys=True)
    w.seed_genesis_settlement()                      # a re-call is a no-op
    w.seed_genesis_settlement()
    assert len(w.settlements) == 1
    assert json.dumps(w.to_snapshot({}).get("settlements"), sort_keys=True) == before


def test_off_never_seeds_genesis_and_is_byte_identical():
    off = _world(enabled=False, seed_genesis=True)   # seed_genesis is a no-op OFF
    assert off.settlements == {}
    assert "settlements" not in off.to_snapshot({})
    for a in off.agents.values():
        assert a.home_settlement_id is None
    # an OFF agent dict never gains the new home/transit keys
    d = off.agents["a"].to_dict()
    assert "home_settlement_id" not in d
    assert "in_transit_to" not in d and "transit_arrival_tick" not in d


# ── travel_ticks formula ───────────────────────────────────────────────────────

def test_travel_ticks_formula():
    w = _world()
    genesis = w.agents["a"].home_settlement_id
    sid = _found_second(w)
    ca = w.settlements[genesis]["center"]
    cb = w.settlements[sid]["center"]
    dist = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
    expected = max(TRAVEL_MIN_TICKS, math.ceil(dist / TRAVEL_SPEED))
    assert w.travel_ticks(genesis, sid) == expected
    assert w.travel_ticks(genesis, sid) == w.travel_ticks(sid, genesis)  # symmetric
    # the floor holds for a same-point / adjacent trip
    assert w.travel_ticks(genesis, genesis) == TRAVEL_MIN_TICKS


# ── (b) travel_to: off-board (0 turns) until arrival, then migrate + rejoin ─────

def test_travel_departs_offboard_then_arrives_and_migrates():
    w = _world()
    genesis = w.agents["b"].home_settlement_id
    sid = _found_second(w, agent_id="a")             # 'a' now homes to Ridgehold
    traveler = w.agents["b"]                          # still in genesis

    evt = w.action_travel_to(traveler, sid)
    assert evt["kind"] == "travel_departed"
    assert evt["payload"]["from_settlement"] == genesis
    assert evt["payload"]["to_settlement"] == sid
    arrival = evt["payload"]["arrival_tick"]
    assert arrival == w.tick + w.travel_ticks(genesis, sid)
    # off-board: in_transit set, home NOT yet migrated
    assert traveler.in_transit_to == sid
    assert traveler.transit_arrival_tick == arrival
    assert traveler.home_settlement_id == genesis

    # EXCLUDED from scheduling while traveling — 0 LLM calls (a rate saving).
    assert "b" not in w._due_ids(w.round)
    round_ids = _collect_round(w)
    assert "b" not in round_ids
    assert set(round_ids) == {"a", "c", "d", "e"}    # never muted — the rest run

    # not yet arrived at tick = arrival-1 ⇒ still off-board after a round start
    w.tick = arrival - 1
    w._start_new_round()
    assert traveler.in_transit_to == sid
    assert "b" not in w._turn_order

    # at/after arrival ⇒ migrate at the next round boundary + rejoin
    w.tick = arrival
    w.pending_spawn_events.clear()
    w._start_new_round()
    assert traveler.in_transit_to is None
    assert traveler.transit_arrival_tick is None
    assert traveler.home_settlement_id == sid        # home MIGRATED
    assert w.settlement_of("b") == sid               # loose membership moved
    assert "b" not in (w.settlements[genesis]["members"])
    # landed at the target's anchor place (nearest place to its center)
    assert traveler.location in ("ridge", "orchard", "farm")
    assert "b" in w._due_ids(w.round)                # rejoined the rotation
    # a feed-safe travel_arrived event was parked for the loop to drain
    arrived = [e for e in w.pending_spawn_events if e["kind"] == "travel_arrived"]
    assert len(arrived) == 1
    assert arrived[0]["actor_id"] == "b"
    assert arrived[0]["payload"]["settlement"] == sid


def test_credits_and_skills_follow_the_traveler():
    w = _world()
    sid = _found_second(w, agent_id="a")
    b = w.agents["b"]
    b.credits = 77
    b.skills = {"masonry": 3}
    evt = w.action_travel_to(b, sid)
    w.tick = evt["payload"]["arrival_tick"]
    w._start_new_round()
    assert b.home_settlement_id == sid
    assert b.credits == 77 and b.skills == {"masonry": 3}   # rode WITH the agent


# ── travel_to rejections (all feed-safe, never a dead turn) ────────────────────

def test_travel_to_rejections():
    w = _world()
    sid = _found_second(w, agent_id="a")
    b = w.agents["b"]

    # unknown target
    r = w.action_travel_to(b, "Nowhere")
    assert r["kind"] == "parse_failure" and b.in_transit_to is None
    # already home
    r = w.action_travel_to(b, b.home_settlement_id)
    assert r["kind"] == "parse_failure" and b.in_transit_to is None
    # depart, then reject a second departure while traveling
    ok = w.action_travel_to(b, sid)
    assert ok["kind"] == "travel_departed"
    r = w.action_travel_to(b, sid)
    assert r["kind"] == "parse_failure"
    assert b.in_transit_to == sid                    # unchanged by the reject


def test_travel_to_resolves_name_case_insensitively():
    w = _world()
    _found_second(w, agent_id="a", name="Ridgehold")
    evt = w.action_travel_to(w.agents["b"], "  ridgehold ")
    assert evt["kind"] == "travel_departed"


def test_travel_to_disabled_is_feed_safe_noop():
    w = _world(enabled=False, seed_genesis=True)
    r = w.action_travel_to(w.agents["a"], "anything")
    assert r["kind"] == "parse_failure"
    assert w.agents["a"].in_transit_to is None


# ── (c) a traveling agent survives snapshot round-trip identically ─────────────

def test_traveling_agent_round_trips_byte_identical():
    w = _world()
    sid = _found_second(w, agent_id="a")
    w.action_travel_to(w.agents["b"], sid)
    assert w.agents["b"].in_transit_to == sid        # mid-trip

    snap = w.to_snapshot({})
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    again = restored.to_snapshot({})

    rb = restored.agents["b"]
    assert rb.in_transit_to == w.agents["b"].in_transit_to
    assert rb.transit_arrival_tick == w.agents["b"].transit_arrival_tick
    assert rb.home_settlement_id == w.agents["b"].home_settlement_id
    # the full agent-dict list round-trips byte-for-byte (raw dump, no sort)
    assert json.dumps(snap["agents"]) == json.dumps(again["agents"])
    assert json.dumps(snap["settlements"]) == json.dumps(again["settlements"])


def test_restored_traveler_still_offboard_then_arrives_on_schedule():
    w = _world()
    sid = _found_second(w, agent_id="a")
    evt = w.action_travel_to(w.agents["b"], sid)
    restored = World.from_snapshot(w.to_snapshot({}), params=_params())
    assert "b" not in restored._due_ids(restored.round)   # resumes off-board
    restored.tick = evt["payload"]["arrival_tick"]
    restored._start_new_round()
    assert restored.agents["b"].home_settlement_id == sid  # arrives on schedule


# ── settlements OFF: the scheduler is byte-identical (no in-transit path) ──────

def test_off_scheduler_due_set_unchanged():
    w = _world(enabled=False, seed_genesis=True)
    # no agent can ever be in transit OFF ⇒ the due set is the full living cast
    assert w._due_ids(w.round) == ["a", "b", "c", "d", "e"]
    for a in w.agents.values():
        assert w._in_transit(a) is False


# ── helpers ────────────────────────────────────────────────────────────────────

def _collect_round(world):
    """Drive next_agent through exactly one round; return the agent ids seen.

    Boost is OFF (default cost 0) so a round is exactly its due set."""
    world._round_start = True
    first = world.next_agent()
    if first is None:
        return []
    seen = [first.id]
    for _ in range(len(world._turn_order) - 1):
        a = world.next_agent()
        if a is None:
            break
        seen.append(a.id)
    return seen

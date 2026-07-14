"""QE — ADVERSARIAL verification of the multi-city keystone (EM-109/EM-110).

These are NOT re-runs of the implement agents' green tests; each one is written
to FAIL if a risky claim in contracts/settlement-travel.md is broken:

  1. Byte-identity when OFF — a settlements-disabled world must expose NONE of
     the new surface (no top-level `settlements` key, no home/transit agent-dict
     keys) and round-trip byte-for-byte.
  2. Flat prompt with N cities — pushed to 2 AND 3 settlements, a fixed agent's
     assembled prompt must not grow materially (bounded, never per-city
     multiplication).
  3. In-transit = truly off-board — an in-transit agent leaks into NO scheduling
     path (due set, turn order, boost slots), and its bought boost is not
     silently eaten while off-board.
  4. Nasty edges — same-city / double / unknown travel rejects; arrival EXACTLY
     at the boundary tick; found-then-immediately-travel; mid-transit snapshot
     round-trip; migration touches ONLY the 4 expected fields; same-seed runs
     produce identical ids + arrival ticks + post-arrival snapshots.

Realized entirely on the EM-269 Settlement primitive — NO new cities table.
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import json

from petridish.engine.world import (World, AgentState, PlaceState,
                                     RelationshipState)
from petridish.config.loader import WorldParams, SettlementParams
from petridish.agents.runtime import _assemble_context


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


# Three well-separated clusters so nearest-settlement partitioning and a THIRD
# foundable (unclaimed, >SETTLEMENT_R from the others) settlement are unambiguous.
#   plaza cluster → world origin (genesis)   ·  ridge cluster → +26,+26
#   cliff cluster → -26,-26 (the 3rd city's unclaimed ground)
_PLACES = [
    PlaceState(id="plaza",   name="Plaza",   x=500, y=500, kind="social"),
    PlaceState(id="well",    name="Well",    x=520, y=460, kind="social"),
    PlaceState(id="market",  name="Market",  x=560, y=520, kind="work"),
    PlaceState(id="ridge",   name="Ridge",   x=900, y=900, kind="social"),
    PlaceState(id="orchard", name="Orchard", x=860, y=880, kind="wild"),
    PlaceState(id="farm",    name="Farm",    x=900, y=820, kind="work"),
    PlaceState(id="cliff",   name="Cliff",   x=100, y=100, kind="social"),
    PlaceState(id="cove",    name="Cove",    x=140, y=120, kind="wild"),
]
_GENESIS_CLUSTER = {"plaza", "well", "market"}
_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve"]


def _world(enabled=True, seed_genesis=True, n=5, at="plaza"):
    w = World(params=_params(enabled),
              places=[copy.copy(p) for p in _PLACES],
              agents=[AgentState(id=chr(ord("a") + i), name=_NAMES[i],
                                 personality="", profile="mock", location=at,
                                 energy=80.0, credits=20) for i in range(n)])
    if seed_genesis:
        w.seed_genesis_settlement()
    return w


def _found(w, agent_id, place, name):
    w.agents[agent_id].location = place
    evt = w.action_found_settlement(w.agents[agent_id], name)
    assert evt["kind"] == "settlement_founded", evt
    return evt["payload"]["settlement_id"]


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _drive_round(world):
    """next_agent through exactly one round; return the ids seen (boost-aware)."""
    world._round_start = True
    seen = []
    guard = 0
    a = world.next_agent()
    if a is None:
        return seen
    seen.append(a.id)
    while guard < 64:
        guard += 1
        if world._turn_index >= len(world._turn_order):
            break
        a = world.next_agent()
        if a is None:
            break
        seen.append(a.id)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# 1. BYTE-IDENTITY WHEN OFF — the hard gate
# ══════════════════════════════════════════════════════════════════════════════

def test_off_snapshot_exposes_zero_new_surface():
    """A settlements-OFF world must carry NONE of the keystone's surface: no
    top-level `settlements` key, no home/transit keys on any agent dict, and the
    literal key names must not appear anywhere in the serialized snapshot."""
    off = _world(enabled=False)
    snap = off.to_snapshot({})
    assert "settlements" not in snap
    for a in off.agents.values():
        d = a.to_dict()
        assert "home_settlement_id" not in d
        assert "in_transit_to" not in d
        assert "transit_arrival_tick" not in d
        assert a.home_settlement_id is None
    blob = json.dumps(snap)
    for leaked in ("home_settlement_id", "in_transit_to", "transit_arrival_tick"):
        assert leaked not in blob, f"OFF snapshot leaked {leaked!r}"


def test_off_snapshot_round_trips_byte_identical():
    """OFF world: to_snapshot → from_snapshot → to_snapshot is byte-for-byte
    identical (the EM-155 keystone; a stray new key would diverge the re-dump)."""
    off = _world(enabled=False)
    snap = off.to_snapshot({})
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params(enabled=False))
    assert json.dumps(snap, sort_keys=True) == \
           json.dumps(restored.to_snapshot({}), sort_keys=True)


def test_on_settled_agent_dict_omits_the_transit_pair():
    """The only-when-non-default guarantee for the transit pair: an ON, settled,
    NON-traveling agent serializes home_settlement_id but NOT the transit keys —
    so a settled-but-still world's dicts don't grow the transit surface."""
    w = _world(enabled=True)
    d = w.agents["b"].to_dict()
    assert d["home_settlement_id"] == w.agents["b"].home_settlement_id
    assert "in_transit_to" not in d
    assert "transit_arrival_tick" not in d


# ══════════════════════════════════════════════════════════════════════════════
# 2. FLAT PROMPT with 1 → 2 → 3 CITIES (the free-scale keystone)
# ══════════════════════════════════════════════════════════════════════════════

def test_prompt_stays_flat_across_1_2_3_cities():
    """A fixed genesis agent's assembled system prompt must NOT balloon as cities
    grow: with per-city scoping it perceives only its own town + a bounded roster
    line, so 3 cities ≈ 1 city. A non-scoped build would append each new town's
    places (a per-city multiplication) and blow these bounds."""
    w = _world()
    one = _sys(w.agents["b"], w)                    # 1 city: b sees the full town
    assert _move_places(one) == set(w.places)        # no scoping at len==1

    _found(w, "a", "ridge", "Ridgehold")            # 2 cities
    two = _sys(w.agents["b"], w)                     # b now scoped to genesis

    _found(w, "c", "cliff", "Craghold")             # 3 cities
    three = _sys(w.agents["b"], w)                    # still scoped to genesis

    # THE TEETH: per-city scoping partitions b to EXACTLY its own city's places
    # and HIDES every other city's places — at 3 cities genesis keeps only its
    # own cluster (a broken/absent scoping would leave b seeing all 8 places).
    assert _move_places(three) == _GENESIS_CLUSTER
    assert not (_move_places(three) & {"ridge", "orchard", "farm", "cliff", "cove"})

    # And the total prompt does NOT balloon as cities grow — it stays in a tight
    # band around the 1-city size (measured ~78 chars across 1→3 cities), never a
    # per-city multiplication of the whole town.
    sizes = [len(one), len(two), len(three)]
    assert len(three) <= len(one) + 300
    assert max(sizes) - min(sizes) <= 250


def _move_places(sys_text):
    for line in sys_text.splitlines():
        if "move_to (place)" in line:
            tail = line.split("go to one of:", 1)[1]
            return {p.strip() for p in tail.split(",") if p.strip()}
    return set()


# ══════════════════════════════════════════════════════════════════════════════
# 3. IN-TRANSIT = TRULY OFF-BOARD — no scheduling leak, boost survives
# ══════════════════════════════════════════════════════════════════════════════

def test_in_transit_leaks_into_no_scheduling_path_even_with_a_boost():
    """An off-board traveler must be absent from EVERY scheduling path — the due
    set, the rebuilt turn order, and the boost-slot injector — and its bought
    boost must NOT be silently consumed while off-board (it waits, durable)."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    b = w.agents["b"]
    evt = w.action_travel_to(b, sid)
    arrival = evt["payload"]["arrival_tick"]
    b.boosted_turns = 2                              # a parked boost, mid-transit

    # (i) due set + turn order exclude it
    assert "b" not in w._due_ids(w.round)
    w._start_new_round()
    assert "b" not in w._turn_order

    # (ii) drive several full rounds off-board — never scheduled, boost intact,
    #      the boost injector never smuggles it back in.
    for _ in range(3):
        assert "b" not in _drive_round(w)
        assert b.in_transit_to == sid
        assert b.boosted_turns == 2                  # NOT eaten while off-board
        assert w.tick < arrival                       # (still traveling)

    # (iii) at arrival it migrates and rejoins — with its boost still in hand.
    w.tick = arrival
    w._start_new_round()
    assert b.in_transit_to is None
    assert b.home_settlement_id == sid
    assert "b" in w._due_ids(w.round)
    assert b.boosted_turns == 2                       # boost preserved across travel


# ══════════════════════════════════════════════════════════════════════════════
# 4. NASTY EDGES
# ══════════════════════════════════════════════════════════════════════════════

def test_reject_same_double_and_unknown_are_all_feed_safe():
    """Every rejection returns a feed-safe failure (never a crash / dead turn) and
    leaves transit state untouched."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    b = w.agents["b"]

    # unknown target — no such settlement (must not raise, must not set transit)
    r = w.action_travel_to(b, "Atlantis")
    assert r["kind"] == "parse_failure"
    assert isinstance(r.get("text"), str) and r["text"]
    assert b.in_transit_to is None

    # same city — b's own home is rejected
    r = w.action_travel_to(b, b.home_settlement_id)
    assert r["kind"] == "parse_failure"
    assert b.in_transit_to is None

    # depart, then a SECOND departure while traveling is rejected (state unchanged)
    ok = w.action_travel_to(b, sid)
    assert ok["kind"] == "travel_departed"
    keep = (b.in_transit_to, b.transit_arrival_tick)
    r = w.action_travel_to(b, sid)
    assert r["kind"] == "parse_failure"
    assert (b.in_transit_to, b.transit_arrival_tick) == keep


def test_arrival_is_exactly_at_the_boundary_tick_never_early():
    """Off-board through arrival-1, migrates AT arrival — the `tick < arrival`
    boundary is inclusive at arrival and not a tick early."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    b = w.agents["b"]
    arrival = w.action_travel_to(b, sid)["payload"]["arrival_tick"]

    w.tick = arrival - 1
    w._start_new_round()
    assert b.in_transit_to == sid                     # NOT arrived one tick early
    assert b.home_settlement_id != sid

    w.tick = arrival
    w._start_new_round()
    assert b.in_transit_to is None                    # arrived exactly on the tick
    assert b.home_settlement_id == sid


def test_found_then_immediately_travel_back_home():
    """A founder adopts its new city as home; it may immediately travel BACK to
    genesis and arrive there — the round-trip of the whole loop in one test."""
    w = _world()
    genesis = w.agents["a"].home_settlement_id
    ridge = _found(w, "a", "ridge", "Ridgehold")
    a = w.agents["a"]
    assert a.home_settlement_id == ridge              # founding migrated home

    evt = w.action_travel_to(a, genesis)              # immediately head back
    assert evt["kind"] == "travel_departed"
    assert evt["payload"]["from_settlement"] == ridge
    assert evt["payload"]["to_settlement"] == genesis
    w.tick = evt["payload"]["arrival_tick"]
    w._start_new_round()
    assert a.home_settlement_id == genesis            # home again
    assert w.settlement_of("a") == genesis            # membership moved back


def test_mid_transit_snapshot_round_trips_then_arrives_on_schedule():
    """Snapshot taken MID-transit → from_snapshot → the agent is still in_transit
    with the IDENTICAL arrival tick, still off-board, and then arrives + migrates
    + moves membership exactly on schedule."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    evt = w.action_travel_to(w.agents["b"], sid)
    arrival = evt["payload"]["arrival_tick"]

    snap = w.to_snapshot({})
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    rb = restored.agents["b"]
    assert rb.in_transit_to == sid                    # resumes mid-trip
    assert rb.transit_arrival_tick == arrival         # identical arrival tick
    assert rb.home_settlement_id == w.agents["b"].home_settlement_id
    assert "b" not in restored._due_ids(restored.round)   # still off-board
    # the agent dicts round-trip byte-for-byte through the restore
    assert json.dumps(snap["agents"]) == \
           json.dumps(restored.to_snapshot({})["agents"])

    restored.tick = arrival
    restored._start_new_round()
    assert rb.in_transit_to is None
    assert rb.home_settlement_id == sid
    assert restored.settlement_of("b") == sid         # membership migrated
    assert "b" not in restored.settlements[
        w.agents["b"].home_settlement_id]["members"] or \
        w.agents["b"].home_settlement_id == sid


def test_migration_touches_only_home_location_and_transit():
    """Migration carries credits/skills/memories/relationships WITH the agent by
    touching ONLY home_settlement_id + location + the transit pair — every other
    serialized field is byte-identical before vs after arrival."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    b = w.agents["b"]
    b.credits = 77
    b.skills = {"masonry": 3, "trade": 1}
    b.soul = ["I recall the plaza well", "the market smelled of bread"]
    b.beliefs = ["the ridge is cold"]
    b.contributions = {"townhall": 5}
    b.held_memes = ["mem_abc123"]
    b.relationships = {"a": RelationshipState(type="ally", trust=50, interactions=4)}

    _MUT = {"location", "home_settlement_id", "in_transit_to", "transit_arrival_tick"}
    before = copy.deepcopy({k: v for k, v in b.to_dict().items() if k not in _MUT})

    ev = w.action_travel_to(b, sid)
    w.tick = ev["payload"]["arrival_tick"]
    w._start_new_round()
    assert b.home_settlement_id == sid                # (arrived)

    after = {k: v for k, v in b.to_dict().items() if k not in _MUT}
    assert after == before, "migration mutated a non-travel field"
    # spot-check the migration note's named carriers explicitly
    assert b.credits == 77
    assert b.skills == {"masonry": 3, "trade": 1}
    assert b.soul == ["I recall the plaza well", "the market smelled of bread"]
    assert b.relationships["a"].trust == 50


def test_same_seed_runs_are_identical_ids_arrivals_and_snapshots():
    """Determinism: two same-seed runs mint identical settlement ids, compute the
    identical arrival tick, and produce byte-identical post-arrival snapshots —
    NO uuid4/random/clock on the tick path."""
    def _run():
        w = _world()
        sid = _found(w, "a", "ridge", "Ridgehold")
        ev = w.action_travel_to(w.agents["b"], sid)
        w.tick = ev["payload"]["arrival_tick"]
        w._start_new_round()
        return w, sid, ev["payload"]["arrival_tick"]

    w1, sid1, arr1 = _run()
    w2, sid2, arr2 = _run()
    assert list(w1.settlements) == list(w2.settlements)
    assert sid1 == sid2
    assert arr1 == arr2
    assert json.dumps(w1.to_snapshot({}), sort_keys=True) == \
           json.dumps(w2.to_snapshot({}), sort_keys=True)


def test_travel_arrived_event_is_feed_safe_and_actor_stamped():
    """The parked travel_arrived carries actor_id + settlement + a human text so
    the feed renders it as a normal movement card (never an error)."""
    w = _world()
    sid = _found(w, "a", "ridge", "Ridgehold")
    ev = w.action_travel_to(w.agents["b"], sid)
    w.tick = ev["payload"]["arrival_tick"]
    w.pending_spawn_events.clear()
    w._start_new_round()
    arrived = [e for e in w.pending_spawn_events if e["kind"] == "travel_arrived"]
    assert len(arrived) == 1
    e = arrived[0]
    assert e["actor_id"] == "b"
    assert e["payload"]["settlement"] == sid
    assert isinstance(e.get("text"), str) and e["text"]
    assert e["kind"] != "parse_failure"               # NOT an error card

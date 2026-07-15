"""EM-269 (F2) — settlement-anchored free placement: a member's build clusters
at their settlement's center; a non-member anchors to the city origin EXACTLY
as F1 shipped; building near a settlement associates the builder (loosely)."""
import copy
import uuid as _uuidlib

# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import petridish.engine.world as world_mod
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.placement import (SETTLEMENT_R, place_all, place_one_anchored)
from petridish.config.loader import WorldParams, SettlementParams
import petridish.agents.runtime as rt


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


def _world(enabled=True):
    return World(
        params=_params(enabled),
        places=[
            PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
            PlaceState(id="ridge", name="Ridge", x=900, y=900, kind="social"),
        ],
        agents=[
            AgentState(id="a", name="Ann", personality="", profile="mock",
                       location="ridge", energy=80.0, credits=20),
            AgentState(id="b", name="Bob", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20),
        ])


def _dist(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _det_uuid(start=0):
    """Deterministic uuid4 stand-in (top-32-bit counter ⇒ distinct str[:8]).
    `start` offsets the counter so a RESET stream can mint ids disjoint from
    the ones already minted — a reset that re-mints bld_00000001 would silently
    OVERWRITE that building in world.buildings and turn any 'newest build'
    assertion vacuous (it would inspect a pre-fork building instead)."""
    counter = {"n": start}

    def _f():
        counter["n"] += 1
        return _uuidlib.UUID(int=counter["n"] << 96)

    return _f


def _positions(w):
    return {bid: b.position for bid, b in sorted(w.buildings.items())}


def _newest(w):
    return max(w.buildings.values(), key=lambda b: (b.created_tick, b.id))


# ── member builds anchor to the settlement center ─────────────────────────────

def test_member_build_lands_at_the_settlement(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    evt = w.action_found_settlement(w.agents["a"], "Outpost")
    center = tuple(evt["payload"]["center"])         # ridge ≈ (26.4, 26.4)
    w.action_propose_project(w.agents["a"], name="Hall", kind="workshop",
                             funds_required=0)
    b = next(iter(w.buildings.values()))
    assert b.position is not None
    assert _dist(b.position, center) <= SETTLEMENT_R  # the hamlet's first hut
    # and it matches the pure anchored fn over the same inputs (determinism)
    assert b.position == place_one_anchored(
        b, list(w.buildings.values()), center, w.city_seed)


def test_settlement_grows_around_its_seed(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    evt = w.action_found_settlement(w.agents["a"], "Outpost")
    center = tuple(evt["payload"]["center"])
    for i in range(5):
        w.action_propose_project(w.agents["a"], name=f"Hut {i}", kind="home",
                                 funds_required=0)
    positions = [b.position for b in w.buildings.values()]
    assert all(p is not None for p in positions)
    # every build clusters at the outpost, none drifts back to the origin
    assert all(_dist(p, center) <= SETTLEMENT_R * 1.5 for p in positions)
    assert all(_dist(p, (0.0, 0.0)) > SETTLEMENT_R for p in positions)


def test_fork_continuation_byte_identical_anchored(monkeypatch):
    """EM-155 fork == continuous, ANCHORED path (mirrors
    test_free_placement_determinism.py::test_fork_continuation_byte_identical):
    a settlement member's build that continues after a snapshot round-trip lands
    byte-identically to the same build on the unforked world — settlement ids,
    centers and loose membership all survive the fork verbatim, so
    place_one_anchored sees identical inputs on both sides. Reset the uuid
    stream before each continuation so both mint the SAME next id ('same
    subsequent input'); resetting AFTER from_snapshot makes any construction
    uuid consumption irrelevant. The resets use start=100 so the continuation
    id (bld_00000065) is DISJOINT from the pre-fork ids (bld_00000001..03) —
    a start=0 reset would re-mint bld_00000001, overwrite Hut 0, and leave
    _newest pointing at a pre-fork building (assertions proven vacuous: a
    simulated lost-center restore bug sailed through start=0 and only the
    start=100 form caught it)."""
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid())
    w1 = _world()
    evt = w1.action_found_settlement(w1.agents["a"], "Outpost")
    center = tuple(evt["payload"]["center"])
    for i in range(3):
        w1.action_propose_project(w1.agents["a"], name=f"Hut {i}", kind="home",
                                  funds_required=0)
    w2 = World.from_snapshot(copy.deepcopy(w1.to_snapshot({})), params=_params())
    assert _positions(w2) == _positions(w1)            # restore is exact
    assert w2.settlement_of("a") is not None           # membership survived

    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid(start=100))  # w1's next build → bld_00000065
    w1.action_propose_project(w1.agents["a"], name="Next Hut", kind="home",
                              funds_required=0)
    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid(start=100))  # w2's next build → SAME id
    w2.action_propose_project(w2.agents["a"], name="Next Hut", kind="home",
                              funds_required=0)
    n1, n2 = _newest(w1), _newest(w2)
    assert n1.id == n2.id == "bld_00000065"            # same subsequent input,
    assert n1.name == "Next Hut"                       # and truly the NEW build
    assert n1.position is not None
    assert n1.position == n2.position                  # fork+resume == continuous
    # and both landed at the outpost — proof the ANCHORED path (not the F1
    # origin fallback) is what replayed byte-identically.
    assert _dist(n1.position, center) <= SETTLEMENT_R * 1.5


# ── non-members fall back to the F1 city-origin anchor byte-identically ───────

def test_non_member_build_anchors_to_city_origin(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    w.action_found_settlement(w.agents["a"], "Outpost")   # far away, at ridge
    w.action_propose_project(w.agents["b"], name="Shed", kind="workshop",
                             funds_required=0)
    b = next(iter(w.buildings.values()))
    # exactly the F1 pure fn (anchor = world origin) — the shipped behavior
    assert b.position == place_all(
        w.buildings.values(), (0.0, 0.0), w.city_seed)[b.id]


def test_settlements_disabled_is_f1_byte_identical(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world(enabled=False)
    w.action_propose_project(w.agents["a"], name="Hall", kind="workshop",
                             funds_required=0)
    b = next(iter(w.buildings.values()))
    assert b.position == place_all(
        w.buildings.values(), (0.0, 0.0), w.city_seed)[b.id]


def test_free_placement_off_stores_no_position(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", False)
    w = _world()
    w.action_found_settlement(w.agents["a"], "Outpost")
    r = w.action_propose_project(w.agents["a"], name="Hall", kind="workshop",
                                 funds_required=0)
    assert next(iter(w.buildings.values())).position is None
    # and no position ⇒ no loose-join signal either
    assert all(e["kind"] != "settlement_joined" for e in r["_multi"])


# ── the pure anchored fn: deterministic, append-only, overlap-clear ───────────

class _B:
    def __init__(self, id, created_tick, position=None):
        self.id, self.created_tick, self.position = id, created_tick, position


def test_place_one_anchored_is_pure_and_stable():
    stored = [_B(f"b{i}", i, (float(i), 0.0)) for i in range(4)]
    new = _B("new", 99)
    args = (new, stored + [new], (2.0, 0.0), 1337)
    p1 = place_one_anchored(*args)
    p2 = place_one_anchored(*args)
    assert p1 == p2                                   # pure fn of its inputs
    assert all(b.position == (float(i), 0.0)          # never moves the stored set
               for i, b in enumerate(stored))


def test_place_one_anchored_empty_pool_jitters_at_anchor():
    # nothing stored within SETTLEMENT_R of the anchor ⇒ the first hut lands
    # beside the anchor itself (seeded jitter), not beside the far city.
    far_city = [_B(f"c{i}", i, (float(i) * 1.6, 0.0)) for i in range(3)]
    new = _B("new", 99)
    pos = place_one_anchored(new, far_city + [new], (25.0, 25.0), 1337)
    assert _dist(pos, (25.0, 25.0)) <= 2.0


def test_place_one_anchored_never_stacks_on_stored():
    stored = [_B(f"b{i}", i, (25.0 + 0.2 * i, 25.0)) for i in range(6)]
    new = _B("new", 99)
    pos = place_one_anchored(new, stored + [new], (25.0, 25.0), 1337)
    assert all(((pos[0] - b.position[0]) ** 2
                + (pos[1] - b.position[1]) ** 2) ** 0.5 >= 1.0 for b in stored)


# ── loose joining: build near a settlement, get associated ────────────────────

def test_building_near_a_settlement_joins_it(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    evt = w.action_found_settlement(w.agents["b"], "Plazaville")  # at plaza ≈ origin
    sid = evt["payload"]["settlement_id"]
    w.agents["c"] = AgentState(id="c", name="Cyd", personality="", profile="mock",
                               location="plaza", energy=80.0, credits=20)
    r = w.action_propose_project(w.agents["c"], name="Hut", kind="home",
                                 funds_required=0)
    joined = [e for e in r["_multi"] if e["kind"] == "settlement_joined"]
    assert len(joined) == 1
    assert joined[0]["payload"]["settlement_id"] == sid
    assert joined[0]["payload"]["agent_id"] == "c"
    assert w.settlement_of("c") == sid                # loosely associated


def test_join_on_build_moves_home_with_membership(monkeypatch):
    """C10 regression — the EM-110 lock-step invariant: joining IS (re)homing.
    A build landing in a settlement's reach used to move the loose membership
    but leave home_settlement_id behind (unlike found_settlement and the
    arrival migration), desyncing the per-city perception horizon and
    travel_to's origin from where the agent actually belongs."""
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    evt = w.action_found_settlement(w.agents["b"], "Plazaville")  # at plaza ≈ origin
    sid = evt["payload"]["settlement_id"]
    w.agents["c"] = AgentState(id="c", name="Cyd", personality="", profile="mock",
                               location="plaza", energy=80.0, credits=20)
    assert w.agents["c"].home_settlement_id is None   # unhomed newcomer
    r = w.action_propose_project(w.agents["c"], name="Hut", kind="home",
                                 funds_required=0)
    assert any(e["kind"] == "settlement_joined" for e in r["_multi"])
    assert w.settlement_of("c") == sid                # membership moved …
    assert w.agents["c"].home_settlement_id == sid    # … and home WITH it


def test_member_building_at_home_emits_no_join(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    w.action_found_settlement(w.agents["a"], "Outpost")
    r = w.action_propose_project(w.agents["a"], name="Hall", kind="workshop",
                                 funds_required=0)
    assert all(e["kind"] != "settlement_joined" for e in r["_multi"])

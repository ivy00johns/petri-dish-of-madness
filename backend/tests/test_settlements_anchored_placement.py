"""EM-269 (F2) — settlement-anchored free placement: a member's build clusters
at their settlement's center; a non-member anchors to the city origin EXACTLY
as F1 shipped; building near a settlement associates the builder (loosely)."""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
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


def test_member_building_at_home_emits_no_join(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    w.action_found_settlement(w.agents["a"], "Outpost")
    r = w.action_propose_project(w.agents["a"], name="Hall", kind="workshop",
                                 funds_required=0)
    assert all(e["kind"] != "settlement_joined" for e in r["_multi"])

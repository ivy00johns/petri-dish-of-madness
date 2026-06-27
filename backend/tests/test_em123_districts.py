"""
EM-123 — zoned districts that DEEPEN as megaprojects complete.

Contract under test:
  - Places group into Neighborhoods (id == `neighborhood_id or district`) at
    tier 1; zone_kind is derived (override > district > kind) and reproduces the
    frontend's existing district→zone mapping.
  - A completed collective building advances its district's growth progress;
    every `completions_per_tier` completions raise the tier (capped at
    `max_tier`) and emit ONE `district_grew` event. Sub-threshold completions
    are silent.
  - EM-174-safe: growth is a tier/zoning state change, never a filler building.
  - Snapshot byte-identity (EM-155): a fresh world (all tier 1) omits the
    `neighborhoods` key entirely; once a tier diverges it serializes and
    round-trips through from_snapshot. Disabling the feature is byte-identical
    to pre-EM-123.

Everything here is deterministic and offline — pure world-core mechanics driven
through the World.action_* API + advance_buildings(), per the test_w7.py /
test_wave_b_citygrowth.py harness pattern.
"""
from __future__ import annotations

from petridish.engine.world import (
    World, AgentState, PlaceState, Neighborhood, zone_kind_for_place,
)
from petridish.config.loader import WorldParams, BuildingParams, DistrictGrowthParams


# Auto-build fast enough that one round finishes any funded project.
FAST_AUTO = 100


def _params(*, growth: DistrictGrowthParams | None = None, **building_overrides) -> WorldParams:
    p = WorldParams(
        energy_decay_per_turn=0.0,
        starting_energy=100.0,
        starting_credits=500,
        work_reward=4,
        death_after_zero_turns=99,
    )
    kwargs = dict(enabled=True, build_step=20, abandon_after_ticks=50,
                  auto_build_per_round=FAST_AUTO)
    kwargs.update(building_overrides)
    p.buildings = BuildingParams(**kwargs)
    if growth is not None:
        p.district_growth = growth
    return p


def _districted_places() -> list[PlaceState]:
    """The hand-authored town's district shape in miniature."""
    return [
        PlaceState(id="plaza",  name="Plaza",  x=0,  y=0,  kind="social",     district="core"),
        PlaceState(id="market", name="Market", x=10, y=0,  kind="work",       district="market"),
        PlaceState(id="forge",  name="Forge",  x=20, y=0,  kind="work",       district="market"),
        PlaceState(id="home",   name="Home",   x=0,  y=10, kind="home",       district="residential"),
        PlaceState(id="hall",   name="Hall",   x=0,  y=20, kind="governance", district="civic"),
        PlaceState(id="commons", name="Commons", x=10, y=10, kind="wild",     district="farm"),
    ]


def _world(params: WorldParams | None = None,
           places: list[PlaceState] | None = None) -> tuple[World, AgentState]:
    params = params or _params()
    places = places if places is not None else _districted_places()
    agent = AgentState(
        id="a0", name="Ada", personality="builder", profile="mock",
        location="plaza", energy=100.0, credits=params.starting_credits,
    )
    return World(params=params, places=places, agents=[agent]), agent


def _complete_one(world: World, agent: AgentState, place: str, name: str) -> list[dict]:
    """Propose + fully fund a project AT `place`, then run one round so the
    auto-build reflex finishes it. Returns the completion-round events."""
    res = world.action_propose_project(agent, name, "garden", 5, "+forage", place=place)
    bid = res["_building_id"]
    assert world.buildings[bid].location == place
    world.action_contribute_funds(agent, bid, 5)
    assert world.buildings[bid].status == "under_construction"
    world.tick += 1
    evts = world.advance_buildings()
    assert world.buildings[bid].status == "operational"
    return evts


def _of(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["kind"] == kind]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Neighborhood derivation
# ──────────────────────────────────────────────────────────────────────────────

def test_neighborhoods_derived_from_districts_at_tier_one():
    world, _ = _world()
    nb = world.neighborhoods
    assert set(nb) == {"core", "market", "residential", "civic", "farm"}
    # Every freshly-founded district starts at the baseline.
    assert all(n.tier == 1 and n.progress == 0 for n in nb.values())
    # zone_kind reproduces the frontend district mapping.
    assert nb["core"].zone_kind == "civic"
    assert nb["market"].zone_kind == "market"
    assert nb["residential"].zone_kind == "residential"
    assert nb["civic"].zone_kind == "civic"
    assert nb["farm"].zone_kind == "farm"
    # Display names are humanized.
    assert nb["residential"].name == "Residential"


def test_undistricted_town_yields_no_neighborhoods():
    places = [
        PlaceState(id="plaza",  name="Plaza",  x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=1, y=0, kind="work"),
    ]
    world, _ = _world(places=places)
    assert world.neighborhoods == {}


def test_neighborhood_id_override_splits_a_district():
    places = [
        PlaceState(id="a", name="A", x=0, y=0, kind="home", district="residential"),
        PlaceState(id="b", name="B", x=1, y=0, kind="home", district="residential",
                   neighborhood_id="uptown"),
    ]
    world, _ = _world(places=places)
    assert set(world.neighborhoods) == {"residential", "uptown"}


def test_zone_kind_override_wins_over_district():
    p = PlaceState(id="x", name="X", x=0, y=0, kind="home", district="residential",
                   zone_kind="industrial")
    assert zone_kind_for_place(p) == "industrial"
    world, _ = _world(places=[p])
    assert world.neighborhoods["residential"].zone_kind == "industrial"


def test_zone_kind_falls_back_through_district_then_kind():
    # No override, recognized district → district mapping.
    assert zone_kind_for_place(
        PlaceState(id="x", name="X", x=0, y=0, kind="work", district="farm")) == "farm"
    # No override, unknown district → place.kind fallback.
    assert zone_kind_for_place(
        PlaceState(id="x", name="X", x=0, y=0, kind="home", district="weird")) == "residential"
    # Nothing recognized → 'civic'.
    assert zone_kind_for_place(
        PlaceState(id="x", name="X", x=0, y=0, kind="mystery")) == "civic"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Growth on megaproject completion
# ──────────────────────────────────────────────────────────────────────────────

def test_first_completion_is_silent_second_levels_the_district():
    world, agent = _world()
    # 1st completion in 'market' → progress 1, still tier 1, NO district_grew.
    evts1 = _complete_one(world, agent, "market", "Stall One")
    assert world.neighborhoods["market"].tier == 1
    assert world.neighborhoods["market"].progress == 1
    assert _of(evts1, "district_grew") == []
    # The completion still emits its usual two events (byte-identical shape).
    assert [e["kind"] for e in evts1] == ["structure_state_changed", "building_operational"]

    # 2nd completion in 'market' → tier 2, progress reset, ONE district_grew.
    evts2 = _complete_one(world, agent, "market", "Stall Two")
    assert world.neighborhoods["market"].tier == 2
    assert world.neighborhoods["market"].progress == 0
    grew = _of(evts2, "district_grew")
    assert len(grew) == 1
    ev = grew[0]
    assert ev["actor_id"] is None          # system reflex, not an agent action
    assert ev["payload"]["neighborhood_id"] == "market"
    assert ev["payload"]["tier"] == 2
    assert ev["payload"]["zone_kind"] == "market"
    assert ev["payload"]["reason"] == "megaproject_completed"


def test_growth_is_isolated_per_district():
    world, agent = _world()
    _complete_one(world, agent, "market", "M1")
    _complete_one(world, agent, "home", "H1")
    # One completion each → both still tier 1; districts don't share progress.
    assert world.neighborhoods["market"].tier == 1
    assert world.neighborhoods["market"].progress == 1
    assert world.neighborhoods["residential"].tier == 1
    assert world.neighborhoods["residential"].progress == 1


def test_tier_caps_at_max_tier_and_stops_emitting():
    # per_tier=1 so every completion levels up; max_tier=3.
    growth = DistrictGrowthParams(enabled=True, completions_per_tier=1, max_tier=3)
    world, agent = _world(params=_params(growth=growth))
    grew = 0
    for i in range(6):
        evts = _complete_one(world, agent, "market", f"Build {i}")
        grew += len(_of(evts, "district_grew"))
    # tier 1 → 2 → 3 then frozen; only 2 level-ups ever fired.
    assert world.neighborhoods["market"].tier == 3
    assert grew == 2


def test_disabled_growth_is_byte_identical_pre_em123():
    growth = DistrictGrowthParams(enabled=False)
    world, agent = _world(params=_params(growth=growth))
    for i in range(4):
        evts = _complete_one(world, agent, "market", f"B{i}")
        assert _of(evts, "district_grew") == []
    # Districts never move; no divergence ⇒ no snapshot key (asserted below).
    assert world.neighborhoods["market"].tier == 1
    assert world.neighborhoods["market"].progress == 0
    assert "neighborhoods" not in world.to_snapshot()


def test_completion_in_undistricted_place_does_not_grow():
    places = [PlaceState(id="void", name="Void", x=0, y=0, kind="work")]
    world = World(params=_params(), places=places,
                  agents=[AgentState(id="a0", name="Ada", personality="b",
                                     profile="mock", location="void",
                                     energy=100.0, credits=500)])
    agent = world.agents["a0"]
    evts = _complete_one(world, agent, "void", "Nowhere Hall")
    assert _of(evts, "district_grew") == []
    assert world.neighborhoods == {}


# ──────────────────────────────────────────────────────────────────────────────
# 3. Snapshot round-trip + determinism (EM-155)
# ──────────────────────────────────────────────────────────────────────────────

def test_fresh_world_omits_neighborhoods_key():
    world, _ = _world()
    snap = world.to_snapshot()
    # All tier 1 ⇒ derivable baseline ⇒ key omitted (cap_demotions pattern).
    assert "neighborhoods" not in snap


def test_grown_world_serializes_and_round_trips():
    world, agent = _world()
    _complete_one(world, agent, "market", "M1")
    _complete_one(world, agent, "market", "M2")   # market → tier 2
    snap = world.to_snapshot()
    assert "neighborhoods" in snap
    market = next(n for n in snap["neighborhoods"] if n["id"] == "market")
    assert market["tier"] == 2 and market["progress"] == 0

    restored = World.from_snapshot(snap, params=world.params)
    assert restored.neighborhoods["market"].tier == 2
    assert restored.neighborhoods["market"].progress == 0
    # Untouched districts restore at the derived baseline.
    assert restored.neighborhoods["civic"].tier == 1
    # Byte-identical re-serialization (fork/replay fidelity).
    assert restored.to_snapshot()["neighborhoods"] == snap["neighborhoods"]


def test_mid_progress_round_trips():
    world, agent = _world()
    _complete_one(world, agent, "market", "M1")   # progress 1, tier 1
    snap = world.to_snapshot()
    # progress>0 diverges from baseline ⇒ serialized even though tier is 1.
    assert "neighborhoods" in snap
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.neighborhoods["market"].progress == 1
    # One more completion after restore levels it up (progress carried over).
    _complete_one(restored, restored.agents["a0"], "market", "M2")
    assert restored.neighborhoods["market"].tier == 2


def test_pre_em123_snapshot_restores_baseline():
    """A snapshot lacking the neighborhoods key (an old run) restores the
    derived tier-1 baseline from its places — never crashes, never loses zoning."""
    world, _ = _world()
    snap = world.to_snapshot()
    snap.pop("neighborhoods", None)   # simulate a pre-EM-123 snapshot
    restored = World.from_snapshot(snap, params=world.params)
    assert set(restored.neighborhoods) == {"core", "market", "residential", "civic", "farm"}
    assert all(n.tier == 1 for n in restored.neighborhoods.values())


def test_growth_timeline_is_deterministic_across_identical_runs():
    def run() -> list[int]:
        world, agent = _world()
        tiers = []
        for i in range(4):
            _complete_one(world, agent, "market", f"B{i}")
            tiers.append(world.neighborhoods["market"].tier)
        return tiers
    assert run() == run()   # pure counter arithmetic, no clock/RNG

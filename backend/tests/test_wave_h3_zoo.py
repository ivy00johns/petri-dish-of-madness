"""Wave H · H3 — THE LIVING ZOO (EM-208).

Proves the zoo slice end to end, reusing the EXISTING collective-project
pipeline (a zoo is just a building kind=="zoo" — no pipeline change):

  - a zoo project taken propose -> fund -> build_step to OPERATIONAL auto-stocks
    up to buildings.zoo_capacity animals AT the zoo's place (housing = same
    place), DETERMINISTICALLY (same building id -> identical menagerie), and
    respects animals.max_population;
  - a NON-zoo building completing the SAME pipeline stocks NOTHING (the hook is
    guarded to kind=="zoo");
  - World.trigger_zoo_escape relocates every housed animal OUT to another place
    and emits the dramatic random_event + one is_chaotic animal_action per
    escapee;
  - an escape with no operational zoo is an empty no-op.

CRITICAL suite rule (mirrors the W8 / menagerie family): import
petridish.engine.world BEFORE petridish.agents.runtime / animals.runtime so the
world module binds first. The world import below precedes every runtime import.
"""
from __future__ import annotations

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, BuildingParams, AnimalParams
# Runtime imports AFTER world.
from petridish.animals.runtime import ANIMAL_SPECIES_CATALOG  # noqa: F401


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a tiny offline world + a deterministic propose->fund->build driver.
# ──────────────────────────────────────────────────────────────────────────────

def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="commons", name="Commons", x=0, y=10, kind="wild"),
        PlaceState(id="shack", name="The Shack", x=10, y=10, kind="home"),
    ]


def _world(
    *,
    zoo_capacity: int = 5,
    max_population: int = 0,
    places: list[PlaceState] | None = None,
) -> tuple[World, AgentState]:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        buildings=BuildingParams(enabled=True, build_step=20, zoo_capacity=zoo_capacity),
        animals=AnimalParams(enabled=True, llm_chance=0.0, model_profile="",
                             max_population=max_population),
    )
    ada = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                     location="plaza", energy=100.0, credits=1000)
    world = World(params=params, places=places or _places(), agents=[ada])
    return world, ada


def _drive_to_operational(world: World, agent: AgentState, kind: str,
                          name: str = "Civic Build") -> Building:
    """Propose -> fully fund -> build_step a `kind` building to operational,
    using ONLY the existing pipeline actions (no engine change needed)."""
    proposed = world.action_propose_project(agent, name, kind, funds_required=40)
    bid = proposed["_building_id"]
    world.action_contribute_funds(agent, bid, 40)            # fully funds it
    # build_step repeatedly until operational (build_step=20 -> 5 steps).
    for _ in range(10):
        world.action_build_step(agent, bid)
        if world.buildings[bid].status == "operational":
            break
    return world.buildings[bid]


def _build_events_to_operational(world: World, agent: AgentState, kind: str,
                                 name: str = "Civic Build") -> list[dict]:
    """Same as _drive_to_operational but returns the FLATTENED event stream from
    the build_step calls (so tests can assert what completion emitted)."""
    proposed = world.action_propose_project(agent, name, kind, funds_required=40)
    bid = proposed["_building_id"]
    world.action_contribute_funds(agent, bid, 40)
    events: list[dict] = []
    for _ in range(10):
        result = world.action_build_step(agent, bid)
        events.extend(result.get("_multi", []))
        if world.buildings[bid].status == "operational":
            break
    return events


# ──────────────────────────────────────────────────────────────────────────────
# 1. AUTO-STOCK — a zoo opening stocks <= zoo_capacity animals AT the zoo place.
# ──────────────────────────────────────────────────────────────────────────────

def test_zoo_auto_stocks_at_its_place_on_open():
    world, ada = _world(zoo_capacity=5)
    events = _build_events_to_operational(world, ada, "zoo", name="City Zoo")
    zoo = next(b for b in world.buildings.values() if b.kind == "zoo")
    assert zoo.status == "operational"

    stock_events = [e for e in events
                    if e.get("kind") == "animal_spawned"
                    and e["payload"].get("method") == "zoo_stock"]
    assert len(stock_events) == 5, "should stock exactly zoo_capacity animals"

    housed = [a for a in world.living_animals() if a.location == zoo.location]
    assert len(housed) == 5, "all stocked animals live AT the zoo's place"
    # Every stock event reports the zoo place + the zoo building id.
    for e in stock_events:
        assert e["payload"]["location"] == zoo.location
        assert e["payload"]["building_id"] == zoo.id
        assert e["actor_type"] == "animal"


def test_zoo_stock_is_deterministic_for_same_building_id():
    """Same building id -> same stock (seeded off the id + index, no RNG)."""
    # Force a fixed building id so two independent worlds stock identically.
    world_a, ada_a = _world(zoo_capacity=4)
    world_b, ada_b = _world(zoo_capacity=4)

    def _drive_fixed(world: World, agent: AgentState) -> Building:
        bld = Building(id="bld_fixedzoo", name="City Zoo", kind="zoo",
                       location="plaza", owner_id="public",
                       status="under_construction", progress=80,
                       funds_required=40, funds_committed=40)
        world.buildings[bld.id] = bld
        world.action_build_step(agent, bld.id)  # 80 -> 100 -> operational + stock
        return world.buildings[bld.id]

    zoo_a = _drive_fixed(world_a, ada_a)
    zoo_b = _drive_fixed(world_b, ada_b)
    assert zoo_a.status == zoo_b.status == "operational"

    species_a = sorted(a.species for a in world_a.living_animals())
    species_b = sorted(a.species for a in world_b.living_animals())
    assert species_a == species_b and len(species_a) == 4, \
        "a fixed building id must yield the identical menagerie"


def test_zoo_stock_respects_max_population():
    # Cap of 2: a zoo that wants 5 can only stock 2.
    world, ada = _world(zoo_capacity=5, max_population=2)
    _drive_to_operational(world, ada, "zoo", name="Tiny Zoo")
    assert len(world.living_animals()) == 2, "stock stops at animals.max_population"


def test_zoo_capacity_zero_stocks_nothing():
    world, ada = _world(zoo_capacity=0)
    _drive_to_operational(world, ada, "zoo", name="Empty Zoo")
    assert world.living_animals() == []


# ──────────────────────────────────────────────────────────────────────────────
# 2. GUARDED — a NON-zoo completion stocks nothing (byte-identical to pre-H3).
# ──────────────────────────────────────────────────────────────────────────────

def test_non_zoo_building_stocks_nothing():
    world, ada = _world(zoo_capacity=5)
    events = _build_events_to_operational(world, ada, "garden", name="Town Garden")
    bld = next(b for b in world.buildings.values() if b.kind == "garden")
    assert bld.status == "operational"
    assert world.living_animals() == [], "only kind=='zoo' auto-stocks"
    assert not any(e.get("kind") == "animal_spawned" for e in events)


# ──────────────────────────────────────────────────────────────────────────────
# 3. ESCAPE — relocate housed animals OUT + emit the chaos events.
# ──────────────────────────────────────────────────────────────────────────────

def test_trigger_zoo_escape_relocates_and_emits_chaos():
    world, ada = _world(zoo_capacity=5)
    zoo = _drive_to_operational(world, ada, "zoo", name="City Zoo")
    housed_ids = {a.id for a in world.living_animals()
                  if a.location == zoo.location}
    assert len(housed_ids) == 5

    events = world.trigger_zoo_escape()

    # One dramatic banner + one is_chaotic animal_action per escapee.
    banners = [e for e in events if e.get("kind") == "random_event"]
    escapes = [e for e in events if e.get("kind") == "animal_action"]
    assert len(banners) == 1
    assert banners[0]["actor_type"] == "system"
    assert banners[0]["is_chaotic"] is True
    assert "ESCAPE!" in banners[0]["text"] and zoo.name in banners[0]["text"]
    assert banners[0]["payload"]["escaped"] == 5

    assert len(escapes) == 5
    for e in escapes:
        assert e["is_chaotic"] is True
        assert e["payload"]["action"] == "escape"
        assert e["payload"]["from_place"] == zoo.location
        assert e["payload"]["to_place"] != zoo.location

    # Every animal has actually MOVED out of the zoo's place.
    assert not any(a.location == zoo.location for a in world.living_animals()
                   if a.id in housed_ids)


def test_trigger_zoo_escape_is_deterministic():
    """Same animal ids + same tick -> same destinations (the escape destination
    is a seeded hash of animal.id + tick, so it replays identically). We pin the
    animal ids (spawn_animal mints a uuid suffix, so we place the housed animals
    by hand) to isolate the escape's own determinism."""
    def _world_with_zoo() -> tuple[World, Building]:
        world, _ = _world(zoo_capacity=0)
        zoo = Building(id="bld_fixedzoo", name="City Zoo", kind="zoo",
                       location="plaza", owner_id="public", status="operational",
                       progress=100, funds_required=40, funds_committed=40)
        world.buildings[zoo.id] = zoo
        for sp, fixed_id in (("cat", "animal_pin_cat"),
                             ("dog", "animal_pin_dog"),
                             ("crow", "animal_pin_crow")):
            a = world.spawn_animal(species=sp, name=sp.capitalize(),
                                   location="plaza")
            # Re-key under a fixed id so both worlds share identical ids.
            del world.animals[a.id]
            a.id = fixed_id
            world.animals[fixed_id] = a
        return world, zoo

    world_a, _ = _world_with_zoo()
    world_b, _ = _world_with_zoo()
    world_a.trigger_zoo_escape()
    world_b.trigger_zoo_escape()
    dests_a = {a.id: a.location for a in world_a.living_animals()}
    dests_b = {a.id: a.location for a in world_b.living_animals()}
    assert dests_a == dests_b
    # And they really left the zoo place.
    assert all(loc != "plaza" for loc in dests_a.values())


def test_trigger_zoo_escape_no_operational_zoo_is_noop():
    world, ada = _world(zoo_capacity=5)
    # A garden (non-zoo) operational + a PLANNED zoo (not yet operational).
    _drive_to_operational(world, ada, "garden", name="Town Garden")
    world.action_propose_project(ada, "Future Zoo", "zoo", funds_required=40)
    before = {a.id: a.location for a in world.living_animals()}

    events = world.trigger_zoo_escape()
    assert events == [], "no operational zoo -> empty no-op"
    after = {a.id: a.location for a in world.living_animals()}
    assert before == after, "no animal moved"


def test_trigger_zoo_escape_empty_zoo_is_noop():
    """An operational zoo with NO housed animals frees nobody."""
    world, ada = _world(zoo_capacity=0)  # opens but stocks nothing
    zoo = _drive_to_operational(world, ada, "zoo", name="Empty Zoo")
    assert zoo.status == "operational"
    assert world.trigger_zoo_escape() == []


def test_trigger_zoo_escape_named_building_targets_only_that_zoo():
    world, ada = _world(zoo_capacity=2)
    # Two operational zoos at different places.
    ada.location = "plaza"
    zoo1 = _drive_to_operational(world, ada, "zoo", name="Plaza Zoo")
    ada.location = "market"
    zoo2 = _drive_to_operational(world, ada, "zoo", name="Market Zoo")

    z2_ids = {a.id for a in world.living_animals() if a.location == zoo2.location}
    events = world.trigger_zoo_escape(zoo1.id)

    # Only zoo1 broke loose: one banner, and zoo2's animals never moved.
    banners = [e for e in events if e.get("kind") == "random_event"]
    assert len(banners) == 1
    assert banners[0]["payload"]["building_id"] == zoo1.id
    assert all(a.location == zoo2.location for a in world.living_animals()
               if a.id in z2_ids), "the un-named zoo's animals stay put"

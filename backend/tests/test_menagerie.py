"""Wave H · H1 — add-a-pet + the expanded 7-species menagerie (EM-143).

Proves the menagerie slice end to end:
  - the 5 NEW species (squirrel/raccoon/goat/fox/crow) spawn via
    world.spawn_animal and take a REFLEX turn drawing from their OWN species
    table (zero LLM calls — free-scale);
  - POST /api/animals ACCEPTS a new catalog species and REJECTS an unknown one
    (400) instead of the old hardcoded cat|dog gate;
  - the population cap raises ValueError at the engine seam and surfaces as 409
    once living animals >= animals.max_population.

CRITICAL suite rule (mirrors the W8 family): import petridish.engine.world
BEFORE petridish.agents.runtime / petridish.animals.runtime so the world module
binds first. The world import below precedes every runtime import.
"""
from __future__ import annotations

import asyncio
import sys

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, AnimalParams
from petridish.providers.router import Router
from petridish.config.loader import ModelProfile
# Runtime imports AFTER world.
from petridish.animals.runtime import (
    ANIMAL_SPECIES_CATALOG,
    AnimalRuntime,
    _REFLEX_TABLE,
    _ROLE_CARDS,
)


NEW_SPECIES = ("squirrel", "raccoon", "goat", "fox", "crow")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a tiny offline world + a reflex-only runtime (no router calls needed).
# ──────────────────────────────────────────────────────────────────────────────

def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
        PlaceState(id="commons", name="Commons", x=500, y=750, kind="wild"),
    ]


def _world(max_population: int = 0) -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        animals=AnimalParams(enabled=True, llm_chance=0.0, model_profile="",
                             max_population=max_population),
    )
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=10),
    ]
    return World(params=params, places=_places(), agents=agents)


def _reflex_runtime(world: World) -> AnimalRuntime:
    # llm_chance=0 + no profile → the runtime is purely reflex; the router is only
    # held as a reference and is never called on a reflex tick.
    router = Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                  color="#2ecc71")], cache_enabled=False)
    return AnimalRuntime(world, router)


# ──────────────────────────────────────────────────────────────────────────────
# (1) The catalog IS exactly the 7 species, and every species has a reflex table.
# ──────────────────────────────────────────────────────────────────────────────

def test_catalog_is_the_seven_species():
    assert ANIMAL_SPECIES_CATALOG == frozenset(
        {"cat", "dog", "squirrel", "raccoon", "goat", "fox", "crow"}
    )
    # Catalog keys mirror the role-card keys exactly (single source of truth).
    assert ANIMAL_SPECIES_CATALOG == frozenset(_ROLE_CARDS.keys())
    # Every catalog species has a distinct, non-empty reflex table.
    for species in ANIMAL_SPECIES_CATALOG:
        assert species in _REFLEX_TABLE, f"{species} missing a reflex table"
        assert _REFLEX_TABLE[species], f"{species} reflex table is empty"


# ──────────────────────────────────────────────────────────────────────────────
# (2) A new species spawns and takes a reflex turn from ITS OWN species table.
# ──────────────────────────────────────────────────────────────────────────────

def test_new_species_spawn_and_reflex_turn_from_own_table():
    for species in NEW_SPECIES:
        world = _world()
        runtime = _reflex_runtime(world)
        animal = world.spawn_animal(species=species, name=f"Test{species}",
                                    location="plaza")
        assert animal.species == species
        assert animal in world.living_animals()

        # Reflex tick (llm_chance=0): ZERO router calls, deterministic action that
        # MUST be drawn from this species' own reflex table.
        events = asyncio.run(runtime.act(animal, world, tick=1))
        action_events = [e for e in events if e.get("kind") == "animal_action"]
        assert len(action_events) == 1
        assert not [e for e in events if e.get("kind") == "llm_call"], \
            "a reflex tick must make ZERO LLM calls (free-scale)"

        action = action_events[0]["payload"]["action"]
        table_actions = {a for a, _ in _REFLEX_TABLE[species]}
        assert action in table_actions, (
            f"{species} reflex picked {action!r} not in its table {table_actions}"
        )
        assert action_events[0]["actor_type"] == "animal"


def test_raccoon_reflex_can_express_its_thief_flavor():
    # The raccoon's table carries steal_food (its defining chaos flavor). Across a
    # window of deterministic reflex ticks it should surface at least one of its
    # signature destructive/thief actions, never just naps.
    world = _world()
    runtime = _reflex_runtime(world)
    animal = world.spawn_animal(species="raccoon", name="Bandit", location="plaza")
    actions = set()
    for tick in range(40):
        events = asyncio.run(runtime.act(animal, world, tick=tick))
        for e in events:
            if e.get("kind") == "animal_action":
                actions.add(e["payload"]["action"])
    table_actions = {a for a, _ in _REFLEX_TABLE["raccoon"]}
    assert actions <= table_actions, f"raccoon drew off-table action(s): {actions - table_actions}"
    assert actions & {"knock_over", "steal_food", "mark_territory"}, \
        "raccoon never expressed its ransacker/thief flavor across 40 reflex ticks"


# ──────────────────────────────────────────────────────────────────────────────
# (3) Population cap — engine seam raises ValueError once full (0 = unlimited).
# ──────────────────────────────────────────────────────────────────────────────

def test_population_cap_raises_value_error_when_full():
    world = _world(max_population=2)
    world.spawn_animal(species="fox", name="One", location="plaza")
    world.spawn_animal(species="crow", name="Two", location="plaza")
    assert len(world.living_animals()) == 2
    try:
        world.spawn_animal(species="goat", name="Three", location="plaza")
        raised = False
    except ValueError as exc:
        raised = True
        assert "population cap reached" in str(exc)
        assert "2" in str(exc)
    assert raised, "spawn_animal must raise ValueError once the cap is reached"
    assert len(world.living_animals()) == 2, "no animal added past the cap"


def test_population_cap_zero_is_unlimited():
    world = _world(max_population=0)
    for i in range(20):
        world.spawn_animal(species="squirrel", name=f"S{i}", location="plaza")
    assert len(world.living_animals()) == 20


# ──────────────────────────────────────────────────────────────────────────────
# (4) API — POST /api/animals accepts a catalog species, rejects unknown (400),
#     and the cap surfaces as 409. Uses the TestClient (test_w11b / god idiom).
# ──────────────────────────────────────────────────────────────────────────────

def test_api_accepts_new_species_rejects_unknown_and_caps():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # ACCEPT a NEW catalog species (was impossible under the old cat|dog gate).
        resp = client.post("/api/animals",
                           json={"species": "raccoon", "name": "Bandit",
                                 "location": "plaza"})
        assert resp.status_code == 201, resp.text
        animal_id = resp.json()["animal_id"]
        assert appmod._world.animals[animal_id].species == "raccoon"

        # Name is OPTIONAL-ish (a default of "" is accepted by the body model),
        # but species drives validation: an unknown species is a 400, not a 500.
        bad = client.post("/api/animals",
                          json={"species": "dragon", "name": "Smaug",
                                "location": "plaza"})
        assert bad.status_code == 400, bad.text
        assert "dragon" in bad.json()["detail"]

        # Population cap → 409. Pin the live world's cap just above the current
        # count so the very next spawn trips it deterministically.
        living = len(appmod._world.living_animals())
        appmod._world.params.animals.max_population = living
        capped = client.post("/api/animals",
                             json={"species": "fox", "name": "Toofull",
                                   "location": "plaza"})
        assert capped.status_code == 409, capped.text
        assert "population cap reached" in capped.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# Wave H2 · THE MENAGERIE — ambient spawning + the REWILD god button (EM-207).
# ──────────────────────────────────────────────────────────────────────────────

from petridish.config.loader import WorldConfig, AnimalSeed
from petridish.engine.loop import TickLoop
from petridish.agents.runtime import AgentRuntime
from petridish.persistence.repository import SQLiteRepository
from petridish.config.loader import ModelProfile as _MP


def _ambient_loop(max_population: int = 0, every: int = 4,
                  chance: float = 1.0) -> tuple[World, TickLoop, list]:
    """A tiny offline TickLoop wired for ambient-spawn assertions (no LLM)."""
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        animals=AnimalParams(
            enabled=True, llm_chance=0.0, model_profile="",
            max_population=max_population,
            ambient_spawn_every=every, ambient_spawn_chance=chance,
        ),
    )
    agents = [AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                         location="plaza", energy=100.0, credits=10)]
    world = World(params=params, places=_places(), agents=agents)
    router = Router([_MP(name="mock", adapter="mock", model_id="mock",
                         color="#2ecc71")], cache_enabled=False)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    events: list = []
    loop = TickLoop(world, runtime, repo, router,
                    broadcaster=lambda m: events.append(m))
    loop._run_id = 1
    return world, loop, events


# (5) Ambient spawn respects the cap AND is deterministic for a fixed tick.

def test_ambient_spawn_is_deterministic_for_a_fixed_tick():
    # Two independent worlds, same run_id + same tick → identical species + place.
    w1, l1, _ = _ambient_loop(max_population=0, every=4, chance=1.0)
    w2, l2, _ = _ambient_loop(max_population=0, every=4, chance=1.0)
    w1.tick = 8
    w2.tick = 8
    l1._maybe_schedule_ambient_animal()
    l2._maybe_schedule_ambient_animal()
    a1 = list(w1.living_animals())
    a2 = list(w2.living_animals())
    assert len(a1) == 1 and len(a2) == 1, "exactly one ambient critter per window"
    assert a1[0].species == a2[0].species, "same seed → same species"
    assert a1[0].location == a2[0].location, "same seed → same place"
    assert a1[0].species in ANIMAL_SPECIES_CATALOG


def test_ambient_spawn_emits_animal_spawned_method_ambient():
    world, loop, events = _ambient_loop(max_population=0, every=4, chance=1.0)
    world.tick = 4
    loop._maybe_schedule_ambient_animal()
    spawned = [m for m in events
               if isinstance(m, dict) and m.get("kind") == "animal_spawned"]
    # Broadcast frames also flow through `events`; filter to the spawn event.
    spawn_evts = [e for e in spawned if (e.get("payload") or {}).get("method") == "ambient"]
    assert spawn_evts, "ambient spawn must emit animal_spawned{method:ambient}"


def test_ambient_spawn_respects_the_cap():
    # Cap of 1, with the seed agent's world starting at 0 animals: the first aligned
    # tick fills the menagerie; later aligned ticks must NOT exceed the cap.
    world, loop, _ = _ambient_loop(max_population=1, every=4, chance=1.0)
    for t in (4, 8, 12, 16):
        world.tick = t
        loop._maybe_schedule_ambient_animal()
    assert len(world.living_animals()) == 1, "ambient spawning must honor max_population"


def test_ambient_spawn_off_when_every_is_zero():
    # ambient_spawn_every:0 (the backward-compatible default) disables it entirely.
    world, loop, _ = _ambient_loop(max_population=0, every=0, chance=1.0)
    for t in (1, 2, 3, 4, 8, 40):
        world.tick = t
        loop._maybe_schedule_ambient_animal()
    assert len(world.living_animals()) == 0, "every:0 must disable ambient spawning"


def test_ambient_spawn_skips_on_unaligned_ticks_and_zero_chance():
    # Not on an aligned tick → no spawn.
    world, loop, _ = _ambient_loop(max_population=0, every=4, chance=1.0)
    world.tick = 5  # 5 % 4 != 0
    loop._maybe_schedule_ambient_animal()
    assert len(world.living_animals()) == 0
    # Aligned tick but chance 0.0 → no spawn (the roll never lands).
    world2, loop2, _ = _ambient_loop(max_population=0, every=4, chance=0.0)
    world2.tick = 4
    loop2._maybe_schedule_ambient_animal()
    assert len(world2.living_animals()) == 0


# (6) POST /api/god/rewild — a burst up to the cap, reports cap_reached when full.

def test_api_rewild_spawns_a_burst_and_reports_cap_reached():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        before = len(appmod._world.living_animals())
        resp = client.post("/api/god/rewild", json={"count": 3})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["spawned"] == 3, body
        assert body["cap_reached"] is False
        assert len(appmod._world.living_animals()) == before + 3
        # Every rewilded critter is a real catalog species.
        for a in appmod._world.animals.values():
            assert a.species in ANIMAL_SPECIES_CATALOG

        # Pin the cap to the current count; the next rewild can spawn NOTHING and
        # must report cap_reached.
        living = len(appmod._world.living_animals())
        appmod._world.params.animals.max_population = living
        full = client.post("/api/god/rewild", json={"count": 4})
        assert full.status_code == 200, full.text
        full_body = full.json()
        assert full_body["spawned"] == 0
        assert full_body["cap_reached"] is True
        assert len(appmod._world.living_animals()) == living, "no spawn past the cap"

        # A burst that PARTIALLY fits stops exactly at the cap (cap_reached True).
        appmod._world.params.animals.max_population = living + 2
        partial = client.post("/api/god/rewild", json={"count": 5})
        assert partial.status_code == 200, partial.text
        pbody = partial.json()
        assert pbody["spawned"] == 2, pbody
        assert pbody["cap_reached"] is True
        assert len(appmod._world.living_animals()) == living + 2


def test_api_rewild_default_count_is_four():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # Lift the cap so the default burst fits.
        appmod._world.params.animals.max_population = 0
        before = len(appmod._world.living_animals())
        resp = client.post("/api/god/rewild")  # no body → count defaults to 4
        assert resp.status_code == 200, resp.text
        assert resp.json()["spawned"] == 4
        assert len(appmod._world.living_animals()) == before + 4


# ──────────────────────────────────────────────────────────────────────────────
# (5) Cull — thin the herd to `keep`, oldest-of-each-species first (seeds survive).
# ──────────────────────────────────────────────────────────────────────────────

def test_cull_thins_to_keep_oldest_per_species():
    world = _world()  # unlimited cap
    # Two seed pets (oldest) + four younger test critters (one a DUP species).
    cat = world.spawn_animal(species="cat", name="Mochi", location="plaza")
    cat.created_tick = 0
    dog = world.spawn_animal(species="dog", name="Biscuit", location="commons")
    dog.created_tick = 0
    for i, (sp, nm) in enumerate(
        [("cat", "Extra cat"), ("goat", "Goaty"), ("fox", "Foxy"), ("squirrel", "Nutters")],
        start=1,
    ):
        a = world.spawn_animal(species=sp, name=nm, location="plaza")
        a.created_tick = 10 + i
    assert len(world.living_animals()) == 6

    events = world.cull_animals(keep=3)

    living = world.living_animals()
    assert len(living) == 3, "thinned down to keep"
    names = {a.name for a in living}
    assert "Mochi" in names and "Biscuit" in names, "seed pets (oldest) survive"
    assert "Extra cat" not in names, "the younger DUP-species critter is culled first"
    # variety-first: the kept three are distinct species (cat, dog, + one more).
    assert sorted(a.species for a in living)[:2] == ["cat", "dog"]
    assert len(events) == 3
    assert all(e["kind"] == "animal_died" and e["payload"]["method"] == "culled"
               for e in events)
    assert sum(1 for a in world.animals.values() if not a.alive) == 3


def test_cull_is_a_noop_at_or_under_keep():
    world = _world()
    world.spawn_animal(species="cat", name="Solo", location="plaza")
    assert world.cull_animals(keep=5) == []
    assert len(world.living_animals()) == 1

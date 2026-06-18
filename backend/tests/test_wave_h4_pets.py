"""Wave H · H4 — PETS & BONDS (EM-209), the emotional capstone.

Proves the arc end to end, reflex-first and deterministic/replay-safe:
  - ADOPT sets owner_id, is CO-LOCATION-gated, rejects an already-owned animal;
  - an OWNED pet FOLLOWS — after the owner moves, the pet's reflex turn syncs its
    location to the owner's place (zero LLM);
  - feed_pet restores a co-located animal's energy (no credits move);
  - an owned pet DECLINES per turn and on energy 0 DIES and emits a `reflection`
    event ATTRIBUTED TO THE OWNER (the guaranteed grief diary entry) PLUS an
    `animal_died` carrying the owner so the owner's reflection accumulator gets the
    pet_death boost;
  - an UNOWNED animal does NOT decline and still wanders.

CRITICAL suite rule (mirrors the W8 / menagerie family): import
petridish.engine.world BEFORE the runtime modules so the world module binds first.
"""
from __future__ import annotations

import asyncio

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, AnimalParams, ModelProfile
from petridish.providers.router import Router

# Runtime imports AFTER world.
from petridish.animals.runtime import AnimalRuntime
from petridish.agents.runtime import (
    AgentRuntime,
    ACTION_SCHEMA,
    TOOL_REGISTRY,
    _validate_world,
    _IMPORTANCE_WEIGHTS,
)

import jsonschema


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a tiny offline world; reflex-only animal runtime (no router calls).
# ──────────────────────────────────────────────────────────────────────────────

def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
        PlaceState(id="commons", name="Commons", x=500, y=750, kind="wild"),
    ]


def _world(*, pet_energy_decay: int = 2, pet_feed_amount: int = 25) -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        animals=AnimalParams(
            enabled=True, llm_chance=0.0, model_profile="",
            pet_energy_decay=pet_energy_decay, pet_feed_amount=pet_feed_amount,
        ),
    )
    agents = [
        AgentState(id="agent_vesper", name="Vesper", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=10),
        AgentState(id="agent_bram", name="Bram", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=10),
    ]
    return World(params=params, places=_places(), agents=agents)


def _router() -> Router:
    # llm_chance=0 + no profile → the animal runtime is purely reflex; the router
    # is only held as a reference and is never called on a reflex tick.
    return Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                color="#2ecc71")], cache_enabled=False)


def _animal_runtime(world: World) -> AnimalRuntime:
    return AnimalRuntime(world, _router())


def _agent_runtime(world: World) -> AgentRuntime:
    return AgentRuntime(world, _router())


# ──────────────────────────────────────────────────────────────────────────────
# (1) Schema + registry: adopt/feed_pet are reflex tools with an animal_id arg.
# ──────────────────────────────────────────────────────────────────────────────

def test_adopt_and_feed_are_registered_reflex_tools():
    for action in ("adopt", "feed_pet"):
        meta = TOOL_REGISTRY[action]
        assert meta["tier"] == "reflex"
        # The CO-LOCATION gate is animal-specific (enforced in _validate_world), so
        # neither carries a place location_gate or an agreement_gate.
        assert meta["location_gate"] is None
        assert meta["agreement_gate"] is None
    # Both verbs are in the single-action enum AND require animal_id structurally.
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    assert "adopt" in enum and "feed_pet" in enum
    jsonschema.validate({"action": "adopt", "args": {"animal_id": "animal_x"}}, ACTION_SCHEMA)
    jsonschema.validate({"action": "feed_pet", "args": {"animal_id": "animal_x"}}, ACTION_SCHEMA)
    # animal_id is required.
    for bad in ({"action": "adopt", "args": {}}, {"action": "feed_pet", "args": {}}):
        try:
            jsonschema.validate(bad, ACTION_SCHEMA)
            raised = False
        except jsonschema.ValidationError:
            raised = True
        assert raised, f"{bad} must fail (animal_id required)"


# ──────────────────────────────────────────────────────────────────────────────
# (2) ADOPT: sets owner_id, is co-location-gated, rejects an already-owned animal.
# ──────────────────────────────────────────────────────────────────────────────

def test_adopt_sets_owner_id():
    world = _world()
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    assert cat.owner_id is None
    ok, reason = world.action_adopt(vesper, cat.id)
    assert ok and reason == "ok"
    assert cat.owner_id == vesper.id
    # Serialized in the Animal to-dict (so world_state / snapshot carries the bond).
    assert cat.to_dict()["owner_id"] == vesper.id


def test_adopt_is_co_location_gated():
    world = _world()
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="commons")
    # Vesper is at the plaza, the cat at the commons → the validator rejects.
    err = _validate_world({"action": "adopt", "args": {"animal_id": cat.id}}, vesper, world)
    assert err is not None and "not here" in err
    # The engine method is independently safe (defense in depth).
    ok, reason = world.action_adopt(vesper, cat.id)
    assert not ok and cat.owner_id is None


def test_adopt_rejects_an_already_owned_animal():
    world = _world()
    vesper = world.agents["agent_vesper"]
    bram = world.agents["agent_bram"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    ok, _ = world.action_adopt(vesper, cat.id)
    assert ok
    # A second agent at the same place cannot poach an owned pet.
    err = _validate_world({"action": "adopt", "args": {"animal_id": cat.id}}, bram, world)
    assert err is not None and "already has an owner" in err
    ok2, reason2 = world.action_adopt(bram, cat.id)
    assert not ok2 and cat.owner_id == vesper.id
    # The owner re-adopting is also rejected (a no-op turn, not a silent success).
    err_self = _validate_world({"action": "adopt", "args": {"animal_id": cat.id}}, vesper, world)
    assert err_self is not None and "already own" in err_self


def test_adopt_unknown_or_dead_animal_rejected():
    world = _world()
    vesper = world.agents["agent_vesper"]
    assert _validate_world({"action": "adopt", "args": {"animal_id": "nope"}}, vesper, world)
    cat = world.spawn_animal(species="cat", name="Ghost", location="plaza")
    cat.alive = False
    err = _validate_world({"action": "adopt", "args": {"animal_id": cat.id}}, vesper, world)
    assert err is not None and "not alive" in err


# ──────────────────────────────────────────────────────────────────────────────
# (3) FOLLOW: an owned pet's reflex turn syncs its location to the owner's.
# ──────────────────────────────────────────────────────────────────────────────

def test_owned_pet_follows_its_owner_after_a_move():
    world = _world()
    runtime = _animal_runtime(world)
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    world.action_adopt(vesper, cat.id)
    assert cat.location == "plaza"

    # The owner crosses the plaza to the commons; the pet's NEXT reflex turn trails.
    vesper.location = "commons"
    events = asyncio.run(runtime.act(cat, world, tick=1))
    assert cat.location == "commons", "an owned pet must follow its owner"
    # Reflex-only (zero LLM) and still emits exactly one animal_action.
    assert not [e for e in events if e.get("kind") == "llm_call"]
    assert len([e for e in events if e.get("kind") == "animal_action"]) == 1


def test_pet_with_dead_or_missing_owner_reverts_to_wandering():
    # An owned pet whose owner died falls back to ordinary wandering (no crash, no
    # stuck-at-origin). The reflex must NOT lock it onto a gone owner's place.
    world = _world()
    runtime = _animal_runtime(world)
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    world.action_adopt(vesper, cat.id)
    vesper.alive = False  # owner gone — owner_id now dangles
    # With a live owner-at-the-plaza the FOLLOW reflex pins the pet to the owner's
    # place; with the owner gone, _owner_of returns None so the pet wanders freely.
    # Drive `wander` directly through the reflex apply path (no LLM) and assert it
    # is NOT locked onto the gone owner — it reaches the other known place.
    runtime._apply(cat, "wander", {})
    assert cat.location == "commons", (
        "a pet whose owner is gone must wander freely, not stay pinned"
    )


# ──────────────────────────────────────────────────────────────────────────────
# (4) FEED: feed_pet restores energy (no credits move); co-location-gated.
# ──────────────────────────────────────────────────────────────────────────────

def test_feed_pet_restores_energy():
    world = _world(pet_feed_amount=30)
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    world.action_adopt(vesper, cat.id)
    cat.energy = 40
    credits_before = vesper.credits
    ok, reason = world.action_feed_pet(vesper, cat.id)
    assert ok and reason == "ok"
    assert cat.energy == 70  # 40 + 30
    assert vesper.credits == credits_before, "feeding moves NO credits (invariant 7)"
    # Energy clamps at 100.
    cat.energy = 90
    world.action_feed_pet(vesper, cat.id)
    assert cat.energy == 100


def test_feed_pet_co_location_gated_and_any_agent_can_feed():
    world = _world()
    vesper = world.agents["agent_vesper"]
    bram = world.agents["agent_bram"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    world.action_adopt(vesper, cat.id)
    cat.energy = 20
    # A co-located NON-owner (Bram) may feed the pet (sustains a declining pet).
    assert _validate_world({"action": "feed_pet", "args": {"animal_id": cat.id}}, bram, world) is None
    ok, _ = world.action_feed_pet(bram, cat.id)
    assert ok and cat.energy == 45
    # Move Bram away → the gate rejects feeding from afar.
    bram.location = "commons"
    err = _validate_world({"action": "feed_pet", "args": {"animal_id": cat.id}}, bram, world)
    assert err is not None and "not here" in err


# ──────────────────────────────────────────────────────────────────────────────
# (5) DECLINE + DEATH + GRIEF: an owned pet declines, dies at 0, and the OWNER
#     gets a guaranteed grief reflection (+ a pet_death importance boost).
# ──────────────────────────────────────────────────────────────────────────────

def test_owned_pet_declines_each_turn():
    world = _world(pet_energy_decay=3)
    runtime = _animal_runtime(world)
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Mittens", location="plaza")
    cat.energy = 100
    world.action_adopt(vesper, cat.id)
    asyncio.run(runtime.act(cat, world, tick=1))
    assert cat.energy == 97, "an owned pet loses pet_energy_decay each of its turns"


def test_owned_pet_dies_at_zero_and_owner_writes_a_grief_reflection():
    # A steep decay forces death quickly so the test stays deterministic + fast.
    world = _world(pet_energy_decay=100)
    runtime = _animal_runtime(world)
    vesper = world.agents["agent_vesper"]
    cat = world.spawn_animal(species="cat", name="Whiskers", location="plaza")
    cat.energy = 100
    world.action_adopt(vesper, cat.id)

    collected: list[dict] = []
    for tick in range(3):
        collected += asyncio.run(runtime.act(cat, world, tick=tick))
        if not cat.alive:
            break

    assert not cat.alive and cat.energy == 0
    # The pet's death event names the owner (so the owner witnesses + accumulates).
    died = [e for e in collected if e.get("kind") == "animal_died"]
    assert died, "an owned pet at energy 0 must emit animal_died"
    assert died[0]["payload"]["owner_id"] == vesper.id
    assert died[0].get("target_id") == vesper.id

    # THE BEAT — a guaranteed grief reflection ATTRIBUTED TO THE OWNER, matching
    # the existing reflection event shape (kind:"reflection", payload{text,importance}).
    grief = [e for e in collected if e.get("kind") == "reflection"]
    assert grief, "an owned pet's death must emit a grief reflection"
    g = grief[0]
    assert g["actor_id"] == vesper.id
    assert g["payload"]["text"]
    assert "importance" in g["payload"]
    assert "Whiskers" in g["payload"]["text"] and "Vesper" in g["payload"]["text"]


def test_pet_death_boosts_the_owners_reflection_accumulator():
    # An animal_died carrying payload.owner_id pulls the owner's next LLM turn so
    # they may ADD their own words to the guaranteed grief reflection.
    assert "pet_death" in _IMPORTANCE_WEIGHTS
    world = _world()
    runtime = _agent_runtime(world)
    vesper = world.agents["agent_vesper"]
    runtime.push_event({
        "kind": "animal_died", "actor_id": "animal_x", "target_id": vesper.id,
        "tick": 5, "payload": {"owner_id": vesper.id, "name": "Mittens"},
    })
    assert runtime._importance.get(vesper.id, 0.0) >= _IMPORTANCE_WEIGHTS["pet_death"]


# ──────────────────────────────────────────────────────────────────────────────
# (6) UNOWNED animals do NOT decline and still wander.
# ──────────────────────────────────────────────────────────────────────────────

def test_unowned_animal_does_not_decline():
    # A decay steep enough to obliterate an OWNED pet in one turn — an unowned
    # animal must be wholly immune to it. (Its energy may still drift UP via the
    # `nap` reflex; the decay simply never applies, so it never drops/dies.)
    world = _world(pet_energy_decay=100)
    runtime = _animal_runtime(world)
    stray = world.spawn_animal(species="dog", name="Stray", location="plaza")
    stray.energy = 50
    for tick in range(5):
        asyncio.run(runtime.act(stray, world, tick=tick))
        assert stray.alive, "an unowned animal must never decline to death"
        assert stray.energy >= 50, "the pet decay must never apply to an unowned animal"


def test_unowned_animal_still_wanders():
    world = _world()
    runtime = _animal_runtime(world)
    stray = world.spawn_animal(species="dog", name="Stray", location="plaza")
    assert stray.owner_id is None
    # An unowned animal's wander is the ordinary free wander (no owner to pin to):
    # it moves to the other known place, deterministically.
    runtime._apply(stray, "wander", {})
    assert stray.location == "commons", "an unowned animal must still wander freely"

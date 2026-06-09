"""
W8 gate tests — LLM-driven cat & dog chaos animals (EM-064) and the free-scale
guarantees that keep them cheap.

Contracts under test:
  - contracts/world-model.md §W8 / EM-064 — animal entity (actor_type="animal"),
    NO credits (invariant 7), species-driven reflex + occasional LLM decision.
  - contracts/action-protocol — animal actions (nap / steal_food / arson / …) and
    the is_chaotic tagging surfaced on animal_action events.
  - contracts/providers.md (free-scale) — animals act on a slow cadence and only
    SOMETIMES use the LLM; an unavailable model_profile degrades to reflex-only
    with ZERO router calls.
  - api: snapshot.animals present; animal_spawned / animal_action / llm_call events.

Deterministic and offline, following tests/test_w6.py / test_w7.py: a counting
mock provider drives the animal LLM path so router calls can be asserted exactly,
and async loop turns are run via asyncio.run (the test_w7 idiom). This file
supersedes the ad-hoc backend/_animal_selfcheck.py scratch harness.
"""
from __future__ import annotations

import asyncio
import json

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import (
    WorldParams, AnimalParams, ModelProfile, WorldConfig, AnimalSeed,
)
from petridish.engine.loop import TickLoop
from petridish.agents.runtime import AgentRuntime
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Helpers (a counting provider + a deterministic world builder)
# ──────────────────────────────────────────────────────────────────────────────

class CountingMock:
    """Records every chat() call and returns a scripted animal action, so the
    animal LLM path is exercised deterministically and router calls are countable."""
    name = "gemini-flash"
    color = "#3498db"
    last_routed_via = "gemini-flash"
    last_usage = {"input_tokens": 11, "output_tokens": 7, "latency_ms": 1.0,
                  "finish_reason": "stop", "cached": False}

    def __init__(self, response):
        self.calls = 0
        self._response = response

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        return self._response


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
        PlaceState(id="commons", name="Commons", x=500, y=750, kind="wild"),
    ]


def _profiles():
    # gemini-flash is a mock-adapter profile so profile.available() is True (the
    # free-scale gate keys on availability); a CountingMock override counts calls.
    return [
        ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71"),
        ModelProfile(name="gemini-flash", adapter="mock", model_id="gemini-2.0-flash",
                     color="#3498db"),
    ]


def _build(params, animal_response=None, agent_profile="mock"):
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile=agent_profile,
                   location="plaza", energy=100.0, credits=10),
        AgentState(id="agent_bram", name="Bram", personality="", profile=agent_profile,
                   location="plaza", energy=100.0, credits=10),
    ]
    world = World(params=params, places=_places(), agents=agents)
    overrides = {}
    counting = None
    if animal_response is not None:
        counting = CountingMock(animal_response)
        overrides["gemini-flash"] = counting
    router = Router(_profiles(), adapter_overrides=overrides or None, cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    events = []
    loop = TickLoop(world, runtime, repo, router, broadcaster=lambda m: events.append(m))
    router.inject_world(world)
    return world, router, loop, repo, counting, events


def _animal_params(**overrides) -> WorldParams:
    base = dict(energy_decay_per_turn=0.0, death_after_zero_turns=99, turns_per_day=999)
    animals = AnimalParams(
        enabled=True,
        act_every_n_ticks=overrides.pop("act_every_n_ticks", 1),
        llm_chance=overrides.pop("llm_chance", 0.0),
        model_profile=overrides.pop("model_profile", "gemini-flash"),
    )
    base.update(overrides)
    return WorldParams(animals=animals, **base)


async def _drive(loop, world, n):
    for _ in range(n):
        agent = world.next_agent()
        await loop._execute_turn(agent)


# ──────────────────────────────────────────────────────────────────────────────
# (a) Seed spawn: snapshot.animals present, NO credits (inv 7), animal_spawned
# ──────────────────────────────────────────────────────────────────────────────

def test_seed_animals_spawn_into_snapshot_without_credits():
    p = _animal_params(act_every_n_ticks=3, llm_chance=0.0)
    world, router, loop, repo, _, events = _build(p)
    cfg = WorldConfig(world=p, places=[], agents=[],
                      animals=[AnimalSeed("cat", "Mochi", "plaza"),
                               AnimalSeed("dog", "Biscuit", "commons")])
    loop.init_run(cfg)

    snap = world.to_snapshot()
    assert "animals" in snap, "snapshot missing animals"
    assert sorted(a["name"] for a in snap["animals"]) == ["Biscuit", "Mochi"]
    # Invariant 7: animals carry NO credits.
    assert all("credits" not in a for a in snap["animals"])

    spawned = [e for e in events if e.get("kind") == "animal_spawned"]
    assert len(spawned) == 2
    assert all(e["actor_type"] == "animal" for e in spawned)


# ──────────────────────────────────────────────────────────────────────────────
# (b) Free-scale: reflex ticks make ZERO router calls
# ──────────────────────────────────────────────────────────────────────────────

def test_reflex_ticks_make_zero_router_calls():
    p = _animal_params(act_every_n_ticks=1, llm_chance=0.0)
    world, router, loop, repo, counting, _ = _build(
        p, animal_response=json.dumps({"action": "nap", "args": {}}))
    cfg = WorldConfig(world=p, places=[], agents=[],
                      animals=[AnimalSeed("cat", "Mochi", "plaza"),
                               AnimalSeed("dog", "Biscuit", "commons")])
    loop.init_run(cfg)

    asyncio.run(_drive(loop, world, 30))
    assert counting.calls == 0, f"reflex ticks made {counting.calls} router calls (must be 0)"


# ──────────────────────────────────────────────────────────────────────────────
# (c) An LLM tick emits animal_action + an llm_call tagged actor_type=animal
# ──────────────────────────────────────────────────────────────────────────────

def test_llm_tick_emits_animal_action_and_tagged_llm_call():
    p = _animal_params(act_every_n_ticks=1, llm_chance=1.0)
    arson = json.dumps({"animal_thought": "burn it", "action": "arson",
                        "args": {"building_id": "bld_x"}})
    world, router, loop, repo, counting, events = _build(p, animal_response=arson)
    cfg = WorldConfig(world=p, places=[], agents=[], animals=[AnimalSeed("cat", "Mochi", "plaza")])
    loop.init_run(cfg)
    world.buildings["bld_x"] = Building(id="bld_x", name="Clocktower", kind="clocktower",
                                        location="plaza", status="operational", health=100)
    events.clear()

    asyncio.run(_drive(loop, world, 1))

    aa = [e for e in events if e.get("kind") == "animal_action"]
    lc = [e for e in events if e.get("kind") == "llm_call" and e.get("actor_type") == "animal"]
    assert aa and aa[0]["actor_type"] == "animal", "no animal_action tagged animal"
    assert aa[0]["is_chaotic"] is True, "arson must be is_chaotic"
    assert lc, "no animal-tagged llm_call event"
    assert lc[0]["payload"]["gen_ai.usage.input_tokens"] == 11, "llm_call missing OTel usage"
    assert counting.calls == 1, f"acted LLM tick made {counting.calls} calls (must be exactly 1)"


# ──────────────────────────────────────────────────────────────────────────────
# (d) Animal arson flips a building to damaged via the W7 structure path
# ──────────────────────────────────────────────────────────────────────────────

def test_animal_arson_damages_building_via_w7_path():
    p = _animal_params(act_every_n_ticks=1, llm_chance=1.0)
    arson = json.dumps({"animal_thought": "burn it", "action": "arson",
                        "args": {"building_id": "bld_x"}})
    world, router, loop, repo, counting, events = _build(p, animal_response=arson)
    cfg = WorldConfig(world=p, places=[], agents=[], animals=[AnimalSeed("cat", "Mochi", "plaza")])
    loop.init_run(cfg)
    world.buildings["bld_x"] = Building(id="bld_x", name="Clocktower", kind="clocktower",
                                        location="plaza", status="operational", health=100)
    events.clear()

    asyncio.run(_drive(loop, world, 1))

    b = world.buildings["bld_x"]
    assert b.status in ("damaged", "destroyed"), f"building not damaged by arson: {b.status}"
    assert 0 <= b.health <= 100, f"health out of clamp: {b.health}"
    scc = [e for e in events if e.get("kind") == "structure_state_changed"]
    assert scc and scc[0]["payload"]["to"] in ("damaged", "destroyed")


# ──────────────────────────────────────────────────────────────────────────────
# (e) Invariant 7: an animal's steal_food moves NO credits
# ──────────────────────────────────────────────────────────────────────────────

def test_animal_steal_food_moves_no_credits():
    p = _animal_params(act_every_n_ticks=1, llm_chance=1.0)
    steal = json.dumps({"animal_thought": "snack!", "action": "steal_food",
                        "args": {"target": "agent_ada"}})
    world, router, loop, repo, counting, events = _build(p, animal_response=steal)
    cfg = WorldConfig(world=p, places=[], agents=[], animals=[AnimalSeed("dog", "Biscuit", "plaza")])
    loop.init_run(cfg)

    asyncio.run(_drive(loop, world, 6))

    aa = [e for e in events if e.get("kind") == "animal_action"
          and e["payload"]["action"] == "steal_food"]
    assert aa, "no steal_food animal_action emitted"
    assert all("credits_delta" not in e.get("payload", {}) for e in aa), \
        "steal_food must not carry a credits delta (invariant 7)"


# ──────────────────────────────────────────────────────────────────────────────
# (free-scale) An unavailable model_profile degrades to reflex-only, zero calls
# ──────────────────────────────────────────────────────────────────────────────

def test_unavailable_profile_falls_back_to_reflex_only():
    p = _animal_params(act_every_n_ticks=1, llm_chance=1.0, model_profile="nonexistent")
    world, router, loop, repo, _, events = _build(
        p, animal_response=json.dumps({"action": "nap", "args": {}}))
    cfg = WorldConfig(world=p, places=[], agents=[], animals=[AnimalSeed("cat", "M", "plaza")])
    loop.init_run(cfg)
    events.clear()

    asyncio.run(_drive(loop, world, 5))

    lc = [e for e in events if e.get("kind") == "llm_call" and e.get("actor_type") == "animal"]
    aa = [e for e in events if e.get("kind") == "animal_action"]
    assert not lc, "unavailable profile must NOT produce an animal llm_call"
    assert aa, "animal should still act via reflex with an unavailable profile"

"""The travel_arrived feed card carries the traveler's model color.

`travel_arrived` is parked in the World's spawn outbox WITHOUT a profile_color (the
World has no router/legend). The loop enriches it from the arriving agent at flush
(`_flush_spawn_events`, mirroring `_sync_transplant_router`), so the arrival card wears
the traveler's color instead of the neutral fallback. This pins that enrichment.
"""
from __future__ import annotations

from petridish.config.loader import ModelProfile, WorldConfig, WorldParams
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _loop():
    params = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=20, energy_decay_per_turn=2.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=5,
    )
    places = [PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")]
    agents = [AgentState(id="agent_ada", name="Ada", personality="t", profile="mock",
                         location="plaza", energy=80.0, credits=20)]
    world = World(params=params, places=places, agents=agents)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": MockProvider(script=None)},
    )
    router.reassign("agent_ada", "mock")
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=AgentRuntime(world, router),
                    repo=SQLiteRepository(":memory:"), router=router,
                    broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world


def test_flush_enriches_travel_arrived_with_actor_color():
    loop, world = _loop()
    emitted: list[dict] = []
    loop._emit_event = lambda evt: emitted.append(evt)  # capture, skip persist/broadcast side effects

    # Park a color-less travel_arrived exactly as the World resolver does.
    world.pending_spawn_events.append({
        "kind": "travel_arrived", "actor_id": "agent_ada",
        "text": "Ada reached Riverton.",
        "payload": {"settlement": "stl_rivertown", "tick": 5},
    })
    loop._flush_spawn_events()

    arrived = [e for e in emitted if e.get("kind") == "travel_arrived"]
    assert arrived, "travel_arrived should be emitted by the flush"
    assert arrived[0].get("profile_color") == "#2ecc71", \
        "arrival card must carry the traveler's model color (enriched from the agent)"


def test_flush_leaves_a_prestamped_color_untouched():
    loop, world = _loop()
    emitted: list[dict] = []
    loop._emit_event = lambda evt: emitted.append(evt)

    world.pending_spawn_events.append({
        "kind": "travel_arrived", "actor_id": "agent_ada", "profile_color": "#abcdef",
        "text": "Ada reached Riverton.",
        "payload": {"settlement": "stl_rivertown", "tick": 5},
    })
    loop._flush_spawn_events()

    arrived = [e for e in emitted if e.get("kind") == "travel_arrived"]
    assert arrived and arrived[0]["profile_color"] == "#abcdef", \
        "an already-colored event is not overwritten"

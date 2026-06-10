"""PROTOTYPE — god-channel proclamation injection.

Proves the LOUD tier of the god↔town channel: a god proclamation is injected
into EVERY agent's prompt (so "name the town" actually reaches them), unlike the
opt-in billboard, and that proclamations round-trip through to_snapshot /
from_snapshot. Pure unit tests — no loop/provider/db; _assemble_context is
called directly, the same seam the W11b cognition tests pin.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )


def _world() -> World:
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id="ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
        # Bo is at the market — nowhere near the plaza billboard. A proclamation
        # must still reach him; an opt-in billboard note never would.
        AgentState(id="bo", name="Bo", personality="", profile="mock",
                   location="market", energy=80.0, credits=20),
    ]
    return World(params=_params(), places=places, agents=agents)


def _system_prompt(world: World, agent: AgentState) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def test_no_proclamation_means_no_block():
    world = _world()
    assert world.active_proclamation() is None
    for agent in world.agents.values():
        assert "THE GOD HAS PROCLAIMED" not in _system_prompt(world, agent)


def test_proclamation_reaches_every_agent_regardless_of_location():
    world = _world()
    evt = world.post_proclamation_as_god("Decide on a name for this town.")

    # The god's word rides EVERY agent's prompt — including Bo at the market.
    for agent in world.agents.values():
        sp = _system_prompt(world, agent)
        assert "📜 THE GOD HAS PROCLAIMED" in sp
        assert "Decide on a name for this town." in sp

    # The emitted event is the god-ink feed line.
    assert evt["kind"] == "proclamation_posted"
    assert evt["actor_type"] == "god"
    assert evt["payload"]["text"] == "Decide on a name for this town."
    assert world.active_proclamation()["text"] == "Decide on a name for this town."


def test_newest_proclamation_is_the_active_decree():
    world = _world()
    world.post_proclamation_as_god("First decree.")
    world.post_proclamation_as_god("Second decree supersedes it.")

    sp = _system_prompt(world, world.agents["ada"])
    assert "Second decree supersedes it." in sp
    assert "First decree." not in sp
    assert world.active_proclamation()["text"] == "Second decree supersedes it."


def test_proclamations_round_trip_through_snapshot():
    world = _world()
    world.tick = 7
    world.post_proclamation_as_god("Build a castle on the hill.")

    snap = world.to_snapshot()
    assert snap["proclamations"][0]["text"] == "Build a castle on the hill."

    restored = World.from_snapshot(snap, params=_params())
    assert restored.to_snapshot()["proclamations"] == snap["proclamations"]
    assert restored.active_proclamation()["text"] == "Build a castle on the hill."

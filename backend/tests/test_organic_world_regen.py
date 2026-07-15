"""Organic-world reroll (feat/organic-world-regen).

`loop.reset()` gains a gated reroll: when `world.city.randomize_on_reset` is set,
a reset picks a FRESH city_seed + a fresh template from `template_pool` and rebuilds
the road graph, so every reset is a genuinely different city (roads + POI ring +
building scatter) instead of the byte-identical same-seed rebuild. With the flag OFF
(the default), reset is byte-identical to before — same seed, same template.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import (
    AgentConfig, ModelProfile, PlaceConfig, ProcgenParams, CityProfileParams,
    WorldConfig, WorldParams,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _params(city: CityProfileParams, procgen: ProcgenParams) -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=20, energy_decay_per_turn=2.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=5,
        city_seed=1337, city=city, procgen=procgen,
    )


def _loop(params: WorldParams):
    """A minimal TickLoop + a reset config carrying the same params, with places +
    an agent so reset (and procgen housing) have something to rebuild from."""
    places = [
        PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
        PlaceState(id="townhall", name="Hall", x=300, y=300, kind="governance"),
    ]
    agents = [AgentState(id="agent_ada", name="Ada", personality="t", profile="mock",
                         location="plaza", energy=80.0, credits=20)]
    world = World(params=params, places=places, agents=agents)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": MockProvider(script=None)},
    )
    router.reassign("agent_ada", "mock")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=SQLiteRepository(":memory:"),
                    router=router, broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    cfg = WorldConfig(
        world=params,
        places=[PlaceConfig(id="plaza", name="Plaza", x=500, y=500, kind="social"),
                PlaceConfig(id="townhall", name="Hall", x=300, y=300, kind="governance")],
        agents=[AgentConfig(name="Ada", personality="t", profile="mock", location="plaza")],
    )
    return loop, world, cfg


@pytest.mark.asyncio
async def test_reset_reroll_changes_seed_and_template():
    # Genesis is the GRID baseline with procgen OFF; the reroll turns both organic.
    params = _params(
        CityProfileParams(template="grid", randomize_on_reset=True,
                          template_pool=("pentagon", "radial", "ring")),
        ProcgenParams(enabled=False, seed=42),
    )
    loop, world, cfg = _loop(params)
    assert world.city_seed == 1337              # genesis untouched by the reroll
    assert world.city_graph.template == "grid"  # genesis is the deterministic grid

    seeds: set[int] = set()
    templates: set[str] = set()
    for _ in range(16):
        await loop.reset(cfg)
        seeds.add(world.city_seed)
        templates.add(world.city_graph.template)
        # every rolled template is a real off-grid plan the pool allows
        assert world.city_graph.template in ("pentagon", "radial", "ring")
        # the graph is actually rebuilt for that plan (non-grid ⇒ has nodes/edges)
        assert world.city_graph.nodes and world.city_graph.edges
        # the reroll switched POIs to the seeded organic ring (procgen forced ON +
        # re-seeded), replacing the hand-authored 2-place config town.
        assert cfg.world.procgen.enabled is True
        assert cfg.world.procgen.seed == world.city_seed
        assert "plaza" in world.places and len(world.places) > 2

    assert len(seeds) > 1, "reset must actually re-roll city_seed, not repeat it"
    assert 1337 not in seeds, "a reroll must leave the genesis seed behind"


@pytest.mark.asyncio
async def test_reset_is_deterministic_when_flag_off():
    """Flag OFF (default) ⇒ reset keeps the same seed + template (byte-identical)."""
    params = _params(
        CityProfileParams(template="grid", randomize_on_reset=False),
        ProcgenParams(enabled=False, seed=42),
    )
    loop, world, cfg = _loop(params)
    assert world.city_seed == 1337
    assert world.city_graph.template == "grid"

    for _ in range(3):
        await loop.reset(cfg)
        assert world.city_seed == 1337, "no reroll ⇒ seed is unchanged"
        assert world.city_graph.template == "grid", "no reroll ⇒ template unchanged"


def test_city_profile_parses_reroll_knobs():
    from petridish.config.loader import _parse_city_profile
    p = _parse_city_profile({"template": "radial", "randomize_on_reset": True,
                             "template_pool": ["pentagon", "radial", "ring", "grid"]})
    assert p.randomize_on_reset is True
    assert p.template_pool == ("pentagon", "radial", "ring", "grid")
    # a garbage / empty pool falls back to the default (never silently empty)
    q = _parse_city_profile({"template_pool": ["bogus", 42]})
    assert q.template_pool == CityProfileParams().template_pool
    # absent knobs ⇒ deterministic-reset defaults
    r = _parse_city_profile({"template": "grid"})
    assert r.randomize_on_reset is False

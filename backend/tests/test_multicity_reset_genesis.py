"""reset() must re-seed the genesis settlement AND re-home the fresh cast even when
a settlement from a prior run survived.

The restart-then-reset bug: reset rebuilds the agent roster (new ids) but used to
leave `world.settlements` intact, so `seed_genesis_settlement`'s idempotency guard
(settlements non-empty ⇒ no-op) skipped re-seeding — the fresh cast ended up with
`home_settlement_id = None` and the surviving settlement's `members` pointed at
replaced ids. reset now clears settlements like it clears factions.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import (
    AgentConfig, ModelProfile, PlaceConfig, SettlementParams, WorldConfig, WorldParams,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _loop_with_settlements():
    params = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=20, energy_decay_per_turn=2.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=5,
        settlements=SettlementParams(enabled=True),
    )
    places = [PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
              PlaceState(id="townhall", name="Hall", x=300, y=300, kind="governance")]
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
    cfg = WorldConfig(
        world=params,
        places=[PlaceConfig(id="plaza", name="Plaza", x=500, y=500, kind="social"),
                PlaceConfig(id="townhall", name="Hall", x=300, y=300, kind="governance")],
        agents=[AgentConfig(name="Ada", personality="t", profile="mock", location="plaza"),
                AgentConfig(name="Bram", personality="t", profile="mock", location="plaza")],
    )
    return loop, world, cfg


@pytest.mark.asyncio
async def test_reset_reseeds_genesis_and_rehomes_every_agent_across_repeats():
    # init_run already seeds a genesis settlement (the pre-existing state a reset
    # must not be fooled by). Reset repeatedly and assert every pass re-homes.
    loop, world, cfg = _loop_with_settlements()
    for i in range(3):
        await loop.reset(cfg)
        # exactly ONE genesis settlement, freshly minted (no stale survivors)
        assert len(world.settlements) == 1, f"reset {i}: stale settlements survived"
        sid, s = next(iter(world.settlements.items()))
        assert s["founder_id"] == "genesis"
        # every CURRENT agent points home at the genesis settlement
        assert world.agents
        for a in world.agents.values():
            assert a.home_settlement_id == sid, f"reset {i}: {a.name} left homeless"
        # members == the live cast exactly (no replaced ids linger)
        assert sorted(s["members"]) == sorted(world.agents), f"reset {i}: stale members"


@pytest.mark.asyncio
async def test_reset_settlements_disabled_stays_empty_and_unhomed():
    # OFF path: no genesis, no homes, byte-identical to pre-settlements.
    loop, world, cfg = _loop_with_settlements()
    cfg.world.settlements.enabled = False
    world.params.settlements.enabled = False
    await loop.reset(cfg)
    assert world.settlements == {}
    assert all(a.home_settlement_id is None for a in world.agents.values())

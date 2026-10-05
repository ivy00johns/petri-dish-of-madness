"""EM-339 — the contact honesty ledger belongs to exactly ONE run.

Root cause (run 23, 2026-10-04): ``TickLoop.reset`` rebuilt the world
in-place but left ``contact_ledger`` and ``contact_made`` intact, so the
fresh run inherited the prior run's crossings (run 23 shipped run 22's
131-crossing ledger on every /api surface AND inside its own snapshots)
while run 22's one-shot ``contact_made`` latch blocked the fresh world's
own first-contact stamp. The DB event log was the only ground truth.

Fix: ``World.reset_contact_state()`` (the ONE fresh-run seam — loop.reset
calls it), an owning-run stamp ``World.contact_run_id`` (init_run/reset
stamp the fresh row id; forks deliberately keep the parent stamp), and the
stamp serialized inside the ledger snapshot block only-when-set.
"""
from __future__ import annotations

import copy

import pytest

from petridish.config.loader import (
    AgentConfig, ModelProfile, PlaceConfig, SettlementParams, WorldConfig,
    WorldParams,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider

# A stale ledger shaped exactly like run 22's survivor (the payload that
# masqueraded as run-23 data).
_STALE_LEDGER = {
    "crossings": 131,
    "by_family": {
        "gemini": {"hops": 89, "mutated": 0},
        "llama": {"hops": 42, "mutated": 0},
    },
}
_STALE_MARKER = {
    "tick": 615,
    "agent_id": "agent_ada_728ec0",
    "from_settlement": "stl_a",
    "to_settlement": "stl_b",
}


def _loop():
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
    cfg = WorldConfig(
        world=params,
        places=[PlaceConfig(id="plaza", name="Plaza", x=500, y=500, kind="social"),
                PlaceConfig(id="townhall", name="Hall", x=300, y=300, kind="governance")],
        agents=[AgentConfig(name="Ada", personality="t", profile="mock", location="plaza"),
                AgentConfig(name="Bram", personality="t", profile="mock", location="plaza")],
    )
    return loop, world, cfg


def test_fresh_world_has_no_stamp_and_no_ledger():
    loop, world, cfg = _loop()
    assert world.contact_ledger == {}
    assert world.contact_made is None
    assert world.contact_run_id is None


@pytest.mark.asyncio
async def test_init_run_stamps_the_ledger_with_its_run_row():
    loop, world, cfg = _loop()
    loop.init_run(cfg)
    assert world.contact_run_id == loop._run_id
    assert world.contact_ledger == {}


@pytest.mark.asyncio
async def test_reset_clears_stale_ledger_marker_and_restamps():
    loop, world, cfg = _loop()
    loop.init_run(cfg)
    first_run = loop._run_id
    # Inject run-22-style survivors (what the pre-339 reset carried across).
    world.contact_ledger = copy.deepcopy(_STALE_LEDGER)
    world.contact_made = dict(_STALE_MARKER)
    world.contact_run_id = first_run

    await loop.reset(cfg)

    assert world.contact_ledger == {}, "stale ledger survived the reset"
    assert world.contact_made is None, "stale contact_made latch survived"
    fresh = loop._run_id
    assert fresh != first_run
    assert world.contact_run_id == fresh, "ledger not re-stamped with the fresh run"


@pytest.mark.asyncio
async def test_crossing_after_reset_scores_into_a_clean_ledger():
    # The run-23 symptom inverse: a hop recorded after the reset must land in
    # a fresh ledger, not on top of the prior run's counts.
    loop, world, cfg = _loop()
    loop.init_run(cfg)
    world.contact_ledger = copy.deepcopy(_STALE_LEDGER)
    await loop.reset(cfg)
    world._record_carriage(next(iter(world.agents)), mutated=True)
    assert world.contact_ledger["crossings"] == 1
    fam_rec = next(iter(world.contact_ledger["by_family"].values()))
    assert fam_rec == {"hops": 1, "mutated": 1}


def test_snapshot_roundtrip_preserves_the_stamp():
    _, world, _ = _loop()
    world.contact_ledger = copy.deepcopy(_STALE_LEDGER)
    world.contact_run_id = 7
    snap = world.to_snapshot()
    assert snap["contact_ledger"]["run_id"] == 7
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.contact_ledger == world.contact_ledger
    assert restored.contact_run_id == 7


def test_stampless_pre339_ledger_restores_without_a_stamp():
    # Additive: a pre-EM-339 archive (no run_id key) restores byte-identically
    # and reports no owning run.
    _, world, _ = _loop()
    snap = world.to_snapshot()
    snap["contact_ledger"] = copy.deepcopy(_STALE_LEDGER)
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.contact_ledger == _STALE_LEDGER
    assert restored.contact_run_id is None


def test_fresh_ledger_snapshot_stays_absent_and_restore_drops_the_stamp():
    # No crossings ⇒ no ledger key at all (the byte-identical path); and a
    # stamp without crossings does not survive restore (the ledger block owns
    # the stamp).
    _, world, _ = _loop()
    world.contact_run_id = 9
    snap = world.to_snapshot()
    assert "contact_ledger" not in snap
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.contact_run_id is None


def test_stamp_helper_explicit_none_clears_the_stamp():
    _, world, _ = _loop()
    world.stamp_contact_ledger_run(5)
    assert world.contact_run_id == 5
    world.stamp_contact_ledger_run(None)
    assert world.contact_run_id is None

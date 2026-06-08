"""
Regression tests for the TickLoop asyncio task lifecycle.

These exercise the loop's control surface (start/pause/step) the way the API
does — driving the background asyncio task — rather than calling the engine
directly. They cover the wave-gate bug:

  * step() did nothing before start() (no run task existed to consume it).
  * a stale step request poisoned the next start() into re-pausing after one turn.
"""
from __future__ import annotations

import asyncio

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _make_loop(interval: float = 0.02, agent_count: int = 3) -> tuple[TickLoop, World]:
    params = WorldParams(
        tick_interval_seconds=interval,
        energy_decay_per_turn=2.0,
        starting_energy=80.0,
        starting_credits=15,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=20,
        memory_window=5,
    )
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(
            id=f"agent_{i}",
            name=f"Agent{i}",
            personality="Test agent.",
            profile="mock",
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for i in range(agent_count)
    ]
    world = World(params=params, places=places, agents=agents)

    # Deterministic mock that always forages (mutates credits every turn).
    mock = MockProvider(script=[{"action": "forage", "args": {}}])
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock},
    )
    for a in agents:
        router.reassign(a.id, "mock")

    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)

    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop._run_id = 1  # avoid touching DB run setup
    return loop, world


async def _drain_task(loop: TickLoop) -> None:
    if loop._task and not loop._task.done():
        loop._task.cancel()
        try:
            await loop._task
        except asyncio.CancelledError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# step() before start()
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_step_advances_without_start():
    """N calls to step() (never calling start()) advance exactly N turns."""
    loop, world = _make_loop()
    try:
        assert world.tick == 0

        n = 5
        credits_before = [a.credits for a in world.agents.values()]
        for i in range(n):
            loop.step()
            # Yield to let the background task consume the step (poll on tick).
            target = i + 1
            for _ in range(100):
                await asyncio.sleep(0.005)
                if world.tick >= target:
                    break

        assert world.tick == n, f"expected tick={n}, got {world.tick}"
        # State mutated: at least one agent's credits changed (forage adds credits).
        credits_after = [a.credits for a in world.agents.values()]
        assert credits_after != credits_before
        # step() leaves the loop paused.
        assert loop.is_running() is False
        assert world.running is False
    finally:
        await _drain_task(loop)


@pytest.mark.asyncio
async def test_step_then_start_runs_continuously():
    """A leftover step must not poison start() into re-pausing after one turn."""
    loop, world = _make_loop(interval=0.02)
    try:
        # Step once before start (consumed → tick 1, paused).
        loop.step()
        for _ in range(100):
            await asyncio.sleep(0.005)
            if world.tick >= 1:
                break
        assert world.tick == 1
        assert loop.is_running() is False

        # Now start continuous running.
        loop.start()
        assert loop.is_running() is True
        await asyncio.sleep(0.4)

        assert world.tick > 1, f"continuous run stalled at tick {world.tick}"
        assert loop.is_running() is True
        assert world.running is True
    finally:
        await _drain_task(loop)


# ──────────────────────────────────────────────────────────────────────────────
# start()/pause()
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_advances_then_pause_stops():
    """start() runs continuously; pause() halts advancement."""
    loop, world = _make_loop(interval=0.02)
    try:
        loop.start()
        assert loop.is_running() is True
        await asyncio.sleep(0.3)

        tick_running = world.tick
        assert tick_running > 1, f"expected >1 ticks, got {tick_running}"

        loop.pause()
        assert loop.is_running() is False
        # Let any in-flight turn settle, then sample.
        await asyncio.sleep(0.1)
        tick_paused = world.tick
        await asyncio.sleep(0.3)

        assert world.tick == tick_paused, (
            f"loop kept advancing after pause: {tick_paused} -> {world.tick}"
        )
        assert world.running is False
    finally:
        await _drain_task(loop)


@pytest.mark.asyncio
async def test_step_advances_exactly_one_while_paused():
    """Each step advances exactly one turn and leaves running=false."""
    loop, world = _make_loop()
    try:
        loop.step()
        for _ in range(100):
            await asyncio.sleep(0.005)
            if world.tick >= 1:
                break
        assert world.tick == 1
        assert loop.is_running() is False

        # No spontaneous advancement while idle.
        await asyncio.sleep(0.2)
        assert world.tick == 1
    finally:
        await _drain_task(loop)

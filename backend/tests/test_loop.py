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


# ──────────────────────────────────────────────────────────────────────────────
# EM-226 — auto-pause on a sustained provider/network outage
# ──────────────────────────────────────────────────────────────────────────────

def _provider_fail_result(agent) -> dict:
    """An idle-fallback turn result whose reason is a provider_error (the shape
    AgentRuntime.run_turn returns when the call never reached a model)."""
    return {
        "kind": "parse_failure",
        "actor_id": agent.id,
        "profile": "mock",
        "profile_color": "#2ecc71",
        "text": f"{agent.name} failed to produce a valid action (idle fallback): provider_error: x",
        "payload": {
            "reason": 'provider_error: {"error":{"message":"All models exhausted.","type":"routing_error"}}',
        },
        "_trace": {
            "perceived": {"perceived_summary": None},
            "memory": {},
            "llm_attempts": [],
            "reasoning": {"reasoning": None, "perceived_summary": None, "memories_used": None},
            "action_chosen": {"chosen_tool": "idle", "args": {}, "tier": "llm"},
            "resolved": {"outcome": "failed", "state_deltas": {}},
        },
    }


def _ok_result(agent) -> dict:
    """A normal successful (reached-a-model) turn result."""
    return {
        "kind": "agent_action",
        "actor_id": agent.id,
        "profile": "mock",
        "profile_color": "#2ecc71",
        "text": f"{agent.name} foraged.",
        "payload": {"action": "forage"},
        "_trace": {
            "perceived": {"perceived_summary": "ok"},
            "memory": {},
            "llm_attempts": [],
            "reasoning": {"reasoning": "r", "perceived_summary": "ok", "memories_used": []},
            "action_chosen": {"chosen_tool": "forage", "args": {}, "tier": "llm"},
            "resolved": {"outcome": "ok", "state_deltas": {}},
        },
    }


def test_provider_error_reason_classifies():
    cls = TickLoop._provider_error_reason
    assert cls({"kind": "parse_failure", "payload": {"reason": "provider_error: z"}}) is not None
    # a content parse failure (a model DID answer with junk) is NOT a provider error
    assert cls({"kind": "parse_failure", "payload": {"reason": "no_json"}}) is None
    # a success is not a provider error
    assert cls({"kind": "agent_action", "payload": {}}) is None
    # _multi results are scanned too
    assert cls({"_multi": [{"kind": "parse_failure", "payload": {"reason": "provider_error: y"}}]}) is not None
    assert cls(None) is None


@pytest.mark.asyncio
async def test_auto_pauses_on_sustained_provider_errors():
    loop, world = _make_loop(agent_count=2)
    world.params.provider_error_pause_threshold = 3
    loop._paused = False  # simulate a running loop (we drive _execute_turn directly)
    world.running = True
    kinds: list[str] = []
    orig = loop._emit_event
    loop._emit_event = lambda evt: (kinds.append(evt.get("kind")), orig(evt))[1]  # type: ignore

    async def fail(agent):
        return _provider_fail_result(agent)
    loop._runtime.run_turn = fail  # type: ignore

    agent = next(iter(world.agents.values()))
    for _ in range(3):
        await loop._execute_turn(agent)

    assert loop._provider_error_streak >= 3
    assert loop._paused is True
    assert world.running is False
    assert "world_paused" in kinds
    # one-shot: another failing turn does not emit a second world_paused
    kinds.clear()
    await loop._execute_turn(agent)
    assert "world_paused" not in kinds
    await _drain_task(loop)


@pytest.mark.asyncio
async def test_streak_resets_when_a_turn_reaches_a_model():
    loop, world = _make_loop(agent_count=2)
    world.params.provider_error_pause_threshold = 3
    loop._paused = False
    world.running = True
    results = [
        _provider_fail_result, _provider_fail_result,
        _ok_result,                       # breaks the streak
        _provider_fail_result, _provider_fail_result,
    ]
    seq = iter(results)

    async def run(agent):
        return next(seq)(agent)
    loop._runtime.run_turn = run  # type: ignore

    agent = next(iter(world.agents.values()))
    for _ in range(len(results)):
        await loop._execute_turn(agent)

    # never hit 3-in-a-row, so never paused
    assert loop._paused is False
    assert loop._provider_error_streak == 2
    await _drain_task(loop)


@pytest.mark.asyncio
async def test_disabled_flag_never_auto_pauses_on_provider_errors():
    loop, world = _make_loop(agent_count=2)
    world.params.provider_error_pause_threshold = 2
    world.params.auto_pause_on_provider_errors = False
    loop._paused = False
    world.running = True

    async def fail(agent):
        return _provider_fail_result(agent)
    loop._runtime.run_turn = fail  # type: ignore

    agent = next(iter(world.agents.values()))
    for _ in range(5):
        await loop._execute_turn(agent)

    assert loop._paused is False  # flag off ⇒ keeps running (streak still tracked)
    assert loop._provider_error_streak >= 5
    await _drain_task(loop)


# ──────────────────────────────────────────────────────────────────────────────
# EM-226 network-down grace — auto-resume once connectivity returns
# ──────────────────────────────────────────────────────────────────────────────

from petridish.engine.loop import _PROVIDER_PROBE_EVERY


@pytest.mark.asyncio
async def test_auto_pause_arms_the_provider_resume_flag():
    """The EM-226 provider-error pause arms the auto-resume flag."""
    loop, world = _make_loop(agent_count=2)
    world.params.provider_error_pause_threshold = 3
    loop._paused = False
    world.running = True

    async def fail(agent):
        return _provider_fail_result(agent)
    loop._runtime.run_turn = fail  # type: ignore

    agent = next(iter(world.agents.values()))
    for _ in range(3):
        await loop._execute_turn(agent)

    assert loop._paused is True
    assert loop._auto_paused_for_provider is True
    await _drain_task(loop)


@pytest.mark.asyncio
async def test_auto_resume_probes_then_resumes_on_recovery():
    loop, world = _make_loop(agent_count=2)
    loop._paused = True
    world.running = False
    loop._auto_paused_for_provider = True
    loop._provider_error_streak = 8
    loop._provider_pause_emitted = True
    loop._provider_probe_skips = 0

    kinds: list[str] = []
    orig = loop._emit_event
    loop._emit_event = lambda evt: (kinds.append(evt.get("kind")), orig(evt))[1]  # type: ignore

    calls = {"n": 0}
    async def probe():
        calls["n"] += 1
        return True
    loop._router.probe_connectivity = probe  # type: ignore

    # Counter-gated: the first _PROVIDER_PROBE_EVERY-1 polls neither probe nor resume.
    for _ in range(_PROVIDER_PROBE_EVERY - 1):
        assert await loop._maybe_auto_resume() is False
    assert calls["n"] == 0
    assert loop._paused is True

    # The cadence poll probes and, on success, resumes + re-arms the one-shot pause.
    assert await loop._maybe_auto_resume() is True
    assert calls["n"] == 1
    assert loop._paused is False
    assert world.running is True
    assert loop._auto_paused_for_provider is False
    assert loop._provider_error_streak == 0
    assert loop._provider_pause_emitted is False
    assert "world_resumed" in kinds
    await _drain_task(loop)


@pytest.mark.asyncio
async def test_auto_resume_stays_paused_while_probe_fails():
    loop, world = _make_loop(agent_count=2)
    loop._paused = True
    world.running = False
    loop._auto_paused_for_provider = True

    async def probe():
        return False
    loop._router.probe_connectivity = probe  # type: ignore

    for _ in range(_PROVIDER_PROBE_EVERY * 2):
        assert await loop._maybe_auto_resume() is False
    assert loop._paused is True
    assert loop._auto_paused_for_provider is True
    await _drain_task(loop)


@pytest.mark.asyncio
async def test_auto_resume_noop_when_paused_for_other_reason():
    """A manual pause (not a provider outage) must never be auto-resumed."""
    loop, world = _make_loop(agent_count=2)
    loop._paused = True
    world.running = False
    loop._auto_paused_for_provider = False

    probed = {"n": 0}
    async def probe():
        probed["n"] += 1
        return True
    loop._router.probe_connectivity = probe  # type: ignore

    for _ in range(_PROVIDER_PROBE_EVERY + 5):
        assert await loop._maybe_auto_resume() is False
    assert probed["n"] == 0
    assert loop._paused is True
    await _drain_task(loop)


# ──────────────────────────────────────────────────────────────────────────────
# _run() turn guard — an unhandled turn exception must pause, not silently kill
# the tick task (the old bug: the task died with the exception while
# /api/health kept reporting running=true).
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_turn_crash_pauses_instead_of_killing_the_task():
    loop, world = _make_loop(interval=0.01)
    msgs: list[dict] = []
    loop._broadcaster = msgs.append  # type: ignore

    orig_run_turn = loop._runtime.run_turn

    async def boom(agent):
        raise RuntimeError("synthetic turn crash")
    loop._runtime.run_turn = boom  # type: ignore

    try:
        loop.start()
        for _ in range(200):
            await asyncio.sleep(0.005)
            if loop._paused:
                break

        # The task survived the crash (old bug: it died with the exception).
        assert loop._task is not None and not loop._task.done(), (
            "tick task died on a turn exception instead of pausing"
        )
        # ... and the world was auto-paused so /api/health tells the truth.
        assert loop._paused is True
        assert world.running is False
        # An internal-error crash must NOT arm the EM-226 connectivity probe:
        # it won't heal with the network, so no auto-resume.
        assert loop._auto_paused_for_provider is False

        # A best-effort world_paused {reason: internal_error} was emitted.
        paused = [m for m in msgs
                  if m.get("type") == "event" and m.get("kind") == "world_paused"]
        assert paused, "no world_paused event for the crashed turn"
        assert paused[-1]["payload"]["reason"] == "internal_error"
        assert paused[-1]["payload"]["auto_paused"] is True
        # The pause broadcast a fresh world_state carrying running=False.
        states = [m for m in msgs if m.get("type") == "world_state"]
        assert states and states[-1]["running"] is False

        # The loop is not just alive but FUNCTIONAL: with a healthy runtime
        # back, a step advances a turn exactly as before the crash.
        loop._runtime.run_turn = orig_run_turn  # type: ignore
        tick_before = world.tick
        loop.step()
        for _ in range(200):
            await asyncio.sleep(0.005)
            if world.tick > tick_before:
                break
        assert world.tick == tick_before + 1
    finally:
        await _drain_task(loop)


@pytest.mark.asyncio
async def test_turn_crash_still_resolves_step_waiters():
    """A crash during a queued step must not hang the step_and_wait caller."""
    loop, world = _make_loop()

    async def boom(agent):
        raise RuntimeError("synthetic turn crash")
    loop._runtime.run_turn = boom  # type: ignore

    try:
        tick = await asyncio.wait_for(loop.step_and_wait(timeout=2.0), timeout=3.0)
        assert tick == world.tick  # resolved, not timed out/hung
        assert loop._task is not None and not loop._task.done()
        assert loop._paused is True
    finally:
        await _drain_task(loop)


@pytest.mark.asyncio
async def test_turn_cancellation_still_propagates_through_the_guard():
    """reset/fork teardown cancels the task THROUGH the awaited turn — the
    guard must re-raise CancelledError, never swallow it into a pause."""
    loop, world = _make_loop()
    started = asyncio.Event()

    async def hang(agent):
        started.set()
        await asyncio.Event().wait()  # parks until cancelled
    loop._runtime.run_turn = hang  # type: ignore

    loop.start()
    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert loop._task is not None
    loop._task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await loop._task
    assert loop._task.done()

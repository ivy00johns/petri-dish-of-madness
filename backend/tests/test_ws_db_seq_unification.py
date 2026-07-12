"""
WS/DB seq unification regression (likely EM-305 root) — a live WS `event`
message's `seq` IS the persisted `events.seq` (the AUTOINCREMENT event_id).

The loop used to stamp a per-boot counter as the broadcast `seq` and DISCARD
save_event's returned rowid — two id spaces for the same event. Every backend
restart/fork restarted the counter at 0, so clients that dedupe/evict live
events against REST-fetched history (which carries the DB event_ids) dropped
fresh events as "already seen": the confirmed feed-freeze/flicker mechanism.

Invariants pinned here:
  1. Every broadcast `event` message carries the seq of ITS OWN persisted row
     (matched on kind + text) — one id space, live == REST.
  2. A second TickLoop over the SAME repo (i.e. a backend restart or fork)
     broadcasts seqs that CONTINUE past the first boot's high-water mark —
     never a fresh 1..n that collides with history.
  3. The headless runner (petridish.run) stamps the same DB event_id on the
     messages it prints/pushes.

`world_state` snapshot messages are OUT of scope: they are ephemeral,
never-persisted projections and keep the per-boot counter.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    AgentConfig,
    ModelProfile,
    PlaceConfig,
    WorldConfig,
    WorldParams,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        energy_decay_per_turn=2.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=20,
        memory_window=5,
    )
    base.update(overrides)
    return WorldParams(**base)


def _make_loop(
    repo: SQLiteRepository,
    broadcasts: list[dict],
    *,
    agent_count: int = 2,
) -> tuple[TickLoop, World]:
    """A fresh World/Router/Runtime/TickLoop around a CALLER-OWNED repo, so two
    loops can share one DB (the restart/fork scenario)."""
    params = _params()
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

    mock = MockProvider(script=[{"action": "forage", "args": {}}])
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock},
    )
    for a in agents:
        router.reassign(a.id, "mock")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)

    loop = TickLoop(
        world=world, runtime=runtime, repo=repo, router=router,
        broadcaster=broadcasts.append,
    )
    loop._run_id = 1  # shared run: rowids continue in the same id space
    return loop, world


async def _run_turns(loop: TickLoop, world: World, n: int) -> None:
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)


def _ws_events(broadcasts: list[dict]) -> list[dict]:
    return [m for m in broadcasts if m.get("type") == "event"]


# ──────────────────────────────────────────────────────────────────────────────
# 1. One id space: broadcast seq == the persisted row's seq.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_event_seq_is_the_db_event_id():
    repo = SQLiteRepository(":memory:")
    broadcasts: list[dict] = []
    loop, world = _make_loop(repo, broadcasts)

    await _run_turns(loop, world, 4)

    rows = repo.get_events(1, order="asc")
    ws = _ws_events(broadcasts)
    assert rows and ws
    # Every emitted event was both persisted and broadcast, 1:1.
    assert len(ws) == len(rows)

    by_seq = {r["seq"]: r for r in rows}
    for msg in ws:
        row = by_seq.get(msg["seq"])
        assert row is not None, (
            f"broadcast seq {msg['seq']} ({msg['kind']}) has no persisted row — "
            f"two id spaces for one event"
        )
        # And it is THIS event's row, not a colliding neighbor.
        assert row["kind"] == msg["kind"], (
            f"seq {msg['seq']}: broadcast kind {msg['kind']!r} vs "
            f"persisted kind {row['kind']!r}"
        )
        assert row["text"] == msg["text"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. Restart/fork: the live stream continues the DB id space, never resets.
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restarted_backend_continues_the_id_space():
    repo = SQLiteRepository(":memory:")

    boot1: list[dict] = []
    loop1, world1 = _make_loop(repo, boot1)
    await _run_turns(loop1, world1, 3)
    seqs1 = {m["seq"] for m in _ws_events(boot1)}
    assert seqs1
    high_water = max(seqs1)

    # "Restart": a brand-new TickLoop (fresh per-boot counter) on the same DB.
    boot2: list[dict] = []
    loop2, world2 = _make_loop(repo, boot2)
    await _run_turns(loop2, world2, 2)
    seqs2 = {m["seq"] for m in _ws_events(boot2)}
    assert seqs2

    # The old bug: boot 2 re-issued 1..n, colliding with boot 1's ids — clients
    # deduping on seq silently dropped every live event after the restart.
    assert not (seqs1 & seqs2), (
        f"restarted loop reused live seq ids {sorted(seqs1 & seqs2)[:5]}…"
    )
    assert min(seqs2) > high_water, (
        f"restarted loop's first live seq {min(seqs2)} did not continue past "
        f"the persisted high-water mark {high_water}"
    )
    # And boot 2's messages still match their own persisted rows.
    by_seq = {r["seq"]: r for r in repo.get_events(1, order="asc")}
    for msg in _ws_events(boot2):
        assert by_seq[msg["seq"]]["kind"] == msg["kind"]


# ──────────────────────────────────────────────────────────────────────────────
# 3. The headless runner stamps the DB event_id too (run.py parity).
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_headless_runner_stamps_db_event_ids(monkeypatch):
    import petridish.run as run_mod

    cfg = WorldConfig(
        world=_params(db_path=":memory:"),
        places=[
            PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social"),
            PlaceConfig(id="market", name="Market", x=10, y=0, kind="work"),
        ],
        agents=[
            AgentConfig(name="Ada", personality="t", profile="mock", location="market"),
            AgentConfig(name="Bram", personality="t", profile="mock", location="market"),
        ],
        profiles=[ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
    )
    monkeypatch.setattr("petridish.config.loader.load_config", lambda **kw: cfg)

    captured: dict = {}
    real_build_world = run_mod.build_world

    def spy_build_world(c):
        world, router, runtime, repo = real_build_world(c)
        pushed: list[dict] = []
        real_push = runtime.push_event
        def spy_push(evt):
            pushed.append(evt)
            return real_push(evt)
        runtime.push_event = spy_push  # type: ignore[method-assign]
        captured["repo"] = repo
        captured["pushed"] = pushed
        return world, router, runtime, repo

    monkeypatch.setattr(run_mod, "build_world", spy_build_world)

    await run_mod.run_headless(ticks=3, profile_override=None)

    repo = captured["repo"]
    rows = repo.get_events(1, order="asc")
    assert rows
    by_seq = {r["seq"]: r for r in rows}
    pushed_events = [e for e in captured["pushed"] if e.get("type") == "event"]
    assert pushed_events
    for msg in pushed_events:
        row = by_seq.get(msg["seq"])
        assert row is not None, (
            f"headless message seq {msg['seq']} ({msg.get('kind')}) is not a DB "
            f"event_id (old per-tick counter?)"
        )
        assert row["kind"] == msg.get("kind")
        assert row["text"] == msg.get("text")

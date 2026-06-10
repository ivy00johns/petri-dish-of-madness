"""EM-145 — god-voice delivery made legible.

The user-reported failure mode: whispers and billboard replies were posted,
and NOTHING in the feed ever indicated an agent heard them. Two fixes under
test here:

  1. `run_turn` (not the silent prompt builder) consumes the god's voice and
     emits a `god_voice_heard` feed event per channel — whisper deliveries
     ("✦ {name} hears the whisper") and god billboard posts read by an agent
     standing at the board ("📌 {name} reads the god's note on the board").
     Delivery is legible even when the turn fails to parse: the voice rode
     the prompt either way.
  2. God billboard posts now reach agents AT a billboard place once each
     (consume-once via the runtime's per-agent seen high-water), instead of
     waiting for a voluntary read_billboard that never came.

Free-scale law: context injection + plain events — zero extra LLM calls
(the duck router's call count pins it).

Snapshot persistence of queued whispers (the hot-reload loss mode) is pinned
in test_god_console.py::test_pending_whispers_survive_the_snapshot_round_trip.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import AgentState, PlaceState, World
from petridish.config.loader import WorldParams
from petridish.agents.runtime import AgentRuntime

_IDLE_JSON = '{"action": "idle", "args": {}}'


class _DuckRouter:
    """Minimal duck-typed router (the test_lane_health idiom): returns a canned
    response and counts chat calls so the free-scale law stays pinned."""

    def __init__(self, response: str = _IDLE_JSON):
        self.response = response
        self.calls = 0

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_messages = messages
        return self.response

    def last_usage(self, profile_name):
        return None

    def last_routed_via(self, profile_name):
        return None


def _world() -> World:
    params = WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id="ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
        AgentState(id="bo", name="Bo", personality="", profile="mock",
                   location="market", energy=80.0, credits=20),
    ]
    return World(params=params, places=places, agents=agents)


def _events(result: dict) -> list[dict]:
    return result["_multi"] if "_multi" in result else [result]


def _heard(result: dict, channel: str) -> list[dict]:
    return [
        e for e in _events(result)
        if e.get("kind") == "god_voice_heard"
        and e.get("payload", {}).get("channel") == channel
    ]


def _system_prompt(router: _DuckRouter) -> str:
    return next(m["content"] for m in router.last_messages if m["role"] == "system")


# ── whisper delivery ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_whisper_delivery_emits_god_voice_heard_once():
    world = _world()
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    world.post_whisper_as_god("ada", "Name the town Petriville.")

    result = await rt.run_turn(world.agents["ada"])
    heard = _heard(result, "whisper")
    assert len(heard) == 1
    assert heard[0]["actor_id"] == "ada"
    assert heard[0]["text"] == "✦ Ada hears the whisper"
    assert heard[0]["payload"]["count"] == 1
    # The whisper rode THIS prompt (prompt capture)...
    assert "Name the town Petriville." in _system_prompt(router)
    # ...and was consumed: the next turn carries neither block nor event.
    result2 = await rt.run_turn(world.agents["ada"])
    assert _heard(result2, "whisper") == []
    assert "Name the town Petriville." not in _system_prompt(router)
    assert router.calls == 2  # free-scale: one call per turn, nothing extra


@pytest.mark.asyncio
async def test_whisper_delivery_stays_legible_on_a_failed_turn():
    world = _world()
    router = _DuckRouter(response="not json at all")
    rt = AgentRuntime(world, router)
    world.post_whisper_as_god("ada", "Even failures hear me.")

    result = await rt.run_turn(world.agents["ada"])
    kinds = [e["kind"] for e in _events(result)]
    assert "parse_failure" in kinds
    # The prompt carried the whisper, so delivery happened and must be visible.
    assert len(_heard(result, "whisper")) == 1


# ── god billboard posts reach agents at the board ─────────────────────────────

@pytest.mark.asyncio
async def test_god_board_post_reaches_agent_at_the_plaza_once():
    world = _world()
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    world.tick = 5
    world.post_billboard_as_god("The well will be blessed at dawn.")

    result = await rt.run_turn(world.agents["ada"])  # ada stands at the plaza
    heard = _heard(result, "billboard")
    assert len(heard) == 1
    assert heard[0]["text"] == "📌 Ada reads the god's note on the board"
    sp = _system_prompt(router)
    assert "NEW ON THE NOTICE BOARD" in sp
    assert "The well will be blessed at dawn." in sp

    # Consume-once: the same note is never re-delivered to the same agent.
    result2 = await rt.run_turn(world.agents["ada"])
    assert _heard(result2, "billboard") == []
    assert "The well will be blessed at dawn." not in _system_prompt(router)


@pytest.mark.asyncio
async def test_god_board_post_does_not_reach_agents_away_from_the_board():
    world = _world()
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    world.post_billboard_as_god("Only plaza-dwellers see this.")

    result = await rt.run_turn(world.agents["bo"])  # bo is at the market
    assert _heard(result, "billboard") == []
    assert "Only plaza-dwellers see this." not in _system_prompt(router)


@pytest.mark.asyncio
async def test_agent_billboard_posts_are_not_god_voice():
    world = _world()
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    world.action_post_billboard(world.agents["ada"], "Selling apples, 2c.")

    result = await rt.run_turn(world.agents["ada"])
    assert _heard(result, "billboard") == []
    assert "NEW ON THE NOTICE BOARD" not in _system_prompt(router)


@pytest.mark.asyncio
async def test_later_god_post_is_delivered_after_an_earlier_one_was_seen():
    world = _world()
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    world.tick = 3
    world.post_billboard_as_god("First decree.")
    await rt.run_turn(world.agents["ada"])

    world.tick = 9
    world.post_billboard_as_god("Second decree.")
    result = await rt.run_turn(world.agents["ada"])
    heard = _heard(result, "billboard")
    assert len(heard) == 1
    sp = _system_prompt(router)
    assert "Second decree." in sp
    assert "First decree." not in sp  # already seen, not re-injected

"""
EM-140 — behavioral-arg normalization (live-run fix).

Run 139's DB showed two classes of turns dying on world errors the model could
never correct from feedback:
  · 55× move_to with the destination under a guessed key (destination/to) or a
    JSON null → "unknown place 'None'" — the prompt never documented the arg.
  · 119× social/economy actions targeting agents by NAME ('Ada') while the
    world keys agents by id ('agent_ada_…') — and the prompt lists names, so
    names are the only thing the model CAN send.

These tests drive the real _execute_turn path with scripted MockProvider
actions (deterministic, offline) and assert:
  1. Alias keys and display names now RESOLVE instead of failing the turn.
  2. What still legitimately fails gets actionable feedback + forensics
     (payload.rejected_action) so the next live failure is diagnosable.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile, WorldConfig
from petridish.agents.runtime import AgentRuntime, _normalize_args
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _make_params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
    )


def _make_loop(script: list, *, agent_count: int = 3):
    """All-mock wired loop (mirrors tests/test_w6.py). Agents all start at
    market; ids are agent_<name-lower>, names Ada/Bram/Cleo — so a scripted
    target of 'Ada' is a NAME, never a valid id."""
    params = _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=20, y=0, kind="governance"),
        PlaceState(id="home", name="Hearth", x=30, y=0, kind="home"),
        PlaceState(id="commons", name="Commons", x=40, y=0, kind="wild"),
    ]
    names = ["Ada", "Bram", "Cleo"][:agent_count]
    agents = [
        AgentState(
            id=f"agent_{name.lower()}",
            name=name,
            personality="Test agent.",
            profile="mock",
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for name in names
    ]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    for a in agents:
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo


async def _run_first_turn(script: list, *, agent_count: int = 3):
    """Drive ONE turn (the first agent) and return (by_kind, world, agent)."""
    loop, world, repo = _make_loop(script, agent_count=agent_count)
    agent = world.next_agent()
    await loop._execute_turn(agent)
    events = repo.get_events(loop._run_id, order="asc")
    return {e["kind"]: e for e in events}, world, agent


# ══════════════════════════════════════════════════════════════════════════════
# move_to — alias keys, case, and the missing-place feedback
# ══════════════════════════════════════════════════════════════════════════════

async def test_move_to_destination_alias_resolves():
    """The 'unknown place None' class: destination under a guessed key now
    collapses onto args.place and the move resolves."""
    by_kind, world, agent = await _run_first_turn(
        [{"action": "move_to", "args": {"destination": "plaza"}}]
    )
    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "move_to"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"
    assert agent.location == "plaza"


async def test_move_to_case_insensitive_place():
    by_kind, world, agent = await _run_first_turn(
        [{"action": "move_to", "args": {"place": "Plaza"}}]
    )
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"
    assert agent.location == "plaza"


async def test_move_to_null_place_fails_with_clear_feedback_and_forensics():
    """A genuinely missing place still fails the turn — but the feedback now
    says what's missing (not "unknown place 'None'"), and the parse_failure
    payload carries the rejected action for forensics."""
    by_kind, world, agent = await _run_first_turn(
        [{"action": "move_to", "args": {"place": None}}]
    )
    fail = by_kind["parse_failure"]
    assert "requires args.place" in fail["text"]
    assert "'None'" not in fail["text"]
    rejected = fail["payload"]["rejected_action"]
    assert rejected["action"] == "move_to"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"


async def test_move_to_truly_unknown_place_still_fails():
    """Normalization never invents a place — 'nowhere-land' still fails."""
    by_kind, world, agent = await _run_first_turn(
        [{"action": "move_to", "args": {"place": "nowhere-land"}}]
    )
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"
    assert agent.location == "market"


# ══════════════════════════════════════════════════════════════════════════════
# Targeted actions — display names resolve to agent ids
# ══════════════════════════════════════════════════════════════════════════════

async def test_give_target_by_name_resolves():
    """The 119× class: 'give to Cleo' works even though the world key is
    agent_cleo. First agent is Ada; Cleo is co-located at market."""
    by_kind, world, agent = await _run_first_turn(
        [{"action": "give", "args": {"target": "Cleo", "amount": 1}}]
    )
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"
    assert world.agents["agent_cleo"].credits == world.params.starting_credits + 1


async def test_whisper_target_lowercase_name_resolves():
    by_kind, world, agent = await _run_first_turn(
        [{"action": "whisper", "args": {"target": "cleo", "text": "psst"}}]
    )
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"


async def test_dead_target_gets_a_dead_message_not_unknown():
    """Targeting a dead agent by name resolves to them and says they're dead —
    distinct feedback from an unknown name."""
    loop, world, repo = _make_loop(
        [{"action": "give", "args": {"target": "Cleo", "amount": 1}}]
    )
    world.agents["agent_cleo"].alive = False
    agent = world.next_agent()
    await loop._execute_turn(agent)
    events = repo.get_events(loop._run_id, order="asc")
    fail = next(e for e in events if e["kind"] == "parse_failure")
    assert "is dead" in fail["text"]


async def test_unknown_target_feedback_lists_agents_here():
    """A name matching nobody fails with WHO is actually reachable, so the
    retry can self-correct."""
    by_kind, world, agent = await _run_first_turn(
        [{"action": "give", "args": {"target": "Zorp", "amount": 1}}]
    )
    fail = by_kind["parse_failure"]
    assert "Agents at your location" in fail["text"]
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"


# ══════════════════════════════════════════════════════════════════════════════
# _normalize_args unit edges
# ══════════════════════════════════════════════════════════════════════════════

def _bare_world():
    params = _make_params()
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [
        AgentState(id="agent_ada_1", name="Ada", personality="", profile="mock",
                   location="plaza", energy=50, credits=5),
        AgentState(id="agent_ada_2", name="Ada", personality="", profile="mock",
                   location="plaza", energy=50, credits=5),
        AgentState(id="agent_bram_1", name="Bram", personality="", profile="mock",
                   location="plaza", energy=50, credits=5),
    ]
    return World(params=params, places=places, agents=agents)


def test_normalize_prefers_living_colocated_and_breaks_ties_by_id():
    world = _bare_world()
    actor = world.agents["agent_bram_1"]
    action = {"action": "attack", "args": {"target": "Ada"}}
    _normalize_args(action, actor, world)
    assert action["args"]["target"] == "agent_ada_1"


def test_normalize_noneish_strings_dropped():
    world = _bare_world()
    actor = world.agents["agent_bram_1"]
    action = {"action": "move_to", "args": {"place": "None"}}
    _normalize_args(action, actor, world)
    assert "place" not in action["args"]


def test_normalize_non_dict_args_replaced():
    world = _bare_world()
    actor = world.agents["agent_bram_1"]
    action = {"action": "idle", "args": "garbage"}
    _normalize_args(action, actor, world)
    assert action["args"] == {}

"""
Multi-action turns (EM-199, action-protocol v1.2.0).

One LLM call may carry an ORDERED `actions` sequence — `move` + `fund` + `say`
from a single response → one `_multi` chain sharing one turn_id → three feed
lines, not one. Restores the session-189 feed flood (do MORE per call, never
fewer). The single `action` form stays valid byte-for-byte.

Tests drive the REAL parse → validate → apply path with scripted MockProvider
actions (deterministic, offline). `run_turn` is exercised directly for the
chain/trace shape; `_execute_turn` for the persisted shared-turn_id property.

See contracts/multi-action-turns.md.
"""
from __future__ import annotations

import jsonschema
import pytest

from petridish.engine.world import AgentState, PlaceState, World
from petridish.config.loader import ModelProfile, WorldConfig, WorldParams
from petridish.agents.runtime import ACTION_SCHEMA, AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router

DOMAIN_KINDS = {
    "agent_action", "agent_speech", "agent_moved", "economy",
    "conflict", "relationship", "parse_failure",
}


def _make_params(**over) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
    )
    base.update(over)
    return WorldParams(**base)


def _make_world_runtime(script: list, *, start: str = "market", params=None):
    """Two protagonists (Ada, Bram) co-located at `start`. Returns
    (runtime, world, ada, bram). Both cycle the SAME mock script."""
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="home", name="Hearth", x=20, y=0, kind="home"),
        PlaceState(id="commons", name="Commons", x=30, y=0, kind="wild"),
    ]
    agents = [
        AgentState(id=f"agent_{n.lower()}", name=n, personality="Test agent.",
                   profile="mock", location=start,
                   energy=params.starting_energy, credits=params.starting_credits)
        for n in ("Ada", "Bram")
    ]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    return runtime, world, agents[0], agents[1]


def _domain_events(result: dict) -> list[dict]:
    """The ordered domain events from a run_turn result (strip the _trace)."""
    if "_multi" in result:
        evts = result["_multi"]
    else:
        evts = [{k: v for k, v in result.items() if k != "_trace"}]
    return [e for e in evts if e.get("kind") in DOMAIN_KINDS]


def _make_loop(script: list, *, start: str = "market", params=None):
    runtime, world, ada, bram = _make_world_runtime(script, start=start, params=params)
    repo = SQLiteRepository(":memory:")
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=runtime.router)
    loop.init_run(WorldConfig(world=world.params, places=[], agents=[]))
    return loop, world, repo, ada


# ══════════════════════════════════════════════════════════════════════════════
# Schema — the `actions` array is accepted; the single form still validates.
# ══════════════════════════════════════════════════════════════════════════════

def test_schema_accepts_actions_array():
    jsonschema.validate(
        {"thought": "do three things",
         "actions": [
             {"action": "move_to", "args": {"place": "plaza"}},
             {"action": "work", "args": {}},
             {"action": "say", "args": {"text": "hi"}},
         ]},
        ACTION_SCHEMA,
    )


def test_schema_still_accepts_single_action():
    jsonschema.validate({"action": "work", "args": {}}, ACTION_SCHEMA)
    jsonschema.validate({"action": "say", "args": {"text": "hello"}}, ACTION_SCHEMA)


def test_schema_rejects_neither_action_nor_actions():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"thought": "nothing"}, ACTION_SCHEMA)


def test_schema_actions_only_does_not_force_single_action_args():
    """The per-action arg conditionals must fire ONLY for a top-level `action`,
    never on an actions[]-only response (else `say` etc. would wrongly demand
    top-level args.text)."""
    jsonschema.validate(
        {"actions": [{"action": "say", "args": {"text": "hi"}}]},
        ACTION_SCHEMA,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Resolution — ordered chain, one turn, shared turn_id.
# ══════════════════════════════════════════════════════════════════════════════

async def test_multi_action_emits_ordered_chain_from_one_turn():
    """say → work → move_to in one response yields THREE domain events in that
    order, and the world reflects all three (earned credits, moved)."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "morning all"}},
            {"action": "work", "args": {}},
            {"action": "move_to", "args": {"place": "plaza"}},
        ]}],
        start="market",
    )
    start_credits = ada.credits
    result = await runtime.run_turn(ada)
    kinds = [e["kind"] for e in _domain_events(result)]
    assert kinds == ["agent_speech", "economy", "agent_moved"]
    assert ada.location == "plaza"            # the move applied
    assert ada.credits > start_credits        # the work applied


async def test_multi_action_persisted_events_share_one_turn_id():
    loop, world, repo, ada = _make_loop(
        [{"actions": [
            {"action": "say", "args": {"text": "let's build"}},
            {"action": "work", "args": {}},
        ]}],
        start="market",
    )
    await loop._execute_turn(ada)
    events = repo.get_events(loop._run_id, order="asc")
    domain = [e for e in events if e["kind"] in DOMAIN_KINDS and e.get("actor_id") == ada.id]
    assert len(domain) >= 2
    turn_ids = {e.get("turn_id") for e in domain}
    assert len(turn_ids) == 1 and None not in turn_ids
    # Two distinct feed lines (a speech + an economy) from the one turn.
    assert {"agent_speech", "economy"} <= {e["kind"] for e in domain}


async def test_failed_step_does_not_abort_siblings():
    """A gated/invalid step emits its parse_failure but the rest still run —
    the `say` happens even though the move target is unknown."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "move_to", "args": {"place": "atlantis"}},   # unknown place → fails
            {"action": "say", "args": {"text": "still spoke"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    assert "parse_failure" in kinds            # the bad move surfaced
    assert "agent_speech" in kinds             # the say still resolved
    assert ada.location == "market"            # never moved
    speech = next(e for e in evts if e["kind"] == "agent_speech")
    assert "still spoke" in speech["text"]


async def test_single_action_still_works():
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "work", "args": {}}], start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    assert [e["kind"] for e in evts] == ["economy"]


# ══════════════════════════════════════════════════════════════════════════════
# Cognition — thought once, trace shape, overheard per speech step, cap.
# ══════════════════════════════════════════════════════════════════════════════

async def test_thought_surfaced_once_on_first_event_only():
    runtime, world, ada, _bram = _make_world_runtime(
        [{"thought": "busy morning", "actions": [
            {"action": "say", "args": {"text": "hi"}},
            {"action": "work", "args": {}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    with_thought = [e for e in evts if "💭" in (e.get("text") or "")]
    assert len(with_thought) == 1
    assert evts[0]["text"].endswith("💭 busy morning")


async def test_trace_records_all_steps_when_multi():
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "hi"}},
            {"action": "work", "args": {}},
            {"action": "move_to", "args": {"place": "plaza"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    chosen = result["_trace"]["action_chosen"]
    # Back-compat: the singular fields still read the FIRST step.
    assert chosen["chosen_tool"] == "say"
    # Additive: the full sequence is recorded only on a multi-action turn.
    assert [s["action"] for s in chosen["actions"]] == ["say", "work", "move_to"]


async def test_trace_single_action_has_no_actions_array():
    """A single-action (and reflex) trace keeps its exact pre-EM-199 key set —
    no additive `actions` array — so exact-equality assertions elsewhere hold."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "work", "args": {}}], start="market",
    )
    result = await runtime.run_turn(ada)
    assert "actions" not in result["_trace"]["action_chosen"]


async def test_overheard_distributed_for_a_non_first_speech_step():
    """The `say` is the SECOND step. Pre-EM-199 only the first chosen action
    distributed, so a listener heard nothing; multi-action distributes EACH
    speech step."""
    runtime, world, ada, bram = _make_world_runtime(
        [{"actions": [
            {"action": "work", "args": {}},
            {"action": "say", "args": {"text": "after work"}},
        ]}],
        start="market",
    )
    await runtime.run_turn(ada)
    heard = runtime._overheard.get(bram.id, [])
    assert any("after work" in h.get("text", "") for h in heard)


async def test_actions_capped_at_max_actions_per_turn():
    """Steps beyond max_actions_per_turn are dropped (logged), not resolved."""
    params = _make_params(max_actions_per_turn=2)
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "one"}},
            {"action": "say", "args": {"text": "two"}},
            {"action": "say", "args": {"text": "three"}},
            {"action": "say", "args": {"text": "four"}},
        ]}],
        start="market", params=params,
    )
    result = await runtime.run_turn(ada)
    speeches = [e for e in _domain_events(result) if e["kind"] == "agent_speech"]
    assert len(speeches) == 2
    assert "three" not in " ".join(e["text"] for e in speeches)

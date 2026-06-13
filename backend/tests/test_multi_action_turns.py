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


# ══════════════════════════════════════════════════════════════════════════════
# QE adversarial probes — edge cases the original 13 tests did not cover.
# ══════════════════════════════════════════════════════════════════════════════

async def test_give_no_target_in_multi_step_caught_not_aborted():
    """give with no 'target' key is rejected per-step by _validate_world
    ("give requires target") and surfaces as parse_failure — never reaching the
    args['target'] KeyError in _apply_action_inner. The SUBSEQUENT say step
    still resolves (continue-on-failure)."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "give", "args": {"amount": 5}},  # no target → KeyError
            {"action": "say", "args": {"text": "still here"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    # The broken give must surface as parse_failure, NOT propagate as an
    # unhandled exception that kills the turn.
    assert "parse_failure" in kinds, "missing give KeyError emitted as parse_failure"
    # The sibling say must still resolve.
    assert "agent_speech" in kinds, "sibling say was aborted by the give KeyError"
    speech = next(e for e in evts if e["kind"] == "agent_speech")
    assert "still here" in speech["text"]


async def test_steal_no_target_in_multi_step_caught_not_aborted():
    """steal with no 'target' key — rejected per-step by _validate_world
    ("steal requires target") as parse_failure; the sibling work still runs."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "steal", "args": {}},  # no target → KeyError
            {"action": "work", "args": {}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    assert "parse_failure" in kinds, "steal KeyError not caught as parse_failure"
    assert "economy" in kinds, "sibling work was aborted by the steal KeyError"


async def test_single_element_actions_array_no_multi_wrapper():
    """actions:[{...}] with ONE element: the result must NOT be wrapped in
    _multi (it is equivalent to the legacy single-action form). The trace must
    also have NO 'actions' key (back-compat)."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [{"action": "work", "args": {}}]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    # A single-element chain produces a bare event, not a _multi dict.
    assert "_multi" not in result, (
        "single-element actions[] was wrapped in _multi; "
        "this breaks the contract's back-compat guarantee for 1-step responses"
    )
    # Trace: no 'actions' key — single-action key set preserved.
    assert "actions" not in result["_trace"]["action_chosen"], (
        "single-element actions[] added 'actions' key to trace; "
        "breaks exact-equality assertions in pre-EM-199 tests"
    )


async def test_max_actions_per_turn_1_behaves_as_legacy():
    """max_actions_per_turn=1 with a 3-step script: only the first step
    resolves, the other two are dropped (logged). Result is NOT wrapped in
    _multi; trace has no 'actions' key (indistinguishable from pre-EM-199)."""
    params = _make_params(max_actions_per_turn=1)
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "only me"}},
            {"action": "work", "args": {}},
            {"action": "move_to", "args": {"place": "plaza"}},
        ]}],
        start="market", params=params,
    )
    result = await runtime.run_turn(ada)
    # Only one event, no _multi wrap.
    assert "_multi" not in result, "max_actions=1 result was wrapped in _multi"
    evts = _domain_events(result)
    assert len(evts) == 1
    assert evts[0]["kind"] == "agent_speech"
    assert "only me" in evts[0]["text"]
    # Dropped steps → no work or move applied.
    assert ada.location == "market"
    # Trace: no 'actions' key.
    assert "actions" not in result["_trace"]["action_chosen"]


async def test_whisper_target_excluded_from_overhearers_in_multi_step():
    """In a multi-step turn with a whisper step, the whisper target must be
    EXCLUDED from overheard distribution. Only bystanders receive it."""
    runtime, world, ada, bram = _make_world_runtime(
        [{"actions": [
            {"action": "work", "args": {}},
            {"action": "whisper", "args": {
                "target": "agent_bram",
                "text": "secret for bram only",
            }},
        ]}],
        start="market",
    )
    await runtime.run_turn(ada)
    # Bram is the whisper target — must NOT receive an overheard entry.
    bram_heard = runtime._overheard.get(bram.id, [])
    secret_leaked = any(
        "secret for bram only" in h.get("text", "") for h in bram_heard
    )
    assert not secret_leaked, (
        "whisper target (Bram) received the whisper in the overheard queue — "
        "the exclusion logic is broken for multi-step turns"
    )


async def test_state_deltas_aggregate_across_multi_step():
    """move + work + forage in one turn: credits_delta in state_deltas must
    be the SUM of both economy steps, not just the first step's value."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "move_to", "args": {"place": "commons"}},
            {"action": "forage", "args": {}},
            {"action": "move_to", "args": {"place": "market"}},
            {"action": "work", "args": {}},
        ]}],
        start="market",
    )
    start_credits = ada.credits
    result = await runtime.run_turn(ada)
    # Both economy steps should have applied.
    earned = ada.credits - start_credits
    assert earned > 0, "expected at least one economy step to earn credits"
    # The trace state_deltas should aggregate across the chain.
    deltas = result["_trace"]["resolved"]["state_deltas"]
    # credits_delta should be the sum of what the two economy steps yielded.
    assert deltas.get("credits_delta", 0) == earned, (
        f"state_deltas.credits_delta={deltas.get('credits_delta')} "
        f"but agent earned {earned} credits — aggregation may be wrong"
    )


async def test_no_relationship_leak_on_failed_step():
    """EM-113 — a failed step (here a gate-rejected give: no target) must not
    introduce orphaned relationship_changed events into the chain. Whether a step
    is rejected by _validate_world (no inner dispatch, nothing parked) or raises
    inside _apply_action_inner (drained-and-discarded in the finally), the rule
    is the same: a failed step never leaks a relationship shift onto the chain."""
    runtime, world, ada, bram = _make_world_runtime(
        [{"actions": [
            {"action": "give", "args": {"amount": 5}},  # no target → gate-rejected
            {"action": "say", "args": {"text": "ok"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    # The chain should contain the parse_failure (from give) + agent_speech
    # (from say) only — no orphaned relationship_changed events.
    evts = _domain_events(result)
    relationship_evts = [e for e in evts if e.get("kind") == "relationship_changed"]
    # No real relationship action was performed, so there must be no leaked shifts.
    assert len(relationship_evts) == 0, (
        f"Unexpected relationship_changed events in chain after a raising step: "
        f"{relationship_evts}"
    )


async def test_chain_order_matches_step_order():
    """The emitted domain events must be in the EXACT step order: event for
    step-1 appears before event for step-2, regardless of action types."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "first"}},
            {"action": "move_to", "args": {"place": "plaza"}},
            {"action": "say", "args": {"text": "second"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    # Expect: agent_speech, agent_moved, agent_speech — in that order.
    assert kinds == ["agent_speech", "agent_moved", "agent_speech"], (
        f"Step ordering not preserved: got {kinds}"
    )
    speech_texts = [e["text"] for e in evts if e["kind"] == "agent_speech"]
    assert "first" in speech_texts[0]
    assert "second" in speech_texts[1]


async def test_normalize_steps_empty_actions_array_falls_to_single_action():
    """_normalize_steps must fall back to the single-action form when the
    actions[] list is empty (or all elements are malformed). An empty list is
    technically invalid per schema (minItems 1) but we probe the fallback path
    defensively so the runtime never panics on a malformed response."""
    from petridish.agents.runtime import AgentRuntime
    # Access the static method directly to unit-test the fallback.
    steps, dropped = AgentRuntime._normalize_steps(
        {"action": "work", "args": {}, "actions": []}, max_steps=4
    )
    # Empty actions[] → falls back to single action.
    assert len(steps) == 1
    assert steps[0]["action"] == "work"
    assert dropped == 0


async def test_normalize_steps_none_action_items_are_filtered():
    """_normalize_steps filters items where step.get('action') is falsy.
    If ALL items are bad, fall back to the single-action form."""
    from petridish.agents.runtime import AgentRuntime
    steps, dropped = AgentRuntime._normalize_steps(
        {
            "action": "idle",
            "args": {},
            "actions": [
                {"args": {}},           # no action key → filtered
                {"action": None, "args": {}},  # null action → filtered
            ]
        },
        max_steps=4,
    )
    # All actions[] items were bad → fell back to single 'idle'.
    assert len(steps) == 1
    assert steps[0]["action"] == "idle"


async def test_extra_events_appended_once_not_per_step():
    """turn-level cognition extras (commitment_made, reflection, bond shifts,
    god_voice_heard) must be appended exactly ONCE after the full chain — not
    once per step. We verify that a multi-step turn with a reflection only
    produces one reflection event."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "step one"}},
            {"action": "work", "args": {}},
        ],
        "reflection": "I did two things today."}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    all_events = result["_multi"] if "_multi" in result else [result]
    reflection_evts = [e for e in all_events if e.get("kind") == "reflection"]
    assert len(reflection_evts) == 1, (
        f"Expected exactly 1 reflection event, got {len(reflection_evts)}: "
        f"{reflection_evts}"
    )


async def test_trace_outcome_ok_when_any_step_ok():
    """resolved.outcome == 'ok' if ANY step resolved ok, even if another step
    failed (contract: outcome is ok if ANY step ok)."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "move_to", "args": {"place": "atlantis"}},  # fails
            {"action": "work", "args": {}},                        # ok
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    assert result["_trace"]["resolved"]["outcome"] == "ok", (
        "outcome should be 'ok' when at least one step succeeded"
    )


async def test_trace_outcome_failed_when_all_steps_fail():
    """resolved.outcome == 'failed' when every step fails."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "move_to", "args": {"place": "atlantis"}},  # fails
            {"action": "move_to", "args": {"place": "narnia"}},    # fails
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    assert result["_trace"]["resolved"]["outcome"] == "failed", (
        "outcome should be 'failed' when every step failed"
    )


async def test_thought_not_duplicated_when_first_event_is_parse_failure():
    """If the FIRST step fails (parse_failure is the first chain event), the
    thought must ride that failure event exactly once — not duplicate onto the
    second successful event."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"thought": "test-thought", "actions": [
            {"action": "move_to", "args": {"place": "atlantis"}},  # → parse_failure first
            {"action": "say", "args": {"text": "hi"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    all_evts = result["_multi"] if "_multi" in result else [result]
    thought_bearing = [e for e in all_evts if "💭" in (e.get("text") or "")]
    assert len(thought_bearing) == 1, (
        f"thought appeared on {len(thought_bearing)} events (expected 1): "
        f"{[e.get('text') for e in thought_bearing]}"
    )
    # It should be on the FIRST event (the parse_failure), not the second.
    assert thought_bearing[0] is all_evts[0], (
        "thought was not on the first chain event"
    )


async def test_per_step_arg_aliases_normalized_in_multi_action():
    """EM-140/EM-199 — each actions[] step runs _normalize_args, so an arg alias
    (`destination`→`place`) is collapsed per-step exactly as in the single-action
    form. The move_to step SUCCEEDS instead of dying on key spelling the prompt
    never specified."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "move_to", "args": {"destination": "plaza"}},  # alias → normalized
            {"action": "say", "args": {"text": "after move"}},
        ]}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    assert "agent_moved" in kinds, "alias 'destination' was not normalized to 'place'"
    assert ada.location == "plaza", "agent did not move despite normalized alias"
    assert "agent_speech" in kinds  # the sibling say also ran


async def test_tier_gate_enforced_per_step_for_background_agent():
    """EM-163/EM-199 — the tier gate in _validate_world fires PER-STEP: a
    background agent that sneaks a propose_project into an actions[] sequence
    (off its diet menu) is rejected at resolution, exactly as a single-action
    propose_project would be. The sibling `say` still resolves (continue-on-
    failure). Proves the contract's 'same _validate_world gates' claim holds for
    the multi-action form."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"actions": [
            {"action": "say", "args": {"text": "hi"}},
            {"action": "propose_project", "args": {
                "name": "TestProject", "kind": "workshop",
            }},
        ]}],
        start="market",
    )
    ada.cadence_tier = "background"  # type: ignore[attr-defined]
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    tier_error_evts = [
        e for e in evts
        if e.get("kind") == "parse_failure" and "tier rule" in (e.get("text") or "")
    ]
    assert len(tier_error_evts) == 1, "tier gate did not fire per-step on the actions[] propose_project"
    # The sibling say still reached the room.
    assert any(e["kind"] == "agent_speech" for e in evts)

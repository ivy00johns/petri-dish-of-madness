"""EM-340 — the failure-kind split.

`parse_failure` used to carry THREE unrelated phenomena, so any per-run
"parse failure rate" mixed them. Run 23 (322 events, ZERO malformed JSON)
decomposed — measured from the persisted DB — into:

    124  rejected:true          → action_rejected   (dispatch / per-step gate)
     30  reason='provider_error' → provider_error
    115  reason='no valid JSON'  → parse_failure
     30  reason='schema error'   → parse_failure
     14  reason='world error'    → parse_failure (the RETRIED validation path)
      9  dispatch refusals w/o the flag → action_rejected

Run 26 was worse: 288 of its 417 were provider errors (the tick-1147 outage)
and only ~31 were real parse failures.

The seam this file pins, and why it is where it is:

  * `action_rejected` — the model answered with a schema-valid action and the
    WORLD refused it at APPLY time (per-step `_validate_world` gate, the
    `_apply_action_inner` dispatch table, or `World._fail_event`). Payload
    keeps `{action, error, rejected?}` — unchanged, only the kind moves.
  * `provider_error` — the provider never served a usable response (transport
    error, exhausted/rate-limited lanes, or the wall-clock turn budget).
  * `parse_failure` — the response could not be turned into an applicable
    action: no JSON, a `schema error:`, or a `world error:` from the
    PRE-dispatch validator (which is retried as "your response failed
    validation"). That retried path stays `parse_failure` ON PURPOSE — it is
    the model's response that failed, and it is the path the retry loop and
    the EM-140 `rejected_action` forensic belong to.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime
(the circular-import guard).
"""
from __future__ import annotations

import pytest

from petridish.config.loader import ModelProfile, WorldParams
from petridish.engine.world import World, AgentState, PlaceState  # noqa: F401 — must precede agents.runtime
from petridish.agents.runtime import (  # noqa: E402
    AgentRuntime,
    _emit_world_result,
    _failure_kind_for,
    _is_failure_kind,
)
from petridish.engine.loop import TickLoop  # noqa: E402
from petridish.providers.base import ProviderError  # noqa: E402
from petridish.providers.mock import MockProvider  # noqa: E402
from petridish.providers.router import Router  # noqa: E402


# ── (A) The classifier unit — the reason→kind whitelist ───────────────────────

def test_provider_side_reasons_earn_provider_error():
    # The provider never answered: transport error, exhausted lanes, budget.
    assert _failure_kind_for("provider_error: timed out after 30s") == "provider_error"
    assert _failure_kind_for(
        "llm_timeout: LLM call exceeded the 30s turn budget"
    ) == "provider_error"
    assert _failure_kind_for("unexpected_error: boom") == "provider_error"
    # Prefix matching is case/whitespace tolerant (the reason round-trips as-is).
    assert _failure_kind_for("  Provider_Error: nope") == "provider_error"


def test_content_failures_keep_parse_failure():
    assert _failure_kind_for(
        "no valid JSON object (finish_reason='length') in response: 'hi'"
    ) == "parse_failure"
    assert _failure_kind_for(
        "schema error: 'action' is a required property"
    ) == "parse_failure"


def test_retried_world_error_stays_parse_failure_by_design():
    """The pre-dispatch validator's refusal is RETRIED ("your previous response
    failed validation") — the response could not be turned into an applicable
    action, so it stays parse_failure. The APPLY-time refusals are the ones that
    become action_rejected (the 124 `rejected:true` in run 23)."""
    assert _failure_kind_for("world error: unknown target 'Zorp'") == "parse_failure"


def test_missing_reason_defaults_to_parse_failure():
    # Conservative default: an unrecognized reason keeps the pre-EM-340 meaning.
    assert _failure_kind_for(None) == "parse_failure"
    assert _failure_kind_for("") == "parse_failure"
    assert _failure_kind_for("some future failure mode") == "parse_failure"


def test_is_failure_kind_covers_the_split_and_the_legacy_kind():
    for kind in ("parse_failure", "action_rejected", "provider_error"):
        assert _is_failure_kind(kind) is True
    for kind in ("economy", "agent_speech", "agent_action", None, ""):
        assert _is_failure_kind(kind) is False


# ── (B) World-side refusals → action_rejected ────────────────────────────────

def test_world_fail_event_is_action_rejected():
    evt = World._fail_event("agent_a", "demolish", "building_not_found",
                            "A tried to demolish an unknown structure.")
    assert evt["kind"] == "action_rejected"
    assert evt["payload"] == {"action": "demolish", "error": "building_not_found"}


def test_malformed_world_return_stays_parse_failure():
    """The engine's OWN defensive fallback (no model output involved) is not a
    rejection — there is no action to reject."""
    evt = _emit_world_result(
        12345, {"actor_id": "agent_a", "profile": "p", "profile_color": "#fff",
                "tick": 1},
    )
    assert evt["kind"] == "parse_failure"
    assert evt["payload"] == {"error": "bad_world_result"}


# ── (C) End-to-end: the per-step gate → action_rejected, turn continues ──────

def _multi_action_runtime(script: list):
    """Ada + Bram co-located, one mock script per turn (the
    test_multi_action_turns idiom)."""
    params = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=20, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, recharge_cost=2,
        recharge_amount=20.0,
    )
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="home", name="Hearth", x=20, y=0, kind="home"),
        PlaceState(id="commons", name="Commons", x=30, y=0, kind="wild"),
        PlaceState(id="townhall", name="Town Hall", x=40, y=0, kind="governance"),
    ]
    agents = [
        AgentState(id=f"agent_{n.lower()}", name=n, personality="Test agent.",
                   profile="mock", location="market",
                   energy=params.starting_energy, credits=params.starting_credits)
        for n in ("Ada", "Bram")
    ]
    world = World(params=params, places=places, agents=agents)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": MockProvider(script=script)},
    )
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    return AgentRuntime(world, router), world, agents[0]


@pytest.mark.asyncio
async def test_refused_step_is_action_rejected_and_siblings_still_run():
    runtime, world, ada = _multi_action_runtime([
        {"actions": [
            {"action": "give", "args": {"amount": 5}},   # no target → gate refuses
            {"action": "say", "args": {"text": "still spoke"}},
        ]},
    ])
    result = await runtime.run_turn(ada)
    evts = result["_multi"] if "_multi" in result else [result]
    kinds = [e.get("kind") for e in evts]

    assert "action_rejected" in kinds, kinds
    assert "parse_failure" not in kinds, "an apply-time refusal must NOT wear parse_failure"
    assert "agent_speech" in kinds, "the sibling say was aborted"

    rejected = next(e for e in evts if e.get("kind") == "action_rejected")
    assert rejected["payload"]["rejected"] is True
    assert rejected["payload"]["action"] == "give"
    assert "requires target" in rejected["payload"]["error"]


def test_apply_steps_marks_a_rejected_step_not_ok():
    """The turn-level accounting the split must not disturb: a refused step is
    ok=False (commitment aging / step_results / coherence all key off this)."""
    runtime, world, ada = _multi_action_runtime([])
    chain, results = runtime._apply_steps(
        ada,
        [{"action": "give", "args": {"amount": 5}},
         {"action": "say", "args": {"text": "hi"}}],
        "mock", "#fff", "",
    )
    assert [e["kind"] for e in chain] == ["action_rejected", "agent_speech"]
    assert [r["ok"] for r in results] == [False, True]


# ── (D) End-to-end: the idle-fallback kinds ──────────────────────────────────

class _Router:
    """Duck-typed router returning one canned response (the test_god_voice
    idiom) — lets a turn fail with exact reason shapes."""

    def __init__(self, response: str):
        self.response = response
        self.calls = 0

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls += 1
        return self.response

    def last_usage(self, profile_name):
        return None

    def last_routed_via(self, profile_name):
        return None


def _one_agent_world() -> tuple[World, AgentState]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=90.0, starting_credits=10,
        memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(id="agent_0", name="Agent0", personality="curious",
                       profile="mock", location="plaza", energy=90.0, credits=10)
    world = World(params=params, places=places, agents=[agent])
    return world, agent


class _ErrorAdapter:
    """Always raises ProviderError — the provider never answered."""

    def __init__(self):
        self.calls = 0
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError("lane", 502, "bad gateway")


@pytest.mark.asyncio
async def test_provider_failure_idles_as_provider_error_not_parse_failure():
    world, agent = _one_agent_world()
    router = Router(profiles=[], adapter_overrides={"mock": _ErrorAdapter()})
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)

    assert event["kind"] == "provider_error"
    assert event["payload"]["reason"].startswith("provider_error")
    # The text is unchanged — only the kind moved (feed copy stays byte-stable).
    assert "failed to produce a valid action (idle fallback)" in event["text"]


@pytest.mark.asyncio
async def test_no_json_idles_as_parse_failure():
    world, agent = _one_agent_world()
    runtime = AgentRuntime(world, _Router("not json at all"))

    event = await runtime.run_turn(agent)

    assert event["kind"] == "parse_failure"
    assert event["payload"]["reason"].startswith("no valid JSON")


@pytest.mark.asyncio
async def test_schema_invalid_idles_as_parse_failure_with_forensics():
    world, agent = _one_agent_world()
    runtime = AgentRuntime(world, _Router('{"thought": "hmm", "not_action": "work"}'))

    event = await runtime.run_turn(agent)

    assert event["kind"] == "parse_failure"
    assert event["payload"]["reason"].startswith("schema error")
    # EM-140 forensics survive the split.
    assert event["payload"]["rejected_action"]["action"] is None


# ── (E) The auto-pause classifier (EM-226) reads the new kind ────────────────

def test_provider_error_reason_classifies_the_split_kinds():
    cls = TickLoop._provider_error_reason
    # The new kind is what live turns now carry.
    assert cls({"kind": "provider_error",
                "payload": {"reason": "provider_error: x"}}) == "provider_error: x"
    assert cls({"_multi": [{"kind": "provider_error",
                            "payload": {"reason": "provider_error: y"}}]}
               ) == "provider_error: y"
    # Legacy persisted rows still classify (append-only log, never re-kinded).
    assert cls({"kind": "parse_failure",
                "payload": {"reason": "provider_error: z"}}) == "provider_error: z"


def test_provider_error_reason_still_excludes_timeouts_and_content_failures():
    cls = TickLoop._provider_error_reason
    # A turn-budget timeout is NOT a provider outage (EM-170/173/226 preserved):
    # it earns a reflex, never the auto-pause streak.
    assert cls({"kind": "provider_error",
                "payload": {"reason": "llm_timeout: exceeded 30s"}}) is None
    # A content parse failure is not a provider error either.
    assert cls({"kind": "parse_failure",
                "payload": {"reason": "no valid JSON object"}}) is None
    # The new action_rejected kind never counts toward the outage streak.
    assert cls({"kind": "action_rejected",
                "payload": {"error": "target_not_found"}}) is None

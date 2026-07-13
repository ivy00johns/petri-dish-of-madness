"""EM-324 — content-truncation detour.

A finish_reason=length response that yields NO parseable JSON (the proxy's
cohere/command-a-plus reroute — a plaintext reasoning preamble hard-capped at
1024 tokens, run 1388: 32/32 strict-JSON turns) is recorded as an `error` lane
demerit, so a CHRONIC truncator goes sick and the adaptive bounce loop routes
AROUND it — instead of agents being silently fed straight back into it, idling
turn after turn into "failed to produce a valid action" feed cards.

`_looks_truncated` only detects an UNCLOSED '{'; a pure-prose preamble has none,
so before EM-324 these evaded lane health entirely (recorded truncated=False,
which lane_sick does not count). Contract:
  - note_parse_outcome(errored=True) appends an `error` entry lane_sick counts.
  - chronic content-truncations (>= sick_threshold) → lane_sick True.
  - a PLAIN parse-failure (parsed=False, no error/timeout) still does NOT sick
    the lane (content problems != lane problems — the pre-EM-324 guarantee).
  - end-to-end: a runtime whose lane returns finish=length + no JSON drives the
    real lane sick; a duck-typed router WITHOUT `errored` still works unchanged.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import WorldParams
from petridish.engine.world import World, AgentState, PlaceState
from petridish.providers.router import Router


# ── (A) Router unit — the errored demerit + sickness ──────────────────────────

def test_content_truncation_records_error_demerit():
    r = Router(profiles=[])
    r.note_parse_outcome("lane", parsed=False, truncated=False, errored=True)
    health = r.lane_health()["lane"]
    assert health["window"] == [{"parsed": False, "truncated": False, "error": True}]
    assert health["errors"] == 1


def test_chronic_content_truncation_goes_sick():
    r = Router(profiles=[])
    assert r.lane_sick("lane") is False
    for _ in range(r._sick_threshold()):
        r.note_parse_outcome("lane", parsed=False, truncated=False, errored=True)
    assert r.lane_sick("lane") is True


def test_plain_parse_failure_stays_healthy():
    # Backward-compat: a content problem (no error/timeout) must NOT sick the
    # lane — only errored/timed_out demerits do (pre-EM-324 guarantee).
    r = Router(profiles=[])
    for _ in range(6):
        r.note_parse_outcome("lane", parsed=False, truncated=False)
    assert r.lane_sick("lane") is False


def test_errored_defaults_false_backward_compat():
    # Existing callers that omit `errored` produce the exact old window shape.
    r = Router(profiles=[])
    r.note_parse_outcome("lane", parsed=True, truncated=False)
    assert r.lane_health()["lane"]["window"] == [{"parsed": True, "truncated": False}]


# ── (B) End-to-end — the runtime threads content_truncation → lane sick ───────

_PROSE_PREAMBLE = (
    "We need to output a JSON object with action(s). Must be only JSON, no "
    "prose. We need to decide what to do this turn. The agent is in the Plaza."
)


def _world_with_agent(profile: str) -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        recharge_cost=2, recharge_amount=20.0, work_reward=4, forage_reward=1,
        steal_max=5, death_after_zero_turns=10, memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="mox", name="Mox", personality="curious", profile=profile,
        location="plaza", energy=88.0, credits=10,
    )
    return agent, World(params=params, places=places, agents=[agent])


class _LengthTruncRouter:
    """Duck-typed router delegating the EM-135/EM-324 surface to a REAL Router.
    Serves a pure-prose preamble (no JSON) and reports finish_reason=length —
    the exact command-a-plus signature. Its note_parse_outcome accepts `errored`
    so the runtime's guarded thread reaches the real lane window."""

    def __init__(self) -> None:
        self.lane = Router(profiles=[])

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        return _PROSE_PREAMBLE

    def last_usage(self, profile_name):
        return {"input_tokens": 4900, "output_tokens": 1024, "latency_ms": 1.0,
                "finish_reason": "length", "cached": False}

    def last_routed_via(self, profile_name):
        return "cohere/command-a-plus-05-2026"

    def first_attempt_max_tokens(self, profile_name, base):
        return self.lane.first_attempt_max_tokens(profile_name, base)

    def note_parse_outcome(self, profile_name, *, parsed, truncated,
                           served_by=None, errored=False):
        self.lane.note_parse_outcome(
            profile_name, parsed=parsed, truncated=truncated, errored=errored)


@pytest.mark.asyncio
async def test_length_no_json_turns_drive_lane_sick():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent("command-r")
    router = _LengthTruncRouter()
    runtime = AgentRuntime(world, router)

    assert router.lane.lane_sick("command-r") is False
    # Each failing turn records content-truncation demerits (attempt 1 + the
    # length-boosted retry). Two turns cross the sick threshold (3).
    for _ in range(2):
        await runtime.run_turn(agent)
    assert router.lane.lane_sick("command-r") is True


class _PlainDuckRouter:
    """A duck-typed router WITHOUT the EM-324 `errored` kwarg — the guarded
    getattr/_accepts_kwarg wiring must leave it fully functional (no crash)."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls.append(max_tokens)
        return _PROSE_PREAMBLE

    def last_usage(self, profile_name):
        return {"finish_reason": "length"}

    def last_routed_via(self, profile_name):
        return None


@pytest.mark.asyncio
async def test_duck_router_without_errored_still_runs():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent("legacy")
    router = _PlainDuckRouter()
    runtime = AgentRuntime(world, router)
    event = await runtime.run_turn(agent)  # must not raise on the errored thread
    assert event is not None
    assert router.calls  # the turn actually consulted the lane

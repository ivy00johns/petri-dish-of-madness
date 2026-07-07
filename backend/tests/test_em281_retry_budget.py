"""EM-281 (W29) — the parse-failure retry budget must STRICTLY EXCEED the budget
the first attempt actually used.

On an EM-135-boosted lane, attempt 1 runs at first_attempt_max_tokens (=
max(base*4, 8192)) and truncates there. The old code computed the retry budget
from the BASE (`_retry_max_tokens(base)` == max(base*4, 8192)), which equals the
boosted attempt-1 cap the lane just cut at — so the retry could never grow past
the cap that failed, and the agent kept starving on idle fallbacks. The fix bases
the retry on the ACTUAL attempt-1 budget, so it is always strictly larger.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import WorldParams
from petridish.engine.world import World, AgentState, PlaceState
from petridish.providers.router import Router


# A response that FAILS to parse (no extractable JSON object) but is structurally
# TRUNCATED (an unclosed brace) — so _call_and_parse reports action_dict=None with
# truncated_json=True, which is exactly the case that boosts the retry budget.
_UNPARSEABLE_TRUNCATED = 'Let me reason about my options first {"acti'


def _world_with_agent():
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        recharge_cost=2, recharge_amount=20.0, work_reward=4, forage_reward=1,
        steal_max=5, death_after_zero_turns=10, memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(id="cleo", name="Cleo", personality="curious", profile="test",
                       location="plaza", energy=88.0, credits=10)
    world = World(params=params, places=places, agents=[agent])
    return agent, world


class _BoostedLaneRouter:
    """Duck-typed runtime router delegating the EM-135 surface to a REAL Router,
    so first_attempt_max_tokens boosts exactly as production does. Records the
    max_tokens of every chat() call."""

    def __init__(self, response: str):
        self.response = response
        self.calls: list[int] = []
        self.lane = Router(profiles=[])

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None  # fall back to the agent default budget (1024)

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls.append(max_tokens)
        return self.response

    def last_usage(self, profile_name):
        # The lying 'stop': truncation is detected structurally, not by finish_reason.
        return {"input_tokens": 100, "output_tokens": 50, "latency_ms": 1.0,
                "finish_reason": "stop", "cached": False}

    def last_routed_via(self, profile_name):
        return "mistral/mistral-medium-latest"

    def first_attempt_max_tokens(self, profile_name, base):
        return self.lane.first_attempt_max_tokens(profile_name, base)

    def note_parse_outcome(self, profile_name, *, parsed, truncated):
        self.lane.note_parse_outcome(profile_name, parsed=parsed, truncated=truncated)


@pytest.mark.asyncio
async def test_retry_budget_strictly_exceeds_boosted_attempt1_budget():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _BoostedLaneRouter(_UNPARSEABLE_TRUNCATED)
    # Pre-seed the lane as known-bad so attempt 1 ALREADY starts boosted.
    router.note_parse_outcome("test", parsed=False, truncated=True)
    runtime = AgentRuntime(world, router)

    await runtime.run_turn(agent)

    # Two calls: the boosted first attempt, then the retry.
    assert len(router.calls) == 2, router.calls
    # Attempt 1 boosted: max(1024*4, 8192) = 4096.
    assert router.calls[0] == 8192
    # THE FIX: the retry must be strictly larger than the boosted cap that just
    # truncated — the old bug made these equal (both 4096).
    assert router.calls[1] > router.calls[0]
    # Regression pin: grown from the ACTUAL attempt-1 budget → max(8192*4, 8192).
    assert router.calls[1] == 32768


@pytest.mark.asyncio
async def test_healthy_lane_retry_still_grows_from_base():
    """On an un-boosted (healthy) lane attempt 1 runs at the base 1024 and the
    retry still boosts to max(1024*4, 8192) = 4096 — the fix is a no-op here
    (attempt_tokens == base), so the historical behavior is preserved."""
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _BoostedLaneRouter(_UNPARSEABLE_TRUNCATED)  # lane starts healthy
    runtime = AgentRuntime(world, router)

    await runtime.run_turn(agent)

    assert router.calls[0] == 1024      # base, not boosted
    assert router.calls[1] == 8192      # max(1024*4, 8192)

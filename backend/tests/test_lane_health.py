"""
EM-135 — reroute-aware lane health (first-attempt budget bump).

The proxy silently reroutes profiles to models that truncate (reasoning CoT
eats the budget; mistral-medium cuts mid-JSON while reporting 'stop' — runs
102/126). The retry boost rescues individual turns; lane health stops the
FIRST attempt failing repeatedly once a lane is known-bad:

  (A) Router unit: note_parse_outcome window → first_attempt_max_tokens boosts
      after ≥2 truncations, recovers on clean outcomes, and is flushed by
      clear_cache(). lane_health() exposes the introspection snapshot.
  (B) End-to-end (agents): a runtime whose responses parse ONLY via truncation
      repair still reports truncated=True, and the NEXT turn's attempt-1
      budget is bumped — then recovers once the lane runs clean.
  (C) End-to-end (animals): same wiring through AnimalRuntime._decide_via_llm.
  (D) Guarded getattr: duck-typed routers WITHOUT the EM-135 surface keep
      working unchanged.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from petridish.config.loader import WorldParams
from petridish.engine.world import World, AgentState, PlaceState, Animal
from petridish.providers.router import Router


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})

# Truncated mid-string: parses ONLY via the progressive truncation repair, and
# _looks_truncated says True — the lane is still cutting output.
_REPAIRABLE_TRUNCATED_ACTION = '{"action": "idle", "args": {}, "thought": "cut mid-sen'

_VALID_ANIMAL_JSON = json.dumps({"animal_thought": "zzz", "action": "nap", "args": {}})
_REPAIRABLE_TRUNCATED_ANIMAL = '{"action": "nap", "args": {}, "animal_thought": "sleepy bu'


# ──────────────────────────────────────────────────────────────────────────────
# (A) Router unit — outcome window, boost formula, recovery, reset, introspection
# ──────────────────────────────────────────────────────────────────────────────

def _router() -> Router:
    # No profiles needed: lane health is pure in-memory bookkeeping.
    return Router(profiles=[])


def test_boost_engages_after_two_truncations_in_window():
    r = _router()
    r.note_parse_outcome("lane", parsed=False, truncated=True)
    assert r.first_attempt_max_tokens("lane", 512) == 512  # one is noise
    r.note_parse_outcome("lane", parsed=True, truncated=True)  # repaired counts too
    # Same formula as the retry boost: max(base * 4, 2048).
    assert r.first_attempt_max_tokens("lane", 512) == 2048
    assert r.first_attempt_max_tokens("lane", 1024) == 4096


def test_healthy_lane_base_unchanged():
    r = _router()
    for _ in range(6):
        r.note_parse_outcome("lane", parsed=True, truncated=False)
    assert r.first_attempt_max_tokens("lane", 512) == 512
    # Unknown lane (no outcomes yet) → base.
    assert r.first_attempt_max_tokens("never-seen", 512) == 512


def test_unparsed_but_not_truncated_does_not_boost():
    # Prose-only garbage is a parse failure but NOT lane truncation — the
    # budget bump is truncation-specific.
    r = _router()
    for _ in range(6):
        r.note_parse_outcome("lane", parsed=False, truncated=False)
    assert r.first_attempt_max_tokens("lane", 512) == 512


def test_boost_disengages_after_clean_outcomes():
    r = _router()
    r.note_parse_outcome("lane", parsed=False, truncated=True)
    r.note_parse_outcome("lane", parsed=False, truncated=True)
    # Four clean outcomes: both truncations still inside the 6-wide window.
    for _ in range(4):
        r.note_parse_outcome("lane", parsed=True, truncated=False)
    assert r.first_attempt_max_tokens("lane", 512) == 2048
    # Two more clean outcomes push the truncations out — deque(maxlen=6)
    # flushes the flag with no extra bookkeeping.
    r.note_parse_outcome("lane", parsed=True, truncated=False)
    r.note_parse_outcome("lane", parsed=True, truncated=False)
    assert r.first_attempt_max_tokens("lane", 512) == 512


def test_clear_cache_flushes_lane_health():
    r = _router()
    r.note_parse_outcome("lane", parsed=False, truncated=True)
    r.note_parse_outcome("lane", parsed=False, truncated=True)
    assert r.first_attempt_max_tokens("lane", 512) == 2048

    r.clear_cache()  # world reset: prior-run evidence must not boost a new run
    assert r.first_attempt_max_tokens("lane", 512) == 512
    assert r.lane_health() == {}


def test_lane_health_introspection_snapshot():
    # An adapter override supplies last_routed_via so the snapshot records it.
    fake_adapter = SimpleNamespace(last_routed_via="mistral/mistral-medium-latest")
    r = Router(profiles=[], adapter_overrides={"lane": fake_adapter})

    r.note_parse_outcome("lane", parsed=True, truncated=True)
    r.note_parse_outcome("lane", parsed=False, truncated=True)

    health = r.lane_health()
    assert set(health) == {"lane"}
    assert health["lane"]["window"] == [
        {"parsed": True, "truncated": True},
        {"parsed": False, "truncated": True},
    ]
    assert health["lane"]["boosted"] is True
    assert health["lane"]["last_routed_via"] == "mistral/mistral-medium-latest"


def test_window_is_bounded_to_six_outcomes():
    r = _router()
    for _ in range(10):
        r.note_parse_outcome("lane", parsed=True, truncated=False)
    assert len(r.lane_health()["lane"]["window"]) == 6


# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures — minimal world + duck-typed routers
# ──────────────────────────────────────────────────────────────────────────────

def _world_with_agent() -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        recharge_cost=2, recharge_amount=20.0, work_reward=4, forage_reward=1,
        steal_max=5, death_after_zero_turns=10, memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="cleo", name="Cleo", personality="curious", profile="test",
        location="plaza", energy=88.0, credits=10,
    )
    world = World(params=params, places=places, agents=[agent])
    return agent, world


class _LaneAwareRouter:
    """Duck-typed runtime router that DELEGATES the EM-135 surface to a REAL
    Router instance, so the end-to-end wiring (guarded getattr in both
    runtimes) exercises the real lane-health logic. Records the max_tokens of
    every chat() call; `response` is swappable mid-test."""

    def __init__(self, response: str):
        self.response = response
        self.calls: list[int] = []
        self.lane = Router(profiles=[])

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None  # runtimes fall back to default budgets (agents 512, animals 256)

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls.append(max_tokens)
        return self.response

    def last_usage(self, profile_name):
        # The lying 'stop': truncation must be detected structurally.
        return {"input_tokens": 100, "output_tokens": 50, "latency_ms": 1.0,
                "finish_reason": "stop", "cached": False}

    def last_routed_via(self, profile_name):
        return "mistral/mistral-medium-latest"

    # ── EM-135 surface: the real implementation under test ──────────────────
    def first_attempt_max_tokens(self, profile_name, base):
        return self.lane.first_attempt_max_tokens(profile_name, base)

    def note_parse_outcome(self, profile_name, *, parsed, truncated):
        self.lane.note_parse_outcome(profile_name, parsed=parsed, truncated=truncated)


class _PlainDuckRouter:
    """Duck-typed router WITHOUT the EM-135 surface (like the test_json_mode
    routers) — the guarded getattr wiring must leave it fully functional."""

    def __init__(self, response: str):
        self.response = response
        self.calls: list[int] = []

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls.append(max_tokens)
        return self.response

    def last_usage(self, profile_name):
        return None

    def last_routed_via(self, profile_name):
        return None


# ──────────────────────────────────────────────────────────────────────────────
# (B) End-to-end, agents: repaired truncations still count; next turn is bumped
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_turns_record_repaired_truncations_and_bump_next_budget():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _LaneAwareRouter(_REPAIRABLE_TRUNCATED_ACTION)
    runtime = AgentRuntime(world, router)

    # Two turns whose responses parse ONLY via truncation repair: no
    # parse_failure surfaces, but BOTH outcomes must report truncated=True.
    for _ in range(2):
        event = await runtime.run_turn(agent)
        assert event["kind"] != "parse_failure"
    assert router.calls == [512, 512]  # evidence first, boost after
    assert router.lane.lane_health()["test"]["window"] == [
        {"parsed": True, "truncated": True},
        {"parsed": True, "truncated": True},
    ]

    # Third turn: the lane is known-bad → attempt 1 starts at the boosted cap.
    router.response = _VALID_ACTION_JSON
    await runtime.run_turn(agent)
    assert router.calls[2] == 2048


@pytest.mark.asyncio
async def test_agent_lane_recovers_after_clean_turns():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _LaneAwareRouter(_REPAIRABLE_TRUNCATED_ACTION)
    runtime = AgentRuntime(world, router)

    for _ in range(2):
        await runtime.run_turn(agent)
    router.response = _VALID_ACTION_JSON

    # Six clean turns flush both truncations out of the 6-wide window.
    for _ in range(6):
        await runtime.run_turn(agent)
    await runtime.run_turn(agent)
    assert router.calls[-1] == 512  # back to the base budget


@pytest.mark.asyncio
async def test_healthy_agent_lane_keeps_base_budget():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _LaneAwareRouter(_VALID_ACTION_JSON)
    runtime = AgentRuntime(world, router)

    for _ in range(3):
        await runtime.run_turn(agent)
    assert router.calls == [512, 512, 512]
    window = router.lane.lane_health()["test"]["window"]
    assert all(o == {"parsed": True, "truncated": False} for o in window)


# ──────────────────────────────────────────────────────────────────────────────
# (C) End-to-end, animals: same wiring through _decide_via_llm
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_animal_decisions_record_outcomes_and_bump_next_budget():
    from petridish.animals.runtime import AnimalRuntime

    _, world = _world_with_agent()
    animal = Animal(id="cat_1", species="cat", name="Mochi", location="plaza")
    router = _LaneAwareRouter(_REPAIRABLE_TRUNCATED_ANIMAL)
    runtime = AnimalRuntime(world, router)

    for _ in range(2):
        action_dict, _meta = await runtime._decide_via_llm(animal, world, "test")
        assert action_dict is not None  # repaired, not a dead turn
        assert action_dict["action"] == "nap"
    assert router.calls == [256, 256]  # animal default budget, unboosted

    router.response = _VALID_ANIMAL_JSON
    await runtime._decide_via_llm(animal, world, "test")
    assert router.calls[2] == 2048  # max(256 * 4, 2048)


# ──────────────────────────────────────────────────────────────────────────────
# (D) Guarded getattr — routers without the EM-135 surface work unchanged
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_turn_works_against_router_without_lane_surface():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _PlainDuckRouter(_VALID_ACTION_JSON)
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)
    assert event["kind"] != "parse_failure"
    assert router.calls == [512]  # base budget, no EM-135 methods consulted


@pytest.mark.asyncio
async def test_animal_decision_works_against_router_without_lane_surface():
    from petridish.animals.runtime import AnimalRuntime

    _, world = _world_with_agent()
    animal = Animal(id="cat_1", species="cat", name="Mochi", location="plaza")
    router = _PlainDuckRouter(_VALID_ANIMAL_JSON)
    runtime = AnimalRuntime(world, router)

    action_dict, _meta = await runtime._decide_via_llm(animal, world, "test")
    assert action_dict is not None
    assert action_dict["action"] == "nap"
    assert router.calls == [256]

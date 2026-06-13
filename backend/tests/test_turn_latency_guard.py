"""
Wave D2 / EM-170 — turn-latency guard.

Run 248 measured single LLM calls of 14-32s freezing the entire world because
the tick loop is strictly sequential. The guard wraps the FULL per-turn consult
(router.chat, including the adapter's internal retry chain) in
asyncio.wait_for(world.turn_llm_budget_seconds):

  (A) Stub adapter sleeping past the budget ⇒ the call is cancelled CLEANLY,
      the turn resolves via the EM-173 survival reflex (run 321: timeout
      idles starved Ada — a wall-clock timeout means the agent never got to
      speak, so instinct acts instead), the llm_call span carries
      timed_out:true + real elapsed ms, a lane demerit lands in the EM-135
      health window, and the NEXT agent's turn proceeds — the world never
      freezes.
  (B) Budget absent/0 ⇒ guard fully disabled: a slow call is NOT interrupted
      (byte-for-byte today's behavior).
  (C) Generous budget ⇒ a normal turn is untouched (no timed_out key anywhere).
  (D) A timed-out call never poisons the router's decision cache.
  (E) Config plumbing: both yamls ship the key at 12; absent parses to 0.
  (F) EM-173 — the survival reflex on timeout: starving⇒recharge, at-work⇒work,
      reflex events stamped payload.reflex + cadence_reason llm_timeout_reflex,
      ANY tier (protagonist included); reflex-validation failure falls through
      to the idle fallback; provider_error / parse failures STAY honest idles.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import yaml

from petridish.config.loader import (
    EMBEDDED_WORLD_YAML,
    WorldParams,
    _parse_world,
)
from petridish.engine.world import World, AgentState, PlaceState  # noqa: F401 — must precede agents.runtime
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.providers.base import ProviderError
from petridish.providers.router import Router


_VALID_ACTION = '{"action": "idle", "args": {}, "thought": "ok"}'


class _SlowAdapter:
    """Adapter stub whose chat() sleeps `delay` seconds before answering.
    Records call/cancel counts so tests can prove the guard cancelled the
    in-flight call cleanly (reaped, not abandoned)."""

    def __init__(self, delay: float, response: str = _VALID_ACTION):
        self.delay = delay
        self.response = response
        self.calls = 0
        self.cancelled = 0
        self.last_routed_via = "slow/model-x"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        self.last_usage = {
            "input_tokens": 100, "output_tokens": 20,
            "latency_ms": self.delay * 1000, "finish_reason": "stop",
            "cached": False,
        }
        return self.response


def _world(
    budget: float, n_agents: int = 1, *,
    place_kind: str = "social", energy: float = 90.0, credits: int = 10,
    **params_kw,
) -> tuple[list[AgentState], World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=90.0, starting_credits=10,
        memory_window=5, turn_llm_budget_seconds=budget, **params_kw,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind=place_kind)]
    agents = [
        AgentState(
            id=f"agent_{i}", name=f"Agent{i}", personality="curious",
            profile="lane", location="plaza", energy=energy, credits=credits,
        )
        for i in range(n_agents)
    ]
    world = World(params=params, places=places, agents=agents)
    return agents, world


def _runtime(budget: float, adapter, n_agents: int = 1, **world_kw):
    agents, world = _world(budget, n_agents, **world_kw)
    router = Router(profiles=[], adapter_overrides={"lane": adapter})
    return agents, world, router, AgentRuntime(world, router)


# ──────────────────────────────────────────────────────────────────────────────
# (A) Past-budget call ⇒ survival reflex, llm_timeout legible, demerit,
#     world moves on
# ──────────────────────────────────────────────────────────────────────────────

async def test_timeout_resolves_via_survival_reflex_with_llm_timeout_reflex():
    adapter = _SlowAdapter(delay=30.0)
    (agent, other), world, router, runtime = _runtime(0.05, adapter, n_agents=2)

    event = await runtime.run_turn(agent)

    # EM-173 — the wall-clock timeout resolves the EM-159 reflex routine (this
    # agent: not starving, not at work, no homes ⇒ forage), NOT an idle: the
    # agent never got to speak, so instinct acted. The timeout stays legible
    # on the event payload AND in the feed line itself.
    assert event["kind"] == "economy"
    assert event["payload"]["action"] == "forage"
    assert event["payload"]["reflex"] is True
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"
    assert "forages" in event["text"]
    assert "LLM call timed out — instinct took over" in event["text"]

    # ONE attempt only — a timed-out consult never retries (a retry would risk
    # stalling the world for a second budget). The reflex trace still carries
    # the timed-out llm_call span so the timeout stays inspectable.
    attempts = event["_trace"]["llm_attempts"]
    assert len(attempts) == 1
    span = attempts[0]
    assert span["timed_out"] is True
    assert isinstance(span["latency_ms"], float)
    assert span["latency_ms"] >= 50.0  # real elapsed ms, at least the budget
    assert event["_trace"]["reflex"] is True
    assert event["_trace"]["action_chosen"]["tier"] == "reflex"

    # Clean cancel: the in-flight adapter call was cancelled and reaped.
    assert adapter.calls == 1
    assert adapter.cancelled == 1

    # EM-135 lane demerit recorded via the same window truncation uses.
    lane = router.lane_health()["lane"]
    assert lane["window"] == [
        {"parsed": False, "truncated": False, "timed_out": True}
    ]
    assert lane["timeouts"] == 1

    # The world moves on: the NEXT agent's turn proceeds normally.
    adapter.delay = 0.0
    nxt = await runtime.run_turn(other)
    assert nxt["kind"] == "agent_action"
    assert nxt["payload"]["action"] == "idle"


async def test_timed_out_llm_call_event_payload_carries_flag_and_elapsed():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(0.05, adapter)

    event = await runtime.run_turn(agent)
    span = event["_trace"]["llm_attempts"][0]

    payload = TickLoop._llm_call_payload("lane", span)
    assert payload["timed_out"] is True
    assert payload["latency_ms"] == span["latency_ms"]
    # The pinned OTel key set is still fully present (timed_out is additive).
    assert {
        "gen_ai.request.model", "gen_ai.response.model",
        "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
        "latency_ms", "gen_ai.response.finish_reasons", "cached", "attempt",
    } <= set(payload)


# ──────────────────────────────────────────────────────────────────────────────
# (B) Budget absent / 0 ⇒ guard disabled — a slow call is NOT interrupted
# ──────────────────────────────────────────────────────────────────────────────

async def test_budget_zero_disables_guard_slow_call_not_interrupted():
    adapter = _SlowAdapter(delay=0.25)
    (agent,), world, router, runtime = _runtime(0.0, adapter)

    event = await runtime.run_turn(agent)

    assert event["kind"] == "agent_action"  # old behavior: it just waited
    assert adapter.calls == 1
    assert adapter.cancelled == 0
    span = event["_trace"]["llm_attempts"][0]
    assert "timed_out" not in span


async def test_budget_absent_defaults_to_disabled():
    # WorldParams default is 0.0 — built without the field, the guard is off.
    params = WorldParams()
    assert params.turn_llm_budget_seconds == 0.0

    adapter = _SlowAdapter(delay=0.2)
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="a1", name="Ada", personality="curious", profile="lane",
        location="plaza", energy=90.0, credits=10,
    )
    world = World(params=params, places=places, agents=[agent])
    router = Router(profiles=[], adapter_overrides={"lane": adapter})
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)
    assert event["kind"] == "agent_action"
    assert adapter.cancelled == 0


# ──────────────────────────────────────────────────────────────────────────────
# (C) Generous budget ⇒ normal turn untouched
# ──────────────────────────────────────────────────────────────────────────────

async def test_generous_budget_leaves_normal_turn_untouched():
    adapter = _SlowAdapter(delay=0.0)
    (agent,), world, router, runtime = _runtime(10.0, adapter)

    event = await runtime.run_turn(agent)

    assert event["kind"] == "agent_action"
    assert adapter.calls == 1
    assert adapter.cancelled == 0
    span = event["_trace"]["llm_attempts"][0]
    assert "timed_out" not in span
    payload = TickLoop._llm_call_payload("lane", span)
    assert "timed_out" not in payload  # non-timeout rows keep the exact key set

    # Lane window shows a clean parse — no timeout demerit, pre-EM-170 shape.
    lane = router.lane_health()["lane"]
    assert lane["window"] == [{"parsed": True, "truncated": False}]
    assert lane["timeouts"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# (D) A timed-out call never poisons the decision cache
# ──────────────────────────────────────────────────────────────────────────────

async def test_timeout_does_not_poison_decision_cache():
    adapter = _SlowAdapter(delay=30.0)
    # forage_reward=0 keeps the EM-173 forage reflex state-neutral, so the
    # next turn's prompt is byte-identical to the timed-out one — the exact
    # cache key a poisoned entry would be served under.
    (agent,), world, router, runtime = _runtime(0.05, adapter, forage_reward=0)

    event = await runtime.run_turn(agent)
    assert event["kind"] == "economy"  # EM-173: timeout ⇒ reflex (forage)
    assert event["payload"]["reflex"] is True
    # The cancelled call never reached the router's cache-store line.
    assert len(router._cache) == 0

    # Same agent, same world state ⇒ identical prompt ⇒ identical cache key:
    # a poisoned entry would be served HERE. Instead the adapter is consulted.
    adapter.delay = 0.0
    event = await runtime.run_turn(agent)
    assert event["kind"] == "agent_action"
    assert adapter.calls == 2

    # And the GOOD response cached normally: the third identical turn is a HIT.
    event = await runtime.run_turn(agent)
    assert event["kind"] == "agent_action"
    assert adapter.calls == 2  # served from cache, no third adapter call


# ──────────────────────────────────────────────────────────────────────────────
# (F) EM-173 — survival reflex on llm_timeout (run 321: timeout idles starved
#     Ada — the world-freeze fix must not be an agent-death sentence)
# ──────────────────────────────────────────────────────────────────────────────

class _ErrorAdapter:
    """Adapter stub whose chat() always raises ProviderError (content failure,
    NOT a wall-clock timeout — must stay an honest idle, never a reflex)."""

    def __init__(self):
        self.calls = 0
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError("lane", 502, "bad gateway")


async def test_timeout_while_starving_resolves_recharge_reflex():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(
        0.05, adapter, energy=10.0, credits=10  # starving, recharge affordable
    )

    event = await runtime.run_turn(agent)

    # Run 321's fix in one line: the timed-out turn RECHARGES instead of idling.
    assert event["kind"] == "economy"
    assert event["payload"]["action"] == "recharge"
    assert event["payload"]["reflex"] is True
    assert event["payload"]["reflex_streak"] == 1
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"
    assert agent.energy > 10.0
    assert agent.credits < 10  # paid the recharge cost

    # Feed line: the instinct action AND the timeout, both legible.
    assert "recharges" in event["text"]
    assert "LLM call timed out — instinct took over" in event["text"]

    # Trace: reflex-resolved, but the timed-out llm_call span still rides it
    # and the loop still emits its llm_call row with timed_out: true.
    trace = event["_trace"]
    assert trace["reflex"] is True
    assert trace["action_chosen"] == {
        "chosen_tool": "recharge", "args": {}, "tier": "reflex",
    }
    assert trace["resolved"]["outcome"] == "ok"
    assert len(trace["llm_attempts"]) == 1
    assert trace["llm_attempts"][0]["timed_out"] is True
    row = TickLoop._llm_call_payload("lane", trace["llm_attempts"][0])
    assert row["timed_out"] is True

    # EM-170 lane demerit unchanged by the reflex resolution.
    lane = router.lane_health()["lane"]
    assert lane["window"] == [
        {"parsed": False, "truncated": False, "timed_out": True}
    ]
    assert lane["timeouts"] == 1


async def test_timeout_at_work_place_resolves_work_reflex():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(0.05, adapter, place_kind="work")

    event = await runtime.run_turn(agent)

    assert event["kind"] == "economy"
    assert event["payload"]["action"] == "work"
    assert event["payload"]["reflex"] is True
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"
    assert agent.credits > 10  # earned the work reward


async def test_timeout_reflex_validation_failure_falls_through_to_idle():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(0.05, adapter)
    # Force a reflex pick the world's gates reject (target does not exist).
    runtime._reflex_pick = lambda a: {
        "action": "give", "args": {"target": "ghost", "amount": 1},
    }

    event = await runtime.run_turn(agent)

    # The EXISTING idle-fallback surface, reason llm_timeout — never a crash,
    # and no reflex markers on a turn that did not actually resolve one.
    assert event["kind"] == "parse_failure"
    assert "failed to produce a valid action (idle fallback)" in event["text"]
    assert event["payload"]["reason"].startswith("llm_timeout")
    assert "reflex" not in event["payload"]
    assert "cadence_reason" not in event["payload"]
    assert agent.reflex_streak == 0  # the failed reflex left no streak behind
    span = event["_trace"]["llm_attempts"][0]
    assert span["timed_out"] is True


async def test_provider_error_still_resolves_idle_not_reflex():
    # Regression pin: ONLY the wall-clock timeout earns the reflex. A content
    # failure (provider_error) stays an honest idle — even for a starving
    # agent who could afford to recharge.
    adapter = _ErrorAdapter()
    (agent,), world, router, runtime = _runtime(0.05, adapter, energy=10.0)

    event = await runtime.run_turn(agent)

    assert event["kind"] == "parse_failure"
    assert event["payload"]["reason"].startswith("provider_error")
    assert "reflex" not in event["payload"]
    assert "cadence_reason" not in event["payload"]
    assert agent.energy == 10.0  # no instinct recharge happened


async def test_protagonist_tier_gets_reflex_on_timeout_too():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(0.05, adapter, energy=10.0)
    agent.cadence_tier = "protagonist"  # explicit — never salience-gated

    event = await runtime.run_turn(agent)

    assert event["payload"]["action"] == "recharge"
    assert event["payload"]["reflex"] is True
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"


async def test_background_salient_timeout_gets_reflex_and_stays_salient():
    adapter = _SlowAdapter(delay=30.0)
    (agent,), world, router, runtime = _runtime(0.05, adapter)
    agent.cadence_tier = "background"  # first due turn: no baseline ⇒ salient

    event = await runtime.run_turn(agent)
    assert adapter.calls == 1
    assert event["payload"]["reflex"] is True
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"

    # The LLM never answered, so salience baselines were NOT re-noted: the
    # next due turn consults the LLM again instead of going quiet-reflex.
    event = await runtime.run_turn(agent)
    assert adapter.calls == 2
    assert event["payload"]["cadence_reason"] == "llm_timeout_reflex"


# ──────────────────────────────────────────────────────────────────────────────
# (E) Config plumbing — both yamls ship 12; absent parses to disabled
# ──────────────────────────────────────────────────────────────────────────────

def test_embedded_world_yaml_ships_budget_disabled():
    # The turn-latency guard is OFF by default: on free-tier accounts with a
    # large token budget, throttling turns to "save cost" only starves the
    # model-vs-model bake-off and mutes the world. The guard stays AVAILABLE
    # (set a positive value to re-enable), it is just not the shipped default.
    params, _, _ = _parse_world(yaml.safe_load(EMBEDDED_WORLD_YAML))
    assert params.turn_llm_budget_seconds == 0.0


def test_shipped_world_yaml_ships_budget_disabled():
    cfg_path = Path(__file__).resolve().parents[2] / "config" / "world.yaml"
    raw = yaml.safe_load(cfg_path.read_text())
    assert raw["world"]["turn_llm_budget_seconds"] == 0


def test_absent_key_parses_to_disabled():
    params, _, _ = _parse_world({"world": {}})
    assert params.turn_llm_budget_seconds == 0.0
    # Explicit 0 and null both disable.
    params, _, _ = _parse_world({"world": {"turn_llm_budget_seconds": 0}})
    assert params.turn_llm_budget_seconds == 0.0
    params, _, _ = _parse_world({"world": {"turn_llm_budget_seconds": None}})
    assert params.turn_llm_budget_seconds == 0.0

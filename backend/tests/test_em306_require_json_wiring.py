"""EM-306 — the strict-JSON reasoning-skip is WIRED, not dead.

The router's `require_json` bounce gate (spec P1: a reasoning-tagged lane is
skipped on a strict-JSON turn — the #77/#78 lesson, chain-of-thought eats the
budget and truncates before the JSON object appears) previously had NO
production caller. The natural strict-JSON call sites are the agent and animal
action turns: both parse the reply with _extract_first_json and schema-validate
it, so a reasoning lane serving them burns retries / dead-turns. Prose turns
(narrator, deep-dive) stay require_json=False — a reasoning lane is fine there.

These tests run END-TO-END through the real Router (adaptive ON, a reasoning-
tagged lane ranked FIRST in the sorting list) and prove the wire: a bounced
agent/animal turn lands on the plain lane with the reasoner untouched. If the
runtime ever drops the flag, the reasoner (top priority) serves and these fail.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime.
"""
from __future__ import annotations

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile, WorldParams,
)
from petridish.engine.world import AgentState, PlaceState, World
from petridish.agents.runtime import AgentRuntime
from petridish.animals.runtime import AnimalRuntime
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

pytestmark = pytest.mark.asyncio

_KEY_ENV = "EM_306_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]
_AGENT_JSON = '{"action": "idle", "args": {}}'
_ANIMAL_JSON = '{"animal_thought": "zzz", "action": "nap", "args": {}}'


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


class _OkAdapter:
    def __init__(self, name: str, text: str):
        self.name = name
        self.text = text
        self.calls = 0
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


class _FailAdapter:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError(self.name, 429, "Too Many Requests")


def _profile(name: str, model_id: str) -> ModelProfile:
    return ModelProfile(
        name=name, adapter="openai", model_id=model_id,
        max_tokens=512, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV,
    )


def _reasoner_first_router(json_text: str) -> tuple[Router, _OkAdapter, _OkAdapter]:
    """Pinned `lane` FAILS; the sorting list ranks a reasoning-tagged lane
    FIRST and a plain lane second. Only the require_json wire keeps a strict-
    JSON turn off the reasoner."""
    home = _FailAdapter("lane")
    reasoner = _OkAdapter("reasoner", json_text)
    plain = _OkAdapter("plain", json_text)
    profiles = [_profile("lane", "m-home"), _profile("reasoner", "reason-m"),
                _profile("plain", "m-plain")]
    ar = AdaptiveRoutingParams(
        enabled=True, max_attempts=3, allow_paid=False,
        per_attempt_timeout_s=12.0,
        order=(
            LaneOrderEntry("freellmapi", "reason-m", tags=("reasoning",)),
            LaneOrderEntry("freellmapi", "*"),
        ),
    )
    router = Router(
        profiles,
        adapter_overrides={"lane": home, "reasoner": reasoner, "plain": plain},
        cache_enabled=False, adaptive_routing=ar,
    )
    return router, reasoner, plain


def _world() -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=90.0, starting_credits=10,
        memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agent = AgentState(id="a1", name="Ann", personality="curious",
                       profile="lane", location="plaza", energy=90.0, credits=10)
    return agent, World(params=params, places=places, agents=[agent])


async def test_agent_turn_is_strict_json_and_skips_the_reasoning_lane():
    router, reasoner, plain = _reasoner_first_router(_AGENT_JSON)
    agent, world = _world()
    runtime = AgentRuntime(world, router)

    action, err, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, agent)

    assert err is None and action is not None and action["action"] == "idle"
    assert reasoner.calls == 0      # reasoning-tagged ⇒ skipped on a JSON turn
    assert plain.calls == 1         # the bounce landed on the plain lane
    assert meta["routed_via"] == "routed/plain"
    assert meta["usage"]["bounced_to"] == "plain"


async def test_animal_turn_is_strict_json_and_skips_the_reasoning_lane():
    router, reasoner, plain = _reasoner_first_router(_ANIMAL_JSON)
    _agent, world = _world()
    runtime = AnimalRuntime(world, router)

    action, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, attempt=1)

    assert action is not None and action["action"] == "nap"
    assert reasoner.calls == 0      # mirrors the agent runtime
    assert plain.calls == 1
    assert meta["routed_via"] == "routed/plain"


async def test_prose_chat_still_reaches_the_reasoning_lane():
    # The narrator/deep-dive path calls chat()/chat_attributed() WITHOUT
    # require_json — a reasoning lane is a fine prose narrator, so the
    # default must keep it reachable (the wire is per-call, not global).
    router, reasoner, plain = _reasoner_first_router("a fine chapter")
    text, attr = await router.chat_attributed(
        "lane", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "a fine chapter"
    assert reasoner.calls == 1 and plain.calls == 0
    assert attr["served_by"] == "reasoner"

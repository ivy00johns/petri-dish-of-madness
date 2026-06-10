"""
JSON-mode hardening for the prose-instead-of-action failure (T8 idle fallback).

Weak free models routed through FreeLLMAPI sometimes return a pure-prose
chain-of-thought with no JSON object at all, costing the agent a turn to the
idle fallback. Two defenses are tested here:

  (A) The OpenAI-compatible adapter asks for `response_format: json_object`.
  (B) Providers that don't understand `response_format` answer 4xx — the adapter
      must disable JSON mode and retry once WITHOUT it (sticky for its lifetime),
      so an unsupported provider degrades to plain prompting, not a dead turn.
  (C) The agent context ends with a user turn demanding JSON-only output, and
      drops the "chain of thought" wording that invites prose narration.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context
from petridish.providers.adapters import OpenAICompatibleAdapter


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})


# ──────────────────────────────────────────────────────────────────────────────
# Stub server that records every request and can reject response_format with 4xx
# ──────────────────────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # silence
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        self.server._requests.append(body)  # type: ignore[attr-defined]

        reject = self.server._reject_json_mode and "response_format" in body  # type: ignore[attr-defined]
        if reject:
            payload = {"error": {"message": "response_format is not supported by this model"}}
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        body_out = {"choices": [{"message": {"content": _VALID_ACTION_JSON}}]}
        self.wfile.write(json.dumps(body_out).encode())


class _Server(HTTPServer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._requests: list[dict] = []
        self._reject_json_mode: bool = False


@pytest.fixture()
def stub():
    server = _Server(("127.0.0.1", 0), _Handler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}/v1", server
    server.shutdown()
    thread.join(timeout=2)


def _adapter(base_url: str) -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        profile="test", base_url=base_url, api_key="k",
        model_id="m", color="#fff",
    )


# ──────────────────────────────────────────────────────────────────────────────
# (A) JSON mode requested by default
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_requests_json_object_by_default(stub):
    base_url, server = stub
    adapter = _adapter(base_url)

    await adapter.chat([{"role": "system", "content": "x"}], max_tokens=256, temperature=0.5)

    assert len(server._requests) == 1
    assert server._requests[0].get("response_format") == {"type": "json_object"}


# ──────────────────────────────────────────────────────────────────────────────
# (B) Provider rejects response_format → retry without it, stay disabled
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_falls_back_when_json_mode_rejected(stub):
    base_url, server = stub
    server._reject_json_mode = True
    adapter = _adapter(base_url)

    # Must NOT raise: degrade to plain prompting.
    result = await adapter.chat([{"role": "system", "content": "x"}], max_tokens=256, temperature=0.5)
    assert result == _VALID_ACTION_JSON

    # First attempt carried response_format (rejected), second dropped it.
    assert len(server._requests) == 2
    assert "response_format" in server._requests[0]
    assert "response_format" not in server._requests[1]


@pytest.mark.asyncio
async def test_adapter_stays_in_plain_mode_after_rejection(stub):
    base_url, server = stub
    server._reject_json_mode = True
    adapter = _adapter(base_url)

    await adapter.chat([{"role": "system", "content": "x"}], max_tokens=256, temperature=0.5)
    server._requests.clear()

    # Second turn must skip response_format entirely — no wasted rejected round-trip.
    await adapter.chat([{"role": "system", "content": "x"}], max_tokens=256, temperature=0.5)
    assert len(server._requests) == 1
    assert "response_format" not in server._requests[0]


# ──────────────────────────────────────────────────────────────────────────────
# (C) Agent context ends with a JSON-only user turn; no "chain of thought" bait
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


def test_context_ends_with_json_only_user_turn():
    agent, world = _world_with_agent()
    messages = _assemble_context(agent, world, [], world.params)

    assert messages[0]["role"] == "system"
    last = messages[-1]
    assert last["role"] == "user"
    assert "JSON" in last["content"]
    assert "{" in last["content"]  # explicit "begin with {" cue


def test_context_drops_chain_of_thought_bait():
    agent, world = _world_with_agent()
    messages = _assemble_context(agent, world, [], world.params)
    joined = " ".join(m["content"] for m in messages).lower()
    assert "chain of thought" not in joined


# ──────────────────────────────────────────────────────────────────────────────
# (D) Parse-failure message surfaces finish_reason + a wider text snippet, so a
#     reasoning model that ran out of tokens (finish_reason="length") before
#     emitting JSON is diagnosable from the feed instead of hidden by text[:200].
# ──────────────────────────────────────────────────────────────────────────────

def test_no_json_error_surfaces_finish_reason():
    from petridish.agents.runtime import _no_json_error

    msg = _no_json_error("reasoning prose with no braces", "length")
    assert "finish_reason='length'" in msg
    assert "reasoning prose" in msg


def test_no_json_error_widens_snippet_past_200():
    from petridish.agents.runtime import _no_json_error

    msg = _no_json_error("y" * 500, "stop")
    assert msg.count("y") > 200  # old cap was text[:200]


# ──────────────────────────────────────────────────────────────────────────────
# (E) Length-truncated first attempt retries with a BOOSTED token budget. The
#     proxy reroutes lanes to reasoning models (nemotron/gpt-oss/cogito seen
#     live) whose chain-of-thought eats the whole 512-token budget before any
#     JSON appears; retrying at the same budget failed identically every turn
#     and starved agents to death on idle fallbacks.
# ──────────────────────────────────────────────────────────────────────────────

def test_retry_max_tokens_boosts_on_length():
    from petridish.agents.runtime import _retry_max_tokens

    assert _retry_max_tokens(512, {"finish_reason": "length"}) == 2048
    assert _retry_max_tokens(1024, {"finish_reason": "length"}) == 4096


def test_retry_max_tokens_unchanged_otherwise():
    from petridish.agents.runtime import _retry_max_tokens

    assert _retry_max_tokens(512, {"finish_reason": "stop"}) == 512
    assert _retry_max_tokens(512, None) == 512
    assert _retry_max_tokens(512, {}) == 512


class _ReasoningRerouteRouter:
    """Duck-typed Router: attempt 1 returns truncated chain-of-thought with
    finish_reason=length; attempt 2 returns a valid action. Records the
    max_tokens of every call."""

    def __init__(self):
        self.calls: list[int] = []
        self._usage: dict | None = None

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None  # runtime falls back to max_tokens=512

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls.append(max_tokens)
        if len(self.calls) == 1:
            self._usage = {"input_tokens": 900, "output_tokens": 512,
                           "latency_ms": 1.0, "finish_reason": "length",
                           "cached": False}
            return "We need to output a valid JSON object with action first,"
        self._usage = {"input_tokens": 950, "output_tokens": 20,
                       "latency_ms": 1.0, "finish_reason": "stop",
                       "cached": False}
        return _VALID_ACTION_JSON

    def last_usage(self, profile_name):
        return self._usage

    def last_routed_via(self, profile_name):
        return "nvidia/nemotron-3-nano-30b-a3b"


@pytest.mark.asyncio
async def test_run_turn_retries_length_truncation_with_boosted_budget():
    from petridish.agents.runtime import AgentRuntime

    agent, world = _world_with_agent()
    router = _ReasoningRerouteRouter()
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)

    assert router.calls == [512, 2048]
    assert event["kind"] != "parse_failure"

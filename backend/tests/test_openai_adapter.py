"""
Priority 1: OpenAICompatibleAdapter end-to-end tests using a local stub server.

These tests de-risk the FreeLLMAPI live-run path WITHOUT spending a real token.
A threaded stdlib HTTP server mimics POST /v1/chat/completions, asserts the
required request shape, and returns well-formed responses.

Test coverage:
  - Happy path: stub → adapter.chat() returns content string
  - Full path: adapter output → AgentRuntime parse/validate → valid action applied
  - Failure path: stub returns 500 → ProviderError → runtime falls back to idle
  - Request shape assertions: Authorization header, model, messages, max_tokens
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import ModelProfile, WorldParams
from petridish.agents.runtime import AgentRuntime
from petridish.providers.adapters import OpenAICompatibleAdapter
from petridish.providers.base import ProviderError
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Stub HTTP server fixture
# ──────────────────────────────────────────────────────────────────────────────

class _StubHandler(BaseHTTPRequestHandler):
    """Handles POST /v1/chat/completions with configurable response."""

    def log_message(self, format: str, *args: Any) -> None:  # silence noisy logs
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)
        body = json.loads(body_bytes) if body_bytes else {}

        # Store request details for assertion
        self.server._last_request_headers = dict(self.headers)  # type: ignore[attr-defined]
        self.server._last_request_body = body  # type: ignore[attr-defined]

        status = self.server._response_status  # type: ignore[attr-defined]
        response = self.server._response_body  # type: ignore[attr-defined]

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


class StubHTTPServer(HTTPServer):
    """Extends HTTPServer with per-test configurable response state."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._response_status: int = 200
        self._response_body: dict = {}
        self._last_request_headers: dict = {}
        self._last_request_body: dict = {}


@pytest.fixture()
def stub_server():
    """Stand up a local stub server in a background thread; yield (url, server); tear down."""
    server = StubHTTPServer(("127.0.0.1", 0), _StubHandler)  # port 0 = OS-assigned
    host, port = server.server_address

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    base_url = f"http://{host}:{port}/v1"
    yield base_url, server

    server.shutdown()
    thread.join(timeout=2)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

_VALID_ACTION_JSON = json.dumps({
    "thought": "I need to earn credits.",
    "action": "work",
    "args": {},
})

_VALID_IDLE_JSON = json.dumps({
    "thought": "Nothing to do.",
    "action": "idle",
    "args": {},
})


def _make_adapter(base_url: str, model_id: str = "test-model") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        profile="test-openai",
        base_url=base_url,
        api_key="test-bearer-token",
        model_id=model_id,
        color="#ff0000",
    )


def _make_world_with_market() -> tuple[World, AgentState]:
    """Create a minimal world with one agent at the market (work place)."""
    params = WorldParams(
        energy_decay_per_turn=0.0,  # no decay, keep tests simple
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=10,
        memory_window=5,
    )
    places = [
        PlaceState(id="market", name="Market", x=0, y=0, kind="work"),
        PlaceState(id="plaza", name="Plaza", x=10, y=0, kind="social"),
    ]
    agent = AgentState(
        id="agent_test",
        name="TestAgent",
        personality="A test agent.",
        profile="test-openai",
        location="market",
        energy=80.0,
        credits=20,
    )
    world = World(params=params, places=places, agents=[agent])
    return world, agent


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: Happy path — adapter returns content string
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_happy_path_returns_content(stub_server):
    """Stub returns valid JSON; adapter.chat() returns the content string."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": _VALID_ACTION_JSON}}]
    }

    adapter = _make_adapter(base_url)
    messages = [{"role": "system", "content": "You are an agent."}]

    result = await adapter.chat(messages, max_tokens=256, temperature=0.7)
    assert result == _VALID_ACTION_JSON


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Request shape assertions
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_sends_correct_headers_and_body(stub_server):
    """Adapter must send Authorization: Bearer, model, messages, max_tokens."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": _VALID_IDLE_JSON}}]
    }

    model_id = "llama-3.3-70b-versatile"
    adapter = _make_adapter(base_url, model_id=model_id)
    messages = [
        {"role": "system", "content": "System prompt."},
        {"role": "user", "content": "What do you do?"},
    ]

    await adapter.chat(messages, max_tokens=512, temperature=0.8)

    # Assert Authorization header
    req_headers = server._last_request_headers
    auth = req_headers.get("Authorization") or req_headers.get("authorization", "")
    assert auth.startswith("Bearer "), f"Expected 'Bearer ...' auth header, got: {auth!r}"
    assert "test-bearer-token" in auth, f"Expected token in auth header, got: {auth!r}"

    # Assert body shape
    req_body = server._last_request_body
    assert req_body.get("model") == model_id, f"model mismatch: {req_body.get('model')!r}"
    assert "messages" in req_body, "messages field missing from request body"
    assert isinstance(req_body["messages"], list), "messages must be a list"
    assert len(req_body["messages"]) == 2
    assert "max_tokens" in req_body, "max_tokens field missing from request body"
    assert req_body["max_tokens"] == 512
    assert "temperature" in req_body, "temperature field missing"


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Full path — adapter → AgentRuntime parse/validate → action applied
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_full_path_action_applied(stub_server):
    """
    Full live-LLM-stub path:
      stub server → OpenAICompatibleAdapter → AgentRuntime parse/validate → work action applied.
    The agent is at a work place so 'work' is valid.
    """
    base_url, server = stub_server

    action_json = json.dumps({
        "thought": "I should earn credits at the market.",
        "action": "work",
        "args": {},
    })
    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": action_json}}]
    }

    world, agent = _make_world_with_market()
    credits_before = agent.credits

    # Build a Router that uses our OpenAICompatibleAdapter pointed at the stub
    profile = ModelProfile(
        name="test-openai",
        adapter="openai",
        model_id="test-model",
        max_tokens=256,
        temperature=0.7,
        color="#ff0000",
        base_url=base_url,
        api_key_env="",
    )

    adapter = _make_adapter(base_url)
    router = Router(
        profiles=[profile],
        adapter_overrides={"test-openai": adapter},
    )
    router.reassign(agent.id, "test-openai")

    runtime = AgentRuntime(world, router)
    result = await runtime.run_turn(agent)

    # Action was applied: work at market → credits increase
    assert result.get("kind") == "economy", (
        f"Expected economy event from work action, got kind={result.get('kind')!r}"
    )
    assert result.get("payload", {}).get("action") == "work"
    assert agent.credits == credits_before + world.params.work_reward, (
        f"Expected credits {credits_before + world.params.work_reward}, got {agent.credits}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: Full path — forage action (no place restriction)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_forage_action_applied(stub_server):
    """Stub returns forage action; verify credits increased."""
    base_url, server = stub_server

    action_json = json.dumps({
        "thought": "Forage for food.",
        "action": "forage",
        "args": {},
    })
    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": action_json}}]
    }

    world, agent = _make_world_with_market()
    credits_before = agent.credits
    profile = ModelProfile(
        name="test-openai",
        adapter="openai",
        model_id="test-model",
        max_tokens=256,
        temperature=0.7,
        color="#ff0000",
        base_url=base_url,
        api_key_env="",
    )
    adapter = _make_adapter(base_url)
    router = Router(profiles=[profile], adapter_overrides={"test-openai": adapter})
    router.reassign(agent.id, "test-openai")
    runtime = AgentRuntime(world, router)

    result = await runtime.run_turn(agent)

    assert result.get("kind") == "economy"
    assert result.get("payload", {}).get("action") == "forage"
    assert agent.credits == credits_before + world.params.forage_reward


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: Failure path — stub returns 500 → ProviderError → runtime falls back to idle
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_500_raises_provider_error(stub_server):
    """Stub returns 500 → adapter raises ProviderError (after retry)."""
    base_url, server = stub_server

    # Return 500 on every request (triggers 1 retry, then raises)
    server._response_status = 500
    server._response_body = {"error": "Internal server error"}

    adapter = _make_adapter(base_url)
    messages = [{"role": "system", "content": "You are an agent."}]

    with pytest.raises(ProviderError) as exc_info:
        await adapter.chat(messages, max_tokens=256, temperature=0.7)

    err = exc_info.value
    assert err.profile == "test-openai"
    # After retries, status should reflect the HTTP error
    assert err.status == 500 or err.status is None  # status from last failed attempt


@pytest.mark.asyncio
async def test_openai_adapter_500_runtime_falls_back_to_idle_no_crash(stub_server):
    """
    Full failure path:
      stub returns 500 → adapter raises ProviderError → AgentRuntime catches it
      → runtime falls back to idle (parse_failure event) → loop does NOT crash.
    """
    base_url, server = stub_server

    server._response_status = 500
    server._response_body = {"error": "Service unavailable"}

    world, agent = _make_world_with_market()
    credits_before = agent.credits

    profile = ModelProfile(
        name="test-openai",
        adapter="openai",
        model_id="test-model",
        max_tokens=256,
        temperature=0.7,
        color="#ff0000",
        base_url=base_url,
        api_key_env="",
    )
    adapter = _make_adapter(base_url)
    router = Router(profiles=[profile], adapter_overrides={"test-openai": adapter})
    router.reassign(agent.id, "test-openai")
    runtime = AgentRuntime(world, router)

    # This must NOT raise — ProviderError is caught, emits parse_failure
    result = await runtime.run_turn(agent)

    assert result.get("kind") == "parse_failure", (
        f"Expected parse_failure on 500 error, got kind={result.get('kind')!r}"
    )
    payload = result.get("payload", {})
    assert "provider_error" in str(payload.get("reason", "")), (
        f"Expected provider_error reason, got: {payload.get('reason')!r}"
    )
    # World state unchanged — no credits gained from failed turn
    assert agent.credits == credits_before, (
        f"Credits changed during failed turn: {credits_before} → {agent.credits}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: Adapter handles JSON wrapped in prose (model output with leading text)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_json_embedded_in_prose(stub_server):
    """Runtime can extract JSON from model output that includes surrounding prose."""
    base_url, server = stub_server

    # Simulate a verbose model that wraps JSON in prose
    prose_with_json = (
        'Here is my decision:\n'
        '{"thought": "Forage.", "action": "forage", "args": {}}\n'
        'That is what I will do.'
    )
    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": prose_with_json}}]
    }

    world, agent = _make_world_with_market()
    profile = ModelProfile(
        name="test-openai",
        adapter="openai",
        model_id="test-model",
        max_tokens=256,
        temperature=0.7,
        color="#ff0000",
        base_url=base_url,
        api_key_env="",
    )
    adapter = _make_adapter(base_url)
    router = Router(profiles=[profile], adapter_overrides={"test-openai": adapter})
    router.reassign(agent.id, "test-openai")
    runtime = AgentRuntime(world, router)

    result = await runtime.run_turn(agent)
    assert result.get("kind") == "economy"
    assert result.get("payload", {}).get("action") == "forage"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: Bad response shape → ProviderError
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_bad_response_shape_raises_provider_error(stub_server):
    """If stub returns 200 but wrong shape, adapter raises ProviderError."""
    base_url, server = stub_server

    # Missing 'choices' key entirely
    server._response_status = 200
    server._response_body = {"result": "unexpected"}

    adapter = _make_adapter(base_url)
    messages = [{"role": "user", "content": "Act now."}]

    with pytest.raises(ProviderError) as exc_info:
        await adapter.chat(messages, max_tokens=256, temperature=0.7)

    assert "unexpected response shape" in exc_info.value.detail


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: Invalid action → retry → idle fallback (no crash)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_openai_adapter_invalid_action_retries_then_idles(stub_server):
    """
    Stub always returns schema-invalid JSON → parse_failure on second attempt → idle.
    Verifies the retry mechanism works end-to-end with the real adapter.
    """
    base_url, server = stub_server

    # Return a JSON object with missing 'action' field (schema invalid)
    bad_json = json.dumps({"thought": "Hmm", "not_action": "work", "args": {}})
    server._response_status = 200
    server._response_body = {
        "choices": [{"message": {"content": bad_json}}]
    }

    world, agent = _make_world_with_market()
    profile = ModelProfile(
        name="test-openai",
        adapter="openai",
        model_id="test-model",
        max_tokens=256,
        temperature=0.7,
        color="#ff0000",
        base_url=base_url,
        api_key_env="",
    )
    adapter = _make_adapter(base_url)
    router = Router(profiles=[profile], adapter_overrides={"test-openai": adapter})
    router.reassign(agent.id, "test-openai")
    runtime = AgentRuntime(world, router)

    # Must NOT raise; should produce parse_failure
    result = await runtime.run_turn(agent)
    assert result.get("kind") == "parse_failure", (
        f"Expected parse_failure for schema-invalid response, got: {result.get('kind')!r}"
    )

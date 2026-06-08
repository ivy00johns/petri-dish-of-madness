"""
Regression tests for the `routed_via` feature ("which model actually answered").

Providers capture the proxy's 'X-Routed-Via' response header on each chat() and
surface it as `adapter.last_routed_via`. The Router exposes it per profile via
`Router.last_routed_via(profile)`, and AgentRuntime.run_turn injects it into the
emitted event payload(s) as `payload['routed_via']` (including the parse_failure
fallback path).

Coverage:
  1. OpenAICompatibleAdapter.chat() sets last_routed_via from the 'X-Routed-Via'
     response header when present.
  2. Fallback chain: header absent -> body 'model' field -> configured model_id.
  3. Router.last_routed_via(profile) returns the adapter's value for that profile.
  4. End-to-end via MockProvider: AgentRuntime.run_turn emits an event whose
     payload['routed_via'] == 'mock' (each sub-event for a _multi result).

Stubbing matches the pattern in test_openai_adapter.py: a threaded stdlib HTTP
server mimics POST /v1/chat/completions and returns a configurable response,
INCLUDING configurable extra response headers (so we can inject 'X-Routed-Via').
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest

from emergence.engine.world import World, AgentState, PlaceState
from emergence.config.loader import ModelProfile, WorldParams
from emergence.agents.runtime import AgentRuntime
from emergence.providers.adapters import OpenAICompatibleAdapter
from emergence.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Stub HTTP server fixture (mirrors test_openai_adapter.py, plus extra headers)
# ──────────────────────────────────────────────────────────────────────────────

class _StubHandler(BaseHTTPRequestHandler):
    """Handles POST /v1/chat/completions with a configurable body + headers."""

    def log_message(self, format: str, *args: Any) -> None:  # silence noisy logs
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(length)
        body = json.loads(body_bytes) if body_bytes else {}

        self.server._last_request_headers = dict(self.headers)  # type: ignore[attr-defined]
        self.server._last_request_body = body  # type: ignore[attr-defined]

        status = self.server._response_status  # type: ignore[attr-defined]
        response = self.server._response_body  # type: ignore[attr-defined]
        extra_headers = self.server._response_headers  # type: ignore[attr-defined]

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for key, value in extra_headers.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


class StubHTTPServer(HTTPServer):
    """Extends HTTPServer with per-test configurable response state."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._response_status: int = 200
        self._response_body: dict = {}
        self._response_headers: dict = {}
        self._last_request_headers: dict = {}
        self._last_request_body: dict = {}


@pytest.fixture()
def stub_server():
    """Stand up a local stub server in a background thread; yield (url, server)."""
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

def _make_adapter(base_url: str, model_id: str = "test-model") -> OpenAICompatibleAdapter:
    return OpenAICompatibleAdapter(
        profile="test-openai",
        base_url=base_url,
        api_key="test-bearer-token",
        model_id=model_id,
        color="#ff0000",
    )


def _chat_body(content: str = '{"action": "idle", "args": {}}', model: str | None = None) -> dict:
    body: dict = {"choices": [{"message": {"content": content}}]}
    if model is not None:
        body["model"] = model
    return body


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: last_routed_via comes from the 'X-Routed-Via' response header
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_last_routed_via_from_header(stub_server):
    """When the proxy returns 'X-Routed-Via', the adapter surfaces it verbatim."""
    base_url, server = stub_server

    server._response_status = 200
    # Header value differs from both the request model_id and the body 'model'
    # so we can prove the HEADER wins.
    server._response_headers = {"X-Routed-Via": "groq/llama-3.3-70b-versatile"}
    server._response_body = _chat_body(model="ignored-body-model")

    adapter = _make_adapter(base_url, model_id="test-model")
    messages = [{"role": "system", "content": "You are an agent."}]

    await adapter.chat(messages, max_tokens=256, temperature=0.7)

    assert adapter.last_routed_via == "groq/llama-3.3-70b-versatile", (
        f"Expected header value to win, got: {adapter.last_routed_via!r}"
    )


@pytest.mark.asyncio
async def test_adapter_header_lookup_is_case_insensitive(stub_server):
    """httpx headers are case-insensitive; a lowercase 'x-routed-via' still wins."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_headers = {"x-routed-via": "openrouter/mistral-large"}
    server._response_body = _chat_body(model="body-model")

    adapter = _make_adapter(base_url, model_id="cfg-model")
    await adapter.chat([{"role": "system", "content": "go"}], max_tokens=64, temperature=0.5)

    assert adapter.last_routed_via == "openrouter/mistral-large"


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: Fallback chain when the header is ABSENT
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adapter_falls_back_to_body_model_when_header_absent(stub_server):
    """No 'X-Routed-Via' header -> fall back to the response body 'model' field."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_headers = {}  # no X-Routed-Via
    server._response_body = _chat_body(model="body-resolved-model")

    adapter = _make_adapter(base_url, model_id="cfg-model")
    await adapter.chat([{"role": "system", "content": "go"}], max_tokens=64, temperature=0.5)

    assert adapter.last_routed_via == "body-resolved-model", (
        f"Expected fallback to body 'model', got: {adapter.last_routed_via!r}"
    )


@pytest.mark.asyncio
async def test_adapter_falls_back_to_model_id_when_header_and_body_model_absent(stub_server):
    """No header AND no body 'model' -> fall back to the configured model_id."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_headers = {}  # no X-Routed-Via
    server._response_body = _chat_body(model=None)  # no 'model' key in body

    adapter = _make_adapter(base_url, model_id="configured-model-id")
    await adapter.chat([{"role": "system", "content": "go"}], max_tokens=64, temperature=0.5)

    assert adapter.last_routed_via == "configured-model-id", (
        f"Expected fallback to configured model_id, got: {adapter.last_routed_via!r}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: Router.last_routed_via(profile) returns the adapter's value
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_last_routed_via_returns_adapter_value(stub_server):
    """Router.last_routed_via(profile) reflects the underlying adapter after chat()."""
    base_url, server = stub_server

    server._response_status = 200
    server._response_headers = {"X-Routed-Via": "proxy/picked-this-model"}
    server._response_body = _chat_body(model="body-model")

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

    # Before any call, nothing is known.
    assert router.last_routed_via("test-openai") is None

    await router.chat(
        "test-openai",
        [{"role": "system", "content": "go"}],
        max_tokens=256,
        temperature=0.7,
    )

    assert router.last_routed_via("test-openai") == "proxy/picked-this-model"
    # And it is the SAME value the adapter holds.
    assert router.last_routed_via("test-openai") == adapter.last_routed_via


def test_router_last_routed_via_unknown_profile_returns_none():
    """An unknown profile name yields None rather than raising."""
    profile = ModelProfile(name="mock", adapter="mock", model_id="mock")
    router = Router(profiles=[profile])
    assert router.last_routed_via("does-not-exist") is None


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: End-to-end via MockProvider -> payload['routed_via'] == 'mock'
# ──────────────────────────────────────────────────────────────────────────────

def _make_mock_world() -> tuple[World, AgentState]:
    """Minimal world with one agent on the mock profile, at a work place."""
    params = WorldParams(
        energy_decay_per_turn=0.0,
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
        id="agent_mock",
        name="MockAgent",
        personality="A scripted mock agent.",
        profile="mock",
        location="market",
        energy=80.0,
        credits=20,
    )
    world = World(params=params, places=places, agents=[agent])
    return world, agent


@pytest.mark.asyncio
async def test_run_turn_injects_routed_via_mock_end_to_end():
    """
    Wire World + Router(mock) + AgentRuntime as run.py does, run one turn, and
    assert the emitted event payload carries routed_via == 'mock'.
    """
    world, agent = _make_mock_world()

    mock_profile = ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")
    router = Router(profiles=[mock_profile])
    router.reassign(agent.id, "mock")
    router.inject_world(world)

    runtime = AgentRuntime(world, router)
    result = await runtime.run_turn(agent)

    # Sanity: the mock provider reports 'mock' as its routed_via.
    assert router.last_routed_via("mock") == "mock"

    if "_multi" in result:
        sub_events = result["_multi"]
        assert sub_events, "expected at least one sub-event in _multi result"
        for evt in sub_events:
            assert evt.get("payload", {}).get("routed_via") == "mock", (
                f"sub-event missing routed_via=='mock': {evt!r}"
            )
    else:
        assert result.get("payload", {}).get("routed_via") == "mock", (
            f"event payload missing routed_via=='mock': {result!r}"
        )


@pytest.mark.asyncio
async def test_run_turn_routed_via_present_across_multiple_mock_turns():
    """
    Run several mock turns; every emitted event (including any _multi sub-events)
    must carry payload['routed_via'] == 'mock'. This exercises varied action
    kinds from the scripted mock so the injection isn't action-specific.
    """
    world, agent = _make_mock_world()

    mock_profile = ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")
    router = Router(profiles=[mock_profile])
    router.reassign(agent.id, "mock")
    router.inject_world(world)

    runtime = AgentRuntime(world, router)

    seen_any = False
    for _ in range(6):
        result = await runtime.run_turn(agent)
        events = result["_multi"] if "_multi" in result else [result]
        for evt in events:
            seen_any = True
            assert evt.get("payload", {}).get("routed_via") == "mock", (
                f"event missing routed_via=='mock': {evt!r}"
            )
        world.tick += 1

    assert seen_any, "expected at least one emitted event across the runs"

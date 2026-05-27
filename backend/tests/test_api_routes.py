"""
Priority 2: API route coverage using FastAPI TestClient.

Tests all required endpoints from api.openapi.yaml:
  - GET  /api/health        → 200, {status, tick, running}
  - GET  /api/state         → 200, valid world_state shape
  - GET  /api/profiles      → 200, list with {name, adapter, model_id, color, available}
  - POST /api/agents/{id}/model → reassign profile; subsequent /api/state reflects it
  - POST /api/control/step  → advances tick by 1
  - POST /api/events/inject → returns ok

All agents are on 'mock' profile so steps produce deterministic state.
"""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

# ──────────────────────────────────────────────────────────────────────────────
# Force embedded config (mock adapters only) by unsetting config dir env vars
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """Create TestClient with the app using embedded (all-mock) config."""
    # Clear any config dir overrides so embedded defaults are used
    env_before = os.environ.copy()
    os.environ.pop("EM_CONFIG_DIR", None)

    # Import app after env is clean
    from emergence.api.app import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Restore env
    os.environ.clear()
    os.environ.update(env_before)


# ──────────────────────────────────────────────────────────────────────────────
# Helper: get first live agent id from state
# ──────────────────────────────────────────────────────────────────────────────

def _agents_by_id(state: dict) -> dict:
    """world_state.agents is a LIST (per events.schema.json); index it by id."""
    return {a["id"]: a for a in state.get("agents", [])}


def _first_agent_id(client: TestClient) -> str:
    state = client.get("/api/state").json()
    for agent in state.get("agents", []):
        if agent.get("alive", True):
            return agent["id"]
    raise RuntimeError("No live agents in world state")


def _all_agents_to_mock(client: TestClient) -> None:
    """Put every agent on the `mock` profile so turns are fast + deterministic
    (real profiles have no network in tests and incur slow failing retries)."""
    state = client.get("/api/state").json()
    for agent in state.get("agents", []):
        client.post(f"/api/agents/{agent['id']}/model", json={"profile": "mock"})


def _wait_for_tick(client: TestClient, target: int, timeout: float = 5.0) -> int:
    """Poll /api/state until tick >= target (step runs on the background asyncio task)."""
    import time
    deadline = time.time() + timeout
    tick = client.get("/api/state").json()["tick"]
    while tick < target and time.time() < deadline:
        time.sleep(0.05)
        tick = client.get("/api/state").json()["tick"]
    return tick


# ──────────────────────────────────────────────────────────────────────────────
# Test 1: GET /api/health
# ──────────────────────────────────────────────────────────────────────────────

def test_health_returns_200_and_shape(client):
    """GET /api/health returns 200 with {status, tick, running}."""
    resp = client.get("/api/health")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert "status" in body, f"Missing 'status' in health response: {body}"
    assert "tick" in body, f"Missing 'tick' in health response: {body}"
    assert "running" in body, f"Missing 'running' in health response: {body}"
    assert body["status"] == "ok"
    assert isinstance(body["tick"], int)
    assert isinstance(body["running"], bool)


# ──────────────────────────────────────────────────────────────────────────────
# Test 2: GET /api/state
# ──────────────────────────────────────────────────────────────────────────────

def test_state_returns_valid_world_state_shape(client):
    """GET /api/state returns 200 with world_state containing type, tick, agents, places, profiles."""
    resp = client.get("/api/state")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    state = resp.json()

    # Contract fields per world-model.md and WS snapshot shape
    assert "type" in state, f"Missing 'type' in world_state: {list(state.keys())}"
    assert "tick" in state, f"Missing 'tick' in world_state: {list(state.keys())}"
    assert "agents" in state, f"Missing 'agents' in world_state: {list(state.keys())}"
    assert "places" in state, f"Missing 'places' in world_state: {list(state.keys())}"

    # Tick must be non-negative integer
    assert isinstance(state["tick"], int) and state["tick"] >= 0

    # Agents must be a list (per events.schema.json) with required fields
    agents = state["agents"]
    assert isinstance(agents, list), f"agents should be list, got {type(agents)}"
    assert len(agents) >= 1, "World should have at least 1 agent"

    for agent in agents:
        assert "id" in agent, f"Agent missing id: {agent}"
        assert "name" in agent, f"Agent missing 'name': {agent}"
        assert "energy" in agent, f"Agent missing 'energy': {agent}"
        assert "credits" in agent, f"Agent missing 'credits': {agent}"
        assert "alive" in agent, f"Agent missing 'alive': {agent}"
        assert "location" in agent, f"Agent missing 'location': {agent}"
        assert "profile" in agent, f"Agent missing 'profile': {agent}"

        # Invariant checks
        assert isinstance(agent["energy"], (int, float))
        assert 0.0 <= agent["energy"] <= 100.0, f"Energy out of range: {agent['energy']}"
        assert agent["credits"] >= 0, f"Negative credits: {agent['credits']}"

    # Places must be present
    places = state["places"]
    assert isinstance(places, (dict, list)), f"places should be dict or list, got {type(places)}"
    if isinstance(places, dict):
        assert len(places) >= 1
    else:
        assert len(places) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# Test 3: GET /api/profiles
# ──────────────────────────────────────────────────────────────────────────────

def test_profiles_returns_legend_with_available_booleans(client):
    """GET /api/profiles returns list of {name, adapter, model_id, color, available}."""
    resp = client.get("/api/profiles")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    profiles = resp.json()
    assert isinstance(profiles, list), f"Expected list, got {type(profiles)}"
    assert len(profiles) >= 1, "Should have at least one profile (mock)"

    required_fields = {"name", "adapter", "model_id", "color", "available"}
    for p in profiles:
        missing = required_fields - set(p.keys())
        assert not missing, f"Profile missing fields {missing}: {p}"
        assert isinstance(p["available"], bool), f"available should be bool: {p['available']}"
        assert isinstance(p["name"], str) and p["name"], "name must be non-empty string"
        assert isinstance(p["color"], str), "color must be string"

    # Mock profile must always be available
    mock_profiles = [p for p in profiles if p["adapter"] == "mock"]
    assert len(mock_profiles) >= 1, "No mock profile found"
    for mp in mock_profiles:
        assert mp["available"] is True, f"mock profile should always be available: {mp}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 4: POST /api/agents/{id}/model — reassign + verify in state
# ──────────────────────────────────────────────────────────────────────────────

def test_reassign_agent_model_and_state_reflects_it(client):
    """POST /api/agents/{id}/model reassigns and /api/state reflects new profile."""
    agent_id = _first_agent_id(client)

    # Reassign to mock (always valid)
    resp = client.post(f"/api/agents/{agent_id}/model", json={"profile": "mock"})
    assert resp.status_code == 200, f"Expected 200 on reassign, got {resp.status_code}: {resp.text}"

    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("agent_id") == agent_id
    assert body.get("profile") == "mock"

    # Verify state reflects new profile
    state_resp = client.get("/api/state")
    assert state_resp.status_code == 200
    state = state_resp.json()
    agent = _agents_by_id(state)[agent_id]
    assert agent["profile"] == "mock", (
        f"State should show profile='mock' after reassign, got {agent['profile']!r}"
    )


def test_reassign_unknown_agent_returns_404(client):
    """POST /api/agents/nonexistent/model returns 404."""
    resp = client.post("/api/agents/nonexistent_agent_id_xyz/model", json={"profile": "mock"})
    assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"


def test_reassign_unknown_profile_returns_400(client):
    """POST /api/agents/{id}/model with unknown profile returns 400."""
    agent_id = _first_agent_id(client)
    resp = client.post(f"/api/agents/{agent_id}/model", json={"profile": "nonexistent-profile-xyz"})
    assert resp.status_code == 400, f"Expected 400, got {resp.status_code}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 5: POST /api/control/step — advances tick by 1
# ──────────────────────────────────────────────────────────────────────────────

def test_step_advances_tick_by_one(client):
    """POST /api/control/step advances tick by exactly 1."""
    _all_agents_to_mock(client)
    # Get tick before
    state_before = client.get("/api/state").json()
    tick_before = state_before["tick"]

    # Step
    resp = client.post("/api/control/step")
    assert resp.status_code == 200, f"Expected 200 on step, got {resp.status_code}: {resp.text}"
    assert resp.json().get("status") == "ok"

    # step runs on the background asyncio task — poll for it to land
    tick_after = _wait_for_tick(client, tick_before + 1)

    assert tick_after == tick_before + 1, (
        f"Expected tick to advance from {tick_before} to {tick_before + 1}, got {tick_after}"
    )


def test_multiple_steps_advance_tick_correctly(client):
    """Multiple POST /api/control/step calls each advance tick by 1."""
    _all_agents_to_mock(client)
    state_before = client.get("/api/state").json()
    tick_before = state_before["tick"]

    n_steps = 3
    for _ in range(n_steps):
        resp = client.post("/api/control/step")
        assert resp.status_code == 200

    tick_after = _wait_for_tick(client, tick_before + n_steps)

    assert tick_after == tick_before + n_steps, (
        f"Expected tick to advance by {n_steps} (from {tick_before}), got {tick_after}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Test 6: POST /api/events/inject — returns ok
# ──────────────────────────────────────────────────────────────────────────────

def test_inject_event_returns_ok(client):
    """POST /api/events/inject (no body) returns 200 with status ok."""
    resp = client.post("/api/events/inject")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body.get("status") == "ok", f"Expected status=ok, got {body}"


def test_inject_event_with_kind_returns_ok(client):
    """POST /api/events/inject with explicit kind returns ok."""
    for kind in ["windfall", "famine", "festival", "blackout"]:
        resp = client.post("/api/events/inject", json={"kind": kind})
        assert resp.status_code == 200, (
            f"Expected 200 for kind={kind!r}, got {resp.status_code}: {resp.text}"
        )
        body = resp.json()
        assert body.get("status") == "ok", f"Expected status=ok for kind={kind!r}, got {body}"


def test_inject_event_windfall_increases_credits(client):
    """POST /api/events/inject windfall increases all agents' credits by 5."""
    state_before = client.get("/api/state").json()
    credits_before = {
        aid: a["credits"]
        for aid, a in _agents_by_id(state_before).items()
        if a.get("alive", True)
    }

    client.post("/api/events/inject", json={"kind": "windfall"})

    state_after = client.get("/api/state").json()
    credits_after = {
        aid: a["credits"]
        for aid, a in _agents_by_id(state_after).items()
        if a.get("alive", True)
    }

    for aid in credits_before:
        if aid in credits_after:
            assert credits_after[aid] == credits_before[aid] + 5, (
                f"Agent {aid}: expected credits {credits_before[aid] + 5}, got {credits_after[aid]}"
            )


def test_inject_event_invalid_kind_returns_400(client):
    """POST /api/events/inject with invalid kind returns 400."""
    resp = client.post("/api/events/inject", json={"kind": "tornado"})
    assert resp.status_code == 400, f"Expected 400 for invalid kind, got {resp.status_code}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 7: GET /api/config
# ──────────────────────────────────────────────────────────────────────────────

def test_config_returns_world_params(client):
    """GET /api/config returns valid world configuration."""
    resp = client.get("/api/config")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    config = resp.json()

    required_params = [
        "tick_interval_seconds", "energy_decay_per_turn",
        "starting_energy", "starting_credits", "work_reward",
    ]
    for param in required_params:
        assert param in config, f"Missing config param '{param}': {list(config.keys())}"


# ──────────────────────────────────────────────────────────────────────────────
# Test 8: POST /api/control/start and /api/control/pause
# ──────────────────────────────────────────────────────────────────────────────

def test_start_and_pause_return_ok(client):
    """Start and pause control endpoints return 200."""
    # Start
    resp = client.post("/api/control/start")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("running") is True

    # Pause immediately
    resp = client.post("/api/control/pause")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "ok"
    assert body.get("running") is False

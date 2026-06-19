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
    """Create a TestClient and neutralize the W8 chaos-animal layer so stepping
    is deterministic.

    The repo config (loaded via .env's EM_CONFIG_DIR, which dotenv applies with
    override=True at import) enables network-LLM cat/dog animals on a real
    profile. On cadence-aligned ticks an animal rolls an LLM call that blocks the
    whole turn ~5s against the absent local proxy — making /api/control/step
    flaky. Agents are forced to `mock` per-test via _all_agents_to_mock(), but
    animals have no per-entity model hook, so we disable them at the source on
    the built world right after lifespan."""
    import sys
    from petridish.api.app import app
    # `petridish.api.app` the *name* resolves to the FastAPI instance (the package
    # __init__ does `from .app import app`), so reach the real module via sys.modules.
    _appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as c:
        # Lifespan has built the world; kill the chaos layer for determinism.
        if _appmod._world is not None:
            _appmod._world.params.animals.enabled = False
            _appmod._world.animals.clear()
        yield c


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
    """POST /api/control/step advances tick by exactly 1 and returns the new tick
    only AFTER the turn has completed (synchronous step — no polling/race)."""
    _all_agents_to_mock(client)
    client.post("/api/control/pause")  # deterministic single-stepping
    tick_before = client.get("/api/state").json()["tick"]

    resp = client.post("/api/control/step")
    assert resp.status_code == 200, f"Expected 200 on step, got {resp.status_code}: {resp.text}"
    assert resp.json().get("status") == "ok"
    # The step endpoint awaits turn completion, so the new tick is authoritative now.
    assert resp.json()["tick"] == tick_before + 1, (
        f"Expected step to return tick {tick_before + 1}, got {resp.json().get('tick')}"
    )
    assert client.get("/api/state").json()["tick"] == tick_before + 1


def test_multiple_steps_advance_tick_correctly(client):
    """Each POST /api/control/step advances tick by exactly 1, deterministically."""
    _all_agents_to_mock(client)
    client.post("/api/control/pause")
    tick_before = client.get("/api/state").json()["tick"]

    n_steps = 3
    for i in range(1, n_steps + 1):
        resp = client.post("/api/control/step")
        assert resp.status_code == 200
        assert resp.json()["tick"] == tick_before + i, (
            f"After {i} step(s), expected tick {tick_before + i}, got {resp.json().get('tick')}"
        )

    assert client.get("/api/state").json()["tick"] == tick_before + n_steps


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


# ──────────────────────────────────────────────────────────────────────────────
# Backfill model-chip regression: /api/events must carry profile_color
# ──────────────────────────────────────────────────────────────────────────────

def test_events_backfill_includes_profile_color(client):
    """The live-feed model chip needs profile_color, which is NOT a stored column
    (only the live WS broadcast stamps it via loop._get_profile_color). Backfilled
    events from /api/events must therefore have profile_color DERIVED from profile,
    or history renders chip-less (the resume/fork made this stark). Regression:
    profile_color was null for every backfilled event."""
    _all_agents_to_mock(client)
    client.post("/api/control/pause")
    for _ in range(3):
        client.post("/api/control/step")

    events = client.get("/api/events?order=desc&limit=200").json()
    profiled = [e for e in events if e.get("profile")]
    assert profiled, "expected some backfilled events to carry a profile"
    bad = [
        e for e in profiled
        if not (isinstance(e.get("profile_color"), str)
                and e["profile_color"].startswith("#"))
    ]
    assert not bad, (
        f"{len(bad)}/{len(profiled)} backfilled events have a profile but no hex "
        f"profile_color (model chip would not render). e.g. {bad[0] if bad else None}"
    )


def test_replay_events_include_profile_color(client):
    """Same enrichment for the inspector scrub path (/api/replay returns the
    fold-forward event delta), so scrubbed history shows model chips too."""
    _all_agents_to_mock(client)
    client.post("/api/control/pause")
    for _ in range(2):
        client.post("/api/control/step")
    tick = client.get("/api/state").json()["tick"]

    replay = client.get(f"/api/replay?tick={tick}").json()
    profiled = [e for e in replay.get("events", []) if e.get("profile")]
    bad = [
        e for e in profiled
        if not (isinstance(e.get("profile_color"), str)
                and e["profile_color"].startswith("#"))
    ]
    assert not bad, f"{len(bad)} replay events have a profile but no hex profile_color"

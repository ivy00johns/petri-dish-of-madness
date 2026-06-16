"""
A/B opt-in variant spawn tests — run-663.

Contracts under test:
  - POST /api/agents with ab_models=[p1, p2] in god mode spawns exactly one
    agent per model, each named "{name}·{tag}" where tag is the first '-'
    segment of the profile name (or the whole name when no '-' is present).
  - Every model in ab_models must be a known profile; an unknown one → 400.
  - The response body is {status:"ok", mode:"god",
    agents:[{agent_id, name, profile}, ...]} with status 201.
  - Omitting ab_models leaves single-spawn behavior byte-identical.
  - Profiles available in the test suite: mock (the only offline-safe one;
    we register two aliases "mock-a" and "mock-b" via the router override so
    we can test distinguishable labels without a network).

Deterministic and offline (MockProvider, ':memory:' DB, no network). Harness
idioms follow test_w11b / test_w11a.
"""
from __future__ import annotations

import sys

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _client_with_profiles(extra_profiles: list[dict]):
    """Return a TestClient whose app is initialized with the default test
    config PLUS any extra ModelProfile entries injected via adapter_overrides
    so offline tests can use named profiles without a live API.

    We inject the extra profiles by patching _router directly after the app
    lifespan initialises the singleton, which is the same technique used in
    test_w11b for the persona tests."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    from petridish.config.loader import ModelProfile
    from petridish.providers.router import Router

    client = TestClient(app, raise_server_exceptions=True)
    appmod = sys.modules["petridish.api.app"]

    # Register extra profiles on the live _router singleton so get_profile()
    # resolves them and reassign() can route to them.  The mock adapter is
    # reused for all — we only care about profile identity, not LLM output.
    for pd in extra_profiles:
        prof = ModelProfile(
            name=pd["name"],
            adapter="mock",
            model_id=pd["name"],
            color="#aaa",
        )
        # _router._profiles is the canonical registry dict (name → profile).
        appmod._router._profiles[prof.name] = prof

    return client, appmod


# ──────────────────────────────────────────────────────────────────────────────
# 1. Happy path — two variants spawn with correct names + profiles
# ──────────────────────────────────────────────────────────────────────────────

def test_ab_variants_spawn_two_agents_with_tagged_names():
    """Posting ab_models=[mistral-small, groq-llama] spawns two agents named
    '<base>·mistral' and '<base>·groq' on the respective profiles."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # Register the two profiles on the live router so they resolve offline.
        from petridish.config.loader import ModelProfile
        for pname in ("mistral-small", "groq-llama"):
            prof = ModelProfile(name=pname, adapter="mock", model_id=pname,
                                color="#aaa")
            appmod._router._profiles[pname] = prof

        resp = client.post("/api/agents", json={
            "name": "Atlas",
            "personality": "curious",
            "ab_models": ["mistral-small", "groq-llama"],
            "mode": "god",
        })

        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["mode"] == "god"
        agents = body["agents"]
        assert len(agents) == 2

        # Build a lookup by profile for order-independent checking.
        by_profile = {a["profile"]: a for a in agents}
        assert set(by_profile.keys()) == {"mistral-small", "groq-llama"}

        assert by_profile["mistral-small"]["name"] == "Atlas·mistral"
        assert by_profile["groq-llama"]["name"] == "Atlas·groq"

        # Verify the agents actually exist in the world.
        world_agents = appmod._world.agents
        mistral_id = by_profile["mistral-small"]["agent_id"]
        groq_id = by_profile["groq-llama"]["agent_id"]
        assert world_agents[mistral_id].profile == "mistral-small"
        assert world_agents[groq_id].profile == "groq-llama"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tag derivation — first '-' segment becomes the label
# ──────────────────────────────────────────────────────────────────────────────

def test_ab_variants_tag_uses_first_dash_segment():
    """Profile 'kimi' (no dash) → tag 'kimi'; 'cerebras-glm' → tag 'cerebras'."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        from petridish.config.loader import ModelProfile
        for pname in ("kimi", "cerebras-glm"):
            prof = ModelProfile(name=pname, adapter="mock", model_id=pname,
                                color="#aaa")
            appmod._router._profiles[pname] = prof

        resp = client.post("/api/agents", json={
            "name": "Nova",
            "personality": "bold",
            "ab_models": ["kimi", "cerebras-glm"],
            "mode": "god",
        })

        assert resp.status_code == 201, resp.text
        agents = resp.json()["agents"]
        names = {a["name"] for a in agents}
        assert "Nova·kimi" in names
        assert "Nova·cerebras" in names


# ──────────────────────────────────────────────────────────────────────────────
# 3. Unknown profile in ab_models → 400
# ──────────────────────────────────────────────────────────────────────────────

def test_ab_variants_unknown_profile_returns_400():
    """An unregistered profile name in ab_models must produce a 400."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/agents", json={
            "name": "Ghost",
            "personality": "mysterious",
            "ab_models": ["mock", "no-such-model-xyz"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "no-such-model-xyz" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 4. Omitting ab_models → unchanged single-spawn response shape
# ──────────────────────────────────────────────────────────────────────────────

def test_single_spawn_unchanged_when_no_ab_models():
    """Omitting ab_models produces the original {status, agent_id, mode} shape."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/agents", json={
            "name": "Singleton",
            "profile": "mock",
            "mode": "god",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "ok"
        assert body["mode"] == "god"
        assert "agent_id" in body
        # Must NOT have the 'agents' list key — keeps the old contract.
        assert "agents" not in body


# ──────────────────────────────────────────────────────────────────────────────
# 5. ab_group in agent_spawned event payload ties variants together
# ──────────────────────────────────────────────────────────────────────────────

def test_ab_variants_events_carry_ab_group():
    """Each agent_spawned event for an A/B pair must carry payload.ab_group
    equal to the requested base name so the UI can correlate them."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        from petridish.config.loader import ModelProfile
        for pname in ("mistral-small", "groq-llama"):
            prof = ModelProfile(name=pname, adapter="mock", model_id=pname,
                                color="#aaa")
            appmod._router._profiles[pname] = prof

        resp = client.post("/api/agents", json={
            "name": "Zeta",
            "personality": "analytical",
            "ab_models": ["mistral-small", "groq-llama"],
            "mode": "god",
        })
        assert resp.status_code == 201, resp.text

        # Pull the agent_spawned events from the event log and check ab_group.
        run_id = appmod._loop._run_id
        events = appmod._repo.get_events(run_id, kinds=["agent_spawned"])
        ab_events = [e for e in events
                     if e.get("payload", {}).get("ab_group") == "Zeta"]
        assert len(ab_events) == 2, (
            f"Expected 2 ab_group='Zeta' events, got {len(ab_events)}: {events}"
        )

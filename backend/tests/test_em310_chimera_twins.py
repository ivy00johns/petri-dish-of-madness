"""EM-310 — Chimera Twins spawn endpoint tests.

Contracts under test:
  - POST /api/agents with twin_models=[p1, p2] (god mode, flag ON) spawns
    EXACTLY two agents sharing name/personality/starting state, named by the
    Vesper / Vesper II dedup convention, cross-linked via each agent's `twin`
    key, and returns {status:"ok", mode:"god", twins:[...]} with status 201.
  - Both agent_spawned events carry payload.twin_group (the shared base name)
    and payload.twin_of (the peer id) so the client twin lens correlates them.
  - The flag is DEFAULT OFF: twin_models with the flag off → 400.
  - Guards: exactly two DISTINCT known profiles; god mode only; mutually
    exclusive with ab_models.
  - Omitting twin_models leaves single-spawn + ab_models behavior byte-identical
    (covered by test_ab_variants.py; a smoke assert here too).

Deterministic and offline (MockProvider, ':memory:' DB, no network). Harness
idioms follow test_ab_variants.py — the flag is flipped on the live _config
singleton after the app lifespan initialises it.
"""
from __future__ import annotations

import sys

from fastapi.testclient import TestClient

from petridish.api.app import app
from petridish.config.loader import ModelProfile


def _register(appmod, *names: str) -> None:
    for pname in names:
        prof = ModelProfile(name=pname, adapter="mock", model_id=pname,
                            color="#aaa")
        appmod._router._profiles[pname] = prof


def _enable_twins(appmod, on: bool = True) -> None:
    """Flip world.chimera_twins.enabled on the live config singleton."""
    appmod._config.world.chimera_twins.enabled = on


# ── happy path ────────────────────────────────────────────────────────────────

def test_twin_spawn_creates_linked_vesper_pair():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama")
        _enable_twins(appmod, True)

        # Base name chosen to be ABSENT from the seed roster (which already holds
        # a "Vesper") so the dedup demonstrates the clean base / base II split.
        resp = client.post("/api/agents", json={
            "name": "Zephyrine",
            "personality": "wary, quick to judge",
            "twin_models": ["gemini-flash", "groq-llama"],
            "mode": "god",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "ok" and body["mode"] == "god"
        twins = body["twins"]
        assert len(twins) == 2

        names = [t["name"] for t in twins]
        # Zephyrine / Zephyrine II — the dedup convention renames the second.
        assert names[0] == "Zephyrine"
        assert names[1] == "Zephyrine II"
        assert {t["profile"] for t in twins} == {"gemini-flash", "groq-llama"}

        # Both agents carry a cross-link pointing at the other. The shared
        # `group` is the requested base name (before dedup).
        a_id, b_id = twins[0]["agent_id"], twins[1]["agent_id"]
        agents = appmod._world.agents
        assert agents[a_id].twin == {
            "group": "Zephyrine", "of": b_id, "model": "gemini-flash"}
        assert agents[b_id].twin == {
            "group": "Zephyrine", "of": a_id, "model": "groq-llama"}

        # Byte-identical starting state — only the model differs.
        assert agents[a_id].personality == agents[b_id].personality
        assert agents[a_id].energy == agents[b_id].energy
        assert agents[a_id].credits == agents[b_id].credits
        assert agents[a_id].location == agents[b_id].location


def test_twin_spawn_events_carry_twin_group_and_peer():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Ada",
            "twin_models": ["gemini-flash", "groq-llama"],
            "mode": "god",
        })
        assert resp.status_code == 201, resp.text

        run_id = appmod._loop._run_id
        events = appmod._repo.get_events(run_id, kinds=["agent_spawned"])
        twin_events = [e for e in events
                       if e.get("payload", {}).get("twin_group") == "Ada"]
        assert len(twin_events) == 2, twin_events
        # each event names the OTHER twin as its peer.
        peers = {e["payload"]["agent_id"]: e["payload"]["twin_of"]
                 for e in twin_events}
        ids = list(peers.keys())
        assert peers[ids[0]] == ids[1]
        assert peers[ids[1]] == ids[0]


# ── flag gate ─────────────────────────────────────────────────────────────────

def test_twin_spawn_rejected_when_flag_disabled():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama")
        _enable_twins(appmod, False)  # DEFAULT-OFF path

        resp = client.post("/api/agents", json={
            "name": "Vesper",
            "twin_models": ["gemini-flash", "groq-llama"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "chimera_twins" in resp.json()["detail"]


# ── guards ────────────────────────────────────────────────────────────────────

def test_twin_spawn_requires_exactly_two_models():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama", "mistral-small")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Trio",
            "twin_models": ["gemini-flash", "groq-llama", "mistral-small"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "EXACTLY two" in resp.json()["detail"]


def test_twin_spawn_requires_distinct_models():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Clone",
            "twin_models": ["gemini-flash", "gemini-flash"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "DISTINCT" in resp.json()["detail"]


def test_twin_spawn_unknown_profile_returns_400():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Ghost",
            "twin_models": ["gemini-flash", "no-such-model-xyz"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "no-such-model-xyz" in resp.json()["detail"]


def test_twin_spawn_rejects_governance_mode():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Vesper",
            "twin_models": ["gemini-flash", "groq-llama"],
            "mode": "governance",
        })
        assert resp.status_code == 400
        assert "god mode" in resp.json()["detail"]


def test_twin_and_ab_models_mutually_exclusive():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _register(appmod, "gemini-flash", "groq-llama")
        _enable_twins(appmod, True)

        resp = client.post("/api/agents", json={
            "name": "Vesper",
            "twin_models": ["gemini-flash", "groq-llama"],
            "ab_models": ["gemini-flash", "groq-llama"],
            "mode": "god",
        })
        assert resp.status_code == 400
        assert "mutually exclusive" in resp.json()["detail"]


# ── unchanged paths (smoke) ──────────────────────────────────────────────────

def test_single_spawn_unchanged_and_untwinned():
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as client:
        _enable_twins(appmod, True)  # flag on must NOT alter a normal spawn
        resp = client.post("/api/agents", json={
            "name": "Solo", "profile": "mock", "mode": "god",
        })
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert "twins" not in body
        agent = appmod._world.agents[body["agent_id"]]
        assert agent.twin is None

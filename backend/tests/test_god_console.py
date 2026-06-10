"""Wave A.2 god console — targeted interventions (EM-136) + god whisper (EM-137).

Proves the god can reach ONE agent instead of the whole world: god_intervene
blesses energy (clamped at 100) / grants credits with validated amounts, and
post_whisper_as_god queues a line that rides ONLY the target agent's NEXT
prompt, exactly once. Engine/context halves are pure unit tests calling
world seams + _assemble_context directly (the test_proclamation idiom); the
API half pins POST /api/god/intervene + /api/god/whisper (200/422/503) with
the TestClient (the test_w11b idiom).

Contracts under test:
  - contracts/wave-a2-god-console.md — Agent G section (request shapes are
    fixed: {kind, agent_id, amount?} and {agent_id, text}).
  - Free-scale law: zero LLM calls — intervene is a pure state mutation +
    event; whisper is context injection only.
"""
from __future__ import annotations

import sys

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )


def _world() -> World:
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id="ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
        AgentState(id="bo", name="Bo", personality="", profile="mock",
                   location="market", energy=80.0, credits=20),
    ]
    return World(params=_params(), places=places, agents=agents)


def _system_prompt(world: World, agent: AgentState) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ──────────────────────────────────────────────────────────────────────────────
# 1. EM-136 — god_intervene engine seam (bless / grant / validation / event).
# ──────────────────────────────────────────────────────────────────────────────

def test_bless_energy_adds_and_clamps_at_100():
    world = _world()
    ada = world.agents["ada"]
    ada.energy = 90.0

    evt = world.god_intervene("bless_energy", "ada", 25)

    assert ada.energy == 100.0, "energy must clamp at 100"
    assert evt["kind"] == "god_intervention"
    assert evt["actor_id"] == "god"
    assert evt["actor_type"] == "god"
    assert evt["target_id"] == "ada"
    assert evt["payload"] == {"kind": "bless_energy", "amount": 25,
                              "before": 90.0, "after": 100.0}
    assert "✦ god restores Ada — +25 energy" in evt["text"]


def test_grant_credits_adds():
    world = _world()
    bo = world.agents["bo"]

    evt = world.god_intervene("grant_credits", "bo", 40)

    assert bo.credits == 60
    assert evt["target_id"] == "bo"
    assert evt["payload"] == {"kind": "grant_credits", "amount": 40,
                              "before": 20, "after": 60}
    assert "✦ god favors Bo — +40 credits" in evt["text"]


def test_default_amounts_are_25_energy_and_10_credits():
    world = _world()
    ada = world.agents["ada"]

    evt = world.god_intervene("bless_energy", "ada")
    assert evt["payload"]["amount"] == 25
    assert ada.energy == 100.0  # 80 + 25 clamped

    evt = world.god_intervene("grant_credits", "ada")
    assert evt["payload"]["amount"] == 10
    assert ada.credits == 30


def test_amount_validated_1_to_100():
    world = _world()
    for bad in (0, 101, -5, "lots"):
        with pytest.raises(ValueError):
            world.god_intervene("bless_energy", "ada", bad)
    # Boundaries are inclusive.
    assert world.god_intervene("grant_credits", "ada", 1)["payload"]["amount"] == 1
    assert world.god_intervene("grant_credits", "ada", 100)["payload"]["amount"] == 100


def test_unknown_kind_and_unknown_agent_raise():
    world = _world()
    with pytest.raises(ValueError):
        world.god_intervene("smite", "ada")
    with pytest.raises(ValueError):
        world.god_intervene("bless_energy", "nobody")


def test_dead_agents_are_beyond_the_gods_reach():
    world = _world()
    world.kill_agent("bo")
    # Resurrection is explicitly out of scope: no bless, no grant, no whisper.
    with pytest.raises(ValueError):
        world.god_intervene("bless_energy", "bo")
    with pytest.raises(ValueError):
        world.god_intervene("grant_credits", "bo")
    with pytest.raises(ValueError):
        world.post_whisper_as_god("bo", "rise")


# ──────────────────────────────────────────────────────────────────────────────
# 2. EM-137 — post_whisper_as_god queues + emits; delivery is one-shot and
#    targeted (present on the NEXT context only, never other agents').
# ──────────────────────────────────────────────────────────────────────────────

def test_whisper_queues_and_returns_the_event():
    world = _world()

    evt = world.post_whisper_as_god("ada", "The market hides a fortune.")

    assert world.pending_whispers == {"ada": ["The market hides a fortune."]}
    assert evt["kind"] == "whisper_posted"
    assert evt["actor_id"] == "god"
    assert evt["actor_type"] == "god"
    assert evt["target_id"] == "ada"
    assert evt["payload"] == {"agent_id": "ada",
                              "text": "The market hides a fortune."}
    # Spectator app: the feed line names the target AND carries the content.
    assert "✦ god whispers to Ada" in evt["text"]
    assert "The market hides a fortune." in evt["text"]


def test_whisper_text_capped_at_280_and_empty_rejected():
    world = _world()
    evt = world.post_whisper_as_god("ada", "x" * 500)
    assert evt["payload"]["text"] == "x" * 280
    with pytest.raises(ValueError):
        world.post_whisper_as_god("ada", "   ")
    with pytest.raises(ValueError):
        world.post_whisper_as_god("nobody", "hello?")


def test_whisper_rides_exactly_the_next_context_once():
    world = _world()
    world.post_whisper_as_god("ada", "Bo cannot be trusted.")

    # The whisper rides Ada's NEXT prompt, clearly framed...
    sp = _system_prompt(world, world.agents["ada"])
    assert "A VOICE ONLY YOU CAN HEAR" in sp
    assert "Bo cannot be trusted." in sp
    # ...and assembly IS the consumption: the following turn has no trace.
    sp2 = _system_prompt(world, world.agents["ada"])
    assert "A VOICE ONLY YOU CAN HEAR" not in sp2
    assert "Bo cannot be trusted." not in sp2
    assert world.pending_whispers.get("ada", []) == []


def test_whisper_never_reaches_other_agents():
    world = _world()
    world.post_whisper_as_god("ada", "Only for Ada.")

    # Bo's context (assembled BEFORE Ada consumes hers) carries nothing.
    bo_sp = _system_prompt(world, world.agents["bo"])
    assert "A VOICE ONLY YOU CAN HEAR" not in bo_sp
    assert "Only for Ada." not in bo_sp
    # Ada still gets it — Bo's assembly must not have consumed her queue.
    assert "Only for Ada." in _system_prompt(world, world.agents["ada"])


def test_multiple_pending_whispers_deliver_together_once():
    world = _world()
    world.post_whisper_as_god("ada", "First whisper.")
    world.post_whisper_as_god("ada", "Second whisper.")

    sp = _system_prompt(world, world.agents["ada"])
    assert "First whisper." in sp and "Second whisper." in sp
    sp2 = _system_prompt(world, world.agents["ada"])
    assert "First whisper." not in sp2 and "Second whisper." not in sp2


def test_pending_whispers_stay_out_of_the_snapshot_surface():
    world = _world()
    world.post_whisper_as_god("ada", "ephemeral")
    # Ephemeral by design: not serialized, so a restore drops undelivered ones.
    assert "pending_whispers" not in world.to_snapshot()


# ──────────────────────────────────────────────────────────────────────────────
# 3. API — POST /api/god/intervene + /api/god/whisper (200 / 422 / 503),
#    events persisted with actor_type god + target_id (the test_w11b idiom).
# ──────────────────────────────────────────────────────────────────────────────

def test_god_intervene_api_200_mutates_and_persists():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        agent = appmod._world.living_agents()[0]
        agent.energy = 40.0
        credits_before = agent.credits

        resp = client.post("/api/god/intervene",
                           json={"kind": "bless_energy", "agent_id": agent.id,
                                 "amount": 30})
        assert resp.status_code == 200
        assert agent.energy == 70.0

        # amount omitted → the seam's grant default (+10).
        resp = client.post("/api/god/intervene",
                           json={"kind": "grant_credits", "agent_id": agent.id})
        assert resp.status_code == 200
        assert agent.credits == credits_before + 10

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["god_intervention"])
        assert len(rows) == 2
        for row in rows:
            assert row["actor_type"] == "god"
            assert row["actor_id"] == "god"
            assert row["target_id"] == agent.id
        assert rows[0]["payload"] == {"kind": "bless_energy", "amount": 30,
                                      "before": 40.0, "after": 70.0}
        assert rows[1]["payload"]["kind"] == "grant_credits"


def test_god_intervene_api_422s_do_not_emit():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        agent = appmod._world.living_agents()[0]
        bad_bodies = [
            {"kind": "smite", "agent_id": agent.id},            # unknown kind
            {"kind": "bless_energy", "agent_id": "nobody"},     # unknown agent
            {"kind": "bless_energy", "agent_id": agent.id, "amount": 0},
            {"kind": "bless_energy", "agent_id": agent.id, "amount": 101},
        ]
        for body in bad_bodies:
            assert client.post("/api/god/intervene", json=body).status_code == 422

        # Dead agents 422 too (resurrection is out of scope).
        appmod._world.kill_agent(agent.id)
        assert client.post(
            "/api/god/intervene",
            json={"kind": "grant_credits", "agent_id": agent.id},
        ).status_code == 422

        assert appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["god_intervention"]) == [], \
            "rejected interventions must not emit"


def test_god_whisper_api_200_queues_and_persists():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        agent = appmod._world.living_agents()[0]
        resp = client.post("/api/god/whisper",
                           json={"agent_id": agent.id, "text": "Seek the plaza."})
        assert resp.status_code == 200
        assert appmod._world.pending_whispers[agent.id] == ["Seek the plaza."]

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["whisper_posted"])
        assert len(rows) == 1
        assert rows[0]["actor_type"] == "god"
        assert rows[0]["target_id"] == agent.id
        assert rows[0]["payload"] == {"agent_id": agent.id,
                                      "text": "Seek the plaza."}


def test_god_whisper_api_422s():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        agent = appmod._world.living_agents()[0]
        # Empty / whitespace / oversized text and unknown agent all 422.
        assert client.post("/api/god/whisper",
                           json={"agent_id": agent.id, "text": ""}).status_code == 422
        assert client.post("/api/god/whisper",
                           json={"agent_id": agent.id, "text": "   "}).status_code == 422
        assert client.post("/api/god/whisper",
                           json={"agent_id": agent.id,
                                 "text": "x" * 281}).status_code == 422
        assert client.post("/api/god/whisper",
                           json={"agent_id": "nobody",
                                 "text": "hello?"}).status_code == 422
        assert appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["whisper_posted"]) == [], \
            "rejected whispers must not emit"


def test_god_endpoints_503_when_uninitialized():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        saved_world = appmod._world
        try:
            appmod._world = None
            assert client.post(
                "/api/god/intervene",
                json={"kind": "bless_energy", "agent_id": "x"},
            ).status_code == 503
            assert client.post(
                "/api/god/whisper",
                json={"agent_id": "x", "text": "hello"},
            ).status_code == 503
        finally:
            appmod._world = saved_world

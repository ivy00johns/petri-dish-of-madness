"""
Wave E / B5 — EM-184 world-scale god miracles (contracts/wave-e.md §B5).

Covers the full B5 acceptance list:
  · send_rain: forage yield boosted while active, normal after expiry;
    miracle_expired emitted exactly once; refresh-not-stack proven
  · bountiful_harvest scales energy decay by harvest_decay_factor only
    while active
  · calm_spirits: moods set 'hopeful', trust nudged + clamped through the
    B1 reflex seam (a friend transition CAN fire and its
    relationship_changed rides the SAME emission batch — the god path
    drains the B1 outbox itself, QE carry-over), no duration entry left
  · API matrix: world kind + agent_id ⇒ 422; targeted kind without
    agent_id ⇒ 422; existing bless/grant behavior unchanged (regression)
  · snapshot round-trip mid-rain: buff survives resume, expires on
    schedule; `active_miracles` key ADDITIVE (absent ⇒ [])
  · enabled:false ⇒ world kinds rejected, targeted kinds untouched
  · god_miracle is importance-weighted 2.0 + globally witnessed
    (pre-ratified runtime.py constant entries)
  · config block parsing (defaults, overrides, malformed values) + the
    EMBEDDED_WORLD_YAML mirror stays in sync

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import sys

import pytest
import yaml

from petridish.engine.world import (
    AgentState,
    Building,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import (
    EMBEDDED_WORLD_YAML,
    MiracleParams,
    WorldParams,
    _parse_miracles,
)
from petridish.agents.runtime import _IMPORTANCE_WEIGHTS, AgentRuntime
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider
from petridish.config.loader import ModelProfile


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    p = WorldParams(
        turns_per_day=10,
        energy_decay_per_turn=4.0,
        forage_reward=1,
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]


def _agent(aid: str, name: str, location: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=80.0, credits=20)


def _world(agents: list[AgentState] | None = None, **param_overrides) -> World:
    agents = agents if agents is not None else [
        _agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
    ]
    return World(params=_params(**param_overrides), places=_places(),
                 agents=agents)


def _rel(world: World, a_id: str, b_id: str, *, type: str = "neutral",
         trust: int = 0, interactions: int = 0) -> RelationshipState:
    rel = RelationshipState(type=type, trust=trust, interactions=interactions)
    world.agents[a_id].relationships[b_id] = rel
    return rel


# ══════════════════════════════════════════════════════════════════════════════
# 1. send_rain — timed forage buff (active / expiry / refresh-not-stack)
# ══════════════════════════════════════════════════════════════════════════════

def test_send_rain_buffs_forage_while_active_and_normal_after_expiry():
    world = _world()
    ada = world.agents["agent_ada"]

    ok, _, base = world.action_forage(ada)
    assert ok and base == 1, "pre-miracle forage is the plain reward"

    events = world.god_intervene("send_rain")
    assert isinstance(events, list) and len(events) == 1
    evt = events[0]
    assert evt["kind"] == "god_miracle"
    assert evt["actor_id"] == "god" and evt["actor_type"] == "god"
    assert evt["target_id"] is None and evt["turn_id"] is None
    # rain_days(2) × turns_per_day(10) from tick 0.
    assert evt["payload"] == {"kind": "send_rain", "until_tick": 20}
    assert world.miracle_active("send_rain")

    ok, _, buffed = world.action_forage(ada)
    assert ok and buffed == 1 + 2, "rain adds rain_forage_bonus on top of base"

    # Expiry boundary: tick == until_tick ⇒ inactive (the blackout convention).
    world.tick = 20
    assert not world.miracle_active("send_rain")
    ok, _, after = world.action_forage(ada)
    assert ok and after == 1, "yield returns to normal after expiry"


def test_send_rain_stacks_with_garden_bonus_not_instead_of_it():
    """Contract item 2: the rain bonus lands ON TOP of base + garden bonus."""
    world = _world()
    ada = world.agents["agent_ada"]
    world.buildings["bld_garden"] = Building(
        id="bld_garden", name="Garden", kind="garden", location="plaza",
        status="operational")
    garden_bonus = world._bld_param("forage_bonus", 0)
    assert garden_bonus > 0, "the default garden forage_bonus must be real"

    ok, _, before = world.action_forage(ada)
    assert ok and before == 1 + garden_bonus

    world.god_intervene("send_rain")
    ok, _, buffed = world.action_forage(ada)
    assert ok and buffed == 1 + garden_bonus + 2


def test_recasting_an_active_miracle_refreshes_until_tick_never_stacks():
    world = _world()
    world.god_intervene("send_rain")
    assert world.active_miracles == [{"kind": "send_rain", "until_tick": 20}]

    world.tick = 5
    events = world.god_intervene("send_rain")
    # ONE entry, until_tick refreshed to 5 + 20; no duplicate.
    assert world.active_miracles == [{"kind": "send_rain", "until_tick": 25}]
    assert events[0]["payload"]["until_tick"] == 25

    # The buff is single-strength even after a re-cast (refresh ≠ stack).
    ada = world.agents["agent_ada"]
    ok, _, reward = world.action_forage(ada)
    assert ok and reward == 1 + 2


def test_miracle_expired_emitted_exactly_once():
    world = _world()
    world.god_intervene("send_rain")

    world.tick = 19
    assert world.expire_miracles() == [], "still active: nothing expires"

    world.tick = 20
    events = world.expire_miracles()
    assert len(events) == 1
    evt = events[0]
    assert evt["kind"] == "miracle_expired"
    assert evt["actor_id"] is None and evt["actor_type"] == "system"
    assert evt["target_id"] is None and evt["turn_id"] is None
    assert evt["payload"] == {"kind": "send_rain", "until_tick": 20}
    assert "rains pass" in evt["text"]
    assert world.active_miracles == []

    # Sweeping again is a no-op: exactly once.
    assert world.expire_miracles() == []


# ══════════════════════════════════════════════════════════════════════════════
# 2. bountiful_harvest — timed decay factor
# ══════════════════════════════════════════════════════════════════════════════

def test_bountiful_harvest_halves_decay_only_while_active():
    world = _world()
    ada = world.agents["agent_ada"]

    world.apply_energy_decay(ada)
    assert ada.energy == 76.0, "pre-miracle decay is the plain rate"

    events = world.god_intervene("bountiful_harvest")
    assert events[0]["payload"] == {"kind": "bountiful_harvest",
                                    "until_tick": 20}
    world.apply_energy_decay(ada)
    assert ada.energy == 74.0, "active harvest halves the 4.0 decay to 2.0"

    world.tick = 20  # expired
    world.apply_energy_decay(ada)
    assert ada.energy == 70.0, "full decay resumes after expiry"


def test_rain_and_harvest_are_independent_kinds():
    world = _world()
    world.god_intervene("send_rain")
    assert world.miracle_active("send_rain")
    assert not world.miracle_active("bountiful_harvest")
    world.god_intervene("bountiful_harvest")
    assert len(world.active_miracles) == 2


# ══════════════════════════════════════════════════════════════════════════════
# 3. calm_spirits — one-time mood + trust nudge through the B1 seam
# ══════════════════════════════════════════════════════════════════════════════

def test_calm_spirits_sets_moods_nudges_trust_clamps_and_leaves_no_entry():
    world = _world()
    world.agents["agent_ada"].mood = "anxious"
    world.agents["agent_bram"].mood = "angry"
    # Warm relationship near the +100 clamp; reverse direction untouched
    # (zero interactions ⇒ skipped).
    _rel(world, "agent_ada", "agent_bram", type="friend", trust=99,
         interactions=7)
    _rel(world, "agent_bram", "agent_ada", type="friend", trust=10,
         interactions=0)

    events = world.god_intervene("calm_spirits")

    assert world.agents["agent_ada"].mood == "hopeful"
    assert world.agents["agent_bram"].mood == "hopeful"
    rel = world.agents["agent_ada"].relationships["agent_bram"]
    assert rel.trust == 100, "trust nudge clamps at +100 (99 + 3 → 100)"
    assert world.agents["agent_bram"].relationships["agent_ada"].trust == 10, \
        "interactions == 0 relationships are untouched"
    # ONE-TIME: no duration entry, nothing to expire, payload has no until_tick.
    assert world.active_miracles == []
    assert world.expire_miracles() == []
    assert events[0]["kind"] == "god_miracle"
    assert events[0]["payload"] == {"kind": "calm_spirits"}


def test_calm_spirits_b1_transition_rides_the_same_batch_outbox_empty():
    """QE carry-over (ratified): _update_trust parks relationship_changed in
    the pending_relationship_events outbox, which only runtime._apply_action
    drains — god mutations happen outside any action turn, so calm_spirits
    MUST drain it itself. trust 28 + calm bonus 3 crosses the friend
    threshold (30) ⇒ the relationship_changed is returned WITH the miracle."""
    world = _world()
    _rel(world, "agent_ada", "agent_bram", type="neutral", trust=28,
         interactions=5)

    events = world.god_intervene("calm_spirits")

    kinds = [e["kind"] for e in events]
    assert kinds == ["god_miracle", "relationship_changed"]
    shift = events[1]
    assert shift["actor_id"] == "agent_ada"
    assert shift["target_id"] == "agent_bram"
    assert shift["turn_id"] is None, "god batch is outside any turn chain"
    assert shift["payload"]["from_type"] == "neutral"
    assert shift["payload"]["to_type"] == "friend"
    assert shift["payload"]["trust"] == 31
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "friend"
    assert world.pending_relationship_events == [], \
        "the outbox must be drained by the calm_spirits path itself"


def test_calm_spirits_ignores_dead_agents_entirely():
    world = _world(agents=[
        _agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
        _agent("agent_mox", "Mox"),
    ])
    _rel(world, "agent_ada", "agent_mox", type="friend", trust=20,
         interactions=4)
    world.kill_agent("agent_mox")
    world.agents["agent_mox"].mood = "content"

    world.god_intervene("calm_spirits")

    assert world.agents["agent_mox"].mood == "content", \
        "the dead keep their last mood"
    assert world.agents["agent_ada"].relationships["agent_mox"].trust == 20, \
        "relationships toward the dead are not nudged"


# ══════════════════════════════════════════════════════════════════════════════
# 4. god_intervene validation matrix (engine seam)
# ══════════════════════════════════════════════════════════════════════════════

def test_world_kinds_reject_an_agent_id():
    world = _world()
    for kind in ("send_rain", "bountiful_harvest", "calm_spirits"):
        with pytest.raises(ValueError):
            world.god_intervene(kind, "agent_ada")
    assert world.active_miracles == [], "rejected casts must not mutate"


def test_targeted_kinds_require_an_agent_id():
    world = _world()
    with pytest.raises(ValueError):
        world.god_intervene("bless_energy")
    with pytest.raises(ValueError):
        world.god_intervene("grant_credits", None)


def test_targeted_bless_and_grant_stay_byte_identical():
    """Regression for the EM-136 contract: the targeted kinds still return the
    single god_intervention event DICT with the exact pre-E payload shape."""
    world = _world()
    evt = world.god_intervene("bless_energy", "agent_ada", 25)
    assert isinstance(evt, dict), "targeted kinds return a dict, not a batch"
    assert evt["kind"] == "god_intervention"
    assert evt["payload"] == {"kind": "bless_energy", "amount": 25,
                              "before": 80.0, "after": 100.0}
    with pytest.raises(ValueError):
        world.god_intervene("smite", "agent_ada")  # unknown kind still rejected


# ══════════════════════════════════════════════════════════════════════════════
# 5. enabled: false — world kinds rejected, targeted kinds untouched
# ══════════════════════════════════════════════════════════════════════════════

def test_enabled_false_rejects_world_kinds_targeted_untouched():
    world = _world(miracles=MiracleParams(enabled=False))
    for kind in ("send_rain", "bountiful_harvest", "calm_spirits"):
        with pytest.raises(ValueError):
            world.god_intervene(kind)
    assert world.active_miracles == []
    assert world.agents["agent_ada"].mood != "hopeful"
    # Targeted kinds are untouched by the toggle.
    evt = world.god_intervene("grant_credits", "agent_ada", 5)
    assert evt["payload"]["after"] == 25


def test_enabled_false_world_is_byte_identical_pre_e():
    """With miracles disabled (and absent — pre-E configs), economy math and
    the snapshot key set are exactly the pre-E bytes."""
    disabled = _world(miracles=MiracleParams(enabled=False))
    absent = _world(miracles=None)
    for world in (disabled, absent):
        ada = world.agents["agent_ada"]
        world.apply_energy_decay(ada)
        assert ada.energy == 76.0
        ok, _, reward = world.action_forage(ada)
        assert ok and reward == 1
        assert "active_miracles" not in world.to_snapshot()


# ══════════════════════════════════════════════════════════════════════════════
# 6. Snapshot round-trip (ADDITIVE key; mid-rain resume)
# ══════════════════════════════════════════════════════════════════════════════

def test_active_miracles_snapshot_key_only_when_non_empty():
    world = _world()
    assert "active_miracles" not in world.to_snapshot(), \
        "no active miracle ⇒ the pre-E key set, byte-identical"
    world.god_intervene("send_rain")
    assert world.to_snapshot()["active_miracles"] == [
        {"kind": "send_rain", "until_tick": 20}
    ]


def test_pre_e_snapshot_restores_empty_active_miracles():
    snap = _world().to_snapshot()
    assert "active_miracles" not in snap
    restored = World.from_snapshot(snap, params=_params())
    assert restored.active_miracles == []


def test_mid_rain_snapshot_round_trip_buff_survives_and_expires_on_schedule():
    world = _world()
    world.god_intervene("send_rain")
    world.tick = 12  # mid-rain (until_tick 20)
    snap = world.to_snapshot()

    restored = World.from_snapshot(snap, params=_params())
    assert restored.active_miracles == [
        {"kind": "send_rain", "until_tick": 20}]
    assert restored.miracle_active("send_rain")
    ada = restored.agents["agent_ada"]
    ok, _, reward = restored.action_forage(ada)
    assert ok and reward == 1 + 2, "the buff survives the resume"
    assert restored.expire_miracles() == [], "not due yet"

    restored.tick = 20
    expired = restored.expire_miracles()
    assert [e["kind"] for e in expired] == ["miracle_expired"]
    ok, _, reward = restored.action_forage(ada)
    assert ok and reward == 1, "and it still expires on schedule"


# ══════════════════════════════════════════════════════════════════════════════
# 7. Pre-ratified runtime.py constants: weight 2.0 + global witness
# ══════════════════════════════════════════════════════════════════════════════

def test_god_miracle_importance_weight_is_2():
    assert _IMPORTANCE_WEIGHTS["god_miracle"] == 2.0


def test_god_miracle_is_globally_witnessed():
    """Every living agent remembers a god_miracle — even with no actor/target
    match and no shared location (the random_event treatment)."""
    world = _world()  # Ada at plaza, Bram… moved to market below
    world.agents["agent_bram"].location = "market"
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider()})
    runtime = AgentRuntime(world, router)

    runtime.push_event({
        "kind": "god_miracle", "actor_id": "god", "actor_type": "god",
        "target_id": None, "tick": 3,
        "text": "🌧 Rain falls on the gardens — forage flourishes",
        "payload": {"kind": "send_rain", "until_tick": 20},
    })

    for aid in ("agent_ada", "agent_bram"):
        buf = runtime._memory.get(aid, [])
        assert any(e["kind"] == "god_miracle" for e in buf), \
            f"{aid} must witness the miracle regardless of location"
        assert runtime._importance.get(aid, 0.0) == 2.0


# ══════════════════════════════════════════════════════════════════════════════
# 8. Config — _parse_miracles + the EMBEDDED_WORLD_YAML mirror
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_miracles_defaults_overrides_and_malformed():
    d = MiracleParams()
    assert _parse_miracles(None) == d
    assert _parse_miracles({}) == d
    assert d == MiracleParams(enabled=True, rain_forage_bonus=2, rain_days=2,
                              harvest_decay_factor=0.5, harvest_days=2,
                              calm_trust_bonus=3)

    p = _parse_miracles({
        "enabled": False, "rain_forage_bonus": 5, "rain_days": 1,
        "harvest_decay_factor": 0.25, "harvest_days": 3,
        "calm_trust_bonus": 10,
    })
    assert p == MiracleParams(enabled=False, rain_forage_bonus=5, rain_days=1,
                              harvest_decay_factor=0.25, harvest_days=3,
                              calm_trust_bonus=10)

    # Malformed values fall back per-key; clamps apply (bonus >= 0,
    # days >= 1, factor in [0, 1]).
    q = _parse_miracles({
        "rain_forage_bonus": "many", "rain_days": 0,
        "harvest_decay_factor": 7, "harvest_days": "long",
        "calm_trust_bonus": -4,
    })
    assert q.rain_forage_bonus == 2
    assert q.rain_days == 1
    assert q.harvest_decay_factor == 1.0
    assert q.harvest_days == 2
    assert q.calm_trust_bonus == 0


def test_embedded_world_yaml_mirror_matches_defaults():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    block = raw["world"].get("miracles")
    assert isinstance(block, dict), "EMBEDDED_WORLD_YAML must carry the block"
    assert _parse_miracles(block) == MiracleParams()


def test_world_params_default_block_matches_engine_defaults():
    """An absent config block (engine _mir_param defaults) and the loader's
    MiracleParams defaults must agree — the EM-155 invariant."""
    world = _world(miracles=None)
    assert world._mir_param("enabled", True) is True
    assert world._mir_param("rain_forage_bonus", 2) == 2
    assert world._mir_param("rain_days", 2) == 2
    assert world._mir_param("harvest_decay_factor", 0.5) == 0.5
    assert world._mir_param("harvest_days", 2) == 2
    assert world._mir_param("calm_trust_bonus", 3) == 3
    d = MiracleParams()
    assert (d.enabled, d.rain_forage_bonus, d.rain_days,
            d.harvest_decay_factor, d.harvest_days,
            d.calm_trust_bonus) == (True, 2, 2, 0.5, 2, 3)


# ══════════════════════════════════════════════════════════════════════════════
# 9. API — POST /api/god/intervene (matrix, batch emission, loop sweep)
# ══════════════════════════════════════════════════════════════════════════════

def _client():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]
    return TestClient(app, raise_server_exceptions=True), appmod


def test_api_agent_id_matrix_422s():
    client, appmod = _client()
    with client:
        agent = appmod._world.living_agents()[0]
        # World kind + agent_id ⇒ 422 (and nothing mutates).
        for kind in ("send_rain", "bountiful_harvest", "calm_spirits"):
            resp = client.post("/api/god/intervene",
                               json={"kind": kind, "agent_id": agent.id})
            assert resp.status_code == 422, kind
        assert appmod._world.active_miracles == []
        # Targeted kind without agent_id ⇒ 422.
        for kind in ("bless_energy", "grant_credits"):
            resp = client.post("/api/god/intervene", json={"kind": kind})
            assert resp.status_code == 422, kind
        assert appmod._repo.get_events(
            appmod._loop._run_id,
            kinds=["god_miracle", "god_intervention"]) == [], \
            "rejected interventions must not emit"


def test_api_send_rain_200_returns_until_tick_and_persists_god_miracle():
    client, appmod = _client()
    with client:
        resp = client.post("/api/god/intervene", json={"kind": "send_rain"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        world = appmod._world
        tpd = int(world.params.turns_per_day)
        rain_days = int(world.params.miracles.rain_days)
        assert body["until_tick"] == world.tick + rain_days * tpd
        assert world.miracle_active("send_rain")

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["god_miracle"])
        assert len(rows) == 1
        assert rows[0]["actor_id"] == "god"
        assert rows[0]["actor_type"] == "god"
        assert rows[0]["target_id"] is None
        assert rows[0]["turn_id"] is None
        assert rows[0]["payload"] == {"kind": "send_rain",
                                      "until_tick": body["until_tick"]}


def test_api_calm_spirits_batch_carries_relationship_changed_turn_id_null():
    client, appmod = _client()
    with client:
        world = appmod._world
        living = world.living_agents()
        a, b = living[0], living[1]
        a.relationships[b.id] = RelationshipState(type="neutral", trust=28,
                                                  interactions=5)

        resp = client.post("/api/god/intervene", json={"kind": "calm_spirits"})
        assert resp.status_code == 200
        assert "until_tick" not in resp.json(), "one-time kind has no window"

        assert all(ag.mood == "hopeful" for ag in world.living_agents())
        assert a.relationships[b.id].type == "friend"
        assert world.pending_relationship_events == [], \
            "the god path must leave the B1 outbox drained"

        miracle_rows = appmod._repo.get_events(appmod._loop._run_id,
                                               kinds=["god_miracle"])
        shift_rows = appmod._repo.get_events(appmod._loop._run_id,
                                             kinds=["relationship_changed"])
        assert len(miracle_rows) == 1
        assert len(shift_rows) == 1
        assert shift_rows[0]["actor_id"] == a.id
        assert shift_rows[0]["target_id"] == b.id
        assert shift_rows[0]["turn_id"] is None
        assert shift_rows[0]["payload"]["to_type"] == "friend"


def test_api_loop_sweep_expires_miracles_beside_blackouts():
    """The per-tick path (loop._execute_turn) sweeps miracle expiry: cast,
    shrink the window to the next tick, step twice ⇒ exactly one
    miracle_expired row lands without any direct expire_miracles() call."""
    client, appmod = _client()
    with client:
        world = appmod._world
        # Determinism: mock agents, no chaos animals (the test_api_routes idiom).
        world.params.animals.enabled = False
        world.animals.clear()
        for ag in world.living_agents():
            client.post(f"/api/agents/{ag.id}/model", json={"profile": "mock"})

        assert client.post("/api/god/intervene",
                           json={"kind": "send_rain"}).status_code == 200
        world.active_miracles[0]["until_tick"] = world.tick + 1

        for _ in range(2):
            assert client.post("/api/control/step").status_code == 200

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["miracle_expired"])
        assert len(rows) == 1, "the loop sweep emits the expiry exactly once"
        assert rows[0]["actor_type"] == "system"
        assert rows[0]["turn_id"] is None
        assert rows[0]["payload"]["kind"] == "send_rain"
        assert world.active_miracles == []


def test_api_send_rain_is_witnessed_by_runtime():
    """Wave E QE gate regression (qa-report.json MAJOR): the PRODUCTION
    /api/god/intervene path must feed the emitted batch to the agent runtime
    (runtime.push_event, the loop._execute_turn stamping) so a cast miracle is
    actually WITNESSED — memory entry, the ratified 2.0 importance weight, and
    the EM-159 background-salience marking — not just persisted/broadcast."""
    client, appmod = _client()
    with client:
        runtime = appmod._runtime
        living = appmod._world.living_agents()
        assert living, "fixture world must have living agents"

        # Clean slate: nothing has been witnessed before the cast.
        for ag in living:
            assert runtime._importance.get(ag.id, 0.0) == 0.0

        resp = client.post("/api/god/intervene", json={"kind": "send_rain"})
        assert resp.status_code == 200

        # EVERY living agent witnessed the miracle through the runtime —
        # the exact QE probe shape (test_wave_e_qe.py runtime-seam pin).
        for ag in living:
            buf = runtime._memory.get(ag.id, [])
            assert any(m["kind"] == "god_miracle" for m in buf), \
                f"{ag.id} must hold a god_miracle memory entry after the cast"
            assert runtime._importance.get(ag.id, 0.0) == 2.0
            assert ag.id in runtime._witnessed_since_llm


def test_api_targeted_bless_is_remembered_by_target():
    """Same gap, targeted tier: a blessed agent must REMEMBER the blessing
    (god_intervention rides push_event; target_id makes them the witness).
    god_intervention carries no importance weight, so the accumulator and the
    salience set stay untouched — only the memory entry lands."""
    client, appmod = _client()
    with client:
        runtime = appmod._runtime
        agent = appmod._world.living_agents()[0]
        resp = client.post("/api/god/intervene",
                           json={"kind": "bless_energy", "agent_id": agent.id,
                                 "amount": 10})
        assert resp.status_code == 200
        buf = runtime._memory.get(agent.id, [])
        assert any(m["kind"] == "god_intervention" for m in buf), \
            "the blessed agent must remember being blessed"
        assert runtime._importance.get(agent.id, 0.0) == 0.0
        assert agent.id not in runtime._witnessed_since_llm


def test_api_targeted_bless_regression_unchanged():
    """The pre-E god console request still works byte-identically through the
    widened InterveneBody (agent_id now optional in the MODEL, still required
    by the targeted kinds)."""
    client, appmod = _client()
    with client:
        agent = appmod._world.living_agents()[0]
        agent.energy = 40.0
        resp = client.post("/api/god/intervene",
                           json={"kind": "bless_energy", "agent_id": agent.id,
                                 "amount": 30})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}, "no until_tick for targeted"
        assert agent.energy == 70.0
        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["god_intervention"])
        assert len(rows) == 1
        assert rows[0]["payload"] == {"kind": "bless_energy", "amount": 30,
                                      "before": 40.0, "after": 70.0}

"""
Wave D3 / EM-168 — cap-pressure governor (contracts/wave-d3.md §B2).

A usage_alert for a lane (UsageAlertTracker ≥70% of its rpd/tpd day cap)
demotes every agent ASSIGNED to that lane ONE cadence tier (protagonist →
supporting → background; background stays), recording `demoted_from`; the
demotion lifts at the tracker's UTC-day rollover. This file gates:

  (A) Demotion on alert — each tier steps down one, background floor,
      lane/aliveness scoping, ONE `cap_pressure{phase:demoted}` feed event.
  (B) Once per lane-alert-day — repeated alerts (rpd then tpd) never stack;
      a manual override is never re-demoted the same day.
  (C) Restoration at rollover — agents return to demoted_from (which clears);
      rollover-first ordering on a new day's alert; the scheduler-side probe
      restores with zero clock reads and parks the feed event in the outbox.
  (D) Snapshot — demoted_from + cap_demotions round-trip; ungoverned worlds
      keep the exact pre-D3 key set; pre-D3 snapshots restore clean.
  (E) enabled:false — alerts stay alert-only, byte-identical pre-D3 state.
  (F) Feed events — exactly one per edge across a full demote→restore cycle.
  (G) EM-177 composition — a demoted agent on a SICK lane still detours.
  (H) Config — yaml → CapGovernorParams → runs.config_json round-trip;
      EMBEDDED_WORLD_YAML mirror; shipped config/world.yaml block.
  (I) App wiring — the usage_alert sink drives the governor; a manual
      POST /api/agents/{id}/tier wins and clears demoted_from.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from petridish.config.loader import (
    CapGovernorParams, EMBEDDED_WORLD_YAML, ModelProfile, WorldParams,
    _parse_world,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import _world_params_json
from petridish.providers.router import Router


D1 = "2026-06-11"
D2 = "2026-06-12"

_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})

# Env var the EM-177 composition profiles use for availability.
_KEY_ENV = "EM_CAP_GOVERNOR_TEST_KEY"


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


def _make_world(
    agents_spec: list[tuple[str, str, str]],
    *,
    governor_enabled: bool = True,
) -> World:
    """World over one plaza with agents [(name, profile, cadence_tier), ...]."""
    params = WorldParams(
        cap_governor=CapGovernorParams(enabled=governor_enabled),
        energy_decay_per_turn=0.0,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agents = [
        AgentState(
            id=f"agent_{name.lower()}", name=name, personality="", profile=profile,
            location="plaza", energy=80.0, credits=10, cadence_tier=tier,
        )
        for name, profile, tier in agents_spec
    ]
    return World(params=params, places=places, agents=agents)


# ──────────────────────────────────────────────────────────────────────────────
# (A) Demotion on alert
# ──────────────────────────────────────────────────────────────────────────────

def test_alert_demotes_each_tier_one_step_and_records_demoted_from():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "alpha", "supporting"),
        ("Cal", "alpha", "background"),
    ])
    events = w.apply_cap_pressure("alpha", D1)

    ada, bea, cal = (w.agents[f"agent_{n}"] for n in ("ada", "bea", "cal"))
    assert (ada.cadence_tier, ada.demoted_from) == ("supporting", "protagonist")
    assert (bea.cadence_tier, bea.demoted_from) == ("background", "supporting")
    # Background floor: stays put, nothing recorded (nothing to restore).
    assert (cal.cadence_tier, cal.demoted_from) == ("background", None)

    assert len(events) == 1
    evt = events[0]
    assert evt["kind"] == "cap_pressure"
    assert evt["actor_type"] == "system"
    assert evt["payload"]["phase"] == "demoted"
    assert evt["payload"]["lane"] == "alpha"
    assert evt["payload"]["window"] == D1
    assert {a["agent_id"] for a in evt["payload"]["agents"]} == {
        "agent_ada", "agent_bea",
    }
    assert w.cap_demotions == {"alpha": D1}


def test_only_agents_assigned_to_the_alerting_lane_are_demoted():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "beta", "protagonist"),
    ])
    w.apply_cap_pressure("alpha", D1)
    assert w.agents["agent_ada"].cadence_tier == "supporting"
    bea = w.agents["agent_bea"]
    assert (bea.cadence_tier, bea.demoted_from) == ("protagonist", None)


def test_dead_agents_are_not_demoted():
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.agents["agent_ada"].alive = False
    events = w.apply_cap_pressure("alpha", D1)
    assert events == []
    ada = w.agents["agent_ada"]
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)


def test_alert_on_an_all_background_lane_emits_no_event_but_still_latches():
    w = _make_world([("Cal", "alpha", "background")])
    assert w.apply_cap_pressure("alpha", D1) == []
    # The lane-alert-day is still recorded (the alert WAS processed).
    assert w.cap_demotions == {"alpha": D1}


def test_demoted_tier_actually_changes_scheduling_cadence():
    w = _make_world([("Ada", "alpha", "protagonist")])
    ada = w.agents["agent_ada"]
    assert w._tier_due(ada, 1) is True       # protagonist: every round
    w.apply_cap_pressure("alpha", D1)
    assert w._tier_due(ada, 1) is False      # supporting: every 3rd round
    assert w._tier_due(ada, 3) is True


# ──────────────────────────────────────────────────────────────────────────────
# (B) Once per lane-alert-day — never stack
# ──────────────────────────────────────────────────────────────────────────────

def test_repeated_alerts_same_lane_same_day_never_stack():
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.apply_cap_pressure("alpha", D1)          # rpd alert
    events = w.apply_cap_pressure("alpha", D1)  # tpd alert, same window
    assert events == []
    ada = w.agents["agent_ada"]
    assert (ada.cadence_tier, ada.demoted_from) == ("supporting", "protagonist")


def test_manual_override_is_not_redemoted_by_a_same_day_repeat_alert():
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.apply_cap_pressure("alpha", D1)
    ada = w.agents["agent_ada"]
    # The user puts the agent back (the API endpoint does exactly this).
    ada.cadence_tier = "protagonist"
    ada.demoted_from = None
    events = w.apply_cap_pressure("alpha", D1)  # same lane, same day
    assert events == []
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)


def test_an_alert_on_a_second_lane_demotes_only_that_lane_same_day():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "beta", "protagonist"),
    ])
    w.apply_cap_pressure("alpha", D1)
    events = w.apply_cap_pressure("beta", D1)
    assert [e["payload"]["phase"] for e in events] == ["demoted"]
    assert w.agents["agent_bea"].cadence_tier == "supporting"
    assert w.cap_demotions == {"alpha": D1, "beta": D1}


# ──────────────────────────────────────────────────────────────────────────────
# (C) Restoration at the tracker's day rollover
# ──────────────────────────────────────────────────────────────────────────────

def test_restoration_returns_agents_to_demoted_from_which_clears():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "alpha", "supporting"),
    ])
    w.apply_cap_pressure("alpha", D1)
    events = w.restore_cap_demotions(D2)

    ada, bea = w.agents["agent_ada"], w.agents["agent_bea"]
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)
    assert (bea.cadence_tier, bea.demoted_from) == ("supporting", None)
    assert w.cap_demotions == {}

    assert len(events) == 1
    evt = events[0]
    assert evt["kind"] == "cap_pressure"
    assert evt["payload"]["phase"] == "restored"
    assert evt["payload"]["window"] == D2
    assert {a["agent_id"] for a in evt["payload"]["agents"]} == {
        "agent_ada", "agent_bea",
    }


def test_restore_within_the_same_window_is_a_noop():
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.apply_cap_pressure("alpha", D1)
    assert w.restore_cap_demotions(D1) == []
    assert w.agents["agent_ada"].cadence_tier == "supporting"
    assert w.cap_demotions == {"alpha": D1}


def test_a_new_days_alert_restores_yesterday_before_demoting_today():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "beta", "protagonist"),
    ])
    w.apply_cap_pressure("alpha", D1)
    events = w.apply_cap_pressure("beta", D2)  # first observation of the new day
    assert [e["payload"]["phase"] for e in events] == ["restored", "demoted"]
    ada, bea = w.agents["agent_ada"], w.agents["agent_bea"]
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)
    assert (bea.cadence_tier, bea.demoted_from) == ("supporting", "protagonist")
    assert w.cap_demotions == {"beta": D2}


def test_scheduler_probe_restores_at_rollover_and_parks_the_feed_event():
    w = _make_world([("Ada", "alpha", "protagonist")])
    cell = {"window": D1}
    w.set_usage_window_probe(lambda: cell["window"])
    w.apply_cap_pressure("alpha", D1)
    ada = w.agents["agent_ada"]

    # Same window: scheduling never restores (zero clock reads either way —
    # the probe is an attribute peek at the tracker's lazily-rolled window).
    assert w.next_agent() is not None
    assert (ada.cadence_tier, ada.demoted_from) == ("supporting", "protagonist")

    # The tracker rolls its day window; the next scheduling decision restores.
    cell["window"] = D2
    assert w.next_agent() is not None
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)
    assert w.cap_demotions == {}

    parked = [e for e in w.drain_spawn_events() if e["kind"] == "cap_pressure"]
    assert [e["payload"]["phase"] for e in parked] == ["restored"]


def test_probe_returning_nothing_never_restores():
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.set_usage_window_probe(lambda: "")
    w.apply_cap_pressure("alpha", D1)
    assert w.next_agent() is not None
    assert w.agents["agent_ada"].cadence_tier == "supporting"
    assert w.cap_demotions == {"alpha": D1}


# ──────────────────────────────────────────────────────────────────────────────
# (D) Snapshot round-trip — replay/fork safe
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_round_trips_demoted_from_and_cap_demotions():
    w = _make_world([
        ("Ada", "alpha", "protagonist"),
        ("Bea", "beta", "protagonist"),
    ])
    w.apply_cap_pressure("alpha", D1)
    snap = w.to_snapshot()

    ada_d = next(a for a in snap["agents"] if a["id"] == "agent_ada")
    bea_d = next(a for a in snap["agents"] if a["id"] == "agent_bea")
    assert ada_d["demoted_from"] == "protagonist"
    assert ada_d["cadence_tier"] == "supporting"
    assert "demoted_from" not in bea_d           # ungoverned agents: no key
    assert snap["cap_demotions"] == {"alpha": D1}

    restored = World.from_snapshot(json.loads(json.dumps(snap)), params=WorldParams())
    ada2 = restored.agents["agent_ada"]
    assert (ada2.cadence_tier, ada2.demoted_from) == ("supporting", "protagonist")
    assert restored.cap_demotions == {"alpha": D1}

    # The restored/forked world still lifts the demotion at the day rollover.
    restored.restore_cap_demotions(D2)
    assert (ada2.cadence_tier, ada2.demoted_from) == ("protagonist", None)
    assert restored.cap_demotions == {}


def test_ungoverned_snapshot_keeps_the_exact_pre_d3_key_set():
    w = _make_world([("Ada", "alpha", "protagonist")])
    snap = w.to_snapshot()
    assert "cap_demotions" not in snap
    assert all("demoted_from" not in a for a in snap["agents"])
    # A pre-D3 snapshot (no governor keys) restores clean.
    restored = World.from_snapshot(snap, params=WorldParams())
    assert restored.cap_demotions == {}
    assert all(a.demoted_from is None for a in restored.agents.values())


def test_snapshot_rejects_unknown_demoted_from_values():
    w = _make_world([("Ada", "alpha", "protagonist")])
    snap = w.to_snapshot()
    next(a for a in snap["agents"] if a["id"] == "agent_ada")["demoted_from"] = "emperor"
    restored = World.from_snapshot(snap, params=WorldParams())
    assert restored.agents["agent_ada"].demoted_from is None  # fail-safe


# ──────────────────────────────────────────────────────────────────────────────
# (E) enabled:false — alerts stay alert-only, byte-identical pre-D3 state
# ──────────────────────────────────────────────────────────────────────────────

def test_disabled_governor_is_inert_and_byte_identical():
    w = _make_world(
        [("Ada", "alpha", "protagonist"), ("Bea", "alpha", "supporting")],
        governor_enabled=False,
    )
    before = json.dumps(w.to_snapshot(), sort_keys=True, default=str)
    events = w.apply_cap_pressure("alpha", D1)
    assert events == []
    ada = w.agents["agent_ada"]
    assert (ada.cadence_tier, ada.demoted_from) == ("protagonist", None)
    assert w.cap_demotions == {}
    after = json.dumps(w.to_snapshot(), sort_keys=True, default=str)
    assert before == after  # byte-identical pre-D3 state


def test_governor_defaults_on_when_the_params_block_is_absent():
    # Engine reads the block via the defensive accessor: a bare/dict/None
    # params object without `cap_governor` behaves like the shipped default.
    w = _make_world([("Ada", "alpha", "protagonist")])
    w.params = WorldParams()  # default block, enabled=True
    assert w._cap_governor_enabled() is True
    object.__setattr__(w.params, "cap_governor", None)
    assert w._cap_governor_enabled() is True


# ──────────────────────────────────────────────────────────────────────────────
# (F) Feed events — exactly once per edge across a full cycle
# ──────────────────────────────────────────────────────────────────────────────

def test_feed_events_fire_exactly_once_per_edge_across_a_full_cycle():
    w = _make_world([("Ada", "alpha", "protagonist")])
    events: list[dict] = []
    events += w.apply_cap_pressure("alpha", D1)   # rpd alert  → demoted edge
    events += w.apply_cap_pressure("alpha", D1)   # tpd alert  → nothing
    events += w.restore_cap_demotions(D2)         # rollover   → restored edge
    events += w.restore_cap_demotions(D2)         # idempotent → nothing
    assert [e["payload"]["phase"] for e in events] == ["demoted", "restored"]


# ──────────────────────────────────────────────────────────────────────────────
# (G) EM-177 composition — a demoted agent on a sick lane still detours
# ──────────────────────────────────────────────────────────────────────────────

class ScriptedAdapter:
    """Recording fake adapter: every chat() call is the proof surface."""

    def __init__(self, name: str, text: str = _VALID_ACTION_JSON):
        self.name = name
        self.text = text
        self.calls: list[tuple[int, float]] = []
        self.last_routed_via = f"real/{name}"
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls.append((max_tokens, temperature))
        return self.text


def _profile(name: str, *, adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=f"model/{name}",
        base_url="http://localhost:9",
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


@pytest.mark.asyncio
async def test_demoted_agent_on_a_sick_lane_still_detours():
    alpha, beta = ScriptedAdapter("alpha"), ScriptedAdapter("beta")
    router = Router(
        [_profile("alpha"), _profile("beta"), _profile("mock", adapter="mock")],
        adapter_overrides={"alpha": alpha, "beta": beta},
        cache_enabled=False,
    )
    world = _make_world([("Ada", "alpha", "protagonist")])
    agent = world.agents["agent_ada"]
    runtime = AgentRuntime(world, router)

    # EM-168: the lane's day-cap alert demotes the agent ...
    world.apply_cap_pressure("alpha", D1)
    assert (agent.cadence_tier, agent.demoted_from) == ("supporting", "protagonist")
    # ... and EM-177: the same lane is also SICK (3 timeouts in the window).
    for _ in range(3):
        router.note_parse_outcome("alpha", parsed=False, truncated=False,
                                  timed_out=True)

    event = await runtime.run_turn(agent)
    assert event["kind"] != "parse_failure"

    # The demoted agent's due turn DETOURED — the substitute adapter served it.
    assert beta.calls and alpha.calls == []
    span = event["_trace"]["llm_attempts"][0]
    assert span["gen_ai.request.model"] == "beta"
    assert span["requested_profile"] == "alpha"
    assert span["detoured"] is True

    # The two mechanisms never clobber each other: demotion state and the
    # assigned profile both survive the detour.
    assert (agent.cadence_tier, agent.demoted_from) == ("supporting", "protagonist")
    assert agent.profile == "alpha"
    assert router.profile_name_for(agent.id, agent.profile) == "alpha"


# ──────────────────────────────────────────────────────────────────────────────
# (H) Config — params, round-trip, embedded mirror, shipped yaml
# ──────────────────────────────────────────────────────────────────────────────

def test_cap_governor_param_defaults():
    p = CapGovernorParams()
    assert p.enabled is True
    assert WorldParams().cap_governor == p


def test_parse_world_reads_the_cap_governor_block():
    params, _, _ = _parse_world({"world": {"cap_governor": {"enabled": False}}})
    assert params.cap_governor == CapGovernorParams(enabled=False)


def test_parse_world_defaults_malformed_cap_governor_blocks():
    params, _, _ = _parse_world({"world": {}})
    assert params.cap_governor == CapGovernorParams()
    params, _, _ = _parse_world({"world": {"cap_governor": "nope"}})
    assert params.cap_governor == CapGovernorParams()


def test_config_round_trips_through_runs_config_json():
    # The fork/replay seam: WorldParams → runs.config_json → _parse_world.
    params, _, _ = _parse_world({"world": {"cap_governor": {"enabled": False}}})
    blob = json.loads(json.dumps(_world_params_json(params)))
    restored, _, _ = _parse_world({"world": blob})
    assert restored.cap_governor == params.cap_governor


def test_embedded_world_yaml_mirror_carries_the_block():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    params, _, _ = _parse_world(raw)
    assert params.cap_governor == CapGovernorParams(enabled=True)


def test_shipped_world_yaml_carries_the_block_in_sync_with_the_mirror():
    path = Path(__file__).resolve().parents[2] / "config" / "world.yaml"
    raw = yaml.safe_load(path.read_text())
    params, _, _ = _parse_world(raw)
    assert params.cap_governor == CapGovernorParams(enabled=True)


# ──────────────────────────────────────────────────────────────────────────────
# (I) App wiring — sink-driven demotion + manual override via the API
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient over the real app (the test_api_routes idiom)."""
    import sys
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    _appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as c:
        if _appmod._world is not None:
            _appmod._world.params.animals.enabled = False
            _appmod._world.animals.clear()
        yield c


def _cap_pressure_rows(client) -> list[dict]:
    rows = client.get("/api/events", params={"kinds": "cap_pressure"}).json()
    return rows["events"] if isinstance(rows, dict) else rows


def test_usage_alert_sink_drives_the_governor_and_manual_set_overrides(client):
    import sys
    _appmod = sys.modules["petridish.api.app"]
    world = _appmod._world
    agent = next(a for a in world.agents.values() if a.alive)
    # Normalize: this test owns the world's governor state from here on.
    world.restore_cap_demotions("test-cleanup")
    world.cap_demotions.clear()
    agent.cadence_tier = "protagonist"
    agent.demoted_from = None
    lane = agent.profile

    # The lifespan wired the router's usage-alert sink to _emit_usage_alert;
    # drive the app-level sink directly (the W11b test idiom).
    _appmod._emit_usage_alert(
        {"provider": lane, "metric": "rpd", "pct": 71.0, "limit": 100})
    assert (agent.cadence_tier, agent.demoted_from) == ("supporting", "protagonist")
    demoted_rows = [
        e for e in _cap_pressure_rows(client) if e["payload"]["phase"] == "demoted"
    ]
    assert len(demoted_rows) == 1
    assert demoted_rows[0]["payload"]["lane"] == lane
    assert agent.name in demoted_rows[0]["text"]

    # A same-day repeat alert (the tpd metric) never stacks — no new event.
    _appmod._emit_usage_alert(
        {"provider": lane, "metric": "tpd", "pct": 70.2, "limit": 5000})
    assert agent.cadence_tier == "supporting"
    assert len([
        e for e in _cap_pressure_rows(client) if e["payload"]["phase"] == "demoted"
    ]) == 1

    # Manual tier set WINS and clears the governor's marker.
    resp = client.post(f"/api/agents/{agent.id}/tier", json={"tier": "protagonist"})
    assert resp.status_code == 200
    assert (agent.cadence_tier, agent.demoted_from) == ("protagonist", None)

    # Cleanup: lift any other demotions this lane's alert applied.
    world.restore_cap_demotions("test-cleanup-2")
    world.cap_demotions.clear()


def test_app_wired_the_usage_window_probe_onto_the_world(client):
    import sys
    _appmod = sys.modules["petridish.api.app"]
    world = _appmod._world
    probe = getattr(world, "_usage_window_probe", None)
    assert callable(probe)
    # The probe peeks at the tracker's CURRENT day window — a YYYY-MM-DD key.
    window = probe()
    assert isinstance(window, str) and len(window) == 10
    assert window == _appmod._usage_alert_window()

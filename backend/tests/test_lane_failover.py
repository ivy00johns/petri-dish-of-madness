"""
Wave D3 / EM-177 — lane failover with recovery probes (contracts/wave-d3.md §B1).

Triggering incident (2026-06-11): the proxy silently rerouted every FreeLLMAPI
lane but one to a reasoning model that blew the EM-170 12s budget; the router
KNEW lane health (EM-135/170 windows) but nothing ACTED. This file gates:

  (A) Sickness predicate — ≥ sick_threshold timed_out entries in the existing
      6-window ⇒ SICK; mock never sick; provider_error-shaped entries don't count.
  (B) effective_profile — healthiest-candidate detour, load-spread tie-break,
      stable order, all-sick ⇒ home, never-to-mock, assigned profile unchanged.
  (C) Recovery probes — every probe_every-th would-be-detour goes home; clean
      probe outcomes age the lane healthy; a failed probe keeps it sick.
  (D) lane_detour edge events — exactly TWO per sick→recovered cycle.
  (E) enabled:false — byte-identical pre-D3 behavior (home lane, zero events,
      exact pre-D3 llm_call payload key set).
  (F) Runtime end-to-end — a detoured turn actually calls the SUBSTITUTE
      adapter at the substitute's max_tokens/temperature ("green gate ≠ real
      fix"); spans/payloads carry requested_profile + detoured/probe; outcome
      attribution lands on the effective lane.
  (G) Config — yaml → LaneFailoverParams → runs.config_json round-trip;
      EMBEDDED_WORLD_YAML mirror; shipped config/world.yaml block.
  (H) GET /api/lanes — lane_health() augmented with sick + detours_routed_here.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from petridish.config.loader import (
    EMBEDDED_WORLD_YAML, LaneFailoverParams, ModelProfile, WorldParams,
    _parse_world,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop, _world_params_json
from petridish.providers.router import Router


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})

# Env var the test profiles use for availability; set in the autouse fixture.
_KEY_ENV = "EM_LANE_FAILOVER_TEST_KEY"


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


def _profile(name: str, *, adapter: str = "openai", max_tokens: int = 512,
             temperature: float = 0.8, key_env: str = _KEY_ENV) -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=f"model/{name}",
        max_tokens=max_tokens, temperature=temperature,
        base_url="http://localhost:9", api_key_env=key_env if adapter != "mock" else "",
    )


def _router(profiles: list[ModelProfile] | None = None, **kwargs) -> Router:
    if profiles is None:
        profiles = [
            _profile("alpha"),
            _profile("beta"),
            _profile("gamma"),
            _profile("mock", adapter="mock"),
        ]
    return Router(profiles, **kwargs)


def _sicken(r: Router, lane: str, n: int = 3) -> None:
    for _ in range(n):
        r.note_parse_outcome(lane, parsed=False, truncated=False, timed_out=True)


def _clean(r: Router, lane: str, n: int = 1) -> None:
    for _ in range(n):
        r.note_parse_outcome(lane, parsed=True, truncated=False)


# ──────────────────────────────────────────────────────────────────────────────
# (A) Sickness predicate
# ──────────────────────────────────────────────────────────────────────────────

def test_three_timeouts_in_window_make_a_lane_sick():
    r = _router()
    _sicken(r, "alpha", 3)
    assert r.lane_sick("alpha") is True


def test_two_timeouts_are_not_sick():
    r = _router()
    _sicken(r, "alpha", 2)
    assert r.lane_sick("alpha") is False


def test_mock_lane_is_never_sick():
    r = _router()
    _sicken(r, "mock", 6)
    assert r.lane_sick("mock") is False


def test_provider_error_shaped_entries_do_not_count():
    # provider_error turns never enter the window as timed_out (EM-173 keeps
    # them idle on purpose) — a window full of plain failures is NOT sick.
    r = _router()
    for _ in range(6):
        r.note_parse_outcome("alpha", parsed=False, truncated=False)
    assert r.lane_sick("alpha") is False


def test_unknown_or_empty_window_lane_is_not_sick():
    r = _router()
    assert r.lane_sick("alpha") is False
    assert r.lane_sick("never-seen") is False


def test_sick_threshold_is_configurable():
    r = _router(lane_failover={"sick_threshold": 2})
    _sicken(r, "alpha", 2)
    assert r.lane_sick("alpha") is True


def test_timeouts_age_out_of_the_six_window():
    r = _router()
    _sicken(r, "alpha", 3)
    _clean(r, "alpha", 3)   # window [T,T,T,C,C,C] — still 3 timeouts
    assert r.lane_sick("alpha") is True
    _clean(r, "alpha", 1)   # [T,T,C,C,C,C] — 2 timeouts
    assert r.lane_sick("alpha") is False


# ──────────────────────────────────────────────────────────────────────────────
# (B) Detour candidate selection
# ──────────────────────────────────────────────────────────────────────────────

def test_healthy_home_lane_is_used_unchanged():
    r = _router()
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)


def test_detour_picks_the_candidate_with_fewest_window_timeouts():
    r = _router()
    _sicken(r, "alpha", 3)
    # beta has one timeout (not sick); gamma is clean → gamma is healthiest.
    _sicken(r, "beta", 1)
    _clean(r, "gamma", 2)
    assert r.effective_profile("agent_1", "alpha") == ("gamma", "detour")


def test_tie_break_spreads_load_by_detours_already_routed():
    r = _router()
    _sicken(r, "alpha", 3)
    # beta and gamma both clean: stable order picks beta first, then the
    # detour counter tie-break alternates the load.
    first, _ = r.effective_profile("agent_1", "alpha")
    second, _ = r.effective_profile("agent_1", "alpha")
    third, _ = r.effective_profile("agent_1", "alpha")
    assert first == "beta"     # stable profile order on a full tie
    assert second == "gamma"   # beta already absorbed one detour
    assert third == "beta"     # back to even — stable order again


def test_all_sick_falls_back_to_the_home_lane():
    r = _router()
    for lane in ("alpha", "beta", "gamma"):
        _sicken(r, lane, 3)
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)


def test_never_detours_to_mock_even_when_it_is_the_only_healthy_lane():
    r = _router([_profile("alpha"), _profile("mock", adapter="mock")])
    _sicken(r, "alpha", 3)
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)


def test_unavailable_lanes_are_never_candidates():
    profiles = [
        _profile("alpha"),
        _profile("beta", key_env="EM_LANE_FAILOVER_NO_SUCH_KEY"),  # unavailable
        _profile("gamma"),
    ]
    r = Router(profiles)
    _sicken(r, "alpha", 3)
    assert r.effective_profile("agent_1", "alpha") == ("gamma", "detour")


def test_assigned_profile_never_changes_across_detours():
    r = _router()
    r.reassign("agent_1", "alpha")
    _sicken(r, "alpha", 3)
    for _ in range(5):
        r.effective_profile("agent_1", "alpha")
    assert r.profile_name_for("agent_1", "alpha") == "alpha"
    assert r.profile_for("agent_1").name == "alpha"


# ──────────────────────────────────────────────────────────────────────────────
# (C) Recovery probes
# ──────────────────────────────────────────────────────────────────────────────

def test_every_fourth_would_be_detour_probes_the_home_lane():
    r = _router()
    _sicken(r, "alpha", 3)
    reasons = [r.effective_profile("agent_1", "alpha")[1] for _ in range(8)]
    assert reasons == [
        "detour", "detour", "detour", "probe",
        "detour", "detour", "detour", "probe",
    ]


def test_probe_every_is_configurable():
    r = _router(lane_failover={"probe_every": 2})
    _sicken(r, "alpha", 3)
    reasons = [r.effective_profile("agent_1", "alpha")[1] for _ in range(4)]
    assert reasons == ["detour", "probe", "detour", "probe"]


def test_probe_returns_the_home_lane_itself():
    r = _router()
    _sicken(r, "alpha", 3)
    results = [r.effective_profile("agent_1", "alpha") for _ in range(4)]
    assert results[3] == ("alpha", "probe")


def test_all_sick_calls_do_not_tick_the_probe_cadence():
    # A call with NO healthy candidate cannot detour, so it must not count
    # toward "every Nth would-be-detour".
    r = _router([_profile("alpha"), _profile("beta")])
    _sicken(r, "alpha", 3)
    _sicken(r, "beta", 3)
    for _ in range(10):
        assert r.effective_profile("agent_1", "alpha") == ("alpha", None)
    # beta recovers; the cadence starts fresh from 1 (3 detours, then probe).
    _clean(r, "beta", 4)
    reasons = [r.effective_profile("agent_1", "alpha")[1] for _ in range(4)]
    assert reasons == ["detour", "detour", "detour", "probe"]


def test_clean_probe_outcomes_age_the_lane_back_to_healthy():
    r = _router()
    _sicken(r, "alpha", 3)
    # Drive the cadence: each probe lands a clean outcome on the home lane
    # (the runtime's note_parse_outcome path); detours land on the substitute.
    for _ in range(40):
        lane, reason = r.effective_profile("agent_1", "alpha")
        if reason is None:
            break  # recovered
        r.note_parse_outcome(lane, parsed=True, truncated=False)
    assert r.lane_sick("alpha") is False
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)


def test_failed_probe_keeps_the_lane_sick():
    r = _router()
    _sicken(r, "alpha", 3)
    for _ in range(3):
        r.effective_profile("agent_1", "alpha")          # detours
    lane, reason = r.effective_profile("agent_1", "alpha")  # the probe
    assert (lane, reason) == ("alpha", "probe")
    r.note_parse_outcome("alpha", parsed=False, truncated=False, timed_out=True)
    assert r.lane_sick("alpha") is True
    assert r.effective_profile("agent_1", "alpha")[1] == "detour"


# ──────────────────────────────────────────────────────────────────────────────
# (D) lane_detour edge events — exactly two per sick→recovered cycle
# ──────────────────────────────────────────────────────────────────────────────

def test_exactly_two_events_across_a_sick_recovered_cycle():
    r = _router()
    events: list[dict] = []
    r.set_lane_event_sink(events.append)
    _sicken(r, "alpha", 3)

    for _ in range(60):
        lane, reason = r.effective_profile("agent_1", "alpha")
        if reason is None and not r.lane_sick("alpha") and events and \
                events[-1]["phase"] == "recovered":
            break
        r.note_parse_outcome(lane, parsed=True, truncated=False)

    assert [e["phase"] for e in events] == ["degraded", "recovered"]
    assert events[0]["home"] == "alpha"
    assert events[0]["substitute"] == "beta"
    assert events[0]["agent_id"] == "agent_1"
    assert events[1]["home"] == "alpha"
    assert events[1]["agent_id"] == "agent_1"


def test_no_event_without_an_actual_detour():
    # A lane that gets sick and recovers WITHOUT any call routed for it must
    # not emit edges (no streak ever started).
    r = _router()
    events: list[dict] = []
    r.set_lane_event_sink(events.append)
    _sicken(r, "alpha", 3)
    _clean(r, "alpha", 4)
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)
    assert events == []


def test_probes_and_repeat_detours_emit_no_extra_events():
    r = _router()
    events: list[dict] = []
    r.set_lane_event_sink(events.append)
    _sicken(r, "alpha", 3)
    for _ in range(12):  # detours + probes, lane stays sick (probes fail)
        lane, reason = r.effective_profile("agent_1", "alpha")
        if reason == "probe":
            r.note_parse_outcome(lane, parsed=False, truncated=False, timed_out=True)
    assert [e["phase"] for e in events] == ["degraded"]


# ──────────────────────────────────────────────────────────────────────────────
# (E) enabled:false — byte-identical pre-D3 behavior
# ──────────────────────────────────────────────────────────────────────────────

def test_disabled_failover_always_returns_home_and_emits_nothing():
    r = _router(lane_failover={"enabled": False})
    events: list[dict] = []
    r.set_lane_event_sink(events.append)
    _sicken(r, "alpha", 6)
    for _ in range(10):
        assert r.effective_profile("agent_1", "alpha") == ("alpha", None)
    assert events == []
    # No failover state was touched at all.
    assert r._lane_detour_counter == {}
    assert r._lane_detours_routed == {}
    assert r._lane_streak_substitute == {}


def test_disabled_via_dataclass_params_too():
    r = _router(lane_failover=LaneFailoverParams(enabled=False))
    _sicken(r, "alpha", 3)
    assert r.effective_profile("agent_1", "alpha") == ("alpha", None)


# ──────────────────────────────────────────────────────────────────────────────
# Reset — failover state is in-memory only, cleared with the lane windows
# ──────────────────────────────────────────────────────────────────────────────

def test_clear_cache_flushes_failover_state():
    r = _router()
    _sicken(r, "alpha", 3)
    for _ in range(3):
        r.effective_profile("agent_1", "alpha")
    assert r._lane_detour_counter and r._lane_detours_routed
    assert r._lane_streak_substitute

    r.clear_cache()
    assert r._lane_detour_counter == {}
    assert r._lane_detours_routed == {}
    assert r._lane_streak_substitute == {}
    assert r.lane_sick("alpha") is False  # windows flushed too (EM-135)


# ──────────────────────────────────────────────────────────────────────────────
# (F) Runtime end-to-end — the detour actually calls the substitute adapter
# ──────────────────────────────────────────────────────────────────────────────

class ScriptedAdapter:
    """Recording fake adapter: every chat() call is the proof surface."""

    def __init__(self, name: str, text: str = _VALID_ACTION_JSON):
        self.name = name
        self.text = text
        self.calls: list[tuple[int, float]] = []  # (max_tokens, temperature)
        self.last_routed_via = f"real/{name}"
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls.append((max_tokens, temperature))
        return self.text


def _world_with_agent(profile: str = "alpha") -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="agent_ada", name="Ada", personality="curious", profile=profile,
        location="plaza", energy=88.0, credits=10,
    )
    world = World(params=params, places=places, agents=[agent])
    return agent, world


def _e2e_router(**kwargs) -> tuple[Router, ScriptedAdapter, ScriptedAdapter]:
    """Real Router over [alpha, beta, mock] with recording adapters and the
    decision cache OFF (a cache HIT would hide which adapter served)."""
    alpha = ScriptedAdapter("alpha")
    beta = ScriptedAdapter("beta")
    profiles = [
        _profile("alpha", max_tokens=512, temperature=0.8),
        _profile("beta", max_tokens=777, temperature=0.3),
        _profile("mock", adapter="mock"),
    ]
    router = Router(
        profiles,
        adapter_overrides={"alpha": alpha, "beta": beta},
        cache_enabled=False,
        **kwargs,
    )
    return router, alpha, beta


@pytest.mark.asyncio
async def test_detoured_turn_calls_the_substitute_adapter_with_its_budget():
    router, alpha, beta = _e2e_router()
    agent, world = _world_with_agent()
    runtime = AgentRuntime(world, router)
    _sicken(router, "alpha", 3)

    event = await runtime.run_turn(agent)
    assert event["kind"] != "parse_failure"

    # The substitute adapter REALLY served the call (green gate ≠ flag flip),
    # at the EFFECTIVE profile's max_tokens/temperature.
    assert beta.calls == [(777, 0.3)]
    assert alpha.calls == []

    # The span: profile keys are the lane actually called; the failover keys
    # are additive.
    span = event["_trace"]["llm_attempts"][0]
    assert span["gen_ai.request.model"] == "beta"
    assert span["requested_profile"] == "alpha"
    assert span["detoured"] is True
    assert "probe" not in span

    # Identity untouched: detours are per-call.
    assert agent.profile == "alpha"
    assert router.profile_name_for(agent.id, agent.profile) == "alpha"

    # Outcome attribution lands on the EFFECTIVE lane.
    health = router.lane_health()
    assert health["beta"]["window"] == [{"parsed": True, "truncated": False}]
    assert health["alpha"]["timeouts"] == 3


@pytest.mark.asyncio
async def test_llm_call_event_payload_carries_the_failover_keys():
    router, _alpha, _beta = _e2e_router()
    agent, world = _world_with_agent()
    runtime = AgentRuntime(world, router)
    _sicken(router, "alpha", 3)

    event = await runtime.run_turn(agent)
    span = event["_trace"]["llm_attempts"][0]
    payload = TickLoop._llm_call_payload("alpha", span)
    assert payload["requested_profile"] == "alpha"
    assert payload["detoured"] is True
    assert payload["gen_ai.request.model"] == "beta"
    assert "probe" not in payload


@pytest.mark.asyncio
async def test_fourth_sick_turn_probes_home_and_logs_a_clean_outcome():
    router, alpha, beta = _e2e_router()
    agent, world = _world_with_agent()
    runtime = AgentRuntime(world, router)
    _sicken(router, "alpha", 3)

    spans = []
    for _ in range(4):
        event = await runtime.run_turn(agent)
        spans.append(event["_trace"]["llm_attempts"][0])

    assert beta.calls and len(beta.calls) == 3       # turns 1-3 detoured
    assert alpha.calls == [(512, 0.8)]               # turn 4 probed home
    assert spans[3]["gen_ai.request.model"] == "alpha"
    assert spans[3]["probe"] is True
    assert spans[3]["requested_profile"] == "alpha"
    assert "detoured" not in spans[3]
    # The clean probe outcome landed on the home lane's window.
    assert router.lane_health()["alpha"]["window"][-1] == {
        "parsed": True, "truncated": False,
    }


@pytest.mark.asyncio
async def test_healthy_turn_keeps_the_exact_pre_d3_span_and_payload_keys():
    router, alpha, beta = _e2e_router()
    agent, world = _world_with_agent()
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)
    assert alpha.calls == [(512, 0.8)] and beta.calls == []
    span = event["_trace"]["llm_attempts"][0]
    for key in ("requested_profile", "detoured", "probe"):
        assert key not in span
    payload = TickLoop._llm_call_payload("alpha", span)
    assert set(payload) == {
        "gen_ai.request.model", "gen_ai.response.model",
        "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
        "latency_ms", "gen_ai.response.finish_reasons", "cached", "attempt",
    }


@pytest.mark.asyncio
async def test_disabled_failover_runtime_path_is_byte_identical():
    router, alpha, beta = _e2e_router(lane_failover={"enabled": False})
    events: list[dict] = []
    router.set_lane_event_sink(events.append)
    agent, world = _world_with_agent()
    runtime = AgentRuntime(world, router)
    _sicken(router, "alpha", 3)  # sick — but failover is OFF

    event = await runtime.run_turn(agent)
    assert alpha.calls == [(512, 0.8)]  # home lane, home budget
    assert beta.calls == []
    assert events == []
    span = event["_trace"]["llm_attempts"][0]
    for key in ("requested_profile", "detoured", "probe"):
        assert key not in span
    payload = TickLoop._llm_call_payload("alpha", span)
    assert set(payload) == {
        "gen_ai.request.model", "gen_ai.response.model",
        "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
        "latency_ms", "gen_ai.response.finish_reasons", "cached", "attempt",
    }


# ──────────────────────────────────────────────────────────────────────────────
# (G) Config — params, round-trip, embedded mirror, shipped yaml
# ──────────────────────────────────────────────────────────────────────────────

def test_lane_failover_param_defaults():
    p = LaneFailoverParams()
    assert p.enabled is True
    assert p.sick_threshold == 3
    assert p.probe_every == 4
    assert WorldParams().lane_failover == p


def test_parse_world_reads_the_lane_failover_block():
    raw = {"world": {"lane_failover": {
        "enabled": False, "sick_threshold": 5, "probe_every": 2,
    }}}
    params, _, _ = _parse_world(raw)
    assert params.lane_failover == LaneFailoverParams(
        enabled=False, sick_threshold=5, probe_every=2,
    )


def test_parse_world_defaults_and_clamps_malformed_values():
    params, _, _ = _parse_world({"world": {}})
    assert params.lane_failover == LaneFailoverParams()
    params, _, _ = _parse_world({"world": {"lane_failover": {
        "sick_threshold": 0, "probe_every": "soon",
    }}})
    assert params.lane_failover.sick_threshold == 1   # clamped >= 1
    assert params.lane_failover.probe_every == 4      # malformed -> default


def test_config_round_trips_through_runs_config_json():
    # The fork/replay seam: WorldParams → runs.config_json → _parse_world.
    raw = {"world": {"lane_failover": {
        "enabled": False, "sick_threshold": 4, "probe_every": 6,
    }}}
    params, _, _ = _parse_world(raw)
    blob = json.loads(json.dumps(_world_params_json(params)))
    restored, _, _ = _parse_world({"world": blob})
    assert restored.lane_failover == params.lane_failover


def test_embedded_world_yaml_mirror_carries_the_block():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    params, _, _ = _parse_world(raw)
    assert params.lane_failover == LaneFailoverParams(
        enabled=True, sick_threshold=3, probe_every=4,
    )


def test_shipped_world_yaml_ships_failover_off_per_em205():
    """EM-205 — the shipped config deliberately turns the EM-177 pre-emptive
    detours OFF: the proxy's `auto` lane is now the universal backup (handled in
    router.chat() auto-backup, independent of this flag), so client-side detours
    are redundant. The library DEFAULT stays ON (embedded mirror test above);
    only the shipped deployment overrides it. Thresholds are preserved so
    re-enabling is a one-line flip."""
    path = Path(__file__).resolve().parents[2] / "config" / "world.yaml"
    raw = yaml.safe_load(path.read_text())
    params, _, _ = _parse_world(raw)
    assert params.lane_failover == LaneFailoverParams(
        enabled=False, sick_threshold=3, probe_every=4,
    )


# ──────────────────────────────────────────────────────────────────────────────
# (H) GET /api/lanes — shape
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


def test_api_lanes_shape(client):
    import sys
    _appmod = sys.modules["petridish.api.app"]
    router = _appmod._router
    router.clear_cache()
    # Seed two synthetic lanes (names outside the profile registry are
    # non-mock by definition, so the predicate is config-independent).
    for _ in range(3):
        router.note_parse_outcome(
            "lane-sick", parsed=False, truncated=False, timed_out=True)
    router.note_parse_outcome("lane-fine", parsed=True, truncated=False)

    body = client.get("/api/lanes").json()
    assert set(body) >= {"lane-sick", "lane-fine"}
    for entry in body.values():
        assert set(entry) >= {
            "window", "boosted", "timeouts", "last_routed_via",
            "sick", "detours_routed_here",
        }
        assert isinstance(entry["window"], list)
        assert isinstance(entry["detours_routed_here"], int)
    assert body["lane-sick"]["sick"] is True
    assert body["lane-sick"]["timeouts"] == 3
    assert body["lane-fine"]["sick"] is False
    router.clear_cache()


def test_app_lane_detour_sink_emits_a_feed_event(client):
    import sys
    _appmod = sys.modules["petridish.api.app"]
    # The lifespan wired the router sink to _emit_lane_detour; drive the
    # app-level emission directly and read it back from the event log.
    agent_id = next(iter(_appmod._world.agents))
    agent_name = _appmod._world.agents[agent_id].name
    _appmod._emit_lane_detour({
        "phase": "degraded", "home": "gemini-flash",
        "substitute": "mistral-small", "agent_id": agent_id,
    })
    _appmod._emit_lane_detour({
        "phase": "recovered", "home": "gemini-flash",
        "substitute": "mistral-small", "agent_id": agent_id,
    })
    rows = client.get("/api/events", params={"kinds": "lane_detour"}).json()
    events = rows["events"] if isinstance(rows, dict) else rows
    assert len(events) == 2
    degraded, recovered = events[0], events[1]
    assert degraded["payload"]["phase"] == "degraded"
    assert degraded["payload"]["home"] == "gemini-flash"
    assert degraded["payload"]["substitute"] == "mistral-small"
    assert agent_name in degraded["text"]
    assert "degraded" in degraded["text"]
    assert recovered["payload"]["phase"] == "recovered"
    assert "recovered" in recovered["text"]

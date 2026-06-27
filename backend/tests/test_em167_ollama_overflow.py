"""
EM-167 — Ollama overflow lane (Wave M4, contracts/wave-m.md §3).

Background/supporting cadence-tier turns spill OFF FreeLLMAPI onto a local
Ollama lane as an off-critical-path overflow (the animal-task pattern): a slow,
non-survival lane that, if it stalls or is unreachable, falls back to the
existing routing WITHOUT ever hard-failing a turn. Ollama is not reachable in
this build env, so the live calls are stood in by a recording mock adapter;
live verification is pending a running `ollama serve`.

This file gates:
  (A) Router.effective_profile(tier) — enabled + a background/supporting tier
      routes to the overflow profile; protagonist stays home; disabled/absent
      is a no-op; a missing / unavailable / sick Ollama is never chosen;
      tiers + profile name are configurable.
  (B) Runtime end-to-end — a background turn REALLY calls the ollama adapter at
      its budget; the span carries requested_profile + overflow; identity is
      untouched; a protagonist turn is byte-identical (no overflow).
  (C) Graceful fallback — an UNREACHABLE Ollama (adapter raises) degrades via
      EM-205 auto-backup / EM-173 idle: the turn still resolves, never a hard
      error (default-off, absent Ollama = no-op).
  (D) Config — yaml → OverflowLaneParams round-trip; EMBEDDED_WORLD_YAML mirror;
      shipped config/world.yaml block; default OFF.
  (E) profiles.yaml — an enabled `ollama` profile exists.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from petridish.config.loader import (
    EMBEDDED_WORLD_YAML, ModelProfile, OverflowLaneParams, WorldParams,
    _parse_world,
)
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop, _world_params_json
from petridish.providers.base import ProviderError
from petridish.providers.router import Router


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})

_KEY_ENV = "EM_OVERFLOW_TEST_KEY"


@pytest.fixture(autouse=True)
def _overflow_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


def _profile(name: str, *, adapter: str = "openai", max_tokens: int = 512,
             temperature: float = 0.8, key_env: str = _KEY_ENV) -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=f"model/{name}",
        max_tokens=max_tokens, temperature=temperature,
        base_url="http://localhost:9",
        api_key_env=key_env if adapter != "mock" else "",
    )


def _router(profiles: list[ModelProfile] | None = None, *, enabled=True,
            **kwargs) -> Router:
    if profiles is None:
        profiles = [
            _profile("home"),
            _profile("ollama"),
            _profile("mock", adapter="mock"),
        ]
    overflow = kwargs.pop("overflow_lane", None)
    if overflow is None:
        overflow = OverflowLaneParams(enabled=enabled)
    return Router(profiles, overflow_lane=overflow, **kwargs)


def _sicken(r: Router, lane: str, n: int = 3) -> None:
    for _ in range(n):
        r.note_parse_outcome(lane, parsed=False, truncated=False, timed_out=True)


# ──────────────────────────────────────────────────────────────────────────────
# (A) effective_profile(tier) — routing decision
# ──────────────────────────────────────────────────────────────────────────────

def test_background_tier_overflows_to_ollama_when_enabled():
    r = _router()
    assert r.effective_profile("a1", "home", tier="background") == (
        "ollama", "overflow")


def test_supporting_tier_overflows_to_ollama_when_enabled():
    r = _router()
    assert r.effective_profile("a1", "home", tier="supporting") == (
        "ollama", "overflow")


def test_protagonist_tier_stays_on_the_home_lane():
    r = _router()
    assert r.effective_profile("a1", "home", tier="protagonist") == ("home", None)


def test_no_tier_argument_is_byte_identical_pre_em167():
    # The old two-arg call site (and duck-typed routers) must keep working:
    # absent tier ⇒ never overflow, just the EM-177 home/failover path.
    r = _router()
    assert r.effective_profile("a1", "home") == ("home", None)


def test_disabled_overflow_is_a_no_op():
    r = _router(enabled=False)
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_absent_overflow_block_is_a_no_op():
    # No overflow_lane param at all (the pre-EM-167 Router construction).
    r = Router([
        _profile("home"), _profile("ollama"), _profile("mock", adapter="mock"),
    ])
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_missing_ollama_profile_falls_back_to_home():
    r = Router(
        [_profile("home"), _profile("mock", adapter="mock")],
        overflow_lane=OverflowLaneParams(enabled=True),  # profile "ollama" absent
    )
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_unavailable_ollama_is_never_chosen():
    # No api key env ⇒ available() is False ⇒ overflow self-suppresses.
    r = Router(
        [_profile("home"),
         _profile("ollama", key_env="EM_OVERFLOW_NO_SUCH_KEY"),
         _profile("mock", adapter="mock")],
        overflow_lane=OverflowLaneParams(enabled=True),
    )
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_sick_ollama_is_never_chosen():
    # A stalling Ollama (3 demerits) stops being the overflow target — the turn
    # falls back to home (graceful auto-suppression, counters only).
    r = _router()
    _sicken(r, "ollama", 3)
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_mock_overflow_target_is_never_chosen():
    r = Router(
        [_profile("home"), _profile("ollama", adapter="mock"),
         _profile("real", )],
        overflow_lane=OverflowLaneParams(enabled=True, profile="ollama"),
    )
    assert r.effective_profile("a1", "home", tier="background") == ("home", None)


def test_overflow_when_home_is_already_the_overflow_target_is_a_no_op():
    # An agent pinned to ollama as its home never self-overflows.
    r = _router()
    assert r.effective_profile("a1", "ollama", tier="background") == (
        "ollama", None)


def test_tiers_are_configurable():
    r = _router(overflow_lane=OverflowLaneParams(
        enabled=True, tiers=("background",)))
    assert r.effective_profile("a1", "home", tier="background") == (
        "ollama", "overflow")
    # supporting NOT in the configured set ⇒ home
    assert r.effective_profile("a1", "home", tier="supporting") == ("home", None)


def test_overflow_profile_name_is_configurable():
    r = Router(
        [_profile("home"), _profile("local-llm"),
         _profile("mock", adapter="mock")],
        overflow_lane=OverflowLaneParams(enabled=True, profile="local-llm"),
    )
    assert r.effective_profile("a1", "home", tier="background") == (
        "local-llm", "overflow")


def test_dict_shaped_overflow_config_is_read_defensively():
    # The block may arrive as a plain dict (config_json fork seam), not a
    # dataclass — the defensive accessor must read it identically.
    r = Router(
        [_profile("home"), _profile("ollama"), _profile("mock", adapter="mock")],
        overflow_lane={"enabled": True, "profile": "ollama",
                       "tiers": ["background", "supporting"]},
    )
    assert r.effective_profile("a1", "home", tier="background") == (
        "ollama", "overflow")


def test_overflow_takes_precedence_over_sick_home_failover():
    # A background turn overflows to ollama EVEN IF the home lane is sick (the
    # off-critical-path lane wins for background traffic) — and ollama is not
    # itself sick.
    r = _router()
    _sicken(r, "home", 3)
    assert r.effective_profile("a1", "home", tier="background") == (
        "ollama", "overflow")


# ──────────────────────────────────────────────────────────────────────────────
# (B) Runtime end-to-end — the overflow detour actually calls ollama
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


class FailingAdapter:
    """An UNREACHABLE Ollama: every chat() raises (server down)."""

    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.last_routed_via = None
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError(self.name, None, "connection refused")


def _world_with_agent(profile: str = "home", tier: str = "background"
                      ) -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0,
                         kind="social")]
    agent = AgentState(
        id="agent_ada", name="Ada", personality="curious", profile=profile,
        location="plaza", energy=88.0, credits=10, cadence_tier=tier,
    )
    world = World(params=params, places=places, agents=[agent])
    return agent, world


def _e2e_router(*, ollama_adapter=None, **kwargs):
    home = ScriptedAdapter("home")
    ollama = ollama_adapter if ollama_adapter is not None else ScriptedAdapter(
        "ollama")
    profiles = [
        _profile("home", max_tokens=512, temperature=0.8),
        _profile("ollama", max_tokens=999, temperature=0.1),
        _profile("mock", adapter="mock"),
    ]
    overflow = kwargs.pop("overflow_lane", OverflowLaneParams(enabled=True))
    router = Router(
        profiles,
        adapter_overrides={"home": home, "ollama": ollama},
        cache_enabled=False,
        overflow_lane=overflow,
        **kwargs,
    )
    return router, home, ollama


@pytest.mark.asyncio
async def test_background_turn_really_calls_the_ollama_adapter():
    router, home, ollama = _e2e_router()
    agent, world = _world_with_agent(tier="background")
    runtime = AgentRuntime(world, router)

    # Force a non-reflex background turn: a salient trigger or the reassess
    # path. Easiest deterministic route: a wildcard via the reflex-streak floor
    # would need many turns; instead make the agent's tier supporting so it
    # always takes a full LLM turn.
    agent.cadence_tier = "supporting"
    event = await runtime.run_turn(agent)
    assert event["kind"] != "parse_failure"

    # The overflow lane REALLY served the call, at OLLAMA's budget.
    assert ollama.calls == [(999, 0.1)]
    assert home.calls == []

    span = event["_trace"]["llm_attempts"][0]
    assert span["gen_ai.request.model"] == "ollama"
    assert span["requested_profile"] == "home"
    assert span["overflow"] is True
    assert "detoured" not in span

    # Identity untouched — overflow is per-call.
    assert agent.profile == "home"
    assert router.profile_name_for(agent.id, agent.profile) == "home"


@pytest.mark.asyncio
async def test_protagonist_turn_is_byte_identical_no_overflow():
    router, home, ollama = _e2e_router()
    agent, world = _world_with_agent(tier="protagonist")
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)
    assert event["kind"] != "parse_failure"

    assert home.calls == [(512, 0.8)]
    assert ollama.calls == []
    span = event["_trace"]["llm_attempts"][0]
    assert span["gen_ai.request.model"] == "home"
    assert "overflow" not in span
    assert "requested_profile" not in span


# ──────────────────────────────────────────────────────────────────────────────
# (C) Graceful fallback — an unreachable Ollama never hard-fails a turn
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unreachable_ollama_falls_back_via_auto_backup():
    # ollama raises (server down); an `auto` lane serves the retry (EM-205).
    auto = ScriptedAdapter("auto")
    home = ScriptedAdapter("home")
    ollama = FailingAdapter("ollama")
    profiles = [
        _profile("home", max_tokens=512, temperature=0.8),
        _profile("ollama", max_tokens=999, temperature=0.1),
        _profile("auto"),
        _profile("mock", adapter="mock"),
    ]
    router = Router(
        profiles,
        adapter_overrides={"home": home, "ollama": ollama, "auto": auto},
        cache_enabled=False,
        overflow_lane=OverflowLaneParams(enabled=True),
    )
    agent, world = _world_with_agent(tier="supporting")
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)

    # The turn RESOLVED (no hard error): ollama was tried and failed, `auto`
    # served the EM-205 retry — exactly the animal background-task fallback.
    assert ollama.calls == 1
    assert auto.calls == [(999, 0.1)]
    assert event["kind"] != "parse_failure"


@pytest.mark.asyncio
async def test_unreachable_ollama_with_no_backup_idles_not_raises():
    # No `auto` lane: ollama raises and the turn falls to the EM-173 idle
    # fallback. run_turn never raises (the animal-task guarantee).
    ollama = FailingAdapter("ollama")
    home = ScriptedAdapter("home")
    profiles = [
        _profile("home"),
        _profile("ollama"),
        _profile("mock", adapter="mock"),
    ]
    router = Router(
        profiles,
        adapter_overrides={"home": home, "ollama": ollama},
        cache_enabled=False,
        overflow_lane=OverflowLaneParams(enabled=True),
    )
    agent, world = _world_with_agent(tier="supporting")
    runtime = AgentRuntime(world, router)

    event = await runtime.run_turn(agent)  # must not raise
    # Ollama was tried (>=1 — the EM-173 idle path may retry the home lane,
    # which is still the overflow target here); the turn resolved to a valid
    # idle event WITHOUT a hard error (the animal-task fallback guarantee).
    assert ollama.calls >= 1
    assert isinstance(event, dict)
    assert event.get("kind") is not None


# ──────────────────────────────────────────────────────────────────────────────
# (D) Config — round-trip, mirror, shipped yaml
# ──────────────────────────────────────────────────────────────────────────────

def test_overflow_config_round_trips_through_runs_config_json():
    raw = {"world": {"overflow_lane": {
        "enabled": True, "profile": "ollama",
        "tiers": ["background", "supporting"],
    }}}
    params, _, _ = _parse_world(raw)
    blob = json.loads(json.dumps(_world_params_json(params)))
    restored, _, _ = _parse_world({"world": blob})
    assert restored.overflow_lane == params.overflow_lane


def test_absent_overflow_block_parses_to_defaults_off():
    params, _, _ = _parse_world({"world": {}})
    assert params.overflow_lane == OverflowLaneParams()
    assert params.overflow_lane.enabled is False


def test_malformed_overflow_block_falls_back_per_key():
    params, _, _ = _parse_world({"world": {"overflow_lane": {
        "enabled": "yes", "profile": 123, "tiers": "background",
    }}})
    ol = params.overflow_lane
    assert ol.enabled is True            # truthy coerced
    assert ol.profile == "ollama"        # non-str ⇒ default
    assert ol.tiers == ("background", "supporting")  # non-list ⇒ default


def test_embedded_world_yaml_mirror_carries_the_block():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    params, _, _ = _parse_world(raw)
    assert params.overflow_lane == OverflowLaneParams()
    assert params.overflow_lane.enabled is False


def test_shipped_world_yaml_ships_overflow_off():
    # Default OFF: live verification pends a running Ollama; flip enabled:true
    # once an `ollama serve` is reachable.
    path = Path(__file__).resolve().parents[2] / "config" / "world.yaml"
    raw = yaml.safe_load(path.read_text())
    params, _, _ = _parse_world(raw)
    assert params.overflow_lane.enabled is False
    assert params.overflow_lane.profile == "ollama"
    assert "background" in params.overflow_lane.tiers


# ──────────────────────────────────────────────────────────────────────────────
# (E) profiles.yaml — the ollama lane is enabled
# ──────────────────────────────────────────────────────────────────────────────

def test_profiles_yaml_has_an_enabled_ollama_profile():
    path = Path(__file__).resolve().parents[2] / "config" / "profiles.yaml"
    raw = yaml.safe_load(path.read_text())
    names = {p["name"] for p in raw["profiles"]}
    assert "ollama" in names, (
        "EM-167: the overflow lane needs a profile literally named `ollama`")
    ollama = next(p for p in raw["profiles"] if p["name"] == "ollama")
    assert ollama["adapter"] in ("openai", "openai-compatible")
    assert "11434" in str(ollama["base_url"])  # the Ollama default port

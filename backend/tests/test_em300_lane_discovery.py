"""
EM-300 P2 — dynamic lane discovery/refresh (spec 2026-07-07 §4/§9/§10).

Hermetic: every HTTP surface is mocked (httpx.MockTransport) — the suite NEVER
touches the real FreeLLMAPI proxy. Covers the spec §10 P2 rows:

  (A) parse/fetch — /v1/models availability parsing (the §11 Q1 shape: `available`
      + `unavailable_reason`), admin quota fetch, direct-key detection.
  (B) merge_universe — the pure merge: discovered adds (synth), unavailable
      retires, direct-key gating, idempotency, flag gating.
  (C) router refresh — discovered adds/removes reflected in the registry;
      exclude honored; paid excluded without allow_paid; the terminal `auto`
      reservation follows `auto` by name (never inherited); health carries
      across refreshes; clear_cache drops synth + resets to the static registry.
  (D) counter cadence — note_served_turn gates every N served turns; no-op OFF.
  (E) determinism / byte-identical OFF — discovery:false ⇒ no fetch, no registry
      delta, config asdict round-trip stable.
  (F) endpoints — GET /api/lanes/registry, POST /api/lanes/refresh, and
      GET /api/lanes byte-identical (profile-keyed health map).

Repo rule: import petridish.engine.world BEFORE petridish.agents.runtime.
"""
from __future__ import annotations

from dataclasses import asdict

import httpx
import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, DiscoveryParams, LaneOrderEntry, ModelProfile,
    _parse_adaptive_routing, _parse_discovery,
)
from petridish.providers import discovery as disco
from petridish.providers.base import ProviderError
from petridish.providers.discovery import (
    DiscoveredModel, FreeLLMTemplate, SynthLaneSpec,
    detect_direct_sources, fetch_admin_quota, fetch_freellmapi_catalog,
    merge_universe, parse_models,
)
from petridish.providers.lanes import Lane
from petridish.providers.router import Router

_KEY_ENV = "EM_EM300_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


# ── fakes + builders ──────────────────────────────────────────────────────────

class _OkAdapter:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.last_routed_via = f"routed/{name}"
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_usage = {"input_tokens": 1, "output_tokens": 1,
                           "latency_ms": 1.0, "finish_reason": "stop"}
        return f"served/{self.name}"


class _FailAdapter:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.last_routed_via = None
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError(self.name, 429, "Too Many Requests")


def _profile(name: str, model_id: str, *, adapter: str = "openai",
             max_tokens: int = 512) -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=model_id,
        max_tokens=max_tokens, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _disco(*, enabled=True, every_turns=40, freellmapi_models=True,
           direct_keys=True, admin_quota=False) -> DiscoveryParams:
    return DiscoveryParams(
        enabled=enabled, every_turns=every_turns,
        freellmapi_models=freellmapi_models, direct_keys=direct_keys,
        admin_quota=admin_quota)


def _mk_router(profiles, *, order, overrides=None, discovery=None,
               allow_paid=False, exclude=(), auto=False) -> Router:
    profs = list(profiles)
    ov = dict(overrides or {})
    if auto:
        profs.append(_profile("auto", "auto"))
        ov.setdefault("auto", _OkAdapter("auto"))
    ar = AdaptiveRoutingParams(
        enabled=True, order=tuple(order), allow_paid=allow_paid,
        exclude=tuple(exclude), discovery=discovery or DiscoveryParams())
    return Router(profs, adapter_overrides=ov, cache_enabled=False,
                  adaptive_routing=ar)


def _mock_factory(handler):
    """A client_factory yielding an httpx.AsyncClient wired to a MockTransport
    (the suite never hits a real host)."""
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _lane(profile, model_id, *, source="freellmapi", free=True):
    return Lane(id=f"{source}:{profile}", source=source, model_id=model_id,
                profile=profile, free=free)


def _ids(view):
    return {ln["model_id"] for ln in view["lanes"]}


# ══════════════════════════════════════════════════════════════════════════════
# (A) parse / fetch / detect
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_models_reads_availability_shape():
    # The live shape (probe 2026-07-15): available + unavailable_reason.
    payload = {"object": "list", "data": [
        {"id": "m1", "available": True, "context_window": 131072},
        {"id": "m2", "available": False, "unavailable_reason": "no_key"},
        {"id": "m3", "available": False, "unavailable_reason": "disabled"},
        {"bad": "no-id"},
    ]}
    out = parse_models(payload)
    assert [m.id for m in out] == ["m1", "m2", "m3"]     # id-less row skipped
    assert out[0].available is True and out[0].context_window == 131072
    assert out[1].available is False and out[1].unavailable_reason == "no_key"


def test_parse_models_defensive_on_garbage():
    assert parse_models(None) == []
    assert parse_models("nope") == []
    assert parse_models({"data": "notalist"}) == []
    # availability defaults TRUE when the proxy omits it (older builds).
    assert parse_models({"data": [{"id": "x"}]})[0].available is True


def test_detect_direct_sources_by_env_presence():
    env = {"GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "  ", "OLLAMA_BASE_URL": "u"}
    got = detect_direct_sources(env)
    assert got["gemini"] is True          # present
    assert got["anthropic"] is False      # whitespace-only ⇒ absent
    assert got["openai"] is False         # missing
    assert got["ollama"] is True


@pytest.mark.asyncio
async def test_fetch_catalog_hermetic_and_defensive():
    def ok(request):
        assert request.url.path.endswith("/models")
        assert request.headers.get("Authorization") == "Bearer k"
        return httpx.Response(200, json={"data": [
            {"id": "a", "available": True},
            {"id": "b", "available": False, "unavailable_reason": "no_key"}]})
    out = await fetch_freellmapi_catalog(
        "http://proxy/v1", "k", client_factory=_mock_factory(ok))
    assert [(m.id, m.available) for m in out] == [("a", True), ("b", False)]

    def boom(request):
        return httpx.Response(500, text="down")
    assert await fetch_freellmapi_catalog(
        "http://proxy/v1", "k", client_factory=_mock_factory(boom)) == []


@pytest.mark.asyncio
async def test_fetch_admin_quota_hermetic_and_credless():
    def handler(request):
        if request.url.path.endswith("/auth/login"):
            return httpx.Response(200, json={"token": "T"})
        assert request.headers.get("Authorization") == "Bearer T"
        return httpx.Response(200, json={"quotaStates": [
            {"platform": "cerebras", "metric": "requests", "remaining": 2399}]})
    qs = await fetch_admin_quota(
        "http://proxy", "e@x", "pw", client_factory=_mock_factory(handler))
    assert isinstance(qs, list) and qs[0]["platform"] == "cerebras"
    # no creds ⇒ None, no network
    assert await fetch_admin_quota("", "", "") is None


# ══════════════════════════════════════════════════════════════════════════════
# (B) merge_universe — the pure merge
# ══════════════════════════════════════════════════════════════════════════════

def _tmpl():
    return FreeLLMTemplate(base_url="http://localhost:3001/v1", api_key="k")


def test_merge_synthesizes_lane_for_new_available_model():
    existing = [_lane("home", "home-model")]
    discovered = [DiscoveredModel("home-model", available=True),
                  DiscoveredModel("new-model", available=True,
                                  context_window=131072)]
    res = merge_universe(existing, discovered, freellmapi_template=_tmpl())
    # home kept (available), new-model synthesized
    assert {ln.model_id for ln in res.universe} == {"home-model", "new-model"}
    assert res.synth == (SynthLaneSpec(
        profile="disco:new-model", model_id="new-model", ctx_hint=131072),)
    synth_lane = next(ln for ln in res.universe if ln.model_id == "new-model")
    assert synth_lane.profile == "disco:new-model"
    assert synth_lane.source == "freellmapi"


def test_merge_retires_configured_lane_the_catalog_marks_unavailable():
    existing = [_lane("home", "home-model"), _lane("dead", "dead-model")]
    discovered = [DiscoveredModel("home-model", available=True),
                  DiscoveredModel("dead-model", available=False,
                                  unavailable_reason="no_key")]
    res = merge_universe(existing, discovered, freellmapi_template=_tmpl())
    assert {ln.model_id for ln in res.universe} == {"home-model"}
    assert ("freellmapi:dead", "no_key") in res.retired


def test_merge_keeps_lane_absent_from_catalog():
    # A configured lane the catalog does not mention is KEPT (defensive).
    existing = [_lane("home", "home-model")]
    res = merge_universe(existing, [DiscoveredModel("other", available=True)],
                         freellmapi_template=_tmpl())
    assert "home-model" in {ln.model_id for ln in res.universe}


def test_merge_direct_key_gating():
    direct = [_lane("gem", "gemini-x", source="gemini")]
    # direct_keys ON + key absent ⇒ retired
    res = merge_universe(direct, [], direct_sources={"gemini": False},
                         direct_keys=True)
    assert res.universe == () and ("gemini:gem", "no_direct_key") in res.retired
    # key present ⇒ kept
    res2 = merge_universe(direct, [], direct_sources={"gemini": True},
                          direct_keys=True)
    assert [ln.model_id for ln in res2.universe] == ["gemini-x"]
    # direct_keys OFF ⇒ pass-through (P1 behavior), no gating
    res3 = merge_universe(direct, [], direct_sources={"gemini": False},
                          direct_keys=False)
    assert [ln.model_id for ln in res3.universe] == ["gemini-x"]


def test_merge_is_idempotent_and_flag_gated():
    existing = [_lane("home", "home-model")]
    discovered = [DiscoveredModel("new-model", available=True)]
    once = merge_universe(existing, discovered, freellmapi_template=_tmpl())
    # feed the once-result's own freellmapi lanes back: no double-synth
    twice = merge_universe(once.universe, discovered, freellmapi_template=_tmpl())
    assert {ln.model_id for ln in twice.universe} == {"home-model", "new-model"}
    assert twice.synth == ()          # already covered, not re-synthesized
    # freellmapi_models OFF ⇒ no synth, no retire
    off = merge_universe(existing, [DiscoveredModel("home-model", available=False)],
                         freellmapi_template=_tmpl(), freellmapi_models=False)
    assert {ln.model_id for ln in off.universe} == {"home-model"}
    assert off.synth == ()


def test_merge_no_template_synthesizes_nothing():
    res = merge_universe([_lane("home", "home-model")],
                         [DiscoveredModel("new", available=True)],
                         freellmapi_template=None)
    assert res.synth == ()
    assert {ln.model_id for ln in res.universe} == {"home-model"}


# ══════════════════════════════════════════════════════════════════════════════
# (C) router refresh — registry rebuild
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_refresh_adds_discovered_lane_and_builds_adapter():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        discovery=_disco())
    assert _ids(r.lanes_view()) == {"home-model"}       # static P1 registry
    did = await r.refresh_lanes(
        catalog=[DiscoveredModel("home-model", available=True),
                 DiscoveredModel("disco-x", available=True)], env={})
    assert did is True
    view = r.lanes_view()
    assert _ids(view) == {"home-model", "disco-x"}      # swept in
    dl = next(ln for ln in view["lanes"] if ln["model_id"] == "disco-x")
    assert dl["discovered"] is True and dl["enabled"] is True
    # a real callable adapter was synthesized for it
    from petridish.providers.adapters import OpenAICompatibleAdapter
    assert isinstance(r._adapters["disco:disco-x"], OpenAICompatibleAdapter)


@pytest.mark.asyncio
async def test_refresh_removes_vanished_lane():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        discovery=_disco())
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("temp", available=True)], env={})
    assert "temp" in _ids(r.lanes_view())
    # temp no longer available ⇒ drops out next refresh
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("temp", available=False,
                                                   unavailable_reason="disabled")],
                          env={})
    assert "temp" not in _ids(r.lanes_view())


@pytest.mark.asyncio
async def test_refresh_honors_exclude_denylist():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        exclude=[LaneOrderEntry("freellmapi", "banned")],
        discovery=_disco())
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("banned", available=True),
                                   DiscoveredModel("ok", available=True)], env={})
    ids = _ids(r.lanes_view())
    assert "ok" in ids and "banned" not in ids     # denylist beats the sweep


@pytest.mark.asyncio
async def test_refresh_excludes_paid_without_allow_paid():
    r = _mk_router(
        [_profile("home", "home-model"),
         _profile("claude", "claude-sonnet-5", adapter="anthropic")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*"),
               LaneOrderEntry("anthropic", "claude-sonnet-5", free=False)],
        discovery=_disco(direct_keys=False),   # don't gate the direct lane on key
        allow_paid=False)
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("free-x", available=True)], env={})
    ids = _ids(r.lanes_view())
    assert "free-x" in ids                       # discovered free lane placed
    assert "claude-sonnet-5" not in ids          # paid still excluded (allow_paid off)


@pytest.mark.asyncio
async def test_terminal_auto_reservation_follows_auto_by_name_after_discovery():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*"),
               LaneOrderEntry("freellmapi", "auto")],
        discovery=_disco(), auto=True)
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("auto", available=True),
                                   DiscoveredModel("disco-x", available=True)], env={})
    # the reserved backstop is still `auto` by name — no discovered lane inherits it
    assert r._terminal_fallback_profile() == "auto"
    view = r.lanes_view()
    assert "auto" in {ln["profile"] for ln in view["lanes"]}


@pytest.mark.asyncio
async def test_refresh_serves_a_bounce_from_a_discovered_lane():
    # Inject a fake adapter under the synth profile so the bounce is hermetic.
    ok = _OkAdapter("disco:good")
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        overrides={"home": _FailAdapter("home"), "disco:good": ok},
        discovery=_disco())
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("good", available=True)], env={})
    text = await r.chat("home", _MESSAGES, max_tokens=64, temperature=0.8)
    assert text == "served/disco:good" and ok.calls == 1


@pytest.mark.asyncio
async def test_discovered_lane_health_carries_across_refresh():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        discovery=_disco())
    cat = [DiscoveredModel("home-model", available=True),
           DiscoveredModel("sicky", available=True)]
    await r.refresh_lanes(catalog=cat, env={})
    # drive the synth lane sick (3 error demerits in the window)
    for _ in range(3):
        r.note_lane_error("disco:sicky")
    assert r.lane_sick("disco:sicky") is True
    await r.refresh_lanes(catalog=cat, env={})     # same catalog, re-ranked
    sick = next(ln for ln in r.lanes_view()["lanes"] if ln["profile"] == "disco:sicky")
    assert sick["health"] == "sick"                # window survived the rebuild


@pytest.mark.asyncio
async def test_clear_cache_drops_synth_and_resets_to_static_registry():
    r = _mk_router(
        [_profile("home", "home-model")],
        order=[LaneOrderEntry("freellmapi", "home-model"),
               LaneOrderEntry("freellmapi", "*")],
        discovery=_disco())
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True),
                                   DiscoveredModel("gone", available=True)], env={})
    assert "disco:gone" in r._adapters and "gone" in _ids(r.lanes_view())
    r.clear_cache()
    assert "disco:gone" not in r._adapters         # synth adapter dropped
    assert _ids(r.lanes_view()) == {"home-model"}  # back to the static registry
    assert r._discovery_served == 0


@pytest.mark.asyncio
async def test_admin_quota_fetched_only_when_opted_in(monkeypatch):
    calls = {"n": 0}

    async def fake_quota(self, env):
        calls["n"] += 1
        return [{"platform": "groq"}]
    monkeypatch.setattr(Router, "_fetch_admin_quota_from_env", fake_quota)

    r = _mk_router([_profile("home", "home-model")],
                   order=[LaneOrderEntry("freellmapi", "*")],
                   discovery=_disco(admin_quota=False))
    await r.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True)],
                          env={})
    assert calls["n"] == 0                         # opt-in off ⇒ no admin fetch

    r2 = _mk_router([_profile("home", "home-model")],
                    order=[LaneOrderEntry("freellmapi", "*")],
                    discovery=_disco(admin_quota=True))
    await r2.refresh_lanes(catalog=[DiscoveredModel("home-model", available=True)],
                           env={})
    assert calls["n"] == 1 and r2._discovery_quota == [{"platform": "groq"}]


# ══════════════════════════════════════════════════════════════════════════════
# (D) counter-gated cadence
# ══════════════════════════════════════════════════════════════════════════════

def test_note_served_turn_gates_every_n():
    r = _mk_router([_profile("home", "home-model")],
                   order=[LaneOrderEntry("freellmapi", "*")],
                   discovery=_disco(every_turns=3))
    got = [r.note_served_turn() for _ in range(7)]
    assert got == [False, False, True, False, False, True, False]
    assert r._discovery_served == 7


def test_note_served_turn_is_noop_when_discovery_off():
    r = _mk_router([_profile("home", "home-model")],
                   order=[LaneOrderEntry("freellmapi", "*")],
                   discovery=_disco(enabled=False))
    assert [r.note_served_turn() for _ in range(5)] == [False] * 5
    assert r._discovery_served == 0                # counter untouched


# ══════════════════════════════════════════════════════════════════════════════
# (E) determinism / byte-identical OFF
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_discovery_off_is_byte_identical_and_refresh_is_noop():
    profs = [_profile("home", "home-model")]
    order = [LaneOrderEntry("freellmapi", "home-model"),
             LaneOrderEntry("freellmapi", "*")]
    # a router with NO discovery block vs one with discovery explicitly OFF
    base = _mk_router(profs, order=order, discovery=None)
    off = _mk_router([_profile("home", "home-model")], order=order,
                     discovery=_disco(enabled=False))
    assert base.lane_registry_snapshot() == off.lane_registry_snapshot()
    # refresh is a no-op OFF: returns False, registry unchanged even if a catalog
    # is (wrongly) supplied
    before = off.lane_registry_snapshot()
    assert await off.refresh_lanes(
        catalog=[DiscoveredModel("intruder", available=True)], env={}) is False
    assert off.lane_registry_snapshot() == before


def test_discovery_params_default_is_disabled():
    assert DiscoveryParams().enabled is False
    assert AdaptiveRoutingParams().discovery == DiscoveryParams()


def test_parse_discovery_defensive():
    assert _parse_discovery(None) == DiscoveryParams()
    assert _parse_discovery({}) == DiscoveryParams()
    assert _parse_discovery("junk") == DiscoveryParams()
    assert _parse_discovery({"enabled": True, "every_turns": 0}).every_turns == 1
    got = _parse_discovery({"enabled": True, "every_turns": 9,
                            "direct_keys": False})
    assert got == DiscoveryParams(enabled=True, every_turns=9, direct_keys=False)


def test_config_json_asdict_round_trip_with_discovery():
    original = AdaptiveRoutingParams(
        enabled=True, order=(LaneOrderEntry("freellmapi", "*"),),
        discovery=DiscoveryParams(enabled=True, every_turns=25,
                                  admin_quota=True))
    reparsed = _parse_adaptive_routing(asdict(original))
    assert reparsed == original
    assert reparsed.discovery.every_turns == 25


def test_absent_discovery_block_round_trips_default():
    # an old config_json (no discovery key) reparses to the disabled default
    raw = asdict(AdaptiveRoutingParams(enabled=True))
    raw.pop("discovery")
    assert _parse_adaptive_routing(raw).discovery == DiscoveryParams()


# ══════════════════════════════════════════════════════════════════════════════
# (F) endpoints (over the real app; default config ships discovery OFF)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    import sys
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    _appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as c:
        if _appmod._world is not None:
            _appmod._world.params.animals.enabled = False
            _appmod._world.animals.clear()
        yield c


def test_api_lanes_registry_view(client):
    body = client.get("/api/lanes/registry").json()
    assert set(body) >= {"lanes", "discovery"}
    assert isinstance(body["lanes"], list)
    assert set(body["discovery"]) >= {
        "enabled", "served_turns", "last_refresh_counter", "retired"}
    if body["lanes"]:
        assert set(body["lanes"][0]) >= {
            "id", "source", "priority", "enabled", "health", "cap_state",
            "discovered", "last_refresh_counter"}


def test_api_lanes_refresh_noop_when_disabled(client):
    # the default config ships discovery OFF ⇒ refresh is a safe no-op
    body = client.post("/api/lanes/refresh").json()
    assert body["refreshed"] is False
    assert "lanes" in body and "discovery" in body


def test_api_lanes_health_endpoint_still_profile_keyed(client):
    # GET /api/lanes stays the byte-identical profile-keyed health map — the
    # discovery view lives at the additive /api/lanes/registry sibling.
    body = client.get("/api/lanes").json()
    assert isinstance(body, dict)
    assert "lanes" not in body and "discovery" not in body   # not the registry shape

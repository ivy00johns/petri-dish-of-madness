"""EM-307 — per-call chat attribution (the pending-snapshot concurrency fix).

Concurrent chat() calls on ONE profile (narrator / deep-dive / animal
background tasks sharing an agent's lane) clobber the router's per-profile
`_pending_cached` EM-198 attribution snapshot: the second call's MISS-path pop
(or its own staging) rewrites the snapshot before the first caller's
last_usage()/last_routed_via()/note_parse_outcome() reads, misattributing
usage and — since W30 credits bounced outcomes to the serving lane — lane
HEALTH. The fix moves attribution to per-call state:

  (A) chat_attributed() returns (text, {routed_via, usage, served_by}) — this
      call's truth, for every path (home serve / adaptive bounce / EM-205
      backup / cache HIT), byte-equal to what the single-caller profile-level
      reads produced before.
  (B) chat() stays the text façade and still stages the pending snapshot
      byte-identically (the single-caller last_usage contract + old tests).
  (C) Interleaved calls on one profile each get their OWN attribution even
      though the shared snapshot can only reflect one of them.
  (D) note_parse_outcome(served_by=...) credits the serving lane from the
      per-call channel — no pending read; stale/absent snapshots can no
      longer misroute a health credit. Adaptive OFF ignores served_by (the
      #76 byte-identical attribution guarantee).
  (E) The runtimes thread it through: AgentRuntime consumes chat_attributed()
      when the router offers it (meta from the per-call record, served_by
      into note_parse_outcome) and falls back to the historical chat() +
      profile reads for duck-typed routers.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime.
"""
from __future__ import annotations

import asyncio

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile, WorldParams,
)
from petridish.engine.world import AgentState, PlaceState, World
from petridish.agents.runtime import AgentRuntime
from petridish.animals.runtime import AnimalRuntime
from petridish.engine.loop import TickLoop
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

pytestmark = pytest.mark.asyncio

_KEY_ENV = "EM_307_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


class _OkAdapter:
    def __init__(self, name: str, text: str | None = None):
        self.name = name
        self.text = text if text is not None else f"served/{name}"
        self.calls = 0
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


class _GatedOkAdapter(_OkAdapter):
    """Serves only after `gate` is set — forces two calls to interleave."""

    def __init__(self, name: str):
        super().__init__(name)
        self.gate = asyncio.Event()

    async def chat(self, messages, *, max_tokens, temperature):
        await self.gate.wait()
        return await super().chat(messages, max_tokens=max_tokens,
                                  temperature=temperature)


class _FlakyAdapter(_OkAdapter):
    """Fails its first `fail_first` calls with a 429, then serves."""

    def __init__(self, name: str, *, fail_first: int):
        super().__init__(name)
        self.fail_first = fail_first

    async def chat(self, messages, *, max_tokens, temperature):
        if self.calls < self.fail_first:
            self.calls += 1
            raise ProviderError(self.name, 429, "Too Many Requests")
        return await super().chat(messages, max_tokens=max_tokens,
                                  temperature=temperature)


def _profile(name: str, model_id: str, *, adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=model_id,
        max_tokens=512, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _router(specs, *, adaptive: bool = True, cache_enabled: bool = False) -> Router:
    """specs: list of (profile_name, model_id, adapter_obj)."""
    profiles = [_profile(n, m) for (n, m, _a) in specs]
    overrides = {n: a for (n, _m, a) in specs}
    ar = AdaptiveRoutingParams(
        enabled=adaptive, max_attempts=3, allow_paid=False,
        per_attempt_timeout_s=12.0,
        order=(LaneOrderEntry("freellmapi", "*"),),
    )
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=cache_enabled,
        adaptive_routing=ar,
    )


def _sicken(r: Router, profile: str, n: int = 3) -> None:
    for _ in range(n):
        r.note_lane_error(profile)


def _demerits(r: Router, profile: str) -> int:
    entry = r.lane_health().get(profile) or {}
    return len(entry.get("window") or [])


# ══════════════════════════════════════════════════════════════════════════════
# (A) chat_attributed returns this call's truth, byte-equal to the profile reads
# ══════════════════════════════════════════════════════════════════════════════

async def test_home_serve_attribution_matches_single_caller_profile_reads():
    home = _OkAdapter("home")
    r = _router([("home", "m-home", home)])
    text, attr = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "served/home"
    assert attr["served_by"] == "home"
    # Byte-equal to what the single-caller profile-level reads report.
    assert attr["usage"] == r.last_usage("home")
    assert attr["routed_via"] == r.last_routed_via("home") == "routed/home"


async def test_bounced_attribution_carries_the_substitute_truth():
    home = _OkAdapter("home", text="home (never called — sick)")
    sub = _OkAdapter("sub", text="sub served")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)])
    _sicken(r, "home")

    text, attr = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "sub served"
    assert home.calls == 0                      # pre-emptively skipped (sick)
    assert attr["served_by"] == "sub"
    assert attr["routed_via"] == "routed/sub"
    assert attr["usage"]["bounced_from"] == "home"
    assert attr["usage"]["bounced_to"] == "sub"
    # Single caller: the staged EM-198 pending snapshot agrees exactly.
    assert attr["usage"] == r.last_usage("home")
    assert attr["routed_via"] == r.last_routed_via("home")


async def test_cache_hit_attribution_is_the_cached_snapshot():
    home = _OkAdapter("home")
    r = _router([("home", "m-home", home)], cache_enabled=True)
    text1, attr1 = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    text2, attr2 = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 1                      # second call served from cache
    assert text2 == text1
    assert attr1["usage"]["cached"] is False
    assert attr2["usage"]["cached"] is True
    assert attr2["usage"]["input_tokens"] is None
    assert attr2["served_by"] == "home"
    assert attr2["routed_via"] == "routed/home"
    # And the HIT snapshot still surfaces on the profile reads (W7 contract).
    assert r.last_usage("home") == attr2["usage"]


async def test_chat_facade_still_returns_text_and_stages_the_snapshot():
    home = _OkAdapter("home", text="home (never called — sick)")
    sub = _OkAdapter("sub", text="sub served")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)])
    _sicken(r, "home")
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "sub served"                 # a plain str — the old interface
    usage = r.last_usage("home")                # single-caller EM-198 contract
    assert usage["bounced_from"] == "home" and usage["bounced_to"] == "sub"


# ══════════════════════════════════════════════════════════════════════════════
# (C) interleaved calls on ONE profile — each gets its own attribution
# ══════════════════════════════════════════════════════════════════════════════

async def test_concurrent_calls_on_one_profile_keep_their_own_attribution():
    # Call A on `home` (sick) bounces to the GATED `sub` and parks there;
    # call B starts AFTER A parked, and `home` — probed on B per the recovery
    # cadence — serves it from home. B finishes FIRST. Pre-EM-307 A's caller
    # then read B's truth off the shared profile snapshot; the per-call
    # records must each keep their own.
    home = _OkAdapter("home", text="home served")
    sub = _GatedOkAdapter("sub")
    lf = {"probe_every": 2}     # B (2nd would-be-detour) probes home → serves
    profiles = [_profile("sub", "m-sub"), _profile("home", "m-home")]
    ar = AdaptiveRoutingParams(
        enabled=True, max_attempts=3, allow_paid=False,
        per_attempt_timeout_s=12.0, order=(LaneOrderEntry("freellmapi", "*"),),
    )
    r = Router(profiles, adapter_overrides={"sub": sub, "home": home},
               cache_enabled=False, adaptive_routing=ar, lane_failover=lf)
    _sicken(r, "home")

    task_a = asyncio.create_task(r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8))
    for _ in range(10):         # let A reach the gated sub adapter
        await asyncio.sleep(0)
    text_b, attr_b = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    sub.gate.set()              # release A
    text_a, attr_a = await task_a

    assert text_a == "served/sub" and attr_a["served_by"] == "sub"
    assert attr_a["usage"]["bounced_to"] == "sub"
    assert text_b == "home served" and attr_b["served_by"] == "home"
    assert "bounced_to" not in (attr_b["usage"] or {})
    # The shared per-profile snapshot can only reflect ONE of them (here the
    # later-finishing A) — exactly why callers must not read it concurrently.
    assert r.last_usage("home") == attr_a["usage"]


# ══════════════════════════════════════════════════════════════════════════════
# (D) note_parse_outcome(served_by=...) — credit rides the per-call channel
# ══════════════════════════════════════════════════════════════════════════════

async def test_served_by_credits_the_serving_lane_without_a_snapshot():
    home = _OkAdapter("home")
    sub = _OkAdapter("sub")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)])
    _sicken(r, "home")
    _, attr = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert attr["served_by"] == "sub"
    # A LATER call on the same profile clobbers/pops the pending snapshot
    # (the concurrency hazard) — the fallback path would then credit `home`.
    r._pending_cached.pop("home", None)
    before_sub, before_home = _demerits(r, "sub"), _demerits(r, "home")
    r.note_parse_outcome("home", parsed=True, truncated=False,
                         served_by=attr["served_by"])
    assert _demerits(r, "sub") == before_sub + 1     # credited to the server
    assert _demerits(r, "home") == before_home       # not to the pin


async def test_adaptive_off_ignores_served_by_the_76_attribution():
    home = _OkAdapter("home")
    sub = _OkAdapter("sub")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)],
                adaptive=False)
    before_sub, before_home = _demerits(r, "sub"), _demerits(r, "home")
    r.note_parse_outcome("home", parsed=True, truncated=False, served_by="sub")
    assert _demerits(r, "home") == before_home + 1   # the pin, as in #76
    assert _demerits(r, "sub") == before_sub


# ══════════════════════════════════════════════════════════════════════════════
# (E) the agent runtime threads the per-call channel through
# ══════════════════════════════════════════════════════════════════════════════

def _agent_world() -> tuple[AgentState, World]:
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=90.0, starting_credits=10,
        memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agent = AgentState(id="a1", name="Ann", personality="curious",
                       profile="lane", location="plaza", energy=90.0, credits=10)
    return agent, World(params=params, places=places, agents=[agent])


class _AttributedFakeRouter:
    """Duck-typed router WITH the EM-307 channel: returns a bounced
    attribution and records what note_parse_outcome receives."""

    def __init__(self, text: str = '{"action": "idle", "args": {}}'):
        self.text = text
        self.noted: list[dict] = []

    async def chat_attributed(self, profile_name, messages, *,
                              max_tokens, temperature, require_json=False):
        # EM-306 — the agent/animal turn is strict-JSON and must say so.
        assert require_json is True
        return self.text, {
            "routed_via": "routed/sub",
            "usage": {"input_tokens": 7, "output_tokens": 3,
                      "latency_ms": 5.0, "finish_reason": "stop",
                      "cached": False,
                      "bounced_from": profile_name, "bounced_to": "sub"},
            "served_by": "sub",
        }

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        raise AssertionError("chat_attributed must be preferred when offered")

    def note_parse_outcome(self, profile_name, *, parsed, truncated,
                           timed_out=False, served_by=None):
        self.noted.append({"profile": profile_name, "parsed": parsed,
                           "served_by": served_by})

    def last_usage(self, profile_name):    # must NOT be consulted
        raise AssertionError("per-call attribution must replace last_usage")

    def last_routed_via(self, profile_name):
        raise AssertionError("per-call attribution must replace last_routed_via")


class _LegacyFakeRouter:
    """Duck-typed router WITHOUT chat_attributed and with the pre-EM-307
    note_parse_outcome signature — the historical path must still work."""

    def __init__(self, text: str = '{"action": "idle", "args": {}}'):
        self.text = text
        self.noted: list[dict] = []

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        return self.text

    def note_parse_outcome(self, profile_name, *, parsed, truncated,
                           timed_out=False):
        self.noted.append({"profile": profile_name, "parsed": parsed})

    def last_usage(self, profile_name):
        return {"input_tokens": 1, "output_tokens": 1, "latency_ms": 2.0,
                "finish_reason": "stop", "cached": False}

    def last_routed_via(self, profile_name):
        return "routed/legacy"


async def test_agent_runtime_consumes_the_per_call_attribution():
    agent, world = _agent_world()
    router = _AttributedFakeRouter()
    runtime = AgentRuntime(world, router)
    action, err, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, agent)
    assert err is None and action is not None
    assert meta["routed_via"] == "routed/sub"
    assert meta["usage"]["bounced_to"] == "sub"
    assert router.noted == [{"profile": "lane", "parsed": True,
                             "served_by": "sub"}]


async def test_agent_runtime_falls_back_for_legacy_duck_typed_routers():
    agent, world = _agent_world()
    router = _LegacyFakeRouter()
    runtime = AgentRuntime(world, router)
    action, err, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, agent)
    assert err is None and action is not None
    assert meta["routed_via"] == "routed/legacy"        # profile-level reads
    assert router.noted == [{"profile": "lane", "parsed": True}]


_ANIMAL_JSON = '{"animal_thought": "zzz", "action": "nap", "args": {}}'


async def test_animal_runtime_consumes_the_per_call_attribution():
    # Mirror of the agent-runtime test (W30 review gap): animal turns are the
    # canonical concurrent background caller, so they must ride the same
    # per-call channel — meta from the attribution record, served_by into
    # note_parse_outcome, profile-level reads never consulted.
    _agent, world = _agent_world()
    router = _AttributedFakeRouter(_ANIMAL_JSON)
    runtime = AnimalRuntime(world, router)
    action, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, attempt=1)
    assert action is not None and action["action"] == "nap"
    assert meta["routed_via"] == "routed/sub"
    assert meta["usage"]["bounced_to"] == "sub"
    assert router.noted == [{"profile": "lane", "parsed": True,
                             "served_by": "sub"}]


async def test_animal_runtime_falls_back_for_legacy_duck_typed_routers():
    _agent, world = _agent_world()
    router = _LegacyFakeRouter(_ANIMAL_JSON)
    runtime = AnimalRuntime(world, router)
    action, meta = await runtime._call_and_parse(
        "lane", _MESSAGES, 256, 0.8, attempt=1)
    assert action is not None and action["action"] == "nap"
    assert meta["routed_via"] == "routed/legacy"        # profile-level reads
    assert router.noted == [{"profile": "lane", "parsed": True}]


# ══════════════════════════════════════════════════════════════════════════════
# (F) cache HIT of a BOUNCED call — the CURRENT attribution design, pinned
# ══════════════════════════════════════════════════════════════════════════════

async def test_cache_hit_from_a_bounced_call_attributes_served_by_to_the_pin():
    # A bounced MISS stores the substitute's routed_via/usage in the cache.
    # CURRENT design (pinned by the W30 review, not necessarily final): a
    # later HIT is served by the CACHE on the requested profile — served_by is
    # the PIN, even though the cached text was produced by the bounced-to
    # lane. The substitute's truth survives in routed_via; the HIT snapshot
    # drops the bounce keys (tokens null, cached=true). A health credit for a
    # HIT therefore lands on the pin, which never called a provider.
    home = _OkAdapter("home", text="home (never called — sick)")
    sub = _OkAdapter("sub", text="sub served")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)],
                cache_enabled=True)
    _sicken(r, "home")

    text1, attr1 = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text1 == "sub served" and attr1["served_by"] == "sub"

    text2, attr2 = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert sub.calls == 1 and home.calls == 0   # second call: pure cache HIT
    assert text2 == "sub served"
    assert attr2["served_by"] == "home"         # the pin — CURRENT design
    assert attr2["routed_via"] == "routed/sub"  # the substitute's routed truth
    assert attr2["usage"]["cached"] is True
    assert "bounced_to" not in attr2["usage"]   # HIT snapshot drops bounce keys


async def test_attribution_usage_is_isolated_from_snapshot_and_cache():
    # W30 review — attribution["usage"] must be a COPY: a consumer mutating
    # its per-call record must not leak into the staged pending snapshot (the
    # single-caller profile reads) or the decision-cache entry a later HIT is
    # served from.
    home = _OkAdapter("home", text="home (never called — sick)")
    sub = _OkAdapter("sub", text="sub served")
    r = _router([("sub", "m-sub", sub), ("home", "m-home", home)],
                cache_enabled=True)
    _sicken(r, "home")

    _, attr = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert attr["usage"]["bounced_to"] == "sub"
    attr["usage"]["output_tokens"] = 10 ** 9    # consumer mutates its record
    attr["usage"]["poisoned"] = True
    # the pending snapshot (single-caller profile reads) is unharmed…
    assert r.last_usage("home")["output_tokens"] == 5
    assert "poisoned" not in r.last_usage("home")
    # …and so is the cache entry the next HIT is served from
    _, attr_hit = await r.chat_attributed(
        "home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert attr_hit["usage"]["cached"] is True
    assert "poisoned" not in attr_hit["usage"]
    assert attr_hit["routed_via"] == "routed/sub"


# ══════════════════════════════════════════════════════════════════════════════
# (G) the loop's EM-307 branches — narrator + deep-dive consume the channel
# ══════════════════════════════════════════════════════════════════════════════

_CHAPTER = "The town stirred, and the schemes began anew."


class _FakeRepo:
    """Duck-typed repository: no history, records every persisted event."""

    def __init__(self):
        self.saved: list[dict] = []

    def get_events(self, run_id, **kwargs):
        return []

    def save_event(self, run_id, evt, tick):
        self.saved.append(evt)


class _ProseAttrRouter:
    """Offers chat_attributed for prose calls; the profile-level reads RAISE,
    proving the loop's EM-307 branches never consult them."""

    def __init__(self, prose: str = _CHAPTER):
        self.prose = prose
        self.attributed_calls = 0
        self.plain_calls = 0

    def get_profile(self, name):
        return None

    def profile_names(self):
        return []

    async def chat_attributed(self, profile_name, messages, *,
                              max_tokens, temperature, require_json=False):
        self.attributed_calls += 1
        assert require_json is False            # prose turns stay non-strict
        return self.prose, {
            "routed_via": "routed/sub",
            "usage": {"input_tokens": 9, "output_tokens": 9,
                      "latency_ms": 3.0, "finish_reason": "stop",
                      "cached": False,
                      "bounced_from": profile_name, "bounced_to": "sub"},
            "served_by": "sub",
        }

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        # deep-dive DIMENSION passes (analytical notes) use the plain façade
        self.plain_calls += 1
        return "Ada passed the ubi law. Mox schemed in the plaza."

    def last_usage(self, name):
        raise AssertionError("EM-307: the loop must consume the per-call attribution")

    def last_routed_via(self, name):
        raise AssertionError("EM-307: the loop must consume the per-call attribution")


def _tick_loop(router) -> tuple[TickLoop, _FakeRepo]:
    _agent, world = _agent_world()
    repo = _FakeRepo()
    loop = TickLoop(world, runtime=None, repo=repo, router=router,
                    broadcaster=lambda _msg: None, animal_runtime=object())
    return loop, repo


async def test_narrator_consumes_the_per_call_attribution():
    # The narrator swallows every exception and emits NOTHING on failure, so
    # a fallback to the raising profile-level reads shows up as zero events.
    router = _ProseAttrRouter()
    loop, repo = _tick_loop(router)
    await loop._run_narrator(0, 20, "lane")
    assert router.attributed_calls == 1
    assert len(repo.saved) == 1
    evt = repo.saved[0]
    assert evt["kind"] == "narrator_summary"
    assert evt["text"].startswith("The town stirred")
    assert evt["payload"]["routed_via"] == "routed/sub"   # per-call truth


async def test_deepdive_synthesis_consumes_the_per_call_attribution():
    router = _ProseAttrRouter()
    loop, repo = _tick_loop(router)
    await loop._run_deepdive("lane")
    assert router.attributed_calls == 1         # the SYNTHESIS call
    assert router.plain_calls == 3              # one per deep-dive dimension
    assert len(repo.saved) == 1
    evt = repo.saved[0]
    assert evt["kind"] == "narrator_summary"
    assert evt["payload"]["mode"] == "deepdive"
    assert evt["payload"]["routed_via"] == "routed/sub"   # per-call truth

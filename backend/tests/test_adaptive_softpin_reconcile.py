"""
Adaptive Lane Routing — soft-pin / bounce-loop reconciliation (W30, spec §6).

The 2026-07-09 fix: with adaptive_routing.enabled, the #76 soft-pin PRE-CALL
detour to `auto` is disabled and the registry walk OWNS the sick-lane skip. This
file gates the reconciliation:

  (1) adaptive ON + pinned SICK → effective_profile() yields (returns the pinned
      lane), and chat() PRE-EMPTIVELY skips the sick pinned lane (zero calls) and
      serves the top healthy SORTED lane — NOT `auto`, which stays last.
  (2) adaptive OFF + pinned SICK → the legacy #76 detour to `auto` is preserved
      byte-for-byte (effective_profile → ("auto", "detour")).
  (3) Token-clamp (#77): a TRUNCATION-BOOSTED call must not skip every healthy
      small-ceiling free lane — the boosted max_tokens is clamped to the lane's
      ceiling and the lane is ATTEMPTED (a truncation-retry beats an idle
      fallback). Un-boosted genuine requests still skip a too-small lane.
  (4) Every sorted lane rate-limited → `auto` is attempted LAST (no premature
      abort while candidates remain) and the terminal failure surfaces exactly
      as before (the last provider error → EM-173 idle).
  (5) The adaptive-routing config-bake round-trip still holds after the changes.

W30 remediation additions (2026-07-09):

  (6) RESERVED `auto` BACKSTOP — in a production-shaped 9-lane universe the
      curated walk keeps max_attempts-1 attempts and the terminal `auto` entry
      is GUARANTEED the final slot, even when healthy curated lanes outnumber
      the attempt budget (the toy-universe blind spot that let the old code
      pass while `auto` was structurally unreachable in the shipped shape).
  (7) BOUNCE ATTRIBUTION — a bounced call's parse outcome credits the lane
      that ACTUALLY served (bounced_to), not the pin, so a persistently-capped
      pin stays sick instead of flapping healthy; adaptive OFF keeps the exact
      #76 pin attribution (byte-identical guarantee).
  (8) RECOVERY PROBE CADENCE — every probe_every-th pre-skip of a sick pin
      attempts the pin first (bounded probe); a failed probe returns to
      zero-call skipping, a clean probe serves from home and opens the
      window-aging path back.

Style-matches test_adaptive_lane_routing.py: a REAL Router over fake adapters
that count calls / record the max_tokens they saw.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise) — not needed here, but we
import engine.world first defensively per the repo convention.
"""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile, WorldParams,
    _parse_adaptive_routing,
)
from petridish.engine.world import AgentState, PlaceState, World
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

_KEY_ENV = "EM_ADAPTIVE_SOFTPIN_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


# ──────────────────────────────────────────────────────────────────────────────
# Test adapters (mirror test_adaptive_lane_routing.py's fakes)
# ──────────────────────────────────────────────────────────────────────────────

class _OkAdapter:
    def __init__(self, name: str, text: str | None = None,
                 log: list[str] | None = None):
        self.name = name
        self.text = text if text is not None else f"served/{name}"
        self.calls = 0
        self.seen_max_tokens: list[int] = []
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None
        self._log = log

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.seen_max_tokens.append(max_tokens)
        if self._log is not None:
            self._log.append(self.name)
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


class _FailAdapter:
    def __init__(self, name: str, status: int = 429, detail: str = "Too Many Requests",
                 log: list[str] | None = None):
        self.name = name
        self.status = status
        self.detail = detail
        self.calls = 0
        self._log = log
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        if self._log is not None:
            self._log.append(self.name)
        raise ProviderError(self.name, self.status, self.detail)


def _profile(name: str, model_id: str, *, max_tokens: int = 512,
             adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=model_id,
        max_tokens=max_tokens, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _ar(order, *, enabled: bool = True, max_attempts: int = 3,
        allow_paid: bool = False, per_attempt_timeout_s: float = 12.0
        ) -> AdaptiveRoutingParams:
    return AdaptiveRoutingParams(
        enabled=enabled, max_attempts=max_attempts, allow_paid=allow_paid,
        per_attempt_timeout_s=per_attempt_timeout_s, order=tuple(order),
    )


def _router(specs, order, *, auto=None, lane_failover=None, **ar_kwargs) -> Router:
    """specs: list of (name, model_id, adapter_obj, max_tokens)."""
    profiles = [_profile(n, m, max_tokens=mt) for (n, m, _a, mt) in specs]
    overrides = {n: a for (n, _m, a, _mt) in specs}
    if auto is not None:
        profiles.append(_profile("auto", "auto"))
        overrides["auto"] = auto
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=False,
        adaptive_routing=_ar(order, **ar_kwargs), lane_failover=lane_failover,
    )


# ══════════════════════════════════════════════════════════════════════════════
# (1) adaptive ON + pinned sick → top healthy SORTED lane, not auto, home 0 calls
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_adaptive_on_sick_pin_preskips_home_and_serves_top_sorted_lane():
    # `home` would SUCCEED if called (it is an _OkAdapter) — but it is SICK, so
    # the registry walk must pre-emptively skip it with ZERO calls and serve the
    # top healthy sorted lane. `auto` stays the last resort, untouched.
    top = _OkAdapter("top", text="top served")
    home = _OkAdapter("home", text="home served (should never be called)")
    second = _OkAdapter("second", text="second served")
    auto = _OkAdapter("auto", text="auto served")
    r = _router(
        # insertion order sets the glob priority: top(0) → home(1) → second(2)
        [("top", "m-top", top, 512), ("home", "m-home", home, 512),
         ("second", "m-second", second, 512)],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto,
    )
    # Sicken the pinned `home` lane (default threshold 3 error demerits).
    for _ in range(3):
        r.note_lane_error("home")
    assert r.lane_sick("home") is True

    # The soft-pin YIELDS under adaptive routing: effective_profile no longer
    # detours a sick pin to `auto`; it returns the pinned lane unchanged so
    # chat()'s registry walk owns the skip.
    assert r.effective_profile("agent_1", "home") == ("home", None)

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "top served"
    assert home.calls == 0        # pinned sick lane pre-emptively skipped
    assert top.calls == 1         # top of the curated sorting list served
    assert second.calls == 0      # never reached (top served first)
    assert auto.calls == 0        # auto is a LAST resort, not the first stop

    # Attribution surfaces on the REQUESTED profile (EM-198 contract).
    usage = r.last_usage("home")
    assert usage["bounced_from"] == "home" and usage["bounced_to"] == "top"
    assert r.last_routed_via("home") == "routed/top"

    # A pre-skip notes NO fresh demerit — the window keeps the pre-existing 3
    # (the lane was already sick; we didn't invent a 4th error).
    assert r.lane_health()["home"]["errors"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# (2) adaptive OFF + pinned sick → legacy #76 detour to `auto` preserved
# ══════════════════════════════════════════════════════════════════════════════

def test_adaptive_off_sick_pin_keeps_the_legacy_auto_detour():
    home = _OkAdapter("home")
    beta = _OkAdapter("beta")
    auto = _OkAdapter("auto")
    r = _router(
        [("home", "m-home", home, 512), ("beta", "m-beta", beta, 512)],
        [LaneOrderEntry("freellmapi", "*")], enabled=False, auto=auto,
    )
    for _ in range(3):
        r.note_lane_error("home")
    assert r.lane_sick("home") is True

    # adaptive OFF ⇒ the #76 soft-pin detour is byte-identical: a sick pinned
    # lane detours PRE-CALL to the universal `auto` lane.
    assert r.effective_profile("agent_1", "home") == ("auto", "detour")


def test_adaptive_off_via_dataclass_param_still_detours_to_auto():
    # Belt-and-suspenders: an explicit AdaptiveRoutingParams(enabled=False)
    # (not just an absent block) must also keep the legacy detour.
    home = _OkAdapter("home")
    auto = _OkAdapter("auto")
    r = _router(
        [("home", "m-home", home, 512)],
        [LaneOrderEntry("freellmapi", "*")], enabled=False, auto=auto,
    )
    for _ in range(3):
        r.note_lane_error("home")
    assert r.effective_profile("agent_1", "home") == ("auto", "detour")


# ══════════════════════════════════════════════════════════════════════════════
# (3) Boosted max_tokens → clamp-not-skip a healthy small-ceiling lane (#77)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_boosted_call_clamps_to_small_ceiling_lane_instead_of_skipping():
    # `home` truncates (its EM-135 window is flagged), so the runtime hands the
    # bounce a BOOSTED max_tokens (4096) though the home lane's configured
    # ceiling is only 1024. A healthy 1024-ceiling free lane must be ATTEMPTED
    # with the boost CLAMPED to 1024 — never skipped into an idle fallback.
    home = _FailAdapter("home")
    small = _OkAdapter("small", text="small served")   # out_hint 1024
    r = _router(
        [("home", "m-home", home, 1024), ("small", "m-small", small, 1024)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    # Flag `home` as truncation-boosted (a single truncation trips it), NOT sick
    # (truncations are not demerits), so chat() still calls home first and bounces
    # on its fresh failure.
    r.note_parse_outcome("home", parsed=False, truncated=True)
    assert r._lane_boosted("home") is True
    assert r.lane_sick("home") is False

    text = await r.chat("home", _MESSAGES, max_tokens=4096, temperature=0.8)

    assert text == "small served"
    assert small.calls == 1
    # The adapter saw the CLAMPED value (lane ceiling 1024), not the 4096 boost.
    assert small.seen_max_tokens == [1024]


@pytest.mark.asyncio
async def test_unboosted_genuine_large_request_still_skips_a_too_small_lane():
    # The contrast that proves the clamp keys on the BOOST, not on every call:
    # the SAME 4096 max_tokens, but UN-boosted, keeps the #77 skip — a
    # 1024-ceiling lane can't fit the genuine floor, so the 4096-ceiling lane
    # serves instead.
    home = _FailAdapter("home")
    small = _OkAdapter("small", text="small served")   # out_hint 1024
    big = _OkAdapter("big", text="big served")         # out_hint 4096
    r = _router(
        [("home", "m-home", home, 1024), ("small", "m-small", small, 1024),
         ("big", "m-big", big, 4096)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    # home NOT boosted ⇒ 4096 is a genuine floor.
    assert r._lane_boosted("home") is False

    text = await r.chat("home", _MESSAGES, max_tokens=4096, temperature=0.8)

    assert text == "big served"
    assert small.calls == 0        # 1024 < genuine 4096 ⇒ skipped (the #77 skip)
    assert big.calls == 1          # 4096 ceiling fits the genuine request


# ══════════════════════════════════════════════════════════════════════════════
# (3b) Explicit boost signal — the clamp keys on chat(boosted=True), not on
#      inferring boost from the home lane's window (which the W30 bounce
#      attribution redirect can leave CLEAN after a bounced truncation)
# ══════════════════════════════════════════════════════════════════════════════

class _ScriptedAdapter:
    """Returns a scripted sequence of texts (last one repeats). Records the
    max_tokens of every call, like _OkAdapter."""

    def __init__(self, name: str, texts: list[str]):
        self.name = name
        self.texts = list(texts)
        self.calls = 0
        self.seen_max_tokens: list[int] = []
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        self.seen_max_tokens.append(max_tokens)
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return text


# Fails to parse (repair cannot salvage it: no comma to backtrack to) but is
# structurally TRUNCATED — exactly the shape that triggers the runtime's
# _retry_max_tokens length-retry boost. Mirrors test_em281_retry_budget.py.
_UNPARSEABLE_TRUNCATED = 'Let me reason about my options first {"acti'


@pytest.mark.asyncio
async def test_explicit_boost_kwarg_clamps_when_home_window_shows_no_boost():
    """The core defect: the clamp used to key ONLY on _lane_boosted(home).
    A caller that KNOWS it boosted (the runtime's length-retry) must be able
    to say so explicitly — even when the home window shows zero truncations
    (the W30 redirect credits bounced truncations to the SERVING lane, so the
    pin's window stays clean)."""
    home = _FailAdapter("home")
    small = _OkAdapter("small", text="small served")   # out_hint 1024
    r = _router(
        [("home", "m-home", home, 1024), ("small", "m-small", small, 1024)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    # The home window is CLEAN — inference alone would treat 4096 as genuine.
    assert r._lane_boosted("home") is False

    text = await r.chat("home", _MESSAGES, max_tokens=4096, temperature=0.8,
                        boosted=True)

    assert text == "small served"
    assert small.calls == 1                      # attempted, not skipped
    assert small.seen_max_tokens == [1024]       # boost clamped to the ceiling


@pytest.mark.asyncio
async def test_boosted_length_retry_clamps_to_serving_small_lane_end_to_end():
    """The verifier-confirmed mis-attribution, end-to-end through AgentRuntime:
    attempt 1 bounces off the failing pin to a small lane whose reply is
    TRUNCATED; the W30 redirect credits that truncation to the SERVING lane,
    so _lane_boosted(home) stays False. The length-retry then calls with a
    boosted 4096 — pre-fix the bounce read the clean home window, treated
    4096 as a genuine floor, skipped the healthy 1024-ceiling lane that had
    just served, and collapsed to 'all lanes exhausted' → idle churn. With
    the explicit signal the retry is clamped and the small lane serves."""
    from petridish.agents.runtime import AgentRuntime

    home = _FailAdapter("home")
    small = _ScriptedAdapter(
        "small", [_UNPARSEABLE_TRUNCATED, _VALID_ACTION_JSON])
    r = _router(
        [("home", "m-home", home, 1024), ("small", "m-small", small, 1024)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        recharge_cost=2, recharge_amount=20.0, work_reward=4, forage_reward=1,
        steal_max=5, death_after_zero_turns=10, memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="cleo", name="Cleo", personality="curious", profile="home",
        location="plaza", energy=88.0, credits=10,
    )
    world = World(params=params, places=places, agents=[agent])
    runtime = AgentRuntime(world, r)

    await runtime.run_turn(agent)

    # Attempt 1: home fails → bounce serves the truncated reply from `small`;
    # the truncation is credited to the SERVING lane (W30), pin stays clean.
    assert r._lane_boosted("small") is True
    assert r._lane_boosted("home") is False
    # Attempt 2 (the boosted length-retry): home fails again and the bounce
    # must RE-ATTEMPT the healthy small lane with the boost CLAMPED to its
    # 1024 ceiling — not skip it into an idle fallback.
    assert home.calls == 2
    assert small.calls == 2, (
        "the boosted length-retry skipped the healthy small lane "
        f"(small saw {small.calls} call(s)) — the #77 collapse is back")
    assert small.seen_max_tokens == [1024, 1024]


@pytest.mark.asyncio
async def test_default_unboosted_call_keeps_bounce_attribution_byte_identical():
    """No boost anywhere (default boosted=False, clean windows): the genuine-
    floor skip and the single-caller EM-198 attribution events are exactly the
    pre-signal bytes — the new kwarg must be invisible when unused."""
    home = _FailAdapter("home")
    small = _OkAdapter("small")                        # out_hint 1024
    big = _OkAdapter("big", text="big served")         # out_hint 4096
    r = _router(
        [("home", "m-home", home, 1024), ("small", "m-small", small, 1024),
         ("big", "m-big", big, 4096)],
        [LaneOrderEntry("freellmapi", "*")],
    )

    text = await r.chat("home", _MESSAGES, max_tokens=4096, temperature=0.8)

    assert text == "big served"
    assert small.calls == 0        # genuine 4096 floor still skips the #77 lane
    assert big.seen_max_tokens == [4096]
    # Exact attribution snapshot — byte-identical to the pre-kwarg contract.
    assert r.last_usage("home") == {
        "input_tokens": 10, "output_tokens": 5, "latency_ms": 12.0,
        "finish_reason": "stop", "cached": False,
        "bounced_from": "home", "bounced_to": "big",
    }
    assert r.last_routed_via("home") == "routed/big"
    assert r.lane_health()["home"]["window"] == [
        {"parsed": False, "truncated": False, "error": True}]


# ══════════════════════════════════════════════════════════════════════════════
# (4) Every sorted lane rate-limited → auto attempted LAST, terminal fail surfaces
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_all_lanes_rate_limited_tries_auto_last_then_surfaces_terminal():
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    free1 = _FailAdapter("free1", 429, "free1 429", log=call_log)
    free2 = _FailAdapter("free2", 429, "free2 429", log=call_log)
    auto = _FailAdapter("auto", 429, "All models exhausted", log=call_log)
    r = _router(
        [("home", "m-home", home, 512), ("free1", "m-free1", free1, 512),
         ("free2", "m-free2", free2, 512)],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto, max_attempts=3,
    )

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # No premature abort while candidates remained: every sorted lane, then
    # `auto` LAST, each tried exactly once.
    assert call_log == ["home", "free1", "free2", "auto"]
    assert home.calls == 1 and free1.calls == 1 and free2.calls == 1
    assert auto.calls == 1
    # A failing `auto` ("All models exhausted") is an ordinary lane failure; the
    # terminal error surfaces to the runtime's EM-173 idle fallback, as before.
    assert exc_info.value.detail == "All models exhausted"
    # A terminal failure serves nothing ⇒ no bounced attribution is staged.
    assert r.last_usage("home") is None


# ══════════════════════════════════════════════════════════════════════════════
# (5) Config-bake round-trip still holds after the reconciliation changes
# ══════════════════════════════════════════════════════════════════════════════

def test_adaptive_params_config_bake_round_trip_still_holds():
    original = _parse_adaptive_routing({
        "enabled": True, "max_attempts": 3, "per_attempt_timeout_s": 12,
        "allow_paid": False,
        "order": [
            {"source": "freellmapi", "model": "gpt-oss-120b*", "free": True},
            {"source": "freellmapi", "model": "*", "free": True},
            {"source": "freellmapi", "model": "auto"},
        ],
    })
    # The fork/replay seam serializes via asdict and reparses.
    reparsed = _parse_adaptive_routing(asdict(original))
    assert reparsed == original
    assert reparsed.enabled is True

    # And two routers built from the two sides of the round-trip agree on both the
    # master gate and the resolved registry order — the router consumes the baked
    # config identically after the W30 changes.
    ok = _OkAdapter("gpt-oss-120b")
    specs = [("gpt-oss-120b", "gpt-oss-120b", ok, 512)]
    profiles = [_profile(n, m, max_tokens=mt) for (n, m, _a, mt) in specs]
    overrides = {n: a for (n, _m, a, _mt) in specs}
    profiles.append(_profile("auto", "auto"))
    overrides["auto"] = _OkAdapter("auto")

    r_orig = Router(profiles, adapter_overrides=overrides,
                    cache_enabled=False, adaptive_routing=original)
    r_re = Router(profiles, adapter_overrides=dict(overrides),
                  cache_enabled=False, adaptive_routing=reparsed)

    assert r_orig._adaptive_enabled() is True
    assert r_re._adaptive_enabled() is True
    prio_orig = [(l["profile"], l["priority"])
                 for l in r_orig.lane_registry_snapshot()]
    prio_re = [(l["profile"], l["priority"])
               for l in r_re.lane_registry_snapshot()]
    assert prio_orig == prio_re
    # gpt-oss-120b is ranked ahead of the last-resort `auto`.
    assert prio_orig[0][0] == "gpt-oss-120b"
    assert prio_orig[-1][0] == "auto"


# ══════════════════════════════════════════════════════════════════════════════
# (6) W30 finding 1 — the reserved `auto` backstop
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_production_shaped_universe_reserves_final_attempt_for_auto():
    """FINDING 1 regression, PRODUCTION shape: the shipped lanes.yaml resolves
    to 9 lanes (3 named + 5-lane free sweep + auto). In an intermittent rate
    window the top curated lanes 429 while each stays sub-threshold HEALTHY
    (one error < sick_threshold 3), so the pre-W30 walk burned every attempt
    on them and `auto` — the whole-pool router that may still serve — was
    never consulted. The reserved backstop guarantees `auto` the final slot."""
    call_log: list[str] = []
    pin = _FailAdapter("gpt-oss-120b", 429, "gpt-oss 429", log=call_log)
    groq = _FailAdapter("groq-llama", 429, "groq 429", log=call_log)
    qwen = _FailAdapter("qwen-next", 429, "qwen 429", log=call_log)
    sweep = {
        name: _FailAdapter(name, 429, f"{name} 429", log=call_log)
        for name in ("gemini-flash", "deepseek-pro", "cerebras-glm",
                     "mistral-small", "kimi")
    }
    auto = _OkAdapter("auto", text="auto served", log=call_log)
    specs = [
        ("gpt-oss-120b", "gpt-oss-120b", pin, 512),
        ("groq-llama", "llama-3.3-70b-versatile", groq, 512),
        ("qwen-next", "qwen/qwen3-next-80b-a3b-instruct:free", qwen, 512),
        *[(n, f"m-{n}", a, 512) for n, a in sweep.items()],
    ]
    r = _router(
        specs,
        [LaneOrderEntry("freellmapi", "gpt-oss-120b*"),
         LaneOrderEntry("freellmapi", "*llama-3.3-70b*"),
         LaneOrderEntry("freellmapi", "*qwen3-next-80b*"),
         LaneOrderEntry("freellmapi", "*"),
         LaneOrderEntry("freellmapi", "auto")],
        auto=auto, max_attempts=4,   # the shipped W30 config value
    )
    # Sanity: the registry mirrors the shipped 9-lane resolution, `auto` last.
    prio = [l["profile"] for l in r.lane_registry_snapshot()]
    assert len(prio) == 9 and prio[0] == "gpt-oss-120b" and prio[-1] == "auto"

    text = await r.chat("gpt-oss-120b", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "auto served"
    # Home + max_attempts-1 = 3 curated attempts, then the RESERVED final
    # attempt goes to `auto` — not to the next sweep lane.
    assert call_log == [
        "gpt-oss-120b", "groq-llama", "qwen-next", "gemini-flash", "auto"]
    assert auto.calls == 1
    for untouched in ("deepseek-pro", "cerebras-glm", "mistral-small", "kimi"):
        assert sweep[untouched].calls == 0
    # Every 429ing lane took exactly ONE demerit — all still sub-threshold
    # healthy, which is precisely the shape the old walk lost `auto` in.
    assert not any(l["sick"] for l in r.lane_registry_snapshot())
    assert r.last_usage("gpt-oss-120b")["bounced_to"] == "auto"


@pytest.mark.asyncio
async def test_reserved_auto_attempted_when_curated_lanes_outnumber_attempts():
    """Closes the toy-universe blind spot: the sibling
    test_all_lanes_rate_limited_tries_auto_last_then_surfaces_terminal passed
    pre-W30 only because its universe had exactly max_attempts non-home lanes
    before `auto`. With MORE healthy curated lanes than attempts, `auto` must
    still receive the reserved final slot, and its terminal error surfaces."""
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    frees = {
        f"free{i}": _FailAdapter(f"free{i}", 429, f"free{i} 429", log=call_log)
        for i in range(1, 5)
    }
    auto = _FailAdapter("auto", 429, "All models exhausted", log=call_log)
    r = _router(
        [("home", "m-home", home, 512),
         *[(n, f"m-{n}", a, 512) for n, a in frees.items()]],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto, max_attempts=3,
    )

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # Curated walk gets max_attempts-1 = 2 slots; the final slot is `auto`'s.
    assert call_log == ["home", "free1", "free2", "auto"]
    assert frees["free3"].calls == 0 and frees["free4"].calls == 0
    assert exc_info.value.detail == "All models exhausted"


@pytest.mark.asyncio
async def test_sick_auto_forfeits_the_reservation():
    """A health-sick `auto` gives its reserved slot back to the curated walk
    (full max_attempts budget, exactly the pre-W30 semantics)."""
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    frees = {
        f"free{i}": _FailAdapter(f"free{i}", 429, f"free{i} 429", log=call_log)
        for i in range(1, 5)
    }
    auto = _FailAdapter("auto", 429, "All models exhausted", log=call_log)
    r = _router(
        [("home", "m-home", home, 512),
         *[(n, f"m-{n}", a, 512) for n, a in frees.items()]],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto, max_attempts=3,
    )
    for _ in range(3):
        r.note_lane_error("auto")
    assert r.lane_sick("auto") is True

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert call_log == ["home", "free1", "free2", "free3"]
    assert auto.calls == 0
    assert exc_info.value.detail == "free3 429"


# ══════════════════════════════════════════════════════════════════════════════
# (7) W30 finding 2a — bounce attribution credits the SERVING lane
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bounced_parse_outcome_credits_the_serving_lane_not_the_pin():
    """The runtimes report their parse outcome against the REQUESTED profile;
    under adaptive routing the router must re-attribute it to the lane that
    ACTUALLY served (the pending EM-198 snapshot's bounced_to), so bounced
    successes stop aging a capped pin's error demerits out of its window."""
    home = _FailAdapter("home")
    beta = _OkAdapter("beta", text="beta served")
    r = _router([("home", "m-home", home, 512), ("beta", "m-beta", beta, 512)],
                [LaneOrderEntry("freellmapi", "*")])

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "beta served"

    # The runtime's post-parse report lands on `beta`, the lane that served.
    r.note_parse_outcome("home", parsed=True, truncated=False)

    health = r.lane_health()
    assert health["beta"]["window"] == [{"parsed": True, "truncated": False}]
    # The pin keeps ONLY its real error demerit — no clean entry dilutes it.
    assert health["home"]["window"] == [
        {"parsed": False, "truncated": False, "error": True}]


@pytest.mark.asyncio
async def test_bounced_truncation_boosts_the_serving_lane_not_the_pin():
    home = _FailAdapter("home")
    beta = _OkAdapter("beta", text="beta served (cut)")
    r = _router([("home", "m-home", home, 512), ("beta", "m-beta", beta, 512)],
                [LaneOrderEntry("freellmapi", "*")])
    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    r.note_parse_outcome("home", parsed=False, truncated=True)

    assert r._lane_boosted("beta") is True    # the lane that actually cut
    assert r._lane_boosted("home") is False   # the pin never emitted output


@pytest.mark.asyncio
async def test_adaptive_off_keeps_pin_attribution_byte_identical():
    """Byte-identical-when-OFF: the EM-205 auto-backup also stages bounced_to,
    but with adaptive disabled the parse outcome must land on the PIN exactly
    as in #76 — no re-attribution."""
    home, auto = _FailAdapter("home"), _OkAdapter("auto", text="auto served")
    r = _router([("home", "m-home", home, 512)],
                [LaneOrderEntry("freellmapi", "*")], enabled=False, auto=auto)

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    assert r.last_usage("home")["bounced_to"] == "auto"

    r.note_parse_outcome("home", parsed=True, truncated=False)

    health = r.lane_health()
    assert health["home"]["window"] == [
        {"parsed": False, "truncated": False, "error": True},
        {"parsed": True, "truncated": False},
    ]
    assert "auto" not in health


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})


@pytest.mark.asyncio
async def test_capped_pin_stays_sick_across_consecutive_turns_of_bounced_successes():
    """FINDING 2a end-to-end: pre-W30, every bounced SUCCESS appended a clean
    entry to the PIN's window, so a persistently-capped pin flapped healthy
    after ~3 turns and burned a real doomed call roughly every other turn.
    Post-fix the pin's window is untouched by bounced turns: it stays sick and
    receives ZERO calls (probes pushed out of reach via a huge probe_every)."""
    from petridish.agents.runtime import AgentRuntime

    pin_adapter = _OkAdapter("pin", text="pin (must never be called)")
    server = _OkAdapter("server", text=_VALID_ACTION_JSON)
    r = _router(
        [("pin", "m-pin", pin_adapter, 512), ("server", "m-server", server, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        lane_failover={"probe_every": 99},
    )
    for _ in range(3):
        r.note_lane_error("pin")
    assert r.lane_sick("pin") is True

    params = WorldParams(
        energy_decay_per_turn=0.0, starting_energy=88.0, starting_credits=10,
        recharge_cost=2, recharge_amount=20.0, work_reward=4, forage_reward=1,
        steal_max=5, death_after_zero_turns=10, memory_window=5,
    )
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0, kind="social")]
    agent = AgentState(
        id="cleo", name="Cleo", personality="curious", profile="pin",
        location="plaza", energy=88.0, credits=10,
    )
    world = World(params=params, places=places, agents=[agent])
    runtime = AgentRuntime(world, r)

    for _ in range(5):
        await runtime.run_turn(agent)
        assert r.lane_sick("pin") is True    # never flaps healthy mid-storm

    assert pin_adapter.calls == 0            # zero doomed real calls on the pin
    assert server.calls == 5                 # every turn served by the bounce
    # The clean outcomes accumulated on the SERVING lane's window.
    window = r.lane_health()["server"]["window"]
    assert len(window) == 5 and all(o.get("parsed") for o in window)
    # The pin's window still holds ONLY the three seeding error demerits.
    assert r.lane_health()["pin"]["errors"] == 3


# ══════════════════════════════════════════════════════════════════════════════
# (8) W30 finding 2b — sick-pin recovery probe cadence
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_sick_pin_probed_every_probe_every_preskips_then_reskips_on_failure():
    """effective_profile()'s adaptive early-return bypassed the #76 probe_every
    recovery cadence, leaving a recovered pin no principled path back. Every
    probe_every-th pre-skip must attempt the PIN exactly once (a bounded
    recovery probe); a failed probe returns to zero-call skipping."""
    pin = _FailAdapter("pin", 429, "pin still capped")
    server = _OkAdapter("server", text="server served")
    r = _router(
        [("pin", "m-pin", pin, 512), ("server", "m-server", server, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        lane_failover={"probe_every": 3},
    )
    for _ in range(3):
        r.note_lane_error("pin")
    assert r.lane_sick("pin") is True

    pin_calls_after_turn: list[int] = []
    for _ in range(6):
        text = await r.chat("pin", _MESSAGES, max_tokens=256, temperature=0.8)
        assert text == "server served"       # every turn is still served
        pin_calls_after_turn.append(pin.calls)

    # Pre-skips 1-2: ZERO pin calls. Pre-skip 3: ONE probe (fails → bounce
    # serves). 4-5: skipped again. 6: the next probe.
    assert pin_calls_after_turn == [0, 0, 1, 1, 1, 2]
    # Each failed probe recorded exactly ONE fresh demerit on the pin.
    assert r.lane_health()["pin"]["errors"] == 5   # 3 seeded + 2 failed probes


@pytest.mark.asyncio
async def test_successful_probe_serves_from_the_pin_and_opens_recovery():
    """A probe that SUCCEEDS serves the turn from the pinned lane itself; the
    runtime's clean outcomes (credited HOME — nothing was bounced) then age
    the demerits out of the window, and the recovered pin is called directly
    again — the principled path back the early-return had severed."""
    pin = _OkAdapter("pin", text="pin recovered")
    server = _OkAdapter("server", text="server served")
    r = _router(
        [("pin", "m-pin", pin, 512), ("server", "m-server", server, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        lane_failover={"probe_every": 2},
    )
    for _ in range(3):
        r.note_lane_error("pin")
    assert r.lane_sick("pin") is True

    # Pre-skip 1: zero pin calls, the bounce serves.
    text = await r.chat("pin", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "server served" and pin.calls == 0

    # Pre-skip 2 → probe: the pin is attempted FIRST and serves the turn.
    text = await r.chat("pin", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "pin recovered"
    assert pin.calls == 1 and server.calls == 1   # the probe turn never bounced
    # A served probe is attributed HOME: no bounced snapshot is staged.
    assert r.last_routed_via("pin") == "routed/pin"

    # The runtime's clean outcomes credit the PIN (nothing pending), so the
    # 6-wide window ages the three demerits below the threshold.
    for _ in range(4):
        r.note_parse_outcome("pin", parsed=True, truncated=False)
    assert r.lane_sick("pin") is False

    # Recovered: the healthy pin is called directly again, no pre-skip.
    text = await r.chat("pin", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "pin recovered"
    assert pin.calls == 2 and server.calls == 1

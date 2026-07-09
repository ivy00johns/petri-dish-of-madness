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

Style-matches test_adaptive_lane_routing.py: a REAL Router over fake adapters
that count calls / record the max_tokens they saw.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise) — not needed here, but we
import engine.world first defensively per the repo convention.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile, _parse_adaptive_routing,
)
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
    def __init__(self, name: str, text: str | None = None):
        self.name = name
        self.text = text if text is not None else f"served/{name}"
        self.calls = 0
        self.seen_max_tokens: list[int] = []
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.seen_max_tokens.append(max_tokens)
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


def _router(specs, order, *, auto=None, **ar_kwargs) -> Router:
    """specs: list of (name, model_id, adapter_obj, max_tokens)."""
    profiles = [_profile(n, m, max_tokens=mt) for (n, m, _a, mt) in specs]
    overrides = {n: a for (n, _m, a, _mt) in specs}
    if auto is not None:
        profiles.append(_profile("auto", "auto"))
        overrides["auto"] = auto
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=False,
        adaptive_routing=_ar(order, **ar_kwargs),
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

"""
Per-lane rate-limit cooldown (approved spec 2026-07-07 — EM-300 P3).

A pinned lane that 429s is remembered as down until its limit resets; its
agent routes straight to `auto` in the meantime (no doomed pinned POST every
turn), and the pin resumes on expiry (probe-on-expiry is implicit). This file
gates the spec's §5 list with a fake monotonic clock + counting adapters:

  1. 429 on pinned ⇒ NEXT call routes to `auto`, the pinned adapter is NOT
     called while cooling.
  2. Advance the fake clock past the window ⇒ the pin is probed exactly once;
     a success clears the cooldown and the pin resumes.
  3. Repeated 429s ⇒ the window grows 45 → 90 → 180 … capped at 600; strikes
     increment.
  4. `Retry-After` / `X-RateLimit-Reset` parsing in adapters.py ⇒ the parsed
     window wins regardless of strikes.
  5. A non-429 ProviderError ⇒ NO cooldown (the pin is still called next turn).
  6. No `auto` lane ⇒ cooldown is inert (the pinned lane is called every turn).
  7. `profile == auto` ⇒ never self-cools.
  8. Pre-emptive route records NO fresh home error demerit (the opening 429
     already did).
  9. lane_health() / lane_cooldowns() surface the window for observability.

Style-matches test_adaptive_softpin_reconcile.py: a REAL Router over fake
adapters that count calls, with the monotonic clock injected.
"""
from __future__ import annotations

import time

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import ModelProfile
from petridish.providers.adapters import _parse_retry_after
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

_MESSAGES = [{"role": "user", "content": "act"}]
_KEY_ENV = "EM_LANE_COOLDOWN_TEST_KEY"


# ──────────────────────────────────────────────────────────────────────────────
# Fake clock + adapters
# ──────────────────────────────────────────────────────────────────────────────

class _Clock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def advance(self, seconds: float) -> None:
        self.value += seconds

    def __call__(self) -> float:
        return self.value


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


class _RateAdapter:
    def __init__(self, name: str, status: int = 429, detail: str = "Too Many Requests",
                 retry_after: float | None = None):
        self.name = name
        self.status = status
        self.detail = detail
        self.retry_after = retry_after
        self.calls = 0
        self.last_routed_via: str | None = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError(self.name, self.status, self.detail,
                            retry_after=self.retry_after)


def _profile(name: str, model_id: str, *, max_tokens: int = 512,
             adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=model_id,
        max_tokens=max_tokens, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _router(specs, *, auto=None, clock: _Clock | None = None,
            adaptive_enabled: bool = False) -> Router:
    profiles = [_profile(n, m) for (n, m, _a) in specs]
    overrides = {n: a for (n, _m, a) in specs}
    if auto is not None:
        profiles.append(_profile("auto", "auto"))
        overrides["auto"] = auto
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=False,
        adaptive_routing={"enabled": adaptive_enabled},
        clock=clock if clock is not None else _Clock(),
    )


# ──────────────────────────────────────────────────────────────────────────────
# §5.1 — 429 on pinned ⇒ next call routes to auto, pinned NOT called while cooling
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_429_cools_pin_and_next_turn_preskips_to_auto():
    home = _RateAdapter("home", 429, "Too Many Requests")
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    # Turn 1 — the pinned lane 429s: cooldown opens, auto serves the turn.
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    assert home.calls == 1 and auto.calls == 1
    assert "home" in r.lane_cooldowns()
    assert r.lane_cooldowns()["home"]["strikes"] == 1

    # Turn 2 — STILL inside the window: the doomed pinned POST is skipped
    # entirely; auto serves again with zero home calls.
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    assert home.calls == 1       # pre-emptive skip — no second doomed POST
    assert auto.calls == 2
    # The pre-emptive route records NO fresh home demerit (spec §3.5) — the
    # opening 429 already noted the one error.
    assert r.lane_health()["home"]["errors"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# §5.2 — window expiry ⇒ pin probed exactly once; success resumes the pin
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_expiry_probes_pin_once_and_success_clears_cooldown():
    home = _RateAdapter("home", 429, "rate limited")
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 1 and "home" in r.lane_cooldowns()

    # The lane RECOVERS upstream: swap in a healthy adapter before the probe.
    healed = _OkAdapter("home", text="home served again")
    r._adapters["home"] = healed

    # Inside the window → still pre-emptive.
    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert healed.calls == 0

    # Past the window → the pin is probed exactly once (no separate probe
    # counter); the success clears the cooldown and resumes the pin.
    clock.advance(46)
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "home served again"
    assert healed.calls == 1
    assert r.lane_cooldowns() == {}          # recovered — window gone
    assert "cooldown" not in r.lane_health().get("home", {})


# ──────────────────────────────────────────────────────────────────────────────
# §5.3 — repeated 429s ⇒ window grows 45 → 90 → 180 … capped at 600
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_repeated_429s_grow_backoff_capped_at_600():
    home = _RateAdapter("home", 429, "quota exhausted")
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    # Strike 1 (initial 429): window 45.
    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 1
    assert r.lane_cooldowns()["home"]["expires_in_s"] == 45.0
    # Strikes 2..5: each probe (after the window passes) re-cools with a
    # doubled backoff: 90 → 180 → 360 → capped 600. Read the window BEFORE
    # advancing past it again (lane_cooldowns() lazily-expires on read).
    for expected in (90.0, 180.0, 360.0, 600.0):
        clock.advance(601)  # always past the previous (capped) window
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
        assert r.lane_cooldowns()["home"]["expires_in_s"] == expected
    assert r.lane_cooldowns()["home"]["strikes"] == 5


# ──────────────────────────────────────────────────────────────────────────────
# §5.4 — Retry-After / X-RateLimit-Reset parsing (adapters.py)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retry_after_header_wins_over_backoff():
    home = _RateAdapter("home", 429, "Too Many Requests", retry_after=12.0)
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.lane_cooldowns()["home"]["expires_in_s"] == 12.0
    assert r.lane_cooldowns()["home"]["strikes"] == 1


@pytest.mark.asyncio
async def test_retry_after_clamped_to_cap():
    # An absurd upstream Retry-After (bogus header, far-future date, or a
    # clock-skewed value) must never cripple a lane past the 600s cap the
    # exponential fallback itself respects.
    home = _RateAdapter("home", 429, "Too Many Requests", retry_after=999999.0)
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.lane_cooldowns()["home"]["expires_in_s"] == 600.0


def test_parse_retry_after_shapes():
    import httpx
    # Integer seconds.
    assert _parse_retry_after(httpx.Headers({"Retry-After": "12"})) == 12.0
    # HTTP-date in the future → seconds-from-now.
    future = time.time() + 90
    rfc = email_utils_format(future)
    parsed = _parse_retry_after(httpx.Headers({"Retry-After": rfc}))
    assert parsed is not None and 85.0 <= parsed <= 90.0
    # Epoch reset stamp (huge value) → remaining seconds.
    stamp = str(time.time() + 60)
    parsed = _parse_retry_after(httpx.Headers({"X-RateLimit-Reset": stamp}))
    assert parsed is not None and 55.0 <= parsed <= 60.0
    # Seconds-remaining (small value).
    assert _parse_retry_after(httpx.Headers({"X-RateLimit-Reset": "37"})) == 37.0
    # Garbage → None (defensive; backoff covers it).
    assert _parse_retry_after(httpx.Headers({"Retry-After": "soon"})) is None
    assert _parse_retry_after(httpx.Headers({})) is None


def email_utils_format(epoch: float) -> str:
    from datetime import datetime, timezone
    from email.utils import format_datetime
    return format_datetime(datetime.fromtimestamp(epoch, tz=timezone.utc))


# ──────────────────────────────────────────────────────────────────────────────
# §5.6 — a non-429 error sets NO cooldown
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_non_rate_limit_sets_no_cooldown():
    home = _RateAdapter("home", 500, "Internal Server Error")
    auto = _OkAdapter("auto", text="auto served")
    clock = _Clock()
    r = _router([("home", "m-home", home)], auto=auto, clock=clock)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.lane_cooldowns() == {}     # 5xx is transient — no cooldown
    # Next turn still calls the pinned lane directly (no pre-emptive skip).
    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 2


# ──────────────────────────────────────────────────────────────────────────────
# §5.7 — no `auto` lane ⇒ cooldown inert (pin called every turn)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cooldown_inert_without_auto_lane():
    home = _RateAdapter("home", 429, "Too Many Requests")
    clock = _Clock()
    r = _router([("home", "m-home", home)], clock=clock)   # no auto profile

    for _ in range(2):
        with pytest.raises(ProviderError):
            await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    # No auto lane ⇒ no pre-emptive hop possible: the pinned lane is called
    # every turn exactly as before the cooldown existed.
    assert home.calls == 2


# ──────────────────────────────────────────────────────────────────────────────
# §5.8 — `auto` itself never self-cools
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_auto_never_self_cools():
    auto = _RateAdapter("auto", 429, "All models exhausted")
    clock = _Clock()
    r = _router([("home", "m-home", _OkAdapter("home"))], auto=auto, clock=clock)

    for _ in range(2):
        with pytest.raises(ProviderError):
            await r.chat("auto", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.lane_cooldowns() == {}     # the terminal lane never cools itself
    assert auto.calls == 2

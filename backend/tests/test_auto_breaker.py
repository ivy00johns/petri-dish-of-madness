"""
EM-226 — auto-backup circuit breaker (storm fast-fail).

During a rate-limit STORM the proxy's own `auto` router returns "All models
exhausted" (or times out): there is no healthy upstream left to bounce to.
Re-issuing the EM-205 backup every turn then DOUBLES the doomed POST volume
(home + auto, both failing) and keeps the upstream rate windows pinned, slowing
their refill. The breaker trips on ANY `auto` failure (the auto lane IS the
whole-pool health router — if IT can't serve, nothing can) and FAST-FAILS the
next would-be-backups: the home error propagates straight to the runtime's
EM-173 idle fallback with NO 2nd network call. Recovery is COUNTER-based (no
clock reads, like EM-177): every Nth skipped backup PROBES the auto lane once;
a probe success closes the breaker and normal per-turn backup resumes.

  (A) Trip + fast-fail — after auto fails once the next would-be-backups skip
                         the auto POST entirely (home still attempted each turn).
  (B) Probe cadence    — every Nth skip probes auto once (the only auto POSTs
                         during a sustained storm).
  (C) Recovery         — a probe that SUCCEEDS closes the breaker; normal
                         per-turn backup resumes immediately.
  (D) Reset on world   — clear_cache() closes the breaker (no cross-run carry).
  (E) Healthy/opt-out  — breaker never trips with a healthy pool or no auto lane.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import ModelProfile
from petridish.providers.base import ProviderError
from petridish.providers.router import Router, _AUTO_BREAKER_PROBE_EVERY

pytestmark = pytest.mark.asyncio

_KEY_ENV = "EM_AUTO_BREAKER_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]
_EXHAUSTED = "All models exhausted. Add more API keys or wait for rate limits to reset."


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


def _profile(name: str, *, adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=f"model/{name}",
        max_tokens=512, temperature=0.8,
        base_url="http://localhost:9",
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


class _OkAdapter:
    def __init__(self, name: str, text: str = '{"action": "idle"}'):
        self.name = name
        self.text = text
        self.calls = 0
        self.last_routed_via = f"served/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


class _FailAdapter:
    def __init__(self, name: str, status: int = 429, detail: str = "Too Many Requests"):
        self.name = name
        self.status = status
        self.detail = detail
        self.calls = 0
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise ProviderError(self.name, self.status, self.detail)


class _FlakyAuto:
    """Auto lane that fails its first `fail_first` calls (storm), then serves —
    models the pool recovering between recovery probes."""

    def __init__(self, name: str, *, fail_first: int, text: str = "auto served",
                 status: int = 429):
        self.name = name
        self.fail_first = fail_first
        self.text = text
        self.status = status
        self.calls = 0
        self.last_routed_via = f"served/{name}"
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        if self.calls <= self.fail_first:
            raise ProviderError(self.name, self.status, _EXHAUSTED)
        self.last_usage = {
            "input_tokens": 4, "output_tokens": 2,
            "latency_ms": 5.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


def _router(adapters: dict[str, object], *, auto: object | None = None,
            cache_enabled: bool = False, with_mock: bool = True,
            probe_every: int = 3) -> Router:
    profiles = [_profile(name) for name in adapters]
    overrides = dict(adapters)
    if auto is not None:
        profiles.append(_profile("auto"))
        overrides["auto"] = auto
    if with_mock:
        profiles.append(_profile("mock", adapter="mock"))
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=cache_enabled,
        auto_breaker_probe_every=probe_every,
    )


# ──────────────────────────────────────────────────────────────────────────────
# (A) trip + fast-fail — the storm-amplifier (doomed 2nd call) is suppressed
# ──────────────────────────────────────────────────────────────────────────────

async def test_breaker_trips_and_fast_fails_subsequent_backups():
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto, probe_every=3)

    # Turn 1 — discovers the pool is dry: home + auto both POST, then raise.
    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 1 and auto.calls == 1
    assert r.auto_backup_health()["open"] is True

    # Turns 2 & 3 — breaker OPEN, below the probe cadence: home still POSTs,
    # auto does NOT (fast-fail — no doomed 2nd call feeding the storm).
    for _ in range(2):
        with pytest.raises(ProviderError):
            await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 3   # home attempted every turn
    assert auto.calls == 1   # auto NOT re-hit while fast-failing


# ──────────────────────────────────────────────────────────────────────────────
# (B) probe cadence — only every Nth skip POSTs to auto during a sustained storm
# ──────────────────────────────────────────────────────────────────────────────

async def test_every_nth_skip_probes_the_auto_lane():
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto, probe_every=3)

    # cadence (probe when skips % 3 == 0): 1=trip(call), 2=skip, 3=skip,
    # 4=probe(call), 5=skip, 6=skip, 7=probe(call).
    for _ in range(7):
        with pytest.raises(ProviderError):
            await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 7   # home attempted every turn (idle fallback per turn)
    assert auto.calls == 3   # trip + two recovery probes — not 7 doomed POSTs


# ──────────────────────────────────────────────────────────────────────────────
# (C) recovery — a successful probe closes the breaker; normal backup resumes
# ──────────────────────────────────────────────────────────────────────────────

async def test_probe_success_closes_breaker_and_resumes_backup():
    home = _FailAdapter("home", 429)
    auto = _FlakyAuto("auto", fail_first=1)  # call#1 fails (trip), call#2+ serves
    r = _router({"home": home}, auto=auto, probe_every=3)

    # Turn 1 trips the breaker (auto call#1 fails).
    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is True

    # Turns 2,3 skip; turn 4 PROBES — auto call#2 now SERVES → breaker closes.
    text = None
    for _ in range(3):
        try:
            text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
        except ProviderError:
            text = None
    assert text == "auto served"                    # the probe turn served
    assert r.auto_backup_health()["open"] is False
    assert auto.calls == 2                           # trip + the successful probe

    # Next failing turn: breaker CLOSED → auto is hit immediately (no skip).
    text2 = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text2 == "auto served"
    assert auto.calls == 3


# ──────────────────────────────────────────────────────────────────────────────
# (D) world reset closes the breaker — no storm state carries into a new run
# ──────────────────────────────────────────────────────────────────────────────

async def test_clear_cache_closes_the_breaker():
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto, probe_every=3)

    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is True

    r.clear_cache()
    assert r.auto_backup_health()["open"] is False
    assert r.auto_backup_health()["skips"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# (E) healthy pool / opt-out — the breaker never trips
# ──────────────────────────────────────────────────────────────────────────────

async def test_healthy_pool_never_trips_the_breaker():
    home = _FailAdapter("home", 429)
    auto = _OkAdapter("auto", text="auto served")
    r = _router({"home": home}, auto=auto, probe_every=3)

    for _ in range(4):
        text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
        assert text == "auto served"
    assert r.auto_backup_health()["open"] is False
    assert auto.calls == 4   # every turn served by auto, no fast-fail


async def test_no_auto_lane_breaker_stays_closed():
    home = _FailAdapter("home", 429)
    r = _router({"home": home}, auto=None, probe_every=3)

    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is False


async def test_default_probe_every_is_sane():
    # The shipped cadence must probe periodically (recovery) without re-hammering
    # the pool every turn (the whole point of the breaker). async only to inherit
    # the module's asyncio mark cleanly — no awaiting needed.
    assert _AUTO_BREAKER_PROBE_EVERY >= 2

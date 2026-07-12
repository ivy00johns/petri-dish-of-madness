"""
EM-226 auto-backup breaker — BLIND-SKIP RESCINDED 2026-07-06.

Originally the breaker fast-failed the EM-205 auto-backup while "open" to avoid
doubling POSTs during a whole-pool storm. In practice that MUTED agents to an
idle fallback even though the `auto` lane was usually still serving, and it
silently killed the EM-177 lane-failover recovery probe (which re-hits a dead
pinned lane every Nth turn) — violating the project rule "never mute an agent,
always bounce to `auto`". The blind-skip is gone: the backup now ALWAYS fires.
The open/closed state is retained as observability only (auto_backup_health).

  (A) Storm          — auto also failing ⇒ the backup is STILL attempted every
                       turn (the accepted doomed-2nd-POST tradeoff), state open.
  (B) No cadence     — probe_every no longer throttles anything; auto is hit on
                       every failing turn.
  (C) State clears   — open flips to closed the instant auto serves again.
  (D) Reset on world — clear_cache() clears the state (no cross-run carry).
  (E) Healthy/opt-out— state never opens with a healthy pool or no auto lane.
  (F) Never mutes    — a tripped breaker still serves the very next turn.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import ModelProfile
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

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
            cache_enabled: bool = False, with_mock: bool = True) -> Router:
    profiles = [_profile(name) for name in adapters]
    overrides = dict(adapters)
    if auto is not None:
        profiles.append(_profile("auto"))
        overrides["auto"] = auto
    if with_mock:
        profiles.append(_profile("mock", adapter="mock"))
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=cache_enabled,
    )


# ──────────────────────────────────────────────────────────────────────────────
# (A) trip + fast-fail — the storm-amplifier (doomed 2nd call) is suppressed
# ──────────────────────────────────────────────────────────────────────────────

async def test_storm_still_attempts_the_backup_every_turn():
    # Genuine whole-pool storm (auto ALSO failing). We now accept the doomed 2nd
    # POST every turn rather than mute the agent — the breaker no longer skips.
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto)

    for _ in range(3):
        with pytest.raises(ProviderError):
            await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 3
    assert auto.calls == 3   # auto attempted EVERY turn (was 1 under the blind-skip)
    assert r.auto_backup_health()["open"] is True   # state still tracks the storm


# ──────────────────────────────────────────────────────────────────────────────
# (B) no probe cadence — auto is POSTed on every failing turn (skip rescinded)
# ──────────────────────────────────────────────────────────────────────────────

async def test_no_skip_cadence_auto_is_hit_on_every_failing_turn():
    # The probe cadence that used to gate the skip is gone: a small probe_every
    # must NOT throttle the backup. All 7 failing turns POST to auto.
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto)

    for _ in range(7):
        with pytest.raises(ProviderError):
            await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert home.calls == 7
    assert auto.calls == 7   # every turn (was 3 under the probe cadence)


# ──────────────────────────────────────────────────────────────────────────────
# (C) recovery — a successful probe closes the breaker; normal backup resumes
# ──────────────────────────────────────────────────────────────────────────────

async def test_open_state_clears_the_moment_auto_serves_again():
    # Observability tracking still works: the breaker "opens" on an auto failure
    # and "closes" the instant auto serves — but nothing is ever skipped between.
    home = _FailAdapter("home", 429)
    auto = _FlakyAuto("auto", fail_first=1)  # call#1 fails (opens), call#2+ serves
    r = _router({"home": home}, auto=auto)

    with pytest.raises(ProviderError):   # turn 1: auto#1 fails → opens
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is True

    # turn 2: auto#2 serves immediately (no skip) → state closes.
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    assert r.auto_backup_health()["open"] is False
    assert auto.calls == 2


# ──────────────────────────────────────────────────────────────────────────────
# (D) world reset closes the breaker — no storm state carries into a new run
# ──────────────────────────────────────────────────────────────────────────────

async def test_clear_cache_closes_the_breaker():
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 429, _EXHAUSTED)
    r = _router({"home": home}, auto=auto)

    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is True

    r.clear_cache()
    assert r.auto_backup_health() == {"open": False}


# ──────────────────────────────────────────────────────────────────────────────
# (E) healthy pool / opt-out — the breaker never trips
# ──────────────────────────────────────────────────────────────────────────────

async def test_healthy_pool_never_trips_the_breaker():
    home = _FailAdapter("home", 429)
    auto = _OkAdapter("auto", text="auto served")
    r = _router({"home": home}, auto=auto)

    for _ in range(4):
        text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
        assert text == "auto served"
    assert r.auto_backup_health()["open"] is False
    assert auto.calls == 4   # every turn served by auto, no fast-fail


async def test_no_auto_lane_breaker_stays_closed():
    home = _FailAdapter("home", 429)
    r = _router({"home": home}, auto=None)

    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert r.auto_backup_health()["open"] is False


async def test_vestigial_fast_fail_state_is_gone():
    # EM-304 — the rescinded fast-fail design's state is fully removed: the
    # health snapshot carries ONLY the open/closed observability bit, and the
    # old constructor cadence knob no longer exists. async only to inherit the
    # module's asyncio mark cleanly — no awaiting needed.
    home = _FailAdapter("home", 429)
    r = _router({"home": home}, auto=None)
    assert r.auto_backup_health() == {"open": False}
    with pytest.raises(TypeError):
        Router([], auto_breaker_probe_every=3)


# ──────────────────────────────────────────────────────────────────────────────
# (F) 2026-07-06 — the blind-skip is RESCINDED: never mute an agent to save a
#     call. Even with the breaker "open" from a prior auto failure, the backup
#     MUST still fire — a recovery probe hitting a dead pinned lane was being
#     muted to an idle fallback while the auto lane was actually serving.
# ──────────────────────────────────────────────────────────────────────────────

async def test_tripped_breaker_still_fires_the_backup_never_mutes():
    home = _FailAdapter("home", 429)
    auto = _FlakyAuto("auto", fail_first=1)  # call#1 fails (opens), call#2+ serves
    r = _router({"home": home}, auto=auto)

    # Turn 1: home + auto both fail → the breaker "opens".
    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert auto.calls == 1

    # Turn 2: breaker OPEN — but the backup fires IMMEDIATELY (no skip), and auto
    # now serves. Under the old blind-skip this turn was fast-failed to idle.
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    assert auto.calls == 2   # hit on the very next turn, not skipped

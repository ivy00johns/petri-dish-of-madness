"""
EM-205 — auto-backup routing (2026-06-15 decision; supersedes the EM-198 fan-out).

A provider error (429 / 5xx / transport failure / malformed completion) on an
agent's PINNED lane retries the SAME call exactly ONCE on the proxy's `auto`
router model — FreeLLMAPI then health-routes it across its whole upstream pool
in a single request. This replaces the EM-198 multi-lane fan-out, which
*amplified* a rate-limit storm (one failure → up to ~6 POSTs across pinned
lanes, each itself possibly throttled). The home lane keeps its identity for the
model-vs-model experiment; only the backup is delegated to the proxy router.

  (A) Backup       — pinned lane raises ⇒ the `auto` lane serves the SAME call
                     ONCE; the requested profile's last_usage/last_routed_via
                     report auto's truth with additive bounced_from/bounced_to.
  (B) No fan-out   — other PINNED lanes are NEVER tried; only `auto` is backup.
  (C) Demerit      — the error is recorded in the home lane's EM-135 window.
  (D) Exhaustion   — auto ALSO failing re-raises (runtime EM-173 idle = last resort).
  (E) Opt-out      — no `auto` profile ⇒ the original error propagates unbounced.
  (F) No recursion — a failing `auto` call (e.g. the narrator on auto) raises,
                     never bounces to itself, never targets mock.
  (G) Healthy path — no error ⇒ one call, no bounced_* keys anywhere.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import pytest

from petridish.config.loader import ModelProfile
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

pytestmark = pytest.mark.asyncio

_KEY_ENV = "EM_AUTO_BACKUP_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


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


def _router(adapters: dict[str, object], *, auto: object | None = None,
            cache_enabled: bool = False, with_mock: bool = True) -> Router:
    """Build a Router over the given PINNED adapters. `auto` (when not None) adds
    the `auto` backup lane with that adapter override; omitting it models a
    deployment with no proxy router available (the opt-out path)."""
    profiles = [_profile(name) for name in adapters]
    overrides = dict(adapters)
    if auto is not None:
        profiles.append(_profile("auto"))
        overrides["auto"] = auto
    if with_mock:
        profiles.append(_profile("mock", adapter="mock"))
    return Router(profiles, adapter_overrides=overrides, cache_enabled=cache_enabled)


# ──────────────────────────────────────────────────────────────────────────────
# (A) backup serves + attribution
# ──────────────────────────────────────────────────────────────────────────────

async def test_pinned_error_bounces_to_auto_and_serves_the_call():
    home, auto = _FailAdapter("home"), _OkAdapter("auto", text="auto served")
    r = _router({"home": home}, auto=auto)

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "auto served"
    assert home.calls == 1
    assert auto.calls == 1


async def test_bounced_call_reports_auto_truth_on_requested_profile():
    home, auto = _FailAdapter("home"), _OkAdapter("auto")
    r = _router({"home": home}, auto=auto)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # The runtime reads last_usage/last_routed_via for the profile it CALLED —
    # those must reflect the auto lane that actually served, flagged additively.
    usage = r.last_usage("home")
    assert usage["bounced_from"] == "home"
    assert usage["bounced_to"] == "auto"
    assert usage["output_tokens"] == 5
    assert r.last_routed_via("home") == "served/auto"


# ──────────────────────────────────────────────────────────────────────────────
# (B) NO fan-out across pinned lanes — the EM-198 amplifier is gone
# ──────────────────────────────────────────────────────────────────────────────

async def test_other_pinned_lanes_are_never_tried_only_auto():
    home, beta = _FailAdapter("home"), _OkAdapter("beta")  # beta = another pinned lane
    auto = _OkAdapter("auto", text="auto served")
    r = _router({"home": home, "beta": beta}, auto=auto)

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "auto served"
    assert home.calls == 1 and auto.calls == 1
    assert beta.calls == 0  # never fanned out to other pinned models


# ──────────────────────────────────────────────────────────────────────────────
# (C) Demerit recorded for observability
# ──────────────────────────────────────────────────────────────────────────────

async def test_error_records_demerit_on_home_lane_window():
    home, auto = _FailAdapter("home"), _OkAdapter("auto")
    r = _router({"home": home}, auto=auto)

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    health = r.lane_health()["home"]
    assert health["errors"] == 1
    assert health["window"][-1]["error"] is True


# ──────────────────────────────────────────────────────────────────────────────
# (D) Exhaustion — auto also failing re-raises (runtime idle stays last resort)
# ──────────────────────────────────────────────────────────────────────────────

async def test_auto_also_failing_reraises_its_error():
    home = _FailAdapter("home", 429)
    auto = _FailAdapter("auto", 502, "bad gateway")
    r = _router({"home": home}, auto=auto)

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert exc_info.value.status == 502  # the auto failure surfaces, not home's
    assert home.calls == 1 and auto.calls == 1


# ──────────────────────────────────────────────────────────────────────────────
# (E) Opt-out — no `auto` profile ⇒ original error propagates, no fan-out
# ──────────────────────────────────────────────────────────────────────────────

async def test_no_auto_profile_propagates_original_error_unbounced():
    home, beta = _FailAdapter("home", 429), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta}, auto=None)  # no proxy router lane

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert exc_info.value.status == 429
    assert beta.calls == 0  # the mock is never a backup either


# ──────────────────────────────────────────────────────────────────────────────
# (F) No recursion — a failing `auto` call raises, never bounces to itself
# ──────────────────────────────────────────────────────────────────────────────

async def test_auto_lane_failure_does_not_recurse():
    auto = _FailAdapter("auto", 429)
    r = _router({}, auto=auto)  # only auto + mock

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("auto", _MESSAGES, max_tokens=256, temperature=0.8)

    assert exc_info.value.status == 429
    assert auto.calls == 1  # called once as the home lane, no self-bounce


# ──────────────────────────────────────────────────────────────────────────────
# (G) Healthy path byte-identical
# ──────────────────────────────────────────────────────────────────────────────

async def test_healthy_call_is_unchanged_no_bounce_keys_anywhere():
    home, auto = _OkAdapter("home"), _OkAdapter("auto")
    r = _router({"home": home}, auto=auto)

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == home.text
    assert home.calls == 1 and auto.calls == 0
    usage = r.last_usage("home")
    assert "bounced_from" not in usage and "bounced_to" not in usage
    assert r.last_routed_via("home") == "served/home"
    assert r.lane_health() == {}  # no demerits recorded on a clean call


async def test_bounced_result_is_cached_with_auto_attribution():
    home, auto = _FailAdapter("home"), _OkAdapter("auto", text="cached-auto")
    r = _router({"home": home}, auto=auto, cache_enabled=True)

    first = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    second = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert first == second == "cached-auto"
    assert home.calls == 1 and auto.calls == 1  # second served from cache
    assert r.last_usage("home")["cached"] is True

"""
EM-198 — error-bounce routing (2026-06-12 user mandate).

A provider error (429 / 5xx / transport failure / malformed completion) must
BOUNCE the same call to the healthiest other lane instead of idling the turn.
The pre-existing EM-173 "provider errors idle on purpose" rule was a
budget-era decision: with ~16 free provider lanes the right response to a
rate limit is a different model, not silence. This file gates:

  (A) chat() bounce — home lane raises ⇒ the healthiest substitute serves the
      SAME call; the requested profile's last_usage/last_routed_via report the
      substitute's truth with additive bounced_from/bounced_to keys.
  (B) Demerits — every adapter-level error records an `error` entry in the
      EM-135 window; lane_sick() counts errors alongside timeouts, so chronic
      429ers get pre-emptively detoured by effective_profile on FUTURE calls.
  (C) Exhaustion — every candidate failing re-raises the LAST ProviderError
      (the runtime's EM-173 idle stays the true last resort); mock is never a
      bounce target.
  (D) Opt-out — lane_failover.enabled: false ⇒ no bounce, the original error
      propagates exactly as pre-EM-198.
  (E) Healthy path byte-identical — no error ⇒ one adapter call, no bounced_*
      keys anywhere.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import pytest

from petridish.config.loader import ModelProfile
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

pytestmark = pytest.mark.asyncio

_KEY_ENV = "EM_ERROR_BOUNCE_TEST_KEY"
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


def _router(adapters: dict[str, object], *, lane_failover=None,
            cache_enabled: bool = False, with_mock: bool = True) -> Router:
    profiles = [_profile(name) for name in adapters]
    if with_mock:
        profiles.append(_profile("mock", adapter="mock"))
    return Router(
        profiles, adapter_overrides=dict(adapters),
        cache_enabled=cache_enabled, lane_failover=lane_failover,
    )


# ──────────────────────────────────────────────────────────────────────────────
# (A) chat() bounce
# ──────────────────────────────────────────────────────────────────────────────

async def test_429_bounces_to_a_healthy_lane_and_serves_the_call():
    home, beta = _FailAdapter("home"), _OkAdapter("beta", text="bounced!")
    r = _router({"home": home, "beta": beta})

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "bounced!"
    assert home.calls == 1
    assert beta.calls == 1


async def test_bounced_call_reports_substitute_truth_on_requested_profile():
    home, beta = _FailAdapter("home"), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta})

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # The runtime reads last_usage/last_routed_via for the profile it CALLED —
    # those must reflect the lane that actually served, flagged additively.
    usage = r.last_usage("home")
    assert usage["bounced_from"] == "home"
    assert usage["bounced_to"] == "beta"
    assert usage["output_tokens"] == 5
    assert r.last_routed_via("home") == "served/beta"


async def test_bounce_skips_already_failed_lanes_and_tries_the_next():
    home, beta, gamma = (
        _FailAdapter("home"), _FailAdapter("beta"), _OkAdapter("gamma"),
    )
    r = _router({"home": home, "beta": beta, "gamma": gamma})

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == gamma.text
    assert home.calls == 1 and beta.calls == 1 and gamma.calls == 1


# ──────────────────────────────────────────────────────────────────────────────
# (B) Demerits and sickness
# ──────────────────────────────────────────────────────────────────────────────

async def test_provider_errors_record_error_demerits_in_the_lane_window():
    home, beta = _FailAdapter("home"), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta})

    await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    health = r.lane_health()["home"]
    assert health["errors"] == 1
    assert health["window"][-1]["error"] is True


async def test_three_errors_make_a_lane_sick_and_future_calls_detour():
    home, beta = _FailAdapter("home"), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta})

    for _ in range(3):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert r.lane_sick("home") is True
    # effective_profile now pre-emptively detours the NEXT call's lane choice.
    effective, reason = r.effective_profile("agent_x", "home")
    assert effective == "beta"
    assert reason == "detour"


async def test_errors_and_timeouts_compose_toward_sickness():
    r = _router({"home": _FailAdapter("home"), "beta": _OkAdapter("beta")})
    r.note_parse_outcome("home", parsed=False, truncated=False, timed_out=True)
    r.note_parse_outcome("home", parsed=False, truncated=False, timed_out=True)
    assert r.lane_sick("home") is False
    r.note_lane_error("home")  # 2 timeouts + 1 error = 3 demerits
    assert r.lane_sick("home") is True


async def test_plain_parse_failures_still_do_not_count_toward_sickness():
    r = _router({"home": _OkAdapter("home")})
    for _ in range(6):
        r.note_parse_outcome("home", parsed=False, truncated=False)
    assert r.lane_sick("home") is False


# ──────────────────────────────────────────────────────────────────────────────
# (C) Exhaustion and the mock rule
# ──────────────────────────────────────────────────────────────────────────────

async def test_all_lanes_failing_reraises_the_last_provider_error():
    home, beta = _FailAdapter("home", 429), _FailAdapter("beta", 502, "bad gateway")
    r = _router({"home": home, "beta": beta})

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert exc_info.value.status == 502  # the LAST failure, not the first
    assert home.calls == 1 and beta.calls == 1


async def test_mock_is_never_a_bounce_target():
    home = _FailAdapter("home")
    r = _router({"home": home})  # only home + the mock profile

    with pytest.raises(ProviderError):
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)


# ──────────────────────────────────────────────────────────────────────────────
# (D) Opt-out
# ──────────────────────────────────────────────────────────────────────────────

async def test_failover_disabled_propagates_the_original_error_unbounced():
    home, beta = _FailAdapter("home"), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta},
                lane_failover={"enabled": False})

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert exc_info.value.status == 429
    assert beta.calls == 0


# ──────────────────────────────────────────────────────────────────────────────
# (E) Healthy path byte-identical
# ──────────────────────────────────────────────────────────────────────────────

async def test_healthy_call_is_unchanged_no_bounce_keys_anywhere():
    home, beta = _OkAdapter("home"), _OkAdapter("beta")
    r = _router({"home": home, "beta": beta})

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == home.text
    assert home.calls == 1 and beta.calls == 0
    usage = r.last_usage("home")
    assert "bounced_from" not in usage and "bounced_to" not in usage
    assert r.last_routed_via("home") == "served/home"
    assert r.lane_health() == {}  # no demerits recorded on a clean call


async def test_bounced_result_is_cached_with_substitute_attribution():
    home, beta = _FailAdapter("home"), _OkAdapter("beta", text="cached-bounce")
    r = _router({"home": home, "beta": beta}, cache_enabled=True)

    first = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    second = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert first == second == "cached-bounce"
    assert home.calls == 1 and beta.calls == 1  # second served from cache
    assert r.last_usage("home")["cached"] is True

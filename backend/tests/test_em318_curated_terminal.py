"""
EM-318 — CURATED TERMINAL FALLBACK (the mechanism) + the EM-319 revert.

`adaptive_routing.terminal_fallback` names the profile that holds the RESERVED
final-attempt slot in the adaptive bounce loop. UNSET ⇒ the W30 `auto` backstop
(byte-identical). EM-318 pointed it at a deterministic free lane
(gpt-oss-120b); EM-319 REVERTED the SHIPPED value to `auto` after a live storm
proved every specific lane can be individually rate-limited while the blind
pool still routes — so the mechanism supports any curated terminal, but the
shipped lanes.yaml deliberately keeps `terminal_fallback: auto`.

Covered here:
  - config parse + asdict fork/replay round-trip of `terminal_fallback`;
  - UNSET terminal_fallback ⇒ the reserved slot is `auto` (byte-identical W30);
  - a CONFIGURED curated terminal lane SERVES the reserved final attempt, and
    the blind `auto` lane is NEVER called during a full rate storm;
  - a curated terminal lane still gets the reserved slot when the curated lanes
    outnumber the attempt budget (the toy-universe blind spot the W30 auto
    backstop test also closed);
  - the shipped lanes.yaml resolves terminal_fallback=auto (the EM-319 revert).

Style-matches test_adaptive_softpin_reconcile.py: a REAL Router over fake
adapters that count calls / log call order. EM-318's part 1 (a viewer-side
feed-silence filter) was REMOVED per fix-don't-hide — EM-324 fixed the idle
churn at the root, so exhaustion idles are visible feed signal again.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime — collection breaks otherwise (repo convention).
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile, load_config,
    _parse_adaptive_routing,
)
from petridish.providers.base import ProviderError
from petridish.providers.router import Router

_KEY_ENV = "EM_EM318_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


# ──────────────────────────────────────────────────────────────────────────────
# Test adapters (mirror test_adaptive_softpin_reconcile.py's fakes)
# ──────────────────────────────────────────────────────────────────────────────

class _OkAdapter:
    def __init__(self, name: str, text: str | None = None,
                 log: list[str] | None = None):
        self.name = name
        self.text = text if text is not None else f"served/{name}"
        self.calls = 0
        self.last_routed_via = f"routed/{name}"
        self.last_usage: dict | None = None
        self._log = log

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        if self._log is not None:
            self._log.append(self.name)
        self.last_usage = {
            "input_tokens": 10, "output_tokens": 5,
            "latency_ms": 12.0, "finish_reason": "stop", "cached": False,
        }
        return self.text


class _FailAdapter:
    def __init__(self, name: str, status: int = 429,
                 detail: str = "Too Many Requests", log: list[str] | None = None):
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


def _profile(name: str, model_id: str, *, max_tokens: int = 512) -> ModelProfile:
    return ModelProfile(
        name=name, adapter="openai", model_id=model_id,
        max_tokens=max_tokens, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV,
    )


def _router(specs, order, *, terminal_fallback=None, max_attempts=3) -> Router:
    """specs: list of (profile_name, model_id, adapter_obj)."""
    profiles = [_profile(n, m) for (n, m, _a) in specs]
    overrides = {n: a for (n, _m, a) in specs}
    ar = AdaptiveRoutingParams(
        enabled=True, max_attempts=max_attempts, allow_paid=False,
        per_attempt_timeout_s=12.0, terminal_fallback=terminal_fallback,
        order=tuple(order),
    )
    return Router(profiles, adapter_overrides=overrides, cache_enabled=False,
                  adaptive_routing=ar)


# ══════════════════════════════════════════════════════════════════════════════
# Config parse + fork/replay round-trip
# ══════════════════════════════════════════════════════════════════════════════

def test_terminal_fallback_absent_defaults_to_none():
    d = _parse_adaptive_routing({"enabled": True})
    assert d.terminal_fallback is None


def test_terminal_fallback_parses_a_profile_name():
    d = _parse_adaptive_routing(
        {"enabled": True, "terminal_fallback": "gpt-oss-120b"})
    assert d.terminal_fallback == "gpt-oss-120b"


def test_terminal_fallback_blank_or_nonstring_falls_back_to_none():
    assert _parse_adaptive_routing(
        {"terminal_fallback": ""}).terminal_fallback is None
    assert _parse_adaptive_routing(
        {"terminal_fallback": 123}).terminal_fallback is None
    assert _parse_adaptive_routing(
        {"terminal_fallback": None}).terminal_fallback is None


def test_terminal_fallback_config_bake_round_trip():
    """The fork/replay seam serializes via asdict and reparses; the curated
    terminal-fallback name must survive so a replayed run routes identically."""
    original = _parse_adaptive_routing({
        "enabled": True, "terminal_fallback": "gpt-oss-120b",
        "order": [{"source": "freellmapi", "model": "*"}],
    })
    reparsed = _parse_adaptive_routing(asdict(original))
    assert reparsed == original
    assert reparsed.terminal_fallback == "gpt-oss-120b"


# ══════════════════════════════════════════════════════════════════════════════
# UNSET terminal_fallback ⇒ `auto` reserved (byte-identical W30)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_unset_terminal_fallback_reserves_auto_byte_identical():
    """No terminal_fallback ⇒ the reserved final slot is the proxy `auto` lane,
    exactly the W30 backstop. Every curated free lane 429s; `auto` serves the
    reserved final attempt."""
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    llama = _FailAdapter("groq-llama", 429, "llama 429", log=call_log)
    qwen = _FailAdapter("qwen-next", 429, "qwen 429", log=call_log)
    auto = _OkAdapter("auto", text="auto served", log=call_log)
    r = _router(
        [("home", "m-home", home), ("groq-llama", "m-llama", llama),
         ("qwen-next", "m-qwen", qwen), ("auto", "auto", auto)],
        [LaneOrderEntry("freellmapi", "m-llama"),
         LaneOrderEntry("freellmapi", "m-qwen"),
         LaneOrderEntry("freellmapi", "auto")],   # auto LAST, as in real configs
        terminal_fallback=None, max_attempts=3,
    )
    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served"
    # curated walk = max_attempts-1 = 2 (llama, qwen), then reserved `auto`.
    assert call_log == ["home", "groq-llama", "qwen-next", "auto"]
    assert auto.calls == 1
    assert r.last_usage("home")["bounced_to"] == "auto"


# ══════════════════════════════════════════════════════════════════════════════
# Curated terminal fallback SERVES the reserved slot; blind `auto` never called
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_curated_terminal_serves_final_slot_and_auto_is_never_called():
    """terminal_fallback=gpt-oss-120b ⇒ the reserved final attempt is the
    curated deterministic lane, NOT the proxy's blind `auto` router. During a
    full rate storm the curated walk 429s, then gpt-oss serves the reserved
    slot; `auto` (a low-priority mid-walk resort) is never even reached."""
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    llama = _FailAdapter("groq-llama", 429, "llama 429", log=call_log)
    qwen = _FailAdapter("qwen-next", 429, "qwen 429", log=call_log)
    auto = _OkAdapter("auto", text="auto served (must NOT be called)", log=call_log)
    gpt = _OkAdapter("gpt-oss-120b", text="gpt-oss served", log=call_log)
    r = _router(
        [("home", "m-home", home), ("groq-llama", "m-llama", llama),
         ("qwen-next", "m-qwen", qwen), ("auto", "auto", auto),
         ("gpt-oss-120b", "gpt-oss-120b", gpt)],
        [LaneOrderEntry("freellmapi", "m-llama"),
         LaneOrderEntry("freellmapi", "m-qwen"),
         LaneOrderEntry("freellmapi", "auto"),        # blind resort, mid-walk
         LaneOrderEntry("freellmapi", "gpt-oss*")],   # curated terminal, LAST
        terminal_fallback="gpt-oss-120b", max_attempts=3,
    )
    # Registry sanity: gpt-oss is the last FREE lane; auto sits before it.
    prio = [l["profile"] for l in r.lane_registry_snapshot()]
    assert prio[-1] == "gpt-oss-120b" and "auto" in prio

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "gpt-oss served"
    # curated walk = 2 (llama, qwen); reserved terminal = gpt-oss; auto skipped.
    assert call_log == ["home", "groq-llama", "qwen-next", "gpt-oss-120b"]
    assert auto.calls == 0                       # blind `auto` NEVER consulted
    assert gpt.calls == 1
    assert r.last_usage("home")["bounced_to"] == "gpt-oss-120b"


@pytest.mark.asyncio
async def test_curated_terminal_reserved_when_curated_lanes_outnumber_attempts():
    """More healthy curated lanes than the attempt budget: the curated terminal
    still gets the RESERVED final slot (not consumed by an earlier walk lane),
    and its own failure surfaces to the runtime's idle fallback."""
    call_log: list[str] = []
    home = _FailAdapter("home", 429, "home 429", log=call_log)
    frees = {
        f"free{i}": _FailAdapter(f"free{i}", 429, f"free{i} 429", log=call_log)
        for i in range(1, 5)
    }
    gpt = _FailAdapter("gpt-oss-120b", 429, "gpt-oss 429", log=call_log)
    r = _router(
        [("home", "m-home", home),
         *[(n, f"m-{n}", a) for n, a in frees.items()],
         ("gpt-oss-120b", "gpt-oss-120b", gpt)],
        [LaneOrderEntry("freellmapi", "m-free*"),     # sweeps free1..free4
         LaneOrderEntry("freellmapi", "gpt-oss*")],   # curated terminal, LAST
        terminal_fallback="gpt-oss-120b", max_attempts=3,
    )
    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # curated walk = max_attempts-1 = 2 slots; the final slot is gpt-oss's.
    assert call_log == ["home", "free1", "free2", "gpt-oss-120b"]
    assert frees["free3"].calls == 0 and frees["free4"].calls == 0
    assert gpt.calls == 1
    assert exc_info.value.detail == "gpt-oss 429"


@pytest.mark.asyncio
async def test_curated_terminal_that_is_the_pin_forfeits_the_reservation():
    """A pin can't be its own backstop: when the pinned lane IS the configured
    terminal_fallback, the reservation is forfeited (already in `tried`) and the
    curated walk keeps the FULL budget — no self-recursion, no lost attempts."""
    call_log: list[str] = []
    gpt = _FailAdapter("gpt-oss-120b", 429, "gpt-oss 429", log=call_log)  # pin
    llama = _FailAdapter("groq-llama", 429, "llama 429", log=call_log)
    qwen = _OkAdapter("qwen-next", text="qwen served", log=call_log)
    r = _router(
        [("gpt-oss-120b", "gpt-oss-120b", gpt), ("groq-llama", "m-llama", llama),
         ("qwen-next", "m-qwen", qwen)],
        [LaneOrderEntry("freellmapi", "m-llama"),
         LaneOrderEntry("freellmapi", "m-qwen"),
         LaneOrderEntry("freellmapi", "gpt-oss*")],
        terminal_fallback="gpt-oss-120b", max_attempts=3,
    )
    text = await r.chat("gpt-oss-120b", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "qwen served"
    # Full budget (max_attempts=3): pin + llama + qwen; the pin is not re-tried.
    assert call_log == ["gpt-oss-120b", "groq-llama", "qwen-next"]
    assert gpt.calls == 1


# ══════════════════════════════════════════════════════════════════════════════
# Shipped lanes.yaml wiring
# ══════════════════════════════════════════════════════════════════════════════

def test_shipped_lanes_yaml_terminal_fallback_reverted_to_auto():
    # EM-319 (2026-07-13) REVERTED EM-318's curated `gpt-oss-120b` terminal back
    # to blind `auto`. EM-318's premise ("`auto` returns All models exhausted in
    # a storm") was empirically false: during a real rate storm every SPECIFIC
    # lane (incl. gpt-oss-120b) 429s while `auto` still routes to a live model —
    # so a specific terminal death-spiraled the sim (~93% idle → starvation). The
    # blind pool is the only storm-proof last attempt; its rare exhaustion idles
    # stay VISIBLE in the feed (fix-don't-hide — EM-324 fixed the root churn).
    cfg = load_config()
    ar = cfg.world.adaptive_routing
    # EM-323 widened max_attempts 4→5; EM-324 rebuilt `order` to probe-verified
    # clean lanes (dropped command-a-2 the truncator). Terminal stays `auto`
    # (EM-319) — the only storm-proof last attempt.
    assert ar.enabled is True and ar.max_attempts == 5
    assert ar.terminal_fallback == "auto"
    # Still $0-first, paid anthropic opt-in stays dead last.
    assert ar.allow_paid is False
    assert ar.order[-1].source == "anthropic" and ar.order[-1].free is False

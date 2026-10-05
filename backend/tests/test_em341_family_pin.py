"""
EM-341 — family-scoped routing (`adaptive_routing.family_pin`, default OFF).

The finding (runs 22/23): adaptive routing + lane discovery collapsed BOTH
contact casts onto the same third-party kilo/* disco lanes (~60-70% of resolved
turns each agent), so the EM-335 cast-vs-town read-off was confounded and the
run-23 llama cast went stationary on lane-specific failures (behavior tracks
the LANE, not the nominal family). The fix: when `family_pin: true`, a call
whose HOME lane classifies to a known model family (the EM-112 table) may only
be SERVED by same-family lanes — enforced at every substitute-serving path:

  - the adaptive bounce walk (kilo/"other" disco lanes barred),
  - the RESERVED terminal slot (cross-family `auto` forfeits, never serves
    blind; a curated same-family terminal still serves),
  - the EM-205 auto backup (non-adaptive path),
  - the per-lane-cooling pre-emptive route to `auto`,
  - the EM-167 overflow spill, and the #76 detour candidate.

Byte-identical when OFF (the default) and for an UNCLASSIFIABLE home (a lane
the table cannot name — `auto`, mock, kilo/ling-* — has no family to pin to).
The caller's OWN pin is never gated (a sick pin still probes home); when every
same-family lane fails the bounce re-raises to the idle fallback exactly as
before — never mute.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise) — we import
engine.world first per the repo convention.
"""
from __future__ import annotations

from dataclasses import asdict

import pytest

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile,
    _parse_adaptive_routing,
)
from petridish.providers.base import ProviderError
from petridish.providers.lanes import Lane
from petridish.providers.router import Router

_KEY_ENV = "EM_ADAPTIVE_ROUTING_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


# ──────────────────────────────────────────────────────────────────────────────
# Harness (mirrors test_adaptive_lane_routing.py's fakes)
# ──────────────────────────────────────────────────────────────────────────────

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


def _profile(name: str, model_id: str, *, max_tokens: int = 512,
             adapter: str = "openai") -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=model_id,
        max_tokens=max_tokens, temperature=0.8,
        base_url="http://localhost:3001/v1",   # ⇒ source "freellmapi"
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _ar(order, *, enabled: bool = True, max_attempts: int = 3,
        allow_paid: bool = False, per_attempt_timeout_s: float = 12.0,
        family_pin: bool = False,
        terminal_fallback: str | None = None) -> AdaptiveRoutingParams:
    return AdaptiveRoutingParams(
        enabled=enabled, max_attempts=max_attempts, allow_paid=allow_paid,
        per_attempt_timeout_s=per_attempt_timeout_s, order=tuple(order),
        family_pin=family_pin, terminal_fallback=terminal_fallback,
    )


def _router(specs, order, *, auto=None, lane_failover=None,
            overflow_lane=None, **ar_kwargs) -> Router:
    """specs: list of (name, model_id, adapter_obj, max_tokens)."""
    profiles = [_profile(n, m, max_tokens=mt) for (n, m, _a, mt) in specs]
    overrides = {n: a for (n, _m, a, _mt) in specs}
    if auto is not None:
        profiles.append(_profile("auto", "auto"))
        overrides["auto"] = auto
    return Router(
        profiles, adapter_overrides=overrides, cache_enabled=False,
        lane_failover=lane_failover, overflow_lane=overflow_lane,
        adaptive_routing=_ar(order, **ar_kwargs),
    )


def _lane(profile: str, model_id: str, *, source: str = "freellmapi",
          out_hint: int | None = None, tags=()) -> Lane:
    return Lane(id=f"{source}:{profile}", source=source, model_id=model_id,
                profile=profile, out_hint=out_hint, tags=tuple(tags))


# ══════════════════════════════════════════════════════════════════════════════
# (A) Config parse + gate predicates
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_family_pin_default_off_and_roundtrip():
    # Absent (no lanes.yaml / old config_json) ⇒ OFF, byte-identical.
    d = _parse_adaptive_routing(None)
    assert d.family_pin is False
    assert _parse_adaptive_routing({}).family_pin is False
    assert _parse_adaptive_routing({"family_pin": False}).family_pin is False
    # Explicit flip parses; the asdict round-trip (config_json → fork/replay)
    # preserves it.
    assert _parse_adaptive_routing({"family_pin": True}).family_pin is True
    original = _parse_adaptive_routing({"family_pin": True, "enabled": True})
    assert _parse_adaptive_routing(asdict(original)).family_pin is True


def test_lane_family_classification():
    """The EM-112 table classifies the lanes this flag must separate — the
    exact run-23/26 rogues included. gemma is its OWN family (not llama)."""
    r = _router(
        [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512),
         ("llm", "llama-3.3-70b-fp8-fast", _OkAdapter("llm"), 512),
         ("ol", "gemma4:31b", _OkAdapter("ol"), 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", _OkAdapter("kilo"), 512)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    assert r._lane_family("gem") == "gemini"
    assert r._lane_family("llm") == "llama"
    assert r._lane_family("ol") == "gemma"
    assert r._lane_family("kilo") == "other"   # the EM-341 confound lane
    assert r._lane_family("auto") == "other"   # the blind terminal
    assert r._lane_family("missing") == "other"


def test_family_gate_active_only_for_classified_homes():
    r = _router(
        [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", _OkAdapter("kilo"), 512)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    # Flag off ⇒ never active (byte-identical), whatever the home is.
    assert r._family_gate_active("gem") is False
    # Flag on + classified home ⇒ active.
    r2 = _router(
        [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512)],
        [LaneOrderEntry("freellmapi", "*")], family_pin=True,
    )
    assert r2._family_gate_active("gem") is True
    # Flag on + UNCLASSIFIABLE home ⇒ stands the gate down.
    assert r2._family_gate_active("kilo") is False


def test_family_allows_strict_rules():
    r = _router(
        [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512),
         ("gem2", "gemini-3.8-flash", _OkAdapter("gem2"), 512),
         ("llm", "llama-3.3-70b-fp8-fast", _OkAdapter("llm"), 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", _OkAdapter("kilo"), 512)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    gate = True
    assert r._family_allows(gate, "gem", "gem2") is True    # same family
    assert r._family_allows(gate, "gem", "gem") is True     # the pin itself
    assert r._family_allows(gate, "gem", "llm") is False    # cross-family
    # STRICT: an unclassifiable candidate (the kilo collapse) is barred.
    assert r._family_allows(gate, "gem", "kilo") is False
    # Gate off ⇒ everything allowed (pre-341 behavior).
    assert r._family_allows(False, "gem", "kilo") is True


# ══════════════════════════════════════════════════════════════════════════════
# (B) The bounce walk
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bounce_confined_to_home_family():
    """Gemini home fails → the kilo/* lane (the run-23/26 confound) is never
    called; the same-family lane serves."""
    home = _FailAdapter("gem")
    kilo = _OkAdapter("kilo")
    gem2 = _OkAdapter("gem2", text="same-family served")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", kilo, 512),
         ("gem2", "gemini-3.8-flash", gem2, 512)],
        [LaneOrderEntry("freellmapi", "*")], family_pin=True,
    )
    text = await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "same-family served"
    assert home.calls == 1 and gem2.calls == 1
    assert kilo.calls == 0   # cross-family candidate barred from serving


@pytest.mark.asyncio
async def test_bounce_gate_off_keeps_pre341_behavior():
    """Negative control: flag OFF (the default) — the cross-family lane DOES
    serve, exactly the pre-341 walk (this is how runs 22/23 collapsed)."""
    home = _FailAdapter("gem")
    kilo = _OkAdapter("kilo", text="kilo served")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", kilo, 512)],
        [LaneOrderEntry("freellmapi", "*")], family_pin=False,
    )
    text = await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "kilo served"
    assert kilo.calls == 1


@pytest.mark.asyncio
async def test_bounce_no_same_family_lane_reraises():
    """Every same-family lane failing ⇒ re-raise to the idle fallback (never
    mute, never silently cross the family line)."""
    home = _FailAdapter("gem")
    kilo = _OkAdapter("kilo", text="should not serve")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512),
         ("kilo", "kilo/ling-3.0-flash-sante:free", kilo, 512)],
        [LaneOrderEntry("freellmapi", "*")], family_pin=True,
    )
    with pytest.raises(ProviderError):
        await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert kilo.calls == 0


@pytest.mark.asyncio
async def test_unclassifiable_home_stands_gate_down():
    """A home the table cannot name (kilo/ling-*) has no family to pin —
    pre-341 behavior: the next lane serves, whatever its family."""
    home = _FailAdapter("kilo")
    gem = _OkAdapter("gem", text="gemini served")
    r = _router(
        [("kilo", "kilo/ling-3.0-flash-sante:free", home, 512),
         ("gem", "gemini-3.1-flash-lite", gem, 512)],
        [LaneOrderEntry("freellmapi", "*")], family_pin=True,
    )
    text = await r.chat("kilo", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "gemini served"
    assert gem.calls == 1


# ══════════════════════════════════════════════════════════════════════════════
# (C) The reserved terminal slot
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reserved_auto_forfeits_when_cross_family():
    """The blind `auto` whole-pool router (family 'other') FORFEITS the
    reserved slot for a family-scoped call instead of smuggling another
    family's model in; the curated budget stays full and the walk re-raises."""
    home = _FailAdapter("gem")
    llm = _OkAdapter("llm")
    auto = _OkAdapter("auto")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512),
         ("llm", "llama-3.3-70b-fp8-fast", llm, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        auto=auto, family_pin=True,
    )
    with pytest.raises(ProviderError):
        await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert llm.calls == 0    # cross-family curated candidate barred
    assert auto.calls == 0   # cross-family reserved terminal forfeited


@pytest.mark.asyncio
async def test_reserved_same_family_terminal_serves():
    """A CURATED same-family terminal keeps its slot: budget consumed by a
    failing same-family lane, the reserved lane serves post-loop."""
    home = _FailAdapter("gem")
    gem_a = _FailAdapter("gem_a", 500, "err-a")
    gem_b = _OkAdapter("gem_b", text="reserved served")
    llm = _OkAdapter("llm")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512),
         ("gem_a", "gemini-3.8-flash", gem_a, 512),
         ("gem_b", "gemini-3.5-flash", gem_b, 512),
         ("llm", "llama-3.3-70b-fp8-fast", llm, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        family_pin=True, max_attempts=2, terminal_fallback="gem_b",
    )
    text = await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "reserved served"
    assert gem_a.calls == 1          # consumed the curated budget
    assert llm.calls == 0            # cross-family, barred
    assert gem_b.calls == 1          # the reserved same-family slot


# ══════════════════════════════════════════════════════════════════════════════
# (D) auto backup (EM-205, non-adaptive) + the cooling pre-empt
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_auto_backup_forfeits_when_cross_family():
    """Non-adaptive EM-205 path: family_pin still scopes the backup — a
    cross-family `auto` forfeits and the home error propagates."""
    home = _FailAdapter("gem")
    auto = _OkAdapter("auto")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        auto=auto, enabled=False, family_pin=True,
    )
    with pytest.raises(ProviderError):
        await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert auto.calls == 0


@pytest.mark.asyncio
async def test_auto_backup_serves_when_gate_off():
    """Negative control: the EM-205 backup fires as today when the flag is
    off (byte-identical pre-341)."""
    home = _FailAdapter("gem")
    auto = _OkAdapter("auto")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        auto=auto, enabled=False, family_pin=False,
    )
    text = await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "served/auto"
    assert auto.calls == 1


@pytest.mark.asyncio
async def test_cooling_preempt_skips_cross_family_auto():
    """A cooling gemini pin must NOT be pre-empted onto the blind `auto`
    (cross-family); it falls through to the (gated) adaptive walk and
    re-raises when no same-family lane exists."""
    home = _FailAdapter("gem")
    auto = _OkAdapter("auto")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        auto=auto, family_pin=True,
    )
    r._set_cooldown("gem", 30.0)
    with pytest.raises(ProviderError):
        await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert auto.calls == 0    # the cross-family pre-empt did not fire


@pytest.mark.asyncio
async def test_cooling_preempt_serves_auto_when_gate_off():
    """Negative control: the cooling pre-empt routes to `auto` as today."""
    home = _FailAdapter("gem")
    auto = _OkAdapter("auto")
    r = _router(
        [("gem", "gemini-3.1-flash-lite", home, 512)],
        [LaneOrderEntry("freellmapi", "*")],
        auto=auto, family_pin=False,
    )
    r._set_cooldown("gem", 30.0)
    text = await r.chat("gem", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "served/auto"
    assert home.calls == 0    # pre-empted, no doomed POST


# ══════════════════════════════════════════════════════════════════════════════
# (E) Overflow spill (EM-167) + detour candidate (#76)
# ══════════════════════════════════════════════════════════════════════════════

def test_overflow_suppresses_cross_family_target():
    """A gemini home spilling background turns onto the local ollama/gemma
    lane (run 26's actual top lane at 25%) self-suppresses when pinned."""
    specs = [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512),
             ("ollama", "gemma4:31b", _OkAdapter("ollama"), 512)]
    over = {"enabled": True, "profile": "ollama",
            "tiers": ("background", "supporting")}
    on = _router(specs, [LaneOrderEntry("freellmapi", "*")],
                 overflow_lane=over, enabled=False, family_pin=True)
    assert on.effective_profile("a1", "gem", "background") == ("gem", None)
    off = _router(specs, [LaneOrderEntry("freellmapi", "*")],
                  overflow_lane=over, enabled=False, family_pin=False)
    assert off.effective_profile("a1", "gem", "background") == (
        "ollama", "overflow")


def test_detour_candidate_scoped_to_family():
    """The #76 pre-adaptive detour cannot hand a sick gemini pin to a
    llama-family lane when pinned; the same-family substitute wins."""
    specs = [("gem", "gemini-3.1-flash-lite", _OkAdapter("gem"), 512),
             ("ollama", "gemma4:31b", _OkAdapter("ollama"), 512),
             ("gem2", "gemini-3.8-flash", _OkAdapter("gem2"), 512)]
    lf = {"enabled": True}
    on = _router(specs, [LaneOrderEntry("freellmapi", "*")],
                 lane_failover=lf, enabled=False, family_pin=True)
    for _ in range(3):
        on.note_lane_error("gem")
    assert on.effective_profile("a1", "gem") == ("gem2", "detour")
    off = _router(specs, [LaneOrderEntry("freellmapi", "*")],
                  lane_failover=lf, enabled=False, family_pin=False)
    for _ in range(3):
        off.note_lane_error("gem")
    # Pre-341: the first healthy candidate in profile order (the ollama lane).
    assert off.effective_profile("a1", "gem") == ("ollama", "detour")

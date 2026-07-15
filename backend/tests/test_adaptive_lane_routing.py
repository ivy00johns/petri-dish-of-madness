"""
Adaptive Lane Routing — Phase P1 (spec 2026-07-07, §9/§10).

Registry + sorting list + the ordered/health-aware/time-capped bounce loop that
replaces the auto-only backup, behind `adaptive_routing.enabled` (default OFF ⇒
byte-identical). This file gates:

  (A) SortingList + LaneRegistry — ascending priority top-to-bottom, `*` glob
      sweep of remaining lanes, paid exclusion unless allow_paid, `auto` pinned
      last, Lane.fits ceiling.
  (B) Bounce loop — pinned-healthy candidate used + attributed; a sick candidate
      skipped to the next healthy; try up to max_attempts then re-raise (idle =
      last resort); ceiling-skip (the #77 regression, now a test); reasoning-tag
      skipped on a strict-JSON turn; `auto` is just the last order entry; a
      per-attempt timeout skips to the next lane.
  (C) Determinism — `enabled: false` (the default / no lanes.yaml) is
      byte-identical: chat()'s except-branch calls _auto_backup_call and NEVER
      the registry; config parse defaults + asdict round-trip.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise) — not needed here, but we
import engine.world first defensively per the repo convention.
"""
from __future__ import annotations

import fnmatch
from dataclasses import asdict, replace
from pathlib import Path

import pytest
import yaml

import petridish.engine.world  # noqa: F401 — circular-import guard (repo rule)
from petridish.config.loader import (
    AdaptiveRoutingParams, LaneOrderEntry, ModelProfile,
    _parse_adaptive_routing, load_config,
)
from petridish.providers.base import ProviderError
from petridish.providers.lanes import Lane, LaneRegistry, SortingList
from petridish.providers.router import Router

_KEY_ENV = "EM_ADAPTIVE_ROUTING_TEST_KEY"
_MESSAGES = [{"role": "user", "content": "act"}]


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


# ──────────────────────────────────────────────────────────────────────────────
# Test adapters (mirror test_error_bounce.py's fakes)
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


class _HangAdapter:
    def __init__(self, name: str):
        self.name = name
        self.calls = 0
        self.last_routed_via = None
        self.last_usage: dict | None = None

    async def chat(self, messages, *, max_tokens, temperature):
        import asyncio
        self.calls += 1
        await asyncio.sleep(30)  # cancelled by the per-attempt timeout
        return "never"           # pragma: no cover


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


def _lane(profile: str, model_id: str, *, source: str = "freellmapi",
          out_hint: int | None = None, tags=()) -> Lane:
    return Lane(id=f"{source}:{profile}", source=source, model_id=model_id,
                profile=profile, out_hint=out_hint, tags=tuple(tags))


# ══════════════════════════════════════════════════════════════════════════════
# (A) SortingList + LaneRegistry
# ══════════════════════════════════════════════════════════════════════════════

def test_sorting_assigns_ascending_priority_top_to_bottom():
    universe = [_lane("a", "m-a"), _lane("b", "m-b"), _lane("c", "m-c")]
    order = [LaneOrderEntry("freellmapi", "m-c"),
             LaneOrderEntry("freellmapi", "m-a"),
             LaneOrderEntry("freellmapi", "m-b")]
    out = SortingList(order).apply(universe)
    assert [(l.profile, l.priority) for l in out] == [("c", 0), ("a", 1), ("b", 2)]


def test_sorting_glob_sweeps_remaining_lanes_of_source():
    universe = [_lane("a", "m-a"), _lane("b", "m-b"),
                _lane("g", "m-g", source="gemini")]
    order = [LaneOrderEntry("freellmapi", "m-a"),
             LaneOrderEntry("freellmapi", "*")]
    out = SortingList(order).apply(universe)
    # m-a explicit first, then the glob sweeps b; gemini:g matches no entry → dropped.
    assert [(l.profile, l.priority) for l in out] == [("a", 0), ("b", 1)]


def test_sorting_paid_entry_excluded_unless_allow_paid():
    universe = [_lane("free1", "m-free"),
                _lane("paid1", "claude-x", source="anthropic")]
    order = [LaneOrderEntry("freellmapi", "*"),
             LaneOrderEntry("anthropic", "claude-x", free=False)]

    without = SortingList(order, allow_paid=False).apply(universe)
    assert [l.profile for l in without] == ["free1"]  # paid excluded

    with_paid = SortingList(order, allow_paid=True).apply(universe)
    assert [l.profile for l in with_paid] == ["free1", "paid1"]
    assert with_paid[-1].free is False


def test_glob_does_not_grab_a_lane_a_concrete_entry_names_later():
    # `auto` is listed AFTER the `*`; it must still land last, not be swept.
    universe = [_lane("x", "m-x"), _lane("auto", "auto"), _lane("y", "m-y")]
    order = [LaneOrderEntry("freellmapi", "*"),
             LaneOrderEntry("freellmapi", "auto")]
    out = SortingList(order).apply(universe)
    assert out[-1].profile == "auto"          # pinned last, not swept by `*`
    assert {l.profile for l in out} == {"x", "y", "auto"}


def test_exclude_denylists_a_lane_from_the_glob_sweep():
    """PR#106 C15: a legacy-only profile (command-a-2, the EM-324 truncator)
    must not be re-placed by the `*` sweep — the exclude matcher bars it."""
    universe = [_lane("a", "m-a"), _lane("command-a", "command-a-2")]
    order = [LaneOrderEntry("freellmapi", "*")]
    out = SortingList(
        order, exclude=[LaneOrderEntry("freellmapi", "command-a-2")],
    ).apply(universe)
    assert [l.profile for l in out] == ["a"]   # swept lane in, denylisted out


def test_exclude_beats_a_concrete_entry_naming_the_same_model():
    """Exclusion is absolute: even a concrete order entry cannot place a
    denylisted lane."""
    universe = [_lane("a", "m-a"), _lane("command-a", "command-a-2")]
    order = [LaneOrderEntry("freellmapi", "command-a-2"),
             LaneOrderEntry("freellmapi", "*")]
    out = SortingList(
        order, exclude=[LaneOrderEntry("freellmapi", "command-a-2")],
    ).apply(universe)
    assert [l.profile for l in out] == ["a"]


def test_exclude_is_source_scoped():
    # An exclude matcher only covers its own source; a same-model lane of
    # another source is untouched.
    universe = [_lane("g", "shared-id", source="gemini"),
                _lane("f", "shared-id")]
    order = [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("gemini", "*")]
    out = SortingList(
        order, exclude=[LaneOrderEntry("freellmapi", "shared-id")],
    ).apply(universe)
    assert [l.profile for l in out] == ["g"]


def test_registry_ordered_and_get():
    lanes = [replace(_lane("a", "m-a"), priority=2),
             replace(_lane("b", "m-b"), priority=0)]
    reg = LaneRegistry(lanes)
    assert [l.profile for l in reg.ordered()] == ["b", "a"]  # sorted by priority
    assert reg.get("freellmapi:a").profile == "a"
    assert reg.get("nope") is None


def test_lane_fits_ceiling():
    assert _lane("a", "m", out_hint=1024).fits(512) is True
    assert _lane("a", "m", out_hint=1024).fits(1024) is True
    assert _lane("a", "m", out_hint=512).fits(1024) is False
    assert _lane("a", "m", out_hint=None).fits(99999) is True  # no ceiling ⇒ fits


# ══════════════════════════════════════════════════════════════════════════════
# (B) Bounce loop
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bounce_uses_next_healthy_lane_and_attributes_it():
    home, beta = _FailAdapter("home"), _OkAdapter("beta", text="beta served")
    r = _router([("home", "m-home", home, 512), ("beta", "m-beta", beta, 512)],
                [LaneOrderEntry("freellmapi", "*")])

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "beta served"
    assert home.calls == 1 and beta.calls == 1
    # EM-198/EM-205 attribution: the requested profile reports the substitute's truth.
    usage = r.last_usage("home")
    assert usage["bounced_from"] == "home" and usage["bounced_to"] == "beta"
    assert r.last_routed_via("home") == "routed/beta"
    # Home's failure is recorded as a demerit (observability, like EM-205).
    assert r.lane_health()["home"]["errors"] == 1


@pytest.mark.asyncio
async def test_bounce_skips_sick_candidate_to_next_healthy():
    home = _FailAdapter("home")
    sick = _OkAdapter("sick")
    healthy = _OkAdapter("healthy", text="healthy served")
    r = _router(
        [("home", "m-home", home, 512), ("sick", "m-sick", sick, 512),
         ("healthy", "m-healthy", healthy, 512)],
        [LaneOrderEntry("freellmapi", "*")],
    )
    # Mark the `sick` lane sick in the EM-135 window (default threshold 3).
    for _ in range(3):
        r.note_lane_error("sick")
    assert r.lane_sick("sick") is True

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "healthy served"
    assert sick.calls == 0        # sick candidate skipped, never called
    assert healthy.calls == 1


@pytest.mark.asyncio
async def test_bounce_tries_up_to_max_attempts_then_reraises():
    home = _FailAdapter("home")
    a, b = _FailAdapter("a", 500, "err-a"), _FailAdapter("b", 502, "err-b")
    c = _OkAdapter("c", text="should not reach")
    r = _router(
        [("home", "m-home", home, 512), ("a", "m-a", a, 512),
         ("b", "m-b", b, 512), ("c", "m-c", c, 512)],
        [LaneOrderEntry("freellmapi", "*")], max_attempts=2,
    )

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert a.calls == 1 and b.calls == 1      # exactly max_attempts lanes tried
    assert c.calls == 0                        # the 3rd healthy lane never reached
    assert exc_info.value.detail == "err-b"    # last failure surfaces (→ EM-173 idle)


@pytest.mark.asyncio
async def test_bounce_skips_lane_whose_out_hint_cannot_fit_request():
    """The #77 regression: a capped-output lane is skipped when it can't fit
    THIS request's max_tokens — we never strand ourselves on it again."""
    home = _FailAdapter("home")
    small = _OkAdapter("small")                 # out_hint 512 (profile max_tokens)
    big = _OkAdapter("big", text="big served")  # out_hint 4096
    r = _router(
        [("home", "m-home", home, 512), ("small", "m-small", small, 512),
         ("big", "m-big", big, 4096)],
        [LaneOrderEntry("freellmapi", "*")],
    )

    text = await r.chat("home", _MESSAGES, max_tokens=1024, temperature=0.8)

    assert text == "big served"
    assert small.calls == 0    # 512 < 1024 ⇒ skipped
    assert big.calls == 1


@pytest.mark.asyncio
async def test_big_max_tokens_does_not_exclude_a_small_lane_for_a_small_request():
    """The #77 nuance: the ceiling skip is per-REQUEST. A small request must
    still try a small-output free lane."""
    home = _FailAdapter("home")
    small = _OkAdapter("small", text="small served")  # out_hint 512
    r = _router([("home", "m-home", home, 512), ("small", "m-small", small, 512)],
                [LaneOrderEntry("freellmapi", "*")])

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "small served"
    assert small.calls == 1    # 512 >= 256 ⇒ tried, not stranded


@pytest.mark.asyncio
async def test_bounce_skips_reasoning_lane_on_strict_json_turn():
    home = _FailAdapter("home")
    reasoner = _OkAdapter("reasoner")
    plain = _OkAdapter("plain", text="plain served")
    r = _router(
        [("home", "m-home", home, 512), ("reasoner", "reason-m", reasoner, 512),
         ("plain", "m-plain", plain, 512)],
        [LaneOrderEntry("freellmapi", "reason-m", tags=("reasoning",)),
         LaneOrderEntry("freellmapi", "*")],
    )

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8,
                        require_json=True)

    assert text == "plain served"
    assert reasoner.calls == 0    # reasoning-tagged ⇒ skipped on a JSON turn


@pytest.mark.asyncio
async def test_reasoning_lane_is_tried_when_not_a_strict_json_turn():
    home = _FailAdapter("home")
    reasoner = _OkAdapter("reasoner", text="reasoner served")
    plain = _OkAdapter("plain")
    r = _router(
        [("home", "m-home", home, 512), ("reasoner", "reason-m", reasoner, 512),
         ("plain", "m-plain", plain, 512)],
        [LaneOrderEntry("freellmapi", "reason-m", tags=("reasoning",)),
         LaneOrderEntry("freellmapi", "*")],
    )

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8,
                        require_json=False)

    assert text == "reasoner served"   # highest priority, no JSON constraint
    assert reasoner.calls == 1 and plain.calls == 0


@pytest.mark.asyncio
async def test_auto_is_just_the_last_order_entry_not_special_cased():
    home = _FailAdapter("home")
    free = _OkAdapter("free", text="free served")
    auto = _OkAdapter("auto", text="auto served")
    r = _router(
        [("home", "m-home", home, 512), ("free", "m-free", free, 512)],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto,
    )

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "free served"   # a free lane precedes auto in the order
    assert free.calls == 1 and auto.calls == 0


@pytest.mark.asyncio
async def test_auto_serves_last_when_the_free_lanes_fail():
    home = _FailAdapter("home")
    free = _FailAdapter("free")
    auto = _OkAdapter("auto", text="auto served")
    r = _router(
        [("home", "m-home", home, 512), ("free", "m-free", free, 512)],
        [LaneOrderEntry("freellmapi", "*"), LaneOrderEntry("freellmapi", "auto")],
        auto=auto,
    )

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "auto served"   # auto is the last resort in the curated list
    assert free.calls == 1 and auto.calls == 1


@pytest.mark.asyncio
async def test_per_attempt_timeout_skips_a_hanging_lane():
    home = _FailAdapter("home")
    hang = _HangAdapter("hang")
    live = _OkAdapter("live", text="live served")
    r = _router(
        [("home", "m-home", home, 512), ("hang", "m-hang", hang, 512),
         ("live", "m-live", live, 512)],
        [LaneOrderEntry("freellmapi", "*")], per_attempt_timeout_s=0.05,
    )

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    assert text == "live served"
    assert hang.calls == 1 and live.calls == 1
    # A stalled lane is recorded as a timeout demerit (EM-170 window).
    assert r.lane_health()["hang"]["timeouts"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# (C) Determinism — disabled path is byte-identical (never touches the registry)
# ══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_disabled_uses_auto_backup_and_never_the_registry():
    home, auto = _FailAdapter("home"), _OkAdapter("auto", text="auto served")
    r = _router([("home", "m-home", home, 512)],
                [LaneOrderEntry("freellmapi", "*")], enabled=False, auto=auto)

    # Spy: the bounce loop must NOT run on the disabled path.
    def _boom(*a, **k):  # pragma: no cover - must never be called
        raise AssertionError("bounce loop ran while adaptive_routing disabled")
    r._bounce_call = _boom  # type: ignore[assignment]

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)

    # Byte-identical EM-205 behavior: the home error bounced to `auto`.
    assert text == "auto served"
    assert auto.calls == 1
    assert r.last_usage("home")["bounced_to"] == "auto"


@pytest.mark.asyncio
async def test_disabled_by_default_when_no_adaptive_config():
    # adaptive_routing=None ⇒ OFF ⇒ EM-205 auto-backup, no registry consulted.
    home, auto = _FailAdapter("home"), _OkAdapter("auto", text="auto served")
    profiles = [_profile("home", "m-home"), _profile("auto", "auto")]
    r = Router(profiles, adapter_overrides={"home": home, "auto": auto},
               cache_enabled=False)  # no adaptive_routing kwarg at all

    assert r._adaptive_enabled() is False

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("bounce ran with no adaptive config")
    r._bounce_call = _boom  # type: ignore[assignment]

    text = await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert text == "auto served" and auto.calls == 1


@pytest.mark.asyncio
async def test_disabled_opt_out_propagates_original_error_unbounced():
    # No auto lane + disabled ⇒ the original error propagates (EM-205 opt-out).
    home = _FailAdapter("home", 429)
    r = _router([("home", "m-home", home, 512)],
                [LaneOrderEntry("freellmapi", "*")], enabled=False)

    with pytest.raises(ProviderError) as exc_info:
        await r.chat("home", _MESSAGES, max_tokens=256, temperature=0.8)
    assert exc_info.value.status == 429


# ── Config parsing / round-trip ───────────────────────────────────────────────

def test_absent_block_parses_to_off_defaults():
    d = _parse_adaptive_routing(None)
    assert d == AdaptiveRoutingParams()
    assert d.enabled is False and d.max_attempts == 3
    assert d.per_attempt_timeout_s == 12.0 and d.allow_paid is False
    assert d.order == ()


def test_parse_block_reads_order_and_knobs():
    raw = {
        "enabled": True, "max_attempts": 5, "per_attempt_timeout_s": 8,
        "allow_paid": True,
        "order": [
            {"source": "freellmapi", "model": "gpt-oss-120b*", "free": True},
            {"source": "freellmapi", "model": "*"},
            {"source": "anthropic", "model": "claude-sonnet-5", "free": False},
        ],
    }
    d = _parse_adaptive_routing(raw)
    assert d.enabled is True and d.max_attempts == 5
    assert d.per_attempt_timeout_s == 8.0 and d.allow_paid is True
    assert [(e.source, e.model, e.free) for e in d.order] == [
        ("freellmapi", "gpt-oss-120b*", True),
        ("freellmapi", "*", True),
        ("anthropic", "claude-sonnet-5", False),
    ]


def test_parse_clamps_max_attempts_and_skips_malformed_entries():
    d = _parse_adaptive_routing({
        "max_attempts": 0,                       # clamped to >= 1
        "order": [{"model": "x"},                # no source ⇒ skipped
                  {"source": "freellmapi"}],      # default model "*"
    })
    assert d.max_attempts == 1
    assert [(e.source, e.model) for e in d.order] == [("freellmapi", "*")]


def test_parse_reads_exclude_denylist():
    d = _parse_adaptive_routing({
        "exclude": [{"source": "freellmapi", "model": "command-a-2"}],
    })
    assert [(e.source, e.model) for e in d.exclude] == [
        ("freellmapi", "command-a-2")]
    # Absent / malformed ⇒ empty (nothing excluded).
    assert _parse_adaptive_routing({}).exclude == ()
    assert _parse_adaptive_routing({"exclude": "nope"}).exclude == ()


def test_exclude_survives_config_json_asdict_round_trip():
    """PR#106 C15: the denylist must survive the fork/replay seam, or a
    replayed run would re-place the excluded lane."""
    original = _parse_adaptive_routing({
        "enabled": True,
        "order": [{"source": "freellmapi", "model": "*"}],
        "exclude": [{"source": "freellmapi", "model": "command-a-2"}],
    })
    reparsed = _parse_adaptive_routing(asdict(original))
    assert reparsed == original
    assert reparsed.exclude[0].model == "command-a-2"


def test_config_json_asdict_round_trip():
    """The fork/replay seam serializes via asdict (order → list of dicts) and
    reparses; the entries must survive the round-trip."""
    original = _parse_adaptive_routing({
        "enabled": True,
        "order": [{"source": "freellmapi", "model": "a*", "free": True,
                   "out_hint": 2048, "tags": ["reasoning"]}],
    })
    reparsed = _parse_adaptive_routing(asdict(original))
    assert reparsed == original
    assert reparsed.order[0].out_hint == 2048
    assert reparsed.order[0].tags == ("reasoning",)


def test_shipped_lanes_yaml_loads_enabled_by_default():
    cfg = load_config()
    ar = cfg.world.adaptive_routing
    assert ar.enabled is True            # go-live 2026-07-08 — ordered bounce loop
    # W30 shipped 4 (3 curated + reserved terminal); EM-323 widened to 5. EM-324
    # rebuilt `order` to the probe-verified clean lanes (dropped command-a-2 the
    # truncator + qwen :free); 5 keeps a 4-lane clean walk + the reserved `auto`.
    assert ar.max_attempts == 5 and ar.allow_paid is False
    assert len(ar.order) >= 1
    # The last order entry is the paid anthropic opt-in (dead last).
    assert ar.order[-1].source == "anthropic" and ar.order[-1].free is False


def test_shipped_lanes_yaml_matches_repo_file():
    """Guard against config drift between the shipped file and the parser."""
    repo_root = Path(__file__).resolve().parents[2]
    lanes_path = repo_root / "config" / "lanes.yaml"
    assert lanes_path.exists()
    block = yaml.safe_load(lanes_path.read_text())["adaptive_routing"]
    assert block["enabled"] is True
    assert block["allow_paid"] is False


# ── Real-config wiring (review finding M3) ─────────────────────────────────
#
# The pre-2026-07-08 incident: config/lanes.yaml's `order:` glob matchers
# (`gpt-oss-120b*`, bare `qwen3-next-80b*`) were authored against IMAGINED
# profile model_ids that never matched the real config/profiles.yaml — ghost
# matchers that silently collapsed the curated priority to config-order with
# `auto` last. Unit tests on synthetic universes (see section A above) can't
# catch this class of bug because they never touch the real, shipped config.
# This test builds the SAME lane universe the live Router builds (from the
# real profiles.yaml), applies the real SortingList (from the real
# lanes.yaml), and asserts every glob that is supposed to hit something DOES.

def test_real_config_glob_matchers_resolve_against_real_profiles():
    """M3: every non-wildcard adaptive_routing.order matcher must resolve to
    >= 1 real lane against the shipped config/profiles.yaml, built the exact
    way the router builds it (Router._build_lane_universe → SortingList).
    A future glob that resolves to zero lanes must fail loudly, naming the
    offending glob, instead of silently degrading to config-order/auto-last."""
    cfg = load_config()
    ar = cfg.world.adaptive_routing
    router = Router(cfg.profiles, cache_enabled=False, adaptive_routing=ar)
    universe = router._build_lane_universe()

    def _matches(source: str, model_glob: str) -> list[Lane]:
        return [
            ln for ln in universe
            if ln.source == source and fnmatch.fnmatch(ln.model_id, model_glob)
        ]

    # (a) the EM-324 pin globs must each resolve to a real, live profile (the
    # deliberate new cast: command-r / llama-fast / gemini-flash-lite added to
    # profiles.yaml alongside the existing gpt-oss-120b / mistral-* lanes).
    named_globs = ["command-r-2", "llama-3.3-70b-fp8-fast", "gemini-3.1-flash-lite"]
    for glob in named_globs:
        matches = _matches("freellmapi", glob)
        assert matches, (
            f"adaptive_routing order glob {glob!r} (source=freellmapi) "
            f"resolved to ZERO lanes against the real config/profiles.yaml "
            f"— ghost matcher (M3)."
        )

    # Generic sweep: ANY non-wildcard FREE order entry that resolves to zero
    # lanes fails loudly, naming the offending glob — not just the three
    # above. The paid anthropic opt-in is checked separately in (b): it is
    # EXPECTED to resolve to zero lanes (no anthropic-adapter profile is
    # configured), so it is excluded from this "must match" sweep.
    for entry in ar.order:
        if entry.model == "*" or entry.source == "anthropic":
            continue
        matches = _matches(entry.source, entry.model)
        assert matches, (
            f"adaptive_routing order entry source={entry.source!r} "
            f"model={entry.model!r} resolved to ZERO lanes against the real "
            f"config/profiles.yaml — ghost matcher (M3)."
        )

    # (b) the paid anthropic/claude-sonnet-5 entry resolves to zero lanes
    # (no anthropic-adapter profile is configured) while allow_paid is false
    # — it is excluded from the sorting list either way.
    anthropic_entries = [e for e in ar.order if e.source == "anthropic"]
    assert anthropic_entries, "expected the paid anthropic opt-in entry in lanes.yaml"
    anthropic_entry = anthropic_entries[0]
    assert anthropic_entry.free is False
    assert ar.allow_paid is False
    assert _matches(anthropic_entry.source, anthropic_entry.model) == []

    sorted_lanes = SortingList(ar.order, allow_paid=ar.allow_paid).apply(universe)
    assert not any(ln.source == "anthropic" for ln in sorted_lanes)


def test_real_config_freellmapi_model_ids_are_plain_catalog_ids():
    """PR#106 C5 (the EM-321/EM-323 class): FreeLLMAPI catalog ids are PLAIN —
    a `vendor/`-prefixed (OpenRouter-style) or `@cf/`-prefixed model_id 404s on
    the proxy, so its lane silently burns a bounce attempt per walk. deepseek-pro
    shipped `deepseek-ai/deepseek-v4-pro` (dead); the catalog id is
    `deepseek-v4-pro`. Pin the invariant for every freellmapi profile."""
    cfg = load_config()
    router = Router(cfg.profiles, cache_enabled=False,
                    adaptive_routing=cfg.world.adaptive_routing)
    for lane in router._build_lane_universe():
        if lane.source != "freellmapi":
            continue
        assert "/" not in lane.model_id and not lane.model_id.startswith("@"), (
            f"profile {lane.profile!r} model_id {lane.model_id!r} is vendor-"
            f"prefixed — not a FreeLLMAPI catalog id (404s on the proxy; C5)."
        )


def test_real_config_registry_excludes_the_command_a_truncator():
    """PR#106 C15: the shipped lanes.yaml `*` sweep re-placed command-a-2 (the
    EM-324 strict-JSON truncator, kept in profiles.yaml only for legacy
    references) at sweep priority. The `exclude` denylist must keep it out of
    the live registry entirely."""
    cfg = load_config()
    ar = cfg.world.adaptive_routing
    assert any(e.model == "command-a-2" for e in ar.exclude), (
        "expected the command-a-2 denylist entry in lanes.yaml adaptive_routing.exclude")
    router = Router(cfg.profiles, cache_enabled=False, adaptive_routing=ar)
    registry_models = [ln["model_id"] for ln in router.lane_registry_snapshot()]
    assert "command-a-2" not in registry_models
    # The denylist bars ONLY the truncator — the sweep still places other lanes.
    assert len(registry_models) > 0

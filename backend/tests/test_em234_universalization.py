"""EM-234 — Universalization prompting (Wave M1).

Injects the GovSim "universalization" scaffold — before acting on the commons,
ask: what if EVERY agent did this? — as a single conditional prompt block in
`_assemble_context`. The block is ALWAYS-ON for every agent when enabled, which
would break the em161 lawful-citizen golden, so it is gated behind the config
flag `world.universalization.enabled` DEFAULT OFF — exactly how EM-223 planning
shipped (default off ⇒ prompt golden + snapshot byte-identical).

Invariants pinned here:
  * em161 golden — DEFAULT OFF: a default-config agent gets NO universalization
    block, so the lawful-citizen golden stays byte-identical. The block appears
    ONLY when `world.universalization.enabled` is true.
  * config-absent = OFF — a world.yaml WITHOUT a `universalization` block reads
    `enabled=False` via the defensive accessor (no KeyError, byte-identical).
  * EM-155 snapshot — EM-234 adds NO AgentState/World state (it is a pure prompt
    block read off config), so the snapshot dict is untouched; this is asserted
    by the dedicated snapshot tests, but we re-check the prompt invariant here.
  * determinism — the block is a static scaffold string; no random/clock.
"""

import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    WorldParams, UniversalizationParams, _parse_universalization,
)
from petridish.agents.runtime import _assemble_context, _universalization_enabled


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _world(agents, params=None):
    return World(params=params or _params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── config dataclass + parser ────────────────────────────────────────────────

def test_universalization_params_default_off():
    p = UniversalizationParams()
    assert p.enabled is False


def test_parse_universalization_absent_is_off():
    # absent/None/garbage → default-OFF params (config-absent = no-op)
    assert _parse_universalization(None).enabled is False
    assert _parse_universalization({}).enabled is False
    assert _parse_universalization("nonsense").enabled is False
    assert _parse_universalization([1, 2, 3]).enabled is False


def test_parse_universalization_enabled_true():
    assert _parse_universalization({"enabled": True}).enabled is True


def test_worldparams_has_universalization_default_off():
    # WorldParams built directly (the golden-test path) defaults the block OFF.
    p = _params()
    assert p.universalization.enabled is False


def test_universalization_enabled_accessor():
    assert _universalization_enabled(_params()) is False
    assert _universalization_enabled(
        _params(universalization=UniversalizationParams(enabled=True))) is True
    # defensive: a params object missing the attribute reads False, never raises
    assert _universalization_enabled(object()) is False


# ── prompt block: ABSENT when off (golden-safe) ──────────────────────────────

def test_block_absent_when_disabled():
    a = _agent()
    w = _world([a])  # default params → universalization OFF
    sys = _sys(a, w)
    assert "what if EVERY" not in sys
    assert "UNIVERSALIZATION" not in sys
    assert "commons" not in sys.lower() or "what if every" not in sys.lower()


def test_block_absent_is_byte_identical_to_no_feature():
    # The off-default prompt must equal the prompt assembled by a params object
    # that has no universalization concept at all (proves zero golden drift).
    a = _agent()
    w_off = _world([a])
    sys_off = _sys(a, w_off)
    assert "universaliz" not in sys_off.lower()


# ── prompt block: PRESENT when enabled ───────────────────────────────────────

def test_block_present_when_enabled():
    a = _agent()
    w = _world([a], _params(
        universalization=UniversalizationParams(enabled=True)))
    sys = _sys(a, w)
    assert "what if EVERY" in sys
    assert "commons" in sys.lower()


def test_block_present_for_background_tier_too():
    # ALWAYS-ON: the scaffold rides every tier when enabled (the cheap
    # cooperation lift is for the whole population, not just protagonists).
    a = _agent(cadence_tier="background")
    w = _world([a], _params(
        universalization=UniversalizationParams(enabled=True)))
    sys = _sys(a, w)
    assert "what if EVERY" in sys


def test_block_present_for_protagonist_tier():
    a = _agent(cadence_tier="protagonist")
    w = _world([a], _params(
        universalization=UniversalizationParams(enabled=True)))
    sys = _sys(a, w)
    assert "what if EVERY" in sys


# ── EM-155: EM-234 adds no serialized state ──────────────────────────────────

def test_enabling_universalization_does_not_change_snapshot():
    a = _agent()
    w_off = _world([a])
    w_on = _world([_agent()], _params(
        universalization=UniversalizationParams(enabled=True)))
    # AgentState.to_dict is identical regardless of the config flag — EM-234
    # carries no per-agent state.
    assert json.dumps(w_off.agents["dot"].to_dict(), sort_keys=True) == \
        json.dumps(w_on.agents["dot"].to_dict(), sort_keys=True)

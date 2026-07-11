"""EM-269 (F2) — settlements.enabled default OFF ⇒ complete no-op: default
params keep the flag off, the snapshot gains no key, the prompt gains no line
or menu entry, and the verb rejects cleanly (byte-identical pre-EM-269)."""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (WorldParams, SettlementParams,
                                     _parse_settlements)
from petridish.agents.runtime import _assemble_context


def _params(settlements=None):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    if settlements is not None:
        p.settlements = settlements
    return p


def _world(params=None):
    return World(
        params=params or _params(),
        places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
        agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                           location="plaza", energy=80.0, credits=20)])


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── config: the flag defaults OFF and parses defensively ──────────────────────

def test_default_params_ship_disabled():
    assert SettlementParams().enabled is False
    assert WorldParams(tick_interval_seconds=0.5, turns_per_day=1,
                       energy_decay_per_turn=0.0, starting_energy=1.0,
                       starting_credits=1,
                       snapshot_interval_ticks=1).settlements.enabled is False
    assert _world()._settlements_enabled() is False


def test_parse_settlements_defensive():
    assert _parse_settlements(None) == SettlementParams()
    assert _parse_settlements({}) == SettlementParams()
    assert _parse_settlements("junk") == SettlementParams()
    assert _parse_settlements({"enabled": True}).enabled is True
    assert _parse_settlements({"enabled": 0}).enabled is False


# ── flag OFF ⇒ byte-identical world surface ───────────────────────────────────

def test_flag_off_snapshot_is_byte_identical():
    # A default world's snapshot must not know settlements exist — even after a
    # (rejected) found attempt. Same key set, same bytes, as a fresh world.
    w = _world()
    baseline = json.dumps(w.to_snapshot({}), sort_keys=True, default=str)
    evt = w.action_found_settlement(w.agents["a"], "Nope")
    assert evt["kind"] == "parse_failure"            # rejected with guidance
    after = json.dumps(w.to_snapshot({}), sort_keys=True, default=str)
    assert baseline == after
    assert "settlements" not in w.to_snapshot({})


def test_flag_off_prompt_is_byte_identical():
    w = _world()
    sys = _sys(w.agents["a"], w)
    assert "SETTLEMENTS" not in sys                  # no perception block
    assert "found_settlement" not in sys             # no menu entry


# ── flag ON ⇒ the surface appears (the same world, one flag away) ─────────────

def test_flag_on_offers_the_verb_on_unclaimed_ground():
    w = _world(_params(SettlementParams(enabled=True)))
    sys = _sys(w.agents["a"], w)
    assert "found_settlement (name?)" in sys         # menu entry
    assert "SETTLEMENTS" not in sys                  # no block until one exists


def test_flag_on_renders_the_settlement_line_and_gates_claimed_ground():
    w = _world(_params(SettlementParams(enabled=True)))
    w.action_found_settlement(w.agents["a"], "River Camp")
    sys = _sys(w.agents["a"], w)
    assert "=== 🏘 SETTLEMENTS ===" in sys
    assert "Your settlement: River Camp (1 member)" in sys
    # standing on claimed ground ⇒ the verb is NOT offered (menu == resolution)
    assert "found_settlement (name?)" not in sys

"""EM-280 (W29) — the layout-governance effects the propose_rule gate ALREADY
accepts (demolish_road / set_car_policy / adopt_master_plan, plus set_zone_rule
behind GRAPH_ZONES_ENABLED) must be surfaced on the propose_rule menu, each with a
concrete arg and gated exactly as the validator gates it (EM-108). Before, they
appeared on no prompt surface, so an agent could only find them by burning a turn
on a rejection.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents import runtime as rt
from petridish.agents.runtime import _assemble_context


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world():
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance")]
    agent = AgentState(id="dot", name="Dot", personality="civic", profile="mock",
                       location="townhall", energy=80.0, credits=20)
    return agent, World(params=_params(), places=places, agents=[agent])


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _propose_line(sys: str) -> str:
    return next(l for l in sys.split("\n") if l.strip().startswith("propose_rule"))


# ── the live layout effects are surfaced with concrete args ───────────────────

def test_live_layout_effects_on_propose_menu():
    agent, w = _world()
    line = _propose_line(_sys(agent, w))
    assert "demolish_road" in line
    assert "set_car_policy" in line
    assert "adopt_master_plan" in line
    # Concrete demolish_road target (a real edge id) so menu/resolution agree.
    assert "demolish_road needs target=<a road id, e.g. e:" in line
    assert "policy=cars|pedestrian|mixed" in line
    assert "pentagon|radial|ring|grid" in line


# ── adopt_master_plan is suppressed while a morph is already running ───────────

def test_adopt_master_plan_hidden_when_a_morph_is_active():
    agent, w = _world()
    w.master_plan = {"kind": "pentagon", "seed": 1}   # one-active guard
    line = _propose_line(_sys(agent, w))
    assert "adopt_master_plan" not in line
    # The other live effects are unaffected.
    assert "demolish_road" in line and "set_car_policy" in line


# ── set_zone_rule is flag-gated (dormant by default, appears when enabled) ─────

def test_set_zone_rule_absent_when_flag_off(monkeypatch):
    # Zones now ship ON by default (feat/organic-world-regen); pin OFF to prove the
    # dormant path still omits set_zone_rule from the propose menu.
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", False)
    agent, w = _world()
    assert not rt.GRAPH_ZONES_ENABLED           # pinned off
    assert "set_zone_rule" not in _propose_line(_sys(agent, w))


def test_set_zone_rule_offered_when_zones_enabled(monkeypatch):
    monkeypatch.setattr(rt, "GRAPH_ZONES_ENABLED", True)
    agent, w = _world()                          # default grid has 25 real faces
    line = _propose_line(_sys(agent, w))
    assert "set_zone_rule" in line
    assert "hint=residential|market|civic|open" in line

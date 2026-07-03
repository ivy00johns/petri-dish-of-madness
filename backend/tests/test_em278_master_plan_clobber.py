"""EM-278 — a ratified master plan must not clobber an in-progress morph.

The one-active invariant is enforced at PROPOSE time, but a god_adopt_master_plan
(or a second ratified vote) can start a morph between propose and the
threshold-crossing vote. `_on_rule_activated` set self.master_plan
unconditionally, silently abandoning the running morph (its target is re-derived
from self.master_plan each tick). Activation now re-checks: if a plan is already
active, the ratified one yields (the vote still "passed").
"""

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world():
    a = AgentState(id="a", name="Ann", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=[a])


def _adopt_rule(kind):
    return RuleState(id="r1", effect="adopt_master_plan", text="morph",
                     proposer_id="a", status="proposed",
                     payload={"kind": kind, "params": {}})


def test_ratified_plan_yields_to_active_morph():
    w = _world()
    # A pentagon morph is already in progress (e.g. from god_adopt_master_plan).
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}

    w._on_rule_activated(_adopt_rule("radial"))

    # The running morph is untouched — NOT overwritten by the late-landing vote.
    assert w.master_plan is not None
    assert w.master_plan["kind"] == "pentagon"
    kinds = {e["kind"] for e in w.drain_spawn_events()}
    assert "master_plan_dropped" in kinds
    assert "master_plan_adopted" not in kinds


def test_ratified_plan_starts_morph_when_none_active():
    w = _world()
    w.master_plan = None

    w._on_rule_activated(_adopt_rule("radial"))

    assert w.master_plan is not None and w.master_plan["kind"] == "radial"
    kinds = {e["kind"] for e in w.drain_spawn_events()}
    assert "master_plan_adopted" in kinds

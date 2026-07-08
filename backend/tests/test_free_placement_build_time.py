"""EM-268 F1 — a build stores a world-frame position when the flag is on."""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.placement import place_all
from petridish.config.loader import WorldParams
import petridish.agents.runtime as rt


def _world():
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    return World(params=p,
                 places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
                 agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                    location="plaza", energy=80.0, credits=20)])


def _build(w):
    # EM-268 §3: the real build reflex is action_propose_project (there is NO
    # propose_building). It mints a Building(status=planned) and adds it — the
    # site where the F1 build-time position hook fires.
    a = w.agents["a"]
    w.action_propose_project(a, name="Hall", kind="workshop", funds_required=0,
                             place="plaza")


def test_flag_on_stores_position(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    _build(w)
    b = next(iter(w.buildings.values()))
    assert b.position is not None
    # matches the pure fn over the full set (anchor = world origin)
    assert b.position == place_all(w.buildings.values(), (0.0, 0.0), w.city_seed)[b.id]


def test_flag_off_leaves_position_none(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", False)
    w = _world()
    _build(w)
    assert next(iter(w.buildings.values())).position is None   # byte-identical

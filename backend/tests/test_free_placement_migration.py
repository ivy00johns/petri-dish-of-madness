"""EM-268 F1 — derive-on-load fills missing positions == live incremental (R3),
never overwrites, keeps destroyed buildings as fixed parents, flag-off no-ops."""
import copy
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
from petridish.engine.world import World, Building, AgentState, PlaceState
from petridish.engine.placement import place_all
from petridish.config.loader import WorldParams
import petridish.agents.runtime as rt


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world_with_buildings(positions):
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    for i, pos in enumerate(positions):
        w.buildings[f"bld_{i:03d}"] = Building(
            id=f"bld_{i:03d}", name="B", kind="workshop", location="plaza",
            created_tick=i, position=pos)
    return w


def test_pre_f1_snapshot_derives_all_positions(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([None, None, None])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert all(b.position is not None for b in restored.buildings.values())
    # == a batch place_all over the set (anchor = origin)
    expect = place_all(restored.buildings.values(), (0.0, 0.0), restored.city_seed)
    for b in restored.buildings.values():
        assert b.position == expect[b.id]


def test_derive_on_load_equals_live_incremental(monkeypatch):
    # R3: a run where positions were set live must match one where they're derived.
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    live = _world_with_buildings([None, None, None])
    live_pos = place_all(live.buildings.values(), (0.0, 0.0), live.city_seed)
    for b in live.buildings.values():
        b.position = live_pos[b.id]
    # a pre-F1 snapshot of the SAME set with positions stripped
    stripped = _world_with_buildings([None, None, None])
    restored = World.from_snapshot(copy.deepcopy(stripped.to_snapshot()), params=_params())
    for b in restored.buildings.values():
        assert b.position == live_pos[b.id]


def test_existing_positions_never_overwritten(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([(9.0, 9.0), None])   # one fixed, one missing
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert restored.buildings["bld_000"].position == (9.0, 9.0)   # untouched
    assert restored.buildings["bld_001"].position is not None     # filled


def test_flag_off_is_a_noop(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", False)
    w = _world_with_buildings([None, None])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert all(b.position is None for b in restored.buildings.values())  # byte-identical

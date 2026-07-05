"""EM-268 F1 — Building.position rides the snapshot only when set (byte-identical)."""
import copy
from petridish.engine.world import Building, World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def test_position_serialized_only_when_set():
    b = Building(id="bld_x", name="Hall", kind="workshop", location="plaza")
    assert "position" not in b.to_dict()          # unset ⇒ omitted (byte-identical)
    b.position = (3.5, -2.0)
    assert b.to_dict()["position"] == [3.5, -2.0]  # set ⇒ list, world frame


def test_position_round_trips_through_snapshot():
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    b = Building(id="bld_x", name="Hall", kind="workshop", location="plaza",
                 position=(3.5, -2.0))
    w.buildings[b.id] = b
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert restored.buildings["bld_x"].position == (3.5, -2.0)


def test_old_snapshot_without_position_restores_none():
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    w.buildings["bld_x"] = Building(id="bld_x", name="Hall", kind="workshop",
                                    location="plaza")
    snap = w.to_snapshot()
    for d in snap.get("buildings", []):
        d.pop("position", None)                    # a pre-F1 snapshot
    restored = World.from_snapshot(snap, params=_params())
    assert restored.buildings["bld_x"].position is None   # deterministic default

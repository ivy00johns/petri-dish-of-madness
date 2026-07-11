"""EM-268 F1 — legacy (pre-F1) restore under the SHIPPED flag-ON config.

The user RATIFIED derive-on-load (2026-07-09): restoring a position-less
(pre-F1) snapshot with FREE_PLACEMENT_ENABLED=True derives a world-frame
position for every building — the live run.sqlite city re-places on next load,
intentionally. PR #82 pinned the surviving byte-identity guards to flag-OFF,
so this exact flag-ON behavior was asserted NOWHERE. This file locks it in:

  1. legacy restore derives every position == the deterministic place_all batch;
  2. an all-positioned (post-F1) snapshot round-trips byte-identically under
     flag-ON (migration is a no-op when nothing is None) — the integration-level
     guarantee #82 dropped;
  3. a mixed snapshot keeps stored positions VERBATIM and fills the missing ones
     (with the documented EM-303 caveat below);
  4. restoring the same legacy snapshot twice is identical (pure fn of the set).

Style-matched to the sibling test_free_placement_*.py files: same _params /
_world_with_buildings helpers, explicit monkeypatch of the runtime flag. The
migration reads petridish.agents.runtime.FREE_PLACEMENT_ENABLED at call time
(a local import inside from_snapshot), so monkeypatching rt.* takes effect.
"""
import copy
import json

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
    """A World with one place, one agent, and len(positions) buildings whose
    `position` is each entry (None ⇒ a pre-F1, position-less building)."""
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    for i, pos in enumerate(positions):
        w.buildings[f"bld_{i:03d}"] = Building(
            id=f"bld_{i:03d}", name="B", kind="workshop", location="plaza",
            created_tick=i, position=pos)
    return w


def test_legacy_restore_derives_all_positions(monkeypatch):
    # (1) A pre-F1 snapshot (every building position-less) restored under the
    # shipped flag-ON config gains a position for EVERY building, and each equals
    # the deterministic place_all batch (anchor = origin, keyed on city_seed).
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([None, None, None, None, None])
    snap = copy.deepcopy(w.to_snapshot())
    # Confirm the snapshot is genuinely pre-F1: no building carries a position.
    assert all("position" not in d for d in snap["buildings"])
    restored = World.from_snapshot(snap, params=_params())
    assert all(b.position is not None for b in restored.buildings.values())
    expect = place_all(restored.buildings.values(), (0.0, 0.0), restored.city_seed)
    for b in restored.buildings.values():
        assert b.position == expect[b.id]


def test_post_f1_round_trip_is_byte_identical(monkeypatch):
    # (2) An all-positioned (post-F1) snapshot restored under flag-ON re-serializes
    # byte-identically: migration is a genuine no-op when nothing is None (the
    # `any(position is None)` guard is False ⇒ place_all is never called). These
    # stored positions are NOT what place_all would derive, proving no overwrite.
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([(1.0, 2.0), (3.0, 4.0), (-5.0, 6.0)])
    snap_before = copy.deepcopy(w.to_snapshot())
    restored = World.from_snapshot(copy.deepcopy(snap_before), params=_params())
    snap_after = restored.to_snapshot()
    # Positions are untouched...
    assert restored.buildings["bld_000"].position == (1.0, 2.0)
    assert restored.buildings["bld_001"].position == (3.0, 4.0)
    assert restored.buildings["bld_002"].position == (-5.0, 6.0)
    # ...and the serialized building shape is byte-identical across the round-trip.
    assert snap_after["buildings"] == snap_before["buildings"]
    assert (json.dumps(snap_after["buildings"])
            == json.dumps(snap_before["buildings"]))


def test_mixed_snapshot_keeps_stored_and_fills_missing(monkeypatch):
    # (3) A mixed snapshot: two buildings carry stored positions, one is pre-F1
    # (position-less). Under flag-ON the stored ones restore VERBATIM and the
    # missing one gains a deterministic position.
    #
    # KNOWN CAVEAT (EM-303): the migration passes the FULL building set to
    # place_all, which RECOMPUTES a position for every building from the seed and
    # keeps only the recomputed values for the None ones. So the filled building
    # clusters around the RECOMPUTED parent positions, NOT the stored ones. We
    # assert the CURRENT ACTUAL behavior (== place_all's recomputed value for that
    # id); we do NOT "fix" the algorithm to attach to stored parents here.
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    # Stored positions deliberately far from anything place_all would produce, so
    # "verbatim" is unambiguous (place_all stays within a few units of origin).
    w = _world_with_buildings([(100.0, 100.0), None, (-100.0, -80.0)])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    # Stored positions survive untouched.
    assert restored.buildings["bld_000"].position == (100.0, 100.0)
    assert restored.buildings["bld_002"].position == (-100.0, -80.0)
    # The missing one is filled with place_all's recomputed value for its id
    # (the EM-303 caveat: recomputed, not stored-parent-relative).
    recomputed = place_all(restored.buildings.values(), (0.0, 0.0), restored.city_seed)
    assert restored.buildings["bld_001"].position is not None
    assert restored.buildings["bld_001"].position == recomputed["bld_001"]


def test_legacy_restore_is_deterministic(monkeypatch):
    # (4) Restoring the same legacy snapshot twice yields identical positions both
    # times — placement is a pure fn of (building set, anchor, city_seed).
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([None, None, None, None])
    snap = copy.deepcopy(w.to_snapshot())
    first = World.from_snapshot(copy.deepcopy(snap), params=_params())
    second = World.from_snapshot(copy.deepcopy(snap), params=_params())
    for bid in first.buildings:
        assert first.buildings[bid].position is not None
        assert first.buildings[bid].position == second.buildings[bid].position

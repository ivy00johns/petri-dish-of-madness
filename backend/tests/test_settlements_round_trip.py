"""EM-269 (F2) — settlements ride the snapshot only when non-empty, restore
verbatim, and round-trip byte-identically (the factions pattern)."""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SettlementParams


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


def _world(enabled=True):
    return World(
        params=_params(enabled),
        places=[
            PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
            PlaceState(id="ridge", name="Ridge", x=900, y=900, kind="social"),
        ],
        agents=[
            AgentState(id="a", name="Ann", personality="", profile="mock",
                       location="ridge", energy=80.0, credits=20),
            AgentState(id="b", name="Bob", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20),
        ])


def test_settlement_free_world_has_no_snapshot_key():
    w = _world()
    assert "settlements" not in w.to_snapshot({})    # only-when-non-empty


def test_snapshot_round_trip_is_byte_identical():
    w = _world()
    w.action_found_settlement(w.agents["a"], "River Camp")
    w.action_found_settlement(w.agents["b"], "")     # seeded pool name
    snap = w.to_snapshot({})
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    again = restored.to_snapshot({})
    # Real persistence dumps WITHOUT sort_keys (loop._save_snapshot), so the
    # raw dump — key order AND settlement-id order included — is the byte
    # contract. sort_keys=True would mask an id-order regression (e.g. a
    # from_snapshot that re-sorts settlements) that changes the stored bytes.
    assert json.dumps(snap["settlements"]) == json.dumps(again["settlements"])


def test_restore_preserves_identity_and_membership():
    w = _world()
    evt = w.action_found_settlement(w.agents["a"], "River Camp")
    sid = evt["payload"]["settlement_id"]
    restored = World.from_snapshot(w.to_snapshot({}), params=_params())
    assert set(restored.settlements) == {sid}        # id continuity (fork-safe)
    s = restored.settlements[sid]
    assert s["name"] == "River Camp"
    assert s["center"] == w.settlements[sid]["center"]   # world frame, verbatim
    assert isinstance(s["center"], tuple)                # internal shape restored
    assert s["founder_id"] == "a"
    assert s["members"] == ["a"]
    assert restored.settlement_of("a") == sid


def test_pre_em269_snapshot_restores_empty():
    w = _world()
    snap = w.to_snapshot({})
    assert "settlements" not in snap                 # a genuine pre-EM-269 shape
    restored = World.from_snapshot(snap, params=_params())
    assert restored.settlements == {}                # absent ⇒ {} — no crash


def test_malformed_entries_restore_defensively():
    w = _world()
    snap = w.to_snapshot({})
    snap["settlements"] = {
        "stl_ok": {"name": "Kept", "center": [1.5, -2.5],
                   "founded_tick": 3, "founder_id": "a", "members": ["a"]},
        "stl_sparse": {},                            # every field defaulted
        "": {"name": "dropped"},                     # empty id dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert set(restored.settlements) == {"stl_ok", "stl_sparse"}
    assert restored.settlements["stl_ok"]["center"] == (1.5, -2.5)
    sparse = restored.settlements["stl_sparse"]
    assert sparse["center"] == (0.0, 0.0) and sparse["members"] == []

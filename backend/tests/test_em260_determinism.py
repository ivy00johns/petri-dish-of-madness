# backend/tests/test_em260_determinism.py
"""EM-260 — the Religion-plumbing determinism golden (EM-155).

With faith disabled (the default) a world is BYTE-IDENTICAL to pre-EM-260: no
faiths snapshot key, no faith_id/devotion agent keys, and the default snapshot
round-trips byte-identically. Enabling the flag ALONE (no faith minted) changes
nothing at rest — the flag is a pure no-op until the EM-261+ verbs mint one.
mint_faith is fully SEEDED (id + invented name/deity/tenets), so two identical
worlds mint byte-identical faiths; and a POPULATED faith world (a minted faith
with members + a devout, faith-bound agent) round-trips byte-identically, so a
fork/replay resumes the exact same religion state.
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, FaithParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)


def _world(faith: bool = False) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    w = World(params=_params(),
              agents=[_a("ada"), _a("bram"), _a("dot"), _a("eli")],
              places=places)
    if faith:
        w.params.faith = {"enabled": True}
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── default world: inert + byte-identical (faith disabled by default) ─────────

def test_default_world_snapshot_has_no_faith_keys():
    snap = _world().to_snapshot()
    assert "faiths" not in snap
    for a in snap.get("agents", []):
        assert "faith_id" not in a and "devotion" not in a


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_enabling_the_flag_alone_is_a_pure_no_op():
    """The load-bearing golden: faith.enabled=true WITHOUT a minted faith leaves
    the snapshot byte-identical to the default (flag-OFF) world — the flag adds
    no faiths key, no agent faith fields, nothing until an EM-261+ verb mints."""
    base = _dumps(_world(faith=False).to_snapshot())
    flagged = _dumps(_world(faith=True).to_snapshot())
    assert flagged == base


def test_absent_faith_block_behaves_like_defaults():
    """An ABSENT world.faith block (params.faith is None — a pre-EM-260 world)
    is inert exactly like the FaithParams() defaults: gate OFF, snapshot clean."""
    w = _world()
    w.params.faith = None
    assert w.faith_enabled() is False
    assert w.faith_enabled() == _world().faith_enabled()   # == FaithParams()
    assert "faiths" not in w.to_snapshot()


# ── mint_faith determinism (id + invented name/deity/tenets all seeded) ───────

def test_mint_faith_is_byte_identical_across_two_worlds():
    w1, w2 = _world(faith=True), _world(faith=True)
    w1.tick = w2.tick = 17
    f1 = w1.mint_faith("ada")
    f2 = w2.mint_faith("ada")
    assert f1.id == f2.id
    assert f1.name == f2.name and f1.deity == f2.deity
    assert f1.tenets == f2.tenets
    assert _dumps(w1.to_snapshot()) == _dumps(w2.to_snapshot())


# ── populated faith world: byte-identical round-trip ──────────────────────────

def _faith_world() -> World:
    w = _world(faith=True)
    w.tick = 11
    f = w.mint_faith("ada")
    f.members = ["ada", "bram"]
    f.meme_id = "mem_faith1"
    f.temple_id = "b_temple"
    w.agents["ada"].faith_id = f.id
    w.agents["ada"].devotion = 65
    w.agents["bram"].faith_id = f.id
    w.agents["bram"].devotion = 30
    # A schismed child faith with lineage back to the root.
    child = w.mint_faith("bram", parent_id=f.id)
    child.members = ["bram"]
    return w


def test_populated_faith_world_round_trips_byte_identical():
    w = _faith_world()
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_faith_world_survives_a_second_hop():
    w = _faith_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


def test_restored_faith_world_preserves_membership_and_devotion():
    w = _faith_world()
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    (root_id,) = [fid for fid, f in restored.faiths.items() if f.parent_id is None]
    root = restored.faiths[root_id]
    assert sorted(root.members) == ["ada", "bram"]
    assert restored.agents["ada"].faith_id == root_id
    assert restored.agents["ada"].devotion == 65
    assert restored.agents["bram"].devotion == 30
    child = next(f for f in restored.faiths.values() if f.parent_id is not None)
    assert child.parent_id == root_id and child.members == ["bram"]

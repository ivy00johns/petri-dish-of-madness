"""EM-268 F1 — flag-ON determinism gate (EM-155).

The default path is flag-OFF (proven byte-identical elsewhere). THIS file exercises
the flag-ON envelope: with FREE_PLACEMENT_ENABLED forced on, stored world-frame
positions ride snapshot/replay/fork byte-identically, and a build that continues
after a fork lands byte-identically to the same build on the unforked world
(fork == continuous). The two teeth-tests prove the golden is NON-vacuous — it
would catch a canonical-order or seed regression, not pass trivially.
"""
import copy
import uuid as _uuidlib
from dataclasses import dataclass

# NOTE: import engine.world BEFORE agents.runtime — importing runtime first
# triggers the engine↔agents circular import at collection (the codebase's
# documented "world before runtime" test rule).
import petridish.engine.world as world_mod
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.placement import place_all
import petridish.agents.runtime as rt
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _det_uuid():
    """Deterministic uuid4 stand-in (top-32-bit counter ⇒ distinct str[:8])."""
    counter = {"n": 0}

    def _f():
        counter["n"] += 1
        return _uuidlib.UUID(int=counter["n"] << 96)

    return _f


def _world():
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
                 agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                    location="plaza", energy=80.0, credits=20)])


def _build(w, n):
    a = w.agents["a"]
    for i in range(n):
        w.action_propose_project(a, f"B{i}", "workshop", 0, place="plaza")


def _positions(w):
    return {bid: b.position for bid, b in sorted(w.buildings.items())}


def _newest(w):
    return max(w.buildings.values(), key=lambda b: (b.created_tick, b.id))


def test_replay_round_trip_preserves_positions(monkeypatch):
    """Stored positions ride to_snapshot/from_snapshot verbatim (byte-identical)."""
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid())
    w = _world()
    _build(w, 6)
    before = _positions(w)
    assert all(p is not None for p in before.values())
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert _positions(restored) == before


def test_fork_continuation_byte_identical(monkeypatch):
    """Fork == continuous: a build that continues after a snapshot round-trip lands
    byte-identically to the same build on the unforked world. Reset the uuid stream
    before each continuation so both mint the SAME next id ('same subsequent input');
    resetting AFTER from_snapshot makes any construction uuid consumption irrelevant."""
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid())
    w1 = _world()
    _build(w1, 4)
    w2 = World.from_snapshot(copy.deepcopy(w1.to_snapshot()), params=_params())
    assert _positions(w2) == _positions(w1)            # restore is exact

    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid())                 # w1's next build → bld_00000001
    _build(w1, 1)
    monkeypatch.setattr(world_mod.uuid, "uuid4", _det_uuid())                 # w2's next build → SAME id
    _build(w2, 1)
    n1, n2 = _newest(w1), _newest(w2)
    assert n1.id == n2.id                              # same subsequent input
    assert n1.position is not None
    assert n1.position == n2.position                  # fork+resume == continuous


def test_teeth_created_tick_order_changes_positions():
    """NON-vacuous golden: canonical (created_tick, id) order is load-bearing.
    Reverse created_tick ⇒ different accretion sequence ⇒ different positions.
    If this ever passed with equal dicts, the determinism assertions above would
    be catching nothing."""
    @dataclass
    class B:
        id: str
        created_tick: int

    ids = [f"bld_{i:03d}" for i in range(12)]
    forward = place_all([B(id=i, created_tick=t) for t, i in enumerate(ids)],
                        (0.0, 0.0), 1337)
    rev = place_all([B(id=i, created_tick=len(ids) - t) for t, i in enumerate(ids)],
                    (0.0, 0.0), 1337)
    assert forward != rev


def test_teeth_seed_sensitive():
    """NON-vacuous golden: positions genuinely depend on city_seed (a fork that
    accidentally used a different seed would be caught)."""
    @dataclass
    class B:
        id: str
        created_tick: int

    s = [B(id=f"bld_{i:03d}", created_tick=i) for i in range(12)]
    assert place_all(s, (0.0, 0.0), 1337) != place_all(s, (0.0, 0.0), 9999)

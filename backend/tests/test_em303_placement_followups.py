"""EM-303 — F1 free-placement follow-ups (on top of the ratified derive-on-load).

(a) world-extent sprawl clamp: MAX_EXTENT caps accretion; out-of-extent growth
    degrades gracefully (densifies near the center) instead of erring or leaving
    the world. Stored history is NEVER moved by the clamp.
(b) STORED-WINS mixed-snapshot precedence: stored positions are event-sourced
    truth; recompute only fills absences, clustered around the STORED town.
(c) batch-vs-incremental ordering stability under production uuid4 ids: a
    same-tick build whose uuid4 id sorts BEFORE an existing one must not move
    it (append-only), must respect its STORED spacing, and place_all over the
    stored set is a fixed point.
"""
import copy
import math

# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
from petridish.engine.world import World, Building, AgentState, PlaceState
import petridish.engine.placement as placement
from petridish.engine.placement import (
    MIN_SPACING, place_all, place_one,
)
from petridish.config.loader import WorldParams
import petridish.agents.runtime as rt

ANCHOR = (0.0, 0.0)
SEED = 1337


class B:
    """Pure-fn test double (the accretion-test idiom); optional stored position."""

    def __init__(self, id: str, created_tick: int, position=None):
        self.id = id
        self.created_tick = created_tick
        self.position = position


def _set(n, start_tick=0):
    return [B(id=f"bld_{i:03d}", created_tick=start_tick + i) for i in range(n)]


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


# ──────────────────────────────────────────────────────────────────────────────
# (a) world-extent sprawl clamp
# ──────────────────────────────────────────────────────────────────────────────

def test_extent_clamp_keeps_every_derived_position_inside(monkeypatch):
    # A tiny extent forces the clamp on almost every accretion step: every
    # derived position must stay inside, with no error raised (densify, don't die).
    monkeypatch.setattr(placement, "MAX_EXTENT", 6.0)
    out = place_all(_set(80), ANCHOR, SEED)
    assert len(out) == 80
    for x, z in out.values():
        assert math.hypot(x, z) <= 6.0 + 1e-9


def test_extent_clamp_densifies_rather_than_erroring(monkeypatch):
    # Far more buildings than MIN_SPACING-clear slots in the disc (area budget
    # ~ pi*4^2 / 1.6^2 ≈ 20): the overflow accepts tighter packing near the
    # center — graceful degradation, every building still placed, all inside.
    monkeypatch.setattr(placement, "MAX_EXTENT", 4.0)
    out = place_all(_set(120), ANCHOR, SEED)
    assert len(out) == 120
    assert all(math.hypot(x, z) <= 4.0 + 1e-9 for x, z in out.values())


def test_extent_clamp_is_deterministic(monkeypatch):
    monkeypatch.setattr(placement, "MAX_EXTENT", 5.0)
    a = place_all(_set(60), ANCHOR, SEED)
    b = place_all(_set(60), ANCHOR, SEED)
    assert a == b


def test_extent_clamp_never_moves_stored_history(monkeypatch):
    # STORED-WINS beats the clamp: a stored position beyond the extent is truth
    # (event-sourced) — the clamp shapes new growth only.
    monkeypatch.setattr(placement, "MAX_EXTENT", 5.0)
    fixed = B("bld_far", 0, position=(20.0, 20.0))
    new = B("bld_new", 1)
    out = place_all([fixed, new], ANCHOR, SEED)
    assert out["bld_far"] == (20.0, 20.0)
    assert math.hypot(*out["bld_new"]) <= 5.0 + 1e-9


def test_extent_none_is_the_unclamped_pre_em303_behavior(monkeypatch):
    # None ⇒ byte-identical pure accretion (the pre-clamp golden path).
    monkeypatch.setattr(placement, "MAX_EXTENT", None)
    baseline = place_all(_set(40), ANCHOR, SEED)
    monkeypatch.setattr(placement, "MAX_EXTENT", 32.5)
    shipped = place_all(_set(40), ANCHOR, SEED)
    # 40 accreted buildings never near the world edge ⇒ shipped default no-ops.
    assert shipped == baseline


# ──────────────────────────────────────────────────────────────────────────────
# (b) STORED-WINS mixed-snapshot precedence
# ──────────────────────────────────────────────────────────────────────────────

def test_mixed_set_missing_clusters_around_the_stored_town():
    # The stored town sits FAR from where a from-scratch recompute would put it.
    # The absent building must attach near the STORED cluster, not the phantom.
    stored_cluster = [B(f"bld_s{i}", i, position=(18.0 + 0.2 * i, 18.0)) for i in range(4)]
    missing = B("bld_zzz", 10)   # sorts last; position absent
    out = place_all(stored_cluster + [missing], ANCHOR, SEED)
    for b in stored_cluster:
        assert out[b.id] == b.position          # stored is truth, verbatim
    mx, mz = out["bld_zzz"]
    d_stored = min(math.dist((mx, mz), b.position) for b in stored_cluster)
    # a from-scratch recompute of the same ids clusters near the anchor instead
    phantom = place_all([B(b.id, b.created_tick) for b in stored_cluster], ANCHOR, SEED)
    d_phantom = min(math.dist((mx, mz), p) for p in phantom.values())
    assert d_stored < d_phantom
    assert d_stored <= NEIGHBOR_R_BOUND         # genuinely attached to the town


# accretion attaches within MIN_SPACING*2 of a parent, then spirals: a loose
# bound that still proves "near the stored town, not near the origin phantom".
NEIGHBOR_R_BOUND = 8.0


def test_mixed_snapshot_restore_fills_absences_around_stored_parents(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([(15.0, 15.0), (16.8, 15.2), None])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert restored.buildings["bld_000"].position == (15.0, 15.0)
    assert restored.buildings["bld_001"].position == (16.8, 15.2)
    filled = restored.buildings["bld_002"].position
    assert filled is not None
    assert math.dist(filled, (15.0, 15.0)) <= NEIGHBOR_R_BOUND   # stored parent won
    # and it respects the stored town's spacing
    assert math.dist(filled, (15.0, 15.0)) >= MIN_SPACING - 1e-9
    assert math.dist(filled, (16.8, 15.2)) >= MIN_SPACING - 1e-9


def test_all_absent_set_keeps_the_pre_em303_pure_path():
    # No stored positions anywhere ⇒ the ratified pre-F1 derive is unchanged:
    # position-carrying doubles with position=None equal the attribute-less
    # accretion-test doubles.
    from dataclasses import dataclass

    @dataclass
    class Bare:
        id: str
        created_tick: int

    bare = place_all([Bare(id=f"bld_{i:03d}", created_tick=i) for i in range(12)],
                     ANCHOR, SEED)
    nones = place_all(_set(12), ANCHOR, SEED)
    assert bare == nones


def test_place_all_is_a_fixed_point_over_a_stored_set():
    # Batch over an already-placed town returns the stored map verbatim —
    # derive-on-load can never reshuffle a fully-positioned snapshot.
    derived = place_all(_set(15), ANCHOR, SEED)
    stored = [B(b.id, b.created_tick, position=derived[b.id]) for b in _set(15)]
    assert place_all(stored, ANCHOR, SEED) == derived


# ──────────────────────────────────────────────────────────────────────────────
# (c) ordering stability under production uuid4 ids
# ──────────────────────────────────────────────────────────────────────────────

# uuid4[:8]-shaped ids, deliberately chosen so creation order ≠ sort order
# WITHIN a shared tick (the case seeded test ids never exercise).
_UUID_BUILDS = [
    ("bld_f00dcafe", 5),   # built 1st, sorts LAST of tick 5
    ("bld_0badbeef", 5),   # built 2nd, sorts FIRST of tick 5
    ("bld_9e51dead", 5),   # built 3rd, sorts middle
    ("bld_00c0ffee", 7),
    ("bld_ffee4a2b", 7),
]


def _incremental_uuid_run():
    """Simulate the live flag-ON run: each build gets place_one over the current
    set (earlier builds carrying their STORED positions), then stores it."""
    built: list[B] = []
    for bid, tick in _UUID_BUILDS:
        b = B(bid, tick)
        built.append(b)
        b.position = place_one(b, built, ANCHOR, SEED)
    return built


def test_uuid4_same_tick_incremental_is_append_only():
    # The EM-303c regression: pre-STORED-WINS, bld_0badbeef (sorting before the
    # already-built bld_f00dcafe) made place_one recompute the town from scratch
    # and disagree with what bld_f00dcafe had stored.
    snapshots: list[dict] = []
    built: list[B] = []
    for bid, tick in _UUID_BUILDS:
        b = B(bid, tick)
        built.append(b)
        b.position = place_one(b, built, ANCHOR, SEED)
        snapshots.append({x.id: x.position for x in built})
    final = snapshots[-1]
    for snap in snapshots:
        for bid, pos in snap.items():
            assert final[bid] == pos            # nobody ever moved


def test_uuid4_same_tick_incremental_respects_stored_spacing():
    built = _incremental_uuid_run()
    for i in range(len(built)):
        for j in range(i + 1, len(built)):
            assert math.dist(built[i].position, built[j].position) >= MIN_SPACING - 1e-9


def test_uuid4_batch_derive_is_input_order_independent():
    # The content-derived (created_tick, id) key is total ⇒ shuffling the input
    # container can never change a batch derive (no hash/insertion-order drift).
    s = [B(bid, tick) for bid, tick in _UUID_BUILDS]
    forward = place_all(s, ANCHOR, SEED)
    reverse = place_all(list(reversed(s)), ANCHOR, SEED)
    assert forward == reverse


def test_uuid4_incremental_then_batch_is_stable():
    # The (c) proof: after a live uuid4 run, a batch place_all over the stored
    # set (what derive-on-load does to a fully-positioned snapshot) returns the
    # stored positions verbatim — batch and incremental can never disagree.
    built = _incremental_uuid_run()
    stored_map = {b.id: b.position for b in built}
    assert place_all(built, ANCHOR, SEED) == stored_map

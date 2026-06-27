"""
Wave M4 / EM-189 — Deterministic child ids (contracts/wave-m.md §3).

The EM-114 child-spawn path minted child agent ids with `uuid4`, so two
same-seed / same-config runs produced identical births carrying DIFFERENT
ids — cross-run A/B diffing could not align children, violating the EM-155
determinism intent (which already makes prop ids / image ids / births
otherwise replay-stable).

EM-189 derives the child id from a SEEDED birth hash (parents' sorted ids +
birth tick + a per-tick birth ordinal + city_seed), exactly like the EM-210
`_image_id` / EM-218 `_prop_id` seeds. The id stays format-compatible
(a stable `agent_<name>_<hash>` prefix), is collision-safe, and is
replay / fork stable.

Covers:
  · same-seed / same-config runs → IDENTICAL child ids
  · a different city_seed → a DIFFERENT child id (the seed actually rides)
  · two children born the SAME tick get DISTINCT ids (the per-tick ordinal)
  · fork / replay identity preserved (re-running the same birth → same id)
  · the minted id is format-compatible (agent_<name>_<10hex>, hex-suffixed)
  · NO uuid4 anywhere in the birth path (the regression guard)

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

from petridish.engine.world import (
    AgentState,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import ChildrenParams, WorldParams


# ──────────────────────────────────────────────────────────────────────────────
# Helpers (mirror test_wave_e_children.py so the birth path is exercised
# end-to-end through check_births, not a private id helper in isolation)
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    p = WorldParams()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _children(**overrides) -> ChildrenParams:
    c = ChildrenParams(birth_chance=1.0)
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


def _places(beds: int = 10) -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="hearth", name="Hearth House", x=10, y=0, kind="home",
                   capacity=beds),
    ]


def _agent(aid: str, name: str, location: str = "hearth", credits: int = 50,
           energy: float = 80.0, profile: str = "mock") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile=profile,
                      location=location, energy=energy, credits=credits)


def _make_partners(world: World, a_id: str, b_id: str, trust: int = 50) -> None:
    for x, y in ((a_id, b_id), (b_id, a_id)):
        world.agents[x].relationships[y] = RelationshipState(
            type="partner", trust=trust, interactions=10)


def _eligible_world(*, beds: int = 10, city_seed: int = 1337,
                    children: ChildrenParams | None = None,
                    pair=(("agent_ada", "Ada"), ("agent_bram", "Bram")),
                    **param_overrides) -> World:
    params = _params(city_seed=city_seed, **param_overrides)
    params.children = children if children is not None else _children()
    agents = [_agent(aid, name) for aid, name in pair]
    world = World(params=params, places=_places(beds=beds), agents=agents)
    _make_partners(world, pair[0][0], pair[1][0])
    return world


CARDS = [
    {"name": "Mox", "personality": "Reads hidden messages in typos."},
    {"name": "Vesper", "personality": "Pitches a new scheme to anyone."},
]


def _birth_one(world: World, tick: int) -> str:
    world.tick = tick
    events = world.check_births(CARDS)
    assert [e["kind"] for e in events] == ["child_spawned", "agent_spawned"], (
        "expected exactly one birth")
    return events[0]["payload"]["child_id"]


# ══════════════════════════════════════════════════════════════════════════════
# Same-seed / same-config → identical child ids
# ══════════════════════════════════════════════════════════════════════════════

def test_same_seed_runs_produce_identical_child_ids():
    """Two independent worlds with identical seed/config/parents/tick mint the
    SAME child id — the whole point of EM-189 (A/B diffs can align children)."""
    id_a = _birth_one(_eligible_world(), tick=33)
    id_b = _birth_one(_eligible_world(), tick=33)
    assert id_a == id_b


def test_child_id_is_replay_fork_stable_across_repeated_births():
    """Re-running the exact same birth (replay / fork resume) yields the exact
    same child id every time — no per-process salt, no clock, no uuid."""
    ids = {_birth_one(_eligible_world(), tick=77) for _ in range(5)}
    assert len(ids) == 1


def test_different_city_seed_changes_the_child_id():
    """The city_seed actually rides the hash — a different city seeds a
    different (but still deterministic) child id."""
    id_default = _birth_one(_eligible_world(city_seed=1337), tick=33)
    id_other = _birth_one(_eligible_world(city_seed=9001), tick=33)
    assert id_default != id_other


def test_different_birth_tick_changes_the_child_id():
    """Birth tick is part of the seed — same parents, different tick → distinct
    ids (a later child of the same pair can never alias an earlier one)."""
    id_t33 = _birth_one(_eligible_world(), tick=33)
    id_t34 = _birth_one(_eligible_world(), tick=34)
    assert id_t33 != id_t34


def test_different_parents_change_the_child_id():
    """Parents' ids are part of the seed — a different pair → a different id."""
    id_pair1 = _birth_one(_eligible_world(), tick=33)
    id_pair2 = _birth_one(
        _eligible_world(pair=(("agent_cy", "Cy"), ("agent_dot", "Dot"))),
        tick=33)
    assert id_pair1 != id_pair2


# ══════════════════════════════════════════════════════════════════════════════
# Two children at the SAME tick → distinct ids (the per-tick ordinal)
# ══════════════════════════════════════════════════════════════════════════════

def test_two_children_same_tick_get_distinct_ids():
    """Two pairs that both give birth at the SAME tick (the ordinal arm of the
    seed) get DISTINCT ids — id collisions can't occur within a tick. We drive
    two check_births calls at the same tick (one birth per call, world cooldown)
    so two children share tick 50 with the ordinal disambiguating them."""
    params = _params(city_seed=1337)
    params.children = _children()
    agents = [
        _agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
        _agent("agent_cy", "Cy"), _agent("agent_dot", "Dot"),
    ]
    # Cy/Dot live at a SECOND home so both pairs are co-located-at-home but the
    # birth check picks one pair per call (sorted-id order, ada/bram first).
    places = _places(beds=10) + [
        PlaceState(id="hearth2", name="Hearth Two", x=20, y=0, kind="home",
                   capacity=10),
    ]
    world = World(params=params, places=places, agents=agents)
    world.agents["agent_cy"].location = "hearth2"
    world.agents["agent_dot"].location = "hearth2"
    _make_partners(world, "agent_ada", "agent_bram")
    _make_partners(world, "agent_cy", "agent_dot")

    world.tick = 50
    first = world.check_births(CARDS)
    second = world.check_births(CARDS)
    assert [e["kind"] for e in first] == ["child_spawned", "agent_spawned"]
    assert [e["kind"] for e in second] == ["child_spawned", "agent_spawned"]

    id1 = first[0]["payload"]["child_id"]
    id2 = second[0]["payload"]["child_id"]
    assert id1 != id2
    # Both genuinely born at tick 50 (the ordinal, not the tick, separated them).
    for cid in (id1, id2):
        rel = next(iter(world.agents[cid].relationships.values()))
        assert rel.since_tick == 50


# ══════════════════════════════════════════════════════════════════════════════
# Format compatibility + no-uuid4 regression guard
# ══════════════════════════════════════════════════════════════════════════════

def test_child_id_is_format_compatible():
    """The minted id keeps the `agent_<name>_<hash>` shape with a stable hex
    suffix (consumers that split on '_' or match the prefix keep working)."""
    cid = _birth_one(_eligible_world(), tick=33)
    assert cid.startswith("agent_")
    suffix = cid.rsplit("_", 1)[-1]
    assert len(suffix) == 10
    assert all(c in "0123456789abcdef" for c in suffix)
    # The name segment survives (Mox is the first unused card).
    assert "mox" in cid.lower()


def test_no_uuid4_in_the_birth_path():
    """Hard regression guard: a birth must not call uuid4 at all. We patch
    uuid.uuid4 to explode and assert a birth still completes deterministically."""
    import petridish.engine.world as world_mod

    world = _eligible_world()
    world.tick = 33

    original = world_mod.uuid.uuid4

    def _boom():
        raise AssertionError("uuid4 called in the birth path (EM-189 regression)")

    world_mod.uuid.uuid4 = _boom
    try:
        events = world.check_births(CARDS)
    finally:
        world_mod.uuid.uuid4 = original

    assert [e["kind"] for e in events] == ["child_spawned", "agent_spawned"]
    assert events[0]["payload"]["child_id"].startswith("agent_")


def test_snapshot_round_trip_preserves_deterministic_child_id():
    """A born child's deterministic id survives a snapshot → from_snapshot
    round-trip unchanged (no re-mint on restore)."""
    world = _eligible_world()
    cid = _birth_one(world, tick=33)

    snap = world.to_snapshot()
    restored = World.from_snapshot(snap)
    assert cid in restored.agents
    assert restored.agents[cid].parents == ["agent_ada", "agent_bram"]


def test_fork_resume_keeps_same_tick_ordinal_stable():
    """The per-tick birth ordinal is derived from the snapshotted family-tie
    since_tick (NOT a transient process counter), so a fork/resume between two
    same-tick births mints the SAME second-child id an in-process run would.
    We drive the id derivation directly (the birth gate is config-sensitive and
    config is reconstructed from defaults on resume — orthogonal to EM-189), so
    this isolates the ordinal's fork-safety."""
    world = _eligible_world()
    cid_first = _birth_one(world, tick=50)  # one child already born at tick 50

    # In-process: the ordinal for the next same-tick birth is 1.
    parents2 = sorted(("agent_cy", "agent_dot"))
    in_process = world._child_id(
        parents2, 50, world._births_at_tick(50), "Vesper")

    # Across a fork: the snapshotted since_tick reproduces the same ordinal.
    restored = World.from_snapshot(world.to_snapshot())
    restored.tick = 50
    across_fork = restored._child_id(
        parents2, 50, restored._births_at_tick(50), "Vesper")

    assert world._births_at_tick(50) == 1
    assert restored._births_at_tick(50) == 1
    assert in_process == across_fork
    assert in_process != cid_first

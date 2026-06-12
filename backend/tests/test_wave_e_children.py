"""
Wave E / B2 — EM-114 lightweight children (contracts/wave-e.md §B2).

Covers the full B2 acceptance list:
  · happy path: mutual partners co-located at home with credits/energy →
    child appears, parents debited, both events emitted, child at background
    tier with family ties both ways, parents field set
  · cap gates: population cap (the free-scale proof: AT cap, no birth ever
    fires regardless of conditions), housing capacity, credits, energy,
    pair cooldown, the seeded chance gate (seed-pinned both ways), and
    one-birth-per-round
  · persona casting: unused card consumed; collisions with living AND dead
    names skipped; exhausted library → Kit-N
  · profile pick: fewest living assigned agents, non-mock, stable order
  · snapshot round-trip: parents + the new config; a resumed world doesn't
    re-birth (pair cooldown derived from the child's family-tie since_tick)
  · enabled:false ⇒ byte-identical pre-E behavior
  · repository: additive parents_json round-trip + the idempotent migration
  · the TickLoop casting-pool hook

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import json
import sqlite3

from petridish.engine.world import (
    AgentState,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import (
    ChildrenParams,
    ModelProfile,
    WorldConfig,
    WorldParams,
    _parse_children,
    load_config,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    p = WorldParams()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _children(**overrides) -> ChildrenParams:
    """A birth-friendly children block: chance 1.0 so tests are deterministic
    unless a test pins the chance gate itself."""
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


def _eligible_world(*, beds: int = 10, children: ChildrenParams | None = None,
                    **param_overrides) -> World:
    """Two mutual partners co-located at the home, every gate satisfied."""
    params = _params(**param_overrides)
    params.children = children if children is not None else _children()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")]
    world = World(params=params, places=_places(beds=beds), agents=agents)
    _make_partners(world, "agent_ada", "agent_bram")
    return world


CARDS = [
    {"name": "Mox", "personality": "Reads hidden messages in typos."},
    {"name": "Vesper", "personality": "Pitches a new scheme to anyone."},
]


# ══════════════════════════════════════════════════════════════════════════════
# Happy path
# ══════════════════════════════════════════════════════════════════════════════

def test_happy_path_birth():
    world = _eligible_world()
    world.tick = 33
    events = world.check_births(CARDS)

    assert [e["kind"] for e in events] == ["child_spawned", "agent_spawned"]
    assert world.pending_spawn_events == events  # parked in the proven outbox

    child_id = events[0]["payload"]["child_id"]
    child = world.agents[child_id]
    assert child.name == "Mox"                      # first unused card
    assert child.alive
    assert child.cadence_tier == "background"       # free-scale law
    assert child.energy == 70.0
    assert child.credits == 0
    assert child.location == "hearth"               # the birth home
    assert child.parents == ["agent_ada", "agent_bram"]

    # Both parents debited (credits sink — nobody received them).
    assert world.agents["agent_ada"].credits == 44
    assert world.agents["agent_bram"].credits == 44

    # Family ties both ways, since_tick = birth tick.
    for pid in ("agent_ada", "agent_bram"):
        down = child.relationships[pid]
        up = world.agents[pid].relationships[child_id]
        for rel in (down, up):
            assert rel.type == "family"
            assert rel.trust == 40
            assert rel.since_tick == 33

    # The "born in {town}" memory line rides the world-side beliefs seam.
    assert any("Born in the town" in b for b in child.beliefs)

    # Event shapes: agent ids only on endpoints, contracted payloads.
    born = events[0]
    assert born["actor_id"] == child_id
    assert born.get("target_id") is None
    assert born["text"] == "👶 Mox is born to Ada and Bram"
    assert born["payload"] == {
        "child_id": child_id, "parents": ["agent_ada", "agent_bram"],
        "name": "Mox", "profile": child.profile, "place": "hearth"}
    spawned = events[1]
    assert spawned["payload"]["method"] == "birth"
    assert spawned["payload"]["agent_id"] == child_id
    assert spawned["payload"]["parents"] == ["agent_ada", "agent_bram"]


def test_child_personality_blend_is_prefixed_and_deterministic():
    world = _eligible_world()
    world.agents["agent_ada"].personality = (
        "Warm-hearted tinkerer, keeps the village tidy.")
    world.agents["agent_bram"].personality = "Charming trader; loves a deal."
    events = world.check_births(CARDS)
    child = world.agents[events[0]["payload"]["child_id"]]
    assert child.personality == (
        "Child of Ada and Bram. Reads hidden messages in typos. "
        "Warm-hearted tinkerer. Charming trader.")


def test_birth_fires_at_round_boundary_and_events_drain():
    """The hook lives beside the per-round effects: a plain next_agent() that
    starts a round births the child, whose events drain via the existing
    governance-spawn outbox; the background child does NOT join a round whose
    tier isn't due (EM-158/172 pointer safety intact)."""
    world = _eligible_world()
    world.tick = 5
    first = world.next_agent()                 # starts round 1 → birth check
    assert first.id == "agent_ada"
    assert world.round == 1
    children = [a for a in world.agents.values() if a.parents]
    assert len(children) == 1
    child = children[0]
    assert child.id not in world._turn_order   # background not due round 1
    drained = world.drain_spawn_events()
    assert [e["kind"] for e in drained] == ["child_spawned", "agent_spawned"]
    assert world.drain_spawn_events() == []    # idempotent
    # The remaining round walks the original pair only.
    assert world.next_agent().id == "agent_bram"


def test_town_name_rides_the_memory_line():
    world = _eligible_world()
    world.town_name = "Petriville"
    events = world.check_births(CARDS)
    child = world.agents[events[0]["payload"]["child_id"]]
    assert "Born in Petriville." in child.beliefs


# ══════════════════════════════════════════════════════════════════════════════
# Cap gates
# ══════════════════════════════════════════════════════════════════════════════

def test_free_scale_proof_no_birth_ever_at_max_population():
    """AT (or over) max_population no birth EVER fires, regardless of every
    other condition being perfect — across many rounds/ticks/seeds."""
    world = _eligible_world(children=_children(max_population=2))
    for tick in range(0, 120):
        world.tick = tick
        assert world.check_births(CARDS) == []
    assert world.pending_spawn_events == []
    assert all(not a.parents for a in world.agents.values())
    # Over the cap is just as dead.
    world.params.children.max_population = 1
    assert world.check_births(CARDS) == []


def test_housing_capacity_gates_births():
    # 2 living, 2 beds → no vacancy → no birth.
    blocked = _eligible_world(beds=2)
    assert blocked.check_births(CARDS) == []
    # 2 living, 3 beds → vacancy → birth.
    allowed = _eligible_world(beds=3)
    assert len(allowed.check_births(CARDS)) == 2


def test_cottages_count_one_bed_each():
    world = _eligible_world()
    world.places["cottage_a"] = PlaceState(
        id="cottage_a", name="A's cottage", x=1, y=1, kind="home")
    world.places["bunk"] = PlaceState(
        id="bunk", name="Bunkhouse", x=2, y=2, kind="home", capacity=4)
    # hearth(10) + cottage(1) + bunk(4); plaza (social) never counts.
    assert world.home_bed_capacity() == 15


def test_credits_gate_both_parents_must_afford():
    world = _eligible_world()
    world.agents["agent_ada"].credits = 5      # below birth_cost_credits 6
    assert world.check_births(CARDS) == []
    world.agents["agent_ada"].credits = 6      # at the cost: allowed
    assert len(world.check_births(CARDS)) == 2
    assert world.agents["agent_ada"].credits == 0


def test_energy_gate_both_parents_need_30():
    world = _eligible_world()
    world.agents["agent_bram"].energy = 29.0
    assert world.check_births(CARDS) == []
    world.agents["agent_bram"].energy = 30.0
    assert len(world.check_births(CARDS)) == 2


def test_partners_must_be_colocated_at_a_home():
    # Apart: no birth.
    apart = _eligible_world()
    apart.agents["agent_bram"].location = "plaza"
    assert apart.check_births(CARDS) == []
    # Together at a NON-home place: no birth.
    not_home = _eligible_world()
    for a in not_home.living_agents():
        a.location = "plaza"
    assert not_home.check_births(CARDS) == []


def test_non_partners_never_birth():
    world = _eligible_world()
    for x, y in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada")):
        world.agents[x].relationships[y].type = "friend"
    assert world.check_births(CARDS) == []


def test_chance_gate_seed_pinned_both_ways():
    """birth_chance 0.25 with the sha1-seeded roll: a tick whose roll passes
    births; a tick whose roll fails doesn't — both pinned via _birth_roll
    (deterministic: city_seed + tick + sorted pair, no `random`)."""
    probe = _eligible_world(children=_children(birth_chance=0.25))
    rolls = {}
    for t in range(500):
        probe.tick = t
        rolls[t] = probe._birth_roll("agent_ada", "agent_bram")
    pass_tick = next(t for t, r in rolls.items() if r < 0.25)
    fail_tick = next(t for t, r in rolls.items() if r >= 0.25)

    failing = _eligible_world(children=_children(birth_chance=0.25))
    failing.tick = fail_tick
    assert failing.check_births(CARDS) == []

    passing = _eligible_world(children=_children(birth_chance=0.25))
    passing.tick = pass_tick
    assert len(passing.check_births(CARDS)) == 2

    # The roll is order-insensitive (sorted pair) and seed-sensitive.
    assert (probe._birth_roll("agent_ada", "agent_bram")
            == probe._birth_roll("agent_bram", "agent_ada"))
    probe.tick = pass_tick
    before = probe._birth_roll("agent_ada", "agent_bram")
    probe.city_seed += 1
    assert probe._birth_roll("agent_ada", "agent_bram") != before


def test_at_most_one_birth_per_round():
    """Two fully-eligible pairs → ONE child per check (sorted-id pair order
    picks the first pair deterministically)."""
    params = _params()
    params.children = _children()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cleo", "Cleo"), _agent("agent_dov", "Dov")]
    world = World(params=params, places=_places(beds=10), agents=agents)
    _make_partners(world, "agent_ada", "agent_bram")
    _make_partners(world, "agent_cleo", "agent_dov")

    events = world.check_births(CARDS)
    assert len(events) == 2                      # one birth = two events
    children = [a for a in world.agents.values() if a.parents]
    assert len(children) == 1
    assert children[0].parents == ["agent_ada", "agent_bram"]  # first pair


def test_pair_cooldown_derived_from_youngest_child():
    world = _eligible_world(children=_children(pair_cooldown_ticks=100))
    world.tick = 10
    assert len(world.check_births(CARDS)) == 2
    world.drain_spawn_events()
    # Top everyone back up so ONLY the cooldown gates.
    for a in world.living_agents():
        a.credits, a.energy = 50, 80.0
    world.tick = 109                              # 99 ticks later: inside
    assert world.check_births(CARDS) == []
    world.tick = 110                              # exactly cooldown: free
    events = world.check_births(CARDS)
    assert len(events) == 2
    assert events[0]["payload"]["name"] == "Vesper"   # next unused card


def test_dead_child_still_anchors_the_cooldown():
    world = _eligible_world(children=_children(pair_cooldown_ticks=100))
    world.tick = 10
    child_id = world.check_births(CARDS)[0]["payload"]["child_id"]
    world.kill_agent(child_id)
    for a in world.living_agents():
        a.credits, a.energy = 50, 80.0
    world.tick = 50
    assert world.check_births(CARDS) == []        # still inside the window


# ══════════════════════════════════════════════════════════════════════════════
# Persona casting
# ══════════════════════════════════════════════════════════════════════════════

def test_card_colliding_with_living_name_is_skipped():
    world = _eligible_world()
    cards = [{"name": "ada", "personality": "imposter"}] + CARDS  # case-insensitive
    events = world.check_births(cards)
    assert events[0]["payload"]["name"] == "Mox"


def test_dead_agent_identity_is_never_recycled():
    world = _eligible_world()
    ghost = _agent("agent_mox", "Mox", location="plaza")
    ghost.alive = False
    world.agents[ghost.id] = ghost
    events = world.check_births(CARDS)
    assert events[0]["payload"]["name"] == "Vesper"


def test_exhausted_library_falls_back_to_kit_n():
    world = _eligible_world()
    events = world.check_births([])               # empty library
    assert events[0]["payload"]["name"] == "Kit-1"
    # A taken Kit-1 bumps to the smallest free number.
    world2 = _eligible_world()
    world2.agents["agent_kit"] = _agent("agent_kit", "Kit-1", location="plaza")
    events2 = world2.check_births([])
    assert events2[0]["payload"]["name"] == "Kit-2"


def test_round_boundary_uses_the_seeded_casting_pool():
    world = _eligible_world()
    world.set_birth_casting(CARDS, ["lane-a"])
    world.next_agent()                            # round start → birth
    children = [a for a in world.agents.values() if a.parents]
    assert children[0].name == "Mox"
    assert children[0].profile == "lane-a"


# ══════════════════════════════════════════════════════════════════════════════
# Profile pick — fewest living assigned, non-mock, stable order
# ══════════════════════════════════════════════════════════════════════════════

def test_profile_fewest_living_non_mock_stable_order():
    params = _params()
    params.children = _children()
    agents = [
        _agent("agent_ada", "Ada", profile="alpha"),
        _agent("agent_bram", "Bram", profile="alpha"),
        _agent("agent_cleo", "Cleo", location="plaza", profile="beta"),
        _agent("agent_dov", "Dov", location="plaza", profile="mock"),
    ]
    world = World(params=params, places=_places(beds=10), agents=agents)
    world.set_birth_casting([], ["alpha", "beta"])
    _make_partners(world, "agent_ada", "agent_bram")
    events = world.check_births(CARDS)
    assert events[0]["payload"]["profile"] == "beta"   # 1 beta < 2 alpha

    # Tie → stable roster (config) order; a dead agent doesn't count.
    world.kill_agent("agent_cleo")  # now alpha 2(+?), beta 0… rebuild cleanly:
    world2 = World(params=params, places=_places(beds=10), agents=[
        _agent("agent_ada", "Ada", profile="alpha"),
        _agent("agent_bram", "Bram", profile="beta"),
    ])
    world2.set_birth_casting([], ["alpha", "beta"])
    _make_partners(world2, "agent_ada", "agent_bram")
    assert world2.check_births(CARDS)[0]["payload"]["profile"] == "alpha"


def test_profile_roster_never_picks_mock_and_degrades_safely():
    # mock in the seeded roster is filtered out.
    world = _eligible_world()
    world.set_birth_casting([], ["mock", "alpha"])
    assert world.check_births(CARDS)[0]["payload"]["profile"] == "alpha"
    # Unseeded roster derives from living agents' non-mock profiles.
    world2 = _eligible_world()
    world2.agents["agent_bram"].profile = "gamma"
    assert world2.check_births(CARDS)[0]["payload"]["profile"] == "gamma"
    # All-mock test world: mock is the only thing left (mirrors _pad_agents).
    world3 = _eligible_world()
    assert world3.check_births(CARDS)[0]["payload"]["profile"] == "mock"


# ══════════════════════════════════════════════════════════════════════════════
# Snapshot round-trip + the enabled:false byte-identical proof
# ══════════════════════════════════════════════════════════════════════════════

def test_parents_roundtrip_snapshot_and_absent_means_empty():
    world = _eligible_world()
    world.tick = 12
    child_id = world.check_births(CARDS)[0]["payload"]["child_id"]

    restored = World.from_snapshot(world.to_snapshot())
    assert restored.agents[child_id].parents == ["agent_ada", "agent_bram"]
    # Non-children carry NO parents key at all (pre-E dict shape)…
    snap = world.to_snapshot()
    by_id = {a["id"]: a for a in snap["agents"]}
    assert "parents" not in by_id["agent_ada"]
    assert by_id[child_id]["parents"] == ["agent_ada", "agent_bram"]
    # …and a pre-E snapshot (key stripped) restores [].
    by_id[child_id].pop("parents")
    re_restored = World.from_snapshot(snap)
    assert re_restored.agents[child_id].parents == []


def test_resumed_world_does_not_rebirth_inside_cooldown():
    """The pair cooldown is DERIVED state (child's family-tie since_tick via
    the parents field): a snapshot/restore mid-window must not re-birth."""
    world = _eligible_world(children=_children(pair_cooldown_ticks=200))
    world.tick = 20
    assert len(world.check_births(CARDS)) == 2
    for a in world.living_agents():
        a.credits, a.energy = 50, 80.0

    restored = World.from_snapshot(world.to_snapshot(), params=world.params)
    restored.tick = 21
    assert restored.check_births(CARDS) == []     # inside the window
    restored.tick = 220                            # window over
    assert len(restored.check_births(CARDS)) == 2


def test_enabled_false_is_byte_identical_and_checkless():
    """children.enabled: false ⇒ NO birth checks at all: a fully eligible
    world's snapshot is byte-identical before/after every round hook, and
    matches a pre-E params world (no children block) given no partners."""
    world = _eligible_world(children=_children(enabled=False))
    before = json.dumps(world.to_snapshot(), sort_keys=True)
    for _ in range(6):
        world.next_agent()                         # crosses round boundaries
    assert world.check_births(CARDS) == []         # explicit call: still inert
    assert world.pending_spawn_events == []
    after = json.dumps(world.to_snapshot(), sort_keys=True)
    # Only the scheduler bookkeeping moved (rounds advanced); the agents
    # block — the part births would touch — is byte-identical, with no
    # parents keys anywhere (the exact pre-E dict shape).
    assert json.dumps(json.loads(before)["agents"], sort_keys=True) \
        == json.dumps(json.loads(after)["agents"], sort_keys=True)
    assert "parents" not in after
    assert all(not a.parents for a in world.agents.values())


def test_absent_children_block_behaves_like_defaults():
    """Defensive _chl_param accessor: a pre-E params object WITHOUT the block
    gets identical defaults (enabled, 25/6/0.25/600)."""
    params = _params()
    del params.children                            # pre-E params shape
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")]
    world = World(params=params, places=_places(beds=10), agents=agents)
    assert getattr(world.params, "children", None) is None
    assert world._chl_param("max_population", 25) == 25
    assert world._chl_param("birth_chance", 0.25) == 0.25
    # No partners (every pre-E world) ⇒ the default-enabled check is a no-op.
    assert world.check_births(CARDS) == []
    # With partners + a passing roll it births on the defaults.
    _make_partners(world, "agent_ada", "agent_bram")
    for tick in range(500):
        world.tick = tick
        if world._birth_roll("agent_ada", "agent_bram") < 0.25:
            break
    assert len(world.check_births(CARDS)) == 2


# ══════════════════════════════════════════════════════════════════════════════
# Config — world.children block (EM-155 conventions)
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_children_defaults_overrides_malformed():
    d = _parse_children(None)
    assert (d.enabled, d.max_population, d.birth_cost_credits,
            d.birth_chance, d.pair_cooldown_ticks) == (True, 25, 6, 0.25, 600)
    assert _parse_children("nonsense") == ChildrenParams()
    p = _parse_children({"enabled": False, "max_population": 10,
                         "birth_chance": 7, "pair_cooldown_ticks": "junk",
                         "birth_cost_credits": -3})
    assert p.enabled is False
    assert p.max_population == 10
    assert p.birth_chance == 1.0                   # clamped to [0, 1]
    assert p.pair_cooldown_ticks == 600            # malformed → default
    assert p.birth_cost_credits == 0               # clamped to >= 0


def test_embedded_and_shipped_yaml_match_dataclass_defaults():
    """The EMBEDDED_WORLD_YAML mirror AND config/world.yaml parse to the same
    children defaults as the dataclass (the EM-155 loader↔engine invariant)."""
    import yaml as _yaml
    from petridish.config.loader import EMBEDDED_WORLD_YAML, _parse_world
    params, _, _ = _parse_world(_yaml.safe_load(EMBEDDED_WORLD_YAML))
    assert params.children == ChildrenParams()
    cfg = load_config()                            # shipped config/world.yaml
    assert cfg.world.children == ChildrenParams()


# ══════════════════════════════════════════════════════════════════════════════
# Repository — additive parents_json
# ══════════════════════════════════════════════════════════════════════════════

def test_parents_json_roundtrips_repository():
    world = _eligible_world()
    child_id = world.check_births(CARDS)[0]["payload"]["child_id"]
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    repo.save_agent(run_id, world.agents[child_id], tick=5)
    repo.save_agent(run_id, world.agents["agent_ada"], tick=5)

    rows = dict(repo._conn.execute(
        "SELECT id, parents_json FROM agents").fetchall())
    assert json.loads(rows[child_id]) == ["agent_ada", "agent_bram"]
    assert json.loads(rows["agent_ada"]) == []     # absent ⇒ [] by default


def test_agents_table_migration_adds_parents_json(tmp_path):
    """A pre-Wave-E file DB (agents table without parents_json) gets the
    column via the idempotent guarded ALTER at repo init."""
    db = tmp_path / "old.sqlite"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE agents (
          id TEXT PRIMARY KEY, run_id INTEGER NOT NULL, name TEXT NOT NULL,
          personality TEXT NOT NULL, profile TEXT NOT NULL,
          location TEXT NOT NULL, energy REAL NOT NULL,
          credits INTEGER NOT NULL, mood TEXT,
          alive INTEGER NOT NULL DEFAULT 1,
          zero_energy_turns INTEGER NOT NULL DEFAULT 0,
          beliefs_json TEXT NOT NULL DEFAULT '[]',
          relationships_json TEXT NOT NULL DEFAULT '{}',
          updated_tick INTEGER NOT NULL DEFAULT 0
        );
        INSERT INTO agents (id, run_id, name, personality, profile, location,
                            energy, credits)
        VALUES ('agent_old', 1, 'Old', '', 'mock', 'plaza', 50, 10);
    """)
    conn.commit()
    conn.close()

    repo = SQLiteRepository(db)
    cols = {row[1] for row in repo._conn.execute("PRAGMA table_info(agents)")}
    assert "parents_json" in cols
    row = repo._conn.execute(
        "SELECT parents_json FROM agents WHERE id='agent_old'").fetchone()
    assert json.loads(row[0]) == []                # legacy rows default '[]'
    # And save_agent works against the migrated table.
    run_id = repo.start_run("{}")
    repo.save_agent(run_id, _agent("agent_new", "New"), tick=1)
    repo.close()


# ══════════════════════════════════════════════════════════════════════════════
# The TickLoop casting hook
# ══════════════════════════════════════════════════════════════════════════════

def test_loop_seeds_birth_casting_from_router_and_library():
    params = _params()
    params.children = _children()
    agents = [_agent("agent_ada", "Ada")]
    world = World(params=params, places=_places(), agents=agents)
    profiles = [
        ModelProfile(name="mock", adapter="mock", model_id="mock"),
        ModelProfile(name="lane-a", adapter="openai", model_id="m1"),
        ModelProfile(name="lane-b", adapter="openai", model_id="m2"),
    ]
    router = Router(profiles, adapter_overrides={
        "lane-a": MockProvider(), "lane-b": MockProvider()})
    runtime = AgentRuntime(world, router)
    repo = SQLiteRepository(":memory:")
    TickLoop(world=world, runtime=runtime, repo=repo, router=router)

    # Non-mock roster, STABLE config order; mock filtered out.
    assert world.birth_profile_roster == ["lane-a", "lane-b"]
    # The persona library loaded fail-soft (10 cards in the shipped file).
    assert isinstance(world.birth_personas, list)
    assert all(isinstance(c, dict) for c in world.birth_personas)
    assert {"Mox", "Vesper"} <= {c.get("name") for c in world.birth_personas}


async def test_birth_events_emit_through_the_loop_pipeline():
    """End-to-end: a round boundary births the child world-side; the loop's
    per-turn _advance_round_buildings drains the outbox into persisted
    standalone system events (turn_id null) — the EM-062/168 pattern."""
    params = _params(energy_decay_per_turn=0.0)
    params.children = _children()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")]
    world = World(params=params, places=_places(beds=10), agents=agents)
    _make_partners(world, "agent_ada", "agent_bram")
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock")]
    router = Router(profiles, adapter_overrides={
        "mock": MockProvider(script=[{"action": "idle", "args": {}}])})
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))

    agent = world.next_agent()                     # round 1 starts → birth
    await loop._execute_turn(agent)

    events = repo.get_events(loop._run_id, order="asc")
    by_kind = {e["kind"]: e for e in events}
    assert "child_spawned" in by_kind
    assert "agent_spawned" in by_kind
    assert by_kind["child_spawned"]["turn_id"] is None      # standalone
    assert by_kind["child_spawned"]["actor_type"] == "system"
    payload = by_kind["child_spawned"]["payload"]
    assert payload["parents"] == ["agent_ada", "agent_bram"]
    assert world.agents[payload["child_id"]].cadence_tier == "background"

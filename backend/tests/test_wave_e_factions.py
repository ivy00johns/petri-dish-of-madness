"""
Wave E / B3 — EM-120 factions, feuds & reputation (contracts/wave-e.md §B3).

Covers the full B3 acceptance list:
  · 3 mutually-warm agents form a faction (one formed event, deterministic
    id/name); a 4th warm agent joins (one joined event); a trust drop below
    threshold → left event; shrinking under min_size → dissolved
  · identity continuity across membership churn (>= 50% overlap of the OLD
    membership keeps id/name)
  · reputation math (mean incoming trust from LIVING agents with
    interactions >= 1; zero-relationship default) + the snapshot surface
  · determinism: same world state ⇒ identical faction ids/names across two
    recomputes; snapshot round-trip preserves factions (absent key ⇒ {})
  · enabled:false ⇒ byte-identical pre-E behavior (no recompute, no events,
    no factions/reputation snapshot keys)
  · events carry agent ids only; diff-driven (zero events across many
    stable rounds); round-boundary hook order (births FIRST, then factions)
  · config: world.factions block (EM-155 conventions) + the embedded/shipped
    yaml ↔ dataclass default invariant

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import hashlib
import json

from petridish.engine.world import (
    AgentState,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import (
    ChildrenParams,
    FactionParams,
    WorldParams,
    _parse_factions,
    load_config,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    p = WorldParams()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _factions(**overrides) -> FactionParams:
    f = FactionParams()
    for k, v in overrides.items():
        setattr(f, k, v)
    return f


def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="hearth", name="Hearth House", x=10, y=0, kind="home",
                   capacity=10),
    ]


def _agent(aid: str, name: str, location: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=80.0, credits=50)


def _warm(world: World, a_id: str, b_id: str, trust: int = 50,
          rel_type: str = "friend") -> None:
    """A MUTUAL warm edge (both directions typed warm, both trusts set)."""
    for x, y in ((a_id, b_id), (b_id, a_id)):
        world.agents[x].relationships[y] = RelationshipState(
            type=rel_type, trust=trust, interactions=5)


def _cool(world: World, a_id: str, b_id: str, trust: int = 0) -> None:
    """Drop ONE direction's trust (enough to break the mutual edge)."""
    world.agents[a_id].relationships[b_id].trust = trust


def _trio_world(factions: FactionParams | None = None, **param_overrides) -> World:
    """Ada/Bram/Cora, all pairwise mutually warm — a 3-clique."""
    params = _params(**param_overrides)
    params.factions = factions if factions is not None else _factions()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cora", "Cora")]
    world = World(params=params, places=_places(), agents=agents)
    for a, b in (("agent_ada", "agent_bram"), ("agent_ada", "agent_cora"),
                 ("agent_bram", "agent_cora")):
        _warm(world, a, b)
    return world


def _faction_kinds(events: list[dict]) -> list[str]:
    return [e["kind"] for e in events if e["kind"].startswith("faction")]


# ══════════════════════════════════════════════════════════════════════════════
# Formation / join / leave / dissolve (acceptance item 1)
# ══════════════════════════════════════════════════════════════════════════════

def test_three_warm_agents_form_a_faction_deterministically():
    world = _trio_world()
    world.tick = 40
    events = world.recompute_factions()

    assert [e["kind"] for e in events] == ["faction_formed"]
    assert world.pending_spawn_events == events     # parked in the proven outbox

    fid = events[0]["payload"]["faction_id"]
    expected = "fct_" + hashlib.sha1(
        b"agent_ada:agent_bram:agent_cora:40").hexdigest()[:8]
    assert fid == expected                           # sha1 — never builtin hash
    # Name: "{oldest founding member's name}'s circle", oldest = LOWEST id.
    assert events[0]["payload"]["name"] == "Ada's circle"
    assert events[0]["payload"]["members"] == [
        "agent_ada", "agent_bram", "agent_cora"]
    assert world.factions == {fid: {
        "name": "Ada's circle", "founded_tick": 40,
        "members": ["agent_ada", "agent_bram", "agent_cora"]}}

    # Stable second recompute: no diff ⇒ NO events, identity kept.
    assert world.recompute_factions() == []
    assert set(world.factions) == {fid}


def test_fourth_warm_agent_joins_with_one_event():
    world = _trio_world()
    world.tick = 40
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_ada")          # one warm edge connects
    world.tick = 41
    events = world.recompute_factions()

    assert [e["kind"] for e in events] == ["faction_joined"]
    assert events[0]["actor_id"] == "agent_dell"
    assert events[0]["payload"] == {"faction_id": fid, "name": "Ada's circle"}
    assert world.factions[fid]["members"] == [
        "agent_ada", "agent_bram", "agent_cora", "agent_dell"]
    assert world.factions[fid]["founded_tick"] == 40  # continuity keeps it


def test_trust_drop_below_threshold_emits_left():
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_ada")
    world.tick = 40
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    _cool(world, "agent_dell", "agent_ada", trust=10)  # below faction_trust 25
    events = world.recompute_factions()

    assert [e["kind"] for e in events] == ["faction_left"]
    assert events[0]["actor_id"] == "agent_dell"
    assert events[0]["payload"] == {"faction_id": fid, "name": "Ada's circle"}
    # 3 of 4 old members remain (>= 50% overlap) ⇒ identity kept.
    assert world.factions[fid]["members"] == [
        "agent_ada", "agent_bram", "agent_cora"]


def test_at_threshold_trust_keeps_the_edge():
    """trust == faction_trust (25) is warm enough; 24 (strictly below) breaks
    the edge. CHAIN topology (ada-bram at 25, bram-cora at 50, no ada-cora)
    so the threshold edge is the only thing holding Ada in."""
    params = _params()
    params.factions = _factions()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cora", "Cora")]
    world = World(params=params, places=_places(), agents=agents)
    _warm(world, "agent_ada", "agent_bram", trust=25)   # exactly AT threshold
    _warm(world, "agent_bram", "agent_cora", trust=50)
    assert _faction_kinds(world.recompute_factions()) == ["faction_formed"]
    world.pending_spawn_events.clear()
    _cool(world, "agent_ada", "agent_bram", trust=24)   # one below ⇒ edge gone
    events = world.recompute_factions()
    # Ada drops out; {bram, cora} shrinks under min_size 3 ⇒ dissolved.
    assert _faction_kinds(events) == ["faction_dissolved"]


def test_shrink_under_min_size_dissolves():
    """A CHAIN faction (ada-bram, bram-cora): breaking one edge splits it
    into components of 2 and 1 — both under min_size 3 ⇒ dissolved."""
    params = _params()
    params.factions = _factions()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cora", "Cora")]
    world = World(params=params, places=_places(), agents=agents)
    _warm(world, "agent_ada", "agent_bram")
    _warm(world, "agent_bram", "agent_cora")         # chain, no ada-cora edge
    world.tick = 7
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    _cool(world, "agent_bram", "agent_cora", trust=0)
    events = world.recompute_factions()

    assert [e["kind"] for e in events] == ["faction_dissolved"]
    assert events[0]["actor_id"] == "agent_ada"      # lowest OLD member id
    assert events[0]["payload"] == {
        "faction_id": fid, "name": "Ada's circle",
        "members": ["agent_ada", "agent_bram", "agent_cora"]}
    assert world.factions == {}


def test_member_death_drops_them_from_the_faction():
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_ada")
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    world.kill_agent("agent_dell")
    events = world.recompute_factions()
    assert [e["kind"] for e in events] == ["faction_left"]
    assert events[0]["actor_id"] == "agent_dell"
    assert "agent_dell" not in world.factions[fid]["members"]


# ══════════════════════════════════════════════════════════════════════════════
# Mutual-warm edge semantics
# ══════════════════════════════════════════════════════════════════════════════

def test_edges_must_be_mutual_and_warm_typed():
    params = _params()
    params.factions = _factions()
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cora", "Cora")]
    world = World(params=params, places=_places(), agents=agents)

    # One-directional warmth never binds.
    world.agents["agent_ada"].relationships["agent_bram"] = RelationshipState(
        type="friend", trust=80, interactions=9)
    assert world.recompute_factions() == []

    # Mutual high trust but a NON-warm type (rival/feud) never binds.
    for a, b in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada"),
                 ("agent_ada", "agent_cora"), ("agent_cora", "agent_ada"),
                 ("agent_bram", "agent_cora"), ("agent_cora", "agent_bram")):
        world.agents[a].relationships[b] = RelationshipState(
            type="rival", trust=80, interactions=9)
    assert world.recompute_factions() == []
    assert world.factions == {}


def test_all_warm_types_bind_and_min_size_is_respected():
    """ally/friend/partner/family all count; 2 warm agents never form on the
    default min_size 3 but DO on min_size 2."""
    for rel_type in ("ally", "friend", "partner", "family"):
        params = _params()
        params.factions = _factions()
        agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")]
        world = World(params=params, places=_places(), agents=agents)
        _warm(world, "agent_ada", "agent_bram", rel_type=rel_type)
        assert world.recompute_factions() == []      # size 2 < min_size 3
        world.params.factions = _factions(faction_min_size=2)
        assert _faction_kinds(world.recompute_factions()) == ["faction_formed"]


# ══════════════════════════════════════════════════════════════════════════════
# Identity continuity (acceptance item 2)
# ══════════════════════════════════════════════════════════════════════════════

def test_identity_survives_churn_at_50_percent_overlap():
    """4-member faction; 2 leave and 2 NEW agents join the same round:
    overlap = 2 of 4 OLD members (exactly 50%) ⇒ id and name survive."""
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_cora")
    world.tick = 10
    formed = world.recompute_factions()[0]["payload"]
    fid = formed["faction_id"]
    world.pending_spawn_events.clear()

    # Cora + Dell drift out; Emil + Fern arrive warm to Ada.
    _cool(world, "agent_ada", "agent_cora", trust=0)
    _cool(world, "agent_bram", "agent_cora", trust=0)
    for new_id, new_name in (("agent_emil", "Emil"), ("agent_fern", "Fern")):
        world.agents[new_id] = _agent(new_id, new_name)
        _warm(world, new_id, "agent_ada")
    world.tick = 30
    events = world.recompute_factions()

    assert set(world.factions) == {fid}              # id kept
    assert world.factions[fid]["name"] == "Ada's circle"
    assert world.factions[fid]["founded_tick"] == 10
    assert world.factions[fid]["members"] == [
        "agent_ada", "agent_bram", "agent_emil", "agent_fern"]
    assert sorted(_faction_kinds(events)) == [
        "faction_joined", "faction_joined", "faction_left", "faction_left"]


def test_below_50_percent_overlap_is_a_new_faction():
    """Only 1 of 4 OLD members survives into the new component (25% < 50%):
    the old faction dissolves and a NEW one forms (fresh id/name)."""
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_ada")
    world.tick = 10
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    for gone in ("agent_ada", "agent_cora", "agent_dell"):
        world.kill_agent(gone)
    for new_id, new_name in (("agent_emil", "Emil"), ("agent_fern", "Fern")):
        world.agents[new_id] = _agent(new_id, new_name)
        _warm(world, new_id, "agent_bram")
    world.tick = 30
    events = world.recompute_factions()

    kinds = sorted(_faction_kinds(events))
    assert kinds == ["faction_dissolved", "faction_formed"]
    new_fid = next(e for e in events if e["kind"] == "faction_formed")[
        "payload"]["faction_id"]
    assert new_fid != fid
    assert world.factions[new_fid]["name"] == "Bram's circle"
    assert world.factions[new_fid]["founded_tick"] == 30


def test_split_faction_keeps_id_on_the_best_overlap_component():
    """A 6-clique splitting into two 3-cliques: each holds exactly 50% of the
    OLD membership — the deterministic tie-break keeps the id on the
    component containing the LOWEST agent id; the other half forms fresh."""
    params = _params()
    params.factions = _factions()
    ids = [f"agent_{c}" for c in "abcdef"]
    agents = [_agent(aid, aid[-1].upper()) for aid in ids]
    world = World(params=params, places=_places(), agents=agents)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            _warm(world, a, b)
    world.tick = 5
    fid = world.recompute_factions()[0]["payload"]["faction_id"]
    world.pending_spawn_events.clear()

    # Sever every cross edge between {a,b,c} and {d,e,f} (both directions).
    for a in ids[:3]:
        for b in ids[3:]:
            _cool(world, a, b, trust=0)
            _cool(world, b, a, trust=0)
    world.tick = 9
    events = world.recompute_factions()

    assert world.factions[fid]["members"] == ids[:3]   # lowest-id half keeps it
    kinds = sorted(_faction_kinds(events))
    assert kinds.count("faction_formed") == 1
    assert kinds.count("faction_left") == 3


# ══════════════════════════════════════════════════════════════════════════════
# Reputation (acceptance item 3)
# ══════════════════════════════════════════════════════════════════════════════

def test_reputation_math_and_zero_default():
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")

    # Nobody holds a relationship toward Dell ⇒ 0.
    assert world.reputation("agent_dell") == 0
    # Mean incoming trust: Ada has bram(50) + cora(50) toward her ⇒ 50.
    assert world.reputation("agent_ada") == 50

    world.agents["agent_bram"].relationships["agent_ada"].trust = -10
    assert world.reputation("agent_ada") == 20       # round((-10 + 50) / 2)

    # interactions == 0 relationships are EXCLUDED from the mean.
    world.agents["agent_dell"].relationships["agent_ada"] = RelationshipState(
        type="neutral", trust=-100, interactions=0)
    assert world.reputation("agent_ada") == 20

    # Dead raters are excluded (mean over LIVING agents only).
    world.kill_agent("agent_bram")
    assert world.reputation("agent_ada") == 50       # only Cora's 50 remains

    # Rounding: 11 and 10 ⇒ 10.5 ⇒ round() ⇒ 10 (banker's, pinned).
    world.agents["agent_cora"].relationships["agent_ada"].trust = 11
    world.agents["agent_dell"].relationships["agent_ada"].interactions = 1
    world.agents["agent_dell"].relationships["agent_ada"].trust = 10
    assert world.reputation("agent_ada") == 10


def test_reputation_surfaces_in_snapshot_agents():
    world = _trio_world()
    by_id = {a["id"]: a for a in world.to_snapshot()["agents"]}
    assert by_id["agent_ada"]["reputation"] == 50
    assert by_id["agent_bram"]["reputation"] == 50
    # …and the key VANISHES when factions are disabled (pre-E dict shape).
    world.params.factions = _factions(enabled=False)
    by_id = {a["id"]: a for a in world.to_snapshot()["agents"]}
    assert all("reputation" not in a for a in by_id.values())


# ══════════════════════════════════════════════════════════════════════════════
# Determinism + snapshot round-trip (acceptance item 4)
# ══════════════════════════════════════════════════════════════════════════════

def test_same_world_state_yields_identical_factions():
    a, b = _trio_world(), _trio_world()
    a.tick = b.tick = 77
    a.recompute_factions()
    b.recompute_factions()
    assert a.factions == b.factions                  # ids AND names identical


def test_factions_roundtrip_snapshot_and_absent_means_empty():
    world = _trio_world()
    world.tick = 40
    fid = world.recompute_factions()[0]["payload"]["faction_id"]

    snap = world.to_snapshot()
    assert snap["factions"] == {fid: {
        "name": "Ada's circle", "founded_tick": 40,
        "members": ["agent_ada", "agent_bram", "agent_cora"]}}

    restored = World.from_snapshot(snap, params=world.params)
    assert restored.factions == world.factions
    # Continuity survives the restore: a stable recompute keeps the id
    # (relationships round-trip too) and emits NOTHING.
    assert restored.recompute_factions() == []
    assert set(restored.factions) == {fid}

    # Absent key (every pre-E snapshot) ⇒ {}.
    pre_e = {k: v for k, v in snap.items() if k != "factions"}
    assert World.from_snapshot(pre_e).factions == {}


def test_faction_free_world_snapshot_has_no_factions_key():
    """The cap_demotions only-when-non-empty pattern: no factions ⇒ no key."""
    params = _params()
    params.factions = _factions()
    world = World(params=params, places=_places(),
                  agents=[_agent("agent_ada", "Ada")])
    assert "factions" not in world.to_snapshot()


# ══════════════════════════════════════════════════════════════════════════════
# enabled:false byte-identical + pre-E params shape (acceptance item 5)
# ══════════════════════════════════════════════════════════════════════════════

def test_enabled_false_is_byte_identical_and_checkless():
    """factions.enabled: false ⇒ NO recompute at all: a fully warm trio's
    snapshot agents block is byte-identical across round boundaries, with no
    factions or reputation keys anywhere (the exact pre-E shape)."""
    world = _trio_world(factions=_factions(enabled=False))
    before = json.dumps(world.to_snapshot(), sort_keys=True)
    for _ in range(9):
        world.next_agent()                           # crosses round boundaries
    assert world.recompute_factions() == []          # explicit call: inert
    assert world.pending_spawn_events == []
    assert world.factions == {}
    after = json.dumps(world.to_snapshot(), sort_keys=True)
    assert json.dumps(json.loads(before)["agents"], sort_keys=True) \
        == json.dumps(json.loads(after)["agents"], sort_keys=True)
    assert "factions" not in after
    assert "reputation" not in after


def test_absent_factions_block_behaves_like_defaults():
    """Defensive _fct_param accessor: a pre-E params object WITHOUT the block
    gets identical defaults (enabled, trust 25, min_size 3) — a warm trio
    forms on them."""
    world = _trio_world()
    del world.params.factions                        # pre-E params shape
    assert getattr(world.params, "factions", None) is None
    assert world._fct_param("faction_trust", 25) == 25
    assert world._fct_param("faction_min_size", 3) == 3
    assert _faction_kinds(world.recompute_factions()) == ["faction_formed"]


# ══════════════════════════════════════════════════════════════════════════════
# Events: agent ids only + diff-driven (no spam on stable rounds)
# ══════════════════════════════════════════════════════════════════════════════

def test_faction_events_carry_agent_ids_only():
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    _warm(world, "agent_dell", "agent_ada")
    events = list(world.recompute_factions())
    _cool(world, "agent_dell", "agent_ada", trust=0)
    events += world.recompute_factions()             # joined faction → left
    for a, b in (("agent_ada", "agent_bram"), ("agent_ada", "agent_cora"),
                 ("agent_bram", "agent_cora")):
        _cool(world, a, b, trust=0)
        _cool(world, b, a, trust=0)
    events += world.recompute_factions()             # dissolved
    kinds = {e["kind"] for e in events}
    assert kinds == {"faction_formed", "faction_left", "faction_dissolved"}
    for e in events:
        assert e["actor_id"] in world.agents         # EM-141: agent ids only
        assert e.get("target_id") is None
        assert e["actor_type"] == "system"


def test_many_stable_rounds_emit_zero_faction_events():
    """The diff rule: after formation, advancing MANY round boundaries with
    stable membership parks ZERO further faction events in the outbox."""
    world = _trio_world()
    world.next_agent()                               # first round boundary
    formed = world.drain_spawn_events()
    assert _faction_kinds(formed) == ["faction_formed"]

    start_round = world.round
    while world.round < start_round + 20:            # 20 more stable rounds
        world.next_agent()
    assert _faction_kinds(world.drain_spawn_events()) == []
    assert len(world.factions) == 1                  # still standing, same one


# ══════════════════════════════════════════════════════════════════════════════
# Round-boundary hook: births FIRST, then factions (contract order)
# ══════════════════════════════════════════════════════════════════════════════

def test_round_hook_runs_births_before_factions():
    """Two co-located partners birth a child at the round boundary; the
    newborn's family edges complete a 3-member component the SAME round —
    only possible when check_births runs BEFORE recompute_factions."""
    params = _params()
    params.children = ChildrenParams(birth_chance=1.0)
    params.factions = _factions()
    agents = [_agent("agent_ada", "Ada", location="hearth"),
              _agent("agent_bram", "Bram", location="hearth")]
    world = World(params=params, places=_places(), agents=agents)
    _warm(world, "agent_ada", "agent_bram", rel_type="partner")

    world.next_agent()                               # round boundary fires both
    events = world.drain_spawn_events()
    assert [e["kind"] for e in events] == [
        "child_spawned", "agent_spawned", "faction_formed"]
    child_id = events[0]["payload"]["child_id"]
    assert events[2]["payload"]["members"] == sorted(
        ["agent_ada", "agent_bram", child_id])
    assert events[2]["payload"]["name"] == "Ada's circle"


# ══════════════════════════════════════════════════════════════════════════════
# faction_of — the world-side prompt seam (B4 wires the runtime line)
# ══════════════════════════════════════════════════════════════════════════════

def test_faction_of_accessor():
    world = _trio_world()
    world.agents["agent_dell"] = _agent("agent_dell", "Dell")
    assert world.faction_of("agent_ada") is None     # nothing computed yet
    fid = world.recompute_factions()[0]["payload"]["faction_id"]

    got = world.faction_of("agent_bram")
    assert got == {"id": fid, "name": "Ada's circle",
                   "members": ["agent_ada", "agent_bram", "agent_cora"]}
    assert world.faction_of("agent_dell") is None    # not a member
    # The returned members list is a COPY — mutating it never leaks back.
    got["members"].append("intruder")
    assert world.factions[fid]["members"] == [
        "agent_ada", "agent_bram", "agent_cora"]


# ══════════════════════════════════════════════════════════════════════════════
# Config — world.factions block (EM-155 conventions)
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_factions_defaults_overrides_malformed():
    d = _parse_factions(None)
    assert (d.enabled, d.faction_trust, d.faction_min_size) == (True, 25, 3)
    assert _parse_factions("nonsense") == FactionParams()
    p = _parse_factions({"enabled": False, "faction_trust": -5,
                         "faction_min_size": 0})
    assert p.enabled is False
    assert p.faction_trust == -5                     # any int is legal
    assert p.faction_min_size == 1                   # clamped to >= 1
    q = _parse_factions({"faction_trust": "junk", "faction_min_size": "junk"})
    assert (q.enabled, q.faction_trust, q.faction_min_size) == (True, 25, 3)


def test_embedded_and_shipped_yaml_match_dataclass_defaults():
    """The EMBEDDED_WORLD_YAML mirror AND config/world.yaml parse to the same
    factions defaults as the dataclass (the EM-155 loader↔engine invariant)."""
    import yaml as _yaml
    from petridish.config.loader import EMBEDDED_WORLD_YAML, _parse_world
    params, _, _ = _parse_world(_yaml.safe_load(EMBEDDED_WORLD_YAML))
    assert params.factions == FactionParams()
    cfg = load_config()                              # shipped config/world.yaml
    assert cfg.world.factions == FactionParams()

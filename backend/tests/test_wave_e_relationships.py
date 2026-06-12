"""
Wave E / B1 — EM-113 relationship depth (contracts/wave-e.md §B1).

Covers the full B1 acceptance list:
  · since_tick round-trips snapshot + repository json; absent key ⇒ 0
  · give-driven trust 30 flips neutral→friend exactly once (one event,
    since_tick stamped; further gives don't re-emit)
  · steal-driven trust ≤ -40 flips rival→feud; -39 doesn't
  · set_relationship: partner below threshold rejected with guidance, at
    threshold accepted; family always rejected for agents
  · are_partners true only when mutual + both trusts ≥ threshold
  · relationship_changed events carry agent ids only (both endpoints) and
    ride the triggering action's turn chain (same turn_id)
  · pre-E snapshots restore byte-identical relationship state (since_tick 0,
    no transitions fired on restore)
  · config block parsing (defaults, overrides, malformed values)

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import json

from petridish.engine.world import (
    AgentState,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import (
    ModelProfile,
    RelationshipParams,
    WorldConfig,
    WorldParams,
    _parse_relationships,
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


def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]


def _agent(aid: str, name: str, location: str = "plaza",
           credits: int = 100) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=80.0, credits=credits)


def _world(agents: list[AgentState] | None = None) -> World:
    agents = agents if agents is not None else [
        _agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
    ]
    return World(params=_params(), places=_places(), agents=agents)


def _rel(world: World, a_id: str, b_id: str, *, type: str = "neutral",
         trust: int = 0, interactions: int = 0,
         since_tick: int = 0) -> RelationshipState:
    rel = RelationshipState(type=type, trust=trust, interactions=interactions,
                            since_tick=since_tick)
    world.agents[a_id].relationships[b_id] = rel
    return rel


# ══════════════════════════════════════════════════════════════════════════════
# since_tick — serialization round-trips (snapshot + repository json)
# ══════════════════════════════════════════════════════════════════════════════

def test_since_tick_roundtrips_snapshot():
    world = _world()
    world.tick = 42
    _rel(world, "agent_ada", "agent_bram",
         type="friend", trust=33, interactions=6, since_tick=17)

    restored = World.from_snapshot(world.to_snapshot())
    rel = restored.agents["agent_ada"].relationships["agent_bram"]
    assert (rel.type, rel.trust, rel.interactions, rel.since_tick) == (
        "friend", 33, 6, 17)


def test_since_tick_absent_in_snapshot_restores_zero():
    """Pre-E snapshots lack since_tick — additive key, absent ⇒ 0, and the
    relationship state otherwise restores byte-identical (no transitions fire
    on restore: thresholds only run on NEW trust mutations)."""
    world = _world()
    # Warm enough that the friend reflex WOULD fire on any new trust mutation —
    # restore alone must not flip it.
    _rel(world, "agent_ada", "agent_bram",
         type="neutral", trust=90, interactions=9)
    snap = world.to_snapshot()
    for agent_d in snap["agents"]:
        for rel_d in agent_d["relationships"].values():
            rel_d.pop("since_tick", None)  # simulate a pre-E snapshot

    restored = World.from_snapshot(snap)
    rel = restored.agents["agent_ada"].relationships["agent_bram"]
    assert (rel.type, rel.trust, rel.interactions) == ("neutral", 90, 9)
    assert rel.since_tick == 0
    assert restored.pending_relationship_events == []


def test_since_tick_in_repository_relationships_json():
    world = _world()
    _rel(world, "agent_ada", "agent_bram",
         type="feud", trust=-55, interactions=8, since_tick=23)
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    repo.save_agent(run_id, world.agents["agent_ada"], tick=30)

    row = repo._conn.execute(
        "SELECT relationships_json FROM agents WHERE id='agent_ada'"
    ).fetchone()
    rels = json.loads(row[0])
    assert rels["agent_bram"] == {
        "type": "feud", "trust": -55, "interactions": 8, "since_tick": 23}


# ══════════════════════════════════════════════════════════════════════════════
# Reflex transition: neutral|ally → friend
# ══════════════════════════════════════════════════════════════════════════════

def test_gives_to_trust_30_flip_neutral_to_friend_exactly_once():
    """give×5 from a warming start (trust 5) reaches trust 30 with
    interactions 5 → friend, exactly one event, since_tick stamped; further
    gives don't re-emit."""
    world = _world()
    world.tick = 7
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", type="neutral", trust=5)

    for _ in range(4):
        ok, reason = world.action_give(ada, bram, 1)
        assert ok, reason
    rel = ada.relationships["agent_bram"]
    assert rel.type == "neutral"          # trust 25, interactions 4 — not yet
    assert world.pending_relationship_events == []

    ok, _ = world.action_give(ada, bram, 1)   # trust 30, interactions 5
    assert ok
    assert rel.type == "friend"
    assert rel.since_tick == 7
    events = world.drain_relationship_events()
    assert len(events) == 1
    evt = events[0]
    assert evt["kind"] == "relationship_changed"
    assert evt["payload"] == {
        "from_type": "neutral", "to_type": "friend",
        "trust": 30, "since_tick": 7}
    assert "are now friends" in evt["text"]

    # Further gives: type already friend — no re-emit.
    world.action_give(ada, bram, 1)
    world.action_give(ada, bram, 1)
    assert world.drain_relationship_events() == []
    assert rel.type == "friend"


def test_friend_flip_requires_both_trust_and_interactions():
    """Trust ≥ 30 with interactions < 5 does NOT flip (and vice versa)."""
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    # High trust, too few interactions.
    _rel(world, "agent_ada", "agent_bram", type="neutral", trust=28)
    world.action_give(ada, bram, 1)       # trust 33, interactions 1
    assert ada.relationships["agent_bram"].type == "neutral"
    # Enough interactions, low trust.
    _rel(world, "agent_ada", "agent_bram", type="neutral", trust=0,
         interactions=10)
    world.action_give(ada, bram, 1)       # trust 5, interactions 11
    assert ada.relationships["agent_bram"].type == "neutral"
    assert world.drain_relationship_events() == []


def test_ally_also_flips_to_friend():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", type="ally", trust=27,
         interactions=9)
    world.action_give(ada, bram, 1)       # trust 32, interactions 10
    rel = ada.relationships["agent_bram"]
    assert rel.type == "friend"
    events = world.drain_relationship_events()
    assert len(events) == 1
    assert events[0]["payload"]["from_type"] == "ally"


# ══════════════════════════════════════════════════════════════════════════════
# Reflex transition: rival|enemy → feud
# ══════════════════════════════════════════════════════════════════════════════

def test_steal_driven_trust_minus_40_flips_rival_to_feud():
    world = _world()
    world.tick = 11
    ada = world.agents["agent_ada"]    # the thief
    bram = world.agents["agent_bram"]  # the victim
    _rel(world, "agent_bram", "agent_ada", type="rival", trust=-30,
         interactions=3)

    ok, reason, _ = world.action_steal(ada, bram)
    assert ok, reason
    rel = bram.relationships["agent_ada"]   # victim's -10 → -40
    assert rel.type == "feud"
    assert rel.since_tick == 11
    events = world.drain_relationship_events()
    feuds = [e for e in events if e["payload"]["to_type"] == "feud"]
    assert len(feuds) == 1
    assert "hardened into a feud" in feuds[0]["text"]
    assert feuds[0]["actor_id"] == "agent_bram"
    assert feuds[0]["target_id"] == "agent_ada"


def test_trust_minus_39_does_not_flip_to_feud():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_bram", "agent_ada", type="rival", trust=-29,
         interactions=3)
    world.action_steal(ada, bram)           # victim's trust -29 → -39
    rel = bram.relationships["agent_ada"]
    assert rel.trust == -39
    assert rel.type == "rival"
    assert all(e["payload"]["to_type"] != "feud"
               for e in world.drain_relationship_events())


def test_enemy_also_hardens_into_feud():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_bram", "agent_ada", type="enemy", trust=-35,
         interactions=2)
    world.action_steal(ada, bram)           # -35 → -45 ≤ -40
    assert bram.relationships["agent_ada"].type == "feud"


def test_steal_escalation_never_downgrades_a_feud():
    """The pre-E rival/enemy escalation in action_steal stays beneath the
    reflex transitions: a feud (set by the -40 reflex in the same steal) is
    never overwritten back to enemy."""
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_bram", "agent_ada", type="rival", trust=-95,
         interactions=5)
    world.action_steal(ada, bram)           # clamp to -100 → feud
    assert bram.relationships["agent_ada"].type == "feud"
    world.drain_relationship_events()
    # A second steal must keep the feud (escalation block skips it).
    world.action_steal(ada, bram)
    assert bram.relationships["agent_ada"].type == "feud"
    assert world.drain_relationship_events() == []


def test_types_never_auto_downgrade():
    """A friend whose trust collapses stays a friend (drama persists); only an
    explicit set_relationship overwrites."""
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", type="friend", trust=31,
         interactions=8)
    for _ in range(5):
        world.action_insult(ada, bram)      # -10 each toward bram… wait: ada→bram
    rel = ada.relationships["agent_bram"]
    assert rel.trust < 0
    assert rel.type == "friend"
    assert world.drain_relationship_events() == []


# ══════════════════════════════════════════════════════════════════════════════
# set_relationship — extended vocabulary + guards
# ══════════════════════════════════════════════════════════════════════════════

def test_partner_below_threshold_rejected_with_guidance():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", trust=39, interactions=10)
    ok, reason = world.action_set_relationship(ada, bram, "partner")
    assert not ok
    assert "barely know them" in reason
    assert ada.relationships["agent_bram"].type == "neutral"
    assert world.drain_relationship_events() == []


def test_partner_at_threshold_accepted_with_event():
    world = _world()
    world.tick = 19
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", trust=40, interactions=10)
    ok, reason = world.action_set_relationship(ada, bram, "partner")
    assert ok, reason
    rel = ada.relationships["agent_bram"]
    assert rel.type == "partner"
    assert rel.since_tick == 19
    assert rel.trust == 40                  # declaration preserves trust
    events = world.drain_relationship_events()
    assert len(events) == 1
    assert events[0]["payload"]["to_type"] == "partner"


def test_family_always_rejected_for_agents():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", trust=100, interactions=50)
    ok, reason = world.action_set_relationship(ada, bram, "family")
    assert not ok
    assert "birth" in reason
    assert world.drain_relationship_events() == []


def test_mentor_and_feud_declarable_legacy_types_still_work():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    for rel_type in ("mentor", "feud", "ally", "rival", "neutral", "friend",
                     "enemy"):
        ok, reason = world.action_set_relationship(ada, bram, rel_type)
        assert ok, f"{rel_type}: {reason}"
        assert ada.relationships["agent_bram"].type == rel_type
    ok, reason = world.action_set_relationship(ada, bram, "soulmate")
    assert not ok
    assert "invalid relationship type" in reason


def test_set_relationship_same_type_emits_no_event():
    world = _world()
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", type="ally", trust=10,
         since_tick=4)
    ok, _ = world.action_set_relationship(ada, bram, "ally")
    assert ok
    rel = ada.relationships["agent_bram"]
    assert rel.since_tick == 4              # unchanged: no type transition
    assert world.drain_relationship_events() == []


# ══════════════════════════════════════════════════════════════════════════════
# are_partners — the mutual-consent predicate
# ══════════════════════════════════════════════════════════════════════════════

def test_are_partners_requires_mutual_type_and_both_trusts():
    world = _world()
    a, b = "agent_ada", "agent_bram"
    # One-directional partner: not partners.
    _rel(world, a, b, type="partner", trust=50)
    assert not world.are_partners(a, b)
    # Mutual type but one trust below threshold: not partners.
    _rel(world, b, a, type="partner", trust=39)
    assert not world.are_partners(a, b)
    # Mutual + both ≥ threshold: partners (symmetric).
    _rel(world, b, a, type="partner", trust=40)
    assert world.are_partners(a, b)
    assert world.are_partners(b, a)
    # Type mismatch on one side: not partners.
    _rel(world, a, b, type="friend", trust=50)
    assert not world.are_partners(a, b)
    # Unknown agents: never partners.
    assert not world.are_partners(a, "agent_ghost")


# ══════════════════════════════════════════════════════════════════════════════
# Event endpoints + the action turn chain (real _execute_turn path)
# ══════════════════════════════════════════════════════════════════════════════

def _make_loop(script: list):
    params = _params(energy_decay_per_turn=0.0)
    agents = [
        _agent("agent_ada", "Ada", location="plaza"),
        _agent("agent_bram", "Bram", location="plaza"),
    ]
    world = World(params=params, places=_places(), agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles,
                    adapter_overrides={"mock": MockProvider(script=script)})
    for a in agents:
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo


async def test_relationship_changed_rides_the_action_turn_chain():
    """A give that trips the friend reflex emits relationship_changed in the
    SAME turn chain (shared turn_id) as the give's economy event, with agent
    ids on both endpoints (EM-141)."""
    loop, world, repo = _make_loop(
        [{"action": "give", "args": {"target": "Bram", "amount": 1}}])
    _rel(world, "agent_ada", "agent_bram", type="neutral", trust=28,
         interactions=4)

    agent = world.next_agent()
    assert agent.id == "agent_ada"
    await loop._execute_turn(agent)

    events = repo.get_events(loop._run_id, order="asc")
    by_kind = {e["kind"]: e for e in events}
    assert "economy" in by_kind
    rel_evt = by_kind.get("relationship_changed")
    assert rel_evt is not None
    assert rel_evt["turn_id"] == by_kind["economy"]["turn_id"]
    assert rel_evt["actor_id"] == "agent_ada"
    assert rel_evt["target_id"] == "agent_bram"
    payload = json.loads(rel_evt["payload_json"]) if "payload_json" in rel_evt \
        else rel_evt.get("payload", {})
    assert payload["from_type"] == "neutral"
    assert payload["to_type"] == "friend"
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "friend"


async def test_no_transition_no_relationship_changed_event():
    loop, world, repo = _make_loop(
        [{"action": "give", "args": {"target": "Bram", "amount": 1}}])
    agent = world.next_agent()
    await loop._execute_turn(agent)
    kinds = [e["kind"] for e in repo.get_events(loop._run_id, order="asc")]
    assert "relationship_changed" not in kinds


# ══════════════════════════════════════════════════════════════════════════════
# Config — world.relationships block (EM-155 conventions)
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_relationships_defaults_and_overrides():
    d = _parse_relationships(None)
    assert (d.friend_trust, d.friend_interactions, d.feud_trust,
            d.partner_trust_threshold) == (30, 5, -40, 40)
    assert _parse_relationships("nonsense") == RelationshipParams()
    p = _parse_relationships({"friend_trust": 10, "feud_trust": -20,
                              "partner_trust_threshold": "junk"})
    assert p.friend_trust == 10
    assert p.feud_trust == -20
    assert p.friend_interactions == 5          # absent → default
    assert p.partner_trust_threshold == 40     # malformed → default


def test_embedded_and_shipped_yaml_match_dataclass_defaults():
    """The EMBEDDED_WORLD_YAML mirror AND config/world.yaml parse to the same
    defaults as the dataclass (the EM-155 loader↔engine sync invariant)."""
    import yaml as _yaml
    from petridish.config.loader import EMBEDDED_WORLD_YAML, _parse_world
    params, _, _ = _parse_world(_yaml.safe_load(EMBEDDED_WORLD_YAML))
    assert params.relationships == RelationshipParams()
    cfg = load_config()                      # shipped config/world.yaml
    assert cfg.world.relationships == RelationshipParams()


def test_engine_reads_thresholds_from_config():
    params = _params()
    params.relationships = RelationshipParams(
        friend_trust=10, friend_interactions=1, feud_trust=-15,
        partner_trust_threshold=12)
    world = World(params=params,
                  places=_places(),
                  agents=[_agent("agent_ada", "Ada"),
                          _agent("agent_bram", "Bram")])
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    # friend flips at the configured (lower) bar.
    _rel(world, "agent_ada", "agent_bram", trust=5)
    world.action_give(ada, bram, 1)            # trust 10, interactions 1
    assert ada.relationships["agent_bram"].type == "friend"
    world.drain_relationship_events()
    # partner gate uses the configured threshold.
    _rel(world, "agent_bram", "agent_ada", trust=12, interactions=1)
    ok, _ = world.action_set_relationship(bram, ada, "partner")
    assert ok
    # feud flips at the configured bar.
    _rel(world, "agent_bram", "agent_ada", type="rival", trust=-10,
         interactions=2)
    world.action_insult(ada, bram)             # bram's trust toward ada: -15
    assert bram.relationships["agent_ada"].type == "feud"


def test_absent_relationships_block_behaves_like_defaults():
    """Defensive _rel_param accessor: a params object WITHOUT the block (a
    pre-E WorldParams stand-in) gets identical defaults — transitions behave
    exactly as with the shipped block."""
    params = _params()
    del params.relationships                 # pre-E params shape
    world = World(params=params,
                  places=_places(),
                  agents=[_agent("agent_ada", "Ada"),
                          _agent("agent_bram", "Bram")])
    assert getattr(world.params, "relationships", None) is None
    assert world._rel_param("friend_trust", 30) == 30
    assert world._rel_param("partner_trust_threshold", 40) == 40
    # Behavior matches the defaults: trust 30 + interactions 5 still flips.
    ada = world.agents["agent_ada"]
    bram = world.agents["agent_bram"]
    _rel(world, "agent_ada", "agent_bram", trust=25, interactions=4)
    world.action_give(ada, bram, 1)          # trust 30, interactions 5
    assert ada.relationships["agent_bram"].type == "friend"

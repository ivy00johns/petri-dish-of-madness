"""
Wave E QE gate — adversarial cross-batch verification (contracts/wave-e.md
§Gates). Per-batch lenses verified each batch in isolation; this file proves
what only the COMPOSED wave can show:

  1. COMPOSITION CHAIN (B1+B2+B3+B4): mutual partners → a birth at a real
     round boundary → the newborn's engine-assigned family edges complete a
     ≥3-member warm component → faction_formed rides the SAME boundary drain
     BEHIND the birth events (births-before-factions contract order) → and on
     the next due LLM turn a member's actually-assembled prompt carries the
     "Your circle:" line. One scenario through the real World scheduler + the
     real TickLoop turn path, scripted mock provider only.

  2. MIRACLE→SOCIETY CHAIN (B5+B1+B3): calm_spirits on a pair sitting at
     trust 28 / interactions ≥ 5 flips them to friends INSIDE the miracle's
     own event batch (the B1 reflex seam fired through _update_trust), and at
     the next round boundary that new warm edge completes a 3-member faction.
     Plus the salience half: a god_miracle pushed through the runtime makes a
     REMOTE background agent's next due turn salient (witnessed_importance)
     while the miracle itself adds ZERO llm_call rows.
     ⚠ QE FINDING (filed in coordination/qa-report.json): the production
     /api/god/intervene handler only _emit_event()s the batch — it never
     calls runtime.push_event, so the salience chain below is asserted at the
     runtime seam (the contracted constants) and is NOT reachable from the
     god console today (same pre-existing gap as API-injected random_event).

  3. WAVE-LEVEL FREE-SCALE: a default-wave-config world (children/factions/
     miracles all enabled — the shipped defaults) with NO partners and NO
     miracles run for 30 full rounds produces EXACTLY the pre-E llm_call
     count computed from D2/D3 cadence math. Derivation in the test. The
     wave's round-boundary hooks (check_births + recompute_factions) run
     every round here and must add zero calls, zero agents, zero events.

  4. FORK FIDELITY (EM-101/EM-155): a world carrying ALL wave-E state at
     once — typed relationships with since_tick, a born child with parents,
     a live faction, an active send_rain miracle — survives
     to_snapshot → from_snapshot with a byte-equal re-snapshot, and behavior
     RESUMES: rain still buffs forage, the faction is stable (zero churn
     events), and the derived pair cooldown still blocks a re-birth until
     exactly its tick — then fires (proving the gate is live, not vestigial).

Deterministic and offline (scripted fakes, ':memory:' DBs, no network, no
real keys — the wave's verification law). CRITICAL suite rule:
petridish.engine.world is imported BEFORE petridish.agents.runtime.
"""
from __future__ import annotations

import asyncio
import json

from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState,
)
from petridish.config.loader import (
    CadenceParams, ChildrenParams, ModelProfile, WorldConfig, WorldParams,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


IDLE = {"action": "idle", "args": {}}

CARDS = [
    {"name": "Mox", "personality": "Reads hidden messages in typos."},
    {"name": "Vesper", "personality": "Pitches a new scheme to anyone."},
]


class ScriptedProvider:
    """The test_wave_d2_cadence ByAgentProvider idiom: per-agent scripts +
    prompt capture. len(prompts) IS the router call count — the free-scale
    proof surface (a reflex turn must never appear here)."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list] | None = None):
        self._scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []  # (agent_id, system content)

    def set_world(self, world: object) -> None:  # router.inject_world seam
        self._world = world

    @staticmethod
    def _extract(messages: list[dict]) -> tuple[str, str]:
        agent_id, system = "unknown", ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                for line in system.split("\n"):
                    line = line.strip()
                    if line.startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
        return agent_id, system

    async def chat(self, messages, *, max_tokens, temperature):
        agent_id, system = self._extract(messages)
        self.prompts.append((agent_id, system))
        script = self._scripts.get(agent_id) or [IDLE]
        i = min(self._pos.get(agent_id, 0), len(script) - 1)
        self._pos[agent_id] = i + 1
        return json.dumps(script[i])


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        memory_window=12,
        snapshot_interval_ticks=100,
        # Wildcard OFF / streak floor parked so reflex-vs-LLM counts are
        # exact (the established cadence-test convention; EM-160 has its own
        # dedicated proofs in test_wave_d2_cadence.py).
        cadence=CadenceParams(spontaneity_chance=0.0, reflex_streak_limit=999),
    )
    base.update(overrides)
    return WorldParams(**base)


def _agent(aid: str, name: str, location: str, tier: str = "protagonist",
           credits: int = 50, energy: float = 80.0) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=energy, credits=credits,
                      cadence_tier=tier)


def _harness(agents: list[AgentState], params: WorldParams,
             places: list[PlaceState]):
    """Real World + real TickLoop + scripted mock adapter (no network)."""
    world = World(params=params, places=places, agents=agents)
    provider = ScriptedProvider()
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": provider},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    return loop, world, repo, runtime, provider


def _llm_rows(repo: SQLiteRepository, loop: TickLoop) -> list[dict]:
    return repo.get_events(loop._run_id or 1, kinds=["llm_call"], order="asc")


# ══════════════════════════════════════════════════════════════════════════════
# 1. COMPOSITION CHAIN — partners → birth → faction → "Your circle:" prompt
# ══════════════════════════════════════════════════════════════════════════════

def test_composition_chain_birth_completes_faction_and_prompt_carries_circle():
    """B1 partner consent → B2 birth at the round boundary → the newborn's
    engine-assigned family edges complete a 3-warm component → B3
    faction_formed in the SAME boundary drain, BEHIND the birth events → the
    very next due LLM turn (a member, through the real loop) assembles a
    prompt carrying the B4-wired 'Your circle:' line. All through next_agent()
    + TickLoop._execute_turn — no helper shortcuts."""
    params = _params(children=ChildrenParams(birth_chance=1.0))
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="hearth", name="Hearth House", x=10, y=0, kind="home",
                   capacity=10),
    ]
    agents = [_agent("agent_ada", "Ada", "hearth"),
              _agent("agent_bram", "Bram", "hearth")]
    loop, world, repo, runtime, provider = _harness(agents, params, places)
    # Pin the casting pool AFTER the loop seeded the shipped library, so the
    # child's identity is deterministic for this test.
    world.set_birth_casting(CARDS, ["mock"])

    # B1: mutual partners at/above the trust threshold (the consent mechanic).
    for x, y in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada")):
        world.agents[x].relationships[y] = RelationshipState(
            type="partner", trust=50, interactions=10)
    assert world.are_partners("agent_ada", "agent_bram")

    # Drive rounds 1-3 through the REAL scheduler + loop turn path.
    turn_actors: list[str] = []
    while True:
        agent = world.next_agent()
        assert agent is not None
        if world.round > 3:
            break
        turn_actors.append(agent.id)
        asyncio.run(loop._execute_turn(agent))

    # The birth happened at the round-1 boundary: exactly ONE child, ever
    # (round-2/3 boundaries re-check and the derived pair cooldown blocks).
    children = [a for a in world.agents.values() if a.parents]
    assert len(children) == 1
    child = children[0]
    assert child.name == "Mox"
    assert child.cadence_tier == "background"          # free-scale law
    assert child.parents == ["agent_ada", "agent_bram"]
    assert world.agents["agent_ada"].credits == 44     # both parents debited
    assert world.agents["agent_bram"].credits == 44    # (50 - 6, a sink)

    # The SAME boundary formed the faction — birth events FIRST, then the
    # faction event, all drained together as standalone system rows.
    run_id = loop._run_id or 1
    rows = repo.get_events(
        run_id, kinds=["child_spawned", "agent_spawned", "faction_formed"],
        order="asc")
    assert [r["kind"] for r in rows] == [
        "child_spawned", "agent_spawned", "faction_formed"]
    assert all(r["turn_id"] is None for r in rows)
    assert all(r["tick"] == 0 for r in rows)           # the round-1 boundary

    # The faction is the newborn-completed 3-warm component, deterministic
    # name (lowest founding member id = agent_ada), agent ids ONLY (EM-141).
    formed = rows[2]
    assert formed["actor_id"] == "agent_ada"
    assert formed["target_id"] is None
    assert formed["payload"]["name"] == "Ada's circle"
    assert sorted(formed["payload"]["members"]) == sorted(
        ["agent_ada", "agent_bram", child.id])
    assert len(world.factions) == 1

    # No faction event spam on the stable round-2/3 boundaries (diff-driven).
    assert len(repo.get_events(run_id, kinds=["faction_formed"])) == 1
    assert repo.get_events(
        run_id, kinds=["faction_joined", "faction_left", "faction_dissolved"]
    ) == []

    # The NEXT due LLM turn after the boundary was Ada's (round-1, turn 1):
    # her actually-assembled system prompt carries the one-line circle.
    ada_prompts = [s for (aid, s) in provider.prompts if aid == "agent_ada"]
    assert ada_prompts, "Ada must have taken LLM turns"
    assert "Your circle: Ada's circle (3 members)" in ada_prompts[0]

    # Free-scale composition: the background child consulted the LLM exactly
    # ZERO times across rounds 1-3 (due only at round 10), so the call count
    # is the two protagonists' rounds only.
    assert turn_actors == ["agent_ada", "agent_bram"] * 3
    assert len(provider.prompts) == 6
    assert {aid for (aid, _) in provider.prompts} == {"agent_ada", "agent_bram"}
    assert len(_llm_rows(repo, loop)) == 6


# ══════════════════════════════════════════════════════════════════════════════
# 2. MIRACLE→SOCIETY CHAIN — calm_spirits → friend flip → faction; salience
# ══════════════════════════════════════════════════════════════════════════════

def _society_world():
    params = _params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        _agent("agent_ada", "Ada", "plaza"),
        _agent("agent_bram", "Bram", "plaza"),
        _agent("agent_cora", "Cora", "plaza"),
        # The REMOTE background witness: alone at the market, no relationships.
        _agent("agent_dot", "Dot", "market", tier="background"),
    ]
    loop, world, repo, runtime, provider = _harness(agents, params, places)
    # ada↔bram: already warm (ally) but only a 2-component — no faction yet.
    # interactions 1 keeps the calm nudge from ALSO flipping them to friends
    # (the B1 friend reflex needs interactions ≥ 5), isolating the chain.
    for x, y in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada")):
        world.agents[x].relationships[y] = RelationshipState(
            type="ally", trust=30, interactions=1)
    # bram↔cora: the contracted shape — trust 28, interactions ≥ 5, neutral.
    for x, y in (("agent_bram", "agent_cora"), ("agent_cora", "agent_bram")):
        world.agents[x].relationships[y] = RelationshipState(
            type="neutral", trust=28, interactions=5)
    return loop, world, repo, runtime, provider


def test_calm_spirits_friend_flip_completes_a_faction_next_boundary():
    loop, world, repo, runtime, provider = _society_world()
    world.tick = 9

    # Sanity: pre-miracle the warm graph has no component of 3.
    assert world.recompute_factions() == []
    assert world.factions == {}
    world.drain_spawn_events()

    # The miracle. The friend flips ride INSIDE the miracle's own batch (the
    # B1 reflex seam fired through _update_trust, drained by god_miracle).
    events = world.god_intervene("calm_spirits")
    assert [e["kind"] for e in events] == [
        "god_miracle", "relationship_changed", "relationship_changed"]
    flips = events[1:]
    assert [(e["actor_id"], e["target_id"]) for e in flips] == [
        ("agent_bram", "agent_cora"), ("agent_cora", "agent_bram")]
    for e in flips:
        assert e["payload"]["from_type"] == "neutral"
        assert e["payload"]["to_type"] == "friend"
        assert e["payload"]["trust"] == 31          # 28 + calm_trust_bonus 3
        assert e["payload"]["since_tick"] == 9
    # ally pair nudged but NOT flipped (interactions still under 5).
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "ally"
    assert world.agents["agent_ada"].relationships["agent_bram"].trust == 33
    # ONE-TIME kind: every living mood lifted (even the remote background
    # agent), and no timed entry left behind.
    assert all(a.mood == "hopeful" for a in world.living_agents())
    assert world.active_miracles == []
    # The B1 outbox was drained INTO the batch — nothing left parked.
    assert world.pending_relationship_events == []

    # Emit the batch exactly as /api/god/intervene does (turn_id null) and
    # prove the miracle itself added ZERO llm_call rows.
    before = len(_llm_rows(repo, loop))
    for e in events:
        e.setdefault("turn_id", None)
        loop._emit_event(e)
    assert len(_llm_rows(repo, loop)) == before == 0
    assert len(repo.get_events(loop._run_id or 1,
                               kinds=["relationship_changed"])) == 2

    # NEXT round boundary: the new warm edge bridges ada—bram—cora into a
    # 3-component → faction_formed (Dot, edgeless, stays outside).
    first = world.next_agent()
    assert first is not None and world.round == 1
    drained = world.drain_spawn_events()
    assert [e["kind"] for e in drained] == ["faction_formed"]
    assert sorted(drained[0]["payload"]["members"]) == [
        "agent_ada", "agent_bram", "agent_cora"]
    assert drained[0]["payload"]["name"] == "Ada's circle"
    assert world.faction_of("agent_dot") is None


def test_miracle_makes_remote_background_agent_salient_without_calls():
    """The contracted salience chain (B5 item 3) at the runtime seam: a
    god_miracle pushed through push_event reaches a REMOTE background agent
    (global witness, weight 2.0), making its next due turn salient via
    witnessed_importance — while the miracle adds zero llm_call rows.

    NOTE (QE finding, coordination/qa-report.json): the production
    /api/god/intervene handler emits the batch (_emit_event → DB + WS) but
    never calls runtime.push_event, so this chain is NOT reachable from the
    god console today. This test pins the contracted runtime semantics so the
    one-line app.py wiring fix lands on proven ground."""
    loop, world, repo, runtime, provider = _society_world()
    dot = world.agents["agent_dot"]

    # Baseline: one LLM turn for Dot (first_turn salience) so the later
    # trigger set is EXACTLY witnessed_importance and nothing else.
    asyncio.run(loop._execute_turn(dot))
    assert len(provider.prompts) == 1
    assert dot.id not in runtime._witnessed_since_llm
    salient, triggers = runtime._background_salience(dot)
    assert (salient, triggers) == (False, [])

    # Cast send_rain; emit as the API does; the miracle makes zero calls.
    before = len(_llm_rows(repo, loop))
    events = world.god_intervene("send_rain")
    assert [e["kind"] for e in events] == ["god_miracle"]
    for e in events:
        e.setdefault("turn_id", None)
        loop._emit_event(e)
    assert len(_llm_rows(repo, loop)) == before

    # The runtime seam: pushing the stamped event makes the REMOTE
    # background agent (different place, no actor/target match) a witness.
    runtime.push_event({**events[0], "tick": world.tick})
    assert any(m["kind"] == "god_miracle"
               for m in runtime._memory.get(dot.id, []))
    assert runtime._importance.get(dot.id) == 2.0      # the ratified weight
    assert dot.id in runtime._witnessed_since_llm
    salient, triggers = runtime._background_salience(dot)
    assert salient and triggers == ["witnessed_importance"]

    # And the salient due turn really consults the LLM — exactly one more
    # call, after which the witness flag is consumed.
    asyncio.run(loop._execute_turn(dot))
    assert len(provider.prompts) == 2
    assert provider.prompts[-1][0] == dot.id
    assert dot.id not in runtime._witnessed_since_llm


# ══════════════════════════════════════════════════════════════════════════════
# 3. WAVE-LEVEL FREE-SCALE — 30 rounds at wave defaults == pre-E cadence math
# ══════════════════════════════════════════════════════════════════════════════

def test_wave_default_world_llm_call_count_equals_pre_e_cadence_math():
    """The wave's free-scale law at WORLD level, not per-feature: a world
    running with every wave-E block at its shipped default (children,
    factions, miracles all enabled: true) but with no partners and no
    miracles cast must produce EXACTLY the llm_call count the pre-E cadence
    machinery (D2 EM-158/159 + D3) predicts — the round-boundary hooks
    check_births() and recompute_factions() run on all 30 boundaries here
    and must add zero calls, zero agents, zero events.

    PRE-E EXPECTATION (derivation): rounds 1..30, wildcard off, decay 0,
    no homes (reflex = forage, no movement → co-location never changes),
    nothing salient ever happens after each agent's baseline:
      · protagonist × 2  — due EVERY round ............ 2 × 30 = 60 llm_calls
      · supporting  × 1  — due round % 3 == 0 ......... 10     llm_calls
      · background  × 1  — due round % 10 == 0 (10/20/30):
          round 10 = its FIRST due turn → first_turn salience → 1 llm_call;
          rounds 20/30 → nothing salient → reflex, ZERO llm_call rows.
      TOTAL = 60 + 10 + 1 = 71 llm_calls over 73 executed turns.
    Pre-E code yields the identical count (the cadence machinery is
    untouched by wave E); any wave-E standing call would break equality."""
    params = _params()
    # Wave-E blocks deliberately NOT overridden: the WorldParams defaults are
    # the shipped enabled:true blocks (pinned by each batch's config tests).
    assert params.children.enabled is True
    assert params.factions.enabled is True
    assert params.miracles.enabled is True

    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        _agent("agent_ada", "Ada", "plaza"),
        _agent("agent_bob", "Bob", "plaza"),
        _agent("agent_sup", "Sup", "plaza", tier="supporting"),
        _agent("agent_bgr", "Bgr", "plaza", tier="background"),
    ]
    loop, world, repo, runtime, provider = _harness(agents, params, places)

    executed: list[tuple[int, str]] = []
    while True:
        agent = world.next_agent()
        assert agent is not None
        if world.round > 30:
            break
        executed.append((world.round, agent.id))
        asyncio.run(loop._execute_turn(agent))

    # The cadence-math turn ledger.
    assert len(executed) == 73
    assert sum(1 for _, aid in executed if aid == "agent_ada") == 30
    assert sum(1 for _, aid in executed if aid == "agent_bob") == 30
    assert [r for r, aid in executed if aid == "agent_sup"] == \
        list(range(3, 31, 3))
    assert [r for r, aid in executed if aid == "agent_bgr"] == [10, 20, 30]

    # THE seam assertion: llm_call rows == 71 == the pre-E expectation, and
    # the router really made exactly that many calls (one attempt each).
    assert len(_llm_rows(repo, loop)) == 71
    assert len(provider.prompts) == 71
    bgr_calls = [aid for (aid, _) in provider.prompts if aid == "agent_bgr"]
    assert len(bgr_calls) == 1                       # first_turn only

    # And the wave's hooks stayed inert: no births, no factions, no events
    # of any of the 8 new kinds, population unchanged.
    assert len(world.living_agents()) == 4
    assert all(not a.parents for a in world.agents.values())
    assert world.factions == {}
    assert world.active_miracles == []
    assert repo.get_events(loop._run_id or 1, kinds=[
        "relationship_changed", "child_spawned", "faction_formed",
        "faction_joined", "faction_left", "faction_dissolved",
        "god_miracle", "miracle_expired",
    ]) == []


# ══════════════════════════════════════════════════════════════════════════════
# 4. FORK FIDELITY — all wave-E state live → byte-equal round-trip + resume
# ══════════════════════════════════════════════════════════════════════════════

def test_fork_fidelity_all_wave_e_state_roundtrips_and_behavior_resumes():
    """EM-101 fork path × EM-155 invariant with EVERY wave-E surface live at
    once: typed relationships with since_tick, a born child with parents +
    family ties, a faction, an active send_rain miracle. to_snapshot →
    from_snapshot → to_snapshot must be byte-equal (json-serialized,
    sorted keys), and the restored world must BEHAVE: rain still buffs
    forage, the faction recompute is a zero-event no-op, the derived pair
    cooldown blocks a re-birth until exactly its boundary tick, and the rain
    expires on schedule exactly once."""
    params = _params(children=ChildrenParams(birth_chance=1.0))
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="hearth", name="Hearth House", x=10, y=0, kind="home",
                   capacity=10),
    ]
    agents = [_agent("agent_ada", "Ada", "hearth"),
              _agent("agent_bram", "Bram", "hearth")]
    world = World(params=params, places=places, agents=agents)
    world.town_name = "Petriville"

    # B1 state: typed partner edges with a non-zero since_tick.
    for x, y in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada")):
        world.agents[x].relationships[y] = RelationshipState(
            type="partner", trust=50, interactions=10, since_tick=7)

    # B2 state: a real birth at tick 12 (family ties stamp the cooldown).
    world.tick = 12
    birth_events = world.check_births(CARDS)
    assert [e["kind"] for e in birth_events] == ["child_spawned",
                                                 "agent_spawned"]
    child = world.agents[birth_events[0]["payload"]["child_id"]]
    assert child.parents == ["agent_ada", "agent_bram"]
    # Documented from_snapshot limit (pinned in test_w11b): beliefs serialize
    # as a count only and restore empty — cleared here so byte-equality
    # exercises the wave-E keys, not the pre-existing beliefs limitation.
    child.beliefs = []

    # B3 state: the family+partner component is a live faction.
    formed = world.recompute_factions()
    assert [e["kind"] for e in formed] == ["faction_formed"]
    assert len(world.factions) == 1
    fid = next(iter(world.factions))

    # B5 state: an active rain miracle (until 15 + 2 days × 20 turns = 55).
    world.tick = 15
    cast = world.god_intervene("send_rain")
    assert cast[0]["payload"]["until_tick"] == 55
    assert world.miracle_active("send_rain")

    # Outboxes are transient by design — drained before the fork point (the
    # loop drains them at the turn that follows any boundary).
    world.drain_spawn_events()
    world.drain_relationship_events()

    # ── The EM-155 invariant: byte-equal re-snapshot through the fork seam ──
    snap = world.to_snapshot()
    restored = World.from_snapshot(snap, params=params)
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
        json.dumps(snap, sort_keys=True)

    # Spot the wave-E keys actually crossed (guards against a vacuous pass).
    assert snap["factions"][fid]["members"] == sorted(
        ["agent_ada", "agent_bram", child.id])
    assert snap["active_miracles"] == [{"kind": "send_rain",
                                        "until_tick": 55}]
    child_snap = next(a for a in snap["agents"] if a["id"] == child.id)
    assert child_snap["parents"] == ["agent_ada", "agent_bram"]
    assert child_snap["relationships"]["agent_ada"]["since_tick"] == 12
    ada_snap = next(a for a in snap["agents"] if a["id"] == "agent_ada")
    assert ada_snap["relationships"]["agent_bram"]["since_tick"] == 7
    assert "reputation" in ada_snap                    # derived, recomputed

    # ── Behavior resumes ────────────────────────────────────────────────────
    # Rain still buffs forage (+rain_forage_bonus 2 on the base 1).
    ada = restored.agents["agent_ada"]
    ok, _, reward = restored.action_forage(ada)
    assert ok and reward == 3
    # The partner predicate and the faction survive; recompute = ZERO churn.
    assert restored.are_partners("agent_ada", "agent_bram")
    assert restored.recompute_factions() == []
    assert set(restored.factions) == {fid}
    assert restored.faction_of(child.id)["id"] == fid
    # NO re-birth inside the derived cooldown window (birth tick 12 + 600):
    # every other gate is deliberately ripe, so the cooldown is provably the
    # active gate — and it re-opens at exactly tick 612.
    restored.tick = 611
    assert restored.check_births(CARDS) == []
    # Rain expires on schedule, exactly once, and the buff is gone.
    expired = restored.expire_miracles()
    assert [e["kind"] for e in expired] == ["miracle_expired"]
    assert restored.expire_miracles() == []
    ok, _, reward = restored.action_forage(ada)
    assert ok and reward == 1
    restored.tick = 612
    reborn = restored.check_births(CARDS)
    assert [e["kind"] for e in reborn] == ["child_spawned", "agent_spawned"]
    assert reborn[0]["payload"]["name"] == "Vesper"    # next unused card

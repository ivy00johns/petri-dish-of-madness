"""
Wave E / B4 — EM-125 reflection-driven bonds (contracts/wave-e.md §B4),
plus the two ratified carry-overs B4 owns:
  · B3 item 6 — the faction prompt line ("Your circle: {name} ({k} members)"),
    wired in runtime via World.faction_of() with the getattr pattern.
  · B1 QE finding — the pending_relationship_events outbox drain in
    runtime._apply_action is exception-safe (a handler exception can never
    leak a parked event onto the NEXT agent's turn chain).

Covers the full B4 acceptance list:
  · MockProvider turn with reflection+valid bond → relationship type set, one
    relationship_changed event in the SAME turn chain (shared turn_id),
    reflection payload carries bond_applied {target_id, type}
  · bond target resolves via the EM-140 name→id machinery (display name and
    exact id both work)
  · partner bond below trust threshold rejected (trace bond_rejected reason),
    turn succeeds; at threshold accepted
  · family bond rejected (B1 engine-only rule); unknown target dropped;
    malformed bond objects ignored — never failing the turn
  · throttle: at most ONE bond per reflection (single object by schema; a
    bond on a non-reflection turn is dropped)
  · no bond instruction when reflection is not requested (the non-reflection
    prompt is unchanged; the protagonist fixture guard in
    test_wave_d2_prompt_diet stays green — fixture world has no factions and
    never requests a reflection)
  · ZERO llm_call delta: a reflection+bond turn emits exactly the same
    llm_call rows as a plain reflection turn

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from petridish.engine.world import (
    AgentState,
    PlaceState,
    RelationshipState,
    World,
)
from petridish.config.loader import (
    ModelProfile,
    ReflectionParams,
    WorldConfig,
    WorldParams,
)
from petridish.agents.runtime import (
    ACTION_SCHEMA,
    AgentRuntime,
    _assemble_context,
    _sanitize_bond,
    _validate_schema,
)
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


IDLE = {"action": "idle", "args": {}}


# ──────────────────────────────────────────────────────────────────────────────
# Harness (test_w11b idiom: per-agent scripts + prompt capture)
# ──────────────────────────────────────────────────────────────────────────────

class ScriptedProvider:
    """Per-agent scripted provider with prompt capture (the ByAgentProvider
    idiom from test_w11b). Script keys are substrings of agent ids; entries
    are consumed sequentially, last entry repeats. Every chat() records
    (agent_id, system_prompt) so tests can assert the EM-125 prompt seam."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list]):
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []

    def set_world(self, world: object) -> None:  # router.inject_world seam
        self._world = world

    async def chat(self, messages, *, max_tokens, temperature):
        agent_id, system = "unknown", ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                for line in system.split("\n"):
                    if line.strip().startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
        self.prompts.append((agent_id, system))
        script = None
        for key, entries in self._scripts.items():
            if key in agent_id:
                script = entries
                break
        if script is None:
            script = [dict(IDLE)]
        i = min(self._pos.get(agent_id, 0), len(script) - 1)
        self._pos[agent_id] = i + 1
        entry = script[i]
        if callable(entry):
            entry = entry(agent_id)
        return json.dumps(entry)


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]


def _agent(aid: str, name: str, location: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=80.0, credits=20)


def _make(agents: list[AgentState], scripts: dict[str, list],
          params: WorldParams | None = None):
    """World + runtime + repo + loop on a ScriptedProvider (offline)."""
    params = params or _params()
    world = World(params=params, places=_places(), agents=agents)
    provider = ScriptedProvider(scripts)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": provider},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo, runtime, provider


def _ada_bram() -> list[AgentState]:
    return [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")]


def _rel(world: World, a_id: str, b_id: str, **kw) -> RelationshipState:
    rel = RelationshipState(**kw)
    world.agents[a_id].relationships[b_id] = rel
    return rel


def _trip_reflection(runtime: AgentRuntime, agent_id: str) -> None:
    """Force the EM-080 accumulator over any threshold for this agent."""
    runtime._importance[agent_id] = 99.0


async def _drive(loop: TickLoop, world: World, n: int) -> None:
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)
        if loop._animal_task is not None:
            await loop._animal_task
        if getattr(loop, "_narrator_task", None) is not None:
            await loop._narrator_task


def _reflection_turn(reflection: str = "I see Bram differently now.",
                     bond: object = None) -> dict:
    entry: dict = {"action": "idle", "args": {}, "reflection": reflection}
    if bond is not None:
        entry["bond"] = bond
    return entry


# ══════════════════════════════════════════════════════════════════════════════
# 1. Happy path — valid bond on a reflection turn (full loop path)
# ══════════════════════════════════════════════════════════════════════════════

def test_valid_bond_sets_relationship_and_rides_the_same_turn_chain():
    """B4 acceptance 1: reflection+bond → type set, ONE relationship_changed
    sharing the reflection's turn_id, reflection payload carries bond_applied."""
    loop, world, repo, runtime, provider = _make(
        _ada_bram(),
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "mentor"})],
         "bram": [dict(IDLE)]},
        _params(reflection=ReflectionParams(importance_threshold=3.0)),
    )
    _trip_reflection(runtime, "agent_ada")
    asyncio.run(_drive(loop, world, 1))  # ada's turn (lowest id goes first)

    # The bond instruction rode the SAME single prompt as the reflection ask.
    assert 'ALSO include "reflection"' in provider.prompts[0][1]
    assert '"bond"' in provider.prompts[0][1]

    rel = world.agents["agent_ada"].relationships["agent_bram"]
    assert rel.type == "mentor"

    refl_rows = repo.get_events(loop._run_id, kinds=["reflection"])
    rel_rows = repo.get_events(loop._run_id, kinds=["relationship_changed"])
    assert len(refl_rows) == 1 and len(rel_rows) == 1
    assert rel_rows[0]["payload"]["since_tick"] == rel.since_tick
    assert rel_rows[0]["turn_id"] == refl_rows[0]["turn_id"], \
        "the bond's relationship_changed rides the SAME turn chain"
    assert rel_rows[0]["actor_id"] == "agent_ada"
    assert rel_rows[0]["target_id"] == "agent_bram"
    assert rel_rows[0]["payload"]["to_type"] == "mentor"
    assert refl_rows[0]["payload"]["bond_applied"] == {
        "target_id": "agent_bram", "type": "mentor",
    }


def test_bond_target_accepts_exact_agent_id():
    loop, world, repo, runtime, _ = _make(
        _ada_bram(),
        {"ada": [_reflection_turn(bond={"target": "agent_bram",
                                        "type": "friend"})],
         "bram": [dict(IDLE)]},
    )
    _trip_reflection(runtime, "agent_ada")
    asyncio.run(_drive(loop, world, 1))
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "friend"


def test_bond_target_resolves_display_name_preferring_co_located_living():
    """The EM-140 name→id machinery is REUSED: two 'Bram's resolve to the
    living, co-located one."""
    agents = [
        _agent("agent_ada", "Ada", location="plaza"),
        _agent("agent_bram_far", "Bram", location="market"),
        _agent("agent_bram_near", "Bram", location="plaza"),
    ]
    loop, world, repo, runtime, _ = _make(
        agents,
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "friend"})],
         "bram": [dict(IDLE)]},
    )
    _trip_reflection(runtime, "agent_ada")
    asyncio.run(_drive(loop, world, 1))
    ada = world.agents["agent_ada"]
    assert ada.relationships.get("agent_bram_near") is not None
    assert ada.relationships["agent_bram_near"].type == "friend"
    assert "agent_bram_far" not in ada.relationships


# ══════════════════════════════════════════════════════════════════════════════
# 2. Guards — B1 rules apply; rejection never fails the turn
# ══════════════════════════════════════════════════════════════════════════════

def _run_one_turn(scripts: dict[str, list], *, trip: bool = True,
                  pre_rel: dict | None = None):
    loop, world, repo, runtime, provider = _make(_ada_bram(), scripts)
    if pre_rel:
        _rel(world, "agent_ada", "agent_bram", **pre_rel)
    if trip:
        _trip_reflection(runtime, "agent_ada")
    agent = world.next_agent()
    assert agent.id == "agent_ada"
    result = asyncio.run(runtime.run_turn(agent))
    return world, result


def _events_of(result: dict) -> list[dict]:
    return result["_multi"] if "_multi" in result else [result]


def test_partner_bond_below_trust_threshold_rejected_turn_succeeds():
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "partner"})]},
        pre_rel=dict(type="friend", trust=10, interactions=6),
    )
    assert "barely know" in result["_trace"]["bond_rejected"]
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "friend"
    events = _events_of(result)
    kinds = [e["kind"] for e in events]
    assert "parse_failure" not in kinds, "a rejected bond never fails the turn"
    assert "relationship_changed" not in kinds
    refl = next(e for e in events if e["kind"] == "reflection")
    assert "bond_applied" not in refl["payload"]


def test_partner_bond_at_threshold_accepted():
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "partner"})]},
        pre_rel=dict(type="friend", trust=40, interactions=6),
    )
    assert "bond_rejected" not in result["_trace"]
    assert world.agents["agent_ada"].relationships["agent_bram"].type == "partner"
    refl = next(e for e in _events_of(result) if e["kind"] == "reflection")
    assert refl["payload"]["bond_applied"] == {
        "target_id": "agent_bram", "type": "partner",
    }


def test_family_bond_rejected_with_trace_reason_turn_succeeds():
    """family is engine-only (B1). The disallowed type is stripped BEFORE
    schema validation, so additionalProperties/enum can never fail the turn."""
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "family"})]},
    )
    assert "family" in result["_trace"]["bond_rejected"]
    assert "agent_bram" not in world.agents["agent_ada"].relationships
    assert all(e["kind"] != "parse_failure" for e in _events_of(result))


def test_unknown_target_bond_silently_dropped():
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "Zorblax", "type": "friend"})]},
    )
    assert "unknown target" in result["_trace"]["bond_rejected"]
    assert world.agents["agent_ada"].relationships == {}
    assert all(e["kind"] != "parse_failure" for e in _events_of(result))


def test_self_bond_rejected():
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "agent_ada",
                                        "type": "friend"})]},
    )
    assert "yourself" in result["_trace"]["bond_rejected"]
    assert world.agents["agent_ada"].relationships == {}


def test_dead_target_bond_rejected():
    loop, world, repo, runtime, _ = _make(
        _ada_bram(),
        {"ada": [_reflection_turn(bond={"target": "agent_bram",
                                        "type": "friend"})]},
    )
    world.agents["agent_bram"].alive = False
    _trip_reflection(runtime, "agent_ada")
    result = asyncio.run(runtime.run_turn(world.agents["agent_ada"]))
    assert "no longer among the living" in result["_trace"]["bond_rejected"]
    assert "agent_bram" not in world.agents["agent_ada"].relationships


@pytest.mark.parametrize("bad_bond", [
    "Bram",                                   # not an object
    ["Bram", "friend"],                       # list (also: >1 bond impossible)
    {"target": "Bram"},                       # missing type
    {"type": "friend"},                       # missing target
    {"target": "", "type": "friend"},         # empty target
    {"target": "Bram", "type": "sworn_enemy"},  # unknown type
    {"target": "Bram", "type": 7},            # non-string type
])
def test_malformed_bond_objects_are_ignored_turn_succeeds(bad_bond):
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond=bad_bond)]},
    )
    assert all(e["kind"] != "parse_failure" for e in _events_of(result)), \
        f"malformed bond {bad_bond!r} must never fail the turn"
    assert world.agents["agent_ada"].relationships == {}
    # The reflection itself still lands.
    assert any(e["kind"] == "reflection" for e in _events_of(result))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Throttle + prompt gating — bonds exist ONLY on reflection turns
# ══════════════════════════════════════════════════════════════════════════════

def test_bond_without_reflection_request_is_dropped():
    """A model volunteering a bond on a non-reflection turn is ignored (the
    throttle: bonds ride the importance-gated reflection request only)."""
    world, result = _run_one_turn(
        {"ada": [_reflection_turn(bond={"target": "Bram", "type": "friend"})]},
        trip=False,
    )
    assert result["_trace"]["bond_rejected"] == \
        "no reflection was requested this turn"
    assert world.agents["agent_ada"].relationships == {}


def test_no_bond_instruction_when_reflection_not_requested():
    """The non-reflection prompt carries NO bond instruction (pre-E
    byte-identical path; the protagonist fixture guard in
    test_wave_d2_prompt_diet proves the exact bytes)."""
    loop, world, repo, runtime, provider = _make(
        _ada_bram(), {"ada": [dict(IDLE)], "bram": [dict(IDLE)]})
    asyncio.run(_drive(loop, world, 2))
    for _aid, prompt in provider.prompts:
        assert '"bond"' not in prompt
        assert 'ALSO include "reflection"' not in prompt


def test_schema_bond_is_additive_and_excludes_family():
    """ACTION_SCHEMA: optional bond object {target ≤60, type enum of the 4
    declarable bond types} — additive (absent stays valid)."""
    bond_schema = ACTION_SCHEMA["properties"]["bond"]
    assert bond_schema["properties"]["target"]["maxLength"] == 60
    assert bond_schema["properties"]["type"]["enum"] == [
        "friend", "partner", "mentor", "feud"]
    assert "family" not in bond_schema["properties"]["type"]["enum"]
    # EM-199 — top-level `required` became `anyOf` (a turn needs `action` OR
    # `actions`); bond stays additive (in neither required branch).
    assert all("bond" not in b.get("required", []) for b in ACTION_SCHEMA["anyOf"])
    assert _validate_schema({"action": "idle", "args": {}}) is None
    assert _validate_schema({
        "action": "idle", "args": {},
        "bond": {"target": "Bram", "type": "feud"},
    }) is None


def test_sanitize_bond_normalizes_and_truncates():
    d = {"action": "idle", "args": {},
         "bond": {"target": "  " + "B" * 80, "type": " FRIEND ",
                  "extra": "dropped"}}
    assert _sanitize_bond(d) is None
    assert d["bond"] == {"target": "B" * 60, "type": "friend"}


# ══════════════════════════════════════════════════════════════════════════════
# 4. Free-scale proof — ZERO llm_call delta
# ══════════════════════════════════════════════════════════════════════════════

def test_bond_turn_emits_exactly_the_same_llm_call_rows_as_plain_reflection():
    """B4 acceptance: a reflection turn WITH a bond emits exactly the same
    llm_call rows as a reflection turn today (the bond rides the same single
    call — zero new LLM calls)."""
    def llm_calls_for(script_entry: dict) -> list[dict]:
        loop, world, repo, runtime, _ = _make(
            _ada_bram(), {"ada": [script_entry], "bram": [dict(IDLE)]})
        _trip_reflection(runtime, "agent_ada")
        asyncio.run(_drive(loop, world, 1))
        return repo.get_events(loop._run_id, kinds=["llm_call"])

    plain = llm_calls_for(_reflection_turn())
    bonded = llm_calls_for(
        _reflection_turn(bond={"target": "Bram", "type": "friend"}))
    assert len(plain) == len(bonded) == 1, \
        "one attempt ⇒ exactly one llm_call row, bond or no bond"
    assert [r["payload"].get("attempt") for r in plain] == \
        [r["payload"].get("attempt") for r in bonded]


# ══════════════════════════════════════════════════════════════════════════════
# 5. World.apply_bond helper (set_relationship semantics + outbox event)
# ══════════════════════════════════════════════════════════════════════════════

def test_apply_bond_sets_type_and_parks_relationship_changed():
    world = World(params=_params(), places=_places(), agents=_ada_bram())
    world.tick = 7
    ada = world.agents["agent_ada"]
    ok, msg = world.apply_bond(ada, "agent_bram", "feud", world.tick)
    assert ok and msg == "ok"
    rel = ada.relationships["agent_bram"]
    assert rel.type == "feud" and rel.since_tick == 7
    parked = world.drain_relationship_events()
    assert len(parked) == 1
    assert parked[0]["kind"] == "relationship_changed"
    assert parked[0]["payload"]["to_type"] == "feud"
    # Same-type re-bond: accepted, but no second event (set_relationship rule).
    ok, _ = world.apply_bond(ada, "agent_bram", "feud", world.tick)
    assert ok
    assert world.drain_relationship_events() == []


def test_apply_bond_enforces_b1_guards():
    world = World(params=_params(), places=_places(), agents=_ada_bram())
    ada = world.agents["agent_ada"]
    ok, msg = world.apply_bond(ada, "agent_bram", "family", 0)
    assert not ok and "birth" in msg
    ok, msg = world.apply_bond(ada, "agent_bram", "partner", 0)
    assert not ok and "barely know" in msg
    ok, msg = world.apply_bond(ada, "agent_ghost", "friend", 0)
    assert not ok and "unknown target" in msg
    world.agents["agent_bram"].alive = False
    ok, msg = world.apply_bond(ada, "agent_bram", "friend", 0)
    assert not ok and "living" in msg
    assert world.drain_relationship_events() == []


# ══════════════════════════════════════════════════════════════════════════════
# 6. Carry-over (B3.6) — the faction prompt line
# ══════════════════════════════════════════════════════════════════════════════

def test_faction_prompt_line_present_for_members_absent_otherwise():
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cyn", "Cyn")]
    world = World(params=_params(), places=_places(), agents=agents)

    def prompt_for(aid: str) -> str:
        msgs = _assemble_context(world.agents[aid], world, [], world.params)
        return msgs[0]["content"]

    # No factions (the fixture-world case): no line, anywhere.
    assert "Your circle:" not in prompt_for("agent_ada")

    world.factions["fct_deadbeef"] = {
        "name": "Ada's circle", "founded_tick": 3,
        "members": ["agent_ada", "agent_bram", "agent_cyn"],
    }
    p = prompt_for("agent_ada")
    assert "Your circle: Ada's circle (3 members)" in p
    assert p.count("Your circle:") == 1, "exactly ONE line"
    # A non-member's prompt stays clean.
    world.factions["fct_deadbeef"]["members"] = ["agent_bram", "agent_cyn"]
    assert "Your circle:" not in prompt_for("agent_ada")


def test_faction_line_rides_the_live_turn_prompt():
    """Through the REAL loop path: the B3 round-boundary recompute forms the
    faction from mutual warm edges, and B4's prompt line surfaces it for
    members only."""
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cyn", "Cyn"), _agent("agent_dee", "Dee")]
    loop, world, repo, runtime, provider = _make(
        agents, {a.id.split("_")[1]: [dict(IDLE)] for a in agents})
    # Mutual warm triangle bram↔cyn↔dee (ally, trust ≥ faction_trust 25) so
    # the round-boundary recompute forms "Bram's circle"; ada stays out.
    for a, b in (("agent_bram", "agent_cyn"), ("agent_bram", "agent_dee"),
                 ("agent_cyn", "agent_dee")):
        _rel(world, a, b, type="ally", trust=30, interactions=1)
        _rel(world, b, a, type="ally", trust=30, interactions=1)
    asyncio.run(_drive(loop, world, 4))
    by_agent = dict(provider.prompts)
    assert "Your circle: Bram's circle (3 members)" in by_agent["agent_bram"]
    assert "Your circle: Bram's circle (3 members)" in by_agent["agent_cyn"]
    assert "Your circle:" not in by_agent["agent_ada"]


# ══════════════════════════════════════════════════════════════════════════════
# 7. Carry-over (B1 QE) — exception-safe outbox drain
# ══════════════════════════════════════════════════════════════════════════════

def test_relationship_outbox_never_leaks_across_a_handler_exception():
    """Regression for the ratified B1 QE finding: an event parked during a
    handler that then RAISES must be drained (dropped), never left to ride
    the NEXT agent's turn chain."""
    loop, world, repo, runtime, _ = _make(
        _ada_bram(), {"ada": [dict(IDLE)], "bram": [dict(IDLE)]})

    parked_evt = {"kind": "relationship_changed", "actor_id": "agent_ada",
                  "target_id": "agent_bram", "text": "x", "payload": {}}

    def exploding_handler(agent, action_dict, profile_name, profile_color):
        world.pending_relationship_events.append(dict(parked_evt))
        raise RuntimeError("handler blew up after parking an event")

    original = runtime._apply_action_inner
    runtime._apply_action_inner = exploding_handler
    try:
        with pytest.raises(RuntimeError):
            runtime._apply_action(
                world.agents["agent_ada"], dict(IDLE), "mock", "#2ecc71")
    finally:
        runtime._apply_action_inner = original

    assert world.pending_relationship_events == [], \
        "the parked event must be drained on the exception path"

    # The NEXT agent's turn chain carries no stowaway relationship_changed.
    asyncio.run(_drive(loop, world, 2))
    assert repo.get_events(loop._run_id, kinds=["relationship_changed"]) == []


def test_outbox_drain_success_path_unchanged():
    """The try/finally refactor keeps the happy path byte-identical: an
    accepted set_relationship still rides its own turn chain."""
    loop, world, repo, runtime, _ = _make(
        _ada_bram(),
        {"ada": [{"action": "set_relationship",
                  "args": {"target": "Bram", "type": "ally"}}],
         "bram": [dict(IDLE)]})
    asyncio.run(_drive(loop, world, 1))
    rows = repo.get_events(loop._run_id, kinds=["relationship_changed"])
    assert len(rows) == 1
    assert rows[0]["payload"]["to_type"] == "ally"
    action_rows = repo.get_events(loop._run_id, kinds=["relationship"])
    assert action_rows and rows[0]["turn_id"] == action_rows[0]["turn_id"]

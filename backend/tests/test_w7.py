"""
W7 gate tests — buildings / collective-project pipeline, function gating, credit
conservation, failure modes, tool gating, ad-hoc spawn, decision caching, and the
GET /api/buildings surface.

Contracts under test:
  - contracts/world-model.md §W7        — Building entity + state machine + invariant 6.
  - contracts/action-protocol.schema.json — the 6 new construction actions + args.
  - contracts/providers.md (Decision caching) — EM-068 router LRU cache.
  - contracts/api.openapi.yaml (v1.1.0) — POST /api/agents spawn modes; GET /api/buildings.

Everything here is deterministic and offline (MockProvider, in-memory repo). The
suite follows the patterns established in tests/test_w6.py / test_invariants.py:
  - world-core lifecycle/economy is exercised through the World.action_* API
    (the single source of truth for invariant 6 and the state machine);
  - the runtime end-to-end path is driven through AgentRuntime.run_turn with a
    scripted MockProvider (the SAME parse/validate/apply path the loop uses);
  - tool gating is asserted through runtime._validate_world (what the engine
    enforces at resolution time);
  - the API surface (spawn modes + GET /api/buildings) is exercised through a
    FastAPI TestClient.

QE NOTE — integration defects surfaced by these tests (see the *_runtime_*
cases): the runtime's AgentRuntime._apply_action dispatches the W7 building
actions assuming world.action_propose_project/contribute_funds/build_step/...
return `(ok, reason, ...)` tuples and take a building OBJECT, but world-core's
implementations return event dicts ({"_multi": [...]}) and take a building_id
STRING. The two W7 implementers shipped incompatible signatures. Every building
action therefore raises ValueError before resolving, crashing the turn. The
xfail-marked runtime cases pin this defect so the gate stays red until the wiring
is reconciled; the world-core + cache + spawn + API tests verify the parts that
ARE correct.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest
from fastapi.testclient import TestClient

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import (
    WorldParams,
    BuildingParams,
    SpawnParams,
    CacheParams,
    ModelProfile,
    WorldConfig,
)
from petridish.agents.runtime import AgentRuntime, _validate_world
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _params(**overrides) -> WorldParams:
    """A deterministic, decay-free WorldParams with a knowable buildings block."""
    p = WorldParams(
        energy_decay_per_turn=0.0,
        starting_energy=100.0,
        starting_credits=50,
        work_reward=4,
        forage_reward=1,
        death_after_zero_turns=99,
    )
    # Deterministic buildings config: 20% per build_step (5 steps -> 100), a short
    # abandon window, predictable arson damage, and clear economy buffs.
    p.buildings = BuildingParams(
        enabled=True,
        build_step=20,
        abandon_after_ticks=5,
        arson_damage=60,
        forage_bonus=3,
        work_bonus_pct=50,
    )
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def _world(*, places=None, agents=None, params=None) -> tuple[World, list[AgentState]]:
    params = params or _params()
    if places is None:
        places = [
            PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
            PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
            PlaceState(id="townhall", name="Town Hall", x=20, y=0, kind="governance"),
        ]
    if agents is None:
        agents = [
            AgentState(
                id="a0", name="Ada", personality="builder", profile="mock",
                location="plaza", energy=params.starting_energy, credits=params.starting_credits,
            ),
            AgentState(
                id="a1", name="Bram", personality="arsonist", profile="mock",
                location="plaza", energy=params.starting_energy, credits=params.starting_credits,
            ),
        ]
    world = World(params=params, places=places, agents=agents)
    return world, agents


def _propose(world: World, agent: AgentState, name: str, kind: str,
             funds_required: int, function: str | None = None) -> str:
    """Propose a building via world-core; return its building_id."""
    res = world.action_propose_project(agent, name, kind, funds_required, function)
    return res["_building_id"]


def _kinds(res: dict) -> list[str]:
    """The event kinds emitted by a world-core action result ({"_multi":[...]} or one event)."""
    if "_multi" in res:
        return [e["kind"] for e in res["_multi"]]
    return [res["kind"]]


def _drive_runtime_turn(world: World, agent: AgentState, script: list) -> dict:
    """Run ONE agent turn through the real AgentRuntime.run_turn path with a
    scripted MockProvider. Returns the (possibly multi) result event dict."""
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    router.reassign(agent.id, "mock")
    runtime = AgentRuntime(world, router)
    return asyncio.run(runtime.run_turn(agent))


def _loop_with_script(world: World, agent: AgentState, script: list) -> tuple[TickLoop, list[dict]]:
    """Build a real TickLoop over `world` with a scripted MockProvider for `agent`,
    capturing every broadcast/emitted event. Turns are driven through the SAME
    TickLoop._execute_turn path the live loop uses (this is the W7 integration
    boundary the runtime/world-core wiring must satisfy end-to-end)."""
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    router.reassign(agent.id, "mock")
    router.inject_world(world)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    emitted: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda msg: emitted.append(msg))
    loop.init_run(WorldConfig(world=world.params, places=[], agents=[]))
    return loop, emitted


def _emitted_kinds(loop_events: list[dict]) -> list[str]:
    """Collect the `kind` of every domain event the loop broadcast (TickLoop
    stamps each event as {type:"event", kind, ...}; world_state snapshots have no
    kind and are skipped)."""
    return [
        msg["kind"]
        for msg in loop_events
        if isinstance(msg, dict) and msg.get("type") == "event" and "kind" in msg
    ]


def _emitted_events(loop_events: list[dict]) -> list[dict]:
    """The full stamped event dicts the loop broadcast (excludes world_state)."""
    return [
        msg for msg in loop_events
        if isinstance(msg, dict) and msg.get("type") == "event" and "kind" in msg
    ]


# ══════════════════════════════════════════════════════════════════════════════
# 1. BUILDING LIFECYCLE — propose -> contribute -> build_step xN -> operational.
#    Assert status transitions + the event ordering, and operational at progress==100.
# ══════════════════════════════════════════════════════════════════════════════

def test_lifecycle_propose_emits_proposed_then_state_changed_planned():
    world, agents = _world()
    res = world.action_propose_project(agents[0], "Clock Tower", "clocktower", 10)
    assert _kinds(res) == ["project_proposed", "structure_state_changed"]
    state_evt = res["_multi"][1]
    assert state_evt["payload"]["from"] == "none"
    assert state_evt["payload"]["to"] == "planned"
    bld = world.buildings[res["_building_id"]]
    assert bld.status == "planned"
    assert bld.owner_id == "public"
    assert bld.progress == 0
    assert bld.funds_required == 10


def test_lifecycle_full_funding_flips_to_under_construction():
    world, agents = _world()
    bid = _propose(world, agents[0], "Clock Tower", "clocktower", 10)
    res = world.action_contribute_funds(agents[0], bid, 10)
    # economy + project_funded + (the flip) structure_state_changed, in order.
    assert _kinds(res) == ["economy", "project_funded", "structure_state_changed"]
    flip = res["_multi"][2]
    assert flip["payload"]["from"] == "planned"
    assert flip["payload"]["to"] == "under_construction"
    assert world.buildings[bid].status == "under_construction"


def test_lifecycle_build_steps_reach_operational_at_progress_100():
    world, agents = _world()
    bid = _propose(world, agents[0], "Clock Tower", "clocktower", 10, function="voting")
    world.action_contribute_funds(agents[0], bid, 10)
    bld = world.buildings[bid]

    # 4 steps of 20 keep it under_construction (progress 20,40,60,80).
    progresses = []
    for _ in range(4):
        res = world.action_build_step(agents[0], bid)
        assert _kinds(res) == ["project_built"]
        progresses.append(bld.progress)
        assert bld.status == "under_construction"
    assert progresses == [20, 40, 60, 80]

    # The 5th step crosses 100 -> operational, emitting project_built then
    # structure_state_changed(under_construction->operational) then building_operational.
    res = world.action_build_step(agents[0], bid)
    assert _kinds(res) == ["project_built", "structure_state_changed", "building_operational"]
    assert bld.progress == 100
    assert bld.status == "operational"
    # building_operational only fires at progress==100 (invariant 6).
    op_evt = res["_multi"][2]
    assert op_evt["payload"]["building_id"] == bid
    assert op_evt["payload"]["function"] == "voting"
    # structure_state_changed records the right transition.
    sc_evt = res["_multi"][1]
    assert (sc_evt["payload"]["from"], sc_evt["payload"]["to"]) == (
        "under_construction", "operational"
    )


def test_lifecycle_building_operational_only_at_100_not_before():
    """A building never emits building_operational until progress hits exactly 100."""
    world, agents = _world()
    bid = _propose(world, agents[0], "Hall", "monument", 10)
    world.action_contribute_funds(agents[0], bid, 10)
    for _ in range(4):  # 80% built
        res = world.action_build_step(agents[0], bid)
        assert "building_operational" not in _kinds(res)
        assert world.buildings[bid].status != "operational"


# ══════════════════════════════════════════════════════════════════════════════
# 2. FUNCTION GATING (invariant 6) — function granted ONLY while operational.
# ══════════════════════════════════════════════════════════════════════════════

def _operationalize(world: World, agent: AgentState, name: str, kind: str) -> str:
    bid = _propose(world, agent, name, kind, 5)
    world.action_contribute_funds(agent, bid, 5)
    while world.buildings[bid].status != "operational":
        world.action_build_step(agent, bid)
    return bid


def test_function_gating_operational_garden_raises_forage():
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    # Non-operational garden -> NO buff.
    bid = _propose(world, a, "Garden", "garden", 5)
    before = a.credits
    world.action_forage(a)
    assert a.credits - before == world.params.forage_reward, "planned garden must grant no buff"

    # Operationalize the garden -> +forage_bonus.
    world.action_contribute_funds(a, bid, 5)
    while world.buildings[bid].status != "operational":
        world.action_build_step(a, bid)
    before = a.credits
    world.action_forage(a)
    expected = world.params.forage_reward + world.params.buildings.forage_bonus
    assert a.credits - before == expected, "operational garden must grant +forage_bonus"


def test_function_gating_operational_farm_raises_forage():
    world, agents = _world()
    a = agents[0]
    fid = _operationalize(world, a, "Farm", "farm")
    assert world.buildings[fid].status == "operational"
    before = a.credits
    world.action_forage(a)
    expected = world.params.forage_reward + world.params.buildings.forage_bonus
    assert a.credits - before == expected


def test_function_gating_operational_workshop_raises_work():
    # Workshop buffs work, which requires a work place.
    params = _params()
    places = [PlaceState(id="market", name="Market", x=0, y=0, kind="work")]
    agents = [AgentState(id="a0", name="Ada", personality="x", profile="mock",
                         location="market", energy=100.0, credits=50)]
    world, agents = _world(places=places, agents=agents, params=params)
    a = agents[0]

    # Non-operational workshop -> base work reward only.
    bid = _propose(world, a, "Shop", "workshop", 5)
    ok, _, reward = world.action_work(a)
    assert ok and reward == world.params.work_reward, "planned workshop must grant no buff"

    # Operationalize -> work reward +work_bonus_pct%.
    world.action_contribute_funds(a, bid, 5)
    while world.buildings[bid].status != "operational":
        world.action_build_step(a, bid)
    ok, _, reward = world.action_work(a)
    pct = world.params.buildings.work_bonus_pct
    assert reward == int(world.params.work_reward * (1 + pct / 100.0))


def test_function_gating_non_operational_grants_no_buff_across_states():
    """damaged / offline / abandoned / destroyed gardens grant NO forage buff."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    gid = _operationalize(world, a, "Garden", "garden")
    base = world.params.forage_reward
    bonus = base + world.params.buildings.forage_bonus

    # operational -> buffed
    before = a.credits
    world.action_forage(a)
    assert a.credits - before == bonus

    # take offline -> no buff
    world.action_take_offline(a, gid)
    assert world.buildings[gid].status == "offline"
    before = a.credits
    world.action_forage(a)
    assert a.credits - before == base, "offline garden must not buff"

    # repair back to operational -> buffed again
    world.action_repair(a, gid)
    assert world.buildings[gid].status == "operational"
    before = a.credits
    world.action_forage(a)
    assert a.credits - before == bonus

    # arson -> damaged/destroyed -> no buff
    world.action_arson(agents[1], gid)
    assert world.buildings[gid].status in ("damaged", "destroyed")
    before = a.credits
    world.action_forage(a)
    assert a.credits - before == base, "damaged/destroyed garden must not buff"


# ══════════════════════════════════════════════════════════════════════════════
# 3. CREDIT CONSERVATION (invariants 1 + 6) — contribute moves credits exactly,
#    no creation/loss; an agent can't contribute more than it has.
# ══════════════════════════════════════════════════════════════════════════════

def test_contribute_conserves_credits_exactly():
    world, agents = _world()
    a = agents[0]
    start = a.credits
    bid = _propose(world, a, "Clock", "clocktower", 30)
    bld = world.buildings[bid]
    assert bld.funds_committed == 0

    world.action_contribute_funds(a, bid, 7)
    assert a.credits == start - 7, "exactly 7 leaves the agent"
    assert bld.funds_committed == 7, "exactly 7 accrues to funds_committed"
    assert a.credits + bld.funds_committed == start, "no credit created or destroyed"
    assert a.id in bld.contributors

    world.action_contribute_funds(a, bid, 3)
    assert a.credits == start - 10
    assert bld.funds_committed == 10
    assert a.credits + bld.funds_committed == start
    # contributor recorded once, not duplicated.
    assert bld.contributors.count(a.id) == 1


def test_contribute_over_balance_is_rejected_and_mutates_nothing():
    world, agents = _world()
    a = agents[0]
    a.credits = 5
    bid = _propose(world, a, "Clock", "clocktower", 100)
    bld = world.buildings[bid]
    res = world.action_contribute_funds(a, bid, 6)  # more than the 5 it holds
    assert res["kind"] == "parse_failure"
    assert a.credits == 5, "rejected contribution must not debit the agent"
    assert bld.funds_committed == 0, "rejected contribution must not credit the building"
    assert a.id not in bld.contributors


def test_contribute_credits_never_go_negative():
    world, agents = _world()
    a = agents[0]
    a.credits = 0
    bid = _propose(world, a, "Clock", "clocktower", 10)
    world.action_contribute_funds(a, bid, 1)
    assert a.credits == 0  # rejected (can't afford), stays at floor
    assert a.credits >= 0


# ══════════════════════════════════════════════════════════════════════════════
# 4. FAILURE MODES — abandonment (the clock-tower failure), arson damage/destroy,
#    repair restore.
# ══════════════════════════════════════════════════════════════════════════════

def test_abandon_planned_building_after_idle_window():
    """A planned building with no fund/build activity for abandon_after_ticks
    becomes abandoned (the realistic clock-tower-that-never-got-built failure)."""
    world, agents = _world()
    bid = _propose(world, agents[0], "Clock", "clocktower", 50)
    bld = world.buildings[bid]
    window = world.params.buildings.abandon_after_ticks

    # Inside the window: not yet abandoned.
    world.tick = bld.last_progress_tick + window
    assert world.advance_buildings() == []
    assert bld.status == "planned"

    # Past the window: abandoned, emitting one structure_state_changed.
    world.tick = bld.last_progress_tick + window + 1
    evts = world.advance_buildings()
    assert [e["kind"] for e in evts] == ["structure_state_changed"]
    assert (evts[0]["payload"]["from"], evts[0]["payload"]["to"]) == ("planned", "abandoned")
    assert bld.status == "abandoned"


def test_abandon_under_construction_building_after_idle_window():
    """An under_construction building that stalls also rots to abandoned."""
    world, agents = _world()
    bid = _propose(world, agents[0], "Clock", "clocktower", 10)
    world.action_contribute_funds(agents[0], bid, 10)  # -> under_construction
    bld = world.buildings[bid]
    assert bld.status == "under_construction"
    world.action_build_step(agents[0], bid)  # one step, then stalls
    last = bld.last_progress_tick

    world.tick = last + world.params.buildings.abandon_after_ticks + 1
    evts = world.advance_buildings()
    assert [e["payload"]["to"] for e in evts] == ["abandoned"]
    assert bld.status == "abandoned"


def test_abandon_does_not_touch_operational_buildings():
    """Operational/offline structures are completed — never 'abandoned'."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    gid = _operationalize(world, a, "Garden", "garden")
    world.action_take_offline(a, gid)  # offline = a built structure, not a stalled project
    world.tick = world.buildings[gid].updated_tick + 999
    assert world.advance_buildings() == []
    assert world.buildings[gid].status == "offline"


def test_arson_drops_health_to_damaged_then_destroyed_repair_restores():
    world, agents = _world()
    a, bram = agents[0], agents[1]
    a.location = bram.location = "plaza"
    bid = _operationalize(world, a, "Hall", "monument")
    bld = world.buildings[bid]
    assert bld.status == "operational" and bld.health == 100

    # arson_damage=60: 100 -> 40 -> damaged.
    res = world.action_arson(bram, bid)
    assert _kinds(res) == ["conflict", "structure_state_changed"]
    assert bld.health == 40
    assert bld.status == "damaged"
    sc = res["_multi"][1]
    assert (sc["payload"]["from"], sc["payload"]["to"]) == ("operational", "damaged")
    # Crime: co-located witness loses trust in the arsonist.
    assert a.relationships[bram.id].trust < 0

    # repair restores health to 100 and status to operational.
    res = world.action_repair(a, bid)
    assert "structure_state_changed" in _kinds(res)
    assert bld.health == 100
    assert bld.status == "operational"

    # arson twice more: 100 -> 40 -> 0 -> destroyed.
    world.action_arson(bram, bid)
    assert bld.status == "damaged"
    res = world.action_arson(bram, bid)
    assert bld.health == 0
    assert bld.status == "destroyed"
    sc = res["_multi"][1]
    assert sc["payload"]["to"] == "destroyed"


def test_arson_on_destroyed_is_a_noop_failure():
    world, agents = _world()
    a, bram = agents[0], agents[1]
    bid = _operationalize(world, a, "Hall", "monument")
    # Knock it to destroyed (60 + 60 >= 100 over two hits).
    world.action_arson(bram, bid)
    world.action_arson(bram, bid)
    assert world.buildings[bid].status == "destroyed"
    health_before = world.buildings[bid].health
    res = world.action_arson(bram, bid)
    assert res["kind"] == "parse_failure"
    assert world.buildings[bid].health == health_before


# ══════════════════════════════════════════════════════════════════════════════
# 5. TOOL GATING — build_step only when under_construction AND at the building's
#    place; arson blocked by ban_arson; contribute affordability. Gated attempts
#    fail and DON'T mutate.
# ══════════════════════════════════════════════════════════════════════════════

def test_gate_build_step_requires_under_construction():
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    bid = _propose(world, a, "Clock", "clocktower", 10)  # planned, not under_construction
    err = _validate_world({"action": "build_step", "args": {"building_id": bid}}, a, world)
    # W9 / EM-073 B4: an UNFUNDED planned building is still rejected, but with a
    # funding-specific reason (a fully-funded planned building now validates OK —
    # world.action_build_step auto-advances it to under_construction).
    assert err is not None and "not fully funded" in err
    # Building untouched.
    assert world.buildings[bid].progress == 0
    assert world.buildings[bid].status == "planned"


def test_gate_build_step_requires_co_location():
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    bid = _propose(world, a, "Clock", "clocktower", 10)
    world.action_contribute_funds(a, bid, 10)  # under_construction, at plaza
    # Same place -> allowed.
    assert _validate_world({"action": "build_step", "args": {"building_id": bid}}, a, world) is None
    # Move away -> gated.
    a.location = "market"
    err = _validate_world({"action": "build_step", "args": {"building_id": bid}}, a, world)
    assert err is not None and "place" in err
    assert world.buildings[bid].progress == 0  # nothing built from afar


def test_gate_arson_blocked_by_ban_arson_rule():
    world, agents = _world()
    a, bram = agents[0], agents[1]
    bid = _operationalize(world, a, "Hall", "monument")
    world.rules["r_ban"] = RuleState(
        id="r_ban", effect="ban_arson", text="No fire.", proposer_id="a0", status="active"
    )
    assert world.has_active_rule("ban_arson")
    err = _validate_world({"action": "arson", "args": {"building_id": bid}}, bram, world)
    assert err is not None and "ban_arson" in err
    # Health untouched by the gated attempt.
    assert world.buildings[bid].health == 100
    assert world.buildings[bid].status == "operational"


def test_gate_contribute_affordability():
    world, agents = _world()
    a = agents[0]
    a.credits = 3
    bid = _propose(world, a, "Clock", "clocktower", 100)
    err = _validate_world(
        {"action": "contribute_funds", "args": {"building_id": bid, "amount": 4}}, a, world
    )
    assert err is not None and "insufficient" in err
    # Affordable amount passes.
    assert _validate_world(
        {"action": "contribute_funds", "args": {"building_id": bid, "amount": 3}}, a, world
    ) is None


def test_gate_take_offline_owner_only():
    """take_offline is owner-gated: a non-owner is rejected and nothing changes."""
    world, agents = _world()
    a, bram = agents[0], agents[1]
    bid = _operationalize(world, a, "Hall", "monument")
    # Owner is "public" (proposed projects are public), so neither agent owns it.
    err = _validate_world({"action": "take_offline", "args": {"building_id": bid}}, a, world)
    assert err is not None and "owner" in err
    assert world.buildings[bid].status == "operational"
    # Make Ada the owner; now it's allowed.
    world.buildings[bid].owner_id = a.id
    assert _validate_world(
        {"action": "take_offline", "args": {"building_id": bid}}, a, world
    ) is None


# ── Runtime end-to-end gating (the parse/validate path actually idles on a gate) ──

def test_runtime_idles_on_gated_build_step_without_mutating():
    """A scripted build_step on a planned building must be gated at validation
    (the runtime falls back to a parse_failure/idle turn) and leave it untouched.

    This exercises AgentRuntime._call_and_parse -> _validate_world, which is the
    real engine gate; it does NOT reach the broken _apply_action dispatch because
    validation rejects the action first."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    bid = _propose(world, a, "Clock", "clocktower", 10)  # planned
    res = _drive_runtime_turn(world, a, [{"action": "build_step", "args": {"building_id": bid}}])
    # Gated -> the turn resolves to a parse_failure (idle fallback), not a build.
    assert res["kind"] == "parse_failure"
    assert world.buildings[bid].progress == 0
    assert world.buildings[bid].status == "planned"


# ══════════════════════════════════════════════════════════════════════════════
# 6. SPAWN — god immediate (method god); governance enqueues admit_agent, agent
#    enters only when the vote passes (method governance).
# ══════════════════════════════════════════════════════════════════════════════

def test_world_governance_admit_agent_enters_only_after_vote_passes():
    """world-core: enqueue admit_agent -> agent absent -> vote passes threshold ->
    agent spawned with method=governance, drainable exactly once."""
    params = _params()
    places = [PlaceState(id="townhall", name="TH", x=0, y=0, kind="governance")]
    agents = [
        AgentState(id="a0", name="Ada", personality="x", profile="mock",
                   location="townhall", energy=100.0, credits=10),
        AgentState(id="a1", name="Bram", personality="y", profile="mock",
                   location="townhall", energy=100.0, credits=10),
    ]
    world, agents = _world(places=places, agents=agents, params=params)

    rule = world.enqueue_admit_agent("a0", "Newbie", "curious", "mock", "townhall")
    assert rule.effect == "admit_agent"
    assert rule.status == "proposed"
    assert not any(a.name == "Newbie" for a in world.agents.values()), "absent before vote"

    # 2 living agents -> threshold floor(2/2)=1 -> need >1, i.e. both YES.
    world.action_vote(agents[0], rule.id, True)
    assert rule.status == "proposed", "one vote is not a majority of two"
    assert not any(a.name == "Newbie" for a in world.agents.values())

    world.action_vote(agents[1], rule.id, True)
    assert rule.status == "active"
    assert any(a.name == "Newbie" for a in world.agents.values()), "admitted once the vote passes"

    drained = world.drain_spawn_events()
    assert len(drained) == 1
    evt = drained[0]
    assert evt["kind"] == "agent_spawned"
    assert evt["payload"]["method"] == "governance"
    assert evt["payload"]["proposal_id"] == rule.id
    # Idempotent: a second drain yields nothing (no double-spawn).
    assert world.drain_spawn_events() == []


def test_world_governance_admit_agent_rejected_vote_does_not_admit():
    params = _params()
    places = [PlaceState(id="townhall", name="TH", x=0, y=0, kind="governance")]
    agents = [
        AgentState(id="a0", name="Ada", personality="x", profile="mock",
                   location="townhall", energy=100.0, credits=10),
        AgentState(id="a1", name="Bram", personality="y", profile="mock",
                   location="townhall", energy=100.0, credits=10),
    ]
    world, agents = _world(places=places, agents=agents, params=params)
    rule = world.enqueue_admit_agent("a0", "Reject", "x", "mock", "townhall")
    world.action_vote(agents[0], rule.id, False)
    world.action_vote(agents[1], rule.id, False)
    assert rule.status == "rejected"
    assert not any(a.name == "Reject" for a in world.agents.values())
    assert world.drain_spawn_events() == []


@pytest.fixture()
def api_client():
    """A TestClient over the app's own lifespan-initialized (all-mock) world."""
    env_before = os.environ.copy()
    os.environ.pop("EM_CONFIG_DIR", None)
    from petridish.api.app import app
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    os.environ.clear()
    os.environ.update(env_before)


def _state_names(client: TestClient) -> set[str]:
    return {a["name"] for a in client.get("/api/state").json().get("agents", [])}


def test_api_god_spawn_is_immediate(api_client):
    """POST /api/agents (god) -> 201 and the agent appears in /api/state at once."""
    r = api_client.post("/api/agents", json={"name": "Zed", "profile": "mock", "mode": "god"})
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "god"
    assert "agent_id" in body
    assert "Zed" in _state_names(api_client), "god spawn must enter immediately"


def test_api_governance_spawn_is_deferred(api_client):
    """POST /api/agents (governance) -> 202 + proposal_id; the agent does NOT
    enter immediately (it would enter only once the admit_agent vote passes)."""
    r = api_client.post(
        "/api/agents", json={"name": "Quill", "profile": "mock", "mode": "governance"}
    )
    assert r.status_code == 202
    body = r.json()
    assert body["mode"] == "governance"
    assert body.get("proposal_id")
    assert "Quill" not in _state_names(api_client), "governance spawn must NOT enter immediately"


# ══════════════════════════════════════════════════════════════════════════════
# 7. CACHE (EM-068) — identical (profile, messages) -> adapter invoked ONCE, the
#    second is cached (cached=true, tokens null); different messages -> invoked
#    again; mock NEVER cached.
# ══════════════════════════════════════════════════════════════════════════════

class _CountingAdapter:
    """A minimal openai-shaped adapter that counts real calls and exposes the
    last_routed_via / last_usage snapshot the router caches."""
    name = "count"
    color = "#abcdef"

    def __init__(self) -> None:
        self.calls = 0
        self.last_routed_via = "real-model-x"
        self.last_usage = {
            "input_tokens": 11, "output_tokens": 7, "latency_ms": 9.0,
            "finish_reason": "stop", "cached": False,
        }

    async def chat(self, messages, *, max_tokens, temperature) -> str:
        self.calls += 1
        return '{"action": "idle", "args": {}}'


def _counting_router() -> tuple[Router, _CountingAdapter]:
    prof = ModelProfile(name="count", adapter="openai", model_id="m", color="#abcdef",
                        base_url="http://x", api_key_env="")
    ad = _CountingAdapter()
    return Router([prof], adapter_overrides={"count": ad}), ad


def test_cache_identical_messages_hit_invokes_adapter_once():
    router, ad = _counting_router()
    msgs = [{"role": "system", "content": "world snapshot ALPHA"}]

    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    assert ad.calls == 1
    u1 = router.last_usage("count")
    assert u1["cached"] is False
    assert u1["input_tokens"] == 11

    # Second identical call -> HIT, no extra adapter invocation.
    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    assert ad.calls == 1, "identical (profile, messages) must be cached"
    u2 = router.last_usage("count")
    assert u2["cached"] is True, "a cache HIT surfaces cached=true to llm_call"
    assert u2["input_tokens"] is None and u2["output_tokens"] is None, "cached tokens null"
    assert u2["latency_ms"] == 0.0
    # The cached routed model is still surfaced.
    assert router.last_routed_via("count") == "real-model-x"


def test_cache_forget_evicts_entry():
    """forget(profile, messages) drops the exact cached entry so a response
    that failed to parse/validate is never replayed (run 126: cached=true
    served the same truncated JSON back into a turn)."""
    router, ad = _counting_router()
    msgs = [{"role": "system", "content": "world snapshot ALPHA"}]

    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    assert ad.calls == 1

    router.forget("count", msgs)

    # Same request again → the adapter is re-invoked (entry gone), and other
    # keys are untouched.
    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    assert ad.calls == 2, "forgotten entry must not serve a cache HIT"

    # Forgetting an unknown key / uncacheable profile is a harmless no-op.
    router.forget("count", [{"role": "system", "content": "never cached"}])
    router.forget("no-such-profile", msgs)


def test_cache_different_messages_invokes_adapter_again():
    router, ad = _counting_router()
    asyncio.run(router.chat("count", [{"role": "system", "content": "ALPHA"}],
                            max_tokens=10, temperature=0.0))
    asyncio.run(router.chat("count", [{"role": "system", "content": "BETA"}],
                            max_tokens=10, temperature=0.0))
    assert ad.calls == 2, "a different situation (different messages) must miss the cache"
    assert router.last_usage("count")["cached"] is False


def test_cache_miss_then_hit_then_miss_sequence():
    router, ad = _counting_router()
    a = [{"role": "system", "content": "A"}]
    b = [{"role": "system", "content": "B"}]
    asyncio.run(router.chat("count", a, max_tokens=10, temperature=0.0))  # miss
    asyncio.run(router.chat("count", a, max_tokens=10, temperature=0.0))  # hit
    asyncio.run(router.chat("count", b, max_tokens=10, temperature=0.0))  # miss
    assert ad.calls == 2


def test_cache_mock_adapter_is_never_cached():
    """Mock is deterministic already -> the router must never cache it; its
    last_usage stays None (no fabricated cached snapshot)."""
    prof = ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")
    mock = MockProvider(script=[{"action": "idle", "args": {}}])
    # Count real invocations by wrapping chat.
    calls = {"n": 0}
    orig = mock.chat

    async def counting_chat(messages, *, max_tokens, temperature):
        calls["n"] += 1
        return await orig(messages, max_tokens=max_tokens, temperature=temperature)

    mock.chat = counting_chat  # type: ignore[assignment]
    router = Router([prof], adapter_overrides={"mock": mock})
    msgs = [{"role": "system", "content": "Agent ID: a0\nTick: 0"}]

    asyncio.run(router.chat("mock", msgs, max_tokens=10, temperature=0.0))
    asyncio.run(router.chat("mock", msgs, max_tokens=10, temperature=0.0))
    assert calls["n"] == 2, "mock is re-invoked every time (never cached)"
    assert router.last_usage("mock") is None, "mock contributes no usage / no cached snapshot"


def test_cache_disabled_does_not_cache():
    prof = ModelProfile(name="count", adapter="openai", model_id="m", color="#abcdef",
                        base_url="http://x", api_key_env="")
    ad = _CountingAdapter()
    router = Router([prof], adapter_overrides={"count": ad}, cache_enabled=False)
    msgs = [{"role": "system", "content": "SAME"}]
    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    asyncio.run(router.chat("count", msgs, max_tokens=10, temperature=0.0))
    assert ad.calls == 2, "cache_enabled=False must disable the decision cache"


# ══════════════════════════════════════════════════════════════════════════════
# 8. GET /api/buildings — returns the building dicts; empty-200 with no run.
# ══════════════════════════════════════════════════════════════════════════════

def test_api_buildings_empty_200_with_no_buildings(api_client):
    r = api_client.get("/api/buildings")
    assert r.status_code == 200
    assert r.json() == [], "no buildings -> empty 200 (never 500)"


def test_api_buildings_returns_building_dicts():
    """With buildings present in the world, GET /api/buildings returns their
    serialized dicts (the to_dict() shape from world-model.md §W7)."""
    import petridish.api.app  # noqa: F401 — ensure the submodule is imported
    # petridish/api/__init__.py does `from .app import app`, so the dotted name
    # `petridish.api.app` resolves to the FastAPI *instance*; reach the real
    # MODULE (which holds the _world/_loop singletons) via sys.modules.
    appmod = sys.modules["petridish.api.app"]
    saved = {k: getattr(appmod, k) for k in ("_world", "_loop")}
    try:
        world, agents = _world()
        bid = _propose(world, agents[0], "Clock", "clocktower", 10)
        world.action_contribute_funds(agents[0], bid, 10)
        appmod._world = world
        appmod._loop = None  # endpoint reads world.buildings directly
        client = TestClient(appmod.app, raise_server_exceptions=True)
        r = client.get("/api/buildings")
        assert r.status_code == 200
        out = r.json()
        assert isinstance(out, list) and len(out) == 1
        b = out[0]
        # The §W7 Building dict surface.
        for key in ("id", "name", "kind", "location", "owner_id", "status",
                    "health", "condition_label", "progress", "funds_committed",
                    "funds_required", "contributors", "function"):
            assert key in b, f"building dict missing '{key}'"
        assert b["id"] == bid
        assert b["kind"] == "clocktower"
        assert b["status"] == "under_construction"
        assert b["funds_committed"] == 10
    finally:
        for k, v in saved.items():
            setattr(appmod, k, v)


def test_api_buildings_no_world_returns_empty_200():
    """No initialized world -> empty 200."""
    import petridish.api.app  # noqa: F401
    appmod = sys.modules["petridish.api.app"]
    saved = {k: getattr(appmod, k) for k in ("_world", "_loop")}
    try:
        appmod._world = None
        appmod._loop = None
        client = TestClient(appmod.app, raise_server_exceptions=True)
        r = client.get("/api/buildings")
        assert r.status_code == 200
        assert r.json() == []
    finally:
        for k, v in saved.items():
            setattr(appmod, k, v)


# ══════════════════════════════════════════════════════════════════════════════
# INTEGRATION — the runtime building-action dispatch consumes world-core's
# event-dict return contract (NOT an (ok, reason, value) tuple) and passes the
# building_id STRING. These end-to-end cases drive the full collective-project
# pipeline through the REAL TickLoop._execute_turn path (the same code the live
# loop runs), so they fail closed if the runtime/world-core wiring regresses.
# (They were strict-xfail pins on the now-fixed signature mismatch.)
# ══════════════════════════════════════════════════════════════════════════════

def test_runtime_propose_project_end_to_end_through_loop():
    """propose_project, driven through TickLoop._execute_turn with a scripted
    MockProvider, creates the Building and emits the project_proposed +
    structure_state_changed{to:planned} domain events (no parse_failure/crash)."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    loop, emitted = _loop_with_script(
        world, a,
        [{"action": "propose_project",
          "args": {"name": "Clock", "kind": "clocktower", "funds_required": 10}}],
    )

    asyncio.run(loop._execute_turn(a))

    # The Building now exists, owner=public, planned at the agent's place.
    matches = [b for b in world.buildings.values() if b.kind == "clocktower"]
    assert len(matches) == 1, "propose_project must mint exactly one Building"
    bld = matches[0]
    assert bld.status == "planned"
    assert bld.owner_id == "public"
    assert bld.location == "plaza"

    kinds = _emitted_kinds(emitted)
    assert "project_proposed" in kinds, "the domain event must be emitted by the loop"
    assert "structure_state_changed" in kinds
    assert "parse_failure" not in kinds, "a correctly-wired propose must not fail/idle"
    # The decision-trace chain still brackets the domain event(s).
    assert "turn_start" in kinds and "action_chosen" in kinds
    assert kinds.index("turn_start") < kinds.index("project_proposed")
    assert kinds.index("project_proposed") < kinds.index("action_resolved")
    # action_resolved reports a successful (non-failed) outcome.
    resolved = [e for e in _emitted_events(emitted) if e["kind"] == "action_resolved"][-1]
    assert resolved["payload"]["outcome"] == "ok"
    # routed_via still flows onto the domain event's payload.
    proposed = [e for e in _emitted_events(emitted) if e["kind"] == "project_proposed"][0]
    assert "routed_via" in proposed["payload"]


def test_runtime_full_construction_chain_to_operational_through_loop():
    """The whole collective-project pipeline — propose -> contribute -> build_step
    xN -> operational — driven THROUGH TickLoop._execute_turn. Asserts the building
    reaches operational at progress==100 and the loop emits the project_funded,
    the planned->under_construction flip, project_built, and the building_operational
    domain events, with credits conserved (contribute moved exactly funds_required)."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"

    # Mint the Building via world-core so the script can reference its (uuid) id;
    # the funding + every build_step then runs through the real loop path.
    bid = _propose(world, a, "Clock", "clocktower", 10, function="voting")
    assert world.buildings[bid].status == "planned"
    start_credits = a.credits

    # build_step=20 -> 5 steps cross 100. Script: fund fully, then 5 build_steps.
    script = [{"action": "contribute_funds", "args": {"building_id": bid, "amount": 10}}]
    script += [{"action": "build_step", "args": {"building_id": bid}} for _ in range(5)]
    loop, emitted = _loop_with_script(world, a, script)

    for _ in range(len(script)):
        asyncio.run(loop._execute_turn(a))

    bld = world.buildings[bid]
    assert bld.progress == 100, "5 build_steps of 20 must reach progress==100"
    assert bld.status == "operational", "progress==100 must flip the building operational"
    assert a.credits == start_credits - 10, "contribute moved exactly funds_required (conserved)"
    assert bld.funds_committed == 10

    kinds = _emitted_kinds(emitted)
    assert "parse_failure" not in kinds, "no turn in the chain may fail/idle"
    assert "project_funded" in kinds
    assert "project_built" in kinds
    assert "building_operational" in kinds, "the loop must emit building_operational at 100%"
    # The funding fully-funded the project -> a planned->under_construction flip,
    # and the final build_step drove under_construction->operational. Both surface
    # as structure_state_changed events through the loop.
    transitions = [
        (e["payload"].get("from"), e["payload"].get("to"))
        for e in _emitted_events(emitted) if e["kind"] == "structure_state_changed"
    ]
    assert ("planned", "under_construction") in transitions
    assert ("under_construction", "operational") in transitions
    # building_operational carries the granted function.
    op = [e for e in _emitted_events(emitted) if e["kind"] == "building_operational"][0]
    assert op["payload"]["function"] == "voting"
    # routed_via flowed onto the domain events (W6 chain metadata still present).
    assert all("routed_via" in e["payload"] for e in _emitted_events(emitted)
               if e["kind"] in ("project_funded", "project_built", "building_operational"))


def test_runtime_gated_build_step_idles_through_loop_without_mutating():
    """A gated build_step (planned, not under_construction) driven through the loop
    resolves to a clean parse_failure/idle and mutates nothing — the gate fires
    BEFORE dispatch, never reaching world-core."""
    world, agents = _world()
    a = agents[0]
    a.location = "plaza"
    bid = _propose(world, a, "Clock", "clocktower", 10)  # planned
    loop, emitted = _loop_with_script(
        world, a, [{"action": "build_step", "args": {"building_id": bid}}]
    )
    asyncio.run(loop._execute_turn(a))
    assert world.buildings[bid].progress == 0
    assert world.buildings[bid].status == "planned"
    resolved = [e for e in _emitted_events(emitted) if e["kind"] == "action_resolved"][-1]
    assert resolved["payload"]["outcome"] == "failed"


def test_api_governance_spawn_creates_admit_rule_and_admits_on_pass(api_client):
    """The HIGH fix: POST /api/agents (governance) actually calls
    world.enqueue_admit_agent -> an admit_agent RULE exists carrying the spec, its
    id is returned as proposal_id, and once the living agents vote it through, the
    agent is admitted (method=governance). Previously the API called a non-existent
    `propose_admit_agent` and silently no-op'd (no rule, no admission)."""
    import petridish.api.app  # noqa: F401
    appmod = sys.modules["petridish.api.app"]
    world = appmod._world
    assert world is not None
    before = _state_names(api_client)

    r = api_client.post(
        "/api/agents", json={"name": "Wren", "profile": "mock", "mode": "governance"}
    )
    assert r.status_code == 202
    proposal_id = r.json()["proposal_id"]

    # A REAL admit_agent rule now exists in world-core (not a silent no-op), keyed
    # by the returned proposal_id, carrying the pending agent spec.
    rule = world.rules.get(proposal_id)
    assert rule is not None, "governance spawn must create an admit_agent rule"
    assert rule.effect == "admit_agent"
    assert rule.status == "proposed"
    assert rule.payload.get("name") == "Wren"
    assert "Wren" not in before and "Wren" not in _state_names(api_client), "absent pre-vote"

    # Vote it through with the living agents -> the agent is admitted.
    # Civic actions are gated to the governance place — gather voters there.
    hall = next(p.id for p in world.places.values() if p.kind == "governance")
    living = [a for a in world.agents.values() if a.alive]
    assert living, "need living agents to pass the admit vote"
    for voter in living:
        voter.location = hall
        world.action_vote(voter, proposal_id, True)
    assert rule.status == "active", "unanimous YES must pass the admit_agent rule"
    assert any(a.name == "Wren" for a in world.agents.values()), "agent admitted once vote passes"

    # The governance-spawn event is queued with method=governance + proposal_id.
    drained = world.drain_spawn_events()
    assert any(
        e["kind"] == "agent_spawned"
        and e["payload"].get("method") == "governance"
        and e["payload"].get("proposal_id") == proposal_id
        for e in drained
    )

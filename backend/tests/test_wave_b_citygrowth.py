"""
Wave B / EM-115 — deterministic city growth (auto-build reflex).

Contract under test: contracts/wave-b.md §"Agent B1 — backend-world".

Funded (under_construction) collective projects must ALWAYS finish: each round
World.advance_buildings() adds buildings.auto_build_per_round progress with zero
LLM calls, refreshing last_progress_tick so funded projects no longer rot to
abandoned. Completion rides the SAME shared helper as the agent build_step path
(_complete_construction), so structure_state_changed + building_operational
events carry identical payload keys and function activation (forage buffs)
works for auto-completed buildings. planned/unfunded stalls still abandon, and
auto_build_per_round=0 restores the pre-EM-115 behavior entirely.

Everything here is deterministic and offline — pure world-core mechanics driven
through the World.action_* API + advance_buildings(), per the test_w7.py
harness pattern.
"""
from __future__ import annotations

import math

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, BuildingParams


AUTO = 10          # auto_build_per_round used across these tests (the default)
WINDOW = 5         # short abandon window so stall tests stay cheap
FORAGE_BONUS = 3


# ──────────────────────────────────────────────────────────────────────────────
# Helpers (test_w7.py pattern)
# ──────────────────────────────────────────────────────────────────────────────

def _params(**building_overrides) -> WorldParams:
    """Deterministic, decay-free WorldParams with a knowable buildings block."""
    p = WorldParams(
        energy_decay_per_turn=0.0,
        starting_energy=100.0,
        starting_credits=200,
        work_reward=4,
        forage_reward=1,
        death_after_zero_turns=99,
    )
    kwargs = dict(
        enabled=True,
        build_step=20,
        abandon_after_ticks=WINDOW,
        arson_damage=60,
        forage_bonus=FORAGE_BONUS,
        work_bonus_pct=50,
        auto_build_per_round=AUTO,
    )
    kwargs.update(building_overrides)
    p.buildings = BuildingParams(**kwargs)
    return p


def _world(params: WorldParams | None = None) -> tuple[World, AgentState]:
    params = params or _params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agent = AgentState(
        id="a0", name="Ada", personality="builder", profile="mock",
        location="plaza", energy=params.starting_energy,
        credits=params.starting_credits,
    )
    world = World(params=params, places=places, agents=[agent])
    return world, agent


def _funded_project(world: World, agent: AgentState, *, name="Herb Garden",
                    kind="garden", funds=10, function="+forage") -> str:
    """Propose + fully fund a project -> under_construction at 0%."""
    res = world.action_propose_project(agent, name, kind, funds, function)
    bid = res["_building_id"]
    world.action_contribute_funds(agent, bid, funds)
    assert world.buildings[bid].status == "under_construction"
    assert world.buildings[bid].progress == 0
    return bid


def _round(world: World) -> list[dict]:
    """One loop round as the engine sees it: tick advances, then the per-round
    building lifecycle reflex runs (loop.py calls advance_buildings once/round)."""
    world.tick += 1
    return world.advance_buildings()


def _events_of(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e["kind"] == kind]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Funded project completes in ceil(100/auto) rounds with ZERO build_step
# ──────────────────────────────────────────────────────────────────────────────

def test_funded_project_auto_completes_in_ceil_rounds_without_build_steps():
    world, agent = _world()
    bid = _funded_project(world, agent)
    bld = world.buildings[bid]
    rounds_needed = math.ceil(100 / AUTO)

    all_events: list[dict] = []
    # Every round short of completion: progress creeps, stays under_construction,
    # and interim progress is SILENT (no per-round feed spam).
    for r in range(1, rounds_needed):
        evts = _round(world)
        all_events.extend(evts)
        assert bld.status == "under_construction"
        assert bld.progress == AUTO * r
        assert evts == [], f"interim round {r} must be silent, got {evts}"
        # Auto-build refreshes the stall clock — funded projects cannot rot.
        assert bld.last_progress_tick == world.tick

    # The ceil(100/auto)-th round completes it.
    evts = _round(world)
    all_events.extend(evts)
    assert bld.status == "operational"
    assert bld.progress == 100
    assert bld.health == 100
    assert [e["kind"] for e in evts] == [
        "structure_state_changed", "building_operational"]
    assert len(_events_of(all_events, "building_operational")) == 1

    # System reflex, not an agent action: no actor (abandonment event pattern).
    for e in evts:
        assert e["actor_id"] is None

    # Once operational the reflex leaves it alone.
    assert _round(world) == []
    assert bld.progress == 100


def test_funded_project_never_abandons_even_past_the_idle_window():
    """Intended EM-115 semantics change: auto-build refreshes last_progress_tick,
    so a funded project can no longer rot to abandoned no matter the gap."""
    world, agent = _world()
    bid = _funded_project(world, agent, funds=10)
    bld = world.buildings[bid]

    # Jump far past the abandon window between rounds — still builds, never rots.
    for _ in range(math.ceil(100 / AUTO)):
        world.tick += WINDOW + 10
        world.advance_buildings()
        assert bld.status != "abandoned"
    assert bld.status == "operational"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Completion events match the build_step path (shared helper)
# ──────────────────────────────────────────────────────────────────────────────

def test_auto_completion_payload_keys_match_build_step_completion_path():
    # Path A — agent build_step completion (the existing W7 social path).
    world_a, agent_a = _world()
    bid_a = _funded_project(world_a, agent_a)
    last = None
    for _ in range(5):  # 5 x 20% = 100
        last = world_a.action_build_step(agent_a, bid_a)
    step_state = _events_of(last["_multi"], "structure_state_changed")[-1]
    step_oper = _events_of(last["_multi"], "building_operational")[0]

    # Path B — auto-build completion (EM-115 reflex).
    world_b, agent_b = _world()
    bid_b = _funded_project(world_b, agent_b)
    auto_events: list[dict] = []
    for _ in range(math.ceil(100 / AUTO)):
        auto_events.extend(_round(world_b))
    auto_state = _events_of(auto_events, "structure_state_changed")[0]
    auto_oper = _events_of(auto_events, "building_operational")[0]

    # building_operational: the contract-mandated payload keys, identical sets.
    for payload in (step_oper["payload"], auto_oper["payload"]):
        assert {"building_id", "kind", "function", "location"} <= set(payload)
    assert set(auto_oper["payload"]) == set(step_oper["payload"])
    assert auto_oper["payload"]["building_id"] == bid_b
    assert auto_oper["payload"]["kind"] == "garden"
    assert auto_oper["payload"]["function"] == "+forage"
    assert auto_oper["payload"]["location"] == "plaza"

    # structure_state_changed: same keys, same under_construction -> operational.
    assert set(auto_state["payload"]) == set(step_state["payload"])
    assert (auto_state["payload"]["from"], auto_state["payload"]["to"]) == \
        ("under_construction", "operational")
    assert (step_state["payload"]["from"], step_state["payload"]["to"]) == \
        ("under_construction", "operational")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Function activation after auto-completion (invariant 6 still holds)
# ──────────────────────────────────────────────────────────────────────────────

def test_function_activates_after_auto_completion_forage_bonus_applies():
    world, agent = _world()
    bid = _funded_project(world, agent, kind="garden")

    # Not operational yet: base forage only (invariant 6 — function gated).
    ok, _, reward = world.action_forage(agent)
    assert ok and reward == world.params.forage_reward

    for _ in range(math.ceil(100 / AUTO)):
        _round(world)
    assert world.buildings[bid].status == "operational"
    assert world.operational_building_at("plaza", "garden") is not None

    ok, _, reward = world.action_forage(agent)
    assert ok and reward == world.params.forage_reward + FORAGE_BONUS


# ──────────────────────────────────────────────────────────────────────────────
# 4. planned/unfunded projects do NOT auto-advance and still abandon
# ──────────────────────────────────────────────────────────────────────────────

def test_planned_unfunded_project_does_not_auto_advance_and_still_abandons():
    world, agent = _world()
    res = world.action_propose_project(agent, "Clock Tower", "clocktower", 50)
    bid = res["_building_id"]
    bld = world.buildings[bid]

    # Inside the window: no progress, no events, still planned.
    for _ in range(WINDOW):
        evts = _round(world)
        assert evts == []
        assert bld.status == "planned"
        assert bld.progress == 0

    # Past the window: rots to abandoned exactly as before EM-115.
    evts = _round(world)
    assert [e["kind"] for e in evts] == ["structure_state_changed"]
    assert (evts[0]["payload"]["from"], evts[0]["payload"]["to"]) == \
        ("planned", "abandoned")
    assert evts[0]["actor_id"] is None
    assert bld.status == "abandoned"
    assert bld.progress == 0


# ──────────────────────────────────────────────────────────────────────────────
# 5. auto_build_per_round=0 — the escape hatch restores old behavior
# ──────────────────────────────────────────────────────────────────────────────

def test_auto_build_zero_disables_reflex_and_stalled_construction_abandons():
    world, agent = _world(_params(auto_build_per_round=0))
    bid = _funded_project(world, agent)
    bld = world.buildings[bid]
    world.action_build_step(agent, bid)  # one social step (20%), then stalls
    assert bld.progress == 20
    start = bld.last_progress_tick

    # Inside the window: nothing moves (no auto progress, no tick refresh).
    for _ in range(WINDOW):
        assert _round(world) == []
        assert bld.progress == 20
        assert bld.last_progress_tick == start
        assert bld.status == "under_construction"

    # Past the window: pre-EM-115 stall rot.
    evts = _round(world)
    assert [e["payload"]["to"] for e in evts] == ["abandoned"]
    assert bld.status == "abandoned"
    assert bld.progress == 20


# ──────────────────────────────────────────────────────────────────────────────
# 6. build_step + auto-build compose: clamp at 100, exactly one completion
# ──────────────────────────────────────────────────────────────────────────────

def test_build_step_and_auto_build_compose_clamped_single_completion():
    world, agent = _world()
    bid = _funded_project(world, agent)
    bld = world.buildings[bid]
    all_events: list[dict] = []

    # 4 social steps (80%) interleaved with 1 auto round (90%).
    for _ in range(4):
        all_events.extend(world.action_build_step(agent, bid)["_multi"])
        assert bld.progress <= 100
    assert bld.progress == 80
    all_events.extend(_round(world))
    assert bld.progress == 90
    assert bld.status == "under_construction"

    # Final build_step would overshoot (90 + 20): clamped to 100, completes once.
    all_events.extend(world.action_build_step(agent, bid)["_multi"])
    assert bld.progress == 100
    assert bld.status == "operational"
    assert len(_events_of(all_events, "building_operational")) == 1

    # Subsequent rounds never re-complete, re-emit, or push past 100.
    for _ in range(3):
        all_events.extend(_round(world))
    assert bld.progress == 100
    assert len(_events_of(all_events, "building_operational")) == 1


def test_auto_overshoot_clamps_at_100():
    """auto_build_per_round larger than the remaining gap clamps at exactly 100."""
    world, agent = _world(_params(auto_build_per_round=33))
    bid = _funded_project(world, agent)
    bld = world.buildings[bid]
    events: list[dict] = []
    for _ in range(3):  # 33, 66, 99
        events.extend(_round(world))
    assert bld.status == "under_construction" and bld.progress == 99
    events.extend(_round(world))  # round ceil(100/33)=4: 99+33 clamps to 100
    assert bld.status == "operational" and bld.progress == 100
    assert len(_events_of(events, "building_operational")) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 7. Contract guard: auto_build_per_round never leaks into Building.to_dict()
# ──────────────────────────────────────────────────────────────────────────────

def test_building_to_dict_unchanged_by_em115():
    world, agent = _world()
    bid = _funded_project(world, agent)
    _round(world)
    d = world.buildings[bid].to_dict()
    assert "auto_build_per_round" not in d
    assert set(d) == {
        "id", "name", "kind", "location", "owner_id", "status", "health",
        "condition_label", "progress", "funds_committed", "funds_required",
        "contributors", "function", "last_progress_tick", "created_tick",
        "updated_tick", "position",   # EM-268 F1 — free-placement 2-D position
    }

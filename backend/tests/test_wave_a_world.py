"""
Wave A — backend-world items (contracts/wave-a.md, Agent W).

EM-129  humanize agent-built building names (snake_case → display, raw_name kept)
EM-132  build_step on a damaged building redirects to repair (no wasted turn)
EM-133  contribute_funds clamps at the remaining funding gap (never overshoots)
EM-134  per-building animal-damage cooldown (first hit lands, then shooed away)
EM-108  governance location gate at resolution time (propose_rule / vote)
"""
from __future__ import annotations

from petridish.config.loader import WorldParams
from petridish.engine.world import (
    AgentState,
    Building,
    PlaceState,
    World,
    _humanize_project_name,
)


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
        PlaceState(id="townhall", name="Town Hall", x=0, y=10, kind="governance"),
    ]


def _agent(aid: str, name: str, location: str = "plaza",
           credits: int = 50) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=80.0, credits=credits)


def _world(agents: list[AgentState] | None = None,
           places: list[PlaceState] | None = None) -> World:
    agents = agents if agents is not None else [_agent("agent_ada", "Ada")]
    return World(params=_params(), places=places or _places(), agents=agents)


def _kinds(res: dict) -> list[str]:
    return [e["kind"] for e in res["_multi"]]


def _propose(world: World, agent: AgentState, name: str, kind: str,
             funds: int, function: str | None = None) -> str:
    res = world.action_propose_project(agent, name, kind, funds, function)
    assert "_building_id" in res, res
    return res["_building_id"]


# ══════════════════════════════════════════════════════════════════════════════
# EM-129 — humanize agent-built building names
# ══════════════════════════════════════════════════════════════════════════════

def test_humanize_snake_case_becomes_title_case():
    assert _humanize_project_name("prepare_beds") == "Prepare Beds"
    assert _humanize_project_name("village_fair") == "Village Fair"
    assert _humanize_project_name("market-stall") == "Market Stall"


def test_humanize_collapses_whitespace_and_keeps_styled_names():
    assert _humanize_project_name("  the   grand    hall ") == "The Grand Hall"
    # Already-styled names pass through untouched (no forced Title Case).
    assert _humanize_project_name("Bram's Market Stall") == "Bram's Market Stall"
    assert _humanize_project_name("HQ of the Cats") == "HQ of the Cats"


def test_humanize_junk_yields_empty_for_fallback():
    assert _humanize_project_name("") == ""
    assert _humanize_project_name("   ") == ""
    assert _humanize_project_name("!!??--__") == ""
    assert _humanize_project_name("x") == ""  # single character


def test_humanize_caps_at_sixty():
    assert len(_humanize_project_name("a_" * 100)) <= 60


def test_propose_project_stores_display_name_and_raw_name_payload():
    world = _world()
    ada = world.agents["agent_ada"]
    res = world.action_propose_project(ada, "prepare_beds", "garden", 5)
    building = world.buildings[res["_building_id"]]
    assert building.name == "Prepare Beds", "Building.name stores the DISPLAY name"
    proposed = res["_multi"][0]
    assert proposed["kind"] == "project_proposed"
    assert proposed["payload"]["name"] == "Prepare Beds"
    assert proposed["payload"]["raw_name"] == "prepare_beds", "raw arg preserved"
    assert "Prepare Beds" in proposed["text"]
    # kind stays a raw key (the frontend maps it — EM-130).
    assert building.kind == "garden"


def test_propose_project_junk_name_falls_back_to_agent_and_kind():
    world = _world()
    ada = world.agents["agent_ada"]
    res = world.action_propose_project(ada, "??", "market_stall", 5)
    building = world.buildings[res["_building_id"]]
    assert building.name == "Ada's Market Stall"
    assert res["_multi"][0]["payload"]["raw_name"] == "??"


def test_propose_project_junk_name_and_junk_kind_fall_back_to_project():
    world = _world()
    ada = world.agents["agent_ada"]
    res = world.action_propose_project(ada, "", "!", 5)
    building = world.buildings[res["_building_id"]]
    assert building.name == "Ada's Project"


# ══════════════════════════════════════════════════════════════════════════════
# EM-132 — build_step on a damaged building redirects to repair
# ══════════════════════════════════════════════════════════════════════════════

def _damaged_building(world: World, location: str = "plaza") -> Building:
    b = Building(id="bld_booth", name="The Booth", kind="workshop",
                 location=location, status="damaged", health=40,
                 progress=100, funds_committed=5, funds_required=5)
    world.buildings[b.id] = b
    return b


def test_build_step_on_damaged_redirects_to_repair():
    world = _world()
    ada = world.agents["agent_ada"]
    b = _damaged_building(world)
    res = world.action_build_step(ada, b.id)
    # The existing repair semantics ran: health restored, operational again.
    assert b.health == 100
    assert b.status == "operational"
    assert _kinds(res) == ["economy", "structure_state_changed"]
    economy = res["_multi"][0]
    assert "switched to repairing" in economy["text"], "redirect must be legible"
    assert economy["payload"]["action"] == "repair"
    assert economy["payload"]["redirected_from"] == "build_step"
    state = res["_multi"][1]
    assert (state["payload"]["from"], state["payload"]["to"]) == (
        "damaged", "operational")


def test_build_step_other_invalid_statuses_keep_failing():
    world = _world()
    ada = world.agents["agent_ada"]
    for status in ("operational", "destroyed", "abandoned"):
        b = Building(id=f"bld_{status}", name="X", kind="workshop",
                     location="plaza", status=status, health=50)
        world.buildings[b.id] = b
        res = world.action_build_step(ada, b.id)
        assert res["kind"] == "parse_failure", status
        assert res["payload"]["error"] == f"cannot build a {status} structure"
    # offline keeps its current (not-under-construction) failure too.
    b = Building(id="bld_offline", name="X", kind="workshop",
                 location="plaza", status="offline", health=100)
    world.buildings[b.id] = b
    res = world.action_build_step(ada, b.id)
    assert res["kind"] == "parse_failure"
    assert res["payload"]["error"] == "project is not under construction"


# ══════════════════════════════════════════════════════════════════════════════
# EM-133 — contribute_funds clamps at the remaining gap
# ══════════════════════════════════════════════════════════════════════════════

def test_contribute_overshoot_is_clamped_to_the_gap():
    world = _world()
    ada = world.agents["agent_ada"]  # 50 credits
    bid = _propose(world, ada, "Snack Booth", "workshop", 5)
    res = world.action_contribute_funds(ada, bid, 12)  # the live 12/5 booth
    b = world.buildings[bid]
    assert b.funds_committed == 5, "never exceeds funds_required"
    assert ada.credits == 45, "ONLY the clamped amount is deducted"
    economy = res["_multi"][0]
    assert economy["payload"]["amount_requested"] == 12
    assert economy["payload"]["amount_applied"] == 5
    assert economy["payload"]["credits_delta"] == -5
    assert "clamped" in economy["text"]
    # The flip to under_construction still fires on the clamped full funding.
    assert b.status == "under_construction"


def test_contribute_exact_fit_unchanged():
    world = _world()
    ada = world.agents["agent_ada"]
    bid = _propose(world, ada, "Mill", "workshop", 10)
    res = world.action_contribute_funds(ada, bid, 10)
    b = world.buildings[bid]
    assert b.funds_committed == 10
    assert ada.credits == 40
    economy = res["_multi"][0]
    assert economy["payload"]["amount_requested"] == 10
    assert economy["payload"]["amount_applied"] == 10
    assert "clamped" not in economy["text"]


def test_contribute_zero_gap_soft_fails_costing_nothing():
    world = _world()
    ada = world.agents["agent_ada"]
    bid = _propose(world, ada, "Mill", "workshop", 5)
    world.action_contribute_funds(ada, bid, 5)
    before = ada.credits
    res = world.action_contribute_funds(ada, bid, 3)
    assert res["kind"] == "parse_failure"
    assert res["payload"]["error"] == "already fully funded"
    assert "build_step" in res["text"], "soft failure must carry guidance"
    assert ada.credits == before, "a zero-gap contribution costs nothing"
    assert world.buildings[bid].funds_committed == 5


def test_contribute_partial_then_overshoot_never_exceeds_required():
    world = _world()
    ada = world.agents["agent_ada"]
    bid = _propose(world, ada, "Mill", "workshop", 10)
    world.action_contribute_funds(ada, bid, 7)
    world.action_contribute_funds(ada, bid, 9)  # gap is 3 — clamp to 3
    b = world.buildings[bid]
    assert b.funds_committed == 10
    assert ada.credits == 40
    assert b.funds_committed <= b.funds_required


def test_contribute_insufficient_for_clamped_amount_still_rejected():
    world = _world()
    ada = world.agents["agent_ada"]
    ada.credits = 2
    bid = _propose(world, ada, "Mill", "workshop", 10)
    res = world.action_contribute_funds(ada, bid, 8)  # clamp 8, holds 2
    assert res["kind"] == "parse_failure"
    assert ada.credits == 2
    assert world.buildings[bid].funds_committed == 0


# ══════════════════════════════════════════════════════════════════════════════
# EM-134 — animal-damage cooldown per building
# ══════════════════════════════════════════════════════════════════════════════

def _operational_building(world: World, bid: str = "bld_hall") -> Building:
    b = Building(id=bid, name="Hall", kind="monument", location="plaza",
                 status="operational", health=100, progress=100)
    world.buildings[b.id] = b
    return b


def test_animal_damage_first_hit_always_lands():
    world = _world()
    b = _operational_building(world)
    evt = world.animal_damage_building(b.id, 10)
    assert evt is not None
    assert b.health == 90
    assert b.status == "damaged"


def test_animal_damage_blocked_within_cooldown_window():
    world = _world()
    b = _operational_building(world)
    world.tick = 10
    assert world.animal_damage_building(b.id, 10) is not None
    # Every tick inside the 6-tick window resolves harmlessly: no health loss,
    # no state change (the critter is shooed away).
    for tick in range(10, 10 + World.ANIMAL_DAMAGE_COOLDOWN_TICKS):
        world.tick = tick
        assert world.animal_damage_building(b.id, 10) is None
        assert b.health == 90
        assert b.status == "damaged"


def test_animal_damage_allowed_again_after_cooldown():
    world = _world()
    b = _operational_building(world)
    world.tick = 10
    assert world.animal_damage_building(b.id, 10) is not None
    world.tick = 10 + World.ANIMAL_DAMAGE_COOLDOWN_TICKS
    evt = world.animal_damage_building(b.id, 10)
    assert evt is not None
    assert b.health == 80


def test_human_arson_unaffected_by_animal_cooldown():
    world = _world()
    ada = world.agents["agent_ada"]
    b = _operational_building(world)
    world.tick = 10
    assert world.animal_damage_building(b.id, 10) is not None
    # Same tick, human arson still lands (the cooldown is animal-only).
    res = world.action_arson(ada, b.id)
    assert res["_multi"][0]["kind"] == "conflict"
    assert b.health < 90


def test_cooldown_field_not_serialized():
    world = _world()
    b = _operational_building(world)
    world.animal_damage_building(b.id, 10)
    assert "last_animal_damage_tick" not in b.to_dict(), "non-contract field"


# ══════════════════════════════════════════════════════════════════════════════
# EM-108 — governance location gate at resolution time
# ══════════════════════════════════════════════════════════════════════════════

def test_propose_rule_fails_away_from_governance_place():
    world = _world([_agent("agent_ada", "Ada", "market")])
    ada = world.agents["agent_ada"]
    ok, reason, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert not ok and rule is None
    assert reason == "civic actions happen at the town hall — move there first"


def test_propose_rule_succeeds_at_governance_place():
    world = _world([_agent("agent_ada", "Ada", "townhall")])
    ada = world.agents["agent_ada"]
    ok, reason, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert ok and rule is not None, reason


def test_vote_is_not_location_gated_em199():
    """EM-199 — voting is UN-gated: a civic vote lands from ANYWHERE (governance
    was dead when only the proposer, at Town Hall, could vote — run 648). Bo
    votes from the plaza and it counts. PROPOSING a rule still requires Town
    Hall (see the propose_rule tests)."""
    world = _world([
        _agent("agent_ada", "Ada", "townhall"),
        _agent("agent_bo", "Bo", "plaza"),
    ])
    ada, bo = world.agents["agent_ada"], world.agents["agent_bo"]
    ok, _, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert ok
    ok, reason, _ = world.action_vote(bo, rule.id, True)
    assert ok, f"vote should land from the plaza now (un-gated): {reason}"
    assert rule.votes.get(bo.id) is True, "the off-governance vote must be recorded"


def test_vote_succeeds_at_governance_place():
    world = _world([
        _agent("agent_ada", "Ada", "townhall"),
        _agent("agent_bo", "Bo", "townhall"),
    ])
    ada, bo = world.agents["agent_ada"], world.agents["agent_bo"]
    ok, _, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert ok
    ok, _, _ = world.action_vote(ada, rule.id, True)
    assert ok
    ok, _, new_status = world.action_vote(bo, rule.id, True)
    assert ok
    assert new_status == "active"


def test_gate_is_on_place_kind_not_the_townhall_id():
    """The procgen invariant makes the first governance place id 'townhall',
    but the gate keys on kind == governance, never the hardcoded id."""
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="moot_ring", name="Moot Ring", x=5, y=5, kind="governance"),
    ]
    world = _world([_agent("agent_ada", "Ada", "moot_ring")], places=places)
    ada = world.agents["agent_ada"]
    ok, reason, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert ok and rule is not None, reason


def test_gate_exempts_worlds_without_any_governance_place():
    """Legacy / hand-rolled layouts with no governance place anywhere cannot
    demand civic actions happen at a town hall that does not exist."""
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    world = _world([_agent("agent_ada", "Ada", "market")], places=places)
    ada = world.agents["agent_ada"]
    ok, _, rule = world.action_propose_rule(ada, "ubi", "Basic income!")
    assert ok and rule is not None
    ok, _, _ = world.action_vote(ada, rule.id, True)
    assert ok

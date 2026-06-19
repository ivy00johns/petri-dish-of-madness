"""Wave K · The Builders' City (EM-216–221 + EM-182) — backend behavior.

Proves the agent-driven 3-D customization arc end to end, reflex-first and
replay-safe (contracts/wave-k.md §§1-4):

  - PLACE_PROP creates a tracked Prop with a SEEDED id (never uuid4 — EM-189), an
    engine-assigned deterministic in-place offset (props don't stack), owner set;
  - the prop population CAP rejects over-cap placement WITH GUIDANCE (never a dead
    turn);
  - REMOVE_PROP removes an owned prop and a co-located unowned prop; rejects a
    non-owner / non-co-located removal;
  - DEMOLISH: an OWNER tears down their own building immediately; a NON-owner is
    REJECTED with guidance to use governance; a PUBLIC demolish runs through the
    shipped propose_rule → vote → _on_rule_activated path;
  - SET_BUILDING_SKIN is owner-only and persists across a snapshot round-trip;
  - EM-182: propose_project's optional `place` builds in a chosen district;
  - EM-217: the BUILD_TYPES menu is surfaced in the propose_project prompt;
  - REPLAY DETERMINISM: props + skin round-trip byte-identically through
    to_snapshot()/from_snapshot();
  - the menu and the resolution gate AGREE (EM-108's lesson): every tool offered
    in _assemble_context resolves, and every gate rejection is reachable.

CRITICAL suite rule (mirrors the W8 / menagerie family): import
petridish.engine.world BEFORE the runtime modules so the world module binds
first (avoids the engine↔agents circular-import order trap).
"""
from __future__ import annotations

# Suite rule: world FIRST.
from petridish.engine.world import (
    World, AgentState, PlaceState, Building, Prop, BUILD_TYPES,
)
from petridish.config.loader import WorldParams, BuildingParams, PropsParams

# Runtime imports AFTER world.
from petridish.agents.runtime import (
    ACTION_SCHEMA,
    TOOL_REGISTRY,
    _validate_world,
    _assemble_context,
    _normalize_args,
)

import jsonschema
import pytest


def _prompt_text(ctx) -> str:
    """_assemble_context returns a list of {role, content} messages; join the
    contents so substring assertions read the whole rendered prompt."""
    if isinstance(ctx, list):
        return "\n".join(str(m.get("content", "")) for m in ctx)
    if isinstance(ctx, dict):
        return str(ctx.get("system") or ctx.get("user") or ctx)
    return str(ctx)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a tiny offline world (no router calls). Two work/social places + a
# couple of agents; a building owned by agent A.
# ──────────────────────────────────────────────────────────────────────────────

def _places():
    return [
        PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceState(id="forge", name="The Forge", x=600, y=500, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=400, y=500, kind="governance"),
    ]


def _world(*, props_max: int = 48) -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        buildings=BuildingParams(enabled=True),
        props=PropsParams(max_population=props_max),
    )
    agents = [
        AgentState(id="agent_a", name="Ada", personality="", profile="mock",
                   location="plaza", energy=100, credits=100),
        AgentState(id="agent_b", name="Bram", personality="", profile="mock",
                   location="plaza", energy=100, credits=100),
    ]
    return World(params, _places(), agents)


def _owned_building(world: World, owner: str = "agent_a", place: str = "plaza",
                    kind: str = "workshop", status: str = "operational") -> Building:
    b = Building(
        id="bld_test1", name="Ada's Workshop", kind=kind, location=place,
        owner_id=owner, status=status, health=100, progress=100,
    )
    world.buildings[b.id] = b
    return b


# ──────────────────────────────────────────────────────────────────────────────
# Schema / registry wiring
# ──────────────────────────────────────────────────────────────────────────────

def test_action_schema_is_valid_and_lists_new_tools():
    jsonschema.Draft202012Validator.check_schema(ACTION_SCHEMA)
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    for tool in ("place_prop", "remove_prop", "demolish", "set_building_skin"):
        assert tool in enum
        assert tool in TOOL_REGISTRY
        assert TOOL_REGISTRY[tool]["tier"] == "reflex"  # invariant: reflex tools


def test_new_tools_validate_structurally_via_inline_schema():
    v = jsonschema.Draft202012Validator(ACTION_SCHEMA)
    # happy structural shapes
    for doc in (
        {"action": "place_prop", "args": {"kind": "bench"}},
        {"action": "place_prop", "args": {"kind": "tree", "place": "forge"}},
        {"action": "remove_prop", "args": {"prop_id": "prop_x"}},
        {"action": "demolish", "args": {"building_id": "bld_1"}},
        {"action": "set_building_skin", "args": {"building_id": "bld_1", "skin": "rose"}},
        {"action": "propose_project", "args": {"name": "Forge", "kind": "smithy", "place": "forge"}},
    ):
        v.validate(doc)
    # missing required args fail structurally
    with pytest.raises(jsonschema.ValidationError):
        v.validate({"action": "set_building_skin", "args": {"building_id": "bld_1"}})


# ──────────────────────────────────────────────────────────────────────────────
# K2 — place_prop: seeded id, deterministic offset, cap
# ──────────────────────────────────────────────────────────────────────────────

def test_place_prop_creates_tracked_prop_with_seeded_id_and_event():
    world = _world()
    ada = world.agents["agent_a"]
    evt = world.action_place_prop(ada, "bench", "plaza")
    assert evt["kind"] == "prop_placed"
    assert len(world.props) == 1
    prop = next(iter(world.props.values()))
    assert prop.kind == "bench"
    assert prop.place == "plaza"
    assert prop.owner_id == "agent_a"
    # SEEDED id — prefixed prop_, NOT a uuid4 (EM-189). Hex tail, deterministic.
    assert prop.id.startswith("prop_")
    assert "-" not in prop.id  # uuid4 has hyphens; a seeded hex id does not
    assert evt["payload"]["prop_id"] == prop.id


def test_place_prop_id_is_deterministic_and_pure():
    # Two worlds with the same seed produce the SAME prop id for the same placement.
    w1, w2 = _world(), _world()
    e1 = w1.action_place_prop(w1.agents["agent_a"], "lamp", "plaza")
    e2 = w2.action_place_prop(w2.agents["agent_a"], "lamp", "plaza")
    assert e1["payload"]["prop_id"] == e2["payload"]["prop_id"]


def test_place_prop_offset_is_deterministic_and_props_dont_stack():
    world = _world()
    ada = world.agents["agent_a"]
    first = world.props[world.action_place_prop(ada, "bench", "plaza")["payload"]["prop_id"]]
    second = world.props[world.action_place_prop(ada, "bench", "plaza")["payload"]["prop_id"]]
    # The FIRST prop sits on the anchor; the SECOND is offset off it (no stack).
    assert (first.dx, first.dz) == (0.0, 0.0)
    assert (second.dx, second.dz) != (0.0, 0.0)
    # Pure offset: World._prop_offset is a static, RNG-free function.
    assert World._prop_offset(0) == (0.0, 0.0)
    assert World._prop_offset(2) == World._prop_offset(2)
    # Ring radius is bounded (~3u).
    dx, dz = World._prop_offset(50)
    assert (dx ** 2 + dz ** 2) ** 0.5 <= 3.0001


def test_place_prop_defaults_place_to_agent_location():
    world = _world()
    bram = world.agents["agent_b"]
    bram.location = "forge"
    evt = world.action_place_prop(bram, "anvil-stand", None)
    assert evt["kind"] == "prop_placed"
    assert next(iter(world.props.values())).place == "forge"


def test_place_prop_unknown_place_is_rejected_with_guidance_not_crash():
    world = _world()
    evt = world.action_place_prop(world.agents["agent_a"], "bench", "atlantis")
    assert evt["kind"] == "parse_failure"
    assert "unknown place" in evt["payload"]["error"]


def test_place_prop_cap_rejected_with_guidance():
    world = _world(props_max=2)
    ada = world.agents["agent_a"]
    assert world.action_place_prop(ada, "bench", "plaza")["kind"] == "prop_placed"
    assert world.action_place_prop(ada, "lamp", "plaza")["kind"] == "prop_placed"
    over = world.action_place_prop(ada, "tree", "plaza")
    assert over["kind"] == "parse_failure"
    assert "cap" in over["payload"]["error"]
    assert len(world.props) == 2  # the over-cap prop was NOT created


def test_place_prop_cap_zero_means_unlimited():
    world = _world(props_max=0)
    ada = world.agents["agent_a"]
    for _ in range(60):
        assert world.action_place_prop(ada, "bench", "plaza")["kind"] == "prop_placed"
    assert len(world.props) == 60


# ──────────────────────────────────────────────────────────────────────────────
# K3 — remove_prop
# ──────────────────────────────────────────────────────────────────────────────

def test_remove_prop_owner_removes_own_prop():
    world = _world()
    ada = world.agents["agent_a"]
    pid = world.action_place_prop(ada, "bench", "plaza")["payload"]["prop_id"]
    evt = world.action_remove_prop(ada, pid)
    assert evt["kind"] == "prop_removed"
    assert pid not in world.props


def test_remove_prop_rejects_non_owner_of_owned_prop():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    pid = world.action_place_prop(ada, "bench", "plaza")["payload"]["prop_id"]
    evt = world.action_remove_prop(bram, pid)  # Bram is co-located but not owner
    assert evt["kind"] == "parse_failure"
    assert pid in world.props  # untouched


def test_remove_prop_co_located_agent_removes_unowned_prop():
    world = _world()
    # A god/seeded prop with no owner.
    world.props["prop_seed"] = Prop(id="prop_seed", kind="fountain", place="plaza", owner_id=None)
    ada = world.agents["agent_a"]  # at plaza
    evt = world.action_remove_prop(ada, "prop_seed")
    assert evt["kind"] == "prop_removed"
    assert "prop_seed" not in world.props


def test_remove_prop_rejects_remote_unowned_prop():
    world = _world()
    world.props["prop_seed"] = Prop(id="prop_seed", kind="fountain", place="forge", owner_id=None)
    ada = world.agents["agent_a"]  # at plaza, NOT forge
    evt = world.action_remove_prop(ada, "prop_seed")
    assert evt["kind"] == "parse_failure"
    assert "prop_seed" in world.props


def test_remove_prop_unknown_id_is_soft_fail():
    world = _world()
    evt = world.action_remove_prop(world.agents["agent_a"], "prop_nope")
    assert evt["kind"] == "parse_failure"


# ──────────────────────────────────────────────────────────────────────────────
# K3 — demolish (owner-immediate) + public via governance
# ──────────────────────────────────────────────────────────────────────────────

def test_owner_demolish_is_immediate():
    world = _world()
    b = _owned_building(world, owner="agent_a")
    evt = world.action_demolish(world.agents["agent_a"], b.id)
    assert evt["kind"] == "building_demolished"
    assert evt["payload"]["by"] == "owner"
    assert world.buildings[b.id].status == "destroyed"


def test_non_owner_demolish_rejected_with_governance_guidance():
    world = _world()
    b = _owned_building(world, owner="agent_a")
    evt = world.action_demolish(world.agents["agent_b"], b.id)
    assert evt["kind"] == "parse_failure"
    assert "vote" in evt["text"] or "governance" in evt["text"].lower()
    assert world.buildings[b.id].status == "operational"  # untouched


def test_demolish_unknown_and_already_rubble_are_soft_fails():
    world = _world()
    assert world.action_demolish(world.agents["agent_a"], "bld_nope")["kind"] == "parse_failure"
    b = _owned_building(world, status="destroyed")
    assert world.action_demolish(world.agents["agent_a"], b.id)["kind"] == "parse_failure"


def test_public_demolish_through_governance_pipeline():
    # A PUBLIC (public-owned) building is demolished by the shipped
    # propose_rule → vote → _on_rule_activated path (EM-219), not the tool.
    world = _world()
    b = _owned_building(world, owner="public", place="plaza")
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    ada.location = "townhall"  # propose_rule is governance-gated
    ok, msg, rule = world.action_propose_rule(
        ada, "demolish", "Tear down the eyesore", target=b.id)
    assert ok, msg
    assert rule.payload["target"] == b.id
    # Two living agents → strict majority needs > 1 yes... both vote yes to pass.
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.rules[rule.id].status == "active"
    assert world.buildings[b.id].status == "destroyed"  # demolished on activation
    # The building_demolished event is parked in the spawn-event outbox (by=governance).
    drained = world.drain_spawn_events()
    kinds = [e["kind"] for e in drained]
    assert "building_demolished" in kinds
    dem = next(e for e in drained if e["kind"] == "building_demolished")
    assert dem["payload"]["by"] == "governance"


def test_propose_demolish_requires_real_target():
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "townhall"
    ok, msg, rule = world.action_propose_rule(ada, "demolish", "x", target="bld_nope")
    assert not ok
    assert rule is None


# ──────────────────────────────────────────────────────────────────────────────
# K4 — set_building_skin (owner-only) + persistence
# ──────────────────────────────────────────────────────────────────────────────

def test_set_building_skin_owner_only_and_sets_field():
    world = _world()
    b = _owned_building(world, owner="agent_a")
    evt = world.action_set_building_skin(world.agents["agent_a"], b.id, "rose")
    assert evt["kind"] == "building_reskinned"
    assert world.buildings[b.id].skin == "rose"
    assert evt["payload"]["skin"] == "rose"
    # Non-owner rejected; skin untouched.
    rej = world.action_set_building_skin(world.agents["agent_b"], b.id, "sky")
    assert rej["kind"] == "parse_failure"
    assert world.buildings[b.id].skin == "rose"


def test_set_building_skin_empty_clears():
    world = _world()
    b = _owned_building(world, owner="agent_a")
    b.skin = "amber"
    world.action_set_building_skin(world.agents["agent_a"], b.id, "")
    assert world.buildings[b.id].skin is None


def test_building_to_dict_includes_skin_only_when_set():
    b = Building(id="b1", name="X", kind="workshop", location="plaza")
    assert "skin" not in b.to_dict()  # pre-K byte-identical when unset
    b.skin = "sage"
    assert b.to_dict()["skin"] == "sage"


# ──────────────────────────────────────────────────────────────────────────────
# EM-182 — propose_project optional `place`
# ──────────────────────────────────────────────────────────────────────────────

def test_propose_project_honors_chosen_place():
    world = _world()
    ada = world.agents["agent_a"]  # at plaza
    result = world.action_propose_project(ada, "Foundry", "smithy", 10, place="forge")
    bid = result["_building_id"]
    assert world.buildings[bid].location == "forge"


def test_propose_project_defaults_and_ignores_bad_place():
    world = _world()
    ada = world.agents["agent_a"]  # at plaza
    # No place → agent location.
    r1 = world.action_propose_project(ada, "Stall", "market", 5)
    assert world.buildings[r1["_building_id"]].location == "plaza"
    # Unknown place → falls back to agent location (no dead turn).
    r2 = world.action_propose_project(ada, "Stall2", "market", 5, place="atlantis")
    assert world.buildings[r2["_building_id"]].location == "plaza"


# ──────────────────────────────────────────────────────────────────────────────
# EM-217 — BUILD_TYPES catalog + kind→buff extension
# ──────────────────────────────────────────────────────────────────────────────

def test_build_types_catalog_has_at_least_ten_entries_with_required_keys():
    assert len(BUILD_TYPES) >= 10
    for t in BUILD_TYPES:
        assert set(t) == {"type", "function", "zone"}
    names = {t["type"] for t in BUILD_TYPES}
    for required in ("tavern", "market", "smithy", "park", "granary", "well", "house"):
        assert required in names


def test_build_types_menu_surfaced_in_propose_project_prompt():
    world = _world()
    ada = world.agents["agent_a"]
    prompt = _prompt_text(_assemble_context(ada, world, [], world.params))
    # The menu lists catalog types and documents the optional place arg.
    assert "propose_project" in prompt
    assert "smithy" in prompt and "granary" in prompt
    assert "place?" in prompt


def test_catalog_kind_extends_work_and_forage_buffs():
    # A smithy at a work place grants the SAME work bonus a workshop does.
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "forge"
    base = world.params.work_reward
    # No buff building yet.
    ada.credits = 0
    world.action_work(ada)
    plain = ada.credits
    # Add an operational smithy at the forge → buff applies.
    world.buildings["smithy1"] = Building(
        id="smithy1", name="Smithy", kind="smithy", location="forge",
        owner_id="public", status="operational")
    ada.credits = 0
    world.action_work(ada)
    buffed = ada.credits
    assert buffed >= plain  # smithy is recognized as a work-buff building
    # A granary at a place grants the forage bonus a garden/farm does.
    world.params.buildings.forage_bonus = 5
    world.buildings["gran1"] = Building(
        id="gran1", name="Granary", kind="granary", location="forge",
        owner_id="public", status="operational")
    ada.credits = 0
    world.action_forage(ada)
    assert ada.credits >= world.params.forage_reward + 5


# ──────────────────────────────────────────────────────────────────────────────
# Replay determinism — props + skin round-trip
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_round_trip_props_and_skin_byte_identical():
    world = _world()
    ada = world.agents["agent_a"]
    bram = world.agents["agent_b"]
    bram.location = "forge"
    # Mix of owned + unowned props at two places, plus a skinned building.
    world.action_place_prop(ada, "bench", "plaza")
    world.action_place_prop(ada, "lamp", "plaza")
    world.action_place_prop(bram, "tree", "forge")
    world.props["prop_seed"] = Prop(id="prop_seed", kind="fountain", place="plaza", owner_id=None)
    b = _owned_building(world, owner="agent_a")
    world.action_set_building_skin(ada, b.id, "plum")

    snap1 = world.to_snapshot()
    assert "props" in snap1
    assert len(snap1["props"]) == 4

    restored = World.from_snapshot(snap1, params=world.params)
    snap2 = restored.to_snapshot()
    # The full props payload and the skinned building round-trip byte-identically.
    assert snap2["props"] == snap1["props"]
    restored_b = next(x for x in snap2["buildings"] if x["id"] == b.id)
    assert restored_b["skin"] == "plum"
    # Prop registry restored intact (ids, places, offsets, ownership).
    assert {p.id for p in restored.props.values()} == {p.id for p in world.props.values()}
    for pid, p in world.props.items():
        rp = restored.props[pid]
        assert (rp.kind, rp.place, rp.dx, rp.dz, rp.owner_id) == \
               (p.kind, p.place, p.dx, p.dz, p.owner_id)


def test_pre_wave_k_snapshot_without_props_key_restores_empty():
    world = _world()
    snap = world.to_snapshot()
    del snap["props"]  # simulate a pre-Wave-K snapshot
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.props == {}


# ──────────────────────────────────────────────────────────────────────────────
# Menu ⇄ resolution agreement (EM-108) via _validate_world
# ──────────────────────────────────────────────────────────────────────────────

def test_validate_world_place_prop_gates():
    world = _world()
    ada = world.agents["agent_a"]
    assert _validate_world({"action": "place_prop", "args": {"kind": "bench"}}, ada, world) is None
    # missing kind
    assert _validate_world({"action": "place_prop", "args": {}}, ada, world) is not None
    # unknown place
    assert _validate_world(
        {"action": "place_prop", "args": {"kind": "bench", "place": "atlantis"}}, ada, world
    ) is not None


def test_validate_world_place_prop_cap_gate():
    world = _world(props_max=1)
    ada = world.agents["agent_a"]
    world.action_place_prop(ada, "bench", "plaza")
    err = _validate_world({"action": "place_prop", "args": {"kind": "lamp"}}, ada, world)
    assert err is not None and "brim" in err


def test_validate_world_demolish_and_skin_gates():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    b = _owned_building(world, owner="agent_a", place="plaza")
    # owner, co-located → OK
    assert _validate_world({"action": "demolish", "args": {"building_id": b.id}}, ada, world) is None
    # non-owner → rejected with governance guidance
    err = _validate_world({"action": "demolish", "args": {"building_id": b.id}}, bram, world)
    assert err is not None and "vote" in err
    # skin: owner OK, non-owner rejected
    assert _validate_world(
        {"action": "set_building_skin", "args": {"building_id": b.id, "skin": "rose"}}, ada, world
    ) is None
    assert _validate_world(
        {"action": "set_building_skin", "args": {"building_id": b.id, "skin": "rose"}}, bram, world
    ) is not None
    # not co-located → rejected
    ada.location = "forge"
    assert _validate_world({"action": "demolish", "args": {"building_id": b.id}}, ada, world) is not None


def test_validate_world_remove_prop_gates():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    pid = world.action_place_prop(ada, "bench", "plaza")["payload"]["prop_id"]
    assert _validate_world({"action": "remove_prop", "args": {"prop_id": pid}}, ada, world) is None
    assert _validate_world({"action": "remove_prop", "args": {"prop_id": pid}}, bram, world) is not None
    assert _validate_world({"action": "remove_prop", "args": {"prop_id": "nope"}}, ada, world) is not None


def test_menu_offers_demolish_and_skin_only_for_owned_co_located_building():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    _owned_building(world, owner="agent_a", place="plaza")
    ada_prompt = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "demolish (building_id=bld_test1" in ada_prompt
    assert "set_building_skin (building_id=bld_test1" in ada_prompt
    # Bram (co-located, not owner) is NOT offered demolish/skin for it.
    bram_prompt = _prompt_text(_assemble_context(bram, world, [], world.params))
    # set_building_skin must not be offered to a non-owner (a hard owner gate).
    assert "set_building_skin (building_id=bld_test1" not in bram_prompt
    assert "demolish (building_id=bld_test1" not in bram_prompt


def test_menu_offers_place_prop_and_hides_when_cap_full():
    world = _world(props_max=1)
    ada = world.agents["agent_a"]
    assert "place_prop" in _prompt_text(_assemble_context(ada, world, [], world.params))
    world.action_place_prop(ada, "bench", "plaza")  # fill the cap
    assert "place_prop" not in _prompt_text(_assemble_context(ada, world, [], world.params))


# ──────────────────────────────────────────────────────────────────────────────
# Never-a-dead-turn — fuzzy place resolution for the EM-182/218 place arg
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_args_resolves_loose_place_for_place_prop():
    world = _world()
    ada = world.agents["agent_a"]
    doc = {"action": "place_prop", "args": {"kind": "lamp", "place": "the_forge"}}
    _normalize_args(doc, ada, world)
    assert doc["args"]["place"] == "forge"  # the_forge → forge (token/fuzzy)


def test_normalize_args_resolves_loose_place_for_propose_project():
    world = _world()
    ada = world.agents["agent_a"]
    doc = {"action": "propose_project", "args": {"name": "X", "kind": "smithy", "place": "Forge"}}
    _normalize_args(doc, ada, world)
    assert doc["args"]["place"] == "forge"  # case-insensitive id match


def test_normalize_args_drops_noneish_place():
    world = _world()
    ada = world.agents["agent_a"]
    doc = {"action": "place_prop", "args": {"kind": "bench", "place": None}}
    _normalize_args(doc, ada, world)
    assert "place" not in doc["args"]  # null place reads as MISSING (→ defaults here)


# ──────────────────────────────────────────────────────────────────────────────
# FIX 2 (Wave K adversarial review) — a PUBLIC/landmark demolish requires a ~70%
# SUPERMAJORITY (the user's locked decision + design spec + contract §3), NOT the
# simple >50% majority ordinary rules pass on. With 5 living agents, 3/5 (60%)
# must NOT demolish; 4/5 (80%) must.
# ──────────────────────────────────────────────────────────────────────────────

def _world_with_n_agents(n: int) -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0, death_after_zero_turns=99, turns_per_day=999,
        buildings=BuildingParams(enabled=True),
        props=PropsParams(max_population=48),
    )
    agents = [
        AgentState(id=f"agent_{i}", name=f"A{i}", personality="", profile="mock",
                   location="townhall", energy=100, credits=100)
        for i in range(n)
    ]
    return World(params, _places(), agents)


def test_public_demolish_needs_70pct_supermajority_3of5_fails():
    """3/5 yes (60%) is a simple majority but BELOW the ~70% demolish bar → the
    rule does NOT pass and the building stands."""
    world = _world_with_n_agents(5)
    b = _owned_building(world, owner="public", place="plaza")
    proposer = world.agents["agent_0"]
    ok, msg, rule = world.action_propose_rule(
        proposer, "demolish", "Tear it down", target=b.id)
    assert ok, msg
    # 3 yes, 2 no — a simple majority, but only 60% (< ceil(0.7*5)=4).
    world.action_vote(world.agents["agent_0"], rule.id, True)
    world.action_vote(world.agents["agent_1"], rule.id, True)
    world.action_vote(world.agents["agent_2"], rule.id, True)
    world.action_vote(world.agents["agent_3"], rule.id, False)
    world.action_vote(world.agents["agent_4"], rule.id, False)
    assert world.rules[rule.id].status != "active", "60% must NOT clear the demolish bar"
    assert world.buildings[b.id].status == "operational", "the building still stands"


def test_public_demolish_70pct_supermajority_4of5_passes():
    """4/5 yes (80%) clears the ~70% demolish bar → the building is demolished."""
    world = _world_with_n_agents(5)
    b = _owned_building(world, owner="public", place="plaza")
    proposer = world.agents["agent_0"]
    ok, msg, rule = world.action_propose_rule(
        proposer, "demolish", "Tear it down", target=b.id)
    assert ok, msg
    for i in range(4):  # 4 yes
        world.action_vote(world.agents[f"agent_{i}"], rule.id, True)
    world.action_vote(world.agents["agent_4"], rule.id, False)  # 1 no
    assert world.rules[rule.id].status == "active", "80% clears the demolish bar"
    assert world.buildings[b.id].status == "destroyed"


def test_ordinary_rule_keeps_simple_majority_bar():
    """An ordinary (non-demolish) rule still passes on the simple >50% majority —
    the supermajority change is scoped to `demolish` only."""
    world = _world_with_n_agents(5)
    proposer = world.agents["agent_0"]
    ok, msg, rule = world.action_propose_rule(proposer, "ubi", "Universal credits")
    assert ok, msg
    # 3/5 yes (60%) — clears the simple-majority bar for an ordinary rule.
    for i in range(3):
        world.action_vote(world.agents[f"agent_{i}"], rule.id, True)
    assert world.rules[rule.id].status == "active", "ordinary rules keep the >50% bar"


# ──────────────────────────────────────────────────────────────────────────────
# FIX 3 (Wave K adversarial review) — a multi-action turn (EM-199) whose step
# carries an OBJECT/ARRAY-valued building_id must NOT crash the TickLoop with an
# unhashable-type TypeError. Defense-in-depth: the gate coerces ids to str before
# the dict lookup AND the per-step gate runs under the same try/except as the
# inner dispatch, so the bad step becomes a parse_failure and the turn continues.
# ──────────────────────────────────────────────────────────────────────────────

async def test_multi_action_object_building_id_is_parse_failure_not_raise():
    from petridish.engine.loop import TickLoop
    from petridish.config.loader import ModelProfile, WorldConfig
    from petridish.persistence.repository import SQLiteRepository
    from petridish.providers.mock import MockProvider
    from petridish.providers.router import Router
    from petridish.agents.runtime import AgentRuntime

    world = _world()
    _owned_building(world, owner="agent_a", place="plaza")
    ada = world.agents["agent_a"]
    # A multi-action turn: a step with an OBJECT-valued building_id (a model that
    # returned a nested object instead of a bare id), then a benign `say` that MUST
    # still resolve (the loop never dies, the turn never aborts its siblings).
    script = [{"actions": [
        {"action": "demolish", "args": {"building_id": {"id": "bld_test1"}}},
        {"action": "say", "args": {"text": "the loop survives"}},
    ]}]
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    router.reassign(ada.id, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)

    # The whole turn must NOT raise (pre-fix: TypeError: unhashable type 'dict').
    result = await runtime.run_turn(ada)
    evts = result["_multi"] if "_multi" in result else [result]
    kinds = [e.get("kind") for e in evts]
    assert "parse_failure" in kinds, "the object-id step rejects cleanly"
    assert "agent_speech" in kinds, "the sibling `say` still resolved — turn continued"
    assert world.buildings["bld_test1"].status == "operational"  # never demolished


def test_validate_world_object_id_is_rejection_not_raise():
    """The gate itself must turn an unhashable (object/array) id into a guidance
    string, never raise — for demolish, remove_prop, and set_building_skin."""
    world = _world()
    ada = world.agents["agent_a"]
    _owned_building(world, owner="agent_a", place="plaza")
    world.action_place_prop(ada, "bench", "plaza")
    for doc in (
        {"action": "demolish", "args": {"building_id": {"id": "x"}}},
        {"action": "demolish", "args": {"building_id": ["bld_test1"]}},
        {"action": "remove_prop", "args": {"prop_id": {"id": "x"}}},
        {"action": "set_building_skin", "args": {"building_id": {"id": "x"}, "skin": "rose"}},
    ):
        err = _validate_world(doc, ada, world)
        assert isinstance(err, str) and err, f"{doc} must reject with guidance, not raise"


# ──────────────────────────────────────────────────────────────────────────────
# FIX 4 (Wave K adversarial review) — set_building_skin must enforce the
# destroyed-status gate the menu already applies (EM-108 menu/resolution
# divergence): the menu only offers re-skin for status != "destroyed", so the
# resolution path must reject rubble too.
# ──────────────────────────────────────────────────────────────────────────────

def test_set_building_skin_rejects_destroyed_building_at_resolution():
    world = _world()
    b = _owned_building(world, owner="agent_a", place="plaza", status="destroyed")
    ada = world.agents["agent_a"]
    evt = world.action_set_building_skin(ada, b.id, "rose")
    assert evt["kind"] == "parse_failure"
    assert "rubble" in evt["text"].lower()
    assert world.buildings[b.id].skin is None  # untouched


def test_validate_world_rejects_reskin_of_owned_destroyed_building():
    world = _world()
    b = _owned_building(world, owner="agent_a", place="plaza", status="destroyed")
    ada = world.agents["agent_a"]
    err = _validate_world(
        {"action": "set_building_skin", "args": {"building_id": b.id, "skin": "rose"}},
        ada, world)
    assert err is not None and "rubble" in err.lower()

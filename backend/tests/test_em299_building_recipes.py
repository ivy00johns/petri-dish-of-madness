"""EM-299 (Wave Q) — parametric building-recipe grammar (backend).

An agent's `propose_project` gains an OPTIONAL `recipe` object authoring the
building's SHAPE (footprint/floors/roof/material/palette/window_density/trim).

THE LAW (contracts/em299-building-recipes.md §0, mirroring EM-266's posture):
  1. The build ALWAYS succeeds. A bad/missing/garbage recipe never rejects or
     wastes the turn — it degrades (coerce-to-defaults, or drop to a no-recipe
     build), never a dead turn, never a hole.
  2. Byte-identical / additive: `Building.recipe` is serialized ONLY when set;
     with the flag OFF or no recipe authored, behavior is byte-identical to
     pre-EM-299 (snapshot key set + prompt).
  3. Deterministic: the stored recipe is a pure function of the input dict —
     no clock, no randomness (EM-155).
  4. The runtime grammar EQUALS the EM-297 probe grammar (no drift).

The World ctor mirrors test_zone_targeted_build.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import petridish.engine.world as world_mod
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.building_recipe import (
    Recipe, coerce_recipe, normalize_recipe, DEFAULTS, FIELD_NAMES,
    FLOORS_MIN, FLOORS_MAX, Footprint, Roof, Material, Palette, WindowDensity, Trim,
)
from petridish.config.loader import load_config, BuildingRecipesParams


# ── fixtures ──────────────────────────────────────────────────────────────────

def _world() -> World:
    cfg = load_config()
    places = [
        PlaceState(id=p.id, name=p.name, x=p.x, y=p.y,
                   kind=p.kind, description=p.description,
                   district=p.district, neighborhood_id=p.neighborhood_id,
                   zone_kind=p.zone_kind)
        for p in cfg.places
    ]
    agents = [
        AgentState(id=f"agent_{a.name.lower()}", name=a.name,
                   personality=a.personality, profile=a.profile,
                   location=a.location,
                   energy=cfg.world.starting_energy,
                   credits=cfg.world.starting_credits)
        for a in cfg.agents
    ]
    return World(params=cfg.world, places=places, agents=agents)


def _agent(w: World) -> AgentState:
    return next(iter(w.agents.values()))


def _enable(w: World) -> None:
    w.params.building_recipes.enabled = True


def _building(w: World, result: dict):
    return w.buildings[result["_building_id"]]


_GOOD = {
    "footprint": "grand", "floors": 4, "roof": "dome", "material": "marble",
    "palette": "warm", "window_density": "dense", "trim": "gilded",
}


# ── flag ON: a valid recipe is coerced, stored, and serialized ────────────────

def test_valid_recipe_stored_on_building():
    w = _world()
    _enable(w)
    b = _building(w, w.action_propose_project(_agent(w), "Cathedral", "temple", 10,
                                              recipe=dict(_GOOD)))
    assert b.recipe == _GOOD
    assert b.status == "planned"           # the build proceeded
    assert b.to_dict()["recipe"] == _GOOD  # serialized


def test_recipe_value_dict_is_canonical_order():
    w = _world()
    _enable(w)
    # keys emitted in a scrambled order coerce back to canonical FIELD_NAMES order.
    scrambled = {k: _GOOD[k] for k in reversed(list(_GOOD))}
    b = _building(w, w.action_propose_project(_agent(w), "X", "temple", 10,
                                              recipe=scrambled))
    assert list(b.recipe.keys()) == list(FIELD_NAMES)


# ── coercion: bad fields repair to defaults, the build still stands ───────────

def test_garbage_fields_coerce_to_defaults_build_succeeds():
    w = _world()
    _enable(w)
    b = _building(w, w.action_propose_project(
        _agent(w), "Junk", "house", 10,
        recipe={"footprint": "huge", "floors": 99, "roof": "banana", "extra": "x"}))
    # unknown enums → grammar defaults; floors clamped; unknown key dropped.
    assert b.recipe["footprint"] == DEFAULTS["footprint"].value
    assert b.recipe["roof"] == DEFAULTS["roof"].value
    assert b.recipe["floors"] == FLOORS_MAX          # 99 clamped to 8
    assert "extra" not in b.recipe
    assert b.status == "planned"                     # never a dead turn


def test_floors_below_min_clamped():
    w = _world()
    _enable(w)
    b = _building(w, w.action_propose_project(
        _agent(w), "Sub", "house", 10, recipe={**_GOOD, "floors": 0}))
    assert b.recipe["floors"] == FLOORS_MIN


def test_empty_dict_recipe_becomes_all_defaults():
    w = _world()
    _enable(w)
    b = _building(w, w.action_propose_project(_agent(w), "Empty", "house", 10, recipe={}))
    assert b.recipe == {k: DEFAULTS[k].value if hasattr(DEFAULTS[k], "value")
                        else DEFAULTS[k] for k in FIELD_NAMES}


# ── a non-dict recipe drops to a normal no-recipe build (feed-safe) ───────────

def test_non_dict_recipe_drops_to_no_recipe_build():
    w = _world()
    _enable(w)
    for bad in ("a string", ["a", "list"], 42, True):
        b = _building(w, w.action_propose_project(
            _agent(w), f"N{bad!r}", "house", 10, recipe=bad))
        assert b.recipe is None                 # unsalvageable ⇒ dropped
        assert "recipe" not in b.to_dict()      # not serialized
        assert b.status == "planned"            # build still succeeds


def test_missing_recipe_is_a_normal_build():
    w = _world()
    _enable(w)
    b = _building(w, w.action_propose_project(_agent(w), "Plain", "house", 10))
    assert b.recipe is None
    assert "recipe" not in b.to_dict()


# ── flag OFF ⇒ recipe ignored entirely, byte-identical ────────────────────────

def test_flag_off_ignores_recipe_byte_identical():
    # default-OFF: a build passing a (would-be valid) recipe with the flag OFF...
    w1 = _world()
    assert w1.params.building_recipes.enabled is False   # ships dormant
    b1 = _building(w1, w1.action_propose_project(
        _agent(w1), "Alpha", "temple", 10, recipe=dict(_GOOD)))
    assert b1.recipe is None                # ignored entirely
    assert "recipe" not in b1.to_dict()     # not serialized

    # ...serializes byte-identically to the SAME build with NO recipe arg at all.
    w2 = _world()
    b2 = _building(w2, w2.action_propose_project(_agent(w2), "Alpha", "temple", 10))
    d1, d2 = b1.to_dict(), b2.to_dict()
    # the uuid id + seed/id-derived free-placement position vary and are orthogonal.
    for d in (d1, d2):
        d.pop("id"); d.pop("position", None)
    assert d1 == d2


def test_recipe_serialized_only_when_set():
    w = _world()
    _enable(w)
    with_recipe = _building(w, w.action_propose_project(
        _agent(w), "A", "house", 10, recipe=dict(_GOOD)))
    without = _building(w, w.action_propose_project(_agent(w), "B", "house", 10))
    assert with_recipe.to_dict()["recipe"] == _GOOD
    assert "recipe" not in without.to_dict()


# ── the proposed event carries the recipe (+ repairs) only when present ───────

def test_event_payload_carries_recipe_and_repairs():
    w = _world()
    _enable(w)
    r = w.action_propose_project(_agent(w), "Rep", "house", 10,
                                 recipe={"footprint": "huge", "floors": 4})
    proposed = next(e for e in r["_multi"] if e["kind"] == "project_proposed")
    assert proposed["payload"]["recipe"]["footprint"] == DEFAULTS["footprint"].value
    # 'huge' was invalid + several fields missing ⇒ repairs recorded.
    assert proposed["payload"]["recipe_repairs"]


def test_event_payload_no_recipe_when_absent():
    w = _world()
    _enable(w)
    r = w.action_propose_project(_agent(w), "NoRec", "house", 10)
    proposed = next(e for e in r["_multi"] if e["kind"] == "project_proposed")
    assert "recipe" not in proposed["payload"]
    assert "recipe_repairs" not in proposed["payload"]


# ── snapshot / replay / fork round-trip ───────────────────────────────────────

def test_snapshot_round_trip_preserves_recipe():
    w = _world()
    _enable(w)
    agent = _agent(w)
    w.action_propose_project(agent, "Keeper", "temple", 10, recipe=dict(_GOOD))
    w.action_propose_project(agent, "Free", "house", 10)  # no recipe
    snap = w.to_snapshot()

    w2 = World.from_snapshot(snap)
    by_name = {b.name: b for b in w2.buildings.values()}
    assert by_name["Keeper"].recipe == _GOOD
    assert by_name["Free"].recipe is None
    # a fork of the restored world re-serializes identically (buildings block).
    assert w2.to_snapshot()["buildings"] == snap["buildings"]


def test_pre_em299_snapshot_loads_unchanged():
    # A snapshot minted before EM-299: NO building carries a recipe key.
    w = _world()
    w.action_propose_project(_agent(w), "Legacy", "house", 10)
    snap = w.to_snapshot()
    for bd in snap["buildings"]:
        assert "recipe" not in bd
    w2 = World.from_snapshot(snap)
    b = next(b for b in w2.buildings.values() if b.name == "Legacy")
    assert b.recipe is None
    assert "recipe" not in b.to_dict()
    assert w2.to_snapshot()["buildings"] == snap["buildings"]


def test_hand_edited_snapshot_recipe_restores_valid():
    # A snapshot with a garbage recipe dict (hand-edited / older shape) still
    # restores to a VALID canonical recipe — never a hole on load.
    w = _world()
    _enable(w)
    r = w.action_propose_project(_agent(w), "Tamper", "house", 10, recipe=dict(_GOOD))
    snap = w.to_snapshot()
    for bd in snap["buildings"]:
        if bd["name"] == "Tamper":
            bd["recipe"] = {"footprint": "wat", "floors": "x", "junk": 1}
    w2 = World.from_snapshot(snap)
    b = next(b for b in w2.buildings.values() if b.name == "Tamper")
    assert set(b.recipe.keys()) == set(FIELD_NAMES)   # coerced to a valid shape
    assert b.recipe["footprint"] == DEFAULTS["footprint"].value


# ── determinism: a fixed action sequence ⇒ byte-identical buildings ───────────

def _det_uuid():
    import uuid as _uuidlib
    counter = {"n": 0}

    def _f():
        counter["n"] += 1
        return _uuidlib.UUID(int=counter["n"] << 96)

    return _f


def test_determinism_fixed_sequence_byte_identical():
    def _run() -> list:
        world_mod.uuid.uuid4 = _det_uuid()
        w = _world()
        _enable(w)
        agent = _agent(w)
        w.action_propose_project(agent, "A", "temple", 10, recipe=dict(_GOOD))
        w.action_propose_project(agent, "B", "house", 10,
                                 recipe={"footprint": "tiny", "floors": 2})
        w.action_propose_project(agent, "C", "house", 10, recipe="garbage")
        w.action_propose_project(agent, "D", "house", 10)
        return w.to_snapshot()["buildings"]

    original = world_mod.uuid.uuid4
    try:
        a = _run()
        b = _run()
    finally:
        world_mod.uuid.uuid4 = original
    assert a == b
    # sanity: at least one building actually carries a recipe.
    assert any("recipe" in bd for bd in a)


# ── normalize_recipe / coerce_recipe unit behavior ────────────────────────────

def test_normalize_recipe_idempotent():
    v, repairs = normalize_recipe(dict(_GOOD))
    assert repairs == []
    v2, _ = normalize_recipe(v)
    assert v2 == v          # re-normalizing a clean recipe is a no-op


def test_coerce_records_every_repair():
    _, repairs = coerce_recipe({"footprint": "nope"})
    # footprint invalid + 5 missing enum fields + floors missing = several repairs
    assert any("footprint" in r for r in repairs)
    assert any("floors" in r for r in repairs)


def test_strict_recipe_rejects_unknown_keys():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Recipe.model_validate({**_GOOD, "unknown": 1})


# ── config: the flag parses + defaults OFF ────────────────────────────────────

def test_config_flag_default_off():
    cfg = load_config()
    assert isinstance(cfg.world.building_recipes, BuildingRecipesParams)
    assert cfg.world.building_recipes.enabled is False


# ── DRIFT GUARD: the runtime grammar EQUALS the EM-297 probe grammar ──────────

def _load_probe_schema():
    path = (Path(__file__).resolve().parents[1] / "scripts" / "em297_recipe_schema.py")
    spec = importlib.util.spec_from_file_location("em297_recipe_schema", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_engine_schema_matches_probe():
    probe = _load_probe_schema()
    # field set + order
    assert FIELD_NAMES == probe.FIELD_NAMES
    # floors bounds
    assert (FLOORS_MIN, FLOORS_MAX) == (probe.FLOORS_MIN, probe.FLOORS_MAX)
    # enum value sets — identical vocabularies, no drift
    pairs = [
        (Footprint, probe.Footprint), (Roof, probe.Roof), (Material, probe.Material),
        (Palette, probe.Palette), (WindowDensity, probe.WindowDensity), (Trim, probe.Trim),
    ]
    for engine_enum, probe_enum in pairs:
        assert [e.value for e in engine_enum] == [e.value for e in probe_enum]
    # defaults match (compare primitive values)
    engine_defaults = {k: (v.value if hasattr(v, "value") else v) for k, v in DEFAULTS.items()}
    probe_defaults = {k: (v.value if hasattr(v, "value") else v) for k, v in probe.DEFAULTS.items()}
    assert engine_defaults == probe_defaults

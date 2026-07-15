# backend/tests/test_em263_schema.py
"""EM-263 — Religion conflict-surface WIRING (mirrors test_em262_schema).

  * excommunicate / declare_hostility — registered reflexes (no gates), in BOTH
    action enums; excommunicate requires args.target (resolved by name/id but NOT
    co-location gated), declare_hostility requires args.faith_id (a rival faith).
  * menu gating: a faith's FOUNDER is offered excommunicate (with >= 1 living
    non-founder member) + declare_hostility (when another faith exists); a plain
    member, a faithless agent, and every agent in a faith-OFF world see neither.
  * the flag-OFF golden: faith disabled ⇒ NO excommunicate / declare_hostility
    anywhere in the prompt, byte-identical control.
  * validator: excommunicate needs a reachable LIVING target (from afar — no
    co-location), declare_hostility needs a real, DIFFERENT faith id.
  * dispatch: both reflexes route through _apply_action_inner.
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.providers.router import Router
from petridish.agents.runtime import (
    _assemble_context, _validate_world, ACTION_SCHEMA, TOOL_REGISTRY,
    _TARGETED_ACTIONS, AgentRuntime,
)


def _router() -> Router:
    return Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                color="#2ecc71")], cache_enabled=False)


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337)


def _a(aid: str, loc: str = "townhall") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20)


def _world(ids: list[str], faith: bool = True) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="temple_sq", name="Temple Square", x=5, y=5,
                         kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        w.params.faith = {"enabled": True, "conversion_chance": 1.0}
    return w


def _found(w: World, aid: str) -> str:
    return w.action_found_faith(w.agents[aid])["payload"]["faith_id"]


def _enlist(w: World, faith_id: str, member: str) -> None:
    """Make `member` a plain (non-founder) member of `faith_id` for menu tests."""
    w.agents[member].faith_id = faith_id
    faith = w.faiths[faith_id]
    if member not in faith.members:
        faith.members.append(member)


def _sys_of(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── registration + enums ──────────────────────────────────────────────────────

def test_verbs_registered_reflex_no_gates():
    for v in ("excommunicate", "declare_hostility"):
        meta = TOOL_REGISTRY[v]
        assert meta["tier"] == "reflex"
        assert meta["location_gate"] is None
        assert meta["agreement_gate"] is None


def test_verbs_in_both_action_enums():
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    item_enum = (ACTION_SCHEMA["properties"]["actions"]["items"]
                 ["properties"]["action"]["enum"])
    for v in ("excommunicate", "declare_hostility"):
        assert v in enum and v in item_enum


def test_excommunicate_requires_target_in_allof():
    clause = next(
        c for c in ACTION_SCHEMA["allOf"]
        if c["if"]["properties"]["action"]["const"] == "excommunicate")
    assert clause["then"]["properties"]["args"]["required"] == ["target"]


def test_declare_hostility_requires_faith_id_in_allof():
    clause = next(
        c for c in ACTION_SCHEMA["allOf"]
        if c["if"]["properties"]["action"]["const"] == "declare_hostility")
    assert clause["then"]["properties"]["args"]["required"] == ["faith_id"]


def test_excommunicate_is_targeted_declare_hostility_is_not():
    # excommunicate resolves an agent name→id (like proselytize) …
    assert "excommunicate" in _TARGETED_ACTIONS
    # … declare_hostility carries a faith_id, not an agent (EXCLUDED).
    assert "declare_hostility" not in _TARGETED_ACTIONS


# ── menu gating ───────────────────────────────────────────────────────────────

def test_excommunicate_offered_to_founder_with_a_member():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    _enlist(w, fid, "bram")
    sys = _sys_of(w.agents["ada"], w)
    assert "excommunicate" in sys
    assert "Bram" in sys                                 # the named castable member


def test_excommunicate_hidden_from_founder_with_no_member():
    w = _world(["ada", "bram"])
    _found(w, "ada")                                     # a lone founder, no flock
    assert "excommunicate" not in _sys_of(w.agents["ada"], w)


def test_excommunicate_hidden_from_a_plain_member():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    _enlist(w, fid, "bram")
    # bram is a member but NOT the founder → he may not excommunicate.
    assert "excommunicate" not in _sys_of(w.agents["bram"], w)


def test_declare_hostility_offered_to_founder_when_a_rival_faith_exists():
    w = _world(["ada", "bram"])
    _found(w, "ada")
    bram_fid = _found(w, "bram")                          # a second, rival faith
    sys = _sys_of(w.agents["ada"], w)
    assert "declare_hostility" in sys
    assert bram_fid in sys                                # named by id so it resolves


def test_declare_hostility_hidden_when_no_rival_faith():
    w = _world(["ada", "bram"])
    _found(w, "ada")                                     # the only faith in town
    assert "declare_hostility" not in _sys_of(w.agents["ada"], w)


# ── flag-OFF golden ───────────────────────────────────────────────────────────

def test_faith_off_menu_never_names_the_verbs():
    w = _world(["ada", "bram"], faith=False)
    sys = _sys_of(w.agents["ada"], w)
    assert "excommunicate" not in sys and "declare_hostility" not in sys


def test_faith_off_prompt_is_byte_identical_control():
    a = _sys_of(_world(["ada", "bram"], faith=False).agents["ada"],
                _world(["ada", "bram"], faith=False))
    b = _sys_of(_world(["ada", "bram"], faith=False).agents["ada"],
                _world(["ada", "bram"], faith=False))
    assert a == b


# ── validator ─────────────────────────────────────────────────────────────────

def test_excommunicate_validator_accepts_a_living_target_from_afar():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    _enlist(w, fid, "bram")
    w.agents["bram"].location = "temple_sq"              # NOT co-located with ada
    # a living target passes even though bram is elsewhere (no co-location gate)…
    assert _validate_world(
        {"action": "excommunicate", "args": {"target": "bram"}},
        w.agents["ada"], w) is None
    # …an unknown target is rejected with guidance.
    err = _validate_world(
        {"action": "excommunicate", "args": {"target": "ghost"}},
        w.agents["ada"], w)
    assert err is not None and "unknown target" in err


def test_declare_hostility_validator_requires_a_real_rival_faith():
    w = _world(["ada", "bram"])
    _found(w, "ada")
    bram_fid = _found(w, "bram")
    # a real, different faith passes…
    assert _validate_world(
        {"action": "declare_hostility", "args": {"faith_id": bram_fid}},
        w.agents["ada"], w) is None
    # …an unknown faith is rejected.
    err = _validate_world(
        {"action": "declare_hostility", "args": {"faith_id": "fth_ghost"}},
        w.agents["ada"], w)
    assert err is not None and "unknown faith" in err
    # …the actor's OWN faith is rejected (no self-hostility).
    own = _validate_world(
        {"action": "declare_hostility", "args": {"faith_id": w.agents["ada"].faith_id}},
        w.agents["ada"], w)
    assert own is not None and "own faith" in own


# ── dispatch ──────────────────────────────────────────────────────────────────

def test_dispatch_routes_excommunicate_and_declare_hostility():
    w = _world(["ada", "bram", "cyn"])
    fid = _found(w, "ada")                                # ada founds faith A
    _enlist(w, fid, "bram")                              # bram is a member of A
    cyn_fid = _found(w, "cyn")                            # cyn founds a rival faith
    rt = AgentRuntime(w, _router())
    # excommunicate → routes to action_excommunicate (bram leaves faith A).
    evt = rt._apply_action_inner(
        w.agents["ada"], {"action": "excommunicate", "args": {"target": "bram"}},
        "P", "#fff")
    assert evt["kind"] == "excommunicated"
    assert w.agents["bram"].faith_id is None
    assert "bram" not in w.faiths[fid].members
    # declare_hostility → routes to action_declare_hostility (A turns on cyn's faith).
    evt2 = rt._apply_action_inner(
        w.agents["ada"], {"action": "declare_hostility",
                          "args": {"faith_id": cyn_fid}},
        "P", "#fff")
    assert evt2["kind"] == "faith_hostility_declared"
    assert cyn_fid in w.faiths[fid].hostile_to

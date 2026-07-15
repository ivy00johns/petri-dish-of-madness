# backend/tests/test_em261_schema.py
"""EM-261 — Religion founding/consecration WIRING (mirrors test_em253_schema +
test_em254_governance's menu-golden coverage).

  * found_faith — registered reflex (no gates), in BOTH action enums, offered in
    the menu ONLY when faith_enabled AND the agent is faithless.
  * consecrate_faith — surfaces on the propose_rule line ONLY when faith_enabled
    (FAITH-gated, NOT comm-gated) and an unconsecrated faith exists; rejected at
    the runtime gate as an invalid effect when faith is off.
  * the flag-OFF golden: faith disabled ⇒ NO found_faith / consecrate_faith
    anywhere in the prompt, byte-identical control.
  * FaithParams.devotion_base — the EM-261 config addition (founder's starting
    devotion), defaults + defensive parse.
"""
from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, FaithParams, _parse_faith, ModelProfile
from petridish.providers.router import Router
from petridish.agents.runtime import (
    _assemble_context, _validate_world, ACTION_SCHEMA, TOOL_REGISTRY, AgentRuntime,
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


def _world(ids: list[str], faith: bool = True, comm: bool = False) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="temple_sq", name="Temple Square", x=5, y=5,
                         kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        w.params.faith = {"enabled": True}
    if comm:
        w.params.comm = {"enabled": True}
    return w


def _sys_of(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _propose_line(sys_text: str) -> str:
    return next((l for l in sys_text.split("\n")
                 if l.strip().startswith("propose_rule")), "")


# ── found_faith registration + enums ──────────────────────────────────────────

def test_found_faith_registered_reflex_no_gates():
    meta = TOOL_REGISTRY["found_faith"]
    assert meta["tier"] == "reflex"
    assert meta["location_gate"] is None
    assert meta["agreement_gate"] is None


def test_found_faith_in_both_action_enums():
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    item_enum = (ACTION_SCHEMA["properties"]["actions"]["items"]
                 ["properties"]["action"]["enum"])
    assert "found_faith" in enum
    assert "found_faith" in item_enum


# ── found_faith menu gating ───────────────────────────────────────────────────

def test_found_faith_offered_when_enabled_and_faithless():
    w = _world(["ada", "bram"])
    assert "found_faith" in _sys_of(w.agents["ada"], w)


def test_found_faith_hidden_once_agent_is_faithful():
    w = _world(["ada", "bram"])
    w.action_found_faith(w.agents["ada"])              # ada now has a faith
    assert "found_faith" not in _sys_of(w.agents["ada"], w)
    # a still-faithless citizen keeps the offer.
    assert "found_faith" in _sys_of(w.agents["bram"], w)


def test_found_faith_absent_when_faith_disabled():
    w = _world(["ada", "bram"], faith=False)
    assert "found_faith" not in _sys_of(w.agents["ada"], w)


# ── consecrate_faith propose-line gating (faith-gated, not comm-gated) ─────────

def test_consecrate_in_propose_line_when_faith_on_with_a_faith():
    w = _world(["ada", "bram", "cyn"])
    w.action_found_faith(w.agents["ada"])              # an unconsecrated faith
    line = _propose_line(_sys_of(w.agents["ada"], w))
    assert "|consecrate_faith" in line


def test_consecrate_not_in_propose_line_when_faith_off():
    w = _world(["ada", "bram", "cyn"], faith=False)
    line = _propose_line(_sys_of(w.agents["ada"], w))
    assert line                                        # governance place ⇒ a line
    assert "consecrate_faith" not in line


def test_consecrate_surfaces_with_comm_off_proving_faith_gate():
    """comm OFF, faith ON ⇒ consecrate_faith still surfaces — it rides the FAITH
    gate, not the culture (comm) gate."""
    w = _world(["ada", "bram", "cyn"], faith=True, comm=False)
    w.action_found_faith(w.agents["ada"])
    line = _propose_line(_sys_of(w.agents["ada"], w))
    assert "|consecrate_faith" in line
    assert "canonize_meme" not in line                 # culture stays comm-gated


def test_consecrate_invalid_proposal_at_runtime_gate_when_faith_off():
    w = _world(["ada", "bram", "cyn"], faith=False)
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "consecrate_faith", "text": "t",
                  "faith_id": "fth_x"}},
        w.agents["ada"], w)
    assert err is not None and "invalid effect" in err
    assert "consecrate_faith" not in err.split("Valid:")[1]


def test_consecrate_validator_agrees_with_real_faith_when_faith_on():
    w = _world(["ada", "bram", "cyn"])
    evt = w.action_found_faith(w.agents["ada"])
    fid = evt["payload"]["faith_id"]
    # a real faith on the generic target passes the runtime gate…
    assert _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "consecrate_faith", "text": "t", "faith_id": fid}},
        w.agents["ada"], w) is None
    # …an unknown faith is rejected with guidance.
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "consecrate_faith", "text": "t",
                  "faith_id": "fth_ghost"}},
        w.agents["ada"], w)
    assert err is not None and "real faith" in err


# ── flag-OFF golden: no religion trace, byte-identical control ────────────────

def test_faith_off_menu_never_names_religion():
    w = _world(["ada", "bram", "cyn"], faith=False)
    sys = _sys_of(w.agents["ada"], w)
    assert "found_faith" not in sys
    assert "consecrate_faith" not in sys


def test_faith_off_prompt_is_byte_identical_control():
    a = _sys_of(_world(["ada", "bram", "cyn"], faith=False).agents["ada"],
                _world(["ada", "bram", "cyn"], faith=False))
    b = _sys_of(_world(["ada", "bram", "cyn"], faith=False).agents["ada"],
                _world(["ada", "bram", "cyn"], faith=False))
    assert a == b


# ── FaithParams.devotion_base (the EM-261 config addition) ────────────────────

def test_faith_params_devotion_base_default_and_parse():
    p = FaithParams()
    assert p.devotion_base == 10                        # EM-261 default (> 0)
    # unchanged EM-260 defaults still hold.
    assert p.enabled is False and p.temple_buff == 5
    assert _parse_faith(None) == FaithParams()          # absent block
    assert _parse_faith({}) == FaithParams()
    assert _parse_faith({"enabled": True, "devotion_base": 25}) == FaithParams(
        enabled=True, devotion_base=25)
    # a malformed value falls back to the default (the block never breaks).
    assert _parse_faith({"devotion_base": "junk"}).devotion_base == 10


def test_devotion_base_drives_the_founder_start():
    w = _world(["ada"])
    w.params.faith = {"enabled": True, "devotion_base": 30}
    w.action_found_faith(w.agents["ada"])
    assert w.agents["ada"].devotion == 30


# ── dispatch: the reflex verb routes through _apply_action_inner ──────────────

def test_dispatch_routes_found_faith():
    """_apply_action_inner routes 'found_faith' → world.action_found_faith
    (the create_meme/found_settlement dispatch recipe)."""
    w = _world(["ada"])
    rt = AgentRuntime(w, _router())
    evt = rt._apply_action_inner(
        w.agents["ada"], {"action": "found_faith", "args": {}}, "P", "#fff")
    assert evt["kind"] == "faith_founded"
    assert w.agents["ada"].faith_id == evt["payload"]["faith_id"]

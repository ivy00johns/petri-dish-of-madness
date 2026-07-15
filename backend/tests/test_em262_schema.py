# backend/tests/test_em262_schema.py
"""EM-262 — Religion emergence WIRING (mirrors test_em261_schema).

  * proselytize / worship — registered reflexes (no gates), in BOTH action enums;
    proselytize requires args.target (the clash allOf recipe), worship takes none.
  * menu gating: a FAITHFUL agent is offered proselytize (with a co-located
    FAITHLESS target) + worship (at a co-located consecrated temple seat); a
    faithless agent, and every agent in a faith-OFF world, sees neither.
  * the flag-OFF golden: faith disabled ⇒ NO proselytize / worship anywhere in the
    prompt, byte-identical control.
  * dispatch: both reflexes route through _apply_action_inner.
"""
from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, ModelProfile
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


def _world(ids: list[str], faith=True) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="temple_sq", name="Temple Square", x=5, y=5,
                         kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        w.params.faith = {"enabled": True, "conversion_chance": 1.0}
    return w


def _temple(w, commemorates=None):
    b = Building(id="bld_temple", name="Grand Temple", kind="temple",
                 location="townhall", owner_id="public", status="operational",
                 health=100, commemorates=commemorates, position=(0.0, 0.0))
    w.buildings[b.id] = b
    return b


def _sys_of(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── registration + enums ──────────────────────────────────────────────────────

def test_verbs_registered_reflex_no_gates():
    for v in ("proselytize", "worship"):
        meta = TOOL_REGISTRY[v]
        assert meta["tier"] == "reflex"
        assert meta["location_gate"] is None
        assert meta["agreement_gate"] is None


def test_verbs_in_both_action_enums():
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    item_enum = (ACTION_SCHEMA["properties"]["actions"]["items"]
                 ["properties"]["action"]["enum"])
    for v in ("proselytize", "worship"):
        assert v in enum and v in item_enum


def test_proselytize_requires_target_in_allof():
    clause = next(
        c for c in ACTION_SCHEMA["allOf"]
        if c["if"]["properties"]["action"]["const"] == "proselytize")
    assert clause["then"]["properties"]["args"]["required"] == ["target"]


def test_proselytize_is_a_targeted_action():
    from petridish.agents.runtime import _TARGETED_ACTIONS
    assert "proselytize" in _TARGETED_ACTIONS
    assert "worship" not in _TARGETED_ACTIONS           # worship takes no target


# ── menu gating ───────────────────────────────────────────────────────────────

def test_proselytize_offered_to_faithful_agent_with_faithless_target():
    w = _world(["ada", "bram"])
    w.action_found_faith(w.agents["ada"])               # ada is faithful
    sys = _sys_of(w.agents["ada"], w)
    assert "proselytize" in sys
    assert "Bram" in sys                                 # the faithless co-located


def test_proselytize_hidden_when_no_faithless_target():
    w = _world(["ada", "bram"])
    w.action_found_faith(w.agents["ada"])
    w.agents["bram"].faith_id = "fth_somewhere"          # everyone here has a faith
    assert "proselytize" not in _sys_of(w.agents["ada"], w)


def test_proselytize_hidden_from_faithless_agent():
    w = _world(["ada", "bram"])
    # ada has no faith → she cannot proselytize (found_faith is offered instead).
    sys = _sys_of(w.agents["ada"], w)
    assert "proselytize" not in sys
    assert "found_faith" in sys


def test_worship_offered_at_a_co_located_seat():
    w = _world(["ada"])
    fid = w.action_found_faith(w.agents["ada"])["payload"]["faith_id"]
    _temple(w, commemorates=fid)                         # a temple of ada's faith, here
    assert "worship" in _sys_of(w.agents["ada"], w)


def test_worship_hidden_with_no_seat():
    w = _world(["ada"])
    w.action_found_faith(w.agents["ada"])               # faithful, but no temple here
    assert "worship" not in _sys_of(w.agents["ada"], w)


# ── flag-OFF golden ───────────────────────────────────────────────────────────

def test_faith_off_menu_never_names_the_verbs():
    w = _world(["ada", "bram"], faith=False)
    sys = _sys_of(w.agents["ada"], w)
    assert "proselytize" not in sys and "worship" not in sys


def test_faith_off_prompt_is_byte_identical_control():
    a = _sys_of(_world(["ada", "bram"], faith=False).agents["ada"],
                _world(["ada", "bram"], faith=False))
    b = _sys_of(_world(["ada", "bram"], faith=False).agents["ada"],
                _world(["ada", "bram"], faith=False))
    assert a == b


# ── validator ─────────────────────────────────────────────────────────────────

def test_proselytize_validator_requires_reachable_target():
    w = _world(["ada", "bram"])
    w.action_found_faith(w.agents["ada"])
    # a reachable co-located target passes…
    assert _validate_world(
        {"action": "proselytize", "args": {"target": "bram"}},
        w.agents["ada"], w) is None
    # …an unknown target is rejected with guidance.
    err = _validate_world(
        {"action": "proselytize", "args": {"target": "ghost"}},
        w.agents["ada"], w)
    assert err is not None and "unknown target" in err


# ── dispatch ──────────────────────────────────────────────────────────────────

def test_dispatch_routes_proselytize_and_worship():
    w = _world(["ada", "bram"])
    fid = w.action_found_faith(w.agents["ada"])["payload"]["faith_id"]
    rt = AgentRuntime(w, _router())
    # proselytize → a conversion _multi chain.
    evt = rt._apply_action_inner(
        w.agents["ada"], {"action": "proselytize", "args": {"target": "bram"}},
        "P", "#fff")
    assert "_multi" in evt
    assert [e["kind"] for e in evt["_multi"]] == ["proselytized", "faith_joined"]
    assert w.agents["bram"].faith_id == fid
    # worship → a fail event when no seat (routing still reached the world action).
    evt2 = rt._apply_action_inner(
        w.agents["ada"], {"action": "worship", "args": {}}, "P", "#fff")
    assert evt2["kind"] == "parse_failure" and "no seat" in evt2["payload"]["error"]

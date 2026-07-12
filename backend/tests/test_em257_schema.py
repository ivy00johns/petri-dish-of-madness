# backend/tests/test_em257_schema.py
"""EM-257 — prompt-menu + runtime-validator surface (mirrors
test_em240_schema/test_em280: the EM-108 menu/resolution-agreement rule).

The war lane surfaces ONLY when relevant: declare_war only when the agent's
faction holds a live casus belli, peace_treaty only when its faction is at
war. War disabled (the default), a factionless agent, or a quiet grievance
ledger ⇒ the ENTIRE system prompt is byte-identical to a war-free world (the
em161-golden guarantee) — peacetime carries no trace of the lane. The
validator gates exactly the same way, so the menu never dangles an effect
the gate would reject.
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context, _validate_world

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=20)


def _world(war: bool = True) -> tuple[AgentState, World]:
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if war:
        w.params.war = {"enabled": True}
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram", "cyn"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    return w.agents["ada"], w


def _sys(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _propose_line(sys: str) -> str:
    return next(l for l in sys.split("\n") if l.strip().startswith("propose_rule"))


# ── peacetime golden: byte-identical prompt ───────────────────────────────────

def test_war_disabled_prompt_is_byte_identical_to_war_enabled_peacetime():
    """The scope's pinned guarantee: enabling war WITHOUT a casus belli or an
    active war changes NOTHING — the full system prompt (menu included) is
    byte-identical, so the em161 golden and every live peacetime world are
    unaffected by the lane merely existing."""
    agent_off, w_off = _world(war=False)
    agent_on, w_on = _world(war=True)          # enabled but QUIET — peacetime
    assert _sys(agent_off, w_off) == _sys(agent_on, w_on)


def test_peacetime_menu_never_names_the_war_effects():
    agent, w = _world(war=True)
    line = _propose_line(_sys(agent, w))
    assert "declare_war" not in line
    assert "peace_treaty" not in line


# ── the lane surfaces only when relevant ──────────────────────────────────────

def test_declare_war_surfaces_past_the_casus_belli_threshold():
    agent, w = _world()
    w.grievances[f"{FA}->{FB}"] = 49           # below 50 → still peacetime
    assert "declare_war" not in _propose_line(_sys(agent, w))
    w.grievances[f"{FA}->{FB}"] = 60
    line = _propose_line(_sys(agent, w))
    assert "|declare_war" in line
    assert f"e.g. {FB} (Dot's circle, grievance 60)" in line
    assert "70% vote" in line
    # …but never for a factionless agent, and never for the wrong direction.
    assert "declare_war" not in _propose_line(_sys(w.agents["fay"], w))
    assert "declare_war" not in _propose_line(_sys(w.agents["dot"], w))


def test_peace_treaty_surfaces_only_for_belligerents():
    agent, w = _world()
    war = w.open_war(FA, FB, "x")
    line = _propose_line(_sys(agent, w))
    assert "|peace_treaty" in line and war.id in line
    assert "peace_treaty" not in _propose_line(_sys(w.agents["fay"], w))
    war.status = "settled"
    assert "peace_treaty" not in _propose_line(_sys(agent, w))


# ── validator: gates agree with the menu and the world ────────────────────────

def _gate(agent, world, effect, **args):
    return _validate_world(
        {"action": "propose_rule",
         "args": {"effect": effect, "text": "t", **args}},
        agent, world)


def test_validator_rejects_the_lane_when_war_disabled():
    agent, w = _world(war=False)
    w.grievances[f"{FA}->{FB}"] = 60
    err = _gate(agent, w, "declare_war", target=FB)
    assert err is not None and "invalid effect" in err
    assert "declare_war" not in err.split("Valid:")[1]   # not listed as valid
    err = _gate(agent, w, "peace_treaty", war_id="war_x")
    assert err is not None and "invalid effect" in err


def test_validator_mirrors_the_declare_war_gates():
    agent, w = _world()
    # No casus belli yet → rejected with guidance.
    err = _gate(agent, w, "declare_war", target=FB)
    assert err is not None and "casus belli" in err
    w.grievances[f"{FA}->{FB}"] = 60
    # Factionless proposer → rejected.
    err = _gate(w.agents["fay"], w, "declare_war", target=FB)
    assert err is not None and "belong to a faction" in err
    # A real casus-belli target passes — by id AND by name (Task 12a: agents
    # see names, not ids).
    assert _gate(agent, w, "declare_war", target=FB) is None
    assert _gate(agent, w, "declare_war", target="Dot's Circle") is None
    # An unknown faction / the wrong direction is rejected.
    assert _gate(agent, w, "declare_war", target="fct_ghost000") is not None
    assert _gate(w.agents["dot"], w, "declare_war", target=FA) is not None


def test_validator_mirrors_the_peace_treaty_gates():
    agent, w = _world()
    err = _gate(agent, w, "peace_treaty", war_id="war_ghost123")
    assert err is not None and "active war" in err
    war = w.open_war(FA, FB, "x")
    assert _gate(agent, w, "peace_treaty", war_id=war.id) is None
    assert _gate(agent, w, "peace_treaty", target=war.id) is None   # generic arg
    assert _gate(w.agents["fay"], w, "peace_treaty", war_id=war.id) is not None
    assert _gate(agent, w, "peace_treaty", war_id=war.id,
                 reparations=-1) is not None
    assert _gate(agent, w, "peace_treaty", war_id=war.id,
                 reparations="lots") is not None
    assert _gate(agent, w, "peace_treaty", war_id=war.id,
                 reparations=40) is None

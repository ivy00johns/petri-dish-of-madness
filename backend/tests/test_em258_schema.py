# backend/tests/test_em258_schema.py
"""EM-258/EM-259 — the war-verb prompt/validator surface (the EM-108
menu/resolution-agreement rule, mirroring test_em257_schema).

The war menu (muster / clash / siege lines) surfaces ONLY while the agent's
faction is actually AT WAR: war disabled, a factionless agent, or a quiet
world adds NO line — the FULL system prompt stays byte-identical (the
em161-golden guarantee; the static ACTION_SCHEMA/TOOL_REGISTRY entries are
identical on both sides so they cancel). The jail-gate widens to `exiled`
and explicitly NOT to `belligerent` (a marker, not a restriction — plan
§Feature 3), and `belligerent` round-trips the snapshot whitelist.
"""
from petridish.engine.world import World, AgentState, PlaceState, Building
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


def _world(war: bool = True) -> World:
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
    return w


def _sys(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── peacetime golden: the war verbs leave no trace ────────────────────────────

def test_peacetime_prompt_is_byte_identical_with_the_verbs_shipped():
    """The stage-C re-pin of the EM-257 guarantee, now with muster/clash/
    siege in the codebase: a war-enabled-but-quiet world's FULL prompt is
    byte-identical to a war-disabled one — the combat verbs surface nowhere
    in peacetime."""
    w_off, w_on = _world(war=False), _world(war=True)
    assert _sys(w_off.agents["ada"], w_off) == _sys(w_on.agents["ada"], w_on)


def test_peacetime_menu_never_names_the_war_verbs():
    w = _world()
    sys = _sys(w.agents["ada"], w)
    for verb in ("muster", "clash", "siege"):
        assert f"{verb} " not in sys and f"{verb}(" not in sys


# ── the war menu surfaces only when relevant ─────────────────────────────────

def _menu_lines(agent, world) -> list[str]:
    return [l.strip() for l in _sys(agent, world).split("\n")
            if l.strip().startswith(("muster", "clash", "siege"))]


def test_muster_surfaces_only_for_unbanded_belligerents():
    w = _world()
    w.open_war(FA, FB, "x")
    lines = _menu_lines(w.agents["ada"], w)
    assert len(lines) == 1 and lines[0].startswith("muster")
    assert "Dot's circle" in lines[0]                    # names the enemy
    # A factionless bystander sees nothing.
    assert _menu_lines(w.agents["fay"], w) == []
    # Once banded, muster drops and clash surfaces (a foe stands here).
    w.factions[FA]["war_band"] = ["ada"]
    lines = _menu_lines(w.agents["ada"], w)
    assert not any(l.startswith("muster") for l in lines)
    assert any(l.startswith("clash") for l in lines)


def test_clash_line_names_only_co_located_enemies():
    w = _world()
    w.open_war(FA, FB, "x")
    w.factions[FA]["war_band"] = ["ada"]
    clash = next(l for l in _menu_lines(w.agents["ada"], w)
                 if l.startswith("clash"))
    assert "Dot" in clash and "Eli" in clash
    assert "Bram" not in clash and "Fay" not in clash    # never friend/bystander
    # Enemies elsewhere ⇒ no clash line at all.
    w.agents["dot"].location = "nowhere"
    w.agents["eli"].location = "nowhere"
    assert not any(l.startswith("clash")
                   for l in _menu_lines(w.agents["ada"], w))


def test_clash_line_respects_clash_requires_band_off():
    w = _world()
    w.params.war = {"enabled": True, "clash_requires_band": False}
    w.open_war(FA, FB, "x")
    lines = _menu_lines(w.agents["ada"], w)              # unbanded, gate off
    assert any(l.startswith("clash") for l in lines)


def test_siege_line_names_only_enemy_structures_here():
    w = _world()
    w.open_war(FA, FB, "x")
    w.factions[FA]["war_band"] = ["ada"]
    w.buildings["bld_keep"] = Building(
        id="bld_keep", name="Dot's Keep", kind="generic", location="townhall",
        owner_id="dot", status="operational", health=100)
    w.buildings["bld_home"] = Building(
        id="bld_home", name="Bram's Hut", kind="generic", location="townhall",
        owner_id="bram", status="operational", health=100)
    lines = _menu_lines(w.agents["ada"], w)
    sieges = [l for l in lines if l.startswith("siege")]
    assert len(sieges) == 1 and "bld_keep" in sieges[0]
    assert "Dot's Keep" in sieges[0]
    # A destroyed enemy structure drops off the menu.
    w.buildings["bld_keep"].status = "destroyed"
    assert not any(l.startswith("siege")
                   for l in _menu_lines(w.agents["ada"], w))


# ── the jail-gate widening ────────────────────────────────────────────────────

def test_belligerent_does_not_restrict_actions():
    w = _world()
    ada = w.agents["ada"]
    ada.crime_status = "belligerent"
    assert _validate_world({"action": "forage", "args": {}}, ada, w) is None
    assert _validate_world(
        {"action": "move_to", "args": {"place": "townhall"}},
        ada, w) is None


def test_exiled_restricts_like_jail_but_permanently():
    w = _world()
    ada = w.agents["ada"]
    ada.crime_status = "exiled"
    err = _validate_world({"action": "forage", "args": {}}, ada, w)
    assert err is not None and "exiled" in err
    # The talk-and-think channel stays open (the jail whitelist).
    for action_dict in (
        {"action": "say", "args": {"text": "hello"}},
        {"action": "whisper", "args": {"target": "bram", "text": "psst"}},
        {"action": "idle", "args": {}},
        {"action": "remember", "args": {"fact": "the war is lost"}},
    ):
        assert _validate_world(action_dict, ada, w) is None
    # advance_crime's release path never frees exiled (EM-257 pinned it for
    # snapshots; re-pinned here beside the gate it now powers).
    ada.crime_status_until_tick = 0
    w.advance_crime()
    assert ada.crime_status == "exiled"


def test_detained_and_jailed_still_restrict():
    w = _world()
    ada = w.agents["ada"]
    for status in ("detained", "jailed"):
        ada.crime_status = status
        err = _validate_world({"action": "forage", "args": {}}, ada, w)
        assert err is not None and "jailed" in err


def test_clash_front_gate_requires_a_reachable_target():
    w = _world()
    ada = w.agents["ada"]
    err = _validate_world({"action": "clash", "args": {}}, ada, w)
    assert err is not None and "requires target" in err
    err = _validate_world({"action": "clash", "args": {"target": "ghost"}},
                          ada, w)
    assert err is not None and "unknown target" in err
    # A reachable target passes the FRONT gate — the world action owns the
    # at-war/mustered checks (menu/resolution agreement).
    assert _validate_world({"action": "clash", "args": {"target": "dot"}},
                           ada, w) is None


# ── the belligerent snapshot whitelist ────────────────────────────────────────

def test_belligerent_round_trips_the_snapshot():
    w = _world()
    w.agents["ada"].crime_status = "belligerent"
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    assert restored.agents["ada"].crime_status == "belligerent"


def test_unknown_crime_status_still_fails_safe():
    w = _world()
    snap = w.to_snapshot()
    for a in snap["agents"]:
        if a["id"] == "ada":
            a["crime_status"] = "warlord"                # not a real status
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["ada"].crime_status is None

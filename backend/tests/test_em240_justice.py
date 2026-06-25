"""EM-240 Task 10 — enforcer verbs (investigate/accuse/detain), the jail place,
the jail-restriction gate, and the enforcer role-gate (validator + menu)."""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _validate_world, _assemble_context


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="jail", name="Jail", x=9, y=9, kind="civic"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


# ── action_investigate ────────────────────────────────────────────────────────

def test_investigate_confirms_unwitnessed_crimes_when_a_witness_is_present():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.rap_sheet = [
        {"tick": 0, "crime": "steal", "victim_id": "x", "witnessed": False}]
    witness = _a("witness", "plaza")
    world = _world([cop, crook, witness])
    ok, reason, n = world.action_investigate(cop, crook)
    assert ok and n == 1
    assert crook.rap_sheet[0]["witnessed"] is True
    assert crook.notoriety == 10             # investigate_notoriety


def test_investigate_needs_a_witness():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.rap_sheet = [
        {"tick": 0, "crime": "steal", "victim_id": "x", "witnessed": False}]
    world = _world([cop, crook])
    ok, reason, n = world.action_investigate(cop, crook)
    assert not ok and n == 0


# ── action_detain ─────────────────────────────────────────────────────────────

def test_detain_jails_a_wanted_suspect():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.crime_status = "wanted"; crook.notoriety = 45
    world = _world([cop, crook]); world.tick = 3
    evt = world.action_detain(cop, crook)
    assert isinstance(evt, dict) and evt["kind"] == "detained"
    assert crook.crime_status == "detained"
    assert crook.location == "jail"
    assert crook.crime_status_until_tick == 3 + 6   # detain_sentence


def test_detain_rejected_without_grounds():
    cop = _a("cop", "plaza", role="enforcer")
    citizen = _a("cit", "plaza")                     # clean
    world = _world([cop, citizen])
    res = world.action_detain(cop, citizen)
    assert res == (False, "insufficient grounds to detain", None)


# ── action_accuse ─────────────────────────────────────────────────────────────

def test_accuse_emits_an_accusation_event():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.notoriety = 22
    world = _world([cop, crook])
    evt = world.action_accuse(cop, crook)
    assert isinstance(evt, dict) and evt["kind"] == "accusation"
    assert evt["actor_id"] == "cop" and evt["target_id"] == "crook"
    assert evt["payload"]["notoriety"] == 22


def test_accuse_needs_co_location():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "jail")
    world = _world([cop, crook])
    evt = world.action_accuse(cop, crook)
    assert evt["kind"] == "parse_failure"


# ── _jail_place_id ────────────────────────────────────────────────────────────

def test_jail_place_id_prefers_the_jail_id():
    world = _world([_a("cop", "plaza", role="enforcer")])
    assert world._jail_place_id() == "jail"


def test_jail_place_id_falls_back_to_first_civic_then_none():
    # No 'jail' id, but a civic place exists → that civic place is the jail.
    civic_only = World(params=_params(), places=[
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="lockup", name="Cell", x=1, y=1, kind="civic"),
    ], agents=[])
    assert civic_only._jail_place_id() == "lockup"
    # No civic place at all → None (a town with no jail cannot detain).
    no_jail = World(params=_params(), places=[
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
    ], agents=[])
    assert no_jail._jail_place_id() is None


# ── validator: enforcer gate ──────────────────────────────────────────────────

def test_validator_gates_justice_verbs_to_enforcers():
    citizen = _a("cit", "plaza")
    crook = _a("crook", "plaza"); crook.crime_status = "wanted"
    world = _world([citizen, crook])
    err = _validate_world({"action": "detain", "args": {"target": "Crook"}},
                          citizen, world)
    assert err and "enforcer" in err.lower()


def test_validator_allows_justice_verbs_for_enforcers():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.crime_status = "wanted"
    world = _world([cop, crook])
    err = _validate_world({"action": "detain", "args": {"target": "crook"}},
                          cop, world)
    assert err is None


# ── validator: jail restriction ───────────────────────────────────────────────

def test_validator_blocks_actions_while_jailed():
    con = _a("con", "jail"); con.crime_status = "jailed"; con.crime_status_until_tick = 99
    world = _world([con]); world.tick = 1
    assert _validate_world({"action": "move_to", "args": {"place": "plaza"}},
                           con, world)  # blocked
    assert _validate_world({"action": "steal", "args": {"target": "x"}},
                           con, world)  # blocked
    assert _validate_world({"action": "say", "args": {"text": "let me out"}},
                           con, world) is None  # talk allowed


def test_validator_blocks_actions_while_detained():
    con = _a("con", "jail"); con.crime_status = "detained"; con.crime_status_until_tick = 99
    cellmate = _a("cellmate", "jail")          # co-located so whisper has a target
    world = _world([con, cellmate]); world.tick = 1
    assert _validate_world({"action": "forage", "args": {}}, con, world)  # blocked
    assert _validate_world(
        {"action": "whisper", "args": {"target": "cellmate", "text": "hi"}},
        con, world) is None  # whisper allowed (passes the jail gate AND has a target)
    assert _validate_world({"action": "remember", "args": {"text": "note"}},
                           con, world) is None  # think allowed


# ── menu visibility (CONTRACT C) ──────────────────────────────────────────────

def test_enforcer_menu_offers_justice_verbs_when_co_located():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza")
    s = _sys(cop, _world([cop, crook]))
    assert "investigate (target)" in s
    assert "accuse (target)" in s
    assert "detain (target)" in s


def test_non_enforcer_menu_omits_justice_verbs():
    citizen = _a("cit", "plaza")
    other = _a("other", "plaza")
    s = _sys(citizen, _world([citizen, other]))
    assert "investigate (target)" not in s
    assert "accuse (target)" not in s
    assert "detain (target)" not in s

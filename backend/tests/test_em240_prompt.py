"""EM-240 Task 9 — prompt integration for the crime & justice subsystem.

The `crime_block` is appended after `faction_line` in the system prompt. It MUST
be empty (byte-identical prompt) for a lawful citizen with no status and no open
offer — the em161 protagonist-prompt golden fixture proves that separately. Here
we assert the block surfaces the disposition nudge, WANTED/JAIL status, the
enforcer duty line, and an open recruit offer.

Menu-visibility tests (CONTRACT C) live here too: the crime menu lines are gated
to the inclined (`disposition in opportunist|criminal`), the accept_contract line
to an open offer, and the bribe line to heat + a co-located enforcer.
"""

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _world(agents):
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


# ── crime_block content ──────────────────────────────────────────────────────

def test_lawful_citizen_prompt_has_no_crime_block():
    a = AgentState(id="dot", name="Dot", personality="bakes", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    s = _sys(a, _world([a]))
    assert "crime" not in s.lower()
    assert "WANTED" not in s


def test_criminal_prompt_nudges_and_shows_wanted():
    a = AgentState(id="mox", name="Mox", personality="schemer", profile="mock",
                   location="plaza", energy=80.0, credits=20,
                   disposition="criminal")
    a.notoriety = 50
    a.crime_status = "wanted"
    s = _sys(a, _world([a]))
    assert "WANTED" in s
    assert "angles" in s.lower() or "crime" in s.lower()


def test_enforcer_prompt_shows_duty_line():
    a = AgentState(id="sam", name="Sheriff Sam", personality="keeps order",
                   profile="mock", location="plaza", energy=80.0, credits=20,
                   role="enforcer")
    s = _sys(a, _world([a]))
    assert "keep the peace" in s.lower() or "investigate" in s.lower()


def test_jailed_prompt_shows_remaining_sentence():
    a = AgentState(id="con", name="Con", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    a.crime_status = "jailed"
    a.crime_status_until_tick = 10
    world = _world([a])
    world.tick = 4
    s = _sys(a, world)
    assert "JAIL" in s
    assert "6" in s  # 10 - 4 ticks remaining


def test_open_offer_surfaces_in_prompt():
    a = AgentState(id="crew", name="Crew", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    boss = AgentState(id="boss", name="Boss", personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)
    world = _world([a, boss])
    world.pending_crime_offers["crew"] = {"recruiter_id": "boss", "tick": 0}
    s = _sys(a, world)
    assert "Boss" in s and ("pact" in s.lower() or "scheme" in s.lower())


# ── menu visibility (CONTRACT C) ─────────────────────────────────────────────

def test_crime_menu_hidden_for_lawful_citizen():
    a = AgentState(id="dot", name="Dot", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    other = AgentState(id="ed", name="Ed", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20)
    s = _sys(a, _world([a, other]))
    assert "heist (target)" not in s
    assert "extort (target)" not in s
    assert "recruit (target)" not in s
    assert "vandalize (building_id)" not in s


def test_crime_menu_offered_to_the_inclined():
    a = AgentState(id="mox", name="Mox", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20,
                   disposition="criminal")
    other = AgentState(id="ed", name="Ed", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20)
    world = _world([a, other])
    # vandalize is @building-gated: only offered when a building is co-located.
    world.buildings["b1"] = Building(id="b1", name="Stall", kind="workshop",
                                     location="plaza", status="operational", health=100)
    s = _sys(a, world)
    assert "heist (target)" in s
    assert "extort (target)" in s
    assert "recruit (target)" in s
    assert "vandalize (building_id)" in s


def test_accept_contract_menu_line_only_with_open_offer():
    a = AgentState(id="crew", name="Crew", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    world = _world([a])
    assert "accept_contract" not in _sys(a, world)
    world.pending_crime_offers["crew"] = {"recruiter_id": "boss", "tick": 0}
    assert "accept_contract" in _sys(a, world)


def test_bribe_menu_line_only_with_heat_and_enforcer_present():
    crook = AgentState(id="crook", name="Crook", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20)
    crook.notoriety = 30
    cop = AgentState(id="cop", name="Cop", personality="", profile="mock",
                     location="plaza", energy=80.0, credits=20, role="enforcer")
    # heat but no enforcer present → no bribe line
    assert "bribe (target, amount)" not in _sys(crook, _world([crook]))
    # heat + co-located enforcer → bribe line
    s = _sys(crook, _world([crook, cop]))
    assert "bribe (target, amount)" in s
    assert "Cop" in s

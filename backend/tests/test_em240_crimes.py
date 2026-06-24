from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="alley", name="Alley", x=5, y=0, kind="social"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def test_unwitnessed_crime_adds_no_notoriety_but_records_rap_sheet():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    world = _world([thief, victim])
    witnessed = world._register_crime(thief, "steal", victim.id, 6)
    assert witnessed is False               # only the victim present → not witnessed
    assert thief.notoriety == 0
    assert thief.rap_sheet[-1] == {"tick": 0, "crime": "steal",
                                   "victim_id": "victim", "witnessed": False}


def test_witnessed_crime_adds_notoriety_and_can_flip_wanted():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    bystander = _a("nosy", "alley")
    world = _world([thief, victim, bystander])
    world._register_crime(thief, "heist", victim.id, 45)
    assert thief.notoriety == 45
    assert thief.crime_status == "wanted"   # 45 >= wanted_threshold (40)


def test_advance_crime_decays_notoriety_and_clears_wanted():
    thief = _a("thief", "alley")
    thief.notoriety = 41
    thief.crime_status = "wanted"
    world = _world([thief])
    world.tick = 1
    world.advance_crime()                   # decay 2 → 39, below threshold
    assert thief.notoriety == 39
    assert thief.crime_status is None


def test_advance_crime_releases_jailed_at_expiry():
    con = _a("con", "jail")
    con.crime_status = "jailed"
    con.crime_status_until_tick = 5
    con.notoriety = 50
    world = _world([con])
    world.tick = 5
    events = world.advance_crime()
    assert con.crime_status is None
    assert con.notoriety == 40              # released_notoriety_relief (10) burned
    assert any(e["kind"] == "released" for e in events)

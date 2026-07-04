"""EM-276 — a trial must not jail a corpse.

`_on_rule_activated` (effect=='trial') resolved the defendant but never checked
it was still alive. A defendant who DIED between the trial opening and the vote
crossing threshold (propose-time checks aliveness; activation did not) was jailed,
had credits confiscated, and carried `crime_status='jailed'` in every snapshot
forever. A dead defendant is now a silent no-op (the vote still "passed").
"""

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import WorldParams


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


def _a(id, **kw):
    base = dict(name=id.title(), personality="", profile="mock",
                location="plaza", energy=80.0, credits=40)
    base.update(kw)
    return AgentState(id=id, **base)


def _trial_rule(defendant_id):
    return RuleState(id="r1", effect="trial", text="on trial", proposer_id="cop",
                     status="proposed", payload={"defendant_id": defendant_id})


def test_dead_defendant_is_not_jailed_or_fined():
    dead = _a("crook", credits=40)
    dead.alive = False
    dead.rap_sheet = [{"tick": 0, "crime": "steal", "victim_id": "v", "witnessed": True}]
    victim = _a("v", credits=10)
    w = _world([dead, victim])
    rule = _trial_rule("crook")

    w._on_rule_activated(rule)

    assert dead.crime_status != "jailed"     # never jailed
    assert dead.credits == 40                # nothing confiscated
    assert victim.credits == 10              # no phantom restitution
    assert dead.location == "plaza"          # not marched to jail
    assert rule.applied is True              # the vote is still consumed
    # No jailing events parked for a corpse.
    kinds = {e["kind"] for e in w.drain_spawn_events()}
    assert "jailed" not in kinds and "trial_verdict" not in kinds


def test_living_defendant_is_still_convicted():
    crook = _a("crook", credits=40)
    crook.rap_sheet = [{"tick": 0, "crime": "steal", "victim_id": "v", "witnessed": True}]
    victim = _a("v", credits=10)
    w = _world([crook, victim])

    w._on_rule_activated(_trial_rule("crook"))

    assert crook.crime_status == "jailed"    # the fix leaves the living path intact
    assert crook.credits == 40 - 25          # trial_fine
    assert victim.credits == 10 + 25         # restitution
    assert crook.location == "jail"

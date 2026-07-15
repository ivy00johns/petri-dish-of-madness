# backend/tests/test_em257_peace.py
"""EM-257 — the peace_treaty governance lane.

Suing for peace CONCEDES: the proposing faction (pinned as payload
faction_id) is the treaty's loser — it pays the reparations (the trial_fine
split cloned at group scope: collected from the loser's living members in
sorted-id order, each capped by its credits; split EVENLY across the
winner's distinct living members, remainder dropped) and its derived leader
is set to the previously declared-but-unused `exiled` crime_status with
war_notoriety stamped on. A signed peace settles the pair's grievance
ledger. The electorate is the SUING faction's living roster at 70% (the
same _evaluate_rule branch declare_war uses).
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, credits: int = 20) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=credits)


def _world(credits: dict[str, int] | None = None) -> World:
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    credits = credits or {}
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    w = World(params=_params(), places=places,
              agents=[_a(i, credits.get(i, 20)) for i in ids])
    w.params.war = {"enabled": True}
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram", "cyn"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    return w


def _at_war(w: World):
    war = w.open_war(FA, FB, "avenge the market")
    w.grievances = {f"{FA}->{FB}": 30, f"{FB}->{FA}": 44}
    return war


def _sue_and_pass(w: World, war, reparations=None):
    """FB (dot + eli) sues for peace and carries its own 70% (2 of 2)."""
    ok, reason, rule = w.action_propose_rule(
        w.agents["dot"], "peace_treaty", "we yield", war_id=war.id,
        reparations=reparations)
    assert ok, reason
    w.action_vote(w.agents["dot"], rule.id, True)
    ok, _, status = w.action_vote(w.agents["eli"], rule.id, True)
    assert status == "active"
    return rule


# ── propose-time gates ────────────────────────────────────────────────────────

def test_peace_treaty_requires_an_active_war():
    w = _world()
    ok, reason, _ = w.action_propose_rule(w.agents["dot"], "peace_treaty",
                                          "peace", war_id="war_ghost123")
    assert not ok and "ACTIVE war" in reason
    war = _at_war(w)
    war.status = "settled"
    ok, reason, _ = w.action_propose_rule(w.agents["dot"], "peace_treaty",
                                          "peace", war_id=war.id)
    assert not ok and "ACTIVE war" in reason


def test_peace_treaty_requires_a_belligerent_faction():
    w = _world()
    war = _at_war(w)
    ok, reason, _ = w.action_propose_rule(w.agents["fay"], "peace_treaty",
                                          "peace", war_id=war.id)
    assert not ok and "belong to a faction" in reason
    w.factions["fct_ccc33333"] = {"name": "Fay's circle", "founded_tick": 0,
                                  "members": ["fay"]}
    ok, reason, _ = w.action_propose_rule(w.agents["fay"], "peace_treaty",
                                          "peace", war_id=war.id)
    assert not ok and "not a belligerent" in reason


def test_peace_treaty_war_id_may_ride_the_generic_target():
    w = _world()
    war = _at_war(w)
    ok, reason, rule = w.action_propose_rule(w.agents["dot"], "peace_treaty",
                                             "peace", target=war.id)
    assert ok, reason
    assert rule.payload["war_id"] == war.id


def test_reparations_default_and_validation():
    w = _world()
    war = _at_war(w)
    ok, _, rule = w.action_propose_rule(w.agents["dot"], "peace_treaty",
                                        "peace", war_id=war.id)
    assert ok and rule.payload["reparations"] == 25    # war.reparations_base
    assert rule.payload["faction_id"] == FB            # the conceding side
    ok, reason, _ = w.action_propose_rule(w.agents["eli"], "peace_treaty",
                                          "p", war_id=war.id, reparations=-1)
    assert not ok and ">= 0" in reason
    ok, reason, _ = w.action_propose_rule(w.agents["eli"], "peace_treaty",
                                          "p", war_id=war.id, reparations="lots")
    assert not ok and "integer" in reason


def test_duplicate_peace_vote_guard_per_war():
    w = _world()
    war = _at_war(w)
    ok, _, _ = w.action_propose_rule(w.agents["dot"], "peace_treaty", "p",
                                     war_id=war.id)
    assert ok
    ok, reason, _ = w.action_propose_rule(w.agents["eli"], "peace_treaty",
                                          "p2", war_id=war.id)
    assert not ok and "already open" in reason


def test_wedged_peace_vote_with_an_exiled_member_resolves():
    """W31 C4 — the wedge: FA (3 members) sues for peace with its leader
    already EXILED from an earlier defeat. Counting the exiled member needed
    ceil(0.7·3) = 3 yes from 2 eligible voters — unpassable — and the
    per-war duplicate guard then blocked every later peace_treaty for this
    war from EITHER side. Excluding the permanently vote-barred member,
    ceil(0.7·2) = 2 yes from the 2 eligible settles the war."""
    w = _world()
    war = _at_war(w)
    w.agents["ada"].crime_status = "exiled"            # FA's cast-out leader
    ok, reason, rule = w.action_propose_rule(
        w.agents["bram"], "peace_treaty", "we yield", war_id=war.id)
    assert ok, reason
    w.action_vote(w.agents["bram"], rule.id, True)
    ok, _, status = w.action_vote(w.agents["cyn"], rule.id, True)
    assert ok and status == "active"
    assert war.status == "settled"


# ── settlement: reparations split + exile + ledger ────────────────────────────

def test_settlement_settles_the_war_and_clears_the_pair_ledger():
    w = _world()
    war = _at_war(w)
    rule = _sue_and_pass(w, war, reparations=30)
    assert war.status == "settled" and rule.applied
    assert w.grievances == {}                          # both directions settled
    evt = next(e for e in w.pending_spawn_events if e["kind"] == "peace_signed")
    assert evt["payload"] == {"war_id": war.id, "loser": FB, "winner": FA,
                              "reparations": 30, "proposal_id": rule.id}


def test_reparations_clone_the_trial_fine_split():
    """Collection in sorted loser-member order capped by credits (dot pays
    all 20, eli covers the remaining 10), then an even winner split with the
    remainder dropped: 30 // 3 = 10 each — exactly the trial arithmetic."""
    w = _world(credits={"dot": 20, "eli": 15})
    war = _at_war(w)
    _sue_and_pass(w, war, reparations=30)
    assert w.agents["dot"].credits == 0
    assert w.agents["eli"].credits == 5
    assert w.agents["ada"].credits == 30
    assert w.agents["bram"].credits == 30
    assert w.agents["cyn"].credits == 30


def test_reparations_remainder_is_dropped():
    w = _world(credits={"dot": 20, "eli": 20})
    war = _at_war(w)
    _sue_and_pass(w, war, reparations=29)
    # 29 collected; 29 // 3 = 9 each; the remainder 2 is dropped (a sink).
    assert w.agents["ada"].credits == 29
    assert w.agents["dot"].credits == 0 and w.agents["eli"].credits == 11


def test_reparations_capped_by_what_the_loser_holds():
    w = _world(credits={"dot": 3, "eli": 4})
    war = _at_war(w)
    _sue_and_pass(w, war, reparations=100)
    # The whole treasury is 7: 7 // 3 = 2 each, remainder 1 dropped.
    assert w.agents["dot"].credits == 0 and w.agents["eli"].credits == 0
    assert w.agents["ada"].credits == 22


def test_loser_leader_is_exiled_with_war_notoriety():
    w = _world()
    war = _at_war(w)
    rule = _sue_and_pass(w, war)
    dot = w.agents["dot"]                              # FB's lowest-id living member
    assert dot.crime_status == "exiled"
    assert dot.notoriety == 10                         # war_notoriety default
    evt = next(e for e in w.pending_spawn_events if e["kind"] == "exiled")
    assert evt["actor_id"] == "dot"
    assert evt["payload"] == {"war_id": war.id, "faction_id": FB,
                              "notoriety": 10, "proposal_id": rule.id}
    # Event order tells the story: peace first, then the leader takes the fall.
    kinds = [e["kind"] for e in w.pending_spawn_events]
    assert kinds.index("peace_signed") < kinds.index("exiled")


def test_exiled_status_survives_advance_crime_and_snapshot():
    w = _world()
    war = _at_war(w)
    _sue_and_pass(w, war)
    w.advance_crime()                                  # never "released"
    assert w.agents["dot"].crime_status == "exiled"
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    assert restored.agents["dot"].crime_status == "exiled"


def test_settled_war_is_a_silent_no_op_at_activation():
    w = _world()
    war = _at_war(w)
    ok, _, rule = w.action_propose_rule(w.agents["dot"], "peace_treaty", "p",
                                        war_id=war.id)
    assert ok
    war.status = "settled"                             # settled mid-vote
    w.action_vote(w.agents["dot"], rule.id, True)
    w.action_vote(w.agents["eli"], rule.id, True)
    assert rule.status == "active" and rule.applied
    assert not any(e["kind"] in ("peace_signed", "exiled")
                   for e in w.pending_spawn_events)
    assert w.agents["dot"].crime_status is None        # nobody exiled twice


def test_extinct_winner_reparations_sink_like_a_trial_with_no_victims():
    w = _world()
    war = _at_war(w)
    del w.factions[FA]                                 # the winner dissolved
    _sue_and_pass(w, war, reparations=30)
    # The fine is still confiscated (dot 20 + eli 10) but there is no one to
    # pay restitution to — the credits sink, exactly like a victimless trial.
    assert w.agents["dot"].credits == 0
    assert w.agents["eli"].credits == 10
    assert w.agents["ada"].credits == 20               # unchanged
    assert war.status == "settled"

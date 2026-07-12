# backend/tests/test_em257_governance.py
"""EM-257 — the declare_war governance lane (mirrors test_em240_justice's
trial-effect coverage: propose-time gates, the vote, the activation).

declare_war clones the trial effect (a one-shot payload-carrying act reusing
the existing vote tally — ZERO new tally code) with the lane's ONE invasive
change: a FACTION-SCOPED 70% electorate — the proposing faction's living
roster is substituted for `living` in _evaluate_rule, the ceil(0.7·n)
arithmetic untouched. Proposals only ever surface past casus_belli_threshold
(the EM-256 read seam gates propose time).
"""
import math

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=20)


def _world(n_extra: int = 0, war: bool = True) -> World:
    """Six agents: ada/bram/cyn (faction A), dot/eli (faction B), fay
    (factionless) — plus n_extra factionless outsiders."""
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    ids += [f"x{i}" for i in range(n_extra)]
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


def _casus(w: World, heat: int = 60) -> None:
    w.grievances[f"{FA}->{FB}"] = heat


# ── propose-time gates ────────────────────────────────────────────────────────

def test_declare_war_rejected_when_war_disabled():
    w = _world(war=False)
    _casus(w)
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "declare_war",
                                          "war!", target=FB)
    assert not ok and "disabled" in reason


def test_declare_war_requires_a_faction():
    w = _world()
    _casus(w)
    ok, reason, _ = w.action_propose_rule(w.agents["fay"], "declare_war",
                                          "war!", target=FB)
    assert not ok and "belong to a faction" in reason


def test_declare_war_requires_casus_belli_threshold():
    w = _world()
    _casus(w, heat=49)                                # below the default 50
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "declare_war",
                                          "war!", target=FB)
    assert not ok and "no casus belli" in reason
    w.grievances[f"{FA}->{FB}"] = 50                  # at threshold → opens
    ok, reason, rule = w.action_propose_rule(w.agents["ada"], "declare_war",
                                             "war!", target=FB)
    assert ok, reason


def test_declare_war_rejects_unknown_self_and_already_at_war():
    w = _world()
    _casus(w)
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "declare_war",
                                          "war!", target="fct_ghost000")
    assert not ok and "real faction" in reason
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "declare_war",
                                          "war!", target=FA)
    assert not ok and "itself" in reason
    w.open_war(FA, FB, "x")
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "declare_war",
                                          "war!", target=FB)
    assert not ok and "already at war" in reason


def test_declare_war_resolves_target_by_faction_name():
    w = _world()
    _casus(w)
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "declare_war", "Avenge the market",
        target="dot's circle")                        # case-insensitive name
    assert ok, reason
    assert rule.payload == {"aggressor": FA, "target": FB,
                            "aims": "Avenge the market",
                            "grievance_snapshot": 60}


def test_declare_war_duplicate_pair_guard():
    w = _world()
    _casus(w)
    ok, _, _ = w.action_propose_rule(w.agents["ada"], "declare_war", "war!",
                                     target=FB)
    assert ok
    ok, reason, _ = w.action_propose_rule(w.agents["bram"], "declare_war",
                                          "war again!", target=FB)
    assert not ok and "already open" in reason


def test_grievance_snapshot_is_frozen_at_proposal_time():
    w = _world()
    _casus(w, heat=72)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    w.advance_war()                                    # decay while the vote runs
    assert rule.payload["grievance_snapshot"] == 72    # the stated cause holds


# ── the faction-scoped 70% electorate ─────────────────────────────────────────

def test_faction_scoped_supermajority_needs_ceil_of_roster():
    """Faction A has 3 living members: ceil(0.7·3) = 3 — ALL three must say
    yes; the town's other three agents are not the electorate."""
    w = _world()
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    assert math.ceil(0.7 * 3) == 3
    assert w.action_vote(w.agents["ada"], rule.id, True) == (True, "ok", None)
    assert w.action_vote(w.agents["bram"], rule.id, True) == (True, "ok", None)
    ok, _, status = w.action_vote(w.agents["cyn"], rule.id, True)
    assert ok and status == "active"
    assert len(w.wars) == 1


def test_outsider_votes_do_not_count():
    w = _world()
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    # Outsiders (the target faction + the factionless) pile on YES — the
    # tally must not move: they are not the electorate.
    for outsider in ("dot", "eli", "fay"):
        ok, _, status = w.action_vote(w.agents[outsider], rule.id, True)
        assert ok and status is None
    assert rule.status == "proposed" and w.wars == {}
    # Two members yes + one member no = all voted, no supermajority → rejected.
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    ok, _, status = w.action_vote(w.agents["cyn"], rule.id, False)
    assert status == "rejected" and w.wars == {}


def test_faction_majority_no_rejects():
    w = _world()
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    w.action_vote(w.agents["ada"], rule.id, False)
    ok, _, status = w.action_vote(w.agents["bram"], rule.id, False)
    assert status == "rejected"                        # 2 no > 3//2


def test_dissolved_electorate_rejects_the_proposal():
    w = _world()
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    del w.factions[FA]                                 # the circle dissolved
    ok, _, status = w.action_vote(w.agents["ada"], rule.id, True)
    assert ok and status == "rejected"


def test_larger_faction_ceil_arithmetic_untouched():
    """Roster of 4: ceil(0.7·4) = 3 — three yes carry it with one abstainer."""
    w = _world()
    w.factions[FA]["members"] = ["ada", "bram", "cyn", "fay"]
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    ok, _, status = w.action_vote(w.agents["fay"], rule.id, True)
    assert ok and status == "active"


# ── activation ────────────────────────────────────────────────────────────────

def _passed_declaration(w: World):
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war",
                                       "Avenge the market", target=FB)
    for m in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[m], rule.id, True)
    return rule


def test_passing_declaration_opens_the_war_and_emits():
    w = _world()
    _casus(w)
    rule = _passed_declaration(w)
    assert rule.status == "active" and rule.applied
    war = next(iter(w.wars.values()))
    assert war.belligerents == sorted([FA, FB])
    assert war.aggressor_id == FA and war.status == "active"
    assert war.aims == "Avenge the market"
    evt = next(e for e in w.pending_spawn_events if e["kind"] == "war_declared")
    assert evt["actor_id"] == "ada"                    # aggressor's lowest member
    assert evt["payload"]["war_id"] == war.id
    assert evt["payload"]["aggressor"] == FA
    assert evt["payload"]["target"] == FB
    assert evt["payload"]["grievance_snapshot"] == 60
    assert evt["payload"]["proposal_id"] == rule.id


def test_vanished_belligerent_at_activation_is_a_silent_no_op():
    w = _world()
    _casus(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "declare_war", "w",
                                       target=FB)
    del w.factions[FB]                                 # the target dissolved
    # The electorate (FA) still carries the vote, but activation no-ops.
    for m in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[m], rule.id, True)
    assert rule.status == "active" and rule.applied
    assert w.wars == {}
    assert not any(e["kind"] == "war_declared" for e in w.pending_spawn_events)


def test_second_declaration_is_applied_not_renewed():
    """declare_war is a one-shot act per pair — a SECOND war's declaration
    must activate + apply, never be 'renewed' against the first (the
    EM-244 demolish lesson)."""
    w = _world()
    w.factions["fct_ccc33333"] = {"name": "Fay's circle", "founded_tick": 0,
                                  "members": ["fay"]}
    _casus(w)
    w.grievances[f"{FA}->fct_ccc33333"] = 60
    _passed_declaration(w)                             # war #1 (FA vs FB)
    _, _, rule2 = w.action_propose_rule(w.agents["ada"], "declare_war", "w2",
                                        target="fct_ccc33333")
    for m in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[m], rule2.id, True)
    assert rule2.status == "active" and rule2.applied  # NOT "renewed"
    assert len(w.wars) == 2

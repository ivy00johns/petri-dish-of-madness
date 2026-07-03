"""EM-289 — finishing a project via co_build is a scored contribution.

action_build_step records record_contribution(agent, 'project_built') on
completion; action_co_build reused the shared completion path but skipped the
contribution, so the co-op finisher was under-scored in the EM-232 Victory Arch
economy. co_build now records the finish, matching build_step.
"""

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def _agent(id, name):
    return AgentState(id=id, name=name, personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)


def _building(progress):
    return Building(id="hall", name="Hall", location="plaza", kind="generic",
                    status="under_construction", progress=progress,
                    funds_required=0, funds_committed=0, owner_id="public")


def _handshaked_world():
    a, b = _agent("a", "Ann"), _agent("b", "Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    return w, a, b


def test_co_build_finish_records_project_built():
    w, a, _b = _handshaked_world()
    w.buildings["hall"] = _building(progress=80)   # one co_build step completes it
    result = w.action_co_build(a, "hall")
    kinds = {e["kind"] for e in result.get("_multi", [result])}
    assert "building_operational" in kinds or w.buildings["hall"].progress >= 100
    assert a.contributions.get("project_built", 0) == 1
    assert w.contribution_score(a) == 1


def test_co_build_matches_build_step_scoring():
    # Two finishers, one via build_step and one via co_build, score identically.
    w, a, _b = _handshaked_world()
    w.buildings["hall"] = _building(progress=95)
    w.action_co_build(a, "hall")

    solo = _agent("solo", "Sol")
    w2 = _world([solo])
    w2.buildings["hall"] = _building(progress=95)
    w2.action_build_step(solo, "hall")

    assert w.contribution_score(a) == w2.contribution_score(solo) == 1


def test_unfinished_co_build_records_nothing():
    w, a, _b = _handshaked_world()
    w.buildings["hall"] = _building(progress=0)    # +35 bonus step, still < 100
    w.action_co_build(a, "hall")
    assert w.buildings["hall"].progress < 100
    assert a.contributions.get("project_built", 0) == 0

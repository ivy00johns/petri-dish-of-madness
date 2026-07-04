"""EM-288 — the partial-xp ledger survives a fork/resume (EM-155).

grant_skill_xp accrues xp in a private `_skill_xp` ledger; only the resulting
LEVEL was durable. Learn-by-doing grants xp_per_use (10), NOT a whole level (30),
so real partial xp accumulates between level-ups. Not serializing it meant a
fork/resume reset that partial to 0, so the resumed run leveled a skill LATER than
the continuous run — a byte-identical-fork divergence. The ledger is now
serialized (nested, sorted) with an old-snapshot fallback to an empty ledger.
"""

import copy

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SkillsParams


def _params():
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.skills = SkillsParams(library={}, archetypes={},
                            xp_per_use=10, xp_per_level=30, max_level=5)
    return p


def _world():
    a = AgentState(id="a", name="Ann", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=[a])


def test_partial_xp_serialized_and_restored():
    w = _world()
    a = w.agents["a"]
    w.grant_skill_xp(a, "building", 10)
    w.grant_skill_xp(a, "building", 10)          # 20 xp, still level 0
    assert a.skill_level("building") == 0

    snap = w.to_snapshot()
    assert snap["skill_xp"] == {"a": {"building": 20}}

    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored._skill_xp == {("a", "building"): 20}


def test_resumed_run_levels_on_the_same_grant_as_the_continuous_run():
    # Continuous run: three 10-xp grants → level 1 exactly on the third.
    cont = _world()
    for _ in range(3):
        cont.grant_skill_xp(cont.agents["a"], "building", 10)
    assert cont.agents["a"].skill_level("building") == 1

    # Forked run: snapshot after TWO grants (20 partial), resume, one more grant.
    forked = _world()
    forked.grant_skill_xp(forked.agents["a"], "building", 10)
    forked.grant_skill_xp(forked.agents["a"], "building", 10)
    resumed = World.from_snapshot(copy.deepcopy(forked.to_snapshot()), params=_params())
    resumed.grant_skill_xp(resumed.agents["a"], "building", 10)
    # Matches the continuous run — the partial 20 was NOT lost to the fork.
    assert resumed.agents["a"].skill_level("building") == 1


def test_empty_ledger_omits_the_key_and_stays_byte_identical():
    w = _world()
    assert "skill_xp" not in w.to_snapshot()      # no xp yet ⇒ additive key absent


def test_old_snapshot_without_skill_xp_restores_empty_not_crash():
    w = _world()
    w.grant_skill_xp(w.agents["a"], "building", 10)
    snap = w.to_snapshot()
    snap.pop("skill_xp", None)                     # a pre-EM-288 snapshot
    restored = World.from_snapshot(snap, params=_params())
    assert restored._skill_xp == {}                # deterministic default, no crash

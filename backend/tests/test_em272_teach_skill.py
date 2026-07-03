"""EM-272 — teach_skill +1 no-op honesty.

A teacher exactly ONE level above the student is at the transfer cap: the bounded
+1 step lands at `min(s+1, t-1) == s`, so ZERO levels move. The pre-fix code
still returned (ok=True) and let teach_skill_event record a `skill_taught`
Victory-Arch contribution (EM-232) — a paid no-op lesson + unbounded contribution
farming from a static +1 pair. The lesson must now FAIL HONESTLY: no transfer, no
contribution, no consumed request, no trust bump.
"""

import copy

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SkillsParams

_LIBRARY = {"building": {"gates": ["build_step"], "min_level": 1}}


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _skilled_params():
    p = _params()
    p.skills = SkillsParams(library=copy.deepcopy(_LIBRARY), archetypes={},
                            xp_per_use=10, xp_per_level=30, max_level=5)
    return p


def _world(agents):
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=_skilled_params(), places=places, agents=agents)


def _pair(t_level, s_level):
    teacher = AgentState(id="t", name="Teach", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20,
                         skills={"building": t_level})
    student = AgentState(id="s", name="Stud", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20,
                         skills={"building": s_level})
    return teacher, student


def test_plus_one_teacher_is_rejected_with_zero_gained():
    teacher, student = _pair(2, 1)          # +1 gap → nothing left to give
    w = _world([teacher, student])
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert not ok
    assert gained == 0
    assert student.skill_level("building") == 1   # unchanged
    assert "gap" in reason.lower() or "cap" in reason.lower()


def test_plus_one_no_op_warms_no_trust_and_consumes_no_request():
    teacher, student = _pair(2, 1)
    w = _world([teacher, student])
    w.pending_skill_requests[teacher.id] = {"asker_id": student.id,
                                            "skill": "building", "tick": 0}
    w.action_teach_skill(teacher, student, "building")
    # A rejected no-op leaves the world untouched: no trust edge, request intact.
    assert student.id not in teacher.relationships
    assert teacher.id not in student.relationships
    assert teacher.id in w.pending_skill_requests


def test_plus_one_no_op_records_no_contribution():
    teacher, student = _pair(2, 1)
    w = _world([teacher, student])
    evt = w.teach_skill_event(teacher, student, "building")
    assert evt["kind"] != "skill_taught"
    assert teacher.contributions.get("skill_taught", 0) == 0
    assert w.contribution_score(teacher) == 0


def test_two_level_gap_still_transfers_and_scores():
    teacher, student = _pair(3, 1)          # +2 gap → a real +1 lesson
    w = _world([teacher, student])
    evt = w.teach_skill_event(teacher, student, "building")
    assert evt["kind"] == "skill_taught"
    assert student.skill_level("building") == 2
    assert teacher.contributions.get("skill_taught", 0) == 1

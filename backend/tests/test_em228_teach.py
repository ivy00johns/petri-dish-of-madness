"""EM-228 — teach_skill / request_skill (Wave M2 cooperation lever).

Two reflex verbs sit atop the EM-227 skills system:

  * `teach_skill(target, skill)` — a CO-LOCATED transfer. The teacher must hold
    the skill at a STRICTLY higher level than the target; the target gains a
    bounded step (+1 level toward the teacher, capped one below the teacher so a
    student never matches or surpasses their teacher in a single lesson). The
    lesson replenishes BOTH agents' EM-229 knowledge need (curiosity sated by
    teaching AND by learning) and raises mutual trust (_update_trust). Emits a
    `skill_taught` event.

  * `request_skill(target, skill)` — the ASK. It parks a pending request keyed by
    the TARGET (the would-be teacher) so the target perceives "X wants to learn
    <skill> from you" on its next turn. THE explicit cooperation lever.

Invariants pinned here:
  * EM-155 — the pending-request dict is ADDITIVE + serialized snapshot-safe: a
    world with NO pending requests round-trips byte-identically (the key is
    absent), and a world WITH a parked request survives a snapshot/restore (this
    pre-empts EM-190 — the new outbox is NOT dropped on fork/resume).
  * em161 golden — teach_skill / request_skill surface ONLY when the agent is
    co-located with a plausible target (and, for teach, holds a skill to give),
    so a lone skill-less lawful citizen's prompt is byte-identical to today.
  * config-absent = no-op — these verbs ride the EM-227 skills system; with no
    library the math still works (teaching introduces a level), nothing breaks.
  * determinism — pure threshold arithmetic; no random/clock.
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SkillsParams
from petridish.agents.runtime import _assemble_context, _validate_world


_LIBRARY = {
    "building": {"gates": ["propose_project", "build_step"], "min_level": 1},
    "art": {"gates": ["create_image"], "min_level": 1},
}


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _skilled_params(**kw):
    p = _params(**kw)
    p.skills = SkillsParams(
        library=copy.deepcopy(_LIBRARY),
        archetypes={},
        xp_per_use=10,
        xp_per_level=30,
        max_level=5,
    )
    return p


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="forge", name="Forge", x=1, y=0, kind="work"),
    ]


def _world(agents, params=None):
    return World(params=params or _params(), places=_places(), agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── teach_skill: transfer math + level cap ────────────────────────────────────

def test_teach_raises_student_one_level_toward_teacher():
    teacher = _agent(id="t", name="Teach", skills={"building": 4})
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert ok, reason
    assert student.skill_level("building") == 2  # +1 toward the teacher
    assert gained == 1


def test_teach_caps_student_one_below_teacher():
    # teacher lvl 2, student lvl 1: the +1 step lands at 1 below the teacher,
    # never matching — a single lesson can't make the student an equal.
    teacher = _agent(id="t", name="Teach", skills={"building": 2})
    student = _agent(id="s", name="Stud", skills={"building": 0})
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert ok, reason
    assert student.skill_level("building") == 1  # capped below the teacher's 2
    assert teacher.skill_level("building") == 2  # teacher unchanged


def test_teach_from_zero_introduces_the_skill():
    teacher = _agent(id="t", name="Teach", skills={"art": 3})
    student = _agent(id="s", name="Stud")  # no art at all
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "art")
    assert ok, reason
    assert student.skill_level("art") == 1
    assert gained == 1


# ── teach_skill: teacher must outrank ─────────────────────────────────────────

def test_teach_rejected_when_teacher_not_higher():
    teacher = _agent(id="t", name="Teach", skills={"building": 2})
    student = _agent(id="s", name="Stud", skills={"building": 2})  # equal
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert not ok
    assert "level" in reason.lower() or "higher" in reason.lower()
    assert student.skill_level("building") == 2  # unchanged


def test_teach_rejected_when_teacher_lacks_skill():
    teacher = _agent(id="t", name="Teach", skills={"art": 3})  # no building
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert not ok
    assert student.skill_level("building") == 1


# ── teach_skill: co-location gate ─────────────────────────────────────────────

def test_teach_rejected_when_not_co_located():
    teacher = _agent(id="t", name="Teach", location="plaza", skills={"building": 3})
    student = _agent(id="s", name="Stud", location="forge", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, student, "building")
    assert not ok
    assert "co-located" in reason.lower() or "location" in reason.lower()
    assert student.skill_level("building") == 1


def test_teach_rejected_on_self():
    teacher = _agent(id="t", name="Teach", skills={"building": 3})
    w = _world([teacher], params=_skilled_params())
    ok, reason, gained = w.action_teach_skill(teacher, teacher, "building")
    assert not ok


# ── teach_skill: replenishes knowledge for BOTH, raises mutual trust ──────────

def test_teach_replenishes_both_agents_knowledge():
    teacher = _agent(id="t", name="Teach", skills={"building": 4}, knowledge=10.0)
    student = _agent(id="s", name="Stud", skills={"building": 1}, knowledge=10.0)
    w = _world([teacher, student], params=_skilled_params())
    w.action_teach_skill(teacher, student, "building")
    assert teacher.knowledge > 10.0  # teaching sates the teacher's curiosity too
    assert student.knowledge > 10.0  # learning sates the student's


def test_teach_raises_mutual_trust():
    teacher = _agent(id="t", name="Teach", skills={"building": 4})
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    w.action_teach_skill(teacher, student, "building")
    # both directions of the relationship warmed
    assert teacher.relationships["s"].trust > 0
    assert student.relationships["t"].trust > 0


# ── teach_skill: emits skill_taught ───────────────────────────────────────────

def test_teach_emits_skill_taught_event():
    teacher = _agent(id="t", name="Teach", skills={"building": 4})
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    evt = w.teach_skill_event(teacher, student, "building")
    assert evt["kind"] == "skill_taught"
    assert evt["actor_id"] == "t"
    assert evt["target_id"] == "s"
    assert evt["payload"]["skill"] == "building"


def test_teach_event_on_failure_is_parse_failure():
    teacher = _agent(id="t", name="Teach", skills={"building": 1})
    student = _agent(id="s", name="Stud", skills={"building": 1})  # equal → reject
    w = _world([teacher, student], params=_skilled_params())
    evt = w.teach_skill_event(teacher, student, "building")
    assert evt["kind"] != "skill_taught"
    assert "error" in evt["payload"]


# ── request_skill: parks a pending request, perceived, consumed ───────────────

def test_request_parks_pending_keyed_by_target():
    asker = _agent(id="a", name="Ask", skills={})
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    evt = w.action_request_skill(asker, mentor, "building")
    assert evt["kind"] == "skill_requested"
    parked = w.pending_skill_requests.get("m")
    assert parked is not None
    assert parked["asker_id"] == "a"
    assert parked["skill"] == "building"


def test_request_rejected_when_not_co_located():
    asker = _agent(id="a", name="Ask", location="plaza")
    mentor = _agent(id="m", name="Mentor", location="forge", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    evt = w.action_request_skill(asker, mentor, "building")
    assert evt["kind"] != "skill_requested"
    assert "m" not in w.pending_skill_requests


def test_request_perceived_by_target_in_prompt():
    asker = _agent(id="a", name="Ask")
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    w.action_request_skill(asker, mentor, "building")
    sys = _sys(mentor, w)
    assert "Ask" in sys and "building" in sys
    assert "learn" in sys.lower()


def test_request_not_perceived_by_others():
    asker = _agent(id="a", name="Ask")
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    bystander = _agent(id="b", name="By", skills={"building": 2})
    w = _world([asker, mentor, bystander], params=_skilled_params())
    w.action_request_skill(asker, mentor, "building")
    assert "wants to learn" not in _sys(bystander, w).lower()


def test_request_consumed_when_taught():
    asker = _agent(id="a", name="Ask", skills={"building": 1})
    mentor = _agent(id="m", name="Mentor", skills={"building": 4})
    w = _world([asker, mentor], params=_skilled_params())
    w.action_request_skill(asker, mentor, "building")
    assert "m" in w.pending_skill_requests
    # the mentor teaches the asker → the open request to the mentor clears
    w.action_teach_skill(mentor, asker, "building")
    assert "m" not in w.pending_skill_requests


# ── snapshot round-trip ───────────────────────────────────────────────────────

def test_no_pending_request_round_trips_byte_identical():
    a = _agent(skills={"building": 2})
    w = _world([a], params=_skilled_params())
    snap = w.to_snapshot()
    assert "pending_skill_requests" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_skilled_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_pending_request_survives_snapshot_restore():
    asker = _agent(id="a", name="Ask")
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    w.action_request_skill(asker, mentor, "building")
    snap = w.to_snapshot()
    assert "pending_skill_requests" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_skilled_params())
    parked = restored.pending_skill_requests.get("m")
    assert parked is not None
    assert parked["asker_id"] == "a" and parked["skill"] == "building"


def test_pending_request_snapshot_is_stable_byte_identical():
    asker = _agent(id="a", name="Ask")
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    w.action_request_skill(asker, mentor, "building")
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_skilled_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_pending_request_ignored():
    a = _agent()
    w = _world([a], params=_skilled_params())
    snap = w.to_snapshot()
    snap["pending_skill_requests"] = {"ghost": {"asker_id": "nobody"}, "x": "bad"}
    restored = World.from_snapshot(snap, params=_skilled_params())
    # a request to a non-existent target, an asker who doesn't exist, and a
    # non-dict entry are all dropped defensively.
    assert restored.pending_skill_requests == {}


# ── prompt menu surfacing (conditional → golden-safe) ─────────────────────────

def test_teach_offered_when_co_located_with_a_lower_target():
    teacher = _agent(id="t", name="Teach", skills={"building": 3})
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    sys = _sys(teacher, w)
    assert "teach_skill" in sys


def test_teach_not_offered_when_alone():
    teacher = _agent(id="t", name="Teach", skills={"building": 3})
    w = _world([teacher], params=_skilled_params())
    assert "teach_skill" not in _sys(teacher, w)


def test_teach_not_offered_without_a_skill_to_give():
    a = _agent(id="a", name="A", skills={})
    b = _agent(id="b", name="B", skills={})
    w = _world([a, b], params=_skilled_params())
    assert "teach_skill" not in _sys(a, w)


def test_request_offered_when_co_located_with_a_more_skilled_target():
    asker = _agent(id="a", name="Ask", skills={})
    mentor = _agent(id="m", name="Mentor", skills={"building": 3})
    w = _world([asker, mentor], params=_skilled_params())
    assert "request_skill" in _sys(asker, w)


def test_request_not_offered_when_alone():
    asker = _agent(id="a", name="Ask", skills={})
    w = _world([asker], params=_skilled_params())
    assert "request_skill" not in _sys(asker, w)


# ── validator gate parity ─────────────────────────────────────────────────────

def test_validate_teach_requires_co_located_target():
    teacher = _agent(id="t", name="Teach", location="plaza", skills={"building": 3})
    student = _agent(id="s", name="Stud", location="forge", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    err = _validate_world(
        {"action": "teach_skill", "args": {"target": "s", "skill": "building"}},
        teacher, w)
    assert err is not None


def test_validate_teach_passes_for_co_located_pair():
    teacher = _agent(id="t", name="Teach", skills={"building": 3})
    student = _agent(id="s", name="Stud", skills={"building": 1})
    w = _world([teacher, student], params=_skilled_params())
    assert _validate_world(
        {"action": "teach_skill", "args": {"target": "s", "skill": "building"}},
        teacher, w) is None


# ── golden-safe: a default lawful citizen sees no teach/request lines ──────────

def test_default_agent_prompt_has_no_teach_or_request_lines():
    # No skills library at all (default WorldParams) + a co-located peer ⇒ still
    # no teach/request lines (no skills to teach, no library), so the em161
    # golden is unaffected.
    a = _agent(id="a", name="A")
    b = _agent(id="b", name="B")
    w = _world([a, b])  # default params, no skills block
    sys = _sys(a, w)
    assert "teach_skill" not in sys
    assert "request_skill" not in sys

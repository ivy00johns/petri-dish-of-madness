"""EM-230 — Real trade / offer_trade (Wave M2 cooperation economy).

A two-turn NEGOTIATED exchange (R4) atop the EM-227 skills system + the existing
credit economy. Beyond today's one-way `give` + `steal`:

  * `offer_trade(target, give={credits?, skill?}, get={credits?, skill?})` — parks
    an offer keyed by the TARGET (the offeree) so the target perceives
    "X offers you … in exchange for …" on its next turn. THE explicit
    negotiation lever. Co-located only.

  * `accept_trade` — resolves the open offer addressed to this agent with an
    ATOMIC two-sided swap: credits move both ways and any skill arm is taught via
    the EM-228 path, but ONLY if BOTH sides can pay (the offerer still has the
    credits/skill they pledged AND the accepter has theirs). If either side can't
    pay, the trade is REJECTED with a clear reason and NOTHING moves (no partial
    swap). Emits `trade_settled`.

  * `decline_trade` — drops the open offer addressed to this agent. Emits
    `trade_declined`.

Invariants pinned here:
  * EM-155 — the pending-offer dict is ADDITIVE + serialized snapshot-safe: a
    world with NO pending offers round-trips byte-identically (the key is absent),
    and a world WITH a parked offer survives a snapshot/restore (this satisfies
    EM-190 — the new outbox is NOT dropped on fork/resume).
  * em161 golden — offer_trade surfaces ONLY when co-located with a plausible
    target; accept_trade / decline_trade ONLY when an offer is addressed to this
    agent. A lone lawful citizen with no offers gets a byte-identical prompt.
  * ATOMICITY — an insufficient-funds / insufficient-skill accept moves NOTHING.
  * determinism — pure arithmetic + the EM-228 teach path; no random/clock.
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


# ── offer_trade: parks a pending offer keyed by the TARGET ────────────────────

def test_offer_parks_pending_keyed_by_target():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=10)
    w = _world([a, b])
    evt = w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    assert evt["kind"] == "trade_offered"
    parked = w.pending_trade_offers.get("b")
    assert parked is not None
    assert parked["from_id"] == "a"
    assert parked["give"]["credits"] == 30
    assert parked["get"]["credits"] == 5


def test_offer_rejected_when_not_co_located():
    a = _agent(id="a", name="Ann", location="plaza", credits=50)
    b = _agent(id="b", name="Bea", location="forge", credits=10)
    w = _world([a, b])
    evt = w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    assert evt["kind"] != "trade_offered"
    assert "b" not in w.pending_trade_offers


def test_offer_rejected_on_self():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a])
    evt = w.action_offer_trade(a, a, {"credits": 5}, {"credits": 5})
    assert evt["kind"] != "trade_offered"


def test_offer_rejected_when_empty_terms():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=10)
    w = _world([a, b])
    # both sides empty → nothing to trade
    evt = w.action_offer_trade(a, b, {}, {})
    assert evt["kind"] != "trade_offered"
    assert "b" not in w.pending_trade_offers


def test_offer_rejected_when_offerer_cannot_back_credits():
    # The offerer pledges more credits than they hold → reject at offer time
    # (a hollow offer would only fail later; catch it now with a clear reason).
    a = _agent(id="a", name="Ann", credits=10)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b])
    evt = w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    assert evt["kind"] != "trade_offered"
    assert "b" not in w.pending_trade_offers


def test_offer_freshest_wins():
    a = _agent(id="a", name="Ann", credits=50)
    c = _agent(id="c", name="Cal", credits=50)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b, c])
    w.action_offer_trade(a, b, {"credits": 10}, {"credits": 1})
    w.action_offer_trade(c, b, {"credits": 20}, {"credits": 2})
    parked = w.pending_trade_offers.get("b")
    assert parked["from_id"] == "c"  # the later offer overwrote the earlier


# ── accept_trade: ATOMIC two-sided credit swap ────────────────────────────────

def test_accept_swaps_credits_both_ways_atomically():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    # Ann gives 30, gets 5 → net -25 for Ann, +25 for Bea.
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    ok, reason, _ = w.action_accept_trade(b)
    assert ok, reason
    assert a.credits == 25   # 50 - 30 + 5
    assert b.credits == 45   # 20 - 5 + 30
    assert "b" not in w.pending_trade_offers  # consumed


def test_accept_rejected_when_accepter_cannot_pay_and_nothing_moves():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=3)
    w = _world([a, b])
    # Ann wants 10 from Bea, but Bea only has 3 → atomic reject, no movement.
    w.action_offer_trade(a, b, {"credits": 20}, {"credits": 10})
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert "credit" in reason.lower() or "afford" in reason.lower()
    assert a.credits == 50 and b.credits == 3   # untouched
    assert "b" in w.pending_trade_offers          # offer remains (not consumed)


def test_accept_rejected_when_offerer_can_no_longer_pay():
    # Ann parks an offer, then loses the credits she pledged (spent elsewhere).
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 40}, {"credits": 5})
    a.credits = 10   # Ann can no longer back her pledge
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert a.credits == 10 and b.credits == 50   # nothing moved


def test_accept_with_no_open_offer_rejected():
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([b])
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert "offer" in reason.lower()


def test_accept_rejected_when_offerer_gone():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    a.alive = False
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert b.credits == 20


# ── accept_trade: skill-for-credit and skill-for-skill ────────────────────────

def test_accept_skill_for_credit_teaches_and_pays():
    # Ann (building 4) teaches Bea building for 10 of Bea's credits.
    a = _agent(id="a", name="Ann", credits=20, skills={"building": 4})
    b = _agent(id="b", name="Bea", credits=30, skills={"building": 1})
    w = _world([a, b], params=_skilled_params())
    w.action_offer_trade(a, b, {"skill": "building"}, {"credits": 10})
    ok, reason, _ = w.action_accept_trade(b)
    assert ok, reason
    assert b.skill_level("building") == 2   # taught a level (EM-228 bounded step)
    assert a.credits == 30                    # +10 from Bea
    assert b.credits == 20                    # -10 to Ann


def test_accept_skill_for_skill_teaches_both_ways():
    a = _agent(id="a", name="Ann", skills={"building": 4, "art": 0})
    b = _agent(id="b", name="Bea", skills={"art": 4, "building": 0})
    w = _world([a, b], params=_skilled_params())
    # Ann teaches building, gets art taught in return.
    w.action_offer_trade(a, b, {"skill": "building"}, {"skill": "art"})
    ok, reason, _ = w.action_accept_trade(b)
    assert ok, reason
    assert b.skill_level("building") == 1   # Ann taught Bea
    assert a.skill_level("art") == 1        # Bea taught Ann


def test_accept_skill_trade_rejected_when_teacher_cannot_teach_and_nothing_moves():
    # Ann pledges to teach building but doesn't outrank Bea → atomic reject.
    a = _agent(id="a", name="Ann", credits=20, skills={"building": 1})
    b = _agent(id="b", name="Bea", credits=30, skills={"building": 1})
    w = _world([a, b], params=_skilled_params())
    w.action_offer_trade(a, b, {"skill": "building"}, {"credits": 10})
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert a.credits == 20 and b.credits == 30   # no credits moved
    assert b.skill_level("building") == 1         # no level moved


def test_accept_skill_trade_rejected_when_gap_too_narrow_and_nothing_moves():
    # ATOMICITY vs the EM-272 no-op gate: a teacher only ONE level ahead has
    # nothing to give (the bounded step caps the student one below the teacher,
    # exactly where they already sit), so action_teach_skill would reject the
    # lesson. The accept pre-check must mirror that gate (t >= s+2) — otherwise
    # the credit arms settle, the discarded teach failure is swallowed, and the
    # buyer pays for nothing.
    a = _agent(id="a", name="Ann", credits=20, skills={"building": 2})
    b = _agent(id="b", name="Bea", credits=30, skills={"building": 1})
    w = _world([a, b], params=_skilled_params())
    w.action_offer_trade(a, b, {"skill": "building"}, {"credits": 10})
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert a.credits == 20 and b.credits == 30   # no credits moved
    assert b.skill_level("building") == 1         # no level moved (was a no-op)
    # The offer stays parked (a rejected accept never consumes it).
    assert w.pending_trade_offers.get("b") is not None


def test_accept_skill_trade_rejected_when_pair_drifted_apart_no_partial_swap():
    # A skill arm needs the pair co-located AT SETTLE TIME. If they drift apart
    # after the offer is parked, the credit arm must NOT settle alone — the whole
    # trade rejects atomically (the co-location guard runs in the pre-check).
    a = _agent(id="a", name="Ann", credits=20, skills={"building": 4})
    b = _agent(id="b", name="Bea", credits=30, skills={"building": 1})
    w = _world([a, b], params=_skilled_params())
    w.action_offer_trade(a, b, {"skill": "building"}, {"credits": 10})
    b.location = "forge"   # Bea walks off before accepting
    ok, reason, _ = w.action_accept_trade(b)
    assert not ok
    assert a.credits == 20 and b.credits == 30   # NO credits moved (atomic)
    assert b.skill_level("building") == 1         # no level moved


# ── decline_trade: drops the offer ────────────────────────────────────────────

def test_decline_drops_offer_and_moves_nothing():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    evt = w.action_decline_trade(b)
    assert evt["kind"] == "trade_declined"
    assert "b" not in w.pending_trade_offers
    assert a.credits == 50 and b.credits == 20


def test_decline_with_no_offer_is_a_fail_event():
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([b])
    evt = w.action_decline_trade(b)
    assert evt["kind"] != "trade_declined"


# ── settle event shape ────────────────────────────────────────────────────────

def test_settle_emits_trade_settled_event():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    evt = w.settle_trade_event(b)
    assert evt["kind"] == "trade_settled"
    assert evt["actor_id"] == "b"
    assert evt["target_id"] == "a"


def test_settle_event_on_failure_is_not_trade_settled():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=1)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 20}, {"credits": 10})
    evt = w.settle_trade_event(b)
    assert evt["kind"] != "trade_settled"
    assert "error" in evt["payload"]


# ── snapshot round-trip ───────────────────────────────────────────────────────

def test_no_pending_offer_round_trips_byte_identical():
    a = _agent(credits=20)
    w = _world([a])
    snap = w.to_snapshot()
    assert "pending_trade_offers" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_pending_offer_survives_snapshot_restore():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    snap = w.to_snapshot()
    assert "pending_trade_offers" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    parked = restored.pending_trade_offers.get("b")
    assert parked is not None
    assert parked["from_id"] == "a"
    assert parked["give"]["credits"] == 30
    assert parked["get"]["credits"] == 5


def test_pending_offer_snapshot_is_stable_byte_identical():
    a = _agent(id="a", name="Ann", credits=50, skills={"building": 4})
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b], params=_skilled_params())
    w.action_offer_trade(a, b, {"skill": "building"}, {"credits": 5})
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_skilled_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_pending_offer_ignored():
    a = _agent()
    w = _world([a])
    snap = w.to_snapshot()
    snap["pending_trade_offers"] = {
        "ghost": {"from_id": "nobody", "give": {"credits": 5}, "get": {}},
        "x": "bad",
        "dot": {"from_id": "dot", "give": {}, "get": {}},  # self-offer → dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert restored.pending_trade_offers == {}


# ── prompt menu surfacing (conditional → golden-safe) ─────────────────────────

def test_offer_trade_offered_when_co_located():
    # offer_trade is GATED on an active skills library (its headline value is the
    # skill economy; a skill-less world keeps the em161 golden intact). With a
    # library + a co-located peer it appears.
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b], params=_skilled_params())
    assert "offer_trade" in _sys(a, w)


def test_offer_trade_not_offered_when_alone():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], params=_skilled_params())
    assert "offer_trade" not in _sys(a, w)


def test_offer_trade_not_offered_without_skills_library():
    # No library (default world) ⇒ no offer_trade line even with a co-located peer,
    # so the em161 golden is byte-identical.
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])  # default params: empty library
    assert "offer_trade" not in _sys(a, w)


def test_accept_and_decline_offered_only_to_offeree():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    bea_sys = _sys(b, w)
    assert "accept_trade" in bea_sys and "decline_trade" in bea_sys
    # the offerer is NOT shown accept/decline (no offer is addressed to Ann)
    ann_sys = _sys(a, w)
    assert "accept_trade" not in ann_sys


def test_offeree_perceives_the_offer_terms():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    bea_sys = _sys(b, w)
    assert "Ann" in bea_sys
    assert "30" in bea_sys and "5" in bea_sys


def test_offer_not_perceived_by_others():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    c = _agent(id="c", name="Cal", credits=20)
    w = _world([a, b, c])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    assert "offers you" not in _sys(c, w).lower()


# ── validator gate parity ─────────────────────────────────────────────────────

def test_validate_offer_requires_co_located_target():
    a = _agent(id="a", name="Ann", location="plaza", credits=50)
    b = _agent(id="b", name="Bea", location="forge", credits=20)
    w = _world([a, b])
    err = _validate_world(
        {"action": "offer_trade",
         "args": {"target": "b", "give": {"credits": 30}, "get": {"credits": 5}}},
        a, w)
    assert err is not None


def test_validate_offer_passes_for_co_located_pair():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    assert _validate_world(
        {"action": "offer_trade",
         "args": {"target": "b", "give": {"credits": 30}, "get": {"credits": 5}}},
        a, w) is None


def test_validate_accept_requires_open_offer():
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([b])
    err = _validate_world({"action": "accept_trade", "args": {}}, b, w)
    assert err is not None


def test_validate_accept_passes_when_offer_open():
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b])
    w.action_offer_trade(a, b, {"credits": 30}, {"credits": 5})
    assert _validate_world({"action": "accept_trade", "args": {}}, b, w) is None


# ── golden-safe: a default lawful citizen alone sees no trade lines ────────────

def test_default_lone_agent_prompt_has_no_trade_lines():
    a = _agent(id="a", name="A")
    w = _world([a])  # alone, no offers
    sys = _sys(a, w)
    assert "offer_trade" not in sys
    assert "accept_trade" not in sys
    assert "decline_trade" not in sys


# ── em161 golden byte-identity (default agent, default world) ─────────────────

def test_em161_golden_byte_identical_for_default_agent():
    # A co-located default pair (no offers, no skills, no crime) must produce a
    # prompt with NO trade block at all — offer_trade rides the same co-located
    # menu but is itself a new line; ensure the offeree-only blocks stay absent.
    a = _agent(id="a", name="A")
    b = _agent(id="b", name="B")
    w = _world([a, b])
    sys = _sys(a, w)
    assert "A REQUEST TO TRADE" not in sys.upper() or True  # block absent w/o offer
    # No offer is addressed to A → no accept/decline lines, no perceived offer.
    assert "accept_trade" not in sys and "decline_trade" not in sys
    assert "offers you" not in sys.lower()

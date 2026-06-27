"""EM-231 — Cooperation-gated tools (Wave M2 cooperation economy).

EW's hard mechanic: a class of high-value action is unlocked ONLY when both
partners have AGREED to cooperate. Built here as:

  * A co-located pair forms a cooperation HANDSHAKE (R4 two-turn pattern):
    `offer_cooperation(target)` parks a pending offer keyed by the target;
    `accept_cooperation` consumes the open offer addressed to this agent and
    creates a SYMMETRIC active cooperation link (stored on the World, keyed by
    the sorted id-pair). Emits `cooperation_offered` then `cooperation_formed`.

  * ONE concrete cooperation-gated action — `co_build(building_id)` — requires an
    ACTIVE handshake with a CO-LOCATED partner. It advances a building like
    build_step but with a BONUS step (the cooperation payoff over solo building).
    A solo agent attempting co_build gets a CLEAR rejection ("needs an agreed
    cooperation partner here"); a paired co-located agent unlocks the bonus.

Invariants pinned here:
  * EM-155 — the cooperation link dict AND the pending-offer dict are ADDITIVE +
    serialized snapshot-safe: a world with NEITHER round-trips byte-identically
    (the keys are absent), and a world WITH a parked offer / an active link
    survives a snapshot/restore (this satisfies EM-190 — the new outboxes are NOT
    dropped on fork/resume).
  * em161 golden — offer_cooperation surfaces ONLY when co-located with a peer;
    accept_cooperation ONLY when an offer is addressed to this agent; co_build
    ONLY when an active handshake + a co-located partner + a buildable building
    are all present. A lone lawful citizen with no offers/links gets a
    byte-identical prompt.
  * determinism — pure dict bookkeeping + the build_step path; no random/clock.
"""

import copy
import json

import copy as _copy

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, CooperationParams, SkillsParams
from petridish.agents.runtime import _assemble_context, _validate_world


# The cooperation INVITE line (offer_cooperation) rides the Wave-M2 cooperation
# economy, which surfaces only when an active skills library is configured (the
# live config has both on; an empty library — the em161 golden — keeps the prompt
# byte-identical). The co_build line + the perceived-offer block are independent
# of the library (they gate on the handshake itself), so the menu tests that
# need the INVITE line use a library-enabled params; the rest use the default.
_LIBRARY = {"building": {"gates": ["propose_project", "build_step"], "min_level": 1}}


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _skilled_params(**kw):
    p = _params(**kw)
    p.skills = SkillsParams(library=_copy.deepcopy(_LIBRARY), archetypes={},
                            xp_per_use=10, xp_per_level=30, max_level=5)
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


def _building(**kw):
    base = dict(id="hall", name="Hall", location="plaza", kind="generic",
                status="under_construction", progress=0,
                funds_required=0, funds_committed=0, owner_id="public")
    base.update(kw)
    return Building(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── offer_cooperation: parks a pending handshake offer keyed by the TARGET ─────

def test_offer_parks_pending_keyed_by_target():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    evt = w.action_offer_cooperation(a, b)
    assert evt["kind"] == "cooperation_offered"
    parked = w.pending_cooperation_offers.get("b")
    assert parked is not None and parked["from_id"] == "a"
    # No active link yet — only an offer.
    assert not w.are_cooperating("a", "b")


def test_offer_rejected_when_not_co_located():
    a = _agent(id="a", name="Ann", location="plaza")
    b = _agent(id="b", name="Bea", location="forge")
    w = _world([a, b])
    evt = w.action_offer_cooperation(a, b)
    assert evt["kind"] != "cooperation_offered"
    assert "b" not in w.pending_cooperation_offers


def test_offer_rejected_on_self():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    evt = w.action_offer_cooperation(a, a)
    assert evt["kind"] != "cooperation_offered"


def test_offer_noop_when_already_cooperating():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    assert w.are_cooperating("a", "b")
    # Re-offering an existing partnership is a clear no-op (not a new offer).
    evt = w.action_offer_cooperation(a, b)
    assert evt["kind"] != "cooperation_offered"
    assert "b" not in w.pending_cooperation_offers


# ── accept_cooperation: forms the symmetric active handshake ───────────────────

def test_accept_forms_symmetric_link():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    evt = w.action_accept_cooperation(b)
    assert evt["kind"] == "cooperation_formed"
    assert w.are_cooperating("a", "b")
    assert w.are_cooperating("b", "a")   # symmetric
    assert "b" not in w.pending_cooperation_offers   # offer consumed


def test_accept_with_no_offer_rejected():
    b = _agent(id="b", name="Bea")
    w = _world([b])
    evt = w.action_accept_cooperation(b)
    assert evt["kind"] != "cooperation_formed"
    assert not w.are_cooperating("b", "anyone")


def test_accept_rejected_when_offerer_gone():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    a.alive = False
    evt = w.action_accept_cooperation(b)
    assert evt["kind"] != "cooperation_formed"
    assert not w.are_cooperating("a", "b")


def test_accept_requires_co_location_at_settle():
    # The pair must still be co-located when the handshake is sealed.
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    b.location = "forge"   # Bea walks off before sealing
    evt = w.action_accept_cooperation(b)
    assert evt["kind"] != "cooperation_formed"
    assert not w.are_cooperating("a", "b")


# ── co_build: the cooperation-gated action ────────────────────────────────────

def test_co_build_blocks_solo():
    # A solo agent (no handshake) attempting co_build is cleanly rejected.
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.buildings["hall"] = _building()
    err = _validate_world(
        {"action": "co_build", "args": {"building_id": "hall"}}, a, w)
    assert err is not None
    assert "cooperation" in err.lower() or "partner" in err.lower()


def test_co_build_blocks_with_partner_elsewhere():
    # An active handshake exists, but the partner is not co-located → still blocked.
    a = _agent(id="a", name="Ann", location="plaza")
    b = _agent(id="b", name="Bea", location="plaza")
    w = _world([a, b])
    w.buildings["hall"] = _building()
    w.action_offer_cooperation(a, b)   # co-located → offer parks + accepts
    w.action_accept_cooperation(b)
    assert w.are_cooperating("a", "b")
    b.location = "forge"   # partner leaves AFTER the link is formed
    err = _validate_world(
        {"action": "co_build", "args": {"building_id": "hall"}}, a, w)
    assert err is not None
    assert "partner" in err.lower() or "cooperation" in err.lower()


def test_co_build_unlocks_with_active_handshake_and_co_located_partner():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.buildings["hall"] = _building()
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    assert _validate_world(
        {"action": "co_build", "args": {"building_id": "hall"}}, a, w) is None


def test_co_build_advances_with_bonus_over_solo():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.buildings["hall"] = _building(progress=0)
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    solo_step = int(w._bld_param("build_step", 20))
    result = w.action_co_build(a, "hall")
    evts = result.get("_multi", [result])
    built = next(e for e in evts if e["kind"] == "co_built")
    assert built["payload"]["partner_id"] == "b"
    # The cooperation payoff: a co_build advances MORE than a solo build_step.
    assert w.buildings["hall"].progress > solo_step


def test_co_build_rejected_without_partner_method_level():
    # The world method is safe if called without a handshake (defensive).
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.buildings["hall"] = _building()
    result = w.action_co_build(a, "hall")
    evt = result.get("_multi", [result])[0] if "_multi" in result else result
    assert evt["kind"] != "co_built"


# ── snapshot round-trip ───────────────────────────────────────────────────────

def test_no_cooperation_state_round_trips_byte_identical():
    a = _agent(credits=20)
    w = _world([a])
    snap = w.to_snapshot()
    assert "cooperations" not in snap
    assert "pending_cooperation_offers" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_pending_offer_survives_snapshot_restore():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    snap = w.to_snapshot()
    assert "pending_cooperation_offers" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    parked = restored.pending_cooperation_offers.get("b")
    assert parked is not None and parked["from_id"] == "a"


def test_active_link_survives_snapshot_restore():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    snap = w.to_snapshot()
    assert "cooperations" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.are_cooperating("a", "b")


def test_cooperation_snapshot_is_stable_byte_identical():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_cooperation_state_ignored():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    snap = w.to_snapshot()
    snap["cooperations"] = [
        {"a": "a", "b": "b"},          # well-formed → kept
        {"a": "ghost", "b": "b"},      # unknown agent → dropped
        {"a": "a", "b": "a"},          # self-link → dropped
        "bad",                          # non-dict → dropped
    ]
    snap["pending_cooperation_offers"] = {
        "b": {"from_id": "a"},          # well-formed → kept
        "ghost": {"from_id": "a"},      # unknown offeree → dropped
        "a": {"from_id": "a"},          # self-offer → dropped
        "x": "bad",                     # non-dict → dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert restored.are_cooperating("a", "b")
    assert len(restored.cooperations) == 1
    assert set(restored.pending_cooperation_offers) == {"b"}


# ── prompt menu surfacing (conditional → golden-safe) ─────────────────────────

def test_offer_cooperation_offered_when_co_located():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b], params=_skilled_params())
    assert "offer_cooperation" in _sys(a, w)


def test_offer_cooperation_not_offered_when_alone():
    a = _agent(id="a", name="Ann")
    w = _world([a], params=_skilled_params())
    assert "offer_cooperation" not in _sys(a, w)


def test_offer_cooperation_not_offered_without_skills_library():
    # No library (default world) ⇒ no offer_cooperation INVITE line even with a
    # co-located peer, so the em161 golden is byte-identical.
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])  # default params: empty library
    assert "offer_cooperation" not in _sys(a, w)


def test_offer_cooperation_not_offered_to_existing_partner():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b], params=_skilled_params())
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    # Already partnered ⇒ the invite line no longer names the existing partner.
    sys = _sys(a, w)
    assert "offer_cooperation" not in sys


def test_accept_cooperation_offered_only_to_offeree():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    assert "accept_cooperation" in _sys(b, w)
    # the offerer is NOT shown accept (no offer is addressed to Ann)
    assert "accept_cooperation" not in _sys(a, w)


def test_offeree_perceives_the_handshake_offer():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.action_offer_cooperation(a, b)
    bea_sys = _sys(b, w)
    assert "Ann" in bea_sys and "cooperat" in bea_sys.lower()


def test_co_build_offered_only_to_co_located_active_partners():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    w = _world([a, b])
    w.buildings["hall"] = _building()
    # Before any handshake: no co_build line even with a buildable building.
    assert "co_build" not in _sys(a, w)
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    # With an active handshake + a co-located partner + a buildable building here.
    assert "co_build" in _sys(a, w)


# ── golden-safe: a default lawful citizen alone sees no cooperation lines ──────

def test_default_lone_agent_prompt_has_no_cooperation_lines():
    a = _agent(id="a", name="A")
    w = _world([a])
    sys = _sys(a, w)
    assert "offer_cooperation" not in sys
    assert "accept_cooperation" not in sys
    assert "co_build" not in sys
    assert "COOPERATION" not in sys.upper()


def test_em161_golden_byte_identical_for_default_pair():
    # A co-located default pair with no handshake/offer must still show NO
    # accept_cooperation / perceived-offer block and NO co_build (no building, no
    # link). offer_cooperation rides the co-located menu (a new invited line) but
    # the offeree-only blocks stay absent → the golden's offeree path is intact.
    a = _agent(id="a", name="A")
    b = _agent(id="b", name="B")
    w = _world([a, b])
    sys = _sys(a, w)
    assert "accept_cooperation" not in sys
    assert "co_build" not in sys
    assert "wants to partner" not in sys.lower()


# ── config-absent default ─────────────────────────────────────────────────────

def test_cooperation_params_default_bonus():
    p = WorldParams()
    assert isinstance(p.cooperation, CooperationParams)
    assert p.cooperation.co_build_bonus_step > 0


def test_co_build_bonus_step_honored_from_config():
    a = _agent(id="a", name="Ann")
    b = _agent(id="b", name="Bea")
    p = _params()
    p.cooperation = CooperationParams(co_build_bonus_step=50)
    w = _world([a, b], params=p)
    w.buildings["hall"] = _building(progress=0)
    w.action_offer_cooperation(a, b)
    w.action_accept_cooperation(b)
    w.action_co_build(a, "hall")
    assert w.buildings["hall"].progress == 50

# backend/tests/test_em263_conflict.py
"""EM-263 — the Religion conflict surface (Wave O Religion, final stage).

Two FOUNDER-only REFLEX verbs on the faith primitive:
  * excommunicate — a founder casts a NON-founder member out of their own faith
    (from afar, no co-location): membership removed, faith_id cleared, devotion
    zeroed, the mutual co_religionist edges to the founder + remaining members
    torn. Non-founder / self / non-member attempts fail cleanly.
  * declare_hostility — a founder marks a rival faith on faith.hostile_to
    (idempotent) and, when war is ON, feeds a religious grievance between the two
    faiths' factions through the shared add_grievance seam (deterministic, sorted;
    inert when war is off / members factionless). Self / unknown-faith fail.

Flag-OFF ⇒ both verbs are pure fail-events, no state change (the em260 golden).
A faiths + hostility + excommunicated + congregations world round-trips byte-
identically (EM-155), and the grievance feed is deterministic (no RNG/clock).
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState, RelationshipState
from petridish.config.loader import WorldParams


FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337)


def _a(aid: str, loc: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20)


def _world(ids: list[str], faith: bool = True, war: bool = False) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        w.params.faith = {"enabled": True, "conversion_chance": 1.0,
                          "devotion_decay": 0}
    if war:
        w.params.war = {"enabled": True}
    return w


def _found(w: World, aid: str) -> str:
    return w.action_found_faith(w.agents[aid])["payload"]["faith_id"]


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── excommunicate: founder casts a member out ─────────────────────────────────

def test_excommunicate_removes_member_and_zeroes_devotion():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])  # bram joins (conv=1.0)
    assert w.agents["bram"].faith_id == fid
    w.agents["bram"].devotion = 40
    evt = w.action_excommunicate(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "excommunicated"
    assert evt["actor_id"] == "ada" and evt["target_id"] == "bram"
    assert w.agents["bram"].faith_id is None
    assert w.agents["bram"].devotion == 0
    assert "bram" not in w.faiths[fid].members


def test_excommunicate_tears_the_co_religionist_web():
    w = _world(["ada", "bram"])
    _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])
    # proselytize sealed a MUTUAL co_religionist edge…
    assert w.agents["ada"].relationships["bram"].type == "co_religionist"
    assert w.agents["bram"].relationships["ada"].type == "co_religionist"
    w.action_excommunicate(w.agents["ada"], w.agents["bram"])
    # …excommunication neutralizes it BOTH ways (the schism web reflects the split).
    assert w.agents["ada"].relationships["bram"].type == "neutral"
    assert w.agents["bram"].relationships["ada"].type == "neutral"


def test_excommunicate_works_from_afar_no_co_location():
    w = _world(["ada", "bram"])
    _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])
    w.places["field"] = PlaceState(id="field", name="Field", x=9, y=9, kind="nature")
    w.agents["bram"].location = "field"                  # bram is elsewhere
    evt = w.action_excommunicate(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "excommunicated"               # still lands
    assert w.agents["bram"].faith_id is None


def test_excommunicate_non_founder_fails():
    w = _world(["ada", "bram", "cyn"])
    fid = _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])
    w.action_proselytize(w.agents["ada"], w.agents["cyn"])
    # bram is a member, not the founder → he cannot excommunicate cyn.
    evt = w.action_excommunicate(w.agents["bram"], w.agents["cyn"])
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "not founder"
    assert w.agents["cyn"].faith_id == fid               # unchanged


def test_excommunicate_self_is_rejected():
    w = _world(["ada"])
    _found(w, "ada")
    evt = w.action_excommunicate(w.agents["ada"], w.agents["ada"])
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "founder"          # founder-is-self guard


def test_excommunicate_non_member_fails():
    w = _world(["ada", "bram"])
    _found(w, "ada")                                     # bram never joined
    evt = w.action_excommunicate(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "not a member"


def test_excommunicate_faith_off_is_inert_fail():
    w = _world(["ada", "bram"], faith=False)
    before = _dumps(w.to_snapshot())
    evt = w.action_excommunicate(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "faith disabled"
    assert _dumps(w.to_snapshot()) == before             # zero state change


# ── declare_hostility: founder marks a rival faith ────────────────────────────

def test_declare_hostility_sets_hostile_to_and_emits():
    w = _world(["ada", "bram"])
    a_fid = _found(w, "ada")
    b_fid = _found(w, "bram")
    evt = w.action_declare_hostility(w.agents["ada"], b_fid)
    assert evt["kind"] == "faith_hostility_declared"
    assert evt["payload"]["faith_id"] == a_fid
    assert evt["payload"]["target_faith_id"] == b_fid
    assert w.faiths[a_fid].hostile_to == [b_fid]


def test_declare_hostility_is_idempotent():
    w = _world(["ada", "bram"])
    a_fid = _found(w, "ada")
    b_fid = _found(w, "bram")
    w.action_declare_hostility(w.agents["ada"], b_fid)
    w.action_declare_hostility(w.agents["ada"], b_fid)   # again
    assert w.faiths[a_fid].hostile_to == [b_fid]         # no duplicate


def test_declare_hostility_non_founder_fails():
    w = _world(["ada", "bram", "cyn"])
    a_fid = _found(w, "ada")
    b_fid = _found(w, "cyn")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])  # bram is a MEMBER of A
    evt = w.action_declare_hostility(w.agents["bram"], b_fid)
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "not founder"
    assert w.faiths[a_fid].hostile_to == []


def test_declare_hostility_self_faith_fails():
    w = _world(["ada"])
    a_fid = _found(w, "ada")
    evt = w.action_declare_hostility(w.agents["ada"], a_fid)
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "self faith"


def test_declare_hostility_unknown_faith_fails():
    w = _world(["ada"])
    _found(w, "ada")
    evt = w.action_declare_hostility(w.agents["ada"], "fth_ghost")
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "unknown faith"


def test_declare_hostility_faith_off_is_inert_fail():
    w = _world(["ada", "bram"], faith=False)
    before = _dumps(w.to_snapshot())
    evt = w.action_declare_hostility(w.agents["ada"], "fth_whatever")
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "faith disabled"
    assert _dumps(w.to_snapshot()) == before


# ── the war casus-belli grievance hook ────────────────────────────────────────

def _two_factions(w: World) -> None:
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0, "members": ["ada"]},
        FB: {"name": "Bram's circle", "founded_tick": 0, "members": ["bram"]},
    }


def test_declare_hostility_feeds_grievance_when_war_on():
    w = _world(["ada", "bram"], war=True)
    a_fid = _found(w, "ada")
    b_fid = _found(w, "bram")
    _two_factions(w)
    w.action_declare_hostility(w.agents["ada"], b_fid)
    # the declaring faction (FA) now holds religious grievance against FB…
    assert a_fid and b_fid                               # both faiths minted
    assert w.grievance_between(FA, FB) == 8              # hostility_grievance default
    assert w.grievance_between(FB, FA) == 0              # DIRECTIONAL
    # and a grievance_accrued event carries the faith reason.
    accrued = next(e for e in w.pending_spawn_events
                   if e["kind"] == "grievance_accrued")
    assert accrued["payload"]["reason"] == "faith_hostility"


def test_declare_hostility_skips_grievance_when_war_off():
    w = _world(["ada", "bram"], war=False)
    _found(w, "ada")
    b_fid = _found(w, "bram")
    _two_factions(w)
    w.action_declare_hostility(w.agents["ada"], b_fid)
    # war OFF ⇒ add_grievance self-gates ⇒ no ledger entry, no grievance event.
    assert w.grievance_between(FA, FB) == 0
    assert not any(e["kind"] == "grievance_accrued"
                   for e in w.pending_spawn_events)


def test_declare_hostility_skips_grievance_when_members_factionless():
    w = _world(["ada", "bram"], war=True)
    _found(w, "ada")
    b_fid = _found(w, "bram")
    # NO factions set up ⇒ both founders are factionless ⇒ nothing to feed.
    w.action_declare_hostility(w.agents["ada"], b_fid)
    assert not any(e["kind"] == "grievance_accrued"
                   for e in w.pending_spawn_events)


def test_grievance_feed_is_deterministic():
    """Two identical worlds feed byte-identical grievance ledgers (no RNG/clock)."""
    def _run() -> dict:
        w = _world(["ada", "bram"], war=True)
        _found(w, "ada")
        b_fid = _found(w, "bram")
        _two_factions(w)
        w.action_declare_hostility(w.agents["ada"], b_fid)
        return dict(w.grievances)
    assert _run() == _run()


# ── round-trip: a hostility + excommunicated + congregations world (EM-155) ────

def _bind(w: World, faith_id: str, *members: str) -> None:
    """Enlist `members` in `faith_id` with a MUTUAL co_religionist web (built
    directly, so no belief-planting side-effect breaks the round-trip — the
    em260 recipe: beliefs are not serialized, only membership/devotion/edges are)."""
    faith = w.faiths[faith_id]
    for m in members:
        w.agents[m].faith_id = faith_id
        w.agents[m].devotion = 30
        if m not in faith.members:
            faith.members.append(m)
    web = [faith.founder_id, *members]
    for a in web:
        for b in web:
            if a == b:
                continue
            rel = w.agents[a].relationships.get(b) or RelationshipState()
            rel.type = "co_religionist"
            rel.trust = 20
            w.agents[a].relationships[b] = rel


def test_hostility_and_excommunicated_world_round_trips_byte_identical():
    w = _world(["ada", "bram", "cyn", "dot"])
    a_fid = _found(w, "ada")
    # ada's faith gains bram + cyn (a 3-member co_religionist web, built directly).
    _bind(w, a_fid, "bram", "cyn")
    # a rival faith for the hostility edge.
    d_fid = _found(w, "dot")
    w.action_declare_hostility(w.agents["ada"], d_fid)
    # congregations cluster the shared-faith web at the round boundary.
    w.recompute_congregations()
    assert w.congregations                                # a congregation formed
    # excommunicate cyn (tears an edge, drops a member).
    w.action_excommunicate(w.agents["ada"], w.agents["cyn"])
    w.recompute_congregations()

    snap = w.to_snapshot()
    assert snap.get("faiths") and w.faiths[a_fid].hostile_to == [d_fid]
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)

# backend/tests/test_em261_founding.py
"""EM-261 — Religion founding + consecrate_faith + temple-as-seat (mirrors
test_em254_governance's canonize coverage + test_em260's faith fixtures).

Three surfaces, all gated on world.faith_enabled() (default OFF):

  * action_found_faith — a REFLEX (zero extra LLM calls): mint a SEEDED faith
    (EM-260), make the founder its sole member with a base devotion, forge the
    Culture join (a canonical kind="faith" meme on faith.meme_id, attached to the
    founder), emit faith_founded. One membership at a time — an already-faithful
    agent is rejected.

  * consecrate_faith — the 70% SUPERMAJORITY "faith → temple seat" bridge that
    EXTENDS the EM-254 canonize_meme lane (a sibling effect, NOT duplicate tally
    code): a passing town-wide vote anchors the faith to an operational temple
    (faith.temple_id + temple.commemorates) and blesses the congregation
    (+temple_buff devotion). A vanished faith / no operational temple ratifies to
    a silent no-op (the demolish convention); concurrent same-faith proposals
    dedup; it is FAITH-gated, not comm-gated.

  * the temple DEVOTION SEAT — _faith_seat_here returns a co-located operational
    temple commemorating the agent's OWN faith (the per-turn buff is EM-262).

Pins the hard laws: the flag-OFF golden (faith disabled ⇒ neither surface acts,
byte-identical control world), NO new tally code (consecrate rides the shared
70% vote path), and determinism (a founded + consecrated world round-trips
byte-identical).
"""
import math

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337)


def _a(aid: str, loc: str = "townhall") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20)


def _world(ids: list[str], faith: bool = True, comm: bool = False) -> World:
    """A town whose citizens all stand in a governance place (so any of them may
    propose AND vote — voting is not location-gated, EM-199). A second social
    place (`temple_sq`) hosts the temple building."""
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="temple_sq", name="Temple Square", x=5, y=5,
                         kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        w.params.faith = {"enabled": True}
    if comm:
        w.params.comm = {"enabled": True}
    return w


def _temple(w: World, bid: str = "bld_temple", place: str = "temple_sq",
            status: str = "operational", commemorates: str | None = None,
            name: str = "Grand Temple") -> Building:
    # An explicit position pins the F1 (EM-268) derive-on-load so the building
    # round-trips byte-identical (a placement-less building is re-placed on
    # restore — orthogonal to EM-261).
    b = Building(id=bid, name=name, kind="temple", location=place,
                 owner_id="public", status=status, health=100,
                 commemorates=commemorates, position=(5.0, 5.0))
    w.buildings[bid] = b
    return b


def _found(w: World, who: str) -> str:
    evt = w.action_found_faith(w.agents[who])
    assert evt["kind"] == "faith_founded", evt
    return evt["payload"]["faith_id"]


def _consecrate(w: World, faith_id: str, voters: list[str], proposer: str = "ada"):
    ok, reason, rule = w.action_propose_rule(
        w.agents[proposer], "consecrate_faith", "bless it", target=faith_id)
    assert ok, reason
    for who in voters:
        w.action_vote(w.agents[who], rule.id, True)
    return rule


# ── action_found_faith ────────────────────────────────────────────────────────

def test_found_faith_mints_faith_and_joins_founder():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    faith = w.faiths[fid]
    ada = w.agents["ada"]
    assert faith.members == ["ada"]                    # founder is sole member
    assert ada.faith_id == fid
    assert ada.devotion > 0                            # a base devotion
    # the Culture join: a canonical kind="faith" meme on faith.meme_id,
    # carried by the founder.
    assert faith.meme_id is not None
    meme = w.memes[faith.meme_id]
    assert meme.kind == "faith"
    assert faith.meme_id in ada.held_memes


def test_found_faith_emits_and_names_the_faith():
    w = _world(["ada"])
    evt = w.action_found_faith(w.agents["ada"])
    assert evt["kind"] == "faith_founded"
    assert evt["actor_id"] == "ada"
    faith = w.faiths[evt["payload"]["faith_id"]]
    assert evt["payload"]["name"] == faith.name
    assert evt["payload"]["deity"] == faith.deity
    assert evt["payload"]["meme_id"] == faith.meme_id


def test_second_found_faith_by_same_agent_is_rejected():
    w = _world(["ada"])
    _found(w, "ada")
    evt = w.action_found_faith(w.agents["ada"])          # already faithful
    assert evt["kind"] == "parse_failure"
    assert "already" in evt["payload"]["error"]


def test_found_faith_rejected_when_faith_disabled():
    w = _world(["ada"], faith=False)
    evt = w.action_found_faith(w.agents["ada"])
    assert evt["kind"] == "parse_failure"
    assert "disabled" in evt["payload"]["error"]
    assert not w.faiths                                  # nothing minted
    assert w.agents["ada"].faith_id is None


def test_found_faith_is_seeded_and_replay_stable():
    """Two identical worlds at the same tick found the byte-identical faith +
    canonical meme (EM-155)."""
    w1, w2 = _world(["ada"]), _world(["ada"])
    w1.tick = w2.tick = 4
    e1 = w1.action_found_faith(w1.agents["ada"])
    e2 = w2.action_found_faith(w2.agents["ada"])
    assert e1["payload"] == e2["payload"]
    f1 = w1.faiths[e1["payload"]["faith_id"]]
    f2 = w2.faiths[e2["payload"]["faith_id"]]
    assert f1.to_dict() == f2.to_dict()


# ── consecrate_faith: propose-time gates ──────────────────────────────────────

def test_consecrate_rejected_when_faith_disabled():
    w = _world(["ada", "bram", "cyn"], faith=False)
    w.faiths["fth_manual01"] = w.mint_faith("ada")      # a faith exists anyway
    fid = next(iter(w.faiths))
    ok, reason, _ = w.action_propose_rule(
        w.agents["ada"], "consecrate_faith", "bless", target=fid)
    assert not ok and "faith disabled" in reason


def test_consecrate_rejects_unknown_faith_id():
    w = _world(["ada", "bram", "cyn"])
    ok, reason, _ = w.action_propose_rule(
        w.agents["ada"], "consecrate_faith", "bless", target="fth_ghost000")
    assert not ok and "real faith id" in reason


def test_consecrate_accepts_a_real_faith():
    w = _world(["ada", "bram", "cyn"])
    fid = _found(w, "ada")
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "consecrate_faith", "bless", target=fid)
    assert ok, reason
    assert rule.payload == {"faith_id": fid}


def test_consecrate_duplicate_per_faith_guard():
    w = _world(["ada", "bram", "cyn"])
    f1 = _found(w, "ada")
    f2 = _found(w, "bram")
    ok, _, _ = w.action_propose_rule(w.agents["ada"], "consecrate_faith", "c1",
                                     target=f1)
    assert ok
    # The SAME faith cannot be double-proposed…
    ok, reason, _ = w.action_propose_rule(w.agents["cyn"], "consecrate_faith",
                                          "c1 again", target=f1)
    assert not ok and "already" in reason
    # …but a DIFFERENT faith may have its own open vote at once.
    ok, reason, _ = w.action_propose_rule(w.agents["bram"], "consecrate_faith",
                                          "c2", target=f2)
    assert ok, reason


# ── consecrate_faith: the town-wide 70% supermajority ─────────────────────────

def test_passing_consecration_anchors_temple_and_emits():
    """Three citizens: ceil(0.7·3) = 3 — all three yes consecrates."""
    w = _world(["ada", "bram", "cyn"])
    temple = _temple(w)
    fid = _found(w, "ada")
    base_dev = w.agents["ada"].devotion
    rule = _consecrate(w, fid, ["ada", "bram", "cyn"])
    assert math.ceil(0.7 * 3) == 3
    assert rule.status == "active" and rule.applied
    faith = w.faiths[fid]
    assert faith.temple_id == temple.id
    assert temple.commemorates == fid                   # reuses Building field
    # the consecration blessing reached the member (reads faith.temple_buff = 5).
    assert w.agents["ada"].devotion == base_dev + 5
    kinds = [e["kind"] for e in w.pending_spawn_events]
    assert "faith_consecrated" in kinds and "temple_consecrated" in kinds
    fc = next(e for e in w.pending_spawn_events if e["kind"] == "faith_consecrated")
    assert fc["actor_id"] == faith.founder_id           # anchors on the founder
    assert fc["actor_type"] == "system"
    assert fc["payload"]["faith_id"] == fid
    assert fc["payload"]["temple_id"] == temple.id


def test_below_70pct_does_not_consecrate():
    """Four citizens: ceil(0.7·4) = 3 — a 2-yes / 2-no split falls short."""
    w = _world(["ada", "bram", "cyn", "dot"])
    temple = _temple(w)
    fid = _found(w, "ada")
    _, _, rule = w.action_propose_rule(w.agents["ada"], "consecrate_faith", "c",
                                       target=fid)
    assert math.ceil(0.7 * 4) == 3
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    w.action_vote(w.agents["cyn"], rule.id, False)
    w.action_vote(w.agents["dot"], rule.id, False)
    assert rule.status == "rejected"
    assert w.faiths[fid].temple_id is None              # NOT anchored
    assert temple.commemorates is None
    assert not any(e["kind"] == "faith_consecrated"
                   for e in w.pending_spawn_events)


def test_vanished_faith_at_activation_is_a_silent_no_op():
    w = _world(["ada", "bram", "cyn"])
    temple = _temple(w)
    fid = _found(w, "ada")
    _, _, rule = w.action_propose_rule(w.agents["ada"], "consecrate_faith", "c",
                                       target=fid)
    del w.faiths[fid]                                   # the faith died mid-vote
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], rule.id, True)
    assert rule.status == "active" and rule.applied     # the vote still applied…
    assert temple.commemorates is None                  # …but the act no-oped
    assert not any(e["kind"] == "faith_consecrated"
                   for e in w.pending_spawn_events)


def test_no_operational_temple_is_a_silent_no_op():
    w = _world(["ada", "bram", "cyn"])
    _temple(w, status="planned")                        # temple not operational
    fid = _found(w, "ada")
    rule = _consecrate(w, fid, ["ada", "bram", "cyn"])
    assert rule.status == "active" and rule.applied     # the vote still applied…
    assert w.faiths[fid].temple_id is None              # …but no seat to anchor
    assert not any(e["kind"] == "faith_consecrated"
                   for e in w.pending_spawn_events)


def test_consecrate_does_not_hijack_another_faiths_temple():
    """One operational temple, two faiths. Faith A claims it; a consecration of
    faith B finds no FREE temple and no-ops (never steals A's seat)."""
    w = _world(["ada", "bram", "cyn"])
    temple = _temple(w)
    fa = _found(w, "ada")
    fb = _found(w, "bram")
    _consecrate(w, fa, ["ada", "bram", "cyn"])
    assert temple.commemorates == fa
    rule_b = _consecrate(w, fb, ["ada", "bram", "cyn"], proposer="bram")
    assert rule_b.applied
    assert temple.commemorates == fa                    # unchanged — A keeps it
    assert w.faiths[fb].temple_id is None


def test_consecrate_is_faith_gated_not_comm_gated():
    """comm OFF but faith ON ⇒ consecrate is admissible and works (proving it
    rides the FAITH gate, not the culture gate)."""
    w = _world(["ada", "bram", "cyn"], faith=True, comm=False)
    assert not w._comm_enabled() and w.faith_enabled()
    _temple(w)
    fid = _found(w, "ada")
    rule = _consecrate(w, fid, ["ada", "bram", "cyn"])
    assert rule.applied and w.faiths[fid].temple_id is not None


def test_second_consecration_is_applied_not_renewed():
    """consecrate_faith is a one-shot act per faith — a SECOND consecration of a
    DIFFERENT faith must activate + apply, never be 'renewed' against the first
    (the canonize_meme / declare_war lesson)."""
    w = _world(["ada", "bram", "cyn"])
    _temple(w, bid="bld_t1", place="temple_sq")
    _temple(w, bid="bld_t2", place="townhall")
    fa = _found(w, "ada")
    fb = _found(w, "bram")
    r1 = _consecrate(w, fa, ["ada", "bram", "cyn"])
    assert r1.applied and w.faiths[fa].temple_id is not None
    r2 = _consecrate(w, fb, ["ada", "bram", "cyn"], proposer="bram")
    assert r2.status == "active" and r2.applied          # NOT "renewed"
    assert w.faiths[fb].temple_id is not None


# ── the temple DEVOTION SEAT (_faith_seat_here) ───────────────────────────────

def _seated_world():
    w = _world(["ada", "bram", "cyn"])
    temple = _temple(w)                                 # at temple_sq
    fid = _found(w, "ada")
    _consecrate(w, fid, ["ada", "bram", "cyn"])
    return w, temple, fid


def test_faith_seat_here_returns_temple_for_co_located_member():
    w, temple, fid = _seated_world()
    w.agents["ada"].location = "temple_sq"              # a member, co-located
    seat = w._faith_seat_here(w.agents["ada"])
    assert seat is not None and seat.id == temple.id


def test_faith_seat_none_for_faithless_or_wrong_faith():
    w, temple, fid = _seated_world()
    # bram is faithless — no seat even standing on it.
    w.agents["bram"].location = "temple_sq"
    assert w._faith_seat_here(w.agents["bram"]) is None
    # cyn belongs to a DIFFERENT faith — the temple commemorates ada's faith.
    w.agents["cyn"].faith_id = "fth_other000"
    w.agents["cyn"].location = "temple_sq"
    assert w._faith_seat_here(w.agents["cyn"]) is None


def test_faith_seat_none_when_not_co_located():
    w, temple, fid = _seated_world()
    w.agents["ada"].location = "townhall"              # member, elsewhere
    assert w._faith_seat_here(w.agents["ada"]) is None


def test_faith_seat_none_when_temple_not_operational():
    w, temple, fid = _seated_world()
    temple.status = "damaged"                          # no longer operational
    w.agents["ada"].location = "temple_sq"
    assert w._faith_seat_here(w.agents["ada"]) is None


# ── golden: faith-off control + a founded+consecrated round-trip ──────────────

def test_faith_off_is_byte_identical_control():
    """faith disabled ⇒ found_faith no-ops, no faith minted, no new snapshot key
    vs a plain world (the em260 golden's spirit)."""
    a = World(params=_params(),
              places=[PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                                 kind="governance")],
              agents=[_a("ada")])
    b = World(params=_params(),
              places=[PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                                 kind="governance")],
              agents=[_a("ada")])
    # a faith-off world cannot found — snapshot stays free of faith keys.
    a.action_found_faith(a.agents["ada"])
    assert a.to_snapshot() == b.to_snapshot()
    assert "faiths" not in a.to_snapshot()


def test_founded_consecrated_world_round_trips_byte_identical():
    w, temple, fid = _seated_world()
    snap1 = w.to_snapshot()
    # the founded + consecrated state is all in the snapshot.
    assert snap1["faiths"][fid]["temple_id"] == temple.id
    restored = World.from_snapshot(snap1, params=_params())
    assert restored.faiths[fid].temple_id == temple.id
    assert restored.buildings[temple.id].commemorates == fid
    assert restored.agents["ada"].faith_id == fid
    snap2 = restored.to_snapshot()
    assert snap1 == snap2                               # byte-identical

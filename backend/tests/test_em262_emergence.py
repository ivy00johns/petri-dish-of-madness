# backend/tests/test_em262_emergence.py
"""EM-262 — Religion emergence (mirrors test_em261_founding + test_em253_lifecycle
+ test_em256_determinism). Four surfaces, ALL gated on world.faith_enabled()
(default OFF):

  * action_proselytize — a REFLEX, TRUST-POSITIVE conversion channel (the
    spread_rumor recipe): plant the faith's pitch via the shared _plant_belief seam
    (NO crime, NO trust crater), and on a SEEDED roll convert a co-located FAITHLESS
    target — set faith_id, join faith.members, bump devotion, seal a MUTUAL
    co_religionist edge, emit proselytized + faith_joined. A same-faith target is a
    gentle no-op; a different-faith target always resists (no forced steal).

  * action_worship — a REFLEX temple buff (action_work's buff-at-place clone): at a
    co-located consecrated temple seat (_faith_seat_here), a small energy buff +
    devotion += temple_buff; no seat ⇒ a clear fail.

  * recompute_congregations — the round-boundary Religion subsystem: shared-faith
    members cluster into cng_ congregations (the shared _recompute_groups clusterer),
    devotion cools by devotion_decay, and a persistent schism forks.

  * DETERMINISTIC schism forking — a faith whose co_religionist web tears into 2+
    components for schism_grace rounds forks the splinter into a parent-linked child.

Pins the hard laws: the flag-OFF golden (byte-identical control), determinism (a
mid-schism world round-trips byte-identical), and the round-order invariant
(factions → diffuse_culture → congregations → war → age).
"""
from petridish.engine.world import (
    World, AgentState, PlaceState, Building, RelationshipState,
)
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337)


def _a(aid: str, loc: str = "townhall") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20)


def _world(ids: list[str], faith=True, faith_cfg: dict | None = None) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="temple_sq", name="Temple Square", x=5, y=5,
                         kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if faith:
        cfg = {"enabled": True}
        if faith_cfg:
            cfg.update(faith_cfg)
        w.params.faith = cfg
    return w


def _temple(w: World, bid="bld_temple", place="temple_sq", status="operational",
            commemorates=None, name="Grand Temple") -> Building:
    b = Building(id=bid, name=name, kind="temple", location=place,
                 owner_id="public", status=status, health=100,
                 commemorates=commemorates, position=(5.0, 5.0))
    w.buildings[bid] = b
    return b


def _found(w: World, who: str) -> str:
    evt = w.action_found_faith(w.agents[who])
    assert evt["kind"] == "faith_founded", evt
    return evt["payload"]["faith_id"]


# ── action_proselytize: conversion ────────────────────────────────────────────

def test_proselytize_converts_faithless_co_located_target():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 1.0})
    fid = _found(w, "ada")
    result = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    # a conversion is a _multi chain: proselytized + faith_joined.
    assert "_multi" in result
    kinds = [e["kind"] for e in result["_multi"]]
    assert kinds == ["proselytized", "faith_joined"]
    bram = w.agents["bram"]
    assert bram.faith_id == fid                        # adopted the faith
    assert "bram" in w.faiths[fid].members             # joined the roster
    assert bram.devotion > 0                           # devotion bumped
    # a MUTUAL co_religionist edge, trust-positive (never cratered).
    rel_ab = w.agents["ada"].relationships["bram"]
    rel_ba = bram.relationships["ada"]
    assert rel_ab.type == "co_religionist" and rel_ba.type == "co_religionist"
    assert rel_ab.trust >= 0 and rel_ba.trust >= 0
    # the pitch was planted in the target's beliefs (the shared seam).
    assert any("Ada told me:" in b for b in bram.beliefs)


def test_proselytize_devotion_uses_devotion_base():
    w = _world(["ada", "bram"],
               faith_cfg={"conversion_chance": 1.0, "devotion_base": 30})
    _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert w.agents["bram"].devotion == 30


def test_proselytize_resistance_is_zero_trust_damage():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 0.0})
    fid = _found(w, "ada")
    result = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert result["kind"] == "proselytize_resisted"
    bram = w.agents["bram"]
    assert bram.faith_id is None                        # NOT converted
    assert "bram" not in w.faiths[fid].members
    # ZERO trust interaction — no relationship created either way.
    assert w.agents["ada"].relationships.get("bram") is None
    assert bram.relationships.get("ada") is None
    # …but the sermon (a belief) still landed — proselytize always plants.
    assert any("Ada told me:" in b for b in bram.beliefs)


def test_proselytize_not_co_located_fails():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 1.0})
    _found(w, "ada")
    w.agents["bram"].location = "temple_sq"             # elsewhere
    evt = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "parse_failure"
    assert "co-located" in evt["payload"]["error"]
    assert w.agents["bram"].faith_id is None


def test_proselytize_by_faithless_actor_fails():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 1.0})
    # ada never founded a faith — she has nothing to preach.
    evt = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "parse_failure"
    assert "faithless" in evt["payload"]["error"] or "no faith" in evt["text"]


def test_proselytize_same_faith_is_gentle_no_op():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 1.0})
    fid = _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])   # bram converts
    bram_dev = w.agents["bram"].devotion
    members_before = list(w.faiths[fid].members)
    evt = w.action_proselytize(w.agents["ada"], w.agents["bram"])  # already same
    assert evt["kind"] == "proselytized"
    assert evt["payload"].get("already") is True
    assert "_multi" not in evt                          # NO re-join chain
    assert w.faiths[fid].members == members_before      # no duplicate join
    assert w.agents["bram"].devotion == bram_dev + 1    # a gentle nudge


def test_proselytize_different_faith_target_resists():
    w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 1.0})
    fa = _found(w, "ada")
    # bram belongs to a different faith already.
    w.agents["bram"].faith_id = "fth_other000"
    evt = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "proselytize_resisted"        # no forced steal
    assert w.agents["bram"].faith_id == "fth_other000"  # unchanged
    assert "bram" not in w.faiths[fa].members


def test_proselytize_rejected_when_faith_disabled():
    w = _world(["ada", "bram"], faith=False)
    w.faiths["fth_manual"] = w.mint_faith("ada")        # a faith exists anyway
    w.agents["ada"].faith_id = "fth_manual"
    evt = w.action_proselytize(w.agents["ada"], w.agents["bram"])
    assert evt["kind"] == "parse_failure"
    assert "disabled" in evt["payload"]["error"]


def test_proselytize_is_seeded_and_replay_stable():
    """Two identical worlds at the same tick get the byte-identical roll →
    identical convert/resist outcome (EM-155)."""
    outs = []
    for _ in range(2):
        w = _world(["ada", "bram"], faith_cfg={"conversion_chance": 0.5})
        w.tick = 7
        _found(w, "ada")
        r = w.action_proselytize(w.agents["ada"], w.agents["bram"])
        outs.append((("_multi" in r), r.get("kind"), w.agents["bram"].faith_id))
    assert outs[0] == outs[1]


# ── action_worship ────────────────────────────────────────────────────────────

def _seated_world():
    """A founded + consecrated faith with its temple at temple_sq (the EM-261
    consecration path), the member standing on it."""
    w = _world(["ada", "bram", "cyn"])
    temple = _temple(w)
    fid = _found(w, "ada")
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "consecrate_faith", "bless", target=fid)
    assert ok, reason
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], rule.id, True)
    assert w.faiths[fid].temple_id == temple.id
    w.agents["ada"].location = "temple_sq"
    return w, temple, fid


def test_worship_at_seat_buffs_devotion_and_energy():
    w, temple, fid = _seated_world()
    ada = w.agents["ada"]
    dev0, en0 = ada.devotion, ada.energy
    evt = w.action_worship(ada)
    assert evt["kind"] == "worshipped"
    assert evt["payload"]["temple_id"] == temple.id
    assert ada.devotion == min(100, dev0 + 5)          # temple_buff default 5
    assert ada.energy == min(100.0, en0 + 5)           # small energy buff
    assert ada.devotion <= 100                          # clamped


def test_worship_without_seat_fails():
    w, temple, fid = _seated_world()
    w.agents["ada"].location = "townhall"              # member, but no temple here
    evt = w.action_worship(w.agents["ada"])
    assert evt["kind"] == "parse_failure"
    assert "no seat" in evt["payload"]["error"]


def test_worship_at_wrong_faiths_temple_fails():
    w, temple, fid = _seated_world()
    # cyn is faithless — no seat for her even standing on the temple.
    w.agents["cyn"].location = "temple_sq"
    evt = w.action_worship(w.agents["cyn"])
    assert evt["kind"] == "parse_failure"
    assert "no seat" in evt["payload"]["error"]


def test_worship_rejected_when_faith_disabled():
    w = _world(["ada"], faith=False)
    evt = w.action_worship(w.agents["ada"])
    assert evt["kind"] == "parse_failure"
    assert "disabled" in evt["payload"]["error"]


# ── recompute_congregations ───────────────────────────────────────────────────

def _join_faith(w: World, aid: str, fid: str):
    """Directly enroll a living agent in a faith (bypasses the roll for a
    deterministic congregation fixture)."""
    w.agents[aid].faith_id = fid
    if aid not in w.faiths[fid].members:
        w.faiths[fid].members.append(aid)


def test_same_faith_members_cluster_into_a_congregation():
    w = _world(["ada", "bram", "cyn"])
    fid = _found(w, "ada")
    _join_faith(w, "bram", fid)                         # two same-faith members
    events = w.recompute_congregations()
    formed = [e for e in events if e["kind"] == "congregation_formed"]
    assert len(formed) == 1
    cng = formed[0]
    assert cng["payload"]["congregation_id"].startswith("cng_")
    assert cng["payload"]["congregation_id"] in w.congregations
    members = w.congregations[cng["payload"]["congregation_id"]]["members"]
    assert set(members) == {"ada", "bram"}


def test_congregation_membership_diffs_emit_joined_and_left():
    w = _world(["ada", "bram", "cyn"])
    fid = _found(w, "ada")
    _join_faith(w, "bram", fid)
    w.recompute_congregations()                        # forms {ada, bram}
    # cyn joins the same faith → a joined diff.
    _join_faith(w, "cyn", fid)
    events = w.recompute_congregations()
    assert any(e["kind"] == "congregation_joined" and e["actor_id"] == "cyn"
               for e in events)
    # bram leaves the faith → a left diff.
    w.agents["bram"].faith_id = None
    w.faiths[fid].members = [m for m in w.faiths[fid].members if m != "bram"]
    events = w.recompute_congregations()
    assert any(e["kind"] == "congregation_left" and e["actor_id"] == "bram"
               for e in events)


def test_congregation_dissolves_when_it_drops_below_min_size():
    w = _world(["ada", "bram"])
    fid = _found(w, "ada")
    _join_faith(w, "bram", fid)
    w.recompute_congregations()
    assert w.congregations                              # a congregation exists
    # bram leaves → only ada left, below min_size 2 → dissolve.
    w.agents["bram"].faith_id = None
    w.faiths[fid].members = ["ada"]
    events = w.recompute_congregations()
    assert any(e["kind"] == "congregation_dissolved" for e in events)
    assert not w.congregations


def test_recompute_congregations_is_deterministic_byte_identical():
    def _built():
        w = _world(["ada", "bram", "cyn"])
        w.tick = 3
        fid = _found(w, "ada")
        _join_faith(w, "bram", fid)
        _join_faith(w, "cyn", fid)
        events = w.recompute_congregations()
        return w.congregations, events
    c1, e1 = _built()
    c2, e2 = _built()
    assert c1 == c2
    assert e1 == e2


def test_devotion_decay_applied_per_round():
    w = _world(["ada", "bram"], faith_cfg={"devotion_decay": 3})
    fid = _found(w, "ada")           # ada.devotion = devotion_base (10)
    _join_faith(w, "bram", fid)
    w.agents["bram"].devotion = 2
    w.recompute_congregations()
    assert w.agents["ada"].devotion == 7               # 10 - 3
    assert w.agents["bram"].devotion == 0              # 2 - 3 clamped >= 0


def test_recompute_congregations_no_op_when_faith_disabled():
    w = _world(["ada", "bram"], faith=False)
    w.faiths["fth_manual"] = w.mint_faith("ada")
    w.agents["ada"].faith_id = "fth_manual"
    w.agents["bram"].faith_id = "fth_manual"
    events = w.recompute_congregations()
    assert events == []
    assert w.congregations == {}                       # nothing written


# ── deterministic schism forking ──────────────────────────────────────────────

def _split_faith_world(grace=2, threshold=1):
    """ada founds a faith and converts bram + cyn (co_religionist edges ada↔bram,
    ada↔cyn). Killing ada tears the web into {bram} | {cyn} — a divergence."""
    w = _world(["ada", "bram", "cyn"],
               faith_cfg={"conversion_chance": 1.0, "schism_grace": grace,
                          "schism_threshold": threshold, "devotion_decay": 0})
    fid = _found(w, "ada")
    w.action_proselytize(w.agents["ada"], w.agents["bram"])
    w.action_proselytize(w.agents["ada"], w.agents["cyn"])
    assert set(w.faiths[fid].members) == {"ada", "bram", "cyn"}
    w.agents["ada"].alive = False                      # the evangelist dies
    return w, fid


def test_schism_forks_splinter_after_grace_elapses():
    w, fid = _split_faith_world(grace=2, threshold=1)
    w.tick = 10
    assert w._advance_schisms() == []                  # first sight → latch only
    assert w.schism_pending.get(fid) == 10
    w.tick = 11
    assert w._advance_schisms() == []                  # still within grace
    w.tick = 12                                         # tick - first = 2 = grace
    events = w._advance_schisms()
    assert len(events) == 1 and events[0]["kind"] == "faith_schism"
    child_id = events[0]["payload"]["faith_id"]
    child = w.faiths[child_id]
    assert child.parent_id == fid                      # parent-linked
    # the splinter (the higher-lowest-id component = {cyn}) forked; bram keeps parent.
    assert child.members == ["cyn"]
    assert w.agents["cyn"].faith_id == child_id
    assert w.agents["bram"].faith_id == fid
    assert "cyn" not in w.faiths[fid].members
    assert fid not in w.schism_pending                 # latch cleared on fork


def test_schism_does_not_fork_before_grace():
    w, fid = _split_faith_world(grace=5, threshold=1)
    w.tick = 10
    w._advance_schisms()                               # latch set at 10
    w.tick = 14                                         # 14 - 10 = 4 < 5
    events = w._advance_schisms()
    assert events == []
    assert w.agents["cyn"].faith_id == fid             # NOT forked yet
    assert fid in w.schism_pending


def test_schism_min_splinter_size_gate():
    """A splinter below schism_threshold never even registers as pending."""
    w, fid = _split_faith_world(grace=1, threshold=5)  # splinter of 1 < 5
    w.tick = 10
    w._advance_schisms()
    assert w.schism_pending == {}                       # never latched
    w.tick = 20
    assert w._advance_schisms() == []                   # never forks


def test_schism_latch_clears_when_faith_recoalesces():
    w, fid = _split_faith_world(grace=5, threshold=1)
    w.tick = 10
    w._advance_schisms()
    assert fid in w.schism_pending
    # ada is revived → the web reconnects (ada↔bram, ada↔cyn) into ONE component.
    w.agents["ada"].alive = True
    w.tick = 11
    assert w._advance_schisms() == []
    assert fid not in w.schism_pending                 # latch cleared


def test_schism_is_deterministic_across_two_worlds():
    def _run():
        w, fid = _split_faith_world(grace=1, threshold=1)
        w.tick = 5
        w._advance_schisms()                           # latch at 5
        w.tick = 6                                      # 6 - 5 = 1 = grace
        events = w._advance_schisms()
        return events, w.to_snapshot()
    e1, s1 = _run()
    e2, s2 = _run()
    assert e1 == e2
    assert s1 == s2


# ── round-order invariant ─────────────────────────────────────────────────────

def test_round_start_chain_factions_diffuse_congregations_war_age():
    """The full canonical Wave-O chain: recompute_factions → diffuse_culture →
    recompute_congregations → advance_war → age_agents."""
    w = _world(["ada"])
    calls: list[str] = []
    orig_rf, orig_dc, orig_rc, orig_aw, orig_age = (
        w.recompute_factions, w.diffuse_culture, w.recompute_congregations,
        w.advance_war, w.age_agents)
    w.recompute_factions = lambda: (calls.append("recompute_factions"), orig_rf())[1]
    w.diffuse_culture = lambda: (calls.append("diffuse_culture"), orig_dc())[1]
    w.recompute_congregations = (
        lambda: (calls.append("recompute_congregations"), orig_rc())[1])
    w.advance_war = lambda: (calls.append("advance_war"), orig_aw())[1]
    w.age_agents = lambda pre: (calls.append("age_agents"), orig_age(pre))[1]

    w._apply_round_start()

    for name in ("recompute_factions", "diffuse_culture", "recompute_congregations",
                 "advance_war", "age_agents"):
        assert name in calls
    assert (calls.index("recompute_factions")
            < calls.index("diffuse_culture")
            < calls.index("recompute_congregations")
            < calls.index("advance_war")
            < calls.index("age_agents"))


# ── golden: faith-off control + a mid-schism round-trip ───────────────────────

def test_faith_off_is_byte_identical_control():
    """faith disabled ⇒ recompute_congregations no-ops, no religion snapshot key
    vs a plain world (the em260 golden's spirit)."""
    def _plain() -> World:
        return World(params=_params(),
                     places=[PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                                        kind="governance")],
                     agents=[_a("ada")])
    a, b = _plain(), _plain()
    a.recompute_congregations()                        # a faith-off no-op
    a._advance_schisms()
    assert a.to_snapshot() == b.to_snapshot()
    snap = a.to_snapshot()
    assert "congregations" not in snap and "schism_pending" not in snap


def _seal_co_religionist(w, a_id, b_id):
    """Directly seal a mutual co_religionist edge (the proselytize seal, WITHOUT
    its transient belief-plant — beliefs are deliberately NOT serialized, an
    orthogonal pre-existing property, so a round-trip fixture avoids them)."""
    for a, b in ((a_id, b_id), (b_id, a_id)):
        rel = RelationshipState()
        rel.type = "co_religionist"
        rel.trust = 20
        rel.since_tick = w.tick
        w.agents[a].relationships[b] = rel


def test_mid_schism_world_round_trips_byte_identical():
    """A world with converts (co_religionist edges), a congregation, AND a pending
    schism latch round-trips byte-identical through snapshot → restore → snapshot."""
    w = _world(["ada", "bram", "cyn"],
               faith_cfg={"schism_grace": 9, "schism_threshold": 1,
                          "devotion_decay": 0})
    fid = _found(w, "ada")
    for who in ("bram", "cyn"):
        _join_faith(w, who, fid)                       # enroll (no belief-plant)
        _seal_co_religionist(w, "ada", who)            # the conversion web
    w.tick = 4
    w.recompute_congregations()                        # writes self.congregations
    w.agents["ada"].alive = False                      # tear the web
    w.tick = 5
    w._advance_schisms()                               # sets schism_pending
    assert w.congregations and w.schism_pending        # both non-empty
    snap1 = w.to_snapshot()
    assert "congregations" in snap1 and "schism_pending" in snap1
    restored = World.from_snapshot(snap1, params=_params())
    assert restored.congregations == w.congregations
    assert restored.schism_pending == w.schism_pending
    snap2 = restored.to_snapshot()
    assert snap1 == snap2                               # byte-identical

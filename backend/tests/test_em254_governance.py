# backend/tests/test_em254_governance.py
"""EM-254 — the culture governance lane (mirrors test_em257_governance's
declare_war coverage + test_em253_lifecycle's culture fixtures).

Two governance effects, both gated on world.comm.enabled (default OFF):

  * canonize_meme — the 70% SUPERMAJORITY "popular meme → institution" bridge.
    A one-shot payload-carrying ACT (like declare_war / trial — reuses the vote
    tally, ZERO new tally code): a passing town-wide 70% vote sets
    town_motif_ref and emits meme_canonized. A vanished target ratifies to a
    silent no-op (the demolish convention); concurrent same-meme proposals dedup.

  * ban_gossip — a simple-majority AGREEMENT-GATE rule (ban_stealing's twin): a
    persistent active rule (no on-ratify side effect) that BLOCKS spread_rumor
    while active. Simple majority — NOT the 70% lane.

Pins the hard laws: the flag-OFF golden (comm disabled ⇒ neither effect is an
admissible proposal, no new menu lines, byte-identical control world), NO new
tally code (both ride the shared _evaluate_rule path), and determinism (a
ban_gossip + canonized-meme world round-trips byte-identical).
"""
import math

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import (
    _assemble_context, _validate_world, TOOL_REGISTRY,
)


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337)


def _a(aid: str, loc: str = "townhall") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20)


def _world(ids: list[str], comm: bool = True) -> World:
    """A town whose citizens all stand in a governance place (so any of them may
    propose AND vote — voting is not location-gated, EM-199)."""
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance"),
              PlaceState(id="plaza", name="Plaza", x=5, y=5, kind="social")]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if comm:
        w.params.comm = {"enabled": True}
    return w


def _meme(w: World, text: str = "the fox motif", origin: str = "ada"):
    return w.mint_meme("idea", text, origin)


# ── propose-time gates ────────────────────────────────────────────────────────

def test_canonize_meme_rejected_when_comm_disabled():
    w = _world(["ada", "bram", "cyn"], comm=False)
    m = _meme(w)                                       # mint works even comm-off
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "canonize_meme",
                                          "our canon", target=m.id)
    assert not ok and "comm disabled" in reason


def test_ban_gossip_rejected_when_comm_disabled():
    w = _world(["ada", "bram", "cyn"], comm=False)
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "ban_gossip",
                                          "no whispering")
    assert not ok and "comm disabled" in reason


def test_canonize_meme_rejects_unknown_meme_id():
    w = _world(["ada", "bram", "cyn"])
    ok, reason, _ = w.action_propose_rule(w.agents["ada"], "canonize_meme",
                                          "our canon", target="mem_ghost")
    assert not ok and "real meme id" in reason


def test_canonize_meme_accepts_a_real_meme():
    w = _world(["ada", "bram", "cyn"])
    m = _meme(w)
    ok, reason, rule = w.action_propose_rule(w.agents["ada"], "canonize_meme",
                                             "our canon", target=m.id)
    assert ok, reason
    assert rule.payload == {"meme_id": m.id}


def test_ban_gossip_accepts_with_no_payload_when_comm_on():
    w = _world(["ada", "bram", "cyn"])
    ok, reason, rule = w.action_propose_rule(w.agents["ada"], "ban_gossip",
                                             "no whispering")
    assert ok, reason
    assert rule.effect == "ban_gossip"


def test_canonize_meme_duplicate_per_meme_guard():
    w = _world(["ada", "bram", "cyn"])
    m1, m2 = _meme(w, "one"), _meme(w, "two")
    ok, _, _ = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c1",
                                     target=m1.id)
    assert ok
    # The SAME meme cannot be double-proposed…
    ok, reason, _ = w.action_propose_rule(w.agents["bram"], "canonize_meme",
                                          "c1 again", target=m1.id)
    assert not ok and "already" in reason
    # …but a DIFFERENT meme may have its own open vote at once.
    ok, reason, _ = w.action_propose_rule(w.agents["cyn"], "canonize_meme",
                                          "c2", target=m2.id)
    assert ok, reason


# ── canonize_meme: the town-wide 70% supermajority ────────────────────────────

def test_passing_canonization_sets_motif_and_emits():
    """Three citizens: ceil(0.7·3) = 3 — all three yes canonizes."""
    w = _world(["ada", "bram", "cyn"])
    m = _meme(w, "plant a garden", origin="bram")
    _, _, rule = w.action_propose_rule(w.agents["ada"], "canonize_meme",
                                       "our canon", target=m.id)
    assert math.ceil(0.7 * 3) == 3
    assert w.action_vote(w.agents["ada"], rule.id, True) == (True, "ok", None)
    assert w.action_vote(w.agents["bram"], rule.id, True) == (True, "ok", None)
    ok, _, status = w.action_vote(w.agents["cyn"], rule.id, True)
    assert ok and status == "active"
    assert rule.applied
    assert w.town_motif_ref == m.id
    evt = next(e for e in w.pending_spawn_events if e["kind"] == "meme_canonized")
    assert evt["actor_id"] == "bram"                   # the meme's origin_agent_id
    assert evt["actor_type"] == "system"
    assert evt["payload"] == {"meme_id": m.id, "proposal_id": rule.id}


def test_below_70pct_does_not_canonize():
    """Four citizens: ceil(0.7·4) = 3 — a 2-yes / 2-no split falls short."""
    w = _world(["ada", "bram", "cyn", "dot"])
    m = _meme(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c",
                                       target=m.id)
    assert math.ceil(0.7 * 4) == 3
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    w.action_vote(w.agents["cyn"], rule.id, False)
    ok, _, status = w.action_vote(w.agents["dot"], rule.id, False)
    assert status == "rejected"
    assert w.town_motif_ref is None                    # NOT canonized
    assert not any(e["kind"] == "meme_canonized"
                   for e in w.pending_spawn_events)


def test_vanished_meme_at_activation_is_a_silent_no_op():
    w = _world(["ada", "bram", "cyn"])
    m = _meme(w)
    _, _, rule = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c",
                                       target=m.id)
    del w.memes[m.id]                                  # the meme died mid-vote
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], rule.id, True)
    assert rule.status == "active" and rule.applied    # the vote still applied…
    assert w.town_motif_ref is None                    # …but the act no-oped
    assert not any(e["kind"] == "meme_canonized"
                   for e in w.pending_spawn_events)


def test_second_canonization_is_applied_not_renewed():
    """canonize_meme is a one-shot act per meme — a SECOND canonization must
    activate + apply (re-setting the motif), never be 'renewed' against the
    first (the declare_war / demolish lesson)."""
    w = _world(["ada", "bram", "cyn"])
    m1, m2 = _meme(w, "one", origin="ada"), _meme(w, "two", origin="cyn")
    _, _, r1 = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c1",
                                     target=m1.id)
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], r1.id, True)
    assert w.town_motif_ref == m1.id
    _, _, r2 = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c2",
                                     target=m2.id)
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], r2.id, True)
    assert r2.status == "active" and r2.applied        # NOT "renewed"
    assert w.town_motif_ref == m2.id                   # the motif moved


# ── ban_gossip: the simple-majority agreement-gate ────────────────────────────

def test_ban_gossip_passes_on_simple_majority_not_70pct():
    """Three citizens: simple majority needs 2 yes (> 3//2); the 70% lane would
    need 3. Two yes activates ⇒ ban_gossip is NOT on the supermajority lane."""
    w = _world(["ada", "bram", "cyn"])
    _, _, rule = w.action_propose_rule(w.agents["ada"], "ban_gossip", "hush")
    assert w.action_vote(w.agents["ada"], rule.id, True) == (True, "ok", None)
    ok, _, status = w.action_vote(w.agents["bram"], rule.id, True)
    assert ok and status == "active"                   # 2 of 3 — below 70%
    assert 2 < math.ceil(0.7 * 3)
    assert w.has_active_rule("ban_gossip")


def test_active_ban_gossip_blocks_spread_rumor_in_the_world():
    # Both stand at the town hall (a governance place ⇒ they can propose there)
    # AND are co-located (so spread_rumor is reachable).
    w = _world(["ada", "bram"])
    # Sanity: with no ban, a rumor spreads (comm on, co-located). A drift returns
    # a {"_multi": [...]} chain (no top-level "kind") — check that FIRST.
    ok_evt = w.action_spread_rumor(w.agents["ada"], w.agents["bram"], "psst")
    assert "_multi" in ok_evt or ok_evt["kind"] == "rumor_spread"
    # Activate the ban directly (the vote path is proven above).
    ok, _, rule = w.action_propose_rule(w.agents["ada"], "ban_gossip", "hush")
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    assert w.has_active_rule("ban_gossip")
    evt = w.action_spread_rumor(w.agents["ada"], w.agents["bram"], "psst")
    assert evt["kind"] == "parse_failure"
    assert "ban_gossip" in evt["payload"]["error"]


def test_active_ban_gossip_hides_spread_rumor_from_the_menu_and_validator():
    # Co-located at the town hall (governance place) so spread_rumor is offered
    # AND ban_gossip is proposable in the one spot.
    w = _world(["ada", "bram"])

    def _sys(agent):
        msgs = _assemble_context(agent, w, [], w.params)
        return next(m["content"] for m in msgs if m["role"] == "system")

    # Before the ban: comm on + co-located ⇒ the verb is offered.
    assert "spread_rumor" in _sys(w.agents["ada"])
    # Ratify the ban.
    ok, _, rule = w.action_propose_rule(w.agents["ada"], "ban_gossip", "hush")
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    assert w.has_active_rule("ban_gossip")
    # The menu no longer names it…
    assert "spread_rumor" not in _sys(w.agents["ada"])
    # …and the validator rejects an attempt anyway.
    err = _validate_world(
        {"action": "spread_rumor", "args": {"target": "Bram"}},
        w.agents["ada"], w)
    assert err is not None and "ban_gossip" in err


# ── comm-off golden: no admissible effect, no menu trace, byte-identical ───────

def _propose_line(sys_text: str) -> str:
    return next((l for l in sys_text.split("\n")
                 if l.strip().startswith("propose_rule")), "")


def _sys_of(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def test_comm_off_effects_are_invalid_proposals_at_the_runtime_gate():
    w = _world(["ada", "bram", "cyn"], comm=False)
    for effect, extra in (("canonize_meme", {"meme_id": "mem_x"}),
                          ("ban_gossip", {})):
        err = _validate_world(
            {"action": "propose_rule",
             "args": {"effect": effect, "text": "t", **extra}},
            w.agents["ada"], w)
        assert err is not None and "invalid effect" in err
        assert effect not in err.split("Valid:")[1]    # not listed as valid


def test_comm_off_menu_never_names_the_culture_effects():
    w = _world(["ada", "bram", "cyn"], comm=False)
    line = _propose_line(_sys_of(w.agents["ada"], w))
    assert line                                        # governance place ⇒ a line
    assert "canonize_meme" not in line
    assert "ban_gossip" not in line


def test_comm_off_prompt_is_byte_identical_control():
    a = _sys_of(_world(["ada", "bram", "cyn"], comm=False).agents["ada"],
                _world(["ada", "bram", "cyn"], comm=False))
    b = _sys_of(_world(["ada", "bram", "cyn"], comm=False).agents["ada"],
                _world(["ada", "bram", "cyn"], comm=False))
    assert a == b


def test_comm_on_menu_surfaces_the_culture_effects():
    w = _world(["ada", "bram", "cyn"])
    _meme(w)                                           # a canonizable target
    line = _propose_line(_sys_of(w.agents["ada"], w))
    assert "|canonize_meme" in line
    assert "|ban_gossip" in line


# ── determinism: a ban_gossip + canonized-meme world round-trips ──────────────

def _governed_world() -> World:
    """A world carrying an ACTIVE ban_gossip rule AND a canonized meme (motif +
    the meme registry) — everything EM-254 persists, for the round-trip golden."""
    w = _world(["ada", "bram", "cyn"])
    m = _meme(w, "the shared canon", origin="ada")
    _, _, rc = w.action_propose_rule(w.agents["ada"], "canonize_meme", "c",
                                     target=m.id)
    for who in ("ada", "bram", "cyn"):
        w.action_vote(w.agents[who], rc.id, True)
    _, _, rb = w.action_propose_rule(w.agents["ada"], "ban_gossip", "hush")
    w.action_vote(w.agents["ada"], rb.id, True)
    w.action_vote(w.agents["bram"], rb.id, True)
    assert w.town_motif_ref == m.id and w.has_active_rule("ban_gossip")
    return w


def test_governed_world_round_trips_byte_identical():
    w = _governed_world()
    snap1 = w.to_snapshot()
    assert snap1["town_motif_ref"] == w.town_motif_ref

    restored = World.from_snapshot(snap1, params=_params())
    assert restored.town_motif_ref == w.town_motif_ref
    assert restored.has_active_rule("ban_gossip")

    snap2 = restored.to_snapshot()
    assert snap1 == snap2                              # byte-identical

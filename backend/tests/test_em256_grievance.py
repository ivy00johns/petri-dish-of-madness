# backend/tests/test_em256_grievance.py
"""EM-256 — the grievance subsystem (the group-scope notoriety analog).

Mirrors the test_em240_* split for the crime substrate it clones:
  * add_grievance — the ONE public seam (Religion/Culture feed it later):
    directional accrual, 0..100 clamp, the grievance_accrued event, and the
    war-disabled no-op (golden-safe).
  * _register_war_act folded into _register_crime — ordinary cross-faction
    crime feeds casus belli (base per act + escalation per witness); same-
    faction / factionless crime feeds nothing (EM-240's individual story).
  * advance_war grievance decay — cooled-to-zero entries are DROPPED (the
    ledger never carries dead heat).
  * the _apply_round_start chain order invariant: recompute_factions →
    advance_war → age_agents (the plan's contended seam; diffuse_culture /
    recompute_congregations slots are reserved BETWEEN factions and war).
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, loc: str = "plaza", **kw) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def _world(agents: list[AgentState], war: bool = True) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
              PlaceState(id="field", name="Field", x=5, y=5, kind="nature")]
    w = World(params=_params(), places=places, agents=agents)
    if war:
        w.params.war = {"enabled": True}
    return w


def _two_factions(w: World) -> None:
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }


# ── add_grievance: the one public seam ───────────────────────────────────────

def test_add_grievance_accrues_directionally_and_emits():
    w = _world([_a("ada"), _a("dot")])
    _two_factions(w)
    total = w.add_grievance(FA, FB, 12, "steal")
    assert total == 12
    assert w.grievance_between(FA, FB) == 12
    assert w.grievance_between(FB, FA) == 0          # DIRECTIONAL — not mirrored
    evt = w.pending_spawn_events[-1]
    assert evt["kind"] == "grievance_accrued"
    assert evt["actor_id"] == "ada"                  # aggrieved group's lowest member
    assert evt["payload"] == {"src": FA, "dst": FB, "amount": 12,
                              "total": 12, "reason": "steal"}


def test_add_grievance_clamps_at_100():
    w = _world([_a("ada")])
    _two_factions(w)
    w.add_grievance(FA, FB, 80, "raid")
    assert w.add_grievance(FA, FB, 80, "raid") == 100


def test_add_grievance_rejects_self_blank_and_non_positive():
    w = _world([_a("ada")])
    _two_factions(w)
    assert w.add_grievance(FA, FA, 10, "x") == 0
    assert w.add_grievance("", FB, 10, "x") == 0
    assert w.add_grievance(FA, FB, 0, "x") == 0
    assert w.add_grievance(FA, FB, -5, "x") == 0
    assert w.grievances == {} and w.pending_spawn_events == []


def test_add_grievance_is_a_no_op_when_war_disabled():
    w = _world([_a("ada")], war=False)
    _two_factions(w)
    assert w.add_grievance(FA, FB, 12, "steal") == 0
    assert w.grievances == {}
    assert w.pending_spawn_events == []


# ── _register_war_act folded into _register_crime ────────────────────────────

def test_cross_faction_crime_feeds_the_victims_faction():
    actor, victim = _a("dot"), _a("ada")
    w = _world([actor, victim])
    _two_factions(w)
    w._register_crime(actor, "steal", "ada", 10)
    # The VICTIM's faction holds the heat AGAINST the actor's faction:
    # base 6 (grievance_per_act), no extra witness at the place.
    assert w.grievance_between(FA, FB) == 6
    assert w.grievance_between(FB, FA) == 0
    # EM-240's individual bookkeeping is untouched (witnessed=False here:
    # only actor+victim present, so no notoriety — behavior-identical).
    assert actor.rap_sheet[-1]["crime"] == "steal"


def test_witnesses_escalate_the_grievance():
    actor, victim, w1, w2 = _a("dot"), _a("ada"), _a("bram"), _a("eli")
    w = _world([actor, victim, w1, w2])
    _two_factions(w)
    w._register_crime(actor, "extort", "ada", 10)
    # base 6 + 2 per co-located witness (bram + eli; the victim is excluded).
    assert w.grievance_between(FA, FB) == 6 + 2 * 2


def test_same_faction_and_factionless_crime_feed_nothing():
    a1, a2, loner = _a("ada"), _a("bram"), _a("zed")
    w = _world([a1, a2, loner])
    _two_factions(w)
    w._register_crime(a1, "steal", "bram", 10)       # same faction
    w._register_crime(loner, "steal", "ada", 10)     # factionless actor
    w._register_crime(a1, "steal", "zed", 10)        # factionless victim
    assert w.grievances == {}


def test_crime_feeds_nothing_when_war_disabled():
    actor, victim = _a("dot"), _a("ada")
    w = _world([actor, victim], war=False)
    _two_factions(w)
    w._register_crime(actor, "steal", "ada", 10)
    assert w.grievances == {}
    # …and the EM-240 individual path still ran (golden: behavior-identical).
    assert actor.rap_sheet[-1]["crime"] == "steal"


# ── advance_war: grievance decay ──────────────────────────────────────────────

def test_advance_war_decays_and_drops_cooled_entries():
    w = _world([_a("ada")])
    _two_factions(w)
    w.grievances = {f"{FA}->{FB}": 2, f"{FB}->{FA}": 1}
    w.advance_war()                                   # decay 1 (the default)
    assert w.grievances == {f"{FA}->{FB}": 1}         # cooled-to-0 DROPPED
    w.advance_war()
    assert w.grievances == {}                         # never dead heat


def test_advance_war_is_a_no_op_when_disabled():
    w = _world([_a("ada")], war=False)
    w.grievances = {f"{FA}->{FB}": 5}                 # hand-planted
    assert w.advance_war() == []
    assert w.grievances == {f"{FA}->{FB}": 5}         # untouched


def test_advance_war_honors_configured_decay():
    w = _world([_a("ada")])
    w.params.war = {"enabled": True, "grievance_decay": 4}
    w.grievances = {f"{FA}->{FB}": 9}
    w.advance_war()
    assert w.grievances == {f"{FA}->{FB}": 5}


# ── the contended-seam order invariant ────────────────────────────────────────

def test_round_start_chain_order_factions_then_war_then_aging():
    """The plan's canonical chain: recompute_factions → (reserved:
    diffuse_culture → recompute_congregations) → advance_war → age_agents.
    Culture/religion round systems are NOT built this pass — their slots are
    reserved between recompute_factions and advance_war (see the comment in
    _apply_round_start); this pins the three that exist TODAY."""
    w = _world([_a("ada")])
    calls: list[str] = []
    orig_rf, orig_aw, orig_age = (
        w.recompute_factions, w.advance_war, w.age_agents)
    w.recompute_factions = (
        lambda: (calls.append("recompute_factions"), orig_rf())[1])
    w.advance_war = lambda: (calls.append("advance_war"), orig_aw())[1]
    w.age_agents = (
        lambda pre: (calls.append("age_agents"), orig_age(pre))[1])
    w._apply_round_start()
    assert "recompute_factions" in calls
    assert "advance_war" in calls
    assert "age_agents" in calls
    assert (calls.index("recompute_factions")
            < calls.index("advance_war")
            < calls.index("age_agents"))

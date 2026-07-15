# backend/tests/test_em259_endgame.py
"""EM-259 — siege + war exhaustion + auto-resolution + the settled-war sweep.

siege routes through the SHARED _damage_building path (invariant 8 — the
arson/vandalize lane), so damaged/destroyed transitions and health clamps
hold identically; it is NOT a crime (no notoriety/grievance — the war is
already declared), the besieged faction takes exhaustion instead.

advance_war (round boundary, AFTER recompute_factions / BEFORE age_agents)
grinds both belligerents by exhaustion_per_round, auto-resolves a collapsed
side through the SAME _settle_war lane the EM-257 peace_treaty vote uses
(reparations + exile, announced as war_exhausted), then SWEEPS: settled
wars are deleted and bands disband (belligerence is DERIVED from band
membership — the W31 C3 fix — so the sweep clears nothing else). The
declare → muster → clash → siege → peace integration pins the whole arc.
"""
from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=20)


def _world(war: bool = True) -> World:
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    places = [
        PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance"),
        PlaceState(id="plaza", name="Plaza", x=1, y=0, kind="social"),
    ]
    w = World(params=_params(), places=places, agents=[_a(i) for i in ids])
    if war:
        w.params.war = {"enabled": True}
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram", "cyn"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    return w


def _bld(w: World, owner: str = "dot", health: int = 100,
         status: str = "operational", place: str = "townhall") -> Building:
    b = Building(id="bld_keep", name="Dot's Keep", kind="generic",
                 location=place, owner_id=owner, status=status, health=health)
    w.buildings[b.id] = b
    return b


def _at_war(w: World, band_a=("ada",), band_b=("dot",)):
    war = w.open_war(FA, FB, "avenge the market")
    w.factions[FA]["war_band"] = list(band_a)
    w.factions[FB]["war_band"] = list(band_b)
    return war


# ── siege: gates ──────────────────────────────────────────────────────────────

def test_siege_gates():
    w = _world(war=False)
    _bld(w)
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "war disabled"
    w = _world()
    _at_war(w)
    evt = w.action_siege(w.agents["ada"], "bld_ghost")
    assert evt["payload"]["error"] == "building_not_found"
    _bld(w, status="destroyed", health=0)
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "already destroyed"
    w.buildings.clear()
    _bld(w, place="plaza")
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "not here"


def test_siege_requires_an_enemy_owned_structure():
    w = _world()
    _at_war(w)
    _bld(w, owner="public")                      # unowned/public — not a target
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "not an enemy structure"
    w.buildings.clear()
    _bld(w, owner="bram")                        # own circle's structure
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "not an enemy structure"
    w.buildings.clear()
    _bld(w, owner="fay")                         # factionless owner — no war
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "not an enemy structure"


def test_siege_requires_muster():
    w = _world()
    _at_war(w, band_a=())                        # ada not banded
    _bld(w)
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["payload"]["error"] == "not mustered"


# ── siege: the shared damage path ────────────────────────────────────────────

def test_siege_damages_through_the_shared_path():
    w = _world()
    war = _at_war(w)
    b = _bld(w)
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert "_multi" in evt
    siege_evt, state_evt = evt["_multi"]
    assert siege_evt["kind"] == "war_siege"
    assert siege_evt["payload"] == {
        "action": "siege", "war_id": war.id, "building_id": "bld_keep",
        "damage": 20, "health": 80}
    assert b.health == 80 and b.status == "damaged"
    assert state_evt["kind"] == "structure_state_changed"
    # NOT a crime: no notoriety, no grievance — exhaustion instead. W31 C14:
    # siege is not free — the besieger burns energy and grinds their OWN
    # circle too (exhaustion_per_siege_own).
    assert w.agents["ada"].notoriety == 0
    assert w.agents["ada"].energy == 76.0        # 80 - siege_energy_cost
    assert w.grievances == {}
    assert war.exhaustion == {FB: 4, FA: 2}      # per_siege / per_siege_own


def test_siege_destroys_at_zero_health():
    w = _world()
    _at_war(w)
    b = _bld(w, health=15)
    w.action_siege(w.agents["ada"], "bld_keep")
    assert b.health == 0 and b.status == "destroyed"


# ── advance_war: exhaustion accrual + auto-resolution ────────────────────────

def test_round_boundary_grinds_both_belligerents():
    w = _world()
    war = _at_war(w)
    evts = w.advance_war()
    assert war.exhaustion == {FA: 1, FB: 1}      # exhaustion_per_round
    assert evts == []                            # no collapse, no events
    assert war.status == "active"


def test_exhaustion_cap_collapses_the_wearier_side():
    w = _world()
    war = _at_war(w)
    wid = war.id
    war.exhaustion = {FA: 40, FB: 99}            # FB crosses the cap this round
    w.grievances = {f"{FA}->{FB}": 30, f"{FB}->{FA}": 44}
    evts = w.advance_war()
    kinds = [e["kind"] for e in evts]
    assert kinds == ["war_exhausted", "exiled"]
    settled = evts[0]["payload"]
    assert settled["loser"] == FB and settled["winner"] == FA
    assert settled["reason"] == "exhaustion"
    assert settled["war_id"] == wid
    # The SAME settlement lane as peace_treaty: reparations_base collected
    # (dot 20 + eli 5 = 25), split across FA's 3 living members (25//3 = 8).
    assert w.agents["dot"].credits == 0 and w.agents["eli"].credits == 15
    assert all(w.agents[m].credits == 28 for m in ("ada", "bram", "cyn"))
    # Loser leader (lowest-id living member) exiled with war_notoriety.
    assert w.agents["dot"].crime_status == "exiled"
    assert w.agents["dot"].notoriety == 10
    # Ledger cleared BOTH ways; the settled war is SWEPT the same round.
    assert w.grievances == {}
    assert wid not in w.wars


def test_exhaustion_tie_blames_the_aggressor():
    w = _world()
    war = _at_war(w)
    war.exhaustion = {FA: 99, FB: 99}            # both cross together
    evts = w.advance_war()
    assert evts[0]["payload"]["loser"] == FA     # FA declared the war
    assert w.agents["ada"].crime_status == "exiled"


def test_dissolved_faction_loses_on_the_spot():
    w = _world()
    _at_war(w)
    for aid in ("dot", "eli"):
        w.agents[aid].alive = False              # FB extinct
    evts = w.advance_war()
    assert evts[0]["kind"] == "war_exhausted"
    assert evts[0]["payload"]["loser"] == FB
    assert evts[0]["payload"]["reason"] == "faction dissolved"
    # An extinct loser has no living leader — no exile event rides.
    assert [e["kind"] for e in evts] == ["war_exhausted"]


def test_band_collapse_loses_while_the_enemy_still_fields_one():
    w = _world()
    _at_war(w, band_a=("ada",), band_b=("dot",))
    w.agents["ada"].alive = False                # FA's whole band falls
    evts = w.advance_war()
    assert evts[0]["payload"]["loser"] == FA
    assert evts[0]["payload"]["reason"] == "war band collapsed"
    # bram is FA's derived leader now (lowest-id LIVING member).
    assert w.agents["bram"].crime_status == "exiled"


# ── the sweep ─────────────────────────────────────────────────────────────────

def test_sweep_disbands_bands_and_ends_belligerence():
    """W31 C3 — belligerence is DERIVED from the band, so dropping the
    war_band key IS the demobilization (crime_status is never touched)."""
    w = _world()
    war = _at_war(w)
    assert w.is_belligerent("ada") and w.is_belligerent("dot")
    war.status = "settled"                       # e.g. a signed peace
    w.advance_war()
    assert w.wars == {}
    assert "war_band" not in w.factions[FA]
    assert "war_band" not in w.factions[FB]
    assert not w.is_belligerent("ada")
    assert not w.is_belligerent("dot")


def test_sweep_spares_a_faction_still_at_war():
    """A faction fighting on a SECOND front keeps its band (and so its
    members' derived belligerence) when the first war settles."""
    w = _world()
    FC = "fct_ccc33333"
    w.factions[FC] = {"name": "Fay's circle", "founded_tick": 0,
                      "members": ["fay"]}
    war1 = _at_war(w)                            # FA vs FB
    w.tick = 1
    w.open_war(FA, FC, "two fronts")             # FA vs FC stays active
    war1.status = "settled"
    w.advance_war()
    assert "war_band" in w.factions[FA]          # still at war (vs FC)
    assert w.is_belligerent("ada")
    assert "war_band" not in w.factions[FB]      # FB's war is over
    assert not w.is_belligerent("dot")


def test_sweep_never_clears_crime_statuses():
    w = _world()
    war = _at_war(w)
    w.agents["dot"].crime_status = "wanted"
    w.agents["ada"].crime_status = "exiled"      # a past defeat
    war.status = "settled"
    w.advance_war()
    assert w.agents["dot"].crime_status == "wanted"
    assert w.agents["ada"].crime_status == "exiled"


# ── the full arc: declare → muster → clash → siege → peace ───────────────────

def test_declare_muster_clash_siege_peace_integration():
    w = _world()
    w.grievances[f"{FA}->{FB}"] = 60             # casus belli
    keep = _bld(w)                               # dot's structure, townhall

    # DECLARE — the EM-257 faction-scoped 70% lane (3 of 3 FA members).
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "declare_war", "Avenge the market", target=FB)
    assert ok, reason
    for voter in ("ada", "bram", "cyn"):
        ok, _, status = w.action_vote(w.agents[voter], rule.id, True)
    assert status == "active"
    war = next(iter(w.wars.values()))
    assert war.status == "active"
    assert [e["kind"] for e in w.pending_spawn_events] == ["war_declared"]
    w.pending_spawn_events.clear()

    # MUSTER — both sides raise a band; ally rings seal; belligerence derives.
    for aid in ("ada", "bram", "dot"):
        evt = w.action_muster(w.agents[aid])
        assert evt["kind"] == "war_band_joined"
    assert w.factions[FA]["war_band"] == ["ada", "bram"]
    assert w.is_belligerent("ada")
    assert w.agents["ada"].crime_status is None  # W31 C3 — never a status

    # CLASH — tick 0, pair (ada, dot): pinned swing +4. ada fields bram's
    # support (+4); dot shelters behind the standing keep (defender terrain
    # +5): margin = 94 + 4 − 95 = 3, damage 8 + floor(3*0.5) = 9.
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["kind"] == "war_clash"
    assert evt["payload"]["margin"] == 3
    assert w.agents["dot"].energy == 80.0 - 9
    assert war.exhaustion == {FB: 5, FA: 2}

    # SIEGE — the keep takes the shared-path damage; FB grinds further and
    # (W31 C14) the besieger burns energy + grinds their OWN circle a little.
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["_multi"][0]["kind"] == "war_siege"
    assert keep.health == 80
    assert war.exhaustion == {FB: 9, FA: 4}

    # PEACE — the battered side sues (concedes): FB's own 70% (2 of 2).
    ok, reason, treaty = w.action_propose_rule(
        w.agents["dot"], "peace_treaty", "we yield", war_id=war.id,
        reparations=30)
    assert ok, reason
    w.action_vote(w.agents["dot"], treaty.id, True)
    ok, _, status = w.action_vote(w.agents["eli"], treaty.id, True)
    assert status == "active"
    assert war.status == "settled"
    kinds = [e["kind"] for e in w.pending_spawn_events]
    assert kinds == ["peace_signed", "exiled"]
    # Reparations: dot 20 + eli 10 = 30 collected, 30 // 3 = 10 each to FA.
    assert w.agents["dot"].credits == 0 and w.agents["eli"].credits == 10
    assert all(w.agents[m].credits == 30 for m in ("ada", "bram", "cyn"))
    assert w.agents["dot"].crime_status == "exiled"     # FB's derived leader
    assert w.grievances == {}                           # ledger cleared

    # The ROUND BOUNDARY sweeps the settled war and stands the armies down.
    w.advance_war()
    assert w.wars == {}
    assert "war_band" not in w.factions[FA]
    assert w.agents["ada"].crime_status is None
    assert w.agents["bram"].crime_status is None
    assert w.agents["dot"].crime_status == "exiled"     # the price stays paid

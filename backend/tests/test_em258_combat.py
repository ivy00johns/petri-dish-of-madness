# backend/tests/test_em258_combat.py
"""EM-258 — the combat primitive (muster + clash), plan §Feature 3.

clash is THE one genuinely new mechanic in the Wave O portfolio: a pure
seeded stat contest (no random, no clock — EM-155) whose EXACT formula is
pinned here:

    seed   = _seed_int("clash", city_seed, tick, *sorted ids)   # symmetric
    swing  = (seed % (2*span+1)) - span                          # [-span,+span]
    power  = E + S*skill_weight + B*support_weight + D + floor(M*morale_weight)
    margin = power(attacker) + swing - power(defender)
    winner = attacker if margin >= 0 else defender
    dmg_loser  = base_damage + floor(min(|margin|, cap) * per_margin)  # FLOOR
    dmg_winner = base_damage // 2

Damage rides energy → the EXISTING check_death (energy IS the HP analog —
the frozen no-weapons/no-HP-objects constraint). The seed is SYMMETRIC in
the pair, so who initiates cannot re-roll the swing (order-independence,
pinned below with a hardcoded literal). muster seals an accept_contract-
style ally ring across the war band; belligerence is DERIVED from band
membership (World.is_belligerent) and never rides crime_status — riding it
suppressed the wanted flip and froze notoriety decay (the W31 C3 fix; the
jail-gate widening is pinned in test_em258_schema.py).
"""
import math

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, place: str = "townhall") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=place, energy=80.0, credits=20)


def _world(war: bool = True) -> World:
    """ada/bram/cyn (faction A) + dot/eli (faction B) + fay (factionless),
    all at the townhall (city_seed defaults to 1337, tick 0)."""
    ids = ["ada", "bram", "cyn", "dot", "eli", "fay"]
    places = [
        PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance"),
        PlaceState(id="plaza", name="Plaza", x=1, y=0, kind="social"),
        PlaceState(id="workshop", name="Workshop", x=2, y=0, kind="work"),
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


def _at_war(w: World, band_a: list[str] | None = None,
            band_b: list[str] | None = None):
    war = w.open_war(FA, FB, "avenge the market")
    if band_a is not None:
        w.factions[FA]["war_band"] = list(band_a)
    if band_b is not None:
        w.factions[FB]["war_band"] = list(band_b)
    return war


# ── muster ────────────────────────────────────────────────────────────────────

def test_muster_requires_war_enabled_faction_and_active_war():
    w = _world(war=False)
    evt = w.action_muster(w.agents["ada"])
    assert evt["kind"] == "parse_failure" and evt["payload"]["error"] == "war disabled"
    w = _world()
    evt = w.action_muster(w.agents["fay"])                  # factionless
    assert evt["payload"]["error"] == "no faction"
    evt = w.action_muster(w.agents["ada"])                  # no war open
    assert evt["payload"]["error"] == "not at war"


def test_muster_joins_the_band_and_derives_belligerence():
    """W31 C3 — muster never writes crime_status (that suppressed the wanted
    flip + froze notoriety decay); the band list IS belligerence."""
    w = _world()
    _at_war(w)
    assert w.is_belligerent("ada") is False
    evt = w.action_muster(w.agents["ada"])
    assert evt["kind"] == "war_band_joined"
    assert w.factions[FA]["war_band"] == ["ada"]
    assert w.agents["ada"].crime_status is None
    assert w.is_belligerent("ada") is True
    assert evt["payload"] == {"action": "muster", "faction_id": FA,
                              "band_size": 1}


def test_muster_twice_is_rejected():
    w = _world()
    _at_war(w, band_a=["ada"])
    evt = w.action_muster(w.agents["ada"])
    assert evt["payload"]["error"] == "already mustered"
    assert w.factions[FA]["war_band"] == ["ada"]            # unchanged


def test_muster_seals_the_ally_ring_like_accept_contract():
    """The conspiracy-bond clone: mutual trust floored at band_trust_seed,
    neutral edges promoted to ally — with EVERY living banded comrade."""
    w = _world()
    _at_war(w, band_a=["ada"])
    evt = w.action_muster(w.agents["bram"])
    assert evt["kind"] == "war_band_joined"
    assert w.factions[FA]["war_band"] == ["ada", "bram"]
    for a, b in (("ada", "bram"), ("bram", "ada")):
        rel = w.agents[a].relationships[b]
        assert rel.trust >= 30                              # band_trust_seed
        assert rel.type == "ally"


def test_muster_never_touches_crime_status():
    """W31 C3 — a wanted agent who musters stays wanted (justice applies to
    soldiers); belligerence derives from the band, not crime_status."""
    w = _world()
    _at_war(w)
    w.agents["ada"].crime_status = "wanted"
    evt = w.action_muster(w.agents["ada"])
    assert evt["kind"] == "war_band_joined"
    assert w.agents["ada"].crime_status == "wanted"         # untouched
    assert "ada" in w.factions[FA]["war_band"]              # band is the truth
    assert w.is_belligerent("ada") is True


def test_mustered_agent_still_flips_wanted_at_threshold():
    """W31 C3 — the failure the crime_status overload caused: a mustered
    agent in the 40-59 notoriety band could never be flagged wanted (justice
    silently disabled). A witnessed crime past wanted_threshold flips it."""
    w = _world()
    _at_war(w)
    assert w.action_muster(w.agents["ada"])["kind"] == "war_band_joined"
    ada = w.agents["ada"]
    ada.notoriety = 39
    # townhall crowd: 4 witnesses ⇒ gain 10 + 3·3 = 19 ⇒ notoriety 58 ≥ 40.
    w._register_crime(ada, "steal", "dot", 10)
    assert ada.notoriety == 58
    assert ada.crime_status == "wanted"
    assert w.is_belligerent("ada")                          # still a soldier


def test_mustered_agent_still_decays_notoriety():
    """W31 C3 — advance_crime's decay gate reads (None, wanted); a mustered
    agent's crime_status stays in that set, so their heat cools like
    anyone else's."""
    w = _world()
    _at_war(w)
    w.action_muster(w.agents["ada"])
    w.agents["ada"].notoriety = 10
    w.advance_crime()
    assert w.agents["ada"].notoriety == 8                   # decay default 2


# ── clash: gates ──────────────────────────────────────────────────────────────

def test_clash_gates_self_colocation_war_and_band():
    w = _world()
    evt = w.action_clash(w.agents["ada"], w.agents["ada"])
    assert evt["payload"]["error"] == "self"
    w.agents["dot"].location = "plaza"
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["payload"]["error"] == "not co-located"
    w.agents["dot"].location = "townhall"
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])  # no war open
    assert evt["payload"]["error"] == "not at war"
    _at_war(w)                                              # war, but no band
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["payload"]["error"] == "not mustered"
    evt = w.action_clash(w.agents["ada"], w.agents["fay"])  # factionless foe
    assert evt["payload"]["error"] == "not at war"


def test_clash_requires_band_can_be_configured_off():
    w = _world()
    w.params.war = {"enabled": True, "clash_requires_band": False}
    _at_war(w)
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["kind"] == "war_clash"


def test_clash_disabled_world_fails_closed():
    w = _world(war=False)
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["payload"]["error"] == "war disabled"


# ── clash: the pinned seeded contest ─────────────────────────────────────────

def test_clash_exact_outcome_is_pinned():
    """The formula, end to end, with EVERY value literal: city_seed 1337,
    tick 0, pair (ada, dot) ⇒ seed swing = +4 (hardcoded — the regression
    pin). Equal fighters (energy 80, no skill, no support, no terrain,
    morale 100): power 80 + floor(100*0.1) = 90 each. margin = +4 ⇒ the
    attacker wins; dmg_loser = 8 + floor(min(4,40)*0.5) = 10;
    dmg_winner = 8 // 2 = 4."""
    w = _world()
    war = _at_war(w, band_a=["ada"], band_b=["dot"])
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["kind"] == "war_clash"
    p = evt["payload"]
    assert p["swing"] == 4                                  # the seed literal
    assert p["margin"] == 4
    assert p["winner"] == "ada" and p["loser"] == "dot"
    assert p["damage_loser"] == 10 and p["damage_winner"] == 4
    assert w.agents["dot"].energy == 70.0                   # 80 - 10
    assert w.agents["ada"].energy == 76.0                   # 80 - 4
    # Exhaustion: loser faction +exhaustion_per_clash, winner half (floored).
    assert war.exhaustion == {FB: 5, FA: 2}
    assert war.casualties == []                             # nobody died


def test_clash_formula_matches_the_seeded_recompute():
    """The same contest recomputed from the formula's constituents (the
    _seed_int import — no engine internals), for a NON-trivial world: skill,
    band support, terrain cover and unequal energy all in play."""
    from petridish.animals.runtime import _seed_int
    w = _world()
    w.tick = 7
    war = _at_war(w, band_a=["ada", "bram"], band_b=["dot", "eli"])
    war.exhaustion = {FA: 20, FB: 60}                       # morale 80 / 40
    w.agents["ada"].energy = 66.0
    w.agents["ada"].skills = {"combat": 3}
    w.agents["dot"].energy = 71.0
    # A standing structure at the townhall shelters the DEFENDER (dot).
    w.buildings["bld_cover"] = Building(
        id="bld_cover", name="Barricade", kind="generic", location="townhall",
        owner_id="dot", status="operational", health=100)
    seed = _seed_int("clash", 1337, 7, "ada", "dot")        # sorted pair
    swing = (seed % 21) - 10
    # power(E, S, B, D, M): ada = 66 + 3*5 + 1*4 (bram) + 0 + floor(80*0.1)
    # = 93; dot = 71 + 0 + 1*4 (eli) + 5 (cover) + floor(40*0.1) = 84.
    p_ada = 66 + 15 + 4 + 0 + 8
    p_dot = 71 + 0 + 4 + 5 + 4
    margin = p_ada + swing - p_dot
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    p = evt["payload"]
    assert p["swing"] == swing == 1                         # pinned literal
    assert p["margin"] == margin == 10
    assert p["winner"] == "ada"
    dmg = 8 + math.floor(min(abs(margin), 40) * 0.5)
    assert p["damage_loser"] == dmg == 13
    assert w.agents["dot"].energy == 71.0 - 13
    assert w.agents["ada"].energy == 66.0 - 4


def test_clash_seed_is_order_independent():
    """clash(a,b) and clash(b,a) draw the SAME swing (sorted-pair seed) — who
    initiates cannot re-roll the contest. Two identical worlds, opposite
    initiators: identical swing, mirrored margin, identical damage."""
    w1, w2 = _world(), _world()
    _at_war(w1, band_a=["ada"], band_b=["dot"])
    _at_war(w2, band_a=["ada"], band_b=["dot"])
    e1 = w1.action_clash(w1.agents["ada"], w1.agents["dot"])
    e2 = w2.action_clash(w2.agents["dot"], w2.agents["ada"])
    p1, p2 = e1["payload"], e2["payload"]
    assert p1["swing"] == p2["swing"] == 4                  # the SAME roll
    # Equal fighters ⇒ the +4 swing hands the win to whoever initiated —
    # but the damage arithmetic is identical (same margin magnitude).
    assert p1["winner"] == "ada" and p2["winner"] == "dot"
    assert p1["damage_loser"] == p2["damage_loser"] == 10
    assert (w1.agents["dot"].energy, w1.agents["ada"].energy) == (70.0, 76.0)
    assert (w2.agents["ada"].energy, w2.agents["dot"].energy) == (70.0, 76.0)


def test_clash_defender_wins_on_negative_margin():
    """tick 0, pair (ada, eli): pinned swing -4 ⇒ equal fighters, the
    DEFENDER prevails and the attacker takes the loser damage."""
    w = _world()
    war = _at_war(w, band_a=["ada"], band_b=["eli"])
    evt = w.action_clash(w.agents["ada"], w.agents["eli"])
    p = evt["payload"]
    assert p["swing"] == -4 and p["margin"] == -4
    assert p["winner"] == "eli" and p["loser"] == "ada"
    assert w.agents["ada"].energy == 70.0                   # loser damage 10
    assert w.agents["eli"].energy == 76.0
    assert war.exhaustion == {FA: 5, FB: 2}


def test_clash_margin_is_capped_before_damage():
    """A crushing power gap caps at margin_cap (40): dmg = 8 + floor(40*0.5)
    = 28 — never more, however lopsided the fight."""
    w = _world()
    _at_war(w, band_a=["ada"], band_b=["dot"])
    w.agents["dot"].energy = 5.0                            # feeble defender
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    p = evt["payload"]
    assert p["margin"] > 40                                 # raw gap past cap
    assert p["damage_loser"] == 28                          # capped
    assert w.agents["dot"].energy == 0.0                    # clamped ≥ 0


# ── clash: the war-death path ────────────────────────────────────────────────

def test_clash_kill_rides_energy_check_death():
    """A lethal clash resolves the TARGET's death INLINE (the target gets no
    turn): energy → 0, the EXISTING check_death flips alive=False, the
    casualty is recorded, the faction takes exhaustion_per_casualty, and the
    agent_died event rides the _multi chain."""
    w = _world()
    w.params.death_after_zero_turns = 1                     # die on first zero
    war = _at_war(w, band_a=["ada"], band_b=["dot"])
    w.agents["dot"].energy = 5.0
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert "_multi" in evt
    kinds = [e["kind"] for e in evt["_multi"]]
    assert kinds[0] == "war_clash" and "agent_died" in kinds
    assert not w.agents["dot"].alive
    assert war.casualties == ["dot"]
    # loser +5 (clash) then +15 (casualty) = 20; winner +2.
    assert war.exhaustion == {FB: 20, FA: 2}
    died = next(e for e in evt["_multi"] if e["kind"] == "agent_died")
    assert died["payload"]["war_id"] == war.id


def test_clash_survivor_below_threshold_is_not_killed_inline():
    """Zero energy WITHOUT reaching death_after_zero_turns only increments
    the existing counter — the loop's post-turn sweep owns the follow-up
    (no double-count, the exact pre-war death model)."""
    w = _world()                                            # default threshold > 1
    war = _at_war(w, band_a=["ada"], band_b=["dot"])
    w.agents["dot"].energy = 5.0
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert evt["kind"] == "war_clash"                       # single event
    assert w.agents["dot"].alive
    assert w.agents["dot"].zero_energy_turns == 1
    assert war.casualties == []


# ── clash: morale break ⇒ deterministic retreat ──────────────────────────────

def test_loser_retreats_at_the_retreat_floor():
    """Faction morale (100 − exhaustion) at/below retreat_floor (30) sends
    the LOSER to the lowest-id place free of the winner's living members —
    deterministically."""
    w = _world()
    war = _at_war(w, band_a=["ada"], band_b=["dot"])
    war.exhaustion = {FB: 70}                               # FB morale 30
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    p = evt["payload"]
    assert p["winner"] == "ada" and p["loser"] == "dot"
    # Sorted places: plaza < townhall < workshop; all of FA stands at the
    # townhall, so the lowest-id enemy-free place is the plaza.
    assert p["retreated_to"] == "plaza"
    assert w.agents["dot"].location == "plaza"


def test_retreat_skips_places_held_by_the_enemy():
    w = _world()
    war = _at_war(w, band_a=["ada"], band_b=["dot"])
    war.exhaustion = {FB: 70}
    w.agents["cyn"].location = "plaza"                      # FA holds the plaza
    w.action_clash(w.agents["ada"], w.agents["dot"])
    assert w.agents["dot"].location == "workshop"           # next free place


def test_no_retreat_above_the_floor():
    w = _world()
    _at_war(w, band_a=["ada"], band_b=["dot"])              # morale 100
    evt = w.action_clash(w.agents["ada"], w.agents["dot"])
    assert "retreated_to" not in evt["payload"]
    assert w.agents["dot"].location == "townhall"

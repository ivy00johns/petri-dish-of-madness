"""EM-333 — First Contact honesty wiring (SB): cross-border meme carriage,
per-family rumor-fidelity telemetry, settlement-scoped war grievances, and
defection legality (the write-once origin stamp).

Layers covered (each at its own seam):
  - config/loader — the `world.contact.honesty` flag parse.
  - engine.world origin stamps — genesis split stamps BOTH towns; travel
    (defection) never re-stamps; the stamp is byte-identical-absent when
    honesty is OFF.
  - diffuse_culture / action_spread_rumor — a hop whose meme's ORIGINAL
    author was born in a different contact settlement is a BORDER CROSSING:
    `meme_crossed_border` / `rumor_crossed_border` events + the honesty
    ledger {crossings, by_family: {family: {hops, mutated}}}.
  - War scoping — a border crime heats the TOWNS as well as the factions;
    a cross-town declare_war ratifies BETWEEN THE SETTLEMENTS
    (WarState.scope == "settlement", belligerents = settlement ids); a
    scoped war grinds via exhaustion and settles through the shared
    _settle_war lane (reparations resolve from settlement records).
  - Byte-identity — honesty OFF: no stamps, no ledger, no events, no
    scoping (the EM-155 keystone).

Deterministic and offline (no network). Carriage state existed pre-EM-333
(diffusion is co-location-based, so a visitor was always a vector) — SB adds
the HONESTY: the telling-on-itself telemetry.
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import hashlib

import pytest

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import (
    CommunicationParams,
    ContactParams,
    SettlementParams,
    WarParams,
    WorldParams,
    _parse_contact,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

_PLACES = [
    PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
    PlaceState(id="well", name="Well", x=520, y=460, kind="social"),
    PlaceState(id="market", name="Market", x=560, y=520, kind="work"),
]
_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve", "Fay"]


def _params(*, contact=True, honesty=True, comm=True, war=False) -> WorldParams:
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=True)
    if contact:
        p.contact = ContactParams(enabled=True, family_a="gemini",
                                  family_b="llama", name_b="Grimstead",
                                  honesty=honesty)
    if comm:
        p.comm = CommunicationParams(enabled=True, diffusion_chance=1.0)
    if war:
        p.war = WarParams(enabled=True)
    return p


def _agents(n=6):
    """The seed roster in config order; the profile matches the family the
    SPLIT will give the agent (first ceil(n/2) names → town A → gemini-x)."""
    out = []
    a_half = (n + 1) // 2
    for i, name in enumerate(_NAMES[:n]):
        out.append(AgentState(id=f"agent_{name.lower()}_{i}", name=name,
                              personality="",
                              profile="gemini-x" if i < a_half else "llama-x",
                              location="plaza", energy=80.0, credits=20))
    return out


def _honesty_world(n=6, **kw):
    w = World(params=_params(**kw),
              places=[copy.copy(p) for p in _PLACES],
              agents=_agents(n))
    w.seed_genesis_settlement()
    return w


def _towns(w):
    """(sid_a, sid_b) — B is the founder_id=='contact' settlement."""
    sid_b = next(s for s in w.settlements
                 if w.settlements[s]["founder_id"] == "contact")
    sid_a = next(s for s in w.settlements if s != sid_b)
    return sid_a, sid_b


def _half_ids(w, side):
    sid_a, sid_b = _towns(w)
    return sorted(w.settlements[sid_a if side == "a" else sid_b]["members"])


def _inject_factions(w):
    """Two single-town circles the war seams can read (faction_of walks the
    members lists). fct_a is based in town A, fct_b in town B."""
    a_ids = _half_ids(w, "a")
    b_ids = _half_ids(w, "b")
    w.factions["fct_a"] = {"id": "fct_a", "name": "A Circle",
                           "members": list(a_ids[:2])}
    w.factions["fct_b"] = {"id": "fct_b", "name": "B Circle",
                           "members": list(b_ids[:2])}
    return w.factions["fct_a"], w.factions["fct_b"]


# ── 1. flag + origin stamps (the write-once birth town) ──────────────────────

def test_parse_contact_honesty_flag():
    assert _parse_contact({"enabled": True, "honesty": True}).honesty is True
    assert _parse_contact({"enabled": True}).honesty is False
    assert _parse_contact(None).honesty is False


def test_genesis_stamps_both_towns():
    w = _honesty_world()
    sid_a, sid_b = _towns(w)
    stamps = {a.name: a.origin_settlement_id for a in w.agents.values()}
    assert all(stamps.values()), "every split agent carries a birth town"
    assert {stamps[n] for n in ("Ann", "Bob", "Cleo")} == {sid_a}
    assert {stamps[n] for n in ("Dex", "Eve", "Fay")} == {sid_b}


def test_stamps_absent_when_honesty_off():
    w = _honesty_world(honesty=False)
    assert all(a.origin_settlement_id is None for a in w.agents.values())
    snap = w.to_snapshot({})
    assert "contact_ledger" not in snap
    assert all("origin_settlement_id" not in a.to_dict()
               for a in w.agents.values())


def test_honesty_explicit_false_is_byte_identical_to_absent_key():
    w1 = _honesty_world(honesty=False)
    w2 = _honesty_world(honesty=False)
    w2.params.contact = ContactParams(enabled=True, family_a="gemini",
                                      family_b="llama", name_b="Grimstead")
    w2.seed_genesis_settlement()
    assert w1.to_snapshot({}) == w2.to_snapshot({})


# ── 2. meme carriage across the border ─────────────────────────────────────────

def _a_carrier_meme_at_b_plaza(w, text="The plaza bells borrowed their chime"):
    """An A-half author mints an idea; the author (its only carrier) is then
    standing in town B's plaza — the visitor vector. Membership-based (works
    with honesty OFF, where no origin stamps exist)."""
    sid_a = _towns(w)[0]
    a_id = sorted(w.settlements[sid_a]["members"])[0]
    author = w.agents[a_id]
    meme = w.mint_meme("idea", text, author.id)
    w._attach_meme(author, meme)
    author.location = "cb_plaza"
    return author, meme


def test_diffusion_crosses_border():
    w = _honesty_world()
    sid_a, sid_b = _towns(w)
    author, meme = _a_carrier_meme_at_b_plaza(w)
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings, "the visit infected town B — that is a crossing"
    ev = crossings[0]
    assert ev["payload"]["from_settlement"] == sid_a
    assert ev["payload"]["to_settlement"] == sid_b
    assert ev["payload"]["carrier_family"] == "gemini"
    assert ev["payload"]["mutated"] is True  # 'borrowed' → 'stole'
    assert ev["payload"]["from_settlement"] != ev["payload"]["to_settlement"]
    # Town B actually CAUGHT the idea (state, not just telemetry).
    b_ids = _half_ids(w, "b")
    assert any(meme.id in w.agents[aid].held_memes or
               any(c in b_ids for c in m.carriers)
               for mid, m in w.memes.items() for aid in b_ids)
    # The fidelity-per-family ledger.
    assert w.contact_ledger["crossings"] >= 1
    gem = w.contact_ledger["by_family"]["gemini"]
    assert gem["hops"] >= 1 and gem["mutated"] >= 1


def test_diffusion_within_town_records_nothing():
    w = _honesty_world()
    author = next(a for a in w.agents.values()
                  if a.origin_settlement_id == _towns(w)[0])
    meme = w.mint_meme("idea", "The plaza bells borrowed their chime", author.id)
    w._attach_meme(author, meme)  # carrier stays at the A plaza
    events = w.diffuse_culture()
    assert not [e for e in events if "crossed_border" in e["kind"]]
    assert int(w.contact_ledger.get("crossings", 0)) == 0


def test_diffusion_crossing_carries_generation_in_payload():
    # EM-336 — the archive row must be auditable offline: the carried
    # lineage's drift depth rides every crossing payload. The seam helper's
    # text distorts on the border hop ('borrowed' → 'stole'), so the payload
    # carries the minted gen-1 CHILD; the gen-0 verbatim ride is pinned by
    # the image-meme test below, the gen-3 verbatim ride by the run-22 one.
    w = _honesty_world()
    author, meme = _a_carrier_meme_at_b_plaza(w)
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings
    assert crossings[0]["payload"]["generation"] == 1
    assert crossings[0]["payload"]["meme_id"] != meme.id


def test_gen3_verbatim_hop_is_a_drifted_crossing():
    # THE RUN-22 REPRODUCTION (EM-336): a lineage drifted past the
    # meme-coherence drift cap spreads AS ITSELF (child is meme, text
    # unchanged) — the old text-delta flag read these as intact, pinning
    # run 22 at fidelity 1.0 while 22/23 crossing lineages were themselves
    # mutants. Lineage is the truth: a gen-3 hop IS a drifted crossing.
    w = _honesty_world()
    sid_a, _ = _towns(w)
    a_id = sorted(w.settlements[sid_a]["members"])[0]
    author = w.agents[a_id]
    root = w.mint_meme("idea", "The plaza bells borrowed their chime", author.id)
    w._attach_meme(author, root)
    drifted = w.mint_meme("idea", "The plaza bells STOLE their chime",
                          author.id, parent_id=root.id, generation=3)
    w._attach_meme(author, drifted)   # root evicted from the FIFO cap? no —
    # held_meme_cap is 12 and the author holds 2; the drifted child carries.
    assert drifted.generation == 3
    author.location = "cb_plaza"     # the visitor vector, per the seam tests
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings, "the drifted lineage crossed"
    ev = next(e for e in crossings if e["payload"]["meme_id"] == drifted.id)
    assert ev["payload"]["parent_id"] == drifted.id   # verbatim: child IS parent
    assert ev["payload"]["mutated"] is True           # LINEAGE, not text delta
    assert ev["payload"]["generation"] == 3
    gem = w.contact_ledger["by_family"]["gemini"]
    assert gem["hops"] >= 1 and gem["mutated"] >= 1


def test_gen0_original_riding_verbatim_is_faithful():
    # The other side of the EM-336 contract: a gen-0 original (image memes
    # ALWAYS spread this way — the image IS the content) that crosses with
    # its text unchanged is a GENUINE fidelity-1.0 carriage, not a blind
    # spot. The old text-delta flag happened to get this one right.
    w = _honesty_world()
    author, meme = _a_carrier_meme_at_b_plaza(w, text="The plaza bells chime")
    meme.image_id = "img_test0001"    # image memes spread as themselves at ANY generation
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings
    ev = next(e for e in crossings if e["payload"]["meme_id"] == meme.id)
    assert ev["payload"]["mutated"] is False
    assert ev["payload"]["generation"] == 0


def test_gen0_text_original_distorting_at_the_border_is_mutated():
    # A gen-0 TEXT original can still mint a distorted child on a border hop
    # (under the drift cap, not an image) — the mutation must count.
    w = _honesty_world()
    author, meme = _a_carrier_meme_at_b_plaza(w)
    assert meme.generation == 0 and meme.image_id is None
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings
    ev = crossings[0]
    assert ev["payload"]["meme_id"] != ev["payload"]["parent_id"]  # a mint happened
    assert ev["payload"]["generation"] == 1
    assert ev["payload"]["mutated"] is True
    gem = w.contact_ledger["by_family"]["gemini"]
    assert gem["mutated"] >= 1


def test_honesty_off_spreads_without_telemetry():
    # Carriage is not new — diffusion always infected co-located agents.
    # Honesty OFF must keep the STATE and add NONE of the telling.
    w = _honesty_world(honesty=False)
    author, meme = _a_carrier_meme_at_b_plaza(w)
    events = w.diffuse_culture()
    assert not [e for e in events if "crossed_border" in e["kind"]]
    assert w.contact_ledger == {}
    b_ids = _half_ids(w, "b")
    assert any(meme.id in w.agents[aid].held_memes or
               any(c in b_ids for c in m.carriers)
               for mid, m in w.memes.items() for aid in b_ids), \
        "the meme still spreads — only the telemetry is off"


def test_visitor_carries_meme_home():
    # The full EM-333(a) arc: a B-half agent travels to town A (the sanctioned
    # defection — home flips on arrival), keeps its BIRTH town, and its memes
    # infect A residents as a crossing in the OTHER direction.
    w = _honesty_world()
    sid_a, sid_b = _towns(w)
    visitor = w.agents[_half_ids(w, "b")[0]]
    ev = w.action_travel_to(visitor, sid_a)
    # EM-334 — the first cross-town departure now rides a contact_made leg;
    # this test is about the carriage, so unwrap the chain.
    departed = ev["_multi"][0] if "_multi" in ev else ev
    assert departed["kind"] == "travel_departed"
    w.tick = departed["payload"]["arrival_tick"]
    w.resolve_travel_arrivals()
    assert visitor.home_settlement_id == sid_a      # the defection is real
    assert visitor.origin_settlement_id == sid_b    # the origin is too
    visitor.location = "plaza"  # they wander into the town square
    meme = w.mint_meme("idea", "Grimstead wells borrowed their shine",
                       visitor.id)
    w._attach_meme(visitor, meme)
    events = w.diffuse_culture()
    crossings = [e for e in events if e["kind"] == "meme_crossed_border"]
    assert crossings
    assert crossings[0]["payload"]["from_settlement"] == sid_b
    assert crossings[0]["payload"]["to_settlement"] == sid_a
    assert crossings[0]["payload"]["carrier_family"] == "llama"


# ── 3. rumor distortion — fidelity per carrying family ───────────────────────

def _spread_foreign_rumor(w, text="Rex borrowed the well bucket"):
    """An A-half carrier whispers a rumor AUTHORED by a B-half agent to an
    A-half listener — the source's birth town differs from the target's."""
    sid_a, sid_b = _towns(w)
    b_author = w.agents[_half_ids(w, "b")[0]]
    source = w.mint_meme("rumor", text, b_author.id)
    carrier = next(a for a in w.agents.values()
                   if a.origin_settlement_id == sid_a)
    target = next(a for a in w.agents.values()
                  if a.origin_settlement_id == sid_a and a.id != carrier.id)
    res = w.action_spread_rumor(carrier, target, meme_id=source.id)
    return res, carrier, target


def test_rumor_crosses_border_and_tells_on_itself():
    w = _honesty_world()
    sid_a, sid_b = _towns(w)
    res, carrier, target = _spread_foreign_rumor(w)
    legs = res["_multi"] if "_multi" in res else [res]
    assert legs[0]["kind"] == "rumor_spread"
    assert [leg["kind"] for leg in legs] == \
        ["rumor_spread", "meme_mutated", "rumor_crossed_border"]
    crossing = legs[-1]["payload"]
    assert crossing["from_settlement"] == sid_b
    assert crossing["to_settlement"] == sid_a
    assert crossing["carrier_family"] == "gemini"
    assert crossing["mutated"] is True
    gem = w.contact_ledger["by_family"]["gemini"]
    assert gem == {"hops": 1, "mutated": 1}


def test_rumor_fidelity_intact_hop():
    # A rumor that already carries its one allowed distortion suffix distorts
    # NO further (the DISTORTION_SUFFIX_CAP no-op) — the crossing still
    # fires, but with mutated=False: a faithful carriage.
    w = _honesty_world()
    res, carrier, target = _spread_foreign_rumor(
        w, text="Rex left — or so they say")
    legs = res["_multi"] if "_multi" in res else [res]
    assert [leg["kind"] for leg in legs] == \
        ["rumor_spread", "rumor_crossed_border"]  # no mutation leg
    assert legs[-1]["payload"]["mutated"] is False
    gem = w.contact_ledger["by_family"]["gemini"]
    assert gem == {"hops": 1, "mutated": 0}  # fidelity 1.0 for this hop


def test_rumor_no_crossing_within_town():
    w = _honesty_world()
    sid_a, _ = _towns(w)
    a_author = next(a for a in w.agents.values()
                    if a.origin_settlement_id == sid_a)
    source = w.mint_meme("rumor", "Rex borrowed the well bucket", a_author.id)
    carrier = next(a for a in w.agents.values()
                   if a.origin_settlement_id == sid_a and a.id != a_author.id)
    target = next(a for a in w.agents.values()
                  if a.origin_settlement_id == sid_a
                  and a.id not in (carrier.id, a_author.id))
    res = w.action_spread_rumor(carrier, target, meme_id=source.id)
    legs = [res] if "kind" in res else res["_multi"]
    assert not [leg for leg in legs if leg["kind"] == "rumor_crossed_border"]
    assert w.contact_ledger == {}


# ── 4. the honesty ledger rides the snapshot ────────────────────────────────

def test_ledger_round_trips_through_a_snapshot():
    w = _honesty_world()
    _spread_foreign_rumor(w)
    snap = copy.deepcopy(w.to_snapshot({}))
    assert snap["contact_ledger"] == w.contact_ledger
    restored = World.from_snapshot(snap, params=_params())
    assert restored.contact_ledger == w.contact_ledger
    assert {a.name: a.origin_settlement_id for a in restored.agents.values()} \
        == {a.name: a.origin_settlement_id for a in w.agents.values()}


def test_fresh_ledger_absent_from_snapshot():
    w = _honesty_world()
    assert "contact_ledger" not in w.to_snapshot({})


# ── 5. war scoping — grievances that name TOWNS ─────────────────────────────

def test_border_crime_heats_town_and_faction():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    _inject_factions(w)
    actor = w.agents[_half_ids(w, "a")[0]]
    victim = _half_ids(w, "b")[0]
    w._register_war_act(actor, "attack", victim)
    # The pre-EM-333 faction heat is untouched…
    assert w.grievance_between("fct_b", "fct_a") > 0
    # …and the TOWNS now hold the same story.
    assert w.grievance_between(sid_b, sid_a) > 0
    assert w.grievance_between(sid_a, sid_b) == 0  # directional


def test_same_town_crime_no_settlement_heat():
    w = _honesty_world(war=True)
    sid_a, _ = _towns(w)
    a_ids = _half_ids(w, "a")
    w.factions["fct_a1"] = {"id": "fct_a1", "name": "East Circle",
                            "members": [a_ids[0]]}
    w.factions["fct_a2"] = {"id": "fct_a2", "name": "West Circle",
                            "members": [a_ids[1]]}
    w._register_war_act(w.agents[a_ids[0]], "attack", a_ids[1])
    assert w.grievance_between("fct_a2", "fct_a1") > 0  # faction heat lives
    assert int(w.contact_ledger.get("crossings", 0)) == 0
    assert w.grievance_between(sid_a, sid_a) == 0


def test_settlement_grievance_event_names_towns():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    total = w.add_grievance(sid_a, sid_b, 30, "border raid")
    assert total == 30
    name_a = w.settlements[sid_a]["name"]
    name_b = w.settlements[sid_b]["name"]
    ev = next(e for e in w.pending_spawn_events
              if e["kind"] == "grievance_accrued")
    assert name_a in ev["text"] and name_b in ev["text"]
    anchor = min(w.settlements[sid_a]["members"])
    assert ev["actor_id"] == anchor  # the aggrieved town's lowest member


def test_declare_war_between_towns_scopes_to_settlements():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    _inject_factions(w)
    a_ids = _half_ids(w, "a")
    w.add_grievance("fct_a", "fct_b", 60, "grudges")  # past casus belli
    rule = RuleState(id="rule_war", effect="declare_war",
                     text="war on the other town", proposer_id=a_ids[0],
                     payload={"aggressor": "fct_a", "target": "fct_b",
                              "aims": "the well",
                              "grievance_snapshot": 60})
    w._on_rule_activated(rule)
    assert len(w.wars) == 1
    war = next(iter(w.wars.values()))
    assert war.scope == "settlement"
    assert war.belligerents == sorted([sid_a, sid_b])
    assert war.aggressor_id == sid_a
    ev = next(e for e in w.pending_spawn_events
              if e["kind"] == "war_declared")
    assert ev["payload"]["scope"] == "settlement"
    assert w.settlements[sid_a]["name"] in ev["text"]
    assert w.settlements[sid_b]["name"] in ev["text"]
    assert ev["payload"]["aggressor"] == "fct_a"  # the proposal record


def test_declare_war_unscoped_when_honesty_off():
    w = _honesty_world(war=True, honesty=False)
    _inject_factions(w)
    a_ids = _half_ids(w, "a")
    w.add_grievance("fct_a", "fct_b", 60, "grudges")
    rule = RuleState(id="rule_war", effect="declare_war",
                     text="war", proposer_id=a_ids[0],
                     payload={"aggressor": "fct_a", "target": "fct_b",
                              "aims": "the well", "grievance_snapshot": 60})
    w._on_rule_activated(rule)
    war = next(iter(w.wars.values()))
    assert war.scope == ""
    assert war.belligerents == ["fct_a", "fct_b"]
    assert "scope" not in war.to_dict()
    ev = next(e for e in w.pending_spawn_events
              if e["kind"] == "war_declared")
    assert "scope" not in ev["payload"]


def test_faction_war_id_is_byte_identical():
    # The pre-EM-333 seeded id format is untouched (the EM-155 keystone):
    # sha1 of the sorted pair + tick, scope absent from the key.
    w = _honesty_world(war=True)
    expected = "war_" + hashlib.sha1(
        f"fct_a:fct_b:{w.tick}".encode()).hexdigest()[:8]
    war = w.open_war("fct_b", "fct_a", "the well")
    assert war.id == expected
    assert war.scope == ""


def test_scoped_war_id_differs_from_faction_war_id():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    town_war = w.open_war(sid_a, sid_b, "the well", scope="settlement")
    faction_war = w.open_war(sid_a, sid_b, "the well")
    assert town_war.id != faction_war.id  # scope folds into the id seed
    assert town_war.scope == "settlement" and faction_war.scope == ""


def test_settlement_war_grinds_and_settles_through_the_shared_lane():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    w.params.war = WarParams(enabled=True, exhaustion_per_round=100,
                             exhaustion_cap=100, reparations_base=25)
    for aid in _half_ids(w, "a") + _half_ids(w, "b"):
        w.agents[aid].credits = 10
    war = w.open_war(sid_a, sid_b, "the well", scope="settlement")
    events = w.advance_war()
    # Exhaustion caps BOTH towns in one round → a tie collapses the AGGRESSOR.
    assert war.id not in w.wars  # settled + swept (the EM-259 endgame)
    assert any(e["kind"] == "war_exhausted" for e in events)
    loser = war.aggressor_id
    winner = sid_b if loser == sid_a else sid_a
    loser_credits = sum(w.agents[m].credits
                        for m in w.settlements[loser]["members"])
    winner_credits = sum(w.agents[m].credits
                         for m in w.settlements[winner]["members"])
    assert loser_credits < 10 * len(w.settlements[loser]["members"])
    assert winner_credits > 10 * len(w.settlements[winner]["members"])
    ev_text = [e["text"] for e in events if e["kind"] == "war_exhausted"]
    assert ev_text, "the collapse announces itself"
    assert w.settlements[loser]["name"] in ev_text[0]


def test_settlement_war_clears_town_grievances():
    w = _honesty_world(war=True)
    sid_a, sid_b = _towns(w)
    w.params.war = WarParams(enabled=True, exhaustion_per_round=100,
                             exhaustion_cap=100, reparations_base=0)
    w.add_grievance(sid_b, sid_a, 40, "border raid")
    w.open_war(sid_a, sid_b, "the well", scope="settlement")
    w.advance_war()
    assert w.grievance_between(sid_b, sid_a) == 0  # settled ⇒ ledger cooled

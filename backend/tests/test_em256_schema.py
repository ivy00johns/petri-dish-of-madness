# backend/tests/test_em256_schema.py
"""EM-256 — War data model schema (mirrors the test_em240_schema split).

  * WarState.to_dict — scalar core always rides; the stage-C combat ledgers
    (casualties/exhaustion) ride ONLY when non-empty (the Meme convention).
  * World.open_war — seeded war_<8hex> id (replay-stable), sorted exactly-two
    belligerents, idempotent re-open.
  * wars/grievances snapshot keys — only-when-non-empty; defensive restore
    (garbage rows dropped, heat clamped, dead heat never restored).
  * THE faction-snapshot-writer fix — faction records gain optional war_band /
    treasury_pledged written only-when-set AND the snapshot writer emits them
    (the plan's called-out hidden sub-task: without the writer fix they drop
    on every round-trip) AND the recompute continuity rebuild carries them.
  * the EM-257 read seams: casus_belli_targets / active_war_between /
    active_wars_for / _faction_leader.
"""
import copy
import json

from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState, WarState,
)
from petridish.config.loader import WorldParams, WarParams, _parse_war

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, **kw) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20, **kw)


def _world(agents: list[AgentState] | None = None, war: bool = True) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    w = World(params=_params(), places=places,
              agents=agents if agents is not None else [_a("ada"), _a("dot")])
    if war:
        w.params.war = {"enabled": True}
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── WarState.to_dict ──────────────────────────────────────────────────────────

def test_fresh_war_serializes_minimal_scalar_core():
    war = WarState(id="war_ab12cd34", belligerents=[FA, FB],
                   aggressor_id=FA, start_tick=7, aims="avenge the market")
    d = war.to_dict()
    assert d == {"id": "war_ab12cd34", "belligerents": [FA, FB],
                 "aggressor_id": FA, "start_tick": 7,
                 "aims": "avenge the market", "status": "active"}
    assert "casualties" not in d and "exhaustion" not in d


def test_combat_ledgers_ride_only_when_non_empty():
    war = WarState(id="war_ab12cd34", belligerents=[FA, FB],
                   aggressor_id=FA, start_tick=7,
                   casualties=["ada"], exhaustion={FA: 30})
    d = war.to_dict()
    assert d["casualties"] == ["ada"]
    assert d["exhaustion"] == {FA: 30}


# ── open_war: seeded + idempotent ─────────────────────────────────────────────

def test_open_war_id_is_seeded_and_replay_stable():
    w1, w2 = _world(), _world()
    w1.tick = w2.tick = 9
    a = w1.open_war(FA, FB, "aims")
    b = w2.open_war(FB, FA, "aims")            # order-independent (sorted pair)
    assert a.id == b.id
    assert a.id.startswith("war_") and len(a.id) == 4 + 8
    assert a.belligerents == sorted([FA, FB])
    assert a.aggressor_id == FA and b.aggressor_id == FB


def test_open_war_is_idempotent_same_key_returns_registered():
    w = _world()
    a = w.open_war(FA, FB, "first")
    b = w.open_war(FA, FB, "second")           # same pair + tick → SAME war
    assert a is b and len(w.wars) == 1
    assert a.aims == "first"


# ── snapshot: only-when-non-empty + defensive restore ─────────────────────────

def test_wars_and_grievances_absent_on_a_default_world():
    snap = _world(war=False).to_snapshot()
    assert "wars" not in snap
    assert "grievances" not in snap


def test_populated_wars_and_grievances_round_trip():
    w = _world()
    w.tick = 5
    war = w.open_war(FA, FB, "avenge")
    war.casualties = ["ada"]
    war.exhaustion = {FA: 20, FB: 55}
    w.grievances = {f"{FA}->{FB}": 60}
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)
    r = restored.wars[war.id]
    assert r.belligerents == [FA, FB] and r.status == "active"
    assert r.casualties == ["ada"] and r.exhaustion == {FA: 20, FB: 55}
    assert restored.grievances == {f"{FA}->{FB}": 60}


def test_restore_drops_garbage_war_rows_and_dead_heat():
    w = _world(war=False)
    snap = w.to_snapshot()
    snap["wars"] = {
        "war_ok123456": {"belligerents": [FA, FB], "aggressor_id": FA,
                         "start_tick": 1, "aims": "", "status": "weird"},
        "": {"belligerents": [FA, FB]},              # blank id → dropped
        "war_bad": "not-a-dict",                      # non-dict → dropped
        "war_one_side": {"belligerents": [FA]},       # not exactly 2 → dropped
    }
    snap["grievances"] = {f"{FA}->{FB}": 250,         # clamped to 100
                          f"{FB}->{FA}": 0,           # dead heat → dropped
                          "notakey": 5,               # no '->' → dropped
                          f"{FB}->{FA}x": -3}         # non-positive → dropped
    restored = World.from_snapshot(snap, params=_params())
    assert list(restored.wars) == ["war_ok123456"]
    assert restored.wars["war_ok123456"].status == "active"   # coerced
    assert restored.grievances == {f"{FA}->{FB}": 100}


# ── the faction-snapshot-writer fix (war_band / treasury_pledged) ─────────────

def test_faction_war_keys_emitted_only_when_set():
    w = _world(war=False)
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0, "members": ["ada"],
             "war_band": ["ada"], "treasury_pledged": 40},
        FB: {"name": "Dot's circle", "founded_tick": 0, "members": ["dot"]},
    }
    snap = w.to_snapshot()
    fa = snap["factions"][FA]
    fb = snap["factions"][FB]
    assert fa["war_band"] == ["ada"] and fa["treasury_pledged"] == 40
    assert "war_band" not in fb and "treasury_pledged" not in fb


def test_faction_war_keys_survive_a_round_trip():
    """THE explicit test the plan demands: the snapshot writer MUST emit
    war_band/treasury_pledged or they silently drop on every round-trip
    (the EM-240 faction-snapshot-writer lesson)."""
    w = _world(war=False)
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0, "members": ["ada"],
             "war_band": ["ada"], "treasury_pledged": 40},
    }
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    assert restored.factions[FA]["war_band"] == ["ada"]
    assert restored.factions[FA]["treasury_pledged"] == 40
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_recompute_continuity_carries_the_war_keys():
    """The OTHER faction writer: the per-round recompute's continuity rebuild
    must carry the durable extras or every round would wipe them."""
    agents = [_a(f"a{i}") for i in range(3)]
    w = _world(agents, war=False)
    for i in range(3):
        for j in range(3):
            if i != j:
                agents[i].relationships[agents[j].id] = RelationshipState(
                    type="ally", trust=40, interactions=3)
    w.recompute_factions()
    (fid, rec), = w.factions.items()
    rec["war_band"] = ["a0", "a1"]
    rec["treasury_pledged"] = 15
    w.recompute_factions()                     # a stable round — no diffs
    assert w.factions[fid]["war_band"] == ["a0", "a1"]
    assert w.factions[fid]["treasury_pledged"] == 15


# ── the EM-257 read seams ────────────────────────────────────────────────────

def _two_factions(w: World) -> None:
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0, "members": ["ada"]},
        FB: {"name": "Dot's circle", "founded_tick": 0, "members": ["dot"]},
    }


def test_casus_belli_targets_honors_threshold_and_existing_wars():
    w = _world()
    _two_factions(w)
    assert w.casus_belli_targets(FA) == []
    w.grievances[f"{FA}->{FB}"] = 49                  # below threshold (50)
    assert w.casus_belli_targets(FA) == []
    w.grievances[f"{FA}->{FB}"] = 50
    assert w.casus_belli_targets(FA) == [
        {"id": FB, "name": "Dot's circle", "grievance": 50}]
    w.open_war(FA, FB, "x")                           # already at war → gone
    assert w.casus_belli_targets(FA) == []


def test_casus_belli_targets_skips_vanished_factions():
    w = _world()
    _two_factions(w)
    w.grievances[f"{FA}->fct_ghost000"] = 90          # dissolved faction
    assert w.casus_belli_targets(FA) == []


def test_active_war_lookups():
    w = _world()
    war = w.open_war(FA, FB, "x")
    assert w.active_war_between(FB, FA) is war        # order-independent
    assert [x.id for x in w.active_wars_for(FA)] == [war.id]
    war.status = "settled"
    assert w.active_war_between(FA, FB) is None
    assert w.active_wars_for(FA) == []


def test_faction_leader_is_lowest_id_living_member():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram])
    w.factions = {FA: {"name": "x", "founded_tick": 0,
                       "members": ["bram", "ada"]}}
    assert w._faction_leader(FA) is ada
    ada.alive = False
    assert w._faction_leader(FA) is bram
    bram.alive = False
    assert w._faction_leader(FA) is None
    assert w._faction_leader("fct_ghost000") is None


# ── config block ─────────────────────────────────────────────────────────────

def test_war_params_defaults_and_parse():
    p = WarParams()
    assert p.enabled is False                          # DEFAULT OFF (golden)
    assert p.casus_belli_threshold == 50
    assert p.grievance_per_act == 6
    assert p.grievance_per_witness == 2
    assert p.grievance_decay == 1
    assert p.reparations_base == 25
    assert p.war_notoriety == 10
    assert _parse_war(None) == WarParams()
    assert _parse_war({"enabled": True, "war_notoriety": 3}) == WarParams(
        enabled=True, war_notoriety=3)


def test_war_enabled_accessor_conventions():
    w = _world(war=False)
    assert w.war_enabled() is False                    # dataclass default
    w.params.war = None                                # absent block
    assert w.war_enabled() is False
    w.params.war = {"enabled": True}                   # EM-155 dict convention
    assert w.war_enabled() is True

# backend/tests/test_em311_determinism.py
"""EM-311 — the Self-Authored Charters determinism golden (EM-155).

With charters disabled (the default) a world is BYTE-IDENTICAL to pre-EM-311: no
`charter` key on any agent dict, no charter seeding, and the default snapshot
round-trips byte-identically. A POPULATED charter world (agents carrying
self-authored charters at various revision counts) ALSO round-trips
byte-identically, so a fork/replay resumes the exact same declared identities —
the compounding-identity guarantee. normalize_charter is total (garbage → None,
never raises) and the enum grammar is enforced defensively on restore.
"""
import copy
import json

from petridish.engine.world import (
    World, AgentState, PlaceState, normalize_charter,
    AMBITION_KINDS, CHARTER_MAX_AMBITIONS, CHARTER_CREED_CAP,
)
from petridish.config.loader import WorldParams, CharterParams


def _params(enabled: bool = False, **overrides) -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        charters=CharterParams(enabled=enabled, **overrides),
    )


def _a(aid: str) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="townhall", energy=80.0, credits=20)


def _world(enabled: bool = False) -> World:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    return World(params=_params(enabled), places=places,
                 agents=[_a("ada"), _a("bram"), _a("dot")])


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── normalize_charter — total, bounded, enum-gated ───────────────────────────

def test_normalize_charter_is_total_and_bounds():
    assert normalize_charter(None) is None
    assert normalize_charter("nope") is None
    assert normalize_charter({}) is None
    assert normalize_charter({"ambitions": "seize_power"}) is None   # not a list
    assert normalize_charter({"ambitions": []}) is None              # empty
    assert normalize_charter({"ambitions": ["bogus"]}) is None       # off-grammar
    # dedupe (order-preserving), drop invalid, truncate to the cap
    c = normalize_charter({
        "ambitions": ["nope", "seize_power", "seize_power", "amass_wealth",
                      "sow_chaos", "claim_territory"],
        "creed": "X" * 500,
    })
    assert c["ambitions"] == ["seize_power", "amass_wealth", "sow_chaos"]
    assert len(c["ambitions"]) == CHARTER_MAX_AMBITIONS
    assert len(c["creed"]) == CHARTER_CREED_CAP
    assert c["revised_tick"] == 0 and c["revisions"] == 0
    # every legal kind normalizes to itself
    for k in AMBITION_KINDS:
        assert normalize_charter({"ambitions": [k]})["ambitions"] == [k]


def test_normalize_charter_coerces_meta_ints():
    c = normalize_charter({"ambitions": ["seize_power"],
                           "revised_tick": "junk", "revisions": -4})
    assert c["revised_tick"] == 0 and c["revisions"] == 0
    c2 = normalize_charter({"ambitions": ["seize_power"],
                            "revised_tick": 42, "revisions": 7})
    assert c2["revised_tick"] == 42 and c2["revisions"] == 7


# ── default world: inert + byte-identical (charters disabled by default) ─────

def test_default_world_agents_have_no_charter_key():
    snap = _world().to_snapshot()
    for a in snap["agents"]:
        assert "charter" not in a, "charter-off agent must omit the key"


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)
    for aid in w.agents:
        assert restored.agents[aid].charter is None


def test_pre_em311_snapshot_restores_charter_none():
    """An agent dict lacking `charter` (every pre-EM-311 snapshot) restores None."""
    legacy = {
        "agents": [{"id": "agent_ada", "name": "Ada", "personality": "",
                    "profile": "mock", "location": "plaza", "energy": 80.0,
                    "credits": 20}],
        "places": [{"id": "plaza", "name": "Plaza", "x": 0, "y": 0,
                    "kind": "social"}],
        "tick": 5, "day": 0, "round": 0,
    }
    restored = World.from_snapshot(legacy)
    assert restored.agents["agent_ada"].charter is None


# ── populated charter world: byte-identical round-trip ───────────────────────

def _charter_world() -> World:
    w = _world(enabled=True)
    w.tick = 4000
    # Ada: an amateur peacekeeper turned street-owner (the marquee arc).
    w.agents["ada"].charter = normalize_charter({
        "ambitions": ["claim_territory", "amass_wealth"],
        "creed": "I will own this street and everyone on it.",
        "revised_tick": 4000, "revisions": 5,
    })
    # Bram: a single-ambition charter with an empty creed (edge of the shape).
    w.agents["bram"].charter = normalize_charter({
        "ambitions": ["expose_a_conspiracy"], "creed": "",
        "revised_tick": 1200, "revisions": 2,
    })
    # Dot: never rewrote — still on the uniform seed.
    w.agents["dot"].charter = normalize_charter({
        "ambitions": ["keep_the_peace"],
        "creed": "I am still finding my place here.",
        "revised_tick": 0, "revisions": 0,
    })
    return w


def test_populated_charter_world_round_trips_byte_identical():
    w = _charter_world()
    snap1 = w.to_snapshot()
    assert snap1["agents"][0]["charter"]["ambitions"] == [
        "claim_territory", "amass_wealth"]
    restored = World.from_snapshot(copy.deepcopy(snap1),
                                   params=_params(enabled=True))
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_charter_world_survives_a_second_hop():
    w = _charter_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params(enabled=True))
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params(enabled=True))
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


def test_restore_drops_off_grammar_charter_defensively():
    """A tampered snapshot carrying an illegal ambition kind restores WITHOUT it
    (the enum grammar is enforced on the restore path, not just the write path)."""
    w = _world(enabled=True)
    snap = w.to_snapshot()
    snap["agents"][0]["charter"] = {
        "ambitions": ["seize_power", "___hacked___"],
        "creed": "c", "revised_tick": 3, "revisions": 1,
    }
    restored = World.from_snapshot(snap, params=_params(enabled=True))
    ch = restored.agents[snap["agents"][0]["id"]].charter
    assert ch["ambitions"] == ["seize_power"]        # illegal kind dropped
    # an ALL-illegal charter restores to None (not a charter)
    snap["agents"][0]["charter"] = {"ambitions": ["___all_bad___"]}
    restored2 = World.from_snapshot(snap, params=_params(enabled=True))
    assert restored2.agents[snap["agents"][0]["id"]].charter is None


# ── seeding — deterministic, idempotent, gated ───────────────────────────────

def test_seed_all_charters_noop_when_disabled():
    w = _world(enabled=False)
    w.seed_all_charters()
    for a in w.agents.values():
        assert a.charter is None


def test_seed_all_charters_uniform_and_idempotent():
    w = _world(enabled=True)
    w.seed_all_charters()
    seeds = [tuple(a.charter["ambitions"]) for a in w.agents.values()]
    assert all(s == ("keep_the_peace",) for s in seeds), "uniform baseline"
    # a self-authored charter is NEVER clobbered by a re-seed
    w.agents["ada"].charter = normalize_charter({"ambitions": ["sow_chaos"]})
    w.seed_all_charters()
    assert w.agents["ada"].charter["ambitions"] == ["sow_chaos"]


def test_seed_respects_config_and_stamps_tick():
    w = _world(enabled=True)
    w.tick = 7
    w.params.charters = CharterParams(
        enabled=True, seed_ambitions=["amass_wealth", "seize_power"],
        seed_creed="Coin and a crown.")
    w.seed_all_charters()
    ada = w.agents["ada"].charter
    assert ada["ambitions"] == ["amass_wealth", "seize_power"]
    assert ada["creed"] == "Coin and a crown."
    assert ada["revised_tick"] == 7 and ada["revisions"] == 0

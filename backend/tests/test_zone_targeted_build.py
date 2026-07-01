"""EM-266 (SC) — zone-targeted emergent building (Lane 1, backend).

An agent's `propose_project` gains an OPTIONAL `zone_id` targeting a city block
(planar face). SC is the payoff slice: it gives a build a zone TARGET and RECORDS
DEFIANCE — it NEVER enforces.

THE LAW (contract §0):
  1. The build ALWAYS succeeds — honor / ignore / break. Wrong-kind, over-cap, or
     piling into one zone all land. Defiance is a finding, not a bug.
  2. "Build nothing" stays valid (a zone may sit empty the whole run).
  3. Byte-identical / additive: `Building.zone_id` serialized ONLY when set; with
     no zone target OR GRAPH_ZONES_ENABLED off, behavior is byte-identical to pre-SC.
  4. Deterministic: zone_id + the zone_violation observation are pure functions of
     (build, buildings, zones) — no clock/random.

The World ctor mirrors test_zone_rules.py; `w.city_graph` is overridden with a
tiny controlled two-square graph so the zone ids under test are known exactly.
"""
from __future__ import annotations

import uuid as _uuidlib

import pytest

import petridish.engine.world as world_mod
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.citygraph import (
    CityGraph, CityNode, CityEdge, ZoneRule, planar_faces, zone_id_for,
    apply_zone_rule,
)
from petridish.config.loader import load_config


# ── fixtures ──────────────────────────────────────────────────────────────────

def _world() -> World:
    """A default-config world; `city_graph` is replaced per-test with a controlled
    graph so the zone ids are deterministic + known."""
    cfg = load_config()
    places = [
        PlaceState(id=p.id, name=p.name, x=p.x, y=p.y,
                   kind=p.kind, description=p.description,
                   district=p.district, neighborhood_id=p.neighborhood_id,
                   zone_kind=p.zone_kind)
        for p in cfg.places
    ]
    agents = [
        AgentState(id=f"agent_{a.name.lower()}", name=a.name,
                   personality=a.personality, profile=a.profile,
                   location=a.location,
                   energy=cfg.world.starting_energy,
                   credits=cfg.world.starting_credits)
        for a in cfg.agents
    ]
    return World(params=cfg.world, places=places, agents=agents)


def _square(prefix: str, ox: float, oz: float, size: float = 10.0) -> CityGraph:
    """One 4-node square block; `prefix` makes two squares' face ids distinct."""
    ids = [f"{prefix}:a", f"{prefix}:b", f"{prefix}:c", f"{prefix}:d"]
    nodes = [
        CityNode(id=ids[0], x=ox, z=oz),
        CityNode(id=ids[1], x=ox + size, z=oz),
        CityNode(id=ids[2], x=ox + size, z=oz + size),
        CityNode(id=ids[3], x=ox, z=oz + size),
    ]
    pairs = [(0, 1), (1, 2), (2, 3), (3, 0)]
    edges = [CityEdge(id=f"e:{prefix}:{i}->{j}", a=ids[i], b=ids[j]) for i, j in pairs]
    return CityGraph(seed=1, nodes=nodes, edges=edges)


def _two_zone_graph() -> CityGraph:
    """Two well-separated squares ⇒ two distinct planar faces (zone A, zone B)."""
    a = _square("za", 0.0, 0.0)
    b = _square("zb", 100.0, 100.0)
    return CityGraph(seed=1, nodes=a.nodes + b.nodes, edges=a.edges + b.edges)


def _install_two_zones(w: World) -> tuple[str, str]:
    """Override the world graph with the two-zone graph; return (zone_a, zone_b)."""
    w.city_graph = _two_zone_graph()
    zones = sorted(zone_id_for(f.boundary) for f in planar_faces(w.city_graph))
    assert len(zones) == 2, zones
    return zones[0], zones[1]


def _agent(w: World) -> AgentState:
    return next(iter(w.agents.values()))


def _enable(monkeypatch) -> None:
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)


def _violations(w: World) -> list[dict]:
    return [e for e in w.pending_spawn_events if e.get("kind") == "zone_violation"]


def _building(w: World, result: dict):
    return w.buildings[result["_building_id"]]


# ── flag ON: a valid zone_id is stored on the Building ─────────────────────────

def test_valid_zone_id_stored_on_building(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    r = w.action_propose_project(_agent(w), "Alpha", "house", 10, zone_id=zone_a)
    b = _building(w, r)
    assert b.zone_id == zone_a
    assert b.status == "planned"  # the build proceeded


# ── honor: kind matches, under cap ⇒ NO violation ─────────────────────────────

def test_honored_build_emits_no_violation(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=4))
    r = w.action_propose_project(_agent(w), "Home", "house", 10, zone_id=zone_a)
    assert _building(w, r).zone_id == zone_a
    assert _violations(w) == []  # honored: kind==hint, under cap


# ── break: kind mismatch ⇒ zone_violation (over_cap False), build still stands ─

def test_kind_mismatch_emits_violation_but_build_succeeds(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=None))
    r = w.action_propose_project(_agent(w), "Bazaar", "market", 10, zone_id=zone_a)
    b = _building(w, r)
    assert b.zone_id == zone_a
    assert b.status == "planned"  # NOT blocked, NOT coerced
    assert b.kind == "market"     # rendered with its own kind
    viols = _violations(w)
    assert len(viols) == 1
    p = viols[0]["payload"]
    assert p["zone_id"] == zone_a
    assert p["building_id"] == b.id
    assert p["kind"] == "market"
    assert p["rule_hint"] == "residential"
    assert p["over_cap"] is False
    assert p["tick"] == w.tick


# ── unmapped kind ⇒ treated as matching ⇒ NO false violation ──────────────────

def test_unmapped_kind_is_not_a_violation(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=None))
    # `generic` (the dominant agent-authored bucket) is UNMAPPED ⇒ no violation.
    r = w.action_propose_project(_agent(w), "Thing", "generic", 10, zone_id=zone_a)
    assert _building(w, r).zone_id == zone_a
    assert _violations(w) == []


# ── over-cap ⇒ zone_violation{over_cap:true} AND the build still succeeds ──────

def test_over_cap_emits_violation_and_build_succeeds(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=2))
    agent = _agent(w)
    # builds 1 + 2: honored (kind matches, at/under cap) ⇒ no violation.
    w.action_propose_project(agent, "H1", "house", 10, zone_id=zone_a)
    w.action_propose_project(agent, "H2", "house", 10, zone_id=zone_a)
    assert _violations(w) == []
    # build 3: count 3 > cap 2 ⇒ over_cap violation; the building still lands.
    r3 = w.action_propose_project(agent, "H3", "house", 10, zone_id=zone_a)
    b3 = _building(w, r3)
    assert b3.zone_id == zone_a
    assert b3.status == "planned"  # over cap, but it stands
    viols = _violations(w)
    assert len(viols) == 1
    assert viols[0]["payload"]["over_cap"] is True
    assert viols[0]["payload"]["building_id"] == b3.id
    # all three buildings really exist in the zone
    assert sum(1 for b in w.buildings.values() if b.zone_id == zone_a) == 3


# ── choke-the-core: MANY builds into one zone all succeed, no crash ───────────

def test_choke_the_core_all_succeed(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="civic",
                                           density_cap=1))
    agent = _agent(w)
    ids = []
    for i in range(30):
        r = w.action_propose_project(agent, f"Pile{i}", "library", 5, zone_id=zone_a)
        ids.append(r["_building_id"])
    # every build landed (no drop, no crash) and claims the zone
    assert len(set(ids)) == 30
    assert sum(1 for b in w.buildings.values() if b.zone_id == zone_a) == 30
    # everything past cap 1 recorded an over-cap violation (29 of the 30)
    over = [v for v in _violations(w) if v["payload"]["over_cap"] is True]
    assert len(over) == 29


# ── unresolvable zone_id ⇒ auto-placement fallback, build succeeds ────────────

def test_unresolvable_zone_id_falls_back(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    _install_two_zones(w)
    r = w.action_propose_project(_agent(w), "Ghost", "house", 10,
                                 zone_id="n:nope:1|n:nope:2|n:nope:3")
    b = _building(w, r)
    assert b.zone_id is None        # dropped (not a current face)
    assert b.status == "planned"    # build still succeeds
    assert _violations(w) == []     # no zone ⇒ no observation


# ── "build nothing" / no zone target is valid ─────────────────────────────────

def test_no_zone_target_is_valid(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    _install_two_zones(w)
    r = w.action_propose_project(_agent(w), "Plain", "house", 10)
    b = _building(w, r)
    assert b.zone_id is None
    assert "zone_id" not in b.to_dict()
    assert _violations(w) == []


# ── flag OFF ⇒ zone_id ignored, no events, byte-identical ─────────────────────

def test_flag_off_ignores_zone_id_byte_identical():
    # GRAPH_ZONES_ENABLED defaults OFF — no monkeypatch here.
    from petridish.agents.runtime import GRAPH_ZONES_ENABLED
    assert GRAPH_ZONES_ENABLED is False  # ships dormant

    # a build passing a (would-be valid) zone_id with the flag OFF...
    w1 = _world()
    zone_a, _ = _install_two_zones(w1)
    apply_zone_rule(w1.city_graph, ZoneRule(zone_id=zone_a, hint="civic", density_cap=1))
    r1 = w1.action_propose_project(_agent(w1), "Alpha", "market", 10, zone_id=zone_a)
    b1 = _building(w1, r1)
    assert b1.zone_id is None                 # ignored entirely
    assert "zone_id" not in b1.to_dict()      # not serialized
    assert _violations(w1) == []              # no observation stream when dormant

    # ...serializes byte-identically to the SAME build with NO zone arg at all.
    w2 = _world()
    _install_two_zones(w2)
    apply_zone_rule(w2.city_graph, ZoneRule(zone_id=zone_a, hint="civic", density_cap=1))
    r2 = w2.action_propose_project(_agent(w2), "Alpha", "market", 10)
    b2 = _building(w2, r2)
    # equalize the only random field (uuid building id) before comparing shapes
    d1, d2 = b1.to_dict(), b2.to_dict()
    d1.pop("id"); d2.pop("id")
    assert d1 == d2


# ── zone_id serialized ONLY when set ──────────────────────────────────────────

def test_zone_id_serialized_only_when_set(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    with_zone = _building(w, w.action_propose_project(
        _agent(w), "A", "house", 10, zone_id=zone_a))
    without = _building(w, w.action_propose_project(
        _agent(w), "B", "house", 10))
    assert with_zone.to_dict()["zone_id"] == zone_a
    assert "zone_id" not in without.to_dict()


# ── snapshot / replay / fork round-trip ───────────────────────────────────────

def test_snapshot_round_trip_preserves_zone_id(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, zone_b = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=1))
    agent = _agent(w)
    w.action_propose_project(agent, "Keeper", "house", 10, zone_id=zone_a)
    w.action_propose_project(agent, "Free", "house", 10)  # no zone
    snap = w.to_snapshot()

    w2 = World.from_snapshot(snap)
    by_name = {b.name: b for b in w2.buildings.values()}
    assert by_name["Keeper"].zone_id == zone_a
    assert by_name["Free"].zone_id is None
    # a fork of the restored world re-serializes identically (buildings block)
    assert w2.to_snapshot()["buildings"] == snap["buildings"]


# ── a pre-SC snapshot (no zone_id key) loads unchanged ────────────────────────

def test_pre_sc_snapshot_loads_unchanged():
    # A snapshot minted before SC: NO building carries a zone_id key.
    w = _world()
    r = w.action_propose_project(_agent(w), "Legacy", "house", 10)
    snap = w.to_snapshot()
    for bd in snap["buildings"]:
        assert "zone_id" not in bd  # pre-SC shape
    w2 = World.from_snapshot(snap)
    b = next(b for b in w2.buildings.values() if b.name == "Legacy")
    assert b.zone_id is None                     # absent ⇒ None
    assert "zone_id" not in b.to_dict()          # re-serializes byte-identically
    assert w2.to_snapshot()["buildings"] == snap["buildings"]


# ── determinism: a fixed action sequence ⇒ byte-identical placement + events ──

def _det_uuid():
    """A deterministic uuid4 stand-in: the counter rides the top 32 bits so
    `str(...)[:8]` is a distinct hex per call (real uuid4 is os.urandom-seeded)."""
    counter = {"n": 0}

    def _f():
        counter["n"] += 1
        return _uuidlib.UUID(int=counter["n"] << 96)

    return _f


def test_determinism_fixed_sequence_byte_identical(monkeypatch):
    _enable(monkeypatch)

    def _run() -> dict:
        # a fresh deterministic uuid stream per run ⇒ matching building ids
        world_mod.uuid.uuid4 = _det_uuid()
        w = _world()
        zone_a, zone_b = _install_two_zones(w)
        apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                               density_cap=2))
        agent = _agent(w)
        # honor, break, over-cap, other-zone, no-zone, unresolvable — a full mix.
        w.action_propose_project(agent, "H1", "house", 10, zone_id=zone_a)
        w.action_propose_project(agent, "Mkt", "market", 10, zone_id=zone_a)
        w.action_propose_project(agent, "H2", "house", 10, zone_id=zone_a)
        w.action_propose_project(agent, "H3", "house", 10, zone_id=zone_a)
        w.action_propose_project(agent, "B1", "house", 10, zone_id=zone_b)
        w.action_propose_project(agent, "Plain", "house", 10)
        w.action_propose_project(agent, "Ghost", "house", 10, zone_id="n:x|n:y|n:z")
        snap = w.to_snapshot()
        return {"buildings": snap["buildings"],
                "violations": [e["payload"] for e in _violations(w)]}

    original = world_mod.uuid.uuid4
    try:
        a = _run()
        b = _run()
    finally:
        world_mod.uuid.uuid4 = original

    assert a == b  # byte-identical placement + zone_violation stream
    # sanity: the mix really exercised the observation path
    assert any(v["over_cap"] for v in a["violations"])
    assert any(not v["over_cap"] for v in a["violations"])

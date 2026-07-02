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


# ── F1 (LOW): over_cap counts LIVE occupancy — DESTROYED builds are excluded ──
# A demolished building stays in self.buildings with status "destroyed" (never
# popped), so its zone_id tag persists. It must NOT inflate the over_cap count.

def test_over_cap_excludes_destroyed_buildings(monkeypatch):
    _enable(monkeypatch)
    w = _world()
    zone_a, _ = _install_two_zones(w)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=2))
    agent = _agent(w)
    # builds 1 + 2 fill the zone to its cap ⇒ no violation.
    r1 = w.action_propose_project(agent, "H1", "house", 10, zone_id=zone_a)
    r2 = w.action_propose_project(agent, "H2", "house", 10, zone_id=zone_a)
    assert _violations(w) == []
    # demolish BOTH — they remain in self.buildings as status "destroyed", still
    # tagged with zone_a (the tag persists through demolition).
    w._demolish_building(_building(w, r1), agent.id, "owner")
    w._demolish_building(_building(w, r2), agent.id, "owner")
    assert _building(w, r1).status == "destroyed"
    assert _building(w, r2).status == "destroyed"
    # build 3: LIVE occupancy is now 1 (< cap 2). The two DESTROYED builds must
    # NOT inflate the count into a false over_cap violation.
    r3 = w.action_propose_project(agent, "H3", "house", 10, zone_id=zone_a)
    b3 = _building(w, r3)
    assert b3.zone_id == zone_a
    assert b3.status == "planned"            # the build always stands
    over = [v for v in _violations(w) if v["payload"]["over_cap"] is True]
    assert over == []                        # live count 1 < cap 2 ⇒ no over_cap


# ── F2 (LOW, coherence): the nearby_zones "N built" count an agent PERCEIVES must
# use the SAME zone_id basis SC OBSERVES (the over_cap trigger) — not a decoupled
# point-in-polygon over the build's `location` place (which SC's zone_id never
# moves). Otherwise an agent piling into a capped zone reads "0 built" while
# over_cap violations fire, and gets no perceivable feedback to honor/defy the cap.

def _canonical_block(i0: int, j0: int) -> CityGraph:
    """One BLOCK_PITCH square from CANONICAL grid nodes (n:i:j), so
    `build_nearby_layout`'s road block parses the ids and reaches the zones line
    (synthetic za:*/zb:* ids don't parse ⇒ that helper early-returns None)."""
    from petridish.engine.citygraph import tile_center
    idx = [(i0, j0), (i0 + 5, j0), (i0 + 5, j0 + 5), (i0, j0 + 5)]
    nodes = [CityNode(id=f"n:{i}:{j}", x=tile_center(i), z=tile_center(j))
             for i, j in idx]
    ids = [n.id for n in nodes]
    pairs = [(0, 1), (1, 2), (2, 3), (3, 0)]
    edges = [CityEdge(id=f"e:{ids[a]}->{ids[b]}", a=ids[a], b=ids[b])
             for a, b in pairs]
    return CityGraph(seed=1, nodes=nodes, edges=edges)


def test_nearby_zones_built_count_uses_zone_id_basis(monkeypatch):
    from petridish.agents.runtime import build_nearby_layout, _point_in_poly
    _enable(monkeypatch)
    w = _world()
    w.city_graph = _canonical_block(2, 2)
    faces = planar_faces(w.city_graph)
    assert len(faces) == 1
    face = faces[0]
    zone_a = zone_id_for(face.boundary)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zone_a, hint="residential",
                                           density_cap=2))
    agent = _agent(w)
    place = w.places[agent.location]
    # the agent's location place sits OUTSIDE the zone polygon, so the OLD
    # point-in-poly basis (over the builds' `location`) would count these as 0.
    assert not _point_in_poly(float(place.x), float(place.y), face.poly)
    # pile 4 zone_id-tagged builds into zone_a — the SAME basis over_cap uses.
    for i in range(4):
        w.action_propose_project(agent, f"H{i}", "house", 10, zone_id=zone_a)
    # SC RECORDS 4 in the zone (over cap 2 ⇒ over_cap violations fired)...
    assert sum(1 for b in w.buildings.values() if b.zone_id == zone_a) == 4
    assert any(v["payload"]["over_cap"] for v in _violations(w))
    # ...and the agent now PERCEIVES the same 4 (was "0 built" under point-in-poly).
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "cap 2" in line
    assert "4 built" in line
    assert "0 built" not in line


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


# ── fix-wave A3 — perception names `zone_id`; dispatch aliases `zone` → `zone_id` ─
# The nearby-zones clause used to tell agents to "pass zone=<id>" but the schema
# (:253) and dispatch (:6138) read ONLY `zone_id`, so SC targeting could never fire.
# The perception now says `zone_id=<id>`, and the dispatch aliases a stray `zone`
# arg onto `zone_id` (when zone_id is absent) for robustness against replayed/old
# emissions.

def test_nearby_zones_perception_uses_zone_id_arg_name(monkeypatch):
    from petridish.agents.runtime import build_nearby_layout
    _enable(monkeypatch)
    w = _world()
    w.city_graph = _canonical_block(2, 2)
    place = w.places[_agent(w).location]
    line = build_nearby_layout(w, place)
    assert line is not None and "nearby zones:" in line.lower()
    # the perception must name the SAME arg the schema/dispatch read.
    assert "pass zone_id=<id>" in line
    assert "pass zone=<id>" not in line


def _runtime(w: World):
    from petridish.agents.runtime import AgentRuntime
    from petridish.providers.router import Router
    from petridish.config.loader import ModelProfile
    return AgentRuntime(w, Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        cache_enabled=False))


def test_dispatch_aliases_zone_arg_onto_zone_id(monkeypatch):
    # A `zone` arg with NO `zone_id` (an old-styled / replayed emission) must still
    # target the zone — the dispatch aliases it onto zone_id.
    _enable(monkeypatch)
    w = _world()
    zone_a, _zb = _install_two_zones(w)
    rt = _runtime(w)
    agent = _agent(w)
    rt._apply_action_inner(
        agent,
        {"action": "propose_project",
         "args": {"name": "Aliased", "kind": "house", "funds_required": 10,
                  "zone": zone_a}},
        "P", "#fff")
    b = next(b for b in w.buildings.values() if b.name == "Aliased")
    assert b.zone_id == zone_a


def test_dispatch_zone_id_wins_over_zone_when_both_present(monkeypatch):
    # When both are present, the explicit `zone_id` is authoritative (the alias only
    # fills in when zone_id is absent).
    _enable(monkeypatch)
    w = _world()
    zone_a, zone_b = _install_two_zones(w)
    rt = _runtime(w)
    agent = _agent(w)
    rt._apply_action_inner(
        agent,
        {"action": "propose_project",
         "args": {"name": "Both", "kind": "house", "funds_required": 10,
                  "zone_id": zone_a, "zone": zone_b}},
        "P", "#fff")
    b = next(b for b in w.buildings.values() if b.name == "Both")
    assert b.zone_id == zone_a

"""EM-265 (SB) — vote-gated set_zone_rule governance effect + zone perception.

set_zone_rule is a new rule effect on the unified action_propose_rule machinery
(same one-shot, no-renewal, per-target shape as EM-244 demolish_road / EM-245
adopt_master_plan): propose at a governance place → action_vote → _evaluate_rule
ratifies at 0.7 supermajority → _on_rule_activated applies apply_zone_rule on the
CityGraph + parks a zone_rule_set event. Ratification is SYNCHRONOUS: the
threshold-crossing action_vote calls _on_rule_activated itself.

LAW (contract §0): advisory ONLY — a ratified rule changes NO build/placement/
outcome in SB; zone_rules is additive (serialized only when non-empty) so pre-SB
snapshots stay byte-identical; everything is deterministic (no clock/random) and
round-trips through snapshot/replay/fork byte-identically.

The World ctor mirrors run.py / test_layout_governance.py: World(params=, places=,
agents=) from the embedded default config; all agents move to a governance place so
action_propose_rule's governance_here gate passes.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.citygraph import (
    CityGraph, CityNode, CityEdge, ZoneRule, planar_faces, zone_id_for,
    apply_zone_rule, tile_center,
)
from petridish.config.loader import load_config, ModelProfile
from petridish.providers.router import Router


# ── fixtures ──────────────────────────────────────────────────────────────────

def _gov_world() -> World:
    """A world (default config: 5 agents, classic_grid city) with every agent at
    the governance place so propose_rule is allowed."""
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
    w = World(params=cfg.world, places=places, agents=agents)
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    return w


def _router() -> Router:
    return Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                color="#2ecc71")], cache_enabled=False)


def _ratify(w: World, rule):
    """Cast yes from every living agent; the threshold-crossing vote activates +
    applies the rule synchronously."""
    for a in w.agents.values():
        w.action_vote(a, rule.id, True)
    return rule


def _zone_ids(w: World) -> list[str]:
    return [zone_id_for(f.boundary) for f in planar_faces(w.city_graph)]


def _square(prefix: str, ox: float, oz: float, size: float = 10.0) -> CityGraph:
    """A single 4-node square block at origin (ox, oz). Node ids carry `prefix` so
    two squares at the SAME coords have DISTINCT face ids (the morph-survival
    re-point case: renamed nodes, identical geometry)."""
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


# ── propose → 0.7 vote → activate + zone_rule_set ─────────────────────────────

def test_propose_and_ratify_set_zone_rule_applies_and_emits_event():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "zone it residential",
        target=zid, hint="residential", density_cap=4)
    assert ok, reason
    _ratify(w, rule)
    assert rule.effect == "set_zone_rule"
    assert rule.status == "active"
    # apply_zone_rule landed exactly one rule on the zone
    matches = [r for r in w.city_graph.zone_rules if r.zone_id == zid]
    assert len(matches) == 1
    assert matches[0].hint == "residential"
    assert matches[0].density_cap == 4
    # the zone_rule_set event was parked in the outbox with the right payload
    evt = next(e for e in w.pending_spawn_events if e.get("kind") == "zone_rule_set")
    assert evt["payload"]["zone_id"] == zid
    assert evt["payload"]["hint"] == "residential"
    assert evt["payload"]["density_cap"] == 4
    assert evt["payload"]["proposal_id"] == rule.id
    assert "tick" in evt["payload"]


def test_set_zone_rule_accepts_null_density_cap():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "open space", zone_id=zid, hint="open",
        density_cap=None)
    assert ok, reason
    _ratify(w, rule)
    r = next(r for r in w.city_graph.zone_rules if r.zone_id == zid)
    assert r.density_cap is None


def test_set_zone_rule_needs_supermajority_not_simple_majority():
    # 0.7 of 5 living = ceil(3.5) = 4 yes. A simple majority (3) must NOT ratify.
    w = _gov_world()
    agents = list(w.agents.values())
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(
        agents[0], "set_zone_rule", "x", target=zid, hint="market")
    assert ok, reason
    for a in agents[:3]:  # only 3 yes
        w.action_vote(a, rule.id, True)
    assert rule.status == "proposed"
    assert not w.city_graph.zone_rules  # nothing applied below threshold
    w.action_vote(agents[3], rule.id, True)  # 4th yes crosses 0.7
    assert rule.status == "active"
    assert any(r.zone_id == zid for r in w.city_graph.zone_rules)


def test_below_threshold_no_rule_applied():
    w = _gov_world()
    agents = list(w.agents.values())
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(
        agents[0], "set_zone_rule", "x", target=zid, hint="civic")
    assert ok, reason
    # 3 NO votes (> floor(5/2)=2) reject it
    for a in agents[:3]:
        w.action_vote(a, rule.id, False)
    assert rule.status == "rejected"
    assert not w.city_graph.zone_rules


# ── validation: unknown zone / bad hint / bad cap ─────────────────────────────

def test_unknown_zone_id_rejected():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "x", target="n:nope|n:also-nope", hint="market")
    assert not ok and rule is None
    assert "zone" in reason.lower()


def test_bad_hint_rejected():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, _ = w.action_propose_rule(
        agent, "set_zone_rule", "x", target=zid, hint="industrial")
    assert not ok and "hint" in reason.lower()


def test_negative_density_cap_rejected():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, _ = w.action_propose_rule(
        agent, "set_zone_rule", "x", target=zid, hint="market", density_cap=-1)
    assert not ok and "cap" in reason.lower()


def test_set_zone_rule_requires_governance_place():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    non_gov = next(p for p in w.places.values() if p.kind != "governance")
    agent.location = non_gov.id
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "x", target=zid, hint="market")
    assert not ok and rule is None


# ── duplicate-open guard (per zone_id) ────────────────────────────────────────

def test_duplicate_open_vote_blocked_per_zone():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zids = _zone_ids(w)
    z0, z1 = zids[0], zids[1]
    ok, _, _ = w.action_propose_rule(agent, "set_zone_rule", "a", target=z0, hint="market")
    assert ok
    # SAME zone, still open → rejected
    ok, reason, _ = w.action_propose_rule(agent, "set_zone_rule", "b", target=z0, hint="civic")
    assert not ok and "already open" in reason.lower()
    # DIFFERENT zone → allowed (two distinct zones may have open votes)
    ok, reason, _ = w.action_propose_rule(agent, "set_zone_rule", "c", target=z1, hint="open")
    assert ok, reason


# ── no-renewal: a passed rule re-proposed on the same zone APPLIES afresh ──────

def test_set_zone_rule_never_renews_last_wins():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, _, r1 = w.action_propose_rule(agent, "set_zone_rule", "res", target=zid,
                                      hint="residential", density_cap=2)
    assert ok
    _ratify(w, r1)
    assert r1.status == "active"
    # A SECOND zone rule on the SAME zone must APPLY (not be misclassified a
    # renewal — set_zone_rule is a one-shot per-zone act). last-wins replaces.
    ok, _, r2 = w.action_propose_rule(agent, "set_zone_rule", "mkt", target=zid,
                                      hint="market", density_cap=9)
    assert ok
    _ratify(w, r2)
    assert r2.status == "active", f"2nd zone rule was {r2.status} (renewal bug)"
    matches = [r for r in w.city_graph.zone_rules if r.zone_id == zid]
    assert len(matches) == 1  # one rule per zone
    assert matches[0].hint == "market" and matches[0].density_cap == 9


# ── runtime front-gate AGREES with the world ──────────────────────────────────

def test_runtime_gate_accepts_valid_and_rejects_unknown_zone(monkeypatch):
    from petridish.agents.runtime import _validate_world
    # EM-265 fix: set_zone_rule is offered on the agent surface ONLY behind the
    # GRAPH_ZONES_ENABLED flag — enable it so the effect-specific validation is
    # reached (this test goes THROUGH the runtime gate).
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    # the propose_rule front-gate is skill-gated (rhetoric); grant it so the
    # effect-specific zone validation is reached (the only thing under test here).
    gate = w.skill_gate_for("propose_rule")
    if gate is not None:
        agent.skills[gate[0]] = gate[1]
    zid = _zone_ids(w)[0]
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "x", "zone_id": zid,
                  "hint": "residential", "density_cap": 4}},
        agent, w)
    assert not err or "invalid effect" not in err, err
    # unknown zone → gate rejects (mirrors the world)
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "x", "zone_id": "n:nope",
                  "hint": "market"}},
        agent, w)
    assert err and "zone" in err.lower()
    # bad hint → gate rejects
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "x", "zone_id": zid,
                  "hint": "industrial"}},
        agent, w)
    assert err and "hint" in err.lower()


def test_propose_rule_threads_zone_args_through_dispatch(monkeypatch):
    from petridish.agents.runtime import AgentRuntime
    # EM-265 fix: the dispatch path runs through the runtime gate, so the flag must
    # be ON for set_zone_rule to be accepted.
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    rt = AgentRuntime(w, _router())
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    evt = rt._apply_action_inner(
        agent,
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "zone it civic",
                  "zone_id": zid, "hint": "civic", "density_cap": 3}},
        "P", "#fff")
    assert evt["kind"] == "rule_proposed", evt
    rule = w.rules[evt["payload"]["rule_id"]]
    assert rule.effect == "set_zone_rule"
    assert rule.payload.get("zone_id") == zid
    assert rule.payload.get("hint") == "civic"
    assert rule.payload.get("density_cap") == 3


# ── morph-survival (§4) — keep / re-point / drop, never mis-attach, never crash ─

def test_morph_survival_keeps_rule_when_block_id_unchanged():
    w = _gov_world()
    g = _square("A", 0, 0)
    f = planar_faces(g)[0]
    zid = zone_id_for(f.boundary)
    g.zone_rules = [ZoneRule(zone_id=zid, hint="market", density_cap=2)]
    w.city_graph = g
    events = w._reconcile_zone_rules_after_morph({zid: f.centroid})
    assert [r.zone_id for r in w.city_graph.zone_rules] == [zid]  # kept, unchanged
    assert not any(e["kind"] == "zone_rule_dropped" for e in events)


def test_morph_survival_repoints_rule_to_same_block_renamed_nodes():
    w = _gov_world()
    gA = _square("A", 0, 0)
    fA = planar_faces(gA)[0]
    zidA = zone_id_for(fA.boundary)
    # post-morph: the SAME geometry, DIFFERENT node ids ⇒ a new face id, same centroid
    gB = _square("B", 0, 0)
    zidB = zone_id_for(planar_faces(gB)[0].boundary)
    assert zidA != zidB
    gB.zone_rules = [ZoneRule(zone_id=zidA, hint="civic", density_cap=None)]
    w.city_graph = gB
    events = w._reconcile_zone_rules_after_morph({zidA: fA.centroid})
    assert len(w.city_graph.zone_rules) == 1
    assert w.city_graph.zone_rules[0].zone_id == zidB  # re-pointed by centroid
    assert w.city_graph.zone_rules[0].hint == "civic"
    assert not any(e["kind"] == "zone_rule_dropped" for e in events)


def test_morph_survival_drops_rule_when_block_gone():
    w = _gov_world()
    gA = _square("A", 0, 0)
    fA = planar_faces(gA)[0]
    zidA = zone_id_for(fA.boundary)
    # post-morph: a block FAR away (no centroid match) ⇒ the rule must drop cleanly
    gFar = _square("B", 1000, 1000)
    gFar.zone_rules = [ZoneRule(zone_id=zidA, hint="market", density_cap=1)]
    w.city_graph = gFar
    events = w._reconcile_zone_rules_after_morph({zidA: fA.centroid})
    assert not w.city_graph.zone_rules  # dropped
    drop = next(e for e in events if e["kind"] == "zone_rule_dropped")
    assert drop["payload"]["zone_id"] == zidA


def test_morph_survival_end_to_end_pentagon_drops_grid_rule_no_crash():
    # A grid block is zoned, then the town morphs to a pentagon (disjoint node ids
    # + geometry). The grid block is destroyed → its rule drops cleanly, logged,
    # never mis-attached to a pentagon face, never a crash.
    w = _gov_world()
    zid = _zone_ids(w)[0]
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zid, hint="residential",
                                           density_cap=None))
    assert len(w.city_graph.zone_rules) == 1
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    all_events: list[dict] = []
    for _ in range(500):  # generous bound; converges well within
        if w.master_plan is None:
            break
        all_events.extend(w.step_master_plan_morph())
    assert w.master_plan is None, "morph never converged"
    # the grid block is gone → the rule dropped + was logged
    assert not any(r.zone_id == zid for r in w.city_graph.zone_rules)
    assert any(e["kind"] == "zone_rule_dropped" for e in all_events)
    # NEVER mis-attached: every surviving rule binds a REAL current face
    post_ids = {zone_id_for(f.boundary) for f in planar_faces(w.city_graph)}
    assert all(r.zone_id in post_ids for r in w.city_graph.zone_rules)


def test_rule_free_morph_emits_no_zone_events_byte_identical():
    # A morph with NO zone rules must behave exactly as pre-SB (no reconcile churn).
    w = _gov_world()
    assert not w.city_graph.zone_rules
    w.master_plan = {"kind": "ring", "params": {}, "seed": w.city_seed}
    events: list[dict] = []
    for _ in range(500):
        if w.master_plan is None:
            break
        events.extend(w.step_master_plan_morph())
    assert not any(e["kind"] == "zone_rule_dropped" for e in events)
    assert not w.city_graph.zone_rules


# ── snapshot / replay / fork byte-identical + pre-SB unchanged (law §0.1/§0.3) ─

def test_ratified_zone_rule_survives_snapshot_round_trip():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(agent, "set_zone_rule", "x",
                                             target=zid, hint="market", density_cap=5)
    assert ok, reason
    _ratify(w, rule)
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()  # byte-identical
    r = next(r for r in w2.city_graph.zone_rules if r.zone_id == zid)
    assert r.hint == "market" and r.density_cap == 5


def test_zone_rule_fork_round_trips_byte_identically():
    # fork == load from a prior snapshot; a double round-trip must be byte-stable.
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, _, rule = w.action_propose_rule(agent, "set_zone_rule", "x", target=zid,
                                        hint="civic", density_cap=None)
    assert ok
    _ratify(w, rule)
    snap1 = w.to_snapshot()
    w2 = World.from_snapshot(snap1)
    w3 = World.from_snapshot(w2.to_snapshot())
    assert w3.city_graph.to_dict() == w.city_graph.to_dict()


def test_replaying_same_zone_proposals_yields_identical_graph():
    def _run() -> World:
        w = _gov_world()
        agent = next(iter(w.agents.values()))
        zids = _zone_ids(w)
        ok, _, r1 = w.action_propose_rule(agent, "set_zone_rule", "a",
                                          target=zids[0], hint="residential",
                                          density_cap=3)
        assert ok
        _ratify(w, r1)
        ok, _, r2 = w.action_propose_rule(agent, "set_zone_rule", "b",
                                          target=zids[1], hint="market",
                                          density_cap=None)
        assert ok
        _ratify(w, r2)
        return w

    a, b = _run(), _run()
    assert a.city_graph.to_dict() == b.city_graph.to_dict()


def test_pre_sb_snapshot_has_no_zone_rules_key_and_loads_unchanged():
    # No rule ratified ⇒ zone_rules empty ⇒ the key is OMITTED (byte-identical to
    # a pre-SB snapshot), and it round-trips to an empty list.
    w = _gov_world()
    snap = w.to_snapshot()
    assert "zone_rules" not in snap["city_graph"]
    w2 = World.from_snapshot(snap)
    assert w2.city_graph.zone_rules == []
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()


def test_zone_rules_serialized_only_when_non_empty():
    w = _gov_world()
    assert "zone_rules" not in w.city_graph.to_dict()
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=_zone_ids(w)[0], hint="open"))
    assert "zone_rules" in w.city_graph.to_dict()


# ── advisory only: a ratified rule changes NO build/placement/outcome ──────────

def test_ratified_zone_rule_does_not_mutate_graph_topology():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    before_nodes = [n.to_dict() for n in w.city_graph.nodes]
    before_edges = [e.to_dict() for e in w.city_graph.edges]
    before_cars = w.city_graph.car_policy
    zid = _zone_ids(w)[0]
    ok, _, rule = w.action_propose_rule(agent, "set_zone_rule", "x", target=zid,
                                        hint="market", density_cap=2)
    assert ok
    _ratify(w, rule)
    # only zone_rules grew; nodes/edges/car_policy untouched (additive metadata)
    assert [n.to_dict() for n in w.city_graph.nodes] == before_nodes
    assert [e.to_dict() for e in w.city_graph.edges] == before_edges
    assert w.city_graph.car_policy == before_cars


# ── nearby_zones perception: present / district-scoped / bounded / omitted ─────

def _corner_place() -> PlaceState:
    # near the grid's NE corner node so the nearest node has OPEN (extendable) dirs
    return PlaceState(id="corner", name="NE Corner", x=60, y=60, kind="social")


def test_nearby_zones_present_and_size_bounded(monkeypatch):
    from petridish.agents.runtime import build_nearby_layout, _NEARBY_ZONES_MAX
    w = _gov_world()
    # EM-265 fix: the block is gated on the GRAPH_ZONES_ENABLED flag (NOT on a rule
    # existing), so a zoning-free prompt stays byte-identical to pre-SB (law §0.1).
    # Activate the flag; a rule on a face gives it a hint to surface.
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=_zone_ids(w)[0], hint="open"))
    line = build_nearby_layout(w, _corner_place())
    assert line is not None
    assert "nearby zones:" in line.lower()
    # hard line cap: at most _NEARBY_ZONES_MAX zones listed (each clause has "lots")
    assert line.lower().count(" lots") <= _NEARBY_ZONES_MAX


def test_nearby_zones_district_scoped_not_whole_graph(monkeypatch):
    # 25 grid faces exist, but only the nearest few are surfaced (diet discipline).
    from petridish.agents.runtime import build_nearby_layout, _NEARBY_ZONES_MAX
    w = _gov_world()
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=_zone_ids(w)[0], hint="civic"))
    assert len(planar_faces(w.city_graph)) > _NEARBY_ZONES_MAX
    line = build_nearby_layout(w, _corner_place())
    assert line is not None
    assert line.lower().count(" lots") <= _NEARBY_ZONES_MAX


def test_nearby_zones_omitted_when_no_rules_byte_identical():
    # The §0.1 guarantee: with the GRAPH_ZONES_ENABLED flag at its default OFF, the
    # block is omitted entirely (the zoning-free prompt is byte-identical to pre-SB),
    # even though faces exist and there are no rules. (Flag-OFF path, default state.)
    from petridish.agents.runtime import build_nearby_layout, GRAPH_ZONES_ENABLED
    assert GRAPH_ZONES_ENABLED is False  # ships dormant by default
    w = _gov_world()
    assert not w.city_graph.zone_rules and planar_faces(w.city_graph)
    line = build_nearby_layout(w, _corner_place())
    assert line is not None  # the EM-243 road line still builds
    assert "nearby zones" not in line.lower()


def test_nearby_zones_reports_hint_and_cap_for_ruled_zone(monkeypatch):
    from petridish.agents.runtime import build_nearby_layout
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    place = _corner_place()
    # zone the face NEAREST the place so it appears in the (nearest-first) block
    px, pz = float(place.x), float(place.y)
    nearest = min(planar_faces(w.city_graph),
                  key=lambda f: (f.centroid["x"] - px) ** 2 + (f.centroid["z"] - pz) ** 2)
    zid = zone_id_for(nearest.boundary)
    apply_zone_rule(w.city_graph, ZoneRule(zone_id=zid, hint="market", density_cap=3))
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "market" in line.lower()
    assert "cap 3" in line.lower()
    assert "built" in line.lower()


def test_nearby_zones_omitted_when_no_faces(monkeypatch):
    # A path graph (one edge, no enclosed face) still has extendable directions, so
    # the layout line builds — but the zones block is OMITTED (no faces).
    from petridish.agents.runtime import build_nearby_layout
    # flag ON (the block is enabled) — yet there are no faces to list, so the block
    # must still be omitted regardless.
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    w.city_graph = CityGraph(
        seed=1,
        nodes=[CityNode(id="n:2:2", x=tile_center(2), z=tile_center(2)),
               CityNode(id="n:7:2", x=tile_center(7), z=tile_center(2))],
        edges=[CityEdge(id="e:n:2:2->n:7:2", a="n:2:2", b="n:7:2")],
        # a stray rule present, but with the flag ON the block is gated on the flag,
        # not the rule; there are still no faces to list, so it must be omitted.
        zone_rules=[ZoneRule(zone_id="gone", hint="market")],
    )
    place = PlaceState(id="p", name="On A Road", x=tile_center(2), y=tile_center(2),
                       kind="social")
    line = build_nearby_layout(w, place)
    assert line is not None  # extendable dirs exist
    assert "nearby zones" not in line.lower()  # but no faces → block omitted


def test_nearby_zones_deterministic_names():
    # zone names are seeded (city_seed, zone_id) → stable across calls/replay.
    from petridish.agents.runtime import _zone_display_name
    w = _gov_world()
    zid = _zone_ids(w)[0]
    assert _zone_display_name(w, zid) == _zone_display_name(w, zid)


# ── EM-265 fix: GRAPH_ZONES_ENABLED flag gates the AGENT SURFACE (bootstrap) ────

def test_graph_zones_flag_defaults_off():
    # SB ships DORMANT: the backend agent-surface flag is OFF by default, mirroring
    # the frontend GRAPH_LOTS_ENABLED.
    from petridish.agents import runtime
    assert runtime.GRAPH_ZONES_ENABLED is False


def test_runtime_gate_rejects_set_zone_rule_when_flag_off():
    # OFF path (default): set_zone_rule is NOT offered on the agent surface, so the
    # runtime gate rejects it as an invalid effect BEFORE the zone-specific checks —
    # agent behavior is byte-identical to pre-SB.
    from petridish.agents.runtime import _validate_world
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    gate = w.skill_gate_for("propose_rule")
    if gate is not None:
        agent.skills[gate[0]] = gate[1]
    zid = _zone_ids(w)[0]
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "x", "zone_id": zid,
                  "hint": "residential", "density_cap": 4}},
        agent, w)
    assert err and "invalid effect" in err.lower()
    # set_zone_rule is NOT among the effects the gate would accept while dormant
    assert "valid:" in err.lower() and "'set_zone_rule'" not in err.split("Valid:")[1]


def test_dispatch_rejects_set_zone_rule_when_flag_off():
    # OFF path: the GATED dispatch (_apply_steps runs _validate_world → dispatch)
    # refuses set_zone_rule — it emits a parse_failure, never rule_proposed, and no
    # zone rule is applied, so SB ships byte-identical / dormant. (The world method
    # action_propose_rule itself stays directly callable — only the agent surface is
    # gated.)
    from petridish.agents.runtime import AgentRuntime
    w = _gov_world()
    rt = AgentRuntime(w, _router())
    agent = next(iter(w.agents.values()))
    gate = w.skill_gate_for("propose_rule")
    if gate is not None:
        agent.skills[gate[0]] = gate[1]
    zid = _zone_ids(w)[0]
    chain, results = rt._apply_steps(
        agent,
        [{"action": "propose_rule",
          "args": {"effect": "set_zone_rule", "text": "zone it civic",
                   "zone_id": zid, "hint": "civic", "density_cap": 3}}],
        "P", "#fff", "")
    assert not any(e["kind"] == "rule_proposed" for e in chain), chain
    assert any(e["kind"] == "parse_failure" for e in chain)
    assert not w.city_graph.zone_rules  # nothing applied while dormant


def test_bootstrap_nearby_zones_lists_unzoned_faces_when_flag_on_zero_rules(monkeypatch):
    # THE BOOTSTRAP REGRESSION (chicken-and-egg fix): with GRAPH_ZONES_ENABLED ON
    # and ZERO zone rules ratified, build_nearby_layout STILL surfaces a nearby_zones
    # block listing the district's UNZONED faces — so an agent perceives a real
    # zone_id to propose the FIRST set_zone_rule. (Pre-fix the block was gated on
    # zone_rules being non-empty ⇒ no rule ⇒ no perceivable zone ⇒ no first rule.)
    from petridish.agents.runtime import build_nearby_layout, _NEARBY_ZONES_MAX
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    assert not w.city_graph.zone_rules          # zero rules ratified
    assert planar_faces(w.city_graph)            # but faces exist
    line = build_nearby_layout(w, _corner_place())
    assert line is not None
    assert "nearby zones:" in line.lower()       # the block IS present
    assert "unzoned" in line.lower()             # listing UNZONED faces (no rules yet)
    assert "cap" not in line.lower()             # no density caps without rules
    assert line.lower().count(" lots") <= _NEARBY_ZONES_MAX  # still diet-bounded


def test_agent_path_propose_vote_activate_through_runtime_gate(monkeypatch):
    # ON path, end-to-end through the RUNTIME agent surface: an agent proposes
    # set_zone_rule via the GATED dispatch (_apply_steps runs _validate_world →
    # dispatch — the gate ACCEPTS it), then the town ratifies via action_vote → the
    # rule activates + applies on the CityGraph.
    from petridish.agents.runtime import AgentRuntime
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    rt = AgentRuntime(w, _router())
    proposer = next(iter(w.agents.values()))
    gate = w.skill_gate_for("propose_rule")
    if gate is not None:
        proposer.skills[gate[0]] = gate[1]
    zid = _zone_ids(w)[0]
    chain, results = rt._apply_steps(
        proposer,
        [{"action": "propose_rule",
          "args": {"effect": "set_zone_rule", "text": "zone it residential",
                   "zone_id": zid, "hint": "residential", "density_cap": 4}}],
        "P", "#fff", "")
    proposed = next(e for e in chain if e["kind"] == "rule_proposed")
    rule = w.rules[proposed["payload"]["rule_id"]]
    assert rule.effect == "set_zone_rule"
    _ratify(w, rule)
    assert rule.status == "active"
    matches = [r for r in w.city_graph.zone_rules if r.zone_id == zid]
    assert len(matches) == 1
    assert matches[0].hint == "residential" and matches[0].density_cap == 4


# ── FINDING #2 — TOCTOU orphan rule: a zone destroyed BETWEEN propose and the ───
# threshold-crossing vote must NOT activate onto a non-existent zone. action_propose_
# rule validates the zone is a CURRENT face when the vote OPENS, but a master-plan
# morph can COMPLETE before the vote lands. _on_rule_activated re-validates and, if
# the zone vanished, no-ops (the vote still "passed") — no permanent orphan rule.

def test_toctou_zone_destroyed_before_vote_lands_leaves_no_orphan_rule():
    w = _gov_world()
    agents = list(w.agents.values())
    zid = _zone_ids(w)[0]  # a real grid block at propose time
    ok, reason, rule = w.action_propose_rule(
        agents[0], "set_zone_rule", "zone it civic", target=zid, hint="civic",
        density_cap=3)
    assert ok, reason
    # Cast yes from 3 of 5 — BELOW the 0.7 supermajority (needs 4), so the vote is
    # still open (the rule has NOT activated yet).
    for a in agents[:3]:
        w.action_vote(a, rule.id, True)
    assert rule.status == "proposed"
    assert not w.city_graph.zone_rules
    # A master plan morphs the city to a pentagon and RUNS TO COMPLETION (clears
    # self.master_plan), destroying the grid block the pending rule targets. Because
    # the rule isn't in city_graph.zone_rules yet, _reconcile_zone_rules_after_morph
    # never sees it — exactly the orphan window.
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    for _ in range(1000):
        if w.master_plan is None:
            break
        w.step_master_plan_morph()
    assert w.master_plan is None, "morph never converged"
    assert zid not in set(_zone_ids(w)), "the target block should be gone post-morph"
    # The 4th yes crosses 0.7 and activates the rule onto a VANISHED zone.
    w.action_vote(agents[3], rule.id, True)
    assert rule.status == "active"   # the vote still passed
    assert rule.applied is True      # activation ran (one-shot)
    # ...but NO orphan rule was grafted onto the non-existent block.
    assert not any(r.zone_id == zid for r in w.city_graph.zone_rules)
    assert w.city_graph.zone_rules == []
    # invariant: every rule that DOES exist binds a real current face (no orphans).
    post = set(_zone_ids(w))
    assert all(r.zone_id in post for r in w.city_graph.zone_rules)


def test_toctou_surviving_zone_still_applies_normally():
    # Control: if the zone SURVIVES to activation, the rule applies as usual (the
    # re-validation is a no-op on the happy path).
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    zid = _zone_ids(w)[0]
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "x", target=zid, hint="market", density_cap=5)
    assert ok, reason
    _ratify(w, rule)  # no morph in between → zone still current
    assert rule.status == "active"
    matches = [r for r in w.city_graph.zone_rules if r.zone_id == zid]
    assert len(matches) == 1 and matches[0].hint == "market"


# ── FINDING #3 — reconcile priority inversion: KEEP must globally outrank ────────
# RE-POINT. A single mixed pass let an earlier rule's RE-POINT claim a face that a
# later rule still LITERALLY keeps, dropping the keeper. The two-pass fix claims all
# keepers first, then re-points the rest only onto faces no keeper owns.

def test_reconcile_keep_outranks_repoint_keeper_not_stolen():
    w = _gov_world()
    g = _square("F", 0, 0)
    fF = planar_faces(g)[0]
    zidF = zone_id_for(fF.boundary)  # a CURRENT face id
    # ORDER is load-bearing: the ghost rule is FIRST, so a single-pass reconcile
    # would let its RE-POINT steal F before the keeper (second) is examined.
    ghost = ZoneRule(zone_id="ghost|zone", hint="market", density_cap=1)
    keeper = ZoneRule(zone_id=zidF, hint="residential", density_cap=2)
    g.zone_rules = [ghost, keeper]
    w.city_graph = g
    # The ghost's ORIGINAL face centroid coincides EXACTLY with F (a re-point magnet);
    # the keeper's original centroid is F too (it still literally owns F).
    pre = {"ghost|zone": fF.centroid, zidF: fF.centroid}
    events = w._reconcile_zone_rules_after_morph(pre)
    # The KEEPER survived on F (its literal id), unchanged — NOT stolen by the ghost.
    survivors = w.city_graph.zone_rules
    assert [r.zone_id for r in survivors] == [zidF]
    assert survivors[0].hint == "residential" and survivors[0].density_cap == 2
    # The ghost dropped cleanly (no other face to re-point onto), and was logged.
    drop = next(e for e in events if e["kind"] == "zone_rule_dropped")
    assert drop["payload"]["zone_id"] == "ghost|zone"


def test_reconcile_ghost_repoints_elsewhere_without_stealing_keeper():
    # Variant: a SECOND surviving face exists, so the ghost re-points THERE instead
    # of stealing the keeper's face. Keeper survives on its own face either way.
    w = _gov_world()
    gF = _square("F", 0, 0)
    gG = _square("G", 100, 100)  # a second, far-away surviving face
    fF = planar_faces(gF)[0]
    fG = planar_faces(gG)[0]
    zidF = zone_id_for(fF.boundary)
    zidG = zone_id_for(fG.boundary)
    combined = CityGraph(seed=1, nodes=gF.nodes + gG.nodes, edges=gF.edges + gG.edges)
    ghost = ZoneRule(zone_id="ghost|zone", hint="market", density_cap=1)
    keeper = ZoneRule(zone_id=zidF, hint="residential", density_cap=2)
    combined.zone_rules = [ghost, keeper]
    w.city_graph = combined
    # ghost's original centroid sits on face G (so it should re-point to G, not steal F)
    pre = {"ghost|zone": fG.centroid, zidF: fF.centroid}
    events = w._reconcile_zone_rules_after_morph(pre)
    by_zone = {r.zone_id: r for r in w.city_graph.zone_rules}
    # keeper kept F; ghost re-pointed onto G — neither dropped, no mis-attach.
    assert zidF in by_zone and by_zone[zidF].hint == "residential"
    assert zidG in by_zone and by_zone[zidG].hint == "market"
    assert not any(e["kind"] == "zone_rule_dropped" for e in events)


# ── FINDING #4 — bootstrap: the FIRST rule is proposable from perception alone ───
# build_nearby_layout must surface the canonical zone_id (the "|"-joined node id) the
# action gate + action_propose_rule demand — not just the colliding display name —
# so with the flag ON and ZERO rules an agent can propose the very first rule.

def test_bootstrap_zone_id_parsed_from_perception_is_proposable_end_to_end(monkeypatch):
    import re
    from petridish.agents.runtime import build_nearby_layout, _validate_world
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    assert not w.city_graph.zone_rules           # ZERO rules ratified (bootstrap state)
    agent = next(iter(w.agents.values()))
    line = build_nearby_layout(w, _corner_place())
    assert line is not None and "nearby zones:" in line.lower()
    # The perception EXPOSES the canonical zone_id handle the gate requires.
    m = re.search(r"\[zone ([^\]]+)\]", line)
    assert m, f"perception has no [zone <id>] handle: {line}"
    zid = m.group(1)
    assert zid in set(_zone_ids(w)), "the parsed handle must be a real current zone"
    # 1) the parsed handle passes the RUNTIME action gate (skill-gated; grant it).
    gate = w.skill_gate_for("propose_rule")
    if gate is not None:
        agent.skills[gate[0]] = gate[1]
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_zone_rule", "text": "zone it civic",
                  "zone_id": zid, "hint": "civic", "density_cap": 2}},
        agent, w)
    assert not err, f"gate rejected the perceived zone_id: {err}"
    # 2) and world.action_propose_rule accepts it — the FIRST rule is proposable from
    #    perception alone (the GRAPH_ZONES_ENABLED bootstrap promise is now real).
    ok, reason, rule = w.action_propose_rule(
        agent, "set_zone_rule", "zone it civic", zone_id=zid, hint="civic",
        density_cap=2)
    assert ok, reason
    assert rule.effect == "set_zone_rule"
    assert rule.payload["zone_id"] == zid


def test_bootstrap_perception_shows_zone_id_for_every_listed_zone(monkeypatch):
    # Each nearby-zone clause carries its raw zone_id handle (names collide across the
    # seeded pool, so the id — not the name — is the agent's only unambiguous target).
    import re
    from petridish.agents.runtime import build_nearby_layout
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", True)
    w = _gov_world()
    line = build_nearby_layout(w, _corner_place())
    assert line is not None and "nearby zones:" in line.lower()
    handles = re.findall(r"\[zone ([^\]]+)\]", line)
    # one handle per listed zone (each clause has a " lots" count)
    assert len(handles) == line.lower().count(" lots")
    current = set(_zone_ids(w))
    for zid in handles:
        assert zid in current  # every surfaced handle is a real current zone

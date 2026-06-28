"""EM-245 (S3b) — master-plan city morph: the per-tick morph engine, the
vote-gated adopt_master_plan rule effect (mirrors EM-244 demolish_road), and
determinism/replay/snapshot-resume acceptance.

The World ctor mirrors run.py / test_layout_governance.py: World(params=, places=,
agents=) built from the embedded default config; for governance tests all agents
are moved to a governance place so action_propose_rule's gate passes. Ratification
is SYNCHRONOUS (the threshold-crossing action_vote calls _on_rule_activated), so
the adopt tests never call _on_rule_activated by hand.
"""
from __future__ import annotations

import pytest

from petridish.config.loader import load_config
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.citygraph import master_plan, diff_graphs


def _world() -> World:
    cfg = load_config()
    places = [PlaceState(id=p.id, name=p.name, x=p.x, y=p.y, kind=p.kind, description=p.description,
                         district=p.district, neighborhood_id=p.neighborhood_id, zone_kind=p.zone_kind)
              for p in cfg.places]
    agents = [AgentState(id=f"agent_{a.name.lower()}", name=a.name, personality=a.personality,
                         profile=a.profile, location=a.location, energy=cfg.world.starting_energy,
                         credits=cfg.world.starting_credits) for a in cfg.agents]
    return World(params=cfg.world, places=places, agents=agents)


# ── Task 2: the per-tick morph engine ─────────────────────────────────────────

def test_morph_converges_to_target_over_ticks():
    w = _world()
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    events = []
    for _ in range(200):                       # bounded; converges well before
        evts = w.step_master_plan_morph()
        events += evts
        if w.master_plan is None:
            break
    assert w.master_plan is None              # converged + cleared
    target = master_plan("pentagon", {}, w.city_seed)
    d = diff_graphs(w.city_graph, target)
    assert d["add_edges"] == [] and d["remove_edge_ids"] == []   # graph == target
    assert any(e["kind"] == "master_plan_complete" for e in events)
    assert any(e["kind"] == "road_built" for e in events)


def test_morph_step_is_bounded_per_tick():
    w = _world()
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    from petridish.engine.world import MORPH_EDGES_PER_TICK
    evts = w.step_master_plan_morph()
    edge_ops = [e for e in evts if e["kind"] in ("road_built", "road_demolished")]
    assert 0 < len(edge_ops) <= MORPH_EDGES_PER_TICK


def test_no_active_plan_is_noop():
    w = _world()
    assert w.master_plan is None
    assert w.step_master_plan_morph() == []


def test_morph_is_deterministic_and_snapshot_safe():
    def run():
        w = _world()
        w.master_plan = {"kind": "radial", "params": {}, "seed": w.city_seed}
        for _ in range(8):
            w.step_master_plan_morph()
        return w
    a, b = run(), run()
    assert a.city_graph.to_dict() == b.city_graph.to_dict()
    assert a.master_plan == b.master_plan
    # mid-morph state survives a snapshot round-trip
    w2 = World.from_snapshot(a.to_snapshot())
    assert w2.master_plan == a.master_plan
    assert w2.city_graph.to_dict() == a.city_graph.to_dict()


# ── Task 3: adopt_master_plan vote-gated effect (mirrors EM-244 demolish_road) ──

def test_propose_and_ratify_adopt_master_plan_starts_morph():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "adopt_master_plan", "go pentagon", target="pentagon")
    assert ok, reason
    for a in w.agents.values():
        w.action_vote(a, rule.id, True)
    assert rule.status == "active"
    assert w.master_plan is not None and w.master_plan["kind"] == "pentagon"


def test_one_active_plan_at_a_time():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    ok, reason, _ = w.action_propose_rule(agent, "adopt_master_plan", "switch", target="radial")
    assert not ok and "already" in reason.lower()


def test_adopt_master_plan_rejects_unknown_kind():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    ok, reason, _ = w.action_propose_rule(next(iter(w.agents.values())),
                                          "adopt_master_plan", "x", target="hexagon")
    assert not ok and "kind" in reason.lower()


def test_adopt_master_plan_needs_supermajority_not_simple_majority():
    # 0.7 of 5 living agents = ceil(3.5) = 4 yes votes. A simple majority (3) must
    # NOT ratify an adopt_master_plan (it's structural/irreversible).
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agents = list(w.agents.values())
    ok, reason, rule = w.action_propose_rule(agents[0], "adopt_master_plan", "go pentagon",
                                             target="pentagon")
    assert ok, reason
    for a in agents[:3]:  # only 3 yes votes
        w.action_vote(a, rule.id, True)
    assert rule.status == "proposed"
    assert w.master_plan is None             # not started yet
    w.action_vote(agents[3], rule.id, True)  # the 4th yes crosses 0.7
    assert rule.status == "active"
    assert w.master_plan is not None and w.master_plan["kind"] == "pentagon"


def test_adopt_master_plan_in_runtime_valid_effects_gate():
    # The runtime front-gate must accept the new effect (it is the agent's ONLY
    # path; an effect missing here is silently un-proposable).
    from petridish.agents.runtime import _validate_world
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "adopt_master_plan", "text": "x", "target": "pentagon"}},
        agent, w)
    assert not err or "invalid effect" not in err


def test_adopt_master_plan_threads_kind_through_dispatch():
    from petridish.agents.runtime import AgentRuntime
    from petridish.config.loader import ModelProfile
    from petridish.providers.router import Router
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    rt = AgentRuntime(w, Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                              color="#2ecc71")], cache_enabled=False))
    agent = next(iter(w.agents.values()))
    evt = rt._apply_action_inner(
        agent,
        {"action": "propose_rule",
         "args": {"effect": "adopt_master_plan", "text": "go pentagon", "target": "pentagon"}},
        "P", "#fff")
    assert evt["kind"] == "rule_proposed", evt
    rule = w.rules[evt["payload"]["rule_id"]]
    assert rule.effect == "adopt_master_plan"
    assert rule.payload.get("kind") == "pentagon"


def test_ratified_adopt_master_plan_survives_snapshot_round_trip():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "adopt_master_plan", "go ring", target="ring")
    assert ok, reason
    for a in w.agents.values():
        w.action_vote(a, rule.id, True)
    assert w.master_plan is not None
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.master_plan == w.master_plan


# ── Task 5: determinism / replay / snapshot-resume acceptance ──────────────────

def test_full_morph_replay_is_byte_identical():
    def run(snapshot_at=None):
        w = _world()
        w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
        for t in range(200):
            if snapshot_at is not None and t == snapshot_at:
                w = World.from_snapshot(w.to_snapshot())     # restore mid-morph
            w.step_master_plan_morph()
            assert len(w.city_graph.edges) >= 1              # never edgeless
            if w.master_plan is None:
                break
        return w.city_graph.to_dict()
    assert run() == run(snapshot_at=5)                       # snapshot mid-morph ⇒ identical result


def test_full_propose_to_morph_completion_is_deterministic():
    # A full propose→ratify→morph-to-completion sequence is deterministic across
    # two worlds (identical city_graph.to_dict() at every tick of the morph).
    def run():
        w = _world()
        gov = next(p for p in w.places.values() if p.kind == "governance")
        for a in w.agents.values():
            a.location = gov.id
        agent = next(iter(w.agents.values()))
        ok, _reason, rule = w.action_propose_rule(agent, "adopt_master_plan", "go radial",
                                                  target="radial")
        assert ok
        for a in w.agents.values():
            w.action_vote(a, rule.id, True)
        snaps = []
        for _ in range(200):
            w.step_master_plan_morph()
            snaps.append(w.city_graph.to_dict())
            if w.master_plan is None:
                break
        return snaps
    a, b = run(), run()
    assert a == b


def test_morph_never_leaves_graph_edgeless():
    w = _world()
    w.master_plan = {"kind": "ring", "params": {}, "seed": w.city_seed}
    for _ in range(200):
        w.step_master_plan_morph()
        assert len(w.city_graph.edges) >= 1
        if w.master_plan is None:
            break
    assert w.master_plan is None


def test_building_relocation_is_deferred_buildings_keep_location():
    # EM-245 records that building relocation rides the FRONTEND assignBuildingLots
    # re-derivation (per EM-244); the backend does NOT move buildings as the graph
    # morphs. A building's `location` (its place id) is untouched by the morph.
    from petridish.engine.world import Building
    w = _world()
    place = next(iter(w.places.values()))
    b = Building(id="bld_keep", name="Old Hall", kind="library", location=place.id,
                 owner_id="public", status="operational")
    w.buildings[b.id] = b
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    for _ in range(200):
        w.step_master_plan_morph()
        if w.master_plan is None:
            break
    assert w.buildings["bld_keep"].location == place.id   # backend never relocated it


def test_corrupt_master_plan_snapshot_degrades_to_none():
    # EM-245 review fix (MEDIUM): a SHAPE-corrupt master_plan in a snapshot must
    # degrade to None — not survive and wedge/misfire the morph engine.
    w = _world()
    base = w.to_snapshot()
    for bad in ({"kind": "pentagon"}, {"seed": 5}, {"kind": "hexagon", "seed": 1},
                "x", 123, [], {}):
        snap = dict(base)
        snap["master_plan"] = bad
        w2 = World.from_snapshot(snap)
        assert w2.master_plan is None, f"corrupt {bad!r} should degrade to None"
        assert w2.step_master_plan_morph() == []  # no wedge, no spurious morph

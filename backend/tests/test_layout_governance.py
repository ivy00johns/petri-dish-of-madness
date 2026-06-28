"""EM-244 (S3a) — vote-gated demolish_road + set_car_policy governance effects.

Both are new rule effects on the unified action_propose_rule machinery (same path
as EM-183 relocate_center / EM-219 demolish): propose at a governance place ->
action_vote -> _evaluate_rule ratifies at 0.7 -> _on_rule_activated applies the
pure CityGraph mutation. Ratification is SYNCHRONOUS: the threshold-crossing
action_vote calls _on_rule_activated itself (see world.action_vote), so these
tests never call _on_rule_activated by hand.

The World ctor mirrors run.py / test_build_road.py: World(params=, places=,
agents=) built from the embedded default config; all agents are moved to a
governance place so action_propose_rule's governance_here gate passes.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import load_config, ModelProfile
from petridish.providers.router import Router


def _gov_world() -> World:
    """A world with agents at the governance place so propose_rule is allowed.
    Built from the default embedded config (5 agents, real places incl. a
    governance town hall), mirroring run.py's World(params=, places=, agents=)."""
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
    # cast yes votes from every living agent; the threshold-crossing vote
    # activates the rule (and applies its effect) synchronously.
    for a in w.agents.values():
        w.action_vote(a, rule.id, True)
    return rule


# ── Task 2: propose -> vote -> ratify -> apply ────────────────────────────────

def test_propose_and_ratify_demolish_road_removes_edge():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    assert any(e.id == edge_id for e in w.city_graph.edges)
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road",
                                             "tear down 7th & 12th", target=edge_id)
    assert ok, reason
    _ratify(w, rule)
    assert rule.effect == "demolish_road"
    assert rule.status == "active"
    assert not any(e.id == edge_id for e in w.city_graph.edges)


def test_propose_and_ratify_car_policy_city_bans_cars():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy",
                                             "ban cars citywide",
                                             scope="city", policy="pedestrian")
    assert ok, reason
    _ratify(w, rule)
    assert rule.status == "active"
    assert w.city_graph.car_policy == "pedestrian"


def test_propose_and_ratify_car_policy_street_sets_one_edge():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy",
                                             "pedestrianize 7th & 12th",
                                             scope="street", policy="pedestrian",
                                             target=edge_id)
    assert ok, reason
    _ratify(w, rule)
    assert rule.status == "active"
    edge = next(e for e in w.city_graph.edges if e.id == edge_id)
    assert edge.car_policy == "pedestrian"
    assert w.city_graph.car_policy == "cars"  # city default untouched


def test_demolish_road_requires_real_edge():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "x",
                                             target="e:nope->nope")
    assert not ok and "road" in reason.lower()


def test_car_policy_rejects_bad_policy_scope_and_target():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    # bad policy
    ok, reason, _ = w.action_propose_rule(agent, "set_car_policy", "x",
                                          scope="city", policy="flying")
    assert not ok and "policy" in reason.lower()
    # deferred district scope
    ok, reason, _ = w.action_propose_rule(agent, "set_car_policy", "x",
                                          scope="district", policy="pedestrian")
    assert not ok and "scope" in reason.lower()
    # street scope with unknown edge
    ok, reason, _ = w.action_propose_rule(agent, "set_car_policy", "x",
                                          scope="street", policy="pedestrian",
                                          target="e:nope")
    assert not ok and "road" in reason.lower()


def test_demolish_road_requires_governance_place():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    # move the proposer to a non-governance place -> gate rejects
    non_gov = next(p for p in w.places.values() if p.kind != "governance")
    agent.location = non_gov.id
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "x",
                                             target="e:n:7:2->n:12:2")
    assert not ok and rule is None


def test_demolish_road_emits_system_event():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "tear it down",
                                             target=edge_id)
    assert ok, reason
    _ratify(w, rule)
    kinds = [e.get("kind") for e in w.pending_spawn_events]
    assert "road_demolished" in kinds


def test_set_car_policy_emits_system_event():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy", "ped",
                                             scope="city", policy="pedestrian")
    assert ok, reason
    _ratify(w, rule)
    kinds = [e.get("kind") for e in w.pending_spawn_events]
    assert "car_policy_set" in kinds


def test_layout_effects_need_supermajority_not_simple_majority():
    # 0.7 of 5 living agents = ceil(3.5) = 4 yes votes. A simple majority (3) must
    # NOT ratify a demolish_road (it's structural/irreversible).
    w = _gov_world()
    agents = list(w.agents.values())
    edge_id = "e:n:7:2->n:12:2"
    ok, reason, rule = w.action_propose_rule(agents[0], "demolish_road", "x",
                                             target=edge_id)
    assert ok, reason
    for a in agents[:3]:  # only 3 yes votes
        w.action_vote(a, rule.id, True)
    assert rule.status == "proposed"
    assert any(e.id == edge_id for e in w.city_graph.edges)  # not torn down yet
    w.action_vote(agents[3], rule.id, True)  # the 4th yes crosses 0.7
    assert rule.status == "active"
    assert not any(e.id == edge_id for e in w.city_graph.edges)


# ── Task 3: action surface (schema + front-gate) + perception ─────────────────

def test_layout_effects_in_runtime_valid_effects_gate():
    # The runtime front-gate must accept the new effects (it is the agent's ONLY
    # path; an effect missing here is silently un-proposable).
    from petridish.agents.runtime import _validate_world
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    # demolish_road reaches the world (no "invalid effect" string)
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "demolish_road", "text": "x", "target": edge_id}},
        agent, w)
    assert not err or "invalid effect" not in err
    # set_car_policy reaches the world too
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "set_car_policy", "text": "x",
                  "scope": "city", "policy": "pedestrian"}},
        agent, w)
    assert not err or "invalid effect" not in err


def test_propose_rule_threads_scope_policy_through_dispatch():
    # Driving the FULL runtime path (_apply_action_inner) must thread scope/policy
    # from args -> world.action_propose_rule and open the vote.
    from petridish.agents.runtime import AgentRuntime
    w = _gov_world()
    rt = AgentRuntime(w, _router())
    agent = next(iter(w.agents.values()))
    evt = rt._apply_action_inner(
        agent,
        {"action": "propose_rule",
         "args": {"effect": "set_car_policy", "text": "ban cars",
                  "scope": "city", "policy": "pedestrian"}},
        "P", "#fff")
    assert evt["kind"] == "rule_proposed", evt
    rule = w.rules[evt["payload"]["rule_id"]]
    assert rule.effect == "set_car_policy"
    assert rule.payload.get("scope") == "city"
    assert rule.payload.get("policy") == "pedestrian"


def test_propose_rule_threads_demolish_road_target_through_dispatch():
    from petridish.agents.runtime import AgentRuntime
    w = _gov_world()
    rt = AgentRuntime(w, _router())
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    evt = rt._apply_action_inner(
        agent,
        {"action": "propose_rule",
         "args": {"effect": "demolish_road", "text": "tear it down",
                  "target": edge_id}},
        "P", "#fff")
    assert evt["kind"] == "rule_proposed", evt
    rule = w.rules[evt["payload"]["rule_id"]]
    assert rule.effect == "demolish_road"
    assert rule.payload.get("target") == edge_id


def test_nearby_layout_reports_car_policy():
    from petridish.agents.runtime import build_nearby_layout
    w = _gov_world()
    place = next(iter(w.places.values()))
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "cars" in line.lower()


def test_nearby_layout_surfaces_open_layout_vote():
    from petridish.agents.runtime import build_nearby_layout
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    # open a layout vote, then perceive near a node with an open direction
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy", "ban cars",
                                             scope="city", policy="pedestrian")
    assert ok, reason
    # a corner place whose nearest node has an open (extendable) direction
    place = PlaceState(id="far", name="Far Corner", x=500, y=500, kind="social")
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "open vote" in line.lower()
    assert "set_car_policy" in line.lower()


# ── Task 5: determinism / replay / snapshot acceptance ────────────────────────

def test_car_policy_survives_snapshot_round_trip():
    from petridish.engine.citygraph import apply_car_policy
    w = _gov_world()
    apply_car_policy(w.city_graph, "city", "pedestrian")
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.car_policy == "pedestrian"


def test_ratified_demolish_road_survives_snapshot_round_trip():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "x",
                                             target=edge_id)
    assert ok, reason
    _ratify(w, rule)
    snap = w.to_snapshot()
    w2 = World.from_snapshot(snap)
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()  # byte-identical
    assert not any(e.id == edge_id for e in w2.city_graph.edges)


def test_ratified_car_policy_survives_snapshot_round_trip():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy", "ped",
                                             scope="city", policy="pedestrian")
    assert ok, reason
    _ratify(w, rule)
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.car_policy == "pedestrian"


def test_replaying_same_proposals_yields_identical_graph():
    # EM-155: the graph is a pure function of (seed, ordered ratified effects).
    def _run() -> World:
        w = _gov_world()
        agent = next(iter(w.agents.values()))
        ok, _, r1 = w.action_propose_rule(agent, "demolish_road", "x",
                                          target="e:n:7:2->n:12:2")
        assert ok
        _ratify(w, r1)
        ok, _, r2 = w.action_propose_rule(agent, "set_car_policy", "ped",
                                          scope="city", policy="pedestrian")
        assert ok
        _ratify(w, r2)
        return w

    a, b = _run(), _run()
    assert a.city_graph.to_dict() == b.city_graph.to_dict()

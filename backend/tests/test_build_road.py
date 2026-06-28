"""EM-243 (S2) — the agent `build_road` verb: world-method, schema/dispatch,
nearby_layout perception, and determinism/replay acceptance.

House import idiom: engine.world BEFORE agents.runtime so the world module binds
first. The `_world()` helper builds a minimal-but-REAL World (the plan's
`World(cfg)` shorthand doesn't match the actual `World(params=, places=, agents=)`
constructor — see run.py:65 / app.py:124). The single place sits far in +x/+z so
its nearest graph node is the n:12:12 corner, which has BOTH open (east/north) and
road (west/south) directions — exactly the mix these tests exercise.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import load_config, ModelProfile
from petridish.providers.router import Router


def _world() -> World:
    # Minimal world from the default config params; a corner-mapping place + one agent.
    cfg = load_config()  # default embedded config
    places = [PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social")]
    agents = [AgentState(id="agent_test", name="Tester", personality="",
                         profile="mock", location="plaza", energy=100.0, credits=10)]
    return World(params=cfg.world, places=places, agents=agents)


def _router() -> Router:
    return Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                color="#2ecc71")], cache_enabled=False)


def _agent_at(w: World, place_id: str):
    a = next(iter(w.agents.values()))
    a.location = place_id
    a.energy = 100.0
    return a


def test_action_build_road_success_emits_event_and_costs_energy():
    w = _world()
    place_id = next(iter(w.places))            # any real place
    a = _agent_at(w, place_id)
    e0 = len(w.city_graph.edges)
    before = a.energy
    # find an open direction from the agent's nearest node so the build is valid
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "open")
    evt = w.action_build_road(a, {"direction": direction})
    assert evt["kind"] == "road_built"
    assert evt["payload"]["direction"] == direction
    assert len(w.city_graph.edges) == e0 + 1
    assert a.energy == pytest.approx(before - w.params.road_build_energy_cost)


def test_action_build_road_too_tired_refuses_no_graph_change():
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    a.energy = 1.0
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": "east"})
    assert evt["kind"] == "parse_failure"
    assert "tired" in evt["text"].lower()
    assert len(w.city_graph.edges) == e0   # no mutation when refused


def test_action_build_road_blocked_direction_reports_reason():
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    blocked = next((d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "road"), None)
    if blocked is None:
        pytest.skip("no blocked direction at this node")
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": blocked})
    assert evt["kind"] == "parse_failure"
    assert len(w.city_graph.edges) == e0


# ── Task 3: action schema + dispatch ──────────────────────────────────────────

def test_build_road_in_action_schema_enum():
    from petridish.agents.runtime import ACTION_SCHEMA
    # both the single-action and multi-action enums must allow it
    single = ACTION_SCHEMA["properties"]["action"]["enum"]
    assert "build_road" in single
    multi = ACTION_SCHEMA["properties"]["actions"]["items"]["properties"]["action"]["enum"]
    assert "build_road" in multi


def test_dispatch_routes_build_road(monkeypatch):
    # _apply_action_inner must route "build_road" -> world.action_build_road
    from petridish.agents.runtime import AgentRuntime  # the class holding _apply_action_inner
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    rt = AgentRuntime(w, _router())  # real ctor is AgentRuntime(world, router)
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "open")
    evt = rt._apply_action_inner(a, {"action": "build_road", "args": {"direction": direction}}, "P", "#fff")
    assert evt["kind"] == "road_built"


# ── Task 4: nearby_layout perception helper ───────────────────────────────────

def test_nearby_layout_lists_extendable_directions():
    from petridish.agents.runtime import build_nearby_layout  # pure helper (Step 3)
    w = _world()
    place = w.places[next(iter(w.places))]
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "build" in line.lower() or "extend" in line.lower()
    # reports at least one cardinal status and the car policy
    assert any(d in line.lower() for d in ("north", "south", "east", "west"))
    assert "cars" in line.lower()


def test_nearby_layout_omitted_when_nothing_extendable():
    # A fully-enclosed node (all 4 dirs are road/edge) -> None (diet: omit empties)
    from petridish.agents.runtime import build_nearby_layout
    w = _world()
    # n:2:2 is interior — all four neighbors are existing roads
    place = w.places[next(iter(w.places))]
    # force the nearest node to the interior by placing the perception at center coords
    line = build_nearby_layout(w, place, force_node_id="n:2:2")
    assert line is None


# ── Task 6: determinism / replay / snapshot acceptance ────────────────────────

def test_grown_graph_survives_snapshot_round_trip():
    from petridish.engine.citygraph import apply_build_road
    w = _world()
    apply_build_road(w.city_graph, "n:12:2", "east")     # n:17:2
    apply_build_road(w.city_graph, "n:17:2", "east")     # n:22:2
    snap = w.to_snapshot()
    w2 = World.from_snapshot(snap)
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()  # byte-identical grown graph


def test_replaying_same_builds_yields_identical_graph():
    # EM-155: the grown graph is a pure function of (seed, ordered road_built actions)
    from petridish.engine.citygraph import apply_build_road
    a, b = _world(), _world()
    builds = [("n:12:2", "east"), ("n:17:2", "east"), ("n:2:12", "north")]
    for nid, d in builds:
        apply_build_road(a.city_graph, nid, d)
        apply_build_road(b.city_graph, nid, d)
    assert a.city_graph.to_dict() == b.city_graph.to_dict()


def test_new_road_extends_node_and_edge_counts_monotonically():
    from petridish.engine.citygraph import apply_build_road
    w = _world()
    n0, e0 = len(w.city_graph.nodes), len(w.city_graph.edges)
    ok, _, _ = apply_build_road(w.city_graph, "n:12:2", "east")
    assert ok
    assert len(w.city_graph.nodes) == n0 + 1
    assert len(w.city_graph.edges) == e0 + 1

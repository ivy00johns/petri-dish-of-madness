"""EM-243 (S2) — the agent `build_road` verb: world-method, schema/dispatch,
nearby_layout perception, and determinism/replay acceptance.

Coordinate frame (fix-wave A1): a place's (x, y) are LOGICAL 0..1000 coords, and
the CityGraph lives in the ±32.5 world frame (tile-center units). The engine now
maps logical→world via `citygraph.logical_to_world` (mirrors web/worldSpace.ts)
BEFORE `nearest_node`, so a place anchors to the graph node under it — not the
n:12:12 NE corner every place used to snap to when raw 0..1000 coords were fed
straight into the world-frame graph. So the central plaza at (500,500) now grows
roads from the TOWN CENTER, and agents standing at different places get different
anchors. The `_world()` helper takes the place's logical coords so each test can
stand its agent where the frame under test demands.

House import idiom: engine.world BEFORE agents.runtime so the world module binds
first.
"""
from __future__ import annotations

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import load_config, ModelProfile
from petridish.providers.router import Router


def _world(px: float = 500, py: float = 500) -> World:
    # Minimal world from the default config params; one place at the given LOGICAL
    # (0..1000) coords + one agent standing on it.
    cfg = load_config()  # default embedded config
    places = [PlaceState(id="plaza", name="Central Plaza", x=px, y=py, kind="social")]
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


def _anchor(w: World, place):
    """The graph node the ENGINE anchors this place to — the logical→world mapping
    then nearest_node (the same path action_build_road / build_nearby_layout use)."""
    from petridish.engine.citygraph import logical_to_world, nearest_node
    wx, wz = logical_to_world(float(place.x), float(place.y))
    return nearest_node(w.city_graph, wx, wz)


# ── A1: the logical→world frame (shared contract with web/worldSpace.ts) ────────

def test_logical_to_world_pinned_conversions():
    from petridish.engine.citygraph import logical_to_world, WORLD_SIZE
    assert WORLD_SIZE == 66.0  # MUST equal web worldSpace.ts SIZE
    # center maps to the world origin (exact)
    assert logical_to_world(500, 500) == (0.0, 0.0)
    # an off-center pin (matches web toWorldX/toWorldZ exactly)
    x, z = logical_to_world(106, 894)
    assert x == pytest.approx(-26.004) and z == pytest.approx(26.004)
    # the SW-ish extreme (exact)
    assert logical_to_world(0, 1000) == (-33.0, 33.0)


def test_plaza_anchors_interior_node_not_corner():
    # (500,500) → world origin → a fully-INTERIOR node (all four dirs are already
    # road), NOT the n:12:12 corner the pre-fix bug snapped every place to.
    from petridish.engine.citygraph import extendable_directions
    w = _world(500, 500)
    node = _anchor(w, w.places["plaza"])
    assert node.id != "n:12:12"
    dirs = extendable_directions(w.city_graph, node.id)
    assert dirs and all(s == "road" for s in dirs.values())


def test_places_in_different_quadrants_get_different_anchors():
    # Two places in opposite town quadrants must anchor to DIFFERENT graph nodes
    # (the bug collapsed every place onto the same corner node).
    cfg = load_config()
    places = [
        PlaceState(id="sw", name="Southwest", x=100, y=100, kind="social"),
        PlaceState(id="ne", name="Northeast", x=900, y=900, kind="work"),
    ]
    agents = [AgentState(id="a", name="A", personality="", profile="mock",
                         location="sw", energy=100.0, credits=10)]
    w = World(params=cfg.world, places=places, agents=agents)
    n_sw = _anchor(w, w.places["sw"])
    n_ne = _anchor(w, w.places["ne"])
    assert n_sw.id != n_ne.id


def test_build_road_uses_corrected_anchor_not_corner():
    # BEHAVIORAL regression proof: an agent at the central plaza (500,500) anchors
    # to the fully-interior town center, so a build there is correctly REFUSED
    # ("already a road" in every direction). The pre-fix corner bug would have
    # 'succeeded' by extending the map edge from n:12:12.
    w = _world(500, 500)
    a = _agent_at(w, "plaza")
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": "east"})
    assert evt["kind"] == "parse_failure"
    assert "already a road" in evt["text"].lower()
    assert len(w.city_graph.edges) == e0  # no mutation


# ── world-method success / refusal (corrected frame) ──────────────────────────

def test_action_build_road_success_emits_event_and_costs_energy():
    # A place at the NE extreme (1000,1000) → world (33,33) → the n:12:12 corner,
    # which genuinely HAS open (extendable) directions in the corrected frame.
    from petridish.engine.citygraph import extendable_directions
    w = _world(1000, 1000)
    a = _agent_at(w, "plaza")
    e0 = len(w.city_graph.edges)
    before = a.energy
    node = _anchor(w, w.places["plaza"])
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items()
                     if s == "open")
    evt = w.action_build_road(a, {"direction": direction})
    assert evt["kind"] == "road_built"
    assert evt["payload"]["direction"] == direction
    # the road grows from the CORRECTED anchor, not a hard-coded corner
    assert evt["payload"]["from_node"] == node.id
    assert len(w.city_graph.edges) == e0 + 1
    assert a.energy == pytest.approx(before - w.params.road_build_energy_cost)


def test_action_build_road_too_tired_refuses_no_graph_change():
    w = _world(1000, 1000)
    a = _agent_at(w, "plaza")
    a.energy = 1.0
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": "east"})
    assert evt["kind"] == "parse_failure"
    assert "tired" in evt["text"].lower()
    assert len(w.city_graph.edges) == e0   # no mutation when refused


def test_action_build_road_blocked_direction_reports_reason():
    from petridish.engine.citygraph import extendable_directions
    w = _world(1000, 1000)
    a = _agent_at(w, "plaza")
    node = _anchor(w, w.places["plaza"])
    blocked = next((d for d, s in extendable_directions(w.city_graph, node.id).items()
                    if s == "road"), None)
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
    from petridish.engine.citygraph import extendable_directions
    w = _world(1000, 1000)
    a = _agent_at(w, "plaza")
    rt = AgentRuntime(w, _router())  # real ctor is AgentRuntime(world, router)
    node = _anchor(w, w.places["plaza"])
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items()
                     if s == "open")
    evt = rt._apply_action_inner(a, {"action": "build_road", "args": {"direction": direction}}, "P", "#fff")
    assert evt["kind"] == "road_built"


# ── Task 4: nearby_layout perception helper ───────────────────────────────────

def test_nearby_layout_lists_extendable_directions():
    from petridish.agents.runtime import build_nearby_layout  # pure helper (Step 3)
    w = _world(1000, 1000)  # a corner place with genuinely open directions
    place = w.places["plaza"]
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "build" in line.lower() or "extend" in line.lower()
    # reports at least one cardinal status and the car policy
    assert any(d in line.lower() for d in ("north", "south", "east", "west"))
    assert "cars" in line.lower()


def test_nearby_layout_omitted_when_nothing_extendable(monkeypatch):
    # A fully-enclosed node (all 4 dirs are road/edge), the zones flag OFF → None
    # (diet: omit empties). Zones now ship ON by default (feat/organic-world-regen),
    # which would add a nearby_zones block, so pin the flag off to test the road-only
    # omission.
    monkeypatch.setattr("petridish.agents.runtime.GRAPH_ZONES_ENABLED", False)
    from petridish.agents.runtime import build_nearby_layout
    w = _world()
    place = w.places["plaza"]
    # force the nearest node to the interior — all four neighbors are existing roads
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

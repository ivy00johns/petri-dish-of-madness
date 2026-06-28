from petridish.engine.citygraph import (
    CityGraph, classic_grid, ROAD_TILE_INDICES, tile_center,
)


def test_classic_grid_node_and_edge_counts():
    g = classic_grid(1337)
    # 6 road lines per axis -> 6x6 = 36 intersections.
    assert len(g.nodes) == 36
    # 6 lines x 5 segments, per axis -> 60 edges.
    assert len(g.edges) == 60
    assert g.version == 1
    assert g.seed == 1337
    assert g.car_policy == "cars"


def test_classic_grid_nodes_sit_on_road_line_centers():
    g = classic_grid(1337)
    centers = {round(tile_center(i), 3) for i in ROAD_TILE_INDICES}
    for n in g.nodes:
        assert round(n.x, 3) in centers
        assert round(n.z, 3) in centers
        assert n.kind == "junction"


def test_classic_grid_is_deterministic():
    assert classic_grid(1337).to_dict() == classic_grid(1337).to_dict()


def test_classic_grid_edges_are_axis_aligned_unit_segments():
    g = classic_grid(1337)
    by_id = {n.id: n for n in g.nodes}
    for e in g.edges:
        a, b = by_id[e.a], by_id[e.b]
        # exactly one axis differs, by one block pitch (13.0).
        dx, dz = abs(a.x - b.x), abs(a.z - b.z)
        assert (dx == 0.0) ^ (dz == 0.0)
        assert round(dx + dz, 3) == 13.0


def test_to_dict_from_dict_round_trip():
    g = classic_grid(1337)
    assert CityGraph.from_dict(g.to_dict()).to_dict() == g.to_dict()


def _min_world():
    # Build the smallest real World: one place, no agents.
    from petridish.config.loader import WorldParams
    from petridish.engine.world import World, PlaceState
    params = WorldParams()
    places = [PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social")]
    return World(params=params, places=places, agents=[])


def test_world_builds_classic_grid_at_init():
    w = _min_world()
    assert w.city_graph.to_dict() == classic_grid(w.city_seed).to_dict()


def test_to_snapshot_carries_city_graph():
    w = _min_world()
    snap = w.to_snapshot()
    assert snap["city_graph"] == classic_grid(w.city_seed).to_dict()


def test_from_snapshot_restores_graph_verbatim():
    from petridish.engine.world import World
    w = _min_world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(snap)
    assert restored.city_graph.to_dict() == snap["city_graph"]


def test_from_snapshot_derives_graph_when_absent():
    # Migration / old snapshot: no city_graph key -> derive classic_grid(seed).
    from petridish.engine.world import World
    w = _min_world()
    snap = w.to_snapshot()
    seed = snap["city_seed"]
    del snap["city_graph"]
    restored = World.from_snapshot(snap)
    assert restored.city_graph.to_dict() == classic_grid(seed).to_dict()


def test_snapshot_round_trip_is_graph_stable():
    # to_snapshot -> from_snapshot -> to_snapshot keeps city_graph identical
    # (replay/fork parity: the graph survives restore byte-for-byte).
    from petridish.engine.world import World
    w = _min_world()
    snap1 = w.to_snapshot()
    snap2 = World.from_snapshot(snap1).to_snapshot()
    assert snap2["city_graph"] == snap1["city_graph"]


def test_from_snapshot_degrades_on_corrupt_graph():
    # ModelBoundary (EM-239): a type-corrupt / partially-written city_graph must
    # degrade to classic_grid(restored_seed) — from_snapshot must NEVER crash on
    # a corrupted or partially-written snapshot (fork/restore resilience).
    from petridish.engine.world import World
    w = _min_world()
    base = w.to_snapshot()
    seed = base["city_seed"]
    expected = classic_grid(seed).to_dict()
    corrupt = [
        {"nodes": "xxx", "edges": []},            # nodes truthy but not a list
        {"nodes": [{"id": "n"}], "edges": []},    # node dict missing x/z
        {"nodes": 5, "edges": [{"a": "x", "b": "y"}]},  # nodes not a list
        {"edges": [{"a": "x", "b": "y"}]},        # no nodes key at all
        {},                                        # empty dict
        {"nodes": []},                             # empty node list
        "not-a-dict",                              # not even a dict
        None,                                      # explicit null
    ]
    for bad in corrupt:
        snap = dict(base)
        snap["city_graph"] = bad
        restored = World.from_snapshot(snap)  # must not raise
        assert restored.city_graph.to_dict() == expected, f"failed on {bad!r}"


# ── EM-243 (S2): pure, bounded, deterministic individual road growth ──────────
from petridish.engine.citygraph import (
    apply_build_road, nearest_node, extendable_directions,
    MAX_IDX, MIN_IDX,
)


def test_build_road_extends_one_segment_east():
    g = classic_grid(1337)
    n0, e0 = len(g.nodes), len(g.edges)
    ok, reason, info = apply_build_road(g, "n:12:2", "east")
    assert ok, reason
    assert info["new_node_id"] == "n:17:2"
    assert info["new_edge_id"] == "e:n:12:2->n:17:2"
    assert len(g.nodes) == n0 + 1 and len(g.edges) == e0 + 1
    assert any(n.id == "n:17:2" for n in g.nodes)


def test_build_road_edge_id_orders_low_index_first():
    # Extending WEST from the left edge: the new (lower-i) node sorts first in the id.
    g = classic_grid(1337)
    ok, reason, info = apply_build_road(g, "n:-13:2", "west")
    assert ok, reason
    assert info["new_node_id"] == "n:-18:2"
    assert info["new_edge_id"] == "e:n:-18:2->n:-13:2"


def test_build_road_rejects_out_of_bounds():
    g = classic_grid(1337)
    # n:22:2 is the max index; one more east is off the 9x9 envelope.
    apply_build_road(g, "n:12:2", "east")     # -> n:17:2
    apply_build_road(g, "n:17:2", "east")     # -> n:22:2 (still in bounds)
    ok, reason, info = apply_build_road(g, "n:22:2", "east")  # -> n:27:2 OUT
    assert not ok and info is None
    assert "edge of the city" in reason


def test_build_road_rejects_existing_road():
    g = classic_grid(1337)
    # n:7:2 -> n:12:2 is already an edge in the classic grid.
    ok, reason, info = apply_build_road(g, "n:7:2", "east")
    assert not ok and "already a road" in reason


def test_build_road_rejects_unknown_anchor_and_direction():
    g = classic_grid(1337)
    ok, reason, _ = apply_build_road(g, "n:999:999", "east")
    assert not ok and "anchor" in reason
    ok, reason, _ = apply_build_road(g, "n:12:2", "upward")
    assert not ok and "direction" in reason


def test_build_road_is_pure_and_deterministic():
    a, b = classic_grid(1337), classic_grid(1337)
    for nid, d in [("n:12:2", "east"), ("n:17:2", "east"), ("n:2:12", "north")]:
        apply_build_road(a, nid, d)
        apply_build_road(b, nid, d)
    assert a.to_dict() == b.to_dict()  # identical grown graph


def test_nearest_node_picks_closest():
    g = classic_grid(1337)
    n = nearest_node(g, tile_center(2) + 0.1, tile_center(2) - 0.1)
    assert n is not None and n.id == "n:2:2"


def test_extendable_directions_classifies_open_road_edge():
    g = classic_grid(1337)
    dirs = extendable_directions(g, "n:12:2")  # right edge of the grid, middle row
    assert dirs["east"] == "open"   # in-bounds, no edge yet
    assert dirs["west"] == "road"   # n:7:2->n:12:2 exists
    dirs_corner = extendable_directions(g, "n:22:22")
    # n:22:22 doesn't exist yet; but extendable_directions parses the id and bounds-checks
    assert dirs_corner["east"] == "edge" and dirs_corner["north"] == "edge"


# ── EM-244 (S3a): vote-gated demolish + car-policy (pure graph ops) ────────────
from petridish.engine.citygraph import apply_demolish_road, apply_car_policy, CAR_POLICIES


def test_demolish_road_removes_edge_and_orphaned_node():
    g = classic_grid(1337)
    # build a dead-end stub so its far node is orphan-removable on demolish
    apply_build_road(g, "n:12:2", "east")  # adds n:17:2 + e:n:12:2->n:17:2
    n0, e0 = len(g.nodes), len(g.edges)
    ok, reason, info = apply_demolish_road(g, "e:n:12:2->n:17:2")
    assert ok, reason
    assert info["edge_id"] == "e:n:12:2->n:17:2"
    assert "n:17:2" in info["removed_node_ids"]      # the stub's far node had no other edge
    assert len(g.edges) == e0 - 1 and len(g.nodes) == n0 - 1
    assert not any(e.id == "e:n:12:2->n:17:2" for e in g.edges)


def test_demolish_road_keeps_still_connected_nodes():
    g = classic_grid(1337)
    # an interior edge: both endpoints keep other edges, so no node is removed
    ok, reason, info = apply_demolish_road(g, "e:n:7:2->n:12:2")
    assert ok, reason
    assert info["removed_node_ids"] == []
    assert any(n.id == "n:7:2" for n in g.nodes) and any(n.id == "n:12:2" for n in g.nodes)


def test_demolish_road_rejects_unknown_edge():
    g = classic_grid(1337)
    ok, reason, info = apply_demolish_road(g, "e:nope->nope")
    assert not ok and info is None and "no such road" in reason


def test_car_policy_city_sets_graph_default():
    g = classic_grid(1337)
    ok, reason, info = apply_car_policy(g, "city", "pedestrian")
    assert ok and g.car_policy == "pedestrian" and info["scope"] == "city"


def test_car_policy_street_sets_one_edge():
    g = classic_grid(1337)
    ok, reason, info = apply_car_policy(g, "street", "pedestrian", "e:n:7:2->n:12:2")
    assert ok and info["edge_id"] == "e:n:7:2->n:12:2"
    edge = next(e for e in g.edges if e.id == "e:n:7:2->n:12:2")
    assert edge.car_policy == "pedestrian"


def test_car_policy_rejects_bad_policy_scope_and_target():
    g = classic_grid(1337)
    assert not apply_car_policy(g, "city", "flying")[0]
    assert not apply_car_policy(g, "district", "pedestrian")[0]   # deferred
    assert not apply_car_policy(g, "street", "pedestrian", "e:nope")[0]


def test_demolish_road_is_pure_deterministic():
    a, b = classic_grid(1337), classic_grid(1337)
    apply_demolish_road(a, "e:n:7:2->n:12:2"); apply_demolish_road(b, "e:n:7:2->n:12:2")
    apply_car_policy(a, "city", "pedestrian"); apply_car_policy(b, "city", "pedestrian")
    assert a.to_dict() == b.to_dict()

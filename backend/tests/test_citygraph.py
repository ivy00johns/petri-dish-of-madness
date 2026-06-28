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

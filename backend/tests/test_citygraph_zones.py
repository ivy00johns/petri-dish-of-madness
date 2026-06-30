"""EM-265 (SB) Lane 1 — zone-rule data layer + the Python planar-face port.

Pins contract `contracts/em265-build-contract.md` §0 (the law), §2 (the shared
ZoneRule / zone-id / Python-port contract) and §6 (Lane 1 tests):
  • ZoneRule to/from_dict (incl. None / coerced density_cap).
  • `zone_rules` serialized ONLY when non-empty ⇒ pre-SB snapshots stay
    byte-identical (law §0.1).
  • apply_zone_rule replaces by zone_id (one rule per zone, last wins).
  • planar_faces matches the SA matrix (grid→25, pentagon→sectors, radial,
    disconnected, concave) and is SAFE on empty / corrupt / stub / dangling
    graphs (never throws, never drops an enclosed region) and DETERMINISTIC
    under shuffled node/edge order.
  • The cross-language fixture round-trips: planar_faces on each fixture graph
    reproduces the fixture's zone_id set (law §0.2; the frontend asserts the TS
    planarFaces against the SAME file).
"""
import json
import random
from pathlib import Path

import pytest

from petridish.engine.citygraph import (
    CityEdge,
    CityGraph,
    CityNode,
    Face,
    ZONE_HINTS,
    ZoneRule,
    apply_zone_rule,
    classic_grid,
    master_plan,
    planar_faces,
    zone_id_for,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "contracts" / "em265-zone-id-fixture.json"
)


# ── helpers ────────────────────────────────────────────────────────────────────
def _graph_from_fixture(gdict: dict) -> CityGraph:
    return CityGraph(
        seed=1337,
        nodes=[CityNode.from_dict(n) for n in gdict["nodes"]],
        edges=[CityEdge.from_dict(e) for e in gdict["edges"]],
    )


def _square(prefix: str = "", ox: float = 0.0, oz: float = 0.0) -> CityGraph:
    """A unit-ish square block (4 nodes, 4 edges) ⇒ exactly one bounded face."""
    p = prefix
    nodes = [
        CityNode(id=f"{p}A", x=ox + 0.0, z=oz + 0.0),
        CityNode(id=f"{p}B", x=ox + 10.0, z=oz + 0.0),
        CityNode(id=f"{p}C", x=ox + 10.0, z=oz + 10.0),
        CityNode(id=f"{p}D", x=ox + 0.0, z=oz + 10.0),
    ]
    pairs = [(f"{p}A", f"{p}B"), (f"{p}B", f"{p}C"), (f"{p}C", f"{p}D"), (f"{p}D", f"{p}A")]
    edges = [CityEdge(id=f"e:{a}->{b}", a=a, b=b) for a, b in pairs]
    return CityGraph(seed=1, nodes=nodes, edges=edges)


def _merge_graphs(*graphs: CityGraph) -> CityGraph:
    nodes: list[CityNode] = []
    edges: list[CityEdge] = []
    for g in graphs:
        nodes += g.nodes
        edges += g.edges
    return CityGraph(seed=1, nodes=nodes, edges=edges)


def _zone_ids(graph: CityGraph) -> list[str]:
    return sorted(zone_id_for(f.boundary) for f in planar_faces(graph))


# ── ZoneRule to/from_dict ───────────────────────────────────────────────────────
def test_zone_hints_vocabulary_is_frozen():
    assert ZONE_HINTS == frozenset({"residential", "market", "civic", "open"})


def test_zone_rule_round_trip_with_cap():
    rule = ZoneRule(zone_id="a|b|c", hint="residential", density_cap=12)
    d = rule.to_dict()
    assert d == {"zone_id": "a|b|c", "hint": "residential", "density_cap": 12}
    assert ZoneRule.from_dict(d) == rule


def test_zone_rule_round_trip_with_none_cap():
    rule = ZoneRule(zone_id="x|y", hint="open", density_cap=None)
    d = rule.to_dict()
    assert d["density_cap"] is None
    assert ZoneRule.from_dict(d) == rule


def test_zone_rule_default_density_cap_is_none():
    assert ZoneRule(zone_id="z", hint="civic").density_cap is None


def test_zone_rule_from_dict_coerces_types():
    # JSON may carry a stringy cap / non-str zone_id; from_dict normalizes.
    r = ZoneRule.from_dict({"zone_id": 7, "hint": "market", "density_cap": "5"})
    assert r.zone_id == "7" and r.density_cap == 5 and isinstance(r.density_cap, int)


def test_zone_rule_from_dict_absent_cap_is_none():
    r = ZoneRule.from_dict({"zone_id": "q", "hint": "open"})
    assert r.density_cap is None


# ── additive serialization (law §0.1 — byte-identical pre-SB) ───────────────────
def test_zone_rules_omitted_when_empty():
    g = classic_grid(1337)
    d = g.to_dict()
    assert "zone_rules" not in d  # absent key ⇒ byte-identical to a pre-SB snapshot


def test_pre_sb_snapshot_loads_without_zone_rules():
    # A snapshot written before SB has no "zone_rules" key.
    pre_sb = classic_grid(1337).to_dict()
    assert "zone_rules" not in pre_sb
    restored = CityGraph.from_dict(pre_sb)
    assert restored.zone_rules == []
    assert restored.to_dict() == pre_sb  # round-trips byte-identical (no key added)


def test_zone_rules_serialized_when_non_empty():
    g = classic_grid(1337)
    apply_zone_rule(g, ZoneRule("n:-13:-13|n:-13:-8|n:-8:-13|n:-8:-8", "civic", 4))
    d = g.to_dict()
    assert d["zone_rules"] == [
        {"zone_id": "n:-13:-13|n:-13:-8|n:-8:-13|n:-8:-8", "hint": "civic", "density_cap": 4}
    ]


def test_round_trip_preserves_zone_rules():
    g = classic_grid(1337)
    apply_zone_rule(g, ZoneRule("z1", "residential", None))
    apply_zone_rule(g, ZoneRule("z2", "market", 3))
    d = g.to_dict()
    assert CityGraph.from_dict(d).to_dict() == d


# ── apply_zone_rule (one rule per zone, last wins; pure mutation) ────────────────
def test_apply_zone_rule_appends_new_zone():
    g = classic_grid(1337)
    assert apply_zone_rule(g, ZoneRule("z1", "open", None)) is None
    assert len(g.zone_rules) == 1


def test_apply_zone_rule_replaces_same_zone_last_wins():
    g = classic_grid(1337)
    apply_zone_rule(g, ZoneRule("z1", "residential", 10))
    apply_zone_rule(g, ZoneRule("z1", "market", 3))
    assert len(g.zone_rules) == 1
    assert g.zone_rules[0].hint == "market" and g.zone_rules[0].density_cap == 3


def test_apply_zone_rule_distinct_zones_accumulate():
    g = classic_grid(1337)
    apply_zone_rule(g, ZoneRule("z1", "residential", None))
    apply_zone_rule(g, ZoneRule("z2", "civic", None))
    apply_zone_rule(g, ZoneRule("z1", "open", 1))  # replaces z1, keeps z2
    assert [r.zone_id for r in g.zone_rules] == ["z1", "z2"]
    assert g.zone_rules[0].hint == "open"


# ── zone_id_for (IDENTICAL formula to the TS side) ──────────────────────────────
def test_zone_id_for_is_sorted_join():
    assert zone_id_for(["b", "a", "c"]) == "a|b|c"


def test_zone_id_for_is_rotation_and_direction_independent():
    assert zone_id_for(["a", "b", "c", "d"]) == zone_id_for(["c", "d", "a", "b"])
    assert zone_id_for(["a", "b", "c", "d"]) == zone_id_for(["d", "c", "b", "a"])


# ── planar_faces matrix ─────────────────────────────────────────────────────────
def test_planar_faces_grid_25_blocks():
    faces = planar_faces(classic_grid(1337))
    assert len(faces) == 25
    for f in faces:
        assert isinstance(f, Face)
        assert f.area > 0
        assert len(f.boundary) == 4  # every grid block is a quad
        assert round(f.area, 6) == 169.0  # 13.0 x 13.0 block


def test_planar_faces_pentagon_yields_five_sectors():
    faces = planar_faces(master_plan("pentagon", None, 1337))
    assert len(faces) == 5
    for f in faces:
        assert f.area > 0
        # each sector is a triangle: two rim nodes + the center.
        assert len(f.boundary) == 3
        assert "n:pent:c" in f.boundary


def test_planar_faces_radial_collinear_split_yields_sixteen():
    # The center→outer spoke passes THROUGH the inner-ring node (collinear overlap);
    # the sanitizer splits it so the region decomposes into 8 inner triangles + 8
    # outer trapezoids instead of silently dropping a tangled face.
    faces = planar_faces(master_plan("radial", None, 1337))
    assert len(faces) == 16
    assert all(f.area > 0 for f in faces)


def test_planar_faces_disconnected_drops_each_outer_ring_only():
    # Two separate squares ⇒ two bounded faces; each component's outer ring is
    # dropped by winding SIGN (not max |area|), so no real region is lost.
    g = _merge_graphs(_square("p", 0, 0), _square("q", 100, 100))
    faces = planar_faces(g)
    assert len(faces) == 2
    assert all(f.area > 0 for f in faces)


def test_planar_faces_concave_block_is_one_face():
    # Concave L-shaped hexagon (CCW): a single enclosed region survives, outer dropped.
    pts = [("A", 0, 0), ("B", 20, 0), ("C", 20, 10), ("D", 10, 10), ("E", 10, 20), ("F", 0, 20)]
    nodes = [CityNode(id=i, x=float(x), z=float(z)) for i, x, z in pts]
    order = ["A", "B", "C", "D", "E", "F"]
    edges = [
        CityEdge(id=f"e:{order[k]}->{order[(k + 1) % 6]}", a=order[k], b=order[(k + 1) % 6])
        for k in range(6)
    ]
    faces = planar_faces(CityGraph(seed=1, nodes=nodes, edges=edges))
    assert len(faces) == 1
    assert faces[0].area > 0
    assert set(faces[0].boundary) == set(order)


def test_planar_faces_coincident_nodes_merge_no_region_dropped():
    # A2 sits exactly on A (coincident); the edge D->A2 must merge onto D->A so the
    # square still closes into one face (a tangle here would silently drop it).
    g = _square()
    g.nodes.append(CityNode(id="A2", x=0.0, z=0.0))  # coincident with A
    g.edges = [e for e in g.edges if e.id != "e:D->A"]
    g.edges.append(CityEdge(id="e:D->A2", a="D", b="A2"))
    faces = planar_faces(g)
    assert len(faces) == 1
    assert faces[0].area > 0


# ── planar_faces: safe on degenerate / corrupt / stub graphs ────────────────────
def test_planar_faces_none_graph_is_empty():
    assert planar_faces(None) == []


def test_planar_faces_no_edges_is_empty():
    assert planar_faces(CityGraph(seed=1, nodes=[CityNode("A", 0, 0)], edges=[])) == []


def test_planar_faces_empty_graph_is_empty():
    assert planar_faces(CityGraph(seed=1)) == []


def test_planar_faces_corrupt_node_list_is_empty():
    g = classic_grid(1337)
    g.nodes = "not a list"  # type-corrupt (e.g. partially-written snapshot)
    assert planar_faces(g) == []


def test_planar_faces_corrupt_edge_list_is_empty():
    g = classic_grid(1337)
    g.edges = None
    assert planar_faces(g) == []


def test_planar_faces_non_finite_nodes_are_filtered():
    nan = float("nan")
    g = CityGraph(
        seed=1,
        nodes=[CityNode("A", nan, 0.0), CityNode("B", 1.0, nan)],
        edges=[CityEdge(id="e:A->B", a="A", b="B")],
    )
    assert planar_faces(g) == []  # both nodes invalid ⇒ nothing to trace


def test_planar_faces_stub_edge_encloses_nothing():
    g = CityGraph(
        seed=1,
        nodes=[CityNode("A", 0, 0), CityNode("B", 10, 0)],
        edges=[CityEdge(id="e:A->B", a="A", b="B")],
    )
    assert planar_faces(g) == []


def test_planar_faces_dangling_endpoints_dropped_safely():
    # Edge references a node id that does not exist ⇒ dropped, no crash, no face.
    g = CityGraph(
        seed=1,
        nodes=[CityNode("A", 0, 0)],
        edges=[CityEdge(id="e:A->Z", a="A", b="Z")],
    )
    assert planar_faces(g) == []


def test_planar_faces_does_not_mutate_input():
    g = classic_grid(1337)
    before = g.to_dict()
    planar_faces(g)
    assert g.to_dict() == before


# ── determinism under shuffled input order ──────────────────────────────────────
@pytest.mark.parametrize("base", ["grid", "pentagon", "radial"])
def test_planar_faces_deterministic_under_shuffle(base: str):
    g = {
        "grid": classic_grid(1337),
        "pentagon": master_plan("pentagon", None, 1337),
        "radial": master_plan("radial", None, 1337),
    }[base]
    rng = random.Random(99)
    nodes_s = list(g.nodes)
    edges_s = list(g.edges)
    rng.shuffle(nodes_s)
    rng.shuffle(edges_s)
    shuffled = CityGraph(seed=g.seed, nodes=nodes_s, edges=edges_s)

    faces_a = planar_faces(g)
    faces_b = planar_faces(shuffled)
    # zone-id SET is identical (the cross-language invariant)...
    assert sorted(zone_id_for(f.boundary) for f in faces_a) == sorted(
        zone_id_for(f.boundary) for f in faces_b
    )
    # ...and so is the exact walk-order boundary of each face (full determinism).
    assert [f.boundary for f in faces_a] == [f.boundary for f in faces_b]


# ── cross-language fixture (law §0.2) ───────────────────────────────────────────
def test_fixture_exists_and_covers_required_cases():
    data = json.loads(FIXTURE_PATH.read_text())
    names = {c["name"] for c in data["cases"]}
    assert names == {"classic_grid", "pentagon", "radial"}


def test_fixture_round_trips_through_planar_faces():
    data = json.loads(FIXTURE_PATH.read_text())
    for case in data["cases"]:
        graph = _graph_from_fixture(case["graph"])
        computed = sorted(zone_id_for(f.boundary) for f in planar_faces(graph))
        assert computed == case["zone_ids"], f"fixture mismatch for {case['name']}"
        # zone ids are well-formed: each is its own sorted boundary join.
        for zid in case["zone_ids"]:
            parts = zid.split("|")
            assert parts == sorted(parts)


def test_fixture_matches_live_generators():
    # The fixture must equal what the REAL generators produce right now (it was
    # generated from them; this guards against the checked-in JSON drifting).
    data = json.loads(FIXTURE_PATH.read_text())
    live = {
        "classic_grid": _zone_ids(classic_grid(1337)),
        "pentagon": _zone_ids(master_plan("pentagon", None, 1337)),
        "radial": _zone_ids(master_plan("radial", None, 1337)),
    }
    for case in data["cases"]:
        assert case["zone_ids"] == live[case["name"]]

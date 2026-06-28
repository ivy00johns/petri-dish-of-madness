"""EM-239 (S1) — the authoritative CityGraph: roads as first-class, mutable,
snapshot-serialized state. S1 ships only the axis-aligned `classic_grid`
template that reproduces today's frozen 5x5 grid; lots/zones/landmarks/streets
keep deriving from the graph on the frontend. Pure + seeded (EM-155).

Frozen geometry (must match web/src/components/world3d/cityLayout.ts; the
byte-identical test enforces agreement):
  TILE = 2.6, BLOCK_PITCH = 13.0, road-line indices = ((i-2) % 5 == 0) within
  [-13, 12] = (-13, -8, -3, 2, 7, 12); tile center = (i + 0.5) * TILE.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

TILE: float = 2.6
BLOCK_PITCH: float = 13.0
ROAD_TILE_INDICES: tuple[int, ...] = (-13, -8, -3, 2, 7, 12)


def tile_center(i: int) -> float:
    return (i + 0.5) * TILE


@dataclass
class CityNode:
    id: str
    x: float
    z: float
    kind: str = "junction"  # S1: all junctions (S3 adds roundabout/plaza/dead_end)

    def to_dict(self) -> dict:
        return {"id": self.id, "x": self.x, "z": self.z, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict) -> "CityNode":
        return cls(id=str(d["id"]), x=float(d["x"]), z=float(d["z"]),
                   kind=str(d.get("kind", "junction")))


@dataclass
class CityEdge:
    id: str
    a: str
    b: str
    road_class: str = "street"   # S1: single class
    car_policy: str = "inherit"  # S1: inherits the graph default

    def to_dict(self) -> dict:
        return {"id": self.id, "a": self.a, "b": self.b,
                "road_class": self.road_class, "car_policy": self.car_policy}

    @classmethod
    def from_dict(cls, d: dict) -> "CityEdge":
        return cls(id=str(d["id"]), a=str(d["a"]), b=str(d["b"]),
                   road_class=str(d.get("road_class", "street")),
                   car_policy=str(d.get("car_policy", "inherit")))


@dataclass
class CityGraph:
    seed: int
    version: int = 1
    car_policy: str = "cars"  # global default (S3 flips it for "ban cars")
    template: str = "grid"  # EM-246 (S4) — the run-start profile kind (records intent)
    nodes: list[CityNode] = field(default_factory=list)
    edges: list[CityEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "seed": self.seed,
            "car_policy": self.car_policy,
            "template": self.template,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityGraph":
        return cls(
            seed=int(d.get("seed", 1337)),
            version=int(d.get("version", 1)),
            car_policy=str(d.get("car_policy", "cars")),
            template=str(d.get("template", "grid")),
            nodes=[CityNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[CityEdge.from_dict(e) for e in d.get("edges", [])],
        )


def _node_id(i: int, j: int) -> str:
    return f"n:{i}:{j}"


def classic_grid(seed: int) -> CityGraph:
    """The axis-aligned 5x5-block grid that reproduces today's frozen city:
    nodes at the 36 road-line intersections, edges along each line between
    adjacent intersections. Pure function of `seed` (the grid itself is frozen;
    `seed` rides on the graph for downstream seeded derivations)."""
    nodes: list[CityNode] = []
    for j in ROAD_TILE_INDICES:
        for i in ROAD_TILE_INDICES:
            nodes.append(CityNode(id=_node_id(i, j), x=tile_center(i), z=tile_center(j)))

    edges: list[CityEdge] = []
    n = len(ROAD_TILE_INDICES)
    # Horizontal lines (constant j): connect adjacent i.
    for j in ROAD_TILE_INDICES:
        for k in range(n - 1):
            a, b = _node_id(ROAD_TILE_INDICES[k], j), _node_id(ROAD_TILE_INDICES[k + 1], j)
            edges.append(CityEdge(id=f"e:{a}->{b}", a=a, b=b))
    # Vertical lines (constant i): connect adjacent j.
    for i in ROAD_TILE_INDICES:
        for k in range(n - 1):
            a, b = _node_id(i, ROAD_TILE_INDICES[k]), _node_id(i, ROAD_TILE_INDICES[k + 1])
            edges.append(CityEdge(id=f"e:{a}->{b}", a=a, b=b))

    return CityGraph(seed=int(seed), nodes=nodes, edges=edges)


# ── EM-243 (S2): bounded, deterministic individual road growth ────────────────
# The frozen 5x5 grid spans tile-index [-13, 12] (6 road lines, all ≡ 2 mod 5).
# MAX_CITY_BLOCKS=9 widens that to a 9x9 envelope = 10 lines = index [-23, 22].
# A segment is one BLOCK_PITCH = 5 index steps (5 * TILE = 13.0u).
MAX_CITY_BLOCKS: int = 9
MIN_IDX: int = -23
MAX_IDX: int = 22

# direction -> (di, dj) in tile-index space (east = +x, north = +z; the N/S label
# is cosmetic and may be flipped to match the on-screen compass — determinism is
# unaffected since ids derive from (i, j), not from the label).
DIR_DELTA: dict[str, tuple[int, int]] = {
    "east": (5, 0), "west": (-5, 0), "north": (0, 5), "south": (0, -5),
}


def _parse_node(node_id: str) -> tuple[int, int]:
    """'n:{i}:{j}' -> (i, j). Raises ValueError on a malformed id."""
    parts = node_id.split(":")
    if len(parts) != 3 or parts[0] != "n":
        raise ValueError(f"malformed node id: {node_id!r}")
    return int(parts[1]), int(parts[2])


def _ordered_edge(id_a: str, id_b: str) -> tuple[str, str, str]:
    """Order two node ids by (i, j) ascending and build the edge id — reproducing
    classic_grid's a->b convention (horizontal by i, vertical by j), so a grown
    grid's edge ids match what a larger classic_grid would emit. Returns (id, a, b)."""
    a, b = sorted([id_a, id_b], key=_parse_node)
    return f"e:{a}->{b}", a, b


def _in_bounds(i: int, j: int) -> bool:
    return MIN_IDX <= i <= MAX_IDX and MIN_IDX <= j <= MAX_IDX


def nearest_node(graph: CityGraph, x: float, z: float) -> CityNode | None:
    """The graph node closest (Euclidean) to a world (x, z). None on an empty graph.
    Note: callers map a place's (x, y) -> (x, z) here (place.y is the world z)."""
    if not graph.nodes:
        return None
    return min(graph.nodes, key=lambda n: (n.x - x) ** 2 + (n.z - z) ** 2)


def extendable_directions(graph: CityGraph, node_id: str) -> dict[str, str]:
    """For each cardinal direction from node_id: 'open' (in-bounds, no edge yet),
    'road' (an edge already runs that way), or 'edge' (out of the city envelope).
    Empty dict if node_id is malformed."""
    try:
        fi, fj = _parse_node(node_id)
    except ValueError:
        return {}
    edge_ids = {e.id for e in graph.edges}
    out: dict[str, str] = {}
    for d, (di, dj) in DIR_DELTA.items():
        ni, nj = fi + di, fj + dj
        if not _in_bounds(ni, nj):
            out[d] = "edge"
            continue
        eid, _, _ = _ordered_edge(node_id, _node_id(ni, nj))
        out[d] = "road" if eid in edge_ids else "open"
    return out


def apply_build_road(
    graph: CityGraph, from_node_id: str, direction: str,
) -> tuple[bool, str, dict | None]:
    """Extend the graph one segment from from_node_id in direction (N/S/E/W).
    Pure validation + in-place mutation on success. Adds the target node if absent
    and the connecting edge. Returns (ok, reason, info). info on success:
    {from_node, direction, new_node_id, new_edge_id}."""
    if direction not in DIR_DELTA:
        return False, f"unknown direction '{direction}' (use north/south/east/west)", None
    if not any(n.id == from_node_id for n in graph.nodes):
        return False, "no anchor node there to build from", None
    try:
        fi, fj = _parse_node(from_node_id)
    except ValueError:
        return False, "the anchor node id is malformed", None
    di, dj = DIR_DELTA[direction]
    ni, nj = fi + di, fj + dj
    if not _in_bounds(ni, nj):
        return False, "that way is the edge of the city (out of bounds)", None
    new_node_id = _node_id(ni, nj)
    new_edge_id, a, b = _ordered_edge(from_node_id, new_node_id)
    if any(e.id == new_edge_id for e in graph.edges):
        return False, "there's already a road that way", None
    if not any(n.id == new_node_id for n in graph.nodes):
        graph.nodes.append(CityNode(id=new_node_id, x=tile_center(ni), z=tile_center(nj)))
    graph.edges.append(CityEdge(id=new_edge_id, a=a, b=b))
    return True, "ok", {
        "from_node": from_node_id, "direction": direction,
        "new_node_id": new_node_id, "new_edge_id": new_edge_id,
    }


# ── EM-244 (S3a): vote-gated demolish + car-policy (pure graph ops) ────────────
CAR_POLICIES: frozenset[str] = frozenset({"cars", "pedestrian", "mixed"})
CAR_SCOPES: frozenset[str] = frozenset({"city", "street"})  # 'district' deferred (no edge->district map)


def apply_demolish_road(graph: CityGraph, edge_id: str) -> tuple[bool, str, dict | None]:
    """Remove the edge `edge_id`; also remove either endpoint node that is left with
    NO remaining edges (a freed dead-end stub). Pure + deterministic. Returns
    (ok, reason, info); info = {edge_id, removed_node_ids (sorted)}."""
    edge = next((e for e in graph.edges if e.id == edge_id), None)
    if edge is None:
        return False, f"no such road to tear down ({edge_id})", None
    # EM-244 (S3a): keep at least one road. A city demolished to zero edges would
    # leave the frontend's graph-vs-fallback guard (an empty edge list reads as
    # "absent/corrupt graph") resurrecting the hardcoded 5x5 grid — the opposite of
    # the vote's intent. A one-road floor keeps the graph authoritative + non-empty.
    if len(graph.edges) <= 1:
        return False, "can't tear down the last road in the city", None
    a, b = edge.a, edge.b
    graph.edges = [e for e in graph.edges if e.id != edge_id]
    still = {nid for e in graph.edges for nid in (e.a, e.b)}
    removed = sorted(nid for nid in (a, b) if nid not in still)
    if removed:
        graph.nodes = [n for n in graph.nodes if n.id not in removed]
    return True, "ok", {"edge_id": edge_id, "removed_node_ids": removed}


def apply_car_policy(
    graph: CityGraph, scope: str, policy: str, target: str | None = None,
) -> tuple[bool, str, dict | None]:
    """Set the car policy. scope='city' sets graph.car_policy; scope='street' sets
    one edge's car_policy (target=edge id). 'district' is deferred. Pure."""
    if policy not in CAR_POLICIES:
        return False, f"car policy must be one of {sorted(CAR_POLICIES)} (got {policy!r})", None
    if scope == "city":
        graph.car_policy = policy
        return True, "ok", {"scope": "city", "policy": policy}
    if scope == "street":
        edge = next((e for e in graph.edges if e.id == target), None)
        if edge is None:
            return False, f"no such street to set policy on ({target})", None
        edge.car_policy = policy
        return True, "ok", {"scope": "street", "policy": policy, "edge_id": target}
    return False, f"car-policy scope must be 'city' or 'street' (got {scope!r}; 'district' not yet supported)", None


# ── EM-246 (S4): run-start templates ───────────────────────────────────────────
# grid/greenfield/village ship now (axis-aligned); pentagon/radial/ring need
# EM-245 (master_plan) + EM-247 (meshing) → grid fallback.
TEMPLATE_KINDS: frozenset[str] = frozenset({"grid", "greenfield", "village"})
_DENSITY_KEEP: dict[str, float] = {"low": 0.4, "medium": 0.6, "high": 0.8}
# the central block's two lattice lines closest to the origin (lo, hi)
_CENTRAL_IDX: tuple[int, int] = (-3, 2)


def _seeded_unit(seed: int, key: str) -> float:
    """Deterministic [0,1) from (seed, key) — stdlib sha1, pure (village sparsity)."""
    h = hashlib.sha1(f"{seed}:{key}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0x100000000


def _central_plaza_edges() -> list[tuple[int, int, int, int]]:
    """The four edges of the central block as (ia, ja, ib, jb) index pairs."""
    lo, hi = _CENTRAL_IDX
    return [
        (lo, lo, hi, lo), (lo, hi, hi, hi),  # south + north sides
        (lo, lo, lo, hi), (hi, lo, hi, hi),  # west + east sides
    ]


def _build_from_index_edges(seed: int, idx_edges, template_kind: str) -> CityGraph:
    """Assemble a CityGraph from (ia,ja,ib,jb) index-edge tuples — nodes derived
    from the endpoints, edges via _ordered_edge (classic_grid's id convention)."""
    nodes: dict[str, CityNode] = {}
    edges: list[CityEdge] = []
    seen: set[str] = set()
    for ia, ja, ib, jb in idx_edges:
        aid, bid = _node_id(ia, ja), _node_id(ib, jb)
        for nid, (i, j) in ((aid, (ia, ja)), (bid, (ib, jb))):
            if nid not in nodes:
                nodes[nid] = CityNode(id=nid, x=tile_center(i), z=tile_center(j))
        eid, a, b = _ordered_edge(aid, bid)
        if eid not in seen:
            seen.add(eid)
            edges.append(CityEdge(id=eid, a=a, b=b))
    return CityGraph(seed=int(seed), template=template_kind,
                     nodes=list(nodes.values()), edges=edges)


def _greenfield(seed: int) -> CityGraph:
    """Minimal: a single central-block plaza (4 nodes / 4 edges). Agents build the
    rest. Non-empty (one-road floor holds), the 'maybe they build nothing' start."""
    return _build_from_index_edges(seed, _central_plaza_edges(), "greenfield")


def _village(seed: int, density: str) -> CityGraph:
    """Sparse axis-aligned scatter: classic_grid's edges thinned by a seeded keep
    probability, with the central plaza always kept (connected, non-empty core).
    Organic (non-axis-aligned) village waits for S5a."""
    keep = _DENSITY_KEEP.get(density, 0.6)
    full = classic_grid(seed)
    # central edges via _ordered_edge — the canonical id matching classic_grid's.
    core = {_ordered_edge(_node_id(ia, ja), _node_id(ib, jb))[0]
            for (ia, ja, ib, jb) in _central_plaza_edges()}
    kept = [e for e in full.edges
            if e.id in core or _seeded_unit(seed, f"village:{e.id}") < keep]
    keep_ids = {e.id for e in kept}
    live = {nid for e in kept for nid in (e.a, e.b)}
    nodes = [n for n in full.nodes if n.id in live]
    g = CityGraph(seed=int(seed), template="village", nodes=nodes,
                  edges=[e for e in full.edges if e.id in keep_ids])
    return g


def template(kind: str, seed: int, *, size: int = 5, density: str = "medium") -> CityGraph:
    """Build the run-start CityGraph for a city profile. grid/greenfield/village
    ship now; pentagon/radial/ring fall back to grid (need EM-245 + EM-247) but
    record the requested kind in `.template` so the caller can warn + the UI reflect
    intent. `size` is RESERVED — accepted for forward-compat but NOT yet honored:
    greenfield is a fixed central plaza and village thins the canonical 5x5, so the
    extent is fixed for now (scaling it is a follow-up, tracked with the geometric
    presets that ride EM-245/EM-247). grid is always the canonical 5x5."""
    if kind == "grid":
        return classic_grid(seed)  # .template defaults to 'grid'
    if kind == "greenfield":
        return _greenfield(seed)
    if kind == "village":
        return _village(seed, density)
    # unknown / geometric: grid topology, but record the requested kind.
    g = classic_grid(seed)
    g.template = kind
    return g

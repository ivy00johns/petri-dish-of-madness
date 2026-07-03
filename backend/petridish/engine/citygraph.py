"""EM-239 (S1) — the authoritative CityGraph: roads as first-class, mutable,
snapshot-serialized state. S1 ships only the axis-aligned `classic_grid`
template that reproduces today's frozen 5x5 grid; lots/zones/landmarks/streets
keep deriving from the graph on the frontend. Pure + seeded (EM-155).

Frozen geometry (must match web/src/components/world3d/cityLayout.ts; the
byte-identical test enforces agreement):
  TILE = 2.6, BLOCK_PITCH = 13.0, road-line indices = ((i-2) % 5 == 0) within
  [-13, 12] = (-13, -8, -3, 2, 7, 12); tile center = (i + 0.5) * TILE.

EM-243 ↔ EM-245/246 exclusivity: individual `apply_build_road` growth (EM-243) is
LATTICE-ONLY — it parses `n:i:j` ids and steps in BLOCK_PITCH units. A geometric
master-plan city (EM-245/246: pentagon/radial/ring, whose nodes are `n:pent:*`,
`n:rad*:*`, `n:ring:*` off the tile lattice) has no axis-aligned grid to extend, so
build_road on such a node fails with a plain "no lattice grid to extend" (A5) and
its nodes yield no extendable directions (the build_road menu is suppressed there).
The two road systems are mutually exclusive; a city is grown one way or the other.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

TILE: float = 2.6
BLOCK_PITCH: float = 13.0
ROAD_TILE_INDICES: tuple[int, ...] = (-13, -8, -3, 2, 7, 12)


def tile_center(i: int) -> float:
    return (i + 0.5) * TILE


# ── fix-wave A1: logical (place) coords → world (graph) frame ──────────────────
# A place's (x, y) are LOGICAL 0..1000 coords; the CityGraph lives in the ±32.5
# world frame (tile-center units). Callers MUST map through here before nearest_node
# / face-centroid distance, else every place snaps to the n:12:12 corner. Mirrors
# web/src/components/world3d/worldSpace.ts (SIZE / toWorldX / toWorldZ) EXACTLY so
# backend + frontend place the same building on the same block.
WORLD_SIZE: float = 66.0   # MUST equal web worldSpace.ts SIZE


def logical_to_world(x: float, y: float) -> tuple[float, float]:
    """Place logical coords (0..1000) → world (x, z). Mirrors web/worldSpace.ts."""
    return ((x / 1000.0 - 0.5) * WORLD_SIZE, (y / 1000.0 - 0.5) * WORLD_SIZE)


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


# ── EM-265 (SB): agent-authored zone rules (advisory metadata) ────────────────
# A ratified ZoneRule tags a planar face (city block) of the road graph with a
# land-use hint + an optional density cap. Advisory ONLY in SB — nothing enforces
# it (that's SC). The zone's identity is its face id (see `zone_id_for`), so a
# rule stays bound to its block across snapshot/replay/fork; a master-plan morph
# that destroys the block re-points or drops the rule (Lane 2's morph-survival).
ZONE_HINTS: frozenset[str] = frozenset({"residential", "market", "civic", "open"})


@dataclass
class ZoneRule:
    """One advisory rule per zone. `zone_id` is the face id (`zone_id_for`);
    `hint` ∈ ZONE_HINTS; `density_cap` is None (no cap) or an int >= 0."""
    zone_id: str
    hint: str
    density_cap: int | None = None

    def to_dict(self) -> dict:
        return {"zone_id": self.zone_id, "hint": self.hint,
                "density_cap": self.density_cap}

    @classmethod
    def from_dict(cls, d: dict) -> "ZoneRule":
        dc = d.get("density_cap", None)
        return cls(zone_id=str(d["zone_id"]), hint=str(d["hint"]),
                   density_cap=None if dc is None else int(dc))


@dataclass
class CityGraph:
    seed: int
    version: int = 1
    car_policy: str = "cars"  # global default (S3 flips it for "ban cars")
    template: str = "grid"  # EM-246 (S4) — the run-start profile kind (records intent)
    nodes: list[CityNode] = field(default_factory=list)
    edges: list[CityEdge] = field(default_factory=list)
    # EM-265 (SB) — additive: serialized ONLY when non-empty (law §0.1, byte-identical).
    zone_rules: list[ZoneRule] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "version": self.version,
            "seed": self.seed,
            "car_policy": self.car_policy,
            "template": self.template,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }
        # Omit the key entirely when empty so pre-SB snapshots stay byte-identical.
        if self.zone_rules:
            d["zone_rules"] = [z.to_dict() for z in self.zone_rules]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CityGraph":
        return cls(
            seed=int(d.get("seed", 1337)),
            version=int(d.get("version", 1)),
            car_policy=str(d.get("car_policy", "cars")),
            template=str(d.get("template", "grid")),
            nodes=[CityNode.from_dict(n) for n in d.get("nodes", [])],
            edges=[CityEdge.from_dict(e) for e in d.get("edges", [])],
            zone_rules=[ZoneRule.from_dict(z) for z in d.get("zone_rules", [])],
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
        # fix-wave A5: the node EXISTS (checked just above) but its id is not a
        # lattice n:i:j id — a geometric master-plan city (EM-245/246: n:pent:*,
        # n:rad*:*, n:ring:*) has no axis-aligned grid to grow. Say so honestly
        # instead of "malformed" (which reads like corrupt input, not the real
        # cause). EM-243 individual growth is grid-only; the two are exclusive.
        return False, "this city's road plan has no lattice grid to extend", None
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
    ship now; EM-245 (S3b) makes pentagon/radial/ring LIVE — they now route to
    `master_plan` (a geometric plan seeded at start, no morph) instead of the grid
    fallback, recording the requested kind in `.template`. Their non-axis-aligned
    *visual* renders correctly through EM-247's mesh once `ROAD_MESH_ENABLED` is on.
    Truly unknown kinds still fall back to grid topology (kind recorded for the
    warning + UI). `size` is RESERVED — accepted for forward-compat but NOT yet
    honored: greenfield is a fixed central plaza and village thins the canonical
    5x5, so the extent is fixed for now (scaling it is a follow-up). grid is always
    the canonical 5x5."""
    if kind == "grid":
        return classic_grid(seed)  # .template defaults to 'grid'
    if kind == "greenfield":
        return _greenfield(seed)
    if kind == "village":
        return _village(seed, density)
    # EM-245 (S3b) — geometric presets are now live (a master plan seeded at start,
    # no morph); the geometric visual rides EM-247's mesh under ROAD_MESH_ENABLED.
    if kind in ("pentagon", "radial", "ring"):
        return master_plan(kind, {"radius": _PLAN_RADIUS}, seed)
    # truly unknown: grid topology, but record the requested kind.
    g = classic_grid(seed)
    g.template = kind
    return g


# ── EM-245 (S3b): parametric master-plan generators + diff ─────────────────────
# Pure fn of (kind, params, seed). Geometric kinds use their OWN deterministic id
# scheme (positions are off the tile lattice); EM-247's buildRoadMesh reads x,z so
# any ids render. grid reuses classic_grid.
MASTER_PLAN_KINDS: frozenset[str] = frozenset({"pentagon", "radial", "ring", "grid"})
_PLAN_RADIUS = 26.0   # world units (within the 9x9 envelope ~ +-32)


def _ordered_edge_geom(id_a: str, id_b: str) -> tuple[str, str, str]:
    """Edge id for geometric (non-lattice) node ids: order lexicographically for a
    stable canonical id (the lattice _ordered_edge parses n:i:j, which geom ids aren't)."""
    a, b = sorted([id_a, id_b])
    return f"e:{a}->{b}", a, b


def _ring_plan(prefix: str, seed: int, sides: int, radius: float,
               with_center: bool, with_ring: bool) -> CityGraph:
    """A perimeter polygon of `sides` nodes on a circle + optional center + spokes."""
    nodes: list[CityNode] = []
    edges: list[CityEdge] = []
    pts: list[str] = []
    for k in range(sides):
        ang = (k / sides) * 2 * math.pi
        nid = f"n:{prefix}:{k}"
        nodes.append(CityNode(id=nid, x=radius * math.cos(ang), z=radius * math.sin(ang)))
        pts.append(nid)
    if with_ring:
        for k in range(sides):
            a, b = pts[k], pts[(k + 1) % sides]
            eid, ea, eb = _ordered_edge_geom(a, b)
            edges.append(CityEdge(id=eid, a=ea, b=eb))
    if with_center:
        cid = f"n:{prefix}:c"
        nodes.append(CityNode(id=cid, x=0.0, z=0.0, kind="roundabout"))
        for k, p in enumerate(pts):
            eid, ea, eb = _ordered_edge_geom(p, cid)
            edges.append(CityEdge(id=eid, a=ea, b=eb))
    return CityGraph(seed=int(seed), nodes=nodes, edges=edges)


def master_plan(kind: str, params: dict | None, seed: int) -> CityGraph:
    """Target CityGraph for a master plan. Pure fn of (kind, params, seed).
    Unknown kind ⇒ classic_grid (safe fallback). `template` records the kind."""
    p = params or {}
    radius = float(p.get("radius", _PLAN_RADIUS))
    if kind == "grid":
        return classic_grid(seed)
    if kind == "pentagon":
        g = _ring_plan("pent", seed, int(p.get("sides", 5)), radius, True, True)
    elif kind == "radial":
        # two concentric rings + spokes to a SHARED roundabout center. The outer
        # ring carries the center ('n:radO:c') + its spokes; the inner ring's nodes
        # also spoke to that SAME center, so the plan is one connected component
        # (a floating inner ring with no inter-ring/center link was a topology bug).
        spokes = int(p.get("spokes", 8))
        outer = _ring_plan("radO", seed, spokes, radius, True, True)
        inner = _ring_plan("radI", seed, spokes, radius * 0.5, False, True)
        edges = list(outer.edges) + list(inner.edges)
        for n in inner.nodes:
            eid, ea, eb = _ordered_edge_geom(n.id, "n:radO:c")
            edges.append(CityEdge(id=eid, a=ea, b=eb))
        g = CityGraph(seed=int(seed), nodes=outer.nodes + inner.nodes, edges=edges)
    elif kind == "ring":
        g = _ring_plan("ring", seed, int(p.get("sides", 8)), radius, False, True)
    else:
        return classic_grid(seed)
    g.template = kind
    return g


def diff_graphs(current: CityGraph, target: CityGraph) -> dict:
    """Node/edge add+remove sets to morph `current` toward `target`, matched by id
    (a geometric target's ids are disjoint from the grid ⇒ full swap). Deterministic
    order (target order for adds, current order for removes)."""
    cur_node_ids = {n.id for n in current.nodes}
    cur_edge_ids = {e.id for e in current.edges}
    tgt_node_ids = {n.id for n in target.nodes}
    tgt_edge_ids = {e.id for e in target.edges}
    return {
        "add_nodes": [n for n in target.nodes if n.id not in cur_node_ids],
        "add_edges": [e for e in target.edges if e.id not in cur_edge_ids],
        "remove_node_ids": [n.id for n in current.nodes if n.id not in tgt_node_ids],
        "remove_edge_ids": [e.id for e in current.edges if e.id not in tgt_edge_ids],
    }


# ── EM-265 (SB): planar faces (city blocks) — Python port of cityFaces.ts ──────
# A FAITHFUL port of the HARDENED web/src/components/world3d/cityFaces.ts so the
# zone id a face yields here equals the one the frontend's planarFaces yields for
# the same graph (law §0.2, pinned by contracts/em265-zone-id-fixture.json).
#
# The law (mirrors cityFaces.ts §0):
#   • DETERMINISTIC — pure fn of the graph. Node/edge INPUT ORDER must not affect
#     output: sort nodes/edges by id, sort each vertex's half-edges by angle, walk
#     from a globally-sorted half-edge order.
#   • NEVER THROWS, NEVER SILENTLY DROPS A REGION — a corrupt / stub / disconnected
#     / degenerate graph returns []. We drop ONLY the unbounded outer face(s),
#     identified PER-CYCLE by winding (signed area <= 0); every enclosed region
#     survives (the forbidden failure is dropping an enclosed face). Worst case is
#     a clean WHOLE-graph [] (caller falls back to the grid) — never a partial drop.
#   • Sanitize a working copy first: (1) merge coincident nodes onto a 1e-6
#     lattice, (2) split collinear-overlapping edges at interior nodes, (3) tie-break
#     residual equal angles by distance, (4) whole-graph [] backstop on a residual
#     exact-direction tie.

# Coincident-node merge quantum (world units): two nodes rounding to the same
# integer lattice cell are treated as one (a 0.001 nudge lands in a different cell).
_MERGE_QUANT: float = 1e-6
# A node within this perpendicular distance of an edge (strictly between its
# endpoints) is treated as lying ON it ⇒ the edge is split there.
_ON_SEG_EPS: float = 1e-6
# Exclude the endpoints themselves from the point-on-segment test.
_ON_SEG_T_EPS: float = 1e-9
# Two outgoing half-edges whose normalized cross is below this (and dot > 0) point
# in the SAME direction — an unresolved angular tie ⇒ whole-graph [].
_DIR_TIE_EPS: float = 1e-9
# Below this |area| a polygon centroid degenerates; fall back to the vertex mean.
_AREA_EPS: float = 1e-12


@dataclass
class _HalfEdge:
    frm: str
    to: str
    dx: float
    dz: float
    length: float
    angle: float


@dataclass
class Face:
    """A bounded planar face (city block). `boundary` are node ids in walk order
    (loose; may be slightly degenerate); `poly` are world-space {x,z} vertices in
    the same order; `area` is the signed area (CCW positive, always > 0 here)."""
    boundary: list[str]
    poly: list[dict]
    centroid: dict
    area: float


def _signed_area(poly: list[dict]) -> float:
    a = 0.0
    n = len(poly)
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        a += p["x"] * q["z"] - q["x"] * p["z"]
    return a / 2.0


def _polygon_centroid(poly: list[dict], area: float) -> dict:
    if not poly:
        return {"x": 0.0, "z": 0.0}
    if len(poly) < 3 or abs(area) < _AREA_EPS:
        # Degenerate (sliver / collinear): area-weighted centroid is unstable, so
        # fall back to the vertex mean — still inside the loose polygon's hull.
        sx = sum(p["x"] for p in poly)
        sz = sum(p["z"] for p in poly)
        return {"x": sx / len(poly), "z": sz / len(poly)}
    cx = 0.0
    cz = 0.0
    n = len(poly)
    for i in range(n):
        p = poly[i]
        q = poly[(i + 1) % n]
        cross = p["x"] * q["z"] - q["x"] * p["z"]
        cx += (p["x"] + q["x"]) * cross
        cz += (p["z"] + q["z"]) * cross
    f = 1.0 / (6.0 * area)
    return {"x": cx * f, "z": cz * f}


def _point_on_segment(px: float, pz: float, ax: float, az: float,
                      bx: float, bz: float) -> float | None:
    """If p lies strictly between a→b and within _ON_SEG_EPS of the line, return
    its parameter t∈(0,1); else None. Used to planarize collinear overlaps."""
    dx = bx - ax
    dz = bz - az
    len2 = dx * dx + dz * dz
    if len2 == 0:
        return None  # degenerate segment encloses nothing to split
    t = ((px - ax) * dx + (pz - az) * dz) / len2
    if t <= _ON_SEG_T_EPS or t >= 1 - _ON_SEG_T_EPS:
        return None  # endpoint / outside
    d = math.hypot(px - (ax + t * dx), pz - (az + t * dz))
    return t if d <= _ON_SEG_EPS else None


def _same_direction(p: _HalfEdge, q: _HalfEdge) -> bool:
    """Two outgoing half-edges point the same way (an unresolved angular tie) when
    their normalized cross ≈ 0 AND they face the same way (dot > 0). Vector-based,
    so it catches the ±π wrap an angle compare would miss."""
    if p.length == 0 or q.length == 0:
        return False
    cross = (p.dx * q.dz - p.dz * q.dx) / (p.length * q.length)
    dot = p.dx * q.dx + p.dz * q.dz
    return abs(cross) < _DIR_TIE_EPS and dot > 0


def _is_valid_node(n) -> bool:
    return (
        isinstance(getattr(n, "id", None), str)
        and isinstance(getattr(n, "x", None), (int, float))
        and not isinstance(n.x, bool)
        and math.isfinite(n.x)
        and isinstance(getattr(n, "z", None), (int, float))
        and not isinstance(n.z, bool)
        and math.isfinite(n.z)
    )


def _add_undirected(m: dict, a: str, b: str) -> None:
    """Insert an undirected edge, canonically keyed, first-wins (dedupes exact
    duplicates + the duplicates node-merge / edge-split create). Self-loops drop."""
    if a == b:
        return
    key = (a, b) if a < b else (b, a)
    if key not in m:
        m[key] = (a, b)


def _planar_faces_uncached(graph) -> list[Face]:
    """Trace the bounded planar faces (city blocks) of the road graph. Pure +
    deterministic (sort nodes/edges by id first). Defensive: stubs, disconnected
    components, and degenerate faces are tolerated; coincident nodes and collinear
    edge overlaps are sanitized first so an angular tie never silently drops a
    region; a graph with no real nodes/edges returns []. NEVER throws; NEVER drops
    an enclosed region (worst case: clean whole-graph [])."""
    # ModelBoundary guard — not a graph, nodes/edges aren't lists, or no edges ⇒ [].
    if (
        graph is None
        or not isinstance(getattr(graph, "nodes", None), list)
        or not isinstance(getattr(graph, "edges", None), list)
        or len(graph.edges) == 0
    ):
        return []

    # Sort nodes by id ⇒ input order never matters.
    sorted_nodes = sorted(
        (n for n in graph.nodes if _is_valid_node(n)), key=lambda n: n.id
    )
    if not sorted_nodes:
        return []

    # ── Sanitize step 1: MERGE coincident nodes ────────────────────────────────
    # Two node ids at the SAME coord give the walk two outgoing half-edges at an
    # IDENTICAL angle, tangling a bounded face into the outer face (silent drop).
    # Group nodes onto a fine lattice and collapse each cell to one canonical id
    # (lex-smallest, for determinism). first-wins on duplicate ids, too.
    canon_of: dict[str, str] = {}       # origId → canonical id
    canon_nodes: dict[str, dict] = {}   # canonical id → {"id","x","z"}
    cell_to_canon: dict[str, str] = {}  # quant cell → canonical id
    for n in sorted_nodes:
        if n.id in canon_of:
            continue  # duplicate id: first (lex-smallest) wins
        # HALF-UP rounding (math.floor(v + 0.5)) to match JS Math.round on the TS
        # side (cityFaces.ts). Python's built-in round() is half-to-EVEN, so at an
        # exact-half lattice value (e.g. x/1e-6 == 1000002.5) it would pick a
        # DIFFERENT cell than Math.round → a different merge → a different zone_id
        # SET → a rule tints the wrong block (law §0.2). floor(v+0.5) matches
        # Math.round on both signs: floor(1000002.5+0.5)=1000003 == Math.round;
        # floor(-2.5+0.5)=-2 == Math.round(-2.5). (Pinned by the tie fixture case.)
        cell = (
            f"{math.floor(n.x / _MERGE_QUANT + 0.5)}"
            f"|{math.floor(n.z / _MERGE_QUANT + 0.5)}"
        )
        existing = cell_to_canon.get(cell)
        if existing is not None:
            canon_of[n.id] = existing  # coincident with an earlier node → merge
        else:
            cell_to_canon[cell] = n.id
            canon_of[n.id] = n.id
            canon_nodes[n.id] = {"id": n.id, "x": float(n.x), "z": float(n.z)}
    if not canon_nodes:
        return []

    # Sort edges by id (then endpoints), rewrite endpoints to canonical ids, drop
    # self-loops + dangling endpoints + exact duplicates.
    def _edge_key(e):
        eid = getattr(e, "id", None)
        return eid if isinstance(eid, str) else (str(getattr(e, "a", "")), str(getattr(e, "b", "")))

    sorted_edges = sorted((e for e in graph.edges if e is not None), key=_edge_key)
    undirected: dict = {}
    for e in sorted_edges:
        ea = getattr(e, "a", None)
        eb = getattr(e, "b", None)
        if not isinstance(ea, str) or not isinstance(eb, str):
            continue
        a = canon_of.get(ea)
        b = canon_of.get(eb)
        if a is None or b is None:
            continue  # dangling endpoint
        _add_undirected(undirected, a, b)  # a==b (self-loop / merged) dropped inside
    if not undirected:
        return []

    # ── Sanitize step 2: SPLIT collinear overlaps ──────────────────────────────
    # When a node lies ON another edge (e.g. radial's center→outer spoke passing
    # through the inner-ring node), the long edge overlaps the short one — two
    # outgoing half-edges at the SAME angle ⇒ tie ⇒ silent drop. Split the long
    # edge at every interior node. Split ONLY at EXISTING nodes; one pass suffices.
    canon_list = sorted(canon_nodes.values(), key=lambda c: c["id"])
    planar_edges: dict = {}
    for k in sorted(undirected.keys()):
        a, b = undirected[k]
        na = canon_nodes[a]
        nb = canon_nodes[b]
        interior: list[tuple[float, str]] = []
        for c in canon_list:
            if c["id"] == a or c["id"] == b:
                continue
            t = _point_on_segment(c["x"], c["z"], na["x"], na["z"], nb["x"], nb["z"])
            if t is not None:
                interior.append((t, c["id"]))
        if not interior:
            _add_undirected(planar_edges, a, b)
            continue
        interior.sort(key=lambda it: (it[0], it[1]))
        prev = a
        for _t, cid in interior:
            _add_undirected(planar_edges, prev, cid)
            prev = cid
        _add_undirected(planar_edges, prev, b)
    if not planar_edges:
        return []

    # Build directed half-edges + per-vertex outgoing lists.
    outgoing: dict[str, list[_HalfEdge]] = {}

    def _add_half_edge(frm: str, to: str) -> None:
        fn = canon_nodes[frm]
        tn = canon_nodes[to]
        dx = tn["x"] - fn["x"]
        dz = tn["z"] - fn["z"]
        he = _HalfEdge(frm=frm, to=to, dx=dx, dz=dz,
                       length=math.hypot(dx, dz), angle=math.atan2(dz, dx))
        outgoing.setdefault(frm, []).append(he)

    for a, b in planar_edges.values():
        _add_half_edge(a, b)
        _add_half_edge(b, a)

    # Sort each vertex's outgoing half-edges CCW by angle. Residual safety
    # (sanitize step 3): tie-break EQUAL angles by distance (nearer first), then
    # dest id, so any leftover exact tie still hugs the nearer geometry.
    idx_in_list: dict[tuple[str, str], int] = {}
    for _v, lst in outgoing.items():
        lst.sort(key=lambda h: (h.angle, h.length, h.to))
        m = len(lst)
        for i in range(m):
            idx_in_list[(lst[i].frm, lst[i].to)] = i
            # Backstop (sanitize step 4): if two outgoing half-edges STILL point
            # the exact same direction after merge + split, the next-by-angle walk
            # cannot order them and would silently drop a region. Bail the WHOLE
            # graph to [] (caller falls back to the grid). A clean whole-graph []
            # is sanctioned; a silent PARTIAL drop is not.
            if m > 1 and _same_direction(lst[i], lst[(i + 1) % m]):
                return []

    # next(u→v): at v, the most-clockwise turn = the entry immediately CW of the
    # reverse edge v→u (the PREVIOUS entry in v's CCW-sorted outgoing list).
    def _next_of(he: _HalfEdge):
        lst = outgoing.get(he.to)
        if not lst:
            return None
        ti = idx_in_list.get((he.to, he.frm))
        if ti is None:
            return None
        ni = (ti - 1 + len(lst)) % len(lst)
        return lst[ni]

    # Deterministic walk order: all half-edges sorted by (frm, to). Each cycle is
    # started from its globally-smallest half-edge, so the boundary sequence is
    # identical regardless of input order.
    all_half_edges: list[_HalfEdge] = [he for lst in outgoing.values() for he in lst]
    all_half_edges.sort(key=lambda h: (h.frm, h.to))

    visited: set[tuple[str, str]] = set()
    faces: list[Face] = []
    max_steps = len(all_half_edges) + 1  # paranoia bound — next is a permutation

    for start in all_half_edges:
        if (start.frm, start.to) in visited:
            continue
        boundary: list[str] = []
        poly: list[dict] = []
        cur = start
        steps = 0
        while cur is not None:
            ck = (cur.frm, cur.to)
            if ck in visited:
                break  # closed the cycle (back at start)
            visited.add(ck)
            boundary.append(cur.frm)
            fn = canon_nodes[cur.frm]
            poly.append({"x": fn["x"], "z": fn["z"]})
            cur = _next_of(cur)
            steps += 1
            if steps > max_steps:
                break  # never spin (defensive; shouldn't trigger)
        if len(poly) < 3:
            continue  # a degenerate out-and-back encloses nothing
        area = _signed_area(poly)
        # Keep ONLY positive-area (CCW) bounded faces. Outer faces of every
        # connected component come out CW (area <= 0) and are dropped — the
        # sign/winding test, NOT a "largest |area|" test, so disconnected graphs
        # drop each component's outer ring without discarding a real region.
        if area > 0:
            faces.append(Face(boundary=boundary, poly=poly,
                              centroid=_polygon_centroid(poly, area), area=area))
    return faces


# ── EM-295 (W29): per-graph memoization of planar_faces ────────────────────────
# planar_faces is O(edges×nodes) (the collinear-overlap split) and is recomputed
# from scratch up to 3× per agent-turn when GRAPH_ZONES_ENABLED (perception + the
# propose_rule gate + action_propose_rule), on a graph that did not change between
# those calls. Cache the result ON the graph, keyed by a STRUCTURAL SIGNATURE of
# everything planar_faces reads (each valid node's id/x/z + every edge's id/a/b).
#
# Why a content signature and not an "epoch counter" bumped by mutators: the graph
# is mutated in several places — including world.step_master_plan_morph, which
# splices graph.nodes/graph.edges DIRECTLY — so an epoch would have to be bumped at
# every such site or the cache would go stale (a correctness bug). A signature
# self-invalidates on ANY change no matter who made it, and a MATCHING signature
# means byte-identical input ⇒ identical faces (determinism, EM-155). The cache
# lives in the instance __dict__: it is never a declared field, so to_dict never
# serializes it and snapshot/replay/fork recompute fresh, identical results.
def _faces_signature(graph) -> tuple:
    nodes = tuple(sorted(
        (n.id, float(n.x), float(n.z)) for n in graph.nodes if _is_valid_node(n)
    ))
    edges = tuple(sorted(
        (str(getattr(e, "id", "")), str(getattr(e, "a", "")), str(getattr(e, "b", "")))
        for e in graph.edges if e is not None
    ))
    return (nodes, edges)


def planar_faces(graph) -> list[Face]:
    """Bounded planar faces (city blocks) of the road graph — memoized per graph by
    a structural signature (EM-295). Identical results to a fresh computation; the
    cache self-invalidates on any node/edge change. See `_planar_faces_uncached`
    for the algorithm + guarantees (pure, deterministic, never drops a region)."""
    # Cheap guard first (also avoids attaching a cache to a non-graph / stub).
    if (
        graph is None
        or not isinstance(getattr(graph, "nodes", None), list)
        or not isinstance(getattr(graph, "edges", None), list)
        or len(graph.edges) == 0
    ):
        return []
    sig = _faces_signature(graph)
    cached = getattr(graph, "_faces_cache", None)
    if cached is not None and cached[0] == sig:
        return cached[1]
    faces = _planar_faces_uncached(graph)
    try:
        graph._faces_cache = (sig, faces)
    except (AttributeError, TypeError):  # a duck-typed graph that can't hold it
        pass  # correctness is unaffected — just no caching
    return faces


def zone_id_for(boundary_node_ids) -> str:
    """A zone's stable id: sorted boundary node ids joined. IDENTICAL formula to
    the TS side (`[...face.boundary].sort().join('|')`) so backend + frontend
    agree on which block a rule tints (law §0.2)."""
    return "|".join(sorted(boundary_node_ids))


def apply_zone_rule(graph: CityGraph, rule: ZoneRule) -> None:
    """Replace the existing ZoneRule for `rule.zone_id` (one rule per zone, last
    wins) else append. Pure mutation of `graph.zone_rules`."""
    for i, existing in enumerate(graph.zone_rules):
        if existing.zone_id == rule.zone_id:
            graph.zone_rules[i] = rule
            return
    graph.zone_rules.append(rule)

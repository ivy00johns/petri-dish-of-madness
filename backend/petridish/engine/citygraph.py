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
    nodes: list[CityNode] = field(default_factory=list)
    edges: list[CityEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "seed": self.seed,
            "car_policy": self.car_policy,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "CityGraph":
        return cls(
            seed=int(d.get("seed", 1337)),
            version=int(d.get("version", 1)),
            car_policy=str(d.get("car_policy", "cars")),
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

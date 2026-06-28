# EM-239 — Layout-Graph Spine (S1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the frozen 5×5-grid constant in `web/src/components/world3d/cityLayout.ts` with an authoritative, snapshot-serialized backend `CityGraph` (roads first-class; lots/zones/landmarks/streets still derived), seeded by a `classic_grid` template, while the rendered city stays **byte-identical**.

**Architecture:** A new backend module `engine/citygraph.py` owns the `CityGraph` data model + the `classic_grid(seed)` template. `World` builds the graph at init from `city_seed`, serializes it in `to_snapshot()`, and restores-or-derives it in `from_snapshot()`. The graph rides the existing snapshot `state_json` blob (the `snapshots` table) — **no DB schema change**. The frontend gains a `CityGraph` type, and `computeCityPlan` derives the road-tile set (and street-line indices) **from the graph** when present, falling back to today's hardcoded grid when absent. The byte-identical gate is proven by feeding a `classic_grid` graph and asserting the plan equals the no-graph fallback.

**Tech Stack:** Python 3.12 + pytest (backend); TypeScript + React-Three-Fiber + Vitest (frontend).

## Global Constraints

- **Determinism (EM-155):** the rendered `CityPlan` must stay a pure function of its inputs; `classic_grid(seed)` is a pure function of `seed`. No `Math.random`, no `Date`/clock, no module state — the seeded-hash idiom only.
- **Byte-identical gate:** for the shipped town + `seed 1337`, `computeCityPlan` with a `classic_grid` graph must equal `computeCityPlan` with no graph (today's output), field-by-field.
- **Frozen geometry constants (must match across languages):** `TILE = 2.6`, `BLOCK_PITCH = 13.0`, road-line tile indices `(-13, -8, -3, 2, 7, 12)` (the `((i-2) mod 5)==0` set within `[-13, 12]`), tile center `= (i + 0.5) * TILE`. The byte-identical test is what enforces backend↔frontend agreement.
- **Fallback discipline (ModelBoundary):** a snapshot without `city_graph` (old run / old API / pre-migration replay) must still render via the legacy hardcoded path — never a hole, never a crash.
- **Additive snapshot key:** `city_graph` is an additive `to_snapshot()` key (like `city_seed` was in W15). It does not gate or reshape any existing key.
- **Scope:** roads-only first-class. NO agent verbs, NO new topologies, NO new assets, NO governance — those are S2/S3/S5.

---

### Task 1: Backend `CityGraph` model + `classic_grid` template

**Files:**
- Create: `backend/petridish/engine/citygraph.py`
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `CityNode` dataclass: `id: str`, `x: float`, `z: float`, `kind: str` (`"junction"`).
  - `CityEdge` dataclass: `id: str`, `a: str`, `b: str`, `road_class: str` (`"street"`), `car_policy: str` (`"inherit"`).
  - `CityGraph` dataclass: `version: int` (=1), `seed: int`, `car_policy: str` (=`"cars"`), `nodes: list[CityNode]`, `edges: list[CityEdge]`; methods `to_dict() -> dict`, `@classmethod from_dict(d: dict) -> CityGraph`.
  - `classic_grid(seed: int) -> CityGraph` — the 36-node / 60-edge axis-aligned grid.
  - Module constants `TILE = 2.6`, `ROAD_TILE_INDICES = (-13, -8, -3, 2, 7, 12)`, `tile_center(i: int) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_citygraph.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_citygraph.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'petridish.engine.citygraph'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/petridish/engine/citygraph.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_citygraph.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py
git commit -m "feat(EM-239): CityGraph model + classic_grid template"
```

---

### Task 2: Wire `CityGraph` into `World` (init, to_snapshot, from_snapshot)

**Files:**
- Modify: `backend/petridish/engine/world.py` (init ~1294, `to_snapshot` ~7106, `from_snapshot` ~7378)
- Test: `backend/tests/test_citygraph.py` (append)

**Interfaces:**
- Consumes: `classic_grid`, `CityGraph` from Task 1.
- Produces: `World.city_graph: CityGraph` (always set); `to_snapshot()` gains an additive `"city_graph"` key; `from_snapshot()` restores it from `state["city_graph"]` or derives `classic_grid(city_seed)` when absent.

- [ ] **Step 1: Write the failing test (append to test_citygraph.py)**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest backend/tests/test_citygraph.py -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'city_graph'`

- [ ] **Step 3a: Add the import + init build in `world.py`**

Add to the imports near the other `engine` imports at the top of `world.py`:

```python
from .citygraph import CityGraph, classic_grid
```

At the END of `World.__init__` (immediately after the `self.neighborhoods = self._derive_neighborhoods()` line, ~world.py:1294), add:

```python
        # EM-239 (S1) — the authoritative road graph. S1 seeds it from the
        # frozen classic_grid template (pure fn of city_seed); it serializes in
        # to_snapshot() and restores in from_snapshot(). Roads are first-class
        # state here; lots/zones/landmarks/streets keep deriving frontend-side.
        self.city_graph: CityGraph = classic_grid(self.city_seed)
```

- [ ] **Step 3b: Serialize in `to_snapshot`**

In `to_snapshot()`, in the `snap = { ... }` literal, immediately after the `"city_seed": self.city_seed,` line (~world.py:7106), add:

```python
            # EM-239 (S1) — the authoritative road graph (additive key, like
            # city_seed). The frontend renders FROM this when present and falls
            # back to the hardcoded grid when absent (old snapshots).
            "city_graph": self.city_graph.to_dict(),
```

- [ ] **Step 3c: Restore-or-derive in `from_snapshot`**

In `from_snapshot()`, after the `places = [...]` list comprehension that ends ~world.py:7378 (before agents are built), add:

```python
        # EM-239 (S1) — restore the road graph verbatim, or derive classic_grid
        # for pre-S1 snapshots (derive-on-load migration; never a hole).
        cg = state.get("city_graph")
```

Then, after the `World(...)` instance is constructed and returned within `from_snapshot` (locate the `world = cls(...)` / construction near the end of the method), set the graph on it before returning:

```python
        # (immediately before the final `return world`)
        if isinstance(cg, dict) and cg.get("nodes"):
            world.city_graph = CityGraph.from_dict(cg)
        # else: __init__ already built classic_grid(city_seed) — the migration path.
```

> Note: `__init__` already sets `city_graph` to `classic_grid(seed)`, so the
> `else` branch needs no code — absent/empty `city_graph` correctly leaves the
> derived grid in place. If `from_snapshot` constructs the world via a path that
> sets `city_seed` from the snapshot, confirm `city_seed` is read from
> `state["city_seed"]` before the graph default is used; the derive path keys off
> that seed.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest backend/tests/test_citygraph.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Run the existing backend suite to confirm no regression**

Run: `python -m pytest backend/tests/ -q`
Expected: PASS — same count as baseline + the new tests (the additive `city_graph` key must not break snapshot/replay/fork tests; if a golden snapshot test pins the exact key set, update its expectation to include `city_graph`).

- [ ] **Step 6: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_citygraph.py
git commit -m "feat(EM-239): World holds/serializes CityGraph; derive-on-load migration"
```

---

### Task 3: Frontend `CityGraph` types

**Files:**
- Modify: `web/src/types/index.ts` (add types + `WorldState.city_graph`, near `city_seed` at :287 and `neighborhoods` at :298)

**Interfaces:**
- Consumes: nothing.
- Produces: exported `CityGraphNode`, `CityGraphEdge`, `CityGraph` interfaces; `WorldState.city_graph?: CityGraph | null`.

- [ ] **Step 1: Add the types**

In `web/src/types/index.ts`, add near the other world-shape interfaces (e.g. just below the `Neighborhood` interface ~:32):

```typescript
/** EM-239 (S1) — the authoritative road graph (mirrors backend
 *  engine/citygraph.py). S1 ships axis-aligned junctions only. */
export interface CityGraphNode {
  id: string;
  x: number;
  z: number;
  kind: 'junction'; // S3 widens to 'roundabout' | 'plaza' | 'dead_end'
}

export interface CityGraphEdge {
  id: string;
  a: string; // node id
  b: string; // node id
  road_class: 'street';
  car_policy: 'inherit'; // S3 adds 'cars' | 'pedestrian' | 'mixed'
}

export interface CityGraph {
  version: number;
  seed: number;
  car_policy: 'cars'; // S3 adds 'pedestrian' | 'mixed'
  nodes: CityGraphNode[];
  edges: CityGraphEdge[];
}
```

In the `WorldState` interface (~:287, right after `city_seed?: number | null;`), add:

```typescript
  // EM-239 (S1) — the authoritative road graph. When present the 3D city
  // renders FROM it; when absent (pre-S1 snapshots) the renderer falls back
  // to the hardcoded grid. Additive/optional — fallback discipline.
  city_graph?: CityGraph | null;
```

- [ ] **Step 2: Typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: PASS (no errors — types are additive).

- [ ] **Step 3: Commit**

```bash
git add web/src/types/index.ts
git commit -m "feat(EM-239): frontend CityGraph types"
```

---

### Task 4: Graph-derived road-tile predicate + `computeCityPlan` fallback (byte-identical gate)

**Files:**
- Modify: `web/src/components/world3d/cityLayout.ts` (the `CityWorld` interface ~:153; `isRoadTile`/`isRoadIndex` usage in `emitRoads` ~:467 and `computeStreets` ~:429; `computeCityPlan` ~:671)
- Modify: `web/src/components/world3d/CityScape.tsx` (pass `city_graph` through, ~:311 and :324)
- Test: `web/src/components/world3d/cityLayout.test.ts` (append the byte-identical + fallback tests)

**Interfaces:**
- Consumes: `CityGraph` (Task 3); the existing `CityWorld`, `computeCityPlan`, `CityPlan`.
- Produces: `CityWorld.city_graph?: CityGraph | null`; an internal `roadTileSetFrom(graph: CityGraph | null | undefined): Set<string>` and `roadLineIndicesFrom(graph, axis): number[]`; `computeCityPlan` consumes `world.city_graph`.

- [ ] **Step 1: Write the failing test (append to cityLayout.test.ts)**

```typescript
// Build the classic_grid graph exactly as backend engine/citygraph.py emits it.
const ROAD_IDX = [-13, -8, -3, 2, 7, 12];
const tc = (i: number) => (i + 0.5) * TILE; // TILE is already imported in the test
function classicGridGraph(seed = 1337) {
  const nodes = [];
  for (const j of ROAD_IDX) for (const i of ROAD_IDX)
    nodes.push({ id: `n:${i}:${j}`, x: tc(i), z: tc(j), kind: 'junction' as const });
  const edges = [];
  for (const j of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${ROAD_IDX[k]}:${j}`, b = `n:${ROAD_IDX[k + 1]}:${j}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  for (const i of ROAD_IDX) for (let k = 0; k < ROAD_IDX.length - 1; k++) {
    const a = `n:${i}:${ROAD_IDX[k]}`, b = `n:${i}:${ROAD_IDX[k + 1]}`;
    edges.push({ id: `e:${a}->${b}`, a, b, road_class: 'street' as const, car_policy: 'inherit' as const });
  }
  return { version: 1, seed, car_policy: 'cars' as const, nodes, edges };
}

describe('EM-239 byte-identical graph rendering', () => {
  const seed = 1337;
  const places: Place[] = SHIPPED_TOWN_PLACES; // reuse the fixture the file already uses

  it('classic_grid graph yields a plan identical to the no-graph fallback', () => {
    const fallback = computeCityPlan({ places, city_seed: seed });
    const fromGraph = computeCityPlan({ places, city_seed: seed, city_graph: classicGridGraph(seed) });
    expect(fromGraph).toEqual(fallback);
  });

  it('absent city_graph still renders via the legacy path', () => {
    const plan = computeCityPlan({ places, city_seed: seed, city_graph: null });
    expect(plan.pieces.road_straight.length).toBeGreaterThan(0);
    expect(plan.blocks.length).toBe(GRID_BLOCKS * GRID_BLOCKS);
  });
});
```

> If the test file has no `SHIPPED_TOWN_PLACES` fixture, reuse whatever places
> array the existing `expectCityLaws`-style tests build (search the file for the
> `Place[]` it already feeds `computeCityPlan`), or construct a minimal
> `[{ id: 'plaza', name: 'Central Plaza', x: 500, y: 500, kind: 'social' }]`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/components/world3d/cityLayout.test.ts`
Expected: FAIL — `computeCityPlan` ignores `city_graph` (the second assertion's `toEqual` passes trivially, but the type/property `city_graph` is unknown → compile error, or the graph path doesn't exist yet).

- [ ] **Step 3a: Extend `CityWorld` to accept the graph**

In `cityLayout.ts`, add the import at the top:

```typescript
import type { CityGraph } from '../../types';
```

In the `CityWorld` interface (~:153), add:

```typescript
  // EM-239 (S1) — the authoritative road graph. When present, roads + street
  // lines derive from it; when absent, the hardcoded frozen grid is used
  // (fallback discipline). Same byte-identical output for the classic_grid.
  city_graph?: CityGraph | null;
```

- [ ] **Step 3b: Add the graph-derived predicate helpers**

Add near the other grid helpers (after `isRoadTile`, ~:282):

```typescript
/** Build the set of road-tile "i,j" keys from the graph's edges (each edge is
 *  axis-aligned; mark every tile index between its endpoints). For the
 *  classic_grid this reproduces the hardcoded isRoadTile set exactly, so the
 *  plan is byte-identical. S2-ready: partial graphs mark only their segments. */
function roadTileSetFrom(graph: CityGraph | null | undefined): Set<string> {
  const set = new Set<string>();
  if (!graph || !graph.edges?.length) {
    // Fallback: today's hardcoded full grid.
    for (let j = TILE_MIN; j <= TILE_MAX; j++)
      for (let i = TILE_MIN; i <= TILE_MAX; i++)
        if (isRoadTile(i, j)) set.add(`${i},${j}`);
    return set;
  }
  const nodeById = new Map(graph.nodes.map((n) => [n.id, n]));
  const idxOf = (world: number) => Math.round(world / TILE - 0.5);
  for (const e of graph.edges) {
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;
    const ai = idxOf(a.x), aj = idxOf(a.z), bi = idxOf(b.x), bj = idxOf(b.z);
    if (ai === bi) {
      const lo = Math.min(aj, bj), hi = Math.max(aj, bj);
      for (let j = lo; j <= hi; j++) if (inGrid(ai, j)) set.add(`${ai},${j}`);
    } else if (aj === bj) {
      const lo = Math.min(ai, bi), hi = Math.max(ai, bi);
      for (let i = lo; i <= hi; i++) if (inGrid(i, aj)) set.add(`${i},${aj}`);
    }
  }
  return set;
}

/** Road-line tile indices on one axis, derived from the graph (for street
 *  naming). Fallback = the hardcoded isRoadIndex lines. */
function roadLineIndicesFrom(
  graph: CityGraph | null | undefined,
  axis: 'ns' | 'ew',
): number[] {
  if (!graph || !graph.nodes?.length) {
    const out: number[] = [];
    for (let i = TILE_MIN; i <= TILE_MAX; i++) if (isRoadIndex(i)) out.push(i);
    return out;
  }
  const idxOf = (world: number) => Math.round(world / TILE - 0.5);
  const s = new Set<number>();
  // ns lines run along Z at constant x; ew lines run along X at constant z.
  for (const n of graph.nodes) s.add(idxOf(axis === 'ns' ? n.x : n.z));
  return [...s].sort((p, q) => p - q);
}
```

- [ ] **Step 3c: Make `emitRoads` consult the road-tile set**

Change `emitRoads` (~:467) to accept the set and use membership instead of `isRoadTile`:

```typescript
function emitRoads(
  pieces: Record<CityPieceKey, CityInstance[]>,
  roadTiles: Set<string>,
): void {
  const isRoad = (i: number, j: number) => roadTiles.has(`${i},${j}`);
  for (let j = TILE_MIN; j <= TILE_MAX; j++) {
    for (let i = TILE_MIN; i <= TILE_MAX; i++) {
      if (!isRoad(i, j)) continue;
      let mask = 0;
      for (const d of SIDES) {
        if (isRoad(i + d.dx, j + d.dz)) mask |= d.bit;
      }
      if (mask === 0) continue;
      const x = tileCenter(i);
      const z = tileCenter(j);
      if (mask === 15) pieces.road_cross.push({ x, z, rotY: 0 });
      else if (mask in TEE_ROT) pieces.road_tee.push({ x, z, rotY: TEE_ROT[mask] });
      else if (mask in STRAIGHT_ROT) pieces.road_straight.push({ x, z, rotY: STRAIGHT_ROT[mask] });
      else if (mask in CORNER_ROT) pieces.road_corner.push({ x, z, rotY: CORNER_ROT[mask] });
      else pieces.road_end.push({ x, z, rotY: END_ROT[mask] });
    }
  }
}
```

- [ ] **Step 3d: Make `computeStreets` take the graph-derived lines**

Change `computeStreets` (~:429) to derive its per-axis line indices from the graph instead of scanning `isRoadIndex`:

```typescript
export function computeStreets(
  seed: number,
  graph?: CityGraph | null,
): CityStreet[] {
  const used = new Set<number>();
  const out: CityStreet[] = [];
  for (const axis of ['ns', 'ew'] as const) {
    for (const i of roadLineIndicesFrom(graph, axis)) {
      const at = tileCenter(i);
      const main = i !== TILE_MIN && i !== TILE_MAX; // ring road => not main
      const start = Math.floor(h(seed, `street-name-${axis}`, i) * STREET_NAME_BANK_SIZE);
      let k = start % STREET_NAME_BANK_SIZE;
      while (used.has(k)) k = (k + 1) % STREET_NAME_BANK_SIZE;
      used.add(k);
      out.push({
        id: `${axis}:${i}`,
        name: streetNameAt(k),
        axis,
        at,
        main,
        labels: main
          ? STREET_LABEL_CROSS.map((c) =>
              axis === 'ns' ? { x: at, z: c } : { x: c, z: at },
            )
          : [],
      });
    }
  }
  return out;
}
```

> The original loop walked `i` ascending over `isRoadIndex`; `roadLineIndicesFrom`
> returns the same indices in the same ascending order for the classic grid, so
> the seeded dedupe walk and resulting names are byte-identical.

- [ ] **Step 3e: Thread the graph through `computeCityPlan`**

In `computeCityPlan` (~:671), build the road-tile set from the world's graph and pass it down; pass the graph to `computeStreets`:

```typescript
  const roadTiles = roadTileSetFrom(world.city_graph);
  // ...
  emitRoads(pieces, roadTiles);
  // ... (at the return) ...
    streets: computeStreets(seed, world.city_graph),
```

(Replace the existing `emitRoads(pieces);` call and the `streets: computeStreets(seed),` line.)

- [ ] **Step 3f: Pass `city_graph` from `CityScape`**

In `CityScape.tsx` (~:311), include `city_graph` in the destructure and pass it to `computeCityPlan` (~:324):

```typescript
  const { places = [], city_seed: citySeed, neighborhoods, city_graph } = world;
  // ...
      plan: computeCityPlan({ places, city_seed: citySeed, neighborhoods, city_graph }),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/components/world3d/cityLayout.test.ts`
Expected: PASS — including the new `toEqual(fallback)` byte-identical assertion.

- [ ] **Step 5: Run the full frontend world3d suite + typecheck**

Run: `cd web && npx vitest run src/components/world3d && npx tsc --noEmit`
Expected: PASS — every existing `cityLayout`/`CityScape` test still green (the fallback path keeps no-graph snapshots byte-identical).

- [ ] **Step 6: Commit**

```bash
git add web/src/components/world3d/cityLayout.ts web/src/components/world3d/CityScape.tsx web/src/components/world3d/cityLayout.test.ts
git commit -m "feat(EM-239): render city FROM CityGraph with byte-identical fallback"
```

---

### Task 5: End-to-end replay/fork parity + manual verification

**Files:**
- Test: `backend/tests/test_citygraph.py` (append a replay/fork parity test)

**Interfaces:**
- Consumes: everything above.
- Produces: a test proving snapshot→from_snapshot→to_snapshot is graph-stable; a manual checklist.

- [ ] **Step 1: Write the failing test**

```python
def test_snapshot_round_trip_is_graph_stable():
    # to_snapshot -> from_snapshot -> to_snapshot keeps city_graph identical
    # (replay/fork parity: the graph survives restore byte-for-byte).
    from petridish.engine.world import World
    w = _min_world()
    snap1 = w.to_snapshot()
    snap2 = World.from_snapshot(snap1).to_snapshot()
    assert snap2["city_graph"] == snap1["city_graph"]
```

- [ ] **Step 2: Run test to verify it fails (or passes if Task 2 is complete)**

Run: `python -m pytest backend/tests/test_citygraph.py::test_snapshot_round_trip_is_graph_stable -v`
Expected: PASS once Tasks 1–2 are in (this is the regression lock for replay/fork).

- [ ] **Step 3: Manual verification checklist (no code)**

Start the sim and confirm the byte-identical gate holds in the running app:

```
1. Start backend + frontend (per README "5-minute live demo").
2. The live 3D city is visually unchanged from before this branch
   (roads, lots, props, street labels identical).
3. Open an existing replay run — it renders identically (derive-on-load path:
   old snapshots have no city_graph -> classic_grid(seed)).
4. Fork a run -> the forked tick-0 city matches the parent at that tick.
5. Console clean (no errors/warnings from the city renderer).
```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_citygraph.py
git commit -m "test(EM-239): snapshot round-trip graph parity (replay/fork lock)"
```

---

## Self-Review

**1. Spec coverage:**
- CityGraph model + classic_grid → Task 1. ✓
- Backend authoritative state (init/to_snapshot/from_snapshot) → Task 2. ✓
- Persistence: graph rides the snapshot blob → no repo change (stated in Task 2 / Architecture). ✓
- Migration (derive-on-load) → Task 2 Step 3c + test. ✓
- Fallback (graph-less snapshot) → Task 4 (`roadTileSetFrom(null)`, `computeStreets(seed, null)`) + test. ✓
- Frontend types → Task 3. ✓
- Graph-derived road-tile predicate + CityPlan interface unchanged → Task 4. ✓
- Byte-identical golden gate → Task 4 Step 1 (`toEqual(fallback)`). ✓
- Determinism / replay-fork parity → Task 5. ✓
- Lots/zones/landmarks unchanged (derive as today) → untouched code paths; covered by the existing suite re-run (Task 4 Step 5). ✓

**2. Placeholder scan:** No TBD/TODO; every code step shows real code; commands have expected output. The only conditional guidance (fixture name in Task 4, exact `from_snapshot` construction site in Task 2) gives the engineer a concrete fallback. ✓

**3. Type consistency:** `CityGraph`/`CityGraphNode`/`CityGraphEdge` (frontend) mirror `CityGraph`/`CityNode`/`CityEdge` (backend) field-for-field; `classic_grid` node-id format `n:{i}:{j}` and edge-id `e:{a}->{b}` are identical in the backend module (Task 1) and the frontend test fixture (Task 4); `roadTileSetFrom` / `roadLineIndicesFrom` / `emitRoads(pieces, roadTiles)` / `computeStreets(seed, graph)` signatures are consistent between definition (Task 4 Step 3b–3d) and call sites (Step 3e). ✓

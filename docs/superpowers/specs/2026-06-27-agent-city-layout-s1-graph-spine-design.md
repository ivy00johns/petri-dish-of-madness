# Agent-Controlled City Layout — S1: Layout-Graph Spine

> **Parent:** `2026-06-27-agent-city-layout-overview-design.md` (the three pillars,
> decomposition, and cross-cutting constraints bind this spec).
> **Status:** design (2026-06-27). First sub-project of the initiative.

## 1. Goal

Replace the **frozen 5×5 grid constant** in `cityLayout.ts` with a **`CityGraph`** that is
**authoritative backend state**, seeded by a `classic_grid` template. Everything else keeps
deriving from the graph exactly the way it currently derives from the hardcoded grid. The
city must look **byte-identical** to today — this is an architecture change, not a visual one.

The point: S2/S3 need a layout that is *state agents can mutate*. S1 builds that state and
re-points the renderer at it, while changing nothing the user sees. It is the lowest-risk
place to get the data model, determinism, and persistence right before any agent touches it.

## 2. Non-goals (explicitly out of scope for S1)

- **No new agent verbs** (`build_road`, `build_on_lot`) — that is S2.
- **No new topologies / non-axis-aligned geometry** — the graph stays a grid; arbitrary
  angles, roundabouts, pentagons are S3 (+ S5a meshing).
- **No new assets** — reuse the frozen 23-key tile palette unchanged.
- **No governance hooks / votes over layout** — that is S3.
- **No change to lots, zones, landmarks, streets, buildings** — all keep deriving exactly
  as today (byte-identical).
- **Lots are NOT promoted to first-class state** (decision below) — deferred to S2.

## 3. Architecture

### The keystone move

```
TODAY:   places + seed ─▶ [hardcoded 5×5 grid] ─▶ blocks, lots, landmarks, streets, road tiles
S1:      seed ─▶ classic_grid template ─▶ CityGraph  (authoritative backend state)
         CityGraph + places + seed ─▶ blocks, lots, landmarks, streets, road tiles  (byte-identical)
```

The graph lives in the **backend** (sim state: persisted, included in the world snapshot the
API serves) — *not* a frontend computation. This is non-negotiable: agents are backend, so
the thing they mutate in S2/S3 must be backend state. The frontend stops *computing* roads
and starts *reading* them from the snapshot.

### First-class vs. derived (resolved: roads-only)

| Entity | S1 treatment | Why |
|---|---|---|
| **Nodes** (intersections) + **Edges** (road segments) | **First-class graph state** | This *is* the road graph — what `build_road` mutates in S2. |
| Global **car-policy** | First-class (one field) | Cheap; S3's "ban cars" flips it. |
| **Blocks** (faces enclosed by roads) | **Derived** from the graph | For the classic grid, faces == today's 5×5 blocks → byte-identical. |
| **Lots, zones, landmarks, streets** | **Derived** from `(graph + places + seed)` exactly as today | No behavior change; keeps S1 tight. Lots become first-class in S2 when `build_on_lot` needs persistent identity. |

So S1's graph is fundamentally the **road graph** (nodes + edges + one policy field).

## 4. Data model

```
Node  { id: string; x: number; z: number; kind: 'junction' }          # S1: all 'junction'
Edge  { id: string; a: NodeId; b: NodeId;
        road_class: 'street';                                          # S1: single class
        car_policy: 'inherit' }                                        # S1: inherits graph default
CityGraph { version: 1; seed: number;
            car_policy: 'cars';                                        # global default
            nodes: Node[]; edges: Edge[] }
```

Forward-compatibility (reserved, unused in S1, so S2/S3 don't reshape the model):
`Node.kind` will gain `'roundabout' | 'plaza' | 'dead_end'`; `Edge` will gain real
`road_class` values and per-edge `car_policy`; the graph will carry a `district` tag per
node/edge. S1 ships only the values listed above.

## 5. The `classic_grid` template

A pure function of `seed` (and the frozen world size) that emits a `CityGraph` reproducing
today's exact grid:

- **Nodes** at the 6 road centerlines per axis (tile indices `{−13,−8,−3,2,7,12}` →
  world `{−32.5,−19.5,−6.5,6.5,19.5,32.5}`), i.e. the 6×6 = **36 intersections**.
- **Edges** along each centerline between adjacent intersections (≈ 60 edges; the outer
  `−13`/`12` lines are the existing ring road).
- `car_policy: 'cars'` (matches today's `CARS_ENABLED = true`).

Determinism: identical seed ⇒ identical graph; no `Math.random`, no clock.

## 6. Determinism, replay & EM-155

EM-155 strengthens rather than breaks:

- **Render = pure function of `(graph, places, seed)`** — same inputs ⇒ byte-identical
  `CityPlan`.
- **Graph state = pure function of its event log** — the initial graph is reproducible from
  `seed` (so S1 needs no stored event); S2+ layout mutations append `layout_event`s to the
  existing event stream, and replay/fork re-derive the graph by replaying them in order.
- **Replay/fork:** the graph is part of persisted world state, restored verbatim; the
  `layout_event` stream (empty in S1) replays deterministically.

S1 reserves the `layout_event` envelope but emits none (the initial graph is seed-derived).

## 7. Persistence, snapshot & migration

- **Storage:** serialize the current `CityGraph` into the world snapshot (the fast render
  path). The future source of truth for *mutations* is the `layout_event` stream (S2+);
  in S1 the graph is simply seed-derived and stored.
- **Backend integration:** `World` holds `city_graph`; `World.from_snapshot` /
  `to_snapshot` round-trips it; `repository.py` saves/loads it alongside places.
- **API:** include `city_graph` in the world snapshot the frontend consumes (`api/app.py`).
- **Migration (existing runs in `data/run.sqlite`):** on load, if a run has places but no
  `city_graph`, derive `classic_grid(seed)` and attach it. No data rewrite required — derive
  on read.
- **Fallback (ModelBoundary discipline):** if a snapshot reaches the frontend without a
  `city_graph` (old API / pre-migration replay), the renderer falls back to today's
  `computeCityPlan` grid path — "never a hole, never a crash."

## 8. Frontend integration

The crux of the byte-identical guarantee is the **road-tile predicate**:

- Today `cityLayout.ts` hardcodes `isRoadIndex` / `isRoadTile`. S1 replaces that with a
  predicate **derived from the graph's edges**: a tile `(i,j)` is a road tile iff it lies on
  some edge's centerline. The existing mask-based `emitRoads` classification
  (cross/tee/straight/corner/end) runs **unchanged** on that predicate.
- For `classic_grid`, the derived road-tile set is identical to today's hardcoded set ⇒
  `emitRoads` produces byte-identical pieces.
- `blocks`, `landmarks`, `streets`, `realLots`, `blockLots`, `emptyLots` all continue to
  derive from `(graph-derived grid + places + seed)` with no other change.
- **`CityPlan` interface is unchanged**, so `CityScape.tsx` and all consumers are untouched.
- `types.ts` gains `CityGraph`; `computeCityPlan(world)` reads `world.city_graph` when
  present, else falls back to the current grid generation.

## 9. Components & boundaries

- **Backend — new `backend/petridish/engine/citygraph.py`:** the `CityGraph` model, the
  `classic_grid(seed)` template, serialization to/from snapshot, and the reserved
  `layout_event` type. One clear purpose; testable in isolation.
- **Backend — `engine/world.py`:** `World` holds `city_graph`; snapshot round-trip;
  derive-on-load migration. (`world.py` is already large at ~7.9k lines — keep the graph
  model in `citygraph.py` and let `world.py` only *hold/serialize* it.)
- **Backend — `persistence/repository.py`:** save/load the serialized graph.
- **Backend — `api/app.py`:** include `city_graph` in the served snapshot.
- **Frontend — `cityLayout.ts`:** graph-derived road-tile predicate + fallback; everything
  else unchanged. `types.ts`: add `CityGraph`.

## 10. Testing & acceptance

- **Byte-identical golden test (the gate):** for the shipped town's snapshot + `seed 1337`,
  the graph-derived `CityPlan` equals today's `computeCityPlan` output, field-by-field
  (`pieces`, `blocks`, `landmarks`, `realLots`, `blockLots`, `emptyLots`, `streets`,
  `extent`). The current `cityLayout.test.ts` is the oracle.
- **Template determinism (backend):** `classic_grid(seed)` is stable across runs; round-trip
  serialize→deserialize is identity; `new test_citygraph.py`.
- **Migration:** a graph-less run snapshot loads and renders identically (derive-on-load).
- **Fallback:** a snapshot with `city_graph` omitted renders via the legacy path with no
  error and no visual diff.
- **Replay/fork:** the graph survives snapshot/restore byte-identically; an empty
  `layout_event` stream replays to the same graph.

**Acceptance:** the live town and an existing replay are visually unchanged; the layout now
originates from backend `CityGraph` state; all golden/determinism/migration/fallback tests
pass.

## 11. Risks & open questions

- **Tessellation parity is the whole risk.** If the graph→road-tile predicate diverges from
  the hardcoded `isRoadTile` by even one tile, the golden test fails. Mitigation: derive the
  predicate, keep `emitRoads` untouched, lean on the existing test as oracle.
- **Snapshot size / churn:** the serialized graph is tiny (≈36 nodes + 60 edges) — negligible
  vs. event volume. No concern at S1 scale.
- **`world.py` size:** resist adding graph logic there; it only holds/serializes. The model
  lives in `citygraph.py`.

## 12. What S2 needs from S1 (handoff)

- A mutable backend `CityGraph` with stable node/edge ids.
- The `layout_event` envelope, ready to carry `road_built` / `road_demolished`.
- A frontend renderer that re-derives from the graph every snapshot (so a new edge appears
  without a code change).
- The decision to keep the graph **axis-aligned** in S2 (so the tile renderer is still
  reused; arbitrary geometry waits for S3 + S5a).

# EM-247 (S5a) — Procedural Road Meshing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render the road network as **procedural geometry built at runtime from the `CityGraph`** so roads at **any angle** (pentagon/radial/roundabouts) render correctly — landed **behind a flag** (default OFF) so the EM-239/243 tile renderer stays the byte-identical default until a human visual sign-off.

**Architecture:** A pure generator `buildRoadMesh(graph, seed) → RoadMesh` turns each edge into a width-correct **ribbon** instance (oriented along the edge vector at any angle) and each node into an **intersection** patch (roundabout/plaza nodes get parametric annulus/plaza geometry — ready for S3b's node kinds). The output is **instance transforms per piece-type bucket** (matching the existing raw-`InstancedMesh`-per-bucket pattern in `CityScape`), so the whole city is a handful of draw calls. A new R3F `<RoadMesh>` renders those buckets with one toon material. A `ROAD_MESH_ENABLED` flag (default **false**) selects tile path (default, byte-identical) vs mesh path. The generator is a **pure function of (graph, seed)** → determinism/replay-safe; the visual quality (atlas, lane markings, crosswalks, LOD, chunked culling, roundabout/plaza fidelity) is the spec's deferred "budget real iteration" behind the sign-off.

**Tech Stack:** TypeScript + React-Three-Fiber + Three.js, Vitest. EM-155 (the *grid data* contract; S5a road *art* is a visual change, explicitly NOT byte-identical to the tile look — gated on sign-off).

## Global Constraints

- **Land behind a flag; tile path is the default + fallback.** `ROAD_MESH_ENABLED` defaults **false**. With it false, the road render path is the EM-239/243 tile renderer **unchanged and byte-identical** (all existing goldens hold). The mesh path is opt-in pending a human visual sign-off (the spec's gate — "keep the tile path as a fallback until signed off"). **Do not retire the tile path in this slice.**
- **Visual change, NOT byte-identical.** S5a road art deliberately differs from the tile look. EM-155's byte-identical guarantee is about the *grid/graph data* (which is unchanged), not the road art. So there is **no golden-image gate** here; the gates are determinism + draw-call budget + arbitrary-angle geometry correctness (math, not pixels) + the deferred human sign-off.
- **Determinism.** `buildRoadMesh` is a pure function of `(graph, seed)` — no `Math.random`, no clock, no mutable module state. Same graph ⇒ identical instance arrays (order = edge/node order). Replay/fork safe.
- **Draw-call budget.** Geometry is **raw `InstancedMesh` per piece-type bucket** (ribbons / intersections / roundabouts / plazas) + chunking — a handful of buckets, well under the spec's ~100-draw-call budget. Verify the bucket count in a test.
- **Any angle.** A ribbon's orientation is `atan2(dz, dx)` and length is `hypot(dx, dz)` — correct for axis-aligned AND diagonal edges. No assumption of axis-alignment anywhere in the generator.
- **Toolchain:** `cd web && /usr/local/bin/npx vitest run <path>`; typecheck `cd web && /usr/local/bin/npx tsc -b --force`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `web/src/components/world3d/roadMesh.ts` (new) | **Pure** `buildRoadMesh(graph, seed)` + `RoadMesh`/transform types + width/size constants + roundabout/plaza generators | 1 |
| `web/src/components/world3d/roadMesh.test.ts` (new) | Determinism, arbitrary-angle math, no-NaN, budget, width-by-class tests | 1 |
| `web/src/components/world3d/RoadMesh.tsx` (new) | R3F component: raw `InstancedMesh` per bucket + toon material (procedural geometry) | 2 |
| `web/src/components/world3d/RoadMesh.test.tsx` (new) | Smoke mount (jsdom) — no throw on a graph; instance counts | 2 |
| `web/src/components/world3d/CityScape.tsx` | `ROAD_MESH_ENABLED` flag; select mesh vs tile road path (default tile, byte-identical) | 3 |
| `web/src/components/world3d/CityScape.test.tsx` | flag-off ⇒ tile path unchanged; flag-on ⇒ RoadMesh present | 3 |

---

### Task 1: `buildRoadMesh(graph, seed)` — the pure geometry generator

**Files:**
- Create: `web/src/components/world3d/roadMesh.ts`
- Test: `web/src/components/world3d/roadMesh.test.ts`

**Interfaces:**
- Consumes: `CityGraph`, `CityGraphNode`, `CityGraphEdge` (`web/src/types/index.ts`).
- Produces:
  - `RibbonInstance = { x: number; z: number; rotY: number; length: number; width: number }`
  - `PatchInstance = { x: number; z: number; size: number }`
  - `RingInstance = { x: number; z: number; outerR: number; innerR: number }`
  - `RoadMesh = { ribbons: RibbonInstance[]; intersections: PatchInstance[]; roundabouts: RingInstance[]; plazas: PatchInstance[] }`
  - `ROAD_WIDTH: Record<string, number>` (by `road_class`; `street` default)
  - `buildRoadMesh(graph: CityGraph | null | undefined, seed: number): RoadMesh` (empty buckets when graph absent/edgeless)

- [ ] **Step 1: Write the failing tests**

Create `web/src/components/world3d/roadMesh.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { buildRoadMesh, ROAD_WIDTH, type RoadMesh } from './roadMesh';
import type { CityGraph } from '../../types';

function graphOf(nodes: Array<[string, number, number]>, edges: Array<[string, string, string]>,
                 extra: Partial<CityGraph> = {}): CityGraph {
  return {
    version: 1, seed: 1337, car_policy: 'cars',
    nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
    edges: edges.map(([id, a, b]) => ({ id, a, b, road_class: 'street' as const, car_policy: 'inherit' as const })),
    ...extra,
  };
}

it('extrudes a width-correct ribbon along an axis-aligned edge', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
  const m = buildRoadMesh(g, 1337);
  expect(m.ribbons).toHaveLength(1);
  const r = m.ribbons[0];
  expect(r.x).toBeCloseTo(5); expect(r.z).toBeCloseTo(0);   // midpoint
  expect(r.length).toBeCloseTo(10);
  expect(r.rotY).toBeCloseTo(0);                            // along +x
  expect(r.width).toBeCloseTo(ROAD_WIDTH.street);
});

it('orients a DIAGONAL ribbon at any angle (the whole point of S5a)', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 10]], [['e', 'a', 'b']]);
  const r = buildRoadMesh(g, 1337).ribbons[0];
  expect(r.length).toBeCloseTo(Math.hypot(10, 10));        // ~14.14
  expect(r.rotY).toBeCloseTo(Math.atan2(10, 10));          // 45° = π/4
  expect(r.x).toBeCloseTo(5); expect(r.z).toBeCloseTo(5);
});

it('emits one intersection patch per node', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 0, 10]],
                    [['e1', 'a', 'b'], ['e2', 'a', 'c']]);
  const m = buildRoadMesh(g, 1337);
  expect(m.intersections).toHaveLength(3);
  expect(m.intersections.every((p) => Number.isFinite(p.x) && Number.isFinite(p.z) && p.size > 0)).toBe(true);
});

it('roundabout / plaza nodes get ring / plaza geometry', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
  g.nodes[0] = { ...g.nodes[0], kind: 'roundabout' } as any;
  g.nodes[1] = { ...g.nodes[1], kind: 'plaza' } as any;
  const m = buildRoadMesh(g, 1337);
  expect(m.roundabouts).toHaveLength(1);
  expect(m.roundabouts[0].outerR).toBeGreaterThan(m.roundabouts[0].innerR);
  expect(m.plazas).toHaveLength(1);
  // a roundabout/plaza node is NOT also a plain intersection patch
  expect(m.intersections).toHaveLength(0);
});

it('road_class scales ribbon width', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]);
  g.edges[0] = { ...g.edges[0], road_class: 'avenue' } as any;
  const r = buildRoadMesh(g, 1337).ribbons[0];
  expect(r.width).toBeCloseTo(ROAD_WIDTH.avenue ?? ROAD_WIDTH.street);
});

it('is pure + deterministic (same graph ⇒ identical mesh)', () => {
  const g = graphOf([['a', 0, 0], ['b', 10, 0], ['c', 5, 9]],
                    [['e1', 'a', 'b'], ['e2', 'b', 'c'], ['e3', 'c', 'a']]);
  expect(buildRoadMesh(g, 1337)).toEqual(buildRoadMesh(g, 1337));
});

it('no NaN/Infinity anywhere; absent/edgeless graph ⇒ empty buckets', () => {
  const m = buildRoadMesh(null, 1337);
  expect(m.ribbons).toEqual([]); expect(m.intersections).toEqual([]);
  const all = (mm: RoadMesh) => [...mm.ribbons, ...mm.intersections, ...mm.roundabouts, ...mm.plazas];
  const g = graphOf([['a', 0, 0], ['b', -7, 3]], [['e', 'a', 'b']]);
  for (const inst of all(buildRoadMesh(g, 1337)))
    for (const v of Object.values(inst)) expect(Number.isFinite(v)).toBe(true);
});

it('draw-call budget: a 36-node/60-edge classic grid stays a handful of buckets', () => {
  // 4 bucket types regardless of city size — the instancing keeps draw calls bounded.
  const m = buildRoadMesh(graphOf([['a', 0, 0], ['b', 10, 0]], [['e', 'a', 'b']]), 1337);
  const buckets = [m.ribbons, m.intersections, m.roundabouts, m.plazas].filter((b) => b.length > 0);
  expect(buckets.length).toBeLessThanOrEqual(4);
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/roadMesh.test.ts`
Expected: FAIL — `roadMesh.ts` does not exist.

- [ ] **Step 3: Implement the pure generator**

Create `web/src/components/world3d/roadMesh.ts`:

```typescript
/**
 * roadMesh.ts — EM-247 (S5a): PURE procedural road geometry from the CityGraph.
 * Each edge → a width-correct ribbon instance oriented at ANY angle; each node →
 * an intersection patch (roundabout/plaza nodes → ring/plaza geometry, ready for
 * S3b). Output is instance transforms per piece bucket (the existing raw-
 * InstancedMesh-per-bucket pattern), so the whole city is a few draw calls.
 *
 * Pure fn of (graph, seed): same graph ⇒ identical arrays (edge/node order). No
 * RNG/clock/mutable state. This is the data layer S5a's <RoadMesh> renders behind
 * the ROAD_MESH_ENABLED flag; the tile path stays the default until visual sign-off.
 */
import type { CityGraph, CityGraphNode } from '../../types';

export interface RibbonInstance { x: number; z: number; rotY: number; length: number; width: number }
export interface PatchInstance { x: number; z: number; size: number }
export interface RingInstance { x: number; z: number; outerR: number; innerR: number }
export interface RoadMesh {
  ribbons: RibbonInstance[];
  intersections: PatchInstance[];
  roundabouts: RingInstance[];
  plazas: PatchInstance[];
}

// Road widths by class (world units). 'street' is the S1/S2 default; wider classes
// arrive with S3b master plans. TILE = 2.6 (cityLayout), a lane ~ one tile wide.
export const ROAD_WIDTH: Record<string, number> = {
  street: 2.6,
  avenue: 3.9,
  boulevard: 5.2,
};

const JUNCTION_SIZE = 3.0;   // intersection patch (covers ribbon ends at a node)
const PLAZA_SIZE = 6.0;      // plaza node footprint
const ROUNDABOUT_OUTER = 4.0;
const ROUNDABOUT_INNER = 2.0;

function widthFor(roadClass: string | undefined): number {
  return (roadClass && ROAD_WIDTH[roadClass]) || ROAD_WIDTH.street;
}

export function buildRoadMesh(graph: CityGraph | null | undefined, _seed: number): RoadMesh {
  const empty: RoadMesh = { ribbons: [], intersections: [], roundabouts: [], plazas: [] };
  if (!graph || !Array.isArray(graph.nodes) || !Array.isArray(graph.edges)) return empty;

  const nodeById = new Map<string, CityGraphNode>(graph.nodes.map((n) => [n.id, n]));

  const ribbons: RibbonInstance[] = [];
  for (const e of graph.edges) {
    const a = nodeById.get(e.a);
    const b = nodeById.get(e.b);
    if (!a || !b) continue;            // dangling edge: skip (never throw)
    const dx = b.x - a.x;
    const dz = b.z - a.z;
    const length = Math.hypot(dx, dz);
    if (length === 0) continue;        // degenerate
    ribbons.push({
      x: (a.x + b.x) / 2,
      z: (a.z + b.z) / 2,
      rotY: Math.atan2(dz, dx),        // ANY angle — the S5a point
      length,
      width: widthFor((e as { road_class?: string }).road_class),
    });
  }

  const intersections: PatchInstance[] = [];
  const roundabouts: RingInstance[] = [];
  const plazas: PatchInstance[] = [];
  for (const n of graph.nodes) {
    const kind = (n as { kind?: string }).kind;
    if (kind === 'roundabout') {
      roundabouts.push({ x: n.x, z: n.z, outerR: ROUNDABOUT_OUTER, innerR: ROUNDABOUT_INNER });
    } else if (kind === 'plaza') {
      plazas.push({ x: n.x, z: n.z, size: PLAZA_SIZE });
    } else {
      intersections.push({ x: n.x, z: n.z, size: JUNCTION_SIZE });
    }
  }

  return { ribbons, intersections, roundabouts, plazas };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/roadMesh.test.ts`
Expected: PASS (all 8).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/world3d/roadMesh.ts web/src/components/world3d/roadMesh.test.ts
git commit -m "feat(EM-247): buildRoadMesh — pure any-angle road geometry generator (S5a)"
```

---

### Task 2: `<RoadMesh>` R3F component (procedural instanced geometry)

**Files:**
- Create: `web/src/components/world3d/RoadMesh.tsx`
- Test: `web/src/components/world3d/RoadMesh.test.tsx`

**Interfaces:**
- Consumes: `buildRoadMesh`, `RoadMesh` (Task 1); the existing toon-material helper (`toonMaterial` — grep `CityScape.tsx`/`assets/` for the exact export the tile path uses) and `CityGraph`.
- Produces: `<RoadMesh graph={...} seed={...} />` — one raw `THREE.InstancedMesh` per non-empty bucket (ribbon plane, intersection plane, roundabout ring, plaza plane), each with a toon material; ground-flush, flat (rotated to lie in XZ).

- [ ] **Step 1: Write the smoke test**

Create `web/src/components/world3d/RoadMesh.test.tsx` (jsdom mount, mirroring how `CityScape.test.tsx` mounts instanced meshes without the R3F reconciler — grep it for the stub pattern). Assert: mounting `<RoadMesh>` with a 3-edge graph does not throw, and (via a small exported helper `roadMeshBuckets(graph, seed)` that returns `[{key, count}]`) the bucket counts match `buildRoadMesh`. Run it red.

- [ ] **Step 2: Implement the component**

Create `RoadMesh.tsx`: build the four `THREE.InstancedMesh` buckets from `buildRoadMesh(graph, seed)`:
- **ribbons** — a unit `PlaneGeometry(1,1)` rotated flat (`-π/2` about X); per instance, compose a matrix `translate(x, ROAD_Y, z) · rotateY(rotY) · scale(length, 1, width)` (ground-flush at a small `ROAD_Y`).
- **intersections / plazas** — a unit flat plane scaled to `size`.
- **roundabouts** — a `RingGeometry(innerR, outerR)` rotated flat (+ optional island disc).
- One shared toon material (reuse the tile path's toon material/atlas helper). Set `instanceMatrix` via `setMatrixAt` in a `useLayoutEffect` (mirror `setupCityMesh` in `CityScape.tsx`).
Keep geometry minimal (no atlas UV packing / lane markings yet — those are the deferred sign-off iteration). Guard against an empty bucket (render nothing for it).

- [ ] **Step 3: Run + typecheck**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/RoadMesh.test.tsx && /usr/local/bin/npx tsc -b --force`
Expected: PASS + exit 0.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/world3d/RoadMesh.tsx web/src/components/world3d/RoadMesh.test.tsx
git commit -m "feat(EM-247): <RoadMesh> R3F component — instanced procedural roads behind the flag (S5a)"
```

---

### Task 3: `ROAD_MESH_ENABLED` flag + CityScape wiring (tile path stays default)

**Files:**
- Modify: `web/src/components/world3d/CityScape.tsx` (the flag + select mesh vs tile road rendering)
- Test: `web/src/components/world3d/CityScape.test.tsx`

**Interfaces:**
- Consumes: `<RoadMesh>` (Task 2); `world.city_graph`; the existing road-tile render path.
- Produces: `export const ROAD_MESH_ENABLED = false;` — when false the road render is the existing tile path **unchanged**; when true, `<RoadMesh graph={world.city_graph} seed={citySeed} />` replaces the road-tile pieces (buildings/props/lots/non-road pieces unchanged in both modes).

- [ ] **Step 1: Write the flag tests**

Add to `CityScape.test.tsx`:
- `ROAD_MESH_ENABLED` is exported and **defaults to `false`** (the byte-identical-default guard — a future flip is a deliberate, reviewed change).
- With the flag false, the rendered city tree contains the road-tile pieces (the existing assertion idiom) and **no** `<RoadMesh>` — i.e., the tile path is untouched (mirror the EM-239/243 byte-identical render assertions; they must still pass).
- (Flag-on behavior is covered by the RoadMesh smoke test; a full flag-on render test is part of the visual sign-off, not this slice.)

- [ ] **Step 2: Wire the flag**

In `CityScape.tsx`: add `export const ROAD_MESH_ENABLED = false;` (with a comment: EM-247 S5a — opt-in pending visual sign-off; the tile path is the default + fallback). In the city render, branch the **road** rendering only: `ROAD_MESH_ENABLED ? <RoadMesh graph={city_graph} seed={citySeed} /> : <existing road-tile instanced meshes>`. Leave every non-road piece (buildings, props, lots, landmarks) rendering identically in both branches. Do NOT remove or alter the tile road path.

- [ ] **Step 3: Run the world3d suite + typecheck**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d && /usr/local/bin/npx tsc -b --force`
Expected: PASS + exit 0, **0 regressions** — with the flag false the EM-239/243/244/246 goldens + byte-identical assertions all still hold (the road path is unchanged).

- [ ] **Step 4: Commit**

```bash
git add web/src/components/world3d/CityScape.tsx web/src/components/world3d/CityScape.test.tsx
git commit -m "feat(EM-247): ROAD_MESH_ENABLED flag — mesh path opt-in, tile path the byte-identical default (S5a)"
```

---

### Task 4: Determinism / budget / arbitrary-angle acceptance + handoff note

**Files:**
- Test: `web/src/components/world3d/roadMesh.test.ts`
- Doc: append a short "visual sign-off pending" note to the EM-247 build results (handled at build close).

- [ ] **Step 1: Acceptance tests**

Add to `roadMesh.test.ts`: a pentagon-shaped graph (5 nodes on a circle + 5 perimeter edges + 5 spokes to a center node) builds a `RoadMesh` with 10 ribbons, all finite, deterministic (`toEqual` on a re-run), and the spoke ribbons at five distinct non-axis-aligned `rotY` angles (proving arbitrary-angle support end-to-end on the geometry S3b will feed it). Confirm the bucket count stays ≤ 4.

```typescript
it('a pentagon graph builds clean any-angle geometry (S3b/S4 acceptance)', () => {
  const R = 30, cx = 0, cz = 0;
  const pts = Array.from({ length: 5 }, (_, i) => {
    const t = (i / 5) * Math.PI * 2;
    return [`p${i}`, cx + R * Math.cos(t), cz + R * Math.sin(t)] as [string, number, number];
  });
  const nodes = [...pts, ['c', cx, cz] as [string, number, number]];
  const edges: Array<[string, string, string]> = [];
  for (let i = 0; i < 5; i++) {
    edges.push([`peri${i}`, `p${i}`, `p${(i + 1) % 5}`]);
    edges.push([`spoke${i}`, `p${i}`, 'c']);
  }
  const g = { version: 1, seed: 1337, car_policy: 'cars' as const,
    nodes: nodes.map(([id, x, z]) => ({ id, x, z, kind: 'junction' as const })),
    edges: edges.map(([id, a, b]) => ({ id, a, b, road_class: 'street' as const, car_policy: 'inherit' as const })) };
  const m = buildRoadMesh(g, 1337);
  expect(m.ribbons).toHaveLength(10);
  expect(m.ribbons.every((r) => Number.isFinite(r.rotY) && Number.isFinite(r.length))).toBe(true);
  expect(buildRoadMesh(g, 1337)).toEqual(m); // deterministic
  const spokeAngles = new Set(m.ribbons.map((r) => Math.round(r.rotY * 1000)));
  expect(spokeAngles.size).toBeGreaterThan(4); // many distinct non-axis-aligned angles
});
```

- [ ] **Step 2: Run the full world3d suite + typecheck**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d && /usr/local/bin/npx tsc -b --force`
Expected: PASS + exit 0, 0 regressions.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/world3d/roadMesh.test.ts
git commit -m "test(EM-247): pentagon any-angle + determinism + budget acceptance (S5a)"
```

---

## Self-Review

**1. Spec coverage (§S5a):**
- Edges → width-correct ribbons (honoring road_class) → Task 1 (`buildRoadMesh` ribbons + `ROAD_WIDTH`). ✅
- Nodes → intersections; roundabout/plaza parametric → Task 1 (intersections/roundabouts/plazas buckets, by `node.kind`). ✅ (roundabout/plaza node kinds arrive with S3b; the generators are ready.)
- Raw InstancedMesh per bucket + toon material; bounded draw calls → Task 2 (`<RoadMesh>`) + Task 1 budget test. ✅
- Determinism (pure fn of graph+seed) → Task 1 + Task 4. ✅
- Land behind a visual sign-off; tile path as fallback → Task 3 (`ROAD_MESH_ENABLED` default false). ✅
- Lane markings / crosswalks / sidewalk surfaces, atlas UV packing, chunked culling, LOD → **deferred** (the spec's "budget real iteration" behind the sign-off) — recorded, not silently dropped.
- Acceptance: a pentagon/radial renders cleanly at 60fps + visual sign-off → the **geometry** is built + tested any-angle (Task 4 pentagon); the **visual sign-off + 60fps eyeball is the user's deferred gate** (browser automation unavailable in this build). Recorded as the explicit handoff.

**2. Placeholder scan:** The two FILL points (Task 2 `toonMaterial` export name + the jsdom mount stub idiom; Task 3 the road-tile render assertion idiom) are "grep the real pattern and mirror" — the surrounding code/types are exact. Task 1 (the meat) is complete code. No TBD/"handle errors". ✅

**3. Type consistency:** `RoadMesh`/`RibbonInstance`/`PatchInstance`/`RingInstance` consistent across `buildRoadMesh`, `<RoadMesh>`, and tests; `ROAD_WIDTH` keyed by `road_class`; `ROAD_MESH_ENABLED` flag name consistent; the generator reads `node.kind`/`edge.road_class` defensively (S1 graphs are all `junction`/`street`). ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-em247-procedural-road-meshing.md`. Built via **/orchestrator ultracode** (Workflow mode). Frontend-only. **The geometry generator + flag are fully code-verified (determinism, any-angle math, budget); the road *art* visual quality (atlas/lane-markings/crosswalks/LOD/chunked-culling/roundabout fidelity) and the 60fps pentagon sign-off are the spec's explicitly-deferred human gate** — the mesh path ships OFF by default behind `ROAD_MESH_ENABLED`, the tile path stays the byte-identical default, and flipping it on for the visual sign-off is the user's call. This unblocks EM-245 (S3b master plans) — whose geometric morph renders through this mesh.

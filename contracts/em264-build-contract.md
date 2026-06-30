# EM-264 (SA) — Graph-Derived Buildable Zones · Build Contract

> **Spec:** `docs/superpowers/specs/2026-06-29-agent-building-layout-sA-graph-zones-design.md`
> **Parent:** `…-agent-building-layout-overview-design.md`
> **Slice:** SA (keystone of the building-layout initiative). Frontend-only.
> **Flag:** `GRAPH_LOTS_ENABLED`, default **OFF** → byte-identical to today (EM-155).
> **Branch:** `build/em264-graph-zones`. Version: 1.0.0 — see `CHANGELOG`/ledger, not inline.

## 0. The law (non-negotiable acceptance bar)

1. **Off-path byte-identical (EM-155).** With `GRAPH_LOTS_ENABLED = false` (and
   for any `computeCityPlan(world)` call with no `opts`), output is **byte-for-byte
   identical** to today. The existing `cityLayout.test.ts` golden suite passes
   **unchanged**. This is the hard gate.
2. **Never throws, never silently drops a region (pillar 2).** `planarFaces` on a
   corrupt / stub / disconnected / degenerate graph returns loose data or `[]` —
   it never throws and never discards an enclosed region. A discarded enclosed
   face is the **forbidden** failure.
3. **Deterministic (EM-155).** Pure function of `(graph, seed)`. No `Math.random`,
   no clock, no unsorted `Map`/`Set` iteration leaking into output. Node/edge
   **input order must not affect output** — stabilize by sorting on id before the
   walk.
4. **No special-casing the core (pillar 4).** The pentagon inner face is just
   another zone. Choking it is a finding, not a bug.

## 1. File ownership (strict — no shared-file edits across lanes)

| Lane | Owns (create/modify) | May read |
|---|---|---|
| **A — algorithm** | `web/src/components/world3d/cityFaces.ts` (CREATE), `web/src/components/world3d/cityFaces.test.ts` (CREATE) | everything |
| **B — wiring** | `web/src/components/world3d/cityLayout.ts` (MODIFY), `web/src/components/world3d/CityScape.tsx` (MODIFY), `web/src/components/world3d/cityLayout.test.ts` (MODIFY — *append* on-path tests; never weaken existing goldens) | `cityFaces.ts` |
| **QE** | `coordination/em264-qa-report.json` (CREATE) | everything; runs tests; **edits no source/test** |

`cityFaces.ts` MUST NOT runtime-import `cityLayout.ts` (circular-import hazard —
`cityLayout` imports `cityFaces`). Use **`import type`** only for `CityInstance` /
`CityZone`, and receive the zone-hint derivation as an **injected callback**.

## 2. Lane A — `cityFaces.ts` (the planar-face keystone)

```ts
import type { CityGraph } from '../../types';
import type { CityInstance, CityZone } from './cityLayout';
import { hashUnit } from './worldSpace';

/** SB will own the real rule vocabulary; SA defines a minimal forward stub and
 *  never populates it (every BuildZone.rules is []). */
export interface ZoneRule {
  zoneId: string;
  hint: CityZone;
  densityCap: number | null;
}

export interface CityFace {
  /** Boundary node ids in walk order (loose; may be slightly degenerate). */
  boundary: string[];
  /** Polygon vertices in world space, same order as `boundary`. */
  poly: { x: number; z: number }[];
  centroid: { x: number; z: number };
  /** Signed area; the unbounded outer face is dropped by sign + max |area|. */
  area: number;
}

/** Trace the bounded planar faces (city blocks) of the road graph.
 *  Pure + deterministic (sort nodes/edges by id first). Defensive: stubs,
 *  disconnected components, and degenerate faces are tolerated; a graph with
 *  no real nodes/edges returns []. NEVER throws; NEVER drops an enclosed
 *  region. */
export function planarFaces(graph: CityGraph | null | undefined): CityFace[];

export interface BuildZone {
  /** Stable id: sorted boundary node ids joined (rotation/direction-independent). */
  id: string;
  face: CityFace;
  /** Suggested lot pads — a hint, NOT an assignment (overflow/gaps allowed). */
  suggestedLots: CityInstance[];
  /** Derived default zone (from the injected callback at the centroid). */
  zoneHint: CityZone;
  /** SB hook — always [] in SA. */
  rules: ZoneRule[];
}

/** Turn faces into buildable zones. `zoneForCentroid` is injected by the caller
 *  (computeCityPlan owns places + zoneForPlace) to avoid a cityLayout import
 *  cycle. suggestedLots are seeded via hashUnit (the EM-155 idiom), inset from
 *  the face boundary, clipped loosely to the interior. */
export function buildZonesFromFaces(
  faces: CityFace[],
  seed: number,
  zoneForCentroid: (x: number, z: number) => CityZone,
): BuildZone[];
```

**Algorithm (half-edge / next-edge-by-angle):** for each directed half-edge, the
next half-edge around a face is the most-clockwise turn at its destination node;
faces are the closed cycles. Drop the single unbounded outer face (largest |area|
or opposite winding). Mirror the type-guards in `roadTileSetFrom`
(`!graph || !Array.isArray(nodes) || !Array.isArray(edges) || !edges.length` → `[]`).
Node coordinates are `node.x`, `node.z` (NOT y). Edge endpoints are `edge.a`,
`edge.b` (node ids).

**`cityFaces.test.ts` matrix (pin the failure modes, not pixel accuracy):**
- classic 5×5 grid graph → **25** enclosed faces (one per block), no outer face.
- pentagon master-plan graph → **5 outer faces + 1 core face**, all returned.
- **dangling stub** (degree-1 node) → no spurious face, no crash.
- **disconnected components** → every component that encloses area yields its
  zone(s); no region silently dropped.
- **concave / near-collinear face** → returned as a loose polygon (NOT discarded);
  `buildZonesFromFaces` clips lots into it without crashing.
- empty / corrupt / no-edge graph → `[]`.
- **determinism:** shuffled node/edge input order ⇒ identical `planarFaces` output
  (deep-equal) and identical `buildZonesFromFaces` output.

## 3. Lane B — wiring (`cityLayout.ts` + `CityScape.tsx`)

```ts
// cityLayout.ts — NEW export, mirrors roadTileSetFrom's guard:
export function hasRealGraph(graph: CityGraph | null | undefined): boolean;
//   true  ⇔ graph && Array.isArray(graph.nodes) && Array.isArray(graph.edges) && graph.edges.length > 0

// cityLayout.ts — computeCityPlan gains an optional opts param (default OFF):
export function computeCityPlan(
  world: CityWorld,
  opts?: { graphLots?: boolean },
): CityPlan;

// CityPlan gains ONE additive optional field (present only on the graph-lots path):
//   zones?: BuildZone[];
```

**The branch (the ONLY behavioral change):**

```ts
if ((opts?.graphLots ?? false) && hasRealGraph(world.city_graph)) {
  const faces = planarFaces(world.city_graph);
  const zoneFor = (x: number, z: number): CityZone => {
    const p = nearestPlace(x, z);            // existing closure
    return p ? zoneForPlace(p) : 'residential';
  };
  const zones = buildZonesFromFaces(faces, seed, zoneFor);
  // Replace ONLY the block/lot derivation with zone-derived lots:
  //   blockLots = zones.map(z => ({ cx: z.face.centroid.x, cz: z.face.centroid.z, lots: z.suggestedLots }))
  //   emptyLots = blockLots.flatMap(b => b.lots)
  //   blocks    = zones.map(z => ({ cx: z.face.centroid.x, cz: z.face.centroid.z, zone: z.zoneHint }))
  //   plan.zones = zones
  // Everything else is UNCHANGED and shared with the grid path:
  //   roads (roadTileSetFrom), landmarks (computeLandmarks), realLots,
  //   streets (computeStreets), pedestrianTiles, extent.
  // assignBuildingLots is REUSED AS-IS — its round-robin + slotLayout ring
  // fallback already tolerates fewer/uneven lots and overflow.
} else {
  // today's fixed-grid Pass 1 / Pass 2 — byte-identical, untouched.
}
```

**`CityScape.tsx`:**
- `export const GRAPH_LOTS_ENABLED = false;` — module const, mirrors
  `ROAD_MESH_ENABLED` (line 547). Default **off**.
- In `useCityPlan`, thread it: `computeCityPlan({ … }, { graphLots: GRAPH_LOTS_ENABLED })`.
- **No new render component in SA.** Zone lots flow through the existing
  `blockLots`/`emptyLots`/`blocks` render path. `citySignature` already folds
  node/edge counts + car_policy, so zones (a pure function of edges) re-derive on
  graph mutation — but **add an explicit reactivity test**.

**`cityLayout.test.ts` (append, never weaken):**
- on-path determinism golden: same graph + seed + `{graphLots:true}` ⇒
  `JSON.stringify`-identical; shuffled node/edge order ⇒ identical.
- on-path pentagon: `{graphLots:true}` with a pentagon graph ⇒ `plan.zones.length === 6`
  and `plan.blockLots` non-empty inside the faces.
- off-path proof: `computeCityPlan(world)` and `computeCityPlan(world,{graphLots:false})`
  are `JSON.stringify`-equal to the no-graph baseline for the classic_grid.
- reactivity: a graph mutation changes `citySignature`; a no-op poll does not.

## 4. Toolchain (from project memory — DO NOT deviate)

- Frontend tests: `cd web && /usr/local/bin/npx vitest run` (single file:
  `… vitest run src/components/world3d/cityFaces.test.ts`).
- Typecheck: `cd web && /usr/local/bin/npx tsc -b --force` (NOT `--noEmit` —
  project refs with `files:[]` make it vacuous).
- `node`/`npx`: use `/usr/local/bin/...` (nvm shim is broken).

## 5. Gate sequence (orchestrator)

1. Lane A builds + self-verifies (`cityFaces.test.ts` green, typecheck clean).
2. Lane B builds against the REAL `cityFaces.ts` + self-verifies.
3. **Wave gate (lead, inline):** integrated `tsc -b --force` + `vitest run` — ALL
   green, existing goldens **unchanged**.
4. **Adversarial verify (workflow):** algorithm-correctness lens, byte-identical/
   determinism lens, silent-drop/crash lens — each tries to REFUTE.
5. **QA gate:** QE writes `coordination/em264-qa-report.json` (schema-conformant);
   `gate_decision.proceed` must be true, no CRITICAL blocker, contract_conformance
   ≥ 3, security ≥ 3.
6. **Visual sign-off (USER gate, deferred):** flip `GRAPH_LOTS_ENABLED = true`
   against a live pentagon and confirm buildings land inside the road-enclosed
   blocks (no grid-on-pentagon). Ships **off** until the user signs off — exactly
   the `ROAD_MESH_ENABLED` (EM-247) pattern.

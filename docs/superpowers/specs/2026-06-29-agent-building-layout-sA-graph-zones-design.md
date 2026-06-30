# Agent-Controlled Building Layout — SA: Graph-Derived Buildable Zones

> **Parent:** `2026-06-29-agent-building-layout-overview-design.md`.
> **Depends on:** the merged road suite — EM-239 (`CityGraph` spine), EM-247
> (procedural mesh, `ROAD_MESH_ENABLED` default-on). Reuses `roadTileSetFrom` /
> the `city_graph` snapshot field already on `CityWorld`.
> **Ledger:** EM-264. **Status:** design (2026-06-29).

## 1. Goal

Make buildings follow the road graph instead of a frozen grid. Walk the graph's
enclosed regions (planar faces), turn each into a buildable **zone**, and place
buildings into zones — so a pentagon road plan finally gets pentagon-shaped
blocks. Frontend-only; behind `GRAPH_LOTS_ENABLED`, default **off** and
byte-identical to today's grid.

This is the keystone: it both delivers the visible fix **and** lays down the
`zone` data shape (with an empty `rules` hook) that SB and SC build on.

## 2. Non-goals (out of scope for SA)

- **No agent behavior change.** No new verbs, no perception, no backend. Agents
  still author buildings exactly as today; this slice only changes *where the
  renderer puts them.*
- **No rule authoring / enforcement** — that's SB/SC. Zones carry an empty
  `rules` field now purely as the forward hook.
- **No geometric perfection.** Face boundaries are loose by design (pillar 2).
- **No new GLB assets / no road changes.** Roads already render via EM-247.

## 3. Stage 1 — find the blocks (`cityFaces.ts`)

New module `web/src/components/world3d/cityFaces.ts`:

```ts
export interface CityFace {
  /** Boundary node ids in walk order (loose; may be slightly degenerate). */
  boundary: string[];
  /** Polygon vertices in world space, same order as boundary. */
  poly: { x: number; z: number }[];
  centroid: { x: number; z: number };
  /** Signed area; the unbounded outer face is dropped by sign + max-area. */
  area: number;
}

export function planarFaces(graph: CityGraph | null | undefined): CityFace[];
```

- **Algorithm:** standard planar-subdivision face trace — half-edge / next-edge-
  by-angle walk. For each directed half-edge, the next half-edge around the walk
  is the most-clockwise turn at the destination node; faces are the closed
  cycles. Drop the one unbounded outer face (largest |area|, or the
  opposite-sign winding).
- **Loose, defensive, never throws** (pillar 2). Specifically:
  - **Dangling stubs** (degree-1 nodes): traversed and returned to (they border
    no enclosed region) — produce no spurious face, no crash.
  - **Disconnected components:** each connected component enumerated
    independently; every component that encloses area yields its zone(s).
  - **Degenerate / near-collinear faces:** allowed through as loose polygons —
    not discarded (discarding is the *silent-drop* failure we forbid).
  - **No graph / corrupt graph / no edges:** return `[]` (caller falls back to
    the grid path — fallback discipline). Mirror the type-guards already in
    `roadTileSetFrom` (`!graph || !Array.isArray(nodes/edges) || !edges.length`).
- **Deterministic:** pure function of the graph; node/edge order is stabilized by
  sorting on id before the walk, so output order is fixed regardless of input
  array order (EM-155).

## 4. Stage 2 — each face becomes a buildable ZONE

```ts
export interface BuildZone {
  id: string;                 // stable: derived from sorted boundary node ids
  face: CityFace;
  /** Suggested lots — a hint, NOT an assignment (overflow/gaps allowed). */
  suggestedLots: CityInstance[];
  zoneHint: CityZone;         // derived default (centroid's nearest place)
  /** SB hook — empty in SA. Optional rules agents author later. */
  rules: ZoneRule[];          // [] in SA
}
```

- **`suggestedLots`:** seeded grid (or ring) of lot pads, inset from the face
  boundary by a margin, clipped to the interior — generated with the existing
  `hashUnit(seed, 'zone-lot', …)` idiom. This is the *suggestion*; the placer in
  Stage 3 may overflow it. Loose clipping is fine.
- **`zoneHint`:** the derived default zone (`zoneForPlace(nearestPlace(centroid))`)
  — reuses the existing zone-tint vocabulary. In SA this only tints the ground,
  exactly as block zones do today.
- **The inner core is just another zone** — no special-casing (pillar 4).
- **`id`** is content-stable (sorted boundary node ids), so SB can attach rules
  to *this* zone and have them survive a graph morph.

## 5. Stage 3 — place buildings into zones (`computeCityPlan` branch)

`computeCityPlan` gains a branch, gated by a flag threaded in from `CityScape`:

```ts
if (GRAPH_LOTS_ENABLED && hasRealGraph(world.city_graph)) {
  const zones = buildZonesFromFaces(planarFaces(world.city_graph), seed, places);
  // emit zones' ground tiles + suggestedLots as the blockLots/emptyLots source
  // assignBuildingLots places real W7 buildings into zone lots (round-robin +
  //   slotLayout ring fallback — ALREADY tolerant of fewer/uneven lots)
} else {
  // unchanged: today's fixed-grid Pass 1 / Pass 2 (byte-identical, EM-155)
}
```

- **Reuse `assignBuildingLots` as-is.** It already round-robins buildings across
  available lots and falls back to a `slotLayout` ring when lots run out — so it
  *already* tolerates "fewer lots than buildings" and "uneven lots," which is
  exactly the loose behavior we want. Zone lots feed it the same `CityBlockLots[]`
  / `emptyLots` shape it consumes today; minimal change.
- **The lot grid is a suggestion.** Overflow rings outside `suggestedLots` and
  empty zones are both acceptable outputs.
- **`CityPlan` shape unchanged** except (additive) an optional `zones?: BuildZone[]`
  the renderer can use for tints/labels now and SB/SC reuse. `blocks` / `blockLots`
  / `emptyLots` / `realLots` / `streets` / `pedestrianTiles` all keep their types.

## 6. Frontend integration (`CityScape.tsx`)

- **Flag:** `const GRAPH_LOTS_ENABLED = false;` (module const, mirrors
  `ROAD_MESH_ENABLED`). Threaded into `computeCityPlan` (add a param or read a
  module flag — match how `ROAD_MESH_ENABLED` is wired).
- **Signature:** `citySignature` already folds node/edge counts + `car_policy`.
  Because zones are a pure function of those edges, the existing signature already
  re-derives zones when the graph changes — **but add an explicit reactivity test**
  (pillar: the thrice-shipped bug) confirming a graph mutation re-runs the plan and
  a no-op poll does not churn it.
- **No new render components in SA** — zones reuse the existing ground-tile / lot-
  pad rendering. (SB adds rule tints/labels.)

## 7. Determinism, fallback & testing

- **Off-path byte-identical (EM-155):** with `GRAPH_LOTS_ENABLED = false`, the
  existing `cityLayout.test.ts` golden passes unchanged — this is the hard gate.
- **On-path determinism golden:** same graph + seed ⇒ byte-identical plan; input
  array order of nodes/edges does not affect output.
- **Face cases (`cityFaces.test.ts`):**
  - classic 5×5 grid graph → 25 enclosed faces (one per block), no outer face.
  - pentagon master-plan graph → 5 outer faces + 1 core face, all buildable.
  - **dangling stub** → no spurious face, stub does not crash the walk.
  - **disconnected components** → both components yield their zones (no region
    silently dropped — the forbidden failure).
  - **concave / near-collinear face** → returned as a loose polygon, lots clip
    into it without crashing (geometry need not be pretty — pillar 2).
  - empty / corrupt / no-edge graph → `[]` (caller falls back to grid).
- **Placement:** more buildings than lots → overflow handled (no crash, no drop);
  empty zone → renders empty; uneven zones → buildings still placed.
- **Render reactivity:** flip graph content ⇒ plan changes; flip nothing ⇒ stable
  (no per-poll churn).

**Acceptance:** with the flag on, a pentagon/radial road graph renders buildings
inside the road-enclosed blocks (no more grid-on-pentagon); with the flag off the
plan is byte-identical to today; no graph mutation ever crashes or silently drops
a region.

## 8. Risks & open questions

- **Planar enumeration is the hard part** ("the EM-247 of lots"). Mitigation: the
  chaos framing *lowers* the bar — loose faces are acceptable; only crashes /
  silent drops fail. The test list pins the failure modes, not pixel accuracy.
- **Performance:** face enumeration runs in `useCityPlan` per signature change
  (not per frame). Bound it; the 9×9 growth envelope keeps node/edge counts small.
- **Open:** lot-inset margin and `suggestedLots` density — set during build against
  a live pentagon so blocks read as populated-but-loose, not packed.

## 9. What SB needs from SA (handoff)

- `BuildZone` with a **stable `id`** (sorted boundary node ids) and an empty
  `rules: ZoneRule[]` field — SB attaches voted rules to these ids.
- `zones` surfaced on `CityPlan` so SB can render rule tints/labels and SC can
  target zones.
- Proven loose/defensive face enumeration (stubs/disconnected/degenerate) so SB's
  morph-survival of rules has a stable zone-identity foundation.

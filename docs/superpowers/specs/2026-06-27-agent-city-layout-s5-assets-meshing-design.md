# Agent-Controlled City Layout — S5: Asset & Road-Mesh Expansion

> **Parent:** `2026-06-27-agent-city-layout-overview-design.md`.
> **Status:** design (2026-06-27).
> **Two independent tracks:** **S5a** (road meshing — gates S3b + geometric S4 presets) and
> **S5b** (building variety — standalone, the immediate fix for the repeat-asset pain).

## Track S5b — building variety (standalone, ship anytime)

The screenshots read as repeats because 99 GLBs collapse to a **frozen 23-key registry**
with **one GLB per key**, and buildings fall through to a thin "generic" pool (~86% per the
generic-pool finding). S5b breaks that monoculture. **No dependency on any other sub-project**
— it can ship first as the immediate visible win.

- **Vendor more CC0 GLBs** via the established pipeline (`docs/em216-kit-acquisition-plan.md`:
  poly.pizza CC0-only + `@gltf-transform`, runtime toon, variant pools). Target the buckets
  that actually repeat: the **generic building pool** first (it dominates), then per-zone
  variety (commercial/residential/industrial/civic) and props.
- **Expand the registries:** widen the building variant pools (`assets/models.ts`,
  `propModels.ts`, the generic pool) so each semantic key draws from many GLBs, chosen by the
  existing seeded-hash idiom (deterministic; EM-155-safe).
- **CC0 discipline:** every vendored file gets an `ASSET_LICENSES.md` row (standing rule);
  verify license text in-archive before vendoring.
- **Determinism:** variant selection is seeded per (building id / lot) — same world ⇒ same
  models. No new visual churn beyond the wider pool.

S5b acceptance: walking the city, building/prop repetition is visibly reduced; the generic
monoculture is gone; all assets CC0 + licensed; output stays deterministic.

## Track S5a — procedural road meshing (gates S3b + geometric presets)

Chosen approach: **procedural extrusion**. Build road geometry at runtime from the
`CityGraph` so **any** angle/topology renders — the only honest path to true pentagon/radial/
roundabouts.

### What it builds
- **Edges → road ribbons:** extrude a width-correct ribbon along each edge (honoring
  `road_class` width and `car_policy` surface).
- **Nodes → intersections:** generate junction/corner/tee geometry procedurally;
  **roundabout** and **plaza** node kinds get their own parametric geometry (roundabout =
  annulus + island; a small CC0 GLB centerpiece is an optional polish, not required).
- **Lane markings / crosswalks / sidewalk surfaces:** from the atlas; pedestrian edges
  (S3a) render a sidewalk/plaza surface.

### Rendering architecture (follows `deep-research-v4.md §4`)
- **Raw `<instancedMesh>` per piece-type bucket** (not drei `<Instances>`); one toon atlas
  material; ~10–20 draw calls for the whole city.
- **Chunked culling** by block/region; **LOD** via `<Detailed>` for distant shells.
- **Determinism:** the mesh is a pure function of the `CityGraph` (+ seed) — same graph ⇒
  same geometry; replay/fork safe.

### Relationship to the tile renderer
S5a **supersedes** the 5 Kenney road tiles (it handles axis-aligned roads too), unifying the
road path. But it is a **visual change**, so it is NOT byte-identical to S1's tile look —
treat it like EM-127's deferred day/night: **land behind a visual sign-off**, keep the tile
path as a fallback until signed off. (S1–S2's byte-identical guarantee is about the *grid
data*, not about forever freezing the road art.)

### Components & boundaries
- **Frontend — new road-mesh module** (`world3d/`): `buildRoadMesh(graph)` → instanced
  geometry; roundabout/plaza generators; atlas/toon integration; chunked culling; LOD.
- **Frontend — renderer wiring:** consume the mesh in `CityScape.tsx`; traffic (EM-169)
  honors per-edge `car_policy`.
- **Assets:** optional roundabout/plaza/footpath/bridge CC0 GLBs (polish), licensed.

### Testing & acceptance
- Mesh determinism per graph; arbitrary-angle edges render without gaps/z-fighting;
  roundabout/plaza nodes read correctly.
- Draw-call budget < ~100 on integrated-GPU 60fps target; chunked culling verified.
- Visual sign-off gate before retiring the tile path.
- Acceptance: a pentagon/radial graph (from S3b or an S4 preset) renders cleanly at 60fps.

## Sequencing

- **S5b** is independent → can ship **first** (immediate repeat-asset fix), in parallel with
  S1/S2.
- **S5a** is the gating dependency for **S3b** and the **geometric S4 presets** → sequence
  `S1 → S2 → S3a → S5a → S3b` (S4 grid/greenfield/village land early; geometric presets ride
  S5a).

## Risks & open questions

- **S5a meshing quality** (intersections, roundabouts, no gaps at arbitrary angles) is the
  hard part — budget real iteration; keep the tile fallback until sign-off.
- **Perf at scale:** a grown/morphed city is larger than today's 5×5 — lean on instancing +
  chunked culling + LOD from the start.
- **Asset sprawl (S5b):** keep pools CC0 + licensed + deterministic; vendor toward the
  buckets that actually repeat, not breadth for its own sake.

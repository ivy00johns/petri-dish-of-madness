# Wave C — "a town, not a diorama" (design spec)

> **Status:** approved design (2026-06-10) — pending implementation plan (writing-plans).
> **Branch (future build):** `build/wave-c-real-city` (Wave C starts after Wave B merges).
> **Predecessor:** Wave B (`build/wave-b-city-comes-alive`) lands first as the
> lighting/material/instancing foundation — see `contracts/wave-b.md`.
> **Art roadmap parent:** `docs/ui-redesign/3D-WORLD-ART-DIRECTION.md` (this realizes the
> deferred GLB building-kit swap — ledger **EM-122**'s explicitly-deferred remainder, now
> **EM-150** — plus the **EM-124** character-mesh swap, and a layout rethink the art doc
> never scoped. The art doc's internal EM table uses pre-intake report numbering; ledger
> IDs are canonical. Filed via `plan-intake` 2026-06-10 as **EM-147–150** + EM-124 rescope).

## 1. Problem

The cozy 3-D village is being *spruced up*, not *rethought*. Two gaps produce the
"polished blocks pointing at a fountain" look the screenshot shows, and neither is on
any current plate.

**Gap 1 — fidelity (generic blocks).** Wave B is renderer-only on the existing
procedural geometry by design. `contracts/wave-b.md:160` is explicit:
*"Buildings remain procedural this wave — the external GLB kit swap (KayKit/Kenney)
stays deferred."* So EM-122's "distinct buildings" are better silhouettes made of the
same primitives (a garden is planted-rows-of-boxes; a workshop is a box with a
chimney-box). The thing that actually turns *generic blocks* into *assets that look
nice* — real CC0 GLB model kits — is exactly what the art doc defers (the EM-122 GLB
building swap, the EM-124 character swap — ledger IDs). Nobody scheduled it. (Now
scheduled: EM-150 / EM-124.)

**Gap 2 — structure (the fountain pinwheel).** `config/world.yaml:148-153` defines only
**5 places**, all packed into the center of the logical grid (plaza dead-center at
`500,500`; the others within ~250 units). `worldSpace.ts` maps that onto a 40-unit
plane (`SIZE = 40`), and the camera's home target is the plaza. Worse, `Ground.tsx:56-63`
draws paths as straight spokes *from the social hub to every other place* — the radial
pinwheel, rendered in dirt. There are no streets, no districts, no sprawl: none of what
makes Stardew / SimCity / GTA read as *a place you move through*. Wave B does not touch
this.

## 2. Decisions (locked 2026-06-10)

1. **Fidelity: real CC0 asset kits — full.** Bring in Kenney / Quaternius / KayKit GLB
   models for buildings, villagers, **and** signature props. Instanced + lazy-loaded so
   the feed and the 60fps bar stay cheap; procedural geometry survives only as invisible
   filler and as the in-flight loading fallback.
2. **Layout: cozy village + districts.** Replace the radial cluster with a handcrafted
   ~15-place town of distinct districts linked by a lane network, on a larger ground
   plane. (Stardew-leaning, not a SimCity grid — stays legible with only 3-5 agents.)
3. **Sequencing: land Wave B, then build Wave C.** Wave B's golden-hour lighting + toon
   ramp + instancing infra are keepers — they light the GLB models too, and EM-122's
   `kind → VariantKey` mapping is reused verbatim. Only EM-122's *procedural building
   geometry* is superseded.
4. **Handcraft the hero town first; generator later.** Design the town **in code/config**,
   get the place schema correct and working, *then* scale to a procedural district
   generator that emits the same schema. (Honors `v3-city-depth-before-multi-city`:
   deepen one city before founding a second.)

The feed remains the product centerpiece (`chat-feed-is-centerpiece`). The 3-D world
stays the center-panel `<Canvas>`; lazy-loading keeps first paint fast so the city
upgrade never taxes the feed.

## 3. Architecture — three new seams

The data flow is unchanged: world snapshot (`places[] / agents[] / buildings[] /
animals[]`) → `CozyWorld` → `Scene`. Only the *renderers* (mesh → GLB) and the *layout
coordinates* change. The event/snapshot schema stays additive-only (no renames, no
removals, no changes to existing `to_dict()` keys).

### A. Asset layer — new `web/src/components/world3d/assets/`

- **`models.ts`** — the single source of truth. Maps each `VariantKey` (reused from
  EM-122's `operationalVariant`) and each `PlaceKind` → `{ glbUrl, scale, yOffset,
  rotation, clips? }`. A registry, not scattered literals.
- **`<Model>`** — a wrapper over drei `useGLTF` + `<Clone>`. Anything that repeats
  (trees, fences, lamps, same-variant cottages) is instanced via drei `<Merged>` /
  `<Instances>` so N copies cost ~1 draw call per part.
- **Loading discipline** — `useGLTF.preload()` for the hero kits (plaza, cottages,
  villagers); everything else behind `<Suspense>`. **Fallback invariant:** while a GLB
  is in flight, render the existing procedural mesh so the scene never shows a hole.
- **No new runtime deps.** three 0.171 + drei 9.122 already ship `useGLTF`, `<Merged>`,
  `<Instances>`, `useAnimations`, `<Detailed>`. Meshopt/DRACO decoders (for small GLBs)
  are vendored into `web/public/` rather than added to `package.json`.

### B. Layout layer — `config/world.yaml` + `Ground.tsx` + new `townLayout.ts`

- **Expanded places (~15).** Districts, using the existing 5 kinds only (→ zero engine
  change, see §5): **plaza core** (`social` + the well), **market lane** (2-3 `work`),
  **residential row** (several `home` cottages), **civic corner** (`governance` + a 2nd
  civic), **farm/orchard edge** (`wild` / `work`) with a stream. `SIZE` is increased and
  the coordinates spread so districts breathe.
- **Lane network replaces hub-and-spoke.** `Ground.tsx`'s spoke paths are replaced by a
  graph: a main-lane spine plus connector segments between adjacent districts
  (nearest-neighbor within/between districts), rendered as road/lane meshes with
  junctions. **This is the change that kills the pinwheel.**
- **`townLayout.ts`** — pure and tested. Given places (+ their district), it emits: lane
  segments (the graph), per-district ground-zone tints, and clearance-aware prop "lots"
  (benches, lamps, market goods) along lanes — reusing the seeded `hashUnit` scatter so
  it is deterministic and unit-testable.

### C. Characters — `Villager.tsx` / `Critter.tsx` swap

- Capsule villagers → rigged CC0 chibi GLB driven by drei `useAnimations` (idle + walk;
  the walk clip plays while the existing `animMap` lerp carries the villager between
  places). Per-agent identity tint via material override. Name label, model chip, and
  chat bubble stay as DOM overlays (unchanged).
- Cat / dog critters → CC0 animal GLBs, same animation treatment. The magenta chaos
  accent stays.

## 4. The place schema (get this right first)

The handcrafted town **defines the target schema the future generator must reproduce.**
Minimal, additive extension to `PlaceConfig` / the place serialization:

```yaml
places:
  - { id: plaza, name: "Central Plaza", x: 500, y: 500, kind: social,
      district: "core", description: "Open square where everyone mingles." }
  # ... ~15 places across districts: core / market / residential / civic / farm
```

- **`district: str | None`** — the one new field. Optional, additive (default `null`).
  Serialized into the place dict so the frontend can group districts for zone tinting
  and lane adjacency; when absent, `townLayout.ts` falls back to coordinate clustering.
- Everything else (`id / name / x / y / kind / description`) is unchanged. Kinds stay
  the existing five (`social / work / governance / home / wild`).
- Lanes are **derived** by `townLayout.ts` from positions + districts (spine +
  nearest-neighbor) — not hand-authored in config for the MVP. Explicit lane authoring
  is a possible later schema addition, noted but out of scope here.
- The future generator (deferred) reuses this exact schema and kind set; `procgen` /
  `generate_procgen_places` will emit `district`-tagged places when it is built.

## 5. Backend impact — near zero

`loader.py` reads `places:` generically into `PlaceConfig{id,name,x,y,kind,description}`;
no engine path hardcodes the 5 place ids except the default-config mirror in `loader.py`
itself. The building/project pipeline, movement, well, and notice-board logic all iterate
places generically (the notice board keys on the `plaza` id / first `social` place — we
keep a plaza, so it still resolves).

Backend work for Wave C is therefore: (1) add the district town to `config/world.yaml`
and the `loader.py` default mirror; (2) add the optional `district` field to
`PlaceConfig` + place serialization; (3) a test proving an ~15-place town runs end to end.
**No event/snapshot schema changes beyond the one additive optional field.**

## 6. Reuse, don't reinvent

EM-122 shipped `operationalVariant(kind) → VariantKey`
(`garden / farm / workshop / library / clocktower / house / stall / monument / well /
generic`) with keyword matching and tests, so agent-invented kinds ("prepare_beds",
"Bram's Market Stall") already resolve sensibly. Wave C **repoints each `VariantKey` at a
GLB instead of procedural geometry** — the mapping and its tests carry over verbatim.
`healthTint` (soot) stays, applied as a GLB material tint so a half-burned workshop still
looks half-burned.

## 7. Asset kits (all CC0 → recorded in `ASSET_LICENSES.md`)

- **Buildings:** Kenney City / Survival + KayKit City / Medieval — cottages, market
  stalls, hall, well, towers.
- **Nature / props:** Kenney Nature (trees, rocks, bushes) + City / Furniture (benches,
  lamps, fences, crates, signs).
- **Characters:** Quaternius animated Universal characters + animals (rigged GLB).
- **Roads:** Kenney City (Roads) tiles **or** widened toon lane strips — a look-dev call
  at C3, not a blocker.

CC0-only is a hard rule; never ship art ripped from commercial games. Every external
asset is recorded in `ASSET_LICENSES.md`.

## 8. Performance (the 60fps bar)

- Instance every repeated model via `<Merged>` / `<Instances>`.
- `<Detailed>` LOD for distant buildings/trees (Wave B's foliage already proved the
  pattern).
- Lazy-load non-hero kits behind `<Suspense>`; preload the hero set.
- Keep GLBs small and meshopt/draco-compressed.
- If any kit can't hold 60fps at the default camera on an M-series Mac, fall back to the
  procedural mesh and **say so in the build report** — same discipline as Wave B.

## 9. Wave breakdown & gates (mirrors the Wave B contract style)

- **C1 — config/schema (tiny, backend).** District `places:` in `world.yaml` + loader
  mirror; optional `district` field on `PlaceConfig` + serialization; test that an
  ~15-place town runs (movement, building pipeline, well + notice-board still resolve).
- **C2 — asset layer (foundational; others depend on it).** `assets/models.ts` registry
  + `<Model>` / instanced loader + Suspense/preload + vendored decoders + first GLBs +
  `ASSET_LICENSES.md` entries.
- **C3 — layout/roads.** `townLayout.ts` (pure, tested) + `Ground.tsx` lane network +
  district zone tints + `SIZE`/coordinate retune + camera `PAN_BOUND`/bounds update.
- **C4 — buildings swap.** `Structure.tsx` / `Building.tsx` render GLBs via the registry
  keyed by `operationalVariant`; keep status renderers, soot tint, EM-102 labels, idle
  bob.
- **C5 — characters swap.** `Villager.tsx` / `Critter.tsx` GLB + `useAnimations`
  (idle/walk), per-agent tint, overlays intact.
- **Gate each wave:** full backend pytest + web vitest + `npm run build` + an orchestrator
  browser check (scene renders, console clean, 60fps at default camera). Final:
  render-sanity + ux-review pass, then ledger/BUILD-doc updates.

## 10. Testing

- **Pure logic → unit tests** (the repo's pattern): `townLayout` determinism + clearance
  invariants + lane-graph adjacency; `models.ts` registry completeness (every
  `VariantKey` and `PlaceKind` resolves to a real `glbUrl`); EM-122's `operationalVariant`
  tests reused unchanged; the new `district` field round-trips through serialization.
- **Visual quality → browser/ux-review gates** (a render cannot be unit-tested).

## 11. Out of scope (YAGNI / deferred)

- Day/night + seasons + weather + particles (EM-124).
- The procedural district **generator** (handcraft the hero town first — decision 4).
- A second city / multi-city.
- Tilt-shift "diorama" share-card / mobile hero mode (Direction 2 — a separate, isolated
  render path).
- Postprocessing stack (bloom / N8AO / vignette / LUT — EM-127).

## 12. Open look-dev decision (not a blocker)

Roads rendered as Kenney road-tile GLBs vs. widened warm-toon lane strips — decide
visually during C3. Both satisfy the contract; the choice is purely which reads more
"cozy" against the golden-hour palette.

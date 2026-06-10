# Wave C contract — "a town, not a diorama"

> Source design (frozen decisions): `docs/superpowers/specs/2026-06-10-wave-c-real-city-design.md`
> Ledger items: **EM-147** (C1) · **EM-148** (C2) · **EM-149** (C3) · **EM-150** (C4) · **EM-124** (C5)
> Branch: `build/wave-c-real-city` (stacked on `fix/live-run-annoyances`, PR #8)
> Build waves: **wave 1 = C1 ∥ C2** → gate → **wave 2 = C3 ∥ C4 ∥ C5** → gate → QE → closeout.

## Global rules (binding on every agent)

1. **Free-scale law.** No change may add a standing LLM call. This wave is renderer +
   config only — zero engine-LLM surface.
2. **Exclusive file ownership** (below). Need another agent's file? Stop and report the
   exact change to the orchestrator — never edit it yourself.
3. **Agents never commit.** The orchestrator commits at gates.
4. **Additive-only data contracts.** The world snapshot/event shapes may gain optional
   keys; no renames, no removals, no changes to existing `to_dict()` keys. The ONE
   schema delta this wave: optional `district: str | None` on places (C1).
5. **CC0 only, recorded.** Every external asset lands with a row in `ASSET_LICENSES.md`
   (name, author, source URL, license, file paths). Never ship art ripped from
   commercial games. Prefer assets fetchable headlessly (GitHub releases, direct zips).
6. **60fps bar** at the default camera on an M-series Mac. Instance every repeated
   model (drei `<Merged>`/`<Instances>`); `<Detailed>` LOD where Wave B used it. If a
   kit can't hold 60fps, fall back to the procedural mesh AND say so in your report.
7. **Fallback invariant (load-bearing).** While any GLB is in flight (or fails to
   load), the existing procedural mesh renders in its place. The scene never shows a
   hole and never regresses below Wave B quality. `<Suspense>` boundaries per model
   group, with the procedural renderer as the fallback child.
8. **One visual language.** GLB materials are converted to the toon ramp —
   `toonGradientMap()` from `toon.ts`, original texture/color maps preserved — so kits
   match Wave B's golden-hour banding. No untouched PBR materials in the frame.
9. **No new runtime deps.** three 0.171 + drei 9.122 already ship `useGLTF`, `<Clone>`,
   `<Instances>`, `<Merged>`, `<Detailed>`, `useAnimations`. Meshopt/DRACO decoders are
   vendored into `web/public/` if needed — never added to `package.json`.
10. **WebGL hex exemption** stands (Wave B convention): canvas-only colors live in
    worldSpace.ts / toon.ts / the world3d tree, not CSS tokens.
11. **Tests are the gate.** Pure logic → vitest/pytest. Every agent leaves its suite
    green and reports the count.

## The place schema (C1 defines it; everyone consumes it)

```yaml
places:
  - { id: plaza, name: "Central Plaza", x: 500, y: 500, kind: social,
      district: "core", description: "Open square where everyone mingles." }
```

- `district` is OPTIONAL and additive (default null). Kinds stay the existing five
  (`social / work / governance / home / wild`). ~15 places across districts:
  **core** (plaza + well), **market** (2–3 work), **residential** (several home),
  **civic** (governance + a 2nd civic), **farm** (wild/work edge).
- The first governance place keeps id `townhall`, the social anchor keeps id `plaza`
  (billboard + notice-board gates key on them).
- Lanes are DERIVED by `townLayout.ts` from positions + districts — not authored in
  config.
- The handcrafted town defines the schema a future generator must emit (spec §4).

## Agent C1 — backend district town (EM-147)

**Owns:** `config/world.yaml` (places block), `backend/petridish/config/loader.py`,
`backend/petridish/engine/world.py` (PlaceState/PlaceConfig serialization ONLY),
`backend/tests/test_wave_c_town.py` (new).

- Add `district: str | None = None` to PlaceConfig/PlaceState + `to_dict()` (additive).
- Author the ~15-place district town in `config/world.yaml` AND the loader's default
  mirror. Coordinates spread across the logical [0..1000] grid so districts breathe
  (plaza stays near center; districts cluster, e.g. market east, residential south-west,
  civic north-west, farm south-east — exact numbers are C1's call, but place-place
  spacing within a district ≥ 60 logical units, district centroids ≥ 250 apart).
- NOTE: `world.yaml` has an uncommitted USER edit — read it, preserve their change,
  extend the places block only.
- Tests: district round-trips config→PlaceState→to_dict→from_snapshot; a 15-place town
  runs end-to-end (movement, building pipeline, well + notice-board resolve); absent
  `district` defaults null (back-compat with old snapshots).

## Agent C2 — asset layer (EM-148) — foundational; wave 2 depends on it

**Owns:** `web/src/components/world3d/assets/` (new dir: `models.ts`, `Model.tsx`,
`models.test.ts`), `web/public/models/` (new), `web/public/draco/` or meshopt decoder
if needed, `ASSET_LICENSES.md`.

- **Acquire CC0 kits headlessly** (curl/gh): prefer KayKit GitHub repos
  (github.com/KayLousberg — City Builder Bits / Medieval Town / Adventurers /
  Restaurant etc.), Kenney direct zips (kenney.nl — Fantasy Town Kit, Nature Kit),
  Quaternius (quaternius.com direct zips / GitHub mirrors). Verify CC0 in each kit's
  bundled license file BEFORE vendoring; record in `ASSET_LICENSES.md`.
- Budget: keep vendored GLB payload lean — only the models the registry references,
  not whole kits; target ≤ 15 MB total in `web/public/models/`.
- `models.ts` — THE registry: `MODEL_REGISTRY: Record<VariantKey, ModelSpec | null>` +
  `PLACE_MODELS: Record<PlaceKind, ModelSpec | null>` + character/critter/prop entries.
  `ModelSpec = { url, scale, yOffset, rotation?, clips? }`. `null` = stay procedural
  (legitimate; recorded). Footprint discipline: buildings read at ≲3 world units in the
  4.2-spacing slot rings (scale accordingly).
- `<Model>` — drei `useGLTF` + `<Clone>`, toon-converts materials ONCE per GLB (cache),
  preserves maps, applies `healthTint`-compatible color override hooks, castShadow on.
  `<InstancedModel>` for repeats via `<Merged>`.
- `useGLTF.preload()` for the hero set (place models, villager, cat/dog); everything
  else lazy behind `<Suspense>`.
- Tests (no canvas): registry completeness (every VariantKey + PlaceKind key present,
  spec shape valid, urls point under /models/ and exist on disk — fs check in vitest is
  fine), scale/footprint bounds, toon-conversion function unit-tested on a stub
  material tree.
- **Do NOT touch** Structure.tsx / Building.tsx / Villager.tsx / Critter.tsx /
  Scenery.tsx — wave 2 owns the consumers.

## Agent C3 — town layout + lanes (EM-149) — wave 2

**Owns:** `web/src/components/world3d/townLayout.ts` (+ test), `Ground.tsx`,
`worldSpace.ts` (SIZE + camera-bounds constants ONLY — coordinate mapping math stays),
`CozyWorld.tsx` (camera PAN_BOUND + zone-tint mount only), `foliageLayout.ts` ONLY if
clearances must learn lanes (coordinate with the contract: pathSegments() moves to
townLayout and foliage consumes it).

- `townLayout.ts` (pure, tested): lane graph = main-lane spine through district
  centroids + nearest-neighbor connectors (every place reachable, no orphan), junction
  points, per-district ground-zone tints, clearance-aware prop lots along lanes
  (seeded `hashUnit`, deterministic).
- `Ground.tsx`: lane meshes from the graph **replace the hub→place spokes** (the
  pinwheel dies this wave). Look-dev call: widened warm-toon lane strips vs Kenney road
  tiles — decide visually, record the call + a screenshot in your report.
- Retune `SIZE` (e.g. 40 → ~64) so ~15 districted places breathe; update camera
  PAN_BOUND/zoom bounds; villager/critter wander + building slot rings must still land
  on their places (verify, don't rewrite).
- Tests: determinism, reachability (graph connects all places), lane-clearance
  invariants, zone-tint mapping, fallback to coordinate clustering when `district`
  is absent (pre-C1 snapshots).

## Agent C4 — buildings GLB swap (EM-150) — wave 2

**Owns:** `web/src/components/world3d/Structure.tsx`, `Building.tsx`,
`worldSpace.test.ts` additions if mapping consts move (they should NOT — reuse
`operationalVariant()` verbatim).

- Operational buildings render `<Model>` from the registry keyed by
  `operationalVariant(kind)`; registry `null` → keep the EM-122 procedural variant
  (it IS the Suspense fallback child either way).
- Preserve: status renderers (planned/under_construction/damaged/etc. stay procedural
  this wave), `healthTint` soot applied as a GLB material color tint, offline glow
  extinguish, EM-102 label gating, idle bob, onPick/click-to-focus.
- Tests: variant→model wiring table, soot-tint application path, fallback selection
  logic (pure helpers extracted so no canvas needed).

## Agent C5 — characters swap (EM-124) — wave 2

**Owns:** `web/src/components/world3d/Villager.tsx`, `Critter.tsx`.

- Villagers: rigged CC0 chibi GLB via registry + drei `useAnimations` — idle clip at
  rest, walk clip while the existing `animMap` lerp moves them. Per-agent identity
  tint via CLONED materials (`<Clone>` shares materials by default — clone before
  tinting). DOM overlays (name label, model chip, chat bubble) untouched.
- Critters: CC0 animal GLBs, same treatment; magenta chaos accent stays.
- Capsule/procedural bodies remain as the Suspense fallback.
- Tests: pure helpers (clip selection by movement state, tint cloning) unit-tested.

## QE agent — gate (mandatory)

Full backend pytest + web vitest + `npm run build` + adversarial probes (suggested:
missing GLB file → fallback renders; registry null entry; pre-C1 snapshot without
`district`; 15-place town snapshot resume; malformed kind through the GLB path —
the 'constructor' class again). `coordination/qa-report.json` per the standard schema.

## Gates (orchestrator-run)

Wave gate after each build wave: backend pytest + web vitest + build + Playwright
browser pass (scene renders, console 0 errors, fallback never shows holes, fps
spot-check). Final: render-sanity + scoped ux-review + ledger/BUILD-doc closeout.

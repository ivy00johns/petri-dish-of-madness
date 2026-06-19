# EM-216 — new-kit acquisition plan (the Wave K visual finisher)

> **Status:** the *registry side* of EM-216 shipped with Wave K (PR #18). `PROP_MODELS`,
> `propVariant`, build-type palettes, and the `PlacedProps` render path are all live, wired to
> **already-vendored** GLBs. This doc is the runbook for the one recorded HITL follow-on:
> vendoring the **new** CC0 kits so props and building types render as distinct *new art* instead
> of reused city-kit GLBs + procedural fallbacks. When the GLBs land, the systems consume them
> with **zero further code** — only registry rows + `ASSET_LICENSES.md` entries.
>
> **The "HITL = needs network" tag is satisfiable here.** Verified 2026-06-18: `kenney.nl`,
> `github.com/KayKit-Game-Assets`, and the npm registry all return HTTP 200 from this environment.
> So Claude can execute the downloads + repack + wiring + tests autonomously. The genuine
> human-in-the-loop bits are (a) aesthetic GLB selection, (b) confirming each kit's bundled
> `License.txt` says CC0 before vendoring, and (c) scope sign-off.

---

## 1. What's already true (don't redo it)

- **Runtime toon conversion.** `assets/toonify.ts` `toonifyScene()` converts every loaded GLB's
  materials to `MeshToonMaterial` (gradient ramp, `.map`/`.color` preserved) **at load time**,
  cached per source material. There is **no offline toon-ramp step** — drop a clean GLB in and it
  matches the art direction automatically. (The ledger's "per-atlas toon-ramp conversion" was the
  EM-152 description; in practice it's runtime.)
- **No DRACO / meshopt.** Per `ASSET_LICENSES.md`: existing GLBs were repacked with
  `@gltf-transform` (`copy`/`dedup`/`prune`/`resample`, gltf→glb texture embedding), **no
  compression**, so **no decoder is vendored**. New kits MUST match — a `--draco`/meshopt output
  would fail to load (drei `useGLTF` has no decoder configured).
- **Preload is automatic.** `CozyWorld.tsx` calls `preloadHeroModels()` / `preloadCityModels()` /
  `preloadPropModels()`, which iterate `allModelSpecs()` / `allCityModelSpecs()` /
  `allPropModelSpecs()`. New registry rows are preloaded for free.
- **Fallback invariant.** Unknown prop kind → `propVariant()` returns `null` → procedural marker
  (never a hole). Adding a kind just upgrades a marker to real art; nothing breaks if a kit is
  missing.

## 2. The gaps the new kits fill (grounded in the registries)

### A. Props — `assets/propModels.ts` (`PROP_MODELS`, today **7** kinds)
Current: `bench, lamp, tree, fence, bin, hydrant, fountain` (all reused city/furniture GLBs).
Target additions (ledger + `contracts/wave-k.md`: "statues, planters, rocks, flowers, market
stalls, signage"): **`statue, planter, flower, rock, bush, crate, barrel, sign, stall`**.
Each needs a `PROP_MODELS` row **and** a `PROP_KEYWORDS` substring row.

### B. Building null-gaps — `assets/models.ts` `MODEL_REGISTRY` / `PLACE_MODELS`
These render procedurally today because no CC0 match was acquired:
- `MODEL_REGISTRY.garden = null` → a Nature-kit planter-bed / greenhouse cluster.
- `MODEL_REGISTRY.library = null` → a distinct un-used Kenney/Fantasy-Town building.
- `MODEL_REGISTRY.zoo = null` (EM-208) → a fenced enclosure (Nature-kit fence ring + a hero piece).
- `PLACE_MODELS.wild = null` (parks) → a Nature-kit hero tree / tree cluster.

### C. Distinct build-types (EM-217 payoff) — **bigger lift, Phase 2**
`BUILD_TYPES` (`contracts/wave-k.md` §EM-217) surfaces `tavern, market, smithy, school, temple,
clinic, park, granary, well, workshop, garden, house, library, monument, farm`. Most fuzzy-map
via `operationalVariant()` onto ~3 shared shells (commercial-a / civic-n / industrial-g), so a
tavern and a market look identical. Giving each its own GLB means **expanding the `VariantKey`
set** (`worldSpace.ts`) + `MODEL_REGISTRY` keys + their tests — a real code change, not just
registry rows. Deferred to Phase 2 so Phase 1 proves the pipeline first.

## 3. Source kits (CC0, reachability verified)

| Kit | Source | Pull |
|---|---|---|
| **Kenney Nature Kit** | `kenney.nl/assets/nature-kit` | trees, rocks, plants, flowers, bushes, logs, mushrooms, fences — the core nature vocabulary (props A + `garden`/`wild`/`zoo`-fence fills) |
| **Kenney Fantasy Town Kit** *(fountain already used)* | `kenney.nl/assets/fantasy-town-kit` | market stall, signpost, well, banner, lantern, statue, and distinct building shells (`tavern`/`temple`/`library` in Phase 2) |
| **Kenney Furniture Kit** *(bench/bin already used)* | `kenney.nl/assets/furniture-kit` | potted plant → `planter`, floor lamp variants, crates |
| **KayKit City Builder Bits** *(hydrant already used)* | `github.com/KayKit-Game-Assets/KayKit-City-Builder-Bits-1.0` | planter, bin/bench variants, small civic props, statue candidates |
| **Kenney City kits** *(already vendored A–H subset)* | `kenney.nl/assets/city-kit-commercial` etc. | extra building letters for Phase-2 distinct build-types |

All five are CC0 (verify the bundled `License.txt`/`LICENSE.txt` per archive at vendor time, as
the existing entries note). Statues specifically: prefer the Fantasy Town / KayKit statue piece;
fall back to a CC0 Poly Pizza statue (record the exact mirror URL) if neither has one.

## 4. The vendor pipeline (one pass per chosen GLB — matches the existing process)

New kit family → new dir `web/public/models/<kit>/` (e.g. `kenney-nature/`). For each selected asset:

```bash
# 0. node via nvm; tooling is ephemeral via npx (not a saved dep), as at vendor time.
KIT=kenney-nature ; SRC=path/to/extracted/Model.gltf ; OUT=web/public/models/$KIT/<name>.glb

# 1. gltf → glb, embedding textures (the "gltf→glb embedding" step)
npx --yes @gltf-transform/cli copy "$SRC" "$OUT"
# 2. dedup + prune (drop unused accessors/materials/nodes); resample only if animated (props aren't)
npx --yes @gltf-transform/cli dedup "$OUT" "$OUT"
npx --yes @gltf-transform/cli prune "$OUT" "$OUT"
# 3. inspect (sanity: one mesh/material atlas, embedded texture, sane vertex count)
npx --yes @gltf-transform/cli inspect "$OUT"
```

**Do NOT** run `optimize` or pass `--draco`/meshopt — that would require a decoder we don't ship.
Keep payload discipline: total `web/public/models/` is ~3.7 MB today; the Nature kit adds maybe
~0.3–0.6 MB for the dozen pieces we actually pick (extract selectively, don't vendor whole kits).

## 5. Wiring (what changes once GLBs are on disk — no new systems)

**`web/src/components/world3d/assets/propModels.ts`**
- Add a `const KENNEY_NATURE = '/models/kenney-nature';` (+ any new family).
- Extend `PropKind` union + `PROP_MODELS` with the Phase-1 kinds (each `{ url, scale, yOffset }`).
- Add matching `PROP_KEYWORDS` rows (substring → kind); keep order safe (no keyword a substring of
  an earlier one — e.g. put `flower` before `flowerbed`-style aliases).

**`web/src/components/world3d/assets/models.ts`**
- Fill `MODEL_REGISTRY.garden/library/zoo` and `PLACE_MODELS.wild` (Phase 1B) with the new specs;
  leave `null` for anything still without a good CC0 match (honest — don't force a bad fit).

**`ASSET_LICENSES.md`**
- One table row per vendored file: `| Asset | File (+size) | Source | Author | License (CC0 link) | Used for (EM-216) |`.
- Append a short "Wave K (EM-216) — new kits" note paragraph mirroring the existing Wave-K note.

**Scale discipline (load-bearing — tests enforce it):** every `scale` is derived from the GLB's
measured bounding box. Props read at **0.5–1.2u** on the long side (fountain ~3.2u as a plaza
piece); buildings ≤**3.4u** long; place anchors ~15% larger. `models.test.ts` /
`propModels.test.ts` re-measure the vendored files and assert these bounds — set scale by running
the test, reading the measured box, and tuning until green.

## 6. Verification gate

1. `cd web && npm test` — `models.test.ts`, `propModels.test.ts`, `cityModels.test.ts` re-measure
   bounds + assert files exist on disk (this is where scale tuning converges).
2. `cd web && npx tsc -b && npx vite build` — typecheck + production build clean.
3. `design-token-guard` — N/A for registry-only changes (no new DOM), but run it if any panel
   copy changes.
4. **Live render walk:** `./dev`, open the god console → **BUILDERS** group → place each new prop
   kind; confirm it renders as real art (not the procedural marker) and toonifies correctly.
   Spot-check a `garden`/`library`/`zoo` building and a `park` (wild) anchor.

## 7. Phasing + recommendation

- **Phase 1 (recommended first):** props vocabulary `7 → ~15` (Nature + Furniture/KayKit picks)
  **+** fill the four building null-gaps (`garden`, `library`, `zoo`, `wild`). Registry-only code;
  closes the most visible holes (a zoo renders as a box today). ~1 evening; proves the pipeline.
- **Phase 2:** distinct GLBs per `BUILD_TYPE` (tavern/market/smithy/temple/…). Needs `VariantKey`
  expansion + tests; bigger blast radius. Run after Phase 1 lands and looks right.
- **Phase 3 (optional):** re-enable vehicles (EM-169/176) as a prop category now that props exist.

EM-216 flips to **done** when Phase 1 lands (props + null-gaps); Phase 2/3 are tracked as their
own follow-ons so the ledger stays honest.

## 8. Risks / notes

- **Aesthetic fit is the real HITL.** Picking *which* Nature-kit tree/rock/flower reads best is a
  human call; the plan can shortlist, but sign-off is yours.
- **`garden`/`zoo` may stay partly procedural.** There's no clean CC0 "garden plot" or "zoo" GLB;
  a planter-bed cluster / fence-ring composition is the honest fit, or leave `null` and note it.
- **Selective extraction.** Vendor only the dozen pieces we map — not whole kits — to hold the
  payload budget and keep `ASSET_LICENSES.md` auditable.
- **Determinism unaffected.** Props use seeded ids/offsets (EM-218); adding art GLBs changes
  nothing about snapshot/replay byte-equality (EM-155).

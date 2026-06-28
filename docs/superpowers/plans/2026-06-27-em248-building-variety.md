# EM-248 (S5b) — Building-Variety Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kill the ~86% `generic` building monoculture and visible repeat-asset look by completing the variety-pool system (every repeated render path draws from a seeded pool) and vendoring a new wave of CC0 GLBs into the dominant buckets.

**Architecture:** Two halves. **(A) Rewire (Tasks 1–2, zero downloads):** add the one missing pool dimension — `PLACE_POOLS` for place anchors — and give the still-single-model recurring building keys (industrial/civic) pools drawn from already-vendored GLBs, so *every* repeated structure resolves through a deterministic id-seeded pool. **(B) Vendor (Tasks 3–6, network + HITL):** download/repack new CC0 GLBs (poly.pizza/Kenney/KayKit per `docs/em216-kit-acquisition-plan.md`) into the generic pool (dominant), residential/commercial pools, and the remaining single-model props, each footprint-measured and license-recorded. Selection stays the seeded-hash idiom (`Math.floor(hashUnit(id) * pool.length) % pool.length`); slot 0 stays each key's registry default.

**Tech Stack:** TypeScript + React-Three-Fiber, Vitest (fs-backed GLB reader — no WebGL), `@gltf-transform/cli` for repack, Three.js for bounds measurement in tests.

## Global Constraints

- **Scope is pool-widening ONLY.** No `VariantKey` set changes, no `operationalVariant`/`VARIANT_KEYWORDS` routing changes (the per-build-type "Phase 2" distinct-mesh split is explicitly OUT — stays a future item). Registry rows + pool arrays + one new `PLACE_POOLS` map/signature only.
- **CC0 only.** Every vendored file gets one `ASSET_LICENSES.md` table row (`| Asset | File (+size) | Source | Author | License (CC0 link) | Used for |`) whose File cell contains the literal `web/public/models/<dir>/<name>.glb`. Verify the in-archive `License.txt`/`LICENSE.txt` says CC0 *before* vendoring (HITL).
- **No DRACO / meshopt.** Repack only with `@gltf-transform/cli copy` (gltf→glb, embeds textures) then `dedup` then `prune`. **Never** run `optimize` or pass `--draco`/meshopt — no decoder is shipped, the GLB would fail to load.
- **Footprint discipline (test-measured from the real file):** buildings are `>1.2u` and `≤3.4u` on the long side (`max(size.x,size.z)*scale`) and `≤4.2u` tall (`size.y*scale`); place anchors `≤3.4u` long and `≤5.5u` tall; every model sits on the ground: `|min.y*scale + yOffset| < 0.15`. **Scale is not guessed — it is converged by running the footprint test, reading the measured box it prints, and tuning `scale`/`yOffset` until green.** This is the established EM-216 idiom, not a placeholder.
- **Pool invariants (test-enforced):** each pool has ≥2 entries, all distinct urls, and **slot 0 (`pool[0].url`) equals the key's single-spec default** (`MODEL_REGISTRY[key]` / `PROP_MODELS[key]` / `PLACE_MODELS[key]`) so the no-id path agrees with the pool.
- **Determinism / EM-155:** the chosen mesh is a pure function of the entity `id` + the registry code (no snapshot stores it), so appending pool members is replay/fork-safe — the same id recomputes the same mesh wherever the code runs. **S5b is a VISUAL change (more variety), NOT byte-identical-gated** — unlike S1, there is no golden-image freeze here; the gate is the footprint/license/pool tests + the live walk.
- **Payload budget:** total `web/public/models/` is **24 MB today**. The old 28 MB *total* guard was a tight throttle on asset **count** — wrong for a "drastically expand" wave, since these GLBs are lazy-loaded via `useGLTF`/preload (not first-paint bundle weight). Task 6 reframes the guard: raise the total ceiling to **64 MB** (a pure runaway-catch) **and** add a **per-file ≤ 4 MB** sanity cap — which catches the real failure mode (an un-pruned / mis-compressed giant file) without capping how many assets we add. Practice selective extraction regardless (~50–300 KB/file; largest existing file is the rigged villager at ~1.8 MB, so 4 MB is generous headroom for a bigger hero piece while still flagging a bloated dump).
- **Toolchain (from `petridish-test-toolchain` memory):** run FE tests with `cd web && /usr/local/bin/npx vitest run <file>`; typecheck with `cd web && /usr/local/bin/npx tsc -b --force` (NOT `--noEmit` — vacuous under project references). `npx` is broken via nvm; use the absolute path.
- **HITL gates (network + human):** (a) aesthetic GLB selection, (b) in-archive CC0 verification, (c) final live render walk sign-off. Reachability of `kenney.nl` / `github.com/KayKit-Game-Assets` / `poly.pizza` / npm was verified in `docs/em216-kit-acquisition-plan.md`.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `web/src/components/world3d/assets/models.ts` | Building/anchor registry + pools; **new `PLACE_POOLS`**; `allModelSpecs()` includes it; new industrial/civic + vendored generic/house/stall pool members | 1,2,3,4 |
| `web/src/components/world3d/structureModel.ts` | `resolvePlaceModel` gains an `id` param + pool pick (mirrors `resolveStructureModel`) | 1 |
| `web/src/components/world3d/Building.tsx` | Thread `place.id` into `resolvePlaceModel` | 1 |
| `web/src/components/world3d/assets/propModels.ts` | New `PROP_POOLS` entries for the 7 still-single-model props | 5 |
| `web/src/components/world3d/assets/models.test.ts` | New `PLACE_POOLS` describe block; existing `MODEL_POOLS` block auto-covers new building pools; budget bump | 1,2,3,4,6 |
| `web/src/components/world3d/structureModel.test.ts` | `resolvePlaceModel` id determinism/distribution/slot-0 tests | 1 |
| `web/src/components/world3d/assets/propModels.test.ts` | Existing `PROP_POOLS` block auto-covers new prop pools | 5 |
| `ASSET_LICENSES.md` | One row per vendored GLB + an EM-248 wave note | 3,4,5 |
| `web/public/models/poly/`, `web/public/models/poly-props/` | New vendored GLB files | 3,4,5 |

---

### Task 1: `PLACE_POOLS` — place-anchor variety (pure-code, zero downloads)

Place anchors (`work`/`home`/`social`/`governance`/`wild`) are the one repeated render path still single-model — `MODEL_POOLS`/`PROP_POOLS`/`VILLAGER_POOL` exist but there is no `PLACE_POOLS`. Add it, mirroring `MODEL_POOLS` exactly, using only already-vendored on-disk GLBs (every tuple copied verbatim from an already-footprint-validated registry/pool row, so bounds hold by construction).

**Files:**
- Modify: `web/src/components/world3d/assets/models.ts` (add `PLACE_POOLS`, include in `allModelSpecs()`)
- Modify: `web/src/components/world3d/structureModel.ts:81-86` (`resolvePlaceModel` gains `id`)
- Modify: `web/src/components/world3d/Building.tsx:365` (pass `place.id`)
- Test: `web/src/components/world3d/assets/models.test.ts`, `web/src/components/world3d/structureModel.test.ts`

**Interfaces:**
- Consumes: `PlaceKind` (`web/src/types/index.ts:5`), `ModelSpec` + `PLACE_MODELS` (`models.ts`), `hashUnit(seed: string): number` (`worldSpace.ts:676`), `Place.id` (`types/index.ts:8`).
- Produces: `PLACE_POOLS: Partial<Record<PlaceKind, ModelSpec[]>>`; `resolvePlaceModel(kind: string, id?: string): ModelSpec | null` (id-seeded pool pick; back-compatible — `id` optional, no-id returns slot 0 = `PLACE_MODELS` default).

- [ ] **Step 1: Write the failing test (structureModel resolvePlaceModel pool behavior)**

Add to `web/src/components/world3d/structureModel.test.ts`:

```typescript
import { PLACE_MODELS, PLACE_POOLS } from './assets/models';

describe('resolvePlaceModel (EM-248 place-anchor variety)', () => {
  it('without an id returns the single PLACE_MODELS default (pool slot 0)', () => {
    for (const kind of Object.keys(PLACE_POOLS)) {
      expect(resolvePlaceModel(kind)).toBe(PLACE_MODELS[kind as keyof typeof PLACE_MODELS]);
    }
  });

  it('with an id picks a stable, distributed pool member', () => {
    for (const [kind, pool] of Object.entries(PLACE_POOLS)) {
      if (!pool) continue;
      const ids = Array.from({ length: 24 }, (_, i) => `place_${kind}_${i}`);
      const picks = ids.map((id) => resolvePlaceModel(kind, id));
      for (const p of picks) expect(pool, kind).toContain(p);
      expect(resolvePlaceModel(kind, ids[0])).toBe(resolvePlaceModel(kind, ids[0])); // deterministic
      expect(new Set(picks.map((s) => s!.url)).size, kind).toBeGreaterThan(1); // distributes
    }
  });

  it('unknown kinds still return null (procedural fallback intact)', () => {
    expect(resolvePlaceModel('not-a-place', 'x')).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/structureModel.test.ts`
Expected: FAIL — `PLACE_POOLS` is not exported from `models.ts`, and `resolvePlaceModel` ignores a second arg.

- [ ] **Step 3: Add `PLACE_POOLS` to `models.ts`**

Insert after `MODEL_POOLS` (after line 262), and update `allModelSpecs()`:

```typescript
/**
 * EM-248 (S5b) — per-anchor VARIETY pools for PLACE anchors, mirroring
 * MODEL_POOLS. A place kind with a pool renders one of several distinct GLBs,
 * picked deterministically from the place id (resolvePlaceModel) so repeated
 * homes/workplaces aren't clones — stable across frame/reload/fork (EM-155).
 * Every member is a (url, scale, yOffset) tuple copied verbatim from an already
 * footprint-validated MODEL_REGISTRY / PLACE_MODELS / MODEL_POOLS row, so the
 * anchor footprint (≤3.4u long / ≤5.5u tall / grounded) holds by construction.
 * Slot 0 is the PLACE_MODELS default so the no-id path agrees with the pool.
 */
export const PLACE_POOLS: Partial<Record<PlaceKind, ModelSpec[]>> = {
  home: [
    { url: `${KENNEY_CITY}/suburban-b.glb`, scale: 1.8, yOffset: 0 },  // slot 0 = PLACE_MODELS.home
    { url: `${KENNEY_CITY}/suburban-a.glb`, scale: 2.3, yOffset: 0 },
    { url: `${POLY}/house-modern.glb`, scale: 3.3, yOffset: 0 },
    { url: `${POLY}/house-fantasy.glb`, scale: 1.1, yOffset: 0 },
  ],
  work: [
    { url: `${KENNEY_CITY}/commercial-e.glb`, scale: 2.0, yOffset: 0 }, // slot 0 = PLACE_MODELS.work
    { url: `${KENNEY_CITY}/commercial-a.glb`, scale: 2.6, yOffset: 0 },
    { url: `${POLY}/bank.glb`, scale: 0.87, yOffset: 0.27 },
    { url: `${POLY}/office-tower.glb`, scale: 0.616, yOffset: 0.008 },
  ],
  social: [
    { url: `${KENNEY_FANTASY_TOWN}/fountain.glb`, scale: 1.6, yOffset: 0 }, // slot 0 = PLACE_MODELS.social
    { url: `${POLY}/bathhouse.glb`, scale: 0.32, yOffset: 0.32 },
    { url: `${POLY}/market.glb`, scale: 1.4, yOffset: 0 },
  ],
  governance: [
    { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 }, // slot 0 = PLACE_MODELS.governance
    { url: `${POLY}/library.glb`, scale: 2.35, yOffset: 0 },
    { url: `${POLY}/church.glb`, scale: 3.644, yOffset: 0.187 },
    { url: `${POLY}/bank.glb`, scale: 0.87, yOffset: 0.27 },
  ],
  wild: [
    { url: `${POLY}/park.glb`, scale: 2.3, yOffset: 0 }, // slot 0 = PLACE_MODELS.wild
    { url: `${POLY}/garden.glb`, scale: 1.65, yOffset: 0 },
  ],
};
```

Then change `allModelSpecs()` (line 282-288) to include the new pools:

```typescript
  const specs = [
    ...Object.values(MODEL_REGISTRY),
    ...Object.values(PLACE_MODELS),
    ...Object.values(CHARACTER_MODELS),
    ...Object.values(MODEL_POOLS).flat(),
    ...Object.values(PLACE_POOLS).flat(),
    ...VILLAGER_POOL,
  ].filter((s): s is ModelSpec => s != null);
```

- [ ] **Step 4: Add the id-seeded pick to `resolvePlaceModel` in `structureModel.ts`**

Update the import (line 26) and the function (lines 81-86):

```typescript
import { MODEL_REGISTRY, MODEL_POOLS, PLACE_MODELS, PLACE_POOLS, type ModelSpec } from './assets/models';
```

```typescript
/**
 * Resolve a place-anchor GLB by place kind (Building.tsx). Unknown kinds (or
 * registry nulls — none today) return null. EM-248: when the kind has a
 * PLACE_POOLS pool AND an `id` is supplied, the GLB is picked deterministically
 * from the id (so repeated homes/workplaces aren't clones), stable across
 * frame/reload/fork (EM-155). Without an id (or pool), the single PLACE_MODELS
 * spec stands, which is pool slot 0 by construction.
 */
export function resolvePlaceModel(kind: string, id?: string): ModelSpec | null {
  const pool = Object.prototype.hasOwnProperty.call(PLACE_POOLS, kind)
    ? PLACE_POOLS[kind as keyof typeof PLACE_POOLS]
    : undefined;
  if (pool && pool.length > 0 && id) {
    const idx = Math.floor(hashUnit(id) * pool.length) % pool.length;
    return pool[idx];
  }
  const spec = Object.prototype.hasOwnProperty.call(PLACE_MODELS, kind)
    ? PLACE_MODELS[kind as keyof typeof PLACE_MODELS]
    : null;
  return spec ?? null;
}
```

- [ ] **Step 5: Run the structureModel test to verify it passes**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/structureModel.test.ts`
Expected: PASS (all three new cases + the existing suite).

- [ ] **Step 6: Write the failing `PLACE_POOLS` footprint/shape test in `models.test.ts`**

Add after the `MODEL_POOLS` describe block (after line 277), and import `PLACE_POOLS`:

```typescript
// (add PLACE_POOLS to the existing import from './models')

describe('PLACE_POOLS (EM-248 anchor variety)', () => {
  const poolEntries = Object.entries(PLACE_POOLS) as Array<[PlaceKind, ModelSpec[]]>;

  it('each pool has ≥2 distinct GLBs and includes its PLACE_MODELS default at slot 0', () => {
    expect(poolEntries.length).toBeGreaterThan(0);
    for (const [kind, pool] of poolEntries) {
      expect(pool.length, kind).toBeGreaterThanOrEqual(2);
      expect(new Set(pool.map((s) => s.url)).size, `${kind} dup urls`).toBe(pool.length);
      expect(pool[0].url, `${kind} slot 0`).toBe(PLACE_MODELS[kind]!.url);
    }
  });

  it('every pool member fits the anchor footprint and sits on the ground', () => {
    for (const [kind, pool] of poolEntries) {
      for (const spec of pool) {
        const { size, min } = glbBounds(readGlbJson(diskPath(spec)));
        expect(Math.max(size.x, size.z) * spec.scale, `${kind} ${spec.url} xz`).toBeLessThanOrEqual(3.4);
        expect(size.y * spec.scale, `${kind} ${spec.url} y`).toBeLessThanOrEqual(5.5);
        expect(Math.abs(min.y * spec.scale + spec.yOffset), `${kind} ${spec.url} ground`).toBeLessThan(0.15);
      }
    }
  });
});
```

- [ ] **Step 7: Run the models test to verify it passes**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: PASS — every reused tuple is already footprint-validated, so bounds hold; the license/orphan checks still pass because all urls were already referenced (de-duped in `allModelSpecs()`).

- [ ] **Step 8: Thread `place.id` into the renderer call site**

In `web/src/components/world3d/Building.tsx`, change line 365:

```typescript
  const spec = resolvePlaceModel(place.kind, place.id);
```

- [ ] **Step 9: Typecheck**

Run: `cd web && /usr/local/bin/npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 10: Commit**

```bash
git add web/src/components/world3d/assets/models.ts web/src/components/world3d/structureModel.ts web/src/components/world3d/Building.tsx web/src/components/world3d/assets/models.test.ts web/src/components/world3d/structureModel.test.ts
git commit -m "feat(EM-248): PLACE_POOLS — id-seeded place-anchor variety (S5b rewire)"
```

---

### Task 2: Pools for the remaining single-model recurring building keys (pure-code, zero downloads)

Residential (`house`) and commercial (`stall`) already have pools; industrial (`farm`/`workshop`) and civic (`library`/`clocktower`) are still single-model. Give each a pool from already-vendored GLBs so every zone-representative building key varies. Pure data — the existing `MODEL_POOLS` describe block validates them automatically.

**Files:**
- Modify: `web/src/components/world3d/assets/models.ts` (`MODEL_POOLS` += `farm`,`workshop`,`library`,`clocktower`)
- Test: `web/src/components/world3d/assets/models.test.ts` (existing `MODEL_POOLS` block auto-covers)

**Interfaces:**
- Consumes: `MODEL_REGISTRY` defaults (slot 0), existing validated tuples.
- Produces: four new `MODEL_POOLS` entries (industrial + civic variety). `resolveStructureModel` already consumes `MODEL_POOLS` with no change.

- [ ] **Step 1: Add the four pools to `MODEL_POOLS` in `models.ts`**

Inside the `MODEL_POOLS` object (before the closing `};` at line 262), add:

```typescript
  // EM-248 (S5b) — INDUSTRIAL variety. Slot 0 = MODEL_REGISTRY default; members
  // are verbatim already-validated tuples (warehouse/factory/silo/windmill/port).
  farm: [
    { url: `${KENNEY_CITY}/industrial-h.glb`, scale: 2.4, yOffset: 0 },  // slot 0 = MODEL_REGISTRY.farm
    { url: `${KENNEY_CITY}/industrial-g.glb`, scale: 2.0, yOffset: 0 },
    { url: `${POLY}/granary.glb`, scale: 0.45, yOffset: 0 },
    { url: `${POLY}/windmill.glb`, scale: 0.35, yOffset: 0.012 },
  ],
  workshop: [
    { url: `${KENNEY_CITY}/industrial-g.glb`, scale: 2.0, yOffset: 0 },  // slot 0 = MODEL_REGISTRY.workshop
    { url: `${KENNEY_CITY}/industrial-h.glb`, scale: 2.4, yOffset: 0 },
    { url: `${POLY}/smithy.glb`, scale: 0.8, yOffset: 0 },
    { url: `${POLY}/dock.glb`, scale: 1.91, yOffset: 0.8 },
  ],
  // EM-248 (S5b) — CIVIC variety. Slot 0 = MODEL_REGISTRY default; members are
  // verbatim already-validated civic/landmark tuples.
  library: [
    { url: `${POLY}/library.glb`, scale: 2.35, yOffset: 0 },  // slot 0 = MODEL_REGISTRY.library
    { url: `${POLY}/church.glb`, scale: 3.644, yOffset: 0.187 },
    { url: `${POLY}/bell-tower.glb`, scale: 0.84, yOffset: 0 },
    { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 },
  ],
  clocktower: [
    { url: `${KENNEY_CITY}/civic-n.glb`, scale: 1.45, yOffset: 0 },  // slot 0 = MODEL_REGISTRY.clocktower
    { url: `${POLY}/bell-tower.glb`, scale: 0.84, yOffset: 0 },
    { url: `${POLY}/lighthouse.glb`, scale: 0.28, yOffset: 0.03 },
    { url: `${POLY}/office-tower.glb`, scale: 0.616, yOffset: 0.008 },
  ],
```

- [ ] **Step 2: Run the models test to verify the new pools pass**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: PASS — the `MODEL_POOLS` block asserts ≥2 distinct, slot 0 = `MODEL_REGISTRY[variant]`, and every member fits the footprint. All tuples are verbatim from validated rows; slot 0 of each equals its registry default (`farm`=industrial-h, `workshop`=industrial-g, `library`=poly/library, `clocktower`=civic-n).

- [ ] **Step 3: Verify variety actually engages (resolveStructureModel distribution)**

Add to `web/src/components/world3d/structureModel.test.ts`:

```typescript
import { MODEL_POOLS } from './assets/models';

describe('resolveStructureModel covers every recurring building key (EM-248)', () => {
  it.each(['farm', 'workshop', 'library', 'clocktower'] as const)(
    '%s distributes across its pool by id', (kind) => {
      const pool = MODEL_POOLS[kind]!;
      const picks = Array.from({ length: 24 }, (_, i) =>
        resolveStructureModel(kind, `b_${kind}_${i}`).spec!.url);
      for (const u of picks) expect(pool.map((s) => s.url)).toContain(u);
      expect(new Set(picks).size, kind).toBeGreaterThan(1);
    },
  );
});
```

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/structureModel.test.ts`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/world3d/assets/models.ts web/src/components/world3d/structureModel.test.ts
git commit -m "feat(EM-248): industrial + civic building pools from vendored GLBs (S5b rewire)"
```

> **Rewire half (Tasks 1–2) ships here** — a real, zero-download variety win: every repeated render path (buildings via `MODEL_POOLS`, anchors via `PLACE_POOLS`, props via `PROP_POOLS`, agents via `VILLAGER_POOL`) now draws from a seeded pool. Tasks 3–6 add new art on top.

---

### Task 3: Vendor + wire a new generic-pool wave (dominant 86% bucket) — network + HITL

The `generic` catch-all is where ~86% of agent-authored buildings land (abstract civic/economic kinds). Even with 24 members, a large city repeats each silhouette. Add ~10 **new, visually distinct** CC0 building GLBs to widen it. This is the single highest-leverage vendoring slot.

**Files:**
- Create: `web/public/models/poly/<new>.glb` (×~10)
- Modify: `web/src/components/world3d/assets/models.ts` (`MODEL_POOLS.generic` += new members)
- Modify: `ASSET_LICENSES.md` (one row per file + EM-248 wave note)
- Test: `web/src/components/world3d/assets/models.test.ts`

**Interfaces:**
- Consumes: the `@gltf-transform` pipeline, the `MODEL_POOLS` footprint/license tests as the convergence oracle.
- Produces: ~10 new `MODEL_POOLS.generic` entries (distinct urls; existing slot 0 = `commercial-g` unchanged).

**Candidate shortlist (HITL — pick the visually distinct ~10; all CC0, verify in-archive):** mid-rise apartment block, hotel, hospital, fire station, police station, town hall variant, museum, shopping arcade, parking structure, gas/charging station, cinema, warehouse variant, clock-faced tower, pavilion. Sources per `docs/em216-kit-acquisition-plan.md` §3: Kenney City kits (more commercial/industrial letters), Kenney Fantasy Town shells, KayKit City Builder Bits, poly.pizza CC0 (Quaternius / CreativeTrio / Kay Lousberg mirrors). Prefer silhouettes that differ from the existing 24 (avoid more near-identical commercial blocks).

- [ ] **Step 1: Write the failing test — declare the intended members first**

Append the chosen new members to `MODEL_POOLS.generic` in `models.ts` with a **provisional** scale of `1` (will be tuned), e.g.:

```typescript
    // EM-248 (S5b) — new CC0 generic-bucket silhouettes (poly.pizza/Kenney CC0).
    { url: `${POLY}/apartment-block.glb`, scale: 1, yOffset: 0 },
    { url: `${POLY}/hotel.glb`, scale: 1, yOffset: 0 },
    { url: `${POLY}/hospital.glb`, scale: 1, yOffset: 0 },
    // …the rest of the chosen ~10…
```

- [ ] **Step 2: Run the models test to verify it fails**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: FAIL — `missing file: …/apartment-block.glb` (existence check) and/or footprint out of bounds, and/or `ASSET_LICENSES.md is missing /models/poly/apartment-block.glb`.

- [ ] **Step 3: Vendor each chosen GLB (repack, no compression)**

For each file (HITL: download the chosen CC0 source first; confirm its `License.txt` is CC0):

```bash
KIT=poly ; SRC=path/to/extracted/Model.gltf ; OUT=web/public/models/$KIT/apartment-block.glb
/usr/local/bin/npx --yes @gltf-transform/cli copy "$SRC" "$OUT"
/usr/local/bin/npx --yes @gltf-transform/cli dedup "$OUT" "$OUT"
/usr/local/bin/npx --yes @gltf-transform/cli prune "$OUT" "$OUT"
/usr/local/bin/npx --yes @gltf-transform/cli inspect "$OUT"   # sanity: 1 mesh/atlas, embedded texture, sane verts
```

Do NOT run `optimize` / `--draco` / meshopt.

- [ ] **Step 4: Converge each scale against the footprint test**

Re-run the test; for each new member read the measured `xz`/`y` it reports and set `scale` so `max(x,z)*scale ∈ (1.2, 3.4]` and `y*scale ≤ 4.2`; set `yOffset` so `|min.y*scale + yOffset| < 0.15` (lift origin-centered models). Repeat until green.

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: footprint + ground checks PASS for each new member.

- [ ] **Step 5: Add a license row per file + the EM-248 wave note**

In `ASSET_LICENSES.md`, add one row per file (File cell must literally contain `web/public/models/poly/apartment-block.glb`), e.g.:

```markdown
| Quaternius — Apartment Block | `web/public/models/poly/apartment-block.glb` (~NNN KB) | [poly.pizza](https://poly.pizza/m/<id>) | <Author> | [CC0](https://creativecommons.org/publicdomain/zero/1.0/) | `MODEL_POOLS.generic` variant (EM-248 S5b) |
```

Add a short note paragraph: `**EM-248 (S5b) — generic-bucket variety:** new CC0 building GLBs widening the dominant generic pool; all CC0, lazy-loaded.`

- [ ] **Step 6: Run the full models test (footprint + license + orphan + budget)**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: PASS, **except possibly the payload budget** — if the old 28 MB total guard fails, apply the Task 6 guard change now (total → 64 MB runaway-catch + per-file ≤ 4 MB cap), then re-run.

- [ ] **Step 7: Commit**

```bash
git add web/public/models/poly/ web/src/components/world3d/assets/models.ts ASSET_LICENSES.md
git commit -m "feat(EM-248): vendor new CC0 generic-bucket building GLBs (S5b)"
```

---

### Task 4: Vendor + wire residential (`house`) + commercial (`stall`) variety — network + HITL

Same pipeline as Task 3, aimed at the next-most-repeated buckets. Add ~4 new homes to `MODEL_POOLS.house` and ~3 new shopfronts to `MODEL_POOLS.stall`.

**Files:**
- Create: `web/public/models/poly/<new>.glb` (×~7)
- Modify: `web/src/components/world3d/assets/models.ts` (`MODEL_POOLS.house`, `MODEL_POOLS.stall`)
- Modify: `ASSET_LICENSES.md`
- Test: `web/src/components/world3d/assets/models.test.ts`

**Candidate shortlist (HITL, CC0):** residential — row-house terrace, bungalow, A-frame, apartment walk-up, duplex; commercial — corner store, café/bistro, boutique, pharmacy, kiosk-row, diner. (Distinct from the existing house=13 / stall=7 members.)

- [ ] **Step 1: Declare new members at provisional `scale: 1`**

Append to `MODEL_POOLS.house` and `MODEL_POOLS.stall` in `models.ts` (slot 0 of each stays its current default — append only):

```typescript
  // …inside MODEL_POOLS.house:
    { url: `${POLY}/house-terrace.glb`, scale: 1, yOffset: 0 },   // EM-248
    { url: `${POLY}/house-bungalow.glb`, scale: 1, yOffset: 0 },  // EM-248
    // …
  // …inside MODEL_POOLS.stall:
    { url: `${POLY}/shop-corner.glb`, scale: 1, yOffset: 0 },     // EM-248
    // …
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: FAIL — missing files / footprint / license.

- [ ] **Step 3: Vendor each GLB**

Same repack pipeline as Task 3 Step 3 (copy → dedup → prune → inspect; no compression; verify CC0).

- [ ] **Step 4: Converge scales against the footprint test**

Same as Task 3 Step 4 until green.

- [ ] **Step 5: Add license rows**

One row per file in `ASSET_LICENSES.md` (`Used for`: `MODEL_POOLS.house`/`MODEL_POOLS.stall` variant (EM-248 S5b)).

- [ ] **Step 6: Run the full models test**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/models.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/public/models/poly/ web/src/components/world3d/assets/models.ts ASSET_LICENSES.md
git commit -m "feat(EM-248): vendor new CC0 residential + commercial GLBs (S5b)"
```

---

### Task 5: Vendor + wire pools for the 7 still-single-model props — network + HITL

`PROP_POOLS` covers `tree/rock/bush/flower/bench/lamp/statue/planter`. The other seven prop kinds (`fence`, `bin`, `hydrant`, `fountain`, `sign`, `crate`, `barrel`) are still single-model. Give each a ≥2-member pool (slot 0 = current `PROP_MODELS` default) so scattered props stop reading as clones.

**Files:**
- Create: `web/public/models/poly-props/<new>.glb` (×~7–10)
- Modify: `web/src/components/world3d/assets/propModels.ts` (`PROP_POOLS` += the 7 kinds)
- Modify: `ASSET_LICENSES.md`
- Test: `web/src/components/world3d/assets/propModels.test.ts` (existing `PROP_POOLS` block auto-covers)

**Interfaces:**
- Consumes: `PROP_MODELS` defaults (slot 0), the `POLY_PROPS` dir constant (`propModels.ts:35`), `propModel`/`PROP_POOLS` test invariants.
- Produces: `PROP_POOLS` entries for `fence`,`bin`,`hydrant`,`fountain`,`sign`,`crate`,`barrel`.

**Candidate shortlist (HITL, CC0):** fence — stone wall, iron railing, wood rail; bin — recycling bin, dumpster; hydrant — water pump, standpipe; fountain — tiered fountain, birdbath, wall fountain; sign — directional sign, billboard, A-board; crate — wooden box stack, pallet; barrel — metal drum, wine cask. (Prop street-furniture size — see propModels.ts scale comments, ~0.5–1.5u longest dim.)

- [ ] **Step 1: Declare the new pools at provisional `scale: 1`**

Add to `PROP_POOLS` in `propModels.ts` (slot 0 = `PROP_MODELS.<kind>` so the no-id path agrees):

```typescript
  fence: [
    PROP_MODELS.fence, // slot 0
    { url: `${POLY_PROPS}/fence-stone.glb`, scale: 1, yOffset: 0 }, // EM-248
  ],
  bin: [
    PROP_MODELS.bin,
    { url: `${POLY_PROPS}/bin-recycle.glb`, scale: 1, yOffset: 0 },
  ],
  hydrant: [
    PROP_MODELS.hydrant,
    { url: `${POLY_PROPS}/hydrant-pump.glb`, scale: 1, yOffset: 0 },
  ],
  fountain: [
    PROP_MODELS.fountain,
    { url: `${POLY_PROPS}/fountain-tiered.glb`, scale: 1, yOffset: 0 },
  ],
  sign: [
    PROP_MODELS.sign,
    { url: `${POLY_PROPS}/sign-directional.glb`, scale: 1, yOffset: 0 },
  ],
  crate: [
    PROP_MODELS.crate,
    { url: `${POLY_PROPS}/crate-stack.glb`, scale: 1, yOffset: 0 },
  ],
  barrel: [
    PROP_MODELS.barrel,
    { url: `${POLY_PROPS}/barrel-drum.glb`, scale: 1, yOffset: 0 },
  ],
```

- [ ] **Step 2: Run the prop test to verify it fails**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/propModels.test.ts`
Expected: FAIL — `missing pool GLB` and `ASSET_LICENSES.md is missing …`.

- [ ] **Step 3: Vendor each prop GLB**

Same repack pipeline (copy → dedup → prune → inspect; no compression; verify CC0). Output under `web/public/models/poly-props/`.

- [ ] **Step 4: Converge scales (prop sizing)**

`propModels.test.ts` checks existence + slot-0 + distribution + ground, not strict footprint bounds, but keep props at street-furniture size — set `scale` from the `inspect` longest-dim so the largest dimension reads ~0.5–1.5u (fountain ~3.2u as a plaza piece), and `yOffset` to seat origin-centered models on the ground. Re-run until green.

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/propModels.test.ts`
Expected: PASS (`PROP_POOLS` block: each pool ≥2 distinct, slot 0 = default, distributes, exists on disk, licensed).

- [ ] **Step 5: Add license rows**

One row per file (`Used for`: `PROP_POOLS.<kind>` variant (EM-248 S5b)).

- [ ] **Step 6: Run the full prop test**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/assets/propModels.test.ts`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add web/public/models/poly-props/ web/src/components/world3d/assets/propModels.ts ASSET_LICENSES.md
git commit -m "feat(EM-248): vendor CC0 prop variety pools (fence/bin/hydrant/fountain/sign/crate/barrel) (S5b)"
```

---

### Task 6: Payload-guard reframe, full-suite gate, and live render walk (HITL sign-off)

**Files:**
- Modify: `web/src/components/world3d/assets/models.test.ts:187-198` (payload guard → runaway-catch + per-file cap)
- Verify: full FE suite + typecheck; live walk.

- [ ] **Step 1: Reframe the payload guard (if not already done in Task 3)**

The old guard throttled asset *count* via a tight total. Replace it with a generous total runaway-catch **plus** a per-file cap that targets the real failure mode (a bloated un-pruned/mis-compressed file). In `models.test.ts`, replace the single budget test with:

```typescript
  // EM-248: the payload guard is a runaway-catch, NOT a count throttle. GLBs are
  // LAZY-loaded via drei useGLTF/preload — they are NOT first-paint bundle weight,
  // so adding MORE variety is free at load time. The total ceiling only catches an
  // accidental whole-kit dump; the per-file cap catches the real failure (a file
  // vendored without dedup/prune, or with the wrong compression). 15→28 (EM-216e)
  // → 64 MB total + 4 MB/file (EM-248).
  it('no single vendored GLB exceeds the 4 MB per-file sanity cap', () => {
    for (const s of specs) {
      const bytes = readFileSync(diskPath(s)).byteLength;
      expect(bytes, `${s.url} is ${(bytes / 1024 / 1024).toFixed(1)} MB — repack (dedup/prune, no compression)`)
        .toBeLessThanOrEqual(4 * 1024 * 1024);
    }
  });

  it('total vendored payload stays within the 64 MB runaway-catch', () => {
    const total = specs.reduce((sum, s) => sum + readFileSync(diskPath(s)).byteLength, 0);
    expect(total).toBeLessThanOrEqual(64 * 1024 * 1024);
  });
```

- [ ] **Step 2: Run the full frontend suite**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d`
Expected: PASS — all world3d files green (models, propModels, structureModel, cityModels, cityLayout, etc.), 0 regressions.

- [ ] **Step 3: Typecheck the whole project**

Run: `cd web && /usr/local/bin/npx tsc -b --force`
Expected: exit 0.

- [ ] **Step 4: Live render walk (HITL — visual sign-off)**

Start the stack (`./dev`), open the 3-D city. Confirm: (a) the generic-building rows no longer read as repeated dark towers; (b) homes/workplaces/anchors vary; (c) new props render as real art (not procedural markers) and toonify correctly; (d) the city is visually richer with no floating/buried/oversized models. Use the god console **BUILDERS** group to spot-place each new prop kind. This is the acceptance gate the spec names ("walking the city, building/prop repetition is visibly reduced; the generic monoculture is gone").

- [ ] **Step 5: Final commit (if the guard change wasn't already committed)**

```bash
git add web/src/components/world3d/assets/models.test.ts
git commit -m "test(EM-248): reframe asset payload guard — 64 MB runaway-catch + 4 MB/file cap (S5b)"
```

---

## Self-Review

**1. Spec coverage (`…s5-assets-meshing-design.md` §S5b):**
- "Vendor more CC0 GLBs… generic pool first, then per-zone variety, then props" → Tasks 3 (generic), 2+4 (per-zone: industrial/civic pools + residential/commercial), 5 (props). ✅
- "Expand the registries / widen variant pools (`models.ts`/`propModels.ts`/generic pool)" → Tasks 1–5. ✅
- "CC0 discipline — `ASSET_LICENSES.md` row per file; verify in-archive" → Global Constraints + each vendor task Step 5; HITL gate. ✅
- "Determinism — seeded per id, EM-155-safe" → Global Constraints (pure-fn-of-id, append-safe) + every pool uses the existing `hashUnit` idiom. ✅
- "S5b acceptance: repetition visibly reduced, monoculture gone, all CC0, deterministic" → Task 6 live walk + test gates. ✅
- Decided scope: pool-widening only (no VariantKey/Phase-2 split) → enforced in Global Constraints. ✅

**2. Placeholder scan:** The `scale: 1` values in Tasks 3–5 are explicitly **provisional, converged by the footprint test** (the established EM-216 measure-and-tune idiom), not unfilled placeholders — the convergence procedure is exact. New GLB filenames in vendor tasks are illustrative of the HITL pick; the pipeline, tests, and license rows are exact. No "TBD"/"handle errors"/"similar to" placeholders. ✅

**3. Type consistency:** `resolvePlaceModel(kind, id?)` matches its new test usage and the `Building.tsx` call site; `PLACE_POOLS: Partial<Record<PlaceKind, ModelSpec[]>>` matches `MODEL_POOLS`'s shape and the new test's `Object.entries`; `hashUnit`/slot-0/`Math.floor(...)%len` idiom is identical across `resolveStructureModel`, `propModel`, and the new `resolvePlaceModel`; `allModelSpecs()` includes `PLACE_POOLS` so license/orphan/disk checks cover anchor-pool members. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-27-em248-building-variety.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks. Note: Tasks 1–2 are pure-code (no network/HITL) and can run fully autonomously; Tasks 3–5 each need network access + your aesthetic asset pick + in-archive CC0 verification, and Task 6 needs your live-walk sign-off.

**2. Inline Execution** — execute in this session with checkpoints (using executing-plans).

**Which approach?**

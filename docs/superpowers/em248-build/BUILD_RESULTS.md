# EM-248 (S5b — Building Variety) — Build Results

**Status: ✅ CODE-COMPLETE on branch `feat/em248-building-variety` (Tasks 1–5 + payload-guard reframe). Two QA gates PASS. The ONLY remaining step is the user's live-walk visual sign-off (plan Task 6).**
Built in two phases: (1) the **pure-code rewire** (Tasks 1–2), then — after the user lifted the "stop before vendoring" hold and explicitly approved vendoring — (2) the **vendoring half** (Tasks 3–5: ~29 new CC0 GLBs). Not merged, no PR (no instruction). See the "Vendoring half" section at the bottom for Tasks 3–5.

> History note: Tasks 1–2 first shipped as a "stop before vendoring" slice per the user's instruction; the user then approved vendoring, and Tasks 3–5 landed on the same branch.

Orchestrated build (subagents via Agent tool — no Workflow mode, no ultracode reminder this turn): one frontend implementation agent, lead-run wave gate, mandatory QE gate. Not merged, not PR'd (no instruction to).

## What shipped (the rewire)

After EM-216's pools, the one repeated render path with **no** variety pool was the **place anchors**, and several recurring building keys were still single-model. This slice closes both, so **every repeated structure now resolves through a deterministic, id-seeded pool** (buildings via `MODEL_POOLS`, anchors via `PLACE_POOLS`, props via `PROP_POOLS`, agents via `VILLAGER_POOL`). Zero downloads — every new pool member is a tuple copied verbatim from an already-footprint-validated registry row.

- **`web/src/components/world3d/assets/models.ts`** — new export `PLACE_POOLS: Partial<Record<PlaceKind, ModelSpec[]>>` (home/work/social/governance/wild); 4 new `MODEL_POOLS` entries (`farm`/`workshop` = industrial, `library`/`clocktower` = civic); `allModelSpecs()` now flattens `PLACE_POOLS` (so anchor-pool members get disk/license/footprint/ground coverage).
- **`web/src/components/world3d/structureModel.ts`** — `resolvePlaceModel(kind, id?)` gains the id-seeded pool pick (`Math.floor(hashUnit(id) * pool.length) % pool.length`, own-property-guarded), mirroring `resolveStructureModel`. No-id/no-pool path unchanged (returns slot 0 = `PLACE_MODELS` default).
- **`web/src/components/world3d/Building.tsx`** — threads `place.id` into `resolvePlaceModel` (Task 1 is inert otherwise).
- **Tests** — `models.test.ts` (+`PLACE_POOLS` shape + footprint block), `structureModel.test.ts` (+`resolvePlaceModel` determinism/distribution + recurring-key distribution for the 4 new pools).

Slot 0 of every new pool equals its registry default (`farm`=industrial-h, `workshop`=industrial-g, `library`=poly/library, `clocktower`=civic-n; anchors = their `PLACE_MODELS` default), so the no-id path agrees with the pool and id-hash picks are replay-stable (EM-155).

## Gates (lead-run AND independently re-run by QE)

| Gate | Baseline (EM-239) | Final | Result |
|---|---|---|---|
| `models.test.ts` | — | **129** | ✅ |
| `structureModel.test.ts` | — | **69** | ✅ |
| Full `world3d` suite | 534 | **543** (+9) | ✅ 24 files, 0 regressions |
| `tsc -b --force` | exit 0 | **exit 0** | ✅ |

## Verification — adversarial QE (this is where the value was)

QE independently re-ran all four gates and verified the *claims* behind the green, not just the count:
- **Determinism / EM-155: ✅** `resolvePlaceModel` pick is a pure function of `id` via `hashUnit` (pure FNV-1a, grep-confirmed no `Math.random`/`Date`/mutable state); same id → same object ref; no-id → default.
- **Slot-0 invariant: ✅** all 9 new pools have `pool[0]` matching the registry default on **url AND scale/yOffset**; all urls distinct.
- **Tests have teeth (anti-vacuous): ✅** the `Set(picks).size > 1` distribution assertions would fail if the impl returned only slot 0.
- **Call-site wiring: ✅** `Building.tsx` passes `place.id` (`Place.id` is a required string; tsc green).
- **Footprint/license integrity: ✅** `allModelSpecs()` includes `PLACE_POOLS`; all members are already-validated reused tuples, so exists-on-disk/footprint/license/orphan checks stay green.
- **Scope: ✅** only the 5 source/test files + docs; NO `.glb`, NO `ASSET_LICENSES.md`, nothing from Task 3+.

**`qa-report.json`:** status PASS, 5/5 across contract/correctness/security/coverage/scope, 0 blockers, `gate_decision.proceed=true`.

## Render / reality gate stance

No new imagery, no UI/styling/className change — this is data-pipeline logic in `.ts` registry files. So `nano-banana`/`frontend-design`/`design-token-guard`/`render-sanity`/`ux-review` are N/A as *change* gates for this slice (recorded in `MISSION_SKILLS.md`). The visual payoff (anchors/buildings visibly varying) is real but its sign-off is the **live render walk in plan Task 6**, which is POST-vendoring and out of this slice.

## Handoff / what's next

1. **Tasks 3–5 (vendoring)** — download/repack new CC0 GLBs into the generic (dominant), residential/commercial, and remaining-prop buckets. Needs network + your aesthetic asset picks + in-archive CC0 verification. Scales converge against the footprint test (the EM-216 measure-and-tune idiom).
2. **Task 6** — payload-guard reframe (28 MB total → 64 MB runaway-catch + 4 MB/file cap) + full suite + **live render walk sign-off** (the visual acceptance gate).
3. **Not committed to main / no PR** — slice lives on `feat/em248-building-variety`, awaiting your call.
4. **Ledger** — EM-248 stays `open` (slice is partial); flip to `done` only when the vendoring + live walk land.

## Definition of Done (for this slice)
- [x] Implementation agent passed; QE gate PASS (`proceed=true`)
- [x] Wave gate green, 0 regressions (543 vs 534)
- [x] Contract = plan's exact code; zero body/tuple/test deviations (only correct import-merge adjustments)
- [x] Determinism (EM-155) + slot-0 + tests-have-teeth independently verified
- [x] Mission skill manifest closed (`MISSION_SKILLS.md`)
- [x] End-state report (this file)
- N/A — imagery / ux-review / render-sanity / design-token-guard / deployment (no visual/styling change; recorded). Live walk = plan Task 6 (post-vendoring).
- **Intentionally INCOMPLETE:** Tasks 3–6 (vendoring + live walk) — out of this slice by user instruction ("stop before vendoring").

---

## Vendoring half (Tasks 3–5) — DONE ✅

After the user approved vendoring, three waves landed (one frontend agent each, lead-gated + committed per wave), then a consolidated QE gate.

| Wave | Commit | What | Pool effect |
|---|---|---|---|
| Task 3 — generic (dominant 86% bucket) | `693cb88` | 9 CC0 building GLBs | `MODEL_POOLS.generic` 23 → 32 |
| Task 4 — residential + commercial | `a140b49` | 4 homes + 3 shops | `house` 12 → 16, `stall` 7 → 10 |
| Task 5 — props | `8e26cc0` | 13 CC0 prop GLBs | 7 new `PROP_POOLS` (fence/bin/hydrant/fountain/sign/crate/barrel) |

**~29 new CC0 GLBs**, all from the established toon family (Quaternius / Kenney / Kay Lousberg / CreativeTrio / Isa Lousberg via poly.pizza), repacked `copy→dedup→prune` (no compression), footprints measured + scale-converged.

### Consolidated QE gate (`qa-report-vendor.json`) — PASS, `proceed=true`, 5/5, 0 blockers
- **CC0 audit (the hard rule): 29/29 verified `"Licence":"CC0 1.0"` at source — exhaustive, not sampled. Zero CC-BY.** Vendor agents *rejected* CC-BY candidates (Poly-by-Google hotel/hospital/museum/mall) on their own.
- Gates: combined asset suites 229 pass; full world3d **560** (24 files, +17 vs the 543 EM-239 baseline, 0 regressions); `tsc -b --force` exit 0.
- Determinism (EM-155) intact — resolvers unchanged, picks pure-fn-of-id; slot-0 invariant holds on url+scale+yOffset for every new pool.
- Payload **28 MB** (< 64 MB cap); largest GLB 1.97 MB (< 4 MB/file cap).
- Scope clean — `git diff 7cd3641..HEAD` = 40 files, all within world3d/models/docs/ASSET_LICENSES; no backend, no `kenney-city/` disturbance.

### Honest gaps (no silent drops)
- `fountain` prop pool is at the minimum 2 members (no clean CC0 birdbath/tiered piece exists). `hydrant` = 2 distinct hydrant silhouettes, `barrel` = wood+open (no CC0 pump/standpipe or street oil-drum exists). Logged, not forced.
- `tower-setback` (Task 3) dropped — no scale satisfies the footprint.

## Remaining (Task 6 — the only open item)
- **Live render walk (HITL, user's call):** start the stack, confirm the generic-tower monoculture is visibly broken, homes/shops/anchors vary, and the new props render as real toon art. This is the spec's acceptance gate. Code + tests + license are all green and committed; this is a visual sign-off, not a code blocker.
- **Not merged / no PR / ledger still `open`** — awaiting the user's call after the live walk.

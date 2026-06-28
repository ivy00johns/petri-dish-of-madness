# EM-248 (S5b — Building Variety) — Build Results · Tasks 1–2 slice

**Status: ✅ COMPLETE on branch `feat/em248-building-variety`. QA gate PASS (`proceed=true`, 5/5, 0 blockers).**
This is the **pure-code rewire half** of EM-248 (the user explicitly asked to "start task 1 now, stop before vendoring"). **Tasks 3–6 (new CC0 GLB vendoring + live-walk sign-off) are deliberately NOT in this slice** — they need network access + human aesthetic asset selection and remain queued.

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

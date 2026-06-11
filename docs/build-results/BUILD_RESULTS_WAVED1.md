# Wave D1 — "the EW-grade city: vocabulary + generator" (W15) · Build Results

> Branch: `build/wave-d1-ew-city` (off merged main `4ae3755`)
> Date: 2026-06-10 · Contract: `contracts/wave-d1.md` · QA: `coordination/qa-report.json` (proceed=true)
> Items: EM-152, EM-153, EM-154, EM-155, EM-156, EM-157 — all **done** in the ledger (`wave-D1 2026-06-10`).
> Source: `docs/research/deep-research-v4.md` + review feedback, filed via plan-intake as EM-152–169 (W15–W17).
> Substrate: ultracode Workflow swarm — implement fan-out `wf_1b3838bb` (3 role-agents ∥), gate-fix via agent resume, verify `wf_d7a16916` (QE + adversarial refuters).

## What shipped

| Item | Commit | Delivery |
|---|---|---|
| EM-152 city asset vocabulary | `ebeb37f` | 23 CC0 GLBs (~1.45 MB of a 15 MB budget): 6 Kenney kits (Roads/Commercial/Suburban/Industrial/Car/Furniture, direct-zip headless, License.txt verified pre-vendor) + KayKit fire hydrant; gltf-transform dedup/prune repack, textures embedded, no decoders. All 23 `CityPieceKey` registry slots non-null. 56 tests incl. byte-measured footprints (road tiles exactly TILE=2.6) and ASSET_LICENSES.md ↔ file integrity both directions. |
| EM-153 deterministic CityGenerator | `f4be249` | Pure seeded `cityLayout.ts`: Manhattan grid (TILE 2.6) → avenues → 4–6-tile blocks → 4–8 street-facing lots → zones (commercial ring / residential mid / industrial edge / civic sprinkle / 1-in-9 park with at-least-one fallback) → props + parked cars. Road kinds classified from actual neighbors so `road_end` caps fall out at boundaries. coreRadius derived from townLayout (41.85 on the 15-place town), never hardcoded; ~1,177 instances at seed 1337, ≤3,000 enforced with auto-shrink. 19 tests; the EM-155 determinism invariant lives here. |
| EM-155 city snapshot contract | `6ff4fee` | `world.city_seed` (config default 1337) → `to_snapshot`/`from_snapshot` (snapshot authoritative over params — a fork under an edited config still renders the parent's city) → every world_state payload. Silent-drop audit of all construction/assembly sites: none needed fixes (all derive from to_snapshot). 10 tests; backend 367→377. |
| EM-154/156/157 instanced render | `e142278` | `CityScape.tsx`: raw `InstancedMesh` per piece-key × spatial chunk (29 meshes for the whole city), shared toon materials, per-chunk bounding spheres, `StaticDrawUsage`, raycast no-op'd (EM-157 — set dressing is pointer-invisible), per-key `ModelBoundary` (null/failed GLB ⇒ skip, never a hole). `WORLD_REACH` bounds + camera/fog/shadow retune (shadow frustum deliberately covers core + near ring only). SIZE kept at 66 — documented deviation: growing SIZE rescales the city with it, so fit is a bounds problem, not a SIZE problem. 14 tests. |
| EM-156 old-town invariant + gate fix | `38ec37d` | Historic core untouched (zero Wave C component changes in the city path); wilderness scatter clamped to `deriveCoreRadius − 1` per snapshot — treeline 72→42 (honest saturation; the ring's ~28 `tree_city` carry the outer canopy), new EM-156 test block pins every tree/bush/rock/mushroom inside what the generator clears. |

## Gates

- Backend **377/377** (+10) · web **467/467** (+91) · `npm run build` clean · tsc clean.
- Orchestrator live pass (gate 2): **60fps measured**, console 0 errors, city ring renders around the core. Gate-fix round: R3F `dispose={null}` prop clobbers the method object-side — cleanup removed (R3F disposes the unmounted object itself; shared GLB caches safe); ~85 dev warnings → 0 on fresh load.
- QE adversarial gate: **proceed=true** (contract 4, coverage 4, security 5, regression 4); **10 probe families, 9 CONFIRMED-OK**: EM-155 determinism on the REAL live snapshot (byte-identical through a JSON wire round-trip), core-intrusion sweep seeds 1–25 (geometrically impossible by tile eligibility), pre-Wave-C snapshot defaults, license integrity, fps 60.2 default / 60.0 zoomed, free-scale law (zero LLM-path changes), instance budget across 10 seeds incl. negative/INT_MAX, console-clean live run, Wave C regression sweep (click-to-focus, lanes, animation all live-verified).
- The 1 FAILED probe (blocked `/models/**` console noise) became the MAJOR below — **adversarially REFUTED**.

## Adversarial verification (the headline)

QE's one MAJOR — "~160 unhandled preload promise rejections under blocked /models/**" — was independently refuted with decisive evidence: the events are React 18 **dev-mode** re-dispatch of errors that ModelBoundary correctly catches (`invokeGuardedCallbackDev`), not unhandled rejections (`unhandledrejection` count: 0); suspend-react already attaches the `.catch` the finding proposed adding; and a **production build under the identical probe produced 0 pageerrors**. The render half of the fallback invariant passed everywhere: full procedural town, no blank canvas, no crash. Residual kept as test-hardening note only.

## Recorded QE MINORs (not blocking)

1. Road-framed empty blocks ring the core at some seeds (block-level eligibility vs per-tile roads) — a future density pass may want lot-level eligibility or road pruning.
2. HMR edits to CityScape pin pieces absent until full reload (dev-loop footgun only; re-opened by any future cleanup added to the chunk effect — comment documents why there is none).
3. Contract's "+30 draw calls" delta is unverifiable without a no-city baseline toggle; absolute outcome met (~401 GL draw invocations incl. shadow pass at locked 60fps). A `?nocity` debug flag would make it enforceable.
4. `foliageLayout ↔ cityLayout` module cycle is benign but load-order fragile; cheap fix: lift `BAND_MAX` into worldSpace.

## Deliberate scope notes

- All 23 registry keys are non-null today; null-skip and failure-skip paths are still implemented and test-pinned (contract rule 10).
- Ambient/moving traffic is EM-169 (W17); cars ship parked.
- City growth from sim state is EM-123 (the generator consumes places+seed today; growth output becomes its input later).
- W16 (population scaling) is gated on EM-155 ✅ (done this wave) and EM-164 (budget-assumption verification — open, measurement can now start since the city renders).

## Evidence

`docs/build-evidence/`: `wave-d1-final-city.jpeg` (post-clamp hero shot, live run day 10), `wave-d1-gate2-city-{default,wide}.jpeg`, `qe-wave-d1-{default-camera,city-zoomed,blocked-models}.jpeg`.

## Wave D1.5 — corrective: "make it THE city" (user verdict on D1: decor, rejected)

D1's ring city was decor around an unchanged medieval core — the user killed the core and
ordered the sim onto the grid. Contract: `contracts/wave-d1.5.md`. Lean build (2 agents +
orchestrator gates), commits `f115dd1`/`aaf5825`/`c2d9dce`/`c685144`:

- **The sim IS the city now**: 15 places became landmarks on a 5×5-block lattice (13.0u
  pitch; ids/kinds/districts unchanged so the engine and every pinned backend test held —
  377/377 with ZERO test edits); names re-themed (City Hall, Market Hall, The Steelworks,
  Hearth House, The Commons Park…).
- **Dense by law**: landmark blocks reserved for their place; every other lot developed
  (8/8 per block, test-enforced "zero empty road-framed blocks"); parks from the old farm
  edge + 1 seeded park. 473 instances, extent 33.8 — the city spans the 66u world exactly.
- **Medieval retired**: kaykit-medieval-hexagon deleted (9 GLBs + license rows; fountain
  stays for the plaza), lanes/wilderness machinery removed (signatures kept, so consumers
  didn't churn), anchors swapped to kenney-city GLBs, camera/fog/shadow retuned compact.
- Gates: backend **377/377**, web **468/468**, tsc + build clean, **61fps**, console 0
  errors; live-verified at street level: Ada/Cleo/Bram with chips at the Central Plaza
  fountain, critters + billboard among dense blocks — the EW reference shot. Evidence:
  `docs/build-evidence/wave-d15-{city,plaza-zoom,street-level}.jpeg`.
- Known polish (recorded, not blocking): generated-block variety skews dark-commercial in
  civic zones; agents lerp straight lines between landmarks rather than following streets
  (road-pathing is a natural W17 item); D1's ring-era evidence shots are historical.

## Handoff

- Wave D1 complete on `build/wave-d1-ew-city` — **PR to main awaits the user's word.**
- Next per the v4 wave shape: **W16 / D2 population scaling** (EM-158–166; hard rules: EM-159 must not ship without EM-160's spontaneity floor; EM-164 verification is the go/no-go), then W17 / D3 life (EM-167–169 + EM-127 day/night + EM-123 growth).
- Still owed: full-skill repo-wide `ux-review` on merged main (standing since W11b — now covers W9→WaveD1); EM-151 (P1, inspector archive blank on 40k-event runs) remains open.

# EM-239 (S1 — Layout-Graph Spine) — Build Results

**Status: ✅ COMPLETE on branch `feat/em239-layout-graph-spine`. QA gate PASS (`proceed=true`).**
Acceptance bar — byte-identical rendered output (EM-155) — **met and independently proven**, including a true cross-language check against the real Python emitter. Not merged (feature branch; awaiting your call).

This was an orchestrated build in **Workflow mode** (ultracode): design/contracts/branching inline, implement + verify phases as deterministic Workflow scripts with adversarial verification. The QA gate stayed with the lead.

## What shipped

The frozen 5×5-grid pure-function city is now rendered **from an authoritative, snapshot-serialized backend `CityGraph`** (roads first-class; lots/zones/landmarks/streets still derived). Output is byte-identical to before — this is the spine S2–S5 build on, not a visible change.

- **`backend/petridish/engine/citygraph.py`** (new) — `CityNode`/`CityEdge`/`CityGraph` + `classic_grid(seed)` (36 nodes / 60 edges, axis-aligned), pure of seed; `to_dict`/`from_dict`.
- **`backend/petridish/engine/world.py`** — builds the graph at init; additive `city_graph` key in `to_snapshot()`; **restore-or-derive** in `from_snapshot()` keyed off the *restored* `city_seed` (derive-on-load migration), hardened against corrupt input.
- **`web/src/types/index.ts`** — `CityGraph`/`CityGraphNode`/`CityGraphEdge` + `WorldState.city_graph?`.
- **`web/src/components/world3d/cityLayout.ts`** — `roadTileSetFrom` / `roadLineIndicesFrom` derive roads + street-lines **from the graph**; `emitRoads(pieces, roadTiles)` + `computeStreets(seed, graph)`; falls back to the hardcoded grid when the graph is absent/empty/corrupt.
- **`web/src/components/world3d/CityScape.tsx`** — passes `city_graph` through; **deliberately not** in the `useMemo` deps (graph is seed-determined in S1; adding a per-tick object would churn the buffers — EM-155 perf invariant).

No DB schema change — the graph rides the existing snapshot `state_json` blob, so `repository.py` is untouched (the plan's tentative "persistence touch" was confirmed unnecessary).

## Commits (on `feat/em239-layout-graph-spine`)

| Commit | What |
|---|---|
| `39bbe97` | docs: the EM-239 implementation plan |
| `5bb01ae` | feat: backend CityGraph spine — model, classic_grid, World wiring + derive-on-load migration |
| `ba5729d` | feat: render city FROM CityGraph with byte-identical fallback |
| `52d6c67` | fix: harden CityGraph boundaries against corrupt input (ModelBoundary) |

## Gates (independently re-run by the lead and by the QE agent)

| Gate | Baseline | Final | Result |
|---|---|---|---|
| Backend `pytest` | 1609 | **1620** (+11) | ✅ 0 regressions |
| Frontend `cityLayout` | 54 | **57** (+3) | ✅ |
| Frontend `world3d` suite | 530 | **534** | ✅ 24 files |
| Typecheck `tsc -b --force` | exit 0 | **exit 0** | ✅ |

> Note: plain `tsc --noEmit` is **vacuous** in `web/` (tsconfig uses project references with `files:[]`). The real typecheck is `tsc -b --force` — surfaced by the frontend agent; it actually caught the pre-impl red state (TS2353 on `city_graph`).

## Verification — adversarial + QE (this is where the value was)

A 3-lens adversarial pass + a QE gate ran after implementation:

- **Byte-identical + cross-language: PASS.** 20 seed×fixture combos byte-identical (deep `toEqual` *and* order-sensitive `JSON.stringify`); the **real `classic_grid(1337)` JSON emitted by Python** fed into the frontend is byte-identical to the no-graph fallback across all fixtures (proves the emitter agrees, not just the hand-written test fixture).
- **Scope + determinism: PASS.** Strictly S1 (no S2/S3/S5 leakage); no `Math.random`/clock/mutable module state; stable sort keeps street-name order byte-identical.
- **Resilience: FAIL → fixed.** Found two **real render-crash paths** on *type-corrupt* graphs (FE `roadTileSetFrom`/`roadLineIndicesFrom` dereferenced a non-array `nodes`; BE `from_snapshot` reached the strict `from_dict` on a malformed graph). Both crashed *upstream* of the per-piece `<ModelBoundary>` — violating the spec's "never a hole, never a crash." **Fixed in `52d6c67`** with `Array.isArray` guards (FE) + list-validation/try-except → derive (BE), and regression tests codifying the exact crash vectors. QE re-verified both resolved.

**Final `qa-report.json`:** status **PASS**, scores 5/5 across contract/correctness/security/coverage/scope, **0 blockers**, `gate_decision.proceed=true`. (`docs/superpowers/em239-build/qa-report.json`.)

## Render / reality gate stance

The product surface is the 3-D city, but the acceptance bar is *byte-identical output*. The **byte-identical golden test + cross-language emitter proof are the render gate** — any visual drift fails them, and the render is a pure function of the `CityPlan` (EM-155), so identical `CityPlan` ⇒ identical pixels. `nano-banana`/`ux-review`/`render-sanity`/`design-token-guard` are therefore N/A as *change* gates (recorded in `MISSION_SKILLS.md`).

## Handoff items

1. **Manual live/replay/fork eyeball** (plan Task 5 Step 3) — start the stack, confirm the live city is visually unchanged, an existing replay renders identically (derive-on-load), and a fork's tick-0 city matches the parent. This is corroborative (byte-identity is already proven at the data layer); offered if you want it run via the browser tools.
2. **Unrelated uncommitted changes** — `backend/petridish/imagegen/provider.py`, `config/world*.yaml`, `backend/tests/test_imagegen_providers.py` live on the `feat/image-providers-freellmapi` concern and are **outside EM-239**; they were not touched or folded in.
3. **PR** — not opened (no merge/PR without your say-so). Branch is ready.

## Scope boundary

S1 only — the spine. The rest of the initiative remains tracked (Wave N): **EM-243** (S2 build verbs), **EM-244/245** (S3a/S3b governance + master plans), **EM-246** (S4 templates), **EM-247/248** (S5a/S5b meshing + assets). S5b (building variety) is the standalone immediate fix for the repeat-asset pain and can run anytime.

## Definition of Done

- [x] Agents passed validation; integration issues (2 HIGH) fixed + re-validated
- [x] Contract diff — zero mismatches (byte-identical, cross-language)
- [x] Render gate — byte-identical golden + cross-language emitter proof (PASS); live eyeball = handoff #1
- [x] Plan acceptance criteria — all 5 tasks + byte-identical gate (EM-155)
- [x] Mission skill manifest closed out (`MISSION_SKILLS.md`)
- [x] QA gate passed — `qa-report.json` PASS, `proceed=true`
- [x] End-state report (this file)
- N/A — new imagery / ux-review / render-sanity / design-token-guard / deployment (no visual or styling change; recorded)

# EM-245 (S3b — master plans / city morph) — Build Results

**Status: ✅ COMPLETE on branch `feat/em245-master-plan-morph`. QA gate PASS (proceed=true, 0 blockers); the MEDIUM + the actionable LOW the review surfaced are FIXED. This is the FINAL agent city-layout control — the initiative is complete (modulo EM-247's deferred visual sign-off).**
Orchestrated **ultracode** build (Workflow mode): plan inline; implement + verify workflows. Backend-only.

## What shipped
The town can vote a whole **city topology** and watch the city **morph** toward it over ticks:
- `master_plan(kind, params, seed)` (`citygraph.py`, pure) → a target `CityGraph` for **pentagon / radial / ring / grid**.
- `diff_graphs(current, target)` → the node/edge add/remove set (by id).
- `World.step_master_plan_morph()` — per tick (loop hook beside `expire_miracles`), applies ≤ `MORPH_EDGES_PER_TICK` ops (adds-before-removes, seeded order) toward the target, emitting `road_built`/`road_demolished`, until convergence → `master_plan_complete` + clears.
- `adopt_master_plan` — a vote-gated `propose_rule` effect (ratify at **0.7**, **one active plan at a time**) mirroring EM-244. On activation it sets `self.master_plan = {kind, params, seed}`.
- `template()` now routes the **geometric presets** (pentagon/radial/ring) to `master_plan` — **completing EM-246's templates** (a plan seeded at run start, no morph).

The active plan rides the snapshot (target re-derived each tick) so replay/fork + mid-morph resume are byte-identical (EM-155). An inactive plan is a byte-identical no-op (existing runs unchanged). The morph renders via EM-243 live-render + EM-247 mesh; building relocation rides `assignBuildingLots` re-derivation (per EM-244).

## Commits (on `feat/em245-master-plan-morph`)
| Commit | What |
|---|---|
| `c60cf83` | docs: the S3b plan |
| `9527739` | feat: master-plan morph (generators/diff/morph/adopt effect/template wiring) |
| `ee8d9bd` | fix: pre-ship review — snapshot shape-hardening (MEDIUM) + connected radial (LOW) |

## Gates
| Gate | Baseline (EM-244) | Final | Result |
|---|---|---|---|
| Backend `pytest` | 1682 | **1706** (+24) | ✅ 0 regressions |

## Verification — adversarial (4 lenses) + QE gate: PASS
- **Determinism + no-op-safety:** master_plan/diff/morph pure; full propose→ratify→morph-to-completion deterministic across two worlds; mid-morph snapshot resumes byte-identically; inactive plan = byte-identical no-op (airtight). **Fixed** the MEDIUM (type-only snapshot guard → now shape-validates kind∈MASTER_PLAN_KINDS + seed → None, so a corrupt plan can't wedge/misfire the morph).
- **Governance + EM-244 mirror: CLEAN.** Ratifies only at 0.7 (3/5 fails, 4th passes); governance gate; one-active guard (world + runtime agree); no-renewal in both lists; the EM-244 effects (demolish_road/set_car_policy/demolish) + shared machinery still work.
- **Morph safety: CLEAN** (post-fix). Never edgeless (adds-before-removes); converges + clears (no infinite/oscillating morph); bounded per tick; raw removal doesn't weaken the EM-244 individual one-road-floor; no dangling edges. **Fixed** the LOW disconnected radial (inner ring now spokes to the shared center — one component).
- **Scope + EM-246 completion: CLEAN.** Only the 8 backend files; the 2 EM-246 geometric-fallback test updates are legitimate (pentagon now yields a pentagon graph; unknown-kind fallback coverage preserved); template geometric routing correct; grid/greenfield/village still byte-identical-default.

## Recorded follow-ups (non-blocking)
- **Cross-host sin/cos ULP** (LOW): geometric node coords use `math.cos/sin` (not correctly-rounded cross-platform). Same-host replay/fork byte-identical (diff matches by id; placed nodes ride serialized floats); a mid-morph fork resumed on a *different* host could differ in the last ULP for not-yet-placed nodes.
- **No-op-self-shape adopt guard** (LOW): adopting `grid` on an already-grid city ratifies then instantly completes (0 roads). Mirror-consistent with EM-244; the morph no-op-completes cleanly.
- **Menu discoverability:** `adopt_master_plan` (like EM-244's `demolish_road`/`set_car_policy`) isn't in the base `propose_rule` menu — surface the layout-governance effects in the menu/perception so agents discover + vote them autonomously.
- **Building `building_relocated` event:** deferred — relocation rides the frontend (per EM-244).

## Definition of Done
- [x] Implement (Workflow) — backend chain, TDD
- [x] Wave gate green, 0 regressions (1706); inactive plan byte-identical
- [x] Adversarial verify (4 lenses) + QE gate PASS; MEDIUM + actionable LOW FIXED + regression-tested
- [x] Determinism (EM-155) + snapshot-resume + convergence + never-edgeless proven
- [x] Completes EM-246 geometric presets
- [x] Mission manifest + this report
- [ ] **Geometric visual sign-off** = EM-247's deferred user gate (flip ROAD_MESH_ENABLED, vote a pentagon, watch it morph at 60fps).

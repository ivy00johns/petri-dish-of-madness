# EM-244 (S3a — vote-gated demolish + car-policy) — Build Results

**Status: ✅ COMPLETE on branch `feat/em244-vote-demolish-carpolicy`. QA gate PASS_WITH_ISSUES (`proceed=true`); the HIGH + both MEDIUM findings the adversarial pass surfaced are FIXED.**
Orchestrated **ultracode** build (Workflow mode): plan inline; implement + verify as workflows.

## What shipped
Two agent-collective city controls via the existing town-hall vote (ratify at 0.7):
- **`demolish_road`** — a ratified vote tears down a `CityGraph` edge (+ freed dead-end node), with a **one-road floor**.
- **`set_car_policy`** — a ratified vote bans cars city-wide (the "ban cars + all sidewalks" headline) or pedestrianizes one street; ambient traffic + parked cars vanish on `pedestrian`, which renders a surface tint.

Both are new rule **effects** on the unified `propose_rule`/`vote`/`_evaluate_rule`/`_on_rule_activated` machinery (the EM-183/EM-219 pattern) — emitting `road_demolished` / `car_policy_set` system events. Pure `apply_demolish_road`/`apply_car_policy` in `citygraph.py`; the graph rides the snapshot → EM-155 holds. Frontend: `car_policy` (dormant since S1) is now live + **re-renders live** (citySignature folds it). Demolish needs no relocation code — `assignBuildingLots` re-derives + reassigns deterministically.

## Commits (on `feat/em244-vote-demolish-carpolicy`)
| Commit | What |
|---|---|
| `1ec213e` | docs: the S3a plan |
| `22cbc20` | feat: backend — demolish_road + set_car_policy rule effects |
| `adccc25` | feat: frontend — car_policy live (traffic/parked cars/tint) |
| `00ab573` | fix: pre-ship review — live car-policy (HIGH) + demolish guards (2× MEDIUM) |

## Gates (lead-run AND QE-re-run)
| Gate | Baseline (EM-243) | Final | Result |
|---|---|---|---|
| Backend `pytest` | 1638 | **1665** (+27) | ✅ 0 regressions |
| Frontend `world3d` | 564 | **577** (+13) | ✅ 24 files |
| `tsc -b --force` | 0 | **0** | ✅ |

## Verification — adversarial (4 lenses) + QE gate
Lens verdicts: determinism+live-render = issues (1 HIGH), governance = issues (1 MEDIUM), scope = clean, integration = issues. QE gate **PASS_WITH_ISSUES, `proceed=true`, 0 blockers**. The adversarial pass caught three real issues the green suites missed — all FIXED + regression-tested:

- **HIGH — `set_car_policy` didn't re-render live.** `citySignature` folded only node/edge **counts** (the EM-243 fix); a car_policy change is counts-invariant, so the pedestrian tint + parked-car removal showed only after reload (ambient traffic reacted via ref-identity → a half-applied live state). **Fix:** `citySignature` now folds `car_policy` (city + per-edge non-inherit), computed every render; the ref-cache still gates the rebuild. Regression test added (the exact gap the suite missed: a policy flip at constant counts).
- **MEDIUM — demolish-everything resurrected the grid.** A city demolished to zero edges hit the frontend's empty-graph guard (empty edges read as "absent/corrupt" → 5×5 fallback). **Fix:** `apply_demolish_road` refuses the last edge (one-road floor). Test added.
- **MEDIUM (pre-existing) — 2nd building demolish-by-vote never applied.** `'demolish'` was missing from `action_vote`'s renewal-exclusion, so a 2nd public-demolish was misclassified as a renewal of the first (the 3814 comment already called demolish one-shot). **Fix:** added `'demolish'` to the exclusion. Regression test: a 2nd building demolish-by-vote now applies.

Backend graph ops are pure + deterministic; snapshot round-trip byte-identical; replay-stable; default car path byte-identical (EM-239/EM-243 goldens hold). `demolish_road` re-renders live (count changes).

## Deviations from the plan (recorded, sound)
- Front-gate is the module-level `_validate_world` (not a method); the agent mirrored it + added gate-agreement (EM-108).
- Added the new effects to the **no-renewal exclusion** (both propose + vote sites) — the plan omitted this; without it a re-proposal would be misclassified as a renewal and not apply.
- Ratification is **synchronous** (`action_vote → _evaluate_rule → _on_rule_activated`); tests assert post-ratify state, no manual `_on_rule_activated` call.
- Frontend touched `CityScape.tsx`/`CozyWorld.tsx` (render the tint + thread the graph into `<Traffic>`) beyond the plan's file list — required + frontend-only.

## Scope boundary + deferrals (recorded)
- **S3a only.** No S3b (master plans / morph — EM-245, gated on EM-247). No explicit building relocation (rides `assignBuildingLots`).
- **`district` car-policy scope deferred** (no edge→district mapping; city + street ship).
- **Follow-ups (LOW):** `Traffic` memo recomputes every poll (ref-identity dep; functionally correct, perf nit); `demolish_road`/`set_car_policy` are one-open-proposal-at-a-time (not per-target scoped like building `demolish`); `road_demolished`/`car_policy_set` (like `road_built`) aren't in the feed `EventKind`/`CATEGORIES` (show in default view; hidden under category filters).

## Definition of Done
- [x] Implement (Workflow) — backend governance chain ∥ frontend car-policy, TDD
- [x] Wave gate green, 0 regressions (1665 / 577 / tsc 0)
- [x] Adversarial verify (4 lenses) + QE gate PASS; HIGH + 2 MEDIUM FIXED + regression-tested
- [x] Determinism (EM-155) proven; default car path byte-identical
- [x] Mission manifest (`MISSION_SKILLS.md`) + this report
- [ ] Live-walk eyeball + merge — handled by the session goal (merge proceeding)

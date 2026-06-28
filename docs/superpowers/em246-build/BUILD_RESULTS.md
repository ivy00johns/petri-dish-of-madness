# EM-246 (S4 — city templates / "city profile") — Build Results

**Status: ✅ COMPLETE on branch `feat/em246-city-templates`. QA gate PASS_WITH_ISSUES (`proceed=true`, 0 blockers); the review's findings (1 MEDIUM doc + LOW null-template) are FIXED.**
Orchestrated **ultracode** build (Workflow mode): plan inline; implement + verify as workflows.

## What shipped
The "city profile" that was never worked out: a run-start `world.city` block (`template`, `size`, `density`, `car_policy`) seeds the initial `CityGraph` via a pure `template()` dispatcher:
- **grid** → `classic_grid` (byte-identical default; no `city:` block ⇒ grid).
- **greenfield** → a minimal central-block plaza (4 nodes / 4 edges) — the "maybe they build nothing" start; agents build out from it.
- **village** → a seeded-sparse axis-aligned grid (`hashlib`, density-tuned low/medium/high), central plaza always kept (connected, non-empty core).
- **pentagon / radial / ring** → fall back to grid + a logged warning (need EM-245 generators + EM-247 meshing), recording the requested kind in `CityGraph.template`.

`World.__init__` seeds from the profile + sets the initial `car_policy`. `CityGraph` gains an additive `template` field (back-compat default `"grid"`). The different starting cities render **for free** via the EM-243 graph-driven renderer (frontend gets only an additive `template?` type field). EM-155 holds (pure fn of profile+seed; graph rides the snapshot; default byte-identical).

## Commits (on `feat/em246-city-templates`)
| Commit | What |
|---|---|
| `e4daa9c` | docs: the S4 plan |
| `b448b53` | feat: backend — template() dispatcher + greenfield/village + CityProfileParams config |
| `09768a8` | feat: frontend — additive `template` type + greenfield-renders test |
| `1eab97f` | fix: pre-ship review — null-template→grid + reserved-`size` docs |

## Gates (lead-run AND QE-re-run)
| Gate | Baseline (EM-244) | Final | Result |
|---|---|---|---|
| Backend `pytest` | 1665 | **1682** (+17) | ✅ 0 regressions |
| Frontend `world3d` | 577 | **578** (+1) | ✅ 24 files |
| `tsc -b --force` | 0 | **0** | ✅ |

## Verification — adversarial (4 lenses) + QE gate
QE gate **PASS_WITH_ISSUES, `proceed=true`, 0 blockers, no HIGH/CRITICAL**. Determinism + byte-identical default both confirmed (template("grid", seed) == classic_grid(seed) full to_dict; greenfield/village deterministic per (seed, density); snapshot round-trip byte-identical; geometric fallback warns once, forks without re-warn). The review surfaced doc/robustness issues, all FIXED:

- **MEDIUM — `size` advertised but inert** (3 lenses). `size` is parsed + threaded but greenfield/village ignore it (plaza fixed; village thins the canonical 5×5). **Fix:** corrected the 3 docs (template() docstring, loader field, world.yaml) to say RESERVED / not-yet-honored — no false config surface. (Honoring `size` for a scaled extent is a follow-up, tracked with the geometric presets.)
- **LOW — `template: null` → `'none'`.** A null/empty template scalar coerced to the literal `'none'`, routing through the geometric fallback + a spurious "needs EM-245" warning. **Fix:** coerces None/empty → grid. Regression test added.
- **LOW (left as follow-up):** world.py reads profile fields via `getattr` not `_block_get` (not reachable — `params.city` is always a `CityProfileParams`).
- **INFO:** old-snapshot re-save gains an additive `"template":"grid"` key (additive design); village may emit disconnected satellite roads (acceptable — agents connect them; core stays connected).

## Scope boundary + deferrals (recorded)
- **S4 ship-now:** grid / greenfield / village (axis-aligned). Geometric presets (pentagon/radial/ring) → grid + warning until **EM-245** (generators) + **EM-247** (meshing) land — EM-245's PR completes the geometric-template loop.
- **`size`** reserved (parsed, not yet honored). The visible template-name UI label + run-start picker deferred (the renderer already shows the city; `template` rides the snapshot for a future label).

## Definition of Done
- [x] Implement (Workflow) — backend templates chain ∥ frontend type, TDD
- [x] Wave gate green, 0 regressions (1682 / 578 / tsc 0)
- [x] Adversarial verify (4 lenses) + QE gate PASS; findings FIXED + regression-tested
- [x] Determinism (EM-155) + byte-identical default proven; greenfield near-empty render + perception safe
- [x] Mission manifest + this report
- [ ] Merge — proceeding (session goal)

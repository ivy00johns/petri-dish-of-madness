# Mission skill manifest — EM-243 (S2 build_road verb)
Source: docs/superpowers/plans/2026-06-27-em243-build-road-verbs.md · Scanned: 2026-06-27

Orchestrated ultracode build (Workflow mode — ultracode reminder present). Design/contracts
inline (the plan); implement + verify as Workflow scripts. Backend-heavy; one frontend slice.

## Phase: Implement (Workflow — parallel, disjoint files; agents TDD but DON'T commit)
- [ ] backend-agent (general-purpose) — plan Tasks 1,2,3,4,6 (citygraph pure ops → world method+param → dispatch/schema → perception/menu → determinism acceptance). `.venv/bin/python -m pytest`.
- [ ] frontend-agent (general-purpose) — plan Task 5 (tessellation tests for extended/irregular graphs; reuse EM-239 cityLayout fixtures). `/usr/local/bin/npx vitest` + `tsc -b --force`.

## Phase: Wave gate (lead, inline)
- [ ] full backend `pytest` (≥1620, 0 regressions) + full `world3d` vitest + `tsc -b --force` green; lead commits per-task slices.

## Phase: Verify (Workflow — adversarial + QE)
- [ ] adversarial lenses — EM-155 determinism (graph pure-fn of seed+road_built; snapshot round-trip; ids stable), verb validity rules (anchor/bounds/vacant/affordable + clear reasons), scope (grow-only; no S3 leakage), prompt-diet (nearby_layout line-capped, district-scoped, omitted when empty).
- [ ] qe-agent (MANDATORY) — qa-report.json, gate_decision.proceed.

## N/A (recorded)
- `nano-banana`/`frontend-design`/`design-token-guard`/`render-sanity`/`ux-review` — N/A: backend logic + a graph-derived render that re-derives with no new frontend code; Task 5 is tests only. Live-walk (an agent actually building a road) is the acceptance eyeball, offered at the end.
- `contract-author` — N/A: the plan's exact code + signatures are the contract.

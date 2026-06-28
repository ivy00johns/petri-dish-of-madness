# Mission skill manifest — EM-246 (S4 city templates)
Source: docs/superpowers/plans/2026-06-28-em246-city-templates.md · Scanned: 2026-06-28

Orchestrated ultracode build (Workflow mode): plan inline; implement + verify workflows.
- [x] implement workflow — backend templates chain ∥ frontend type, TDD, no commits
- [x] wave gate (lead) — backend 1682 / world3d 578 / tsc 0, 0 regressions
- [x] verify workflow — 4 adversarial lenses (determinism/byte-identical, config/back-compat, scope, greenfield-safety)
- [x] qe-agent (MANDATORY) — qa-report.json PASS_WITH_ISSUES, proceed=true; MEDIUM (size docs) + LOW (null-template) FIXED
- N/A: nano-banana / design-token-guard / render-sanity / ux-review — no new imagery/styling; the graph-driven renderer shows the different cities for free. Live-walk = the user's eyeball (the greenfield/village start renders sparse).

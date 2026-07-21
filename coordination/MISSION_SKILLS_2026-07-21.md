# Mission skill manifest — Overnight "Every Angle" run
Source: docs/plans/2026-07-21-overnight-everything-plan.md · Scanned: 2026-07-21

Every box must end the build either ✅ (invoked, with the artifact path)
or annotated with a one-line reason for deferral. Empty boxes are bugs.

## Pre-build (research — complete before orchestration)
- [x] `plan-builder` — produced `docs/plans/2026-07-21-overnight-everything-plan.md` ✅
- [x] research fan-out (4 agents) — reports in scratchpad `research/` (pain-points, fallback-review, world-inventory, docs-skills-drift) ✅

## W1/W2 — Lane root fixes + rejection cut
- [ ] contracts (lead-authored, repo format) — `contracts/2026-07-21-feed-truth.md`
- [ ] wave gate (`fix-until-green` discipline) — pytest / vitest / tsc in worktree
- [ ] QE agent — `coordination/qa-report-2026-07-21-w1w2.json`

## W3 — Observability UI (Lane Health panel + PR #113 styling)
- [ ] `playwright` screenshots — hard gate for both panels (visual-validation rule)
- [ ] lab-* token audit (manual; no design-token-guard config in repo)
- [ ] QE agent — `coordination/qa-report-2026-07-21-w3.json`

## W4 — Safe discovery-ON + quota pre-emption
- [ ] live strict-JSON probes against FreeLLMAPI before any new pin
- [ ] QE agent — regression gates

## W5 — Emergence wave (headline)
- [ ] ideation+judge panel (3 proposals → judged) — `coordination/SURPRISE_PANEL_2026-07-21.md`
- [ ] contracts (lead-authored) — `contracts/2026-07-21-lived-culture.md` + surprise-feature contract
- [ ] determinism goldens — mandatory (sim-surface)
- [ ] QE agent — `coordination/qa-report-2026-07-21-w5.json`

## W6 — Docs, skills, ledger, memory
- [ ] 23 drift findings applied — docs-agent
- [ ] ledger reconcile + EM-325+ filed (living-plan convention, lead-reviewed)
- [ ] memory files written (new pains + live-health-first diagnosis rule)

## W7 — Go-live + verification
- [ ] run.sqlite backup (VACUUM INTO) BEFORE restart
- [ ] sim restart WITHOUT --reload; new config adopted
- [ ] `playwright` — feed + 3-D + panel screenshots into `docs/screenshots/2026-07-21/`
- [ ] `MORNING-REPORT.md` at repo root (end-state report; DoD item 17)

## Deliberately not invoked (reasons)
- `nano-banana` — no seed-imagery need; in-world art rides the free Pollinations lane (subscription-only billing rule).
- `ux-review`/`render-sanity` full suite — replaced by targeted Playwright screenshot gates (W3/W7); the app is a single-page live sim, not a route matrix. Recorded per DoD 8.
- `wiki-research` — no Obsidian wiki in this repo; START-HERE.md + ledger serve that role.
- Chrome-extension browser tools — banned by user global rule; Playwright only.

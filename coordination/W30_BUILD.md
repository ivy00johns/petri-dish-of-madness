# W30 — Fable-audit remediation build

Source mission: user directive 2026-07-09 — "complete as much of the backlog, keep the docs
updated, test model routing per task, workflow" + mid-build addendum: "the Mox 'All models
exhausted' idle-fallback churn — add to the list and fix."
Input report: the 2026-07-08 Fable deep review of the no-Fable window (PRs #75–#83, sessions
Jul 5–8). Branch: `build/w30-audit-remediation` (worktree, off main @ c419029).
The main working tree hosts the LIVE SIM and is untouched by this build.

User design calls captured 2026-07-09 (these close the two gates the review flagged):
1. **F1 restore behavior: derive-on-load RATIFIED.** Old saves gain positions on load; the
   live `run.sqlite` city re-places on next restore. Lock in with flag-ON legacy coverage (A9).
2. **Soft-pin/bounce-loop conflict: FIX NOW** (spec §6 step 1 — the registry walk owns the
   pre-emptive sick-lane skip; no more blind detour to `auto`). Expanded per the churn
   addendum to also stop fits()-skipping healthy free lanes on boosted calls (A8).

## Mission skill manifest
Scanned: 2026-07-09 · Source: user directive (no MISSION.md)

- [x] `orchestrator` — this build (Workflow mode; user said "workflow").
- [x] `model-adaptation` (model & effort tiering) — the explicit "test model routing" ask:
      Haiku = mechanical docs; Sonnet = standard implementation; Opus = subtle tests + the
      routing fix; Fable = adversarial verify + synthesis. Recorded per-agent below.
- [x] `git-commit` — conventional commits by the lead at wave boundaries (agents do NOT commit).
- [x] `code-review` — verify workflow: opus code-review + spec-conformance lenses on the branch diff; every finding adversarially checked by fable verifiers (2 code findings confirmed → fixed same-build by a fable remediation agent; toy-universe blind spot closed with a production-shaped test).
- [x] `verify` / QE — wave gate ran twice (post-implement and post-remediation, both fully green: backend 2005 passed/1 skipped, web 1215, tsc clean) + independent QE gate agent (proceed=true, anti-cheat pass confirmed coverage UP, no weakened assertions).
- [x] `plan-intake` convention — EM-268/298 swept, EM-300–307 filed, closure log backfilled through W30 itself; verify round caught and fixed the A6/A7 reconciliation misses.
- [ ] `render-sanity` / `ux-review` — DEFERRED: no UI behavior ships here except the decal-clear
      fix; visual F1 sign-off is a separate user-driven session against the live sim.
- [ ] `nano-banana` — N/A: no new UI surface, no imagery need.

## File ownership (one owner per file; lead resolves all conflicts)

| Agent | Model/effort | Owns |
|---|---|---|
| A1 golive-config | sonnet/high | `backend/tests/test_adaptive_lane_routing.py` (config diffs pre-applied by lead) |
| A2 f1-frontend | sonnet/medium | `web/src/components/world3d/cityLayout.f1.test.ts` (+ `cityLayout.ts` only if flag injection is required) |
| A3 ci | sonnet/high | `.github/workflows/ci.yml` (new) |
| A5 facades-clear | sonnet/high | `backend/petridish/engine/world.py` (decal-clear only), `backend/tests/test_em298_facades.py` |
| A6 docs-mechanical | haiku | `docs/COMPLETED-WORK.md`, `BUILD-PLAN.md` (closure rows only) |
| A7 docs-authored | sonnet/medium | `docs/REMAINING-WORK.md`, `START-HERE.md`, `docs/research/deep-research-v5.md` (inline markers), `docs/superpowers/specs/2026-07-07-adaptive-lane-routing.md` (header) |
| A8 adaptive-delivery | opus/xhigh | `backend/petridish/providers/router.py`, `backend/petridish/agents/runtime.py` (soft-pin path), `config/world.yaml`, `config/world.city25.yaml`, `backend/tests/test_adaptive_softpin_reconcile.py` (new) |
| A9 f1-coverage | opus/high | `backend/tests/test_free_placement_legacy_restore.py` (new) |

Known cross-branch caution: open PR #84 (`fix/timeout-error-handling`) also touches
`router.py`/`loop.py`/`adapters.py`. A8 stays surgical; a trivial rebase of #84 or this
branch may be needed at merge time — that is expected and recorded here.

## Wave gate (lead, inline, after implement workflow)
From `/Users/johns/Projects/petri-dish-of-madness-worktrees/w30`:
1. `./.venv/bin/python -m pytest backend/tests -q`
2. `cd web && /usr/local/bin/npx vitest run`
3. `cd web && /usr/local/bin/npx tsc -b --force`
Failures route back by file ownership. fix-until-green discipline: one root cause per
iteration, no weakened assertions, no flag-pinning-to-dodge (the exact anti-pattern PR #82
committed), 3-failure circuit breaker.

## Verify workflow (after wave gate green)
QE full-suite QA report (sonnet/high) → review lenses: code-review on branch diff
(opus/high), A8 spec-conformance vs spec §6 (opus/high), docs/ledger cross-check
(sonnet/medium) → adversarial verification of every finding (fable/high). QA gate is law.

## End-state
Lead commits per-workstream on the branch, writes `coordination/W30_RESULTS.md`, reports.
No merge, no PR unless the user asks (their call, per house policy).

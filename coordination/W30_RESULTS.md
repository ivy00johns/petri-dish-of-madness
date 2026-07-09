# W30 — end-state report (2026-07-09)

**Status: build complete and verified on `build/w30-audit-remediation` (9 commits ahead of main). Not merged — merge/PR is the user's call.** Everything here ran against the isolated worktree; the live sim's working tree was never touched.

## What shipped (all gates green: backend 2005 passed / 1 skipped · web 1215 passed · tsc clean)

| # | Commit | What |
|---|---|---|
| 1 | `feat: flip adaptive lane routing on and fix ghost matchers` | Go-live config committed (was uncommitted-only), 2/3 ghost matcher globs fixed, bounce-only `gpt-oss-120b` profile, real-config wiring test so a zero-lane glob can never ship silently again (audit M3). |
| 2 | `fix: sick pins walk the sorting list and bounces clamp max_tokens` | Spec §6 step 1: sick pinned lanes enter the curated walk (zero wasted calls) instead of detouring to `auto`; boosted calls clamp per-lane instead of excluding every small free lane (the "All models exhausted" churn path). Adaptive-OFF byte-identical to #76. |
| 3 | `test: green frontend f1 suite and lock in flag-on placement` | Main's red `cityLayout.f1.test.ts` fixed via tri-state `forceFlag` seam; OFF-parity coverage kept; go-live locked in. |
| 4 | `test: lock in derive-on-load legacy restore under flag-on` | The user-ratified (2026-07-09) F1 restore behavior asserted under shipped config, incl. the flag-ON byte-identity guarantee PR #82 dropped. |
| 5 | `fix: clear surface decals when a building is demolished or burns` | Murals no longer float over rubble (+7 tests). |
| 6 | `chore: add ci running backend pytest plus web vitest and tsc` | First CI for this repo; would have caught the red-main incident. Minor follow-up: add an explicit `permissions: contents: read` block. |
| 7 | `docs: backfill ledger for #75-#83, file em-300..306, refresh start-here` | Intake gap from the no-Fable window closed. |
| 8 | `fix: reserve the final bounce attempt for the auto backstop` | Verify-round remediation (Fable agent): `auto` was structurally unreachable (max_attempts=3 eaten by the top-3 curated lanes) — now the terminal `auto` lane is guaranteed the final slot (`max_attempts` 3→4, 3 curated + reserved auto); bounce outcomes credit the lane that actually served (capped pins stay skipped); bounded sick-pin recovery probe reuses the #76 cadence; production-shaped 9-lane test closes the toy-universe blind spot. |
| 9 | `docs: reconcile ledger sweep and record w30 loop ends` | EM-268/298 dedupe per ledger convention, closure rows for the audit intake + W30, START-HERE recently-merged refresh, spec W30 amendment (reserved slot, max_attempts 4), EM-307 filed, manifest closed out. |

## Verify results (workflow: QE gate + 3 lenses + Fable adversarial verification)

- **QE gate: proceed=true.** Contract conformance 5/5, security 5/5, anti-cheat pass confirmed no assertion weakened anywhere (coverage strictly UP).
- **Fable verifiers confirmed 5 real findings** (2 code, 3 docs) out of 9 raised; all 5 fixed same-build (commits 8–9). 4 refuted/info — including confirming the `forceFlag` change is production-safe and that the EM-205 detour counters going dark under adaptive is intentional layering.

## Model-routing scorecard (the mission's explicit test)

- **Haiku** (docs-mechanical): clean format-by-example closure rows — but its half of the A6/A7 split left a reconciliation seam (stale "pending A6" notes) the verify round had to fix. Right tier for the work, needs a reconciliation check when splitting one ledger across two agents.
- **Sonnet** (5 roles): all delivered green on first pass; the CI agent's validation discipline (pip --dry-run, YAML parse, real command dry-runs) was notably good.
- **Opus/xhigh** (adaptive-delivery flagship): strong implementation with honest design notes — but shipped the reserved-backstop blind spot behind a toy-shaped test. Exactly the class of miss adversarial verification exists for.
- **Fable**: lead (architecture, contracts, gates, synthesis) + adversarial verification (confirmed the major routing defect with an executable repro; refuted 4 plausible-but-wrong findings) + the remediation commit 8 (+9 tests, zero regressions, two well-argued design deviations).

## Handoff items (user decisions / next actions)

1. **Merge when ready** — branch is self-contained. After it lands on main, **PR #84 needs a trivial rebase** (both touch `router.py`).
2. **After merge: reconcile the LIVE tree** — the main working tree (on `fix/timeout-error-handling`) still carries the now-superseded uncommitted `config/lanes.yaml` + `config/profiles.yaml` diff; discard it (`git checkout -- config/`) once the branch containing these commits is current there, then **restart the sim** — config is baked per-run, so runs 1371/1372 keep `max_attempts=3` (and the old router code) until a restart.
3. **F1 visual sign-off still owed** (live session, watching cluster-accretion in the UI) — the only remaining F1 gate; also note the first restore of the pre-F1 live DB will re-place old buildings (ratified; consider `VACUUM INTO` backup first).
4. **Churn expectations**: W30 makes bounces real (sick pins walk, `auto` guaranteed) but cannot manufacture capacity in a genuinely dry rate window; PR #84 (timeouts) + the Ollama overflow lane (EM-167) are the remaining levers (see EM-301).
5. **Deferred with reasons**: EM-304 router dead-state removal (avoids PR #84 conflict), EM-305 flicker/yellow-tile bug (needs a dedicated browser-driven repro session), EM-306 dead reasoning-skip wiring, EM-307 attribution concurrency hazard, CI `permissions:` hardening nit.

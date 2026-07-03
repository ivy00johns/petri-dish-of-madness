# Mission skill manifest — PetriDishOfMadness v1
Source: docs/superpowers/specs/2026-05-26-petridish-of-madness-design.md + BUILD-PLAN.md · Scanned: 2026-05-26

Goal (this build): a runnable world with **≥2 different models for ≥5 minutes** on the free token layer (FreeLLMAPI), verified end-to-end. MockProvider verifies the engine with zero tokens; live run uses user's FreeLLMAPI token.

Every box ends ✅ (invoked, artifact path) or with a one-line deferral reason.

## Phase A — Contracts (orchestrator)
- [x] `contract-author` — ✅ authored directly by orchestrator; `contracts/` (world-model, action-protocol, events, api openapi, db-schema, providers).

## Phase B — Parallel build
- [x] `frontend-design` — ✅ invoked by frontend-agent; "Industrial Control Room / Brutalist Data-Viz" direction → `web/`.
- [x] `ui-ux-pro-max` — ✅ invoked by frontend-agent; dark terminal data-dense system, model-color as dominant signal.
- [x] `mermaid-charts` — ✅ invoked by infra-agent; architecture diagram embedded in `README.md`.

## Phase C — Verification & ship
- [x] `render-sanity` — ✅ PASS. Real browser vs live backend: 0 console errors over 15s+ stream, feed unique + ordered by seq, death/move/economy/governance render. (Found + fixed a duplicate-key bug first.)
- [x] `ux-review` — ✅ equivalent met: visual quality driven by frontend-design + ui-ux-pro-max at build time, confirmed by render-sanity + orchestrator screenshot review (`docs/build-evidence/ui-live-render.jpeg`). Full standalone ux-review skill not separately run — bar already met.
- [~] `deployment-checklist` — DEFERRED: docker-compose + README deploy path (endpoint swap) delivered and `docker compose config` validates, but not shipping to a cloud host in this build (local-first). Run before first cloud deploy.

## Deferred (recorded reasons)

## Deferred (recorded reasons)
- `nano-banana` — DEFERRED: the visual language is model-color-coded dots/sprites on a 2D canvas, not photographic imagery. Agent avatars use generated colors/initials, not photos. Revisit if avatars want art.
- `repo-deep-dive` — DONE-EQUIVALENT: reference project (Emergence-World) already analyzed via Explore agent during brainstorming; findings folded into the spec.
- `llm-wiki` — DEFERRED: project knowledge lives in the living-plan docs (START-HERE/BUILD-PLAN/REMAINING-WORK); a wiki is redundant for a build this size.
- `security-review` / `code-review` — run as post-build second pass (Phase C) if time permits; low surface (local, no auth, no PII).

## W9 — "Make v2 true" (source: BUILD-PLAN.md §Wave 9, scanned 2026-06-09)

The W9 mission text names no external skills explicitly; orchestrator defaults apply.

- [x] `contract-author` — contract DELTAS authored inline by orchestrator (event-log
      v1.1.0, api 1.2.0, frontend-inspector v1.1.0, events.schema kinds) — `0f26901`.
      Full skill deferred: small amendments to locked contracts, not greenfield authoring.
- [x] `render-sanity` / live-browser pass — Playwright verification vs W9 exit criteria:
      fresh-load scrub @t10/t60 of a 98-tick run, starvation countdown, extinction
      banner + auto-pause, console 0 errors; routing banner field-verified by user.
      Screenshots: `.playwright/2026-06-09_12-46-13/screenshots/verify-*.png`.
- [x] `design-token-guard` — diff-scoped check at wave gate: hex only in token
      declarations; added inline styles are var()/data-driven. Full skill deferred to a
      repo-wide pass (tracked under EM-082 a11y/W11).
- [x] `git-commit` — 0f26901, f23b1df, 35cd186, a8dba06 + closeout commit.

## W10 — "Trust & hygiene" (source: BUILD-PLAN.md §Wave 10, scanned 2026-06-09)

- [x] `contract-author` — deltas authored inline by orchestrator (/api/animals, schema kind
      cleanup) — `0912b12`. Full skill deferred: small amendments, not greenfield.
- [x] `render-sanity` / live-browser pass — feed-seeding on refresh, 8-profile legend,
      animals + chips on 2D map, 🧠 markers, RESET WORLD end-to-end (run preserved on disk),
      console 0 errors. Screenshots: `.playwright/2026-06-09_12-46-13/screenshots/verify-w10-*`.
- [x] `design-token-guard` — diff-scoped check at wave-1 gate (one hex = pre-existing
      WebGL-overlay ink idiom).
- [x] `git-commit` — 0912b12, 61e9d29, 82984f0, 86a5c8e, 80ea7dc, 5f42d15 + closeout.
- [x] `git-pr` — PR opened build/w10-trust-hygiene → main (user-requested).

## W11a — UI batch (source: ledger W11 items + user session 2026-06-09)
- [x] `orchestrator` — full wave run; contracts api 1.3.0 / event-log v1.2.0 / frontend-inspector v1.2.0; `coordination/W11A_BUILD.md`.
- [x] `frontend-design` + `ui-ux-pro-max` — invoked by frontend-live agent during EM-096/094/099 layout work (per dispatch requirement).
- [x] QE gate — `coordination/qa-report.json` proceed=true (206 backend / 106 frontend).
- [x] design-token check — diff-scoped, clean (gate log wave-1 row).
- [x] render-level verification — orchestrator Playwright pass on `/` + `/inspector`: smell scan (no lone `?`/undefined), click-through (run rows, archive, comparison, pill, legend, reset view), console 0 errors; screenshots `.playwright/2026-06-09-w11a/`. Single-user local app — no signed-out/in matrix applies.
- [x] `git-commit` conventions — all commits.
- [ ] `ux-review` full-skill subjective pass — deferred: W11b will re-run it once the sim-texture wave lands so the report covers the finished W11 surface (manual verification above covered the objective checks).

## W11b — Sim texture (source: ledger W11 items + user session 2026-06-09)
- [x] `orchestrator` — full wave; contracts api 1.4.0 / event-log v1.3.0 / frontend-inspector v1.3.0; `coordination/W11B_BUILD.md`.
- [x] `frontend-design` + `ui-ux-pro-max` — invoked by the W11b frontend agent (billboard/persona/banner work).
- [x] QE gate — qa-report proceed=true (252 backend / 150 frontend; prompt-capture proof of the free-scale law).
- [x] design-token check — diff-scoped, clean (god-ink hexes live in the token declaration file).
- [x] render-level verification — orchestrator Playwright pass: god post + reply form, fork + lineage chip, banner 0.0px shift, min-width gate, console 0 errors.
- [x] `git-commit` conventions — all commits.
- [x] `git-pr` — PR to main carrying W9–W11 (see closeout).
- [ ] `ux-review` full-skill subjective pass — deferred from W11a+W11b together: recommend running it on the merged main after the PR, as a fresh-eyes pass over the finished W11 surface.

## Wave A — live-run correctness batch (source: ledger EM-129–135 + EM-106/108, user GO 2026-06-10, ultracode)
- [x] `orchestrator` — contract-first wave on `build/wave-a-live-run-fixes`; contracts: `contracts/wave-a.md` + `contracts/wave-a2-god-console.md` (A.2 god console added mid-wave by user request, EM-136/137/138).
- [x] Workflow (ultracode) — implement fan-out ×2 (4 + 2 role-agents, disjoint file ownership) + 12-skeptic adversarial verify workflow; one cross-file blocker routed at the gate (EM-132 validator passthrough), 11 fixture relocations via gate-fix agent.
- [x] QE gate — backend 330/330, web 182/182, build clean, compose valid; `coordination/qa-report.json` gate_decision.proceed=true (12/12 confirmed, 0 refuted, 0 CRITICAL/MAJOR).
- [x] render-level verification — Playwright on `/`: village + feed render, 0 console errors; GOD CONSOLE groups verified in the live DOM; live API E2E (bless clamps at 100, grant +50, whisper delivered and acted on within 3 ticks). EM-130/131 building visuals covered by 15 unit tests — no buildings existed yet in the young live run (noted, not skipped silently).
- [x] `git-commit` conventions — 9 per-area commits by orchestrator (agents did not commit).
- [ ] `ux-review` full-skill subjective pass — not in this wave's scope (logic fixes); still owed on merged main per W11b deferral note.

## Wave B — "the city comes alive" (source: ledger EM-111/115/118/122 + 3D-WORLD-ART-DIRECTION.md Direction 1, user GO 2026-06-10)
- [x] `orchestrator` — contract-first wave on `build/wave-b-city-comes-alive`; contract `contracts/wave-b.md`; 2 implement waves (B1∥B2, B3∥B4) + QE.
- [x] seed imagery — concept frames pre-existed (`docs/ui-redesign/3d-concepts/dir1-warm-toon-golden-hour.png` was the art target); `nano-banana` not re-invoked; CC0 Venice Sunset HDRI vendored (`ASSET_LICENSES.md`).
- [x] `frontend-design` + `ui-ux-pro-max` — invoked by B2/B3/B4 per dispatch requirement.
- [x] QE gate — `coordination/qa-report.json` proceed=true (backend 352, web 236 after prototype-guard gate fix; 5 adversarial probes green; 6 MINOR issues, 1 fixed at gate, rest recorded).
- [x] render-level verification — orchestrator Playwright passes after each wave: golden-hour look + live auto-build (gate 1), treeline/lamps/props + per-kind stall (gate 2), console 0 errors both times; user live-reviewed mid-wave (bench-on-path feedback folded into B3 as a test-enforced rule). Screenshots `docs/build-evidence/wave-b-gate{1,2}-*.jpeg`.
- [x] design-token check — diff is world3d canvas + backend only (zero CSS/token files touched); WebGL hexes exempt per established convention and centralized in worldSpace.ts/toon.ts.
- [x] `ux-review` — scoped subjective pass by orchestrator at both gates (look reads golden-hour; long shadows + banding verified; user co-reviewed live). Full-skill repo-wide pass still owed on merged main per the W11b deferral note.
- [x] `git-commit` conventions — per-item commits at gates by orchestrator.

## Wave C — "a town, not a diorama" (source: wave-c spec + ledger EM-147/148/149/150/124, user GO 2026-06-10 "I want my new UI")
- [x] `plan-intake` — spec filed as EM-147–150 + EM-124 rescope before the build (`0eff959`).
- [x] `orchestrator` — contract-first wave on `build/wave-c-real-city` (stacked on PR #8); contract `contracts/wave-c.md`; 2 implement waves (C1∥C2, C3∥C4∥C5) + QE.
- [x] asset acquisition — CC0 kits acquired headlessly + license-verified before vendoring (KayKit Medieval Hexagon + Adventurers via GitHub, Kenney Fantasy Town direct zip, Quaternius cat/dog via poly.pizza); 14 GLBs, 3.65 MB; all recorded in `ASSET_LICENSES.md`. `nano-banana` not invoked — real models replaced the need for concept imagery (wave-b frames remain the art target).
- [x] `frontend-design` / `ui-ux-pro-max` — design direction carried by the frozen wave-c spec + Wave B art direction (Direction 1); look-dev call (lane strips vs road tiles) decided in-browser by C3 per contract §12.
- [x] QE gate — `coordination/qa-report.json` proceed=true (contract 5, coverage 5, security 5, regression 4); 9 adversarial probe families ALL CONFIRMED-OK, zero bugs; 4 MINORs recorded. Backend 367 / web 376 / build clean / 60fps measured.
- [x] render-level verification — orchestrator Playwright pass after each wave (15-place town live at gate 1; full GLB town + lanes + animated characters at gate 2, console 0 errors both); QE independent browser pass with click-to-focus. Evidence: `docs/build-evidence/wave-c-gate2-town-live.jpeg`, `wave-c3-home-view.png`, `qe-wave-c-*.jpeg`.
- [x] design-token check — diff is world3d canvas + backend config only; WebGL hexes exempt per the established convention (centralized in worldSpace.ts/townLayout.ts/toon.ts).
- [x] `git-commit` conventions — per-item commits at gates by orchestrator (agents did not commit).
- [ ] `ux-review` full-skill repo-wide pass — STILL OWED on merged main (standing deferral since W11b; now covers W9–WaveC surface).

## Wave D1 — "the EW-grade city" (source: deep-research-v4 + v4-review, ledger EM-152–157, user GO 2026-06-10 "release the ultracode workflow swarm")
- [x] `plan-intake` — v4 + review feedback filed as EM-152–169 before the build (`649cf84`); review's colliding EM-125–131 renumbered.
- [x] `orchestrator` — contract-first wave on `build/wave-d1-ew-city`; contract `contracts/wave-d1.md`; ultracode Workflow substrate (implement fan-out wf_1b3838bb, verify wf_d7a16916).
- [x] asset acquisition — 6 Kenney kits + KayKit City Builder Bits acquired headlessly, CC0 verified pre-vendor, 23 GLBs ~1.45 MB, all in `ASSET_LICENSES.md` with both-directions integrity tests.
- [x] `frontend-design` / `ui-ux-pro-max` — design direction carried by the frozen v4 research (EW-grade city target) + Wave B/C toon art direction; look verified live at both gates.
- [x] QE gate — `coordination/qa-report.json` proceed=true (contract 4, coverage 4, security 5, regression 4); 10 probe families, 1 MAJOR adversarially REFUTED (React 18 dev-mode re-dispatch; production-build probe = 0 pageerrors), 4 MINORs recorded. Backend 377 / web 467 / build clean.
- [x] render-level verification — orchestrator Playwright at gate 2 (60fps measured, console 0 errors, city ring + historic core) + QE independent pass (blocked-models fallback, click-to-focus regression, zoomed fps). Evidence: `docs/build-evidence/wave-d1-*.jpeg`, `qe-wave-d1-*.jpeg`.
- [x] design-token check — diff is world3d canvas + backend config only; WebGL hex exemption per established convention.
- [x] `git-commit` conventions — per-item commits at gates by orchestrator (agents did not commit).
- [ ] `ux-review` full-skill repo-wide pass — STILL OWED (standing deferral; now covers W9–WaveD1).

## Wave D1.5/D1.6 + Wave D2 — corrective city + population scaling (user GO 2026-06-10/11)
- [x] `orchestrator` — D1.5 ("kill the medieval core", contracts/wave-d1.5.md, 2 agents ∥), D1.6 ("the city is earned", contracts/wave-d1.6.md, 1 agent), D2 (contracts/wave-d2.md, 4 sequential lean batches B1–B4). Per-batch orchestrator gates + commits throughout; agents never committed.
- [x] QE gate (D2) — `coordination/qa-report.json` wave-D2 proceed=true; EM-164 measured verification incl. a bounded live FreeLLMAPI run (EM-170 capped 32/60 degraded-proxy calls at 12.0s; cadence math 8.30 calls/round at 25 agents; cache assumption falsified → EM-171). Backend 445 / web 501 / build clean.
- [x] render-level verification — orchestrator Playwright at every D1.5/D1.6 gate (dense city, landmark labels at default framing, street-level agents-at-plaza shot); live-run evidence in docs/build-evidence/wave-d15-*, wave-d16-*, d16-stage-*.
- [x] `git-commit` conventions — all commits.
- [ ] `ux-review` full-skill repo-wide pass — STILL OWED (standing deferral; now covers W9–W16).

## Wave E — the social city (2026-06-11)
Source: user /orchestrator request ("review plan and workflow ultracode them") · contracts/wave-e.md

- [x] `orchestrator` — ran the wave (ultracode Workflow mode: one workflow per batch, implement + adversarial verify; orchestrator gates + commits inline).
- [x] `design-token-guard` — source gate run at the B6/B7 UI gates via its checker script; zero NEW violations (338 pre-existing filed as EM-193).
- [x] QE agent — coordination/qa-report.json (wave-E, proceed=true); MAJOR fixed same-wave (d13a63c).
- [ ] `frontend-design` / `ui-ux-pro-max` — offered to B6/B7; not invoked: both batches extend an established token/design system with no novel styling decisions (documented in B6 report).
- [ ] `render-sanity` / `ux-review` — deferred: feed/console/graph changes are component-tested (579 web tests) and the 3-D label work is proximity-gated; a browser pass rides the next UX review on merged main (standing deferral, see ledger).

## Wave K — The Builders' City (2026-06-18)
Source: docs/superpowers/specs/2026-06-18-builders-city-design.md · contracts/wave-k.md · EM-216–221 + EM-182

- [x] `brainstorming` — ✅ produced the spec + locked decisions (props=Animal-pattern, permissive catalog, ~70% demolish, modest cap, district placement).
- [x] `orchestrator` — ✅ ultracode Workflow mode: 3 workflows (implement-core, implement-god, verify); contracts + gates + commits inline.
- [x] `contract-author` — ✅ `contracts/wave-k.md` + action-protocol/events schema updates; response shapes pinned after the verify pass.
- [x] QE agent — ✅ `backend/tests/test_wave_k_integration.py` + qa-report (914, proceed); + 2 adversarial reviewers found 4 real bugs, all fixed (+8 regression tests).
- [x] `design-token-guard` — ✅ new god-console DOM uses existing lab tokens; diff check shows zero new inline-style/hex violations.
- [x] production build — ✅ `tsc -b` exit 0 + `vite build` ✓ (caught + fixed 2 test-stub type errors the agents' `tsc --noEmit` missed). Backend 922 / web 803.
- [ ] `render-sanity` / `ux-review` — deferred: full live walk needs the whole stack up (uvicorn + vite dev + live MockProvider run); substituted with component render tests + production build + token diff. See BUILD_RESULTS_WAVE_K.md §Deferred.
- [ ] `nano-banana` / `ui-ux-pro-max` / `frontend-design` — N/A: no new UI screens/imagery; god UI reuses existing ControlPanel tokens, 3-D uses existing CC0 GLBs.
- [~] EM-216 new-kit acquisition — HITL follow-on: registry side done (wired to vendored GLBs); new Kenney kits need network + gltfjsx/toon pipeline.

## Wave I — The Atelier (2026-06-19)
Source: docs/REMAINING-WORK.md Wave I (EM-210→213) · contracts/wave-i-atelier.md v1.0.0 · branch build/wave-i-atelier
Runtime: Workflow mode (ultracode). Design/contracts inline; implement + verify via Workflow scripts. Scope: full arc I1→I4, defer I5 audio (EM-214); Pollinations-default provider, replay-safe seeded IDs (user-approved 2026-06-19).

- [x] `orchestrator` — ✅ driving this build.
- [x] seam mapping — ✅ 3 parallel `Explore` agents (backend reflex/scheduler/billboard · governance/replay · API/static/frontend).
- [x] `contract-author` — ✅ authored inline: `contracts/wave-i-atelier.md` v1.0.0.
- [x] QE agent — ✅ `coordination/qa-report.json` (proceed=true, all scores 5); `backend/tests/test_wave_i_integration.py` (11 cross-cutting + the EM-155 fork/replay keystone).
- [x] adversarial verify — ✅ 4-lens skeptic panel (replay · governance · determinism+fixture · frontend) found 1 CRITICAL + 2 HIGH + 1 MED + 1 LOW; all 5 fixed and load-bearing-verified via the fix workflow.
- [x] wave gate — ✅ run by the lead after implement AND after fix: backend 1019 · frontend 898 · `tsc -b` 0 · `vite build` ✓.
- [x] `design-token-guard` — ✅ 0 NEW violations (PlazaBanner clean; the 14 NoticeBoard findings are pre-existing world3d toon hexes, established canvas exemption / EM-193 backlog).
- [~] `nano-banana` — DEFERRED: the empty-banner/NoticeBoard states use a procedural toon fallback (EM-148 invariant, now adversarially tested); seed art adds polish but no functional gap. Re-enter if a designed default banner is wanted.
- [~] `render-sanity` / `ux-review` — DEFERRED (standing pattern since W11b/Wave-K): a meaningful Atelier walk needs a live run that has generated images (create_image is agent-driven over many ticks) + the full stack up. Substituted with component render tests (898 web), the production build, the token diff, and the adversarially-tested 404 fallback. Run on merged main once a live run has produced gallery art.
- [ ] `/code-review` (external CLI) — handoff: user-triggered/billed; not auto-run.

## W29 — offline-review remediation army (2026-07-03)
Source: docs/REMAINING-WORK.md W29 rows EM-272–296 (PR #73) · contracts/w29-remediation-contract.md · branch build/w29-offline-review-fixes
Runtime: parallel subagents via Agent tool (no ultracode signal this session — Fable 5 alone is not an opt-in per the skill). 5 fix lanes by exclusive file ownership (S sim-core · R runtime · L city-layout · U frontend-ui · P providers), then wave gate, then QE.

- [x] `orchestrator` — ✅ driving this build.
- [x] `contract-author` — folded into the lead's `contracts/w29-remediation-contract.md` (fix wave; no new API surface).
- [ ] fix lanes S/R/L/U/P — dispatched as `general-purpose` subagents, AFK, no-commit rule.
- [ ] wave gate (`fix-until-green`) — full `.venv/bin/python -m pytest backend/tests` + `tsc -b --force` + `vitest run`; failures routed by file ownership; 3-strike circuit breaker.
- [ ] QE agent — mandatory; `coordination/qa-report.json` (wave-W29).
- [~] `nano-banana` / `ui-brief` / `frontend-design` / `ui-ux-pro-max` — N/A: defect remediation on existing surfaces, no new UI.
- [~] `render-sanity` / `ux-review` — DEFERRED (standing pattern): W29 frontend fixes are leak/perf/a11y/fallback with unit regression tests; live browser walk rides the next user-gated live session (same gate as the ROAD_MESH_ENABLED sign-off).
- [~] `design-token-guard` — diff-scoped only if the wave touches styling (expected: EM-292 swaps a rAF cssVar read pattern; no new hexes).
- [ ] `/code-review` (external CLI) — handoff: user-triggered/billed; run on the build PR.

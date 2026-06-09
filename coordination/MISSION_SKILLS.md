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

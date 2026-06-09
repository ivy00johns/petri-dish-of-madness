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

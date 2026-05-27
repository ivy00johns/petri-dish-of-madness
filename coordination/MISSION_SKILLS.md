# Mission skill manifest — EmergenceMadness v1
Source: docs/superpowers/specs/2026-05-26-emergence-madness-design.md + BUILD-PLAN.md · Scanned: 2026-05-26

Goal (this build): a runnable world with **≥2 different models for ≥5 minutes** on the free token layer (FreeLLMAPI), verified end-to-end. MockProvider verifies the engine with zero tokens; live run uses user's FreeLLMAPI token.

Every box ends ✅ (invoked, artifact path) or with a one-line deferral reason.

## Phase A — Contracts (orchestrator)
- [ ] `contract-author` — authored directly by orchestrator (contracts well-specified by spec); produces `contracts/*`.

## Phase B — Parallel build
- [ ] `frontend-design` — frontend-agent MUST invoke during build; produces `web/` UI.
- [ ] `ui-ux-pro-max` — frontend-agent MUST invoke during build; informs map/feed/panel design.
- [ ] `mermaid-charts` — architecture diagram in README; produces a diagram in `README.md`/`docs/`.

## Phase C — Verification & ship
- [ ] `render-sanity` — hard gate; walk the live UI, four checks must PASS.
- [ ] `ux-review` — subjective visual pass after render-sanity.
- [ ] `deployment-checklist` — ship readiness for docker-compose local + cloud path.

## Deferred (recorded reasons)
- `nano-banana` — DEFERRED: the visual language is model-color-coded dots/sprites on a 2D canvas, not photographic imagery. Agent avatars use generated colors/initials, not photos. Revisit if avatars want art.
- `repo-deep-dive` — DONE-EQUIVALENT: reference project (Emergence-World) already analyzed via Explore agent during brainstorming; findings folded into the spec.
- `llm-wiki` — DEFERRED: project knowledge lives in the living-plan docs (START-HERE/BUILD-PLAN/REMAINING-WORK); a wiki is redundant for a build this size.
- `security-review` / `code-review` — run as post-build second pass (Phase C) if time permits; low surface (local, no auth, no PII).

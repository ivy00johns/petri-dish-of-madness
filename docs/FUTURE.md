# PetriDishOfMadness — Future / Out of Scope (frontier)

Explicitly **not** in v1. Kept here so they aren't lost and don't clutter the tactical
ledger. When a scope decision promotes one of these, give it an `EM-###` in
`docs/REMAINING-WORK.md` and remove it here.

Deferred from the design spec (§1 non-goals) and brainstorming:

- **TTS / voice** — agent speech as audio (the original used Google Chirp3-HD).
- **Victory-Arch pitch cycle** — periodic evidence-backed credit-grant competition. v1 economy is work/forage/give/steal only.
- **LLM memory summarization** — compressing old memories via the model (the original's big hidden cost). v1 uses a fixed rolling buffer + beliefs.
- **Agent-authored tools** — agents proposing and adding new tools via governance.
- **Real weather / news integrations** — live external data feeding the world.

## Atelier follow-ups (image generation shipped as EM-210 / Wave I)

- ~~**Gallery / artwork admin viewer**~~ — **SHIPPED 2026-06-21.** A read-only
  `GalleryPanel` (collapsible thumbnail grid + lightbox) rides under the billboard in the
  feed column: reads `world.gallery` (newest-first, degrades to deriving from
  `image_posted`/`image_promoted` history), badges the piece on `plaza_banner_ref` with
  ★ PLAZA, and degrades a 404'd PNG to a labeled placeholder. Also added the missing
  `/assets` dev proxy in `vite.config.ts` so the relative PNG urls resolve to the backend
  on :5173 (this also fixes the 3D PlazaBanner texture falling back to procedural in dev).
  Frontend-only, no new storage. 9 tests in `GalleryPanel.test.tsx`.
- **Credit-gated re-enables (parked 2026-06-21):** image generation is currently **OFF**
  (`world.image_gen.enabled: false`, the EM-210 kill switch) and EM-222 embeddings are on
  blind-recency fallback — the HF inference credit pool depleted (402). Flip
  `image_gen.enabled: true` and embeddings auto-recover once credits return. Per the
  subscription-only billing rule, do **not** buy credits to restore them early.

## Dev infra (low priority)

- **Don't fork an empty run on every hot-reload.** With `uvicorn --reload`, each backend
  edit restarts the worker and resume-on-boot (EM-187) forks a NEW run from the latest
  snapshot. The existing "skip tick-0 snapshots" guard misses the common case: the fork
  **inherits the parent's tick** (e.g. 4475) and never advances, leaving a 1-event
  `run_resumed` shell. Streaks of edits chain these, cluttering the run browser and
  needing periodic manual pruning (the `fork-cleanup-procedure` runbook: re-point kept
  children → delete `events==1` runs). Fix options: extend the resume guard to also skip
  a fork whose parent has only the boot event (no advanced turn), reuse the parent run
  instead of forking when nothing changed, or ship a prune endpoint/tool. **Low priority**
  — only bites during dev hot-reload streaks; cleanup is a known, quick procedure.

Promoted to `docs/REMAINING-WORK.md` (and removed above per the convention):
replay viewer → EM-055 (shipped, W6) · head-to-head analytics dashboard → EM-059
(shipped, W6) · reactive overhearing chains → EM-081 (shipped, W11b) · image generation
→ EM-210 (shipped, Wave I — The Atelier) · multi-world parallel runs → EM-112 (open, W12)
· multiple cities + transport → EM-109/EM-110 (open, W12).


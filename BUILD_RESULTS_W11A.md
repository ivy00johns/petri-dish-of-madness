# W11a Build Results — "UI batch"

**Branch:** `build/w11a-ui-batch` (stacked on `build/w10-trust-hygiene`) · **Date:** 2026-06-09
**Contracts:** api.openapi.yaml **1.3.0** · event-log.md **v1.2.0** · frontend-inspector.md
**v1.2.0** (§8 run browser, §9 live view incl. the chat-first priority amendment).
**Gates:** wave-1 GREEN → QA GREEN (proceed=true) → live verification GREEN.
Full gate log: `coordination/W11A_BUILD.md`.

## What shipped

| Item | Result |
|---|---|
| EM-086 run browser | `GET /api/runs` (active = loop-held MAX(id), never the unreliable status column; `ended_at` added by migration) + `run_id` scoping on all 7 read endpoints (unknown → 404); inspector RunBrowser panel, archive mode (live merge disabled, run-scoped backfill/replay/roster, "back to live"), cross-run AWI comparison with deltas. Verified against 27 real runs on disk |
| EM-093 scroll stability | Frozen-snapshot feed: un-pinned = literal row snapshot, arrivals mutate nothing (root cause was the 200-cap bottom trim). Measured live: **0.00px viewport drift**, "↑ N new" pill, click/edge re-pin |
| EM-094 story so far | Zero-LLM digest selector (`lib/storySoFar.ts`: roster+deaths, rules, projects, drama heuristic) atop the feed + optional backend **Narrator mode** (`world.narrator`, off by default, one rate-limited free-profile call per window, failure emits nothing, never stalls the loop) |
| EM-095 camera nav | Pan (bounded), zoom-to-place on building click, follow-agent/critter (user drag always escapes), RESET VIEW — drei OrbitControls only, zero new deps |
| EM-096 layout | Chat-first redesign per user sketch + priority ("chat is the central figure"): digest + 432px default feed left, full-height village center (~1.5–1.7× pixels, bounded by feed-wins rule), roster strip riding the village's bottom edge, controls right. No info loss |
| EM-097 | SocialGraph captured-instance cleanup (React 18 ref-detach safe); regression pin un-xfailed — W10-QA-1 closed |
| EM-099 critters in roster | CRITTERS group on the strip: species, name, mood, model chip, location, CHAOS ×n; click-to-follow like agents |
| EM-102 (user, in-wave) | Distance-gated 3D labels with hysteresis: full label near/hovered/focused, mini markers otherwise; zoom-to-place reveals the target's label |
| EM-104 (user, in-wave) | Collapsible "MODELS (8)" legend, persisted |
| EM-105 (user, in-wave) | Drag-resizable feed column (280px ↔ 50vw, persisted, dbl-click reset, keyboard nudge) |
| Animal replay exactness | `animal_action` moves now carry `payload.place` (EM-086 note 3 closed) |

## QA

Backend **206/206** (+18 `test_w11a.py`: RunRow/zombie-run/aggregates, run_id scoping +
404s across all endpoints, narrator on/off/failure/cadence, animal place). Frontend
**106/106** across 16 files (+43: storySoFar, archiveAgents, api run-scoping, RunBrowser,
EventFeed freeze; xfail pins now 0). contract_conformance 5/5, security 4/5, zero
blockers. Wave-1 src passed every new test on first run.

## Live verification highlights

27 runs on disk rendered with exactly **one** ACTIVE chip — the zombie `status='running'`
rows (every crash/hot-reload ever) correctly read ARCHIVED, which was the EM-086 trap.
Archive mode on run 26: banner + live-feed-disabled + scrubber bounded to tick 78.
Scroll freeze measured at literally 0.00px drift while the sim ticked. Console: 0 errors
for the whole session. Screenshots: `.playwright/2026-06-09-w11a/`.

## Notes & carries

- QE INFO: narrator **skips** (never queues) a window whose call is still in flight —
  in-contract; sparse summaries on slow providers are by design.
- `AgentPanels.tsx` is unused by the live route (roster strip replaced it); kept because
  its test imports it. Candidate deletion in W11b cleanup.
- README Deploy section still says "no persistent storage needed" — now wrong in Docker
  (`data/` wants a volume). Queued for W11b docs pass.
- Mock generator emits no `narrator_summary`; mock mode shows the labeled off-state.

## Handoff

- **W11b (sim texture) is next:** EM-079 commitments/phantom-commitments, EM-080
  reflection/diary, EM-081 overhearing, EM-082 mobile/a11y, EM-083 blackout+usage alerts,
  EM-087 duplicate-law semantics, EM-091 billboard, EM-092 persona library, EM-098
  procgen town + housing, EM-100 rule names, EM-101 run fork/resume, EM-103
  legislation-as-architecture guard.
- PR #4 (audit + W9 + W10) still open to `main`; W11a is NOT in it — branch
  `build/w11a-ui-batch` awaits either a PR of its own or stacking after #4 merges.

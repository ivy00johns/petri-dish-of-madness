# W9 Build Results — "Make v2 true"

**Branch:** `build/w9-make-v2-true` (off `build/v2-expansion`) · **Date:** 2026-06-09
**Commits:** `0f26901` (contracts+plan) · `f23b1df` (backend) · `35cd186` (frontend) ·
`a8dba06` (QA fix + tests) · closeout (docs)
**Gates:** wave gate GREEN → QA gate RED→GREEN (fix-forward) → live verification GREEN.
Full gate log: `coordination/W9_BUILD.md`.

## What shipped

| Item | Result |
|---|---|
| EM-069 deep replay | Inspector backfills the FULL run from `/api/events` on mount (verified: 869 events after a fresh page load), scrubs via `/api/replay` snapshot+delta, `onSeekTick` wired, panels pinned to the scrub tick (no live-edge bleed), labeled empty states everywhere, replay map made legible (names + contrast), `PanelStub.tsx` deleted |
| EM-070 survival pressure | Needs block in every turn prompt with explicit death countdown; recharge-at-full rejected with feedback and NO charge; `agent_starving` events (threshold cross + per-turn countdown at 0); `turns_until_death` in world_state + pulsing DYING badge; config `starving_warn_threshold: 25` |
| EM-071 extinction | `world_extinct` event + auto-pause (config `auto_pause_on_extinction: true`, god-kill path included); red EXTINCTION banner + end-of-run summary card (ticks, deaths in order, rules, crimes, top credit holder) |
| EM-072 routing banner | Dismissible "Routing degraded" banner when ≥2 profiles all resolve to one routed model — **field-verified the same afternoon on a real degraded FreeLLMAPI run** (all 3 profiles → ollama-cloud cogito-2.1:671b; root cause: free-tier RPD exhaustion, model IDs verified valid) |
| EM-073 backend batch | Animal turns get own turn_id (no trace contamination); `reset()` awaits the cancelled tick task + flushes decision cache; `ban_arson` proposable end-to-end; `build_step` accepts funded `planned` buildings; `llm_call` exactly once per attempt (structural de-dupe); `/api/replay` returns delta-only; snapshots carry round/turn-order state with post-tick boundary semantics |
| EM-074 frontend batch | Replay PLAY/PAUSE + speed buttons render real state; WS reconnect timer cleaned up on unmount + exponential backoff (2s→30s); force-graph pauseAnimation fixed (ref read at teardown); AWI gov column consistent per-proposer (passed/resolved); synthetic events use collision-free negative seqs |

**Contracts bumped (orchestrator):** event-log v1.1.0, api.openapi 1.2.0, frontend-inspector
v1.1.0, events.schema kinds (+`agent_starving`, `world_extinct`, `usage_sampled`).

## QA

`backend/tests/test_w9.py`: 24 new tests — per-attempt llm_call invariant, animal turn_id
isolation (incl. white-box in-flight sentinel), replay delta + an 18-tick fold-forward
**property test** that replicates the shipped frontend fold against per-tick ground truth,
recharge-at-full, starvation lifecycle, extinction (one-shot, config-off, god-kill, reset
re-arm, e2e DELETE), ban_arson, build_step, and the reset race (a hung provider cannot
mutate the rebuilt world). Suite: **172 passed / 0 failed / 1 intentional strict-xfail**.

**QA gate caught a real blocker** (W9-QA-1): the replay fold read the `agent_moved`
destination from the wrong payload key, so scrubbed positions were stale between snapshots.
Fixed forward (`payload.place` first, old keys as fallbacks), re-gated `proceed: true`.

## Live verification (W9 exit criteria)

1. ✅ Fresh page load vs a 98-tick run (snapshots @0/25/50/75): scrub to t10 and t60 renders
   correct agent positions and tick-scoped panels (this exact scrub was a black void in the
   morning audit).
2. ✅ Starvation: mock Bram emitted "starving — 3/2/1 turns until death" then died; survivors
   recharged. Needs are in the prompt; warnings render in the feed.
3. ✅ Extinction: god-killing the survivors emitted `world_extinct{tick:98, auto_paused:true}`,
   paused the loop, and rendered the banner + summary card.
4. ✅ Routing-degraded banner verified by the user on a genuinely degraded live run.
5. ✅ Console: 0 errors on both routes (one known benign dev-mode StrictMode WS line).

## Known issues carried forward (tracked)

- **W9-QA-1b** (MEDIUM): backend `analytics.space_exploration` reads the same wrong key —
  pinned by a strict xfail in test_w9.py; lands in **W10/EM-076**.
- Inspector status strip mixes scrub tick with live agent count (cosmetic) — W10/EM-075 polish.
- Scrubbed panel agents re-project `alive`/position only (energy/credits stay live) — full
  historical agent state is **W10/EM-075** replay fidelity.
- Mock generator doesn't emit `agent_starving`/`turns_until_death` (graceful absence) — add
  with **EM-043** test work if mock-mode demos need the countdown.
- **EM-079 scope note (ledger):** agents roleplay world changes without executing tools
  (zero `project_*` events while verbally "completing" a community garden) — phantom
  commitments must be logged as a failure mode.

## Handoff

- Branch `build/w9-make-v2-true` is complete and verified; **not merged** (say the word).
- Next waves: **W10** (EM-075–078 + EM-043), **W11** (EM-079–083).
- The dev backend runs with `--reload`; backend file changes reset the in-memory world —
  use a file `db_path` for runs you want to keep (event-log contract §6).

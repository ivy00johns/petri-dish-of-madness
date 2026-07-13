# MISSION — Overnight Expansion Build (2026-07-13)

**Author:** overnight orchestrator (autonomous). **Sleeper:** John (approved + went to bed).
**Source ideas:** `docs/research/2026-07-11-expansion-ideas.md` (Fable 3-lens panel, 26 ideas).

## What the user approved before bed
1. **model:auto fix — LIVE.** Stop routing/exhaustion errors from EVER rendering in the
   chat feed; replace the reserved terminal `auto` slot in `config/lanes.yaml` + routing
   code with a deterministic curated last-resort free lane. **No Ollama** (local = battery,
   cloud = "not using it"). Adopt live: back up `run.sqlite`, restart, unpause, verify calm feed.
2. **Build the Tier-1 batch** behind default-OFF flags, goldens + CI green, opened as PR(s).
3. **Ship mode:** auto-fix live; new features in PRs to flip in the morning.
4. **Durability is the #1 requirement** — the last overnight run died at ~2h (likely Mac sleep).
   This one must self-continue via loops. Mitigations in place: `caffeinate -dimsu -t 43200`,
   background workflow, ScheduleWakeup heartbeat that resumes/re-dispatches until done.

## Git hygiene (unattended)
- Commit with `--no-gpg-sign` (Touch ID would block; user asleep). `commit.gpgsign=false` set.
- Keep `Co-Authored-By: Claude Opus 4.8 (1M context)`. **Omit** the Claude-Session trailer
  and any session URL (public repo — standing rule).
- Every feature: own branch off `origin/main`, default-OFF flag, PR to `main`. No live flips
  except the approved model:auto fix.

## Standing laws (constraint-checked in the source doc)
$0-first · single-city deepening · **no throttling / MAX call-rate (never mute an agent)** ·
byte-identical determinism (sim-state → goldens; viewer/feed chrome → off replay surface) ·
EW-dense art target (not Stardew-cozy).

## Workspace
- Isolated build worktree: `/Users/johns/Projects/petri-dish-build` (branch base `overnight/base` == `origin/main`).
- Live sim stays on the MAIN checkout `/Users/johns/Projects/petri-dish-of-madness` (untouched by builds).
- Toolchain: `.venv/bin/python -m pytest`, `/usr/local/bin/npx tsc -b --force` (NOT `--noEmit`), `node_modules`/`.venv` symlinked into the worktree.

## Scope — IDs assigned (max was EM-308)
| ID | Feature | Tier | Wave | Risk |
|----|---------|------|------|------|
| EM-318 | model:auto feed-silence + curated terminal fallback | live-fix | 0 | adopt LIVE |
| EM-309 | The Blind Lineup (hidden model chips game) | T1 #1 | 1 | zero-LLM feed |
| EM-313 | Fingerprint Ticker (behavioral stylometry) | T1 #5 | 1 | zero-LLM |
| EM-314 | The Babel Matrix (dyadic inter-model heatmap) | T1 #16 | 1 | zero-LLM |
| EM-316 | The Drama Wire (salience index → breaking cards) | T1 #18 | 1 | feed scorer |
| EM-312 | Storylines Rail (feed notices its own drama) | T1 #4 | 1 | feed scorer |
| EM-310 | Chimera Twins (one persona, two brains) | T1 #2 | 2 | sim-state |
| EM-311 | Self-Authored Charters (agents rewrite identity) | T1 #3 | 2 | sim-state |
| EM-315 | The Healing House (society-wielded hot-swap) | T1 #17 | 2 | sim-state |
| EM-317 | The Prophecy Board (watcher omens, scored) | T1 #19 | 2 | sim-state |

## Exit criteria
Every feature: green (pytest + tsc) + PR open + flag default-OFF. Auto-fix adopted live with a
calm, running feed. Morning summary written with PR links + what needs a look.

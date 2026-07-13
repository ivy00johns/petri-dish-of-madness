# ☀️ Good morning — Overnight Expansion Build results (2026-07-13)

**You went to bed at ~01:00 asking to "wake up to a new world." It's done.**
Fable's 26-idea expansion panel → all **9 Tier-1 features + the model:auto fix** built,
tested green, and opened as PRs. The build ran **~4.9 hours, 21 agents, 0 errors, 0 blocked.**
The sim is **live and calm** right now.

---

## TL;DR
- ✅ **model:auto errors are gone from the chat** — adopted **LIVE** (PR #95). The sim is running
  (tick ~2383, `running:true`) and routing-exhaustion errors no longer render in the feed.
- ✅ **9 new features**, each behind a **default-OFF flag**, green (pytest + tsc), one PR each (#96–#104).
  Nothing changed in your live world except the auto-fix — flip a flag when you want to try one.
- ✅ **Ledger updated** (PR #94): EM-309..EM-318 filed into `docs/REMAINING-WORK.md` + `BUILD-PLAN.md`.
- ✅ Durable overnight: `caffeinate` kept the Mac awake, an isolated worktree kept the live sim
  untouched, and a heartbeat loop drove it to completion (this is what the last 2-hour run lacked).

## What's LIVE right now
**EM-318 — model:auto feed-silence + curated terminal fallback** (PR #95, merged into local `main`, adopted live):
- **Feed-silence (default ON):** provider-exhaustion / "All models exhausted" idle-fallbacks are
  dropped from the live feed (they still persist in the event log for determinism; agents are never
  muted — they retry next tick). Verified live: the one exhaustion event that fired was silenced.
- **Curated terminal fallback:** the blind `auto` last-resort slot is replaced by a deterministic
  free lane (`gpt-oss-120b`, cleanest-JSON) via `config/lanes.yaml → adaptive_routing.terminal_fallback`.
  Call-rate unchanged; set it to null to restore old `auto` behavior.
- **No Ollama** — as you said (local = battery, cloud = not using it).

## The 10 PRs (all green, flags default-OFF unless noted)
| PR | EM | Feature | Flag | Notes |
|----|----|---------|------|-------|
| **#95** | EM-318 | model:auto feed-silence + curated fallback | *(feed-silence ON)* | **LIVE now** |
| #96 | EM-309 | The Blind Lineup — hide model chips, guess, REVEAL + scorecard | `blind_lineup.enabled` (VITE_BLIND_LINEUP) | zero-LLM, frontend only |
| #97 | EM-313 | Fingerprint Ticker — zero-LLM behavioral stylometry, live "which model?" guess | `fingerprint_ticker.enabled` | retroactive over run.sqlite |
| #98 | EM-314 | The Babel Matrix — dyadic (speaker×listener model) social heatmap | `babel_matrix.enabled` | zero-LLM, click-through receipts |
| #99 | EM-316 | The Drama Wire — deterministic salience → BREAKING cards + camera | `drama_wire.enabled` | derived view, off replay surface |
| #100 | EM-312 | Storylines Rail — rivalries/arcs into a feed rail + 3-D tethers | `storylines_rail.enabled` | consumes the Drama Wire scorer |
| #101 | EM-310 | Chimera Twins — one persona, two brains (Vesper/Vesper II) + divergence card | `chimera_twins.enabled` | sim-state, determinism golden |
| #102 | EM-311 | Self-Authored Charters — agents rewrite an enum-grammar charter | `charters.enabled` | sim-state, determinism golden |
| #103 | EM-315 | The Healing House — trial/vote sentences a citizen to a model hot-swap | `healing_house.enabled` | sim-state, determinism golden |
| #104 | EM-317 | The Prophecy Board — enum-menu omens, deterministically scored | `prophecy_board.enabled` | god-channel, on replay surface |
| #94 | — | Ledger intake (EM-309..EM-318) | — | docs only |
| #105 | — | `dev` EM_RELOAD guard | — | tiny hygiene (the local-main tweak, now PR'd) |

**Wave 1** (zero-LLM / feed chrome, safe): EM-309/313/314/316/312.
**Wave 2** (sim-state, all shipped with determinism goldens): EM-310/311/315/317.

## How to review / try each feature
1. `gh pr checkout <#>` (or open the PR on GitHub).
2. Flip its flag ON (frontend: the `VITE_*` env / config; backend: `config/*.yaml`) and run `./dev`.
3. Each PR body has what/why/how-tested. Sim-state PRs include a determinism golden — spot-check it.
Merge order suggestion: **#94 (ledger)** and **#95 (already live)** first, then feature PRs in any order
(EM-316 before EM-312 if you care about the shared drama scorer landing first).

## Cleanup notes (no rush)
- **Live sim** runs on the MAIN checkout `main`, which carries the EM-318 merge (= PR #95) and the
  `dev` guard (= PR #105) as **local commits**. After you merge #95 and #105, you can
  `git fetch origin && git reset --hard origin/main` to tidy `main` — **that will also delete this
  file and `coordination/MISSION_OVERNIGHT_2026-07-13.md`**, so copy anything you want to keep first.
  (Or just leave `main` as-is — it works fine and the sim keeps running.)
- **DB backup** before the restart: `data/run.sqlite.bak-pre-em318-0713-0132` (947 MB) — delete when happy.
- **Restart note:** adopting EM-318 forked a fresh run at the snapshot tick (normal resume behavior) and
  I unpaused it. Old empty forks can be pruned later (your fork-cleanup procedure).
- **Isolated build worktree** `/Users/johns/Projects/petri-dish-build`: remove with
  `git worktree remove /Users/johns/Projects/petri-dish-build` (don't `--force`; commit anything first).
- **caffeinate** auto-expires at 12h (~13:00) — or kill it now that the build's done.

## Why it didn't die at 2 hours this time
The last overnight run almost certainly stopped because the **Mac slept**. This run: `caffeinate -dimsu`
held it awake, the build ran as a **background workflow** (survives context compaction), an **isolated
git worktree** kept build churn off the live sim, and a **~17-min heartbeat loop** verified health +
resumed on any stall. It never stalled — 21/21 agents finished clean.

*(Full per-feature agent summaries: workflow journal at
`.../subagents/workflows/wf_cbe7a261-00d/journal.jsonl`.)*

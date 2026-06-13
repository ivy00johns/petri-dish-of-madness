# Wave F — inspector at long-session scale · Build Results

> Branch: `build/wave-f-inspector-scale` (stacked on wave E / PR #12)
> Date: 2026-06-12 · Contract: `contracts/wave-f.md` (v1.1)
> Items: **EM-151, EM-194** — done (`wave-F 2026-06-12`).
> Trigger (user, live): "for a long session it's just an infinite scroll and
> useless… takes forever to finally render, I still haven't reached the
> bottom of the page." Measured at trigger time: 99,140 events on disk;
> boot paged ~50×1000 chunks to exhaustion; every scrub tick re-folded the
> full history through 4–6 O(n) selectors; zero virtualization; zero error
> boundaries (the run-#189 white-screen).

## What shipped

| Batch | Commit | Delivery |
|---|---|---|
| F1 | `c660f18` | `GET /api/events/stats` (total/max_seq/max_tick/min_seq, run-scoped) + honest desc tail (`before_seq` keyset, newest-first, overlap-free), asc path regression-pinned byte-identical. 12 tests, verify pass with zero findings. |
| F2 | `d83711d` | Tail-first boot (stats → newest chunk → RENDER, background backfill with "loaded N / total" progress; archive hook identical); incremental scrub projections — `agentEconomyAt`/`replayStateAt` re-expressed as fold seed/step/finalize so incremental == full **by construction**, cursor + checkpoint-LRU, golden test at 25 random-walk ticks; shared ascending-sort WeakMap cache benefits every selector; hand-rolled fixed-row `VirtualList` on AnimalChaosFeed + DecisionTrace rail (bounded-row tests at 10k events; critter dialogue kept inline at 2 lines, ROW_HEIGHT 96 — preserves 99f3822); per-panel `ErrorBoundary` with labeled fallback + retry; 50k-cap honesty strip + replay-path engagement pinned for the truncated case. 41 tests. |

Side commits riding the branch (user requests): `f9059d8` VITE_COFFEE_BUTTON
flag, `647ce34` single root `.env` (vite `envDir`, only `VITE_*` reaches the
browser) + README configure-step note (the pending README docs refresh
committed with it).

## Gates

Backend 705 → **717** · web 579 → **625** (+ build green). Token guard: the
two new inline styles in `VirtualList.tsx` are ratified geometry
(height/translateY — nothing a token could express); zero new color
violations (backlog stays EM-193's 338).

## Live verification (the actual complaint, re-run)

Real browser against the live stack: `/inspector` loads with 0 console
errors; archived **run #189 (40,842 events — the original white-screen
run)** shows archive content **16 ms** after clicking view, 0 crashed
panels, no truncation strip (40.8k < 50k cap, correct). `/api/events/stats`
live on the running backend via hot-reload.

## QE follow-ups filed

- **EM-195** (P3): extend the projector pattern to the remaining panel
  selectors (panelEvents identity busts the sort cache per scrub tick) +
  insert-sorted WS merge for events older than the history head mid-backfill.

## Notes

- GovernanceHistory deliberately not virtualized (bounded by rule count,
  variable-height cards) — contract-ratified.
- Existing inspector tests untouched all wave (golden lens checked).

## Handoff

- Stacked PR chain: merge PR #12 (wave E) first, then PR this branch.
- The archive view of very long runs now boots tail-first; scrubbing way
  back into a 100k+ run engages the snapshot+delta path — if any panel ever
  dies it now says so by name instead of blanking the annex.

# Overnight build — 2026-07-15 (Fable review sprint → Opus overnight)

**Mission:** review everything built without Fable, fix it, then burn the backlog overnight.
**Status at last update: review + fix pack SHIPPED; 3 Opus builders dispatched (1 done, 2 running).**

## Shipped tonight (done, verified)

1. **Fresh-context adversarial review** of all non-Fable work — 6 finders + per-finding skeptics
   (31 agents): **21 confirmed / 4 refuted**, incl. 1 reproduced CRITICAL (all-in-transit world
   freeze on the multi-city branch). Full report: `coordination/REVIEW-2026-07-15-nonfable.md`.
2. **Multi-city branch fixed** (`build/multi-city-expansion`, pushed):
   - `6d2b7e6` shadow boil/halo fix (PCSS→PCF) + zoom-distance DPR tiers (committed from the
     dangling working-tree edit after gates).
   - `a6b3491` **the critical**: tick fast-forward unfreezes all-in-transit worlds (replay-safe,
     +4 regressions incl. the reviewer's repro) + join-on-build home lock-step.
   - `90b4f24` travel markers use real trip lengths (backend formula mirrored); arrivals snap at
     the destination instead of gliding cross-map; comment corrections.
   - Gates: backend **2490/0** · tsc clean · vitest **1520/0**. Still pending: DoD #7 live
     sign-off (found a 2nd city, walk an agent across, watch the feed) — yours, needs `./dev`
     restart + reset.
3. **Fix pack → PR #108** (`fix/nonfable-review-pack`): all 16 main-code findings — war/justice
   (derived belligerence, exile-proof electorates, death-card colors, siege cost), routing pool
   (deepseek id, command-a-2 denylist, honest ops docs), W31 perf/correctness (DramaWire flag-OFF
   scans, /api/fingerprints off the event loop + delta cache, healing target validation, charter
   cap round-trip, storyline staleness, BabelMatrix NUL bytes, TwinLens alignment, config-parse
   crashes) — **plus the EM-318 feed-silence removal** (fix-don't-hide; EM-324 fixed the root).
   Gates: backend **2475/0 (+1 pre-existing skip)** · tsc clean · vitest **1472/0**.
4. **EM-299 parametric building-recipe grammar → PR #107** (Wave Q keystone, Opus builder,
   `feat/em299-building-recipes`): optional 7-field recipe (the EM-297-validated schema verbatim)
   on the build turn → procedural `RecipeStructure` render, catalog fallback untouched, flag
   `building_recipes.enabled` default OFF, byte-identity proven. Gates: backend 2463/0 · tsc
   clean · vitest 1486/0. Results: `coordination/EM299_RESULTS.md` (that worktree/PR).

## EM-305 ROOT-CAUSED (the 3×-reported feed flicker — live browser repro tonight)

Instrumented the **running live sim** read-only with Playwright (TICK advancing — real feed):
**123 of 255 WS events arrived as duplicates (~2× delivery), 13 non-monotonic, ~20 feed-card DOM
removals/min with the viewer pinned at top** — the visible flicker. Root cause is NOT the PR #91
seq collision (that part held): `useSimulation.ts`'s socket handlers act unconditionally, so ANY
stale socket closing (StrictMode first mount, transient drop) nulls `wsRef` — orphaning the live
socket it pointed at — and schedules a reconnect that spawns another. Proven live: 3 sockets open;
force-closing the extras bred a 4th within seconds. N live sockets ⇒ N× event/world_state
processing ⇒ feed churn. Fix (stale-socket guards + handler detach on cleanup) + regression tests
on branch `fix/em305-ws-double-socket` — see the PR list below. The yellow-tile half did not
reproduce in tonight's windows; likely the same double-processing surfacing in gallery thumbs —
re-check after the fix soaks.

## Also shipped overnight

5. **EM-300 P2 lane discovery → PR #109** (Opus builder): the registry is data-driven — probe
   answered spec §11 Q1 empirically (`/v1/models` carries real `available` flags; admin
   quotaStates wired as opt-in enrichment only), `providers/discovery.py` + `refresh_lanes()` +
   `POST /api/lanes/refresh` + counter-gated auto-refresh (off the replay surface), terminal
   `auto` reservation followed BY NAME (the P4 caveat). Live e2e: 2 static lanes → 96 discovered.
   Flag default OFF ⇒ byte-identical. Backend 2505/0 (+30 new). Merge after #108.
6. **EM-305 fixed → PR #110** (see the root-cause section above): stale-socket guards + teardown
   detach, 3 regression tests, vitest 1471/0. Independent of #108 (branched off main).
7. **EM-121 multi-city camera → `2a74042` on the multi-city branch**: settlements clickable
   (label + town-square core) via a settlement FocusTarget framing the whole cluster; the
   follow chain across a journey extracted + pinned by a whole-journey test; reset-view frames
   ALL settlements with the same ease. Gates: tsc clean, vitest 1537/0 (+17). Deferred: 2D-map
   clicks (the map routes no clicks at all today).

## Still running overnight (Opus — independent of the Fable budget)

- **waveo-builder** → `build/wave-o-culture-religion` (fix pack merged in): Culture EM-251→255
  then Religion EM-260→263, per-item goldens + commits, one PR at the end (merges after #108).
  Progress log: `../petri-dish-waveo/coordination/WAVEO_RESULTS.md`.

## Morning checklist (for you)

1. Merge order: **#108 (fix pack) → #107 (EM-299) → the two overnight PRs** (they were built on
   top of #108; expect trivial conflicts at worst).
2. Multi-city live sign-off (DoD #7) — back up `data/run.sqlite` first; restart `./dev`; reset;
   watch a founding + a crossing. The C1 freeze fix means an all-travelers moment now
   fast-forwards instead of hanging.
3. Live flag-flip sign-off for EM-309–317 (unchanged ask from the ledger) — now safer: DramaWire
   and the fingerprint endpoints got their perf fixes in #108.
4. EM-318 removal is in #108: exhaustion idles are VISIBLE again (rare post-EM-324). If the feed
   gets noisy during a rate storm, that's signal now, not a bug — the root levers are EM-300
   P2 (discovery) and EM-167 (Ollama overflow), not re-hiding.
5. Ledger sweep: EM-249/250/256–259 rows still say "in-progress PR #92" (merged 2026-07-12) —
   waveo-builder was told to flip them; verify at its PR.

## Environment notes

- `caffeinate -dimsu` was started (PID in session) so the Mac can't sleep-kill the run.
- Worktrees: `../petri-dish-fixpack`, `../petri-dish-em299`, `../petri-dish-waveo`,
  `../petri-dish-em300` (each with own venv + node_modules; safe to `git worktree remove` after
  merges — see the git-post-merge-cleanup skill).
- The accidental root `node_modules` symlink (rode in with #90) is untracked by #108, same as
  the `.venv` one before it.

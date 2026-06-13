# Wave F contract — inspector at long-session scale (EM-151 + EM-194)

> Version: 1.0 · Date: 2026-06-12 · Branch: `build/wave-f-inspector-scale`
> (stacked on `build/wave-e-social-world` / PR #12 — wave E touched
> `selectors.ts`, so this stacks rather than forks main)
> Trigger (user, live session 2026-06-12): "for a long session it's just an
> infinite scroll and useless. it's trying to load all of it and takes forever
> to finally render, I still haven't reached the bottom of the page."
> Measured: the live DB holds **99,140 events / 4,097 ticks** — past the 50k
> `MAX_HISTORY` cap. Boot pages ~50×1000-event chunks to exhaustion before the
> page is usable; every scrub tick re-folds the full history through 4–6 O(n)
> selectors; nothing is virtualized; one selector crash blanks the annex
> (the EM-151 white-panel symptom on run #189).

## Global rules

- Free-scale law: zero LLM-call changes (this wave never touches providers).
- Backend suite green (`cd backend && source ../.venv/bin/activate &&
  python -m pytest -q`, 705 at wave start); web suite green
  (`npx vitest run`, 579 at wave start) + `npm run build`.
- Never touch `README.md`, `START-HERE.md`, `web/src/components/world3d/`,
  engine/providers code.
- Agents do NOT commit — the orchestrator commits at batch gates.
- Replay-fidelity invariants (EM-069/155) are non-negotiable: scoping/
  windowing must never change WHAT a panel shows for a given tick — only how
  cheaply it's computed. Existing inspector tests keep passing unmodified
  (weakening one is a CRITICAL finding).
- No new heavyweight deps. A virtualization micro-dep (@tanstack/react-virtual
  or react-window) is allowed IF vendor-light and justified; a hand-rolled
  fixed-row-height window is equally acceptable — implementer documents the
  choice.

---

## F1 — events API tail + stats (backend, small)

**Owner:** backend-agent-F1.
**Files owned:** `backend/petridish/api/app.py`,
`backend/petridish/persistence/repository.py` (query helpers),
`backend/tests/test_wave_f_events_api.py` (new).

1. `GET /api/events/stats [?run_id]` → `{total: int, max_seq: int,
   max_tick: int, min_seq: int}` for the run (cheap COUNT/MAX — sqlite
   indexed on seq). Lets the client size backfill + show real progress.
2. `GET /api/events` gains an honest TAIL mode: `order=desc` +
   `before_seq` keyset pagination (mirror of the existing `after_seq` asc
   contract; rows returned newest-first). Existing asc behavior byte-identical
   (regression-pin with a test).
3. OpenAPI/docs untouched elsewhere; additive only.

Acceptance: stats shape + correctness on a seeded run; desc keyset pages
overlap-free and exhaustive; asc path unchanged; suite green.

## F2 — inspector boot, scrub, and render at scale (frontend)

**Owner:** frontend-agent-F2 (after F1 gate).
**Files owned:** `web/src/hooks/useSimulation.ts`,
`web/src/inspector/**` (InspectorLayout, selectors, useArchiveHistory,
useReplayMaterials, panels), `web/src/types/index.ts` (additive),
api client, new `web/src/inspector/ErrorBoundary.tsx`, matching tests.
NOT world3d/, NOT the live-page EventFeed (its 200-cap is fine).
Ratified v1.1: one-line `App.tsx` wiring (historyTotal → InspectorLayout) and
an additive guarded matchMedia stub in `test-utils/setup.ts`.
GovernanceHistory exempted from virtualization (bounded by rule count, not
event volume). Chaos-feed rows fixed at 96px so critter dialogue stays
inline at two lines (preserves the 99f3822 behavior).

1. **Tail-first boot:** load the newest chunk FIRST (F1 desc tail) and render
   immediately; backfill older chunks in the background with visible progress
   ("12,000 / 99,140 events") driven by F1 stats. The annex must be
   interactive after chunk one. Archive mode (`useArchiveHistory`) gets the
   same treatment.
2. **Scrub-time projection caching:** split tick-scoped projections from
   full-history folds so dragging the scrubber does NOT re-run O(n) selectors
   per tick — fold-forward incrementally from the last projected tick where
   the selector is a pure fold (economyAt, replayStateAt), or cache per-tick
   results (bounded LRU) where it isn't. Target (assert structurally in
   tests): a scrub step re-processes only the events BETWEEN the two ticks,
   not the whole history. Projection RESULTS for any tick stay byte-equal to
   the pre-F full fold (golden test comparing both paths on a fixture run).
3. **Virtualize the unbounded lists:** the high-volume scrolling surfaces
   (AnimalChaosFeed list, DecisionTrace turn list, GovernanceHistory if
   unbounded) render only the visible window (+overscan); rendered row count
   stays bounded (assert ≤ cap in a test with a 10k-event fixture).
4. **Panel error boundaries (EM-151):** every grid panel + the scrubber gets
   a boundary rendering a labeled dead-panel fallback ("this panel crashed —
   <name>; the rest of the annex is fine") instead of blanking the annex;
   test by throwing from a child.
5. **50k-cap honesty:** when history is truncated at the cap, the UI says so
   ("showing the newest 50,000 of 99,140") and the scrubber's pre-cap range
   uses the existing snapshot+delta replay path (already built, EM-069) —
   verify it engages instead of silently projecting from a hole.

Acceptance: golden equality of projections pre/post; scrub-step incremental
fold proven; bounded row rendering proven; boundaries proven; tail-first boot
order proven (first render before backfill completes — fake-timer test);
suites + build green.

## Gates

Per batch: full backend pytest (F1) / vitest + build (F2), orchestrator
commits. F2's verify includes a structural-perf lens (no full-history fold on
scrub-step; bounded DOM rows) and the golden-equality lens. Closeout: ledger
(EM-151 → done, EM-194 filed+done), BUILD-PLAN row, build results, live
check against the 99k-event run.

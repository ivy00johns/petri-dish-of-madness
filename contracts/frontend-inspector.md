# Contract: Frontend Routing & the Inspector Annex — v1.1.0

**Wave:** W5 (EM-053). **Owner:** frontend-agent.

> **v1.1.0 (W9, 2026-06-09 — audit §C1/C4/C8/D2, EM-069):** §7's deep-replay clause is
> now NORMATIVE, not aspirational — `inspectorApi` with zero consumers is a contract
> violation. Requirements:
> 1. **Backfill on mount (live mode):** `InspectorLayout` seeds its history from
>    `GET /api/events` (keyset-paginated via `after_seq`, ascending) and merges the WS
>    rolling history on top, deduped by `seq`. After a fresh page load mid-run, every
>    panel renders the FULL run, not just events since connect.
> 2. **Scrub uses replay materials:** seeking to tick T beyond what client history can
>    project uses `GET /api/replay?tick=T` (`base.state` + delta per api.openapi.yaml
>    v1.2.0) through the SAME `replayStateAt` selector. Fold boundary is strict-left
>    (`base.tick < e.tick <= T`) per event-log.md v1.1.0.
> 3. **`onSeekTick` is wired:** `App.tsx` passes the simulation hook's `seekTick` into
>    `InspectorLayout`; while scrubbed (not pinned to live), panels project at the
>    scrub tick and MUST NOT bleed live-edge data into their views.
> 4. **Empty states are mandatory** (§7 already says so): any panel state with no data
>    renders a labeled explanation (e.g. "no events at this tick — history loading /
>    out of window"), never a blank region. Mock mode (no backend) must keep working —
>    every fetch degrades to the rolling history.

## 0. Framing (read this first)

**The 3D cozy village is the main experience and stays the front door.** The `/inspector`
route is a 2D **analysis annex** you visit to understand *why* what you watched happened —
it is NOT a demotion of the 3D world and NOT the default view.

There are exactly two reasons the analysis layer is 2D, neither of which is "2D is primary":
1. **Right tool** — replay scrubbers, force-directed social graphs, and time-series AWI
   charts are native to Canvas2D/SVG/lightweight charts and awkward/expensive in Three.js.
2. **Free the GPU during analysis** — when you stop *watching* and start *dissecting*
   (scrubbing a 1,600-tick replay, diffing models), the WebGL village should not be
   burning the GPU/battery. So the annex lives on its own route where `<Canvas>` unmounts.

The 3D world also gets **richer** from W7/W8 (buildings with visible mutable state, a clock
tower rising as it's funded/built, scorched buildings after arson, a cat & dog roaming) —
those render in the 3D village, not only in 2D panels.

## 1. Routing

- Add `react-router-dom` (only new dep for W5). Wrap `<App>` in `<BrowserRouter>` in
  `web/src/main.tsx`.
- Routes:
  - **`/`** → the existing live layout (3-column grid; **3D `CozyWorld` is the default**
    center view, with the existing 2D `WorldMap` reachable via the in-page village/map
    toggle). Unchanged behavior, now mounted under a route.
  - **`/inspector`** → `<InspectorLayout>` — full 2D, **no `<Canvas>` mounted at all**.
- A persistent nav affordance (in `Header.tsx`) links `/` ⇄ `/inspector`. Label the
  inspector clearly as analysis (e.g. "Inspector" / "Analyze"), not "2D".

## 2. WebGL unmount (the hard requirement)

When the route is `/inspector`, the `CozyWorld` `<Canvas>` (R3F) MUST be **unmounted**, not
hidden — so the WebGL context is released (zero GPU). Because routing controls whether the
center block renders, navigating away unmounts the R3F tree and React/R3F dispose GPU
resources. `CozyWorld` must have correct `useEffect` cleanup (cancel RAF, dispose) so the
unmount/remount cycle leaks nothing. Verify by toggling routes and watching GPU/memory.

A global "instrumentation mode" pauses the live render loop while a 2D panel is open;
returning to `/` remounts the canvas from current `world_state`.

## 3. State store (`useSimulation.ts`)

The live feed stays capped (`MAX_EVENTS=200`) for the `/` feed. The inspector needs more:

- Add a separate **rolling event history** ref (e.g. last 5,000 events, configurable) fed
  from the same WS `onmessage`, exposed for replay/trace/graph/dashboard. Document the
  window; older ticks beyond it are reachable only via the backend replay API (W6).
- In **live** mode the history accumulates from WS. In **mock** mode the mock generator
  feeds it (and must be seek-able for the replay scrubber — seed RNG by tick so replay is
  deterministic).
- New control surface (implemented at W6 against the backend read API, stubbed at W5):
  `seekTick(tick)` (pauses, projects state at tick), and inspector data selectors
  (`turnTrace(turnId)`, `governanceHistory()`, `socialGraph(atTick)`, `analytics(range)`).

## 4. Inspector panels (mount points; built W6/W8)

`web/src/inspector/InspectorLayout.tsx` hosts, all 2D, all reading the event log via the
backend read API (`contracts/event-log.md` §7, surfaced over REST at W6):

- `ReplayScrubber.tsx` (EM-055) — timeline + play/pause/step/speed, event markers
  color-coded by type (crime=red, governance=blue, construction=amber, animal=magenta),
  top-down Canvas2D map (NOT the 3D scene).
- `DecisionTrace.tsx` (EM-056) — click an action/turn → the linked chain
  (perceived → memory_retrieved → llm_call → reasoning → action_chosen → action_resolved)
  with model/provider, tokens, and state deltas.
- `GovernanceHistory.tsx` (EM-057) — proposal lifecycle timeline + downstream-consequence
  links (the "clock tower" failure made visible).
- `SocialGraph.tsx` (EM-058) — `react-force-graph-2d`; nodes=agents (color by model),
  edges=relationships; time-scrub; **freeze the force sim after layout settles** (battery).
- `AWIDashboard.tsx` (EM-059) — 9 AWI indicators side-by-side + model-vs-model cut;
  `uPlot` for time series, `Observable Plot` for distributions; **no composite score**;
  stop chart animation when the panel isn't visible.
- `AnimalChaosFeed.tsx` (EM-065) — filtered `actor_type:"animal"` / `is_chaotic` stream.

Libraries added per wave: W5 `react-router-dom`; W6 `react-force-graph-2d`, `uplot`,
`@observablehq/plot`. Reuse the existing `lab-*` Tailwind palette and `index.css`
primitives — no new theme.

## 5. Types (`web/src/types/index.ts`)

W5 adds the minimum so live events carry the trace + the route compiles. Add to
`WorldEvent`: `turn_id?: string | null`, `actor_type?: 'human_agent'|'system'|'god'|'animal' | null`,
`sim_time?: number | null`. Extend `EventKind` with the chain kinds
(`perceived|memory_retrieved|llm_call|reasoning|action_chosen|action_resolved`). Keep
`EventKind` permissive (the feed already falls back on unknown kinds). Richer inspector
view-models (`TurnTrace`, `GovernanceTimeline`, `SocialGraphData`, `AwiSummary`) are
authored at W6 against the read API. **No `any`; `tsc -b` must stay green.**

## 6. Definition of Done (W5 slice)
- `/` renders the existing live app unchanged (3D village default); `/inspector` renders a
  placeholder `InspectorLayout` with **no WebGL context** (verified: canvas unmounts).
- Header nav switches routes; route change unmounts/remounts `CozyWorld` cleanly (no leak).
- `WorldEvent` carries `turn_id`/`actor_type`/`sim_time`; `tsc -b` + `vite build` green.
- `design-token-guard` clean (no inline styles / hardcoded colors).

## 7. W6 data contract (the panels)

**Primary data source = the client-side rolling history**, NOT the backend. The panels compute
from `useSimulation.history` (`WorldEvent[]`, the 5,000-cap ref from §3) via pure selectors, so
they render in **mock mode with no backend** and in live mode alike. The REST read endpoints
(`api.openapi.yaml` v1.1.0) are the **deep-replay** source: full history beyond the rolling
window, and `seekTick` in live mode. A panel must degrade gracefully (empty-but-labeled state)
when its data isn't present yet — never a blank or a crash.

Files (all under `web/src/inspector/`, all token-only, no `any`, `tsc -b` green):
- `api.ts` — typed fetch client for `/api/events|turns/{id}|rules/history|relationships|snapshots|replay|analytics`. Response rows are `EventRow` (api.openapi.yaml component).
- `types.ts` — view-models: `TurnTrace` (ordered chain + parsed spans), `GovTimelineEntry`
  (rule_id, proposer, status path, votes, downstream[]), `SocialGraphData` ({nodes:{id,label,color}, edges:{source,target,type,trust}}), `AwiSummary` (the §7 analytics dict, typed), `ReplayFrame` (world state at a tick).
- `selectors.ts` — PURE functions over `WorldEvent[]` (+ snapshots): `turnTrace(events,turnId)`,
  `governanceTimeline(events)`, `socialGraph(events,agents,atTick)`, `awiSummary(events,range)`,
  `replayStateAt(events,snapshots,tick)`. Same logic the backend `get_*` methods use, client-side.
- Shared **`currentTick`** state lives in `InspectorLayout`; `ReplayScrubber` drives it; the
  other panels re-project at `currentTick` (scrub once, everything follows).

Panels (one file each — parallel-safe; `InspectorLayout` imports all five from fixed paths):
- `ReplayScrubber.tsx` (EM-055), `DecisionTrace.tsx` (EM-056), `GovernanceHistory.tsx` (EM-057),
  `SocialGraph.tsx` (EM-058, `react-force-graph-2d`), `AWIDashboard.tsx` (EM-059, `uplot` +
  `@observablehq/plot`). Freeze the force sim after layout settles; stop chart animation when a
  panel isn't visible; Canvas2D for the replay map (never the 3D scene).

**Mock generator (`web/src/mock/generator.ts`) MUST emit representative data** so the panels look
real offline: the per-turn decision-trace chain (the 6 chain kinds with populated payloads incl.
`llm_call` usage), a rule lifecycle (propose → vote → pass/reject with a visible downstream
effect), and relationship/conflict/gift events. Without this the inspector is empty in the demo.

Libraries added at W6: `react-force-graph-2d`, `uplot`, `@observablehq/plot`. Quality gates for
the wave: `tsc -b` + `vite build` green, `design-token-guard` clean, and `render-sanity` PASS on
`/` AND `/inspector` (every panel shows real-looking data, no lone `?`/`undefined`/empty shells).

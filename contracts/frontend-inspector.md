# Contract: Frontend Routing & the Inspector Annex — v1.0.0

**Wave:** W5 (EM-053). **Owner:** frontend-agent.

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

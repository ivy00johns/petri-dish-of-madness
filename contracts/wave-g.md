# Wave G contract — inspector layout: the data-dense annex (EM-196 + EM-197)

> Version: 1.0 · Date: 2026-06-12 · Branch: `build/wave-g-inspector-layout`
> (stacked on wave F / `build/wave-f-inspector-scale`)
> Trigger (user, with screenshots): the annex is one infinite vertical page —
> screenfuls of blank space (empty governance owns a tall half-width column,
> 26-row structures list, oversized fixed chaos rows, unbalanced columns),
> new live entries push the reading position out of sight, and the social
> graph is a broken white box. "/ui-ux-pro-max we need to rethink the layout
> design of the inspector page because it's not usable anymore."
> Design direction (ui-ux-pro-max, Data-Dense Dashboard style): minimal
> padding, grid layout, space-efficient, maximum data visibility, internal
> scrolling. The EXISTING dark lab token system stays — no palette change.

## Global rules

- web/ only. Never touch backend, world3d/, the live-page EventFeed,
  README.md, START-HERE.md.
- Existing tests keep passing UNMODIFIED unless a test pins the OLD layout
  structure itself (a layout test may be updated to the new structure, but
  any data/selector/behavior assertion that weakens is a CRITICAL finding;
  list every modified test with justification).
- All colors via existing tokens; new tokens go in the tokens css. Canvas
  paints get literal-hex fallbacks (the EM-196 lesson — canvas never trusts
  an unresolved var).
- Wave-F invariants hold: golden-equal projections, bounded rendered rows,
  error boundaries, tail-first boot. Do not regress them.
- Gates: `npx vitest run` + `npm run build` green.

## G1 — EM-196: social graph canvas fix (ship first, surgical)

**Owner:** frontend-agent-G1.
**Files owned:** `web/src/inspector/SocialGraph.tsx`, its test file.

1. Every canvas-bound token read in `useResolvedTokens` gets a literal hex
   fallback (`cssVar('--lab-bg') || '#0a0a0b'`, …, matching the declared
   token values exactly); same for any other `getComputedStyle` read that
   feeds ctx colors (`withAlpha` inputs included).
2. Remount safety: `key={String(ready)}` (or equivalent) on the ForceGraph2D
   wrapper so the ready transition forces a clean kapsule mount (kills the
   StrictMode stale-detached-canvas path).
3. Tests: token-fallback unit (empty cssVar ⇒ literal), and a mount test
   asserting the graph container holds a canvas after ready flips.

## G2 — EM-197: viewport-fit data-dense dashboard

**Owner:** frontend-agent-G2 (after G1 gate).
**Files owned:** `web/src/inspector/**` (layout, panels, VirtualList,
tokens css), `web/src/App.tsx` (route wrapper if needed), new tests.
NOT hooks/useSimulation.ts (wave-F owns the data layer; consume as-is).

### Layout law (the contract's heart)

1. **No page scroll.** The annex is `h-dvh` (header/status bar + scrubber
   strip fixed): the panel area is a CSS grid sized to the remaining
   viewport; every panel scrolls INTERNALLY (`overflow-auto`, thin themed
   scrollbar). Desktop (≥1280): 3-column grid — suggested template, G2 may
   tune with reasoning: [replay-map+structures | decision trace | governance
   +AWI] top row, [social graph | chaos feed | (AWI continued)] bottom; the
   point is BALANCED, viewport-bounded cells, no orphan black columns.
   1024–1279: 2 columns. <1024: panels stack with internal max-heights
   (page scroll allowed ONLY here, as the small-screen fallback).
2. **Empty panels collapse.** A panel with no data (governance at 0 rules,
   chaos feed with 0 animal events, …) renders as a slim strip: title +
   zero-state counts + expand affordance; its grid space is reclaimed by
   siblings (grid template adjusts or the strip sits in a rail). Empty-state
   text says what would fill it ("no laws yet — proposals appear here").
3. **Reading position never moves.** Live updates must not shift any panel's
   scroll position: panels are fixed grid cells (layout can't push), and
   event lists apply the EM-093 anchoring pattern internally (when scrolled
   away from the newest edge, prepends/appends preserve scrollTop;
   a "↓ N new" pin appears like the live feed).
4. **Kill dead space inside lists:**
   - `VirtualList` gains per-item-kind heights (deterministic height
     function + prefix sums — still windowed, still bounded-rows): chaos
     LLM-call rows shrink to one line (~40px), dialogue rows keep two lines
     (96px). The wave-F bounded-row test is EXTENDED to the variable case,
     not weakened.
   - Structures: the 26-row list becomes a wrapped compact chip grid
     (name + status dot, status text on hover/title), capped height with
     internal scroll.
   - The replay map keeps its aspect but fits its cell; tick badge stays.
5. **Density polish (ui-ux-pro-max checklist):** minimal padding per the
   data-dense style; tabular numerals where counts align; panel headers
   become slim sticky-in-panel bars (title + count + EM-tag right-aligned);
   hover tooltips for truncation; `prefers-reduced-motion` respected
   (anchoring/pin behavior is instant, no smooth-scroll dependence);
   keyboard focus order follows the grid reading order.

### Acceptance (minimum)

- At 1440×900 with a 3k-event run: `document.body` does not scroll
  (jsdom structural test: the grid container's class set pins h-dvh/overflow
  rules); each panel cell has its own scroll container.
- Empty governance renders as the slim strip (test with 0 rules) and
  expands when a rule exists.
- Anchoring: with a list scrolled mid-history, appending events preserves
  scrollTop (the EM-093-style unit test pattern) and shows the new-count pin.
- Variable-height windowing: rendered row count stays bounded with mixed
  item kinds; heights match the per-kind function (extend wave-F tests).
- Structures chip grid renders all 26 with status dots, container capped.
- Social graph (post-G1) renders inside its cell; legend + canvas present.
- vitest + build green; no new hex outside tokens css (canvas fallbacks
  exempt — they mirror token literals, commented as such).

## Gates

G1: targeted tests + full suite, orchestrator commit. G2: full suite +
build + bounded-row/golden invariants + a REAL-BROWSER render check
(playwright: load /inspector on the live stack, assert no page scrollbar,
screenshot to the user, console clean). Closeout: ledger flips, BUILD-PLAN
row, build results.

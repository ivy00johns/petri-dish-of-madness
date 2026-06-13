# Wave G — inspector layout: the data-dense annex · Build Results

> Branch: `build/wave-g-inspector-layout` (stacked on wave F)
> Date: 2026-06-12 · Contract: `contracts/wave-g.md`
> Items: **EM-196, EM-197** — done (`wave-G 2026-06-12`).
> Trigger: user screenshots — infinite vertical page, screenfuls of blank
> space, live entries pushing the reading position away, social graph a
> broken white box. Invoked `/ui-ux-pro-max` → Data-Dense Dashboard
> direction (minimal padding, grid, internal scrolling, max data
> visibility) on the existing dark lab tokens.

## What shipped

| Batch | Commit | Delivery |
|---|---|---|
| G1 EM-196 | `c594abb` | Social-graph white-box fix. Root cause (debugger agent): `useResolvedTokens` read CSS vars via getComputedStyle in a useState initializer — an `''` resolution makes force-graph's truthiness guard skip the canvas background (transparent canvas over OS white), and react-kapsule's StrictMode double-mount leaves a stale detached canvas (broken-image artifact + dead rAF loop). Fix: literal hex fallbacks mirroring the declared tokens on every canvas-bound read + `key`-forced clean remount on the ready transition. Introduced by Wave E B6 (`bd780e8`). 3 tests incl. a regression pin on `backgroundColor` non-empty. |
| G2 EM-197 | `550632b` | Viewport-fit dashboard. No page scroll ≥1024px (`scrollHeight == innerHeight` proven live at 1440×900 AND 1100×800): fixed header/status/scrub chrome + a viewport-sized CSS grid (xl 3-col: map+social+runs · trace+chaos · governance+AWI; lg 2-col; <1024 stacked behind the MinWidthGate). Every panel scrolls internally. Empty panels collapse to slim strips with what-would-fill-it text + EXPAND (governance/chaos tested, auto-expand on data). VirtualList gains per-item-kind heights (prefix sums + binary search; chaos LLM rows 40px, dialogue rows 96px — two-line dialogue preserved per 99f3822) and EM-093 freeze-snapshot anchoring with an "↑ N new" pin. Structures → wrapped chip grid (status dots + tooltips, capped, scrolled). ReplayScrubber split into the slim transport strip + an aspect-preserving ReplayMapPanel. Per-cell error boundaries extended to Replay Map + Run Browser. 21 tests added; only 2 pre-existing tests touched, both additive/structural (verifier-audited). |

## Gates

Web 628 → **649**, build green, tsc clean. Wave-F invariants intact
(golden projections untouched, bounded rows EXTENDED to variable heights,
tail-first boot untouched). Zero new hex outside the tokens css (canvas
fallbacks comment-pinned to their tokens).

## Real-browser verification (live stack)

- `documentElement.scrollHeight == innerHeight` at both viewports; html and
  body overflow hidden; no horizontal scroll.
- 4 internal scroll containers active; social graph canvas nonzero buffer
  with dark computed background (the white box is dead).
- Anchoring held a mid-history scroll position across ~3s of live ticks.
- Console: zero errors (one benign WS dev-session reconnect warning).
- Evidence: `docs/build-evidence/em197-inspector-1440.png` / `-1100.png`
  (also delivered to the user directly).

## Notes

- The new-pin glyph is "↑ N new" (newest-first lists pin at the top edge,
  matching the live feed's EM-093 idiom).
- A concurrent session's `feat/reflex-chatter` backend work shares this
  worktree; wave-G commits were scoped to web/ + docs only and that work
  was left untouched (verifier MAJOR resolved at the gate).

## Handoff

- Branch chain: PR #12 (wave E) → wave F → wave G; PR when ready.
- EM-195 (remaining panel-selector residuals) still open — the new layout
  reduces its blast radius but doesn't close it.

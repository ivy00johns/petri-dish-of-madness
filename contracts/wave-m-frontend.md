# Contract — Wave M Frontend (Wave F): UI backlog (EM-202/215/204/195/180/191/192/193 + EM-225 FE)

> Integration contract for the frontend items in the backlog build. Source:
> `docs/REMAINING-WORK.md`. Frontend map: this contract (distilled from a full
> `web/src` recon). Stack: Vite + React 18 + TS + React Three Fiber + Tailwind +
> Vitest. **Branch `build/wave-m-cooperation-economy`. Never merge/push to main.**

## §1 — Invariants (DO NOT BREAK)
- `cd web && npm run typecheck` (tsc -b) clean; `npm test` (vitest run) green;
  `npm run lint` clean. Add tests for new components/logic.
- WorldState/event types stay **additive** (optional fields) — pre-wave snapshots
  must still type-check (model on `types/index.ts` existing optional fields).
- **3D WebGL palette is EXEMPT from the design-token system** — colors in
  `world3d/toon.ts`, `world3d/worldSpace.ts`, and WebGL material props in
  `Structure.tsx`/`Building.tsx` are intentionally GPU-scene colors, NOT CSS
  tokens. Do NOT "fix" them in EM-193. Token discipline applies to **DOM/CSS
  chrome** only.
- Scroll-anchoring (EM-093/EM-197 pattern): never yank the reader when new
  events arrive.

## §2 — Area ownership (serialize within an area; parallelize across)
- **Inspector lane** (serial): EM-195 → EM-204. Files: `inspector/InspectorLayout.tsx`,
  `inspector/selectors.ts`, `inspector/*Panel*.tsx`.
- **world3d lane** (serial): EM-180 → EM-192. Files: `components/world3d/Structure.tsx`,
  `toon.ts`, `worldSpace.ts`, `structureModel.ts`, `types/index.ts` (WorldState).
- **feed/controls lane** (parallel-ish): EM-191 (`feed/EventFeed.tsx`) ∥ EM-202
  (`controls/ControlPanel.tsx` + `types/index.ts` SpawnSpec). NOTE both world3d-lane
  (EM-192) and EM-202 edit `types/index.ts` — different interfaces (WorldState vs
  SpawnSpec), low conflict, but **serialize the two `types/index.ts` edits** if they
  land together.
- **nav seam** (SHARED, integrate centrally): EM-215 Diary tab + EM-204 inspector
  tabs both touch `App.tsx` Routes + `Header.tsx` NAV_TABS. Lead integrates the nav.
- **EM-193 token burndown: LAST, SOLO** (touches chrome across many files).
- **EM-225**: backend half (new chronicle deep-dive endpoint/mode in `api/app.py` +
  loop.py chronicler) ships in a BACKEND wave; frontend half (ChronicleView "Deep
  Dive" toggle) here.

## §3 — Per-item specs

**EM-202 — A/B persona-across-models UI.** Backend `POST /api/agents` already
accepts `ab_models` (EM-200). Add `ab_models?: string[]` to `SpawnSpec`
(`types/index.ts`). In `controls/ControlPanel.tsx` spawn form: an "A/B test"
toggle revealing a model multi-select; on submit with ≥2 models, send `ab_models`.
Surface `ab_group` in feed/roster (variants share a base name, distinguished by a
`·tag` + the model chip). Tests: form emits ab_models, roster groups variants.

**EM-215 — The Diary.** Today reflections are only a feed FILTER
(`EventFeed.tsx` diary category = reflection+commitment_made+commitment_lapsed+
plan_revised). Build a dedicated per-agent **DiaryView** (new `/diary` route +
NAV_TABS entry, full-screen like Inspector → mounts without LiveLayout): group
`reflection` events by agent, chronological, with agent avatar + mood + the
inner-life text. Individual cousin to the town Chronicle. Reuse the existing diary
category logic. Tests: groups by agent, renders chronologically, empty-state.

**EM-204 — Inspector IA cleanup.** Reorg the 9-panel grid
(`InspectorLayout.tsx`) into grouped/tabbed sections: **Forensics** (ReplayMap +
DecisionTrace), **Society** (SocialGraph + Governance), **Chaos** (AnimalChaosFeed),
**Runs** (RunBrowser) — plus AWIDashboard placed sensibly. Replace the fixed grid
with a tab state + conditional column-stack rendering; keep `panelProps` wiring +
scrub. Empty panels collapse to slim strips. Tests: tab switch renders the right
panels, scrub still drives all.

**EM-195 — Inspector scrub residuals.** `panelEvents` (`InspectorLayout.tsx`) gets
a fresh identity each scrub tick → non-projector panels (turnIds/turnTrace,
governance, socialGraph) re-sort+re-fold each tick (the `selectors.ts` WeakMap
ascending cache misses). Add a secondary cache (eventArrayRef, projecting,
currentTick) so `panelEvents` identity is STABLE across identity-equal scrubs;
extend the wave-F projector pattern to the remaining panels; insert-sorted WS merge
for an out-of-order late event. Tests: stable identity across equal scrubs, fold
correctness unchanged (golden-equal to full fold).

**EM-180 — Funds-as-marker.** `structureModel.ts:isFundBuilding()` ALREADY
detects funds (name/kind keyword: fund/treasury/coffers/endowment/reserves/
warchest, kind=commons); `Structure.tsx` ALREADY shows a "Treasury · N/M ¢" label.
The remaining work: when `isFundBuilding()`, render a SMALL treasury/ledger MARKER
mesh (a chest/ledger/coin affordance) instead of the full operational building
shell — a treasury is an account, not a structure. Keep the label + click-to-focus.
Tests: fund → marker mesh path, non-fund → building path.

**EM-192 — Frontend follow-ups.** (a) Add `town_name?: string | null` to WorldState
(`types/index.ts`) so reads stop using a defensive cast. (b) Migrate Building/
Structure label HEX literals (STATUS_TINT etc. in `Structure.tsx`) onto the
`toon.ts` LABEL_INK/LABEL_OUTLINE constants (which already exist) — these ARE the
sanctioned label constants. (c) A real opacity FADE for proximity-gated labels
(useProximity already used). Tests: town_name typed, labels use constants, fade law.

**EM-191 — GRANT reply typographic distinction.** In `EventFeed.tsx`
GrantAffordance, the god's reply quotes the petition inline (`In answer to: "…"`).
Give the quoted petition a DISTINCT typographic treatment (nested block, italic,
softer color/border) so god's voice and the agent's words never blend (it's an
injection-shaped channel; React-escaped + 280-capped already). Tests: quoted block
renders distinctly.

**EM-193 — Token-discipline burndown.** design-token-guard reports ~338 hardcoded
hex in DOM/CSS chrome (Header/ControlPanel/EventFeed fallback colors). Run it
standalone on `web/src`, burn the backlog DOWN file-by-file, mapping hex → existing
CSS vars (`inspector-tokens.css`, `roster-tokens.css`, app tokens). **Do NOT touch
the exempt 3D WebGL palette (§1).** LAST + SOLO. Gate: design-token-guard errors
drop toward zero; typecheck+test still green. Log how many cleared + what remains.

**EM-225 (frontend half) — Chronicle deep-dive.** After the backend deep-dive
endpoint/mode ships, add a "Deep Dive" toggle in `ChronicleView.tsx` that requests
the multi-pass narration and shows progress + the richer chapter. Tests: toggle
calls the deep-dive path, renders the result.

## §4 — DoD (Wave F)
- typecheck + vitest green; new tests added per item.
- design-token-guard errors reduced (EM-193); class-extraction-guard reviewed on
  touched UI.
- render-sanity (if the stack can be brought up) + ux-review on the new views
  (Diary, reorganized Inspector) — or recorded reason if the stack isn't running.
- Ledger + closure log + BUILD_RESULTS updated.

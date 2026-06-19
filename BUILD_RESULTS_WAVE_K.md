# Build results — Wave K · The Builders' City

> Orchestrated build (ultracode) of `docs/superpowers/specs/2026-06-18-builders-city-design.md`.
> Branch: `build/wave-k-builders-city` (off the `docs/wave-k-builders-city` planning branch).
> Contract-first, gated waves, adversarial verify. **NOT merged to main** — stays on the branch.

## Status: ✅ complete (one recorded HITL follow-on)

| Test gate | Result |
|-----------|--------|
| Backend `pytest` | **922 passed** (886 baseline → +36 Wave K) |
| Frontend `vitest` | **803 passed** (789 baseline → +14 Wave K) |
| `tsc -b` (project typecheck) | **exit 0** |
| `vite build` (production) | **✓ built** (2056 modules) |
| design-token-guard (new DOM) | **zero new violations** (god console uses existing lab tokens; no inline styles/hex) |

## What shipped

| ID | Slice | Status |
|----|-------|--------|
| **EM-217** | K1 · Agent-selectable build-type catalog (BUILD_TYPES surfaced in the prompt; permissive EM-130 fallback kept; distinct palettes/labels) | ✅ done |
| **EM-218** | K2 · **Props as first-class items** — `Prop` entity (Animal-pattern, seeded ids, deterministic offset, `max_props` cap=48), `place_prop`/`remove_prop` reflex tools, snapshot round-trip, `PROP_MODELS` + `PlacedProps` render | ✅ done |
| **EM-219** | K3 · Remove & demolish — `remove_prop` + owner-immediate `demolish`; **public/landmark demolish via ~70% governance supermajority** | ✅ done |
| **EM-220** | K4 · Recolor/skin — `Building.skin` + `set_building_skin` (owner-only, destroyed-gated) + `SKIN_PALETTES` override layered under healthTint | ✅ done |
| **EM-221** | K5 · God-console parity — `/api/god/{place_prop,clear_props,demolish,reskin}` + a BUILDERS group in ControlPanel | ✅ done |
| **EM-182** | Agent-chosen placement — `propose_project` optional `place` arg; renderer honors `building.location` | ✅ done |
| **EM-216** | K0 · Asset vocabulary | 🟡 in-progress — **registry side done** (PROP_MODELS/propVariant/build-type palettes wired to existing vendored GLBs); see HITL below |

## Deferred / handoffs

1. **EM-216 new-kit acquisition (HITL).** Vendoring NEW Kenney CC0 kits (Nature Kit,
   expanded Furniture/City, distinct per-type building models) needs network access + the
   gltfjsx `--transform` + toon-ramp pipeline (EM-152). The Wave K systems already consume
   `PROP_MODELS`/build-type palettes, so when the kits land they wire in with **zero further
   code** — only registry URL additions + `ASSET_LICENSES.md` entries. This is the single
   intentional cap, recorded (not silently dropped).
2. **Full live render walk (render-sanity / ux-review) — deferred.** Verified instead via
   component render tests (`PlacedProps.test.tsx`, `ControlPanel.builders.test.tsx`), the
   production build, and a token-discipline diff check. A full Playwright walk needs the
   whole stack up (uvicorn + vite dev + a live MockProvider run); the changes are additive
   to an already-green app. To see it live: run the repo's dev stack and open the god console
   → BUILDERS group; place a prop / reskin / demolish and watch the 3-D scene update.
3. **Info (pre-existing, out of scope):** `propose_project` mints Building ids with `uuid4`,
   so cross-run *building-id* equality doesn't hold (single-run snapshot round-trip + fork
   determinism, the EM-155 contract, ARE asserted). Flagged for the EM-155 replay-equivalence
   ledger if full cross-run building-id determinism is ever wanted.

## Verify pass — adversarial review earned its keep

The QE gate passed (914) but two adversarial reviewers found **4 real backend bugs the unit
suites missed** (the mock path masked the worst one). All fixed test-first (+8 regression
tests, red-before/green-after):

1. **HIGH** — live god `clear_props`/`demolish`/`reskin` returned shapes the `useSimulation`
   hook never read → live confirmations always showed failure. Aligned shapes; **response
   shapes pinned in `contracts/wave-k.md` §5** + asserted (a mock can't mask drift again).
2. **MEDIUM** — public demolish passed on simple majority, not the locked ~70% supermajority.
3. **MEDIUM** — a multi-action turn with an object-valued `building_id`/`prop_id` crashed the
   whole TickLoop (unhashable). Coerced ids to `str` + guarded `_validate_world` in `_apply_steps`.
4. **LOW** — `set_building_skin` lacked the destroyed-status gate its menu enforced (EM-108).

## Commits (on `build/wave-k-builders-city`)

```
e15726d fix: declare Wave K test-stub JSX intrinsics so tsc -b passes
8dcecaf fix: wave K verify findings — god shapes, 70% demolish, crash guard, skin gate
60bd756 feat: wave K god-console — place/clear props, demolish, reskin (EM-221)
38f9007 feat: wave K core — props, build-type catalog, demolish, skin, placement
cff0bf4 docs: add Wave K integration contract (props, tools, events, god API)
5ac5d7a docs: lock Wave K open questions + pull EM-182 into the wave
4d7e3be docs: plan Wave K (The Builders' City) — agent-driven 3-D customization
```

## Your move

The build sits on `build/wave-k-builders-city`, fully green. When you're ready: **open a PR**
(or merge). Then the natural next item is EM-216's kit acquisition (HITL — I can prep the
gltfjsx pipeline + the exact kit URLs when you want to run the downloads).

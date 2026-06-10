# Wave B — "the city comes alive" (contract v1.0)

> Build branch: `build/wave-b-city-comes-alive` · Date: 2026-06-10
> Items: EM-115 (backend-world) · EM-111 (frontend-art) · EM-118 (frontend-foliage)
> · EM-122 (frontend-buildings)
> Art target: **Direction 1 — Warm Toon, Golden Hour**
> (`docs/ui-redesign/3D-WORLD-ART-DIRECTION.md`, concept frame
> `docs/ui-redesign/3d-concepts/dir1-warm-toon-golden-hour.png`).

## Global rules (all agents)

- **Free-scale law:** no change may add a standing LLM call. EM-115 is
  reflex/deterministic; EM-111/118/122 are pure renderer.
- **File ownership is exclusive** (per-agent sections below). If your item seems
  to need a file you don't own, STOP and report a blocker instead of editing it.
- **No git commits.** The orchestrator commits after each wave gate.
- **Tests are part of the item.** Backend: `cd backend && source
  ../.venv/bin/activate && python -m pytest -q`. Web: `cd web && command npm run
  test -- --run` and `command npm run build` (broken nvm shim: `export
  PATH="$HOME/.nvm/versions/node/v22.22.3/bin:$PATH"` first).
- Existing event/snapshot contracts (`contracts/events.schema.json`,
  `world-model.md`) are **additive-only**: new optional fields OK, no renames,
  no removals, no changes to existing `to_dict()` keys.
- **Assets must be CC0** and every external asset recorded in a new root
  `ASSET_LICENSES.md`. Never ship art ripped from commercial games.
- WebGL hex colors live in `worldSpace.ts`/component code by established
  convention (the canvas palette is exempt from the CSS design-token system);
  keep them centralized in `worldSpace.ts` palettes where one exists.
- Performance bar: the village must hold **~60fps** at default camera on an
  M-series Mac; if a fancier technique (AccumulativeShadows, high instance
  counts) can't hold it, use the cheaper fallback and SAY SO in your report.

## Agent B1 — backend-world (EM-115, city-growth slice)

Owns: `backend/petridish/engine/world.py`, `backend/petridish/config/loader.py`
(BuildingParams only), NEW `backend/tests/test_wave_b_citygrowth.py`.

Today a fully-funded project still requires agents to *choose* `build_step`
turns (20%/step), and if nobody follows through `advance_buildings()` abandons
it. EM-115 makes city growth **deterministic**: funded projects always finish.

- Add `BuildingParams.auto_build_per_round: int = 10` (progress % per round;
  `0` disables the feature entirely — keep that escape hatch working).
- In `World.advance_buildings()` (world.py ~1373, runs once per round from
  loop.py ~842): every building with `status == "under_construction"` gains
  `auto_build_per_round` progress and refreshes `last_progress_tick` (so funded
  projects can no longer rot to `abandoned` — intended semantics change;
  abandonment still applies to `planned`/unfunded stalls).
- On reaching 100: flip to `operational`, `health = 100`, emit the SAME
  `structure_state_changed` + `building_operational` events/payloads as the
  `action_build_step` completion path — **extract a shared completion helper,
  do not duplicate the logic**. Agent `build_step` (20%) stays as the faster,
  social path; auto-build is the slow guaranteed baseline.
- Per-round progress events: emit at most ONE `project_built`-style event per
  building per round, mirroring the existing advance_buildings event pattern
  (no actor agent; in-character feed text, e.g. "🔨 the village work crew
  raises {name} ({progress}%)"). Don't spam: if you can make interim progress
  silent and only emit on completion + state changes, prefer that — but the
  completion events are mandatory.
- Snapshot/replay must keep working unchanged (buildings already serialize;
  `auto_build_per_round` must not enter `to_dict()`).

Tests (minimum): funded project completes in `ceil(100/auto)` rounds with zero
build_step actions; completion emits `building_operational` with the same
payload keys as the build_step path; function activates (forage bonus applies);
`planned`+unfunded does NOT auto-advance and still abandons; `auto_build_per_round=0`
restores old behavior; build_step + auto-build compose (progress never exceeds
100, no double `building_operational`).

## Agent B2 — frontend-art (EM-111, warm toon golden hour) — Wave 1

Owns: `web/src/components/world3d/CozyWorld.tsx`, `Ground.tsx`, `Building.tsx`,
`Villager.tsx`, `Critter.tsx`, `NoticeBoard.tsx`, `Scenery.tsx` (materials-only
this wave), NEW `web/src/components/world3d/toon.ts` (+ its test file), NEW
`web/public/hdri/` asset, NEW root `ASSET_LICENSES.md`.
(`Structure.tsx`/`worldSpace.ts` are wave-2 files — to restyle Structure
materials, put the shared helper in `toon.ts` and leave Structure.tsx itself
for agent B4, who will adopt it.)

Recipe = Direction 1 in `docs/ui-redesign/3D-WORLD-ART-DIRECTION.md` §1:

- **Environment:** drei `<Environment>` with a warm dusk/sunset HDRI. Vendor a
  small (1k) CC0 .hdr from Poly Haven into `web/public/hdri/` and load via
  `files=` (record in `ASSET_LICENSES.md`); if download is impossible from the
  sandbox, fall back to `preset="sunset"` and report it. Keep (or replace) the
  `<Sky>` so the backdrop still reads golden-hour; keep fog tuned to match.
- **Lights:** low-angle sun `directionalLight` `#FFCF99` intensity ~2.2 (keep
  shadow casting, keep/raise the 2048 map), hemisphere fill sky `#FFE9C2` /
  ground `#3A5A2A`. Warm shadows, never black.
- **Toon ramp:** `toon.ts` exports a 3–4-step gradient `DataTexture`
  (NearestFilter, `generateMipmaps=false`) and a **cached** material factory
  `toonMaterial(color, {emissive?, emissiveIntensity?, transparent?, opacity?})`
  returning `MeshToonMaterial` — cache keyed by the full param tuple so the
  scene reuses materials instead of allocating per mesh. Sweep the components
  you own from `meshStandardMaterial` to the helper. Keep `meshBasicMaterial`
  labels/overlays as-is. Keep emissive glows (windows, lanterns, flowers).
- **Shadows:** drei `<SoftShadows>` (PCSS) on the existing shadow map is the
  baseline. `<AccumulativeShadows>` ONLY if applied to static geometry and it
  holds 60fps with moving villagers — otherwise skip it and say so.
- **Palette nudge** (art doc): terrain `#8FB85A→#6E9A3E`, paths `#C9A36B`,
  sky gradient warm. Don't repaint every component hex — adjust Ground/fog/sky
  and let the toon ramp + lighting do the work.
- NO postprocessing package this wave (bloom/AO/vignette is EM-127, later).

Tests (minimum, vitest, headless-safe): gradient map step count + NearestFilter
+ no mipmaps; material cache returns identical instance for identical params and
distinct for distinct; emissive params honored. `npm run build` must pass.

## Agent B3 — frontend-foliage (EM-118 + "deepen one city" props) — Wave 2

Owns: `web/src/components/world3d/Scenery.tsx`, `CozyWorld.tsx` (mount points),
NEW foliage/props module(s) (e.g. `Foliage.tsx`), NEW test file for scatter
logic. Consumes `toon.ts` from B2 (do not modify it; blockers go to the
orchestrator).

- **Trees:** replace the 16 individual trees with **instanced** trees — 2–3
  procedural variants (round, tall/conifer, fruit/blossom), batched per part
  (trunks/canopies as instanced meshes or drei `<Instances>`/`<Merged>`),
  total ~50–80 trees forming a town-edge orchard/treeline feel.
- **LOD:** drei `<Detailed>` (or an equivalent distance-gated batch split):
  full detail near, simplified (or culled canopy detail) far. State your
  approach + rough draw-call count in your report.
- **Props that make the town feel lived-in** (procedural, instanced where
  counts warrant, all toon-shaded): lamp posts with warm emissive glow along
  paths, benches near the plaza, fence segments near home/farm edges, bushes/
  shrubs, mushrooms/rocks in wild areas. Keep total NEW instances ≲400.
- **Placement is deterministic** (reuse the existing `hashUnit` scatter
  pattern — no `Math.random()`): clear of place centers (existing minClear) AND
  clear of building slot rings (`SLOT_BASE_RADIUS` + ring growth from
  `worldSpace.ts` — read it, don't edit it): trees ≥ ~10 units from place
  centers so they never collide with project structures.
- 60fps bar applies; prefer fewer, better props over density that drops frames.

Tests (minimum): scatter determinism (same seed → same layout), clearance
invariants (no item within the forbidden radii), variant distribution sanity.

## Agent B4 — frontend-buildings (EM-122, distinct meshes per kind) — Wave 2

Owns: `web/src/components/world3d/Structure.tsx`, `worldSpace.ts`,
`worldSpace.test.ts`. Consumes `toon.ts` from B2 (do not modify).

- Add `operationalVariant(kind: string): VariantKey` to `worldSpace.ts` beside
  `buildingStyle()` (EM-130) — same keyword-matching approach, mapping emergent
  kinds onto a small set of variant keys: `garden`, `farm`, `workshop`,
  `library`, `clocktower`, `house`, `stall`, `monument`, `well`, `generic`.
- In `Structure.tsx`, split `OperationalStructure` into per-variant procedural
  sub-components (garden = planted rows + blooms; farm = field plot + fence;
  workshop = chimney + bench; library = columns + book spines; stall = awning
  + crates; monument = plinth + obelisk, commemorative ones keep their glow;
  well = ring + roof + bucket; house = cottage-ish; clocktower = existing tall
  body + spinning clock; generic = current mesh as fallback). Reuse the
  existing palette from `buildingStyle(kind)`; all materials via B2's
  `toonMaterial`. Keep the idle bob/sway, offline darkening, and EM-102 label
  behavior intact. planned/under_construction/damaged/abandoned/destroyed
  status renderers stay as they are (only swap their materials to toon if
  trivial).
- **Wire condition:** operational buildings with `health < 100` darken/soot
  their body tint proportionally (lerp toward a charcoal), so a half-burned
  workshop LOOKS half-burned before it flips to `damaged`.
- Buildings remain procedural this wave — the external GLB kit swap (KayKit/
  Kenney) stays deferred; the visible outcome (distinct building types per
  kind) is delivered procedurally to match the existing art style and keep the
  bundle light.

Tests (minimum, in `worldSpace.test.ts` or a sibling): `operationalVariant`
exact keys, keyword-matched emergent kinds (e.g. "herb_garden"→garden,
"grain_farm"→farm, "watchtower"→clocktower? choose sensible mappings and test
them), unknown → `generic`; health-tint helper is pure and clamped.

## Waves & gates

- **Wave 1 (parallel):** B1 (EM-115) ∥ B2 (EM-111). Gate: full backend pytest +
  web vitest + `npm run build` + orchestrator browser check (scene renders,
  console clean, golden-hour look visible).
- **Wave 2 (parallel):** B3 (EM-118) ∥ B4 (EM-122) — disjoint files; CozyWorld
  mount edits belong to B3 ONLY. Gate: same suite + browser check.
- **Wave 3:** QE agent — full-suite verification + `coordination/qa-report.json`
  per the existing schema; then ux-review pass + ledger/BUILD doc updates by the
  orchestrator.

## Contract changelog

- v1.0 (2026-06-10): initial.

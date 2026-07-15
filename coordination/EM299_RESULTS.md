# EM-299 — Parametric Building-Recipe Grammar · Build Results

**Branch:** `feat/em299-building-recipes` (off `main`) · **Wave Q keystone** ·
**Status: BUILT, gates green, PR pending. NOT merged. Dormant behind a default-OFF flag.**

Built fully AFK overnight. This is **slice (a)** from the ledger caveat — compose
procedural THREE primitives (extend `Structure.tsx`), **no new assets vendored**
(our CC0 kit is whole-building GLBs, nothing to kit-bash).

## What shipped

A model may now author a building's *shape* via an OPTIONAL `recipe` object on the
`propose_project` turn. The grammar is **reused verbatim** from the EM-297 divergence
probe (which validated it at 100% against real free models).

### Backend
- **`backend/petridish/engine/building_recipe.py`** (new) — canonical runtime grammar:
  6 closed enums + bounded `floors` (1–8), `DEFAULTS`, strict `Recipe` (pydantic,
  `extra="forbid"`), lenient `coerce_recipe` (repairs + records every deviation), and
  `normalize_recipe(raw)` (dict ⇒ canonical value-dict; non-dict ⇒ `None` ⇒ no-recipe
  build). Pure — no clock/random.
- **`world.py`** — `Building.recipe: dict | None` (serialized in `to_dict` **only when
  set**; restored via `_restore_recipe`, re-coerced so a clean recipe round-trips
  byte-identically and a garbage one still renders). `action_propose_project(...,
  recipe=None)` gated on `_building_recipes_enabled()`; the `project_proposed` payload
  carries `recipe` (+ `recipe_repairs`) only when stored.
- **`runtime.py`** — dispatch passes `recipe`; inline schema adds loose
  `"recipe": {"type":"object"}`; the build-menu line gains a compact recipe clause
  **only when the flag is on** (byte-identical off — no trailing-period drift).
- **`config/loader.py`** — `BuildingRecipesParams{enabled=False}` under `WorldParams`
  + `_parse_building_recipes`, wired into `world.building_recipes`. **Default OFF.**

### Frontend
- **`web/src/components/world3d/buildingRecipe.ts`** (new) — pure
  `computeBuildingMesh(recipe, idHash) → RecipeMesh`: footprint→width/depth,
  floors→body height, roof-by-kind primitive params, window grid by density, trim
  tiers; toon-consistent colors (material base × palette anchor + warm window glow).
  Default-safe enums, `floors` clamped, `idHash` drives only a bounded depth jitter.
- **`Structure.tsx`** — new `RecipeStructure` (procedural body + roof + windows + trim,
  health-sooted, skin-overridable, offline-dimmed). Rendered INSTEAD of the
  GLB/silhouette when `building.recipe` is present AND operational/offline; else the
  exact pre-EM-299 path. Mesh memo keys on recipe **content** + id (not identity —
  the citygraph-live-render lesson). Label clears the authored height.
- **`web/src/types/index.ts`** — `BuildingRecipe` type + enum unions + `recipe?` on
  `Building`.

### Docs
- **`contracts/em299-building-recipes.md`** — the contract (law, grammar, wire shape,
  backend/frontend rules, tests, follow-ups).
- **`docs/REMAINING-WORK.md`** — EM-299 row → **in-progress**.

## Gates (all green)

| Gate | Command | Result |
|---|---|---|
| Backend | `.venv/bin/python -m pytest backend/tests/ -q` | **2463 passed, 1 skipped** (was 2443 + 20 new EM-299) |
| Typecheck | `cd web && npx tsc -b --force` | **exit 0** (clean) |
| Frontend | `cd web && node node_modules/.bin/vitest run` | **1486 passed / 123 files** (18 new EM-299) |

Flag-OFF byte-identity is proven directly (`test_flag_off_ignores_recipe_byte_identical`,
`test_pre_em299_snapshot_loads_unchanged`) and indirectly (the whole existing suite
passes unchanged — no golden regenerated).

## The law it honors
- **EM-155 determinism:** flag-off world byte-identical; recipe is a pure fn of the
  input; serialized only-when-set; snapshot/replay/fork byte-identical.
- **Free-scale:** one compact prompt clause (flag-gated), zero extra LLM calls.
- **Fix-don't-hide:** no test weakened, no error masked. A bad recipe degrades
  (coerce-to-defaults or drop-to-catalog), never a rejected/dead turn, never a hole.
- **No drift:** `test_engine_schema_matches_probe` fails if the engine grammar ever
  diverges from `backend/scripts/em297_recipe_schema.py`.

## How to flip the flag (for the user's live sign-off)
1. In `config/world.city25.yaml`, add under `world:`:
   ```yaml
   building_recipes:
     enabled: true
   ```
2. Restart the sim (config bakes per-run).
3. **What to look for:** as agents build, some buildings render as procedural
   recipe shapes (varied footprints/floors/roofs/windows/trim) instead of catalog
   GLBs — each model's town should grow a distinct skyline. Feed `project_proposed`
   cards carry the `recipe` (+ any `recipe_repairs`). Buildings without a recipe look
   exactly as today.

## Deferred / owed (post-sign-off)
- **Live visual sign-off** (user gate — not marked done here).
- **EM-297 lane top-up:** run the probe for the qwen/llama lanes (probe §6) before
  sign-off to confirm divergence across all four production labs.
- **Roof fidelity + window draw-call cost:** see contract §6. Tune `gable`/`hip`
  against the live golden-hour look; add instanced windows if the scene shows draw-call
  pressure at scale.

## Environment note (for the next builder in this worktree)
The repo-root `node_modules` is a **tracked self-referential symlink loop**
(`petri-dish-of-madness/node_modules -> itself`, inherited from `main`). In a fresh
worktree it makes `npm ci` / `npx tsc` / `vitest` in `web/` crash (ELOOP / empty exit
194) because node walks up into the loop. Workaround used here: `mv node_modules
_nm_loop_bak` before running any web toolchain command, then `mv _nm_loop_bak
node_modules` to restore the clean tracked tree. Worth fixing that symlink on `main`
separately (out of scope for EM-299).

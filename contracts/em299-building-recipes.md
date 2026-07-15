# EM-299 (Wave Q) — Parametric Building-Recipe Grammar · Contract

> **Ledger:** `docs/REMAINING-WORK.md` EM-299 (the Wave Q keystone)
> **Depends on:** EM-297 divergence probe (`docs/research/2026-07-11-em297-divergence-probe.md`,
> **verdict GO**) — the probe validated the exact 7-field grammar at 100% schema-validity
> against real free models. **Reuses that grammar verbatim.**
> **Branch:** `feat/em299-building-recipes`
> **Dormant behind a default-OFF flag** (`world.building_recipes.enabled`) until the user's
> live visual sign-off — same gate posture as EM-268 / `ROAD_MESH_ENABLED`.

Agents currently author a building's *kind* only; ~86% collapse to `generic`
(memory: `generic-is-the-dominant-building-variant`). EM-299 lets a model author
the building's *shape*: an OPTIONAL `recipe` object on the build turn → a pure
frontend `computeBuildingMesh(recipe, idHash)` that procedurally generates the
geometry, falling back to today's catalog GLB/silhouette lookup when `recipe` is
absent. Each model's town grows a legible skyline signature.

**Load-bearing scope decision (research-v5-1 §3.1):** our CC0 kit is whole-building
GLBs, NOT modular parts — there is nothing to kit-bash. This slice composes
**procedural THREE primitives**, extending the existing `Structure.tsx` procedural
path. **No new assets are vendored.**

## 0. The law (non-negotiable acceptance bar)

1. **Byte-identical / additive (EM-155).** `Building.recipe` serializes in `to_dict`
   **only when set** (`if self.recipe:`) and restores in `from_snapshot` only when
   present (absent ⇒ `None`, never a crash). With `building_recipes.enabled` **off**,
   no build stores a recipe, `to_dict` omits the key, and the build **prompt menu
   carries no recipe clause** ⇒ **byte-identical to pre-EM-299**. Full backend +
   frontend suites pass unchanged — no golden regenerated.
2. **The build ALWAYS succeeds.** A bad / missing / garbage recipe **never** rejects
   or wastes the turn (EM-266's posture). Three explicit tiers on the tick path
   (probe §6 recommended posture):
   - **strict-valid** dict ⇒ stored as-is (canonical value-dict);
   - **salvageable** dict (bad/missing fields) ⇒ **coerced** to grammar defaults,
     with every repair recorded; stored;
   - **unsalvageable** (a non-object: string / list / number / null) ⇒ **dropped**,
     the build proceeds as a normal no-recipe build (today's catalog fallback).
   Never a dead turn, never a hole.
3. **Deterministic (EM-155).** The stored recipe is a **pure function** of the input
   dict — no clock, no randomness, no `uuid4` on the recipe path. The frontend mesh
   is a pure function of `(recipe, idHash)`. Round-trips through snapshot/replay/fork
   byte-identically.
4. **The runtime grammar EQUALS the EM-297 probe grammar.** No drift — enforced by
   `test_em299_building_recipes.py::test_engine_schema_matches_probe` (loads the probe
   module by path and asserts identical enum vocabularies, floors bounds, defaults,
   field set/order).
5. **Free-scale (flat prompt).** The recipe clause is ONE compact line appended to the
   `propose_project` menu, added **only when the flag is on**. Zero extra LLM calls —
   the recipe rides the existing build turn.

## 1. The grammar (7 fields — 6 closed enums + 1 bounded int)

Verbatim from `backend/scripts/em297_recipe_schema.py`; the engine copy is
`backend/petridish/engine/building_recipe.py`.

| field | type | allowed values | default |
|---|---|---|---|
| `footprint` | enum | `tiny` `small` `medium` `large` `grand` | `medium` |
| `floors` | int | `1`–`8` (clamped) | `1` |
| `roof` | enum | `flat` `shed` `gable` `hip` `dome` `spire` | `gable` |
| `material` | enum | `wood` `timber_frame` `brick` `stone` `marble` `plaster` `mud_brick` | `wood` |
| `palette` | enum | `warm` `cool` `earthy` `pastel` `vivid` `muted` `monochrome` | `earthy` |
| `window_density` | enum | `none` `sparse` `regular` `dense` | `regular` |
| `trim` | enum | `none` `simple` `ornate` `gilded` | `simple` |

## 2. The wire shape (the only cross-layer coupling)

The recipe crosses backend→frontend as a **flat 7-key object**, serialized only when set:

```
# backend (Python)   Building.recipe: dict | None       # canonical value-dict, or None
# wire (JSON)         "recipe": {"footprint": "...", "floors": 4, "roof": "...", ...}
#                                                        # present only when set; omitted ⇒ pre-EM-299
# frontend (TS)       recipe?: BuildingRecipe | null     # web/src/types/index.ts
```

The stored dict always has keys in **canonical order** (`footprint, floors, roof,
material, palette, window_density, trim`) regardless of the order the model emitted
them, so snapshots are byte-stable.

**Frontend gate = recipe presence.** The backend is the *sole authority* for whether
a recipe enters the snapshot (it serializes one only when the flag is on AND a
salvageable recipe was authored). The renderer therefore renders the procedural mesh
**iff `building.recipe` is present** — there is no separate frontend flag to keep in
sync (mirrors how `skin` / `zone_id` / `position` render on presence). Flag off ⇒ no
recipe in any snapshot ⇒ the renderer is exactly the pre-EM-299 path.

## 3. Backend rules

- **Action:** `action_propose_project(..., recipe=None)`. Gated on
  `world.building_recipes.enabled` (`_building_recipes_enabled()` →
  `_block_get(params.building_recipes, "enabled", False)`).
- **Normalization:** `engine.building_recipe.normalize_recipe(raw)`:
  - `dict` ⇒ `coerce_recipe` (always yields a valid `Recipe`; drops unknown keys,
    defaults missing/invalid enums, clamps `floors`) → `(canonical value-dict, repairs)`.
  - non-`dict` ⇒ `(None, notes)` ⇒ no recipe stored (build proceeds normally).
- **Persistence:** stored on `Building.recipe`; `to_dict` emits `"recipe"` only when
  set; `from_snapshot` restores via `_restore_recipe` (re-coerces the stored dict —
  idempotent for a clean recipe ⇒ byte-identical round-trip; repairs a hand-edited /
  garbage one so it still renders).
- **Observability:** the `project_proposed` event payload carries `recipe` (+
  `recipe_repairs` when coercion changed anything) **only when a recipe was stored** —
  additive, byte-identical when absent.
- **Prompt:** the `propose_project` menu line gains `recipe?` + one compact
  enum-listing clause **only when the flag is on** (`_building_recipes_enabled(params)`
  in `runtime.py`). Off ⇒ the line is byte-identical (no trailing period drift).
- **Schema:** the inline action schema adds `"recipe": {"type": "object"}` (LOOSE —
  the closed-enum grammar is enforced by server-side coercion, not the structural
  gate, so a malformed shape never fails the turn).

## 4. Frontend rules

- **Pure module** `web/src/components/world3d/buildingRecipe.ts`:
  `computeBuildingMesh(recipe, idHash) → RecipeMesh` — deterministic geometry
  (footprint→width/depth, floors→body height, roof→primitive by kind, window grid by
  density, trim tiers) + toon-consistent colors (material base × palette anchor, warm
  golden-hour window glow). Every enum lookup is default-safe; `floors` clamped
  `[1,8]`; `idHash` (a stable `hashUnit(id)`) drives **only** a bounded depth jitter,
  never the silhouette.
- **`Structure.tsx`:** when `building.recipe` is present AND status is
  `operational`/`offline`, render `RecipeStructure` (procedural body + roof + windows +
  trim, health-sooted, skin-overridable, offline-dimmed) INSTEAD of the GLB/silhouette;
  otherwise the exact pre-EM-299 path. Label clears the authored `totalHeight`.
- **Memo discipline (citygraph-live-render lesson):** the mesh memo keys on the recipe
  **content** (`JSON.stringify(recipe)`) + `id`, NOT object identity — a fresh snapshot
  object each tick would otherwise recompute every frame (identity) or never re-render
  a live change (naive identity memo). Content-keying recomputes exactly on change.

## 5. Tests (all three gates green)

- **Backend** `backend/tests/test_em299_building_recipes.py` (20): flag-off
  byte-identity, coercion edges (unknown enum / oversized floors / unknown keys /
  empty dict / non-dict-drop), serialize-only-when-set, snapshot round-trip +
  hand-edited-recipe restore, determinism (fixed sequence), event payload, config
  default-off, and the **probe drift guard**.
- **Frontend** `buildingRecipe.test.ts` (13): determinism, monotonic footprint widths,
  finite/positive geometry for every footprint×roof, floors clamp, window-density
  ordering + in-bounds coords, valid `#rrggbb` colors, trim-tier escalation, garbage-enum
  fallbacks, NaN-idHash safety, `mixHex`.
- **Frontend** `Structure.recipe.test.tsx` (5): no-recipe ⇒ GLB path (Model mounts);
  recipe ⇒ GLB suppressed + procedural meshes; undefined-recipe safety; planned-state
  unaffected.

## 6. Known follow-ups (post-sign-off)

- **Draw-call cost:** a dense grand 8-floor building emits up to ~16 window planes;
  across 100s of buildings this is many draw calls. Acceptable for the sign-off slice
  (village is ~tens of buildings); an instanced-window pass is the optimization if the
  live scene shows pressure.
- **Roof fidelity:** `gable` is a two-plank tent and `hip` a 4-sided pyramid — legible
  and distinct, but not architecturally exact. Tune against the live golden-hour look
  at visual sign-off.
- **EM-297 lane top-up:** before visual sign-off, run the probe top-up for the qwen /
  llama lanes (probe §6) to confirm divergence across all four production labs.

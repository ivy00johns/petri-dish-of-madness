# Wave K — The Builders' City (design)

> **Status:** design (approved via brainstorm 2026-06-18). Ledger entries **EM-216–221**.
> **One-liner:** agents shape and decorate their own town — they pick real building
> *types*, place and remove *props* (benches, trees, statues…), demolish, and re-skin
> what they own; the god console gets parity levers. Breadth-first, reflex-first,
> population-capped, replay-safe.

## Why

The town already *looks* customizable — it has benches, lamps, trees, distinct
buildings — but none of it is **agent-driven**:

- Props (benches/lamps/trees/fences) are **deterministic seeded scatter** in
  `cityLayout.ts`. Nobody — agent or god — can add, move, or remove a single one.
  They are painted-on scenery, not real objects.
- Building *type* is a **free-text `kind` string** the agent guesses blind
  (`action_propose_project`, `world.py`). The frontend `operationalVariant(kind)`
  fuzzy-matches that word into ~10 visual buckets; a poor match renders a generic box.
  Agents are never shown what they *can* build.
- The only path to removing a structure is **`arson` → health 0 → destroyed**. There
  is no clean demolish, and a building's color is derived only from health + kind.

So the gap between "a city that changes because the agents changed it" and what we
have is: **a real menu of building types, placeable/removable props as first-class
objects, a clean demolish, and an agent-set skin** — plus the assets to make the
variety *visible*.

## Goals / non-goals

**Goals**
- Agents choose building *types* from a real, prompt-surfaced menu (permissive — off-menu
  inventions still resolve).
- Agents place and remove **props** (decorations/furniture/nature) as first-class objects
  the world tracks.
- Agents (and owners) **demolish** buildings cleanly and **re-skin** their own building.
- The god console mirrors every agent lever (place/remove/recolor/demolish + bursts).
- Expand the vendored Kenney CC0 3-D vocabulary so "different types" is actually visible.

**Non-goals (this wave)**
- No prop *economy* (props are free/cheap texture, not a crafting/inventory sim).
- No agent-created **places** (props/buildings still attach to existing places).
- No per-prop health/lifecycle, funding, or build steps (that's what makes them *not*
  buildings — see Decision 1).
- Vehicles stay as their own tracked items (EM-169/176) — once props land, a vehicle is
  conceptually "a prop category," but moving traffic is out of scope here.

## Architecture decisions

### Decision 1 — props are their own lightweight entity (modeled on `Animal`)

A placed prop must become something the world **remembers** (so it persists, replays,
forks, and can be removed). It is stored as a dedicated lightweight entity rather than a
flavored `Building`:

- A `Building` carries owner, location, status machine, health, funding, build progress —
  none of which a bench needs. Reusing it would drag that baggage and mix decorations into
  the building list.
- The **`Animal`** entity is the proven template for "lightweight, reflex-driven,
  population-capped, snapshot-serialized, replay-safe." Props copy that pattern exactly.

```
Prop {
  id: str            # stable; derived from a seeded hash for replay alignment (cf. EM-189)
  kind: str          # "bench" | "lamp" | "tree" | "statue" | "planter" | "stall" | ...
  place: str         # the place id it sits at (no free-floating props)
  offset: (dx, dz)   # small in-place offset so multiple props don't stack on the anchor
  owner_id: str|None # the agent who placed it, or None for god/seeded
}
```

Stored in `world.props: dict[str, Prop]`, serialized into the snapshot `state_json`
alongside agents/buildings/animals, and **population-capped** (`world.params.max_props`).
The cap protects free-scale: more props = more chronicle texture, never more LLM calls.

### Decision 2 — building types are a permissive catalog

Add a documented `build_type` **catalog** surfaced in the turn prompt; keep today's
free-text fallback so creativity never dead-ends:

- Each catalog entry maps to a **distinct GLB** + a default `function` buff + a
  **zone affinity** (e.g. `smithy` → industrial). The catalog is the single source of
  truth shared by the prompt text, the function-grant logic, and the renderer.
- An off-menu / free-text `kind` (e.g. "moon-temple") is **not rejected** — it resolves
  through the existing `operationalVariant()` fuzzy match (EM-130 neutral fallback). No
  turn is ever wasted on an invalid type.

This **extends** EM-122/EM-150 (the kind→GLB swap already shipped); it does not replace
the mapping, it widens it and makes the choices legible to the model.

## Invariants (load-bearing across all slices)

- **Free-scale / do-more:** every new agent action is a **reflex** tool — the kind/type/
  color rides the agent's existing turn, zero extra invoke-LLM calls. Population caps, not
  muting, hold the cost line. (Honors the no-throttle north star.)
- **Replay/fork determinism (EM-155):** anything the world tracks (props, skins, demolish
  state) is serialized into the snapshot and reconstructed byte-identically on replay/fork.
  Prop ids derive from a seeded hash (avoid the EM-189 uuid-vs-determinism trap).
- **Never a dead turn:** permissive fallbacks everywhere — unknown build types, capped
  prop placement, etc. degrade to a sensible result + feed line, not an idle.
- **Fallback render invariant (EM-148):** a procedural mesh renders while a GLB streams in;
  a prop/building never shows a hole.

## The slices (breadth-first; each a demo-able PR)

### K0 — Asset vocabulary expansion (EM-216) · *enabler*
Vendor curated Kenney CC0 kits: **Nature Kit** (trees/rocks/plants/flowers), expanded
**Furniture/City** props (benches, lamps, planters, statues, market stalls, signage), and
more **building** GLBs for distinct types. Run the EM-152 pipeline (gltfjsx `--transform`
atlas/dedupe + toon-ramp conversion per atlas). New `PROP_MODELS` registry (prop kind →
GLB) and an expanded building catalog in `models.ts`/`cityModels.ts`. Every file recorded
in `ASSET_LICENSES.md`. *Unblocks K1–K5 visually.*

### K1 — Building-type catalog (EM-217)
Backend: a `BUILD_TYPES` catalog (type → function buff + zone affinity); the turn prompt
lists the menu; `action_propose_project` keeps accepting any `kind` (permissive). Frontend:
`operationalVariant()`/`buildingStyle()` gain the new types → distinct GLBs from K0.
Tests: each catalog type resolves to its own GLB; an off-menu kind still resolves to the
neutral fallback (no dead turn).

### K2 — Props as first-class items (EM-218) · *keystone*
Backend: the `Prop` entity + `world.props`, reflex `place_prop(kind, place?, offset?)`
(defaults to the agent's current place), `max_props` cap, `prop_placed` event, snapshot
(de)serialization. Frontend: `PROP_MODELS` instanced render path (drei `<Instances>`),
fallback procedural mesh. Tests: place → snapshot → restore is byte-identical; cap is
honored; replay reproduces props exactly.

### K3 — Remove & demolish (EM-219)
Backend: reflex `remove_prop(prop_id)` and a clean `demolish(building_id)`
(owner/governance-gated, distinct from `arson`; frees the lot back to claimable per the
EM-174/EM-181 lot model). Events `prop_removed` / `building_demolished`. Frontend clears
the mesh and releases the lot. Tests: demolish frees the lot; arson semantics unchanged;
gating enforced at resolution.

### K4 — Recolor / skin (EM-220)
Backend: a `tint`/`skin` field on `Building`, set by a light reflex tool (agent self /
owner), serialized. Frontend: the renderer reads it as a material override, layered over
(not replacing) the health-soot tint. Pairs with the Wave I art-banner path (EM-213).
Tests: skin persists across snapshot; health soot still composes on top.

### K5 — God-console parity (EM-221)
Frontend + backend: god-panel controls over the same APIs — place/remove/recolor props,
demolish buildings, and a "decorate"/"clear" prop-burst (mirrors the rewild/zoo-escape
buttons). A manual curation + seeding lever; no new engine semantics beyond K2–K4.

## Cross-links (existing ledger items — referenced, not duplicated)

- **EM-182** (agent-chosen *placement*/zone) is the natural companion to K1/K2 — "build a
  house in the industrial district." Recommend pulling it into this wave; not re-filed.
- **EM-169 / EM-176** (vehicles) become "a prop category" conceptually once K2 lands;
  moving traffic stays their scope.
- **EM-123** (zoning growth) and **EM-183** (vote to move the town center) are unaffected
  and benefit from the richer vocabulary.

## Build order & dependencies

```
EM-216 (K0 assets) ──┬─► EM-217 (K1 types) ──► EM-220 (K4 recolor) ──┐
                     └─► EM-218 (K2 props) ──► EM-219 (K3 remove) ───┴─► EM-221 (K5 god)
```

K4 may swap ahead of K3 (it's lighter); K5 is last (it consumes K2–K4 APIs).

## Open questions (carry into implementation)

1. **Prop cap value** — what `max_props` keeps the chronicle lively without flooding the
   scene at 25 agents? (Tune from a live run, like the animal cap.)
2. **Demolish gate** — owner-only, or governance-vote for public structures? (Lean: owner
   for self-built, ~70% vote for public/landmark — reuse the governance texture.)
3. **Prop placement freedom** — does `place_prop` honor an agent-chosen zone (depends on
   EM-182), or only the agent's current place for v1? (Lean: current place for v1.)

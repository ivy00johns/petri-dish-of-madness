# Contract — Wave K · The Builders' City (EM-216–221 + EM-182)

> **Integration surface** for the agent-driven 3-D customization arc. Design:
> `docs/superpowers/specs/2026-06-18-builders-city-design.md`. This contract is the
> single source of truth for the names/shapes backend ⇄ frontend ⇄ god-console agree on.
> Implementers conform to existing repo patterns (cited by symbol) for everything else.

## Invariants (apply to every item)

- **Reflex / free-scale:** new agent tools are `tier:"reflex"` — the kind/type/skin rides
  the agent's existing turn. **Zero extra invoke-LLM calls.** Caps, not muting, hold cost.
- **Replay/fork determinism (EM-155):** anything added to world state serializes into
  `to_snapshot()` and restores byte-identically in `from_snapshot()`. **No `uuid4`** for
  prop ids — derive from a seeded hash (cf. EM-189). Frontend stays pure-of-`Math.random`/
  `Date` on any path feeding the deterministic city layout.
- **Never a dead turn:** unknown build type → fuzzy fallback (EM-130/`operationalVariant`);
  capped/invalid placement → rejection *with guidance*, resolved as the engine's idle.
- **Fallback render invariant (EM-148):** procedural mesh renders while a GLB streams; a
  prop/building never shows a hole. Unknown prop/building kind → procedural + label.
- **Token discipline:** WebGL material colors stay out of the CSS design-token system (the
  existing `BUILDING_STYLES`/`ANIMAL_STYLES` convention). DOM/CSS in ControlPanel obeys
  `design-token-guard` (no inline styles / off-token hex).

---

## 1. Backend entity — `Prop` (EM-218)

New dataclass in `engine/world.py`, modeled **exactly on `Animal`** (class @327, `to_dict`
@352; registry `self.animals` @516; snapshot @3344; restore @3404):

```python
@dataclass
class Prop:
    id: str                      # "prop_" + seeded hash(place, kind, ordinal) — NOT uuid4
    kind: str                    # free-text, ≤30 chars; FE maps to a prop model/style
    place: str                   # place id it sits at (must exist; no free-floating props)
    dx: float = 0.0              # in-place offset, engine-assigned (deterministic ring)
    dz: float = 0.0
    owner_id: str | None = None  # agent who placed it; None for god/seeded
    def to_dict(self) -> dict: ...   # {id, kind, place, dx, dz, owner_id}
```

- Registry: `self.props: dict[str, Prop]` (init beside `self.animals`).
- Cap: read modestly from config — mirror `params.animals.max_population`. Add
  `params.props.max_population` (loader.py + both yamls), **default 48** (a populated town,
  not overwhelming; tunable up). Over cap ⇒ `place_prop` rejected with guidance.
- Offset: engine assigns `(dx,dz)` deterministically from the count of props already at the
  place (small ring, ≤ ~3u radius) so props don't stack. Pure/seeded.
- Snapshot: add `"props": [p.to_dict() for p in self.props.values()]` to `to_snapshot()`;
  restore in `from_snapshot()` (tolerate pre-Wave-K snapshots with no `props` key → `{}`).

## 2. Backend tools (EM-217/218/219/220 + EM-182)

Add to `TOOL_REGISTRY` (runtime.py @211), the inline arg schema (runtime.py @145 `allOf`),
**and** `contracts/action-protocol.schema.json` (canonical). Handlers mirror
`action_adopt`/`action_contribute_funds` (return `(ok: bool, msg: str)`); register in the
same action dispatch; offered via `_assemble_context` valid-actions and enforced in
`_validate_world` (menu and resolution must agree — EM-108's lesson).

| action | tier | location_gate | args (required • optional) | gate (in `_validate_world`) |
|--------|------|---------------|----------------------------|------------------------------|
| `place_prop` | reflex | None | `kind`(≤30) • `place` | place exists; under `max_props` cap; defaults `place`→agent.location |
| `remove_prop` | reflex | None | `prop_id` • — | prop exists; agent is owner **or** co-located with an unowned prop |
| `demolish` | reflex | `@building` | `building_id` • — | agent is the building's **owner** ⇒ immediate; else REJECT with guidance (public/landmark goes through governance — see §3) |
| `set_building_skin` | reflex | `@building` | `building_id`, `skin`(≤24) • — | agent is the building's owner |

**EM-182 — `propose_project` gains optional `place`:** if provided and a valid place id,
the new Building's `location` = that place (build in a chosen district); else current
behavior (agent.location). Add `place: {type:string}` to the propose_project arg schema
(optional). Frontend lot assignment already keys off `building.location` (no FE change
needed beyond honoring it).

**EM-220 — Building gains `skin`:** add `skin: str | None = None` to `Building`
(default None), include in `Building.to_dict()`, restore in `from_snapshot`. `set_building_skin`
sets it; owner-only.

**EM-217 — build-type catalog:** a `BUILD_TYPES` table (new small module or in world.py)
of `{type, function, zone}` surfaced in the propose_project prompt guidance
(`_assemble_context`). `propose_project` stays permissive (`kind` free-text). Where a catalog
type trivially matches an existing buff (`smithy`/`forge`→work_reward, `granary`→forage,
`tavern`/`market`→work_reward, `park`/`garden`→forage), extend the existing kind→buff
mapping; otherwise the type is cosmetic+labelled (no buff). v1 menu (≥10):
`tavern, market, smithy, school, temple, clinic, park, granary, well, workshop, garden, house, library, monument, farm`.

## 3. Backend governance — public demolish (EM-219)

Public/landmark demolish uses the **existing** governance pipeline, not a bespoke vote:
add a rule **effect** `demolish` carrying a `target` building id. When a rule with effect
`demolish` passes (the shipped propose_rule→vote→`_evaluate_rule`→`_on_rule_activated`
path, ~70% majority), the engine demolishes the target building. Reuses EM-087/EM-103
governance texture; the agent `demolish` tool handles only the owner case (§2).

## 4. Events

Emit via the same mechanism as `animal_*` / `structure_*` events (the action-resolution
event stream; god paths build the dict inline like `/api/god/rewild`). Add to the event-kind
schema/contract where animal/structure kinds are listed.

| kind | payload |
|------|---------|
| `prop_placed` | `{prop_id, kind, place, owner_id}` |
| `prop_removed` | `{prop_id, kind, place}` |
| `building_demolished` | `{building_id, kind, name, place, by}` |
| `building_reskinned` | `{building_id, skin}` |

## 5. God endpoints (EM-221) — Wave 2

Mirror `/api/god/rewild` (@1148) + `/api/animals` (@1101): read `_world`, mutate via the
same world methods/tools the agents use, emit god-ink events (`actor_type:"god"`,
`payload.method`), one `world_state` broadcast at the end. Cap burst counts.

| endpoint | body | effect |
|----------|------|--------|
| `POST /api/god/place_prop` | `{kind, place, count?}` | place `count` (≤ a small cap) props at `place` |
| `POST /api/god/clear_props` | `{place?}` | remove props at `place` (or all) |
| `POST /api/god/demolish` | `{building_id}` | demolish immediately (god override) |
| `POST /api/god/reskin` | `{building_id, skin}` | set building skin |

## 6. Frontend

- **Types (`web/src/types/index.ts`):** add `Prop {id, kind, place, dx, dz, owner_id}`;
  `skin?: string | null` on `Building`; `props?: Prop[]` on `WorldState`.
- **Prop registry (`world3d/assets/models.ts` or new `propModels.ts`):** `PROP_MODELS`
  (prop kind → `ModelSpec`) wired to **already-vendored** Kenney furniture GLBs
  (bench, lamp/streetlight, tree, fence, bin, hydrant) + fantasy-town fountain. A pure
  `propVariant(kind)` resolver (substring map → known prop kinds, mirror
  `operationalVariant`), `null`/unknown ⇒ procedural fallback. Record any reuse in
  `ASSET_LICENSES.md` (no NEW kit downloads this wave — see K0 note below).
- **Prop render:** a `<PlacedProps>` component reading `world.props`, positioning each at
  `placeToWorld(place) + (dx,dz)`, rendering the GLB via the existing `<Model>` wrapper
  with procedural fallback; instanced where repeats warrant. Mount in `CozyWorld.tsx`.
- **Build-type catalog (`worldSpace.ts`):** extend `EXACT_VARIANTS`, `VARIANT_KEYWORDS`,
  and `BUILDING_STYLES` so each menu type resolves to a distinct palette/label + best
  available vendored GLB/variant. (Fully distinct *models* per type arrive with K0.)
- **Skin override (`Structure.tsx`):** operational body color = `skinPalette(building.skin)
  ?? buildingStyle(kind).body`, then `healthTint(...)` on top (soot still composes). A small
  named `SKIN_PALETTES` map (e.g. rose/sky/sage/amber/slate/plum); unknown skin ⇒ ignored.
- **God UI (`controls/ControlPanel.tsx`):** a "BUILDERS" group in the god console — place
  prop (kind + place picker + count), clear props, demolish (building picker), reskin
  (building + skin) — mirroring the rewild/zoo-escape button + spawn-form pattern. Obeys
  `design-token-guard`.

### K0 note (EM-216) — assets

This build wires the new registries to the **existing** vendored GLBs so props + types
render now. Acquiring NEW Kenney CC0 kits (Nature Kit, more Furniture/City, distinct
per-type building models) needs network + the gltfjsx/toon-ramp pipeline (EM-152) and is a
**recorded HITL follow-on** — it is NOT silently dropped; `BUILD_RESULTS.md` lists exactly
what was deferred and why. EM-216 closes when the kits land; the systems built here consume
them with zero further wiring.

## File ownership (no overlap)

- **backend-agent:** `backend/petridish/engine/world.py`, `engine/loop.py`,
  `agents/runtime.py`, `config/loader.py`, `config/world.yaml`, `config/world.city25.yaml`,
  `api/app.py` (god endpoints, Wave 2), `contracts/action-protocol.schema.json`,
  `backend/tests/test_wave_k_*.py`.
- **frontend-agent:** `web/src/components/world3d/**`, `web/src/types/index.ts`,
  `web/src/components/controls/ControlPanel.tsx`, `web/src/hooks/useSimulation.ts`,
  `web/src/mock/generator.ts` (mock props for FE tests), `ASSET_LICENSES.md`,
  co-located `*.test.ts(x)`.
- **qe-agent (verify):** `backend/tests/test_wave_k_integration.py` (+ a determinism test);
  runs full suites; produces `qa-report.json`. Does not edit impl files.

## Wave-gate commands

- Backend: `backend/.venv/bin/python -m pytest -q`
- Frontend: `cd web && PATH="/Users/johns/.nvm/versions/node/v24.6.0/bin:$PATH" node_modules/.bin/vitest run`
- Token gate (UI waves): the repo's `design-token-guard` against `web/` (zero NEW errors;
  `web/.design-guard.json` is the baseline).

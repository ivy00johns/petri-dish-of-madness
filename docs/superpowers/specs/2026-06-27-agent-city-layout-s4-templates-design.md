# Agent-Controlled City Layout — S4: Templates / City Profiles

> **Parent:** `2026-06-27-agent-city-layout-overview-design.md`.
> **Depends on:** S1 (graph spine + `classic_grid`); reuses S3b's parametric `master_plan`
> library for non-grid presets (which therefore also need S5a to *render*).
> **Status:** design (2026-06-27).

## 1. Goal

Define the **"city profile"** that was never worked out: a **named starting template +
params** that seeds the initial `CityGraph` at run start. This is the variety-of-starts lever
*and* the user's authoring lever ("what *I* can generate") — chosen at run start via config,
agents take it from there (the agents-drive-emergently pillar holds).

Key reuse: **a template is a master plan applied at run start with no morph** — it's the
seed. S4 reuses S3b's `master_plan(kind, params, seed, extent)` library rather than inventing
a parallel generator.

## 2. Non-goals

- **No live god-editing or drag-to-draw editor** — run-start config picker only. (Live
  god-edit is a noted cheap follow-on via the existing god channel; a full editor is out.)
- **No new generator math** — presets are the S1/S3b generators.

## 3. The city profile

```
city:
  template: greenfield      # grid | greenfield | village | pentagon | radial | ring
  size: 7                   # graph extent in blocks (bounded by MAX_CITY_BLOCKS)
  density: low              # seeds how much starting road/structure exists
  car_policy: cars          # starting global policy (S3a can change it later)
  seed: 1337               # determinism
```

A **city profile = template + params + default policies**. Pure function of
`(template, params, seed)` → the initial `CityGraph` (and global car-policy).

### Preset set
- **grid** — the `classic_grid` (S1). Axis-aligned → ships on the tile renderer.
- **greenfield** — minimal: a central plaza + a stub or two; agents build the rest. Supports
  "maybe they don't build anything" (a near-empty graph is valid).
- **village** — sparse, organic-ish scatter of short streets. Axis-aligned variant ships
  pre-S5a; an organic variant waits for S5a.
- **pentagon / radial / ring** — the S3b `master_plan` kinds applied at start (no morph).
  **Non-axis-aligned → render gated on S5a**, exactly like S3b.

So **grid / greenfield / (axis-aligned) village ship before S5a**; the geometric presets ride
S5a alongside S3b.

## 4. Determinism & integration

- **Determinism:** the initial graph is a pure function of the profile (no clock/RNG beyond
  the seeded-hash idiom) → same profile + seed ⇒ byte-identical start; replay/fork safe.
- **Backend:** generalize S1's `classic_grid` call into a `template(profile, seed)` dispatcher
  (reusing the S3b library); world init seeds the `CityGraph` from it.
- **Config:** `config/world.yaml` gains the `city:` block; `config/loader.py` parses it.
- **Frontend:** surface the active template name in the UI (read-only). A run-start picker UI
  is an optional later nicety — config is the MVP lever.

### Synergy with parallel worlds (EM-112) + Model-Family Arena (EM-119)
Different runs with different profiles, or the same profile seeded across model families,
make the city *form* a comparable outcome — "Gemini-on-greenfield vs Qwen-on-greenfield."
S4 is the knob that makes those comparisons legible.

## 5. Components & boundaries

- **Backend — `engine/citygraph.py`:** `template(profile, seed)` dispatcher over the
  presets; greenfield/village generators (axis-aligned now).
- **Backend — `config/loader.py` + `config/world.yaml`:** parse the `city:` profile block.
- **Frontend:** display template name; optional later picker.

## 6. Testing & acceptance

- Each preset is deterministic per `(profile, seed)`; config round-trips.
- **Greenfield edge case:** a near-empty graph renders + drives perception without crashing
  (no roads → no lots → agents must build) — the "build nothing" case is safe.
- Grid/greenfield/village render on the tile path; geometric presets render once S5a lands.
- Acceptance: choosing a template in `world.yaml` starts a run with that city; agents then
  reshape it via S2/S3.

## 7. Risks & open questions

- **Near-empty graphs** (greenfield) stress every derivation (lots/streets/landmarks/
  perception) — test the degenerate cases explicitly.
- **Geometric presets** inherit S5a's dependency and visual-sign-off (§S5).
- **Open:** how rich `density`/`params` get — start with a tiny param set, grow on demand.

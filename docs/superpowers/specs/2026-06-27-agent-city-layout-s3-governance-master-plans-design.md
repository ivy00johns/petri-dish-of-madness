# Agent-Controlled City Layout — S3: Governance + Master Plans

> **Parent:** `2026-06-27-agent-city-layout-overview-design.md`.
> **Depends on:** S1 (graph spine), S2 (`build_road` + event/apply pattern), and — for
> **S3b only** — S5a (procedural road meshing for arbitrary geometry).
> **Status:** design (2026-06-27).

## 1. Goal

Deliver the headline examples — **ban cars / all-sidewalks**, **teardown**, and **master
plans** (pentagon / radial / ring) — through the **existing town-hall vote** (the hybrid
pillar: destructive/structural/city-wide changes are collective, not individual). Reuses
governance (EM-079/087/100/103, EM-183 "move town center", EM-240 town-hall trials).

S3 splits into two phases so the geometry-heavy part is isolated:

- **S3a — vote-gated toggles** (`demolish`, `pedestrianize`/`ban_cars`): axis-aligned,
  reuses the tile renderer. Cheap; ships two headline examples without new geometry.
- **S3b — master plans** (pentagon/radial/ring): non-axis-aligned → gated on **S5a**. The
  heavy part.

## 2. Shared scaffolding (both phases)

- **Proposal verbs** create a town-hall proposal; ratification at the existing **~70% vote
  threshold** triggers application. Mirrors EM-183's "vote to move the town center" exactly.
- **Every applied change is a `layout_event`** (`road_demolished`, `car_policy_set`,
  `master_plan_adopted`, `building_relocated`) appended to the stream from S1/S2 — so the
  graph stays a pure function of its event log and replay/fork are byte-identical.
- **Perception:** extend S2's `nearby_layout` block with current car-policy and any active
  proposal/morph, district-scoped (prompt-diet law).

---

## 3. S3a — vote-gated toggles (cheap, axis-aligned)

### 3a.1 `demolish`
- **Proposal:** `propose_demolish(edge | building)`. Ratified → remove the edge/building.
- **Cascade:** removing an edge can orphan lots/buildings on its block face → relocate them
  to the nearest valid lot (see §4.3 relocation, shared with S3b), or mark the lot vacant.
- **Event:** `road_demolished` / `building_demolished` (+ `building_relocated` as needed).
- **Determinism:** removal + relocation are pure functions of the graph + seed.

### 3a.2 `pedestrianize` / `ban_cars`
- **Proposal:** `propose_car_policy(scope, policy)` where `scope ∈ {street, district, city}`
  and `policy ∈ {cars, pedestrian, mixed}`. "Ban cars + all sidewalks" = city-scope
  `pedestrian`.
- **Effect:** sets `car_policy` on the graph (city) or on edges (street/district). This is a
  **render/behavior flag**, not geometry: ambient traffic (EM-169) + parked cars
  (`CARS_ENABLED`, EM-176) stop on `pedestrian` edges; pedestrianized streets render with a
  sidewalk/plaza surface variant (reuses existing tiles + a surface tint; a footpath GLB is
  an optional S5 polish, not required).
- **Event:** `car_policy_set`.
- **No new geometry** → S3a ships on the S1/S2 tile renderer.

S3a acceptance: a ratified vote bans cars city-wide (traffic + parked cars vanish, surfaces
read as pedestrian) or tears down a road/building; both survive replay/fork.

---

## 4. S3b — master plans (morph model; gated on S5a)

The town can ratify a whole **topology**. Chosen application model: **morph the whole city** —
the plan is laid over the existing graph and the city *transitions toward it over time*, so
you watch it reshape (not an instant swap, not a preserved-core annex).

### 4.1 Target generation (parametric library)
`master_plan(kind, params, seed, extent)` → a target `CityGraph`. Initial kinds:
- **pentagon** — nodes on a pentagon perimeter + radial spokes to a center + optional ring.
- **radial** — concentric rings + spokes (a roundabout center node).
- **ring** — outer ring road + interior grid infill.
- **grid** — the `classic_grid` (lets a town vote *back* to a grid).

Pure function of `(kind, params, seed, extent)`; extensible (the library is the long-tail
growth surface). Non-axis-aligned edges + roundabout/plaza nodes ⇒ **requires S5a meshing**.

### 4.2 The morph
- **Diff:** correspond current nodes to target nodes by spatial proximity/snapping →
  compute edges to **add** and edges to **remove**.
- **Schedule:** apply the diff over a deterministic window of ticks (k edges/tick, ordered by
  a seeded key) — emitting `road_built` / `road_demolished` events. The reshape is itself a
  visible, emergent event in the world.
- **Determinism:** target, diff, schedule, and ordering are all pure functions of
  `(current graph, target, seed)` → replay re-applies the identical morph.

### 4.3 Building relocation (shared with S3a demolish)
- Buildings are **preserved where their lot survives** the morph.
- A building whose lot is removed **relocates** to the nearest valid lot in the evolving
  graph (deterministic nearest-lot, input-order-independent — same discipline as
  `assignBuildingLots`); emit `building_relocated`.
- If no lot is available, the building is queued and placed as lots open (deterministic).

### 4.4 Adoption gate
`propose_master_plan(kind)` → town-hall proposal → ~70% ratification → the morph schedule
begins. While a morph is active, conflicting layout proposals are blocked (one master plan at
a time).

S3b acceptance: a ratified pentagon plan visibly reshapes the city over several ticks; roads
render at arbitrary angles (S5a), roundabout centers read correctly; buildings survive or
relocate deterministically; the whole morph replays byte-identically.

## 5. Components & boundaries

- **Backend — `engine/citygraph.py`:** the parametric `master_plan` library; `diff_graphs`;
  the morph scheduler; relocation; `apply_*` for each S3 event.
- **Backend — governance (`engine/world.py` / governance module):** new proposal types
  routed through the existing vote machinery + threshold; "one active master plan" guard.
- **Backend — agent action surface (`agents/runtime.py`):** `propose_*` verbs + extended
  perception (car-policy, active morph).
- **Frontend — renderer:** S3a needs only a car-policy flag + a pedestrian surface variant.
  **S3b needs S5a** (arbitrary-angle road meshing + roundabout/plaza geometry); traffic
  (EM-169) honors per-edge `car_policy`.

## 6. Testing & acceptance

- **S3a:** proposal→vote→apply for `demolish` and `car_policy`; cars/traffic stop on
  `pedestrian`; demolish cascade + relocation; all events replay byte-identically.
- **S3b:** `master_plan` target determinism per kind; `diff_graphs` correctness; morph
  schedule determinism + ordering; relocation determinism; full morph replay/fork parity.
- **Governance:** threshold reuse; one-active-plan guard; conflicting-proposal blocking.
- **Free-scale:** proposal verbs are turn options; perception delta within diet.

## 7. Risks & open questions

- **S3b is the program's hardest slice** — graph diffing + scheduled morph + relocation +
  non-axis-aligned rendering all at once. Keep S3a shippable on its own; do not let S3b block
  the car-free/teardown wins.
- **Morph legibility:** too fast reads as a teleport, too slow drags. Tune k-edges/tick
  against a live run.
- **Relocation churn:** a big morph could relocate many buildings at once. Cap relocations
  per tick (deterministic queue) to keep it legible and cheap.
- **S5a coupling:** S3b cannot ship until S5a renders arbitrary geometry — sequence
  S3a → S5a → S3b.
- **Open:** master-plan `params` surface (how much agents/voters parameterize a plan vs. pick
  a named preset) — start with **named presets**, parameterize later.

## 8. Handoff

- S4 (templates) reuses the same `master_plan`/parametric-generator library as its starting
  presets — a template *is* a master plan applied at run start (no morph; it's the seed).
- S5a is the gating dependency for S3b; S5b (building variety) is independent throughout.

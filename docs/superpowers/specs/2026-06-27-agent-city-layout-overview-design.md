# Agent-Controlled City Layout — Initiative Overview

> **Status:** design (brainstorming output, 2026-06-27). Parent doc for a
> multi-spec initiative. Each sub-project below gets its own design spec →
> implementation plan → build cycle. This doc holds the shared decisions and
> the decomposition so the sub-specs stay consistent.

## The problem

The 3-D city reads as boxy and repetitive. Two root causes:

1. **The layout is frozen art, not a world.** `web/src/components/world3d/cityLayout.ts`
   emits a fixed **5×5 Manhattan grid** as a *pure function of `(places, city_seed)`*
   (EM-155 byte-identical; EM-174 emits zero decorative buildings). Roads never move;
   nothing in the sim can say "the agents chose this street." Agent influence on form
   today is a single crack — EM-183 "vote to move the town center."
2. **The asset vocabulary is tiny.** 99 GLBs on disk collapse to a **frozen 23-key
   registry** (`assets/cityModels.ts`) with **one GLB per key** — roads are literally 5
   Kenney tiles, and buildings collapse to a thin "generic" pool (~86%). That is the
   visual repetition in the screenshots.

## The vision

Give **the agents** control over the **full city form** — where streets go, what gets
built where, whether to add traffic circles, ban cars and go all-sidewalks, lay out a
pentagon road plan, or build nothing at all. Start from a basic city (a *template*) that
the agents then reshape. The city's *shape* becomes an emergent signature you watch —
the same thesis as crime/governance, applied to urban form (imagine one model family
growing a tidy grid while another sprawls into a radial mess).

## Foundational decisions (the three pillars)

These were settled in brainstorming and bind every sub-spec:

1. **Authorship — agents, emergently.** Layout is sim state the *agents* mutate, not a
   god/editor tool. Spine = backend event-sourced state + agent verbs/votes. (A god/run-start
   authoring lever for the *user* is a secondary affordance, folded into S4 templates, not
   the spine.)
2. **Representation — a free-form road graph (nodes + edges).** Topology is arbitrary:
   grid, radial, ring, pentagon, and traffic circles (a node rendered as a roundabout).
   This is the only model that expresses every example above; it is the largest rendering
   departure (procedural road meshing eventually replaces the axis-aligned tile palette).
3. **Decision mechanism — hybrid.** Agents *build freely* on their turn (cheap, emergent
   growth); *destructive / city-wide / structural* changes (demolish others' work, ban
   cars, re-plat a district, adopt a master plan) go through the **existing town-hall
   vote** (reuses EM-079/087/100/103, EM-183). "Pentagon roads" = a master plan the town
   ratifies.

## Decomposition

| # | Sub-project | What it is | Ships | Depends on |
|---|---|---|---|---|
| **S1** | **Layout-graph spine** | Promote layout from a frozen `(places, seed)` function to an **event-sourced `CityGraph`** (nodes/edges/policy) that is authoritative backend state. Seed it from one axis-aligned `classic_grid` template so the **current tile renderer is reused** and output is **byte-identical**. | Same city — now data, not frozen code. The keystone. | — |
| **S2** | **Agent build verbs + local perception** | Cheap individual verbs (`build_road`, `build_on_lot`); district-scoped layout in the prompt (prompt-diet-safe). Axis-aligned for now → tile renderer still works. | Watch agents organically extend streets. | S1 |
| **S3** | **Governance + master plans** | Vote-gated `demolish` / `pedestrianize` / `ban_cars` / `adopt_master_plan`. Master plans are parametric generators (pentagon / radial / ring) the town ratifies. Needs arbitrary-angle road meshing + roundabout/plaza geometry. | The headline examples. Heaviest. | S1, S2, S5a |
| **S4** | **Templates / city profiles** | The named starting set (basic grid, greenfield, village, coastal…) + the user's run-start picker / authoring lever ("what *I* can generate"). | User control + variety of starts. | S1 (which ships template #1) |
| **S5** | **Asset & road-mesh expansion** | (a) **Procedural road meshing** for arbitrary geometry + roundabout/plaza/footpath/bridge pieces (feeds S3). (b) **Building-variety expansion** to kill the ~86% generic monoculture via the existing poly.pizza CC0 pipeline (`docs/em216-kit-acquisition-plan.md`). | (b) fixes the repeat-asset pain immediately and is independent. | (a) feeds S3; (b) standalone |

**Sequence:** `S1 → S2 → S3`, with **S4** folded across and **S5(b)** runnable in
parallel as an immediate win. The cleverness that keeps S1/S2 cheap: keep the graph
**axis-aligned** at first so the existing tile renderer is reused; defer the hard
procedural-geometry work (S5a) until S3 actually needs pentagon/roundabout shapes.

## Cross-cutting constraints (apply to every sub-spec)

- **Determinism / replay (EM-155).** Render must stay a pure function of state; layout
  state must stay a pure function of its event log. Same snapshot + seed ⇒ byte-identical,
  across live/replay/fork. No `Math.random`, no clock — the seeded-hash idiom only.
- **Free-scale law.** New agent actions are *options in the existing turn*, never new
  standing LLM calls. Layout perception in the prompt is **district-scoped** to respect
  the prompt-diet caps (`deep-research-v4.md §5`). Never throttle/mute agents to afford this.
- **Fallback discipline (ModelBoundary).** A snapshot without a graph (old run / old API)
  must still render via today's path — "never a hole, never a crash."
- **CC0-only assets.** Every vendored GLB gets an `ASSET_LICENSES.md` row (standing rule).

## Resolved design decisions (per sub-spec)

- **S1** — roads-only first-class (lots/blocks/zones derived); byte-identical is the gate.
- **S2** — `build_road` only; paid in energy + the turn; individuals can only *grow* the graph.
- **S3** — split into **S3a** (cheap vote-gated `demolish` + car-policy, axis-aligned) and
  **S3b** (master plans). S3b application model = **morph the whole city** (the city visibly
  reshapes over ticks; buildings preserved-or-relocated).
- **S4** — run-start preset picker + params via `config/world.yaml`; a template *is* a master
  plan seeded at start; reuses the S3b generator library.
- **S5** — **S5a** road rendering = **procedural extrusion** (gates S3b + geometric presets);
  **S5b** building-variety expansion is standalone (the immediate repeat-asset fix).

## Revised sequence (with the splits + dependencies)

`S5b (anytime) ‖ S1 → S2 → S3a → S5a → S3b`, with S4's grid/greenfield/village landing after
S1 and its geometric presets riding S5a alongside S3b.

## Status of the sub-specs (all designed 2026-06-27)

- **S1** — `2026-06-27-agent-city-layout-s1-graph-spine-design.md`
- **S2** — `2026-06-27-agent-city-layout-s2-build-verbs-design.md`
- **S3** — `2026-06-27-agent-city-layout-s3-governance-master-plans-design.md`
- **S4** — `2026-06-27-agent-city-layout-s4-templates-design.md`
- **S5** — `2026-06-27-agent-city-layout-s5-assets-meshing-design.md`

**Next:** file these into the tracked ledger via the `plan-intake` skill (fail-closed), then
take the first slice (S1, or S5b for an immediate win) into the `writing-plans` /
implementation cycle.

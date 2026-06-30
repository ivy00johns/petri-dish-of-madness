# Agent-Controlled Building Layout — Initiative Overview

> **Status:** design (brainstorming output, 2026-06-29). Parent doc for a
> multi-spec initiative. Each sub-project below gets its own design spec →
> implementation plan → build cycle. This doc holds the shared decisions and
> the decomposition so the sub-specs stay consistent.
>
> **Lineage:** the direct continuation of the **Agent-Controlled City Layout**
> initiative (`2026-06-27-agent-city-layout-overview-design.md`, EM-239/243/244/
> 245/246/247/248, all merged). That suite gave **roads** an emergent, agent-
> authored, free-form graph and a procedural mesh renderer. This suite does the
> same for **buildings**.

## The problem

EM-247 made roads any-angle (pentagon, radial, roundabouts) and shipped the
procedural mesh as the default renderer. But the buildings didn't move.
`web/src/components/world3d/cityLayout.ts` `computeCityPlan` **Pass 1**
(≈ lines 919–934) still iterates a **fixed axis-aligned grid of blocks**
(`bx, bz ∈ −B_MAX..B_MAX`, each at `bx*BLOCK_PITCH, bz*BLOCK_PITCH`) that is
computed **independently of the road graph**. So a pentagon road plan renders
with grid buildings sitting on top of it — *"you can still see the underlying
city layout."* Roads are emergent; building lots are frozen art.

## The vision — and the reframe

Buildings should follow the roads the agents actually built. The way to find
*where a building could go* is to find the regions the roads enclose — the city
blocks (the **planar faces** of the road graph).

But this is a **chaos experiment**, not a city planner. The point is emergence,
so the design deliberately rejects the "derive correct lots → fill them tidily"
framing. Instead:

> The graph derives buildable **zones** (loose regions, optionally carrying
> rules). Agents then **choose** whether and how to build in them — including
> badly, including not at all, including over the line. **Freedom to make
> mistakes is part of the madness.**

The user's directive, verbatim: *"They need freedom to make mistakes as well as
part of the madness. They can make rules for areas, and agents can choice to
build there if they want. this is a chaos experiment, need flex."*

A zone is an **affordance the agents act on**, not a layout function that
`assignBuildingLots` consumes wholesale.

## Foundational decisions (the pillars)

Settled in brainstorming; they bind every sub-spec.

1. **Buildings follow the road graph, via planar faces.** The enclosed regions
   of the road graph become the buildable zones. This replaces the fixed-grid
   Pass 1.
2. **Loose, not precise.** Geometric precision of face boundaries is **not** the
   crux. A slightly-wrong block is fine — an agent will just build on it weirdly,
   which is the point. The **only** failures that matter are: a crash, or a
   *whole region silently dropped* so no agent can ever build there. Defensive
   handling of dangling stubs / disconnected components / degenerate faces stays
   important; pixel-perfect edges do not.
3. **Zones are affordances with optional rules, not assignments.** A zone is
   "you may build here," plus an optional `rules` field (zoning hint, density
   cap). Rules are **suggestions agents can honor, break, or ignore.**
4. **No special-casing.** The inner "core" face of a pentagon/radial is just
   another buildable zone. Agents pile into it and choke the center → *a finding,
   not a bug.* Nobody builds there → an empty plaza, also fine.
5. **Hybrid decision model carries over (EM-244/245).** *Building is free* (the
   build-freely side). *Zone rules are city policy → vote-gated* (the same
   `action_propose_rule` → `_evaluate_rule` 0.7 supermajority → `_on_rule_activated`
   machinery the road initiative used). The chaos lives in the tension: the town
   votes a rule into being, and any individual can defy it on their turn.
6. **Flag + default-off byte-identical path (EM-155).** All new behavior sits
   behind `GRAPH_LOTS_ENABLED` (mirrors `ROAD_MESH_ENABLED`). Default **off** ⇒
   the rendered plan is byte-identical to today's grid, so the old city stays
   reproducible and you can A/B exactly what changed.

## Decomposition

| # | Sub-project | What it is | Ships | Depends on |
|---|---|---|---|---|
| **SA** | **Graph-derived buildable zones** | New `cityFaces.ts` → `planarFaces(graph)`; each face becomes a **zone** (buildable region + empty `rules` hook); `computeCityPlan` branches behind `GRAPH_LOTS_ENABLED` to place buildings into zones, lot grid a *suggestion* (overflow/gaps allowed). Frontend-only. | The visible win: pentagon roads finally get pentagon-shaped blocks. The keystone + the data shape. | EM-247 (merged) |
| **SB** | **Agent-authored zone rules** | Vote-gated verb `propose_zone_rule(zone, rule)` (zoning hint + optional density cap) on the EM-244/245 governance machinery; stable zone identity that survives morphs; perception surfaces zones + rules; rules render (tint/label, content-keyed signature). Rules are advisory metadata. | *"They can make rules for areas."* | SA |
| **SC** | **Zone-targeted emergent building** | Agents target a zone when building; rules are honored-or-broken, never enforced (wrong type, over-cap, choke the core all succeed); "build nothing" stays valid; renderer shows the mess honestly (cram/overflow); optional violation record (observation, no penalty). | *"Agents can choose to build there if they want"* + freedom to make mistakes. The emergent payoff. | SB |

**Sequence:** `SA → SB → SC`. SA is frontend-only and shippable alone (it's the
"pentagon roads, pentagon blocks" fix). SB + SC are the emergent loop. The flag
+ default-off byte-identical path carries through all three.

## Cross-cutting constraints (apply to every sub-spec)

- **Determinism / replay (EM-155).** Render stays a pure function of state; layout
  state a pure function of its event log. The **off** path stays byte-identical to
  today's grid. The **on** path is a *new* deterministic layout — it gets its own
  golden (same graph + seed ⇒ byte-identical) but is not required to match the grid.
  No `Math.random`, no clock — the seeded-hash idiom (`worldSpace.hashUnit`) only.
- **Live-render content-key (the thrice-shipped bug).** Anything rendering from
  `city_graph` must key its memo on graph **content** (node/edge counts +
  `car_policy` + a kinds/rules hash), never object identity, or live mutations
  don't render until reload. Bit EM-243/244/247; every slice here adds a
  render-reactivity test. See `citySignature` / `useCityPlan` in `CityScape.tsx`.
- **Free-scale law.** New agent actions (SB/SC) are *options in the existing turn*,
  never new standing LLM calls. Zone perception is district-scoped to respect the
  prompt-diet caps. Never throttle/mute agents to afford this.
- **Fallback discipline (ModelBoundary).** A snapshot without a graph (old run /
  old API) and the flag-off path must both render via today's grid — "never a
  hole, never a crash." Face enumeration runs upstream of the per-piece
  `<ModelBoundary>`, so it must degrade, never throw.

## Status of the sub-specs (all designed 2026-06-29)

- **SA** — `2026-06-29-agent-building-layout-sA-graph-zones-design.md`
- **SB** — `2026-06-29-agent-building-layout-sB-zone-rules-design.md`
- **SC** — `2026-06-29-agent-building-layout-sC-emergent-build-design.md`

**Ledger:** SA = **EM-264**, SB = **EM-265**, SC = **EM-266** (next free IDs;
filed via `plan-intake`, fail-closed).

**Next:** take SA (EM-264) into the `writing-plans` / implementation cycle.

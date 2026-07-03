# Free Placement + Settlements — Initiative Overview

> **Status:** design (brainstorming output, 2026-07-02). Parent doc for a
> multi-spec initiative. **Supersedes the *building-placement* direction of the
> Agent-Controlled Building Layout suite (EM-264/265/266)** — which bound building
> to the road graph's enclosed faces and thereby restricted *where* agents could
> build. The *road* suite (EM-239–248) is untouched and reused.

## The problem — why we're reversing course

Wave P (EM-264/265/266) made buildings derive from the road graph's planar
**faces**. The live sign-off (2026-07-02, `GRAPH_LOTS_ENABLED` + `GRAPH_ZONES_ENABLED`
flipped on) exposed the cost:

- Buildings became **confined to road-enclosed regions.** A single pentagon
  trapped the entire city *inside* it; nothing outside the roads was buildable.
- It **stalled the expanding-city and multi-city goals.** With placement gated by
  enclosed faces, the city can't sprawl outward or spawn a distant second cluster.
- It **inverted the ethos.** The thing that made this project work was agents
  having *free rein to build wherever*. Binding building to roads made building a
  **slave to roads** — a restriction dressed as a feature.

The flags have been reverted (both off, `main`); the world is un-caged again. This
initiative replaces the binding with the freedom it displaced — and then goes
*past* the old fixed 5×5 grid to true free placement.

## The vision

Agents build **anywhere**, cluster where they like, deliberately **found new
settlements** in far corners, and lay roads/patterns **purely because they want
them** (a roundabout in the residential, a pentagon for the industrial, a road
that runs off toward the next town). **Multi-city falls out of the freedom** —
many settlements + connecting roads — not a bolted-on mode. The city's *spread and
shape* become the emergent signature you watch.

## Foundational decisions (the pillars) — settled in brainstorming 2026-07-02

1. **Free placement.** Building is gated by *nothing* — not roads, not a fixed
   grid. A build lands at a world position via a deterministic organic placement
   function. Agents can build anywhere on the open map.
2. **Agent-founded settlements.** A lightweight **Settlement** primitive
   (`name` + `center` + loose membership) that agents can **found anywhere** via a
   new turn action. Settlements are cluster *seeds/anchors*, **not containers that
   gate building.** `len(settlements) > 1` *is* multi-city.
3. **Roads are optional decoration + identity.** Keep the entire agent-controlled
   road engine (build_road, demolish, master plans, morph, car policy, procedural
   mesh) — but **sever the building↔road-face tie.** Roads gate nothing; a road
   toward another settlement reads as connection *visually*, mechanically it's free
   decoration.
4. **Hybrid placement mechanic.** Default: a build spreads organically from the
   agent's current location / home settlement — cheap, needs no map knowledge.
   Optional: the agent attaches a **target** (a direction, a named place/settlement,
   or "found here") to place deliberately. Agency when they want it; emergence by
   default.

## The key architectural shift

Building placement moves from a **frontend render-time computation**
(`cityLayout.assignBuildingLots` plats buildings into lots) to **backend
event-sourced world state**: each building carries a deterministic **position** +
optional **settlement membership**, set when it is built. The frontend *renders*
positions; it no longer *invents* the layout.

This is exactly the promotion **S1 (EM-239)** did for roads — a frozen frontend
`(places, seed)` function → agent-controlled backend state — now applied to
**buildings**. Concentrating the deterministic placement math in **one frame**
(backend) is deliberate: it keeps replay byte-identical *and* avoids reintroducing
the cross-frame divergence class of bug that bit the road work (logical 0..1000 vs
world ±33). Determinism (EM-155), the free-scale law, and fallback discipline all
carry over unchanged.

## What we keep vs retire

- **Keep:** the road engine (EM-239–248) in full — `build_road`, `demolish_road`,
  master plans, morph, car policy, and the `RoadMesh` procedural renderer. Agents
  still author roads freely; roads just stop gating building.
- **Retire (as a placement mechanism):** the graph-lots binding — `cityFaces`
  `planarFaces` → zones → building placement (EM-264 SA placement path). Buildings
  no longer derive from faces.
- **Set aside:** road-face zone rules (EM-265 SB) + zone-targeted building
  (EM-266 SC). Their propose/vote governance machinery is reusable; the
  *road-face-derived* zoning is dropped. If zoning returns, it is a **settlement /
  region** property, never road-derived. The Wave P *code* stays on `main` behind
  `GRAPH_LOTS_ENABLED` / `GRAPH_ZONES_ENABLED` (both off); the rejected activation
  attempt (flag-flips) was reverted and dropped in cleanup, recoverable via git reflog.

## New agent surface (free-scale: turn options, never new standing LLM calls)

- **`found_settlement(name, where)`** — deliberately seed a new cluster anchor at a
  chosen spot/direction (the far-corner town).
- **`build(...)` gains an optional `target`** — a direction, a named
  place/settlement, or "found here" — defaulting to organic spread from the agent's
  location when omitted.
- **Perception:** a compact, district-scoped "settlements + directions + nearby"
  sense so an agent *can* place deliberately, without bloating the prompt
  (prompt-diet law). Default builds need zero map knowledge.

## Cross-cutting constraints (unchanged from the frozen design)

- **Determinism / replay (EM-155).** Placement position is a **pure function of
  (anchors, seed, building set), input-order-independent** — the `assignBuildingLots`
  discipline generalized to free coordinates. Same snapshot + seed ⇒ byte-identical
  across live/replay/fork.
- **Free-scale law.** New actions are options in the existing turn; perception is
  district-scoped. Never throttle/mute agents to afford this.
- **Fallback discipline.** Old snapshots (buildings with no stored position /
  settlement) and no-settlement builds must render deterministically — *never a
  hole, never a crash.* Migration derives positions on load.
- **CC0-only assets** (standing rule).

## Decomposition (slices) — sequential, each shippable, each byte-identical-gated

| # | Slice | What it is | The win |
|---|---|---|---|
| **F1** | **Unbind + free placement core** | Retire the graph-lots placement path; replace fixed-grid/face placement with deterministic **free-coordinate organic placement** anchored to the existing city center (one implicit settlement). Buildings sprawl the open map. | "Free rein" restored — and past the old grid. The keystone. |
| **F2** | **Settlement primitive + founding** | Add `Settlement` (backend state) + `found_settlement` action + membership + settlement perception. Placement anchors to the agent's settlement. | Multi-city becomes *possible* — deliberate, agent-driven. |
| **F3** | **Deliberate placement target** | `build` gains the optional `target` (direction / settlement / place); compact map perception. | Agents place a roundabout-district, a far-corner town, on purpose. |
| **F4** | **Roads as pure decoration (formalize)** | Confirm roads gate nothing; a road between settlements reads as connection. Mostly falls out of F1's unbinding — this is cleanup + "roads I lay for vibe" perception. | Roads become expression, not constraint. |

**Later, deferred (not now):** a roads-as-light-connection *mechanic* (option B from
brainstorming); settlement-level zoning; explicit multi-city stats/UI. Held back so
the first city can *deepen* before multi-city is *encouraged* (not just enabled).

**Sequence:** `F1 → F2 → F3`, with **F4 folded into F1's unbinding**. **F1 alone
restores the freedom** and is worth shipping first on its own.

## Open questions for the F1 sub-spec

- The exact **frontend/backend split** of the placement function (lean: positions
  are backend state; frontend renders them — see the architectural shift above).
- The **organic-placement algorithm** (seeded spiral / jittered-Poisson around
  anchors, overlap avoidance) and its byte-identical golden.
- **Migration** for existing runs' buildings (derive-on-load vs preserve stored).

## Status

Design (2026-07-02). **Next:** user reviews this overview; then decompose **F1**
into a sub-spec + implementation plan (`writing-plans`). Ledger: file via
`plan-intake` (fail-closed) under the next free `EM-###` IDs.

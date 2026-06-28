# Agent-Controlled City Layout — S2: Agent Build Verbs + Local Perception

> **Parent:** `2026-06-27-agent-city-layout-overview-design.md`.
> **Depends on:** S1 (`...-s1-graph-spine-design.md`) — the mutable backend `CityGraph`,
> the `layout_event` envelope, and the graph-driven renderer.
> **Status:** design (2026-06-27).

## 1. Goal

Give agents the first verb that reshapes the city: **`build_road`** — extend the road graph
by one axis-aligned segment on the agent's turn. This is the initiative's first *visible*
emergent payoff: you watch streets grow where agents choose to build. Because the graph
stays **axis-aligned**, S1's tile renderer is reused unchanged — no new geometry yet.

## 2. Non-goals (out of scope for S2)

- **No demolish, no car-policy change, no master plans** — all destructive/structural/
  city-wide changes are vote-gated in S3.
- **No agent choice of building placement** (`claim_lot`) — building placement stays
  auto-assigned (`assignBuildingLots`, unchanged). Chosen separately later.
- **No non-axis-aligned geometry, roundabouts, or new assets** — S3 + S5a.
- **No new standing LLM calls** — `build_road` is an option in the existing turn.

## 3. The verb: `build_road`

- **Semantics:** extend a road one segment (`BLOCK_PITCH`, 13u) in a cardinal direction
  (N/E/S/W) from the graph node nearest the agent's current location. Adds the target node
  if absent and the connecting edge.
- **Validity rules:**
  - **Anchored:** must extend from an existing node (no floating roads).
  - **In-bounds:** target within `MAX_CITY_BLOCKS` (a bounded growth cap — protects prompt
    + render budget; e.g. grow the 5×5 up to a 9×9 envelope, tunable).
  - **Vacant:** no edge already on that segment.
  - **Affordable:** agent has ≥ `ROAD_BUILD_ENERGY_COST` energy.
  - On failure the agent gets a clear reason (out of bounds / already a road / too tired).
- **Cost:** deduct `ROAD_BUILD_ENERGY_COST` energy and consume the turn. Energy is the
  natural rate-limiter (reuses the survival system; no new economy).
- **Emergent loop:** new roads enclose new block faces → new platted lots derive
  automatically (S1's graph-driven derivation) → founded buildings auto-assign into them.
  Roads literally create developable land.

Individuals can only *grow* the graph in S2 — there is no individual teardown — so the city
accretes and stays legible. (Demolition is the vote-gated S3 lever.)

## 4. Local perception (prompt)

Agents need to see nearby layout to choose a build. Add a compact, **district-scoped**
`nearby_layout` block to the prompt, sized for the 8K Cerebras lane (prompt-diet law,
`deep-research-v4.md §5`):

```
Nearby layout: you're at the Oak Lane / Maple Row corner.
  Extendable: north (open), east (open). Blocked: south (road), west (edge of city).
  Lots: 2 empty within a block. Cars: allowed.
```

- Only the agent's local neighborhood/district — never the whole graph.
- Hard-capped lines; degrades gracefully (omit when nothing is extendable).
- Counts and directions only — no full node/edge dump.

## 5. Determinism, events & replay

- **`road_built` event:** `{ agent_id, from_node, direction, new_node_id, new_edge_id,
  tick }`. Node/edge ids are deterministic from grid position
  (`n:{gx},{gz}` / `e:{a}->{b}`), so replay re-adds the identical edge.
- **Graph = pure function of the `layout_event` log** (S1's contract). Replay/fork re-derive
  the grown graph by replaying `road_built` in tick order. EM-155 holds.
- **Render:** the frontend re-derives from the mutated graph each snapshot — a new edge
  appears with **no frontend code change** (S1 guaranteed this).

## 6. Derivation generalizes (why S1 came first)

S1 moved blocks/lots/landmarks/streets to derive from *the graph* rather than the fixed
5×5. S2 simply grows the graph; derivation follows for free:

- **Lots:** new block faces → new platted lots (existing logic over the larger graph).
- **Streets:** new grid lines get seeded names from the existing street-name bank
  (`computeStreets` generalized to the current graph extent — already graph-driven post-S1).
- **Landmarks:** still snap to the nearest node.

## 7. Frontend integration

Essentially **none beyond S1** — the graph-driven renderer already re-derives. The one real
requirement is that the **tessellation handles irregular axis-aligned graphs**, not just the
full 5×5: a single extension creates a new `road_end` (dead-end stub) and turns its anchor
into a `road_tee`. The existing mask classification (`END_ROT`/`TEE_ROT`/`CORNER_ROT`)
already supports this; S2 must *test* it on partial/extended grids (S1 only exercised the
full grid).

## 8. Components & boundaries

- **Backend — `engine/citygraph.py`:** `apply_build_road(graph, from_node, direction)` →
  validated mutation + `road_built` event; bounds/vacancy/anchor checks; deterministic ids.
- **Backend — agent action surface (`agents/runtime.py`):** register `build_road` as a turn
  action with energy cost + failure messaging; assemble the `nearby_layout` perception block.
- **Backend — `engine/loop.py`:** apply the event, deduct energy, advance the turn (the
  action *is* the turn).
- **Frontend:** no new code; add tessellation tests for irregular graphs.

## 9. Testing & acceptance

- **Verb validity:** anchored / in-bounds / vacant / affordable rules; clear failure reasons.
- **Energy:** correct deduction; verb refused (no graph change) when too tired.
- **Determinism / replay:** a run with N `road_built` events re-derives the identical graph;
  ids stable.
- **Tessellation on irregular graphs:** a single extension yields the correct `road_end` +
  `road_tee`; multi-extension shapes classify correctly (new S2 frontend tests).
- **Derivation:** new roads produce new lots/streets; buildings auto-assign into new lots.
- **Perception:** `nearby_layout` present, district-scoped, size-bounded; omitted when
  nothing is extendable.
- **Free-scale:** no new standing call; prompt delta within the diet budget.

**Acceptance:** an agent can spend energy to extend a street; the new road (and the lots it
creates) appear in the live view and survive replay/fork byte-identically; the city only
grows (no individual teardown).

## 10. Risks & open questions

- **Tessellation parity on irregular grids** is the main new risk (S1 only proved the full
  grid). Mitigation: dedicated S2 tests for dead-ends/tees/corners from partial extensions.
- **Prompt bloat:** keep `nearby_layout` minimal and district-scoped; measure against the
  8K lane.
- **Runaway growth:** `MAX_CITY_BLOCKS` + energy cost bound it; tune so a city grows over a
  session without exploding render/prompt budgets.
- **Open:** exact `ROAD_BUILD_ENERGY_COST` and `MAX_CITY_BLOCKS` values — set during
  implementation against a live run; pick so a road is a meaningful but not rare act.

## 11. What S3 needs from S2 (handoff)

- A working individual mutation path (`build_road`) + `road_built` event — S3's vote-gated
  verbs follow the same apply/event pattern.
- Proven tessellation of irregular axis-aligned graphs (S3 then adds non-axis-aligned).
- Local perception scaffolding to extend with car-policy + master-plan proposals.

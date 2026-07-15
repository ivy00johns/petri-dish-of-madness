# Contract: Multi-City Frontend (frontend)

**Version:** 1.0.0 · **Owner:** frontend · **Consumes:** `contracts/settlement-travel.md` (backend)

Renders 2+ settlements as distinct cities + visualizes travel. Pure `f(world)`, no new
network. Owns `web/src/` only.

## 1. Data shape (from `world_state` broadcast — already/soon present)

```ts
// web/src/types/index.ts — Settlement EXISTS (:271); ADD the 3 agent fields.
interface Settlement { name: string; center: [number, number]; founded_tick?: number; founder_id?: string; members?: string[] }
interface WorldState { settlements?: Record<string, Settlement>; /* … */ }
interface AgentState {
  home_settlement_id?: string | null;   // NEW — the agent's city
  in_transit_to?: string | null;        // NEW — target settlement id while traveling
  transit_arrival_tick?: number | null; // NEW — arrival tick
  /* … existing … */
}
```
`center` is WORLD-FRAME (±33), same frame as `SettlementLabels`/`CityScape`. Convert
logical↔world with the existing `worldSpace.ts` helpers — DO NOT hand-roll (two-coordinate-frame
bugs have bitten this repo repeatedly).

## 2. Per-settlement geometry (3D — the main new work)

Today ONE `<CityScape>` renders at `GRID_CENTER {0,0}` (CityScape.tsx:80) and `SettlementLabels`
(CozyWorld.tsx:699) draws N name markers. Buildings already free-place at world positions near
their settlement (F1 SETTLEMENT_R). **Goal: each settlement reads as a distinct city**, not one
grid + scattered buildings + far labels.

- Render a per-settlement ground/road **cluster centered at each `settlement.center`** — reuse
  the CityScape/road geometry, offset per center (parameterize the hardwired center, or mount one
  instance per settlement). Assign a place/building to a settlement by NEAREST center (mirror the
  backend `nearest_settlement` radius) so each cluster shows only its own.
- Keep it deterministic and instanced (perf: 60fps target, EM-155-safe render). If full
  per-settlement CityScape re-centering is too large for one pass, the MINIMUM bar is: a distinct
  ground pad + that settlement's buildings + its label at each center, visually separated.
- `SettlementLabels` stays (it already works); ensure it reads with the new geometry.

## 3. In-transit agent viz (3D + 2D)

An agent with `in_transit_to != null` is TRAVELING (off-board on the backend). Render it as a
marker moving along the straight line from its home settlement center → target center, positioned
by progress `= clamp((tick - departTick)/(transit_arrival_tick - departTick))`. `departTick` is
derivable, or interpolate from `transit_arrival_tick` + a constant; a simple "🧳 traveling to X"
indicator on the route is acceptable for v1. Do NOT render it inside either city.

## 4. 2D WorldMap (`web/src/components/map/WorldMap.tsx`)

It already receives the full `world` (incl. `world.settlements`) but draws none. Add: a marker +
label per settlement at its center (the macro "cities on the grid" view the user wants), routes
between settlements, and in-transit agents on those routes. This is the closest thing to the
"expandable world grid" view — make settlements first-class on the 2D map.

## 5. Feed (event cards)

New event kinds `travel_departed` / `travel_arrived` (+ existing `settlement_founded`) get feed
cards in the appropriate registry (`web/src/components/feed/`), styled as normal movement events
(NOT errors). Reuse the settlement/movement card chrome.

## Acceptance (frontend self-check before wave gate)

- [ ] `tsc -b --force` clean; full `vitest run` green.
- [ ] With 2 settlements in `world`, each renders a visually distinct city cluster at its center.
- [ ] An `in_transit_to` agent renders on the route between cities, not inside one.
- [ ] 2D WorldMap shows both settlements + the route.
- [ ] `travel_departed`/`travel_arrived` render as feed cards.
- [ ] Single-settlement world renders exactly as before (no regression).

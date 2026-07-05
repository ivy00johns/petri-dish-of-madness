# Free Placement F1 — Organic Cluster-Accretion Placement (sub-spec)

> **Status:** design (brainstorming output, 2026-07-04). Sub-spec of
> [`2026-07-02-free-placement-and-settlements-design.md`](2026-07-02-free-placement-and-settlements-design.md)
> (initiative overview). Covers **F1 only** — the unbind + free-coordinate
> placement keystone. **Ledger:** EM-268. **Acceptance bar:** byte-identical
> determinism (EM-155). **Next:** `writing-plans` → orchestrator build.
>
> **Supersedes** the graph-lots *building-placement* path of Wave P
> (EM-264 SA placement / EM-265 / EM-266). The road engine (EM-239–248) is
> untouched and reused. F2 (settlements), F3 (deliberate target), and multi-city
> UI are **out of scope** — see "Out of scope" below.

## Goal

Retire the frontend's invention of building positions and the building↔road-face
tie. Each building gains a deterministic **world position** — computed by a
**cluster-accretion** algorithm anchored to the existing city center (F1's single
implicit settlement) — set at build time as backend event-sourced state. The
frontend *renders* positions; it no longer *invents* the layout. Buildings sprawl
the open map and clump into organic **hamlets**, restoring build-anywhere freedom
and going past the old fixed 5×5 grid.

This is exactly the promotion **S1/EM-239** did for roads (frozen frontend
`(places, seed)` fn → agent-controlled backend state), now applied to buildings.

## Pillars carried from the overview (unchanged)

1. **Free placement** — building is gated by *nothing* (not roads, not a grid).
2. **Roads are decoration** — keep the whole road engine; sever the building→face tie.
3. **Determinism (EM-155), free-scale, and fallback discipline all carry over.**

## Decisions locked in brainstorming (2026-07-04)

| Decision | Choice | Why |
|---|---|---|
| **Placement algorithm** | **Deterministic cluster accretion** (canonical order + seeded preferential attachment + seeded overlap resolution) | Only option that forms *hamlets* rather than an even scatter — the emergent signature the user wants. |
| **Coordinate frame** | Store `position` in the **world frame (±32.5 tile-center units)** — the frame citygraph nodes *and* `assignBuildingLots` already output; **no render conversion** | Zero frame-crossings is the safest anti-EM-243 choice; flag-on and the flag-off fallback then emit identical-frame coords the render path consumes the same way. (CityGraph nodes are world-frame, NOT logical — `citygraph.py:35-36`.) |
| **Persistence model** | **Store at build time** (primary); **derive-on-load** only for position-less (pre-F1) buildings | Ids are minted-once-and-persisted (R1), so positions pin to the same lifecycle; old saved cities never reshuffle. |
| **Rollout** | Flag-gated **`FREE_PLACEMENT_ENABLED`, default OFF, byte-identical** | Same discipline as `ROAD_MESH_ENABLED` / `GRAPH_LOTS_ENABLED`; a user visual sign-off flips it on without regenerating the golden. |

## Determinism envelope (R1 — verified in code, no design change)

Building ids are `uuid4` (`world.py:4896`) but are **minted once at live build
time and restored verbatim** on load (`from_snapshot` `id=str(d["id"])`,
`world.py:8255`) — never re-minted. Keying accretion order and every seeded draw
on `building.id` is therefore:

- **Stable within a run's lineage** — snapshot round-trip, replay, and
  fork-resume all restore the same ids → identical placement. This is precisely
  what the EM-155 fork tests (EM-288, EM-275) gate. ✅
- **Variable across independent fresh runs** — `uuid4` is per-run-random. This is
  the **pre-existing, tolerated** behavior: today's `assignBuildingLots`
  (`cityLayout.ts:1217`) already sorts by id, so placement is already
  per-run-random. **F1 introduces no new non-determinism.**

The byte-identical **golden test** makes placement reproducible by monkeypatching
`world_mod.uuid.uuid4` via the established `_det_uuid()` counter
(`test_zone_targeted_build.py:322-421`). **No seeded-building-id prerequisite is
required.**

## The accretion algorithm

All math in the **world frame (±32.5)** — the frame citygraph nodes and
`assignBuildingLots` output use. `anchor` = the world-frame city center `(0.0,
0.0)` in F1 (= logical `(500, 500)`; one implicit settlement). Every random draw is
`_seeded_unit(city_seed, f"{building_id}:{purpose}")` — the helper at
`citygraph.py:335`. `MIN_SPACING` is a logical-unit constant.

```
def place_all(buildings, anchor, city_seed) -> dict[id, (x, z)]:
    # Canonical order == creation order → append-only growth never moves existing.
    ordered = sorted(buildings, key=lambda b: (b.created_tick, b.id))
    placed: list[(id, x, z)] = []
    for i, b in enumerate(ordered):
        if i == 0:
            x, z = jitter(anchor, city_seed, b.id)      # first ~ anchor + tiny seeded jitter
        else:
            parent = pref_attach(placed, city_seed, b.id)   # seeded, weighted by local density
            ang    = _seeded_unit(city_seed, f"{b.id}:ang") * TAU
            dist   = MIN_SPACING * (1 + _seeded_unit(city_seed, f"{b.id}:dist"))
            cand   = parent + (cos ang, sin ang) * dist
            x, z   = resolve_overlap(cand, placed, city_seed, b.id)  # seeded spiral-out, capped
        placed.append((b.id, x, z))
    return {id: (x, z) for id, x, z in placed}
```

- **Canonical order `(created_tick, id)` == creation order.** A new build has the
  latest `created_tick` → sorts **last** → attaches to the existing set **without
  moving any existing building** (stable append-only growth — the city accretes,
  never rearranges).
- **`pref_attach` (the clumping mechanism).** Pick a parent among already-placed
  buildings with weight `1 + (neighbors within R)` — rich-get-richer, so dense
  spots pull more builds → **hamlets emerge**. Iterate over the **id-sorted
  `placed` list only** — never a `dict`/`set` (hash-order = non-determinism, R4).
  The weight exponent is a moderate default aesthetic knob (cheap to retune; the
  "too clumpy" lever).
- **`resolve_overlap`.** If `cand` is within `MIN_SPACING` of any placed building,
  nudge outward on a **seeded spiral**, **capped** at N iterations then accept
  (deterministic + terminating). Exact-coord stacking is thereby avoided; a
  choked-cluster near-overlap is "a finding, not a bug" (chaos ethos). No global
  density cap in F1 — the city may **sprawl past nominal bounds** (build-anywhere;
  camera follows) rather than hard-clamp into pile-ups.

**Build-time entry point.** On a build, `place_one(new_building, existing, anchor,
city_seed)` computes the new building's position from the current set (equivalent
to `place_all` because the new building sorts last) and **stores it**.

## Data model & code changes

### Backend (`engine/world.py`)

- **`Building.position: tuple[float, float] | None = None`** (world frame ±32.5).
  Serialize in `to_dict` **only when set** (`if self.position:`) — byte-identical
  to pre-F1 like `skin`/`zone_id` (`world.py:790,794`). Restore in
  `from_snapshot` when present, `None` when absent (pre-F1 snapshots).
- **Placement module** — `place_all` / `place_one` pure fns (new file, e.g.
  `engine/placement.py`, or a section of `world.py`; the plan decides). Used at
  two entry points: **build-time** (store the new building's position, at the
  mint site `world.py:4895-4910`) and **migration** (fill missing positions on
  load).
- **Migration (derive-on-load).** After restoring buildings, any building with
  `position is None` gets one via `place_all` over the **full** building set in
  `(created_tick, id)` order — treating already-positioned buildings as **fixed
  parents** (fill only the gaps, **never overwrite** a stored position). Because
  canonical order == creation order, derive-on-load == what the live incremental
  path produced (R3 equivalence). **Destroyed buildings keep their position and
  stay in the parent pool** (they are never popped — `world.py:4917-4919`).

### Frontend (`web/src/components/world3d/cityLayout.ts`, `types.ts`)

- **`types.ts`** — `Building.position?: [number, number]` (world frame ±32.5).
- **`cityLayout.ts`** — when `FREE_PLACEMENT_ENABLED` **and** a building has a
  `position`, render it **directly** (already world frame — same units as
  `assignBuildingLots` output, **no conversion**). Otherwise fall back to
  `assignBuildingLots` (`cityLayout.ts:1217`) **unchanged** → byte-identical when
  the flag is off or a building lacks a position.
- **Sever the tie.** Retire only the building→planar-face *placement consumption*
  (the EM-264 SA path). **Keep** `cityFaces`/`planarFaces` for **road** rendering.
  Wave P code stays on `main` behind its (off) flags.

## Byte-identical gate semantics (R2 — do not conflate)

- **Flag OFF ⇒ byte-identical to current `main`** (old grid). The existing
  `cityLayout.test.ts` golden is the oracle and is **never regenerated**.
- **Flag ON ⇒ a fresh golden**, self-consistent across live/replay/fork. F1
  **deliberately** moves buildings off the grid — the gate is *self-consistency*,
  **not** "F1 reproduces the old grid."

## Consumers to audit (R8)

Enumerate every reader of building placement and route each through the **correct
frame**; none may read stale lot coords. The 3D path needs no conversion (world
frame end-to-end); the **2D `map/WorldMap.tsx`** may need world→logical for its
minimap. Also: the inspector, `world3d/Traffic.tsx` / parked-cars, and landmark
placement. (Scoping task for the plan, not a blocker.)

## Non-risks (bounded for scope)

- **Free-scale / prompt-diet** — placement is pure compute at build time, no LLM;
  the default path needs zero map knowledge, so prompts do not grow.
- **Two coordinate frames** — F1 stays **entirely in the world frame** (backend
  accretion, storage, and render all ±32.5), so there are **zero** frame-crossings
  on the 3D path — the strongest possible guard against the EM-243 silent-kill
  class. Zero road interaction in F1.

## Testing

**Backend** (`backend/tests/test_free_placement_accretion.py`, new file) — golden
patches `uuid.uuid4` via the `_det_uuid()` pattern:

- Determinism: two runs (patched uuid) produce byte-identical positions.
- Append-only stability: adding a building does **not** move existing positions.
- Clumping: preferential attachment forms >1 cluster (hamlets), not a uniform grid.
- Overlap: `resolve_overlap` terminates and honors `MIN_SPACING` (no exact stack).
- **R3 equivalence:** derive-on-load over a position-less set == live incremental.
- Destroyed buildings retain position and remain accretion parents.
- Old-snapshot fallback: `position` absent ⇒ derived on load, no crash.
- Flag OFF ⇒ `to_dict` omits `position` ⇒ byte-identical snapshot.

**Frontend** (`web/src/components/world3d/cityLayout.f1.test.ts`, new file):

- Flag OFF ⇒ byte-identical to the existing `cityLayout.test.ts` oracle.
- Flag ON + `position` ⇒ renders the converted position (single conversion).
- Flag ON + no `position` ⇒ falls back to `assignBuildingLots`.

**Determinism (EM-155):** no existing golden regenerated; the flag-off path is
byte-identical; the flag-on golden is captured fresh with the `_det_uuid` patch,
proven identical across a fork/replay round-trip (add a teeth-test that
re-introduces id-order divergence, per the W29 pattern).

## Open questions from the overview — resolved

- **Frontend/backend split** → positions are **backend state**; frontend renders.
- **Organic-placement algorithm** → cluster accretion (above); byte-identical
  golden via canonical order + seeded draws + `_det_uuid` patch.
- **Migration** → store-primary; derive-on-load fills only missing positions.

## Out of scope (later slices)

- **F2 (EM-269)** — `Settlement` primitive + `found_settlement`; F1 ships **one
  implicit settlement** (the city center anchor).
- **F3 (EM-270)** — the optional `build(target=...)` deliberate-placement + map
  perception. F1 is the **default organic-spread path only**.
- **F4 (EM-271)** — formalizing roads-as-decoration beyond severing the placement
  tie (mostly falls out of F1).
- Settlement/region zoning, explicit multi-city stats/UI.

## Status

Design (2026-07-04). **Next:** user review → `writing-plans` (F1 implementation
plan) → orchestrator build.

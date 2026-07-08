# EM-268 (F1) — Free-Placement Organic Cluster-Accretion · Build Contract

> **Spec:** `docs/superpowers/specs/2026-07-04-free-placement-f1-organic-accretion-design.md`
> **Plan:** `docs/superpowers/plans/2026-07-04-free-placement-f1.md` (complete code, task-by-task)
> **Branch:** `build/free-placement-f1`
> **Supersedes** the Wave P (EM-264/265/266) building-*placement* path; the road
> engine (EM-239–248) is untouched and reused. Advisory/dormant behind a default-OFF
> flag until the user's visual sign-off (same gate as `ROAD_MESH_ENABLED`).

## 0. The law (non-negotiable acceptance bar)

1. **Byte-identical / additive (EM-155).** `Building.position` serializes in
   `to_dict` **only when set** (`if self.position:`) and restores in `from_snapshot`
   only when present (absent ⇒ `None`, never a crash). With `FREE_PLACEMENT_ENABLED`
   **off**, no build stores a position, migration no-ops, `to_dict` omits the key ⇒
   **byte-identical to current `main`.** The whole backend + frontend golden suites
   pass **unchanged** — no golden regenerated.
2. **World frame ±32.5 end-to-end.** `position` is world-frame (the frame citygraph
   nodes and `assignBuildingLots` output already use). **Zero logical↔world
   conversion on the 3D path.** Anchor = world `(0.0, 0.0)`.
3. **Determinism / replay / fork (EM-155).** Placement is a **pure fn** of
   `(building set, anchor, city_seed)`. Every random draw is
   `citygraph._seeded_unit(seed, key)`. Iterate **id-sorted lists only** — never a
   `dict`/`set` (hash-order = non-determinism). Positions round-trip through
   snapshot/replay/fork byte-identically. Golden reproducibility via the
   `_det_uuid()` uuid4 monkeypatch (`test_zone_targeted_build.py:322-421`).
4. **Append-only stability.** Canonical `(created_tick, id)` order == creation order
   ⇒ a new build sorts **last** and **never moves an existing building**.
5. **R3 equivalence.** Derive-on-load over a position-less set == what the live
   incremental path produced (guaranteed by canonical order). Already-positioned
   buildings are **fixed parents, never overwritten**; destroyed buildings keep their
   position and stay in the parent pool.

## 1. File ownership (strict — no shared-file edits across lanes)

| Lane | Owns (create/modify) | May read |
|---|---|---|
| **S — backend** | `backend/petridish/engine/world.py` (M), `backend/petridish/engine/placement.py` (C), `backend/petridish/agents/runtime.py` (M: add flag), `backend/tests/test_free_placement_position_field.py` (C), `…_accretion.py` (C), `…_build_time.py` (C), `…_migration.py` (C) | everything |
| **U — frontend** | `web/src/types/index.ts` (M), `web/src/components/world3d/cityLayout.ts` (M), `web/src/components/world3d/CozyWorld.tsx` (M), `web/src/components/world3d/cityLayout.f1.test.ts` (C), + any T6 consumer files under `web/src/components/map` / `web/src/inspector` | the wire shape in §2 |
| **QE** | `coordination/em268-qa-report.json` (C) | everything; runs suites; edits no source |

Lanes S and U own **disjoint file trees** (`backend/` vs `web/`) → they run **in
parallel**. U depends only on the **wire shape** (§2), fully specified below — it
does not wait for S. QE runs after both are green.

**Lead commits, not agents.** Implement agents WRITE FILES and RUN TESTS only.
They MUST NOT run `git` (no add/commit/checkout). The lead commits per lane after
the wave gate.

## 2. The shared contract — the wire shape (the only cross-lane coupling)

A building's position crosses the backend→frontend boundary as a **2-element
world-frame array**, serialized only when set:

```
# backend (Python)   Building.position: tuple[float, float] | None      # world ±32.5
# wire (JSON)        "position": [x, z]           # present only when set; omitted ⇒ pre-F1
# frontend (TS)      position?: [number, number]  # world ±32.5, rendered verbatim (NO conversion)
```

**Placement module public surface (Lane S produces; used at build-time + migration):**

```python
# backend/petridish/engine/placement.py
MIN_SPACING: float
def place_all(buildings, anchor: tuple[float,float], city_seed: int) -> dict[str, tuple[float,float]]
def place_one(building, all_buildings, anchor: tuple[float,float], city_seed: int) -> tuple[float,float]
# buildings items need .id: str and .created_tick: int. Canonical (created_tick, id) order.
```

**Flag (paired, both default False):**
- backend `agents.runtime.FREE_PLACEMENT_ENABLED = False` (beside `GRAPH_ZONES_ENABLED`, `runtime.py:961`)
- frontend `export const FREE_PLACEMENT_ENABLED = false` (beside `CARS_ENABLED`, `cityLayout.ts:635`)

**Frontend render entry point (Lane U produces):**

```typescript
export function resolveBuildingPositions(
  plan, buildings, placeCenters, forceFlag = false
): Map<string, { x: number; z: number }>
// flag off OR no position ⇒ === assignBuildingLots (byte-identical). Positioned
// buildings overridden with their world-frame position verbatim.
```

## 3. Grounded anchors (verified against current HEAD — use these, not the plan's approximate lines)

**Backend `world.py`:**
- `Building` dataclass **719**; fields `created_tick` (737), `skin` (754), `zone_id`
  (761). Add `position: tuple[float,float] | None = None` **after 761**.
- `to_dict` serialize-when-set: `skin` (790-791), `zone_id` (794-795). Add the
  `if self.position:` block **after 795**.
- `from_snapshot` building restore: loop `for d in state.get("buildings", [])` at
  **8251**, `Building(` ctor at **8254**, `zone_id=` at **8277**,
  `world.buildings[b.id] = b` at **8279**. Add `position=…` in the ctor **after 8277**;
  add the derive-on-load migration block **after 8279** (after the loop closes).
- Build mint + add: `id=f"bld_{str(uuid.uuid4())[:8]}"` at **4896**,
  `self.buildings[building.id] = building` at **4910** — this is the **only**
  `self.buildings[…] =` add site. Insert the build-time storage hook **after 4910**.
- `self.city_seed` at **1318** (default 1337).
- ⚠ **Build reflex is `action_propose_project(self, agent, name, kind, funds_required,
  function=None, place=None, zone_id=None)` (4813) — there is NO `propose_building`.**
  The `test_free_placement_build_time.py` `_build` helper in the plan MUST be adapted:
  ```python
  def _build(w):
      a = w.agents["a"]
      w.action_propose_project(a, name="Hall", kind="workshop", funds_required=0, place="plaza")
  ```
  The assertions in the plan (position set when flag on / None when off) are what matter.

**Backend `runtime.py`:** `GRAPH_ZONES_ENABLED = False` at **961** — add
`FREE_PLACEMENT_ENABLED = False` beside it.

**Frontend:**
- `web/src/types/index.ts`: `interface Building` at **170** (`skin?` 187, `zone_id?`
  195). Add `position?: [number, number]`.
- `web/src/components/world3d/cityLayout.ts`: `CARS_ENABLED = true` at **635**,
  `export function assignBuildingLots` at **1217**. Add the flag near 635, the wrapper
  after 1217.
- ⚠ `web/src/components/world3d/CozyWorld.tsx`: the **sole** production
  `assignBuildingLots` caller is at **541**:
  `const spotById = assignBuildingLots(cityPlan, lotInput, placeCenters);` (import at
  50). Swap to `resolveBuildingPositions(cityPlan, lotInput, placeCenters)`. (Plan
  said ~475-528; actual is 541.)

## 4. Task assignment

- **Lane S** executes plan Tasks 1→2→3→4 **in order** (they touch `world.py`
  sequentially; do not parallelize within the lane). Complete code is in the plan;
  apply the §3 anchor corrections. Run each task's targeted pytest, then the full
  backend suite (`.venv/bin/python -m pytest backend/tests -q`) at the end to prove
  flag-off byte-identity.
- **Lane U** executes plan Tasks 5→6. Run
  `/usr/local/bin/npx vitest run src/components/world3d/cityLayout.f1.test.ts
  src/components/world3d/cityLayout.test.ts` (the F1 file passes AND the existing
  oracle is unchanged), then `/usr/local/bin/npx tsc -b --force` (rc=0) from `web/`.
  For T6: grep for other building-*position* readers; if none (likely — CozyWorld:541
  was the only `assignBuildingLots` caller), record that as a comment and skip wiring.
- **QE** runs after S+U: full backend + full frontend suites + `tsc`, the
  byte-identical determinism audit (flag-off == main golden unchanged; flag-on fresh
  golden reproducible across a fork/replay round-trip with a teeth-test that
  re-introduces id-order divergence), writes `coordination/em268-qa-report.json` with
  `proceed` + blockers.

## 5. Gates

- **Wave gate (lead, inline):** backend `pytest -q` all pass; frontend `vitest run`
  all pass; `tsc -b --force` rc=0; `vite build` ✓. No golden regenerated.
- **QA gate (lead, inline):** QE `proceed=true`, 0 blockers. Every new behavior has a
  regression test; determinism proven end-to-end.
- **Circuit breaker:** 3 consecutive failures on the same target ⇒ stop and escalate.
- **Standing user gate (NOT in this build):** flip both `FREE_PLACEMENT_ENABLED` flags
  and watch a real accreted city render (the `ROAD_MESH_ENABLED`-style visual sign-off).

## 6. Toolchain (exact)

- Backend: `.venv/bin/python -m pytest <targets>` from repo root (no bare `python`).
- Frontend: `/usr/local/bin/npx vitest run <targets>` and
  `/usr/local/bin/npx tsc -b --force` from `web/` (nvm broken; never `tsc --noEmit`).

# EM-247 (S5a — procedural road meshing) — Build Results

**Status: ✅ CODE-COMPLETE on branch `feat/em247-procedural-road-meshing`. QA gate PASS (4/4 lenses clean, 0 blockers). Mesh path ships behind `ROAD_MESH_ENABLED` (default OFF) — the tile path is the byte-identical default; the VISUAL sign-off (flip the flag, eyeball a pentagon at 60fps) is the spec's explicitly-deferred human gate.**

## What shipped
`buildRoadMesh(graph, seed)` (`roadMeshData.ts`) — a **pure** generator turning the `CityGraph` into road geometry at **any angle**: each edge → a width-correct ribbon (`rotY=atan2(dz,dx)`, `length=hypot`), each node → an intersection patch (roundabout/plaza node kinds → ring/plaza, ready for S3b). Output is instance transforms per piece bucket. `<RoadMesh>` renders them as raw `InstancedMesh` per bucket + one toon material (a handful of draw calls). `ROAD_MESH_ENABLED` (default **false**) selects mesh vs the EM-239/243 tile path.

## Commits (on `feat/em247-procedural-road-meshing`)
| Commit | What |
|---|---|
| `aa6b873` | docs: the S5a plan |
| `dcec93b` | feat: procedural road meshing behind the flag |
| `79e9347` | fix: content-signature memo key (per-poll churn, pre-ship review) |

## Gates
| Gate | Baseline (EM-246) | Final | Result |
|---|---|---|---|
| Frontend `world3d` | 578 | **592** (+14) | ✅ 26 files |
| `tsc -b --force` | 0 | **0** | ✅ |

## Verification — adversarial (4 lenses) + QE gate: **PASS** (full, not PASS_WITH_ISSUES)
- **Flag-off byte-identical: CLEAN.** With the flag false, `drawEntries` short-circuits to the same `entries` reference, no `<RoadMesh>` mounts, `buildRoadMesh` is never called — the tile path is byte-identical; EM-239/243/244/246 goldens all hold.
- **Determinism + any-angle: CLEAN.** `buildRoadMesh` pure (no RNG/clock/state); the `-rotY` ribbon orientation was **numerically verified correct against the real three lib** (length axis aligns with edge direction, dot=1.0 across axis-aligned/diagonal/negative-coord edges — no mirror/rotation defect); no NaN; pentagon acceptance (10 ribbons, distinct non-axis-aligned angles).
- **Render-soundness + scope: CLEAN.** Mounts without throw; one InstancedMesh per non-empty bucket; the case-collision rename (`roadMeshData.ts`) leaves no dangling imports / no cycle; only the 6 intended frontend files changed.

The review's one MEDIUM (per-poll mesh rebuild on graph object identity) was **fixed** (content-signature key). Two LOWs deferred to the sign-off iteration (below).

## Deferred to the visual sign-off iteration (recorded, spec-sanctioned)
The spec explicitly defers mesh-path visual quality + the 60fps pentagon sign-off ("budget real iteration; keep the tile fallback until sign-off"). Not in this slice:
- Atlas UV packing, lane markings, crosswalks, pedestrian sidewalk surfaces.
- LOD (`<Detailed>`) + chunked culling for a grown/morphed city.
- Roundabout/plaza visual fidelity (incl. disposing the per-rebuild `RingGeometry`; heterogeneous-radius rings).
- Ribbon z-overlap at node centers (polygonOffset / trim) — a flag-ON visual nit.
- **The human visual sign-off itself:** flip `ROAD_MESH_ENABLED` on, confirm a pentagon/radial city renders cleanly at 60fps, then retire the tile path. (Browser automation was unavailable in this build.)

## Definition of Done
- [x] Implement (Workflow) — generator + component + flag, TDD
- [x] Wave gate green, 0 regressions (592 / tsc 0); flag OFF, tile path byte-identical
- [x] Adversarial verify (4 lenses, ALL clean) + QE gate PASS; MEDIUM fixed
- [x] Determinism + any-angle geometry proven (vs real three lib)
- [x] Mission manifest + this report
- [ ] **Visual sign-off (flip the flag, eyeball a pentagon at 60fps) — the user's deferred gate.** Unblocks retiring the tile path.

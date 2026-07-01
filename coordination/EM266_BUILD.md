# EM-266 (SC) — Zone-Targeted Emergent Building · Build Coordination

Spec: `docs/superpowers/specs/2026-06-29-agent-building-layout-sC-emergent-build-design.md`
Contract: `contracts/em266-build-contract.md` · Branch: `build/em266-emergent-build` · 2026-06-30

## Runtime
ultracode ON → Workflow mode. Design + contracts inline. The payoff slice: agents
TARGET a zone when they build and honor/ignore/**break** its voted rules — all succeed
(SC records, never enforces). Builds on merged SA + SB. Ships dormant behind the SA
(`GRAPH_LOTS_ENABLED`) + SB (`GRAPH_ZONES_ENABLED`) flags.

## Lanes (ownership in contract §1) — independent, parallel
- **Lane 1 — backend** (`world.py`, `runtime.py`): `Building.zone_id`, `action_propose_project`
  optional zone target (loose resolve, build always succeeds), `zone_violation` observation
  event, args threading + `nearby_zones` "target this zone" framing. Gated on `GRAPH_ZONES_ENABLED`.
- **Lane 2 — frontend** (`cityLayout.ts`, `CozyWorld.tsx`, `types`): `Building.zone_id`,
  `assignBuildingLots` honors `zone_id` (place in the zone's lots, overflow when over-cap),
  `CozyWorld` passes it. Gated on `GRAPH_LOTS_ENABLED` + `plan.zones`.
- **QE** — `coordination/em266-qa-report.json`.

## Mission skill manifest — EM-266
- [x] `brainstorming` — ✅ spec merged (#66).
- [x] `contract-author` (inline) — ✅ `contracts/em266-build-contract.md`.
- [x] Lane 1/2 implement (Workflow `em266-implement`) — ✅ done (crash interrupted the
  workflow's REPORT, not the work; recovered green + committed `e92d8ad`).
- [x] Wave gate (lead) — ✅ backend 1800 passed / 0 fail; frontend tsc clean, world3d 654 /
  3 pre-existing ROAD_MESH.
- [x] Adversarial verify (subagents — ultracode off) — ✅ QA PASS; **no law violation** (build
  always succeeds under real attack). 4 quality findings, all fixed (`1f69341`):
  - **MED dead wiring:** `CozyWorld`'s `useCityPlan` omitted `city_graph` → `plan.zones` never
    set → SA graph-lots AND SC zone-targeting never rendered live. Pass `city_graph` in
    (byte-identical when off). Also enables SA's live rendering.
  - LOW: over_cap counted `destroyed` buildings → filter to live.
  - LOW: perceived "N built" decoupled from `zone_id` → count by tag (feedback for honor/defy).
  - LOW: zone/location pad-pool collision → shared claim ledger.
- [x] `qe-agent` — ✅ `coordination/em266-qa-report.json`: PASS, `proceed=true`, 5/5/5/5, 0 blockers.
- N/A: nano-banana/ux-review/render-sanity/design-token-guard/deployment-checklist — no new
  UI chrome/imagery/styling; SC changes placement + adds an event behind the dormant flags.

## Outcome
**SC DONE** on `build/em266-emergent-build` (3 commits). Ships **dormant + byte-identical**
behind the SA (`GRAPH_LOTS_ENABLED`) + SB (`GRAPH_ZONES_ENABLED`) flags. Agents may target a
zone and honor/ignore/**break** its voted rules — all succeed; SC records (`zone_violation`)
but NEVER enforces. The dead-wiring fix means flipping the flags now actually renders builds
piling into their targeted zones (SA+SB+SC together). **Wave P (EM-264/265/266) complete.**

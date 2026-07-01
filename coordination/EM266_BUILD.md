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
- [ ] Lane 1/2 implement (Workflow `em266-implement`).
- [ ] Wave gate (lead) — pytest + tsc + vitest, goldens unchanged.
- [ ] Adversarial verify (Workflow `em266-verify`) — build-always-succeeds/honor-ignore-break,
  choke-core, over-cap overflow, zone_violation correctness, byte-identical/replay, flag-off dormancy.
- [ ] `qe-agent` — `coordination/em266-qa-report.json` (QA gate).
- N/A: nano-banana/ux-review/render-sanity/design-token-guard/deployment-checklist — no new
  UI chrome/imagery/styling; SC changes placement + adds an event behind the dormant flags.

## Gate sequence
Contract §6. Hard gates: build ALWAYS succeeds (no enforcement leak); byte-identical when
no zone_id / flags off; deterministic placement + violation record.

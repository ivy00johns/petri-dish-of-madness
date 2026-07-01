# EM-265 (SB) — Agent-Authored Zone Rules · Build Coordination

Spec: `docs/superpowers/specs/2026-06-29-agent-building-layout-sB-zone-rules-design.md`
Contract: `contracts/em265-build-contract.md` · Branch: `build/em265-zone-rules` · 2026-06-30

## Runtime
ultracode ON → Workflow mode. Design + contracts inline (this doc + the contract).
Implement + verify run as Workflow scripts. SB rides EM-244/245 governance; advisory
only (SC enforces). Builds on the merged SA `BuildZone`/`planarFaces`.

## Lanes (ownership in contract §1) — dependency: Lane 1 → (Lane 2 ‖ Lane 3)
- **Lane 1 — backend-core** (`citygraph.py`): ZoneRule + zone_rules serialization +
  the **Python planar-face port** (mirror hardened cityFaces.ts) + zone_id +
  apply_zone_rule + the cross-consistency fixture `contracts/em265-zone-id-fixture.json`.
  The keystone + the main risk (cross-language zone-id consistency).
- **Lane 2 — backend-gov** (`world.py`,`runtime.py`): wire `set_zone_rule` into
  propose/evaluate(0.7)/activate + no-renewal exclusion, emit `zone_rule_set`,
  morph-survival re-attach/drop, action gate, `nearby_zones` perception. Needs Lane 1.
- **Lane 3 — frontend** (`types`,`cityFaces`,`cityLayout`,`CityScape`): wire ZoneRule +
  zone_rules, attach rules to BuildZone by id, citySignature rules hash (content-key
  trap), tint/label by hint. Needs the fixture + wire shapes.
- **QE** — `coordination/em265-qa-report.json`.

## Mission skill manifest — EM-265
- [x] `brainstorming` — ✅ spec merged (#66).
- [x] `contract-author` (inline) — ✅ `contracts/em265-build-contract.md`.
- [x] Lane 1/2/3 implement agents (Workflow `em265-implement`) — ✅ done.
- [x] Wave gate (lead) — ✅ backend 1786 passed / 0 fail; frontend tsc clean,
  world3d 642 / 3 pre-existing ROAD_MESH; prompt golden byte-identical (flag off).
- [x] Adversarial verify (Workflow `em265-verify`) — ✅ QA PASS; **4 confirmed, 0
  refuted**, all fixed (2 rounds):
  - bootstrap (rd 1): perception gated on zone_rules-nonempty → chicken-and-egg →
    re-gated on `GRAPH_ZONES_ENABLED` (default off).
  - keystone §0.2 (rd 2): Python `round()` vs JS `Math.round` merge divergence →
    aligned to half-up + rounding-tie fixture pinned both sides.
  - TOCTOU orphan (rd 2): re-validate zone at activation → silent no-op if gone.
  - reconcile inversion (rd 2): two-pass KEEP-before-RE-POINT.
  - bootstrap take-2 (rd 2): exposed the `zone_id` handle in perception + e2e test.
- [x] `qe-agent` — ✅ `coordination/em265-qa-report.json`: PASS, `proceed=true`,
  contract 5 / security 5 / coverage 5 / regression 5, 0 blockers.

## Outcome
**SB DONE** on `build/em265-zone-rules` (5 commits). Ships **dormant + byte-identical**:
the zone-rule system is gated behind `GRAPH_ZONES_ENABLED` (backend, runtime.py) —
the pair of the frontend `GRAPH_LOTS_ENABLED`. Flip BOTH to activate agent-controlled
zoning (agents perceive zones → vote rules → rules tint the right block, cross-language
verified). Advisory only — SC (EM-266) enforces. No user visual gate (renders tints
under the SA flag). SC is unblocked.
- N/A: nano-banana/ux-review/render-sanity/design-token-guard/deployment-checklist —
  SB renders zone tints behind the existing GRAPH_LOTS_ENABLED flag (off); no new UI
  chrome/imagery/styling. Visual surfaces with SC / the SA flag sign-off.

## Gate sequence
Contract §6. Hard gates: byte-identical (zone_rules omitted when empty; pre-SB
snapshots unchanged) + cross-language zone-id consistency + content-keyed reactivity.

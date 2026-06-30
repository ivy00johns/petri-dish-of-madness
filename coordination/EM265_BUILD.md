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
- [ ] Lane 1/2/3 implement agents (Workflow `em265-implement`).
- [ ] Wave gate (lead) — pytest + tsc + vitest, goldens unchanged.
- [ ] Adversarial verify (Workflow `em265-verify`) — byte-identical/replay, cross-lang
  zone-id consistency, vote/threshold, morph-survival, content-key reactivity.
- [ ] `qe-agent` — `coordination/em265-qa-report.json` (QA gate).
- N/A: nano-banana/ux-review/render-sanity/design-token-guard/deployment-checklist —
  SB renders zone tints behind the existing GRAPH_LOTS_ENABLED flag (off); no new UI
  chrome/imagery/styling. Visual surfaces with SC / the SA flag sign-off.

## Gate sequence
Contract §6. Hard gates: byte-identical (zone_rules omitted when empty; pre-SB
snapshots unchanged) + cross-language zone-id consistency + content-keyed reactivity.

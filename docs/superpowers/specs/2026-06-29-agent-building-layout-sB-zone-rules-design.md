# Agent-Controlled Building Layout — SB: Agent-Authored Zone Rules

> **Parent:** `2026-06-29-agent-building-layout-overview-design.md`.
> **Depends on:** SA (`...-sA-graph-zones-design.md`) — `BuildZone` with a stable
> `id` and the empty `rules` hook. Reuses the EM-244/245 governance machinery:
> `action_propose_rule` → `_evaluate_rule` (0.7 supermajority) → `_on_rule_activated`
> + the no-renewal exclusion list (`engine/world.py`).
> **Ledger:** EM-265. **Status:** design (2026-06-29).

## 1. Goal

*"They can make rules for areas."* Give agents a vote-gated verb to author a
**zoning rule** on a buildable zone — a zoning hint (e.g. `residential` /
`market` / `civic` / `open`) and an optional density cap. Because a zone rule
constrains the shared city, it is **city policy → vote-gated**, riding the exact
governance path the road initiative used for demolish / car-policy / master-plan.

Rules are **advisory metadata** in SB — they render and they're perceivable, but
nothing enforces them. Acting on (or against) them is SC.

## 2. Non-goals (out of scope for SB)

- **No enforcement.** A rule does not stop or alter any build in SB. (SC is where
  agents honor/break it.)
- **No agent choice of where to build** (`build into zone X`) — that's SC.
- **No new geometry / assets / road changes.**
- **No new standing LLM calls** — proposing a rule is an option in the existing turn.

## 3. The verb: `propose_zone_rule`

- **Semantics:** an agent proposes a rule on a zone identified by its SA-stable
  `id`. The proposal enters the **existing town-hall vote** (`action_propose_rule`)
  and activates only on **≥ 0.7 supermajority** (`_evaluate_rule`), exactly like
  `ban_cars` / `demolish` / `adopt_master_plan`.
- **Rule shape:**

  ```python
  # engine/citygraph.py (or a small zoning module) — pure data on the graph
  @dataclass
  class ZoneRule:
      zone_id: str          # SA-stable id (sorted boundary node ids)
      hint: str             # 'residential' | 'market' | 'civic' | 'open'
      density_cap: int | None  # optional max buildings; None = no cap
  ```

- **Where rules live:** on the authoritative graph state, e.g.
  `CityGraph.zone_rules: list[ZoneRule]` (additive; absent ⇒ `[]` ⇒ pre-SB
  snapshots stay valid + byte-identical). Serialized in the snapshot, replayed
  from the event log.
- **Activation (`_on_rule_activated`):** append/replace the `ZoneRule` for that
  `zone_id`; emit a `zone_rule_set` event `{ zone_id, hint, density_cap, tick }`.
  Add the rule kind to the **no-renewal exclusion list** so a just-passed rule
  isn't immediately re-proposed (the EM-244/245 pattern).
- **Chaos by design:** a rule is *ratified by vote* but (in SC) *defiable by any
  individual.* SB only establishes the ratify half.

## 4. Stable zone identity across morphs

The hard part. A ratified rule must stick to *its* block when the graph mutates
(`build_road`, demolish, S3b master-plan morph).

- **Identity = SA's `id`** (sorted boundary node ids). When the same nodes still
  bound a face, the rule re-attaches.
- **When the bounding nodes change** (morph re-plats the block): match by closest
  centroid within a tolerance; if no zone matches, the rule is **dropped, not
  crashed** (a morph can legitimately destroy a zone — silent-drop of a *region*
  is forbidden by pillar 2, but a *rule* losing its zone is acceptable and logged).
- Tested explicitly (§7): propose a rule, morph the city, assert the rule follows
  the block or is cleanly dropped — never attached to the wrong block, never a crash.

## 5. Perception (prompt)

Agents must see zones and any rules to (in SC) honor or break them. Extend the
SA-era layout perception with a compact, **district-scoped**, size-bounded block
(prompt-diet law — never the whole graph):

```
Nearby zones: Market Quarter (market, ~3 lots, cap 4 — 2 built).
  Riverside (residential, ~5 lots, no cap — empty).
  Center (open, ~2 lots — unzoned).
```

- Local district only; hard line cap; omit when nothing nearby.
- Counts + hint + cap only — no full polygon dump.
- This is the scaffolding SC's "target a zone" choice reads from.

## 6. Frontend — render the rules

- **Tint / label per `hint`:** a zone with a ratified rule renders a zoning tint
  and an optional label (reuse the EM-188 sparse-label discipline).
- **Content-keyed signature (the thrice-shipped bug).** Fold a **rules hash**
  (zone_id + hint + cap, sorted) into `citySignature` so a ratified rule renders
  **live, no reload.** This is the exact failure that shipped green-but-broken in
  EM-243/244/247 — a dedicated reactivity test is mandatory.
- **Default-off / no-rules path stays byte-identical** (no rules ⇒ no tint delta).

## 7. Components, determinism & testing

- **Backend — `engine/citygraph.py`:** `ZoneRule`, `apply_zone_rule(graph, rule)`,
  serialization; pure + deterministic ids.
- **Backend — `engine/world.py`:** wire `propose_zone_rule` into `action_propose_rule`
  / `_evaluate_rule` / `_on_rule_activated` + the no-renewal exclusion list; emit
  `zone_rule_set`; the morph-survival re-attach/drop logic.
- **Backend — agent action surface:** register `propose_zone_rule` as a turn action;
  assemble the `nearby_zones` perception block.
- **Frontend — `types/index.ts`:** add `zone_rules?` to `CityGraph`, `ZoneRule`
  type. **`cityLayout.ts`/`cityFaces.ts`:** attach rules to `BuildZone.rules` by id.
  **`CityScape.tsx`:** rules hash in `citySignature`; zone tint/label render.
- **Tests:**
  - propose → ≥0.7 vote → rule activates; below threshold → no rule.
  - no-renewal: a just-passed rule isn't immediately re-proposed.
  - **morph-survival:** rule follows its block across a master-plan morph, or is
    cleanly dropped if its zone is gone — never mis-attached, never a crash.
  - snapshot / replay / fork round-trips `zone_rules` byte-identically (EM-155);
    pre-SB snapshot (no `zone_rules`) loads + renders unchanged.
  - **render reactivity:** ratified rule changes `citySignature` ⇒ tint appears
    live; no-op poll ⇒ no churn.
  - perception present, district-scoped, size-bounded; omitted when empty.

**Acceptance:** an agent can propose a zoning rule, the town ratifies it by
supermajority, the zone tints live in the view, the rule survives replay/fork and
follows its block across a morph (or drops cleanly) — and nothing yet *enforces*
it.

## 8. Risks & open questions

- **Zone identity across morphs** is the main risk (§4). Mitigation: id-by-boundary
  first, centroid-tolerance fallback, clean-drop last; pinned by tests.
- **Prompt bloat:** keep `nearby_zones` minimal + district-scoped; measure vs the
  8K lane.
- **Open:** exact hint vocabulary + whether `density_cap` is absolute or per-area;
  set during build. Whether a zone can carry multiple stacked rules or one
  (recommend one rule per zone, last-ratified wins — simpler).

## 9. What SC needs from SB (handoff)

- A ratified, perceivable, rendered `ZoneRule` on a stable zone id — SC reads it to
  decide honor/break and to render violations.
- The `nearby_zones` perception scaffolding to extend with "target this zone."
- The morph-survival contract so SC's per-zone build counts track the right block.

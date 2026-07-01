# EM-265 (SB) — Agent-Authored Zone Rules · Build Contract

> **Spec:** `docs/superpowers/specs/2026-06-29-agent-building-layout-sB-zone-rules-design.md`
> **Depends on:** SA (EM-264, merged) — `BuildZone` with a stable `id` + the empty
> `rules` hook; the hardened `planarFaces` in `web/src/components/world3d/cityFaces.ts`.
> **Rides:** EM-244/245 governance (`action_propose_rule` → `_evaluate_rule` 0.7 →
> `_on_rule_activated` + the no-renewal exclusion lists), exactly like
> `set_car_policy` / `adopt_master_plan`.
> **Branch:** `build/em265-zone-rules`. Advisory only — NOTHING enforces a rule (that's SC).

## 0. The law (non-negotiable acceptance bar)

1. **Byte-identical / additive (EM-155).** `CityGraph.zone_rules` is additive and
   **serialized ONLY when non-empty** (omit the key when `[]`). Pre-SB snapshots
   (no `zone_rules`) load + render + replay **byte-identical**. The whole backend
   + frontend golden suites pass unchanged when no rule has ever been ratified.
2. **Cross-language zone-id consistency.** A zone's `id` computed by the **Python**
   `planar_faces` (backend) MUST equal the `id` computed by the **TS** `planarFaces`
   (frontend) for the same graph — both are `"|".join(sorted(boundary_node_ids))`.
   A ratified rule's `zone_id` (backend) must match a rendered `BuildZone.id`
   (frontend) or it won't tint the right block. **Pinned by a shared-fixture test.**
3. **Determinism / replay / fork (EM-155).** `zone_rules` round-trips through
   snapshot/replay/fork byte-identically. Zone-id + face enumeration are pure
   (sorted walk, no clock/random), mirroring SA.
4. **Advisory only.** A ratified rule changes NO build, NO placement, NO agent
   outcome in SB. It is metadata that renders + is perceivable. (SC acts on it.)
5. **Content-keyed reactivity (the thrice-shipped bug — EM-243/244/247).** A
   ratified rule must render **live, no reload**: fold a rules hash into
   `citySignature`. A dedicated reactivity test is **mandatory**.

## 1. File ownership (strict — no shared-file edits across lanes)

| Lane | Owns (create/modify) | May read |
|---|---|---|
| **1 — backend-core** | `backend/petridish/engine/citygraph.py` (MODIFY), `backend/tests/test_citygraph_zones.py` (CREATE) | everything |
| **2 — backend-gov** | `backend/petridish/engine/world.py` (MODIFY), `backend/petridish/agents/runtime.py` (MODIFY), `backend/tests/test_zone_rules.py` (CREATE) | `citygraph.py` |
| **3 — frontend** | `web/src/types/index.ts` (MODIFY), `web/src/components/world3d/cityFaces.ts` (MODIFY), `web/src/components/world3d/cityLayout.ts` (MODIFY), `web/src/components/world3d/CityScape.tsx` (MODIFY), the matching `*.test.ts(x)` (MODIFY/CREATE) | the wire shapes below |
| **QE** | `coordination/em265-qa-report.json` (CREATE) | everything; runs tests; edits no source |

Lane 2 depends on Lane 1's real code (runs after it). Lane 3 depends only on the
**wire shapes** in §2 (runs in parallel with Lane 1). The cross-consistency
fixture (§2) is Lane 1's output that Lane 3 + QE verify against.

## 2. The shared contract — `ZoneRule`, zone id, hint vocabulary

**Hint vocabulary (frozen for SB):** `'residential' | 'market' | 'civic' | 'open'`.
**Zone id:** `"|".join(sorted(boundary_node_ids))` — IDENTICAL formula both sides.
**One rule per zone:** last ratified wins (replace, never stack).

```python
# backend — engine/citygraph.py
ZONE_HINTS = frozenset({"residential", "market", "civic", "open"})

@dataclass
class ZoneRule:
    zone_id: str
    hint: str                 # ∈ ZONE_HINTS
    density_cap: int | None    # absolute max buildings; None = no cap; >= 0
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d) -> "ZoneRule": ...

# CityGraph gains (additive):
#   zone_rules: list[ZoneRule] = field(default_factory=list)
#   to_dict: include "zone_rules": [...] ONLY when the list is non-empty (omit when [])
#   from_dict: zone_rules = [ZoneRule.from_dict(z) for z in d.get("zone_rules", [])]

def planar_faces(graph: CityGraph) -> list[Face]: ...   # Python port of cityFaces.ts
def zone_id_for(boundary_node_ids: list[str]) -> str:    # "|".join(sorted(ids))
def apply_zone_rule(graph: CityGraph, rule: ZoneRule) -> None:  # replace-by-zone_id, pure
```

```ts
// frontend — types/index.ts  (wire shape — snake_case, matches backend JSON)
export interface ZoneRule {
  zone_id: string;
  hint: 'residential' | 'market' | 'civic' | 'open';
  density_cap: number | null;
}
// CityGraph gains:  zone_rules?: ZoneRule[];   // additive, absent ⇒ no rules
```

**Frontend ZoneRule REPLACES SA's stub** (`{zoneId, hint: CityZone, densityCap}` →
the wire shape above). SA never populated `rules`, so there is no data migration —
just update `cityFaces.ts`'s `ZoneRule` + `BuildZone.rules` type to the wire shape.

**Python planar-face port (Lane 1 keystone):** mirror the HARDENED
`web/src/components/world3d/cityFaces.ts` exactly — sort nodes/edges by id;
half-edge / next-edge-by-angle walk; drop the outer face PER-CYCLE by winding sign
(positive area kept, NOT max |area|); sanitize a working copy first (merge
coincident nodes onto a 1e-6 lattice, split collinear-overlapping edges at interior
nodes, distance tie-break equal angles, whole-graph `[]` backstop on a residual
tie); never throw; never drop an enclosed region. Same coords (`node.x`, `node.z`),
same edge endpoints (`a`/`b`). **Cross-consistency fixture:** Lane 1 emits (or a
test asserts) that for `classic_grid`, `master_plan("pentagon")`, and
`master_plan("radial")` the Python zone-id SET equals the TS zone-id SET (a checked-in
fixture JSON the frontend test also reads). This is law §0.2 — pin it hard.

## 3. Lane 2 — governance wiring (`world.py` + `runtime.py`)

The verb is **`propose_rule(effect="set_zone_rule")`** — clones the
`set_car_policy` / `adopt_master_plan` one-shot, no-renewal, per-target shape.

**`world.py action_propose_rule`** (mirror `set_car_policy`, ~line 3786):
- `valid_effects += "set_zone_rule"`.
- Args: `zone_id` (on `target`), `hint`, `density_cap` (reuse/extend the kwargs).
- Payload build + validation: `hint ∈ ZONE_HINTS`; `density_cap` is `None` or an
  int `>= 0`; `zone_id` must be a **current** zone (in `{zone_id_for(f.boundary)
  for f in planar_faces(self.city_graph)}`) — reject an unknown zone (like a
  demolish of an absent building). `payload = {"zone_id", "hint", "density_cap"}`.
- Duplicate-open guard: **scoped per `zone_id`** (mirror demolish-per-target — two
  distinct zones may have open votes; the SAME zone may not be double-proposed).
- No-renewal: add `"set_zone_rule"` to the one-shot exclusion lists (the
  `("name_town", "demolish", … "adopt_master_plan")` tuples at ~3874 AND ~3805's
  `_active_rule` skip) — a one-shot act per zone, never "renews".

**`world.py _evaluate_rule`** (~4347): add `"set_zone_rule"` to the **0.7
supermajority** effect tuple (structural city policy → demolish-grade bar).

**`world.py _on_rule_activated`** (~3968): on a passing `set_zone_rule`:
`rule.applied = True`; `apply_zone_rule(self.city_graph, ZoneRule(zone_id, hint,
density_cap))`; park a `zone_rule_set` event `{zone_id, hint, density_cap, tick,
proposal_id}` in `pending_spawn_events` (same outbox name_town/demolish use).

**`world.py step_master_plan_morph`** (~1340) — **morph-survival** (§4 of the spec):
after the morph mutates `self.city_graph`, reconcile `zone_rules`: for each rule,
(a) if its `zone_id` still equals a current face id → keep; (b) elif a current
face's centroid is within tolerance of the rule's original face centroid →
re-point the rule to that face's id; (c) else **drop** the rule (a morph can
legitimately destroy a zone — a *rule* losing its zone is acceptable + logged;
this is NOT the forbidden region-drop). Deterministic; emit a `zone_rule_dropped`
event when (c) fires. Pure fn of (graph, zone_rules).

**`runtime.py`** — the agent surface:
- Action gate (~1948, mirror `set_car_policy`): `set_zone_rule` needs
  `args.zone_id` (a real current zone), `args.hint ∈ ZONE_HINTS`, `args.density_cap`
  `None`/int≥0 — reject early so the gate AGREES with `action_propose_rule`. Add
  `"set_zone_rule"` to the proposable-effects set (~1892).
- **`build_nearby_layout`** (~925) — extend with the **`nearby_zones`** block
  (spec §5): district-scoped, hard line cap, omitted when empty. Per zone:
  `<name> (<hint or "unzoned">, ~<N> lots[, cap <C> — <B> built])`. Counts + hint +
  cap only — NO full polygon dump. Names derive deterministically (seeded, like
  street names). This is the scaffold SC's "target a zone" reads from.

## 4. Lane 3 — frontend render + attach

- **`cityFaces.ts`/`cityLayout.ts`:** attach `graph.zone_rules` to `BuildZone.rules`
  by matching `rule.zone_id === zone.id` (in `buildZonesFromFaces` or the
  `computeCityPlan` graph-lots branch). Absent/empty ⇒ `rules: []` (SA behavior,
  byte-identical).
- **`CityScape.tsx`:**
  - **`citySignature`** — fold a **rules hash**: `(zone_id + ':' + hint + ':' +
    (density_cap ?? '')) sorted, joined`. No rules ⇒ `''` ⇒ byte-identical + no
    churn. This is law §0.5 — a ratified rule must re-render live.
  - Zone **tint by hint** (map `residential/market/civic/open` to the existing
    zone-tint vocabulary) + an OPTIONAL sparse **label** (reuse EM-188 sparse-label
    discipline — main zones, not every block). Render gated on `GRAPH_LOTS_ENABLED`
    + a real graph (zones only exist on the graph-lots path); **no rules ⇒ no tint
    delta ⇒ byte-identical**.

## 5. Toolchain (project memory — DO NOT deviate)

- Backend: `.venv/bin/python -m pytest backend/tests/...` (no `python` on PATH).
- Frontend: `cd web && /usr/local/bin/npx vitest run …` ; typecheck `… tsc -b --force`.
- `node`/`npx`: `/usr/local/bin/...` (nvm shim broken).

## 6. Testing & gate sequence

**Lane 1 (`test_citygraph_zones.py`):** ZoneRule to/from_dict; zone_rules serialized
only when non-empty (empty ⇒ key absent ⇒ byte-identical); apply_zone_rule replaces
by zone_id; planar_faces matches SA's matrix (grid→25, pentagon→6/sectors,
stub/disconnected/concave/empty, determinism); **cross-consistency fixture** (Python
zone ids == the TS fixture for grid/pentagon/radial).

**Lane 2 (`test_zone_rules.py`):** propose set_zone_rule → ≥0.7 vote → rule activates
+ `zone_rule_set` emitted; below threshold → no rule; unknown zone_id rejected;
duplicate-open guard per zone; no-renewal (a just-passed rule isn't re-proposed);
**morph-survival** (rule follows its block across a master-plan morph, or drops
cleanly if its zone is gone — never mis-attached, never a crash); snapshot/replay/fork
round-trips `zone_rules` byte-identically; pre-SB snapshot (no zone_rules) loads
unchanged; `nearby_zones` perception present, district-scoped, size-bounded, omitted
when empty.

**Lane 3 (frontend tests):** rules attach to `BuildZone.rules` by id; **render
reactivity** (a ratified rule changes `citySignature` ⇒ tint appears live; no-op poll
⇒ no churn); no-rules path byte-identical; zone-id fixture matches the backend.

**Gate sequence (orchestrator):** Lane 1 self-verify → Lane 2 (against real Lane 1)
self-verify ‖ Lane 3 self-verify → **wave gate** (lead, inline: full `pytest` +
`tsc -b --force` + `vitest`, ALL green, goldens unchanged) → **adversarial verify**
(QE + lenses: byte-identical/replay, cross-language zone-id consistency, governance
vote/threshold, morph-survival re-attach/drop, content-key reactivity) → **QA gate**
(`coordination/em265-qa-report.json`, `proceed=true`, no CRITICAL, contract ≥3,
security ≥3). No new user visual gate (SB renders tints; SC is the next slice).

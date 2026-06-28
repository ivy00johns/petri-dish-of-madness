# EM-244 (S3a) — Vote-Gated Demolish + Car-Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver two headline agent-collective city controls — **tear down a road** and **ban cars / all-sidewalks** — through the existing town-hall vote (ratify at ~70%), axis-aligned, on the S1/S2 tile renderer.

**Architecture:** Both are new **rule effects** on the unified `action_propose_rule` machinery (the same path as EM-183 `relocate_center` and EM-219 `demolish`): propose at the governance place → `action_vote` → `_evaluate_rule` ratifies at 0.7 → `_on_rule_activated` applies. The applies are pure `CityGraph` mutations (`apply_demolish_road` removes an edge; `apply_car_policy` sets `car_policy` on the graph or an edge) emitting `road_demolished` / `car_policy_set` system events. The graph rides the existing snapshot (EM-239) so replay/fork reproduce it. Frontend: `car_policy` (dormant since S1) becomes live — ambient traffic (EM-169) + parked cars (EM-176) stop on `pedestrian` edges, which render with a surface tint; demolish needs **no relocation code** (the frontend `assignBuildingLots` already re-derives + reassigns deterministically when lots shrink).

**Tech Stack:** Python 3.12 backend (pytest), TypeScript/R3F frontend (Vitest). EM-155 determinism.

## Global Constraints

- **Collective, not individual.** Both verbs are **proposals** ratified by the town-hall vote at a **0.7 supermajority** (the existing `_evaluate_rule` bar for `demolish`/`relocate_center`/`amend_constitution`). No individual teardown. Proposals require being at the governance place (the existing `governance_here` gate on `action_propose_rule`).
- **Axis-aligned only.** S3a reuses the S1/S2 tile renderer — no new geometry (that's S3b/EM-245, gated on S5a/EM-247). Car-policy is a **render/behavior flag**, not geometry.
- **Determinism / EM-155.** `apply_demolish_road` and `apply_car_policy` are pure functions of the graph (id-keyed, no RNG/clock). The grown/edited graph is serialized in `to_snapshot` (`world.py:7158`) / restored in `from_snapshot` (`world.py:7562`); proposal+vote state already rides the rules snapshot. Same snapshot + ordered ratifications ⇒ identical graph across live/replay/fork.
- **Scope (S3a car-policy):** `policy ∈ {cars, pedestrian, mixed}`; `scope ∈ {city, street}` fully supported (**city** = the headline "ban cars + all sidewalks"; **street** = a single edge). **`district` scope is DEFERRED** — the graph has no edge→district mapping; a `district` proposal is rejected with a clear reason. (Honest deferral, recorded; revisit when edges carry district tags.)
- **Demolish cascade:** removing an edge re-derives fewer lots on the frontend; `assignBuildingLots` reassigns buildings deterministically (round-robin + `slotLayout` ring fallback). **No backend relocation code** in S3a (explicit relocation is S3b/§4.3).
- **Toolchain:** backend `.venv/bin/python -m pytest <path> -q`; frontend `cd web && /usr/local/bin/npx vitest run <path>`; typecheck `cd web && /usr/local/bin/npx tsc -b --force`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/petridish/engine/citygraph.py` | Pure `apply_demolish_road`, `apply_car_policy` (+ `edge_for_scope` helper) | 1 |
| `backend/tests/test_citygraph.py` | Tests for the pure ops | 1 |
| `backend/petridish/engine/world.py` | `valid_effects` += 2; propose-validation; `_on_rule_activated` apply branches; `_evaluate_rule` supermajority set | 2 |
| `backend/tests/test_layout_governance.py` (new) | propose→vote→ratify→apply for both effects; determinism/snapshot | 2,5 |
| `backend/petridish/agents/runtime.py` | front-gate effects set + `propose_rule` schema; `nearby_layout` += car-policy + active layout proposal | 3 |
| `web/src/types/index.ts` | widen `car_policy` unions (edge + graph) | 4 |
| `web/src/components/world3d/cityLayout.ts` | thread `car_policy` into `computeStreets`/`emitCurbLife`; pedestrian surface tint | 4 |
| `web/src/components/world3d/Traffic.tsx` + `trafficLayout.ts` | gate ambient cars on `pedestrian` | 4 |
| `web/src/components/world3d/*.test.ts(x)` | car-policy gating + pedestrian-surface tests | 4 |

---

### Task 1: Pure graph ops — `apply_demolish_road`, `apply_car_policy`

**Files:**
- Modify: `backend/petridish/engine/citygraph.py` (append after the EM-243 ops)
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: `CityGraph`, `CityEdge`, `_parse_node` (EM-243).
- Produces:
  - `apply_demolish_road(graph: CityGraph, edge_id: str) -> tuple[bool, str, dict | None]` (removes the edge; removes a now-orphaned endpoint node; `info = {edge_id, removed_node_ids}`)
  - `apply_car_policy(graph: CityGraph, scope: str, policy: str, target: str | None = None) -> tuple[bool, str, dict | None]` (`scope ∈ {city, street}`; sets `graph.car_policy` or one edge's `car_policy`; `info = {scope, policy, edge_id?}`)
  - `CAR_POLICIES: frozenset = frozenset({"cars", "pedestrian", "mixed"})`

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_citygraph.py`:

```python
from petridish.engine.citygraph import apply_demolish_road, apply_car_policy, CAR_POLICIES


def test_demolish_road_removes_edge_and_orphaned_node():
    g = classic_grid(1337)
    # build a dead-end stub so its far node is orphan-removable on demolish
    apply_build_road(g, "n:12:2", "east")  # adds n:17:2 + e:n:12:2->n:17:2
    n0, e0 = len(g.nodes), len(g.edges)
    ok, reason, info = apply_demolish_road(g, "e:n:12:2->n:17:2")
    assert ok, reason
    assert info["edge_id"] == "e:n:12:2->n:17:2"
    assert "n:17:2" in info["removed_node_ids"]      # the stub's far node had no other edge
    assert len(g.edges) == e0 - 1 and len(g.nodes) == n0 - 1
    assert not any(e.id == "e:n:12:2->n:17:2" for e in g.edges)


def test_demolish_road_keeps_still-connected_nodes():
    g = classic_grid(1337)
    # an interior edge: both endpoints keep other edges, so no node is removed
    ok, reason, info = apply_demolish_road(g, "e:n:7:2->n:12:2")
    assert ok, reason
    assert info["removed_node_ids"] == []
    assert any(n.id == "n:7:2" for n in g.nodes) and any(n.id == "n:12:2" for n in g.nodes)


def test_demolish_road_rejects_unknown_edge():
    g = classic_grid(1337)
    ok, reason, info = apply_demolish_road(g, "e:nope->nope")
    assert not ok and info is None and "no such road" in reason


def test_car_policy_city_sets_graph_default():
    g = classic_grid(1337)
    ok, reason, info = apply_car_policy(g, "city", "pedestrian")
    assert ok and g.car_policy == "pedestrian" and info["scope"] == "city"


def test_car_policy_street_sets_one_edge():
    g = classic_grid(1337)
    ok, reason, info = apply_car_policy(g, "street", "pedestrian", "e:n:7:2->n:12:2")
    assert ok and info["edge_id"] == "e:n:7:2->n:12:2"
    edge = next(e for e in g.edges if e.id == "e:n:7:2->n:12:2")
    assert edge.car_policy == "pedestrian"


def test_car_policy_rejects_bad_policy_scope_and_target():
    g = classic_grid(1337)
    assert not apply_car_policy(g, "city", "flying")[0]
    assert not apply_car_policy(g, "district", "pedestrian")[0]   # deferred
    assert not apply_car_policy(g, "street", "pedestrian", "e:nope")[0]


def test_demolish_road_is_pure_deterministic():
    a, b = classic_grid(1337), classic_grid(1337)
    apply_demolish_road(a, "e:n:7:2->n:12:2"); apply_demolish_road(b, "e:n:7:2->n:12:2")
    apply_car_policy(a, "city", "pedestrian"); apply_car_policy(b, "city", "pedestrian")
    assert a.to_dict() == b.to_dict()
```

> NOTE: rename `test_demolish_road_keeps_still-connected_nodes` to a valid identifier (`test_demolish_road_keeps_still_connected_nodes`) when pasting — the hyphen above is a typo.

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_demolish_road'`.

- [ ] **Step 3: Implement the pure ops**

Append to `backend/petridish/engine/citygraph.py`:

```python
# ── EM-244 (S3a): vote-gated demolish + car-policy (pure graph ops) ────────────
CAR_POLICIES: frozenset[str] = frozenset({"cars", "pedestrian", "mixed"})
CAR_SCOPES: frozenset[str] = frozenset({"city", "street"})  # 'district' deferred (no edge->district map)


def apply_demolish_road(graph: CityGraph, edge_id: str) -> tuple[bool, str, dict | None]:
    """Remove the edge `edge_id`; also remove either endpoint node that is left with
    NO remaining edges (a freed dead-end stub). Pure + deterministic. Returns
    (ok, reason, info); info = {edge_id, removed_node_ids (sorted)}."""
    edge = next((e for e in graph.edges if e.id == edge_id), None)
    if edge is None:
        return False, f"no such road to tear down ({edge_id})", None
    a, b = edge.a, edge.b
    graph.edges = [e for e in graph.edges if e.id != edge_id]
    still = {nid for e in graph.edges for nid in (e.a, e.b)}
    removed = sorted(nid for nid in (a, b) if nid not in still)
    if removed:
        graph.nodes = [n for n in graph.nodes if n.id not in removed]
    return True, "ok", {"edge_id": edge_id, "removed_node_ids": removed}


def apply_car_policy(
    graph: CityGraph, scope: str, policy: str, target: str | None = None,
) -> tuple[bool, str, dict | None]:
    """Set the car policy. scope='city' sets graph.car_policy; scope='street' sets
    one edge's car_policy (target=edge id). 'district' is deferred. Pure."""
    if policy not in CAR_POLICIES:
        return False, f"car policy must be one of {sorted(CAR_POLICIES)} (got {policy!r})", None
    if scope == "city":
        graph.car_policy = policy
        return True, "ok", {"scope": "city", "policy": policy}
    if scope == "street":
        edge = next((e for e in graph.edges if e.id == target), None)
        if edge is None:
            return False, f"no such street to set policy on ({target})", None
        edge.car_policy = policy
        return True, "ok", {"scope": "street", "policy": policy, "edge_id": target}
    return False, f"car-policy scope must be 'city' or 'street' (got {scope!r}; 'district' not yet supported)", None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py
git commit -m "feat(EM-244): pure apply_demolish_road + apply_car_policy graph ops (S3a)"
```

---

### Task 2: Two new rule effects in the governance machinery

Add `demolish_road` and `set_car_policy` as rule effects on the unified `action_propose_rule` path — mirroring the EM-219 `demolish` effect exactly.

**Files:**
- Modify: `backend/petridish/engine/world.py` — `valid_effects` (`~3554`); a propose-validation block (after the `demolish` block `~3582`); two apply branches in `_on_rule_activated` (after the `demolish` branch `~3844-3853`); the supermajority tuple in `_evaluate_rule` (`~4172`); import the new citygraph ops.
- Test: `backend/tests/test_layout_governance.py` (new)

**Interfaces:**
- Consumes: `apply_demolish_road`, `apply_car_policy`, `CAR_POLICIES`, `CAR_SCOPES` (Task 1); `RuleState`, `action_propose_rule`, `action_vote`, `_on_rule_activated`, `_evaluate_rule`, `self.pending_spawn_events`, `self.city_graph`.
- Produces: ratifiable `demolish_road` (payload `{target: edge_id}`) and `set_car_policy` (payload `{scope, policy, target?}`) effects emitting `road_demolished` / `car_policy_set` system events.

- [ ] **Step 1: Write the failing governance test**

Create `backend/tests/test_layout_governance.py`:

```python
import pytest
from petridish.config.loader import load_config
from petridish.engine.world import World


def _gov_world():
    """A world with agents at the governance place so propose_rule is allowed."""
    cfg = load_config()
    # mirror the construction used in test_build_road.py / existing world tests
    # (load_config().world + places + agents); place all agents at a governance place.
    w = World(params=cfg.world, places=..., agents=...)   # FILL from the real ctor (grep existing tests)
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    return w


def _ratify(w, rule):
    # cast yes votes from every living agent until the rule activates
    for a in w.agents.values():
        ok, reason, status = w.action_vote(a, rule.id, True)
    return rule


def test_propose_and_ratify_demolish_road_removes_edge():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    edge_id = "e:n:7:2->n:12:2"
    assert any(e.id == edge_id for e in w.city_graph.edges)
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "tear down 7th & 12th", target=edge_id)
    assert ok, reason
    _ratify(w, rule)
    assert rule.effect == "demolish_road"
    w._on_rule_activated(rule)  # if not auto-applied by the vote that crossed threshold
    assert not any(e.id == edge_id for e in w.city_graph.edges)


def test_propose_and_ratify_car_policy_city_bans_cars():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "set_car_policy", "ban cars citywide",
                                             target=None)
    # scope/policy ride explicit kwargs or the payload — see Step 3 for how the runtime
    # passes them; this test calls the world method with them on the proposal.
    # (Adjust to the real signature once Step 3 lands.)
    assert ok, reason


def test_demolish_road_requires_real_edge():
    w = _gov_world()
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "demolish_road", "x", target="e:nope->nope")
    assert not ok and "road" in reason.lower()


def test_car_policy_survives_snapshot_round_trip():
    w = _gov_world()
    from petridish.engine.citygraph import apply_car_policy
    apply_car_policy(w.city_graph, "city", "pedestrian")
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.car_policy == "pedestrian"
```

> NOTE: this test file has two FILL points — the `World(...)` ctor and the exact `set_car_policy` param passing. Grep `backend/tests/test_build_road.py` (EM-243) for the real `World` constructor and `backend/tests/` for an existing `action_propose_rule` + `action_vote` test (e.g. the EM-183 relocate_center or EM-219 demolish tests) and mirror them verbatim. Do NOT invent signatures.

Run: `.venv/bin/python -m pytest backend/tests/test_layout_governance.py -q`
Expected: FAIL — `invalid effect: 'demolish_road'`.

- [ ] **Step 2: Add the effects to `valid_effects`**

In `world.py` `action_propose_rule` (`~3554`):
```python
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "ban_extortion", "ban_vandalism",
                         "name_town", "demolish", "promote_image", "trial",
                         "amend_constitution", "relocate_center",
                         "demolish_road", "set_car_policy"}  # EM-244 (S3a)
```

- [ ] **Step 3: Add the propose-validation blocks**

After the `demolish` validation block (`~3589`), add (the `effect`, `target`, and — for car-policy — `scope`/`policy` arrive as `action_propose_rule` kwargs; extend the signature with `scope: str | None = None, policy: str | None = None`):

```python
        # EM-244 (S3a) — demolish_road carries the TARGET edge id (like demolish's
        # building target). A teardown of an absent road is meaningless.
        if effect == "demolish_road":
            target = str(target or "").strip()
            if not any(e.id == target for e in self.city_graph.edges):
                return False, f"demolish_road requires a real road id (got {target!r})", None
            payload = {"target": target}
        # EM-244 (S3a) — set_car_policy carries {scope, policy, target?}. city = the
        # headline ban-cars; street = one edge (target). 'district' is deferred.
        if effect == "set_car_policy":
            from .citygraph import CAR_POLICIES, CAR_SCOPES
            scope = str(scope or "city").strip()
            policy = str(policy or "").strip()
            if policy not in CAR_POLICIES:
                return False, f"car policy must be one of {sorted(CAR_POLICIES)}", None
            if scope not in CAR_SCOPES:
                return False, f"car-policy scope must be 'city' or 'street' ('district' not yet supported)", None
            if scope == "street":
                target = str(target or "").strip()
                if not any(e.id == target for e in self.city_graph.edges):
                    return False, f"street car-policy requires a real road id (got {target!r})", None
            payload = {"scope": scope, "policy": policy, "target": (target or None)}
```

- [ ] **Step 4: Add the apply branches in `_on_rule_activated`**

After the `demolish` branch (`~3853`), import the ops at the top of `world.py` (extend the existing citygraph import) and add:
```python
        # EM-244 (S3a) — demolish_road: a passing vote tears down the target edge
        # (+ any freed dead-end node). road_demolished is parked in the same outbox
        # demolish/promote_image use (drained by the loop's _flush_spawn_events).
        if rule.effect == "demolish_road":
            rule.applied = True
            edge_id = (rule.payload or {}).get("target")
            ok, _reason, info = apply_demolish_road(self.city_graph, edge_id)
            if ok:
                self.pending_spawn_events.append({
                    "kind": "road_demolished", "actor_id": "system", "actor_type": "system",
                    "text": "🚧 By vote, a road is torn down.",
                    "payload": {"proposal_id": rule.id, **info},
                })
            return
        # EM-244 (S3a) — set_car_policy: a passing vote sets the city or a street's
        # car policy. car_policy_set parked in the same outbox.
        if rule.effect == "set_car_policy":
            rule.applied = True
            p = rule.payload or {}
            ok, _reason, info = apply_car_policy(
                self.city_graph, p.get("scope", "city"), p.get("policy", "cars"), p.get("target"))
            if ok:
                self.pending_spawn_events.append({
                    "kind": "car_policy_set", "actor_id": "system", "actor_type": "system",
                    "text": f"🚦 By vote, {p.get('scope')} car policy → {p.get('policy')}.",
                    "payload": {"proposal_id": rule.id, **info},
                })
            return
```
Import (extend the existing `from .citygraph import ...` near the top of world.py):
```python
from .citygraph import (CityGraph, classic_grid, apply_build_road, nearest_node,
                        apply_demolish_road, apply_car_policy)
```

- [ ] **Step 5: Add the effects to the 0.7-supermajority set in `_evaluate_rule`**

In `_evaluate_rule` (`~4172`):
```python
        if rule.effect in ("demolish", "amend_constitution", "relocate_center",
                           "demolish_road", "set_car_policy"):  # EM-244 (S3a) — irreversible/structural → 0.7
```
(Both fall into the fixed `else: frac = 0.7` branch, like demolish/relocate_center.)

- [ ] **Step 6: Run the governance tests + full backend suite**

Run: `.venv/bin/python -m pytest backend/tests/test_layout_governance.py backend/tests/test_citygraph.py -q` then `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions vs the 1638 baseline.

- [ ] **Step 7: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_layout_governance.py
git commit -m "feat(EM-244): demolish_road + set_car_policy rule effects (vote-gated, 0.7) (S3a)"
```

---

### Task 3: Action surface (schema + front-gate) + perception

**Files:**
- Modify: `backend/petridish/agents/runtime.py` — the propose-rule front-gate effects set (`~1884`); the `propose_rule`/effect schema; `build_nearby_layout` (EM-243, `~924`) to add current car-policy + any active layout proposal.
- Test: `backend/tests/test_layout_governance.py`

**Interfaces:**
- Consumes: the new effects (Task 2); `action_propose_rule` extended signature (`scope`, `policy`).
- Produces: `demolish_road`/`set_car_policy` reachable as `propose_rule` effects from a turn; `nearby_layout` reports car-policy + active proposal.

- [ ] **Step 1: Add the effects to the runtime front-gate set + thread scope/policy**

In `runtime.py` propose_rule handling (`~1884`), add `"demolish_road", "set_car_policy"` to the effects set, and pass `scope`/`policy`/`target` from `args` through to `world.action_propose_rule` (grep the existing `relocate_center` arg-passing at `~1891` and mirror — it reads `args.get("target")`; add `args.get("scope")`, `args.get("policy")`).

- [ ] **Step 2: Extend `build_nearby_layout` with car-policy + active proposal**

In `build_nearby_layout` (`runtime.py ~924`, EM-243), append the current city car-policy and any open layout proposal (one extra clause, diet-safe):
```python
    line += f" Cars: {world.city_graph.car_policy}."
    # EM-244 (S3a): surface an open layout vote so agents can vote (district-scoped, one clause).
    open_layout = next((r for r in world.rules.values()
                        if getattr(r, "status", "") == "proposed"
                        and getattr(r, "effect", "") in ("demolish_road", "set_car_policy")), None)
    if open_layout is not None:
        line += f" Open vote: {open_layout.effect} (vote yes/no)."
```
> Grep the real `world.rules` accessor + `RuleState.status` field name and mirror exactly (the snippet assumes `world.rules: dict[id, RuleState]` with `.status == "proposed"`). Adjust to the real names.

- [ ] **Step 3: Add a reachability test + run**

Add to `test_layout_governance.py` a test that `_assemble_context` (or the menu) offers the new effects when at governance, and that `build_nearby_layout` includes `Cars:`. Run the file + the relevant runtime tests.

Run: `.venv/bin/python -m pytest backend/tests/test_layout_governance.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/petridish/agents/runtime.py backend/tests/test_layout_governance.py
git commit -m "feat(EM-244): propose_rule schema/gate for demolish_road+set_car_policy + perception (S3a)"
```

---

### Task 4: Frontend — car-policy becomes live (traffic + parked cars + surface)

`car_policy` is dormant since S1. Make it live: ambient traffic + parked cars stop on `pedestrian`, and pedestrian roads render with a surface tint.

**Files:**
- Modify: `web/src/types/index.ts` (widen `CityGraphEdge.car_policy` + `CityGraph.car_policy` to `'cars' | 'pedestrian' | 'mixed'` / `+ 'inherit'` for the edge)
- Modify: `web/src/components/world3d/cityLayout.ts` (`computeStreets`/`computeCityPlan` carry per-street policy; `emitCurbLife` suppresses parked cars on pedestrian; pedestrian road tint)
- Modify: `web/src/components/world3d/Traffic.tsx` + `trafficLayout.ts` (gate ambient cars on pedestrian)
- Test: `web/src/components/world3d/cityLayout.test.ts`, `trafficLayout.test.ts` (or the existing test files)

**Interfaces:**
- Consumes: `world.city_graph` (already threaded into `computeCityPlan`, EM-239); `CityGraphEdge.car_policy`, `CityGraph.car_policy`.
- Produces: cars absent on `pedestrian` edges; pedestrian road tiles tinted; the effective per-edge policy = `edge.car_policy === 'inherit' ? graph.car_policy : edge.car_policy`.

- [ ] **Step 1: Widen the types**

In `web/src/types/index.ts`:
```typescript
export interface CityGraphEdge {
  id: string; a: string; b: string;
  road_class: 'street';
  car_policy: 'inherit' | 'cars' | 'pedestrian' | 'mixed'; // EM-244 (S3a)
}
export interface CityGraph {
  version: number; seed: number;
  car_policy: 'cars' | 'pedestrian' | 'mixed'; // EM-244 (S3a)
  nodes: CityGraphNode[]; edges: CityGraphEdge[];
}
```

- [ ] **Step 2: Write failing tests (effective-policy + traffic gate + tint)**

Add a `pedestrianPolicyFor(graph, edge)` helper test + a `computeTraffic` test that a `city: pedestrian` graph yields zero cars, and a `cityLayout` test that pedestrian roads emit the tinted variant. (Mirror the EM-239/EM-243 graph-fixture idiom in each file.) Run them red.

- [ ] **Step 3: Implement**

- Add `export function pedestrianPolicyFor(graph, edge): 'cars'|'pedestrian'|'mixed'` (`edge.car_policy === 'inherit' ? graph.car_policy : edge.car_policy`) in `cityLayout.ts`.
- `emitCurbLife` (`cityLayout.ts ~695`): pass `city_graph`; skip the parked-car emit when the adjacent edge resolves to `pedestrian`.
- `Traffic.tsx`/`trafficLayout.ts computeTraffic`: thread `city_graph`; skip a street whose edges resolve to `pedestrian` (city-scope `pedestrian` ⇒ all cars off — the headline).
- Pedestrian road tint: emit pedestrian road tiles to a tinted material variant (mirror the `EmptyLotPads`/`PAD_COLOR` `toonMaterial` idiom; add `PEDESTRIAN_ROAD_COLOR`).

- [ ] **Step 4: Run frontend tests + typecheck**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d` then `/usr/local/bin/npx tsc -b --force`
Expected: PASS + exit 0, 0 regressions (the no-policy / `cars` default path stays byte-identical — EM-239/EM-243 goldens hold).

- [ ] **Step 5: Commit**

```bash
git add web/src/types/index.ts web/src/components/world3d/
git commit -m "feat(EM-244): car_policy live — traffic + parked cars stop on pedestrian; surface tint (S3a)"
```

---

### Task 5: Determinism / replay / acceptance

**Files:**
- Test: `backend/tests/test_layout_governance.py`

- [ ] **Step 1: Acceptance tests**

Add: a full propose→ratify→apply for `demolish_road` and `set_car_policy` whose resulting `city_graph` survives `to_snapshot`/`from_snapshot` byte-identical; a replay test (two worlds, same ordered proposals+votes ⇒ identical `city_graph.to_dict()`); confirm a `pedestrian` city policy is restored on load.

- [ ] **Step 2: Full backend suite (regression)**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions vs 1638.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_layout_governance.py
git commit -m "test(EM-244): determinism/replay/snapshot acceptance for S3a governance effects"
```

---

## Self-Review

**1. Spec coverage (§3 S3a):**
- §3a.1 `demolish` (propose → ~70% → remove edge/building; cascade; event; determinism) → Task 1 (`apply_demolish_road`) + Task 2 (effect, 0.7 gate, `road_demolished`); building demolish-by-vote already exists (effect `demolish`); cascade rides frontend re-derivation (recorded). ✅
- §3a.2 `pedestrianize`/`ban_cars` (propose scope/policy → set graph/edge `car_policy`; traffic + parked cars stop; surface variant; event) → Task 1 (`apply_car_policy`) + Task 2 (`set_car_policy`, `car_policy_set`) + Task 4 (live traffic/parked/tint). `district` deferred (recorded). ✅
- §2 shared scaffolding (proposal verbs via existing vote at ~70%; events; perception) → Tasks 2, 3. ✅
- §6 testing/determinism → Tasks 1, 2, 5. ✅
- S3b (master plans) → OUT (EM-245, gated on EM-247). ✅

**2. Placeholder scan:** The two FILL points (Task 2 test `World(...)` ctor + the `action_propose_rule` test idiom; Task 3 `world.rules`/`RuleState.status` names) are explicit "grep the real pattern and mirror" instructions — the surrounding code is exact. The `test_demolish_road_keeps_still-connected_nodes` hyphen typo is flagged for rename. No TBD/"handle errors". ✅

**3. Type consistency:** `apply_demolish_road(graph, edge_id) -> (ok, reason, info{edge_id, removed_node_ids})`; `apply_car_policy(graph, scope, policy, target=None) -> (ok, reason, info)`; effects `demolish_road`/`set_car_policy` consistent across valid_effects, propose-validation, `_on_rule_activated`, `_evaluate_rule`, runtime gate, schema; events `road_demolished`/`car_policy_set`; frontend `pedestrianPolicyFor(graph, edge)` + widened unions. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-em244-vote-gated-demolish-carpolicy.md`. Built via **/orchestrator ultracode** (Workflow mode) per the session goal: design/contracts inline (this plan); implement + verify as workflows. Backend-heavy (Tasks 1–3, 5) + a frontend slice (Task 4). `district` car-policy scope and explicit demolish relocation are honestly deferred (recorded), keeping S3a shippable on the tile renderer.

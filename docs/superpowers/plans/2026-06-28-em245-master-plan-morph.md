# EM-245 (S3b) — Master Plans / City Morph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the town **vote a whole city topology** (pentagon / radial / ring / grid) and watch the city **morph** toward it over ticks — the final agent city-layout control.

**Architecture:** `master_plan(kind, params, seed)` (pure, in `citygraph.py`) generates a target `CityGraph`; `diff_graphs(current, target)` computes the node/edge add/remove set; a per-tick `World.step_master_plan_morph()` applies `MORPH_EDGES_PER_TICK` ops (adds before removes, deterministic seeded order) toward the target, emitting `road_built`/`road_demolished`, until convergence. Adoption is a vote-gated rule effect `adopt_master_plan` on the EM-244 `propose_rule`/`_evaluate_rule`/`_on_rule_activated` machinery (ratify at 0.7, **one active plan at a time**). The active plan is stored as `{kind, params, seed}` on World (target re-derived each tick → light snapshot; the morph is a pure function of `(stored plan, current graph)` so replay/fork reproduce it byte-for-byte). The geometric generators also complete **EM-246's templates** — `template("pentagon"/"radial"/"ring", seed)` now routes to `master_plan` instead of the grid fallback. The geometric result renders through **EM-247's mesh** (so the geometric *visual* rides the `ROAD_MESH_ENABLED` sign-off); building relocation rides the frontend `assignBuildingLots` re-derivation (per EM-244 — no backend relocation code).

**Tech Stack:** Python 3.12 backend (pytest). Frontend: **no new code** (EM-243 live-render + EM-247 mesh show the morph). EM-155 determinism.

## Global Constraints

- **Collective + 0.7.** `adopt_master_plan` is a `propose_rule` effect ratified at the 0.7 supermajority (the demolish/relocate_center/EM-244 bar). **One active master plan at a time** — propose is rejected while a morph is active.
- **Determinism / EM-155.** `master_plan`, `diff_graphs`, and the morph schedule are pure functions of `(kind, params, seed)` + the current graph — no RNG/clock/mutable state (ordering uses the `_seeded_unit` hash from EM-246). The active plan `{kind, params, seed}` rides `to_snapshot`/`from_snapshot`; the target is re-derived each tick. Same snapshot + tick sequence ⇒ identical morph across live/replay/fork.
- **Morph safety.** Each tick applies up to `MORPH_EDGES_PER_TICK` ops, **adds before removes**, so the graph never transiently drops below the target's edge set. Morph edge-removal is a raw graph op (NOT the EM-244 `apply_demolish_road` one-road-floor — the target guarantees ≥1 edge; the floor is for *individual* agent demolish only).
- **Geometric node ids.** Geometric plans use their own deterministic id scheme (e.g. `n:pent:0`, `n:pent:c`) — node positions are off the tile lattice. `diff_graphs` matches by **id** (a grid→pentagon morph is a full swap-over-ticks; proximity-preservation to reduce churn is a recorded refinement). EM-247's `buildRoadMesh` reads node `x,z` (not ids), so any id scheme renders.
- **Renders through EM-247.** Non-axis-aligned geometry renders correctly only with `ROAD_MESH_ENABLED` on (the user's deferred visual sign-off). The control logic + backend ship now; the geometric *visual* is gated on that flag.
- **Relocation rides the frontend.** Buildings re-assign to lots via `assignBuildingLots` as the graph morphs (per EM-244's finding). No backend relocation code; `building_relocated` is deferred (recorded).
- **Toolchain:** `.venv/bin/python -m pytest <path> -q`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/petridish/engine/citygraph.py` | `master_plan()` generators (pentagon/radial/ring/grid) + `diff_graphs()` | 1 |
| `backend/tests/test_citygraph.py` | generator + diff determinism/shape tests | 1 |
| `backend/petridish/engine/world.py` | `master_plan` state + `step_master_plan_morph()` + snapshot; `template()` geometric wiring | 2,4 |
| `backend/petridish/engine/loop.py` | per-tick morph step hook (~loop.py:627, beside `expire_miracles`) | 2 |
| `backend/tests/test_master_plan.py` (new) | morph engine + adopt effect + determinism/snapshot | 2,3,5 |
| `backend/petridish/engine/world.py` + `agents/runtime.py` | `adopt_master_plan` rule effect (mirrors EM-244 `demolish_road`) + front-gate/schema | 3 |

---

### Task 1: `master_plan()` generators + `diff_graphs()` (pure)

**Files:**
- Modify: `backend/petridish/engine/citygraph.py` (append after the EM-246 `template` block)
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: `CityGraph`, `CityNode`, `CityEdge`, `classic_grid`, `_ordered_edge`, `_seeded_unit` (EM-246), `tile_center`.
- Produces:
  - `MASTER_PLAN_KINDS: frozenset = frozenset({"pentagon", "radial", "ring", "grid"})`
  - `master_plan(kind: str, params: dict | None, seed: int) -> CityGraph`
  - `GraphDiff = {"add_nodes": list[CityNode], "add_edges": list[CityEdge], "remove_node_ids": list[str], "remove_edge_ids": list[str]}`
  - `diff_graphs(current: CityGraph, target: CityGraph) -> GraphDiff` (by id; deterministic order)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_citygraph.py`:

```python
from petridish.engine.citygraph import master_plan, diff_graphs, MASTER_PLAN_KINDS
import math


def test_master_plan_grid_is_classic_grid():
    assert [e.id for e in master_plan("grid", None, 1337).edges] == [e.id for e in classic_grid(1337).edges]


def test_master_plan_pentagon_has_perimeter_and_spokes():
    g = master_plan("pentagon", None, 1337)
    assert any(n.id == "n:pent:c" for n in g.nodes)            # center
    assert sum(1 for n in g.nodes if n.id.startswith("n:pent:")) == 6   # 5 perimeter + center
    assert len(g.edges) == 10                                   # 5 perimeter + 5 spokes
    # perimeter nodes sit on a circle (equal radius from center)
    c = next(n for n in g.nodes if n.id == "n:pent:c")
    radii = [math.hypot(n.x - c.x, n.z - c.z) for n in g.nodes if n.id != "n:pent:c"]
    assert max(radii) - min(radii) < 1e-6


def test_master_plan_radial_and_ring_nonempty_deterministic():
    for kind in ("radial", "ring"):
        a = master_plan(kind, None, 1337)
        b = master_plan(kind, None, 1337)
        assert len(a.edges) > 0 and a.to_dict() == b.to_dict()


def test_diff_grid_to_pentagon_is_full_swap():
    cur = classic_grid(1337)
    tgt = master_plan("pentagon", None, 1337)
    d = diff_graphs(cur, tgt)
    # ids disjoint ⇒ add every target edge, remove every current edge
    assert {e.id for e in d["add_edges"]} == {e.id for e in tgt.edges}
    assert set(d["remove_edge_ids"]) == {e.id for e in cur.edges}


def test_diff_same_graph_is_empty():
    g = classic_grid(1337)
    d = diff_graphs(g, master_plan("grid", None, 1337))
    assert d["add_edges"] == [] and d["remove_edge_ids"] == []


def test_diff_is_deterministic_ordered():
    cur, tgt = classic_grid(1337), master_plan("pentagon", None, 1337)
    assert diff_graphs(cur, tgt) == diff_graphs(cur, tgt)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: FAIL — `cannot import name 'master_plan'`.

- [ ] **Step 3: Implement the generators + diff**

Append to `citygraph.py`:

```python
import math

# EM-245 (S3b): parametric master-plan generators. Pure fn of (kind, params, seed).
# Geometric kinds use their OWN deterministic id scheme (positions are off the tile
# lattice); EM-247's buildRoadMesh reads x,z so any ids render. grid reuses classic_grid.
MASTER_PLAN_KINDS: frozenset[str] = frozenset({"pentagon", "radial", "ring", "grid"})
_PLAN_RADIUS = 26.0   # world units (within the 9x9 envelope ~ +-32)


def _ring_plan(prefix: str, seed: int, sides: int, radius: float,
               with_center: bool, with_ring: bool) -> CityGraph:
    """A perimeter polygon of `sides` nodes on a circle + optional center + spokes."""
    nodes: list[CityNode] = []
    edges: list[CityEdge] = []
    pts: list[str] = []
    for k in range(sides):
        ang = (k / sides) * 2 * math.pi
        nid = f"n:{prefix}:{k}"
        nodes.append(CityNode(id=nid, x=radius * math.cos(ang), z=radius * math.sin(ang)))
        pts.append(nid)
    if with_ring:
        for k in range(sides):
            a, b = pts[k], pts[(k + 1) % sides]
            eid, ea, eb = _ordered_edge_geom(a, b)
            edges.append(CityEdge(id=eid, a=ea, b=eb))
    if with_center:
        cid = f"n:{prefix}:c"
        nodes.append(CityNode(id=cid, x=0.0, z=0.0, kind="roundabout"))
        for k, p in enumerate(pts):
            eid, ea, eb = _ordered_edge_geom(p, cid)
            edges.append(CityEdge(id=eid, a=ea, b=eb))
    return CityGraph(seed=int(seed), nodes=nodes, edges=edges)


def _ordered_edge_geom(id_a: str, id_b: str) -> tuple[str, str, str]:
    """Edge id for geometric (non-lattice) node ids: order lexicographically for a
    stable canonical id (the lattice _ordered_edge parses n:i:j, which geom ids aren't)."""
    a, b = sorted([id_a, id_b])
    return f"e:{a}->{b}", a, b


def master_plan(kind: str, params: dict | None, seed: int) -> CityGraph:
    """Target CityGraph for a master plan. Pure fn of (kind, params, seed).
    Unknown kind ⇒ classic_grid (safe fallback). `template` records the kind."""
    p = params or {}
    radius = float(p.get("radius", _PLAN_RADIUS))
    if kind == "grid":
        return classic_grid(seed)
    if kind == "pentagon":
        g = _ring_plan("pent", seed, int(p.get("sides", 5)), radius, True, True)
    elif kind == "radial":
        # two concentric rings + spokes to a roundabout center
        outer = _ring_plan("radO", seed, int(p.get("spokes", 8)), radius, True, True)
        inner = _ring_plan("radI", seed, int(p.get("spokes", 8)), radius * 0.5, False, True)
        g = CityGraph(seed=int(seed), nodes=outer.nodes + inner.nodes, edges=outer.edges + inner.edges)
    elif kind == "ring":
        g = _ring_plan("ring", seed, int(p.get("sides", 8)), radius, False, True)
    else:
        return classic_grid(seed)
    g.template = kind
    return g


def diff_graphs(current: CityGraph, target: CityGraph) -> dict:
    """Node/edge add+remove sets to morph `current` toward `target`, matched by id
    (a geometric target's ids are disjoint from the grid ⇒ full swap). Deterministic
    order (target order for adds, current order for removes)."""
    cur_node_ids = {n.id for n in current.nodes}
    cur_edge_ids = {e.id for e in current.edges}
    tgt_node_ids = {n.id for n in target.nodes}
    tgt_edge_ids = {e.id for e in target.edges}
    return {
        "add_nodes": [n for n in target.nodes if n.id not in cur_node_ids],
        "add_edges": [e for e in target.edges if e.id not in cur_edge_ids],
        "remove_node_ids": [n.id for n in current.nodes if n.id not in tgt_node_ids],
        "remove_edge_ids": [e.id for e in current.edges if e.id not in tgt_edge_ids],
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py
git commit -m "feat(EM-245): master_plan generators (pentagon/radial/ring/grid) + diff_graphs (S3b)"
```

---

### Task 2: The morph engine — `step_master_plan_morph()` + per-tick hook + snapshot

**Files:**
- Modify: `backend/petridish/engine/world.py` (the `master_plan` state field near `city_graph` init ~1303; `step_master_plan_morph()`; snapshot key in `to_snapshot` ~7158 + restore in `from_snapshot` ~7562; import `master_plan, diff_graphs`)
- Modify: `backend/petridish/engine/loop.py` (call the step in the per-tick block ~627, beside `expire_miracles`)
- Test: `backend/tests/test_master_plan.py` (new)

**Interfaces:**
- Consumes: `master_plan`, `diff_graphs` (Task 1); `_seeded_unit` (EM-246); `self.city_graph`, `self.tick`.
- Produces:
  - `self.master_plan: dict | None` (`{"kind", "params", "seed"}` while a morph is active, else None)
  - `World.step_master_plan_morph(self) -> list[dict]` (applies ≤ `MORPH_EDGES_PER_TICK` ops/call; emits `road_built`/`road_demolished`; emits `master_plan_complete` + clears when converged; `[]` when no active plan)
  - `MORPH_EDGES_PER_TICK = 4` (module const in `world.py`; tune vs a live run)

- [ ] **Step 1: Write the failing morph test**

Create `backend/tests/test_master_plan.py`:

```python
import pytest
from petridish.config.loader import load_config
from petridish.engine.world import World, AgentState, PlaceState
from petridish.engine.citygraph import master_plan, diff_graphs


def _world():
    cfg = load_config()
    places = [PlaceState(id=p.id, name=p.name, x=p.x, y=p.y, kind=p.kind, description=p.description,
                         district=p.district, neighborhood_id=p.neighborhood_id, zone_kind=p.zone_kind)
              for p in cfg.places]
    agents = [AgentState(id=f"agent_{a.name.lower()}", name=a.name, personality=a.personality,
                         profile=a.profile, location=a.location, energy=cfg.world.starting_energy,
                         credits=cfg.world.starting_credits) for a in cfg.agents]
    return World(params=cfg.world, places=places, agents=agents)


def test_morph_converges_to_target_over_ticks():
    w = _world()
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    events = []
    for _ in range(200):                       # bounded; converges well before
        evts = w.step_master_plan_morph()
        events += evts
        if w.master_plan is None:
            break
    assert w.master_plan is None              # converged + cleared
    target = master_plan("pentagon", {}, w.city_seed)
    d = diff_graphs(w.city_graph, target)
    assert d["add_edges"] == [] and d["remove_edge_ids"] == []   # graph == target
    assert any(e["kind"] == "master_plan_complete" for e in events)
    assert any(e["kind"] == "road_built" for e in events)


def test_morph_step_is_bounded_per_tick():
    w = _world()
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    from petridish.engine.world import MORPH_EDGES_PER_TICK
    evts = w.step_master_plan_morph()
    edge_ops = [e for e in evts if e["kind"] in ("road_built", "road_demolished")]
    assert 0 < len(edge_ops) <= MORPH_EDGES_PER_TICK


def test_no_active_plan_is_noop():
    w = _world()
    assert w.master_plan is None
    assert w.step_master_plan_morph() == []


def test_morph_is_deterministic_and_snapshot_safe():
    def run():
        w = _world()
        w.master_plan = {"kind": "radial", "params": {}, "seed": w.city_seed}
        for _ in range(8):
            w.step_master_plan_morph()
        return w
    a, b = run(), run()
    assert a.city_graph.to_dict() == b.city_graph.to_dict()
    assert a.master_plan == b.master_plan
    # mid-morph state survives a snapshot round-trip
    w2 = World.from_snapshot(a.to_snapshot())
    assert w2.master_plan == a.master_plan
    assert w2.city_graph.to_dict() == a.city_graph.to_dict()
```

Run: `.venv/bin/python -m pytest backend/tests/test_master_plan.py -q`
Expected: FAIL — `World` has no `master_plan` / `step_master_plan_morph`.

- [ ] **Step 2: Add the state + morph step**

In `world.py`: extend the citygraph import (`from .citygraph import ..., master_plan, diff_graphs`); add `MORPH_EDGES_PER_TICK = 4` (module const); initialize `self.master_plan: dict | None = None` near the `city_graph` init (~1303); add the method:

```python
    def step_master_plan_morph(self) -> list[dict]:
        """EM-245 (S3b) — advance an active master-plan morph by up to
        MORPH_EDGES_PER_TICK ops toward the target (adds before removes, seeded
        order), mutating self.city_graph. Emits road_built/road_demolished; on
        convergence clears self.master_plan + emits master_plan_complete. Pure fn
        of (self.master_plan, self.city_graph) → replay/fork reproduce it."""
        plan = self.master_plan
        if not plan:
            return []
        from .citygraph import _seeded_unit, CityNode, CityEdge
        target = master_plan(plan["kind"], plan.get("params"), int(plan["seed"]))
        d = diff_graphs(self.city_graph, target)
        # converged?
        if not d["add_edges"] and not d["remove_edge_ids"]:
            self.master_plan = None
            return [{"kind": "master_plan_complete", "actor_id": "system", "actor_type": "system",
                     "text": f"🏙 The {plan['kind']} master plan is complete.",
                     "payload": {"kind": plan["kind"]}}]
        events: list[dict] = []
        budget = MORPH_EDGES_PER_TICK
        # ADDS first (never shrink below target mid-morph). Seeded-stable order.
        tgt_node = {n.id: n for n in target.nodes}
        for e in sorted(d["add_edges"], key=lambda e: _seeded_unit(int(plan["seed"]), f"morph:add:{e.id}")):
            if budget <= 0:
                break
            for nid in (e.a, e.b):                       # ensure endpoint nodes exist
                if not any(n.id == nid for n in self.city_graph.nodes) and nid in tgt_node:
                    tn = tgt_node[nid]
                    self.city_graph.nodes.append(CityNode(id=tn.id, x=tn.x, z=tn.z, kind=tn.kind))
            self.city_graph.edges.append(CityEdge(id=e.id, a=e.a, b=e.b,
                                                  road_class=e.road_class, car_policy=e.car_policy))
            events.append({"kind": "road_built", "actor_id": "system", "actor_type": "system",
                           "text": "🛣 A new road takes shape (master plan).",
                           "payload": {"edge_id": e.id, "morph": plan["kind"]}})
            budget -= 1
        # then REMOVES (raw — the morph target guarantees validity; bypasses the
        # EM-244 individual one-road-floor).
        if budget > 0:
            rm = sorted(d["remove_edge_ids"], key=lambda eid: _seeded_unit(int(plan["seed"]), f"morph:rm:{eid}"))[:budget]
            rm_set = set(rm)
            self.city_graph.edges = [e for e in self.city_graph.edges if e.id not in rm_set]
            still = {nid for e in self.city_graph.edges for nid in (e.a, e.b)}
            tgt_ids = {n.id for n in target.nodes}
            self.city_graph.nodes = [n for n in self.city_graph.nodes if n.id in still or n.id in tgt_ids]
            for eid in rm:
                events.append({"kind": "road_demolished", "actor_id": "system", "actor_type": "system",
                               "text": "🚧 A road is cleared (master plan).",
                               "payload": {"edge_id": eid, "morph": plan["kind"]}})
        return events
```

Snapshot: in `to_snapshot` (~7158) add `if self.master_plan: snap["master_plan"] = self.master_plan` (additive — only when active); in `from_snapshot` (~7562, near the city_graph restore) add `world.master_plan = state.get("master_plan") or None`.

- [ ] **Step 3: Hook the per-tick step in `loop.py`**

In `loop.py`, in the per-tick block (~627, right after the `expire_miracles` try/except), add:
```python
        # EM-245 (S3b) — advance an active master-plan morph (deterministic k
        # edges/tick, standalone system events, turn_id null).
        try:
            for evt in self._world.step_master_plan_morph():
                evt.setdefault("turn_id", None)
                self._emit_event(evt)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("master-plan morph step failed: %s", exc)
```

- [ ] **Step 4: Run the morph tests + full backend**

Run: `.venv/bin/python -m pytest backend/tests/test_master_plan.py -q` then `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions (an inactive `master_plan` is a no-op → existing runs byte-identical).

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/engine/loop.py backend/tests/test_master_plan.py
git commit -m "feat(EM-245): per-tick city-morph engine + snapshot + loop hook (S3b)"
```

---

### Task 3: `adopt_master_plan` vote-gated rule effect (mirror EM-244)

**Files:**
- Modify: `backend/petridish/engine/world.py` (`valid_effects` ~3554 += `adopt_master_plan`; propose-validation block after `set_car_policy`; `_on_rule_activated` branch after the `set_car_policy` branch; `_evaluate_rule` 0.7 set ~4172; the no-renewal exclusion lists)
- Modify: `backend/petridish/agents/runtime.py` (front-gate effects set + `propose_rule` schema; mirror `demolish_road`)
- Test: `backend/tests/test_master_plan.py`

**Interfaces:**
- Consumes: the morph state (Task 2); the EM-244 `propose_rule` machinery.
- Produces: ratifiable `adopt_master_plan` (payload `{kind, params}`) that sets `self.master_plan` on activation; **one active plan at a time** (propose rejected while `self.master_plan` is set).

- [ ] **Step 1: Write the failing governance test**

Add to `test_master_plan.py` (mirror `test_layout_governance.py`'s `_gov_world`/`_ratify` — grep + reuse them):

```python
def test_propose_and_ratify_adopt_master_plan_starts_morph():
    from petridish.engine.world import World
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    ok, reason, rule = w.action_propose_rule(agent, "adopt_master_plan", "go pentagon", target="pentagon")
    assert ok, reason
    for a in w.agents.values():
        w.action_vote(a, rule.id, True)
    assert rule.status == "active"
    assert w.master_plan is not None and w.master_plan["kind"] == "pentagon"


def test_one_active_plan_at_a_time():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    agent = next(iter(w.agents.values()))
    w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
    ok, reason, _ = w.action_propose_rule(agent, "adopt_master_plan", "switch", target="radial")
    assert not ok and "already" in reason.lower()


def test_adopt_master_plan_rejects_unknown_kind():
    w = _world()
    gov = next(p for p in w.places.values() if p.kind == "governance")
    for a in w.agents.values():
        a.location = gov.id
    ok, reason, _ = w.action_propose_rule(next(iter(w.agents.values())),
                                          "adopt_master_plan", "x", target="hexagon")
    assert not ok and "kind" in reason.lower()
```

Run: `.venv/bin/python -m pytest backend/tests/test_master_plan.py -q -k adopt or one_active`
Expected: FAIL — `invalid effect: 'adopt_master_plan'`.

- [ ] **Step 2: Add the effect (mirror `demolish_road` from EM-244)**

In `world.py`:
- `valid_effects` (~3554) += `"adopt_master_plan"`.
- Propose-validation block (after the `set_car_policy` block): `target` (or a `kind` kwarg) is the plan kind; reject if not in `MASTER_PLAN_KINDS`; **reject if `self.master_plan is not None`** ("a master plan is already in progress"); `payload = {"kind": kind, "params": {}}`.
- `_on_rule_activated` branch (after the `set_car_policy` branch): `rule.applied = True`; `self.master_plan = {"kind": payload["kind"], "params": payload.get("params") or {}, "seed": self.city_seed}`; park a `master_plan_adopted` system event.
- `_evaluate_rule` (~4172) supermajority tuple += `"adopt_master_plan"`.
- No-renewal exclusion lists (propose ~3755 + vote ~3818) += `"adopt_master_plan"` (one-shot; the one-active guard already blocks duplicates).

In `runtime.py`: add `"adopt_master_plan"` to the `_validate_world` front-gate effects set + the `propose_rule` effect schema; thread the `kind` via `args.target` (mirror `demolish_road`'s target passing). Import `MASTER_PLAN_KINDS` where the gate validates.

- [ ] **Step 3: Run the governance tests + full backend**

Run: `.venv/bin/python -m pytest backend/tests/test_master_plan.py -q` then `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions.

- [ ] **Step 4: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/agents/runtime.py backend/tests/test_master_plan.py
git commit -m "feat(EM-245): adopt_master_plan vote-gated effect (0.7, one active plan) (S3b)"
```

---

### Task 4: Wire the geometric presets into `template()` (completes EM-246)

**Files:**
- Modify: `backend/petridish/engine/citygraph.py` (the EM-246 `template()` dispatcher — geometric kinds now route to `master_plan` instead of the grid fallback)
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: `master_plan` (Task 1); the EM-246 `template()`.
- Produces: `template("pentagon"/"radial"/"ring", seed)` returns the geometric graph (a master plan seeded at start, no morph).

- [ ] **Step 1: Write the failing test**

Add to `test_citygraph.py`:
```python
def test_template_geometric_now_routes_to_master_plan():
    g = template("pentagon", 1337)
    mp = master_plan("pentagon", {}, 1337)
    assert [e.id for e in g.edges] == [e.id for e in mp.edges]   # NOT the grid fallback anymore
    assert g.template == "pentagon"
```

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q -k geometric_now`
Expected: FAIL — `template("pentagon")` still returns the grid fallback.

- [ ] **Step 2: Route geometric kinds in `template()`**

In `template()` (EM-246), before the unknown/fallback branch, add:
```python
    if kind in ("pentagon", "radial", "ring"):
        return master_plan(kind, {"radius": _PLAN_RADIUS}, seed)   # a plan seeded at start, no morph
```
(Keep grid/greenfield/village as-is; truly unknown kinds still fall back to grid.) Update the EM-246 `template()` docstring: geometric presets are now live (render through EM-247's mesh when `ROAD_MESH_ENABLED` is on).

- [ ] **Step 3: Run + full backend**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py backend/tests/test_city_templates.py -q` then `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions. (The EM-246 geometric-fallback test must be UPDATED — a `template: pentagon` now yields a pentagon graph, not grid; adjust that EM-246 assertion to the new behavior and note it.)

- [ ] **Step 4: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py backend/tests/test_city_templates.py
git commit -m "feat(EM-245): route geometric templates to master_plan — completes EM-246 presets (S3b)"
```

---

### Task 5: Determinism / replay / acceptance

**Files:**
- Test: `backend/tests/test_master_plan.py`

- [ ] **Step 1: Acceptance tests**

Add: a full propose→ratify→morph-to-completion sequence is deterministic across two worlds (identical `city_graph.to_dict()` at every tick); a mid-morph snapshot round-trips and **resumes identically** (snapshot at tick N, restore, continue → same final graph as not snapshotting); the morph never leaves the graph edgeless (≥1 edge at every step). Confirm `building_relocation` is deferred (a comment test: buildings keep their `location`; lots re-derive frontend-side).

```python
def test_full_morph_replay_is_byte_identical():
    def run(snapshot_at=None):
        w = _world()
        w.master_plan = {"kind": "pentagon", "params": {}, "seed": w.city_seed}
        for t in range(200):
            if snapshot_at is not None and t == snapshot_at:
                w = World.from_snapshot(w.to_snapshot())     # restore mid-morph
            w.step_master_plan_morph()
            assert len(w.city_graph.edges) >= 1              # never edgeless
            if w.master_plan is None:
                break
        return w.city_graph.to_dict()
    assert run() == run(snapshot_at=5)                       # snapshot mid-morph ⇒ identical result
```

- [ ] **Step 2: Full backend suite (regression)**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_master_plan.py
git commit -m "test(EM-245): full-morph determinism/replay/snapshot-resume acceptance (S3b)"
```

---

## Self-Review

**1. Spec coverage (§4 S3b):**
- §4.1 target generation (pentagon/radial/ring/grid, pure) → Task 1 (`master_plan`). ✅
- §4.2 morph (diff + deterministic schedule k edges/tick, road_built/road_demolished) → Task 1 (`diff_graphs`) + Task 2 (`step_master_plan_morph` + loop hook). ✅
- §4.3 building relocation → **rides frontend `assignBuildingLots`** (per EM-244); backend `building_relocated` deferred (recorded). ✅ (documented deviation)
- §4.4 adoption gate (propose → 0.7 → morph; one active plan) → Task 3. ✅
- §2 shared scaffolding (events, layout_event = the graph-in-snapshot) → Task 2 snapshot. ✅
- §6 determinism/replay → Tasks 1, 2, 5. ✅
- S4 handoff (templates reuse the generators) → Task 4. ✅
- Renders through EM-247's mesh; geometric visual gated on `ROAD_MESH_ENABLED` sign-off → recorded.

**2. Placeholder scan:** The FILL points (Task 3 `_gov_world`/`_ratify` reuse from `test_layout_governance.py`; the EM-244 mirror sites) are "grep + mirror" with exact line pointers. Task 4 flags the EM-246 geometric-fallback test must be updated (behavior legitimately changed). `_ordered_edge_geom` is distinct from the lattice `_ordered_edge` (geom ids don't parse as `n:i:j`). No TBD. ✅

**3. Type consistency:** `master_plan(kind, params, seed) -> CityGraph`; `diff_graphs(current, target) -> dict` (add_nodes/add_edges/remove_node_ids/remove_edge_ids); `self.master_plan: {kind, params, seed} | None`; `step_master_plan_morph() -> list[dict]`; `MORPH_EDGES_PER_TICK`; `MASTER_PLAN_KINDS`; effect `adopt_master_plan` consistent across valid_effects/propose/activate/evaluate/gate/schema; events `road_built`/`road_demolished`/`master_plan_adopted`/`master_plan_complete`. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-em245-master-plan-morph.md`. Built via **/orchestrator ultracode** (Workflow mode). **Backend-only** (frontend renders the morph via EM-243 live-render + EM-247 mesh). This is the **final** agent city-layout control — after it, the initiative is complete (modulo EM-247's deferred visual sign-off). Building relocation rides the frontend re-derivation (per EM-244); proximity-preserving diff + per-plan `params` richness are recorded refinements. The geometric *visual* renders correctly once `ROAD_MESH_ENABLED` is flipped on (the user's sign-off).

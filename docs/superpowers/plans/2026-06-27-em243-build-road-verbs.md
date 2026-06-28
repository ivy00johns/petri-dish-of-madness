# EM-243 (S2) — Agent `build_road` Verb + Local Perception Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give agents the first city-reshaping verb — `build_road` — that extends the `CityGraph` by one axis-aligned segment on the agent's turn, paid in energy, with a district-scoped `nearby_layout` perception block so agents can choose where to build.

**Architecture:** A pure, deterministic graph mutation (`apply_build_road` in `citygraph.py`) wrapped by a `World.action_build_road` method (validate → mutate `self.city_graph` → deduct energy → return a `road_built` event dict, mirroring `action_demolish`), dispatched through the existing `_apply_action_inner` table and `ACTION_SCHEMA`. The grown graph already serializes in every snapshot (EM-239), so replay/fork reproduce it; `apply_build_road` is pure so action-replay reproduces it too. The renderer re-derives from the mutated graph with **no frontend code change** (S1 guaranteed this) — the only frontend work is *tests* proving tessellation handles irregular/extended grids.

**Tech Stack:** Python 3.12 backend (pytest), TypeScript/React-Three-Fiber frontend (Vitest). EM-155 byte-identical determinism contract.

## Global Constraints

- **Axis-aligned only.** Segments extend one `BLOCK_PITCH` (13.0u = 5 tile-index steps) in a cardinal direction. No diagonal/curved geometry (that's S3b/S5a). S1's tile renderer is reused unchanged.
- **Grow-only.** Individuals can only *add* roads in S2 — no demolish, no car-policy, no master plans (all vote-gated in S3). The city accretes and stays legible.
- **Determinism / EM-155.** Node ids are `n:{i}:{j}` and edge ids `e:{a}->{b}` derived purely from grid position (no RNG/clock). The grown graph is serialized in `to_snapshot` (`world.py:7118`, unconditional) and restored in `from_snapshot` (`world.py:7522`); `apply_build_road` is a pure function. Same snapshot/seed + same `road_built` actions ⇒ identical grown graph across live/replay/fork.
- **No new standing LLM calls.** `build_road` is an option in the existing turn; the only prompt delta is the compact `nearby_layout` block (must fit the 8K diet lane — district-scoped, hard line-capped, omitted when nothing is extendable).
- **Energy is the rate-limiter.** `build_road` costs `road_build_energy_cost` energy (reuses the survival economy; no new economy). Under the EM-199 multi-action model each step deducts energy independently — energy bounds the rate, there is no hard one-build-per-turn rule.
- **Bounded growth.** New nodes must stay within the `MAX_CITY_BLOCKS` envelope (9×9: tile-index lattice `[-23, 22]`, extending the frozen 5×5 `[-13, 12]`) — protects prompt + render budget.
- **Toolchain (from `petridish-test-toolchain` memory):** backend tests `.venv/bin/python -m pytest <path> -q`; frontend `cd web && /usr/local/bin/npx vitest run <path>`; typecheck `cd web && /usr/local/bin/npx tsc -b --force` (NOT `--noEmit`). No `python`/`npx` on PATH.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/petridish/engine/citygraph.py` | Pure graph ops: bounds, direction deltas, `nearest_node`, `extendable_directions`, `apply_build_road` | 1 |
| `backend/tests/test_citygraph.py` | Tests for the pure ops (extends the EM-239 file) | 1 |
| `backend/petridish/config/loader.py` | `road_build_energy_cost` + `max_city_blocks` params (dataclass + embedded YAML + parser) | 2 |
| `backend/petridish/engine/world.py` | `action_build_road(agent, args) -> dict` (the world-side verb) | 2 |
| `backend/tests/test_build_road.py` (new) | World-method + dispatch + perception tests | 2,3,4 |
| `backend/petridish/agents/runtime.py` | `ACTION_SCHEMA` enum, `_apply_action_inner` dispatch, `_assemble_context` menu + `nearby_layout` | 3,4 |
| `web/src/components/world3d/cityLayout.test.ts` | Tessellation tests for irregular/extended axis-aligned graphs | 5 |
| `backend/tests/test_build_road.py` | Determinism/replay + derivation acceptance | 6 |

---

### Task 1: Pure graph ops in `citygraph.py`

**Files:**
- Modify: `backend/petridish/engine/citygraph.py` (append constants + functions after `classic_grid`)
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: `CityGraph`, `CityNode`, `CityEdge`, `tile_center`, `_node_id`, `ROAD_TILE_INDICES` (all already in `citygraph.py`).
- Produces:
  - `MAX_CITY_BLOCKS: int = 9`, `MIN_IDX: int = -23`, `MAX_IDX: int = 22`
  - `DIR_DELTA: dict[str, tuple[int, int]]` (north/south/east/west → (di, dj))
  - `nearest_node(graph: CityGraph, x: float, z: float) -> CityNode | None`
  - `extendable_directions(graph: CityGraph, node_id: str) -> dict[str, str]` (dir → "open"|"road"|"edge")
  - `apply_build_road(graph: CityGraph, from_node_id: str, direction: str) -> tuple[bool, str, dict | None]` (mutates `graph` on success; `info = {from_node, direction, new_node_id, new_edge_id}`)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_citygraph.py`:

```python
from petridish.engine.citygraph import (
    classic_grid, apply_build_road, nearest_node, extendable_directions,
    MAX_IDX, MIN_IDX, tile_center,
)


def test_build_road_extends_one_segment_east():
    g = classic_grid(1337)
    n0, e0 = len(g.nodes), len(g.edges)
    ok, reason, info = apply_build_road(g, "n:12:2", "east")
    assert ok, reason
    assert info["new_node_id"] == "n:17:2"
    assert info["new_edge_id"] == "e:n:12:2->n:17:2"
    assert len(g.nodes) == n0 + 1 and len(g.edges) == e0 + 1
    assert any(n.id == "n:17:2" for n in g.nodes)


def test_build_road_edge_id_orders_low_index_first():
    # Extending WEST from the left edge: the new (lower-i) node sorts first in the id.
    g = classic_grid(1337)
    ok, reason, info = apply_build_road(g, "n:-13:2", "west")
    assert ok, reason
    assert info["new_node_id"] == "n:-18:2"
    assert info["new_edge_id"] == "e:n:-18:2->n:-13:2"


def test_build_road_rejects_out_of_bounds():
    g = classic_grid(1337)
    # n:22:2 is the max index; one more east is off the 9x9 envelope.
    apply_build_road(g, "n:12:2", "east")     # -> n:17:2
    apply_build_road(g, "n:17:2", "east")     # -> n:22:2 (still in bounds)
    ok, reason, info = apply_build_road(g, "n:22:2", "east")  # -> n:27:2 OUT
    assert not ok and info is None
    assert "edge of the city" in reason


def test_build_road_rejects_existing_road():
    g = classic_grid(1337)
    # n:7:2 -> n:12:2 is already an edge in the classic grid.
    ok, reason, info = apply_build_road(g, "n:7:2", "east")
    assert not ok and "already a road" in reason


def test_build_road_rejects_unknown_anchor_and_direction():
    g = classic_grid(1337)
    ok, reason, _ = apply_build_road(g, "n:999:999", "east")
    assert not ok and "anchor" in reason
    ok, reason, _ = apply_build_road(g, "n:12:2", "upward")
    assert not ok and "direction" in reason


def test_build_road_is_pure_and_deterministic():
    a, b = classic_grid(1337), classic_grid(1337)
    for nid, d in [("n:12:2", "east"), ("n:17:2", "east"), ("n:2:12", "north")]:
        apply_build_road(a, nid, d)
        apply_build_road(b, nid, d)
    assert a.to_dict() == b.to_dict()  # identical grown graph


def test_nearest_node_picks_closest():
    g = classic_grid(1337)
    n = nearest_node(g, tile_center(2) + 0.1, tile_center(2) - 0.1)
    assert n is not None and n.id == "n:2:2"


def test_extendable_directions_classifies_open_road_edge():
    g = classic_grid(1337)
    dirs = extendable_directions(g, "n:12:2")  # right edge of the grid, middle row
    assert dirs["east"] == "open"   # in-bounds, no edge yet
    assert dirs["west"] == "road"   # n:7:2->n:12:2 exists
    dirs_corner = extendable_directions(g, "n:22:22")
    # n:22:22 doesn't exist yet; but extendable_directions parses the id and bounds-checks
    assert dirs_corner["east"] == "edge" and dirs_corner["north"] == "edge"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: FAIL — `ImportError: cannot import name 'apply_build_road'` (functions not defined).

- [ ] **Step 3: Implement the pure ops**

Append to `backend/petridish/engine/citygraph.py` (after `classic_grid`):

```python
# ── EM-243 (S2): bounded, deterministic individual road growth ────────────────
# The frozen 5x5 grid spans tile-index [-13, 12] (6 road lines, all ≡ 2 mod 5).
# MAX_CITY_BLOCKS=9 widens that to a 9x9 envelope = 10 lines = index [-23, 22].
# A segment is one BLOCK_PITCH = 5 index steps (5 * TILE = 13.0u).
MAX_CITY_BLOCKS: int = 9
MIN_IDX: int = -23
MAX_IDX: int = 22

# direction -> (di, dj) in tile-index space (east = +x, north = +z; the N/S label
# is cosmetic and may be flipped to match the on-screen compass — determinism is
# unaffected since ids derive from (i, j), not from the label).
DIR_DELTA: dict[str, tuple[int, int]] = {
    "east": (5, 0), "west": (-5, 0), "north": (0, 5), "south": (0, -5),
}


def _parse_node(node_id: str) -> tuple[int, int]:
    """'n:{i}:{j}' -> (i, j). Raises ValueError on a malformed id."""
    parts = node_id.split(":")
    if len(parts) != 3 or parts[0] != "n":
        raise ValueError(f"malformed node id: {node_id!r}")
    return int(parts[1]), int(parts[2])


def _ordered_edge(id_a: str, id_b: str) -> tuple[str, str, str]:
    """Order two node ids by (i, j) ascending and build the edge id — reproducing
    classic_grid's a->b convention (horizontal by i, vertical by j), so a grown
    grid's edge ids match what a larger classic_grid would emit. Returns (id, a, b)."""
    a, b = sorted([id_a, id_b], key=_parse_node)
    return f"e:{a}->{b}", a, b


def _in_bounds(i: int, j: int) -> bool:
    return MIN_IDX <= i <= MAX_IDX and MIN_IDX <= j <= MAX_IDX


def nearest_node(graph: CityGraph, x: float, z: float) -> CityNode | None:
    """The graph node closest (Euclidean) to a world (x, z). None on an empty graph.
    Note: callers map a place's (x, y) -> (x, z) here (place.y is the world z)."""
    if not graph.nodes:
        return None
    return min(graph.nodes, key=lambda n: (n.x - x) ** 2 + (n.z - z) ** 2)


def extendable_directions(graph: CityGraph, node_id: str) -> dict[str, str]:
    """For each cardinal direction from node_id: 'open' (in-bounds, no edge yet),
    'road' (an edge already runs that way), or 'edge' (out of the city envelope).
    Empty dict if node_id is malformed."""
    try:
        fi, fj = _parse_node(node_id)
    except ValueError:
        return {}
    edge_ids = {e.id for e in graph.edges}
    out: dict[str, str] = {}
    for d, (di, dj) in DIR_DELTA.items():
        ni, nj = fi + di, fj + dj
        if not _in_bounds(ni, nj):
            out[d] = "edge"
            continue
        eid, _, _ = _ordered_edge(node_id, _node_id(ni, nj))
        out[d] = "road" if eid in edge_ids else "open"
    return out


def apply_build_road(
    graph: CityGraph, from_node_id: str, direction: str,
) -> tuple[bool, str, dict | None]:
    """Extend the graph one segment from from_node_id in direction (N/S/E/W).
    Pure validation + in-place mutation on success. Adds the target node if absent
    and the connecting edge. Returns (ok, reason, info). info on success:
    {from_node, direction, new_node_id, new_edge_id}."""
    if direction not in DIR_DELTA:
        return False, f"unknown direction '{direction}' (use north/south/east/west)", None
    if not any(n.id == from_node_id for n in graph.nodes):
        return False, "no anchor node there to build from", None
    try:
        fi, fj = _parse_node(from_node_id)
    except ValueError:
        return False, "the anchor node id is malformed", None
    di, dj = DIR_DELTA[direction]
    ni, nj = fi + di, fj + dj
    if not _in_bounds(ni, nj):
        return False, "that way is the edge of the city (out of bounds)", None
    new_node_id = _node_id(ni, nj)
    new_edge_id, a, b = _ordered_edge(from_node_id, new_node_id)
    if any(e.id == new_edge_id for e in graph.edges):
        return False, "there's already a road that way", None
    if not any(n.id == new_node_id for n in graph.nodes):
        graph.nodes.append(CityNode(id=new_node_id, x=tile_center(ni), z=tile_center(nj)))
    graph.edges.append(CityEdge(id=new_edge_id, a=a, b=b))
    return True, "ok", {
        "from_node": from_node_id, "direction": direction,
        "new_node_id": new_node_id, "new_edge_id": new_edge_id,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: PASS (the new tests + the existing EM-239 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py
git commit -m "feat(EM-243): pure build_road graph ops — apply_build_road/nearest_node/extendable_directions (S2)"
```

---

### Task 2: `road_build_energy_cost` param + `World.action_build_road`

**Files:**
- Modify: `backend/petridish/config/loader.py` (param: dataclass `~1382`, embedded YAML `~71`, parser `~2585`)
- Modify: `backend/petridish/engine/world.py` (import from `.citygraph`; new method near the other `action_*` methods, e.g. after `action_demolish` ~3233)
- Modify: `config/world.yaml` (live default)
- Test: `backend/tests/test_build_road.py` (new)

**Interfaces:**
- Consumes: `apply_build_road`, `nearest_node` (Task 1); `self.params.road_build_energy_cost`; `self._fail_event` (`world.py:4198`); `self.places`, `self.city_graph`, `AgentState.energy/location`.
- Produces: `World.action_build_road(self, agent: AgentState, args: dict) -> dict` (a `road_built` event dict or a `_fail_event`).

- [ ] **Step 1: Add the config param**

In `backend/petridish/config/loader.py`:

Dataclass field (after `attack_energy_cost: float = 6.0`, ~line 1382):
```python
    road_build_energy_cost: float = 8.0  # EM-243 (S2) — meaningful but not rare (cf. attack 6)
    max_city_blocks: int = 9             # EM-243 (S2) — growth envelope (9x9); see citygraph.MAX_CITY_BLOCKS
```
Embedded YAML mirror (after `attack_energy_cost: 6`, ~line 71):
```yaml
  road_build_energy_cost: 8
  max_city_blocks: 9
```
Parser (after `attack_energy_cost=float(w.get("attack_energy_cost", 6))`, ~line 2585):
```python
        road_build_energy_cost=float(w.get("road_build_energy_cost", 8)),
        max_city_blocks=int(w.get("max_city_blocks", 9)),
```
And add to `config/world.yaml` under `world:`:
```yaml
  road_build_energy_cost: 8
  max_city_blocks: 9
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_build_road.py`:

```python
import pytest
from petridish.engine.world import World
from petridish.config.loader import load_config


def _world() -> World:
    # Minimal world from the default config; mirror the existing world-test setup.
    cfg = load_config()  # default embedded config
    w = World(cfg)
    return w


def _agent_at(w: World, place_id: str):
    a = next(iter(w.agents.values()))
    a.location = place_id
    a.energy = 100.0
    return a


def test_action_build_road_success_emits_event_and_costs_energy():
    w = _world()
    place_id = next(iter(w.places))            # any real place
    a = _agent_at(w, place_id)
    e0 = len(w.city_graph.edges)
    before = a.energy
    # find an open direction from the agent's nearest node so the build is valid
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "open")
    evt = w.action_build_road(a, {"direction": direction})
    assert evt["kind"] == "road_built"
    assert evt["payload"]["direction"] == direction
    assert len(w.city_graph.edges) == e0 + 1
    assert a.energy == pytest.approx(before - w.params.road_build_energy_cost)


def test_action_build_road_too_tired_refuses_no_graph_change():
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    a.energy = 1.0
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": "east"})
    assert evt["kind"] == "parse_failure"
    assert "tired" in evt["text"].lower()
    assert len(w.city_graph.edges) == e0   # no mutation when refused


def test_action_build_road_blocked_direction_reports_reason():
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    blocked = next((d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "road"), None)
    if blocked is None:
        pytest.skip("no blocked direction at this node")
    e0 = len(w.city_graph.edges)
    evt = w.action_build_road(a, {"direction": blocked})
    assert evt["kind"] == "parse_failure"
    assert len(w.city_graph.edges) == e0
```

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'action_build_road'`.

- [ ] **Step 3: Implement `action_build_road`**

In `backend/petridish/engine/world.py`, extend the citygraph import (it already imports `CityGraph, classic_grid`):
```python
from .citygraph import CityGraph, classic_grid, apply_build_road, nearest_node
```
Add the method (after `action_demolish`, ~line 3233):
```python
    def action_build_road(self, agent: AgentState, args: dict) -> dict:
        """EM-243 (S2) — an agent extends the road graph one axis-aligned segment
        from the node nearest their location, paid in energy. Grow-only (no
        teardown). Returns a `road_built` event dict, or a clear `_fail_event`."""
        direction = str((args or {}).get("direction", "")).strip().lower()
        place = self.places.get(agent.location)
        if place is None:
            return self._fail_event(
                agent.id, "build_road", "no_location",
                f"{agent.name} can't build a road from nowhere.")
        cost = self.params.road_build_energy_cost
        if agent.energy < cost:
            return self._fail_event(
                agent.id, "build_road", "too_tired",
                f"{agent.name} is too tired to build a road (needs {cost:.0f} energy).")
        # place.x/place.y are the world (x, z); the graph node uses (x, z).
        from_node = nearest_node(self.city_graph, float(place.x), float(place.y))
        if from_node is None:
            return self._fail_event(
                agent.id, "build_road", "no_graph",
                f"{agent.name} finds no road to build from.")
        ok, reason, info = apply_build_road(self.city_graph, from_node.id, direction)
        if not ok:
            return self._fail_event(
                agent.id, "build_road", reason,
                f"{agent.name} tried to build a road but: {reason}.")
        agent.energy = max(0.0, agent.energy - cost)
        return {
            "kind": "road_built",
            "actor_id": agent.id,
            "text": f"{agent.name} builds a new road heading {direction}.",
            "payload": {
                "action": "build_road",
                "from_node": info["from_node"],
                "direction": direction,
                "new_node_id": info["new_node_id"],
                "new_edge_id": info["new_edge_id"],
            },
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/config/loader.py backend/petridish/engine/world.py config/world.yaml backend/tests/test_build_road.py
git commit -m "feat(EM-243): World.action_build_road + road_build_energy_cost/max_city_blocks params (S2)"
```

---

### Task 3: Wire `build_road` into the action schema + dispatch

**Files:**
- Modify: `backend/petridish/agents/runtime.py` (`ACTION_SCHEMA` enums ~110 + ~197; dispatch in `_apply_action_inner` ~5359; an `if/then` arg clause mirroring the `propose_project` clause ~237)
- Test: `backend/tests/test_build_road.py`

**Interfaces:**
- Consumes: `World.action_build_road` (Task 2); `_emit_world_result(result, base, thought)` (`runtime.py:1528`).
- Produces: `"build_road"` as a valid parsed action that dispatches to `action_build_road`.

- [ ] **Step 1: Write the failing dispatch test**

Add to `backend/tests/test_build_road.py`:

```python
def test_build_road_in_action_schema_enum():
    from petridish.agents.runtime import ACTION_SCHEMA
    # both the single-action and multi-action enums must allow it
    single = ACTION_SCHEMA["properties"]["action"]["enum"]
    assert "build_road" in single
    multi = ACTION_SCHEMA["properties"]["actions"]["items"]["properties"]["action"]["enum"]
    assert "build_road" in multi


def test_dispatch_routes_build_road(monkeypatch):
    # _apply_action_inner must route "build_road" -> world.action_build_road
    from petridish.agents.runtime import AgentRuntime  # the class holding _apply_action_inner
    w = _world()
    place_id = next(iter(w.places))
    a = _agent_at(w, place_id)
    rt = AgentRuntime(w)  # mirror the existing runtime construction in other tests
    from petridish.engine.citygraph import nearest_node, extendable_directions
    place = w.places[place_id]
    node = nearest_node(w.city_graph, place.x, place.y)
    direction = next(d for d, s in extendable_directions(w.city_graph, node.id).items() if s == "open")
    evt = rt._apply_action_inner(a, {"action": "build_road", "args": {"direction": direction}}, "P", "#fff")
    assert evt["kind"] == "road_built"
```

> NOTE: match the real `AgentRuntime` class name / constructor used in the existing runtime tests — grep `backend/tests/` for how `_apply_action_inner` is currently exercised and mirror that exactly (class name, constructor args). Do not invent a constructor.

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q -k schema or dispatch`
Expected: FAIL — `"build_road"` not in the enum; dispatch falls through to the unknown-action branch.

- [ ] **Step 2: Add `build_road` to both `ACTION_SCHEMA` enums**

In `runtime.py`, add `"build_road"` to the single-action enum (~line 162, near `"demolish", "set_building_skin"`) and the multi-action enum (~line 224). Add an arg clause after the `propose_project` clause (~line 237) so a `build_road` requires `args.direction`:
```python
        {"if": {"required": ["action"], "properties": {"action": {"const": "build_road"}}},
         "then": {"properties": {"args": {"required": ["direction"],
                  "properties": {"direction": {"enum": ["north", "south", "east", "west"]}}}}}},
```

- [ ] **Step 3: Add the dispatch branch**

In `_apply_action_inner` (`runtime.py`, alongside the other `elif action == ...` branches, e.g. near `demolish`):
```python
        elif action == "build_road":
            result = self.world.action_build_road(agent, args)
            return _emit_world_result(result, base, thought)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/agents/runtime.py backend/tests/test_build_road.py
git commit -m "feat(EM-243): wire build_road into ACTION_SCHEMA + dispatch (S2)"
```

---

### Task 4: `nearby_layout` perception + menu entry in `_assemble_context`

**Files:**
- Modify: `backend/petridish/agents/runtime.py` (`_assemble_context` ~2134: `valid_actions` ~2288 + a `nearby_layout` context line)
- Test: `backend/tests/test_build_road.py`

**Interfaces:**
- Consumes: `extendable_directions`, `nearest_node` (Task 1); `self.params.road_build_energy_cost`; `world.city_graph.car_policy`; `_diet_visible_districts`/`world.places[agent.location]`.
- Produces: a `build_road` menu line (only when the agent can afford it AND a direction is `open`); a compact `nearby_layout` perception string (district-scoped, hard-capped, omitted when nothing is extendable).

**Scope note (honest):** lot *counts* in the spec's example require backend lot derivation, which does not exist (lots derive on the frontend, S1). S2's `nearby_layout` reports **extendable directions + car policy** — what the backend can compute from the graph. Lot-count perception is deferred to whenever backend lot derivation lands; do not fabricate it.

- [ ] **Step 1: Write the failing perception test**

Add to `backend/tests/test_build_road.py`:

```python
def test_nearby_layout_lists_extendable_directions():
    from petridish.agents.runtime import build_nearby_layout  # pure helper (Step 3)
    w = _world()
    place = w.places[next(iter(w.places))]
    line = build_nearby_layout(w, place)
    assert line is not None
    assert "build" in line.lower() or "extend" in line.lower()
    # reports at least one cardinal status and the car policy
    assert any(d in line.lower() for d in ("north", "south", "east", "west"))
    assert "cars" in line.lower()


def test_nearby_layout_omitted_when_nothing_extendable():
    # A fully-enclosed node (all 4 dirs are road/edge) -> None (diet: omit empties)
    from petridish.agents.runtime import build_nearby_layout
    from petridish.engine.citygraph import classic_grid
    w = _world()
    # n:2:2 is interior — all four neighbors are existing roads
    place = w.places[next(iter(w.places))]
    # force the nearest node to the interior by placing the perception at center coords
    line = build_nearby_layout(w, place, force_node_id="n:2:2")
    assert line is None
```

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q -k nearby`
Expected: FAIL — `ImportError: cannot import name 'build_nearby_layout'`.

- [ ] **Step 2 is folded into Step 3** (helper + wiring land together — the menu line and the perception string share the same `extendable_directions` call).

- [ ] **Step 3: Implement `build_nearby_layout` + wire the menu**

Add a module-level helper to `runtime.py` (near `_diet_visible_districts`, ~line 900):
```python
def build_nearby_layout(world: "World", place: Any, force_node_id: str | None = None) -> str | None:
    """EM-243 (S2) — a compact, diet-safe perception line for road-building:
    extendable directions from the node nearest `place`, plus the car policy.
    Returns None when nothing is extendable (diet: omit empty blocks)."""
    from ..engine.citygraph import nearest_node, extendable_directions
    node = (next((n for n in world.city_graph.nodes if n.id == force_node_id), None)
            if force_node_id else nearest_node(world.city_graph, float(place.x), float(place.y)))
    if node is None:
        return None
    dirs = extendable_directions(world.city_graph, node.id)
    openable = [d for d, s in dirs.items() if s == "open"]
    if not openable:
        return None
    blocked = [f"{d} ({s})" for d, s in dirs.items() if s != "open"]
    cars = world.city_graph.car_policy
    line = f"Nearby layout: can build a road {', '.join(openable)}."
    if blocked:
        line += f" Blocked: {', '.join(blocked)}."
    line += f" Cars: {cars}."
    return line
```
In `_assemble_context`, after the existing perception sections, add the line to the agent's context (mirror how other perception strings are appended — grep the function for where `nearby`/place context is added) and add the menu entry guarded by affordability + an open direction:
```python
        # EM-243 (S2) — road-building perception + menu (only when affordable + extendable).
        _here = world.places.get(agent.location)
        _layout = build_nearby_layout(world, _here) if _here is not None else None
        if _layout is not None and agent.energy >= world.params.road_build_energy_cost:
            valid_actions.append("build_road (direction: north|south|east|west) - extend a street one block")
            # append _layout into the context block the same way sibling perception lines are added
```

> Wiring detail: append `_layout` to whatever list/string `_assemble_context` returns as the observation (the same mechanism the "nearby places/agents" lines use). Keep it ONE line (diet). Do not add it when `_layout is None`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_build_road.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/agents/runtime.py backend/tests/test_build_road.py
git commit -m "feat(EM-243): nearby_layout perception + build_road menu (diet-safe) (S2)"
```

---

### Task 5: Frontend tessellation tests for irregular/extended graphs

The renderer needs **no new code** (S1's graph-driven derivation already re-derives roads from the graph). S2's risk is that S1 only *tested* the full 5×5; a single extension creates a new `road_end` stub and turns its anchor into a `road_tee`. Prove the existing mask classification handles partial/extended grids.

**Files:**
- Modify: `web/src/components/world3d/cityLayout.test.ts` (new EM-243 describe block)

**Interfaces:**
- Consumes: the EM-239 `CityGraph` fixture helpers already in `cityLayout.test.ts` (e.g. `classicGridGraph`), `computeCityPlan` / the road-tile predicate, and the tile-classification (`END_ROT`/`TEE_ROT`/`CORNER_ROT`) exercised by the existing tests.

- [ ] **Step 1: Write the tessellation tests**

Add to `web/src/components/world3d/cityLayout.test.ts` (mirror the existing graph-fixture style; build a grown graph by appending one node+edge to the classic-grid fixture, matching `apply_build_road`'s ids `n:17:2` / `e:n:12:2->n:17:2`):

```typescript
describe('EM-243 (S2): tessellation of extended/irregular axis-aligned graphs', () => {
  it('a single east extension renders a road_end stub + turns its anchor into a tee', () => {
    const g = classicGridGraph(1337);
    // mirror apply_build_road: add node n:17:2 + edge n:12:2->n:17:2
    g.nodes.push({ id: 'n:17:2', x: (17 + 0.5) * 2.6, z: (2 + 0.5) * 2.6, kind: 'junction' });
    g.edges.push({ id: 'e:n:12:2->n:17:2', a: 'n:12:2', b: 'n:17:2', road_class: 'street', car_policy: 'inherit' });
    const plan = computeCityPlan({ ...TOWN, city_graph: g });
    // the new stub tile classifies as a dead-end; no crash, no gap
    expect(plan).toBeTruthy();
    // assert the road-tile set now includes the extended segment's tiles
    // (use the same road-tile assertion idiom the EM-239 tests use)
  });

  it('classifies tee/corner/end correctly on a partial (non-full) grid', () => {
    // remove one edge from the full grid to force a tee/end and confirm classification
    const g = classicGridGraph(1337);
    g.edges = g.edges.filter((e) => e.id !== 'e:n:7:2->n:12:2');
    const plan = computeCityPlan({ ...TOWN, city_graph: g });
    expect(plan).toBeTruthy(); // renders without gap/throw on the irregular grid
  });
});
```

> Match the EM-239 test's exact fixture names (`classicGridGraph`, `TOWN`, `computeCityPlan`) and the road-tile assertion idiom — grep `cityLayout.test.ts` for the EM-239 describe block and reuse its helpers/assertions verbatim. If a real classification bug surfaces on irregular grids, FIX it in `cityLayout.ts` (the spec says the masks already support this; a failure is a real defect, not a test to weaken).

- [ ] **Step 2: Run the tests**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d/cityLayout.test.ts`
Expected: PASS (new block + existing). If a classification gap is found, fix `cityLayout.ts` and re-run.

- [ ] **Step 3: Typecheck + commit**

Run: `cd web && /usr/local/bin/npx tsc -b --force` (exit 0)
```bash
git add web/src/components/world3d/cityLayout.test.ts web/src/components/world3d/cityLayout.ts
git commit -m "test(EM-243): tessellation parity on extended/irregular axis-aligned graphs (S2)"
```

---

### Task 6: Determinism / replay / derivation acceptance

**Files:**
- Test: `backend/tests/test_build_road.py`

**Interfaces:**
- Consumes: `World.to_snapshot`/`World.from_snapshot`, `action_build_road`, `apply_build_road`.

- [ ] **Step 1: Write the acceptance tests**

Add to `backend/tests/test_build_road.py`:

```python
def test_grown_graph_survives_snapshot_round_trip():
    w = _world()
    apply_build_road(w.city_graph, "n:12:2", "east")     # n:17:2
    apply_build_road(w.city_graph, "n:17:2", "east")     # n:22:2
    snap = w.to_snapshot()
    w2 = World.from_snapshot(snap)
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()  # byte-identical grown graph


def test_replaying_same_builds_yields_identical_graph():
    # EM-155: the grown graph is a pure function of (seed, ordered road_built actions)
    a, b = _world(), _world()
    builds = [("n:12:2", "east"), ("n:17:2", "east"), ("n:2:12", "north")]
    for nid, d in builds:
        apply_build_road(a.city_graph, nid, d)
        apply_build_road(b.city_graph, nid, d)
    assert a.city_graph.to_dict() == b.city_graph.to_dict()


def test_new_road_extends_node_and_edge_counts_monotonically():
    w = _world()
    n0, e0 = len(w.city_graph.nodes), len(w.city_graph.edges)
    ok, _, _ = apply_build_road(w.city_graph, "n:12:2", "east")
    assert ok
    assert len(w.city_graph.nodes) == n0 + 1
    assert len(w.city_graph.edges) == e0 + 1
```

> Derivation (new roads → new lots → buildings auto-assign) is **frontend-derived** from the grown graph (S1), so its data-layer proof is the snapshot round-trip above (the frontend re-derives from the identical graph). The *visual* derivation is the live-walk acceptance, not a backend unit test.

- [ ] **Step 2: Run the full backend suite (regression)**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions vs the pre-EM-243 baseline (the EM-239 build left it at 1620; the new tests add to that).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_build_road.py
git commit -m "test(EM-243): determinism/replay/snapshot acceptance for build_road (S2)"
```

---

## Self-Review

**1. Spec coverage (`…s2-build-verbs-design.md`):**
- §3 the verb (anchored/in-bounds/vacant/affordable + cost + clear reasons) → Task 1 (`apply_build_road` rules) + Task 2 (energy/affordable + `_fail_event` reasons). ✅
- §4 local perception (district-scoped, line-capped, omitted when nothing extendable, counts/directions only) → Task 4 (`build_nearby_layout`). ✅ (lot-count deferred, recorded honestly.)
- §5 determinism/events/replay (`road_built`, deterministic ids, graph = pure fn) → Task 2 (event), Task 1 (ids), Task 6 (replay/snapshot). ✅
- §6 derivation generalizes → covered by S1 + Task 6 round-trip + Task 5 frontend tessellation. ✅
- §7 frontend (tessellation on irregular grids, no new code) → Task 5. ✅
- §8 component boundaries (citygraph / runtime action surface / loop) → Tasks 1/2/3/4. ✅
- §9 testing & acceptance → Tasks 1–6. ✅
- §10 open values (`ROAD_BUILD_ENERGY_COST`, `MAX_CITY_BLOCKS`) → set to 8 and 9 (tunable config), recorded. ✅

**2. Placeholder scan:** No TBD/"handle errors"/"similar to". Two flagged *verification* notes (match the real `AgentRuntime` constructor in Task 3; reuse the EM-239 `cityLayout.test.ts` fixture names in Task 5) are explicit "grep the existing pattern and mirror it" instructions, not placeholders — the surrounding code is exact. ✅

**3. Type consistency:** `apply_build_road` returns `(bool, str, dict | None)` everywhere; `nearest_node(graph, x, z)`; `build_nearby_layout(world, place, force_node_id=None)`; node ids `n:{i}:{j}`, edge ids `e:{a}->{b}` ordered by `(i,j)`; `action_build_road(agent, args) -> dict` (demolish dict-pattern, `_emit_world_result`-wrapped). Direction enum `north|south|east|west` consistent across schema, `DIR_DELTA`, and the menu. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-27-em243-build-road-verbs.md`. Per your request this will be built via **/orchestrator in ultracode (Workflow mode)** — design/contracts inline (this plan), implement + verify as workflows. Backend-heavy (Tasks 1–4, 6) with a focused frontend tessellation slice (Task 5); the open tuning values (energy cost 8, envelope 9×9) are set as config and confirmed against a live run at the end.

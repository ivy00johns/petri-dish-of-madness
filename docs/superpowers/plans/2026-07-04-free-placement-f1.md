# Free Placement F1 — Organic Cluster-Accretion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Intended executor: the `orchestrator` army** (the user's framing) — under multi-agent execution the LEAD commits per task/lane per the build contract; the per-task "Commit" steps below are the lead's checkpoints, not subagent git writes.

**Goal:** Give buildings a deterministic world-frame `position` computed by cluster accretion (hamlets, not a grid), set as backend event-sourced state, rendered directly by the frontend — restoring build-anywhere freedom behind a default-off flag, byte-identical (EM-155).

**Architecture:** Buildings gain `position` (world frame ±32.5). A pure `place_all(buildings, anchor, seed)` runs cluster accretion in canonical `(created_tick, id)` order (== creation order → append-only-stable). Position is stored at build time; migration derives-on-load only for position-less (pre-F1) buildings. Frontend renders `position` directly when the flag is on, else falls back to the untouched `assignBuildingLots`.

**Tech Stack:** Python 3.11 / FastAPI backend (`backend/petridish/`), React + TypeScript + Three.js frontend (`web/`). Determinism via `citygraph._seeded_unit`. Design: `docs/superpowers/specs/2026-07-04-free-placement-f1-organic-accretion-design.md`.

## Global Constraints

- **Determinism (EM-155) is the acceptance bar.** Replay/fork byte-identical. New serialized fields serialize **only when set** + restore with an old-snapshot fallback (absent ⇒ deterministic default, never a crash). Never regenerate a golden silently.
- **World frame ±32.5 end-to-end.** `position` is world-frame (the frame citygraph nodes and `assignBuildingLots` output already use); NO logical↔world conversion on the 3D path. Anchor = world `(0.0, 0.0)` (= logical `(500,500)`, city center). CityGraph nodes are world-frame, NOT logical (`citygraph.py:35-36`).
- **Seed source:** `self.city_seed` (int, default 1337; `world.py:1318`). Every random draw is `citygraph._seeded_unit(seed, key)` → float `[0,1)` (`citygraph.py:335`).
- **Flag:** `FREE_PLACEMENT_ENABLED`, default **False**, backend + frontend paired (mirror `GRAPH_ZONES_ENABLED`, `agents/runtime.py:961`). Flag OFF ⇒ byte-identical to current `main`.
- **Toolchain:** backend `.venv/bin/python -m pytest <targets>` from repo root (no bare `python`). Frontend `/usr/local/bin/npx vitest run <targets>` and `/usr/local/bin/npx tsc -b --force` from `web/` (nvm broken; never `tsc --noEmit`).
- **Byte-identical golden reproducibility:** tests that assert positions monkeypatch `world_mod.uuid.uuid4` via the `_det_uuid()` counter pattern (`backend/tests/test_zone_targeted_build.py:322-421`).
- **New test files only** — never edit a shared existing test file. Minimal diffs, match surrounding style.

## File Structure

- `backend/petridish/engine/placement.py` — **new.** Pure accretion: `place_all`, `place_one`, `MIN_SPACING`, helpers.
- `backend/petridish/engine/world.py` — **modify.** `Building.position` field + `to_dict` + `from_snapshot` restore + build-time storage (mint site ~`4910`) + migration (after restore loop ~`8279`).
- `backend/petridish/agents/runtime.py` — **modify.** Add `FREE_PLACEMENT_ENABLED = False`.
- `web/src/types/index.ts` — **modify.** `Building.position?: [number, number]` (`:170`).
- `web/src/components/world3d/cityLayout.ts` — **modify.** `FREE_PLACEMENT_ENABLED` + `resolveBuildingPositions` wrapper.
- `web/src/components/world3d/CozyWorld.tsx` — **modify.** Call `resolveBuildingPositions` instead of `assignBuildingLots` (`:50`, `:475-528`).
- New tests: `backend/tests/test_free_placement_position_field.py`, `test_free_placement_accretion.py`, `test_free_placement_build_time.py`, `test_free_placement_migration.py`; `web/src/components/world3d/cityLayout.f1.test.ts`.

---

### Task 1: `Building.position` field + snapshot round-trip

**Files:**
- Modify: `backend/petridish/engine/world.py` (`Building` dataclass ~`761`, `to_dict` ~`794`, `from_snapshot` ~`8277`)
- Test: `backend/tests/test_free_placement_position_field.py`

**Interfaces:**
- Produces: `Building.position: tuple[float, float] | None`; serialized as `"position": [x, z]` in `to_dict` only when set; restored in `from_snapshot`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_free_placement_position_field.py
"""EM-268 F1 — Building.position rides the snapshot only when set (byte-identical)."""
import copy
from petridish.engine.world import Building, World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def test_position_serialized_only_when_set():
    b = Building(id="bld_x", name="Hall", kind="workshop", location="plaza")
    assert "position" not in b.to_dict()          # unset ⇒ omitted (byte-identical)
    b.position = (3.5, -2.0)
    assert b.to_dict()["position"] == [3.5, -2.0]  # set ⇒ list, world frame


def test_position_round_trips_through_snapshot():
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    b = Building(id="bld_x", name="Hall", kind="workshop", location="plaza",
                 position=(3.5, -2.0))
    w.buildings[b.id] = b
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert restored.buildings["bld_x"].position == (3.5, -2.0)


def test_old_snapshot_without_position_restores_none():
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    w.buildings["bld_x"] = Building(id="bld_x", name="Hall", kind="workshop",
                                    location="plaza")
    snap = w.to_snapshot()
    for d in snap.get("buildings", []):
        d.pop("position", None)                    # a pre-F1 snapshot
    restored = World.from_snapshot(snap, params=_params())
    assert restored.buildings["bld_x"].position is None   # deterministic default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_position_field.py -v`
Expected: FAIL — `Building.__init__() got an unexpected keyword argument 'position'`.

- [ ] **Step 3: Add the field**

In `backend/petridish/engine/world.py`, in the `Building` dataclass, after the `zone_id` field (~`761`):

```python
    # EM-268 (F1) — deterministic WORLD-frame placement (±32.5), set at build
    # time by engine.placement (or derived on load for pre-F1 buildings).
    # Serialized in to_dict + restored in from_snapshot ONLY when set, so pre-F1
    # snapshots are byte-identical. None ⇒ frontend falls back to assignBuildingLots.
    position: tuple[float, float] | None = None
```

- [ ] **Step 4: Serialize when set** — in `Building.to_dict`, after the `zone_id` block (~`795`):

```python
        # EM-268 (F1) — world-frame position rides the shape ONLY when set, so a
        # pre-F1 build (or the flag off) serializes byte-identically.
        if self.position:
            d["position"] = [self.position[0], self.position[1]]
```

- [ ] **Step 5: Restore when present** — in `from_snapshot`, in the `Building(...)` restore (~`8277`, after `zone_id=`):

```python
                # EM-268 (F1) — restore world-frame position (pre-F1 snapshots
                # lack the key ⇒ None, byte-identical default; migration fills it).
                position=((float(d["position"][0]), float(d["position"][1]))
                          if isinstance(d.get("position"), (list, tuple))
                          and len(d["position"]) == 2 else None),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_position_field.py -v`
Expected: PASS (3 tests).

- [ ] **Step 7: Commit** — `test: EM-268 F1 Building.position field + snapshot round-trip`

---

### Task 2: Accretion placement module (pure fn)

**Files:**
- Create: `backend/petridish/engine/placement.py`
- Test: `backend/tests/test_free_placement_accretion.py`

**Interfaces:**
- Produces: `place_all(buildings, anchor, city_seed) -> dict[str, tuple[float,float]]`; `place_one(building, all_buildings, anchor, city_seed) -> tuple[float,float]`; `MIN_SPACING: float`. `buildings` items need `.id: str` and `.created_tick: int`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_free_placement_accretion.py
"""EM-268 F1 — cluster-accretion placement is deterministic, append-stable,
clumpy, overlap-free (EM-155)."""
import math
from dataclasses import dataclass
from petridish.engine.placement import place_all, place_one, MIN_SPACING

ANCHOR = (0.0, 0.0)
SEED = 1337


@dataclass
class B:
    id: str
    created_tick: int


def _set(n, start_tick=0):
    # distinct ticks ⇒ deterministic canonical order without relying on id hashing
    return [B(id=f"bld_{i:03d}", created_tick=start_tick + i) for i in range(n)]


def test_deterministic_same_inputs_same_positions():
    a = place_all(_set(20), ANCHOR, SEED)
    b = place_all(_set(20), ANCHOR, SEED)
    assert a == b


def test_input_order_independent():
    s = _set(20)
    forward = place_all(s, ANCHOR, SEED)
    reverse = place_all(list(reversed(s)), ANCHOR, SEED)
    assert forward == reverse            # canonical sort ⇒ order-independent


def test_first_building_near_anchor():
    pos = place_all(_set(1), ANCHOR, SEED)["bld_000"]
    assert math.dist(pos, ANCHOR) <= MIN_SPACING


def test_append_only_growth_never_moves_existing():
    small = place_all(_set(10), ANCHOR, SEED)
    grown = place_all(_set(11), ANCHOR, SEED)   # one more, latest tick ⇒ sorts last
    for k in small:
        assert grown[k] == small[k]             # existing positions frozen


def test_min_spacing_no_exact_stacking():
    pos = list(place_all(_set(40), ANCHOR, SEED).values())
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            assert pos[i] != pos[j]             # never identical coords


def test_forms_more_than_one_clump():
    # Preferential attachment ⇒ hamlets, not a single tight blob nor a uniform ring.
    pos = list(place_all(_set(60), ANCHOR, SEED).values())
    xs = [p[0] for p in pos]
    zs = [p[1] for p in pos]
    spread = max(max(xs) - min(xs), max(zs) - min(zs))
    assert spread > 4 * MIN_SPACING            # the city spreads out (not one blob)


def test_place_one_equals_place_all_slice():
    s = _set(15)
    full = place_all(s, ANCHOR, SEED)
    last = s[-1]
    assert place_one(last, s, ANCHOR, SEED) == full[last.id]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_accretion.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'petridish.engine.placement'`.

- [ ] **Step 3: Write the module**

```python
# backend/petridish/engine/placement.py
"""EM-268 F1 — deterministic organic building placement (cluster accretion).

Buildings sprawl the open map and clump into hamlets. Placement is a PURE
function of (building set, anchor, city_seed): canonical (created_tick, id)
ordering makes it input-order-independent and append-only-stable — a new build
sorts LAST and never moves an existing one. All math is in the WORLD frame
(±32.5), the frame citygraph nodes and assignBuildingLots already use, so nothing
is ever converted. Every random draw is seeded via citygraph._seeded_unit →
replay/fork byte-identical (EM-155). See
docs/superpowers/specs/2026-07-04-free-placement-f1-organic-accretion-design.md.
"""
from __future__ import annotations

import math

from .citygraph import _seeded_unit

# WORLD-frame tuning constants (±32.5 spans the map). Aesthetic knobs; pure fn,
# cheap to retune. MIN_SPACING = min centers gap; NEIGHBOR_R = clump radius.
MIN_SPACING: float = 1.6
NEIGHBOR_R: float = 4.0
_OVERLAP_CAP: int = 48
_GOLDEN_ANGLE: float = 2.399963229728653   # radians; deterministic spiral spread
_TAU: float = 2.0 * math.pi


def _u(seed: int, bid: str, purpose: str) -> float:
    return _seeded_unit(seed, f"{bid}:{purpose}")


def _pref_attach(placed: list[tuple[str, float, float]], seed: int,
                 bid: str) -> tuple[float, float]:
    """Pick a parent among already-placed buildings, weighted by local density
    (1 + neighbors within NEIGHBOR_R) — rich-get-richer ⇒ hamlets. Iterates the
    id-ordered `placed` list only (never a set/dict ⇒ no hash-order drift)."""
    weights: list[float] = []
    total = 0.0
    r2 = NEIGHBOR_R * NEIGHBOR_R
    for i, (_pid, px, pz) in enumerate(placed):
        n = 0
        for j, (_qid, qx, qz) in enumerate(placed):
            if i != j and (px - qx) * (px - qx) + (pz - qz) * (pz - qz) <= r2:
                n += 1
        w = 1.0 + float(n)
        weights.append(w)
        total += w
    pick = _u(seed, bid, "parent") * total
    acc = 0.0
    for (_pid, px, pz), w in zip(placed, weights):
        acc += w
        if pick <= acc:
            return (px, pz)
    return (placed[-1][1], placed[-1][2])   # float-drift guard: last on fallthrough


def _resolve_overlap(cand: tuple[float, float],
                     placed: list[tuple[str, float, float]],
                     seed: int, bid: str) -> tuple[float, float]:
    """Nudge cand outward on a seeded spiral until MIN_SPACING-clear, capped then
    accepted (deterministic + terminating; a choked cluster is a finding, not a bug)."""
    cx, cz = cand
    base = _u(seed, bid, "spiral") * _TAU
    s2 = MIN_SPACING * MIN_SPACING
    x, z = cx, cz
    for step in range(_OVERLAP_CAP):
        if all((x - px) * (x - px) + (z - pz) * (z - pz) >= s2 for (_pid, px, pz) in placed):
            return (x, z)
        r = MIN_SPACING * (1.0 + 0.5 * (step + 1))
        ang = base + (step + 1) * _GOLDEN_ANGLE
        x = cx + math.cos(ang) * r
        z = cz + math.sin(ang) * r
    return (x, z)


def place_all(buildings, anchor: tuple[float, float],
              city_seed: int) -> dict[str, tuple[float, float]]:
    """World-frame position for every building. Pure fn of (set, anchor, seed);
    canonical (created_tick, id) order == creation order ⇒ append-only-stable."""
    ordered = sorted(buildings, key=lambda b: (int(b.created_tick), str(b.id)))
    ax, az = anchor
    placed: list[tuple[str, float, float]] = []
    out: dict[str, tuple[float, float]] = {}
    for i, b in enumerate(ordered):
        bid = str(b.id)
        if i == 0:
            x = ax + (_u(city_seed, bid, "jx") - 0.5) * MIN_SPACING
            z = az + (_u(city_seed, bid, "jz") - 0.5) * MIN_SPACING
        else:
            px, pz = _pref_attach(placed, city_seed, bid)
            ang = _u(city_seed, bid, "ang") * _TAU
            dist = MIN_SPACING * (1.0 + _u(city_seed, bid, "dist"))
            x, z = _resolve_overlap((px + math.cos(ang) * dist, pz + math.sin(ang) * dist),
                                    placed, city_seed, bid)
        placed.append((bid, x, z))
        out[bid] = (x, z)
    return out


def place_one(building, all_buildings, anchor: tuple[float, float],
              city_seed: int) -> tuple[float, float]:
    """Position for one building given the full current set (which includes it).
    Equivalent to place_all — the newest build sorts last — so live-incremental
    and migration-batch agree (the R3 equivalence)."""
    return place_all(all_buildings, anchor, city_seed)[str(building.id)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_accretion.py -v`
Expected: PASS (7 tests). If `test_forms_more_than_one_clump` is flaky on the spread threshold, it is a *tuning* signal, not a determinism failure — adjust `NEIGHBOR_R`/threshold, never the seed.

- [ ] **Step 5: Commit** — `feat: EM-268 F1 cluster-accretion placement module`

---

### Task 3: `FREE_PLACEMENT_ENABLED` flag + build-time storage

**Files:**
- Modify: `backend/petridish/agents/runtime.py` (add flag, near `GRAPH_ZONES_ENABLED` ~`961`)
- Modify: `backend/petridish/engine/world.py` (build mint site ~`4910`)
- Test: `backend/tests/test_free_placement_build_time.py`

**Interfaces:**
- Consumes: `place_one` (Task 2), `Building.position` (Task 1).
- Produces: `agents.runtime.FREE_PLACEMENT_ENABLED: bool`; a built building carries `position` when the flag is on.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_free_placement_build_time.py
"""EM-268 F1 — a build stores a world-frame position when the flag is on."""
import petridish.agents.runtime as rt
from petridish.engine.placement import place_all
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _world():
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    return World(params=p,
                 places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
                 agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                    location="plaza", energy=80.0, credits=20)])


def _build(w):
    a = w.agents["a"]
    w.propose_building(a, kind="workshop", name="Hall", location="plaza")


def test_flag_on_stores_position(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world()
    _build(w)
    b = next(iter(w.buildings.values()))
    assert b.position is not None
    # matches the pure fn over the full set (anchor = world origin)
    assert b.position == place_all(w.buildings.values(), (0.0, 0.0), w.city_seed)[b.id]


def test_flag_off_leaves_position_none(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", False)
    w = _world()
    _build(w)
    assert next(iter(w.buildings.values())).position is None   # byte-identical
```

> Note: confirm the exact build entry point (`propose_building` vs `build`) at the mint site `world.py:4895` during Step 3; adjust `_build` to the real reflex name. The assertion is what matters.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_build_time.py -v`
Expected: FAIL — `AttributeError: module 'petridish.agents.runtime' has no attribute 'FREE_PLACEMENT_ENABLED'`.

- [ ] **Step 3: Add the flag** — in `backend/petridish/agents/runtime.py`, beside `GRAPH_ZONES_ENABLED` (~`961`):

```python
# EM-268 (F1) — agent-controlled FREE building placement. Default OFF ⇒ buildings
# carry no position ⇒ frontend falls back to assignBuildingLots (byte-identical to
# pre-F1). Flip ON (with the frontend FREE_PLACEMENT_ENABLED) after the visual
# sign-off to activate deterministic cluster-accretion placement.
FREE_PLACEMENT_ENABLED = False
```

- [ ] **Step 4: Store position at build time** — in `world.py`, immediately after `self.buildings[building.id] = building` (`4910`):

```python
        # EM-268 (F1) — deterministic world-frame placement, stored at build time
        # (flag off ⇒ None ⇒ byte-identical). Lazy import mirrors the GRAPH_ZONES
        # pattern (avoids the engine→agents cycle). Anchor = world origin (city
        # center). Placed over the FULL set incl. this build (it sorts last).
        from ..agents.runtime import FREE_PLACEMENT_ENABLED
        if FREE_PLACEMENT_ENABLED:
            from .placement import place_one
            building.position = place_one(building, list(self.buildings.values()),
                                          (0.0, 0.0), self.city_seed)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_build_time.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit** — `feat: EM-268 F1 flag + build-time position storage`

---

### Task 4: Migration derive-on-load

**Files:**
- Modify: `backend/petridish/engine/world.py` (`from_snapshot`, after the building-restore loop ~`8279`)
- Test: `backend/tests/test_free_placement_migration.py`

**Interfaces:**
- Consumes: `place_all` (Task 2), `Building.position` (Task 1), `FREE_PLACEMENT_ENABLED` (Task 3).
- Produces: on load with the flag on, every position-less building gets a deterministic position; already-positioned buildings are never overwritten.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_free_placement_migration.py
"""EM-268 F1 — derive-on-load fills missing positions == live incremental (R3),
never overwrites, keeps destroyed buildings as fixed parents, flag-off no-ops."""
import copy
import petridish.agents.runtime as rt
from petridish.engine.placement import place_all
from petridish.engine.world import World, Building, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world_with_buildings(positions):
    w = World(params=_params(),
              places=[PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")],
              agents=[AgentState(id="a", name="Ann", personality="", profile="mock",
                                 location="plaza", energy=80.0, credits=20)])
    for i, pos in enumerate(positions):
        w.buildings[f"bld_{i:03d}"] = Building(
            id=f"bld_{i:03d}", name="B", kind="workshop", location="plaza",
            created_tick=i, position=pos)
    return w


def test_pre_f1_snapshot_derives_all_positions(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([None, None, None])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert all(b.position is not None for b in restored.buildings.values())
    # == a batch place_all over the set (anchor = origin)
    expect = place_all(restored.buildings.values(), (0.0, 0.0), restored.city_seed)
    for b in restored.buildings.values():
        assert b.position == expect[b.id]


def test_derive_on_load_equals_live_incremental(monkeypatch):
    # R3: a run where positions were set live must match one where they're derived.
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    live = _world_with_buildings([None, None, None])
    live_pos = place_all(live.buildings.values(), (0.0, 0.0), live.city_seed)
    for b in live.buildings.values():
        b.position = live_pos[b.id]
    # a pre-F1 snapshot of the SAME set with positions stripped
    stripped = _world_with_buildings([None, None, None])
    restored = World.from_snapshot(copy.deepcopy(stripped.to_snapshot()), params=_params())
    for b in restored.buildings.values():
        assert b.position == live_pos[b.id]


def test_existing_positions_never_overwritten(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", True)
    w = _world_with_buildings([(9.0, 9.0), None])   # one fixed, one missing
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert restored.buildings["bld_000"].position == (9.0, 9.0)   # untouched
    assert restored.buildings["bld_001"].position is not None     # filled


def test_flag_off_is_a_noop(monkeypatch):
    monkeypatch.setattr(rt, "FREE_PLACEMENT_ENABLED", False)
    w = _world_with_buildings([None, None])
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_params())
    assert all(b.position is None for b in restored.buildings.values())  # byte-identical
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_migration.py -v`
Expected: FAIL — positions stay `None` (no migration yet).

- [ ] **Step 3: Add derive-on-load** — in `world.py`, after the `for d in state.get("buildings", ...)` restore loop closes (after `world.buildings[b.id] = b`, ~`8279`):

```python
        # EM-268 (F1) — derive-on-load migration: fill ONLY missing positions
        # (pre-F1 buildings), treating already-positioned ones as fixed parents;
        # NEVER overwrite. Destroyed buildings stay in the set as fixed parents
        # (they're never popped). Canonical order == creation order ⇒ this batch
        # equals what live-incremental produced (R3). Flag off ⇒ no-op (byte-id).
        from ..agents.runtime import FREE_PLACEMENT_ENABLED
        if FREE_PLACEMENT_ENABLED and any(
                b.position is None for b in world.buildings.values()):
            from .placement import place_all
            derived = place_all(world.buildings.values(), (0.0, 0.0), world.city_seed)
            for b in world.buildings.values():
                if b.position is None:
                    b.position = derived[b.id]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_free_placement_migration.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Backend determinism sweep** — run the full backend suite to prove flag-off byte-identity holds:

Run: `.venv/bin/python -m pytest backend/tests -q`
Expected: all pass, no golden regenerated.

- [ ] **Step 6: Commit** — `feat: EM-268 F1 derive-on-load position migration`

---

### Task 5: Frontend — `position` type, flag, render-from-position + fallback

**Files:**
- Modify: `web/src/types/index.ts` (`Building` ~`170`)
- Modify: `web/src/components/world3d/cityLayout.ts` (add `FREE_PLACEMENT_ENABLED` + `resolveBuildingPositions`)
- Modify: `web/src/components/world3d/CozyWorld.tsx` (`:50`, `:475-528` — call the wrapper)
- Test: `web/src/components/world3d/cityLayout.f1.test.ts`

**Interfaces:**
- Consumes: `Building.position` (backend contract, Task 1).
- Produces: `resolveBuildingPositions(plan, buildings, placeCenters) -> Map<string, {x,z}>` — identical to `assignBuildingLots` when the flag is off or a building lacks a position; overrides with `building.position` (world frame, no conversion) when on.

- [ ] **Step 1: Write the failing test**

```typescript
// web/src/components/world3d/cityLayout.f1.test.ts
import { describe, it, expect } from 'vitest';
import {
  computeCityPlan, assignBuildingLots, resolveBuildingPositions,
  FREE_PLACEMENT_ENABLED,
} from './cityLayout';
import type { Building } from '../../types';

const TOWN = [
  { id: 'plaza', name: 'Plaza', x: 500, y: 500, kind: 'social' },
  { id: 'market', name: 'Market', x: 300, y: 400, kind: 'commerce' },
];
const plan = computeCityPlan({ places: TOWN as any });
const centers = new Map(TOWN.map((p) => [p.id, { x: 0, z: 0 }]));

function mk(id: string, extra: Partial<Building> = {}): Building {
  return { id, name: id, kind: 'workshop', location: 'plaza', status: 'operational',
           ...extra } as Building;
}

describe('EM-268 F1 resolveBuildingPositions', () => {
  it('flag OFF ⇒ identical to assignBuildingLots (byte-identical)', () => {
    const bs = [mk('bld_a', { position: [3, -2] })];   // position present but flag off
    const viaWrapper = resolveBuildingPositions(plan, bs, centers);
    const viaBase = assignBuildingLots(plan, bs, centers);
    // Guard the invariant this test relies on:
    expect(FREE_PLACEMENT_ENABLED).toBe(false);
    expect([...viaWrapper.entries()]).toEqual([...viaBase.entries()]);
  });

  it('with a position + flag on ⇒ renders the world-frame position directly', () => {
    const b = mk('bld_a', { position: [7.5, -4.25] });
    const out = resolveBuildingPositions(plan, [b], centers, /* forceFlag */ true);
    expect(out.get('bld_a')).toEqual({ x: 7.5, z: -4.25 });   // no conversion
  });

  it('flag on but no position ⇒ falls back to assignBuildingLots', () => {
    const b = mk('bld_a');   // no position
    const out = resolveBuildingPositions(plan, [b], centers, true);
    const base = assignBuildingLots(plan, [b], centers);
    expect(out.get('bld_a')).toEqual(base.get('bld_a'));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `web/`): `/usr/local/bin/npx vitest run src/components/world3d/cityLayout.f1.test.ts`
Expected: FAIL — `resolveBuildingPositions`/`FREE_PLACEMENT_ENABLED` are not exported.

- [ ] **Step 3: Add the `position` field to the type** — in `web/src/types/index.ts`, inside `interface Building` (~`170`):

```typescript
  /** EM-268 (F1) — deterministic WORLD-frame placement (±32.5), set by the
   *  backend. Present only when free placement is active; absent ⇒ the frontend
   *  falls back to assignBuildingLots. Rendered directly (no logical conversion). */
  position?: [number, number];
```

- [ ] **Step 4: Add the flag + wrapper** — in `cityLayout.ts`, near `CARS_ENABLED` (`:635`):

```typescript
// EM-268 (F1) — the frontend half of backend FREE_PLACEMENT_ENABLED. Default
// OFF ⇒ resolveBuildingPositions === assignBuildingLots (byte-identical). Flip ON
// (with the backend flag) after the visual sign-off. Paired, like GRAPH_LOTS.
export const FREE_PLACEMENT_ENABLED = false;
```

And the wrapper (beside `assignBuildingLots`, after `:1217`):

```typescript
/** EM-268 (F1) — render entry point. When free placement is active AND a building
 *  carries a backend world-frame `position`, use it verbatim (no conversion — same
 *  frame as assignBuildingLots output). Every other building — and the whole map
 *  when the flag is off — routes through assignBuildingLots UNCHANGED, so the
 *  flag-off path is byte-identical to pre-F1. `forceFlag` is a test seam. */
export function resolveBuildingPositions(
  plan: Pick<CityPlan, 'realLots' | 'landmarks' | 'blockLots' | 'zones'>,
  buildings: ReadonlyArray<{ id: string; location: string; zone_id?: string | null; position?: [number, number] }>,
  placeCenters: ReadonlyMap<string, { x: number; z: number }>,
  forceFlag = false,
): Map<string, { x: number; z: number }> {
  const active = FREE_PLACEMENT_ENABLED || forceFlag;
  const positioned = active
    ? buildings.filter((b) => Array.isArray(b.position) && b.position.length === 2)
    : [];
  // Base path (byte-identical when nothing is positioned): the untouched lot claim.
  const out = assignBuildingLots(plan, buildings, placeCenters);
  for (const b of positioned) {
    out.set(b.id, { x: b.position![0], z: b.position![1] });
  }
  return out;
}
```

> Note: keep passing ALL buildings to `assignBuildingLots` (not just position-less ones) so its deterministic lot-claim order is unchanged; positioned buildings are then overridden. This preserves byte-identity for the position-less remainder.

- [ ] **Step 5: Wire the consumer** — in `CozyWorld.tsx`, import `resolveBuildingPositions` (`:50`) and replace the `assignBuildingLots(...)` call in the building-render memo (~`:475-528`) with `resolveBuildingPositions(...)`, passing the same args. Confirm no other production caller of `assignBuildingLots` exists:

Run: `grep -rn "assignBuildingLots(" web/src --include=*.tsx --include=*.ts | grep -v test`
Expected: only the CozyWorld call site (now switched) + the wrapper's internal call.

- [ ] **Step 6: Run tests + typecheck**

Run (from `web/`):
`/usr/local/bin/npx vitest run src/components/world3d/cityLayout.f1.test.ts src/components/world3d/cityLayout.test.ts`
Expected: PASS — the F1 file passes AND the existing `cityLayout.test.ts` oracle is unchanged (flag-off byte-identical).
Run: `/usr/local/bin/npx tsc -b --force`
Expected: rc=0.

- [ ] **Step 7: Commit** — `feat: EM-268 F1 frontend render-from-position + fallback`

---

### Task 6: Consumer audit (2D map + inspector)

**Files:**
- Modify (as needed): `web/src/components/map/WorldMap.tsx`, inspector building readers, `world3d/Traffic.tsx` (parked-cars), landmark placement.
- Test: extend `cityLayout.f1.test.ts` or add a focused test per consumer touched.

**Interfaces:**
- Consumes: `Building.position`. The 3D path needs no conversion (world frame); the 2D `WorldMap` minimap may need world→logical (`worldSpace.ts` inverse) if it plots in logical space.

- [ ] **Step 1: Enumerate consumers** — `grep -rn "\.location\b" web/src/components/map web/src/inspector | grep -i build` and inspect each reader of building placement. For each, decide: does it read a *position* or only a *place id*? Only position-readers need F1 wiring.

- [ ] **Step 2: For each real position-reader, write a failing test** asserting it renders `building.position` in that consumer's frame (add to `cityLayout.f1.test.ts` or a new `<Consumer>.f1.test.tsx`). If the audit finds NO other position-reader (likely — the 3D `CozyWorld` path was the only production `assignBuildingLots` caller), record that in the test file as a comment and skip to Step 4.

- [ ] **Step 3: Wire each consumer** through the correct frame; run its test to green.

- [ ] **Step 4: Frontend determinism sweep** — `/usr/local/bin/npx vitest run` (full) + `/usr/local/bin/npx tsc -b --force`. Expected: all pass, existing goldens unchanged.

- [ ] **Step 5: Commit** — `feat: EM-268 F1 route building consumers through position`

---

## Self-Review

- **Spec coverage:** position field (T1), accretion algorithm + determinism/append-stability/clumping/overlap (T2), flag + build-time storage (T3), derive-on-load migration + R3 equivalence + no-overwrite + destroyed-as-parents + flag-off no-op (T4), frontend render-from-position + fallback + flag-off byte-identical + sever-tie (T5), consumer audit incl. 2D map frame (T6). Byte-identical gate: flag-off sweeps in T4-S5 and T5-S6/T6-S4; golden reproducibility via `_det_uuid` noted in Global Constraints. ✅
- **Placeholder scan:** two explicit "confirm at implementation" notes (the build reflex name in T3-S1; the CozyWorld call site in T5-S5) are *locate steps with a grep*, not gaps — every code block is complete. ✅
- **Type consistency:** `place_all`/`place_one` signatures match across T2→T3→T4; `position: tuple[float,float]|None` (backend) ↔ `position?: [number,number]` (frontend) ↔ `"position": [x,z]` (wire) consistent; anchor `(0.0, 0.0)` and `self.city_seed` used identically at every backend call site. ✅

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-04-free-placement-f1.md`. Intended executor is the **orchestrator army** (contracts by file-ownership lane: `engine/placement.py` + `world.py` = sim-core lane; `agents/runtime.py` flag = runtime lane; frontend = ui lane; a QE lane for the determinism/byte-identical audit). Alternatively, subagent-driven-development per task. The `ROAD_MESH_ENABLED`-style visual sign-off (flip both `FREE_PLACEMENT_ENABLED` flags, watch a real accreted city render) is the standing user gate after the build is green.

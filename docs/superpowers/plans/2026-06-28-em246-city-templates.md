# EM-246 (S4) — City Templates / "City Profile" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Define the "city profile" — a named run-start template + params that seeds the initial `CityGraph` — so a run can start as a grid, a greenfield (near-empty), or a sparse village, with agents reshaping it from there.

**Architecture:** A `template(kind, seed, ...)` dispatcher in `citygraph.py` generalizes EM-239's frozen `classic_grid` call: `grid` → `classic_grid` (byte-identical default), `greenfield` → a minimal central plaza, `village` → a seeded-sparse axis-aligned grid. The profile is a `world.city` config block (`CityProfileParams`, mirroring `district_growth`) parsed in `config/loader.py`; `World.__init__` seeds `self.city_graph` from it. Pure function of `(kind, params, seed)` → identical start; the graph rides the snapshot so replay/fork are byte-identical (EM-155). The different starting cities render for free via the EM-243 graph-driven renderer — frontend gets only an additive `template` type field. Geometric presets (pentagon/radial/ring) need EM-245's `master_plan` library + EM-247 rendering, so they fall back to `grid` with a clear warning until then.

**Tech Stack:** Python 3.12 backend (pytest), TypeScript/R3F frontend (Vitest). EM-155 determinism.

## Global Constraints

- **Back-compat / byte-identical default.** No `city:` block (or `template: grid`) ⇒ `template("grid", city_seed)` ⇒ `classic_grid(city_seed)` ⇒ **byte-identical to today** (EM-239/EM-243 goldens hold). The `template` field added to `CityGraph` is additive (default `"grid"`); absent in old snapshots ⇒ `"grid"`.
- **Determinism / EM-155.** Every generator is a pure function of `(kind, seed, size, density)` — no clock/RNG; `village`'s sparsity uses a seeded hash (`hashlib`, stdlib). The seeded initial graph rides `to_snapshot`/`from_snapshot`. Same profile + seed ⇒ byte-identical start; replay/fork safe.
- **Layering.** `citygraph.py` stays config-free: `template()` takes primitives (`kind: str, seed: int, size: int, density: str`), NOT the config dataclass. `world.py` reads the profile from params and calls it.
- **One-road floor (EM-244).** Every shipped preset (incl. greenfield) yields ≥1 edge so the EM-244 demolish floor + the EM-243 empty-graph guard hold.
- **Scope (ship now):** `grid` / `greenfield` / `village` (axis-aligned). **Geometric presets (`pentagon`/`radial`/`ring`) fall back to `grid` + a logged warning** — they need EM-245 (generators) + EM-247 (rendering). `size` is honored by greenfield/village extent; `grid` stays canonical 5×5 (noted). The run-start picker UI + a visible template-name label are deferred (the renderer already shows the different city).
- **Toolchain:** backend `.venv/bin/python -m pytest <path> -q`; frontend `cd web && /usr/local/bin/npx vitest run <path>`; typecheck `cd web && /usr/local/bin/npx tsc -b --force`.

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `backend/petridish/engine/citygraph.py` | `template()` dispatcher + `_greenfield`/`_village` generators + `_seeded_unit`; `CityGraph.template` field | 1 |
| `backend/tests/test_citygraph.py` | Generator determinism/shape tests | 1 |
| `backend/petridish/config/loader.py` | `CityProfileParams` dataclass + `_parse_city_profile` + `WorldParams.city` field | 2 |
| `backend/petridish/config/world.yaml` (+ embedded default) | the `world.city` profile block | 2 |
| `backend/petridish/engine/world.py` | seed `city_graph` from the profile at init; set car_policy + template; geometric→grid warning | 3 |
| `backend/tests/test_city_templates.py` (new) | config→world-init seeding + determinism/snapshot acceptance | 2,3,5 |
| `web/src/types/index.ts` | additive `template?: string` on `CityGraph` | 4 |
| `web/src/components/world3d/cityLayout.test.ts` | greenfield near-empty renders without crash | 4 |

---

### Task 1: `template()` dispatcher + generators in `citygraph.py`

**Files:**
- Modify: `backend/petridish/engine/citygraph.py` (add `template` field to `CityGraph` + dispatcher/generators)
- Test: `backend/tests/test_citygraph.py`

**Interfaces:**
- Consumes: `CityGraph`, `CityNode`, `CityEdge`, `classic_grid`, `tile_center`, `_node_id`, `_ordered_edge`, `ROAD_TILE_INDICES`.
- Produces:
  - `CityGraph.template: str = "grid"` (new field; in `to_dict`/`from_dict`)
  - `TEMPLATE_KINDS: frozenset = frozenset({"grid", "greenfield", "village"})` (shippable now)
  - `template(kind: str, seed: int, *, size: int = 5, density: str = "medium") -> CityGraph` (dispatcher; unknown/geometric kind → `classic_grid` fallback, with `.template` recording the REQUESTED kind so the warning + UI reflect intent)

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_citygraph.py`:

```python
from petridish.engine.citygraph import template, TEMPLATE_KINDS


def test_template_grid_equals_classic_grid():
    g = template("grid", 1337)
    base = classic_grid(1337)
    # identical topology; template field records the kind
    assert [n.id for n in g.nodes] == [n.id for n in base.nodes]
    assert [e.id for e in g.edges] == [e.id for e in base.edges]
    assert g.template == "grid"


def test_template_greenfield_is_minimal_nonempty():
    g = template("greenfield", 1337)
    assert g.template == "greenfield"
    assert 1 <= len(g.edges) < len(classic_grid(1337).edges)   # minimal but ≥1 road
    assert len(g.nodes) >= 2
    # every edge endpoint resolves to a node (no dangling)
    ids = {n.id for n in g.nodes}
    assert all(e.a in ids and e.b in ids for e in g.edges)


def test_template_village_is_sparser_than_grid_and_connected_core():
    g = template("village", 1337, density="medium")
    full = classic_grid(1337)
    assert g.template == "village"
    assert 0 < len(g.edges) < len(full.edges)   # sparse
    ids = {n.id for n in g.nodes}
    assert all(e.a in ids and e.b in ids for e in g.edges)   # no dangling edges


def test_templates_are_pure_deterministic():
    for kind in ("grid", "greenfield", "village"):
        a = template(kind, 1337)
        b = template(kind, 1337)
        assert a.to_dict() == b.to_dict()
    # density changes village sparsity deterministically
    assert template("village", 1337, density="low").to_dict() != \
           template("village", 1337, density="high").to_dict()


def test_template_geometric_falls_back_to_grid_recording_kind():
    g = template("pentagon", 1337)
    base = classic_grid(1337)
    assert [e.id for e in g.edges] == [e.id for e in base.edges]   # grid topology
    assert g.template == "pentagon"   # records the requested kind (for the warning + UI)


def test_citygraph_template_field_round_trips():
    g = template("village", 1337)
    assert CityGraph.from_dict(g.to_dict()).template == "village"
    # absent template key in an old snapshot ⇒ 'grid'
    d = classic_grid(1337).to_dict()
    d.pop("template", None)
    assert CityGraph.from_dict(d).template == "grid"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: FAIL — `ImportError: cannot import name 'template'` (and `CityGraph` has no `template`).

- [ ] **Step 3: Add the `template` field + dispatcher/generators**

In `citygraph.py`, add `template` to the `CityGraph` dataclass (after `car_policy`):
```python
    template: str = "grid"  # EM-246 (S4) — the run-start profile kind (records intent)
```
Extend `to_dict` (add `"template": self.template`) and `from_dict` (`template=str(d.get("template", "grid"))`).

Append the dispatcher + generators:
```python
import hashlib

# EM-246 (S4): run-start templates. grid/greenfield/village ship now (axis-aligned);
# pentagon/radial/ring need EM-245 (master_plan) + EM-247 (meshing) → grid fallback.
TEMPLATE_KINDS: frozenset[str] = frozenset({"grid", "greenfield", "village"})
_DENSITY_KEEP: dict[str, float] = {"low": 0.4, "medium": 0.6, "high": 0.8}
# the central block's four corner indices (closest lattice lines to the origin)
_CENTRAL_IDX: tuple[int, int] = (-3, 2)


def _seeded_unit(seed: int, key: str) -> float:
    """Deterministic [0,1) from (seed, key) — stdlib sha1, pure (village sparsity)."""
    h = hashlib.sha1(f"{seed}:{key}".encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0x100000000


def _central_plaza_edges() -> list[tuple[int, int, int, int]]:
    """The four edges of the central block as (ia, ja, ib, jb) index pairs."""
    lo, hi = _CENTRAL_IDX
    return [
        (lo, lo, hi, lo), (lo, hi, hi, hi),  # south + north sides
        (lo, lo, lo, hi), (hi, lo, hi, hi),  # west + east sides
    ]


def _build_from_index_edges(seed: int, idx_edges, template_kind: str) -> CityGraph:
    """Assemble a CityGraph from (ia,ja,ib,jb) index-edge tuples — nodes derived
    from the endpoints, edges via _ordered_edge (classic_grid's id convention)."""
    nodes: dict[str, CityNode] = {}
    edges: list[CityEdge] = []
    seen: set[str] = set()
    for ia, ja, ib, jb in idx_edges:
        aid, bid = _node_id(ia, ja), _node_id(ib, jb)
        for nid, (i, j) in ((aid, (ia, ja)), (bid, (ib, jb))):
            if nid not in nodes:
                nodes[nid] = CityNode(id=nid, x=tile_center(i), z=tile_center(j))
        eid, a, b = _ordered_edge(aid, bid)
        if eid not in seen:
            seen.add(eid)
            edges.append(CityEdge(id=eid, a=a, b=b))
    return CityGraph(seed=int(seed), template=template_kind,
                     nodes=list(nodes.values()), edges=edges)


def _greenfield(seed: int) -> CityGraph:
    """Minimal: a single central-block plaza (4 nodes / 4 edges). Agents build the
    rest. Non-empty (one-road floor holds), the 'maybe they build nothing' start."""
    return _build_from_index_edges(seed, _central_plaza_edges(), "greenfield")


def _village(seed: int, density: str) -> CityGraph:
    """Sparse axis-aligned scatter: classic_grid's edges thinned by a seeded keep
    probability, with the central plaza always kept (connected, non-empty core).
    Organic (non-axis-aligned) village waits for S5a."""
    keep = _DENSITY_KEEP.get(density, 0.6)
    full = classic_grid(seed)
    core = {f"e:{_node_id(ia, ja)}->{_node_id(ib, jb)}"  # central edges (already _ordered in classic_grid order)
            for (ia, ja, ib, jb) in _central_plaza_edges()}
    # _ordered_edge gives the canonical id; recompute to match classic_grid's ids
    core = {(_ordered_edge(_node_id(ia, ja), _node_id(ib, jb))[0])
            for (ia, ja, ib, jb) in _central_plaza_edges()}
    kept = [e for e in full.edges
            if e.id in core or _seeded_unit(seed, f"village:{e.id}") < keep]
    keep_ids = {e.id for e in kept}
    live = {nid for e in kept for nid in (e.a, e.b)}
    nodes = [n for n in full.nodes if n.id in live]
    g = CityGraph(seed=int(seed), template="village", nodes=nodes,
                  edges=[e for e in full.edges if e.id in keep_ids])
    return g


def template(kind: str, seed: int, *, size: int = 5, density: str = "medium") -> CityGraph:
    """Build the run-start CityGraph for a city profile. grid/greenfield/village
    ship now; pentagon/radial/ring fall back to grid (need EM-245 + EM-247) but
    record the requested kind in `.template` so the caller can warn + the UI reflect
    intent. `size` is honored by greenfield/village extent (grid stays canonical)."""
    if kind == "grid":
        return classic_grid(seed)  # .template defaults to 'grid'
    if kind == "greenfield":
        return _greenfield(seed)
    if kind == "village":
        return _village(seed, density)
    # unknown / geometric: grid topology, but record the requested kind.
    g = classic_grid(seed)
    g.template = kind
    return g
```

> NOTE on `size`: the shippable presets currently ignore `size` beyond the central plaza (grid is canonical 5×5; greenfield is 1 block; village thins the 5×5). Keep the `size` param in the signature for forward-compat; honoring it for a generalized N×N grid is a recorded follow-up (don't generalize `classic_grid` here — that would risk the EM-155 byte-identical default).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest backend/tests/test_citygraph.py -q`
Expected: PASS (new + existing). (If the `village` test's central-core dedup is fiddly, simplify `_village` to compute `core` once via `_ordered_edge` — the second assignment above is the canonical one; delete the first.)

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/citygraph.py backend/tests/test_citygraph.py
git commit -m "feat(EM-246): template() dispatcher + greenfield/village generators + CityGraph.template (S4)"
```

---

### Task 2: `CityProfileParams` config block

**Files:**
- Modify: `backend/petridish/config/loader.py` (`CityProfileParams` dataclass mirroring `DistrictGrowthParams`; `WorldParams.city` field `~1584`; `_parse_city_profile` `~2076`; wire in the WorldParams builder `~2640`)
- Modify: `backend/petridish/config/world.yaml` (the `city:` block under `world:`) + the embedded default in `loader.py` (`~316`, near `city_seed`)
- Test: `backend/tests/test_city_templates.py` (new)

**Interfaces:**
- Consumes: the YAML `world.city` block.
- Produces: `WorldParams.city: CityProfileParams` with `template`, `size`, `density`, `car_policy` fields (seed reuses `world.city_seed`).

- [ ] **Step 1: Write the failing config test**

Create `backend/tests/test_city_templates.py`:

```python
from petridish.config.loader import load_config, CityProfileParams


def test_default_config_city_profile_is_grid():
    cfg = load_config()
    assert isinstance(cfg.world.city, CityProfileParams)
    assert cfg.world.city.template == "grid"        # back-compat default
    assert cfg.world.city.car_policy == "cars"


def test_city_profile_parses_fields(tmp_path):
    # mirror how other loader tests build a config dict (grep test_*loader* / conftest);
    # assert a world.city block parses template/size/density/car_policy.
    from petridish.config.loader import _parse_city_profile
    p = _parse_city_profile({"template": "greenfield", "size": 7,
                             "density": "low", "car_policy": "pedestrian"})
    assert (p.template, p.size, p.density, p.car_policy) == ("greenfield", 7, "low", "pedestrian")


def test_city_profile_absent_block_defaults(tmp_path):
    from petridish.config.loader import _parse_city_profile
    p = _parse_city_profile(None)
    assert p.template == "grid" and p.density == "medium" and p.car_policy == "cars"
```

Run: `.venv/bin/python -m pytest backend/tests/test_city_templates.py -q`
Expected: FAIL — `cannot import name 'CityProfileParams'`.

- [ ] **Step 2: Add the dataclass + parser + wiring**

In `loader.py`, add (mirroring `DistrictGrowthParams`):
```python
@dataclass
class CityProfileParams:
    """EM-246 (S4) — the run-start city profile (config `world.city`). Seeds the
    initial CityGraph via citygraph.template(). Absent/empty ⇒ grid (byte-identical
    pre-EM-246). seed reuses world.city_seed."""
    template: str = "grid"      # grid|greenfield|village (pentagon|radial|ring → grid until EM-245)
    size: int = 5               # extent hint (greenfield/village); grid stays canonical
    density: str = "medium"     # low|medium|high — village sparsity
    car_policy: str = "cars"    # starting global graph car policy (S3a can change it)
```
`WorldParams` field (`~1584`, near `district_growth`):
```python
    city: CityProfileParams = field(default_factory=CityProfileParams)
```
Parser (near `_parse_district_growth`):
```python
def _parse_city_profile(raw: dict | None) -> "CityProfileParams":
    """Parse `world.city` (EM-246). Absent/malformed ⇒ grid defaults. template/
    density/car_policy clamp to known values (unknown template is KEPT — template()
    falls back to grid + warns, so a future preset name doesn't break the loader)."""
    if not isinstance(raw, dict):
        return CityProfileParams()
    d = CityProfileParams()
    template = str(raw.get("template", d.template)).strip().lower() or d.template
    density = str(raw.get("density", d.density)).strip().lower()
    if density not in ("low", "medium", "high"):
        density = d.density
    car_policy = str(raw.get("car_policy", d.car_policy)).strip().lower()
    if car_policy not in ("cars", "pedestrian", "mixed"):
        car_policy = d.car_policy
    try:
        size = max(1, int(raw.get("size", d.size)))
    except (TypeError, ValueError):
        size = d.size
    return CityProfileParams(template=template, size=size, density=density, car_policy=car_policy)
```
Wire it in the WorldParams builder (`~2640`, near `district_growth=_parse_district_growth(...)`):
```python
        city=_parse_city_profile(w.get("city")),
```
Embedded default YAML (`loader.py ~316`, near `city_seed: 1337`) and `config/world.yaml` under `world:`:
```yaml
  city:
    template: grid          # grid | greenfield | village (pentagon/radial/ring → grid until EM-245)
    size: 5
    density: medium
    car_policy: cars
```

- [ ] **Step 3: Run the config tests**

Run: `.venv/bin/python -m pytest backend/tests/test_city_templates.py -q`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/petridish/config/loader.py backend/petridish/config/world.yaml backend/tests/test_city_templates.py
git commit -m "feat(EM-246): world.city profile config block (CityProfileParams) (S4)"
```

---

### Task 3: Seed the initial graph from the profile in `World.__init__`

**Files:**
- Modify: `backend/petridish/engine/world.py` (the EM-239 seeding line `~1303`; import `template`; a `logger.warning` for geometric/unknown kinds)
- Test: `backend/tests/test_city_templates.py`

**Interfaces:**
- Consumes: `template` (Task 1); `params.city` (Task 2); `self.city_seed`.
- Produces: `World.city_graph` seeded from the profile, with `car_policy` + `template` set; a one-time warning when a geometric kind falls back to grid.

- [ ] **Step 1: Write the failing world-init test**

Add to `backend/tests/test_city_templates.py`:

```python
from petridish.engine.world import World
from petridish.engine.world import AgentState, PlaceState


def _world_with_profile(template_kind, density="medium", car_policy="cars"):
    cfg = load_config()
    cfg.world.city.template = template_kind
    cfg.world.city.density = density
    cfg.world.city.car_policy = car_policy
    places = [PlaceState(id=p.id, name=p.name, x=p.x, y=p.y, kind=p.kind,
                         description=p.description, district=p.district,
                         neighborhood_id=p.neighborhood_id, zone_kind=p.zone_kind)
              for p in cfg.places]
    agents = [AgentState(id=f"agent_{a.name.lower()}", name=a.name,
                         personality=a.personality, profile=a.profile, location=a.location,
                         energy=cfg.world.starting_energy, credits=cfg.world.starting_credits)
              for a in cfg.agents]
    return World(params=cfg.world, places=places, agents=agents)


def test_world_seeds_greenfield_graph():
    w = _world_with_profile("greenfield")
    assert w.city_graph.template == "greenfield"
    from petridish.engine.citygraph import classic_grid
    assert len(w.city_graph.edges) < len(classic_grid(w.city_seed).edges)


def test_world_default_is_classic_grid_byte_identical():
    from petridish.engine.citygraph import classic_grid
    w = _world_with_profile("grid")
    assert w.city_graph.to_dict()["edges"] == classic_grid(w.city_seed).to_dict()["edges"]


def test_world_sets_initial_car_policy_from_profile():
    w = _world_with_profile("grid", car_policy="pedestrian")
    assert w.city_graph.car_policy == "pedestrian"


def test_world_geometric_template_falls_back_to_grid():
    w = _world_with_profile("pentagon")
    from petridish.engine.citygraph import classic_grid
    assert [e.id for e in w.city_graph.edges] == [e.id for e in classic_grid(w.city_seed).edges]
    assert w.city_graph.template == "pentagon"  # intent recorded


def test_seeded_graph_survives_snapshot_round_trip():
    w = _world_with_profile("village")
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()
```

Run: `.venv/bin/python -m pytest backend/tests/test_city_templates.py -q`
Expected: FAIL — world still hardcodes `classic_grid` (greenfield/car_policy assertions fail).

- [ ] **Step 2: Seed from the profile**

In `world.py`, extend the citygraph import to include `template`, and replace the EM-239 seeding line (`~1303`):
```python
        # EM-246 (S4) — seed the road graph from the run-start city profile
        # (config world.city). grid → classic_grid (byte-identical default);
        # greenfield/village ship now; geometric kinds fall back to grid + warn.
        _profile = _block_get(params, "city", None)
        _kind = getattr(_profile, "template", "grid") if _profile is not None else "grid"
        _density = getattr(_profile, "density", "medium") if _profile is not None else "medium"
        _size = getattr(_profile, "size", 5) if _profile is not None else 5
        self.city_graph: CityGraph = template(_kind, self.city_seed, size=_size, density=_density)
        if _kind not in ("grid", "greenfield", "village"):
            logger.warning(
                "city template %r needs EM-245 (S3b generators) + EM-247 (meshing) — "
                "starting on the grid; the requested kind is recorded for when they land.", _kind)
        _policy = getattr(_profile, "car_policy", "cars") if _profile is not None else "cars"
        if _policy in ("cars", "pedestrian", "mixed"):
            self.city_graph.car_policy = _policy
```
> Use the module's existing `logger` (grep `world.py` for `logger =` / `logging.getLogger`); if none, use `logging.getLogger(__name__)` at module top. `_block_get` is the existing defensive accessor used for `city_seed` (`world.py:1254`).

- [ ] **Step 3: Run the world tests + full backend suite**

Run: `.venv/bin/python -m pytest backend/tests/test_city_templates.py -q` then `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions vs the 1665 baseline (the default-grid path keeps every existing test byte-identical).

- [ ] **Step 4: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_city_templates.py
git commit -m "feat(EM-246): seed initial CityGraph from the world.city profile at init (S4)"
```

---

### Task 4: Frontend — additive `template` type + greenfield renders

The graph-driven renderer (EM-243) already shows whatever the graph contains — greenfield (sparse) and village render for free. The only required frontend change is type-correctness (the additive `template` field) + proving the near-empty greenfield graph renders without crashing.

**Files:**
- Modify: `web/src/types/index.ts` (`CityGraph` gains `template?: string`)
- Test: `web/src/components/world3d/cityLayout.test.ts`

- [ ] **Step 1: Add the additive type field**

In `web/src/types/index.ts`, `CityGraph`:
```typescript
export interface CityGraph {
  version: number;
  seed: number;
  car_policy: 'cars' | 'pedestrian' | 'mixed';
  template?: string; // EM-246 (S4) — run-start profile kind (read-only metadata)
  nodes: CityGraphNode[];
  edges: CityGraphEdge[];
}
```

- [ ] **Step 2: Write the greenfield-renders test**

Add to `cityLayout.test.ts` (mirror the EM-239/EM-243 fixture idiom): build a minimal greenfield-shaped graph (4 central-block nodes + 4 edges) and assert `computeCityPlan` returns a valid plan (no crash, road tiles present for the plaza, no throw on the near-empty graph). Run it.

```typescript
describe('EM-246 (S4): greenfield / near-empty graph renders without crashing', () => {
  it('a minimal central-plaza graph computes a valid plan', () => {
    const g = {
      version: 1, seed: 1337, car_policy: 'cars' as const, template: 'greenfield',
      nodes: [
        { id: 'n:-3:-3', x: (-3 + 0.5) * 2.6, z: (-3 + 0.5) * 2.6, kind: 'junction' as const },
        { id: 'n:2:-3', x: (2 + 0.5) * 2.6, z: (-3 + 0.5) * 2.6, kind: 'junction' as const },
        { id: 'n:-3:2', x: (-3 + 0.5) * 2.6, z: (2 + 0.5) * 2.6, kind: 'junction' as const },
        { id: 'n:2:2', x: (2 + 0.5) * 2.6, z: (2 + 0.5) * 2.6, kind: 'junction' as const },
      ],
      edges: [
        { id: 'e:n:-3:-3->n:2:-3', a: 'n:-3:-3', b: 'n:2:-3', road_class: 'street' as const, car_policy: 'inherit' as const },
        { id: 'e:n:-3:2->n:2:2', a: 'n:-3:2', b: 'n:2:2', road_class: 'street' as const, car_policy: 'inherit' as const },
        { id: 'e:n:-3:-3->n:-3:2', a: 'n:-3:-3', b: 'n:-3:2', road_class: 'street' as const, car_policy: 'inherit' as const },
        { id: 'e:n:2:-3->n:2:2', a: 'n:2:-3', b: 'n:2:2', road_class: 'street' as const, car_policy: 'inherit' as const },
      ],
    };
    const plan = computeCityPlan({ places: TOWN, city_seed: 1337, city_graph: g });
    expect(plan).toBeTruthy();
    // the plaza renders some road tiles; far less than a full grid (greenfield is sparse)
  });
});
```
> Match the real `computeCityPlan` call idiom + fixture names (grep the EM-239/EM-243 blocks). If the near-empty graph reveals a real crash in any derivation, FIX it (greenfield safety is the spec's §6 acceptance).

- [ ] **Step 3: Run frontend tests + typecheck**

Run: `cd web && /usr/local/bin/npx vitest run src/components/world3d && /usr/local/bin/npx tsc -b --force`
Expected: PASS + exit 0, 0 regressions (the additive field + a new test; default render byte-identical).

- [ ] **Step 4: Commit**

```bash
git add web/src/types/index.ts web/src/components/world3d/cityLayout.test.ts
git commit -m "feat(EM-246): additive CityGraph.template type + greenfield-renders test (S4)"
```

---

### Task 5: Determinism / acceptance

**Files:**
- Test: `backend/tests/test_city_templates.py`

- [ ] **Step 1: Acceptance tests**

Add: each preset deterministic per `(kind, seed)` (already in Task 1 for the generators; here at the World level — two worlds with the same profile have identical `city_graph.to_dict()`); the greenfield world drives `build_nearby_layout` without crashing (near-empty perception safe — spec §6); the village world's graph is sparser than grid and snapshot-round-trips.

```python
def test_same_profile_two_worlds_identical_graph():
    a = _world_with_profile("village", density="low")
    b = _world_with_profile("village", density="low")
    assert a.city_graph.to_dict() == b.city_graph.to_dict()


def test_greenfield_perception_does_not_crash():
    from petridish.agents.runtime import build_nearby_layout
    w = _world_with_profile("greenfield")
    place = next(iter(w.places.values()))
    # near-empty graph: perception returns a string or None, never raises
    line = build_nearby_layout(w, place)
    assert line is None or isinstance(line, str)
```

- [ ] **Step 2: Full backend suite (regression)**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS, 0 regressions vs 1665.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_city_templates.py
git commit -m "test(EM-246): preset determinism + greenfield perception-safety acceptance (S4)"
```

---

## Self-Review

**1. Spec coverage (S4):**
- §3 city profile (template/size/density/car_policy/seed) → Task 2 (`CityProfileParams`, seed reuses `city_seed`). ✅
- §3 preset set: grid/greenfield/village ship → Task 1; pentagon/radial/ring → grid fallback + warning (deferred to EM-245/247), intent recorded → Task 1 + Task 3. ✅
- §4 determinism (pure fn of profile; replay/fork) → Tasks 1, 5. Backend dispatcher; config block; world-init seeding. ✅
- §4 frontend (surface template name) → Task 4 ships the additive `template` field (data); the visible label/picker is deferred (recorded). The different city renders for free. ✅
- §6 greenfield near-empty safety → Task 4 (render) + Task 5 (perception). ✅

**2. Placeholder scan:** The two FILL points (Task 2 config-dict test idiom; Task 4 `computeCityPlan` call idiom) are "grep the real pattern and mirror" — surrounding code exact. The `_village` `core` double-assignment is explicitly flagged to collapse to the canonical `_ordered_edge` one. No TBD/"handle errors". ✅

**3. Type consistency:** `template(kind, seed, *, size, density) -> CityGraph`; `CityGraph.template: str = "grid"` (backend) ↔ `template?: string` (frontend); `CityProfileParams(template, size, density, car_policy)`; `TEMPLATE_KINDS`/`_DENSITY_KEEP` consistent; fallback records the requested kind everywhere. ✅

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-28-em246-city-templates.md`. Built via **/orchestrator ultracode** (Workflow mode) per the session goal. Backend-heavy (Tasks 1–3, 5) + a tiny frontend slice (Task 4). Geometric presets (pentagon/radial/ring), the `size`-scaled grid, and the visible template-name UI label are honestly deferred (recorded) — the geometric presets complete when EM-245 lands its generator library + EM-247 renders arbitrary geometry.

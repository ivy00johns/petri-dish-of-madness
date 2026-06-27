# Crime & Justice Engine Implementation Plan (EM-240)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a self-balancing crime↔justice subsystem — criminals commit a richer menu of crimes, witnessed crime accrues notoriety, enforcers investigate/accuse/detain or escalate to a town-hall trial, conviction means jail + restitution — plus the persona `disposition`/`role` schema it introduces.

**Architecture:** Pure additive engine work in `backend/petridish/engine/world.py` (state + actions), `backend/petridish/agents/runtime.py` (registry + validation + prompt), with config in `config/world.yaml`. Every crime/justice verb is a reflex-tier action chosen by the agent's normal LLM turn (zero extra model calls). Trials reuse the existing governance vote machinery as a new rule `effect`. Jail is a place + a validator gate. Status decay/release rides a new per-round `advance_crime()` beside `advance_buildings()`.

**Tech Stack:** Python 3 / FastAPI backend, `dataclass` world model, pytest (hermetic, `:memory:` DB). No new dependencies.

## Global Constraints

Copied verbatim from the spec (`docs/superpowers/specs/2026-06-24-crime-and-justice-engine-design.md`). Every task's requirements implicitly include these:

- **Byte-identical serialization.** A pre-EM-240 world's `AgentState.to_dict()` output must be unchanged. Every new field serializes **only when non-default** (the `demoted_from`/`plan`/`parents` pattern at `world.py:214-232`) and restores to its default when absent (`from_snapshot`, `world.py:4539-4573`).
- **Determinism (EM-155).** No `random` module and no wall-clock reads in engine paths; replay/fork must reproduce. The crime logic here is fully deterministic (no RNG needed) — keep it that way.
- **Zero extra LLM calls per action.** Every new crime/justice verb is registered `tier: "reflex"` in `TOOL_REGISTRY`. The agent's normal decision turn is the only model call.
- **Defaulted config.** All tunables live in a new `crime:` block in `config/world.yaml`. An absent block ⇒ every default ⇒ existing worlds run unchanged. Read defensively via a `_crime_param()` accessor (the `_rel_param`/`_bld_param` pattern).
- **Enforcement at resolution time.** Enforcer-only verbs and jail restrictions are enforced in `_validate_world` (`runtime.py:1210`) — prompt-only gating is not enforcement (the EM-108 lesson) — AND mirrored in the `_assemble_context` menu so menu and resolution agree.
- **Crime is available to everyone**, gated only by active ban rules. `disposition` biases the prompt, not the menu. Only `role: enforcer` gates the justice verbs.
- **Tests are hermetic.** `conftest.py` pins `EM_DB_PATH=:memory:`. Build worlds via the `World(params=..., places=[PlaceState(...)], agents=[AgentState(...)])` idiom from `tests/test_god_console.py:39-50`.

---

### Task 1: Persona `disposition`/`role` fields on `AgentState`

**Files:**
- Modify: `backend/petridish/engine/world.py` (`AgentState` dataclass ~145-188; `to_dict` ~190-233; `spawn_agent` ~4095-4124; `from_snapshot` agent restore ~4539-4573)
- Test: `backend/tests/test_em240_schema.py` (create)

**Interfaces:**
- Produces: `AgentState.disposition: str = "lawful"`, `AgentState.role: str = "citizen"`. `World.spawn_agent(name, personality, profile, location, cadence_tier="protagonist", disposition="lawful", role="citizen") -> AgentState`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_em240_schema.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world() -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [AgentState(id="ada", name="Ada", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20)]
    return World(params=_params(), places=places, agents=agents)


def test_disposition_role_default_and_omitted_from_to_dict():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    assert a.disposition == "lawful"
    assert a.role == "citizen"
    d = a.to_dict()
    # Byte-stability: defaults must NOT appear in the serialized dict.
    assert "disposition" not in d
    assert "role" not in d


def test_disposition_role_serialized_only_when_set():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20,
                   disposition="criminal", role="enforcer")
    d = a.to_dict()
    assert d["disposition"] == "criminal"
    assert d["role"] == "enforcer"


def test_spawn_agent_threads_disposition_and_role():
    world = _world()
    a = world.spawn_agent("Mona", "a fixer", "mock", "plaza",
                          disposition="criminal", role="citizen")
    assert a.disposition == "criminal"
    assert a.role == "citizen"
    # Round-trips through to_dict
    assert a.to_dict()["disposition"] == "criminal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_em240_schema.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'disposition'`.

- [ ] **Step 3: Add the fields, serialization, spawn threading, and restore**

In `world.py`, in the `AgentState` dataclass after `plan: dict | None = None` (line ~186), before `beliefs`:

```python
    # EM-240 — Crime & Justice persona schema. ADDITIVE with non-None defaults;
    # serialized ONLY when non-default (to_dict below), so a lawful citizen — and
    # every pre-EM-240 snapshot — keeps the exact prior dict shape.
    disposition: str = "lawful"   # lawful | opportunist | criminal — prompt bias only
    role: str = "citizen"         # citizen | enforcer — enforcer unlocks justice verbs
```

In `AgentState.to_dict`, just before `return d` (line ~233):

```python
        # EM-240 — only when non-default, so lawful citizens keep the pre-EM-240 shape.
        if self.disposition != "lawful":
            d["disposition"] = self.disposition
        if self.role != "citizen":
            d["role"] = self.role
```

In `spawn_agent` (line ~4095), extend the signature and the constructor:

```python
    def spawn_agent(
        self,
        name: str,
        personality: str,
        profile: str,
        location: str,
        cadence_tier: str = "protagonist",
        disposition: str = "lawful",
        role: str = "citizen",
    ) -> AgentState:
```

and in the `AgentState(...)` it builds (line ~4105), after the `cadence_tier=` argument:

```python
            disposition=disposition if disposition in ("lawful", "opportunist", "criminal") else "lawful",
            role=role if role in ("citizen", "enforcer") else "citizen",
```

In `from_snapshot`'s agent restore (line ~4539, inside the `AgentState(...)` call, after `plan=normalize_plan(d.get("plan")),`):

```python
                # EM-240 — additive: pre-EM-240 snapshots lack the keys and
                # restore the lawful/citizen defaults (unknown values fail-safe).
                disposition=(str(d.get("disposition")) if d.get("disposition")
                             in ("lawful", "opportunist", "criminal") else "lawful"),
                role=(str(d.get("role")) if d.get("role")
                      in ("citizen", "enforcer") else "citizen"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_em240_schema.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite to prove no regression (byte-stability)**

Run: `cd backend && python -m pytest -q`
Expected: PASS — no existing snapshot/serialization test breaks.

- [ ] **Step 6: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_em240_schema.py
git commit -m "feat: add persona disposition/role fields to AgentState (EM-240)"
```

---

### Task 2: Persona-card load + spawn-API plumbing for `disposition`/`role`

**Files:**
- Modify: `backend/petridish/config/loader.py` (`load_personas` ~1779-1815)
- Modify: `backend/petridish/api/app.py` (`SpawnBody` ~855-879; `_resolve_spawn_fields` ~882-905; the spawn endpoint's `spawn_agent(...)` call — find it after line 927)
- Test: `backend/tests/test_em240_schema.py` (append)

**Interfaces:**
- Consumes: `World.spawn_agent(..., disposition=, role=)` from Task 1.
- Produces: persona cards from `load_personas()` now carry `"disposition"` and `"role"` keys (defaulted). `_resolve_spawn_fields(body) -> tuple[str, str, str, str, str]` returning `(name, personality, profile, disposition, role)`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_em240_schema.py
def test_load_personas_defaults_disposition_role(tmp_path, monkeypatch):
    import petridish.config.loader as loader
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "personas.yaml").write_text(
        "personas:\n"
        "  - name: Crank\n"
        "    archetype: Racketeer\n"
        "    personality: shakes down stalls\n"
        "    suggested_profile: groq-llama\n"
        "    disposition: criminal\n"
        "  - name: Dot\n"
        "    archetype: Baker\n"
        "    personality: bakes bread\n"
    )
    monkeypatch.setattr(loader, "_find_config_dir", lambda: cfg)
    cards = {c["name"]: c for c in loader.load_personas()}
    assert cards["Crank"]["disposition"] == "criminal"
    assert cards["Crank"]["role"] == "citizen"          # defaulted
    assert cards["Dot"]["disposition"] == "lawful"      # defaulted
    assert cards["Dot"]["role"] == "citizen"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_em240_schema.py::test_load_personas_defaults_disposition_role -v`
Expected: FAIL — `KeyError: 'disposition'`.

- [ ] **Step 3: Implement the loader + API plumbing**

In `loader.py`, inside `load_personas`'s `out.append({...})` (line ~1809), add two keys (validate against the allowed sets, fail-soft to defaults):

```python
        out.append({
            "name": name,
            "archetype": str(c.get("archetype") or ""),
            "personality": str(c.get("personality") or ""),
            "suggested_profile": str(c.get("suggested_profile") or ""),
            # EM-240 — additive persona schema; unknown/absent → lawful/citizen.
            "disposition": (str(c.get("disposition") or "").strip().lower()
                            if str(c.get("disposition") or "").strip().lower()
                            in ("lawful", "opportunist", "criminal") else "lawful"),
            "role": (str(c.get("role") or "").strip().lower()
                     if str(c.get("role") or "").strip().lower()
                     in ("citizen", "enforcer") else "citizen"),
        })
```

In `app.py`, add two optional fields to `SpawnBody` (after `cadence_tier`, line ~875):

```python
    # EM-240 — optional crime-schema overrides; a persona card fills these in,
    # an explicit body wins. Unknown values fall back to lawful/citizen.
    disposition: str | None = Field(default=None, max_length=20)
    role: str | None = Field(default=None, max_length=20)
```

Replace `_resolve_spawn_fields` (line ~882) to also resolve disposition/role:

```python
def _resolve_spawn_fields(body: SpawnBody) -> tuple[str, str, str, str, str]:
    """Effective (name, personality, profile, disposition, role) for a spawn.

    Explicit body fields always win; a `persona` card fills the gaps; what is
    still missing after that is a 400 (unknown persona is a 400 too)."""
    name, personality, profile = body.name, body.personality, body.profile
    disposition, role = body.disposition, body.role
    if body.persona:
        wanted = body.persona.strip().lower()
        card = next(
            (c for c in load_personas() if c["name"].strip().lower() == wanted),
            None,
        )
        if card is None:
            raise HTTPException(400, f"Unknown persona: {body.persona!r}")
        name = name or card["name"]
        personality = personality or card["personality"]
        profile = profile or card["suggested_profile"] or None
        disposition = disposition or card.get("disposition")
        role = role or card.get("role")
    if not name:
        raise HTTPException(400, "name is required (directly or via persona)")
    if not profile:
        raise HTTPException(400, "profile is required (directly or via persona)")
    disposition = disposition if disposition in ("lawful", "opportunist", "criminal") else "lawful"
    role = role if role in ("citizen", "enforcer") else "citizen"
    return name, (personality or "A generic agent."), profile, disposition, role
```

Find the spawn endpoint's call to `_resolve_spawn_fields` / `spawn_agent` (after line 927) and update the unpack + pass-through. The current call unpacks three values; change it to five and forward them:

```python
    name, personality, profile, disposition, role = _resolve_spawn_fields(body)
    # ... existing tier resolution ...
    agent = _world.spawn_agent(
        name, personality, profile, location,
        cadence_tier=tier, disposition=disposition, role=role,
    )
```

> NOTE: if other call sites unpack `_resolve_spawn_fields` (e.g. the A/B `ab_models` path), update each to the 5-tuple. Grep first: `grep -n "_resolve_spawn_fields" backend/petridish/api/app.py`.

- [ ] **Step 4: Run test + full suite**

Run: `cd backend && python -m pytest tests/test_em240_schema.py -v && python -m pytest -q`
Expected: PASS. (If an A/B spawn test fails on the tuple change, fix that call site to unpack 5 values.)

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/config/loader.py backend/petridish/api/app.py backend/tests/test_em240_schema.py
git commit -m "feat: load and spawn personas with disposition/role (EM-240)"
```

---

### Task 3: Crime status scalars on `AgentState`

**Files:**
- Modify: `backend/petridish/engine/world.py` (`AgentState` ~145-188; `to_dict` ~190-233; `from_snapshot` ~4539-4573)
- Test: `backend/tests/test_em240_schema.py` (append)

**Interfaces:**
- Produces: `AgentState.notoriety: int = 0`, `AgentState.crime_status: str | None = None`, `AgentState.crime_status_until_tick: int = 0`, `AgentState.rap_sheet: list[dict] = []`.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_em240_schema.py
def test_crime_scalars_default_and_omitted():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    assert a.notoriety == 0
    assert a.crime_status is None
    assert a.crime_status_until_tick == 0
    assert a.rap_sheet == []
    d = a.to_dict()
    for k in ("notoriety", "crime_status", "crime_status_until_tick", "rap_sheet"):
        assert k not in d, f"{k} must be omitted at default for byte-stability"


def test_crime_scalars_serialized_when_set():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    a.notoriety = 42
    a.crime_status = "wanted"
    a.crime_status_until_tick = 99
    a.rap_sheet = [{"tick": 3, "crime": "heist", "victim_id": "y", "witnessed": True}]
    d = a.to_dict()
    assert d["notoriety"] == 42
    assert d["crime_status"] == "wanted"
    assert d["crime_status_until_tick"] == 99
    assert d["rap_sheet"][0]["crime"] == "heist"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_em240_schema.py::test_crime_scalars_default_and_omitted -v`
Expected: FAIL — `AttributeError: 'AgentState' object has no attribute 'notoriety'`.

- [ ] **Step 3: Add the scalars, serialization, and restore**

In `AgentState`, after the `disposition`/`role` fields from Task 1 (keep them adjacent):

```python
    # EM-240 — crime status substrate. ALL additive, serialized only when set.
    notoriety: int = 0                       # 0..100; witnessed-crime heat, decays
    crime_status: str | None = None          # None|wanted|detained|jailed|exiled
    crime_status_until_tick: int = 0         # release tick for detained/jailed
    rap_sheet: list[dict] = field(default_factory=list)  # capped crime record
```

In `to_dict`, after the disposition/role block from Task 1:

```python
        if self.notoriety:
            d["notoriety"] = self.notoriety
        if self.crime_status is not None:
            d["crime_status"] = self.crime_status
            d["crime_status_until_tick"] = self.crime_status_until_tick
        if self.rap_sheet:
            d["rap_sheet"] = [dict(e) for e in self.rap_sheet]
```

In `from_snapshot`, after the disposition/role restore from Task 1:

```python
                notoriety=max(0, min(100, _int(d.get("notoriety")))),
                crime_status=(str(d.get("crime_status")) if d.get("crime_status")
                              in ("wanted", "detained", "jailed", "exiled") else None),
                crime_status_until_tick=_int(d.get("crime_status_until_tick")),
                rap_sheet=[dict(e) for e in (d.get("rap_sheet") or []) if isinstance(e, dict)],
```

- [ ] **Step 4: Run test + full suite**

Run: `cd backend && python -m pytest tests/test_em240_schema.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_em240_schema.py
git commit -m "feat: add notoriety/crime_status/rap_sheet to AgentState (EM-240)"
```

---

### Task 4: Crime config block + `_crime_param` accessor

**Files:**
- Modify: `config/world.yaml` (add a `crime:` block under the `world:` params, near `steal_max` line 27)
- Modify: `backend/petridish/engine/world.py` (add `_crime_param` beside `_rel_param` ~3519)
- Test: `backend/tests/test_em240_schema.py` (append)

**Interfaces:**
- Produces: `World._crime_param(name: str, default) -> Any` — reads `self.params.crime` (dataclass OR dict OR absent), returns `default` when missing.

- [ ] **Step 1: Write the failing test**

```python
# append to backend/tests/test_em240_schema.py
def test_crime_param_defaults_when_block_absent():
    world = _world()  # WorldParams() has no `crime` block
    assert world._crime_param("wanted_threshold", 40) == 40
    assert world._crime_param("detain_sentence", 6) == 6


def test_crime_param_reads_dict_block():
    world = _world()
    world.params.crime = {"wanted_threshold": 25}  # dict block, EM-155 convention
    assert world._crime_param("wanted_threshold", 40) == 25
    assert world._crime_param("detain_sentence", 6) == 6  # falls through to default
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_em240_schema.py::test_crime_param_defaults_when_block_absent -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute '_crime_param'`.

- [ ] **Step 3: Add the accessor and config**

In `world.py`, beside `_rel_param` (line ~3519):

```python
    def _crime_param(self, name: str, default: Any) -> Any:
        """Defensive accessor for the `world.crime` config block (dataclass OR
        dict OR absent — EM-155 conventions, like _rel_param/_bld_param). An
        absent block ⇒ every default ⇒ pre-EM-240 worlds are unchanged."""
        return _block_get(getattr(self.params, "crime", None), name, default)
```

In `config/world.yaml`, add under the `world:` params block (after `max_actions_per_turn`, line ~31). All values are first-pass defaults to tune against a live run:

```yaml
  # EM-240 — Crime & Justice tunables. Absent ⇒ engine defaults (pre-EM-240
  # behavior). Notoriety accrues from THIRD-PARTY-witnessed crime and decays
  # while lying low; crossing wanted_threshold flags an agent `wanted`.
  crime:
    wanted_threshold: 40           # notoriety → `wanted`
    detain_threshold: 60           # on-the-spot detain without a trial
    notoriety_decay: 2             # per round, while not jailed
    notoriety_per_extra_witness: 3 # added per witness beyond the first
    rap_sheet_cap: 10              # keep only the most recent N entries
    heist_max: 30                  # vs steal_max (8)
    heist_min_target_credits: 15   # a heist needs a worthwhile mark
    extort_max: 15
    vandalize_blackout_ticks: 8    # building blackout from vandalism
    vandalize_notoriety: 10
    heist_notoriety: 18
    extort_notoriety: 12
    steal_notoriety: 6             # folded into existing steal
    arson_notoriety: 22            # folded into existing arson
    bribe_efficacy: 0.75           # fraction of payer notoriety wiped
    bribe_notoriety: 14            # enforcer's notoriety gain if bribe witnessed
    launder_cut: 0.3               # fraction of laundered credits lost
    launder_notoriety_reduction: 8
    investigate_notoriety: 10      # added per unwitnessed crime confirmed
    conspiracy_notoriety: 6        # each conspirator on a sealed pact
    detain_sentence: 6             # ticks jailed by on-the-spot detain
    trial_sentence: 20             # ticks jailed by conviction
    trial_fine: 25                 # credits confiscated on conviction
    acquittal_notoriety_relief: 15 # notoriety cleared on acquittal
    accuser_acquittal_penalty: 8   # accuser trust hit from onlookers
    released_notoriety_relief: 10  # notoriety cleared on release
```

> NOTE: `WorldParams` ingests unknown YAML keys as a nested block already (the `relationships`/`children`/`animals` precedent). If your loader has an explicit allow-list for top-level `world:` keys, add `crime` there the same way those blocks are added. Verify with: `grep -n "relationships\|children\|animals" backend/petridish/config/loader.py | head`.

- [ ] **Step 4: Run test + confirm config loads**

Run: `cd backend && python -m pytest tests/test_em240_schema.py -v && python -c "from petridish.config.loader import load_config; load_config()"`
Expected: tests PASS; config import prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add config/world.yaml backend/petridish/engine/world.py backend/tests/test_em240_schema.py
git commit -m "feat: add crime config block and _crime_param accessor (EM-240)"
```

---

### Task 5: `_register_crime` + `advance_crime` + fold notoriety into steal/arson

**Files:**
- Modify: `backend/petridish/engine/world.py` (`action_steal` ~1437; `action_arson` ~2746; add helpers near `agents_at` ~3632)
- Modify: `backend/petridish/engine/loop.py` (advance seam ~1559-1569)
- Test: `backend/tests/test_em240_crimes.py` (create)

**Interfaces:**
- Produces:
  - `World._register_crime(actor: AgentState, crime: str, victim_id: str | None, notoriety_base: int) -> bool` — appends a `rap_sheet` entry, bumps `notoriety` when third-party-witnessed, flips `crime_status` to `"wanted"` at threshold. Returns `witnessed`. **Witnesses = co-located living agents other than the actor AND the direct victim** (so a theft with only the victim present is unwitnessed — the classic pickpocket; `investigate` later surfaces it).
  - `World.advance_crime() -> list[dict]` — per round: decay notoriety, clear stale `wanted`, release `detained`/`jailed` at expiry. Returns events to emit.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_em240_crimes.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="alley", name="Alley", x=5, y=0, kind="social"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def test_unwitnessed_crime_adds_no_notoriety_but_records_rap_sheet():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    world = _world([thief, victim])
    witnessed = world._register_crime(thief, "steal", victim.id, 6)
    assert witnessed is False               # only the victim present → not witnessed
    assert thief.notoriety == 0
    assert thief.rap_sheet[-1] == {"tick": 0, "crime": "steal",
                                   "victim_id": "victim", "witnessed": False}


def test_witnessed_crime_adds_notoriety_and_can_flip_wanted():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    bystander = _a("nosy", "alley")
    world = _world([thief, victim, bystander])
    world._register_crime(thief, "heist", victim.id, 45)
    assert thief.notoriety == 45
    assert thief.crime_status == "wanted"   # 45 >= wanted_threshold (40)


def test_advance_crime_decays_notoriety_and_clears_wanted():
    thief = _a("thief", "alley")
    thief.notoriety = 41
    thief.crime_status = "wanted"
    world = _world([thief])
    world.tick = 1
    world.advance_crime()                   # decay 2 → 39, below threshold
    assert thief.notoriety == 39
    assert thief.crime_status is None


def test_advance_crime_releases_jailed_at_expiry():
    con = _a("con", "jail")
    con.crime_status = "jailed"
    con.crime_status_until_tick = 5
    con.notoriety = 50
    world = _world([con])
    world.tick = 5
    events = world.advance_crime()
    assert con.crime_status is None
    assert con.notoriety == 40              # released_notoriety_relief (10) burned
    assert any(e["kind"] == "released" for e in events)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute '_register_crime'`.

- [ ] **Step 3: Implement the helpers and fold into steal/arson**

In `world.py`, near `agents_at` (line ~3632):

```python
    def _register_crime(
        self, actor: AgentState, crime: str, victim_id: str | None, notoriety_base: int
    ) -> bool:
        """EM-240 — shared crime bookkeeping. Witnesses = co-located living agents
        OTHER than the actor and the direct victim. Bumps notoriety only when
        witnessed; always records the rap sheet; flips `wanted` at threshold.
        Does NOT touch trust — each action keeps its own witness-trust deltas."""
        witnesses = [
            a for a in self.agents_at(actor.location)
            if a.id != actor.id and a.id != victim_id
        ]
        witnessed = len(witnesses) > 0
        if witnessed:
            per = int(self._crime_param("notoriety_per_extra_witness", 3))
            gain = int(notoriety_base) + per * (len(witnesses) - 1)
            actor.notoriety = max(0, min(100, actor.notoriety + gain))
        actor.rap_sheet.append({
            "tick": self.tick, "crime": crime,
            "victim_id": victim_id, "witnessed": witnessed,
        })
        cap = int(self._crime_param("rap_sheet_cap", 10))
        if len(actor.rap_sheet) > cap:
            del actor.rap_sheet[: len(actor.rap_sheet) - cap]
        threshold = int(self._crime_param("wanted_threshold", 40))
        if actor.crime_status is None and actor.notoriety >= threshold:
            actor.crime_status = "wanted"
        return witnessed

    def advance_crime(self) -> list[dict]:
        """EM-240 — per-round crime status maintenance (called from the loop beside
        advance_buildings). Decays notoriety while free, clears stale `wanted`, and
        releases detained/jailed agents at expiry. Deterministic; no RNG/clock."""
        events: list[dict] = []
        decay = int(self._crime_param("notoriety_decay", 2))
        threshold = int(self._crime_param("wanted_threshold", 40))
        relief = int(self._crime_param("released_notoriety_relief", 10))
        for agent in self.living_agents():
            # Release first (a freed agent then decays this round too).
            if agent.crime_status in ("detained", "jailed") and \
                    self.tick >= agent.crime_status_until_tick:
                agent.crime_status = None
                agent.crime_status_until_tick = 0
                agent.notoriety = max(0, agent.notoriety - relief)
                events.append({
                    "kind": "released",
                    "actor_id": agent.id,
                    "text": f"{agent.name} is released back into the town.",
                    "payload": {"notoriety": agent.notoriety},
                })
            # Decay only while free (jail is its own cool-off).
            if agent.crime_status in (None, "wanted") and agent.notoriety > 0:
                agent.notoriety = max(0, agent.notoriety - decay)
            # Clear a `wanted` flag that has cooled below threshold.
            if agent.crime_status == "wanted" and agent.notoriety < threshold:
                agent.crime_status = None
        return events
```

Fold into `action_steal` — just before `return True, "ok", amount` (line ~1461):

```python
        self._register_crime(agent, "steal", target.id,
                             int(self._crime_param("steal_notoriety", 6)))
```

Fold into `action_arson` — just before the `return {"_multi": [...]}` (line ~2767). Arson has no single victim, so `victim_id=None`:

```python
        self._register_crime(agent, "arson", None,
                             int(self._crime_param("arson_notoriety", 22)))
```

In `loop.py`, in the advance method, right after the `advance_buildings` block (after line ~1568, before `self._flush_spawn_events()` at 1569):

```python
        advance_crime = getattr(world, "advance_crime", None)
        if callable(advance_crime):
            try:
                for evt in advance_crime():
                    evt.setdefault("turn_id", None)
                    self._emit_event(evt)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("crime status advance failed: %s", exc)
```

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -v && python -m pytest -q`
Expected: PASS. Existing 2-agent steal/arson tests are unaffected (no third party present ⇒ no notoriety; trust deltas unchanged).

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/engine/loop.py backend/tests/test_em240_crimes.py
git commit -m "feat: add notoriety bookkeeping, decay/release, fold into steal/arson (EM-240)"
```

---

### Task 6: Offensive crime verbs — heist, extort, vandalize

**Files:**
- Modify: `backend/petridish/engine/world.py` (new actions near `action_steal` ~1461; add `ban_extortion`/`ban_vandalism` to `valid_effects` ~1958)
- Modify: `backend/petridish/agents/runtime.py` (`TOOL_REGISTRY` ~281-342; `_validate_world` ~1259 steal branch — add the new verbs)
- Test: `backend/tests/test_em240_crimes.py` (append)

**Interfaces:**
- Consumes: `_register_crime`, `_crime_param`, `_update_trust`, `_damage_building`, `has_active_rule`.
- Produces:
  - `World.action_heist(agent, target) -> tuple[bool, str, int]`
  - `World.action_extort(agent, target) -> tuple[bool, str, int]`
  - `World.action_vandalize(agent, building_id) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_em240_crimes.py
def test_heist_takes_more_than_steal_and_builds_notoriety_when_witnessed():
    robber = _a("robber", "alley"); robber.credits = 0
    mark = _a("mark", "alley"); mark.credits = 50
    eye = _a("eye", "alley")
    world = _world([robber, mark, eye])
    ok, reason, amount = world.action_heist(robber, mark)
    assert ok and reason == "ok"
    assert amount == 30                      # heist_max
    assert robber.credits == 30 and mark.credits == 20
    assert robber.notoriety == 18            # heist_notoriety, witnessed by `eye`


def test_heist_rejected_when_target_too_poor():
    robber = _a("robber", "alley")
    mark = _a("mark", "alley"); mark.credits = 5   # below heist_min_target_credits (15)
    world = _world([robber, mark])
    ok, reason, amount = world.action_heist(robber, mark)
    assert not ok and amount == 0


def test_extort_transfers_credits_and_snaps_rivalry():
    thug = _a("thug", "alley"); thug.credits = 0
    shop = _a("shop", "alley"); shop.credits = 40
    world = _world([thug, shop])
    ok, reason, amount = world.action_extort(thug, shop)
    assert ok and amount == 15               # extort_max
    assert thug.credits == 15 and shop.credits == 25
    # victim now sees the extorter as at least a rival
    assert shop.relationships[thug.id].type in ("rival", "enemy", "feud")


def test_vandalize_blacks_out_building_and_records_crime():
    from petridish.engine.world import Building  # adjust import to the real class
    vandal = _a("vandal", "plaza")
    world = _world([vandal])
    # Minimal building at the vandal's place — mirror how other building tests
    # construct one (see tests that touch action_arson / _damage_building).
    bld = world.buildings_seed_one("b1", "Stall", "plaza")  # helper added below if absent
    ok = world.action_vandalize(vandal, "b1")
    assert isinstance(ok, dict)
    assert world.buildings["b1"].blackout_until_tick > world.tick or \
           world.places["plaza"].blackout_until_tick > world.tick
    assert vandal.rap_sheet[-1]["crime"] == "vandalize"
```

> If there is no `buildings_seed_one` helper, construct a `Building` the way the existing arson tests do — grep `tests/test_*` for `action_arson(` to copy the exact constructor. Keep the vandalize assertion focused on `rap_sheet` + a blackout being set.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -k "heist or extort or vandalize" -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'action_heist'`.

- [ ] **Step 3: Implement the three actions + registry + validator + ban effects**

In `world.py`, after `action_steal` (line ~1461):

```python
    def action_heist(self, agent: AgentState, target: AgentState) -> tuple[bool, str, int]:
        """EM-240 — a big-score theft: up to heist_max (≫ steal_max), gated on a
        worthwhile mark. Same co-location + ban_stealing gate as steal; heavier
        notoriety. Victim trust craters like steal."""
        if self.has_active_rule("ban_stealing"):
            return False, "ban_stealing rule is active", 0
        if agent.location != target.location:
            return False, "target not co-located", 0
        if target.credits < int(self._crime_param("heist_min_target_credits", 15)):
            return False, "target not worth the risk", 0
        amount = min(target.credits, int(self._crime_param("heist_max", 30)))
        target.credits -= amount
        agent.credits += amount
        self._update_trust(agent, target, -20)
        self._update_trust(target, agent, -15)
        rel = target.relationships.get(agent.id)
        if rel is None or rel.type not in ("rival", "enemy", "feud"):
            if rel is None:
                rel = RelationshipState()
                target.relationships[agent.id] = rel
            rel.type = "enemy" if rel.trust < -20 else "rival"
            rel.since_tick = self.tick
        self._register_crime(agent, "heist", target.id,
                             int(self._crime_param("heist_notoriety", 18)))
        return True, "ok", amount

    def action_extort(self, agent: AgentState, target: AgentState) -> tuple[bool, str, int]:
        """EM-240 — threaten a co-located agent for credits (up to extort_max).
        Always snaps the victim's view to at least rival."""
        if agent.location != target.location:
            return False, "target not co-located", 0
        amount = min(target.credits, int(self._crime_param("extort_max", 15)))
        if amount <= 0:
            return False, "target has nothing to give", 0
        target.credits -= amount
        agent.credits += amount
        self._update_trust(target, agent, -18)
        rel = target.relationships.get(agent.id)
        if rel is None or rel.type not in ("rival", "enemy", "feud"):
            if rel is None:
                rel = RelationshipState()
                target.relationships[agent.id] = rel
            rel.type = "enemy" if rel.trust < -20 else "rival"
            rel.since_tick = self.tick
        self._register_crime(agent, "extort", target.id,
                             int(self._crime_param("extort_notoriety", 12)))
        return True, "ok", amount

    def action_vandalize(self, agent: AgentState, building_id: str) -> dict:
        """EM-240 — damage a building short of arson: a short blackout at its place,
        no health destruction. Witnesses lose trust (like arson)."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(agent.id, "vandalize", "building_not_found",
                                    f"{agent.name} tried to vandalize an unknown structure.")
        place = self.places.get(building.location)
        ticks = int(self._crime_param("vandalize_blackout_ticks", 8))
        if place is not None:
            place.blackout_until_tick = max(place.blackout_until_tick, self.tick + ticks)
        for witness in self.agents_at(building.location):
            if witness.id != agent.id:
                self._update_trust(witness, agent, -10)
        self._register_crime(agent, "vandalize", None,
                             int(self._crime_param("vandalize_notoriety", 10)))
        return {
            "kind": "crime_committed",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} vandalizes {building.name}!",
            "payload": {"action": "vandalize", "building_id": building.id,
                        "blackout_ticks": ticks},
        }
```

Add the two new ban effects to `valid_effects` (line ~1958):

```python
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "ban_extortion", "ban_vandalism",
                         "name_town", "demolish", "promote_image"}
```

In `runtime.py` `TOOL_REGISTRY` (after the `steal` entry, line ~290):

```python
    "heist":            {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_stealing"},
    "extort":           {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_extortion"},
    "vandalize":        {"tier": "reflex", "location_gate": "@building",     "agreement_gate": "ban_vandalism"},
```

In `_validate_world`, extend the steal branch (line ~1259) to cover the agent-target crimes, and add a building-target check. After the existing `elif action == "steal":` block, add:

```python
    elif action in ("heist", "extort"):
        gate = {"heist": "ban_stealing", "extort": "ban_extortion"}[action]
        if world.has_active_rule(gate):
            return f"{gate} rule is active — {action} is forbidden"
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error

    elif action == "vandalize":
        if world.has_active_rule("ban_vandalism"):
            return "ban_vandalism rule is active — vandalize is forbidden"
```

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/agents/runtime.py backend/tests/test_em240_crimes.py
git commit -m "feat: add heist/extort/vandalize crime verbs (EM-240)"
```

> NOTE: wiring these verbs into the action-dispatch (`_apply_action_inner`, `runtime.py:4150`) and the args/name-resolution path follows the SAME mapping the existing `steal`/`arson` use. Add a dispatch case for each new verb that resolves the target (agent or building) and calls the world method, mirroring the steal/arson cases already there. Confirm with: `grep -n '"steal"\|action_steal\|"arson"\|action_arson' backend/petridish/agents/runtime.py`.

---

### Task 7: Economy & corruption verbs — launder, bribe

**Files:**
- Modify: `backend/petridish/engine/world.py` (new actions near the Task 6 actions)
- Modify: `backend/petridish/agents/runtime.py` (`TOOL_REGISTRY`; `_validate_world`; dispatch)
- Test: `backend/tests/test_em240_crimes.py` (append)

**Interfaces:**
- Produces:
  - `World.action_launder(agent, amount: int) -> tuple[bool, str, int]` (returns fee paid)
  - `World.action_bribe(agent, enforcer, amount: int) -> tuple[bool, str, int]` (returns amount paid)

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_em240_crimes.py
def test_launder_reduces_notoriety_for_a_cut():
    crook = _a("crook", "alley"); crook.credits = 100; crook.notoriety = 30
    world = _world([crook])
    ok, reason, fee = world.action_launder(crook, 50)
    assert ok and fee == 15                  # launder_cut 0.3 * 50
    assert crook.credits == 85
    assert crook.notoriety == 22             # launder_notoriety_reduction (8)


def test_launder_rejected_when_clean():
    crook = _a("crook", "alley"); crook.notoriety = 0
    world = _world([crook])
    ok, reason, fee = world.action_launder(crook, 10)
    assert not ok and fee == 0


def test_bribe_wipes_payer_notoriety_and_pays_enforcer():
    crook = _a("crook", "alley"); crook.credits = 40; crook.notoriety = 40
    crook.crime_status = "wanted"
    cop = _a("cop", "alley", role="enforcer")
    world = _world([crook, cop])
    ok, reason, paid = world.action_bribe(crook, cop, 20)
    assert ok and paid == 20
    assert cop.credits == 40
    assert crook.notoriety == 10             # 40 * (1 - 0.75)
    assert crook.crime_status is None        # dropped below wanted_threshold


def test_witnessed_bribe_dirties_the_enforcer():
    crook = _a("crook", "alley"); crook.credits = 40; crook.notoriety = 40
    cop = _a("cop", "alley", role="enforcer")
    snitch = _a("snitch", "alley")
    world = _world([crook, cop, snitch])
    world.action_bribe(crook, cop, 20)
    assert cop.notoriety == 14               # bribe_notoriety, witnessed by snitch
    assert cop.rap_sheet[-1]["crime"] == "bribery"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -k "launder or bribe" -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'action_launder'`.

- [ ] **Step 3: Implement**

In `world.py` (after the Task 6 actions):

```python
    def action_launder(self, agent: AgentState, amount: int) -> tuple[bool, str, int]:
        """EM-240 — spend a cut of credits to cool notoriety. Only when dirty."""
        if agent.notoriety <= 0:
            return False, "nothing to launder", 0
        amount = max(0, min(agent.credits, int(amount or 0)))
        if amount <= 0:
            return False, "no credits to launder", 0
        fee = int(amount * float(self._crime_param("launder_cut", 0.3)))
        agent.credits -= fee
        agent.notoriety = max(0, agent.notoriety -
                              int(self._crime_param("launder_notoriety_reduction", 8)))
        self._clear_wanted_if_cool(agent)
        return True, "ok", fee

    def action_bribe(self, agent: AgentState, enforcer: AgentState,
                     amount: int) -> tuple[bool, str, int]:
        """EM-240 — pay a co-located enforcer to wipe notoriety. If a third party
        witnesses it, the ENFORCER gains notoriety (corruption is catchable)."""
        if enforcer.role != "enforcer":
            return False, "can only bribe an enforcer", 0
        if agent.location != enforcer.location:
            return False, "enforcer not co-located", 0
        amount = max(0, min(agent.credits, int(amount or 0)))
        if amount <= 0:
            return False, "no credits to offer", 0
        agent.credits -= amount
        enforcer.credits += amount
        eff = float(self._crime_param("bribe_efficacy", 0.75))
        agent.notoriety = max(0, int(agent.notoriety * (1.0 - eff)))
        self._clear_wanted_if_cool(agent)
        witnesses = [a for a in self.agents_at(agent.location)
                     if a.id not in (agent.id, enforcer.id)]
        if witnesses:
            self._register_crime(enforcer, "bribery", agent.id,
                                 int(self._crime_param("bribe_notoriety", 14)))
        return True, "ok", amount

    def _clear_wanted_if_cool(self, agent: AgentState) -> None:
        """Drop a `wanted` flag once notoriety falls back below threshold."""
        if agent.crime_status == "wanted" and \
                agent.notoriety < int(self._crime_param("wanted_threshold", 40)):
            agent.crime_status = None
```

> NOTE: `_register_crime` adds `bribe_notoriety` as the base, but the enforcer is the actor and the briber is the "victim" excluded from witnesses — so only the third-party `snitch` counts, giving exactly `bribe_notoriety` (14). Verified by `test_witnessed_bribe_dirties_the_enforcer`.

In `runtime.py` `TOOL_REGISTRY`:

```python
    "launder":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "bribe":            {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
```

In `_validate_world`, add a co-location check for bribe (launder needs none):

```python
    elif action == "bribe":
        target_error = _validate_target(args, agent, world, "bribe")
        if target_error:
            return target_error
```

Add the dispatch cases in `_apply_action_inner` mirroring steal (resolve `args["target"]` to the enforcer agent for bribe; pass `args["amount"]` for both).

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/agents/runtime.py backend/tests/test_em240_crimes.py
git commit -m "feat: add launder/bribe verbs with catchable corruption (EM-240)"
```

---

### Task 8: Conspiracy — recruit + accept_contract (pact → criminal ring)

**Files:**
- Modify: `backend/petridish/engine/world.py` (add `pending_crime_offers` to `World.__init__`/state; new actions)
- Modify: `backend/petridish/agents/runtime.py` (`TOOL_REGISTRY`; `_validate_world`; dispatch)
- Test: `backend/tests/test_em240_crimes.py` (append)

**Interfaces:**
- Produces:
  - `World.pending_crime_offers: dict[str, dict]` — keyed by target agent id → `{recruiter_id, tick}`.
  - `World.action_recruit(agent, target) -> dict` — posts a pact offer (no crime yet).
  - `World.action_accept_contract(agent) -> tuple[bool, str]` — accepts the offer addressed to `agent`: seeds mutual warm trust + sets mutual `ally`, stamps both rap sheets with `conspiracy`, bumps both notoriety. The warm edges let `recompute_factions` cluster the pair into a ring.

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_em240_crimes.py
def test_recruit_posts_offer_without_committing_crime():
    boss = _a("boss", "alley"); crew = _a("crew", "alley")
    world = _world([boss, crew])
    evt = world.action_recruit(boss, crew)
    assert evt["kind"] == "recruited"
    assert world.pending_crime_offers.get("crew", {}).get("recruiter_id") == "boss"
    assert crew.notoriety == 0               # no crime yet


def test_accept_contract_forms_a_warm_pact():
    boss = _a("boss", "alley"); crew = _a("crew", "alley")
    world = _world([boss, crew])
    world.action_recruit(boss, crew)
    ok, reason = world.action_accept_contract(crew)
    assert ok
    # Mutual warm edges (ally) above faction_trust → a ring can derive.
    assert boss.relationships["crew"].type == "ally"
    assert crew.relationships["boss"].type == "ally"
    assert boss.relationships["crew"].trust >= 25
    assert crew.notoriety == 6 and boss.notoriety == 6   # conspiracy_notoriety
    assert "crew" not in world.pending_crime_offers       # consumed


def test_accept_contract_without_offer_is_rejected():
    lone = _a("lone", "alley")
    world = _world([lone])
    ok, reason = world.action_accept_contract(lone)
    assert not ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -k "recruit or contract or pact" -v`
Expected: FAIL — `AttributeError: 'World' object has no attribute 'pending_crime_offers'`.

- [ ] **Step 3: Implement**

In `World.__init__`, beside the other parked-event/queue dicts (search for `self.pending_relationship_events` and `self.pending_spawn_events` to place it consistently):

```python
        # EM-240 — open recruit offers, keyed by TARGET agent id. Consumed on the
        # target's accept_contract turn. Not snapshotted (ephemeral, like whispers).
        self.pending_crime_offers: dict[str, dict] = {}
```

New actions in `world.py`:

```python
    def action_recruit(self, agent: AgentState, target: AgentState) -> dict:
        """EM-240 — propose a criminal pact to a co-located agent. Posts a pending
        offer the target may accept on its NEXT turn. No crime committed here."""
        if agent.location != target.location:
            return self._fail_event(agent.id, "recruit", "not co-located",
                                    f"{agent.name} found no one here to recruit.")
        if agent.id == target.id:
            return self._fail_event(agent.id, "recruit", "self",
                                    f"{agent.name} cannot recruit themselves.")
        self.pending_crime_offers[target.id] = {
            "recruiter_id": agent.id, "tick": self.tick,
        }
        return {
            "kind": "recruited",
            "actor_id": agent.id,
            "target_id": target.id,
            "text": f"{agent.name} quietly pitches {target.name} on a scheme.",
            "payload": {"action": "recruit"},
        }

    def action_accept_contract(self, agent: AgentState) -> tuple[bool, str]:
        """EM-240 — accept the open pact addressed to this agent: seal a warm
        mutual bond (the ring) and mark both with a conspiracy notoriety bump."""
        offer = self.pending_crime_offers.pop(agent.id, None)
        if not offer:
            return False, "no open offer to accept"
        recruiter = self.agents.get(offer.get("recruiter_id"))
        if recruiter is None or not recruiter.alive:
            return False, "the recruiter is gone"
        # Seed mutual trust to the faction threshold and set warm `ally` edges so
        # recompute_factions clusters the pair into a ring (partner is trust-gated;
        # ally is not, which is why we use it for fresh conspirators).
        seed = int(self._crime_param("conspiracy_trust_seed", 30))
        for a, b in ((agent, recruiter), (recruiter, agent)):
            rel = a.relationships.get(b.id)
            if rel is None:
                rel = RelationshipState()
                a.relationships[b.id] = rel
            rel.trust = max(rel.trust, seed)
            if rel.type in ("neutral",):
                rel.type = "ally"
                rel.since_tick = self.tick
        bump = int(self._crime_param("conspiracy_notoriety", 6))
        for who in (agent, recruiter):
            who.notoriety = max(0, min(100, who.notoriety + bump))
            who.rap_sheet.append({"tick": self.tick, "crime": "conspiracy",
                                  "victim_id": None, "witnessed": False})
        return True, "ok"
```

Add `conspiracy_trust_seed: 30` to the `crime:` config block in `config/world.yaml` (Task 4).

In `runtime.py` `TOOL_REGISTRY`:

```python
    "recruit":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "accept_contract":  {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
```

In `_validate_world`: `recruit` needs a co-located target (`_validate_target`); `accept_contract` takes no args (reject if no open offer for a clearer message):

```python
    elif action == "recruit":
        target_error = _validate_target(args, agent, world, "recruit")
        if target_error:
            return target_error

    elif action == "accept_contract":
        if agent.id not in getattr(world, "pending_crime_offers", {}):
            return "no criminal pact has been offered to you"
```

Add dispatch cases mirroring steal (recruit resolves a target agent; accept_contract takes none).

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_crimes.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/petridish/agents/runtime.py config/world.yaml backend/tests/test_em240_crimes.py
git commit -m "feat: add recruit/accept_contract conspiracy verbs (EM-240)"
```

---

### Task 9: Prompt integration — disposition, status, enforcer, and offer lines

**Files:**
- Modify: `backend/petridish/agents/runtime.py` (`_assemble_context` — the system block near `faction_line` ~2049 and the `Mood:` render ~2229)
- Test: `backend/tests/test_em240_prompt.py` (create)

**Interfaces:**
- Consumes: `AgentState.disposition`, `.role`, `.crime_status`, `.notoriety`; `World.pending_crime_offers`.
- Produces: a `crime_block` string appended to the system prompt; empty (byte-identical prompt) for a lawful citizen with no status and no offer.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_em240_prompt.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _world(agents):
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def test_lawful_citizen_prompt_has_no_crime_block():
    a = AgentState(id="dot", name="Dot", personality="bakes", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    s = _sys(a, _world([a]))
    assert "crime" not in s.lower()
    assert "WANTED" not in s


def test_criminal_prompt_nudges_and_shows_wanted():
    a = AgentState(id="mox", name="Mox", personality="schemer", profile="mock",
                   location="plaza", energy=80.0, credits=20,
                   disposition="criminal")
    a.notoriety = 50; a.crime_status = "wanted"
    s = _sys(a, _world([a]))
    assert "WANTED" in s
    assert "angles" in s.lower() or "crime" in s.lower()


def test_enforcer_prompt_shows_duty_line():
    a = AgentState(id="sam", name="Sheriff Sam", personality="keeps order",
                   profile="mock", location="plaza", energy=80.0, credits=20,
                   role="enforcer")
    s = _sys(a, _world([a]))
    assert "keep the peace" in s.lower() or "investigate" in s.lower()


def test_open_offer_surfaces_in_prompt():
    a = AgentState(id="crew", name="Crew", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    boss = AgentState(id="boss", name="Boss", personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)
    world = _world([a, boss])
    world.pending_crime_offers["crew"] = {"recruiter_id": "boss", "tick": 0}
    s = _sys(a, world)
    assert "Boss" in s and ("pact" in s.lower() or "scheme" in s.lower())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_prompt.py -v`
Expected: FAIL — assertions on missing crime/WANTED/duty text.

- [ ] **Step 3: Implement the crime_block**

In `runtime.py`, right after the `faction_line` block (line ~2057), build a `crime_block`:

```python
    # ── EM-240 — Crime & Justice context. Empty (byte-identical prompt) for a
    # lawful citizen with no status and no open offer. Rides this turn — zero
    # extra LLM calls. (getattr keeps callers safe if the engine seam is absent.)
    crime_block = ""
    _disp = getattr(agent, "disposition", "lawful")
    _role = getattr(agent, "role", "citizen")
    _status = getattr(agent, "crime_status", None)
    _noto = getattr(agent, "notoriety", 0)
    _lines = []
    if _disp in ("opportunist", "criminal"):
        _lines.append(
            "You see angles others miss. Crime is on the table when the payoff is "
            "right and no one is watching — steal, heist, extort, vandalize, launder, "
            "or recruit an accomplice. Witnesses build your notoriety; lie low to cool off."
        )
    if _role == "enforcer":
        _lines.append(
            "You keep the peace. You can investigate suspects, accuse them, detain "
            "the wanted, and escalate the worst to a town-hall trial."
        )
    if _status == "wanted":
        _lines.append(f"You are WANTED (notoriety {_noto}). Lay low or get caught.")
    elif _status in ("detained", "jailed"):
        _until = getattr(agent, "crime_status_until_tick", 0)
        _left = max(0, _until - getattr(world, "tick", 0))
        _lines.append(
            f"You are in JAIL for {_left} more ticks. You can only talk, whisper, "
            "and think — no moving, working, or crime until you are released."
        )
    _offers = getattr(world, "pending_crime_offers", {})
    _offer = _offers.get(agent.id) if isinstance(_offers, dict) else None
    if _offer:
        _recruiter = world.agents.get(_offer.get("recruiter_id"))
        if _recruiter is not None:
            _lines.append(
                f"{_recruiter.name} has offered you a criminal pact (a scheme). "
                "Use accept_contract to seal it, or ignore it."
            )
    if _lines:
        crime_block = "\n=== ⚖ THE LAW & THE UNDERWORLD ===\n" + "\n".join(
            f"  {ln}" for ln in _lines)
```

Then add `{crime_block}` to the system-prompt f-string. Find the `Mood: {agent.mood}{faction_line}` line (line ~2229) and append it:

```python
Mood: {agent.mood}{faction_line}{crime_block}
```

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_prompt.py -v && python -m pytest -q`
Expected: PASS. The protagonist-prompt golden fixture (`tests/fixtures/em161_protagonist_prompt_pre_diet.txt`) must still match — a lawful citizen with no status yields an empty `crime_block`, so the fixture is unchanged. If that test fails, the block is leaking for lawful agents — fix the guard.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/agents/runtime.py backend/tests/test_em240_prompt.py
git commit -m "feat: surface disposition/status/enforcer/offer in agent prompt (EM-240)"
```

---

### Task 10: Enforcer verbs — investigate, accuse, detain + jail place + jail gate

**Files:**
- Modify: `backend/petridish/engine/world.py` (new actions; `_jail_place_id` helper)
- Modify: `config/world.yaml` (add a `jail` place to the town's `places`)
- Modify: `backend/petridish/agents/runtime.py` (`TOOL_REGISTRY`; `_validate_world` — enforcer gate + jail restriction; dispatch)
- Test: `backend/tests/test_em240_justice.py` (create)

**Interfaces:**
- Produces:
  - `World.action_investigate(agent, suspect) -> tuple[bool, str, int]` (returns count confirmed)
  - `World.action_accuse(agent, suspect) -> dict`
  - `World.action_detain(agent, suspect) -> dict | tuple[bool, str, None]`
  - `World._jail_place_id() -> str | None`
- Consumes: `_validate_world` now rejects justice verbs unless `agent.role == "enforcer"`, and rejects non-whitelisted actions while `crime_status in ("detained","jailed")`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_em240_justice.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _validate_world


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="jail", name="Jail", x=9, y=9, kind="civic"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def test_investigate_confirms_unwitnessed_crimes_when_a_witness_is_present():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.rap_sheet = [
        {"tick": 0, "crime": "steal", "victim_id": "x", "witnessed": False}]
    witness = _a("witness", "plaza")
    world = _world([cop, crook, witness])
    ok, reason, n = world.action_investigate(cop, crook)
    assert ok and n == 1
    assert crook.rap_sheet[0]["witnessed"] is True
    assert crook.notoriety == 10             # investigate_notoriety


def test_investigate_needs_a_witness():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.rap_sheet = [
        {"tick": 0, "crime": "steal", "victim_id": "x", "witnessed": False}]
    world = _world([cop, crook])
    ok, reason, n = world.action_investigate(cop, crook)
    assert not ok and n == 0


def test_detain_jails_a_wanted_suspect():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza"); crook.crime_status = "wanted"; crook.notoriety = 45
    world = _world([cop, crook]); world.tick = 3
    evt = world.action_detain(cop, crook)
    assert isinstance(evt, dict) and evt["kind"] == "detained"
    assert crook.crime_status == "detained"
    assert crook.location == "jail"
    assert crook.crime_status_until_tick == 3 + 6   # detain_sentence


def test_detain_rejected_without_grounds():
    cop = _a("cop", "plaza", role="enforcer")
    citizen = _a("cit", "plaza")                     # clean
    world = _world([cop, citizen])
    res = world.action_detain(cop, citizen)
    assert res == (False, "insufficient grounds to detain", None)


def test_validator_gates_justice_verbs_to_enforcers():
    citizen = _a("cit", "plaza")
    crook = _a("crook", "plaza"); crook.crime_status = "wanted"
    world = _world([citizen, crook])
    err = _validate_world({"action": "detain", "args": {"target": "Crook"}},
                          citizen, world)
    assert err and "enforcer" in err.lower()


def test_validator_blocks_actions_while_jailed():
    con = _a("con", "jail"); con.crime_status = "jailed"; con.crime_status_until_tick = 99
    world = _world([con]); world.tick = 1
    assert _validate_world({"action": "move_to", "args": {"place": "plaza"}},
                           con, world)  # blocked
    assert _validate_world({"action": "steal", "args": {"target": "x"}},
                           con, world)  # blocked
    assert _validate_world({"action": "say", "args": {"text": "let me out"}},
                           con, world) is None  # talk allowed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_justice.py -v`
Expected: FAIL — `AttributeError: ... 'action_investigate'` / validator returns None where a block is expected.

- [ ] **Step 3: Implement the actions, jail helper, place, and validator gates**

In `world.py`:

```python
    def _jail_place_id(self) -> str | None:
        """EM-240 — the town jail: a place with id 'jail', else the first civic
        place, else None (a town with no jail simply cannot detain)."""
        if "jail" in self.places:
            return "jail"
        for p in self.places.values():
            if p.kind == "civic":
                return p.id
        return None

    def action_investigate(self, agent: AgentState, suspect: AgentState) -> tuple[bool, str, int]:
        """EM-240 — an enforcer questions co-located witnesses to confirm a
        suspect's unwitnessed crimes into notoriety. Needs a third party present."""
        if agent.location != suspect.location:
            return False, "suspect not co-located", 0
        witnesses = [a for a in self.agents_at(agent.location)
                     if a.id not in (agent.id, suspect.id)]
        if not witnesses:
            return False, "no witnesses here to question", 0
        base = int(self._crime_param("investigate_notoriety", 10))
        confirmed = 0
        for entry in suspect.rap_sheet:
            if not entry.get("witnessed"):
                entry["witnessed"] = True
                suspect.notoriety = max(0, min(100, suspect.notoriety + base))
                confirmed += 1
        if confirmed and suspect.crime_status is None and \
                suspect.notoriety >= int(self._crime_param("wanted_threshold", 40)):
            suspect.crime_status = "wanted"
        return True, "ok", confirmed

    def action_accuse(self, agent: AgentState, suspect: AgentState) -> dict:
        """EM-240 — an enforcer publicly names a suspect. Narrative + a feed
        event; the actual penalty comes via detain or a trial vote."""
        if agent.location != suspect.location:
            return self._fail_event(agent.id, "accuse", "not co-located",
                                    f"{agent.name} found no one here to accuse.")
        return {
            "kind": "accusation",
            "actor_id": agent.id,
            "target_id": suspect.id,
            "text": f"{agent.name} accuses {suspect.name} of crimes against the town.",
            "payload": {"notoriety": suspect.notoriety},
        }

    def action_detain(self, agent: AgentState, suspect: AgentState):
        """EM-240 — an enforcer jails a wanted / high-notoriety suspect on the
        spot for detain_sentence ticks. (The spec's 'red-handed' fast lane is
        subsumed: a witnessed crime registers notoriety, which is the grounds.)"""
        if agent.location != suspect.location:
            return False, "suspect not co-located", None
        threshold = int(self._crime_param("detain_threshold", 60))
        if not (suspect.crime_status == "wanted" or suspect.notoriety >= threshold):
            return False, "insufficient grounds to detain", None
        jail = self._jail_place_id()
        if jail is None:
            return False, "this town has no jail", None
        suspect.location = jail
        suspect.crime_status = "detained"
        suspect.crime_status_until_tick = self.tick + int(self._crime_param("detain_sentence", 6))
        return {
            "kind": "detained",
            "actor_id": agent.id,
            "target_id": suspect.id,
            "text": f"{agent.name} detains {suspect.name} and marches them to jail.",
            "payload": {"until_tick": suspect.crime_status_until_tick},
        }
```

In `config/world.yaml`, add a `jail` place to the town's `places:` list (match the existing place entry shape — id/name/x/y/kind/description):

```yaml
  - id: jail
    name: The Lockup
    x: 9
    y: 9
    kind: civic
    description: A spare stone cell where the town holds its lawbreakers.
```

> Verify the exact place schema first: `grep -n "kind: civic\|- id: townhall\|kind: governance" config/world.yaml`. Match the surrounding entries' fields exactly.

In `runtime.py` `TOOL_REGISTRY`:

```python
    "investigate":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "accuse":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "detain":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
```

In `_validate_world`, add two gates. First, the **jail restriction** — put it near the top, right after the dead-agent guard (line ~1217):

```python
    # EM-240 — jail restriction: a detained/jailed agent may only talk and think.
    JAIL_ALLOWED = {"say", "whisper", "idle", "remember"}
    if getattr(agent, "crime_status", None) in ("detained", "jailed") and \
            action not in JAIL_ALLOWED:
        return ("you are jailed — you can only talk, whisper, and think until "
                "you are released")
```

Then the **enforcer gate** (add an elif alongside the other action branches):

```python
    elif action in ("investigate", "accuse", "detain"):
        if getattr(agent, "role", "citizen") != "enforcer":
            return f"{action} is reserved for enforcers (role) — you keep no badge"
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error
```

Add dispatch cases for the three verbs mirroring steal's target resolution.

Finally, mirror the enforcer gate in the **menu** (`_assemble_context`): the justice verbs must be omitted from a non-enforcer's valid-actions list (the menu/resolution-agree rule). Find where the valid-actions list is assembled (grep `valid_actions` / the menu builder) and append `investigate/accuse/detain` only when `getattr(agent, "role", "citizen") == "enforcer"`.

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_justice.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py config/world.yaml backend/petridish/agents/runtime.py backend/tests/test_em240_justice.py
git commit -m "feat: add enforcer investigate/accuse/detain + jail (EM-240)"
```

---

### Task 11: Trial governance — propose, convict, acquit, fine, restitution

**Files:**
- Modify: `backend/petridish/engine/world.py` (`action_propose_rule` ~1941 — add `trial` effect + payload; `_on_rule_activated` ~2084 — conviction; `action_vote` ~2044 — acquittal branch)
- Test: `backend/tests/test_em240_justice.py` (append)

**Interfaces:**
- Consumes: `action_propose_rule(agent, effect="trial", text=charges, target=defendant_id)`, `action_vote`, `_evaluate_rule`, `pending_spawn_events`.
- Produces: a passing trial vote jails the defendant for `trial_sentence`, confiscates `trial_fine` (restitution to distinct rap-sheet victims, remainder dropped), and parks `trial_verdict`(guilty) + `jailed`. A rejected trial clears `acquittal_notoriety_relief` notoriety, docks the proposer `accuser_acquittal_penalty` trust from onlookers, and parks `trial_verdict`(acquitted).

- [ ] **Step 1: Write the failing tests**

```python
# append to backend/tests/test_em240_justice.py
def test_trial_proposal_requires_a_real_defendant():
    cop = _a("cop", "plaza", role="enforcer")
    world = _world([cop])
    # governance gate: proposing requires a governance place — put the cop there.
    world.places["plaza"].kind = "governance"
    ok, reason, rule = world.action_propose_rule(
        cop, "trial", "theft and arson", target="nobody")
    assert not ok and rule is None


def test_trial_conviction_jails_and_fines_with_restitution():
    cop = _a("cop", "gov", role="enforcer")
    crook = _a("crook", "plaza"); crook.credits = 40
    crook.rap_sheet = [{"tick": 0, "crime": "steal", "victim_id": "victim", "witnessed": True}]
    victim = _a("victim", "plaza"); victim.credits = 10
    juror = _a("juror", "plaza")
    world = _world([cop, crook, victim, juror])
    world.places["gov"] = PlaceState(id="gov", name="Hall", x=1, y=1, kind="governance")
    cop.location = "gov"
    ok, reason, rule = world.action_propose_rule(
        cop, "trial", "habitual theft", target="crook")
    assert ok
    # 3 of 4 vote guilty → conviction.
    for v in (cop, victim, juror):
        world.action_vote(v, rule.id, True)
    assert crook.crime_status == "jailed"
    assert crook.location == "jail"
    assert crook.credits == 40 - 25          # trial_fine
    assert victim.credits == 10 + 25         # sole victim gets full restitution
    evts = world.drain_spawn_events()
    kinds = {e["kind"] for e in evts}
    assert "trial_verdict" in kinds and "jailed" in kinds


def test_trial_acquittal_clears_notoriety_and_dings_accuser():
    cop = _a("cop", "gov", role="enforcer")
    crook = _a("crook", "plaza"); crook.notoriety = 30
    j1 = _a("j1", "plaza"); j2 = _a("j2", "plaza"); j3 = _a("j3", "plaza")
    world = _world([cop, crook, j1, j2, j3])
    world.places["gov"] = PlaceState(id="gov", name="Hall", x=1, y=1, kind="governance")
    cop.location = "gov"
    ok, reason, rule = world.action_propose_rule(cop, "trial", "vague vibes", target="crook")
    assert ok
    for v in (crook, j1, j2, j3):            # 4 of 5 vote not-guilty
        world.action_vote(v, rule.id, False)
    assert crook.notoriety == 15             # 30 - acquittal_notoriety_relief
    # accuser (cop) takes an onlooker trust hit from at least one juror
    assert any(j.relationships.get("cop") and j.relationships["cop"].trust < 0
               for j in (j1, j2, j3))
    evts = world.drain_spawn_events()
    assert any(e["kind"] == "trial_verdict" and e["payload"]["verdict"] == "acquitted"
               for e in evts)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_em240_justice.py -k trial -v`
Expected: FAIL — `invalid effect: 'trial'`.

- [ ] **Step 3: Implement trial proposal, conviction, acquittal**

In `action_propose_rule`, add `"trial"` to `valid_effects` (the Task 6 edit already touches this set — add it there):

```python
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "ban_extortion", "ban_vandalism",
                         "name_town", "demolish", "promote_image", "trial"}
```

and add a payload/guard block (place it beside the `demolish` block, ~1978):

```python
        # EM-240 — trial carries the defendant id on the payload (like demolish's
        # target). A trial of an unknown/dead defendant, or one already jailed/on
        # trial, is rejected.
        if effect == "trial":
            target = str(target or "").strip()
            defendant = self.agents.get(target)
            if defendant is None or not defendant.alive:
                return False, f"trial requires a living defendant (got {target!r})", None
            if defendant.crime_status in ("detained", "jailed"):
                return False, f"{defendant.name} is already in custody", None
            for r in self.rules.values():
                if r.effect == "trial" and r.status == "proposed" and \
                        (r.payload or {}).get("defendant_id") == target:
                    return False, f"{defendant.name} is already on trial", None
            payload = {"defendant_id": target, "charges": str(text)[:200]}
```

> The duplicate-effect guard at ~2009 blocks a second *open* proposal per effect; scope trial per-defendant the same way demolish/promote_image are scoped. In that loop, add a `trial` branch mirroring demolish:

```python
            if effect == "trial":
                if (rule.payload or {}).get("defendant_id") == payload.get("defendant_id"):
                    return False, "that defendant already has an open trial", None
                continue
```

In `_on_rule_activated`, add a conviction branch (after the demolish branch, ~2123):

```python
        # EM-240 — trial conviction: a passing guilty vote jails the defendant and
        # fines them, paying restitution to their distinct rap-sheet victims.
        if rule.effect == "trial":
            rule.applied = True
            defendant = self.agents.get((rule.payload or {}).get("defendant_id"))
            if defendant is None:
                return
            sentence = int(self._crime_param("trial_sentence", 20))
            fine = min(defendant.credits, int(self._crime_param("trial_fine", 25)))
            defendant.credits -= fine
            jail = self._jail_place_id()
            if jail is not None:
                defendant.location = jail
            defendant.crime_status = "jailed"
            defendant.crime_status_until_tick = self.tick + sentence
            # Restitution: split the fine evenly across distinct living victims.
            victim_ids = []
            for e in defendant.rap_sheet:
                vid = e.get("victim_id")
                v = self.agents.get(vid) if vid else None
                if v is not None and v.alive and vid not in victim_ids:
                    victim_ids.append(vid)
            if victim_ids and fine > 0:
                share = fine // len(victim_ids)
                for vid in victim_ids:
                    self.agents[vid].credits += share
            self.pending_spawn_events.append({
                "kind": "trial_verdict", "actor_id": "system", "actor_type": "system",
                "target_id": defendant.id,
                "text": f"⚖ By vote, {defendant.name} is found GUILTY and jailed.",
                "payload": {"verdict": "guilty", "fine": fine,
                            "sentence": sentence, "proposal_id": rule.id},
            })
            self.pending_spawn_events.append({
                "kind": "jailed", "actor_id": "system", "actor_type": "system",
                "target_id": defendant.id,
                "text": f"{defendant.name} is led to jail for {sentence} ticks.",
                "payload": {"until_tick": defendant.crime_status_until_tick},
            })
            return
```

In `action_vote`, add an acquittal branch. The rejected path is the `else` at line ~2080 (`rule.status = new_status`). Insert before that assignment:

```python
            # EM-240 — a rejected trial is an ACQUITTAL: clear some notoriety and
            # dock the accuser's standing with co-located onlookers.
            if rule.effect == "trial" and new_status == "rejected" and not rule.applied:
                rule.applied = True
                defendant = self.agents.get((rule.payload or {}).get("defendant_id"))
                accuser = self.agents.get(rule.proposer_id)
                if defendant is not None:
                    defendant.notoriety = max(
                        0, defendant.notoriety -
                        int(self._crime_param("acquittal_notoriety_relief", 15)))
                    self._clear_wanted_if_cool(defendant)
                if accuser is not None:
                    pen = int(self._crime_param("accuser_acquittal_penalty", 8))
                    for onlooker in self.agents_at(accuser.location):
                        if onlooker.id != accuser.id:
                            self._update_trust(onlooker, accuser, -pen)
                self.pending_spawn_events.append({
                    "kind": "trial_verdict", "actor_id": "system", "actor_type": "system",
                    "target_id": defendant.id if defendant else None,
                    "text": (f"⚖ By vote, {defendant.name if defendant else 'the accused'} "
                             "is ACQUITTED."),
                    "payload": {"verdict": "acquitted", "proposal_id": rule.id},
                })
```

> NOTE: `_clear_wanted_if_cool` was added in Task 7. If Task 7 is not yet merged, inline the two-line check instead.

- [ ] **Step 4: Run tests + full suite**

Run: `cd backend && python -m pytest tests/test_em240_justice.py -v && python -m pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/engine/world.py backend/tests/test_em240_justice.py
git commit -m "feat: add town-hall trial (convict/acquit/fine/restitution) (EM-240)"
```

---

### Task 12: Seed personas + event-kind registration + capstone integration test

**Files:**
- Modify: `config/personas.yaml` (add criminals/enforcers; promote Brick)
- Modify: `contracts/events.schema.json` (`x-known-kinds`)
- Test: `backend/tests/test_em240_integration.py` (create)

**Interfaces:**
- Consumes: everything above. This task proves the loop end-to-end.

- [ ] **Step 1: Add the seed personas**

Append to `config/personas.yaml` (match the existing card shape; the new keys are optional):

```yaml
  - name: Roop
    archetype: Con Artist
    personality: >-
      Sells the same bridge twice and a third time as an apology. Reads a mark in
      one glance and a room in two, and never met a promise he meant to keep.
    suggested_profile: groq-llama
    disposition: criminal

  - name: Sledge
    archetype: Protection Racketeer
    personality: >-
      Offers every stallholder "insurance" against accidents he personally
      arranges. Polite, patient, and absolutely certain the town owes him rent.
    suggested_profile: cerebras-glm
    disposition: criminal

  - name: Wisp
    archetype: Smuggler
    personality: >-
      Moves anything for anyone and launders the proceeds through a smile. Keeps
      two ledgers, trusts neither, and vanishes the moment a badge looks twice.
    suggested_profile: kimi
    disposition: criminal

  - name: Sheriff Cobb
    archetype: Town Sheriff
    personality: >-
      Keeps a tin star polished and a list of every debt unpaid. Believes the law
      is a promise the town makes to itself, and intends to collect on it.
    suggested_profile: deepseek-pro
    role: enforcer

  - name: Reyes
    archetype: Vigilante
    personality: >-
      Decided the law was too slow and appointed herself the difference. Means
      well, mostly, and leaves a trail of bruised certainties behind her.
    suggested_profile: qwen-next
    role: enforcer
    disposition: opportunist

  - name: Pip
    archetype: Petty Pickpocket
    personality: >-
      Lifts a credit here, a trinket there, never enough to hang for. Swears each
      time is the last and means it for almost a whole afternoon.
    suggested_profile: gemini-flash
    disposition: opportunist
```

Promote the existing Brick card — add `role: enforcer` under its `suggested_profile` (the "Retired Enforcer" archetype now carries the badge):

```yaml
  - name: Brick
    archetype: Retired Enforcer
    personality: >-
      Settles disagreements by flexing first and apologizing later. Secretly
      composes tender little reviews of the Commons' foraging berries and is
      one kind word away from crying at a festival.
    suggested_profile: cerebras-glm
    role: enforcer
```

- [ ] **Step 2: Register the new event kinds (docs)**

In `contracts/events.schema.json`, add the EM-240 kinds to the `x-known-kinds` list (line ~38): `crime_committed`, `crime_witnessed`, `wanted`, `investigation`, `accusation`, `detained`, `trial_proposed`, `trial_vote`, `trial_verdict`, `jailed`, `released`, `bribe`, `recruited`.

- [ ] **Step 3: Write the capstone integration test**

```python
# backend/tests/test_em240_integration.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, load_personas


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="gov", name="Hall", x=1, y=1, kind="governance"),
        PlaceState(id="jail", name="Jail", x=9, y=9, kind="civic"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def test_seed_personas_include_criminals_and_enforcers():
    cards = {c["name"]: c for c in load_personas()}
    assert cards["Roop"]["disposition"] == "criminal"
    assert cards["Sheriff Cobb"]["role"] == "enforcer"
    assert cards["Brick"]["role"] == "enforcer"   # promoted


def test_crime_to_conviction_end_to_end():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza", disposition="criminal"); crook.credits = 50
    mark = _a("mark", "plaza"); mark.credits = 40
    eye = _a("eye", "plaza")
    world = _world([cop, crook, mark, eye])

    # 1. A witnessed heist builds notoriety.
    ok, _, amt = world.action_heist(crook, mark)
    assert ok and crook.notoriety > 0

    # 2. The cop escalates to a trial and the town convicts.
    cop.location = "gov"
    ok, _, rule = world.action_propose_rule(cop, "trial", "the heist", target="crook")
    assert ok
    for v in (cop, mark, eye):
        world.action_vote(v, rule.id, True)
    assert crook.crime_status == "jailed" and crook.location == "jail"

    # 3. Jailed crook can only talk; serves the sentence and is released.
    world.tick = crook.crime_status_until_tick
    events = world.advance_crime()
    assert crook.crime_status is None
    assert any(e["kind"] == "released" for e in events)


def test_conspiracy_forms_a_faction():
    boss = _a("boss", "plaza", disposition="criminal")
    crew = _a("crew", "plaza", disposition="criminal")
    other = _a("other", "plaza"); other2 = _a("other2", "plaza")
    world = _world([boss, crew, other, other2])
    world.action_recruit(boss, crew)
    world.action_accept_contract(crew)
    factions = world.recompute_factions()
    member_sets = [set(f["members"]) for f in factions]
    assert any({"boss", "crew"} <= m for m in member_sets)
```

> NOTE: `recompute_factions` needs mutual warm edges meeting `faction_trust` (default 25) and `faction_min_size` (default 3). The pact seeds trust 30 but only makes a 2-member cluster. If `faction_min_size` is 3, either seed a third conspirator in the test or assert the warm mutual `ally` edges directly instead of a derived faction. Check the default: `grep -n "faction_min_size\|faction_trust" config/world.yaml backend/petridish/engine/world.py`. Adjust the test to the real minimum (add a third recruited member if needed).

- [ ] **Step 4: Run the full EM-240 suite + everything**

Run: `cd backend && python -m pytest tests/test_em240_integration.py -v && python -m pytest -q`
Expected: PASS across the suite.

- [ ] **Step 5: Commit**

```bash
git add config/personas.yaml contracts/events.schema.json backend/tests/test_em240_integration.py
git commit -m "feat: seed crime personas, register event kinds, add integration test (EM-240)"
```

---

## Post-implementation

- [ ] Run the whole backend suite once more: `cd backend && python -m pytest -q`.
- [ ] File the EM-240 closure note into the ledger via the `plan-intake` skill (per `START-HERE.md` "How work flows in"), and mark EM-241 (persona content) / EM-242 (management UI) as the follow-on specs.
- [ ] Optional live smoke: start the sim, spawn `Sheriff Cobb` and `Roop`, and watch the feed for `crime_committed` → `accusation` → `trial_verdict` → `jailed` → `released`.

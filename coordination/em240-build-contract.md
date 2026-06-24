# EM-240 Build Contract — overrides & firmed details for the implementation plan

> Read this **alongside** `docs/superpowers/plans/2026-06-24-crime-and-justice-engine.md`.
> Where this contract and the plan disagree, **this contract wins** — it captures
> facts a read-only scout confirmed against the *current* source that the plan
> wrote before those internals were read. Everything else in the plan stands.

## Global rules for every task

- **Re-anchor by symbol, not line number.** Earlier tasks shift line numbers in
  `world.py` / `runtime.py`. Find functions by name (grep), don't trust the
  plan's `~NNNN` anchors after Task 1.
- **Run the FULL backend suite before every commit:** `cd backend && python -m pytest -q`.
  Commit only when green. A task is not done until the whole suite passes.
- **Never cheat the gate.** Do not skip/delete tests, weaken assertions, add
  `# type: ignore`/`pytest.mark.skip`, or relocate a violation to make a check
  pass. If the plan's exact code does not fit the current source, ADAPT it to the
  real pattern (documented below) and note what you changed in the commit body.
- **One commit per task**, message per the plan's Step 5 (conventional commits,
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`, no
  session trailer).
- **Determinism (EM-155):** no `random`, no wall-clock in engine paths.

---

## CONTRACT A — Action dispatch wiring (affects Tasks 6, 7, 8, 10)

New agent-targeted verbs need TWO edits in `backend/petridish/agents/runtime.py`
beyond the plan's `TOOL_REGISTRY` + `_validate_world` edits:

### A1. Register name-resolution for agent-targeted verbs

Find `_TARGETED_ACTIONS` (near line ~1090, used by `_normalize_args`). Add the
new **agent-targeted** verbs so a name like `"Vesper"` in `args["target"]` is
resolved to an agent id BEFORE dispatch (exactly as `steal` is):

```python
# add to the _TARGETED_ACTIONS set:
"heist", "extort", "bribe", "recruit", "investigate", "accuse", "detain"
```

`launder` and `accept_contract` take **no target** — do NOT add them.
`vandalize` targets a building id (`args["building_id"]`), NOT a name — do NOT add it.

### A2. Add dispatch cases in `_apply_action_inner`

The dispatch is an if/elif chain. Two shapes — copy the matching one:

**Tuple-returning verbs** (heist/extort return `(ok, reason, amount)`; launder/bribe
return `(ok, reason, value)`; investigate returns `(ok, reason, count)`) — follow the
`steal` case (runtime.py ~4218). Example for heist:

```python
        elif action == "heist":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to heist but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, amount = self.world.action_heist(agent, target)
            if ok:
                return {**base, "kind": "crime_committed", "target_id": target.id,
                        "text": f"{agent.name} pulls off a heist on {target.name} ({amount} credits)!",
                        "payload": {"action": "heist", "amount": amount, "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to heist but: {reason}",
                    "payload": {"error": reason}}
```

- `extort`: same shape; `kind: "crime_committed"`, `payload.action: "extort"`.
- `bribe`: target is the enforcer (`args["target"]`); pass `args.get("amount", 0)`:
  `ok, reason, paid = self.world.action_bribe(agent, target, args.get("amount", 0))`;
  success `kind: "bribe"`.
- `launder` (no target): `ok, reason, fee = self.world.action_launder(agent, args.get("amount", 0))`; success `kind: "economy"`, `payload.action: "launder"`.
- `investigate`: `ok, reason, n = self.world.action_investigate(agent, target)`; success `kind: "investigation"`, `payload: {"action":"investigate","confirmed":n}`.
- `accept_contract` (no target): `ok, reason = self.world.action_accept_contract(agent)` (2-tuple); success `kind: "recruited"`, `payload.action: "accept_contract"`.

**Dict / `_multi`-returning verbs** (vandalize, accuse, detain, recruit return a
ready event dict) — follow the `arson` case (runtime.py ~4449) using
`_emit_world_result`:

```python
        elif action == "vandalize":
            result = self.world.action_vandalize(agent, args.get("building_id", ""))
            return _emit_world_result(result, base, thought)
        elif action == "recruit":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to recruit but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(self.world.action_recruit(agent, target), base, thought)
        elif action == "accuse":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to accuse but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(self.world.action_accuse(agent, target), base, thought)
        elif action == "detain":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to detain but target not found",
                        "payload": {"error": "target_not_found"}}
            result = self.world.action_detain(agent, target)
            # action_detain returns a dict on success OR a (False, reason, None) tuple
            if isinstance(result, dict):
                return _emit_world_result(result, base, thought)
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to detain but: {result[1]}",
                    "payload": {"error": result[1]}}
```

> NOTE the detain mixed-return shape: `action_detain` returns a **dict** on success
> and a **`(False, reason, None)` tuple** on rejection (per the plan). Handle both
> as shown. (If you prefer, make `action_detain` always return a dict via
> `_fail_event` on rejection — but then update the plan's Task 10 test, which
> asserts the `(False, "insufficient grounds to detain", None)` tuple. Keep the
> tuple to match the test.)

### A3. The name→id resolver (reference, do not modify)

`_resolve_agent_target` (runtime.py ~983) + `_normalize_args` (~1099) already do
name→id resolution for `_TARGETED_ACTIONS`. Adding your verb to that set (A1) is
all that's needed — `self.world.agents.get(args["target"])` then returns the agent.

---

## CONTRACT B — Config requires a real `CrimeParams` dataclass (REVISES Task 4)

The plan's Task 4 assumed `crime:` is ingested automatically as a dict. It is NOT.
`WorldParams` (in `backend/petridish/config/loader.py` ~769) declares each nested
block as a typed dataclass field (e.g. `relationships: RelationshipParams =
field(default_factory=RelationshipParams)`). Do the same for crime:

### B1. Define `CrimeParams` (place it beside `RelationshipParams` in loader.py)

```python
@dataclass
class CrimeParams:
    """EM-240 — Crime & Justice tunables. Defaults MUST match the _crime_param()
    call-site defaults in world.py (the RelationshipParams/_rel_param convention)."""
    wanted_threshold: int = 40
    detain_threshold: int = 60
    notoriety_decay: int = 2
    notoriety_per_extra_witness: int = 3
    rap_sheet_cap: int = 10
    heist_max: int = 30
    heist_min_target_credits: int = 15
    extort_max: int = 15
    vandalize_blackout_ticks: int = 8
    vandalize_notoriety: int = 10
    heist_notoriety: int = 18
    extort_notoriety: int = 12
    steal_notoriety: int = 6
    arson_notoriety: int = 22
    bribe_efficacy: float = 0.75
    bribe_notoriety: int = 14
    launder_cut: float = 0.3
    launder_notoriety_reduction: int = 8
    investigate_notoriety: int = 10
    conspiracy_notoriety: int = 6
    conspiracy_trust_seed: int = 30
    detain_sentence: int = 6
    trial_sentence: int = 20
    trial_fine: int = 25
    acquittal_notoriety_relief: int = 15
    accuser_acquittal_penalty: int = 8
    released_notoriety_relief: int = 10
```

### B2. Wire it into `WorldParams` AND the YAML parser

- Add the field to `WorldParams`: `crime: CrimeParams = field(default_factory=CrimeParams)`.
- **Wire parsing exactly like `RelationshipParams`.** Grep loader.py for EVERY
  reference to `RelationshipParams` / `relationships` (the dataclass→YAML coercion
  may be explicit — a `_coerce_block`, a `from_dict`, or per-field construction in
  `_parse_world`/`load_config`). Add a parallel `CrimeParams` / `crime` reference at
  each site. Verify: `cd backend && python -c "from petridish.config.loader import load_config; c=load_config(); print(c.world.crime.wanted_threshold)"` prints `40` (or your world.yaml override).

The plan's `_crime_param` accessor (`_block_get(getattr(self.params,'crime',None), name, default)`)
then reads `CrimeParams` attributes; its `default` arg is only a fallback for a key
absent from the dataclass, so **keep accessor defaults == CrimeParams defaults**.

The `config/world.yaml` `crime:` block from the plan still goes in (it OVERRIDES the
dataclass defaults). Add `conspiracy_trust_seed: 30` to that YAML block (Task 8 needs it).

---

## CONTRACT C — Menu lines for the new verbs (EXTENDS Tasks 6, 7, 8, 9, 10)

Adding a verb to `TOOL_REGISTRY` + `_validate_world` makes it *legal* but the LLM
never *picks* it unless it appears in the `valid_actions` menu built in
`_assemble_context`. Add menu lines, gated so the menu matches the design:

- **Crime verbs are offered only to the inclined** (`disposition in
  ("opportunist","criminal")`) — lawful citizens see no crime on the menu, matching
  their empty crime_block. The *validator still allows crime for everyone* (a lawful
  agent CAN emit an off-menu crime and it resolves — the emergent "snap"); the menu
  just doesn't invite it.
- **Enforcer verbs are offered only to enforcers** (`role == "enforcer"`).

Mirror the existing co-located block (runtime.py ~1708, `if co_located:`). Add,
near it:

```python
    # EM-240 — crime menu, only for the inclined (validator still allows all).
    if getattr(agent, "disposition", "lawful") in ("opportunist", "criminal"):
        if co_located:
            tnames = ", ".join(a.name for a in co_located)
            if _gate_ok("heist"):
                valid_actions.append(f"heist (target) - big-score theft from: {tnames}")
            if _gate_ok("extort"):
                valid_actions.append(f"extort (target) - shake down for credits: {tnames}")
            if _gate_ok("recruit"):
                valid_actions.append(f"recruit (target) - pitch a criminal pact to: {tnames}")
        if _gate_ok("vandalize"):
            valid_actions.append("vandalize (building_id) - damage a building short of arson")
        if getattr(agent, "notoriety", 0) > 0:
            valid_actions.append("launder (amount) - spend a cut to cool your notoriety")
    # An open criminal pact addressed to this agent → offer accept_contract.
    if agent.id in getattr(world, "pending_crime_offers", {}):
        valid_actions.append("accept_contract - seal the criminal pact offered to you")
    # Anyone wanted, co-located with an enforcer, may try a bribe.
    if getattr(agent, "notoriety", 0) > 0 and co_located:
        cops = [a.name for a in co_located if getattr(a, "role", "citizen") == "enforcer"]
        if cops:
            valid_actions.append(f"bribe (target, amount) - pay an enforcer to drop your heat: {', '.join(cops)}")

    # EM-240 — enforcer-only justice verbs.
    if getattr(agent, "role", "citizen") == "enforcer" and co_located:
        tnames = ", ".join(a.name for a in co_located)
        valid_actions.append(f"investigate (target) - question witnesses about: {tnames}")
        valid_actions.append(f"accuse (target) - publicly accuse: {tnames}")
        valid_actions.append(f"detain (target) - jail a wanted suspect: {tnames}")
    # Trial = a governance proposal effect; extend the propose_rule effect list to
    # include `trial` (target=<defendant id>) wherever that line is built.
```

Use the same `_gate_ok(...)` helper the existing `steal` menu line uses (it checks
the `agreement_gate`). `co_located` is already computed in `_assemble_context`. Add
these in the task that introduces each verb (heist/extort/vandalize → Task 6;
launder/bribe → Task 7; recruit/accept_contract → Task 8; enforcer verbs → Task 10).
Each addition needs a menu test (assert the line appears for the right
disposition/role and is absent otherwise) — extend `test_em240_prompt.py`.

---

## CONTRACT D — Building construction in tests (affects Task 6 vandalize test)

The plan's vandalize test referenced a nonexistent `buildings_seed_one` helper.
Construct a real `Building` instead (`from petridish.engine.world import Building`):

```python
from petridish.engine.world import Building

def test_vandalize_blacks_out_building_and_records_crime():
    vandal = _a("vandal", "plaza")
    world = _world([vandal])
    world.buildings["b1"] = Building(id="b1", name="Stall", kind="workshop",
                                     location="plaza", status="operational", health=100)
    evt = world.action_vandalize(vandal, "b1")
    assert isinstance(evt, dict) and evt["kind"] == "crime_committed"
    assert world.places["plaza"].blackout_until_tick > world.tick
    assert vandal.rap_sheet[-1]["crime"] == "vandalize"
```

`Building` required fields: `id, name, kind, location`. Everything else defaults.
Assign to `world.buildings[b.id]`.

---

## CONTRACT E — `WorldParams` minimal-construction in tests

The test helpers build `WorldParams(tick_interval_seconds=..., turns_per_day=999, ...)`
with only a few kwargs. After Contract B adds `crime: CrimeParams = field(...)`,
those constructions still work (crime defaults to `CrimeParams()`), so
`world._crime_param("wanted_threshold", 40)` returns `40` with no `crime` kwarg.
No test-helper change needed for that. The plan's Task 4 dict-override test
(`world.params.crime = {"wanted_threshold": 25}`) also still works because
`_block_get` reads dicts too.

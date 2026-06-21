# Contract — EM-223 recursive + reactive planning

Integration boundaries for the build. The locked architecture lives in
`docs/superpowers/specs/2026-06-20-em223-recursive-planning-design.md` (the spike); this
contract is the signature surface the engine + runtime build against. Single ownership lane
(no parallel split): `engine/world.py`, `agents/runtime.py`, `config/loader.py`,
`config/world.yaml`, plus a thin frontend feed touch.

**Master gate — `world.planning.enabled` (default `False`).** Disabled ⇒ no plan block, no
plan invite, `plan_revision` ignored, `AgentState.plan` never set: prompts are byte-identical
to pre-EM-223 (the `test_protagonist_prompt_byte_identical_to_pre_diet_capture` golden file)
and snapshots keep the prior key set. The user flips it on for the live tuning run the spike
calls for. This mirrors the established opt-in pattern (factions / narrator / procgen / miracles).

## 1. Plan state — `engine/world.py`

**`normalize_plan(raw: Any) -> dict | None`** (module-level, pure/total, never raises):
coerce a raw plan into the canonical bounded shape, or `None` if it lacks a usable goal+steps.
Used BOTH when an agent emits a `plan_revision` (runtime) AND when restoring a snapshot
(world), so the stored shape is identical on both paths (fork/replay byte-stable). No clock
reads, no RNG inside (the runtime supplies `plan_id`/`made_tick`).

Canonical shape:
```python
{
  "plan_id": str,          # opaque id (runtime-generated at creation; preserved on restore)
  "goal": str,             # ≤ PLAN_GOAL_CAP (200), stripped
  "steps": [str, ...],     # 1..PLAN_MAX_STEPS (8), each ≤ PLAN_STEP_CAP (120), stripped, non-empty
  "current_step": int,     # clamped to [0, len(steps)-1]
  "made_tick": int,
  "stale": bool,
}
```
Bounds: `PLAN_GOAL_CAP = 200`, `PLAN_STEP_CAP = 120`, `PLAN_MAX_STEPS = 8`.

**`AgentState.plan: dict | None = None`** — ADDITIVE. Serialized in `to_dict` ONLY when set
(the `parents`/`cap_demotions` pattern); `from_snapshot` restores via `normalize_plan(d.get("plan"))`
⇒ `None` for pre-EM-223 snapshots. Snapshot-additive ⇒ old forks/replays load unchanged.

## 2. Plan block in context — `agents/runtime.py::_assemble_context`

A `=== YOUR CURRENT PLAN ===` block slotted AFTER `{commitments_block}`, BEFORE
`=== YOUR BELIEFS ===`. Rendered only when `planning.enabled` AND `agent.plan` is set
(absent ⇒ byte-identical). Absolute `made at tick N` stamp (cache-stable for background, EM-171).
Prompt-diet aware (EM-161): background renders goal + current step only; protagonist/supporting
render goal + all steps with a `▶` pointer at `current_step`. Always invites abandonment
("this is YOUR intention, not an order … act freely"). When enabled AND the agent has NO plan,
a one-line creation invite is shown instead (non-byte-identical, but gated behind `enabled`).

## 3. `plan_revision` turn field (zero extra call) — `agents/runtime.py`

- `ACTION_SCHEMA.properties.plan_revision`: optional object `{goal:str, steps:[str], reason?:str}`
  (`additionalProperties:false`). Declared so `additionalProperties:false` at top level admits it.
- `_sanitize_plan_revision(action_dict) -> str | None`: pre-validation, IN PLACE — a malformed
  `plan_revision` is POPPED (never fails the turn, the `_sanitize_bond` leniency rule); a valid
  one is left for the parser. Returns a reject reason for the decision trace, else None.
- Added to `_HOISTABLE_COGNITION` so a model that scatters it into `actions[0]` is hoisted.
- In `run_turn`, parsed once beside `commitment`/`reflection` (SAME single response, zero extra
  calls): build `normalize_plan({**rev, plan_id, made_tick=tick, current_step:0, stale:False})`;
  on success set `agent.plan` and emit ONE `plan_revised` event. Gated on `planning.enabled`.

## 4. Plan-aware reflex bias (zero call) — `agents/runtime.py::_reflex_pick`

When `planning.enabled` AND `planning.reflex_bias` AND the agent has an active (non-stale) plan,
the FINAL rotation tier (after the survival-recharge and at-work-→-work preflights, which are
untouched) biases toward the current step: if the step text names a reachable world place and
the agent isn't already there, return `move_to(that place)` instead of the seeded forage/move
rotation. Pure re-ordering of an ALREADY-valid reflex action (`move_to`) — never adds an action,
never makes a call, deterministic (place matched by sorted id/name substring). Survival/work
picks are never overridden.

## 5. `plan_revised` event — `agents/runtime.py`

Mirrors `commitment_made` (rides `extra_events` → `_multi`; the loop tick-stamps, persists via
`repository.save_event`, and broadcasts — no kind allowlist):
```python
{"kind": "plan_revised", "actor_id": agent.id, "profile": profile_name,
 "profile_color": profile_color, "text": f"{agent.name} plans: {goal}",
 "payload": {"plan_id", "goal", "steps", "reason", "old_plan_id"}}
```
Frontend: a feed glyph + membership in the existing `diary` channel (data-only; surfaced, not gating).

### Out of scope (v1 — matches the spike)
Hourly/minute sub-decomposition; cross-agent shared plans; the `plan_advance` salience call lever
(unit 5b, ships disabled — NOT wired in 1–5a); learned step durations. Step-pointer advance is a
deterministic v1 heuristic (a successful non-talk resolution advances `current_step` by one, capped),
flagged in the spike's open risks for live tuning.

## Definition of done
`world.planning.enabled` default False ⇒ prompt golden + snapshot key-set byte-identical. With it
on: additive snapshot round-trips with/without a plan; `plan_revision` folds into a turn with zero
extra LLM calls; plan-biased reflex stays zero-call and only re-orders valid actions; gate/floor
state (`reflex_streak`, salience, spontaneity) provably untouched by plan mutation; `plan_revised`
persists + broadcasts. Mock-deterministic; fork/replay byte-stable (EM-155). Backend suite green.

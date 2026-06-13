# Multi-Action Turns (EM-199)

> Action protocol **v1.2.0** — one turn may carry an ORDERED *sequence* of
> actions, applied in order, all from a **single LLM call**, emitted as one
> `_multi` chain sharing one `turn_id`. Restores the "session-189" feed flood:
> `move` + `contribute_funds` + `say` from one call → three feed lines, not one
> dull `works on (60% built)`. Strictly additive; the single `action` form stays
> valid byte-for-byte (legacy responses, Mock/deterministic agents, reflex
> turns, every existing test).

## Why

North star: agents do **MORE per call**, never less (see memory
`session-189-rate-is-the-target`). The roster is all-protagonist, so every agent
already calls the LLM every turn — the lever for "do more" is richer turns, not
more calls. A single call that yields `move → fund → say` triples feed activity
at the same request rate.

## The shape

The model returns ONE JSON object per turn. Turn-level **cognition** fields stay
singular (one per turn): `thought`, `mood`, `perceived_summary`,
`memories_used`, `reasoning`, `commitment`, `reflection`, `bond`. What pluralizes
is the **action**:

```jsonc
// NEW (preferred): an ordered sequence
{
  "thought": "Fund the well, then rally the plaza.",
  "mood": "purposeful",
  "actions": [
    { "action": "move_to",         "args": { "place": "well" } },
    { "action": "contribute_funds","args": { "building_id": "well_1", "amount": 5 } },
    { "action": "say",             "args": { "text": "I chipped in for the well — who's with me?" } }
  ]
}

// LEGACY (still valid): a single action
{ "thought": "Earn first.", "action": "work", "args": {} }
```

### Schema rules (action-protocol v1.2.0)

- Top-level `required` relaxes from `["action"]` to **`anyOf: [{required:[action]}, {required:[actions]}]`** — exactly one form is needed; a response may carry both (then `actions` wins; see Resolution).
- `actions`: `array`, `minItems 1`, `maxItems = max_actions_per_turn` (config; default **4**). Each item: `{ action: <enum>, args: object }`, `additionalProperties: false`.
- Every per-action `if/then` arg conditional in the canonical schema gains `required: ["action"]` in its `if`, so the legacy arg-strictness fires **only** for the top-level single `action` and never misfires on an `actions[]`-only response.
- Per-**step** arg requirements (e.g. `say` needs `text`, `give` needs `target`+`amount`) are NOT enforced at top-level JSON-Schema time for the `actions[]` form; they are enforced at **resolution** (continue-on-failure, below). The single `action` form keeps its existing top-level arg strictness (a malformed single action still costs the turn → retry → idle, unchanged).

## Resolution semantics (runtime.py, LLM path only)

1. **Normalize** the parsed object to an ordered `steps` list:
   - `actions` present & non-empty → `steps = actions` (the single `action`, if also present, is ignored).
   - else → `steps = [{action, args}]` from the legacy fields.
2. **Cap**: truncate `steps` to `max_actions_per_turn`; dropped steps are `log`-warned (never silently capped).
3. **Apply in order.** Each step runs the *same* pipeline a single action does: per-step `_normalize_args` (collapse arg aliases like `destination→place`, resolve agent **names** to ids — EM-140) → `_validate_world` gate → `_apply_action_inner` dispatch. Gating is per-step **at apply time**, so a step is checked against the state the prior steps just produced — a `work` step after a `move_to` step validates at the *destination*, not the origin. All resulting events (and each step's drained relationship shifts) concatenate into ONE `_multi` chain, in execution order.
4. **Continue-on-failed-step.** A gated / invalid / exception-raising step emits its `parse_failure` event and execution **continues** to the next step. The `say` still happens even if the `contribute_funds` was rejected. A step never aborts its siblings and never fails the whole turn. (This is more resilient than the single-action form by design — "do more".)
5. **Thought surfaced once.** `thought` (💭) appends to the **first** event of the whole chain only, never per-step.
6. **Reflex turns are unchanged** — `_reflex_turn` resolves ONE deterministic instinct action; multi-action is an LLM-path affordance only.

### Decision-trace shape (`action_chosen`)

Back-compat is strict: `chosen_tool` / `args` / `tier` keep the **first** step's values (existing consumers — `loop._emit_trace_chain`, `repository`, `test_arg_normalization`, `test_turn_latency_guard` — read these unchanged). An **additive** `actions` array (`[{action, args, tier}, …]`) is attached **only when `len(steps) > 1`**, so every single-action and reflex trace keeps its exact current key set (preserves exact-equality assertions). `resolved.outcome` is `"ok"` if **any** step resolved ok, else `"failed"`; `state_deltas` aggregate (sum) across steps.

### Cognition interactions

- **EM-081 overheard**: distributed for **each** `say`/`whisper` step that resolved ok (not just the first).
- **EM-079 commitments**: follow-through credited if **any** step matches the open commitment; lapse logic sees the full set of actions taken.
- **EM-125 bond / EM-080 reflection / EM-145 god-voice**: unchanged — turn-level, appended once after all steps.

## Config

`world.params.max_actions_per_turn` (int, default **4**) in `config/world.yaml` and
`config/world.city25.yaml`, threaded into the runtime and the turn prompt. A
generous guardrail, not a throttle: it is 4× the old limit of 1 and covers the
owner's stated cases (`move`+`fund`+`say`, `move`+`charge`+`fund`+`say`).

## Prompt

Both `format_template` variants (protagonist/supporting + background) and the
trailing instruction gain the `actions` affordance: *"To do several things this
turn, return an `actions` list (up to N) — e.g. move somewhere, act there, and
say something about it, in order. A single `action` is still fine for one thing."*
The ⚠ words-change-nothing warning stays.

## Frontend

**Zero changes.** `loop._execute_turn` already splits a `_multi` result into
separate persisted/broadcast events sharing one `turn_id`, and the feed renders
each event as its own line. Three steps → three feed lines, automatically. QE
verifies no regression via the shared `events.schema.json`.

## Out of scope (follow-ups)

- Visual grouping of a turn's lines in the feed (they render fine ungrouped).
- Raising agent count / cadence changes (roster is already all-protagonist,
  every-turn-LLM; that lever is separate).

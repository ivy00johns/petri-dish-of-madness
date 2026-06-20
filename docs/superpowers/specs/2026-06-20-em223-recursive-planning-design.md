# EM-223 — Recursive + reactive planning (design / spike findings)

> Status: **spike — awaiting "go".** This doc resolves the two open questions on the
> EM-223 ledger row and proposes a locked architecture. No code yet. Source research:
> `docs/research/smallville-to-sid-2026-06-18.md` (§"EM-223"). Sibling shipped: EM-222
> (relevance retrieval) — same Wave L, same call-rate-positive framing. Pairs with
> EM-224 (PIANO coherence), which consumes the plan as its "single decision" substrate.

## Goal

Give agents a **persistent, decomposed plan** they pursue across turns and **revise when
perception changes**, so routines become believable and multi-agent timing/location can
coordinate (the Smallville Valentine's-party mechanism). Today planning is purely
prompt-ephemeral — the model picks an action per turn with no carried intention
(`AgentState` has no goal/plan field; `world.py:93-129`).

## Findings — the two open questions, resolved

### Q1 — "How deep to decompose, given our tick cadence?" → **Two levels, not three.**

Smallville decomposes **day → hourly → 5–15-min**. That assumes a long sim-day. Ours is
**compressed**: `turns_per_day` defaults to **20** (`config/world.yaml:14`;
`world.day = world.tick // turns_per_day`, `engine/loop.py:734`), and a multi-action turn
(EM-199) already resolves up to 4 ordered actions in one call. A third "minute" level would
decompose *below a single turn* — meaningless.

**Decision:** a plan is **(a) a goal + 3–5 ordered NL steps** (the "5–8 daily chunks" analog,
trimmed to our shorter day) **plus (b) a `current_step` pointer**. One step ≈ one
multi-action turn ≈ ~4–6 ticks. Background-tier agents (act every 10th round,
`engine/world.py:767-779` ⇒ ~2 turns/sim-day) carry an even shallower plan: goal +
current step only. Numbers are **proposed defaults to re-tune against a live run** (the
research caveat: our multi-model mix + free-tier limits shift Smallville's tuning).

### Q2 — "How does re-planning interact with EM-159/160 — without fighting the spontaneity floor?"

The salience gate **already is** a perception-change detector. `_background_salience()`
(`agents/runtime.py:2781-2843`) flags a background agent's next turn as LLM-worthy on:
new co-location, witnessed-importance, energy-band flip, pending whisper, active
proclamation, unseen board note, uncast vote. That is precisely "perception changed."

**Decision — re-planning *rides* the gate; it never modifies it:**

1. **Re-plan = a normal LLM turn the agent was already granted.** Plan creation/revision is an
   optional `plan_revision` field in the same JSON response as actions (folded like
   `commitment`/`reflection` — `runtime.py` schema `44-50`, reflection request `3057-3059`).
   **Zero extra LLM calls.** When the gate grants a turn (salient, or wildcard, or the
   reflex-streak "reassess" at `reflex_streak` ≥ `reflex_streak_limit`=8), the prompt shows the
   current plan **plus** the changed circumstance, and the model may revise from that step.
2. **The plan is read-only context — it cannot raise salience, reset `reflex_streak`, or alter
   the spontaneity roll.** A mid-plan background agent that perceives nothing new stays
   reflex-gated; the seeded 15% `spontaneity_chance` (`config/loader.py:694`) still fires blind.
   The floor stays fully in charge — the plan layer sits strictly *on top* of it.
3. **Plan-aware reflex (zero-call) carries routines between LLM turns.** `_reflex_pick()`
   (`runtime.py:2865-2902`) is deterministic; when an agent has an active plan we **bias** that
   existing pick toward the current step (e.g. step says "stake the plot at the commons" ⇒ the
   reflex prefers `move_to(commons)` over seeded rotation). Still no LLM call — believability
   without cost. This is *how* "more believable routines" is delivered at our cadence.
4. **Daily refresh is a stale-flag, never a forced call.** At day rollover the plan is marked
   stale; the agent's **next gate-granted** turn re-plans. We do **not** inject a forced
   per-day planning call (that would override the background gate for ~every agent every 20
   ticks — exactly "fighting the floor"). Protagonists/supporting (never gated) refresh
   naturally on their first turn of the new day.

## North-star note (honest accounting of where calls come from)

The research framed EM-223 as "deeper plans ⇒ more calls." At our **compressed** cadence that
premise only **partially** holds: re-plan and daily-plan ride turns the agent was already
taking, so the *base* design is call-rate-**neutral** and pays off mostly in **quality**
(coordination, routines) at ~zero marginal call cost. The genuine, north-star-aligned call
lever is **opt-in and perception-gated**:

- **Optional `plan_advance` salience trigger** (new knob, default **off**): an agent with an
  active plan whose **current step's preconditions are now satisfied** (e.g. it has arrived at
  the step's location, or the needed credits/material now exist) becomes **salient** → earns an
  LLM turn to advance the step. This *adds* calls — but only on a real perception event, so it
  is consistent with EM-159's contract and **does not** bypass the floor. Ship the base design
  first; enable this lever once a live run shows the floor is healthy.

## Proposed architecture — five additive units (pending "go")

1. **Plan state (additive `AgentState.plan`).** `plan: dict | None = None` —
   `{goal, steps:[str], current_step:int, made_tick:int, stale:bool}`. Serialize only when set
   (the `cap_demotions`/`parents` additive pattern, `world.py` `to_dict` `131-163` / `4149-4154`);
   `from_snapshot` defensive-restores to `None` for pre-EM-223 snapshots (`world.py:4246-4291`).
   Snapshot-additive ⇒ old forks/replays load unchanged.
2. **Plan block in context.** A `=== YOUR CURRENT PLAN ===` block in `_assemble_context()`
   (`runtime.py:1488-2170`), slotted **after ACTIVE COMMITMENTS, before BELIEFS** (~line 2127).
   Prompt-diet aware (EM-161): background uses a `made at plan_tick N` static stamp, **not**
   "made 3 ticks ago" (cache-stable, EM-171). Always invites abandonment ("if circumstances
   changed, act freely") so the plan never overrides spontaneity.
3. **`plan_revision` turn field (zero extra call).** Optional object in `ACTION_SCHEMA`
   (`runtime.py:44-50`) — `{goal, steps[], reason}` — parsed once per response beside
   `commitment`/`reflection`. Emits one `plan_revised` event.
4. **Plan-aware reflex bias (zero call).** Inside `_reflex_turn()` (`runtime.py:2904-2990`),
   filter/bias the deterministic `_reflex_pick()` toward the current step. Pure re-ordering of
   *already-valid* reflex actions; never adds an action or a call.
5. **`plan_revised` event + optional `plan_advance` salience trigger.** Event mirrors
   `commitment_made` (`runtime.py:2670-2676`): `{kind:"plan_revised", actor_id, profile,
   profile_color, tick, text:"<name> plans: <goal>", payload:{plan_id, goal, steps, reason,
   old_plan_id}}`; persisted via `repository.save_event` (`265-287`), broadcast on the normal
   pipeline, surfaced in the feed. The `plan_advance` trigger (unit 5b, **default off**) adds one
   precondition check to `_background_salience()`.

## Data flow (a protagonist/supporting turn)

```
run_turn → (plan stale? day rolled? → leave for the model to revise)
  _assemble_context: …commitments → [YOUR CURRENT PLAN: goal + steps + current_step] → beliefs…
  one LLM call → {thought?, actions[]|action, commitment?, reflection?, plan_revision?}
  if plan_revision: agent.plan = normalize(plan_revision); emit plan_revised   # no extra call
  apply actions in order (EM-199); advance current_step if a step's action resolved
# background non-salient turn: _reflex_turn → plan-biased _reflex_pick (zero LLM calls)
```

## Out of scope (v1)

Hourly/minute sub-decomposition (collapses at 20-tick days); cross-agent shared/joint plans;
plan-conditioned dialogue beyond what the prompt block already affords; the `plan_advance`
call lever **ships disabled**; learned step durations. All notable as follow-ups.

## Open risks (what the spike could not settle without a live run)

- **Decomposition tuning** (steps-per-plan, ticks-per-step) needs a live run to confirm a 3–5
  step plan doesn't out-pace a 20-tick day or go stale before it completes.
- **Reflex-bias vs. spontaneity feel:** biasing reflexes toward the plan could make background
  agents *look* more scripted, not less — must verify on camera it reads as "purposeful," not
  "on rails." The abandonment invitation (unit 2) is the safety valve.
- **`plan_advance` lever** must be validated to not silently erode the floor before it's
  enabled (gate it behind a live-run check, like EM-159 was gated on EM-160).

## Recommendation / Definition of done (for the build, on "go")

Build units 1–5a (lever 5b off). Backend suite green (current 922 + new EM-223 tests:
additive snapshot round-trips with/without a plan; `plan_revision` folds into a turn with zero
extra calls; plan-biased reflex stays zero-call and only re-orders valid actions; gate/floor
state is provably untouched by plan mutation; `plan_revised` event persists + broadcasts).
Mock-deterministic; fork/replay byte-stable (EM-155). Then a live run to tune Q1 numbers and
decide whether to flip `plan_advance` on. Write `contracts/em223-recursive-planning.md` at
build start (the EM-222 contract is the template).

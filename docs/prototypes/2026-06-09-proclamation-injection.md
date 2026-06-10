# Prototype — God-channel: proclaim, answer, name the town (2026-06-09)

**Branch:** `fix/reasoning-model-token-exhaustion` · **Status:** working, all backend tests green (275 passed)

> Three slices landed: (1) the loud **proclamation injection** (god → every agent),
> committed as `31265e5`; (2) the threaded **return path** (`answer_proclamation`,
> agent → god), committed as `1f763db`; (3) **`name_town`** — naming the town by
> consensus vote. This doc covers all three.

## Why

The god could already post to the billboard, but a billboard note is **opt-in**: an
agent must (a) stand at the plaza/town hall and (b) spend a turn choosing
`read_billboard`. Two gates, both rarely met — which is why "I asked them to name
the town and nobody did." The post sat on a board nobody was looking at.

This prototype builds the **loud tier** of the god↔town channel: a *proclamation*
that is injected into **every agent's prompt** each turn until superseded, so the
god's word is guaranteed to reach the whole world. It reuses the EM-081 overhearing
pattern — **zero extra LLM calls**, the injection rides the turn each agent was
already taking (free-scale / subscription-only safe).

These are the first three slices of the approved design
(`The God Channel + Town Editing`). The **move/demolish** verbs are the next
slice, not in this prototype.

## What changed

| File | Change |
|---|---|
| `backend/petridish/engine/world.py` | New `world.proclamations` state; `active_proclamation()`; `post_proclamation_as_god(text)` → `proclamation_posted`; **`answer_proclamation(agent, text)`** → threads the reply and returns `proclamation_answered`. New `world.town_name` + **`name_town`** governance effect: `action_propose_rule` accepts it (carrying the name on the rule payload, exempt from renewal), and `_on_rule_activated` sets `town_name` + parks a `town_named` event when the vote passes. Serialized in `to_snapshot()`/`from_snapshot()` (exact round-trip, replies + town_name included). |
| `backend/petridish/agents/runtime.py` | `_assemble_context` injects the `📜 THE GOD HAS PROCLAIMED` block under `=== NEEDS ===`, offers `answer_proclamation` whenever a decree is live (no location gate), and renders a `Town:` header line (the name, or a nudge to `name_town` when unnamed). `answer_proclamation` + `name_town` wired through the action enum / arg schema / `TOOL_REGISTRY` / `_validate_world` / dispatch; `propose_rule` plumbs the `name` arg through. |
| `backend/petridish/api/app.py` | New `POST /api/proclaim {text}` (god surface), mirroring `/api/billboard`: calls the engine seam, emits `proclamation_posted`, broadcasts world state. 503 not-initialized / 422 empty-or-too-long. |
| `backend/tests/test_proclamation.py` | New — 13 unit tests (see below). |

## How it works

1. `POST /api/proclaim {"text": "..."}` → `world.post_proclamation_as_god(text)`
   appends `{id, tick, text, replies:[]}` to `world.proclamations` (cap 20) and
   returns a `proclamation_posted` event (`actor_type:"god"`).
2. The api layer emits that event through the normal pipeline (god-ink feed line)
   and broadcasts world state. Because `to_snapshot()` is the live world-state seam
   (`loop._broadcast_world_state`), `proclamations` now flows to the frontend
   `world_state` automatically — the data is there for a future panel/thread UI.
3. On each agent's next turn, `_assemble_context` finds the active proclamation and
   renders it into the prompt under NEEDS:

   ```
   === 📜 THE GOD HAS PROCLAIMED ===
     "Decide on a name for this town."
     The god's word reaches every soul in the world. You may heed it, defy it,
     or carry on — but you have heard it, and so has everyone else.
   ```

   It stays in every prompt until the god issues another proclamation (newest wins).
   Tone is **suggestion, not command** (the approved design) — agents can defy it.
4. While a decree is live, every agent is also offered `answer_proclamation (text)`
   in VALID ACTIONS (no location gate — the god's voice is everywhere). Choosing it
   calls `world.answer_proclamation`, which **threads** the reply into the active
   proclamation's `replies` and emits `proclamation_answered` (`↳ <name> answers the
   god: "…"`). So you get a legible exchange — the decree and its answers grouped —
   in both the feed and `world_state.proclamations`. Still zero extra LLM calls: the
   answer rides the agent's own turn.
5. **Naming the town is by consensus**, not decree. An agent at a governance place
   proposes `propose_rule(effect="name_town", name="Hopewell", text="…")`; when the
   vote passes (the existing majority threshold), `_on_rule_activated` sets
   `world.town_name` and parks a `town_named` event. The name then rides every
   prompt's `Town:` header; an unnamed town shows a nudge toward `name_town`. A later
   passing name supersedes the old one (it's a one-shot rename, exempt from the
   UBI-style renewal guard). So the god can *ask* "name the town," but the town
   *decides* — proclaim → answers → a naming vote → a committed name.

## Try it

```bash
# with the backend running:
curl -X POST localhost:8000/api/proclaim -H 'content-type: application/json' \
  -d '{"text":"Decide on a name for this town, and build a hall to mark it."}'
```

Every agent's next turn will carry the proclamation. Watch the feed for the
`📜 GOD proclaims to all: "..."` line, then watch agents react in their
`thought` / `say` / actions.

## Tests

`backend/tests/test_proclamation.py` (pure unit, no loop/provider/db — calls
`_assemble_context` directly, the same seam the W11b cognition tests pin):

- `test_no_proclamation_means_no_block` — clean prompt when no decree is active.
- `test_proclamation_reaches_every_agent_regardless_of_location` — the block lands
  in **both** Ada's (plaza) and Bo's (market) prompts; a billboard note never would
  reach Bo. Also asserts the emitted event shape.
- `test_newest_proclamation_is_the_active_decree` — a second proclamation supersedes
  the first in the prompt.
- `test_proclamations_round_trip_through_snapshot` — `to_snapshot → from_snapshot →
  to_snapshot` preserves proclamations exactly (fork/snapshot safe).

Return path:

- `test_answer_threads_under_the_active_proclamation` — Bo (at the market) answers;
  the reply threads into `replies` and the event carries `in_reply_to`.
- `test_answer_with_no_active_proclamation_is_a_parse_failure` — answering into the
  void fails cleanly.
- `test_answer_action_is_offered_only_while_a_decree_is_live` — the action appears in
  both agents' prompts only after a proclamation, regardless of location.
- `test_validator_gates_answer_on_an_active_proclamation` — `_validate_world` requires
  a live decree + non-empty text.
- `test_replies_round_trip_through_snapshot` — threaded replies survive snapshot/fork.

Naming (consensus):

- `test_naming_the_town_by_vote_sets_the_name_and_emits` — a passing `name_town` vote
  sets `town_name` and parks the `town_named` event.
- `test_name_town_requires_a_name` — a nameless naming proposal is rejected (world +
  validator).
- `test_a_new_name_supersedes_the_old_one_not_a_renewal` — a second naming activates
  and overwrites (not swallowed as a renewal).
- `test_town_name_surfaces_in_prompt_and_round_trips` — unnamed shows the nudge; Cy
  (at the town hall) is offered `name_town`; after the vote the `Town:` header shows
  it; snapshot round-trips it.

Full suite: **275 passed**.

## Honest gaps (deferred, by design)

- **No UI.** The data flows to `world_state` (`proclamations`, `town_name`) and the
  feed gets `proclamation_posted` / `proclamation_answered` / `town_named` events,
  but there's no god-panel "PROCLAIM" button and the frontend event registry doesn't
  know the new kinds yet (generic fallback render).
- **Stale active `name_town` rules.** A rename leaves the previous (applied)
  `name_town` rule in `status="active"`, so the active-rules list can show more than
  one over time. Harmless (`town_name` reflects the latest), cosmetic only.
- **No contract version bump** (api / event-log / events.schema). This is a
  prototype on the branch; the contract changes belong with the full spec.

# Prototype — God-channel proclamation injection (2026-06-09)

**Branch:** `build/w11a-ui-batch` · **Status:** working, all backend tests green (259 passed)

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

This is the first slice of the approved design
(`The God Channel + Town Editing`). The agent **return path** (threaded
`answer_proclamation`) and the **move/demolish** verbs are the next slices, not in
this prototype.

## What changed

| File | Change |
|---|---|
| `backend/petridish/engine/world.py` | New `world.proclamations` state; `active_proclamation()` (newest = active decree); `post_proclamation_as_god(text)` → ready-to-emit `proclamation_posted` event. Serialized in `to_snapshot()` and restored in `from_snapshot()` (exact round-trip). |
| `backend/petridish/agents/runtime.py` | `_assemble_context` injects a `📜 THE GOD HAS PROCLAIMED` block (the active proclamation) into the system prompt, placed just under `=== NEEDS ===`. Reads `world.active_proclamation()` directly — no new param, `getattr`-guarded. |
| `backend/petridish/api/app.py` | New `POST /api/proclaim {text}` (god surface), mirroring the existing `/api/billboard` handler: calls the engine seam, emits `proclamation_posted`, broadcasts world state. 503 not-initialized / 422 empty-or-too-long. |
| `backend/tests/test_proclamation.py` | New — 4 unit tests (see below). |

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

Full suite: **259 passed**.

## Honest gaps (deferred, by design)

- **Return path not built.** Agents can't yet *answer* a proclamation in a threaded
  way (`replies:[]` is reserved but unused). They will react in their normal
  thought/speech/actions, but there's no `answer_proclamation` action yet.
- **No `name_town` affordance.** Even though the request now reaches them, there is
  still no verb to actually set a town name — so "name the town" will surface
  reactions, not a committed name, until that affordance lands.
- **No UI.** The data flows to `world_state.proclamations` and the feed gets a
  `proclamation_posted` event, but there's no god-panel "PROCLAIM" button and the
  frontend event registry doesn't know the new kind yet (generic fallback render).
- **No contract version bump** (api / event-log / events.schema). This is a
  prototype on the branch; the contract changes belong with the full spec.

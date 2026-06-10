# Wave A.2 — god console (contract v1.0)

> Build branch: `build/wave-a-live-run-fixes` (continues Wave A) · Date: 2026-06-10
> Items: EM-136 (targeted interventions), EM-137 (god whisper) — backend-god
> · EM-138 (GOD CONSOLE panel) — frontend-god
> Origin: user watched an agent starve with only world-wide levers available
> ("I can give a windfall. these controls need a revamp.").

## Global rules

Same as `contracts/wave-a.md`: exclusive file ownership, no git, free-scale law
(every intervention is reflex/deterministic — ZERO LLM calls), tests are part of
the item, additive-only event/snapshot changes, code reads like its surroundings.

## Agent G — backend-god

Owns: `backend/petridish/engine/world.py`, `backend/petridish/agents/runtime.py`
(ONLY the context-assembly whisper block), `backend/petridish/api/app.py`,
NEW `backend/tests/test_god_console.py`.

### EM-136 — targeted god interventions
Engine seam `world.god_intervene(kind, agent_id, amount) -> dict` (event dict,
following the existing `post_billboard_as_god` / `post_proclamation_as_god`
seam pattern — study those plus the RANDOM_EVENTS injects in `engine/loop.py`
~line 50 for the house style):
- `bless_energy`: agent.energy = min(100, energy + amount); default amount 25.
- `grant_credits`: agent.credits += amount; default 10.
- amount validated 1..100; unknown kind / unknown or DEAD agent → ValueError
  (the API maps to 422; resurrection is explicitly out of scope).
- Returns a `god_intervention` event: actor_id "god", actor_type "god",
  target_id agent.id, feed text in the god voice (e.g. "✦ god restores Bram —
  +25 energy"), payload {kind, amount, before, after} (additive).
API: `POST /api/god/intervene {kind, agent_id, amount?}` — mirror the existing
`/api/god/billboard` endpoint's shape exactly (503 world-not-initialized via the
same guarded-seam pattern, 422 validation, event emitted + persisted + broadcast
through the same helper that endpoint uses).

### EM-137 — god whisper (one-shot targeted context injection)
- `world.post_whisper_as_god(agent_id, text) -> dict`: queue the line on
  `world.pending_whispers: dict[agent_id, list[str]]` (new field, NOT in
  to_snapshot()'s contract surface unless trivially additive); text capped at
  280 like billboard. Unknown/dead agent → ValueError. Returns/emits
  `whisper_posted` event (actor_type "god", target_id, feed text
  "✦ god whispers to Bram" — the whisper CONTENT is in the payload, and the
  feed line may include it; this is a spectator app, nothing is secret).
- Delivery: in `agents/runtime.py` `_assemble_context`, pop the agent's pending
  whispers (consumed exactly once, mirroring how `pending_overheard` is consumed
  in `run_turn`) and render them as a clearly-framed block ("A voice only you
  can hear...") in the prompt. One-shot: next turn after delivery has no trace.
  Free-scale: context injection only, zero extra LLM calls.
- API: `POST /api/god/whisper {agent_id, text}` — same endpoint pattern as above.

### Tests (minimum)
bless clamps at 100 / grant adds / amount+kind+agent validation incl. dead
agents; events carry actor_type god + target_id + before/after; whisper queues,
rides exactly the target agent's NEXT context once (assert present in messages,
absent on the following turn, absent from other agents' contexts); API: 200
happy paths, 422s, 503 uninitialized; full backend suite green.

## Agent H — frontend-god

Owns: `web/src/components/controls/ControlPanel.tsx` and its test file(s), plus
the API-client module ControlPanel already imports for its god calls (extend in
place; check what `/api/god/billboard` + inject use today). Do not touch feed
or world3d files.

### EM-138 — GOD CONSOLE
Reorganize the god section of ControlPanel into three labeled groups, keeping
the existing god-ink visual idiom (the `--lab-god-*` tokens used by billboard
god styling — no new color system):
1. **WORLD EVENTS** — the existing 4 inject buttons (windfall/famine/blackout/
   festival), unchanged behavior.
2. **INTERVENE** — agent selector (living agents only) + three actions:
   BLESS (+25 energy → POST /api/god/intervene bless_energy),
   GRANT (+10 credits → grant_credits),
   WHISPER (text input ≤280 → POST /api/god/whisper). Optimistic-free like the
   billboard reply (no local echo — the event arrives via the feed/ws). Disable
   buttons while a request is in flight; surface 4xx/5xx as the panel's existing
   error treatment.
3. **VOICE** — the existing billboard reply + proclamation controls, moved into
   the group, unchanged behavior.

### Tests (minimum)
Vitest/RTL following the existing ControlPanel test idiom: groups render; agent
selector lists living agents; BLESS/GRANT/WHISPER fire the right fetches with
the right bodies; whisper input enforces the cap; error path renders. Full web
suite + `npm run build` green.

## Integration note (both agents)

Agent G lands the endpoints; Agent H codes against THIS contract's request
shapes (kind/agent_id/amount, agent_id/text) — if either side must deviate,
report a blocker instead of improvising. The orchestrator diffs the two sides
at the gate.

## Report format

Same JSON schema as `contracts/wave-a.md`.

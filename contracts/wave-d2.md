# Wave D2 contract — "population scaling" (W16: EM-170, EM-158–166)

> Source: deep-research-v4 §5 + v4-review guardrails + live evidence (run 248: 14–32s LLM
> calls froze the world; EM-170 filed from it). Goal: 25 agents (headroom 50) on free
> lanes with the world never visibly stalling — without flattening background agents into
> NPCs-on-rails.
>
> Build order (sequential lean batches — they share backend files, no parallel fan-out):
> **B1** EM-170 latency guard → **B2** EM-158 tiers + EM-160 floor + EM-159 salience +
> EM-166 observability (one agent — EM-159 must not exist without EM-160) → **B3**
> EM-161 prompt diet + EM-162 cache keys + EM-163 tier-gated tools → **B4** EM-165
> 25-agent casting + EM-164 measured verification (QE gate for the wave).
>
> Standing laws: free-scale (these items REMOVE calls; none adds a standing call),
> additive-only config/snapshot changes (old snapshots/configs stay valid), MockProvider
> verification (never paid keys), agents never commit, house import idiom (engine.world
> before agents.runtime in tests).

## B1 — EM-170 turn-latency guard

- Config: `world.turn_llm_budget_seconds: 12` (additive; `0`/absent ⇒ guard disabled ⇒
  exactly today's behavior). Both yamls (world.yaml + EMBEDDED mirror).
- In the agent turn path, the LLM consult (router.chat call chain, including its internal
  retry) is wrapped in `asyncio.wait_for(budget)`. On timeout: cancel cleanly, resolve
  the turn via the EXISTING idle-fallback path with reason `llm_timeout` (rides the same
  events/feed surface as provider_error fallbacks), stamp the llm_call trace event with
  `timed_out: true` + the real elapsed ms.
- Lane-health demerit: report the timeout into the EM-135 per-routed-via health tracking
  in the Router (same mechanism truncation uses) so a lane that keeps timing out gets
  deprioritized/quarantined by the existing logic.
- Animals/narrator already run off the critical path — out of scope (note, don't touch).
- Tests: stub adapter sleeping past budget ⇒ idle fallback + `llm_timeout` + demerit
  recorded + world tick proceeds; budget disabled ⇒ no wait_for semantics change; budget
  generous ⇒ normal turn unaffected; full suite green.

## B2 — EM-158 cadence tiers + EM-160 spontaneity floor + EM-159 salience gating + EM-166 observability

ONE agent builds all four (single coherent scheduler/runtime change; EM-159 without
EM-160 is forbidden by the v4-review verdict).

- `AgentState.cadence_tier: "protagonist" | "supporting" | "background"` — additive,
  default **protagonist** (zero behavior change until assigned); settable in world.yaml
  agent entries, the spawn API body (optional field), and a new
  `POST /api/agents/{id}/tier`. Serialized in snapshots (additive, default protagonist).
- Scheduler (`world.next_agent()` / loop): protagonists act every round; supporting every
  3rd round; background every 10th. A "round" remains the existing sorted-id rotation
  within the due set. Round counting derives from world state (not wall time) and
  survives snapshot/restore.
- Salience gating (EM-159, **background tier only — never protagonists, supporting acts
  normally when due**): when a background agent's turn comes due, run the LLM only if
  salient since its last LLM turn — any of: new co-located agent/animal, witnessed event
  with importance weight > 0 (the existing `_importance` accumulator), energy crossing a
  threshold band, pending whisper/proclamation/board note, active rule vote it hasn't
  cast. Otherwise resolve a deterministic reflex routine (the animals' seeded picker
  pattern): starving⇒recharge, at-work⇒work, else forage/move-home rotation — zero LLM
  calls, normal events emitted with a `payload.reflex: true` marker.
- Spontaneity floor (EM-160, inseparable): (a) wildcard — each due-but-non-salient
  background turn has a seeded `spontaneity_chance` (config, default 0.15) of taking a
  full LLM turn anyway; (b) floor timer — any agent reflex-only for
  `reflex_streak_limit` (config, default 8) consecutive due turns gets a forced LLM
  "reassess" turn. Both configurable under `world.cadence` (additive block).
- EM-166 observability: turn events carry `cadence_tier`; reflex turns are markable in
  the feed/inspector (additive payload fields, no schema migration — kind stays
  `agent_action` etc.); a per-agent `reflex_streak` is visible in the agent panel payload
  (`world_state` agents gain optional `cadence_tier` + `reflex_streak`). Frontend: tier
  chip in the agent strip/panel + a subtle reflex marker on feed rows (small, additive —
  one frontend file pass).
- Tests: tier scheduling cadence math (round due-sets across 30 rounds), salience
  triggers each fire, non-salient ⇒ reflex with zero router calls (prompt-capture/call-
  count proof — the free-scale idiom from W11b), wildcard + floor force LLM turns
  (seeded, deterministic), default-protagonist config unchanged behavior, snapshot
  round-trip of tier/streak/round counters.

## B3 — EM-161 prompt diet + EM-162 cache-key normalization + EM-163 tier-gated tools

- EM-161 (background + supporting tiers only; protagonists keep full prompts):
  relationships block capped to top-8 by |trust|; `open_projects` + `move_to` place list
  scoped to the agent's district + adjacent; decision-trace instruction block dropped
  (background only) — completion shrinks accordingly; `memory_window` 12→8 (background
  only). Cerebras 8K context is the correctness backstop — add a prompt-size assertion
  test at 25 agents.
- EM-162: for background-tier prompts, bucket energy to 10s and floor the tick to the
  day in the prompt text so the router's sha1 decision cache can hit on quiet rounds;
  `forget()` semantics untouched; measure and report hit rate before/after in tests via
  the cache's stats.
- EM-163: `propose_project`, `build_step`, `contribute_funds` (proposal-side),
  `propose_rule` gate to protagonist+supporting at RESOLUTION time (match the billboard
  location-gate pattern — prompt-only gating is the EM-108 lesson); background keeps
  talk/move/economy/billboard. Valid-actions menu reflects the gate (don't offer what
  resolution rejects).
- Tests: prompt-capture proofs of each diet cut; cache-hit improvement demonstrated on a
  scripted quiet loop; resolution-time rejection + menu omission for background tier.

## B4 — EM-165 casting + EM-164 measured verification (wave QE gate)

- EM-165: `config/world.yaml` 25-agent roster from the persona library (5 protagonists —
  the existing named cast stay protagonists — 8 supporting, 12 background), tier
  assignments, spread across all 7 real lanes; population cap honored; `agent_count`
  semantics preserved. A smaller default stays possible (the 25-roster can live as a
  documented config variant if the user prefers the small cast day-to-day — decide WITH
  the orchestrator at gate time).
- EM-164 (QE): on MockProvider first (engine correctness at 25 agents), then a bounded
  FreeLLMAPI live run: measure tokens/turn, realized cache-hit rate (the v4 table assumed
  50–60% — report the real number), turns/hour, per-lane pressure vs caps, and the
  worst single-turn stall with EM-170 active (must be ≤ budget + epsilon). Produce
  `coordination/qa-report.json` (wave-D2) + verdict against the v4 scaling table.
  **This is the wave gate; W17 doesn't start without it.**

## Gates (orchestrator, every batch)

Full backend pytest + web vitest + tsc + build; live spot-check after B1 (induce/observe
a slow lane: world never freezes past ~12s) and after B2 (tier chips visible, reflex
turns in feed, protagonists chatty). The QA gate rules from previous waves apply to B4's
report. Per-batch commits by the orchestrator.

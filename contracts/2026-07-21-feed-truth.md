# Feed Truth (W1+W2, overnight 2026-07-21) · Contract v1.0

> **SUPERSEDED in part (2026-10-05, EM-340/EM-342):** §B1's `parse_failure`
> `cause` discriminator field was never adopted; the taxonomy was instead split
> into distinct EVENT KINDS (`action_rejected` / `provider_error` /
> `parse_failure` — see `event-log.md` v1.5.0). §B2–B4 remain the historic plan.

> **Plan:** `docs/plans/2026-07-21-overnight-everything-plan.md` §W1/§W2
> **Evidence:** scratchpad `research/fallback-review.md` (failure taxonomy: ~44%
> `rejected:True` world-side, ~30% lane-side) + `research/pain-points.md` (#1, #2, #3)
> **Branch:** `build/overnight-feed-truth` (worktree `../petri-dish-build`)
> **Hard steer:** fix-don't-hide. Every change ADDS information to the feed or
> removes an error at its cause. Nothing suppresses, filters, or downgrades an error.

## File ownership

| Agent | Owns |
|---|---|
| **lanes-agent** | `config/profiles.yaml`, `config/lanes.yaml`, `config/personas.yaml`, cast-pin lines in `config/world.yaml` + `config/world.city25.yaml` (pins ONLY — keep the parity test green: any world-block change lands in BOTH files) |
| **feed-truth-agent** | `backend/petridish/**` (failure-emit + action-validation paths), `web/src/**` (feed error cards), matching tests in `backend/tests/` + `web/src/**` |

No other files without lead approval. Both world yamls change together or not at all.

## A. Lane fixes (lanes-agent)

1. Replace dead pins with live ids (verify each against a LIVE probe before writing —
   see §C): `groq-llama` (`llama-3.3-70b-versatile` is gone), `cerebras-glm`
   (`zai-glm-4.7` is gone), the embed model (`bge-m3` gone).
2. Tag `gpt-oss-120b` as a reasoning/truncation-risk model in the same mechanism the
   router already uses to skip reasoning models on strict-JSON turns; audit remaining
   profile claims (context, output cap, reasoning flag) against
   `scratchpad/freellmapi-models.json`.
3. De-stale `personas.yaml` `suggested_profiles` + the world.yaml/world.city25.yaml
   cast pins onto endpoints that pass the §C probe. Free lanes only. Do NOT raise
   max_tokens on free-lane paths (the #77 lesson).
4. Add new clean-JSON lanes for (probe-verified subset of): `glm-5.2`,
   `qwen3.5-122b-a10b`, `deepseek-v4-flash`, `kimi-k2.6`, `minimax-m3`.

## B. Cause-split + repair (feed-truth-agent)

### B1. `parse_failure` gains a `cause` field (additive)
`cause ∈ {rejected, truncated, no_json, exhausted, timeout, other}` on the event
payload, derived where the failure is already classified today (rejected:True flag,
finish_reason=length, no-JSON detour, all-lanes-exhausted, proxy timeout label).
Absent field ⇒ legacy rendering (old snapshots unchanged). Feed card copy per cause
(web): rejected → "⚠ action rejected: <reason> (model answered fine)", truncated →
"✂ reply truncated by <model>", exhausted → "⏳ all lanes rate-limited", timeout →
"⏱ lane timed out", no_json → "⚠ no JSON in reply". More information, never less.

### B2. Valid-target enumeration (prompt)
The decision prompt enumerates the ACTUAL valid targets compactly (place ids in the
agent's scope, co-located agent names, own inventory of valid verbs already listed).
Budget: measure prompt growth; total addition ≤ ~120 tokens on a default 5-agent
world. If scope lists are long (city25), truncate with "…and N more" — never let the
enumeration blow the output ceiling.

### B3. Validate-and-repair (visible, deterministic)
Before rejecting an action for an unknown target: exact match → case/whitespace-
insensitive → unique-prefix / display-name→id alias. If exactly one candidate
survives, EXECUTE with the repaired target and emit a new visible event
`action_repaired {agent, verb, from, to}` (System lane). Zero or 2+ candidates ⇒
reject as today, with `cause: rejected` + the specific reason string. Repair logic
is pure/deterministic (no LLM, no randomness) — replay-safe.

### B4. Metrics honesty
Add a tiny read-only helper (or reuse existing) so W7 can query: parse_failures by
cause per 1k llm_calls, before vs after. No schema migration — events only.

## C. Live-probe protocol (both agents)

A model id may be pinned ONLY after a live strict-JSON probe through the proxy:
`POST $FREELLMAPI_BASE_URL/chat/completions` with the repo's real action-schema
system prompt shape, `response_format` off (as production), max_tokens as production,
asserting: HTTP 200, JSON object extractable, `finish_reason == "stop"`. 2 probes
per candidate (rate-window tolerance). Log results to
`coordination/probe-results-2026-07-21.md`. Creds via `.env` (never hardcode).

## D. Acceptance bar

1. All three gates green in the worktree: `.venv/bin/python -m pytest` ·
   `/usr/local/bin/npx vitest run` · `npx tsc -b --force` (node_modules ELOOP
   workaround applies).
2. Determinism goldens untouched-green (B3 is deterministic; B1 is additive emit).
3. city25 parity test green (both world yamls in sync).
4. No error suppression anywhere in the diff — reviewer greps for removed emit
   lines / added filters; any found = wave FAIL.
5. `coordination/probe-results-2026-07-21.md` exists with per-model probe outcomes.

## Changelog
- v1.0 (2026-07-21): initial.

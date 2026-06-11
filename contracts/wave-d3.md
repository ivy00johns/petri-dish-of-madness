# Wave D3 contract — "self-healing lanes" (W17, part 1)

> Version: 1.0 · Date: 2026-06-11 · Branch: `build/wave-d3-lane-health`
> Items: **EM-177** (B1), **EM-168** (B2), **EM-171 + EM-172** (B3).
> Deferred this wave (written reasons): EM-167 (local Ollama not running — user
> setup required, port 11434 dead at contract time); EM-169/EM-176/EM-127
> (frontend — the user has live uncommitted edits to `CozyWorld.tsx`,
> `Ground.tsx`, `Structure.tsx`, `toon.ts`; no agent may touch those files).
>
> Triggering incident (2026-06-11 live run): every FreeLLMAPI lane except
> mistral-small was silently rerouted by the proxy to
> `nvidia/nemotron-3-super-120b` (a reasoning model that blows the 12s
> EM-170 budget on real prompts) — measured timeout rates: cerebras-glm 12/19,
> qwen-next 11/18, gemini-flash 11/39, groq-llama 3/6, mistral-small 0/6;
> deepseek-pro hung outright. Fourth manual lane rescue in two sessions.
> The router KNOWS lane health (EM-135/170 windows) but nothing ACTS on it.

## Global rules (all batches)

- Backend-only wave. **Never touch** `web/`, `README.md`, `START-HERE.md`, or
  the four user-edited world3d files above.
- Free-scale law: no change may add a standing LLM call. Failover/probing
  re-route calls that would happen anyway; they never add calls.
- Verification on MockProvider / unit tests only — never real paid keys.
- Agents do NOT commit — the orchestrator commits at batch gates.
- Existing test suite must stay green (`cd backend && source ../.venv/bin/activate && python -m pytest -q`).
  Tests must import `petridish.engine.world` BEFORE `petridish.agents.runtime`.
- Config params follow the EM-155 conventions: yaml → loader dataclass →
  snapshot round-trip → `EMBEDDED_WORLD_YAML` mirror in `loader.py` kept in sync
  → fork/replay safe. Snapshot is authoritative over params on restore.

---

## B1 — EM-177: lane failover with recovery probes (P1)

**Owner:** backend-agent-B1.
**Files owned:** `backend/petridish/providers/router.py`,
`backend/petridish/agents/runtime.py`, `backend/petridish/config/loader.py`,
`backend/petridish/api/app.py`, `config/world.yaml`,
`backend/tests/test_lane_failover.py` (new).

### Behavior spec

1. **Sickness predicate** (`Router.lane_sick(profile_name) -> bool`): a lane is
   SICK when its existing EM-135 outcome window (deque maxlen 6,
   `_lane_outcomes`) contains ≥ `sick_threshold` entries with
   `timed_out=True`. Default threshold **3**. Mock lanes are never sick.
   `provider_error` turns do NOT count (EM-173 keeps those idle on purpose).

2. **Detour** (`Router.effective_profile(agent_id, preferred) -> tuple[str, str | None]`):
   returns `(profile_to_call, reason)` where reason is `None` (home lane used),
   `"detour"` (home sick → healthy substitute), or `"probe"` (home sick but
   this call deliberately tests it — see 3).
   - Candidates for a detour: all non-mock profiles whose `available()` is
     True and which are NOT sick. Pick the one with the fewest `timed_out`
     entries in its window; tie-break by fewest detours already routed to it
     this run (track a counter), then stable profile order. No healthy
     candidate ⇒ return the home lane unchanged (never detour to mock,
     never give up the turn).
   - The agent's ASSIGNED profile never changes — identity, UI chip, and
     reassign API semantics are untouched. Detours are per-call.

3. **Recovery probe**: per home lane, count consecutive detoured calls; every
   `probe_every`-th (default **4**) call that WOULD detour goes through the
   home lane instead (`reason="probe"`). A successful probe appends a clean
   outcome (existing `note_parse_outcome` path) and the window ages the
   demerits out — automatic recovery, no timers, no clock reads.

4. **Runtime integration** (`agents/runtime.py`): resolve
   `effective_profile(...)` once per turn where the profile name is currently
   resolved; use the EFFECTIVE profile's `max_tokens`/`temperature`
   (`router.get_profile(effective)`); `note_parse_outcome` attributes the
   outcome to the EFFECTIVE lane (which it already does if the effective name
   flows through). The `llm_call` trace/event payload gains additive keys:
   `requested_profile` (home lane) and `detoured: true` / `probe: true` when
   applicable — `profile` stays the lane actually called (forensics
   compatibility: per-profile timeout queries keep meaning "what the lane
   did").

5. **Feed transparency, no spam**: emit a system event `lane_detour`
   (world event-log kind) ONLY on streak transitions — first detour of a
   streak ("⚠ gemini-flash lane is degraded — Ada is borrowing
   mistral-small") and on recovery ("✓ gemini-flash lane recovered — Ada is
   back home"). Per-turn truth lives in the llm_call payload, not the feed.

6. **Config** (`world.lane_failover`, EM-155 conventions):
   ```yaml
   lane_failover:
     enabled: true        # default ON
     sick_threshold: 3    # timed_out entries in the 6-window
     probe_every: 4       # every Nth would-be-detour probes the home lane
   ```
   `enabled: false` ⇒ byte-identical pre-D3 behavior (prove with a test).

7. **Observability endpoint**: `GET /api/lanes` in `api/app.py` returning
   `router.lane_health()` augmented per profile with `sick: bool` and
   `detours_routed_here: int`. No UI work this wave.

### Acceptance tests (minimum)

- Sick predicate: 3 timeouts in window ⇒ sick; 2 ⇒ not; mock never.
- Detour picks the healthiest candidate; load-spread tie-break; all-sick ⇒
  home lane; assigned profile unchanged after detours.
- Probe fires on the Nth would-be-detour; a clean probe outcome ages the lane
  back to healthy; a failed probe keeps it sick.
- `enabled: false` ⇒ `effective_profile` always returns home, zero new events.
- llm_call payload carries `requested_profile`/`detoured` on a detoured call.
- `lane_detour` event emitted exactly twice across a sick→recovered cycle.
- Config round-trips: yaml → params → snapshot → restore; embedded yaml mirror.
- `GET /api/lanes` shape test.

---

## B2 — EM-168: cap-pressure governor (P1)

**Owner:** backend-agent-B2 (dispatched only after B1 gate passes).
**Files owned:** `backend/petridish/engine/world.py`,
`backend/petridish/agents/runtime.py` (consume-only),
`backend/petridish/api/app.py` (usage-alert sink wiring already exists —
extend), `backend/petridish/config/loader.py`, `config/world.yaml`,
`backend/tests/test_cap_governor.py` (new).

### Behavior spec (per ledger EM-177-adjacent scope, research-v4 §5.6)

1. When a `usage_alert` fires for a profile (UsageAlertTracker ≥70% of
   rpd/tpd), every agent ASSIGNED to that lane is demoted ONE cadence tier
   (protagonist→supporting→background; background stays) with
   `demoted_from` recorded on `AgentState`.
2. Restoration: at the tracker's UTC-day rollover (the alert windows already
   reset daily) demoted agents return to `demoted_from`. No clock reads
   beyond what UsageAlertTracker already does.
3. Feed event on demotion and restoration (one each, dim/system style).
4. Snapshot round-trips `demoted_from`; replay/fork safe.
5. Config: `world.cap_governor: {enabled: true}` — `false` ⇒ alerts stay
   alert-only (pre-D3 behavior, prove with test).
6. Interaction rule: governor demotion composes with EM-177 failover — a
   demoted agent on a sick lane still detours when due.

---

## B3 — EM-171 + EM-172 (P2)

**Owner:** backend-agent-B3 (after B2 gate).
**Files owned:** `backend/petridish/agents/runtime.py`,
`backend/petridish/engine/world.py`, `backend/petridish/providers/router.py`
(read-only: `cache_stats`), `backend/tests/test_wave_d3_cache.py` +
`backend/tests/test_scheduler_skip.py` (new).

- **EM-171**: extend EM-162 normalization — coarsen/drop the day line from
  background prompts, de-tick background memory lines, scope menu target
  lists; protagonists stay byte-identical (fixture guard exists,
  `em161_protagonist_prompt_pre_diet.txt` pattern). Re-measure with
  `Router.cache_stats()` in a unit-level integration test and record the
  realized hit rate in the build results.
- **EM-172**: mid-round-death scheduler skip — `_turn_index` decrement in
  `world.py` + regression test reproducing the silent skip; one-line
  energy-band hysteresis for salience flapping (band only flips after the
  energy crosses the boundary by a margin).

---

## Gates

After each batch: full backend pytest (all tests, not just new), then
orchestrator commit. After B3: QE agent writes/updates `coordination/qa-report.json`
(wave-D3) with adversarial verification of B1's failover claims (the
"green gate ≠ real fix" rule: verify a detour actually calls the substitute
adapter, not just that a flag flips). Build blocked on the standard QA rules.

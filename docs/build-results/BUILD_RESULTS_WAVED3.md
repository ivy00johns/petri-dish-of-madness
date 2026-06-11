# Wave D3 — "self-healing lanes" (W17, part 1) · Build Results

> Branch: `build/wave-d3-lane-health` (stacked on `build/wave-d1-ew-city` / PR #10)
> Date: 2026-06-11 · Contract: `contracts/wave-d3.md`
> QA: `coordination/qa-report.json` (wave-D3, **proceed=true**, 0 blockers, 4 MINOR)
> Items: **EM-177, EM-168, EM-171, EM-172** — all done (`wave-D3 2026-06-11`).
> Lean sequential batches (B1→B3), one agent each, orchestrator-gated; QE
> adversarial pass after B3.

## Triggering incident

2026-06-11 live run: the FreeLLMAPI proxy silently rerouted every lane except
mistral-small to `nvidia/nemotron-3-super-120b` (a reasoning model whose
chain-of-thought blows the EM-170 12s budget on real prompts); deepseek-pro
hung outright. Measured timeout rates: cerebras-glm 12/19, qwen-next 11/18,
gemini-flash 11/39, groq-llama 3/6, **mistral-small 0/6**. Fourth manual lane
rescue in two sessions — the router KNEW lane health (EM-135/170 windows) but
nothing acted on it.

## What shipped

| Batch | Commit | Delivery |
|---|---|---|
| B1 EM-177 | `d2ce65d` | Lane failover with recovery probes: ≥3 timeouts in the 6-outcome window ⇒ that agent's calls detour per-call to the healthiest available lane (assigned profile/identity unchanged); every 4th would-be-detour probes the home lane so demerits age out automatically. `lane_detour` feed events on streak edges only; `llm_call` payloads gain additive `requested_profile`/`detoured`/`probe`; `GET /api/lanes`. `world.lane_failover {enabled: true, sick_threshold: 3, probe_every: 4}`; off ⇒ byte-identical pre-D3. 39 tests. |
| B2 EM-168 | `3d90859` | Cap-pressure governor: a `usage_alert` (70% of a lane's rpd/tpd day cap) demotes that lane's agents one cadence tier (background floor), once per lane-alert-day; the tracker's own lazy UTC-day rollover restores `demoted_from`. Manual tier sets win and clear the demotion. `cap_pressure` events on edges; snapshot/fork round-trips. `world.cap_governor.enabled=false` inert. Composes with EM-177 (tested). 28 tests. |
| B3 EM-171/172 | `1ad6e90` | Background cache payoff: tick line dropped, memory lines de-ticked, rosters/menus sorted (background tier ONLY — protagonist fixture guard untouched) ⇒ realized decision-cache hit rate **91.7%** (was 0%), deterministic across 3 runs. EM-172: mid-round death no longer silently skips the next due agent (`_turn_index` decrement, reproduction-proven) + 5-point energy-band hysteresis kills recharge-flap salience wakes. 20 tests. |
| QE gate | `8909d1b` | Adversarial verification (4 permanent tests): incident-shape proof (all lanes sick but one ⇒ 18/18 real calls on the healthy adapter at its own token budget, exactly 2 probes per home lane, zero mock calls), probe-driven recovery edge exactly once, demotion changes real `next_agent()` scheduling 9→3→9. EM-172 revert experiment in a /tmp copy: exactly the 3 reproduction tests fail pre-fix. |
| B4 EM-187 | `c34a8a3` | Resume-on-boot (added v1.1 on user approval): startup restores the most recent run's latest >tick-0 snapshot via the EM-101 fork machinery (new run row with `forked_from`/`forked_at_tick`, ≤25-tick loss) — `./dev` restarts and uvicorn hot-reloads keep the live world. One `run_resumed` feed line; world-defining config changes fall back to fresh (logged) while tunables adopt current values; no duplicate seed critters; reset stays the explicit fresh start; `resume_on_boot: false` byte-identical. 16 tests. **Live-verified**: run 408→407→406→397 lineage chain on the user's running backend — the build's own hot-reloads resumed instead of resetting. |

## Gates

Backend **566/566** (+107 over the wave: 459→566; B4 post-QE-gate batch
gated on the full suite + live boot-lineage verification) · QA proceed=true
(contract 4, coverage 4, security 5, regression 4, zero CRITICAL/MAJOR).
Backend-only wave — web untouched (user had live working-tree edits in
`world3d/`; all frontend items deferred by contract).

## Live mitigations applied during the wave

- Ada → mistral-small, Cleo → qwen-next, Vesper → mistral-small (reassign API)
  the moment the diagnosis landed — timeout spam stopped before B1 shipped.
- `GET /api/lanes` verified live on the running backend post-deploy.

## QE follow-ups filed

- **EM-186** (P2/W18): headless `run.py` doesn't thread `lane_failover`/sinks
  into the Router — failover + governor fully work only via the API server
  (defaults coincide, so default headless behavior is identical). Includes the
  pre-existing W7 `world.cache`→Router gap.
- Recorded, not filed: the 91.7% hit rate is a single-agent idealized-harness
  number — don't quote it as a 25-agent city property (co-location SET churn
  unnormalized at scale); `lane_detour` recovery-edge `agent_id` names
  whichever agent's call triggered it (cosmetic).

## Deferred this wave (written reasons)

- **EM-167** Ollama overflow — local Ollama not installed/running (port 11434
  dead at contract time); user setup required.
- **EM-169/EM-176** vehicles, **EM-127** day/night — frontend; the user had
  live uncommitted edits to `CozyWorld.tsx`/`Ground.tsx`/`Structure.tsx`/
  `toon.ts` (+ `Header.tsx`); no agent may touch those files.

## New this session (outside the wave)

- **W18 "answered prayers" opened**: EM-184 world-scale god miracles
  (send_rain / bountiful_harvest / calm_spirits — world events all agents
  perceive, zero LLM calls) + EM-185 grant-a-petition UX. Filed from the live
  session: agents petitioned the watchers and god had no world-scale power.

## Handoff

- W17 remaining: EM-167 (needs Ollama), EM-169+176 vehicles, EM-127 day/night,
  EM-183 (P3 move-the-center vote) — frontend items unblock when the user's
  working tree is clean.
- PR #10 (`build/wave-d1-ew-city`) still awaits the user's merge word; this
  branch stacks on it and can PR after.

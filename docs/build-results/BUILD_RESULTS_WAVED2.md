# Wave D2 — "population scaling" (W16) · Build Results

> Branch: `build/wave-d1-ew-city` · Date: 2026-06-11 · Contract: `contracts/wave-d2.md`
> QA: `coordination/qa-report.json` (wave-D2, proceed=true)
> Items: EM-170, EM-158, EM-159, EM-160, EM-166, EM-161, EM-162, EM-163, EM-165, EM-164 —
> all **done** (`wave-D2 2026-06-11`). Lean sequential batches (B1→B4), one agent each,
> orchestrator-gated; triggered by live run 248's 14–32s world freezes.

## What shipped

| Batch | Commit | Delivery |
|---|---|---|
| B1 EM-170 | `361697a` | 12s per-turn LLM wall-time budget (`world.turn_llm_budget_seconds`, 0/absent = off) around the full consult chain; timeout ⇒ existing idle-fallback as `llm_timeout`, parse-retry skipped, `timed_out` on the llm_call trace, EM-135 lane-health demerit; cancelled calls can't poison the decision cache. 9 tests. |
| B2 EM-158/159/160/166 | `db36ddc` + `90394d2` | Cadence tiers (protagonist 1× / supporting ⅓ / background 1⁄10 rounds; default all-protagonist = byte-identical pre-D2 rotation, snapshot-stable). Background salience gating: 8 triggers; non-salient due turns resolve a seeded reflex routine with ZERO router calls (call-count proven). Inseparable floor: 0.15 seeded wildcard + forced reassess at 8 reflex turns. Tier via yaml/spawn/`POST /api/agents/{id}/tier`. UI: PRO/SUP/BG chips, reflex-streak readout, dim feed reflex marker. 36 + 9 tests. |
| B3 EM-161/162/163 | `5a23019` | Tiered prompt diet (background 5,120→3,263 chars; protagonists byte-identical to a pre-diet capture; <5,000-char guard for the 8K cerebras lane); background cache-key normalization (energy 10s-bucketed, tick day-floored; unit-proven hit); propose/build/fund/propose_rule gated to protagonist+supporting at RESOLUTION (billboard pattern; menu agrees; vote ungated). 18 tests. |
| B4 EM-165/164 | `4797249` | `config/world.city25.yaml` variant (NOT default): 5 protagonists (named cast) / 8 supporting (persona library) / 12 background (city-flavored originals) across all 7 real lanes, fast lanes carrying background. EM-164 measured verification + `qa-report.json`. 5 tests. |

## Gates

Backend **445/445** (+68 over the wave) · web **501/501** (+9) · tsc + build clean ·
QA proceed=true (contract 4, coverage 4, security 5, regression 5, zero CRITICAL).

## EM-164 — the measured verdict on the v4 scaling table

- **Cadence math: VALIDATED to the decimal.** 8.30 LLM-consulting turns per 25-agent
  round measured (v4 claimed ~8.3) — a 3× call cut vs naive, before the diet.
- **Prompt diet: HELD.** Background mean 2,113 chars in the 25-fixture; max 2,871 < the
  5,000 guard.
- **EM-170: HELD under fire.** The bounded live run landed on a degraded proxy night
  (rerouting to slow reasoning models): 32/60 calls hit the budget and every one
  cancelled at 12.003–12.010s. Worst stall 12.01s. The run-248 freeze class is dead.
  Live pace 299 turns/h projected at the 3s tick.
- **Cache discount: FALSIFIED.** Realized hit rate 0% (v4 assumed 50–60%): day-floor
  misses (a 25-turn round spans >1 in-world day), raw ticks in memory lines, reflex
  move-home churning co-location. Mechanism unit-sound; integration payoff absent.
  Capacity math closes anyway on the 8.3 calls/round. Follow-up filed as **EM-171**.
- Live observation mid-wave: the user's own session showed the guard firing correctly
  ("Ada … idle fallback: llm_timeout … exceeded the 12s turn budget") — one idled turn
  instead of a frozen world.

## QE follow-ups filed

- **EM-171** (P2/W17): extend EM-162 normalization for real cache payoff, re-measure.
- **EM-172** (P2/W17): pre-existing mid-round-death scheduler skip (one due agent
  silently skipped per mid-round death; surfaced by the 25-agent chaos run) + energy-band
  hysteresis for salience flapping.
- Recorded, not filed: qwen-next's 50 rpd realistically supports Bram ~1 protagonist-hour
  per day (lane choice, not code); degraded-proxy nights idle ~half of protagonist turns
  at the 12s budget — lane-health-aware routing preference is EM-168's natural scope
  (W17); live background/reflex behavior verified on MockProvider + unit proofs, bounded
  live run ended before a background turn came due.

## Handoff

- W16 complete. To run the 25-agent city: see the header of `config/world.city25.yaml`
  (the user flips when ready — default stays the small cast).
- Live session mitigations applied during the wave: all 8 agents on distinct lanes
  (7 real lanes; Marrow doubles gemini-flash), slow seats restored to their original
  lanes once EM-170 landed.
- W17 / D3 next: EM-167 Ollama overflow, EM-168 cap-pressure governor (+ lane-health
  routing preference), EM-169 ambient vehicles, EM-127 day/night, EM-123 growth backend,
  EM-171/172 QE follow-ups. Still owed: repo-wide ux-review on merged main; EM-151
  (inspector archive at 40k events) remains open; PR for `build/wave-d1-ew-city` awaits
  the user's word.

# PetriDishOfMadness — Remaining Work (tactical ledger)

Every open item, ID'd and prioritized. This is the canonical "what exactly needs doing?"
list. The strategic roadmap (waves + exit criteria) lives in `BUILD-PLAN.md`.

> **Status (2026-06-08):** v1 (W0–W4) shipped. **v2 in progress on `build/v2-expansion`:**
> **W5 (foundations) ✅** — append-only event-log trace spine + decision-trace output + the
> 2D `/inspector` analysis annex (3D village stays primary). **W6 (instrumentation) ✅** —
> replay, decision-trace inspector, governance history, social graph, 9-AWI + model-vs-model
> dashboard, per-provider usage capture; QA 97/97, render-sanity PASS. **Next: W7 (expanded
> world — tools, buildings, collective projects, spawn, caching), then W8 (chaos animals).**
> Open from v1: EM-043 (FE unit tests, P1).

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W8` (see `BUILD-PLAN.md`). W0–W4 shipped; W5–W8 are the v2 expansion.
- **Area** — `infra` · `contracts` · `backend` · `providers` · `persistence` · `frontend` · `qe`.
- **Source** — where it came from. New items from reports enter via `plan-intake`.
- **Status** — `open` · `in-progress` · `blocked` · `done`.
- **Owner** — agent role or person; `—` if unassigned.

| ID | Pri | Wave | Area | Source | Summary | Status | Owner |
|----|-----|------|------|--------|---------|--------|-------|
| EM-001 | P0 | W0 | infra | spec §2 | Repo scaffold | done | infra |
| EM-002 | P0 | W0 | contracts | spec §3 | Action-protocol JSON schema | done | orch |
| EM-003 | P0 | W0 | contracts | spec §2,6 | WebSocket event schema | done | orch |
| EM-004 | P0 | W0 | contracts | spec §6 | REST control API (OpenAPI) | done | orch |
| EM-005 | P0 | W0 | contracts | spec §2 | SQLite schema | done | orch |
| EM-006 | P0 | W0 | contracts | spec §2,6 | Provider `chat()` interface + config schema | done | orch |
| EM-007 | P0 | W0 | infra | spec §6 | `profiles.yaml` + `world.yaml` templates | done | infra |
| EM-010 | P0 | W1 | backend | spec §2,4 | World model + state | done | backend |
| EM-011 | P0 | W1 | backend | spec §2 | Tick loop + round-robin scheduler | done | backend |
| EM-012 | P0 | W1 | backend | spec §4 | Needs: energy decay + death | done | backend |
| EM-013 | P0 | W1 | backend | spec §4 | Economy: work/forage/recharge/give/steal | done | backend |
| EM-014 | P0 | W1 | backend | spec §4 | Talk + relationships | done | backend |
| EM-015 | P0 | W1 | backend | spec §4 | Governance: propose/vote/effects | done | backend |
| EM-016 | P0 | W1 | backend | spec §5 | Agent context assembly + cheap memory | done | backend |
| EM-017 | P0 | W1 | backend | spec §3 | Action parse + validate + retry + idle fallback | done | backend |
| EM-018 | P0 | W1 | providers | spec §2 | Router + OpenAI-compatible adapter (FreeLLMAPI/Ollama) | done | backend |
| EM-019 | P1 | W1 | providers | spec §2 | Anthropic adapter | done | backend |
| EM-020 | P1 | W1 | providers | spec §2 | Gemini adapter | done | backend |
| EM-021 | P0 | W1 | providers | spec §7 | MockProvider (scripted JSON, deterministic) | done | backend |
| EM-022 | P0 | W1 | persistence | spec §2 | SQLite repository | done | backend |
| EM-030 | P0 | W2 | backend | spec §6 | FastAPI control endpoints | done | backend |
| EM-031 | P0 | W2 | backend | spec §2 | WebSocket broadcaster | done | backend |
| EM-032 | P0 | W2 | frontend | spec §2 | 2D canvas map | done | frontend |
| EM-033 | P0 | W2 | frontend | spec §2,3 | Live event feed, color-coded by model | done | frontend |
| EM-034 | P0 | W2 | frontend | spec §6 | Per-agent panels | done | frontend |
| EM-035 | P0 | W2 | frontend | spec §6 | Control panel + live model reassign + legend | done | frontend |
| EM-036 | P1 | W2 | frontend | spec §2 | WebSocket client + state store | done | frontend |
| EM-040 | P0 | W3 | qe | spec §10 | Engine unit tests (invariants/economy/governance/death) | done | qe/orch |
| EM-041 | P0 | W3 | qe | spec §10 | Integration test: loop lifecycle + invariants | done | qe/orch |
| EM-042 | P1 | W3 | qe | spec §10 | OpenAI-compatible adapter stub test (+ failure path) | done | qe/orch |
| EM-043 | P1 | W3 | qe | spec §10 | Frontend render smoke/unit tests | open | — |
| EM-044 | P0 | W3 | infra | spec §8 | docker-compose (+ opt-in ollama/freellmapi) | done | infra |
| EM-045 | P0 | W3 | infra | spec §8 | Root README + one-command `dev` | done | infra |
| EM-046 | P1 | W3 | infra | spec §8 | Cloud-deploy notes (endpoint swap) | done | infra |
| EM-047 | P0 | W3 | qe | DoD | render-sanity + ux-review gate | done | orch |
| EM-048 | P0 | W3 | qe | spec §12 | **Live ≥2-model arc run (≥5 min)** — DONE: 3 agents / 3 models ran live on FreeLLMAPI >11 min, 3/3 alive, real chat + passed rule | done | orch |
| EM-049 | P1 | W4 | frontend | user req | Cozy 3D village view (React Three Fiber + drei): procedural buildings per place-kind, walking villagers, chat bubbles, orbit cam; default center view + 2D/3D toggle | done | frontend |
| EM-050 | P1 | W4 | providers | user req | Surface actually-routed model — capture `X-Routed-Via` → `payload.routed_via`; display per-villager + feed | done | backend+frontend |
| EM-051 | P1 | W4 | qe | user req | Regression tests for routed_via capture/fallback/injection | done | qe |
| EM-052 | P2 | W4 | config | user req | Seed 3 agents co-located in plaza so conversation starts round 1 | done | orch |
| EM-053 | P0 | W5 | frontend | research-v2 #1 | Add `/inspector` route — a 2D *analysis annex* (3D village stays the **primary** view at `/`); unmount the WebGL canvas while analyzing | done | frontend |
| EM-054 | P0 | W5 | persistence | research-v2 #2 | Append-only event-log schema (OTel-style linked turn traces) + WAL + periodic snapshots | done | persistence |
| EM-055 | P1 | W6 | frontend | research-v2 #3 | Session replay viewer (2D timeline scrubber + top-down Canvas map) | done | frontend |
| EM-056 | P1 | W6 | frontend | research-v2 #4 | Agent decision-trace inspector (perceived → memories → llm_call → reasoning → action) | done | frontend |
| EM-057 | P1 | W6 | frontend | research-v2 #5 | Governance/laws history view w/ downstream-consequence links (the "clock tower" failure) | done | frontend |
| EM-058 | P1 | W6 | frontend | research-v2 #6 | Relationship/social-graph viz (react-force-graph-2d, time-scrub) | done | frontend |
| EM-059 | P1 | W6 | frontend | research-v2 #7 | Analytics: 9-AWI + model-vs-model dashboard (uPlot/Observable Plot) | done | frontend |
| EM-060 | P2 | W7 | backend | research-v2 #8 | Expanded tiered tool catalog (🟢 reflex vs 🔵 LLM-served), location/agreement-gated | open | — |
| EM-061 | P2 | W7 | backend | research-v2 #9 | Building/structure mutable state model (status/health/progress transitions) | open | — |
| EM-062 | P2 | W7 | backend | research-v2 #10 | Collective-project pipeline (propose→fund→build→succeed/fail) | open | — |
| EM-063 | P2 | W7 | backend | research-v2 #11 | Ad-hoc agent spawning mid-run (god-mode + governance-gated flag) | open | — |
| EM-064 | P3 | W8 | backend | research-v2 #12 | LLM-driven cat & dog as distinct `actor_type:"animal"` chaos entities | open | — |
| EM-065 | P3 | W8 | frontend | research-v2 #13 | Animal Chaos Feed + `is_chaotic` tagging/surfacing (magenta on timeline) | open | — |
| EM-066 | P1 | W5 | contracts | research-v2 §patterns | Structured decision-trace action output `{perceived_summary, memories_used, reasoning, chosen_tool, args}` in one call (enabler for EM-054/056) | done | backend |
| EM-067 | P1 | W6 | providers | research-v2 §x-cut | Per-provider RPD/TPD usage tracking in event log + cap-aware throttling; **also emit per-attempt `llm_call` rows** (W5 logs only the final attempt — see Notes) | done | providers |
| EM-068 | P2 | W7 | providers | research-v2 §x-cut | Decision/prompt-prefix caching (persona + memory-hash + coarse-world-state) | open | — |

_Next free ID: EM-069._

## Notes

- **EM-048** is the project goal. The engine has run 1,600+ ticks continuously on the
  deterministic MockProvider (well past 5 minutes) with deaths, alliances, and passed rules,
  and the OpenAI-compatible adapter is verified end-to-end against a FreeLLMAPI-shaped stub
  (incl. the failure→idle path). The only remaining step is supplying a real token — see the
  "Run the 5-minute 2-model demo" section of `README.md` and `BUILD_RESULTS.md`.
- **EM-043** deferred: frontend is covered by tsc typecheck, production build, a Playwright
  reassign check, and render-sanity; component unit tests are a v1.1 nice-to-have.
- **EM-053–EM-068 (v2 expansion)** entered 2026-06-08 via `plan-intake` from
  `docs/research/deep-research-v2.md`. They open **W5–W8** (Foundations → Instrumentation →
  Expanded world → Chaos animals). **W5 (EM-053/054/066) is the gate**: every later item reads
  the append-only event log, so lock that schema before building any Phase-1 UI. The report's
  own priority scale was translated into this ledger's "blocks-the-wave" P0–P3 semantics.

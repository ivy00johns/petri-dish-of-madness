# PetriDishOfMadness — Remaining Work (tactical ledger)

Every open item, ID'd and prioritized. This is the canonical "what exactly needs doing?"
list. The strategic roadmap (waves + exit criteria) lives in `BUILD-PLAN.md`.

> **Status (2026-06-09):** v1 (W0–W4) and v2 (W5–W8) shipped on `build/v2-expansion`.
> **W9–W11 filed 2026-06-09** via `plan-intake` from `docs/audit-2026-06-09.md` (full audit:
> backend + frontend code audits, live UX review, doc-drift sweep). **W9 ("make v2 true") is
> the gate:** wire the inspector to the persisted event log (deep replay is currently dead
> code), add survival pressure + extinction UX, warn on routing collapse, and fix the P1 bug
> batches. Then W10 (trust & hygiene), W11 (new texture). Open from v1: EM-043 (FE unit
> tests, P1 — now scoped to regression-proof the W9 fixes; see Notes).

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W11` (see `BUILD-PLAN.md`). W0–W4 shipped (v1); W5–W8 shipped (v2); W9–W11 are the audit-driven v2.1 plan.
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
| EM-060 | P2 | W7 | backend | research-v2 #8 | Expanded tiered tool catalog (🟢 reflex vs 🔵 LLM-served), location/agreement-gated | done | backend |
| EM-061 | P2 | W7 | backend | research-v2 #9 | Building/structure mutable state model (status/health/progress transitions) | done | backend |
| EM-062 | P2 | W7 | backend | research-v2 #10 | Collective-project pipeline (propose→fund→build→succeed/fail) | done | backend |
| EM-063 | P2 | W7 | backend | research-v2 #11 | Ad-hoc agent spawning mid-run (god-mode + governance-gated flag) | done | backend |
| EM-064 | P3 | W8 | backend | research-v2 #12 | LLM-driven cat & dog as distinct `actor_type:"animal"` chaos entities | done | backend |
| EM-065 | P3 | W8 | frontend | research-v2 #13 | Animal Chaos Feed + `is_chaotic` tagging/surfacing (magenta on timeline) | done | frontend |
| EM-066 | P1 | W5 | contracts | research-v2 §patterns | Structured decision-trace action output `{perceived_summary, memories_used, reasoning, chosen_tool, args}` in one call (enabler for EM-054/056) | done | backend |
| EM-067 | P1 | W6 | providers | research-v2 §x-cut | Per-provider RPD/TPD usage tracking in event log + cap-aware throttling; **also emit per-attempt `llm_call` rows** (W5 logs only the final attempt — see Notes) | done | providers |
| EM-068 | P2 | W7 | providers | research-v2 §x-cut | Decision/prompt-prefix caching (persona + memory-hash + coarse-world-state) | done | providers |
| EM-069 | P0 | W9 | frontend | audit §C1 | Wire deep replay: inspector boots from `/api/events`, scrub uses `/api/replay` snapshot+delta (filtered past `base.tick`), panels read beyond rolling window, fold-forward boundary fix, scrub pins panels | open | — |
| EM-070 | P0 | W9 | backend | audit §A1 | Survival pressure: needs salience in turn prompt, no-charge recharge-at-full, starvation feed warnings, death-countdown surfacing | open | — |
| EM-071 | P1 | W9 | frontend | audit §A2 | Extinction/run-end UX: auto-pause or banner on 0 alive + end-of-run summary card | open | — |
| EM-072 | P1 | W9 | frontend | audit §A4 | Routing-degraded banner when all live profiles resolve to one routed model | open | — |
| EM-073 | P1 | W9 | backend | audit §B1–B4,B6 | Backend correctness batch: animal turn_id stamp, reset awaits tick task, ban_arson proposable, build_step accepts funded `planned`, duplicate llm_call dedupe | open | — |
| EM-074 | P1 | W9 | frontend | audit §C2,C3,C5,C6,C10 | Frontend correctness batch: replay play/pause state, WS reconnect cleanup+backoff, force-graph pause fix, AWI gov column, synthetic-event seq collision | open | — |
| EM-075 | P2 | W10 | frontend | audit §B8,C7,D3,D4 | Replay fidelity: snapshot round/scheduler state, time-projected building status, replay-map legibility, animals on 2D map | open | — |
| EM-076 | P2 | W10 | backend | audit §B9,D5 | Analytics correctness: active_rules formula/source of truth; speed label synced to server tick interval | open | — |
| EM-077 | P2 | W10 | backend | audit §B10–B12,B14,B15 | Platform hardening: WS broadcast cleanup, Gemini key via header, decision-cache flush on reset, spawn input length caps, profile-color helper | open | — |
| EM-078 | P2 | W10 | contracts | audit §E1–E5 | Docs/contracts sync: README screenshot/chaos-feed regression fix, `/api/animals` in OpenAPI, event-kind schema sync, V2_BUILD.md + FUTURE.md refresh | open | — |
| EM-079 | P2 | W11 | backend | audit §F / research-v2 §rec | Active-commitments injection in turn prompt + ignored-commitment logging (clock-tower pressure) | open | — |
| EM-080 | P2 | W11 | backend | audit §F / research-v2 §rec | Reflection/diary on importance threshold (~2–3×/day, Smallville pattern) | open | — |
| EM-081 | P2 | W11 | backend | audit §F / FUTURE.md | Reactive overhearing chains, capped (1–2 listeners) + reflex-first responses (free-scale) | open | — |
| EM-082 | P2 | W11 | frontend | audit §D1,D6 | Mobile decision (stacked read-only layout OR explicit min-width gate) + semantic headings / a11y pass | open | — |
| EM-083 | P3 | W11 | backend | audit §B13 / research-v2 §bench | Make `blackout` event effect real; benchmark alerts on EM-067 usage data (>70% RPD/TPD → warn) | open | — |

_Next free ID: EM-084._

## Notes

- **EM-048** is the project goal. The engine has run 1,600+ ticks continuously on the
  deterministic MockProvider (well past 5 minutes) with deaths, alliances, and passed rules,
  and the OpenAI-compatible adapter is verified end-to-end against a FreeLLMAPI-shaped stub
  (incl. the failure→idle path). The only remaining step is supplying a real token — see the
  "Run the 5-minute 2-model demo" section of `README.md` and `BUILD_RESULTS.md`.
- **EM-043** re-scoped 2026-06-09 (was "v1.1 nice-to-have"): the audit found four frontend
  bugs (audit §C2, C4, C5, C6) that component/selector unit tests would have caught. Target it
  in W10 at the selectors + ReplayScrubber + AWIDashboard layer, regression-proofing the W9
  fixes (EM-069/074).
- **EM-053–EM-068 (v2 expansion)** entered 2026-06-08 via `plan-intake` from
  `docs/research/deep-research-v2.md`. They open **W5–W8** (Foundations → Instrumentation →
  Expanded world → Chaos animals). **W5 (EM-053/054/066) is the gate**: every later item reads
  the append-only event log, so lock that schema before building any Phase-1 UI. The report's
  own priority scale was translated into this ledger's "blocks-the-wave" P0–P3 semantics.
- **EM-069–EM-083 (v2.1 audit plan)** entered 2026-06-09 via `plan-intake` from
  `docs/audit-2026-06-09.md` (companion UX detail: `docs/ux-review-2026-06-09.md`). They open
  **W9–W11** (Make v2 true → Trust & hygiene → New texture). **W9 (EM-069–074) is the gate**:
  EM-069 closes the gap between "EM-055 done" and the actual deep-replay promise, and EM-070
  fixes the starve-to-extinction failure observed live (all 3 agents died with credits in hand
  while planning a festival). `audit §Xn` source refs point at the theme/finding IDs inside
  the audit doc. No new entry was filed for frontend tests — that folds into the still-open
  EM-043 (see above).

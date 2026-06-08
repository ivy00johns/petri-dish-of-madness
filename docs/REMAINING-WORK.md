# EmergenceMadness — Remaining Work (tactical ledger)

Every open item, ID'd and prioritized. This is the canonical "what exactly needs doing?"
list. The strategic roadmap (waves + exit criteria) lives in `BUILD-PLAN.md`.

> **Status (2026-06-08):** v1 shipped (W0–W3). **W4 (cozy 3D village + live run) complete on
> `build/emergence-madness-3d`.** EM-048 (the project goal) is **DONE** — a 3-agent, 3-model
> world ran live on FreeLLMAPI for >11 min, all 3 alive, with real chat and a passed rule. The
> center view is now a cozy 3D village (Stardew × Animal-Crossing) and the UI surfaces the
> model that *actually* answered each turn (`X-Routed-Via`). Open: EM-043 (FE unit tests, P1).

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W3` (see `BUILD-PLAN.md`).
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

_Next free ID: EM-053._

## Notes

- **EM-048** is the project goal. The engine has run 1,600+ ticks continuously on the
  deterministic MockProvider (well past 5 minutes) with deaths, alliances, and passed rules,
  and the OpenAI-compatible adapter is verified end-to-end against a FreeLLMAPI-shaped stub
  (incl. the failure→idle path). The only remaining step is supplying a real token — see the
  "Run the 5-minute 2-model demo" section of `README.md` and `BUILD_RESULTS.md`.
- **EM-043** deferred: frontend is covered by tsc typecheck, production build, a Playwright
  reassign check, and render-sanity; component unit tests are a v1.1 nice-to-have.

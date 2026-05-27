# EmergenceMadness — Remaining Work (tactical ledger)

Every open item, ID'd and prioritized. This is the canonical "what exactly needs doing?"
list. The strategic roadmap (waves + exit criteria) lives in `BUILD-PLAN.md`.

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish; consider `docs/FUTURE.md` instead).
- **Wave** — `W0`–`W3` (see `BUILD-PLAN.md`).
- **Area** — `infra` · `contracts` · `backend` · `providers` · `persistence` · `frontend` · `qe`.
- **Source** — where it came from (spec §, audit, QA, deep-dive). New items from reports enter via `plan-intake`.
- **Status** — `open` · `in-progress` · `blocked` · `done`. Done items move to the closure log in `BUILD-PLAN.md` at wave close.
- **Owner** — agent role or person; `—` if unassigned.

| ID | Pri | Wave | Area | Source | Summary | Status | Owner |
|----|-----|------|------|--------|---------|--------|-------|
| EM-001 | P0 | W0 | infra | spec §2 | Repo scaffold: `backend/{engine,providers,agents,persistence,api}`, `web/`, `config/`, `docker/` | open | — |
| EM-002 | P0 | W0 | contracts | spec §3 | Action-protocol JSON schema (~14 actions + args + validation rules) | open | — |
| EM-003 | P0 | W0 | contracts | spec §2,6 | WebSocket event schema (event types, model/profile tagging) | open | — |
| EM-004 | P0 | W0 | contracts | spec §6 | REST API spec (control + config endpoints) | open | — |
| EM-005 | P0 | W0 | contracts | spec §2 | SQLite schema (agents, events, relationships, rules, snapshots) | open | — |
| EM-006 | P0 | W0 | contracts | spec §2,6 | Provider `chat()` interface + model-profile config schema | open | — |
| EM-007 | P0 | W0 | infra | spec §6 | `config/profiles.yaml` + `config/world.yaml` templates (load-validated) | open | — |
| EM-010 | P0 | W1 | backend | spec §2,4 | World model + state (grid, places, agents) | open | — |
| EM-011 | P0 | W1 | backend | spec §2 | Tick loop + round-robin scheduler | open | — |
| EM-012 | P0 | W1 | backend | spec §4 | Needs: energy decay + death rules | open | — |
| EM-013 | P0 | W1 | backend | spec §4 | Economy: work / forage / recharge / give / steal | open | — |
| EM-014 | P0 | W1 | backend | spec §4 | Talk + relationships: say / whisper / set_relationship / trust | open | — |
| EM-015 | P0 | W1 | backend | spec §4 | Governance: propose_rule / vote / typed effects → world-param mutation | open | — |
| EM-016 | P0 | W1 | backend | spec §5 | Agent context assembly + cheap memory (rolling buffer, beliefs, relationship map) | open | — |
| EM-017 | P0 | W1 | backend | spec §3 | Action parse + validate + 1 retry + idle fallback | open | — |
| EM-018 | P0 | W1 | providers | spec §2 | Provider router + OpenAI-compatible adapter (FreeLLMAPI / Ollama) | open | — |
| EM-019 | P1 | W1 | providers | spec §2 | Anthropic adapter | open | — |
| EM-020 | P1 | W1 | providers | spec §2 | Gemini adapter | open | — |
| EM-021 | P0 | W1 | providers | spec §7 | MockProvider (scripted JSON actions, deterministic) | open | — |
| EM-022 | P0 | W1 | persistence | spec §2 | SQLite repository implementation behind the repo interface | open | — |
| EM-030 | P0 | W2 | backend | spec §6 | FastAPI control endpoints (start/pause/step/speed/reassign/spawn/kill/inject) | open | — |
| EM-031 | P0 | W2 | backend | spec §2 | WebSocket broadcaster (state + event stream) | open | — |
| EM-032 | P0 | W2 | frontend | spec §2 | 2D canvas map (agents, places, movement) | open | — |
| EM-033 | P0 | W2 | frontend | spec §2,3 | Live event feed, color-coded by model | open | — |
| EM-034 | P0 | W2 | frontend | spec §6 | Per-agent panels (model, needs, mood, credits, relationships) | open | — |
| EM-035 | P0 | W2 | frontend | spec §6 | Control panel + live model reassignment + model legend | open | — |
| EM-036 | P1 | W2 | frontend | spec §2 | WebSocket client + state store | open | — |
| EM-040 | P0 | W3 | qe | spec §10 | Engine unit tests (decay/death, validation, economy, governance, relationships) | open | — |
| EM-041 | P0 | W3 | qe | spec §10 | Integration test: K ticks, assert invariants | open | — |
| EM-042 | P1 | W3 | qe | spec §10 | Provider adapter contract tests (stub OpenAI-compatible endpoint) | open | — |
| EM-043 | P1 | W3 | qe | spec §10 | Frontend render smoke tests + WS mock | open | — |
| EM-044 | P0 | W3 | infra | spec §8 | docker-compose (backend, frontend, optional Ollama / FreeLLMAPI) | open | — |
| EM-045 | P0 | W3 | infra | spec §8 | Root README + one-command `dev` script | open | — |
| EM-046 | P1 | W3 | infra | spec §8 | Cloud-deploy notes (endpoint swap) | open | — |
| EM-047 | P0 | W3 | qe | DoD | `render-sanity` + `ux-review` post-build gate | open | — |
| EM-048 | P0 | W3 | qe | spec §12 | End-to-end mixed-model arc run (conflict, alliances, ≥1 death, ≥1 passed rule) | open | — |

_Next free ID: EM-049._

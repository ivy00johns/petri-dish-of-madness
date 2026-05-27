# EmergenceMadness — Build Plan

Strategic roadmap. **Where are we going, and what have we finished?**
Tactical detail (individual items) lives in `docs/REMAINING-WORK.md`.
The approved design is frozen at `docs/superpowers/specs/2026-05-26-emergence-madness-design.md`.

Build model: **contract-first, parallel multi-agent** (orchestrator). Contracts authored
in W0 before any implementation agent is spawned. A QE gate closes every wave.

---

## Wave 0 — Scaffold & Contracts

Lay the skeleton and author every machine-readable contract before implementation begins.

**Scope:** repo structure (`backend/{engine,providers,agents,persistence,api}`, `web/`,
`config/`, `docker/`); config templates (`profiles.yaml`, `world.yaml`); contracts for the
action protocol JSON, WebSocket event schema, REST API, SQLite schema, and provider
`chat()` interface.

**Exit criteria:**
- All five contracts pass the contract-author quality checklist.
- Skeleton installs/builds (Python + web) with no implementation yet.
- `config/*.yaml` templates documented and load-validated.

## Wave 1 — Engine, Providers, Persistence (backend core)

The sim works headless and deterministically.

**Scope:** world model + state; tick loop + round-robin scheduler; needs decay + death;
economy (work/forage/recharge/give/steal); talk + relationships; lightweight governance
(propose/vote/typed effects → world-param mutation); agent context assembly + cheap memory;
action parse/validate/retry/idle-fallback; provider router + adapters (OpenAI-compatible,
Anthropic, Gemini); MockProvider; SQLite repository.

**Exit criteria:**
- Engine runs K ticks against MockProvider, fully deterministic, zero LLM calls.
- Invariants hold (credits conserved except via defined sources/sinks; dead agents act not; active rules enforced).
- Adapter contract tests pass against a stub OpenAI-compatible endpoint.

## Wave 2 — API & Frontend (the spectacle)

You can watch the madness in a browser.

**Scope:** FastAPI control endpoints (start/pause/step/speed/reassign-model/spawn/kill/inject-event)
+ config endpoints; WebSocket broadcaster (state + events); React/Vite/Tailwind frontend —
2D canvas map, live event feed (color-coded by model), per-agent panels, control panel with
**live model reassignment**, model legend; WS client + state store.

**Exit criteria:**
- UI renders live from a MockProvider run: map moves, feed streams, panels update.
- Reassigning an agent's model from the UI is visibly reflected on the next turn.
- Console clean; primary routes walk cleanly.

## Wave 3 — Integration, QE & Deploy

Ship-ready, tested, one-command up.

**Scope:** end-to-end wiring; QE suite (engine units, integration invariants, adapter
contracts, frontend smoke) + `qa-report.json`; `render-sanity` + `ux-review` gates;
docker-compose one-command up (backend, frontend, optional Ollama / FreeLLMAPI); root README
+ `dev` script; cloud-deploy notes (endpoint swap).

**Exit criteria (= Definition of Done, spec §12):**
- `docker-compose up` brings up the lab; map + feed render and update live.
- A 4–6 agent **mixed-model** world runs a full arc end-to-end (conflict, alliances, ≥1 death, ≥1 passed rule).
- Per-agent model reassignable live from the UI.
- Engine test suite passes deterministically (MockProvider).
- Runs free against FreeLLMAPI and locally against Ollama.
- README documents one-command local run + path to cloud deploy.
- `render-sanity` returns PASS.

---

## Closure log

What shipped and when. Append on each wave/milestone close.

| Date | Wave / Item | Result |
|------|-------------|--------|
| 2026-05-26 | Design | Spec approved & committed (`8048235`); living plan set up |

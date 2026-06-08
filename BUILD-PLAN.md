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

## Wave 4 — Cozy 3D village + live multi-model run (post-v1)

Make the world a place you *watch*, and prove the marquee feature live.

**Scope:** a cozy 3D village center view (React Three Fiber + drei) in the
Stardew × Animal-Crossing register — procedural buildings per place-kind, walking
villagers tinted by model, floating chat bubbles, orbit spectator cam, 2D/3D toggle;
backend surfacing of the model that *actually* answered each turn (`X-Routed-Via` →
`payload.routed_via`) displayed per villager; 3-agent / 3-model config (co-located seed
for immediate conversation); the live FreeLLMAPI run (EM-048).

**Exit criteria:**
- `tsc -b` + `vite build` pass; backend suite green (incl. new routed_via tests).
- A 3-agent, 3-model world runs live on FreeLLMAPI for ≥5 min with agents chatting.
- The UI shows the actually-routed model per agent (not just the requested profile).
- The 3D village renders from live data with a clean console.

---

## Closure log

What shipped and when. Append on each wave/milestone close.

| Date | Wave / Item | Result |
|------|-------------|--------|
| 2026-05-26 | Design | Spec approved & committed (`8048235`); living plan set up |
| 2026-05-26 | W0 Contracts | 6 contracts authored (`bca98f6`) |
| 2026-05-26 | W1+W2 Build | backend (`58a8e7e`), frontend (`d90c1bb`), infra (`18aa21b`) shipped in parallel |
| 2026-05-26 | Wave gate | Found + fixed TickLoop step/start lifecycle bug (`27f9027`) + regression tests |
| 2026-05-26 | W3 QE | 55 tests pass; OpenAI/FreeLLMAPI adapter stub-verified; qa-report gate PASS (`d68a1da`) |
| 2026-05-26 | W3 render-sanity | Found + fixed dual-event-source duplicate-key bug (`1f5964b`); re-verified PASS (0 console errors, ordered feed, live backend) |
| 2026-05-26 | v1 complete | All waves shipped. Open: EM-043 (FE unit tests, P1) + EM-048 (live 2-model run, awaiting user token) |
| 2026-06-08 | W4 build | Cozy 3D village (frontend, R4F+drei) + routed-via surfacing (backend) shipped in parallel; wave gate PASS (`tsc -b`+`vite build`, 55 tests) |
| 2026-06-08 | EM-048 ✅ | Live 3-agent / 3-model FreeLLMAPI run >11 min, 3/3 alive, real chat + passed rule; proxy reroutes surfaced via `X-Routed-Via`. The project goal is met. |

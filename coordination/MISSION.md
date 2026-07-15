# MISSION — Multi-City Keystone (2 cities + travel)

**Branch:** `build/multi-city-expansion` (off the organic-world commit `f0eb5fb`)
**Runtime:** Subagents via Agent/Task tool (parallel, no Agent Teams)
**Scope decision (user, this session):** Keystone slice = EM-109 intent + EM-110 travel.
Roster stays **small (~5–10)** to validate the plumbing first. Founding-driven grid
growth, inter-city trade/diplomacy (EM-116/117), and the parallel-worlds runner
(EM-112) are explicitly **out of scope for this slice** (later builds).

## The architecture decision (locked)

Multi-city is realized via the **already-built `Settlement` primitive (EM-269 F2)**, NOT
the parked EM-109 `cities`/`city_links`/`agent_location` table model. The repo committed
to "multi-city falls out of the freedom" (settlements are emergent, agent-founded,
world-frame clusters). We turn it ON and add the two missing pieces (travel + per-city
scoping + per-city render). This keeps us on the repo's committed architecture and reuses
seeded IDs, snapshot round-trip, the `found_settlement` verb, and `SettlementLabels`.

## Hard constraints (every agent MUST honor)

1. **Determinism / EM-155 byte-identical.** No `uuid4`/`random`/clock reads on the tick
   path. All new IDs seeded from `(…, city_seed)` like `_settlement_id` (world.py:4070).
   New snapshot keys serialize **only-when-non-empty** and restore to empty when absent
   (the `settlements`/`factions` pattern) — so a **settlements-OFF world stays
   byte-identical** to today. Every new golden must assert byte-identity of the OFF path.
2. **Free-scale (flat prompt size).** Per-city scoping must keep an agent's prompt the
   SAME size with 2 cities as with 1 — an agent perceives its OWN settlement only (extend
   the existing `_diet_visible_districts` horizon, runtime.py:2720). NO per-city
   multiplication of LLM calls; ONE tick loop over all agents (world.py `next_agent`).
3. **No throttling / high call-rate.** Travel takes agents *off-board* (0 LLM calls while
   `in_transit`) — that's a rate SAVING, never a mute. Do not add caps/decision-cache.
4. **Toolchain (petridish-test-toolchain):** backend `.venv/bin/python -m pytest`;
   frontend real node binary `/usr/local/bin/node node_modules/vitest/vitest.mjs run`;
   typecheck `/usr/local/bin/npx tsc -b --force` (NOT `--noEmit`, vacuous).
5. **Flag-gated.** All new behavior rides `settlements.enabled` (+ a `travel` sub-gate if
   needed). Default OFF ⇒ byte-identical. The live config opts in.

## Roles & file ownership (NO overlap)

- **backend-core** — owns `backend/petridish/engine/world.py`, `engine/loop.py`,
  `agents/runtime.py`, `engine/placement.py`, `config/loader.py`, `config/world.yaml`.
  Builds: travel state machine, per-settlement perception scoping, migration,
  settlements-on wiring, roster split. Contract: `contracts/settlement-travel.md`.
- **frontend** — owns `web/src/` (components/world3d, components/map, types, App).
  Builds: per-settlement geometry render (offset CityScape per settlement center),
  in-transit agent viz, 2D WorldMap settlements. Contract: `contracts/frontend-multicity.md`.
- **qe** — owns `backend/tests/`, `web/src/**/*.test.*` (NEW test files only; may not
  edit non-test source). Writes tests for the travel state machine, scoping flatness,
  migration, determinism/byte-identity, and the frontend render. Produces `qa-report.json`.

## Wave gate (between waves, run integrated)

- Backend: `.venv/bin/python -m pytest backend/tests/ -q`
- Frontend: `/usr/local/bin/npx tsc -b --force` + `/usr/local/bin/node node_modules/vitest/vitest.mjs run` (from web/)
- Route failures back by file ownership. Byte-identity goldens are the hard gate.

## Definition of Done (this slice)

1. Settlements ON: an agent founds a 2nd settlement; both round-trip through snapshot.
2. `travel_to(settlement)` works: agent goes `in_transit` (0 LLM), arrives at `transit_arrival_tick`, home settlement migrates; credits/skills/memories/relationships follow.
3. Prompt size is FLAT: a 2-settlement world's per-agent prompt ≈ a 1-settlement world's (measured; a guard test like `test_wave_d2_prompt_diet`).
4. Each settlement renders its own geometry at its center (not just a label); in-transit agents visualized; 2D map shows settlements.
5. Byte-identity: settlements-OFF world is byte-identical to pre-build (goldens green).
6. Full suites green (backend pytest + frontend vitest + tsc), QA gate passed.
7. Live sign-off: run it, found a 2nd city, walk an agent across, watch the feed.

## Out of scope (record, don't build)

EM-112 parallel-worlds runner · EM-116 trade caravans · EM-117 diplomacy/city-city scope ·
EM-119 model-family arena · EM-121 multi-city camera polish · agent-founded **grid growth**
beyond what `found_settlement` already gives · roster scale-up beyond ~10.

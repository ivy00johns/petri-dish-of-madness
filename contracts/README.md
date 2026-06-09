# Contracts — PetriDishOfMadness

Machine-readable integration boundaries. Implementation agents build against these;
`contracts/` is **read-only** to every role-agent. Changes follow the full-rewrite +
version-bump + notify protocol (never a verbal/partial change mid-build).

> Format note: this repo has no `docs/agents/contract-format.md`, so contracts use the
> **existing per-file conventions** (JSON Schema, SQL, OpenAPI YAML, markdown). Run
> `/setup-project-skills` to make that choice durable.

## Inventory

| Contract | Format | Version | Owns the boundary for |
|---|---|---|---|
| `action-protocol.schema.json` | JSON Schema | v1.1.0 | The JSON an agent's model returns each turn (+ EM-066 decision-trace fields) |
| `events.schema.json` | JSON Schema | v1.1.0 | WS `world_state` + `event` messages (+ turn_id/actor_type/sim_time + chain kinds) |
| `db-schema.sql` | SQL DDL | v1.1.0 | SQLite tables (events = append-only spine; snapshots populated) |
| `event-log.md` | Markdown | v1.0.0 | **W5 gate.** Event sourcing, decision-trace chain, snapshots, read/query interface |
| `frontend-inspector.md` | Markdown | v1.0.0 | **W5 gate.** `/` (3D, primary) vs `/inspector` (2D annex) routing + WebGL unmount |
| `api.openapi.yaml` | OpenAPI 3.0.3 | v1.0.0 | REST control API (read endpoints added at W6) |
| `world-model.md` | Markdown | v1.0.0 | Domain entities + mechanics (Building/Project/Animal added at W7/W8) |
| `providers.md` | Markdown | v1.0.0 | Provider `chat()` + Router (usage capture added at W6) |

W6–W8 extend `api.openapi.yaml`, `world-model.md`, `providers.md`, and the config files at
each wave's gate (not speculatively now). The W5 spine (`event-log.md` + the schema
extensions) is locked first because everything downstream reads it.

## Domain rules (cross-agent invariants — must hold across all waves)

1. **The event log is append-only.** No row is updated or deleted. State is a projection.
2. **One agent turn = one `turn_id`.** Every row emitted during that turn (chain rows +
   domain events it caused) carries the same `turn_id`. Non-agent events (`system`/`god`/
   `animal`) may stand alone.
3. **Decision trace is captured in the single existing LLM call** (EM-066). Never add a
   second call to populate a trace. Optional fields ⇒ Mock/deterministic agents stay valid.
4. **Existing v1 invariants still hold** (world-model.md §invariants): credits never
   negative; conserved except via defined sources/sinks; dead agents don't act; active
   rules enforced. New W7/W8 income/cost sources must not break solvability.
5. **Free-scale is a hard constraint.** Favor reflex (no-LLM) resolution, slow ticks,
   caching, and per-provider usage tracking before adding entities. `llm_call` rows are the
   usage substrate (EM-067) — no separate usage table.
6. **Consumers tolerate unknown event kinds.** Adding a kind is enum+payload only, no DDL.
7. **3D village is the primary experience;** the 2D `/inspector` is the analysis annex
   (frontend-inspector.md §0). World-state changes from W7/W8 must be representable in the
   3D scene, not only in 2D panels.

## File ownership (parallel-safe)

| Agent | Owns (writes) |
|---|---|
| persistence-agent | `backend/petridish/persistence/**` |
| backend-agent | `backend/petridish/{engine,agents,api,run.py}/**` |
| providers-agent | `backend/petridish/providers/**` |
| frontend-agent | `web/src/**`, `web/package.json` |
| infra/config | `config/**`, `docker/**`, root `dev`/README |
| qe-agent | `backend/tests/**`, `web/src/**/*.test.*`, `coordination/qa-report.json` |
| (nobody) | `contracts/**` — read-only |

When two roles would touch one file, the orchestrator assigns it to exactly one before
dispatch. `loop.py` (turn-chain emission) and `runtime.py` (decision-trace capture) are
**backend-agent**; the repository write/query methods are **persistence-agent**; the
`llm_call` usage payload is **providers-agent** producing it, backend-agent stamping it.

## Per-agent implementation notes

- **persistence-agent:** keep `repository.py SCHEMA` byte-aligned with `db-schema.sql`; set
  pragmas at connection open; add §7 read methods; populate `snapshots`. Guard the v1.0.0→
  v1.1.0 column adds with `PRAGMA table_info(events)` before `ALTER`.
- **backend-agent:** stamp `turn_id`/`actor_type`/`sim_time` in `_emit_event`; emit the
  ordered chain in `_execute_turn`; thread `turn_id` so domain events inherit it.
- **providers-agent:** add `last_usage` (non-breaking; keep `chat()->str`) extracting
  OpenAI `usage` / Anthropic `usage` / Gemini `usageMetadata` (null-safe); Mock returns none.
- **frontend-agent:** add `react-router-dom`; mount `<Canvas>` only on `/`; verify unmount;
  add the rolling history ref; `tsc -b` + `vite build` green; tokens only (no inline CSS).
- **qe-agent:** assert append-only + chain ordering + turn_id grouping on Mock; replay
  determinism (snapshot+fold == live projection); existing 55 tests stay green.

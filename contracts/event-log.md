# Contract: Append-only Event Log + Replay + Query Interface — v1.0.0

**Wave:** W5 (the gate). **Items:** EM-054 (event-log schema + WAL + snapshots),
EM-066 (structured decision-trace output). **Every later wave (W6–W8) reads this.**
Lock it before building any instrumentation UI.

This contract is the READ + WRITE spec for the simulation's source of truth. It does
**not** introduce a new table — it formalizes the existing `events` table
(`contracts/db-schema.sql`) as an OTel-style trace spine and defines the repository
query methods the `/inspector` views consume.

---

## 1. Principle: event sourcing

- The `events` table is **append-only**. Rows are never updated or deleted.
- `seq` (INTEGER PK AUTOINCREMENT) is the monotonic **event_id** and the total order.
- **Current world state is a projection** of the event stream. The live `world_state`
  WS message is that projection materialized; the DB never needs it to be authoritative.
- **Snapshots bound replay cost.** `replay(T)` = load the nearest `snapshots` row with
  `tick <= T`, then fold `events` forward in `seq` order up to `T`.

## 2. Row shape (`events`)

| column | type | meaning |
|---|---|---|
| `seq` | INTEGER PK | event_id, monotonic, total order |
| `run_id` | INTEGER FK runs(id) | the session |
| `tick` | INTEGER | sim step |
| `sim_time` | REAL | `round(tick * tick_interval_seconds, 3)` — sim seconds |
| `kind` | TEXT | event_type (open-ended, see §4) |
| `actor_id` | TEXT? | acting entity id |
| `actor_type` | TEXT | `human_agent` \| `system` \| `god` \| `animal` (default `human_agent`) |
| `target_id` | TEXT? | other agent/place/structure |
| `profile` | TEXT? | model profile of the actor (color-coding) |
| `turn_id` | TEXT? | correlation id grouping one turn's chain |
| `text` | TEXT? | human-readable feed line |
| `payload_json` | TEXT | kind-specific JSON (open) |
| `ts` | TEXT | wall_time, ISO8601 |

`actor_type` semantics: `system` = engine/random events (no agent), `god` = god-mode
injections (EM-063), `animal` = chaos entities (EM-064). Absent ⇒ `human_agent`.

**Forward-compat is the open `payload_json` + open `kind`.** W6–W8 add new kinds and
payload shapes with **no schema migration**. Consumers MUST ignore unknown kinds.

## 3. The decision trace: one turn = one linked chain

Every **agent** turn emits an ordered chain of rows that all share one `turn_id`
(`uuid4().hex`). This mirrors an OpenTelemetry trace; each row is a span. The writer is
`TickLoop._execute_turn` → `_emit_event` (loop.py); `turn_id`/`actor_type`/`sim_time`
are stamped alongside the existing `seq`/`tick`/`kind`/`ts`.

Ordered chain (kinds + `payload` shapes):

1. **`turn_start`** *(existing kind, now carries turn_id)* —
   `{turn_id, agent_id, profile, location, energy, credits, day}`
2. **`perceived`** — `{visible_agents:[id], nearby_places:[id], overheard:[seq], perceived_summary?}`
   Assembled from `runtime._assemble_context` (co-located agents, place, recent witnessed events).
3. **`memory_retrieved`** — `{memories:[{ref, tick, kind, text, recency?, importance?, relevance?}], window}`
   The memory window fed to the prompt. `recency/importance/relevance` are OPTIONAL scores
   (Smallville-style); emit what's cheaply available, omit the rest.
4. **`llm_call`** — OTel GenAI attribute names:
   `{ "gen_ai.request.model": <profile>, "gen_ai.response.model": <routed_via>,
      "gen_ai.usage.input_tokens": int|null, "gen_ai.usage.output_tokens": int|null,
      "latency_ms": number|null, "gen_ai.response.finish_reasons": [str]|null,
      "cached": bool, "attempt": int }`
   `cached:true` ⇒ no network call (EM-068). **W5 emits one `llm_call` per turn carrying the
   FINAL attempt** (`attempt` = the attempt that produced the result, 1 or 2). On a retry the
   earlier attempt's row is NOT emitted in W5; **per-attempt rows (attempt 1 + 2 sharing the
   turn_id) land in W6 with EM-067**, whose token capture rewrites this emission anyway. Tokens
   are `null` until EM-067.
5. **`reasoning`** — `{reasoning?, perceived_summary?, memories_used?}` from the EM-066
   structured output. Fields are OPTIONAL (Mock/deterministic agents omit them).
6. **`action_chosen`** — `{chosen_tool, args, tier:"reflex"|"llm"}` — the validated action.
7. **`action_resolved`** — `{outcome:"ok"|"gated"|"failed", state_deltas:{energy?,credits?,mood?,...}, routed_via?}`

Plus: any **domain events** the action produces (`economy`, `conflict`, `relationship`,
`agent_speech`, `rule_*`, `agent_died`, …) are emitted as today AND tagged with the same
`turn_id`. So the inspector can show "this `give` (action_resolved) caused this `economy`
transfer and this `relationship` trust bump", all under one turn.

**Failure turns keep the same shape.** A `parse_failure` / `idle` turn emits the SAME ordered
chain, not a truncated one: `perceived` and `memory_retrieved` are still real (context was
assembled before the call), `llm_call` carries the error/finish, `reasoning` and `action_chosen`
carry empty/fallback content (the action falls back to `idle`), and `action_resolved.outcome =
"failed"`. A uniform per-turn chain keeps the decision-trace inspector simple and makes failed
turns just as inspectable as successful ones.

### EM-066 capture rule (zero extra LLM calls)
The structured fields (`perceived_summary`, `memories_used`, `reasoning`) come from the
**same single** model response (action-protocol v1.1.0, all OPTIONAL). The engine reads
whatever is present and distributes it across the `perceived`/`memory_retrieved`/
`reasoning` rows. Never make a second call to "fill in" a trace.

## 4. Event-kind registry (open)

W5 kinds (this contract): the chain kinds above + all existing v1.0.0 kinds. W6–W8 will
add, e.g., `usage_sampled`, `structure_state_changed`, `project_proposed`,
`project_contributed`, `project_completed`, `agent_hot_spawned`, `animal_spawned`,
`animal_action`, `animal_died`. **Adding a kind is enum-only + payload-only — no DDL.**
The registry of kind→payload lives here and grows per wave; consumers default-render
unknown kinds with the generic feed line.

## 5. Snapshots (replay cost bound)

Write a `snapshots(run_id, tick, state_json)` row:
- at run init (`tick 0`),
- on structural change (spawn / kill / reset),
- every `world.snapshot_interval_ticks` thereafter (new config, default **25**).

`state_json` = `world.to_snapshot()` (the same shape as the `world_state` WS message
body). Replay loads the nearest prior snapshot and folds events forward. Target: scrub to
any tick in < 1 s. If it's slower, lower `snapshot_interval_ticks`.

## 6. Durability + concurrency

Pragmas (set once at connection open, see db-schema.sql): `journal_mode=WAL`,
`synchronous=NORMAL`, `busy_timeout=5000`, `wal_autocheckpoint=1000`. **Single writer**
(the tick loop, asyncio single-threaded) — no extra connection, no locking needed; the
`/inspector` reads through the same `_conn` (WAL permits concurrent reads).

**DB path:** default `:memory:` is fine for tests, but a real run that wants replay MUST
pass a **file** `db_path` (config `world.db_path`, e.g. `data/run.sqlite`). Document this
in the README run section. File DBs upgrading from v1.0.0 get the 3 new columns via guarded
`ALTER TABLE events ADD COLUMN` at repo init.

## 7. Repository READ interface (the data-layer contract for W6)

Additive methods on the repository (Python, `snake_case`). **No existing signature
changes.** All are run-scoped, read-only, and return plain dicts (JSON-ready). `EventRow`
= `{seq, run_id, tick, sim_time, kind, actor_id, actor_type, target_id, profile, turn_id,
text, payload, ts}` (`payload` is the parsed dict, not the raw string).

```python
def get_events(run_id: int, *, from_tick: int | None = None, to_tick: int | None = None,
               kinds: list[str] | None = None, actor_id: str | None = None,
               turn_id: str | None = None, after_seq: int | None = None,
               limit: int | None = None, order: str = "asc") -> list[EventRow]: ...
    # order in {"asc","desc"}; after_seq enables keyset pagination for live tailing.

def get_turn_trace(run_id: int, turn_id: str) -> list[EventRow]: ...
    # the full ordered chain for one turn (seq asc).

def get_rule_history(run_id: int) -> list[dict]: ...
    # per rule_id: {rule_id, effect, text, proposer_id, status, created_tick,
    #   votes:[{voter_id, choice, tick}], resolved_tick, outcome,
    #   downstream:[seq]}  -- downstream links the rule to later events it caused
    #   (e.g. an economy/ubi distribution, an agent_died). Powers EM-057.

def get_relationship_timeline(run_id: int, *, agent_id: str | None = None,
               from_tick: int | None = None, to_tick: int | None = None) -> list[EventRow]: ...
    # relationship + conflict + give events, for the time-scrubbed social graph (EM-058).

def get_snapshots(run_id: int) -> list[dict]: ...        # [{tick}] ascending
def nearest_snapshot(run_id: int, tick: int) -> dict | None: ...  # {tick, state} | None

def get_analytics(run_id: int, *, from_tick: int | None = None,
               to_tick: int | None = None) -> dict: ...
    # The 9-AWI + model-vs-model spine (EM-059), computed from event rows:
    # {
    #   population: [{tick, alive}],
    #   crime: {by_kind: {steal:int, attack:int, insult:int, arson:int, ...}},
    #   tool_exploration: {by_agent: {agent_id: unique_tools}},
    #   space_exploration: {by_agent: {agent_id: unique_places}},
    #   governance: {participation: float, proposed:int, passed:int, rejected:int},
    #   public_expression: {say:int, propose_rule:int},
    #   social_fabric: {edges:int, by_type:{ally:int, rival:int, ...}},
    #   economy: {gini: float, throughput: int, by_agent:{agent_id: credits}},
    #   constitution: {active_rules:int, amendments:int},
    #   by_model: {profile: {alive:int, dead:int, crimes:int, gives:int,
    #              proposals:int, passed:int, credit_share: float}},
    #   usage: {by_profile: {profile: {requests:int, input_tokens:int,
    #              output_tokens:int}}}   -- EM-067 reads llm_call rows; no extra table
    # }
```

**No composite AWI score** (mirror the reference system: weighting embeds values). The
dashboard shows the nine indicators side by side; `by_model` is the differentiator cut.

## 8. Ownership & versioning

- **persistence-agent** owns the schema + pragmas + snapshot writes + all §7 query methods.
- **backend-agent** owns stamping `turn_id`/`actor_type`/`sim_time` and emitting the §3
  chain in `loop.py`/`runtime.py`, and surfacing `llm_call` usage (with providers-agent).
- **frontend-agent** consumes §7 over REST (see api.openapi.yaml additions, authored at W6).
- Contract version **v1.0.0**. Bumps follow the full-rewrite + notify protocol.

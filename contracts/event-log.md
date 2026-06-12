# Contract: Append-only Event Log + Replay + Query Interface — v1.3.0

**Wave:** W5 (the gate). **Items:** EM-054 (event-log schema + WAL + snapshots),
EM-066 (structured decision-trace output). **Every later wave (W6–W8) reads this.**
Lock it before building any instrumentation UI.

> **v1.1.0 (W9, 2026-06-09 — audit §B1/B6/B8/C4, EM-070/071/073):**
> 1. **`llm_call` emission is per-attempt, exactly once per attempt.** EM-067's
>    per-attempt emission REPLACED the W5 final-attempt emission; emitting both (two
>    identical rows for one attempt) is a contract violation. One network attempt (or
>    one cache hit) ⇒ exactly one `llm_call` row.
> 2. **Animal turns get their OWN `turn_id`** (`uuid4().hex` per animal turn). Animal
>    events MUST NOT inherit a human agent's in-flight `turn_id` — the engine must not
>    default-stamp the current agent-turn correlation id onto events emitted by
>    concurrent animal/system tasks. `get_turn_trace(agent_turn_id)` returns only that
>    agent's chain.
> 3. **Snapshot boundary semantics (normative):** a snapshot at tick `S` is the state
>    AFTER all tick-`S` events have applied. `replay(T)` = nearest snapshot `S ≤ T`
>    + fold events with `S < e.tick ≤ T` (strict on the left). Producers and consumers
>    (backend `/api/replay`, frontend `replayStateAt`) MUST agree on this. Snapshots
>    additionally serialize the scheduler state needed for a faithful projection:
>    `round`, turn order, and turn index (W9; previously omitted).
> 4. **New kinds (W9, EM-070/071):** `agent_starving`
>    `{energy, turns_until_death, threshold}` — emitted when an agent's energy crosses
>    `world.starving_warn_threshold` (default 25) downward, and once per turn while
>    energy is 0 with the countdown; `text` is a feed-readable warning. `world_extinct`
>    `{tick, last_agent_id, auto_paused}` — emitted when the last living human agent
>    dies; if `world.auto_pause_on_extinction` (default true) the loop pauses after
>    emitting it.

> **v1.3.0 (W11b, 2026-06-09 — EM-079/080/081/083/091/100/101/103):**
> 1. **New kinds (all free-scale — none adds an LLM call):**
>    `billboard_posted {place, text, in_reply_to?}` — the post text rides the SAME turn's
>    model response (EM-066 pattern); god replies use `actor_type:"god"`.
>    `reflection {text, importance}` — diary entry captured from the same single model
>    response, requested in-prompt ONLY when the importance threshold trips (~2–3×/day);
>    never a separate call.
>    `commitment_made {commitment_id, text}` / `commitment_lapsed {commitment_id, text,
>    reason:"phantom"|"expired"}` — `phantom` = claimed in speech, never enacted (EM-079).
>    `usage_alert {provider, metric:"rpd"|"tpd", pct, limit}` — emitted once per
>    provider/metric/window on crossing 70% of a configured cap (EM-083; reads EM-067
>    usage rows).
> 2. **Rule feed text is human-readable (EM-100):** `rule_proposed/rule_vote/rule_passed/
>    rule_rejected` `text` leads with the rule's text + effect ("'Everyone deserves a
>    basic income' (ubi) PASSED"), never the bare uuid hex; the id stays in `payload`.
> 3. **Overhearing (EM-081) adds NO kinds and NO calls:** overheard speech enters ≤2
>    co-located listeners' next-turn `perceived` context (flagged `overheard:true` in
>    that chain event's payload); any immediate reaction is reflex-only.
> 4. **Run forking (EM-101):** `runs` gains nullable `forked_from` + `forked_at_tick`.
>    A forked run's tick-0 state = `World.from_snapshot(replay(T))` of the parent
>    (+ optional `place_overrides`); its first event records the lineage. RunRow
>    (api.openapi 1.4.0) surfaces both fields.
> 5. **`blackout` is real (EM-083):** the random event now applies a concrete effect
>    (recharge disabled at affected places for N ticks), surfaced via the existing
>    `random_event` + `structure_state_changed` kinds.

> **v1.2.0 (W11a, 2026-06-09 — EM-086/094):**
> 1. **New kind `narrator_summary`** (EM-094 Narrator mode, OFF by default):
>    `actor_type:"system"`, `actor_id:"narrator"`, `text` = the 2–3 sentence recap,
>    `payload {from_tick, to_tick, profile, routed_via?}`. Emitted at most once per
>    `world.narrator.every_n_ticks` (default 50) and ONLY when `world.narrator.enabled`
>    — it consumes a real LLM call on `world.narrator.model_profile`, so it is
>    rate-limited and never retried (a failed narrator call emits nothing; the loop
>    must never stall on it). The always-on "story so far" digest is computed
>    client-side from existing events and emits NOTHING.
> 2. **Animal movement carries `payload.place`** (EM-086 note 3): `animal_action` rows
>    whose action moves the animal MUST include the destination `payload.place`, making
>    animal replay exact instead of `~`-approximate. Additive; consumers keep their
>    fallback for old rows.
> 3. **Run-scoped reads are first-class** (EM-086): every §7 read method already takes
>    `run_id`; the REST layer now exposes it (api.openapi.yaml v1.3.0 `/api/runs` +
>    optional `run_id` query param). Active run = `MAX(id)`, never the `status` column.
>    Past-run geometry comes from that run's earliest snapshot `state_json`, not the
>    live-owned `places` table.

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

Wave E kinds (contracts/wave-e.md):

- `relationship_changed` (B1 / EM-113) — emitted ONLY on relationship TYPE
  transitions (reflex friend/feud shifts after a trust mutation, or an accepted
  `set_relationship` type change), riding the triggering action's `_multi`
  chain (same turn_id). `actor_id` = the relationship's owner, `target_id` =
  the other agent — both AGENT ids only (EM-141: the social-graph selector
  drops non-agent endpoints). Payload:
  `{from_type, to_type, trust, since_tick}` where `to_type` ∈
  `neutral|ally|friend|rival|enemy|partner|family|mentor|feud` and
  `since_tick` is the tick the type changed.

- `child_spawned` (B2 / EM-114) — the birth narrative event, emitted at the
  ROUND boundary when a mutual-partner pair co-located at a home passes every
  birth gate (population/housing caps, credits/energy, pair + world cooldown,
  the seeded chance gate). `actor_id` = the CHILD's agent id,
  `actor_type` = system, `target_id` = null (agent-id-only endpoints, EM-141).
  Text `"👶 {name} is born to {p1} and {p2}"`. Payload:
  `{child_id, parents: [sorted parent agent ids], name, profile, place}`.
  ALWAYS paired with a standard `agent_spawned{method: "birth", parents}` for
  the frontend roster contract — both ride the `pending_spawn_events` outbox
  (the EM-062/168 governance-spawn drain) as standalone system events
  (`turn_id` null).

- `faction_formed` / `faction_joined` / `faction_left` / `faction_dissolved`
  (B3 / EM-120) — emitted at the ROUND boundary (after the birth check) when
  the faction recompute DIFFS against the stored memberships; a stable round
  emits NOTHING. All four ride the same `pending_spawn_events` outbox as
  births (standalone system events, `actor_type` system, `turn_id` null) and
  carry ONLY agent ids in actor_id/target_id (EM-141; `target_id` null).
  - `faction_formed` — a new component (size >= `factions.faction_min_size`
    over mutual warm edges) with no >= 50%-overlap match to an existing
    faction. `actor_id` = the oldest founding member (LOWEST agent id).
    Payload: `{faction_id, name, members: [sorted agent ids]}` where
    `faction_id = fct_{8 hex of sha1(sorted founding members + tick)}` and
    `name = "{oldest founding member's name}'s circle"`.
  - `faction_joined` / `faction_left` — membership churn on a faction that
    KEPT its identity. `actor_id` = the joining/leaving agent. Payload:
    `{faction_id, name}`.
  - `faction_dissolved` — an old faction with no >= 50%-overlap successor
    component (including shrinking under `faction_min_size`). `actor_id` =
    the lowest member id of the OLD membership. Payload:
    `{faction_id, name, members: [the old membership]}`.

- `reflection` payload gains ADDITIVE `bond_applied: {target_id, type}`
  (B4 / EM-125) — present ONLY when the reflection-declared bond landed
  (type ∈ `friend|partner|mentor|feud`; B1 guards applied). The bond's own
  `relationship_changed` rides the SAME turn chain (same turn_id) as the
  reflection; rejected bonds add NO event kind and NO payload key — the
  reason lands in the decision trace as `bond_rejected` only. No new kinds,
  no extra `llm_call` rows: the bond rides the existing single reflection
  call.

- `god_miracle` (B5 / EM-184) — a WORLD-scale god intervention, cast via
  `POST /api/god/intervene` with NO agent_id (the targeted
  bless_energy/grant_credits keep emitting `god_intervention`).
  `actor_id` = `'god'`, `actor_type` = `'god'`, `target_id` = null,
  `turn_id` = null (god mutations happen outside any agent turn). Payload:
  `{kind, until_tick?}` where `kind` ∈ `send_rain|bountiful_harvest|
  calm_spirits` and `until_tick` is present for the two TIMED kinds only
  (`tick + days × turns_per_day`; re-casting an active kind refreshes it —
  never stacks, never re-adds). Globally witnessed (every living agent's
  memory, like `random_event`) and importance-weighted 2.0 so the whole town
  can react — this closes the petition→miracle belief loop. A `calm_spirits`
  cast may be accompanied IN THE SAME emission batch by the
  `relationship_changed` events its trust nudges triggered (B1 reflex
  transitions, turn_id null — the god path drains the B1 outbox itself).

- `miracle_expired` (B5 / EM-184) — a timed miracle's window elapsed
  (`tick >= until_tick`), swept in the same per-tick loop path as blackout
  expiry. Standalone system event: `actor_id` null, `actor_type` = system,
  `target_id` null, `turn_id` null. Text e.g. `"☀ The rains pass — forage
  returns to normal."`. Payload: `{kind, until_tick}`. Emitted exactly once
  per expiry; the one-time `calm_spirits` never produces one.

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

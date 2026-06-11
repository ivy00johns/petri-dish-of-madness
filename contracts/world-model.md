# Contract: World Model (shared domain) — v1.1.0

The single source of truth for entities and mechanics. Backend implements it; frontend
renders it; QE tests it. Changes go through the orchestrator (version bump + notify).

> **v1.1.0 (W7)** adds the **Building** entity (which doubles as the collective-project
> pipeline), a **tiered tool catalog**, ad-hoc **spawn modes**, and **decision caching**.
> Buildings live in the world snapshot + event log — **no new SQL tables** (event-sourcing).
> See §W7 below. These render in the **3D village** (primary view), not only the inspector.

## Entities

### Place
A named location. Agents are *at* a place (graph nodes, not free x/y) — cheap for LLM
context, spatial for rendering.
```
Place { id: str, name: str, x: int, y: int, kind: "work"|"home"|"social"|"governance"|"wild", description: str }
```
`x,y` are map coordinates (0–1000 canvas space) for rendering only.

### Agent
```
Agent {
  id: str, name: str, personality: str (<= 280 chars),
  profile: str,            # model-profile name (see providers contract); drives color + LLM
  location: str,           # place id
  energy: float,           # 0..100
  credits: int,            # >= 0
  mood: str,               # short free text, set by agent
  alive: bool,
  zero_energy_turns: int,  # consecutive turns at energy<=0
  beliefs: [str],          # remember()-ed facts (cap 20, FIFO)
  relationships: { agent_id: { type: "ally"|"rival"|"neutral"|"friend"|"enemy", trust: int (-100..100), interactions: int } }
}
```

### Rule (governance)
```
Rule {
  id: str, effect: "ban_stealing"|"ubi"|"recharge_subsidy"|"work_bonus",
  text: str, proposer_id: str, status: "proposed"|"active"|"rejected",
  votes: { agent_id: bool }, created_tick: int
}
```
Effect semantics when `active`:
- `ban_stealing` → `steal` action is rejected (validation fails → idle).
- `ubi` → every living agent gains `world.ubi_amount` credits at the start of each round.
- `recharge_subsidy` → `recharge_cost` halved (min 1).
- `work_bonus` → `work_reward` +50%.

### Event (append-only log + WS stream) — see events.schema.json

## Tick / turn loop
- **Turn** = one agent acts (round-robin over living agents, stable order).
- **Round** = every living agent has taken one turn. Apply per-round effects (UBI) at round start.
- Per **turn**: apply energy decay (`energy_decay_per_turn`); assemble context; call model;
  parse+validate action; apply effects; persist; emit events; death check.
- **Death check**: if `energy <= 0`, increment `zero_energy_turns`; when it reaches
  `death_after_zero_turns`, set `alive=false`, emit `agent_died`. Dead agents are skipped.
- `tick_interval_seconds` is the real wall-clock pause between turns (the "speed" control).
- A counter `tick` increments every turn; `day = tick // turns_per_day`.

## Economy
- `work` (only at `kind=="work"` place): +`work_reward` credits.
- `forage` (anywhere): +`forage_reward` credits.
- `recharge`: spend `recharge_cost` credits → +`recharge_amount` energy (capped 100). Fails if insufficient credits.
- `give`: transfer `amount` credits to a target at the same place (must afford). +trust.
- `steal`: take min(target.credits, `steal_max`) from a co-located target; success unless `ban_stealing` active. -trust, target relationship → rival/enemy.

## Social
- `say`: broadcast text to all living agents at the same place → `agent_speech` event.
- `whisper`: text to one co-located target → `agent_speech` event (private=true).
- `insult`/`attack`: co-located target; -trust; emits conflict event. `attack` also drains a little of both agents' energy.
- `set_relationship`: declare a relationship type toward a target.

## Memory (cheap, no LLM summarization)
- Rolling buffer: the last `memory_window` events the agent witnessed (at its location or involving it).
- `beliefs`: agent-chosen persisted facts (cap 20).
- `relationships` map.

## Invariants (QE asserts)
1. Credits never negative. Credits change only via work/forage/recharge/give/steal/ubi **and the W7 construction sinks (contribute_funds)**.
2. Dead agents take no turns and emit no actions.
3. `ban_stealing` active ⇒ zero successful steals.
4. A rule becomes `active` iff `count(votes==true) > floor(living_count/2)` at evaluation.
5. Energy ∈ [0,100]; a passed `recharge` strictly increases energy unless already 100.
6. **(W7)** A Building's `function` is granted ONLY while `status=="operational"`. `progress`∈[0,100], `health`∈[0,100], `funds_committed`≥0. A Building reaches `operational` iff `progress==100`. Credits spent on `contribute_funds` are conserved (leave the agent, accrue to `funds_committed`).

---

## §W7 — Expanded world (v1.1.0)

### Building (entity; also the collective-project pipeline)
A **project is a Building in `planned`/`under_construction`** — one entity, one lifecycle. The
"clock tower that never got built" is a Building stuck in `under_construction` (abandoned).
```
Building {
  id: str, name: str, kind: str,            # clocktower|garden|workshop|farm|library|house|monument|...
  location: str,                            # place id
  owner_id: str | null,                     # agent id | "public" | null
  status: "planned"|"under_construction"|"operational"|"damaged"|"offline"|"abandoned"|"destroyed",
  health: int (0..100), condition_label: "pristine"|"worn"|"damaged"|"ruined",
  progress: int (0..100),
  funds_committed: int, funds_required: int, contributors: [agent_id],
  function: str,                            # utility while operational, e.g. "+forage" | "+energy" | "voting"
  last_progress_tick: int, created_tick: int, updated_tick: int
}
```
**State machine** (every transition emits a `structure_state_changed` event with `{building_id, from, to, reason}`):
- `planned → under_construction` — `funds_committed >= funds_required` AND a first `build_step`.
- `under_construction → operational` — `progress == 100`. (emits `building_operational`; function activates.)
- `operational → damaged` — `arson`/vandalize drops `health`; `damaged → destroyed` when `health == 0`.
- `damaged → operational` — `repair` restores `health` to 100.
- `operational → offline` — `take_offline` (owner only); `offline → operational` — `repair`/reactivate.
- `* → abandoned` — no `build_step`/`contribute_funds` for `buildings.abandon_after_ticks` while not operational (the realistic collective failure). Engine checks per round.

Function granted ONLY while `operational` (invariant 6). A `garden`/`farm` grants `+forage` at its
place; a `clocktower`/`monument` is cultural (no mechanical buff); `workshop` `+work_reward`; etc.
(exact buffs in config; keep small/free-scale).

### Tiered tool catalog (EM-060)
Each action carries registry metadata `{tier, location_gate, agreement_gate}`:
- **tier** — `reflex` (engine resolves deterministically; the LLM still *chooses* it as its one
  turn-action, but no extra call) vs `llm` (the choice is the reasoning-heavy turn). In this sim
  every agent turn is exactly one LLM call; tier mainly drives prompt framing + future no-LLM
  animal reflexes (W8). Resolution is ALWAYS engine code.
- **location_gate** — action only offered when the agent is at a place of this `kind` (e.g.
  `propose_rule`/`vote` at `governance`; `build_step` at the building's place; `work` at `work`).
  Gating shrinks the per-turn action list → smaller prompts (free-scale win).
- **agreement_gate** — blocked by an active rule (e.g. `steal` by `ban_stealing`; `arson` by a
  `ban_arson` rule if present).
Context assembly filters `valid_actions` by these gates; `_validate_world` enforces them.

### New actions (added to action-protocol.schema.json)
| action | tier | gate | effect |
|---|---|---|---|
| `propose_project` | llm | — | create a Building `status=planned` `{name, kind, funds_required, function?}` at the agent's place; owner=public. emits `structure_state_changed{to:planned}` + `project_proposed`. |
| `contribute_funds` | reflex | must afford | `args:{building_id, amount}` — move `amount` credits from agent → `funds_committed`; add to `contributors`; may flip `planned→under_construction`. emits `economy` + `project_funded`. |
| `build_step` | reflex | at building's place, `under_construction` | `args:{building_id}` — `progress += buildings.build_step`; sets `last_progress_tick`; may flip to `operational`. emits `project_built`. |
| `repair` | reflex | at place, `damaged`/`offline` | `args:{building_id}` — `health=100`, back to `operational`. |
| `arson` | reflex | co-located; blocked by `ban_arson` if active | `args:{building_id}` — `health -= buildings.arson_damage`; `→damaged`/`destroyed`. crime (−trust witnesses). emits `conflict` + `structure_state_changed`. |
| `take_offline` | reflex | owner only | `args:{building_id}` — `operational→offline`. |

Existing actions keep their semantics; they gain registry tiers (movement/economy/perception =
reflex; say/propose_rule = llm). `propose_rule` MAY gain a `ban_arson` effect (optional).

**Implementation return contract (locked — the W7 integration boundary):** the six
`world.action_*` methods take `(agent, building_id: str[, amount])` and RETURN a ready-to-emit
**event dict**, or `{"_multi": [event, ...]}` for multi-event outcomes (NOT the `(ok, reason,
value)` tuple some older `action_*` used) — `propose_project` also returns `"_building_id"`. On a
bad/illegal id they return a `parse_failure` event dict, never raise. The runtime's `_apply_action`
consumes these exactly like the existing `vote → {_multi:[...]}` branch (spread base
`{profile, profile_color, tick}` onto each and emit); it does NOT unpack a tuple and passes the
**id string**, not a Building object. `_validate_world` gates BEFORE dispatch (build_step:
under_construction + at the building's place; arson: blocked by active `ban_arson`; contribute:
affordability; take_offline: owner). Governance spawn: the API calls
`world.enqueue_admit_agent(...)` (not `propose_admit_agent`) and returns its `rule.id` as `proposal_id`.

### Ad-hoc spawn (EM-063)
Two paths, selected by config `spawn.mode` (default `god`):
- **god** — immediate: `POST /api/agents` (exists) spawns now; emits `agent_spawned{method:"god"}`. A
  God-panel button in the control UI drives it (persona + profile picker).
- **governance** — `POST /api/agents` with the flag enqueues an `admit_agent` proposal; the agent
  enters only if the vote passes threshold; emits `agent_spawned{method:"governance", proposal_id}`.
A hot-joined agent enters the round-robin at end of the current round, with empty memory; nearby
agents get a `perceived`/`agent_spawned` so they notice the newcomer.

### world_state additions
`world.to_snapshot()` and the WS `world_state` message gain `buildings: [Building]` (and, in W8,
`animals: [Animal]`). The 3D village renders each Building by `status`: `planned` (stake/outline),
`under_construction` (scaffolding + progress), `operational` (finished, tinted by kind),
`damaged` (scorched), `destroyed` (rubble). Frontend reads `buildings` from `world_state`.

### Decision caching (EM-068) — see providers.md
Router-level cache keyed on `hash(messages + profile)`; a hit returns the prior text and sets
`llm_call.cached=true` (no network). Config `cache.enabled` (default true), small LRU. Saves
repeated identical-context turns (free-scale). Never caches across different world state (the
messages embed the world state, so identical-key ⇒ identical situation).

---

## §W8 — The chaos layer (v1.2.0): LLM-driven animals

Animals are a **distinct entity type** (`actor_type:"animal"`), NOT human agents — own persona,
own (looser) action set, own scheduling, own logging channel. They share the world mechanically
(places, buildings, can damage structures) but are framed to the LLM as critters that act
**impulsively and in-character, not to optimize**.

### Animal (entity)
```
Animal {
  id: str, species: "cat"|"dog", name: str,
  location: str,                 # place id
  energy: int (0..100), mood: str,
  alive: bool, created_tick: int
}
```
Animals have NO credits account (a "bank robbery" by the cat is comedic but logged). They live
in `world.animals: dict[str, Animal]`; `to_snapshot()` gains `animals: [Animal]` and the WS
`world_state` carries them. The 3D village renders a roaming cat + dog (tinted, species-shaped).

### Scheduling (free-scale — this is the biggest cost risk)
Animals act on a **slower cadence**, NOT every round. Config `animals.act_every_n_ticks` (default
3). On an animal's tick, **roll-for-activity**:
- **Most of the time → a REFLEX micro-behavior** (NO LLM call): pick from a cheap weighted table
  (`wander`, `nap`, `knock_over`, `scratch`, `mark_territory`, `pounce`, `chase`). Pure engine.
- **Occasionally (prob `animals.llm_chance`, default 0.25) → an LLM decision** routed to the
  **cheapest/fastest free model** (`animals.model_profile`), producing an in-character
  `animal_thought` + an action. This is where "the LLM decided the cat should commit arson" comes
  from — the toolset is UNDER-CONSTRAINED.

### Animal action set (animal-action protocol — see below)
Reflex/in-character: `wander`, `nap`, `knock_over(target?)`, `scratch(target?)`,
`mark_territory`, `pounce(target?)`, `chase(target?)`, `idle`. Under-constrained escalations the
LLM MAY choose for absurd effect: `steal_food(target)`, `arson(building_id)` (a cat that "starts a
fire" flips a building → `damaged`/`destroyed`, reusing the W7 arson resolution). Animals can't
`vote`/`propose_rule` (no standing) — but their actions become **subjects** of governance (agents
may `propose_rule` "ban the cat", a visible try/fail).

### Chaos surfacing (EM-065)
Every animal event carries `actor_type:"animal"` and an `is_chaotic: bool` heuristic — true when
the animal invokes a crime/economy/structure-targeting tool (`arson`, `steal_food`, `knock_over`
on a building) or an otherwise low-prior action. Events: `animal_spawned`, `animal_action`,
`animal_died`. The **Animal Chaos Feed** (frontend) is a filtered magenta stream of animal
decisions — `animal_thought` + the action + the consequence — and animal markers are **magenta**
on the replay timeline (the legend slot already exists).

### Free-scale guarantees (QE asserts)
- An animal makes **at most one** LLM call per *acted* tick, and only with probability
  `llm_chance`; reflex ticks make **zero** LLM calls.
- Animals never escalate to a paid profile; if `animals.model_profile` is unavailable, they fall
  back to reflex-only (no crash).
- Animal decisions are cacheable (router cache) like agents.

### Invariants (QE asserts)
7. Animals never gain/spend credits (no economy account); an animal "theft" moves goods/❤️ not
   credits, and total agent credits are unchanged by animal actions.
8. Animal damage to a building obeys the W7 building state machine (operational→damaged→destroyed);
   an animal can't push a building below 0 health or above 100.

## §W15 — City snapshot contract (EM-155) — ADDITIVE delta

`World` gains `city_seed: int` (config `world.city_seed`, default **1337**).
`to_snapshot()` emits `"city_seed"`; `from_snapshot()` restores it int-coerced
(absent ⇒ 1337, so pre-W15 snapshots stay valid). It therefore rides the WS
`world_state` payload and survives fork (EM-101) and replay (EM-075).
Frontend: `WorldState.city_seed?: number | null` (additive, optional);
consumers default with `city_seed ?? 1337`. The generated 3D city ring is a
pure function `f(snapshot, city_seed)` — same snapshot + same seed ⇒
byte-identical city plan across live/replay/fork.

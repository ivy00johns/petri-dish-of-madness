# Contract: World Model (shared domain) — v1.0.0

The single source of truth for entities and mechanics. Backend implements it; frontend
renders it; QE tests it. Changes go through the orchestrator (version bump + notify).

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
1. Credits never negative. Credits change only via work/forage/recharge/give/steal/ubi.
2. Dead agents take no turns and emit no actions.
3. `ban_stealing` active ⇒ zero successful steals.
4. A rule becomes `active` iff `count(votes==true) > floor(living_count/2)` at evaluation.
5. Energy ∈ [0,100]; a passed `recharge` strictly increases energy unless already 100.

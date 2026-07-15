# Contract: Settlement + Travel (backend-core)

**Version:** 1.0.0 · **Owner:** backend-core · **Consumers:** frontend, qe

Realizes multi-city via the EXISTING `Settlement` primitive (EM-269 F2, `World.settlements`).
Adds travel (EM-110) + per-settlement scoping. All gated on `settlements.enabled` (default
OFF ⇒ byte-identical). Distances/IDs seeded; NO uuid4/random/clock on the tick path.

## 1. AgentState — 3 additive fields (world.py `AgentState`, ~:539)

```python
home_settlement_id: str | None = None   # the agent's current city; None = unsettled/primordial
in_transit_to:      str | None = None    # target settlement id while traveling; None = not traveling
transit_arrival_tick: int | None = None  # tick the agent arrives; None when not traveling
```
- **Serialize only-when-non-default** (mirror `RelationshipState.scope`, world.py:777): each
  key emitted in `to_dict()` ONLY when not None; `from_dict` defaults to None when absent.
  ⇒ a settlements-OFF world's agent dicts are byte-identical to today.

## 2. Genesis settlement (world.py, gated on `_settlements_enabled()`)

At world init AND reset, when settlements enabled, auto-found ONE genesis settlement at the
plaza center; every seed agent gets `home_settlement_id = <genesis id>` and is added to its
`members`. Seeded id via `_settlement_id(founder="genesis", tick=0, ordinal=0, city_seed)`.
OFF ⇒ nothing created, `home_settlement_id` stays None, byte-identical.

## 3. travel_to — reflex verb (runtime.py verb registry + world.py resolver)

- **Registry:** `travel_to` reflex tier, next to `found_settlement` (runtime.py:556). Menu
  offered ONLY when `_settlements_enabled()` AND `len(world.settlements) > 1` (nowhere to go
  with one city ⇒ verb absent ⇒ prompt unchanged).
- **Args:** `{ "settlement": "<settlement_id or name>" }`.
- **Resolver `action_travel_to(agent, target)` (world.py):**
  - Reject if: settlements disabled · target unknown · target == `home_settlement_id` ·
    agent already `in_transit_to` is not None. Return a normal action-failure string (feed-safe).
  - Success: `in_transit_to = target`; `transit_arrival_tick = tick + travel_ticks(home, target)`;
    emit `travel_departed` `{from_settlement, to_settlement, arrival_tick}`. Agent is now off-board.
- **`travel_ticks(a, b)`** = `max(TRAVEL_MIN_TICKS, ceil(world_distance(center_a, center_b) / TRAVEL_SPEED))`.
  Pure fn of settlement centers (world-frame floats already in `settlements[id]["center"]`).
  Constants module-level in world.py: `TRAVEL_SPEED`, `TRAVEL_MIN_TICKS` (pick sane defaults,
  e.g. SPEED so a cross-map trip is ~a few rounds; document them).

## 4. In-transit = off-board (world.py scheduler — the free-scale saving)

- `_rebuild_turn_order()` / `next_agent()` (world.py:2142/2193): an agent with
  `in_transit_to is not None` AND `tick < transit_arrival_tick` is **excluded** from the due
  set — it takes **0 LLM calls** while traveling. (Do NOT mute; it simply isn't scheduled.)
- **Arrival resolution** at a round boundary (or in `next_agent` when picking): for any agent
  with `in_transit_to is not None` AND `tick >= transit_arrival_tick`:
  - `home_settlement_id = in_transit_to`; move `location` to the target settlement's anchor
    place (nearest place to the target center, else the plaza); remove from old settlement
    `members`, add to new; clear `in_transit_to` / `transit_arrival_tick`.
  - Emit `travel_arrived` `{settlement, tick}`. Agent rejoins the rotation next round.
  - **Migration note:** credits/skills/memories live ON the agent and move WITH it
    automatically — migration = updating `home_settlement_id` + `location` + membership. Do
    NOT rebuild memories. Relationships keep `scope="local"` (unchanged this slice).

## 5. Per-settlement perception scoping (runtime.py `_assemble_context`, :2668)

- **Goal: prompt size FLAT regardless of #settlements.** Extend the existing diet horizon
  (`_diet_visible_districts` / `_place_visible`, :2720): an agent perceives only places whose
  settlement == the agent's `home_settlement_id`. Place→settlement =
  `settlement_of_place(place)` = `nearest_settlement(logical_to_world(place.x,place.y), within=R)`
  (reuse `nearest_settlement`, world.py:4108). Places outside the agent's settlement are hidden.
- Keep the compact existing "🏘 SETTLEMENTS" roster line (one line, other cities summarized) —
  that's the flat cross-city awareness. An `in_transit` agent's block shows a "traveling to X,
  arrives tick N" line instead of local perception.
- OFF path unchanged (settlement scoping only applies when enabled) ⇒ byte-identical.

## 6. Events (new kinds — frontend + feed consume)

`travel_departed` · `travel_arrived` — both carry `actor_id`, `from_settlement`/`to_settlement`
(or `settlement`), `arrival_tick`/`tick`, a human `text`, and a profile color. Feed-safe
(normal event cards, not errors). `settlement_founded` already exists.

## 7. Snapshot (world.py to_snapshot/from_snapshot)

Settlements already round-trip (:10288/:11060). The 3 new AgentState fields ride the agent
dicts (only-when-non-default). NO new top-level snapshot key needed. Assert: a world with a
traveling agent restores with identical `in_transit_to`/`transit_arrival_tick`.

## 8. Config (config/world.yaml + loader.py)

- `settlements.enabled: true` (was false) — the live opt-in. Add a `travel` sub-block if a
  separate gate is wanted (else travel rides `settlements.enabled`). Keep loader defaults OFF.
- Roster: leave `agent_count` small (~5–10) per the scope decision. Do NOT scale it here.

## Acceptance (backend-core self-check before wave gate)

- [ ] settlements-OFF: full determinism goldens byte-identical (the existing suite).
- [ ] Genesis settlement seeded deterministically when ON; two runs same seed ⇒ same id.
- [ ] `travel_to` → agent off-board (not in `next_agent` output) until `transit_arrival_tick`, then home migrates + rejoins.
- [ ] Prompt size for a 2-settlement world ≈ 1-settlement world (flat), verified.
- [ ] Traveling agent survives snapshot round-trip identically.

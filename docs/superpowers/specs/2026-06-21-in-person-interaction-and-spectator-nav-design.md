# In-person agent interaction + spectator navigation — design

**Status:** Proposed · **Date:** 2026-06-21 · **Owner:** TBD
**Extends:** EM-095 (camera nav), EM-124 (movement), EM-081 (reactive overhearing), EM-223 (planning)

---

## 1. Overview

Make the 3-D world legibly reflect the rich in-person interactions the backend already
simulates, add walk-to street pathing, let crowds gather at unfolding drama, and add a
**click-to-watch** spectator camera so you can fly over and watch a robbery or arson happen.

Delivered in **three phases**, each shippable on its own:

1. **Legible in-person interaction** — frontend-only; agents face/cluster/react.
2. **Click-to-watch navigation** — feed↔world linkage + scene-framing camera (+ a small,
   additive backend data change).
3. **Crowds gather** — deterministic, LLM-free convergence on drama (flagged).

## 2. Motivation / context

The backend already simulates **logical** in-person interaction:

- `steal`, `attack`, `give`, `whisper`, `say`, and `arson` all require both agents at the
  **same place** (`if agent.location != target.location: fail`).
- A crime's **witnesses are exactly the co-located agents**, who lose trust in the perpetrator.

So robberies and arson already happen "in person" in the data. The **3-D world just doesn't
show it**:

- Co-located agents stand in a ring **facing outward** and never react — a robbery looks
  identical to idle standing.
- Agents **slide in straight lines** between places (no street-walking).
- The feed and the world are **decoupled** — clicking an event does nothing, so there is no
  way to navigate to watch an event unfold.

## 3. Goals / non-goals

**Goals**
- Co-located, interacting agents visibly face each other, cluster into conversation huddles,
  and play a reaction beat on crimes.
- Agents walk along streets between places.
- Click any agent / chat / event → camera flies there and frames the scene (actor + target +
  witnesses). Cycle between agents and notable events.
- Nearby agents converge on crimes so a watchable crowd forms.

**Non-goals**
- No continuous-coordinate physics or collision; positions stay place-anchored.
- No `in_transit` time-cost in the sim (see §7, rejected).
- No auto-cut "director" camera — the camera **never moves without a user action**; the chat
  feed stays the centerpiece.
- No reduction in LLM call-rate anywhere (north-star: "do MORE, never less").

## 4. Hard constraints

- **Max call-rate.** Movement/gathering is **reflex/deterministic and LLM-free**; it never
  consumes an agent's speaking turn. No transit time-sink. No throttling.
- **Replay-safe.** No wall-clock, no RNG; only `world.tick` and the existing `_seed_int`.
- **Byte-identity when off.** New backend behavior ships behind a flag, default off → snapshots
  and prompts are unchanged from today.
- **Graceful degradation.** Frontend works before the backend `location` field lands (resolves
  from actor position), and upgrades silently once it does.

## 5. Current state — reuse, do not reinvent

**Frontend** (`web/src/components/world3d/`)
- `characterAnim.ts` — `nextMoving`, `clipFor`, `yawTowards`, `stepYaw`, `wrapAngle`.
- `worldSpace.ts` — `placeToWorld`, `ringOffset(center,idx,count)`, `slotLayout`, `SIZE=66`.
- `cityLayout.ts` — frozen 5×5 block grid, road centerlines, zones (the pathing network).
- `Villager.tsx` / `Critter.tsx` — rigged GLB bodies, walk/idle clips, per-frame lerp of a
  mutable `animRef` toward a `target`, speech bubbles, focus ring, click→onPick.
- `CozyWorld.tsx` — `CameraDirector` (`free`/`follow`/`transit`/`reset`), `animMap`/`critterMap`
  live-position source of truth, `resolveFocus`, event-scan `useMemo`s with seq-recency decay
  (`CHAOS_RECENCY_SEQ`).
- `App.tsx` `LiveLayout` — owns `focus`/`resetNonce`/`handleFocus` (the feed↔camera junction);
  `RosterStrip.tsx` card click → `onSelect(FocusTarget)`.
- `feed/EventFeed.tsx` — newest-first feed; crime/chaos kinds already get a magenta accent.
- `types/index.ts` — `FocusTarget = {type:'agent'|'animal'|'place', id}`.

**Backend** (`backend/petridish/`)
- `engine/world.py` — `AgentState.location`, `PlaceState{x,y}`, co-location gates
  (`action_steal` ~1257, `action_attack` ~1690, `action_arson` ~2561), witness loops
  (`agents_at`, arson ~2576), `_update_trust`, `to_snapshot` ~4174.
- `engine/loop.py` — `_execute_turn` (sequential, one agent/turn), `_emit_event` ~1874,
  `_broadcast_world_state` ~1912; reactive overhearing (EM-081), salience gating (EM-159/160).
- `agents/runtime.py` — `ACTION_SCHEMA`; **`move_to` is a reflex (zero LLM)**; `_reflex_pick`
  (plan-biased, EM-223); `push_event`/`_event_importance` ~2658; `base` event dict ~4163.
- `persistence/repository.py` — events table (~86): seq, tick, kind, actor_id, target_id,
  payload_json, ts … **no `location` column today**; reads use explicit `_EVENT_COLS` (~422),
  never `SELECT *`, so `ALTER ADD COLUMN` is safe.
- `config/loader.py` — `PlanningParams`/`_parse_planning` is the template for a flagged param block.

---

## 6. Architecture

### Phase 1 — Legible in-person interaction (frontend-only)

Goal: a robbery *looks* like a robbery. No backend dependency.

**New pure module `world3d/interactionScan.ts`** (the Phase-1 analog of the existing
`chaoticAnimals` scan; pure → unit-testable like `characterAnim.test.ts`):
- `scanInteractions(events, agents) → { facing: Map<id,id>, reacting: Map<id,number>, conversations: Map<placeId,Set<id>> }`.
  One newest-first pass, early-break by seq window. A *directed* event = has both `actor_id`
  and `target_id` resolving to agents at the **same** location (keys on shape, not a kind
  whitelist → survives backend kind churn). Newest wins for `facing`; `reacting` intensity
  decays by seq recency (reuse the `CHAOS_RECENCY_SEQ` idiom).
- `resolveEventLocation(event, agents)` → `event.location` if present, else actor's
  `location`, else target's, else null. **The single graceful-degradation seam** every
  location-dependent path routes through.
- `CRIME_KINDS` predicate (mirrors the feed's magenta logic so registers agree).

**`worldSpace.ts`** — add `huddleOffset(center,idx,count,radius=1.4)` (thin wrapper over
`ringOffset`, tighter radius). Do **not** change `ringOffset` (Critters depend on it).
Facing-inward is a yaw concern (Villager), not a position concern.

**New pure module `world3d/roadRouter.ts`** (walk-to pathing, ~30 lines, no A*):
- `routeWaypoints(from, to) → WorldPoint[]` — snap to nearest road centerline (from
  `cityLayout`), Manhattan along streets, turn once, arrive; cap ~4 waypoints; in-block trips
  (`< BLOCK_PITCH`) return `[to]` so ring/huddle re-seating stays a straight lerp.
- Lockstep test asserts the router's road lines equal `cityLayout`'s centerlines.

**`Villager.tsx`** (movement/lerp untouched; add facing + waypoint queue + reaction beat):
- New props `faceTargetId`, `getAnimPos(id)` (bound to `animMap.current.get`, read in-frame,
  no re-render), `reaction` (0..1).
- Facing: while ~stationary and `faceTargetId` resolves, `stepYaw` toward it (override the
  "idle holds last facing" branch). Direction-of-travel still wins while walking.
- Waypoint queue: on a real `location` change, load `routeWaypoints(animRef, target)`; lerp
  to `waypoints[0]`, shift on arrival, settle on `target`. Existing `nextMoving` + `clipFor`
  consume per-waypoint distance unchanged → walk animation "just works."
- Reaction beat: on `reaction>0`, a time-boxed recoil on a local child group (labels/bubbles
  unaffected) + a `ReactionBillboard` ("!"/emoji) fading with `opacity=reaction`.

**`CozyWorld.tsx`** — add `interactions = useMemo(() => scanInteractions(events, world?.agents ?? []), [events, world])`;
in `Scene`, pick `huddleOffset` vs `ringOffset` per place when a conversation is active;
thread `faceTargetId`/`getAnimPos`/`reaction` into each `<Villager>`. No camera change yet.

### Phase 2 — Click-to-watch navigation + event data backbone

Goal: click any agent/chat/event → camera flies there and frames the scene. Never auto-fires.

**Backend data backbone** (additive, always-on, no behavior change):
1. **Event `location` field.** Add `"location": agent.location` to the `base` event dict
   (`runtime.py` ~4163); spreads onto every action event; `_multi` events (arson/structure)
   inherit via `{**base, **evt}`. `move_to` sets `location`=destination, origin in
   `payload.from`. Stamp at loop level (`loop.py` `_emit_event` ~1874; explicit on
   `turn_start`/`agent_died`). DB: nullable `location TEXT` in the events `SCHEMA`, an
   idempotent `_migrate_events_location()` (mirror `_migrate_events_v1_1_0` ~145), and the
   column added to `save_event`/`_EVENT_COLS`/`_row_to_eventrow`. `ALTER ADD COLUMN` backfills
   the existing `data/run.sqlite` as NULL instantly (schema change, not table rewrite).
2. **Witness roster.** New pure `world.witness_ids(place_id, exclude)` → **sorted**
   (byte-stable) living co-located ids; attach as `payload.witnesses` on arson/steal/attack
   via the existing witness loops.

**Frontend navigation:**
- `types/index.ts` — extend `FocusTarget` with `{ type:'scene', placeId, participantIds }`.
  Feed/world resolve an *event* → scene at click time (via `resolveEventLocation` + witness
  set); the camera layer never touches raw events.
- `worldSpace.ts` — `frameScene(points) → {center, radius}` (centroid + max distance) and
  `dollyForRadius(radius, fov)` (fit formula, clamped to controls min/max). Pure, trig-only.
- `CozyWorld.tsx` — `resolveFocus` gains a `scene` branch (resolve each participant from
  `animMap`/`critterMap`, fall back to `placeCenters`, return centroid + radius);
  `CameraDirector` gains a `'scene'` mode reusing `transit` easing but dollying to
  `dollyForRadius(...)`. Hands control back to `free` on arrival (iron rule: any pointer input
  → `free` + `onFocusBreak`). Respects `prefersReducedMotion`.
- `EventFeed.tsx` — additive inline **"▷ watch"** chip (styled like the existing grant chip)
  on notable events with a resolvable location → `onWatchEvent(event)`. No width/freeze/scroll/
  filter changes — feed stays primary.
- `App.tsx` `LiveLayout` — `onWatchEvent` resolves event → `{type:'scene',…}` → `handleFocus`.
  Click-only.
- New `world3d/WatchBeacon.tsx` — transient pulsing magenta ring at places with a recent crime
  (decays like the chaos accent); click → same scene focus. Reduced-motion → static ring.
- New `panels/SceneNav.tsx` + a `LiveLayout` keyboard hook — cycle agents (`[`/`]`) and notable
  events (`,`/`.`); reuse `handleFocus`/`onWatchEvent`; ignore keys while an input/textarea is
  focused. Rendered in the world header, not the feed.

### Phase 3 — Crowds gather (the payoff)

Goal: when a robbery/arson fires, nearby agents walk over to rubberneck — a watchable crowd
forms. **LLM-free by default, behind a flag.**

- **Drama beacon** — transient in-memory `self._beacons` in `AgentRuntime` (beside
  `_importance`; cleared in `reset_state`; **not** in snapshot → EM-155 byte-equality holds).
  `push_event` plants/refreshes a beacon at the event's `location` when
  `_event_importance ≥ gather.min_importance` (crime/conflict already weighs 3.0; routine
  economy doesn't). Decay `pull = weight * decay^(world.tick - beacon.tick)`, lazily expired by
  `ttl_ticks`/`pull_floor`. `world.tick` is the only time source → replay-safe.
- **Hook A (background, zero-call)** — in `_reflex_pick`, after survival/work guards and before
  the EM-223 plan bias, return `move_to(beacon)` (pure reorder of an already-valid reflex).
  Survival always wins; gather outranks routine errands. A gather move does **not** advance the
  agent's plan pointer.
- **Anti-stampede (three deterministic guards)** in `_gather_target`: `gather.radius` over
  place x,y (new pure `world.place_distance` via `math.hypot`) → local not townwide;
  `gather.crowd_cap` → full scenes reject latecomers; seeded `gather.join_chance`
  (`_seed_int("gather", agent.id, place, beacon.tick)`, stable across the beacon's life) →
  arrivals trickle, no per-tick flicker.
- **Hook B (opt-in, all tiers)** — add `nearby_drama` to `_background_salience` + a bounded
  "you sense a commotion at X" perception line (mirror EM-081 overheard), fired at most once
  per `(agent, beacon.seq)`. Behind `gather.salience` (**default off**) so the first ship is
  provably zero added calls; on, it's a *bounded increase* (≤1 extra background turn per agent
  per incident) — aligned with "do MORE."

---

## 7. Walk-to: keep `location` instant (rejected `in_transit`)

`location` flips instantly; the Phase-1 frontend tween + `payload.from` make convergence read
as walking. An `in_transit` state would spend N turns producing **no speaking/acting beat**
("do less" — against the north-star) and force rewrites of every co-location gate plus new
mutable timer state in the snapshot (replay risk). Instant move keeps every turn a real beat
and every gate trivial; honesty is preserved at tick granularity (an agent emits `agent_moved`
one turn and acts a later turn).

## 8. Config

`config/loader.py` (mirror `PlanningParams`): `GatherParams` →
`world.gather.{enabled, salience, min_importance, radius, crowd_cap, join_chance, ttl_ticks, decay, pull_floor}`.
- `world.gather.enabled` — master, **default OFF** (byte-identical to today when off).
- `world.gather.salience` — LLM-pull sub-toggle, **default OFF** (first ship provably zero-call).
- Event `location` + witness rosters — always-on additive, no flag.

> **Ship note:** follow the convention (default-off for byte-identity), but **set
> `gather.enabled: true` in the local `config/world.yaml`** so the running sim actually shows
> crowds gathering — otherwise the headline feature is invisible until flipped.

## 9. Call-rate impact

- Default config: **zero added LLM calls.** Gather is reflex reordering (`move_to` over
  `forage` on a turn already being taken); event `location`/witnesses are pure data; no transit
  → no lost beats.
- `gather.salience=true`: a **bounded increase** (≤1 extra background turn per agent per
  incident) — deliberately opt-in, aligned with "do MORE." No throttling introduced anywhere.

## 10. Testing

**Frontend (canvas-free, follow `characterAnim.test.ts` / `structureModel.test.ts`):**
`interactionScan.test.ts` (directed detection, newest-wins facing, decay, `resolveEventLocation`
order), `roadRouter.test.ts` (snap, ≤4 waypoints, one turn, in-block direct, lines==cityLayout),
`worldSpace.test.ts` (+`huddleOffset`, `frameScene`, `dollyForRadius`), `EventFeed.watch.test.tsx`
(chip only for notable+resolvable+handler; click fires; absent handler → no chip),
`SceneNav.test.tsx` (cycle order, ignore input-focused keys).

**Backend (follow `test_wave_d2_cadence.py` `ByAgentProvider` prompt-capture, `test_em223_planning.py`,
`test_event_log.py`/`test_w11b.py`):** new `test_gather.py` — event `location` on each action +
DB round-trip + pre-location migration; deterministic sorted witness rosters; gather reflex move
with **zero prompt growth** (the zero-call proof); anti-stampede (crowd cap, radius, failed
roll); decay/ttl; plan-pointer-not-advanced; opt-in salience fires exactly once; default-off
byte-identity (snapshot keys + prompts unchanged); snapshot restore mid-incident.

## 11. Verification (end-to-end)

1. **Unit:** `cd web && npm test` and `cd backend && pytest tests/test_gather.py tests/test_event_log.py` green.
2. **Phase 1 visual:** start sim + frontend; hard-reload (watch the mock-fallback gotcha — confirm
   a real TICK). Force a directed action (god whisper, or a steal/arson) → the two agents face
   each other, huddle, victim plays recoil + "!"; confirm street-route walking on location change.
3. **Phase 2 nav:** click a crime row's "▷ watch" → camera frames actor+target+witnesses; click a
   `WatchBeacon` → same; `[`/`]` cycle agents, `,`/`.` cycle events; any pointer drag instantly
   returns control (no auto-yank); feed never resizes; reduced-motion disables pulse/auto-rotate.
4. **Phase 3 sim:** with `gather.enabled:true`, trigger an arson and watch nearby agents converge
   (capped, not townwide); confirm no extra LLM calls while `gather.salience:false`. With
   `enabled:false`, confirm a replay is byte-identical to pre-change.

## 12. Sequencing

`worldSpace` helpers → `interactionScan` → `roadRouter` → `Villager` → `CozyWorld` wiring
(**end Phase 1, shippable**) → backend event `location` + witness roster + DB migration → `scene`
FocusTarget + scene camera + feed/beacon/SceneNav (**end Phase 2**) → gather beacon + reflex hook
+ config + opt-in salience (**end Phase 3**).

## 13. Risks & mitigations

- **Perf (many agents):** all event derivation in one O(events) `useMemo` (same as
  `chaoticAnimals`); per-frame work is allocation-free ref math; router runs only on place
  changes; reaction billboards time-boxed like speech bubbles.
- **Camera fighting the user / feed primacy:** nothing auto-fires; pointer input always breaks
  to `free`; watch chips are additive inline elements; nav lives in the world header — feed
  width/scroll/filter untouched.
- **Backend field churn:** every location path routes through `resolveEventLocation` +
  own-property-guarded payload reads → works today on actor-position fallback, upgrades silently
  (established additive-field pattern: `cadence_tier`, `owner_id`, `skin`).
- **Call-rate:** default adds zero LLM calls; `gather.salience` is opt-in and bounded; no
  throttling.

## 14. Critical files

**Frontend:** `web/src/components/world3d/{CozyWorld,Villager,worldSpace}.tsx?`,
`web/src/components/feed/EventFeed.tsx`, `web/src/App.tsx`, `web/src/types/index.ts`
+ new `world3d/interactionScan.ts`, `world3d/roadRouter.ts`, `world3d/WatchBeacon.tsx`,
`panels/SceneNav.tsx`.
**Backend:** `backend/petridish/agents/runtime.py`, `engine/world.py`,
`persistence/repository.py`, `engine/loop.py`, `config/loader.py`.

## 15. Ledger

After approval, file these phases as tracked entries via the `plan-intake` skill (assign EM-###
ids). This extends EM-095 (camera nav), EM-124 (movement), EM-081 (overhearing), EM-223 (planning).

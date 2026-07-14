# BUILD RESULTS — Multi-City Keystone (2 cities + travel)

**Branch:** `build/multi-city-expansion` · **Status:** ✅ COMPLETE pending live sign-off (DoD #7)
**Gates:** backend **2482/0**, frontend **1510/0**, `tsc -b --force` clean, QE adversarial gate **PASS**.

## What shipped

Multi-city realized via the already-built **Settlement primitive (EM-269 F2)** — turned on and
extended, NOT the parked EM-109 cities-table model. All new behavior gated on
`settlements.enabled` (default OFF in loader/embedded/dataclass ⇒ byte-identical; the live
`config/world.yaml` opts in).

- **Backend** (`world.py`/`loop.py`/`runtime.py`): AgentState +3 travel fields (serialize
  only-when-set); genesis settlement seeded at init/reset; `travel_to` reflex verb — in-transit
  agents are excluded from ALL scheduling paths (0 LLM calls while traveling), arrival migrates
  home/location/membership at the round boundary; seeded deterministic `travel_ticks`;
  per-settlement perception horizon keeps prompt size flat with N cities.
- **Frontend** (`web/src`): per-settlement ground clusters at each center, in-transit travel
  markers on inter-city routes, settlements + routes on the 2D map, travel feed cards; 3 agent
  fields + `travel_departed`/`travel_arrived` event kinds in types.

## DoD checklist

1. ✅ Settlements ON; a founded 2nd settlement round-trips through snapshot.
2. ✅ `travel_to` → off-board (0 LLM) until arrival, then migrates + rejoins.
3. ✅ Flat prompt: 5544/5622/5562 chars @ 1/2/3 cities (78-char band; place-set partitioned).
4. ✅ Each settlement renders its own cluster; in-transit agents on routes; 2D map settlements.
5. ✅ Byte-identity: settlements-OFF world byte-identical (adversarially verified — zero new surface).
6. ✅ Full suites green + QA gate PASS (`coordination/qa-report.json`, proceed: true).
7. ⏳ **Live sign-off** — the one remaining item (manual): restart `./dev` → reset → agents found a 2nd city → `travel_to` appears → watch an agent cross → confirm the feed.

## Deferred / known (non-blocking)

- **Cosmetic:** `travel_arrived` cards render neutral, not the traveler's model color (parked
  spawn-event lacks `profile_color`; feed doesn't resolve from `actor_id`). Renders fine — a
  color-consistency nit, not a masked error. Fix: enrich in `_flush_spawn_events` (mirror
  `_sync_transplant_router`, loop.py:2091) or resolve via `actor_id` in the feed card; flip the
  `EventFeed.color.qe.test.tsx` pins. QE pinned the current behavior so the fix is a deliberate test change.
- **Viz polish:** travel-marker progress is approximated (backend emits arrival tick + travel_ticks
  in the event, but the agent state carries only `transit_arrival_tick`, so the marker eases over a
  nominal window). Add a depart-tick/travel-ticks to AgentState for exact interpolation if wanted.

## Out of scope (later slices — recorded, not built)

EM-112 parallel-worlds runner · EM-116 trade caravans · EM-117 diplomacy/city-city scope ·
EM-119 model-family arena · EM-121 multi-city camera polish · roster scale-up beyond ~10 ·
per-settlement full CityScape grid re-center (used ground-pad minimum bar this slice).

## Handoff

- Live sign-off is yours (needs a `./dev` restart to load `settlements.enabled` + a reset to seed
  the genesis settlement). Back up `data/run.sqlite` first if you want to keep the current run.
- Ledger update (EM-109/110 → in-progress/done via `plan-intake`) pending the live sign-off.
- Not merged to main — stays on `build/multi-city-expansion` until you ask.

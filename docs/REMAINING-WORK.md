# PetriDishOfMadness — Remaining Work (tactical ledger)

Every **open / in-progress** item, ID'd and prioritized. This is the canonical
"what exactly needs doing?" list — kept lean on purpose.

> **Completed work lives in [`COMPLETED-WORK.md`](COMPLETED-WORK.md)** (tactical
> archive — full per-item detail of everything shipped). The strategic "what
> shipped & when" digest is the **Closure log** in [`BUILD-PLAN.md`](../BUILD-PLAN.md).
> Current status + ownership map: [`START-HERE.md`](../START-HERE.md). When an item
> reaches `done`, sweep its row out to `COMPLETED-WORK.md` (see the `living-plan`
> / `plan-intake` skills — the completion sweep keeps this file scannable).

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W14` (see `BUILD-PLAN.md`). W0–W4 shipped (v1); W5–W8 shipped (v2); W9–W11 shipped (v2.1 audit-driven); W12–W14 are the v3 Village→Civilization plan.
- **Area** — `infra` · `contracts` · `backend` · `providers` · `persistence` · `frontend` · `qe`.
- **Source** — where it came from. New items from reports enter via `plan-intake`.
- **Status** — `open` · `in-progress` · `blocked` · `done`.
- **Owner** — agent role or person; `—` if unassigned.


| ID | Pri | Wave | Area | Source | Summary | Status | Owner |
|----|-----|------|------|--------|---------|--------|-------|
| EM-109 | P0 | W12 | persistence | research-v3 | Multi-city data model: `cities`/`city_links`/`agent_location` tables + a 2nd settlement rendered on the 2D map; ONE tick loop + per-city context scoping so prompt size stays flat (free-scale). Keystone unblocking travel/trade/diplomacy/parallel-worlds | open | — |
| EM-110 | P0 | W12 | backend | research-v3 | Reflex `travel_to(city)` → `in_transit_to`/`transit_arrival_tick` (agent off-board, zero LLM calls until `agent_arrived`); migration re-points credits/skills/memories(top-K)/relationship edges to the new `city_id`. Deps EM-109 | open | — |
| EM-112 | P0 | W12 | backend | research-v3 | Parallel-worlds runner: `runs.model_family` + "seed all agents from family X" casting + **sequential** tournament (snapshot→next, never concurrent — protects FreeLLMAPI free tiers) + run-browser entry. Deps EM-101 ✅, EM-092 ✅, EM-086 ✅ | open | — |
| EM-116 | P1 | W13 | backend | research-v3 | Inter-city trade caravans: reflex `send_caravan(to_city, goods, credits)` → `trade_dispatched`, reflex settlement on arrival (`trade_settled`); optional lightweight `merchant` actor_type on cheaper/less-frequent calls. Deps EM-109, EM-110 | open | — |
| EM-117 | P1 | W13 | backend | research-v3 | Diplomacy via governance: city-scoped treaties/alliances/rivalries ratified by each city's ~70% vote threshold; relationship edges gain `scope` (agent-agent vs city-city); bundles shipped governance texture (EM-079/087/100/103). Deps EM-109, EM-113 | open | — |
| EM-119 | P1 | W13 | frontend | research-v3 | Model-Family Arena: side-by-side cross-run AWI sparklines per family + civilization-outcome cards (population/laws/buildings/crimes/credits) on the existing uPlot/Observable Plot stack — the Gemini-vs-Claude crime/culture contrast demo. Deps EM-112, EM-086 ✅ | open | — |
| EM-121 | P2 | W13 | frontend | research-v3 | Multi-city camera (rescoped): zoom-to-city / follow-agent-across-cities + reset-view for the multi-settlement view. Base orbit/pan/zoom-to-place (EM-095 ✅) + label declutter (EM-102 ✅) already shipped W11a — this is the multi-city delta only | open | — |
| EM-127 | P3 | W17 | frontend | research-v3 | Art phase 5 (re-waved W14→W17 at v4 intake — rides Wave D3 "life"): day/night + seasons + particles (chimney smoke, fireflies) + sparing `<Bloom>`/`<Vignette>` + filmic tone mapping (`antialias:false`, post handles AA). **PR #46 (2026-06-24): the particle beat shipped** — golden-hour dust motes (deterministic field, reduced-motion-safe, off the replay surface). Day/night + seasons + `<Bloom>`/`<Vignette>` + filmic tone-mapping DEFERRED for visual sign-off (they reshape the signature golden-hour look). Deps EM-111 ✅ | in-progress | PR #46 |
| EM-128 | P3 | W14 | frontend | research-v3 | Population-dynamics + culture-drift AWI metrics compared across model families (population/laws/culture charts per family). Deps EM-112, EM-126 | open | — |
| EM-169 | P2 | W17 | frontend | research-v4 §7 | Ambient vehicles: Car Kit traffic on the generated road network (deterministic paths, instanced), parked cars from the prop scatter. **PR #44 (2026-06-24):** deterministic `trafficLayout` fleet (interior streets only, seeded → replay-safe EM-155) + `Traffic.tsx` clock-driven sweep; non-interactive (EM-157) + reduced-motion-safe. Deps EM-152, EM-153 | in-progress | PR #44 |
| EM-176 | P2 | W17 | frontend | user 2026-06-11 | Bring vehicles back when they're playable: parked-car emission disabled at the generator (`CARS_ENABLED=false`, cityLayout) — static cars read as a distraction before they have a purpose. Keys/registry/GLBs/licenses all kept; EM-169's ambient traffic on the road graph is the re-entry point (flip the flag + moving cars together) **— PR #44 (2026-06-24): `CARS_ENABLED` flipped on together with the ambient traffic.** | in-progress | PR #44 |
| EM-214 | P3 | W20 | backend+frontend | Wave I · I5 (stretch) | **Voices / audio** — agent spoken lines via the browser **Web Speech API** ($0, client-side, no network) for v1; free SFX/music gen is NOT mature (slow, GPU-bound) → DEFERRED. Optional cloud TTS (Google free tier) only if server-side audio files are ever wanted. **Deferred at wave-I 2026-06-19** (user-chosen: full arc I1→I4, audio is a stretch with no agent demand yet — re-enter when voices are wanted). | open | defer wave-I |
| EM-243 | P1 | W24 | backend | layout-spec 2026-06-27 | **S2 — `build_road` + local perception:** cheap individual axis-aligned road extension paid in energy+turn; district-scoped `nearby_layout` prompt block (diet-safe); `road_built` events (replay-safe); emergent roads→lots→buildings loop. Deps EM-239. Spec `…s2-build-verbs` | open | — |
| EM-244 | P1 | W24 | backend+frontend | layout-spec 2026-06-27 | **S3a — vote-gated demolish + car-policy:** town-hall `propose_demolish` + `propose_car_policy` (street/district/city, pedestrian↔cars) at ~70%; ban-cars/all-sidewalks as a render flag (traffic EM-169 / parked cars EM-176 honor per-edge policy); axis-aligned. Deps EM-239, EM-243. Spec `…s3-governance-master-plans` §S3a | open | — |
| EM-245 | P2 | W25 | backend+frontend | layout-spec 2026-06-27 | **S3b — master plans (morph):** parametric pentagon/radial/ring/grid generators ratified by ~70% vote; the city **morphs** toward target over ticks (deterministic diff+schedule), buildings preserved-or-relocated; needs arbitrary-angle rendering. Deps EM-239, EM-243, EM-247. Spec `…s3-governance-master-plans` §S3b | open | — |
| EM-246 | P2 | W24 | backend+frontend | layout-spec 2026-06-27 | **S4 — city templates / "city profile":** run-start `city:` block in `config/world.yaml` (template+params+policy) seeding the initial graph (a template = a master plan seeded at start; reuses EM-245 generators); grid/greenfield/village now, geometric presets ride EM-247; feeds parallel-worlds EM-112 / arena EM-119. Deps EM-239. Spec `…s4-templates` | open | — |
| EM-247 | P1 | W25 | frontend | layout-spec 2026-06-27 | **S5a — procedural road meshing:** runtime extrusion of road ribbons + procedural intersection/roundabout/plaza geometry from the graph (any angle), raw-instanced toon atlas + chunked culling + LOD (deep-research-v4 §4); supersedes the 5 road tiles behind a visual sign-off. Gates EM-245 + geometric S4 presets. Deps EM-239. Spec `…s5-assets-meshing` §S5a | open | — |

_Next free ID: EM-249. (EM-240 taken by the crime engine; EM-241/242 reserved for the EM-240 persona content/management-UI follow-ons.)_

## Active-wave notes

- **EM-227–238 (Wave M — Cooperation Economy)** entered 2026-06-24 via `plan-intake` from a
  gap analysis of `docs/research/deep-research-v1.md` (the *original* Emergence-World deep
  research) against shipped capabilities. They open **W23**. The framing: we've built a strong
  observation/world-dressing layer + survival/governance loops, but EW's **cooperation economy**
  (skills → teach/trade → specialization → peer-judged reward; **EM-227–232**) and its
  **multi-drive psychology** (knowledge + influence needs; **EM-229**) are almost entirely
  absent — and those are the mechanisms that made identical agents diverge into a society.
  Ranked Tier 1 (P1, EM-227–230) → Tier 3 (P3, EM-235–238). **Sequencing:** EM-227 (skills) is
  the keystone — EM-228 (teach), EM-230 (trade), EM-231 (co-op-gated tools) all dep on it; do it
  first. **Weapons note (user Q):** EW had *no weapons-as-objects* — violence is tool calls, and
  our `attack`/`insult`/`steal`/`arson` already match that surface, so nothing weapon-shaped was
  filed; **EM-237** only adds the two missing harm *verbs* (intimidate/deceive). Already-tracked
  EW gaps deliberately **not** re-filed: voice/TTS (**EM-214**), weather/day-night (**EM-127**).
  **Reconcile 2026-06-27 (post EM-240):** the **EM-240 Crime & Justice engine** (PR #50) shipped
  the **EM-238** police/justice institution — flipped `done` (investigate/accuse/detain +
  town-hall trial + jail + notoriety), a richer take that went *beyond* EW's soft-enforcement-only
  framing by adding hard enforcement. **EM-237** stays open but is now a small add atop EM-240's
  crime-verb dispatch. Net open Wave M scope: **EM-227–237** (11 items); EM-238 done.

- **EM-239 + EM-243–248 (Wave N — Agent-Controlled City Layout)** entered 2026-06-27 via
  `plan-intake` from the brainstormed design suite
  (`docs/superpowers/specs/2026-06-27-agent-city-layout-*.md`). The initiative replaces the
  frozen 5×5-grid city (a pure fn of places/seed in `cityLayout.ts`) with an **agent-controlled,
  emergent road-graph layout** + a 3-D asset expansion — the concrete form of the
  *deepen-the-first-city-before-a-second* direction (orthogonal to multi-city EM-109/110).
  **Three locked pillars:** authorship = agents, emergently (backend event-sourced state + verbs);
  representation = a free-form road graph (arbitrary topology — pentagon/radial/roundabouts);
  decision = hybrid (build freely, vote for destructive/structural/city-wide changes — reuses
  EM-079/087/100/103, EM-183). **Opens W24** (emergent core: **EM-239** spine keystone → **EM-243**
  `build_road` → **EM-244** demolish/car-policy votes → **EM-246** templates → **EM-248** asset
  variety, standalone) **and W25** (geometry: **EM-247** procedural road meshing → **EM-245** master
  plans/morph). **Sequencing:** EM-239 is the keystone (P0 — everything deps on it) — **✅ shipped
  2026-06-27, PR #58** (S1 spine: backend `CityGraph` + render-from-graph, byte-identical EM-155);
  EM-243–248 now unblocked. **EM-248** (S5b asset/pool variety) **✅ shipped 2026-06-27, PR #59**
  (PLACE_POOLS + industrial/civic pools + 29 CC0 GLBs; generic 23→32; EM-155-safe); EM-247 gates
  EM-245 + the geometric EM-246 presets.

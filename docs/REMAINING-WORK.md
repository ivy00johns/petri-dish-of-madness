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
| EM-249 | P2 | W26 | backend | society plan 2026-06-29 | **`RelationshipState.scope`** (default `"local"`, serialize-when-non-default) — the cheap multi-city down-payment so relationship/faith/war edges stay forward-compatible; nothing reshapes when cities land. *Lands early the same `scope` field EM-117 later consumes for city-city.* | open | — |
| EM-250 | P2 | W26 | backend | society plan 2026-06-29 | **Meme primitive + shared seams (Wave O keystone — do NOT split):** `Meme` dataclass (`rumor\|idea\|ideology\|image`, open `kind` so Religion adds `faith`) + `_plant_belief`/`_attach_meme`/`_distort_text` + `_recompute_groups` (extracted from `recompute_factions` so culture-camps/congregations share one clusterer) + `CommunicationParams` + determinism golden. Build-once substrate the whole portfolio rides | open | — |
| EM-251 | P2 | W26 | backend | society plan 2026-06-29 | Transmission verbs (reflex): `spread_rumor` (clones `deceive` belief-plant, trust-**positive**, no crime) + `send_letter`/`mailbox` — the first non-co-located directed channel, deterministic next-turn delivery (snapshot-safe like `pending_skill_requests`). Deps EM-250 | open | — |
| EM-252 | P2 | W26 | backend | society plan 2026-06-29 | `diffuse_culture()` round-boundary subsystem: passive seeded diffusion (one co-located hop/carrier, `_seed_int`-gated) + `_distort_text` per-hop mutation + half-life/decay prune (zero-carrier meme dies). Deps EM-250 | open | — |
| EM-253 | P2 | W26 | backend | society plan 2026-06-29 | Culture lifecycle: `create_meme`/`adopt_meme`, **visual memes** (extend `create_image` to auto-register an image-meme + drifted repaint on adopt, free Pollinations lane), virality scoring, culture-camp clustering via `_recompute_groups`. Deps EM-250, EM-252 | open | — |
| EM-254 | P2 | W26 | backend | society plan 2026-06-29 | Culture governance: `canonize_meme` (70% lane → sets `town_motif_ref`, the Religion seam) + `ban_gossip` (agreement-gate, clones `ban_stealing`). Deps EM-253 | open | — |
| EM-255 | P2 | W26 | frontend | society plan 2026-06-29 | Culture frontend: `Meme`/`CultureCamp` types, **Meme Lineage panel** (image family tree via `parent_id`/`generation` — the marquee visual-meme demo), culture-camp chips (reuse faction chrome), dominant-motif banner. Deps EM-250–254 | open | — |
| EM-256 | P1 | W26 | backend | society plan 2026-06-29 | **War data model + grievance subsystem:** `WarState` + `world.wars`/`grievances` (directional group-scope notoriety analog), `_register_war_act` (group-scope `_register_crime`, fed by ordinary cross-faction crime), `advance_war` decay, faction-snapshot writer fix (emit `war_band`/`treasury_pledged`), determinism golden. Deps EM-120 ✅, EM-240 ✅ | open | — |
| EM-257 | P1 | W26 | backend | society plan 2026-06-29 | War governance lane: `declare_war`/`peace_treaty` effects (clone the `trial` effect) on a **faction-scoped 70%** electorate (isolated `_evaluate_rule` branch substituting the faction roster for `living`), reparations (clone `trial_fine` split) + loser-leader set to the unused `exiled` `crime_status`. Deps EM-256 | open | — |
| EM-258 | P1 | W26 | backend | society plan 2026-06-29 | **Combat primitive (the one genuinely new mechanic):** reflex `action_clash` seeded deterministic stat contest (energy→existing `check_death` war-death, morale/retreat, `floor()` float-drift guard) + `muster`/war-band bonding (clones `recruit`/`accept_contract`). Deps EM-256, EM-257 | open | — |
| EM-259 | P1 | W26 | backend+frontend | society plan 2026-06-29 | War `siege` (routes through existing `_damage_building`) + exhaustion auto-resolution in `advance_war` + frontend (`War` type, red `conflict`-lane war feed, ⚔ belligerent faction badges). Deps EM-258 | open | — |
| EM-260 | P2 | W26 | backend | society plan 2026-06-29 | Religion plumbing: `Faith` object in `self.faiths` (seeded **invented** name/deity/tenets — no real religions), `AgentState.faith_id`/`devotion`, `co_religionist` relationship type, determinism golden. Deps EM-250 | open | — |
| EM-261 | P2 | W26 | backend | society plan 2026-06-29 | Religion founding: reflex `found_faith` + `consecrate_faith` (70% lane) + **temple-as-seat** (attach a `function` devotion buff to the catalogued-but-empty `temple` kind via `_WORK_BUFF_KINDS`, `commemorates` the faith). Deps EM-260, EM-254 | open | — |
| EM-262 | P2 | W26 | backend | society plan 2026-06-29 | Religion emergence: reflex `proselytize` (calls EM-250 `_plant_belief`, trust-positive, +`co_religionist`, raises devotion, seeded resistance) + `worship` ritual (clones `action_work` buff-at-place) + `recompute_congregations` + deterministic schism forking. Deps EM-260, EM-253 | open | — |
| EM-263 | P2 | W26 | backend+frontend | society plan 2026-06-29 | Religion conflict surface + frontend: `excommunicate`, `declare_hostility` (war casus-belli hook → `Faith.hostile_to`, consumed by EM-256 grievance seam), faith badges + congregation hulls (reuse faction hulls). Deps EM-262, EM-256 | open | — |
| EM-267 | P2 | standalone | backend+frontend | ideologies design 2026-06-30 | **Agent-invented ideologies (the "government bridge"):** `Ideology` dataclass + `found_ideology`/`adopt_ideology` reflex verbs + a `ratify_ideology` 0.7 governance effect + perception injection + deterministic camps, behind `ideology.enabled` (default off). Names/economics **invented, never real-world-labelled**. Rides shipped governance (EM-236/240); orthogonal to Wave O. | open | — |
| EM-268 | P1 | W28 | backend+frontend | free-placement 2026-07-02 | **F1 — Unbind + free placement core (redo keystone):** retire the graph-lots placement path; replace fixed-grid/face placement with deterministic **free-coordinate organic placement** (position → backend event-sourced state; frontend renders) anchored to the city center. Restores build-anywhere. **Supersedes EM-264/265/266 building-placement.** Byte-identical-gated (EM-155). | open | — |
| EM-269 | P1 | W28 | backend+frontend | free-placement 2026-07-02 | **F2 — Settlement primitive + founding:** `Settlement` (name+center+loose membership) backend state + `found_settlement` reflex + district-scoped settlement perception; placement anchors to the agent's settlement. `len(settlements)>1` = emergent multi-city. *Relates to EM-109 (heavier multi-city data model).* Deps EM-268 | open | — |
| EM-270 | P2 | W28 | backend+frontend | free-placement 2026-07-02 | **F3 — Deliberate placement target:** `build` gains an optional `target` (direction / named place / settlement / "found here") + compact map perception, so agents place deliberately (district roundabout, far-corner town) within the prompt-diet. Deps EM-269 | open | — |
| EM-271 | P2 | W28 | frontend | free-placement 2026-07-02 | **F4 — Roads as pure decoration (formalize):** roads gate nothing (keep the full road engine, sever the building↔road-face tie); a road to another settlement reads as connection visually. Mostly falls out of F1. Deps EM-268 | open | — |
| EM-272 | P1 | W29 | backend | offline review 2026-07-01 | **`teach_skill` +1 no-op** (`world.py:2656`): reports success with **zero** levels transferred when the teacher is exactly +1 above the student → paid no-op lessons + unbounded `skill_taught` Victory-Arch contribution farming. | open | — |
| EM-273 | P1 | W29 | frontend | offline review 2026-07-01 | **Phantom streets + off-road cars** (`cityLayout.ts:403`): streets/ambient-traffic/street-labels derive from graph **node** coords (not edges) and cars sweep the full ±span → cars drive through roadless terrain + phantom named streets after demolish/thin/morph. | open | — |
| EM-274 | P1 | W29 | frontend | offline review 2026-07-01 | **`scopedSlice` cache leak** (`inspector/selectors.ts:128`): the EM-195 cache has no eviction — retains one filtered event-array (+ a sorted copy) per visited scrub tick, unbounded for the events-array lifetime. | open | — |
| EM-275 | P1 | W29 | backend | offline review 2026-07-01 | **Crime-decay fork divergence** (`loop.py:1851`): EM-240 `advance_crime` gates on loop-transient `_last_building_round` (never restored from snapshot) → every fork/resume fires one extra notoriety-decay/wanted-clear pass — **EM-155 divergence**. | open | — |
| EM-276 | P2 | W29 | backend | offline review 2026-07-01 | **Trial jails a corpse** (`world.py:4237`): `_on_rule_activated` effect=='trial' never checks the defendant is alive → a defendant who dies before the vote crosses threshold is jailed, credits confiscated, `crime_status='jailed'` in every snapshot forever. | open | — |
| EM-277 | P2 | W29 | backend | offline review 2026-07-01 | **Free heat-cooling via launder** (`world.py:2529`): `action_launder` truncates the fee with `int()` → amount ≤3 at default cut 0.3 charges 0 credits yet still cuts notoriety by the full 8 and can clear a wanted flag → free repeatable. | open | — |
| EM-278 | P2 | W29 | backend | offline review 2026-07-01 | **Master-plan clobber** (`world.py:4411`): `adopt_master_plan` activation sets `self.master_plan` unconditionally (one-active invariant only checked at propose time) → a vote passing after a `god_adopt_master_plan` morph started silently overwrites the in-progress plan. | open | — |
| EM-279 | P2 | W29 | backend | offline review 2026-07-01 | **Memory consolidation unreachable** (`world.py:2205`): EM-233 belief writers FIFO-cap at exactly 20 while `consolidate_memory` fires only when `len(beliefs) > 20` → 20>20 never true; the sleep-sweep/digest path never runs at defaults. | open | — |
| EM-280 | P2 | W29 | backend | offline review 2026-07-01 | **Layout-governance effects undiscoverable** (`runtime.py:2673`): demolish_road/set_car_policy/adopt_master_plan (live) + set_zone_rule (flagged) are accepted by the `propose_rule` gate but on no prompt surface → discoverable only by burning a turn on a rejection. | open | — |
| EM-281 | P2 | W29 | backend | offline review 2026-07-01 | **Truncation retry can't grow** (`runtime.py:4646`): on an EM-135 boosted lane the retry uses the identical budget attempt 1 just truncated at (`_retry_max_tokens(base)` == `max(base*4,2048)`) → the retry can never exceed the cap that just failed. | open | — |
| EM-282 | P2 | W29 | frontend | offline review 2026-07-01 | **Graph-lots grid fallback missing** (`cityLayout.ts:967`): when `planarFaces` returns [] (sanctioned tie backstop) or no bounded face, `computeCityPlan` ships a plan with **zero** blocks/blockLots/emptyLots instead of the grid plat. | open | — |
| EM-283 | P2 | W29 | frontend | offline review 2026-07-01 | **planarFaces ignores crossings** (`cityFaces.ts:357`): sanitizes coincident nodes/node-on-edge but NOT segment×segment crossings (guaranteed mid-morph, adds-before-removes) → can drop an enclosed block or emit self-intersecting faces whose lots sit on roads. | open | — |
| EM-284 | P2 | W29 | frontend | offline review 2026-07-01 | **Car-ban no-op post-morph** (`cityLayout.ts:483`): `pedestrianStreetIds` silently skips non-axis-aligned edges → a ratified city-wide 'pedestrian' car ban (EM-244 headline) has no effect on the fleet after a pentagon/radial/ring morph. | open | — |
| EM-285 | P2 | W29 | backend | offline review 2026-07-01 | **Constitution prompt spam** (`runtime.py:3419`): the EM-236 constitution block rides every agent prompt with no article-count cap and no duplicate-text guard on `add` → ratified-article spam grows every prompt unboundedly (token waste vs the max-call-rate north star). | open | — |
| EM-286 | P2 | W29 | frontend | offline review 2026-07-01 | **Traffic memo identity miss** (`Traffic.tsx:47`): the `useMemo` deps include the raw `graph` object (fresh every world_state message) → the "deterministic fleet" memo misses on 100% of updates. *Bug in EM-169; same identity-vs-content class fixed 3× in siblings.* | open | — |
| EM-287 | P2 | W29 | providers | offline review 2026-07-01 | **Unvalidated image writes** (`imagegen/provider.py:71`): the image lane buffers arbitrary third-party responses with **no size cap and no PNG validation** before writing to `data/assets/images` and serving as `.png`. | open | — |
| EM-288 | P2 | W29 | backend | offline review 2026-07-01 | **Partial-xp fork divergence** (`world.py:6460`): `grant_skill_xp`'s `_skill_xp` partial ledger is deliberately not serialized → save/fork mid-run resets accrued xp; the resumed run levels agents later than the continuous run — **EM-155 fork/resume divergence**. *(PLAUSIBLE — lower confidence than the CONFIRMED set.)* | open | — |
| EM-289 | P3 | W29 | backend | offline review 2026-07-01 | **co_build under-scored** (`world.py:3145`): the `action_co_build` completion path skips `record_contribution(agent,'project_built')` (the `build_step` path at `:5045` records it) → agents finishing via the co-op verb are under-scored in the EM-232 Victory Arch economy. | open | — |
| EM-290 | P3 | W29 | backend | offline review 2026-07-01 | **Funded-project ghost menu** (`runtime.py:3561`): residual PR-#57 gap — the "ACTIVE PROJECTS YOU COULD CONTRIBUTE TO" context block still lists fully-funded/under-construction projects even when the `contribute_funds` menu line is gated off → invites the rejected action #57 targeted. | open | — |
| EM-291 | P3 | W29 | frontend | offline review 2026-07-01 | **RoadMesh GPU leak** (`RoadMesh.tsx:148`): `useRoundaboutBucket` allocates a new `THREE.RingGeometry` every graph rebuild and never disposes the previous (passed via args, outside R3F auto-dispose) → GPU geometry leak. | open | — |
| EM-292 | P3 | W29 | frontend | offline review 2026-07-01 | **cssVar in rAF** (`map/WorldMap.tsx:472`): the token migration put `cssVar()` (a fresh `getComputedStyle(document.documentElement)`) inside the per-agent rAF draw path → hundreds-to-thousands of computed-style reads/sec while agents animate. | open | — |
| EM-293 | P3 | W29 | frontend | offline review 2026-07-01 | **Inspector tabs a11y** (`InspectorLayout.tsx:575`): the EM-204 tab bar uses ARIA tab roles (tablist/tab/tabpanel) with none of the required wiring — no arrow-key roving tabindex, no tab ids, no `aria-controls`/`aria-labelledby`. | open | — |
| EM-294 | P3 | W29 | frontend | offline review 2026-07-01 | **Diary blank on missing diarist** (`DiaryView.tsx:139`): the EM-215 per-agent filter has no guard for a selected diarist that later disappears from grouped history → silently blank reading room. | open | — |
| EM-295 | P3 | W29 | backend | offline review 2026-07-01 | **Uncached planar_faces** (`runtime.py:1024`): with `GRAPH_ZONES_ENABLED` on, `planar_faces()` is recomputed from scratch (O(edges×nodes)) once per agent-turn perception + twice more per zone action (gate `:2123`, `action_propose_rule` `:3992`), no cache keyed to graph mutations. | open | — |
| EM-296 | P3 | W29 | providers | offline review 2026-07-01 | **SSRF in image fetch** (`imagegen/provider.py:145`): the `url` field in the FreeLLMAPI images response is fetched blindly (any scheme/host, redirects followed) → an upstream image provider can aim the backend at internal endpoints. | open | — |

_Next free ID: EM-297. (EM-240 = crime engine; EM-241/242 reserved for EM-240 follow-ons; EM-249–263 = Wave O society; EM-264–266 = Wave P building layout — **shipped then superseded**, archived in COMPLETED-WORK; EM-267 = agent-invented ideologies; EM-268–271 = free-placement + settlements redo (supersedes Wave P placement); EM-272–296 = **W29 offline-review remediation** — the PRs #49–69 deep review 2026-07-01 (9 of its 33 distinct findings already shipped in #70).)_

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
  EM-243–248 now unblocked. **✅ INITIATIVE COMPLETE (2026-06-28)** — all 7 sub-projects shipped:
  EM-239 (S1 spine, PR #58), EM-243 (S2 `build_road`, PR #60), EM-244 (S3a demolish/car-policy,
  PR #61), EM-246 (S4 templates, PR #62), EM-247 (S5a procedural meshing, PR #63), EM-245 (S3b
  master-plan morph, PR #64), EM-248 (S5b assets, PR #59). Agents now author the city end-to-end:
  build roads, vote to demolish / ban cars, vote a pentagon/radial topology and watch it morph,
  start a run from a template — all deterministic + EM-155-safe. **One deferred user gate:** the
  EM-247 geometric **visual sign-off** — flip `ROAD_MESH_ENABLED` on and confirm a pentagon renders
  at 60fps before retiring the tile path (browser automation was unavailable in the build session).
  Recorded refinements (non-blocking): surface the layout-governance effects in the agent menu;
  the S5a visual-polish iteration (atlas/lane-markings/LOD/culling); `size`-scaled templates.

- **EM-249–263 (Wave O — Emergent Society Systems)** entered 2026-06-29 via `plan-intake` from the
  approved 4-feature portfolio plan (`/Users/johns/.claude/plans/goofy-roaming-clarke.md`), itself
  built from a 3-agent codebase audit + a 3-architect design fan-out. Fills the **white space** an
  audit found missing *and* absent from FUTURE.md: **religion/faith**, **culture/memes as a
  propagating object**, **organized violence (war)**, and **gossip/rumor + async letters**. Framed
  as the next *deepen-the-first-city-before-a-second* track (orthogonal to multi-city EM-109/110) —
  **single-city now but multi-city-ready** (every new object carries an additive `scope`/`city_id`
  seam; EM-249 is the down-payment). **Two engines + shared substrate:** (a) **Belief & Culture** —
  the `Meme` primitive (EM-250 keystone, build-once) → transmission (EM-251) + diffusion (EM-252) +
  culture/visual-memes (EM-253) + governance (EM-254) + frontend (EM-255); (b) **Religion** extends
  the `Meme` primitive — plumbing (EM-260) → founding/temple-seat (EM-261) → proselytize/worship/
  schism (EM-262) → conflict+frontend (EM-263); (c) **War** promotes the read-only faction graph to
  belligerent actors — data/grievance (EM-256) → governance (EM-257) → the one new primitive,
  seeded combat (EM-258) → siege/auto-resolution/frontend (EM-259). **Sequencing:** EM-249 +
  **EM-250 (keystone — do NOT split, lands 4 shared seams incl. `_recompute_groups` + `_plant_belief`)**
  unblock everything; then three tracks parallelize — **War (EM-256→259) is P1 and depends only on
  the shipped faction + EM-240 substrate** (ship-first, highest drama-per-effort); Culture
  (EM-251→255) and Religion (EM-260→263, gated on EM-250/253/254) follow. **Determinism keystone
  holds throughout** (seeded `_seed_int`, serialize-when-non-default, em161 golden byte-identical).
  **Frozen-constraint note:** war honors *no weapons-as-objects* — death rides the existing
  `energy`→`check_death` model, siege rides `_damage_building`, war-bands are agent IDs.
  **Contended seam:** all three insert into `_apply_round_start` — canonical order
  `recompute_factions → diffuse_culture → recompute_congregations → advance_war → age_agents`, to be
  enforced as a tested invariant. **Dedup flags:** EM-249 lands early the `scope` field EM-117
  later consumes (city-city diplomacy); EM-250–255 are the culture *mechanism* that the open EM-128
  culture-drift *chart* would finally measure.

- **EM-264–266 (Wave P — Agent-Controlled Building Layout)** entered 2026-06-29 via `plan-intake`
  from the brainstormed design suite `docs/superpowers/specs/2026-06-29-agent-building-layout-*.md`.
  The **direct continuation of the merged road initiative** (EM-239/247): roads are now an emergent,
  any-angle, agent-authored graph, but **buildings still sit on the frozen 5×5 grid** —
  `computeCityPlan` Pass 1 iterates fixed blocks independent of the road graph, so a pentagon road
  plan renders with grid buildings on top ("you can still see the underlying city layout"). The fix
  makes buildings **follow the road graph via its planar faces** — but **reframed for chaos/
  emergence** (user steer 2026-06-29: *"They need freedom to make mistakes as well as part of the
  madness. They can make rules for areas, and agents can choice to build there if they want. this is
  a chaos experiment, need flex."*). So the graph derives buildable **ZONES** (loose regions +
  optional rules), **not** tidy lot assignments; geometric precision is explicitly **not** the crux
  (only crashes / silently-dropped regions fail); the pentagon inner core is just another zone (choke
  it = a finding, not a bug). **Three slices:** **EM-264** (SA, P1, frontend keystone — `cityFaces.ts`
  planar faces → zones → messy placement behind `GRAPH_LOTS_ENABLED`, default-off byte-identical;
  the *visible* win + the data shape) → **EM-265** (SB, P2 — vote-gated `propose_zone_rule` on the
  EM-244/245 governance machinery; rules are advisory) → **EM-266** (SC, P2 — agents target zones and
  may honor/ignore/**break** rules; building stays free; the emergent payoff). The flag + default-off
  byte-identical path (EM-155) + the content-keyed `citySignature` live-render discipline (the
  thrice-shipped EM-243/244/247 bug) carry through all three. **Sequencing:** `SA → SB → SC`; SA is
  frontend-only and shippable alone. Orthogonal to Wave O (society systems) and multi-city
  (EM-109/110) — this is the *deepen-the-first-city* track applied to urban form.

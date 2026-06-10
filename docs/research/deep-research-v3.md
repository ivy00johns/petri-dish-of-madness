# Petri Dish of Madness — v3 "Village → Civilization" Design Doc & PR Roadmap

## TL;DR
- Ship v3 **breadth-first**: a thin visible slice of all six headline features (multi-city, parallel model-family worlds, city growth, deeper relationships, lightweight children, and the first cozy-art win) in the first ~7 PRs, then layer depth. The geographic backbone is a new `cities` table + a `region` world model; the comparison backbone is your existing event-log + snapshot + fork (EM-101) + run-browser/AWI (EM-086); the art backbone is CC0 glTF kits (KayKit, Quaternius, Kenney) piped through gltfjsx into instanced R3F components.
- Everything must stay **free-scale**: travel, trade, and child "tending" resolve as reflex (no-LLM) actions; secondary entities (children, caravans, animals) act less often and on cheaper routed models; prompt size is held flat by per-city context scoping and a hard population cap. The dominant risk is LLM-call/token blowup as cities × agents × children grow — every feature below is designed to add entities without adding proportional LLM calls.
- The single best immediate PR is **EM-105: the multi-city data model + a second settlement on the map** — it unblocks migration, trade, diplomacy, and parallel-world comparison, and demos instantly ("there are now two towns and you can see both").

## Key Findings

**The comparables validate this exact direction.** Emergence AI's *Emergence World* — published May 14, 2026 by Deepak Akkil, Ravi Kokku, Aditya Vempaty and Satya Nitta (a New York firm founded by ex-IBM Research veterans), in the blog post "EMERGENCE WORLD: A Laboratory for Evaluating Long-horizon Agent Autonomy" — ran, in the project's own words on its GitHub README, "five parallel worlds for 15 days each, with 10 agents per world. The only variable across worlds was the foundation model powering the agents" (Claude Sonnet 4.6, Gemini 3 Flash, Grok 4.1 Fast, GPT-5-mini, and a Mixed world). The world was a "~240×240 unit grid synchronized to New York City real-time with live weather data… 38+ landmarks including residences, commercial shops, parks, a governance Town Hall, a police station, and a Victory Arch," with energy survival, 120+ tools, and constitutional governance where laws required 70% approval to pass. This is essentially the parallel-worlds-one-model design PDoM wants for feature 2, and a near-exact match to PDoM's existing mechanics. Notably, the Gemini 3 Flash world "accumulated 683 crimes and was still rising at the cutoff" — the most of any single-model world — yet also produced the most conceptually rich culture (the researchers' "creativity-stability tension"), while Claude Sonnet 4.6 was "the only condition to maintain both order and population persistence" with zero crimes through day 16. Expect, and surface, this instability as texture.

Stanford's *Generative Agents*/Smallville (Park et al., arXiv:2304.03442) established the memory-stream + reflection + replay-with-memory inspector patterns PDoM already echoes; reflections there fire "when the sum of the importance scores for the latest events… exceeds a threshold (150 in our implementation). In practice, our agents reflected roughly two or three times a day" — the exact mechanism for EM-080. *Project Sid / PIANO* (Altera.AL, arXiv:2411.00114) demonstrates "how 10–1000+ AI agents" form specialized roles (shown with "30 PIANO agents who started out identical"), govern themselves (a 25-agent taxation/voting study), and propagate culture/religion (analyzed on "a single 500-agent simulation") across multiple interacting societies in Minecraft — and crucially that "specializing into diverse professions emerged only with social awareness; limiting agents' social perception led to uniform, repetitive actions without distinct roles." Multi-society interaction is the natural scaling axis, and social-relationship richness (feature 4) is the prerequisite for emergent specialization. Recent 2025–2026 work — LLM Economist (Karten et al., arXiv:2507.15815, July 2025; up to ~100 interacting agents in-paper, "3–1000+ agents" in the repo), the Genomebook preprint (Mendelian inheritance of behavioural traits across 8 generations of LLM agents, 626 agents from 20 founders), and an LLM moral-evolution study (lineage tracking, ancestor identification, reproductive-success metrics) — directly inform features 4 and 5.

**The cozy-art problem is solved with off-the-shelf CC0 kits.** The Stardew look is, concretely: a warm-against-dark palette, hand-crafted-feeling rounded forms, soft/warm lighting, and gentle contrast (Stardew reads warmer and more contrasty than Animal Crossing's bright pastels). In a 3D R3F context you evoke it with: toon/gradient-ramp materials (MeshToonMaterial + a 3-tone ramp with NearestFilter), soft accumulated shadows, a warm HDRI, instanced foliage, and sparing bloom/vignette. The asset supply is abundant and license-clean: KayKit (all CC0, ships glTF), Quaternius (CC0), and Kenney (CC0 1.0) cover buildings, nature, characters, animals, and props.

## Details

### Shared backbone (build once, reused by all six features)

**World/geography model.** Introduce a `region` (the world) containing multiple `cities`. New tables:
- `cities(id, run_id, name, kind, center_x, center_y, culture_seed, founded_tick, status)`
- `city_links(from_city, to_city, distance, travel_cost_ticks, link_kind)` — the travel graph (roads/paths).
- `agent_location(agent_id, city_id, place_id, in_transit_to, transit_arrival_tick)` — extends current per-agent location with a city scope and a transit state.

**Event-log additions** (append-only, OTel-linked, same as today): `city_founded`, `agent_departed`, `agent_arrived`, `trade_dispatched`, `trade_settled`, `treaty_proposed`, `treaty_ratified`, `relationship_changed`, `partnership_formed`, `child_spawned`, `building_upgraded`, `neighborhood_zoned`. Keep them small (IDs + deltas), since SQLite event volume is a named risk.

**Free-scale principle (applies everywhere).** Per the scaling evidence, the only way to grow the world without growing cost is to make **most new actions reflex (no LLM call)** and to **scope each agent's context to its own city**. The LLM Economist scaling table is the cautionary curve: framework throughput drops from ~1.16 FPS at 3 workers to 0.05 FPS at 1000 agents. Travel, trade settlement, child tending, and caravan movement are all reflex. The agent's prompt never sees the whole world — only its city, its relationships, and a one-line digest of "news from afar."

### Feature 1 — Multiple cities in one session
- **Data/engine:** cities share ONE tick loop and scheduler (no parallel loops). Each tick the scheduler iterates agents grouped by city; context assembly is scoped per city so prompt size stays flat as cities are added. Travel is a reflex tool `travel_to(city)` that sets `in_transit_to` and `transit_arrival_tick = now + travel_cost_ticks`; the agent is "off the board" (no LLM calls) until arrival, then emits `agent_arrived` and resumes. Migrating agents carry credits, skills, memories (top-K by importance), and relationship edges — all already in your schema, just re-pointed to a new `city_id`.
- **Inter-city trade:** a reflex `send_caravan(to_city, goods, credits)` creates a `trade_dispatched` event; settlement is reflex on arrival (`trade_settled`). Optionally a lightweight "merchant" actor_type (like your animals) that ferries goods on cheaper/less-frequent model calls.
- **Diplomacy:** treaties/alliances/rivalries ride the governance system — a proposal scoped to two cities, ratified by each city's existing vote threshold (Emergence used 70%; keep your ~70%). Relationship edges gain a `scope` (agent-agent vs city-city).
- **Cross-city communication:** a capped, reflex "courier"/billboard digest (ties to EM-091 billboards and EM-081 overhearing) so an agent hears a 1-line summary of another city's big events without an LLM call.
- **UI:** the 2D map view shows multiple settlements + travel routes; the 3D view gets a city switcher / zoom-to-city (pull EM-095 forward). Left feed gains a city filter; bottom agent strip groups by city.
- **Free-scale:** travel/trade/courier are all reflex; in-transit agents are dormant; context scoped per city.

### Feature 2 — Multiple worlds, same model family (A/B by model)
- **Reuse:** this is your existing **run** concept, parameterized. Add `runs.model_family` and a "seed all agents from family X" casting option (ties to EM-092 persona-card library). Use **fork/resume (EM-101)** so worlds can branch from a common seed state for clean A/B. The **run-browser + cross-run AWI comparison (EM-086)** is the comparison UX — pull both forward; they are the dependency that makes feature 2 real. This mirrors Emergence's design exactly: identical roles/conditions, vary only the foundation model.
- **Scheduling for free-scale:** run worlds **sequentially**, not concurrently, to avoid multiplying simultaneous rate-limit pressure across the ~16-provider FreeLLMAPI pool. A "tournament" runner executes Run A to tick T, snapshots, then Run B, etc. Per-provider RPD/TPD tracking (already built) gates this.
- **UI:** a "Model Family Arena" view in the inspector annex: side-by-side AWI sparklines per family, civilization-outcome cards (population, laws passed, buildings built, crimes, GDP/credits), using your existing uPlot/Observable Plot stack. The Gemini-vs-Claude crime/culture contrast is the headline demo this view exists to produce.

### Feature 3 — City building & expansion
- **Reuse:** the **collective-project pipeline** (propose-fund-build-succeed/fail) and the **building-state model** (planned→under_construction→operational→damaged/…). City growth = collective projects that instantiate new `places` and flip `cities.status` toward larger tiers.
- **Data:** `places` gains `neighborhood_id`, `zone_kind` (residential/market/civic/industrial/farm), `tier`. New `neighborhoods` table. Procgen town generation (EM-098) places new buildings on a grid as projects complete.
- **Visible growth:** a run starts with a few buildings; as projects finish, new instanced building meshes appear, roads extend, neighborhoods fill. This is the most "watchable" feature — time-lapse via your replay scrubber shows a town visibly grow.
- **Free-scale:** building placement and growth are reflex/deterministic given completed projects; no extra LLM calls.

### Feature 4 — Deeper relationships
- **Reuse:** the social-graph viz (react-force-graph-2d, time-scrub) and relationship store. Extend `relationships` with `type` (friend/partner/family/mentor/rival/feud), `strength` (float), `valence`, and `since_tick`; add `factions(id, name, city_id)` and `faction_membership`. Reputation = a derived per-agent aggregate.
- **Engine:** relationship changes are mostly reflex consequences of existing talk/give/steal/vote actions (e.g., repeated gifts deepen friendship; theft creates feud). Reflection (EM-080, fired on the Smallville-style importance threshold ~2–3×/day) can occasionally upgrade a relationship type — a cheap, throttled LLM touch, not per-tick.
- **Drives features 1 & 5:** partnerships gate children; factions/feuds drive migration and diplomacy. Per Project Sid, this social awareness is the precondition for emergent specialization and roles.
- **UI:** edge colors/types in the social graph; relationship-type filter; faction hulls; a reputation column in the agent card strip.

### Feature 5 — Children / generations (lightweight first, depth later)
- **Lightweight v1 (rides existing systems):** when two agents form a `partner` relationship above a strength threshold and both consent (reflex check), a **reflex** `child_spawned` event casts a new agent via the **ad-hoc spawn system + persona-card library (EM-092)**: a blended persona (traits crossed from both parents — informed by Genomebook's additive/dominant inheritance models, which produced trait trajectories consistent with the encoded selection rules across 8 generations), a per-model color, an inherited relationship seed (knows its parents), and a small starting memory ("born in {city}"). The child rides a cheaper routed model and acts **less often** (every N ticks) to control cost.
- **Free-scale controls (critical):** hard **population cap** per run (configurable, default ~12–16 to stay near Emergence's 10-agent free-scale sweet spot); child agents act on a slower cadence and cheaper model; mortality (existing needs/death) balances births; births gated by housing capacity (EM-098 bunkhouse scarcity) and credits (a sink). A birth must be "paid for" in energy/credits.
- **Depth roadmap (later waves):** life stages/aging (child→adult→elder act-cadence and tool unlocks), inheritance of credits/relationships/grudges on death, lineage trees in the inspector (cf. the moral-evolution study's lineage tracking + ancestor identification), population-dynamics AWI metrics, and multi-generational culture drift compared across model families (feature 2 synergy).

### Feature 6 — 3D art-direction overhaul (major priority)

**Recommended asset pipeline:** glTF/GLB CC0 kit → `gltfjsx --transform` (draco + webp + resize + dedupe, 70–90% smaller, auto-instancing) → reusable R3F `<Model>`/`<Instances>` components → swap materials to `MeshToonMaterial` with a shared 3-tone gradient ramp (NearestFilter, `generateMipmaps=false`) → bake/accumulate soft shadows via drei `<AccumulativeShadows>`/`<RandomizedLight>` (zero per-frame cost once accumulated) → warm CC0 HDRI from Poly Haven via drei `<Environment>` → sparing `<EffectComposer>` with selective `<Bloom luminanceThreshold≈1>` + `<Vignette>` + filmic tone mapping. Keep `antialias:false` (let post handle it), use drei `<Detailed>` for LOD and drei `<Instances>`/`<Merged>` for repeated props/trees, cap draw calls, and use sprite-impostors for distant buildings in multi-city view.

**License-vetted asset shortlist (all CC0 — no attribution required — unless noted, all ship glTF):**
- **KayKit (Kay Lousberg) — all CC0:** *Medieval Hexagon Pack* (~200+ models, marketed for cozy village builders — top pick for the village base: hex tiles + buildings like blacksmith/tavern/windmill + nature), *Forest Nature Pack* (100+ free — top foliage pick), *City Builder Bits* (32+ free), *Character Pack: Adventurers* + *Character Animations* (rigged/animated humanoids, retargetable), *Furniture/Restaurant/Holiday Bits* (props). FBX/GLTF/OBJ, single 1024² gradient atlas (ideal unified toon look, downsamplable to 128px). The "Medieval Builder Pack" is now legacy — use Hexagon instead. (Complete/Bundle tiers are paid convenience only; individual packs are free.)
- **Quaternius — all CC0:** *Stylized Nature MegaKit* (110+, "Ghibli-inspired" — top nature pick), *Ultimate Nature Pack*, *Medieval Village MegaKit* (300+ modular grid-snapping pieces with interior+exterior walls), *Ultimate Animated Animal Pack* (12 animals, 12+ anims each) + *Farm Animal Pack*, *Ultimate Modular Men/Women* (modular animated characters with humanoid rig), *Universal Animation Library* (120+ retargetable anims). FBX/OBJ/glTF/Blend. (No pack literally named "Cute Animals" exists — use the Animated/Farm Animal packs.)
- **Kenney — all CC0 1.0:** *Nature Kit* (~330 assets, best Kenney nature), *Survival Kit* (~80, farm tools/props), *City Kit Suburban* (40 cozy houses + fences/driveways), *Furniture Kit* (~140), *Food Kit* (~200), *Holiday Kit* (~100 seasonal decor), *Fantasy Town Kit* (~160 modular town pieces), *Mini Characters 1* (~25), *Animal Pack* (~80). Separate FBX/OBJ/glTF per kit.
- **Poly Haven — CC0 (no attribution):** HDRIs (warm-light environments), textures, models — for `<Environment>` lighting and ground textures.
- **itch.io community:** *COZY FARM by styloo* — confirmed CC0 (gradient-palette farm scene matching the KayKit/Quaternius toon look).
- **Attribution-required / verify (use only behind a credits file):** most Sketchfab village packs are CC-BY-4.0 or paid — verify each model's license field before use; named candidates include "Rustic Low Poly Village Pack," "Casual Village Buildings Pack," "Low Poly Fantasy Village." Treat CC-BY as opt-in with a `CREDITS.md`.
- **Toon ramp:** three.js MeshToonMaterial `gradientMap`; grab the three-tone/five-tone PNGs from the sbcode tutorial's `gradientMaps.zip`, or author a trivial self-made 3×1 PNG (license-free). Set min/magFilter = NearestFilter, generateMipmaps = false (otherwise the bands interpolate and you lose the cel look).
- **Starters/libs (all MIT):** pmndrs/react-three-fiber, @react-three/drei, @react-three/gltfjsx, @react-three/postprocessing, pmndrs/react-three-next (Next.js R3F scaffold via `create-r3f-app`), pmndrs/react-three-lightmap (in-browser lightmap/AO baker). No single polished "cozy village" R3F starter exists — scaffold from react-three-next + drei instancing + CC0 GLBs.

**Phased art swap (ships incrementally, each its own demo-able PR):** (1) ground + warm HDRI + toon material + soft shadows (instant vibe change); (2) instanced trees/foliage (KayKit Forest / Quaternius Nature); (3) buildings per place-kind (KayKit Hexagon / Kenney Fantasy Town) wired to building-state; (4) characters (KayKit Adventurers / Quaternius Modular) with model-color tint; (5) day/night + seasons + particles (chimney smoke, fireflies at night) + sparing bloom/vignette. This interleaves with procgen (EM-098) and multi-city geography (each city can pick a culture-themed kit/palette so divergent cultures are visually legible).

### Breadth-first Wave plan (each line = one demo-able PR)

**Wave W10 — "There is more than one place" (breadth slice):**
- **EM-105 (P0):** Multi-city data model + second settlement rendered on 2D map. *Demo: two towns exist in one run.*
- **EM-106 (P0):** Reflex `travel_to` + in-transit state + `agent_arrived`; one agent walks from town A to B carrying credits/memories. *Demo: an agent migrates between cities.*
- **EM-107 (P0):** Art win #1 — warm HDRI + toon material + AccumulativeShadows on existing geometry. *Demo: the village suddenly looks cozy.*
- **EM-108 (P0):** Parallel-worlds runner: `runs.model_family` + sequential tournament + run-browser entry (pull EM-086 forward). *Demo: launch an all-Qwen run vs an all-Gemini run.*
- **EM-109 (P1):** Relationship `type`/`strength` schema + colored edges in social graph. *Demo: friendships vs rivalries visible.*
- **EM-110 (P1):** Lightweight children: partner→reflex `child_spawned` blended persona on cheaper model + population cap. *Demo: two agents pair and a child is born.*
- **EM-111 (P1):** City-growth slice: one collective project that adds a new instanced building when funded. *Demo: the town visibly gains a building.*

**Wave W11 — depth pass 1:**
- **EM-112 (P1):** Inter-city trade caravans (reflex dispatch/settle) + merchant actor_type. *Demo: goods flow between towns.*
- **EM-113 (P1):** Diplomacy via governance (treaties/alliances/rivalries, city-scoped votes; bundle EM-079/087/100/103 texture). *Demo: two cities sign a treaty.*
- **EM-114 (P1):** Instanced trees/foliage swap (art phase 2). *Demo: lush forests, still 60fps.*
- **EM-115 (P1):** Model-Family Arena comparison UI (cross-run AWI side-by-side). *Demo: compare civilizations by model family.*
- **EM-116 (P2):** Factions + feuds + reputation (extends EM-109). *Demo: factions form and cluster on the graph.*
- **EM-117 (P2):** 3D camera nav: zoom-to-city / follow-agent (EM-095) + building-label declutter (EM-102). *Demo: cinematic camera across cities.*

**Wave W12 — depth pass 2:**
- **EM-118 (P2):** Buildings-per-place-kind swap (art phase 3) wired to building-state + procgen (EM-098). *Demo: distinct building types per zone.*
- **EM-119 (P2):** Neighborhoods + zoning + megaprojects (city growth depth). *Demo: zoned districts grow.*
- **EM-120 (P2):** Character model swap (art phase 4) + pets in sidebar (EM-099). *Demo: charming villagers + pets.*
- **EM-121 (P2):** Reflection/diary on importance threshold (EM-080) feeding relationship upgrades + reflection-driven migration. *Demo: agents reflect, then relocate.*
- **EM-122 (P3):** Generational depth: life stages/aging + inheritance of credits/relationships on death + lineage tree in inspector. *Demo: a dynasty across generations.*
- **EM-123 (P3):** Day/night + seasons + particles + sparing bloom/vignette (art phase 5). *Demo: sunset over the village with chimney smoke.*
- **EM-124 (P3):** Population-dynamics AWI metrics + culture-drift comparison across model families. *Demo: population/culture charts per family.*

### Dependencies on existing open backlog (pull-forward recommendations)
- **EM-101 (fork/resume)** — pull forward; the backbone for parallel worlds (feature 2) and lineage. **P0 prerequisite for EM-108.**
- **EM-086 (run-browser + cross-run AWI)** — pull forward; the comparison UX for feature 2. **P0 for EM-108/EM-115.**
- **EM-092 (persona-card library)** — pull forward; casting pool for both family-seeding (feature 2) and children (feature 5). **P0-ish for EM-108/EM-110.**
- **EM-098 (procgen town + housing)** — supports features 3 and 5 (housing caps births). Pull into W12.
- **EM-095 (3D camera nav)** — needed for multi-city navigation; pull into W11 (EM-117).
- **EM-080 (reflection/diary)** — enriches features 4/5; W12 (EM-121). Implement on Smallville's importance-sum threshold (~2–3×/day).
- **EM-091 (billboards) / EM-081 (overhearing)** — back cross-city communication (feature 1); fold into EM-106/EM-112.
- **EM-099 (pets in sidebar), EM-102 (label declutter), EM-096 (layout redesign)** — UI polish that rides the art waves.
- **EM-079 (active-commitments/phantom-commitment), EM-087 (duplicate-law), EM-100 (rule names), EM-103 (legislation-as-architecture)** — governance texture; bundle into diplomacy (EM-113).

## Recommendations
1. **Do EM-105 next** (multi-city data model + second settlement on the 2D map). It is the smallest PR that unblocks the most v3 surface area and demos instantly. Benchmark to proceed: tick-loop time per tick stays flat with 2 cities at the current agent count (no per-city LLM-call multiplication).
2. **Immediately pull EM-101, EM-086, EM-092 forward** — they are hard prerequisites for the parallel-worlds feature and cheap to land. If you only do one extra thing this month, make it EM-101 (fork/resume), because lineage AND A/B both depend on it.
3. **Ship EM-107 (art win #1) early and in parallel** — it's isolated from the engine work, is the stated priority, and produces the most shareable demo. Threshold to expand the art investment: if EM-107 holds ≥50fps on the MacBook alongside the 2D instrumentation, proceed to instanced foliage (EM-114); if not, drop bloom and reduce shadow-accumulation frames first.
4. **Hold the population cap hard** until you've measured token spend. Start children (EM-110) at a low cap (~12–16 total agents) on cheaper routed models and a slow act-cadence; only raise the cap after a full run stays inside the FreeLLMAPI free tiers (watch per-provider RPD/TPD). Threshold to raise the cap: a 15-day-equivalent run completes without exhausting any provider's daily cap.
5. **Run parallel worlds sequentially, not concurrently** (tournament runner) to avoid rate-limit exhaustion across the provider pool; revisit concurrency only if usage tracking shows headroom.
6. **License hygiene now:** add `CREDITS.md` and `ASSET_LICENSES.md` to the repo, prefer CC0 (KayKit/Quaternius/Kenney/Poly Haven), and quarantine any CC-BY asset behind an attribution entry. Never ship Stardew/ConcernedApe assets — evoke the vibe with CC0 kits + toon materials only.

## Caveats
- **LLM-call/cost blowup is the dominant risk.** More cities × agents × children = more calls. De-risk: reflex-first resolution for travel/trade/children/caravans; per-city context scoping; hard population cap; cheaper/slower models for secondary entities; sequential parallel worlds. The LLM Economist scaling table (throughput ~1.16 FPS at 3 workers → 0.05 FPS at 1000 agents) is the cautionary curve, and Emergence's 10-agents-per-world is the demonstrated free-scale sweet spot.
- **Prompt-size growth as the world scales** — never put the whole world in an agent's prompt; scope to its city + a 1-line "news from afar" digest. Watch your existing prompt-prefix cache hit rate as a regression signal.
- **SQLite/event-volume growth** — new event kinds multiply rows; keep events as small ID+delta records, lean on WAL + periodic snapshots, and use per-run DB files (already supported) so one big run doesn't bloat all.
- **3D performance alongside 2D instrumentation** — a richer scene competes with uPlot/force-graph for the MacBook's GPU/battery. De-risk: instancing, LOD (`<Detailed>`), accumulated (not per-frame) shadows, selective bloom, `antialias:false`, sprite-impostors for distant cities, and a "lite" rendering toggle.
- **Keeping each PR small/shippable** — the breadth-first ordering is explicitly designed so each EM-### is independently demo-able; resist bundling trade + diplomacy + factions into one PR.
- **License compliance** — CC0 needs no attribution but CC-BY does; mis-tagging a Sketchfab asset is the most likely compliance slip. Default to CC0 sources and keep the attribution file authoritative.
- **Emergence-style instability is a feature, not a bug** — expect collapse, arson-equivalents, and "phantom commitments." Emergence's Gemini world logged 683 crimes yet the richest culture, while Claude held order with zero crimes; surface these as texture in the Story So Far / Narrator, don't suppress them.

### Consolidated v3 backlog (EM-105 → EM-124)
| EM | Title | Area | P | Wave | Deps | Demo hook |
|----|-------|------|---|------|------|-----------|
| 105 | Multi-city data model + 2nd settlement | Multi-city | P0 | W10 | — | Two towns in one run |
| 106 | Reflex travel + migration | Multi-city | P0 | W10 | 105 | Agent walks A→B with credits/memories |
| 107 | Art win #1: HDRI+toon+soft shadows | Art | P0 | W10 | — | Village looks cozy |
| 108 | Parallel-worlds runner (model_family) | Parallel | P0 | W10 | 101,086,092 | All-Qwen vs all-Gemini run |
| 109 | Relationship type/strength + graph colors | Relationships | P1 | W10 | — | Friend vs rival edges |
| 110 | Lightweight children (partner→spawn) | Children | P1 | W10 | 092,109 | A child is born |
| 111 | City-growth slice (project→building) | City growth | P1 | W10 | — | Town gains a building |
| 112 | Inter-city trade caravans | Multi-city | P1 | W11 | 105,106 | Goods flow between towns |
| 113 | Diplomacy via governance | Multi-city | P1 | W11 | 105,109 | Two cities sign a treaty |
| 114 | Instanced foliage (art phase 2) | Art | P1 | W11 | 107 | Lush forests at 60fps |
| 115 | Model-Family Arena comparison UI | Parallel | P1 | W11 | 108,086 | Compare civs by model family |
| 116 | Factions + feuds + reputation | Relationships | P2 | W11 | 109 | Factions cluster on graph |
| 117 | 3D camera nav + label declutter | Multi-city/Art | P2 | W11 | 095,102 | Cinematic camera across cities |
| 118 | Buildings-per-place-kind (art phase 3) | Art/City | P2 | W12 | 098,111 | Distinct building types |
| 119 | Neighborhoods + zoning + megaprojects | City growth | P2 | W12 | 111 | Zoned districts grow |
| 120 | Character swap (art phase 4) + pets | Art | P2 | W12 | 099 | Charming villagers + pets |
| 121 | Reflection/diary → relationship/migration | Relationships | P2 | W12 | 080,109 | Agents reflect then relocate |
| 122 | Generational depth: aging + inheritance + lineage tree | Children | P3 | W12 | 110 | A dynasty across generations |
| 123 | Day/night + seasons + particles + bloom (art phase 5) | Art | P3 | W12 | 107 | Sunset with chimney smoke |
| 124 | Population/culture AWI metrics per family | Parallel | P3 | W12 | 108,122 | Population/culture charts per family |

**Immediate next PR: EM-105 — the multi-city data model + a second settlement on the map.**

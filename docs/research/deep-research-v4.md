# Deep Research v4 — The EW-Grade City & Scaling to 25 Agents

> Date: 2026-06-10 · Direction adjustment: the art target is **Emergence World's dense, zoned
> city — done better** — not Stardew-cozy. This doc covers (1) the asset catalog, (2) the
> procedural city generator + rendering architecture, (3) the token-scaling architecture for
> ~25 agents (headroom 50) under the free-scale law (subscription-only billing; the sim never
> runs on paid API).
>
> Extends `deep-research-v3.md` (the EW analysis + free-scale principle baseline). Feed this
> through `plan-intake` once reviewed.

## TL;DR

- **EW's secret is density and zoning, not technology.** Their world is ~240×240 units,
  38+ *hand-authored* landmarks (markdown files in their repo), rendered in React + R3F —
  the same stack we already run. They did NOT procedurally generate their city. We can beat
  them with a **deterministic CityGenerator**: sim snapshot + seed → road grid with lane
  markings, zoned blocks, hundreds of kit-assembled buildings, street furniture, vehicles.
  Same seed → same city, stable across re-renders.
- **The asset problem is solved, cheap, and license-clean.** The Kenney City Kit family
  (Roads + Commercial + Suburban + Industrial) + Car Kit + Furniture Kit = **~360+ pieces,
  ~13 MB total, all CC0, all direct headless zip URLs, all one coherent palette.** KayKit
  City Builder Bits (32+ props, CC0, GitHub) supplements. This replaces the medieval kits
  as the world's vocabulary — Wave C's *machinery* (registry, toon pipeline, error
  boundaries, instancing, animation) carries over unchanged.
- **Rendering at EW scale is comfortably in budget.** With raw `InstancedMesh` per kit-piece
  type + a shared texture atlas (gltfjsx `--instanceall`/`--transform`), 500–1000 buildings
  ≈ **8–10 draw calls** — integrated-GPU 60fps territory (budget: <100 draw calls).
- **Agent scaling: the trap is concurrency, not count.** Our loop is strictly sequential
  (one agent turn per tick): 25 agents costs the same tokens/hour as 3 — but each agent
  would act once per ~3 minutes (sim-quality death). Naive parallel 25 agents kills the
  daily free quota in ~40 minutes. The fix is a **tier + salience architecture**
  (protagonists every round; background agents act via LLM only when something changed near
  them, else zero-LLM reflex routines) + a prompt diet + Ollama overflow. Compound effect:
  **~15–20× cheaper than naive**, and 25 agents fits an 8–12h session inside the free tier
  — cheaper per hour than today's 3-agent run.

---

## 1. What Emergence World actually is (so we can beat it)

From their repo (`github.com/EmergenceAI/Emergence-World`) and blog:

- React 18 + **React Three Fiber** front, FastAPI + Postgres back. Our stack already matches.
- ~240×240 unit grid, NYC real-time + live weather, day/night.
- **38+ landmarks defined as hand-written markdown files** (`/landmarks/`) — residences,
  shops, parks, Town Hall, police station, Victory Arch. No procedural layout, no published
  city-generation code.
- 10 agents/world, 5 parallel worlds, 120+ tools, constitutional governance (70% to pass).

**Where we beat them:**

| EW | Us (target) |
|---|---|
| Hand-authored static landmark list | Deterministic generator: the city *derives from sim state* — districts, buildings, growth are the simulation's output |
| Fixed 10 agents | 25 (headroom 50) on free models via tier/salience scheduling |
| One paid frontier model per world | Per-agent hot-swappable models — already our core feature |
| Static city | City that grows: EM-123 (neighborhoods grow) plugs straight into the generator |

## 2. Asset acquisition plan (all CC0, all headless)

### Tier 1 — the core vocabulary (~13 MB, ~360+ pieces)

| Kit | Pieces | Covers | Headless URL |
|---|---|---|---|
| Kenney City Kit (Roads) | 70+ | roads, lane markings, highways, barriers, lightposts | `kenney.nl/media/pages/assets/city-kit-roads/74288c9459-1741864740/kenney_city-kit-roads.zip` |
| Kenney City Kit (Commercial) | 50+ | skyscrapers, offices, shops | `kenney.nl/media/pages/assets/city-kit-commercial/a742d900eb-1753115042/kenney_city-kit-commercial_2.1.zip` |
| Kenney City Kit (Suburban) | 35+ | houses, fences, driveways, trees | `kenney.nl/media/pages/assets/city-kit-suburban/2c871b7af2-1745479373/kenney_city-kit-suburban_20.zip` |
| Kenney City Kit (Industrial) | 25+ | factories, warehouses | `kenney.nl/media/pages/assets/city-kit-industrial/5fcb837741-1750838303/kenney_city-kit-industrial_1.0.zip` |
| Kenney Car Kit | 45+ | vehicles (parked + traffic) | `kenney.nl/media/pages/assets/car-kit/1a312ec241-1775131960/kenney_car-kit.zip` |
| Kenney Furniture Kit | 140+ | benches, lamps, bins, hydrants, street furniture | `kenney.nl/media/pages/assets/furniture-kit/440e0608a4-1677580847/kenney_furniture-kit.zip` |

All ship GLB natively (no conversion needed), single 1024² atlas texture per kit
(toon-ramp friendly, downsamples to 128² without banding), one consistent flat palette
across the whole family, CC0 1.0.

### Tier 2 — prop-density supplement

- **KayKit City Builder Bits 1.0** (`github.com/KayKit-Game-Assets/KayKit-City-Builder-Bits-1.0`,
  also `kaylousberg.itch.io/city-builder-bits`): 32+ models — water towers, dumpsters,
  traffic lights, hydrants, police car/taxi, road bits. CC0, OBJ/FBX/glTF, aesthetic-compatible
  with Kenney. *Note: Wave C skipped this kit because "modern-city aesthetic" — that is now
  exactly the target.*

### Rejected / conditional

- **Quaternius Downtown City MegaKit** (153 free assets, CC0, itch.io, 223 MB): biggest single
  kit but higher saturation + edge definition = palette-clash risk with Kenney; payload heavy.
  Conditional: a distinct downtown district *if* blending tests pass. Not v1.
- **J-Toastie City Pack** (poly.pizza): mixes CC-BY — license fail.
- Eclair GLB repacks: redundant (Kenney ships GLB).
- Poly Haven: HDRI/textures only (we already use Venice Sunset).

Every vendored file gets an `ASSET_LICENSES.md` row, per the standing rule.

## 3. The city generator (the "Fable 5 one-shot" track, made durable)

The two tracks from the question converge: Fable 5's power is spent **at build time
authoring a deterministic generator**; the kits are the vocabulary it arranges. That's
strictly better than a one-shot scene, because the city re-derives from every sim snapshot
(growth, districts, destruction) instead of being frozen art.

**Pipeline** (`CityGenerator` module, pure + seeded — same discipline as `townLayout.ts`):

```
sim snapshot (places + districts + buildings) + seed
  → 1. anchor landmarks: each sim place claims a grid cell by district
  → 2. road network: Manhattan grid (EW-style) — main avenues between district
       centers, local streets subdividing blocks; lane markings from the Roads kit
  → 3. block subdivision: blocks → 4–8 lots each (seeded RNG, min-margin rule)
  → 4. zoning: lot inherits district zone → picks from that zone's kit palette
       (commercial/suburban/industrial/civic)
  → 5. building assembly: lot → kit-piece composition (footprint + height variety,
       seeded); sim Buildings (the agent-built ones) get hero placement on their lot
  → 6. prop scatter: sidewalk furniture, parked cars, trees, park fills — seeded,
       density per zone
  → output: per-piece-type instance lists (position/rotation/scale + atlas UV)
```

- **Determinism is a hard rule** (same as foliage/townLayout): seeded PRNG only
  (`seedrandom` or our existing mulberry-style hash), zero `Math.random()`. Same snapshot +
  seed → byte-identical city. Testable in vitest exactly like `townLayout.test.ts`.
- Parish-Müller L-systems (CityEngine) are overkill; the grid-block-subdivision approach is
  what EW's look actually is, and it's a few hundred lines. Reference implementations:
  `photonlines/Procedural-City-Generator`, `jstrait/city-tour`.
- Scale: ~36 blocks (240×240, 40-unit blocks) → 150–300 buildings → 1,200–2,400 kit-piece
  instances. EW has 38 landmarks; we'd render an order of magnitude more *stuff*.

## 4. Rendering architecture (60fps with hundreds of buildings)

- **Raw `<instancedMesh>` per kit-piece type** — NOT drei `<Instances>` (documented 5–10×
  perf gap, drei issues #2041/#3306). One InstancedMesh per piece type = 1 draw call each.
  Wave C's unused `InstancedModel` finally gets its consumer (and likely a rewrite to raw
  instancing).
- **gltfjsx `--instanceall` / `--transform`**: dedupe kit geometries, share the atlas
  material, 70–90% size reduction. One toon-ramp conversion per atlas (existing
  `toonify.ts` applies).
- **Draw-call math**: ~10–20 piece-type buckets (walls/roofs/windows/roads/cars/furniture/
  trees) ⇒ **~10–20 draw calls for the entire city**. Budget for integrated-GPU 60fps is
  <100. Benchmark: 1,000 instanced trees = 1 draw call @120fps (GTX 1070).
- **Chunked culling**: InstancedMesh culls all-or-nothing — split instance sets into block
  chunks (e.g. per city block) so off-screen districts cull.
- **Shadows**: keep the single directional sun; tighten the shadow frustum to the visible
  chunk rather than cranking resolution; `bias -0.001 / normalBias 0.01`. The city is
  deterministic-static between snapshots, so baking is a later option.
- **LOD**: drei `<Detailed>` for building shells at distance (30–40% frame savings in big
  scenes); characters already have LOD precedent via foliage.
- Wave C machinery that survives unchanged: model registry pattern, `ModelBoundary`
  fallback invariant (procedural silhouettes remain the fallback), toon pipeline,
  rigged characters (KayKit villager reads fine in a modern city), camera/focus system,
  feed/overlay layer.

## 5. Scaling to 25 agents under the free-scale law

### The measured baseline (from `data/run.sqlite`, 12,092 llm_call rows)

- **~1.93k tokens/call** (1,525 in / 403 out avg), ~1.05 calls/turn, 12% retry lifetime
  (4.5% post-EM-140), router cache hits 35% (run 236).
- The loop is **strictly sequential** (`loop.py` one agent turn per tick, ~7s effective
  turn period ⇒ ~510 turns/hour total **regardless of agent count**).
- Free-tier reality (FreeLLMAPI lane caps): realistic sustained aggregate ≈ **2,000–3,500
  quality calls/day, ~4–7M tokens/day**, burst ~105 RPM. Today's 3-agent continuous run
  (~375 net req/h) already exhausts that in ~6–8h.

### The scaling table

| Scheme | Agents | Net req/h | Tokens/h | Verdict |
|---|---|---|---|---|
| Current sequential | 25 | ~375 | ~0.74M | quota-fine, but each agent acts every ~3 min — sim death |
| Naive parallel (cadence held) | 25 | ~3,150 | ~6.1M | daily quota dead in **~40 min**; kills 10-RPM lanes instantly |
| Naive parallel | 50 | ~6,300 | ~12.2M | exceeds burst RPM outright |
| **Tiered + salience + diet + Ollama** | **25** | **~220–260 (+ ~100–150 local)** | ~0.40M | **8–12h sessions inside free tier** |
| Tiered (population governor active) | 50 | ~260–300 (+ ~150 local) | ~0.45M | fits |

### The mechanisms, prioritized (each cites what already exists to build on)

1. **Turn-cadence tiers (3×, build first).** Protagonist (5, every round) / supporting
   (every 3rd) / background (every 10th). The pattern is already shipped end-to-end for
   animals (`act_every_n_ticks` + `llm_chance` + reflex fallback, `loop.py:650–702`,
   `animals/runtime.py:280–305`). Add `cadence_tier` to AgentState + tier-aware
   `next_agent()`.
2. **Salience-gated reflex turns (~2× more; the biggest NEW lever).** Today the LLM is
   called every turn even to choose a reflex action. Gate it: call only if something
   changed near the agent (new co-located agent, importance-weighted witnessed event,
   energy threshold crossing, active whisper/proclamation); otherwise run a deterministic
   needs routine (recharge → work → forage → home) with **zero** calls. The per-agent
   `_importance` accumulator (`runtime.py:1313`) is a ready salience signal; the animals'
   seeded reflex picker is the template. Never applies to protagonists.
3. **Prompt diet (1.6× tokens; a *correctness* requirement for the 8K-context Cerebras
   lane at 25 agents).** Cap relationships block to top-8 by |trust| (it's O(N) today —
   ~700 extra tokens at 50 agents); scope `open_projects` and the `move_to` place list to
   district; drop the ~330-token decision-trace instruction block for background tiers
   (cuts output ~400→~150 too); `memory_window` 12→8 for background.
4. **Cache-key normalization (35%→50–60% hit rate for quiet agents, free).**
   `Tick: {tick}` and `energy:.1f` in the prompt bust the router's sha1 cache every round.
   Bucket energy to 10s, floor tick to day for background prompts.
5. **Ollama overflow lane (~40% of background calls off FreeLLMAPI).** Uncomment
   `profiles.yaml:112–122`; run those turns as background tasks (the animal-task pattern)
   so 10–20s local latency never stalls protagonist rounds. Local 7–13B ≈ 180–350
   turns/h — right for background, useless for protagonists.
6. **Cap-pressure governor.** Wire the three existing *observers* (UsageAlertTracker 70%
   alerts, the default-off `usage_caps` throttle, EM-135 lane health) into the scheduler:
   on a lane's 70% alert, demote that lane's agents one cadence tier instead of merely
   slowing ticks. This enforces v3's population-cap rule.
7. **Batched group scenes (situational, last, background-only).** One call resolves a
   k-agent plaza conversation. Real quality cost: single-model ventriloquism breaks the
   per-agent-model premise — never for protagonists or cross-profile pairs.
8. **Narrator/animals: already depowered** — leave as is (<1.5% of volume).

Compound: **~15–20× cheaper than naive-25**; concurrency stays ≤2–3 parallel turns on
distinct lanes (the 10-RPM Gemini lane is the canary). Every mechanism removes or
relocates calls — none adds a standing call. The free-scale law holds.

## 6. Risks & open questions

- **Aesthetic pivot is real**: medieval kits (Wave C) → modern city kits. The villager/cat/
  dog rigs and toon look carry over; the 9 KayKit-medieval buildings get retired or kept as
  a "old town" district. Decide: full pivot vs. old-town-core-with-modern-growth (the
  latter tells the better story: the town we have *grows into* the city).
- **Sim vocabulary lag**: a zoned city wants the sim to know about zones/lots; today it has
  15 places + districts. The generator can fabricate visual density from day one (set
  dressing), but city *growth* needs EM-123's neighborhood mechanics to drive real lots.
- **Cadence-tier fairness**: who is a "protagonist"? Proposal: user-pinned + highest-salience
  rotating slots, so the camera's subjects are always full-rate.
- Free-tier quota figures are mid-2026 and drift; the governor (mech. 6) is the hedge.
- Quaternius MegaKit blending test is cheap to run if downtown wants more skyline variety.

## 7. Suggested wave shape (for plan-intake)

1. **Wave D1 — vocabulary + generator**: vendor Tier-1 kits, atlas/instancing pipeline,
   deterministic CityGenerator (roads/blocks/lots/zoning), render the dense city from the
   current 15-place snapshot. Pure frontend + assets; zero backend.
2. **Wave D2 — population scaling**: cadence tiers + salience gating + prompt diet +
   cache normalization (backend; mechanisms 1–4), then 25-agent world.yaml + personas.
3. **Wave D3 — life**: vehicles on roads, Ollama lane, cap governor, day/night (EM-127
   folds in), EM-123 growth driving generator input.

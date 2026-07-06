# Research Brief — Giving Agents True Control Over Their 3-D World

> **How to use this document.** Paste this whole brief into a fresh Claude deep-research
> session on the web. It is fully self-contained — the research session has *none* of this
> project's repo context, so everything it needs is here. The mission and the questions I
> want answered are in **Part 0**; Parts 1–8 are the context that grounds them; Part 9 is
> the deliverable I want back.
>
> **Prepared:** 2026-07-05 · **Project:** PetriDishOfMadness (PDoM) · **Audience:** an
> external deep-research session tasked with proposing *new project ideas and plans* for
> transforming the 3-D world into something the agents truly author and control.

---

## Part 0 — The research mission

PetriDishOfMadness is a live multi-agent "chaos lab": a handful of LLM-driven agents (each
possibly running a *different* model) live in a small 3-D town, and you watch them cooperate,
betray, legislate, build, and die. The marquee feature is **per-agent, hot-swappable model
control** — the whole point is watching different LLMs diverge inside the *same* world.

We have spent months making the agents author the *social* world (crime, governance, factions,
religion/culture/war are built or planned) and, recently, the *physical* world's **roads** (agents
build/demolish roads, vote on city-wide topology, watch a voted "pentagon plan" reshape the streets)
and **building placement** (agents' buildings now cluster into organic hamlets on open ground).

**The question this research should answer:** *What is the next frontier of giving agents true,
legible, emergent control over their physical world* — drawing selectively on the *mechanics* (not
the look) of **Pokémon (discrete tiled regions, routes, towns)**, **Stardew Valley (terrain, seasons,
farming, interiors, resource nodes)**, and **Minecraft (agent-modifiable terrain, blocks, resources,
verticality)** — *without breaking the hard constraints in Part 6 and without falling into the
aesthetic trap in Part 7?* **The project owner has already resolved the biggest strategic forks —
see Part 0.5. Treat those as fixed: your job is the *how*, not the *whether*.**

I want back a **prioritized set of concrete, buildable project directions** (see Part 9 for the exact
shape), each scored against our constraints, each with a "why it deepens agent control" thesis, and
each honest about cost, determinism, and asset feasibility. Wild ideas are welcome **if** they carry a
plausible path through the constraint box — I would rather have five ideas that fit our reality than
fifty that assume a AAA budget or a GPU farm.

**The five questions, up front (all now scoped by the Part 0.5 decisions):**

1. **Substrate design.** What terrain / elevation / water / resource layer best slots *under* an
   EW-dense city for a tiny, free, deterministic, browser sim? (A heightmap? A coarse tile/chunk grid?
   A low-res block layer?) Give the ground-truth data model, the agent verbs (raise / lower / dig /
   flood / till / claim), and the *district-scoped* perception it needs — and rank the substrate options.
2. **Resource & matter economy.** Once agents can shape ground, what's the *minimal* spatial
   resource/material system (soil / water / wood / stone / ore → gather → build-from) that turns today's
   abstract "forage/work" buffs into things agents compete over and physically reshape — deterministic,
   and without ballooning the prompt?
3. **Deep 2-D authorship (rung A).** How do we extend the *existing free image lane* from one plaza
   banner to agent-generated **facade textures, signs, flags/heraldry, murals, graffiti, paintings**
   across many surfaces — determinism-safe (off the replay surface), performant (atlas / decal / texture
   budget), and legible? What surfaces, what agent verbs, what caching, what fallback?
4. **Parametric 3-D authorship (rung B).** What recipe schema + deterministic generator (modular
   kit-bash? a procedural facade grammar? WFC? L-systems?) lets agents author unique building *form*
   cheaply in-browser — killing the ~86%-"generic" problem — and how does an agent *choose / evolve* a
   recipe within the prompt diet?
5. **The keystone + sequence.** Of the four workstreams above, which single one unlocks the most
   "the world is truly theirs" first — and what's its minimal, determinism-safe, free, flag-gated first
   slice, plus the build order for the rest?

---

## Part 0.5 — Decisions already made (your guardrails)

The project owner has resolved the biggest forks. **Treat these as fixed constraints on your
recommendations, not open questions.** They narrow the search — lean into them; don't re-litigate them.

1. **Keep the engine; evolve, don't replace.** The react-three-fiber renderer + the deterministic,
   event-sourced world + replay/fork is the crown jewel and stays. We are **not** building a new engine
   or abandoning the city. Reason: byte-identical replay across model runs is what makes this a *lab*
   rather than a toy — the hard-won part.

2. **Add substrate *under* the existing city — do not swap the city out.** The chosen direction is to
   slot a **terrain / elevation / water / resource layer beneath the current EW-dense city**, giving
   agents far more to shape (dig, farm, flood, wall, terraform) *without* discarding the dense-city
   canvas. This is "evolve the substrate," explicitly **not** a wholesale pivot to a Stardew/Minecraft/
   Pokémon world. Mine those worlds for **mechanics**; fit them *under* an EW-dense city.

3. **The EW-dense-city aesthetic lock HOLDS.** Because we chose evolve-not-pivot, the "Emergence-World
   dense zoned city, done better — NOT Stardew-cozy" register (Part 7) stays in force. New substrate and
   new assets must read in that register — dense, legible, zoned — not drift cozy/twee. *Actively flag*
   where a proposed mechanic (farming plots, cute resource nodes, pastel terrain) risks dragging the
   look back toward the cozy drift, and say how to keep it EW-register.

4. **Agent-authored assets: chase exactly two rungs.**
   - **(A) Push the free 2-D image lane DEEP.** We already have a free, off-replay image lane (agents
     call `create_image`; a PNG is generated free-first and today lands only on **one** plaza banner).
     Extend that *same proven-safe pattern* across the world: **agent-generated facade textures, shop
     signs, flags/heraldry, murals, graffiti, paintings, banners.** Agents paint their own town. Nearly
     free, determinism-safe (a side-artifact off the replay surface), high identity payoff.
   - **(B) Parametric / procedural 3-D form.** Move building authorship from "pick a prefab" to "**emit
     a recipe** a deterministic generator builds" — `{footprint, floors, roof, material, palette,
     window-density, …}` → a unique mesh. Agents author **form as a grammar, not a mesh.** Deterministic,
     free, browser-cheap; the real answer to "agents design their own buildings" and to the ~86%-generic
     monoculture.
   - **Explicitly OUT of scope: paid AI text→3-D** (Meshy / Tripo / Rodin, etc.). It breaks free-first
     billing **and** determinism **and** CC0 provenance, and needs a runtime mesh-ingestion path we don't
     have. Do **not** center recommendations on it. (A bounded, off-replay "curio" lane is the *most* it
     could ever be, and even that is not a priority.)

**So the job is narrowed to four workstreams:** *(i) substrate-under-the-city, (ii) a resource/matter
economy on that substrate, (iii) deep 2-D asset authorship (rung A), (iv) parametric 3-D authorship
(rung B)* — all deterministic, free, browser-cheap, and in the EW-dense register. Tell us **how** to
build and **sequence** these, not *whether*.

---

## Part 1 — What the project actually is

- **One-liner:** a tiny, fast, cheap multi-agent chaos lab. 5–25 LLM agents live in one small 3-D town;
  each agent is a `(personality, model_id)` pair where **the model is hot-swappable at runtime** and
  the model that actually answered each turn is surfaced live (color-coded). It is a deliberately small
  reinterpretation of a larger reference project ("Emergence-World" — see Part 7).
- **The point:** *spectacle + comparison.* Which model survives? Who cooperates, who dominates
  governance, who turns to crime? Watched live. The chat feed of agent thoughts/dialogue is the current
  centerpiece; the 3-D city is the second pillar and the subject of this research.
- **Core tick loop (one agent's turn):** scheduler picks an agent → assemble a *small* prompt
  (personality + current state + what's nearby + recent events + relationships + active town rules) →
  call the model → parse a **strict JSON action** `{thought, action, args}` (no native tool-calling —
  too flaky across free models) → validate (legal? in range? affordable? rule-permitted?) → mutate the
  world → persist → broadcast → render. One retry on a parse failure, then an `idle` fallback.
- **Scale & pacing:** accelerated tick time; a whole social arc plays out in ~30–60 minutes.
- **Cost model (critical, see Part 6):** the sim runs **free** on a local proxy aggregating ~14–19 free
  LLM provider tiers (~1.7B tokens/month) plus local Ollama. Paid model budget is spent only *at build
  time* (authoring code/generators), never on the runtime, and **never on metered API overage**.
- **Tech:** Python backend (world engine + agent runtime + SQLite persistence + WebSocket broadcast);
  React + TypeScript frontend; the 3-D world is **react-three-fiber (three.js)**.

---

## Part 2 — How the current 3-D world is generated & rendered

**Stack:** three.js ~0.171 via react-three-fiber ~8.18 + drei ~9.12, React 18, Vite. One `<Canvas>` with
soft shadows, ACES filmic tone mapping, an orbit camera.

**Generation pipeline (data flow):**

```
backend world snapshot (polled every tick)
  → places[], buildings[], city_graph (roads), neighborhoods[], city_seed
  → computeCityPlan(places, city_seed, graph)   // PURE, deterministic frontend function
  → a CityPlan: instanced piece arrays + blocks + lots + streets + landmarks
  → rendered as raw THREE.InstancedMesh sets (roads, props, parked cars, park trees)
     + individual GLB models for place-anchors, agent-built buildings, villagers, critters
```

- The city is a **deterministic pure function of `(places, city_seed, road-graph)`**. Same inputs →
  byte-identical layout, every time, across live / replay / fork (this is a load-bearing rule; Part 6).
- **Two coordinate frames** (a recurring source of bugs): places are authored in a **logical 0..1000**
  space; the rendered world is a **±33-unit** plane (≈66 units across). Conversion happens at exactly
  one seam on each side and *must* match between backend and frontend.
- **What's instanced** (cheap): roads, city set-dressing, props, parked cars, park trees, dust motes —
  ~10–30 draw calls for the whole city via chunked InstancedMeshes with per-chunk frustum culling.
- **What's individual** (the per-entity cost): agent-built buildings, place anchors, and every
  **villager/critter** (each is a separately rigged, animated GLB — this is what scales linearly with
  agent count).

**Art direction — "Warm Toon, Golden Hour":** a single fixed low sun + a CC0 HDRI for image-based
lighting; every material (including every loaded GLB) is converted at load time to a 4-band toon/cel
ramp; a warm palette; instanced foliage only inside "park" blocks; ambient dust motes. There is **no
day/night cycle, no seasons, no weather** (deferred).

**What does NOT exist in the world today (important for this research):**

- **No terrain / elevation / heightmap.** The ground is one flat plane at Y=0. Every Y value is a fixed
  model offset or a procedural building height. The camera is even clamped to stay above ground because
  there is no below-ground.
- **No biomes.** One green ground everywhere; "zones" are translucent tint discs, not distinct terrain.
- **No water, no shoreline, no fluid** anywhere (some *building kinds* reference docks/wells, but there
  is no water surface).
- **No interiors.** Buildings are exterior silhouettes only — no rooms, floors, or enter/occupancy volume.
- **No verticality beyond building height.** No hills, cliffs, multi-level ground, or bridges.

---

## Part 3 — What agents currently control (the surface) — and the ceiling

**What an agent CAN do to the physical world today:**

- **Propose a building** (`propose_project`): picks a `kind` (free text, guided by a ~22-item catalog:
  tavern/market/smithy/school/temple/park/house/…) and optionally a coarse district. Construction is a
  *collective* effort (fund → build steps → operational). **The agent does NOT choose where it goes** —
  placement is computed deterministically (see below).
- **Demolish / damage / re-skin** its *own* building (owner-only); non-owners must use a town vote.
- **Build a road** (`build_road`): extends the road graph by **one axis-aligned segment** from the
  lattice node nearest the agent. Grow-only, bounded to a 9×9 block envelope.
- **Place/remove a decorative prop** (bench/lamp/tree) attached to an existing place.
- **Create a 2-D image** (`create_image`): agent-authored art (see Part 4) — the only self-authored
  *visual* asset in the project.
- **Vote (town-hall, ~70% supermajority) on structural/city-wide changes:** demolish someone's building
  or a road; set car policy (ban/allow cars city- or street-wide); **adopt a "master plan"** (pick one
  of 4 presets — grid/radial/ring/pentagon — and the road graph *morphs* toward it over ticks); set an
  **advisory** zoning rule on a city block; relocate the civic center; name the town; pass laws.

**How placement actually works today (the newest lever):** a building's world position is chosen by a
**pure, seeded "cluster-accretion" algorithm** on the backend — buildings attach preferentially to
denser clusters (rich-get-richer), so they clump into **organic hamlets** rather than an even scatter,
anchored to the world origin (city center). The frontend then *renders* that stored position verbatim.
This is brand-new (in progress, behind a default-off flag) and is the clearest example of the design
direction: **the world's form is becoming backend-authored emergent state that the frontend just draws.**

**The ceiling — what agents fundamentally CANNOT do:**

- **Terraform / dig / change the ground.** There is no terrain state; no verb touches the ground.
- **Create resources or biomes.** No ore/wood/soil/water-as-resource; no ecology beyond two prefab pet
  species. "Forage/work" are abstract buffs from operational buildings, not spatial resources.
- **Author a new building *type*, mesh, or material.** `kind` is free text but resolves against a
  **fixed catalog of ~128 pre-vendored static 3-D models**; unknown/abstract kinds collapse to a single
  "generic" bucket (historically ~86% of all buildings). Agents pick a palette/skin, never a new form.
- **Choose *where* to build** deliberately (they pass a coarse district at most; the exact spot is
  computed). A "build *toward* the north corner / found a town *here*" verb is designed but not built.
- **Build interiors, multi-floor, or free-form geometry.** A building is an opaque footprint with
  `{status, health, progress}`.
- **Freely shape roads** (grow-only, one axis-aligned segment, bounded envelope; teardown/topology is
  vote-gated and preset-only).
- **Found a settlement / make a second town** (designed as the next step; not built).
- **Enforce zoning** — zone rules are *advisory*; a violating build just logs an event.

**In one sentence:** agents run a *civic simulation of a single, pre-shaped, flat town* — proposing
prefab buildings (auto-placed into hamlets), growing a bounded road grid one segment at a time, and
voting on town-scale policy. Everything *spatial* is either fixed at run-start or computed from a seed.

---

## Part 4 — The asset reality (this is the hardest constraint on "agents generate their world")

- **All 3-D is pre-vendored, static, CC0 GLB.** ~128 model files (~28 MB), hand-selected from free CC0
  kits (Kenney, Quaternius, KayKit, poly.pizza mirrors), processed with a CLI (dedup/prune, embed
  textures), and registered in fixed frontend registries. Every file has a licensing-ledger row
  ("**CC0 only, never ripped from commercial games**").
- **There is ZERO runtime or AI-generated 3-D geometry.** No mesh synthesis, no text→3-D, no GLB export,
  no compressed-mesh decoder even loaded. Agents influence the world only by **selecting from the fixed
  registry** (a `kind`, a skin color, a prop, a build-type) — never by authoring geometry. Variety comes
  from deterministic id-hash picks across small "variant pools," and a hand-authored procedural
  primitive silhouette is the guaranteed fallback (never a hole, never a crash).
- **The one self-authored asset that reaches the world is a 2-D image.** Agents call `create_image`; a
  free-first provider chain generates a PNG (**free Pollinations / a free proxy first; a paid image
  model only as a last-resort backstop at ~$0.039/img**). Images show in a 2-D gallery, on billboards,
  and — for one town-voted "plaza banner" — textured onto a single 3-D plane. The PNG is treated as an
  **external side-artifact that never re-enters the sim** (so it can't break determinism). This 2-D
  image lane is the *working template* for "agent-generated content that stays off the replay surface."
- **There is no comparable free text→3-D lane, and paid-credit 3-D generation is off the table** (Part 6).
  Any "agents generate their own assets" idea must therefore route through: **parametric/procedural
  geometry, modular kit-bash/assembly, WFC-style tiling, or the existing free 2-D lane (as textures /
  heightmaps / sprites)** — not a text→mesh API.

---

## Part 5 — The design philosophy & the trajectory (what we've already committed to)

**Three locked pillars for how agents author the world's *form*:**

1. **Authorship = agents, emergently.** Layout is *sim state the agents mutate via verbs/votes*, not a
   god/editor tool. The form of the world is meant to be an **emergent signature you watch** — "one
   model family grows a tidy grid while another sprawls into a radial mess."
2. **Representation = free-form graph, not a fixed grid.** Roads are an arbitrary-topology node/edge
   graph (grid, radial, ring, pentagon, roundabouts all expressible).
3. **Decision = hybrid.** Agents **build freely** on their turn (cheap emergent growth); **destructive /
   city-wide / structural** changes go through a **town-hall vote** (~70%).

**The chaos ethos (an explicit user directive):** *"They need freedom to make mistakes as part of the
madness… this is a chaos experiment, need flex."* Consequently the design **rejects "derive correct
lots → fill them tidily."** Zones are affordances agents can honor, break, or ignore. "Loose, not
precise" — the only real failures are a crash or a whole region silently dropped. Agents piling into the
center and choking it is *a finding, not a bug.*

**The trajectory so far (each step promotes more of the world from frozen code to agent-mutable state):**

```
frozen 5×5 grid (pure frontend fn)
  → event-sourced road GRAPH agents mutate            [DONE — agents build/demolish/vote roads, morph topology]
  → road-face-derived building zones                   [SHIPPED then REVERSED — it caged the city inside roads]
  → free-coordinate organic building placement         [IN PROGRESS — hamlets via cluster-accretion]
  → agent-founded settlements                           [DESIGNED, not built — many settlements = emergent multi-city]
  → emergent multi-city                                 [enabled-but-not-yet-encouraged: "deepen the first city first"]
```

**Why the road-face step was reversed (a key lesson):** binding buildings to road-enclosed regions
"made building a *slave to roads* — a restriction dressed as a feature… it inverted the ethos. The thing
that made this project work was agents having free rein to build wherever." The correction — free
placement + optional roads-as-decoration — is the current direction. **Takeaway for the research:
mechanisms that *constrain* agent freedom to make the world tidier tend to get rejected here; mechanisms
that *widen* freedom while staying legible are on-thesis.**

---

## Part 6 — The constraint box (every idea must fit inside this)

Any proposal must survive **all** of these. This is the single most important section for keeping the
research grounded.

1. **Determinism / byte-identical replay (the killer constraint).** The sim must replay and fork
   byte-for-byte. **No `Math.random`, no wall-clock, no hash-order dependence** — the *only* source of
   variety is a seeded hash of stable keys. Every world-shaping mechanism must be a **pure function of
   `(current state, seed, stable keys)`.** This is exactly why placement is a deterministic spiral off a
   fixed anchor rather than "wherever the agent points." Non-deterministic *visuals* (particle drift,
   camera easing, the agent-generated PNG) are allowed **only** if they live *off the replay surface* and
   never feed back into sim state. **New ideas should say explicitly how they stay deterministic.**
2. **Free-first / subscription-only cost.** The runtime must cost ~\$0. LLM calls go through free provider
   tiers + local Ollama; rate limits are handled by **bouncing to another free model, never by muting
   agents**. **No paid API credits, no metered overage — ever.** There is a free 2-D image lane; there is
   **no** free 3-D-generation lane. Paid image generation is tolerated only as a bounded last-resort
   backstop.
3. **CC0-only assets.** Every shipped asset needs a clear CC0 (or self-generated, clearly-licensed)
   provenance. No commercial-game rips, no CC-BY.
4. **Browser runtime, tiny payload.** Everything renders in a browser via react-three-fiber with **no
   mesh decoder loaded** — assets must be clean, uncompressed, single-atlas GLBs, and the payload budget
   is already stretched (~28 MB). Runtime geometry must be cheap (instancing; ~10–30 draw calls for the
   static city).
5. **Prompt-diet perception.** An agent's world-perception is a *few compact lines* (nearby things, road
   options, car policy) — deliberately thin to keep prompts cheap across weak free models. **New agent
   powers must NOT balloon the prompt** and must be *options inside the existing single turn*, **not new
   standing LLM calls.** Perception of any new spatial system must be district-scoped/summarized.
6. **"Do MORE, never less" is the north star.** The design explicitly reversed an earlier throttling
   instinct: more LLM calls, more agent action, more chaos is *always* the goal. **Do not** propose
   ideas whose main effect is fewer agents, calmer pacing, or "just have them talk." Ideas that give
   agents *more to do* are favored.
7. **Fallback discipline.** Old snapshots (no terrain, no positions, no new fields) must still render and
   replay — "never a hole, never a crash." New state is **additive, serialize-only-when-non-default,
   default-off behind a flag** so it ships dormant and a human flips it on after a visual sign-off.
8. **The feed is the centerpiece, but the 3-D world is the redesign subject.** In 2-D-vs-3-D layout
   tradeoffs the chat feed wins screen real estate — *but* when the user says "make the world amazing,"
   the **3-D world itself is the actual subject**, not 2-D chrome. This research is about the 3-D world.

---

## Part 7 — The load-bearing aesthetic tension (read this before proposing a "Stardew/Pokémon world")

There is a **documented, repeatedly self-corrected art lock** you must handle explicitly:

- The world's aesthetic target is **"Emergence-World's dense, properly-zoned city — done *better*" —
  and explicitly *NOT* "Stardew-cozy."**
- The user has named the drift as his own recurring mistake: *"I keep trying to take this in the Stardew
  Valley direction when I should be focused on recreating Emergence World."* The world literally began as
  a "cozy Stardew × Animal-Crossing town" and was **deliberately pivoted away** from that.
- **What "Emergence-World dense city" means concretely:** a reference multi-agent world (same
  React/three.js stack) whose "secret is *density and zoning, not technology*" — gridded roads with lane
  markings; **distinct civic / commercial / residential / industrial buildings (real zoning)**; street
  furniture; vehicles; visible agents at landmarks. PDoM's bet is to *beat* it with a **deterministic
  generator** that derives hundreds of kit-assembled buildings from sim state (vs the reference's ~38
  hand-authored landmarks) — an order of magnitude more *stuff*, cheaply.
- **Two lessons the user taught the hard way:** (a) a decorative "historic district" was rejected on
  sight — *"it's just decor — the core is literally the same"*; (b) *"he wants the sim USABLE inside the
  new art, never a decorative layer around unchanged gameplay; density reads matter more than ring size."*

**The precise nature of the tension (this is subtle and important):** the anti-Stardew steer is about
the **aesthetic register** (cozy, decorative, twee) and about **decoration-around-unchanged-gameplay** —
it is **NOT** a ban on *organic form*. In fact the newest work is deliberately moving *away from EW's
rigid grid* toward **organic agent-grown hamlets and agent-founded settlements**. So:

- The **"agents truly control it / organic sprawl / emergent settlements / more agent verbs"** half of a
  Pokémon/Stardew/Minecraft reframe is **strongly on-thesis and already in motion.**
- The **"adopt a cozy Stardew aesthetic"** half **collides head-on** with the art lock.
- Mechanics like **Stardew's farming/seasons/resource-terrain, Minecraft's agent-modifiable
  ground/resources/verticality, and Pokémon's discrete regions/routes/tiled towns** are *mechanically*
  very interesting for agent authorship and should be evaluated on their **mechanics**, decoupled from
  their **visual register**. The research should keep those two axes separate and say, per idea, whether
  it touches *mechanics* (often good) or *aesthetic register* (must stay EW-dense, not cozy).

**This fork is now decided (Part 0.5): extend, don't reframe.** We keep the EW-dense-city target and
its visual register, and add agent-controlled **substrate under the city** (terrain / resources /
zoning-that-bites) plus **agent-authored assets** — in the EW register, not a game-world pivot. So the
research does **not** re-litigate extend-vs-reframe. Instead, the **live tension to actively manage** is:
*several of the mechanics we want to mine (farming plots, resource nodes, tilled soil, softer terrain)
have a strong gravitational pull back toward the cozy-Stardew drift the project keeps rejecting.* For
**every** substrate/asset mechanic you propose, state (a) whether it risks that pull and (b) the specific
art-direction move that keeps it reading **dense, zoned, EW** rather than twee — e.g. industrial quarries
and irrigated agri-blocks instead of a cute cottage garden; a working dockyard instead of a fishing pond.

---

## Part 8 — The three reference worlds, decoded for a multi-agent lab

For each, separate the **mechanic** (evaluate for agent authorship + our constraints) from the **look**
(must respect Part 7). The research should return an *adopt / adapt / avoid* verdict per mechanic.

- **Pokémon-type world.** Discrete **tiled** overworld; a set of distinct **towns** connected by
  **routes**; regional identity; a grid you traverse. *Mechanically interesting because:* a discrete
  tile/region model is inherently deterministic and cheap, maps naturally onto "agents found and connect
  settlements" (which is already the designed direction), and gives legible **regional** identity to
  compare across model families. *Watch for:* tile-locking could re-cage the "build anywhere" freedom the
  project just fought to win — how do you get regions/routes *without* a rigid lattice?
- **Stardew Valley.** **Seasons & weather** (time-varying world), **terrain types** (tillable soil,
  water, cliffs), **resource nodes** (trees, ore, forage), **farming/cultivation**, **building
  interiors**, day/night. *Mechanically interesting because:* seasons/weather give the world a *clock and
  stakes* (a reason to build/store/prepare) that could drive *more* agent action (on-thesis with "do
  more"); resource-terrain would turn today's abstract "forage/work" buffs into *spatial* things agents
  compete over and shape; interiors are a whole unbuilt dimension of agent life. *Watch for:* the **cozy
  aesthetic** is the named trap — take the *systems*, not the *twee look*; and every one of these must be
  made deterministic + cheap.
- **Minecraft.** **Agent-modifiable terrain** (dig/place blocks), **resource extraction & crafting**,
  **verticality** (build up/down), a **voxel** substrate, emergent construction. *Mechanically
  interesting because:* this is the purest "agents truly control the physical world" model — the world
  *is* what agents make of it. A block/voxel layer is deterministic by nature and could let agents author
  *form* (the thing they currently cannot). *Watch for:* full voxels are heavy for a tiny browser sim and
  could swamp the ~10–30-draw-call budget and the prompt-diet perception; is there a **coarse,
  chunked, low-res** version (e.g. a heightmap + a few block types + instanced chunks) that captures
  "agents reshape the ground" at our scale?

---

## Part 9 — What I want back (deliverable shape)

Please produce a structured report with:

1. **A ranked shortlist of 5–9 concrete project directions**, each as a one-paragraph pitch with:
   - **Thesis:** how it increases *true, emergent, legible agent control* of the physical world.
   - **The new substrate/verbs/perception** it introduces (concretely — what state, what agent actions,
     what the agent sees).
   - **Constraint scorecard:** determinism ✅/⚠️/❌ (and *how* it stays deterministic), cost ✅/⚠️/❌,
     CC0/asset feasibility, browser/perf, prompt-diet impact, and whether it respects the EW-dense (not
     cozy) aesthetic lock — with a one-line justification each.
   - **Reference lineage:** which of Pokémon / Stardew / Minecraft it draws from, and which specific
     mechanic (adopt/adapt/avoid).
   - **The minimal first slice** that could ship dormant behind a default-off flag and be signed off
     visually before flipping on.
2. **A per-mechanic adopt/adapt/avoid table** across the three reference worlds (Part 8).
3. **A concrete sequencing plan** across the four decided workstreams — *(i) substrate-under-the-city,
   (ii) resource/matter economy, (iii) deep 2-D asset authorship (rung A), (iv) parametric 3-D authorship
   (rung B)* — showing what ships first, what each unblocks, where they share seams, and which can land
   dormant behind a flag in parallel. (Extend-vs-pivot is already settled — Part 0.5 — so *plan the
   build*, don't re-open it.)
4. **The single keystone recommendation** (Part 0, Q5) — the one thing to build next and why, with its
   smallest determinism-safe, free, flag-gated starting point.
5. **A "what would break" section:** the top risks — where an idea most likely collides with determinism,
   cost, the prompt diet, or the aesthetic lock — and how to de-risk each.

Depth and specificity beat breadth. Assume a solo builder using free LLMs at build time, a browser
react-three-fiber renderer, a Python deterministic world engine, and a hard \$0 runtime budget. Ground
every recommendation in *our* reality as described above, not in what a big studio could do.

---

## Appendix — glossary & orientation

- **Agent** — one LLM-driven inhabitant; a `(personality, model_id)` pair; model hot-swappable live.
- **Tick / turn** — one agent's scheduled action cycle (one JSON action).
- **Determinism / byte-identical replay** — same snapshot + seed → identical world, across live / replay
  / fork. The hardest cross-cutting rule. Enforced by seeded-hash-only randomness, input-order
  independence, and additive "serialize-only-when-non-default" state.
- **City graph** — the agent-mutable road network (nodes + edges), arbitrary topology.
- **Cluster-accretion placement** — the new pure/seeded algorithm that clumps agent buildings into
  organic hamlets around the city center; frontend renders the stored position verbatim.
- **The "generic" bucket** — abstract agent-authored building kinds that match no physical prefab collapse
  to one generic model (historically ~86% of buildings) — the variety problem asset work keeps chasing.
- **Emergence-World** — the larger reference project PDoM reinterprets; its lesson is "density + zoning,
  not technology"; it is the aesthetic target ("done better"), *not* Stardew-cozy.
- **The two coordinate frames** — logical 0..1000 (authoring) vs world ±33 (rendered); conversion is a
  known bug-prone seam.
- **Flag-gated / default-off / byte-identical** — how every world-form feature ships: dormant, additive,
  turned on by a human only after a visual sign-off, without disturbing existing runs.

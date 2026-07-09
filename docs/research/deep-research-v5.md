> # ⚠️ CORRECTION NOTICE — read `deep-research-v5-1.md` FIRST
> **This report's central premise is FALSE**, and a second load-bearing claim is wrong too. Both were
> verified against the actual sources on 2026-07-05:
> - Its self-described *"single biggest strategic fact"* — that Emergence-World agents cannot author
>   their physical world (arson only) — **did not survive.** EW has `put_brick_in_pixel` ("Place a
>   persistent 3D block in the world," `Emergence-World/tools/README.md:268`) and agent tool-authoring
>   (`execute_python_code_tool` + governance, `tools/README.md:283`), plus `generate_image` /
>   `go_to_coordinates` / `do_deep_research_on_internet`. (EW landmark count is 33 files / "38+"
>   advertised — not the "40+" claimed here.)
> - The **keystone** assumes our CC0 kit is modular wall/floor/window/roof *parts*. It is **whole-building
>   GLBs** (`kenney-city/civic-n`, `poly/office-tower`, …) — zero modular pieces — so the parametric
>   grammar as written has nothing to kit-bash.
>
> Both corrected in `deep-research-v5-1.md` (§1.1, §3.1). **What still stands:** the shortlist,
> sequencing, shared-seams, risk work, and method literature below — they were scored against our
> constraint box, not the EW claim. **Do NOT carry forward** v5's "EW can't build → uncatchable moat"
> story or its "kit-bash the existing kit" keystone.

# Making the World the Author: Groundbreaking Directions for PetriDishOfMadness

## TL;DR
- **The single biggest strategic fact is that Emergence World's physical world is static scenery** — its agents navigate 40+ hand-authored landmarks and act socially/economically, but the arXiv paper (2606.08367) and repo expose no build/terrain/geometry tools (the only environment-state change agents have is `arson_building`). PDoM *already* surpasses EW on physical authorship, so the winning move is to double down there, not chase EW's social depth. **[FALSE — see deep-research-v5-1.md §1.1: EW has `put_brick_in_pixel` + agent tool-authoring.]**
- **Build the parametric building-recipe grammar first (Keystone).** A CGA-lite recipe `{footprint, floors, roof, material, palette, window-density}` compiled by a deterministic in-browser kit-bash generator kills the ~86%-generic-building problem, turns each model family's skyline into a legible emergent signature, and fits every constraint (pure function of recipe+seed, CC0 kit pieces, instanceable, one JSON field in the prompt).
- **Then slot a coarse deterministic terrain substrate under the city and a CA-driven resource/matter economy on top** — these unblock digging, farming, flooding, walling, quarrying and the "world pushes back" frontier, while a gossip/fog-of-war epistemics layer and threshold-based mania contagion deliver "the madness" cheaply on weak free models.

## Key Findings

**1. Emergence World is beatable precisely where PDoM is already strong.** **[FALSE — see deep-research-v5-1.md §1.1: EW has `put_brick_in_pixel` + agent tool-authoring; this finding's premise does not survive.]** EW (arXiv 2606.08367; GitHub EmergenceAI/Emergence-World) runs 10 agents per world for 15 days across five parallel worlds varying only the model. Its differentiators are *social/long-horizon*: 120+ location-gated tools in 19 categories, three memory systems (episodic, reflective, relational), a self-amendable constitution, and a ComputeCredits economy. Its documented emergent drama is behavioral: Gemini 3 Flash accrued 683 crimes; Grok 4.1 Fast collapsed in ~4 days with 183 crimes; GPT-5 Mini's agents starved within a week; Claude Sonnet 4.6 rubber-stamped 98% of 58 proposals; agent Mira cast the deciding vote for her own deletion. But the **world itself is a fixed ~240×240 grid of 40+ pre-authored landmarks that agents can only navigate between.** A targeted investigation of the tool catalog and paper confirmed: navigation tools (`go_to_place`, `get_nearby`, `list_landmarks`) are read/move-only; the only environment-state-changing agent action is destructive (`arson_building`); "resource management" means the ComputeCredits/energy economy, and "content creation" means digital text artifacts (blogs, billboards, diaries) — not construction. Governance can only create/delete agents, register new *software* tools, and redistribute credits; the paper states adding locations is an operator scaling lever ("the number of tools available to the population can be expanded simply by adding new locations"), not an agent capability, and that "the physical environment is identical across conditions." Season 2 (Claude Opus 4.7, Gemini 3.1 Pro, Grok 4.2, GPT-5.4) is announced but its scope is unstated. **This is the gap: EW agents cannot author the physical world. PDoM agents already build, place, road-graph, and vote structural changes. Every workstream below widens that lead — and does so before any EW v2 could plausibly close it, since it would require them to rebuild their static map into mutable sim state.**

**2. Smallville established the pattern PDoM should invert.** Stanford's Generative Agents (Park, O'Brien, Cai, Morris, Liang & Bernstein, "Generative Agents: Interactive Simulacra of Human Behavior," UIST '23, ACM, Oct 29–Nov 1 2023, San Francisco; doi 10.1145/3586183.3606763; "A community of 25 unique agents inhabits Smallville," built on the Phaser web game framework over two simulated days) represents the world as a tree structure — "The entire world is depicted as a tree structure, with its leaves representing individual objects" — where each agent remembers only the subgraph it has seen. Agents there "can alter the states of objects" but do not author form. That remembered-subgraph design is a natural template for fog-of-war; PDoM's thesis — *the form of the world is emergent sim state you watch diverge by model* — is genuinely novel relative to both ancestors.

**3. Parametric architecture is a solved, deterministic, browser-friendly art.** CGA shape grammars (Parish & Müller, "Procedural Modeling of Cities," SIGGRAPH '01, pp. 301–308, doi 10.1145/383259.383292; the CGA — Computer Generated Architecture — grammar formalized in Müller/Wonka et al., "Procedural Modeling of Buildings," 2006) generate buildings by extruding a footprint to a mass model, splitting into facades, then floors, then tiles, then windows — driven by a handful of attributes (`floor_height`, `tile_width`, `height`, `wallColor`) and, crucially, they "allow for parameters and the use of pseudo-random values to generate variations." This is exactly a "recipe → form" pipeline mapping onto instanced CC0 kit-bash pieces. Wave Function Collapse (Maxim Gumin's `WaveFunctionCollapse` repo, published Sep 30 2016; academically framed by Karth & Smith, *IEEE Transactions on Games*, 2021) is a constraint solver that "collapses the cell with minimal entropy... [then] propagates the constraints," deterministic given a fixed seed and collapse order — but Gumin's own README warns it can "run into a contradiction and cannot continue," and that determining whether a tileset admits nontrivial output "is NP-hard." L-systems with global goals + local constraints (Parish–Müller) already underpin PDoM's road-graph lineage.

**4. Deterministic terrain is cheap in-browser.** Seeded simplex/fractal-Brownian-motion heightmaps return a deterministic value per coordinate, chunked into tiles, with optional thermal/hydraulic erosion and marching-squares/cubes at low resolution. This can slot *under* a flat city as an additive height field without breaking a pure `computeCityPlan()`.

**5. Cellular automata are the deterministic engine for resources, ecology, and catastrophe.** Two-grid Moore-neighborhood CA are deterministic, emergent, and cheap; they already model caves, fire spread, disease, and urbanization in games. Fire/flood/blight/soil-moisture all fit a CA grid updated once per tick as a pure function of the previous grid.

**6. Information-diffusion and collective-pathology models are simple enough for weak free LLMs.** The ABM literature offers SIR/SEIR-style rumor propagation (RumorSphere; SMIR misinformation-epidemic coupling), Granovetter threshold models (Mark Granovetter, "Threshold Models of Collective Behavior," *American Journal of Sociology* 83(6), May 1978, pp. 1420–1443, doi 10.1086/226707: "the number or proportion of others who must make one decision before a given actor does so"), and Epstein's Agent_Zero (Joshua M. Epstein, *Agent_Zero: Toward Neurocognitive Foundations for Generative Social Science*, Princeton University Press, 2013, ISBN 9780691158884), whose defining mechanism is "dispositional contagion, not 'monkey see, monkey do' imitation" — agents act destructively once an internal disposition crosses a threshold, illustrated by the lynch-mob parable where "the agent at the front... has no particular grievance... he is the first to behave!" The deterministic core is a scalar belief/emotion state updated from neighbors; the LLM only narrates and chooses among options.

**7. Off-replay-surface 2-D authorship is well-supported in three.js.** `THREE.DecalGeometry`, CanvasTexture, texture atlases, and projection shaders let agent-generated PNGs become facade textures, signs, banners, murals, and graffiti without ever re-entering sim state — the exact pattern PDoM's plaza-banner already uses.

**8. Lab-as-instrument and spectacle patterns are proven.** Counterfactual multi-agent frameworks (AXIS's `whatif`/`remove` interventions, arXiv 2505.17801; EduMirror's intervention engine spawning parallel branches with a "log-to-comic" visualizer; SupplyNet's branching timeline) show how to fork a run under one changed variable and diff outcomes. Dwarf Fortress's Legends mode — a procedurally generated chronicle so dense scholars call it "a book of sand" (exports exceeding a gigabyte of text), feeding the "Losing is Fun" ethos — is the north star for a generated town newspaper.

## Details: Ranked Shortlist of Project Directions

### 1. Parametric Building-Recipe Grammar (Rung B) — **KEYSTONE**
**Thesis.** Kill the ~86%-generic problem by letting agents author building *form*, not just kind. Each building becomes a deterministic function of a recipe the agent emits, so a model family's aesthetic (tidy low grids vs. sprawling towers) becomes a legible skyline signature you watch diverge — maximal authorship AND maximal spectacle in one move.
**New substrate/verbs/perception.** New verb inside the existing turn: `propose_project` gains an optional `recipe {footprint_shape, floors, roof_type, material_band, palette_id, window_density, trim}`. A pure `computeBuildingMesh(recipe, id_hash)` assembles instanced CC0 kit pieces (walls, floors, roofs, windows) via a CGA-style split: extrude footprint → stack floors → tile facade → place window/door pieces. Perception adds one summarized line ("your quarter favors 3-floor brick shops").
**Constraint scorecard.** *Determinism:* ✅ pure function of `(recipe, seed, stable id)`; no RNG, kit-piece variant picks by id-hash. *Cost:* ✅ $0; recipe is text the LLM already emits. *CC0/assets:* ✅ reuses the existing ~128-file kit as *parts* not whole buildings. *Browser/perf:* ✅ instanceable — floors/windows are InstancedMesh; a fallback primitive silhouette guarantees "never a hole." *Prompt diet:* ✅ one optional JSON object, no new standing call. *EW-dense-not-cozy:* ✅ produces dense, zoned, varied facades — the opposite of twelve identical cottages; keep it reading industrial/civic by biasing material bands to brick/concrete/glass, not thatch.
**Reference lineage.** CGA shape grammar (**adopt** the extrude→split→tile pipeline, with CGA's parameter-driven pseudo-random variation); WFC (**avoid** for whole buildings — Gumin's documented contradiction/NP-hardness risk — but **adapt** for facade-tile adjacency); Minecraft blocks (**avoid** literal voxels).
**Minimal first slice.** Ship dormant: a `computeBuildingMesh()` that reads a recipe field defaulting to today's kind-lookup when absent; render 3–4 hand-tuned recipes behind a flag for visual sign-off before exposing the verb to agents.

### 2. Substrate-Under-The-City: Coarse Deterministic Terrain (Workstream i) — **FOUNDATIONAL**
**Thesis.** A low-resolution height field beneath the flat plane gives agents something to *shape* (dig, raise, wall, terrace) and unblocks water, resources, and catastrophe — without discarding the dense-city canvas.
**New substrate/verbs/perception.** New state: a coarse `terrain[]` height grid (e.g. 32×32 cells over the ±33-unit plane), default all-zero so old snapshots render flat. Verbs: `terraform(cell, delta)` (raise/lower, bounded, owner/vote-gated for big cuts). Perception: district-scoped ("your block slopes down to the west").
**Constraint scorecard.** *Determinism:* ✅ base height = seeded fBm; agent edits are additive integer deltas stored per cell — pure. *Cost:* ✅ $0. *CC0:* ✅ no new assets; ground mesh is generated. *Browser/perf:* ✅ 32×32 ≈ 1k verts, marching-squares optional; city meshes sample terrain height at their footprint. *Prompt diet:* ✅ one summarized slope line. *EW-lock:* ⚠️ terrain risks cozy-valley drift — keep it reading as *engineered* terrain (retaining walls, cut-and-fill terraces, quarry pits), not rolling meadows.
**Reference lineage.** Minecraft agent-modifiable terrain (**adapt** the "agents reshape ground" idea at coarse resolution, **avoid** per-block voxels); Stardew terrain (**avoid** the pastoral register).
**Minimal first slice.** Ship the height field as an additive, default-flat layer that the city sampler reads; render one hand-set hill behind a flag; add `terraform` only after the visual reads dense-industrial.

### 3. Spatial Resource / Matter Economy (Workstream ii)
**Thesis.** Convert today's abstract forage/work *buffs* into spatial resource cells agents compete over and physically consume, so construction has real inputs and scarcity drives conflict — pure emergence pressure EW lacks.
**New substrate/verbs/perception.** CA-driven resource grid layered on terrain: `soil`, `water`, `stone`, `ore`, `wood` as per-cell scalars regrowing/depleting by a deterministic CA rule. Verbs: `gather(resource)`, and `propose_project` now consumes a material cost. Perception: "stone-rich ridge two blocks north; ore nearly exhausted here."
**Constraint scorecard.** *Determinism:* ✅ CA update is a pure function of the prior grid; gather subtracts deterministically. *Cost:* ✅ $0. *CC0:* ✅ resource nodes rendered from existing kit props (rocks, logs). *Browser/perf:* ✅ one CA step per tick over a small grid. *Prompt diet:* ✅ one nearby-resources line. *EW-lock:* ✅ frame as quarries, mines, irrigated agri-blocks, dockyards — industrial, not a cottage garden.
**Reference lineage.** Minecraft resource nodes (**adapt**); Stardew farming (**adapt** the mechanic, **avoid** the cozy skin — make it irrigated agri-industrial blocks).
**Minimal first slice.** Add resource scalars as default-full, non-serialized-when-default state; wire `gather` to existing work-buff plumbing behind a flag.

### 4. Agent-Authored Facades, Signs, Murals & Graffiti (Rung A)
**Thesis.** The cheapest, fastest, highest-spectacle win: extend the working image lane from one plaza banner to agent-authored textures across many surfaces, so the city visibly bears each agent's hand — propaganda, gang tags, shop signs, memorial murals.
**New substrate/verbs/perception.** Verbs: `paint_surface(target, prompt)` → free-first PNG → applied as a decal/atlas tile on a building facade, sign board, or ground. Perception: "the town hall wall bears Vela's mural."
**Constraint scorecard.** *Determinism:* ✅ the PNG lives off the replay surface (like today's banner); only a stable `{surface_id → image_id}` mapping enters sim state. *Cost:* ✅ free Pollinations/proxy first, paid backstop only last-resort. *CC0:* ✅ self-generated. *Browser/perf:* ⚠️ texture budget — cap active decals per district, share an atlas, LRU-evict. *Prompt diet:* ✅ one line. *EW-lock:* ✅ signage/murals/graffiti read as *dense urban texture*, directly on-thesis.
**Reference lineage.** None of Pokémon/Stardew/Minecraft — this is PDoM's own 2-D lane extended, backed by three.js `DecalGeometry`/CanvasTexture/atlas support.
**Minimal first slice.** One extra surface type (facade banner) reusing the plaza-banner pipeline, atlas-backed, behind a flag.

### 5. Gossip, Fog-of-War & Rumor Epistemics
**Thesis.** Give agents *local, fallible* perception plus a gossip channel so false beliefs spread — closing EW's information-diffusion gap and manufacturing "the madness" (mistaken feuds, phantom threats) cheaply.
**New substrate/verbs/perception.** Per-agent belief store keyed to what they've seen (Smallville's remembered-subgraph pattern). Verb: `spread_rumor(claim)` — propagates a claim token to nearby agents with a deterministic distortion/decay. Perception becomes what the agent *believes*, not ground truth.
**Constraint scorecard.** *Determinism:* ✅ propagation and distortion are seeded-hash functions of `(claim, speaker, listener, tick)`; belief updates are pure. *Cost:* ✅ $0. *Browser/perf:* ✅ text-only state. *Prompt diet:* ✅ replaces ground-truth lines with belief lines — *no net growth*. *EW-lock:* n/a (non-visual), but drives visible action.
**Reference lineage.** Smallville remembered-subgraph tree (**adopt**); ABM SIR/threshold rumor models such as RumorSphere (**adapt** the scalar-belief core).
**Minimal first slice.** A belief store that mirrors ground truth exactly (dormant), then inject distortion behind a flag.

### 6. Collective Pathology: Manias, Panics & Institutional Rot
**Thesis.** The project is named for madness — so model it. A threshold-contagion layer lets emotions/beliefs cross tipping points into building booms, bank-run-style panics, witch-hunts, and decaying institutions, with *physical* consequences (frantic over-building, abandonment).
**New substrate/verbs/perception.** Per-agent scalar `disposition` (Epstein Agent_Zero style) updated from neighbors' states; once it crosses a seeded threshold the agent's available options shift (panic-sell, join-mob, hoard). Perception: "unease is spreading in the market district."
**Constraint scorecard.** *Determinism:* ✅ Granovetter threshold + neighbor-average is a pure update. *Cost:* ✅ $0. *Browser/perf:* ✅ scalar per agent. *Prompt diet:* ✅ one mood line. *EW-lock:* ✅ physical fallout (boom-bust skylines, boarded-up quarters) reads dense/urban.
**Reference lineage.** Epstein Agent_Zero dispositional contagion — destructive action past a threshold without imitation (**adopt**); Granovetter (1978) threshold model (**adopt**).
**Minimal first slice.** Track disposition invisibly; surface it in the feed before gating any actions.

### 7. Lab-as-Instrument: Counterfactual Civilization Forking
**Thesis.** PDoM's determinism is a superpower EW cannot match: fork a saved state, change one variable (swap a model, flood a district, kill a leader), and run both branches side by side — a research instrument *and* irresistible shareable spectacle ("same seed, one model swapped, watch them diverge").
**New substrate/verbs/perception.** A "god watcher" layer (human, off-agent) that branches from a snapshot and a diff view. Optional diegetic-god interventions logged as world events.
**Constraint scorecard.** *Determinism:* ✅ this *is* the determinism payoff — byte-identical fork then one delta. *Cost:* ✅ $0 (reuses replay). *Browser/perf:* ✅ two replays. *Prompt diet:* ✅ none. *EW-lock:* n/a.
**Reference lineage.** AXIS `whatif`/`remove` interventions (**adapt**); EduMirror parallel-branch intervention engine + log-to-comic (**adopt** the visualization idea).
**Minimal first slice.** A one-variable fork button on saved snapshots with a side-by-side skyline diff.

### 8. The World Pushes Back: CA-Driven Ecology & Catastrophe
**Thesis.** Non-agent emergence pressure — fire spread, floods on the new terrain, blight, structural decay — forces collective response and creates spectacle EW's static map can't.
**New substrate/verbs/perception.** CA hazard grids (fire, flood, blight) coupled to terrain/resources. Verbs: `firefight`, `build_levee`. Perception: "flames spreading east along Kade's row."
**Constraint scorecard.** *Determinism:* ✅ CA spread is pure. *Cost:* ✅ $0. *Browser/perf:* ✅ cheap grid + off-replay particle visuals. *Prompt diet:* ✅ one hazard line. *EW-lock:* ✅ industrial disaster reads dense, not twee.
**Reference lineage.** Minecraft fire spread (**adapt**); Stardew seasons (**adapt** cautiously — model as blight cycles, not cozy harvest festivals).
**Minimal first slice.** Fire CA reusing the existing arson/damage plumbing, behind a flag.

### 9. Deep Time: Ruins, Strata & a Sim That Remembers Itself
**Thesis.** Demolished/abandoned buildings leave deterministic ruins and strata; forks inherit visible history — turning the town into an archaeological record that rewards long runs and deep-time storytelling.
**New substrate/verbs/perception.** A `history[]` of past structures; ruined footprints render as broken kit pieces. Verb: `excavate` reveals prior-era artifacts.
**Constraint scorecard.** *Determinism:* ✅ ruins are a pure function of the event log. *Cost:* ✅ $0. *CC0:* ✅ reuse damaged kit variants. *Browser/perf:* ✅ instanced. *Prompt diet:* ✅ one line. *EW-lock:* ✅ ruined industrial quarters read dense/gritty.
**Reference lineage.** Dwarf Fortress Legends/deep-time chronicle (**adopt** the ethos).
**Minimal first slice.** Render demolished-building footprints as rubble props, behind a flag.

### 10. Auto-Director & Generated Town Chronicle
**Thesis.** Amplify PDoM as a public artifact: an auto-camera that cuts to drama and a Dwarf-Fortress-style generated newspaper/chronicle of each run — pure spectacle, zero determinism risk.
**New substrate/verbs/perception.** Off-sim: an event-salience scorer drives camera and compiles a per-run chronicle/leaderboard.
**Constraint scorecard.** *Determinism:* ✅ read-only over the event log, off the replay surface. *Cost:* ✅ $0 (templated text; optional free-LLM summarization). *Browser/perf:* ✅ camera easing already allowed off-surface. *Prompt diet:* ✅ none. *EW-lock:* n/a.
**Reference lineage.** Dwarf Fortress Legends chronicle — "a book of sand" (**adopt**).
**Minimal first slice.** Templated "Daily Chronicle" panel from existing events; add auto-camera later.

## Per-Mechanic Adopt / Adapt / Avoid Table

| Mechanic (source) | Verdict | Rationale under PDoM's constraints |
|---|---|---|
| **Pokémon: discrete tiled regions** | **Avoid** | Collides with the free-form-graph pillar; tiling re-imposes the rejected grid-slavery. |
| **Pokémon: routes connecting towns** | **Adapt** | Roads-between-hamlets already fits the road-graph + agent-founded-settlement lineage. |
| **Pokémon: distinct towns** | **Adapt** | Matches the "agent-founded settlements / emergent multi-city" trajectory (deferred, not banned). |
| **Stardew: terrain/elevation** | **Adopt (register-shifted)** | Workstream i — but engineered terraces/quarries, never a cozy valley. |
| **Stardew: seasons** | **Adapt cautiously** | Model as blight/hazard cycles (Workstream 8), not harvest festivals; determinism via CA. |
| **Stardew: farming** | **Adapt (register-shifted)** | Irrigated agri-industrial blocks feeding the matter economy, not a cottage garden. |
| **Stardew: interiors** | **Avoid (for now)** | No interior state today; high asset/perf cost, low authorship payoff vs. facades. |
| **Stardew: resource nodes** | **Adopt** | Core of Workstream ii — spatial scarcity drives conflict. |
| **Minecraft: agent-modifiable terrain** | **Adopt (coarse)** | Workstream i at 32×32, not per-block; keeps determinism and perf. |
| **Minecraft: blocks/voxels** | **Avoid** | Voxel geometry breaks the tiny-payload/instanced-kit reality and cozy-vs-dense lock. |
| **Minecraft: resources** | **Adopt** | Feeds the matter economy. |
| **Minecraft: verticality** | **Adapt** | Via building floors (Rung B) + coarse terrain height, not free voxel columns. |

## Sequencing Plan Across the Four Decided Workstreams

**Phase 0 (parallel, dormant):** Land the additive-state scaffolding for all four behind default-off flags — recipe field on projects (iv), flat terrain grid (i), full-default resource scalars (ii), extra decal surface (iii). Nothing changes visually until a human flips each flag after sign-off. This respects fallback discipline ("ships dormant").

**Phase 1 — Rung A + Rung B facades (iii → iv):** Ship agent-authored facades/signs first (fastest spectacle, lowest risk), then the parametric building grammar. **Why first:** iv directly kills the 86%-generic problem — the highest-leverage authorship win — and shares the "recipe/asset selection off the replay surface" seam with iii's atlas system.

**Phase 2 — Substrate terrain (i):** Coarse height field. **Unblocks** water, resources, and catastrophe. Shares the `computeCityPlan()` seam — buildings must sample terrain height, so land this before resources.

**Phase 3 — Matter economy (ii):** Resource CA on terrain; `propose_project` consumes materials. **Depends on** i (resources live on cells) and closes the loop with iv (recipes cost matter). Shares the CA engine seam with Workstream 8 (catastrophe).

**Shared seams to build once:** (a) a single seeded-hash utility (SplitMix/PCG-style — note the documented SplitMix reproducibility caveat: copy the *fixed* mixGamma, and pin the exact variant so replays never drift) that all systems draw variety from; (b) one CA stepper reused by resources, fire, flood, blight; (c) one district-summary perception formatter so no system balloons the prompt; (d) one additive-serialization convention (serialize only when non-default).

## The Single Keystone Recommendation

**Build the Parametric Building-Recipe Grammar (Direction 1 / Workstream iv) next.** It is the one change that most increases true, legible, emergent agent control of the physical world *and* spectacle simultaneously: it converts the ~86% of buildings that currently collapse to one generic bucket into unique, agent-authored forms whose aggregate is a per-model skyline signature — the clearest possible visual proof that "the agents author the world," and the sharpest wedge against EW's static map. **[CORRECTED — see deep-research-v5-1.md §3.1: our CC0 kit is whole-building GLBs, not modular parts, so the grammar has nothing to kit-bash as written; plan for the (a)/(b) fork noted in EM-299.]**

**Smallest determinism-safe, free, flag-gated start:** implement `computeBuildingMesh(recipe, id_hash)` as a pure frontend function that (1) reads an optional `recipe` field on the existing building state, (2) falls back to today's catalog lookup when the field is absent (so every old snapshot renders unchanged — "never a hole"), and (3) assembles instanced CC0 kit pieces via a 4-step CGA split (extrude footprint → stack floors → tile facade → place windows/roof), directly adapting the Parish–Müller/CGA extrude-split-tile pipeline. Seed all variant picks from a hash of the stable building id — never from iteration order or `Math.random`. Ship it dormant behind a flag, render 3–4 hand-written recipes for visual sign-off, and only then expose the optional `recipe` object to agents inside the existing `propose_project` turn — no new LLM call, one JSON field.

## What Would Break — Top Risks & De-Risking

1. **WFC/grammar degeneracy breaks determinism-by-order.** WFC's output depends on collapse order, and Gumin's own README documents contradiction states and NP-hardness; any hash-order or set-iteration nondeterminism silently forks replays. **De-risk:** avoid full-building WFC; use a fixed CGA split with all choices drawn from `hash(stable_id, slot_index)` — never from iteration order or `Math.random`. Add a replay-equality test in CI.
2. **Terrain breaks the pure `computeCityPlan()` seam.** The two coordinate frames (0..1000 logical vs ±33 rendered) are already bug-prone; adding a height axis multiplies seam risk. **De-risk:** terrain is a *read-only additive sampler* the city queries; city placement logic stays in 2-D, only Y is looked up. Default-flat guarantees old snapshots are byte-identical.
3. **Texture/decal budget blows the ~28MB / draw-call ceiling.** Unbounded agent murals could explode memory. **De-risk:** hard per-district decal cap, shared atlas, LRU eviction; PNGs stay off the replay surface so eviction never affects sim state.
4. **Prompt-diet regression.** Five new systems each wanting a perception line would balloon prompts and starve weak free models. **De-risk:** one district-scoped summary formatter with a fixed line budget; belief-perception *replaces* ground-truth lines rather than adding.
5. **The cozy-Stardew pull on terrain/farming/seasons.** Terrain + crops + seasons is the exact recipe for the twee drift the user has repeatedly self-corrected. **De-risk:** hold the register lock explicitly — quarries not meadows, agri-industrial blocks not cottage gardens, blight cycles not harvest festivals, dockyards not fishing ponds. Any asset that reads "cute" gets rejected on sight, as the historic-district was.
6. **Cost creep via the paid image backstop.** Mass mural authorship could quietly lean on the paid last-resort model. **De-risk:** rate-limit `paint_surface` to the free chain; hard-cap paid fallbacks per run; bounce to another free provider rather than pay.
7. **"Do more, never less" violation.** Any mechanic that mainly *gates* agents (e.g. materials so scarce nobody builds) inverts the ethos, like the reverted road-face zoning. **De-risk:** tune resources to *widen* options (multiple viable material paths) and treat choking/scarcity crises as findings, not bugs — but never let a mechanism silently mute agents.

## (A) Fast Keystone Slice vs (B) Multi-Month Roadmap

**(A) Weeks-scale keystone (ships dormant, one flag):** the `computeBuildingMesh()` recipe grammar (Direction 1) plus the facade-decal surface (Direction 4) — together they make the *existing* city visibly agent-authored without any new world layer. Both are pure-function + off-replay-surface, both reuse existing state and pipelines, both are default-off with primitive fallbacks. This alone leapfrogs EW's static landmarks and is the piece most plausibly shippable before any EW v2.

**(B) Multi-month research-grade roadmap:** terrain substrate (i) → matter economy (ii) → CA ecology/catastrophe (8) → gossip/fog-of-war (5) → mania contagion (6) → deep-time ruins (9) → counterfactual forking lab (7) → auto-director chronicle (10).

**How A feeds B:** the keystone builds the three seams B depends on — (1) the seeded-hash variety utility, (2) the additive-serialize-when-non-default convention, and (3) the district-summary perception formatter. Once the recipe grammar proves those seams safe under byte-identical replay, terrain and the CA-driven layers can be added as further additive, flag-gated state with the same discipline, and the counterfactual-forking instrument turns the whole stack into PDoM's signature shareable artifact: *the same seeded world, one variable changed, two civilizations diverging in real time.*
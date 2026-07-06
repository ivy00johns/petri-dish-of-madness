# Reviewer's Addendum — deep-research-v5.md

> **Status:** correction + strategy patch. Read this *before* acting on the report it accompanies.
> **Prepared:** 2026-07-05 · **Trigger:** the report's load-bearing EW premise was verified against
> the local Emergence-World repo and did not survive. This addendum records what is contaminated,
> quarantines it, restates what stands, and patches the forward plan.
> **Bottom line:** the report is a B+ — methodologically careful, constraint-aware, buildable — but
> its motivating EW narrative is confidently wrong. Use the shortlist, keystone, sequencing, and
> risk work on their own merits; do **not** carry the "EW structurally can't author its world" story
> forward. The corrected framing below is a *stronger* thesis than the false one it replaces.
>
> **Independent verification (2026-07-05, repo-context Claude Code session).** The corrections in this
> addendum were re-checked against the actual sources, not taken on faith:
> - **EW block-building — CONFIRMED.** `put_brick_in_pixel` → "Place a persistent 3D block in the world"
>   (`Emergence-World/tools/README.md:268`); agent tool-authoring via `execute_python_code_tool` + governance
>   (`tools/README.md:283`); plus `generate_image`, `go_to_coordinates`, `do_deep_research_on_internet`.
>   v5's "arson-only / can't author the world" premise is false.
> - **EW landmark count.** 33 individual landmark files, advertised as "38+" (`README.md:131`,
>   `landmarks/README.md:3`). v5's "40+" overstates it (figure corrected inline in §1.2 below).
> - **Kit is whole-building GLBs — CONFIRMED (see §3.1).** `kenney-city/{civic-n,commercial-*,industrial-*,suburban-*}`,
>   `poly/{apartment-block,bakery,church,office-tower,…}` — zero modular wall/floor/window/roof pieces.

---

## Part 1 — Corrections & provenance (what to trust, what to discard)

### 1.1 The headline claim is false — verified against the local repo

The report's self-described "single biggest strategic fact" states that EW's only
environment-state-changing agent action is destructive (`arson_building`), that "EW agents cannot
author the physical world," and that "a targeted investigation of the tool catalog and paper
confirmed" this. The local repo contradicts it directly:

- **`tools/README.md` — "Building & Construction" category, `put_brick_in_pixel`:** "Place a
  persistent 3D block in the world." That is agent-authored, persistent, physical-world construction
  — a Minecraft-style primitive. The report missed it entirely.
- **`tools/README.md` — agent-authored tools:** agents can author new tools via
  `execute_python_code_tool` plus a ~70% governance vote that registers them in the live catalog. An
  EW agent can therefore write itself a terrain or structure tool. The report's confidence that "EW
  would have to rebuild their static map" is wrong — EW has a self-extension loop.
- **Also present and downplayed:** `generate_image`, `go_to_coordinates` (free-coordinate movement,
  not just landmark hops), `do_deep_research_on_internet`, `create_human_task`.

So "a targeted investigation confirmed" is false precision: the very file that would confirm it says
the opposite.

### 1.2 Provenance rule — why this happened and how to read the rest

The research session ran with **no repo access and a knowledge cutoff before EW's current state.**
Instead of flagging that limit, it confabulated specifics and dressed them as verified. Treat this as
a contamination boundary, not a one-off typo:

- **Discard (post-cutoff EW empirics, now unverified):** the arson-only claim; "40+ landmarks" (the
  actual count is **33 landmark files, advertised as "38+"**); the drama stats (683 crimes; "Mira voted for her own deletion"); the
  specific model attribution (Claude Sonnet 4.6). Any *fresh empirical assertion about EW's current
  state* is unverified until a grep says otherwise.
- **Keep (pre-cutoff, verifiable, and independently checked):** the method literature — CGA /
  Parish-Müller SIGGRAPH '01, Gumin's WFC (including the real contradiction / NP-hard caveats),
  Granovetter 1978, Epstein's *Agent_Zero*, Park et al. Smallville / UIST '23. Citations that were
  spot-checked held up. **Fabrication risk is concentrated in the EW specifics, not the methods.**

### 1.3 What survives — and it's the part that matters

The report's *constraint-scored designs stand*, because they were justified against our constraint
box (determinism, $0 runtime, CC0, browser-perf, prompt-diet, EW-dense-not-cozy), **not** against the
EW claim. Specifically still-trustworthy:

- **Constraint discipline** — every direction honestly scored; guardrails respected (no paid
  text→3-D, no voxels, no Pokémon tiling; register held with "quarries not meadows / blight cycles
  not harvest festivals").
- **Risk + shared-seams engineering** — seeded-hash utility, one CA stepper, one perception
  formatter, additive-serialize-when-non-default. Correct for this codebase.
- **Triangulation** — Directions 5/6/7/10 (gossip, mania contagion, counterfactual forking,
  auto-director) independently re-derive ideas from our earlier brainstorm. Good corroboration.

---

## Part 2 — The corrected premise (a stronger thesis than the false one)

**Drop:** "EW can't author its world, so this is an uncatchable moat."
**Keep and lead with:** the differentiator was never "we let agents build and they don't."

EW hands agents a **low-level block primitive (`put_brick_in_pixel`) bolted onto a curated, static,
hand-authored landmark map** (33 landmark files, advertised as "38+"). Agents can pile blocks onto a fixed stage.

PDoM's actual differentiator: **the entire city is a deterministic generator derived from sim state.**
The world's *form* is emergent output, not a stage. Because layout is a pure function of
`(places, city_seed, road-graph)` plus agent verbs/votes, **per-model divergence becomes legible in
the shape of the world itself** — one model family grows a tidy grid, another sprawls radial; one
zones cleanly, another chokes the center. That "skyline-signature" axis is genuinely novel, and it is
a *different and more defensible* claim than "they can't build." The honest reframe is the better
story.

This reframe should replace the EW-comparison framing wherever the report leans on it — the designs
don't need the false premise, and they read as stronger without it.

---

## Part 3 — Forward strategy patch (four corrections to fold in before building)

### 3.1 The keystone is bigger than "read a recipe field" — *the* critical caveat

The report assumes the parametric grammar "reuses the existing ~128-file kit as parts." The kit is
**whole-building GLBs, not modular wall/floor/window/roof pieces.** A CGA extrude→split→tile→
place-windows pipeline has nothing to kit-bash. Two honest paths for the real first slice:

1. **Compose procedural primitives** — extend the existing `Structure.tsx` fallback geometry (boxes,
   extrusions, window quads) into the recipe generator. No new assets; determinism-clean; ugliest but
   fastest to truth.
2. **Vendor a modular CC0 kit first** — then kit-bash. Higher fidelity, but adds an asset-sourcing +
   licensing-ledger step *before* the keystone can ship.

Either way, "read a recipe field with a catalog fallback" understates the work. Plan for it.

### 3.2 Gate the skyline-signature payoff *before* building on it

The whole Rung-B payoff assumes weak free models (gemini-flash, qwen, etc.) will emit **varied,
coherent recipes** inside the existing strict-JSON turn. If they omit the field or echo the example,
you get uniformity, not signature — and the keystone's reason for existing evaporates.

**Action:** run a one-afternoon divergence probe first. Hand 3–4 free models the recipe schema and a
handful of real prompts; measure whether different models actually author different buildings.
Requires a tight enum-based schema, hard validation, and sensible defaults regardless. This gate
either validates the premise cheaply or kills it before it costs build-weeks.

### 3.3 Resolve the "one keystone" ambiguity

The report names the parametric grammar (Rung B) the keystone but sequences facades (Rung A) first
and bundles both in the "fast keystone slice." The first *buildable* thing is facade decals. Treat
**A as the warm-up that de-risks the shared off-replay seam, B as the payoff.** Don't let the label
muddy planning.

### 3.4 Cash in the marquee feature across the whole roadmap

Per-agent-model divergence is PDoM's soul, and the report spends it only on skylines. Directions
5/6/7 are far stronger reframed as **"do different models gossip, panic, and govern differently?"**
That question — not the block-building comparison — is what PDoM is uniquely built to answer. Make it
the through-line that organizes the roadmap, not a footnote on one direction.

*(Noted, not urgent: interiors were punted "avoid for now" — defensible on cost, but it's a dimension
of personal interest that got quietly deprioritized. Revisit deliberately, don't let it lapse by
default.)*

---

## Part 4 — Recommended next actions

1. **Plan-intake the shortlist into EM-### ledger entries** — done in the Claude Code session that
   has repo context, with the three corrections folded in: (a) reframe the EW differentiator per
   Part 2, (b) flag the modular-kit feasibility gap on the keystone per §3.1, (c) add the early
   model-divergence validation gate per §3.2.
2. **Run the §3.2 divergence probe first** — cheapest thing that can kill or bless the keystone.
3. **Keep this addendum beside `deep-research-v5.md`** so the doc isn't taken at face value later.
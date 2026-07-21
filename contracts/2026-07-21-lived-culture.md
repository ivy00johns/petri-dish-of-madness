# Lived Culture — the culture→cognition loop (W5, overnight 2026-07-21) · Contract v1.0

> **Plan:** `docs/plans/2026-07-21-overnight-everything-plan.md` §W5.1 · §1.3
> **Evidence:** scratchpad `research/world-inventory.md` §4–§7 (the autopsy: memes are
> cosmetic to cognition — `held_memes` never reaches the decision prompt; passive
> diffusion plants no beliefs; beliefs aren't serialized)
> **Flag:** `world.comm.lived_culture` (default **OFF** in engine defaults + loader;
> byte-identical when off — same posture as every Wave-O knob). Go-live may flip it
> per-run in world.yaml (+ world.city25.yaml in sync — parity test).
> **Branch:** `build/overnight-lived-culture` off `build/overnight-feed-truth`.

## Why (one paragraph the implementer must internalize)
The world GENERATES culture but agents don't LIVE it. Memes spawn, drift, and die as
feed decoration; nothing an agent carries changes what it does. This contract closes
the loop through the existing, underused `_plant_belief`→prompt seam so drift becomes
*meaningful* (agents act on the distorted version they actually heard) — fixing the
"meme spam" complaint at the root: fewer, weightier culture lines, each with visible
behavioral consequence. Chat quality is the centerpiece; this must make chat RICHER.

## Scope (all behind the flag; every item additive)

### L1. Held memes enter perception
Each turn, up to `lived_culture.perception_top_k` (default 3) of the agent's
`held_memes` — ranked by (virality desc, recency desc, seeded tiebreak) — render as a
compact prompt block, e.g. `CULTURE YOU CARRY: "<text>" (heard from <src>)`. The text
is the agent's OWN drifted copy, not the canonical original — the telephone game
becomes epistemically real. Token budget: ≤ ~90 tokens; measure and report.

### L2. Passive diffusion plants a decaying belief
`diffuse_culture()` hops additionally call `_plant_belief(recipient, meme.text,
source=carrier, ttl=lived_culture.belief_ttl_ticks default 40)` — passive culture
becomes something agents *believe* for a while, not just carry. Dedup: re-hearing
refreshes ttl instead of stacking. Cap: at most `belief_cap_per_agent` (default 4)
culture-born beliefs; oldest evicted.

### L3. Beliefs serialize
`AgentState.beliefs` (culture-born entries at minimum) round-trip
`to_dict`/`from_snapshot` — serialize-when-non-empty (additive key; absent ⇒ [] on
load, old snapshots unchanged). This kills the resume blind-spot for culture.

### L4. Canonized memes get teeth
While a meme is canonized (`town_motif_ref`), agents whose action matches its
`lived_culture.motif_verb_map` verb class receive the existing small buff mechanism
(reuse the work-buff/`_WORK_BUFF_KINDS` pattern — no new buff engine). Mapping is
deterministic keyword→verb-class, defined in the loader with defaults; emits visible
`motif_observed {agent, meme, verb}` (Culture lane, aggregated per the existing
notable-cap pattern so it can't flood).

## The law
1. **Flag OFF ⇒ byte-identical.** No prompt line, no belief plant, no serialization
   key, no event. Full suites + determinism goldens pass unchanged.
2. **Deterministic.** Ranking seeded/tiebroken; no `random.random()` outside the
   seeded engine RNG; L2/L4 fire at existing round boundaries.
3. **Prompt-diet honest.** Report measured token growth (L1+enumeration ≤ ~120 total
   on the 5-agent world). NEVER raise free-lane max_tokens to compensate.
4. **Feed legible, not louder.** L4 events use the aggregation pattern; L1/L2 add
   ZERO feed events (they change decisions, and the decisions speak).
5. **New knobs parse.** Every new `CommunicationParams`/`lived_culture` field is
   wired into the yaml loader (`_parse_comm` sibling) WITH a regression test — the
   exact 9f56f10 failure class must be impossible to reintroduce silently.

## Acceptance
Full three-gate pass (pytest / vitest run / tsc -b --force) · goldens untouched-green
· parity test green (both world yamls) · unit tests: L1 ranking + budget, L2
plant/refresh/evict, L3 round-trip incl. legacy snapshot, L4 mapping + aggregation ·
a 60-tick seeded smoke with flag ON showing ≥1 belief-driven divergence vs flag OFF
(documented in the results file, not asserted byte-exactly).

## Changelog
- v1.0 (2026-07-21): initial.

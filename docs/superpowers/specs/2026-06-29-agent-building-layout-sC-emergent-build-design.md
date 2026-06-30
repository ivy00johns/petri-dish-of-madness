# Agent-Controlled Building Layout — SC: Zone-Targeted Emergent Building

> **Parent:** `2026-06-29-agent-building-layout-overview-design.md`.
> **Depends on:** SB (`...-sB-zone-rules-design.md`) — ratified, perceivable
> `ZoneRule`s on stable zone ids + the `nearby_zones` perception scaffolding.
> **Ledger:** EM-266. **Status:** design (2026-06-29).

## 1. Goal

*"Agents can choose to build there if they want"* + *"freedom to make mistakes as
part of the madness."* Let agents **target a zone** when they build, and let them
**honor, ignore, or break** that zone's rules — never enforced. Building stays
**free** (the build-freely side of the hybrid model; only the *rules* in SB were
vote-gated), so defiance is always possible. This is the emergent payoff: you
watch agents comply with, drift from, or actively defy the zoning the town voted
in.

## 2. Non-goals (out of scope for SC)

- **No enforcement, no penalties.** Breaking a rule is allowed and free. Recording
  a violation (§5) is pure observation, never a cost or a block.
- **No new vote gate.** Building is free; SC adds no governance.
- **No new geometry / assets / road changes.**
- **No new standing LLM calls** — choosing a zone is an option in the existing turn.

## 3. Targeting a zone

- **Build gains an optional zone target.** The agent's build action can name a
  `zone_id` (from SB's `nearby_zones` perception). Absent ⇒ today's auto-placement
  (back-compatible).
- **The build always succeeds** regardless of the zone's rule:
  - **Honor:** build a `market` kind in a `market` zone, under the cap.
  - **Ignore:** build in an *unzoned* zone (no rule) — fine.
  - **Break:** build a `residential` kind in a `market` zone, or build past the
    `density_cap`, or pile into the pentagon **core** zone and choke it. **All
    succeed.** *A finding, not a bug* (pillar 4).
- **"Build nothing" stays valid** — a zone can sit empty for the whole run. No
  pressure to fill it.

## 4. Frontend — show the mess honestly

The renderer must make defiance *visible*, not hide it:

- **Over-cap zones cram / overflow** their `suggestedLots` (SA already allows
  overflow rings) rather than refusing the building — a violated cap you can see.
- **Wrong-type buildings** render with their own kind, not coerced to the zone
  hint — the mismatch is visible.
- **Choked core** renders as a dense pile in the center — the headline emergent
  picture.
- Reuses SA's loose placement + SB's zone tints; the tint says "the town wanted
  X here," the buildings show "what actually happened."

## 5. Optional — record violations (pure observation)

So you can *see* where agents defied the plan:

- On a build whose kind ≠ its zone's `hint`, or that exceeds `density_cap`, emit a
  lightweight `zone_violation` event `{ zone_id, building_id, kind, rule_hint,
  over_cap, tick }`. No penalty, no block — observation only.
- Optionally surface a count in the AWI / feed ("3 buildings defied zoning this
  era") as emergent texture, consistent with the crime/governance signal style.
- **Strictly additive** — off by default if it risks the prompt/render budget;
  the build behavior in §3 does not depend on it.

## 6. Determinism, free-scale & fallback

- **Deterministic:** a fixed action sequence ⇒ byte-identical placement (EM-155).
  Zone targeting is data on the build event; replay re-applies it. No clock/random.
- **Free-scale:** zone choice is a field on the existing build turn — no new
  standing call; the `nearby_zones` perception (SB) is already district-scoped.
- **Fallback:** a build with no `zone_id`, or against a graph-less/old snapshot,
  uses today's auto-placement — never a hole, never a crash. Flag-off path
  (`GRAPH_LOTS_ENABLED = false`) is byte-identical to today.

## 7. Components & boundaries

- **Backend — agent action surface (`agents/runtime.py` / `engine/world.py`):**
  add the optional `zone_id` to the build action; resolve it to a zone; the build
  proceeds unconditionally; emit `zone_violation` when applicable.
- **Backend — perception:** extend `nearby_zones` (SB) with the agent-facing
  "you can target one of these" framing + current built-count vs cap.
- **Frontend — `cityLayout.ts`:** honor a building's `zone_id` when assigning lots
  (place it in *that* zone, overflowing if over-cap); keep `assignBuildingLots`'s
  ring fallback. **`CityScape.tsx`:** nothing new beyond SA/SB rendering; over-cap
  cram is just SA overflow.
- **Frontend (optional):** a violations count in the AWI/feed if §5 is enabled.

## 8. Testing & acceptance

- **Targeting:** a build naming `zone_id` lands in that zone.
- **Honor / ignore / break:** all three succeed; a rule-violating build is **not**
  refused and **is** rendered (crammed / wrong-kind / overflow).
- **Choke the core:** many builds into the core zone all place; renderer shows the
  dense pile; no crash.
- **Empty zone:** renders empty; never auto-filled.
- **Over-cap placement:** placer overflows without crashing or dropping buildings.
- **Determinism:** fixed action sequence ⇒ byte-identical; replay/fork match.
- **Violation record (if enabled):** `zone_violation` emitted on mismatch/over-cap
  only; never on an honored build; no penalty applied.
- **Fallback:** no-`zone_id` build + graph-less snapshot ⇒ today's auto-placement,
  byte-identical with the flag off.

**Acceptance:** an agent can choose to build in a specific zone and may comply
with or defy its voted rules; defiance always succeeds and is rendered honestly
(crammed core, wrong-type buildings, overflowed caps); empty zones stay empty;
everything survives replay/fork byte-identically. The city's *built form* — who
honored the plan and who didn't — becomes an emergent signature you can watch.

## 9. Risks & open questions

- **Over-cram readability:** a choked zone could render as z-fighting mush.
  Mitigation: SA's overflow rings spiral outward; tune spacing so "too many" reads
  as dense-but-legible, not broken.
- **Prompt budget:** the "target a zone" affordance must stay within the SB
  perception block — no extra lines per zone beyond what SB already shows.
- **Open:** whether to ship the §5 violation record now or defer it as texture —
  recommend ship behind its own flag, off until the build budget is measured.

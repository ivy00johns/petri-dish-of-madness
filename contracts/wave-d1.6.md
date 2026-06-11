# Wave D1.6 contract — "the city is earned" (addendum to wave-d1.5.md)

> User verdict on D1.5: "before this we had a world that made sense and had labels, now we
> have a skin." Three fixes, one lean agent, orchestrator gates. All standing laws hold
> (determinism f(snapshot, city_seed), free-scale, additive-only, fallback law, CC0,
> agents never commit).

## 1. Development is a function of sim state (EM-123 brought forward, frontend half)

- **Tick 0 = founded, not finished.** Founding stock seeded by distance from the plaza
  block: blocks adjacent to core ≈ 2–3 developed lots, mid ring ≈ 0–1, edge 0. Everything
  else is an empty platted lot (subtle procedural pavement pad / curb mark so empty reads
  "young city", not "broken" — no new GLB keys, the 23-key vocabulary is frozen).
- **Growth budget derives ONLY from snapshot fields** the frontend already has:
  `growthBudget = 2 × (real buildings with status operational|damaged|offline)
  + floor(day / 2)`, distributed deterministically (seeded order, weighted toward the
  core and the matching zone), capped at total lots. Tune the constants against the real
  archived long runs (run browser has 200+-day runs) so a scrub shows clear stages:
  young grid → filling blocks → dense city. The formula constants are yours to tune;
  derivation-from-snapshot-only is law (no Date, no tick-time accumulation in the client).
- Replay/fork correctness falls out for free: same snapshot ⇒ same city. Keep the EM-155
  determinism test block green; add "growth monotone in building count" and "tick-0
  founding stock matches the frozen falloff" tests.

## 2. Real buildings claim real lots

- `CityPlan` gains `realLots: Record<placeId, CityInstance[]>` — up to 6 street-front
  lots INSIDE each landmark block (never on roads), reserved for the sim's actual W7
  Building entities at that place. Generated fill never touches landmark blocks (already
  law).
- `Building.tsx` placement: building index among its place's buildings (stable order by
  building id) → that place's realLots entry; overflow falls back to the existing
  slotLayout ring. This also fixes the live bug where SLOT_BASE_RADIUS 5.5 > half-block
  5.2 puts agent-built buildings on the streets.
- Real buildings keep EVERYTHING: status renderers, healthTint, labels, click-to-focus,
  raycast. They are the foreground; generated fill stays raycast-dead.

## 3. Legibility: the labels come back

- The 15 landmark place labels must be readable at the default camera framing (the user
  navigates by them). Diagnose why they currently don't show (EM-102 distance gating vs
  the new 89u camera distance) and retune honestly — landmark labels get a generous gate
  (or always-on at city framing with distance fade); agent-built building labels keep the
  tighter gate; generated fill gets no labels ever.
- Sanity in the live browser before reporting done: default framing shows named
  landmarks; zooming to a place shows its real buildings labeled.

## Ownership (single agent — no siblings this wave)

`web/src/components/world3d/cityLayout.ts` (+test), `CityScape.tsx` (+test),
`Building.tsx` / `Structure.tsx` (+tests), `worldSpace.ts` (slot constants only if
needed), `CozyWorld.tsx` (label gating only). Backend untouched.

## Gate (orchestrator)

Full suites + build; live: tick-0 young city with labels, real building lands on a lot
(god-spawn a project or use an archived run), archive scrub shows growth stages, 60fps,
console clean.

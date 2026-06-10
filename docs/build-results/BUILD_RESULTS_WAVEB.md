# Wave B — "the city comes alive" · Build Results

> Branch: `build/wave-b-city-comes-alive` (stacked on `build/wave-a-live-run-fixes`, PR #6)
> Date: 2026-06-10 · Contract: `contracts/wave-b.md` · QA: `coordination/qa-report.json` (proceed=true)
> Items: EM-115, EM-111, EM-118, EM-122 — all **done** in the ledger (`wave-B 2026-06-10`).

## What shipped

| Item | Commit | Delivery |
|---|---|---|
| EM-115 city-growth slice | `5bbaefa` | `BuildingParams.auto_build_per_round` (default 10, 0 disables): under_construction buildings advance every round via the existing `advance_buildings()` hook and complete through a shared `_complete_construction` helper — identical `structure_state_changed`/`building_operational` payloads to the agent `build_step` path. Funded projects can no longer rot to abandoned; agent labor stays the faster path. Zero LLM calls. |
| EM-111 warm toon golden hour | `c0a6879` | Vendored CC0 Venice Sunset 1k HDRI (`web/public/hdri/`, `ASSET_LICENSES.md`), cached `toonMaterial()` factory + banded 3-tone ramp (`toon.ts`) swept across every world3d component, low warm sun `#FFCF99` @2.2 + hemisphere fill, drei `<SoftShadows>` (AccumulativeShadows deliberately skipped — movers), golden ground/fog/sky palette per Direction 1 of `docs/ui-redesign/3D-WORLD-ART-DIRECTION.md`. |
| EM-118 foliage + props | `dd1c3a9` | 60 instanced trees (oak/conifer/blossom) with deterministic near/far LOD split (~26 instanced draw calls total — fewer than the old 16 individual trees); lamp posts lining paths on alternating sides, plaza benches, fences, bushes, mushrooms, rocks (275 instances ≤400 bound). All clearances test-enforced: slot rings, place centers, and **path corridors** (added mid-wave from live user feedback — benches were spawning on path ribbons). |
| EM-122 per-kind buildings | `209e187` | `operationalVariant()` keyword-maps emergent kinds onto 10 distinct procedural meshes (garden/farm/workshop/library/clocktower/house/stall/monument/well/generic); `healthTint()` soots operational bodies as health drops. Bob/sway, offline darkening, label gating, click-to-focus preserved. GLB kit swap stays deferred — outcome delivered procedurally. |
| QE gate fix | `c5cb42b` | Prototype-chain guard in `buildingStyle`/`operationalVariant` — model-authored kinds like `constructor` crashed the canvas (QE adversarial find). |

## Gates

- Backend: **352/352** (+9 EM-115 tests; 1 wave-A test re-pinned to `auto=0` to keep guarding stall-rot).
- Web: **236/236** across 29 files (+45 new: toon 14, foliage 17/18, worldSpace 12+1 guard).
- `npm run build`: clean (pre-existing chunk-size warning only; HDRI ships via `public/`, not the bundle).
- Browser (Playwright, both gates): console **0 errors**; gate-1 shot caught EM-115 live (`2 operational` at day 2); gate-2 shot shows treeline/lamps/props/stall. Evidence: `docs/build-evidence/wave-b-gate1-golden-hour.jpeg`, `wave-b-gate2-city-alive.jpeg`.
- QA report: proceed=true — contract 4/5, coverage 4/5, security 5/5, regression 4/5; 5 adversarial probes green (snapshot mid-construction resume, `auto=0` restore, damaged-stall rot, negative-auto, malformed-input purity).

## Recorded QE MINORs (not blocking, future work)

1. ~~Prototype-member kinds crash canvas~~ → fixed at gate (`c5cb42b`).
2. `structure_state_changed.reason` value differs between completion paths (keys identical; no consumer switches on it).
3. Health-tint material cache never evicts (bounded ~tens; bucket health if it grows).
4. Negative `auto_build_per_round` behaves as disabled but is unvalidated.
5. No automated snapshot-resume-auto-build test (QE probed green manually; fork-endpoint seam).

## Filed during the wave (user live observations)

- **EM-143** — god-spawn critters (species picker incl. squirrel; population cap).
- **EM-144** — starvation banner doesn't clear after recharge (latched event vs live energy; confirmed on screen: banner 22/100 from T105 while card read 92).
- **EM-145** (P1) — god whispers + billboard replies show no agent uptake; make delivery legible ("✦ {name} hears the whisper") + verify UI→API→prompt with capture. Note: in-memory `pending_whispers` were repeatedly wiped today by build hot-reloads.
- **EM-146** (P1) — story-so-far digest still pushes the feed out of view when long; cap height + scroll + collapse toggle.

## Handoff

- Wave B is complete on `build/wave-b-city-comes-alive` (not merged; stacked on PR #6's branch — merge PR #6 first or retarget).
- Live sim runs all of Wave A+B; the work crew finishes funded projects autonomously.
- Suggested next wave: EM-145 + EM-146 + EM-144 (the live-run annoyance batch) or continue the city track (EM-123 neighborhoods).
- Full-skill `ux-review` repo-wide pass still owed on merged main (deferral standing since W11b).

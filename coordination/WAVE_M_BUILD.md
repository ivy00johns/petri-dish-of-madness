# Wave M build log — Cooperation Economy + W23 (orchestrated, ultracode)

**Branch:** `build/wave-m-cooperation-economy` · **Started:** 2026-06-26
**Mission:** complete the backlog minus deployment (user, /orchestrator ultracode).
**Scope locked (user):** multi-city wave DEFERRED (city-depth-first); subjective UI
IN (EM-204/215/180); EM-127 day/night DEFERRED (visual sign-off).
**Contract:** `contracts/wave-m.md`. **Baseline:** 1142 passed, 1 skipped (~43s).

## Architectural constraint
All backend features mutate `world.py` (5312 ln) / `runtime.py` / `loop.py` /
`loader.py` → built **sequentially**, full-suite gate between waves (run by lead).
Frontend serial-by-area (inspector / world3d / controls / nav). Verify phase
parallelizes per-feature.

## Invariants gated every wave
EM-155 byte-identical snapshots · em161 prompt golden · determinism (no
random/clock) · config-absent = no-op · full suite green · north-star (add
activity, never throttle).

## Wave ledger
| Wave | Items | Gate | Status |
|------|-------|------|--------|
| M1 | EM-229, EM-233, EM-234 | full pytest | ✅ green — 1192 passed/1 skip |
| M2 | EM-227, EM-228, EM-230, EM-231 | full pytest | ✅ green — 1326 passed/1 skip |
| M3 | EM-232, EM-235, EM-236, EM-237 | full pytest | ✅ green — 1413 passed/1 skip |
| M4a | EM-224, EM-203/206, EM-189, EM-190 | full pytest | ✅ green — 1462 passed/1 skip |
| M4b | EM-186, EM-167, EM-126(stretch) | full pytest | ✅ green — 1530 passed/1 skip |
| F | EM-202, EM-215, EM-204, EM-195, EM-180, EM-191, EM-192, EM-193, EM-225 | typecheck+test+token-guard | pending |
| Verify | adversarial review + QA gate + ledger + results + PR | qa-report.json | pending |

- **M4a (2026-06-27):** EM-224 PIANO coherence (post-resolution contradiction pass, gated
  world.coherence default OFF, design doc) → 33028be. EM-203/206 governance renewal cooldown
  + settled-naming → bb7d50a. EM-189 deterministic seeded child ids → 8751c97. EM-190 fork-safe
  outbox serialization → 990811d. Suite 1462/1skip.
- **M4b (2026-06-27):** EM-186 headless run.py D3 wiring parity with app.py → 2e12dde. EM-167
  Ollama overflow lane (mock-verified; live-verify pending a running Ollama, world.overflow_lane
  default OFF) → 232f4e4. EM-126 generational depth — life stages/aging/inheritance, gated
  world.generations → d9e7a7f. Suite 1530/1skip. **ALL BACKEND WAVES COMPLETE** (18 feat commits,
  +10.4k lines, em161 golden + EM-155 held throughout).
- **Frontend env (2026-06-27):** the shell's npm/node are broken nvm placeholder funcs; node v25
  has a broken jsdom localStorage (55 spurious fails). Frontend MUST use node **v22.22.3** — baseline
  there is GREEN (tsc clean, 963 tests). Incantation in contracts/wave-m-frontend.md §1.

## Deferred (with reasons)
- Multi-city EM-109/110/116/117/121 + parallel-worlds 112/119/128 — user: deepen
  first city before founding a second.
- EM-127 day/night + seasons — user: needs visual sign-off (look change).
- EM-214 audio — user deferred at Wave I (re-enter when voices wanted).
- EM-169/176 vehicles — in PR #44, art sign-off pending.

## Run notes
- **M1 (2026-06-26):** EM-229 three-needs (knowledge/influence decay, salience-gated
  prompt line, replenish hooks for M2) → commit f272f17. EM-233 soul entries + memory
  consolidation (deterministic digest at round boundary, `memory` event) → 7db913b.
  EM-234 universalization (GovSim commons scaffold, gated `world.universalization.enabled`
  default OFF → golden-safe) → 900e851. Full suite 1192/1skip. em161 golden + EM-155
  snapshot byte-identical held. Also touched config/world.city25.yaml (needs block).
  M2 TODO: wire world.replenish_knowledge on skill-gain/teach, replenish_influence on
  governance/social wins.
- **M2 (2026-06-27):** EM-227 skills keystone (library gates propose_project/build_step→building,
  create_image→art, propose_rule→rhetoric; deterministic seed gradient + use-xp; knowledge
  replenish wired) → 89e6556. EM-228 teach_skill/request_skill (transfer + pending request,
  snapshot-safe) → 470bdf0. EM-230 offer_trade/accept/decline (atomic two-sided swap, pending
  offer serialized) → d0200a7. EM-231 cooperation handshake + co_build gated action → 9a3120a.
  Full suite 1326/1skip. New pending outboxes (pending_skill_requests/trade_offers/cooperation_
  offers) all serialized only-when-non-empty (EM-190 pre-empted). em161 golden + EM-155 held.

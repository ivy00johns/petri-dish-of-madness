# Wave A + A.2 — build results

**Branch:** `build/wave-a-live-run-fixes` · **Date:** 2026-06-10 · **Gate:** GREEN
**QE report:** `coordination/qa-report.json` (proceed=true · 12/12 adversarially confirmed · 0 refuted · 0 CRITICAL/MAJOR)
**Tests:** backend 330/330 (55 new) · web 182/182 (32 new) · `npm run build` clean · `docker compose config -q` clean

## What shipped

### Pre-wave fixes (carried on this branch)
| Commit | What |
|---|---|
| `fa084b2` | Retry length-truncated turns with a boosted token budget (reasoning-model reroutes) |
| `483d422` | Salvage stop-truncated JSON (progressive prefix repair), evict bad responses from the router cache, full-text forensics on dead turns |
| `31265e5` `1f763db` `b30b254` `b8e031d` | God-channel prototype: proclamations reach every agent, threaded replies, consensus town naming, emergent-only town-name surfacing |

### Wave A — live-run correctness (contract: `contracts/wave-a.md`)
| Item | What | Commit |
|---|---|---|
| EM-129 | Agent-built buildings get humanized display names (`prepare_beds` → "Prepare Beds"); junk names fall back to "<Agent>'s <Kind>"; raw arg kept in payload | `0892c71` |
| EM-132 | `build_step` on a damaged building auto-redirects to repair (world redirect + validator passthrough) instead of wasting the turn | `0892c71` + `9fef06e` |
| EM-133 | `contribute_funds` clamps at the remaining gap — funding can never overshoot (the 12/5 booth) | `0892c71` |
| EM-134 | Per-building animal-damage cooldown (6 ticks; first hit always lands; arson unaffected) | `0892c71` |
| EM-108 | Governance location gate enforced at resolution: laws require standing at a governance place | `0892c71` |
| EM-135 | Reroute-aware lane health: after repeated truncations on a profile, attempt 1 gets the boosted budget pre-emptively | `9fef06e` |
| EM-130 | Unknown building kinds no longer render as "Monument": keyword mapping + neutral fallback + humanized kind subtitles | `9a055e2` |
| EM-131 | Deterministic placement slots — buildings sharing a place fan out on concentric rings instead of stacking | `9a055e2` |
| EM-106 | `backend_data` named compose volume — run history survives container recreation | `d6fd6a7` |

### Wave A.2 — god console (contract: `contracts/wave-a2-god-console.md`, user-requested mid-wave)
| Item | What | Commit |
|---|---|---|
| EM-136 | `POST /api/god/intervene`: BLESS (+energy, clamped at 100) / GRANT (+credits) aimed at ONE agent — the "save this villager" lever | `d0dca87` |
| EM-137 | `POST /api/god/whisper`: a one-shot line only the target agent hears on their next turn | `d0dca87` |
| EM-138 | GOD CONSOLE panel: WORLD EVENTS / INTERVENE (living-agent selector + BLESS/GRANT/WHISPER) / VOICE groups | `6abd475` |

## Live verification (run on the dev stack, 2026-06-10)

- Truncation fixes: run 139 ticks 1–26 — **0 parse failures, 0 deaths** with both hostile lanes (mistral 'stop' cuts, nemotron 'length') active; user later reported agents surviving **400+ turns** (previous death window: ~T200).
- God console E2E: blessed Ada 96→100 (clamp verified), granted Bram +50 credits, whispered "recharge before you spend" to Cleo — **she recharged within 3 ticks**. Unknown agent → 422. Events persisted in god ink.
- Render: village + feed at `/` with 0 console errors; GOD CONSOLE groups live in the DOM.

## Build process

Ultracode orchestration: 2 implement workflows (4 + 2 role-agents, disjoint file ownership, structured JSON reports) → integrated wave gates → 12-skeptic adversarial verify workflow → QE gate agent (wrote `coordination/qa-report.json`). One cross-file blocker (EM-132 validator) routed at the gate; 11 pre-existing test fixtures relocated to the townhall by a gate-fix agent (the new governance gate working as intended).

## Deferred / known-minor (from the adversarial pass — none blocking)

- `raw_name` payload capped at 60 chars (matches the name cap; contract said "raw").
- EM-134 cooldown feed line uses the pre-existing harmless animal phrases, not the contract's literal "shooed away" wording.
- God endpoints return 200 (contract's own "200 happy paths" clause) vs the 201 of billboard/proclaim.
- No dedicated unit test for the EM-132 validator passthrough (behavior verified by the skeptic manually + covered end-to-end).
- Full `ux-review` subjective pass still owed on merged main (deferred since W11b).
- Title-case quirks on digit/non-ASCII names (`2nd_market` → "2Nd Market").

## Handoff

- **Ledger statuses for the 12 items are flipped to done in the working tree** but `docs/REMAINING-WORK.md` is deliberately left uncommitted — it carries the user's not-yet-committed v3 intake (EM-109–128) and planning edits (`BUILD-PLAN.md`, `docs/FUTURE.md`, `docs/research/deep-research-v3.md`, `CLAUDE-DESIGN-PROMPT.md`, `docs/ui-redesign/`). Commit those together when the v3 plans settle.
- Next per the agreed build order: **Wave B** — EM-111 (warm toon golden hour), EM-115+131-pairing (city growth), EM-113 (relationship schema), EM-112 (parallel-worlds runner).

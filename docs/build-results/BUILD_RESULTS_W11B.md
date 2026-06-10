# W11b Build Results — "Sim texture"

**Branch:** `build/w11a-ui-batch` (continues W11a; one PR carries W9–W11) · **Date:** 2026-06-09
**Contracts:** api.openapi.yaml **1.4.0** · event-log.md **v1.3.0** · frontend-inspector.md **v1.3.0** (§10).
**Gates:** wave-1 GREEN → QA GREEN (proceed=true) → live verification GREEN.
Full gate log: `coordination/W11B_BUILD.md`.

**Free-scale law held and PROVEN:** commitments, reflections, and billboard posts ride the
same single turn response; QE's prompt-capture tests assert it literally. Zero new
standing LLM calls in the whole wave.

## What shipped

| Item | Result |
|---|---|
| EM-079 commitments | Active-commitments prompt block, `commitment_made`, 👻 `commitment_lapsed{phantom}` after 12 talk-only turns, tool-salience line ("SAYING ≠ doing"), cap 5 |
| EM-080 reflections | Importance accumulator → same-call `reflection` field → ✎ diary events feeding memory (~2–3/day) |
| EM-081 overhearing | ≤2 co-located listeners get speech in next-turn perceived (`overheard_speech`), cap 2 pending, reflex-only reactions |
| EM-087 + EM-103 | Identical-active re-proposals RENEW (↻, never stack — the 3×UBI invariant is now pinned by tests); law-named projects tagged commemorative + linked to the rule, one monument per law |
| EM-091 billboard | Reflex post/read tools (plaza/town hall), 20-post `world.billboard` in snapshots + WS, 3D notice board with proximity label, 📌 feed idiom, BILLBOARD panel, god replies via panel form or `POST /api/billboard` (violet god ink + ✦) |
| EM-092 personas | `config/personas.yaml` — 10 cards across all 8 model lanes (Mox, Vesper, Hazel, Quill, Sable, Brick, Lumen, Patches, Marrow, Tilly); `GET /api/personas`; spawn picker prefills, edits win |
| EM-098 procgen + housing | `world.procgen` seeded towns (existing kinds, ≤12 places, guaranteed minimums) + per-agent cottages + The Bunkhouse (beds = agents−1); off by default |
| EM-100 rule names | Feed leads with quoted rule text + effect tag; uuid only in payload |
| EM-101 fork/resume | `World.from_snapshot` (round-trip verified) + `POST /api/runs/fork` — snapshot-grain with HONEST response (`forked_at_tick` + note), lineage columns, paused start, ⑂ FORK in Run Browser with ↩ lineage chips, `place_overrides` works (multi-city seed) |
| EM-082 | Min-width 1024px gate + a11y pass (landmarks, headings, aria-labels, focus-visible, reduced-motion) |
| EM-083 | Real blackouts (recharge fails at blacked-out homes, expiry restores) + `usage_alert` at 70% of per-profile rpd/tpd caps, once per UTC day, amber banner |
| EM-107 (user, in-wave) | Top banners moved to an absolute overlay stack with opacity-only 180ms fade — banner appearance/clearing moves ZERO content pixels (measured 0.0px live); reduced-motion = instant |

## QA

Backend **252/252** (+46), frontend **150/150** (+44). contract 5/5, security 4/5, zero
blockers. Findings: EM-108 filed (governance location gate is prompt-only — pre-existing);
LOW dead `THE WATCHERS` value in BillboardPanel; 3×INFO in-contract notes (positional
commitment-keeping; deterministic listener pick; `reason:"expired"` typed but unreachable).

## Live verification highlights

Posted as the watchers via the API and watched it land in god ink with the reply form
ready; forked run 26 @ tick 78 → run 101 born paused at honest tick 75 with "↩ #26 @
tick 75" in the Run Browser; dismissed a real banner and measured 0.0px content shift;
800px viewport hit the "THE LAB NEEDS ≥1024px" gate. Console: 0 errors throughout.

## Notes & carries

- Reset-after-fork resets to the FILE config, not the forked state (same as any reset).
- Fork is snapshot-grain (every 25 ticks); the response says so honestly.
- Open small items: EM-106 (compose `data/` volume), EM-108 (governance location gate).
- `docs/research/deep-research-v3.md` appeared in the working tree (user's) — unreviewed.

## Handoff

**W9–W11 are complete.** PR to `main` carries the audit + W9 + W10 + W11a + W11b
(supersedes PR #4). Next frontier candidates: multi-city/transport (FUTURE.md, now
unblocked by fork + place_overrides + procgen), EM-106/108 cleanups, deep-research-v3
intake.

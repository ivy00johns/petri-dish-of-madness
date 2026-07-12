# Mission skill manifest — beast-mode ultracode session
Source: user mission 2026-07-11 ("build out as much as we can… dream up new ways to expand… bug hunting and fixing and testing… get the branches merged if completed then clean up") · Scanned: 2026-07-11

Every box must end the build either ✅ (invoked, with the artifact path)
or annotated with a one-line reason for deferral. Empty boxes are bugs.

## Phase 0 — Merge & cleanup (user mid-turn directive)
- [x] `git-pr` / `git-commit` conventions — ✅ applied: #84 merged, #86 (W30) created+merged on green CI, #85 closed superseded, branches/worktree cleaned.

## Phase 1 — Build out (ultracode Workflow: implement)
- [x] `orchestrator` — ✅ invoked (this session's coordinator).
- [x] `Workflow` (ultracode, explicit user opt-in) — ✅ implement phase shipped all five streams: Wave O keystone+War → PR #92; EM-297 probe → PR #87 (merged); EM-269 settlements → PR #88 (merged); EM-302 → PR #89; W30 fix pack → PR #90.

## Phase 2 — Bug hunting / fixing / testing (ultracode Workflow: find + verify)
- [x] `Workflow` — ✅ 5 finders → 24 findings; 7/7 highs adversarially CONFIRMED; 4/4 stream reviews approve_with_nits (zero gate-cheating); fixes → PR #91 + nit commits on #89/#90/#87/#88.
- [x] `fix-until-green` discipline — ✅ every fix carries a regression test proven to FAIL pre-fix; zero existing tests deleted/weakened (one routing test rewritten to the new contract on the verifier's explicit instruction, documented in PR #91).

## Phase 3 — Dream up expansions
- [x] Ideation panel (3 lenses + synthesis) — ✅ `docs/research/2026-07-11-expansion-ideas.md` (18 proposals, T1×6). NOT filed into the ledger — `plan-intake` is fail-closed and needs user approval (deferred by design).

## Deferred with reasons
- `plan-intake` — fail-closed by convention; proposals parked in the ideas report for user approval.
- EM-305 feed-flicker repro — needs the sim up + browser; sim restart is user-gated ("Not yet", 2026-07-11).
- Live smoke / render-sanity of new features — same sim gate; recorded as handoff items.
- `nano-banana`/`ux-review`/`render-sanity` — no UI-from-scratch deliverable in this mission; UI deltas are typed/tested, visual sign-off rides the next live session.

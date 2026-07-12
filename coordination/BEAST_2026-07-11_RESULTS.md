# Beast-mode ultracode session — end-state report (2026-07-11)

> Mission: "build out as much as we can… dream up new ways to expand… bug hunting
> and fixing and testing… get the branches merged if completed then clean up."
> Executed as an orchestrated ultracode campaign: ~40 agent dispatches across four
> Workflow runs (implement → verify → fix → fix-round-2), all builds in isolated
> worktrees off `main`, every stream adversarially reviewed before its PR.

## Merged to main today

| PR | What | Notes |
|----|------|-------|
| #84 | Proxy-timeout labeling + network-down auto-resume | closes the Jul-8 timeout lead (EM-301 thread) |
| #86 | W30 audit remediation | adaptive routing LIVE (reserved `auto` backstop, max_attempts 4), F1 restores, **first CI on main**, ledger EM-300..307 |
| #87 | EM-297 model-divergence probe | **GO (qualified)** for EM-299; qwen/llama top-up owed in a healthy proxy window |
| #88 | EM-269 F2 settlements | flag OFF; `found_settlement`, anchored placement, 3-D markers; emergent multi-city seed |

(#85 closed as superseded by #86 — it was red against the config tests.)

## Open PRs (CI-green, reviewer-passed; awaiting human merge)

| PR | What | Review verdict |
|----|------|----------------|
| #89 | EM-302 facade follow-ups (decal buckets, measured placement + x-center, **billed**-semantics paid cap) | approve_with_nits → all nits applied |
| #90 | W30 fix pack: EM-303 (sprawl clamp flag-OFF, stored-wins, falsifiable uuid4 test) · EM-304 · EM-306 (require_json WIRED, dormant until lanes tagged) · EM-307 per-call attribution | approve_with_nits → all applied |
| #91 | **7-bug sweep** (see below) | every fix verifier-confirmed pre-write |
| #92 | Wave O keystone + War track (EM-249/250 + EM-256–259) — backend 2168 / tsc / vitest 1253 all green; comm+war flags default OFF, byte-identical goldens pinned | gates ×3 green; unlike the four smaller streams, no separate fresh-context diff review ran (largest branch; review it at the PR) |

## The bug hunt (find → adversarially verify → fix)

5 read-only finders swept frozen main across determinism / engine / providers /
frontend / persistence → **24 findings**. All 7 high-severity findings were
independently rechecked by verifiers instructed to REFUTE them: **7/7 CONFIRMED.**
All 7 fixed on PR #91, each with a regression test proven to fail pre-fix:

1. Trade-settle atomicity (+1-gap trade moved credits for a no-op teach)
2. Arson→abandoned (damage clock measured from construction completion)
3. Token-clamp boost signal (boosted retries dodged the #77 clamp)
4. **WS/DB seq unification — the leading EM-305 feed-flicker root cause.** Broadcast
   events carried a per-boot counter, not the persisted event_id; every restart/fork
   made clients dedupe/evict live events against a colliding id space.
5. Unguarded `_execute_turn` (one exception silently froze the sim while
   /api/health said running) — now pauses loudly
6. Mock-fallback events never purged on live recovery (colliding positive seqs)
7. Bounce-latch: bounce-only lanes (incl. the reserved `auto` backstop) latched
   sick permanently — reserved slot no longer forfeits; sick lanes heal via
   cadence probes

Unfixed findings (medium/low, 17): parked for `plan-intake` — the raw finder
reports live in the session's workflow journals; notable mediums: lineage
tick-ceiling off-by-one, `/api/replay` lacks lineage support, analytics population
counts animals/governance double-spawns, `ab_models` burst without cap, fork/resume
never `end_run`s the parent.

## Wave Q go/no-go: EM-297 verdict

**GO (qualified).** 13/13 answered outputs strict-schema-valid, 0 hard echoes,
divergence on 1–4 of 7 fields per co-answered prompt, 9/9 coherence checks, legible
per-model signatures (gemini monumental vs gpt-oss frugal). Qualification: qwen +
llama lanes 429'd throughout (the EM-301 churn itself!) — an ~18-call top-up in a
healthy window is owed before EM-299 visual sign-off and retains go/no-go authority.
EM-299 must ship strict-parse → coerce-with-defaults → catalog-fallback as three
explicit tiers; 429'd recipe turns are a production fact.

## Expansion ideas (NOT filed — plan-intake is fail-closed)

`docs/research/2026-07-11-expansion-ideas.md`: 18 proposals from a 3-lens panel
(emergence / spectacle / model-lab), deduped and tiered T1×6 / T2×8 / T3×4, each
constraint-checked ($0-first, single-city, no-throttle, determinism, EW-dense).
T1 headliner: **Story Arcs** — a deterministic, read-only arc detector that threads
the feed's own drama. File via `plan-intake` with user approval.

## Handoff items (user gates)

- **Merge queue:** #89, #90, #91, then #92 (Wave O — expect a `world.py` rebase
  against #91; merge #91 first).
- **Sim restart** adopts: adaptive routing + reserved backstop (#86), timeout
  labeling (#84), and (once merged) the seq fix + bounce-latch healing. Config
  bakes per-run. Watch: idle-fallback churn should visibly drop; `/api/lanes`
  sick-latch recovery; feed survives a backend restart (the EM-305 test).
- **EM-305 live check:** after the seq fix merges + restart, try the old repro —
  if the flicker is gone, close EM-305 against PR #91.
- **Back up `data/run.sqlite`** (VACUUM INTO) before first post-restart load —
  the ratified derive-on-load will re-place pre-F1 buildings (by design).
- **Live visual sign-offs owed:** x-centered murals (#89), settlement markers
  (#88 — then flip `settlements.enabled`), war feed lane (#92), the deferred
  EM-247 `ROAD_MESH_ENABLED` pentagon check.
- **EM-306 activation:** tag reasoning lanes in `config/lanes.yaml` + restart.
- **EM-297 top-up:** `em297_probe.py --models "qwen=…,llama=…"` in a healthy window.
- **Ledger sweep:** EM-269/297 (merged) swept in this PR; EM-302/303/304/306/307 +
  Wave O rows sweep when their PRs merge.

## Deferred with reasons

- **EM-305 dedicated repro session** — needs live sim + browser; sim was
  user-gated down all session. (Likely obsoleted by the #91 root-cause fix.)
- **Wave O Culture/Religion tracks (EM-251–255, 260–263)** — keystone seams landed
  (EM-250 pre-registered `culture_camp`/`congregation` group kinds); War shipped
  first per plan. Next session's natural build.
- **plan-intake for new findings/ideas** — fail-closed; needs user approval.

## Session stats (approx)

- 4 Workflow runs, ~40 agent dispatches (6-slot cap on 8 cores), ~6.9M subagent
  tokens, ~1,700 tool uses. Two network windows + one session-limit reset killed
  ~8 agent attempts; every casualty was resumed from cache or respawned with zero
  lost commits.
- Test suite growth: backend 2025 → 2026+ on the sweep branch (goldens untouched
  everywhere); web 1215 → 1303 on em302. Zero gate-cheating found by any reviewer
  across four streams.

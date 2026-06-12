# Wave E — "the social city" (characters & the social world) · Build Results

> Branch: `build/wave-e-social-world` (off merged main, post-PR #11)
> Date: 2026-06-11 · Contract: `contracts/wave-e.md` (v1.2)
> QA: `coordination/qa-report.json` (wave-E, **proceed=true**, 0 blockers;
> its one MAJOR fixed same-wave, see below)
> Items: **EM-113, EM-114, EM-120, EM-125, EM-184, EM-185, EM-188** — all done
> (`wave-E 2026-06-11`). Ultracode build: one Workflow per batch
> (implement agent + adversarial verify lenses), orchestrator gates + commits
> between every batch.

## Mission

Recreate the Emergence-World experience. EW's magic was *social* texture
(683-crimes-vs-zero-crimes cultures) — that needs typed relationships,
factions, family lines, and a closed petition→miracle→belief loop. This wave
is the v3 "deepen the first city" character/social cluster plus the W18
answered-prayers items filed from the user's live session.

## What shipped

| Batch | Commit | Delivery |
|---|---|---|
| B1 EM-113 | `fd8ae50` | Typed relationships: 9-type vocabulary (adds partner/family/mentor/feud), `since_tick`, reflex transitions at the single `_update_trust` seam (neutral/ally→friend at trust≥30 & 5 interactions; rival/enemy→feud at ≤-40; never auto-downgrade), partner consent = mutual declaration + trust≥40 (`are_partners`), family engine-only, `relationship_changed` events on type edges only. 23 tests. |
| B2 EM-114 | `90fd3a8` | Children: round-boundary birth checks — mutual partners co-located at a home, both pay 6 credits, seeded sha1 chance gate, pair cooldown derived from the youngest shared child (zero new clock state), births fill vacancies ONLY under `max_population: 25` AND home-bed capacity (free-scale proven: at cap, no birth ever). Child casts from unused persona cards at background tier on the least-loaded non-mock lane; family ties both ways; `parents` field (the EM-126 hook). 31 tests. |
| B3 EM-120 | `5e2a2e6` | Factions + reputation: round-boundary connected components over mutual warm edges (both directions ∈ {ally,friend,partner,family}, trust≥25, size≥3), identity continuity by ≥50% overlap, diff-driven `faction_*` events (zero spam on stable rounds), deterministic ids/names ("<lowest-id member>'s circle"). Reputation = derived mean incoming trust, zero storage, on every world payload. 24 tests. |
| B4 EM-125 | `106d518` | Reflection-driven bonds: the existing EM-080 reflection request gains an optional `bond {target, type}` riding the SAME single turn call (zero llm_call delta proven by row-count test); valid bonds apply through the B1 guards on the same turn chain; invalid ones drop silently with a trace reason. Carry-overs: faction "Your circle" prompt line (B3.6), exception-safe relationship-outbox drain (B1 QE finding). 27 tests. |
| B5 EM-184 | `bbf6e57` | World miracles: `send_rain` (+2 forage, 2 days), `bountiful_harvest` (decay ×0.5, 2 days) as refresh-not-stack timed modifiers swept beside blackout expiry; `calm_spirits` one-time hopeful mood + trust nudge that drains its own relationship events (B1 transitions can fire — by design). `agent_id` now optional on `POST /api/god/intervene` with a strict world/targeted 422 matrix; `god_miracle` globally witnessed at importance 2.0. 27 tests. |
| B6 EM-185 | `bd780e8` | Grant-a-petition: inline GRANT picker on petition-shaped feed entries (agent billboard posts / proclamation answers — never god's own) casting a miracle AND auto-replying on the billboard quoting the petition; god console MIRACLES row. Social-graph typed edge colors + faction rings, roster REP stat + 4 new REL colors, all 8 wave-E event kinds registered in icon/color/category. 63 tests. |
| QE gate | `f1958f5` | Cross-batch adversarial pass (5 permanent tests): birth→faction→prompt-line composition through the real loop; calm_spirits→friend-flip→faction chain with zero llm_call rows; wave-level free-scale (30-round default world = exactly 71 llm_calls, matching pre-E cadence math derived in-test); all-state fork byte-equality with behavior resuming; green-gate audit (zero pre-existing test files modified all wave). proceed=true, scores contract 4 / coverage 4 / security 5 / regression 4. |
| QE-MAJOR fix | `d13a63c` | God-console casts are now witnessed: the intervene API path pushes its event batch into the runtime with loop-identical tick stamping — a cast miracle lands in agent memory, accrues importance 2.0, wakes background salience; a blessed agent remembers being blessed. Without this, the belief loop was mute from the actual UI (QE execution-verified). |
| B7 EM-188 | `64de9b3` | Street + city names (user mid-wave request, contract v1.2): seeded deterministic street names for the 12 grid centerlines (96-name bank, dedupe proven across 11 seeds, EM-155 byte-identical invariant EXTENDED to pin them), painted flat on interior avenues behind the existing 32u proximity gate (zero labels at default zoom); `town_name` HUD chip, absent-safe. 15 tests. |

## Gates

Backend **566 → 705** · web **501 → 579**, vite build green. Full suite +
orchestrator commit after every batch; design-token source gate on the UI
batches: **zero new hex outside the token sheets** (the 338 pre-existing
violations are filed as EM-193 backlog — the line now holds at zero new).

## Live verification

On the user's running backend (resume-on-boot kept the world through every
hot-reload of the wave — lineage visible in the feed):

```
150  run_resumed  — ▶ resumed run 506 from tick 150
150  god_miracle  — 🌧 Rain falls on the gardens — forage flourishes
```

`POST /api/god/intervene {"kind":"send_rain"}` → `{status: ok, until_tick: 190}`;
live agent payloads carry `reputation`; the witnessing fix was live within one
hot-reload.

## QE follow-ups filed

- **EM-189** (P3): child ids are uuid4 — same-seed runs can't align children
  for cross-run A/B; derive from the seeded birth hash.
- **EM-190** (P3): transient outboxes unserialized — fork-anywhere sharp edge.
- **EM-191** (P3): GRANT reply quotes agent text in god ink — give the quote a
  distinct typographic treatment.
- **EM-192** (P3): B7 follow-ups (town_name on WorldState type, label-ink
  constant migration, real opacity fade).
- **EM-193** (P3): design-token backlog burndown (338 pre-existing errors).

## Deferred this wave (written reasons)

- **EM-126** generations (P3) — the v3 report stages it "depth later"; its
  hook (`parents`) shipped in B2.
- **EM-125's migration half** — reflection-driven *migration* is multi-city
  surface; single-city scope shipped the bond-upgrade path only (user
  direction: deepen the first city before founding a second).
- **EM-182/183** — city-agency, pairs with generator work, separate wave.
- Steal-escalation type changes stamp `since_tick` but emit no
  `relationship_changed` (contract-conformant; the social graph still folds
  conflict events) — recorded, can ride a later batch.

## Handoff

- New live behaviors to watch: first birth (needs a mutual partner pair at a
  home with credits), first faction ("X's circle" in the feed + ring on the
  social graph), GRANT button on the next petition, named streets at close
  zoom, the city's name top-left of the world view.
- W17/W18 remainder: EM-167 (needs Ollama running), EM-169+176 vehicles,
  EM-127 day/night, EM-151 inspector archive, EM-182/183, EM-186 headless
  wiring, EM-189–193 (this wave's P3 batch).
- Branch awaits the user's PR/merge word.

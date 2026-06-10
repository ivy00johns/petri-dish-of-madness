# W10 Build Results — "Trust & hygiene"

**Branch:** `build/w10-trust-hygiene` (stacked on `build/w9-make-v2-true`) · **Date:** 2026-06-09
**Commits:** `0912b12` (contracts+plan) · `61e9d29` (backend) · `82984f0` (config/persistence+roster) ·
`86a5c8e` (frontend) · `80ea7dc` (docs) · `5f42d15` (tests) · closeout.
**Gates:** wave-1 GREEN → QA GREEN (proceed=true) → live verification GREEN.
Full gate log: `coordination/W10_BUILD.md`.

## What shipped

| Item | Result |
|---|---|
| EM-075 replay fidelity | Time-projected building status in replay (status at tick T, not live), animals on the 2D + replay maps, status strip follows the scrub tick, agent energy/credits re-projected from `turn_start` samples (honest `~` where approximate) |
| EM-076 analytics correctness | `active_rules` from real rule state (not event arithmetic); space-exploration reads `payload.place` (W9-QA-1b xfail flipped); speed label synced to server truth |
| EM-077 hardening | WS broadcast evicts dead sockets; Gemini key via `x-goog-api-key` header; governance spawns get real profile colors; spawn input length caps (422) |
| EM-078 docs sync | README screenshot embeds restored atop user edits, two factually-wrong docker commands fixed, db_path documented; V2_BUILD.md unstaled; FUTURE.md promoted items removed; `/api/animals` contracted; dead event kinds pruned from schema |
| **EM-043 closed** (open since v1) | vitest + jsdom + testing-library; **63 tests** pinning every historical frontend regression (fold boundaries, destination chains, gov attribution, play/pause state, hysteresis machine, extinction, animal correlation) |
| EM-084 (user) | Two-click RESET WORLD + extinction-banner NEW RUN CTA — verified end-to-end: run `ended` cleanly on disk, fresh run started, no service restart |
| EM-085 (user) | Runs persist to `<repo>/data/run.sqlite` (env-overridable, parent auto-created, pytest pinned to `:memory:`); 5 historical runs already on disk |
| EM-088 (user) | Live feed seeds from backfilled history on refresh (verified: 50/300 events on fresh load mid-run) |
| EM-089 (user) | Animal model chips (from real `llm_call` correlation) + 🧠 markers on LLM-decided animal actions; mock parity |
| EM-090 (user) | +4 provider-diverse profiles (groq-llama, cerebras-glm, mistral-small, kimi) — 7 real lanes across 7 upstream families |
| EM-072 follow-up (user) | Routing banner hysteresis (5-sample trip, 2-diverse clear) + transient "routing recovered" notice |

## QA

Backend **188 passed / 0 failed**; frontend **63 passed** (1 intentional xfail pinning the
new LOW finding). New finding **W10-QA-1**: the W9 SocialGraph cleanup is dead code under
React 18 ref-detach ordering (mitigated — the library's own destructor pauses the rAF loop);
filed as **EM-097**.

## Live verification highlights

Reset flow proved the whole persistence story in one click: run 4 → `ended` (445 events
preserved), run 5 born at tick 0, UI clean. The duplicate-law finding (EM-087) reproduced
in mock during verification — 3 simultaneously-active UBI rules — and the evidence now
survives on disk. Console: 0 errors throughout.

## Filed during the wave (user session)

EM-086 run browser/cross-run diff, EM-087 duplicate-law semantics, EM-091 billboard,
EM-092 persona library, EM-093 feed scroll stability, EM-094 story-so-far summary,
EM-095 3D camera nav, EM-096 live layout redesign, EM-097 (QA finding), EM-098 (see
ledger) — plus multi-city + transport to `docs/FUTURE.md`.

## Handoff

- W11 is large (15 items): suggest **W11a UI batch** (EM-093→096, 086) then **W11b sim
  texture** (EM-079–083, 087, 091, 092, 097, 098).
- PR opened from `build/w10-trust-hygiene` → `main` (user-requested) — contains the audit,
  W9, and W10.
- Backend `--reload` no longer destroys history (EM-085), but a restart IS a new run.

# PetriDishOfMadness — Remaining Work (tactical ledger)

Every open item, ID'd and prioritized. This is the canonical "what exactly needs doing?"
list. The strategic roadmap (waves + exit criteria) lives in `BUILD-PLAN.md`.

> **Status (2026-06-09):** v1 (W0–W4) and v2 (W5–W8) shipped on `build/v2-expansion`.
> **W9 ✅ + W10 ✅ shipped** (`build/w9-make-v2-true`, `build/w10-trust-hygiene`). W9: deep
> replay, survival pressure, extinction UX, routing banner, P1 bug batches. W10: replay
> fidelity, analytics correctness, API hardening, docs sync, **EM-043 closed (63 frontend
> unit tests)**, plus user-session items: reset button (EM-084), persistent runs (EM-085),
> feed survives refresh (EM-088), animal model chips + 🧠 markers (EM-089), 8-profile
> roster (EM-090), routing-banner hysteresis. Gate logs: `coordination/W{9,10}_BUILD.md`;
> results: `BUILD_RESULTS_W{9,10}.md`. **W11a ✅ shipped** (`build/w11a-ui-batch`): run
> browser + archive mode + cross-run AWI (EM-086), frozen-snapshot feed scroll (EM-093),
> story-so-far digest + narrator mode (EM-094), 3D camera nav (EM-095), chat-first layout
> (EM-096), SocialGraph cleanup (EM-097), critters in roster (EM-099), label declutter
> (EM-102), collapsible legend (EM-104), resizable feed (EM-105). Backend 206 / frontend
> 106 tests. Gate log: `coordination/W11A_BUILD.md`; results: `BUILD_RESULTS_W11A.md`.
> **Next: W11b sim-texture batch (EM-079–083, 087, 091, 092, 098, 100, 101, 103).**

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W11` (see `BUILD-PLAN.md`). W0–W4 shipped (v1); W5–W8 shipped (v2); W9–W11 are the audit-driven v2.1 plan.
- **Area** — `infra` · `contracts` · `backend` · `providers` · `persistence` · `frontend` · `qe`.
- **Source** — where it came from. New items from reports enter via `plan-intake`.
- **Status** — `open` · `in-progress` · `blocked` · `done`.
- **Owner** — agent role or person; `—` if unassigned.

| ID | Pri | Wave | Area | Source | Summary | Status | Owner |
|----|-----|------|------|--------|---------|--------|-------|
| EM-001 | P0 | W0 | infra | spec §2 | Repo scaffold | done | infra |
| EM-002 | P0 | W0 | contracts | spec §3 | Action-protocol JSON schema | done | orch |
| EM-003 | P0 | W0 | contracts | spec §2,6 | WebSocket event schema | done | orch |
| EM-004 | P0 | W0 | contracts | spec §6 | REST control API (OpenAPI) | done | orch |
| EM-005 | P0 | W0 | contracts | spec §2 | SQLite schema | done | orch |
| EM-006 | P0 | W0 | contracts | spec §2,6 | Provider `chat()` interface + config schema | done | orch |
| EM-007 | P0 | W0 | infra | spec §6 | `profiles.yaml` + `world.yaml` templates | done | infra |
| EM-010 | P0 | W1 | backend | spec §2,4 | World model + state | done | backend |
| EM-011 | P0 | W1 | backend | spec §2 | Tick loop + round-robin scheduler | done | backend |
| EM-012 | P0 | W1 | backend | spec §4 | Needs: energy decay + death | done | backend |
| EM-013 | P0 | W1 | backend | spec §4 | Economy: work/forage/recharge/give/steal | done | backend |
| EM-014 | P0 | W1 | backend | spec §4 | Talk + relationships | done | backend |
| EM-015 | P0 | W1 | backend | spec §4 | Governance: propose/vote/effects | done | backend |
| EM-016 | P0 | W1 | backend | spec §5 | Agent context assembly + cheap memory | done | backend |
| EM-017 | P0 | W1 | backend | spec §3 | Action parse + validate + retry + idle fallback | done | backend |
| EM-018 | P0 | W1 | providers | spec §2 | Router + OpenAI-compatible adapter (FreeLLMAPI/Ollama) | done | backend |
| EM-019 | P1 | W1 | providers | spec §2 | Anthropic adapter | done | backend |
| EM-020 | P1 | W1 | providers | spec §2 | Gemini adapter | done | backend |
| EM-021 | P0 | W1 | providers | spec §7 | MockProvider (scripted JSON, deterministic) | done | backend |
| EM-022 | P0 | W1 | persistence | spec §2 | SQLite repository | done | backend |
| EM-030 | P0 | W2 | backend | spec §6 | FastAPI control endpoints | done | backend |
| EM-031 | P0 | W2 | backend | spec §2 | WebSocket broadcaster | done | backend |
| EM-032 | P0 | W2 | frontend | spec §2 | 2D canvas map | done | frontend |
| EM-033 | P0 | W2 | frontend | spec §2,3 | Live event feed, color-coded by model | done | frontend |
| EM-034 | P0 | W2 | frontend | spec §6 | Per-agent panels | done | frontend |
| EM-035 | P0 | W2 | frontend | spec §6 | Control panel + live model reassign + legend | done | frontend |
| EM-036 | P1 | W2 | frontend | spec §2 | WebSocket client + state store | done | frontend |
| EM-040 | P0 | W3 | qe | spec §10 | Engine unit tests (invariants/economy/governance/death) | done | qe/orch |
| EM-041 | P0 | W3 | qe | spec §10 | Integration test: loop lifecycle + invariants | done | qe/orch |
| EM-042 | P1 | W3 | qe | spec §10 | OpenAI-compatible adapter stub test (+ failure path) | done | qe/orch |
| EM-043 | P1 | W3 | qe | spec §10 | Frontend render smoke/unit tests | done | — |
| EM-044 | P0 | W3 | infra | spec §8 | docker-compose (+ opt-in ollama/freellmapi) | done | infra |
| EM-045 | P0 | W3 | infra | spec §8 | Root README + one-command `dev` | done | infra |
| EM-046 | P1 | W3 | infra | spec §8 | Cloud-deploy notes (endpoint swap) | done | infra |
| EM-047 | P0 | W3 | qe | DoD | render-sanity + ux-review gate | done | orch |
| EM-048 | P0 | W3 | qe | spec §12 | **Live ≥2-model arc run (≥5 min)** — DONE: 3 agents / 3 models ran live on FreeLLMAPI >11 min, 3/3 alive, real chat + passed rule | done | orch |
| EM-049 | P1 | W4 | frontend | user req | Cozy 3D village view (React Three Fiber + drei): procedural buildings per place-kind, walking villagers, chat bubbles, orbit cam; default center view + 2D/3D toggle | done | frontend |
| EM-050 | P1 | W4 | providers | user req | Surface actually-routed model — capture `X-Routed-Via` → `payload.routed_via`; display per-villager + feed | done | backend+frontend |
| EM-051 | P1 | W4 | qe | user req | Regression tests for routed_via capture/fallback/injection | done | qe |
| EM-052 | P2 | W4 | config | user req | Seed 3 agents co-located in plaza so conversation starts round 1 | done | orch |
| EM-053 | P0 | W5 | frontend | research-v2 #1 | Add `/inspector` route — a 2D *analysis annex* (3D village stays the **primary** view at `/`); unmount the WebGL canvas while analyzing | done | frontend |
| EM-054 | P0 | W5 | persistence | research-v2 #2 | Append-only event-log schema (OTel-style linked turn traces) + WAL + periodic snapshots | done | persistence |
| EM-055 | P1 | W6 | frontend | research-v2 #3 | Session replay viewer (2D timeline scrubber + top-down Canvas map) | done | frontend |
| EM-056 | P1 | W6 | frontend | research-v2 #4 | Agent decision-trace inspector (perceived → memories → llm_call → reasoning → action) | done | frontend |
| EM-057 | P1 | W6 | frontend | research-v2 #5 | Governance/laws history view w/ downstream-consequence links (the "clock tower" failure) | done | frontend |
| EM-058 | P1 | W6 | frontend | research-v2 #6 | Relationship/social-graph viz (react-force-graph-2d, time-scrub) | done | frontend |
| EM-059 | P1 | W6 | frontend | research-v2 #7 | Analytics: 9-AWI + model-vs-model dashboard (uPlot/Observable Plot) | done | frontend |
| EM-060 | P2 | W7 | backend | research-v2 #8 | Expanded tiered tool catalog (🟢 reflex vs 🔵 LLM-served), location/agreement-gated | done | backend |
| EM-061 | P2 | W7 | backend | research-v2 #9 | Building/structure mutable state model (status/health/progress transitions) | done | backend |
| EM-062 | P2 | W7 | backend | research-v2 #10 | Collective-project pipeline (propose→fund→build→succeed/fail) | done | backend |
| EM-063 | P2 | W7 | backend | research-v2 #11 | Ad-hoc agent spawning mid-run (god-mode + governance-gated flag) | done | backend |
| EM-064 | P3 | W8 | backend | research-v2 #12 | LLM-driven cat & dog as distinct `actor_type:"animal"` chaos entities | done | backend |
| EM-065 | P3 | W8 | frontend | research-v2 #13 | Animal Chaos Feed + `is_chaotic` tagging/surfacing (magenta on timeline) | done | frontend |
| EM-066 | P1 | W5 | contracts | research-v2 §patterns | Structured decision-trace action output `{perceived_summary, memories_used, reasoning, chosen_tool, args}` in one call (enabler for EM-054/056) | done | backend |
| EM-067 | P1 | W6 | providers | research-v2 §x-cut | Per-provider RPD/TPD usage tracking in event log + cap-aware throttling; **also emit per-attempt `llm_call` rows** (W5 logs only the final attempt — see Notes) | done | providers |
| EM-068 | P2 | W7 | providers | research-v2 §x-cut | Decision/prompt-prefix caching (persona + memory-hash + coarse-world-state) | done | providers |
| EM-069 | P0 | W9 | frontend | audit §C1 | Wire deep replay: inspector boots from `/api/events`, scrub uses `/api/replay` snapshot+delta (filtered past `base.tick`), panels read beyond rolling window, fold-forward boundary fix, scrub pins panels | done | — |
| EM-070 | P0 | W9 | backend | audit §A1 | Survival pressure: needs salience in turn prompt, no-charge recharge-at-full, starvation feed warnings, death-countdown surfacing | done | — |
| EM-071 | P1 | W9 | frontend | audit §A2 | Extinction/run-end UX: auto-pause or banner on 0 alive + end-of-run summary card | done | — |
| EM-072 | P1 | W9 | frontend | audit §A4 | Routing-degraded banner when all live profiles resolve to one routed model | done | — |
| EM-073 | P1 | W9 | backend | audit §B1–B4,B6 | Backend correctness batch: animal turn_id stamp, reset awaits tick task, ban_arson proposable, build_step accepts funded `planned`, duplicate llm_call dedupe | done | — |
| EM-074 | P1 | W9 | frontend | audit §C2,C3,C5,C6,C10 | Frontend correctness batch: replay play/pause state, WS reconnect cleanup+backoff, force-graph pause fix, AWI gov column, synthetic-event seq collision | done | — |
| EM-075 | P2 | W10 | frontend | audit §B8,C7,D3,D4 | Replay fidelity: snapshot round/scheduler state, time-projected building status, replay-map legibility, animals on 2D map | done | — |
| EM-076 | P2 | W10 | backend | audit §B9,D5 | Analytics correctness: active_rules formula/source of truth; speed label synced to server tick interval | done | — |
| EM-077 | P2 | W10 | backend | audit §B10–B12,B14,B15 | Platform hardening: WS broadcast cleanup, Gemini key via header, decision-cache flush on reset, spawn input length caps, profile-color helper | done | — |
| EM-078 | P2 | W10 | contracts | audit §E1–E5 | Docs/contracts sync: README screenshot/chaos-feed regression fix, `/api/animals` in OpenAPI, event-kind schema sync, V2_BUILD.md + FUTURE.md refresh | done | — |
| EM-079 | P2 | W11 | backend | audit §F / research-v2 §rec | Active-commitments injection in turn prompt + ignored-commitment logging (clock-tower pressure) | open | — |
| EM-080 | P2 | W11 | backend | audit §F / research-v2 §rec | Reflection/diary on importance threshold (~2–3×/day, Smallville pattern) | open | — |
| EM-081 | P2 | W11 | backend | audit §F / FUTURE.md | Reactive overhearing chains, capped (1–2 listeners) + reflex-first responses (free-scale) | open | — |
| EM-082 | P2 | W11 | frontend | audit §D1,D6 | Mobile decision (stacked read-only layout OR explicit min-width gate) + semantic headings / a11y pass | open | — |
| EM-083 | P3 | W11 | backend | audit §B13 / research-v2 §bench | Make `blackout` event effect real; benchmark alerts on EM-067 usage data (>70% RPD/TPD → warn) | open | — |

| EM-084 | P1 | W10 | frontend | user 2026-06-09 | Reset/new-run button in UI (extinction banner CTA + control panel) wired to existing `POST /api/control/reset` — no more service restarts | done | — |
| EM-085 | P1 | W10 | infra | user 2026-06-09 | Persist runs by default: file `db_path` (`data/run.sqlite`) in config/world.yaml + gitignore `data/` — runs currently die with the process (`:memory:`) | done | — |
| EM-086 | P2 | W11 | frontend | user 2026-06-09 | Run browser: list past runs (`GET /api/runs` + run_id-scoped reads), load any run into the inspector, cross-run AWI comparison ("what changed between sessions") | done | — |
| EM-087 | P2 | W11 | backend | user 2026-06-09 | Duplicate-law semantics: engine allows re-proposing an already-ACTIVE effect → stacks of identical active laws (verified: only `proposed` status is guarded, world.py:473-476). Decide reject-vs-amend/renew + group repeats in governance UI | open | — |

| EM-088 | P1 | W10 | frontend | user 2026-06-09 | Live feed survives refresh: seed the `/` EventFeed from the EM-069 backfilled history (last N events) instead of starting empty at WS connect | done | — |

| EM-089 | P2 | W10 | frontend | user 2026-06-09 | Surface animal model identity: critter label/panel shows `animals.model_profile` (+ routed_via when an LLM served the turn); feed/chaos-feed distinguishes 🧠 LLM decisions from reflex micro-behaviors | done | — |

| EM-090 | P2 | W10 | config | user 2026-06-09 | Expand model roster: +4 FreeLLMAPI profiles chosen for provider diversity (groq-llama, cerebras-glm, mistral-small, kimi) — one exhausted tier can't collapse the A/B; ids verified in live catalog | done | orch |

| EM-091 | P2 | W11 | backend | user 2026-06-09 / research-v2 §tools | Village billboard: 🟢 reflex `post_billboard`/`read_billboard` tools (post text rides the same LLM turn — zero extra calls), `billboard_posted` events, physical notice board in the 3D village + panel/feed surface, god-panel "respond/grant" affordance for agent petitions to the watchers; counts toward Public Expression AWI | open | — |

| EM-092 | P2 | W11 | config | user 2026-06-09 | Persona library: config-defined character cards (name, personality, archetype, suggested profile) — god-panel spawn picker offers the roster alongside the freeform custom fields; seed mix configurable per run. Reusable casting pool for the multi-world plans (FUTURE.md) | open | — |

| EM-093 | P1 | W11 | frontend | user 2026-06-09 | Feed scroll stability: new messages still jump the scroll position despite the "X new"/LIVE pin — anchor scroll when not pinned (prepend-safe, e.g. scrollTop compensation or overflow-anchor), never yank the user while reading | done | — |
| EM-094 | P2 | W11 | frontend | user 2026-06-09 | Running "story so far" summary: computed zero-LLM digest (deaths, active rules, project status, current-drama heuristics) always on; optional Narrator mode = cheap-profile LLM 2-3 sentence recap every N ticks, off by default, rate-limited (free-scale) | done | — |
| EM-095 | P2 | W11 | frontend | user 2026-06-09 | 3D camera navigation: currently orbit-only around town center — add pan, zoom-to-place (click a building), and follow-agent mode (track a villager), with a reset-view control | done | — |
| EM-096 | P2 | W11 | frontend | user 2026-06-09 | Live layout redesign (user sketch): full-height feed + summary in a wider LEFT column, agents as a horizontally-scrollable card strip at the BOTTOM of the world view (badges stay visible), controls stay right, village gets ~2x the pixels. Sequence after EM-093 so the new layout starts scroll-stable | done | — |

| EM-097 | P3 | W11 | frontend | qa W10-QA-1 | SocialGraph unmount cleanup reads a React-18-detached ref (dead code; mitigated — force-graph's own destructor pauses the rAF loop). Replace with a captured-instance cleanup or delete the false safety net + its comment; un-xfail the pin in SocialGraph tests | done | — |

| EM-098 | P2 | W11 | backend | user 2026-06-09 | Expanded building/place catalog + seeded procedural town generation: config `world.procgen {enabled, seed, n_places, kind_weights}` lays out a varied town (more place kinds + building types, road-aware positions); 3D already renders per-kind so visuals scale. Gate place count for prompt size (free-scale); per-run generated towns pair with EM-085 persistence + the FUTURE multi-city plan. **Housing (user 2026-06-09):** today there is ONE communal Hearth and zero per-agent homes — the expanded catalog must include `home` variants: per-agent cottages ("Ada's cottage") and/or a capacity-limited communal bunkhouse (beds < agents ⇒ scarcity drama); recharge wires to them; ownership/rent (credits sink) is a deliberate follow-on, not in-scope | open | — |
| EM-099 | P2 | W11 | frontend | user 2026-06-09 | Pets join the agents sidebar: CRITTERS section under AGENTS with mood, model chip (they're LLM-powered), location, and chaos count; click focuses them like agents | done | — |

| EM-100 | P3 | W11 | backend | user 2026-06-09 | Human-readable rule names in feed lines: `rule_vote`/`rule_passed` text uses the rule's text/effect ("'Everyone deserves a basic income' (ubi) PASSED"), not the bare rule_id hex; keep the id in payload | open | — |
| EM-101 | P2 | W11 | backend | user 2026-06-09 | Run fork/resume: `World.from_snapshot()` (snapshot+delta → live world at tick T, the missing restore half of W9/B8) + `POST /api/runs/fork {run_id, tick, place_overrides?}` starting a NEW run with lineage (`forked_from`). `place_overrides` lets a forked society wake up in a different town (EM-098 procgen / FUTURE multi-city: "session from turn X meets a different city"). Surface in run browser (EM-086) | open | — |

| EM-102 | P2 | W11 | frontend | user 2026-06-09 | 3D building-label declutter: labels overlap each other and agent/critter chips (new buildings make it worse) — zoom/distance-gated visibility, fade or occlusion culling, and non-colliding placement for the in-canvas Html labels | done | — |
| EM-103 | P2 | W11 | backend | user 2026-06-09 | Legislation-as-architecture guard: agents built a Monument named after a LAW ("Festival Fund Transparency Initiative") alongside a second monument — project/rule cross-contamination. Keep the emergent charm but add semantics: project proposals that duplicate an active/proposed rule's name get steered to governance (or flagged commemorative + linked to the rule); dedupe near-identical monuments. Pairs with EM-087 duplicate-law semantics | open | — |
| EM-104 | P2 | W11 | frontend | user 2026-06-09 | Collapsible model legend in the controls column (8-profile roster eats vertical space) | done | — |

| EM-105 | P2 | W11 | frontend | user 2026-06-09 | Expandable feed column: user-resizable width via drag handle on the feed/world boundary (persisted in localStorage), with sane min/max so the village never collapses; pairs with the EM-096 layout | done | — |

| EM-106 | P3 | — | infra | docs-agent W11b | docker-compose: ship a named volume for `data/` on the backend service by default (runs persist to data/run.sqlite since W10; README documents the manual override, compose should just do it) | open | — |

| EM-107 | P1 | W11 | frontend | user 2026-06-09 | Banner mount/unmount reflows the whole app ("zooms in and out", eye strain) — routing-degraded/recovered + usage-alert banners must not shift layout: overlay them (or reserve the row) with a reduced-motion-safe fade, so appearance/clearing never moves content | open | — |

| EM-108 | P3 | — | backend | qa W11b | Governance location gate is prompt-only: `_validate_world` never location-checks `propose_rule`/`vote` despite the TOOL_REGISTRY comment claiming resolution-time enforcement — a prompt-ignoring model can legislate from anywhere. Enforce at resolution (match the billboard gate pattern) | open | — |

_Next free ID: EM-109._

## Notes

- **EM-048** is the project goal. The engine has run 1,600+ ticks continuously on the
  deterministic MockProvider (well past 5 minutes) with deaths, alliances, and passed rules,
  and the OpenAI-compatible adapter is verified end-to-end against a FreeLLMAPI-shaped stub
  (incl. the failure→idle path). The only remaining step is supplying a real token — see the
  "Run the 5-minute 2-model demo" section of `README.md` and `BUILD_RESULTS.md`.
- **EM-043** re-scoped 2026-06-09 (was "v1.1 nice-to-have"): the audit found four frontend
  bugs (audit §C2, C4, C5, C6) that component/selector unit tests would have caught. Target it
  in W10 at the selectors + ReplayScrubber + AWIDashboard layer, regression-proofing the W9
  fixes (EM-069/074).
- **EM-053–EM-068 (v2 expansion)** entered 2026-06-08 via `plan-intake` from
  `docs/research/deep-research-v2.md`. They open **W5–W8** (Foundations → Instrumentation →
  Expanded world → Chaos animals). **W5 (EM-053/054/066) is the gate**: every later item reads
  the append-only event log, so lock that schema before building any Phase-1 UI. The report's
  own priority scale was translated into this ledger's "blocks-the-wave" P0–P3 semantics.
- **EM-079 scope note (2026-06-09, live-run observation):** agents roleplay world changes
  instead of executing them — a full run produced ZERO `project_*`/`structure_*` events while
  the agents verbally "completed" a community garden (every turn resolved to `say`). EM-079
  must cover the step BEFORE follow-through too: make non-talk tools salient enough that
  intentions become `propose_project`/`build_step` calls, and log talk-only "phantom
  commitments" (claimed in speech, never enacted) as a visible failure mode.
- **EM-086 implementation notes (from EM-085 verification, 2026-06-09):** (1) run `status`
  is unreliable for "active" — restarts/hot-reloads never call `end_run`, so dead runs stay
  `running` forever; the run browser must treat `MAX(id)` (or latest `started_at`) as active.
  (2) the `places` table is keyed on bare place id with `INSERT OR REPLACE`, so each run
  re-owns the rows — prior runs' places must come from their tick-0 snapshot `state_json`
  (or composite-key the table `(run_id, id)`). `agents`/`rules` use uuid ids and are safe.
  (3) Animal wander `animal_action` events carry no destination `place` — per-tick animal
  replay is approximate (`~`-flagged in the UI); emitting `payload.place` on animal moves
  would make it exact (small additive backend change, pairs well with EM-086).
- **EM-069–EM-083 (v2.1 audit plan)** entered 2026-06-09 via `plan-intake` from
  `docs/audit-2026-06-09.md` (companion UX detail: `docs/ux-review-2026-06-09.md`). They open
  **W9–W11** (Make v2 true → Trust & hygiene → New texture). **W9 (EM-069–074) is the gate**:
  EM-069 closes the gap between "EM-055 done" and the actual deep-replay promise, and EM-070
  fixes the starve-to-extinction failure observed live (all 3 agents died with credits in hand
  while planning a festival). `audit §Xn` source refs point at the theme/finding IDs inside
  the audit doc. No new entry was filed for frontend tests — that folds into the still-open
  EM-043 (see above).

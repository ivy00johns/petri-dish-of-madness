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
> **W11b ✅ shipped** (same branch): commitments + 👻 phantom logging (EM-079), reflections
> (EM-080), overhearing (EM-081), min-width gate + a11y (EM-082), real blackouts + usage
> alerts (EM-083), law RENEWAL semantics (EM-087), billboard + god replies (EM-091),
> persona library (EM-092), procgen towns + housing (EM-098), readable rule names
> (EM-100), run fork/resume (EM-101), commemorative-monument guard (EM-103), layout-stable
> banners (EM-107). Backend 252 / frontend 150 tests. Gate log: `coordination/
> W11B_BUILD.md`; results: `BUILD_RESULTS_W11B.md`. **W9–W11 complete. Open: EM-106 (compose
> data/ volume), EM-108 (governance location gate) — both small, unscheduled.**
> **v3 (Village→Civilization) filed 2026-06-09** via `plan-intake` from
> `docs/research/deep-research-v3.md` — **EM-109–128**, opening **W12–W14**. Every hard
> prereq already shipped in W11a/W11b (fork/resume EM-101, persona library EM-092,
> procgen+housing EM-098, reflection EM-080, run browser EM-086), so v3 is unblocked. Build
> order per user: **deepen the first city before founding a second.**

## Format & conventions

- **ID** — `EM-###`. Stable, never reused. New items take the next free number.
- **Priority** — `P0` (blocks the wave) · `P1` (needed for v1, not blocking) · `P2` (nice-to-have) · `P3` (deferred-ish).
- **Wave** — `W0`–`W14` (see `BUILD-PLAN.md`). W0–W4 shipped (v1); W5–W8 shipped (v2); W9–W11 shipped (v2.1 audit-driven); W12–W14 are the v3 Village→Civilization plan.
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
| EM-079 | P2 | W11 | backend | audit §F / research-v2 §rec | Active-commitments injection in turn prompt + ignored-commitment logging (clock-tower pressure) | done | — |
| EM-080 | P2 | W11 | backend | audit §F / research-v2 §rec | Reflection/diary on importance threshold (~2–3×/day, Smallville pattern) | done | — |
| EM-081 | P2 | W11 | backend | audit §F / FUTURE.md | Reactive overhearing chains, capped (1–2 listeners) + reflex-first responses (free-scale) | done | — |
| EM-082 | P2 | W11 | frontend | audit §D1,D6 | Mobile decision (stacked read-only layout OR explicit min-width gate) + semantic headings / a11y pass | done | — |
| EM-083 | P3 | W11 | backend | audit §B13 / research-v2 §bench | Make `blackout` event effect real; benchmark alerts on EM-067 usage data (>70% RPD/TPD → warn) | done | — |

| EM-084 | P1 | W10 | frontend | user 2026-06-09 | Reset/new-run button in UI (extinction banner CTA + control panel) wired to existing `POST /api/control/reset` — no more service restarts | done | — |
| EM-085 | P1 | W10 | infra | user 2026-06-09 | Persist runs by default: file `db_path` (`data/run.sqlite`) in config/world.yaml + gitignore `data/` — runs currently die with the process (`:memory:`) | done | — |
| EM-086 | P2 | W11 | frontend | user 2026-06-09 | Run browser: list past runs (`GET /api/runs` + run_id-scoped reads), load any run into the inspector, cross-run AWI comparison ("what changed between sessions") | done | — |
| EM-087 | P2 | W11 | backend | user 2026-06-09 | Duplicate-law semantics: engine allows re-proposing an already-ACTIVE effect → stacks of identical active laws (verified: only `proposed` status is guarded, world.py:473-476). Decide reject-vs-amend/renew + group repeats in governance UI | done | — |

| EM-088 | P1 | W10 | frontend | user 2026-06-09 | Live feed survives refresh: seed the `/` EventFeed from the EM-069 backfilled history (last N events) instead of starting empty at WS connect | done | — |

| EM-089 | P2 | W10 | frontend | user 2026-06-09 | Surface animal model identity: critter label/panel shows `animals.model_profile` (+ routed_via when an LLM served the turn); feed/chaos-feed distinguishes 🧠 LLM decisions from reflex micro-behaviors | done | — |

| EM-090 | P2 | W10 | config | user 2026-06-09 | Expand model roster: +4 FreeLLMAPI profiles chosen for provider diversity (groq-llama, cerebras-glm, mistral-small, kimi) — one exhausted tier can't collapse the A/B; ids verified in live catalog | done | orch |

| EM-091 | P2 | W11 | backend | user 2026-06-09 / research-v2 §tools | Village billboard: 🟢 reflex `post_billboard`/`read_billboard` tools (post text rides the same LLM turn — zero extra calls), `billboard_posted` events, physical notice board in the 3D village + panel/feed surface, god-panel "respond/grant" affordance for agent petitions to the watchers; counts toward Public Expression AWI | done | — |

| EM-092 | P2 | W11 | config | user 2026-06-09 | Persona library: config-defined character cards (name, personality, archetype, suggested profile) — god-panel spawn picker offers the roster alongside the freeform custom fields; seed mix configurable per run. Reusable casting pool for the multi-world plans (FUTURE.md) | done | — |

| EM-093 | P1 | W11 | frontend | user 2026-06-09 | Feed scroll stability: new messages still jump the scroll position despite the "X new"/LIVE pin — anchor scroll when not pinned (prepend-safe, e.g. scrollTop compensation or overflow-anchor), never yank the user while reading | done | — |
| EM-094 | P2 | W11 | frontend | user 2026-06-09 | Running "story so far" summary: computed zero-LLM digest (deaths, active rules, project status, current-drama heuristics) always on; optional Narrator mode = cheap-profile LLM 2-3 sentence recap every N ticks, off by default, rate-limited (free-scale) | done | — |
| EM-095 | P2 | W11 | frontend | user 2026-06-09 | 3D camera navigation: currently orbit-only around town center — add pan, zoom-to-place (click a building), and follow-agent mode (track a villager), with a reset-view control | done | — |
| EM-096 | P2 | W11 | frontend | user 2026-06-09 | Live layout redesign (user sketch): full-height feed + summary in a wider LEFT column, agents as a horizontally-scrollable card strip at the BOTTOM of the world view (badges stay visible), controls stay right, village gets ~2x the pixels. Sequence after EM-093 so the new layout starts scroll-stable | done | — |

| EM-097 | P3 | W11 | frontend | qa W10-QA-1 | SocialGraph unmount cleanup reads a React-18-detached ref (dead code; mitigated — force-graph's own destructor pauses the rAF loop). Replace with a captured-instance cleanup or delete the false safety net + its comment; un-xfail the pin in SocialGraph tests | done | — |

| EM-098 | P2 | W11 | backend | user 2026-06-09 | Expanded building/place catalog + seeded procedural town generation: config `world.procgen {enabled, seed, n_places, kind_weights}` lays out a varied town (more place kinds + building types, road-aware positions); 3D already renders per-kind so visuals scale. Gate place count for prompt size (free-scale); per-run generated towns pair with EM-085 persistence + the FUTURE multi-city plan. **Housing (user 2026-06-09):** today there is ONE communal Hearth and zero per-agent homes — the expanded catalog must include `home` variants: per-agent cottages ("Ada's cottage") and/or a capacity-limited communal bunkhouse (beds < agents ⇒ scarcity drama); recharge wires to them; ownership/rent (credits sink) is a deliberate follow-on, not in-scope | done | — |
| EM-099 | P2 | W11 | frontend | user 2026-06-09 | Pets join the agents sidebar: CRITTERS section under AGENTS with mood, model chip (they're LLM-powered), location, and chaos count; click focuses them like agents | done | — |

| EM-100 | P3 | W11 | backend | user 2026-06-09 | Human-readable rule names in feed lines: `rule_vote`/`rule_passed` text uses the rule's text/effect ("'Everyone deserves a basic income' (ubi) PASSED"), not the bare rule_id hex; keep the id in payload | done | — |
| EM-101 | P2 | W11 | backend | user 2026-06-09 | Run fork/resume: `World.from_snapshot()` (snapshot+delta → live world at tick T, the missing restore half of W9/B8) + `POST /api/runs/fork {run_id, tick, place_overrides?}` starting a NEW run with lineage (`forked_from`). `place_overrides` lets a forked society wake up in a different town (EM-098 procgen / FUTURE multi-city: "session from turn X meets a different city"). Surface in run browser (EM-086) | done | — |

| EM-102 | P2 | W11 | frontend | user 2026-06-09 | 3D building-label declutter: labels overlap each other and agent/critter chips (new buildings make it worse) — zoom/distance-gated visibility, fade or occlusion culling, and non-colliding placement for the in-canvas Html labels | done | — |
| EM-103 | P2 | W11 | backend | user 2026-06-09 | Legislation-as-architecture guard: agents built a Monument named after a LAW ("Festival Fund Transparency Initiative") alongside a second monument — project/rule cross-contamination. Keep the emergent charm but add semantics: project proposals that duplicate an active/proposed rule's name get steered to governance (or flagged commemorative + linked to the rule); dedupe near-identical monuments. Pairs with EM-087 duplicate-law semantics | done | — |
| EM-104 | P2 | W11 | frontend | user 2026-06-09 | Collapsible model legend in the controls column (8-profile roster eats vertical space) | done | — |

| EM-105 | P2 | W11 | frontend | user 2026-06-09 | Expandable feed column: user-resizable width via drag handle on the feed/world boundary (persisted in localStorage), with sane min/max so the village never collapses; pairs with the EM-096 layout | done | — |

| EM-106 | P3 | — | infra | docs-agent W11b | docker-compose: ship a named volume for `data/` on the backend service by default (runs persist to data/run.sqlite since W10; README documents the manual override, compose should just do it) | done | wave-A 2026-06-10 |

| EM-107 | P1 | W11 | frontend | user 2026-06-09 | Banner mount/unmount reflows the whole app ("zooms in and out", eye strain) — routing-degraded/recovered + usage-alert banners must not shift layout: overlay them (or reserve the row) with a reduced-motion-safe fade, so appearance/clearing never moves content | done | — |

| EM-108 | P3 | — | backend | qa W11b | Governance location gate is prompt-only: `_validate_world` never location-checks `propose_rule`/`vote` despite the TOOL_REGISTRY comment claiming resolution-time enforcement — a prompt-ignoring model can legislate from anywhere. Enforce at resolution (match the billboard gate pattern) | done | wave-A 2026-06-10 |

| EM-109 | P0 | W12 | persistence | research-v3 | Multi-city data model: `cities`/`city_links`/`agent_location` tables + a 2nd settlement rendered on the 2D map; ONE tick loop + per-city context scoping so prompt size stays flat (free-scale). Keystone unblocking travel/trade/diplomacy/parallel-worlds | open | — |
| EM-110 | P0 | W12 | backend | research-v3 | Reflex `travel_to(city)` → `in_transit_to`/`transit_arrival_tick` (agent off-board, zero LLM calls until `agent_arrived`); migration re-points credits/skills/memories(top-K)/relationship edges to the new `city_id`. Deps EM-109 | open | — |
| EM-111 | P0 | W12 | frontend | research-v3 | Art win #1: warm CC0 HDRI (`<Environment>`) + `MeshToonMaterial` 3-tone ramp (NearestFilter, no mipmaps) + drei `<AccumulativeShadows>` on existing geometry. Isolated from engine, most shareable demo; CC0-only + `CREDITS.md`/`ASSET_LICENSES.md` | done | wave-B 2026-06-10 |
| EM-112 | P0 | W12 | backend | research-v3 | Parallel-worlds runner: `runs.model_family` + "seed all agents from family X" casting + **sequential** tournament (snapshot→next, never concurrent — protects FreeLLMAPI free tiers) + run-browser entry. Deps EM-101 ✅, EM-092 ✅, EM-086 ✅ | open | — |
| EM-113 | P1 | W12 | backend | research-v3 | Relationship depth schema: `type`(friend/partner/family/mentor/rival/feud)/`strength`(float)/`valence`/`since_tick`; changes are reflex consequences of existing talk/give/steal/vote; typed+colored edges in the social graph. Precondition for children/factions/diplomacy | open | — |
| EM-114 | P1 | W12 | backend | research-v3 | Lightweight children: partner-above-threshold + reflex consent → reflex `child_spawned` casts a blended persona (traits crossed from parents) on a **cheaper routed model**, acting every N ticks; hard population cap (~12–16), births gated by housing + credits. Deps EM-092 ✅, EM-113 | open | — |
| EM-115 | P1 | W12 | backend | research-v3 | City-growth slice: one collective project (existing propose→fund→build pipeline) instantiates a new instanced building when funded; town visibly gains a building (replay scrubber). Reflex/deterministic given completed projects — no extra LLM calls | done | wave-B 2026-06-10 |
| EM-116 | P1 | W13 | backend | research-v3 | Inter-city trade caravans: reflex `send_caravan(to_city, goods, credits)` → `trade_dispatched`, reflex settlement on arrival (`trade_settled`); optional lightweight `merchant` actor_type on cheaper/less-frequent calls. Deps EM-109, EM-110 | open | — |
| EM-117 | P1 | W13 | backend | research-v3 | Diplomacy via governance: city-scoped treaties/alliances/rivalries ratified by each city's ~70% vote threshold; relationship edges gain `scope` (agent-agent vs city-city); bundles shipped governance texture (EM-079/087/100/103). Deps EM-109, EM-113 | open | — |
| EM-118 | P1 | W13 | frontend | research-v3 | Art phase 2: instanced trees/foliage (KayKit Forest / Quaternius Nature) via drei `<Instances>`/`<Merged>` + LOD `<Detailed>`; hold ≥60fps alongside 2D instrumentation. Deps EM-111 | done | wave-B 2026-06-10 |
| EM-119 | P1 | W13 | frontend | research-v3 | Model-Family Arena: side-by-side cross-run AWI sparklines per family + civilization-outcome cards (population/laws/buildings/crimes/credits) on the existing uPlot/Observable Plot stack — the Gemini-vs-Claude crime/culture contrast demo. Deps EM-112, EM-086 ✅ | open | — |
| EM-120 | P2 | W13 | backend | research-v3 | Factions + feuds + reputation: `factions`/`faction_membership` tables, reputation = derived per-agent aggregate; faction hulls on the graph + reputation column in the agent strip. Extends EM-113 | open | — |
| EM-121 | P2 | W13 | frontend | research-v3 | Multi-city camera (rescoped): zoom-to-city / follow-agent-across-cities + reset-view for the multi-settlement view. Base orbit/pan/zoom-to-place (EM-095 ✅) + label declutter (EM-102 ✅) already shipped W11a — this is the multi-city delta only | open | — |
| EM-122 | P2 | W14 | frontend | research-v3 | Art phase 3: buildings-per-place-kind mesh swap (KayKit Hexagon / Kenney Fantasy Town) wired to the building-state model + procgen layout; distinct building types per zone. Deps EM-098 ✅, EM-115 | done | wave-B 2026-06-10 |
| EM-123 | P2 | W14 | backend | research-v3 | City-growth depth: `neighborhoods` table + `places.neighborhood_id`/`zone_kind`(residential/market/civic/industrial/farm)/`tier`; zoned districts grow as megaprojects complete. Deps EM-115 | open | — |
| EM-124 | P2 | W14 | frontend | research-v3 | Art phase 4 (rescoped): 3D character mesh swap (KayKit Adventurers / Quaternius Modular) with per-model color tint. Pets-in-sidebar (EM-099 ✅) already shipped W11a — character swap only | open | — |
| EM-125 | P2 | W14 | backend | research-v3 | Reflection-driven society: importance-threshold reflection (**consumes** EM-080 ✅) occasionally upgrades a relationship type (cheap, throttled LLM touch) and triggers reflection-driven migration. Deps EM-080 ✅, EM-113 | open | — |
| EM-126 | P3 | W14 | backend | research-v3 | Generational depth: life stages/aging (child→adult→elder cadence + tool unlocks), inheritance of credits/relationships/grudges on death, lineage tree in the inspector. Deps EM-114 | open | — |
| EM-127 | P3 | W14 | frontend | research-v3 | Art phase 5: day/night + seasons + particles (chimney smoke, fireflies) + sparing `<Bloom>`/`<Vignette>` + filmic tone mapping (`antialias:false`, post handles AA). Deps EM-111 | open | — |
| EM-128 | P3 | W14 | frontend | research-v3 | Population-dynamics + culture-drift AWI metrics compared across model families (population/laws/culture charts per family). Deps EM-112, EM-126 | open | — |

| EM-129 | P2 | W12 | backend | user 2026-06-09 | Humanize agent-built building names: raw snake_case args render verbatim in 3D labels + feed ("prepare_beds", "village_fair") — `action_propose_project` should derive a display name (underscores→spaces, title case) while keeping the raw string in payload; trim/reject empty or identifier-only names | done | wave-A 2026-06-10 |
| EM-130 | P2 | W12 | frontend | user 2026-06-09 | Every unknown building kind renders as "Monument": `buildingStyle()` falls back to the monument palette/tag, so a market stall is labeled Monument — add a neutral "Building" fallback style and map common emergent kinds (stall/market/pavilion/inn/…) onto existing palettes | done | wave-A 2026-06-10 |
| EM-131 | P2 | W12 | frontend | user 2026-06-09 | Building placement overlap: new projects spawn at `agent.location`, so meshes pile onto the same spot and labels collide again at plaza density (EM-102 declutter insufficient once the town grows) — slot/offset placement around the place + a declutter second pass for dense clusters. Pairs with EM-115 city-growth slice | done | wave-A 2026-06-10 |

| EM-132 | P2 | W12 | backend | user 2026-06-09 | `build_step` on a damaged building wastes the turn ("is damaged, not under_construction" → idle fallback) — auto-redirect build_step→repair when status=damaged (intent is unambiguous), or surface building status in the prompt so models pick repair themselves | done | wave-A 2026-06-10 |
| EM-133 | P2 | W12 | backend | user 2026-06-09 | Funding overshoot: `action_contribute_funds` accepts unlimited credits with no clamp at `funds_required` (booth hit 12/5) — clamp contributions to the remaining gap (refund/reject overflow with guidance); overspent credits matter when recharge costs 2 and agents starve | done | wave-A 2026-06-10 |
| EM-134 | P3 | W12 | backend | user 2026-06-09 | Animal-damage cooldown: `animal_damage_building` has no rate limit — same critter re-damaged the same booth twice in 6 ticks, immediately after a repair. Per-building cooldown ticks (or diminishing chance) so new builds aren't perma-griefed; keep the chaos, lose the lock | done | wave-A 2026-06-10 |
| EM-135 | P2 | W12 | backend | user 2026-06-09 | Reroute-aware lane health ("smarter routing"): the proxy silently reroutes lanes to models with incompatible output behavior (reasoning CoT eats budget; mistral-medium cuts mid-JSON reporting 'stop' — runs 102/126). Hotfixes salvage individual turns (repair/boost/cache-evict, `fix/reasoning-model-token-exhaustion`); the durable fix is per-`routed_via` health tracking in the Router — remember which routed models truncate/fail-to-parse and adapt (first-attempt budget bump per lane, or deprioritize/quarantine a lane that keeps mangling JSON). Zero standing extra calls; observability via existing `llm_call` rows | done | wave-A 2026-06-10 |
| EM-136 | P1 | W12 | backend | user 2026-06-10 | Targeted god interventions: every god lever is world-wide (windfall/famine/blackout/festival hit ALL agents) — user watched an agent starve with no way to help it. Engine seam `world.god_intervene(kind, agent_id, amount)` for `bless_energy` / `grant_credits` (clamped, reflex, zero LLM) + `POST /api/god/intervene`; emits `god_intervention` (actor_type god, target_id) in god ink | done | wave-A 2026-06-10 |
| EM-137 | P1 | W12 | backend | user 2026-06-10 | God whisper (targeted proclamation): one-shot context injection into ONE agent's next prompt (proclamation mechanics, single-target, consumed on delivery) — the precision tool ("go recharge, now"). `world.post_whisper_as_god(agent_id, text)` + `POST /api/god/whisper`; feed shows "✦ god whispers to {name}" in god ink | done | wave-A 2026-06-10 |
| EM-138 | P1 | W12 | frontend | user 2026-06-10 | God panel revamp: ControlPanel god section becomes a grouped GOD CONSOLE — (1) world events (existing 4 injects), (2) per-agent intervention row (agent selector → BLESS +energy / GRANT +credits / WHISPER text), (3) voice tools (billboard reply + proclamation, existing). Consumes EM-136/137; god-ink styling throughout | done | wave-A 2026-06-10 |

| EM-139 | P1 | W12 | frontend | user 2026-06-10 | Story-digest PROJECTS line was unbounded: day-197 run enumerated ~50 destroyed projects as one wall of text, making the feed unscrollable — live projects named (capped at 3, +N more), settled statuses aggregated to counts (`projectReadout`, lib/storySoFar.ts) | done | wave-A 2026-06-10 |

| EM-140 | P1 | W12 | backend | user 2026-06-10 | Behavioral-arg normalization: run 189 burned 55 turns on `move_to` with the place under a guessed key/null ("unknown place 'None'" — the prompt never documented the arg) and 119 turns on social actions targeting agents by NAME while the world keys by id (the prompt lists names). Fix: `_normalize_args` collapses alias keys (destination→place, case-insensitive places) and resolves names→ids (living/co-located preferred); prompt now documents `move_to (place)` with the place list; clearer validator feedback; `rejected_action` forensics in parse_failure payloads | done | wave-A 2026-06-10 |

| EM-141 | P1 | W12 | frontend | user 2026-06-10 | Inspector archive view died on building-heavy runs: socialGraph folded conflict/economy events with a BUILDING target_id into relationship edges, d3-force threw "node not found: bld_…" 50× and the run-189 view never loaded — edges now filtered to agent-node endpoints (selectors.ts) | done | wave-A 2026-06-10 |

| EM-142 | P1 | W12 | backend | user 2026-06-10 | Over-cap behavioral strings dead-turned agents (Cleo: 60-char propose_project `function` vs cap 40; Bram: 300-char billboard vs 280): `_ARG_STRING_CAPS` in `_normalize_args` truncates display-text args to their schema caps instead of failing the turn | done | wave-A 2026-06-10 |

| EM-143 | P2 | W13 | backend | user 2026-06-10 | God-spawn critters: god console "add critter" affordance (species picker) + `POST /api/god/spawn_animal {species, name?}` registering the animal live in AnimalRuntime; expand the species roster beyond cat/dog (squirrel, …) with `ANIMAL_STYLES` entries + per-species chaos flavor; population cap so chaos stays affordable (animal turns are reflex/off-critical-path — free-scale holds) | open | — |

| EM-144 | P2 | W12 | frontend | user 2026-06-10 | Stale starvation banner: "[STARVATION] ⚠ Bram is starving — energy 22/100 (below 25)" stayed up after Bram recharged back above the threshold (seen T105) — the warning should derive from live agent energy (clear when energy ≥ threshold, or re-derive per world_state), not latch on the last starvation event | open | — |

| EM-145 | P1 | W12 | backend | user 2026-06-10 | God voice tools show no agent uptake: user posted billboard replies and god whispers multiple times and nothing indicated agents "heard" or "read" them (goal: get agents to name the town — still impossible). Wave-A E2E showed an API whisper acted on within 3 ticks, so suspect the UI→API path, whisper loss on hot-reload (`pending_whispers` is in-memory), or prompt injection too weak for live models. Fix end-to-end + make delivery LEGIBLE: feed event when a whisper/billboard reply is consumed into a prompt ("✦ {name} hears the whisper"), and verify with prompt capture | open | — |

| EM-146 | P1 | W12 | frontend | user 2026-06-10 | Story-so-far summary still pushes the chat/feed out of view when it grows (EM-139 bounded the PROJECTS line, but the whole digest block is unbounded — long DRAMA/BILLBOARD content reproduces it): cap the summary's height and make it scrollable, plus a collapse toggle (persisted) so the feed always keeps its space — feed is the centerpiece, it wins layout tradeoffs | open | — |

_Next free ID: EM-147._

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
- **EM-109–128 (v3 Village→Civilization)** entered 2026-06-09 via `plan-intake` from
  `docs/research/deep-research-v3.md`. They open **W12–W14** (breadth slice → depth pass 1 →
  depth pass 2); six headline features (multi-city, parallel model-family worlds, city growth,
  deeper relationships, lightweight children, cozy-art overhaul) shipped **breadth-first**, each
  EM-### an independently demo-able PR. The report authored these as EM-105–124; all were
  **renumbered to EM-109–128** (EM-105–108 were taken by W11a/W11b in the interim) and internal
  deps remapped. Several report "pull-forward" deps had already shipped: **EM-086** (run browser/
  cross-run AWI), **EM-095** (camera nav), **EM-096** (layout), **EM-099** (pets), **EM-102**
  (label declutter) — so **EM-121** (camera) and **EM-124** (character swap) were **rescoped to
  their multi-city / mesh-swap deltas only**, and **EM-125** kept as a **consumer** of (not a
  duplicate of) the shipped reflection work (EM-080). **All hard prerequisites are already done**
  (EM-101 fork/resume, EM-092 persona library, EM-098 procgen+housing, EM-080 reflection,
  governance texture EM-079/087/100/103) — v3 is unblocked at the foundation. **Sequencing (user
  2026-06-09):** depth-first on the *first* city — grow and change it, make it "be more things"
  (EM-115 city-growth, EM-122 buildings-per-kind, EM-123 neighborhoods/zoning, all riding shipped
  EM-098) — *before* founding a second settlement (EM-109/110 multi-city), inverting the report's
  "multi-city is the keystone" recommendation. Multi-city + multi-world were promoted out of
  `docs/FUTURE.md` per its convention.

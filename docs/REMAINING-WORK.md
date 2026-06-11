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
> **v4 (EW-grade city + 25-agent scaling) filed 2026-06-10** via `plan-intake` from
> `docs/research/deep-research-v4.md` + its review feedback — **EM-152–169**, opening
> **W15–W17** (Wave D: D1 city vocabulary+generator · D2 population scaling · D3 life).
> Direction lock: the art target is Emergence World's dense zoned city, not Stardew-cozy;
> the Wave C medieval core persists as a historic district (EM-156).

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
| EM-123 | P2 | W14 | backend | research-v3 | City-growth depth: `neighborhoods` table + `places.neighborhood_id`/`zone_kind`(residential/market/civic/industrial/farm)/`tier`; zoned districts grow as megaprojects complete. Deps EM-115 ✅, EM-147 ✅; feeds the W15 CityGenerator (EM-153) — growth output becomes generator input | open | — |
| EM-124 | P1 | W14 | frontend | research-v3 + wave-c spec C5 | Art phase 4 (rescoped → Wave C C5): 3D character mesh swap — rigged CC0 GLB villagers + critters (KayKit Adventurers / Quaternius Universal Animated) via drei `useAnimations` (idle + walk wired to the existing `animMap` lerp), per-agent identity tint (cloned materials — `<Clone>` shares them by default), DOM overlays (name label, model chip, chat bubble) intact. Pets-in-sidebar (EM-099 ✅) already shipped W11a. Deps EM-148 | done | wave-C 2026-06-10 |
| EM-125 | P2 | W14 | backend | research-v3 | Reflection-driven society: importance-threshold reflection (**consumes** EM-080 ✅) occasionally upgrades a relationship type (cheap, throttled LLM touch) and triggers reflection-driven migration. Deps EM-080 ✅, EM-113 | open | — |
| EM-126 | P3 | W14 | backend | research-v3 | Generational depth: life stages/aging (child→adult→elder cadence + tool unlocks), inheritance of credits/relationships/grudges on death, lineage tree in the inspector. Deps EM-114 | open | — |
| EM-127 | P3 | W17 | frontend | research-v3 | Art phase 5 (re-waved W14→W17 at v4 intake — rides Wave D3 "life"): day/night + seasons + particles (chimney smoke, fireflies) + sparing `<Bloom>`/`<Vignette>` + filmic tone mapping (`antialias:false`, post handles AA). Deps EM-111 ✅ | open | — |
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

| EM-144 | P2 | W12 | frontend | user 2026-06-10 | Stale starvation banner: "[STARVATION] ⚠ Bram is starving — energy 22/100 (below 25)" stayed up after Bram recharged back above the threshold (seen T105) — the warning should derive from live agent energy (clear when energy ≥ threshold, or re-derive per world_state), not latch on the last starvation event | done | fix-batch 2026-06-10 |

| EM-145 | P1 | W12 | backend | user 2026-06-10 | God voice tools show no agent uptake: user posted billboard replies and god whispers multiple times and nothing indicated agents "heard" or "read" them (goal: get agents to name the town — still impossible). Wave-A E2E showed an API whisper acted on within 3 ticks, so suspect the UI→API path, whisper loss on hot-reload (`pending_whispers` is in-memory), or prompt injection too weak for live models. Fix end-to-end + make delivery LEGIBLE: feed event when a whisper/billboard reply is consumed into a prompt ("✦ {name} hears the whisper"), and verify with prompt capture | done | fix-batch 2026-06-10 |

| EM-146 | P1 | W12 | frontend | user 2026-06-10 | Story-so-far summary still pushes the chat/feed out of view when it grows (EM-139 bounded the PROJECTS line, but the whole digest block is unbounded — long DRAMA/BILLBOARD content reproduces it): cap the summary's height and make it scrollable, plus a collapse toggle (persisted) so the feed always keeps its space — feed is the centerpiece, it wins layout tradeoffs | done | fix-batch 2026-06-10 |

| EM-147 | P1 | W14 | backend | wave-c spec C1 | District town config: ~15-place districted `world.yaml` (core/market/residential/civic/farm) + `loader.py` default mirror; additive optional `district` field on `PlaceConfig` + place serialization (default null); e2e test that a ~15-place town runs (movement, building pipeline, well + notice-board resolve). Kinds stay the existing five; lanes derived, not authored. Precursor to EM-123 | done | wave-C 2026-06-10 |

| EM-148 | P1 | W14 | frontend | wave-c spec C2 | Asset layer (foundational): `web/src/components/world3d/assets/models.ts` registry (VariantKey/PlaceKind → {glbUrl, scale, yOffset, rotation, clips}), `<Model>` wrapper over drei useGLTF+`<Clone>`, `<Instances>`/`<Merged>` for repeats, `<Suspense>` + hero `useGLTF.preload()`, **fallback invariant** (procedural mesh renders while a GLB is in flight — never a hole), meshopt/draco decoders vendored into `web/public/` (no new runtime deps), first CC0 GLB kits + `ASSET_LICENSES.md` entries; **GLB materials converted to the toon ramp** (`toonGradientMap()`, maps preserved) so kits match the Wave B art direction | done | wave-C 2026-06-10 |

| EM-149 | P1 | W14 | frontend | wave-c spec C3 | Town layout + lanes: pure tested `townLayout.ts` (main-lane spine + nearest-neighbor connector graph, per-district ground-zone tints, clearance-aware prop lots via seeded `hashUnit`); `Ground.tsx` lane network **replaces the hub-and-spoke spokes** (kills the pinwheel); `SIZE`/coordinate retune so districts breathe + camera `PAN_BOUND`/bounds update; look-dev call at build time: Kenney road-tile GLBs vs widened warm-toon lane strips. Deps EM-147 | done | wave-C 2026-06-10 |

| EM-150 | P1 | W14 | frontend | wave-c spec C4 | Buildings GLB swap: `Structure.tsx`/`Building.tsx` render registry GLBs keyed by `operationalVariant()` (EM-122 mapping + tests carry over verbatim); keep status renderers, `healthTint` soot as GLB material tint, EM-102 label gating, idle bob, click-to-focus; procedural meshes survive as the in-flight loading fallback. The GLB remainder explicitly deferred at `contracts/wave-b.md` (EM-122 shipped procedural). Deps EM-148 | done | wave-C 2026-06-10 |

| EM-151 | P1 | W12 | frontend | user 2026-06-10 | Inspector archive view breaks on the longest runs: loading run #189 (tick 4097, day 204, **40,842 events**) renders a solid-white left panel and an empty right panel — nothing interactive except BACK TO LIVE (screenshot evidence; header/status bar still render, so a child component is dying or collapsing under the 40k-event projection). EM-141 fixed the d3 "node not found" crash on this same run — this is a NEW failure past that point. Needs: an error boundary around the inspector panels (a dead panel must say so, not blank the annex) + windowing/decimation of the archive projection (selectors currently fold the full history) | open | — |

| EM-152 | P0 | W15 | frontend | research-v4 §2 | City asset vocabulary: vendor Kenney City Kit family (Roads/Commercial/Suburban/Industrial) + Car Kit + Furniture Kit + KayKit City Builder Bits (~360+ pieces, ~13 MB, CC0, headless URLs verified at research time); gltfjsx `--instanceall`/`--transform` atlas+dedupe pipeline; toon-ramp conversion per atlas; every file recorded in `ASSET_LICENSES.md` | done | wave-D1 2026-06-10 |
| EM-153 | P0 | W15 | frontend | research-v4 §3 | Deterministic CityGenerator: pure seeded module (snapshot+seed → grid roads w/ lane markings → blocks → 4–8 lots → zoned kit-assembly → prop/vehicle scatter), zero `Math.random()`, vitest-tested like `townLayout.ts`; sim Buildings get hero placement on their lot. Consumes EM-147 districts; EM-123 growth becomes its input later | done | wave-D1 2026-06-10 |
| EM-154 | P0 | W15 | frontend | research-v4 §4 | Instanced city render path: raw `InstancedMesh` per kit-piece type for static sets, per-block chunked culling, tight shadow frustum + bias, drei `<Detailed>` LOD; budget ~10–20 draw calls for the whole city, 60fps on integrated GPU. Deps EM-152, EM-153 | done | wave-D1 2026-06-10 |
| EM-155 | P0 | W15 | persistence | v4-review §5 | City snapshot contract (replay/fork fidelity): city seed + full generator input captured in event-log snapshots; "city is deterministic from snapshot+seed" added as an EM-101/EM-075 invariant with a vitest test — `generate(snapshot, seed)` byte-identical across live/replay/fork. **Must-fix-before-W16** | done | wave-D1 2026-06-10 |
| EM-156 | P1 | W15 | frontend | v4-review §3 | Old-town migration strategy (resolves v4's open question → old town): Wave C medieval core persists as a seeded "historic district"; Kenney city lands as NEW districts beside known-good geometry — smaller per-PR blast radius, palette-clash contained at district boundaries, "town grows into a city" story | done | wave-D1 2026-06-10 |
| EM-157 | P2 | W15 | frontend | v4-review §6 | Scope the raw-instancing swap to static deterministic sets only; interactive entities (clickable sim Buildings → inspector) keep per-instance-ergonomic rendering — no blanket replacement of drei instancing | done | wave-D1 2026-06-10 |
| EM-158 | P0 | W16 | backend | research-v4 §5.1 | Turn-cadence tiers: `cadence_tier` on AgentState (protagonist every round / supporting ⅓ / background 1⁄10) + tier-aware `next_agent()`; pattern generalized from the shipped animal cadence (`act_every_n_ticks` + reflex fallback) | done | wave-D2 2026-06-11 |
| EM-159 | P0 | W16 | backend | research-v4 §5.2 | Salience-gated reflex turns: LLM called only when something changed near the agent (`_importance` accumulator, co-location delta, energy threshold crossing, active whisper/proclamation); else deterministic needs routine, zero calls. Never for protagonists. **Deps EM-160 — must not ship without the spontaneity floor** | done | wave-D2 2026-06-11 |
| EM-160 | P0 | W16 | backend | v4-review §1 | Spontaneity floor (anti-dead-town): low per-tick wildcard LLM-turn chance for non-salient background agents + a salience-floor timer (reflex-only for N ticks ⇒ one forced "reassess" LLM turn). Gates the free-scale win against a sim-quality regression — the failure shows worst on camera | done | wave-D2 2026-06-11 |
| EM-161 | P1 | W16 | backend | research-v4 §5.3 | Prompt diet: relationships capped to top-8 by abs(trust), `open_projects` + `move_to` place list scoped to district, decision-trace instruction block dropped for background tiers (output ~400→~150 tok), `memory_window` 12→8 for background. Correctness requirement for the 8K-context Cerebras lane at 25 agents | done | wave-D2 2026-06-11 |
| EM-162 | P1 | W16 | providers | research-v4 §5.4 | Cache-key normalization: bucket energy to 10s + floor tick for background-tier prompts so the router's sha1 decision cache serves quiet rounds (35% → target 50–60% hit); keep `forget()` semantics intact | done | wave-D2 2026-06-11 |
| EM-163 | P1 | W16 | backend | v4-review §2 | Tier-gate world-mutating tools: `propose_project`/`build_step`/governance proposals restricted to protagonist+supporting tiers; background keeps talk/move/economy reflex tools. Phantom-commitment containment (pairs EM-079 scope note) | done | wave-D2 2026-06-11 |
| EM-164 | P1 | W16 | qe | v4-review §4 | Verify the two load-bearing budget assumptions on a real run before trusting the v4 scaling table: (a) realized cache-hit rate after EM-162 (don't budget at 60% unproven), (b) Ollama sustained turns/h measured WHILE the R3F city renders on the same machine (CPU/GPU contention). W16 go/no-go; measurement can start during W15 | done | wave-D2 2026-06-11 |
| EM-165 | P1 | W16 | config | research-v4 §5 | 25-agent world: persona-library casting for 25 agents, protagonist-slot selection (user-pinned + salience-rotating), tier assignment in `world.yaml`; population cap honored. Deps EM-158 | done | wave-D2 2026-06-11 |
| EM-166 | P2 | W16 | backend | v4-review obs. | Salience + tier observability: per-agent salience/`cadence_tier` surfaced in event log + inspector ("who's been reflex-only too long, which tier phantom-commits") so EM-160/163 are tunable from data, not vibes | done | wave-D2 2026-06-11 |
| EM-167 | P1 | W17 | providers | research-v4 §5.5 | Ollama overflow lane: enable the scaffolded profile (profiles.yaml), route background/supporting tiers there as off-critical-path background tasks (animal-task pattern) — ~40% of background calls off FreeLLMAPI. Deps EM-158, EM-164 | open | — |
| EM-168 | P1 | W17 | providers | research-v4 §5.6 | Cap-pressure governor: wire the three existing observers (UsageAlertTracker 70% alerts, default-off `usage_caps` throttle, EM-135 lane health) into the tier scheduler — a lane's alert demotes that lane's agents one cadence tier instead of merely slowing ticks. Enforces the v3 population-cap rule. Deps EM-158 | open | — |
| EM-169 | P2 | W17 | frontend | research-v4 §7 | Ambient vehicles: Car Kit traffic on the generated road network (deterministic paths, instanced), parked cars from the prop scatter. Deps EM-152, EM-153 | open | — |

| EM-170 | P1 | W16 | backend | user 2026-06-11 | Turn-latency guard: a single slow LLM call freezes the whole world (sequential loop) — run 248 measured 14-32s calls back-to-back ("no one talking for 30 sec"; speed slider invisible because sleep is the only thing it controls). Cap per-turn LLM wall-time (~10-12s budget, then idle fallback + lane-health demerit via EM-135 tracking) so no call ever stalls the world; pairs with EM-158 tiers + EM-168 governor. Live mitigation applied: slow seats reassigned to gemini-flash/groq-llama (turns 0.5-0.7s after) | done | wave-D2 2026-06-11 |

| EM-171 | P2 | W17 | providers | qe wave-D2 | EM-162 cache payoff is 0% in integration (v4 assumed 50-60%): the day-floored tick still misses (a 25-turn round spans >1 in-world day at 20 turns/day), memory lines embed raw ticks (an agent's own last turn makes every prompt unique), reflex move-home churns co-location rosters. Extend the normalization: coarsen/drop the day line, de-tick background memory lines, scope menu target lists — then re-measure. Capacity math survives without it (8.3 calls/round measured) | open | — |
| EM-172 | P2 | W17 | backend | qe wave-D2 | Mid-round-death scheduler skip (pre-existing since 58a8e7e, surfaced by the 25-agent chaos run): a death mid-round silently skips one due agent's turn that round — cheap `_turn_index` decrement fix in world.py + regression test. Also note: recharge-to-full energy-band flapping inflates background salience (one-line band hysteresis) | open | — |

| EM-173 | P1 | W16 | backend | user 2026-06-11 | Survival reflex on llm_timeout: run 321's degraded proxy night (38% of calls at the 12s budget) turned the EM-170 guard into a death sentence — agents idled turn after turn and Ada starved. Wall-clock timeouts now resolve the EM-159 reflex routine (any tier, marked llm_timeout_reflex, timed_out trace kept); gated reflexes fall through to idle; provider_error stays an honest idle | done | hotfix 2026-06-11 |
| EM-174 | P1 | W15 | frontend | user 2026-06-11 | Every building has a purpose: generated zone-building fill removed entirely (user rule — buildings are landmarks or agent-built W7 entities, nothing else); all 72 lots platted from day 0 and claimable by real buildings (landmark block first, nearest-block overflow, slot-ring at full city); D1.6 growth budget retired as superseded | done | hotfix 2026-06-11 |
| EM-175 | P1 | W16 | backend | user 2026-06-11 | agent_count was dead config (parsed, never consumed — world booted exactly the agents: list despite the yaml comment's promise). Now pads from the persona library at supporting tier; Citizen-N fill when the library runs short; never truncates | done | hotfix 2026-06-11 |

| EM-176 | P2 | W17 | frontend | user 2026-06-11 | Bring vehicles back when they're playable: parked-car emission disabled at the generator (`CARS_ENABLED=false`, cityLayout) — static cars read as a distraction before they have a purpose. Keys/registry/GLBs/licenses all kept; EM-169's ambient traffic on the road graph is the re-entry point (flip the flag + moving cars together) | open | — |

| EM-177 | P1 | W17 | providers | user 2026-06-11 | Lane failover with recovery probes: the router KNOWS lane health (EM-135/170 windows) but nothing acts on it — degraded-proxy days (every lane except mistral-small rerouted to a 12s-blowing reasoning model; 4th manual rescue in two sessions) starve agents glued to sick lanes. A lane with ≥3 timeouts in its 6-window detours that agent's calls to the healthiest lane per-call (assignment/identity unchanged), every 4th would-be-detour probes the home lane so recovery is automatic, `lane_detour` feed events on streak edges only, `GET /api/lanes` exposes health. `world.lane_failover {enabled, sick_threshold, probe_every}`; off ⇒ pre-D3 behavior. Contract: `contracts/wave-d3.md` B1 | open | — |

| EM-178 | P2 | W15 | frontend | user 2026-06-11 | Building-label overflow: the Wave-D `<Billboard>` label (Structure.tsx) sized its dark backdrop to the TITLE only, so a long status line — e.g. a "Community Commons Fund" whose `function` reads "A pooled resource managed by community vote" — spilled past the plate and clipped mid-word. Plate now fits the wider of title/subtitle; subtitle clamped to one line (`SUB_MAX`, `whiteSpace="nowrap"`). EM-102 declutter covered the prior Html labels, not this render path | done | fix-batch 2026-06-11 |

| EM-179 | P2 | W15 | frontend | user 2026-06-11 | "Jittery grass" shimmer at full zoom-out: coplanar ground-zone tints (Ground.tsx) now pass `depthWrite:false` + `polygonOffset` through `toonMaterial` (no z-fight at grazing angles), the directional light gains `shadow-normalBias=0.04` (kills shadow-acne crawl on the flat terrain), and fog tightened 75/230→80/215 so the outer terrain ring dissolves into haze before it can sparkle. Best confirmed visually | done | fix-batch 2026-06-11 |

| EM-180 | P2 | W17 | frontend | user 2026-06-11 | Funds get a DISTINCT non-building treatment: economic/governance pools (e.g. "Community Commons Fund", emergent `kind=commons`) currently instantiate as a full physical W7 building shell (neutral fallback + a claimed lot) — render them instead as a marker/ledger/panel affordance (a treasury is an account, not a structure). Frontend display side; the backend that authors kind/function is out-of-repo. Pairs EM-130 fallback + EM-142 function caps | open | — |

| EM-181 | P2 | W15 | frontend | user 2026-06-11 | Spread sooner: `assignBuildingLots` (cityLayout.ts) packed each place's overflow into the single NEAREST block's lots before spilling, so growth piled up center-out. Overflow now ROUND-ROBINS across blocks (lot 0 of every block nearest-first, then lot 1, …) so a place that outgrows its landmark block fans one lot per surrounding block — stays deterministic (EM-155 byte-identical invariant holds, 497 tests green). The dramatic per-district spread the user wants lands with EM-182 (agent choice). Pairs EM-131 slot placement + EM-174 placement tiers | done | fix-batch 2026-06-11 |

| EM-182 | P2 | W14 | backend+frontend | user 2026-06-11 | Agent-chosen placement freedom: agents should pick WHERE/which zone to build (a house in the industrial district, etc.) rather than the renderer auto-assigning the nearest lot — `propose_project` gains a target place/zone arg (backend), CityGenerator/`assignBuildingLots` honor it (frontend), agents grow the city as they see fit. Extends EM-123 zoned districts (deterministic) with agency; pairs EM-181 | open | — |

| EM-183 | P3 | W17 | backend | user 2026-06-11 | Vote to move/expand the town center: a governance proposal type that re-anchors the civic center / designates a new plaza when ratified (~70% threshold), and the city re-centers on the agents' chosen heart — the "they grow the city as they see fit" end-goal the user expected in the plan (not previously tracked). Builds on shipped governance texture (EM-079/087/100/103) + the city-scoped treaty pattern (EM-117) | open | — |

| EM-184 | P1 | W18 | backend | user 2026-06-11 | World-scale god miracles — answer the prayers: agents petition the watchers ("send rain for the garden", "Petition: fewer famines. Signed, everyone") and god has NO world-scale power to grant them (bless_energy/grant_credits/whisper/spawn are all single-target). Extend `world.god_intervene` with world kinds: `send_rain` (forage/garden yield buff for N in-world days), `bountiful_harvest` (famine relief: temporary energy-decay reduction or food abundance), `calm_spirits` (mood/trust nudge). Each emits a world event ALL agents perceive ("rain falls on the garden") so the ask→answer→belief loop closes inside the sim. Free-scale: pure state modifiers, zero LLM calls. API: new kinds on `POST /api/god/intervene` (agent_id optional for world kinds) | open | — |

| EM-185 | P1 | W18 | frontend | user 2026-06-11 | Grant-a-petition UX: petitions are feed/billboard text with no affordance — add a GRANT button on petition/prayer-shaped events (billboard posts + `pray`/petition actions) opening a small god-console picker of EM-184 miracles, pre-filled from the ask; granting fires the miracle + an automatic god billboard reply quoting the petition, so the watchers visibly answer. Deps EM-184 | open | — |

_Next free ID: EM-186._

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
- **EM-152–169 (v4 EW-grade city + scaling)** entered 2026-06-10 via `plan-intake` from
  `docs/research/deep-research-v4.md` **plus its review feedback** (seven guardrail items the
  review authored as EM-125–131 — all **renumbered**: those IDs were taken by v3/Wave-A
  entries). They open **W15–W17** (Wave D: D1 city vocabulary+generator → D2 population
  scaling → D3 life; the doc's D-labels map to these waves). Direction lock: the art target
  is **Emergence World's dense zoned city**, not Stardew-cozy. Key gates: **EM-155** (city
  snapshot contract) and **EM-164** (budget-assumption verification) are must-pass before
  W16; **EM-159 must not ship without EM-160** (spontaneity floor) or background agents
  flatten into NPCs-on-rails. EM-156 resolves the full-pivot question → old-town historic
  district. Existing entries re-pointed instead of duplicated: **EM-127** re-waved W14→W17
  (day/night rides D3), **EM-123** feeds the EM-153 generator.

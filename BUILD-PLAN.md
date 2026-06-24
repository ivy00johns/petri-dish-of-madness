# PetriDishOfMadness — Build Plan

Strategic roadmap. **Where are we going, and what have we finished?**
Tactical detail (individual items) lives in `docs/REMAINING-WORK.md`.
The approved design is frozen at `docs/superpowers/specs/2026-05-26-petridish-of-madness-design.md`.

Build model: **contract-first, parallel multi-agent** (orchestrator). Contracts authored
in W0 before any implementation agent is spawned. A QE gate closes every wave.

---

## Wave 0 — Scaffold & Contracts

Lay the skeleton and author every machine-readable contract before implementation begins.

**Scope:** repo structure (`backend/{engine,providers,agents,persistence,api}`, `web/`,
`config/`, `docker/`); config templates (`profiles.yaml`, `world.yaml`); contracts for the
action protocol JSON, WebSocket event schema, REST API, SQLite schema, and provider
`chat()` interface.

**Exit criteria:**
- All five contracts pass the contract-author quality checklist.
- Skeleton installs/builds (Python + web) with no implementation yet.
- `config/*.yaml` templates documented and load-validated.

## Wave 1 — Engine, Providers, Persistence (backend core)

The sim works headless and deterministically.

**Scope:** world model + state; tick loop + round-robin scheduler; needs decay + death;
economy (work/forage/recharge/give/steal); talk + relationships; lightweight governance
(propose/vote/typed effects → world-param mutation); agent context assembly + cheap memory;
action parse/validate/retry/idle-fallback; provider router + adapters (OpenAI-compatible,
Anthropic, Gemini); MockProvider; SQLite repository.

**Exit criteria:**
- Engine runs K ticks against MockProvider, fully deterministic, zero LLM calls.
- Invariants hold (credits conserved except via defined sources/sinks; dead agents act not; active rules enforced).
- Adapter contract tests pass against a stub OpenAI-compatible endpoint.

## Wave 2 — API & Frontend (the spectacle)

You can watch the madness in a browser.

**Scope:** FastAPI control endpoints (start/pause/step/speed/reassign-model/spawn/kill/inject-event)
+ config endpoints; WebSocket broadcaster (state + events); React/Vite/Tailwind frontend —
2D canvas map, live event feed (color-coded by model), per-agent panels, control panel with
**live model reassignment**, model legend; WS client + state store.

**Exit criteria:**
- UI renders live from a MockProvider run: map moves, feed streams, panels update.
- Reassigning an agent's model from the UI is visibly reflected on the next turn.
- Console clean; primary routes walk cleanly.

## Wave 3 — Integration, QE & Deploy

Ship-ready, tested, one-command up.

**Scope:** end-to-end wiring; QE suite (engine units, integration invariants, adapter
contracts, frontend smoke) + `qa-report.json`; `render-sanity` + `ux-review` gates;
docker-compose one-command up (backend, frontend, optional Ollama / FreeLLMAPI); root README
+ `dev` script; cloud-deploy notes (endpoint swap).

**Exit criteria (= Definition of Done, spec §12):**
- `docker-compose up` brings up the lab; map + feed render and update live.
- A 4–6 agent **mixed-model** world runs a full arc end-to-end (conflict, alliances, ≥1 death, ≥1 passed rule).
- Per-agent model reassignable live from the UI.
- Engine test suite passes deterministically (MockProvider).
- Runs free against FreeLLMAPI and locally against Ollama.
- README documents one-command local run + path to cloud deploy.
- `render-sanity` returns PASS.

## Wave 4 — Cozy 3D village + live multi-model run (post-v1)

Make the world a place you *watch*, and prove the marquee feature live.

**Scope:** a cozy 3D village center view (React Three Fiber + drei) in the
Stardew × Animal-Crossing register — procedural buildings per place-kind, walking
villagers tinted by model, floating chat bubbles, orbit spectator cam, 2D/3D toggle;
backend surfacing of the model that *actually* answered each turn (`X-Routed-Via` →
`payload.routed_via`) displayed per villager; 3-agent / 3-model config (co-located seed
for immediate conversation); the live FreeLLMAPI run (EM-048).

**Exit criteria:**
- `tsc -b` + `vite build` pass; backend suite green (incl. new routed_via tests).
- A 3-agent, 3-model world runs live on FreeLLMAPI for ≥5 min with agents chatting.
- The UI shows the actually-routed model per agent (not just the requested profile).
- The 3D village renders from live data with a clean console.

---

## Wave 5–8 — v2 expansion (planned)

Filed 2026-06-08 via `plan-intake` from `docs/research/deep-research-v2.md`. Tactical detail
+ IDs live in `docs/REMAINING-WORK.md` (EM-053–EM-068). Phases run in order; each wave reads
the event log W5 establishes.

**Wave 5 — Foundations (the gate).** The 3D village stays the **primary experience** (home
route `/`). Add a separate 2D `/inspector` **analysis annex** on its own route so heavy
data-viz panels never share a render loop with Three.js — and so the WebGL canvas can unmount
entirely while you analyze (zero GPU). The 2D-ness is about using the right tool for charts/
graphs and freeing the GPU during analysis — it is **not** a demotion of the 3D world. Lock
the append-only event-log schema (OTel-style linked turn traces, WAL, periodic snapshots)
every later feature reads. Items: **EM-053** (`/inspector` annex + WebGL unmount), **EM-054**
(event-log schema), **EM-066** (structured decision-trace action output). _Build EM-053/054
first — getting the log right now prevents painful migrations later._

**Wave 6 — "See what happened": instrumentation & observability.** The #1 ask — make the
already-recorded data watchable. Items: **EM-055** replay viewer, **EM-056** decision-trace
inspector, **EM-057** governance/laws history (clock-tower failure), **EM-058** social graph,
**EM-059** 9-AWI + model-vs-model dashboard, **EM-067** per-provider RPD/TPD tracking.

**Wave 7 — Expanded world capabilities.** Items: **EM-060** tiered tool catalog (reflex vs
LLM-served), **EM-061** building/structure state model, **EM-062** collective-project pipeline
(propose→fund→build→succeed/fail), **EM-063** ad-hoc agent spawning, **EM-068** decision caching.
These enrich the **3D village itself** — buildings carry visible mutable state (a clock tower
rising as it's funded/built, scaffolding while under construction, scorched walls after arson),
so the world "feels more real as it grows" on the primary 3D view, not only in 2D panels.

**Wave 8 — The chaos layer.** Items: **EM-064** LLM-driven cat & dog chaos entities (which
roam the **3D village** as distinct tinted critters, not just log lines), **EM-065** Animal
Chaos Feed + tagging.

**Free-scale is a hard constraint throughout:** RPD/TPD caps bind on free tiers, so favor slow
ticks, reflex (no-LLM) tool resolution, aggressive caching, and per-provider usage tracking
before adding entities.

---

## Wave 9–11 — v2.1: audit remediation + texture (planned)

Filed 2026-06-09 via `plan-intake` from `docs/audit-2026-06-09.md` (full audit: backend +
frontend code audits, live UX review against a real FreeLLMAPI run, doc-drift sweep; UX
companion: `docs/ux-review-2026-06-09.md`). Tactical detail + IDs live in
`docs/REMAINING-WORK.md` (EM-069–EM-083, plus re-scoped EM-043).

**Wave 9 — "Make v2 true" (the gate).** The audit's headline: deep replay is dead code (the
inspector never reads the persisted event log — `inspectorApi` has zero consumers) and the
live run starved to total extinction while looking cheerful (no survival pressure in prompts,
no extinction UX, and all three "different model" profiles silently routed to one model).
Items: **EM-069** (wire deep replay), **EM-070** (survival pressure), **EM-071** (extinction/
run-end UX), **EM-072** (routing-degraded banner), **EM-073** (backend P1 batch: animal
turn_id contamination, reset race, ban_arson unreachable, build_step validator, duplicate
llm_call rows), **EM-074** (frontend P1 batch: play/pause state, WS reconnect leak, force-graph
pause, AWI gov column, seq collision).

**Exit criteria:**
- Scrubbing to any tick of a finished run renders correct world state from snapshot + delta
  (works after a fresh page load with zero rolling history).
- A live run where agents hold credits no longer ends in silent total starvation: needs are
  in the prompt, starvation warns in the feed, and 0-alive pauses or banners the run.
- A run where all profiles route to one model shows a routing-degraded warning.
- Backend suite green with new regression tests for each EM-073 fix; console clean.

**Wave 10 — Trust & hygiene.** Make the analytics and replay trustworthy and sync the paper
trail. Items: **EM-075** (replay fidelity: snapshot round-state, time-projected buildings,
map legibility, animals on 2D map), **EM-076** (analytics correctness), **EM-077** (platform
hardening), **EM-078** (docs/contracts sync incl. the README regression), **EM-043** (re-scoped
frontend unit tests targeting selectors/scrubber/dashboard).

**Wave 11 — New texture (free-scale).** The best unfiled ideas from `deep-research-v2.md`
§Recommendations and `docs/FUTURE.md`, gated behind a healthy core. Items: **EM-079**
(active-commitments injection), **EM-080** (importance-threshold reflection/diary), **EM-081**
(capped reactive overhearing — promoted from FUTURE.md), **EM-082** (mobile/min-width decision
+ a11y pass), **EM-083** (real blackout effect + RPD/TPD benchmark alerts).

---

## Wave 12–14 — v3: Village → Civilization (planned)

Filed 2026-06-09 via `plan-intake` from `docs/research/deep-research-v3.md`. Tactical detail
+ IDs live in `docs/REMAINING-WORK.md` (EM-109–128). Six headline features — multi-city,
parallel model-family worlds, city growth, deeper relationships, lightweight children, and a
cozy-art overhaul — shipped **breadth-first**, each EM-### an independently demo-able PR.

**Prerequisites already satisfied.** Unlike v2/v2.1, v3 opens with a clean foundation: every
hard dep shipped in W11a/W11b — fork/resume (EM-101), persona library (EM-092), procgen +
housing (EM-098), reflection (EM-080), run browser + cross-run AWI (EM-086), camera nav
(EM-095), and the governance-texture batch (EM-079/087/100/103). No prerequisite wave to clear.

**Build order (user 2026-06-09):** depth-first on the **first city** — grow it, change it,
make it *be more things* (EM-115 city-growth slice, EM-122 buildings-per-place-kind, EM-123
neighborhoods/zoning, riding shipped EM-098 procgen/housing) — **before founding a second
settlement** (EM-109/110 multi-city). This deliberately inverts the report's "multi-city is the
keystone" recommendation in favor of deepening what's already on screen.

**Wave 12 — "There is more than one place" (breadth slice).** Items: **EM-109** (multi-city
data model + 2nd settlement on the 2D map), **EM-110** (reflex travel + migration), **EM-111**
(art win #1: HDRI + toon + soft shadows), **EM-112** (parallel-worlds runner, `model_family`,
sequential tournament), **EM-113** (relationship type/strength schema + colored edges),
**EM-114** (lightweight children: partner→reflex spawn, population cap), **EM-115** (city-growth
slice: project→building).

**Wave 13 — depth pass 1.** Items: **EM-116** (inter-city trade caravans), **EM-117**
(diplomacy via governance), **EM-118** (instanced foliage, art phase 2), **EM-119**
(Model-Family Arena comparison UI), **EM-120** (factions + feuds + reputation), **EM-121**
(multi-city camera: zoom-to-city / follow-agent).

**Wave 14 — depth pass 2.** Items: **EM-122** (buildings-per-place-kind, art phase 3),
**EM-123** (neighborhoods + zoning + megaprojects), **EM-124** (character mesh swap, art phase
4), **EM-125** (reflection → relationship upgrades + migration), **EM-126** (generational depth:
aging + inheritance + lineage tree), **EM-127** (day/night + seasons + particles, art phase 5),
**EM-128** (population/culture AWI metrics per model family).

**Wave C — "a town, not a diorama" (filed 2026-06-10, P1).** Design spec:
`docs/superpowers/specs/2026-06-10-wave-c-real-city-design.md`. The city-track build that
follows Wave B's lighting/instancing foundation: **EM-147** (district town config — ~15
places + additive `district` field, precursor to EM-123), **EM-148** (GLB asset layer:
registry + instanced loader + toon-converted CC0 kits), **EM-149** (townLayout lane network —
kills the hub-and-spoke pinwheel), **EM-150** (buildings GLB swap via `operationalVariant`),
plus **EM-124 bumped to P1** as Wave C's character swap (C5). Starts after Wave B
(`build/wave-b-city-comes-alive`) merges; handcraft the hero town first, generator later.

**Wave D — "the EW-grade city" (filed 2026-06-10, W15–W17).** Research:
`docs/research/deep-research-v4.md`. Direction lock: the art target is Emergence World's
dense zoned city — done better — not Stardew-cozy. **W15 / D1** (frontend-only): **EM-152**
(Kenney city-kit vocabulary, ~360 pieces CC0), **EM-153** (deterministic CityGenerator:
snapshot+seed → roads/blocks/lots/zoned kit-assembly), **EM-154** (raw-instanced render
path, ~10–20 draw calls), **EM-155** (city snapshot contract — replay/fork fidelity,
must-pass before W16), **EM-156** (old-town historic district — Wave C core persists),
**EM-157** (instancing scoped to static sets). **W16 / D2** (backend scaling to 25 agents):
**EM-158** cadence tiers, **EM-159+160** salience gating WITH the spontaneity floor
(inseparable), **EM-161** prompt diet, **EM-162** cache-key normalization, **EM-163**
tier-gated mutating tools, **EM-164** budget-assumption verification (go/no-go), **EM-165**
25-agent casting, **EM-166** observability. **W17 / D3**: **EM-167** Ollama overflow,
**EM-168** cap-pressure governor, **EM-169** ambient vehicles, plus existing **EM-127**
(day/night, re-waved) and **EM-123** growth feeding the generator.

**Free-scale is the binding constraint (sharper than ever here):** more cities × agents ×
children = more calls, and billing is subscription-only with no overage. Mitigations are
designed in — reflex-first travel/trade/children/caravans, per-city context scoping, a hard
population cap, cheaper/slower models for secondary entities, and **sequential** (never
concurrent) parallel-world runs gated by per-provider RPD/TPD tracking.

---

## Closure log

What shipped and when. Append on each wave/milestone close.

| Date | Wave / Item | Result |
|------|-------------|--------|
| 2026-05-26 | Design | Spec approved & committed (`8048235`); living plan set up |
| 2026-05-26 | W0 Contracts | 6 contracts authored (`bca98f6`) |
| 2026-05-26 | W1+W2 Build | backend (`58a8e7e`), frontend (`d90c1bb`), infra (`18aa21b`) shipped in parallel |
| 2026-05-26 | Wave gate | Found + fixed TickLoop step/start lifecycle bug (`27f9027`) + regression tests |
| 2026-05-26 | W3 QE | 55 tests pass; OpenAI/FreeLLMAPI adapter stub-verified; qa-report gate PASS (`d68a1da`) |
| 2026-05-26 | W3 render-sanity | Found + fixed dual-event-source duplicate-key bug (`1f5964b`); re-verified PASS (0 console errors, ordered feed, live backend) |
| 2026-05-26 | v1 complete | All waves shipped. Open: EM-043 (FE unit tests, P1) + EM-048 (live 2-model run, awaiting user token) |
| 2026-06-08 | W4 build | Cozy 3D village (frontend, R4F+drei) + routed-via surfacing (backend) shipped in parallel; wave gate PASS (`tsc -b`+`vite build`, 55 tests) |
| 2026-06-08 | EM-048 ✅ | Live 3-agent / 3-model FreeLLMAPI run >11 min, 3/3 alive, real chat + passed rule; proxy reroutes surfaced via `X-Routed-Via`. The project goal is met. |
| 2026-06-08 | W6 instrumentation | EM-053–059 + EM-067 — replay, decision-trace, governance/laws history, social graph, AWI + model-vs-model dashboard; 97 tests + adversarial panel + render-sanity GREEN (`3879d1c`, `d4227cf`) |
| 2026-06-08 | W7 expanded world | EM-060–063 + EM-068 — buildings/structure state, collective-project pipeline, tiered tools, ad-hoc spawn, decision cache; gate GREEN (`78dadf9`) |
| 2026-06-09 | W8 chaos animals | EM-064/065 — LLM-driven cat & dog (free-scale: slow cadence, reflex + occasional LLM, reflex-only fallback) + Animal Chaos Feed / `is_chaotic` tagging; suite-integrated `test_w8.py` (6 checks) + full backend suite GREEN |
| 2026-06-09 | Audit intake | Full audit (`docs/audit-2026-06-09.md` + `docs/ux-review-2026-06-09.md`) → EM-069–083 filed via `plan-intake`, opening W9–W11; EM-043 re-scoped. W9 gate = deep-replay wiring (EM-069) + survival pressure (EM-070) |
| 2026-06-09 | W10 ✅ | EM-075–078 + EM-043 (63 frontend unit tests — open since v1) + in-wave user items EM-084/085/088/089/090 shipped on `build/w10-trust-hygiene`. QA proceed=true (188 backend + 63 frontend tests); live verification GREEN (reset button end-to-end with run preserved on disk, feed seeded on refresh, animal chips + 🧠 markers, 8-profile roster). New finding W10-QA-1 filed as EM-097. User session also filed EM-086/087/091–096 (W11) + multi-city to FUTURE.md (`BUILD_RESULTS_W10.md`) |
| 2026-06-09 | W9 ✅ | EM-069–074 shipped on `build/w9-make-v2-true` (contracts bumped: event-log v1.1.0, api 1.2.0, frontend-inspector v1.1.0). QA gate caught + fixed W9-QA-1 (replay fold key); 172 tests / 0 fail / 1 xfail (pins W10 EM-076). Live verification GREEN: fresh-load scrub correct between snapshots, starvation countdown → death, extinction auto-pause + summary, routing-degraded banner field-verified. All W9 exit criteria met (`BUILD_RESULTS_W9.md`) |
| 2026-06-09 | W11a ✅ | UI batch shipped on `build/w11a-ui-batch` (contracts: api 1.3.0, event-log v1.2.0, frontend-inspector v1.2.0). EM-086 run browser/archive/cross-run AWI, EM-093 frozen-snapshot scroll, EM-094 digest+narrator, EM-095 camera nav, EM-096 chat-first layout, EM-097, EM-099 critters roster + in-wave user items EM-102/104/105. QA proceed=true (206 backend + 106 frontend); live verification GREEN (0.00px scroll drift measured, 27-run browser with exactly 1 ACTIVE, archive mode + comparison, console 0 errors). W11b (sim texture) next (`BUILD_RESULTS_W11A.md`) |
| 2026-06-09 | W11b ✅ | Sim-texture batch shipped on `build/w11a-ui-batch` (contracts: api 1.4.0, event-log v1.3.0, frontend-inspector v1.3.0). EM-079/080/081 same-call cognition (commitments+👻 phantoms, reflections, overhearing — prompt-capture tests assert zero extra LLM calls), EM-087+103 law RENEWAL + commemorative-monument guard, EM-091 billboard + god replies, EM-092 personas, EM-098 procgen+housing, EM-100 readable rule names, EM-101 fork/resume (honest snapshot grain), EM-082/083 + in-wave EM-107 layout-stable banners. QA proceed=true (252 backend + 150 frontend); live verification GREEN (god post on the board, fork 26@78→run 101 ↩ chip, banner dismiss 0.0px shift). **W9–W11 complete** (`BUILD_RESULTS_W11B.md`) |
| 2026-06-09 | v3 intake | `docs/research/deep-research-v3.md` → **EM-109–128** filed via `plan-intake`, opening **W12–W14** (v3 Village→Civilization). Report's EM-105–124 renumbered to EM-109–128 (EM-105–108 taken by W11a/W11b in the interim); EM-121/124 rescoped to multi-city/mesh deltas (their deps shipped W11a); multi-city + multi-world promoted out of `FUTURE.md`. All hard prereqs already shipped — v3 is unblocked. Build order per user: deepen the first city before founding a second |
| 2026-06-10 | Wave C intake | `docs/superpowers/specs/2026-06-10-wave-c-real-city-design.md` → **EM-147–150** filed via `plan-intake` (all P1/W14: district town config, GLB asset layer, lane network, buildings GLB swap); **EM-124 bumped P2→P1** and rescoped as Wave C's character swap (C5, deps EM-148); **EM-123** gains dep EM-147. Spec preamble's stale art-doc EM refs (EM-119/121 → ledger EM-122/124) corrected at intake. Gate: Wave C starts after Wave B merges |
| 2026-06-11 | W16 / Wave D2 ✅ | Population scaling shipped on `build/wave-d1-ew-city` (4 lean batches): EM-170 12s turn-latency guard (live-proven: 32/60 degraded-proxy calls capped at 12.0s), EM-158/159/160 cadence tiers + salience reflex + spontaneity floor (zero-call proof), EM-166 tier/reflex UI, EM-161/162/163 prompt diet + cache normalization + resolution-time tier gates, EM-165 city25 roster variant, EM-164 measured verification (8.30 calls/round at 25 agents — v4 validated; cache assumption falsified → EM-171; EM-172 scheduler-skip filed). Backend 445 / web 501; QA proceed=true (`BUILD_RESULTS_WAVED2.md`) |
| 2026-06-10 | W15 / Wave D1.5 ✅ | Corrective on user verdict ("it's just decor — the core is the same"): medieval core KILLED, sim moved onto the grid. 15 places = landmarks on a 5×5-block lattice (ids/kinds stable — backend 377/377 with zero test edits), every non-park block fully developed by law, medieval kit deleted, compact EW-style framing. `contracts/wave-d1.5.md`, lean 2-agent build; web 468/468, 61fps, console clean; street-level shot = agents at the plaza fountain inside the dense city (`BUILD_RESULTS_WAVED1.md` §D1.5) |
| 2026-06-10 | W15 / Wave D1 ✅ | EM-152–157 shipped on `build/wave-d1-ew-city` (contract `contracts/wave-d1.md`, ultracode workflow swarm: 3-agent implement wave ∥, 1-agent render wave, QE + adversarial verify). The EW-grade city ring renders around the Wave C historic core: 23 CC0 Kenney/KayKit GLBs (~1.45 MB), deterministic seeded CityGenerator (roads/blocks/zoned lots/props/cars, ~1,177 instances), raw-instanced render path (29 InstancedMeshes), `city_seed` persisted through snapshot/fork/replay, wilderness clamped to the core. Gates: backend 377 / web 467 / build clean / 60fps live / console clean; QE proceed=true (one MAJOR adversarially REFUTED — React dev-mode error re-dispatch, production clean), 4 MINORs recorded (`BUILD_RESULTS_WAVED1.md`) |
| 2026-06-10 | v4 intake | `docs/research/deep-research-v4.md` + review feedback → **EM-152–169** filed via `plan-intake`, opening **W15–W17** (Wave D: EW-grade city + 25-agent scaling). Review's EM-125–131 renumbered (IDs taken); EM-127 re-waved W14→W17; EM-123 feeds the CityGenerator. Direction lock: EW dense zoned city, not Stardew; old-town historic district (EM-156). Hard gates: EM-155 + EM-164 before W16; EM-159 inseparable from EM-160 |
| 2026-06-11 | W18 opened | "Answered prayers" filed from live session: agents petition the watchers ("send rain for the garden", "Petition: fewer famines. Signed, everyone") and god has no world-scale power to grant them — **EM-184** world miracles (send_rain / bountiful_harvest / calm_spirits as world-state modifiers all agents perceive; zero LLM calls) + **EM-185** grant-a-petition UX (GRANT affordance on petition events → miracle + god billboard reply). Both P1/W18 |
| 2026-06-11 | Wave E ✅ | "The social city" shipped on `build/wave-e-social-world` (6 batches + B7, one agent each, per-batch adversarial verify + wave QE): **EM-113** typed relationships (friend/feud reflex transitions, partner consent, since_tick), **EM-114** children (vacancy-fill births under the 25-cap, persona-card casting, family ties), **EM-120** factions + derived reputation, **EM-125** reflection-driven bonds (zero llm_call delta proven), **EM-184** world miracles + **EM-185** grant-a-petition UX (live-verified: 🌧 cast on run 506 tick 150), **EM-188** street/city name labels (user mid-wave add). QE proceed=true; its MAJOR (god casts unwitnessed by agents) fixed same-wave (`d13a63c`). Backend 705 / web 579; QE follow-ups EM-189–193 filed (`BUILD_RESULTS_WAVEE.md`) |
| 2026-06-12 | Wave F ✅ | Inspector at long-session scale shipped on `build/wave-f-inspector-scale` (stacked on wave E / PR #12): **EM-151** per-panel error boundaries + **EM-194** tail-first boot (stats + desc keyset tail API, newest chunk renders immediately, background backfill with real progress), incremental scrub projections golden-equal to the full folds, fixed-row virtualization (critter dialogue kept inline at 2 lines), 50k-cap truncation honesty. Live-verified: run #189 (40,842 events — the white-screen run) renders archive content in 16ms with 0 crashed panels, console clean. Backend 717 / web 625. Side commits: VITE_COFFEE_BUTTON flag + single root .env (envDir) + README note. EM-195 residuals filed (`BUILD_RESULTS_WAVEF.md`) |
| 2026-06-12 | Wave G ✅ | Inspector layout redesign shipped on `build/wave-g-inspector-layout` (user screenshots + /ui-ux-pro-max data-dense direction): **EM-196** social-graph white-box fix (canvas token reads get literal fallbacks; clean kapsule remount) + **EM-197** viewport-fit dashboard — no page scroll at desktop, per-panel internal scrolling, empty-panel collapse strips, structures chip grid, per-kind row heights (dialogue stays 2 lines), EM-093 anchoring with an "N new" pin. Browser-verified live: scrollHeight == viewport at 1440×900 and 1100×800, anchoring stable across live ticks, console clean (`docs/build-evidence/em197-inspector-*.png`). Web 649. Wave-F invariants intact (`BUILD_RESULTS_WAVEG.md`) |
| 2026-06-18 | Wave L intake | Smallville→Project Sid research + repo-grounded assessment → **EM-222–224** filed via `plan-intake` (`docs/research/smallville-to-sid-2026-06-18.md`), opening **W22** (Cognition). Three spikes after rejecting the doc's wrong premises (assumed Phaser/TS stack; rebuild-already-shipped stages — reflection EM-080, importance EM-159, relationships EM-113, governance EM-200; and the cost-minimization program that contradicts the max-call-rate north star): **EM-222** relevance-scored long-term retrieval (the one missing Smallville mechanism; gating open Q = does FreeLLMAPI expose embeddings?), **EM-223** recursive+reactive planning (must not fight the EM-159/160 spontaneity floor), **EM-224** PIANO coherence for multi-action turns (coherence only — reject the parallelize-for-latency motive). Open questions preserved per item |
| 2026-06-18 | Wave H ✅ | The Menagerie shipped (PR #17, `464c117`): **EM-143** god-spawn critters (`POST /api/god/spawn_animal` + AnimalSpawnForm) and a 7-species roster — cat/dog plus **squirrel/raccoon/goat/fox/crow** with per-species reflex tables + sensory cards (thieves carry `steal_food`); **EM-207** menagerie chaos (multi-species roaming + a rewild god burst + richer Animal Chaos Feed); **EM-208** the Living Zoo (zoo place-kind funded via the EM-062 project pipeline, marquee **breakout/ESCAPE** chaos event); **EM-209** pets & bonds (adopt → follow in 3D → light decline → grief diary on loss, threaded through EM-113 relationships). Reflex-first, population-capped. Also landed the EM-201 chronicle truncation/degenerate-reply guard. Backend 848 / frontend 752 tests (`test_menagerie.py`, `test_wave_h3_zoo.py`, `test_wave_h4_pets.py`). *No `BUILD_RESULTS_WAVE_H.md` was written.* |
| 2026-06-18 | Wave K ✅ | The Builders' City shipped (PR #18, `37f1e83`, `BUILD_RESULTS_WAVE_K.md`): **EM-217** agent-selectable `BUILD_TYPES` catalog (permissive — off-menu kinds still resolve via the EM-130 fallback), **EM-218** first-class `Prop` entity (Animal-pattern, seeded ids, `max_props` cap, snapshot round-trip, `PROP_MODELS`/`PlacedProps` render), **EM-219** remove + demolish (owner-free / public-landmark via ~70% supermajority), **EM-220** `Building.skin` recolor, **EM-221** god-console BUILDERS parity, **EM-182** agent-chosen placement (pulled into the wave). Verify pass caught + fixed 4 real backend bugs (god response shapes, 70% threshold, multi-action unhashable-id crash, skin destroyed-gate). Backend 922 / frontend 803. **EM-216 stays in-progress** — new-kit acquisition (Nature Kit etc.) is the one recorded HITL follow-on; systems consume the kits with zero further code. The #18 squash also folded the EM-222–224 Sid intake (PR #19) |
| 2026-06-18 | Ledger reconcile | `docs/reconcile-ledger-wave-hk`: flipped EM-143/207/208/209 `open`→`done` (Wave H shipped via PR #17 but its rows were never reconciled) and EM-201 `in-progress`→`done` (Chronicle tab/nav/auto/on-demand backfill all live). Filed **EM-225** (P3) for the deferred Chronicle multi-pass deep-dive so the unbuilt scope isn't silently dropped; next free ID → EM-226. Added the missing Wave H + Wave K closure-log rows above |
| 2026-06-19 | Asset deepening ✅ | Shipped on `main` since the reconcile: **EM-216** new-kit acquisition (PR #21, 20 CC0 GLBs — props + distinct build-types, ledger flipped done) + **more 3-D assets** (PR #23 — variant pools, distinct critters, expanded build-types) + **per-agent villager variety** (PR #24). All CC0 via poly.pizza + `@gltf-transform`; runbook `docs/em216-kit-acquisition-plan.md`. **EM-222 gating resolved** (PR #25): FreeLLMAPI embeddings live (`bge-m3`) |
| 2026-06-19 | Wave L / EM-222 ✅ | **Relevance-scored long-term memory retrieval** shipped (ultracode/orchestrator build: inline design+contract → 2-lane implement workflow → wave gate → 4-lens adversarial-verify workflow → fixes). Smallville-style recency×importance×relevance retrieval over the persisted event log for protagonist+supporting tiers, `bge-m3` embeddings cached in `event_embeddings`, graceful blind-recency fallback + embed wall-time budget + cooldown circuit-breaker, `embed` lane excluded from chat/failover. Verify caught 5 HIGH (recent-event duplication, embed-profile leaking into chat lanes ×2, unguarded embed latency, untested orchestration) — all fixed. Backend 975 tests incl. live :3001 smoke. Design + contract: `docs/superpowers/specs/2026-06-19-em222-memory-retrieval-design.md`. EM-223/224 (planning, PIANO coherence) remain open. |
| 2026-06-24 | Wave M intake | Gap analysis of `docs/research/deep-research-v1.md` (original Emergence-World deep research) vs shipped → **EM-227–238** filed via `plan-intake`, opening **W23** (Cooperation Economy). EW's emergence engine we have zero/partial coverage for, ranked by leverage: **cooperation economy** (P1 skills EM-227 → teach EM-228 / trade EM-230 / three-needs EM-229; P2 co-op-gated tools EM-231, peer-judged Victory-Arch credits EM-232, memory consolidation + soul entries EM-233, universalization prompt EM-234) and **Tier 3** texture (boost queue EM-235, living constitution EM-236, intimidate/deceive EM-237, police/justice EM-238). **EM-227 (skills) is the keystone** — EM-228/230/231 dep on it. Weapons Q resolved: EW had none (violence = tool calls); our attack/insult/steal/arson already match, so EM-237 only adds the two missing harm verbs. Not re-filed (already tracked): voice EM-214, weather EM-127 |

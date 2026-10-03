# PetriDishOfMadness — Start Here

> The one place to land. If you're lost, read this first.
> **Last updated:** 2026-10-03

A tiny, fast, cheap multi-agent world whose marquee feature is **per-agent model
control** — drop different LLMs (Gemini-Flash, Groq-Llama, Cerebras-Qwen, Mistral,
local Ollama) into the *same* society and watch them diverge. Small reinterpretation
of [Emergence-World](file:///Users/johns/Repos/ai-tools-and-frameworks/Emergence-World).

## Status at a glance

| Milestone | Scope | State |
|-----------|-------|-------|
| **v1** (W0–W3) | Engine · providers · persistence · API · 2D map + live feed · one-command deploy | ✅ Done |
| **W4** | Cozy 3D village + the marquee live multi-model run | ✅ Done — **EM-048 met** |
| **v2** (W5–W8) | `/inspector` annex · replay + decision traces · governance / social-graph / AWI dashboards · expanded world (buildings, collective projects, ad-hoc spawn, caching) · chaos animals | ✅ Done |
| **v2.1** (W9–W11) | Audit remediation (deep replay wired, survival pressure, extinction + routing-degraded UX) · trust & hygiene · chat-first layout · same-call cognition (commitments / 👻 phantoms, reflections, overhearing) · billboard + god replies · personas · procgen + housing · fork/resume | ✅ Done |
| **v3 art — Wave A** | Live-run correctness (humanized building names, build→repair redirect) + god-channel proclamations | ✅ Done |
| **v3 art — Wave B** | "The city comes alive" — golden-hour HDRI + toon shading, instanced foliage/props, per-place-kind buildings | ✅ Done |
| **v3 art — Wave C** | "A town, not a diorama" — real **CC0 GLB** buildings + animated villagers & critters, a 15-place district town, a real street network | ✅ Done |
| **Wave M** (W23) | Cooperation economy + governance texture (skills/teach/trade, harm-surface finishers, living constitution) | ✅ Done |
| **Wave N** (W24–W25) | Agent-controlled city layout — emergent road graph (`build_road`, demolish/car-policy votes, templates, procedural meshing, master-plan morphs) | ✅ Done — road mesh ON by default since the EM-247 sign-off (PR #65) |
| **Wave O** (W26) | Emergent society systems — belief/culture (memes), religion, organized war | ✅ Done — keystone + War merged PR #92 (2026-07-12), culture + religion (EM-251–255/260–263) merged PR #111 (2026-07-15); war + faith flipped ON live 2026-10-03 (dormant-flag sweep) |
| **Wave P** (W27) | Agent-controlled building layout (graph-derived zones) | Shipped dormant, then **superseded by F1/EM-268** (free placement); code stays on `main` behind default-off flags |
| **W29** | Offline-review remediation — 25 findings (EM-272–296) from the 2026-07-01 deep review | ✅ Done — PR #74 |
| **Wave Q** (W30) | World-authorship first slice — divergence probe (EM-297), agent-authored facades/murals (EM-298 ✅ PR #78), parametric building-recipe grammar keystone (EM-299) | ✅ First slice complete — EM-297 done PR #87, EM-298 done PR #78, EM-299 recipes merged PR #107 (2026-07-15); recipes flipped ON live 2026-10-03 (dormant-flag sweep) |
| **Multi-city expansion** | 2 cities + travel + world3d rendering (EM-109/EM-110/EM-121) | ✅ Merged PR #112 (2026-07-15); settlements flipped ON live 2026-10-03 (dormant-flag sweep — genesis "Ashvale" + homed agents verified) |
| **F1 free-placement** (W28) | Retire graph-lots placement; deterministic free-coordinate organic building placement, build-anywhere restored | ✅ **Merged + ratified** — PR #81/#82; derive-on-load restore behavior ratified by user 2026-07-09 |
| **Adaptive lane routing P1** | Custom sorting list + registry-owned bounce loop, replacing blind `auto` delegation | ✅ **Shipped PR #83 (2026-07-07); go-live flip 2026-07-08.** P2 (dynamic lane discovery/refresh) shipped PR #109 (2026-07-15), **flipped ON live 2026-10-02** (EM-325 heal). **P3 (429-aware lane cooldown + platform `resume_at` parking) + P5 (LaneHealthPanel observability board) shipped 2026-10-02** on `build/reentry-phase1`. P4 (direct-provider lanes) open — EM-300 |
| **W30** | Fable-audit remediation build — go-live flips, facades decal-clear fix, idle-fallback churn mitigation, ledger intake of the 2026-07-08 deep review | ✅ Done — PR #86 et al. |
| **W31** | Fable Tier-1 expansion (9 features EM-309–317) + the command-a-plus routing/chat fix (EM-319–324) | ✅ **All merged 2026-07-13** (PRs #94, #96–#104, #106; #95/#105 superseded by #106). **All 9 features flipped ON live 2026-10-03** (dormant-flag sweep). Live routing/chat fixed: 0 truncation feed cards, cast repinned to clean-JSON lanes |

**Where we are:** the lab is well past v1. The marquee feature is proven live — **EM-048**: a
3-agent / 3-model world ran on FreeLLMAPI for >11 minutes (all three alive, real chat, a passed
town-hall rule), with the model that *actually* answered each turn surfaced via `X-Routed-Via`.
The center view is now a real **CC0-art town** (Wave C): animated villagers and critters walk a
district street network past real buildings under golden-hour light — the procedural capsules and
the old hub-and-spoke pinwheel are gone. To run it yourself, see "Run the 5-minute live demo" in
`README.md`. Per-wave end-state reports live in `docs/build-results/`.

**What's next (2026-10-03, after the re-entry Phase-4 build):**
1. **Run a long-horizon tournament** — the EM-112/119 machinery is live (Runs tab → Model-Family
   Arena): cast 2–3 families at 100–300 ticks each and read the Gemini-vs-Llama civilization
   divergence off the arena standings (the v3 headline demo). Consider overnight for the full
   Emergence-World-style bake-off; EM-128's per-family AWI deltas are the natural follow-on.
2. **Turn the freshly-armed features into evidence** — the 2026-10-03 sign-off flipped EM-309–317,
   Wave O war+faith, EM-299 recipes, and the multi-city expansion ON live; the next watched run
   should read their emergent milestones off the feed (first war grievance→declare_war, first
   found_faith, first recipe-authored skyline, first Healing-House sentence) and land **EM-128's
   AWI-weighted per-family deltas** in the Arena.
3. **EM-300 P4** — direct-provider lanes (Gemini/Anthropic/OpenAI/Ollama without the proxy), the
   last open phase of adaptive lane routing (P3 cooldown/parking + P5 lane board shipped 2026-10-02).
4. **EM-326 cadence levers** — the ~3–4 ticks/min ceiling is structural and latency-bound (5
   serialized turns × p50 6–8s ok-latency); levers: turn concurrency (unfiled architecture work),
   EM-327 `supported_parameters`, EM-331 empty-contents 400s (our own requests feed the proxy's
   per-key cooldowns — `X-Request-ID` correlation is now unblocked). Also now unblocked: the
   tournament multiplies the cadence problem per family, so turn concurrency lifts every world.
5. **EM-301** idle-fallback churn thread (Ollama overflow lane, EM-167, is the identified lever).

See the closure log in `BUILD-PLAN.md` and `docs/REMAINING-WORK.md` for the full ledger. EM-151
(inspector blank on ~40k-event runs) shipped in Wave F.

**Recently merged (2026-07-15 sweep):** EM-297 divergence probe (#87), the W31 fresh-context
**review fix pack** including the EM-318 feed-silence **removal** (#108), EM-300 **P2** dynamic
lane discovery/refresh (#109), the EM-305 feed-flicker **WebSocket fix** (#110), **Wave O**
culture + religion (EM-251–255/260–263, #111), and the **multi-city expansion** — 2 cities +
travel + world3d rendering (EM-109/110/121, #112). Live config: comm **ON**, multi-city **OFF**
via `d97d8ea`. PRs #113 (Lab Setup panel) and #114 (`fix/feed-health`) merged in the interim.

**Recently landed (2026-10-03 re-entry Phase 4, EM-112 + EM-119):** the **parallel-worlds
tournament runner** (sequential all-Gemini vs all-Llama worlds through the live loop, one family
at a time — free-tier-safe) + the **Model-Family Arena** (cross-run civilization standings:
population / laws / buildings / crimes / credits + population sparklines per family, on the Runs
tab beside the run browser). `runs.model_family` stamps + fork inheritance; api.openapi 1.5.0.
Live-verified: a real 2-family/4-tick tournament on the proxy (~26s), runs stamped + aggregated.
Same session also fixed a **py3.11 `asyncio.wait_for` cancel race** that could hang
`TickLoop.reset()` forever (the EM-112 CI wedge) — `_run` re-delivers swallowed cancellations and
`pytest-timeout --timeout=300` guards every future run.

**Recently landed (2026-10-03 dormant-flag sign-off sweep, re-entry Phase 5):** the entire
dormant backlog flipped ON live on the FreeLLMAPI proxy and verified end to end — the **9 Fable
Tier-1 features** (EM-309 Blind Lineup masking the whole feed `???` with the guess card live;
EM-310 Chimera Twins spawning a real Vesper II/III pair with a divergence card at tick 5;
EM-311 charters seeded + organic `charter_revised`; EM-313 fingerprint guesses converging vs
`X-Routed-Via`; EM-314 Babel Matrix serving real dyadic cells; EM-317 prophecy posted →
deterministically resolved), **Wave O war + faith**, **EM-299 building recipes**, and the
**multi-city expansion** (genesis settlement "Ashvale" + homed agents). Frontend env flags
(`VITE_BLIND_LINEUP`, `VITE_STORYLINES_RAIL`, `VITE_DRAMA_WIRE`, `BABEL_MATRIX_ENABLED`) now
default ON; EM-314's backend half boots via `PETRIDISH_BABEL_MATRIX_ENABLED=1`. Loader defaults
stay OFF (goldens byte-identical); the 8 dormant-state guard tests flipped with the sweep.

**Recently landed (2026-10-02 re-entry, `build/reentry-phase1`):** the ledger reconcile + WIP
salvage (reactive per-lane 429 cooldown + LaneHealthPanel), the **EM-325 live heal** (discovery
ON, dead-pin repins, mistral-large retired) with the **EM-326 cadence A/B** recorded (3–4
ticks/min is a structural, latency-bound ceiling — "self-heals" refuted), the **EM-331** filing
(our empty-contents 400s feed the proxy's per-key cooldowns), the bare-JSON-array crash fix, and
**EM-300 P3 + P5 + EM-328 (partial)** — proactive platform `resume_at` parking, the
platform-aware LaneHealthPanel, and `X-Request-ID`/`X-Fallback-Trail` capture into lane health.

## Which doc is which (ownership map)

**Canonical — the living plan (edit these):**
- `BUILD-PLAN.md` — strategic roadmap (waves + exit criteria) + closure log
- `docs/REMAINING-WORK.md` — every **open / in-progress** item, ID'd + prioritized (EM-### scheme). Kept lean: `done` rows are swept out (see below)
- `docs/COMPLETED-WORK.md` — the **completed archive**: every shipped item's row, verbatim (the tactical detail behind the closure log). Append-only history; keeps the open ledger short + cheap to load
- `docs/FUTURE.md` — explicitly out of scope for v1 (the deferred non-goals)
- `ASSET_LICENSES.md` — the CC0-only art ledger (every vendored GLB/HDRI, source + license)

**Frozen reference (read, don't edit):**
- `docs/superpowers/specs/2026-05-26-petridish-of-madness-design.md` — the approved v1 design spec. Source of truth for what v1 is. Changes go through a spec revision, not ad-hoc edits.
- Each later wave files its own spec under `docs/superpowers/specs/` and its end-state report under `docs/build-results/` (e.g. `BUILD_RESULTS_WAVEC.md`).

**Archived (history; superseded):**
- _none yet_ — superseded drafts will live under `docs/archive/` with a breadcrumb.

## How work flows in

Reports don't rot here. A deep-dive, audit, QA, or review report becomes tracked work via
the report→ledger intake loop: run the **`plan-intake`** skill on the report, approve the
proposed entries, and they land in `docs/REMAINING-WORK.md` + the closure log in
`BUILD-PLAN.md`. `plan-intake` is fail-closed — nothing is filed without explicit approval.
See the `living-plan` skill for the full convention.

Work also flows **out**: when an item ships, its row is swept from `docs/REMAINING-WORK.md`
to `docs/COMPLETED-WORK.md` (the completion sweep — `plan-intake` does this as a final step,
or do it at any wave/PR close). History is preserved in full; the open ledger just stays a
short, current to-do list instead of an ever-growing pile of finished work.

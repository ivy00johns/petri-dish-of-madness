# PetriDishOfMadness — Start Here

> The one place to land. If you're lost, read this first.
> **Last updated:** 2026-07-09

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
| **Wave N** (W24–W25) | Agent-controlled city layout — emergent road graph (`build_road`, demolish/car-policy votes, templates, procedural meshing, master-plan morphs) | ✅ Done — visual sign-off on `ROAD_MESH_ENABLED` deferred |
| **Wave O** (W26) | Emergent society systems — belief/culture (memes), religion, organized war | open (EM-249–263) |
| **Wave P** (W27) | Agent-controlled building layout (graph-derived zones) | Shipped dormant, then **superseded by F1/EM-268** (free placement); code stays on `main` behind default-off flags |
| **W29** | Offline-review remediation — 25 findings (EM-272–296) from the 2026-07-01 deep review | ✅ Done — PR #74 |
| **Wave Q** (W30) | World-authorship first slice — divergence probe (EM-297), agent-authored facades/murals (EM-298 ✅ PR #78), parametric building-recipe grammar keystone (EM-299) | EM-298 done; EM-297/299 open |
| **F1 free-placement** (W28) | Retire graph-lots placement; deterministic free-coordinate organic building placement, build-anywhere restored | ✅ **Merged + ratified** — PR #81/#82; derive-on-load restore behavior ratified by user 2026-07-09 |
| **Adaptive lane routing P1** | Custom sorting list + registry-owned bounce loop, replacing blind `auto` delegation | ✅ **Shipped PR #83 (2026-07-07); go-live flip 2026-07-08.** P2–P5 (discovery/refresh, 429 cooldown, direct-provider lanes, observability) open — EM-300 |
| **W30** | Fable-audit remediation build (this build) — go-live flips, facades decal-clear fix, idle-fallback churn mitigation, ledger intake of the 2026-07-08 deep review | in progress, branch `build/w30-audit-remediation` |

**Where we are:** the lab is well past v1. The marquee feature is proven live — **EM-048**: a
3-agent / 3-model world ran on FreeLLMAPI for >11 minutes (all three alive, real chat, a passed
town-hall rule), with the model that *actually* answered each turn surfaced via `X-Routed-Via`.
The center view is now a real **CC0-art town** (Wave C): animated villagers and critters walk a
district street network past real buildings under golden-hour light — the procedural capsules and
the old hub-and-spoke pinwheel are gone. To run it yourself, see "Run the 5-minute live demo" in
`README.md`. Per-wave end-state reports live in `docs/build-results/`.

**Open P1:** EM-297 (world-authorship divergence probe), EM-299 (parametric building-recipe
grammar keystone), EM-300 (adaptive lane routing P2–P5), EM-301 (idle-fallback churn — PR
#84 open), plus the P1 backlog in Wave M/N/O/Q (see `docs/REMAINING-WORK.md`). EM-151
(inspector blank on ~40k-event runs) shipped in Wave F.

**Recently merged (2026-07-07):** agent-authored **facades & murals** (#78, EM-298 —
`paint_surface` + decal render, SHIPPED), the **EM-268 F1 free-placement go-live** (#81 —
cluster-accretion placement, build-anywhere restored), a **post-merge green-up** (#82 —
position goldens + EM-298 round-trip fix), a **revert of the 8192 length-retry floor** (#80 —
PR #77's raise excluded free models, rolled back), and **adaptive lane routing P1** (#83 —
registry + custom sorting list + bounce loop). **PR #84 is open** (idle-fallback timeout
labeling + auto-resume, EM-301).

**In flight (2026-07-09):** **F1 free-placement merged + ratified** (PR #81/#82; derive-on-load
restore behavior locked in 2026-07-09 — closes the paused restore-contradiction gate). **Adaptive
lane routing P1 live** (registry + custom sorting list + bounce loop, PR #83, go-live flip
2026-07-08). **PR #84 open** (timeout labeling + auto-resume for the idle-fallback churn thread,
EM-301). Current work: **W30 remediation build** on branch `build/w30-audit-remediation` — a
Fable-audit-driven pass (this build) fixing the soft-pin/bounce-loop conflict, the facades
decal-clear bug, and filing the 2026-07-08 deep-review findings into the ledger (EM-300–306).

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

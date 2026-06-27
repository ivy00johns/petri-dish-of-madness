# PetriDishOfMadness — Start Here

> The one place to land. If you're lost, read this first.
> **Last updated:** 2026-06-24

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

**Where we are:** the lab is well past v1. The marquee feature is proven live — **EM-048**: a
3-agent / 3-model world ran on FreeLLMAPI for >11 minutes (all three alive, real chat, a passed
town-hall rule), with the model that *actually* answered each turn surfaced via `X-Routed-Via`.
The center view is now a real **CC0-art town** (Wave C): animated villagers and critters walk a
district street network past real buildings under golden-hour light — the procedural capsules and
the old hub-and-spoke pinwheel are gone. To run it yourself, see "Run the 5-minute live demo" in
`README.md`. Per-wave end-state reports live in `docs/build-results/`.

**Open P1:** none. EM-151 (inspector blank on ~40k-event runs) shipped in Wave F.

**Recently merged (2026-06-24):** a wide-ranging asset-library expansion toward the
EW-grade dense city — building-pool variety + **26 new CC0 GLBs** (buildings #42 + props #43,
consolidated #43), **ambient moving traffic + parked cars** (#44, EM-169/176), golden-hour
**dust motes** (#46, EM-127 partial), and **auto-pause on a sustained provider outage** (#47,
EM-226). All CC0-enforced + recorded in `ASSET_LICENSES.md`; the poly.pizza vendoring runbook
is `docs/em216-kit-acquisition-plan.md`.

**In flight (2026-06-24):** **deepening the first city** before founding a second (the
EM-115/122/123 depth track) — **EM-123 zoned districts that mature as megaprojects complete**
(`Neighborhood` tier model; a completed collective building levels its district up, and the
3-D city answers with deterministic extra street life — never filler buildings, EM-174-safe;
byte-identical until a district actually grows). Branch `feat/district-growth`.

## Which doc is which (ownership map)

**Canonical — the living plan (edit these):**
- `BUILD-PLAN.md` — strategic roadmap (waves + exit criteria) + closure log
- `docs/REMAINING-WORK.md` — every open item, ID'd + prioritized (EM-### scheme)
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

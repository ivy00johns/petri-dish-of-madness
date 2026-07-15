# Lab Setup — admin/control panel design

**Date:** 2026-07-15
**Status:** Approved design (pre-implementation)
**Author:** brainstormed with the user, 2026-07-15

## Problem

PetriDishOfMadness has ~23 world-system flags in `config/world.yaml` plus the
`adaptive_routing`/`discovery` block in `config/lanes.yaml`. They bake per-run
(`runs.config_json` is captured at genesis; you restart `./dev` to adopt), and
they are scattered across two YAML files. Two concrete pains follow:

1. **"Why is it happening now but wasn't before?"** — a flag baked into *this*
   run that wasn't in the last one is invisible; there is no one place that shows
   the current run's flag state, let alone a diff against what you're about to run.
2. **Surprise routing failures.** Enabling flags grows the prompt. On 2026-07-15,
   turning `comm` + `settlements` on grew the agent prompt past what the pinned
   free lanes fit in their 1024-token output ceiling, so they emitted reasoning
   preamble and truncated (`finish_reason='length'`), the curated-clean lanes went
   `sick`, and the bounce cascaded into dirty reasoning lanes — a flood of idle
   fallbacks. See memory `finish-length-flood-is-flag-weight`. Nothing warned that
   this combo would cost more than the free lanes could pay.

**Goal:** a panel that makes composing a run *predictable* — pick a flag combo,
see the request size it generates and the model tier that combo needs (or a
"known risk: this will burn/truncate free lanes" warning), then apply via restart.

## Non-goals (v1)

- **Not a live mid-run controller.** Almost every flag bakes per-run; the panel
  stages the *next* run. (The handful of hot-swap levers — per-agent model/tier,
  speed, god actions — already have UI and are out of scope here.)
- **Not an auto-spender.** The recommender *advises* a tier; it never switches
  billing. It honors the subscription-only billing law (memory
  `billing-subscription-only`): a "needs paid/best lane" verdict is information for
  the user to act on, defaulting to subscription-covered / user-provisioned higher
  tiers, never Anthropic API overage on the sim's critical path.

## Shape

A dedicated in-app view ("Lab Setup") in the existing React app, reached by a
view/route switch from the live sim. Read-mostly of the current run; the only
write is **Apply & restart**. The estimator and recommender are the centerpiece;
the toggles exist to feed them.

## Components

### Frontend — `web/src/components/labsetup/`

- **`LabSetupView`** — container; loads current baked config + capability table,
  holds the pending-combo state, lays out the sections below.
- **`FlagBoard`** — the switch inventory in two groups:
  - **Prompt-weight flags** (move the estimate): `comm`, `settlements`,
    `faith`/religion (absent-defaulted block), `factions`, `universalization`,
    `memory_retrieval`, `buildings`, `planning`, `narrator`, `miracles`,
    `children`, `animals`, `image_gen`, `healing_house`, `charters`,
    `chimera_twins`, `coherence`, `generations`, `war` (absent adds no prompt
    line; enabling adds the war governance lane + grievance prompt).
  - **Routing/ops flags** (do not change prompt size): `lane_failover`,
    `overflow_lane`, `cap_governor`, `usage_caps`, `cache`, and lanes.yaml
    `discovery`.

  The exact inventory is enumerated at plan time from `loader.py` params ∪
  `world.yaml` ∪ `lanes.yaml` (the above is the known set as of 2026-07-15).
  Group membership is decided by one objective test the plan applies mechanically:
  **does enabling the flag change the built prompt?** — run the estimator with the
  flag on vs off against the seed snapshot; non-zero token delta ⇒ prompt-weight,
  zero ⇒ routing/ops. This keeps the grouping honest as flags are added.
  Each toggle stages a *pending* change and renders a **baked-vs-pending diff**
  against the current run. Every flag shows a "needs restart" marker (all v1 flags
  bake per-run).
- **`EstimatePanel`** — renders the `/api/estimate` result for the pending combo:
  headline total input tokens, a stacked per-flag breakdown, and the output budget
  (max_tokens). v2: observed-size overlay next to the prediction.
- **`Recommender`** — the verdict banner + safe/risky lane sets + per-cast-pin
  risk flags, computed from the estimate × capability table (see logic below).
- **`CapabilityTable`** — per-lane rows: provider, free/paid, context window,
  reliability tag, (v2) observed truncation rate.
- **`ApplyBar`** — "Apply & restart": shows the exact config diff, confirms, writes,
  triggers a fresh run.

Mounted via a view switch in `App.tsx` (follow the existing panel/route pattern;
reuse the shared API client in `web/src/lib` and types in `web/src/types`).

### Backend — `backend/petridish/api/` + estimator/capability modules

- **`GET /api/config/flags`** — current run's *baked* flag state + the on-disk
  *pending* state, so the panel can diff. Extends the existing `/api/config`.
  **Must merge three sources for the true baked state:** explicit `world.yaml`
  blocks, **loader-default blocks absent from the YAML** (e.g. `world.faith`
  defaults `enabled: false` and is not written in `world.yaml` at all — see
  `loader.py`), and `lanes.yaml`. Reporting only what's written in the YAML would
  hide exactly the "absent-and-defaulted" flags that confuse "why now / why not
  before".
- **`POST /api/estimate`** — body: `{ flag_overrides: {...}, snapshot: "current" |
  "seed" }`. Runs the **real** prompt builder (`runtime.build_messages`) with the
  overridden flags against the chosen world snapshot for a representative
  protagonist, tokenizes, returns `{ total_input_tokens, output_budget,
  breakdown: [{flag|"base", tokens}] }`. No LLM call — build + count only.
- **`GET /api/lanes/capability`** — the capability table (see below).
- **Apply** — writes staged `world.yaml`/`lanes.yaml` changes and starts a fresh
  run (see "Apply mechanism").

New backend modules:
- `backend/petridish/engine/estimator.py` — flag-override + build + tokenize.
- `backend/petridish/providers/capability.py` — derive the capability table.

## Estimator design (real build + tokenize)

- **Override without mutating the live world:** construct a params object with the
  overridden flags (copy of the run's params with flags replaced), take a snapshot
  of the current world (or a canonical seed world), pick a representative
  protagonist agent, and call `build_messages(agent, world, recent_events,
  params_override)`. The running sim is untouched.
- **Tokenizer:** use one consistent reference tokenizer (tiktoken `cl100k_base`)
  across all lanes. The absolute number is an approximation — real lanes tokenize
  differently — but the estimate is used comparatively (base + deltas) and against
  thresholds calibrated in the *same* unit, so consistency matters more than
  per-model exactness. Documented as approximate.
- **Breakdown:** the headline total is the real build of the exact combo
  (authoritative). The per-flag breakdown shows `base` (all prompt-weight flags
  off) plus each flag's **independent marginal delta** (`base+flag − base`). Sum of
  marginals may differ slightly from `total − base` when flags interact; the real
  total is shown as authoritative and the breakdown is labeled "marginal
  contributions" to stay honest.
- **Determinism:** same snapshot + same flags ⇒ same token count (a test invariant).

## Recommender logic (v1, curation-driven; calibrated by observed data in v2)

Inputs: the estimate `E` (input tokens) and the capability table.

Threshold model (seed values, calibrated later by observed data):
- `T_clean` — max input size at which the free **clean** instruct lanes reliably
  emit strict JSON within the 1024 output budget. Seed ≈ 4,500–5,000 tokens
  (educated from the 2026-07-15 incident where the heavier combo tipped them over).
- `T_paid` — above `T_clean`, only paid/best or trimmed combos are safe.

Verdicts:
- `E ≤ T_clean` → **free clean lanes OK** (the curated `order`).
- `T_clean < E ≤ T_paid` → **free lanes at risk → run paid/best, or trim a flag.**
- Reasoning/dirty lanes are **always flagged risky** at agent-turn prompt sizes —
  they truncate on the heavy strict-JSON prompt regardless of `E` (this is the
  class, not the size).

Outputs:
- **Verdict banner** — e.g. "≈3,940 → free clean OK" / "≈6,200 → known risk: free
  lanes will truncate; use paid or drop a flag".
- **Safe vs risky lane sets** — from the capability table.
- **Per-cast-pin risk flags** — cross-reference the current cast pins against the
  safe set ("Mox→kimi will truncate on this combo; bounce lands on `auto`").
- **Fail-closed:** a lane with `unknown` reliability is never placed in "safe".

## Capability table (new source of truth)

`GET /api/lanes/capability` → per lane/profile:
`{ provider, free, context_window, reliability: "clean" | "reasoning" | "unknown",
   observed_truncation_rate? }`

Derivation:
- `provider`, `free`, base `max_tokens` — from `profiles.yaml`.
- `reliability` — `clean` if the lane's model resolves inside the lanes.yaml curated
  `order` (excluding the `*` sweep and `auto`) and is not in `exclude`; `reasoning`
  if in `exclude` or in a maintained `reasoning_models` seed set (kimi-k2.6,
  zai-glm-4.7, gemini-3.5-flash, deepseek-v4-pro, llama-3.3-70b-versatile,
  qwen3-next-80b, and gpt-oss-120b as clean-but-CoT-truncates-on-heavy); `unknown`
  otherwise.
- `context_window` — a static per-model lookup (add an optional `context_window`
  field to `profiles.yaml`, or a keyed table); `unknown` when absent.
- `observed_truncation_rate` — v2, from run history.

## Apply mechanism (open item to resolve in planning)

`Apply & restart` writes the staged `world.yaml`/`lanes.yaml` changes and starts a
fresh run that re-bakes config. **Constraint:** `uvicorn --reload` is banned here
(memory `dev-reload-kills-live-sim` — it forks a paused run). So the re-bake path is
one of:
- **(a)** an in-process endpoint that re-reads config from disk and re-genesis's a
  new run (verify whether `POST /api/control/reset` already re-reads
  `config_json` from disk, or add an endpoint that does), or
- **(b)** a "restart `./dev`" instruction surfaced in the UI with the diff shown.

Plan must confirm which. Apply **always** shows the exact config diff and confirms
first — never silent (memory `fix-dont-hide-the-feed` spirit: surface, don't hide).

## Data flow

`FlagBoard` (pending combo) → `POST /api/estimate` → `EstimatePanel` renders the
breakdown → `Recommender` cross-references `GET /api/lanes/capability` + thresholds
→ verdict + safe/risky sets + cast-pin flags. `ApplyBar` → write config → fresh run.

## Error handling

- Estimator/builder error → show "couldn't estimate" (no fake number).
- Capability gaps (unknown lane) → `unknown` reliability, excluded from "safe"
  (fail-closed).
- Apply → confirm dialog with the exact diff; never silent; on write failure, keep
  the pending state and surface the error.

## Testing

- **Backend:** estimator determinism (same snapshot+flags ⇒ same count); monotonic
  per-flag deltas (adding a prompt-weight flag never lowers tokens); capability-table
  derivation from profiles.yaml + lanes.yaml; recommender boundary verdicts around
  `T_clean`/`T_paid`; reasoning lanes always risky.
- **Frontend:** flag-board staging + baked-vs-pending diff; estimate breakdown
  render; verdict rendering per size bucket; capability table; apply confirm/diff.
  Reuse existing vitest patterns (run with cwd `web/`, per memory
  `petridish-test-toolchain`).

## Phasing

- **v1:** grouped flag board + real-builder estimator + curation recommender +
  capability table + apply-restart.
- **v2:** observed-size overlay — instrument run history to record real prompt
  sizes + per-lane truncation rates; show predicted-vs-actual; auto-calibrate the
  `T_clean`/`T_paid` thresholds and populate `observed_truncation_rate`.

## Open items for the plan

1. Apply mechanism (a) vs (b) — confirm whether `reset` re-reads config from disk.
2. `context_window` source — new `profiles.yaml` field vs a static keyed table.
3. Exact `T_clean`/`T_paid` seed values — pick a defensible starting point; they
   are calibrated in v2 regardless.
4. Snapshot for the estimator — current run vs a canonical seed as the default.

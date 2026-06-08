# EmergenceMadness — Start Here

> The one place to land. If you're lost, read this first.
> **Last updated:** 2026-05-26

A tiny, fast, cheap multi-agent world whose marquee feature is **per-agent model
control** — drop different LLMs (Gemini-Flash, Groq-Llama, Cerebras-Qwen, Mistral,
local Ollama) into the *same* society and watch them diverge. Small reinterpretation
of [Emergence-World](file:///Users/johns/Repos/ai-tools-and-frameworks/Emergence-World).

## Status at a glance

| Wave | Scope | State |
|------|-------|-------|
| W0 | Scaffold & contracts | ✅ Done |
| W1 | Engine, providers, persistence | ✅ Done (55 tests pass) |
| W2 | API & frontend (2D map + live feed) | ✅ Done (renders live, console clean) |
| W3 | Integration, QE, deploy | ✅ Done (QA gate + render-sanity PASS) |
| W4 | Cozy 3D village + live multi-model run | ✅ Done (live 3-agent run; routed-via surfaced) |

**v1 + W4 complete.** W4 lives on branch `build/emergence-madness-3d`. The center view is now a
cozy 3D village (Stardew × Animal-Crossing) built with React Three Fiber, and **EM-048 — the
project goal — is done**: a 3-agent / 3-model world ran live on FreeLLMAPI for >11 minutes (all
three alive, real chat, a passed town-hall rule). Because the proxy is a best-available router,
the UI shows the model that *actually* answered each turn (`X-Routed-Via`). To run it yourself,
see "Run the 5-minute live demo" in `README.md`. End-state report: `BUILD_RESULTS_3D.md`.

## Which doc is which (ownership map)

**Canonical — the living plan (edit these):**
- `BUILD-PLAN.md` — strategic roadmap (waves + exit criteria) + closure log
- `docs/REMAINING-WORK.md` — every open item, ID'd + prioritized (EM-### scheme)
- `docs/FUTURE.md` — explicitly out of scope for v1 (the deferred non-goals)

**Frozen reference (read, don't edit):**
- `docs/superpowers/specs/2026-05-26-emergence-madness-design.md` — the approved design spec. Source of truth for what v1 is. Changes go through a spec revision, not ad-hoc edits.

**Archived (history; superseded):**
- _none yet_ — superseded drafts will live under `docs/archive/` with a breadcrumb.

## How work flows in

Reports don't rot here. A deep-dive, audit, QA, or review report becomes tracked work via
the report→ledger intake loop: run the **`plan-intake`** skill on the report, approve the
proposed entries, and they land in `docs/REMAINING-WORK.md` + the closure log in
`BUILD-PLAN.md`. `plan-intake` is fail-closed — nothing is filed without explicit approval.
See the `living-plan` skill for the full convention.

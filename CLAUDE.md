# PetriDishOfMadness

> **Start here:** see [`START-HERE.md`](START-HERE.md) for current status and the ownership map.

A tiny, cheap, fast multi-agent chaos lab — per-agent hot-swappable model control across
FreeLLMAPI / Ollama / Anthropic / Gemini. Small reinterpretation of Emergence-World.

- **Design (frozen):** `docs/superpowers/specs/2026-05-26-petridish-of-madness-design.md`
- **Roadmap:** `BUILD-PLAN.md` · **Open work:** `docs/REMAINING-WORK.md` · **Out of scope:** `docs/FUTURE.md`
- **Reports → tracked work:** run the `plan-intake` skill; it files entries into the ledger (fail-closed).

<!-- andon:start -->
This repository keeps what it has learned in `.andon/`: one memory entry a file under `memory/<kind>/`, longer notes under `knowledge/`, plans under `plans/` (`.andon/README.md` says how).
Those entries are the repository's memory: Andon puts the relevant ones and the project's plan in a run's prompt; read the rest yourself, and record something by adding a file there, never by editing an entry in place.
`andon memory show` prints the live set (accepted entries, their chains resolved) from this directory, with no board needed.
<!-- andon:end -->

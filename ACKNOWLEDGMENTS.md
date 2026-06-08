# Acknowledgments

PetriDishOfMadness is an independent, from-scratch project — but the *idea* isn't ours.
It's a small, cheap reinterpretation of the multi-agent world pioneered by:

**[Emergence-World](https://github.com/EmergenceAI/Emergence-World)** by **[EmergenceAI](https://github.com/EmergenceAI)**

They did the research and built the original: a large, real-time society of ~10
agents with 120+ tools across 5 parallel worlds, demonstrating genuine
multi-agent emergence — cooperation, conflict, governance, and culture arising
from simple agents in a shared world.

## What we borrowed

The *ideas*, not the code. PetriDishOfMadness was written independently and shares
no source with Emergence-World. From their work we took the core thesis:

- A shared, tick-driven world where autonomous LLM agents live, talk, trade, fight, and govern.
- Emergence as the point — interesting behavior should *arise* from simple rules + agency, not be scripted.
- Stakes (needs, scarcity, death) as the engine of strategy and drama.

## How PetriDishOfMadness differs

Where Emergence-World is large and ambitious, PetriDishOfMadness is deliberately
tiny, cheap, and fast — a petri dish rather than a world:

- **4–6 agents**, a full arc in 30–60 minutes, runnable for free on FreeLLMAPI / local Ollama.
- **Per-agent, hot-swappable model control** is the marquee feature: drop different LLMs into the *same* society and watch them diverge, color-coded by model. The experiment *is* the comparison.
- A small JSON-action protocol built for robustness across free/local models (no reliance on native function-calling).

If you want the real thing — depth, scale, and the original research — go look at
[Emergence-World](https://github.com/EmergenceAI/Emergence-World). This project
exists because their ideas were too fun not to play with on a budget.

## Built with Skill-Madness

PetriDishOfMadness was built end-to-end with **[Skill-Madness](https://github.com/ivy00johns/Skill-Madness)** — the skill / agent
toolchain that carried it from idea to shipped build. The design was brainstormed into a
frozen spec, integration contracts were authored up front, and the implementation ran as a
parallel multi-agent build (backend · frontend · infra · QE) gated by automated render and
UX checks. The skills that shaped this repo — `orchestrator`, `contract-author`,
`frontend-design`, `ui-ux-pro-max`, `mermaid-charts`, `render-sanity`, `ux-review`, and more
— are catalogued in [`coordination/MISSION_SKILLS.md`](coordination/MISSION_SKILLS.md).

## Runs on FreeLLMAPI

The whole "watch different models diverge — for free" premise rides on
**[FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)** by
[tashfeenahmed](https://github.com/tashfeenahmed): a local, OpenAI-compatible proxy that
aggregates 14 free provider tiers (~1.7B tokens/month) behind a single endpoint. It's a
*best-available router* — a request for one model is often served by whichever provider is
up, which is exactly the divergence this lab puts on screen (the UI surfaces the model that
*actually* answered via the `X-Routed-Via` header). Install guide:
<https://tashfeenahmed.github.io/freellmapi/>.

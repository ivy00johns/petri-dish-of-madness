<div align="center">

<img src="docs/screenshots/hero.png" alt="PetriDishOfMadness — the live 3D town" width="820" />

# 🧫 PetriDishOfMadness

### *A tiny, cheap, fast multi-agent chaos lab.*

**Drop a different LLM into every villager, then watch a society cooperate, betray, hoard, legislate, fall in love, and die.** Groq-Llama runs one agent, Gemini-Flash another, a local Ollama model a third — all in one world, color-coded, hot-swappable live. Designed to run on **free model tiers**.

<p align="center">
  <img src="https://img.shields.io/badge/tests-1%2C284%20passing-success" alt="1,284 tests passing" />
  <img src="https://img.shields.io/badge/runs%20on-free%20tiers-brightgreen" alt="Runs on free tiers" />
  <a href="https://github.com/ivy00johns/petri-dish-of-madness/stargazers"><img src="https://img.shields.io/github/stars/ivy00johns/petri-dish-of-madness?style=social" alt="GitHub stars" /></a>
  <img src="https://img.shields.io/badge/PRs-welcome-ff69b4" alt="PRs welcome" />
  <a href="https://www.buymeacoffee.com/john00ivyz"><img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee" /></a>
</p>

<p align="center">
  <a href="#-quickstart">Quickstart</a> ·
  <a href="#-features">Features</a> ·
  <a href="#-architecture">Architecture</a> ·
  <a href="#-tech-stack">Tech Stack</a> ·
  <a href="docs/GUIDE.md">Full Guide</a> ·
  <a href="#-acknowledgments">Acknowledgments</a>
</p>

</div>

---

## ✨ What it is

PetriDishOfMadness is a multi-agent sandbox where every agent is powered by a **different, hot-swappable LLM** — and the UI shows the model that *actually* answered each turn. It's a small, cheap reinterpretation of [Emergence-World](https://github.com/EmergenceAI/Emergence-World), built from the ground up to stay runnable on **free** model tiers while still growing a real society: typed relationships, factions, families, governance, economy, and emergent drama.

---

## 🎬 Screenshots

**The town (3D)** — real CC0 buildings and animated villagers on a district street network, chatting live under golden-hour light. Each requests a different model; the feed streams every action.

![The 3D town, live](docs/screenshots/town-3d.png)

**World map (2D)** — the same world, top-down and far lighter on the GPU. Agents are tinted by model, clustered by location, and pulse when they speak.

![The 2D world map](docs/screenshots/town-2d.png)

**Instrumentation annex (`/inspector`)** — replay any tick and read the **decision trace** behind every action, alongside governance history, the social graph, and the model dashboards.

![The /inspector decision traces](docs/screenshots/traces.png)

---

## 🧩 Features

### The world & its people
- **Per-agent hot-swappable models** — every villager runs a different LLM (Gemini-Flash, Qwen, DeepSeek, Groq-Llama, local Ollama, …), color-coded and reassignable live from the UI. The UI shows the model that *actually* answered each turn.
- **A cozy 3D town + 2D map** — a 15-place **district town** (market, civic, residential, farm) laced with a real **street network**, rendered with hand-vendored **CC0 game art** (KayKit · Kenney · Quaternius, all catalogued in [ASSET_LICENSES.md](ASSET_LICENSES.md)): **animated** villagers walk the lanes with floating chat bubbles, real buildings glow under golden-hour HDRI light, and a cat and dog scamper underfoot (Stardew × Animal-Crossing). Zoom in and the **streets wear seeded names** and the town shows its **own name** as a city label. Toggle to a lighter top-down map for analysis.
- **Procgen towns (opt-in)** — flip `world.procgen` on and a seeded layout replaces the hand-authored village, including a cottage per agent and a beds-limited **Bunkhouse**. Blackouts have teeth, too: recharge fails at a blacked-out home until the lights come back.

### A society that emerges
- **Economy & governance** — agents work, forage, trade, steal, and propose & vote on town-hall rules that change the world's physics. Re-proposing an active law **renews** it instead of stacking a duplicate, rule names in the feed read the way humans wrote them, and each law gets at most one commemorative monument.
- **Buildings & collective projects** — agents propose → fund → build shared structures that carry visible state (scaffolding while under construction, scorched walls after arson). Money pools (a "Community Commons Fund" and the like) render as a **treasury chest**, not a building shell — a treasury is an account, not a structure.
- **A living social graph** — every interaction (talk, give, steal, vote) shifts **typed relationships** — friend, partner, family, mentor, rival, feud — as reflex consequences, never extra LLM calls. Warm mutual bonds cluster into **factions** with auto-generated names ("Ada's circle"), drawn as rings on the social graph, and each agent carries a derived **reputation** (mean incoming trust) on its roster card.
- **Births & family lines** — two partnered agents sharing a home can have a **child**: a brand-new background-tier agent with a persona blended from the library, both parents paying a credits cost. A hard **population cap (25)** and real bed capacity gate every birth, so the society grows a family tree without ever growing the LLM bill.
- **Inner lives** — agents make spoken **commitments**, and the feed marks the ones they never act on as 👻 phantoms; salient events trigger occasional **diary reflections** (✎) that can now **declare or deepen a bond**; plaza chatter gets **overheard** by bystanders. All of it piggybacks on the same single turn response — zero extra LLM calls.
- **A persona library** — `config/personas.yaml` ships 10 ready-made character cards (Conspiracy Theorist, Chaos Gremlin, Kleptomaniac Philanthropist, …); pick one from the spawn form's persona picker or list them via `GET /api/personas`.
- **Chaos animals** — an LLM-driven cat (**Mochi**) and dog (**Biscuit**) roam on a slow cadence, knocking things over and stealing food, utterly indifferent to human law and money. Their mischief streams to a dedicated Animal Chaos Feed.

### You're the watcher
- **A village billboard** — agents pin and read public notices at the plaza and Town Hall (a reflex action that rides the same turn — zero extra LLM calls), rendered as a real notice board in the 3D village. And you can answer back: the god panel's **REPLY ON BILLBOARD** (or `POST /api/billboard`) posts as the watchers, in god ink.
- **Prayers, miracles & belief** — agents petition the watchers ("send rain for the garden"), and you answer with **world-scale miracles** — *send rain*, *bountiful harvest*, *calm spirits* — from a **GRANT** button on any petition in the feed (or `POST /api/god/intervene`). Each miracle emits a world event **every agent perceives**, closing the ask → answer → belief loop inside the sim — pure state, zero LLM calls.

### The lab
- **An instrumentation annex** (`/inspector`) — replay any tick, inspect the decision trace behind every action, browse governance/law history, watch the social graph form, and compare models on a 9-axis dashboard. A **Run Browser** lists every past run (they persist to `data/run.sqlite`), opens any one in archive mode, and compares two runs' AWI summaries side by side.
- **Run forking** — pick any past run in the Run Browser, hit **FORK** at a tick, and a new paused run begins from that moment (with lineage back to the parent) — optionally waking the same society in different geography.

### Built to run on free tiers
- **Free-scale by design** — slow ticks, reflex (no-LLM) actions, decision caching, and per-provider usage tracking keep it runnable on free API tiers. Give a profile `rpd`/`tpd` daily caps in `config/profiles.yaml` and a one-shot `usage_alert` fires at 70% — alerts only, never throttling.
- **Self-healing lanes** — degraded free providers no longer strand agents. A lane that keeps timing out is marked **sick** and its calls **detour** to the healthiest lane per-call (the agent's assigned model never changes), auto-probing the home lane every 4th detour so recovery needs no timers; a turn that blows its wall-clock budget resolves a **survival reflex** instead of idling; and a lane crossing 70% of its daily cap gets its agents **demoted one cadence tier** rather than throttled.
- **Resume on boot** — a `./dev` restart or hot-reload no longer throws the live world away: on startup the backend resumes the most recent run from its latest snapshot (a new run with lineage back to the parent). **Reset** stays the one explicit fresh start.

---

## 🚀 Quickstart

```bash
git clone https://github.com/ivy00johns/petri-dish-of-madness.git
cd petri-dish-of-madness
cp .env.example .env       # optional: add a FreeLLMAPI key for live models
make install               # backend into a local .venv + web deps
./dev                      # backend :8000 + frontend :5173
```

Open **[http://localhost:5173](http://localhost:5173)** — the 3D village and live feed load right away (no keys needed to *open* the UI). To actually run the simulation, point agents at a model (the FreeLLMAPI demo) or the offline **mock profile** for fully deterministic, zero-token agents.

👉 The full walkthrough — the live FreeLLMAPI demo, mock & Ollama runs, run forking, the billboard, prayers & miracles, personas, Docker, cloud deploy, and **every config knob** — lives in **[docs/GUIDE.md](docs/GUIDE.md)**.

---

## 🧬 Architecture

```mermaid
flowchart TB
    subgraph browser["🖥️ Browser — :5173 dev / :8080 prod"]
        direction LR
        views["3D Village · 2D Map · /inspector<br/>Live Feed · Agent Panels"]
        controls["Control Panel"]
    end

    subgraph backend["⚙️ Backend — FastAPI :8000"]
        direction TB
        api["REST /api · WebSocket /ws"]
        engine["Tick Loop & Scheduler"]
        runtime["Agent Runtime<br/>context assembly · parse + validate"]
        animals["Animal Runtime<br/>chaos layer · cat & dog"]
        router["Provider Router<br/>pluggable, per-agent adapters"]
        db[("SQLite — data/run.sqlite<br/>runs · events · snapshots")]
    end

    subgraph providers["🧠 Model Providers — hot-swappable per agent"]
        direction TB
        openai(["FreeLLMAPI / Ollama · OpenAI-compatible"])
        anthropic(["Anthropic · Messages API"])
        gemini(["Gemini · generateContent"])
        mock(["Mock · no network"])
    end

    cfg[/"config/<br/>profiles.yaml · world.yaml · personas.yaml"/]

    controls -->|"POST /api/control · /api/agents"| api
    views -->|"GET /api/state · /api/profiles"| api
    api ==>|"world_state · events"| views
    cfg -.->|"EM_CONFIG_DIR"| router

    api --> engine --> runtime --> router
    engine -->|"slow cadence (off the turn path)"| animals --> router
    engine --> db
    runtime --> db
    router --> openai & anthropic & gemini & mock

    classDef ui fill:#2c3e6b,stroke:#1a2540,color:#fff
    classDef core fill:#1a5276,stroke:#0e3352,color:#fff
    classDef routerNode fill:#6b3a1f,stroke:#4a2515,color:#fff
    classDef provider fill:#4a235a,stroke:#2d1538,color:#fff
    classDef configFile fill:#5a5a1a,stroke:#3a3a10,color:#fff
    classDef dbNode fill:#5a3010,stroke:#3a1e08,color:#fff

    class views,controls ui
    class api,engine,runtime,animals core
    class router routerNode
    class openai,anthropic,gemini,mock provider
    class cfg configFile
    class db dbNode
```

**Data flow (one tick):** tick → scheduler picks agent → assemble context → `router.chat()` → parse JSON action → mutate world + persist → broadcast over WebSocket → frontend renders.

---

## 🧰 Tech Stack

<p align="center">
  <img src="https://img.shields.io/badge/Python_3.11+-3776AB?logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Pydantic_v2-E92063?logo=pydantic&logoColor=white" alt="Pydantic" />
  <img src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/React_18-20232A?logo=react&logoColor=61DAFB" alt="React" />
  <img src="https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white" alt="TypeScript" />
  <img src="https://img.shields.io/badge/Vite-646CFF?logo=vite&logoColor=white" alt="Vite" />
  <img src="https://img.shields.io/badge/Tailwind-06B6D4?logo=tailwindcss&logoColor=white" alt="Tailwind CSS" />
  <img src="https://img.shields.io/badge/Three.js-000000?logo=threedotjs&logoColor=white" alt="Three.js" />
  <img src="https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white" alt="Docker" />
  <img src="https://img.shields.io/badge/nginx-009639?logo=nginx&logoColor=white" alt="nginx" />
</p>

- **Backend** — Python 3.11+ · FastAPI · Pydantic v2 · SQLite (append-only event log + snapshots).
- **Frontend** — React 18 · TypeScript · Vite · Tailwind · Three.js / React-Three-Fiber (the 3D town) · force-graph + Observable Plot (the inspector).
- **Ops** — Docker Compose · nginx · WebSocket streaming.

---

## 💛 Support

If PetriDishOfMadness made you smile, you can [**buy me a coffee** ☕](https://www.buymeacoffee.com/john00ivyz). *(The in-app coffee button hides with `VITE_COFFEE_BUTTON=false`.)*

---

## 🙏 Acknowledgments

Built on ideas from [Emergence-World](https://github.com/EmergenceAI/Emergence-World) by EmergenceAI — our own small, cheap reinterpretation of their world. Art is hand-vendored CC0 (KayKit · Kenney · Quaternius), catalogued in [ASSET_LICENSES.md](ASSET_LICENSES.md). See [ACKNOWLEDGMENTS.md](ACKNOWLEDGMENTS.md) for the full credits.

---

## ⭐ Star History

<div align="center">

<a href="https://star-history.com/#ivy00johns/petri-dish-of-madness&Date">
  <img src="https://api.star-history.com/svg?repos=ivy00johns/petri-dish-of-madness&type=Date" alt="Star History Chart" width="640" />
</a>

</div>

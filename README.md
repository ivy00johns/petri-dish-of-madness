# EmergenceMadness

A tiny, fast, cheap multi-agent chaos lab — drop different LLMs into the same society and watch them cooperate, betray, hoard, legislate, and die.

The marquee feature: **per-agent hot-swappable model control**. Groq-Llama runs one agent, Gemini-Flash runs another, a local Ollama model runs a third — all in one world, color-coded, live.

---

## Architecture

```mermaid
flowchart TB
    subgraph browser["Browser (localhost:5173 dev / :8080 prod)"]
        map[2D Canvas Map]
        feed[Live Event Feed]
        panels[Agent Panels]
        controls[Control Panel]
    end

    subgraph backend["Backend — FastAPI (localhost:8000)"]
        direction TB
        subgraph core["Sim Core"]
            engine[Tick Loop & Scheduler]
            runtime[Agent Runtime\ncontext assembly · action parse]
            db[(SQLite\nPersistence)]
        end
        subgraph api["API Surface"]
            rest[REST /api/...]
            ws[WebSocket /ws]
        end
        router[Provider Router]
    end

    subgraph providers["Model Providers"]
        freellm([FreeLLMAPI\nOpenAI-compatible proxy])
        ollama([Ollama\nlocalhost:11434])
        anthropic([Anthropic\nMessages API])
        gemini([Gemini\ngenerateContent])
        mock([Mock\nno network])
    end

    cfg[/"config/\nprofiles.yaml\nworld.yaml"/]

    controls -- "POST /api/control/\nPOST /api/agents" --> rest
    panels -- "GET /api/state\nGET /api/profiles" --> rest
    ws -- "events stream" --> feed
    ws -- "world_state" --> map

    rest --> engine
    engine --> runtime
    runtime --> router
    router --> db
    engine --> db
    engine -.-> ws

    router -- "openai adapter" --> freellm
    router -- "openai adapter" --> ollama
    router -- "anthropic adapter" --> anthropic
    router -- "gemini adapter" --> gemini
    router -- "mock adapter" --> mock

    cfg -- "EM_CONFIG_DIR" --> router

    classDef ui fill:#2c3e6b,stroke:#1a2540,color:#fff
    classDef core fill:#1a5276,stroke:#0e3352,color:#fff
    classDef apiSurface fill:#1e6b4a,stroke:#114432,color:#fff
    classDef routerNode fill:#6b3a1f,stroke:#4a2515,color:#fff
    classDef provider fill:#4a235a,stroke:#2d1538,color:#fff
    classDef configFile fill:#5a5a1a,stroke:#3a3a10,color:#fff
    classDef dbNode fill:#5a3010,stroke:#3a1e08,color:#fff

    class map,feed,panels,controls ui
    class engine,runtime core
    class rest,ws apiSurface
    class router routerNode
    class freellm,ollama,anthropic,gemini,mock provider
    class cfg configFile
    class db dbNode
```

**Data flow (one tick):** tick → scheduler picks agent → assemble context → `router.chat()` → parse JSON action → mutate world + persist → broadcast over WebSocket → frontend renders.

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.11+ | For local dev without Docker |
| Node.js | 18+ | For local dev without Docker |
| Docker + Compose | v2.x | For `make up` / `docker compose up` |

---

## Quickstart (one command)

```bash
# 1. Clone and enter the repo
git clone <repo-url> EmergenceMadness
cd EmergenceMadness

# 2. Copy the env template
cp .env.example .env

# 3. Install dependencies
pip install -e backend
cd web && npm install && cd ..

# 4. Start both backend + frontend
./dev
```

Open **http://localhost:5173** — the cozy 3D village and live feed load immediately in mock mode (no API keys required). Use the header toggle to switch the center view between **THE VILLAGE** (3D) and the legacy 2D **WORLD MAP**.

---

## Run the 5-minute live demo — 3 agents in the 3D village (FreeLLMAPI)

The default world is **3 cozy villagers** (Ada, Bram, Cleo) who start together in the
plaza and chat, trade, forage, and pass town-hall rules. Each requests a different model;
all are routed through a local [FreeLLMAPI](https://github.com/tashfeenahmed/freellmapi)
OpenAI-compatible proxy. The center view is a **cozy 3D village** (Stardew × Animal-Crossing
vibe) — villagers walk between buildings with floating chat bubbles. A toggle in the panel
header switches back to the legacy 2D map.

> **The fun twist:** FreeLLMAPI is a *best-available router* — it often serves your request
> from a different provider than you asked for. The UI shows the model that **actually
> answered** each turn (the `X-Routed-Via` header), so you ask for Gemini/Qwen/DeepSeek and
> watch Cohere, Cerebras-GLM, gpt-oss-120b, or Gemma show up instead. That divergence is the
> show.

**Step 1 — Run a FreeLLMAPI proxy and enable a provider**

Run the proxy locally (default `http://localhost:3001`) and enable at least one provider on
its dashboard — see the [FreeLLMAPI install guide](https://tashfeenahmed.github.io/freellmapi/).
A zero-key anonymous provider (Pollinations / LLM7 / Kilo) is enough to smoke-test the pipe.

**Step 2 — Configure**

```bash
cp .env.example .env
# Edit .env:
#   FREELLMAPI_BASE_URL=http://localhost:3001/v1
#   FREELLMAPI_KEY=freellmapi-...        # the proxy's unified key (dashboard → Keys)
```

The default profiles (`config/profiles.yaml`) request three distinct models:
- `gemini-flash` → `gemini-3.5-flash`
- `qwen-next` → `qwen/qwen3-next-80b-a3b-instruct:free`
- `deepseek-pro` → `deepseek-ai/deepseek-v4-pro`

If your proxy exposes different IDs, edit `config/profiles.yaml` — the router will fail over
regardless. Confirm what your proxy serves with `curl -s $FREELLMAPI_BASE_URL/models -H "Authorization: Bearer $FREELLMAPI_KEY"`.

**Step 3 — Run**

```bash
./dev
```

**Step 4 — Watch**

Open **http://localhost:5173** and click **Start**. The 3D village comes alive:
- Each villager is tinted by its requested model and carries a floating card with its
  energy, credits, mood, and the **model that actually answered** its last turn.
- Speech appears as chat bubbles above villagers and streams in the live feed.
- Live-reassign any agent's model from its panel — it takes effect on the next turn.

Runs comfortably past 5 minutes with all 3 alive (they recharge to survive); expect emergent
gossip, alliances, the occasional theft, and passed rules.

---

## Run with zero tokens (mock profile)

No API key, no network — fully deterministic scripted responses.

```bash
# Leave FREELLMAPI_KEY blank in .env (or omit .env entirely)
./dev
# Open http://localhost:5173 → Start
```

To assign an agent to the mock profile, use the **Reassign Model** control in the agent panel, or edit `config/world.yaml` to set any agent's `profile: mock` before starting.

---

## Run with Ollama (local models)

```bash
# 1. Install Ollama: https://ollama.com
# 2. Pull a model
ollama pull llama3.2

# 3. Uncomment the ollama-llama profile in config/profiles.yaml
#    and set OLLAMA_BASE_URL in .env (default: http://localhost:11434/v1)

# 4. Start
./dev
```

For Docker-based Ollama:

```bash
docker compose --profile ollama up
# Then pull a model inside the container:
docker exec emergence-ollama ollama pull llama3.2
```

---

## Deploy to the cloud

The same images deploy anywhere. Swap `FREELLMAPI_BASE_URL` to a hosted gateway (Groq, OpenRouter, or your own FreeLLMAPI instance):

```bash
# Build and push
docker compose build
docker tag emergencemadness-backend registry.example.com/em-backend:latest
docker tag emergencemadness-web     registry.example.com/em-web:latest
docker push registry.example.com/em-backend:latest
docker push registry.example.com/em-web:latest

# On the host — set env vars and bring up:
FREELLMAPI_BASE_URL=https://api.freellmapi.com/v1 \
FREELLMAPI_KEY=your-key \
docker compose up -d
```

The web container (nginx) proxies `/api` and `/ws` to the backend, so no CORS configuration is needed. The frontend is served on **port 8080** in production.

Platforms: Railway, Fly.io, Render, any VPS with Docker. No persistent storage configuration required for the basic run; SQLite is written inside the backend container (add a named volume for durability).

---

## Docker services

```bash
# All mandatory services (backend + web)
docker compose up

# With local Ollama
docker compose --profile ollama up

# With self-hosted FreeLLMAPI gateway
docker compose --profile freellmapi up

# Build without starting
docker compose build

# Tear down
docker compose down
```

| Service | Port | Always on? | Notes |
|---------|------|-----------|-------|
| `backend` | 8000 | Yes | FastAPI + uvicorn |
| `web` | 8080 | Yes | nginx serving Vite build + proxy |
| `ollama` | 11434 | Opt-in (`--profile ollama`) | Local LLM server |
| `freellmapi` | 3001 | Opt-in (`--profile freellmapi`) | Self-hosted gateway |

---

## Project layout

```
EmergenceMadness/
├── backend/              # Python package `emergence` — engine, providers, API
│   ├── emergence/
│   │   ├── engine/       # tick loop, world state, scheduler
│   │   ├── agents/       # context assembly, action parsing
│   │   ├── providers/    # router + openai/anthropic/gemini/mock adapters
│   │   ├── persistence/  # SQLite repository
│   │   └── api/          # FastAPI routes + WebSocket broadcaster
│   └── pyproject.toml
├── web/                  # React + Vite + TypeScript + Tailwind frontend
├── config/
│   ├── profiles.yaml     # Model profiles (edit to add/swap models)
│   └── world.yaml        # World params + seed agents
├── docker/
│   ├── backend.Dockerfile
│   ├── web.Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── Makefile              # make dev | make up | make validate | make test
├── dev                   # ./dev — one-command local dev launcher
└── .env.example          # Copy to .env and fill in keys
```

---

## Configuration

All model routing is driven by `config/profiles.yaml` and `config/world.yaml`. No code changes are needed to add a model — add a profile entry, assign an agent to it.

The backend reads config from the directory named by `EM_CONFIG_DIR` (default: `./config`).

See `config/profiles.yaml` for the commented Ollama profile example and inline documentation.

---

## Make targets

```bash
make dev          # Start backend + frontend (same as ./dev)
make install      # pip install -e backend + cd web && npm install
make up           # docker compose up --build
make down         # docker compose down
make validate     # Validate docker-compose config, YAML, and dev script syntax
make test         # Run backend test suite (pytest)
```

---
title: Project layout
tags: [project-layout]
paths: [openai/anthropic/gemini/mock, pyproject.toml, ASSET_LICENSES.md, src/components/world3d, src/inspector, profiles.yaml, add/swap, personas.yaml, world.yaml, lanes.yaml, docker-compose.yml]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:347` by Andon (import docs/GUIDE.md:347 d48743ac02795d73); the original stays there.

```
petri-dish-of-madness/
├── backend/              # Python package `petridish` — engine, providers, API
│   ├── petridish/
│   │   ├── engine/       # tick loop, world state (agents, buildings, rules), scheduler
│   │   ├── agents/       # context assembly, action parsing + validation
│   │   ├── animals/      # W8 chaos-animal runtime (cat & dog)
│   │   ├── providers/    # router + openai/anthropic/gemini/mock adapters
│   │   ├── persistence/  # SQLite repository + append-only event log
│   │   └── api/          # FastAPI routes + WebSocket broadcaster
│   └── pyproject.toml
├── web/                  # React + Vite + TypeScript + Tailwind frontend
│   ├── public/
│   │   ├── models/       # vendored CC0 GLBs (KayKit · Kenney · Quaternius) — see ASSET_LICENSES.md
│   │   └── hdri/         # CC0 golden-hour environment map
│   ├── src/components/world3d/  # the cozy 3D town (R3F): assets/ GLB loader, toon shading, town layout
│   └── src/inspector/    # the /inspector annex (replay, traces, graphs, dashboards)
├── config/
│   ├── profiles.yaml     # Model profiles (edit to add/swap models)
│   ├── personas.yaml     # Persona library — character cards for the spawn form
│   ├── world.yaml        # World params + seed agents
│   └── lanes.yaml        # Adaptive lane routing — the bounce-loop preference order
│                         #   used when a pinned lane fails (see "Adaptive lane
│                         #   routing" below)
├── docker/
│   ├── backend.Dockerfile
│   ├── web.Dockerfile
│   └── nginx.conf
├── docker-compose.yml
├── Makefile              # make dev | make up | make validate | make test
├── dev                   # ./dev — one-command local dev launcher
└── .env.example          # Copy to .env and fill in keys
```

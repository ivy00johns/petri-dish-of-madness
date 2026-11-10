---
title: Install & run (one command)
tags: [install-run-one-command]
paths: [.venv/bin/activate, "**/inspector**"]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:18` by Andon (import docs/GUIDE.md:18 3437a276c9b1ccb1); the original stays there.

```bash
# 1. Clone and enter the repo
git clone https://github.com/ivy00johns/petri-dish-of-madness.git
cd petri-dish-of-madness

# 2. Copy the env template
cp .env.example .env

# 3. Install dependencies (backend into a local .venv + web deps)
make install
#    └─ equivalent to the manual steps:
#       python3.12 -m venv .venv && source .venv/bin/activate
#       pip install -e backend
#       cd web && npm install && cd ..

# 4. Start both backend + frontend
./dev
```

`./dev` auto-activates `.venv` if it exists, so you don't have to keep it activated yourself.

Open **[http://localhost:5173](http://localhost:5173)** — the cozy 3D village and live feed load right away (no keys needed to *open* the UI). To actually run the simulation you need either a model (the FreeLLMAPI live demo below) or the offline **mock profile** (see "Run with zero tokens"). The layout is chat-first: the **feed is the left column** (drag its right edge to resize), topped by a zero-LLM **story-so-far digest**; the world view takes the center with the **agent + critter roster as a card strip along its bottom edge**; controls and a collapsible model legend sit on the right. Use the header toggle to switch the center view between **THE VILLAGE** (3D) and the **WORLD MAP** (2D), and click the filter chips above the feed to show only the categories you care about. Visit **/inspector** for the analysis annex (replay, decision traces, governance history, social graph, model dashboards, run browser). The live lab wants a window at least **1024px wide** — below that you get a friendly gate rather than a crushed layout.

> **macOS / Homebrew note:** bare `pip install -e backend` often fails with either
> `requires a different Python: 3.10.x not in '>=3.11'` (a too-old Homebrew Python is
> first on your `PATH`) or `error: externally-managed-environment` (PEP 668). Both are
> solved by the local virtualenv above — that's exactly what `make install` creates. Pick
> the interpreter explicitly if `python3.12` isn't present: `make install PYTHON=python3.13`.

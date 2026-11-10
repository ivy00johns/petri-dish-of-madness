---
title: Make targets
tags: [make-targets]
paths: []
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:617` by Andon (import docs/GUIDE.md:617 abaa05e608574e59); the original stays there.

```bash
make dev          # Start backend + frontend (same as ./dev)
make install      # Create .venv (Python 3.11+) + pip install -e backend + npm install
make up           # docker compose up --build
make down         # docker compose down
make validate     # Validate docker-compose config, YAML, and dev script syntax
make test         # Run backend test suite (pytest)
```

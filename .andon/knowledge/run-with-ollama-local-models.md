---
title: Run with Ollama (local models)
tags: [run-with-ollama-local-models]
paths: [config/profiles.yaml]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:263` by Andon (import docs/GUIDE.md:263 b2d62c53e4555846); the original stays there.

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
docker compose exec ollama ollama pull llama3.2
```

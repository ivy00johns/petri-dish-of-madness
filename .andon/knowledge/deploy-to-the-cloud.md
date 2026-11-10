---
title: Deploy to the cloud
tags: [deploy-to-the-cloud]
paths: [data/run.sqlite]
updated: 2026-11-10
---

Imported from `docs/GUIDE.md:287` by Andon (import docs/GUIDE.md:287 d82309f2148f1c39); the original stays there.

The same images deploy anywhere. Swap `FREELLMAPI_BASE_URL` to a hosted gateway (Groq, OpenRouter, or your own FreeLLMAPI instance):

```bash
# Build and push
docker compose build
docker tag petri-dish-of-madness-backend registry.example.com/em-backend:latest
docker tag petri-dish-of-madness-web     registry.example.com/em-web:latest
docker push registry.example.com/em-backend:latest
docker push registry.example.com/em-web:latest

# On the host — set env vars and bring up:
FREELLMAPI_BASE_URL=https://api.freellmapi.com/v1 \
FREELLMAPI_KEY=your-key \
docker compose up -d
```

The web container (nginx) proxies `/api` and `/ws` to the backend, so no CORS configuration is needed. The frontend is served on **port 8080** in production.

Platforms: Railway, Fly.io, Render, any VPS with Docker. **Runs persist by default** to `data/run.sqlite` — inside the container that lands at `/app/data`, and the compose file ships a named volume (`backend_data`) mounted there, so run history (and the `/inspector` Run Browser's archive) survives container recreation out of the box. Prefer host-visible files? Swap it for a bind mount:

```yaml
# docker-compose override for the backend service
volumes:
  - ./data:/app/data        # instead of the default backend_data named volume
```

To wipe run history entirely, tear down with `docker compose down -v` (removes named volumes too).

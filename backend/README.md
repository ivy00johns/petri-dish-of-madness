# PetriDishOfMadness — Backend

Python 3.11+ backend for the PetriDishOfMadness multi-agent simulation.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Run the API server

```bash
uvicorn petridish.api.app:app --host 0.0.0.0 --port 8000
```

Health check: `curl -fsS localhost:8000/api/health`

## Run headless (offline, no network, no LLM)

```bash
python -m petridish.run --ticks 40 --profile mock
```

## Run tests

```bash
pytest -v
```

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `EM_CONFIG_DIR` | Directory containing `profiles.yaml` and `world.yaml` | `./config` or `../config` |
| `FREELLMAPI_KEY` | API key for FreeLLMAPI / OpenAI-compatible endpoints | *(none — profile reports unavailable)* |
| `FREELLMAPI_BASE_URL` | Base URL for FreeLLMAPI | `http://localhost:3001/v1` |
| `ANTHROPIC_API_KEY` | API key for Anthropic adapter | *(none)* |
| `GEMINI_API_KEY` | API key for Gemini adapter | *(none)* |

Secrets are referenced by name in `profiles.yaml` via `api_key_env: VAR_NAME`.
They are **never** stored in YAML files.

## Architecture

```
petridish/
  config/       # YAML loader, WorldParams, ModelProfile
  engine/       # World state, tick/turn loop, economy, governance, death
  agents/       # Context assembly, action parse/validate/retry, rolling memory
  providers/    # Router, adapters (OpenAI-compat, Anthropic, Gemini, Mock)
  persistence/  # SQLiteRepository (implements Repository interface)
  api/          # FastAPI app, REST routes, WebSocket /ws broadcaster
  run.py        # Headless runner entry point
```

## API overview

See `contracts/api.openapi.yaml` for the full spec.

| Endpoint | Description |
|---|---|
| `GET /api/health` | Liveness check |
| `GET /api/state` | Full world snapshot (same shape as WS `world_state`) |
| `GET /api/config` | Effective world parameters |
| `GET /api/profiles` | Model profiles with availability |
| `POST /api/control/start` | Start/resume the loop |
| `POST /api/control/pause` | Pause |
| `POST /api/control/step` | Advance one turn |
| `POST /api/control/speed` | Set tick interval |
| `POST /api/control/reset` | Reset world from config |
| `POST /api/agents/{id}/model` | **Reassign agent's model live** |
| `POST /api/agents` | Spawn agent |
| `DELETE /api/agents/{id}` | Kill agent |
| `POST /api/events/inject` | Inject random event (windfall/famine/blackout/festival) |
| `WS /ws` | WebSocket event stream |

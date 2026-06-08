"""
FastAPI application.
Exposes all /api routes per api.openapi.yaml + WS /ws per events.schema.json.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..config.loader import load_config, WorldConfig
from ..engine.world import World, AgentState, PlaceState
from ..engine.loop import TickLoop
from ..agents.runtime import AgentRuntime
from ..persistence.repository import SQLiteRepository
from ..providers.router import Router

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Load repo-root .env so the backend is self-sufficient regardless of launcher.
# Without this the process depends on the shell that started it having exported
# the vars — which silently breaks under `uvicorn --reload` (code hot-swaps but
# the stale environment persists) and when launched outside ./dev. .env is
# gitignored and absent in Docker/prod, where real env vars are used instead, so
# override=True simply makes the local .env authoritative when it exists.
# ──────────────────────────────────────────────────────────────────────────────
try:
    from pathlib import Path as _Path

    from dotenv import load_dotenv as _load_dotenv

    _env_path = _Path(__file__).resolve().parents[3] / ".env"
    if _env_path.is_file():
        _load_dotenv(_env_path, override=True)
        log.info("Loaded environment from %s", _env_path)
except ImportError:
    pass  # python-dotenv not installed; fall back to the shell environment

# ──────────────────────────────────────────────────────────────────────────────
# Application state (module-level singletons, initialized on startup)
# ──────────────────────────────────────────────────────────────────────────────

_world: World | None = None
_router: Router | None = None
_runtime: AgentRuntime | None = None
_repo: SQLiteRepository | None = None
_loop: TickLoop | None = None
_config: WorldConfig | None = None

# WebSocket connection manager
_connections: set[WebSocket] = set()


def _broadcast(msg: dict) -> None:
    """Non-async broadcaster; schedules message to all connected WS clients."""
    dead = set()
    for ws in list(_connections):
        try:
            # Fire-and-forget: schedule coroutine
            asyncio.ensure_future(ws.send_text(json.dumps(msg)))
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


# ──────────────────────────────────────────────────────────────────────────────
# Startup / shutdown
# ──────────────────────────────────────────────────────────────────────────────

def _build_world(cfg: WorldConfig) -> tuple[World, Router, AgentRuntime, SQLiteRepository]:
    from ..engine.world import AgentState, PlaceState

    places = [
        PlaceState(id=p.id, name=p.name, x=p.x, y=p.y,
                   kind=p.kind, description=p.description)
        for p in cfg.places
    ]
    agents = [
        AgentState(
            id=f"agent_{a.name.lower()}_{str(uuid.uuid4())[:6]}",
            name=a.name,
            personality=a.personality,
            profile=a.profile,
            location=a.location,
            energy=cfg.world.starting_energy,
            credits=cfg.world.starting_credits,
        )
        for a in cfg.agents
    ]

    world = World(params=cfg.world, places=places, agents=agents)
    router = Router(cfg.profiles)

    # Register each agent's profile with the router
    for agent in agents:
        router.reassign(agent.id, agent.profile)

    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    return world, router, runtime, repo


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _world, _router, _runtime, _repo, _loop, _config

    _config = load_config()
    _world, _router, _runtime, _repo = _build_world(_config)
    _loop = TickLoop(
        world=_world,
        runtime=_runtime,
        repo=_repo,
        router=_router,
        broadcaster=_broadcast,
    )
    _loop.init_run(_config)
    # Inject world reference into mock providers for dynamic voting
    _router.inject_world(_world)

    log.info("EmergenceMadness backend started (tick_interval=%.2fs)",
             _config.world.tick_interval_seconds)
    yield

    if _loop:
        _loop.pause()
    if _repo:
        _repo.close()


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="EmergenceMadness API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────────────────────
# WebSocket
# ──────────────────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connections.add(websocket)
    try:
        # Send initial world_state snapshot
        if _loop:
            snapshot = _loop.current_snapshot()
            await websocket.send_text(json.dumps(snapshot))

        # Keep alive; just wait for disconnect
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except asyncio.TimeoutError:
                # Send ping-like idle
                await websocket.send_text(json.dumps({"type": "ping"}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("WS error: %s", exc)
    finally:
        _connections.discard(websocket)


# ──────────────────────────────────────────────────────────────────────────────
# REST endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    tick = _world.tick if _world else 0
    running = _world.running if _world else False
    return {"status": "ok", "tick": tick, "running": running}


@app.get("/api/state")
async def get_state():
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    return _loop.current_snapshot()


@app.get("/api/config")
async def get_config():
    if _config is None:
        raise HTTPException(503, "Not initialized")
    params = _config.world
    return {k: getattr(params, k) for k in vars(params) if not k.startswith("_")}


@app.get("/api/profiles")
async def get_profiles():
    if _router is None:
        raise HTTPException(503, "Not initialized")
    legend = _router.legend()
    # Augment with health check
    result = []
    for p in legend:
        result.append({
            "name": p["name"],
            "adapter": p["adapter"],
            "model_id": p["model_id"],
            "color": p["color"],
            "available": p["available"],
        })
    return result


# Control endpoints

@app.post("/api/control/start")
async def control_start():
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    _loop.start()
    return {"status": "ok", "running": True}


@app.post("/api/control/pause")
async def control_pause():
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    _loop.pause()
    return {"status": "ok", "running": False}


@app.post("/api/control/step")
async def control_step():
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    _loop.step()
    # Give the loop a moment to process the step
    await asyncio.sleep(0.1)
    return {"status": "ok"}


class SpeedBody(BaseModel):
    tick_interval_seconds: float


@app.post("/api/control/speed")
async def control_speed(body: SpeedBody):
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    if not (0.1 <= body.tick_interval_seconds <= 60):
        raise HTTPException(400, "tick_interval_seconds must be 0.1–60")
    _loop.set_speed(body.tick_interval_seconds)
    return {"status": "ok", "tick_interval_seconds": body.tick_interval_seconds}


@app.post("/api/control/reset")
async def control_reset():
    if _loop is None or _config is None:
        raise HTTPException(503, "Not initialized")
    await _loop.reset(_config)
    return {"status": "ok"}


# Agent model reassignment

class ReassignBody(BaseModel):
    profile: str


@app.post("/api/agents/{agent_id}/model")
async def reassign_model(agent_id: str, body: ReassignBody):
    if _world is None or _router is None:
        raise HTTPException(503, "Not initialized")
    if agent_id not in _world.agents:
        raise HTTPException(404, f"Unknown agent: {agent_id}")
    if _router.get_profile(body.profile) is None:
        raise HTTPException(400, f"Unknown profile: {body.profile}")
    _router.reassign(agent_id, body.profile)
    agent = _world.agents[agent_id]
    agent.profile = body.profile
    # Emit reassignment event
    if _loop:
        _loop._emit_event({
            "kind": "model_reassigned",
            "actor_id": agent_id,
            "profile": body.profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name}'s model reassigned to {body.profile}.",
            "payload": {"new_profile": body.profile},
        })
        _loop._broadcast_world_state()
    return {"status": "ok", "agent_id": agent_id, "profile": body.profile}


# Spawn / kill agents

class SpawnBody(BaseModel):
    name: str
    profile: str
    personality: str = "A generic agent."
    location: str = "plaza"


@app.post("/api/agents", status_code=201)
async def spawn_agent(body: SpawnBody):
    if _world is None or _router is None:
        raise HTTPException(503, "Not initialized")
    if _router.get_profile(body.profile) is None:
        raise HTTPException(400, f"Unknown profile: {body.profile}")
    agent = _world.spawn_agent(
        name=body.name,
        personality=body.personality,
        profile=body.profile,
        location=body.location,
    )
    _router.reassign(agent.id, body.profile)
    if _loop and _repo:
        run_id = _loop._run_id or 1
        _repo.save_agent(run_id, agent, _world.tick)
        _loop._emit_event({
            "kind": "agent_spawned",
            "actor_id": agent.id,
            "profile": body.profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name} spawned.",
            "payload": {"agent_id": agent.id, "name": agent.name},
        })
        _loop._broadcast_world_state()
    return {"status": "ok", "agent_id": agent.id}


@app.delete("/api/agents/{agent_id}")
async def kill_agent(agent_id: str):
    if _world is None:
        raise HTTPException(503, "Not initialized")
    if agent_id not in _world.agents:
        raise HTTPException(404, f"Unknown agent: {agent_id}")
    agent = _world.agents[agent_id]
    _world.kill_agent(agent_id)
    if _loop:
        _loop._emit_event({
            "kind": "agent_died",
            "actor_id": agent_id,
            "profile": agent.profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name} was removed.",
            "payload": {"reason": "killed_via_api"},
        })
        _loop._broadcast_world_state()
    return {"status": "ok"}


# Random event injection

class InjectBody(BaseModel):
    kind: str | None = None


@app.post("/api/events/inject")
async def inject_event(body: InjectBody = InjectBody()):
    if _loop is None:
        raise HTTPException(503, "Not initialized")
    try:
        result = _loop.inject_random_event(body.kind)
        return {"status": "ok", **result}
    except ValueError as exc:
        raise HTTPException(400, str(exc))

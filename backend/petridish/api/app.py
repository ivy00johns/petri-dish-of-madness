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

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

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


def _on_ws_send_done(task: asyncio.Task, ws: WebSocket) -> None:
    """Done-callback for scheduled WS sends (audit B10): consume the task's
    exception (no 'Task exception was never retrieved' noise) and discard the
    failed socket so _connections never accumulates stale entries."""
    if task.cancelled():
        _connections.discard(ws)
        return
    exc = task.exception()  # consumes the exception
    if exc is not None:
        _connections.discard(ws)
        log.debug("WS send failed; dropping socket: %s", exc)


def _broadcast(msg: dict) -> None:
    """Non-async broadcaster; schedules message to all connected WS clients.

    Each send is scheduled with a done-callback that consumes failures and
    evicts the dead socket from _connections (audit B10) — no unbounded
    stale-socket growth, no unhandled-exception noise."""
    data = json.dumps(msg)
    for ws in list(_connections):
        try:
            task = asyncio.ensure_future(ws.send_text(data))
        except Exception:
            # Scheduling itself failed (e.g. no running loop for this socket).
            _connections.discard(ws)
            continue
        task.add_done_callback(lambda t, ws=ws: _on_ws_send_done(t, ws))


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

    # Thread the configured DB path so a real run can persist for replay; default
    # ':memory:' keeps tests and ad-hoc launches ephemeral (EM-054 §6).
    repo = SQLiteRepository(getattr(cfg.world, "db_path", ":memory:") or ":memory:")
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

    log.info("PetriDishOfMadness backend started (tick_interval=%.2fs)",
             _config.world.tick_interval_seconds)
    yield

    if _loop:
        _loop.pause()
    if _repo:
        _repo.close()


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI app
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="PetriDishOfMadness API", version="1.0.0", lifespan=lifespan)

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
    # Await the turn's completion so the response reflects the advanced tick
    # (deterministic stepping — no fire-and-forget race).
    tick = await _loop.step_and_wait()
    return {"status": "ok", "tick": tick}


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
    # Audit B15: length caps — these strings flow into system prompts (token
    # bloat / prompt-injection surface). Over-limit bodies get FastAPI's 422.
    name: str = Field(max_length=40)
    profile: str
    personality: str = Field(default="A generic agent.", max_length=280)
    location: str = Field(default="plaza", max_length=40)
    # W7 / EM-063 — spawn mode. god = immediate (default, as today); governance =
    # enqueue an admit_agent proposed rule carrying the agent spec; the agent is
    # admitted only if the vote passes threshold.
    mode: str | None = None


def _spawn_mode(body: SpawnBody) -> str:
    """Effective spawn mode: explicit body.mode wins; else config spawn.mode; else god."""
    if body.mode:
        return body.mode
    spawn_cfg = getattr(_config.world, "spawn", None) if _config else None
    mode = getattr(spawn_cfg, "mode", None) if spawn_cfg is not None else None
    return mode or "god"


@app.post("/api/agents")
async def spawn_agent(body: SpawnBody, response: Response):
    if _world is None or _router is None:
        raise HTTPException(503, "Not initialized")
    if _router.get_profile(body.profile) is None:
        raise HTTPException(400, f"Unknown profile: {body.profile}")

    mode = _spawn_mode(body)

    if mode == "governance":
        # Enqueue an admit_agent proposal carrying the agent spec; the agent enters
        # only if the vote passes threshold. world-core owns the proposal store and
        # admits the agent when the vote resolves (_on_rule_activated). This is a
        # SYSTEM-initiated proposal (no human actor), so proposer_id is "system".
        rule = _world.enqueue_admit_agent(
            proposer_id="system",
            name=body.name,
            personality=body.personality,
            profile=body.profile,
            location=body.location,
        )
        proposal_id = rule.id
        spec = {
            "name": body.name,
            "profile": body.profile,
            "personality": body.personality,
            "location": body.location,
        }
        if _loop:
            _loop._emit_event({
                "kind": "agent_spawned",
                "actor_id": None,
                "actor_type": "system",
                "profile": body.profile,
                "profile_color": _loop._get_profile_color_for_profile(body.profile),
                "text": f"Admission of {body.name} proposed (governance vote pending).",
                "payload": {"method": "governance", "proposal_id": proposal_id, "spec": spec},
            })
            _loop._broadcast_world_state()
        response.status_code = 202
        return {"status": "pending", "mode": "governance", "proposal_id": proposal_id}

    # god (default): immediate spawn as today.
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
            "actor_type": "god",
            "profile": body.profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name} spawned.",
            "payload": {"agent_id": agent.id, "name": agent.name, "method": "god"},
        })
        _loop._broadcast_world_state()
    response.status_code = 201
    return {"status": "ok", "agent_id": agent.id, "mode": "god"}


@app.get("/api/buildings")
async def get_buildings():
    """List buildings/structures with state (W7 EM-061). Also present in
    world_state.buildings. Empty-200 when there is no active run / no buildings —
    never 500 (matches the W6 read-endpoint style)."""
    if _world is None:
        return []
    store = getattr(_world, "buildings", None)
    if not isinstance(store, dict):
        # Fall back to the snapshot's buildings key if world-core surfaces it there.
        if _loop is not None:
            snap = _loop.current_snapshot()
            return snap.get("buildings", []) if isinstance(snap, dict) else []
        return []
    out = []
    for b in store.values():
        to_dict = getattr(b, "to_dict", None)
        if callable(to_dict):
            out.append(to_dict())
        elif isinstance(b, dict):
            out.append(b)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# W8 / EM-064 — animals (chaos layer). GET lists the cat + dog (also present in
# world_state.animals); POST spawns one ad-hoc (god-mode), W6 spawn-style.
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/api/animals")
async def get_animals():
    """List animals with state (W8 EM-064). Also present in world_state.animals.
    Empty-200 when there is no active run / no animals — never 500 (matches the
    W6/W7 read-endpoint style)."""
    if _world is None:
        return []
    store = getattr(_world, "animals", None)
    if not isinstance(store, dict):
        return []
    out = []
    for a in store.values():
        to_dict = getattr(a, "to_dict", None)
        if callable(to_dict):
            out.append(to_dict())
        elif isinstance(a, dict):
            out.append(a)
    return out


class SpawnAnimalBody(BaseModel):
    # Audit B15: same caps as SpawnBody (species is enum-checked in the handler).
    species: str            # cat | dog
    name: str = Field(max_length=40)
    location: str = Field(default="plaza", max_length=40)
    personality: str = Field(default="", max_length=280)


@app.post("/api/animals")
async def spawn_animal_endpoint(body: SpawnAnimalBody, response: Response):
    """Spawn an animal immediately (god-mode), emitting animal_spawned. Animals
    have no credits (invariant 7) and are NOT in the agent round-robin — they act
    on the slow animal cadence."""
    if _world is None:
        raise HTTPException(503, "Not initialized")
    if body.species not in ("cat", "dog"):
        raise HTTPException(400, f"Unknown species: {body.species!r} (cat|dog)")
    animal = _world.spawn_animal(
        species=body.species,
        name=body.name,
        location=body.location,
        personality=body.personality,
    )
    if _loop:
        _loop._emit_event({
            "kind": "animal_spawned",
            "actor_id": animal.id,
            "actor_type": "animal",
            "text": f"{animal.name} the {animal.species} appears.",
            "payload": {
                "animal_id": animal.id,
                "species": animal.species,
                "name": animal.name,
                "location": animal.location,
                "method": "god",
            },
        })
        _loop._broadcast_world_state()
    response.status_code = 201
    return {"status": "ok", "animal_id": animal.id}


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
        # W9 / EM-071 — god-killing the last living human agent is extinction
        # too: emit world_extinct (+ auto-pause per config). Idempotent.
        _loop.handle_extinction(agent)
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


# ──────────────────────────────────────────────────────────────────────────────
# W6 read-only event-log endpoints (api.openapi.yaml v1.1.0 / event-log.md §7).
# These surface the repository §7 query methods over the active run
# (_loop._run_id). With no active run/repo they return empty arrays / empty
# payloads with 200 — never 500 — so the /inspector annex degrades gracefully.
# ──────────────────────────────────────────────────────────────────────────────

def _active_run_id() -> int | None:
    """The run_id of the active run, or None when nothing is initialized yet."""
    if _loop is None:
        return None
    return _loop._run_id


@app.get("/api/events")
async def get_events(
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
    kinds: str | None = Query(default=None, description="comma-separated kinds"),
    actor_id: str | None = Query(default=None),
    turn_id: str | None = Query(default=None),
    after_seq: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    order: str = Query(default="asc"),
):
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return []
    kind_list = [k for k in kinds.split(",") if k] if kinds else None
    return _repo.get_events(
        run_id,
        from_tick=from_tick,
        to_tick=to_tick,
        kinds=kind_list,
        actor_id=actor_id,
        turn_id=turn_id,
        after_seq=after_seq,
        limit=limit,
        order=order,
    )


@app.get("/api/turns/{turn_id}")
async def get_turn_trace(turn_id: str):
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return []
    return _repo.get_turn_trace(run_id, turn_id)


@app.get("/api/rules/history")
async def get_rule_history():
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return []
    return _repo.get_rule_history(run_id)


@app.get("/api/relationships")
async def get_relationships(
    agent_id: str | None = Query(default=None),
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
):
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return []
    return _repo.get_relationship_timeline(
        run_id, agent_id=agent_id, from_tick=from_tick, to_tick=to_tick
    )


@app.get("/api/snapshots")
async def get_snapshots():
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return []
    return _repo.get_snapshots(run_id)


@app.get("/api/replay")
async def get_replay(tick: int = Query(...)):
    """Replay materials for tick T (api.openapi.yaml v1.2.0, audit B7).

    `events` contains ONLY the fold-forward delta: rows with
    base.tick < e.tick <= T (strict on the left — the snapshot at base.tick
    already includes all tick-base.tick events, per event-log.md v1.1.0 §3).
    If no snapshot exists, base is null and events cover 0 <= e.tick <= T.
    Clients fold `events` onto `base.state` without further filtering.
    """
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return {"base": None, "events": []}
    base = _repo.nearest_snapshot(run_id, tick)
    from_tick = (base["tick"] + 1) if base is not None else 0
    events = _repo.get_events(run_id, from_tick=from_tick, to_tick=tick, order="asc")
    return {"base": base, "events": events}


@app.get("/api/analytics")
async def get_analytics(
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
):
    run_id = _active_run_id()
    if _repo is None or run_id is None:
        return {}
    return _repo.get_analytics(run_id, from_tick=from_tick, to_tick=to_tick)

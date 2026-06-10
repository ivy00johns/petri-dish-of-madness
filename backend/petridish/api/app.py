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

from ..config.loader import load_config, load_personas, WorldConfig
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


def _emit_usage_alert(alert: dict) -> None:
    """Sink for Router usage-cap alerts (W11b EM-083, event-log.md v1.3.0 note 1).

    Persists + broadcasts ONE `usage_alert {provider, metric, pct, limit}` row
    per provider/metric/day-window (the once-per-window de-dupe lives in
    providers/usage.py). Defensive: alerting must never break a turn."""
    if _loop is None:
        return
    try:
        _loop._emit_event({
            "kind": "usage_alert",
            "actor_type": "system",
            "actor_id": None,
            "profile": alert.get("provider"),
            "text": (
                f"{alert.get('provider')} usage crossed {alert.get('pct')}% of "
                f"its {alert.get('metric')} day cap ({alert.get('limit')})."
            ),
            "payload": {
                "provider": alert.get("provider"),
                "metric": alert.get("metric"),
                "pct": alert.get("pct"),
                "limit": alert.get("limit"),
            },
        })
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("usage_alert emission failed: %s", exc)


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
    # W11b / EM-083 (platform half) — route usage_alert payloads from the
    # Router's day-cap tracker into the event log. The sink reads the CURRENT
    # _loop global, so alerts keep landing in the right run after reset/fork.
    _router.set_usage_alert_sink(_emit_usage_alert)

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
    # W11b / EM-092: name/profile/personality are now OPTIONAL at the schema
    # level so a `persona` card can prefill them; the handler still requires an
    # effective name + profile (400 when neither the body nor a persona supplies
    # them), so plain spawns behave exactly as before.
    name: str | None = Field(default=None, max_length=40)
    profile: str | None = None
    personality: str | None = Field(default=None, max_length=280)
    location: str = Field(default="plaza", max_length=40)
    # W7 / EM-063 — spawn mode. god = immediate (default, as today); governance =
    # enqueue an admit_agent proposed rule carrying the agent spec; the agent is
    # admitted only if the vote passes threshold.
    mode: str | None = None
    # W11b / EM-092 — optional persona card name (config/personas.yaml): the
    # server prefills name/personality/profile (suggested_profile) from the
    # card; explicit body fields override. Unknown persona -> 400.
    persona: str | None = Field(default=None, max_length=40)


def _resolve_spawn_fields(body: SpawnBody) -> tuple[str, str, str]:
    """Effective (name, personality, profile) for a spawn (W11b EM-092).

    Explicit body fields always win; a `persona` card fills the gaps; what is
    still missing after that is a 400 (unknown persona is a 400 too). The
    pre-W11b default personality ('A generic agent.') is preserved when neither
    the body nor a card supplies one."""
    name, personality, profile = body.name, body.personality, body.profile
    if body.persona:
        wanted = body.persona.strip().lower()
        card = next(
            (c for c in load_personas() if c["name"].strip().lower() == wanted),
            None,
        )
        if card is None:
            raise HTTPException(400, f"Unknown persona: {body.persona!r}")
        name = name or card["name"]
        personality = personality or card["personality"]
        profile = profile or card["suggested_profile"] or None
    if not name:
        raise HTTPException(400, "name is required (directly or via persona)")
    if not profile:
        raise HTTPException(400, "profile is required (directly or via persona)")
    return name, (personality or "A generic agent."), profile


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
    # W11b / EM-092 — persona prefill: explicit fields win, the card fills gaps,
    # unknown persona / still-missing name|profile -> 400.
    name, personality, profile = _resolve_spawn_fields(body)
    if _router.get_profile(profile) is None:
        raise HTTPException(400, f"Unknown profile: {profile}")

    mode = _spawn_mode(body)

    if mode == "governance":
        # Enqueue an admit_agent proposal carrying the agent spec; the agent enters
        # only if the vote passes threshold. world-core owns the proposal store and
        # admits the agent when the vote resolves (_on_rule_activated). This is a
        # SYSTEM-initiated proposal (no human actor), so proposer_id is "system".
        rule = _world.enqueue_admit_agent(
            proposer_id="system",
            name=name,
            personality=personality,
            profile=profile,
            location=body.location,
        )
        proposal_id = rule.id
        spec = {
            "name": name,
            "profile": profile,
            "personality": personality,
            "location": body.location,
        }
        if _loop:
            _loop._emit_event({
                "kind": "agent_spawned",
                "actor_id": None,
                "actor_type": "system",
                "profile": profile,
                "profile_color": _loop._get_profile_color_for_profile(profile),
                "text": f"Admission of {name} proposed (governance vote pending).",
                "payload": {"method": "governance", "proposal_id": proposal_id, "spec": spec},
            })
            _loop._broadcast_world_state()
        response.status_code = 202
        return {"status": "pending", "mode": "governance", "proposal_id": proposal_id}

    # god (default): immediate spawn as today.
    agent = _world.spawn_agent(
        name=name,
        personality=personality,
        profile=profile,
        location=body.location,
    )
    _router.reassign(agent.id, profile)
    if _loop and _repo:
        run_id = _loop._run_id or 1
        _repo.save_agent(run_id, agent, _world.tick)
        _loop._emit_event({
            "kind": "agent_spawned",
            "actor_id": agent.id,
            "actor_type": "god",
            "profile": profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name} spawned.",
            "payload": {"agent_id": agent.id, "name": agent.name, "method": "god"},
        })
        _loop._broadcast_world_state()
    response.status_code = 201
    return {"status": "ok", "agent_id": agent.id, "mode": "god"}


@app.get("/api/personas")
async def get_personas():
    """Persona library — config-defined character cards (W11b EM-092,
    api.openapi.yaml 1.4.0). Empty array when config/personas.yaml is missing
    or malformed — never 500 (load_personas is fail-soft by contract)."""
    return load_personas()


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
# W11b — god billboard reply (powers the UI's "REPLY ON BILLBOARD").
# ──────────────────────────────────────────────────────────────────────────────

class BillboardBody(BaseModel):
    # min_length/max_length make FastAPI 422 empty/oversized text before the
    # handler runs (the contract's 422 path); whitespace-only is checked below.
    text: str = Field(min_length=1, max_length=280)
    in_reply_to: str | None = Field(default=None, max_length=120)


@app.post("/api/billboard", status_code=201)
async def post_billboard(body: BillboardBody):
    """God posts/replies on the town billboard (W11b EM-091 god surface).

    Calls the engine seam `world.post_billboard_as_god(text, in_reply_to)`
    (backend-engine implements it alongside world.billboard; 503 with a clear
    message until it lands) and emits `billboard_posted` with actor_type 'god'
    (event-log.md v1.3.0 note 1). 503 world not initialized; 422 empty/too-long."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text must be non-empty")
    post_fn = getattr(_world, "post_billboard_as_god", None)
    if post_fn is None:
        # Cross-boundary seam (coordination/W11B_BUILD.md): engine half pending.
        raise HTTPException(
            503, "engine billboard support (world.post_billboard_as_god) not available yet"
        )
    entry = post_fn(text, body.in_reply_to)
    if isinstance(entry, dict) and entry.get("kind") == "billboard_posted":
        # The engine returns the ready event dict (its docstring delegates the
        # emission to this layer); emit it through the normal pipeline.
        evt = dict(entry)
        evt.setdefault("actor_type", "god")
        _loop._emit_event(evt)
    else:
        # Defensive fallback if the seam's return shape shifts.
        payload: dict = {"place": "plaza", "text": text}
        if body.in_reply_to:
            payload["in_reply_to"] = body.in_reply_to
        _loop._emit_event({
            "kind": "billboard_posted",
            "actor_id": "god",
            "actor_type": "god",
            "text": f"God posts on the billboard: “{text}”",
            "payload": payload,
        })
    _loop._broadcast_world_state()
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# PROTOTYPE — god proclamation (the LOUD tier of the god↔town channel).
# POST /api/billboard pins an opt-in note; POST /api/proclaim is heard by all:
# the active proclamation is injected into every agent's next prompt.
# ──────────────────────────────────────────────────────────────────────────────

class ProclaimBody(BaseModel):
    text: str = Field(min_length=1, max_length=280)


@app.post("/api/proclaim", status_code=201)
async def post_proclamation(body: ProclaimBody):
    """God issues a LOUD proclamation heard by the whole world. Unlike a billboard
    note (opt-in, read at the plaza), the active proclamation rides every agent's
    next prompt — so the god's word is guaranteed to reach them (this is the fix
    for 'I asked them to name the town and nobody heard'). Calls the engine seam
    `world.post_proclamation_as_god(text)` and emits `proclamation_posted`
    (actor_type 'god'). 503 not initialized; 422 empty/too-long."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text must be non-empty")
    post_fn = getattr(_world, "post_proclamation_as_god", None)
    if post_fn is None:
        raise HTTPException(
            503, "engine proclamation support (world.post_proclamation_as_god) not available yet"
        )
    evt = post_fn(text)
    if isinstance(evt, dict) and evt.get("kind") == "proclamation_posted":
        e = dict(evt)
        e.setdefault("actor_type", "god")
        _loop._emit_event(e)
    _loop._broadcast_world_state()
    return {"status": "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# Wave A.2 — god console: targeted interventions (EM-136) + one-shot whispers
# (EM-137). The world-wide levers above (inject/billboard/proclaim) can't save
# ONE starving agent; these target a single soul. Free-scale law: pure state
# mutation + event / context injection — zero LLM calls.
# ──────────────────────────────────────────────────────────────────────────────

class InterveneBody(BaseModel):
    kind: str
    agent_id: str
    # ge/le make FastAPI 422 an out-of-range amount before the handler runs;
    # None falls through to the engine seam's per-kind default (25 / 10).
    amount: int | None = Field(default=None, ge=1, le=100)


@app.post("/api/god/intervene")
async def god_intervene(body: InterveneBody):
    """God targets ONE agent with a deterministic intervention (EM-136):
    `bless_energy` (clamped at 100) or `grant_credits`. Calls the engine seam
    `world.god_intervene(kind, agent_id, amount)` and emits `god_intervention`
    (actor_type 'god', target_id the agent; payload carries before/after).
    503 not initialized; 422 unknown kind, unknown/dead agent, or amount
    outside 1..100 (the seam's ValueError)."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    intervene_fn = getattr(_world, "god_intervene", None)
    if intervene_fn is None:
        raise HTTPException(
            503, "engine intervention support (world.god_intervene) not available yet"
        )
    try:
        evt = intervene_fn(body.kind, body.agent_id, body.amount)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if isinstance(evt, dict) and evt.get("kind") == "god_intervention":
        e = dict(evt)
        e.setdefault("actor_type", "god")
        _loop._emit_event(e)
    _loop._broadcast_world_state()
    return {"status": "ok"}


class GodWhisperBody(BaseModel):
    agent_id: str
    text: str = Field(min_length=1, max_length=280)


@app.post("/api/god/whisper")
async def god_whisper(body: GodWhisperBody):
    """God whispers to ONE agent (EM-137): the line rides only that agent's
    NEXT prompt, exactly once (queued on `world.pending_whispers`, consumed in
    runtime._assemble_context). Calls the engine seam
    `world.post_whisper_as_god(agent_id, text)` and emits `whisper_posted`
    (actor_type 'god', target_id the agent) — a spectator app, so the content
    rides the payload/feed; the whisper is private to the AGENTS, not the
    watchers. 503 not initialized; 422 empty/too-long text or unknown/dead
    agent."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "text must be non-empty")
    whisper_fn = getattr(_world, "post_whisper_as_god", None)
    if whisper_fn is None:
        raise HTTPException(
            503, "engine whisper support (world.post_whisper_as_god) not available yet"
        )
    try:
        evt = whisper_fn(body.agent_id, text)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    if isinstance(evt, dict) and evt.get("kind") == "whisper_posted":
        e = dict(evt)
        e.setdefault("actor_type", "god")
        _loop._emit_event(e)
    _loop._broadcast_world_state()
    return {"status": "ok"}


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


def _resolve_run_id(run_id: int | None) -> int | None:
    """Effective run scope for a read endpoint (W11a EM-086, api v1.3.0).

    Omitted (None) → the active run, byte-identical to pre-W11a behavior.
    Provided → validated against the runs table (SELECT 1 FROM runs WHERE id=?);
    an unknown id raises 404 {"detail": "unknown run"}. NEVER inferred from the
    `status` column — liveness is the loop's _run_id, nothing else."""
    if run_id is None:
        return _active_run_id()
    if _repo is None or not _repo.run_exists(run_id):
        raise HTTPException(404, "unknown run")
    return run_id


@app.get("/api/runs")
async def list_runs():
    """List all persisted runs, newest first (W11a EM-086 — the run browser).
    `is_active` is true ONLY for the run the live loop holds; `status` is
    reported as stored but is unreliable for liveness (crashes/hot-reloads
    leave dead runs 'running'). Empty-200 when no repo — never 500."""
    if _repo is None:
        return []
    return _repo.list_runs(active_run_id=_active_run_id())


# ──────────────────────────────────────────────────────────────────────────────
# W11b / EM-101 — fork a past run at tick T into a NEW run (api.openapi 1.4.0).
# ──────────────────────────────────────────────────────────────────────────────

class ForkBody(BaseModel):
    run_id: int
    tick: int
    # Typed as Any so malformed overrides get the contract's 400 (validated in
    # the handler), not pydantic's 422.
    place_overrides: Any = None


async def _retire_loop(loop: TickLoop) -> None:
    """Tear down a TickLoop we are about to replace: pause it and cancel+await
    its background tasks (the same teardown TickLoop.reset performs on itself)
    so nothing mutates the old world or emits into the old run after the swap."""
    loop.pause()
    for attr in ("_task", "_animal_task", "_narrator_task"):
        task = getattr(loop, attr, None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("%s raised during fork teardown: %s", attr, exc)
        setattr(loop, attr, None)
    # Release any step_and_wait() callers blocked on the old loop.
    waiters = getattr(loop, "_step_waiters", [])
    while waiters:
        fut = waiters.pop(0)
        if not fut.done():
            fut.set_result(loop._world.tick)


@app.post("/api/runs/fork", status_code=201)
async def fork_run(body: ForkBody):
    """Fork a past run at tick T into a NEW run (W11b EM-101).

    FORK SEMANTICS (honest approximation, documented in the response): the fork
    restores the NEAREST SNAPSHOT <= T via `World.from_snapshot` — the
    fold-forward delta (snapshot..T events) is NOT applied server-side (the
    projection fold lives client-side in the replay consumers; duplicating it
    here would be a second, drift-prone implementation). When the snapshot tick
    differs from the requested tick, the response carries the ACTUAL tick in
    `forked_at_tick` plus a `note` saying so. Lineage (`forked_from` +
    `forked_at_tick`) is stamped on the new runs row; the forked run starts
    PAUSED (the user presses play) and its first event is
    `run_forked {parent_run_id, tick}` (open kind registry, event-log.md §4).
    """
    global _world, _runtime, _loop

    if _loop is None or _repo is None or _router is None:
        raise HTTPException(503, "Not initialized")

    # ── Validation: 404 unknown run; 400 tick out of range / bad overrides ──
    parent = _repo.get_run(body.run_id)
    if parent is None:
        raise HTTPException(404, "unknown run")
    max_tick = _repo.run_max_tick(body.run_id)
    if body.tick < 0 or body.tick > max_tick:
        raise HTTPException(400, f"tick out of range (0..{max_tick})")
    overrides = body.place_overrides
    if overrides is not None:
        if not isinstance(overrides, list) or not all(isinstance(p, dict) for p in overrides):
            raise HTTPException(400, "place_overrides must be a list of place objects")

    # ── Replay materials: nearest snapshot <= T (same source as /api/replay) ──
    base = _repo.nearest_snapshot(body.run_id, body.tick)
    if base is None:
        raise HTTPException(
            400, "run has no snapshot at or before that tick — cannot fork"
        )
    actual_tick = int(base["tick"])

    # Parent config (parsed early: the child run row carries it, and the world
    # params inside it make the fork faithful to the parent's physics).
    try:
        child_cfg = json.loads(parent.get("config_json") or "{}")
    except (TypeError, ValueError):
        child_cfg = {}
    if not isinstance(child_cfg, dict):
        child_cfg = {}

    # ── Engine seam (coordination/W11B_BUILD.md): World.from_snapshot ──
    if getattr(World, "from_snapshot", None) is None:
        raise HTTPException(
            503, "engine fork support (World.from_snapshot) not available yet"
        )
    kwargs: dict = {"place_overrides": overrides}
    # ADDITIVE to the contracted seam: when the engine accepts `params`, carry
    # the parent run's world params into the fork (else it defaults to fresh
    # WorldParams). Signature-sniffed so the contracted 2-arg form keeps working.
    try:
        import inspect
        if "params" in inspect.signature(World.from_snapshot).parameters and \
                isinstance(child_cfg.get("world"), dict):
            from ..config.loader import _parse_world
            parent_params, _, _ = _parse_world({"world": child_cfg["world"]})
            kwargs["params"] = parent_params
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not derive parent world params for fork: %s", exc)
        kwargs.pop("params", None)
    try:
        new_world = World.from_snapshot(base["state"], **kwargs)
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(400, f"invalid fork state/overrides: {exc}")

    # ── Swap: fork is "reset to a computed state". Retire the old loop, keep
    # the SAME repo (one DB = one runs table) and the SAME router (profiles +
    # usage-alert tracker survive); rebuild runtime + loop around the new world.
    old_loop = _loop
    await _retire_loop(old_loop)

    for agent in new_world.agents.values():
        try:
            _router.reassign(agent.id, agent.profile)
        except ValueError:
            # Profile vanished from the registry since the parent run: degrade
            # to mock (always present) rather than failing the fork.
            _router.reassign(agent.id, "mock")
            agent.profile = "mock"
    _router.inject_world(new_world)
    clear_cache = getattr(_router, "clear_cache", None)
    if callable(clear_cache):
        clear_cache()  # audit B12: parent-run cached decisions must not serve here

    new_runtime = AgentRuntime(new_world, _router)
    new_loop = TickLoop(
        world=new_world,
        runtime=new_runtime,
        repo=_repo,
        router=_router,
        broadcaster=_broadcast,
    )

    # ── New run row: config carried from the parent + a forked_from marker,
    # lineage stamped in the dedicated columns (event-log.md v1.3.0 note 4). ──
    child_cfg["forked_from"] = body.run_id
    child_cfg["forked_at_tick"] = actual_tick
    new_run_id = _repo.start_run(
        json.dumps(child_cfg), forked_from=body.run_id, forked_at_tick=actual_tick
    )
    new_loop._run_id = new_run_id
    _repo.save_places(new_run_id, list(new_world.places.values()))
    for agent in new_world.agents.values():
        _repo.save_agent(new_run_id, agent, new_world.tick)

    # Swap the module singletons; the forked run is now "the" world, PAUSED.
    new_world.running = False
    _world, _runtime, _loop = new_world, new_runtime, new_loop

    # First event of the forked run records the lineage (open kind registry —
    # consumers tolerate unknown kinds per event-log.md §4).
    new_loop._emit_event({
        "kind": "run_forked",
        "actor_id": None,
        "actor_type": "system",
        "text": f"forked from run #{body.run_id} @ tick {actual_tick}",
        "payload": {"parent_run_id": body.run_id, "tick": actual_tick},
    })
    # Snapshot the forked base (after the event: a snapshot at tick t includes
    # all tick-t events, event-log.md §boundary), then show everyone the world.
    new_loop._save_snapshot(new_world.tick)
    new_loop._broadcast_world_state()

    result: dict = {"status": "ok", "run_id": new_run_id, "forked_at_tick": actual_tick}
    if actual_tick != body.tick:
        result["note"] = (
            f"forked from the nearest snapshot at tick {actual_tick} "
            f"(requested {body.tick}); the {actual_tick + 1}..{body.tick} event "
            "delta is not folded server-side"
        )
    return result


@app.get("/api/events")
async def get_events(
    run_id: int | None = None,  # query param: scope to a past run (default: active run)
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
    kinds: str | None = Query(default=None, description="comma-separated kinds"),
    actor_id: str | None = Query(default=None),
    turn_id: str | None = Query(default=None),
    after_seq: int | None = Query(default=None),
    limit: int | None = Query(default=None),
    order: str = Query(default="asc"),
):
    run_id = _resolve_run_id(run_id)
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
async def get_turn_trace(turn_id: str, run_id: int | None = None):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return []
    return _repo.get_turn_trace(run_id, turn_id)


@app.get("/api/rules/history")
async def get_rule_history(run_id: int | None = None):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return []
    return _repo.get_rule_history(run_id)


@app.get("/api/relationships")
async def get_relationships(
    run_id: int | None = None,
    agent_id: str | None = Query(default=None),
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return []
    return _repo.get_relationship_timeline(
        run_id, agent_id=agent_id, from_tick=from_tick, to_tick=to_tick
    )


@app.get("/api/snapshots")
async def get_snapshots(run_id: int | None = None):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return []
    return _repo.get_snapshots(run_id)


@app.get("/api/replay")
async def get_replay(tick: int = Query(...), run_id: int | None = None):
    """Replay materials for tick T (api.openapi.yaml v1.2.0, audit B7).

    `events` contains ONLY the fold-forward delta: rows with
    base.tick < e.tick <= T (strict on the left — the snapshot at base.tick
    already includes all tick-base.tick events, per event-log.md v1.1.0 §3).
    If no snapshot exists, base is null and events cover 0 <= e.tick <= T.
    Clients fold `events` onto `base.state` without further filtering.

    W11a EM-086: with an explicit ?run_id this serves a PAST run unchanged —
    snapshots + events are both run-scoped, and world geometry (places) comes
    from base.state (that run's snapshot state_json), never the live-owned
    `places` table (which the active run rewrites via INSERT OR REPLACE).
    """
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return {"base": None, "events": []}
    base = _repo.nearest_snapshot(run_id, tick)
    from_tick = (base["tick"] + 1) if base is not None else 0
    events = _repo.get_events(run_id, from_tick=from_tick, to_tick=tick, order="asc")
    return {"base": base, "events": events}


@app.get("/api/analytics")
async def get_analytics(
    run_id: int | None = None,
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return {}
    return _repo.get_analytics(run_id, from_tick=from_tick, to_tick=to_tick)

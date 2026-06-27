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
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config.loader import load_config, load_personas, WorldConfig
from ..engine.world import World, AgentState, PlaceState
from ..engine.loop import TickLoop, _run_config_json
from ..agents.runtime import AgentRuntime
from ..animals.runtime import ANIMAL_SPECIES_CATALOG, _seed_int
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
                   kind=p.kind, description=p.description,
                   district=p.district,  # Wave C / EM-147 — optional, additive
                   neighborhood_id=p.neighborhood_id,  # EM-123 — optional
                   zone_kind=p.zone_kind)              # EM-123 — optional
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
            # Wave D2 / EM-158 — optional per-agent tier from world.yaml.
            cadence_tier=getattr(a, "cadence_tier", "protagonist"),
        )
        for a in cfg.agents
    ]

    world = World(params=cfg.world, places=places, agents=agents)
    # Wave D3 / EM-177 — thread the `world.lane_failover` block to the router
    # (defensive getattr: pre-D3 configs lack the field and get the defaults).
    # W7 / EM-068 — thread the `world.cache` block too: the decision cache is
    # config-gated (OFF since 2026-06-12 per the EM-198 rescope), but the flag
    # was never wired here, so the Router fell back to its default-ON cache and
    # served verbatim hits — characters (esp. animals, whose brief prompts
    # repeat) parroted the same line. Honor the config so `enabled: false`
    # actually disables it. Defensive getattr keeps cache-less configs on the
    # pre-W7 default-ON behavior.
    cache_cfg = getattr(cfg.world, "cache", None)
    router = Router(
        cfg.profiles,
        lane_failover=getattr(cfg.world, "lane_failover", None),
        # EM-167 — thread the `world.overflow_lane` block (defensive getattr:
        # pre-EM-167 configs lack the field and get the OFF defaults).
        overflow_lane=getattr(cfg.world, "overflow_lane", None),
        cache_enabled=bool(getattr(cache_cfg, "enabled", True)),
        cache_max=int(getattr(cache_cfg, "max_entries", 512)),
    )

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
    providers/usage.py). Defensive: alerting must never break a turn.

    Wave D3 / EM-168: the same alert then drives the cap-pressure governor
    (_apply_cap_governor) — config-gated, world-side, additive."""
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
    _apply_cap_governor(alert)


def _usage_alert_window() -> str:
    """The UsageAlertTracker's CURRENT UTC-day window key ("YYYY-MM-DD"), or ""
    when unknown (Wave D3 / EM-168). A pure attribute peek — the tracker owns
    every clock read and rolls the window lazily on real adapter calls; the
    governor's demote/restore cycle keys off this value, never a new clock."""
    tracker = getattr(_router, "_usage_alerts", None)
    return str(getattr(tracker, "_window", "") or "")


def _apply_cap_governor(alert: dict) -> None:
    """Wave D3 / EM-168 — cap-pressure governor, driven off the usage_alert
    sink: demote every agent assigned to the alerting lane one cadence tier
    for the rest of the tracker's day window (world.apply_cap_pressure owns
    the rules: config gate, once-per-lane-alert-day, background floor,
    rollover-first restoration). Emits the returned `cap_pressure` feed
    event(s) and broadcasts the tier change. Same global-reading pattern as
    _emit_usage_alert/_emit_lane_detour so it follows reset/fork; defensive —
    governing must never break a turn."""
    if _world is None or _loop is None:
        return
    provider = alert.get("provider")
    if not provider:
        return
    try:
        apply = getattr(_world, "apply_cap_pressure", None)
        if not callable(apply):
            return
        events = apply(str(provider), _usage_alert_window())
        for evt in events:
            _loop._emit_event(evt)
        if events:
            _loop._broadcast_world_state()
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("cap governor failed for %s: %s", provider, exc)


def _emit_lane_detour(payload: dict) -> None:
    """Sink for Router lane-failover edge events (Wave D3 / EM-177).

    Persists + broadcasts ONE `lane_detour` row per streak transition — the
    first detour of a streak (degraded) and the recovery — never per turn
    (per-turn truth rides the llm_call payload). Same pattern as
    _emit_usage_alert: reads the CURRENT _loop/_world globals so events keep
    landing in the right run after reset/fork. Defensive: feed transparency
    must never break a turn."""
    if _loop is None:
        return
    try:
        agent = (_world.agents or {}).get(payload.get("agent_id")) if _world else None
        who = agent.name if agent is not None else (payload.get("agent_id") or "an agent")
        home = payload.get("home")
        substitute = payload.get("substitute")
        phase = payload.get("phase")
        if phase == "recovered":
            text = f"✓ {home} lane recovered — {who} is back home"
        else:
            text = f"⚠ {home} lane is degraded — {who} is borrowing {substitute}"
        _loop._emit_event({
            "kind": "lane_detour",
            "actor_type": "system",
            "actor_id": None,
            "profile": home,
            "text": text,
            "payload": {
                "phase": phase,
                "home": home,
                "substitute": substitute,
                "agent_id": payload.get("agent_id"),
            },
        })
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("lane_detour emission failed: %s", exc)


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot-restore machinery shared by POST /api/runs/fork (W11b EM-101) and
# resume-on-boot (Wave D3 EM-187). Factored from the fork endpoint so resume
# reuses the exact same restore + spin-up path instead of duplicating it.
# ──────────────────────────────────────────────────────────────────────────────

def _restore_world_from_snapshot(
    state: dict, params: Any = None, place_overrides: list | None = None
) -> World:
    """Rebuild a live World from a snapshot `state` via the EM-101 seam
    (`World.from_snapshot`) — the shared restore half of fork and resume.

    ADDITIVE to the contracted 2-arg seam: when the engine's from_snapshot
    accepts `params`, the given WorldParams ride along (fork passes the PARENT
    run's params; resume passes the CURRENT config's — snapshot state stays
    authoritative over params on restore either way). Signature-sniffed so the
    contracted form keeps working; exceptions propagate to the caller (fork
    maps them to 400, resume falls back to a fresh boot)."""
    kwargs: dict = {"place_overrides": place_overrides}
    try:
        import inspect
        if params is not None and \
                "params" in inspect.signature(World.from_snapshot).parameters:
            kwargs["params"] = params
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not sniff from_snapshot params support: %s", exc)
        kwargs.pop("params", None)
    return World.from_snapshot(state, **kwargs)


def _spin_up_run_from_world(
    new_world: World,
    *,
    parent_run_id: int,
    snapshot_tick: int,
    config_json: str,
) -> tuple[AgentRuntime, TickLoop, int]:
    """Wire a snapshot-restored world into a NEW run — the shared spin-up half
    of fork and resume-on-boot: router reassignment (vanished profiles degrade
    to mock), world injection for the mock providers, the EM-168 usage-window
    probe, a decision-cache flush (audit B12: parent-run cached decisions must
    not serve here), a fresh runtime + loop, and the new runs row with fork
    lineage (forked_from / forked_at_tick) re-seeded with places + agents.
    The caller swaps the module singletons and emits its own lineage event
    (run_forked / run_resumed)."""
    for agent in new_world.agents.values():
        try:
            _router.reassign(agent.id, agent.profile)
        except ValueError:
            # Profile vanished from the registry since the parent run: degrade
            # to mock (always present) rather than failing the restore.
            _router.reassign(agent.id, "mock")
            agent.profile = "mock"
    _router.inject_world(new_world)
    # Wave D3 / EM-168 — re-wire the usage-window probe onto the restored world
    # so cap-governor demotions carried by the snapshot still lift at the
    # tracker's day rollover.
    set_probe = getattr(new_world, "set_usage_window_probe", None)
    if callable(set_probe):
        set_probe(_usage_alert_window)
    clear_cache = getattr(_router, "clear_cache", None)
    if callable(clear_cache):
        clear_cache()

    new_runtime = AgentRuntime(new_world, _router)
    new_loop = TickLoop(
        world=new_world,
        runtime=new_runtime,
        repo=_repo,
        router=_router,
        broadcaster=_broadcast,
    )
    new_run_id = _repo.start_run(
        config_json, forked_from=parent_run_id, forked_at_tick=snapshot_tick
    )
    new_loop._run_id = new_run_id
    # EM-222 — hand the freshly-built runtime the repo + active run so its
    # relevance-scored memory retrieval reads THIS forked/resumed run's log.
    new_loop._wire_runtime_run_context()
    _repo.save_places(new_run_id, list(new_world.places.values()))
    for agent in new_world.agents.values():
        _repo.save_agent(new_run_id, agent, new_world.tick)
    return new_runtime, new_loop, new_run_id


def _resume_block_reason(
    parent_run: dict, snapshot_state: dict, config: WorldConfig
) -> str | None:
    """Wave D3 / EM-187 §B4.3 — the config-compatibility guard. None ⇒ resume;
    else a short reason for the boot log (log.info, no feed noise).

    WORLD-DEFINING bits only: agent roster (names, after EM-175 padding — both
    the parent's stored config_json and the current config are the padded
    effective rosters of their respective boots), places set, and city_seed.
    Tunable params (cadence, budgets, lane_failover, cap_governor, …) adopt
    the CURRENT config and never block a resume."""
    try:
        parent_cfg = json.loads(parent_run.get("config_json") or "{}")
    except (TypeError, ValueError):
        parent_cfg = {}
    if not isinstance(parent_cfg, dict):
        parent_cfg = {}

    # Roster: names are the stable identity (agent ids are minted per run).
    parent_agents = parent_cfg.get("agents")
    if not isinstance(parent_agents, list):
        # Legacy/foreign blob with no roster: fail closed — never resume into
        # a world we cannot prove matches.
        return f"run {parent_run.get('id')} stored no agent roster"
    parent_names = sorted(
        str(a.get("name"))
        for a in parent_agents
        if isinstance(a, dict) and a.get("name")
    )
    current_names = sorted(a.name for a in config.agents)
    if parent_names != current_names:
        return (
            f"agent roster changed (run {parent_run.get('id')}: "
            f"{parent_names} vs current: {current_names})"
        )

    # Places set: stored in config_json since EM-187; legacy rows fall back to
    # the snapshot's geometry — which IS what from_snapshot would restore.
    parent_places = parent_cfg.get("places")
    if isinstance(parent_places, list):
        parent_place_ids = sorted(str(p) for p in parent_places)
    else:
        parent_place_ids = sorted(
            str(d.get("id"))
            for d in (snapshot_state.get("places") or [])
            if isinstance(d, dict) and d.get("id")
        )
    current_place_ids = sorted(p.id for p in config.places)
    if parent_place_ids != current_place_ids:
        return (
            f"places set changed (run {parent_run.get('id')}: "
            f"{parent_place_ids} vs current: {current_place_ids})"
        )

    # city_seed: world-defining (the 3D city renders as f(snapshot, seed)).
    parent_world = parent_cfg.get("world")
    parent_world = parent_world if isinstance(parent_world, dict) else {}
    try:
        parent_seed = int(parent_world.get("city_seed", 1337))
    except (TypeError, ValueError):
        parent_seed = 1337
    current_seed = int(getattr(config.world, "city_seed", 1337))
    if parent_seed != current_seed:
        return f"city_seed changed ({parent_seed} -> {current_seed})"

    return None


def _try_resume_on_boot() -> bool:
    """Wave D3 / EM-187 — resume-on-boot. Called from lifespan AFTER
    _build_world set the module singletons but BEFORE the fresh TickLoop /
    init_run exist. When `world.resume_on_boot` (default true) and the most
    recent run with a >tick-0 snapshot is config-compatible, rebuild the world
    from that snapshot (CURRENT config params + snapshot state) via the shared
    fork machinery, start a NEW run row with fork lineage, emit ONE
    `run_resumed` event into the new run, and swap the world/runtime/loop
    singletons. Returns True when the boot was resumed (the caller then skips
    the fresh init_run). Any mismatch or failure logs ONE info reason and
    falls back to the fresh boot — resume must never stop the backend from
    starting. `resume_on_boot: false` returns immediately (no DB reads):
    byte-identical pre-D3 boot."""
    global _world, _runtime, _loop

    if _config is None or _repo is None:
        return False
    if not bool(getattr(_config.world, "resume_on_boot", True)):
        return False
    finder = getattr(_repo, "latest_resumable_run", None)
    if not callable(finder):  # pragma: no cover - defensive
        return False
    try:
        found = finder()
    except Exception as exc:  # pragma: no cover - defensive
        log.info("resume-on-boot: snapshot lookup failed (%s) — fresh run", exc)
        return False
    if found is None:
        return False  # nothing resumable: fresh run exactly as today

    parent = found["run"]
    snapshot_tick = int(found["snapshot"]["tick"])
    state = found["snapshot"]["state"]
    reason = _resume_block_reason(parent, state, _config)
    if reason is not None:
        log.info("resume-on-boot: config mismatch — starting a fresh run (%s)", reason)
        return False
    try:
        # CURRENT config's params + the snapshot's state (snapshot stays
        # authoritative on restore) — tunables adopt today's world.yaml.
        new_world = _restore_world_from_snapshot(state, _config.world)
    except Exception as exc:
        log.info("resume-on-boot: snapshot restore failed (%s) — fresh run", exc)
        return False

    new_runtime, new_loop, new_run_id = _spin_up_run_from_world(
        new_world,
        parent_run_id=int(parent["id"]),
        snapshot_tick=snapshot_tick,
        config_json=_run_config_json(_config),  # tunables: the CURRENT config
    )
    _world, _runtime, _loop = new_world, new_runtime, new_loop

    # ONE system event announces the resume (§B4.2 feed transparency).
    new_loop._emit_event({
        "kind": "run_resumed",
        "actor_id": None,
        "actor_type": "system",
        "text": f"▶ resumed run {parent['id']} from tick {snapshot_tick}",
        "payload": {
            "parent_run_id": int(parent["id"]),
            "snapshot_tick": snapshot_tick,
        },
    })
    # Seed critters the snapshot does NOT already carry (§B4.4 — e.g. animals
    # newly enabled since the parent run); never a duplicate cat/dog.
    new_loop._spawn_seed_animals(_config)
    # Snapshot the resumed base (after the event: a snapshot at tick T includes
    # all tick-T events, event-log.md §boundary) so replay has its base.
    new_loop._save_snapshot(new_world.tick)
    log.info(
        "resume-on-boot: resumed run %s from tick %s as run %s",
        parent["id"], snapshot_tick, new_run_id,
    )
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _world, _router, _runtime, _repo, _loop, _config

    _config = load_config()
    _world, _router, _runtime, _repo = _build_world(_config)
    # Wave D3 / EM-187 — resume-on-boot: when a config-compatible run with a
    # >tick-0 snapshot exists (and world.resume_on_boot, default true), the
    # fresh world built above is replaced by the snapshot-restored one and a
    # NEW lineage-stamped run row starts; otherwise (or when disabled) the
    # boot below is byte-identical to the pre-D3 fresh start. All the D3
    # wiring that follows (mock-world injection, usage-alert + lane-event
    # sinks, usage-window probe) targets the post-resume singletons either way.
    if not _try_resume_on_boot():
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
    # Wave D3 / EM-177 — route lane_detour streak-edge payloads into the event
    # log the same way. The sink reads the CURRENT _loop/_world globals, so
    # events keep landing in the right run after reset/fork.
    _router.set_lane_event_sink(_emit_lane_detour)
    # Wave D3 / EM-168 — give the world a zero-clock-read peek at the usage
    # tracker's day window so the scheduler can restore cap-governor demotions
    # at the tracker's rollover. (loop.reset mutates this world in place, so
    # the probe survives /api/control/reset; the fork endpoint re-wires it.)
    _world.set_usage_window_probe(_usage_alert_window)

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

# Wave I / EM-210 — serve the Atelier's generated PNGs. The loop writes them to
# data/assets/images/<image_id>.png (an external side-artifact, off the replay
# surface); the frontend reads the relative /assets/images/<id>.png url straight
# from the gallery/event payload. The dir is created on boot if missing (so the
# StaticFiles mount + the test client never error on a fresh checkout).
try:
    from pathlib import Path as _AssetsPath
    _assets_dir = _AssetsPath(__file__).resolve().parents[3] / "data" / "assets"
    _assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")
except Exception as _assets_exc:  # pragma: no cover - defensive (read-only FS etc.)
    log.warning("static /assets mount failed: %s", _assets_exc)


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


def _gallery_images_dir() -> "_Path":
    """Where the Atelier's PNGs land (mirrors the /assets StaticFiles mount).
    A module-level seam so tests can point it at a tmp dir."""
    return _Path(__file__).resolve().parents[3] / "data" / "assets" / "images"


@app.get("/api/gallery")
async def get_gallery():
    """The Atelier viewer's read surface (Wave I / EM-210).

    Returns the live world's gallery records FILTERED to those whose PNG
    actually exists on disk. The gallery record + image_posted are written
    synchronously at create_image time, but the PNG fetch is best-effort
    (bounded, skip-under-load, swallows 402s) — so a record can outlive an
    image that never materialized (a credit-exhausted or load-skipped fetch).

    world_state.gallery stays the replay-pure sim record (what agents intended
    and reacted to); THIS endpoint is the live, disk-aware DISPLAY view, so the
    viewer never points an <img> at a missing file (no 404 spam, no phantom
    'art unavailable' tiles). `total` vs `materialized` lets the panel note how
    many pieces are still un-rendered."""
    if _world is None:
        raise HTTPException(503, "Not initialized")
    gallery = list(getattr(_world, "gallery", []) or [])
    images_dir = _gallery_images_dir()
    materialized = [
        dict(g)
        for g in gallery
        if g.get("image_id") and (images_dir / f"{g['image_id']}.png").is_file()
    ]
    return {
        "images": materialized,
        "plaza_banner_ref": getattr(_world, "plaza_banner_ref", "") or "",
        "total": len(gallery),
        "materialized": len(materialized),
    }


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


class ChronicleBuildBody(BaseModel):
    # EM-201 — optional model override (the picker). Absent → the configured
    # (free) narrator profile. Never forces a paid lane on the user.
    model: str | None = Field(default=None, max_length=60)
    # EM-201 follow-on — when True, regenerate EVERY window 0→now (fresh prose +
    # fresh server-computed fact/version stamps), not just the un-chronicled
    # gaps. Lets old chapters (written before the facts existed) get re-stamped.
    rebuild: bool = False
    # EM-201 follow-on — when True, the CHEAP fix: re-derive chaos for OLD (v1)
    # chapters and re-emit them WITH THEIR ORIGINAL PROSE (zero LLM), narrate only
    # the true gaps, skip windows already carrying a v2 chapter. Wins over rebuild
    # when set (preserves the original prose).
    restamp: bool = False


@app.post("/api/chronicle/build")
async def chronicle_build(body: ChronicleBuildBody):
    """EM-201 — backfill the chronicle from the EXISTING run history. Kicks off a
    background task (returns immediately); chapters emit live as narrator_summary
    events the Chronicle tab renders. The model is the caller's choice — defaults
    to the configured (free) narrator profile, never a paid lane. EM-201
    follow-on: `rebuild=True` regenerates every window instead of gap-filling."""
    if _loop is None or _world is None or _router is None:
        raise HTTPException(503, "Not initialized")
    cfg = getattr(_world.params, "narrator", None)
    model = (body.model or getattr(cfg, "model_profile", "") or "").strip()
    if not model or _router.get_profile(model) is None:
        raise HTTPException(400, f"Unknown or unconfigured chronicle model: {model!r}")
    started = _loop.start_chronicle_backfill(
        model, rebuild=body.rebuild, restamp=body.restamp
    )
    return {
        "status": "building" if started else "already_running",
        "model": model,
        "rebuild": body.rebuild,
        "restamp": body.restamp,
    }


@app.get("/api/lanes")
async def get_lanes():
    """Wave D3 / EM-177 — lane-health observability. Returns the router's
    EM-135 lane_health() snapshot (profile -> {window, boosted, timeouts,
    last_routed_via}) augmented per profile with `sick` (the failover
    predicate) and `detours_routed_here` (detoured calls this lane absorbed
    this run). Lanes appear once they have at least one recorded outcome."""
    if _router is None:
        raise HTTPException(503, "Not initialized")
    return _router.lane_health()


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


# Wave D2 / EM-158 — per-agent cadence tier reassignment (hot-swappable like
# the model endpoint above). Takes effect at the agent's next round-start
# scheduling decision; the change is broadcast so the tier chip updates live.

_VALID_CADENCE_TIERS = ("protagonist", "supporting", "background")


class TierBody(BaseModel):
    tier: str = Field(max_length=20)


@app.post("/api/agents/{agent_id}/tier")
async def reassign_tier(agent_id: str, body: TierBody):
    if _world is None:
        raise HTTPException(503, "Not initialized")
    agent = _world.agents.get(agent_id)
    if agent is None:
        raise HTTPException(404, f"Unknown agent: {agent_id}")
    if body.tier not in _VALID_CADENCE_TIERS:
        raise HTTPException(
            400, f"Unknown tier: {body.tier!r} (protagonist|supporting|background)"
        )
    old_tier = getattr(agent, "cadence_tier", "protagonist")
    agent.cadence_tier = body.tier
    # Wave D3 / EM-168 — a manual tier set WINS over the cap-pressure governor:
    # clear the demotion marker so the day rollover never "restores" over the
    # user's explicit choice. (The lane's once-per-alert-day record stands, so
    # a same-day repeat alert won't re-demote either.)
    if getattr(agent, "demoted_from", None) is not None:
        agent.demoted_from = None
    if _loop:
        _loop._emit_event({
            "kind": "cadence_tier_changed",
            "actor_id": agent_id,
            "profile": agent.profile,
            "profile_color": _loop._get_profile_color(agent),
            "text": f"{agent.name}'s cadence tier set to {body.tier}.",
            "payload": {"old_tier": old_tier, "new_tier": body.tier},
        })
        _loop._broadcast_world_state()
    return {"status": "ok", "agent_id": agent_id, "cadence_tier": body.tier}


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
    # Wave D2 / EM-158 — optional scheduler cadence tier
    # (protagonist | supporting | background). Absent ⇒ protagonist (the
    # zero-behavior-change default). Unknown value -> 400.
    cadence_tier: str | None = Field(default=None, max_length=20)
    # EM-240 — optional crime-schema overrides; a persona card fills these in,
    # an explicit body wins. Unknown values fall back to lawful/citizen.
    disposition: str | None = Field(default=None, max_length=20)
    role: str | None = Field(default=None, max_length=20)
    # run-663 — A/B opt-in: spawn the SAME persona across multiple models as
    # labeled contestants. Each entry must be a known profile name. Only valid
    # in god mode; governance + ab_models is a 400.
    ab_models: list[str] | None = None


def _resolve_spawn_fields(body: SpawnBody) -> tuple[str, str, str, str, str]:
    """Effective (name, personality, profile, disposition, role) for a spawn
    (W11b EM-092; EM-240 added disposition/role).

    Explicit body fields always win; a `persona` card fills the gaps; what is
    still missing after that is a 400 (unknown persona is a 400 too). The
    pre-W11b default personality ('A generic agent.') is preserved when neither
    the body nor a card supplies one. EM-240 disposition/role fall back to the
    lawful/citizen defaults when absent or unknown."""
    name, personality, profile = body.name, body.personality, body.profile
    disposition, role = body.disposition, body.role
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
        disposition = disposition or card.get("disposition")
        role = role or card.get("role")
    if not name:
        raise HTTPException(400, "name is required (directly or via persona)")
    if not profile:
        raise HTTPException(400, "profile is required (directly or via persona)")
    disposition = disposition if disposition in ("lawful", "opportunist", "criminal") else "lawful"
    role = role if role in ("citizen", "enforcer") else "citizen"
    return name, (personality or "A generic agent."), profile, disposition, role


def _spawn_mode(body: SpawnBody) -> str:
    """Effective spawn mode: explicit body.mode wins; else config spawn.mode; else god."""
    if body.mode:
        return body.mode
    spawn_cfg = getattr(_config.world, "spawn", None) if _config else None
    mode = getattr(spawn_cfg, "mode", None) if spawn_cfg is not None else None
    return mode or "god"


def _ab_tag(profile_name: str) -> str:
    """run-663 — derive short label from a profile name.

    Uses the segment before the first '-' (e.g. 'mistral-small' → 'mistral',
    'groq-llama' → 'groq'). When there is no '-', the whole name is the tag
    (e.g. 'kimi' → 'kimi').
    """
    return profile_name.split("-")[0]


@app.post("/api/agents")
async def spawn_agent(body: SpawnBody, response: Response):
    if _world is None or _router is None:
        raise HTTPException(503, "Not initialized")

    # run-663 — A/B opt-in: when ab_models is present and non-empty (god mode
    # only) spawn one agent per model using the shared name/personality.
    if body.ab_models:
        mode = _spawn_mode(body)
        if mode != "god":
            raise HTTPException(
                400,
                "ab_models is only supported in god mode",
            )
        # Name is required; personality is optional (defaults to generic).
        # Profile is NOT required here — each variant supplies its own.
        name = body.name
        if body.persona:
            # Resolve from persona card but do NOT require suggested_profile.
            wanted = body.persona.strip().lower()
            card = next(
                (c for c in load_personas() if c["name"].strip().lower() == wanted),
                None,
            )
            if card is None:
                raise HTTPException(400, f"Unknown persona: {body.persona!r}")
            name = name or card["name"]
            personality = body.personality or card["personality"] or "A generic agent."
        else:
            personality = body.personality or "A generic agent."
        if not name:
            raise HTTPException(400, "name is required (directly or via persona)")

        # Validate all profiles before touching the world.
        for prof_name in body.ab_models:
            if _router.get_profile(prof_name) is None:
                raise HTTPException(400, f"Unknown profile: {prof_name!r}")

        cadence_tier = body.cadence_tier or "protagonist"
        if cadence_tier not in _VALID_CADENCE_TIERS:
            raise HTTPException(
                400,
                f"Unknown cadence_tier: {body.cadence_tier!r} "
                "(protagonist|supporting|background)",
            )

        # Spawn one agent per model in the A/B group.
        spawned: list[dict] = []
        for prof_name in body.ab_models:
            tag = _ab_tag(prof_name)
            variant_name = f"{name}·{tag}"
            agent = _world.spawn_agent(
                name=variant_name,
                personality=personality,
                profile=prof_name,
                location=body.location,
                cadence_tier=cadence_tier,
            )
            _router.reassign(agent.id, prof_name)
            if _loop and _repo:
                run_id = _loop._run_id or 1
                _repo.save_agent(run_id, agent, _world.tick)
                _loop._emit_event({
                    "kind": "agent_spawned",
                    "actor_id": agent.id,
                    "actor_type": "god",
                    "profile": prof_name,
                    "profile_color": _loop._get_profile_color(agent),
                    "text": f"{agent.name} spawned (A/B group: {name}).",
                    "payload": {
                        "agent_id": agent.id,
                        "name": agent.name,
                        "method": "god",
                        "ab_group": name,  # correlates variants in the UI
                    },
                })
            spawned.append({
                "agent_id": agent.id,
                "name": agent.name,
                "profile": prof_name,
            })
        if _loop:
            _loop._broadcast_world_state()
        response.status_code = 201
        return {"status": "ok", "mode": "god", "agents": spawned}

    # ── Single-spawn path (unchanged, byte-identical to pre-run-663) ──────────

    # W11b / EM-092 — persona prefill: explicit fields win, the card fills gaps,
    # unknown persona / still-missing name|profile -> 400.
    name, personality, profile, disposition, role = _resolve_spawn_fields(body)
    if _router.get_profile(profile) is None:
        raise HTTPException(400, f"Unknown profile: {profile}")
    # Wave D2 / EM-158 — optional cadence tier; absent ⇒ protagonist.
    cadence_tier = body.cadence_tier or "protagonist"
    if cadence_tier not in _VALID_CADENCE_TIERS:
        raise HTTPException(
            400,
            f"Unknown cadence_tier: {body.cadence_tier!r} "
            "(protagonist|supporting|background)",
        )

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
            cadence_tier=cadence_tier,  # Wave D2 / EM-158 — additive
        )
        proposal_id = rule.id
        spec = {
            "name": name,
            "profile": profile,
            "personality": personality,
            "location": body.location,
            "cadence_tier": cadence_tier,
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
        cadence_tier=cadence_tier,  # Wave D2 / EM-158 — additive
        disposition=disposition,    # EM-240 — additive persona schema
        role=role,
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
    # Audit B15: same caps as SpawnBody (species is enum-checked in the handler
    # against ANIMAL_SPECIES_CATALOG — the 7-species menagerie, EM-143).
    species: str            # cat | dog | squirrel | raccoon | goat | fox | crow
    name: str = Field(max_length=40)
    location: str = Field(default="plaza", max_length=40)
    personality: str = Field(default="", max_length=280)


@app.post("/api/animals")
async def spawn_animal_endpoint(body: SpawnAnimalBody, response: Response):
    """Spawn an animal immediately (god-mode), emitting animal_spawned. Animals
    have no credits (invariant 7) and are NOT in the agent round-robin — they act
    on the slow animal cadence. Species is validated against the menagerie catalog
    (EM-143); the configured animals.max_population cap returns 409 when reached."""
    if _world is None:
        raise HTTPException(503, "Not initialized")
    if body.species not in ANIMAL_SPECIES_CATALOG:
        allowed = ", ".join(sorted(ANIMAL_SPECIES_CATALOG))
        raise HTTPException(400, f"Unknown species: {body.species!r} (one of: {allowed})")
    try:
        animal = _world.spawn_animal(
            species=body.species,
            name=body.name,
            location=body.location,
            personality=body.personality,
        )
    except ValueError as exc:
        # The population cap (world.spawn_animal) raises ValueError when the
        # menagerie is full — surface it as 409 Conflict, not a 500.
        raise HTTPException(409, str(exc))
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


class RewildBody(BaseModel):
    # Wave H2 / EM-207 — how many critters to seed in one click. Bounded so a god
    # button can't request a runaway burst; the cap still stops it short.
    count: int = Field(default=4, ge=1, le=50)


@app.post("/api/god/rewild")
async def god_rewild(body: RewildBody = RewildBody()):
    """Wave H2 / EM-207 — the REWILD god button: seed a BURST of random catalog
    critters in one click. Spawns up to `count` random species at random places,
    stopping the moment living animals reaches animals.max_population. Each spawn
    is DETERMINISTIC (seeded off the world tick + the burst index — no Math.random
    / no wall-clock, so it is replay-safe + testable) and emits an `animal_spawned`
    (payload.method 'rewild'); one world_state broadcast at the end. Returns
    {spawned: N, cap_reached: bool}. 503 when the world isn't initialized."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    count = int(body.count)
    spawned = 0
    cap_reached = False
    tick = int(getattr(_world, "tick", 0))
    animals_cfg = getattr(_world.params, "animals", None)
    max_population = int(getattr(animals_cfg, "max_population", 0) or 0)
    for i in range(count):
        # Pre-check the cap so we report cap_reached cleanly (and never spam the
        # ValueError path), then defensively catch a racing ValueError too.
        if max_population > 0 and len(_world.living_animals()) >= max_population:
            cap_reached = True
            break
        seed = _seed_int("rewild", tick, i)
        try:
            animal = _world.spawn_random_animal(seed)
        except ValueError:
            cap_reached = True
            break
        if animal is None:
            break  # no place to put it (empty world) — nothing more to do
        spawned += 1
        _loop._emit_event({
            "kind": "animal_spawned",
            "actor_id": animal.id,
            "actor_type": "animal",
            "text": f"{animal.name} the {animal.species} is rewilded into the world.",
            "payload": {
                "animal_id": animal.id,
                "species": animal.species,
                "name": animal.name,
                "location": animal.location,
                "method": "rewild",
            },
        })
    if spawned:
        _loop._broadcast_world_state()
    return {"spawned": spawned, "cap_reached": cap_reached}


class CullBody(BaseModel):
    # Wave H follow-on — how many LIVING animals to KEEP after thinning the herd.
    keep: int = Field(default=5, ge=0, le=100)


@app.post("/api/god/cull")
async def god_cull(body: CullBody = CullBody()):
    """Wave H follow-on — THIN THE HERD: reduce living animals down to `keep`
    (oldest-of-each-species first, so the seed cat & dog + species variety stay),
    removing the rest. Each removed animal emits an `animal_died` (method
    'culled'); one world_state broadcast. Returns {removed: N, kept: M}. 503 when
    the world isn't initialized. The reverse of REWILD — relief when testing/
    rewilds have flooded the feed, without resetting the world."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    events = _world.cull_animals(int(body.keep))
    for e in events:
        _loop._emit_event(e)
    if events:
        _loop._broadcast_world_state()
    return {"removed": len(events), "kept": len(_world.living_animals())}


class ZooEscapeBody(BaseModel):
    # Wave H3 / EM-208 — optionally target ONE operational zoo by id; omit to
    # break loose EVERY operational zoo at once.
    zoo_building_id: str | None = None


@app.post("/api/god/zoo_escape")
async def god_zoo_escape(body: ZooEscapeBody = ZooEscapeBody()):
    """Wave H3 / EM-208 — THE ESCAPE god button: trigger a zoo breakout. Calls
    World.trigger_zoo_escape (deterministic + replay-safe: each animal's new
    place is a seeded hash of its id + the world tick, no wall-clock / no
    Math.random), emits the resulting event batch (one dramatic random_event +
    one is_chaotic animal_action{action:"escape"} per freed animal) via the loop
    emit path, then one world_state broadcast. Returns {escaped: N, zoos: M}.
    A no-op (no operational zoo or no housed animals) returns {escaped: 0,
    zoos: 0} with no broadcast. 503 when the world isn't initialized. Mirrors the
    H2 /api/god/rewild structure."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    events = _world.trigger_zoo_escape(body.zoo_building_id)
    escaped = sum(1 for e in events if e.get("kind") == "animal_action")
    zoos = sum(1 for e in events if e.get("kind") == "random_event")
    for evt in events:
        _loop._emit_event(evt)
    if events:
        _loop._broadcast_world_state()
    return {"escaped": escaped, "zoos": zoos}


# ──────────────────────────────────────────────────────────────────────────────
# Wave K / EM-221 — GOD console BUILDERS endpoints (Wave 2). Each mirrors
# /api/god/rewild + /api/animals exactly: read _world, mutate via the SAME world
# methods the agents reuse (god_place_prop/god_clear_props/god_demolish/god_reskin
# all funnel through the Wave-1 internals), stamp the emitted events with
# actor_type "god" + payload.method, do ONE world_state broadcast at the end.
# Burst counts are capped (≤8 props/click). Validation rejections are 4xx like the
# spawn/rewild endpoints (ValueError → 400/404). NO standing LLM calls; god
# mutations serialize into snapshots like the agent path (EM-155 determinism).
# ──────────────────────────────────────────────────────────────────────────────

GOD_PLACE_PROP_MAX = 8  # bounded burst — a god click can't flood the prop registry


class GodPlacePropBody(BaseModel):
    kind: str = Field(min_length=1, max_length=30)
    place: str = Field(min_length=1, max_length=40)
    count: int = Field(default=1, ge=1, le=GOD_PLACE_PROP_MAX)


@app.post("/api/god/place_prop", status_code=201)
async def god_place_prop_endpoint(body: GodPlacePropBody):
    """Wave K / EM-221 — place `count` (≤8) god-owned props at `place`. Reuses
    World.god_place_prop (same seeded-id + ring-offset internals as the agent
    reflex tool, owner_id None). Stops short at params.props.max_population — the
    short event list reports it. Each placed prop emits a `prop_placed`
    (actor_type 'god', payload.method 'god'); one world_state broadcast at the end.
    Returns {placed: N, cap_reached: bool}. 400 unknown place / empty kind; 503
    when the world isn't initialized. Mirrors /api/god/rewild."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    try:
        events = _world.god_place_prop(body.kind, body.place, body.count)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    for evt in events:
        evt["actor_type"] = "god"
        evt["payload"]["method"] = "god"
        _loop._emit_event(evt)
    if events:
        _loop._broadcast_world_state()
    cap_reached = len(events) < body.count
    return {"placed": len(events), "cap_reached": cap_reached}


class GodClearPropsBody(BaseModel):
    place: str | None = Field(default=None, max_length=40)


@app.post("/api/god/clear_props")
async def god_clear_props_endpoint(body: GodClearPropsBody = GodClearPropsBody()):
    """Wave K / EM-221 — remove props at `place`, or ALL props when `place` is
    omitted (god override — no ownership gate). Reuses World.god_clear_props. Each
    cleared prop emits a `prop_removed` (actor_type 'god', payload.method 'god');
    one world_state broadcast. Returns {cleared: N, removed: N} (the FE reads
    `cleared`; `removed` is kept for back-compat). A no-op (nothing to clear)
    returns {cleared: 0, ...} with no broadcast. 400 unknown place; 503 when the
    world isn't initialized."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    try:
        events = _world.god_clear_props(body.place)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    for evt in events:
        evt["actor_type"] = "god"
        evt["payload"]["method"] = "god"
        _loop._emit_event(evt)
    if events:
        _loop._broadcast_world_state()
    # FE (useSimulation.clearProps) reads result.cleared; keep `removed` for
    # back-compat so existing callers/tests don't break.
    return {"cleared": len(events), "removed": len(events)}


class GodDemolishBody(BaseModel):
    building_id: str = Field(min_length=1, max_length=120)


@app.post("/api/god/demolish")
async def god_demolish_endpoint(body: GodDemolishBody):
    """Wave K / EM-221 — demolish a building IMMEDIATELY (god override: regardless
    of owner / landmark / governance). Reuses World.god_demolish → the shared
    _demolish_building path (same status flip + lot free as the owner tool and the
    governance effect, so it round-trips byte-identically). Emits one
    `building_demolished` (actor_type 'god', payload.method 'god', by 'god'); one
    world_state broadcast. Returns {demolished: true, status: 'ok', building_id}
    (the FE reads `demolished`). 404 unknown building; 409 already rubble; 503 when
    the world isn't initialized."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    try:
        evt = _world.god_demolish(body.building_id)
    except ValueError as exc:
        msg = str(exc)
        if msg == "already destroyed":
            raise HTTPException(409, msg)
        raise HTTPException(404, msg)
    evt["actor_type"] = "god"
    evt["payload"]["method"] = "god"
    _loop._emit_event(evt)
    _loop._broadcast_world_state()
    # FE (useSimulation.godDemolish) reads result.demolished; keep status/building_id.
    return {"demolished": True, "status": "ok", "building_id": body.building_id}


class GodReskinBody(BaseModel):
    building_id: str = Field(min_length=1, max_length=120)
    # An empty skin CLEARS the override back to the building's default palette.
    skin: str = Field(default="", max_length=24)


@app.post("/api/god/reskin")
async def god_reskin_endpoint(body: GodReskinBody):
    """Wave K / EM-221 — set a building's cosmetic skin (god override — no owner
    gate). Reuses World.god_reskin (same skin field + clamp as the agent tool). An
    empty skin clears it. Emits one `building_reskinned` (actor_type 'god',
    payload.method 'god'); one world_state broadcast. Returns {reskinned: true,
    status: 'ok', building_id, skin} (the FE reads `reskinned`). 404 unknown
    building; 503 when the world isn't initialized."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    try:
        evt = _world.god_reskin(body.building_id, body.skin)
    except ValueError as exc:
        raise HTTPException(404, str(exc))
    evt["actor_type"] = "god"
    evt["payload"]["method"] = "god"
    _loop._emit_event(evt)
    _loop._broadcast_world_state()
    # FE (useSimulation.godReskin) reads result.reskinned; keep status/building_id/skin.
    return {"reskinned": True, "status": "ok", "building_id": body.building_id,
            "skin": evt["payload"]["skin"]}


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
    # Wave E / EM-184 — agent_id is OPTIONAL: the targeted kinds
    # (bless_energy/grant_credits) still require it; the world-scale miracle
    # kinds (send_rain/bountiful_harvest/calm_spirits) REJECT it. Both
    # mismatches surface as 422 via the engine seam's ValueError.
    agent_id: str | None = None
    # ge/le make FastAPI 422 an out-of-range amount before the handler runs;
    # None falls through to the engine seam's per-kind default (25 / 10).
    amount: int | None = Field(default=None, ge=1, le=100)


@app.post("/api/god/intervene")
async def god_intervene(body: InterveneBody):
    """God intervention (EM-136 + Wave E / EM-184). Targeted kinds
    (`bless_energy` clamped at 100 / `grant_credits`) require agent_id and
    emit `god_intervention` (actor_type 'god', target_id the agent; payload
    carries before/after) — byte-identical pre-E behavior. World-scale
    miracle kinds (`send_rain`/`bountiful_harvest`/`calm_spirits`) require
    agent_id ABSENT and emit the engine's whole event batch: `god_miracle`
    plus, for calm_spirits, any relationship_changed events its trust nudges
    produced (all turn_id null — no action turn ever drains god mutations).
    The response carries `until_tick` for timed kinds. 503 not initialized;
    422 unknown kind, unknown/dead agent, agent_id present/absent mismatch,
    amount outside 1..100, or miracles disabled (the seam's ValueError)."""
    if _world is None or _loop is None:
        raise HTTPException(503, "Not initialized")
    intervene_fn = getattr(_world, "god_intervene", None)
    if intervene_fn is None:
        raise HTTPException(
            503, "engine intervention support (world.god_intervene) not available yet"
        )
    try:
        result = intervene_fn(body.kind, body.agent_id, body.amount)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    events = result if isinstance(result, list) else [result]
    until_tick = None
    for evt in events:
        if not isinstance(evt, dict):
            continue  # pragma: no cover - defensive
        e = dict(evt)
        # The whole batch is god-initiated, outside any agent turn.
        e.setdefault("turn_id", None)
        if e.get("kind") in ("god_intervention", "god_miracle"):
            e.setdefault("actor_type", "god")
        if e.get("kind") == "god_miracle":
            until_tick = (e.get("payload") or {}).get("until_tick")
        _loop._emit_event(e)
        # Wave E QE fix — feed the batch to the agent runtime exactly like the
        # turn path does (loop._execute_turn: push_event({**evt, "tick": tick})),
        # so a god_miracle is globally witnessed (memory entry + the ratified 2.0
        # importance weight + background salience) and a blessed/granted agent
        # remembers its god_intervention (target_id witness). Without this, the
        # mutation lands but no agent ever knows it happened.
        if _runtime is not None:
            _runtime.push_event({**e, "tick": _world.tick})
    _loop._broadcast_world_state()
    resp: dict = {"status": "ok"}
    if until_tick is not None:
        resp["until_tick"] = until_tick
    return resp


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
    # Carry the parent run's world params into the fork (the shared restore
    # helper signature-sniffs `params` support, so the contracted 2-arg form
    # keeps working; resume-on-boot uses the same helper with CURRENT params).
    parent_params = None
    try:
        if isinstance(child_cfg.get("world"), dict):
            from ..config.loader import _parse_world
            parent_params, _, _ = _parse_world({"world": child_cfg["world"]})
    except Exception as exc:  # pragma: no cover - defensive
        log.debug("could not derive parent world params for fork: %s", exc)
        parent_params = None
    try:
        new_world = _restore_world_from_snapshot(
            base["state"], parent_params, place_overrides=overrides
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise HTTPException(400, f"invalid fork state/overrides: {exc}")

    # ── Swap: fork is "reset to a computed state". Retire the old loop, keep
    # the SAME repo (one DB = one runs table) and the SAME router (profiles +
    # usage-alert tracker survive); the shared spin-up helper rebuilds
    # runtime + loop around the new world and stamps the lineage run row
    # (config carried from the parent + the forked_from marker,
    # event-log.md v1.3.0 note 4).
    old_loop = _loop
    await _retire_loop(old_loop)

    child_cfg["forked_from"] = body.run_id
    child_cfg["forked_at_tick"] = actual_tick
    new_runtime, new_loop, new_run_id = _spin_up_run_from_world(
        new_world,
        parent_run_id=body.run_id,
        snapshot_tick=actual_tick,
        config_json=json.dumps(child_cfg),
    )

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


def _enrich_profile_colors(events: list[dict]) -> list[dict]:
    """Backfilled events from the event log carry `profile` (the deciding model)
    but NOT `profile_color` — it is not a stored column; only the live WS
    broadcast stamps it (loop._get_profile_color). The live-feed/​inspector model
    chip needs profile_color, so derive it here from `profile` at the backfill
    boundary, making /api/events + /api/replay consistent with the live broadcast
    (otherwise all history renders chip-less — starkly visible across a fork/​
    resume lineage). Idempotent: an event that already has a profile_color (live
    rows) is left untouched; events without a profile (animals/system) are
    untouched and render via the kind-fallback. In place; returns the same list.
    """
    color_for = (
        getattr(_loop, "_get_profile_color_for_profile", None)
        if _loop is not None else None
    )
    if not callable(color_for):
        return events
    for e in events:
        if e.get("profile") and not e.get("profile_color"):
            e["profile_color"] = color_for(e["profile"])
    return events


@app.get("/api/events")
async def get_events(
    run_id: int | None = None,  # query param: scope to a past run (default: active run)
    from_tick: int | None = Query(default=None),
    to_tick: int | None = Query(default=None),
    kinds: str | None = Query(default=None, description="comma-separated kinds"),
    actor_id: str | None = Query(default=None),
    turn_id: str | None = Query(default=None),
    after_seq: int | None = Query(default=None),
    before_seq: int | None = Query(default=None,
                                   description="keyset for order=desc tail pages (seq < before_seq)"),
    limit: int | None = Query(default=None),
    order: str = Query(default="asc"),
    lineage: bool = Query(default=False,
                          description="EM-187/EM-101: include ancestor (pre-fork) events for a forked/resumed run"),
):
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return []
    kind_list = [k for k in kinds.split(",") if k] if kinds else None
    return _enrich_profile_colors(_repo.get_events(
        run_id,
        from_tick=from_tick,
        to_tick=to_tick,
        kinds=kind_list,
        actor_id=actor_id,
        turn_id=turn_id,
        after_seq=after_seq,
        before_seq=before_seq,
        limit=limit,
        order=order,
        lineage=lineage,
    ))


@app.get("/api/events/stats")
async def get_event_stats(run_id: int | None = None, lineage: bool = False):
    """Run-scoped event-log bounds (Wave F / EM-194): {total, max_seq,
    max_tick, min_seq} via a single cheap COUNT/MAX/MIN — sizes the client's
    tail-first backfill. Same ?run_id scoping as GET /api/events (omitted →
    active run; unknown id → 404). `lineage=true` sizes the run plus its
    ancestors' pre-fork slices, matching the lineage backfill. Uninitialized →
    all-zeros, never 500."""
    run_id = _resolve_run_id(run_id)
    if _repo is None or run_id is None:
        return {"total": 0, "max_seq": 0, "max_tick": 0, "min_seq": 0}
    return _repo.get_event_stats(run_id, lineage=lineage)


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
    events = _enrich_profile_colors(
        _repo.get_events(run_id, from_tick=from_tick, to_tick=tick, order="asc")
    )
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

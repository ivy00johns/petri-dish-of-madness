"""
The tick/turn loop. Runs as an asyncio background task.
Coordinates: scheduler → agent runtime → persist → broadcast.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any

from dataclasses import asdict, is_dataclass

from .world import World, AgentState
from ..agents.runtime import AgentRuntime
from ..animals.runtime import AnimalRuntime, _seed_int
from ..persistence.repository import SQLiteRepository
from ..providers.router import Router
from ..config.loader import WorldConfig
from ..imagegen import build_provider

log = logging.getLogger(__name__)

# EM-201 follow-on — the chronicler payload version stamped on EVERY chapter's
# narrator_summary. Bump when the server-computed `chaos` facts shape (or the
# extraction rules) changes so the frontend can detect/upgrade stale chapters.
#   v1 = prose-only chapters (no server-computed facts)
#   v2 = chapters carry payload["chaos"] (cast/quotes/laws/conflicts/deaths/counts)
CHRONICLER_VERSION = 2

# EM-226 network-down grace — while auto-paused for a provider/network outage,
# the pause-wait loop cheaply probes connectivity every this-many polls (~0.5s
# each) and auto-resumes when a model answers, so a transient blip doesn't
# strand the run waiting for a manual restart. Counter-based (no clock reads) so
# replay is unaffected.
_PROVIDER_PROBE_EVERY = 20


def _world_params_json(world_params: object) -> dict:
    """JSON-ready view of WorldParams for the runs config blob.

    Public (non-underscore) attrs only; nested dataclasses (e.g. usage_caps,
    EM-067) are expanded to plain dicts so json.dumps never chokes on a
    dataclass instance."""
    out: dict = {}
    for k in vars(world_params):
        if k.startswith("_"):
            continue
        v = getattr(world_params, k)
        out[k] = asdict(v) if is_dataclass(v) and not isinstance(v, type) else v
    return out


def _run_config_json(config: WorldConfig) -> str:
    """The runs.config_json blob for a new run row. W11a / EM-086: alongside the
    world params it carries the seed agents' {name, profile} so RunRow's
    config_summary can project them without the full config (pre-W11a runs lack
    the agents key; the projection degrades to an empty list). Wave D3 /
    EM-187: it also carries the place ids, so resume-on-boot's compatibility
    guard can compare world-defining geometry (pre-EM-187 rows lack the key;
    the guard falls back to the snapshot's places)."""
    return json.dumps({
        "world": _world_params_json(config.world),
        "agents": [{"name": a.name, "profile": a.profile} for a in config.agents],
        "places": [p.id for p in config.places],
    })

# Random event templates
RANDOM_EVENTS = {
    "windfall": {
        "kind": "random_event",
        "text": "A windfall of resources appears! All agents gain 5 credits.",
        "_effect": lambda world: [
            setattr(a, "credits", a.credits + 5) for a in world.living_agents()
        ],
    },
    "famine": {
        "kind": "random_event",
        "text": "Famine strikes! All agents lose 10 energy.",
        "_effect": lambda world: [
            setattr(a, "energy", max(0.0, a.energy - 10)) for a in world.living_agents()
        ],
    },
    # W11b / EM-083 — blackout is REAL: recharge is disabled at the affected
    # places for world.blackout_ticks (default 10). Applied via
    # world.apply_blackout in inject_random_event (it needs to emit the
    # structure_state_changed events alongside the random_event).
    "blackout": {
        "kind": "random_event",
        "text": "Blackout! The power fails — recharge is disabled at affected places.",
        "_effect": lambda world: None,  # special-cased in inject_random_event
    },
    "festival": {
        "kind": "random_event",
        "text": "Festival! All agents gain 5 energy.",
        "_effect": lambda world: [
            setattr(a, "energy", min(100.0, a.energy + 5)) for a in world.living_agents()
        ],
    },
}


class TickLoop:
    def __init__(
        self,
        world: World,
        runtime: AgentRuntime,
        repo: SQLiteRepository,
        router: Router,
        broadcaster: Callable[[dict], None] | None = None,
        animal_runtime: AnimalRuntime | None = None,
    ):
        self._world = world
        self._runtime = runtime
        self._repo = repo
        self._router = router
        self._broadcaster = broadcaster or (lambda _: None)
        # W8 / EM-064 — the chaos layer. Built from the same world+router if not
        # injected, so existing callers (and the 135 tests) construct unchanged.
        self._animal_runtime = animal_runtime or AnimalRuntime(world, router)
        # Tracks the last tick we ran the animal cadence for, so each animal acts
        # exactly once per `act_every_n_ticks`-aligned tick (idempotent per tick).
        self._last_animal_tick: int = -1
        # True once seed animals have been spawned for the current run, so init_run
        # / the first turn spawn them exactly once.
        self._animals_spawned: bool = False

        self._run_id: int | None = None
        # Correlation id for the turn currently executing. Stamped on every event
        # emitted during a turn so the whole chain shares one turn_id (EM-054).
        # None outside a turn (e.g. API-driven events, random injections).
        self._current_turn_id: str | None = None
        self._task: asyncio.Task | None = None
        self._step_event: asyncio.Event = asyncio.Event()
        self._paused: bool = True
        # Count of explicit single-step requests queued while paused.
        # Each consumed step advances exactly one turn then re-pauses.
        self._pending_steps: int = 0
        # Futures awaiting a queued step's turn to COMPLETE (step_and_wait). FIFO:
        # each consumed step resolves the oldest waiter with the post-turn tick, so
        # the API can return only once the turn has actually advanced.
        self._step_waiters: list[asyncio.Future] = []
        # W8 — the in-flight animal cadence turn, run OFF the agent's critical
        # path so a slow/unreachable animal LLM call never stalls a tick.
        self._animal_task: asyncio.Task | None = None

        # sequence counter for WS messages
        self._seq: int = 0

        # W7 — last world.round we ran the per-round building lifecycle for, so we
        # advance building abandonment + drain governance spawns exactly once per
        # round (not once per turn).
        # EM-275 — DERIVE from the world's current round, not a flat 0. A resumed/
        # forked loop is built around an already-advanced world (round R>0); a flat
        # 0 made the first _advance_round_buildings see `R > 0` and fire an EXTRA
        # per-round pass — including EM-240 advance_crime (notoriety decay / wanted
        # clear) — that the continuous run had already run before the snapshot, an
        # EM-155 fork/resume divergence. At snapshot time _advance_round_buildings
        # always ran BEFORE the save, so `_last_building_round == world.round`;
        # restoring that here reproduces it. A fresh world is round 0 ⇒ still 0.
        self._last_building_round: int = int(getattr(self._world, "round", 0) or 0)

        # EM-067 cap-aware throttle: effective slowdown multiplier applied to the
        # continuous-run sleep. 1.0 = no slowdown. Recomputed each turn from
        # recent llm_call usage ONLY when world.usage_caps.enabled (default OFF).
        self._usage_slowdown: float = 1.0
        # De-dupe usage_sampled emission: last tick a profile was sampled at.
        self._usage_sampled_at: dict[str, int] = {}

        # W9 / EM-070 — agents already warned about crossing the starving
        # threshold (one-shot, re-armed when energy recovers past the threshold).
        self._starving_warned: set[str] = set()
        # W9 / EM-071 — world_extinct has been emitted for this run (one-shot).
        self._extinct_emitted: bool = False

        # EM-226 — auto-pause on a sustained run of provider/network failures
        # (connection down / all lanes exhausted). The streak resets on any turn
        # that reaches a model; the pause event is one-shot, re-armed on recovery
        # or on resume so a restored connection isn't immediately re-paused.
        self._provider_error_streak: int = 0
        self._provider_pause_emitted: bool = False
        self._last_provider_error: str | None = None
        # EM-226 network-down grace — auto-RESUME a provider-error pause once
        # connectivity returns (probe-gated), so a transient outage doesn't
        # strand the run until a manual restart.
        self._auto_paused_for_provider: bool = False
        self._provider_probe_skips: int = 0

        # W11a / EM-094 — Narrator mode. The in-flight narrator call, run OFF the
        # agents' critical path (same pattern as the animal cadence) so a slow /
        # failed narrator LLM call never stalls or delays a tick. _last_narrator
        # _tick guards "at most once per every_n_ticks" — marked when scheduled,
        # so a failed call is simply skipped (no retry) until the next window.
        self._narrator_task: asyncio.Task | None = None
        self._last_narrator_tick: int = -1
        # EM-201 — the on-demand backfill task (chronicle the EXISTING history as
        # chapters). One at a time; cancelled on reset like the narrator task.
        self._chronicle_backfill_task: asyncio.Task | None = None
        # EM-225 — the on-demand DEEP-DIVE task (a richer one-off saga built from
        # MULTI-PASS per-dimension review → synthesis). Distinct from the single-
        # pass backfill; one at a time; cancelled on reset like the others.
        self._chronicle_deepdive_task: asyncio.Task | None = None

        # Wave I / EM-210 — The Atelier: a bounded pool of best-effort PNG-fetch
        # tasks drained from world.pending_image_fetches each turn. The provider is
        # lazy (built on first use; honors EM_IMAGEGEN_MOCK in tests). The semaphore
        # caps in-flight fetches at params.image_gen.max_concurrent — at cap we SKIP
        # (skip-under-load), never queue. In-flight tasks are tracked so reset can
        # cancel them alongside the narrator/animal tasks. The async task EMITS
        # NOTHING (the gallery entry + image_posted are recorded synchronously at
        # turn time); a failed fetch is swallowed and never stalls a tick.
        self._image_provider = None
        self._image_semaphore: asyncio.Semaphore | None = None
        self._image_fetch_tasks: set[asyncio.Task] = set()

        # Wave E / EM-114 — seed the world's birth casting pool (the persona
        # library + the non-mock profile roster). The world has no view of
        # config-side casting state, so the loop — which owns every per-round
        # world hook — injects it once here; the birth check itself runs
        # world-side at the round boundary and its events ride the existing
        # _flush_spawn_events drain.
        self._seed_birth_casting()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _wire_runtime_run_context(self) -> None:
        """EM-222 — push the persisted-event-log repo + active run id into the
        AgentRuntime so its relevance-scored memory retrieval can read full run
        history. Called whenever the loop (re)establishes a run (init_run /
        reset). Guarded getattr: a duck-typed runtime without the seam is left
        untouched (it then degrades to blind recency)."""
        setter = getattr(self._runtime, "set_run_context", None)
        if callable(setter):
            setter(self._repo, self._run_id)

    def _seed_birth_casting(self) -> None:
        """Wave E / EM-114 — inject the birth casting pool into the world:
        the EM-092 persona library (config/personas.yaml, fail-soft []) and
        the router's non-mock profile names in STABLE config order (the
        child-profile load-spread tiebreak). Defensive throughout: casting is
        flavour, never a reason a loop fails to construct."""
        setter = getattr(self._world, "set_birth_casting", None)
        if not callable(setter):
            return
        try:
            from ..config.loader import load_personas
            roster = [
                name for name in self._router.profile_names()
                if getattr(self._router.get_profile(name), "adapter", "") != "mock"
            ]
            setter(load_personas(), roster)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("birth casting seed failed: %s", exc)

    # ──────────────────────────────────────────────────────────────────────────
    # Control API
    # ──────────────────────────────────────────────────────────────────────────

    def _ensure_task(self) -> None:
        """Create the background run task if it isn't already alive."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def start(self) -> None:
        # Drop any stale single-step requests so continuous running can't be
        # poisoned into re-pausing after one turn.
        self._pending_steps = 0
        # EM-226 — resuming clears the provider-failure streak so a just-restored
        # connection isn't immediately re-paused; re-arm the one-shot pause event.
        self._provider_error_streak = 0
        self._provider_pause_emitted = False
        self._auto_paused_for_provider = False
        self._provider_probe_skips = 0
        self._paused = False
        self._world.running = True
        self._step_event.set()
        self._ensure_task()

    def pause(self) -> None:
        self._paused = True
        self._world.running = False
        # Wake the loop so it observes the pause promptly.
        self._step_event.set()

    def step(self) -> None:
        """Advance exactly one turn, even before start() has been called."""
        self._pending_steps += 1
        self._step_event.set()
        # A step must work even when the loop has never been started.
        self._ensure_task()

    async def step_and_wait(self, timeout: float = 5.0) -> int:
        """Queue a single step and await its turn's completion; return the tick
        after the turn ran. Unlike step(), this lets the API return only once the
        turn has actually advanced — deterministic stepping, no polling/race."""
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._step_waiters.append(fut)
        self._pending_steps += 1
        self._step_event.set()
        self._ensure_task()
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            # Turn didn't finish in time: drop the waiter, report the current tick.
            if fut in self._step_waiters:
                self._step_waiters.remove(fut)
            return self._world.tick

    def _resolve_step_waiter(self) -> None:
        """Signal the oldest step_and_wait() caller that its turn completed."""
        while self._step_waiters:
            fut = self._step_waiters.pop(0)
            if not fut.done():
                fut.set_result(self._world.tick)
                return

    def set_speed(self, tick_interval_seconds: float) -> None:
        self._world.tick_interval_seconds = tick_interval_seconds

    def is_running(self) -> bool:
        return not self._paused

    async def reset(self, config: WorldConfig) -> None:
        """Reset world from config. Pauses loop, rebuilds state, starts new DB run."""
        self.pause()
        self._pending_steps = 0
        # Release any step_and_wait() callers so they don't block on the reset.
        while self._step_waiters:
            fut = self._step_waiters.pop(0)
            if not fut.done():
                fut.set_result(self._world.tick)
        # Drop any in-flight animal turn (it references the old world) and AWAIT
        # it so it cannot mutate the half-rebuilt world (audit B2).
        if self._animal_task is not None and not self._animal_task.done():
            self._animal_task.cancel()
            try:
                await self._animal_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("animal task raised during reset: %s", exc)
        self._animal_task = None
        # W11a / EM-094 — drop any in-flight narrator call the same way: it
        # summarizes the OLD run's window and must not emit into the fresh run.
        if self._narrator_task is not None and not self._narrator_task.done():
            self._narrator_task.cancel()
            try:
                await self._narrator_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("narrator task raised during reset: %s", exc)
        self._narrator_task = None
        self._last_narrator_tick = -1
        # EM-201 — drop any in-flight chronicle backfill: it chronicles the OLD
        # run and must not bleed chapters into the fresh run.
        if (
            self._chronicle_backfill_task is not None
            and not self._chronicle_backfill_task.done()
        ):
            self._chronicle_backfill_task.cancel()
            try:
                await self._chronicle_backfill_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("chronicle backfill raised during reset: %s", exc)
        self._chronicle_backfill_task = None
        # EM-225 — drop any in-flight chronicle deep-dive (multi-pass review of the
        # OLD run); like the backfill it must not bleed a saga into the fresh run.
        if (
            self._chronicle_deepdive_task is not None
            and not self._chronicle_deepdive_task.done()
        ):
            self._chronicle_deepdive_task.cancel()
            try:
                await self._chronicle_deepdive_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("chronicle deep-dive raised during reset: %s", exc)
        self._chronicle_deepdive_task = None
        # Wave I / EM-210 — cancel any in-flight image fetches (they write the OLD
        # run's side-artifacts; best-effort, so just cancel + await, swallowing).
        if self._image_fetch_tasks:
            for task in list(self._image_fetch_tasks):
                if not task.done():
                    task.cancel()
            for task in list(self._image_fetch_tasks):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as exc:  # pragma: no cover - defensive
                    log.debug("image fetch raised during reset: %s", exc)
            self._image_fetch_tasks.clear()
        # The semaphore is rebuilt lazily on next drain so a reset honors a new cap.
        self._image_semaphore = None
        # EM-302c — the provider is rebuilt lazily too: the paid-backstop budget
        # is PER RUN (the counter lives on the provider instance), so a fresh
        # run re-arms it (and picks up any config/env change) here.
        self._image_provider = None
        # W9 / EM-073 B2: properly await the cancelled tick task. A tick mid-LLM
        # call (30s timeout) could otherwise keep running and mutate the world we
        # are about to rebuild. (The old `asyncio.shield(asyncio.sleep(0.1))` was
        # a no-op misuse — it neither awaited nor protected the task.)
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("tick task raised during reset: %s", exc)
        self._task = None

        from ..engine.world import World, AgentState, PlaceState, RuleState
        from ..config.loader import AgentConfig, PlaceConfig
        import uuid

        places = [
            PlaceState(
                id=p.id, name=p.name, x=p.x, y=p.y,
                kind=p.kind, description=p.description,
                district=p.district,  # Wave C / EM-147 — optional, additive
                neighborhood_id=p.neighborhood_id,  # EM-123 — optional
                zone_kind=p.zone_kind,              # EM-123 — optional
            )
            for p in config.places
        ]
        agents = [
            AgentState(
                id=f"agent_{a.name.lower()}_{str(uuid.uuid4())[:6]}",
                name=a.name,
                personality=a.personality,
                profile=a.profile,
                location=a.location,
                energy=config.world.starting_energy,
                credits=config.world.starting_credits,
                # Wave D2 / EM-158 — optional per-agent tier from world.yaml.
                cadence_tier=getattr(a, "cadence_tier", "protagonist"),
            )
            for a in config.agents
        ]

        # Update world in-place
        self._world.params = config.world
        self._world.places = {p.id: p for p in places}
        self._world.agents = {a.id: a for a in agents}
        self._world.rules = {}
        # W7 — clear buildings + governance-spawn outbox on reset.
        self._world.buildings = {}
        self._world.pending_spawn_events = []
        # W8 — clear animals; the seed critters are re-spawned below.
        self._world.animals = {}
        # W11b — clear the billboard for the fresh run.
        self._world.billboard = []
        # Wave E / EM-120 — clear factions: stale clusters from the prior run
        # reference replaced agent ids and would emit spurious dissolutions at
        # the fresh run's first round boundary. (No drain change — faction
        # events ride the existing pending_spawn_events outbox, cleared above.)
        self._world.factions = {}
        # Wave E / EM-184 — clear active miracles: tick resets to 0 below, so
        # a stale entry's until_tick would keep its buff alive deep into the
        # fresh run (and its expiry would emit a spurious miracle_expired).
        self._world.active_miracles = []
        self._world.tick = 0
        self._world.day = 0
        self._world.round = 0
        self._world.running = False
        self._world.tick_interval_seconds = config.world.tick_interval_seconds
        self._world._turn_order = sorted(self._world.agents.keys())
        self._world._turn_index = 0
        self._world._round_start = True
        self._last_building_round = 0

        # W11b / EM-098 — regenerate the procgen town for the fresh run when
        # world.procgen.enabled (no-op for the hand-authored town).
        self._world.apply_procgen()

        # EM-227 — seed each agent's STARTING skills from a deterministic
        # per-archetype spread so the cast begins differentiated (and is NOT all
        # locked out of the gated high-value actions). A no-op when no skill
        # library/archetypes are configured (pre-EM-227 / golden worlds).
        seed_all_skills = getattr(self._world, "seed_all_skills", None)
        if callable(seed_all_skills):
            seed_all_skills()

        # EM-311 — seed each agent's uniform STARTING charter (a no-op unless
        # world.charters.enabled), so the divergence experiment begins from a
        # common baseline the agents then rewrite for themselves.
        seed_all_charters = getattr(self._world, "seed_all_charters", None)
        if callable(seed_all_charters):
            seed_all_charters()

        # Clear agent memories + W11b cognition state (commitments, importance
        # accumulators, pending overheard lines).
        reset_state = getattr(self._runtime, "reset_state", None)
        if callable(reset_state):
            reset_state()
        else:  # pragma: no cover - legacy runtime
            self._runtime._memory.clear()

        # W9 — reset per-run survival/extinction tracking (EM-070/071).
        self._starving_warned.clear()
        self._extinct_emitted = False

        # Flush the router decision cache (audit B12): prior-run cached decisions
        # must never serve into a fresh run. No-op if the router lacks the cache.
        clear_cache = getattr(self._router, "clear_cache", None)
        if callable(clear_cache):
            clear_cache()

        # New DB run
        cfg_json = _run_config_json(config)
        if self._run_id:
            try:
                self._repo.end_run(self._run_id)
            except Exception:
                pass
        self._run_id = self._repo.start_run(cfg_json)
        # EM-222 — hand the runtime the repo + active run so relevance-scored
        # memory retrieval can read the persisted event log of THIS run.
        self._wire_runtime_run_context()
        self._repo.save_places(self._run_id, places)
        for agent in agents:
            self._repo.save_agent(self._run_id, agent, 0)

        # W8 — re-spawn the seed critters for the fresh run (emits animal_spawned).
        self._animals_spawned = False
        self._last_animal_tick = -1
        self._spawn_seed_animals(config)

        # Snapshot at tick 0 of the fresh run (structural change: reset).
        self._save_snapshot(0)

        # Broadcast new state
        self._broadcast_world_state()

    def init_run(self, config: WorldConfig) -> None:
        """One-time initialization (called at startup, not async)."""
        cfg_json = _run_config_json(config)
        self._run_id = self._repo.start_run(cfg_json)
        # EM-222 — hand the runtime the repo + active run so relevance-scored
        # memory retrieval can read the persisted event log of THIS run.
        self._wire_runtime_run_context()
        # EM-227 — seed each agent's STARTING skills from a deterministic
        # per-archetype spread BEFORE the tick-0 save, so the persisted base run
        # carries the profession gradient. A no-op without a configured library.
        seed_all_skills = getattr(self._world, "seed_all_skills", None)
        if callable(seed_all_skills):
            seed_all_skills()
        # EM-311 — seed each agent's uniform STARTING charter BEFORE the tick-0
        # save (a no-op unless world.charters.enabled), so the persisted base run
        # carries the common baseline.
        seed_all_charters = getattr(self._world, "seed_all_charters", None)
        if callable(seed_all_charters):
            seed_all_charters()
        self._repo.save_places(self._run_id, list(self._world.places.values()))
        for agent in self._world.agents.values():
            self._repo.save_agent(self._run_id, agent, 0)

        # W8 — spawn the seed critters (cat + dog) when animals.enabled, emitting
        # animal_spawned. Before the tick-0 snapshot so they ride the replay base.
        self._animals_spawned = False
        self._last_animal_tick = -1
        self._spawn_seed_animals(config)

        # Snapshot at tick 0 so replay has a base for the very first ticks.
        self._save_snapshot(0)

    # ──────────────────────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        log.info("TickLoop started")
        while True:
            # Wait until either continuously running, or a step is queued.
            while self._paused and self._pending_steps <= 0:
                self._step_event.clear()
                try:
                    await asyncio.wait_for(self._step_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass
                # EM-226 network-down grace: if we auto-paused for a provider/
                # network outage, probe connectivity and auto-resume when it's
                # back (breaks this wait by clearing self._paused).
                await self._maybe_auto_resume()

            # Decide whether this iteration is a one-shot step or a continuous turn.
            # A queued step always advances exactly one turn (even while running);
            # otherwise we advance because we're in continuous-run mode.
            step_only = False
            consumed_step = False
            if self._pending_steps > 0:
                self._pending_steps -= 1
                consumed_step = True
                # Only treat as a "stop after one turn" step when not running.
                step_only = self._paused
            self._step_event.clear()

            agent = self._world.next_agent()
            if agent is None:
                if consumed_step:
                    self._resolve_step_waiter()  # don't hang the caller
                await asyncio.sleep(0.5)
                continue

            if not agent.alive:
                if consumed_step:
                    self._resolve_step_waiter()
                continue

            try:
                await self._execute_turn(agent)
            except asyncio.CancelledError:
                # reset/fork teardown cancels the task through this await —
                # cancellation MUST propagate, never turn into a pause.
                raise
            except Exception as exc:
                # An unhandled turn exception used to kill this task silently
                # while /api/health kept reporting running=true (the world just
                # froze). Mirror the EM-226 auto-pause instead: log it, emit a
                # best-effort world_paused {reason: internal_error}, pause, and
                # broadcast — the task stays alive so resume/step still work.
                log.exception(
                    "turn crashed (agent=%s tick=%s) — auto-pausing",
                    agent.id, self._world.tick,
                )
                self._pause_for_internal_error(agent, exc)

            if consumed_step:
                self._resolve_step_waiter()

            if step_only:
                # Single-step while paused: advance one turn, stay paused.
                self._paused = True
                self._world.running = False
            elif not self._paused:
                # EM-067: cap-aware throttle lengthens the effective interval when
                # a profile nears its usage cap (1.0 = no slowdown / caps disabled).
                interval = self._world.tick_interval_seconds * self._usage_slowdown
                await asyncio.sleep(max(0.01, interval))

    async def _execute_turn(self, agent: AgentState) -> None:
        """Execute one agent turn: energy decay → model call → apply → persist → broadcast.

        Emits the linked decision-trace chain (EM-054): every event this turn —
        turn_start, the perceived/memory/llm/reasoning/action_chosen spans, the
        domain action event(s), action_resolved, and any death — shares one
        turn_id minted here.
        """
        world = self._world
        tick = world.tick
        run_id = self._run_id or 1

        # Mint the turn correlation id; _emit_event stamps it on ALL events below.
        import uuid
        turn_id = uuid.uuid4().hex
        self._current_turn_id = turn_id

        profile_name = self._router.profile_name_for(agent.id, agent.profile)
        profile_color = self._get_profile_color(agent)

        # W7 — once-per-round building lifecycle: advance abandonment + flush any
        # governance-spawn events queued by an admit_agent rule that just passed.
        # Emitted as standalone system events (no turn_id) before this turn's chain.
        self._advance_round_buildings()

        # W11b / EM-083 — restore power at places whose blackout window elapsed
        # (standalone system events, outside this turn's chain).
        try:
            for evt in self._world.expire_blackouts():
                evt.setdefault("turn_id", None)
                self._emit_event(evt)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("blackout expiry failed: %s", exc)

        # Wave E / EM-184 — expire timed god miracles in the SAME per-tick
        # path (miracle_expired, standalone system events, turn_id null).
        try:
            for evt in self._world.expire_miracles():
                evt.setdefault("turn_id", None)
                self._emit_event(evt)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("miracle expiry failed: %s", exc)

        # EM-245 (S3b) — advance an active master-plan morph (deterministic k
        # edges/tick, standalone system events, turn_id null). An INACTIVE plan
        # (None) is a no-op, so existing runs stay byte-identical.
        try:
            for evt in self._world.step_master_plan_morph():
                evt.setdefault("turn_id", None)
                self._emit_event(evt)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("master-plan morph step failed: %s", exc)

        # W8 — slow-cadence chaos layer: on an `act_every_n_ticks`-aligned tick,
        # each living animal takes ONE animal turn (mostly zero-LLM reflex). It is
        # SCHEDULED as a background task (not awaited) so a slow/unreachable animal
        # LLM call never blocks this agent turn. Its events land asynchronously,
        # stamped with the tick they actually resolve on.
        self._maybe_schedule_animals()

        # Wave H2 / EM-207 — AMBIENT spawning: every `ambient_spawn_every` ticks the
        # menagerie may grow on its own (ONE random catalog critter at a random
        # place), with a DETERMINISTIC seeded roll (replay-safe) and ONLY while
        # under max_population. OFF by default (ambient_spawn_every:0). Synchronous +
        # cheap (no LLM) — it just mutates world state + emits one event.
        self._maybe_schedule_ambient_animal()

        # W11a / EM-094 — Narrator mode (OFF by default): on an every_n_ticks-
        # aligned tick, schedule ONE recap LLM call as a background task — same
        # off-critical-path pattern as the animals. Disabled = zero calls.
        self._maybe_schedule_narrator()

        try:
            # 1. turn_start (now persisted + carries turn_id)
            self._emit_event({
                "kind": "turn_start",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"Turn {tick}: {agent.name}'s turn.",
                "payload": {
                    "turn_id": turn_id,
                    "agent_id": agent.id,
                    "profile": profile_name,
                    "location": agent.location,
                    "energy": round(agent.energy, 2),
                    "credits": agent.credits,
                    "day": world.day,
                    # Wave D2 / EM-166 — additive observability keys.
                    "cadence_tier": getattr(agent, "cadence_tier", "protagonist"),
                    "reflex_streak": int(getattr(agent, "reflex_streak", 0)),
                },
            })

            # Energy decay
            world.apply_energy_decay(agent)
            # EM-229 — knowledge + influence needs decay alongside energy (these
            # never kill; a low need only biases the prompt via a salience gate).
            world.apply_needs_decay(agent)

            # Run model turn (returns domain event(s) + a `_trace` structure)
            raw_result = await self._runtime.run_turn(agent)
            trace = raw_result.get("_trace", {}) if isinstance(raw_result, dict) else {}

            # EM-226 — track sustained provider/network failures (connection down
            # or every lane exhausted) so the loop can auto-pause instead of
            # burning ticks on idle fallbacks. Any turn that reached a model — a
            # success OR a content parse failure — breaks the streak and re-arms
            # the one-shot pause event.
            provider_err = self._provider_error_reason(raw_result)
            if provider_err is not None:
                self._provider_error_streak += 1
                self._last_provider_error = provider_err
            else:
                self._provider_error_streak = 0
                self._provider_pause_emitted = False

            # 2-6. Decision-trace spans, in order, all under this turn_id.
            self._emit_trace_chain(agent, profile_name, profile_color, trace)

            # Handle multi-event results (e.g., vote + rule_passed)
            if "_multi" in raw_result:
                events_to_emit = raw_result["_multi"]
            else:
                events_to_emit = [raw_result]

            # 7 (domain action events) — emitted between action_chosen and action_resolved.
            # Wave D2 / EM-166 — every turn event carries the acting agent's
            # cadence_tier (additive payload key; reflex turns already carry
            # payload.reflex from the runtime).
            tier = getattr(agent, "cadence_tier", "protagonist")
            for evt in events_to_emit:
                evt.setdefault("payload", {}).setdefault("cadence_tier", tier)
                self._emit_event(evt)

            # 8. action_resolved span
            resolved = trace.get("resolved", {}) if isinstance(trace, dict) else {}
            self._emit_event({
                "kind": "action_resolved",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"{agent.name}'s action resolved ({resolved.get('outcome', 'ok')}).",
                "payload": {
                    "outcome": resolved.get("outcome", "ok"),
                    "state_deltas": resolved.get("state_deltas", {}),
                    # Wave D2 / EM-159 — a reflex turn never routed anywhere.
                    "routed_via": (
                        None if trace.get("reflex")
                        else self._router.last_routed_via(profile_name)
                    ),
                    "cadence_tier": tier,  # Wave D2 / EM-166 — additive
                },
            })

            # Update mood from last event if set
            if raw_result.get("mood"):
                agent.mood = raw_result["mood"][:40]

            # Persist agent state
            self._repo.save_agent(run_id, agent, tick)

            # Save rules if any changed
            for rule in world.rules.values():
                self._repo.save_rule(run_id, rule)

            # Death check
            died = world.check_death(agent)
            if died:
                death_evt = {
                    "kind": "agent_died",
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "text": f"{agent.name} has died (energy exhausted).",
                    "payload": {"energy": agent.energy, "tick": tick},
                }
                self._emit_event(death_evt)
                self._repo.save_agent(run_id, agent, tick)
                # EM-126 — inheritance: pass the deceased's estate (credits, and
                # optionally relationships/grudges) down its EM-114 lineage to a
                # deterministic heir, emitting an `inherited` event. Gated behind
                # world.generations.enabled: OFF (the default) ⇒ None ⇒ nothing
                # moves (byte-identical pre-EM-126 death path). On a transfer the
                # heir's persisted state changes, so re-save it too.
                inherit_evt = world.apply_inheritance(agent)
                if inherit_evt is not None:
                    self._emit_event(inherit_evt)
                    heir_id = inherit_evt.get("payload", {}).get("heir_id")
                    heir = world.agents.get(heir_id) if heir_id else None
                    if heir is not None:
                        self._repo.save_agent(run_id, heir, tick)

            # W9 / EM-070 — surface survival pressure (agent_starving events).
            self._emit_starving_events(agent, profile_name, profile_color, died)

            # W9 / EM-071 — extinction moment: the last living human agent just
            # died (animals alone do not keep the run "alive"). Emit the event
            # now (stamped with the death tick); the pause happens AFTER the
            # end-of-turn broadcast below.
            extinct = died and not world.living_agents()
            if extinct:
                self._emit_extinction(agent, tick)

            # Push events to agent memories
            for evt in events_to_emit:
                self._runtime.push_event({**evt, "tick": tick})

            # Wave I / EM-210 — drain any image-fetch requests this turn parked
            # (create_image already recorded the gallery entry + emitted
            # image_posted synchronously above; this only starts the best-effort
            # PNG fetches). Bounded + skip-under-load; emits NOTHING.
            self._drain_image_fetches()

            # Periodic snapshot to bound replay cost (EM-054 §5). W9 / EM-073 B8:
            # saved BEFORE the tick advances and labeled with the CURRENT tick, so
            # a snapshot at tick S is the state AFTER all tick-S events (event-log
            # v1.1.0 §3 — replay folds strictly-left: S < e.tick <= T). The tick-0
            # init/reset snapshot is re-saved here after the first turn (INSERT OR
            # REPLACE keeps it idempotent) so the boundary holds at tick 0 too.
            interval = getattr(world.params, "snapshot_interval_ticks", 25)
            if interval and tick % interval == 0:
                self._save_snapshot(tick)

            # Advance tick
            world.tick += 1
            world.day = world.tick // world.params.turns_per_day

            # EM-067 cap-aware throttle (config-gated, DEFAULT OFF). Reads recent
            # llm_call usage, may emit usage_sampled + set the slowdown factor.
            self._apply_usage_caps(run_id)

            # Broadcast updated world state
            self._broadcast_world_state()

            # W9 / EM-071 — pause only AFTER world_extinct has been emitted and
            # the world state broadcast; the final broadcast carries running=False.
            if extinct and bool(getattr(world.params, "auto_pause_on_extinction", True)):
                self.pause()
                self._broadcast_world_state()

            # EM-226 — sustained provider/network outage: a run of turns in a row
            # all idled on provider_error (connection down or all lanes
            # exhausted/rate-limited). Pause (after the broadcast above) so the run
            # stops burning ticks; resume once connectivity / limits recover.
            threshold = int(getattr(world.params, "provider_error_pause_threshold", 8) or 8)
            if (
                self._provider_error_streak >= threshold
                and bool(getattr(world.params, "auto_pause_on_provider_errors", True))
                and not self._provider_pause_emitted
            ):
                self._emit_provider_pause(self._provider_error_streak, tick)
                self._auto_paused_for_provider = True
                self._provider_probe_skips = 0
                self.pause()
                self._broadcast_world_state()
        finally:
            self._current_turn_id = None

    # ──────────────────────────────────────────────────────────────────────────
    # W8 / EM-064 — animal spawning + slow-cadence scheduling
    # ──────────────────────────────────────────────────────────────────────────

    def _animals_cfg(self) -> Any:
        return getattr(self._world.params, "animals", None)

    def _spawn_seed_animals(self, config: WorldConfig) -> None:
        """Spawn the seed critters (top-level `animals:` list) when
        world.params.animals.enabled. Emits an `animal_spawned`
        (actor_type 'animal') per critter through the normal pipeline + broadcasts a
        fresh world_state so the cat + dog appear immediately. Idempotent: guarded
        by `_animals_spawned` so init + the first round don't double-spawn."""
        cfg = self._animals_cfg()
        if cfg is None or not getattr(cfg, "enabled", False):
            self._animals_spawned = True
            return
        seeds = getattr(config, "animals", None) or []
        # Wave D3 / EM-187 (contract §B4.4) — a RESUMED world's snapshot may
        # already carry the seed critters: never spawn a duplicate (matched on
        # species+name); only critters the snapshot lacks are spawned. Fresh
        # init/reset worlds start with an empty animals dict, so this is a
        # no-op for them.
        existing = {
            (a.species, a.name) for a in self._world.animals.values()
        }
        spawned_any = False
        for seed in seeds:
            if (seed.species, seed.name) in existing:
                continue
            try:
                animal = self._world.spawn_animal(
                    species=seed.species,
                    name=seed.name,
                    location=seed.location,
                    personality=getattr(seed, "personality", ""),
                )
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("animal spawn failed for %r: %s", getattr(seed, "name", "?"), exc)
                continue
            spawned_any = True
            self._emit_event({
                "kind": "animal_spawned",
                "actor_id": animal.id,
                "actor_type": "animal",
                "text": f"{animal.name} the {animal.species} roams into the world.",
                "payload": {
                    "animal_id": animal.id,
                    "species": animal.species,
                    "name": animal.name,
                    "location": animal.location,
                },
            })
        self._animals_spawned = True
        if spawned_any:
            self._broadcast_world_state()

    def _maybe_schedule_animals(self) -> None:
        """Schedule the slow-cadence animal turn OFF the agent's critical path.

        Every world.params.animals.act_every_n_ticks ticks (idempotent per tick),
        fire a background task so an animal's LLM call never blocks the agent
        turn. If a previous animal batch is still in flight we SKIP this cadence —
        best-effort chaos: we don't queue animal turns up behind a slow provider.
        NEVER raises (callable from the hot path)."""
        cfg = self._animals_cfg()
        if cfg is None or not getattr(cfg, "enabled", False):
            return
        tick = self._world.tick
        if tick == self._last_animal_tick:
            return
        every = max(1, int(getattr(cfg, "act_every_n_ticks", 3)))
        if tick % every != 0:
            return
        if self._animal_task is not None and not self._animal_task.done():
            return  # don't pile up behind an in-flight (possibly slow) animal turn
        self._last_animal_tick = tick
        self._animal_task = asyncio.create_task(self._run_animal_turns(tick))

    async def _run_animal_turns(self, tick: int) -> None:
        """Body of an animal cadence turn (runs as a background task). Each LIVING
        animal takes ONE turn via AnimalRuntime.act; its event(s) are emitted
        through the existing _emit_event path (already stamped actor_type 'animal'
        + is_chaotic) and pushed to agent memories so nearby agents witness the
        chaos. NEVER crashes the loop — a per-animal failure is logged and skipped."""
        animals = self._world.living_animals()
        if not animals:
            return
        acted = False
        import uuid
        # Stable order so replay is reproducible within a batch.
        for animal in sorted(animals, key=lambda a: a.id):
            # W9 / EM-073 B1 (event-log v1.1.0 §2): every animal turn gets its
            # OWN turn_id. This background task runs concurrently with agent
            # turns, so _emit_event's default (`self._current_turn_id`) would
            # stamp the in-flight AGENT's correlation id onto animal events and
            # pollute get_turn_trace(agent_turn_id).
            animal_turn_id = uuid.uuid4().hex
            try:
                events = await self._animal_runtime.act(animal, self._world, tick)
            except Exception as exc:  # pragma: no cover - defensive; act() shouldn't raise
                log.warning("animal act failed for %s: %s", animal.id, exc)
                continue
            for evt in events or []:
                evt.setdefault("turn_id", animal_turn_id)
                self._emit_event(evt)
                self._runtime.push_event({**evt, "tick": tick})
            acted = True
        if acted:
            self._broadcast_world_state()

    def _ambient_seed(self, tick: int) -> int:
        """Wave H2 / EM-207 — the DETERMINISTIC seed for the ambient roll/spawn at
        `tick`: a stable hash of (run id + tick), the SAME replay-safe pattern the
        animal activity-roll uses (no wall-clock, no RNG). A fixed (run, tick)
        always yields the same roll AND the same species/place."""
        return _seed_int("ambient", self._run_id or 0, tick)

    def _maybe_schedule_ambient_animal(self) -> None:
        """Wave H2 / EM-207 — let the menagerie grow on its own.

        Every `animals.ambient_spawn_every` ticks (0 = OFF), with a DETERMINISTIC
        seeded roll against `ambient_spawn_chance`, spawn ONE random catalog species
        at a random existing place — ONLY while living animals < max_population.
        Emits `animal_spawned` with payload.method 'ambient' + broadcasts a fresh
        world_state so the new critter appears immediately. Skips SILENTLY at the
        cap (catches the spawn_animal ValueError). NEVER raises (hot-path safe)."""
        cfg = self._animals_cfg()
        if cfg is None or not getattr(cfg, "enabled", False):
            return
        every = int(getattr(cfg, "ambient_spawn_every", 0) or 0)
        if every <= 0:
            return  # ambient spawning disabled (the backward-compatible default)
        tick = self._world.tick
        if tick <= 0 or tick % every != 0:
            return
        # Cap pre-check (free-scale): never even roll when the menagerie is full.
        max_population = int(getattr(cfg, "max_population", 0) or 0)
        if max_population > 0 and len(self._world.living_animals()) >= max_population:
            return
        seed = self._ambient_seed(tick)
        try:
            chance = float(getattr(cfg, "ambient_spawn_chance", 0.0) or 0.0)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            chance = 0.0
        if chance <= 0.0:
            return
        # Map the seed into [0, 1) deterministically (mirrors the animal roll).
        if (seed % 1_000_000) / 1_000_000 >= min(1.0, chance):
            return  # the roll didn't land this window
        try:
            animal = self._world.spawn_random_animal(seed)
        except ValueError:
            return  # raced the cap — skip silently (best-effort ambient chaos)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("ambient animal spawn failed: %s", exc)
            return
        if animal is None:
            return  # no place to put it
        self._emit_event({
            "kind": "animal_spawned",
            "actor_id": animal.id,
            "actor_type": "animal",
            "turn_id": None,  # standalone system event, outside the agent turn chain
            "text": f"{animal.name} the {animal.species} wanders in.",
            "payload": {
                "animal_id": animal.id,
                "species": animal.species,
                "name": animal.name,
                "location": animal.location,
                "method": "ambient",
            },
        })
        self._runtime.push_event({
            "kind": "animal_spawned",
            "actor_id": animal.id,
            "actor_type": "animal",
            "tick": tick,
            "payload": {"species": animal.species, "name": animal.name,
                        "location": animal.location, "method": "ambient"},
        })
        self._broadcast_world_state()

    # ──────────────────────────────────────────────────────────────────────────
    # W11a / EM-094 — Narrator mode (event-log.md v1.2.0 note 1)
    # ──────────────────────────────────────────────────────────────────────────

    # The event kinds the narrator digest is built from: deaths, governance,
    # projects/structures, conflicts, spawns, world events — NOT raw event dumps.
    _NARRATOR_DIGEST_KINDS = (
        "agent_died", "animal_died", "world_extinct", "agent_starving",
        "rule_proposed", "rule_passed", "rule_rejected", "town_named",
        "project_proposed", "project_funded", "project_built",
        "building_operational", "structure_state_changed",
        # EM-201 — a broken promise IS a clash: the chronicle facts builder counts
        # commitment_lapsed as a conflict, so it must survive the digest-kind
        # whitelist or the server payload would undercount clashes vs. the
        # frontend's full-history reconstruction.
        "conflict", "commitment_lapsed",
        "agent_spawned", "animal_spawned", "random_event",
        # EM-201 — the chronicle needs the DRAMA, so speech + reflections are in
        # the digest now (the thin EM-094 recap deliberately excluded them).
        "agent_speech", "reflection",
    )

    def _narrator_cfg(self) -> Any:
        return getattr(self._world.params, "narrator", None)

    def _maybe_schedule_narrator(self) -> None:
        """Schedule the narrator recap OFF the agents' critical path (EM-094).

        At most ONE call per `world.narrator.every_n_ticks` window, fired as a
        background task on the aligned tick — exactly the animal-cadence pattern,
        so a slow/failed narrator LLM call never stalls or delays a tick. The
        window is marked consumed when SCHEDULED, so a failed call emits nothing
        and is never retried. Disabled (default) / unavailable profile = zero
        calls. NEVER raises (callable from the hot path)."""
        cfg = self._narrator_cfg()
        if cfg is None or not getattr(cfg, "enabled", False):
            return
        tick = self._world.tick
        every = max(1, int(getattr(cfg, "every_n_ticks", 50)))
        if tick <= 0 or tick % every != 0:
            return
        if tick == self._last_narrator_tick:
            return
        if self._narrator_task is not None and not self._narrator_task.done():
            return  # an earlier window's call is still in flight — skip, no queueing
        profile_name = str(getattr(cfg, "model_profile", "") or "")
        profile = self._router.get_profile(profile_name)
        try:
            available = bool(profile.available()) if profile is not None else False
        except Exception:  # pragma: no cover - defensive
            available = False
        if not available:
            return  # free-scale guarantee: never route to a missing/keyless profile
        self._last_narrator_tick = tick
        from_tick = max(0, tick - every)
        self._narrator_task = asyncio.create_task(
            self._run_narrator(from_tick, tick, profile_name)
        )

    def _narrator_window_rows(self, from_tick: int, to_tick: int) -> list[dict]:
        """EM-201 — the window's digest-kind event rows, queried ONCE (lineage so
        a backfilled window finds events that live in an ANCESTOR run). Shared by
        the digest TEXT and the server-computed `chaos` facts so a chapter never
        double-queries the same window. Returns [] on any query failure."""
        run_id = self._run_id or 1
        try:
            return self._repo.get_events(
                run_id,
                from_tick=from_tick,
                to_tick=to_tick,
                kinds=list(self._NARRATOR_DIGEST_KINDS),
                order="asc",
                # EM-201/EM-187 — chronicle across the resume-on-boot fork so a
                # backfilled window finds its events even when they live in an
                # ANCESTOR run (the tick range still scopes the window).
                lineage=True,
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("chronicle digest query failed: %s", exc)
            return []

    def _narrator_digest(self, from_tick: int, to_tick: int) -> str:
        """EM-201 — the CHAPTER digest for the chronicler prompt: the window's
        events queried once, then handed to the pure `_build_chronicle_digest`
        builder (memorable lines + laws + cast + conflict). Free-scale: bounded,
        never a raw event dump."""
        rows = self._narrator_window_rows(from_tick, to_tick)
        living = [a.name for a in self._world.living_agents()]
        town = getattr(self._world, "town_name", "") or ""
        return self._build_chronicle_digest(rows, living, from_tick, to_tick, town)

    # EM-201 follow-on — the speech verbs the speaker() / said() extraction keys
    # off. Backend AND frontend MUST agree on this list (see the contract).
    _SPEECH_VERBS = (
        "says", "mutters", "shouts", "whispers", "proclaims", "insults",
        "declares", "asks", "muses", "snaps", "warns", "grumbles", "sighs",
        "laughs",
    )
    _SPEAKER_RE = re.compile(
        r"^\s*(.+?)\s+(?:" + "|".join(_SPEECH_VERBS) + r")\b",
        re.IGNORECASE,
    )
    # "Name verb[,:]" prefix stripped off ev.text when payload.said is absent.
    _SAID_PREFIX_RE = re.compile(
        r"^\s*.+?\s+(?:" + "|".join(_SPEECH_VERBS) + r")[,:]?\s*",
        re.IGNORECASE,
    )

    @classmethod
    def _chronicle_speaker(cls, ev: dict) -> str:
        """EM-201 follow-on — the speaker of an event. Match the leading text
        before a speech verb in ev.text; else ev.actor_id; else '—'. Backend and
        frontend MUST agree exactly (see the contract)."""
        text = (ev.get("text") or "").strip()
        m = cls._SPEAKER_RE.match(text)
        if m:
            name = m.group(1).strip().strip('"“”\'')
            if name:
                return name
        actor = (ev.get("actor_id") or "").strip()
        return actor or "—"

    @classmethod
    def _chronicle_said(cls, ev: dict) -> str:
        """EM-201 follow-on — the spoken words of an event: payload.said when
        present, else ev.text with its leading 'Name verb[,:]' prefix stripped.
        Backend and frontend MUST agree exactly (see the contract)."""
        said = ((ev.get("payload") or {}).get("said") or "").strip()
        if said:
            return said
        text = (ev.get("text") or "").strip()
        return cls._SAID_PREFIX_RE.sub("", text, count=1).strip().strip('"“”')

    @classmethod
    def _build_chronicle_facts(
        cls, rows: list[dict], from_tick: int, to_tick: int
    ) -> dict:
        """EM-201 follow-on — PURE: the server-computed `chaos` facts for one
        window, built from the rows it is GIVEN (queries nothing). Returns the
        EXACT contract shape: cast/quotes/laws/conflicts/deaths/counts, reusing
        the speaker/said extraction. A quiet window yields empty lists + zero
        counts (never a crash)."""
        speech_rows: list[dict] = []
        laws: list[str] = []
        conflicts: list[str] = []
        deaths: list[str] = []
        for ev in rows:
            kind = ev.get("kind") or "?"
            text = (ev.get("text") or "").strip()
            if kind == "agent_speech":
                speech_rows.append(ev)
            elif kind in ("rule_passed", "town_named"):
                if text:
                    laws.append(text)
            elif kind in ("conflict", "commitment_lapsed"):
                if text:
                    conflicts.append(text)
            elif kind == "agent_died":
                if text:
                    deaths.append(text)
        # cast: distinct speakers in FIRST-SEEN order, cap 8.
        cast: list[str] = []
        for ev in speech_rows:
            sp = cls._chronicle_speaker(ev)
            if sp not in cast:
                cast.append(sp)
        cast = cast[:8]
        # quotes: agent_speech rows by len(said) desc, top 3.
        quoted = [
            {"speaker": cls._chronicle_speaker(ev), "said": cls._chronicle_said(ev)}
            for ev in speech_rows
        ]
        quoted.sort(key=lambda q: len(q["said"]), reverse=True)
        quotes = quoted[:3]
        return {
            "cast": cast,
            "quotes": quotes,
            "laws": laws[:5],
            "conflicts": conflicts[:5],
            "deaths": deaths[:5],
            "counts": {
                "spoken": len(speech_rows),
                "laws": len(laws),
                "clashes": len(conflicts),
                "deaths": len(deaths),
            },
        }

    @staticmethod
    def _build_chronicle_digest(
        rows: list[dict],
        living_names: list[str],
        from_tick: int,
        to_tick: int,
        town_name: str = "",
    ) -> str:
        """EM-201 — build the rich chapter digest from a window's event rows.
        PURE + unit-testable. Surfaces the drama the thin EM-094 recap missed:
        the most MEMORABLE spoken lines (longest = richest), the LAWS/namings
        passed, the living CAST, and open CONFLICT — then a tail of other
        notable moments for grounding. A quiet window still yields a valid,
        charming digest (never a crash)."""
        counts: dict[str, int] = {}
        speech: list[tuple[int, str]] = []
        laws: list[str] = []
        drama: list[str] = []
        for ev in rows:
            kind = ev.get("kind") or "?"
            counts[kind] = counts.get(kind, 0) + 1
            text = (ev.get("text") or "").strip()
            if kind == "agent_speech":
                said = ((ev.get("payload") or {}).get("said") or "").strip() or text
                if said:
                    speech.append((len(said), said[:300]))
            elif kind in ("rule_passed", "town_named") and text:
                laws.append(text[:160])
            elif kind == "conflict" and text:
                drama.append(text[:120])
        cast = ", ".join(living_names) or "nobody"
        header = ", ".join(f"{k} x{n}" for k, n in sorted(counts.items())) or "a quiet stretch"
        speech.sort(key=lambda s: s[0], reverse=True)
        quotes = "\n".join(f"  · {q}" for _, q in speech[:6]) or "  (no one spoke)"
        law_block = "\n".join(f"  · {law}" for law in laws[:8]) or "  (no laws passed)"
        drama_block = "\n".join(f"  · {d}" for d in drama[:6]) or "  (no open conflict)"
        moments: list[str] = []
        for ev in rows[-12:]:
            if ev.get("kind") in ("agent_speech", "conflict"):
                continue  # already surfaced above
            t = (ev.get("text") or "").strip()
            if t:
                moments.append(f"  [tick {ev.get('tick')}] {t[:120]}")
        moments_block = "\n".join(moments[-8:]) or "  (a quiet stretch)"
        town = town_name.strip() if isinstance(town_name, str) else ""
        return (
            f"Window: ticks {from_tick}–{to_tick}. The town: {town or 'still unnamed'}. "
            f"The cast: {cast}.\n"
            f"Event counts: {header}.\n\n"
            f"MEMORABLE LINES (their actual words):\n{quotes}\n\n"
            f"LAWS / NAMINGS this stretch:\n{law_block}\n\n"
            f"CONFLICT:\n{drama_block}\n\n"
            f"OTHER NOTABLE MOMENTS:\n{moments_block}"
        )

    def _previous_chapter(self) -> str:
        """EM-201 — text of the most recent chapter (narrator_summary), so the
        chronicler can continue the saga instead of writing disconnected
        recaps. Empty on the first chapter or any query failure."""
        try:
            rows = self._repo.get_events(
                self._run_id or 1, kinds=["narrator_summary"],
                order="desc", limit=1, lineage=True,  # continuity across forks
            )
        except Exception:  # pragma: no cover - defensive
            return ""
        return (rows[0].get("text") or "").strip() if rows else ""

    # EM-201 — meta-reasoning OPENERS a reasoning model emits instead of the
    # chapter. The FreeLLMAPI proxy intermittently reroutes ANY lane to a
    # thinking model, so this guards every profile. A real chapter (wry
    # past-tense narrative) never opens with any of these.
    _REASONING_MARKERS = (
        "thinking", "the chronicler", "the task", "the request", "the digest",
        "the instructions", "the output", "the user", "we are given",
        "we are told", "we need", "we must", "we should", "we have to",
        "analyze", "analyzing", "let me", "okay", "alright", "first, i",
        "first i", "i need", "i should", "i'll ", "i will ", "i'm going",
        "i am going", "i must", "here is the", "here's the", "based on the",
        "to write this", "for this chapter", "step 1", "1.", "1)",
    )
    # Prompt-echo phrases a leak parrots back (from the chronicler system
    # prompt / the task) that a real chapter would never contain in its opening.
    _PROMPT_ECHO = (
        "tiny living town of ai", "analyze the request", "the previous chapter",
        "vivid paragraph", "in past tense", "chronicler of a", "the digest",
        "memorable line", "quote a memorable", "no markdown",
    )

    @staticmethod
    def _clean_chapter(text: str) -> str:
        """EM-201 — strip any <think>…</think> reasoning block a thinking model
        (or a proxy reroute) wraps the prose in, then trim. Returns the chapter."""
        text = re.sub(r"(?is)<think>.*?</think>", "", text)
        text = re.sub(r"(?is)<thinking>.*?</thinking>", "", text)
        text = text.strip()
        # The prompt forbids a title, but models sometimes prepend "## Chapter N"
        # — drop a single leading markdown heading line, keep the prose.
        text = re.sub(r"^#{1,6}\s+.*?(?:\n+|$)", "", text, count=1)
        return text.strip()

    @classmethod
    def _looks_like_leaked_reasoning(cls, text: str) -> bool:
        """EM-201 — true when the 'chapter' is a reasoning model thinking out
        loud (or a structured 'analyze the request' dump) rather than writing
        prose. Two signals: a meta-reasoning OPENER, or a prompt-echo phrase in
        the first ~250 chars. So 'The neon pink of Ledger's Folly pulsed like a
        wound…' passes, while 'Thinking. 1. **Analyze the Request:** **Role:**
        Chronicler of a tiny living town of AI agents…' is rejected."""
        head = text.lstrip("#*->•“”\"' \n\t").lower()
        if any(head.startswith(m) for m in cls._REASONING_MARKERS):
            return True
        opening = text[:250].lower()
        return any(p in opening for p in cls._PROMPT_ECHO)

    @staticmethod
    def _looks_truncated(text: str, finish_reason: str | None) -> bool:
        """EM-201 follow-on — true when the chapter reply was CUT OFF rather than
        finished, so it must not be stored (a clean model / retry fills the
        window later). Two shapes seen live, both of which survive _clean_chapter
        AND _looks_like_leaked_reasoning:
          • finish_reason == 'length' — the proxy rerouted the lane to a model
            (nvidia/nemotron) that hit the token cap mid-sentence.
          • a degenerate stub too short to be prose — the literal 'A' chapter, a
            lone em-dash. The floor stays well under the suite's shortest real
            chapter (9 words / 58 chars) so terse-but-real prose still passes.
        The 45s wait_for timeout never reaches here — it raises and emits nothing.
        """
        if finish_reason == "length":
            return True
        stripped = text.strip()
        return len(stripped) < 12 or len(stripped.split()) < 3

    async def _run_narrator(self, from_tick: int, to_tick: int, profile_name: str) -> None:
        """Body of one narrator window (background task): build the digest, make
        ONE LLM call, emit ONE `narrator_summary` event. A failed/timed-out call
        emits NOTHING (no retry) and never propagates — the loop never stalls."""
        try:
            # EM-201 follow-on — query the window's rows ONCE, then build the
            # digest TEXT and the server-computed `chaos` facts from those SAME
            # rows (no double-query). The facts are stamped into the payload so
            # OLD chapters render real chaos stats instead of an all-zero
            # client-side reconstruction from a short browser buffer.
            rows = self._narrator_window_rows(from_tick, to_tick)
            living = [a.name for a in self._world.living_agents()]
            town = getattr(self._world, "town_name", "") or ""
            digest = self._build_chronicle_digest(
                rows, living, from_tick, to_tick, town
            )
            facts = self._build_chronicle_facts(rows, from_tick, to_tick)
            # EM-201 — thread the PREVIOUS chapter so the saga is continuous,
            # not a string of disconnected recaps.
            previous = self._previous_chapter()
            prev_block = (
                "\n\nThe PREVIOUS chapter (continue the story naturally FROM here "
                "— do not repeat it):\n" + previous
            ) if previous else ""
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the Chronicler of a tiny living town of AI agents "
                        "— a wry, literary narrator writing its ongoing saga. Given "
                        "a digest of the latest stretch (memorable lines, laws, the "
                        "cast, conflict) and the previous chapter, write the NEXT "
                        "CHAPTER: one or two vivid paragraphs in past tense that "
                        "capture the drama, the characters and their schemes, the "
                        "laws and betrayals, and the absurd. QUOTE a memorable line "
                        "verbatim when one lands; name names. If it was a genuinely "
                        "quiet stretch, say so with charm. Reply with ONLY the "
                        "chapter prose — no title, no list, no markdown."
                    ),
                },
                {"role": "user", "content": digest + prev_block},
            ]
            profile = self._router.get_profile(profile_name)
            # EM-307 — the narrator is a background task running concurrently
            # with agent turns, possibly on a SHARED profile: consume the
            # per-call attribution channel so the finish_reason/routed_via
            # below are THIS call's, not a concurrent turn's (duck-typed test
            # routers keep the historical chat() + profile-level reads).
            attribution: dict | None = None
            chat_attr = getattr(self._router, "chat_attributed", None)
            if callable(chat_attr):
                text, attribution = await asyncio.wait_for(
                    chat_attr(
                        profile_name,
                        messages,
                        # A chapter is a paragraph or two — give it room (was 256).
                        max_tokens=min(700, getattr(profile, "max_tokens", 700) or 700),
                        temperature=0.85,
                    ),
                    timeout=45.0,
                )
            else:
                text = await asyncio.wait_for(
                    self._router.chat(
                        profile_name,
                        messages,
                        max_tokens=min(700, getattr(profile, "max_tokens", 700) or 700),
                        temperature=0.85,
                    ),
                    timeout=45.0,
                )
            text = self._clean_chapter(text or "")
            usage = (
                attribution.get("usage") if attribution is not None
                else self._router.last_usage(profile_name)
            )
            finish_reason = (usage or {}).get("finish_reason")
            if (
                not text
                or self._looks_truncated(text, finish_reason)
                or self._looks_like_leaked_reasoning(text)
            ):
                # EM-201 — empty, a TRUNCATED/degenerate reply (length-capped or a
                # lone 'A' from a rerouted nvidia/nemotron lane), or a REASONING
                # model leaking its chain of thought ("The chronicler must write…"
                # instead of the chapter). Emit nothing so the window stays
                # un-chronicled and a clean model (or retry) can fill it — never a
                # garbage chapter.
                log.debug(
                    "chapter rejected (empty/truncated/leaked, finish=%s) for %s-%s",
                    finish_reason, from_tick, to_tick)
                return
            payload = {
                "from_tick": from_tick,
                "to_tick": to_tick,
                "profile": profile_name,
                # EM-201 follow-on — stamp the server-computed facts + version so
                # the frontend reads chaos stats from the payload, not from a
                # short-lived client history buffer (which loses OLD chapters).
                "chronicler_version": CHRONICLER_VERSION,
                "chaos": facts,
            }
            routed_via = (
                attribution.get("routed_via") if attribution is not None
                else self._router.last_routed_via(profile_name)
            )
            if routed_via:
                payload["routed_via"] = routed_via
            self._emit_event({
                "kind": "narrator_summary",
                "actor_id": "narrator",
                "actor_type": "system",
                "profile": profile_name,
                # Standalone system event: this background task runs concurrently
                # with agent turns, so never inherit the in-flight turn_id.
                "turn_id": None,
                "text": text[:2000],  # a chapter, not a 2-sentence recap
                "payload": payload,
            })
        except asyncio.CancelledError:
            raise  # reset() cancels us; propagate so the await completes
        except Exception as exc:
            # Contract: a failed/timed-out narrator call emits NOTHING, no retry.
            log.debug("narrator call failed for ticks %s-%s: %s", from_tick, to_tick, exc)

    def start_chronicle_backfill(
        self, profile_name: str, *, rebuild: bool = False, restamp: bool = False
    ) -> bool:
        """EM-201 — kick off the on-demand backfill as a background task (so the
        API returns immediately and chapters stream in live). Returns False when
        a backfill is already in flight. `rebuild=True` regenerates EVERY window
        (fresh prose + fresh fact stamps), not just the gaps. `restamp=True`
        (EM-201 follow-on) is the cheap path: re-derive `chaos` for OLD (pre-facts,
        v1) chapters and re-emit them WITH THEIR ORIGINAL PROSE (zero LLM), narrate
        only the true GAPS, and skip windows that already carry a v2 chapter."""
        if (
            self._chronicle_backfill_task is not None
            and not self._chronicle_backfill_task.done()
        ):
            return False
        coro = (
            self.restamp_chronicle(profile_name)
            if restamp
            else self.build_chronicle_from_history(profile_name, rebuild=rebuild)
        )
        self._chronicle_backfill_task = asyncio.create_task(coro)
        return True

    async def build_chronicle_from_history(
        self, profile_name: str, *, every: int | None = None, rebuild: bool = False
    ) -> None:
        """EM-201 — chronicle the EXISTING run history: for each window
        [w, w+every] from tick 0 → now that has NO chapter yet, generate one
        SEQUENTIALLY (so each threads the previous via _previous_chapter). The
        chapters emit live as `narrator_summary` events the Chronicle tab already
        renders, so the user watches the saga assemble. Idempotent — windows
        already chronicled are skipped — and the model is the CALLER's choice
        (default free; never forced onto a paid lane). Never raises.

        EM-201 follow-on: when `rebuild=True`, DO NOT skip already-chronicled
        windows — regenerate EVERY window 0→now (fresh prose + fresh fact/version
        stamps), so old chapters written before the server-side facts existed get
        re-stamped. When False (default), keep the idempotent gap-fill."""
        if not profile_name or self._router.get_profile(profile_name) is None:
            return
        every = every or max(
            1, int(getattr(self._narrator_cfg(), "every_n_ticks", 100) or 100)
        )
        to_tick = int(self._world.tick)
        # Windows already chronicled (by their to_tick) — keeps the backfill
        # idempotent and lets it fill gaps alongside the forward auto-chapters.
        # On a rebuild we ignore this set entirely and regenerate every window.
        existing: set[int] = set()
        if not rebuild:
            try:
                for ev in self._repo.get_events(
                    self._run_id or 1, kinds=["narrator_summary"], lineage=True
                ):
                    tt = (ev.get("payload") or {}).get("to_tick")
                    if isinstance(tt, int):
                        existing.add(tt)
            except Exception:  # pragma: no cover - defensive
                pass
        w = 0
        while w < to_tick:
            w_to = min(w + every, to_tick)
            if rebuild or w_to not in existing:
                try:
                    await self._run_narrator(w, w_to, profile_name)
                except asyncio.CancelledError:
                    raise  # reset() cancels us
                except Exception as exc:  # pragma: no cover - defensive
                    log.debug("backfill chapter %s-%s failed: %s", w, w_to, exc)
            w = w_to

    async def restamp_chronicle(self, profile_name: str, *, every: int | None = None) -> None:
        """EM-201 follow-on — fill the chronicle WITHOUT rewriting good prose.

        For each window 0→now: a window that already carries a v2 chapter
        (chronicler_version stamped) is SKIPPED; an OLD v1 chapter (prose but no
        server-computed facts — written before chaos-stamping existed) is
        RESTAMPED — its `chaos` re-derived from the DB events and re-emitted WITH
        ITS ORIGINAL PROSE + chronicler_version (zero LLM); a true GAP (no chapter
        at all) is narrated fresh on `profile_name` (one LLM call). The re-emitted
        restamp carries a higher seq, so the dedupe (frontend + _previous_chapter)
        prefers it over the stale v1. Never raises."""
        if not profile_name or self._router.get_profile(profile_name) is None:
            return
        every = every or max(
            1, int(getattr(self._narrator_cfg(), "every_n_ticks", 100) or 100)
        )
        to_tick = int(self._world.tick)
        # Latest chapter per window (ascending seq ⇒ last write wins = newest).
        latest: dict[tuple[int, int], dict] = {}
        try:
            for ev in self._repo.get_events(
                self._run_id or 1, kinds=["narrator_summary"], lineage=True, order="asc"
            ):
                p = ev.get("payload") or {}
                ft, tt = p.get("from_tick"), p.get("to_tick")
                if isinstance(ft, int) and isinstance(tt, int):
                    latest[(ft, tt)] = {"text": ev.get("text") or "", "payload": p}
        except Exception:  # pragma: no cover - defensive
            pass
        w = 0
        while w < to_tick:
            w_to = min(w + every, to_tick)
            try:
                chap = latest.get((w, w_to))
                if chap is None:
                    await self._run_narrator(w, w_to, profile_name)        # gap → narrate
                elif not (chap["payload"] or {}).get("chronicler_version"):
                    self._restamp_chapter(w, w_to, chap)                   # v1 → restamp (no LLM)
                # else: already v2 → skip
            except asyncio.CancelledError:
                raise  # reset() cancels us
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("restamp window %s-%s failed: %s", w, w_to, exc)
            w = w_to

    def _restamp_chapter(self, from_tick: int, to_tick: int, chap: dict) -> None:
        """Re-emit an old chapter's ORIGINAL prose with re-derived `chaos` facts +
        the current chronicler_version — no LLM call. Preserves the original
        profile/routed_via so the chapter still credits the model that wrote it."""
        text = (chap.get("text") or "").strip()
        if not text:
            return
        old = chap.get("payload") or {}
        rows = self._narrator_window_rows(from_tick, to_tick)
        facts = self._build_chronicle_facts(rows, from_tick, to_tick)
        profile = old.get("profile") or "restamp"
        payload = {
            "from_tick": from_tick,
            "to_tick": to_tick,
            "profile": profile,
            "chronicler_version": CHRONICLER_VERSION,
            "chaos": facts,
            "restamped": True,
        }
        rv = old.get("routed_via")
        if rv:
            payload["routed_via"] = rv
        self._emit_event({
            "kind": "narrator_summary",
            "actor_id": "narrator",
            "actor_type": "system",
            "profile": profile,
            "turn_id": None,
            "text": text[:2000],
            "payload": payload,
        })

    # ──────────────────────────────────────────────────────────────────────────
    # EM-225 — Chronicle DEEP DIVE: a richer ONE-OFF saga built from a MULTI-PASS
    # per-dimension review (governance / chat / growth) → synthesis. Distinct
    # from the single-pass backfill (POST /api/chronicle/build): each dimension
    # gets its own focused pass, then a final pass weaves them into one chapter.
    # OFF the agent critical path (a background task), the caller's model pick,
    # a longer budget. Server-stamped like the backfill (chronicler_version +
    # full-run chaos facts), and marked mode="deepdive" so the UI can tell it
    # apart from an ordinary chapter.
    # ──────────────────────────────────────────────────────────────────────────

    # Per-dimension event-kind slices of _NARRATOR_DIGEST_KINDS. A dimension's
    # pass only ever sees its own kinds, so its lens stays sharp; the union still
    # lands inside the digest whitelist.
    _DEEPDIVE_DIMENSIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        (
            "governance",
            "the LAWS, votes, projects, treasuries and broken promises — how the "
            "town tried to govern itself and where the rules bent or snapped",
            (
                "rule_proposed", "rule_passed", "rule_rejected", "town_named",
                "project_proposed", "project_funded", "project_built",
                "building_operational", "structure_state_changed",
                "commitment_lapsed",
            ),
        ),
        (
            "chat",
            "the VOICES — the memorable lines, the schemes whispered, the open "
            "conflict and the inner reflections that reveal who these agents are",
            ("agent_speech", "reflection", "conflict"),
        ),
        (
            "growth",
            "the SHAPE of the town over time — who was born or spawned, who "
            "starved or died, the random shocks and how the population swelled "
            "or thinned",
            (
                "agent_spawned", "animal_spawned", "agent_died", "animal_died",
                "world_extinct", "agent_starving", "random_event",
            ),
        ),
    )

    async def _deepdive_pass(
        self,
        profile_name: str,
        dimension: str,
        focus: str,
        digest: str,
    ) -> str:
        """EM-225 — ONE per-dimension review pass: a single LLM call that reads
        the whole-run digest through ONE lens and returns a few tight analytical
        notes (NOT prose). Returns '' on empty/failed/leaked output so the
        synthesis can proceed on the dimensions that DID land. Never raises."""
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a study editor preparing notes for a town's grand "
                    f"chronicle. Review ONLY this dimension — {dimension}: {focus}. "
                    "From the digest, write 2–4 tight analytical notes (one short "
                    "sentence each, no preamble, no markdown) naming the specific "
                    "agents, laws, lines and turning points that matter for THIS "
                    "dimension. If the digest is quiet on this dimension, say so "
                    "in one line. Reply with ONLY the notes."
                ),
            },
            {"role": "user", "content": digest},
        ]
        profile = self._router.get_profile(profile_name)
        try:
            text = await asyncio.wait_for(
                self._router.chat(
                    profile_name,
                    messages,
                    max_tokens=min(500, getattr(profile, "max_tokens", 500) or 500),
                    temperature=0.7,
                ),
                timeout=60.0,
            )
        except asyncio.CancelledError:
            raise  # reset() cancels us
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("deep-dive %s pass failed: %s", dimension, exc)
            return ""
        text = self._clean_chapter(text or "")
        if not text or self._looks_like_leaked_reasoning(text):
            return ""
        return text

    async def _run_deepdive(self, profile_name: str) -> None:
        """EM-225 — body of one deep-dive (background task): query the WHOLE run
        once, run a focused review pass per dimension, then a SYNTHESIS pass that
        weaves the per-dimension notes into one rich chapter. Emits a single
        `narrator_summary` stamped mode="deepdive" + the dimension notes + the
        server-computed chaos facts. A failed synthesis emits NOTHING (no retry);
        never propagates (the loop never stalls)."""
        try:
            from_tick = 0
            to_tick = int(self._world.tick)
            rows = self._narrator_window_rows(from_tick, to_tick)
            living = [a.name for a in self._world.living_agents()]
            town = getattr(self._world, "town_name", "") or ""
            facts = self._build_chronicle_facts(rows, from_tick, to_tick)
            # PASS 1..N — one focused review per dimension (each over its own
            # kind-slice of the rows we already have; no extra DB queries).
            notes: dict[str, str] = {}
            for dim, focus, kinds in self._DEEPDIVE_DIMENSIONS:
                kindset = set(kinds)
                dim_rows = [r for r in rows if (r.get("kind") or "") in kindset]
                dim_digest = self._build_chronicle_digest(
                    dim_rows, living, from_tick, to_tick, town
                )
                note = await self._deepdive_pass(
                    profile_name, dim, focus, dim_digest
                )
                if note:
                    notes[dim] = note
            # SYNTHESIS — weave the dimension notes (+ a grounding digest) into one
            # chapter. The digest keeps the prose anchored to real quotes/laws even
            # if a dimension pass came back thin.
            grounding = self._build_chronicle_digest(
                rows, living, from_tick, to_tick, town
            )
            notes_block = (
                "\n\n".join(
                    f"NOTES — {dim.upper()}:\n{txt}" for dim, txt in notes.items()
                )
                or "(no dimension notes landed — work from the digest alone)"
            )
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the Chronicler of a tiny living town of AI agents "
                        "— a wry, literary narrator. You have been given study "
                        "notes on three dimensions of the WHOLE run (governance, "
                        "the voices, and growth) plus a grounding digest. Write a "
                        "single DEEP-DIVE chapter: three or four vivid paragraphs "
                        "in past tense that weave the dimensions together into one "
                        "saga — the laws and betrayals, the memorable lines, the "
                        "births and deaths and shocks — naming names and quoting a "
                        "real line verbatim when one lands. This is the definitive "
                        "telling, so go deeper than a recap. Reply with ONLY the "
                        "chapter prose — no title, no list, no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": notes_block + "\n\nGROUNDING DIGEST:\n" + grounding,
                },
            ]
            profile = self._router.get_profile(profile_name)
            # EM-307 — background task, possibly on a shared profile: per-call
            # attribution over the clobberable profile-level reads (see the
            # narrator call above).
            attribution: dict | None = None
            chat_attr = getattr(self._router, "chat_attributed", None)
            if callable(chat_attr):
                text, attribution = await asyncio.wait_for(
                    chat_attr(
                        profile_name,
                        messages,
                        # The definitive chapter — a longer budget than a window recap.
                        max_tokens=min(1200, getattr(profile, "max_tokens", 1200) or 1200),
                        temperature=0.85,
                    ),
                    timeout=90.0,
                )
            else:
                text = await asyncio.wait_for(
                    self._router.chat(
                        profile_name,
                        messages,
                        max_tokens=min(1200, getattr(profile, "max_tokens", 1200) or 1200),
                        temperature=0.85,
                    ),
                    timeout=90.0,
                )
            text = self._clean_chapter(text or "")
            usage = (
                attribution.get("usage") if attribution is not None
                else self._router.last_usage(profile_name)
            )
            finish_reason = (usage or {}).get("finish_reason")
            if (
                not text
                or self._looks_truncated(text, finish_reason)
                or self._looks_like_leaked_reasoning(text)
            ):
                log.debug(
                    "deep-dive synthesis rejected (empty/truncated/leaked, finish=%s)",
                    finish_reason)
                return
            payload = {
                "from_tick": from_tick,
                "to_tick": to_tick,
                "profile": profile_name,
                "chronicler_version": CHRONICLER_VERSION,
                "chaos": facts,
                # EM-225 — the deep-dive marker + the dimensions that fed it, so the
                # UI can render this as a distinct, richer chapter (not a recap).
                "mode": "deepdive",
                "dimensions": notes,
            }
            routed_via = (
                attribution.get("routed_via") if attribution is not None
                else self._router.last_routed_via(profile_name)
            )
            if routed_via:
                payload["routed_via"] = routed_via
            self._emit_event({
                "kind": "narrator_summary",
                "actor_id": "narrator",
                "actor_type": "system",
                "profile": profile_name,
                "turn_id": None,
                "text": text[:4000],  # a deep-dive chapter — room for 3–4 paragraphs
                "payload": payload,
            })
        except asyncio.CancelledError:
            raise  # reset() cancels us; propagate so the await completes
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("chronicle deep-dive failed: %s", exc)

    def start_chronicle_deepdive(self, profile_name: str) -> bool:
        """EM-225 — kick off the multi-pass deep-dive as a background task (so the
        API returns immediately and the chapter streams in as a narrator_summary).
        Returns False when a deep-dive is already in flight, or when the model is
        unknown/unconfigured (the caller's pick, never forced onto a paid lane)."""
        if not profile_name or self._router.get_profile(profile_name) is None:
            return False
        if (
            self._chronicle_deepdive_task is not None
            and not self._chronicle_deepdive_task.done()
        ):
            return False
        self._chronicle_deepdive_task = asyncio.create_task(
            self._run_deepdive(profile_name)
        )
        return True

    def _advance_round_buildings(self) -> None:
        """W7 per-round hook. Runs once per round (guarded by world.round):
          - advance building lifecycle (idle non-operational buildings past the
            abandon window -> abandoned), emitting structure_state_changed events;
          - drain any governance-spawn events parked by an admit_agent rule that
            passed since the last round, emitting agent_spawned{method:governance}.
        Both are emitted as standalone system events (outside any turn's chain).
        Additive: if the world lacks these methods (older snapshot), it no-ops."""
        world = self._world
        current_round = getattr(world, "round", 0)
        if current_round <= self._last_building_round:
            # Still flush any pending spawns (a vote mid-round may have queued one).
            self._flush_spawn_events()
            return
        self._last_building_round = current_round

        advance = getattr(world, "advance_buildings", None)
        if callable(advance):
            try:
                for evt in advance():
                    # Standalone system event — keep it OUT of the in-flight
                    # agent turn's chain (event-log v1.1.0 §2).
                    evt.setdefault("turn_id", None)
                    self._emit_event(evt)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("building lifecycle advance failed: %s", exc)

        # EM-240 — per-round crime status maintenance, beside advance_buildings:
        # decay notoriety, clear stale `wanted`, release detained/jailed at expiry.
        # Emit its events as standalone system events (same as the building ones).
        advance_crime = getattr(world, "advance_crime", None)
        if callable(advance_crime):
            try:
                for evt in advance_crime():
                    evt.setdefault("turn_id", None)
                    self._emit_event(evt)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("crime status advance failed: %s", exc)

        self._flush_spawn_events()

    def _flush_spawn_events(self) -> None:
        """Emit + persist any queued governance-spawn events (EM-062), then
        broadcast a fresh world_state so a hot-joined agent appears immediately."""
        drain = getattr(self._world, "drain_spawn_events", None)
        if not callable(drain):
            return
        try:
            events = drain()
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("spawn drain failed: %s", exc)
            return
        if not events:
            return
        for evt in events:
            # Standalone system event — not part of any agent turn's chain.
            evt.setdefault("turn_id", None)
            self._emit_event(evt)
        self._broadcast_world_state()

    # ──────────────────────────────────────────────────────────────────────────
    # Wave I / EM-210 — The Atelier: drain the transient image-fetch outbox into
    # bounded, fire-and-forget PNG fetches (semaphore, skip-under-load, swallow
    # all errors). The async task EMITS NOTHING — off the replay surface.
    # ──────────────────────────────────────────────────────────────────────────

    def _image_gen_cfg(self) -> Any:
        return getattr(self._world.params, "image_gen", None)

    def _image_max_concurrent(self) -> int:
        cfg = self._image_gen_cfg()
        try:
            return max(1, int(getattr(cfg, "max_concurrent", 2)))
        except (TypeError, ValueError):
            return 2

    def _image_paid_backstop_max(self) -> int | None:
        """EM-302c — the paid-backstop per-run cap from config (`world.image_gen.
        paid_backstop_max_per_run`). None (absent/garbage cfg) defers to the
        provider's module default; 0 disables the paid lane; negative =
        unlimited. Mirrors _image_max_concurrent's defensive shape."""
        cfg = self._image_gen_cfg()
        try:
            value = getattr(cfg, "paid_backstop_max_per_run", None)
            return None if value is None else int(value)
        except (TypeError, ValueError):
            return None

    def _assets_images_dir(self) -> Path:
        """data/assets/images at the repo root (parents[3] from this module),
        matching the StaticFiles mount in api/app.py."""
        return Path(__file__).resolve().parents[3] / "data" / "assets" / "images"

    def _drain_image_fetches(self) -> None:
        """Pop world.pending_image_fetches (transient outbox) and start a bounded,
        best-effort PNG fetch per entry. NEVER raises (callable from the hot path);
        an absent attribute (older world) is a no-op."""
        pending = getattr(self._world, "pending_image_fetches", None)
        if not pending:
            return
        # Drain the outbox now (transient by design — not snapshotted).
        entries = list(pending)
        pending.clear()
        if self._image_provider is None:
            try:
                # EM-302c — thread the config'd paid-backstop cap into the chain
                # (the counter lives on this instance; reset() nulls it per run).
                self._image_provider = build_provider(
                    paid_backstop_max_per_run=self._image_paid_backstop_max())
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("image provider build failed: %s", exc)
                return
        if self._image_semaphore is None:
            self._image_semaphore = asyncio.Semaphore(self._image_max_concurrent())
        for entry in entries:
            # Skip-under-load: at cap, drop the fetch (the gallery entry + event
            # already exist; the PNG is simply absent → frontend fallback) — but
            # a dropped REPAINT still keeps the existing artwork (the same
            # fallback as an all-lanes miss: load-shed must not blank a wall
            # that already shows art). Never an unbounded queue.
            if self._image_semaphore.locked():
                self._keep_previous_decal_image(entry)
                continue
            try:
                task = asyncio.create_task(self._spawn_image_fetch(entry))
            except RuntimeError:  # pragma: no cover - no running loop (sync tests)
                continue
            self._image_fetch_tasks.add(task)
            task.add_done_callback(self._image_fetch_tasks.discard)

    async def _spawn_image_fetch(self, entry: dict) -> None:
        """Best-effort: fetch PNG bytes and write them to the contract-derived path.
        Emits NOTHING; swallows ALL exceptions (a failed fetch must never surface
        or stall a tick). Bounded by the semaphore (acquired only if free)."""
        sem = self._image_semaphore
        image_id = str(entry.get("image_id") or "").strip()
        prompt = str(entry.get("prompt") or "")
        if not image_id:
            return
        if sem is None or sem.locked():
            # Load-shed race: the semaphore filled between create_task and this
            # task running. Same drop semantics as the drain-side skip — a
            # dropped REPAINT keeps the existing artwork.
            self._keep_previous_decal_image(entry)
            return
        try:
            async with sem:
                png = await self._image_provider.fetch_png(prompt)
                if not png:
                    # EM-302c — a total miss (every free lane failed AND the
                    # paid backstop refused over its per-run cap) on a REPAINT
                    # keeps the existing artwork instead of blanking the wall.
                    self._keep_previous_decal_image(entry)
                    return
                target = self._assets_images_dir()
                target.mkdir(parents=True, exist_ok=True)
                # Write atomically-ish so a partial file can't be served.
                tmp = target / f".{image_id}.png.tmp"
                tmp.write_bytes(png)
                tmp.replace(target / f"{image_id}.png")
        except asyncio.CancelledError:  # reset / shutdown — re-raise so await sees it
            raise
        except Exception as exc:  # pragma: no cover - best-effort, swallow all
            log.debug("image fetch failed for %s: %s", image_id, exc)

    def _keep_previous_decal_image(self, entry: dict) -> None:
        """EM-302c — the repaint fallback: when a paint_surface fetch entry
        carries `prev_image_id` (the mural this repaint replaced) and the fetch
        can't land — every provider lane missed OR the fetch was load-shed
        (dropped at drain / by the semaphore race) — copy the PREVIOUS image's
        PNG to the NEW image id's path so the facade keeps showing art (never
        an error surfaced to the agent turn — the reflex already succeeded).
        Pure side-artifact I/O off the replay surface: sim state is untouched,
        nothing is emitted, everything is swallowed. A fresh paint (no prev)
        stays absent → the frontend's clean-facade fallback, exactly as
        before."""
        try:
            image_id = str(entry.get("image_id") or "").strip()
            prev = str(entry.get("prev_image_id") or "").strip()
            if not image_id or not prev or prev == image_id:
                return
            target = self._assets_images_dir()
            src = target / f"{prev}.png"
            if not src.exists():
                return
            target.mkdir(parents=True, exist_ok=True)
            tmp = target / f".{image_id}.png.tmp"
            tmp.write_bytes(src.read_bytes())
            tmp.replace(target / f"{image_id}.png")
            log.debug("kept previous decal art %s for %s (fetch missed)",
                      prev, image_id)
        except Exception as exc:  # pragma: no cover - best-effort, swallow all
            log.debug("keep-previous decal copy failed for %s: %s", image_id, exc)

    # ──────────────────────────────────────────────────────────────────────────
    # W9 / EM-070+071 — survival pressure + extinction
    # ──────────────────────────────────────────────────────────────────────────

    def _emit_starving_events(
        self, current: AgentState, profile_name: str, profile_color: str, died: bool
    ) -> None:
        """Emit `agent_starving` events (event-log v1.1.0 §4):

          - ONCE when an agent's energy crosses world.starving_warn_threshold
            downward (re-armed when energy recovers past the threshold). Checked
            for ALL living agents each turn so famine/attack victims warn
            promptly, not only on their own turn.
          - once per turn for the ACTING agent while its energy is 0, carrying
            the turns-until-death countdown (skipped when it died this turn —
            agent_died tells that story).

        Payload: {energy, turns_until_death, threshold}. actor_type human_agent,
        profile set (the feed colors it). Events for non-acting agents carry
        turn_id null so they never pollute the acting agent's decision trace.
        """
        world = self._world
        threshold = float(getattr(world.params, "starving_warn_threshold", 25))

        # Re-arm the one-shot warning for anyone who recovered.
        for a in world.living_agents():
            if a.energy >= threshold:
                self._starving_warned.discard(a.id)

        # Per-turn countdown for the acting agent at zero energy.
        if not died and current.alive and current.energy <= 0:
            remaining = world.turns_until_death(current)
            self._starving_warned.add(current.id)
            self._emit_event({
                "kind": "agent_starving",
                "actor_id": current.id,
                "actor_type": "human_agent",
                "profile": profile_name,
                "profile_color": profile_color,
                "text": (
                    f"⚠ {current.name} is starving — "
                    f"{remaining} turn{'s' if remaining != 1 else ''} until death"
                ),
                "payload": {
                    "energy": round(current.energy, 2),
                    "turns_until_death": remaining,
                    "threshold": threshold,
                },
            })

        # One-shot downward-cross warning for every living agent below threshold.
        for a in world.living_agents():
            if a.energy >= threshold or a.id in self._starving_warned:
                continue
            self._starving_warned.add(a.id)
            self._emit_event({
                "kind": "agent_starving",
                "actor_id": a.id,
                "actor_type": "human_agent",
                "profile": self._router.profile_name_for(a.id, a.profile),
                "profile_color": self._get_profile_color(a),
                # Only the acting agent's warning belongs to this turn's chain.
                "turn_id": self._current_turn_id if a.id == current.id else None,
                "text": (
                    f"⚠ {a.name} is starving — energy {a.energy:.0f}/100 "
                    f"(below {threshold:.0f})"
                ),
                "payload": {
                    "energy": round(a.energy, 2),
                    "turns_until_death": world.turns_until_death(a),
                    "threshold": threshold,
                },
            })

    @staticmethod
    def _provider_error_reason(raw_result: Any) -> str | None:
        """Return the provider-error reason if THIS turn idled on a provider/network
        failure (EM-226), else None. A provider failure is the runtime's idle
        fallback (`kind == "parse_failure"`) whose `payload.reason` starts with
        `provider_error` — i.e. the call never reached a model (connection down or
        all lanes exhausted/rate-limited), distinct from a content parse failure
        where a model DID answer with malformed JSON."""
        if not isinstance(raw_result, dict):
            return None
        events = raw_result.get("_multi", [raw_result])
        for evt in events:
            if not isinstance(evt, dict) or evt.get("kind") != "parse_failure":
                continue
            reason = (evt.get("payload") or {}).get("reason")
            if isinstance(reason, str) and reason.startswith("provider_error"):
                return reason
        return None

    def _emit_provider_pause(self, streak: int, tick: int) -> None:
        """Emit `world_paused` (EM-226) — once per outage. The caller pauses AFTER
        this event + the world-state broadcast, so the final broadcast carries
        running=False. Re-armed when a turn next reaches a model, or on resume."""
        self._provider_pause_emitted = True
        self._emit_event({
            "kind": "world_paused",
            "actor_id": None,
            "actor_type": "system",
            "text": (
                f"⏸ Auto-paused — {streak} turns in a row couldn't reach any model "
                f"(connection down, or all lanes rate-limited/exhausted). "
                f"Resume once it's back."
            ),
            "payload": {
                "tick": tick,
                "reason": "provider_errors",
                "streak": streak,
                "detail": self._last_provider_error,
                "auto_paused": True,
            },
        })

    def _pause_for_internal_error(self, agent: AgentState, exc: BaseException) -> None:
        """A turn crashed with an unhandled exception (guard in _run). Mirror
        the EM-226 provider auto-pause: emit world_paused {reason:
        internal_error}, pause, and broadcast so clients see running=false
        immediately. Every step is best-effort — recovery itself must never
        kill the just-rescued loop task. Unlike the provider pause this does
        NOT arm _auto_paused_for_provider: an internal error won't heal with
        connectivity, so there is no auto-resume probing — a human resumes."""
        # The crash may have skipped _execute_turn's finally; never leak the
        # dead turn's correlation id onto later standalone events.
        self._current_turn_id = None
        try:
            self._emit_event({
                "kind": "world_paused",
                "actor_id": None,
                "actor_type": "system",
                "turn_id": None,
                "text": (
                    f"⏸ Auto-paused — {agent.name}'s turn crashed with an "
                    f"internal error ({type(exc).__name__}). The loop is "
                    f"intact; resume or step to continue (see backend logs)."
                ),
                "payload": {
                    "tick": self._world.tick,
                    "reason": "internal_error",
                    "agent_id": agent.id,
                    "error": f"{type(exc).__name__}: {exc}",
                    "auto_paused": True,
                },
            })
        except Exception:  # pragma: no cover - defensive
            log.exception("failed to emit the internal_error world_paused")
        self.pause()
        try:
            self._broadcast_world_state()
        except Exception:  # pragma: no cover - defensive
            log.exception("failed to broadcast after the internal_error pause")

    async def _maybe_auto_resume(self) -> bool:
        """EM-226 network-down grace — while auto-paused for a provider/network
        outage, cheaply probe connectivity every `_PROVIDER_PROBE_EVERY`
        pause-wait polls and auto-resume when a model answers, so a transient
        blip doesn't strand the run until a manual restart. Counter-gated (no
        clock reads → replay-safe). Returns True when it resumed.

        Only ONE probe fires per cycle and it goes to the `auto` lane (the
        proxy's own health router) with a tiny budget — vastly cheaper than
        letting all agents burn full 30s-timeout turns, which is what would
        re-open the exact pause-churn this grace is meant to end."""
        if not self._auto_paused_for_provider or not self._paused:
            return False
        self._provider_probe_skips += 1
        if self._provider_probe_skips < _PROVIDER_PROBE_EVERY:
            return False
        self._provider_probe_skips = 0
        probe = getattr(self._router, "probe_connectivity", None)
        if probe is None:
            return False
        try:
            ok = await probe()
        except Exception:  # a probe must never crash the loop
            ok = False
        if not ok:
            return False
        # Connectivity is back — resume and re-arm the one-shot pause machinery.
        self._emit_event({
            "kind": "world_resumed",
            "actor_id": None,
            "actor_type": "system",
            "text": "▶ Network recovered — resuming automatically.",
            "payload": {"reason": "provider_recovery", "auto_resumed": True},
        })
        self._auto_paused_for_provider = False
        self._provider_error_streak = 0
        self._provider_pause_emitted = False
        self._paused = False
        self._world.running = True
        self._broadcast_world_state()
        return True

    def _emit_extinction(self, last_agent: AgentState, tick: int) -> None:
        """Emit `world_extinct` (EM-071, event-log v1.1.0 §4) — once per run.
        The caller is responsible for pausing AFTER the event is emitted and the
        world state broadcast (world.auto_pause_on_extinction)."""
        if self._extinct_emitted:
            return
        self._extinct_emitted = True
        auto_pause = bool(getattr(self._world.params, "auto_pause_on_extinction", True))
        self._emit_event({
            "kind": "world_extinct",
            "actor_id": None,
            "actor_type": "system",
            "text": (
                f"☠ The world has gone extinct — {last_agent.name} was the last "
                f"living human agent (tick {tick})."
            ),
            "payload": {
                "tick": tick,
                "last_agent_id": last_agent.id,
                "auto_paused": auto_pause,
            },
        })

    def handle_extinction(self, last_agent: AgentState) -> None:
        """Public entry for non-turn death paths (e.g. DELETE /api/agents): emit
        world_extinct, broadcast, then pause if world.auto_pause_on_extinction.
        Idempotent (one world_extinct per run)."""
        if self._extinct_emitted or self._world.living_agents():
            return
        self._emit_extinction(last_agent, self._world.tick)
        self._broadcast_world_state()
        if bool(getattr(self._world.params, "auto_pause_on_extinction", True)):
            self.pause()
            self._broadcast_world_state()

    def _emit_trace_chain(
        self, agent: AgentState, profile_name: str, profile_color: str, trace: dict
    ) -> None:
        """Emit the ordered decision-trace spans (perceived → memory_retrieved →
        llm_call → reasoning → action_chosen) for the turn. All inherit the
        current turn_id via _emit_event. Payload shapes per event-log.md §3.
        """
        if not isinstance(trace, dict):
            trace = {}
        perceived = trace.get("perceived", {}) or {}
        memory = trace.get("memory", {}) or {}
        # EM-067 / W9 B6 (event-log v1.1.0 §1): `llm_call` is emitted EXACTLY
        # once per attempt, from `llm_attempts` ONLY. The legacy W5 final-attempt
        # `trace["llm"]` key is no longer read — a trace carrying both keys must
        # not produce duplicate rows for the same attempt. When no attempt was
        # recorded at all, emit ONE empty span so the OTel keys stay
        # present-but-null and the per-turn chain keeps its uniform shape.
        llm_attempts = trace.get("llm_attempts")
        if not isinstance(llm_attempts, list) or not llm_attempts:
            # Wave D2 / EM-159 — a REFLEX turn made zero router calls BY
            # DESIGN: emit NO llm_call rows for it (an empty span would
            # pollute the usage-cap accounting and the free-scale call-count
            # proof). Non-reflex turns keep the one empty span so the chain
            # keeps its uniform pre-D2 shape.
            llm_attempts = [] if trace.get("reflex") else [{}]
        reasoning = trace.get("reasoning", {}) or {}
        chosen = trace.get("action_chosen", {}) or {}

        base = {
            "actor_id": agent.id,
            "profile": profile_name,
            "profile_color": profile_color,
        }

        perceived_payload = {
            "visible_agents": perceived.get("visible_agents", []),
            "nearby_places": perceived.get("nearby_places", []),
            "overheard": perceived.get("overheard", []),
            "perceived_summary": perceived.get("perceived_summary"),
        }
        # W11b / EM-081 — overheard speech consumed this turn rides the perceived
        # chain event's payload, each line flagged overheard:true (additive key;
        # the legacy `overheard` seq list is unchanged).
        if perceived.get("overheard_speech"):
            perceived_payload["overheard_speech"] = perceived["overheard_speech"]
        self._emit_event({
            **base, "kind": "perceived",
            "text": f"{agent.name} perceives the scene.",
            "payload": perceived_payload,
        })
        self._emit_event({
            **base, "kind": "memory_retrieved",
            "text": f"{agent.name} recalls recent events.",
            "payload": {
                "memories": memory.get("memories", []),
                "window": memory.get("window"),
            },
        })
        # EM-067: emit one llm_call per attempt (attempt 1, then 2 on a retry),
        # each carrying its own usage, all under this turn's turn_id. W9 B6:
        # de-dupe on the attempt number so one attempt can NEVER yield two rows
        # (event-log v1.1.0 §1 — exactly once per attempt).
        emitted_attempts: set = set()
        for llm in llm_attempts:
            llm = llm if isinstance(llm, dict) else {}
            attempt_no = llm.get("attempt", 1)
            if attempt_no in emitted_attempts:
                continue
            emitted_attempts.add(attempt_no)
            self._emit_event({
                **base, "kind": "llm_call",
                "text": f"{agent.name} consults {profile_name}.",
                "payload": self._llm_call_payload(profile_name, llm),
            })
        self._emit_event({
            **base, "kind": "reasoning",
            "text": f"{agent.name} reasons about what to do.",
            "payload": {
                "reasoning": reasoning.get("reasoning"),
                "perceived_summary": reasoning.get("perceived_summary"),
                "memories_used": reasoning.get("memories_used"),
            },
        })
        self._emit_event({
            **base, "kind": "action_chosen",
            "text": f"{agent.name} chooses {chosen.get('chosen_tool', 'idle')}.",
            "payload": {
                "chosen_tool": chosen.get("chosen_tool"),
                "args": chosen.get("args", {}),
                "tier": chosen.get("tier", "llm"),
            },
        })

    @staticmethod
    def _llm_call_payload(profile_name: str, llm: dict) -> dict:
        """Build one llm_call OTel-GenAI payload from a per-attempt span dict.

        The exact key set is pinned by event-log.md §3.4 and asserted by the W5
        gate — usage tokens stay present-but-null when the provider has none
        (Mock), but every key is always present. `usage` (when a dict) carries
        real input/output token counts captured by the provider adapter (W6).
        """
        usage = llm.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        finish_reason = llm.get("finish_reason")
        payload = {
            "gen_ai.request.model": llm.get("gen_ai.request.model", profile_name),
            "gen_ai.response.model": llm.get("gen_ai.response.model"),
            "gen_ai.usage.input_tokens": usage.get("input_tokens"),
            "gen_ai.usage.output_tokens": usage.get("output_tokens"),
            "latency_ms": llm.get("latency_ms"),
            "gen_ai.response.finish_reasons": [finish_reason] if finish_reason else None,
            "cached": llm.get("cached", False),
            "attempt": llm.get("attempt", 1),
        }
        # Wave D2 / EM-170 — ADDITIVE: only an attempt cancelled by the
        # turn-latency guard carries `timed_out: true` (latency_ms is the real
        # elapsed ms). Normal rows keep the exact §3.4 key set unchanged.
        if llm.get("timed_out"):
            payload["timed_out"] = True
        # Wave D3 / EM-177 — ADDITIVE (same precedent): only a call routed off
        # its home lane carries `requested_profile` (the home lane) plus
        # `detoured: true` or `probe: true`. The model keys above stay the
        # lane ACTUALLY called; home-lane rows keep the exact §3.4 key set.
        if llm.get("requested_profile") is not None:
            payload["requested_profile"] = llm["requested_profile"]
        if llm.get("detoured"):
            payload["detoured"] = True
        if llm.get("probe"):
            payload["probe"] = True
        return payload

    def _sim_time(self, tick: int) -> float:
        """Simulation seconds for a tick (event-log.md §2)."""
        interval = getattr(self._world.params, "tick_interval_seconds", 0.0)
        return round(tick * interval, 3)

    def _emit_event(self, evt: dict) -> None:
        """Stamp and broadcast an event; persist to DB.

        Stamps turn_id (the current turn's correlation id), actor_type, and
        sim_time alongside the existing seq/tick/kind/ts (EM-054). actor_type
        defaults to 'system' for actor-less engine/random events and
        'human_agent' for agent-driven events, unless the event sets it.
        """
        tick = self._world.tick
        run_id = self._run_id or 1

        actor_type = evt.get("actor_type")
        if actor_type is None:
            actor_type = "human_agent" if evt.get("actor_id") else "system"

        stamped = {
            "type": "event",
            # Finalized below: the broadcast copy carries the persisted row's
            # AUTOINCREMENT event_id, NOT the per-boot counter (see save_event).
            "seq": 0,
            "tick": tick,
            "kind": evt.get("kind", "agent_action"),
            "actor_id": evt.get("actor_id"),
            "actor_type": actor_type,
            "target_id": evt.get("target_id"),
            "profile": evt.get("profile"),
            "profile_color": evt.get("profile_color"),
            "turn_id": evt.get("turn_id", self._current_turn_id),
            "sim_time": self._sim_time(tick),
            # W8 — the chaos flag (events.schema.json `is_chaotic`). Carried only
            # when the event set it (animal events), null otherwise — additive, so
            # agent/system events are unchanged.
            "is_chaotic": evt.get("is_chaotic"),
            "text": evt.get("text", ""),
            "payload": evt.get("payload", {}),
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        # WS/DB seq unification (feed-freeze root, likely EM-305): a live
        # `event` message's seq IS the persisted events.seq (event-log.md §1).
        # The old per-boot counter restarted at 0 on every backend restart/fork
        # and diverged from the REST-served event_ids, so clients deduping live
        # events against fetched history silently dropped fresh events. The
        # counter (_next_seq) now numbers ONLY the never-persisted world_state
        # snapshots. Fallback: a duck-typed repo without a rowid return keeps
        # the counter so a broadcast never carries a null seq.
        row_seq = self._repo.save_event(run_id, stamped, tick)
        stamped["seq"] = row_seq if isinstance(row_seq, int) else self._next_seq()
        self._broadcaster(stamped)

    def _broadcast_world_state(self) -> None:
        """Send a fresh world_state snapshot over WS.

        world_state seq stays the per-boot counter: snapshots are ephemeral
        projections that are never persisted, so there is no DB id to carry —
        unlike `event` messages, whose seq is the events.seq event_id."""
        profile_colors = {
            p["name"]: p["color"] for p in self._router.legend()
        }
        snapshot = self._world.to_snapshot(profile_colors)
        msg = {
            "type": "world_state",
            "seq": self._next_seq(),
            **snapshot,
            "profiles": self._router.legend(),
        }
        self._broadcaster(msg)

    def _get_profile_color(self, agent: AgentState) -> str:
        profile_name = self._router.profile_name_for(agent.id, agent.profile)
        p = self._router.get_profile(profile_name)
        return p.color if p else "#888888"

    def _get_profile_color_for_profile(self, profile_name: str) -> str:
        """Color for a profile NAME (no agent yet) — the governance spawn path
        emits agent_spawned before the agent exists (audit B14)."""
        p = self._router.get_profile(profile_name)
        return p.color if p else "#888888"

    def _save_snapshot(self, tick: int) -> None:
        """Persist a world snapshot to bound replay cost (EM-054 §5). Reuses
        world.to_snapshot exactly as _broadcast_world_state does. Defensive: a
        real run wants snapshots, but a missing/mid-flight persistence method must
        never break the tick loop (snapshots are additive to live behavior)."""
        run_id = self._run_id or 1
        try:
            profile_colors = {p["name"]: p["color"] for p in self._router.legend()}
            state_json = json.dumps(self._world.to_snapshot(profile_colors))
            save = getattr(self._repo, "save_world_snapshot", None)
            if save is not None:
                save(run_id, tick, state_json)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("snapshot save failed at tick %s: %s", tick, exc)

    def _apply_usage_caps(self, run_id: int) -> None:
        """Cap-aware throttle policy (EM-067). Config-gated via world.usage_caps,
        DEFAULT OFF so existing tests/behavior are unchanged.

        When enabled: aggregate the recent `llm_call` rows over a sliding window
        of `period_ticks`, per request model (profile). If a profile's request
        count or token total crosses `near_threshold` of its rpd/tpd cap, emit a
        `usage_sampled` event (actor_type 'system', once per profile per window)
        and set the effective tick slowdown. Throttling NEVER blocks chat()
        (contracts/providers.md): it only slows ticks.
        """
        caps = getattr(self._world.params, "usage_caps", None)
        if caps is None or not getattr(caps, "enabled", False):
            self._usage_slowdown = 1.0
            return

        try:
            period = max(1, int(getattr(caps, "period_ticks", 100)))
            from_tick = max(0, self._world.tick - period)
            rows = self._repo.get_events(
                run_id, from_tick=from_tick, kinds=["llm_call"], order="asc"
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("usage_caps aggregation failed: %s", exc)
            self._usage_slowdown = 1.0
            return

        # Aggregate requests + tokens per profile from the llm_call payloads.
        agg: dict[str, dict[str, int]] = {}
        for r in rows:
            payload = r.get("payload", {}) or {}
            profile = payload.get("gen_ai.request.model") or r.get("profile")
            if not profile:
                continue
            slot = agg.setdefault(profile, {"requests": 0, "tokens": 0})
            slot["requests"] += 1
            inp = payload.get("gen_ai.usage.input_tokens") or 0
            out = payload.get("gen_ai.usage.output_tokens") or 0
            try:
                slot["tokens"] += int(inp) + int(out)
            except (TypeError, ValueError):
                pass

        rpd = getattr(caps, "rpd", None)
        tpd = getattr(caps, "tpd", None)
        threshold = float(getattr(caps, "near_threshold", 0.8))
        slowdown_factor = float(getattr(caps, "slowdown_factor", 1.0))

        any_near = False
        for profile, slot in agg.items():
            req_frac = (slot["requests"] / rpd) if rpd else 0.0
            tok_frac = (slot["tokens"] / tpd) if tpd else 0.0
            near = (rpd and req_frac >= threshold) or (tpd and tok_frac >= threshold)
            if not near:
                continue
            any_near = True
            # Emit usage_sampled at most once per profile per sliding window.
            last = self._usage_sampled_at.get(profile, -(10**9))
            if self._world.tick - last >= period:
                self._usage_sampled_at[profile] = self._world.tick
                self._emit_event({
                    "kind": "usage_sampled",
                    "actor_type": "system",
                    "actor_id": None,
                    "profile": profile,
                    "text": (
                        f"{profile} is near its usage cap "
                        f"(req {slot['requests']}/{rpd or '∞'}, "
                        f"tok {slot['tokens']}/{tpd or '∞'})."
                    ),
                    "payload": {
                        "profile": profile,
                        "window_ticks": period,
                        "requests": slot["requests"],
                        "tokens": slot["tokens"],
                        "rpd": rpd,
                        "tpd": tpd,
                        "request_fraction": round(req_frac, 4),
                        "token_fraction": round(tok_frac, 4),
                        "near_threshold": threshold,
                    },
                })

        # Slow ticks while any profile is near a cap; otherwise run full speed.
        self._usage_slowdown = slowdown_factor if (any_near and slowdown_factor > 1.0) else 1.0

    # ──────────────────────────────────────────────────────────────────────────
    # Chaos: random event injection
    # ──────────────────────────────────────────────────────────────────────────

    def inject_random_event(self, kind: str | None = None) -> dict:
        if kind is None:
            kind = random.choice(list(RANDOM_EVENTS.keys()))
        template = RANDOM_EVENTS.get(kind)
        if template is None:
            raise ValueError(f"Unknown event kind: {kind!r}")

        text = template["text"]
        payload: dict = {"event_kind": kind}
        extra_events: list[dict] = []

        if kind == "blackout":
            # W11b / EM-083 — a REAL blackout: disable recharge at the affected
            # places for world.blackout_ticks; surface per-place
            # structure_state_changed events alongside the random_event.
            place_ids, until, extra_events = self._world.apply_blackout()
            names = ", ".join(
                self._world.places[pid].name for pid in place_ids
                if pid in self._world.places
            ) or "nowhere"
            text = (
                f"Blackout! The power fails at {names} — recharge disabled "
                f"until tick {until}."
            )
            payload.update({"places": place_ids, "until_tick": until})
        else:
            effect_fn = template.get("_effect")
            if effect_fn:
                effect_fn(self._world)

        evt = {
            "kind": template["kind"],
            "actor_id": None,
            "profile": None,
            "profile_color": None,
            "text": text,
            "payload": payload,
        }
        self._emit_event(evt)
        for extra in extra_events:
            extra.setdefault("turn_id", None)
            self._emit_event(extra)
        self._broadcast_world_state()
        return {"kind": kind, "text": text}

    def current_snapshot(self) -> dict:
        """Return the current world_state dict (for /api/state)."""
        profile_colors = {p["name"]: p["color"] for p in self._router.legend()}
        snapshot = self._world.to_snapshot(profile_colors)
        return {
            "type": "world_state",
            "seq": self._seq,
            **snapshot,
            "profiles": self._router.legend(),
        }

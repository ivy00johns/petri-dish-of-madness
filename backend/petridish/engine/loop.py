"""
The tick/turn loop. Runs as an asyncio background task.
Coordinates: scheduler → agent runtime → persist → broadcast.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from datetime import datetime, timezone
from typing import Callable, Any

from dataclasses import asdict, is_dataclass

from .world import World, AgentState
from ..agents.runtime import AgentRuntime
from ..animals.runtime import AnimalRuntime
from ..persistence.repository import SQLiteRepository
from ..providers.router import Router
from ..config.loader import WorldConfig

log = logging.getLogger(__name__)


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
    the agents key; the projection degrades to an empty list)."""
    return json.dumps({
        "world": _world_params_json(config.world),
        "agents": [{"name": a.name, "profile": a.profile} for a in config.agents],
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
        self._last_building_round: int = 0

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

        # W11a / EM-094 — Narrator mode. The in-flight narrator call, run OFF the
        # agents' critical path (same pattern as the animal cadence) so a slow /
        # failed narrator LLM call never stalls or delays a tick. _last_narrator
        # _tick guards "at most once per every_n_ticks" — marked when scheduled,
        # so a failed call is simply skipped (no retry) until the next window.
        self._narrator_task: asyncio.Task | None = None
        self._last_narrator_tick: int = -1

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

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

            await self._execute_turn(agent)

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

        # W8 — slow-cadence chaos layer: on an `act_every_n_ticks`-aligned tick,
        # each living animal takes ONE animal turn (mostly zero-LLM reflex). It is
        # SCHEDULED as a background task (not awaited) so a slow/unreachable animal
        # LLM call never blocks this agent turn. Its events land asynchronously,
        # stamped with the tick they actually resolve on.
        self._maybe_schedule_animals()

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
                },
            })

            # Energy decay
            world.apply_energy_decay(agent)

            # Run model turn (returns domain event(s) + a `_trace` structure)
            raw_result = await self._runtime.run_turn(agent)
            trace = raw_result.get("_trace", {}) if isinstance(raw_result, dict) else {}

            # 2-6. Decision-trace spans, in order, all under this turn_id.
            self._emit_trace_chain(agent, profile_name, profile_color, trace)

            # Handle multi-event results (e.g., vote + rule_passed)
            if "_multi" in raw_result:
                events_to_emit = raw_result["_multi"]
            else:
                events_to_emit = [raw_result]

            # 7 (domain action events) — emitted between action_chosen and action_resolved.
            for evt in events_to_emit:
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
                    "routed_via": self._router.last_routed_via(profile_name),
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
        spawned_any = False
        for seed in seeds:
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

    # ──────────────────────────────────────────────────────────────────────────
    # W11a / EM-094 — Narrator mode (event-log.md v1.2.0 note 1)
    # ──────────────────────────────────────────────────────────────────────────

    # The event kinds the narrator digest is built from: deaths, governance,
    # projects/structures, conflicts, spawns, world events — NOT raw event dumps.
    _NARRATOR_DIGEST_KINDS = (
        "agent_died", "animal_died", "world_extinct", "agent_starving",
        "rule_proposed", "rule_passed", "rule_rejected",
        "project_proposed", "project_funded", "project_built",
        "building_operational", "structure_state_changed",
        "conflict", "agent_spawned", "animal_spawned", "random_event",
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

    def _narrator_digest(self, from_tick: int, to_tick: int) -> str:
        """Compact digest of the window's notable events (deaths, rules, projects,
        conflicts) for the narrator prompt — counts plus the last few feed lines,
        never a raw event dump. Free-scale: the prompt stays tiny."""
        run_id = self._run_id or 1
        try:
            rows = self._repo.get_events(
                run_id,
                from_tick=from_tick,
                to_tick=to_tick,
                kinds=list(self._NARRATOR_DIGEST_KINDS),
                order="asc",
            )
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("narrator digest query failed: %s", exc)
            rows = []
        counts: dict[str, int] = {}
        for ev in rows:
            kind = ev.get("kind") or "?"
            counts[kind] = counts.get(kind, 0) + 1
        header = ", ".join(f"{k} x{n}" for k, n in sorted(counts.items())) or "a quiet stretch"
        lines = []
        for ev in rows[-20:]:  # the most recent notable moments, capped
            text = (ev.get("text") or "").strip()
            if text:
                lines.append(f"[tick {ev.get('tick')}] {text[:140]}")
        moments = "\n".join(lines) or "(nothing notable happened)"
        alive = ", ".join(a.name for a in self._world.living_agents()) or "nobody"
        return (
            f"Window: ticks {from_tick}-{to_tick}. Living agents: {alive}.\n"
            f"Event counts: {header}.\n"
            f"Notable moments:\n{moments}"
        )

    async def _run_narrator(self, from_tick: int, to_tick: int, profile_name: str) -> None:
        """Body of one narrator window (background task): build the digest, make
        ONE LLM call, emit ONE `narrator_summary` event. A failed/timed-out call
        emits NOTHING (no retry) and never propagates — the loop never stalls."""
        try:
            digest = self._narrator_digest(from_tick, to_tick)
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are the narrator of a tiny simulated village of LLM "
                        "agents. Given a digest of the last stretch of events, "
                        "write a vivid 2-3 sentence recap in past tense. Mention "
                        "deaths, laws passed, projects, and conflicts when present; "
                        "if it was quiet, say so with charm. Reply with ONLY the "
                        "2-3 sentences — no lists, no preamble, no markdown."
                    ),
                },
                {"role": "user", "content": digest},
            ]
            profile = self._router.get_profile(profile_name)
            text = await asyncio.wait_for(
                self._router.chat(
                    profile_name,
                    messages,
                    max_tokens=min(256, getattr(profile, "max_tokens", 256) or 256),
                    temperature=0.7,
                ),
                timeout=30.0,
            )
            text = (text or "").strip()
            if not text:
                return  # an empty recap is a failed call: emit nothing
            payload = {"from_tick": from_tick, "to_tick": to_tick, "profile": profile_name}
            routed_via = self._router.last_routed_via(profile_name)
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
                "text": text[:600],
                "payload": payload,
            })
        except asyncio.CancelledError:
            raise  # reset() cancels us; propagate so the await completes
        except Exception as exc:
            # Contract: a failed/timed-out narrator call emits NOTHING, no retry.
            log.debug("narrator call failed for ticks %s-%s: %s", from_tick, to_tick, exc)

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
            llm_attempts = [{}]
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
            "seq": self._next_seq(),
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
        self._repo.save_event(run_id, stamped, tick)
        self._broadcaster(stamped)

    def _broadcast_world_state(self) -> None:
        """Send a fresh world_state snapshot over WS."""
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

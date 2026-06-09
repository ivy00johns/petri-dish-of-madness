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

from .world import World, AgentState
from ..agents.runtime import AgentRuntime
from ..persistence.repository import SQLiteRepository
from ..providers.router import Router
from ..config.loader import WorldConfig

log = logging.getLogger(__name__)

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
    "blackout": {
        "kind": "random_event",
        "text": "Blackout! Energy recharge costs double this round.",
        "_effect": lambda world: None,  # Handled by noting event; TODO: apply temporarily
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
    ):
        self._world = world
        self._runtime = runtime
        self._repo = repo
        self._router = router
        self._broadcaster = broadcaster or (lambda _: None)

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

        # sequence counter for WS messages
        self._seq: int = 0

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

    def set_speed(self, tick_interval_seconds: float) -> None:
        self._world.tick_interval_seconds = tick_interval_seconds

    def is_running(self) -> bool:
        return not self._paused

    async def reset(self, config: WorldConfig) -> None:
        """Reset world from config. Pauses loop, rebuilds state, starts new DB run."""
        self.pause()
        self._pending_steps = 0
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await asyncio.shield(asyncio.sleep(0.1))
            except asyncio.CancelledError:
                pass

        from ..engine.world import World, AgentState, PlaceState, RuleState
        from ..config.loader import AgentConfig, PlaceConfig
        import uuid

        places = [
            PlaceState(
                id=p.id, name=p.name, x=p.x, y=p.y,
                kind=p.kind, description=p.description,
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
        self._world.tick = 0
        self._world.day = 0
        self._world.running = False
        self._world.tick_interval_seconds = config.world.tick_interval_seconds
        self._world._turn_order = sorted(self._world.agents.keys())
        self._world._turn_index = 0
        self._world._round_start = True

        # Clear agent memories
        self._runtime._memory.clear()

        # New DB run
        cfg_json = json.dumps({
            "world": {k: getattr(config.world, k) for k in vars(config.world)
                      if not k.startswith("_")},
        })
        if self._run_id:
            try:
                self._repo.end_run(self._run_id)
            except Exception:
                pass
        self._run_id = self._repo.start_run(cfg_json)
        self._repo.save_places(self._run_id, places)
        for agent in agents:
            self._repo.save_agent(self._run_id, agent, 0)

        # Snapshot at tick 0 of the fresh run (structural change: reset).
        self._save_snapshot(0)

        # Broadcast new state
        self._broadcast_world_state()

    def init_run(self, config: WorldConfig) -> None:
        """One-time initialization (called at startup, not async)."""
        cfg_json = json.dumps({
            "world": {
                k: getattr(config.world, k)
                for k in vars(config.world)
                if not k.startswith("_")
            },
        })
        self._run_id = self._repo.start_run(cfg_json)
        self._repo.save_places(self._run_id, list(self._world.places.values()))
        for agent in self._world.agents.values():
            self._repo.save_agent(self._run_id, agent, 0)

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
            if self._pending_steps > 0:
                self._pending_steps -= 1
                # Only treat as a "stop after one turn" step when not running.
                step_only = self._paused
            self._step_event.clear()

            agent = self._world.next_agent()
            if agent is None:
                await asyncio.sleep(0.5)
                continue

            if not agent.alive:
                continue

            await self._execute_turn(agent)

            if step_only:
                # Single-step while paused: advance one turn, stay paused.
                self._paused = True
                self._world.running = False
            elif not self._paused:
                interval = self._world.tick_interval_seconds
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

            # Push events to agent memories
            for evt in events_to_emit:
                self._runtime.push_event({**evt, "tick": tick})

            # Advance tick
            world.tick += 1
            world.day = world.tick // world.params.turns_per_day

            # Periodic snapshot to bound replay cost (EM-054 §5).
            interval = getattr(world.params, "snapshot_interval_ticks", 25)
            if interval and world.tick % interval == 0:
                self._save_snapshot(world.tick)

            # Broadcast updated world state
            self._broadcast_world_state()
        finally:
            self._current_turn_id = None

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
        llm = trace.get("llm", {}) or {}
        reasoning = trace.get("reasoning", {}) or {}
        chosen = trace.get("action_chosen", {}) or {}

        base = {
            "actor_id": agent.id,
            "profile": profile_name,
            "profile_color": profile_color,
        }

        self._emit_event({
            **base, "kind": "perceived",
            "text": f"{agent.name} perceives the scene.",
            "payload": {
                "visible_agents": perceived.get("visible_agents", []),
                "nearby_places": perceived.get("nearby_places", []),
                "overheard": perceived.get("overheard", []),
                "perceived_summary": perceived.get("perceived_summary"),
            },
        })
        self._emit_event({
            **base, "kind": "memory_retrieved",
            "text": f"{agent.name} recalls recent events.",
            "payload": {
                "memories": memory.get("memories", []),
                "window": memory.get("window"),
            },
        })
        self._emit_event({
            **base, "kind": "llm_call",
            "text": f"{agent.name} consults {profile_name}.",
            "payload": {
                "gen_ai.request.model": llm.get("gen_ai.request.model", profile_name),
                "gen_ai.response.model": llm.get("gen_ai.response.model"),
                "gen_ai.usage.input_tokens": (llm.get("usage") or {}).get("input_tokens")
                if isinstance(llm.get("usage"), dict) else None,
                "gen_ai.usage.output_tokens": (llm.get("usage") or {}).get("output_tokens")
                if isinstance(llm.get("usage"), dict) else None,
                "latency_ms": llm.get("latency_ms"),
                "gen_ai.response.finish_reasons": (
                    [llm["finish_reason"]] if llm.get("finish_reason") else None
                ),
                "cached": llm.get("cached", False),
                "attempt": llm.get("attempt", 1),
            },
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

    # ──────────────────────────────────────────────────────────────────────────
    # Chaos: random event injection
    # ──────────────────────────────────────────────────────────────────────────

    def inject_random_event(self, kind: str | None = None) -> dict:
        if kind is None:
            kind = random.choice(list(RANDOM_EVENTS.keys()))
        template = RANDOM_EVENTS.get(kind)
        if template is None:
            raise ValueError(f"Unknown event kind: {kind!r}")

        effect_fn = template.get("_effect")
        if effect_fn:
            effect_fn(self._world)

        evt = {
            "kind": template["kind"],
            "actor_id": None,
            "profile": None,
            "profile_color": None,
            "text": template["text"],
            "payload": {"event_kind": kind},
        }
        self._emit_event(evt)
        self._broadcast_world_state()
        return {"kind": kind, "text": template["text"]}

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

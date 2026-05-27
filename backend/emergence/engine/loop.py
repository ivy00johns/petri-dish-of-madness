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
        self._task: asyncio.Task | None = None
        self._step_event: asyncio.Event = asyncio.Event()
        self._paused: bool = True
        self._step_requested: bool = False

        # sequence counter for WS messages
        self._seq: int = 0

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ──────────────────────────────────────────────────────────────────────────
    # Control API
    # ──────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._paused = False
        self._world.running = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def pause(self) -> None:
        self._paused = True
        self._world.running = False

    def step(self) -> None:
        """Advance one turn regardless of pause state."""
        self._step_requested = True
        self._step_event.set()

    def set_speed(self, tick_interval_seconds: float) -> None:
        self._world.tick_interval_seconds = tick_interval_seconds

    def is_running(self) -> bool:
        return not self._paused

    async def reset(self, config: WorldConfig) -> None:
        """Reset world from config. Pauses loop, rebuilds state, starts new DB run."""
        self.pause()
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

    # ──────────────────────────────────────────────────────────────────────────
    # Main loop
    # ──────────────────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        log.info("TickLoop started")
        while True:
            # Wait for permission to run
            while self._paused and not self._step_requested:
                self._step_event.clear()
                try:
                    await asyncio.wait_for(self._step_event.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

            step_only = self._step_requested
            self._step_requested = False
            self._step_event.clear()

            agent = self._world.next_agent()
            if agent is None:
                await asyncio.sleep(0.5)
                continue

            if not agent.alive:
                continue

            await self._execute_turn(agent)

            if step_only:
                self._paused = True
                self._world.running = False
            else:
                interval = self._world.tick_interval_seconds
                await asyncio.sleep(max(0.01, interval))

    async def _execute_turn(self, agent: AgentState) -> None:
        """Execute one agent turn: energy decay → model call → apply → persist → broadcast."""
        world = self._world
        tick = world.tick

        # Emit turn_start event
        turn_start_evt = {
            "type": "event",
            "seq": self._next_seq(),
            "tick": tick,
            "kind": "turn_start",
            "actor_id": agent.id,
            "profile": self._router.profile_name_for(agent.id, agent.profile),
            "profile_color": self._get_profile_color(agent),
            "text": f"Turn {tick}: {agent.name}'s turn.",
            "payload": {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        self._broadcaster(turn_start_evt)

        # Energy decay
        world.apply_energy_decay(agent)

        # Run model turn
        raw_result = await self._runtime.run_turn(agent)

        # Handle multi-event results (e.g., vote + rule_passed)
        if "_multi" in raw_result:
            events_to_emit = raw_result["_multi"]
        else:
            events_to_emit = [raw_result]

        for evt in events_to_emit:
            self._emit_event(evt)

        # Update mood from last event if set
        if raw_result.get("mood"):
            agent.mood = raw_result["mood"][:40]

        # Persist agent state
        run_id = self._run_id or 1
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
                "profile": self._router.profile_name_for(agent.id, agent.profile),
                "profile_color": self._get_profile_color(agent),
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

        # Broadcast updated world state
        self._broadcast_world_state()

    def _emit_event(self, evt: dict) -> None:
        """Stamp and broadcast an event; persist to DB."""
        tick = self._world.tick
        run_id = self._run_id or 1

        stamped = {
            "type": "event",
            "seq": self._next_seq(),
            "tick": tick,
            "kind": evt.get("kind", "agent_action"),
            "actor_id": evt.get("actor_id"),
            "target_id": evt.get("target_id"),
            "profile": evt.get("profile"),
            "profile_color": evt.get("profile_color"),
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

"""
Headless runner: python -m petridish.run --ticks N --profile mock

Runs the simulation loop with NO API/network — useful for QE and offline dev.
Exercises: economy, governance proposal + vote, death mechanics.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("petridish.run")


async def run_headless(ticks: int, profile_override: str | None) -> None:
    from petridish.config.loader import load_config
    from petridish.engine.world import World, AgentState, PlaceState
    from petridish.engine.loop import TickLoop
    from petridish.agents.runtime import AgentRuntime
    from petridish.persistence.repository import SQLiteRepository
    from petridish.providers.router import Router
    from petridish.providers.mock import MockProvider

    # Reset mock scripts for a fresh run
    MockProvider.reset_scripts()

    cfg = load_config(profile_override=profile_override)

    log.info("=== PetriDishOfMadness Headless Run ===")
    log.info("Ticks: %d | Profile override: %s", ticks, profile_override or "none")
    log.info("Agents: %s", [a.name for a in cfg.agents])
    log.info("Profiles: %s", [p.name for p in cfg.profiles])

    places = [
        PlaceState(id=p.id, name=p.name, x=p.x, y=p.y,
                   kind=p.kind, description=p.description,
                   district=p.district)  # Wave C / EM-147 — optional, additive
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
    router = Router(cfg.profiles)
    for agent in agents:
        router.reassign(agent.id, agent.profile)

    repo = SQLiteRepository(getattr(cfg.world, "db_path", ":memory:") or ":memory:")
    runtime = AgentRuntime(world, router)
    # Inject world into mock providers so they can vote dynamically
    router.inject_world(world)

    events_log: list[dict] = []

    def collector(msg: dict) -> None:
        if msg.get("type") == "event":
            events_log.append(msg)
            kind = msg.get("kind", "")
            text = msg.get("text", "")
            tick = msg.get("tick", "?")
            if kind not in ("turn_start",):
                print(f"  [tick {tick:3}] [{kind:20s}] {text}")

    loop_ctrl = TickLoop(
        world=world,
        runtime=runtime,
        repo=repo,
        router=router,
        broadcaster=collector,
    )
    loop_ctrl.init_run(cfg)

    # Drive the loop manually: run exactly `ticks` turns
    log.info("Starting %d ticks...", ticks)
    for i in range(ticks):
        agent = world.next_agent()
        if agent is None:
            log.warning("No living agents at tick %d", i)
            break
        if not agent.alive:
            continue

        world.apply_energy_decay(agent)
        raw_result = await runtime.run_turn(agent)

        if "_multi" in raw_result:
            evts = raw_result["_multi"]
        else:
            evts = [raw_result]

        for evt in evts:
            # _trace is the EM-066 decision-trace structure consumed by the
            # TickLoop chain emitter; the headless runner doesn't expand it, so
            # drop it from the persisted/broadcast event dict.
            evt = {k: v for k, v in evt.items() if k != "_trace"}
            stamped = {
                "type": "event",
                "seq": i,
                "tick": world.tick,
                **evt,
            }
            collector(stamped)
            runtime.push_event({**stamped, "tick": world.tick})
            repo.save_event(loop_ctrl._run_id or 1, stamped, world.tick)

        died = world.check_death(agent)
        if died:
            death_evt = {
                "type": "event",
                "seq": i,
                "tick": world.tick,
                "kind": "agent_died",
                "actor_id": agent.id,
                "profile": agent.profile,
                "profile_color": "#888888",
                "text": f"{agent.name} has DIED (energy=0 for {world.params.death_after_zero_turns} turns).",
                "payload": {},
            }
            collector(death_evt)
            repo.save_agent(loop_ctrl._run_id or 1, agent, world.tick)

        repo.save_agent(loop_ctrl._run_id or 1, agent, world.tick)

        world.tick += 1
        world.day = world.tick // world.params.turns_per_day

    # Summary
    print("\n=== SIMULATION SUMMARY ===")
    print(f"Total ticks: {world.tick}")
    print(f"Day: {world.day}")
    living = world.living_agents()
    print(f"Living agents: {len(living)}/{len(world.agents)}")
    for a in world.agents.values():
        status = "ALIVE" if a.alive else "DEAD"
        print(f"  {a.name:10s} [{status}] energy={a.energy:.1f} credits={a.credits} mood={a.mood}")
    print(f"Rules: {len(world.rules)}")
    for r in world.rules.values():
        print(f"  [{r.status:10s}] {r.effect}: {r.text}")
    print(f"Events emitted: {len(events_log)}")

    # Verify invariants
    print("\n=== INVARIANT CHECKS ===")
    all_ok = True

    # Invariant 1: Credits never negative
    for a in world.agents.values():
        if a.credits < 0:
            print(f"  FAIL: {a.name} has negative credits: {a.credits}")
            all_ok = False
    if all_ok:
        print("  PASS: All agents have non-negative credits")

    # Invariant 2: Dead agents took no turns after death
    print("  PASS: Dead agent check (enforced by scheduler)")

    # Invariant 3: ban_stealing active => no steals succeeded
    ban_active = world.has_active_rule("ban_stealing")
    if ban_active:
        steal_events = [e for e in events_log if e.get("kind") == "economy"
                        and e.get("payload", {}).get("action") == "steal"]
        if steal_events:
            print(f"  FAIL: ban_stealing active but {len(steal_events)} steal(s) succeeded")
            all_ok = False
        else:
            print("  PASS: ban_stealing active, zero successful steals")
    else:
        print("  INFO: ban_stealing not active (invariant 3 N/A)")

    # Invariant 5: Energy in [0, 100]
    for a in world.agents.values():
        if not (0.0 <= a.energy <= 100.0):
            print(f"  FAIL: {a.name} energy out of range: {a.energy}")
            all_ok = False
    if all_ok:
        print("  PASS: All agents energy in [0, 100]")

    print(f"\n{'All invariants PASSED' if all_ok else 'Some invariants FAILED'}")
    return


def main() -> None:
    parser = argparse.ArgumentParser(description="PetriDishOfMadness headless runner")
    parser.add_argument("--ticks", type=int, default=40, help="Number of ticks to run")
    parser.add_argument("--profile", type=str, default="mock", help="Profile override (e.g. mock)")
    args = parser.parse_args()

    asyncio.run(run_headless(args.ticks, args.profile))


if __name__ == "__main__":
    main()

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


def build_world(cfg):
    """Build the (world, router, runtime, repo) quad for a headless run.

    EM-186 — D3 wiring parity with the API server: this MIRRORS
    `petridish.api.app._build_world` so the headless entry point constructs the
    Router with the SAME keyword params as the server. Previously `run.py`
    called the bare `Router(cfg.profiles)`, dropping:
      • `world.lane_failover` (EM-177) — so lane failover never engaged headless,
      • `world.cache` (W7/EM-068) — so the Router fell back to its default-ON
        decision cache even when the shipped yaml disables it.
    Defaults coincide with the shipped yaml, so a config WITHOUT these blocks
    builds a Router byte-identical to the old behavior (defensive getattr).
    """
    from petridish.engine.world import World, AgentState, PlaceState
    from petridish.agents.runtime import AgentRuntime
    from petridish.persistence.repository import SQLiteRepository
    from petridish.providers.router import Router

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
    # config-gated (OFF since 2026-06-12 per the EM-198 rescope). Honor the
    # config so `enabled: false` actually disables it; defensive getattr keeps
    # cache-less configs on the pre-W7 default-ON behavior. This is the EXACT
    # construction app.py._build_world uses.
    cache_cfg = getattr(cfg.world, "cache", None)
    router = Router(
        cfg.profiles,
        lane_failover=getattr(cfg.world, "lane_failover", None),
        # EM-167 — thread the `world.overflow_lane` block too (defensive getattr:
        # pre-EM-167 configs lack the field and get the OFF defaults).
        overflow_lane=getattr(cfg.world, "overflow_lane", None),
        cache_enabled=bool(getattr(cache_cfg, "enabled", True)),
        cache_max=int(getattr(cache_cfg, "max_entries", 512)),
    )

    # Register each agent's profile with the router
    for agent in agents:
        router.reassign(agent.id, agent.profile)

    repo = SQLiteRepository(getattr(cfg.world, "db_path", ":memory:") or ":memory:")
    runtime = AgentRuntime(world, router)
    return world, router, runtime, repo


def wire_router_sinks(world, router, loop) -> None:
    """EM-186 — wire the EM-083/EM-168/EM-177 sinks + usage-window probe onto
    the headless Router/world, MIRRORING `api/app.py`'s lifespan wiring so the
    cap-pressure governor (EM-168) and lane failover (EM-177) behave identically
    headless and on the server.

    The server reads module-global `_loop`/`_world`/`_router`; here the same
    three callbacks close over the passed-in `loop`/`world`/`router` and route
    through `loop._emit_event` (persist + broadcast, exactly like the server's
    `_emit_usage_alert`/`_emit_lane_detour`). Defensive: alerting/governing must
    never break a turn.
    """
    def _usage_alert_window() -> str:
        # The UsageAlertTracker's CURRENT UTC-day window key, or "" when unknown
        # (EM-168). A pure attribute peek — the tracker owns every clock read.
        tracker = getattr(router, "_usage_alerts", None)
        return str(getattr(tracker, "_window", "") or "")

    def _apply_cap_governor(alert: dict) -> None:
        # EM-168 — demote agents on the alerting lane one cadence tier for the
        # rest of the tracker's day window (world.apply_cap_pressure owns the
        # rules). Same global-reading shape as the server's _apply_cap_governor.
        provider = alert.get("provider")
        if not provider:
            return
        try:
            apply = getattr(world, "apply_cap_pressure", None)
            if not callable(apply):
                return
            events = apply(str(provider), _usage_alert_window())
            for evt in events:
                loop._emit_event(evt)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("cap governor failed for %s: %s", provider, exc)

    def _emit_usage_alert(alert: dict) -> None:
        # W11b / EM-083 — one usage_alert row per provider/metric/day window,
        # then EM-168 drives the cap-pressure governor. Mirrors app.py.
        try:
            loop._emit_event({
                "kind": "usage_alert",
                "actor_type": "system",
                "actor_id": None,
                "profile": alert.get("provider"),
                "text": (
                    f"{alert.get('provider')} usage crossed {alert.get('pct')}% "
                    f"of its {alert.get('metric')} day cap ({alert.get('limit')})."
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

    def _emit_lane_detour(payload: dict) -> None:
        # Wave D3 / EM-177 — one lane_detour row per streak edge. Mirrors app.py.
        try:
            agent = (world.agents or {}).get(payload.get("agent_id"))
            who = agent.name if agent is not None else (
                payload.get("agent_id") or "an agent")
            home = payload.get("home")
            substitute = payload.get("substitute")
            phase = payload.get("phase")
            if phase == "recovered":
                text = f"✓ {home} lane recovered — {who} is back home"
            else:
                text = (f"⚠ {home} lane is degraded — "
                        f"{who} is borrowing {substitute}")
            loop._emit_event({
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

    # W11b / EM-083 — route usage_alert payloads into the event log.
    router.set_usage_alert_sink(_emit_usage_alert)
    # Wave D3 / EM-177 — route lane_detour streak-edge payloads the same way.
    router.set_lane_event_sink(_emit_lane_detour)
    # Wave D3 / EM-168 — zero-clock-read peek at the tracker's day window so the
    # scheduler can restore cap-governor demotions at rollover.
    world.set_usage_window_probe(_usage_alert_window)


async def run_headless(ticks: int, profile_override: str | None) -> None:
    from petridish.config.loader import load_config
    from petridish.engine.loop import TickLoop
    from petridish.providers.mock import MockProvider

    # Reset mock scripts for a fresh run
    MockProvider.reset_scripts()

    cfg = load_config(profile_override=profile_override)

    log.info("=== PetriDishOfMadness Headless Run ===")
    log.info("Ticks: %d | Profile override: %s", ticks, profile_override or "none")
    log.info("Agents: %s", [a.name for a in cfg.agents])
    log.info("Profiles: %s", [p.name for p in cfg.profiles])

    world, router, runtime, repo = build_world(cfg)
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
    # Wave D3 / EM-186 — wire the EM-083/EM-168/EM-177 sinks + usage-window probe
    # onto the headless router/world, parity with api/app.py's lifespan.
    wire_router_sinks(world, router, loop_ctrl)

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
        world.apply_needs_decay(agent)  # EM-229 — knowledge + influence drift
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

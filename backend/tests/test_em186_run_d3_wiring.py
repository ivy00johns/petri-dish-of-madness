"""
EM-186 — Headless `run.py` D3 wiring parity with the API server (`api/app.py`).

Finding: `run.py` built `Router(cfg.profiles)` WITHOUT `world.lane_failover` and
never wired the lane-event / usage-alert sinks or the usage-window probe, so the
EM-177 lane failover + the EM-168 cap-pressure governor only fully worked via the
API server. It also skipped the W7/EM-068 `world.cache` -> Router gap that
`_build_world` (app.py) already honors. These pin the headless entry point to the
SAME Router construction params + sinks/probe as the server, so headless and
server behave identically.

DEFAULT headless behavior must stay byte-identical: the shipped yaml defaults
coincide with the Router defaults, so a config WITHOUT these blocks constructs an
identical Router and wires no-op-equivalent sinks.

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime (run.py imports runtime transitively).
"""
from __future__ import annotations

import inspect

import petridish.engine.world  # noqa: F401  (import-order guard)
from petridish.config.loader import (
    CacheParams, LaneFailoverParams, ModelProfile, WorldConfig, WorldParams,
)
from petridish.providers.router import Router

import petridish.run as run_mod
# NB: `petridish/api/__init__.py` re-exports the FastAPI instance as
# `petridish.api.app`, so `import petridish.api.app as app_mod` would grab the
# app object, not the module. Import the FUNCTION directly (see test_cache_wiring).
from petridish.api.app import _build_world as _app_build_world


def _cfg(*, cache_enabled: bool = True, lane_failover=None,
         cache_max: int = 512) -> WorldConfig:
    return WorldConfig(
        world=WorldParams(
            cache=CacheParams(enabled=cache_enabled, max_entries=cache_max),
            lane_failover=lane_failover,
        ),
        profiles=[ModelProfile(name="mock", adapter="mock", model_id="mock",
                               color="#2ecc71")],
        places=[],
        agents=[],
    )


# ── Router construction parity ──────────────────────────────────────────────

def test_run_build_world_threads_lane_failover_param():
    """run.py must hand `world.lane_failover` to the Router (EM-177 failover),
    not drop it like the old `Router(cfg.profiles)` call did."""
    lf = LaneFailoverParams(sick_threshold=5)
    _world, router, _runtime, _repo = run_mod.build_world(_cfg(lane_failover=lf))
    assert router._lane_failover is lf, \
        "run.py must thread world.lane_failover into the Router"


def test_run_build_world_threads_cache_flag_and_max():
    """run.py must honor `world.cache` (W7/EM-068) exactly like app.py."""
    _world, router, _runtime, _repo = run_mod.build_world(
        _cfg(cache_enabled=False, cache_max=256))
    assert router._cache_enabled is False
    _world2, router2, _r2, _rp2 = run_mod.build_world(
        _cfg(cache_enabled=True, cache_max=256))
    assert router2._cache_enabled is True
    assert router2._cache_max == 256


def test_run_build_world_matches_app_router_params():
    """Headless and server build the Router with the SAME keyword params:
    same cache flag, same cache bound, same lane_failover object."""
    lf = LaneFailoverParams()
    cfg = _cfg(cache_enabled=False, cache_max=128, lane_failover=lf)
    _w_a, router_a, _ra, _rpa = _app_build_world(cfg)
    _w_r, router_r, _rr, _rpr = run_mod.build_world(cfg)
    assert router_a._cache_enabled == router_r._cache_enabled
    assert router_a._cache_max == router_r._cache_max
    assert router_a._lane_failover is router_r._lane_failover is lf


# ── Sink + probe parity ─────────────────────────────────────────────────────

def test_run_wire_router_sinks_registers_all_three():
    """After wiring, the Router carries the usage-alert + lane-event sinks and
    the world carries the usage-window probe — parity with app.py's lifespan."""
    from petridish.engine.loop import TickLoop

    cfg = _cfg()
    world, router, runtime, repo = run_mod.build_world(cfg)
    for agent in world.agents.values():
        router.reassign(agent.id, agent.profile)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda _m: None)
    loop.init_run(cfg)

    # Pre-condition: a freshly built router/world has no sinks/probe yet.
    assert router._usage_alert_sink is None
    assert router._lane_event_sink is None
    assert world._usage_window_probe is None

    run_mod.wire_router_sinks(world, router, loop)

    assert callable(router._usage_alert_sink), \
        "usage_alert sink must be wired (EM-083/EM-168 parity)"
    assert callable(router._lane_event_sink), \
        "lane_detour sink must be wired (EM-177 parity)"
    assert callable(world._usage_window_probe), \
        "usage-window probe must be wired (EM-168 parity)"


def test_run_usage_window_probe_reads_tracker_window():
    """The headless probe returns the Router tracker's current day window (a
    pure attribute peek, no clock read) — same contract as app.py."""
    from petridish.engine.loop import TickLoop

    cfg = _cfg()
    world, router, runtime, repo = run_mod.build_world(cfg)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda _m: None)
    loop.init_run(cfg)
    run_mod.wire_router_sinks(world, router, loop)

    router._usage_alerts._window = "2026-06-27"
    assert world._usage_window_probe() == "2026-06-27"


def test_run_lane_detour_sink_emits_event_through_loop():
    """A lane_detour payload routed to the headless sink lands as a feed event
    via loop._emit_event — same routing as app.py's _emit_lane_detour."""
    from petridish.engine.loop import TickLoop

    cfg = _cfg()
    world, router, runtime, repo = run_mod.build_world(cfg)
    captured: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=captured.append)
    loop.init_run(cfg)
    run_mod.wire_router_sinks(world, router, loop)

    router._lane_event_sink({
        "phase": "degraded", "home": "freellm", "substitute": "mock",
        "agent_id": None,
    })
    kinds = [e.get("kind") for e in captured]
    assert "lane_detour" in kinds


def test_run_usage_alert_sink_emits_event_and_drives_governor():
    """A usage_alert payload routed to the headless sink emits the feed row AND
    invokes the cap-governor (world.apply_cap_pressure) — full EM-168 parity."""
    from petridish.engine.loop import TickLoop

    cfg = _cfg()
    world, router, runtime, repo = run_mod.build_world(cfg)
    calls: list[tuple] = []
    world.apply_cap_pressure = lambda lane, window: calls.append((lane, window)) or []
    captured: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=captured.append)
    loop.init_run(cfg)
    run_mod.wire_router_sinks(world, router, loop)

    router._usage_alert_sink({
        "provider": "freellm", "metric": "rpd", "pct": 80, "limit": 1000,
    })
    kinds = [e.get("kind") for e in captured]
    assert "usage_alert" in kinds
    assert calls and calls[0][0] == "freellm", \
        "usage_alert must drive the cap-pressure governor in headless too"


# ── Signature parity guard ──────────────────────────────────────────────────

def test_run_build_world_signature_parity_with_app():
    """Both build_world helpers take a single WorldConfig and return the
    (world, router, runtime, repo) quad — so the wiring stays interchangeable."""
    run_sig = inspect.signature(run_mod.build_world)
    app_sig = inspect.signature(_app_build_world)
    assert list(run_sig.parameters) == list(app_sig.parameters)

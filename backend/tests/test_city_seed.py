"""W15 / EM-155 — the city snapshot contract (contracts/wave-d1.md §D1c).

The 3D city ring is rendered as a pure function f(snapshot, city_seed), so the
seed must be config-sourced, snapshot-persisted, fork/replay-stable, and
visible to the frontend — otherwise a replay or fork silently renders a
DIFFERENT city than the live run. These tests pin every leg of that path:

  1. config → World wiring: `world.city_seed` (yaml / WorldParams) lands on
     World.city_seed; absent key defaults to 1337; malformed values coerce.
  2. to_snapshot()/from_snapshot() round-trip: the `"city_seed"` key is
     emitted and restored int-coerced.
  3. Back-compat: a pre-W15 snapshot (no `city_seed` key) restores valid with
     the default 1337 (additive-only contract, wave-d1 rule 4).
  4. Fork path (EM-101): from_snapshot of a MID-RUN snapshot preserves the
     seed alongside tick/agents — a fork renders the same city as its parent.
  5. The WS `world_state` payload (TickLoop.current_snapshot, the same dict
     _broadcast_world_state sends) carries `city_seed` to the frontend.
  6. The shipped config/world.yaml and loader.py's EMBEDDED_WORLD_YAML mirror
     both carry the key, in sync.

Import-order idiom (test_god_voice.py): petridish.engine.world MUST be
imported before petridish.agents.runtime (circular import otherwise).
"""
from __future__ import annotations

from pathlib import Path

import yaml

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    EMBEDDED_WORLD_YAML, ModelProfile, WorldParams, _parse_world,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def _make_world(params: WorldParams | None = None) -> World:
    params = params or WorldParams()
    places = [
        PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
        PlaceState(id="market", name="Market", x=750, y=400, kind="work"),
    ]
    agents = [
        AgentState(
            id=f"agent_{i}", name=f"Agent{i}", personality="Test agent.",
            profile="mock", location="plaza",
            energy=params.starting_energy, credits=params.starting_credits,
        )
        for i in range(2)
    ]
    return World(params=params, places=places, agents=agents)


# ── 1. config → World wiring ──────────────────────────────────────────────────

def test_world_params_default_city_seed_is_1337():
    assert WorldParams().city_seed == 1337
    assert _make_world().city_seed == 1337


def test_yaml_city_seed_flows_config_to_world():
    params, _, _ = _parse_world({"world": {"city_seed": 4242}})
    assert params.city_seed == 4242
    world = _make_world(params)
    assert world.city_seed == 4242
    assert world.to_snapshot()["city_seed"] == 4242


def test_yaml_absent_city_seed_defaults_1337():
    params, _, _ = _parse_world({"world": {"agent_count": 3}})
    assert params.city_seed == 1337


def test_world_coerces_malformed_params_city_seed():
    # Defensive engine-side coercion: a duck-typed params dict with a junk
    # value must not crash World construction (mirrors _block_get reads).
    class _Junk:
        tick_interval_seconds = 0.5
        city_seed = "not-a-number"

    world = World(_Junk(), [PlaceState(id="p", name="P", x=0, y=0, kind="social")], [])
    assert world.city_seed == 1337


# ── 2. snapshot round-trip ────────────────────────────────────────────────────

def test_snapshot_round_trip_preserves_city_seed():
    params = WorldParams(city_seed=99)
    world = _make_world(params)
    snap = world.to_snapshot()
    assert snap["city_seed"] == 99
    restored = World.from_snapshot(snap)
    assert restored.city_seed == 99
    # And it re-emits on the next snapshot (fork's tick-0 world_state).
    assert restored.to_snapshot()["city_seed"] == 99


def test_from_snapshot_int_coerces_city_seed():
    snap = _make_world().to_snapshot()
    snap["city_seed"] = "7"
    assert World.from_snapshot(snap).city_seed == 7
    snap["city_seed"] = {"bogus": True}  # malformed → safe default
    assert World.from_snapshot(snap).city_seed == 1337


# ── 3. back-compat: pre-W15 snapshot without the key ─────────────────────────

def test_pre_w15_snapshot_without_city_seed_stays_valid():
    legacy_snapshot = {
        "tick": 7,
        "day": 0,
        "places": [
            {"id": "plaza", "name": "Central Plaza", "x": 500, "y": 500,
             "kind": "social"},
        ],
        "agents": [
            {"id": "a1", "name": "Ada", "personality": "", "profile": "mock",
             "location": "plaza", "energy": 50.0, "credits": 5, "alive": True},
        ],
    }
    world = World.from_snapshot(legacy_snapshot)
    assert world.tick == 7
    assert world.city_seed == 1337  # frontend's `city_seed ?? 1337` matches


# ── 4. fork path: mid-run snapshot preserves the seed ─────────────────────────

def test_fork_of_mid_run_snapshot_preserves_city_seed():
    world = _make_world(WorldParams(city_seed=2026))
    # Advance into a "mid-run" state: ticks, a round, some mutation.
    world.tick = 42
    world.day = 2
    world.round = 5
    agent = next(iter(world.agents.values()))
    world.action_forage(agent)
    snap = world.to_snapshot()

    # The fork endpoint's seam: World.from_snapshot(replay(T)) — with and
    # without parent params threaded (app.py signature-sniffs `params`).
    fork_default_params = World.from_snapshot(snap)
    assert fork_default_params.city_seed == 2026
    fork_with_params = World.from_snapshot(snap, params=WorldParams(city_seed=2026))
    assert fork_with_params.city_seed == 2026
    assert fork_with_params.tick == 42
    # The snapshot is authoritative over params (same rule as places): a fork
    # under a since-edited config still renders the parent run's city.
    fork_edited_config = World.from_snapshot(snap, params=WorldParams(city_seed=1))
    assert fork_edited_config.city_seed == 2026


# ── 5. the world_state payload carries it to the frontend ────────────────────

def test_world_state_payload_carries_city_seed():
    world = _make_world(WorldParams(tick_interval_seconds=0.02, city_seed=777))
    mock = MockProvider(script=[{"action": "idle", "args": {}}])
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock},
    )
    for a in world.agents.values():
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop._run_id = 1

    # current_snapshot() builds the SAME {"type": "world_state", **to_snapshot}
    # dict that _broadcast_world_state sends over the WS and that /api/state
    # returns — one source of truth, so this pins the frontend seam.
    payload = loop.current_snapshot()
    assert payload["type"] == "world_state"
    assert payload["city_seed"] == 777

    # And the broadcast path itself emits the key.
    sent: list[dict] = []
    loop._broadcaster = sent.append
    loop._broadcast_world_state()
    assert sent and sent[-1]["type"] == "world_state"
    assert sent[-1]["city_seed"] == 777


# ── 6. shipped config + embedded mirror stay in sync ─────────────────────────

def test_shipped_yaml_and_embedded_mirror_both_carry_city_seed():
    embedded_params, _, _ = _parse_world(yaml.safe_load(EMBEDDED_WORLD_YAML))
    shipped_raw = yaml.safe_load((REPO_CONFIG_DIR / "world.yaml").read_text())
    assert "city_seed" in (shipped_raw.get("world") or {})
    shipped_params, _, _ = _parse_world(shipped_raw)
    assert embedded_params.city_seed == shipped_params.city_seed == 1337

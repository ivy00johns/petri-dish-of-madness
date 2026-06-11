"""
Wave D3 / B3 gate tests — EM-171: the EM-162 cache-key normalization,
extended (BACKGROUND tier only) and RE-MEASURED.

Wave D2's EM-162 (energy bucketed to 10s + day-floored tick) measured a 0%
realized cache hit rate in integration, for three reasons this suite locks
the fixes for:

  1. the day-floored tick still missed — a 25-turn round spans >1 in-world
     day at 20 turns/day, so consecutive background due turns (~10 rounds
     apart) NEVER share a day ⇒ the tick line is DROPPED from background
     prompts (the town line survives — it changes once per naming vote).
  2. memory lines embedded raw ticks — an agent's own last-turn memory made
     every prompt unique ⇒ background memory lines render de-ticked.
  3. menu target lists churned with dict insertion order ⇒ background
     co-located rosters and building/project menus render in sorted order.

HARD INVARIANT: protagonist (and supporting) prompts stay byte-identical to
pre-diet behavior — guarded by the em161_protagonist_prompt_pre_diet.txt
fixture test in test_wave_d2_prompt_diet.py (runs in the same suite).

The re-measure (the EM-171 deliverable): the integration test at the bottom
drives REAL AgentRuntime.run_turn turns for a background agent across 12
due turns spaced 250 ticks (~12.5 in-world days) apart — the realistic
background cadence — through a real Router with a fake NON-mock adapter
(mock lanes are uncacheable by design), and asserts Router.cache_stats()
shows hits > 0. Realized: 11 hits / 1 miss = 91.7% on equivalent situations
(1 adapter call for 12 turns).

Deterministic and offline (scripted fakes, no network, no real keys).
House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

import asyncio
import json

from petridish.engine.world import (
    World, AgentState, PlaceState, RuleState, Building,
)
from petridish.config.loader import ModelProfile, WorldParams
from petridish.agents.runtime import AgentRuntime, _assemble_context
from petridish.providers.router import Router


IDLE = {"action": "idle", "args": {}}

_PLACES: list[tuple[str, str, int, int, str, str]] = [
    ("plaza", "Central Plaza", 500, 500, "social", "core"),
    ("market", "Market Hall", 697, 303, "work", "market"),
    ("forge", "The Steelworks", 894, 303, "work", "market"),
    ("home", "Hearth House", 106, 697, "home", "residential"),
    ("townhall", "City Hall", 106, 106, "governance", "civic"),
]


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        memory_window=8,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _places() -> list[PlaceState]:
    return [PlaceState(id=i, name=n, x=x, y=y, kind=k, district=d)
            for (i, n, x, y, k, d) in _PLACES]


def _agent(aid: str, name: str, *, tier: str, location: str = "market",
           energy: float = 78.0, credits: int = 12,
           profile: str = "mock") -> AgentState:
    return AgentState(id=aid, name=name, personality="Quiet, watchful.",
                      profile=profile, location=location, energy=energy,
                      credits=credits, cadence_tier=tier)


def _world(agents: list[AgentState], tick: int = 47) -> World:
    world = World(params=_params(), places=_places(), agents=agents)
    world.tick = tick
    return world


def _events(n: int = 15) -> list[dict]:
    return [{"tick": t, "text": f"event {t} happened", "kind": "agent_action",
             "seq": t} for t in range(1, n + 1)]


def _prompt(world: World, agent: AgentState,
            events: list[dict] | None = None) -> str:
    msgs = _assemble_context(
        agent, world, _events() if events is None else events, world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ──────────────────────────────────────────────────────────────────────────────
# 1. The tick line is DROPPED from background prompts (cause 1)
# ──────────────────────────────────────────────────────────────────────────────

def test_background_prompt_has_no_tick_line():
    world = _world([
        _agent("hero", "Hero", tier="protagonist"),
        _agent("sup_01", "Supporter", tier="supporting"),
        _agent("bg_01", "Bystander", tier="background"),
    ])
    bg = _prompt(world, world.agents["bg_01"])
    assert "Tick:" not in bg
    assert "day 2" not in bg          # the EM-162 day-floored form is gone too
    # Protagonist AND supporting keep the exact tick line, byte-for-byte.
    assert "Tick: 47\n" in _prompt(world, world.agents["hero"])
    assert "Tick: 47\n" in _prompt(world, world.agents["sup_01"])


def test_background_keeps_town_line_despite_tick_drop():
    """The town line rode the tick line in the template; the drop must not
    take the town's name with it (it changes once per naming vote, so it is
    cache-stable)."""
    world = _world([
        _agent("hero", "Hero", tier="protagonist"),
        _agent("bg_01", "Bystander", tier="background"),
    ])
    world.town_name = "Bramblewick"
    bg = _prompt(world, world.agents["bg_01"])
    assert "Town: Bramblewick" in bg
    assert "Tick:" not in bg
    hero = _prompt(world, world.agents["hero"])
    assert "Tick: 47\nTown: Bramblewick" in hero


# ──────────────────────────────────────────────────────────────────────────────
# 2. Background memory lines render de-ticked (cause 2)
# ──────────────────────────────────────────────────────────────────────────────

def test_background_memory_lines_deticked():
    world = _world([
        _agent("hero", "Hero", tier="protagonist"),
        _agent("bg_01", "Bystander", tier="background"),
    ])
    bg = _prompt(world, world.agents["bg_01"])
    assert "[tick" not in bg
    assert "  - event 15 happened" in bg
    assert "  - event 8 happened" in bg        # window still 8 (EM-161)
    assert "event 7 happened" not in bg
    # Protagonist keeps the stamped form byte-for-byte.
    hero = _prompt(world, world.agents["hero"])
    assert "  [tick 15] event 15 happened" in hero


def test_background_memory_bytes_stable_while_ticks_drift():
    """The agent's own last-turn memory: same texts, fresh tick stamps —
    the background render is byte-identical; the protagonist render is not."""
    bg = _agent("bg_solo", "Solo", tier="background", location="home")
    world = _world([bg], tick=41)
    events_a = [{"tick": 30 + i, "text": "Solo idles.", "kind": "agent_action"}
                for i in range(8)]
    events_b = [{"tick": 280 + i, "text": "Solo idles.", "kind": "agent_action"}
                for i in range(8)]
    msgs_a = _assemble_context(bg, world, events_a, world.params)
    world.tick = 291                  # ~12.5 in-world days later (10 rounds)
    bg.energy = 77.4                  # drifted within the ~70 bucket
    msgs_b = _assemble_context(bg, world, events_b, world.params)
    assert json.dumps(msgs_a, sort_keys=True) == json.dumps(msgs_b, sort_keys=True)

    # Protagonist control: the SAME drift changes the prompt.
    bg.cadence_tier = "protagonist"
    world.tick = 41
    bg.energy = 78.0
    pro_a = _assemble_context(bg, world, events_a, world.params)
    world.tick = 291
    bg.energy = 77.4
    pro_b = _assemble_context(bg, world, events_b, world.params)
    assert pro_a != pro_b


# ──────────────────────────────────────────────────────────────────────────────
# 3. Background menu/roster lists render in stable sorted order (cause 3)
# ──────────────────────────────────────────────────────────────────────────────

def test_background_roster_sorted_and_insertion_order_invariant():
    def build(order: list[AgentState]) -> World:
        return _world(order)

    bg_a = _agent("bg_01", "Bystander", tier="background")
    zed_a = _agent("zed", "Zed", tier="background")
    amy_a = _agent("amy", "Amy", tier="background")
    world_a = build([bg_a, zed_a, amy_a])

    bg_b = _agent("bg_01", "Bystander", tier="background")
    zed_b = _agent("zed", "Zed", tier="background")
    amy_b = _agent("amy", "Amy", tier="background")
    world_b = build([bg_b, amy_b, zed_b])     # different insertion order

    prompt_a = _prompt(world_a, world_a.agents["bg_01"])
    prompt_b = _prompt(world_b, world_b.agents["bg_01"])
    assert prompt_a == prompt_b, "equivalent rosters must render identical bytes"
    # ...and the roster is in sorted (name) order.
    coloc = prompt_a.split("CO-LOCATED AGENTS ===")[1].split("=== RECENT")[0]
    assert coloc.index("Amy (id=amy") < coloc.index("Zed (id=zed")

    # Protagonist control: insertion order still shows (behavior unchanged).
    world_a.agents["bg_01"].cadence_tier = "protagonist"
    world_b.agents["bg_01"].cadence_tier = "protagonist"
    assert (_prompt(world_a, world_a.agents["bg_01"])
            != _prompt(world_b, world_b.agents["bg_01"]))


def test_background_project_and_building_menus_sorted_by_id():
    def build(order: list[str]) -> World:
        world = _world([
            _agent("hero", "Hero", tier="protagonist"),
            _agent("bg_01", "Bystander", tier="background"),
        ])
        specs = {
            "b1": ("Spice Stall", "planned", 10, 50),
            "b2": ("Market Awning", "under_construction", 20, 20),
            "b3": ("Forge Annex", "under_construction", 5, 30),
        }
        for bid in order:
            name, status, have, need = specs[bid]
            world.buildings[bid] = Building(
                id=bid, name=name, kind="workshop", location="market",
                status=status, funds_committed=have, funds_required=need)
        return world

    world_a = build(["b3", "b1", "b2"])
    world_b = build(["b2", "b3", "b1"])
    prompt_a = _prompt(world_a, world_a.agents["bg_01"])
    prompt_b = _prompt(world_b, world_b.agents["bg_01"])
    assert prompt_a == prompt_b, "equivalent menus must render identical bytes"
    projects = prompt_a.split("ACTIVE PROJECTS")[1].split("=== ACTIVE RULES")[0]
    assert (projects.index("id=b1 ") < projects.index("id=b2 ")
            < projects.index("id=b3 "))
    buildings = prompt_a.split("BUILDINGS HERE ===")[1].split("=== ACTIVE PROJECTS")[0]
    assert (buildings.index("id=b1 ") < buildings.index("id=b2 ")
            < buildings.index("id=b3 "))

    # Protagonist control: insertion order still shows (behavior unchanged).
    hero_a = _prompt(world_a, world_a.agents["hero"])
    hero_projects = hero_a.split("ACTIVE PROJECTS")[1].split("=== ACTIVE RULES")[0]
    assert hero_projects.index("id=b3 ") < hero_projects.index("id=b1 ")


# ──────────────────────────────────────────────────────────────────────────────
# 4. THE RE-MEASURE — realized cache hit rate through real run_turn turns
# ──────────────────────────────────────────────────────────────────────────────

class StubAdapter:
    """Fake NON-mock adapter (the existing router-test idiom): mock lanes are
    uncacheable by design, so the cache can only be measured through a lane
    the router believes is real."""
    name = "lane"
    color = "#fff"
    last_routed_via = "stub-model"
    last_usage = {"input_tokens": 10, "output_tokens": 5,
                  "latency_ms": 1.0, "finish_reason": "stop"}

    def __init__(self):
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls.append(messages)
        return json.dumps(IDLE)


def _cacheable_harness(tier: str):
    agent = _agent("bg_solo", "Solo", tier=tier, location="home",
                   profile="lane")
    world = _world([agent], tick=41)
    # An open proposed rule keeps every background due turn salient
    # (uncast_vote) WITHOUT touching the prompt — the vote menu only renders
    # at a governance place, and only ACTIVE rules ride the rules block.
    world.rules["r1"] = RuleState(id="r1", effect="ubi", text="Daily bread",
                                  proposer_id="bg_solo", status="proposed")
    adapter = StubAdapter()
    profiles = [ModelProfile(name="lane", adapter="openai", model_id="m",
                             color="#fff")]
    router = Router(profiles, adapter_overrides={"lane": adapter})
    runtime = AgentRuntime(world, router)
    # Saturate the 8-event background memory window with the agent's own
    # past turns (distinct raw ticks — the cause-2 churn) so every assembled
    # prompt carries a full, equivalent window.
    for t in range(1, 9):
        runtime.push_event({"kind": "agent_action", "actor_id": agent.id,
                            "tick": t, "text": "Solo idles.", "payload": {}})
    return world, runtime, router, adapter, agent


def _drive_turns(world, runtime, agent, n: int) -> None:
    for i in range(n):
        world.tick = 41 + i * 250                  # ~12.5 days per due turn
        agent.energy = 78.0 if i % 2 == 0 else 77.4  # drifts within ~70 bucket
        evt = asyncio.run(runtime.run_turn(agent))
        primary = evt["_multi"][0] if "_multi" in evt else evt
        assert primary.get("kind") != "parse_failure", primary
        # Mimic the loop: the turn's own event lands in the agent's memory
        # (this is exactly the raw-tick churn EM-171 normalizes away).
        runtime.push_event({"kind": "agent_action", "actor_id": agent.id,
                            "tick": world.tick, "text": "Solo idles.",
                            "payload": {}})


def test_em171_realized_cache_hit_rate_background():
    """THE EM-171 deliverable: 12 equivalent background due turns spaced 250
    ticks apart hit the decision cache 11 times (1 real adapter call) —
    a 91.7% realized hit rate on equivalent situations, up from 0%."""
    world, runtime, router, adapter, agent = _cacheable_harness("background")
    n_turns = 12
    _drive_turns(world, runtime, agent, n_turns)

    stats = router.cache_stats()
    assert stats["hits"] > 0, "EM-171 must realize actual cache hits"
    assert stats == {"hits": n_turns - 1, "misses": 1, "entries": 1}
    assert len(adapter.calls) == 1, "turns 2..12 must be served from cache"
    hit_rate = stats["hits"] / (stats["hits"] + stats["misses"])
    assert hit_rate > 0.9, f"realized hit rate {hit_rate:.1%}"


def test_em171_cached_turns_carry_cached_flag_in_trace():
    """A cache-served turn stays legible: its llm_call span reports
    cached=true (the EM-068 snapshot path, unchanged by EM-171)."""
    world, runtime, router, adapter, agent = _cacheable_harness("background")
    _drive_turns(world, runtime, agent, 2)
    world.tick = 41 + 2 * 250
    agent.energy = 78.0
    evt = asyncio.run(runtime.run_turn(agent))
    attempts = evt["_trace"]["llm_attempts"]
    assert attempts and attempts[0]["cached"] is True


def test_protagonist_control_never_hits_cache():
    """The control proving the normalization is tier-scoped: the SAME drive
    for a protagonist (exact tick line + stamped memory) misses every time."""
    world, runtime, router, adapter, agent = _cacheable_harness("protagonist")
    _drive_turns(world, runtime, agent, 4)
    stats = router.cache_stats()
    assert stats["hits"] == 0
    assert stats["misses"] == 4
    assert len(adapter.calls) == 4

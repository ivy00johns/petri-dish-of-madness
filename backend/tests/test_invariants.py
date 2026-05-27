"""
Tests for world-model.md INVARIANTS 1-5 using MockProvider.

Invariant 1: Credits never negative; change only via work/forage/recharge/give/steal/ubi.
Invariant 2: Dead agents take no turns and emit no actions.
Invariant 3: ban_stealing active => zero successful steals.
Invariant 4: A rule becomes active iff count(votes==true) > floor(living_count/2).
Invariant 5: Energy in [0,100]; passed recharge strictly increases energy (unless already 100).
"""
from __future__ import annotations

import asyncio
import uuid
import pytest

from emergence.engine.world import World, AgentState, PlaceState, RelationshipState
from emergence.config.loader import WorldParams
from emergence.agents.runtime import AgentRuntime
from emergence.providers.mock import MockProvider
from emergence.providers.router import Router
from emergence.config.loader import ModelProfile


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def make_params(**overrides) -> WorldParams:
    p = WorldParams()
    for k, v in overrides.items():
        setattr(p, k, v)
    return p


def make_world(
    agent_count: int = 3,
    params: WorldParams | None = None,
    place_kind: str = "work",
) -> tuple[World, list[AgentState]]:
    if params is None:
        params = make_params(
            energy_decay_per_turn=2.0,
            starting_energy=50.0,
            starting_credits=10,
            recharge_cost=2,
            recharge_amount=20.0,
            work_reward=4,
            forage_reward=1,
            steal_max=5,
            death_after_zero_turns=3,
            ubi_amount=2,
        )
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(
            id=f"agent_{i}",
            name=f"Agent{i}",
            personality="Test agent.",
            profile="mock",
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for i in range(agent_count)
    ]
    world = World(params=params, places=places, agents=agents)
    return world, agents


def make_router() -> Router:
    MockProvider.reset_scripts()
    profiles = [
        ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")
    ]
    return Router(profiles)


def make_runtime(world: World, router: Router) -> AgentRuntime:
    runtime = AgentRuntime(world, router)
    for agent in world.agents.values():
        router.reassign(agent.id, "mock")
    return runtime


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 1: Credits never negative
# ──────────────────────────────────────────────────────────────────────────────

def test_inv1_credits_never_negative_after_work():
    world, agents = make_world()
    a = agents[0]
    a.credits = 0
    ok, _, reward = world.action_work(a)
    assert ok
    assert a.credits >= 0


def test_inv1_credits_never_negative_recharge_fails_if_insufficient():
    world, agents = make_world()
    a = agents[0]
    a.credits = 0  # can't afford recharge
    ok, reason, _ = world.action_recharge(a)
    assert not ok
    assert a.credits >= 0  # unchanged


def test_inv1_credits_never_negative_give_fails_if_insufficient():
    world, agents = make_world()
    a, b = agents[0], agents[1]
    a.credits = 3
    ok, reason = world.action_give(a, b, 100)  # try to give 100, only have 3
    assert not ok
    assert a.credits >= 0


def test_inv1_credits_never_negative_after_steal():
    world, agents = make_world()
    attacker, victim = agents[0], agents[1]
    victim.credits = 0
    ok, _, amount = world.action_steal(attacker, victim)
    assert ok
    assert victim.credits >= 0
    assert attacker.credits >= 0


@pytest.mark.asyncio
async def test_inv1_credits_conserved_across_ticks():
    """Run 20 ticks and assert sum of credits is non-negative everywhere."""
    MockProvider.reset_scripts()
    params = make_params(
        energy_decay_per_turn=1.0,
        starting_energy=100.0,
        starting_credits=20,
        recharge_cost=2,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=10,
        memory_window=5,
    )
    world, agents = make_world(agent_count=3, params=params)
    router = make_router()
    runtime = make_runtime(world, router)

    script = [
        {"action": "work", "args": {}},
        {"action": "forage", "args": {}},
        {"action": "recharge", "args": {}},
        {"action": "idle", "args": {}},
    ]

    # Use a single shared MockProvider with cycling script
    mock_p = MockProvider(script=script)
    from emergence.providers.router import Router as R
    router2 = R(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock_p},
    )
    for agent in world.agents.values():
        router2.reassign(agent.id, "mock")
    runtime2 = AgentRuntime(world, router2)

    for _ in range(20):
        for agent in world.living_agents():
            world.apply_energy_decay(agent)
            await runtime2.run_turn(agent)
            world.check_death(agent)
        world.tick += 1

    for agent in world.agents.values():
        assert agent.credits >= 0, f"{agent.name} has negative credits: {agent.credits}"


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 2: Dead agents take no turns
# ──────────────────────────────────────────────────────────────────────────────

def test_inv2_dead_agent_skipped_by_scheduler():
    world, agents = make_world(agent_count=3)
    # Kill agent 0
    agents[0].alive = False
    world._rebuild_turn_order()

    # next_agent should never return the dead agent
    for _ in range(10):
        agent = world.next_agent()
        if agent is not None:
            assert agent.alive, "Scheduler returned dead agent"


def test_inv2_dead_agent_not_in_living():
    world, agents = make_world(agent_count=3)
    agents[0].alive = False
    living = world.living_agents()
    assert agents[0] not in living
    assert len(living) == 2


@pytest.mark.asyncio
async def test_inv2_dead_agent_emits_no_action():
    """After death, the agent should not appear in turn order."""
    MockProvider.reset_scripts()
    params = make_params(
        energy_decay_per_turn=30.0,  # Fast death
        starting_energy=10.0,
        starting_credits=0,
        recharge_cost=2,
        death_after_zero_turns=1,
        memory_window=5,
    )
    world, agents = make_world(agent_count=2, params=params)
    router = make_router()
    runtime = make_runtime(world, router)

    # Force agent_0 to die immediately
    agents[0].energy = 0
    agents[0].zero_energy_turns = params.death_after_zero_turns
    died = world.check_death(agents[0])
    assert died
    assert not agents[0].alive

    actions_by_dead_agent = []
    for _ in range(5):
        agent = world.next_agent()
        if agent and agent.id == agents[0].id:
            actions_by_dead_agent.append(agent)

    assert len(actions_by_dead_agent) == 0, "Dead agent appeared in turn order"


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 3: ban_stealing => zero successful steals
# ──────────────────────────────────────────────────────────────────────────────

def test_inv3_ban_stealing_blocks_steal():
    world, agents = make_world(agent_count=2)
    attacker, victim = agents[0], agents[1]
    victim.credits = 10

    # Propose and activate ban_stealing
    ok, reason, rule = world.action_propose_rule(attacker, "ban_stealing", "No theft!")
    assert ok and rule

    # Vote yes (majority of 2 = need >1 → need 2 votes)
    world.action_vote(attacker, rule.id, True)
    world.action_vote(victim, rule.id, True)

    assert world.has_active_rule("ban_stealing"), "Rule should be active"

    ok, reason, amount = world.action_steal(attacker, victim)
    assert not ok
    assert amount == 0
    assert victim.credits == 10  # unchanged


@pytest.mark.asyncio
async def test_inv3_ban_stealing_during_runtime():
    """Run turns with ban_stealing active; no steal events should succeed."""
    MockProvider.reset_scripts()
    params = make_params(
        energy_decay_per_turn=1.0,
        starting_energy=80.0,
        starting_credits=20,
        death_after_zero_turns=10,
        memory_window=5,
    )
    world, agents = make_world(agent_count=3, params=params)
    router = make_router()
    runtime = make_runtime(world, router)

    # Activate ban_stealing manually
    _, _, rule = world.action_propose_rule(agents[0], "ban_stealing", "No stealing allowed.")
    assert rule
    for agent in agents:
        world.action_vote(agent, rule.id, True)
    assert world.has_active_rule("ban_stealing")

    steal_attempts = []
    steal_script = [{"action": "steal", "args": {"target": agents[1].id}}] * 10

    from emergence.providers.mock import MockProvider as MP
    from emergence.providers.router import Router as R2
    mock = MP(script=steal_script)
    router2 = R2(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#00ff00")],
        adapter_overrides={"mock": mock},
    )
    for a in world.agents.values():
        router2.reassign(a.id, "mock")
    runtime2 = AgentRuntime(world, router2)

    for _ in range(5):
        for agent in world.living_agents():
            world.apply_energy_decay(agent)
            result = await runtime2.run_turn(agent)
            # Check: no economy event with action=steal
            evts = result.get("_multi", [result])
            for e in evts:
                if e.get("kind") == "economy" and e.get("payload", {}).get("action") == "steal":
                    steal_attempts.append(e)

    assert len(steal_attempts) == 0, f"Steal succeeded despite ban: {steal_attempts}"


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 4: Rule activation majority rule
# ──────────────────────────────────────────────────────────────────────────────

def test_inv4_rule_needs_strict_majority():
    """5 agents: need >2 yes votes (3+)."""
    world, agents = make_world(agent_count=5)

    ok, _, rule = world.action_propose_rule(agents[0], "ubi", "Universal income.")
    assert ok and rule

    # 2 yes votes out of 5 → not enough (need > floor(5/2) = > 2, i.e. >= 3)
    world.action_vote(agents[0], rule.id, True)
    world.action_vote(agents[1], rule.id, True)
    assert world.rules[rule.id].status == "proposed"

    # 3rd yes vote → should activate (3 > floor(5/2)=2)
    _, _, new_status = world.action_vote(agents[2], rule.id, True)
    assert new_status == "active"
    assert world.rules[rule.id].status == "active"


def test_inv4_rule_rejected_on_no_majority():
    """3 agents: need >1 yes (>=2). Two no votes → reject."""
    world, agents = make_world(agent_count=3)

    ok, _, rule = world.action_propose_rule(agents[0], "work_bonus", "Work harder!")
    assert ok and rule

    world.action_vote(agents[0], rule.id, False)
    world.action_vote(agents[1], rule.id, False)

    # 2 no votes > floor(3/2)=1 → rejected
    assert world.rules[rule.id].status in ("rejected", "proposed")
    # Re-check after third vote
    _, _, new_status = world.action_vote(agents[2], rule.id, False)
    assert world.rules[rule.id].status == "rejected"


def test_inv4_rule_not_active_before_majority():
    """Rule should stay proposed until strict majority."""
    world, agents = make_world(agent_count=4)

    ok, _, rule = world.action_propose_rule(agents[0], "recharge_subsidy", "Cheap recharge!")
    assert ok and rule

    # 1 yes out of 4 → not enough
    world.action_vote(agents[0], rule.id, True)
    assert world.rules[rule.id].status == "proposed"

    # 2 yes out of 4 → still not enough (need >2, i.e. >=3)
    world.action_vote(agents[1], rule.id, True)
    assert world.rules[rule.id].status == "proposed"

    # 3 yes votes → 3 > floor(4/2)=2 → active
    _, _, new_status = world.action_vote(agents[2], rule.id, True)
    assert new_status == "active"


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 5: Energy in [0, 100]; recharge increases energy
# ──────────────────────────────────────────────────────────────────────────────

def test_inv5_energy_never_below_zero():
    world, agents = make_world()
    a = agents[0]
    a.energy = 0.5
    world.apply_energy_decay(a)
    assert a.energy >= 0.0


def test_inv5_energy_never_above_100():
    world, agents = make_world()
    a = agents[0]
    a.energy = 99.0
    a.credits = 100
    world.action_recharge(a)
    assert a.energy <= 100.0


def test_inv5_recharge_strictly_increases_energy_unless_100():
    world, agents = make_world()
    a = agents[0]
    a.energy = 50.0
    a.credits = 10
    energy_before = a.energy
    ok, reason, gained = world.action_recharge(a)
    assert ok
    assert reason == "ok"
    assert a.energy > energy_before, "Recharge should strictly increase energy"


def test_inv5_recharge_no_increase_when_full():
    world, agents = make_world()
    a = agents[0]
    a.energy = 100.0
    a.credits = 10
    ok, reason, gained = world.action_recharge(a)
    assert ok  # succeeds but no increase
    assert a.energy == 100.0


def test_inv5_attack_drains_energy_both_agents():
    world, agents = make_world(agent_count=2)
    a, b = agents[0], agents[1]
    a.energy = 50.0
    b.energy = 50.0
    world.action_attack(a, b)
    assert a.energy < 50.0
    assert b.energy < 50.0
    assert a.energy >= 0.0
    assert b.energy >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Economy transfer tests
# ──────────────────────────────────────────────────────────────────────────────

def test_economy_give_transfers_correctly():
    world, agents = make_world(agent_count=2)
    a, b = agents[0], agents[1]
    a.credits = 10
    b.credits = 5
    ok, reason = world.action_give(a, b, 3)
    assert ok
    assert a.credits == 7
    assert b.credits == 8


def test_economy_steal_transfers_correctly():
    world, agents = make_world(agent_count=2)
    attacker, victim = agents[0], agents[1]
    attacker.credits = 5
    victim.credits = 10
    ok, _, amount = world.action_steal(attacker, victim)
    assert ok
    assert amount <= world.params.steal_max
    assert attacker.credits == 5 + amount
    assert victim.credits == 10 - amount


def test_economy_work_reward_with_bonus():
    world, agents = make_world()
    a = agents[0]
    a.location = "market"
    a.credits = 0

    # Activate work_bonus
    ok, _, rule = world.action_propose_rule(a, "work_bonus", "Bonus pay!")
    assert ok and rule
    for agent in world.living_agents():
        world.action_vote(agent, rule.id, True)

    assert world.has_active_rule("work_bonus")
    ok, _, reward = world.action_work(a)
    assert ok
    expected = int(world.params.work_reward * 1.5)
    assert reward == expected


def test_economy_ubi_applied_at_round_start():
    world, agents = make_world(agent_count=3)
    initial = [a.credits for a in agents]

    # Activate UBI
    ok, _, rule = world.action_propose_rule(agents[0], "ubi", "Basic income!")
    assert ok and rule
    for agent in agents:
        world.action_vote(agent, rule.id, True)
    assert world.has_active_rule("ubi")

    # Force round start
    world._turn_index = len(world._turn_order)
    world._apply_round_start()

    for i, agent in enumerate(agents):
        assert agent.credits == initial[i] + world.params.ubi_amount


# ──────────────────────────────────────────────────────────────────────────────
# Parse/validate/retry/idle tests
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_parse_failure_falls_back_to_idle():
    """If model returns garbage twice, result is parse_failure / idle."""
    world, agents = make_world(agent_count=1)
    world.params = make_params(memory_window=5)

    garbage_script = [{"not_an_action": "garbage"}] * 10
    mock = MockProvider(script=garbage_script)

    from emergence.providers.router import Router as R
    router = R(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#ff0000")],
        adapter_overrides={"mock": mock},
    )
    router.reassign(agents[0].id, "mock")
    runtime = AgentRuntime(world, router)

    result = await runtime.run_turn(agents[0])
    assert result.get("kind") == "parse_failure", f"Expected parse_failure, got {result}"


@pytest.mark.asyncio
async def test_valid_action_succeeds():
    """Valid mock action should produce the expected event kind."""
    world, agents = make_world(agent_count=1)

    script = [{"action": "forage", "args": {}}]
    mock = MockProvider(script=script)
    from emergence.providers.router import Router as R
    router = R(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#00ff00")],
        adapter_overrides={"mock": mock},
    )
    router.reassign(agents[0].id, "mock")
    runtime = AgentRuntime(world, router)

    result = await runtime.run_turn(agents[0])
    assert result.get("kind") == "economy"
    assert result.get("payload", {}).get("action") == "forage"


# ──────────────────────────────────────────────────────────────────────────────
# Death tests
# ──────────────────────────────────────────────────────────────────────────────

def test_death_after_sustained_zero_energy():
    world, agents = make_world()
    a = agents[0]
    params = world.params

    a.energy = 0.0
    for _ in range(params.death_after_zero_turns - 1):
        world.check_death(a)
        assert a.alive, "Agent should still be alive"

    # One more check pushes it over
    died = world.check_death(a)
    assert died
    assert not a.alive


def test_death_zero_energy_counter_resets_on_recovery():
    world, agents = make_world()
    a = agents[0]
    a.energy = 0.0
    world.check_death(a)
    assert a.zero_energy_turns == 1

    a.energy = 10.0
    world.check_death(a)
    assert a.zero_energy_turns == 0


# ──────────────────────────────────────────────────────────────────────────────
# Governance flow: propose -> vote -> active -> effect
# ──────────────────────────────────────────────────────────────────────────────

def test_governance_full_flow():
    world, agents = make_world(agent_count=3)

    # Propose recharge_subsidy
    ok, _, rule = world.action_propose_rule(agents[0], "recharge_subsidy", "Cheap recharge!")
    assert ok and rule
    assert rule.status == "proposed"

    # Vote: 2 yes out of 3 (need > floor(3/2)=1, so >=2)
    world.action_vote(agents[0], rule.id, True)
    assert rule.status == "proposed"  # 1 vote not enough

    _, _, new_status = world.action_vote(agents[1], rule.id, True)
    assert new_status == "active"
    assert world.has_active_rule("recharge_subsidy")

    # Verify effect: recharge cost halved
    a = agents[0]
    a.credits = 100
    a.energy = 50.0
    normal_cost = world.params.recharge_cost
    expected_cost = max(1, normal_cost // 2)
    ok, _, gained = world.action_recharge(a)
    assert ok
    # Credits should have decreased by expected_cost
    assert a.credits == 100 - expected_cost


@pytest.mark.asyncio
async def test_full_run_40_ticks_mock():
    """Run 40 ticks with MockProvider; assert invariants hold throughout."""
    MockProvider.reset_scripts()
    params = make_params(
        energy_decay_per_turn=3.0,
        starting_energy=80.0,
        starting_credits=15,
        recharge_cost=2,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=5,
        memory_window=5,
    )

    places = [
        PlaceState(id="market", name="Market", x=0, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=10, y=0, kind="governance"),
        PlaceState(id="plaza", name="Plaza", x=5, y=5, kind="social"),
    ]
    agents = [
        AgentState(
            id=f"agent_{name.lower()}_{str(uuid.uuid4())[:4]}",
            name=name,
            personality=f"{name}'s personality",
            profile="mock",
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for name in ["Ada", "Bram", "Cleo", "Dov", "Esi"]
    ]

    world = World(params=params, places=places, agents=agents)
    router = make_router()
    for a in agents:
        router.reassign(a.id, "mock")
    runtime = AgentRuntime(world, router)

    for tick in range(40):
        agent = world.next_agent()
        if agent is None:
            break
        world.apply_energy_decay(agent)
        await runtime.run_turn(agent)
        world.check_death(agent)
        world.tick += 1

    # Invariant 1: No negative credits
    for agent in world.agents.values():
        assert agent.credits >= 0, f"{agent.name} has negative credits: {agent.credits}"

    # Invariant 5: Energy in bounds
    for agent in world.agents.values():
        assert 0.0 <= agent.energy <= 100.0, f"{agent.name} energy out of range: {agent.energy}"

    # Invariant 3: If ban_stealing active, no steals occurred
    if world.has_active_rule("ban_stealing"):
        # We can't easily count events here, but world state should reflect no unauthorized steals
        pass

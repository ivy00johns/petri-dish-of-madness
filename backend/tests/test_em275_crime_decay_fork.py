"""EM-275 — resume/fork must not fire an extra crime-decay pass (EM-155).

The loop runs advance_buildings + EM-240 advance_crime once per round, gated on
`_last_building_round`. That field was initialized to a flat 0 and never restored,
so a loop rebuilt around an already-advanced world (resume/fork at round R>0) saw
`R > 0` and fired one EXTRA per-round pass — decaying notoriety / clearing
`wanted` a second time — that the continuous run had already done before the
snapshot. It is now DERIVED from the world's current round.

At snapshot time _advance_round_buildings always ran BEFORE the save, so
`_last_building_round == world.round`; the derivation reproduces exactly that.
"""

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _resumed(round_, notoriety):
    """A world restored at `round_` (as from_snapshot leaves it) wrapped in a
    FRESH loop — exactly the resume/fork wiring (app._spin_up_run_from_world)."""
    crook = AgentState(id="crook", name="Crook", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20,
                       notoriety=notoriety)
    world = World(params=_params(),
                  places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                  agents=[crook])
    world.round = round_
    world.tick = round_ * 3
    router = Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                  color="#2ecc71")],
                    adapter_overrides={"mock": MockProvider()})
    router.reassign(crook.id, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    loop = TickLoop(world=world, runtime=runtime, repo=SQLiteRepository(":memory:"),
                    router=router, broadcaster=lambda _m: None)
    return world, loop


def test_last_building_round_is_derived_from_the_resumed_round():
    _world, loop = _resumed(round_=5, notoriety=50)
    assert loop._last_building_round == 5      # NOT a flat 0


def test_fresh_world_still_starts_at_zero():
    _world, loop = _resumed(round_=0, notoriety=50)
    assert loop._last_building_round == 0


def test_resume_does_not_fire_an_extra_decay_pass():
    world, loop = _resumed(round_=5, notoriety=50)
    loop._advance_round_buildings()            # round 5 already advanced pre-snapshot
    assert world.agents["crook"].notoriety == 50   # untouched — no extra pass


def test_stale_zero_would_have_double_decayed():
    # Pin the pre-fix starting value to show the divergence the derivation prevents.
    world, loop = _resumed(round_=5, notoriety=50)
    loop._last_building_round = 0
    loop._advance_round_buildings()
    assert world.agents["crook"].notoriety == 48   # extra notoriety_decay (2) fired

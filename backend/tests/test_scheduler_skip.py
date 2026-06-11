"""
Wave D3 / B3 gate tests — EM-172.

1. Mid-round-death scheduler skip (pre-existing since 58a8e7e, surfaced by
   the 25-agent chaos run): `World._rebuild_turn_order` prunes dead agents
   from the current round's rotation, but the rotation pointer
   (`_turn_index`) was not shifted back for pruned entries that sat BEFORE
   it — so a death mid-round silently skipped the next due agent's turn that
   round. The fix decrements the pointer once per pruned pre-cursor.
   `test_mid_round_death_before_pointer_skips_no_one` REPRODUCES the skip:
   it fails on pre-fix code (revert the `_turn_index` decrement in
   world._rebuild_turn_order to see it return "c" where "b" is due).

2. Energy-band hysteresis (EM-159 salience trigger): recharge-to-full
   flapping across a band edge (99.x ⇄ 100) re-triggered `energy_band`
   salience every drift, inflating background LLM turns. The band now only
   flips once energy crosses the seen band's boundary by more than the
   _ENERGY_BAND_HYSTERESIS margin.

Deterministic and offline (no network, no LLM calls).
House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import ModelProfile, WorldParams
from petridish.agents.runtime import (
    AgentRuntime, _energy_band_flipped, _ENERGY_BAND_HYSTERESIS,
)
from petridish.providers.router import Router


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        memory_window=8,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _places() -> list[PlaceState]:
    return [PlaceState(id="plaza", name="Central Plaza", x=500, y=500,
                       kind="social")]


def _agent(aid: str, tier: str = "protagonist", energy: float = 80.0) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="plaza", energy=energy, credits=20,
                      cadence_tier=tier)


def _world(ids=("a", "b", "c", "d")) -> World:
    return World(params=_params(), places=_places(),
                 agents=[_agent(i) for i in ids])


# ──────────────────────────────────────────────────────────────────────────────
# 1. EM-172 — mid-round-death scheduler skip
# ──────────────────────────────────────────────────────────────────────────────

def test_mid_round_death_before_pointer_skips_no_one():
    """THE regression reproduction: the agent who just acted dies (it sits
    BEFORE the rotation pointer). Pre-fix, pruning it shifted the remaining
    rotation left while the pointer stayed put, so "b" — the next due agent —
    was silently skipped and "c" acted instead."""
    world = _world()
    assert world.next_agent().id == "a"
    world.agents["a"].alive = False        # dies mid-round, after acting
    assert world.next_agent().id == "b"    # pre-fix: returned "c" (b skipped)
    assert world.next_agent().id == "c"
    assert world.next_agent().id == "d"
    assert world.round == 1                # all of that was ONE round


def test_every_living_due_agent_acts_exactly_once_despite_two_deaths():
    """Two pre-cursor deaths in the same round: every still-living due agent
    gets exactly one turn that round, and the next round rotates only the
    survivors — again exactly once each."""
    world = _world(("a", "b", "c", "d", "e"))
    acted = [world.next_agent().id, world.next_agent().id]   # a, b act
    world.agents["a"].alive = False
    world.agents["b"].alive = False                          # both die mid-round
    acted += [world.next_agent().id for _ in range(3)]
    assert acted == ["a", "b", "c", "d", "e"]
    assert world.round == 1
    nxt = [world.next_agent().id for _ in range(3)]          # round 2
    assert nxt == ["c", "d", "e"]
    assert world.round == 2


def test_death_of_next_due_agent_advances_to_following():
    """The agent AT the pointer dies before its turn: no decrement applies
    (its successor slides into the pointer's slot) — the following agent
    acts and nobody is double-served."""
    world = _world()
    assert world.next_agent().id == "a"
    world.agents["b"].alive = False        # the very next due agent dies
    assert world.next_agent().id == "c"
    assert world.next_agent().id == "d"
    assert world.round == 1


def test_death_after_pointer_unchanged():
    """A death AFTER the pointer (an agent that has not yet acted, further
    down the rotation) needs no pointer shift — the behavior is unchanged."""
    world = _world()
    assert world.next_agent().id == "a"
    world.agents["c"].alive = False
    assert world.next_agent().id == "b"
    assert world.next_agent().id == "d"
    assert world.round == 1


def test_tail_death_still_ends_round_cleanly():
    """The last actor of a round dies after acting: the pointer decrement
    must not break round-boundary detection — the next round starts with the
    living set, exactly once each."""
    world = _world(("a", "b", "c"))
    assert [world.next_agent().id for _ in range(3)] == ["a", "b", "c"]
    world.agents["c"].alive = False
    assert world.round == 1
    assert world.next_agent().id == "a"    # round 2 begins with the survivors
    assert world.round == 2
    assert world.next_agent().id == "b"
    assert world.next_agent().id == "a"    # round 3
    assert world.round == 3


def test_midround_death_with_tiered_due_set():
    """The fix holds on a tiered due set too (EM-158): round 1's due set is
    the protagonists only; a mid-round protagonist death never skips a due
    protagonist."""
    agents = [_agent(i) for i in ("a", "b", "c")]
    agents.append(_agent("z_bg", tier="background"))
    world = World(params=_params(), places=_places(), agents=agents)
    assert world.next_agent().id == "a"    # round 1 due set: a, b, c
    world.agents["a"].alive = False
    assert world.next_agent().id == "b"    # pre-fix: skipped to "c"
    assert world.next_agent().id == "c"
    assert world.round == 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. EM-172 — energy-band hysteresis on the EM-159 salience trigger
# ──────────────────────────────────────────────────────────────────────────────

def _baselined_bg(energy: float):
    bg = _agent("agent_bg", tier="background", energy=energy)
    world = World(params=_params(), places=_places(), agents=[bg])
    router = Router([ModelProfile(name="mock", adapter="mock",
                                  model_id="mock", color="#2ecc71")])
    runtime = AgentRuntime(world, router)
    runtime._note_llm_turn(bg)   # records the energy-band baseline
    return world, runtime, bg


def test_recharge_to_full_flapping_is_quiet():
    """The live flap: full ⇄ just-below-full across the top band edge no
    longer triggers energy_band salience in either direction."""
    world, runtime, bg = _baselined_bg(100.0)
    bg.energy = 96.0                       # drifts just below the 100 edge
    salient, triggers = runtime._background_salience(bg)
    assert not salient and "energy_band" not in triggers
    bg.energy = 100.0                      # recharges back to full
    assert not runtime._background_salience(bg)[0]
    # ...and from the OTHER side: a band-3 baseline recharging to full is
    # within the margin of its own upper edge — also quiet.
    world2, runtime2, bg2 = _baselined_bg(96.0)
    bg2.energy = 100.0
    assert not runtime2._background_salience(bg2)[0]


def test_band_flip_beyond_margin_still_fires():
    world, runtime, bg = _baselined_bg(100.0)
    bg.energy = 100.0 - _ENERGY_BAND_HYSTERESIS - 1.0   # 94: past the margin
    salient, triggers = runtime._background_salience(bg)
    assert salient and "energy_band" in triggers


def test_genuine_band_crossing_unchanged():
    """A real drift (band 3 → band 1, far past any margin) still fires —
    the hysteresis must never mute genuine salience."""
    world, runtime, bg = _baselined_bg(80.0)
    bg.energy = 30.0
    salient, triggers = runtime._background_salience(bg)
    assert salient and "energy_band" in triggers


def test_lower_edge_margin_quiet_then_fires():
    world, runtime, bg = _baselined_bg(78.0)   # band 3 (75..100)
    bg.energy = 72.0                           # band 2, within 5 of the 75 edge
    assert not runtime._background_salience(bg)[0]
    bg.energy = 69.0                           # past the margin
    salient, triggers = runtime._background_salience(bg)
    assert salient and "energy_band" in triggers


def test_energy_band_flipped_helper_edges():
    # Same band ⇒ never flipped, margin irrelevant.
    assert not _energy_band_flipped(80.0, 3)
    # Within margin of either edge of the seen band ⇒ not flipped.
    assert not _energy_band_flipped(72.0, 3)     # 75-edge, inside margin
    assert not _energy_band_flipped(100.0, 3)    # 100-edge, inside margin
    assert not _energy_band_flipped(96.0, 4)     # top band, inside margin
    # Past the margin ⇒ flipped.
    assert _energy_band_flipped(69.9, 3)
    assert _energy_band_flipped(94.0, 4)
    # Garbage energy clamps like _energy_band does (0.0 ⇒ band 0).
    assert _energy_band_flipped("not-a-number", 3)
    assert not _energy_band_flipped("not-a-number", 0)

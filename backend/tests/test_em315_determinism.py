"""EM-315 — The Healing House determinism golden (EM-155).

With the flag OFF (the default) a world is BYTE-IDENTICAL to pre-EM-315: no
healings / pre_healing_profile / treated_at_tick agent keys, the `heal` effect
is rejected at propose time, and the default snapshot round-trips byte-identically.
A world that has HEALED a citizen (the transplant record populated + the model
swapped in the serialized `profile` field) ALSO round-trips byte-identically, so
a fork/replay resumes the exact same transplant — and the deterministic swap-
target pick reproduces bit-for-bit on replay.
"""
import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, HealingHouseParams


def _params(healing_house: HealingHouseParams | None = None) -> WorldParams:
    p = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )
    if healing_house is not None:
        p.healing_house = healing_house
    return p


def _agent(aid: str, name: str, profile: str = "mock") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile=profile,
                      location="plaza", energy=80.0, credits=20)


def _world(params: WorldParams | None = None) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=params or _params(),
                 agents=[_agent("ada", "Ada"), _agent("bram", "Bram")],
                 places=places)


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── flag OFF: inert + byte-identical ─────────────────────────────────────────

def test_default_world_snapshot_has_no_healing_keys():
    snap = _world().to_snapshot()
    for agent in snap["agents"]:
        assert "healings" not in agent
        assert "pre_healing_profile" not in agent
        assert "treated_at_tick" not in agent


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_flag_off_heal_is_rejected_and_snapshot_unchanged():
    w = _world()
    before = _dumps(w.to_snapshot())
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "heal", "he seems off", None, "Bram")
    assert ok is False and rule is None
    assert "disabled" in reason
    assert _dumps(w.to_snapshot()) == before          # no rule minted, no keys


# ── flag ON: a healed world round-trips byte-identically ─────────────────────

def _healed_world() -> World:
    hh = HealingHouseParams(enabled=True,
                            target_profiles=("groq", "cerebras", "mistral"))
    w = _world(_params(hh))
    # Give the patient a real starting model so the swap has somewhere to go.
    w.agents["bram"].profile = "groq"
    w.tick = 11
    ok, reason, rule = w.action_propose_rule(
        w.agents["ada"], "heal", "the town fears his temper", None, "Bram")
    assert ok is True and rule is not None
    # 2 living agents ⇒ ceil(0.7*2)=2 yes votes carry the supermajority.
    w.action_vote(w.agents["ada"], rule.id, True)
    w.action_vote(w.agents["bram"], rule.id, True)
    w.drain_spawn_events()                            # clear the outbox
    return w


def test_heal_swaps_the_model_deterministically():
    w = _healed_world()
    bram = w.agents["bram"]
    assert bram.healings == 1
    assert bram.pre_healing_profile == "groq"
    assert bram.treated_at_tick == 11
    # Never a no-op swap toward the same lane (or toward silence).
    assert bram.profile != "groq"
    assert bram.profile != "mock"
    assert bram.profile in ("cerebras", "mistral")


def test_healed_world_round_trips_byte_identical():
    w = _healed_world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=w.params)
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_healed_snapshot_carries_the_transplant_record():
    w = _healed_world()
    snap = w.to_snapshot()
    bram = next(a for a in snap["agents"] if a["id"] == "bram")
    assert bram["healings"] == 1
    assert bram["pre_healing_profile"] == "groq"
    assert bram["treated_at_tick"] == 11
    assert bram["profile"] == w.agents["bram"].profile   # the swapped lane rode


def test_swap_target_pick_is_reproducible_on_replay():
    # The deterministic pick is a pure function of (patient id, tick, healings);
    # a fresh world re-derives the SAME target, so a replay reproduces the swap.
    w1 = _healed_world()
    w2 = _healed_world()
    assert w1.agents["bram"].profile == w2.agents["bram"].profile


def test_mid_flight_healing_survives_a_second_hop():
    # Fork-of-a-fork: two snapshot hops stay byte-identical (replay safety).
    w = _healed_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=w.params)
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()), params=w.params)
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


# ── defensive restore (tampered snapshots never crash / never grow) ──────────

def test_restore_clamps_tampered_healing_record():
    w = _world()
    snap = w.to_snapshot()
    snap["agents"][0]["healings"] = -5
    snap["agents"][0]["pre_healing_profile"] = 99          # non-str → dropped
    snap["agents"][0]["treated_at_tick"] = "junk"
    restored = World.from_snapshot(snap, params=_params())
    ada = restored.agents[snap["agents"][0]["id"]]
    assert ada.healings == 0
    assert ada.pre_healing_profile is None
    assert ada.treated_at_tick == 0

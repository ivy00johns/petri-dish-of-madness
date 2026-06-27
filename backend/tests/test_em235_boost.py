"""EM-235 — Boost queue (Wave M3).

Agents spend credits to buy extra scheduled turns (EW's ComputeCredits) — they
literally purchase influence over the shared timeline (the north-star: MORE
turns/LLM calls, never fewer).

  * A reflex verb `buy_turn` deducts `world.boost.cost` credits (REJECTED when the
    agent is too poor) and grants the agent ONE extra scheduled turn by bumping a
    durable per-agent counter `boosted_turns`. Zero extra LLM calls at purchase —
    the buy rides the agent's existing turn; the EXTRA turn it grants is a real
    new scheduled turn (the whole point).

  * The scheduler (`next_agent`) honors the counter: when a round's due rotation
    is exhausted, any agent with `boosted_turns > 0` is appended an extra slot
    (sorted by id for determinism — same-seed runs schedule identically) and the
    counter is decremented as that slot is consumed, BEFORE the round rolls over.

  * A per-agent per-round cap (`world.boost.max_per_round`) bounds how many extra
    turns one agent may buy in a single round.

Invariants pinned here (the wave's hard rules):
  * EM-155 — the new AgentState `boosted_turns` field is ADDITIVE + serialized
    only-when-non-zero: a world with no boosts round-trips byte-identically, and a
    world WITH a parked boost survives a snapshot/restore (the boost is NOT
    dropped on fork/resume — it is durable counter state, not a transient outbox).
  * em161 golden — `buy_turn` surfaces in the prompt menu ONLY when the boost is
    configured (cost > 0). A default world (the absent block) never shows the line
    and `buy_turn` is a no-op → byte-identical.
  * determinism — the extra-slot ordering is a pure sorted-by-id append; no
    random, no clock. Same-seed runs schedule identically.
  * config-absent no-op — cost <= 0 (the default, and any world.yaml without the
    block) rejects every buy: no credits move, no boost is granted, the scheduler
    is untouched.
  * EM-172 — granting a boost never disturbs the mid-round-death `_turn_index`
    fix or the cadence tiers (the extra slot is appended AFTER the due set).
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, BoostParams
from petridish.agents.runtime import _assemble_context


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _boost_params(cost=10, max_per_round=2, **kw):
    p = _params(**kw)
    p.boost = BoostParams(cost=cost, max_per_round=max_per_round)
    return p


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="forge", name="Forge", x=1, y=0, kind="work"),
    ]


def _world(agents, params=None):
    return World(params=params or _params(), places=_places(), agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── buy_turn: deducts credits + grants a boost ────────────────────────────────

def test_buy_turn_deducts_cost_and_grants_a_boost():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    evt = w.action_buy_turn(a)
    assert evt["kind"] == "turn_boosted"
    assert a.credits == 40                 # 50 - 10 cost
    assert a.boosted_turns == 1            # one extra turn queued


def test_buy_turn_rejected_when_too_poor():
    a = _agent(id="a", name="Ann", credits=5)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    evt = w.action_buy_turn(a)
    assert evt["kind"] != "turn_boosted"
    assert a.credits == 5                  # no credits moved on rejection
    assert a.boosted_turns == 0            # no boost granted


def test_buy_turn_is_noop_when_boost_unconfigured():
    # Default params: no boost block (cost defaults to 0 = OFF). A buy is a no-op
    # rejection — config-absent never moves credits or schedules a turn.
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a])
    evt = w.action_buy_turn(a)
    assert evt["kind"] != "turn_boosted"
    assert a.credits == 50
    assert a.boosted_turns == 0


def test_buy_turn_respects_per_round_cap():
    a = _agent(id="a", name="Ann", credits=500)
    w = _world([a], _boost_params(cost=10, max_per_round=2))
    e1 = w.action_buy_turn(a)
    e2 = w.action_buy_turn(a)
    e3 = w.action_buy_turn(a)              # over the per-round cap → rejected
    assert e1["kind"] == "turn_boosted"
    assert e2["kind"] == "turn_boosted"
    assert e3["kind"] != "turn_boosted"
    assert a.boosted_turns == 2            # only two within the cap
    assert a.credits == 480                # only two charged (500 - 2*10)


def test_per_round_cap_resets_each_round():
    # The cap is PER round: after a round boundary the agent may buy again.
    a = _agent(id="a", name="Ann", credits=500)
    w = _world([a], _boost_params(cost=10, max_per_round=1))
    assert w.action_buy_turn(a)["kind"] == "turn_boosted"
    assert w.action_buy_turn(a)["kind"] != "turn_boosted"   # cap hit this round
    # Drain the boost + advance a round so the per-round counter resets.
    w.next_agent()                          # consumes the normal slot
    w.next_agent()                          # consumes the boosted slot
    w.next_agent()                          # rolls into the next round
    assert w.action_buy_turn(a)["kind"] == "turn_boosted"   # fresh round → allowed


# ── the scheduler honors the boost (the whole point: MORE turns) ──────────────

def test_boost_grants_an_extra_scheduled_turn():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    # Without the boost a lone protagonist acts once per round; WITH it she acts
    # an extra time before the round rolls over.
    first = w.next_agent()
    second = w.next_agent()
    assert first.id == "a"
    assert second.id == "a"                # the extra (boosted) turn
    assert a.boosted_turns == 0            # the counter was consumed


def test_boosted_turn_is_extra_not_a_replacement():
    # In a two-agent round, Ann's boost gives her a THIRD slot after Bea, not in
    # place of Bea — the boost ADDS a turn (north-star), never steals one.
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    order = [w.next_agent().id for _ in range(3)]
    assert order == ["a", "b", "a"]        # a, b (the due set), then a's boost
    assert a.boosted_turns == 0


def test_multiple_boosts_grant_multiple_extra_turns():
    a = _agent(id="a", name="Ann", credits=500)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    w.action_buy_turn(a)
    order = [w.next_agent().id for _ in range(3)]
    assert order == ["a", "a", "a"]        # normal + two boosted slots
    assert a.boosted_turns == 0


def test_boosts_are_genuine_extra_turns_not_folded_into_next_round():
    # The load-bearing distinction (a lone-agent test can hide it): with TWO agents
    # and Ann holding two boosts, the round serves a, b (the due set) then a, a
    # (Ann's two EXTRA slots) BEFORE the round rolls back to a, b. The boosts ADD
    # turns within the round; they are NOT silently absorbed into the next round's
    # normal turn (the north-star: MORE turns, deterministically).
    a = _agent(id="a", name="Ann", credits=500)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    w.action_buy_turn(a)
    order = [w.next_agent().id for _ in range(6)]
    assert order == ["a", "b", "a", "a", "a", "b"]   # due set, 2 boosts, then next round
    assert a.boosted_turns == 0


def test_restored_boost_serves_normal_round_first():
    # A boost parked at snapshot time is honored AFTER the restored world's first
    # normal round (a boosted agent never pre-empts the due set on resume).
    import copy
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot()), params=_boost_params())
    order = [restored.next_agent().id for _ in range(3)]
    assert order == ["a", "b", "a"]        # normal round (a, b) THEN a's boost


def test_scheduler_extra_slots_are_deterministic_by_id():
    # Two agents each holding a boost → the extra slots append in SORTED id order
    # (alpha before zeta), identically across same-seed runs (no random/clock).
    def _order():
        a = _agent(id="zeta", name="Zeta", credits=50)
        b = _agent(id="alpha", name="Alpha", credits=50)
        w = _world([a, b], _boost_params(cost=10, max_per_round=3))
        w.action_buy_turn(a)
        w.action_buy_turn(b)
        return [w.next_agent().id for _ in range(4)]
    first = _order()
    # The due set is sorted (alpha, zeta); the boosted slots also sorted.
    assert first == ["alpha", "zeta", "alpha", "zeta"]
    assert _order() == first                # byte-identical across runs


def test_boost_for_dead_agent_is_skipped():
    # An agent that dies before its boosted slot is consumed never gets a phantom
    # turn (fail-safe): the dead agent is pruned from the rotation.
    a = _agent(id="a", name="Ann", credits=50)
    b = _agent(id="b", name="Bea", credits=50)
    w = _world([a, b], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    w.next_agent()                          # a's normal turn
    a.alive = False                         # Ann dies mid-round
    nxt = w.next_agent()                    # b's turn (a's boost is skipped)
    assert nxt.id == "b"
    # No phantom dead 'a' turn surfaces afterward.
    after = w.next_agent()
    assert after is None or after.id != "a" or after.alive


# ── snapshot round-trip (EM-155 / EM-190) ─────────────────────────────────────

def test_no_boost_state_round_trips_byte_identical():
    a = _agent(credits=20)
    w = _world([a])
    snap = w.to_snapshot()
    assert "boosted_turns" not in json.dumps(snap)     # field absent when 0
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_boosted_turns_survive_snapshot_restore():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    w.action_buy_turn(a)
    snap = w.to_snapshot()
    assert json.dumps(snap).count('"boosted_turns"') >= 1
    restored = World.from_snapshot(copy.deepcopy(snap), params=_boost_params())
    assert restored.agents["a"].boosted_turns == 2


def test_boost_snapshot_is_stable_byte_identical():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    w.action_buy_turn(a)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_boost_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_boosted_turns_coerced():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a])
    snap = w.to_snapshot()
    # Tamper the agent dict with a garbage value → defensive restore clamps to 0.
    snap["agents"][0]["boosted_turns"] = "nonsense"
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["a"].boosted_turns == 0
    # A negative value also clamps to 0 (never a "negative boost").
    snap2 = w.to_snapshot()
    snap2["agents"][0]["boosted_turns"] = -5
    restored2 = World.from_snapshot(snap2, params=_params())
    assert restored2.agents["a"].boosted_turns == 0


# ── prompt menu: conditional (em161 golden) ───────────────────────────────────

def test_buy_turn_line_absent_without_boost_config():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a])                          # default params: no boost block
    sys = _sys(a, w)
    assert "buy_turn" not in sys


def test_buy_turn_line_present_when_boost_enabled():
    a = _agent(id="a", name="Ann", credits=50)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    sys = _sys(a, w)
    assert "buy_turn" in sys


def test_buy_turn_line_absent_when_too_poor_to_afford():
    # Offered only when the agent can actually afford the cost (menu/resolution
    # agree — no dangling line the validator would reject).
    a = _agent(id="a", name="Ann", credits=3)
    w = _world([a], _boost_params(cost=10, max_per_round=3))
    sys = _sys(a, w)
    assert "buy_turn" not in sys


# ── config-absent default ─────────────────────────────────────────────────────

def test_boost_params_default_is_off():
    p = WorldParams()
    assert isinstance(p.boost, BoostParams)
    assert p.boost.cost == 0                 # default OFF (no-op)


def test_default_world_scheduler_unaffected_by_boost_machinery():
    # A default world's lone protagonist still acts exactly once per round — the
    # boost machinery adds nothing when no boost was bought (golden-safe path).
    a = _agent(id="a", name="Ann", credits=20)
    w = _world([a])
    first = w.next_agent()
    second = w.next_agent()
    assert first.id == "a"
    assert second.id == "a"                  # the NEXT round's turn, not a boost
    assert a.boosted_turns == 0

"""EM-279 — memory consolidation ("sleep") is reachable at defaults.

The EM-233 belief WRITERS (action_remember / action_deceive) FIFO-capped beliefs
at a hardcoded 20 while consolidate_memory fires only when len(beliefs) > 20 (==
the default consolidate_at). 20 > 20 is never true, so the digest/sleep path never
ran. The writer cap now sits ONE above the ceiling (config-derived), so beliefs
can exceed it and the round-boundary sweep actually consolidates.
"""

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, MemoryParams


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _world(agents, memory=None):
    p = _params()
    if memory is not None:
        p.memory = memory
    return World(params=p,
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def test_fifo_cap_sits_one_above_the_consolidation_ceiling():
    # Default ceiling is 20 → the writer cap is 21, so beliefs CAN exceed 20.
    w = _world([_agent()])
    assert w._belief_fifo_cap() == 21
    # And it tracks a non-default ceiling (the hardcoded 20 broke consolidate_at>20).
    w2 = _world([_agent()], memory=MemoryParams(consolidate_at=30))
    assert w2._belief_fifo_cap() == 31


def test_remember_lets_beliefs_exceed_the_default_ceiling():
    a = _agent()
    w = _world([a])
    for i in range(25):
        w.action_remember(a, f"fact {i}")
    # Pre-fix this pinned at 20 forever; now it rides the 21 cap (> the ceiling).
    assert len(a.beliefs) == 21


def test_round_boundary_consolidation_now_fires_at_defaults():
    a = _agent()
    w = _world([a])
    for i in range(25):
        w.action_remember(a, f"fact {i}")
    assert len(a.beliefs) > int(w._memory_param("consolidate_at", 20))  # reachable

    events = w.consolidate_memories()          # the round-boundary sweep
    assert len(events) == 1 and events[0]["kind"] == "memory"
    # Oldest folded into ONE digest; the keep_recent tail survives verbatim.
    keep = int(w._memory_param("consolidate_keep_recent", 8))
    assert a.beliefs[0].startswith("[consolidated")
    assert len(a.beliefs) == 1 + keep


def test_deceive_writer_also_respects_the_raised_cap():
    liar = _agent(id="liar", name="Liar")
    mark = _agent(id="mark", name="Mark")
    w = _world([liar, mark])
    for i in range(25):
        w.action_deceive(liar, mark, f"claim {i}")
    assert len(mark.beliefs) == w._belief_fifo_cap() == 21

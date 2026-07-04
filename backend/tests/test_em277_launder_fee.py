"""EM-277 — launder can no longer cool heat for free.

`action_launder` truncated the fee with int(), so any amount whose cut rounds
below 1 (amount <= 3 at the default 0.3 cut) charged 0 credits yet still cut
notoriety by the full 8 and could clear a `wanted` flag — a free, infinitely
repeatable heat wash. The fee now floors at 1 credit, so every launder costs.
"""

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    return World(params=_params(),
                 places=[PlaceState(id="alley", name="Alley", x=0, y=0, kind="social")],
                 agents=agents)


def _crook(**kw):
    base = dict(id="crook", name="Crook", personality="", profile="mock",
                location="alley", energy=80.0)
    base.update(kw)
    return AgentState(**base)


def test_tiny_launder_now_costs_at_least_one_credit():
    crook = _crook(credits=10, notoriety=30)
    w = _world([crook])
    ok, reason, fee = w.action_launder(crook, 3)   # int(3 * 0.3) == 0 pre-fix
    assert ok
    assert fee == 1                                # floored, not free
    assert crook.credits == 9                      # actually charged
    assert crook.notoriety == 22                   # 8-point cut still applies


def test_repeated_tiny_launder_is_bounded_by_credits_not_free():
    crook = _crook(credits=3, notoriety=90)
    w = _world([crook])
    # Each launder now costs >=1, so a 3-credit crook can wash at most 3 times.
    charged = 0
    for _ in range(10):
        ok, _r, fee = w.action_launder(crook, 1)
        if not ok:
            break
        charged += fee
    assert crook.credits == 0
    assert charged == 3                            # not an unbounded free loop


def test_wanted_clear_now_has_a_price():
    crook = _crook(credits=5, notoriety=8, crime_status="wanted")
    w = _world([crook])
    ok, _r, fee = w.action_launder(crook, 2)       # int(2 * 0.3) == 0 pre-fix
    assert ok and fee == 1
    assert crook.credits == 4                       # paid for the wash
    assert crook.notoriety == 0
    assert crook.crime_status != "wanted"           # cleared — but not for free


def test_large_launder_fee_unchanged():
    crook = _crook(credits=100, notoriety=30)
    w = _world([crook])
    ok, _r, fee = w.action_launder(crook, 50)
    assert ok and fee == 15                          # int(50 * 0.3), floor is a no-op
    assert crook.credits == 85

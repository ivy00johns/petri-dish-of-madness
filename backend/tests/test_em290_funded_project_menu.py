"""EM-290 (W29) — the "ACTIVE PROJECTS YOU COULD CONTRIBUTE TO" context block must
agree with the contribute_funds menu-line gate (EM-108). PR #57 gated the menu
line on there being a FUNDABLE (planned + underfunded) project, but the context
block kept listing fully-funded / under_construction projects — inviting the
rejected contribute_funds. When nothing is fundable the block now shows (none)
(and, as a bonus, trims the prompt); when a fundable project exists the full list
still shows.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context


def _params():
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(buildings):
    places = [PlaceState(id="market", name="Market", x=0, y=0, kind="work")]
    agent = AgentState(id="dot", name="Dot", personality="civic", profile="mock",
                       location="market", energy=80.0, credits=20)
    w = World(params=_params(), places=places, agents=[agent])
    for b in buildings:
        w.buildings[b.id] = b
    return agent, w


def _bld(bid, status, have, need, loc="market"):
    return Building(id=bid, name=f"Project {bid}", kind="workshop", location=loc,
                    status=status, funds_committed=have, funds_required=need)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _projects_block(sys: str) -> str:
    return sys.split("ACTIVE PROJECTS YOU COULD CONTRIBUTE TO ===")[1].split(
        "=== ACTIVE RULES")[0]


# ── no fundable project ⇒ block is (none) AND contribute_funds is not offered ──

def test_block_is_none_when_only_under_construction():
    agent, w = _world([_bld("b1", "under_construction", 20, 20)])
    sys = _sys(agent, w)
    block = _projects_block(sys)
    assert "id=b1" not in block
    assert "(none)" in block
    assert "contribute_funds (building_id" not in sys


def test_block_is_none_when_only_fully_funded_planned():
    # Planned but fully funded (committed >= required) — needs build_step, not funds.
    agent, w = _world([_bld("b1", "planned", 50, 50)])
    sys = _sys(agent, w)
    assert "id=b1" not in _projects_block(sys)
    assert "(none)" in _projects_block(sys)
    assert "contribute_funds (building_id" not in sys


# ── a fundable project ⇒ the full list shows AND contribute_funds is offered ───

def test_block_lists_projects_when_a_fundable_one_exists():
    agent, w = _world([
        _bld("b1", "planned", 10, 50),               # fundable
        _bld("b2", "under_construction", 30, 30),     # not fundable, but still shown
    ])
    sys = _sys(agent, w)
    block = _projects_block(sys)
    assert "id=b1" in block
    assert "id=b2" in block                           # awareness preserved
    assert "contribute_funds (building_id" in sys


def test_block_is_none_with_no_open_projects_at_all():
    agent, w = _world([])
    assert "(none)" in _projects_block(_sys(agent, w))
    assert "contribute_funds (building_id" not in _sys(agent, w)

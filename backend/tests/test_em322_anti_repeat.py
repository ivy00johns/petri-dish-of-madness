"""EM-322 — anti-repetition: the agent's own recent spoken lines are fed back
into the prompt as an explicit YOU RECENTLY SAID / do-not-repeat block, so a
looping model (or the storm fallback) is shown the lines it keeps circling and
told to say something new. This FIXES the repetition (Mox's "the unseen hand…"
loop) at the prompt, without HIDING a line or wasting a turn.

Contract:
  - _recently_said_block([]) / (None) → "" (byte-identical for a silent agent —
    default callers and the em161 golden are unchanged).
  - a non-empty history renders the header, the do-not-repeat directive, and
    each line quoted (clamped to 200 chars).
  - _assemble_context injects the block ONLY when recent_said is passed.
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context, _recently_said_block


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world() -> tuple[AgentState, World]:
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    a = AgentState(id="ada", name="Ada", personality="", profile="mock",
                   location="townhall", energy=80.0, credits=20)
    b = AgentState(id="bram", name="Bram", personality="", profile="mock",
                   location="townhall", energy=80.0, credits=20)
    w = World(params=_params(), places=places, agents=[a, b])
    return w.agents["ada"], w


def _sys(agent, world, **kw) -> str:
    msgs = _assemble_context(agent, world, [], world.params, **kw)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── the pure block builder ────────────────────────────────────────────────────

def test_block_empty_for_no_history():
    assert _recently_said_block(None) == ""
    assert _recently_said_block([]) == ""
    assert _recently_said_block(["", "   "]) == ""  # blank lines are dropped


def test_block_lists_lines_with_directive():
    block = _recently_said_block(["The unseen hand cannot silence us!",
                                  "Let us finish the Rhetoric Academy."])
    assert "YOU RECENTLY SAID" in block
    assert "do NOT repeat" in block
    assert '"The unseen hand cannot silence us!"' in block
    assert '"Let us finish the Rhetoric Academy."' in block


def test_block_clamps_long_line_to_200():
    long = "x" * 300
    block = _recently_said_block([long])
    assert "x" * 200 in block
    assert "x" * 201 not in block


# ── wiring into the assembled prompt ──────────────────────────────────────────

def test_prompt_injects_block_when_recent_said_passed():
    agent, world = _world()
    sys = _sys(agent, world, recent_said=["I'll take those credits with a smile!"])
    assert "YOU RECENTLY SAID" in sys
    assert "I'll take those credits with a smile!" in sys


def test_prompt_has_no_block_by_default():
    # Backward-compat: callers that don't pass recent_said (and the em161
    # golden) must not gain the block.
    agent, world = _world()
    assert "YOU RECENTLY SAID" not in _sys(agent, world)

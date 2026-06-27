"""EM-248 + EM-249 — two recurring idle-fallback wastes, fixed.

EM-248 (funding menu): contribute_funds was offered whenever ANY project was open
(planned OR under_construction), so agents kept trying to fund fully-funded /
under-construction buildings — rejected "already fully funded — needs build_step"
(run-1117: 7 wasted turns). The menu now offers contribute_funds ONLY when a
PLANNED + still-UNDERFUNDED project exists (menu/resolution agree, EM-108). The line
TEXT is unchanged, so the em161 golden (whose b1 is planned-underfunded) is
byte-identical — pinned by test_wave_d2_prompt_diet.

EM-249 (parse): a free model told to 'return "actions" — an ordered list' routinely
echoes the keyword as the verb: {"action": "actions", "actions": [...]}. That died
on the ACTION_SCHEMA enum even though a valid actions[] sat beside it (run-1117:
recurring groq-llama idle fallback). _coerce_actions_keyword drops the spurious
`action` so the multi-action path takes over.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams
from petridish.agents.runtime import (
    _assemble_context, _coerce_actions_keyword,
)


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _world(buildings):
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agent = AgentState(id="dot", name="Dot", personality="civic", profile="mock",
                       location="plaza", energy=80.0, credits=50)
    w = World(params=_params(), places=places, agents=[agent])
    for b in buildings:
        w.buildings[b.id] = b
    return agent, w


def _menu(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _bld(bid, status, have, need):
    return Building(id=bid, name=bid.title(), kind="workshop", location="plaza",
                    status=status, funds_committed=have, funds_required=need)


# ── EM-248 — contribute_funds gated on FUNDABLE (planned + underfunded) ───────

def test_contribute_funds_offered_when_a_fundable_project_exists():
    agent, w = _world([_bld("b1", "planned", 10, 50)])   # planned + underfunded
    assert "contribute_funds (building_id" in _menu(agent, w)


def test_contribute_funds_omitted_when_only_fully_funded_planned():
    # A fully-funded planned building needs build_step, not money.
    agent, w = _world([_bld("b1", "planned", 50, 50)])
    menu = _menu(agent, w)
    assert "contribute_funds (building_id" not in menu


def test_contribute_funds_omitted_when_only_under_construction():
    agent, w = _world([_bld("b1", "under_construction", 40, 40)])
    assert "contribute_funds (building_id" not in _menu(agent, w)


def test_contribute_funds_omitted_with_no_open_projects():
    agent, w = _world([_bld("b1", "operational", 50, 50)])
    assert "contribute_funds (building_id" not in _menu(agent, w)


def test_contribute_funds_offered_when_a_mix_includes_one_fundable():
    # Fully-funded + under_construction + ONE planned-underfunded ⇒ still offered.
    agent, w = _world([
        _bld("b1", "planned", 50, 50),            # fully funded
        _bld("b2", "under_construction", 30, 30),  # building
        _bld("b3", "planned", 5, 80),              # fundable
    ])
    assert "contribute_funds (building_id" in _menu(agent, w)


# ── EM-249 — the "action": "actions" keyword-echo coercion ────────────────────

def test_coerce_drops_spurious_action_keyword_when_array_present():
    d = {"action": "actions", "actions": [
        {"action": "move_to", "args": {"place": "plaza"}},
        {"action": "say", "args": {"text": "hi"}},
    ]}
    _coerce_actions_keyword(d)
    assert "action" not in d                       # spurious verb dropped
    assert len(d["actions"]) == 2                   # the real steps survive


def test_coerce_noop_without_an_actions_array():
    # Nothing to fall back on ⇒ leave it for the normal retry (don't fabricate).
    d = {"action": "actions", "args": {}}
    _coerce_actions_keyword(d)
    assert d == {"action": "actions", "args": {}}


def test_coerce_noop_on_empty_actions_array():
    d = {"action": "actions", "actions": []}
    _coerce_actions_keyword(d)
    assert d["action"] == "actions"                 # unchanged (empty is useless)


def test_coerce_noop_on_a_normal_single_action():
    d = {"action": "say", "args": {"text": "hello"}}
    _coerce_actions_keyword(d)
    assert d == {"action": "say", "args": {"text": "hello"}}


def test_coerce_noop_on_a_normal_actions_array():
    d = {"actions": [{"action": "work", "args": {}}]}
    _coerce_actions_keyword(d)
    assert d == {"actions": [{"action": "work", "args": {}}]}

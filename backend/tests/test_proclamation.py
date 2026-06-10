"""PROTOTYPE — god-channel proclamation injection.

Proves the LOUD tier of the god↔town channel: a god proclamation is injected
into EVERY agent's prompt (so "name the town" actually reaches them), unlike the
opt-in billboard, and that proclamations round-trip through to_snapshot /
from_snapshot. Pure unit tests — no loop/provider/db; _assemble_context is
called directly, the same seam the W11b cognition tests pin.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _assemble_context, _validate_world


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )


def _world() -> World:
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=0, y=10, kind="governance"),
    ]
    agents = [
        AgentState(id="ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
        # Bo is at the market — nowhere near the plaza billboard. A proclamation
        # must still reach him; an opt-in billboard note never would.
        AgentState(id="bo", name="Bo", personality="", profile="mock",
                   location="market", energy=80.0, credits=20),
        # Cy stands at the town hall — where propose_rule (incl. name_town) is offered.
        AgentState(id="cy", name="Cy", personality="", profile="mock",
                   location="townhall", energy=80.0, credits=20),
    ]
    return World(params=_params(), places=places, agents=agents)


def _system_prompt(world: World, agent: AgentState) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def test_no_proclamation_means_no_block():
    world = _world()
    assert world.active_proclamation() is None
    for agent in world.agents.values():
        assert "THE GOD HAS PROCLAIMED" not in _system_prompt(world, agent)


def test_proclamation_reaches_every_agent_regardless_of_location():
    world = _world()
    evt = world.post_proclamation_as_god("Decide on a name for this town.")

    # The god's word rides EVERY agent's prompt — including Bo at the market.
    for agent in world.agents.values():
        sp = _system_prompt(world, agent)
        assert "📜 THE GOD HAS PROCLAIMED" in sp
        assert "Decide on a name for this town." in sp

    # The emitted event is the god-ink feed line.
    assert evt["kind"] == "proclamation_posted"
    assert evt["actor_type"] == "god"
    assert evt["payload"]["text"] == "Decide on a name for this town."
    assert world.active_proclamation()["text"] == "Decide on a name for this town."


def test_newest_proclamation_is_the_active_decree():
    world = _world()
    world.post_proclamation_as_god("First decree.")
    world.post_proclamation_as_god("Second decree supersedes it.")

    sp = _system_prompt(world, world.agents["ada"])
    assert "Second decree supersedes it." in sp
    assert "First decree." not in sp
    assert world.active_proclamation()["text"] == "Second decree supersedes it."


def test_proclamations_round_trip_through_snapshot():
    world = _world()
    world.tick = 7
    world.post_proclamation_as_god("Build a castle on the hill.")

    snap = world.to_snapshot()
    assert snap["proclamations"][0]["text"] == "Build a castle on the hill."

    restored = World.from_snapshot(snap, params=_params())
    assert restored.to_snapshot()["proclamations"] == snap["proclamations"]
    assert restored.active_proclamation()["text"] == "Build a castle on the hill."


# ──────────────────────────────────────────────────────────────────────────────
# Return path — answer_proclamation (the threaded two-way half of the channel).
# ──────────────────────────────────────────────────────────────────────────────

def test_answer_threads_under_the_active_proclamation():
    world = _world()
    world.post_proclamation_as_god("Name this town.")
    bo = world.agents["bo"]  # at the market — no location gate on answering

    evt = world.answer_proclamation(bo, "Call it Hopewell.")

    assert evt["kind"] == "proclamation_answered"
    assert evt["actor_id"] == "bo"
    assert evt["payload"]["text"] == "Call it Hopewell."
    assert evt["payload"]["in_reply_to"] == "Name this town."
    # The reply is threaded under the proclamation itself (world_state seam).
    replies = world.active_proclamation()["replies"]
    assert replies == [{"tick": world.tick, "actor_id": "bo", "text": "Call it Hopewell."}]


def test_answer_with_no_active_proclamation_is_a_parse_failure():
    world = _world()
    evt = world.answer_proclamation(world.agents["ada"], "Hello?")
    assert evt["kind"] == "parse_failure"
    assert evt["kind"] != "proclamation_answered"


def test_answer_action_is_offered_only_while_a_decree_is_live():
    world = _world()
    ada = world.agents["ada"]
    assert "answer_proclamation" not in _system_prompt(world, ada)

    world.post_proclamation_as_god("Speak to me.")
    # Offered to BOTH agents regardless of where they stand (no location gate).
    assert "answer_proclamation" in _system_prompt(world, world.agents["ada"])
    assert "answer_proclamation" in _system_prompt(world, world.agents["bo"])


def test_validator_gates_answer_on_an_active_proclamation():
    world = _world()
    ada = world.agents["ada"]
    act = {"action": "answer_proclamation", "args": {"text": "Hopewell."}}

    # No decree → rejected.
    assert _validate_world(act, ada, world) is not None
    # Decree live + text → allowed.
    world.post_proclamation_as_god("Name the town.")
    assert _validate_world(act, ada, world) is None
    # Decree live but empty text → rejected.
    assert _validate_world(
        {"action": "answer_proclamation", "args": {"text": "  "}}, ada, world) is not None


def test_replies_round_trip_through_snapshot():
    world = _world()
    world.post_proclamation_as_god("Name the town.")
    world.answer_proclamation(world.agents["ada"], "Hopewell.")
    world.answer_proclamation(world.agents["bo"], "No, Lastditch.")

    snap = world.to_snapshot()
    restored = World.from_snapshot(snap, params=_params())
    assert restored.to_snapshot()["proclamations"] == snap["proclamations"]
    assert [r["text"] for r in restored.active_proclamation()["replies"]] == \
        ["Hopewell.", "No, Lastditch."]


# ──────────────────────────────────────────────────────────────────────────────
# name_town — naming the town by CONSENSUS vote (the existing governance path).
# ──────────────────────────────────────────────────────────────────────────────

def _pass_rule(world, effect, text, name=None):
    """Propose `effect` (as Ada) and pass it with Ada + Bo voting yes."""
    ok, reason, rule = world.action_propose_rule(
        world.agents["ada"], effect, text, name=name)
    assert ok, reason
    world.action_vote(world.agents["ada"], rule.id, True)
    world.action_vote(world.agents["bo"], rule.id, True)
    return rule


def test_naming_the_town_by_vote_sets_the_name_and_emits():
    world = _world()
    assert world.town_name == ""
    rule = _pass_rule(world, "name_town", "Let us be Hopewell.", name="Hopewell")

    assert world.rules[rule.id].status == "active"
    assert world.town_name == "Hopewell"
    # The town_named event is parked in the governance outbox (the loop drains it).
    evts = world.drain_spawn_events()
    assert any(e["kind"] == "town_named" and e["payload"]["name"] == "Hopewell"
               for e in evts)


def test_name_town_requires_a_name():
    world = _world()
    ok, reason, rule = world.action_propose_rule(
        world.agents["ada"], "name_town", "Name us something.", name="  ")
    assert not ok and rule is None
    # the runtime validator rejects it too
    act = {"action": "propose_rule", "args": {"effect": "name_town", "text": "x"}}
    assert _validate_world(act, world.agents["ada"], world) is not None


def test_a_new_name_supersedes_the_old_one_not_a_renewal():
    world = _world()
    _pass_rule(world, "name_town", "Hopewell it is.", name="Hopewell")
    assert world.town_name == "Hopewell"

    rule2 = _pass_rule(world, "name_town", "On reflection, Lastditch.", name="Lastditch")
    assert world.rules[rule2.id].status == "active"   # NOT "renewed"
    assert world.town_name == "Lastditch"


def test_town_name_surfaces_in_prompt_and_round_trips():
    world = _world()
    # Unnamed → the prompt nudges toward name_town, and Cy (at the town hall) is
    # actually offered the propose_rule line carrying name_town.
    assert "this town has no name yet" in _system_prompt(world, world.agents["ada"])
    assert "name_town" in _system_prompt(world, world.agents["cy"])

    _pass_rule(world, "name_town", "Hopewell.", name="Hopewell")
    assert "Town: Hopewell" in _system_prompt(world, world.agents["bo"])

    snap = world.to_snapshot()
    assert snap["town_name"] == "Hopewell"
    assert World.from_snapshot(snap, params=_params()).town_name == "Hopewell"

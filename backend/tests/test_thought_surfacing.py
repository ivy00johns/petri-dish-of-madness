"""
EM-194 follow-up — the reflex-chatter "world is never mute" bandaid is gone;
the feed's legibility now comes from surfacing each turn's inner thought onto
the action line itself instead of burying it in payload.thought.

These tests pin AgentRuntime._surface_thought and its wiring in _apply_action:
a turn's one-sentence `thought` is appended to the PRIMARY action event's text
(💭) exactly once across a _multi chain, and an empty/absent thought leaves the
line byte-identical to the pre-feature output.

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

from petridish.engine.world import AgentState, PlaceState, World
from petridish.config.loader import ModelProfile, WorldParams
from petridish.agents.runtime import AgentRuntime
from petridish.providers.router import Router


class _StubProvider:
    """Minimal router adapter — _apply_action never calls chat(), but Router
    construction wants a real adapter behind the 'mock' profile."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def set_world(self, world: object) -> None:
        self._world = world

    async def chat(self, messages, *, max_tokens, temperature):
        return "{}"


def _runtime() -> tuple[World, AgentRuntime]:
    params = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999,
        energy_decay_per_turn=0.0, starting_energy=80.0,
        starting_credits=20, snapshot_interval_ticks=100,
    )
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
        AgentState(id="agent_bram", name="Bram", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20),
    ]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": _StubProvider()},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    return world, AgentRuntime(world, router)


def _apply(runtime: AgentRuntime, world: World, action_dict: dict) -> dict:
    return runtime._apply_action(
        world.agents["agent_ada"], action_dict, "mock", "#2ecc71")


def test_thought_is_appended_to_the_feed_line():
    world, runtime = _runtime()
    evt = _apply(runtime, world, {"action": "idle", "args": {},
                                  "thought": "Quiet today."})
    # exact format: the action line, two spaces, the 💭 bubble, the sentence
    assert evt["text"] == "Ada idles.  💭 Quiet today."


def test_thought_preserves_the_original_action_line():
    world, runtime = _runtime()
    evt = _apply(runtime, world, {"action": "forage", "args": {},
                                  "thought": "Maybe I should save more."})
    assert evt["text"].startswith("Ada forages")
    assert evt["text"].endswith("💭 Maybe I should save more.")


def test_absent_thought_leaves_the_line_byte_identical():
    world, runtime = _runtime()
    evt = _apply(runtime, world, {"action": "idle", "args": {}})
    assert evt["text"] == "Ada idles."
    assert "💭" not in evt["text"]


def test_blank_thought_is_a_noop():
    world, runtime = _runtime()
    evt = _apply(runtime, world, {"action": "idle", "args": {}, "thought": "   "})
    assert evt["text"] == "Ada idles."


def test_thought_surfaces_exactly_once_on_a_multi_chain():
    """A set_relationship drains a relationship_changed into a _multi chain;
    the thought must ride ONLY the primary action event, never the drained
    shift — so it never double-prints across the turn."""
    world, runtime = _runtime()
    evt = _apply(runtime, world, {"action": "set_relationship",
                                  "args": {"target": "Bram", "type": "ally"},
                                  "thought": "I trust Bram now."})
    chain = evt["_multi"] if "_multi" in evt else [evt]
    texts = [e.get("text", "") for e in chain]
    assert sum(t.count("💭") for t in texts) == 1
    assert "💭 I trust Bram now." in chain[0]["text"]

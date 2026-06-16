"""
Insult barb rendering (run-663).

The insult branch was emitting bare "X insults Y!" regardless of whether the
model provided an actual barb in args["text"]. The feed line is flavorless: the
insult_text sat in the payload but never appeared in the event text.

CONTRACT:
  - When args["text"] is a non-empty string, the conflict event text is:
      '{agent.name} insults {target.name}: "{barb}"'
  - When args["text"] is absent or empty, the bare form is kept:
      '{agent.name} insults {target.name}!'
  - insult_text remains in payload["insult_text"] unchanged.
  - Very long barbs are truncated to 200 chars (graceful, not dropped).

Tests drive runtime.run_turn with scripted MockProvider insult actions;
the harness is a local copy of the _make_world_runtime helper from
test_multi_action_turns.py (both agents share the same mock script so
the insult target Ada ↔ Bram always co-locates).
"""
from __future__ import annotations

import pytest

from petridish.engine.world import AgentState, PlaceState, World
from petridish.config.loader import ModelProfile, WorldParams
from petridish.agents.runtime import AgentRuntime
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Minimal harness (mirrors test_multi_action_turns._make_world_runtime)
# ──────────────────────────────────────────────────────────────────────────────

def _make_params(**over) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
    )
    base.update(over)
    return WorldParams(**base)


def _make_world_runtime(script: list, *, start: str = "market", params=None):
    """Two protagonists (Ada, Bram) co-located at `start`. Returns
    (runtime, world, ada, bram). Both cycle the SAME mock script."""
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id=f"agent_{n.lower()}", name=n, personality="Test agent.",
                   profile="mock", location=start,
                   energy=params.starting_energy, credits=params.starting_credits)
        for n in ("Ada", "Bram")
    ]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    return runtime, world, agents[0], agents[1]


def _conflict_event(result: dict) -> dict:
    """Extract the single conflict event from a run_turn result."""
    if "_multi" in result:
        events = result["_multi"]
    else:
        events = [{k: v for k, v in result.items() if k != "_trace"}]
    conflicts = [e for e in events if e.get("kind") == "conflict"]
    assert len(conflicts) == 1, f"Expected 1 conflict event, got {len(conflicts)}: {conflicts}"
    return conflicts[0]


# ──────────────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────────────

async def test_insult_with_barb_renders_barb_in_text():
    """When the model provides a non-empty barb, the feed line includes it
    verbatim: 'Ada insults Bram: "your hat is a crime!"'."""
    # run-663: barb was buried in payload, never in text
    barb = "your hat is a crime!"
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "insult", "args": {"target": "agent_bram", "text": barb}}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evt = _conflict_event(result)
    assert barb in evt["text"], (
        f"Barb not rendered in conflict event text.\n"
        f"  text={evt['text']!r}\n"
        f"  barb={barb!r}"
    )
    # The format must be the colon-quoted form, not the bare exclamation form.
    assert evt["text"].endswith(f': "{barb}"'), (
        f"Text does not end with quoted barb: {evt['text']!r}"
    )


async def test_insult_without_text_renders_bare_exclamation():
    """When no barb is provided (text absent), the feed shows the bare
    'Ada insults Bram!' — no empty quotes."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "insult", "args": {"target": "agent_bram"}}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evt = _conflict_event(result)
    assert evt["text"] == "Ada insults Bram!", (
        f"Expected bare exclamation form, got: {evt['text']!r}"
    )
    # Absolutely no empty-quote artifact.
    assert '""' not in evt["text"], f"Empty quotes leaked into text: {evt['text']!r}"


async def test_insult_empty_string_text_renders_bare_exclamation():
    """An explicit empty string in args['text'] is treated the same as absent —
    the bare exclamation form, no empty quotes."""
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "insult", "args": {"target": "agent_bram", "text": ""}}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evt = _conflict_event(result)
    assert evt["text"] == "Ada insults Bram!", (
        f"Expected bare exclamation for empty string, got: {evt['text']!r}"
    )
    assert '""' not in evt["text"], f"Empty quotes leaked: {evt['text']!r}"


async def test_insult_payload_contains_insult_text_unchanged():
    """insult_text in the payload is not modified by the text-rendering change —
    the raw value the model sent stays there for downstream consumers."""
    barb = "your ideas are as empty as your pockets"
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "insult", "args": {"target": "agent_bram", "text": barb}}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evt = _conflict_event(result)
    assert evt["payload"]["insult_text"] == barb, (
        f"payload.insult_text was modified; expected {barb!r}, "
        f"got {evt['payload'].get('insult_text')!r}"
    )


async def test_insult_long_barb_truncated_in_text():
    """A very long barb (>200 chars) is truncated to 200 chars in the feed text
    (graceful), but the full barb is kept in payload.insult_text."""
    long_barb = "x" * 350
    runtime, world, ada, _bram = _make_world_runtime(
        [{"action": "insult", "args": {"target": "agent_bram", "text": long_barb}}],
        start="market",
    )
    result = await runtime.run_turn(ada)
    evt = _conflict_event(result)
    # The text must not contain the full 350-char barb.
    assert long_barb not in evt["text"], "Long barb was not truncated in feed text"
    # It must contain the first 200 chars.
    assert long_barb[:200] in evt["text"], (
        f"Truncated barb not found in text: {evt['text']!r}"
    )
    # Full barb preserved in payload.
    assert evt["payload"]["insult_text"] == long_barb, (
        "payload.insult_text must hold the full untruncated barb"
    )

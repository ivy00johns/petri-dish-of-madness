"""
EM-224 — PIANO coherence for multi-action turns (Wave M4).

A single LLM call can carry an ordered `actions[]` sequence (EM-199) that *says*
one thing and *does* the opposite — "Sure, here, friend!" then steal from the same
agent. EM-224 adds a DETERMINISTIC, zero-LLM coherence bottleneck between
`_normalize_steps` and `_apply_steps`: derive a single intent from the turn's first
speech act, then reconcile later hostile/helpful steps against it.

Gated behind `world.coherence.enabled` (DEFAULT OFF) so the prompt golden and
EM-155 snapshots stay byte-identical — EM-224 carries NO prompt block and NO
agent/world state. See docs/superpowers/specs/2026-06-27-em224-piano-coherence-design.md.

Tests drive the REAL parse → normalize → coherence → apply path with scripted
MockProvider actions (deterministic, offline).
"""
from __future__ import annotations

import pytest

from petridish.engine.world import AgentState, PlaceState, World
from petridish.config.loader import CoherenceParams, ModelProfile, WorldParams
from petridish.agents.runtime import AgentRuntime, _coherence_enabled
from petridish.providers.mock import MockProvider
from petridish.providers.router import Router

DOMAIN_KINDS = {
    "agent_action", "agent_speech", "agent_moved", "economy",
    "conflict", "relationship", "parse_failure", "coherence_note",
}


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


def _make_world_runtime(script: list, *, start: str = "market", params=None,
                        names=("Ada", "Bram")):
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="home", name="Hearth", x=20, y=0, kind="home"),
    ]
    agents = [
        AgentState(id=f"agent_{n.lower()}", name=n, personality="Test agent.",
                   profile="mock", location=start,
                   energy=params.starting_energy, credits=params.starting_credits)
        for n in names
    ]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)})
    for a in agents:
        router.reassign(a.id, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    return runtime, world, agents[0], agents[1]


def _domain_events(result: dict) -> list[dict]:
    if "_multi" in result:
        evts = result["_multi"]
    else:
        evts = [{k: v for k, v in result.items() if k != "_trace"}]
    return [e for e in evts if e.get("kind") in DOMAIN_KINDS]


# A friendly say to Bram, then a steal FROM Bram — the canonical contradiction.
def _friendly_then_steal_script(target_id="agent_bram"):
    return [{"actions": [
        {"action": "say", "args": {"text": "Sure, here friend, take these — I want to help you!"}},
        {"action": "steal", "args": {"target": target_id}},
    ]}]


# ══════════════════════════════════════════════════════════════════════════════
# Config — the block defaults OFF and parses defensively.
# ══════════════════════════════════════════════════════════════════════════════

def test_coherence_params_default_off():
    p = CoherenceParams()
    assert p.enabled is False
    assert p.strategy == "annotate"


def test_coherence_enabled_accessor_default_off():
    params = _make_params()
    assert _coherence_enabled(params) is False


def test_coherence_enabled_accessor_reads_flag():
    params = _make_params(coherence=CoherenceParams(enabled=True))
    assert _coherence_enabled(params) is True


# ══════════════════════════════════════════════════════════════════════════════
# Disabled = byte-identical to pre-EM-224.
# ══════════════════════════════════════════════════════════════════════════════

async def test_disabled_contradiction_resolves_unchanged():
    """enabled=False ⇒ the steal applies and NO coherence payload appears."""
    runtime, world, ada, bram = _make_world_runtime(
        _friendly_then_steal_script(), start="market",
    )
    bram_start = bram.credits
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    assert "agent_speech" in kinds
    # the steal resolved (economy) — bram lost credits, no coherence stamp
    econ = [e for e in evts if e["kind"] == "economy"]
    assert econ, "steal should have resolved as an economy event"
    assert all("coherence" not in e.get("payload", {}) for e in evts)
    assert bram.credits < bram_start  # the theft happened


async def test_disabled_never_emits_coherence_note():
    runtime, world, ada, bram = _make_world_runtime(
        _friendly_then_steal_script(), start="market",
    )
    result = await runtime.run_turn(ada)
    kinds = [e["kind"] for e in _domain_events(result)]
    assert "coherence_note" not in kinds


# ══════════════════════════════════════════════════════════════════════════════
# Enabled + annotate (default strategy) — keep both, make the hypocrisy legible.
# ══════════════════════════════════════════════════════════════════════════════

async def test_annotate_flags_contradiction_keeps_both():
    runtime, world, ada, bram = _make_world_runtime(
        _friendly_then_steal_script(), start="market",
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    bram_start = bram.credits
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    # both still resolved: the say AND the steal
    assert any(e["kind"] == "agent_speech" for e in evts)
    econ = [e for e in evts if e["kind"] == "economy"]
    assert econ, "annotate keeps the steal — it still resolves"
    assert bram.credits < bram_start  # the theft still happened
    # the steal event is stamped as contradicting the friendly intent
    flagged = [e for e in evts if e.get("payload", {}).get("coherence", {}).get("contradicted")]
    assert flagged, "the steal event should carry payload.coherence.contradicted"
    coh = flagged[0]["payload"]["coherence"]
    assert coh["intent"] == "friendly"
    # and the feed text is honest about the dissonance
    assert "💢" in flagged[0]["text"] or "belying" in flagged[0]["text"].lower()


# ══════════════════════════════════════════════════════════════════════════════
# Enabled + drop — the speech wins, the contradicting act is suppressed.
# ══════════════════════════════════════════════════════════════════════════════

async def test_drop_suppresses_contradicting_step():
    runtime, world, ada, bram = _make_world_runtime(
        _friendly_then_steal_script(), start="market",
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="drop")),
    )
    bram_start = bram.credits
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    kinds = [e["kind"] for e in evts]
    # the say still happened
    assert "agent_speech" in kinds
    # the steal was suppressed — no economy event, bram keeps his credits
    assert "economy" not in kinds
    assert bram.credits == bram_start
    # a coherence_note replaces it
    assert "coherence_note" in kinds


# ══════════════════════════════════════════════════════════════════════════════
# Coherent turns are untouched even when enabled.
# ══════════════════════════════════════════════════════════════════════════════

async def test_coherent_give_unchanged_when_enabled():
    """Friendly say + give to the SAME target is coherent → no flag, identical
    resolution to the no-coherence path."""
    script = [{"actions": [
        {"action": "say", "args": {"text": "Here friend, take these — I want to help you!"}},
        {"action": "give", "args": {"target": "agent_bram", "amount": 5}},
    ]}]
    runtime, world, ada, bram = _make_world_runtime(
        script, start="market",
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    bram_start = bram.credits
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    assert any(e["kind"] == "agent_speech" for e in evts)
    assert any(e["kind"] == "economy" for e in evts)
    assert bram.credits == bram_start + 5  # the gift went through
    assert all("coherence" not in e.get("payload", {}) for e in evts)
    assert "coherence_note" not in [e["kind"] for e in evts]


async def test_neutral_speech_no_target_not_flagged():
    """A say with no target reference + a steal → intent un-derivable, no flag."""
    script = [{"actions": [
        {"action": "say", "args": {"text": "What a fine morning it is."}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]}]
    runtime, world, ada, bram = _make_world_runtime(
        script, start="market",
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    assert all("coherence" not in e.get("payload", {}) for e in evts)
    assert "coherence_note" not in [e["kind"] for e in evts]


async def test_hostile_speech_then_steal_not_flagged():
    """Hostile say + hostile act toward the same target is COHERENT — no flag."""
    script = [{"actions": [
        {"action": "say", "args": {"text": "I hate you, Bram, you fool — give me everything!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]}]
    runtime, world, ada, bram = _make_world_runtime(
        script, start="market",
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    assert all(not e.get("payload", {}).get("coherence", {}).get("contradicted")
               for e in evts)


# ══════════════════════════════════════════════════════════════════════════════
# Determinism — same steps twice → identical resolution.
# ══════════════════════════════════════════════════════════════════════════════

def test_coherence_resolve_is_deterministic():
    from petridish.agents.runtime import _coherence_resolve
    steps = [
        {"action": "say", "args": {"text": "Here friend, take these, I'll help you!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]
    out1, notes1 = _coherence_resolve([dict(s) for s in steps], "", "annotate",
                                      {"agent_bram": "Bram"})
    out2, notes2 = _coherence_resolve([dict(s) for s in steps], "", "annotate",
                                      {"agent_bram": "Bram"})
    assert out1 == out2
    assert notes1 == notes2


def test_coherence_resolve_no_speech_act_is_noop():
    from petridish.agents.runtime import _coherence_resolve
    steps = [
        {"action": "work", "args": {}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]
    out, notes = _coherence_resolve([dict(s) for s in steps], "", "annotate",
                                    {"agent_bram": "Bram"})
    assert out == steps
    assert notes == []


# ══════════════════════════════════════════════════════════════════════════════
# EM-224 regression — target-blind matching (the stance must be directed at the
# SAME target as the harm/help step). A friendly remark ABOUT Cara must not
# contradict a steal FROM Bram; a self-targeted harm after friendly speech must
# not be flagged either.
# ══════════════════════════════════════════════════════════════════════════════

def test_speech_stance_about_other_target_is_neutral_for_named_target():
    """The stance toward a target is asserted ONLY when the speech references
    that target. 'I'll help you, Cara!' is friendly toward Cara — but NEUTRAL
    toward Bram, who the speech never addressed (the 'you' is claimed by the
    named addressee Cara)."""
    from petridish.agents.runtime import _speech_stance
    # Toward Cara (named, second-person bound to her): friendly.
    assert _speech_stance("I'll help you, Cara!", "Cara", ("Bram",)) == "friendly"
    # Toward Bram: the line names Cara, so the 'you' is hers, not Bram's.
    assert _speech_stance("I'll help you, Cara!", "Bram", ("Cara",)) == "neutral"


def test_coherence_resolve_friendly_about_X_then_harm_to_Y_not_flagged():
    """REGRESSION (target-blind): a friendly say naming Cara, then a steal FROM
    Bram (a DIFFERENT target) must NOT be flagged — the friendly stance was
    never directed at Bram."""
    from petridish.agents.runtime import _coherence_resolve
    steps = [
        {"action": "say", "args": {"text": "I'll help you, Cara!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]
    names = {"agent_bram": "Bram", "agent_cara": "Cara"}
    out, notes = _coherence_resolve([dict(s) for s in steps], "", "annotate", names)
    assert notes == []
    assert all("_coherence" not in s for s in out), (
        "friendly-about-Cara must not contradict harm-to-Bram"
    )


def test_coherence_resolve_friendly_about_X_then_harm_to_X_IS_flagged():
    """The true contradiction is preserved: friendly say naming Bram, then a
    steal FROM Bram (the SAME target) IS flagged."""
    from petridish.agents.runtime import _coherence_resolve
    steps = [
        {"action": "say", "args": {"text": "I'll help you, Bram!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]
    names = {"agent_bram": "Bram", "agent_cara": "Cara"}
    out, notes = _coherence_resolve([dict(s) for s in steps], "", "annotate", names)
    flagged = [s for s in out if s.get("_coherence", {}).get("contradicted")]
    assert flagged, "friendly-about-Bram + steal-from-Bram is a true contradiction"
    assert flagged[0]["_coherence"]["intent"] == "friendly"


def test_coherence_resolve_self_harm_after_friendly_speech_not_flagged():
    """A SELF-targeted harm after friendly speech is not a contradiction (the
    actor cannot be hypocritical toward themselves here)."""
    from petridish.agents.runtime import _coherence_resolve
    steps = [
        {"action": "say", "args": {"text": "I'll help you, friend!"}},
        {"action": "steal", "args": {"target": "agent_ada"}},
    ]
    names = {"agent_ada": "Ada", "agent_bram": "Bram"}
    out, notes = _coherence_resolve(
        [dict(s) for s in steps], "", "annotate", names, actor_id="agent_ada",
    )
    assert notes == []
    assert all("_coherence" not in s for s in out), (
        "self-targeted harm after friendly speech must not be flagged"
    )


async def test_friendly_say_to_X_then_harm_to_Y_not_flagged_full_path():
    """Full parse→normalize→coherence→apply path: a friendly say naming Cara,
    then a steal FROM Bram must NOT be flagged when coherence is enabled."""
    script = [{"actions": [
        {"action": "say", "args": {"text": "I'll help you, Cara — take these, friend!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]}]
    runtime, world, ada, bram = _make_world_runtime(
        script, start="market", names=("Ada", "Bram", "Cara"),
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    assert all(not e.get("payload", {}).get("coherence", {}).get("contradicted")
               for e in evts)
    assert "coherence_note" not in [e["kind"] for e in evts]


async def test_friendly_say_to_X_then_harm_to_X_is_flagged_full_path():
    """Full path: friendly say naming Bram, then a steal FROM Bram IS flagged —
    the true contradiction survives the target-aware fix."""
    script = [{"actions": [
        {"action": "say", "args": {"text": "I'll help you, Bram — take these, friend!"}},
        {"action": "steal", "args": {"target": "agent_bram"}},
    ]}]
    runtime, world, ada, bram = _make_world_runtime(
        script, start="market", names=("Ada", "Bram", "Cara"),
        params=_make_params(coherence=CoherenceParams(enabled=True, strategy="annotate")),
    )
    result = await runtime.run_turn(ada)
    evts = _domain_events(result)
    flagged = [e for e in evts if e.get("payload", {}).get("coherence", {}).get("contradicted")]
    assert flagged, "friendly-to-Bram + steal-from-Bram is a true contradiction"
    assert flagged[0]["payload"]["coherence"]["intent"] == "friendly"

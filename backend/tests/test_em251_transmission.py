# backend/tests/test_em251_transmission.py
"""EM-251 — Culture transmission verbs: the reflex behavior (mirrors
test_em258_combat's world-level style + test_em250_determinism's golden).

spread_rumor is the "telephone game" hop — it clones action_deceive's
belief-plant (via the shared _plant_belief seam) and action_recruit's
co-location gate, but stays TRUST-POSITIVE and CRIME-FREE, and carries a
DRIFTED child Meme (parent_id + generation+1) so the distortion has lineage.
send_letter is the first NON-co-located directed channel: it parks a letter
in ANY living agent's mailbox (present or absent), drained EXACTLY ONCE on
the recipient's own next turn by deliver_letters (reflex, no LLM). All paths
are seeded/deterministic (EM-155): meme ids are seeded, no clock, no RNG, and
a parked-letter + mid-drift-meme world round-trips byte-identical.
"""
from __future__ import annotations

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.agents.runtime import AgentRuntime
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ── helpers ──────────────────────────────────────────────────────────────────

def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, place: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=place, energy=80.0, credits=20)


def _world(comm=True, extra: dict | None = None,
           agents: list[AgentState] | None = None) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
              PlaceState(id="market", name="Market", x=1, y=0, kind="work")]
    w = World(params=_params(), places=places,
              agents=agents if agents is not None
              else [_a("ada"), _a("bram"), _a("cyn")])
    if comm:
        block = {"enabled": True}
        block.update(extra or {})
        w.params.comm = block
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


def _flatten(evt: dict) -> list[dict]:
    return evt["_multi"] if isinstance(evt, dict) and "_multi" in evt else [evt]


# ══════════════════════════════════════════════════════════════════════════════
# spread_rumor — gates
# ══════════════════════════════════════════════════════════════════════════════

def test_spread_rumor_fails_closed_when_comm_disabled():
    w = _world(comm=False)
    evt = w.action_spread_rumor(w.agents["ada"], w.agents["bram"], "hi")
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "comm disabled"
    assert w.memes == {}                                # nothing minted


def test_spread_rumor_rejects_self_and_absent_targets():
    w = _world()
    evt = w.action_spread_rumor(w.agents["ada"], w.agents["ada"], "hi")
    assert evt["payload"]["error"] == "self"
    w.agents["bram"].location = "market"                # not co-located
    evt = w.action_spread_rumor(w.agents["ada"], w.agents["bram"], "hi")
    assert evt["payload"]["error"] == "not co-located"


def test_spread_rumor_needs_a_source():
    w = _world()
    evt = w.action_spread_rumor(w.agents["ada"], w.agents["bram"], "")
    assert evt["payload"]["error"] == "empty"


# ══════════════════════════════════════════════════════════════════════════════
# spread_rumor — the telephone-game hop (trust-positive, crime-free, drifted)
# ══════════════════════════════════════════════════════════════════════════════

def test_spread_rumor_plants_a_distorted_belief_no_trust_no_crime():
    w = _world()
    w.tick = 4
    ada, bram = w.agents["ada"], w.agents["bram"]
    evt = w.action_spread_rumor(ada, bram, "Ada borrowed the axe")
    events = _flatten(evt)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "rumor_spread"
    assert "meme_mutated" in kinds                      # text drifted this hop

    # The DISTORTED text (borrowed→stole) landed in bram's beliefs, planted via
    # the shared _plant_belief seam ("<name> told me: <text>").
    assert any("Ada told me:" in b and "stole" in b for b in bram.beliefs)
    assert not any("borrowed" in b for b in bram.beliefs)

    # TRUST-POSITIVE channel: NO edge crater, NO edge created at all.
    assert ada.id not in bram.relationships
    assert bram.id not in ada.relationships
    # CRIME-FREE: no rap-sheet entry, no notoriety.
    assert ada.rap_sheet == [] and ada.notoriety == 0
    assert bram.rap_sheet == [] and bram.notoriety == 0


def test_spread_rumor_child_has_lineage_and_both_carry_it():
    w = _world()
    ada, bram = w.agents["ada"], w.agents["bram"]
    evt = w.action_spread_rumor(ada, bram, "Ada borrowed the axe")
    spread = _flatten(evt)[0]
    child = w.memes[spread["payload"]["meme_id"]]
    parent = w.memes[child.parent_id]
    assert child.parent_id == parent.id                 # lineage
    assert child.generation == parent.generation + 1 == 1
    assert child.text != parent.text                    # drifted
    # Attached to BOTH the actor and the co-located target.
    assert child.id in ada.held_memes and child.id in bram.held_memes
    assert set(child.carriers) == {"ada", "bram"}


def test_spread_rumor_single_event_when_distortion_is_off():
    # distortion_strength 0 ⇒ text unchanged ⇒ NO meme_mutated (single event),
    # and the belief carries the verbatim rumor.
    w = _world(extra={"distortion_strength": 0})
    ada, bram = w.agents["ada"], w.agents["bram"]
    evt = w.action_spread_rumor(ada, bram, "the well is calm")
    assert evt["kind"] == "rumor_spread"                # not a _multi chain
    child = w.memes[evt["payload"]["meme_id"]]
    parent = w.memes[child.parent_id]
    assert child.text == parent.text == "the well is calm"
    assert any("the well is calm" in b for b in bram.beliefs)


def test_spread_rumor_multi_hop_increments_generation_and_drifts():
    w = _world()
    ada, bram, cyn = w.agents["ada"], w.agents["bram"], w.agents["cyn"]
    # Hop 1: ada → bram.
    e1 = w.action_spread_rumor(ada, bram, "Ada borrowed the axe")
    child1 = w.memes[_flatten(e1)[0]["payload"]["meme_id"]]
    assert child1.generation == 1
    # Hop 2: bram carries child1, spreads IT (by meme_id) → cyn.
    assert child1.id in bram.held_memes
    e2 = w.action_spread_rumor(bram, cyn, meme_id=child1.id)
    child2 = w.memes[_flatten(e2)[0]["payload"]["meme_id"]]
    assert child2.parent_id == child1.id
    assert child2.generation == 2
    assert child2.text != child1.text                   # drifted another hop
    assert any(child2.text.split()[0] in b for b in cyn.beliefs)


def test_spread_rumor_meme_ids_are_deterministic_across_worlds():
    a = _world(); b = _world()
    a.tick = b.tick = 9
    ea = a.action_spread_rumor(a.agents["ada"], a.agents["bram"], "Ada borrowed it")
    eb = b.action_spread_rumor(b.agents["ada"], b.agents["bram"], "Ada borrowed it")
    assert _flatten(ea)[0]["payload"]["meme_id"] == \
        _flatten(eb)[0]["payload"]["meme_id"]
    assert set(a.memes) == set(b.memes)                 # same ids both worlds


# ══════════════════════════════════════════════════════════════════════════════
# send_letter — the NON-co-located channel + FIFO cap
# ══════════════════════════════════════════════════════════════════════════════

def test_send_letter_fails_closed_when_comm_disabled():
    w = _world(comm=False)
    evt = w.action_send_letter(w.agents["ada"], w.agents["bram"], "hi")
    assert evt["payload"]["error"] == "comm disabled"
    assert w.agents["bram"].mailbox == []


def test_send_letter_rejects_self_and_empty():
    w = _world()
    assert w.action_send_letter(
        w.agents["ada"], w.agents["ada"], "hi")["payload"]["error"] == "self"
    assert w.action_send_letter(
        w.agents["ada"], w.agents["bram"], "   ")["payload"]["error"] == "empty"


def test_send_letter_parks_in_an_absent_targets_mailbox():
    w = _world()
    w.tick = 5
    w.agents["bram"].location = "market"                # NOT co-located
    evt = w.action_send_letter(w.agents["ada"], w.agents["bram"],
                               "meet me at the plaza")
    assert evt["kind"] == "letter_sent"
    box = w.agents["bram"].mailbox
    assert len(box) == 1
    assert box[0] == {"from_id": "ada", "from_name": "Ada",
                      "text": "meet me at the plaza", "tick": 5}


def test_send_letter_fifo_caps_and_drops_the_oldest():
    w = _world(extra={"letter_cap": 3})
    ada, bram = w.agents["ada"], w.agents["bram"]
    for i in range(5):
        w.action_send_letter(ada, bram, f"letter {i}")
    box = bram.mailbox
    assert len(box) == 3                                # capped
    assert [e["text"] for e in box] == ["letter 2", "letter 3", "letter 4"]


# ══════════════════════════════════════════════════════════════════════════════
# deliver_letters — reflex drain, exactly once, on the recipient's turn
# ══════════════════════════════════════════════════════════════════════════════

def test_deliver_letters_drains_once_plants_beliefs_and_clears():
    w = _world()
    ada, bram = w.agents["ada"], w.agents["bram"]
    w.action_send_letter(ada, bram, "come home")
    w.action_send_letter(ada, bram, "bring bread")
    events = w.deliver_letters(bram)
    assert [e["kind"] for e in events] == ["letter_read", "letter_read"]
    assert any("Ada told me: (letter) come home" == b for b in bram.beliefs)
    assert any("Ada told me: (letter) bring bread" == b for b in bram.beliefs)
    assert bram.mailbox == []                           # cleared
    # A SECOND drain is a no-op (exactly once per letter).
    assert w.deliver_letters(bram) == []


def test_deliver_letters_is_a_noop_when_comm_disabled():
    w = _world(comm=False)
    bram = w.agents["bram"]
    bram.mailbox.append({"from_id": "ada", "from_name": "Ada",
                         "text": "x", "tick": 1})       # a stray parked letter
    assert w.deliver_letters(bram) == []                # gated → no drain
    assert len(bram.mailbox) == 1                       # untouched
    assert bram.beliefs == []


# ── the run_turn wiring: delivery happens on the recipient's OWN next turn ────

def _runtime(world: World, script: list) -> AgentRuntime:
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles,
                    adapter_overrides={"mock": MockProvider(script=script)})
    for a in world.agents.values():
        router.reassign(a.id, "mock")
    rt = AgentRuntime(world, router)
    router.inject_world(world)
    return rt


async def test_letter_delivered_on_recipient_next_run_turn():
    w = _world()
    ada, bram = w.agents["ada"], w.agents["bram"]
    w.action_send_letter(ada, bram, "come to the market")
    assert len(bram.mailbox) == 1
    rt = _runtime(w, [{"action": "idle", "args": {}}])
    result = await rt.run_turn(bram)
    # The reflex drain fired at the START of bram's own turn.
    assert bram.mailbox == []
    assert any("(letter) come to the market" in b for b in bram.beliefs)
    kinds = [e.get("kind") for e in _flatten(result)]
    assert "letter_read" in kinds


# ══════════════════════════════════════════════════════════════════════════════
# determinism golden (EM-155)
# ══════════════════════════════════════════════════════════════════════════════

def test_comm_off_default_world_has_no_wave_o_keys():
    snap = _world(comm=False).to_snapshot()
    for key in ("memes", "culture_camps", "town_motif_ref"):
        assert key not in snap
    for agent in snap["agents"]:
        assert "held_memes" not in agent and "mailbox" not in agent


def _populated_transmission_world() -> World:
    """A live culture state built THROUGH the EM-251 verbs: a drifted rumor
    (mid-lineage memes carried by two agents) + a letter parked in an absent
    recipient's mailbox — exactly the mid-flight state a fork must resume."""
    w = _world()
    w.tick = 7
    ada, bram, cyn = w.agents["ada"], w.agents["bram"], w.agents["cyn"]
    e1 = w.action_spread_rumor(ada, bram, "Ada borrowed the axe")   # gen 1
    child1 = w.memes[_flatten(e1)[0]["payload"]["meme_id"]]
    w.action_spread_rumor(bram, cyn, meme_id=child1.id)             # gen 2
    cyn.location = "market"                                         # now absent
    w.action_send_letter(ada, cyn, "the rumor is false")           # parked
    # Beliefs are in-the-moment memory that _plant_belief deliberately does NOT
    # serialize (the pre-existing deceive contract) — they never ride a snapshot,
    # so clear them here to isolate the DURABLE culture state (meme lineage +
    # parked letter) the byte-identical golden pins.
    for a in w.agents.values():
        a.beliefs.clear()
    return w


def test_populated_transmission_world_round_trips_byte_identical():
    w = _populated_transmission_world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


def test_populated_transmission_world_restores_state():
    w = _populated_transmission_world()
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    assert set(restored.memes) == set(w.memes)
    # A gen-2 drifted meme survived with its lineage.
    gen2 = [m for m in restored.memes.values() if m.generation == 2]
    assert len(gen2) == 1 and gen2[0].parent_id in restored.memes
    # The parked letter survived the round-trip (snapshot-safe like offers).
    assert restored.agents["cyn"].mailbox[0]["text"] == "the rumor is false"


def test_second_snapshot_hop_stays_byte_identical():
    w = _populated_transmission_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()), params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)

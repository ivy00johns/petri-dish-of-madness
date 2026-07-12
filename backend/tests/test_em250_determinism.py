# backend/tests/test_em250_determinism.py
"""EM-249 + EM-250 — the determinism golden (EM-155).

With comm disabled (the default) a world is BYTE-IDENTICAL to pre-Wave-O:
no memes/culture_camps/town_motif_ref snapshot keys, no held_memes/mailbox
agent keys, no relationship scope key — and the default snapshot round-trips
byte-identically. A POPULATED culture world (memes with lineage, camps,
motif, parked letters, non-local edges) also round-trips byte-identically,
so a fork/replay resumes the exact same culture state.
"""
import copy
import json

from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState,
)
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _agent(aid: str, name: str) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)


def _world() -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=_params(), places=places,
                 agents=[_agent("ada", "Ada"), _agent("bram", "Bram")])


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── default world: inert + byte-identical (comm disabled by default) ─────────

def test_default_world_snapshot_has_no_wave_o_keys():
    snap = _world().to_snapshot()
    for key in ("memes", "culture_camps", "town_motif_ref"):
        assert key not in snap, f"{key} must be absent on a default world"
    for agent in snap["agents"]:
        assert "held_memes" not in agent
        assert "mailbox" not in agent
        for rel in agent["relationships"].values():
            assert "scope" not in rel


def test_default_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)


# ── populated culture world: byte-identical round-trip ───────────────────────

def _populated_world() -> World:
    w = _world()
    ada, bram = w.agents["ada"], w.agents["bram"]
    w.tick = 7
    m1 = w.mint_meme("rumor", "The well is cursed", "ada")
    w._attach_meme(ada, m1)
    w._attach_meme(bram, m1)
    m2 = w.mint_meme("image", "A fox in a paper crown", "bram",
                     image_id="img_1", parent_id=m1.id, generation=1)
    m2.virality = 3
    w._attach_meme(bram, m2)
    # A camp record carrying a LATER-WAVE key ("shared") — must round-trip
    # verbatim (the faction-snapshot-writer lesson).
    w.culture_camps = {
        "cmp_ab12cd34": {"name": "Ada's camp", "founded_tick": 3,
                         "members": ["ada", "bram"], "shared": [m1.id]},
    }
    w.town_motif_ref = m2.id
    # A parked (undelivered) letter — snapshot-safe like pending_skill_requests.
    ada.mailbox.append({"from_id": "bram", "text": "meet me at the plaza",
                        "tick": 5})
    # A non-local edge (EM-249) rides its scope.
    ada.relationships["bram"] = RelationshipState(
        type="friend", trust=30, interactions=6, since_tick=2,
        scope="city:port")
    return w


def test_populated_world_round_trips_byte_identical():
    w = _populated_world()
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap1)


def test_populated_world_restores_culture_state():
    w = _populated_world()
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    assert set(restored.memes) == set(w.memes)
    m2 = next(m for m in restored.memes.values() if m.kind == "image")
    assert m2.parent_id is not None and m2.generation == 1
    assert m2.image_id == "img_1" and m2.virality == 3
    m1 = restored.memes[m2.parent_id]
    assert m1.carriers == ["ada", "bram"]
    assert restored.agents["bram"].held_memes == [m1.id, m2.id]
    assert restored.agents["ada"].mailbox[0]["text"] == "meet me at the plaza"
    assert restored.town_motif_ref == m2.id
    # The later-wave camp key survived the round-trip verbatim.
    assert restored.culture_camps["cmp_ab12cd34"]["shared"] == [m1.id]


def test_mid_flight_culture_survives_a_second_hop():
    # Fork-of-a-fork: two snapshot hops stay byte-identical (replay safety).
    w = _populated_world()
    snap1 = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()),
                               params=_params())
    assert _dumps(hop2.to_snapshot()) == _dumps(snap1)


# ── defensive restore (tampered snapshots never crash / never grow) ──────────

def test_restore_drops_garbage_meme_rows():
    w = _world()
    snap = w.to_snapshot()
    snap["memes"] = {
        "mem_ok12345678": {"kind": "rumor", "text": "fine",
                           "origin_agent_id": "ada", "origin_tick": 1,
                           "generation": 0, "carriers": ["ada"],
                           "last_spread_tick": 1, "virality": 0},
        "": {"kind": "rumor", "text": "no id"},          # blank id → dropped
        "mem_bad": "not-a-dict",                          # non-dict → dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert list(restored.memes) == ["mem_ok12345678"]
    assert restored.memes["mem_ok12345678"].carriers == ["ada"]


def test_restore_clamps_tampered_held_memes_and_mailbox():
    w = _world()
    snap = w.to_snapshot()
    snap["agents"][0]["held_memes"] = [f"mem_{i}" for i in range(20)] + [7, ""]
    snap["agents"][0]["mailbox"] = (
        [{"from_id": "x", "text": f"t{i}", "tick": i} for i in range(12)]
        + ["junk", 9]
    )
    restored = World.from_snapshot(snap, params=_params())
    ada = restored.agents[snap["agents"][0]["id"]]
    assert len(ada.held_memes) == 12                     # comm.held_meme_cap
    assert len(ada.mailbox) == 8                         # comm.letter_cap
    assert all(isinstance(e, dict) for e in ada.mailbox)


def test_restore_tolerates_garbage_camps_and_motif():
    w = _world()
    snap = w.to_snapshot()
    snap["culture_camps"] = {"cmp_x": {"name": "ok"}, "": {"name": "drop"},
                             "cmp_bad": "not-a-dict"}
    snap["town_motif_ref"] = ""
    restored = World.from_snapshot(snap, params=_params())
    assert list(restored.culture_camps) == ["cmp_x"]
    assert restored.town_motif_ref is None

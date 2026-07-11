# backend/tests/test_em250_schema.py
"""EM-249 + EM-250 — Wave O keystone schema: RelationshipState.scope (the
multi-city down-payment), the Meme primitive, AgentState.held_memes/mailbox,
and the CommunicationParams config block. Mirrors the test_em240_schema split:
dataclass defaults + serialize-when-non-default + config accessor conventions.
"""
from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState, Meme,
)
from petridish.config.loader import WorldParams, CommunicationParams, _parse_comm


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _agent(aid: str = "ada", name: str = "Ada") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)


def _world(agents: list[AgentState] | None = None) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=_params(), places=places,
                 agents=agents if agents is not None else [_agent()])


# ── EM-249 — RelationshipState.scope ─────────────────────────────────────────

def test_scope_defaults_local_and_omitted_from_to_dict():
    rel = RelationshipState()
    assert rel.scope == "local"
    a = _agent()
    a.relationships["bram"] = RelationshipState(type="ally", trust=10,
                                                interactions=2, since_tick=1)
    d = a.to_dict()
    # Byte-stability: the default scope must NOT appear in the serialized edge.
    assert "scope" not in d["relationships"]["bram"]
    assert d["relationships"]["bram"]["type"] == "ally"


def test_scope_serialized_only_when_non_default():
    a = _agent()
    a.relationships["bram"] = RelationshipState(type="ally", trust=10,
                                                scope="city:port")
    d = a.to_dict()
    assert d["relationships"]["bram"]["scope"] == "city:port"


def test_scope_absent_restores_local():
    w = _world([_agent(), _agent("bram", "Bram")])
    snap = w.to_snapshot()
    # A pre-EM-249 snapshot edge (no scope key) restores the default.
    snap["agents"][0]["relationships"] = {
        "bram": {"type": "friend", "trust": 30, "interactions": 6,
                 "since_tick": 2}
    }
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["ada"].relationships["bram"].scope == "local"


def test_scope_round_trips_through_snapshot():
    a = _agent()
    a.relationships["bram"] = RelationshipState(type="ally", trust=10,
                                                scope="city:port")
    w = _world([a, _agent("bram", "Bram")])
    restored = World.from_snapshot(w.to_snapshot(), params=_params())
    assert restored.agents["ada"].relationships["bram"].scope == "city:port"


# ── EM-250 — the Meme dataclass ──────────────────────────────────────────────

def test_meme_defaults_and_to_dict_shape():
    m = Meme(id="mem_0123456789", kind="rumor", text="The well is cursed",
             origin_agent_id="ada", origin_tick=3)
    assert m.parent_id is None and m.image_id is None
    assert m.generation == 0 and m.carriers == [] and m.virality == 0
    d = m.to_dict()
    # Optional lineage/image keys are omitted at default (byte-stability) …
    assert "image_id" not in d and "parent_id" not in d
    # … while the scalar core always rides (the factions-record convention).
    assert d["id"] == "mem_0123456789" and d["kind"] == "rumor"
    assert d["generation"] == 0 and d["carriers"] == []


def test_meme_kind_is_an_open_string():
    # Religion adds kind="faith" later (EM-260) — no enum gate by design.
    m = Meme(id="mem_x", kind="faith", text="t", origin_agent_id="a",
             origin_tick=0)
    assert m.to_dict()["kind"] == "faith"


def test_meme_lineage_keys_ride_when_set():
    m = Meme(id="mem_y", kind="image", text="a fox in a paper crown",
             origin_agent_id="b", origin_tick=9, image_id="img_1",
             parent_id="mem_x", generation=2)
    d = m.to_dict()
    assert d["image_id"] == "img_1"
    assert d["parent_id"] == "mem_x"
    assert d["generation"] == 2


def test_mint_meme_seeded_id_and_registration():
    w = _world()
    w.tick = 5
    m = w.mint_meme("rumor", "The well is cursed", "ada")
    assert m.id.startswith("mem_") and len(m.id) == len("mem_") + 10
    assert w.memes[m.id] is m
    assert m.origin_tick == 5 and m.last_spread_tick == 5
    assert m.carriers == []          # registration alone attaches nobody


def test_mint_meme_is_idempotent():
    w = _world()
    m1 = w.mint_meme("rumor", "same text", "ada")
    m2 = w.mint_meme("rumor", "same text", "ada")
    assert m1 is m2
    assert len(w.memes) == 1


def test_mint_meme_id_deterministic_across_worlds():
    a = _world().mint_meme("idea", "plant a garden", "ada")
    b = _world().mint_meme("idea", "plant a garden", "ada")
    assert a.id == b.id


# ── EM-250 — held_memes / mailbox on AgentState ──────────────────────────────

def test_held_memes_mailbox_default_and_omitted():
    a = _agent()
    assert a.held_memes == [] and a.mailbox == []
    d = a.to_dict()
    assert "held_memes" not in d
    assert "mailbox" not in d


def test_held_memes_mailbox_serialized_when_set():
    a = _agent()
    a.held_memes = ["mem_a", "mem_b"]
    a.mailbox = [{"from_id": "bram", "text": "hello", "tick": 4}]
    d = a.to_dict()
    assert d["held_memes"] == ["mem_a", "mem_b"]
    assert d["mailbox"][0]["text"] == "hello"


# ── EM-250 — world collections default empty + omitted ───────────────────────

def test_world_collections_default_empty_and_omitted():
    w = _world()
    assert w.memes == {} and w.culture_camps == {} and w.town_motif_ref is None
    snap = w.to_snapshot()
    for key in ("memes", "culture_camps", "town_motif_ref"):
        assert key not in snap, f"{key} must be omitted at default"


# ── EM-250 — CommunicationParams / _comm_param conventions ───────────────────

def test_world_params_carries_commparams_dataclass():
    p = WorldParams()
    assert isinstance(p.comm, CommunicationParams)
    assert p.comm.enabled is False          # DEFAULT OFF — the inert keystone
    assert p.comm.held_meme_cap == 12
    assert p.comm.letter_cap == 8


def test_comm_param_defaults_when_block_absent():
    w = _world()
    w.params.comm = None                    # absent block ⇒ every default
    assert w._comm_param("held_meme_cap", 12) == 12
    assert w._comm_param("distortion_strength", 1) == 1
    assert w._comm_enabled() is False


def test_comm_param_reads_dict_block():
    w = _world()
    w.params.comm = {"enabled": True, "letter_cap": 4}  # EM-155 dict convention
    assert w._comm_enabled() is True
    assert w._comm_param("letter_cap", 8) == 4
    assert w._comm_param("held_meme_cap", 12) == 12     # falls through


def test_parse_comm_defaults_and_overrides():
    assert _parse_comm(None) == CommunicationParams()
    assert _parse_comm("garbage") == CommunicationParams()
    parsed = _parse_comm({"enabled": True, "letter_cap": "4",
                          "diffusion_chance": 0.5,
                          "half_life_ticks": "junk"})
    assert parsed.enabled is True
    assert parsed.letter_cap == 4                 # str coerces
    assert parsed.diffusion_chance == 0.5
    assert parsed.half_life_ticks == 30           # malformed → per-key default
    assert parsed.meme_images is True

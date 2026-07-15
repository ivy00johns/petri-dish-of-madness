# backend/tests/test_em260_schema.py
"""EM-260 — Religion plumbing schema (mirrors the test_em256_schema split).

  * Faith.to_dict — the seeded-at-mint scalar core (id/name/deity/founder_id/
    founded_tick/tenets) always rides; members/temple_id/meme_id/hostile_to/
    parent_id ride ONLY when non-default (the WarState convention).
  * World.mint_faith — seeded fth_<8hex> id (replay-stable), SEEDED-picked
    invented name/deity/tenets, idempotent re-mint, parent_id lineage.
  * faiths snapshot key — only-when-non-empty; defensive restore (garbage rows
    dropped, optional fields default when absent).
  * AgentState faith_id/devotion — additive, serialized only-when-non-default,
    devotion clamped 0..100 on restore.
  * co_religionist in RELATIONSHIP_TYPES but NOT declarable.
  * FaithParams defaults + defensive parse + absent-block behavior.
  * the invented-pool denylist: NO real religions / deities / prophets /
    scriptures anywhere in the seeded pools.
"""
import copy
import json
import re

from petridish.engine.world import (
    World, AgentState, PlaceState, Faith,
    RELATIONSHIP_TYPES, DECLARABLE_RELATIONSHIP_TYPES,
    _FAITH_NAMES, _FAITH_DEITIES, _FAITH_TENETS,
)
from petridish.config.loader import WorldParams, FaithParams, _parse_faith


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, **kw) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20, **kw)


def _world(agents: list[AgentState] | None = None, faith: bool = True) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    w = World(params=_params(), places=places,
              agents=agents if agents is not None else [_a("ada"), _a("dot")])
    if faith:
        w.params.faith = {"enabled": True}
    return w


def _dumps(snap: dict) -> str:
    return json.dumps(snap, sort_keys=True)


# ── Faith.to_dict ─────────────────────────────────────────────────────────────

def test_fresh_faith_serializes_minimal_scalar_core():
    f = Faith(id="fth_ab12cd34", name="The Ashen Covenant",
              deity="Vharûn the Unseen", founder_id="ada", founded_tick=7,
              tenets=["Hoard nothing the river can carry"])
    d = f.to_dict()
    assert d == {"id": "fth_ab12cd34", "name": "The Ashen Covenant",
                 "deity": "Vharûn the Unseen", "founder_id": "ada",
                 "founded_tick": 7,
                 "tenets": ["Hoard nothing the river can carry"]}
    for k in ("members", "temple_id", "meme_id", "hostile_to", "parent_id"):
        assert k not in d


def test_optional_fields_ride_only_when_non_default():
    f = Faith(id="fth_ab12cd34", name="n", deity="d", founder_id="ada",
              founded_tick=7, tenets=["t"], members=["ada"], temple_id="b_1",
              meme_id="mem_x", hostile_to=["fth_zzz"], parent_id="fth_par00000")
    d = f.to_dict()
    assert d["members"] == ["ada"]
    assert d["temple_id"] == "b_1"
    assert d["meme_id"] == "mem_x"
    assert d["hostile_to"] == ["fth_zzz"]
    assert d["parent_id"] == "fth_par00000"


# ── mint_faith: seeded + idempotent ───────────────────────────────────────────

def test_mint_faith_id_is_seeded_and_replay_stable():
    w1, w2 = _world(), _world()
    w1.tick = w2.tick = 9
    a = w1.mint_faith("ada")
    b = w2.mint_faith("ada")
    assert a.id == b.id
    assert a.id.startswith("fth_") and len(a.id) == 4 + 8
    # name/deity/tenets are ALL seeded → byte-identical across two worlds.
    assert a.to_dict() == b.to_dict()
    assert a.name in _FAITH_NAMES and a.deity in _FAITH_DEITIES
    assert a.tenets and all(t in _FAITH_TENETS for t in a.tenets)
    assert len(a.tenets) == len(set(a.tenets))          # distinct


def test_mint_faith_parent_id_lineage_and_distinct_id():
    w = _world()
    w.tick = 3
    root = w.mint_faith("ada")
    child = w.mint_faith("ada", parent_id=root.id)
    assert child.parent_id == root.id
    assert child.id != root.id                          # parent salts the key
    assert child.to_dict()["parent_id"] == root.id


def test_mint_faith_is_idempotent_same_key_returns_registered():
    w = _world()
    a = w.mint_faith("ada")
    b = w.mint_faith("ada")                              # same founder + tick
    assert a is b and len(w.faiths) == 1


# ── snapshot: only-when-non-empty + defensive restore ─────────────────────────

def test_faiths_absent_on_a_default_world():
    assert "faiths" not in _world(faith=False).to_snapshot()


def test_populated_faiths_round_trip():
    w = _world()
    w.tick = 5
    f = w.mint_faith("ada")
    f.members = ["ada", "dot"]
    f.meme_id = "mem_faith1"
    f.temple_id = "b_temple"
    f.hostile_to = ["fth_other000"]
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert _dumps(restored.to_snapshot()) == _dumps(snap)
    r = restored.faiths[f.id]
    assert r.members == ["ada", "dot"] and r.meme_id == "mem_faith1"
    assert r.temple_id == "b_temple" and r.hostile_to == ["fth_other000"]
    assert r.tenets == f.tenets and r.deity == f.deity


def test_restore_drops_garbage_faith_rows():
    w = _world(faith=False)
    snap = w.to_snapshot()
    snap["faiths"] = {
        "fth_ok123456": {"name": "n", "deity": "d", "founder_id": "ada",
                         "founded_tick": 1, "tenets": ["t"]},
        "": {"name": "blank id"},                         # blank id → dropped
        "fth_bad": "not-a-dict",                          # non-dict → dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert list(restored.faiths) == ["fth_ok123456"]
    r = restored.faiths["fth_ok123456"]
    assert r.members == [] and r.temple_id is None and r.parent_id is None


# ── AgentState faith_id / devotion ────────────────────────────────────────────

def test_faith_fields_default_and_omitted():
    a = _a("ada")
    assert a.faith_id is None and a.devotion == 0
    d = a.to_dict()
    assert "faith_id" not in d and "devotion" not in d


def test_faith_fields_serialized_only_when_non_default():
    a = _a("ada", faith_id="fth_ab12cd34", devotion=42)
    d = a.to_dict()
    assert d["faith_id"] == "fth_ab12cd34"
    assert d["devotion"] == 42


def test_devotion_clamps_and_faith_id_coerces_on_restore():
    w = _world(faith=False)
    snap = w.to_snapshot()
    snap["agents"][0]["devotion"] = 250                   # over cap → 100
    snap["agents"][0]["faith_id"] = "fth_ab12cd34"
    snap["agents"][1]["devotion"] = -5                    # under → 0
    snap["agents"][1]["faith_id"] = "   "                 # blank → None
    restored = World.from_snapshot(snap, params=_params())
    a0 = restored.agents[snap["agents"][0]["id"]]
    a1 = restored.agents[snap["agents"][1]["id"]]
    assert a0.devotion == 100 and a0.faith_id == "fth_ab12cd34"
    assert a1.devotion == 0 and a1.faith_id is None


# ── co_religionist relationship type ──────────────────────────────────────────

def test_co_religionist_in_types_but_not_declarable():
    assert "co_religionist" in RELATIONSHIP_TYPES
    assert "co_religionist" not in DECLARABLE_RELATIONSHIP_TYPES


def test_agents_cannot_hand_declare_co_religionist():
    ada, dot = _a("ada"), _a("dot")
    w = _world([ada, dot])
    ok, reason = w.action_set_relationship(ada, dot, "co_religionist")
    assert not ok
    assert "invalid relationship type" in reason


# ── config block ──────────────────────────────────────────────────────────────

def test_faith_params_defaults_and_parse():
    p = FaithParams()
    assert p.enabled is False                             # DEFAULT OFF (golden)
    assert p.temple_buff == 5
    assert p.conversion_chance == 0.3
    assert p.devotion_decay == 1
    assert p.schism_threshold == 50
    assert p.schism_grace == 20
    assert _parse_faith(None) == FaithParams()            # absent block
    assert _parse_faith({}) == FaithParams()
    assert _parse_faith("junk") == FaithParams()
    assert _parse_faith({"enabled": True, "temple_buff": 9}) == FaithParams(
        enabled=True, temple_buff=9)


def test_faith_enabled_accessor_conventions():
    w = _world(faith=False)
    assert w.faith_enabled() is False                     # dataclass default
    w.params.faith = None                                 # absent block
    assert w.faith_enabled() is False
    w.params.faith = {"enabled": True}                    # EM-155 dict convention
    assert w.faith_enabled() is True


# ── the invented-pool denylist (NO real religions / deities / prophets) ───────

# Real-world religions, deities, prophets, and scriptures. Matched as WHOLE
# lowercase tokens against the seeded pools (so an invented word merely
# *containing* a short real substring never false-positives).
_REAL_RELIGION_DENYLIST: frozenset[str] = frozenset({
    # religions / traditions
    "christianity", "christian", "catholic", "protestant", "orthodox",
    "baptist", "methodist", "presbyterian", "lutheran", "evangelical",
    "mormon", "islam", "islamic", "muslim", "sunni", "shia", "shiite", "sufi",
    "judaism", "jewish", "jew", "buddhism", "buddhist", "hinduism", "hindu",
    "sikhism", "sikh", "taoism", "taoist", "daoism", "shinto", "jainism",
    "jain", "zoroastrian", "zoroastrianism", "bahai", "wicca", "wiccan",
    "druid", "druidism", "scientology", "rastafarian", "confucianism",
    "confucian", "pagan", "paganism",
    # deities / divine figures
    "god", "allah", "yahweh", "jehovah", "elohim", "yhwh", "jesus", "christ",
    "muhammad", "mohammed", "buddha", "gautama", "siddhartha", "krishna",
    "vishnu", "shiva", "brahma", "ganesha", "rama", "kali", "durga", "lakshmi",
    "zeus", "hera", "poseidon", "apollo", "athena", "ares", "hades", "hermes",
    "aphrodite", "hephaestus", "artemis", "dionysus", "odin", "thor", "loki",
    "freya", "freyr", "baldr", "heimdall", "ra", "osiris", "isis", "horus",
    "anubis", "thoth", "amun", "jupiter", "juno", "minerva", "mars", "venus",
    "saturn", "neptune", "mercury", "gaia", "cronus", "uranus", "nyx",
    "quetzalcoatl", "marduk", "ishtar", "inanna", "baal", "dagon",
    "ahura", "mazda",
    # prophets / patriarchs / founders
    "moses", "abraham", "noah", "isaac", "jacob", "david", "solomon",
    "elijah", "isaiah", "jeremiah", "ezekiel", "mary", "peter", "paul",
    "nanak", "zoroaster", "confucius", "laozi", "mahavira", "guru",
    # scriptures / texts
    "bible", "gospel", "quran", "koran", "torah", "talmud", "vedas", "veda",
    "upanishad", "gita", "bhagavad", "tripitaka", "sutra", "tanakh",
    "pentateuch", "psalms", "genesis", "exodus", "revelation", "hadith",
    "avesta",
})


def _tokens(entry: str) -> set[str]:
    # Unicode word tokens, lowercased (û etc. stay part of their token).
    return {t.lower() for t in re.findall(r"[^\W_]+", entry, re.UNICODE)}


def test_faith_pools_hold_no_real_religion():
    for entry in (*_FAITH_NAMES, *_FAITH_DEITIES, *_FAITH_TENETS):
        hits = _tokens(entry) & _REAL_RELIGION_DENYLIST
        assert not hits, f"real-religion token(s) {hits} in invented pool: {entry!r}"


def test_faith_pools_are_non_empty_and_sized_for_distinct_tenets():
    assert len(_FAITH_NAMES) >= 3
    assert len(_FAITH_DEITIES) >= 3
    assert len(_FAITH_TENETS) >= 3               # mint_faith picks 3 distinct

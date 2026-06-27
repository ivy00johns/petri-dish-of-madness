"""Wave C / EM-147 — the district town (contracts/wave-c.md, Agent C1).

Pins the ONE schema delta of Wave C — the optional, additive
`district: str | None` on places — and proves the hand-authored ~15-place
district town actually runs:

  1. `district` round-trips config → PlaceState → to_dict() → from_snapshot.
  2. Back-compat: a snapshot WITHOUT the key restores with district=None, and
     a district-less PlaceState serializes WITHOUT the key (pre-Wave-C
     snapshots stay byte-identical — additive-only contract, rule 4).
  3. The shipped config/world.yaml town and loader.py's embedded default
     mirror stay in sync (same ids/kinds/coords/districts), keep the gate ids
     (`plaza` social anchor, `townhall` first governance), keep the original
     five place ids alive, and respect the layout law (within-district
     spacing >= 60, district centroids >= 250 apart, plaza near center).
  4. The full 15-place town boots and runs end-to-end on the deterministic
     mock path: movement across districts, the building pipeline at a
     non-core place, the billboard/notice-board gates, and a snapshot
     round-trip preserving every place + district.
  5. Procgen compatibility: generate_procgen_places stays district-less
     (district=None, key absent from to_dict()).

Free-scale law: the duck router pins exactly one chat call per turn.

Import-order idiom (test_god_voice.py): petridish.engine.world MUST be
imported before petridish.agents.runtime (circular import otherwise).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from petridish.engine.world import PlaceState, AgentState, World, generate_procgen_places
from petridish.config.loader import (
    EMBEDDED_WORLD_YAML, PlaceConfig, WorldParams, load_config, _parse_world,
)
from petridish.agents.runtime import AgentRuntime

import yaml

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

DISTRICTS = {"core", "market", "residential", "civic", "farm"}
# EM-240 added a `civic`-kind place (the jail) to the civic district.
KINDS = {"social", "work", "governance", "home", "wild", "civic"}
# The pre-Wave-C town; these ids must survive (old snapshots/agent locations).
LEGACY_IDS_KINDS = {
    "plaza": "social", "market": "work", "townhall": "governance",
    "commons": "wild", "home": "home",
}

_IDLE_JSON = '{"action": "idle", "args": {}}'


class _DuckRouter:
    """Minimal duck-typed router (the test_god_voice idiom): returns a canned
    response and counts chat calls so the free-scale law stays pinned."""

    def __init__(self, response: str = _IDLE_JSON):
        self.response = response
        self.calls = 0

    def profile_name_for(self, agent_id, agent_profile):
        return agent_profile

    def get_profile(self, name):
        return None

    async def chat(self, profile_name, messages, *, max_tokens, temperature):
        self.calls += 1
        self.last_messages = messages
        return self.response

    def last_usage(self, profile_name):
        return None

    def last_routed_via(self, profile_name):
        return None


def _events(result: dict) -> list[dict]:
    return result["_multi"] if "_multi" in result else [result]


def _load_town(monkeypatch) -> list[PlaceConfig]:
    """The shipped config/world.yaml town, pinned to the repo config dir so
    the test is independent of cwd / a stray EM_CONFIG_DIR."""
    monkeypatch.setenv("EM_CONFIG_DIR", str(REPO_CONFIG_DIR))
    return load_config(profile_override="mock").places


def _town_world(places_cfg: list[PlaceConfig], n_agents: int = 2) -> World:
    params = WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=40,
        snapshot_interval_ticks=1000,
    )
    places = [
        PlaceState(id=p.id, name=p.name, x=p.x, y=p.y, kind=p.kind,
                   description=p.description, district=p.district)
        for p in places_cfg
    ]
    agents = [
        AgentState(id=f"a{i}", name=f"Agent{i}", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=40)
        for i in range(n_agents)
    ]
    return World(params=params, places=places, agents=agents)


# ── 1. the round-trip ─────────────────────────────────────────────────────────

def test_district_round_trips_config_to_state_to_snapshot(monkeypatch):
    places_cfg = _load_town(monkeypatch)
    by_id = {p.id: p for p in places_cfg}
    assert by_id["plaza"].district == "core"

    world = _town_world(places_cfg)
    # config -> PlaceState
    assert world.places["farmstead"].district == "farm"
    # PlaceState -> to_dict
    d = world.places["townhall"].to_dict()
    assert d["district"] == "civic"
    # snapshot -> from_snapshot
    restored = World.from_snapshot(world.to_snapshot())
    for pid, place in world.places.items():
        assert restored.places[pid].district == place.district
        assert restored.places[pid].kind == place.kind


def test_placeconfig_district_parses_and_defaults_none():
    raw = {
        "places": [
            {"id": "p1", "name": "P1", "x": 1, "y": 2, "kind": "social",
             "district": "core"},
            {"id": "p2", "name": "P2", "x": 3, "y": 4, "kind": "work"},
        ]
    }
    _, places, _ = _parse_world(raw)
    assert places[0].district == "core"
    assert places[1].district is None


# ── 2. back-compat: absent district ───────────────────────────────────────────

def test_absent_district_defaults_none_and_stays_off_the_wire():
    # A district-less place serializes WITHOUT the key (pre-Wave-C snapshots
    # stay byte-identical — additive-only contract).
    p = PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")
    assert p.district is None
    assert "district" not in p.to_dict()

    # A pre-Wave-C snapshot (no `district` key anywhere) restores fine.
    legacy_snapshot = {
        "tick": 7, "day": 0, "round": 2,
        "places": [
            {"id": "plaza", "name": "Plaza", "x": 500, "y": 500,
             "kind": "social", "description": "", "blackout_until_tick": 0},
            {"id": "home", "name": "Hearth", "x": 300, "y": 650,
             "kind": "home", "description": "", "blackout_until_tick": 0},
        ],
        "agents": [
            {"id": "ada", "name": "Ada", "location": "plaza",
             "energy": 50.0, "credits": 5, "alive": True},
        ],
    }
    world = World.from_snapshot(legacy_snapshot)
    assert world.places["plaza"].district is None
    assert world.places["home"].district is None
    assert "district" not in world.places["plaza"].to_dict()
    assert world.tick == 7


# ── 3. the authored town: sync, gates, layout law ─────────────────────────────

def _places_signature(places) -> list[tuple]:
    return sorted(
        (p.id, p.name, p.x, p.y, p.kind, p.district) for p in places
    )


def test_yaml_town_and_embedded_mirror_stay_in_sync(monkeypatch):
    yaml_places = _load_town(monkeypatch)
    _, embedded_places, _ = _parse_world(yaml.safe_load(EMBEDDED_WORLD_YAML))
    assert _places_signature(yaml_places) == _places_signature(embedded_places)


def test_town_shape_gates_and_legacy_ids(monkeypatch):
    places = _load_town(monkeypatch)
    by_id = {p.id: p for p in places}

    assert len(places) == 16   # EM-240 added the jail (a civic-kind place)
    assert {p.district for p in places} == DISTRICTS
    assert {p.kind for p in places} <= KINDS

    # Gate ids: the social anchor keeps id `plaza`, the FIRST governance
    # place keeps id `townhall` (billboard/notice-board gates key on these).
    assert by_id["plaza"].kind == "social" and by_id["plaza"].district == "core"
    first_gov = next(p for p in places if p.kind == "governance")
    assert first_gov.id == "townhall"

    # The original five survive with their kinds (old snapshots stay valid).
    for pid, kind in LEGACY_IDS_KINDS.items():
        assert by_id[pid].kind == kind, f"{pid} lost its kind"

    # District composition per the contract.
    by_district: dict[str, list] = {}
    for p in places:
        by_district.setdefault(p.district, []).append(p)
    assert {p.kind for p in by_district["core"]} == {"social"}
    assert all(p.kind == "work" for p in by_district["market"])
    assert 2 <= len(by_district["market"]) <= 3
    assert all(p.kind == "home" for p in by_district["residential"])
    assert 3 <= len(by_district["residential"]) <= 4
    assert any(p.kind == "governance" for p in by_district["civic"])
    # EM-240 — civic now holds townhall + archive (governance) + the jail (civic).
    assert len(by_district["civic"]) == 3
    assert {p.kind for p in by_district["civic"]} == {"governance", "civic"}
    assert {p.kind for p in by_district["farm"]} <= {"wild", "work"}


def test_town_layout_law(monkeypatch):
    places = _load_town(monkeypatch)
    by_district: dict[str, list] = {}
    for p in places:
        assert 0 <= p.x <= 1000 and 0 <= p.y <= 1000
        by_district.setdefault(p.district, []).append(p)

    # Plaza near the center.
    plaza = next(p for p in places if p.id == "plaza")
    assert math.hypot(plaza.x - 500, plaza.y - 500) <= 60

    # Within-district spacing >= 60 logical units.
    for district, members in by_district.items():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                dist = math.hypot(a.x - b.x, a.y - b.y)
                assert dist >= 60, f"{a.id} and {b.id} crowd {district} ({dist:.0f})"

    # District centroids >= 250 apart.
    centroids = {
        d: (sum(p.x for p in ms) / len(ms), sum(p.y for p in ms) / len(ms))
        for d, ms in by_district.items()
    }
    names = sorted(centroids)
    for i, da in enumerate(names):
        for db in names[i + 1:]:
            (ax, ay), (bx, by_) = centroids[da], centroids[db]
            dist = math.hypot(ax - bx, ay - by_)
            assert dist >= 250, f"districts {da}/{db} too close ({dist:.0f})"


# ── 4. the 15-place town runs end-to-end (deterministic mock path) ────────────

@pytest.mark.asyncio
async def test_full_town_runs_end_to_end_on_the_mock_path(monkeypatch):
    places_cfg = _load_town(monkeypatch)
    world = _town_world(places_cfg)
    router = _DuckRouter()
    rt = AgentRuntime(world, router)
    ada = world.agents["a0"]

    # Movement between districts: core (plaza) -> farm (farmstead).
    router.response = '{"action": "move_to", "args": {"place": "farmstead"}}'
    result = await rt.run_turn(ada)
    assert any(e["kind"] == "agent_moved" for e in _events(result))
    assert ada.location == "farmstead"

    # Building pipeline at a NON-core place (the farmstead).
    router.response = ('{"action": "propose_project", "args": {"name": "grain_barn", '
                       '"kind": "barn", "funds_required": 10}}')
    result = await rt.run_turn(ada)
    kinds = [e["kind"] for e in _events(result)]
    assert "project_proposed" in kinds
    building = next(b for b in world.buildings.values() if b.location == "farmstead")

    router.response = ('{"action": "contribute_funds", "args": {"building_id": "%s", '
                       '"amount": 10}}' % building.id)
    result = await rt.run_turn(ada)
    assert any(e["kind"] == "project_funded" for e in _events(result))
    assert building.status == "under_construction"

    router.response = ('{"action": "build_step", "args": {"building_id": "%s"}}'
                       % building.id)
    for _ in range(5):  # build_step=20 -> 5 steps to operational
        await rt.run_turn(ada)
    assert building.status == "operational"
    assert building.progress >= 100

    # Billboard/notice-board gates still resolve in the 15-place town.
    assert world.billboard_here("plaza") is True
    assert world.billboard_here("townhall") is True
    assert world.billboard_here("farmstead") is False
    bo = world.agents["a1"]
    assert bo.location == "plaza"
    router.response = '{"action": "post_billboard", "args": {"text": "well meet at noon"}}'
    result = await rt.run_turn(bo)
    assert any(e["kind"] == "billboard_posted" for e in _events(result))
    assert world.billboard[-1]["text"] == "well meet at noon"

    # Free-scale law: exactly one chat call per turn, nothing extra.
    assert router.calls == 9

    # Snapshot round-trip of the LIVE 15-place world preserves every place,
    # district, and the operational building.
    snap = world.to_snapshot()
    restored = World.from_snapshot(snap)
    assert set(restored.places) == set(world.places)
    for pid, place in world.places.items():
        r = restored.places[pid]
        assert (r.district, r.kind, r.x, r.y) == (
            place.district, place.kind, place.x, place.y)
    assert restored.agents["a0"].location == "farmstead"
    assert restored.buildings[building.id].status == "operational"


# ── 5. procgen compatibility: stays district-less (additive) ──────────────────

def test_procgen_places_emit_no_district():
    from petridish.config.loader import ProcgenParams
    places = generate_procgen_places(ProcgenParams(enabled=True, seed=7, n_places=9),
                                     ["Ada", "Bram"])
    assert len(places) > 0
    for p in places:
        assert p.district is None
        assert "district" not in p.to_dict()

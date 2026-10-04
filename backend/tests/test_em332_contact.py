"""EM-332 — First Contact keystone: ONE world, TWO settlements, the roster
split between them and each half cast from a DIFFERENT model family.

Layers covered (each at its own seam):
  - engine.world.contact_roster_split — the ONE split rule (roster NAME order,
    never boot agent ids — those carry a uuid suffix and would randomize a
    sorted split per boot).
  - engine.world.seed_genesis_settlement — the contact branch: dual genesis,
    town B's starter place cluster (namespaced ids, seed-shifted layout), the
    roster split into their homes, and per-city perception isolation.
  - config/loader — the `world.contact` block parse (defaults + clamps).
  - api/tournament.build_contact_cast_plan — the split cast (available lanes
    first, deterministic round-robin per half) + validation errors.
  - API endpoint (TestClient) — POST /api/arena/contact boots the two-town
    world and arms the contact block on the reset config; 400 paths.

Deterministic and offline (mock lanes / no network). Byte-identity when the
flag is OFF is pinned at the genesis seam (the EM-155 keystone).
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import dataclasses
import json
import sys

import pytest

from petridish.engine.world import World, AgentState, PlaceState, contact_roster_split
from petridish.config.loader import (
    AgentConfig,
    ContactParams,
    ModelProfile,
    SettlementParams,
    WorldConfig,
    WorldParams,
    _parse_contact,
    load_config,
)
from petridish.api.tournament import build_contact_cast_plan


# ── fixtures ──────────────────────────────────────────────────────────────────

_PLACES = [
    PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
    PlaceState(id="well", name="Well", x=520, y=460, kind="social"),
    PlaceState(id="market", name="Market", x=560, y=520, kind="work"),
]
_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve", "Fay"]

_LEGEND = [
    {"name": "gemini-x", "model_id": "gemini-3.5-flash", "available": True},
    {"name": "gemini-y", "model_id": "gemini-2.0-flash", "available": False},
    {"name": "llama-x", "model_id": "llama-3.3-70b-fp8-fast", "available": True},
    {"name": "llama-y", "model_id": "llama-3.1-8b-instant", "available": True},
]


def _params(*, settlements=True, contact=True) -> WorldParams:
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=settlements)
    if contact:
        p.contact = ContactParams(enabled=True, family_a="gemini",
                                  family_b="llama", name_b="Grimstead")
    return p


def _agents(n=6, uuidish=False):
    """The seed roster, in config order. `uuidish` mints boot-style ids (the
    uuid suffix the real boot appends) to prove the split is id-blind."""
    out = []
    for i, name in enumerate(_NAMES[:n]):
        aid = (f"agent_{name.lower()}_{str(i * 7919)[-6:]}" if uuidish
               else f"agent_{name.lower()}_{i}")
        out.append(AgentState(id=aid, name=name, personality="", profile="mock",
                              location="plaza", energy=80.0, credits=20))
    return out


def _contact_world(n=6, uuidish=False):
    w = World(params=_params(),
              places=[copy.copy(p) for p in _PLACES],
              agents=_agents(n, uuidish=uuidish))
    w.seed_genesis_settlement()
    return w


def _towns(w):
    """(sid_a, sid_b) — B is the founder_id=='contact' settlement."""
    sid_b = next(s for s in w.settlements
                 if w.settlements[s]["founder_id"] == "contact")
    sid_a = next(s for s in w.settlements if s != sid_b)
    return sid_a, sid_b


# ── 1. contact_roster_split — the ONE rule (contract pins) ───────────────────

def test_split_keeps_roster_order_not_sorted():
    # Sorted ids would interleave a 10-agent roster (a10 < a2) — the split is
    # ROSTER order, the only identity both config and world agree on.
    a, b = contact_roster_split(["a5", "a1", "a3", "a2", "a4", "a6"])
    assert (a, b) == (["a5", "a1", "a3"], ["a2", "a4", "a6"])


def test_split_odd_roster_gives_a_the_majority():
    a, b = contact_roster_split(["n1", "n2", "n3", "n4", "n5"])
    assert (len(a), len(b)) == (3, 2)
    assert a + b == ["n1", "n2", "n3", "n4", "n5"]


def test_split_empty_safe():
    assert contact_roster_split([]) == ([], [])
    assert contact_roster_split(["solo"]) == (["solo"], [])


# ── 2. dual genesis ───────────────────────────────────────────────────────────

def test_contact_world_seeds_two_settlements():
    w = _contact_world()
    assert len(w.settlements) == 2
    sid_a, sid_b = _towns(w)
    assert w.settlements[sid_b]["name"] == "Grimstead"  # the contact block's name
    assert w.settlements[sid_b]["founder_id"] == "contact"
    assert w.settlements[sid_a]["founder_id"] == "genesis"


def test_roster_split_into_their_homes_and_bodies():
    w = _contact_world()
    sid_a, sid_b = _towns(w)
    # First half (roster order) stays in the genesis town…
    assert [w.agents[m].name for m in w.settlements[sid_a]["members"]] == \
        ["Ann", "Bob", "Cleo"]
    # …the rest are town B, home + body moved to B's plaza.
    assert [w.agents[m].name for m in w.settlements[sid_b]["members"]] == \
        ["Dex", "Eve", "Fay"]
    for m in w.settlements[sid_b]["members"]:
        assert w.agents[m].home_settlement_id == sid_b
        assert w.agents[m].location == "cb_plaza"
    for m in w.settlements[sid_a]["members"]:
        assert w.agents[m].home_settlement_id == sid_a


def test_town_b_gets_a_namespaced_starter_cluster():
    w = _contact_world()
    b_ids = [p.id for p in w.places.values() if p.id.startswith("cb_")]
    # The generator's guarantees survive the namespacing: plaza + town hall
    # (governance) + work/wild minimums + one home per B agent.
    assert "cb_plaza" in b_ids and "cb_townhall" in b_ids
    kinds = {p.id: p.kind for p in w.places.values() if p.id.startswith("cb_")}
    assert "governance" in kinds.values() and "work" in kinds.values()
    assert "wild" in kinds.values()
    homes = [p for p in w.places.values()
             if p.id.startswith("cb_") and p.kind == "home"]
    # One NAMED cottage per B agent (plus the communal bunkhouse and whatever
    # home-kind picks the weighted layout made — the per-agent guarantee is
    # the named cottage, so assert by name).
    cottage_names = " | ".join(p.name for p in homes)
    for name in ("Dex", "Eve", "Fay"):
        assert f"{name}'s cottage" in cottage_names, cottage_names
    # No id or name collides with town A's places.
    a_names = {p.name for p in w.places.values() if not p.id.startswith("cb_")}
    b_names = {p.name for p in w.places.values() if p.id.startswith("cb_")}
    assert not a_names & b_names


def test_perception_isolation_voronoi():
    """Every B place falls on B's side of the nearest-center partition (the
    per-city perception horizon that keeps the towns isolated pre-contact)."""
    w = _contact_world()
    sid_a, sid_b = _towns(w)
    for p in w.places.values():
        want = sid_b if p.id.startswith("cb_") else sid_a
        assert w.settlement_of_place(p) == want, p.id


def test_contact_genesis_is_deterministic_across_boots():
    """Fresh uuid-style ids every boot; the SPLIT and town B's layout must not
    care (same roster order ⇒ same towns, byte-stable place ids/names)."""
    w1 = _contact_world(uuidish=True)
    w2 = _contact_world(uuidish=True)
    _, b1 = _towns(w1)
    _, b2 = _towns(w2)
    assert [w1.agents[m].name for m in w1.settlements[b1]["members"]] == \
        [w2.agents[m].name for m in w2.settlements[b2]["members"]]
    cb1 = [(p.id, p.name, p.x, p.y) for p in w1.places.values()
           if p.id.startswith("cb_")]
    cb2 = [(p.id, p.name, p.x, p.y) for p in w2.places.values()
           if p.id.startswith("cb_")]
    assert cb1 == cb2


def test_genesis_recall_is_a_no_op():
    w = _contact_world()
    snap = w.to_snapshot({})
    w.seed_genesis_settlement()
    w.seed_genesis_settlement()
    assert w.to_snapshot({}) == snap


def test_contact_world_round_trips_through_a_snapshot():
    w = _contact_world()
    restored = World.from_snapshot(copy.deepcopy(w.to_snapshot({})),
                                   params=_params())
    assert len(restored.settlements) == 2
    sid_a, sid_b = _towns(restored)
    assert w.settlements[sid_a] == restored.settlements[sid_a]
    assert w.settlements[sid_b] == restored.settlements[sid_b]
    assert {m: a.home_settlement_id for m, a in restored.agents.items()} == \
        {m: a.home_settlement_id for m, a in w.agents.items()}
    assert "cb_townhall" in restored.places


# ── 3. flag gates — the EM-155 byte-identity keystone ─────────────────────────

def test_contact_off_is_byte_identical_single_genesis():
    on = World(params=_params(contact=False),
               places=[copy.copy(p) for p in _PLACES], agents=_agents())
    off = World(params=_params(contact=False),
                places=[copy.copy(p) for p in _PLACES], agents=_agents())
    off.params.contact = ContactParams()  # present but disabled
    on.seed_genesis_settlement()
    off.seed_genesis_settlement()
    assert len(on.settlements) == 1 and len(off.settlements) == 1
    assert off.to_snapshot({}) == on.to_snapshot({})
    # …and identical to a params object with NO contact field at all
    # (pre-EM-332 configs): the defensive accessor defaults it.


def test_contact_block_without_settlements_is_a_no_op():
    p = _params(settlements=False, contact=True)
    w = World(params=p, places=[copy.copy(q) for q in _PLACES], agents=_agents())
    w.seed_genesis_settlement()
    assert w.settlements == {}
    assert all(a.home_settlement_id is None for a in w.agents.values())
    assert not any(p.id.startswith("cb_") for p in w.places.values())


def test_contact_needs_at_least_two_agents():
    w = World(params=_params(), places=[copy.copy(p) for p in _PLACES],
              agents=_agents(n=1))
    w.seed_genesis_settlement()
    assert len(w.settlements) == 1  # no second founding from a solo world


# ── 4. config parse ───────────────────────────────────────────────────────────

def test_parse_contact_defaults_and_clamps():
    c = _parse_contact(None)
    assert c == ContactParams()  # absent block ⇒ OFF, byte-identical
    c = _parse_contact({"enabled": True, "family_a": "gemini",
                        "family_b": "llama", "margin": "junk",
                        "n_places": -3, "seed_offset": None})
    assert c.enabled and c.family_a == "gemini" and c.family_b == "llama"
    assert c.margin == 60 and c.n_places == 4 and c.seed_offset == 1  # clamped


# ── 5. the split cast ─────────────────────────────────────────────────────────

def _contact_cfg(n=6):
    return WorldConfig(
        world=_params(),
        agents=[AgentConfig(name=n_, personality="", profile="mock",
                            location="plaza") for n_ in _NAMES[:n]],
    )


def test_cast_plan_splits_the_roster_by_family():
    plan = build_contact_cast_plan(_contact_cfg(), _LEGEND, "gemini", "llama")
    assert plan.families == ("gemini", "llama")
    # First half (roster order) draws gemini lanes, rest llama.
    assert plan.profile_by_agent["Ann"].startswith("gemini")
    assert plan.profile_by_agent["Bob"].startswith("gemini")
    assert plan.profile_by_agent["Cleo"].startswith("gemini")
    assert all(plan.profile_by_agent[n].startswith("llama")
               for n in ("Dex", "Eve", "Fay"))
    # Available lanes first, round-robin within a family.
    assert plan.lanes_a == ["gemini-x"]  # gemini-y is unavailable
    assert plan.lanes_b == ["llama-x", "llama-y"]
    assert plan.profile_by_agent["Dex"] == "llama-x"
    assert plan.profile_by_agent["Eve"] == "llama-y"
    assert plan.profile_by_agent["Fay"] == "llama-x"
    # The returned config's agents carry the replaced profiles.
    prof = {a.name: a.profile for a in plan.config.agents}
    assert prof == plan.profile_by_agent


def test_cast_plan_is_deterministic():
    c1 = build_contact_cast_plan(_contact_cfg(), _LEGEND, "gemini", "llama")
    c2 = build_contact_cast_plan(_contact_cfg(), _LEGEND, "gemini", "llama")
    assert c1.profile_by_agent == c2.profile_by_agent
    assert c1.lanes_a == c2.lanes_a and c1.lanes_b == c2.lanes_b


def test_cast_plan_and_genesis_agree_on_the_split():
    """The keystone invariant: the profiles the cast plan assigns and the homes
    the contact genesis assigns put the SAME agents in the SAME town."""
    plan = build_contact_cast_plan(_contact_cfg(), _LEGEND, "gemini", "llama")
    w = _contact_world()
    _, sid_b = _towns(w)
    b_names = {w.agents[m].name for m in w.settlements[sid_b]["members"]}
    assert {n for n, fam in plan.profile_by_agent.items()
            if fam.startswith("llama")} == b_names


@pytest.mark.parametrize(
    ("fam_a", "fam_b", "err"),
    [
        ("gemini", "gemini", "must differ"),
        ("gemini", "qwen", "unknown family"),
        ("gemini", "other", "cannot be cast"),
        ("", "llama", "required"),
        ("gemini", "", "required"),
    ],
)
def test_cast_plan_rejects_bad_requests(fam_a, fam_b, err):
    with pytest.raises(ValueError, match=err):
        build_contact_cast_plan(_contact_cfg(), _LEGEND, fam_a, fam_b)


def test_cast_plan_needs_two_agents():
    with pytest.raises(ValueError, match="at least 2 agents"):
        build_contact_cast_plan(_contact_cfg(n=1), _LEGEND, "gemini", "llama")


# ── 6. the endpoint (TestClient, mock-adapter legend) ─────────────────────────

_TEST_PROFILES = [
    ModelProfile(name="gemini-x", adapter="mock", model_id="gemini-3.5-flash", color="#111111"),
    ModelProfile(name="llama-x", adapter="mock", model_id="llama-3.3-70b-fp8-fast", color="#222222"),
    ModelProfile(name="llama-y", adapter="mock", model_id="llama-3.1-8b-instant", color="#444444"),
    ModelProfile(name="auto", adapter="mock", model_id="auto", color="#333333"),
    # The boot roster's own profile (the fixture patches agents onto "mock") —
    # the router must know it or boot raises Unknown profile.
    ModelProfile(name="mock", adapter="mock", model_id="mock", color="#555555"),
]


@pytest.fixture
def contact_client(monkeypatch):
    """The real app booted on a config whose PROFILES are mock-adapter lanes
    spanning two families — the contact reset boots offline at mock speed."""
    from fastapi.testclient import TestClient

    import petridish.api.app as _app_pkg  # noqa: F401  (ensures the module is loaded)
    appmod = sys.modules["petridish.api.app"]

    base = load_config()
    agents = [
        AgentConfig(name=a.name, personality=a.personality, profile="mock",
                    location=a.location)
        for a in base.agents[:6]
    ]
    assert len(agents) >= 2, "the boot roster must not be empty"
    patched = dataclasses.replace(base, profiles=_TEST_PROFILES, agents=agents)
    monkeypatch.setattr(appmod, "load_config", lambda *a, **k: patched)
    monkeypatch.setattr(appmod, "_tournament", None)

    with TestClient(appmod.app, raise_server_exceptions=True) as client:
        yield client, appmod


def test_contact_endpoint_boots_two_towns(contact_client):
    client, appmod = contact_client
    body = client.post("/api/arena/contact",
                       json={"family_a": "gemini", "family_b": "llama"})
    assert body.status_code == 202, body.text
    out = body.json()
    assert out["status"] == "started"
    assert out["families"] == ["gemini", "llama"]

    world = appmod._loop._world
    assert len(world.settlements) == 2
    sid_b = next(s for s in world.settlements
                 if world.settlements[s]["founder_id"] == "contact")
    b_names = {world.agents[m].name
               for m in world.settlements[sid_b]["members"]}
    llama_names = {n for n, prof in out["casts"].items()
                   if prof.startswith("llama")}
    # The keystone invariant, end to end: the cast the endpoint returned and
    # the homes the fresh world laid out put the SAME agents in town B.
    assert b_names == llama_names

    # The run row self-describes: its config_json carries the armed block.
    row = appmod._repo.get_run(appmod._loop._run_id)
    cfg_json = json.loads(row["config_json"])
    assert cfg_json["world"]["contact"]["enabled"] is True
    assert cfg_json["world"]["contact"]["family_a"] == "gemini"
    assert cfg_json["world"]["contact"]["family_b"] == "llama"
    assert cfg_json["world"]["contact"]["honesty"] is True  # EM-333 arms SB


def test_contact_endpoint_400_on_bad_families(contact_client):
    client, _ = contact_client
    r = client.post("/api/arena/contact",
                    json={"family_a": "gemini", "family_b": "qwen"})
    assert r.status_code == 400
    assert "unknown family" in r.json()["detail"]
    r = client.post("/api/arena/contact",
                    json={"family_a": "gemini", "family_b": "gemini"})
    assert r.status_code == 400
    assert "must differ" in r.json()["detail"]

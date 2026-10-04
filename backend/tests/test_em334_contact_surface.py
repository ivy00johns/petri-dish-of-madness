"""EM-334 — First Contact measurement + frontend (SC): the contact tick
marker, the /api/contact read surface, and the per-settlement Arena cards.

Layers covered (each at its own seam):
  - engine.world.action_travel_to — the FIRST cross-town departure in a
    contact world stamps the one-shot `contact_made` latch and parks the
    `contact_made` event (the Chronicle chapter boundary — the chronicler
    windows events; no new LLM call). Honesty-independent (keystone
    measurement); non-contact worlds never stamp; write-once.
  - engine.world snapshot — the latch round-trips only-when-set.
  - api/arena.py — contact_runs: every run whose config_json carries an
    ARMED contact block gets a card with the family pairing, per-settlement
    populations from its latest snapshot, the honesty ledger, and the
    crossing/travel event counts.
  - GET /api/contact — the live read surface (settlement cards, marker,
    ledger, recent crossings/travels); {enabled: false} without the block.

Deterministic and offline (mock lanes / no network). Byte-identity when the
contact block is OFF is inherited from EM-332 (the marker only exists in a
contact world) and pinned at the non-contact travel seam.
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import dataclasses
import json
import sys

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    AgentConfig,
    ContactParams,
    ModelProfile,
    SettlementParams,
    WorldConfig,
    WorldParams,
    load_config,
)
from petridish.persistence.repository import SQLiteRepository
from petridish.api.arena import arena_summary


# ── fixtures (mirroring the EM-332 contact idioms) ────────────────────────────

_PLACES = [
    PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
    PlaceState(id="well", name="Well", x=520, y=460, kind="social"),
    PlaceState(id="market", name="Market", x=560, y=520, kind="work"),
]
_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve", "Fay"]


def _params(*, contact=True, honesty=False) -> WorldParams:
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=True)
    if contact:
        p.contact = ContactParams(enabled=True, family_a="gemini",
                                  family_b="llama", name_b="Grimstead",
                                  honesty=honesty)
    return p


def _agents(n=6):
    out = []
    for i, name in enumerate(_NAMES[:n]):
        out.append(AgentState(id=f"agent_{name.lower()}_{i}", name=name,
                              personality="", profile="mock",
                              location="plaza", energy=80.0, credits=20))
    return out


def _contact_world(n=6, **kw):
    w = World(params=_params(**kw),
              places=[copy.copy(p) for p in _PLACES],
              agents=_agents(n))
    w.seed_genesis_settlement()
    return w


def _towns(w):
    sid_b = next(s for s in w.settlements
                 if w.settlements[s]["founder_id"] == "contact")
    sid_a = next(s for s in w.settlements if s != sid_b)
    return sid_a, sid_b


# ── 1. the contact tick marker ────────────────────────────────────────────────

def test_first_cross_town_departure_stamps_marker():
    w = _contact_world()
    sid_a, sid_b = _towns(w)
    traveler = w.agents[sorted(w.settlements[sid_a]["members"])[0]]
    res = w.action_travel_to(traveler, sid_b)
    assert res["_multi"], "the marker rides the departure as a chain"
    kinds = [leg["kind"] for leg in res["_multi"]]
    assert kinds == ["travel_departed", "contact_made"]
    marker = res["_multi"][1]
    assert "FIRST CONTACT" in marker["text"]
    assert marker["payload"]["chronicle_chapter"] is True
    assert marker["payload"]["to_settlement"] == sid_b
    # The latch: one-shot, agent-stamped, tick-stamped.
    assert w.contact_made == {
        "tick": w.tick, "agent_id": traveler.id,
        "from_settlement": sid_a, "to_settlement": sid_b,
    }


def test_marker_is_write_once():
    w = _contact_world()
    sid_a, sid_b = _towns(w)
    first = w.agents[sorted(w.settlements[sid_a]["members"])[0]]
    second = w.agents[sorted(w.settlements[sid_a]["members"])[1]]
    w.action_travel_to(first, sid_b)
    latch = dict(w.contact_made)
    res = w.action_travel_to(second, sid_b)
    assert res["kind"] == "travel_departed"  # plain departure, no marker leg
    assert "_multi" not in res
    assert w.contact_made == latch  # the latch never rewrites


def test_marker_fires_without_honesty():
    # Keystone measurement: the marker is gated on contact, NOT on
    # contact.honesty — a contact-honesty-OFF world still records WHEN the
    # worlds met (the honesty ledger stays empty).
    w = _contact_world(honesty=False)
    sid_a, sid_b = _towns(w)
    traveler = w.agents[sorted(w.settlements[sid_a]["members"])[0]]
    res = w.action_travel_to(traveler, sid_b)
    assert res["_multi"][1]["kind"] == "contact_made"
    assert w.contact_made is not None
    assert w.contact_ledger == {}


def test_noncontact_world_never_stamps():
    # A plain multi-city world (settlements ON, NO contact block): the same
    # cross-town departure is ordinary travel — byte-identity at this seam.
    w = World(params=_params(contact=False),
              places=[copy.copy(p) for p in _PLACES], agents=_agents())
    w.seed_genesis_settlement()
    sid_a = next(iter(w.settlements))
    w.settlements["stl_faraway"] = {
        "name": "Faraway", "center": (99999.0, 99999.0),
        "founded_tick": 0, "founder_id": "test", "members": [],
    }
    traveler = w.agents[sorted(w.settlements[sid_a]["members"])[0]]
    res = w.action_travel_to(traveler, "stl_faraway")
    assert res["kind"] == "travel_departed"
    assert "_multi" not in res
    assert w.contact_made is None


def test_marker_round_trips_through_a_snapshot():
    w = _contact_world()
    sid_a, sid_b = _towns(w)
    traveler = w.agents[sorted(w.settlements[sid_a]["members"])[0]]
    w.action_travel_to(traveler, sid_b)
    snap = copy.deepcopy(w.to_snapshot({}))
    assert snap["contact_made"]["agent_id"] == traveler.id
    restored = World.from_snapshot(snap, params=_params())
    assert restored.contact_made == w.contact_made


def test_fresh_contact_world_omits_marker_key():
    w = _contact_world()
    assert "contact_made" not in w.to_snapshot({})


# ── 2. per-settlement Arena cards (from the run's config_json pairing) ───────

def _seed_contact_run(repo, tmp_path_name="x"):
    """A contact run row (armed config_json) + a snapshot carrying two towns,
    split homes, the marker latch and the honesty ledger + a few events."""
    cfg = json.dumps({
        "world": {"contact": {"enabled": True, "family_a": "gemini",
                              "family_b": "llama", "name_b": "Grimstead",
                              "honesty": True}},
        "agents": [{"name": "A", "profile": "gemini-flash"},
                   {"name": "B", "profile": "groq-llama"}],
    })
    rid = repo.start_run(cfg)
    state = {
        "settlements": {
            "stl_a": {"name": "Mossmarket", "center": [0.0, 0.0],
                      "founded_tick": 0, "founder_id": "genesis",
                      "members": ["ag_a"]},
            "stl_b": {"name": "Windrow", "center": [900.0, 900.0],
                      "founded_tick": 0, "founder_id": "contact",
                      "members": ["ag_b"]},
        },
        "agents": [
            {"id": "ag_a", "name": "A", "home_settlement_id": "stl_a",
             "origin_settlement_id": "stl_a", "alive": True},
            {"id": "ag_b", "name": "B", "home_settlement_id": "stl_b",
             "origin_settlement_id": "stl_b", "alive": True},
        ],
        "contact_made": {"tick": 12, "agent_id": "ag_a",
                         "from_settlement": "stl_a",
                         "to_settlement": "stl_b"},
        "contact_ledger": {"crossings": 3, "by_family": {
            "gemini": {"hops": 2, "mutated": 1},
            "llama": {"hops": 1, "mutated": 0}}},
    }
    repo.save_world_snapshot(rid, 30, json.dumps(state))
    repo.save_event(rid, {"kind": "contact_made", "payload": {}}, 12)
    repo.save_event(rid, {"kind": "travel_departed", "payload": {}}, 12)
    repo.save_event(rid, {"kind": "meme_crossed_border", "payload": {}}, 14)
    return rid


def test_arena_contact_runs_card(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "arena.sqlite"))
    rid = _seed_contact_run(repo)
    # A plain (non-contact) run must NOT appear as a contact card.
    repo.start_run(json.dumps({"world": {}}))
    out = arena_summary(repo)
    assert len(out["contact_runs"]) == 1
    card = out["contact_runs"][0]
    assert card["run_id"] == rid
    assert card["family_a"] == "gemini" and card["family_b"] == "llama"
    assert card["name_b"] == "Grimstead"
    assert card["population_by_town"] == {"Mossmarket": 1, "Windrow": 1}
    assert card["contact_made"]["tick"] == 12
    assert card["contact_made"]["agent_id"] == "ag_a"
    assert card["ledger"]["crossings"] == 3
    assert card["ledger"]["by_family"]["gemini"] == {"hops": 2, "mutated": 1}
    assert card["events"]["contact_made"] == 1
    assert card["events"]["meme_crossed_border"] == 1
    assert card["events"]["travel_departed"] == 1
    assert card["outcomes"]["population"] == 2  # the snapshot floor


def test_arena_contact_card_tolerates_snapshotless_run(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "bare.sqlite"))
    rid = repo.start_run(json.dumps({
        "world": {"contact": {"enabled": True, "family_a": "gemini",
                              "family_b": "llama"}}}))
    out = arena_summary(repo)
    card = out["contact_runs"][0]
    assert card["run_id"] == rid
    assert card["population_by_town"] == {}
    assert card["contact_made"] is None and card["ledger"] is None
    assert card["events"] == {"contact_made": 0, "meme_crossed_border": 0,
                              "rumor_crossed_border": 0,
                              "travel_departed": 0, "travel_arrived": 0}


def test_get_run_configs_batches_every_run_in_one_query(tmp_path):
    """EM-334 follow-up — the batched {run_id: config_json} read: every run's
    raw blob in one dict (the screen input list_runs deliberately omits)."""
    repo = SQLiteRepository(str(tmp_path / "batch.sqlite"))
    assert repo.get_run_configs() == {}          # empty db ⇒ no rows, no error
    rid_a = _seed_contact_run(repo)
    rid_plain = repo.start_run(json.dumps({"world": {}}))    # a plain run
    rid_b = _seed_contact_run(repo)              # a second contact run
    configs = repo.get_run_configs()
    assert set(configs) == {rid_a, rid_plain, rid_b}
    assert json.loads(configs[rid_a])["world"]["contact"]["family_b"] == "llama"
    assert json.loads(configs[rid_plain]) == {"world": {}}


def test_arena_contact_screen_batched_byte_identical(tmp_path):
    """The N+1 fix keeps the projection: exactly the ARMED runs get cards,
    newest-first (list_runs order), with the same pairings the per-run
    get_run() fetch produced — now screened off ONE config read."""
    repo = SQLiteRepository(str(tmp_path / "screen.sqlite"))
    rid_a = _seed_contact_run(repo)
    repo.start_run(json.dumps({"world": {}}))                     # plain
    rid_b = _seed_contact_run(repo)                               # armed
    repo.start_run(json.dumps({"world": {"contact": {
        "enabled": False, "family_a": "gemini",
        "family_b": "llama"}}}))                                  # disarmed
    out = arena_summary(repo)
    assert [c["run_id"] for c in out["contact_runs"]] == [rid_b, rid_a]
    assert all(c["family_a"] == "gemini" and c["family_b"] == "llama"
               for c in out["contact_runs"])
    # The snapshot-fed fields survive the batched screen untouched.
    assert all(c["population_by_town"] == {"Mossmarket": 1, "Windrow": 1}
               for c in out["contact_runs"])


# ── 3. GET /api/contact — the live read surface ──────────────────────────────

_TEST_PROFILES = [
    ModelProfile(name="gemini-x", adapter="mock", model_id="gemini-3.5-flash", color="#111111"),
    ModelProfile(name="llama-x", adapter="mock", model_id="llama-3.3-70b-fp8-fast", color="#222222"),
    ModelProfile(name="auto", adapter="mock", model_id="auto", color="#333333"),
    ModelProfile(name="mock", adapter="mock", model_id="mock", color="#555555"),
]


@pytest.fixture
def contact_client(monkeypatch):
    """The real app booted on mock-adapter profiles spanning two families —
    the contact reset boots offline at mock speed (the EM-332 fixture)."""
    from fastapi.testclient import TestClient

    import petridish.api.app as _app_pkg  # noqa: F401
    appmod = sys.modules["petridish.api.app"]

    base = load_config()
    agents = [
        AgentConfig(name=a.name, personality=a.personality, profile="mock",
                    location=a.location)
        for a in base.agents[:5]
    ]
    patched = dataclasses.replace(base, profiles=_TEST_PROFILES, agents=agents)
    monkeypatch.setattr(appmod, "load_config", lambda *a, **k: patched)
    monkeypatch.setattr(appmod, "_tournament", None)

    with TestClient(appmod.app, raise_server_exceptions=True) as client:
        yield client, appmod


def test_contact_endpoint_disabled_before_the_reset(contact_client):
    client, _ = contact_client
    r = client.get("/api/contact")
    assert r.status_code == 200
    assert r.json() == {"enabled": False}


def test_contact_endpoint_surfaces_towns_marker_and_events(contact_client):
    client, appmod = contact_client
    assert client.post("/api/arena/contact",
                       json={"family_a": "gemini",
                             "family_b": "llama"}).status_code == 202
    r = client.get("/api/contact")
    assert r.status_code == 200
    out = r.json()
    assert out["enabled"] is True
    towns = {s["name"]: s for s in out["settlements"]}
    assert len(towns) == 2
    assert all(set(s) >= {"id", "name", "founded_tick", "member_count",
                          "families"} for s in out["settlements"])
    # The cast families aggregate per town (mock profiles degrade to their
    # profile names — never the Arena's "other" bucket).
    gem = next(s for s in out["settlements"] if s["families"])
    assert sum(s["member_count"] for s in out["settlements"]) == 5
    assert out["contact_made"] is None  # nobody has traveled yet
    assert out["ledger"] is None and out["crossings"] == []
    # A departure stamps the marker and surfaces on the travels list. The
    # departure legs are action-RESULT events (returned to the turn handler,
    # not parked in the spawn outbox) — persist them through the SAME repo
    # call the loop's turn pipeline uses, then read the surface.
    world = appmod._loop._world
    sid_a, sid_b = sorted(world.settlements)
    traveler = world.agents[sorted(world.settlements[sid_a]["members"])[0]]
    res = world.action_travel_to(traveler, sid_b)
    for leg in (res["_multi"] if "_multi" in res else [res]):
        appmod._repo.save_event(appmod._loop._run_id, leg, world.tick)
    out2 = client.get("/api/contact").json()
    assert out2["contact_made"]["agent_id"] == traveler.id
    assert out2["contact_made"]["to_settlement"] == sid_b
    assert out2["travels"][0]["kind"] == "travel_departed"
    assert out2["travels"][0]["actor_id"] == traveler.id

"""Wave K · Wave 2 — the GOD console BUILDERS endpoints (EM-221).

Proves the four god-console mutations end to end, REUSING the Wave-1 internals
(the agent reflex tools all funnel through the same _prop_id/_prop_offset/
_demolish_building/building.skin paths) so a god mutation is byte-identical to an
agent one in snapshots:

  - POST /api/god/place_prop {kind, place, count?} places `count` (≤8) god-owned
    props (owner_id None), stops short at params.props.max_population, emits one
    prop_placed (actor_type 'god', payload.method 'god') each, one broadcast;
  - POST /api/god/clear_props {place?} removes props at a place (or ALL), emits
    prop_removed (actor_type 'god') each;
  - POST /api/god/demolish {building_id} is an IMMEDIATE god override (any owner /
    landmark), reusing _demolish_building → status 'destroyed', emits
    building_demolished (by 'god');
  - POST /api/god/reskin {building_id, skin} sets/clears building.skin (override),
    emits building_reskinned;
  - validation rejections are 4xx (unknown place/building) and DO NOT emit;
  - a snapshot round-trip still holds after god mutations (EM-155 determinism: the
    god-placed props + demolished/reskinned buildings restore byte-identically).

Two halves, mirroring the menagerie/god-console suites: a tiny OFFLINE world unit
test for the world methods + snapshot round-trip, and a TestClient API half that
drives the real FastAPI routes against the bootstrapped world.

CRITICAL suite rule (mirrors the W8 / menagerie / zoo family): import
petridish.engine.world BEFORE the runtime modules so the world module binds first.
"""
from __future__ import annotations

import sys

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState, Building, Prop
from petridish.config.loader import WorldParams, BuildingParams, PropsParams


# ──────────────────────────────────────────────────────────────────────────────
# Offline helpers — a tiny world for the world-method + snapshot unit tests.
# ──────────────────────────────────────────────────────────────────────────────

def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]


def _world(*, max_props: int = 48) -> tuple[World, AgentState]:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        buildings=BuildingParams(enabled=True, build_step=20),
        props=PropsParams(max_population=max_props),
    )
    ada = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                     location="plaza", energy=100.0, credits=1000)
    world = World(params=params, places=_places(), agents=[ada])
    return world, ada


def _building(world: World, *, bid: str = "bld_x", owner: str = "agent_ada",
              kind: str = "tavern", place: str = "plaza") -> Building:
    b = Building(id=bid, name="The Spot", kind=kind, location=place,
                 owner_id=owner, status="operational", progress=100, health=100,
                 funds_required=40, funds_committed=40)
    world.buildings[b.id] = b
    return b


# ──────────────────────────────────────────────────────────────────────────────
# 1. world.god_place_prop — god-owned props, reuses placement internals.
# ──────────────────────────────────────────────────────────────────────────────

def test_god_place_prop_places_count_god_owned_props():
    world, _ = _world()
    events = world.god_place_prop("bench", "plaza", 3)

    assert len(events) == 3
    assert len(world.props) == 3
    for p in world.props.values():
        assert p.kind == "bench"
        assert p.place == "plaza"
        assert p.owner_id is None, "god props are unowned (a co-located agent can clear)"
    for e in events:
        assert e["kind"] == "prop_placed"
        assert e["actor_id"] == "god"
        assert e["payload"]["owner_id"] is None

    # Deterministic ring offset: first on the anchor, the rest spread (no stacking).
    offsets = sorted((p.dx, p.dz) for p in world.props.values())
    assert (0.0, 0.0) in offsets
    assert len(set(offsets)) == 3, "the ring offset must keep props from stacking"


def test_god_place_prop_stops_at_cap_and_reports_short_list():
    world, _ = _world(max_props=2)
    events = world.god_place_prop("lamp", "plaza", 5)
    assert len(events) == 2, "the registry cap stops the burst short"
    assert len(world.props) == 2


def test_god_place_prop_rejects_unknown_place_and_empty_kind():
    world, _ = _world()
    for bad in (("bench", "nowhere"), ("", "plaza")):
        try:
            world.god_place_prop(*bad, 1)
            assert False, f"expected ValueError for {bad!r}"
        except ValueError:
            pass
    assert world.props == {}, "a rejected god placement mutates nothing"


def test_god_place_prop_is_deterministic_for_a_fixed_world():
    """Same (place, kind, ordinal) → same seeded id + offset across two worlds."""
    wa, _ = _world()
    wb, _ = _world()
    wa.god_place_prop("tree", "market", 4)
    wb.god_place_prop("tree", "market", 4)
    ids_a = sorted(wa.props)
    ids_b = sorted(wb.props)
    assert ids_a == ids_b and len(ids_a) == 4
    off_a = sorted((p.dx, p.dz) for p in wa.props.values())
    off_b = sorted((p.dx, p.dz) for p in wb.props.values())
    assert off_a == off_b


# ──────────────────────────────────────────────────────────────────────────────
# 2. world.god_clear_props — remove at a place, or ALL (god override, no gate).
# ──────────────────────────────────────────────────────────────────────────────

def test_god_clear_props_at_place_only():
    world, _ = _world()
    world.god_place_prop("bench", "plaza", 2)
    world.god_place_prop("lamp", "market", 3)
    events = world.god_clear_props("plaza")

    assert len(events) == 2
    assert all(e["kind"] == "prop_removed" and e["actor_id"] == "god" for e in events)
    assert all(p.place == "market" for p in world.props.values()), "only plaza cleared"
    assert len(world.props) == 3


def test_god_clear_props_all_when_place_omitted():
    world, _ = _world()
    world.god_place_prop("bench", "plaza", 2)
    world.god_place_prop("lamp", "market", 3)
    events = world.god_clear_props(None)
    assert len(events) == 5
    assert world.props == {}


def test_god_clear_props_ignores_owner_god_override():
    """An agent-OWNED prop is removable by the god clear (no ownership gate)."""
    world, ada = _world()
    world.action_place_prop(ada, "fence", "plaza")  # agent-owned (owner_id=ada.id)
    assert any(p.owner_id == ada.id for p in world.props.values())
    world.god_clear_props("plaza")
    assert world.props == {}, "god clear overrides ownership"


def test_god_clear_props_rejects_unknown_place():
    world, _ = _world()
    try:
        world.god_clear_props("nowhere")
        assert False, "expected ValueError"
    except ValueError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# 3. world.god_demolish — immediate override, reuses _demolish_building.
# ──────────────────────────────────────────────────────────────────────────────

def test_god_demolish_is_immediate_override_for_any_owner():
    world, _ = _world()
    # A PUBLIC building (not owned by the requesting agent) — agents can't touch it
    # without governance, but god demolishes immediately.
    b = _building(world, owner="public")
    evt = world.god_demolish(b.id)
    assert b.status == "destroyed" and b.health == 0
    assert evt["kind"] == "building_demolished"
    assert evt["actor_id"] == "god"
    assert evt["payload"]["by"] == "god"
    assert evt["payload"]["building_id"] == b.id


def test_god_demolish_rejects_unknown_and_already_destroyed():
    world, _ = _world()
    try:
        world.god_demolish("bld_missing")
        assert False, "expected ValueError for unknown building"
    except ValueError as exc:
        assert "building_not_found" in str(exc)
    b = _building(world)
    b.status = "destroyed"
    try:
        world.god_demolish(b.id)
        assert False, "expected ValueError for already-destroyed"
    except ValueError as exc:
        assert "already destroyed" in str(exc)


# ──────────────────────────────────────────────────────────────────────────────
# 4. world.god_reskin — set/clear skin, override (no owner gate).
# ──────────────────────────────────────────────────────────────────────────────

def test_god_reskin_sets_and_clears_skin_for_any_building():
    world, _ = _world()
    b = _building(world, owner="public")  # not the agent's — god overrides
    evt = world.god_reskin(b.id, "rose")
    assert b.skin == "rose"
    assert evt["kind"] == "building_reskinned"
    assert evt["actor_id"] == "god"
    assert evt["payload"]["skin"] == "rose"
    # Empty skin clears it back to the default.
    cleared = world.god_reskin(b.id, "")
    assert b.skin is None
    assert cleared["payload"]["skin"] is None


def test_god_reskin_clamps_long_skin_and_rejects_unknown():
    world, _ = _world()
    b = _building(world)
    world.god_reskin(b.id, "x" * 100)
    assert b.skin is not None and len(b.skin) <= 24
    try:
        world.god_reskin("bld_missing", "sky")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "building_not_found" in str(exc)


# ──────────────────────────────────────────────────────────────────────────────
# 5. SNAPSHOT round-trip after god mutations (EM-155 determinism).
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_round_trip_holds_after_god_mutations():
    world, _ = _world()
    b1 = _building(world, bid="bld_keep", owner="public", kind="market")
    b2 = _building(world, bid="bld_gone", owner="public", kind="smithy")
    world.god_place_prop("bench", "plaza", 2)
    world.god_place_prop("lamp", "market", 1)
    world.god_reskin(b1.id, "sage")
    world.god_demolish(b2.id)

    snap = world.to_snapshot()
    # Props serialize into the snapshot exactly.
    snap_prop_ids = sorted(p["id"] for p in snap["props"])
    assert snap_prop_ids == sorted(world.props)
    assert all(p["owner_id"] is None for p in snap["props"]), "god props stay unowned"

    restored = World.from_snapshot(snap, params=world.params)

    # Props restore byte-identically (id, kind, place, dx, dz, owner_id).
    assert sorted(restored.props) == sorted(world.props)
    for pid, prop in world.props.items():
        rp = restored.props[pid]
        assert (rp.kind, rp.place, rp.dx, rp.dz, rp.owner_id) == \
               (prop.kind, prop.place, prop.dx, prop.dz, prop.owner_id)

    # The reskin + demolish survive the round-trip.
    assert restored.buildings["bld_keep"].skin == "sage"
    assert restored.buildings["bld_gone"].status == "destroyed"


# ──────────────────────────────────────────────────────────────────────────────
# 6. API — the four god endpoints over the real FastAPI routes (TestClient idiom),
#    happy-path + validation rejection + persisted god-ink events.
# ──────────────────────────────────────────────────────────────────────────────

def test_api_place_prop_happy_path_and_persists_god_events():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        before = len(appmod._world.props)
        resp = client.post("/api/god/place_prop",
                            json={"kind": "fountain", "place": "plaza", "count": 3})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["placed"] == 3
        assert body["cap_reached"] is False
        assert len(appmod._world.props) == before + 3
        # The placed props are god-owned (unowned).
        new_props = [p for p in appmod._world.props.values() if p.kind == "fountain"]
        assert len(new_props) == 3 and all(p.owner_id is None for p in new_props)

        rows = appmod._repo.get_events(appmod._loop._run_id, kinds=["prop_placed"])
        assert len(rows) >= 3
        for row in rows[-3:]:
            assert row["actor_type"] == "god"
            assert row["payload"]["method"] == "god"
            assert row["payload"]["owner_id"] is None


def test_api_place_prop_count_is_capped_and_default_is_one():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # count > 8 is rejected by the Pydantic bound (422).
        assert client.post("/api/god/place_prop",
                           json={"kind": "tree", "place": "plaza", "count": 9}
                           ).status_code == 422
        # No count → defaults to 1.
        before = len(appmod._world.props)
        resp = client.post("/api/god/place_prop",
                           json={"kind": "tree", "place": "market"})
        assert resp.status_code == 201, resp.text
        assert resp.json()["placed"] == 1
        assert len(appmod._world.props) == before + 1


def test_api_place_prop_unknown_place_400_and_no_emit():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        before = len(appmod._repo.get_events(appmod._loop._run_id, kinds=["prop_placed"]))
        resp = client.post("/api/god/place_prop",
                           json={"kind": "bench", "place": "atlantis", "count": 2})
        assert resp.status_code == 400, resp.text
        after = len(appmod._repo.get_events(appmod._loop._run_id, kinds=["prop_placed"]))
        assert after == before, "a rejected placement must not emit"


def test_api_clear_props_removes_and_can_clear_all():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        client.post("/api/god/place_prop",
                    json={"kind": "bin", "place": "plaza", "count": 2})
        client.post("/api/god/place_prop",
                    json={"kind": "bin", "place": "market", "count": 2})

        # Clear just plaza.
        resp = client.post("/api/god/clear_props", json={"place": "plaza"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["removed"] == 2
        assert all(p.place != "plaza" for p in appmod._world.props.values())

        # Clear ALL (no place).
        resp = client.post("/api/god/clear_props", json={})
        assert resp.status_code == 200, resp.text
        assert appmod._world.props == {}

        rows = appmod._repo.get_events(appmod._loop._run_id, kinds=["prop_removed"])
        assert rows, "clears must emit prop_removed"
        for row in rows:
            assert row["actor_type"] == "god"
            assert row["payload"]["method"] == "god"


def test_api_clear_props_unknown_place_400():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        assert client.post("/api/god/clear_props",
                           json={"place": "narnia"}).status_code == 400


def test_api_demolish_immediate_override_and_persists():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        b = _building(appmod._world, bid="bld_apidemo", owner="public",
                      kind="monument")
        resp = client.post("/api/god/demolish", json={"building_id": b.id})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok", "building_id": b.id}
        assert appmod._world.buildings[b.id].status == "destroyed"

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["building_demolished"])
        assert any(r["payload"]["building_id"] == b.id for r in rows)
        row = next(r for r in rows if r["payload"]["building_id"] == b.id)
        assert row["actor_type"] == "god"
        assert row["payload"]["by"] == "god"
        assert row["payload"]["method"] == "god"


def test_api_demolish_unknown_404_and_already_destroyed_409():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        assert client.post("/api/god/demolish",
                           json={"building_id": "bld_nope"}).status_code == 404
        b = _building(appmod._world, bid="bld_already", owner="public")
        b.status = "destroyed"
        assert client.post("/api/god/demolish",
                           json={"building_id": b.id}).status_code == 409


def test_api_reskin_sets_skin_and_persists():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        b = _building(appmod._world, bid="bld_apiskin", owner="public",
                      kind="library")
        resp = client.post("/api/god/reskin",
                           json={"building_id": b.id, "skin": "plum"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"status": "ok", "building_id": b.id, "skin": "plum"}
        assert appmod._world.buildings[b.id].skin == "plum"

        # Empty skin clears it.
        resp = client.post("/api/god/reskin",
                           json={"building_id": b.id, "skin": ""})
        assert resp.status_code == 200, resp.text
        assert resp.json()["skin"] is None
        assert appmod._world.buildings[b.id].skin is None

        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["building_reskinned"])
        assert any(r["payload"]["building_id"] == b.id for r in rows)
        for r in rows:
            assert r["actor_type"] == "god"
            assert r["payload"]["method"] == "god"


def test_api_reskin_unknown_building_404():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        assert client.post("/api/god/reskin",
                           json={"building_id": "bld_ghost", "skin": "sky"}
                           ).status_code == 404


def test_api_snapshot_round_trips_after_god_endpoints():
    """End-to-end: drive the real god endpoints, then a to_snapshot/from_snapshot
    of the live world preserves the god mutations (props + skin + demolish)."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        b = _building(appmod._world, bid="bld_rt", owner="public", kind="temple")
        client.post("/api/god/place_prop",
                    json={"kind": "hydrant", "place": "plaza", "count": 2})
        client.post("/api/god/reskin", json={"building_id": b.id, "skin": "amber"})

        snap = appmod._world.to_snapshot()
        restored = World.from_snapshot(snap, params=appmod._world.params)

        assert sorted(restored.props) == sorted(appmod._world.props)
        assert restored.buildings["bld_rt"].skin == "amber"
        # The restored props are byte-identical god-owned props.
        for pid, prop in appmod._world.props.items():
            rp = restored.props[pid]
            assert isinstance(rp, Prop)
            assert (rp.kind, rp.place, rp.owner_id) == \
                   (prop.kind, prop.place, prop.owner_id)

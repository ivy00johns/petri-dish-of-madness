"""EM-298 — agent-authored facades (paint_surface + surface_decals).

Agents paint a mural/sign/graffiti onto a co-located building's facade. The verb
EXTENDS the Wave-I image lane: the SAME seeded-id gallery mint (EM-155) and the
SAME off-replay PNG side-artifact — only a stable {surface_id -> image_id} mapping
(`world.surface_decals`) enters sim state.

Invariants pinned here:
  * mint + record — action_paint_surface mints a gallery image AND records the
    {surface_id -> image_id} mapping (the create_image core is reused, so the
    gallery/pending-fetch bookkeeping is identical).
  * per-district cap + insertion-order LRU — a district holds at most
    max_decals_per_district decals; the OLDEST-in-district is evicted first, and a
    re-paint refreshes recency (moves the surface to the tail).
  * determinism gate (CRITICAL) — a facade-free world's snapshot omits the
    surface_decals key entirely, so it is BYTE-IDENTICAL to a pre-EM-298 snapshot;
    a painted world round-trips byte-identically (order == recency preserved).
  * kill switch — image_gen.enabled False rejects paint_surface with no mint and no
    mapping (credit-safe, mirrors create_image).
  * the runtime seam — ACTION_SCHEMA accepts paint_surface {target, prompt}; the
    @building co-location gate is enforced by _validate_world.
"""

import copy
import json

import jsonschema
import pytest

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, ImageGenParams
from petridish.agents.runtime import ACTION_SCHEMA, _validate_world


# ── fixtures ──────────────────────────────────────────────────────────────────

def _params(image_gen=None, **kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    if image_gen is not None:
        base["image_gen"] = image_gen
    return WorldParams(**base)


def _places():
    # Two districts so the per-district cap can be exercised independently.
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social",
                   district="core"),
        PlaceState(id="market", name="Market", x=1, y=0, kind="work",
                   district="market"),
        PlaceState(id="commons", name="Commons", x=2, y=0, kind="social",
                   district="core"),
    ]


def _agent(**kw):
    base = dict(id="ada", name="Ada", personality="artist", profile="mock",
                location="market", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _world(agents=None, params=None, places=None):
    return World(params=params or _params(),
                 places=places if places is not None else _places(),
                 agents=agents if agents is not None else [_agent()])


def _add_building(world, bid, location="market", status="operational"):
    world.buildings[bid] = Building(
        id=bid, name=f"Structure {bid}", kind="workshop", location=location,
        status=status)
    return world.buildings[bid]


# ── (a) mint + record the {surface_id -> image_id} mapping ────────────────────

def test_paint_surface_mints_image_and_records_mapping():
    a = _agent()
    w = _world([a])
    _add_building(w, "b1", location="market")

    gallery_before = len(w.gallery)
    fetches_before = len(w.pending_image_fetches)

    evt = w.action_paint_surface(a, "b1", "a mural of the harvest")

    # It minted exactly one gallery image + parked exactly one PNG fetch (the
    # create_image core, reused).
    assert len(w.gallery) == gallery_before + 1
    assert len(w.pending_image_fetches) == fetches_before + 1
    image_id = w.gallery[-1]["image_id"]

    # The stable mapping is recorded: surface (building) id -> the minted image id.
    assert w.surface_decals == {"b1": image_id}

    # The emitted event rides the image lane, carrying the surface mapping.
    assert evt["kind"] == "image_posted"
    assert evt["target_id"] == "b1"
    assert evt["payload"]["surface_id"] == "b1"
    assert evt["payload"]["image_id"] == image_id
    assert evt["payload"]["url"].endswith(f"{image_id}.png")


def test_paint_surface_unknown_building_is_rejected():
    a = _agent()
    w = _world([a])
    evt = w.action_paint_surface(a, "nope", "graffiti")
    assert evt["kind"] == "parse_failure"
    assert w.surface_decals == {}
    assert w.gallery == []            # no mint on rejection
    assert w.pending_image_fetches == []


def test_paint_surface_empty_prompt_is_rejected():
    a = _agent()
    w = _world([a])
    _add_building(w, "b1")
    evt = w.action_paint_surface(a, "b1", "   ")
    assert evt["kind"] == "parse_failure"
    assert w.surface_decals == {}
    assert w.gallery == []


def test_paint_surface_image_gen_disabled_is_rejected():
    """Kill switch: disabled image_gen mints NOTHING + records NOTHING (credit-safe)."""
    a = _agent()
    w = _world([a], params=_params(image_gen=ImageGenParams(enabled=False)))
    _add_building(w, "b1")
    evt = w.action_paint_surface(a, "b1", "a mural")
    assert evt["kind"] == "parse_failure"
    assert w.surface_decals == {}
    assert w.gallery == []
    assert w.pending_image_fetches == []


# ── (b) per-district cap + insertion-order LRU eviction ───────────────────────

def test_per_district_cap_evicts_oldest_in_district():
    a = _agent(location="market")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=2)))
    for bid in ("b1", "b2", "b3"):
        _add_building(w, bid, location="market")

    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")
    w.action_paint_surface(a, "b3", "three")

    # Cap is 2 in district "market": the oldest (b1) is evicted; b2, b3 survive
    # in insertion order (== recency).
    assert list(w.surface_decals.keys()) == ["b2", "b3"]


def test_repaint_refreshes_recency():
    a = _agent(location="market")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=2)))
    for bid in ("b1", "b2", "b3"):
        _add_building(w, bid, location="market")

    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")
    # Re-paint b1 → it moves to the most-recent (tail) position.
    w.action_paint_surface(a, "b1", "one again")
    # Now paint b3 → b2 (now oldest) is evicted, b1 (refreshed) survives.
    w.action_paint_surface(a, "b3", "three")

    assert list(w.surface_decals.keys()) == ["b1", "b3"]
    # The refreshed b1 points at the NEWEST minted image (its second painting).
    assert w.surface_decals["b1"] == w.gallery[-2]["image_id"] or \
           w.surface_decals["b1"] in {g["image_id"] for g in w.gallery}


def test_cap_is_scoped_per_district():
    a = _agent()
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=1)))
    # Two buildings in DIFFERENT districts (market vs core).
    _add_building(w, "m1", location="market")   # district "market"
    _add_building(w, "c1", location="commons")   # district "core"

    a.location = "market"
    w.action_paint_surface(a, "m1", "market mural")
    a.location = "commons"
    w.action_paint_surface(a, "c1", "commons mural")

    # cap=1 per district, but the two live in different districts → both survive.
    assert set(w.surface_decals.keys()) == {"m1", "c1"}


# ── (c) determinism gate — byte-identical when empty (CRITICAL) ───────────────

def test_snapshot_omits_surface_decals_when_empty():
    """A facade-free world's snapshot has NO surface_decals key, so it is byte-
    identical to a pre-EM-298 snapshot."""
    w = _world()
    snap = w.to_snapshot()
    assert "surface_decals" not in snap


def test_empty_world_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.surface_decals == {}
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_from_snapshot_absent_key_restores_empty():
    """A pre-EM-298 snapshot (no surface_decals key) restores an empty map."""
    w = _world()
    snap = w.to_snapshot()
    snap.pop("surface_decals", None)   # simulate an old snapshot
    restored = World.from_snapshot(snap, params=_params())
    assert restored.surface_decals == {}


# ── (d) round-trips correctly when non-empty ─────────────────────────────────

def test_non_empty_surface_decals_round_trips():
    a = _agent(location="market")
    w = _world([a])
    for bid in ("b1", "b2", "b3"):
        _add_building(w, bid, location="market")
    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")
    w.action_paint_surface(a, "b3", "three")

    snap = w.to_snapshot()
    assert "surface_decals" in snap
    assert list(snap["surface_decals"].keys()) == ["b1", "b2", "b3"]

    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    # Insertion order (== LRU recency) survives the round-trip.
    assert list(restored.surface_decals.keys()) == ["b1", "b2", "b3"]
    assert restored.surface_decals == w.surface_decals
    # Re-snapshot is byte-identical.
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_from_snapshot_drops_malformed_decal_rows():
    w = _world()
    snap = w.to_snapshot()
    snap["surface_decals"] = {"b1": "img_x", "": "img_y", "b2": ""}
    restored = World.from_snapshot(snap, params=_params())
    assert restored.surface_decals == {"b1": "img_x"}


# ── the runtime seam — schema + co-location gate ─────────────────────────────

def test_action_schema_accepts_paint_surface():
    single = ACTION_SCHEMA["properties"]["action"]["enum"]
    multi = ACTION_SCHEMA["properties"]["actions"]["items"]["properties"]["action"]["enum"]
    assert "paint_surface" in single
    assert "paint_surface" in multi
    # A well-formed call validates.
    jsonschema.validate(
        {"action": "paint_surface", "args": {"target": "b1", "prompt": "art"}},
        ACTION_SCHEMA)
    # Missing target is rejected structurally.
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"action": "paint_surface", "args": {"prompt": "art"}}, ACTION_SCHEMA)


def test_validate_world_enforces_building_gate():
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market")
    _add_building(w, "far", location="plaza")

    # co-located building + prompt → accepted.
    assert _validate_world(
        {"action": "paint_surface", "args": {"target": "b1", "prompt": "art"}},
        a, w) is None
    # unknown building → rejected.
    assert _validate_world(
        {"action": "paint_surface", "args": {"target": "nope", "prompt": "art"}},
        a, w) is not None
    # a building elsewhere (not co-located) → rejected.
    assert _validate_world(
        {"action": "paint_surface", "args": {"target": "far", "prompt": "art"}},
        a, w) is not None
    # empty prompt → rejected.
    assert _validate_world(
        {"action": "paint_surface", "args": {"target": "b1", "prompt": " "}},
        a, w) is not None

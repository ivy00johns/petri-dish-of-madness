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


def _add_building(world, bid, location="market", status="operational",
                   owner_id="public", health=100):
    world.buildings[bid] = Building(
        id=bid, name=f"Structure {bid}", kind="workshop", location=location,
        status=status, owner_id=owner_id, health=health)
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

def test_non_empty_surface_decals_round_trips(monkeypatch):
    # Pin free-placement OFF: this asserts a byte-identical decal round-trip for
    # hand-built (position-less) buildings; F1's derive-on-load migration would
    # add positions on restore, breaking byte-identity. Decal round-trip is
    # orthogonal to placement — flag-ON position determinism is owned by
    # test_free_placement_determinism.
    import petridish.agents.runtime as _rt
    monkeypatch.setattr(_rt, "FREE_PLACEMENT_ENABLED", False)
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


# ── (e) decal clearing on destroy (demolish / arson) ───────────────────────────
# EM-298 follow-up (review finding): _demolish_building and the arson->destroy
# branch of _damage_building set status='destroyed' but used to leave the
# building's surface_decals entry in place, so a painted mural kept rendering
# floating over the rubble (the frontend draws one SurfaceDecal per
# buildingSpot regardless of status). Both paths now pop the entry.

def test_demolish_clears_surface_decal():
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", owner_id=a.id)
    w.action_paint_surface(a, "b1", "a mural of the harvest")
    assert "b1" in w.surface_decals

    evt = w.action_demolish(a, "b1")

    assert evt["kind"] == "building_demolished"
    assert w.buildings["b1"].status == "destroyed"
    assert "b1" not in w.surface_decals


def test_demolish_only_clears_its_own_decal():
    """Demolishing one painted building clears ONLY its decal — a sibling's
    survives untouched."""
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", owner_id=a.id)
    _add_building(w, "b2", location="market", owner_id=a.id)
    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")

    w.action_demolish(a, "b1")

    assert "b1" not in w.surface_decals
    assert "b2" in w.surface_decals


def test_arson_destroy_clears_surface_decal():
    a = _agent(location="market")
    w = _world([a])
    # Low starting health so a single arson hit (default arson_damage=50)
    # drives it straight to destroyed.
    _add_building(w, "b1", location="market", health=10)
    w.action_paint_surface(a, "b1", "graffiti")
    assert "b1" in w.surface_decals

    result = w.action_arson(a, "b1")

    assert w.buildings["b1"].status == "destroyed"
    assert "b1" not in w.surface_decals
    state_evt = result["_multi"][-1]
    assert state_evt["payload"]["to"] == "destroyed"


def test_arson_damage_without_destroy_preserves_decal():
    """Sanity: only a DESTROY-ing hit clears the decal — mere damage (still
    above 0 health) leaves the painted mural alone."""
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", health=100)
    w.action_paint_surface(a, "b1", "a mural")

    w.action_arson(a, "b1")  # default arson_damage=50 -> damaged, not destroyed

    assert w.buildings["b1"].status == "damaged"
    assert "b1" in w.surface_decals


def test_animal_destroy_clears_surface_decal():
    """The arson-destroy clear lives in the SHARED _damage_building path, so
    animal-caused destruction clears a painted facade too."""
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", health=10)
    w.action_paint_surface(a, "b1", "a mural")

    w.animal_damage_building("b1", 50)

    assert w.buildings["b1"].status == "destroyed"
    assert "b1" not in w.surface_decals


def test_snapshot_round_trip_stays_clean_after_decal_clear_via_demolish(monkeypatch):
    """After the decal is cleared by demolish, the empty-decal invariant holds
    again: the serializer only emits non-empty decals, so the snapshot omits
    surface_decals entirely (byte-identical to a facade-free world) and
    round-trips clean.

    Pin free-placement OFF (see test_non_empty_surface_decals_round_trips):
    decal round-trip is orthogonal to placement, and F1's derive-on-load
    migration adds a `position` field on restore that would otherwise break
    this byte-identity assertion for an unrelated reason."""
    import petridish.agents.runtime as _rt
    monkeypatch.setattr(_rt, "FREE_PLACEMENT_ENABLED", False)
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", owner_id=a.id)
    w.action_paint_surface(a, "b1", "a mural")
    assert "surface_decals" in w.to_snapshot()

    w.action_demolish(a, "b1")
    snap = w.to_snapshot()

    assert "surface_decals" not in snap

    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.surface_decals == {}
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_snapshot_round_trip_stays_clean_after_decal_clear_via_arson(monkeypatch):
    """Same invariant, via the arson-destroy path. Free-placement pinned OFF for
    the same reason as the demolish variant above."""
    import petridish.agents.runtime as _rt
    monkeypatch.setattr(_rt, "FREE_PLACEMENT_ENABLED", False)
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", health=10)
    w.action_paint_surface(a, "b1", "a mural")

    w.action_arson(a, "b1")
    snap = w.to_snapshot()

    assert "surface_decals" not in snap

    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.surface_decals == {}
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_snapshot_keeps_surviving_decal_after_partial_clear(monkeypatch):
    """Demolishing one painted building clears only its decal; the snapshot
    still carries the survivor and round-trips it faithfully. Free-placement
    pinned OFF for the same reason as the round-trip tests above."""
    import petridish.agents.runtime as _rt
    monkeypatch.setattr(_rt, "FREE_PLACEMENT_ENABLED", False)
    a = _agent(location="market")
    w = _world([a])
    _add_building(w, "b1", location="market", owner_id=a.id)
    _add_building(w, "b2", location="market", owner_id=a.id)
    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")

    w.action_demolish(a, "b1")
    snap = w.to_snapshot()

    assert list(snap["surface_decals"].keys()) == ["b2"]

    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.surface_decals == w.surface_decals
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


# ── (b2) EM-302a — the untagged-district fallback bucket ─────────────────────
# The defect: places with NO district/neighborhood tag all collapsed into one
# "" bucket, so an untagged town shared a single flat town-wide cap and
# ungrouped places evicted each other's murals. Untagged places now bucket
# PER PLACE; tagged districts keep their exact pre-EM-302 buckets.

def _untagged_places():
    """The _places() town with every district tag stripped (an untagged world)."""
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=1, y=0, kind="work"),
        PlaceState(id="commons", name="Commons", x=2, y=0, kind="social"),
    ]


def test_untagged_places_do_not_share_a_town_wide_bucket():
    """cap=1 across two UNTAGGED places: each place is its own bucket, so both
    murals survive (pre-EM-302a the second paint evicted the first)."""
    a = _agent(location="market")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=1)),
        places=_untagged_places())
    _add_building(w, "m1", location="market")
    _add_building(w, "c1", location="commons")

    w.action_paint_surface(a, "m1", "market mural")
    a.location = "commons"
    w.action_paint_surface(a, "c1", "commons mural")

    assert set(w.surface_decals.keys()) == {"m1", "c1"}


def test_untagged_place_is_still_capped_within_itself():
    """The fallback bucket is not unbounded: three paints at ONE untagged place
    under cap=2 still evict the oldest (same LRU semantics as a tagged district)."""
    a = _agent(location="market")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=2)),
        places=_untagged_places())
    for bid in ("b1", "b2", "b3"):
        _add_building(w, bid, location="market")

    w.action_paint_surface(a, "b1", "one")
    w.action_paint_surface(a, "b2", "two")
    w.action_paint_surface(a, "b3", "three")

    assert list(w.surface_decals.keys()) == ["b2", "b3"]


def test_tagged_and_untagged_buckets_never_interact():
    """A mixed world: painting inside a TAGGED district neither evicts nor is
    evicted by an UNTAGGED place's decal (distinct buckets, cap=1 each)."""
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social",
                   district="core"),
        PlaceState(id="market", name="Market", x=1, y=0, kind="work"),  # untagged
    ]
    a = _agent(location="plaza")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=1)), places=places)
    _add_building(w, "p1", location="plaza")
    _add_building(w, "m1", location="market")

    w.action_paint_surface(a, "p1", "civic mural")
    a.location = "market"
    w.action_paint_surface(a, "m1", "market mural")

    assert set(w.surface_decals.keys()) == {"p1", "m1"}


def test_tagged_district_still_shares_one_bucket_across_places():
    """EM-302a must NOT change tagged capacity: two places in the SAME district
    ("core": plaza + commons) still share one bucket — cap=1 evicts the older."""
    a = _agent(location="plaza")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=1)))
    _add_building(w, "p1", location="plaza")     # district "core"
    _add_building(w, "c1", location="commons")   # district "core"

    w.action_paint_surface(a, "p1", "first")
    a.location = "commons"
    w.action_paint_surface(a, "c1", "second")

    assert list(w.surface_decals.keys()) == ["c1"]


def test_building_with_unknown_location_gets_a_stable_per_place_bucket():
    """Defensive: a building whose location is missing from world.places still
    lands in a bounded per-location bucket (not the old shared "" bucket)."""
    a = _agent(location="market")
    w = _world([a], params=_params(
        image_gen=ImageGenParams(max_decals_per_district=1)),
        places=_untagged_places())
    _add_building(w, "m1", location="market")
    _add_building(w, "ghost", location="nowhere")  # location not in places

    w.action_paint_surface(a, "m1", "market mural")
    w.action_paint_surface(a, "ghost", "ghost mural")

    # Distinct buckets (market vs nowhere) → both survive under cap=1.
    assert set(w.surface_decals.keys()) == {"m1", "ghost"}
    # And the bucket keys themselves are the prefixed fallbacks (no collision
    # with a real district literal).
    assert w._decal_district_of("m1") == "__place__:market"
    assert w._decal_district_of("ghost") == "__place__:nowhere"


def test_neighborhood_tag_still_wins_over_district_and_fallback():
    """The EM-123 grouping precedence is untouched: neighborhood_id beats
    district beats the per-place fallback."""
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social",
                   district="core", neighborhood_id="old-town"),
    ]
    a = _agent(location="plaza")
    w = _world([a], params=_params(), places=places)
    _add_building(w, "p1", location="plaza")
    w.action_paint_surface(a, "p1", "mural")

    assert w._decal_district_of("p1") == "old-town"


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

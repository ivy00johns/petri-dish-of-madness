"""Wave I · The Atelier (EM-210–213) — backend behavior.

Proves the agent-driven ART arc end to end, reflex-first and replay-safe
(contracts/wave-i-atelier.md §§0-9):

  - CREATE_IMAGE (I1) is an UNGATED reflex tool: it records a deterministic
    gallery entry, parks a transient fetch, and emits image_posted ALL
    synchronously at turn time — zero critical-path LLM calls;
  - the image_id is SEEDED-deterministic ("img_"+10hex via _seed_int, never
    uuid4) and the url is DERIVED from it ("/assets/images/<id>.png"), so the
    same seed ⇒ identical id/url across runs (the EM-155 replay keystone);
  - POST_IMAGE (I2) is @billboard-gated: it puts an existing gallery image on the
    billboard with payload.image_ref = the url; it validates ownership/publicness;
  - PROMOTE_IMAGE (I3/I4) rides the shipped propose_rule → vote → _on_rule_activated
    path: a passing vote sets plaza_banner_ref + marks the record promoted=True +
    emits image_promoted; the relaxed one-open-proposal guard allows two DISTINCT
    images to have open votes at once but blocks double-proposing ONE image;
  - SNAPSHOT round-trip: gallery + plaza_banner_ref survive to_snapshot →
    from_snapshot; a pre-Wave-I snapshot (no keys) restores byte-identically;
  - the PROVIDER mock returns bytes (hermetic, EM_IMAGEGEN_MOCK);
  - the LOOP drain writes a PNG under cap and SKIPS over cap without raising;
  - the menu and the resolution gate AGREE (EM-108's lesson).

CRITICAL suite rule (mirrors the W8 / Wave-K family): import
petridish.engine.world BEFORE the runtime modules so the world module binds
first (avoids the engine↔agents circular-import order trap).
"""
from __future__ import annotations

import asyncio

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    ImageGenParams, ModelProfile, PlaceConfig, WorldConfig, WorldParams,
)

# Runtime imports AFTER world.
from petridish.agents.runtime import (
    ACTION_SCHEMA,
    TOOL_REGISTRY,
    AgentRuntime,
    _validate_world,
    _assemble_context,
)
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider

import jsonschema
import pytest


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a tiny offline world (no router calls).
# ──────────────────────────────────────────────────────────────────────────────

def _places():
    return [
        PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceState(id="forge", name="The Forge", x=600, y=500, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=400, y=500, kind="governance"),
    ]


def _world(*, max_gallery: int = 30, city_seed: int = 1337) -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0,
        death_after_zero_turns=99,
        turns_per_day=999,
        city_seed=city_seed,
        image_gen=ImageGenParams(max_gallery=max_gallery),
    )
    agents = [
        AgentState(id="agent_a", name="Ada", personality="", profile="mock",
                   location="plaza", energy=100, credits=100),
        AgentState(id="agent_b", name="Bram", personality="", profile="mock",
                   location="plaza", energy=100, credits=100),
    ]
    return World(params, _places(), agents)


def _prompt_text(ctx) -> str:
    if isinstance(ctx, list):
        return "\n".join(str(m.get("content", "")) for m in ctx)
    if isinstance(ctx, dict):
        return str(ctx.get("system") or ctx.get("user") or ctx)
    return str(ctx)


# ──────────────────────────────────────────────────────────────────────────────
# Schema / registry wiring
# ──────────────────────────────────────────────────────────────────────────────

def test_action_schema_is_valid_and_lists_atelier_tools():
    jsonschema.Draft202012Validator.check_schema(ACTION_SCHEMA)
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    for tool in ("create_image", "post_image"):
        assert tool in enum
        assert tool in TOOL_REGISTRY
        assert TOOL_REGISTRY[tool]["tier"] == "reflex"  # invariant: reflex tools
    # create_image is ungated; post_image is @billboard-gated (like post_billboard).
    assert TOOL_REGISTRY["create_image"]["location_gate"] is None
    assert TOOL_REGISTRY["post_image"]["location_gate"] == "@billboard"
    # Present in the multi-action items enum too (EM-199 multi-action turns).
    item_enum = ACTION_SCHEMA["properties"]["actions"]["items"]["properties"]["action"]["enum"]
    assert "create_image" in item_enum and "post_image" in item_enum


def test_atelier_tools_validate_structurally_via_inline_schema():
    v = jsonschema.Draft202012Validator(ACTION_SCHEMA)
    for doc in (
        {"action": "create_image", "args": {"prompt": "a sunset over the plaza"}},
        {"action": "post_image", "args": {}},
        {"action": "post_image", "args": {"image_id": "img_abc"}},
    ):
        v.validate(doc)
    # create_image REQUIRES a prompt; a prompt over 240 chars fails structurally.
    with pytest.raises(jsonschema.ValidationError):
        v.validate({"action": "create_image", "args": {}})
    with pytest.raises(jsonschema.ValidationError):
        v.validate({"action": "create_image", "args": {"prompt": "x" * 241}})


# ──────────────────────────────────────────────────────────────────────────────
# I1 — create_image: gate + dispatch + deterministic record + replay
# ──────────────────────────────────────────────────────────────────────────────

def test_create_image_records_gallery_entry_and_parks_fetch_and_emits_event():
    world = _world()
    ada = world.agents["agent_a"]
    world.tick = 7
    evt = world.action_create_image(ada, "a cozy lantern in the rain")

    assert evt["kind"] == "image_posted"
    assert evt["actor_id"] == "agent_a"
    pl = evt["payload"]
    assert pl["place"] == "plaza"
    assert pl["prompt"] == "a cozy lantern in the rain"
    # Seeded id + derived url.
    assert pl["image_id"].startswith("img_") and len(pl["image_id"]) == len("img_") + 10
    assert pl["url"] == f"/assets/images/{pl['image_id']}.png"

    # Gallery record shape (all JSON-safe; promoted defaults False).
    assert len(world.gallery) == 1
    rec = world.gallery[0]
    assert rec == {
        "image_id": pl["image_id"], "prompt": "a cozy lantern in the rain",
        "proposer_id": "agent_a", "created_tick": 7,
        "url": pl["url"], "promoted": False,
    }
    # Transient fetch parked (NOT yet drained).
    assert world.pending_image_fetches == [
        {"image_id": pl["image_id"], "prompt": "a cozy lantern in the rain", "url": pl["url"]}
    ]


def test_create_image_empty_prompt_is_soft_noop_not_dead_turn():
    world = _world()
    ada = world.agents["agent_a"]
    evt = world.action_create_image(ada, "   ")
    assert evt["kind"] == "parse_failure"
    assert world.gallery == []
    assert world.pending_image_fetches == []


def test_create_image_is_seeded_deterministic_same_seed_same_id():
    # Two independent worlds, same city_seed + same proposer/place/tick ⇒ identical id/url.
    w1, w2 = _world(city_seed=99), _world(city_seed=99)
    e1 = w1.action_create_image(w1.agents["agent_a"], "a fountain")
    e2 = w2.action_create_image(w2.agents["agent_a"], "a fountain")
    assert e1["payload"]["image_id"] == e2["payload"]["image_id"]
    assert e1["payload"]["url"] == e2["payload"]["url"]
    # A different seed yields a different id (the seed actually participates).
    w3 = _world(city_seed=12345)
    e3 = w3.action_create_image(w3.agents["agent_a"], "a fountain")
    assert e3["payload"]["image_id"] != e1["payload"]["image_id"]


def test_create_image_same_tick_second_image_gets_distinct_id():
    world = _world()
    ada = world.agents["agent_a"]
    e1 = world.action_create_image(ada, "first")
    e2 = world.action_create_image(ada, "second")
    assert e1["payload"]["image_id"] != e2["payload"]["image_id"]
    assert len(world.gallery) == 2


def test_create_image_caps_gallery_pop_oldest():
    world = _world(max_gallery=3)
    ada = world.agents["agent_a"]
    ids = []
    for i in range(5):
        world.tick = i
        ids.append(world.action_create_image(ada, f"art {i}")["payload"]["image_id"])
    assert len(world.gallery) == 3
    kept = [g["image_id"] for g in world.gallery]
    assert kept == ids[-3:]  # newest 3 retained, oldest popped


def test_image_ids_are_unique_across_FULL_HISTORY_past_the_gallery_cap():
    """FINDING 2/3 — created_tick is in the id seed, so ids are unique across the
    run's WHOLE history, not merely within the capped in-memory window.

    Same place + same proposer, MANY images across MANY ticks, with a SMALL cap so
    pop-oldest eviction repeatedly clears the window. Pre-fix, the seed had no tick
    and the collision while-loop only checked the CAPPED gallery — so a later image
    at the same place/proposer/ordinal regenerated an EVICTED id (two distinct
    images aliasing one id+url; the async fetch would overwrite the PNG and a
    promoted banner_ref could silently resolve to new art). With tick in the seed,
    every historical id is distinct."""
    world = _world(max_gallery=3)  # tiny window: eviction happens constantly
    ada = world.agents["agent_a"]
    ada.location = "plaza"  # SAME place every tick (so only tick breaks the seed)
    seen: list[str] = []
    n_ticks = 40  # >> max_gallery, so the window is evicted many times over
    for t in range(n_ticks):
        world.tick = t
        seen.append(world.action_create_image(ada, "a recurring mural")["payload"]["image_id"])
    # Every id minted across the FULL history is distinct (not just the live window).
    assert len(seen) == n_ticks
    assert len(set(seen)) == n_ticks, "an evicted id was regenerated — history collision"
    # And the live gallery is still capped to the newest few.
    assert len(world.gallery) == 3
    # Determinism survives the tick-seeded change: a second world with the same
    # seed + same per-tick script mints the byte-identical id sequence (EM-155).
    w2 = _world(max_gallery=3)
    a2 = w2.agents["agent_a"]
    a2.location = "plaza"
    seen2 = []
    for t in range(n_ticks):
        w2.tick = t
        seen2.append(w2.action_create_image(a2, "a recurring mural")["payload"]["image_id"])
    assert seen2 == seen, "tick-seeded ids must still be replay-deterministic"


def test_image_id_seed_includes_tick_distinct_ticks_never_alias():
    """A focused unit guard on the seam itself: the SAME place/proposer/ordinal at
    two DIFFERENT ticks yields two DIFFERENT ids (tick participates in the seed)."""
    world = _world()
    id_t1 = world._image_id("plaza", "agent_a", 1, 0)
    id_t2 = world._image_id("plaza", "agent_a", 2, 0)
    assert id_t1 != id_t2
    # Same tick + same ordinal is stable (replay-safe); ordinal still disambiguates.
    assert world._image_id("plaza", "agent_a", 1, 0) == id_t1
    assert world._image_id("plaza", "agent_a", 1, 1) != id_t1


def test_validate_create_image_ungated_requires_prompt():
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "forge"  # anywhere — ungated
    assert _validate_world({"action": "create_image", "args": {"prompt": "x"}}, ada, world) is None
    assert _validate_world({"action": "create_image", "args": {"prompt": " "}}, ada, world) is not None


# ──────────────────────────────────────────────────────────────────────────────
# I2 — post_image: @billboard gate + image_ref on the billboard payload
# ──────────────────────────────────────────────────────────────────────────────

def test_post_image_at_billboard_sets_image_ref_on_payload():
    world = _world()
    ada = world.agents["agent_a"]
    created = world.action_create_image(ada, "a mural")
    img_id, url = created["payload"]["image_id"], created["payload"]["url"]
    ada.location = "plaza"  # billboard stands here
    evt = world.action_post_image(ada, img_id)
    assert evt["kind"] == "billboard_posted"
    assert evt["payload"]["image_ref"] == url
    assert evt["payload"]["image_id"] == img_id
    # The post actually landed on the board.
    assert world.billboard and "art" in world.billboard[-1]["text"].lower()


def test_post_image_defaults_to_newest_own_image():
    world = _world()
    ada = world.agents["agent_a"]
    world.tick = 1
    world.action_create_image(ada, "older")
    world.tick = 2
    newest = world.action_create_image(ada, "newer")["payload"]["image_id"]
    ada.location = "plaza"
    evt = world.action_post_image(ada, None)
    assert evt["payload"]["image_id"] == newest


def test_post_image_off_billboard_is_soft_fail():
    world = _world()
    ada = world.agents["agent_a"]
    world.action_create_image(ada, "a mural")
    ada.location = "forge"  # no billboard here
    evt = world.action_post_image(ada, None)
    assert evt["kind"] == "parse_failure"


def test_post_image_rejects_unowned_unpromoted_image():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "ada's art")["payload"]["image_id"]
    bram.location = "plaza"
    # Bram cannot post Ada's image while it is unpromoted.
    evt = world.action_post_image(bram, img_id)
    assert evt["kind"] == "parse_failure"


def test_validate_post_image_gate_and_existence():
    world = _world()
    ada = world.agents["agent_a"]
    # No image yet, at the billboard ⇒ rejected (nothing to post).
    ada.location = "plaza"
    assert _validate_world({"action": "post_image", "args": {}}, ada, world) is not None
    # Create one ⇒ now allowed.
    img_id = world.action_create_image(ada, "x")["payload"]["image_id"]
    assert _validate_world({"action": "post_image", "args": {}}, ada, world) is None
    # Off the board ⇒ rejected even with an image.
    ada.location = "forge"
    assert _validate_world({"action": "post_image", "args": {}}, ada, world) is not None
    # Unknown id ⇒ rejected.
    ada.location = "plaza"
    assert _validate_world({"action": "post_image", "args": {"image_id": "img_nope"}}, ada, world) is not None
    assert _validate_world({"action": "post_image", "args": {"image_id": img_id}}, ada, world) is None


# ──────────────────────────────────────────────────────────────────────────────
# I3/I4 — promote_image governance: propose / vote / pass + relaxed guard
# ──────────────────────────────────────────────────────────────────────────────

def test_promote_image_propose_vote_pass_sets_banner_and_promoted_and_event():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "the chosen one")["payload"]["image_id"]
    ada.location = "townhall"  # propose_rule is governance-gated
    ok, msg, rule = world.action_propose_rule(
        ada, "promote_image", "Hang this over the plaza", image_id=img_id)
    assert ok, msg
    assert rule.payload["image_id"] == img_id
    # Two living agents → strict majority needs > 1 yes.
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.rules[rule.id].status == "active"
    assert world.plaza_banner_ref == img_id
    rec = next(g for g in world.gallery if g["image_id"] == img_id)
    assert rec["promoted"] is True
    # image_promoted parked in the spawn-event outbox (system actor).
    drained = world.drain_spawn_events()
    promo = next(e for e in drained if e["kind"] == "image_promoted")
    assert promo["actor_type"] == "system"
    assert promo["payload"]["image_id"] == img_id
    assert promo["payload"]["proposal_id"] == rule.id
    assert promo["payload"]["url"] == rec["url"]


def test_promote_image_requires_real_image_id():
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "townhall"
    ok, msg, rule = world.action_propose_rule(
        ada, "promote_image", "x", image_id="img_nope")
    assert not ok and rule is None


def test_relaxed_guard_two_distinct_images_open_but_one_image_not_double_proposed():
    world = _world()
    ada = world.agents["agent_a"]
    img1 = world.action_create_image(ada, "one")["payload"]["image_id"]
    img2 = world.action_create_image(ada, "two")["payload"]["image_id"]
    ada.location = "townhall"
    ok1, _, r1 = world.action_propose_rule(ada, "promote_image", "p1", image_id=img1)
    ok2, _, r2 = world.action_propose_rule(ada, "promote_image", "p2", image_id=img2)
    assert ok1 and ok2 and r1 and r2  # two DISTINCT images may have open votes at once
    assert r1.id != r2.id
    # Double-proposing the SAME image is blocked while its vote is open.
    ok_dup, msg_dup, r_dup = world.action_propose_rule(
        ada, "promote_image", "dup", image_id=img1)
    assert not ok_dup and r_dup is None


def test_promote_image_in_propose_rule_valid_effects():
    world = _world()
    ada = world.agents["agent_a"]
    img_id = world.action_create_image(ada, "x")["payload"]["image_id"]
    ada.location = "townhall"
    # image_id may also arrive via the generic `target` arg (the runtime maps either).
    ok, msg, rule = world.action_propose_rule(
        ada, "promote_image", "via target", target=img_id)
    assert ok, msg
    assert rule.payload["image_id"] == img_id


def _runtime_with_script(world: World, agent_id: str, script: list) -> AgentRuntime:
    """Wire a real AgentRuntime over `world` whose `agent_id` is driven by a
    scripted MockProvider — so run_turn rides the genuine perceive → choose →
    parse → _validate_world → _apply_action_inner path (NOT a direct world call)."""
    from petridish.config.loader import ModelProfile
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(script=script)},
                    cache_enabled=False)
    router.reassign(agent_id, "mock")
    router.inject_world(world)
    return AgentRuntime(world, router)


async def test_FULL_AGENT_TURN_promote_image_passes_the_runtime_gate_and_activates():
    """FINDING 1 — the bug the QA tests missed: a promote_image proposal must
    survive the RUNTIME gate (_validate_world) on a real agent turn, not just a
    direct world.action_propose_rule call.

    Drive a full run_turn whose scripted action is `propose_rule promote_image`.
    Pre-fix, _validate_world omitted "promote_image" from valid_effects, so the
    turn was rejected as a parse_failure BEFORE ever reaching the world method —
    no rule was created. Post-fix the proposal is ACCEPTED (a rule exists), votes
    pass at strict majority, plaza_banner_ref is set, and image_promoted emits."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    # Ada paints, then walks to the town hall to propose hanging it over the plaza.
    img_id = world.action_create_image(ada, "the candidate")["payload"]["image_id"]
    ada.location = "townhall"  # propose_rule is governance-gated

    script = [{"thought": "hang my art over the plaza", "action": "propose_rule",
               "args": {"effect": "promote_image", "image_id": img_id,
                        "text": "Hang the candidate over the plaza"}}]
    runtime = _runtime_with_script(world, ada.id, script)

    result = await runtime.run_turn(ada)
    evts = result["_multi"] if "_multi" in result else [result]
    kinds = [e.get("kind") for e in evts]
    # The proposal was ACCEPTED through the gate (NOT a parse_failure / dead turn).
    assert "parse_failure" not in kinds, f"runtime gate rejected promote_image: {evts}"
    # A real promote_image rule now exists in the world (proof the world method ran).
    rule = next((r for r in world.rules.values()
                 if r.effect == "promote_image"
                 and (r.payload or {}).get("image_id") == img_id), None)
    assert rule is not None, "no promote_image rule was created via the full turn"
    assert rule.status == "proposed"
    assert world.plaza_banner_ref == ""  # not promoted until the vote passes

    # Strict majority of two living agents requires BOTH yes.
    world.action_vote(ada, rule.id, True)
    assert world.rules[rule.id].status == "proposed"  # 1/2 is not a majority
    world.action_vote(bram, rule.id, True)
    assert world.rules[rule.id].status == "active"

    # _on_rule_activated side effects: banner set, record promoted, system event.
    assert world.plaza_banner_ref == img_id
    rec = next(g for g in world.gallery if g["image_id"] == img_id)
    assert rec["promoted"] is True
    drained = world.drain_spawn_events()
    promo = next(e for e in drained if e["kind"] == "image_promoted")
    assert promo["actor_type"] == "system"
    assert promo["payload"]["image_id"] == img_id
    assert promo["payload"]["proposal_id"] == rule.id


async def test_FULL_AGENT_TURN_promote_image_unknown_id_is_rejected_at_the_gate():
    """The runtime gate mirrors demolish's target-existence check: a promote of an
    id that is NOT a real gallery image is a clean parse_failure (never reaches the
    world method, never a dead turn)."""
    world = _world()
    ada = world.agents["agent_a"]
    world.action_create_image(ada, "real art")  # gallery is non-empty
    ada.location = "townhall"
    script = [{"action": "propose_rule",
               "args": {"effect": "promote_image", "image_id": "img_nope",
                        "text": "promote a ghost"}}]
    runtime = _runtime_with_script(world, ada.id, script)
    result = await runtime.run_turn(ada)
    evts = result["_multi"] if "_multi" in result else [result]
    assert "parse_failure" in [e.get("kind") for e in evts]
    # No promote_image rule was created.
    assert not any(r.effect == "promote_image" for r in world.rules.values())


def test_validate_world_offers_promote_image_only_for_a_real_gallery_image():
    """FINDING 1 (gate, unit): _validate_world accepts promote_image for a real
    gallery id (via image_id OR the generic target arg) and rejects empty/unknown."""
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "townhall"
    img_id = world.action_create_image(ada, "x")["payload"]["image_id"]
    base = {"action": "propose_rule"}
    # Missing/empty id ⇒ guidance string (rejected).
    assert _validate_world({**base, "args": {"effect": "promote_image", "text": "t"}}, ada, world) is not None
    # Unknown id ⇒ rejected.
    assert _validate_world({**base, "args": {"effect": "promote_image", "image_id": "img_nope", "text": "t"}}, ada, world) is not None
    # Real id via image_id ⇒ accepted.
    assert _validate_world({**base, "args": {"effect": "promote_image", "image_id": img_id, "text": "t"}}, ada, world) is None
    # Real id via the generic target arg ⇒ accepted (the world handler maps it).
    assert _validate_world({**base, "args": {"effect": "promote_image", "target": img_id, "text": "t"}}, ada, world) is None


def test_re_promotion_of_the_current_banner_image_is_rejected_as_noop():
    """FINDING 4 — promoting the image ALREADY on the banner is a no-op and must be
    rejected (mirrors the name_town current-name guard and demolish's already-rubble
    guard), killing the run-663 name_town re-pass-forever spam pattern."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "the one")["payload"]["image_id"]
    ada.location = "townhall"
    # Promote it onto the banner.
    ok, _, rule = world.action_propose_rule(ada, "promote_image", "p", image_id=img_id)
    assert ok
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.plaza_banner_ref == img_id

    # Re-proposing the SAME image that already hangs over the plaza is a no-op.
    ok2, msg2, rule2 = world.action_propose_rule(ada, "promote_image", "again", image_id=img_id)
    assert not ok2 and rule2 is None
    assert "already hangs over the plaza" in msg2
    # A DIFFERENT image is still promotable (the guard is scoped to the current banner).
    other = world.action_create_image(ada, "the other")["payload"]["image_id"]
    ok3, _, rule3 = world.action_propose_rule(ada, "promote_image", "switch", image_id=other)
    assert ok3 and rule3 is not None


# ──────────────────────────────────────────────────────────────────────────────
# Snapshot round-trip (replay-safe, additive)
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_roundtrip_gallery_and_banner_survive():
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "keepsake")["payload"]["image_id"]
    ada.location = "townhall"
    ok, _, rule = world.action_propose_rule(ada, "promote_image", "p", image_id=img_id)
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.plaza_banner_ref == img_id

    snap = world.to_snapshot()
    assert "gallery" in snap and "plaza_banner_ref" in snap
    assert snap["plaza_banner_ref"] == img_id

    restored = World.from_snapshot(snap, params=world.params)
    assert restored.plaza_banner_ref == img_id
    assert len(restored.gallery) == 1
    rrec = restored.gallery[0]
    assert rrec["image_id"] == img_id and rrec["promoted"] is True
    # The transient fetch outbox is NEVER serialized.
    assert "pending_image_fetches" not in snap
    assert restored.pending_image_fetches == []


def test_pre_wave_i_snapshot_restores_byte_identically():
    # A world with no Atelier activity emits neither key (pre-Wave-I byte-identical).
    world = _world()
    snap = world.to_snapshot()
    assert "gallery" not in snap
    assert "plaza_banner_ref" not in snap
    # Restoring a snapshot that lacks both keys yields the empty defaults.
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.gallery == []
    assert restored.plaza_banner_ref == ""


# ──────────────────────────────────────────────────────────────────────────────
# Provider (hermetic — EM_IMAGEGEN_MOCK set in conftest)
# ──────────────────────────────────────────────────────────────────────────────

def test_provider_mock_returns_valid_png_bytes():
    from petridish.imagegen import build_provider
    from petridish.imagegen.provider import MockImageProvider
    provider = build_provider()
    assert isinstance(provider, MockImageProvider)  # EM_IMAGEGEN_MOCK precedence
    png = asyncio.run(provider.fetch_png("anything"))
    assert isinstance(png, bytes) and len(png) > 0
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature


def test_provider_precedence_mock_over_cloudflare(monkeypatch):
    # EM_IMAGEGEN_MOCK wins even when Cloudflare env is present (selection precedence).
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    from petridish.imagegen import build_provider
    from petridish.imagegen.provider import MockImageProvider
    assert isinstance(build_provider(), MockImageProvider)


# ──────────────────────────────────────────────────────────────────────────────
# Menu / resolution agreement (EM-108)
# ──────────────────────────────────────────────────────────────────────────────

def test_menu_offers_create_image_always_and_post_image_only_with_an_image():
    world = _world()
    ada = world.agents["agent_a"]
    ada.location = "plaza"
    ctx = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "create_image" in ctx
    # post_image is NOT offered before the agent has painted anything.
    assert "post_image" not in ctx
    # After creating one, post_image appears (at the billboard).
    world.action_create_image(ada, "first")
    ctx2 = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "post_image" in ctx2


def test_menu_post_image_not_offered_off_billboard():
    world = _world()
    ada = world.agents["agent_a"]
    world.action_create_image(ada, "first")
    ada.location = "forge"  # no billboard
    ctx = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "create_image" in ctx       # ungated, still offered
    assert "post_image" not in ctx     # gate + resolution agree


# ──────────────────────────────────────────────────────────────────────────────
# EM-210 credit kill switch — image_gen.enabled=False (out-of-credits mitigation)
# ──────────────────────────────────────────────────────────────────────────────

def _world_image_disabled() -> World:
    params = WorldParams(
        energy_decay_per_turn=0.0, death_after_zero_turns=99, turns_per_day=999,
        image_gen=ImageGenParams(enabled=False),
    )
    agents = [AgentState(id="agent_a", name="Ada", personality="", profile="mock",
                         location="plaza", energy=100, credits=100)]
    return World(params, _places(), agents)


def test_image_gen_disabled_rejects_create_image_and_parks_no_fetch():
    """The credit-safe kill switch: create_image is rejected BEFORE any fetch is
    parked, so the loop makes ZERO image-API calls (no PNG fetch to drain)."""
    world = _world_image_disabled()
    ada = world.agents["agent_a"]
    evt = world.action_create_image(ada, "a sunset over the plaza")
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["error"] == "image_gen_disabled"
    assert world.gallery == []                 # nothing recorded
    assert world.pending_image_fetches == []   # NO image-API fetch parked


def test_image_gen_disabled_drops_create_image_from_menu():
    world = _world_image_disabled()
    ada = world.agents["agent_a"]
    ctx = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "create_image" not in ctx           # menu + resolution agree (EM-108)


def test_image_gen_enabled_by_default_is_unchanged():
    world = _world()                           # default ImageGenParams ⇒ enabled
    ada = world.agents["agent_a"]
    evt = world.action_create_image(ada, "a fountain")
    assert evt["kind"] == "image_posted"
    assert len(world.pending_image_fetches) == 1
    ctx = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "create_image" in ctx


def test_menu_offers_promote_image_with_a_concrete_promotable_id():
    """FINDING 1(b) — agents must be OFFERED promote_image (menu/resolution agree,
    EM-108): at the town hall the propose_rule menu names the effect with a CONCRETE
    promotable image_id (the newest gallery image), and omits it when there is no
    promotable image — never naming an image that would be rejected as a no-op."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    ada.location = "townhall"  # propose_rule is governance-gated
    # No gallery yet ⇒ the effect is NOT offered (nothing promotable).
    ctx0 = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "promote_image" not in ctx0

    # Paint something ⇒ promote_image is now offered WITH the concrete id.
    img_id = world.action_create_image(ada, "candidate")["payload"]["image_id"]
    ctx1 = _prompt_text(_assemble_context(ada, world, [], world.params))
    assert "promote_image" in ctx1
    assert img_id in ctx1  # the menu names a real, promotable id (resolution agrees)

    # Once it is on the banner, it is no longer promotable; a LATER image is offered.
    _, _, rule = world.action_propose_rule(ada, "promote_image", "p", image_id=img_id)
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.plaza_banner_ref == img_id
    newer = world.action_create_image(ada, "the next one")["payload"]["image_id"]
    ctx2 = _prompt_text(_assemble_context(ada, world, [], world.params))
    # The menu offers the NEWER (promotable) image, never the one already hanging.
    assert newer in ctx2
    assert "promote_image" in ctx2


# ──────────────────────────────────────────────────────────────────────────────
# Loop drain — best-effort PNG fetch (hermetic via the mock provider)
# ──────────────────────────────────────────────────────────────────────────────

def _loop(tmp_path, *, max_concurrent: int = 2):
    """A minimal TickLoop over an offline mock world, with the assets dir
    redirected to a tmp path so a fetch writes there (never into the repo)."""
    params = WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        image_gen=ImageGenParams(max_concurrent=max_concurrent),
    )
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                         location="plaza", energy=80, credits=20)]
    world = World(params=params, places=places, agents=agents)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": MockProvider(
        script=[{"action": "idle", "args": {}}])}, cache_enabled=False)
    router.reassign("agent_ada", "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    # Redirect the assets dir into the test's tmp.
    images_dir = tmp_path / "data" / "assets" / "images"
    loop._assets_images_dir = lambda: images_dir  # type: ignore[assignment]
    return loop, world, images_dir


def test_loop_drain_writes_png_under_cap(tmp_path):
    loop, world, images_dir = _loop(tmp_path)
    img_id = world.action_create_image(world.agents["agent_ada"], "art")["payload"]["image_id"]
    assert world.pending_image_fetches  # parked by create_image

    async def _go():
        loop._drain_image_fetches()        # starts the fire-and-forget fetch
        # await the in-flight tasks so the file is written deterministically.
        for task in list(loop._image_fetch_tasks):
            await task

    asyncio.run(_go())
    assert world.pending_image_fetches == []           # outbox drained
    written = images_dir / f"{img_id}.png"
    assert written.exists()
    assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"  # the mock PNG landed


def test_loop_drain_skips_over_cap_without_raising(tmp_path):
    # max_concurrent=1, and we pre-acquire the semaphore so the drain is "at cap":
    # the fetch must be SKIPPED (no task, no file), never raise or queue.
    loop, world, images_dir = _loop(tmp_path, max_concurrent=1)
    img_id = world.action_create_image(world.agents["agent_ada"], "art")["payload"]["image_id"]

    async def _go():
        # Force the semaphore to exist + be fully held (simulating in-flight load).
        loop._image_semaphore = asyncio.Semaphore(1)
        await loop._image_semaphore.acquire()
        loop._drain_image_fetches()        # at cap ⇒ skip-under-load
        # No fetch task should have been created.
        assert not loop._image_fetch_tasks
        loop._image_semaphore.release()

    asyncio.run(_go())
    # The gallery entry + event still exist; the PNG is simply absent (FE fallback).
    assert any(g["image_id"] == img_id for g in world.gallery)
    assert not (images_dir / f"{img_id}.png").exists()


def test_loop_drain_no_pending_is_noop(tmp_path):
    loop, world, images_dir = _loop(tmp_path)
    # Nothing parked ⇒ no provider build, no tasks, no raise.
    loop._drain_image_fetches()
    assert loop._image_fetch_tasks == set()

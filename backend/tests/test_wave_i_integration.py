"""Wave I · The Atelier (EM-210–213) — CROSS-CUTTING integration tests.

These are the END-TO-END flows the impl-agent unit tests
(`test_wave_i_atelier.py`) deliberately do NOT cover. They exercise the whole
arc on a REAL World + AgentRuntime + TickLoop wired together — never a single
method in isolation:

  1. FULL ARC on a live world+runtime: an agent's reflex `create_image` lands a
     gallery entry + `image_posted` event + a parked `pending_image_fetches`
     request; a second agent `post_image @billboard` carries `image_ref` on the
     billboard payload; a `propose_rule promote_image` voted to STRICT MAJORITY
     drives `_on_rule_activated` → `plaza_banner_ref` set + record `promoted=True`
     + an `image_promoted` event drained from the spawn outbox.

  2. REPLAY/FORK DETERMINISM end-to-end (the EM-155 keystone): drive N ticks with
     `create_image` calls on a MockProvider through the real TickLoop, snapshot,
     FORK via `World.from_snapshot`, continue BOTH lineages with the SAME script,
     and assert the gallery + plaza_banner_ref + every image_id are BYTE-IDENTICAL
     across the two lineages. Tested hard — this is the contract's keystone.

  3. SNAPSHOT round-trips through the loop's serialize path: a world WITH a
     gallery + banner survives `json.dumps(to_snapshot)` → `from_snapshot`
     byte-identically; a pre-Wave-I snapshot (no gallery/banner keys) restores
     with [] / "" and serializes byte-identically to a never-touched baseline.

  4. LOOP DRAIN is hermetic (EM_IMAGEGEN_MOCK, set in conftest) and NEVER raises:
     drains across a real turn without a network hit; over-cap fetches are SKIPPED
     (gallery entry + event survive, the PNG is simply absent).

CRITICAL suite rule (mirrors W8 / Wave-K / the impl file): import
petridish.engine.world BEFORE the runtime modules so the world module binds
first (avoids the engine↔agents circular-import order trap).
"""
from __future__ import annotations

import asyncio
import json

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    ImageGenParams, ModelProfile, PlaceConfig, WorldConfig, WorldParams,
)

# Runtime imports AFTER world.
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# World / loop fixtures — a tiny OFFLINE world (no live router calls).
# ──────────────────────────────────────────────────────────────────────────────

def _places():
    return [
        PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceState(id="forge", name="The Forge", x=600, y=500, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=400, y=500, kind="governance"),
    ]


def _world(*, city_seed: int = 1337, max_gallery: int = 30) -> World:
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


def _build_loop(world: World, *, script: list, assets_dir, max_concurrent: int = 2):
    """A real TickLoop over `world`, driven by a scripted MockProvider so
    create_image rides the genuine perceive → choose → dispatch → emit path.
    The image-fetch side-artifact dir is redirected to a per-test tmp path so a
    best-effort PNG write can NEVER land in the repo's data/assets/images."""
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
    provider = MockProvider(script=script)
    router = Router(profiles, adapter_overrides={"mock": provider}, cache_enabled=False)
    for aid in world.agents:
        router.reassign(aid, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    repo = SQLiteRepository(":memory:")
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=world.params, places=[], agents=[], animals=[]))
    loop._image_semaphore = asyncio.Semaphore(max_concurrent)
    loop._assets_images_dir = lambda: assets_dir  # type: ignore[assignment]
    return loop, router, provider


async def _drive_ticks(loop: TickLoop, n: int) -> None:
    """Advance exactly n turns through the real loop, awaiting each so the per-turn
    image-fetch drain runs deterministically. The loop starts paused, so each
    step_and_wait advances one turn and stops."""
    for _ in range(n):
        await loop.step_and_wait(timeout=5.0)
    # Let any fire-and-forget fetch tasks settle so they cannot leak across runs.
    for task in list(loop._image_fetch_tasks):
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # best-effort; swallow
            pass


# ──────────────────────────────────────────────────────────────────────────────
# 1 — FULL ARC end-to-end on a live World + runtime (no isolated-method shortcut)
# ──────────────────────────────────────────────────────────────────────────────

def test_full_atelier_arc_create_post_promote_end_to_end():
    """create_image → gallery + image_posted + parked fetch; post_image @billboard
    → image_ref on the billboard payload; propose_rule promote_image → vote to
    strict majority → _on_rule_activated sets banner + promoted + image_promoted."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    world.tick = 5

    # --- I1: create_image records gallery + parks a fetch + emits image_posted ---
    created = world.action_create_image(ada, "a koi pond at dusk")
    assert created["kind"] == "image_posted"
    img_id = created["payload"]["image_id"]
    url = created["payload"]["url"]
    assert url == f"/assets/images/{img_id}.png"
    assert len(world.gallery) == 1
    assert world.gallery[0]["promoted"] is False
    assert world.pending_image_fetches == [
        {"image_id": img_id, "prompt": "a koi pond at dusk", "url": url}]

    # --- I2: post_image @billboard threads image_ref onto the billboard payload ---
    ada.location = "plaza"  # the billboard stands at the plaza
    posted = world.action_post_image(ada, img_id)
    assert posted["kind"] == "billboard_posted"
    assert posted["payload"]["image_ref"] == url
    assert posted["payload"]["image_id"] == img_id
    # The post actually landed on the shared board the other agents perceive.
    assert world.billboard and url == posted["payload"]["image_ref"]

    # --- I3/I4: propose_rule promote_image → strict-majority vote → activation ---
    ada.location = "townhall"  # propose_rule is governance-gated
    ok, msg, rule = world.action_propose_rule(
        ada, "promote_image", "Hang the koi over the plaza", image_id=img_id)
    assert ok, msg
    assert rule.payload["image_id"] == img_id
    assert world.plaza_banner_ref == ""  # not yet promoted

    # Two living agents → strict majority requires BOTH yes (one yes is not a pass).
    world.action_vote(ada, rule.id, True)
    assert world.rules[rule.id].status == "proposed"  # 1/2 is not strict majority
    assert world.plaza_banner_ref == ""
    world.action_vote(bram, rule.id, True)
    assert world.rules[rule.id].status == "active"

    # _on_rule_activated side effects.
    assert world.plaza_banner_ref == img_id
    rec = next(g for g in world.gallery if g["image_id"] == img_id)
    assert rec["promoted"] is True

    # image_promoted parked as a SYSTEM event in the spawn outbox, drained here.
    drained = world.drain_spawn_events()
    promo = next(e for e in drained if e["kind"] == "image_promoted")
    assert promo["actor_id"] == "system"
    assert promo["actor_type"] == "system"
    assert promo["payload"]["image_id"] == img_id
    assert promo["payload"]["url"] == url
    assert promo["payload"]["proposal_id"] == rule.id


def test_promoted_image_becomes_public_and_postable_by_others_end_to_end():
    """The promote arc has a downstream consequence the unit tests don't chain:
    once an image is voted onto the banner it is PUBLIC, so a DIFFERENT agent can
    post it (the unowned-unpromoted post is rejected before promotion)."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "ada's mural")["payload"]["image_id"]

    # Before promotion, Bram cannot post Ada's image.
    bram.location = "plaza"
    assert world.action_post_image(bram, img_id)["kind"] == "parse_failure"

    # Promote it by vote.
    ada.location = "townhall"
    _, _, rule = world.action_propose_rule(ada, "promote_image", "p", image_id=img_id)
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.plaza_banner_ref == img_id

    # Now the public, promoted image is postable by Bram.
    bram.location = "plaza"
    evt = world.action_post_image(bram, img_id)
    assert evt["kind"] == "billboard_posted"
    assert evt["payload"]["image_id"] == img_id


# ──────────────────────────────────────────────────────────────────────────────
# 2 — REPLAY / FORK DETERMINISM end-to-end (the EM-155 keystone)
# ──────────────────────────────────────────────────────────────────────────────

# A script that makes EVERY agent paint, share, and (at the town hall) try to
# govern the image. Cycled per-agent by the MockProvider; it drives create_image
# through the genuine reflex dispatch so the ids are minted exactly as in prod.
_ATELIER_SCRIPT = [
    {"thought": "paint", "action": "create_image", "args": {"prompt": "a lantern festival"}},
    {"thought": "paint again", "action": "create_image", "args": {"prompt": "the night market"}},
    {"thought": "to the hall", "action": "move_to", "args": {"place": "townhall"}},
    {"thought": "paint more", "action": "create_image", "args": {"prompt": "a paper crane"}},
    {"thought": "back to plaza", "action": "move_to", "args": {"place": "plaza"}},
]


def _run_lineage(city_seed: int, n_ticks: int, assets_dir) -> dict:
    """Run a fresh world n_ticks through the real loop with the atelier script,
    return its post-run snapshot (json-round-tripped to prove serializability)."""
    world = _world(city_seed=city_seed)
    loop, _router, _provider = _build_loop(
        world, script=list(_ATELIER_SCRIPT), assets_dir=assets_dir)
    asyncio.run(_drive_ticks(loop, n_ticks))
    return json.loads(json.dumps(world.to_snapshot()))


def test_replay_two_independent_lineages_are_byte_identical(tmp_path):
    """Two independent runs with the SAME city_seed + SAME script produce
    byte-identical galleries + image ids + (any) banner — the EM-155 keystone.
    The image_id is seeded, never uuid4/wall-clock, so the whole image surface
    of the snapshot reproduces exactly."""
    snap_a = _run_lineage(4242, 8, tmp_path / "a")
    snap_b = _run_lineage(4242, 8, tmp_path / "b")

    # The galleries actually got populated (the script paints) — guard against a
    # vacuous pass where nothing happened.
    assert snap_a.get("gallery"), "expected the script to populate a gallery"
    ids_a = [g["image_id"] for g in snap_a["gallery"]]
    assert all(i.startswith("img_") and len(i) == len("img_") + 10 for i in ids_a)

    # The keystone: the image surface is byte-identical across the two lineages.
    assert snap_a["gallery"] == snap_b["gallery"]
    assert snap_a.get("plaza_banner_ref", "") == snap_b.get("plaza_banner_ref", "")
    # And the urls are derived purely from the (seeded) ids.
    for g in snap_a["gallery"]:
        assert g["url"] == f"/assets/images/{g['image_id']}.png"

    # A DIFFERENT seed shifts the ids (the seed truly participates in the id).
    snap_c = _run_lineage(909090, 8, tmp_path / "c")
    ids_c = [g["image_id"] for g in snap_c.get("gallery", [])]
    assert ids_a != ids_c


def test_fork_then_continue_two_forks_stay_byte_identical(tmp_path):
    """The fork keystone: run N ticks, FORK the snapshot TWICE via
    World.from_snapshot, then continue BOTH forks with the same subsequent action
    stream — the gallery, every image id, and plaza_banner_ref must be
    byte-identical across the two forked lineages (seeded ids inject no entropy at
    the snapshot boundary). Two forks of one snapshot is exactly the EM-155
    fork-determinism contract: same base + same inputs ⇒ same outputs.

    (Each asyncio.run() makes a fresh event loop, so each loop object is driven
    inside exactly ONE run() — the asyncio primitives are never re-bound.)"""
    # --- Phase 1: a shared parent run up to the fork point. ---
    parent = _world(city_seed=777)
    loop_p, _r, _p = _build_loop(
        parent, script=list(_ATELIER_SCRIPT), assets_dir=tmp_path / "parent")
    asyncio.run(_drive_ticks(loop_p, 6))
    fork_point = json.loads(json.dumps(parent.to_snapshot()))
    assert fork_point.get("gallery"), "fork point should already hold gallery art"

    def _continue_a_fork(tag: str) -> dict:
        forked = World.from_snapshot(fork_point, params=parent.params)
        # Fork fidelity: paused, no transient outbox, same tick + gallery as base.
        assert forked.running is False
        assert forked.pending_image_fetches == []
        assert forked.tick == fork_point["tick"]
        assert [g["image_id"] for g in forked.gallery] == \
            [g["image_id"] for g in fork_point["gallery"]]
        loop_f, _r2, _p2 = _build_loop(
            forked, script=list(_ATELIER_SCRIPT), assets_dir=tmp_path / tag)
        asyncio.run(_drive_ticks(loop_f, 6))
        return json.loads(json.dumps(forked.to_snapshot()))

    fork_one = _continue_a_fork("fork_one")
    fork_two = _continue_a_fork("fork_two")

    # --- The keystone assertion: the two forked lineages diverge in NOTHING. ---
    assert [g["image_id"] for g in fork_one["gallery"]] == \
        [g["image_id"] for g in fork_two["gallery"]]
    assert fork_one["gallery"] == fork_two["gallery"]
    assert fork_one.get("plaza_banner_ref", "") == \
        fork_two.get("plaza_banner_ref", "")
    # The continuation actually produced MORE art than the fork point (guards a
    # vacuous pass where the forks never advanced).
    assert len(fork_one["gallery"]) >= len(fork_point["gallery"])


def test_fork_at_two_points_yields_consistent_seeded_ids(tmp_path):
    """Forking the SAME parent and continuing two re-forks of the same snapshot to
    the same final tick must converge on the same image surface — the seeded id
    depends only on (place, proposer, ordinal, city_seed), never on the fork. A
    second, independent end-to-end witness of the EM-155 keystone."""
    parent = _world(city_seed=1357)
    loop_p, _r, _p = _build_loop(
        parent, script=list(_ATELIER_SCRIPT), assets_dir=tmp_path / "parent")
    asyncio.run(_drive_ticks(loop_p, 8))
    early = json.loads(json.dumps(parent.to_snapshot()))  # fork point @ tick 8

    # Fork A: from the tick-8 snapshot, run 4 more ticks.
    fa = World.from_snapshot(early, params=parent.params)
    la, _r2, _p2 = _build_loop(
        fa, script=list(_ATELIER_SCRIPT), assets_dir=tmp_path / "fa")
    asyncio.run(_drive_ticks(la, 4))
    snap_a = json.loads(json.dumps(fa.to_snapshot()))

    # Fork B: re-fork from the SAME tick-8 snapshot, run the same 4 ticks.
    fb = World.from_snapshot(early, params=parent.params)
    lb, _r3, _p3 = _build_loop(
        fb, script=list(_ATELIER_SCRIPT), assets_dir=tmp_path / "fb")
    asyncio.run(_drive_ticks(lb, 4))
    snap_b = json.loads(json.dumps(fb.to_snapshot()))

    assert snap_a.get("gallery"), "expected art after the fork continuation"
    assert [g["image_id"] for g in snap_a["gallery"]] == \
        [g["image_id"] for g in snap_b["gallery"]]
    assert snap_a["gallery"] == snap_b["gallery"]
    assert snap_a.get("plaza_banner_ref", "") == snap_b.get("plaza_banner_ref", "")


# ──────────────────────────────────────────────────────────────────────────────
# 3 — SNAPSHOT round-trip through the loop serialize path (json-safe, additive)
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_with_gallery_and_banner_survives_json_roundtrip_byte_identical():
    """A world WITH a gallery + promoted banner serializes to JSON and restores
    byte-identically (re-serialized snapshot equals the first). Proves every
    gallery field is JSON-safe and the restore is lossless on the image surface."""
    world = _world()
    ada, bram = world.agents["agent_a"], world.agents["agent_b"]
    img_id = world.action_create_image(ada, "keepsake mural")["payload"]["image_id"]
    ada.location = "townhall"
    _, _, rule = world.action_propose_rule(ada, "promote_image", "p", image_id=img_id)
    world.action_vote(ada, rule.id, True)
    world.action_vote(bram, rule.id, True)
    assert world.plaza_banner_ref == img_id

    snap1 = world.to_snapshot()
    # JSON round-trip (the loop broadcasts json.dumps(to_snapshot)).
    wire = json.loads(json.dumps(snap1))
    assert wire["plaza_banner_ref"] == img_id
    assert any(g["image_id"] == img_id and g["promoted"] is True for g in wire["gallery"])

    restored = World.from_snapshot(wire, params=world.params)
    snap2 = json.loads(json.dumps(restored.to_snapshot()))
    # The image surface round-trips byte-identically.
    assert snap2["gallery"] == wire["gallery"]
    assert snap2["plaza_banner_ref"] == wire["plaza_banner_ref"]
    # The transient outbox is never on the wire either way.
    assert "pending_image_fetches" not in snap1
    assert restored.pending_image_fetches == []


def test_pre_wave_i_snapshot_serializes_byte_identical_to_untouched_baseline():
    """A world that never touched the Atelier emits NEITHER key. Restoring such a
    snapshot and re-serializing yields a dict byte-identical to a baseline world's
    snapshot (the pre-Wave-I key set is preserved end-to-end)."""
    baseline = _world(city_seed=2024)
    baseline_snap = json.loads(json.dumps(baseline.to_snapshot()))
    assert "gallery" not in baseline_snap
    assert "plaza_banner_ref" not in baseline_snap

    # Restore the keyless snapshot → empty defaults, and re-serialize.
    restored = World.from_snapshot(baseline_snap, params=baseline.params)
    assert restored.gallery == []
    assert restored.plaza_banner_ref == ""
    restored_snap = json.loads(json.dumps(restored.to_snapshot()))

    # Byte-identical: the absence of the Wave-I keys is preserved across the trip.
    assert "gallery" not in restored_snap
    assert "plaza_banner_ref" not in restored_snap
    assert restored_snap == baseline_snap


def test_post_wave_i_world_with_empty_gallery_still_emits_no_keys():
    """An empty gallery (e.g. every image popped or none yet) must NOT emit the
    keys — the conditional is on truthiness, so a Wave-I-capable world with no art
    is still byte-identical to pre-Wave-I (guards the cap_demotions pattern)."""
    world = _world(max_gallery=1)
    ada = world.agents["agent_a"]
    # Create then ensure the gallery is emptied to simulate "no active art".
    world.action_create_image(ada, "ephemeral")
    world.gallery.clear()
    snap = world.to_snapshot()
    assert "gallery" not in snap
    assert "plaza_banner_ref" not in snap


# ──────────────────────────────────────────────────────────────────────────────
# 4 — LOOP DRAIN hermeticism (EM_IMAGEGEN_MOCK) + skip-under-load, NEVER raises
# ──────────────────────────────────────────────────────────────────────────────

def test_loop_drain_across_a_real_turn_is_hermetic_and_never_raises(tmp_path):
    """Drive a real turn whose script paints; the per-turn drain runs the mock
    provider (no network — EM_IMAGEGEN_MOCK), writes the side-artifact under the
    redirected tmp dir, and the turn completes without raising."""
    world = _world()
    images_dir = tmp_path / "data" / "assets" / "images"
    loop, _r, _p = _build_loop(
        world, script=[{"thought": "paint", "action": "create_image",
                        "args": {"prompt": "a hermetic test canvas"}}],
        assets_dir=images_dir)

    async def _go():
        await loop.step_and_wait(timeout=5.0)
        # Await the fire-and-forget fetch so the file lands deterministically.
        for task in list(loop._image_fetch_tasks):
            await task

    asyncio.run(_go())
    # A gallery entry exists and the mock PNG landed (hermetic — no network).
    assert world.gallery, "the painted image should be in the gallery"
    img_id = world.gallery[-1]["image_id"]
    written = images_dir / f"{img_id}.png"
    assert written.exists()
    assert written.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # The transient outbox was drained by the turn (nothing left parked).
    assert world.pending_image_fetches == []


def test_loop_drain_over_cap_skips_fetch_but_keeps_gallery_and_never_raises(tmp_path):
    """With the semaphore fully held (in-flight load), the drain SKIPS the fetch:
    no task is created, no PNG is written, nothing raises — yet the gallery entry
    and the event still exist (the frontend renders its procedural fallback)."""
    world = _world()
    images_dir = tmp_path / "data" / "assets" / "images"
    loop, _r, _p = _build_loop(
        world, script=[{"thought": "idle", "action": "idle", "args": {}}],
        assets_dir=images_dir, max_concurrent=1)

    img_id = world.action_create_image(
        world.agents["agent_a"], "over-cap art")["payload"]["image_id"]
    assert world.pending_image_fetches  # parked

    async def _go():
        # Fully hold the (size-1) semaphore to simulate a fetch already in flight.
        await loop._image_semaphore.acquire()
        loop._drain_image_fetches()  # at cap ⇒ skip-under-load
        assert not loop._image_fetch_tasks  # no task created
        loop._image_semaphore.release()

    asyncio.run(_go())
    # Gallery entry + (already-emitted) event survive; the PNG is simply absent.
    assert any(g["image_id"] == img_id for g in world.gallery)
    assert not (images_dir / f"{img_id}.png").exists()


def test_loop_drain_with_nothing_pending_is_a_safe_noop(tmp_path):
    """A drain with an empty outbox builds no provider, starts no task, and never
    raises — safe to call on the hot path every turn."""
    world = _world()
    images_dir = tmp_path / "data" / "assets" / "images"
    loop, _r, _p = _build_loop(
        world, script=[{"thought": "idle", "action": "idle", "args": {}}],
        assets_dir=images_dir)
    assert world.pending_image_fetches == []
    loop._drain_image_fetches()
    assert loop._image_fetch_tasks == set()
    assert not images_dir.exists()  # no side-artifact dir created on a no-op

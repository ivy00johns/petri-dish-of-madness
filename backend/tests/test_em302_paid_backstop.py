"""EM-302c — the paid-image backstop HARD cap (per run) + the repaint fallback.

The zero-cost create_image/paint_surface reflex path had a cost tail: every
minted image parks a PNG fetch, and when every FREE lane misses, the chain
falls through to the PAID Gemini backstop with no bound. Pinned here:

  * GeminiImageProvider.max_per_run — over the cap the paid lane returns None
    with ZERO network calls; a successful generation consumes a slot; an
    UNBILLED miss (no HTTP 200: 429/network failure) releases its slot; a
    billed-but-REJECTED 200 (unusable payload) KEEPS its slot consumed — the
    generation was charged, so releasing would let real spend exceed the cap;
    0 disables the lane outright; negative = unlimited (pre-EM-302);
    concurrent fetches can never overshoot (the slot is reserved before the
    awaited call).
  * build_provider threads `paid_backstop_max_per_run` into the Gemini member
    (None ⇒ the module default 25); free lanes are NEVER capped.
  * config plumbing — ImageGenParams.paid_backstop_max_per_run default 25,
    parsed unfloored (0/negative are first-class), garbage falls back.
  * loop wiring — _drain_image_fetches builds the provider with the config'd
    cap; reset() drops the provider so a NEW run re-arms the budget.
  * the repaint fallback — when every lane misses OR the fetch is load-shed
    (dropped at drain with the semaphore saturated, or dropped by the
    create_task→run semaphore race), a paint_surface REPAINT keeps the
    previous artwork (the prev PNG is copied to the new image id); a fresh
    paint stays absent (clean facade); nothing surfaces to the agent turn
    (the reflex already succeeded at resolution time).
  * world seam — action_paint_surface annotates the parked fetch entry with
    `prev_image_id` ONLY on a repaint; the transient outbox is never
    serialized, so replay/snapshot surfaces are untouched.
"""
from __future__ import annotations

import asyncio
import base64

import pytest

from petridish.config.loader import ImageGenParams, WorldParams, _parse_image_gen
from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.imagegen import build_provider
from petridish.imagegen.provider import (
    ChainImageProvider,
    GeminiImageProvider,
    _MOCK_PNG,
    _PAID_BACKSTOP_DEFAULT_MAX,
)


_PNG_B64 = base64.b64encode(_MOCK_PNG).decode("ascii")
_GEMINI_OK = {"candidates": [{"content": {"parts": [
    {"inlineData": {"data": _PNG_B64}}]}}]}


# ── fake httpx (mirrors test_imagegen_providers.py) ───────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, content=b"", payload=None, text=""):
        self.status_code = status_code
        self.content = content
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    handler = None
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeClient.calls.append(("POST", url, kw))
        return _FakeClient.handler("POST", url, **kw)

    async def get(self, url, **kw):
        _FakeClient.calls.append(("GET", url, kw))
        return _FakeClient.handler("GET", url, **kw)


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    _FakeClient.calls = []
    _FakeClient.handler = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


# ── the provider-level hard cap ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cap_stops_paid_generations_with_zero_network_calls(fake_httpx):
    fake_httpx.handler = lambda m, u, **kw: _FakeResp(200, payload=_GEMINI_OK)
    provider = GeminiImageProvider("gkey", max_per_run=2)
    assert await provider.fetch_png("one") == _MOCK_PNG
    assert await provider.fetch_png("two") == _MOCK_PNG
    assert len(fake_httpx.calls) == 2
    # Third generation: over the cap → None, and NO third HTTP call was made.
    assert await provider.fetch_png("three") is None
    assert await provider.fetch_png("four") is None
    assert len(fake_httpx.calls) == 2


@pytest.mark.asyncio
async def test_failed_attempts_do_not_consume_cap_slots(fake_httpx):
    responses = [_FakeResp(429, text="quota"), _FakeResp(429, text="quota"),
                 _FakeResp(200, payload=_GEMINI_OK)]
    fake_httpx.handler = lambda m, u, **kw: responses.pop(0)
    provider = GeminiImageProvider("gkey", max_per_run=1)
    # Two 429 misses release their reserved slot each time…
    assert await provider.fetch_png("a") is None
    assert await provider.fetch_png("b") is None
    # …so the one budgeted generation still lands on the third try.
    assert await provider.fetch_png("c") == _MOCK_PNG
    # And now the budget is spent: no further HTTP calls.
    assert await provider.fetch_png("d") is None
    assert len(fake_httpx.calls) == 3


@pytest.mark.asyncio
async def test_billed_but_rejected_200_still_consumes_a_cap_slot(fake_httpx):
    """An HTTP 200 whose payload yields no usable image (no image part, or a
    body that isn't even JSON) was still a BILLED generation — its slot must
    stay consumed, or real spend could exceed the cap."""
    responses = [
        _FakeResp(200, payload={"candidates": []}),  # billed, no image part
        _FakeResp(200, payload=None, text="not json"),  # billed, json() raises
        _FakeResp(200, payload=_GEMINI_OK),  # would serve — must never be reached
    ]
    fake_httpx.handler = lambda m, u, **kw: responses.pop(0)
    provider = GeminiImageProvider("gkey", max_per_run=2)
    assert await provider.fetch_png("a") is None  # slot 1 spent (billed miss)
    assert await provider.fetch_png("b") is None  # slot 2 spent (billed miss)
    # The whole budget went to billed-but-rejected calls: no third HTTP call.
    assert await provider.fetch_png("c") is None
    assert len(fake_httpx.calls) == 2


@pytest.mark.asyncio
async def test_cap_zero_disables_the_paid_lane_entirely(fake_httpx):
    fake_httpx.handler = lambda m, u, **kw: _FakeResp(200, payload=_GEMINI_OK)
    provider = GeminiImageProvider("gkey", max_per_run=0)
    assert await provider.fetch_png("x") is None
    assert fake_httpx.calls == []


@pytest.mark.asyncio
async def test_negative_cap_is_unlimited_pre_em302_behavior(fake_httpx):
    fake_httpx.handler = lambda m, u, **kw: _FakeResp(200, payload=_GEMINI_OK)
    provider = GeminiImageProvider("gkey", max_per_run=-1)
    for i in range(_PAID_BACKSTOP_DEFAULT_MAX + 5):
        assert await provider.fetch_png(f"p{i}") == _MOCK_PNG
    assert len(fake_httpx.calls) == _PAID_BACKSTOP_DEFAULT_MAX + 5


@pytest.mark.asyncio
async def test_concurrent_fetches_cannot_overshoot_the_cap(monkeypatch):
    """The slot is reserved BEFORE the awaited network call, so two in-flight
    fetches under cap=1 yield exactly ONE paid generation."""
    import httpx

    gate = asyncio.Event()
    calls: list = []

    class _SlowClient(_FakeClient):
        async def post(self, url, **kw):
            calls.append(url)
            await gate.wait()  # both tasks park here if both got through
            return _FakeResp(200, payload=_GEMINI_OK)

    monkeypatch.setattr(httpx, "AsyncClient", _SlowClient)
    provider = GeminiImageProvider("gkey", max_per_run=1)

    async def _go():
        t1 = asyncio.create_task(provider.fetch_png("first"))
        t2 = asyncio.create_task(provider.fetch_png("second"))
        await asyncio.sleep(0)  # let both tasks hit the cap gate
        gate.set()
        return await asyncio.gather(t1, t2)

    results = await _go()
    assert sorted(r is None for r in results) == [False, True]  # exactly one PNG
    assert len(calls) == 1  # the over-cap task never reached the network


def test_build_provider_threads_the_cap_into_the_gemini_member(monkeypatch):
    for k in ("EM_IMAGEGEN_MOCK", "CF_ACCOUNT_ID", "CF_API_TOKEN", "FREELLMAPI_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    provider = build_provider(paid_backstop_max_per_run=7)
    assert isinstance(provider, ChainImageProvider)
    gemini = provider._providers[-1]
    assert isinstance(gemini, GeminiImageProvider)
    assert gemini._max_per_run == 7
    # None defers to the module default (25).
    default = build_provider()._providers[-1]
    assert default._max_per_run == _PAID_BACKSTOP_DEFAULT_MAX


# ── config plumbing ───────────────────────────────────────────────────────────

def test_image_gen_params_default_and_parse():
    assert ImageGenParams().paid_backstop_max_per_run == _PAID_BACKSTOP_DEFAULT_MAX
    assert _parse_image_gen(None).paid_backstop_max_per_run == 25
    assert _parse_image_gen(
        {"paid_backstop_max_per_run": 3}).paid_backstop_max_per_run == 3
    # 0 and negatives are FIRST-CLASS (paid-off / unlimited) — no floor.
    assert _parse_image_gen(
        {"paid_backstop_max_per_run": 0}).paid_backstop_max_per_run == 0
    assert _parse_image_gen(
        {"paid_backstop_max_per_run": -1}).paid_backstop_max_per_run == -1
    # Garbage falls back to the default.
    assert _parse_image_gen(
        {"paid_backstop_max_per_run": "lots"}).paid_backstop_max_per_run == 25


def test_shipped_configs_carry_the_cap():
    """Both checked-in world configs pin the cap explicitly (config is baked
    per run, so the shipped files are the operative default)."""
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[2] / "config"
    for name in ("world.yaml", "world.city25.yaml"):
        raw = yaml.safe_load((root / name).read_text())
        block = raw["world"]["image_gen"]
        assert block["paid_backstop_max_per_run"] == 25, name
        assert _parse_image_gen(block).paid_backstop_max_per_run == 25


# ── loop wiring + the repaint keep-existing fallback ─────────────────────────

def _params(**image_gen_kw):
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        image_gen=ImageGenParams(**image_gen_kw),
    )


def _loop(tmp_path, params):
    """A minimal TickLoop over an offline mock world (test_wave_i_atelier's
    harness) with the assets dir redirected into tmp."""
    from petridish.engine.loop import TickLoop
    from petridish.agents.runtime import AgentRuntime
    from petridish.providers.router import Router
    from petridish.providers.mock import MockProvider
    from petridish.persistence.repository import SQLiteRepository
    from petridish.config.loader import ModelProfile, WorldConfig

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
    images_dir = tmp_path / "data" / "assets" / "images"
    loop._assets_images_dir = lambda: images_dir  # type: ignore[assignment]
    return loop, world, images_dir


def test_loop_reads_the_cap_from_config(tmp_path):
    loop, _, _ = _loop(tmp_path, _params(paid_backstop_max_per_run=7))
    assert loop._image_paid_backstop_max() == 7


def test_loop_threads_the_cap_into_build_provider(tmp_path, monkeypatch):
    import petridish.engine.loop as loop_mod
    seen = {}

    class _NoneProvider:
        async def fetch_png(self, prompt):
            return None

    def _fake_build(paid_backstop_max_per_run=None):
        seen["cap"] = paid_backstop_max_per_run
        return _NoneProvider()

    monkeypatch.setattr(loop_mod, "build_provider", _fake_build)
    loop, world, _ = _loop(tmp_path, _params(paid_backstop_max_per_run=7))
    world.action_create_image(world.agents["agent_ada"], "art")

    async def _go():
        loop._drain_image_fetches()
        for task in list(loop._image_fetch_tasks):
            await task

    asyncio.run(_go())
    assert seen == {"cap": 7}


class _MissProvider:
    """Every lane misses (the capped-out shape) — fetch_png is None."""

    async def fetch_png(self, prompt):
        return None


def _drain(loop):
    async def _go():
        loop._drain_image_fetches()
        for task in list(loop._image_fetch_tasks):
            await task
    asyncio.run(_go())


def test_repaint_keeps_the_existing_artwork_when_every_lane_misses(tmp_path):
    loop, world, images_dir = _loop(tmp_path, _params())
    ada = world.agents["agent_ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)

    # First paint: the (conftest-mocked) provider serves — PNG lands.
    first = world.action_paint_surface(ada, "b1", "v1")["payload"]["image_id"]
    _drain(loop)
    first_png = images_dir / f"{first}.png"
    assert first_png.exists()

    # Repaint with EVERY lane missing (e.g. free lanes down + paid cap spent).
    loop._image_provider = _MissProvider()
    second = world.action_paint_surface(ada, "b1", "v2")["payload"]["image_id"]
    assert second != first
    _drain(loop)

    # The facade keeps art: the new image id serves the PREVIOUS bytes.
    second_png = images_dir / f"{second}.png"
    assert second_png.exists()
    assert second_png.read_bytes() == first_png.read_bytes()
    # And the decal mapping points at the new id (sim state untouched by I/O).
    assert world.surface_decals == {"b1": second}


class _MustNotFetch:
    """A provider the load-shed drop paths must NEVER reach."""

    async def fetch_png(self, prompt):
        raise AssertionError("a dropped fetch must not reach the provider")


def _paint_first_mural(loop, world, images_dir):
    """First paint via the conftest-mocked provider → its PNG lands on disk."""
    ada = world.agents["agent_ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)
    first = world.action_paint_surface(ada, "b1", "v1")["payload"]["image_id"]
    _drain(loop)
    first_png = images_dir / f"{first}.png"
    assert first_png.exists()
    return ada, first_png


def test_repaint_dropped_at_drain_under_load_keeps_existing_artwork(tmp_path):
    """Load-shed path 1: the semaphore is already saturated when the drain
    runs — the repaint entry is dropped WITHOUT spawning a task, and the
    facade still keeps the previous artwork."""
    loop, world, images_dir = _loop(tmp_path, _params())
    ada, first_png = _paint_first_mural(loop, world, images_dir)

    loop._image_provider = _MustNotFetch()
    second = world.action_paint_surface(ada, "b1", "v2")["payload"]["image_id"]

    async def _go():
        loop._image_semaphore = asyncio.Semaphore(1)
        await loop._image_semaphore.acquire()  # saturate: drain load-sheds
        loop._drain_image_fetches()
        assert loop._image_fetch_tasks == set()  # dropped — never spawned

    asyncio.run(_go())
    second_png = images_dir / f"{second}.png"
    assert second_png.exists()
    assert second_png.read_bytes() == first_png.read_bytes()


def test_repaint_dropped_by_semaphore_race_keeps_existing_artwork(tmp_path):
    """Load-shed path 2: the semaphore was FREE at drain (the task WAS
    created) but filled before the task ran — the spawned fetch must also
    fall back to keeping the current image instead of silently dropping."""
    loop, world, images_dir = _loop(tmp_path, _params())
    ada, first_png = _paint_first_mural(loop, world, images_dir)

    loop._image_provider = _MustNotFetch()
    second = world.action_paint_surface(ada, "b1", "v2")["payload"]["image_id"]

    async def _go():
        loop._image_semaphore = asyncio.Semaphore(1)
        loop._drain_image_fetches()  # sem free → the task is created
        assert len(loop._image_fetch_tasks) == 1
        # Semaphore.acquire on a free semaphore never yields, so the sem fills
        # BEFORE the spawned task gets its first slice — the exact race.
        await loop._image_semaphore.acquire()
        for task in list(loop._image_fetch_tasks):
            await task

    asyncio.run(_go())
    second_png = images_dir / f"{second}.png"
    assert second_png.exists()
    assert second_png.read_bytes() == first_png.read_bytes()


def test_fresh_paint_dropped_under_load_stays_absent(tmp_path):
    """A load-shed FRESH paint (no prev mural) still renders a clean facade —
    the drop paths never invent a PNG."""
    loop, world, images_dir = _loop(tmp_path, _params())
    ada = world.agents["agent_ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)
    loop._image_provider = _MustNotFetch()
    image_id = world.action_paint_surface(ada, "b1", "v1")["payload"]["image_id"]

    async def _go():
        loop._image_semaphore = asyncio.Semaphore(1)
        await loop._image_semaphore.acquire()
        loop._drain_image_fetches()

    asyncio.run(_go())
    assert not (images_dir / f"{image_id}.png").exists()


def test_fresh_paint_miss_stays_absent_clean_facade(tmp_path):
    loop, world, images_dir = _loop(tmp_path, _params())
    ada = world.agents["agent_ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)
    loop._image_provider = _MissProvider()
    image_id = world.action_paint_surface(ada, "b1", "v1")["payload"]["image_id"]
    _drain(loop)
    # No previous mural to keep — the PNG is simply absent (frontend fallback).
    assert not (images_dir / f"{image_id}.png").exists()


def test_repaint_miss_with_missing_prev_png_is_a_silent_noop(tmp_path):
    loop, world, images_dir = _loop(tmp_path, _params())
    ada = world.agents["agent_ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)
    loop._image_provider = _MissProvider()
    world.action_paint_surface(ada, "b1", "v1")   # miss — no PNG written
    _drain(loop)
    second = world.action_paint_surface(ada, "b1", "v2")["payload"]["image_id"]
    _drain(loop)  # prev annotated but its PNG never existed → clean no-op
    assert not (images_dir / f"{second}.png").exists()


def test_reset_rearms_the_per_run_provider(tmp_path):
    from petridish.config.loader import WorldConfig
    loop, world, _ = _loop(tmp_path, _params())
    loop._image_provider = _MissProvider()  # pretend a spent per-run budget

    async def _go():
        await loop.reset(WorldConfig(
            world=world.params, places=[], agents=[], animals=[]))

    asyncio.run(_go())
    # The provider is dropped on reset — rebuilt lazily with a FRESH budget.
    assert loop._image_provider is None


# ── world seam — prev_image_id rides the transient outbox only ───────────────

def test_paint_surface_annotates_prev_image_id_only_on_repaint():
    params = _params()
    world = World(
        params=params,
        places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentState(id="ada", name="Ada", personality="", profile="mock",
                           location="plaza", energy=80, credits=20)])
    ada = world.agents["ada"]
    world.buildings["b1"] = Building(
        id="b1", name="Wall", kind="workshop", location="plaza",
        status="operational", owner_id="public", health=100)

    first = world.action_paint_surface(ada, "b1", "v1")["payload"]["image_id"]
    assert "prev_image_id" not in world.pending_image_fetches[-1]

    second = world.action_paint_surface(ada, "b1", "v2")["payload"]["image_id"]
    entry = world.pending_image_fetches[-1]
    assert entry["image_id"] == second
    assert entry["prev_image_id"] == first

    # create_image never carries it (no surface, nothing to keep).
    world.action_create_image(ada, "free art")
    assert "prev_image_id" not in world.pending_image_fetches[-1]

    # The outbox is transient: the snapshot surface is untouched by the key.
    assert "pending_image_fetches" not in world.to_snapshot()

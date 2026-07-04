"""W29 QE adversarial probes — cross-lane interactions no single fix lane owned.

These are NOT re-runs of the lane regression tests. Each probe stresses a seam
where two W29 fixes MEET (a fork carrying both a serialized xp ledger and a
decaying crime counter; a warm faces-cache riding a snapshot; a repeated no-op
lesson at the contribution economy; the provider write-guard feeding the loop's
disk writer). Written by the QE gate agent, hermetic, no network, no git.

Findings exercised: EM-155 (determinism) × EM-275 (crime-decay fork gate) ×
EM-288 (partial-xp serialization); EM-295 (planar_faces cache under a direct
graph splice); EM-272 (teach no-op contribution farming); EM-287 / EM-296
(image write-guard + SSRF) end-to-end into the loop write site.
"""
from __future__ import annotations

import base64
import copy
import json

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SkillsParams, ModelProfile
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ══════════════════════════════════════════════════════════════════════════════
# Shared harness
# ══════════════════════════════════════════════════════════════════════════════

def _params():
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.skills = SkillsParams(library={}, archetypes={},
                            xp_per_use=10, xp_per_level=30, max_level=5)
    return p


def _fresh_world():
    """A crook whose notoriety DECAYS each round (EM-240/EM-275 surface) plus a
    learner ACCRUING partial xp (EM-227/EM-288 surface) — so a mid-run snapshot
    carries BOTH a non-empty `_skill_xp` ledger AND a live crime counter."""
    crook = AgentState(id="crook", name="Crook", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20, notoriety=50)
    learner = AgentState(id="learner", name="Learner", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20)
    return World(params=_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=[crook, learner])


def _loop_for(world):
    router = Router([ModelProfile(name="mock", adapter="mock", model_id="mock",
                                  color="#2ecc71")],
                    adapter_overrides={"mock": MockProvider()})
    for aid in world.agents:
        router.reassign(aid, "mock")
    router.inject_world(world)
    runtime = AgentRuntime(world, router)
    loop = TickLoop(world=world, runtime=runtime, repo=SQLiteRepository(":memory:"),
                    router=router, broadcaster=lambda _m: None)
    return loop


def _snap_bytes(world) -> str:
    """Canonical byte-image of a world snapshot (sorted keys — the replay surface)."""
    return json.dumps(world.to_snapshot(), sort_keys=True, default=str)


def _advance_round(world, loop, r, xp_each=10):
    """One round: grant partial xp, then run the loop's once-per-round hook (which
    fires EM-240 advance_crime → notoriety decay) — the two W29-fixed mechanisms."""
    world.round = r
    world.tick = r * 3
    world.grant_skill_xp(world.agents["learner"], "building", xp_each)
    loop._advance_round_buildings()


# ══════════════════════════════════════════════════════════════════════════════
# PROBE 1 — EM-155 fork/replay byte-identity with BOTH new serialized states
# ══════════════════════════════════════════════════════════════════════════════

class TestProbe1ForkByteIdentity:
    """A fork taken mid-run — where the snapshot carries a non-empty partial-xp
    ledger (EM-288) AND a mid-decay crime counter (EM-275) — must resume to
    snapshots byte-identical to the continuous run at the same rounds."""

    FORK_AT = 2   # ledger = 20 xp (level 0, non-empty), notoriety = 46 (decaying)
    LAST = 5

    def _continuous(self):
        world = _fresh_world()
        loop = _loop_for(world)
        snaps = {}
        for r in range(1, self.LAST + 1):
            _advance_round(world, loop, r)
            snaps[r] = _snap_bytes(world)
        return world, snaps

    def test_fork_snapshot_carries_both_states(self):
        world = _fresh_world()
        loop = _loop_for(world)
        for r in range(1, self.FORK_AT + 1):
            _advance_round(world, loop, r)
        snap = world.to_snapshot()
        # BOTH surfaces are live at the fork boundary (the whole point of the probe).
        assert snap["skill_xp"] == {"learner": {"building": 20}}
        assert world.agents["crook"].notoriety == 46   # 50 - 2*2, still decaying

    def test_resumed_run_is_byte_identical_to_continuous(self):
        _cont_world, cont = self._continuous()

        # Fork: replay to FORK_AT, snapshot, restore into a FRESH world+loop.
        fworld = _fresh_world()
        floop = _loop_for(fworld)
        for r in range(1, self.FORK_AT + 1):
            _advance_round(fworld, floop, r)
        fork_snap = fworld.to_snapshot()

        rworld = World.from_snapshot(copy.deepcopy(fork_snap), params=_params())
        rloop = _loop_for(rworld)
        # EM-275 re-entry: the resumed loop runs its once-per-round hook at the
        # ALREADY-advanced round before the round increments. With the fix this is
        # a no-op (_last_building_round derived == world.round); pre-fix it fired an
        # extra decay pass here.
        assert rloop._last_building_round == self.FORK_AT
        rloop._advance_round_buildings()

        resumed = {}
        for r in range(self.FORK_AT + 1, self.LAST + 1):
            _advance_round(rworld, rloop, r)
            resumed[r] = _snap_bytes(rworld)

        for r in range(self.FORK_AT + 1, self.LAST + 1):
            assert resumed[r] == cont[r], f"fork diverged from continuous at round {r}"

    def test_probe_has_teeth_stale_last_round_diverges(self):
        """Prove the probe would CATCH the pre-fix bug: forcing the stale flat-0
        `_last_building_round` re-introduces the extra decay pass and the resumed
        snapshot diverges from the continuous one."""
        _cont_world, cont = self._continuous()

        fworld = _fresh_world()
        floop = _loop_for(fworld)
        for r in range(1, self.FORK_AT + 1):
            _advance_round(fworld, floop, r)
        rworld = World.from_snapshot(copy.deepcopy(fworld.to_snapshot()), params=_params())
        rloop = _loop_for(rworld)
        rloop._last_building_round = 0          # simulate the pre-EM-275 regression
        rloop._advance_round_buildings()        # fires an EXTRA notoriety decay
        for r in range(self.FORK_AT + 1, self.LAST + 1):
            _advance_round(rworld, rloop, r)
        assert _snap_bytes(rworld) != cont[self.LAST]

    def test_two_continuous_runs_are_identical_determinism_control(self):
        # Sanity: to_snapshot is a pure function of state (no clock/uuid leak), so
        # a real fork divergence can't be blamed on incidental nondeterminism.
        _w1, a = self._continuous()
        _w2, b = self._continuous()
        assert a == b


# ══════════════════════════════════════════════════════════════════════════════
# PROBE 2 — EM-295 faces cache under a DIRECT graph splice + snapshot hygiene
# ══════════════════════════════════════════════════════════════════════════════

from petridish.engine.citygraph import (  # noqa: E402
    CityGraph, CityNode, CityEdge, classic_grid,
    planar_faces, _planar_faces_uncached,
)


def _faces_key(faces):
    return [(f.boundary, f.poly, f.centroid, f.area) for f in faces]


class TestProbe2FacesCacheSplice:
    """world.step_master_plan_morph mutates graph.nodes / graph.edges DIRECTLY
    (append + whole-list reassignment), NOT through add/demolish helpers. The
    signature-keyed cache must self-invalidate on those splices, and the cache
    object must never ride a snapshot."""

    def test_whole_list_reassignment_invalidates_cache(self):
        # The morph's `self.city_graph.edges = [e for e in ... if e.id not in rm]`
        # shape: a NEW list object, edge removed. (Distinct from the lane test,
        # which uses apply_demolish_road / an in-place coord nudge.)
        g = classic_grid(1337)
        warm = planar_faces(g)                       # populate the cache
        assert planar_faces(g) is warm               # hit
        drop_id = g.edges[0].id
        g.edges = [e for e in g.edges if e.id != drop_id]   # direct splice
        after = planar_faces(g)
        assert after is not warm                     # invalidated, recomputed
        assert _faces_key(after) == _faces_key(_planar_faces_uncached(g))

    def test_append_splice_invalidates_cache(self):
        # The morph's `self.city_graph.nodes.append(...)` / `.edges.append(...)`.
        g = classic_grid(1337)
        _ = planar_faces(g)
        g.nodes.append(CityNode(id="probe:n", x=999.0, z=999.0, kind="junction"))
        g.edges.append(CityEdge(id="probe:e", a=g.nodes[0].id, b="probe:n"))
        after = planar_faces(g)
        assert _faces_key(after) == _faces_key(_planar_faces_uncached(g))

    def test_interleaved_splices_never_serve_stale(self):
        # Hammer the cache: alternate remove / re-add and confirm every read is
        # fresh (a signature collision would surface here as a stale face list).
        g = classic_grid(1337)
        e = g.edges[3]
        saved = CityEdge(id=e.id, a=e.a, b=e.b)
        for _ in range(4):
            g.edges = [x for x in g.edges if x.id != saved.id]
            assert _faces_key(planar_faces(g)) == _faces_key(_planar_faces_uncached(g))
            g.edges = g.edges + [CityEdge(id=saved.id, a=saved.a, b=saved.b)]
            assert _faces_key(planar_faces(g)) == _faces_key(_planar_faces_uncached(g))

    def test_warm_cache_snapshot_is_byte_identical_to_cold_graph_todict(self):
        cold = classic_grid(1337)
        cold_bytes = json.dumps(cold.to_dict(), sort_keys=True)
        warm = classic_grid(1337)
        _ = planar_faces(warm)                       # attach _faces_cache
        assert getattr(warm, "_faces_cache", None) is not None
        warm_bytes = json.dumps(warm.to_dict(), sort_keys=True)
        assert warm_bytes == cold_bytes
        assert "_faces_cache" not in warm_bytes

    def test_warm_cache_never_leaks_into_world_snapshot(self):
        world = _fresh_world()
        world.city_graph = classic_grid(1337)
        cold = _snap_bytes(world)
        _ = planar_faces(world.city_graph)           # warm the graph's cache
        warm = _snap_bytes(world)
        assert warm == cold
        assert "_faces_cache" not in warm


# ══════════════════════════════════════════════════════════════════════════════
# PROBE 4 — EM-272 teach no-op contribution farming (the economy exploit)
# ══════════════════════════════════════════════════════════════════════════════

_TEACH_LIBRARY = {"building": {"gates": ["build_step"], "min_level": 1}}


def _teach_params():
    p = _params()
    p.skills = SkillsParams(library=copy.deepcopy(_TEACH_LIBRARY), archetypes={},
                            xp_per_use=10, xp_per_level=30, max_level=5)
    return p


def _teach_world():
    teacher = AgentState(id="t", name="Teach", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20,
                         skills={"building": 2})
    student = AgentState(id="s", name="Stud", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20,
                         skills={"building": 1})     # exactly +1 below → nothing to give
    return World(params=_teach_params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=[teacher, student])


class TestProbe4TeachEconomy:
    def test_repeated_plus_one_lessons_farm_zero_contribution(self):
        w = _teach_world()
        t, s = w.agents["t"], w.agents["s"]
        for _ in range(50):                          # loop the exploit hard
            evt = w.teach_skill_event(t, s, "building")
            assert evt["kind"] == "teach_failed"     # the agent SEES the failure
        # No contribution accrued, no score, no level moved — the farm is dead.
        assert t.contributions.get("skill_taught", 0) == 0
        assert w.contribution_score(t) == 0
        assert s.skill_level("building") == 1

    def test_failure_reason_reaches_the_agent(self):
        w = _teach_world()
        evt = w.teach_skill_event(w.agents["t"], w.agents["s"], "building")
        # teach_skill_event is exactly what runtime._dispatch calls for teach_skill;
        # the teach_failed event (with its reason text) is the action result the
        # agent perceives — ok=False propagates, not a silent success.
        assert evt["kind"] == "teach_failed"
        assert "error" in evt["payload"]
        assert evt["payload"]["error"]               # a non-empty reason string

    def test_no_op_leaves_no_side_effects(self):
        w = _teach_world()
        t, s = w.agents["t"], w.agents["s"]
        w.pending_skill_requests[t.id] = {"asker_id": s.id, "skill": "building", "tick": 0}
        before_credits = (t.credits, s.credits)
        w.teach_skill_event(t, s, "building")
        assert t.id in w.pending_skill_requests       # request NOT consumed
        assert s.id not in t.relationships            # no trust edge warmed
        assert (t.credits, s.credits) == before_credits


# ══════════════════════════════════════════════════════════════════════════════
# PROBE 5 — EM-287 / EM-296: provider write-guard + SSRF, END-TO-END to disk
# ══════════════════════════════════════════════════════════════════════════════

import petridish.imagegen.provider as provider_mod  # noqa: E402
from petridish.imagegen.provider import (  # noqa: E402
    FreellmapiImageProvider, MockImageProvider, _MOCK_PNG, _get_url_bytes,
)


class _Resp:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload


class _FakeAsyncClient:
    handler = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return _FakeAsyncClient.handler("POST", url, **kw)

    async def get(self, url, **kw):
        return _FakeAsyncClient.handler("GET", url, **kw)


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    _FakeAsyncClient.handler = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    return _FakeAsyncClient


def _resolve_to(monkeypatch, mapping):
    def _fake(host):
        if host in mapping:
            return mapping[host]
        if "*" in mapping:
            return mapping["*"]
        raise OSError(f"unresolved {host}")
    monkeypatch.setattr(provider_mod, "_resolve_ips", _fake)


class TestProbe5ProviderBypass:
    """Hunt for a non-image / oversized / SSRF payload that reaches the .png disk
    writer via the URL shape (the lane tests cover the b64 shape + single-hop
    redirects; these push the url path and a multi-hop redirect chain)."""

    async def test_url_shape_oversized_payload_rejected(self, fake_httpx, monkeypatch):
        _resolve_to(monkeypatch, {"cdn.evil.test": ["93.184.216.34"]})
        monkeypatch.setattr(provider_mod, "_MAX_IMAGE_BYTES", 16)
        big = b"\x89PNG\r\n\x1a\n" + b"\x00" * 4096   # valid magic, way over the cap

        def handler(method, url, **kw):
            if method == "POST":
                return _Resp(200, payload={"data": [{"url": "https://cdn.evil.test/x.png"}]})
            return _Resp(200, content=big)

        fake_httpx.handler = handler
        got = await FreellmapiImageProvider("http://localhost:3001/v1", "k").fetch_png("p")
        assert got is None                            # never handed to the writer

    async def test_url_shape_non_image_payload_rejected(self, fake_httpx, monkeypatch):
        _resolve_to(monkeypatch, {"cdn.evil.test": ["93.184.216.34"]})
        html = b"<html><script>alert(1)</script></html>"

        def handler(method, url, **kw):
            if method == "POST":
                return _Resp(200, payload={"data": [{"url": "https://cdn.evil.test/x.png"}]})
            return _Resp(200, content=html)           # a stored-XSS shape served as .png

        fake_httpx.handler = handler
        got = await FreellmapiImageProvider("http://localhost:3001/v1", "k").fetch_png("p")
        assert got is None

    async def test_multi_hop_redirect_to_private_is_blocked(self, monkeypatch):
        # public → public → private(metadata). Each hop is re-validated at the top
        # of the loop, so the private target is rejected BEFORE it is fetched.
        _resolve_to(monkeypatch, {
            "h1.test": ["93.184.216.34"], "h2.test": ["93.184.216.35"],
            "metadata.internal": ["169.254.169.254"],
        })
        seen = []

        class _C:
            async def get(self, url, **kw):
                seen.append(url)
                if url == "https://h1.test/a":
                    return _Resp(302, headers={"location": "https://h2.test/b"})
                if url == "https://h2.test/b":
                    return _Resp(302, headers={"location": "http://metadata.internal/latest/"})
                return _Resp(200, content=_MOCK_PNG)  # the metadata body — must never be read

        got = await _get_url_bytes(_C(), "https://h1.test/a")
        assert got is None
        assert "http://metadata.internal/latest/" not in seen  # blocked pre-fetch

    async def test_loop_write_site_drops_bad_bytes_keeps_good(self, tmp_path, monkeypatch, fake_httpx):
        """END-TO-END: the loop's disk writer consumes ONLY validated provider
        bytes. A provider fed a non-image writes NOTHING; a valid PNG writes a
        file. Proves EM-287's guard is on the path that actually escapes to disk."""
        world = _fresh_world()
        loop = _loop_for(world)
        import asyncio
        loop._image_semaphore = asyncio.Semaphore(1)
        monkeypatch.setattr(loop, "_assets_images_dir", lambda: tmp_path)

        # (a) provider returns a non-image via the url shape ⇒ no file on disk.
        _resolve_to(monkeypatch, {"cdn.evil.test": ["93.184.216.34"]})

        def bad(method, url, **kw):
            if method == "POST":
                return _Resp(200, payload={"data": [{"url": "https://cdn.evil.test/x.png"}]})
            return _Resp(200, content=b"<svg onload=alert(1)>")

        fake_httpx.handler = bad
        loop._image_provider = FreellmapiImageProvider("http://localhost:3001/v1", "k")
        await loop._spawn_image_fetch({"image_id": "img_deadbeef01", "prompt": "p"})
        assert list(tmp_path.glob("*.png")) == []     # bad bytes never written

        # (b) a validated PNG DOES get written (the guard is not simply dropping all).
        loop._image_provider = MockImageProvider()
        await loop._spawn_image_fetch({"image_id": "img_00c0ffee01", "prompt": "p"})
        written = list(tmp_path.glob("*.png"))
        assert [p.name for p in written] == ["img_00c0ffee01.png"]
        assert written[0].read_bytes() == _MOCK_PNG

"""
W11a gate tests — run browser API (EM-086), narrator mode (EM-094), and the
exact-animal-replay payload.place (event-log.md v1.2.0 note 2).

Contracts under test:
  - api.openapi.yaml v1.3.0 — GET /api/runs (`RunRow`: newest-first, is_active
    from the LOOP-HELD run id and NEVER the stored `status` column, max_tick /
    event_count aggregates, `config_summary` as a small projection of
    runs.config_json that degrades to agents=[] on legacy blobs), plus the
    optional `run_id` query param on every read endpoint (omitted = active run;
    unknown = 404 {"detail": "unknown run"}).
  - event-log.md v1.2.0 note 1 — `narrator_summary` (OFF by default = zero LLM
    calls; enabled = at most ONE event per `every_n_ticks` window with payload
    {from_tick, to_tick, profile}, actor_type "system" / actor_id "narrator";
    a failed narrator call emits NOTHING and never stalls the loop).
  - event-log.md v1.2.0 note 2 — a MOVING `animal_action` (wander) carries the
    destination `payload.place`; non-move animal actions carry no place key.

Deterministic and offline (MockProvider / counting fakes, no network, no real
API keys); conftest pins EM_DB_PATH=':memory:' so the real-app TestClient runs
never touch the live run-history file. Harness idioms follow test_w8/test_w10.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (
    AnimalParams, AnimalSeed, ModelProfile, NarratorParams, PlaceConfig,
    WorldConfig, WorldParams,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Harness (test_w8 / test_w10 idiom)
# ──────────────────────────────────────────────────────────────────────────────

class TextMock:
    """Counting provider returning a fixed PLAIN-TEXT completion — the narrator
    path consumes prose, not a JSON action. Mirrors test_w8.CountingMock."""
    name = "narrator-mock"
    color = "#9b59b6"
    last_routed_via = "narrator-mock"
    last_usage = {"input_tokens": 9, "output_tokens": 5, "latency_ms": 1.0,
                  "finish_reason": "stop", "cached": False}

    def __init__(self, response: str = "The village dozed; nothing burned. Yet."):
        self.calls = 0
        self._response = response

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        return self._response


class RaisingMock(TextMock):
    """Narrator provider whose every call blows up — the loop must shrug."""

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        raise RuntimeError("provider exploded (scripted)")


def _profiles():
    # narrator-mock is a mock-adapter profile so profile.available() is True;
    # the override swaps in the counting/raising fake.
    return [
        ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71"),
        ModelProfile(name="narrator-mock", adapter="mock", model_id="narrator",
                     color="#9b59b6"),
    ]


def _make_params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _make_loop(params: WorldParams, *, narrator_provider=None,
               animals: list[AnimalSeed] | None = None,
               animal_provider=None):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=params.starting_energy,
                   credits=params.starting_credits),
    ]
    world = World(params=params, places=places, agents=agents)
    overrides = {"mock": MockProvider(script=[{"action": "idle", "args": {}}])}
    if narrator_provider is not None:
        overrides["narrator-mock"] = narrator_provider
    if animal_provider is not None:
        overrides["narrator-mock"] = animal_provider  # animals reuse the profile
    router = Router(_profiles(), adapter_overrides=overrides, cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    events: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: events.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[],
                              animals=animals or []))
    return loop, world, repo, events


async def _drive(loop: TickLoop, world: World, n: int) -> None:
    """Run n agent turns, draining the off-critical-path background tasks
    (animal + narrator) after each so assertions observe events deterministically."""
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)
        if loop._animal_task is not None:
            await loop._animal_task
        if loop._narrator_task is not None:
            await loop._narrator_task


# ──────────────────────────────────────────────────────────────────────────────
# 1. /api/runs — RunRow shape, ordering, is_active, aggregates, config_summary
# ──────────────────────────────────────────────────────────────────────────────

RUNROW_KEYS = {"id", "started_at", "ended_at", "status", "is_active",
               "max_tick", "event_count", "config_summary"}


def test_list_runs_shape_newest_first_and_aggregates():
    repo = SQLiteRepository(":memory:")
    r1 = repo.start_run(json.dumps({
        "world": {}, "agents": [{"name": "Ada", "profile": "mock"}],
    }))
    repo.save_event(r1, {"kind": "turn_start", "actor_id": "Ada", "payload": {}}, 0)
    repo.save_event(r1, {"kind": "agent_speech", "actor_id": "Ada", "payload": {}}, 4)
    repo.save_event(r1, {"kind": "agent_died", "actor_id": "Ada", "payload": {}}, 7)
    repo.end_run(r1)
    r2 = repo.start_run(json.dumps({"world": {"seed": 42}, "agents": []}))
    # r2 has NO events: aggregates must degrade to 0, not null/missing.

    rows = repo.list_runs(active_run_id=r2)
    assert [r["id"] for r in rows] == [r2, r1], "runs must list newest first"
    assert all(RUNROW_KEYS <= set(r.keys()) for r in rows), "RunRow keys missing"

    by_id = {r["id"]: r for r in rows}
    assert by_id[r1]["max_tick"] == 7
    assert by_id[r1]["event_count"] == 3
    assert by_id[r1]["status"] == "ended"
    assert by_id[r1]["ended_at"] is not None, "end_run must stamp ended_at (v1.3.0 migration)"
    assert by_id[r2]["max_tick"] == 0 and by_id[r2]["event_count"] == 0
    assert by_id[r2]["ended_at"] is None
    # config_summary is a projection, never the blob.
    assert by_id[r1]["config_summary"]["agents"] == [{"name": "Ada", "profile": "mock"}]
    assert "world" not in by_id[r1]["config_summary"]
    assert by_id[r2]["config_summary"]["seed"] == 42


def test_is_active_tracks_the_loop_not_the_status_column():
    """A dead run whose stored status is still 'running' (crash/hot-reload —
    EM-086 note 1) must NOT be is_active; only the loop-held run is."""
    repo = SQLiteRepository(":memory:")
    dead = repo.start_run("{}")     # status stays 'running' forever (crash)
    live = repo.start_run("{}")

    rows = {r["id"]: r for r in repo.list_runs(active_run_id=live)}
    assert rows[dead]["status"] == "running", "precondition: the lie is stored"
    assert rows[dead]["is_active"] is False, \
        "status='running' must never imply is_active (EM-086 note 1)"
    assert rows[live]["is_active"] is True

    # No loop at all (active_run_id=None): NOTHING is active.
    rows = repo.list_runs(active_run_id=None)
    assert all(r["is_active"] is False for r in rows)


def test_config_summary_legacy_and_malformed_blobs_degrade_to_empty_agents():
    repo = SQLiteRepository(":memory:")
    legacy = repo.start_run(json.dumps({"world": {"turns_per_day": 20}}))  # pre-W11a
    broken = repo.start_run("not json at all {{{")

    rows = {r["id"]: r for r in repo.list_runs()}
    assert rows[legacy]["config_summary"]["agents"] == []
    assert rows[broken]["config_summary"]["agents"] == []


def test_api_runs_endpoint_marks_only_the_live_loop_run_active():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        active = appmod._loop._run_id
        rows = client.get("/api/runs").json()
        assert rows, "lifespan init_run must persist at least the live run"
        assert [r["id"] for r in rows] == sorted((r["id"] for r in rows), reverse=True)
        assert all(RUNROW_KEYS <= set(r.keys()) for r in rows)
        assert [r["id"] for r in rows if r["is_active"]] == [active]


# ──────────────────────────────────────────────────────────────────────────────
# 2. run_id scoping on the read endpoints (omitted = active; unknown = 404)
# ──────────────────────────────────────────────────────────────────────────────

def _seed_past_run(repo: SQLiteRepository) -> int:
    """A finished run with its own events + snapshot, distinct from the live one."""
    past = repo.start_run(json.dumps({"agents": [{"name": "Old", "profile": "mock"}]}))
    repo.save_event(past, {"kind": "turn_start", "actor_id": "Old",
                           "turn_id": "turn_past", "payload": {}}, 1)
    repo.save_event(past, {"kind": "action_resolved", "actor_id": "Old",
                           "turn_id": "turn_past",
                           "payload": {"outcome": "ok", "state_deltas": {}}}, 1)
    repo.save_event(past, {"kind": "agent_speech", "actor_id": "Old",
                           "text": "echo from the past", "payload": {}}, 2)
    repo.save_world_snapshot(past, 1, json.dumps({"tick": 1, "marker": "past-run"}))
    repo.end_run(past)
    return past


def test_run_id_scopes_events_snapshots_and_replay_to_that_run():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        repo = appmod._repo
        active = appmod._loop._run_id
        past = _seed_past_run(repo)
        repo.save_event(active, {"kind": "agent_speech", "actor_id": "agent_now",
                                 "text": "live row", "payload": {}}, 0)

        # events?run_id=past → THAT run's rows only.
        rows = client.get(f"/api/events?run_id={past}").json()
        assert rows and all(r["run_id"] == past for r in rows)
        assert {r["kind"] for r in rows} == {"turn_start", "action_resolved",
                                             "agent_speech"}

        # Omitted run_id = the active run (pre-W11a behavior, byte-identical).
        rows = client.get("/api/events?kinds=agent_speech").json()
        assert rows and all(r["run_id"] == active for r in rows)
        assert all(r["text"] != "echo from the past" for r in rows)

        # Turn trace scoped to the past run; same turn_id finds nothing live.
        chain = client.get(f"/api/turns/turn_past?run_id={past}").json()
        assert [e["kind"] for e in chain] == ["turn_start", "action_resolved"]
        assert client.get("/api/turns/turn_past").json() == []

        # Snapshots: the past run's own tick list, not the live run's.
        assert client.get(f"/api/snapshots?run_id={past}").json() == [{"tick": 1}]
        live_snaps = client.get("/api/snapshots").json()
        assert {"tick": 0} in live_snaps  # init_run's tick-0 snapshot

        # Replay: base = the past run's snapshot state_json (EM-086 note 2 —
        # geometry from the snapshot, never the live-owned places table), and
        # the fold delta is strictly-left scoped to that run.
        replay = client.get(f"/api/replay?tick=2&run_id={past}").json()
        assert replay["base"]["tick"] == 1
        assert replay["base"]["state"]["marker"] == "past-run"
        assert [e["kind"] for e in replay["events"]] == ["agent_speech"]
        assert all(e["run_id"] == past for e in replay["events"])


@pytest.mark.parametrize("path", [
    "/api/events",
    "/api/turns/some_turn",
    "/api/rules/history",
    "/api/relationships",
    "/api/snapshots",
    "/api/replay?tick=0",
    "/api/analytics",
])
def test_unknown_run_id_is_404_on_every_read_endpoint(path):
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        sep = "&" if "?" in path else "?"
        resp = client.get(f"{path}{sep}run_id=999999")
        assert resp.status_code == 404, f"{path}: {resp.status_code} != 404"
        assert resp.json() == {"detail": "unknown run"}


# ──────────────────────────────────────────────────────────────────────────────
# 3. Narrator mode (EM-094, event-log.md v1.2.0 note 1)
# ──────────────────────────────────────────────────────────────────────────────

def test_narrator_disabled_by_default_zero_events_zero_calls():
    """Default config (no narrator block): N ticks emit no narrator_summary and
    make ZERO calls on the would-be narrator provider (off-path = zero cost)."""
    counting = TextMock()
    params = _make_params()  # NarratorParams() default: enabled=False
    assert params.narrator.enabled is False, "narrator must default OFF"
    loop, world, repo, events = _make_loop(params, narrator_provider=counting)

    asyncio.run(_drive(loop, world, 12))

    assert counting.calls == 0, "disabled narrator must make zero provider calls"
    assert repo.get_events(loop._run_id, kinds=["narrator_summary"]) == []
    assert not [e for e in events if e.get("kind") == "narrator_summary"]


def test_narrator_enabled_emits_exactly_one_summary_per_window():
    counting = TextMock("Ada idled through three quiet days; the plaza endured.")
    params = _make_params(narrator=NarratorParams(
        enabled=True, every_n_ticks=3, model_profile="narrator-mock"))
    loop, world, repo, _ = _make_loop(params, narrator_provider=counting)

    # Ticks 0..8 → exactly two aligned windows fire (tick 3 and tick 6).
    asyncio.run(_drive(loop, world, 9))

    rows = repo.get_events(loop._run_id, kinds=["narrator_summary"], order="asc")
    assert len(rows) == 2, f"expected one summary per window, got {len(rows)}"
    assert counting.calls == 2, "exactly ONE LLM call per emitted window"
    for row in rows:
        assert row["actor_type"] == "system"
        assert row["actor_id"] == "narrator"
        assert row["profile"] == "narrator-mock"
        assert row["text"] == "Ada idled through three quiet days; the plaza endured."
        assert row["turn_id"] is None, "a concurrent system task must not inherit a turn_id"
    # Contract payload {from_tick, to_tick, profile} — consecutive windows.
    assert [(r["payload"]["from_tick"], r["payload"]["to_tick"]) for r in rows] == \
        [(0, 3), (3, 6)]
    assert all(r["payload"]["profile"] == "narrator-mock" for r in rows)


def test_narrator_provider_failure_emits_nothing_and_loop_keeps_ticking():
    raising = RaisingMock()
    params = _make_params(narrator=NarratorParams(
        enabled=True, every_n_ticks=2, model_profile="narrator-mock"))
    loop, world, repo, _ = _make_loop(params, narrator_provider=raising)

    asyncio.run(_drive(loop, world, 7))  # windows at ticks 2, 4, 6 all fail

    assert raising.calls == 3, "each window tried once (no retry, no queueing)"
    assert repo.get_events(loop._run_id, kinds=["narrator_summary"]) == [], \
        "a failed narrator call must emit NOTHING"
    assert world.tick == 7, "the loop must keep ticking through narrator failures"
    # And the next turn still runs cleanly (nothing latched/stalled).
    asyncio.run(_drive(loop, world, 1))
    assert world.tick == 8


def test_narrator_unavailable_profile_makes_zero_calls():
    """Free-scale guarantee: enabled but pointing at a missing profile = skip."""
    counting = TextMock()
    params = _make_params(narrator=NarratorParams(
        enabled=True, every_n_ticks=2, model_profile="no-such-profile"))
    loop, world, repo, _ = _make_loop(params, narrator_provider=counting)

    asyncio.run(_drive(loop, world, 6))

    assert counting.calls == 0
    assert repo.get_events(loop._run_id, kinds=["narrator_summary"]) == []


def test_chronicle_backfill_chronicles_existing_history():
    """EM-201 — build_chronicle_from_history backfills one chapter per
    un-chronicled window over the EXISTING run, and is idempotent."""
    params = _make_params(narrator=NarratorParams(
        model_profile="narrator-mock", every_n_ticks=2))  # enabled False ⇒ no auto
    tm = TextMock("A chapter of the saga.")
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 6))  # advance the run; no auto-chapters fire
    assert world.tick == 6
    assert repo.get_events(loop._run_id, kinds=["narrator_summary"]) == []

    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=2))
    rows = repo.get_events(loop._run_id, kinds=["narrator_summary"], order="asc")
    assert tm.calls == 3, "one LLM call per generated chapter"
    windows = [(r["payload"]["from_tick"], r["payload"]["to_tick"]) for r in rows]
    assert windows == [(0, 2), (2, 4), (4, 6)]

    # idempotent — a second build skips windows already chronicled.
    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=2))
    assert len(repo.get_events(loop._run_id, kinds=["narrator_summary"])) == 3


def test_chronicle_backfill_unknown_model_is_a_noop():
    """The picker never forces a paid lane: an unknown/unconfigured model does
    nothing (the API maps this to a 400; the engine is a clean no-op)."""
    params = _make_params(narrator=NarratorParams(model_profile="narrator-mock"))
    tm = TextMock()
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 4))
    asyncio.run(loop.build_chronicle_from_history("no-such-profile", every=2))
    assert tm.calls == 0
    assert repo.get_events(loop._run_id, kinds=["narrator_summary"]) == []


def test_chronicle_rebuild_regenerates_already_chronicled_windows():
    """EM-201 follow-on — rebuild=True does NOT skip already-chronicled windows:
    it regenerates EVERY window 0→now (fresh prose + fresh stamps)."""
    from petridish.engine.loop import CHRONICLER_VERSION

    params = _make_params(narrator=NarratorParams(
        model_profile="narrator-mock", every_n_ticks=2))  # enabled False ⇒ no auto
    tm = TextMock("A chapter of the saga.")
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 6))
    assert world.tick == 6

    # First build chronicles all three windows.
    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=2))
    assert tm.calls == 3
    first = repo.get_events(loop._run_id, kinds=["narrator_summary"], order="asc")
    assert [(r["payload"]["from_tick"], r["payload"]["to_tick"]) for r in first] == \
        [(0, 2), (2, 4), (4, 6)]

    # A plain (non-rebuild) build skips every window — they're all chronicled.
    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=2))
    assert tm.calls == 3, "non-rebuild must skip already-chronicled windows"

    # rebuild=True regenerates ALL of them again (3 more calls, 3 more rows).
    asyncio.run(loop.build_chronicle_from_history(
        "narrator-mock", every=2, rebuild=True))
    assert tm.calls == 6, "rebuild must NOT skip — every window regenerated"
    after = repo.get_events(loop._run_id, kinds=["narrator_summary"], order="asc")
    assert len(after) == 6, "rebuild appends fresh chapters for every window"
    # Every emitted chapter carries the server-computed facts + version stamp.
    for r in after:
        payload = r["payload"]
        assert payload["chronicler_version"] == CHRONICLER_VERSION
        chaos = payload["chaos"]
        assert set(chaos.keys()) == {
            "cast", "quotes", "laws", "conflicts", "deaths", "counts"}
        assert set(chaos["counts"].keys()) == {
            "spoken", "laws", "clashes", "deaths"}


def test_chronicle_chapter_payload_carries_chaos_and_version():
    """EM-201 follow-on — a generated chapter STAMPS the server-computed `chaos`
    facts (cast/quotes/laws/conflicts/deaths/counts) and chronicler_version, with
    real counts drawn from the window's events (not an all-zero reconstruction)."""
    from petridish.engine.loop import CHRONICLER_VERSION

    params = _make_params(narrator=NarratorParams(
        model_profile="narrator-mock", every_n_ticks=10))  # enabled False ⇒ no auto
    tm = TextMock("The town schemed and a law passed.")
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 8))  # advance the run so a window exists
    assert world.tick == 8

    # Seed the window [0,8] with real drama the facts must surface.
    run_id = loop._run_id
    repo.save_event(run_id, {"kind": "agent_speech", "actor_id": "agent_ada",
                             "text": 'Ada says: "We must build the dividend engine now."',
                             "payload": {"said": "We must build the dividend engine now."}}, 3)
    repo.save_event(run_id, {"kind": "rule_passed", "actor_id": "system",
                             "text": "By vote, a UBI of 10 credits passes.",
                             "payload": {}}, 5)
    repo.save_event(run_id, {"kind": "conflict", "actor_id": "system",
                             "text": "Bram insults Ada!", "payload": {}}, 6)

    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=10))

    rows = repo.get_events(run_id, kinds=["narrator_summary"], order="asc")
    assert rows, "a chapter must have been generated for the window"
    payload = rows[0]["payload"]
    assert payload["chronicler_version"] == CHRONICLER_VERSION
    chaos = payload["chaos"]
    assert chaos["counts"]["spoken"] == 1
    assert chaos["counts"]["laws"] == 1
    assert chaos["counts"]["clashes"] == 1
    assert chaos["counts"]["deaths"] == 0
    assert "Ada" in chaos["cast"]
    assert any("dividend engine" in q["said"] for q in chaos["quotes"])
    assert chaos["quotes"][0]["speaker"] == "Ada"
    assert any("UBI" in law for law in chaos["laws"])
    assert any("insults" in c for c in chaos["conflicts"])


def test_chronicle_restamp_keeps_prose_adds_facts_and_fills_gaps():
    """EM-201 follow-on — restamp_chronicle: an OLD v1 chapter is re-emitted with
    its ORIGINAL prose + re-derived chaos + version (NO LLM call); a true GAP is
    narrated fresh; a window already carrying a v2 chapter is skipped entirely."""
    from petridish.engine.loop import CHRONICLER_VERSION

    params = _make_params(narrator=NarratorParams(
        model_profile="narrator-mock", every_n_ticks=2))  # enabled False ⇒ no auto
    tm = TextMock("Freshly narrated gap chapter.")
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 6))  # windows (0,2) (2,4) (4,6)
    run_id = loop._run_id

    # (0,2): an OLD v1 chapter (NO chronicler_version) + real drama to surface.
    repo.save_event(run_id, {"kind": "agent_speech", "actor_id": "agent_ada",
                             "text": 'Ada says: "The cabal walks among us."',
                             "payload": {"said": "The cabal walks among us."}}, 1)
    repo.save_event(run_id, {"kind": "narrator_summary", "actor_id": "narrator",
                             "actor_type": "system", "profile": "deepseek-pro",
                             "text": "The original gorgeous prose of window 0-2.",
                             "payload": {"from_tick": 0, "to_tick": 2,
                                         "profile": "deepseek-pro"}}, 2)  # v1: no version
    # (2,4): already a v2 chapter — must be SKIPPED (not re-emitted).
    repo.save_event(run_id, {"kind": "narrator_summary", "actor_id": "narrator",
                             "actor_type": "system", "profile": "auto",
                             "text": "Already a v2 chapter for 2-4.",
                             "payload": {"from_tick": 2, "to_tick": 4, "profile": "auto",
                                         "chronicler_version": CHRONICLER_VERSION,
                                         "chaos": {"cast": [], "quotes": [], "laws": [],
                                                   "conflicts": [], "deaths": [],
                                                   "counts": {"spoken": 0, "laws": 0,
                                                              "clashes": 0, "deaths": 0}}}}, 3)
    # (4,6): NO chapter → a true gap.

    asyncio.run(loop.restamp_chronicle("narrator-mock", every=2))

    # Only the GAP window made an LLM call.
    assert tm.calls == 1, "only the true gap is narrated; v1 restamped no-LLM; v2 skipped"

    rows = repo.get_events(run_id, kinds=["narrator_summary"], order="asc")

    def latest(ft, tt):
        ms = [r for r in rows if r["payload"].get("from_tick") == ft
              and r["payload"].get("to_tick") == tt]
        return ms[-1] if ms else None

    # (0,2) restamped: SAME prose, now with version + re-derived chaos, marked restamped,
    # original attribution preserved.
    r02 = latest(0, 2)
    assert r02["text"] == "The original gorgeous prose of window 0-2.", "prose preserved"
    assert r02["payload"]["chronicler_version"] == CHRONICLER_VERSION
    assert r02["payload"].get("restamped") is True
    assert r02["payload"]["profile"] == "deepseek-pro", "original attribution kept"
    assert r02["payload"]["chaos"]["counts"]["spoken"] == 1, "facts re-derived from DB"
    assert "Ada" in r02["payload"]["chaos"]["cast"]

    # (2,4) v2 skipped — still exactly one row.
    rows24 = [r for r in rows if r["payload"].get("from_tick") == 2
              and r["payload"].get("to_tick") == 4]
    assert len(rows24) == 1, "an already-v2 window is not re-emitted"

    # (4,6) gap narrated fresh, stamped v2.
    r46 = latest(4, 6)
    assert r46 is not None and r46["payload"]["chronicler_version"] == CHRONICLER_VERSION
    assert r46["text"] == "Freshly narrated gap chapter."


def test_chronicle_chaos_counts_include_commitment_lapsed_through_query():
    """EM-201 follow-on — a commitment_lapsed event IS a clash. It must survive the
    _NARRATOR_DIGEST_KINDS whitelist used by the real get_events query so the
    server-stamped chaos.counts.clashes / chaos.conflicts[] match the frontend's
    full-history reconstruction. This exercises the QUERY boundary (where rows are
    dropped), not just the pure facts builder."""
    params = _make_params(narrator=NarratorParams(
        model_profile="narrator-mock", every_n_ticks=10))
    tm = TextMock("A promise was broken and the town seethed.")
    loop, world, repo, _ = _make_loop(params, narrator_provider=tm)
    asyncio.run(_drive(loop, world, 8))
    assert world.tick == 8

    run_id = loop._run_id
    repo.save_event(run_id, {"kind": "conflict", "actor_id": "system",
                             "text": "Bram insults Ada!", "payload": {}}, 4)
    repo.save_event(run_id, {"kind": "commitment_lapsed", "actor_id": "agent_mox",
                             "text": "Mox broke a promise to Ada.", "payload": {}}, 6)

    asyncio.run(loop.build_chronicle_from_history("narrator-mock", every=10))

    rows = repo.get_events(run_id, kinds=["narrator_summary"], order="asc")
    assert rows, "a chapter must have been generated for the window"
    chaos = rows[0]["payload"]["chaos"]
    # BOTH the conflict AND the commitment_lapsed must be counted as clashes.
    assert chaos["counts"]["clashes"] == 2, \
        "commitment_lapsed must reach the facts builder through the real query"
    assert any("insults" in c for c in chaos["conflicts"])
    assert any("broke a promise" in c for c in chaos["conflicts"])


# ──────────────────────────────────────────────────────────────────────────────
# 4. animal_action payload.place (event-log.md v1.2.0 note 2)
# ──────────────────────────────────────────────────────────────────────────────

def _animal_world(response: str):
    provider = TextMock(response)
    params = _make_params(animals=AnimalParams(
        enabled=True, act_every_n_ticks=1, llm_chance=1.0,
        model_profile="narrator-mock"))
    loop, world, repo, events = _make_loop(
        params, animals=[AnimalSeed("cat", "Mochi", "plaza")],
        animal_provider=provider)
    events.clear()
    return loop, world, repo, events


def test_wander_animal_action_carries_destination_place():
    loop, world, repo, events = _animal_world(
        json.dumps({"animal_thought": "patrol", "action": "wander", "args": {}}))

    asyncio.run(_drive(loop, world, 1))

    moves = [e for e in events if e.get("kind") == "animal_action"
             and e["payload"]["action"] == "wander"]
    assert moves, "no wander animal_action emitted"
    cat = next(a for a in world.animals.values() if a.name == "Mochi")
    for e in moves:
        assert "place" in e["payload"], "moving animal_action must carry payload.place"
        assert e["payload"]["place"] == cat.location, \
            "payload.place must be the DESTINATION (post-move location)"
    assert cat.location == "market", "two-place map: wander must have moved the cat"
    # Persisted rows carry it too (replay reads the DB, not the broadcast).
    rows = repo.get_events(loop._run_id, kinds=["animal_action"])
    assert all(r["payload"]["place"] == "market" for r in rows
               if r["payload"]["action"] == "wander")


def test_non_move_animal_action_has_no_place_key():
    loop, world, repo, events = _animal_world(
        json.dumps({"animal_thought": "zzz", "action": "nap", "args": {}}))

    asyncio.run(_drive(loop, world, 1))

    naps = [e for e in events if e.get("kind") == "animal_action"
            and e["payload"]["action"] == "nap"]
    assert naps, "no nap animal_action emitted"
    assert all("place" not in e["payload"] for e in naps), \
        "non-move animal actions must not carry payload.place"

"""
W10 gate tests — "Trust & hygiene" (EM-076 backend half + EM-077).

Audit findings under test (docs/audit-2026-06-09.md):
  - B9  — get_analytics constitution.active_rules derives from actual rule
          STATE (rules table / rule_* projection), never `passed - rejected`
          event arithmetic. Shape stays event-log.md §7.
  - B10 — api.app._broadcast schedules WS sends with a done-callback that
          consumes exceptions and evicts the dead socket from _connections.
  - B11 — GeminiAdapter sends the API key via the x-goog-api-key header, not
          the ?key= URL query param.
  - B14 — TickLoop._get_profile_color_for_profile exists for the governance
          spawn path (no hasattr guard); governance agent_spawned events carry
          a real profile_color.
  - B15 — SpawnBody / SpawnAnimalBody length caps (name<=40, personality<=280,
          location<=40) reject over-limit input with FastAPI's 422.

Plus the addendum item:
  - EM-085 — persist runs by default: a file db_path survives a repository
          re-open with prior events intact; restart/reset creates a NEW run
          row with prior runs preserved on disk; a relative db_path resolves
          against the repo root (the parent of the config/ dir); missing
          parent directories are auto-created.

The W9-QA-1b flip (space_exploration reads payload.place) lives in
tests/test_w9.py::test_analytics_space_exploration_counts_moves.

Everything is deterministic and offline (MockProvider / fakes; no network).
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import (
    AgentConfig, ModelProfile, PlaceConfig, WorldConfig, WorldParams,
    _resolve_db_path, load_config,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Harness (test_w9.py idiom, trimmed)
# ──────────────────────────────────────────────────────────────────────────────

def _make_params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=2.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=5,
    )
    base.update(overrides)
    return WorldParams(**base)


def _make_loop(*, script: list | None = None, agent_count: int = 1,
               db_path: str = ":memory:"):
    params = _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
    ]
    names = ["Ada", "Bram", "Cleo"][:agent_count]
    agents = [
        AgentState(
            id=f"agent_{n.lower()}", name=n, personality="Test agent.",
            profile="mock", location="market",
            energy=params.starting_energy, credits=params.starting_credits,
        )
        for n in names
    ]
    world = World(params=params, places=places, agents=agents)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": MockProvider(script=script)},
    )
    for a in agents:
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(db_path)
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    events: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: events.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo, router, events


async def _run_ticks(loop: TickLoop, world: World, n: int) -> None:
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        if not agent.alive:
            continue
        await loop._execute_turn(agent)


# ──────────────────────────────────────────────────────────────────────────────
# 1. B9 — active_rules from rule STATE, not event arithmetic
# ──────────────────────────────────────────────────────────────────────────────

def _seed_rule_events(repo: SQLiteRepository, run_id: int) -> None:
    """3 distinct rules proposed+passed, 1 proposed+rejected.

    The old formula (`passed - rejected if > 0 else passed`) yields 2 here —
    a rejected PROPOSAL wrongly deactivating a passed rule. Truth: 3 active.
    """
    for i, tick in ((1, 1), (2, 2), (3, 3)):
        repo.save_event(run_id, {"kind": "rule_proposed", "actor_id": "agent_a",
                                 "payload": {"rule_id": f"rule_{i}"}}, tick)
        repo.save_event(run_id, {"kind": "rule_passed", "actor_id": "agent_a",
                                 "payload": {"rule_id": f"rule_{i}"}}, tick)
    repo.save_event(run_id, {"kind": "rule_proposed", "actor_id": "agent_b",
                             "payload": {"rule_id": "rule_4"}}, 4)
    repo.save_event(run_id, {"kind": "rule_rejected", "actor_id": "agent_b",
                             "payload": {"rule_id": "rule_4"}}, 4)


def _rule(rid: str, status: str) -> RuleState:
    return RuleState(id=rid, effect="ubi", text=f"rule {rid}",
                     proposer_id="agent_a", status=status, created_tick=1)


def test_active_rules_event_projection_not_passed_minus_rejected():
    """Event-only ingestion (empty rules table): active_rules == rules whose
    last lifecycle event is rule_passed (3), NOT `passed - rejected` (2)."""
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    _seed_rule_events(repo, run_id)

    constitution = repo.get_analytics(run_id)["constitution"]
    assert constitution["active_rules"] == 3, (
        "a rejected proposal must never deactivate a passed rule (audit B9)"
    )
    # governance counters keep their event semantics (contract §7).
    gov = repo.get_analytics(run_id)["governance"]
    assert (gov["proposed"], gov["passed"], gov["rejected"]) == (4, 3, 1)


def test_active_rules_full_range_reads_rules_table_as_source_of_truth():
    """With rules table rows present, the full-range count comes from the
    TABLE state — even when the event stream would project differently."""
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    _seed_rule_events(repo, run_id)  # events project 3 active
    # Table truth: only 2 still active (rule_3 ended up rejected in state).
    repo.save_rule(run_id, _rule("rule_1", "active"))
    repo.save_rule(run_id, _rule("rule_2", "active"))
    repo.save_rule(run_id, _rule("rule_3", "rejected"))
    repo.save_rule(run_id, _rule("rule_4", "rejected"))

    assert repo.get_analytics(run_id)["constitution"]["active_rules"] == 2


def test_active_rules_tick_windowed_uses_event_projection():
    """Tick-windowed queries project rule state from events up to to_tick
    (the rules table only knows the LATEST state)."""
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    _seed_rule_events(repo, run_id)
    repo.save_rule(run_id, _rule("rule_1", "active"))  # table present but latest-state

    assert repo.get_analytics(run_id, to_tick=0)["constitution"]["active_rules"] == 0
    assert repo.get_analytics(run_id, to_tick=2)["constitution"]["active_rules"] == 2
    assert repo.get_analytics(run_id, to_tick=4)["constitution"]["active_rules"] == 3


@pytest.mark.asyncio
async def test_active_rules_end_to_end_matches_rules_table():
    """Full pipeline: propose + sole YES vote passes a rule; analytics
    active_rules == 1 and equals the rules-table 'active' count."""
    loop, world, repo, _, _ = _make_loop(agent_count=1, script=[
        {"action": "propose_rule", "args": {"effect": "ubi", "text": "basic income"}},
        {"action": "idle", "args": {}},  # consumed by the dynamic YES vote
    ])
    run_id = loop._run_id
    await _run_ticks(loop, world, 2)
    assert repo.get_events(run_id, kinds=["rule_passed"]), "rule did not pass"

    active = repo.get_analytics(run_id)["constitution"]["active_rules"]
    assert active == 1
    table_active = repo._conn.execute(
        "SELECT COUNT(*) FROM rules WHERE run_id=? AND status='active'",
        (run_id,),
    ).fetchone()[0]
    assert active == table_active


# ──────────────────────────────────────────────────────────────────────────────
# 2. B10 — _broadcast done-callback evicts failed sockets
# ──────────────────────────────────────────────────────────────────────────────

class _GoodWS:
    def __init__(self):
        self.sent: list[str] = []

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _ClosedWS:
    """send_text raises like a closed/aborted starlette WebSocket."""

    async def send_text(self, data: str) -> None:
        raise RuntimeError('Cannot call "send" once a close message has been sent.')


@pytest.mark.asyncio
async def test_broadcast_done_callback_discards_failed_socket_keeps_live_one():
    appmod = pytest.importorskip("petridish.api.app")
    good, dead = _GoodWS(), _ClosedWS()
    saved = set(appmod._connections)
    appmod._connections.clear()
    appmod._connections.update({good, dead})
    try:
        appmod._broadcast({"type": "ping"})
        # Let the scheduled send tasks and their done-callbacks run.
        for _ in range(10):
            await asyncio.sleep(0)
        assert dead not in appmod._connections, (
            "failed socket not evicted from _connections (audit B10)"
        )
        assert good in appmod._connections, "healthy socket wrongly evicted"
        assert good.sent == [json.dumps({"type": "ping"})]
    finally:
        appmod._connections.clear()
        appmod._connections.update(saved)


@pytest.mark.asyncio
async def test_broadcast_send_exception_is_consumed():
    """The done-callback retrieves the task exception — asyncio never sees an
    unretrieved 'Task exception' for a failed WS send."""
    appmod = pytest.importorskip("petridish.api.app")
    unhandled: list[dict] = []
    ev_loop = asyncio.get_running_loop()
    prev_handler = ev_loop.get_exception_handler()
    ev_loop.set_exception_handler(lambda lo, ctx: unhandled.append(ctx))
    saved = set(appmod._connections)
    appmod._connections.clear()
    dead = _ClosedWS()
    appmod._connections.add(dead)
    try:
        appmod._broadcast({"type": "ping"})
        for _ in range(10):
            await asyncio.sleep(0)
        import gc
        gc.collect()  # an unretrieved task exception surfaces on GC
        await asyncio.sleep(0)
        assert unhandled == [], f"unhandled task exception leaked: {unhandled}"
        assert dead not in appmod._connections
    finally:
        ev_loop.set_exception_handler(prev_handler)
        appmod._connections.clear()
        appmod._connections.update(saved)


# ──────────────────────────────────────────────────────────────────────────────
# 3. B11 — Gemini key travels in the x-goog-api-key header
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gemini_adapter_sends_key_header_not_query_param(monkeypatch):
    from petridish.providers import adapters

    captured: dict = {}

    async def fake_post(client, url, headers, payload, profile):
        captured.update(url=url, headers=headers, payload=payload)
        return (
            {"candidates": [{"content": {"parts": [{"text": "hi"}]},
                             "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 1}},
            None,
        )

    monkeypatch.setattr(adapters, "_post_with_retry", fake_post)
    ad = adapters.GeminiAdapter("gemini-flash", "SECRET-KEY-123",
                                "gemini-2.0-flash", "#3498db")
    out = await ad.chat([{"role": "user", "content": "x"}],
                        max_tokens=16, temperature=0.2)

    assert out == "hi"
    assert "SECRET-KEY-123" not in captured["url"], "API key leaked into the URL"
    assert "key=" not in captured["url"], "?key= query param still present (audit B11)"
    assert captured["headers"].get("x-goog-api-key") == "SECRET-KEY-123"
    assert captured["url"].endswith("gemini-2.0-flash:generateContent")


# ──────────────────────────────────────────────────────────────────────────────
# 4. B14 — profile→color lookup for governance spawns
# ──────────────────────────────────────────────────────────────────────────────

def test_get_profile_color_for_profile_known_and_unknown():
    loop, *_ = _make_loop()
    assert loop._get_profile_color_for_profile("mock") == "#2ecc71"
    assert loop._get_profile_color_for_profile("no-such-profile") == "#888888"


def test_governance_spawn_event_carries_real_profile_color():
    """End-to-end on the real app: POST /api/agents mode=governance emits an
    agent_spawned whose profile_color is the profile's configured color (was
    always null behind the hasattr guard, audit B14)."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        profiles = client.get("/api/profiles").json()
        assert profiles, "no profiles configured"
        prof = profiles[0]

        sink: list[dict] = []
        orig = appmod._loop._broadcaster
        appmod._loop._broadcaster = sink.append
        try:
            resp = client.post("/api/agents", json={
                "name": "GovKid", "profile": prof["name"], "mode": "governance",
            })
            assert resp.status_code == 202, resp.text
            assert resp.json()["mode"] == "governance"
        finally:
            appmod._loop._broadcaster = orig

        spawned = [m for m in sink if m.get("kind") == "agent_spawned"
                   and (m.get("payload") or {}).get("method") == "governance"]
        assert spawned, "governance spawn emitted no agent_spawned event"
        assert spawned[-1]["profile_color"] == prof["color"], (
            f"expected {prof['color']!r}, got {spawned[-1]['profile_color']!r}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 5. B15 — spawn input length caps reject with 422
# ──────────────────────────────────────────────────────────────────────────────

def test_spawn_body_length_caps_reject_422_and_boundary_passes():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        # Over-limit fields: FastAPI validation rejects with 422 before the
        # handler runs (the bogus profile is irrelevant at this stage).
        for body in (
            {"name": "x" * 41, "profile": "p"},
            {"name": "Ok", "profile": "p", "personality": "y" * 281},
            {"name": "Ok", "profile": "p", "location": "z" * 41},
        ):
            resp = client.post("/api/agents", json=body)
            assert resp.status_code == 422, (
                f"over-limit body accepted ({resp.status_code}): {body}"
            )

        # Boundary (exactly at the cap) clears VALIDATION: the unknown profile
        # now reaches the handler and gets its domain 400, not a 422.
        resp = client.post("/api/agents", json={
            "name": "n" * 40, "profile": "no-such-profile",
            "personality": "p" * 280, "location": "l" * 40,
        })
        assert resp.status_code == 400, resp.text

        # Animals: same caps; species stays handler-checked (400).
        for body in (
            {"species": "cat", "name": "x" * 41},
            {"species": "dog", "name": "Rex", "personality": "y" * 281},
            {"species": "cat", "name": "Tom", "location": "z" * 41},
        ):
            resp = client.post("/api/animals", json=body)
            assert resp.status_code == 422, (
                f"over-limit animal body accepted ({resp.status_code}): {body}"
            )
        resp = client.post("/api/animals", json={"species": "dragon", "name": "Puff"})
        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────────────────
# 6. EM-085 — persist runs by default
# ──────────────────────────────────────────────────────────────────────────────

def test_file_db_survives_repository_reopen_with_events_intact(tmp_path):
    """A file db_path persists across a close + re-open: the run row and its
    events are readable from a brand-new SQLiteRepository instance (the live
    failure: ':memory:' wiped all history on every backend restart)."""
    db = tmp_path / "run.sqlite"
    repo = SQLiteRepository(db)
    run_id = repo.start_run('{"world": {}}')
    for tick, kind in ((0, "agent_spawned"), (1, "agent_moved"), (2, "economy")):
        repo.save_event(run_id, {"kind": kind, "actor_id": "agent_a",
                                 "payload": {"n": tick}}, tick)
    repo.close()

    reopened = SQLiteRepository(db)
    try:
        rows = reopened.get_events(run_id, order="asc")
        assert [r["kind"] for r in rows] == ["agent_spawned", "agent_moved", "economy"]
        assert [r["payload"]["n"] for r in rows] == [0, 1, 2]
    finally:
        reopened.close()


@pytest.mark.asyncio
async def test_reset_creates_new_run_row_and_preserves_prior_run(tmp_path):
    """Multi-run behavior on a file DB (feeds EM-086): reset() ends the old
    run row ('ended'), starts a DISTINCT new one ('running'), and both runs'
    events stay independently readable — no merge, no corruption."""
    db = str(tmp_path / "run.sqlite")
    loop, world, repo, _, _ = _make_loop(
        agent_count=1, db_path=db,
        script=[{"action": "forage", "args": {}}],
    )
    run1 = loop._run_id
    await _run_ticks(loop, world, 2)
    run1_rows = len(repo.get_events(run1))
    assert run1_rows > 0

    cfg = WorldConfig(
        world=_make_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentConfig(name="Zed", personality="", profile="mock",
                            location="plaza")],
    )
    await loop.reset(cfg)
    run2 = loop._run_id
    assert run2 != run1, "reset must open a NEW run row"

    # A probe event in run 2 lands in run 2 only.
    loop._emit_event({"kind": "probe", "actor_id": None, "payload": {"run": 2}})
    assert [e["kind"] for e in repo.get_events(run2, kinds=["probe"])] == ["probe"]
    assert repo.get_events(run1, kinds=["probe"]) == []
    # Run 1's history is intact on disk (preserved, not merged or truncated).
    assert len(repo.get_events(run1)) == run1_rows

    statuses = dict(repo._conn.execute(
        "SELECT id, status FROM runs ORDER BY id").fetchall())
    assert statuses[run1] == "ended"
    assert statuses[run2] == "running"

    # Both runs survive a process-style re-open too.
    repo.close()
    reopened = SQLiteRepository(db)
    try:
        assert len(reopened.get_events(run1)) == run1_rows
        assert reopened.get_events(run2, kinds=["probe"])
    finally:
        reopened.close()


def test_repository_creates_missing_parent_directories(tmp_path):
    """SQLiteRepository mkdirs the db file's parent (fresh checkout has no
    data/ dir)."""
    db = tmp_path / "data" / "nested" / "run.sqlite"
    assert not db.parent.exists()
    repo = SQLiteRepository(db)
    try:
        assert db.parent.is_dir()
        run_id = repo.start_run("{}")
        assert run_id == 1
    finally:
        repo.close()


def test_resolve_db_path_rules(tmp_path):
    """The documented resolution rule: ':memory:'/'file:' URIs and absolute
    paths pass through; relative paths resolve against the PARENT of the
    config dir (the repo root); no config dir -> unchanged (cwd-relative)."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    assert _resolve_db_path(":memory:", cfg_dir) == ":memory:"
    assert _resolve_db_path("", cfg_dir) == ":memory:"
    assert _resolve_db_path("file:cached?mode=memory", cfg_dir).startswith("file:")
    absolute = str(tmp_path / "abs.sqlite")
    assert _resolve_db_path(absolute, cfg_dir) == absolute
    assert _resolve_db_path("data/run.sqlite", cfg_dir) == str(
        tmp_path / "data" / "run.sqlite"
    )
    assert _resolve_db_path("data/run.sqlite", None) == "data/run.sqlite"


def test_shipped_config_persists_to_repo_root_data_file(monkeypatch):
    """End-to-end on the REAL config/world.yaml: with no EM_DB_PATH override,
    load_config() resolves db_path to <repo>/data/run.sqlite (absolute),
    regardless of cwd; with the suite's EM_DB_PATH=':memory:' pin it stays
    ephemeral (how pytest avoids touching live run history)."""
    repo_root = Path(__file__).resolve().parents[2]
    assert (repo_root / "config" / "world.yaml").is_file()
    monkeypatch.delenv("EM_CONFIG_DIR", raising=False)

    # The suite pin (tests/conftest.py): ':memory:' via the yaml ${EM_DB_PATH:-…}.
    monkeypatch.setenv("EM_DB_PATH", ":memory:")
    monkeypatch.chdir(repo_root / "backend")  # ./dev launch cwd
    assert load_config().world.db_path == ":memory:"

    # Default (no override): repo-root data/run.sqlite from BOTH launch cwds.
    monkeypatch.delenv("EM_DB_PATH")
    expected = str(repo_root / "data" / "run.sqlite")
    assert load_config().world.db_path == expected      # cwd = backend/
    monkeypatch.chdir(repo_root)
    assert load_config().world.db_path == expected      # cwd = repo root

"""
W6 gate tests — read-only event-log API surface + per-attempt llm_call + real
token-usage capture + trace-field truncation (the live-run fix).

Contracts under test:
  - contracts/api.openapi.yaml (v1.1.0)        — the W6 read endpoints + EventRow.
  - contracts/event-log.md §7                  — get_analytics shape (9-AWI + by_model + usage).
  - contracts/providers.md (Usage capture)     — EM-067 last_usage + per-attempt llm_call.
  - contracts/action-protocol.schema.json      — optional trace fields TRUNCATED, not rejected.

Everything here is deterministic and offline. The read-endpoint group drives a
short scripted MockProvider run via the *same* TickLoop._execute_turn path the
asyncio loop uses (no scheduler sleeps), then reads it back over the FastAPI
TestClient by pointing the app's module-level singletons at that in-memory run.
The usage-capture group stubs at the httpx layer (a threaded stdlib HTTP server,
mirroring test_openai_adapter.py) so no real token is ever spent.

Five groups, mirroring the QE brief:
  1. READ ENDPOINTS    — every W6 GET returns 200 + the right shape; no active run
                         degrades to an empty 200 (never 500).
  2. PER-ATTEMPT       — a forced parse-failure turn emits TWO llm_call rows
                         (attempt 1 + 2) sharing one turn_id; success emits one;
                         OTel keys all present; mock usage null.
  3. USAGE CAPTURE     — an openai-style usage block flows to adapter.last_usage
                         and into the llm_call payload; mock stays null.
  4. TRUNCATION        — over-long trace fields are truncated and the turn still
                         resolves to the chosen action (not idle); wrong-type
                         memories_used is dropped; structural args still fail.
  5. REGRESSION        — (the existing suite, run alongside this file.)
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile, WorldConfig
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.adapters import OpenAICompatibleAdapter
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Shared harness — a fully wired loop driven by a scripted MockProvider, mirroring
# the pattern in tests/test_event_log.py.
# ──────────────────────────────────────────────────────────────────────────────

# EventRow keys per contracts/event-log.md §7 + api.openapi.yaml EventRow schema.
EVENT_ROW_KEYS = {
    "seq", "run_id", "tick", "sim_time", "kind", "actor_id", "actor_type",
    "target_id", "profile", "turn_id", "text", "payload", "ts",
}

# The chain kinds emitted (in order) for every agent turn, per event-log.md §3.
TRACE_KINDS = [
    "turn_start", "perceived", "memory_retrieved", "llm_call", "reasoning",
    "action_chosen",
]

# OTel GenAI attribute key set the llm_call payload must always carry (§3.4).
OTEL_LLM_KEYS = {
    "gen_ai.request.model",
    "gen_ai.response.model",
    "gen_ai.usage.input_tokens",
    "gen_ai.usage.output_tokens",
    "latency_ms",
    "gen_ai.response.finish_reasons",
    "cached",
    "attempt",
}

# Documented top-level analytics keys per event-log.md §7 get_analytics shape.
ANALYTICS_TOP_KEYS = {
    "population", "crime", "tool_exploration", "space_exploration",
    "governance", "public_expression", "social_fabric", "economy",
    "constitution", "by_model", "usage",
}


def _make_params(**overrides: Any) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=20,
        memory_window=5,
        snapshot_interval_ticks=5,
    )
    base.update(overrides)
    return WorldParams(**base)


def _make_loop(
    *,
    script: list | None = None,
    params: WorldParams | None = None,
    agent_count: int = 3,
    overrides: dict | None = None,
    profiles: list[ModelProfile] | None = None,
    default_profile: str = "mock",
) -> tuple[TickLoop, World, SQLiteRepository, Router]:
    """Wire World + Router + Runtime + repo + loop.

    Defaults to an all-mock world (deterministic, offline). `overrides`/`profiles`
    let the usage-capture group swap in a stubbed openai adapter. `script` cycles
    the same scripted actions for every agent; None runs the per-agent default
    MockProvider scripts (used for the multi-tick read-endpoint run).
    """
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=20, y=0, kind="governance"),
        PlaceState(id="home", name="Hearth", x=30, y=0, kind="home"),
        PlaceState(id="commons", name="Commons", x=40, y=0, kind="wild"),
    ]
    # Names bind the MockProvider default scripts (ada/bram/cleo/...) so the
    # no-script multi-tick run exercises proposals + votes + economy.
    names = ["Ada", "Bram", "Cleo", "Dov", "Esi"][:agent_count]
    agents = [
        AgentState(
            id=f"agent_{name.lower()}",
            name=name,
            personality="Test agent.",
            profile=default_profile,
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for name in names
    ]
    world = World(params=params, places=places, agents=agents)

    if profiles is None:
        profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")]
        overrides = overrides or {"mock": MockProvider(script=script)}
    router = Router(profiles, adapter_overrides=overrides)
    for a in agents:
        router.reassign(a.id, default_profile)

    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)

    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo, router


async def _run_ticks(loop: TickLoop, world: World, n: int) -> None:
    """Advance exactly n agent turns through the real _execute_turn path."""
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        if not agent.alive:
            continue
        await loop._execute_turn(agent)


# ──────────────────────────────────────────────────────────────────────────────
# TestClient that reads back the SAME in-memory run we just drove.
#
# The app exposes its world/loop/repo as module-level singletons (api.app). The
# W6 read endpoints resolve the active run via _loop._run_id and read through
# _repo. To exercise the HTTP surface against a deterministic, pre-populated run
# we point those singletons at a loop we built and drove here, instead of the
# app's own lifespan-initialized world. We DON'T enter the lifespan (no
# background asyncio task), so the read endpoints serve our run statically.
# ──────────────────────────────────────────────────────────────────────────────

class _AppHandle:
    """A TestClient bound to a specific (loop, repo) singleton state, with the
    originals saved so the module is restored on teardown."""

    def __init__(self, loop: TickLoop, repo: SQLiteRepository) -> None:
        self.loop = loop
        self.repo = repo


@pytest.fixture()
def read_client():
    """Yield (client, attach) where attach(loop, repo, world, router, config)
    rebinds the app singletons to a pre-driven run, then a TestClient over it.

    No lifespan: the W6 read endpoints are pure reads over the bound _repo/_loop,
    so they serve our deterministic run without starting the background loop."""
    import sys
    import petridish.api.app  # noqa: F401 — ensure the submodule is imported
    # petridish/api/__init__.py does `from .app import app`, so `petridish.api.app`
    # resolves to the FastAPI *instance*. Reach the actual MODULE via sys.modules.
    appmod = sys.modules["petridish.api.app"]

    saved = {
        k: getattr(appmod, k)
        for k in ("_world", "_router", "_runtime", "_repo", "_loop", "_config")
    }

    def attach(loop, repo, world, router, config):
        appmod._world = world
        appmod._router = router
        appmod._runtime = loop._runtime
        appmod._repo = repo
        appmod._loop = loop
        appmod._config = config

    # raise_server_exceptions=True so any 500 surfaces as a test error.
    client = TestClient(appmod.app, raise_server_exceptions=True)
    try:
        yield client, attach
    finally:
        for k, v in saved.items():
            setattr(appmod, k, v)


# ══════════════════════════════════════════════════════════════════════════════
# 1. READ ENDPOINTS — every W6 GET returns 200 + the right shape.
# ══════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def driven_run():
    """Build + drive a 30-turn mock run; expose its (loop, world, repo, router).

    A short multi-tick mock run rich enough to populate every read endpoint: the
    default scripts produce economy, movement, proposals, votes, rule lifecycle."""
    loop, world, repo, router = _make_loop(agent_count=3)

    import asyncio
    loop_ = asyncio.new_event_loop()
    try:
        loop_.run_until_complete(_run_ticks(loop, world, 30))
    finally:
        loop_.close()
    return loop, world, repo, router


def test_get_events_returns_200_and_eventrow_shape(read_client, driven_run):
    """GET /api/events returns 200 with a list of EventRows carrying the §7 keys."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/events")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert isinstance(rows, list) and rows, "expected non-empty event list"
    for row in rows:
        assert EVENT_ROW_KEYS <= set(row.keys()), (
            f"EventRow missing keys: {EVENT_ROW_KEYS - set(row.keys())}"
        )
        assert isinstance(row["payload"], dict)
    # Default order is ascending by seq.
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs)


def test_get_events_honors_all_filters(read_client, driven_run):
    """GET /api/events honors from_tick/to_tick/kinds/actor_id/turn_id/after_seq/
    limit/order — every query parameter from api.openapi.yaml."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    all_rows = client.get("/api/events").json()
    assert all_rows

    # kinds (comma-separated string per the contract).
    llm = client.get("/api/events", params={"kinds": "llm_call"}).json()
    assert llm and all(r["kind"] == "llm_call" for r in llm)
    # multi-kind comma list.
    multi = client.get("/api/events", params={"kinds": "llm_call,turn_start"}).json()
    assert multi and {r["kind"] for r in multi} <= {"llm_call", "turn_start"}

    # actor_id.
    actor = next(r["actor_id"] for r in all_rows if r["actor_id"])
    by_actor = client.get("/api/events", params={"actor_id": actor}).json()
    assert by_actor and all(r["actor_id"] == actor for r in by_actor)

    # turn_id.
    turn = next(r["turn_id"] for r in all_rows if r["turn_id"])
    by_turn = client.get("/api/events", params={"turn_id": turn}).json()
    assert by_turn and all(r["turn_id"] == turn for r in by_turn)

    # from_tick / to_tick window.
    windowed = client.get("/api/events", params={"from_tick": 2, "to_tick": 4}).json()
    assert windowed and all(2 <= r["tick"] <= 4 for r in windowed)

    # after_seq keyset pagination.
    pivot = all_rows[len(all_rows) // 2]["seq"]
    tail = client.get("/api/events", params={"after_seq": pivot}).json()
    assert tail and all(r["seq"] > pivot for r in tail)

    # limit.
    limited = client.get("/api/events", params={"limit": 3}).json()
    assert len(limited) == 3

    # order asc vs desc.
    asc = client.get("/api/events", params={"order": "asc"}).json()
    desc = client.get("/api/events", params={"order": "desc"}).json()
    assert [r["seq"] for r in asc] == sorted(r["seq"] for r in asc)
    assert [r["seq"] for r in desc] == sorted((r["seq"] for r in desc), reverse=True)


def test_get_turn_trace_returns_ordered_chain(read_client, driven_run):
    """GET /api/turns/{turn_id} returns the ordered decision-trace chain (EventRows)
    all sharing the one turn_id, seq-ascending."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    events = client.get("/api/events").json()
    turn = next(r["turn_id"] for r in events if r["kind"] == "turn_start" and r["turn_id"])

    resp = client.get(f"/api/turns/{turn}")
    assert resp.status_code == 200, resp.text
    chain = resp.json()
    assert isinstance(chain, list) and chain
    assert {r["turn_id"] for r in chain} == {turn}
    assert [r["seq"] for r in chain] == sorted(r["seq"] for r in chain)
    for row in chain:
        assert EVENT_ROW_KEYS <= set(row.keys())
    # The ordered prefix is the six trace spans, in order.
    kinds = [r["kind"] for r in chain]
    assert kinds[: len(TRACE_KINDS)] == TRACE_KINDS


def test_get_rules_history_returns_lifecycle(read_client, driven_run):
    """GET /api/rules/history returns 200 with rule lifecycle entries. The default
    scripts propose rules, so at least one entry with the documented keys exists."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/rules/history")
    assert resp.status_code == 200, resp.text
    history = resp.json()
    assert isinstance(history, list)
    assert history, "default scripts propose rules; expected ≥1 history entry"
    for key in ("rule_id", "effect", "text", "proposer_id", "status",
                "created_tick", "votes", "resolved_tick", "outcome", "downstream"):
        assert key in history[0], f"rule history missing key {key}"


def test_get_relationships_returns_eventrows(read_client, driven_run):
    """GET /api/relationships returns 200 with a list (EventRows when present),
    and honors the agent_id / from_tick / to_tick filters."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/relationships")
    assert resp.status_code == 200, resp.text
    timeline = resp.json()
    assert isinstance(timeline, list)
    for row in timeline:
        assert EVENT_ROW_KEYS <= set(row.keys())

    # Filtered variants must also be 200 lists (possibly empty).
    filtered = client.get(
        "/api/relationships",
        params={"agent_id": "agent_ada", "from_tick": 0, "to_tick": 5},
    )
    assert filtered.status_code == 200
    assert isinstance(filtered.json(), list)


def test_get_snapshots_returns_tick_list(read_client, driven_run):
    """GET /api/snapshots returns 200 with [{tick}] ascending incl. tick 0."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/snapshots")
    assert resp.status_code == 200, resp.text
    snaps = resp.json()
    assert isinstance(snaps, list) and snaps
    ticks = [s["tick"] for s in snaps]
    assert 0 in ticks, "expected a tick-0 snapshot"
    assert ticks == sorted(ticks), "snapshots must be ascending"


def test_get_replay_returns_base_and_events(read_client, driven_run):
    """GET /api/replay?tick=T returns {base, events}: nearest prior snapshot +
    the events to fold forward up to T (EM-055)."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/replay", params={"tick": 7})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) >= {"base", "events"}
    assert body["base"] is not None, "expected a nearest snapshot at/before tick 7"
    assert {"tick", "state"} <= set(body["base"].keys())
    assert body["base"]["tick"] <= 7
    assert isinstance(body["events"], list) and body["events"]
    assert all(e["tick"] <= 7 for e in body["events"])
    for e in body["events"]:
        assert EVENT_ROW_KEYS <= set(e.keys())


def test_get_analytics_has_section7_top_level_keys(read_client, driven_run):
    """GET /api/analytics returns the §7 shape: all 9-AWI keys + by_model + usage,
    with usage.by_profile populated from the llm_call rows."""
    loop, world, repo, router = driven_run
    client, attach = read_client
    attach(loop, repo, world, router, WorldConfig())

    resp = client.get("/api/analytics")
    assert resp.status_code == 200, resp.text
    analytics = resp.json()
    assert ANALYTICS_TOP_KEYS <= set(analytics.keys()), (
        f"missing analytics keys: {ANALYTICS_TOP_KEYS - set(analytics.keys())}"
    )
    # Nested shapes the dashboard depends on.
    assert "by_kind" in analytics["crime"]
    assert "by_agent" in analytics["economy"]
    assert {"participation", "proposed", "passed", "rejected"} <= set(
        analytics["governance"].keys()
    )
    assert "by_profile" in analytics["usage"]
    # llm_call rows were emitted under the 'mock' request model => usage tracked.
    assert "mock" in analytics["usage"]["by_profile"]
    assert analytics["usage"]["by_profile"]["mock"]["requests"] > 0
    assert isinstance(analytics["by_model"], dict)


def test_no_active_run_reads_are_empty_200_never_500(read_client):
    """With NO active run/repo, every W6 read endpoint degrades to an empty 200
    (empty list / empty payload) — never a 500. Powers graceful /inspector degrade."""
    client, attach = read_client
    import sys
    import petridish.api.app  # noqa: F401
    appmod = sys.modules["petridish.api.app"]
    # Force the no-run state: nothing initialized.
    appmod._repo = None
    appmod._loop = None

    # Array-returning endpoints → empty list, 200.
    for path in ("/api/events", "/api/turns/abc123",
                 "/api/rules/history", "/api/relationships", "/api/snapshots"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}: {r.text}"
        assert r.json() == [], f"{path} should be empty list, got {r.json()!r}"

    # /api/replay → {base: None, events: []}, 200.
    rr = client.get("/api/replay", params={"tick": 3})
    assert rr.status_code == 200
    assert rr.json() == {"base": None, "events": []}

    # /api/analytics → {}, 200.
    ra = client.get("/api/analytics")
    assert ra.status_code == 200
    assert ra.json() == {}


# ══════════════════════════════════════════════════════════════════════════════
# 2. PER-ATTEMPT llm_call (EM-067).
# ══════════════════════════════════════════════════════════════════════════════

async def test_parse_failure_emits_two_llm_call_rows_one_turn_id():
    """A forced parse-failure turn (schema-invalid action on BOTH attempts) emits
    TWO llm_call rows (attempt 1 + attempt 2) that share the one turn_id, and the
    turn falls back to idle / resolves 'failed'. OTel keys present on every row;
    mock usage stays null."""
    # An unknown 'action' fails schema validation on both attempts (cycle repeats it),
    # forcing the runtime's single retry → two llm_call spans, then idle fallback.
    loop, world, repo, _ = _make_loop(
        agent_count=1, script=[{"action": "bogus_action", "args": {}}]
    )
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    events = repo.get_events(run_id, order="asc")
    llm_rows = [e for e in events if e["kind"] == "llm_call"]
    assert len(llm_rows) == 2, f"expected 2 per-attempt llm_call rows, got {len(llm_rows)}"

    # attempt numbers are 1 then 2.
    assert [r["payload"]["attempt"] for r in llm_rows] == [1, 2]
    # Both share the single turn_id of this turn.
    assert len({r["turn_id"] for r in llm_rows}) == 1
    turn_id = llm_rows[0]["turn_id"]
    assert turn_id is not None
    starts = [e for e in events if e["kind"] == "turn_start"]
    assert len(starts) == 1 and starts[0]["turn_id"] == turn_id

    # OTel keys present (and mock usage null) on every attempt row.
    for r in llm_rows:
        assert set(r["payload"].keys()) == OTEL_LLM_KEYS
        assert r["payload"]["gen_ai.usage.input_tokens"] is None
        assert r["payload"]["gen_ai.usage.output_tokens"] is None
        assert isinstance(r["payload"]["cached"], bool)

    # The dead-air turn still produces a complete, inspectable chain → idle/failed.
    by_kind = {e["kind"]: e for e in events}
    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "idle"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"


async def test_success_turn_emits_single_llm_call_row():
    """A turn whose first attempt parses + validates emits exactly ONE llm_call row
    (attempt 1). No spurious retry span. OTel keys all present; mock usage null."""
    loop, world, repo, _ = _make_loop(
        agent_count=1, script=[{"action": "forage", "args": {}}]
    )
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    llm_rows = [e for e in repo.get_events(run_id, order="asc") if e["kind"] == "llm_call"]
    assert len(llm_rows) == 1, f"success turn should emit one llm_call, got {len(llm_rows)}"
    row = llm_rows[0]
    assert row["payload"]["attempt"] == 1
    assert set(row["payload"].keys()) == OTEL_LLM_KEYS
    # Mock has no usage → tokens null but keys present.
    assert row["payload"]["gen_ai.usage.input_tokens"] is None
    assert row["payload"]["gen_ai.usage.output_tokens"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 3. USAGE CAPTURE (EM-067) — stub at the httpx layer (test_openai_adapter pattern).
# ══════════════════════════════════════════════════════════════════════════════

class _UsageStubHandler(BaseHTTPRequestHandler):
    """POST /v1/chat/completions → a configurable openai-style body carrying a
    `usage` block + choices[0].finish_reason."""

    def log_message(self, fmt: str, *args: Any) -> None:  # silence noisy logs
        pass

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = self.server._response_body  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


class _UsageStubServer(HTTPServer):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._response_body: dict = {}


@pytest.fixture()
def usage_stub():
    """Threaded local stub server that returns a usage-bearing chat completion."""
    server = _UsageStubServer(("127.0.0.1", 0), _UsageStubHandler)
    host, port = server.server_address
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://{host}:{port}/v1"
    yield base_url, server
    server.shutdown()
    thread.join(timeout=2)


async def test_openai_adapter_captures_usage_block(usage_stub):
    """With an openai-style response carrying usage, the adapter's last_usage holds
    the real prompt/completion token counts + finish_reason + a measured latency."""
    base_url, server = usage_stub
    server._response_body = {
        "choices": [
            {"message": {"content": json.dumps({"action": "forage", "args": {}})},
             "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 321, "completion_tokens": 88},
        "model": "served-by-proxy",
    }
    adapter = OpenAICompatibleAdapter(
        profile="oai", base_url=base_url, api_key="k", model_id="m", color="#f00"
    )
    text = await adapter.chat(
        [{"role": "system", "content": "go"}], max_tokens=64, temperature=0.5
    )
    assert json.loads(text)["action"] == "forage"

    usage = adapter.last_usage
    assert usage is not None
    assert usage["input_tokens"] == 321
    assert usage["output_tokens"] == 88
    assert usage["finish_reason"] == "stop"
    assert usage["cached"] is False
    assert isinstance(usage["latency_ms"], (int, float))


async def test_llm_call_payload_carries_real_tokens_through_loop(usage_stub):
    """End-to-end: the captured usage flows into the llm_call event payload — the
    OTel input/output token keys carry the REAL counts (replacing the W5 nulls)."""
    base_url, server = usage_stub
    server._response_body = {
        "choices": [
            {"message": {"content": json.dumps({"action": "forage", "args": {}})},
             "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 200, "completion_tokens": 50},
        "model": "served-by-proxy",
    }
    adapter = OpenAICompatibleAdapter(
        profile="oai", base_url=base_url, api_key="k", model_id="m", color="#f00"
    )
    profile = ModelProfile(
        name="oai", adapter="openai", model_id="m", max_tokens=64,
        temperature=0.5, color="#f00", base_url=base_url, api_key_env="",
    )
    loop, world, repo, _ = _make_loop(
        agent_count=1,
        profiles=[profile],
        overrides={"oai": adapter},
        default_profile="oai",
    )
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    llm_rows = [e for e in repo.get_events(run_id, order="asc") if e["kind"] == "llm_call"]
    assert len(llm_rows) == 1
    payload = llm_rows[0]["payload"]
    # Real tokens, not the W5 nulls.
    assert payload["gen_ai.usage.input_tokens"] == 200
    assert payload["gen_ai.usage.output_tokens"] == 50
    assert payload["gen_ai.response.finish_reasons"] == ["stop"]
    assert payload["gen_ai.response.model"] == "served-by-proxy"
    # Full OTel key set still present.
    assert set(payload.keys()) == OTEL_LLM_KEYS


async def test_mock_usage_stays_null_alongside_real_capture():
    """Mock provider has no real call → last_usage None and the llm_call tokens
    are null, even though the openai path captures real tokens (test above)."""
    loop, world, repo, router = _make_loop(
        agent_count=1, script=[{"action": "forage", "args": {}}]
    )
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    assert router.last_usage("mock") is None
    llm = [e for e in repo.get_events(run_id, order="asc") if e["kind"] == "llm_call"][0]
    assert llm["payload"]["gen_ai.usage.input_tokens"] is None
    assert llm["payload"]["gen_ai.usage.output_tokens"] is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. TRACE-FIELD TRUNCATION (the live-run fix).
# ══════════════════════════════════════════════════════════════════════════════

async def _run_single(script: list, *, agent_count: int = 1):
    """Drive one mock turn with `script`; return (by_kind events, repo)."""
    loop, world, repo, _ = _make_loop(agent_count=agent_count, script=script)
    agent = world.next_agent()
    await loop._execute_turn(agent)
    events = repo.get_events(loop._run_id, order="asc")
    return {e["kind"]: e for e in events}


async def test_overlong_trace_fields_truncated_action_still_resolves():
    """An action whose memories_used item >160 / reasoning >1200 /
    perceived_summary >600 is TRUNCATED (not rejected) and the turn still resolves
    to the chosen action (forage at market), NOT idle."""
    action = {
        "action": "forage",
        "args": {},
        "perceived_summary": "P" * 900,        # > 600
        "reasoning": "R" * 2000,               # > 1200
        "memories_used": ["m" * 300, "kept"],  # item > 160
    }
    by_kind = await _run_single([action])

    # Chosen action survived — not an idle fallback.
    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "forage"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"

    # Trace fields were truncated to their caps before validation.
    assert len(by_kind["perceived"]["payload"]["perceived_summary"]) == 600
    rp = by_kind["reasoning"]["payload"]
    assert len(rp["reasoning"]) == 1200
    assert len(rp["memories_used"][0]) == 160
    assert rp["memories_used"][1] == "kept"


async def test_wrong_type_memories_used_dropped_not_failed():
    """A wrong-type memories_used (a string, not a list) is DROPPED rather than
    failing the turn — the action still resolves."""
    action = {"action": "forage", "args": {}, "memories_used": "not-a-list"}
    by_kind = await _run_single([action])

    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "forage"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "ok"
    # Dropped → null in the reasoning row, not a crashed/failed turn.
    assert by_kind["reasoning"]["payload"]["memories_used"] is None


async def test_structural_bad_place_still_fails_to_idle():
    """A structural arg error (move_to an unknown place) STILL fails the turn → idle,
    even when cosmetic trace fields are over-long. Structural args are strict."""
    action = {
        "action": "move_to",
        "args": {"place": "nowhere-land"},
        "reasoning": "R" * 2000,  # over-long cosmetic field present too
    }
    by_kind = await _run_single([action])

    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "idle"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"


async def test_structural_bad_target_still_fails_to_idle():
    """A structural arg error (give to a nonexistent target) STILL fails → idle."""
    action = {"action": "give", "args": {"target": "ghost_agent", "amount": 1}}
    by_kind = await _run_single([action])

    assert by_kind["action_chosen"]["payload"]["chosen_tool"] == "idle"
    assert by_kind["action_resolved"]["payload"]["outcome"] == "failed"

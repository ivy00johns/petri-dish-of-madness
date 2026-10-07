"""EM-112 + EM-119 — the parallel-worlds tournament + Model-Family Arena.

Layers covered (each at its own seam):
  - providers/families.py       — the coarse classifier (mirror of the
                                  frontend EM-309 table, + the kimi addition)
                                  and legend grouping.
  - persistence/repository.py   — `runs.model_family` stamp (round-trip +
                                  legacy-DB migration) + count_events_of_kind.
  - engine/loop.py              — reset(model_family=) stamps the runs row.
  - api/tournament.py           — build_cast_plan (determinism, round-robin,
                                  available-first, un-castable "other"),
                                  request validation, TournamentRunner
                                  sequencing over fakes (order, abort, stall,
                                  error) and over the REAL TickLoop.
  - api/arena.py                — arena_summary from seeded events: outcome
                                  cards, family means, sparkline downsample,
                                  un-stamped runs omitted.
  - API endpoints (TestClient)  — /api/arena, /api/arena/tournament
                                  start/status/abort, 400/409 paths, the
                                  fork/reset 409 guards, fork inheritance.

Deterministic and offline (MockProvider / counting fakes — no network, no real
API keys); conftest pins EM_DB_PATH=':memory:' so TestClient runs never touch
the live run-history file. Harness idioms follow test_w10/test_w11a.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from petridish.config.loader import (
    AgentConfig,
    ModelProfile,
    PlaceConfig,
    WorldConfig,
    WorldParams,
    load_config,
)
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.families import families_in_legend, model_family
from petridish.api.tournament import (
    TournamentRunner,
    build_cast_plan,
    validate_tournament_request,
)

# ──────────────────────────────────────────────────────────────────────────────
# 1. families.py — the classifier (frontend-mirror pin)
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("model_id", "expected"),
    [
        ("gemini-3.5-flash", "gemini"),
        ("llama-3.3-70b-fp8-fast", "llama"),
        ("qwen3-next-80b-a3b-instruct", "qwen"),
        ("deepseek-v4-pro", "deepseek"),
        ("glm-4.7", "glm"),
        ("mistral-small-3.1-24b", "mistral"),
        ("claude-sonnet-4", "claude"),
        ("gpt-5-mini", "gpt"),
        ("kimi-k2", "kimi"),
        ("moonshotai/kimi-latest", "kimi"),
        ("auto", "other"),          # the terminal is NOT a family
        ("mock", "other"),          # the test adapter is NOT a family
        (None, "other"),
        ("proprietary-secret-9000", "other"),
    ],
)
def test_family_classification(model_id, expected):
    assert model_family(model_id) == expected


def test_family_falls_back_to_profile_name():
    # model_id missing → the profile name carries the signal (EM-309 parity).
    assert model_family(None, "groq-llama") == "llama"
    assert model_family("", "Vesper-mistral-small") == "mistral"


def test_families_in_legend_groups_sorted():
    legend = [
        {"name": "llama-fast", "model_id": "llama-3.3-70b-fp8-fast", "available": True},
        {"name": "gemini-flash", "model_id": "gemini-3.5-flash", "available": True},
        {"name": "groq-llama", "model_id": "llama-3.3-70b", "available": False},
        {"name": "mock", "model_id": "mock", "available": True},
    ]
    groups = families_in_legend(legend)
    assert groups["gemini"] == ["gemini-flash"]
    assert groups["llama"] == ["groq-llama", "llama-fast"]  # sorted
    assert groups["other"] == ["mock"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. repository — the runs.model_family stamp
# ──────────────────────────────────────────────────────────────────────────────


def test_runs_model_family_roundtrip(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "runs.sqlite"))
    cfg = json_cfg({"agents": [{"name": "A", "profile": "mock"}]})
    stamped = repo.start_run(cfg, model_family="gemini")
    plain = repo.start_run(cfg)

    got = repo.get_run(stamped)
    assert got is not None and got["model_family"] == "gemini"
    plain_row = repo.get_run(plain)
    assert plain_row is not None and plain_row["model_family"] is None

    rows = {r["id"]: r for r in repo.list_runs()}
    assert rows[stamped]["model_family"] == "gemini"
    assert rows[plain]["model_family"] is None


def test_runs_model_family_migrates_legacy_db(tmp_path):
    """A pre-EM-112 file DB (runs table without the column) upgrades
    idempotently on open — list_runs/get_run keep working."""
    path = str(tmp_path / "legacy.sqlite")
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          started_at TEXT NOT NULL,
          ended_at TEXT,
          config_json TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'running'
        );
        CREATE TABLE events (
          seq INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          tick INTEGER NOT NULL,
          sim_time REAL,
          kind TEXT NOT NULL,
          actor_id TEXT,
          actor_type TEXT NOT NULL DEFAULT 'human_agent',
          target_id TEXT,
          profile TEXT,
          turn_id TEXT,
          text TEXT,
          payload_json TEXT NOT NULL DEFAULT '{}',
          ts TEXT NOT NULL
        );
        INSERT INTO runs (started_at, config_json) VALUES ('2026-01-01', '{}');
        """
    )
    conn.commit()
    conn.close()

    repo = SQLiteRepository(path)
    rid = repo.start_run(json_cfg({}), model_family="llama")
    rows = {r["id"]: r for r in repo.list_runs()}
    assert rows[rid]["model_family"] == "llama"
    legacy = next(r for r in rows.values() if r["model_family"] is None)
    assert legacy["status"] == "running"  # the pre-existing row survived


def test_count_events_of_kind(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "c.sqlite"))
    rid = repo.start_run(json_cfg({}))
    for _ in range(2):
        repo.save_event(rid, {"kind": "building_operational", "payload": {}}, 1)
    repo.save_event(rid, {"kind": "agent_speech", "payload": {}}, 2)
    assert repo.count_events_of_kind(rid, "building_operational") == 2
    assert repo.count_events_of_kind(rid, "building_demolished") == 0
    assert repo.count_events_of_kind(rid + 1, "building_operational") == 0


def json_cfg(agents_cfg: dict) -> str:
    import json

    return json.dumps(agents_cfg)


# ──────────────────────────────────────────────────────────────────────────────
# 3. loop — reset(model_family=) stamps the fresh run
# ──────────────────────────────────────────────────────────────────────────────


def _arena_params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.02,
        energy_decay_per_turn=2.0,
        starting_energy=80.0,
        starting_credits=15,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=20,
        memory_window=5,
    )


def _real_loop(agent_names: tuple[str, ...] = ("A", "B")):
    """A real TickLoop on :memory: with a scripted forage-only mock."""
    from petridish.agents.runtime import AgentRuntime
    from petridish.engine.loop import TickLoop
    from petridish.engine.world import AgentState, PlaceState, World
    from petridish.providers.mock import MockProvider
    from petridish.providers.router import Router

    params = _arena_params()
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [
        AgentState(
            id=f"agent_{n.lower()}", name=n, personality="Test agent.",
            profile="mock", location="plaza",
            energy=params.starting_energy, credits=params.starting_credits,
        )
        for n in agent_names
    ]
    world = World(params=params, places=places, agents=agents)
    mock = MockProvider(script=[{"action": "forage", "args": {}}])
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock},
    )
    for a in agents:
        router.reassign(a.id, "mock")
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    loop.init_run(
        WorldConfig(
            world=params,
            places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
            agents=[AgentConfig(name=n, personality="", profile="mock", location="plaza")
                    for n in agent_names],
        )
    )
    return loop, repo


@pytest.mark.asyncio
async def test_reset_stamps_model_family():
    from petridish.engine.loop import TickLoop  # noqa: F401  (import parity)

    loop, repo = _real_loop()
    cfg = WorldConfig(
        world=_arena_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentConfig(name="A", personality="", profile="mock", location="plaza")],
    )
    await loop.reset(cfg, model_family="qwen")
    assert repo.get_run(loop._run_id)["model_family"] == "qwen"

    await loop.reset(cfg)  # un-stamped reset stays null
    assert repo.get_run(loop._run_id)["model_family"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 4. tournament.py — casting + runner
# ──────────────────────────────────────────────────────────────────────────────

_LEGEND = [
    {"name": "gemini-a", "model_id": "gemini-3.5-flash", "available": True},
    {"name": "gemini-b", "model_id": "gemini-2.0-flash", "available": False},
    {"name": "llama-x", "model_id": "llama-3.3-70b-fp8-fast", "available": True},
    {"name": "auto", "model_id": "auto", "available": True},
    {"name": "mock", "model_id": "mock", "available": True},
]


def _cast_cfg(n_agents: int = 5) -> WorldConfig:
    return WorldConfig(
        world=_arena_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[
            AgentConfig(name=f"A{i}", personality=f"p{i}", profile="mock",
                        location="plaza")
            for i in range(n_agents)
        ],
    )


def test_build_cast_plan_round_robins_deterministically():
    cfg = _cast_cfg(5)
    plan = build_cast_plan(cfg, _LEGEND, "gemini")
    # gemini-a (available) wins the pool; every agent lands on it.
    assert plan.lanes == ["gemini-a"]
    assert all(p == "gemini-a" for p in plan.profile_by_agent.values())

    # Two available lanes ⇒ round-robin; same legend ⇒ same plan (determinism).
    legend2 = [
        {"name": "g1", "model_id": "gemini-1", "available": True},
        {"name": "g2", "model_id": "gemini-2", "available": True},
    ]
    plan2 = build_cast_plan(cfg, legend2, "gemini")
    assert [plan2.profile_by_agent[f"A{i}"] for i in range(5)] == [
        "g1", "g2", "g1", "g2", "g1"]
    plan3 = build_cast_plan(cfg, legend2, "gemini")
    assert plan3.profile_by_agent == plan2.profile_by_agent


def test_build_cast_plan_prefers_available_then_falls_back():
    cfg = _cast_cfg(1)
    # gemini has one available (gemini-a) and one unavailable (gemini-b) lane
    plan = build_cast_plan(cfg, _LEGEND, "gemini")
    assert plan.lanes == ["gemini-a"]
    # A family with NO available lane still casts from its full pool.
    legend = [{"name": "g-down", "model_id": "gemini-9", "available": False}]
    plan2 = build_cast_plan(cfg, legend, "gemini")
    assert plan2.lanes == ["g-down"]


def test_build_cast_plan_rejects_unknown_and_uncastable():
    with pytest.raises(ValueError, match="unknown family"):
        build_cast_plan(_cast_cfg(), _LEGEND, "bogus")
    with pytest.raises(ValueError, match="cannot be cast"):
        build_cast_plan(_cast_cfg(), _LEGEND, "other")
    with pytest.raises(ValueError, match="required"):
        build_cast_plan(_cast_cfg(), _LEGEND, "  ")


def test_build_cast_plan_does_not_mutate_the_base_config():
    cfg = _cast_cfg(2)
    before = [(a.name, a.profile) for a in cfg.agents]
    build_cast_plan(cfg, _LEGEND, "gemini")
    assert [(a.name, a.profile) for a in cfg.agents] == before


def test_build_cast_plan_preserves_agent_identity():
    cfg = _cast_cfg(2)
    plan = build_cast_plan(cfg, _LEGEND, "llama")
    a = plan.config.agents[0]
    assert (a.name, a.personality, a.location, a.cadence_tier) == ("A0", "p0", "plaza", "protagonist")
    assert a.profile == "llama-x"


def test_validate_tournament_request_normalizes_and_bounds():
    fams, ticks = validate_tournament_request([" Gemini ", "llama", "gemini"], 10)
    assert fams == ["gemini", "llama"]  # deduped, order kept, normalized
    assert ticks == 10
    with pytest.raises(ValueError):
        validate_tournament_request([], 10)
    with pytest.raises(ValueError):
        validate_tournament_request(["  ", ""], 10)
    with pytest.raises(ValueError):
        validate_tournament_request([f"fam{i}" for i in range(9)], 10)  # >8 distinct
    with pytest.raises(ValueError):
        validate_tournament_request(["gemini"], 0)
    with pytest.raises(ValueError):
        validate_tournament_request(["gemini"], 501)


class FakeLoop:
    """Records reset() casts; steps advance a fake world tick instantly."""

    def __init__(self, stall: bool = False, explode_on_reset: Exception | None = None):
        self.resets: list[tuple[object, str | None]] = []
        self._world = SimpleNamespace(tick=0)
        self._run_id = 0
        self._stall = stall
        self._explode = explode_on_reset

    async def reset(self, config, *, model_family=None):
        if self._explode is not None:
            raise self._explode
        self.resets.append((config, model_family))
        self._run_id += 100
        self._world.tick = 0

    async def step_and_wait(self, timeout: float = 5.0) -> int:
        if not self._stall:
            self._world.tick += 1
        return self._world.tick


@pytest.mark.asyncio
async def test_runner_sweeps_families_sequentially():
    from petridish.api.tournament import TournamentRunner

    loop = FakeLoop()
    cfg = _cast_cfg(3)

    class FakeRouter:
        def legend(self):
            return _LEGEND

    runner = TournamentRunner(loop=loop, config=cfg, router=FakeRouter(),
                              families=["gemini", "llama"], ticks_per_family=3)
    runner.start()
    await runner.wait()

    assert runner.state.status == "done"
    assert [f for _, f in loop.resets] == ["gemini", "llama"]
    assert loop.resets[0][0] is not cfg.agents and len(loop.resets[0][0].agents) == 3
    assert [r.family for r in runner.state.results] == ["gemini", "llama"]
    assert [r.ticks_run for r in runner.state.results] == [3, 3]
    assert all(r.status == "done" for r in runner.state.results)
    assert runner.state.current_family is None  # cleaned up at settle


@pytest.mark.asyncio
async def test_runner_abort_skips_remaining_families():
    from petridish.api.tournament import TournamentRunner

    loop = FakeLoop()
    cfg = _cast_cfg(2)

    class FakeRouter:
        def legend(self):
            return _LEGEND

    runner = TournamentRunner(loop=loop, config=cfg, router=FakeRouter(),
                              families=["gemini", "llama"],
                              ticks_per_family=10)

    # Abort after the 2nd step of family 1 — checked at the top of each step.
    _orig = loop.step_and_wait

    async def aborting_step(timeout: float = 5.0) -> int:
        out = await _orig(timeout)
        if loop._world.tick >= 2:
            runner.abort()
        return out

    loop.step_and_wait = aborting_step  # type: ignore[method-assign]
    runner.start()
    await runner.wait()

    assert runner.state.status == "aborted"
    assert [f for _, f in loop.resets] == ["gemini"]  # llama never reset
    res = runner.state.results
    assert len(res) == 1 and res[0].status == "aborted" and res[0].ticks_run == 2


@pytest.mark.asyncio
async def test_runner_marks_a_stalled_family_and_moves_on():
    from petridish.api.tournament import TournamentRunner

    loop = FakeLoop(stall=True)  # steps never advance the tick
    cfg = _cast_cfg(2)

    class FakeRouter:
        def legend(self):
            return _LEGEND

    runner = TournamentRunner(loop=loop, config=cfg, router=FakeRouter(),
                              families=["gemini", "llama"], ticks_per_family=50)
    runner.start()
    await runner.wait()

    assert runner.state.status == "done"
    assert [r.status for r in runner.state.results] == ["stalled", "stalled"]
    assert "no tick progress" in runner.state.results[0].note


@pytest.mark.asyncio
async def test_runner_reports_error_status_and_settles():
    from petridish.api.tournament import TournamentRunner

    loop = FakeLoop(explode_on_reset=RuntimeError("cast boom"))
    cfg = _cast_cfg(2)

    class FakeRouter:
        def legend(self):
            return _LEGEND

    runner = TournamentRunner(loop=loop, config=cfg, router=FakeRouter(),
                              families=["gemini", "llama"], ticks_per_family=3)
    runner.start()
    await runner.wait()

    assert runner.state.status == "error"
    assert "cast boom" in (runner.state.error or "")
    assert runner.state.results == []  # failed before the first family ran
    assert not runner.running()


@pytest.mark.asyncio
async def test_runner_over_the_real_loop_stamps_and_ends_runs():
    """The real TickLoop path: each family's reset ENDS the previous run row,
    so finished families land in the run browser as complete stamped runs."""
    from petridish.api.tournament import TournamentRunner

    loop, repo = _real_loop(("A", "B"))
    boot_run = loop._run_id
    cfg = WorldConfig(
        world=_arena_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[
            AgentConfig(name="A", personality="", profile="mock", location="plaza"),
            AgentConfig(name="B", personality="", profile="mock", location="plaza"),
        ],
    )

    class FakeRouter:
        def legend(self):
            return _LEGEND

    runner = TournamentRunner(loop=loop, config=cfg, router=FakeRouter(),
                              families=["gemini", "llama"],
                              ticks_per_family=3, step_timeout=30.0)
    runner.start()
    await runner.wait()

    assert runner.state.status == "done"
    rows = {r["id"]: r for r in repo.list_runs()}
    fam_runs = [r for r in rows.values() if r["model_family"]]
    assert sorted(r["model_family"] for r in fam_runs) == ["gemini", "llama"]
    assert rows[boot_run]["model_family"] is None  # boot run stays un-stamped
    # reset ends each previous run: boot + first family are 'ended'
    assert rows[boot_run]["status"] == "ended"
    gemini_run = next(r for r in fam_runs if r["model_family"] == "gemini")
    assert gemini_run["status"] == "ended"


# ──────────────────────────────────────────────────────────────────────────────
# 5. arena.py — aggregation from seeded events
# ──────────────────────────────────────────────────────────────────────────────


def _seed_run(repo: SQLiteRepository, family: str | None, *, spawns: int = 2,
              deaths: int = 0, laws: int = 0, buildings: int = 0, crimes: int = 0,
              credits: int = 0) -> int:
    rid = repo.start_run(json_cfg({}), model_family=family)
    for i in range(spawns):
        repo.save_event(rid, {"kind": "agent_spawned", "actor_id": f"a{i}",
                              "profile": "x", "payload": {}}, 0)
    for i in range(deaths):
        repo.save_event(rid, {"kind": "agent_died", "actor_id": f"a{i}",
                              "profile": "x", "payload": {}}, 5)
    for _ in range(laws):
        repo.save_event(rid, {"kind": "rule_passed", "payload": {"rule_id": f"r{time.time_ns()}"
                                  if False else laws}}, 3)
    for _ in range(buildings):
        repo.save_event(rid, {"kind": "building_operational", "payload": {}}, 4)
    for _ in range(crimes):
        repo.save_event(rid, {"kind": "action_resolved", "actor_id": "a0",
                              "profile": "x", "payload": {"action": "steal"}}, 6)
    if credits:
        repo.save_event(rid, {"kind": "economy", "actor_id": "a0", "profile": "x",
                              "payload": {"action": "give", "actor_credits": credits}}, 7)
    return rid


def test_arena_summary_groups_outcomes_and_means(tmp_path):
    from petridish.api.arena import arena_summary

    repo = SQLiteRepository(str(tmp_path / "arena.sqlite"))
    g1 = _seed_run(repo, "gemini", laws=2, buildings=1, crimes=1, credits=50, deaths=1)
    g2 = _seed_run(repo, "gemini", laws=0, buildings=2, crimes=0, credits=10)
    l1 = _seed_run(repo, "llama", laws=1, buildings=0, crimes=3, credits=7)
    _seed_run(repo, None)  # un-stamped: never appears

    out = arena_summary(repo)
    fams = {f["family"]: f for f in out["families"]}
    assert set(fams) == {"gemini", "llama"}
    # Families ordered by their EARLIEST stamped run (chronological cast order);
    # runs within a family are newest-first (the run browser's order).
    assert [f["family"] for f in out["families"]] == ["gemini", "llama"]

    gem = fams["gemini"]
    assert [r["run_id"] for r in gem["runs"]] == [g2, g1]
    # Family means: laws (2+0)/2 = 1.0; buildings (1+2)/2 = 1.5; credits 30.0
    assert gem["avg_per_run"]["laws_passed"] == 1.0
    assert gem["avg_per_run"]["buildings"] == 1.5
    assert gem["avg_per_run"]["credits"] == 30.0
    assert gem["avg_per_run"]["crimes"] == 0.5

    r2, r1 = gem["runs"]  # newest-first: r2 = g2, r1 = g1
    assert r1["outcomes"]["laws_passed"] == 2
    assert r1["outcomes"]["buildings"] == 1
    assert r1["outcomes"]["crimes"] == 1
    assert r1["outcomes"]["credits"] == 50
    # 2 spawns - 1 death ⇒ final population 1
    assert r1["outcomes"]["population"] == 1
    assert r2["outcomes"]["laws_passed"] == 0
    assert fams["llama"]["runs"][0]["outcomes"]["crimes"] == 3

    # Sparklines: alive series from spawn/death events, tick-sorted.
    assert r1["population_sparkline"][0]["alive"] >= 1
    assert r1["population_sparkline"][-1]["alive"] == 1


def test_arena_sparkline_downsamples_to_cap(tmp_path):
    from petridish.api.arena import _downsample

    points = [{"tick": t, "alive": t % 3} for t in range(200)]
    out = _downsample(points)
    assert len(out) <= 48
    assert out[0] == points[0] and out[-1] == points[-1]
    ticks = [p["tick"] for p in out]
    assert ticks == sorted(ticks)


def test_arena_summary_empty_and_zero_event_runs(tmp_path):
    from petridish.api.arena import arena_summary

    repo = SQLiteRepository(str(tmp_path / "empty.sqlite"))
    # EM-334 — the payload gains the additive `contact_runs` section.
    # `routes` is the EM-351 cross-run lane rollup — empty here, no lane activity.
    # EM-352 — `chronic_rule` is the rule behind `routes[].chronic`; EM-353 —
    # `lane_curves` echoes the opt-in gate (off by default).
    assert arena_summary(repo) == {
        "families": [], "contact_runs": [], "routes": [],
        "chronic_rule": {"rate_threshold": 0.20, "min_runs": 2},
        "lane_curves": False,
    }
    _seed_run(repo, "gemini", spawns=0)  # a stamped run with NO events
    out = arena_summary(repo)
    assert out["families"][0]["avg_per_run"] == {
        "population": 0.0, "laws_passed": 0.0, "buildings": 0.0,
        "crimes": 0.0, "credits": 0.0,
    }


def test_population_falls_back_to_latest_snapshot(tmp_path):
    """A seeded-roster run emits no spawn/death events — the population card
    floors on the LATEST snapshot's alive-agent count (the get_analytics
    credits-fallback idiom)."""
    import json as _json

    from petridish.api.arena import arena_summary

    repo = SQLiteRepository(str(tmp_path / "snap.sqlite"))
    rid = _seed_run(repo, "gemini", spawns=0)  # no population events
    repo.save_world_snapshot(
        rid, 2,
        _json.dumps({"agents": [
            {"id": "a1", "alive": True}, {"id": "a2"},
            {"id": "a3", "alive": False},
        ]}),
    )
    repo.save_world_snapshot(
        rid, 4, _json.dumps({"agents": [{"id": "a1", "alive": True}]}),
    )  # LATEST snapshot wins
    out = arena_summary(repo)
    r = out["families"][0]["runs"][0]
    assert r["outcomes"]["population"] == 1

    # No snapshots at all ⇒ stays 0 (never a crash).
    rid2 = _seed_run(repo, "llama", spawns=0)
    out2 = arena_summary(repo)
    r2 = next(x for f in out2["families"] for x in f["runs"] if x["run_id"] == rid2)
    assert r2["outcomes"]["population"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# 6. API endpoints (TestClient, patched boot config with mock-adapter lanes)
# ──────────────────────────────────────────────────────────────────────────────

_TEST_PROFILES = [
    ModelProfile(name="gemini-x", adapter="mock", model_id="gemini-3.5-flash", color="#111111"),
    ModelProfile(name="llama-x", adapter="mock", model_id="llama-3.3-70b-fp8-fast", color="#222222"),
    ModelProfile(name="qwen-x", adapter="mock", model_id="qwen3-next-80b", color="#333333"),
    ModelProfile(name="auto", adapter="mock", model_id="auto", color="#444444"),
    ModelProfile(name="mock", adapter="mock", model_id="mock", color="#555555"),
]


@pytest.fixture
def arena_client(monkeypatch):
    """The real app booted on a config whose PROFILES are mock-adapter lanes
    spanning three families — tournament steps run offline at mock speed."""
    from fastapi.testclient import TestClient

    import petridish.api.app as _app_pkg  # noqa: F401  (ensures the module is loaded)
    appmod = sys.modules["petridish.api.app"]

    base = load_config()
    agents = [
        AgentConfig(name=a.name, personality=a.personality, profile="mock",
                    location=a.location)
        for a in base.agents[:5]
    ]
    assert agents, "the boot roster must not be empty"
    patched = dataclasses.replace(base, profiles=_TEST_PROFILES, agents=agents)
    monkeypatch.setattr(appmod, "load_config", lambda *a, **k: patched)
    monkeypatch.setattr(appmod, "_tournament", None)

    with TestClient(appmod.app, raise_server_exceptions=True) as client:
        yield client, appmod


def _await_tournament(client, deadline_s: float = 60.0) -> dict:
    end = time.time() + deadline_s
    status: dict = {}
    while time.time() < end:
        status = client.get("/api/arena/tournament").json()
        if status["status"] in ("done", "aborted", "error"):
            return status
        time.sleep(0.05)
    raise AssertionError(f"tournament never settled: {status}")


def test_tournament_end_to_end_two_families(arena_client):
    client, appmod = arena_client

    # Fresh boot: no stamped runs ⇒ empty arena.
    # EM-334 — the payload gains the additive `contact_runs` section.
    # EM-352/353 — plus the `chronic_rule` and the `lane_curves` gate echo.
    assert client.get("/api/arena").json() == {
        "families": [], "contact_runs": [], "routes": [],
        "chronic_rule": {"rate_threshold": 0.20, "min_runs": 2},
        "lane_curves": False,
    }
    # EM-353 — the curves are opt-in on the endpoint itself: the same empty
    # arena asked for curves echoes the flag (and stays equally empty).
    assert client.get("/api/arena?lane_curves=1").json()["lane_curves"] is True
    assert client.get("/api/arena/tournament").json()["status"] == "idle"

    body = client.post(
        "/api/arena/tournament",
        json={"families": ["gemini", "llama"], "ticks_per_family": 3},
    )
    assert body.status_code == 202, body.text
    started = body.json()
    assert started["families"] == ["gemini", "llama"]
    assert set(started["casts"]["gemini"].values()) == {"gemini-x"}
    assert set(started["casts"]["llama"].values()) == {"llama-x"}

    status = _await_tournament(client)
    assert status["status"] == "done", status
    assert [r["family"] for r in status["results"]] == ["gemini", "llama"]
    assert all(r["ticks_run"] == 3 for r in status["results"])

    # Every tournament run is family-stamped; the boot run is not.
    rows = client.get("/api/runs").json()
    stamped = {r["id"]: r["model_family"] for r in rows if r.get("model_family")}
    assert set(stamped.values()) == {"gemini", "llama"}

    # The arena aggregates both families with ≥1 run each.
    arena = client.get("/api/arena").json()
    fams = {f["family"]: f for f in arena["families"]}
    assert set(fams) == {"gemini", "llama"}
    assert all(len(f["runs"]) >= 1 for f in fams.values())

    # A settled tournament no longer owns the loop: reset is allowed again,
    # and DELETE on the settled runner is a 409.
    assert client.delete("/api/arena/tournament").status_code == 409
    assert client.post("/api/control/reset").status_code == 200


def test_tournament_fork_inherits_family_stamp(arena_client):
    client, appmod = arena_client
    assert client.post(
        "/api/arena/tournament",
        json={"families": ["gemini"], "ticks_per_family": 2},
    ).status_code == 202
    status = _await_tournament(client)
    assert status["status"] == "done", status

    rows = client.get("/api/runs").json()
    gem_run = next(r["id"] for r in rows if r.get("model_family") == "gemini")
    fork = client.post("/api/runs/fork", json={"run_id": gem_run, "tick": 1})
    assert fork.status_code == 201, fork.text
    child_id = fork.json()["run_id"]
    child = client.get("/api/runs").json()
    assert next(r for r in child if r["id"] == child_id)["model_family"] == "gemini"


def test_tournament_request_validation_and_guards(arena_client):
    client, appmod = arena_client

    # Unknown family / the un-castable "other" bucket.
    r = client.post("/api/arena/tournament", json={"families": ["bogus"]})
    assert r.status_code == 400 and "unknown family" in r.json()["detail"]
    r = client.post("/api/arena/tournament", json={"families": ["other"]})
    assert r.status_code == 400 and "cannot be cast" in r.json()["detail"]
    # pydantic bounds: ticks out of range → 422; empty families → 422.
    assert client.post("/api/arena/tournament",
                       json={"families": ["gemini"], "ticks_per_family": 0}
                       ).status_code == 422
    assert client.post("/api/arena/tournament",
                       json={"families": []}).status_code == 422
    # Abort with nothing running → 409.
    assert client.delete("/api/arena/tournament").status_code == 409


def test_running_tournament_guards_reset_fork_and_restart(arena_client):
    client, appmod = arena_client

    class StubRunning:
        def __init__(self):
            self.aborted = False

        def running(self):
            return True

        def abort(self):
            self.aborted = True

    stub = StubRunning()
    appmod._tournament = stub  # type: ignore[assignment]
    try:
        assert client.post("/api/control/reset").status_code == 409
        assert client.post("/api/runs/fork",
                           json={"run_id": 1, "tick": 0}).status_code == 409
        assert client.post(
            "/api/arena/tournament",
            json={"families": ["gemini"], "ticks_per_family": 2},
        ).status_code == 409
        assert client.delete("/api/arena/tournament").json() == {"status": "aborting"}
        assert stub.aborted
    finally:
        appmod._tournament = None

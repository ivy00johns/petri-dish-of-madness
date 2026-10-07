"""EM-344/345/346/347 — the failure-taxonomy read-out expansion.

EM-344 moved the taxonomy into `petridish.taxonomy` (a leaf module) so the API
layer reads it WITHOUT depending on the agent runtime.

EM-345/346/347 extend the per-run `failures` read-out the Arena panel renders:
  • EM-345 `curve`    — the failures OVER TICKS as even-width bucket SUMS, so a
    one-tick provider outage survives the downsample as a tall bar;
  • EM-346 `by_agent` — the same taxonomy per `actor_id`, the "which agent
    fails differently" cut;
  • EM-347            — the per-FAMILY pooled rollup on `arena_summary`.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime
(the circular-import guard).
"""
from __future__ import annotations

import importlib
import inspect
import json

from petridish.engine.world import World  # noqa: F401 — must precede agents.runtime
from petridish.api.arena import (  # noqa: E402
    arena_summary,
    failure_taxonomy,
    run_outcomes,
)
from petridish.persistence.repository import SQLiteRepository  # noqa: E402


def _run(repo: SQLiteRepository, *, family: str | None = "gemini",
         contact: bool = False) -> int:
    world: dict = {}
    if contact:
        world = {"contact": {"enabled": True, "family_a": "gemini", "family_b": "llama"}}
    return repo.start_run(json.dumps({"world": world}), model_family=family)


def _ev(repo: SQLiteRepository, rid: int, kind: str, tick: int,
        actor: str = "agent_a", payload: dict | None = None) -> None:
    repo.save_event(
        rid, {"kind": kind, "payload": payload or {}, "profile": "x",
              "actor_id": actor}, tick)


# ── EM-344 — the taxonomy is a shared leaf module, not runtime-owned ─────────

def test_taxonomy_is_the_shared_home_not_the_agent_runtime():
    taxonomy = importlib.import_module("petridish.taxonomy")
    runtime = importlib.import_module("petridish.agents.runtime")
    arena = importlib.import_module("petridish.api.arena")

    # The emit path's names ARE the taxonomy module's functions (aliased), so
    # both halves route through ONE classifier.
    assert runtime._failure_kind_for is taxonomy.failure_kind_for
    assert runtime._is_failure_kind is taxonomy.is_failure_kind
    assert runtime.true_failure_kind is taxonomy.true_failure_kind

    # The READ side imports the leaf module — the API layer no longer depends on
    # the agent runtime for the taxonomy.
    assert arena.true_failure_kind is taxonomy.true_failure_kind
    src = inspect.getsource(arena)
    assert "agents.runtime" not in src, "api/arena.py must not import the agent runtime"


# ── EM-345 — the per-turn failure curve ──────────────────────────────────────

def test_curve_buckets_sum_so_a_one_tick_spike_survives(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "curve.sqlite"))
    rid = _run(repo)
    # a single-tick provider outage at tick 900 (25 rows at ONE tick) ...
    for _ in range(25):
        _ev(repo, rid, "provider_error", 900, "agent_a", {"reason": "provider_error: 502"})
    # ... plus one early rejection, and a late llm_call to anchor max_tick=1000
    _ev(repo, rid, "parse_failure", 5, "agent_a", {"rejected": True, "action": "give"})
    _ev(repo, rid, "llm_call", 1000, "agent_a")

    t = failure_taxonomy(repo, rid)
    curve = t["curve"]

    assert 2 <= len(curve) <= 48                    # downsampled to ≤48 buckets
    # every failure lands in exactly one bucket (bucket sums == run counts)
    assert sum(p["provider_error"] for p in curve) == 25
    assert sum(p["action_rejected"] for p in curve) == 1
    assert sum(p["parse_failure"] for p in curve) == 0
    # the spike is ONE tall bucket — an even-spaced POINT sample would drop it
    assert max(p["provider_error"] for p in curve) == 25


def test_curve_shapes_and_zero_state(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "curve2.sqlite"))
    rid = _run(repo)
    # no failures at all ⇒ no curve
    assert failure_taxonomy(repo, rid)["curve"] == []

    # a failure with a run span SHORTER than the cap ⇒ one bucket per tick
    _ev(repo, rid, "provider_error", 0, "agent_a", {"reason": "provider_error: x"})
    _ev(repo, rid, "provider_error", 2, "agent_a", {"reason": "provider_error: x"})
    t = failure_taxonomy(repo, rid)
    assert len(t["curve"]) == 3                     # ticks 0, 1, 2
    assert [p["tick"] for p in t["curve"]] == [0, 1, 2]
    assert [p["provider_error"] for p in t["curve"]] == [1, 0, 1]


# ── EM-346 — the per-agent cut ───────────────────────────────────────────────

def test_by_agent_rates_separate_a_broken_route_from_a_shared_outage(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "agents.sqlite"))
    rid = _run(repo)
    # agent_ada: a broken route — EVERY turn fails
    for i in range(3):
        _ev(repo, rid, "parse_failure", i, "agent_ada", {"reason": "no valid JSON"})
        _ev(repo, rid, "llm_call", i, "agent_ada")
    # agent_mox: healthy — 1 failure in 10 turns
    _ev(repo, rid, "parse_failure", 0, "agent_mox", {"reason": "no valid JSON"})
    for i in range(10):
        _ev(repo, rid, "llm_call", i, "agent_mox")
    # a clean non-human actor (an animal) with turns but no failures
    for i in range(4):
        _ev(repo, rid, "llm_call", i, "animal_biscuit")

    ba = failure_taxonomy(repo, rid)["by_agent"]

    assert list(ba) == sorted(ba)                    # deterministic order
    assert set(ba) == {"agent_ada", "agent_mox", "animal_biscuit"}
    assert ba["agent_ada"]["total"] == 3
    assert ba["agent_ada"]["turns"] == 3
    assert ba["agent_ada"]["failure_rate"] == 1.0    # 3/3 — the route is broken
    assert ba["agent_mox"]["failure_rate"] == 0.1    # 1/10 — healthy
    # a clean agent stays listed (0, not hidden) so the spread is readable
    assert ba["animal_biscuit"]["total"] == 0
    assert ba["animal_biscuit"]["turns"] == 4
    assert ba["animal_biscuit"]["failure_rate"] == 0.0
    assert ba["agent_ada"]["counts"] == {
        "action_rejected": 0, "provider_error": 0, "parse_failure": 3,
    }
    assert ba["agent_ada"]["shares"]["parse_failure"] == 1.0


# ── EM-348 — the per-agent route attribution ─────────────────────────────────

def test_by_agent_names_the_route_behind_each_agents_failures(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "routes.sqlite"))
    rid = _run(repo)
    # agent_ada: 3 failures — 2 on ONE bad lane, 1 with no routed_via
    _ev(repo, rid, "provider_error", 1, "agent_ada",
        {"reason": "provider_error: 502",
         "routed_via": "kilo/inclusionai/ling-3.0-flash-sante:free"})
    _ev(repo, rid, "parse_failure", 2, "agent_ada",
        {"reason": "no valid JSON",
         "routed_via": "kilo/inclusionai/ling-3.0-flash-sante:free"})
    _ev(repo, rid, "action_rejected", 3, "agent_ada",
        {"rejected": True, "action": "give"})
    # agent_cleo: a SECOND lane, ordered descending by failure count
    _ev(repo, rid, "provider_error", 1, "agent_cleo",
        {"reason": "provider_error: x", "routed_via": "lane/bbb"})
    for _ in range(3):
        _ev(repo, rid, "parse_failure", 2, "agent_cleo",
            {"reason": "no valid JSON", "routed_via": "lane/aaa"})
    for i in range(6):
        _ev(repo, rid, "llm_call", i, "agent_ada")
    for i in range(4):
        _ev(repo, rid, "llm_call", i, "agent_cleo")

    ba = failure_taxonomy(repo, rid)["by_agent"]
    ada = ba["agent_ada"]
    assert ada["total"] == 3
    assert ada["top_route"] == "kilo/inclusionai/ling-3.0-flash-sante:free"
    # only the rows that NAMED a lane are attributed — coverage stays honest
    assert ada["routes_attributed"] == 2
    assert ada["routes"] == {"kilo/inclusionai/ling-3.0-flash-sante:free": 2}
    # a multi-lane agent orders its routes by descending failure count
    assert list(ba["agent_cleo"]["routes"]) == ["lane/aaa", "lane/bbb"]
    assert ba["agent_cleo"]["routes_attributed"] == 4


def test_clean_agent_has_no_route_and_a_nameless_row_falls_back(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "routes2.sqlite"))
    rid = _run(repo)
    # a failure whose payload carries no routed_via (pre-diagnostic row)
    _ev(repo, rid, "provider_error", 1, "agent_ada", {"reason": "provider_error: x"})
    _ev(repo, rid, "llm_call", 1, "agent_ada")
    # a clean agent with turns only
    for i in range(2):
        _ev(repo, rid, "llm_call", i, "animal_mochi")

    ba = failure_taxonomy(repo, rid)["by_agent"]
    assert ba["agent_ada"]["top_route"] == ""
    assert ba["agent_ada"]["routes"] == {}
    assert ba["agent_ada"]["routes_attributed"] == 0
    assert ba["animal_mochi"]["top_route"] == ""
    assert ba["animal_mochi"]["total"] == 0


# ── EM-349 — the per-lane failure rate ───────────────────────────────────────

def test_by_route_rates_each_lane_against_its_own_attempts(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "lanes.sqlite"))
    rid = _run(repo)
    # lane A: 2 failures across 8 attempts
    for _ in range(2):
        _ev(repo, rid, "provider_error", 1, "agent_a",
            {"reason": "provider_error: x", "routed_via": "lane/aaa"})
    for _ in range(8):
        _ev(repo, rid, "llm_call", 1, "agent_a",
            {"gen_ai.response.model": "lane/aaa"})
    # lane B: fewer failures but a BETTER rate (the point of a rate, not volume)
    _ev(repo, rid, "parse_failure", 1, "agent_a",
        {"reason": "no valid JSON", "routed_via": "lane/bbb"})
    for _ in range(10):
        _ev(repo, rid, "llm_call", 1, "agent_a",
            {"gen_ai.response.model": "lane/bbb"})
    # a lane used but never failing is listed too (it is not bad)
    for _ in range(4):
        _ev(repo, rid, "llm_call", 1, "agent_a",
            {"gen_ai.response.model": "lane/ccc"})

    t = failure_taxonomy(repo, rid)
    br = t["by_route"]
    assert (br["lane/aaa"]["failures"], br["lane/aaa"]["attempts"],
            br["lane/aaa"]["failure_rate"]) == (2, 8, 0.25)
    assert (br["lane/bbb"]["failures"], br["lane/bbb"]["attempts"],
            br["lane/bbb"]["failure_rate"]) == (1, 10, 0.1)
    assert (br["lane/ccc"]["failures"], br["lane/ccc"]["attempts"],
            br["lane/ccc"]["failure_rate"]) == (0, 4, 0.0)
    # worst rate first — the lane with MORE failures also has the worse rate here
    assert list(br) == ["lane/aaa", "lane/bbb", "lane/ccc"]
    assert t["failures_attributed"] == 3
    assert t["attempts_attributed"] == 22
    # EM-350: every lane also carries a curve on the run curve's tick plan, and
    # the buckets sum back to the scalars exactly (nothing lost in bucketing)
    run_ticks = [b["tick"] for b in t["curve"]]
    for lane_stat in br.values():
        assert [b["tick"] for b in lane_stat["curve"]] == run_ticks
        assert sum(b["failures"] for b in lane_stat["curve"]) == lane_stat["failures"]
        assert sum(b["attempts"] for b in lane_stat["curve"]) == lane_stat["attempts"]


def test_by_route_edge_cases(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "lanes2.sqlite"))
    rid = _run(repo)
    # nothing at all ⇒ no lanes, no coverage claim
    t = failure_taxonomy(repo, rid)
    assert t["by_route"] == {}
    assert t["failures_attributed"] == 0 and t["attempts_attributed"] == 0

    # a failure whose lane never recorded an attempt: listed, attempts 0
    _ev(repo, rid, "provider_error", 1, "agent_a",
        {"reason": "provider_error: x", "routed_via": "lane/ghost"})
    t2 = failure_taxonomy(repo, rid)
    ghost = t2["by_route"]["lane/ghost"]
    assert (ghost["failures"], ghost["attempts"], ghost["failure_rate"]) == (1, 0, 0.0)
    assert t2["failures_attributed"] == 1 and t2["attempts_attributed"] == 0

    # an attempt with no `gen_ai.response.model` is not attributed to a lane
    _ev(repo, rid, "llm_call", 1, "agent_a", {})
    t3 = failure_taxonomy(repo, rid)
    assert t3["attempts_attributed"] == 0
    assert t3["turns"] == 1


# ── EM-350 — the per-lane rate curve ─────────────────────────────────────────

def test_by_route_carries_a_rate_curve_that_shows_a_mid_run_degradation(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "lanecurve.sqlite"))
    rid = _run(repo)
    lane = {"gen_ai.response.model": "lane/aaa"}
    # healthy early (ticks 10-20), then failures LATE (ticks 90-95)
    for tick in (10, 20, 90, 95, 100):
        _ev(repo, rid, "llm_call", tick, "agent_a", lane)
    for tick in (90, 95):
        _ev(repo, rid, "provider_error", tick, "agent_a",
            {"reason": "provider_error: x", "routed_via": "lane/aaa"})

    t = failure_taxonomy(repo, rid)
    stat = t["by_route"]["lane/aaa"]
    assert stat["failures"] == 2 and stat["attempts"] == 5
    curve = stat["curve"]
    # shares the run curve's bucket plan, tick for tick
    assert [b["tick"] for b in curve] == [b["tick"] for b in t["curve"]]
    assert sum(b["attempts"] for b in curve) == 5
    assert sum(b["failures"] for b in curve) == 2
    # the failures sit in the SECOND half of the run, not the first — i.e. the
    # single pooled rate could not show this, the curve does
    assert all(b["failures"] == 0 for b in curve[: len(curve) // 2])
    assert any(b["failures"] for b in curve[len(curve) // 2:])


def test_lane_curves_are_capped_to_the_busiest_lanes(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "lanecap.sqlite"))
    rid = _run(repo)
    # seven lanes with descending volume; only the busiest six get a curve
    for i in range(7):
        for _ in range(10 - i):
            _ev(repo, rid, "llm_call", 1, "agent_a",
                {"gen_ai.response.model": f"lane/{i}"})

    d = failure_taxonomy(repo, rid)["by_route"]
    assert len(d) == 7
    curved = [ln for ln, v in d.items() if v["curve"]]
    assert len(curved) == 6
    assert "lane/0" in curved and "lane/6" not in curved
    # every lane still has the scalar entry (curve [] is just "not charted")
    assert d["lane/6"]["curve"] == []
    assert d["lane/6"]["attempts"] == 4


# ── EM-351 — the cross-run lane rollup ───────────────────────────────────────

def test_arena_routes_pool_lane_failures_across_runs(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "crossrun.sqlite"))

    def seed(fam: str, lane: str, n_fail: int, n_attempt: int) -> int:
        rid = _run(repo, family=fam)
        for _ in range(n_fail):
            _ev(repo, rid, "provider_error", 1, "agent_a",
                {"reason": "provider_error: x", "routed_via": lane})
        for _ in range(n_attempt):
            _ev(repo, rid, "llm_call", 1, "agent_a", {"gen_ai.response.model": lane})
        return rid

    seed("gemini", "lane/x", 2, 8)
    seed("llama", "lane/x", 1, 12)
    seed("llama", "lane/y", 3, 3)

    routes = {r["lane"]: r for r in arena_summary(repo)["routes"]}
    # the SAME lane pooled over two runs (2/8 + 1/12), with its sample size
    assert routes["lane/x"] == {
        "lane": "lane/x", "failures": 3, "attempts": 20,
        "runs": 2, "failure_rate": 0.15,
    }
    assert routes["lane/y"]["runs"] == 1
    assert routes["lane/y"]["failure_rate"] == 1.0
    # worst pooled rate first, so a lane bad in one draw is not buried
    assert arena_summary(repo)["routes"][0]["lane"] == "lane/y"


def test_arena_routes_empty_arena(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "empty.sqlite"))
    assert arena_summary(repo)["routes"] == []


# ── EM-347 — the per-family rollup ───────────────────────────────────────────

def test_family_rollup_pools_counts_turns_and_rate(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "family.sqlite"))

    def seed(fam: str, rej: int, prov: int, parse: int, turns: int) -> int:
        rid = _run(repo, family=fam)
        for _ in range(rej):
            _ev(repo, rid, "action_rejected", 1, payload={"action": "x", "error": "y"})
        for _ in range(prov):
            _ev(repo, rid, "provider_error", 1, payload={"reason": "provider_error: x"})
        for _ in range(parse):
            _ev(repo, rid, "parse_failure", 1, payload={"reason": "no valid JSON"})
        for _ in range(turns):
            _ev(repo, rid, "llm_call", 1)
        return rid

    seed("gemini", 2, 1, 1, 10)
    seed("gemini", 0, 3, 0, 10)
    seed("llama", 0, 0, 0, 5)

    out = arena_summary(repo)
    by_fam = {f["family"]: f for f in out["families"]}

    gem = by_fam["gemini"]["failures"]
    assert gem["counts"] == {"action_rejected": 2, "provider_error": 4, "parse_failure": 1}
    assert gem["total"] == 7
    assert gem["turns"] == 20
    assert gem["failure_rate"] == 0.35               # 7 pooled / 20 pooled turns
    assert gem["shares"]["provider_error"] == 0.5714  # 4 / 7
    assert gem["runs"] == 2

    # a family whose runs had no failures rolls up to zeros, not a crash
    llama = by_fam["llama"]["failures"]
    assert llama["total"] == 0 and llama["turns"] == 5 and llama["failure_rate"] == 0.0
    assert llama["counts"] == {"action_rejected": 0, "provider_error": 0, "parse_failure": 0}


def test_run_and_contact_cards_carry_curve_and_by_agent(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "cards.sqlite"))
    rid = _run(repo)
    _ev(repo, rid, "provider_error", 3, "agent_a", {"reason": "provider_error: x"})
    _ev(repo, rid, "llm_call", 3, "agent_a")

    card = run_outcomes(repo, rid, 10)
    assert isinstance(card["failures"]["curve"], list) and card["failures"]["curve"]
    assert card["failures"]["by_agent"]["agent_a"]["total"] == 1
    # EM-349 — the per-lane board rides the same block
    assert "by_route" in card["failures"]
    assert card["failures"]["failures_attributed"] == 0  # this row named no lane

    contact = _run(repo, family=None, contact=True)
    _ev(repo, contact, "provider_error", 1, "agent_b", {"reason": "provider_error: x"})
    _ev(repo, contact, "llm_call", 1, "agent_b")
    out = arena_summary(repo)
    cards = {c["run_id"]: c for c in out["contact_runs"]}
    assert cards[contact]["failures"]["by_agent"]["agent_b"]["failure_rate"] == 1.0
    assert "curve" in cards[contact]["failures"]

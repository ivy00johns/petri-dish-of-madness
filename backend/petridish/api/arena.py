"""EM-119 — the Model-Family Arena aggregation (zero-LLM, read-only).

Groups every run stamped with `runs.model_family` (the EM-112 tournament
stamps it at reset; forks inherit) into per-family blocks of
civilization-outcome cards + population sparklines, compared after the fact —
exactly the deep-research-v3 §40 vision ("side-by-side AWI sparklines per
family, civilization-outcome cards: population, laws passed, buildings built,
crimes, GDP/credits").

Sources, all already persisted (no new instrumentation):
  population   — analytics population series (spawn/death projection), last value
  laws_passed  — analytics.governance.passed (rule_passed events)
  buildings    — `building_operational` events (a completed collective project)
  crimes       — analytics.crime.by_kind total (steal/attack/insult/arson/…)
  credits      — analytics.economy.by_agent total (event-fed, snapshot fallback)

Heavy (full event fetch per run) — callers run it on a worker thread
(same blocking class as /api/fingerprints). Family-level numbers are MEANS
across the family's runs (avg/run), so a family with one run and a family
with three stay comparable. Runs with no events still appear (zeros).
"""

from __future__ import annotations

# Population sparklines are downsampled to this many points (first+last kept).
_MAX_SPARK_POINTS = 48

_BUILDINGS_KIND = "building_operational"


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _downsample(points: list[dict], cap: int = _MAX_SPARK_POINTS) -> list[dict]:
    """Evenly-spaced subset of the population series, first+last always kept,
    sorted by tick. `points` are {tick, alive} dicts (already numeric-typed by
    the caller's defensive parse)."""
    n = len(points)
    if n <= cap:
        return points
    out: list[dict] = []
    for i in range(cap):
        idx = (i * (n - 1)) // (cap - 1)
        p = points[idx]
        if not out or out[-1] != p:
            out.append(p)
    return out


def _as_num(v: object) -> float:
    return v if isinstance(v, (int, float)) else 0.0


def run_outcomes(repo, run_id: int, max_tick: int) -> dict:
    """Civilization-outcome card for ONE run (defensive: absent fields ⇒ 0)."""
    a = repo.get_analytics(run_id) or {}

    pop_series = a.get("population") if isinstance(a.get("population"), list) else []
    population = 0.0
    for p in reversed(pop_series):  # last event's alive count wins
        if isinstance(p, dict):
            population = _as_num(p.get("alive"))
            break
    if population == 0:
        # Projection gap: a seeded-roster run emits no spawn/death events, so
        # the population series is empty (or flat 0) even while the society is
        # alive. Fall back to the LATEST SNAPSHOT's alive-agent count — the
        # same projection-gap idiom get_analytics uses for credits. Snapshot
        # state has no per-agent alive concept here, so any listed agent counts.
        population = _as_num(repo.snapshot_agent_count(run_id))

    gov = a.get("governance") if isinstance(a.get("governance"), dict) else {}
    crime = a.get("crime") if isinstance(a.get("crime"), dict) else {}
    kinds = crime.get("by_kind") if isinstance(crime.get("by_kind"), dict) else {}
    economy = a.get("economy") if isinstance(a.get("economy"), dict) else {}
    by_agent = economy.get("by_agent") if isinstance(economy.get("by_agent"), dict) else {}

    spark: list[dict] = []
    for p in pop_series:
        if isinstance(p, dict):
            tick = p.get("tick")
            if isinstance(tick, (int, float)):
                spark.append({"tick": int(tick), "alive": int(_as_num(p.get("alive")))})
    spark.sort(key=lambda p: p["tick"])

    return {
        "run_id": run_id,
        "max_tick": int(max_tick or 0),
        "outcomes": {
            "population": population,
            "laws_passed": _as_num(gov.get("passed")),
            "buildings": _as_num(repo.count_events_of_kind(run_id, _BUILDINGS_KIND)),
            "crimes": sum(_as_num(v) for v in kinds.values()),
            "credits": sum(_as_num(v) for v in by_agent.values()),
        },
        "population_sparkline": _downsample(spark),
    }


def arena_summary(repo) -> dict:
    """The /api/arena payload: families (with ≥1 stamped run) ordered by their
    EARLIEST stamped run (the chronological cast order), each with its runs'
    outcome cards + sparklines and family means."""
    blocks: dict[str, list[dict]] = {}
    first_seen: dict[str, int] = {}
    for run in repo.list_runs():
        fam = run.get("model_family")
        if not fam:
            continue
        if fam not in blocks:
            blocks[fam] = []
            first_seen[fam] = run["id"]
        blocks[fam].append(run_outcomes(repo, run["id"], run.get("max_tick") or 0))

    families: list[dict] = []
    for fam in sorted(blocks, key=lambda f: first_seen[f]):
        runs = blocks[fam]
        keys = ("population", "laws_passed", "buildings", "crimes", "credits")
        means = {
            k: _mean([r["outcomes"][k] for r in runs]) for k in keys
        }
        families.append({
            "family": fam,
            "avg_per_run": means,
            "runs": runs,
        })
    return {"families": families}

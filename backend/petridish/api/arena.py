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


def _contact_block(run: dict) -> dict | None:
    """EM-334 — the run's ARMED contact block from its config_json (the run
    self-describes — the EM-332 endpoint arms the block on the reset config;
    no new persistence column). None when the run is not a contact run."""
    import json
    try:
        cfg = json.loads(run.get("config_json") or "{}")
    except (TypeError, ValueError):
        return None
    block = ((cfg.get("world") or {}).get("contact") or {}
             if isinstance(cfg, dict) else {})
    if not isinstance(block, dict) or not block.get("enabled"):
        return None
    return block


def contact_run_card(repo, run: dict, *, max_tick: int | None = None) -> dict:
    """EM-334 — ONE contact run's Arena card: the family pairing from the
    run's own config_json + the ordinary civilization-outcome card + the
    PER-SETTLEMENT populations read straight from the run's latest snapshot
    (settlements + agent homes — no new persistence) + the honesty ledger and
    the First Contact marker from the same snapshot + the crossing/travel
    event counts. Zero-LLM, read-only, defensive throughout."""
    run_id = int(run.get("id") or 0)
    block = _contact_block(run) or {}
    card: dict = {
        "run_id": run_id,
        "max_tick": int(max_tick if max_tick is not None
                        else (run.get("max_tick") or 0)),
        "family_a": str(block.get("family_a", "") or ""),
        "family_b": str(block.get("family_b", "") or ""),
        "name_b": str(block.get("name_b", "") or ""),
        "outcomes": run_outcomes(repo, run_id, max_tick if max_tick is not None
                                 else (run.get("max_tick") or 0))["outcomes"],
        "population_by_town": {},
        "contact_made": None,
        "ledger": None,
        "events": {
            "contact_made": int(repo.count_events_of_kind(run_id, "contact_made")),
            "meme_crossed_border": int(
                repo.count_events_of_kind(run_id, "meme_crossed_border")),
            "rumor_crossed_border": int(
                repo.count_events_of_kind(run_id, "rumor_crossed_border")),
            "travel_departed": int(
                repo.count_events_of_kind(run_id, "travel_departed")),
            "travel_arrived": int(
                repo.count_events_of_kind(run_id, "travel_arrived")),
        },
    }
    state = repo.latest_snapshot_state(run_id)
    if isinstance(state, dict):
        # Per-town alive populations: settlement membership is loose, the
        # agent's home_settlement_id is the durable side (EM-110).
        settlements = state.get("settlements")
        agents = state.get("agents")
        if isinstance(settlements, dict) and isinstance(agents, list):
            alive_by_home: dict[str, int] = {}
            for a in agents:
                if not isinstance(a, dict) or a.get("alive") is False:
                    continue
                home = str(a.get("home_settlement_id") or "")
                if home:
                    alive_by_home[home] = alive_by_home.get(home, 0) + 1
            for sid, st in settlements.items():
                if not isinstance(st, dict):
                    continue
                name = str(st.get("name", "")) or str(sid)
                members = st.get("members") or []
                card["population_by_town"][name] = alive_by_home.get(
                    str(sid), len(members) if isinstance(members, list) else 0)
        cm = state.get("contact_made")
        if isinstance(cm, dict):
            card["contact_made"] = {
                "tick": int(cm.get("tick", 0) or 0),
                "agent_id": str(cm.get("agent_id", "") or ""),
                "from_settlement": str(cm.get("from_settlement", "") or ""),
                "to_settlement": str(cm.get("to_settlement", "") or ""),
            }
        ledger = state.get("contact_ledger")
        if isinstance(ledger, dict) and ledger.get("crossings"):
            card["ledger"] = {
                "crossings": int(ledger.get("crossings", 0) or 0),
                "by_family": {
                    str(fam): {
                        "hops": int((rec or {}).get("hops", 0) or 0),
                        "mutated": int((rec or {}).get("mutated", 0) or 0),
                    }
                    for fam, rec in (ledger.get("by_family") or {}).items()
                    if isinstance(rec, dict)
                },
            }
    return card


def arena_summary(repo) -> dict:
    """The /api/arena payload: families (with ≥1 stamped run) ordered by their
    EARLIEST stamped run (the chronological cast order), each with its runs'
    outcome cards + sparklines and family means — plus EM-334's contact_runs:
    every run whose config_json carries an ARMED contact block, with the
    family pairing + per-settlement cards (the First Contact comparison)."""
    blocks: dict[str, list[dict]] = {}
    first_seen: dict[str, int] = {}
    contact_runs: list[dict] = []
    for run in repo.list_runs():
        # EM-334 — the contact pairing lives in runs.config_json, which
        # list_runs deliberately omits (the config_summary projection only).
        # One indexed full-row fetch per run screens for the armed block —
        # trivial next to the per-run analytics this aggregation already does.
        full = repo.get_run(int(run.get("id") or 0)) or {}
        if _contact_block(full) is not None:
            contact_runs.append(
                contact_run_card(repo, full, max_tick=run.get("max_tick") or 0))
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
    return {"families": families, "contact_runs": contact_runs}

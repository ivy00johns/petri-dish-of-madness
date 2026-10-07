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
  routes       — EM-351's cross-run per-lane failure rollup (failures/attempts/
                 rate pooled over the family-standing + contact runs above)
  failures     — the event log's failure rows (EM-343): the TRUE
                 action_rejected / provider_error / parse_failure counts +
                 shares and the failures-per-`llm_call` rate, re-derived from
                 the payload on pre-EM-340 runs (see `failure_taxonomy`). Each
                 run block also carries the failures-over-ticks `curve`
                 (EM-345), the per-`actor_id` `by_agent` cut (EM-346) and the
                 per-LANE `by_route` failure rate (EM-349, against each lane's
                 `llm_call` attempts); each family block carries the pooled
                 rollup (EM-347)

Heavy (full event fetch per run) — callers run it on a worker thread
(same blocking class as /api/fingerprints). Family-level numbers are MEANS
across the family's runs (avg/run), so a family with one run and a family
with three stay comparable. Runs with no events still appear (zeros).
"""

from __future__ import annotations

# EM-344 — the taxonomy itself is a leaf module (`petridish.taxonomy`), shared
# with the emit path in `agents/runtime.py`; the API layer reads it WITHOUT
# depending on the agent runtime.
from ..taxonomy import FAILURE_KIND_ORDER, true_failure_kind

# Population sparklines are downsampled to this many points (first+last kept).
_MAX_SPARK_POINTS = 48

_BUILDINGS_KIND = "building_operational"

# EM-343 — the failure-taxonomy read side. The three EM-340 kinds (the reader
# tolerates the legacy overloaded `parse_failure` via `true_failure_kind`) and
# the turn denominator (one `llm_call` row per attempt — the same unit the
# feed's failure rate is quoted in).
_FAILURE_KINDS = FAILURE_KIND_ORDER
_TURNS_KIND = "llm_call"
# EM-350 — how many lanes carry a per-tick failure curve (the busiest by
# volume); the rest keep the scalar rate so the payload stays bounded.
_LANE_CURVE_LANES = 6


def _shares(counts: dict, total: int) -> dict:
    """Per-kind share of the failure total (0..1; all 0 when there are none)."""
    return {
        k: (round(counts[k] / total, 4) if total else 0.0) for k in _FAILURE_KINDS
    }


def _bucket_plan(top_tick: int, cap: int = _MAX_SPARK_POINTS) -> tuple[int, float]:
    """The shared even-width tick-bucket plan for a run: `(n, width)` over
    integer ticks 0..top_tick (one bucket per tick when the run is short). The
    run-level and per-lane curves share ONE plan so their bars align tick for
    tick."""
    span = max(int(top_tick), 0) + 1
    n = max(1, min(cap, span))
    return n, span / n


def _bucket_index(tick: int, n: int, width: float) -> int:
    return min(n - 1, int(max(int(tick), 0) / width))


def _failure_curve(points: list[tuple[int, str]], n: int, width: float) -> list[dict]:
    """EM-345 — the run's failures over ticks, as even-width tick-bucket SUMS
    per kind. Buckets SUM rather than point-SAMPLE on purpose: an even-spaced
    sample of a 1,700-tick run would drop a single-tick provider-outage spike,
    whereas a bucketed sum keeps it as one tall bar. `points` are (tick,
    true_kind) pairs off the same ascending pass `failure_taxonomy` makes; the
    `(n, width)` plan comes from `_bucket_plan`. All-zero buckets stay in the
    series so the curve reads as a continuous timeline rather than a gap."""
    if not points:
        return []
    buckets = [{k: 0 for k in _FAILURE_KINDS} for _ in range(n)]
    for tick, kind in points:
        buckets[_bucket_index(tick, n, width)][kind] += 1
    return [{"tick": int(b * width), **buckets[b]} for b in range(n)]


def _lane_curve(failure_ticks: list[int], attempt_rows: list[tuple[int, int]],
                n: int, width: float) -> list[dict]:
    """EM-350 — ONE lane's failures and attempts per tick bucket
    (`[{tick, failures, attempts}]`), so a lane that degraded only MID-run is
    distinguishable from one that was bad the whole way — which the single
    run-level rate cannot tell apart. Shares the run's bucket plan, so a lane's
    bar and the run bar sit on the same tick."""
    fails = [0] * n
    atts = [0] * n
    for tick in failure_ticks:
        fails[_bucket_index(tick, n, width)] += 1
    for tick, count in attempt_rows:
        atts[_bucket_index(tick, n, width)] += count
    return [
        {"tick": int(b * width), "failures": fails[b], "attempts": atts[b]}
        for b in range(n)
    ]


def failure_taxonomy(repo, run_id: int) -> dict:
    """EM-343/EM-345/EM-346/EM-349/EM-350 — ONE run's failure taxonomy, read off
    its persisted event log.

    The TRUE shares, not the raw kind counts: every failure row is routed
    through `true_failure_kind`, which re-derives the taxonomy from the payload
    on pre-EM-340 runs (whose rows all wear the single overloaded
    `parse_failure` kind) — so the panel reports what the runtime MEANT, and
    the ambiguity EM-340/EM-342 removed does not reappear on historic runs.
    `legacy_rows_reclassified` counts the rows that needed re-derivation, so a
    reader can see how much of the number came from history.

    `shares` are of the failure total (the taxonomy mix); `failure_rate` is
    failures per `llm_call` (the turn-ish denominator, absent ⇒ 0). Defensive
    throughout: an absent payload degrades to `parse_failure`. Additive
    read-outs riding the same pass:

      • `curve` (EM-345) — the failures over ticks (even-width bucket SUMS), so
        a provider outage reads as a SPIKE, not a number;
      • `by_agent` (EM-346/348) — the same taxonomy keyed by `actor_id` (the
        "which agent fails differently" cut; a per-agent rate separates one
        broken route from a provider-wide outage), each entry carrying `routes`
        (lane each failure row was `routed_via`), `top_route` and
        `routes_attributed`;
      • `by_route` (EM-349/350) — every lane's own failure RATE
        (`{failures, attempts, failure_rate}`) against its `llm_call` attempts,
        ordered worst rate first, plus `failures_attributed` /
        `attempts_attributed` coverage. The top `_LANE_CURVE_LANES` lanes by
        volume also carry a `curve` (`[{tick, failures, attempts}]`) so a lane
        that degraded only mid-run is distinguishable from one that was bad
        throughout. Measured off the live DB, run 23's busiest lane carried the
        MOST failures (218) but only a 15.0% rate — a broadly degraded routing
        period, not one uniquely broken lane — while run 26's lanes were
        uniformly worse (27–29%).
    """
    counts = {k: 0 for k in _FAILURE_KINDS}
    legacy_rows = 0
    curve_points: list[tuple[int, str]] = []
    agent_counts: dict[str, dict] = {}
    agent_legacy: dict[str, int] = {}
    agent_routes: dict[str, dict[str, int]] = {}
    route_failure_ticks: dict[str, list[int]] = {}
    for event in repo.get_events(run_id, kinds=list(_FAILURE_KINDS), order="asc"):
        kind = event.get("kind")
        payload = event.get("payload")
        true_kind = true_failure_kind(kind, payload)
        if true_kind is None:
            continue
        counts[true_kind] += 1
        legacy = true_kind != kind
        if legacy:
            legacy_rows += 1
        tick = event.get("tick")
        tick_i = int(tick) if isinstance(tick, (int, float)) else 0
        curve_points.append((tick_i, true_kind))
        actor = str(event.get("actor_id") or "")
        per = agent_counts.setdefault(actor, {k: 0 for k in _FAILURE_KINDS})
        per[true_kind] += 1
        if legacy:
            agent_legacy[actor] = agent_legacy.get(actor, 0) + 1
        # EM-348/350 — attribute the row to the lane it was routed through. The
        # `routed_via` key is absent on some historic/pre-diagnostic rows, so
        # `routes_attributed` keeps the coverage honest rather than inventing a
        # route for them.
        route = payload.get("routed_via") if isinstance(payload, dict) else None
        if isinstance(route, str) and route.strip():
            lane = route.strip()
            routes = agent_routes.setdefault(actor, {})
            routes[lane] = routes.get(lane, 0) + 1
            route_failure_ticks.setdefault(lane, []).append(tick_i)
    total = sum(counts.values())
    turns = int(repo.count_events_of_kind(run_id, _TURNS_KIND) or 0)

    # Per-agent turns: one grouped COUNT (cheap) rather than a second event pass.
    turns_by_actor = repo.count_events_of_kind_by_actor(run_id, _TURNS_KIND)
    by_agent: dict[str, dict] = {}
    for actor in sorted(set(agent_counts) | set(turns_by_actor)):
        per = agent_counts.get(actor) or {k: 0 for k in _FAILURE_KINDS}
        atotal = sum(per.values())
        aturns = int(turns_by_actor.get(actor) or 0)
        routes = dict(sorted((agent_routes.get(actor) or {}).items(),
                             key=lambda kv: (-kv[1], kv[0])))
        by_agent[actor] = {
            "counts": per,
            "shares": _shares(per, atotal),
            "total": atotal,
            "turns": aturns,
            "failure_rate": (round(atotal / aturns, 4) if aturns else 0.0),
            "legacy_rows_reclassified": int(agent_legacy.get(actor, 0)),
            "routes": routes,
            "top_route": next(iter(routes), ""),
            "routes_attributed": sum(routes.values()),
        }

    # EM-349 — the per-LANE failure rate: attribute each lane's failures to how
    # often the lane was actually USED (`llm_call` attempts, grouped by the
    # serving `gen_ai.response.model`), so a lane that carries many failures
    # simply because it carries most of the traffic is not mistaken for a bad
    # one. Ordered worst-rate first, then by volume, then lane name.
    attempts_by_model = repo.count_llm_attempts_by_model(run_id)
    route_failures: dict[str, int] = {}
    for routes in agent_routes.values():
        for lane, n in routes.items():
            route_failures[lane] = route_failures.get(lane, 0) + n
    by_route: dict[str, dict] = {}
    for lane in set(route_failures) | {ln for ln in attempts_by_model if ln}:
        rf = route_failures.get(lane, 0)
        attempts = int(attempts_by_model.get(lane) or 0)
        by_route[lane] = {
            "failures": rf,
            "attempts": attempts,
            "failure_rate": (round(rf / attempts, 4) if attempts else 0.0),
        }
    by_route = dict(sorted(
        by_route.items(),
        key=lambda kv: (-kv[1]["failure_rate"], -kv[1]["attempts"], kv[0]),
    ))

    # EM-350 — per-lane curves for the busiest lanes (the ones with enough
    # volume to be read), on the SAME bucket plan as the run curve.
    max_tick = repo.run_max_tick(run_id)
    n, width = _bucket_plan(max(max_tick, max((t for t, _ in curve_points), default=0)))
    curve_lanes = set(sorted(by_route, key=lambda ln: (-by_route[ln]["attempts"], ln))
                      [:_LANE_CURVE_LANES])
    attempt_rows: dict[str, list[tuple[int, int]]] = {}
    for tick, lane, count in repo.count_llm_attempts_by_tick_and_model(run_id):
        if lane:
            attempt_rows.setdefault(lane, []).append((tick, count))
    for lane in by_route:
        by_route[lane]["curve"] = (
            _lane_curve(route_failure_ticks.get(lane, []),
                        attempt_rows.get(lane, []), n, width)
            if lane in curve_lanes else []
        )

    return {
        "counts": counts,
        "total": total,
        "shares": _shares(counts, total),
        "turns": turns,
        "failure_rate": (round(total / turns, 4) if turns else 0.0),
        "legacy_rows_reclassified": legacy_rows,
        "curve": _failure_curve(curve_points, n, width),
        "by_agent": by_agent,
        "by_route": by_route,
        # Coverage: how much of the run the lane cut accounts for (failure rows
        # with a lane; `llm_call` attempts that named one). Never invented.
        "failures_attributed": sum(route_failures.values()),
        "attempts_attributed": sum(n for ln, n in attempts_by_model.items() if ln),
    }


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _rollup_failures(runs: list[dict]) -> dict:
    """EM-347 — a family's failure taxonomy, AGGREGATED across its runs'
    already-computed `failures` blocks (no event re-read). Counts/turns/legacy
    sum; `shares` are of the pooled failure total and `failure_rate` is pooled
    failures per `llm_call` — the two comparable to a single run's block, so
    "which family fails differently" reads off shares + rate while the raw
    counts stay honest about how many runs fed them (`runs`)."""
    counts = {k: 0 for k in _FAILURE_KINDS}
    legacy = 0
    turns = 0
    for r in runs:
        f = r.get("failures") or {}
        fc = f.get("counts") or {}
        for k in _FAILURE_KINDS:
            counts[k] += int(fc.get(k) or 0)
        legacy += int(f.get("legacy_rows_reclassified") or 0)
        turns += int(f.get("turns") or 0)
    total = sum(counts.values())
    return {
        "counts": counts,
        "shares": _shares(counts, total),
        "total": total,
        "turns": turns,
        "failure_rate": (round(total / turns, 4) if turns else 0.0),
        "legacy_rows_reclassified": legacy,
        "runs": len(runs),
    }


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
        # EM-343 — the per-run failure taxonomy (the Arena panel's read-off).
        "failures": failure_taxonomy(repo, run_id),
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
    # ONE run_outcomes read feeds both the outcome chips and the EM-343
    # failure taxonomy (it is the heavy full-event pass — never pay it twice).
    oc = run_outcomes(repo, run_id, max_tick if max_tick is not None
                      else (run.get("max_tick") or 0))
    card: dict = {
        "run_id": run_id,
        "max_tick": int(max_tick if max_tick is not None
                        else (run.get("max_tick") or 0)),
        "family_a": str(block.get("family_a", "") or ""),
        "family_b": str(block.get("family_b", "") or ""),
        "name_b": str(block.get("name_b", "") or ""),
        "outcomes": oc["outcomes"],
        "failures": oc["failures"],
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


def _rollup_routes(per_run_routes: dict[int, dict]) -> list[dict]:
    """EM-351 — every lane's failures/attempts POOLED across the Arena's runs
    (the family-standing + contact runs already computed above; no extra event
    read), so a lane that looks bad in one draw can be judged against its whole
    record instead of in isolation. `runs` counts the runs the lane appeared in
    (it had failures or attempts there). Ordered worst pooled rate first."""
    agg: dict[str, dict] = {}
    for by_route in per_run_routes.values():
        for lane, stat in (by_route or {}).items():
            rec = agg.setdefault(
                lane, {"lane": lane, "failures": 0, "attempts": 0, "runs": 0})
            rec["failures"] += int(stat.get("failures") or 0)
            rec["attempts"] += int(stat.get("attempts") or 0)
            rec["runs"] += 1
    out = []
    for rec in agg.values():
        attempts = rec["attempts"]
        out.append({**rec, "failure_rate": (
            round(rec["failures"] / attempts, 4) if attempts else 0.0)})
    out.sort(key=lambda r: (-r["failure_rate"], -r["attempts"], r["lane"]))
    return out


def arena_summary(repo) -> dict:
    """The /api/arena payload: families (with ≥1 stamped run) ordered by their
    EARLIEST stamped run (the chronological cast order), each with its runs'
    outcome cards + sparklines and family means — plus EM-334's contact_runs:
    every run whose config_json carries an ARMED contact block, with the
    family pairing + per-settlement cards (the First Contact comparison) — plus
    EM-351's `routes`: the per-lane failure rate pooled across those runs."""
    blocks: dict[str, list[dict]] = {}
    first_seen: dict[str, int] = {}
    contact_runs: list[dict] = []
    # EM-351 — one entry per INCLUDED run (deduped by run id, so a run that is
    # both contact-armed and family-stamped is counted once).
    per_run_routes: dict[int, dict] = {}
    # EM-334 follow-up — ONE batched read of every run's config_json screens
    # for the armed contact block (list_runs deliberately omits the blob; the
    # old path paid one get_run() fetch per run just to screen it). The card
    # reads only id/max_tick/config_json and max_tick still comes from the
    # list_runs row, so the cards are byte-identical to the per-run fetch.
    configs = repo.get_run_configs()
    for run in repo.list_runs():
        rid = int(run.get("id") or 0)
        full = dict(run, config_json=configs.get(rid, ""))
        if _contact_block(full) is not None:
            card = contact_run_card(repo, full, max_tick=run.get("max_tick") or 0)
            contact_runs.append(card)
            per_run_routes[rid] = (card.get("failures") or {}).get("by_route") or {}
        fam = run.get("model_family")
        if not fam:
            continue
        if fam not in blocks:
            blocks[fam] = []
            first_seen[fam] = run["id"]
        oc = run_outcomes(repo, run["id"], run.get("max_tick") or 0)
        blocks[fam].append(oc)
        per_run_routes.setdefault(
            rid, (oc.get("failures") or {}).get("by_route") or {})

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
            # EM-347 — the family's pooled failure taxonomy (shares + rate), the
            # "which family fails differently" rollup across its runs.
            "failures": _rollup_failures(runs),
        })
    return {
        "families": families,
        "contact_runs": contact_runs,
        # EM-351 — the cross-run per-lane failure rollup (worst pooled rate first).
        "routes": _rollup_routes(per_run_routes),
    }

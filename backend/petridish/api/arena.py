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
  failures     — the event log's failure rows (EM-343): the TRUE
                 action_rejected / provider_error / parse_failure counts +
                 shares and the failures-per-`llm_call` rate, re-derived from
                 the payload on pre-EM-340 runs (see `failure_taxonomy`). Each
                 run block also carries the failures-over-ticks `curve`
                 (EM-345) and the per-`actor_id` `by_agent` cut (EM-346); each
                 family block carries the pooled rollup (EM-347)

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


def _shares(counts: dict, total: int) -> dict:
    """Per-kind share of the failure total (0..1; all 0 when there are none)."""
    return {
        k: (round(counts[k] / total, 4) if total else 0.0) for k in _FAILURE_KINDS
    }


def _failure_curve(points: list[tuple[int, str]], max_tick: int,
                   cap: int = _MAX_SPARK_POINTS) -> list[dict]:
    """EM-345 — the run's failures over ticks, as ≤`cap` even-width tick-bucket
    SUMS per kind. Buckets SUM rather than point-SAMPLE on purpose: an even-
    spaced sample of a 1,700-tick run would drop a single-tick provider-outage
    spike, whereas a bucketed sum keeps it as one tall bar. `points` are
    (tick, true_kind) pairs off the same ascending pass `failure_taxonomy` makes;
    `max_tick` anchors the axis (so the spike's bucket sits where it happened).
    All-zero buckets stay in the series so the curve reads as a continuous
    timeline rather than a gap."""
    if not points:
        return []
    top = max(int(max_tick), max(t for t, _ in points), 0)
    span = top + 1                        # integer ticks 0..top inclusive
    n = max(1, min(cap, span))            # one bucket per tick on a short run
    width = span / n
    buckets = [{k: 0 for k in _FAILURE_KINDS} for _ in range(n)]
    for tick, kind in points:
        idx = min(n - 1, int(max(tick, 0) / width))
        buckets[idx][kind] += 1
    return [{"tick": int(b * width), **buckets[b]} for b in range(n)]


def failure_taxonomy(repo, run_id: int) -> dict:
    """EM-343/EM-345/EM-346 — ONE run's failure taxonomy, read off its persisted
    event log.

    The TRUE shares, not the raw kind counts: every failure row is routed
    through `true_failure_kind`, which re-derives the taxonomy from the payload
    on pre-EM-340 runs (whose rows all wear the single overloaded
    `parse_failure` kind) — so the panel reports what the runtime MEANT, and
    the ambiguity EM-340/EM-342 removed does not reappear on historic runs.
    `legacy_rows_reclassified` counts the rows that needed re-derivation, so a
    reader can see how much of the number came from history.

    `shares` are of the failure total (the taxonomy mix); `failure_rate` is
    failures per `llm_call` (the turn-ish denominator, absent ⇒ 0). Defensive
    throughout: an absent payload degrades to `parse_failure`.

    Two additive read-outs ride the same pass (EM-345/EM-346):
      • `curve` — the failures over ticks (even-width bucket SUMS, see
        `_failure_curve`), so a provider outage reads as a SPIKE, not a number;
      • `by_agent` — the same taxonomy keyed by `actor_id`, the "WHICH agent
        fails differently" cut. A per-agent rate separates ONE broken route
        (run 23: ada 30% vs vesper 5.7%) from a provider outage that hits the
        whole cast evenly (run 26: 16-18% each). It includes every actor with
        turns or failures, so a clean agent shows as 0 rather than vanishing.
    """
    counts = {k: 0 for k in _FAILURE_KINDS}
    legacy_rows = 0
    curve_points: list[tuple[int, str]] = []
    agent_counts: dict[str, dict] = {}
    agent_legacy: dict[str, int] = {}
    for event in repo.get_events(run_id, kinds=list(_FAILURE_KINDS), order="asc"):
        kind = event.get("kind")
        true_kind = true_failure_kind(kind, event.get("payload"))
        if true_kind is None:
            continue
        counts[true_kind] += 1
        legacy = true_kind != kind
        if legacy:
            legacy_rows += 1
        tick = event.get("tick")
        curve_points.append(
            (int(tick) if isinstance(tick, (int, float)) else 0, true_kind))
        actor = str(event.get("actor_id") or "")
        per = agent_counts.setdefault(actor, {k: 0 for k in _FAILURE_KINDS})
        per[true_kind] += 1
        if legacy:
            agent_legacy[actor] = agent_legacy.get(actor, 0) + 1
    total = sum(counts.values())
    turns = int(repo.count_events_of_kind(run_id, _TURNS_KIND) or 0)

    # Per-agent turns: one grouped COUNT (cheap) rather than a second event pass.
    turns_by_actor = repo.count_events_of_kind_by_actor(run_id, _TURNS_KIND)
    by_agent: dict[str, dict] = {}
    for actor in sorted(set(agent_counts) | set(turns_by_actor)):
        per = agent_counts.get(actor) or {k: 0 for k in _FAILURE_KINDS}
        atotal = sum(per.values())
        aturns = int(turns_by_actor.get(actor) or 0)
        by_agent[actor] = {
            "counts": per,
            "shares": _shares(per, atotal),
            "total": atotal,
            "turns": aturns,
            "failure_rate": (round(atotal / aturns, 4) if aturns else 0.0),
            "legacy_rows_reclassified": int(agent_legacy.get(actor, 0)),
        }

    return {
        "counts": counts,
        "total": total,
        "shares": _shares(counts, total),
        "turns": turns,
        "failure_rate": (round(total / turns, 4) if turns else 0.0),
        "legacy_rows_reclassified": legacy_rows,
        "curve": _failure_curve(curve_points, repo.run_max_tick(run_id)),
        "by_agent": by_agent,
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


def arena_summary(repo) -> dict:
    """The /api/arena payload: families (with ≥1 stamped run) ordered by their
    EARLIEST stamped run (the chronological cast order), each with its runs'
    outcome cards + sparklines and family means — plus EM-334's contact_runs:
    every run whose config_json carries an ARMED contact block, with the
    family pairing + per-settlement cards (the First Contact comparison)."""
    blocks: dict[str, list[dict]] = {}
    first_seen: dict[str, int] = {}
    contact_runs: list[dict] = []
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
            # EM-347 — the family's pooled failure taxonomy (shares + rate), the
            # "which family fails differently" rollup across its runs.
            "failures": _rollup_failures(runs),
        })
    return {"families": families, "contact_runs": contact_runs}

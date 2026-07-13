"""EM-314 — The Babel Matrix: dyadic inter-model social physics.

A ZERO-LLM, N×N (actor-model × target-model) heatmap mined from the dyadic
outcomes already sitting in run.sqlite. For every completed interaction with a
KNOWN model on both ends it asks: when an agent running model R acts on an agent
running model C, how often does it go well? Trades that settle vs. get declined;
lessons that land vs. fail. Zero LLM calls, fully retroactive over existing runs.

DISTINCT FROM EM-119 (cross-run family charts): this is WITHIN-run dyads — the
social chemistry between two weight-sets sharing one city — not per-family
outcomes pooled across runs. (Optional lineage pooling folds a fork/resume chain
of a SINGLE lineage, still one within-run society, not a cross-run aggregate.)

Every cell carries its receipts (the exact events, newest-first, capped) so a
finding is quotable, replayable evidence — never a chart alone. Thin dyad
samples get honest confidence: raw n plus a Wilson 95% score interval, so the
viewer can shade uncertain cells instead of over-reading a 1-of-2 streak.

Pure projection of an EventRow list — no sim mutation, no model call, strictly
OFF the replay surface.
"""
from __future__ import annotations

import math
from typing import Iterable

from .features import receipt_routed_via, resolve_agent_models

# Bump on ANY change to the extraction semantics or output shape so a cached /
# persisted matrix can be invalidated and a reader can branch on the version.
BABEL_MATRIX_VERSION = "1.0.0"

# The dyadic outcome vocabulary. Each spec classifies ONE resolution event kind
# into (family, positive?). The dyad is read uniformly from the row's natural
# direction: ROW = actor_id's model (the agent taking the resolving action),
# COL = target_id's model (the counterparty it acted upon). So a cell reads
# "when a <row> agent acts on a <col> agent, positive-outcome rate". Only
# resolution events with BOTH an actor and a target are used (no temporal
# pairing needed) — the smallest coherent slice. Adding families (commitment
# honoring, insult reciprocation, questions answered) is a matter of extending
# this table plus any pairing pass they need; the aggregation below is generic.
OUTCOME_SPECS: dict[str, dict] = {
    # Negotiated trade (EM-230): the counterparty either settles or declines.
    "trade_settled": {"family": "trade", "positive": True},
    "trade_declined": {"family": "trade", "positive": False},
    # Skill teaching (EM-228): a lesson lands, or the teach fails.
    "skill_taught": {"family": "teach", "positive": True},
    "teach_failed": {"family": "teach", "positive": False},
}

# Per-cell receipt cap — bounds the response size on long runs while keeping
# enough evidence to scroll. Newest-first, so the cap drops the OLDEST receipts.
DEFAULT_RECEIPT_CAP = 40

# Wilson score interval z for a 95% confidence level.
_WILSON_Z = 1.959963984540054


def _wilson_interval(positive: int, total: int) -> tuple[float | None, float | None]:
    """Wilson 95% score interval for a binomial proportion positive/total.

    Preferred over the normal approximation for the small n this instrument is
    full of (a 3-agent cast makes thin dyads). Returns (lo, hi) in [0, 1], or
    (None, None) when total == 0 (undefined — no evidence)."""
    if total <= 0:
        return None, None
    z = _WILSON_Z
    n = float(total)
    phat = positive / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4 * n * n))) / denom
    lo = max(0.0, center - half)
    hi = min(1.0, center + half)
    return round(lo, 4), round(hi, 4)


def build_babel_matrix(
    events: Iterable[dict],
    *,
    family: str | None = None,
    receipt_cap: int = DEFAULT_RECEIPT_CAP,
) -> dict:
    """Project an EventRow list into the Babel Matrix summary (JSON-ready).

    ``events`` is the run's rows (as ``SQLiteRepository.get_events`` returns
    them). ``family`` optionally restricts to one outcome family ("trade" /
    "teach"); None aggregates all. ``receipt_cap`` bounds receipts per cell.

    Shape::

        {
          "version": "1.0.0",
          "family": null | "trade",
          "families": ["teach", "trade"],   # families actually present
          "models": ["gemini-flash", ...],  # axis labels (sorted), used ends only
          "cells": [ {actor, target, total, positive, rate,
                      ci_lo, ci_hi, by_family, receipts:[...] }, ... ],
          "totals": {"outcomes", "positive", "cells", "receipts_capped"}
        }

    Deterministic: axis + cell + receipt ordering are all stable sorts, so the
    same event set always yields byte-identical output.
    """
    events = list(events)
    agent_model = resolve_agent_models(events)

    # cell key -> accumulator. Keep receipts as a growing list (we cap at the end
    # after sorting newest-first, so the cap keeps the FRESHEST evidence).
    cells: dict[tuple[str, str], dict] = {}
    used_models: set[str] = set()
    families_present: set[str] = set()
    total_outcomes = 0
    total_positive = 0
    receipts_capped = False

    for ev in events:
        spec = OUTCOME_SPECS.get(ev.get("kind"))
        if spec is None:
            continue
        fam = spec["family"]
        if family is not None and fam != family:
            continue
        actor = ev.get("actor_id")
        target = ev.get("target_id")
        if not actor or not target or actor == target:
            continue
        row_model = agent_model.get(actor)
        col_model = agent_model.get(target)
        # "known models on both ends" — drop any outcome we can't attribute.
        if row_model is None or col_model is None:
            continue

        positive = bool(spec["positive"])
        key = (row_model, col_model)
        cell = cells.get(key)
        if cell is None:
            cell = {
                "actor": row_model,
                "target": col_model,
                "total": 0,
                "positive": 0,
                "by_family": {},
                "_receipts": [],
            }
            cells[key] = cell
        cell["total"] += 1
        if positive:
            cell["positive"] += 1
        fam_acc = cell["by_family"].setdefault(fam, {"total": 0, "positive": 0})
        fam_acc["total"] += 1
        if positive:
            fam_acc["positive"] += 1

        cell["_receipts"].append({
            "seq": ev.get("seq"),
            "tick": ev.get("tick"),
            "kind": ev.get("kind"),
            "family": fam,
            "positive": positive,
            "actor_id": actor,
            "target_id": target,
            "text": ev.get("text") or "",
            # Ground-truth model that actually answered the actor's turn, when the
            # row carries it — surfaces lane bounces the stable axis hides.
            "routed_via": receipt_routed_via(ev.get("payload")),
        })

        used_models.add(row_model)
        used_models.add(col_model)
        families_present.add(fam)
        total_outcomes += 1
        if positive:
            total_positive += 1

    # Finalize cells: rates, Wilson CI, receipt sort + cap. Stable ordering.
    out_cells: list[dict] = []
    for key in sorted(cells.keys()):
        cell = cells[key]
        total = cell["total"]
        positive = cell["positive"]
        ci_lo, ci_hi = _wilson_interval(positive, total)
        receipts = cell.pop("_receipts")
        # Newest-first by seq (fall back to 0 for defensively-missing seqs).
        receipts.sort(key=lambda r: (r.get("seq") or 0), reverse=True)
        if len(receipts) > receipt_cap:
            receipts = receipts[:receipt_cap]
            receipts_capped = True
        out_cells.append({
            "actor": cell["actor"],
            "target": cell["target"],
            "total": total,
            "positive": positive,
            "rate": round(positive / total, 4) if total else None,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "by_family": {
                f: {
                    "total": v["total"],
                    "positive": v["positive"],
                    "rate": round(v["positive"] / v["total"], 4) if v["total"] else None,
                }
                for f, v in sorted(cell["by_family"].items())
            },
            "receipts": receipts,
        })

    return {
        "version": BABEL_MATRIX_VERSION,
        "family": family,
        "families": sorted(families_present),
        "models": sorted(used_models),
        "cells": out_cells,
        "totals": {
            "outcomes": total_outcomes,
            "positive": total_positive,
            "cells": len(out_cells),
            "receipts_capped": receipts_capped,
        },
    }

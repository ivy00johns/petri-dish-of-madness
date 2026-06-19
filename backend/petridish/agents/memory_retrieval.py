"""
EM-222 — relevance-scored long-term memory retrieval (the PURE half).

This module is deliberately GL/IO-free: no router, no DB, no world mutation —
just deterministic functions over plain dicts/vectors. The async orchestration
(embed the query, fetch candidates, ensure embeddings, score, merge) lives in
`AgentRuntime._retrieve_memory`; everything HERE is pure so the scoring is
trivially testable and replay-safe (same inputs ⇒ same order, byte-for-byte).

Smallville-style retrieval (design: docs/.../2026-06-19-em222-memory-retrieval):
a candidate's score blends three signals, EACH normalized to [0, 1] across the
candidate set so no signal's raw scale dominates —

    score = w.relevance  * norm(cosine(query, candidate))
          + w.importance * norm(importance(candidate))
          + w.recency    * decay(now - candidate.tick)

with recency = 0.5 ** ((now - tick) / halflife) (a clean exponential half-life)
and ties broken by `seq` DESC (newest first) so the order is fully stable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable


# ──────────────────────────────────────────────────────────────────────────────
# Globally-salient event kinds — the "town news" an agent recalls even when it
# was neither actor nor target (mirrors the witness rule in push_event + the
# reflection importance weights). The candidate corpus (Lane A's
# fetch_memory_candidates) is `actor_id==agent OR target_id==agent OR kind IN
# BROADCAST_KINDS`, so these kinds ride into every agent's autobiographical
# memory as shared history.
# ──────────────────────────────────────────────────────────────────────────────

BROADCAST_KINDS: tuple[str, ...] = (
    "rule_proposed",
    "rule_passed",
    "rule_rejected",
    "random_event",
    "world_extinct",
    "god_miracle",
    "name_town",
)


def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors, in [-1, 1].

    Returns 0.0 when either vector is empty, mismatched in length, or has zero
    norm (a degenerate vector has no direction, so it is "similar" to nothing) —
    never raises, never divides by zero."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def build_query_text(agent: Any, world: Any, recent_events: list[dict]) -> str:
    """'What's on the agent's mind' as a short query string for the embedder.

    Composed from the agent's current SITUATION (location + the most pressing
    need) plus the texts of its last ~3 perceived events — the same signals the
    prompt foregrounds, so the retrieved memories answer "what is relevant to
    me, right now". Pure: reads only attributes, never mutates anything."""
    parts: list[str] = []

    name = getattr(agent, "name", None)
    if name:
        parts.append(str(name))

    location = getattr(agent, "location", None)
    if location:
        place = world.places.get(location) if hasattr(world, "places") else None
        place_name = getattr(place, "name", None) if place is not None else None
        parts.append(f"at {place_name or location}")

    # Top need: low energy dominates an agent's attention (the survival-pressure
    # NEEDS block in the prompt). Above the line it is simply "content".
    energy = getattr(agent, "energy", None)
    if isinstance(energy, (int, float)):
        if energy <= 0:
            parts.append("dying, desperate for energy")
        elif energy < 25:
            parts.append("starving, needs energy")
        else:
            parts.append("content")

    mood = getattr(agent, "mood", None)
    if mood:
        parts.append(f"feeling {mood}")

    # Last ~3 perceived event texts — the immediate context the query rides on.
    for evt in recent_events[-3:]:
        text = (evt.get("text") or "").strip()
        if text:
            parts.append(text)

    return " | ".join(parts)


@dataclass
class RetrievalWeights:
    """Blend weights for the three retrieval signals + the recency half-life.

    relevance/importance/recency weight each NORMALIZED component (they need not
    sum to 1 — the normalization already puts every component on [0, 1]).
    recency_halflife_ticks is the age (in ticks) at which recency decays to 0.5.
    """
    relevance: float
    importance: float
    recency: float
    recency_halflife_ticks: int


def _normalize(values: list[float]) -> list[float]:
    """Min-max normalize a list to [0, 1]. A flat list (max == min, incl. a
    single element or an all-zero set) maps every entry to 0.0 so a signal with
    no spread across the candidate set contributes nothing — it cannot tilt the
    ranking, leaving the other signals to decide. Pure + deterministic."""
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    span = hi - lo
    if span <= 0.0:
        return [0.0] * len(values)
    return [(v - lo) / span for v in values]


def score_candidates(
    query_vec: list[float],
    candidates: list[dict],
    embeddings: dict[int, list[float]],
    now_tick: int,
    weights: RetrievalWeights,
    importance_of: Callable[[dict], float],
) -> list[dict]:
    """Rank candidates by relevance × importance × recency (DESC).

    Each candidate is `{seq, tick, kind, text}`; `embeddings` maps seq → vector
    and MUST cover every candidate (a missing seq scores cosine 0 defensively).
    The three raw signals are computed per candidate, then EACH normalized to
    [0, 1] across the whole set before the weighted blend, so no signal's native
    scale dominates. recency = 0.5 ** ((now - tick) / halflife) (clamped so a
    future/zero-age event reads as 1.0, and a non-positive half-life degrades to
    a flat 1.0 rather than dividing by zero).

    Stable tie-break: equal blended scores order by `seq` DESC (newest first).
    Pure + deterministic — returns a NEW sorted list, never mutates the inputs.
    """
    if not candidates:
        return []

    halflife = weights.recency_halflife_ticks
    cosines: list[float] = []
    importances: list[float] = []
    recencies: list[float] = []

    for c in candidates:
        seq = c.get("seq")
        vec = embeddings.get(seq) if seq is not None else None
        cosines.append(cosine(query_vec, vec) if vec else 0.0)

        try:
            importances.append(float(importance_of(c)))
        except (TypeError, ValueError):
            importances.append(0.0)

        age = now_tick - int(c.get("tick", now_tick) or 0)
        if halflife and halflife > 0 and age > 0:
            recencies.append(0.5 ** (age / halflife))
        else:
            recencies.append(1.0)  # same/future tick, or half-life disabled

    norm_cos = _normalize(cosines)
    norm_imp = _normalize(importances)
    norm_rec = _normalize(recencies)

    scored: list[tuple[float, int, dict]] = []
    for i, c in enumerate(candidates):
        score = (
            weights.relevance * norm_cos[i]
            + weights.importance * norm_imp[i]
            + weights.recency * norm_rec[i]
        )
        seq = c.get("seq")
        seq_key = int(seq) if isinstance(seq, int) else -1
        scored.append((score, seq_key, c))

    # Sort by score DESC, then seq DESC — both via negation so the sort is stable
    # and the tie-break is the documented "newest seq first".
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return [c for _score, _seq, c in scored]

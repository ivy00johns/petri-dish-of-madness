"""Shared feature-extraction helpers for the fingerprint instruments (EM-314).

Deterministic, side-effect-free projections of the append-only event log. These
are the primitives every model-lab instrument reuses, so the layer is built
once (intake note for #16/#21/#5). Pure functions of an EventRow list — the
shape ``SQLiteRepository.get_events`` returns.
"""
from __future__ import annotations

from typing import Any, Iterable

# The event kinds whose ``profile`` field is a reliable per-turn model
# attribution for the ACTOR. Every LLM-driven agent turn stamps ``profile`` (the
# deciding model slot) at the row top level; system/animal rows carry no useful
# profile, so we simply never learn a model from them (they resolve to None and
# are dropped by the dyadic instruments). We do NOT special-case kinds here —
# any row with an actor_id + a non-empty profile contributes a vote.


def resolve_agent_models(events: Iterable[dict]) -> dict[str, str]:
    """agent_id → its per-agent MODEL identity, for the Babel Matrix axes.

    In this lab a "profile" is a named model slot (gemini-flash, groq-llama,
    local-ollama …): the marquee per-agent model control pins one model per
    agent, so ``profile`` IS the agent's model identity and matches the existing
    ``by_model`` analytics convention (repository.get_analytics groups on it).

    Ground truth over noise: an agent can bounce lanes mid-run (the no-throttle
    law routes a sick pinned lane elsewhere), so a single row's profile is not
    authoritative. We take the DOMINANT profile — the one that stamped the most
    of that agent's rows — as the stable identity. Ties break to the
    lexicographically smallest profile so the mapping is fully deterministic
    (order-independent), a hard requirement for a replay-off-surface projection.

    Rows without an actor_id or without a non-empty profile contribute nothing;
    an agent that never carried a profile is simply absent from the result (the
    dyadic layer drops any outcome touching an unresolvable agent — "known
    models on both ends", per the pitch). The actual routed_via model that
    answered each turn is surfaced per-receipt downstream, not folded into the
    axis, so the axis labels stay stable and readable.
    """
    # agent_id -> {profile: count}
    tallies: dict[str, dict[str, int]] = {}
    for ev in events:
        actor = ev.get("actor_id")
        profile = ev.get("profile")
        if not actor or not isinstance(profile, str) or not profile:
            continue
        bucket = tallies.setdefault(actor, {})
        bucket[profile] = bucket.get(profile, 0) + 1

    resolved: dict[str, str] = {}
    for actor, bucket in tallies.items():
        # max count, ties → lexicographically smallest profile (determinism).
        best = min(bucket.items(), key=lambda kv: (-kv[1], kv[0]))
        resolved[actor] = best[0]
    return resolved


def receipt_routed_via(payload: Any) -> str | None:
    """The ground-truth model that actually answered a turn, when the row's
    payload carries it (``payload.routed_via``, stamped by the loop's per-call
    attribution channel). Best-effort: absent / malformed payloads → None. Used
    only as a per-receipt annotation, never as an axis label."""
    if not isinstance(payload, dict):
        return None
    rv = payload.get("routed_via")
    return rv if isinstance(rv, str) and rv else None

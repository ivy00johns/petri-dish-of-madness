"""
EM-340 / EM-342 / EM-343 — the failure-kind taxonomy.

The ONE shared home for "what did a failed turn actually fail at": the emit
side (`_failure_kind_for`, used by the agent runtime when it idles a turn) and
the read side (`true_failure_kind`, used by the Arena's failure-taxonomy panel)
both route through this module, so a reported taxonomy share can never diverge
from what the runtime MEANT.

Moved out of `agents/runtime.py` (EM-344): the taxonomy is pure policy over a
kind + payload, so the read/API layer (``api/arena.py``) can depend on it
WITHOUT depending on the agent runtime — the layering wart the extraction
removes. This module imports nothing from petridish, so it is a safe leaf for
either side.

The EM-340 split — `parse_failure` used to carry THREE unrelated phenomena, so
any per-run "parse failure rate" mixed them (run 23: 322 events, ZERO malformed
JSON):
  • `action_rejected` — the model answered with a well-formed, schema-valid
    action the WORLD refused (unknown/absent target, gate rule, funds, tier,
    skill, blackout, …). The model was fine; the world said no.
  • `provider_error`  — the provider never delivered a usable response
    (transport error, all lanes exhausted/rate-limited, or the call blew the
    wall-clock turn budget). The model was never consulted.
  • `parse_failure`   — the model DID answer but produced no parseable action
    (no JSON object, JSON that failed the action schema) or the engine hit its
    defensive fallback. This is the only kind genuinely about parsing.

EM-342 — the split is EXHAUSTIVE for world-side refusals: the pre-dispatch
`_validate_world` refusal (reason `world error:`) is a WORLD rejection too, so
it emits `action_rejected` instead of `parse_failure`. The KIND is the
discriminator — payloads are unchanged (an `action_rejected` still carries
`{action, error, rejected?}` or `{reason, rejected_action?}`, a `provider_error`
still carries `reason`). Events are append-only and never re-parsed through this
layer, so pre-EM-340 rows keep their overloaded `parse_failure` kind;
`is_failure_kind` is what lets the internal "did this turn fail?" checks read
every era alike.

EM-343 — `true_failure_kind` is the read-side classifier that recovers the true
kind from one persisted row (or None for a non-failure event), re-deriving it
from the payload on pre-EM-340 rows.
"""
from __future__ import annotations

from typing import Any

# The three EM-340 kinds. `FAILURE_KIND_ORDER` is the canonical display/number
# order (the Arena's counts/shares dicts and the panel's chips follow it).
FAILURE_KIND_ORDER = ("action_rejected", "provider_error", "parse_failure")
FAILURE_KINDS = frozenset(FAILURE_KIND_ORDER)

# Transport-level reasons that mean "the provider never served us a response" —
# the idle-fallback reason prefixes that earn `provider_error`. Anything else
# (no-JSON, schema error, …) stays `parse_failure`. Deliberately a whitelist: an
# unrecognized reason keeps the conservative parse_failure meaning (byte-stable
# for any reason string added later that isn't clearly provider-side).
PROVIDER_ERROR_PREFIXES = (
    "provider_error:", "llm_timeout:", "unexpected_error:",
)

# EM-342 — the WORLD-side refusal prefix: `_validate_world` (the pre-dispatch
# gate in `_call_and_parse`) returns `world error: <reason>` when the model's
# action is well-formed and schema-valid but the world's rules refuse it
# (unknown/absent target, gate rule, funds, tier, skill, blackout, …). That is
# a REJECTION, not a parse problem — it emits `action_rejected`, the same kind
# the APPLY-time refusals (per-step gate / dispatch table / `World._fail_event`)
# already carry, so the taxonomy has no residual world-refusal ambiguity.
# `schema error:` deliberately stays `parse_failure`: that is the response's
# SHAPE failing the action schema, i.e. a genuine parse-side failure.
REJECTION_PREFIXES = ("world error:",)

# EM-343 — the engine's OWN defensive fallback (a malformed `action_*` return,
# no model action involved) wears `parse_failure` by design; its payload is
# `{"error": "bad_world_result"}`. The read-side classifier below must NOT
# mistake that payload's `error` for a dispatch refusal.
BAD_WORLD_RESULT = "bad_world_result"


def is_failure_kind(kind: Any) -> bool:
    """True for any EM-340 failure kind — including the legacy overloaded
    `parse_failure` — so an internal "did this turn fail?" check (reflex
    resolution, skill xp, step outcome, coherence marker) reads identically
    before and after the split."""
    return kind in FAILURE_KINDS


def failure_kind_for(reason: str | None) -> str:
    """EM-340/EM-342 — pick the honest kind for an idle-fallback turn from the
    runtime's own failure reason:
      • `provider_error`  — the provider never answered (transport error, stuck
        lane, or the wall-clock turn budget);
      • `action_rejected` — the WORLD refused the action (`world error:` from the
        pre-dispatch validator — the retried path — or an apply-time refusal);
      • `parse_failure`   — the response itself could not be turned into an
        applicable action (no JSON, a `schema error:`, engine fallback)."""
    normalized = (reason or "").strip().lower()
    if normalized.startswith(PROVIDER_ERROR_PREFIXES):
        return "provider_error"
    if normalized.startswith(REJECTION_PREFIXES):
        return "action_rejected"
    return "parse_failure"


def true_failure_kind(kind: Any, payload: Any) -> str | None:
    """EM-343 — the READ-side taxonomy: recover the TRUE failure kind from one
    persisted event row, or None for a non-failure event.

    This is the ONE classifier both the emit path (`failure_kind_for` above)
    and the read surfaces (the Arena failure-taxonomy panel, EM-343) route
    through, so a reported taxonomy share can never diverge from what the
    runtime meant. It exists because events are APPEND-ONLY: rows emitted
    before EM-340 wear the single overloaded `parse_failure` kind, and the true
    taxonomy survives only in the payload — so a raw kind count on a historic
    run would reproduce exactly the ambiguity EM-340/EM-342 removed.

      • a post-split `action_rejected` / `provider_error` row → its own kind;
      • a `parse_failure` row is re-derived from its payload:
          - `rejected: true` (the per-step/apply-time gate's stamp) → rejected;
          - a `reason` → `failure_kind_for(reason)` (so a legacy
            `world error:` reason reads as `action_rejected` per EM-342, a
            provider prefix as `provider_error`, no-JSON/schema as parse);
          - no reason but an `action`/`error` payload → a dispatch refusal that
            never stamped the flag → `action_rejected`;
          - the `bad_world_result` engine fallback → `parse_failure` (there was
            no model action to reject).
    """
    if kind in ("action_rejected", "provider_error"):
        return kind
    if kind != "parse_failure":
        return None
    if not isinstance(payload, dict):
        return "parse_failure"
    if payload.get("rejected") is True:
        return "action_rejected"
    reason = payload.get("reason")
    if isinstance(reason, str) and reason.strip():
        return failure_kind_for(reason)
    if payload.get("error") == BAD_WORLD_RESULT:
        return "parse_failure"
    if payload.get("action") is not None or payload.get("error") is not None:
        return "action_rejected"
    return "parse_failure"

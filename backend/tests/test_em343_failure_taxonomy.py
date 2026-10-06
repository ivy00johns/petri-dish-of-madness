"""EM-343 — the failure-taxonomy read side (the Arena panel's data).

`true_failure_kind` is the ONE read-side classifier: every persisted failure row
is routed through it, so a run's reported shares describe what the runtime
MEANT rather than the raw kind tally. Its job is the append-only problem — rows
emitted before EM-340 wear the single overloaded `parse_failure` kind and carry
the true taxonomy only in their payload — so the Arena can report run 23/26
honestly instead of reproducing exactly the ambiguity EM-340/EM-342 removed.

`failure_taxonomy` is the per-run aggregation off the event log; the arena's
`run_outcomes` / `contact_run_card` carry it so every run card (family standing
or contact) has the panel's numbers.

House idiom: petridish.engine.world is imported BEFORE petridish.agents.runtime
(the circular-import guard).
"""
from __future__ import annotations

import json

from petridish.engine.world import World  # noqa: F401 — must precede agents.runtime
from petridish.agents.runtime import (  # noqa: E402
    _failure_kind_for,
    true_failure_kind,
)
from petridish.api.arena import (  # noqa: E402
    arena_summary,
    failure_taxonomy,
    run_outcomes,
)
from petridish.persistence.repository import SQLiteRepository  # noqa: E402


# ── (A) the read-side classifier ─────────────────────────────────────────────

def test_post_split_kinds_map_to_themselves():
    assert true_failure_kind("action_rejected", {}) == "action_rejected"
    assert true_failure_kind("provider_error", {}) == "provider_error"
    assert true_failure_kind(
        "parse_failure", {"reason": "no valid JSON object"}
    ) == "parse_failure"


def test_non_failure_events_are_none():
    assert true_failure_kind("agent_speech", {}) is None
    assert true_failure_kind("economy", {"action": "give"}) is None
    assert true_failure_kind("", {}) is None
    assert true_failure_kind(None, None) is None


def test_legacy_overloaded_rows_are_re_derived_from_the_payload():
    # the per-step / apply-time gate's stamp
    assert true_failure_kind(
        "parse_failure", {"rejected": True, "action": "give"}
    ) == "action_rejected"
    # a dispatch refusal that never stamped the flag (payload {action, error})
    assert true_failure_kind(
        "parse_failure", {"action": "move_to", "error": "unknown place"}
    ) == "action_rejected"
    # the EM-342 world-error reason
    assert true_failure_kind(
        "parse_failure", {"reason": "world error: unknown target 'Zorp'"}
    ) == "action_rejected"
    # provider-side reasons
    assert true_failure_kind(
        "parse_failure", {"reason": "provider_error: timed out after 30s"}
    ) == "provider_error"
    assert true_failure_kind(
        "parse_failure", {"reason": "llm_timeout: LLM call exceeded the 30s turn budget"}
    ) == "provider_error"
    # genuine parse-side reasons
    assert true_failure_kind(
        "parse_failure",
        {"reason": "no valid JSON object (finish_reason='length') in response: 'hi'"},
    ) == "parse_failure"
    assert true_failure_kind(
        "parse_failure", {"reason": "schema error: 'action' is a required property"}
    ) == "parse_failure"


def test_engine_fallback_and_bare_payloads_stay_parse_failure():
    # The engine's OWN defensive fallback (no model action to reject) must not be
    # mistaken for a dispatch refusal just because its payload has an `error`.
    assert true_failure_kind(
        "parse_failure", {"error": "bad_world_result"}
    ) == "parse_failure"
    # A payload-less legacy row degrades to the conservative meaning.
    assert true_failure_kind("parse_failure", {}) == "parse_failure"
    assert true_failure_kind("parse_failure", None) == "parse_failure"


def test_read_side_agrees_with_the_emit_side():
    """Both halves route through `_failure_kind_for`, so a reason string can
    never be READ differently than it was EMITTED."""
    for reason in (
        "world error: nope", "provider_error: x", "llm_timeout: y",
        "unexpected_error: z", "no valid JSON", "schema error: q",
        "some future failure mode", "parse_failure",
    ):
        assert true_failure_kind("parse_failure", {"reason": reason}) == _failure_kind_for(reason)


# ── (B) the per-run aggregation off the event log ────────────────────────────

def _seed_legacy_run(repo: SQLiteRepository, *, family: str = "gemini",
                     turns: int = 5) -> int:
    """One run with the run-23 shape: NINE failure rows all wearing the
    overloaded `parse_failure` kind (seven legacy payload shapes + two
    post-split native kinds) and `turns` llm_call rows."""
    rid = repo.start_run(json.dumps({"world": {}}), model_family=family)

    def ev(kind: str, payload: dict, tick: int = 1) -> None:
        repo.save_event(rid, {"kind": kind, "payload": payload, "profile": "x"}, tick)

    ev("parse_failure", {"reason": "no valid JSON object (finish_reason='length') in response: 'hi'"})
    ev("parse_failure", {"reason": "schema error: 'action' is a required property"})
    ev("parse_failure", {"reason": "world error: unknown target 'Zorp'"})
    ev("parse_failure", {"reason": "provider_error: timed out after 30s"})
    ev("parse_failure", {"rejected": True, "action": "give", "error": "give requires target"})
    ev("parse_failure", {"action": "move_to", "error": "unknown place"})
    ev("parse_failure", {"error": "bad_world_result"})
    ev("action_rejected", {"action": "demolish", "error": "building_not_found"})
    ev("provider_error", {"reason": "llm_timeout: LLM call exceeded the 30s turn budget"})
    for _ in range(turns):
        ev("llm_call", {}, tick=2)
    return rid


def test_failure_taxonomy_reports_the_true_shares_not_the_raw_kinds(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "taxonomy.sqlite"))
    rid = _seed_legacy_run(repo, turns=5)

    t = failure_taxonomy(repo, rid)

    # 3 world-refused-ish + 1 dispatch + the legacy rejected:true + the native
    # action_rejected = 4; 2 provider; 3 parse (no-JSON, schema, engine fallback).
    assert t["counts"] == {
        "action_rejected": 4, "provider_error": 2, "parse_failure": 3,
    }
    assert t["total"] == 9
    assert t["turns"] == 5
    assert t["failure_rate"] == 1.8          # 9 failures / 5 llm calls
    assert t["shares"] == {
        "action_rejected": 0.4444, "provider_error": 0.2222, "parse_failure": 0.3333,
    }
    # four rows needed re-derivation (the two native kinds already agreed)
    assert t["legacy_rows_reclassified"] == 4


def test_failure_taxonomy_zero_states(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "empty.sqlite"))
    rid = repo.start_run(json.dumps({"world": {}}), model_family="gemini")

    # a run with no events at all
    t = failure_taxonomy(repo, rid)
    assert t["counts"] == {
        "action_rejected": 0, "provider_error": 0, "parse_failure": 0,
    }
    assert t["total"] == 0 and t["turns"] == 0 and t["failure_rate"] == 0.0
    assert t["shares"] == {
        "action_rejected": 0.0, "provider_error": 0.0, "parse_failure": 0.0,
    }
    assert t["legacy_rows_reclassified"] == 0

    # turns but no failures: the rate is 0, not a division error
    for _ in range(7):
        repo.save_event(rid, {"kind": "llm_call", "payload": {}}, 1)
    t2 = failure_taxonomy(repo, rid)
    assert t2["turns"] == 7 and t2["failure_rate"] == 0.0 and t2["total"] == 0


def test_run_outcomes_carries_the_failures_block(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "outcomes.sqlite"))
    rid = _seed_legacy_run(repo, turns=5)

    card = run_outcomes(repo, rid, 10)
    assert "failures" in card
    assert card["failures"]["counts"]["action_rejected"] == 4
    assert card["failures"]["total"] == 9


# ── (C) the Arena surfaces carry it (family standings + contact cards) ───────

def test_arena_summary_exposes_failures_on_family_and_contact_cards(tmp_path):
    repo = SQLiteRepository(str(tmp_path / "arena.sqlite"))
    # a plain family-stamped run
    family_run = _seed_legacy_run(repo, family="gemini", turns=5)
    # an ARMED contact run (no family stamp — it lands in contact_runs only)
    contact_run = repo.start_run(
        json.dumps({"world": {"contact": {"enabled": True, "family_a": "gemini",
                                          "family_b": "llama"}}}),
        model_family=None,
    )
    repo.save_event(contact_run, {"kind": "provider_error",
                                  "payload": {"reason": "provider_error: 502"}, "profile": "x"}, 1)
    repo.save_event(contact_run, {"kind": "llm_call", "payload": {}}, 1)

    out = arena_summary(repo)

    fam_runs = out["families"][0]["runs"]
    assert [r["run_id"] for r in fam_runs] == [family_run]
    assert fam_runs[0]["failures"]["total"] == 9
    assert fam_runs[0]["failures"]["shares"]["action_rejected"] == 0.4444

    cards = {c["run_id"]: c for c in out["contact_runs"]}
    assert contact_run in cards
    card = cards[contact_run]
    assert card["family_a"] == "gemini" and card["family_b"] == "llama"
    assert card["failures"]["counts"]["provider_error"] == 1
    assert card["failures"]["turns"] == 1
    assert card["failures"]["failure_rate"] == 1.0
    # the outcome chips are untouched by the additive block
    assert "population" in card["outcomes"]

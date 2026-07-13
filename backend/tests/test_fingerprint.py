"""
EM-313 — Fingerprint Ticker (behavioral stylometry, zero-LLM).

The classifier infers which model an agent runs from its event-log behavior
alone (verb-mix / build-vs-talk / JSON-retry / sentence-length), scored against
per-model reference fingerprints, and emits a CONVERGING per-turn guess vs the
X-Routed-Via ground truth. It is FEED/VIEWER chrome: read-only over the event
log, off the replay/determinism surface.

Gates:
  (A) Feature math — the fixed [0,1] vector + versioning contract.
  (B) Convergence over HISTORICAL reference — a 1:1 model→agent target run is
      classified against fingerprints mined from a prior run; confidence races
      up and locks on the correct model.
  (C) Within-run fallback (no history) — leave-one-agent-out classifies each
      agent by its OWN model when ≥2 agents share a model.
  (D) The publishable null — a single agent, single model, no history has no
      honest reference and reports status "gathering" (never a self-lookup).
  (E) Determinism — identical inputs ⇒ byte-identical output.
  (F) Config + endpoint gate — default OFF; the block round-trips.
"""
from __future__ import annotations

import pytest

from petridish.persistence.repository import SQLiteRepository
from petridish.fingerprint import (
    FEATURE_NAMES,
    FEATURE_VERSION,
    classify,
    compute_run_fingerprints,
    features_from_turns,
    turns_from_events,
)
from petridish.fingerprint import classifier as fp
from petridish.config.loader import FingerprintTickerParams, _parse_fingerprint_ticker


# ──────────────────────────────────────────────────────────────────────────────
# Synthetic event helpers — two sharply distinct behavioral signatures:
#   ALPHA "builder": build_step every turn, no speech, never retries.
#   BETA  "talker":  say every turn with a long (25-word) line, always retries.
# ──────────────────────────────────────────────────────────────────────────────

ALPHA = "alpha-builder"
BETA = "beta-talker"
_LONG = " ".join(["word"] * 25)


@pytest.fixture(autouse=True)
def _clear_ref_cache():
    """The reference-corpus memo is module-global; clear it around each test so
    fresh in-memory repos never read a prior test's corpus."""
    fp._REF_CACHE.clear()
    yield
    fp._REF_CACHE.clear()


def _emit_turn(repo, run_id, actor_id, tick, model, *, style):
    turn_id = f"{actor_id}-t{tick}"
    base = {"actor_id": actor_id, "actor_type": "human_agent", "turn_id": turn_id}
    retries = 1 if style == "alpha" else 2
    for attempt in range(1, retries + 1):
        repo.save_event(run_id, {
            **base, "kind": "llm_call",
            "payload": {"gen_ai.response.model": model, "attempt": attempt},
        }, tick)
    if style == "alpha":
        repo.save_event(run_id, {
            **base, "kind": "agent_action",
            "payload": {"action": "build_step", "routed_via": model},
        }, tick)
    else:
        repo.save_event(run_id, {
            **base, "kind": "agent_speech",
            "payload": {"action": "say", "said": _LONG, "routed_via": model},
        }, tick)


def _emit_agent(repo, run_id, actor_id, model, style, n):
    for tick in range(1, n + 1):
        _emit_turn(repo, run_id, actor_id, tick, model, style=style)


# ── (A) feature math + versioning ─────────────────────────────────────────────


def test_feature_contract():
    assert FEATURE_VERSION == 1
    assert len(FEATURE_NAMES) == 10
    # An empty turn-set is the all-zero vector of the right length.
    assert features_from_turns([]) == tuple(0.0 for _ in FEATURE_NAMES)


def test_alpha_vs_beta_feature_vectors():
    repo = SQLiteRepository(":memory:")
    rid = repo.start_run("{}")
    _emit_agent(repo, rid, "A", ALPHA, "alpha", 6)
    _emit_agent(repo, rid, "B", BETA, "beta", 6)
    turns = turns_from_events(repo.get_events(rid, order="asc"), rid)
    va = features_from_turns(turns["A"])
    vb = features_from_turns(turns["B"])
    names = {n: i for i, n in enumerate(FEATURE_NAMES)}
    # Builder: all-build, no talk, no retries, no speech length.
    assert va[names["build_ratio"]] == pytest.approx(1.0)
    assert va[names["talk_ratio"]] == pytest.approx(0.0)
    assert va[names["retry_rate"]] == pytest.approx(0.0)
    assert va[names["sentence_len_mean"]] == pytest.approx(0.0)
    # Talker: all-talk, always retries, real sentence length.
    assert vb[names["talk_ratio"]] == pytest.approx(1.0)
    assert vb[names["build_ratio"]] == pytest.approx(0.0)
    assert vb[names["retry_rate"]] == pytest.approx(1.0)
    assert vb[names["sentence_len_mean"]] > 0.0


def test_classify_empty_centroids_is_null():
    out = classify(features_from_turns([]), {})
    assert out["top"] is None
    assert out["confidence"] == 0.0


# ── (B) convergence against a HISTORICAL reference corpus ─────────────────────


def _seed_history(repo):
    """A prior, ended run carrying BOTH model fingerprints (one agent each)."""
    hid = repo.start_run("{}")
    _emit_agent(repo, hid, "H_alpha", ALPHA, "alpha", 12)
    _emit_agent(repo, hid, "H_beta", BETA, "beta", 12)
    repo.end_run(hid)
    return hid


def test_converges_on_correct_model_from_history():
    repo = SQLiteRepository(":memory:")
    _seed_history(repo)
    # Target run: ONE agent per model (the 1:1 case) — history supplies the
    # reference fingerprints, so within-run leave-one-out is not needed.
    tid = repo.start_run("{}")
    _emit_agent(repo, tid, "T_alpha", ALPHA, "alpha", 10)
    _emit_agent(repo, tid, "T_beta", BETA, "beta", 10)

    result = compute_run_fingerprints(repo, tid, FingerprintTickerParams(enabled=True))
    assert result["enabled"] is True
    assert result["feature_version"] == FEATURE_VERSION
    assert result["reference_source"] == "historical"

    by_id = {a["agent_id"]: a for a in result["agents"]}
    ta, tb = by_id["T_alpha"], by_id["T_beta"]

    # Correct model, high confidence, locked, and matches ground truth.
    assert ta["guess"] == ALPHA
    assert ta["ground_truth"] == ALPHA
    assert ta["correct"] is True
    assert ta["status"] == "locked"
    assert ta["confidence"] >= 0.9
    assert tb["guess"] == BETA
    assert tb["correct"] is True

    # The bar RACES UP: final confidence is not below the first sampled point.
    series = ta["series"]
    assert len(series) >= 2
    assert series[-1]["confidence"] >= series[0]["confidence"]


# ── (C) within-run fallback (no history), leave-one-agent-out ─────────────────


def test_within_run_fallback_needs_shared_model():
    repo = SQLiteRepository(":memory:")
    tid = repo.start_run("{}")
    # TWO agents per model so leave-one-agent-out still leaves a reference.
    _emit_agent(repo, tid, "A1", ALPHA, "alpha", 8)
    _emit_agent(repo, tid, "A2", ALPHA, "alpha", 8)
    _emit_agent(repo, tid, "B1", BETA, "beta", 8)
    _emit_agent(repo, tid, "B2", BETA, "beta", 8)

    result = compute_run_fingerprints(repo, tid, FingerprintTickerParams(enabled=True))
    assert result["reference_source"] == "within_run"
    by_id = {a["agent_id"]: a for a in result["agents"]}
    assert by_id["A1"]["guess"] == ALPHA
    assert by_id["A2"]["guess"] == ALPHA
    assert by_id["B1"]["guess"] == BETA
    assert by_id["B2"]["guess"] == BETA
    assert all(by_id[k]["correct"] for k in by_id)


# ── (D) the publishable null — no honest reference ────────────────────────────


def test_single_agent_no_history_is_gathering():
    repo = SQLiteRepository(":memory:")
    tid = repo.start_run("{}")
    _emit_agent(repo, tid, "solo", ALPHA, "alpha", 10)
    result = compute_run_fingerprints(repo, tid, FingerprintTickerParams(enabled=True))
    solo = result["agents"][0]
    # Its own model is excluded (leave-one-agent-out) and there is no other
    # reference — an HONEST null, never a self-lookup.
    assert solo["status"] == "gathering"
    assert solo["guess"] is None
    assert solo["candidates"] == []


# ── (E) determinism ───────────────────────────────────────────────────────────


def test_deterministic():
    repo = SQLiteRepository(":memory:")
    _seed_history(repo)
    tid = repo.start_run("{}")
    _emit_agent(repo, tid, "T_alpha", ALPHA, "alpha", 9)
    ft = FingerprintTickerParams(enabled=True)
    a = compute_run_fingerprints(repo, tid, ft)
    fp._REF_CACHE.clear()  # prove it doesn't depend on the memo being warm
    b = compute_run_fingerprints(repo, tid, ft)
    assert a == b


# ── (F) config gate ───────────────────────────────────────────────────────────


def test_config_defaults_off_and_roundtrips():
    assert FingerprintTickerParams().enabled is False
    # Absent block ⇒ defaults (OFF).
    assert _parse_fingerprint_ticker(None).enabled is False
    parsed = _parse_fingerprint_ticker({
        "enabled": True, "reference_runs": 5, "temperature": 0.2,
        "lock_threshold": 0.8, "min_turns": 2, "max_series_points": 40,
    })
    assert parsed.enabled is True
    assert parsed.reference_runs == 5
    assert parsed.temperature == pytest.approx(0.2)
    assert parsed.lock_threshold == pytest.approx(0.8)
    assert parsed.min_turns == 2
    assert parsed.max_series_points == 40


def test_endpoint_gate_default_off():
    """End-to-end: the shipped config leaves the ticker OFF, so the endpoint
    returns {enabled: false} through the whole app stack."""
    import sys
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]
    with TestClient(app) as c:
        if appmod._world is not None:
            appmod._world.params.animals.enabled = False
            appmod._world.animals.clear()
        r = c.get("/api/fingerprints")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["feature_version"] == FEATURE_VERSION

        # Flip the flag on the live world → the endpoint now computes (the fresh
        # run has ~no turns yet, so agents may be empty, but the gate opens).
        if appmod._world is not None:
            appmod._world.params.fingerprint_ticker = FingerprintTickerParams(enabled=True)
            on = c.get("/api/fingerprints").json()
            assert on["enabled"] is True
            assert "agents" in on

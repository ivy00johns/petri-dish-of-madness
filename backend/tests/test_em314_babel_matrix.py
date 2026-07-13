"""EM-314 — The Babel Matrix: dyadic inter-model social physics.

Covers the ZERO-LLM feature-extraction layer (pure projection of an EventRow
list) plus the flag-gated read endpoint. The instrument is FEED/VIEWER chrome,
strictly OFF the replay surface — these tests assert it is a deterministic,
side-effect-free function of the event log and that it is dark by default.
"""
from __future__ import annotations

import copy
import random

import pytest

from petridish.fingerprint import (
    BABEL_MATRIX_VERSION,
    build_babel_matrix,
    resolve_agent_models,
)


# ──────────────────────────────────────────────────────────────────────────────
# Event fixtures — the shape SQLiteRepository.get_events returns.
# ──────────────────────────────────────────────────────────────────────────────

def _ev(seq, kind, actor, target=None, profile=None, positive_text="", payload=None, tick=None):
    return {
        "seq": seq,
        "run_id": 1,
        "tick": tick if tick is not None else seq,
        "sim_time": None,
        "kind": kind,
        "actor_id": actor,
        "actor_type": "human_agent",
        "target_id": target,
        "profile": profile,
        "turn_id": None,
        "text": positive_text,
        "payload": payload or {},
        "ts": "2026-07-13T00:00:00+00:00",
    }


def _mixed_run():
    """Three agents on three distinct model profiles, with turns that establish
    each agent's model, then a spread of trade + teach outcomes."""
    A, B, C = "a", "b", "c"
    events = [
        # Model-establishing turns (profile stamped on ordinary actions).
        _ev(1, "agent_speech", A, profile="gemini-flash"),
        _ev(2, "agent_speech", B, profile="groq-llama"),
        _ev(3, "agent_speech", C, profile="cerebras-qwen"),
        # Trades: actor is the responder (accepter/decliner); target is offerer.
        # A acts on B (settles), A acts on B (declines) → A→B: 1/2 positive.
        _ev(10, "trade_settled", A, target=B, payload={"routed_via": "gemini-2.0-flash"}),
        _ev(11, "trade_declined", A, target=B),
        # C acts on B: settle, settle → C→B: 2/2 positive.
        _ev(12, "trade_settled", C, target=B),
        _ev(13, "trade_settled", C, target=B),
        # Teach: actor is the teacher; target is the student.
        # B teaches A: taught, failed → B→A: 1/2 positive.
        _ev(20, "skill_taught", B, target=A),
        _ev(21, "teach_failed", B, target=A),
    ]
    return events


# ──────────────────────────────────────────────────────────────────────────────
# resolve_agent_models
# ──────────────────────────────────────────────────────────────────────────────

def test_resolve_dominant_profile():
    events = [
        _ev(1, "agent_speech", "a", profile="gemini-flash"),
        _ev(2, "agent_speech", "a", profile="gemini-flash"),
        _ev(3, "agent_speech", "a", profile="groq-llama"),  # a bounced once
        _ev(4, "agent_speech", "b", profile="groq-llama"),
    ]
    assert resolve_agent_models(events) == {"a": "gemini-flash", "b": "groq-llama"}


def test_resolve_tie_breaks_lexicographically():
    events = [
        _ev(1, "agent_speech", "a", profile="zeta"),
        _ev(2, "agent_speech", "a", profile="alpha"),
    ]
    # 1 each → deterministic tie-break to the lexicographically smallest.
    assert resolve_agent_models(events)["a"] == "alpha"


def test_resolve_ignores_profileless_and_actorless_rows():
    events = [
        _ev(1, "world_paused", None, profile=None),
        _ev(2, "agent_moved", "a", profile=None),      # no profile → no vote
        _ev(3, "agent_speech", "a", profile="m1"),
    ]
    assert resolve_agent_models(events) == {"a": "m1"}


# ──────────────────────────────────────────────────────────────────────────────
# build_babel_matrix — classification + rates
# ──────────────────────────────────────────────────────────────────────────────

def test_matrix_cells_and_rates():
    m = build_babel_matrix(_mixed_run())
    assert m["version"] == BABEL_MATRIX_VERSION
    assert m["models"] == ["cerebras-qwen", "gemini-flash", "groq-llama"]
    assert set(m["families"]) == {"trade", "teach"}

    cells = {(c["actor"], c["target"]): c for c in m["cells"]}
    # A(gemini)→B(llama): 1 settle + 1 decline = 1/2.
    ab = cells[("gemini-flash", "groq-llama")]
    assert (ab["total"], ab["positive"], ab["rate"]) == (2, 1, 0.5)
    assert ab["by_family"]["trade"] == {"total": 2, "positive": 1, "rate": 0.5}
    # C(qwen)→B(llama): 2/2.
    cb = cells[("cerebras-qwen", "groq-llama")]
    assert (cb["total"], cb["positive"], cb["rate"]) == (2, 2, 1.0)
    # B(llama)→A(gemini): teach 1/2.
    ba = cells[("groq-llama", "gemini-flash")]
    assert (ba["total"], ba["positive"], ba["rate"]) == (2, 1, 0.5)
    assert ba["by_family"]["teach"] == {"total": 2, "positive": 1, "rate": 0.5}

    assert m["totals"]["outcomes"] == 6
    assert m["totals"]["positive"] == 4
    assert m["totals"]["cells"] == 3


def test_self_interaction_dropped():
    events = [
        _ev(1, "agent_speech", "a", profile="m1"),
        _ev(2, "trade_settled", "a", target="a"),  # actor == target → skip
    ]
    m = build_babel_matrix(events)
    assert m["cells"] == []
    assert m["totals"]["outcomes"] == 0


def test_unknown_model_on_one_end_dropped():
    # 'ghost' never carried a profile → unresolvable → outcome dropped.
    events = [
        _ev(1, "agent_speech", "a", profile="m1"),
        _ev(2, "trade_settled", "a", target="ghost"),
    ]
    m = build_babel_matrix(events)
    assert m["cells"] == []
    assert m["totals"]["outcomes"] == 0
    assert m["models"] == []


def test_family_filter():
    m = build_babel_matrix(_mixed_run(), family="trade")
    assert m["family"] == "trade"
    assert m["families"] == ["trade"]
    for c in m["cells"]:
        assert set(c["by_family"].keys()) == {"trade"}
    # The teach-only B→A cell must be absent under the trade filter.
    keys = {(c["actor"], c["target"]) for c in m["cells"]}
    assert ("groq-llama", "gemini-flash") not in keys
    assert m["totals"]["outcomes"] == 4


# ──────────────────────────────────────────────────────────────────────────────
# Receipts — evidence, ordering, cap, ground-truth annotation
# ──────────────────────────────────────────────────────────────────────────────

def test_receipts_present_newest_first_with_routed_via():
    m = build_babel_matrix(_mixed_run())
    ab = next(c for c in m["cells"] if (c["actor"], c["target"]) == ("gemini-flash", "groq-llama"))
    seqs = [r["seq"] for r in ab["receipts"]]
    assert seqs == sorted(seqs, reverse=True)  # newest-first
    # The settle receipt carries the ground-truth routed_via annotation.
    settle = next(r for r in ab["receipts"] if r["kind"] == "trade_settled")
    assert settle["routed_via"] == "gemini-2.0-flash"
    assert settle["positive"] is True
    decline = next(r for r in ab["receipts"] if r["kind"] == "trade_declined")
    assert decline["positive"] is False
    assert decline["routed_via"] is None


def test_receipt_cap_flags_and_truncates():
    events = [_ev(1, "agent_speech", "a", profile="m1"),
              _ev(2, "agent_speech", "b", profile="m2")]
    # 5 settled a→b, cap at 2.
    for i in range(5):
        events.append(_ev(100 + i, "trade_settled", "a", target="b"))
    m = build_babel_matrix(events, receipt_cap=2)
    cell = m["cells"][0]
    assert cell["total"] == 5
    assert len(cell["receipts"]) == 2
    # Kept the freshest (highest seqs).
    assert [r["seq"] for r in cell["receipts"]] == [104, 103]
    assert m["totals"]["receipts_capped"] is True


# ──────────────────────────────────────────────────────────────────────────────
# Confidence — Wilson interval honesty
# ──────────────────────────────────────────────────────────────────────────────

def test_wilson_interval_brackets_rate_and_is_wider_for_thin_samples():
    m = build_babel_matrix(_mixed_run())
    for c in m["cells"]:
        assert 0.0 <= c["ci_lo"] <= c["rate"] <= c["ci_hi"] <= 1.0
    # A 2/2 cell (thin, all-positive) keeps an honest ci_lo well below 1.0.
    cb = next(c for c in m["cells"] if (c["actor"], c["target"]) == ("cerebras-qwen", "groq-llama"))
    assert cb["rate"] == 1.0
    assert cb["ci_lo"] < 0.5  # 2/2 is NOT confidently 100%


# ──────────────────────────────────────────────────────────────────────────────
# Determinism + purity (replay-off-surface requirement)
# ──────────────────────────────────────────────────────────────────────────────

def test_deterministic_under_input_shuffle_and_no_mutation():
    events = _mixed_run()
    frozen = copy.deepcopy(events)
    baseline = build_babel_matrix(events)
    # Input list must not be mutated.
    assert events == frozen
    # Shuffled input → identical output (order-independent projection).
    shuffled = events[:]
    random.Random(1234).shuffle(shuffled)
    assert build_babel_matrix(shuffled) == baseline


def test_empty_events():
    m = build_babel_matrix([])
    assert m["models"] == []
    assert m["cells"] == []
    assert m["families"] == []
    assert m["totals"] == {"outcomes": 0, "positive": 0, "cells": 0, "receipts_capped": False}


# ──────────────────────────────────────────────────────────────────────────────
# Endpoint — flag gating (dark by default) + shape when enabled
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    import sys
    _appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as c:
        if _appmod._world is not None:
            _appmod._world.params.animals.enabled = False
            _appmod._world.animals.clear()
        yield c


def test_endpoint_404_when_disabled(client, monkeypatch):
    monkeypatch.delenv("PETRIDISH_BABEL_MATRIX_ENABLED", raising=False)
    assert client.get("/api/babel-matrix").status_code == 404


def test_endpoint_200_and_shape_when_enabled(client, monkeypatch):
    monkeypatch.setenv("PETRIDISH_BABEL_MATRIX_ENABLED", "1")
    res = client.get("/api/babel-matrix")
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == BABEL_MATRIX_VERSION
    for key in ("models", "cells", "families", "totals"):
        assert key in body


def test_endpoint_unknown_run_404_even_when_enabled(client, monkeypatch):
    monkeypatch.setenv("PETRIDISH_BABEL_MATRIX_ENABLED", "1")
    assert client.get("/api/babel-matrix?run_id=999999").status_code == 404

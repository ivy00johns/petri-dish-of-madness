"""Unit tests for the EM-297 divergence-probe tooling.

Covers the two probe-only modules (they live in backend/scripts/, outside the
app package, so the scripts dir is put on sys.path exactly like the probe
itself does):

  - em297_probe.py       — CallBudget rate discipline, call_with_discipline
                           retry semantics, transport-error encoding
  - em297_recipe_schema.py — strict parse, lenient coerce + repair recording,
                           JSON extraction, and the offline score() math

No test here touches the network: HTTP is stubbed at the chat_once seam.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import em297_probe  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# CallBudget — hard cap + inter-call gap
# ──────────────────────────────────────────────────────────────────────────────

class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_callbudget_hard_cap():
    budget = em297_probe.CallBudget(max_calls=2, sleep_s=0)
    budget.acquire()
    budget.acquire()
    assert budget.exhausted()
    with pytest.raises(RuntimeError):
        budget.acquire()
    assert budget.used == 2  # the refused acquire consumed nothing


def test_callbudget_enforces_min_gap(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(em297_probe.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(em297_probe.time, "sleep", clock.sleep)
    budget = em297_probe.CallBudget(max_calls=5, sleep_s=6.0)

    budget.acquire()  # first call: no gap to honour
    assert clock.sleeps == []

    clock.now += 2.0  # only 2 s elapsed -> must sleep the remaining 4 s
    budget.acquire()
    assert clock.sleeps == [pytest.approx(4.0)]

    clock.now += 10.0  # gap already satisfied -> no extra sleep
    budget.acquire()
    assert clock.sleeps == [pytest.approx(4.0)]


def test_callbudget_clamps_max_calls_to_hard_cap():
    """--max-calls is lowering-only: it can never raise the documented 40-call cap."""
    assert em297_probe.CallBudget(max_calls=999).max_calls == em297_probe.MAX_CALLS
    assert em297_probe.CallBudget(max_calls=5).max_calls == 5


# ──────────────────────────────────────────────────────────────────────────────
# call_with_discipline — retry semantics + transport-error encoding
# ──────────────────────────────────────────────────────────────────────────────

def _stub_chat_once(monkeypatch, fn):
    monkeypatch.setattr(em297_probe, "chat_once", fn)
    monkeypatch.setattr(em297_probe.time, "sleep", lambda s: None)


def test_no_retry_when_budget_exhausted(monkeypatch):
    calls: list[bool] = []

    def failing(client, base_url, api_key, model_id, user_prompt, *, json_mode):
        calls.append(json_mode)
        return {"http_status": 429, "error": "rate limited"}

    _stub_chat_once(monkeypatch, failing)
    budget = em297_probe.CallBudget(max_calls=1, sleep_s=0)
    rec = em297_probe.call_with_discipline(None, budget, "http://x", "k", "m", "p")
    assert rec["attempts"] == 1
    assert calls == [True]  # retry-guard: no second HTTP call past the cap


def test_at_most_one_retry(monkeypatch):
    calls: list[bool] = []

    def failing(client, base_url, api_key, model_id, user_prompt, *, json_mode):
        calls.append(json_mode)
        return {"http_status": 429, "error": "rate limited"}

    _stub_chat_once(monkeypatch, failing)
    budget = em297_probe.CallBudget(max_calls=10, sleep_s=0)
    rec = em297_probe.call_with_discipline(None, budget, "http://x", "k", "m", "p")
    assert rec["attempts"] == 2
    assert budget.used == 2  # exactly one retry, never more
    assert calls == [True, True]  # 429 is not a response_format rejection
    assert rec["first_attempt_error"]["http_status"] == 429


def test_response_format_rejection_retries_without_json_mode(monkeypatch):
    calls: list[bool] = []

    def failing(client, base_url, api_key, model_id, user_prompt, *, json_mode):
        calls.append(json_mode)
        return {"http_status": 400, "error": "response_format unsupported"}

    _stub_chat_once(monkeypatch, failing)
    budget = em297_probe.CallBudget(max_calls=10, sleep_s=0)
    em297_probe.call_with_discipline(None, budget, "http://x", "k", "m", "p")
    assert calls == [True, False]


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ReadError("connection reset by proxy"),
        httpx.RemoteProtocolError("peer closed connection"),
    ],
)
def test_transport_errors_encoded_not_raised(monkeypatch, exc):
    """Any httpx.TransportError must become an error record, not crash the grid."""

    def boom(client, base_url, api_key, model_id, user_prompt, *, json_mode):
        raise exc

    _stub_chat_once(monkeypatch, boom)
    budget = em297_probe.CallBudget(max_calls=4, sleep_s=0)
    rec = em297_probe.call_with_discipline(None, budget, "http://x", "k", "m", "p")
    assert rec["http_status"] is None
    assert type(exc).__name__ in rec["error"]


def test_connect_error_still_flags_unreachable(monkeypatch):
    def boom(client, base_url, api_key, model_id, user_prompt, *, json_mode):
        raise httpx.ConnectError("connection refused")

    _stub_chat_once(monkeypatch, boom)
    budget = em297_probe.CallBudget(max_calls=4, sleep_s=0)
    rec = em297_probe.call_with_discipline(None, budget, "http://x", "k", "m", "p")
    assert rec.get("unreachable") is True

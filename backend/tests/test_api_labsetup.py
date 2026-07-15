"""Lab Setup — /api/config/flags + /api/estimate (Task 3).

`/api/config/flags` reports the current run's BAKED flag state (merges
explicit world.yaml blocks, absent-defaulted blocks like faith, and
adaptive_routing.discovery) plus group membership (prompt_weight vs
routing_ops) — "why now / why not before" in one place.

`/api/estimate` predicts the prompt size of a flag combo by running the REAL
builder (Task 2's `estimate_prompt`) against a flag-overridden shallow copy
of the live world. fix-don't-hide: it must NEVER fabricate a number — any
builder failure surfaces as {ok: false, error}, never a faked total.

Context-manager TestClient idiom (the test_capability.py idiom): a bare
`TestClient(app)` does NOT run the app's lifespan, so `_config`/`_world`
stay None and every endpoint 503s — assertions gated on `if status == 200`
would then silently verify nothing. `with TestClient(app, ...) as client:`
runs lifespan (conftest pins EM_DB_PATH=:memory: + mock providers, so this
is hermetic), so the 200 path is the asserted path here, not a tolerated one.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from petridish.api.app import app

PROMPT_WEIGHT_MIN = {"comm", "settlements", "faith"}


def test_config_flags_lists_groups_and_baked():
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.get("/api/config/flags")
        assert r.status_code == 200
        body = r.json()
        assert "baked" in body and "groups" in body
        assert PROMPT_WEIGHT_MIN.issubset(set(body["groups"]["prompt_weight"]))
        # baked covers every flag in both groups, values are real booleans.
        all_flags = set(body["groups"]["prompt_weight"]) | set(body["groups"]["routing_ops"])
        assert set(body["baked"].keys()) == all_flags
        assert all(isinstance(v, bool) for v in body["baked"].values())


def test_estimate_returns_total_and_breakdown():
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/estimate", json={"overrides": {"comm": True}})
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["total_input_tokens"] > 0
        assert any(row["key"] == "comm" for row in body["breakdown"])
        assert any(row["key"] == "base" for row in body["breakdown"])


def test_estimate_failure_is_reported_not_faked():
    # An unknown flag must not silently produce a number as if it cost tokens.
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/estimate", json={"overrides": {"not_a_real_flag": True}})
        assert r.status_code == 200
        body = r.json()
        # unknown flag is ignored (not in _PROMPT_WEIGHT_FLAGS) -> estimate
        # still succeeds, but it must never appear in the breakdown.
        assert body["ok"] is True
        assert all(row["key"] != "not_a_real_flag" for row in body["breakdown"])

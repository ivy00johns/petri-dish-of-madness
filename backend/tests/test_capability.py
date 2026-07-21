"""Lab Setup — capability table (EM-324 knowledge, encoded).

Pure derivation module tests: `build_capability_table` turns the curated
lanes.yaml `order`/`exclude` + the router's profile legend into a per-lane
{free, context_window, reliability} view. `order` = hand-ranked clean set;
`exclude` denylist + a seed reasoning-model set are the known truncators
(EM-324: command-a-plus/cohere truncate strict-JSON on the heavy agent
prompt). Fail-closed: anything not curated-clean or known-reasoning reports
`unknown`, never coerced to `clean`.

Endpoint half: GET /api/lanes/capability wires the live
`_config.world.adaptive_routing.order`/`.exclude` (tuples of the frozen
`LaneOrderEntry` dataclass — NOT dicts) through a dataclass->dict conversion
before calling the module, and surfaces `cast_pins` from `world.living_agents()`.
The smoke test below runs the FastAPI app under its lifespan (conftest pins
EM_DB_PATH=:memory: + mock providers, so this is hermetic) to prove that
conversion doesn't 500 — a bare import check would not catch a `.get()`
AttributeError on a live dataclass.
"""
from petridish.providers.capability import build_capability_table, REASONING_MODELS

ORDER = [
    {"source": "freellmapi", "model": "mistral-small-4-119b", "free": True},
    {"source": "freellmapi", "model": "gpt-oss-120b*", "free": True},
    {"source": "freellmapi", "model": "*", "free": True},
    {"source": "freellmapi", "model": "auto"},
    {"source": "anthropic", "model": "claude-sonnet-5", "free": False},
]
EXCLUDE = [{"source": "freellmapi", "model": "command-a-2"}]
PROFILES = [
    {"name": "mistral-small", "adapter": "openai", "model_id": "mistral-small-4-119b"},
    {"name": "kimi", "adapter": "openai", "model_id": "kimi-k2.6"},
    {"name": "command-a", "adapter": "openai", "model_id": "command-a-2"},
    {"name": "sonnet", "adapter": "anthropic", "model_id": "claude-sonnet-5"},
]


def test_clean_lane_from_curated_order():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "mistral-small")
    assert row["reliability"] == "clean"
    assert row["free"] is True


def test_reasoning_model_flagged_risky():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "kimi")
    assert row["reliability"] == "reasoning"   # kimi-k2.6 in REASONING_MODELS seed


def test_excluded_lane_is_reasoning_not_clean():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "command-a")
    assert row["reliability"] == "reasoning"   # in exclude denylist


def test_paid_lane_flag():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "sonnet")
    assert row["free"] is False


def test_cast_pins_passthrough():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={"Mox": "kimi"})
    assert t["cast_pins"] == {"Mox": "kimi"}


def test_capability_endpoint_smoke():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    # Context-manager form runs the app's lifespan -> _config/_router/world get
    # initialized (conftest pins EM_DB_PATH=:memory: + mock providers, so this
    # is hermetic). Bare TestClient(app) would NOT init and would 503.
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.get("/api/lanes/capability")
        assert r.status_code == 200
        body = r.json()
        assert "lanes" in body and isinstance(body["lanes"], list)
        assert "cast_pins" in body

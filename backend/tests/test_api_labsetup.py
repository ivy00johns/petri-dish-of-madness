"""Lab Setup — /api/config/flags + /api/estimate (Task 3) + /api/config/apply
(Task 4, the only write path in the panel).

`/api/config/flags` reports the current run's BAKED flag state (merges
explicit world.yaml blocks, absent-defaulted blocks like faith, and
adaptive_routing.discovery) plus group membership (prompt_weight vs
routing_ops) — "why now / why not before" in one place.

`/api/estimate` predicts the prompt size of a flag combo by running the REAL
builder (Task 2's `estimate_prompt`) against a flag-overridden shallow copy
of the live world. fix-don't-hide: it must NEVER fabricate a number — any
builder failure surfaces as {ok: false, error}, never a faked total.

`/api/config/apply` writes staged flag flips to config/world.yaml via
ruamel's comment-preserving round-trip loader (atomically — temp file +
os.replace) and returns the diff + restart_required (config bakes per-run —
the dev-reload-kills-live-sim ban means this never restarts in-process).
`discovery` is the one flag that does NOT live in world.yaml (it's
config/lanes.yaml's adaptive_routing.discovery) so it must come back in
`unapplied`, never silently written as a dead key. A typo'd/unknown override
key must come back in `unknown`, also never written. A true no-op (empty
overrides, all-unapplied/unknown, or values already matching disk) must not
touch the file at all, and `restart_required` reflects that (`bool(diff)`).

Context-manager TestClient idiom (the test_capability.py idiom): a bare
`TestClient(app)` does NOT run the app's lifespan, so `_config`/`_world`
stay None and every endpoint 503s — assertions gated on `if status == 200`
would then silently verify nothing. `with TestClient(app, ...) as client:`
runs lifespan (conftest pins EM_DB_PATH=:memory: + mock providers, so this
is hermetic), so the 200 path is the asserted path here, not a tolerated one.
"""
from __future__ import annotations

import shutil

import ruamel.yaml
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


# ──────────────────────────────────────────────────────────────────────────────
# /api/config/apply (Task 4) — the only write path in the panel.
# ──────────────────────────────────────────────────────────────────────────────

def test_apply_returns_diff_and_restart_required(tmp_path, monkeypatch):
    # Point the writer at a temp copy of world.yaml so the test never edits the
    # real config. `comm` ships enabled: true in world.yaml, so flipping it to
    # False is a real change (a real no-change is covered by the noop test).
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/config/apply", json={"overrides": {"comm": False}})
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            body = r.json()
            assert body["restart_required"] is True
            assert isinstance(body["diff"], list)
            assert {"flag": "comm", "from": True, "to": False} in body["diff"]


def test_apply_creates_absent_flag_block_and_writes_it_to_disk(tmp_path, monkeypatch):
    # `faith` is absent-defaulted in world.yaml — toggling it ON must CREATE
    # `faith: {enabled: true}` under `world:`, and the write must actually land
    # on disk (comment-preserving), not just in the returned diff.
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/config/apply", json={"overrides": {"faith": True}})
        assert r.status_code == 200
        body = r.json()
        assert {"flag": "faith", "from": False, "to": True} in body["diff"]
        assert body["restart_required"] is True

    yaml = ruamel.yaml.YAML()
    with open(dst) as fh:
        doc = yaml.load(fh)
    assert doc["world"]["faith"]["enabled"] is True


def test_apply_discovery_is_unapplied_not_written_to_world_yaml(tmp_path, monkeypatch):
    # `discovery` lives in config/lanes.yaml (adaptive_routing.discovery.enabled),
    # NOT world.yaml. Writing a dead `discovery:` block under `world:` would be a
    # silent no-op bake — the loader would never read it. The endpoint must
    # refuse to write it and report it back as `unapplied` instead.
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/config/apply", json={"overrides": {"discovery": True}})
        assert r.status_code == 200
        body = r.json()
        assert body["unapplied"] == ["discovery"]
        assert "lanes.yaml" in body["message"]
        assert all(d["flag"] != "discovery" for d in body["diff"])

    yaml = ruamel.yaml.YAML()
    with open(dst) as fh:
        doc = yaml.load(fh)
    assert "discovery" not in doc["world"]


def test_apply_noop_does_not_rewrite_file(tmp_path, monkeypatch):
    # Empty overrides -> empty diff -> the file must not be touched at all
    # (Fix 1): a no-op apply must never needlessly rewrite/reformat the
    # hand-maintained world.yaml.
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    before_bytes = dst.read_bytes()
    before_mtime = dst.stat().st_mtime_ns
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/config/apply", json={"overrides": {}})
        assert r.status_code == 200
        body = r.json()
        assert body["diff"] == []
        assert body["restart_required"] is False
        assert "no changes" in body["message"].lower()
    assert dst.read_bytes() == before_bytes
    assert dst.stat().st_mtime_ns == before_mtime


def test_apply_absent_flag_false_is_noop(tmp_path, monkeypatch):
    # `faith` is absent from world.yaml (an absent block implicitly defaults
    # to False). Posting False for an absent flag is therefore a no-op — it
    # must NOT create a `faith: {enabled: false}` block, must not appear in
    # `diff`, and must not write the file (Fix 2).
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    before_bytes = dst.read_bytes()
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post("/api/config/apply", json={"overrides": {"faith": False}})
        assert r.status_code == 200
        body = r.json()
        assert body["diff"] == []
        assert body["restart_required"] is False
    assert dst.read_bytes() == before_bytes

    yaml = ruamel.yaml.YAML()
    with open(dst) as fh:
        doc = yaml.load(fh)
    assert "faith" not in doc["world"]


def test_apply_unknown_flag_reported_not_written(tmp_path, monkeypatch):
    # A typo'd/unknown override key (not in _PROMPT_WEIGHT_FLAGS or
    # _ROUTING_OPS_FLAGS) must never be baked as a dead key under `world:` —
    # the loader would never read it back. It must be surfaced honestly via
    # `unknown`, and must never appear in `diff` (Fix 3).
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    before_bytes = dst.read_bytes()
    with TestClient(app, raise_server_exceptions=True) as client:
        r = client.post(
            "/api/config/apply",
            json={"overrides": {"totally_bogus_flag_xyz": True}},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["unknown"] == ["totally_bogus_flag_xyz"]
        assert all(d["flag"] != "totally_bogus_flag_xyz" for d in body["diff"])
        # An unknown-only override set is also a no-op write (Fix 1 tie-in).
        assert body["diff"] == []
        assert body["restart_required"] is False
    assert dst.read_bytes() == before_bytes

    yaml = ruamel.yaml.YAML()
    with open(dst) as fh:
        doc = yaml.load(fh)
    assert "totally_bogus_flag_xyz" not in doc["world"]

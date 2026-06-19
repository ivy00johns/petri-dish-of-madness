"""
EM-222 — ONE live smoke test for the real embedding lane, gated by skipif.

Everything else in the EM-222 suite is hermetic (the conftest pins
EM_EMBED_MOCK=1 so the embed lane is a deterministic MockProvider). This file is
the SINGLE exception: it temporarily DROPS EM_EMBED_MOCK, loads the SHIPPED
config (the real `embed` profile pointing at the FreeLLMAPI proxy on :3001), and
makes ONE real `router.embed(['hello world'])` call to prove the live lane
returns a 1024-dim (bge-m3) vector.

It is written to be GREEN on CI WITHOUT the proxy: any of
  - no FREELLMAPI_KEY (env or .env),
  - the :3001 proxy unreachable / connection refused,
  - the proxy answering with a ProviderError,
  - the router having no embed profile,
results in pytest.skip(), never a failure. Run it locally with the proxy up to
exercise the real embedding lane.

Self-check (with proxy + key):
  backend/.venv/bin/python -m pytest backend/tests/test_em222_live.py -q
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from petridish.config.loader import load_config
from petridish.providers.base import ProviderError
from petridish.providers.router import Router


# The shipped config lives at <repo>/config (this file is <repo>/backend/tests).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_DIR = _REPO_ROOT / "config"
_ENV_FILE = _REPO_ROOT / ".env"

_EXPECTED_DIM = 1024  # bge-m3 width (the shipped embed profile's model)


def _freellmapi_key() -> str | None:
    """The proxy key from the env, falling back to a bare parse of <repo>/.env
    (KEY=VALUE lines). Returns None when absent — the test then skips."""
    key = os.environ.get("FREELLMAPI_KEY")
    if key:
        return key
    if not _ENV_FILE.exists():
        return None
    try:
        for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("FREELLMAPI_KEY=") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val:
                    return val
    except OSError:
        return None
    return None


async def test_live_embed_returns_1024_dim_vector(monkeypatch):
    """One REAL embed call against the proxy — 1024-dim vector — or SKIP.

    Skips cleanly (CI-green) when the key is missing, the proxy is unreachable,
    or the lane answers with a ProviderError; only a reachable, configured proxy
    actually asserts the dimensionality."""
    key = _freellmapi_key()
    if not key:
        pytest.skip("no FREELLMAPI_KEY in env or .env — live embed smoke skipped")

    # Make the real lane live for THIS test only: drop the hermetic mock switch
    # and point load_config at the shipped config dir + the proxy key.
    monkeypatch.delenv("EM_EMBED_MOCK", raising=False)
    monkeypatch.setenv("EM_CONFIG_DIR", str(_CONFIG_DIR))
    monkeypatch.setenv("FREELLMAPI_KEY", key)

    cfg = load_config()
    router = Router(profiles=cfg.profiles, cache_enabled=False)
    if not router.has_embeddings:
        pytest.skip("shipped config has no `embed` profile — live smoke skipped")

    try:
        vecs = await router.embed(["hello world"])
    except ProviderError as exc:
        pytest.skip(f"embed proxy unreachable / error — skipping: {exc}")
    except (OSError, ConnectionError) as exc:  # pragma: no cover - transport
        pytest.skip(f"embed proxy connection failed — skipping: {exc}")

    assert len(vecs) == 1, "one input ⇒ one vector"
    assert len(vecs[0]) == _EXPECTED_DIM, (
        f"expected a {_EXPECTED_DIM}-dim bge-m3 vector, got {len(vecs[0])}"
    )
    assert all(isinstance(x, float) for x in vecs[0])

"""
EM-068 / EM-198 regression — the Router decision cache is config-gated
(`world.cache.enabled`, OFF since 2026-06-12 per the bounce-don't-cache
rescope), but `_build_world` never threaded the flag: the Router fell back to
its default-ON cache and served verbatim hits, so characters (animals most
visibly — their brief world-view prompts repeat tick to tick) parroted the same
line. These pin the wiring so `world.cache.enabled` actually reaches the Router.

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime (the api app imports runtime transitively).
"""
from __future__ import annotations

import petridish.engine.world  # noqa: F401  (import-order guard)
from petridish.config.loader import (
    CacheParams, ModelProfile, WorldConfig, WorldParams,
)
# NB: import the FUNCTION directly — `petridish/api/__init__.py` re-exports the
# FastAPI instance as `petridish.api.app`, so `from petridish.api import app`
# would grab the app object, not this module.
from petridish.api.app import _build_world


def _cfg(*, cache_enabled: bool) -> WorldConfig:
    return WorldConfig(
        world=WorldParams(cache=CacheParams(enabled=cache_enabled, max_entries=256)),
        profiles=[ModelProfile(name="mock", adapter="mock", model_id="mock",
                               color="#2ecc71")],
        places=[],
        agents=[],
    )


def test_build_world_disables_cache_when_config_says_off():
    _world, router, _runtime, _repo = _build_world(_cfg(cache_enabled=False))
    assert router._cache_enabled is False, \
        "world.cache.enabled=false must disable the Router decision cache"


def test_build_world_enables_cache_and_threads_max_when_config_says_on():
    _world, router, _runtime, _repo = _build_world(_cfg(cache_enabled=True))
    assert router._cache_enabled is True
    assert router._cache_max == 256, "world.cache.max_entries must be threaded too"

"""
Router: unified chat() interface over all adapters.
Manages per-agent profile assignment (hot-swappable at runtime).
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import OrderedDict
from typing import Any

from ..config.loader import ModelProfile
from .adapters import OpenAICompatibleAdapter, AnthropicAdapter, GeminiAdapter
from .base import Provider, ProviderError
from .mock import MockProvider

log = logging.getLogger(__name__)

# W7 / EM-068 — default bound on the Router decision cache (config: world.cache.max_entries).
_DEFAULT_CACHE_MAX = 512


def _cache_key(profile_name: str, messages: list[dict]) -> str:
    """sha1(profile_name + json(messages, sort_keys=True)).

    The messages already embed persona + retrieved memory + coarse world state, so
    an identical key means an identical situation (per contracts/providers.md
    §Decision caching). sort_keys makes the digest stable across dict ordering.
    """
    payload = profile_name + json.dumps(messages, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _build_adapter(profile: ModelProfile) -> Provider:
    adapter = profile.adapter
    name = profile.name
    color = profile.color

    if adapter == "mock":
        p = MockProvider()
        p.name = name  # type: ignore[attr-defined]
        p.color = color  # type: ignore[attr-defined]
        return p  # type: ignore[return-value]

    api_key = profile.api_key() or ""

    if adapter == "openai":
        return OpenAICompatibleAdapter(
            profile=name,
            base_url=profile.base_url or "http://localhost:3001/v1",
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    elif adapter == "anthropic":
        return AnthropicAdapter(
            profile=name,
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    elif adapter == "gemini":
        return GeminiAdapter(
            profile=name,
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    else:
        raise ValueError(f"Unknown adapter: {adapter!r}")


class Router:
    def __init__(
        self,
        profiles: list[ModelProfile],
        adapter_overrides: dict[str, Provider] | None = None,
        *,
        cache_enabled: bool = True,
        cache_max: int = _DEFAULT_CACHE_MAX,
    ):
        self._profiles: dict[str, ModelProfile] = {p.name: p for p in profiles}
        self._adapters: dict[str, Provider] = {
            p.name: _build_adapter(p) for p in profiles
        }
        if adapter_overrides:
            self._adapters.update(adapter_overrides)
        # per-agent overrides: agent_id -> profile_name
        self._agent_profiles: dict[str, str] = {}

        # ── W7 / EM-068 — Router-level decision cache ──────────────────────────
        # Internal LRU keyed on sha1(profile_name + json(messages)). On a HIT we
        # return the cached text WITHOUT touching the adapter; the next
        # last_usage(profile)/last_routed_via(profile) read then reflects the
        # cached snapshot (cached=true, tokens null, latency ~0). ENABLED by
        # default; `cache_enabled=False` disables; `cache_max` bounds the LRU.
        # The mock adapter is NEVER cached (it is deterministic already).
        self._cache_enabled: bool = bool(cache_enabled)
        self._cache_max: int = max(0, int(cache_max))
        # key -> {"text", "routed_via", "usage"}; OrderedDict = LRU by insertion/access.
        self._cache: OrderedDict[str, dict] = OrderedDict()
        # Per-profile pending HIT snapshot. Set on a cache HIT so the subsequent
        # last_usage(profile)/last_routed_via(profile) reads (which the runtime
        # performs right after chat()) report the cached values instead of the
        # adapter's stale state. Cleared on a MISS so real adapter state surfaces.
        # profile_name -> {"routed_via": str|None, "usage": dict|None}
        self._pending_cached: dict[str, dict] = {}

    # ──────────────────────────────────────────────────────────────────────────

    def reassign(self, agent_id: str, profile_name: str) -> None:
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name!r}")
        self._agent_profiles[agent_id] = profile_name

    def profile_for(self, agent_id: str) -> ModelProfile:
        profile_name = self._agent_profiles.get(agent_id)
        if profile_name:
            return self._profiles[profile_name]
        raise KeyError(f"No profile mapping for agent {agent_id!r}")

    def profile_name_for(self, agent_id: str, default_profile: str) -> str:
        return self._agent_profiles.get(agent_id, default_profile)

    def _is_mock_profile(self, profile_name: str) -> bool:
        """True when the profile's adapter is the deterministic mock — never cached."""
        profile = self._profiles.get(profile_name)
        return bool(profile is not None and profile.adapter == "mock")

    def _cacheable(self, profile_name: str) -> bool:
        return self._cache_enabled and self._cache_max > 0 and not self._is_mock_profile(profile_name)

    @staticmethod
    def _cached_usage_snapshot(usage: dict | None) -> dict:
        """Usage snapshot surfaced on a HIT: cached=true, tokens null, latency ~0.

        Preserves the finish_reason of the original completion when available so
        downstream llm_call rows keep a sane stop reason.
        """
        finish_reason = usage.get("finish_reason") if isinstance(usage, dict) else None
        return {
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": 0.0,
            "finish_reason": finish_reason,
            "cached": True,
        }

    async def chat(
        self,
        profile_name: str,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        adapter = self._adapters.get(profile_name)
        if adapter is None:
            raise ProviderError(profile_name, None, "no adapter for profile")

        cacheable = self._cacheable(profile_name)
        key: str | None = None
        if cacheable:
            key = _cache_key(profile_name, messages)
            hit = self._cache.get(key)
            if hit is not None:
                # ── HIT ── return cached text WITHOUT calling the adapter. Stage a
                # pending snapshot so the runtime's immediate last_usage(profile) /
                # last_routed_via(profile) reads report cached=true (tokens null,
                # latency ~0) and the cached routed value.
                self._cache.move_to_end(key)  # LRU: mark most-recently-used
                self._pending_cached[profile_name] = {
                    "routed_via": hit.get("routed_via"),
                    "usage": self._cached_usage_snapshot(hit.get("usage")),
                }
                return hit["text"]

        # ── MISS (or non-cacheable) ── call the adapter as today. Clear any stale
        # pending HIT snapshot so the adapter's real last_routed_via/last_usage
        # surface unchanged for this profile.
        self._pending_cached.pop(profile_name, None)
        text = await adapter.chat(messages, max_tokens=max_tokens, temperature=temperature)

        if cacheable and key is not None:
            self._cache[key] = {
                "text": text,
                "routed_via": getattr(adapter, "last_routed_via", None),
                "usage": getattr(adapter, "last_usage", None),
            }
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)  # evict least-recently-used
        return text

    def clear_cache(self) -> None:
        """Flush the decision cache + pending HIT snapshots (W9, audit B12).
        Called on world reset so prior-run decisions never serve into a new run."""
        self._cache.clear()
        self._pending_cached.clear()

    def last_routed_via(self, profile_name: str) -> str | None:
        """Return the model the proxy actually routed the last request to for
        this profile's persistent adapter, or None if unknown.

        After a cache HIT this reflects the CACHED routed value (staged by chat())
        rather than the adapter's stale state (W7 / EM-068)."""
        pending = self._pending_cached.get(profile_name)
        if pending is not None:
            return pending["routed_via"]
        return getattr(self._adapters.get(profile_name), "last_routed_via", None)

    def last_usage(self, profile_name: str) -> dict | None:
        """Return the token/timing usage of the last successful chat() for this
        profile's persistent adapter, or None if unknown / not captured (Mock).
        Shape per contracts/providers.md §Usage capture:
        {input_tokens, output_tokens, latency_ms, finish_reason, cached}.

        After a cache HIT this returns the cached snapshot (cached=true, tokens
        null, latency ~0) staged by chat() (W7 / EM-068)."""
        pending = self._pending_cached.get(profile_name)
        if pending is not None:
            return pending["usage"]
        return getattr(self._adapters.get(profile_name), "last_usage", None)

    async def health(self, profile_name: str) -> bool:
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        if profile.adapter == "mock":
            return True
        # Cheap: just check that API key is present
        return bool(profile.api_key())

    def legend(self) -> list[dict]:
        import asyncio
        result = []
        for name, profile in self._profiles.items():
            result.append({
                "name": name,
                "adapter": profile.adapter,
                "model_id": profile.model_id,
                "color": profile.color,
                "available": profile.available(),
            })
        return result

    def profile_names(self) -> list[str]:
        return list(self._profiles.keys())

    def get_profile(self, name: str) -> ModelProfile | None:
        return self._profiles.get(name)

    def inject_world(self, world: object) -> None:
        """Inject world reference into MockProvider instances so they can vote dynamically."""
        for adapter in self._adapters.values():
            if hasattr(adapter, "set_world"):
                adapter.set_world(world)

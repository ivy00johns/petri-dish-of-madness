"""
Router: unified chat() interface over all adapters.
Manages per-agent profile assignment (hot-swappable at runtime).
"""
from __future__ import annotations

import logging
from typing import Any

from ..config.loader import ModelProfile
from .adapters import OpenAICompatibleAdapter, AnthropicAdapter, GeminiAdapter
from .base import Provider, ProviderError
from .mock import MockProvider

log = logging.getLogger(__name__)


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
    ):
        self._profiles: dict[str, ModelProfile] = {p.name: p for p in profiles}
        self._adapters: dict[str, Provider] = {
            p.name: _build_adapter(p) for p in profiles
        }
        if adapter_overrides:
            self._adapters.update(adapter_overrides)
        # per-agent overrides: agent_id -> profile_name
        self._agent_profiles: dict[str, str] = {}

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
        return await adapter.chat(messages, max_tokens=max_tokens, temperature=temperature)

    def last_routed_via(self, profile_name: str) -> str | None:
        """Return the model the proxy actually routed the last request to for
        this profile's persistent adapter, or None if unknown."""
        return getattr(self._adapters.get(profile_name), "last_routed_via", None)

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

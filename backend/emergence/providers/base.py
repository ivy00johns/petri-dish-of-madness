"""Base types for the provider layer."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


class ProviderError(Exception):
    """Raised by adapters on transport/HTTP failure. Must NOT crash the loop."""

    def __init__(self, profile: str, status: int | None, detail: str):
        super().__init__(f"[{profile}] {status}: {detail}")
        self.profile = profile
        self.status = status
        self.detail = detail


@runtime_checkable
class Provider(Protocol):
    name: str
    color: str
    # The model the proxy *actually* routed the last request to. Set by the
    # adapter after a successful chat() call; None until then. Part of the
    # interface so callers can surface the real model per turn.
    last_routed_via: str | None

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Return the assistant message text. Raises ProviderError on failure."""
        ...

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
    # W6 / EM-067 — token + timing usage of the last successful chat() call.
    # Shape (null-tolerant; Gemini free tier often omits token counts):
    #   {"input_tokens": int|None, "output_tokens": int|None,
    #    "latency_ms": float, "finish_reason": str|None, "cached": bool}
    # None for Mock and until the first successful call / on error. Surfaced
    # alongside last_routed_via so the runtime can populate the llm_call span.
    last_usage: dict | None

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        """Return the assistant message text. Raises ProviderError on failure."""
        ...

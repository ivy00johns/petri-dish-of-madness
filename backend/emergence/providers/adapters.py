"""
Concrete provider adapters:
  - OpenAICompatibleAdapter  (FreeLLMAPI, Ollama, Groq, etc.)
  - AnthropicAdapter
  - GeminiAdapter

All: 30s timeout, 1 network retry on 5xx/429, then ProviderError.
"""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from .base import Provider, ProviderError

log = logging.getLogger(__name__)

_TIMEOUT = 30.0
_RETRY_STATUSES = {429, 500, 502, 503, 504}


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
    profile: str,
) -> dict:
    for attempt in range(2):
        try:
            resp = await client.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt == 0:
                await asyncio.sleep(1.0)
                continue
            raise ProviderError(profile, None, str(exc)) from exc

        if resp.status_code in _RETRY_STATUSES and attempt == 0:
            log.warning("[%s] HTTP %d, retrying…", profile, resp.status_code)
            await asyncio.sleep(1.5)
            continue

        if not resp.is_success:
            raise ProviderError(profile, resp.status_code, resp.text[:300])

        return resp.json()

    raise ProviderError(profile, None, "exhausted retries")


# ──────────────────────────────────────────────────────────────────────────────
# OpenAI-compatible
# ──────────────────────────────────────────────────────────────────────────────

class OpenAICompatibleAdapter:
    """Covers FreeLLMAPI, Ollama /v1, Groq, vLLM, LM Studio, etc."""

    def __init__(self, profile: str, base_url: str, api_key: str, model_id: str, color: str):
        self.name = profile
        self.color = color
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_id = model_id

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": self._model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        async with httpx.AsyncClient() as client:
            data = await _post_with_retry(client, url, headers, payload, self.name)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, None, f"unexpected response shape: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Anthropic
# ──────────────────────────────────────────────────────────────────────────────

class AnthropicAdapter:
    def __init__(self, profile: str, api_key: str, model_id: str, color: str):
        self.name = profile
        self.color = color
        self._api_key = api_key
        self._model_id = model_id
        self._base_url = "https://api.anthropic.com"

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        # Split system message out
        system_parts = [m["content"] for m in messages if m["role"] == "system"]
        user_msgs = [m for m in messages if m["role"] != "system"]

        url = f"{self._base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        payload: dict = {
            "model": self._model_id,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": user_msgs,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        async with httpx.AsyncClient() as client:
            data = await _post_with_retry(client, url, headers, payload, self.name)
        try:
            return data["content"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, None, f"unexpected response shape: {exc}") from exc


# ──────────────────────────────────────────────────────────────────────────────
# Gemini
# ──────────────────────────────────────────────────────────────────────────────

class GeminiAdapter:
    def __init__(self, profile: str, api_key: str, model_id: str, color: str):
        self.name = profile
        self.color = color
        self._api_key = api_key
        self._model_id = model_id

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        # Map OpenAI roles → Gemini roles
        role_map = {"system": "user", "user": "user", "assistant": "model"}
        contents = [
            {"role": role_map.get(m["role"], "user"), "parts": [{"text": m["content"]}]}
            for m in messages
        ]
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models"
            f"/{self._model_id}:generateContent?key={self._api_key}"
        )
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        async with httpx.AsyncClient() as client:
            data = await _post_with_retry(client, url, {}, payload, self.name)
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, None, f"unexpected response shape: {exc}") from exc

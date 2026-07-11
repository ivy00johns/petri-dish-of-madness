"""
Concrete provider adapters:
  - OpenAICompatibleAdapter  (FreeLLMAPI, Ollama, Groq, etc.)
  - AnthropicAdapter
  - GeminiAdapter

All: 30s timeout, 1 network retry on 5xx/429, then ProviderError.
"""
from __future__ import annotations

import json
import logging
import time

import httpx

from .base import Provider, ProviderError

log = logging.getLogger(__name__)

_TIMEOUT = 30.0


def _coerce_int(value: object) -> int | None:
    """Best-effort int coercion for token counts that may arrive as int, str,
    float, or be absent/null. Returns None when no usable number is present."""
    if value is None:
        return None
    if isinstance(value, bool):  # guard: bool is an int subclass
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (ValueError, AttributeError):
            return None
    return None


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    payload: dict,
    profile: str,
) -> tuple[dict, str | None]:
    """Single POST. Returns (parsed_json, routed_via) or raises ProviderError.

    EM-205 — NO same-model retry. A 429 / 5xx / timeout is raised straight to
    the Router, which retries the call ONCE on the proxy's `auto` router lane
    instead of re-hitting the same (often throttled) model. Re-hitting the same
    rate-limited upstream was pure amplification during a storm. (Name kept for
    the test_w10 monkeypatch; the per-adapter JSON-mode negotiation in chat()
    still calls this twice when a provider rejects `response_format`.)

    `routed_via` is the value of the 'X-Routed-Via' response header (the model
    the proxy actually routed to), or None if the header is absent. httpx
    headers are case-insensitive, so the lookup matches any header casing.
    """
    try:
        resp = await client.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
    except httpx.TimeoutException as exc:
        # httpx timeout exceptions frequently stringify to '' — which surfaced in
        # the feed as a blank `provider_error:` badge (the dominant failure mode
        # when the FreeLLMAPI proxy hangs / is super slow). Give it an explicit,
        # non-empty detail so the feed + the EM-226 pause reason are legible.
        raise ProviderError(profile, None, f"timed out after {_TIMEOUT:.0f}s") from exc
    except httpx.ConnectError as exc:
        # Proxy unreachable / network down. str(exc) is usually non-empty here,
        # but guard the blank case so the badge is never empty.
        detail = str(exc).strip() or "connection refused"
        raise ProviderError(profile, None, f"network unreachable: {detail}") from exc

    if not resp.is_success:
        raise ProviderError(profile, resp.status_code, resp.text[:300])

    routed_via = resp.headers.get("X-Routed-Via")
    return resp.json(), routed_via


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
        self.last_routed_via: str | None = None
        self.last_usage: dict | None = None
        # Ask for a JSON object so weak free models can't drift into prose
        # (the T8 idle-fallback failure). Sticky-disabled the first time a
        # provider rejects the param — see chat().
        self._json_mode = True

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        # Only send the bearer token when we actually have one. An empty/whitespace
        # key would produce "Authorization: Bearer " — which httpx rejects with a
        # cryptic "Illegal header value". Omitting the header instead lets keyless
        # servers (e.g. Ollama) work and lets auth-required proxies (FreeLLMAPI)
        # return a clear 401 ProviderError rather than crashing client-side.
        api_key = (self._api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        def _payload(json_mode: bool) -> dict:
            p = {
                "model": self._model_id,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                p["response_format"] = {"type": "json_object"}
            return p

        # Time the whole post (incl. retry/backoff) with perf_counter (W6).
        started = time.perf_counter()
        async with httpx.AsyncClient() as client:
            try:
                data, routed_via = await _post_with_retry(
                    client, url, headers, _payload(self._json_mode), self.name
                )
            except ProviderError as exc:
                # Providers that don't understand `response_format` answer 4xx.
                # Disable JSON mode for this adapter's lifetime and retry once
                # WITHOUT it — degrade to plain prompting, not a dead tick.
                if not self._json_mode or exc.status not in (400, 404, 422):
                    raise
                log.warning(
                    "[%s] response_format rejected (HTTP %s); disabling JSON mode",
                    self.name, exc.status,
                )
                self._json_mode = False
                data, routed_via = await _post_with_retry(
                    client, url, headers, _payload(False), self.name
                )
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        # Surface the model the proxy actually routed to. Prefer the explicit
        # X-Routed-Via header, then the body's "model" field, then our request.
        self.last_routed_via = routed_via or data.get("model") or self._model_id
        # Capture token usage (OpenAI shape) + finish_reason. Null-tolerant: free
        # proxies sometimes omit `usage`; keep latency regardless.
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        finish_reason = None
        try:
            finish_reason = data["choices"][0].get("finish_reason")
        except (KeyError, IndexError, TypeError):
            finish_reason = None
        self.last_usage = {
            "input_tokens": _coerce_int(usage.get("prompt_tokens")),
            "output_tokens": _coerce_int(usage.get("completion_tokens")),
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
            "cached": False,
        }
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, None, f"unexpected response shape: {exc}") from exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """EM-222 — one vector per input text via POST {base_url}/embeddings.

        OpenAI embeddings shape: body {"model", "input": [...]}; response
        {"data": [{"index": int, "embedding": [...]}, ...]}. The proxy may
        return the data list out of order, so we sort by `index` to keep the
        vectors aligned with `texts`. Same httpx client + ProviderError
        semantics as chat(); NO decision-cache (embeddings ADD calls)."""
        url = f"{self._base_url}/embeddings"
        headers = {"Content-Type": "application/json"}
        # Same keyless-server tolerance as chat(): only send the bearer when we
        # actually have one (an empty "Authorization: Bearer " trips httpx).
        api_key = (self._api_key or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {"model": self._model_id, "input": texts}
        async with httpx.AsyncClient() as client:
            data, _routed_via = await _post_with_retry(
                client, url, headers, payload, self.name
            )
        try:
            items = sorted(data["data"], key=lambda d: d["index"])
            return [list(item["embedding"]) for item in items]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                self.name, None, f"unexpected embeddings response shape: {exc}"
            ) from exc


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
        self.last_routed_via: str | None = None
        self.last_usage: dict | None = None

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

        started = time.perf_counter()
        async with httpx.AsyncClient() as client:
            data, _routed_via = await _post_with_retry(client, url, headers, payload, self.name)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        self.last_routed_via = self._model_id
        # Anthropic Messages API: usage.input_tokens/output_tokens + stop_reason.
        usage = data.get("usage") if isinstance(data, dict) else None
        usage = usage if isinstance(usage, dict) else {}
        stop_reason = data.get("stop_reason") if isinstance(data, dict) else None
        self.last_usage = {
            "input_tokens": _coerce_int(usage.get("input_tokens")),
            "output_tokens": _coerce_int(usage.get("output_tokens")),
            "latency_ms": latency_ms,
            "finish_reason": stop_reason,
            "cached": False,
        }
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
        self.last_routed_via: str | None = None
        self.last_usage: dict | None = None

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
            f"/{self._model_id}:generateContent"
        )
        # Audit B11: the key travels in the x-goog-api-key header, never the URL
        # query string (query params leak into proxy/access logs and tracebacks).
        headers = {"x-goog-api-key": self._api_key}
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        started = time.perf_counter()
        async with httpx.AsyncClient() as client:
            data, _routed_via = await _post_with_retry(client, url, headers, payload, self.name)
        latency_ms = round((time.perf_counter() - started) * 1000, 3)
        self.last_routed_via = self._model_id
        # Gemini: usageMetadata.promptTokenCount/candidatesTokenCount (often absent
        # on the free tier → null). finishReason on the first candidate.
        meta = data.get("usageMetadata") if isinstance(data, dict) else None
        meta = meta if isinstance(meta, dict) else {}
        finish_reason = None
        try:
            finish_reason = data["candidates"][0].get("finishReason")
        except (KeyError, IndexError, TypeError):
            finish_reason = None
        self.last_usage = {
            "input_tokens": _coerce_int(meta.get("promptTokenCount")),
            "output_tokens": _coerce_int(meta.get("candidatesTokenCount")),
            "latency_ms": latency_ms,
            "finish_reason": finish_reason,
            "cached": False,
        }
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(self.name, None, f"unexpected response shape: {exc}") from exc

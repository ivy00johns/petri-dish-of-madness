"""Wave I / EM-210 — image providers (the Atelier's bytes source).

Contract (contracts/wave-i-atelier.md §1):
  - Protocol: `async def fetch_png(prompt: str) -> bytes | None` — PNG bytes or
    None on ANY failure (never raises into the loop).
  - Primary = FreeLLMAPI image lane (FREELLMAPI_KEY) — the proxy's `/images/
    generations` routes across its whole image-model pool; the image queues are
    short relative to chat, so it rarely rate-limits.
  - Next = Pollinations (keyless, zero-config, always present) so art never fully
    stops before any paid lane is tried.
  - Cloudflare Workers AI (CF_ACCOUNT_ID + CF_API_TOKEN) stays an optional env lane.
  - LAST backstop = Gemini (GEMINI_API_KEY) — gemini-2.5-flash-image (PAID; an
    unbilled key 429s and the chain ends with None). Free-first billing law: the
    paid lane only fires after every free lane misses. Override via
    EM_IMAGEGEN_GEMINI_MODEL.
  - Mock lane = EM_IMAGEGEN_MOCK: returns a fixed minimal valid PNG, no network.
  - Selection precedence (build_provider):
      EM_IMAGEGEN_MOCK
        > chain[ FreeLLMAPI (if key) , Pollinations (always, keyless) ,
                 Cloudflare (if env) , Gemini (if key, PAID last) ]
    Each chain member returns None on failure; ChainImageProvider tries the next.

The provider does NOT decide paths or ids — the loop hands it a prompt and writes
the bytes to the contract-derived path itself (replay-safety keystone: the PNG is
an external side-artifact that never re-enters the sim).
"""
from __future__ import annotations

import base64
import logging
import os
from typing import Protocol, runtime_checkable
from urllib.parse import quote

log = logging.getLogger(__name__)

# A fixed, minimal, VALID 1×1 RGBA PNG (deterministic; the mock lane returns this
# without any network call so the suite is hermetic — EM_IMAGEGEN_MOCK).
_MOCK_PNG: bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP4DwQACfsD/Wj6HMwAAAAASUVORK5CYII="
)

# Network knobs (the fetch is OFF the critical path; a generous-but-bounded timeout).
_TIMEOUT_SECONDS = 12.0
_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=512&height=512&nologo=true"
_CLOUDFLARE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}"
    "/ai/run/@cf/black-forest-labs/flux-1-schnell"
)
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-image"
# The FreeLLMAPI proxy's OpenAI-compatible image endpoint lives at {base}/images/
# generations, where {base} already ends in /v1 (parity with the chat lanes).
_FREELLMAPI_DEFAULT_BASE = "http://localhost:3001/v1"


@runtime_checkable
class ImageProvider(Protocol):
    """An image-bytes source. `fetch_png` returns PNG bytes or None on any
    failure; it MUST NEVER raise (the loop swallows nothing of its own)."""

    async def fetch_png(self, prompt: str) -> bytes | None:  # pragma: no cover - protocol
        ...


async def _get_url_bytes(client, url: str) -> bytes | None:
    """GET a url and return its bytes on 200, else None. Follows redirects
    (Pollinations + some proxy image lanes 302 to a CDN). Never raises."""
    try:
        resp = await client.get(url, follow_redirects=True)
        if resp.status_code == 200 and resp.content:
            return resp.content
    except Exception as exc:  # pragma: no cover - network defensive
        log.debug("image url fetch failed: %s", exc)
    return None


class MockImageProvider:
    """Hermetic lane (EM_IMAGEGEN_MOCK): a fixed tiny PNG, zero network."""

    async def fetch_png(self, prompt: str) -> bytes | None:
        return _MOCK_PNG


class PollinationsProvider:
    """Default, zero-config provider — GET image.pollinations.ai/prompt/{prompt}.
    Follows redirects, returns resp.content on 200, else None. Never raises."""

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        url = _POLLINATIONS_URL.format(prompt=quote(prompt, safe=""))
        try:
            import httpx
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=_TIMEOUT_SECONDS
            ) as client:
                resp = await client.get(url)
            if resp.status_code == 200 and resp.content:
                return resp.content
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("pollinations fetch failed: %s", exc)
        return None


class FreellmapiImageProvider:
    """EM-247 — PRIMARY: the FreeLLMAPI proxy's image lane. POST {base}/images/
    generations (OpenAI images shape) with the unified key; the proxy health-routes
    across its whole image-model pool (small queues ⇒ rarely throttled). The model
    is OPTIONAL — omitted ⇒ the proxy auto-picks; pin one via EM_IMAGEGEN_FREELLMAPI_MODEL.
    The response `data[i]` carries EITHER `b64_json` (decode) OR `url` (fetch); we
    handle both. Returns None on any failure (the chain owns fallback); never raises."""

    def __init__(self, base_url: str, api_key: str, model: str | None = None) -> None:
        self._base_url = (base_url or _FREELLMAPI_DEFAULT_BASE).rstrip("/")
        self._api_key = api_key
        self._model = (
            model or os.environ.get("EM_IMAGEGEN_FREELLMAPI_MODEL") or ""
        ).strip()

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        url = f"{self._base_url}/images/generations"
        payload: dict = {"prompt": prompt}
        if self._model:
            payload["model"] = self._model
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=headers, json=payload)
                if resp.status_code != 200:
                    log.debug("freellmapi image http %s: %s",
                              resp.status_code, resp.text[:200])
                    return None
                data = resp.json()
                for item in (data.get("data") or []):
                    b64 = item.get("b64_json")
                    if b64:
                        return base64.b64decode(b64)
                    img_url = item.get("url")
                    if img_url:
                        png = await _get_url_bytes(client, img_url)
                        if png is not None:
                            return png
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("freellmapi image fetch failed: %s", exc)
        return None


class GeminiImageProvider:
    """LAST backstop (GEMINI_API_KEY, PAID) — POST to Gemini generateContent and
    decode the inline base64 PNG from the first image part. Returns None on any
    failure (the chain owns fallback); never raises.

    Model defaults to gemini-2.5-flash-image (override via EM_IMAGEGEN_GEMINI_MODEL).
    Note: that model is PAID — its free-tier request quota is 0, so an unbilled key
    returns HTTP 429. Free-first billing law: this member sits at the END of the
    chain so it only fires after every free lane misses."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = (
            model
            or os.environ.get("EM_IMAGEGEN_GEMINI_MODEL")
            or _GEMINI_DEFAULT_MODEL
        ).strip()

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        url = _GEMINI_URL.format(model=self._model)
        # Key travels in the x-goog-api-key header, never the URL query string
        # (parity with the text GeminiAdapter — query params leak into logs).
        headers = {"x-goog-api-key": self._api_key}
        # TEXT+IMAGE is the broadly-accepted modality combo; the response may
        # interleave a text part, so we scan every part for the image below.
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
        }
        try:
            import httpx
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                log.debug("gemini image http %s: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            candidates = data.get("candidates") or []
            parts = (
                (candidates[0].get("content") or {}).get("parts") or []
                if candidates
                else []
            )
            for part in parts:
                inline = part.get("inlineData") or part.get("inline_data") or {}
                if inline.get("data"):
                    return base64.b64decode(inline["data"])
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("gemini image fetch failed: %s", exc)
        return None


class CloudflareProvider:
    """Optional env lane (CF_ACCOUNT_ID + CF_API_TOKEN) — POST to Workers AI
    flux-1-schnell, decoding the base64 image from the JSON response. Returns None
    on any failure (the chain owns fallback); never raises."""

    def __init__(self, account_id: str, api_token: str) -> None:
        self._account_id = account_id
        self._api_token = api_token

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        url = _CLOUDFLARE_URL.format(account_id=self._account_id)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_token}"},
                    json={"prompt": prompt},
                )
            if resp.status_code == 200:
                data = resp.json()
                # Workers AI returns {"result": {"image": "<base64>"}, ...}.
                b64 = (data.get("result") or {}).get("image")
                if b64:
                    return base64.b64decode(b64)
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("cloudflare fetch failed: %s", exc)
        return None


class ChainImageProvider:
    """Tries each provider in order; returns the first non-None PNG. The composable
    fallback that expresses FreeLLMAPI → Pollinations → Cloudflare → Gemini. A
    member that raises (it shouldn't) is caught and treated as a miss, so one bad
    lane never breaks the chain."""

    def __init__(self, providers: list[ImageProvider]) -> None:
        self._providers = [p for p in providers if p is not None]

    async def fetch_png(self, prompt: str) -> bytes | None:
        for provider in self._providers:
            try:
                png = await provider.fetch_png(prompt)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("image provider %s raised: %s",
                          type(provider).__name__, exc)
                png = None
            if png is not None:
                return png
        return None


def build_provider() -> ImageProvider:
    """Factory honoring the selection precedence (§1):
    EM_IMAGEGEN_MOCK > chain[FreeLLMAPI?, Pollinations, Cloudflare?, Gemini?].

    The chain is built from whichever keys/env are present; Pollinations is always
    present (keyless), ahead of the paid backstops — free-first billing law puts
    paid Gemini LAST, so a no-key deployment is exactly the prior default.
    A single-member chain returns that provider directly (no wrapper)."""
    if os.environ.get("EM_IMAGEGEN_MOCK"):
        return MockImageProvider()

    chain: list[ImageProvider] = []

    freellmapi_key = os.environ.get("FREELLMAPI_KEY")
    if freellmapi_key:
        base = (
            os.environ.get("EM_IMAGEGEN_FREELLMAPI_URL")
            or os.environ.get("FREELLMAPI_BASE_URL")
            or _FREELLMAPI_DEFAULT_BASE
        )
        chain.append(FreellmapiImageProvider(base, freellmapi_key))

    chain.append(PollinationsProvider())  # keyless, free — always present

    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    if account_id and api_token:
        chain.append(CloudflareProvider(account_id, api_token))

    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        chain.append(GeminiImageProvider(gemini_key))  # PAID — last backstop

    return chain[0] if len(chain) == 1 else ChainImageProvider(chain)

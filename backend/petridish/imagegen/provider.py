"""Wave I / EM-210 — image providers (the Atelier's bytes source).

Contract (contracts/wave-i-atelier.md §1):
  - Protocol: `async def fetch_png(prompt: str) -> bytes | None` — PNG bytes or
    None on ANY failure (never raises into the loop).
  - Default = Pollinations (zero-config, no key).
  - Env opt-in = Gemini (GEMINI_API_KEY) — gemini-2.5-flash-image via
    generateContent; a PAID model (free-tier quota is 0), so an unbilled key
    429s and we fall back to Pollinations. Model override: EM_IMAGEGEN_GEMINI_MODEL.
  - Env opt-in = Cloudflare Workers AI (CF_ACCOUNT_ID + CF_API_TOKEN), falling
    back to Pollinations on any failure.
  - Mock lane = EM_IMAGEGEN_MOCK: returns a fixed minimal valid PNG, no network.
  - Selection precedence:
    EM_IMAGEGEN_MOCK > Gemini (if GEMINI_API_KEY) > Cloudflare (if env) > Pollinations.

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


@runtime_checkable
class ImageProvider(Protocol):
    """An image-bytes source. `fetch_png` returns PNG bytes or None on any
    failure; it MUST NEVER raise (the loop swallows nothing of its own)."""

    async def fetch_png(self, prompt: str) -> bytes | None:  # pragma: no cover - protocol
        ...


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


class CloudflareProvider:
    """Env opt-in (CF_ACCOUNT_ID + CF_API_TOKEN) — POST to Workers AI flux-1-schnell.
    Decodes the base64 image from the JSON response. Falls back to Pollinations on
    ANY failure (never raises)."""

    def __init__(self, account_id: str, api_token: str) -> None:
        self._account_id = account_id
        self._api_token = api_token
        self._fallback = PollinationsProvider()

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
            log.debug("cloudflare fetch failed, falling back: %s", exc)
        # On any failure, fall back to the no-key provider.
        return await self._fallback.fetch_png(prompt)


class GeminiImageProvider:
    """Env opt-in (GEMINI_API_KEY) — POST to Gemini generateContent and decode
    the inline base64 PNG from the first image part. Falls back to Pollinations
    on ANY failure (never raises).

    Model defaults to gemini-2.5-flash-image (override via EM_IMAGEGEN_GEMINI_MODEL).
    Note: that model is PAID — its free-tier request quota is 0, so an unbilled
    key returns HTTP 429 and every call falls through to the no-key provider."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self._api_key = api_key
        self._model = (
            model
            or os.environ.get("EM_IMAGEGEN_GEMINI_MODEL")
            or _GEMINI_DEFAULT_MODEL
        ).strip()
        self._fallback = PollinationsProvider()

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        png = await self._fetch_gemini(prompt)
        if png is not None:
            return png
        # On any failure (429 / quota / network / unexpected shape), fall back to
        # the free no-key provider so art keeps flowing.
        return await self._fallback.fetch_png(prompt)

    async def _fetch_gemini(self, prompt: str) -> bytes | None:
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
            log.debug("gemini image fetch failed, falling back: %s", exc)
        return None


def build_provider() -> ImageProvider:
    """Factory honoring the selection precedence (§1, extended for Gemini):
    EM_IMAGEGEN_MOCK > Gemini (if GEMINI_API_KEY) > Cloudflare (if env) > Pollinations."""
    if os.environ.get("EM_IMAGEGEN_MOCK"):
        return MockImageProvider()
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        return GeminiImageProvider(gemini_key)
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    if account_id and api_token:
        return CloudflareProvider(account_id, api_token)
    return PollinationsProvider()

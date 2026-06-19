"""Wave I / EM-210 — image providers (the Atelier's bytes source).

Contract (contracts/wave-i-atelier.md §1):
  - Protocol: `async def fetch_png(prompt: str) -> bytes | None` — PNG bytes or
    None on ANY failure (never raises into the loop).
  - Default = Pollinations (zero-config, no key).
  - Env opt-in = Cloudflare Workers AI (CF_ACCOUNT_ID + CF_API_TOKEN), falling
    back to Pollinations on any failure.
  - Mock lane = EM_IMAGEGEN_MOCK: returns a fixed minimal valid PNG, no network.
  - Selection precedence: EM_IMAGEGEN_MOCK > Cloudflare (if env present) > Pollinations.

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


def build_provider() -> ImageProvider:
    """Factory honoring the selection precedence (§1):
    EM_IMAGEGEN_MOCK > Cloudflare (if env present) > Pollinations."""
    if os.environ.get("EM_IMAGEGEN_MOCK"):
        return MockImageProvider()
    account_id = os.environ.get("CF_ACCOUNT_ID")
    api_token = os.environ.get("CF_API_TOKEN")
    if account_id and api_token:
        return CloudflareProvider(account_id, api_token)
    return PollinationsProvider()

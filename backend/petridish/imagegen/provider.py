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
  - EM-302c — the paid lane carries a HARD per-run generation cap
    (`world.image_gen.paid_backstop_max_per_run`, default 25 ≈ $1/run): once
    `max_per_run` paid images have been generated this run, the Gemini member
    returns None WITHOUT any network call, so the (otherwise zero-cost)
    create_image/paint_surface reflex path can never grow an unbounded cost
    tail. Free lanes are never capped. 0 disables the paid lane outright;
    negative = unlimited (the pre-EM-302 behavior). The counter lives on the
    provider instance; the loop rebuilds the provider per run.
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
import ipaddress
import logging
import os
import socket
from typing import Protocol, runtime_checkable
from urllib.parse import quote, urljoin, urlsplit

log = logging.getLogger(__name__)

# A fixed, minimal, VALID 1×1 RGBA PNG (deterministic; the mock lane returns this
# without any network call so the suite is hermetic — EM_IMAGEGEN_MOCK).
_MOCK_PNG: bytes = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mP4DwQACfsD/Wj6HMwAAAAASUVORK5CYII="
)

# Network knobs (the fetch is OFF the critical path; a generous-but-bounded timeout).
_TIMEOUT_SECONDS = 12.0
# Write-guard (EM-287): provider bytes are written to data/assets/images and served
# to the browser as .png, so cap the size and require a real raster magic header
# before any bytes escape a provider. PNG is canonical (we serve .png); JPEG/GIF/
# WEBP are tolerated so a free lane that returns one of those isn't silently dropped
# to the PAID backstop (free-first billing law).
_MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MiB — a few MB, generous but bounded
_MAX_REDIRECTS = 3
_IMAGE_MAGIC: tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",  # PNG
    b"\xff\xd8\xff",        # JPEG
    b"GIF87a",
    b"GIF89a",             # GIF
)
_POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}?width=512&height=512&nologo=true"
_CLOUDFLARE_URL = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}"
    "/ai/run/@cf/black-forest-labs/flux-1-schnell"
)
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
_GEMINI_DEFAULT_MODEL = "gemini-2.5-flash-image"
# EM-302c — the default HARD cap on paid backstop generations per run (~$1/run
# at the flat ~$0.039/image). Mirrored by ImageGenParams.paid_backstop_max_per_run
# (config/loader.py) — keep the two in sync.
_PAID_BACKSTOP_DEFAULT_MAX = 25
# The FreeLLMAPI proxy's OpenAI-compatible image endpoint lives at {base}/images/
# generations, where {base} already ends in /v1 (parity with the chat lanes).
_FREELLMAPI_DEFAULT_BASE = "http://localhost:3001/v1"


@runtime_checkable
class ImageProvider(Protocol):
    """An image-bytes source. `fetch_png` returns PNG bytes or None on any
    failure; it MUST NEVER raise (the loop swallows nothing of its own)."""

    async def fetch_png(self, prompt: str) -> bytes | None:  # pragma: no cover - protocol
        ...


def _valid_image(data: bytes | None) -> bytes | None:
    """Return `data` iff it is a size-bounded, magic-byte-recognized raster image,
    else None (EM-287 write-guard). Rejects oversized bodies and non-image payloads
    (HTML/SVG/arbitrary text) that would otherwise be written and served as .png."""
    if not data or len(data) > _MAX_IMAGE_BYTES:
        return None
    if any(data.startswith(sig) for sig in _IMAGE_MAGIC):
        return data
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP is a two-part signature
        return data
    return None


def _resolve_ips(host: str) -> list[str]:
    """Resolve `host` → literal IP strings (all A/AAAA records). Split out so the
    SSRF guard is unit-testable via monkeypatch. Raises on a resolution failure
    (the caller treats that as unsafe — fail closed)."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _host_is_public(host: str) -> bool:
    """True iff `host` resolves and EVERY resolved IP is a public, routable address
    (EM-296). Rejects loopback / private / link-local (169.254.169.254 cloud
    metadata) / reserved / multicast / unspecified — checked on the RESOLVED ip so a
    name that resolves inward can't slip past."""
    if not host:
        return False
    try:
        ips = _resolve_ips(host)
    except Exception:
        return False
    if not ips:
        return False
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str.split("%", 1)[0])  # strip any zone id
        except ValueError:
            return False
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_multicast or ip.is_reserved or ip.is_unspecified):
            return False
    return True


def _url_is_public(url: str) -> bool:
    """http/https scheme + a host that resolves entirely to public IPs (SSRF guard)."""
    try:
        parts = urlsplit(url)
    except Exception:
        return False
    if parts.scheme not in ("http", "https"):
        return False
    return _host_is_public(parts.hostname or "")


async def _get_url_bytes(client, url: str) -> bytes | None:
    """Fetch an image url and return a validated raster image on 200, else None.
    Hardened (EM-296 SSRF + EM-287 write-guard): http/https only, the host must
    resolve entirely to public IPs, redirects are followed MANUALLY with each hop
    re-validated by the same guard (≤ _MAX_REDIRECTS), httpx auto-redirects are
    disabled, and the body is size/magic validated before it can be returned.
    Never raises."""
    for _ in range(_MAX_REDIRECTS + 1):
        if not _url_is_public(url):
            log.debug("image url rejected by SSRF guard: %s", url)
            return None
        try:
            resp = await client.get(url, follow_redirects=False)
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("image url fetch failed: %s", exc)
            return None
        status = getattr(resp, "status_code", 0)
        if status in (301, 302, 303, 307, 308):
            headers = getattr(resp, "headers", None) or {}
            location = headers.get("location")
            if not location:
                return None
            url = urljoin(url, location)  # re-validated at the top of the loop
            continue
        if status == 200 and resp.content:
            return _valid_image(resp.content)
        return None
    log.debug("image url exceeded redirect cap: %s", url)
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
                return _valid_image(resp.content)
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
                        png = _valid_image(base64.b64decode(b64))
                        if png is not None:
                            return png
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
    chain so it only fires after every free lane misses.

    EM-302c — `max_per_run` is the HARD cap on paid GENERATIONS this provider
    instance will serve (None ⇒ the module default; 0 ⇒ paid lane disabled;
    negative ⇒ unlimited, the pre-EM-302 behavior). Over the cap, fetch_png
    returns None with ZERO network calls — the chain's free results stand and
    the caller's keep-the-existing-image fallback takes over. A slot is
    reserved BEFORE the awaited call (check+increment is atomic on the
    single-threaded event loop), so concurrent fetches can never overshoot the
    cap. The slot is released ONLY when the attempt provably never billed (no
    HTTP 200 came back: network failure / non-200); a billed-but-REJECTED 200
    (unusable payload) keeps its slot consumed — Google charged for that
    generation, so releasing it would let real spend exceed the cap."""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        max_per_run: int | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = (
            model
            or os.environ.get("EM_IMAGEGEN_GEMINI_MODEL")
            or _GEMINI_DEFAULT_MODEL
        ).strip()
        self._max_per_run = (
            _PAID_BACKSTOP_DEFAULT_MAX if max_per_run is None else int(max_per_run)
        )
        self._paid_served = 0

    async def fetch_png(self, prompt: str) -> bytes | None:
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        capped = self._max_per_run >= 0
        if capped:
            if self._paid_served >= self._max_per_run:
                log.debug(
                    "gemini paid backstop over its per-run cap (%d) — skipping",
                    self._max_per_run)
                return None
            self._paid_served += 1  # reserve before the await (never overshoot)
        billed = True  # conservative: an unexpected raise keeps the slot
        try:
            png, billed = await self._generate(prompt)
        except Exception:  # pragma: no cover - _generate never raises (defensive)
            png = None
        finally:
            if capped and png is None and not billed:
                # The attempt provably never billed (no HTTP 200 came back) —
                # release the reserved slot. A billed-but-rejected 200 keeps
                # its slot: the generation was charged, so releasing would let
                # real spend exceed the cap.
                self._paid_served -= 1
        return png

    async def _generate(self, prompt: str) -> tuple[bytes | None, bool]:
        """The uncapped network call (the pre-EM-302 fetch_png body). Returns
        (png, billed) — `billed` flips True the moment an HTTP 200 response
        arrives, whether or not its payload yields a usable image (Google
        bills the generation on a 200; a rejected payload is still spend)."""
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
        billed = False
        try:
            import httpx
            async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                log.debug("gemini image http %s: %s", resp.status_code, resp.text[:200])
                return None, billed
            billed = True  # a 200 is a BILLED generation, usable payload or not
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
                    png = _valid_image(base64.b64decode(inline["data"]))
                    if png is not None:
                        return png, billed
        except Exception as exc:  # pragma: no cover - network defensive
            log.debug("gemini image fetch failed: %s", exc)
        return None, billed


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
                    return _valid_image(base64.b64decode(b64))
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


def build_provider(paid_backstop_max_per_run: int | None = None) -> ImageProvider:
    """Factory honoring the selection precedence (§1):
    EM_IMAGEGEN_MOCK > chain[FreeLLMAPI?, Pollinations, Cloudflare?, Gemini?].

    The chain is built from whichever keys/env are present; Pollinations is always
    present (keyless), ahead of the paid backstops — free-first billing law puts
    paid Gemini LAST, so a no-key deployment is exactly the prior default.
    A single-member chain returns that provider directly (no wrapper).

    EM-302c — `paid_backstop_max_per_run` is threaded into the paid Gemini
    member as its hard per-run generation cap (None ⇒ the module default 25;
    0 ⇒ paid disabled; negative ⇒ unlimited). Free lanes are never capped."""
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
        chain.append(GeminiImageProvider(  # PAID — last backstop, hard-capped
            gemini_key, max_per_run=paid_backstop_max_per_run))

    return chain[0] if len(chain) == 1 else ChainImageProvider(chain)

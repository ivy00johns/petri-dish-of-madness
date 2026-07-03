"""EM-247 — image provider chain (FreeLLMAPI → Pollinations → Cloudflare → Gemini).

The Atelier's bytes source gains a FreeLLMAPI primary (the proxy's /images/
generations, routed across its whole image-model pool) with keyless Pollinations
next and paid Gemini as the LAST backstop (free-first billing law — cost is cut
via ordering). Pinned here:

  * build_provider() precedence + chain composition by env (Mock wins; the chain
    is FreeLLMAPI? → Pollinations (always) → Cloudflare? → Gemini?, paid last).
  * FreellmapiImageProvider parses BOTH response shapes (b64_json AND url), and
    returns None (never raises) on a non-200 / malformed / empty response.
  * ChainImageProvider returns the FIRST non-None member and skips a member that
    returns None OR raises.

httpx is monkeypatched with a fake AsyncClient so the suite stays hermetic.
"""
from __future__ import annotations

import base64
import json

import pytest

from petridish.imagegen import build_provider
from petridish.imagegen.provider import (
    ChainImageProvider,
    CloudflareProvider,
    FreellmapiImageProvider,
    GeminiImageProvider,
    MockImageProvider,
    PollinationsProvider,
    _MOCK_PNG,
)


# A real, tiny, valid PNG (the mock one) — used as the "bytes the provider returns".
_PNG_BYTES = _MOCK_PNG
_PNG_B64 = base64.b64encode(_PNG_BYTES).decode("ascii")


# ── fake httpx ────────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status_code=200, content=b"", payload=None, text=""):
        self.status_code = status_code
        self.content = content
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    """Drop-in for httpx.AsyncClient: POST/GET return canned responses keyed by a
    handler the test installs. Records calls for assertions."""

    handler = None        # set per-test: (method, url, **kw) -> _FakeResp
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        _FakeClient.calls.append(("POST", url, kw))
        return _FakeClient.handler("POST", url, **kw)

    async def get(self, url, **kw):
        _FakeClient.calls.append(("GET", url, kw))
        return _FakeClient.handler("GET", url, **kw)


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    _FakeClient.calls = []
    _FakeClient.handler = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


# ── build_provider precedence + chain composition ─────────────────────────────

def test_mock_precedence_wins(monkeypatch):
    monkeypatch.setenv("EM_IMAGEGEN_MOCK", "1")
    assert isinstance(build_provider(), MockImageProvider)


def test_no_keys_is_bare_pollinations(monkeypatch):
    for k in ("EM_IMAGEGEN_MOCK", "FREELLMAPI_KEY", "GEMINI_API_KEY",
              "CF_ACCOUNT_ID", "CF_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    # A single-member chain returns that provider directly (no wrapper).
    assert isinstance(build_provider(), PollinationsProvider)


def test_chain_all_keys_orders_paid_gemini_last(monkeypatch):
    # Free-first billing law: with EVERY lane configured, the paid Gemini
    # backstop is the LAST chain member — free lanes always go first.
    monkeypatch.delenv("EM_IMAGEGEN_MOCK", raising=False)
    monkeypatch.setenv("FREELLMAPI_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("CF_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CF_API_TOKEN", "tok")
    provider = build_provider()
    assert isinstance(provider, ChainImageProvider)
    kinds = [type(p).__name__ for p in provider._providers]
    assert kinds == ["FreellmapiImageProvider", "PollinationsProvider",
                     "CloudflareProvider", "GeminiImageProvider"]


def test_chain_is_freellmapi_then_pollinations_then_gemini(monkeypatch):
    for k in ("EM_IMAGEGEN_MOCK", "CF_ACCOUNT_ID", "CF_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FREELLMAPI_KEY", "k")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    provider = build_provider()
    assert isinstance(provider, ChainImageProvider)
    kinds = [type(p).__name__ for p in provider._providers]
    assert kinds == ["FreellmapiImageProvider", "PollinationsProvider",
                     "GeminiImageProvider"]


def test_chain_freellmapi_then_pollinations_without_gemini(monkeypatch):
    for k in ("EM_IMAGEGEN_MOCK", "GEMINI_API_KEY", "CF_ACCOUNT_ID", "CF_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FREELLMAPI_KEY", "k")
    provider = build_provider()
    kinds = [type(p).__name__ for p in provider._providers]
    assert kinds == ["FreellmapiImageProvider", "PollinationsProvider"]


# ── FreellmapiImageProvider: both response shapes ─────────────────────────────

@pytest.mark.asyncio
async def test_freellmapi_decodes_b64_json(fake_httpx):
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(
        200, payload={"data": [{"b64_json": _PNG_B64}]})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    png = await provider.fetch_png("a cat")
    assert png == _PNG_BYTES
    # POSTs to the images/generations endpoint with the prompt + bearer key.
    method, url, kw = fake_httpx.calls[0]
    assert method == "POST" and url.endswith("/images/generations")
    assert kw["json"]["prompt"] == "a cat"
    assert kw["headers"]["Authorization"] == "Bearer key"


@pytest.mark.asyncio
async def test_freellmapi_fetches_url_shape(fake_httpx, monkeypatch):
    # EM-296: the url-fetch path now SSRF-guards the host (resolves it, rejects
    # private/loopback ranges). Stub resolution so the fake CDN host counts as a
    # public target — the url response shape is still exercised end to end.
    import petridish.imagegen.provider as _prov
    monkeypatch.setattr(_prov, "_resolve_ips", lambda host: ["93.184.216.34"])
    def handler(method, url, **kw):
        if method == "POST":
            return _FakeResp(200, payload={"data": [{"url": "https://cdn/img.png"}]})
        return _FakeResp(200, content=_PNG_BYTES)  # the GET on the url
    fake_httpx.handler = handler
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    png = await provider.fetch_png("a dog")
    assert png == _PNG_BYTES
    assert any(m == "GET" and u == "https://cdn/img.png" for m, u, _ in fake_httpx.calls)


@pytest.mark.asyncio
async def test_freellmapi_pins_model_when_configured(fake_httpx, monkeypatch):
    monkeypatch.setenv("EM_IMAGEGEN_FREELLMAPI_MODEL", "flux-schnell")
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(
        200, payload={"data": [{"b64_json": _PNG_B64}]})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    await provider.fetch_png("x")
    assert fake_httpx.calls[0][2]["json"]["model"] == "flux-schnell"


@pytest.mark.asyncio
async def test_freellmapi_non_200_returns_none(fake_httpx):
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(429, text="rate limited")
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") is None


@pytest.mark.asyncio
async def test_freellmapi_empty_data_returns_none(fake_httpx):
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(200, payload={"data": []})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") is None


@pytest.mark.asyncio
async def test_freellmapi_blank_prompt_is_noop():
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("   ") is None


# ── ChainImageProvider: ordering, skip-on-None, skip-on-raise ─────────────────

class _Const:
    def __init__(self, value):
        self.value = value

    async def fetch_png(self, prompt):
        return self.value


class _Boom:
    async def fetch_png(self, prompt):
        raise RuntimeError("provider exploded")


@pytest.mark.asyncio
async def test_chain_returns_first_non_none():
    chain = ChainImageProvider([_Const(None), _Const(b"second"), _Const(b"third")])
    assert await chain.fetch_png("p") == b"second"


@pytest.mark.asyncio
async def test_chain_skips_a_raising_member():
    # A member that raises is caught and treated as a miss — the chain continues.
    chain = ChainImageProvider([_Boom(), _Const(b"rescued")])
    assert await chain.fetch_png("p") == b"rescued"


@pytest.mark.asyncio
async def test_chain_all_none_returns_none():
    chain = ChainImageProvider([_Const(None), _Const(None)])
    assert await chain.fetch_png("p") is None


# ── Gemini: inline base64 decode (the backup path) ────────────────────────────

@pytest.mark.asyncio
async def test_gemini_decodes_inline_image(fake_httpx):
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(200, payload={
        "candidates": [{"content": {"parts": [
            {"text": "here you go"},
            {"inlineData": {"data": _PNG_B64}},
        ]}}]})
    provider = GeminiImageProvider("gkey", model="gemini-2.5-flash-image")
    png = await provider.fetch_png("a fox")
    assert png == _PNG_BYTES
    # Key rides the header, never the URL query string.
    _m, url, kw = fake_httpx.calls[0]
    assert "key=" not in url
    assert kw["headers"]["x-goog-api-key"] == "gkey"


@pytest.mark.asyncio
async def test_gemini_429_returns_none(fake_httpx):
    fake_httpx.handler = lambda method, url, **kw: _FakeResp(429, text="quota 0")
    provider = GeminiImageProvider("gkey")
    assert await provider.fetch_png("x") is None

"""EM-287 — image write-guard.

Third-party image bytes are buffered and then written to data/assets/images and
served to the browser as `.png` (loop._spawn_image_fetch). Before this fix any
provider could hand back arbitrary, unbounded bytes (an HTML/SVG stored-XSS
shape, or a multi-GB body). The providers now size-cap and magic-byte validate
every payload, so the writer only ever sees a bounded, real raster image.

Hermetic — httpx is faked; no network. Covers `_valid_image` directly plus the
FreeLLMAPI provider rejecting oversized / non-image responses.
"""
from __future__ import annotations

import base64

import pytest

import petridish.imagegen.provider as provider_mod
from petridish.imagegen.provider import (
    FreellmapiImageProvider,
    _MOCK_PNG,
    _valid_image,
)

# Minimal valid magic-byte headers for the web raster formats a lane may return.
_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 8
_GIF = b"GIF89a" + b"\x00" * 8
_WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 8
_SVG = b"<svg xmlns='http://www.w3.org/2000/svg' onload=\"alert(1)\"></svg>"


# ── _valid_image unit ─────────────────────────────────────────────────────────

def test_valid_png_is_accepted():
    assert _valid_image(_MOCK_PNG) == _MOCK_PNG


def test_empty_or_none_is_rejected():
    assert _valid_image(b"") is None
    assert _valid_image(None) is None


def test_non_image_payload_is_rejected():
    # HTML / SVG / arbitrary text must never reach the .png write path.
    assert _valid_image(_SVG) is None
    assert _valid_image(b"not a png at all") is None
    assert _valid_image(b"<html><body>hi</body></html>") is None


def test_oversized_image_is_rejected(monkeypatch):
    # A body over the byte cap is rejected even with a valid signature.
    monkeypatch.setattr(provider_mod, "_MAX_IMAGE_BYTES", 16)
    assert len(_MOCK_PNG) > 16
    assert _valid_image(_MOCK_PNG) is None
    # At/under the cap it still passes.
    monkeypatch.setattr(provider_mod, "_MAX_IMAGE_BYTES", len(_MOCK_PNG))
    assert _valid_image(_MOCK_PNG) == _MOCK_PNG


def test_common_web_raster_formats_are_tolerated():
    # A free lane (e.g. Pollinations) may legitimately return JPEG/GIF/WEBP;
    # dropping those would force the PAID Gemini backstop (free-first billing
    # law), so they are accepted alongside the canonical PNG.
    assert _valid_image(_JPEG) == _JPEG
    assert _valid_image(_GIF) == _GIF
    assert _valid_image(_WEBP) == _WEBP


# ── provider-level: bad bytes never returned to the writer ────────────────────

class _Resp:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _FakeClient:
    handler = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return _FakeClient.handler("POST", url, **kw)

    async def get(self, url, **kw):
        return _FakeClient.handler("GET", url, **kw)


@pytest.fixture
def fake_httpx(monkeypatch):
    import httpx
    _FakeClient.handler = None
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    return _FakeClient


async def test_freellmapi_rejects_non_image_b64(fake_httpx):
    bad = base64.b64encode(_SVG).decode("ascii")
    fake_httpx.handler = lambda m, u, **kw: _Resp(200, payload={"data": [{"b64_json": bad}]})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") is None


async def test_freellmapi_rejects_oversized_b64(fake_httpx, monkeypatch):
    monkeypatch.setattr(provider_mod, "_MAX_IMAGE_BYTES", 16)
    big = base64.b64encode(_MOCK_PNG).decode("ascii")  # decodes to a PNG-signed body > 16
    fake_httpx.handler = lambda m, u, **kw: _Resp(200, payload={"data": [{"b64_json": big}]})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") is None


async def test_freellmapi_accepts_valid_png_b64(fake_httpx):
    good = base64.b64encode(_MOCK_PNG).decode("ascii")
    fake_httpx.handler = lambda m, u, **kw: _Resp(200, payload={"data": [{"b64_json": good}]})
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") == _MOCK_PNG

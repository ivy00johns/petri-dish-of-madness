"""EM-296 — SSRF guard on the image url-fetch path.

The `url` field of a FreeLLMAPI images response is attacker-influenceable (an
upstream / compromised provider can point it at an internal endpoint). The
fetch path now: allows only http/https, resolves the host and rejects any
loopback / private / link-local / reserved / multicast address (checked on the
RESOLVED ip — 169.254.169.254 cloud metadata, 127.0.0.1, 10.x, …), re-validates
every redirect hop, and never lets httpx auto-follow redirects.

Hermetic — the DNS resolver (`_resolve_ips`) is monkeypatched; no real DNS or
network is used.
"""
from __future__ import annotations

import pytest

import petridish.imagegen.provider as provider_mod
from petridish.imagegen.provider import (
    FreellmapiImageProvider,
    _MOCK_PNG,
    _get_url_bytes,
    _url_is_public,
)


def _resolve_to(monkeypatch, mapping):
    """Stub the resolver: mapping is host -> list[ip]; '*' is a catch-all; an
    unmapped host raises (mirrors an NXDOMAIN → fail-closed)."""
    def _fake(host):
        if host in mapping:
            return mapping[host]
        if "*" in mapping:
            return mapping["*"]
        raise OSError(f"unresolved {host}")
    monkeypatch.setattr(provider_mod, "_resolve_ips", _fake)


# ── scheme / host allowlist (unit) ────────────────────────────────────────────

def test_non_http_schemes_rejected():
    for url in ("file:///etc/passwd", "ftp://h/x", "gopher://h/x", "data:text/plain,hi"):
        assert _url_is_public(url) is False


def test_public_host_allowed(monkeypatch):
    _resolve_to(monkeypatch, {"cdn.example.com": ["93.184.216.34"]})
    assert _url_is_public("https://cdn.example.com/a.png") is True


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "192.168.1.10",
                                "169.254.169.254", "172.16.0.1", "::1", "0.0.0.0"])
def test_private_and_metadata_hosts_rejected(monkeypatch, ip):
    _resolve_to(monkeypatch, {"evil.example.com": [ip]})
    assert _url_is_public("http://evil.example.com/x") is False


def test_any_private_ip_in_resolution_rejects(monkeypatch):
    # DNS-rebinding shape: one public + one private ⇒ reject (fail closed).
    _resolve_to(monkeypatch, {"mixed.example.com": ["93.184.216.34", "127.0.0.1"]})
    assert _url_is_public("http://mixed.example.com/x") is False


def test_unresolvable_host_rejected(monkeypatch):
    _resolve_to(monkeypatch, {})  # every host raises
    assert _url_is_public("http://nope.invalid/x") is False


# ── _get_url_bytes end-to-end (fake client) ───────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, content=b"", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _Client:
    def __init__(self, route):
        self._route = route  # url -> _Resp (callable or dict)
        self.gets = []

    async def get(self, url, **kw):
        self.gets.append((url, kw))
        r = self._route
        return r(url) if callable(r) else r[url]


async def test_get_url_bytes_blocks_file_scheme(monkeypatch):
    _resolve_to(monkeypatch, {})
    client = _Client({})
    assert await _get_url_bytes(client, "file:///etc/passwd") is None
    assert client.gets == []  # never issued a request


async def test_get_url_bytes_blocks_metadata_host(monkeypatch):
    _resolve_to(monkeypatch, {"metadata.google.internal": ["169.254.169.254"]})
    client = _Client({})
    got = await _get_url_bytes(client, "http://metadata.google.internal/computeMetadata/v1/")
    assert got is None
    assert client.gets == []  # blocked BEFORE the fetch


async def test_get_url_bytes_fetches_public_png(monkeypatch):
    _resolve_to(monkeypatch, {"cdn.example.com": ["93.184.216.34"]})
    client = _Client({"https://cdn.example.com/a.png": _Resp(200, content=_MOCK_PNG)})
    assert await _get_url_bytes(client, "https://cdn.example.com/a.png") == _MOCK_PNG


async def test_get_url_bytes_does_not_auto_follow_redirects(monkeypatch):
    _resolve_to(monkeypatch, {"cdn.example.com": ["93.184.216.34"]})
    client = _Client({"https://cdn.example.com/a.png": _Resp(200, content=_MOCK_PNG)})
    await _get_url_bytes(client, "https://cdn.example.com/a.png")
    assert client.gets and all(kw.get("follow_redirects") is False for _u, kw in client.gets)


async def test_redirect_to_private_is_rejected(monkeypatch):
    _resolve_to(monkeypatch, {"cdn.example.com": ["93.184.216.34"],
                              "internal.host": ["10.1.2.3"]})

    def route(url):
        if url == "https://cdn.example.com/a.png":
            return _Resp(302, headers={"location": "http://internal.host/secret"})
        return _Resp(200, content=_MOCK_PNG)  # would serve if the hop were followed

    client = _Client(route)
    assert await _get_url_bytes(client, "https://cdn.example.com/a.png") is None
    assert all(u != "http://internal.host/secret" for u, _ in client.gets)


async def test_redirect_to_public_is_followed(monkeypatch):
    _resolve_to(monkeypatch, {"cdn.example.com": ["93.184.216.34"],
                              "img.example.net": ["93.184.216.35"]})

    def route(url):
        if url == "https://cdn.example.com/a.png":
            return _Resp(302, headers={"location": "https://img.example.net/real.png"})
        return _Resp(200, content=_MOCK_PNG)

    client = _Client(route)
    assert await _get_url_bytes(client, "https://cdn.example.com/a.png") == _MOCK_PNG


async def test_redirect_loop_is_bounded(monkeypatch):
    _resolve_to(monkeypatch, {"*": ["93.184.216.34"]})
    client = _Client(lambda url: _Resp(302, headers={"location": "https://a.example.com/next"}))
    assert await _get_url_bytes(client, "https://a.example.com/start") is None
    assert len(client.gets) <= provider_mod._MAX_REDIRECTS + 1


# ── FreeLLMAPI url-shape end-to-end ───────────────────────────────────────────

class _Resp2:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeAsyncClient:
    handler = None

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, **kw):
        return _FakeAsyncClient.handler("POST", url, **kw)

    async def get(self, url, **kw):
        return _FakeAsyncClient.handler("GET", url, **kw)


async def test_freellmapi_url_shape_blocks_ssrf_target(monkeypatch):
    _resolve_to(monkeypatch, {"169.254.169.254": ["169.254.169.254"]})
    import httpx
    calls = []

    def handler(method, url, **kw):
        calls.append((method, url))
        if method == "POST":
            return _Resp2(200, payload={"data": [{"url": "http://169.254.169.254/latest/meta-data/"}]})
        return _Resp2(200, content=_MOCK_PNG)  # the metadata endpoint — must never be hit

    _FakeAsyncClient.handler = handler
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    provider = FreellmapiImageProvider("http://localhost:3001/v1", "key")
    assert await provider.fetch_png("x") is None
    assert all(m != "GET" for m, _ in calls)  # never fetched the SSRF target

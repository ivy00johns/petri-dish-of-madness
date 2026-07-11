"""Timeout / network-down handling (2026-07-08).

Two behaviors:
  1. Adapter labels transport failures clearly — an httpx timeout that
     stringifies to '' must NOT surface as a blank `provider_error:` badge;
     it becomes "timed out after 30s". Connect errors become "network
     unreachable: ...".
  2. Network-down grace — the loop auto-RESUMES a provider-error pause once a
     cheap connectivity probe succeeds, so a transient outage doesn't strand
     the run waiting for a manual restart.
"""
from __future__ import annotations

import httpx
import pytest

from petridish.providers.adapters import _post_with_retry, _TIMEOUT
from petridish.providers.base import ProviderError


class _RaisingClient:
    """Minimal stand-in for httpx.AsyncClient whose post() raises `exc`."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def post(self, *args, **kwargs):
        raise self._exc


@pytest.mark.asyncio
async def test_timeout_gets_explicit_detail_not_blank():
    # httpx timeout exceptions frequently stringify to '' — the exact case that
    # surfaced as a blank `provider_error:` in the feed.
    client = _RaisingClient(httpx.ReadTimeout(""))
    with pytest.raises(ProviderError) as ei:
        await _post_with_retry(client, "http://x/v1", {}, {}, "cerebras-glm")
    assert ei.value.detail == f"timed out after {_TIMEOUT:.0f}s"
    assert ei.value.detail.strip()  # never blank
    assert ei.value.profile == "cerebras-glm"


@pytest.mark.asyncio
async def test_connect_error_labeled_network_unreachable():
    client = _RaisingClient(httpx.ConnectError("All connection attempts failed"))
    with pytest.raises(ProviderError) as ei:
        await _post_with_retry(client, "http://x/v1", {}, {}, "auto")
    assert ei.value.detail.startswith("network unreachable")
    assert "All connection attempts failed" in ei.value.detail


@pytest.mark.asyncio
async def test_blank_connect_error_still_non_empty():
    # Guard the empty-string case for connect errors too.
    client = _RaisingClient(httpx.ConnectError(""))
    with pytest.raises(ProviderError) as ei:
        await _post_with_retry(client, "http://x/v1", {}, {}, "auto")
    assert ei.value.detail == "network unreachable: connection refused"

"""
Adaptive Lane Routing — dynamic lane discovery + refresh (spec P2).

Spec: docs/superpowers/specs/2026-07-07-adaptive-lane-routing.md §4/§9 (Phase P2).

P1 shipped a STATIC registry: lanes came from the configured profiles, ranked
once by `config/lanes.yaml`. P2 makes the pool DATA-DRIVEN — it polls the live
FreeLLMAPI proxy's model catalog (`GET /v1/models`) and detects direct-provider
env keys, so lanes the user provisions (adds a key to FreeLLMAPI over days, sets
`GEMINI_API_KEY` locally) APPEAR at the next refresh and vanished ones DROP OUT,
with zero code change and zero restart — the "slow onboarding" story (spec §4).

EMPIRICAL NOTE (live probe 2026-07-15, answers spec §11 Q1): the proxy's
`/v1/models` expresses AVAILABILITY, not merely configuration. Each row carries
`available: bool` + `unavailable_reason` (observed values: "no_key",
"disabled", null) plus `context_window`. So discovery filters to
`available: true` models: a model the user has no key for reports
`available:false, unavailable_reason:"no_key"` and is never placed; provisioning
a key flips it available and it joins the pool at the next refresh. The admin
`/api/health` `quotaStates` surface is richer per-key health but PLATFORM-keyed
(cerebras / cohere / google / groq …), not model-keyed, so it is treated as
OPTIONAL enrichment, never the availability gate — 429-driven cap/cooldown is
P3, not this phase.

This module is deliberately decoupled from the router AND from httpx: the async
fetchers take an injected `client_factory` (default `httpx.AsyncClient`) so the
test suite is hermetic (httpx.MockTransport — never the real proxy), and
`merge_universe` is a PURE function of its inputs. The router owns adapter
synthesis + registry rebuild (see providers/router.py `refresh_lanes`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Iterable

import httpx

from .lanes import Lane

log = logging.getLogger(__name__)

# Direct-provider source → the env var whose PRESENCE lights that source up
# (spec §4 step 2). FreeLLMAPI is NOT here: its lanes are gated by the catalog's
# `available` flag, not a local env key.
DIRECT_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}

# Stable profile-name prefix for a lane SYNTHESIZED from a discovered model that
# has no hand-authored profile. Namespaced so it never collides with a real
# profile, and STABLE across refreshes (health windows are keyed by profile
# name, so a discovered lane's EM-135 health carries over refresh to refresh —
# spec §4 step 3 "state carries across refreshes by lane id").
SYNTH_PREFIX = "disco:"


@dataclass(frozen=True)
class DiscoveredModel:
    """One row from the proxy's `/v1/models` catalog (the fields discovery
    reads). `available` + `unavailable_reason` are the availability truth (spec
    §11 Q1); `context_window` seeds a lane's ctx_hint."""
    id: str
    available: bool = True
    unavailable_reason: str | None = None
    context_window: int | None = None


@dataclass(frozen=True)
class SynthLaneSpec:
    """A lane to synthesize an adapter for: a discovered available FreeLLMAPI
    model with no hand-authored profile. The router builds an
    OpenAICompatibleAdapter from the freellmapi connection template (base_url +
    api_key + color) with this `model_id`, registered under `profile`."""
    profile: str
    model_id: str
    ctx_hint: int | None = None


@dataclass(frozen=True)
class FreeLLMTemplate:
    """Connection params cloned from a representative FreeLLMAPI profile so a
    discovered model with no profile can still be CALLED (all freellmapi lanes
    share one base_url + key; only `model` differs)."""
    base_url: str
    api_key: str
    color: str = "#8888aa"


@dataclass(frozen=True)
class MergeResult:
    """Output of `merge_universe`: the lane universe to feed the SortingList,
    plus the synth specs whose adapters the router must build before it can
    rank/call them. `retired` is observability only (which lanes discovery
    dropped this pass and why)."""
    universe: tuple[Lane, ...]
    synth: tuple[SynthLaneSpec, ...]
    retired: tuple[tuple[str, str], ...] = ()  # (lane_id, reason)


def parse_models(payload: Any) -> list[DiscoveredModel]:
    """Parse a `/v1/models` response body into DiscoveredModel rows.

    Accepts the OpenAI-list shape `{"object":"list","data":[{...}]}` or a bare
    list. Defensive: a non-dict/non-list payload, or rows missing `id`, yield
    []/skip rather than raising — a malformed catalog must degrade to "discover
    nothing," never crash a refresh."""
    if isinstance(payload, dict):
        rows = payload.get("data", [])
    elif isinstance(payload, list):
        rows = payload
    else:
        return []
    out: list[DiscoveredModel] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        # `available` defaults TRUE when the proxy omits it (older builds), so a
        # catalog without the field behaves like "everything configured is
        # usable" rather than silently retiring the whole pool.
        avail = row.get("available", True)
        ctx = row.get("context_window") or row.get("context_length")
        out.append(DiscoveredModel(
            id=mid,
            available=bool(avail),
            unavailable_reason=row.get("unavailable_reason"),
            context_window=int(ctx) if isinstance(ctx, (int, float)) else None,
        ))
    return out


async def fetch_freellmapi_catalog(
    base_url: str,
    api_key: str,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    timeout: float = 8.0,
) -> list[DiscoveredModel]:
    """GET `{base_url}/models` with the runtime bearer key → DiscoveredModel rows.

    `base_url` is the proxy's OpenAI-compatible root (e.g.
    `http://localhost:3001/v1`). Read-only (GET). DEFENSIVE: any transport /
    status / parse error returns [] (the caller keeps the current registry) —
    discovery must never take the sim down. `client_factory` is injected in
    tests (httpx.MockTransport) so the suite never touches the real proxy."""
    root = (base_url or "").rstrip("/")
    if not root:
        return []
    url = f"{root}/models"
    headers = {}
    key = (api_key or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
    try:
        async with factory() as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return parse_models(resp.json())
    except Exception as exc:  # defensive — a down/500 proxy discovers nothing
        log.debug("freellmapi catalog fetch failed (%s): %s", url, exc)
        return []


async def fetch_admin_quota(
    admin_base_url: str,
    email: str,
    password: str,
    *,
    client_factory: Callable[[], httpx.AsyncClient] | None = None,
    timeout: float = 8.0,
) -> list[dict] | None:
    """Optional ENRICHMENT: mint an admin session token (POST /api/auth/login)
    and read `GET /api/health` `quotaStates` (per-key health, platform-keyed).

    Returns the quotaStates list, or None when creds are absent / login fails /
    anything errors. NOT the availability gate (that is the catalog's `available`
    flag); this is richer per-key signal a future P3 429-cap layer can fold in.
    DEFENSIVE like the catalog fetch. Only called when the discovery config opts
    in AND creds are configured."""
    base = (admin_base_url or "").rstrip("/")
    if not (base and email and password):
        return None
    factory = client_factory or (lambda: httpx.AsyncClient(timeout=timeout))
    try:
        async with factory() as client:
            login = await client.post(
                f"{base}/api/auth/login",
                json={"email": email, "password": password},
            )
            login.raise_for_status()
            token = (login.json() or {}).get("token")
            if not token:
                return None
            health = await client.get(
                f"{base}/api/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            health.raise_for_status()
            body = health.json()
            qs = body.get("quotaStates") if isinstance(body, dict) else None
            return qs if isinstance(qs, list) else None
    except Exception as exc:  # defensive
        log.debug("admin quota fetch failed (%s): %s", base, exc)
        return None


def detect_direct_sources(env: dict) -> dict[str, bool]:
    """Which direct-provider sources are LIVE right now, by env-key presence
    (spec §4 step 2). Adding `GEMINI_API_KEY` lights up gemini next refresh;
    removing it drops it. FreeLLMAPI is catalog-gated, not here."""
    return {
        source: bool((env.get(var) or "").strip())
        for source, var in DIRECT_KEY_ENV.items()
    }


def merge_universe(
    existing: Iterable[Lane],
    discovered: Iterable[DiscoveredModel],
    *,
    direct_sources: dict[str, bool] | None = None,
    freellmapi_template: FreeLLMTemplate | None = None,
    freellmapi_models: bool = True,
    direct_keys: bool = True,
) -> MergeResult:
    """PURE merge (spec §4 step 3): fold the discovered catalog + direct-key
    presence into the P1 static universe. The lanes.yaml order/pins stay
    authoritative (this only shapes the UNIVERSE the SortingList then ranks —
    exclusion, allow_paid, priority and the `auto` reservation all remain the
    router's job downstream).

    Rules:
      - A configured FreeLLMAPI lane whose model_id the catalog reports
        `available:false` is RETIRED (no key / disabled upstream) when
        `freellmapi_models` is on. One the catalog does not mention at all is
        KEPT (defensive — never drop a hand-authored lane on a partial catalog).
      - Every discovered `available:true` FreeLLMAPI model with no configured
        lane becomes a SYNTH lane (a `disco:<model>` profile the router builds
        an adapter for) — this is what the lanes.yaml `*` sweep then places, so
        newly-provisioned models appear automatically.
      - A direct-source lane (gemini/anthropic/openai/ollama) is RETIRED when
        `direct_keys` is on AND its key env is absent, KEPT when present. With
        `direct_keys` off, direct lanes pass through unchanged (P1 behavior).

    Idempotent: re-running with the same inputs yields the same universe (a
    discovered model that already has a configured lane is NOT re-synthesized —
    matched by model_id), so health/priority stay stable across refreshes."""
    direct_sources = direct_sources or {}
    existing = list(existing)
    by_model_free = {
        ln.model_id for ln in existing if ln.source == "freellmapi"
    }
    catalog = {m.id: m for m in discovered}

    universe: list[Lane] = []
    retired: list[tuple[str, str]] = []
    for ln in existing:
        if ln.source == "freellmapi":
            if freellmapi_models:
                m = catalog.get(ln.model_id)
                if m is not None and not m.available:
                    retired.append((ln.id, m.unavailable_reason or "unavailable"))
                    continue
            universe.append(ln)
        elif ln.source in DIRECT_KEY_ENV:
            if direct_keys and not direct_sources.get(ln.source, False):
                retired.append((ln.id, "no_direct_key"))
                continue
            universe.append(ln)
        else:  # unknown source — pass through untouched
            universe.append(ln)

    synth: list[SynthLaneSpec] = []
    if freellmapi_models and freellmapi_template is not None:
        for m in discovered:
            if not m.available:
                continue
            if m.id in by_model_free:
                continue  # a configured lane already covers it
            profile = f"{SYNTH_PREFIX}{m.id}"
            synth.append(SynthLaneSpec(
                profile=profile, model_id=m.id, ctx_hint=m.context_window))
            universe.append(Lane(
                id=f"freellmapi:{profile}",
                source="freellmapi",
                model_id=m.id,
                profile=profile,
                ctx_hint=m.context_window,
            ))

    return MergeResult(
        universe=tuple(universe),
        synth=tuple(synth),
        retired=tuple(retired),
    )

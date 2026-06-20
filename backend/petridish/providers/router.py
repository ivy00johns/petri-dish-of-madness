"""
Router: unified chat() interface over all adapters.
Manages per-agent profile assignment (hot-swappable at runtime).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from collections import OrderedDict, deque
from typing import Any

from typing import Callable

from ..config.loader import ModelProfile
from .adapters import OpenAICompatibleAdapter, AnthropicAdapter, GeminiAdapter
from .base import Provider, ProviderError
from .mock import MockProvider
from .usage import UsageAlertTracker

log = logging.getLogger(__name__)

# W7 / EM-068 — default bound on the Router decision cache (config: world.cache.max_entries).
_DEFAULT_CACHE_MAX = 512

# ── EM-135 — reroute-aware lane health ────────────────────────────────────────
# The proxy silently reroutes profiles to models that truncate (reasoning CoT
# eats the budget; mistral-medium cuts mid-JSON while reporting 'stop' — runs
# 102/126). The runtimes report every parse attempt's outcome; once a profile's
# recent window shows repeated truncations, the FIRST attempt gets the same
# token boost the parse-failure retry uses instead of burning a call at a cap
# that keeps cutting. The window flushes naturally (deque maxlen): a full
# window of clean outcomes clears the flag with no extra bookkeeping.
_LANE_WINDOW = 6                  # outcomes remembered per profile
_LANE_TRUNCATION_TRIGGER = 2      # truncations in window that flag the lane
_LANE_BOOST_FLOOR = 2048          # mirrors agents.runtime._LENGTH_RETRY_TOKEN_FLOOR

# ── Wave D3 / EM-177 — lane failover with recovery probes ─────────────────────
# Defaults mirror config.loader.LaneFailoverParams (config `world.lane_failover`).
_LANE_SICK_THRESHOLD_DEFAULT = 3  # timed_out entries in the 6-window ⇒ SICK
_LANE_PROBE_EVERY_DEFAULT = 4     # every Nth would-be-detour probes the home lane

# ── EM-205 — auto-backup routing ──────────────────────────────────────────────
# 2026-06-15 decision (supersedes the EM-198 fan-out): a provider error (429 /
# 5xx / transport failure / malformed completion) on a PINNED lane retries the
# SAME call exactly ONCE on the proxy's `auto` router model. FreeLLMAPI then
# health-routes that single request across its whole upstream pool — it knows
# which providers are throttled in real time, we don't. This replaces the
# EM-198 multi-lane bounce, which AMPLIFIED rate-limit storms: one failure
# fanned out to up to ~6 POSTs across pinned lanes (home ×2 retries × 3 lanes),
# each itself possibly rate-limited, feeding the storm. The agent keeps its
# pinned model (model-vs-model identity intact); only the backup is delegated
# to the proxy. The backup is the profile literally named `auto` when present;
# absent ⇒ the original error propagates (the runtime's EM-173 idle fallback
# stays the true last resort). Total adapter calls per chat(): home + 1 backup.
_AUTO_BACKUP_PROFILE = "auto"

# ── EM-226 — auto-backup circuit breaker (storm fast-fail) ────────────────────
# During a rate-limit STORM the proxy's own `auto` router returns "All models
# exhausted" (or times out): there is no healthy upstream left to bounce to.
# Re-issuing the EM-205 backup every turn then DOUBLES the doomed POST volume
# (home + auto, both failing) and keeps the upstream rate windows pinned,
# slowing their refill. The breaker trips on ANY `auto` failure (the auto lane
# IS the whole-pool health router — if IT can't serve, nothing can) and
# FAST-FAILS subsequent would-be-backups: the home error propagates straight to
# the runtime's EM-173 idle fallback with NO 2nd network call. The agents never
# go quiet (they act on idle); we just stop banging on a door the proxy said is
# locked, so the upstream windows can refill. Recovery is automatic and
# COUNTER-based (no clock reads — counters only, like EM-177): every Nth skipped
# backup PROBES the auto lane once; a probe SUCCESS closes the breaker and
# normal per-turn backup resumes. Cadence is in *skipped backups*, not seconds,
# to stay deterministic + testable; at the default a sustained storm makes one
# auto POST per 8 failing turns instead of one per turn (~87% fewer doomed
# calls) while still probing for recovery within a handful of turns.
_AUTO_BREAKER_PROBE_EVERY = 8  # skipped backups between recovery probes

# ── EM-222 — relevance-scored memory retrieval ────────────────────────────────
# Embeddings route through ONE dedicated profile (a fixed embedding model, NOT
# the agent's chat lane). Resolved once at init from the profile literally named
# `embed`; absent ⇒ has_embeddings is False and embed() raises (the retriever
# falls back to blind recency). NOT decision-cached — embeddings ADD calls.
_EMBED_PROFILE = "embed"


def _cache_key(profile_name: str, messages: list[dict]) -> str:
    """sha1(profile_name + json(messages, sort_keys=True)).

    The messages already embed persona + retrieved memory + coarse world state, so
    an identical key means an identical situation (per contracts/providers.md
    §Decision caching). sort_keys makes the digest stable across dict ordering.
    """
    payload = profile_name + json.dumps(messages, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _build_adapter(profile: ModelProfile) -> Provider:
    adapter = profile.adapter
    name = profile.name
    color = profile.color

    # EM-222 — hermetic/offline switch for the embedding lane. The shipped
    # `embed` profile points at the FreeLLMAPI proxy; under EM_EMBED_MOCK (set by
    # the test conftest, or for offline dev) the embed lane is a deterministic
    # MockProvider so turns never make real embedding network calls (the suite
    # stays hermetic + fast; only the embed profile is affected, chat is not).
    if name == _EMBED_PROFILE and os.environ.get("EM_EMBED_MOCK"):
        p = MockProvider()
        p.name = name  # type: ignore[attr-defined]
        p.color = color  # type: ignore[attr-defined]
        return p  # type: ignore[return-value]

    if adapter == "mock":
        p = MockProvider()
        p.name = name  # type: ignore[attr-defined]
        p.color = color  # type: ignore[attr-defined]
        return p  # type: ignore[return-value]

    api_key = profile.api_key() or ""

    # EM-222 — `openai-compatible` is an accepted alias for `openai` (the
    # contract's embed profile spells the adapter out in full); both build the
    # OpenAICompatibleAdapter.
    if adapter in ("openai", "openai-compatible"):
        return OpenAICompatibleAdapter(
            profile=name,
            base_url=profile.base_url or "http://localhost:3001/v1",
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    elif adapter == "anthropic":
        return AnthropicAdapter(
            profile=name,
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    elif adapter == "gemini":
        return GeminiAdapter(
            profile=name,
            api_key=api_key,
            model_id=profile.model_id,
            color=color,
        )
    else:
        raise ValueError(f"Unknown adapter: {adapter!r}")


class Router:
    def __init__(
        self,
        profiles: list[ModelProfile],
        adapter_overrides: dict[str, Provider] | None = None,
        *,
        cache_enabled: bool = True,
        cache_max: int = _DEFAULT_CACHE_MAX,
        lane_failover: Any = None,
        auto_breaker_probe_every: int = _AUTO_BREAKER_PROBE_EVERY,
    ):
        self._profiles: dict[str, ModelProfile] = {p.name: p for p in profiles}
        self._adapters: dict[str, Provider] = {
            p.name: _build_adapter(p) for p in profiles
        }
        if adapter_overrides:
            self._adapters.update(adapter_overrides)
        # per-agent overrides: agent_id -> profile_name
        self._agent_profiles: dict[str, str] = {}

        # ── W7 / EM-068 — Router-level decision cache ──────────────────────────
        # Internal LRU keyed on sha1(profile_name + json(messages)). On a HIT we
        # return the cached text WITHOUT touching the adapter; the next
        # last_usage(profile)/last_routed_via(profile) read then reflects the
        # cached snapshot (cached=true, tokens null, latency ~0). ENABLED by
        # default; `cache_enabled=False` disables; `cache_max` bounds the LRU.
        # The mock adapter is NEVER cached (it is deterministic already).
        self._cache_enabled: bool = bool(cache_enabled)
        self._cache_max: int = max(0, int(cache_max))
        # key -> {"text", "routed_via", "usage"}; OrderedDict = LRU by insertion/access.
        self._cache: OrderedDict[str, dict] = OrderedDict()
        # Per-profile pending HIT snapshot. Set on a cache HIT so the subsequent
        # last_usage(profile)/last_routed_via(profile) reads (which the runtime
        # performs right after chat()) report the cached values instead of the
        # adapter's stale state. Cleared on a MISS so real adapter state surfaces.
        # profile_name -> {"routed_via": str|None, "usage": dict|None}
        self._pending_cached: dict[str, dict] = {}
        # Wave D2 / EM-162 — additive cache bookkeeping. Counts CACHEABLE
        # traffic only (mock-profile calls bypass the cache and are not
        # counted); a MISS is counted even if the adapter call then fails
        # (the cache was consulted and could not serve). Reset by
        # clear_cache(); read via cache_stats(). Observability only — no
        # behavior rides on these.
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        # ── W11b / EM-083 (platform half) — usage-alert tracking ───────────────
        # Day-window rpd/tpd caps come from the profile entries (profiles.yaml
        # `rpd:`/`tpd:` keys, see providers/usage.py). Profiles without caps
        # contribute no state and can never alert. Alerts are dispatched to the
        # sink set via set_usage_alert_sink (the API layer routes them into the
        # event log as `usage_alert` rows); no sink = alerts are dropped.
        self._usage_alerts = UsageAlertTracker({
            p.name: {"rpd": getattr(p, "rpd", None), "tpd": getattr(p, "tpd", None)}
            for p in profiles
        })
        self._usage_alert_sink: Callable[[dict], None] | None = None

        # ── EM-135 — reroute-aware lane health ─────────────────────────────────
        # Per-profile deque of the last _LANE_WINDOW parse outcomes, reported by
        # the runtimes via note_parse_outcome(). In-memory only — cleared by
        # clear_cache() on world reset so prior-run truncation evidence never
        # boosts a new run's budgets. last routed_via recorded alongside for
        # lane_health() introspection.
        # profile_name -> deque[{"parsed": bool, "truncated": bool}]
        self._lane_outcomes: dict[str, deque[dict]] = {}
        self._lane_routed_via: dict[str, str | None] = {}

        # ── Wave D3 / EM-177 — lane failover with recovery probes ──────────────
        # `lane_failover` is the config `world.lane_failover` block (a
        # LaneFailoverParams dataclass, a plain dict, or None ⇒ defaults). The
        # 2026-06-11 incident: every FreeLLMAPI lane but one was silently
        # rerouted to a reasoning model that blew the EM-170 budget; the router
        # KNEW (EM-135/170 windows) but nothing ACTED. effective_profile()
        # detours a SICK home lane's calls to the healthiest substitute and
        # probes home every Nth would-be-detour so the window can age the
        # demerits out. ALL failover state below is in-memory only and cleared
        # by clear_cache() on world reset, like the lane windows. No clock
        # reads anywhere — counters only.
        self._lane_failover = lane_failover
        # substitute profile -> detours routed there this run (load-spread
        # tie-break + /api/lanes `detours_routed_here`).
        self._lane_detours_routed: dict[str, int] = {}
        # home profile -> consecutive would-be-detour counter (probe cadence).
        self._lane_detour_counter: dict[str, int] = {}
        # home profile -> substitute recorded at streak start. Presence of the
        # key IS the "detour streak active" flag (lane_detour edge events).
        self._lane_streak_substitute: dict[str, str] = {}
        # Sink for `lane_detour` edge payloads (the API layer routes them into
        # the event log, same pattern as set_usage_alert_sink). No sink ⇒ drop.
        self._lane_event_sink: Callable[[dict], None] | None = None

        # ── EM-205 — auto-backup routing ───────────────────────────────────────
        # The universal backup lane: the profile literally named `auto` (the
        # FreeLLMAPI proxy's own health-aware router model). When present, a
        # pinned lane's failure retries ONCE here instead of fanning out across
        # other pinned lanes. None ⇒ no proxy router configured, errors
        # propagate (opt-out / test default). Resolved once; immutable per run.
        self._auto_backup: str | None = (
            _AUTO_BACKUP_PROFILE if _AUTO_BACKUP_PROFILE in self._adapters else None
        )

        # ── EM-226 — auto-backup circuit breaker (storm fast-fail) ─────────────
        # In-memory only; cleared by clear_cache() on world reset so a prior
        # run's storm never suppresses a fresh run's backups. `_open` is the
        # breaker state (auto believed unable to serve the whole pool); `_skips`
        # counts fast-failed would-be-backups since it opened / since the last
        # probe (drives the recovery-probe cadence). The cadence is clamped to
        # >=1 so a degenerate config can't divide by zero.
        self._auto_breaker_open: bool = False
        self._auto_breaker_skips: int = 0
        self._auto_breaker_probe_every: int = max(1, int(auto_breaker_probe_every))

        # ── EM-222 — the dedicated embedding lane ──────────────────────────────
        # The adapter for the profile literally named `embed`, resolved once.
        # adapter_overrides already merged into self._adapters above, so a test
        # MockProvider injected under "embed" wins here. None ⇒ no embed profile
        # configured: has_embeddings is False and embed() raises a clear error.
        self._embed_adapter: Provider | None = self._adapters.get(_EMBED_PROFILE)

    def set_usage_alert_sink(self, sink: Callable[[dict], None] | None) -> None:
        """Register the callback that receives `usage_alert` payloads
        ({provider, metric, pct, limit}) when a real adapter call crosses 70%
        of a configured day cap (W11b EM-083). Called synchronously from
        chat()'s MISS path; the sink must be cheap and never raise."""
        self._usage_alert_sink = sink

    def _note_usage_for_alerts(self, profile_name: str) -> None:
        """Feed the alert tracker after a successful REAL adapter call (cache
        HITs and mock calls never reach here / have no caps). Defensive: alert
        plumbing must never break chat()."""
        if not self._usage_alerts.has_caps:
            return
        try:
            usage = getattr(self._adapters.get(profile_name), "last_usage", None) or {}
            tokens = 0
            for key in ("input_tokens", "output_tokens"):
                v = usage.get(key) if isinstance(usage, dict) else None
                if isinstance(v, (int, float)):
                    tokens += int(v)
            alerts = self._usage_alerts.note(profile_name, requests=1, tokens=tokens)
            sink = self._usage_alert_sink
            if sink is not None:
                for alert in alerts:
                    sink(alert)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("usage-alert tracking failed for %s: %s", profile_name, exc)

    # ──────────────────────────────────────────────────────────────────────────

    def reassign(self, agent_id: str, profile_name: str) -> None:
        if profile_name not in self._profiles:
            raise ValueError(f"Unknown profile: {profile_name!r}")
        self._agent_profiles[agent_id] = profile_name

    def profile_for(self, agent_id: str) -> ModelProfile:
        profile_name = self._agent_profiles.get(agent_id)
        if profile_name:
            return self._profiles[profile_name]
        raise KeyError(f"No profile mapping for agent {agent_id!r}")

    def profile_name_for(self, agent_id: str, default_profile: str) -> str:
        return self._agent_profiles.get(agent_id, default_profile)

    def _is_mock_profile(self, profile_name: str) -> bool:
        """True when the profile's adapter is the deterministic mock — never cached."""
        profile = self._profiles.get(profile_name)
        return bool(profile is not None and profile.adapter == "mock")

    def _cacheable(self, profile_name: str) -> bool:
        return self._cache_enabled and self._cache_max > 0 and not self._is_mock_profile(profile_name)

    @staticmethod
    def _cached_usage_snapshot(usage: dict | None) -> dict:
        """Usage snapshot surfaced on a HIT: cached=true, tokens null, latency ~0.

        Preserves the finish_reason of the original completion when available so
        downstream llm_call rows keep a sane stop reason.
        """
        finish_reason = usage.get("finish_reason") if isinstance(usage, dict) else None
        return {
            "input_tokens": None,
            "output_tokens": None,
            "latency_ms": 0.0,
            "finish_reason": finish_reason,
            "cached": True,
        }

    async def chat(
        self,
        profile_name: str,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        adapter = self._adapters.get(profile_name)
        if adapter is None:
            raise ProviderError(profile_name, None, "no adapter for profile")

        cacheable = self._cacheable(profile_name)
        key: str | None = None
        if cacheable:
            key = _cache_key(profile_name, messages)
            hit = self._cache.get(key)
            if hit is not None:
                # ── HIT ── return cached text WITHOUT calling the adapter. Stage a
                # pending snapshot so the runtime's immediate last_usage(profile) /
                # last_routed_via(profile) reads report cached=true (tokens null,
                # latency ~0) and the cached routed value.
                self._cache.move_to_end(key)  # LRU: mark most-recently-used
                self._cache_hits += 1  # EM-162 bookkeeping
                self._pending_cached[profile_name] = {
                    "routed_via": hit.get("routed_via"),
                    "usage": self._cached_usage_snapshot(hit.get("usage")),
                }
                return hit["text"]
            self._cache_misses += 1  # EM-162 bookkeeping (cacheable miss)

        # ── MISS (or non-cacheable) ── call the adapter as today. Clear any stale
        # pending HIT snapshot so the adapter's real last_routed_via/last_usage
        # surface unchanged for this profile.
        self._pending_cached.pop(profile_name, None)
        served_by = profile_name
        try:
            text = await adapter.chat(messages, max_tokens=max_tokens, temperature=temperature)
        except ProviderError as exc:
            # EM-205 — retry the SAME call ONCE on the proxy's `auto` router
            # instead of fanning out across pinned lanes. Re-raises when no
            # `auto` lane is configured or it also fails (EM-173 idle = last
            # resort).
            text, served_by = await self._auto_backup_call(
                profile_name, exc, messages,
                max_tokens=max_tokens, temperature=temperature,
            )

        # W11b / EM-083 — one REAL provider call completed: feed the day-window
        # usage-alert tracker for the lane that ACTUALLY served (no-op unless
        # that profile has rpd/tpd caps).
        self._note_usage_for_alerts(served_by)

        served_adapter = self._adapters.get(served_by, adapter)
        served_usage = getattr(served_adapter, "last_usage", None)
        served_routed = getattr(served_adapter, "last_routed_via", None)
        if served_by != profile_name:
            # EM-198 — a bounced call's truth must surface on the REQUESTED
            # profile: stage a pending snapshot (the same mechanism cache HITs
            # use) so the runtime's immediate last_usage(profile)/
            # last_routed_via(profile) reads report the substitute's real
            # numbers, with additive bounced_from/bounced_to keys.
            if isinstance(served_usage, dict):
                served_usage = {
                    **served_usage,
                    "bounced_from": profile_name,
                    "bounced_to": served_by,
                }
            self._pending_cached[profile_name] = {
                "routed_via": served_routed,
                "usage": served_usage,
            }

        if cacheable and key is not None:
            self._cache[key] = {
                "text": text,
                "routed_via": served_routed,
                "usage": served_usage,
            }
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_max:
                self._cache.popitem(last=False)  # evict least-recently-used
        return text

    async def _auto_backup_call(
        self,
        home: str,
        first_exc: ProviderError,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> tuple[str, str]:
        """EM-205 — auto-backup: retry one failed call ONCE on the proxy `auto`.

        The home lane's failure is recorded as an `error` demerit in its EM-135
        window (observability; chronic lanes surface in lane_health()). Then the
        SAME call is retried exactly once on the `auto` backup lane — the
        FreeLLMAPI router model, which health-routes across the whole upstream
        pool in a single request. Returns (text, served_by="auto").

        Re-raises the ORIGINAL error when no `auto` lane is configured (opt-out)
        or the home lane IS `auto` (no self-recursion — a failing narrator-on-
        auto call must not bounce to itself). Re-raises the AUTO error when the
        backup also fails — the runtime's EM-173 idle fallback stays the true
        last resort. Never targets mock (the backup is `auto` or nothing).

        EM-226 — while the storm breaker is OPEN the backup is FAST-FAILED (the
        original error propagates with NO 2nd network call) except on every Nth
        skip, which PROBES the auto lane to detect recovery. A probe success
        closes the breaker; any auto failure (re-)opens it."""
        self.note_lane_error(home)
        backup = self._auto_backup
        if backup is None or backup == home:
            raise first_exc
        adapter = self._adapters.get(backup)
        if adapter is None:  # pragma: no cover - defensive
            raise first_exc

        # EM-226 — breaker OPEN: skip the doomed 2nd POST except on a probe turn.
        if self._auto_breaker_open:
            self._auto_breaker_skips += 1
            is_probe = self._auto_breaker_skips % self._auto_breaker_probe_every == 0
            if not is_probe:
                raise first_exc  # fast-fail — agents act on the EM-173 idle fallback

        try:
            text = await adapter.chat(
                messages, max_tokens=max_tokens, temperature=temperature
            )
        except ProviderError as exc:
            self.note_lane_error(backup)
            self._trip_auto_breaker()  # open (or keep open); reset the probe counter
            raise exc
        # Backup served ⇒ the pool has capacity again: close the breaker.
        self._reset_auto_breaker()
        log.info(
            "EM-205 auto-backup: %s failed (%s), proxy `auto` served the call",
            home, (first_exc.detail or "")[:120],
        )
        return text, backup

    # ── EM-226 — auto-backup circuit breaker ───────────────────────────────────

    def _trip_auto_breaker(self) -> None:
        """Open the breaker after an `auto` failure (the whole-pool storm signal)
        and reset the probe counter so the next probe is a full cadence away.
        Logs ONLY the open transition — never per skip."""
        if not self._auto_breaker_open:
            log.info(
                "EM-226 auto-backup breaker OPEN — proxy pool exhausted; "
                "fast-failing backups, probing every %d skips",
                self._auto_breaker_probe_every,
            )
        self._auto_breaker_open = True
        self._auto_breaker_skips = 0

    def _reset_auto_breaker(self) -> None:
        """Close the breaker after a successful backup (the pool serves again).
        Logs ONLY the close transition."""
        if self._auto_breaker_open:
            log.info("EM-226 auto-backup breaker CLOSED — proxy pool serving again")
        self._auto_breaker_open = False
        self._auto_breaker_skips = 0

    def auto_backup_health(self) -> dict:
        """EM-226 — circuit-breaker snapshot for /api/lanes + tests:
        {open, skips, probe_every}. `open` ⇒ the proxy `auto` pool was last seen
        unable to serve and backups are being fast-failed (agents act on the
        EM-173 idle fallback meanwhile); a probe every `probe_every` skips closes
        it on recovery. Absent an `auto` lane the breaker never trips."""
        return {
            "open": self._auto_breaker_open,
            "skips": self._auto_breaker_skips,
            "probe_every": self._auto_breaker_probe_every,
        }

    # ── EM-222 — relevance-scored memory retrieval ─────────────────────────────

    @property
    def has_embeddings(self) -> bool:
        """True iff a dedicated `embed` profile is configured (the retriever
        gates on this: no embed lane ⇒ blind-recency memory, unchanged today)."""
        return self._embed_adapter is not None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """EM-222 — route to the dedicated embed adapter (the `embed` profile).

        One vector per input text, same order. Raises ProviderError when no
        `embed` profile is configured (the caller falls back to blind recency).
        NOT decision-cached — embeddings ADD calls (north-star); a clean
        passthrough to the embed lane's adapter."""
        adapter = self._embed_adapter
        if adapter is None:
            raise ProviderError(
                _EMBED_PROFILE, None,
                "no embed profile configured (add an `embed` profile to enable "
                "relevance-scored memory retrieval)",
            )
        return await adapter.embed(texts)

    def forget(self, profile_name: str, messages: list[dict]) -> None:
        """Evict the decision-cache entry for this exact (profile, messages),
        if present. The runtime calls this when a response fails to parse or
        validate — a truncated/garbage reply must never be replayed from cache
        (cached=true was observed serving the same broken JSON back into a
        turn, run 126). No-op for uncacheable profiles or unknown keys."""
        if not self._cacheable(profile_name):
            return
        self._cache.pop(_cache_key(profile_name, messages), None)

    def clear_cache(self) -> None:
        """Flush the decision cache + pending HIT snapshots (W9, audit B12),
        plus the EM-135 lane-health windows — prior-run truncation evidence
        must never boost a new run's budgets. Called on world reset so
        prior-run decisions never serve into a new run."""
        self._cache.clear()
        self._pending_cached.clear()
        self._cache_hits = 0       # EM-162 — bookkeeping resets with the cache
        self._cache_misses = 0
        self._lane_outcomes.clear()
        self._lane_routed_via.clear()
        # Wave D3 / EM-177 — failover state is in-memory only: detour counters
        # and streak flags reset with the lane windows on world reset.
        self._lane_detours_routed.clear()
        self._lane_detour_counter.clear()
        self._lane_streak_substitute.clear()
        # EM-226 — the storm breaker is per-run state too: a prior run's storm
        # must never suppress a fresh run's backups.
        self._auto_breaker_open = False
        self._auto_breaker_skips = 0

    def cache_stats(self) -> dict:
        """Wave D2 / EM-162 — additive decision-cache bookkeeping:
        {hits, misses, entries}. Counts only cacheable traffic (mock-profile
        calls bypass the cache entirely and are not counted). Reset alongside
        the cache by clear_cache(). The EM-162 prompt normalization's payoff
        is measured against these numbers."""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "entries": len(self._cache),
        }

    # ── EM-135 — reroute-aware lane health ─────────────────────────────────────

    def note_parse_outcome(
        self,
        profile_name: str,
        *,
        parsed: bool,
        truncated: bool,
        timed_out: bool = False,
    ) -> None:
        """Record one runtime parse outcome for this profile's lane (EM-135).

        Called by the runtimes after every parse attempt. A response salvaged
        by truncation REPAIR still reports truncated=True — the lane is still
        cutting output; salvage hides it from the feed, not from health
        tracking. The window is a deque(maxlen=_LANE_WINDOW), so a full window
        of clean outcomes flushes a bad streak automatically.

        EM-170 — `timed_out=True` records a turn-budget timeout as a lane
        demerit in the SAME window (the mechanism truncation uses), so a lane
        that keeps stalling is visible to lane_health() consumers and chronic
        lanes get deprioritized by that logic. Deliberately NOT counted toward
        the truncation token boost (_lane_boosted): a bigger completion budget
        makes a slow lane slower, not healthier. The key is additive — only
        present on entries that actually timed out — so pre-EM-170 window
        shapes are unchanged."""
        window = self._lane_outcomes.setdefault(
            profile_name, deque(maxlen=_LANE_WINDOW)
        )
        entry = {"parsed": bool(parsed), "truncated": bool(truncated)}
        if timed_out:
            entry["timed_out"] = True
        window.append(entry)
        # routed_via at the time of the outcome — introspection only.
        self._lane_routed_via[profile_name] = self.last_routed_via(profile_name)

    def note_lane_error(self, profile_name: str) -> None:
        """EM-198 — record one adapter-level provider error (429 / 5xx /
        transport failure / malformed completion) as an `error` demerit in
        the EM-135 window. Counted by lane_sick() alongside timeouts since
        the 2026-06-12 error-bounce mandate, so a lane that keeps erroring
        gets pre-emptively detoured and recovers via the EM-177 probe path.
        Parse-shaped failures (parsed=False without timeout/error) still do
        NOT count toward sickness — those are content problems, not lane
        problems."""
        window = self._lane_outcomes.setdefault(
            profile_name, deque(maxlen=_LANE_WINDOW)
        )
        window.append({"parsed": False, "truncated": False, "error": True})
        self._lane_routed_via[profile_name] = self.last_routed_via(profile_name)

    def _lane_boosted(self, profile_name: str) -> bool:
        """True when this profile's outcome window shows enough truncations to
        flag the lane as known-bad (≥ _LANE_TRUNCATION_TRIGGER)."""
        window = self._lane_outcomes.get(profile_name)
        if not window:
            return False
        truncations = sum(1 for o in window if o.get("truncated"))
        return truncations >= _LANE_TRUNCATION_TRIGGER

    def first_attempt_max_tokens(self, profile_name: str, base: int) -> int:
        """Attempt-1 token budget for this profile (EM-135). A known-bad lane
        (see _lane_boosted) gets the SAME boost formula the parse-failure retry
        uses (agents.runtime._retry_max_tokens: max(base * 4, 2048)) so the
        first attempt stops failing at a cap the lane keeps cutting. Healthy
        lanes return `base` unchanged; recovery is automatic via the window."""
        if self._lane_boosted(profile_name):
            return max(base * 4, _LANE_BOOST_FLOOR)
        return base

    def lane_health(self) -> dict:
        """Introspection snapshot (EM-135): profile -> {window, boosted,
        timeouts, last_routed_via}. Served by GET /api/lanes (Wave D3).
        `timeouts` (EM-170, additive) counts turn-budget timeouts in the
        current window — chronic stalling lanes surface here. Wave D3 /
        EM-177 augments each entry with `sick` (the failover predicate) and
        `detours_routed_here` (detoured calls this lane absorbed this run) —
        both additive keys."""
        return {
            profile: {
                "window": [dict(o) for o in window],
                "boosted": self._lane_boosted(profile),
                "timeouts": sum(1 for o in window if o.get("timed_out")),
                "errors": sum(1 for o in window if o.get("error")),
                "last_routed_via": self._lane_routed_via.get(profile),
                "sick": self.lane_sick(profile),
                "detours_routed_here": self._lane_detours_routed.get(profile, 0),
            }
            for profile, window in self._lane_outcomes.items()
        }

    # ── Wave D3 / EM-177 — lane failover with recovery probes ──────────────────

    def set_lane_event_sink(self, sink: Callable[[dict], None] | None) -> None:
        """Register the callback that receives `lane_detour` edge payloads
        ({phase: degraded|recovered, home, substitute, agent_id}). Emitted
        ONLY on streak transitions — the first detour of a streak and the
        recovery — never per turn (per-turn truth rides the llm_call payload).
        Called synchronously from effective_profile(); the sink must be cheap
        and never raise."""
        self._lane_event_sink = sink

    def _lf_value(self, key: str, default: Any) -> Any:
        """Read one `world.lane_failover` knob defensively: the block may be a
        LaneFailoverParams dataclass, a plain dict, or absent (⇒ defaults)."""
        cfg = self._lane_failover
        if cfg is None:
            return default
        if isinstance(cfg, dict):
            value = cfg.get(key, default)
        else:
            value = getattr(cfg, key, default)
        return default if value is None else value

    def _failover_enabled(self) -> bool:
        return bool(self._lf_value("enabled", True))

    def _sick_threshold(self) -> int:
        try:
            return max(1, int(self._lf_value(
                "sick_threshold", _LANE_SICK_THRESHOLD_DEFAULT)))
        except (TypeError, ValueError):
            return _LANE_SICK_THRESHOLD_DEFAULT

    def _probe_every(self) -> int:
        try:
            return max(1, int(self._lf_value(
                "probe_every", _LANE_PROBE_EVERY_DEFAULT)))
        except (TypeError, ValueError):
            return _LANE_PROBE_EVERY_DEFAULT

    def lane_sick(self, profile_name: str) -> bool:
        """EM-177 sickness predicate: ≥ sick_threshold (default 3) demerits in
        the existing EM-135 6-window. Mock lanes are never sick. A demerit is
        a turn-budget timeout (EM-170) or — since the EM-198 error-bounce
        mandate — an adapter-level provider error (note_lane_error). Plain
        parse failures (parsed=False with neither flag) still do not count."""
        if self._is_mock_profile(profile_name):
            return False
        window = self._lane_outcomes.get(profile_name)
        if not window:
            return False
        demerits = sum(
            1 for o in window if o.get("timed_out") or o.get("error")
        )
        return demerits >= self._sick_threshold()

    def _pick_detour_candidate(
        self, home: str, exclude: set[str] | None = None
    ) -> str | None:
        """Healthiest substitute for a sick/erroring home lane: non-mock,
        available(), not sick, not in `exclude` (EM-198 — lanes already tried
        this bounce). Ranked by (fewest timeout+error demerits in window,
        fewest detours already routed there this run, stable profile order).
        None ⇒ no healthy candidate (caller keeps the home lane — never
        detour to mock, never give up the turn)."""
        best: str | None = None
        best_key: tuple | None = None
        for idx, (name, profile) in enumerate(self._profiles.items()):
            if name == home or profile.adapter == "mock":
                continue
            if name == _EMBED_PROFILE:
                continue  # EM-222 — the embeddings lane is not a chat substitute
            if name == self._auto_backup:
                continue  # EM-205 — the universal backup is never a pinned detour
            if exclude is not None and name in exclude:
                continue
            try:
                if not profile.available():
                    continue
            except Exception:  # pragma: no cover - defensive
                continue
            if self.lane_sick(name):
                continue
            window = self._lane_outcomes.get(name) or ()
            demerits = sum(
                1 for o in window if o.get("timed_out") or o.get("error")
            )
            key = (demerits, self._lane_detours_routed.get(name, 0), idx)
            if best_key is None or key < best_key:
                best, best_key = name, key
        return best

    def _emit_lane_event(self, payload: dict) -> None:
        """Hand one lane_detour edge payload to the sink; never raise."""
        sink = self._lane_event_sink
        if sink is None:
            return
        try:
            sink(payload)
        except Exception as exc:  # pragma: no cover - defensive
            log.debug("lane_detour sink failed: %s", exc)

    def effective_profile(
        self, agent_id: str, preferred: str
    ) -> tuple[str, str | None]:
        """EM-177 — resolve the lane ONE call should actually go through.

        Returns (profile_to_call, reason) with reason in {None, "detour",
        "probe"}. The agent's ASSIGNED profile never changes — identity, UI
        chip, and reassign semantics are untouched; detours are per-call.

          - failover disabled, home healthy, or no healthy candidate
            ⇒ (preferred, None) — byte-identical pre-D3 routing.
          - home SICK with a healthy candidate ⇒ every probe_every-th
            would-be-detour goes home as (preferred, "probe") so a clean
            outcome ages the demerits out of the window (automatic recovery,
            no timers, no clock reads); the rest detour to the healthiest
            candidate as (candidate, "detour").

        `lane_detour` edge events fire ONLY on streak transitions: the first
        detour of a streak (degraded) and the first healthy call after one
        (recovered) — exactly two per sick→recovered cycle."""
        if not self._failover_enabled():
            return preferred, None

        if not self.lane_sick(preferred):
            # Recovery edge: a streak was active and the lane is healthy again.
            substitute = self._lane_streak_substitute.pop(preferred, None)
            if substitute is not None:
                self._lane_detour_counter.pop(preferred, None)
                self._emit_lane_event({
                    "phase": "recovered",
                    "home": preferred,
                    "substitute": substitute,
                    "agent_id": agent_id,
                })
            return preferred, None

        candidate = self._pick_detour_candidate(preferred)
        if candidate is None:
            # All-sick (or nothing available): home lane unchanged — never
            # detour to mock, never give up the turn.
            return preferred, None

        # This call WOULD detour: count it toward the probe cadence.
        n = self._lane_detour_counter.get(preferred, 0) + 1
        self._lane_detour_counter[preferred] = n
        if n % self._probe_every() == 0:
            return preferred, "probe"

        self._lane_detours_routed[candidate] = (
            self._lane_detours_routed.get(candidate, 0) + 1
        )
        if preferred not in self._lane_streak_substitute:
            # First detour of this streak — the one "degraded" edge event.
            self._lane_streak_substitute[preferred] = candidate
            self._emit_lane_event({
                "phase": "degraded",
                "home": preferred,
                "substitute": candidate,
                "agent_id": agent_id,
            })
        return candidate, "detour"

    def last_routed_via(self, profile_name: str) -> str | None:
        """Return the model the proxy actually routed the last request to for
        this profile's persistent adapter, or None if unknown.

        After a cache HIT this reflects the CACHED routed value (staged by chat())
        rather than the adapter's stale state (W7 / EM-068)."""
        pending = self._pending_cached.get(profile_name)
        if pending is not None:
            return pending["routed_via"]
        return getattr(self._adapters.get(profile_name), "last_routed_via", None)

    def last_usage(self, profile_name: str) -> dict | None:
        """Return the token/timing usage of the last successful chat() for this
        profile's persistent adapter, or None if unknown / not captured (Mock).
        Shape per contracts/providers.md §Usage capture:
        {input_tokens, output_tokens, latency_ms, finish_reason, cached}.

        After a cache HIT this returns the cached snapshot (cached=true, tokens
        null, latency ~0) staged by chat() (W7 / EM-068)."""
        pending = self._pending_cached.get(profile_name)
        if pending is not None:
            return pending["usage"]
        return getattr(self._adapters.get(profile_name), "last_usage", None)

    async def health(self, profile_name: str) -> bool:
        profile = self._profiles.get(profile_name)
        if profile is None:
            return False
        if profile.adapter == "mock":
            return True
        # Cheap: just check that API key is present
        return bool(profile.api_key())

    def legend(self) -> list[dict]:
        import asyncio
        result = []
        for name, profile in self._profiles.items():
            result.append({
                "name": name,
                "adapter": profile.adapter,
                "model_id": profile.model_id,
                "color": profile.color,
                "available": profile.available(),
            })
        return result

    def profile_names(self) -> list[str]:
        return list(self._profiles.keys())

    def get_profile(self, name: str) -> ModelProfile | None:
        return self._profiles.get(name)

    def inject_world(self, world: object) -> None:
        """Inject world reference into MockProvider instances so they can vote dynamically."""
        for adapter in self._adapters.values():
            if hasattr(adapter, "set_world"):
                adapter.set_world(world)

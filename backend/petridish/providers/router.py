"""
Router: unified chat() interface over all adapters.
Manages per-agent profile assignment (hot-swappable at runtime).
"""
from __future__ import annotations

import asyncio
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
from .lanes import Lane, LaneRegistry, SortingList
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
# A SINGLE truncation flags the lane (was 2). During a free-tier 429 storm the
# proxy collapses every lane onto the slow 120B reasoning survivors (nemotron /
# gpt-oss), whose chain-of-thought truncates the FIRST attempt before any JSON
# appears — there is nothing to salvage, so the turn burns a full retry. Boosting
# after the first truncation (instead of letting one through as "noise") gives
# attempt 1 of the NEXT turn room to finish thinking and emit the object, cutting
# the retry rather than the call rate (north-star-safe: fewer WASTED calls).
_LANE_TRUNCATION_TRIGGER = 1      # truncations in window that flag the lane
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
# to stay deterministic + testable; at this cadence a sustained storm makes one
# auto POST per 3 failing turns instead of one per turn (~67% fewer doomed calls)
# while probing for recovery within ~2 turns.
#
# EM-268 note: the live pool is rarely FULLY exhausted — the common case is a few
# home lanes hard rate-limited (429) while healthy lanes (and `auto` itself) still
# serve. The old default of 8 turned each transient `auto` blip into a 7-of-8-turn
# idle BLACKOUT for every rate-limited-home agent, reading as "every other message
# failed" even though `auto` had capacity two turns later. 3 (the value the
# breaker tests already exercise) recovers ~2.7x faster and matches tested
# behavior; test_default_probe_every_is_sane only requires >= 2.
_AUTO_BREAKER_PROBE_EVERY = 3  # skipped backups between recovery probes

# ── Adaptive Lane Routing (spec 2026-07-07 §9 — Phase P1) ─────────────────────
# When `adaptive_routing.enabled`, a pinned lane's failure walks the lane
# registry in priority order (the user's config/lanes.yaml sorting list) instead
# of the single EM-205 `auto` retry: up to _AR_MAX_ATTEMPTS healthy lanes, each
# bounded by _AR_PER_ATTEMPT_TIMEOUT_S, skipping lanes that are health-sick, can't
# fit this request's output ceiling (the #77 lesson), or are reasoning-tagged on
# a strict-JSON turn. The terminal `auto` entry is a RESERVED BACKSTOP (W30): the
# curated walk gets max_attempts-1 attempts and the final slot is guaranteed to
# `auto` — the whole-pool router must be consulted before giving up. All
# fail ⇒ re-raise so the runtime's EM-173 idle fallback stays the last resort.
# Defaults MIRROR config.loader.AdaptiveRoutingParams so an absent lanes.yaml
# (⇒ enabled False) is byte-identical to the pre-spec pin→auto path.
_AR_MAX_ATTEMPTS_DEFAULT = 3
_AR_PER_ATTEMPT_TIMEOUT_S_DEFAULT = 12.0

# Adapter → lane source. The FreeLLMAPI proxy IS this project's OpenAI-compatible
# endpoint, so an `openai`/`openai-compatible` profile is a `freellmapi` lane
# (except the local `ollama` lane). Direct gemini/anthropic keep their source;
# direct openai/gemini/anthropic lanes as first-class registry entries is P4.
_MOCK_ADAPTER = "mock"

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
        overflow_lane: Any = None,
        adaptive_routing: Any = None,
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
        # ── EM-167 — Ollama overflow lane ──────────────────────────────────────
        # The config `world.overflow_lane` block (an OverflowLaneParams
        # dataclass, a plain dict, or None ⇒ OFF defaults). When enabled,
        # effective_profile spills a background/supporting cadence-tier turn off
        # its home FreeLLMAPI lane onto the configured overflow profile (default
        # `ollama`) as an off-critical-path background call (the animal-task
        # pattern). The target self-suppresses when missing / unavailable / mock
        # / sick, so a down Ollama never hard-fails a turn — it falls back to the
        # home lane (then EM-205 auto-backup / EM-173 idle). Read via the
        # defensive _ol_value accessor with router-matching defaults (absent ⇒
        # OFF ⇒ byte-identical pre-EM-167 routing). No clock reads.
        self._overflow_lane = overflow_lane
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

        # ── Adaptive Lane Routing (spec 2026-07-07 — P1) ───────────────────────
        # `adaptive_routing` is the config `adaptive_routing` block (an
        # AdaptiveRoutingParams dataclass, a plain dict, or None ⇒ OFF defaults ⇒
        # byte-identical pre-spec routing). The registry is STATIC for P1: built
        # ONCE from the configured profiles, ordered by the lanes.yaml sorting
        # list. It is CONSTRUCTED unconditionally (pure in-memory data) but only
        # CONSULTED by chat()'s except-branch when `enabled` — so a disabled
        # router never touches it and stays byte-identical. Discovery/refresh
        # (rebuilding this on the fly) is P2.
        self._adaptive_routing = adaptive_routing
        self._lane_registry: LaneRegistry = LaneRegistry(
            SortingList(
                self._ar_order(), allow_paid=self._ar_allow_paid(),
            ).apply(self._build_lane_universe()),
            health_fn=self.lane_sick,
        )

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
        require_json: bool = False,
        boosted: bool = False,
    ) -> str:
        # `require_json` (spec P1): True marks a strict-JSON turn so the adaptive
        # bounce loop skips reasoning-tagged lanes (the #77 lesson). It is READ
        # ONLY inside the adaptive-enabled except-branch below, so existing
        # callers that omit it (default False) keep the exact pre-spec path.
        #
        # `boosted`: True marks THIS max_tokens as a truncation-mitigation BOOST
        # (the runtime's first_attempt_max_tokens bump or the _retry_max_tokens
        # length-retry), not a genuine floor. The bounce loop's #77 token clamp
        # keys on this EXPLICIT signal — inferring the boost from the home
        # lane's window mis-attributes: the W30 redirect credits a bounced
        # truncation to the SERVING lane, so a boosted length-retry can arrive
        # while the pin's window is clean, and 4096 would be treated as a
        # genuine floor that skips every healthy small-ceiling free lane.
        # Also read only inside the adaptive except-branch; default False keeps
        # every existing caller byte-identical.
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
        if self._adaptive_enabled() and self.lane_sick(profile_name):
            # Adaptive Lane Routing (spec §6 step 1) — the pinned lane is
            # health-sick: PRE-EMPTIVELY skip it (ZERO adapter calls) and walk
            # the registry in curated order. This is the sick-lane skip the #76
            # soft-pin detour used to perform by jumping straight to `auto`; the
            # registry walk now OWNS it, so the sorting list (gpt-oss → llama →
            # qwen → * → auto-last) is honored and `auto` is a last resort, not
            # the first stop. effective_profile() yields the detour to us when
            # adaptive is on (it returns the pinned lane unchanged), so no
            # pre-call redirect ever hides the pinned lane from this walk.
            #
            # W30 — recovery probe cadence: effective_profile()'s adaptive
            # early-return bypasses the #76 probe_every path, so without a
            # probe HERE a sick pin has no principled way back home (its
            # window never sees a fresh outcome). Reuse the #76 cadence state:
            # every probe_every-th pre-skip attempts the PIN first, bounded by
            # the per-attempt timeout. A clean probe serves the turn from home
            # (the runtime's parse outcome then ages the demerits out); a
            # failed probe records ONE fresh demerit and bounces as usual.
            probe_text: str | None = None
            probe_exc: ProviderError | None = None
            n = self._lane_detour_counter.get(profile_name, 0) + 1
            self._lane_detour_counter[profile_name] = n
            probed = n % self._probe_every() == 0
            if probed:
                try:
                    probe_text = await self._call_lane(
                        adapter, messages,
                        max_tokens=max_tokens, temperature=temperature,
                        timeout=self._ar_per_attempt_timeout_s(),
                    )
                except ProviderError as exc:
                    # Recorded once by _bounce_call below (pre_skip=False).
                    probe_exc = exc
                except asyncio.TimeoutError:
                    self._record_parse_outcome(
                        profile_name,
                        parsed=False, truncated=False, timed_out=True)
            if probe_text is not None:
                text = probe_text
            elif probe_exc is not None:
                text, served_by = await self._bounce_call(
                    profile_name, probe_exc,
                    messages, max_tokens=max_tokens, temperature=temperature,
                    require_json=require_json, boosted=boosted,
                )
            else:
                text, served_by = await self._bounce_call(
                    profile_name,
                    ProviderError(
                        profile_name, None,
                        "sick-pin recovery probe timed out" if probed
                        else "pinned lane pre-skipped (health-sick)"),
                    messages, max_tokens=max_tokens, temperature=temperature,
                    require_json=require_json, pre_skip=True, boosted=boosted,
                )
        else:
            try:
                text = await adapter.chat(messages, max_tokens=max_tokens, temperature=temperature)
            except ProviderError as exc:
                if self._adaptive_enabled():
                    # Adaptive Lane Routing (spec P1) — walk the sorting-list
                    # registry in priority order (ordered / health-aware /
                    # time-capped) instead of the single EM-205 `auto` retry.
                    # The terminal `auto` entry holds the RESERVED final
                    # attempt slot (W30 backstop). All lanes failing re-raises
                    # (EM-173 idle = last resort).
                    text, served_by = await self._bounce_call(
                        profile_name, exc, messages,
                        max_tokens=max_tokens, temperature=temperature,
                        require_json=require_json, boosted=boosted,
                    )
                else:
                    # EM-205 — retry the SAME call ONCE on the proxy's `auto`
                    # router instead of fanning out across pinned lanes. Re-raises
                    # when no `auto` lane is configured or it also fails (EM-173
                    # idle = last resort). BYTE-IDENTICAL pre-spec path (adaptive
                    # OFF default).
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

        EM-226 — the storm breaker's fast-fail/probe-cadence was RESCINDED
        (2026-07-06): the backup now ALWAYS fires (muting an agent while `auto`
        was usually still serving violated the never-mute rule). The breaker
        state is OBSERVABILITY-ONLY: any `auto` failure marks it open, a served
        backup marks it closed — it no longer skips or gates a single call. The
        vestigial breaker fields are slated for removal in EM-304."""
        self.note_lane_error(home)
        backup = self._auto_backup
        if backup is None or backup == home:
            raise first_exc
        adapter = self._adapters.get(backup)
        if adapter is None:  # pragma: no cover - defensive
            raise first_exc

        # EM-226 blind-skip RESCINDED (2026-07-06): the breaker used to skip the
        # 2nd POST while "open" to avoid doubling calls during a whole-pool storm
        # — but that MUTED agents (idle fallback) even though the auto lane was
        # usually still serving, and it silently killed the lane-failover recovery
        # probe (which deliberately re-hits a dead pinned lane every Nth turn). It
        # violated the project rule: never mute an agent, always bounce to `auto`.
        # The backup now ALWAYS fires; open/closed below is observability only.
        try:
            text = await adapter.chat(
                messages, max_tokens=max_tokens, temperature=temperature
            )
        except ProviderError as exc:
            self.note_lane_error(backup)
            self._trip_auto_breaker()  # mark open (observability only — no gating)
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
        """Mark the breaker open after an `auto` failure (the whole-pool storm
        signal). OBSERVABILITY-ONLY since the 2026-07-06 fast-fail rescind — it
        no longer gates any call; the backup always fires. Logs ONLY the open
        transition. `_auto_breaker_skips` is reset to keep the /api/lanes
        snapshot tidy (a vestigial field, EM-304)."""
        if not self._auto_breaker_open:
            log.info(
                "EM-226 auto-backup breaker OPEN — proxy `auto` last failed "
                "(observability only; the backup still fires every turn)",
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
        {open, skips, probe_every}. OBSERVABILITY-ONLY since the 2026-07-06
        fast-fail rescind: `open` ⇒ the proxy `auto` lane's LAST attempt failed
        (it is no longer fast-failed — the backup still fires every turn); it
        flips closed the next time `auto` serves. Absent an `auto` lane the
        breaker never trips. `skips`/`probe_every` are vestigial (EM-304)."""
        return {
            "open": self._auto_breaker_open,
            "skips": self._auto_breaker_skips,
            "probe_every": self._auto_breaker_probe_every,
        }

    # ── Adaptive Lane Routing (spec 2026-07-07 — P1) ───────────────────────────

    def _ar_value(self, key: str, default: Any) -> Any:
        """Read one `adaptive_routing` knob defensively: the block may be an
        AdaptiveRoutingParams dataclass, a plain dict, or absent (⇒ defaults)."""
        cfg = self._adaptive_routing
        if cfg is None:
            return default
        if isinstance(cfg, dict):
            value = cfg.get(key, default)
        else:
            value = getattr(cfg, key, default)
        return default if value is None else value

    def _adaptive_enabled(self) -> bool:
        """The master gate. False (the default — no lanes.yaml / enabled:false)
        ⇒ chat() takes the byte-identical pre-spec pin→`auto` path."""
        return bool(self._ar_value("enabled", False))

    def _ar_max_attempts(self) -> int:
        try:
            return max(1, int(self._ar_value(
                "max_attempts", _AR_MAX_ATTEMPTS_DEFAULT)))
        except (TypeError, ValueError):
            return _AR_MAX_ATTEMPTS_DEFAULT

    def _ar_per_attempt_timeout_s(self) -> float:
        try:
            return float(self._ar_value(
                "per_attempt_timeout_s", _AR_PER_ATTEMPT_TIMEOUT_S_DEFAULT))
        except (TypeError, ValueError):
            return _AR_PER_ATTEMPT_TIMEOUT_S_DEFAULT

    def _ar_allow_paid(self) -> bool:
        return bool(self._ar_value("allow_paid", False))

    def _ar_order(self) -> tuple:
        order = self._ar_value("order", ())
        if isinstance(order, (list, tuple)):
            return tuple(order)
        return ()

    @staticmethod
    def _lane_source(profile: ModelProfile) -> str | None:
        """Map a profile to its lane `source`, or None when it is not a routable
        chat lane (mock/embed). The FreeLLMAPI proxy is this project's
        OpenAI-compatible endpoint, so `openai`/`openai-compatible` profiles are
        `freellmapi` lanes — except a local Ollama lane. Direct
        gemini/anthropic keep their source (their first-class registry wiring is
        P4; for P1 they are only reachable if such a profile already exists)."""
        adapter = profile.adapter
        if adapter == _MOCK_ADAPTER:
            return None
        if adapter == "anthropic":
            return "anthropic"
        if adapter == "gemini":
            return "gemini"
        if adapter in ("openai", "openai-compatible"):
            base = (profile.base_url or "").lower()
            if profile.name == "ollama" or "11434" in base:
                return "ollama"
            return "freellmapi"
        return None  # pragma: no cover - unknown adapter

    def _build_lane_universe(self) -> list[Lane]:
        """The candidate lanes the sorting list ranks (P1: STATIC, one per
        configured chat profile). Each lane maps back to its profile's adapter
        (lane.profile), so the bounce loop can call it. The embed lane is
        excluded (it is not a chat substitute); mock is excluded (never a real
        lane). `out_hint` is the profile's configured max output (the per-lane
        ceiling the #77 skip compares against)."""
        universe: list[Lane] = []
        for name, profile in self._profiles.items():
            if name == _EMBED_PROFILE:
                continue
            source = self._lane_source(profile)
            if source is None:
                continue
            universe.append(Lane(
                id=f"{source}:{name}",
                source=source,
                model_id=profile.model_id,
                profile=name,
                free=(source in ("freellmapi", "ollama")
                      or bool(getattr(profile, "is_free_tier", False))),
                out_hint=getattr(profile, "max_tokens", None),
            ))
        return universe

    def lane_registry_snapshot(self) -> list[dict]:
        """Observability projection of the static registry (priority order).
        A thin P1 view; the full `/api/lanes` registry surface is P5."""
        return [
            {
                "id": ln.id, "source": ln.source, "model_id": ln.model_id,
                "profile": ln.profile, "priority": ln.priority, "free": ln.free,
                "out_hint": ln.out_hint, "tags": list(ln.tags),
                "sick": self.lane_sick(ln.profile),
            }
            for ln in self._lane_registry.ordered()
        ]

    async def _bounce_call(
        self,
        home: str,
        first_exc: ProviderError,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        require_json: bool = False,
        pre_skip: bool = False,
        boosted: bool = False,
    ) -> tuple[str, str]:
        """Adaptive Lane Routing bounce loop (spec §6). Reached two ways:
        (a) the pinned `home` lane just FAILED (`pre_skip=False`) — its error is
        recorded as an EM-135 demerit, like the EM-205 backup; or (b) the pinned
        lane was health-sick and PRE-EMPTIVELY skipped by chat() with zero calls
        (`pre_skip=True`, spec §6 step 1) — no fresh error is noted (the lane is
        already sick). Either way `home` starts in `tried`, so the walk never
        re-hits it.

        Walk the registry in priority order; for each candidate lane SKIP if it
        is the home lane / already tried this turn, health-sick (EM-135 window),
        its output ceiling can't fit the request's genuine FLOOR (the #77
        lesson), or it is reasoning-tagged on a strict-JSON turn. Try up to
        `max_attempts` HEALTHY lanes, each bounded by `per_attempt_timeout_s`.
        Returns (text, served_by=lane.profile) on the first success; if every
        candidate fails/times out, re-raises the last provider error so the
        runtime's EM-173 idle fallback stays the last resort.

        W30 — RESERVED BACKSTOP: when the terminal sorting-list entry is the
        universal `auto` lane (FreeLLMAPI's whole-pool router), it is
        guaranteed the FINAL attempt slot — the curated walk gets
        max_attempts-1 attempts and the last one is reserved for `auto`. With
        the shipped 9-lane order, an intermittent rate window that 429s the
        top curated lanes while they are all still sub-threshold HEALTHY used
        to burn every attempt before reaching `auto`, so the documented "last
        resort" was structurally unreachable. The reservation is forfeited
        when `auto` is absent from the order, IS the home lane / already
        tried, or is itself health-sick — then the curated walk keeps the
        full budget, as before. An ordinary lane that merely sorts last is
        NOT reserved; only the `auto` backstop gets the guarantee. A failing
        `auto` ("All models exhausted") is an ordinary lane failure whose
        error surfaces to EM-173 like any other terminal failure."""
        if not pre_skip:
            self.note_lane_error(home)
        tried: set[str] = {home}
        attempts = 0
        max_attempts = self._ar_max_attempts()
        timeout = self._ar_per_attempt_timeout_s()
        last_exc: ProviderError = first_exc

        # #77 token-clamp lesson (the churn fix): when THIS request's max_tokens
        # is TRUNCATION-BOOSTED (the caller said so via `boosted` — the runtime's
        # first_attempt bump or length-retry — or the home lane's EM-135 window
        # is flagged), that boost is a mitigation HINT, not a hard requirement —
        # a DIFFERENT model may not truncate at all. Its genuine floor is the
        # home lane's own configured output ceiling. Skipping every healthy
        # 1024-ceiling free lane because 4096 > 1024 collapsed the walk to
        # auto-only and died as "All models exhausted" → idle churn. So we skip
        # a lane only when it can't fit that genuine FLOOR, and CLAMP the
        # boosted hint down to each attempted lane's ceiling (a truncation-retry
        # beats an idle fallback). An UN-boosted request is genuine: its floor IS
        # max_tokens (so a too-small lane is still skipped — the #77 regression
        # test stays green). The EXPLICIT signal matters because window
        # inference mis-attributes: the W30 redirect credits a bounced
        # truncation to the SERVING lane, so a boosted length-retry can arrive
        # while the pin's window is clean (_lane_boosted(home) False) — the
        # window check stays only as a fallback for callers that don't thread
        # the signal (narrator / animals / duck-typed harnesses).
        base_need = max_tokens
        if boosted or self._lane_boosted(home):
            home_out = getattr(self._profiles.get(home), "max_tokens", None)
            if home_out is not None:
                base_need = min(max_tokens, int(home_out))

        # W30 reserved backstop — see the docstring. `reserved` is the terminal
        # `auto` entry when it qualifies; the curated walk then keeps one
        # attempt back for it.
        ordered = self._lane_registry.ordered()
        terminal = ordered[-1] if ordered else None
        reserved: Lane | None = None
        if (terminal is not None
                and terminal.profile == self._auto_backup
                and terminal.profile not in tried
                and self._adapters.get(terminal.profile) is not None
                and not self.lane_sick(terminal.profile)):
            reserved = terminal
        curated_budget = max_attempts - 1 if reserved is not None else max_attempts

        for lane in ordered:
            if attempts >= curated_budget:
                break
            prof = lane.profile
            if prof in tried:
                continue
            if self._adapters.get(prof) is None:
                continue  # P4: direct-provider lanes without a built adapter
            if self.lane_sick(prof):
                continue  # health-sick (EM-135 window) — the auto-blind skip
            if not lane.fits(base_need):
                continue  # #77: ceiling can't fit even the genuine floor
            if require_json and "reasoning" in lane.tags:
                continue  # reasoning lane deprioritized on a strict-JSON turn

            tried.add(prof)
            attempts += 1
            text, exc = await self._attempt_bounce_lane(
                lane, messages,
                max_tokens=max_tokens, temperature=temperature, timeout=timeout,
            )
            if text is not None:
                log.info(
                    "adaptive-routing: %s %s, lane %s served the call",
                    home,
                    "pre-skipped (sick)" if pre_skip
                    else f"failed ({(first_exc.detail or '')[:120]})",
                    prof,
                )
                return text, prof
            if exc is not None:
                last_exc = exc

        # The reserved final slot: `auto`, unless the walk already reached it
        # in-loop (a universe smaller than the budget) — `tried` covers that.
        # A skip-gate that deferred it here (e.g. a genuine floor above its
        # ceiling) does NOT forfeit the slot: it is attempted CLAMPED — a
        # truncation-retry beats an idle fallback (the #77 rationale).
        if reserved is not None and reserved.profile not in tried:
            text, exc = await self._attempt_bounce_lane(
                reserved, messages,
                max_tokens=max_tokens, temperature=temperature, timeout=timeout,
            )
            if text is not None:
                log.info(
                    "adaptive-routing: %s %s, reserved `auto` backstop served "
                    "the call",
                    home,
                    "pre-skipped (sick)" if pre_skip
                    else f"failed ({(first_exc.detail or '')[:120]})",
                )
                return text, reserved.profile
            if exc is not None:
                last_exc = exc

        # Every curated healthy lane (and the reserved backstop, when present)
        # failed / stalled ⇒ re-raise so the runtime's EM-173 idle fallback
        # stays the true last resort (never mute the agent earlier).
        raise last_exc

    async def _attempt_bounce_lane(
        self,
        lane: Lane,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> tuple[str | None, ProviderError | None]:
        """One bounce attempt on `lane`, with the (possibly boosted) hint
        CLAMPED down to the lane's ceiling so a healthy small-ceiling lane is
        attempted, never skipped solely because a boost overshoots it (#77).
        Failures land in the ATTEMPTED lane's own health window. Returns
        (text, None) on success, (None, exc) on a provider error, and
        (None, None) on a stall — the timeout demerit is recorded but there is
        no ProviderError to surface."""
        adapter = self._adapters[lane.profile]
        attempt_max = (
            min(max_tokens, lane.out_hint)
            if lane.out_hint is not None else max_tokens
        )
        try:
            text = await self._call_lane(
                adapter, messages,
                max_tokens=attempt_max, temperature=temperature,
                timeout=timeout,
            )
        except ProviderError as exc:
            self.note_lane_error(lane.profile)
            return None, exc
        except asyncio.TimeoutError:
            # A stalled lane is a demerit in the SAME window a turn-budget
            # timeout uses (EM-170) — chronic stallers surface + get skipped.
            self._record_parse_outcome(
                lane.profile, parsed=False, truncated=False, timed_out=True)
            return None, None
        return text, None

    async def _call_lane(
        self,
        adapter: Provider,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
        timeout: float,
    ) -> str:
        """One bounce attempt, bounded by `per_attempt_timeout_s` (asyncio.wait_for
        cancels + awaits the inner task on timeout, so no orphaned HTTP task).
        timeout <= 0 disables the per-attempt bound."""
        coro = adapter.chat(messages, max_tokens=max_tokens, temperature=temperature)
        if timeout and timeout > 0:
            return await asyncio.wait_for(coro, timeout=timeout)
        return await coro

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
        shapes are unchanged.

        W30 — under adaptive routing, when the last chat() for `profile_name`
        was BOUNCED (the pending EM-198 snapshot carries `bounced_to`), the
        outcome is credited to the lane that ACTUALLY served the text, not
        the pin: crediting bounced successes to a persistently-capped pin
        aged its error demerits out of the window, flapping it healthy and
        burning a doomed real call roughly every other turn. Adaptive OFF
        keeps the exact #76 attribution (byte-identical guarantee)."""
        target = profile_name
        if self._adaptive_enabled():
            pending = self._pending_cached.get(profile_name)
            usage = pending.get("usage") if isinstance(pending, dict) else None
            bounced_to = usage.get("bounced_to") if isinstance(usage, dict) else None
            if isinstance(bounced_to, str) and bounced_to:
                target = bounced_to
        self._record_parse_outcome(
            target, parsed=parsed, truncated=truncated, timed_out=timed_out)

    def _record_parse_outcome(
        self,
        profile_name: str,
        *,
        parsed: bool,
        truncated: bool,
        timed_out: bool = False,
    ) -> None:
        """Raw window append for a KNOWN-attributed lane — the internal path
        the bounce loop's own demerits use, where `profile_name` is already
        the lane that was actually attempted. It must bypass the bounce
        redirect above: a stale pending snapshot for that lane (staged when
        it was itself a bounced-FROM pin on an earlier turn) must never
        re-route a demerit it just earned directly."""
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

    # ── EM-167 — Ollama overflow lane ──────────────────────────────────────────

    def _ol_value(self, key: str, default: Any) -> Any:
        """Read one `world.overflow_lane` knob defensively: the block may be an
        OverflowLaneParams dataclass, a plain dict, or absent (⇒ defaults)."""
        cfg = self._overflow_lane
        if cfg is None:
            return default
        if isinstance(cfg, dict):
            value = cfg.get(key, default)
        else:
            value = getattr(cfg, key, default)
        return default if value is None else value

    def _overflow_enabled(self) -> bool:
        return bool(self._ol_value("enabled", False))

    def _overflow_profile(self) -> str:
        return str(self._ol_value("profile", "ollama"))

    def _overflow_tiers(self) -> tuple[str, ...]:
        tiers = self._ol_value("tiers", ("background", "supporting"))
        if isinstance(tiers, (list, tuple)):
            return tuple(str(t) for t in tiers)
        return ("background", "supporting")

    def _overflow_target(self, home: str, tier: str | None) -> str | None:
        """EM-167 — the overflow profile a turn should spill to, or None when
        the overflow path does not apply this turn (so the caller keeps its
        EM-177 home/failover routing). None when: overflow disabled, the tier is
        not in the configured set (protagonist NEVER overflows), or the target
        is unset / IS the home lane / unknown / mock / unavailable / sick. The
        last group is the GRACEFUL self-suppression: a down or stalling Ollama
        stops being chosen automatically, so the turn never hard-fails. Counters
        only — no clock reads."""
        if not self._overflow_enabled():
            return None
        if tier is None or tier not in self._overflow_tiers():
            return None
        target = self._overflow_profile()
        if not target or target == home:
            return None
        profile = self._profiles.get(target)
        if profile is None or profile.adapter == "mock":
            return None
        try:
            if not profile.available():
                return None
        except Exception:  # pragma: no cover - defensive
            return None
        if self.lane_sick(target):
            return None
        return target

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

    def _detour_target(self, home: str) -> str | None:
        """The lane a SICK `home` call detours to. Prefers the universal `auto`
        lane — FreeLLMAPI's router picks whatever upstream is actually free per
        request — so a pinned free tier that is rate-limited / daily-capped /
        context-too-small routes to REAL capacity instead of idle-falling-back,
        and never collapses when several pinned lanes are sick at once (the gap
        `_pick_detour_candidate` hits: all-sick ⇒ None ⇒ home ⇒ idle fallback).

        `auto` is intentionally NOT gated on its own sick-window: it is the
        dynamic whole-pool picker, so a per-lane demerit window is a poor proxy
        for "can it serve" (the reactive EM-205 backup + EM-173 idle fallback
        still cover the rare case it genuinely can't). Falls back to the
        healthiest pinned substitute only when no `auto` lane is configured, or
        the agent IS pinned to `auto` (no self-detour)."""
        auto = self._auto_backup
        if auto is not None and auto != home:
            return auto
        return self._pick_detour_candidate(home)

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
        self, agent_id: str, preferred: str, tier: str | None = None
    ) -> tuple[str, str | None]:
        """EM-177 / EM-167 — resolve the lane ONE call should actually go through.

        Returns (profile_to_call, reason) with reason in {None, "detour",
        "probe", "overflow"}. The agent's ASSIGNED profile never changes —
        identity, UI chip, and reassign semantics are untouched; detours are
        per-call.

          - EM-167 overflow: when `world.overflow_lane.enabled` and this turn's
            `tier` is in the configured set (default background + supporting —
            protagonist NEVER overflows), the call spills to the configured
            overflow profile (default `ollama`) as (target, "overflow") — an
            off-critical-path background call (the animal-task pattern). The
            target self-suppresses when missing / unavailable / mock / sick, so
            a down Ollama falls back to the home/failover routing below (the
            turn never hard-fails). Overflow is resolved BEFORE failover: for
            background traffic the off-FreeLLMAPI lane wins even when the home
            lane is sick.
          - failover disabled, home healthy, or no healthy candidate
            ⇒ (preferred, None) — byte-identical pre-D3 routing.
          - home SICK with a healthy candidate ⇒ every probe_every-th
            would-be-detour goes home as (preferred, "probe") so a clean
            outcome ages the demerits out of the window (automatic recovery,
            no timers, no clock reads); the rest detour to the healthiest
            candidate as (candidate, "detour").

        `tier` defaults to None so the pre-EM-167 two-arg call sites (and
        duck-typed test routers) keep their exact behavior: no tier ⇒ no
        overflow, just the EM-177 path.

        `lane_detour` edge events fire ONLY on streak transitions: the first
        detour of a streak (degraded) and the first healthy call after one
        (recovered) — exactly two per sick→recovered cycle."""
        # EM-167 — off-critical-path overflow first (background/supporting only).
        overflow = self._overflow_target(preferred, tier)
        if overflow is not None:
            return overflow, "overflow"

        # Adaptive Lane Routing (spec §6, 2026-07-09 reconciliation) — when
        # adaptive_routing is enabled the sick-lane skip + ordered bounce is
        # OWNED by chat()'s registry walk, so the #76 soft-pin PRE-CALL detour to
        # `auto` is DISABLED here: we return the pinned lane unchanged (identity
        # preserved) and let chat() pre-emptively skip it if sick and walk the
        # curated sorting list (gpt-oss → llama → qwen → * → auto-last). Without
        # this yield the blind detour would send a known-sick pinned lane
        # straight to `auto`, and the curated order would never be consulted.
        # The #76 probe_every recovery cadence is honored INSIDE chat()'s
        # pre-skip (W30): every probe_every-th pre-skip attempts the pin first,
        # so a recovered pin still has a principled path back home.
        # Overflow (above) still applies; adaptive OFF ⇒ byte-identical #76 path.
        if self._adaptive_enabled():
            return preferred, None

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

        candidate = self._detour_target(preferred)
        if candidate is None:
            # No `auto` lane AND all pinned substitutes sick (or nothing
            # available): home lane unchanged — never detour to mock, never
            # give up the turn. With `auto` configured this branch is unreached.
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

    async def probe_connectivity(self, *, max_tokens: int = 8) -> bool:
        """Live liveness probe for the loop's network-down auto-resume (EM-226).
        Unlike `health` (a key-present check), this makes ONE tiny real call on
        the `auto` lane (the FreeLLMAPI health router) — or any non-mock lane if
        `auto` is absent — and returns True only when a model actually answers.
        False on any provider/transport error. Never raises, so the loop's
        recovery poll can call it safely."""
        lane = "auto" if "auto" in self._adapters else next(
            (n for n in self._adapters if not self._is_mock_profile(n)), None
        )
        adapter = self._adapters.get(lane) if lane else None
        if adapter is None:
            return False
        try:
            await adapter.chat(
                [{"role": "user", "content": "ping"}],
                max_tokens=max_tokens,
                temperature=0.0,
            )
            return True
        except Exception:
            return False

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

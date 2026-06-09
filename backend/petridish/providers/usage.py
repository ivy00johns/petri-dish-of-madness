"""
W11b / EM-083 (platform half) — usage-cap alert tracker.

Configurable per-provider day caps (rpd = requests/day, tpd = tokens/day) with
ONE `usage_alert {provider, metric, pct, limit}` emission per
provider/metric/window when usage crosses the alert threshold (70% of the cap).

Caps are configured in config/profiles.yaml, per profile entry (a profile IS a
provider lane here — groq-llama/cerebras-glm/etc. map 1:1 to upstream free-tier
providers):

    - name: groq-llama
      adapter: openai
      ...
      rpd: 1000      # optional: requests/day cap (alerts only — never blocks)
      tpd: 100000    # optional: tokens/day cap

Semantics:
  - Window = the cap's day window = one UTC calendar date (free-tier rpd/tpd
    limits are wall-clock daily quotas). On date rollover, counters AND
    emitted-state reset, so a new day can alert again.
  - The tracker only OBSERVES (Router.chat feeds it on each real adapter call);
    it never throttles or blocks anything — that stays EM-067's job.
  - No caps configured == the tracker holds no state for that provider and
    returns no alerts (today's behavior, zero overhead).
  - Distinct from EM-067's `usage_sampled` (sliding tick-window throttle in the
    engine loop): this is the day-quota ALERT channel (event-log.md v1.3.0 note 1).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable


# Contract threshold (event-log.md v1.3.0 note 1): alert on crossing 70% of a cap.
ALERT_THRESHOLD = 0.70


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class UsageAlertTracker:
    """Per-provider day-window usage counters + once-per-window alert latching.

    `caps` shape: {provider_name: {"rpd": int|None, "tpd": int|None}} — entries
    with neither cap are dropped at construction. `clock` is injectable for
    tests (returns the current window key, default = the UTC date).
    """

    def __init__(
        self,
        caps: dict[str, dict] | None = None,
        *,
        threshold: float = ALERT_THRESHOLD,
        clock: Callable[[], str] | None = None,
    ):
        self._caps: dict[str, dict[str, int]] = {}
        for provider, c in (caps or {}).items():
            if not isinstance(c, dict):
                continue
            entry: dict[str, int] = {}
            for metric in ("rpd", "tpd"):
                v = c.get(metric)
                if v is None:
                    continue
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    continue
                if iv > 0:
                    entry[metric] = iv
            if entry:
                self._caps[provider] = entry
        self._threshold = float(threshold)
        self._clock = clock or _utc_date
        # Current window key; counters + emitted-state are valid only within it.
        self._window: str = self._clock()
        # provider -> {"requests": int, "tokens": int}
        self._counts: dict[str, dict[str, int]] = {}
        # (provider, metric) pairs already alerted this window.
        self._emitted: set[tuple[str, str]] = set()

    @property
    def has_caps(self) -> bool:
        return bool(self._caps)

    def _roll_window(self) -> None:
        now = self._clock()
        if now != self._window:
            # Day rollover: fresh quota, fresh counters, re-armed alerts.
            self._window = now
            self._counts.clear()
            self._emitted.clear()

    def note(self, provider: str, *, requests: int = 1, tokens: int = 0) -> list[dict]:
        """Record usage for one real adapter call; return the alerts (0, 1 or 2 —
        one per metric) that CROSSED the threshold on this sample. Each
        provider/metric alerts at most once per window."""
        caps = self._caps.get(provider)
        if not caps:
            return []  # no caps configured = zero alerts, zero state
        self._roll_window()
        counts = self._counts.setdefault(provider, {"requests": 0, "tokens": 0})
        counts["requests"] += max(0, int(requests))
        counts["tokens"] += max(0, int(tokens or 0))

        alerts: list[dict] = []
        for metric, used in (("rpd", counts["requests"]), ("tpd", counts["tokens"])):
            limit = caps.get(metric)
            if not limit:
                continue
            frac = used / limit
            if frac < self._threshold:
                continue
            key = (provider, metric)
            if key in self._emitted:
                continue  # once per provider/metric/window
            self._emitted.add(key)
            alerts.append({
                "provider": provider,
                "metric": metric,
                "pct": round(frac * 100.0, 1),
                "limit": limit,
            })
        return alerts

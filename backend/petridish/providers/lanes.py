"""
Adaptive Lane Routing — lane registry + user-curated sorting list.

Spec: docs/superpowers/specs/2026-07-07-adaptive-lane-routing.md (Phase P1).

A `Lane` is one concrete way to get a completion (spec §3.1). The `SortingList`
turns the user's `config/lanes.yaml` `order:` block into ascending priorities
(top-to-bottom), sweeps remaining lanes of a source with a `*` glob, and drops
paid lanes unless `allow_paid`. The `LaneRegistry` holds the (static, for P1)
ordered lanes and offers a per-lane health lookup for the router's bounce loop.

This module is deliberately decoupled from config + the router: order entries
are DUCK-TYPED (an object with .source/.model/.free/... OR a plain dict), so the
loader owns `AdaptiveRoutingParams`/`LaneOrderEntry` and the router owns health,
with no import cycle. P1 is STATIC — discovery/refresh is P2.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from typing import Any, Callable, Iterable

# Sources the registry recognizes. For P1 only `freellmapi` (the local
# OpenAI-compatible proxy) + `ollama` are actually callable through existing
# adapters; direct gemini/anthropic/openai lanes are wired in P4.
LANE_SOURCES = ("freellmapi", "gemini", "anthropic", "openai", "ollama")

# Priority far below any assigned slot — an unranked lane sorts last.
_UNRANKED = 1_000_000


@dataclass(frozen=True)
class Lane:
    """One concrete way to get a completion (spec §3.1).

    `profile` is the router profile whose adapter actually serves this lane —
    for P1 every lane maps to an existing profiles.yaml entry (the bounce loop
    calls `self._adapters[lane.profile]`). `priority` is assigned by the
    SortingList (lower = tried first). `out_hint`/`ctx_hint` are the lane's
    max-output / context ceilings; a lane whose out_hint can't fit THIS
    request's max_tokens is skipped (the #77 lesson, encoded). `tags` carry
    hints like "reasoning" (deprioritized on strict-JSON turns)."""
    id: str
    source: str
    model_id: str
    profile: str
    priority: int = _UNRANKED
    enabled: bool = True
    free: bool = True
    ctx_hint: int | None = None
    out_hint: int | None = None
    tags: tuple[str, ...] = ()

    def fits(self, max_tokens: int) -> bool:
        """False when this lane's output ceiling can't cover the requested
        max_tokens (the #77 lesson). A lane with no out_hint always fits — we
        never invent a ceiling that strands a request."""
        if self.out_hint is None:
            return True
        return self.out_hint >= max_tokens


def _entry_attr(entry: Any, key: str, default: Any = None) -> Any:
    """Read one field off a duck-typed order entry (dataclass OR plain dict)."""
    if isinstance(entry, dict):
        return entry.get(key, default)
    return getattr(entry, key, default)


class SortingList:
    """The user-curated order (spec §3.3). Each `order:` entry, top-to-bottom,
    assigns the next ascending priority to the lanes it matches (source + model
    glob). A glob `model: "*"` sweeps every not-yet-placed lane of that source.
    A `free: false` entry is a PAID entry: excluded unless `allow_paid`. Lanes
    matching no entry are dropped (they are not in the sorting list). An
    `exclude` matcher (same source + model-glob shape) DENYLISTS its lanes:
    no entry may place them, not even a `*` sweep — the mechanism that keeps a
    legacy-only profile (e.g. the EM-324 command-a-2 truncator) out of the
    bounce walk (PR#106 C15)."""

    def __init__(self, order: Iterable[Any], *, allow_paid: bool = False,
                 exclude: Iterable[Any] = ()):
        self._order = list(order or ())
        self._allow_paid = bool(allow_paid)
        self._exclude = list(exclude or ())

    def _active_entry(self, entry: Any) -> bool:
        """True when this entry is processed (a free entry, or paid + allow_paid).
        A paid entry with opt-in withheld contributes nothing (§3.3)."""
        free = bool(_entry_attr(entry, "free", True))
        return free or self._allow_paid

    def _excluded(self, lane: Lane) -> bool:
        """True when a denylist matcher covers this lane (source equal + model
        glob). Exclusion is absolute: it beats every entry, including a concrete
        one naming the same model — a denylisted lane is never placed."""
        for e in self._exclude:
            if lane.source != _entry_attr(e, "source"):
                continue
            if fnmatch.fnmatch(lane.model_id, str(_entry_attr(e, "model", "*"))):
                return True
        return False

    def apply(self, universe: Iterable[Lane]) -> list[Lane]:
        """Order `universe` per the sorting list, assigning ascending priority.

        Returns a NEW list of Lanes (priority/free/tags/hints stamped from the
        matched entry). Stable: within one entry, lanes keep `universe` order.
        Excluded: paid entries (free:false) unless allow_paid; lanes no entry
        matches; lanes a denylist matcher covers (`exclude`, PR#106 C15).
        A `model: "*"` glob sweeps only lanes NOT named by a concrete
        entry elsewhere in the order (§3.3 "isn't already listed"), so an
        explicitly-listed lane keeps its own slot even when a `*` precedes it —
        that is what pins `freellmapi: auto` truly last."""
        lanes = list(universe)
        # Concrete (non-glob) entries that will actually be processed — these
        # "claim" their lanes, so a `*` sweep must skip lanes they own.
        concrete = [
            e for e in self._order
            if str(_entry_attr(e, "model", "*")) != "*" and self._active_entry(e)
        ]

        def _claimed_by_concrete(lane: Lane) -> bool:
            for e in concrete:
                if lane.source != _entry_attr(e, "source"):
                    continue
                if fnmatch.fnmatch(lane.model_id, str(_entry_attr(e, "model", "*"))):
                    return True
            return False

        placed: dict[str, Lane] = {}
        priority = 0
        for entry in self._order:
            if not self._active_entry(entry):
                continue  # paid entry, opt-in not granted → excluded
            free = bool(_entry_attr(entry, "free", True))
            source = _entry_attr(entry, "source")
            model_glob = str(_entry_attr(entry, "model", "*"))
            is_glob = model_glob == "*"
            entry_out = _entry_attr(entry, "out_hint")
            entry_ctx = _entry_attr(entry, "ctx_hint")
            entry_tags = _entry_attr(entry, "tags") or ()
            for lane in lanes:
                if lane.id in placed:
                    continue
                if self._excluded(lane):
                    continue  # denylisted — no entry may place it (PR#106 C15)
                if lane.source != source:
                    continue
                if not fnmatch.fnmatch(lane.model_id, model_glob):
                    continue
                if is_glob and _claimed_by_concrete(lane):
                    continue  # a concrete entry owns this lane — leave it for that slot
                placed[lane.id] = replace(
                    lane,
                    priority=priority,
                    free=free,
                    out_hint=entry_out if entry_out is not None else lane.out_hint,
                    ctx_hint=entry_ctx if entry_ctx is not None else lane.ctx_hint,
                    tags=tuple(entry_tags) if entry_tags else lane.tags,
                )
                priority += 1
        return sorted(placed.values(), key=lambda ln: ln.priority)


class LaneRegistry:
    """The live pool of ordered lanes (spec §3.2). Static for P1 — built once
    from the router's profiles + sorting list; discovery/refresh is P2. Carries
    an optional per-lane health lookup (`health_fn`, profile → sick) so the
    bounce loop and the future /api/lanes view share one sickness verdict."""

    def __init__(
        self,
        lanes: Iterable[Lane],
        *,
        health_fn: Callable[[str], bool] | None = None,
    ):
        self._lanes: list[Lane] = sorted(lanes, key=lambda ln: ln.priority)
        self._health_fn = health_fn

    def ordered(self) -> list[Lane]:
        """Lanes in ascending priority (tried-first order)."""
        return list(self._lanes)

    def get(self, lane_id: str) -> Lane | None:
        for lane in self._lanes:
            if lane.id == lane_id:
                return lane
        return None

    def is_sick(self, lane: Lane) -> bool:
        """Health verdict for a lane via the injected lookup (default: healthy
        — a registry with no health_fn never reports sick)."""
        if self._health_fn is None:
            return False
        return bool(self._health_fn(lane.profile))

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._lanes)

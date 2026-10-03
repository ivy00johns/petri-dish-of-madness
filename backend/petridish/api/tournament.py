"""EM-112 — the parallel-worlds tournament runner (sequential, never concurrent).

A model-family bake-off casts EVERY agent from one coarse model family
(all-Gemini world vs all-Llama world — ARCHITECTURE.md's "second instance"
idea) and runs those worlds one after another through the live TickLoop:

    for family in [gemini, llama, qwen]:
        loop.reset(cast(config, legend, family), model_family=family)
        for _ in range(ticks_per_family):
            await loop.step_and_wait(timeout=...)

SEQUENTIAL BY DESIGN (deep-research-v3 §risks; ARCHITECTURE.md §Instance):
never concurrent, so the free-tier key pool is never multiplied — the next
world starts only after the previous one finished its tick budget. Each
family's world is a fresh deterministic genesis from the SAME config (same
places/roster/city_seed) differing ONLY in the cast — comparable starts,
compared after the fact via the run browser + /api/arena (EM-119).

The tournament drives steps manually (it never calls loop.start()), so the
live tick timer stays paused and the WS/API surface simply spectates whichever
world is currently on stage. Between families the loop resets — which ENDS the
previous run row (status='ended'), so every finished family lands in the run
browser as a complete, comparable run. The final family's run stays 'running'
(paused) — the operator can keep watching it, reset it, or fork it.

API ownership lives in app.py (`/api/arena/tournament`); this module is the
engine: pure casting + a state machine with abort. Family classification
comes from providers/families.py (mirrors the frontend EM-309 derivation).
"""

from __future__ import annotations

import asyncio
import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config.loader import WorldConfig
from ..providers.families import families_in_legend

# ── Casting ───────────────────────────────────────────────────────────────────

# Families the caster refuses: "other" covers the `auto` terminal (would NOT
# be a model-family bake-off — it routes anywhere) and the `mock` adapter
# (a test double). Both are deliberately un-castable.
_UNCASTABLE_FAMILIES = frozenset({"other"})


@dataclass
class CastPlan:
    """One family's cast: the new WorldConfig + the lanes it drew from."""

    family: str
    config: WorldConfig
    lanes: list[str]                      # the family's lanes, round-robin order
    profile_by_agent: dict[str, str]      # agent name -> lane profile name


def build_cast_plan(
    cfg: WorldConfig, legend: list[dict], family: str
) -> CastPlan:
    """Cast EVERY agent in `cfg` from one coarse model `family`.

    Lanes come from the router legend grouped by family (providers/families.py),
    AVAILABLE lanes first, each group sorted for determinism; agents draw
    round-robin so a 5-agent world on 3 gemini lanes never funnels everyone
    onto one key. Deterministic: same legend ⇒ same plan.

    Raises ValueError on an unknown/un-castable family or a legend with no
    lane of that family — the endpoint maps that to a 400.
    """
    fam = (family or "").strip().lower()
    if not fam:
        raise ValueError("family is required")
    if fam in _UNCASTABLE_FAMILIES:
        raise ValueError(f"family {fam!r} cannot be cast (auto/mock are not model families)")
    groups = families_in_legend(legend)
    if fam not in groups:
        raise ValueError(
            f"unknown family {fam!r} — no configured lane matches "
            f"(available: {', '.join(sorted(groups)) or 'none'})"
        )
    entry = {p.get("name"): p for p in legend or []}
    preferred = [n for n in groups[fam] if entry.get(n, {}).get("available")]
    lanes = preferred or groups[fam]
    if not lanes:
        raise ValueError(f"family {fam!r} has no lanes")

    agents = [
        dataclasses.replace(a, profile=lanes[i % len(lanes)])
        for i, a in enumerate(cfg.agents)
    ]
    cast_cfg = dataclasses.replace(cfg, agents=agents)
    return CastPlan(
        family=fam,
        config=cast_cfg,
        lanes=list(lanes),
        profile_by_agent={a.name: a.profile for a in agents},
    )


# ── Runner ────────────────────────────────────────────────────────────────────

_MAX_FAMILIES = 8          # sanity cap: each family is a full run
_MAX_TICKS_PER_FAMILY = 500
_DEFAULT_TICKS_PER_FAMILY = 40
_STALL_LIMIT = 3           # consecutive no-progress steps before a run is stalled


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class FamilyResult:
    family: str
    run_id: int | None
    ticks_run: int
    status: str            # done | stalled | aborted
    note: str = ""


@dataclass
class TournamentState:
    status: str = "idle"   # idle | running | done | aborted | error
    families: list[str] = field(default_factory=list)
    ticks_per_family: int = _DEFAULT_TICKS_PER_FAMILY
    current_family: str | None = None
    current_index: int = 0
    current_run_id: int | None = None
    ticks_done_in_current: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    results: list[FamilyResult] = field(default_factory=list)

    def snapshot(self) -> dict:
        return {
            "status": self.status,
            "families": list(self.families),
            "ticks_per_family": self.ticks_per_family,
            "current_family": self.current_family,
            "current_index": self.current_index,
            "current_run_id": self.current_run_id,
            "ticks_done_in_current": self.ticks_done_in_current,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "results": [dataclasses.asdict(r) for r in self.results],
        }


class TournamentRunner:
    """One sequential tournament over the live TickLoop.

    Owns exactly one background asyncio task; `running` is False once it
    settles (done/aborted/error). The app module keeps a module-global runner
    so status/abort endpoints reach it from any request.
    """

    def __init__(
        self,
        *,
        loop,                     # the live TickLoop (mutated by reset, never replaced mid-run)
        config,                   # the boot WorldConfig (base for every cast)
        router,                   # for legend() at start time
        families: list[str],      # the cast order (validated by the caller)
        ticks_per_family: int = _DEFAULT_TICKS_PER_FAMILY,
        step_timeout: float = 120.0,
    ) -> None:
        self._loop = loop
        self._config = config
        self._router = router
        self._ticks_per_family = ticks_per_family
        self._step_timeout = step_timeout
        self._abort = False
        self._task: asyncio.Task | None = None
        self.state = TournamentState(
            families=list(families),
            ticks_per_family=ticks_per_family, started_at=_now(), status="running",
        )

    # ── lifecycle ──────────────────────────────────────────────────────────

    def running(self) -> bool:
        return self.state.status == "running"

    def start(self) -> None:
        self._task = asyncio.get_running_loop().create_task(self._run())

    def abort(self) -> bool:
        """Request a stop between turns. Returns True if a running tournament
        was actually aborted."""
        if not self.running():
            return False
        self._abort = True
        return True

    async def wait(self) -> None:
        if self._task is not None:
            try:
                await self._task
            except Exception:  # pragma: no cover - _run never raises (guards below)
                pass

    # ── the sequential sweep ───────────────────────────────────────────────

    async def _run(self) -> None:
        state = self.state
        try:
            legend = self._router.legend()
            plans: list[CastPlan] = []
            for fam in state.families:
                plans.append(build_cast_plan(self._config, legend, fam))

            for i, plan in enumerate(plans):
                if self._abort:
                    break
                state.current_index = i
                state.current_family = plan.family

                await self._loop.reset(plan.config, model_family=plan.family)
                state.current_run_id = getattr(self._loop, "_run_id", None)
                state.ticks_done_in_current = 0

                result = await self._drive_family(plan)
                state.results.append(result)
                state.ticks_done_in_current = result.ticks_run

            state.status = "aborted" if self._abort else "done"
            state.finished_at = _now()
        except Exception as exc:  # never let the task die silently
            state.status = "error"
            state.error = f"{type(exc).__name__}: {exc}"
            state.finished_at = _now()
        finally:
            state.current_family = None
            state.current_run_id = None

    async def _drive_family(self, plan: CastPlan) -> FamilyResult:
        """Step one family's world through its tick budget. Never calls
        start(): the live timer stays paused and every advance is ours."""
        loop = self._loop
        budget = self._ticks_per_family
        stalled = 0
        last_tick = int(getattr(loop._world, "tick", 0))
        for _ in range(budget):
            if self._abort:
                return FamilyResult(plan.family, getattr(loop, "_run_id", None),
                                    last_tick, "aborted",
                                    "aborted mid-run; run left paused with its partial ticks")
            await asyncio.sleep(0)  # yield so WS broadcasts + aborts interleave
            await loop.step_and_wait(timeout=self._step_timeout)
            tick = int(getattr(loop._world, "tick", 0))
            if tick > last_tick:
                stalled = 0
                last_tick = tick
            else:
                stalled += 1
                if stalled >= _STALL_LIMIT:
                    return FamilyResult(plan.family, getattr(loop, "_run_id", None),
                                        last_tick, "stalled",
                                        f"no tick progress for {stalled} consecutive steps")
        return FamilyResult(plan.family, getattr(loop, "_run_id", None), last_tick, "done")


def validate_tournament_request(
    families: list[str], ticks_per_family: int
) -> tuple[list[str], int]:
    """Normalize + bound-check a tournament request (pure; raises ValueError
    with a caller-friendly message). Dedupes families preserving order."""
    if not families:
        raise ValueError("families is required (1-8 family names)")
    seen: list[str] = []
    for f in families:
        fam = str(f or "").strip().lower()
        if fam and fam not in seen:
            seen.append(fam)
    if not seen:
        raise ValueError("families is required (1-8 family names)")
    if len(seen) > _MAX_FAMILIES:
        raise ValueError(f"at most {_MAX_FAMILIES} families per tournament")
    if not (1 <= int(ticks_per_family) <= _MAX_TICKS_PER_FAMILY):
        raise ValueError(
            f"ticks_per_family must be 1..{_MAX_TICKS_PER_FAMILY}"
        )
    return seen, int(ticks_per_family)

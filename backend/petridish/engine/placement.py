"""EM-268 F1 — deterministic organic building placement (cluster accretion).

Buildings sprawl the open map and clump into hamlets. Placement is a PURE
function of (building set incl. stored positions, anchor, city_seed): canonical
(created_tick, id) ordering makes it input-order-independent and append-only-
stable — a new build never moves an existing one. All math is in the WORLD frame
(±32.5), the frame citygraph nodes and assignBuildingLots already use, so nothing
is ever converted. Every random draw is seeded via citygraph._seeded_unit →
replay/fork byte-identical (EM-155). See
docs/superpowers/specs/2026-07-04-free-placement-f1-organic-accretion-design.md.

EM-303 (b/c) — STORED-WINS precedence: a building that already carries a
`position` is event-sourced truth. It is never recomputed; it seeds the parent/
obstacle set (in canonical order) BEFORE any absent position is derived, so a
mixed snapshot fills its gaps around the STORED town — never around a recomputed
phantom of it — and append-only stability holds under production uuid4 ids
(where a same-tick new build can sort BEFORE an existing one, making a from-
scratch recompute disagree with what was stored at build time). A set with no
positions at all (pre-F1 derive-on-load) takes the byte-identical pre-EM-303
pure-accretion path.

EM-303 (a) — world-extent sprawl clamp: MAX_EXTENT caps how far accretion may
wander from the anchor. A derived position beyond the cap degrades GRACEFULLY —
it falls back to a seeded in-extent spiral that prefers a clear spot near the
center and, when the town is choked, accepts the least-crowded candidate seen
(densify, never error, never gate the build). None ⇒ unclamped (pre-EM-303).
"""
from __future__ import annotations

import math

from .citygraph import _seeded_unit

# WORLD-frame tuning constants (±32.5 spans the map). Aesthetic knobs; pure fn,
# cheap to retune. MIN_SPACING = min centers gap; NEIGHBOR_R = clump radius.
MIN_SPACING: float = 1.6
NEIGHBOR_R: float = 4.0
_OVERLAP_CAP: int = 48
_GOLDEN_ANGLE: float = 2.399963229728653   # radians; deterministic spiral spread
_TAU: float = 2.0 * math.pi

# EM-303 (a) — the sprawl clamp (compile-time config, the FREE_PLACEMENT_ENABLED
# pattern). 32.5 = the world half-span, so the clamp is a no-op for every
# placement that stays on the map — it only redirects accretion that would leave
# the world (~1300+ unbounded builds). None ⇒ unclamped (pre-EM-303 behavior).
MAX_EXTENT: float | None = 32.5
_CLAMP_CAP: int = 64   # in-extent fallback spiral candidates before densifying


def _u(seed: int, bid: str, purpose: str) -> float:
    return _seeded_unit(seed, f"{bid}:{purpose}")


def _stored_position(b) -> tuple[float, float] | None:
    """The building's event-sourced position, or None. getattr-defensive: the
    pure-fn test doubles (and pre-F1 snapshots) carry no position attribute."""
    pos = getattr(b, "position", None)
    if isinstance(pos, (tuple, list)) and len(pos) == 2:
        return (float(pos[0]), float(pos[1]))
    return None


def _pref_attach(placed: list[tuple[str, float, float]], seed: int,
                 bid: str) -> tuple[float, float]:
    """Pick a parent among already-placed buildings, weighted by local density
    (1 + neighbors within NEIGHBOR_R) — rich-get-richer ⇒ hamlets. Iterates the
    id-ordered `placed` list only (never a set/dict ⇒ no hash-order drift)."""
    weights: list[float] = []
    total = 0.0
    r2 = NEIGHBOR_R * NEIGHBOR_R
    for i, (_pid, px, pz) in enumerate(placed):
        n = 0
        for j, (_qid, qx, qz) in enumerate(placed):
            if i != j and (px - qx) * (px - qx) + (pz - qz) * (pz - qz) <= r2:
                n += 1
        w = 1.0 + float(n)
        weights.append(w)
        total += w
    pick = _u(seed, bid, "parent") * total
    acc = 0.0
    for (_pid, px, pz), w in zip(placed, weights):
        acc += w
        if pick <= acc:
            return (px, pz)
    return (placed[-1][1], placed[-1][2])   # float-drift guard: last on fallthrough


def _resolve_overlap(cand: tuple[float, float],
                     placed: list[tuple[str, float, float]],
                     seed: int, bid: str) -> tuple[float, float]:
    """Nudge cand outward on a seeded spiral until MIN_SPACING-clear, capped then
    accepted (deterministic + terminating; a choked cluster is a finding, not a bug)."""
    cx, cz = cand
    base = _u(seed, bid, "spiral") * _TAU
    s2 = MIN_SPACING * MIN_SPACING
    x, z = cx, cz
    for step in range(_OVERLAP_CAP):
        if all((x - px) * (x - px) + (z - pz) * (z - pz) >= s2 for (_pid, px, pz) in placed):
            return (x, z)
        r = MIN_SPACING * (1.0 + 0.5 * (step + 1))
        ang = base + (step + 1) * _GOLDEN_ANGLE
        x = cx + math.cos(ang) * r
        z = cz + math.sin(ang) * r
    return (x, z)


def _densify_near_center(anchor: tuple[float, float],
                         placed: list[tuple[str, float, float]],
                         seed: int, bid: str,
                         extent: float) -> tuple[float, float]:
    """EM-303 (a) — the graceful in-extent fallback: sweep a seeded golden-angle
    spiral over the extent disc (area-uniform, center-first) and take the first
    MIN_SPACING-clear spot; when none of the capped candidates is clear (a truly
    choked town), accept the least-crowded candidate seen — the town DENSIFIES
    near the center instead of sprawling off the world or erring. Deterministic:
    the only draw is the seeded base angle keyed by this building's id."""
    ax, az = anchor
    base = _u(seed, bid, "clamp") * _TAU
    s2 = MIN_SPACING * MIN_SPACING
    best: tuple[float, float] | None = None
    best_d2 = -1.0
    for step in range(_CLAMP_CAP):
        # sqrt ⇒ area-uniform radii; +0.5 keeps the first candidate off-center
        # (never exactly on the anchor) while still sweeping the core first.
        r = extent * math.sqrt((step + 0.5) / _CLAMP_CAP)
        ang = base + step * _GOLDEN_ANGLE
        x = ax + math.cos(ang) * r
        z = az + math.sin(ang) * r
        d2 = min(((x - px) * (x - px) + (z - pz) * (z - pz)
                  for (_pid, px, pz) in placed), default=float("inf"))
        if d2 >= s2:
            return (x, z)
        if d2 > best_d2:
            best_d2, best = d2, (x, z)
    return best if best is not None else anchor   # unreachable while _CLAMP_CAP > 0


def _clamped(x: float, z: float, anchor: tuple[float, float]) -> bool:
    """True when (x, z) lies beyond MAX_EXTENT of the anchor (needs the EM-303
    fallback). Radial: the extent disc fits inside the ±32.5 world square."""
    if MAX_EXTENT is None:
        return False
    ax, az = anchor
    dx, dz = x - ax, z - az
    return (dx * dx + dz * dz) > (MAX_EXTENT * MAX_EXTENT)


def place_all(buildings, anchor: tuple[float, float],
              city_seed: int) -> dict[str, tuple[float, float]]:
    """World-frame position for every building. Pure fn of (set incl. stored
    positions, anchor, seed); canonical (created_tick, id) order ⇒ input-order-
    independent. STORED-WINS (EM-303): positioned buildings return their stored
    position verbatim and seed the parent set; only absences are derived."""
    ordered = sorted(buildings, key=lambda b: (int(b.created_tick), str(b.id)))
    ax, az = anchor
    placed: list[tuple[str, float, float]] = []
    out: dict[str, tuple[float, float]] = {}
    # Pass 1 — STORED-WINS: fix every event-sourced position first (canonical
    # order keeps `placed` iteration deterministic), so every derived absence
    # below attaches to / avoids the REAL town. Stored is truth even beyond
    # MAX_EXTENT — the clamp shapes new growth, it never moves history.
    pending = []
    for b in ordered:
        stored = _stored_position(b)
        if stored is None:
            pending.append(b)
            continue
        placed.append((str(b.id), stored[0], stored[1]))
        out[str(b.id)] = stored
    # Pass 2 — derive absences in canonical order (an all-absent set walks the
    # byte-identical pre-EM-303 pure-accretion path: placed starts empty).
    for b in pending:
        bid = str(b.id)
        if not placed:
            x = ax + (_u(city_seed, bid, "jx") - 0.5) * MIN_SPACING
            z = az + (_u(city_seed, bid, "jz") - 0.5) * MIN_SPACING
        else:
            px, pz = _pref_attach(placed, city_seed, bid)
            ang = _u(city_seed, bid, "ang") * _TAU
            dist = MIN_SPACING * (1.0 + _u(city_seed, bid, "dist"))
            x, z = _resolve_overlap((px + math.cos(ang) * dist, pz + math.sin(ang) * dist),
                                    placed, city_seed, bid)
        if _clamped(x, z, anchor):
            # EM-303 (a) — accretion left the world: densify near the center.
            x, z = _densify_near_center((ax, az), placed, city_seed, bid,
                                        MAX_EXTENT)
        placed.append((bid, x, z))
        out[bid] = (x, z)
    return out


def place_one(building, all_buildings, anchor: tuple[float, float],
              city_seed: int) -> tuple[float, float]:
    """Position for one building given the full current set (which includes it).
    Under STORED-WINS every already-positioned neighbor is a fixed parent, so
    live-incremental placement never disagrees with what earlier builds stored —
    append-only stability holds even when a same-tick uuid4 id sorts before an
    existing one (EM-303 c), and a later batch place_all over the stored set is
    a fixed point (returns the stored map verbatim)."""
    return place_all(all_buildings, anchor, city_seed)[str(building.id)]

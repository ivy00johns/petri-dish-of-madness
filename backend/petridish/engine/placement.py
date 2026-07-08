"""EM-268 F1 — deterministic organic building placement (cluster accretion).

Buildings sprawl the open map and clump into hamlets. Placement is a PURE
function of (building set, anchor, city_seed): canonical (created_tick, id)
ordering makes it input-order-independent and append-only-stable — a new build
sorts LAST and never moves an existing one. All math is in the WORLD frame
(±32.5), the frame citygraph nodes and assignBuildingLots already use, so nothing
is ever converted. Every random draw is seeded via citygraph._seeded_unit →
replay/fork byte-identical (EM-155). See
docs/superpowers/specs/2026-07-04-free-placement-f1-organic-accretion-design.md.
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


def _u(seed: int, bid: str, purpose: str) -> float:
    return _seeded_unit(seed, f"{bid}:{purpose}")


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


def place_all(buildings, anchor: tuple[float, float],
              city_seed: int) -> dict[str, tuple[float, float]]:
    """World-frame position for every building. Pure fn of (set, anchor, seed);
    canonical (created_tick, id) order == creation order ⇒ append-only-stable."""
    ordered = sorted(buildings, key=lambda b: (int(b.created_tick), str(b.id)))
    ax, az = anchor
    placed: list[tuple[str, float, float]] = []
    out: dict[str, tuple[float, float]] = {}
    for i, b in enumerate(ordered):
        bid = str(b.id)
        if i == 0:
            x = ax + (_u(city_seed, bid, "jx") - 0.5) * MIN_SPACING
            z = az + (_u(city_seed, bid, "jz") - 0.5) * MIN_SPACING
        else:
            px, pz = _pref_attach(placed, city_seed, bid)
            ang = _u(city_seed, bid, "ang") * _TAU
            dist = MIN_SPACING * (1.0 + _u(city_seed, bid, "dist"))
            x, z = _resolve_overlap((px + math.cos(ang) * dist, pz + math.sin(ang) * dist),
                                    placed, city_seed, bid)
        placed.append((bid, x, z))
        out[bid] = (x, z)
    return out


def place_one(building, all_buildings, anchor: tuple[float, float],
              city_seed: int) -> tuple[float, float]:
    """Position for one building given the full current set (which includes it).
    Equivalent to place_all — the newest build sorts last — so live-incremental
    and migration-batch agree (the R3 equivalence)."""
    return place_all(all_buildings, anchor, city_seed)[str(building.id)]

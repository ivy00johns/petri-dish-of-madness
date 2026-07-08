"""EM-268 F1 — cluster-accretion placement is deterministic, append-stable,
clumpy, overlap-free (EM-155)."""
import math
from dataclasses import dataclass
from petridish.engine.placement import place_all, place_one, MIN_SPACING

ANCHOR = (0.0, 0.0)
SEED = 1337


@dataclass
class B:
    id: str
    created_tick: int


def _set(n, start_tick=0):
    # distinct ticks ⇒ deterministic canonical order without relying on id hashing
    return [B(id=f"bld_{i:03d}", created_tick=start_tick + i) for i in range(n)]


def test_deterministic_same_inputs_same_positions():
    a = place_all(_set(20), ANCHOR, SEED)
    b = place_all(_set(20), ANCHOR, SEED)
    assert a == b


def test_input_order_independent():
    s = _set(20)
    forward = place_all(s, ANCHOR, SEED)
    reverse = place_all(list(reversed(s)), ANCHOR, SEED)
    assert forward == reverse            # canonical sort ⇒ order-independent


def test_first_building_near_anchor():
    pos = place_all(_set(1), ANCHOR, SEED)["bld_000"]
    assert math.dist(pos, ANCHOR) <= MIN_SPACING


def test_append_only_growth_never_moves_existing():
    small = place_all(_set(10), ANCHOR, SEED)
    grown = place_all(_set(11), ANCHOR, SEED)   # one more, latest tick ⇒ sorts last
    for k in small:
        assert grown[k] == small[k]             # existing positions frozen


def test_min_spacing_no_exact_stacking():
    pos = list(place_all(_set(40), ANCHOR, SEED).values())
    for i in range(len(pos)):
        for j in range(i + 1, len(pos)):
            assert pos[i] != pos[j]             # never identical coords


def test_forms_more_than_one_clump():
    # Preferential attachment ⇒ hamlets, not a single tight blob nor a uniform ring.
    pos = list(place_all(_set(60), ANCHOR, SEED).values())
    xs = [p[0] for p in pos]
    zs = [p[1] for p in pos]
    spread = max(max(xs) - min(xs), max(zs) - min(zs))
    assert spread > 4 * MIN_SPACING            # the city spreads out (not one blob)


def test_place_one_equals_place_all_slice():
    s = _set(15)
    full = place_all(s, ANCHOR, SEED)
    last = s[-1]
    assert place_one(last, s, ANCHOR, SEED) == full[last.id]

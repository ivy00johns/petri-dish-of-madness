"""EM-299 — parametric building-recipe grammar (engine-side runtime contract).

An agent's `propose_project` turn may carry an OPTIONAL `recipe` object that
authors the building's *shape*, not just its kind. This module is the canonical
RUNTIME home of that grammar: the closed enums, the bounded `floors` int, the
"sensible defaults", and the two validation paths (strict + lenient coerce).

It mirrors — field-for-field, value-for-value — the EM-297 divergence-probe
schema in `backend/scripts/em297_recipe_schema.py`, which validated at 100 %
against real free models (docs/research/2026-07-11-em297-divergence-probe.md).
That script lives under `backend/scripts/` (NOT an installed package), so the
engine can't import it; instead this module re-states the grammar and
`backend/tests/test_em299_building_recipes.py::test_engine_schema_matches_probe`
loads the probe module by path and asserts the two never drift.

Design rules (unchanged from EM-297):
  - enum-heavy: every categorical field is a closed enum, so weak free models
    can't drift into prose values.
  - three tiers on the tick path (probe §6 recommended posture): strict parse →
    lenient coerce-with-logged-repairs → catalog fallback. `coerce_recipe`
    ALWAYS returns a valid recipe for a dict input, so a malformed shape
    degrades to a building, never a hole and never a dead turn.
  - PURE + deterministic: no clock, no randomness (EM-155). The stored value is
    a plain JSON-safe dict in canonical field order, so snapshots round-trip
    byte-identically.

Only stdlib + pydantic (already a backend dependency) are used.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ──────────────────────────────────────────────────────────────────────────────
# Enums — closed vocabularies, lowercase snake_case values (verbatim EM-297)
# ──────────────────────────────────────────────────────────────────────────────

class Footprint(str, Enum):
    tiny = "tiny"
    small = "small"
    medium = "medium"
    large = "large"
    grand = "grand"


class Roof(str, Enum):
    flat = "flat"
    shed = "shed"
    gable = "gable"
    hip = "hip"
    dome = "dome"
    spire = "spire"


class Material(str, Enum):
    wood = "wood"
    timber_frame = "timber_frame"
    brick = "brick"
    stone = "stone"
    marble = "marble"
    plaster = "plaster"
    mud_brick = "mud_brick"


class Palette(str, Enum):
    warm = "warm"
    cool = "cool"
    earthy = "earthy"
    pastel = "pastel"
    vivid = "vivid"
    muted = "muted"
    monochrome = "monochrome"


class WindowDensity(str, Enum):
    none = "none"
    sparse = "sparse"
    regular = "regular"
    dense = "dense"


class Trim(str, Enum):
    none = "none"
    simple = "simple"
    ornate = "ornate"
    gilded = "gilded"


FLOORS_MIN = 1
FLOORS_MAX = 8

# Field name → default value (the "sensible defaults" contract).
DEFAULTS: dict[str, Any] = {
    "footprint": Footprint.medium,
    "floors": 1,
    "roof": Roof.gable,
    "material": Material.wood,
    "palette": Palette.earthy,
    "window_density": WindowDensity.regular,
    "trim": Trim.simple,
}

# Canonical field ORDER — the stored value-dict always uses this so snapshots are
# byte-stable regardless of the order the model emitted the keys.
FIELD_NAMES: tuple[str, ...] = tuple(DEFAULTS.keys())

_ENUM_FIELDS: dict[str, type[Enum]] = {
    "footprint": Footprint,
    "roof": Roof,
    "material": Material,
    "palette": Palette,
    "window_density": WindowDensity,
    "trim": Trim,
}


# ──────────────────────────────────────────────────────────────────────────────
# Strict model
# ──────────────────────────────────────────────────────────────────────────────

class Recipe(BaseModel):
    """Strict recipe: unknown keys rejected, enums closed, floors bounded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    footprint: Footprint = DEFAULTS["footprint"]
    floors: int = Field(default=DEFAULTS["floors"], ge=FLOORS_MIN, le=FLOORS_MAX)
    roof: Roof = DEFAULTS["roof"]
    material: Material = DEFAULTS["material"]
    palette: Palette = DEFAULTS["palette"]
    window_density: WindowDensity = DEFAULTS["window_density"]
    trim: Trim = DEFAULTS["trim"]

    def as_value_dict(self) -> dict[str, Any]:
        """Plain JSON-safe dict (enum -> str) in canonical FIELD_NAMES order —
        the exact shape stored on Building.recipe and serialized in snapshots."""
        return {name: _plain(getattr(self, name)) for name in FIELD_NAMES}


def _plain(value: Any) -> Any:
    return value.value if isinstance(value, Enum) else value


# ──────────────────────────────────────────────────────────────────────────────
# Coercion (the lenient repair path — the tick-path validator)
# ──────────────────────────────────────────────────────────────────────────────

def coerce_recipe(obj: dict[str, Any]) -> tuple[Recipe, list[str]]:
    """Lenient repair path: always returns a valid Recipe plus repair notes.

    EVERY deviation from the strict schema is recorded (repair-free ⇒ the input
    was already strictly valid):
      - unknown keys dropped (noted)
      - missing keys fall back to DEFAULTS (noted)
      - null / invalid enum values fall back to DEFAULTS (noted)
      - floors int()-coerced when possible (float truncation noted) and clamped
        to [1, 8] (noted)

    Pure + deterministic. Raises nothing for a dict input.
    """
    repairs: list[str] = []
    clean: dict[str, Any] = {}

    for key in obj:
        if key not in FIELD_NAMES:
            repairs.append(f"dropped unknown key {key!r}")

    for name, enum_cls in _ENUM_FIELDS.items():
        if name not in obj:
            repairs.append(f"{name}: missing -> default {DEFAULTS[name].value!r}")
            clean[name] = DEFAULTS[name]
            continue
        value = obj[name]
        if value is None:
            repairs.append(f"{name}: null -> default {DEFAULTS[name].value!r}")
            clean[name] = DEFAULTS[name]
            continue
        try:
            clean[name] = enum_cls(
                str(value).strip().lower().replace("-", "_").replace(" ", "_"))
        except ValueError:
            repairs.append(f"{name}: invalid {value!r} -> default {DEFAULTS[name].value!r}")
            clean[name] = DEFAULTS[name]

    if "floors" not in obj:
        repairs.append(f"floors: missing -> default {DEFAULTS['floors']}")
        clean["floors"] = DEFAULTS["floors"]
    elif obj["floors"] is None:
        repairs.append(f"floors: null -> default {DEFAULTS['floors']}")
        clean["floors"] = DEFAULTS["floors"]
    else:
        floors_raw = obj["floors"]
        try:
            floors_f = float(floors_raw)
            floors = int(floors_f)
        except (TypeError, ValueError, OverflowError):
            repairs.append(f"floors: invalid {floors_raw!r} -> default {DEFAULTS['floors']}")
            floors = DEFAULTS["floors"]
        else:
            if floors != floors_f:
                repairs.append(f"floors: {floors_raw!r} truncated -> {floors}")
            clamped = max(FLOORS_MIN, min(FLOORS_MAX, floors))
            if clamped != floors:
                repairs.append(f"floors: {floors} clamped -> {clamped}")
            floors = clamped
        clean["floors"] = floors

    return Recipe.model_validate(clean), repairs


# ──────────────────────────────────────────────────────────────────────────────
# The engine entry point — args-dict → stored value (or None)
# ──────────────────────────────────────────────────────────────────────────────

def normalize_recipe(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Turn a raw `recipe` action arg into the value stored on Building.recipe.

    Returns `(value_dict, repairs)`:
      - `raw` is a dict  → coerce → `(canonical value-dict, repairs)`. Even a
        garbage dict yields a valid all-default recipe (never a hole).
      - `raw` is anything else (None / str / list / number) → `(None, [])`:
        an UNSALVAGEABLE recipe degrades to a normal no-recipe build (catalog
        fallback, today's behavior — feed-safe, never a dead turn).

    Pure + deterministic; the caller only stores when the flag is on.
    """
    if not isinstance(raw, dict):
        note = [] if raw is None else [f"recipe: not an object ({type(raw).__name__}) -> dropped"]
        return None, note
    recipe, repairs = coerce_recipe(raw)
    return recipe.as_value_dict(), repairs

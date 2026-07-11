"""EM-297 — draft parametric building-recipe schema (probe-only, NOT engine code).

This is the tight, enum-heavy schema handed to free models in the divergence
probe (em297_probe.py). It doubles as the draft contract for EM-299: if the
probe blesses the keystone, this module is the starting point for the real
`recipe` field on the build turn.

Design rules (from REMAINING-WORK EM-297 + deep-research-v5-1 section 3.2):
  - enum-heavy: every categorical field is a closed enum, so weak free models
    can't drift into prose values and divergence is countable.
  - hard validation: strict parse rejects unknown keys, out-of-enum values,
    and out-of-range floors.
  - sensible defaults: every field has a default, and a lenient `coerce`
    path repairs bad fields to defaults (recording every repair) so a
    future engine integration never hard-fails a build turn.

Only stdlib + pydantic (already a backend dependency) are used.
"""

from __future__ import annotations

import json
import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ──────────────────────────────────────────────────────────────────────────────
# Enums — closed vocabularies, lowercase snake_case values
# ──────────────────────────────────────────────────────────────────────────────

class Footprint(str, Enum):
    """Ground-plan size class (maps to lot coverage in EM-299)."""
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
        """Plain dict of primitive values (enum -> str) for scoring/serializing."""
        d = self.model_dump()
        return {k: (v.value if isinstance(v, Enum) else v) for k, v in d.items()}


# The one-shot example embedded in the probe's system prompt. Deliberately
# distinctive (a smithy) with several NON-default values, so an "echo" of the
# example is detectable and distinguishable from a model merely landing on
# the defaults.
EXAMPLE_RECIPE = Recipe(
    footprint=Footprint.small,
    floors=1,
    roof=Roof.shed,
    material=Material.brick,
    palette=Palette.muted,
    window_density=WindowDensity.sparse,
    trim=Trim.none,
)


# ──────────────────────────────────────────────────────────────────────────────
# Parsing helpers
# ──────────────────────────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort extraction of ONE JSON object from raw model output.

    Tries, in order: whole string, fenced ```json blocks, first {...} span.
    Returns None when nothing parses to a dict.
    """
    candidates: list[str] = [text.strip()]
    candidates += [m.strip() for m in _FENCE_RE.findall(text)]
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for cand in candidates:
        if not cand:
            continue
        try:
            obj = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def parse_recipe_strict(raw: str | dict[str, Any]) -> tuple[Recipe | None, list[str]]:
    """Hard validation: (Recipe, []) on success, (None, [errors]) on failure.

    A string input is first run through extract_json_object.
    """
    if isinstance(raw, str):
        obj = extract_json_object(raw)
        if obj is None:
            return None, ["no JSON object found in output"]
    else:
        obj = raw
    try:
        return Recipe.model_validate(obj), []
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}"
            for e in exc.errors()
        ]
        return None, errors


def coerce_recipe(obj: dict[str, Any]) -> tuple[Recipe, list[str]]:
    """Lenient repair path: always returns a valid Recipe plus repair notes.

    - unknown keys are dropped (noted)
    - missing / invalid enum values fall back to DEFAULTS (noted)
    - floors is int()-coerced when possible and clamped to [1, 8] (noted)
    """
    repairs: list[str] = []
    clean: dict[str, Any] = {}

    for key in obj:
        if key not in FIELD_NAMES:
            repairs.append(f"dropped unknown key {key!r}")

    for name, enum_cls in _ENUM_FIELDS.items():
        value = obj.get(name)
        if value is None:
            if name in obj:
                repairs.append(f"{name}: null -> default {DEFAULTS[name].value!r}")
            clean[name] = DEFAULTS[name]
            continue
        try:
            clean[name] = enum_cls(str(value).strip().lower().replace("-", "_").replace(" ", "_"))
        except ValueError:
            repairs.append(f"{name}: invalid {value!r} -> default {DEFAULTS[name].value!r}")
            clean[name] = DEFAULTS[name]

    floors_raw = obj.get("floors")
    if floors_raw is None:
        if "floors" in obj:
            repairs.append(f"floors: null -> default {DEFAULTS['floors']}")
        clean["floors"] = DEFAULTS["floors"]
    else:
        try:
            floors = int(float(floors_raw))
        except (TypeError, ValueError):
            repairs.append(f"floors: invalid {floors_raw!r} -> default {DEFAULTS['floors']}")
            floors = DEFAULTS["floors"]
        else:
            clamped = max(FLOORS_MIN, min(FLOORS_MAX, floors))
            if clamped != floors:
                repairs.append(f"floors: {floors} clamped -> {clamped}")
            floors = clamped
        clean["floors"] = floors

    return Recipe.model_validate(clean), repairs


def schema_prompt_block() -> str:
    """Human/LLM-readable schema description for the probe's system prompt."""
    lines = [
        "Fields (ALL required; values MUST come from the allowed lists):",
        f'- "footprint": one of {[e.value for e in Footprint]}  (ground-plan size)',
        f'- "floors": integer {FLOORS_MIN}-{FLOORS_MAX}',
        f'- "roof": one of {[e.value for e in Roof]}',
        f'- "material": one of {[e.value for e in Material]}  (main wall material)',
        f'- "palette": one of {[e.value for e in Palette]}  (colour mood)',
        f'- "window_density": one of {[e.value for e in WindowDensity]}',
        f'- "trim": one of {[e.value for e in Trim]}  (decorative detail level)',
    ]
    return "\n".join(lines)

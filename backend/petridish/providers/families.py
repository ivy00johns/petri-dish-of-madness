"""EM-112 — coarse model-family classification.

One line of theory: the parallel-worlds tournament seeds every agent from ONE
model *family* (all-Gemini world vs all-Llama world), so both the caster and
the arena aggregation need a stable profile→family mapping. Deliberately
coarse — the tournament asks "which FAMILY", not "which exact checkpoint", so
`llama-3.1` and `llama-3.3` both read `llama`.

The pattern table MIRRORS the frontend's EM-309 derivation
(`web/src/lib/blindLineup.ts` modelFamily()) so a run the Blind Lineup calls
`gemini` is the same family the Arena groups by. Keep the two tables in sync;
`test_model_families.py` pins the cases the frontend test pins. Matched
against the lowercased "<model_id> <profile name>" haystack, most specific
first; unknown ⇒ "other" (which also covers the `auto` terminal and the
`mock` adapter — both intentionally un-castable, see tournament.cast_config).

(The one deliberate addition over the shipped EM-309 table: `kimi|moonshot` —
a real profiles.yaml lane family that otherwise read "other" and would have
been excluded from the tournament cast. Added to BOTH tables in the same
commit so the mirror stays exact.)
"""

from __future__ import annotations

# (regex, family) — most specific first; same order as blindLineup.ts.
FAMILY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bllama\b|llama-?\d", "llama"),
    (r"qwen", "qwen"),
    (r"gemma", "gemma"),
    (r"gemini", "gemini"),
    (r"mixtral|mistral|ministral|codestral", "mistral"),
    (r"claude|haiku|sonnet|opus", "claude"),
    (r"deepseek", "deepseek"),
    (r"command-?r|cohere", "command-r"),
    (r"nemotron", "nemotron"),
    (r"\bphi-?\d|\bphi\b", "phi"),
    (r"\bgpt\b|gpt-?\d|openai/gpt", "gpt"),
    (r"grok", "grok"),
    (r"\bglm\b|glm-?\d", "glm"),
    (r"\byi-?\d|\byi\b", "yi"),
    (r"kimi|moonshot", "kimi"),
)

_COMPILED: tuple[tuple[object, str], ...] | None = None


def _compiled() -> tuple[tuple[object, str], ...]:
    global _COMPILED
    if _COMPILED is None:
        import re

        _COMPILED = tuple((re.compile(pat), fam) for pat, fam in FAMILY_PATTERNS)
    return _COMPILED


def model_family(model_id: str | None, profile_name: str | None = None) -> str:
    """Derive the coarse family for a lane. Looks at model_id first (most
    reliable) then the profile name; never throws; unknown ⇒ "other"."""
    hay = f"{model_id or ''} {profile_name or ''}".lower()
    for rx, fam in _compiled():
        if rx.search(hay):
            return fam
    return "other"


def families_in_legend(legend: list[dict]) -> dict[str, list[str]]:
    """Group a router legend() (list of {name, model_id, ...}) into
    family -> [profile names] (sorted for determinism). Profiles that map to
    "other" (auto / mock / unclassified) are INCLUDED under "other" — the
    tournament caster is what refuses to cast from them; the arena just
    reports what exists."""
    out: dict[str, list[str]] = {}
    for p in legend or []:
        name = str(p.get("name") or "")
        if not name:
            continue
        fam = model_family(p.get("model_id"), name)
        out.setdefault(fam, []).append(name)
    for fam in out:
        out[fam] = sorted(out[fam])
    return out

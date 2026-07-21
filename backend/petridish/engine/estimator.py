"""Predict the request (prompt) size a flag combo generates by running the REAL
prompt builder against a flag-overridden shallow copy of the live world, then
tokenizing. Drift-proof (same code that builds live prompts) and predictive (it
can estimate a combo you have not run). No LLM call — build + count only, and no
mutation of the live world (god_whispers=[] suppresses the one mutation
_assemble_context would otherwise do)."""
from __future__ import annotations
import copy
from typing import Any
from ..agents.runtime import _assemble_context

# v1 base excludes live recent-events/memory (a LOWER BOUND on the true base);
# the flag DELTAS — the centerpiece — are exact. v2 feeds real recent events.
_BASE_NOTE = "base excludes live recent-events/memory (lower bound); flag deltas are exact"


def count_tokens(text: str) -> tuple[int, str]:
    """(token_count, tokenizer_name). Prefers tiktoken cl100k_base; falls back to
    a char/4 heuristic when tiktoken/its encoding is unavailable (offline)."""
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text)), "cl100k_base"
    except Exception:
        return max(1, len(text) // 4), "heuristic"


def _override_params(params: Any, overrides: dict[str, bool]) -> Any:
    """Shallow-copy params and flip `enabled` on a per-block copy for each
    override. Absent blocks (e.g. faith) get a {'enabled': val} overlay — other
    keys fall through to dataclass defaults (== the block's real defaults)."""
    p = copy.copy(params)
    for flag, val in overrides.items():
        block = getattr(p, flag, None)
        if block is None:
            setattr(p, flag, {"enabled": bool(val)})
        elif isinstance(block, dict):
            nb = dict(block); nb["enabled"] = bool(val); setattr(p, flag, nb)
        else:  # dataclass
            nb = copy.copy(block); nb.enabled = bool(val); setattr(p, flag, nb)
    return p


def _build_tokens(world: Any, agent: Any, params: Any, overrides: dict[str, bool]) -> int:
    p = _override_params(params, overrides)
    w = copy.copy(world)
    w.params = p
    messages = _assemble_context(
        agent, w, recent_events=[], params=p,
        god_whispers=[], board_notes=[], commitments=[], overheard=[],
    )
    text = "".join(m.get("content", "") for m in messages)
    n, _ = count_tokens(text)
    return n


def estimate_prompt(world: Any, agent: Any, params: Any,
                    overrides: dict[str, bool], prompt_weight_flags: list[str]) -> dict:
    """Full estimate for the exact combo + per-flag marginal breakdown.

    `overrides` is the pending combo (flag -> bool). The headline total is the
    real build of that exact combo. The breakdown reports `base` (all
    prompt-weight flags OFF) plus each ACTIVE flag's marginal contribution
    (base+flag − base) — labeled marginal because interactions mean the sum need
    not equal total−base; the total is authoritative."""
    # Effective combo: start from the flags' current param state, apply overrides.
    all_off = {f: False for f in prompt_weight_flags}
    combo = dict(all_off)
    combo.update({f: v for f, v in overrides.items() if f in prompt_weight_flags})

    total = _build_tokens(world, agent, params, combo)
    base = _build_tokens(world, agent, params, all_off)
    _, tok_name = count_tokens("probe")

    breakdown = [{"key": "base", "tokens": base}]
    for flag in prompt_weight_flags:
        if combo.get(flag):
            with_flag = _build_tokens(world, agent, params, {**all_off, flag: True})
            breakdown.append({"key": flag, "tokens": max(0, with_flag - base)})

    output_budget = int(getattr(getattr(params, "agent", None), "max_tokens", 1024) or 1024)
    return {
        "total_input_tokens": total,
        "output_budget": output_budget,
        "tokenizer": tok_name,
        "base_note": _BASE_NOTE,
        "breakdown": breakdown,
    }

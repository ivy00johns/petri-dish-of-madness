"""Derive the Lab Setup capability table: per-lane free/paid, context window,
and a clean|reasoning|unknown reliability tag. Reliability encodes the EM-324
knowledge — the curated lanes.yaml `order` is the hand-ranked clean set; the
`exclude` denylist + a seed reasoning-model set are the truncators."""
from __future__ import annotations
import fnmatch

# EM-324 findings: models that emit reasoning preamble and truncate strict-JSON
# on the heavy agent prompt (finish_reason='length'). gpt-oss-120b is clean-JSON
# but CoT-truncates on heavy turns, so it is treated as reasoning for headroom.
REASONING_MODELS = {
    "kimi-k2.6", "zai-glm-4.7", "gemini-3.5-flash", "deepseek-v4-pro",
    "llama-3.3-70b-versatile", "qwen3-next-80b", "gpt-oss-120b",
}

# Static context-window seed (tokens). Absent ⇒ None (unknown). Extend freely.
CONTEXT_WINDOWS = {
    "mistral-large-3-675b": 128000, "mistral-small-4-119b": 128000,
    "llama-3.3-70b-fp8-fast": 128000, "gemini-3.1-flash-lite": 1000000,
    "minimax-m3": 1000000, "command-r-2": 128000, "gpt-oss-120b": 128000,
    "claude-sonnet-5": 200000,
}

def _matches(model_id: str, matcher_model: str) -> bool:
    """True if a lanes.yaml order/exclude matcher glob matches this model_id."""
    return fnmatch.fnmatch(model_id, matcher_model)

def _is_excluded(model_id: str, exclude: list[dict]) -> bool:
    return any(_matches(model_id, e.get("model", "")) for e in exclude)

def _in_curated_order(model_id: str, order: list[dict]) -> bool:
    """In the curated order = a SPECIFIC entry matches (not the `*` sweep, not
    `auto`). The sweep/auto are fallbacks, not a clean endorsement."""
    for e in order:
        m = e.get("model", "")
        if m in ("*", "auto"):
            continue
        if _matches(model_id, m):
            return True
    return False

def _reliability(model_id: str, order: list[dict], exclude: list[dict]) -> str:
    if _is_excluded(model_id, exclude) or model_id in REASONING_MODELS:
        return "reasoning"
    if _in_curated_order(model_id, order):
        return "clean"
    return "unknown"

def _free_for(model_id: str, order: list[dict], adapter: str) -> bool:
    """Paid if a matching SPECIFIC order entry says free: False, or it's a
    non-freellmapi (direct paid) adapter with no free marker. Generic sweep
    entries (`*` / `auto`) are source-blind glob matches — like
    `_in_curated_order`, they're a fallback, not an authoritative free/paid
    marker, so a later specific override (e.g. a paid anthropic model) still
    wins even when a `*` sweep entry appears earlier in the list."""
    for e in order:
        m = e.get("model", "")
        if m in ("*", "auto"):
            continue
        if _matches(model_id, m):
            return bool(e.get("free", adapter == "openai"))
    return adapter == "openai"

def build_capability_table(order: list[dict], exclude: list[dict],
                           profiles: list[dict], cast_pins: dict[str, str]) -> dict:
    lanes = []
    for p in profiles:
        model_id = p.get("model_id", "")
        lanes.append({
            "id": p.get("name", model_id),
            "provider": p.get("adapter", "?"),
            "free": _free_for(model_id, order, p.get("adapter", "")),
            "context_window": CONTEXT_WINDOWS.get(model_id),
            "reliability": _reliability(model_id, order, exclude),
        })
    return {"lanes": lanes, "cast_pins": dict(cast_pins)}

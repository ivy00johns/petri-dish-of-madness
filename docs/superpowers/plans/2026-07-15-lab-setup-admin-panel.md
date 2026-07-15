# Lab Setup Admin Panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the "Lab Setup" panel — a next-run staging view that lets you compose a flag combo, see the request size it generates and the model tier it needs (or a "known risk" warning), then apply via restart.

**Architecture:** Backend-first. Two new pure-ish backend modules (`estimator`, `capability`) + four FastAPI endpoints expose the data; a new React route (`/lab`) with focused components renders it. The estimator runs the REAL prompt builder (`_assemble_context`) against a flag-overridden shallow copy of the live world and tokenizes the result — the single source of truth, drift-proof. The recommender is pure logic over an estimate × a per-lane capability table.

**Tech Stack:** Python 3.12 / FastAPI / pytest (backend); React + TypeScript + Vite + vitest + react-router-dom (frontend); tiktoken (optional, with heuristic fallback).

## Global Constraints

- **Test/typecheck toolchain (memory `petridish-test-toolchain`):** backend `.venv/bin/python -m pytest backend/tests/... -q`; frontend typecheck `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`; frontend tests `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run` (CWD MUST be `web/`). Never `npx`, never `tsc --noEmit`.
- **Subscription-only billing (memory `billing-subscription-only`):** the recommender ADVISES a tier; it never switches billing or auto-spends. A "needs paid" verdict is information only.
- **Fail-closed:** a lane with `unknown` reliability is NEVER placed in the "safe" set.
- **Config bakes per-run (memory `dev-reload-kills-live-sim`):** apply = write config + fresh run; `uvicorn --reload` is banned. Never trigger `--reload`.
- **No live-world mutation:** the estimator MUST pass `god_whispers=[]` (and empty `board_notes`/`commitments`/`overheard`) to `_assemble_context` so building a prompt never consumes the live world's whisper queue.
- **fix-don't-hide (memory `fix-dont-hide-the-feed`):** an estimator/apply failure surfaces the error; it never shows a fabricated number.
- **Commit trailers (memory `no-session-link-in-public-artifacts`):** keep `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`; OMIT any `Claude-Session:` line (public repo).
- **Branch:** all work on a feature branch `feat/lab-setup-panel`, never directly on main.

---

## Shared Contracts (used across tasks — keep names/types identical)

**Flag inventory (v1).** Prompt-weight group: `comm, settlements, faith, war, factions, universalization, memory_retrieval, buildings, planning, narrator, miracles, children, animals, image_gen, healing_house, charters, chimera_twins, coherence, generations`. Routing/ops group: `lane_failover, overflow_lane, cap_governor, usage_caps, cache, discovery`. (`discovery` lives at `world.adaptive_routing.discovery.enabled`; all others at `world.<flag>.enabled`.)

**Threshold seeds:** `T_CLEAN = 4500`, `T_PAID = 8000` (input tokens; calibrated in v2).

**Backend response shapes:**
- `GET /api/config/flags` → `{"baked": {flag: bool}, "groups": {"prompt_weight": [str], "routing_ops": [str]}}`
- `POST /api/estimate` body `{"overrides": {flag: bool}}` → on success `{"ok": true, "total_input_tokens": int, "output_budget": int, "tokenizer": "cl100k_base"|"heuristic", "base_note": str, "breakdown": [{"key": "base"|flag, "tokens": int}]}`; on failure `{"ok": false, "error": str}`
- `GET /api/lanes/capability` → `{"lanes": [{"id": str, "provider": str, "free": bool, "context_window": int|null, "reliability": "clean"|"reasoning"|"unknown"}], "cast_pins": {agent_name: profile_name}}`
- `POST /api/config/apply` body `{"overrides": {flag: bool}}` → `{"ok": bool, "diff": [{"flag": str, "from": bool, "to": bool}], "restart_required": true, "message": str}`

**Frontend types (added to `web/src/types/index.ts`):** `FlagsResponse`, `EstimateResult`, `EstimateBreakdownRow`, `CapabilityLane`, `CapabilityResponse`, `Recommendation`, `ApplyResult` (exact defs in Task 5).

**Recommender pure fn:** `recommend(estimate: EstimateResult, cap: CapabilityResponse, t: {tClean: number, tPaid: number}): Recommendation`.

---

## File Structure

Backend:
- Create `backend/petridish/providers/capability.py` — capability-table derivation.
- Create `backend/petridish/engine/estimator.py` — flag-override build + tokenize + breakdown.
- Modify `backend/petridish/api/app.py` — add the four endpoints.
- Modify `backend/pyproject.toml` — add optional `tiktoken` dep.
- Tests: `backend/tests/test_capability.py`, `backend/tests/test_estimator.py`, `backend/tests/test_api_labsetup.py`.

Frontend:
- Modify `web/src/types/index.ts` — add the shared types.
- Create `web/src/lib/labSetup.ts` — fetch helpers.
- Create `web/src/lib/recommender.ts` — pure recommender logic.
- Create `web/src/components/labsetup/{LabSetupView,FlagBoard,EstimatePanel,Recommender,CapabilityTable,ApplyBar}.tsx`.
- Modify `web/src/App.tsx` — add `/lab` route; modify `web/src/components/Header.tsx` — nav link.
- Tests: `web/src/lib/recommender.test.ts`, `web/src/components/labsetup/{FlagBoard,EstimatePanel,Recommender}.test.tsx`.

---

## Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
cd /Users/johns/Projects/petri-dish-of-madness
git checkout -b feat/lab-setup-panel
```

---

## Task 1: Capability table module + endpoint

**Files:**
- Create: `backend/petridish/providers/capability.py`
- Modify: `backend/petridish/api/app.py` (add `GET /api/lanes/capability`)
- Test: `backend/tests/test_capability.py`

**Interfaces:**
- Produces: `build_capability_table(order: list[dict], exclude: list[dict], profiles: list[dict], cast_pins: dict[str,str]) -> dict` returning `{"lanes": [...], "cast_pins": {...}}` per the contract.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_capability.py
from petridish.providers.capability import build_capability_table, REASONING_MODELS

ORDER = [
    {"source": "freellmapi", "model": "mistral-small-4-119b", "free": True},
    {"source": "freellmapi", "model": "gpt-oss-120b*", "free": True},
    {"source": "freellmapi", "model": "*", "free": True},
    {"source": "freellmapi", "model": "auto"},
    {"source": "anthropic", "model": "claude-sonnet-5", "free": False},
]
EXCLUDE = [{"source": "freellmapi", "model": "command-a-2"}]
PROFILES = [
    {"name": "mistral-small", "adapter": "openai", "model_id": "mistral-small-4-119b"},
    {"name": "kimi", "adapter": "openai", "model_id": "kimi-k2.6"},
    {"name": "command-a", "adapter": "openai", "model_id": "command-a-2"},
    {"name": "sonnet", "adapter": "anthropic", "model_id": "claude-sonnet-5"},
]

def test_clean_lane_from_curated_order():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "mistral-small")
    assert row["reliability"] == "clean"
    assert row["free"] is True

def test_reasoning_model_flagged_risky():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "kimi")
    assert row["reliability"] == "reasoning"   # kimi-k2.6 in REASONING_MODELS seed

def test_excluded_lane_is_reasoning_not_clean():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "command-a")
    assert row["reliability"] == "reasoning"   # in exclude denylist

def test_paid_lane_flag():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={})
    row = next(r for r in t["lanes"] if r["id"] == "sonnet")
    assert row["free"] is False

def test_cast_pins_passthrough():
    t = build_capability_table(ORDER, EXCLUDE, PROFILES, cast_pins={"Mox": "kimi"})
    assert t["cast_pins"] == {"Mox": "kimi"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_capability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'petridish.providers.capability'`

- [ ] **Step 3: Write the module**

```python
# backend/petridish/providers/capability.py
"""Derive the Lab Setup capability table: per-lane free/paid, context window,
and a clean|reasoning|unknown reliability tag. Reliability encodes the EM-324
knowledge — the curated lanes.yaml `order` is the hand-ranked clean set; the
`exclude` denylist + a seed reasoning-model set are the truncators."""
from __future__ import annotations
import fnmatch
from typing import Any

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
    # Paid if a matching order entry says free: False, or it's a non-freellmapi
    # (direct paid) adapter with no free marker.
    for e in order:
        if _matches(model_id, e.get("model", "")):
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_capability.py -q`
Expected: PASS (5 passed)

- [ ] **Step 5: Add the endpoint**

In `backend/petridish/api/app.py`, after the `GET /api/lanes/registry` handler, add:

```python
@app.get("/api/lanes/capability")
async def get_lanes_capability():
    """Lab Setup capability table: per-lane free/paid + context window +
    clean|reasoning|unknown reliability, derived from lanes.yaml order/exclude
    and the profile legend. Fail-closed: unknown never counts as safe (the UI
    recommender enforces that)."""
    if _config is None or _router is None:
        raise HTTPException(503, "Not initialized")
    from ..providers.capability import build_capability_table
    ar = getattr(_config.world, "adaptive_routing", None)
    order = list(getattr(ar, "order", []) or [])
    exclude = list(getattr(ar, "exclude", []) or [])
    profiles = [
        {"name": p["name"], "adapter": p["adapter"], "model_id": p["model_id"]}
        for p in _router.legend()
    ]
    cast_pins = {}
    for a in world.living_agents():
        cast_pins[a.name] = getattr(a, "profile", None) or getattr(a, "model_profile", "")
    return build_capability_table(order, exclude, profiles, cast_pins)
```

- [ ] **Step 6: Verify the endpoint imports cleanly**

Run: `.venv/bin/python -c "import petridish.api.app"`
Expected: no error (exit 0)

- [ ] **Step 7: Commit**

```bash
git add backend/petridish/providers/capability.py backend/tests/test_capability.py backend/petridish/api/app.py
git commit -m "feat: lab-setup capability table module + /api/lanes/capability

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 2: Prompt-size estimator module

**Files:**
- Create: `backend/petridish/engine/estimator.py`
- Modify: `backend/pyproject.toml` (add `tiktoken` to dependencies)
- Test: `backend/tests/test_estimator.py`

**Interfaces:**
- Consumes: `_assemble_context` from `petridish.agents.runtime`; a live `World` + representative `AgentState`.
- Produces:
  - `count_tokens(text: str) -> tuple[int, str]` → `(tokens, tokenizer_name)`.
  - `estimate_prompt(world, agent, params, overrides: dict[str, bool], prompt_weight_flags: list[str]) -> dict` returning the `POST /api/estimate` success body (minus `ok`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_estimator.py
import pytest
from petridish.engine.estimator import estimate_prompt, count_tokens
from petridish.config.loader import load_config
from petridish.engine.world import World, AgentState, PlaceState

PROMPT_WEIGHT = ["comm", "settlements", "faith"]

def _mini_world():
    cfg = load_config()  # defaults; all Wave-O flags OFF
    places = [PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")]
    agents = [AgentState(id="a1", name="Ada", personality="warm", location="plaza",
                         energy=50, credits=10, mood="calm")]
    w = World(params=cfg.world, places=places, agents=agents)
    return w, cfg.world, agents[0]

def test_count_tokens_returns_positive_and_name():
    n, name = count_tokens("hello world " * 10)
    assert n > 0 and name in ("cl100k_base", "heuristic")

def test_estimate_is_deterministic():
    w, params, agent = _mini_world()
    a = estimate_prompt(w, agent, params, {}, PROMPT_WEIGHT)
    b = estimate_prompt(w, agent, params, {}, PROMPT_WEIGHT)
    assert a["total_input_tokens"] == b["total_input_tokens"]

def test_enabling_comm_increases_tokens():
    w, params, agent = _mini_world()
    off = estimate_prompt(w, agent, params, {"comm": False}, PROMPT_WEIGHT)
    on = estimate_prompt(w, agent, params, {"comm": True}, PROMPT_WEIGHT)
    assert on["total_input_tokens"] > off["total_input_tokens"]

def test_breakdown_has_base_and_active_flag_rows():
    w, params, agent = _mini_world()
    r = estimate_prompt(w, agent, params, {"comm": True}, PROMPT_WEIGHT)
    keys = {row["key"] for row in r["breakdown"]}
    assert "base" in keys and "comm" in keys
    comm_row = next(row for row in r["breakdown"] if row["key"] == "comm")
    assert comm_row["tokens"] > 0   # comm contributes real tokens

def test_estimate_does_not_mutate_world():
    w, params, agent = _mini_world()
    before = list(getattr(w, "pending_whispers", []) or [])
    estimate_prompt(w, agent, params, {"comm": True}, PROMPT_WEIGHT)
    assert list(getattr(w, "pending_whispers", []) or []) == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_estimator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'petridish.engine.estimator'`

- [ ] **Step 3: Write the module**

```python
# backend/petridish/engine/estimator.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_estimator.py -q`
Expected: PASS (5 passed). If `test_estimate_is_deterministic` fails because `_assemble_context` reads a config attr the estimator did not override, extend `_override_params` to cover that attr — the delta test is the guard that the override actually flips the gate.

- [ ] **Step 5: Add the optional dependency**

In `backend/pyproject.toml`, add `tiktoken` to the `[project] dependencies` list (the module already degrades gracefully if it is absent, so this is a soft add for accuracy):

```toml
    "tiktoken>=0.7,<1.0",
```

- [ ] **Step 6: Commit**

```bash
git add backend/petridish/engine/estimator.py backend/tests/test_estimator.py backend/pyproject.toml
git commit -m "feat: lab-setup prompt-size estimator (real build + tokenize)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 3: `/api/estimate` + `/api/config/flags` endpoints

**Files:**
- Modify: `backend/petridish/api/app.py`
- Test: `backend/tests/test_api_labsetup.py`

**Interfaces:**
- Consumes: `estimate_prompt` (Task 2); module globals `_config`, `world`.
- Produces: the two endpoints per the Shared Contracts.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_api_labsetup.py
from fastapi.testclient import TestClient
from petridish.api.app import app

client = TestClient(app)

PROMPT_WEIGHT_MIN = {"comm", "settlements", "faith"}

def test_config_flags_lists_groups_and_baked():
    r = client.get("/api/config/flags")
    assert r.status_code in (200, 503)   # 503 only if uninitialized
    if r.status_code == 200:
        body = r.json()
        assert "baked" in body and "groups" in body
        assert PROMPT_WEIGHT_MIN.issubset(set(body["groups"]["prompt_weight"]))

def test_estimate_returns_total_and_breakdown():
    r = client.post("/api/estimate", json={"overrides": {"comm": True}})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body["ok"] is True
        assert body["total_input_tokens"] > 0
        assert any(row["key"] == "comm" for row in body["breakdown"])

def test_estimate_failure_is_reported_not_faked():
    # An unknown flag must not silently produce a number.
    r = client.post("/api/estimate", json={"overrides": {"not_a_real_flag": True}})
    assert r.status_code in (200, 400, 503)
    if r.status_code == 200:
        body = r.json()
        # unknown flag is ignored (not in prompt_weight) → estimate still ok,
        # but it must never appear in the breakdown as if it cost tokens.
        assert all(row["key"] != "not_a_real_flag" for row in body["breakdown"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_api_labsetup.py -q`
Expected: FAIL — 404 on `/api/config/flags` and `/api/estimate` (routes not defined).

- [ ] **Step 3: Add the flag-inventory constant + endpoints**

Near the top of `backend/petridish/api/app.py` (after imports), add:

```python
# Lab Setup flag inventory (v1). Prompt-weight flags move the estimate; routing/ops
# flags do not change prompt size. `discovery` lives under adaptive_routing.
_PROMPT_WEIGHT_FLAGS = [
    "comm", "settlements", "faith", "war", "factions", "universalization",
    "memory_retrieval", "buildings", "planning", "narrator", "miracles",
    "children", "animals", "image_gen", "healing_house", "charters",
    "chimera_twins", "coherence", "generations",
]
_ROUTING_OPS_FLAGS = [
    "lane_failover", "overflow_lane", "cap_governor", "usage_caps", "cache",
    "discovery",
]

def _flag_baked(params, flag: str) -> bool:
    from ..engine.world import _block_get
    if flag == "discovery":
        ar = getattr(params, "adaptive_routing", None)
        return bool(_block_get(getattr(ar, "discovery", None), "enabled", False))
    return bool(_block_get(getattr(params, flag, None), "enabled", False))
```

Then add the endpoints after `GET /api/config`:

```python
@app.get("/api/config/flags")
async def get_config_flags():
    """Current run's BAKED flag state + group membership. Merges explicit
    world.yaml blocks, absent-defaulted blocks (e.g. faith), and adaptive_routing
    — so 'why now / why not before' is answerable in one place."""
    if _config is None:
        raise HTTPException(503, "Not initialized")
    params = _config.world
    baked = {f: _flag_baked(params, f) for f in _PROMPT_WEIGHT_FLAGS + _ROUTING_OPS_FLAGS}
    return {"baked": baked,
            "groups": {"prompt_weight": _PROMPT_WEIGHT_FLAGS,
                       "routing_ops": _ROUTING_OPS_FLAGS}}


class EstimateBody(BaseModel):
    overrides: dict[str, bool] = Field(default_factory=dict)


@app.post("/api/estimate")
async def post_estimate(body: EstimateBody):
    """Predict the prompt size of a flag combo. Runs the real builder against a
    flag-overridden shallow copy of the live world. Never fabricates a number:
    on any failure returns {ok: false, error}."""
    if _config is None:
        raise HTTPException(503, "Not initialized")
    from ..engine.estimator import estimate_prompt
    agents = world.living_agents()
    if not agents:
        return {"ok": False, "error": "no living agents to estimate against"}
    agent = next((a for a in agents if getattr(a, "cadence_tier", "") == "protagonist"), agents[0])
    try:
        result = estimate_prompt(world, agent, _config.world, body.overrides, _PROMPT_WEIGHT_FLAGS)
    except Exception as exc:  # fix-don't-hide: surface, never fake a number
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, **result}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_api_labsetup.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/petridish/api/app.py backend/tests/test_api_labsetup.py
git commit -m "feat: lab-setup /api/config/flags + /api/estimate endpoints

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 4: `/api/config/apply` endpoint (write staged config + signal restart)

**Files:**
- Modify: `backend/petridish/api/app.py`
- Test: `backend/tests/test_api_labsetup.py` (add cases)

**Interfaces:**
- Produces: `POST /api/config/apply` per the contract. v1 mechanism = write the flag changes to `config/world.yaml` and return `restart_required: true` with the diff (memory `dev-reload-kills-live-sim` forbids in-process `--reload`; an in-process re-bake is a v2 option once `/api/control/reset` is confirmed to re-read config from disk — recorded as an open item, NOT assumed here).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_api_labsetup.py
import ruamel.yaml, io, os, tempfile, shutil

def test_apply_returns_diff_and_restart_required(tmp_path, monkeypatch):
    # Point the writer at a temp copy of world.yaml so the test never edits the
    # real config.
    src = "config/world.yaml"
    dst = tmp_path / "world.yaml"
    shutil.copy(src, dst)
    monkeypatch.setenv("PETRIDISH_WORLD_YAML", str(dst))
    r = client.post("/api/config/apply", json={"overrides": {"comm": True}})
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        body = r.json()
        assert body["restart_required"] is True
        assert isinstance(body["diff"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest backend/tests/test_api_labsetup.py::test_apply_returns_diff_and_restart_required -q`
Expected: FAIL — 404 (route not defined).

- [ ] **Step 3: Add the endpoint (comment-preserving YAML write)**

Add to `backend/petridish/api/app.py`:

```python
class ApplyBody(BaseModel):
    overrides: dict[str, bool] = Field(default_factory=dict)


@app.post("/api/config/apply")
async def post_config_apply(body: ApplyBody):
    """Write the staged flag flips to config/world.yaml (comment-preserving) and
    tell the caller a fresh ./dev restart is required to bake them. Never silent:
    returns the exact diff. Does NOT restart in-process (the --reload ban)."""
    import os
    from ruamel.yaml import YAML
    if _config is None:
        raise HTTPException(503, "Not initialized")
    path = os.environ.get("PETRIDISH_WORLD_YAML", "config/world.yaml")
    # ruamel round-trip loader (typ='rt', the default) — comment-preserving AND
    # safe: it does NOT construct arbitrary Python like PyYAML's unsafe
    # yaml.load(). Never swap this for PyYAML yaml.load()/unsafe_load().
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(path) as fh:
        doc = yaml.load(fh)
    world_block = doc.get("world", doc)
    diff = []
    for flag, val in body.overrides.items():
        block = world_block.get(flag)
        if block is None:
            world_block[flag] = {"enabled": bool(val)}
            diff.append({"flag": flag, "from": False, "to": bool(val)})
            continue
        prev = bool(block.get("enabled", False))
        if prev != bool(val):
            block["enabled"] = bool(val)
            diff.append({"flag": flag, "from": prev, "to": bool(val)})
    with open(path, "w") as fh:
        yaml.dump(doc, fh)
    return {"ok": True, "diff": diff, "restart_required": True,
            "message": "Config written. Restart ./dev to bake the new combo into a fresh run."}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest backend/tests/test_api_labsetup.py -q`
Expected: PASS. If `ruamel.yaml` is not installed, add it to `backend/pyproject.toml` dependencies (`"ruamel.yaml>=0.18"`) and reinstall with `.venv/bin/pip install -e './backend[dev]'`.

- [ ] **Step 5: Full backend gate + commit**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS (existing suite + the new tests; no regressions).

```bash
git add backend/petridish/api/app.py backend/tests/test_api_labsetup.py backend/pyproject.toml
git commit -m "feat: lab-setup /api/config/apply writes staged flags + signals restart

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 5: Frontend types + API lib

**Files:**
- Modify: `web/src/types/index.ts`
- Create: `web/src/lib/labSetup.ts`

**Interfaces:**
- Produces: the shared types + `fetchFlags()`, `postEstimate(overrides)`, `fetchCapability()`, `postApply(overrides)`.

- [ ] **Step 1: Add the types**

Append to `web/src/types/index.ts`:

```typescript
// ── Lab Setup admin panel ──────────────────────────────────────────────
export interface FlagsResponse {
  baked: Record<string, boolean>;
  groups: { prompt_weight: string[]; routing_ops: string[] };
}
export interface EstimateBreakdownRow { key: string; tokens: number; }
export interface EstimateResult {
  ok: boolean;
  error?: string;
  total_input_tokens?: number;
  output_budget?: number;
  tokenizer?: 'cl100k_base' | 'heuristic';
  base_note?: string;
  breakdown?: EstimateBreakdownRow[];
}
export type Reliability = 'clean' | 'reasoning' | 'unknown';
export interface CapabilityLane {
  id: string; provider: string; free: boolean;
  context_window: number | null; reliability: Reliability;
}
export interface CapabilityResponse {
  lanes: CapabilityLane[];
  cast_pins: Record<string, string>;
}
export type Verdict = 'free_clean_ok' | 'free_at_risk' | 'needs_paid';
export interface Recommendation {
  verdict: Verdict;
  banner: string;
  safe: string[];
  risky: string[];
  castPinRisks: { agent: string; lane: string; reason: string }[];
}
export interface ApplyResult {
  ok: boolean;
  diff: { flag: string; from: boolean; to: boolean }[];
  restart_required: boolean;
  message: string;
}
```

- [ ] **Step 2: Write the API lib**

```typescript
// web/src/lib/labSetup.ts
import type {
  FlagsResponse, EstimateResult, CapabilityResponse, ApplyResult,
} from '../types';

const JSON_HEADERS = { 'Content-Type': 'application/json', Accept: 'application/json' };

export async function fetchFlags(): Promise<FlagsResponse> {
  const res = await fetch('/api/config/flags', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`flags ${res.status}`);
  return res.json();
}

export async function postEstimate(overrides: Record<string, boolean>): Promise<EstimateResult> {
  const res = await fetch('/api/estimate', {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ overrides }),
  });
  if (!res.ok) throw new Error(`estimate ${res.status}`);
  return res.json();
}

export async function fetchCapability(): Promise<CapabilityResponse> {
  const res = await fetch('/api/lanes/capability', { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`capability ${res.status}`);
  return res.json();
}

export async function postApply(overrides: Record<string, boolean>): Promise<ApplyResult> {
  const res = await fetch('/api/config/apply', {
    method: 'POST', headers: JSON_HEADERS, body: JSON.stringify({ overrides }),
  });
  if (!res.ok) throw new Error(`apply ${res.status}`);
  return res.json();
}
```

- [ ] **Step 3: Typecheck**

Run: `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`
Expected: exit 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/types/index.ts web/src/lib/labSetup.ts
git commit -m "feat: lab-setup frontend types + api client

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 6: Recommender pure logic

**Files:**
- Create: `web/src/lib/recommender.ts`
- Test: `web/src/lib/recommender.test.ts`

**Interfaces:**
- Consumes: `EstimateResult`, `CapabilityResponse` types.
- Produces: `recommend(estimate, cap, thresholds) -> Recommendation`; `DEFAULT_THRESHOLDS = { tClean: 4500, tPaid: 8000 }`.

- [ ] **Step 1: Write the failing test**

```typescript
// web/src/lib/recommender.test.ts
import { describe, it, expect } from 'vitest';
import { recommend, DEFAULT_THRESHOLDS } from './recommender';
import type { CapabilityResponse, EstimateResult } from '../types';

const CAP: CapabilityResponse = {
  lanes: [
    { id: 'mistral-small', provider: 'openai', free: true, context_window: 128000, reliability: 'clean' },
    { id: 'kimi', provider: 'openai', free: true, context_window: 128000, reliability: 'reasoning' },
    { id: 'mystery', provider: 'openai', free: true, context_window: null, reliability: 'unknown' },
    { id: 'sonnet', provider: 'anthropic', free: false, context_window: 200000, reliability: 'clean' },
  ],
  cast_pins: { Mox: 'kimi', Vesper: 'mistral-small' },
};
const est = (t: number): EstimateResult => ({ ok: true, total_input_tokens: t, output_budget: 1024, breakdown: [] });

describe('recommend', () => {
  it('light combo → free clean OK', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('free_clean_ok');
    expect(r.safe).toContain('mistral-small');
    expect(r.risky).toContain('kimi');
  });
  it('unknown reliability is never safe (fail-closed)', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    expect(r.safe).not.toContain('mystery');
  });
  it('mid combo → free at risk', () => {
    const r = recommend(est(6000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('free_at_risk');
  });
  it('heavy combo → needs paid', () => {
    const r = recommend(est(9000), CAP, DEFAULT_THRESHOLDS);
    expect(r.verdict).toBe('needs_paid');
  });
  it('flags risky cast pins with a reason', () => {
    const r = recommend(est(3000), CAP, DEFAULT_THRESHOLDS);
    const mox = r.castPinRisks.find((c) => c.agent === 'Mox');
    expect(mox?.lane).toBe('kimi');
    expect(mox?.reason).toMatch(/truncat/i);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/lib/recommender.test.ts`
Expected: FAIL — cannot resolve `./recommender`.

- [ ] **Step 3: Write the module**

```typescript
// web/src/lib/recommender.ts
import type { CapabilityResponse, EstimateResult, Recommendation, Verdict } from '../types';

export const DEFAULT_THRESHOLDS = { tClean: 4500, tPaid: 8000 };

export function recommend(
  estimate: EstimateResult,
  cap: CapabilityResponse,
  thresholds: { tClean: number; tPaid: number },
): Recommendation {
  const tokens = estimate.total_input_tokens ?? 0;

  // Fail-closed: only `clean` lanes are ever "safe". reasoning/unknown are risky.
  const safe = cap.lanes.filter((l) => l.reliability === 'clean').map((l) => l.id);
  const risky = cap.lanes.filter((l) => l.reliability !== 'clean').map((l) => l.id);

  let verdict: Verdict;
  let banner: string;
  if (tokens <= thresholds.tClean) {
    verdict = 'free_clean_ok';
    banner = `≈${tokens} input tokens → free clean lanes OK.`;
  } else if (tokens <= thresholds.tPaid) {
    verdict = 'free_at_risk';
    banner = `≈${tokens} → known risk: free lanes may truncate. Run paid/best, or drop a flag.`;
  } else {
    verdict = 'needs_paid';
    banner = `≈${tokens} → free lanes will truncate. Use a paid/best lane or trim the combo.`;
  }

  // Reasoning lanes truncate on the heavy strict-JSON turn regardless of size.
  const riskyIds = new Set(risky);
  const castPinRisks = Object.entries(cap.cast_pins)
    .filter(([, lane]) => riskyIds.has(lane))
    .map(([agent, lane]) => ({
      agent, lane,
      reason: 'reasoning/unproven lane — truncates strict-JSON on the heavy turn; bounce lands on auto',
    }));

  return { verdict, banner, safe, risky, castPinRisks };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/lib/recommender.test.ts`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/recommender.ts web/src/lib/recommender.test.ts
git commit -m "feat: lab-setup recommender logic (fail-closed, threshold verdicts)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 7: CapabilityTable component

**Files:**
- Create: `web/src/components/labsetup/CapabilityTable.tsx`

**Interfaces:**
- Consumes: `CapabilityResponse`.
- Produces: `<CapabilityTable cap={...} />`.

- [ ] **Step 1: Write the component**

```tsx
// web/src/components/labsetup/CapabilityTable.tsx
import type { CapabilityResponse } from '../../types';

const TAG_LABEL: Record<string, string> = {
  clean: '✓ clean', reasoning: '⚠ reasoning', unknown: '? unknown',
};

export function CapabilityTable({ cap }: { cap: CapabilityResponse | null }) {
  if (!cap) return <p>Loading lanes…</p>;
  return (
    <table className="labsetup-capability" aria-label="lane capability">
      <thead>
        <tr><th>Lane</th><th>Provider</th><th>Cost</th><th>Context</th><th>Reliability</th></tr>
      </thead>
      <tbody>
        {cap.lanes.map((l) => (
          <tr key={l.id} data-reliability={l.reliability}>
            <td>{l.id}</td>
            <td>{l.provider}</td>
            <td>{l.free ? 'free' : 'paid'}</td>
            <td>{l.context_window ? `${(l.context_window / 1000) | 0}k` : '—'}</td>
            <td>{TAG_LABEL[l.reliability] ?? l.reliability}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/labsetup/CapabilityTable.tsx
git commit -m "feat: lab-setup capability table component

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 8: FlagBoard component (grouped, baked-vs-pending diff)

**Files:**
- Create: `web/src/components/labsetup/FlagBoard.tsx`
- Test: `web/src/components/labsetup/FlagBoard.test.tsx`

**Interfaces:**
- Consumes: `FlagsResponse`; a `pending: Record<string, boolean>` map and `onToggle(flag)` callback from the parent.
- Produces: `<FlagBoard flags={...} pending={...} onToggle={fn} />` rendering two groups; each row shows a "changed" marker when `pending[flag] !== baked[flag]`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/labsetup/FlagBoard.test.tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FlagBoard } from './FlagBoard';
import type { FlagsResponse } from '../../types';

const FLAGS: FlagsResponse = {
  baked: { comm: false, settlements: true, lane_failover: true },
  groups: { prompt_weight: ['comm', 'settlements'], routing_ops: ['lane_failover'] },
};

describe('FlagBoard', () => {
  it('renders both groups with their flags', () => {
    render(<FlagBoard flags={FLAGS} pending={FLAGS.baked} onToggle={() => {}} />);
    expect(screen.getByText(/prompt-weight/i)).toBeInTheDocument();
    expect(screen.getByText(/routing/i)).toBeInTheDocument();
    expect(screen.getByLabelText('comm')).toBeInTheDocument();
  });
  it('marks a flag changed when pending differs from baked', () => {
    render(<FlagBoard flags={FLAGS} pending={{ ...FLAGS.baked, comm: true }} onToggle={() => {}} />);
    expect(screen.getByTestId('flag-row-comm')).toHaveAttribute('data-changed', 'true');
  });
  it('calls onToggle with the flag name', () => {
    const onToggle = vi.fn();
    render(<FlagBoard flags={FLAGS} pending={FLAGS.baked} onToggle={onToggle} />);
    fireEvent.click(screen.getByLabelText('comm'));
    expect(onToggle).toHaveBeenCalledWith('comm');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/FlagBoard.test.tsx`
Expected: FAIL — cannot resolve `./FlagBoard`.

- [ ] **Step 3: Write the component**

```tsx
// web/src/components/labsetup/FlagBoard.tsx
import type { FlagsResponse } from '../../types';

interface Props {
  flags: FlagsResponse;
  pending: Record<string, boolean>;
  onToggle: (flag: string) => void;
}

function Group({ title, keys, flags, pending, onToggle }: {
  title: string; keys: string[];
} & Props) {
  return (
    <section className="labsetup-flaggroup">
      <h3>{title}</h3>
      {keys.map((flag) => {
        const baked = !!flags.baked[flag];
        const now = pending[flag] ?? baked;
        const changed = now !== baked;
        return (
          <label key={flag} data-testid={`flag-row-${flag}`} data-changed={changed}
                 className="labsetup-flagrow">
            <input type="checkbox" aria-label={flag} checked={now}
                   onChange={() => onToggle(flag)} />
            <span>{flag}</span>
            {changed && <em className="labsetup-changed"> · needs restart</em>}
          </label>
        );
      })}
    </section>
  );
}

export function FlagBoard({ flags, pending, onToggle }: Props) {
  return (
    <div className="labsetup-flagboard">
      <Group title="Prompt-weight flags (move the estimate)"
             keys={flags.groups.prompt_weight}
             flags={flags} pending={pending} onToggle={onToggle} />
      <Group title="Routing / ops flags (no prompt-size change)"
             keys={flags.groups.routing_ops}
             flags={flags} pending={pending} onToggle={onToggle} />
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/FlagBoard.test.tsx`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/labsetup/FlagBoard.tsx web/src/components/labsetup/FlagBoard.test.tsx
git commit -m "feat: lab-setup grouped flag board with baked-vs-pending diff

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 9: EstimatePanel component

**Files:**
- Create: `web/src/components/labsetup/EstimatePanel.tsx`
- Test: `web/src/components/labsetup/EstimatePanel.test.tsx`

**Interfaces:**
- Consumes: `EstimateResult`.
- Produces: `<EstimatePanel estimate={...} loading={bool} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/labsetup/EstimatePanel.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { EstimatePanel } from './EstimatePanel';
import type { EstimateResult } from '../../types';

describe('EstimatePanel', () => {
  it('shows the total and per-flag breakdown', () => {
    const est: EstimateResult = {
      ok: true, total_input_tokens: 3940, output_budget: 1024, tokenizer: 'cl100k_base',
      breakdown: [{ key: 'base', tokens: 2600 }, { key: 'comm', tokens: 340 }],
    };
    render(<EstimatePanel estimate={est} loading={false} />);
    expect(screen.getByText(/3,?940/)).toBeInTheDocument();
    expect(screen.getByText('comm')).toBeInTheDocument();
  });
  it('surfaces an error instead of a fake number', () => {
    const est: EstimateResult = { ok: false, error: 'boom' };
    render(<EstimatePanel estimate={est} loading={false} />);
    expect(screen.getByText(/couldn.t estimate/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/EstimatePanel.test.tsx`
Expected: FAIL — cannot resolve `./EstimatePanel`.

- [ ] **Step 3: Write the component**

```tsx
// web/src/components/labsetup/EstimatePanel.tsx
import type { EstimateResult } from '../../types';

export function EstimatePanel({ estimate, loading }: {
  estimate: EstimateResult | null; loading: boolean;
}) {
  if (loading) return <p>Estimating…</p>;
  if (!estimate) return <p>Toggle a flag to estimate.</p>;
  if (!estimate.ok) {
    return (
      <div className="labsetup-estimate error" role="alert">
        <strong>Couldn’t estimate.</strong> <span>{estimate.error}</span>
      </div>
    );
  }
  const total = estimate.total_input_tokens ?? 0;
  const max = Math.max(1, ...(estimate.breakdown ?? []).map((r) => r.tokens));
  return (
    <div className="labsetup-estimate">
      <div className="labsetup-total">
        ≈ {total.toLocaleString()} input tokens
        <small> · output budget {estimate.output_budget} · {estimate.tokenizer}</small>
      </div>
      <ul className="labsetup-breakdown">
        {(estimate.breakdown ?? []).map((r) => (
          <li key={r.key}>
            <span className="labsetup-bd-key">{r.key}</span>
            <span className="labsetup-bd-bar" style={{ width: `${(r.tokens / max) * 100}%` }} />
            <span className="labsetup-bd-n">{r.tokens.toLocaleString()}</span>
          </li>
        ))}
      </ul>
      {estimate.base_note && <p className="labsetup-note">{estimate.base_note}</p>}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/EstimatePanel.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/labsetup/EstimatePanel.tsx web/src/components/labsetup/EstimatePanel.test.tsx
git commit -m "feat: lab-setup estimate panel with per-flag breakdown

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 10: Recommender component

**Files:**
- Create: `web/src/components/labsetup/Recommender.tsx`
- Test: `web/src/components/labsetup/Recommender.test.tsx`

**Interfaces:**
- Consumes: `Recommendation`.
- Produces: `<RecommenderPanel rec={...} />`.

- [ ] **Step 1: Write the failing test**

```tsx
// web/src/components/labsetup/Recommender.test.tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { RecommenderPanel } from './Recommender';
import type { Recommendation } from '../../types';

const REC: Recommendation = {
  verdict: 'free_at_risk',
  banner: '≈6000 → known risk: free lanes may truncate.',
  safe: ['mistral-small'],
  risky: ['kimi'],
  castPinRisks: [{ agent: 'Mox', lane: 'kimi', reason: 'reasoning lane — truncates' }],
};

describe('RecommenderPanel', () => {
  it('shows the verdict banner', () => {
    render(<RecommenderPanel rec={REC} />);
    expect(screen.getByText(/known risk/i)).toBeInTheDocument();
  });
  it('lists safe and risky lanes and cast-pin risks', () => {
    render(<RecommenderPanel rec={REC} />);
    expect(screen.getByText('mistral-small')).toBeInTheDocument();
    expect(screen.getByText(/Mox.*kimi/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/Recommender.test.tsx`
Expected: FAIL — cannot resolve `./Recommender`.

- [ ] **Step 3: Write the component**

```tsx
// web/src/components/labsetup/Recommender.tsx
import type { Recommendation } from '../../types';

export function RecommenderPanel({ rec }: { rec: Recommendation | null }) {
  if (!rec) return null;
  return (
    <div className="labsetup-recommender" data-verdict={rec.verdict}>
      <p className="labsetup-verdict" role="status">{rec.banner}</p>
      <div className="labsetup-lanesets">
        <div><h4>Safe</h4><ul>{rec.safe.map((l) => <li key={l}>{l}</li>)}</ul></div>
        <div><h4>Risky</h4><ul>{rec.risky.map((l) => <li key={l}>{l}</li>)}</ul></div>
      </div>
      {rec.castPinRisks.length > 0 && (
        <div className="labsetup-pinrisks">
          <h4>Cast pins at risk on this combo</h4>
          <ul>
            {rec.castPinRisks.map((c) => (
              <li key={c.agent}>{c.agent} → {c.lane}: {c.reason}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run src/components/labsetup/Recommender.test.tsx`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add web/src/components/labsetup/Recommender.tsx web/src/components/labsetup/Recommender.test.tsx
git commit -m "feat: lab-setup recommender panel (verdict + lane sets + pin risks)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 11: ApplyBar component

**Files:**
- Create: `web/src/components/labsetup/ApplyBar.tsx`

**Interfaces:**
- Consumes: the pending-vs-baked diff (computed by the parent) + an `onApply()` callback + optional `result: ApplyResult`.
- Produces: `<ApplyBar diff={...} onApply={fn} result={...} busy={bool} />`.

- [ ] **Step 1: Write the component**

```tsx
// web/src/components/labsetup/ApplyBar.tsx
import type { ApplyResult } from '../../types';

interface DiffRow { flag: string; from: boolean; to: boolean; }

export function ApplyBar({ diff, onApply, result, busy }: {
  diff: DiffRow[]; onApply: () => void; result: ApplyResult | null; busy: boolean;
}) {
  const nothing = diff.length === 0;
  return (
    <div className="labsetup-applybar">
      {nothing ? (
        <span>No pending changes.</span>
      ) : (
        <ul className="labsetup-diff">
          {diff.map((d) => (
            <li key={d.flag}>{d.flag}: {String(d.from)} → <strong>{String(d.to)}</strong></li>
          ))}
        </ul>
      )}
      <button disabled={nothing || busy} onClick={onApply}>
        {busy ? 'Applying…' : 'Apply & restart'}
      </button>
      {result && (
        <p className="labsetup-applymsg" role="status">
          {result.message}{result.restart_required ? ' (restart ./dev to bake)' : ''}
        </p>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run: `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`
Expected: exit 0.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/labsetup/ApplyBar.tsx
git commit -m "feat: lab-setup apply bar (diff preview + apply & restart)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 12: LabSetupView container + route + nav

**Files:**
- Create: `web/src/components/labsetup/LabSetupView.tsx`
- Modify: `web/src/App.tsx` (add `<Route path="/lab" ...>`)
- Modify: `web/src/components/Header.tsx` (add a nav link to `/lab`)

**Interfaces:**
- Consumes: all Task 5–11 pieces + `recommend`/`DEFAULT_THRESHOLDS` from Task 6.
- Produces: `<LabSetupView />` — the wired page.

- [ ] **Step 1: Write the container**

```tsx
// web/src/components/labsetup/LabSetupView.tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { FlagsResponse, EstimateResult, CapabilityResponse, ApplyResult } from '../../types';
import { fetchFlags, postEstimate, fetchCapability, postApply } from '../../lib/labSetup';
import { recommend, DEFAULT_THRESHOLDS } from '../../lib/recommender';
import { FlagBoard } from './FlagBoard';
import { EstimatePanel } from './EstimatePanel';
import { RecommenderPanel } from './Recommender';
import { CapabilityTable } from './CapabilityTable';
import { ApplyBar } from './ApplyBar';

export function LabSetupView() {
  const [flags, setFlags] = useState<FlagsResponse | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [estimate, setEstimate] = useState<EstimateResult | null>(null);
  const [estimating, setEstimating] = useState(false);
  const [cap, setCap] = useState<CapabilityResponse | null>(null);
  const [applyResult, setApplyResult] = useState<ApplyResult | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchFlags().then((f) => { setFlags(f); setPending({ ...f.baked }); }).catch(() => {});
    fetchCapability().then(setCap).catch(() => {});
  }, []);

  // Re-estimate whenever the pending combo changes (prompt-weight flags only).
  useEffect(() => {
    if (!flags) return;
    const overrides: Record<string, boolean> = {};
    for (const f of flags.groups.prompt_weight) overrides[f] = pending[f] ?? !!flags.baked[f];
    setEstimating(true);
    postEstimate(overrides)
      .then(setEstimate).catch((e) => setEstimate({ ok: false, error: String(e) }))
      .finally(() => setEstimating(false));
  }, [flags, pending]);

  const onToggle = useCallback((flag: string) => {
    setPending((p) => ({ ...p, [flag]: !(p[flag] ?? (flags?.baked[flag] ?? false)) }));
  }, [flags]);

  const diff = useMemo(() => {
    if (!flags) return [];
    return Object.keys(flags.baked)
      .filter((f) => (pending[f] ?? flags.baked[f]) !== flags.baked[f])
      .map((f) => ({ flag: f, from: !!flags.baked[f], to: !!pending[f] }));
  }, [flags, pending]);

  const rec = useMemo(
    () => (estimate?.ok && cap ? recommend(estimate, cap, DEFAULT_THRESHOLDS) : null),
    [estimate, cap],
  );

  const onApply = useCallback(async () => {
    const overrides: Record<string, boolean> = {};
    for (const d of diff) overrides[d.flag] = d.to;
    setBusy(true);
    try { setApplyResult(await postApply(overrides)); }
    finally { setBusy(false); }
  }, [diff]);

  if (!flags) return <div className="labsetup"><p>Loading Lab Setup…</p></div>;
  return (
    <div className="labsetup">
      <h2>Lab Setup — compose the next run</h2>
      <div className="labsetup-grid">
        <FlagBoard flags={flags} pending={pending} onToggle={onToggle} />
        <div className="labsetup-centerpiece">
          <EstimatePanel estimate={estimate} loading={estimating} />
          <RecommenderPanel rec={rec} />
        </div>
        <CapabilityTable cap={cap} />
      </div>
      <ApplyBar diff={diff} onApply={onApply} result={applyResult} busy={busy} />
    </div>
  );
}
```

- [ ] **Step 2: Wire the route**

In `web/src/App.tsx`, add the import and a route inside the existing `<Routes>` block:

```tsx
import { LabSetupView } from './components/labsetup/LabSetupView';
// … inside <Routes>:
<Route path="/lab" element={<LabSetupView />} />
```

- [ ] **Step 3: Add the nav link**

In `web/src/components/Header.tsx`, add a nav link to `/lab` alongside the existing route links (follow the existing link markup/pattern in that file — a `<NavLink to="/lab">Lab</NavLink>` or the same anchor pattern the header already uses).

- [ ] **Step 4: Typecheck + full frontend gate**

Run: `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`
Expected: exit 0.

Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run`
Expected: PASS — the full suite (baseline ≈1684) + the new Lab Setup tests, no regressions.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/labsetup/LabSetupView.tsx web/src/App.tsx web/src/components/Header.tsx
git commit -m "feat: lab-setup view wired to /lab route + header nav

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Task 13: Full gate + PR

- [ ] **Step 1: Backend gate**

Run: `.venv/bin/python -m pytest backend/tests/ -q`
Expected: PASS (no regressions; new capability/estimator/api tests green).

- [ ] **Step 2: Frontend typecheck + tests**

Run: `cd web && /usr/local/bin/node node_modules/typescript/bin/tsc -b --force`
Run: `cd web && /usr/local/bin/node node_modules/vitest/vitest.mjs run`
Expected: exit 0 / all pass.

- [ ] **Step 3: Manual smoke (optional, live)**

Start `./dev`, open `http://localhost:5173/lab`, toggle `comm`, confirm the estimate + verdict update and the diff shows in the apply bar.

- [ ] **Step 4: Open the PR**

```bash
git push -u origin feat/lab-setup-panel
gh pr create --base main --title "feat: Lab Setup admin panel (flag combos → prompt-size estimate + model recommendation)" --body "Implements docs/superpowers/specs/2026-07-15-admin-panel-lab-setup-design.md. Grouped flag board, real-builder estimator, curation-driven recommender + capability table, apply-and-restart. v1; observed-overlay deferred to v2."
```

---

## Deferred to v2 (out of scope here)

- Observed-size overlay: instrument run history to record real prompt sizes + per-lane truncation rates; show predicted-vs-actual; auto-calibrate `T_CLEAN`/`T_PAID` and populate `observed_truncation_rate`.
- Feed real recent-events/memory into the estimator base (v1 base is a labeled lower bound).
- In-process apply (re-bake via `/api/control/reset`) if confirmed to re-read config from disk; v1 writes config + signals a `./dev` restart.
- `seed` snapshot option for the estimator (v1 uses the current live world).

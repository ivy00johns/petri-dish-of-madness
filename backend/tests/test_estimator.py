"""Lab Setup — prompt-size estimator (Task 2).

Proves `estimate_prompt` predicts the request size a flag combo generates by
running the REAL prompt builder (`_assemble_context`) against a
flag-overridden shallow copy of the live world, then tokenizing — the
drift-proof centerpiece of the Lab Setup panel. Covers: token counting
degrades gracefully without tiktoken, the estimate is deterministic, enabling
a prompt-weight flag (comm) measurably grows the prompt, the breakdown
reports a `base` row plus one row per ACTIVE flag, and — the constructor's
one real mutation risk — the call never pops the live world's queued god
whispers (it must pass god_whispers=[], never None; see estimator.py).

`_mini_world` adapts the brief's constructor calls to the TRUE dataclasses:
`AgentState` requires `profile` (the model-profile name, no default) — the
brief's literal omitted it. `World(params, places, agents)` and `PlaceState`
match the brief as written (checked against test_god_console.py's `_world()`
idiom and the real definitions in engine/world.py).
"""
from __future__ import annotations

import pytest

from petridish.engine.estimator import estimate_prompt, count_tokens
from petridish.config.loader import load_config
from petridish.engine.world import World, AgentState, PlaceState

PROMPT_WEIGHT = ["comm", "settlements", "faith"]


def _mini_world():
    # load_config() reads the live world.yaml (comm currently ships enabled
    # there per the multi-city sign-off commit) — irrelevant here: estimate_prompt
    # always overrides every PROMPT_WEIGHT flag explicitly (both the "all off"
    # base and the requested combo), so live config state on those three blocks
    # never leaks into the estimate.
    cfg = load_config()
    places = [PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social")]
    agents = [AgentState(id="a1", name="Ada", personality="warm", profile="mock",
                          location="plaza", energy=50, credits=10, mood="calm")]
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
    # Seed a REAL queued god whisper so this test can actually catch a
    # god_whispers=None regression: _build_tokens shallow-copies the world
    # (copy.copy), so the copy's `pending_whispers` dict is the SAME object as
    # the live world's — a None-triggered pop() would drain it for real, on
    # the live world, from an estimate call. An empty queue can't detect that.
    w, params, agent = _mini_world()
    w.pending_whispers[agent.id] = ["a real god whisper — must survive"]
    before = {k: list(v) for k, v in w.pending_whispers.items()}

    estimate_prompt(w, agent, params, {"comm": True}, PROMPT_WEIGHT)

    after = {k: list(v) for k, v in w.pending_whispers.items()}
    assert after == before

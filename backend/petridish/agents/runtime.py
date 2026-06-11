"""
Agent runtime: context assembly + action parse/validate/retry logic.

Per-turn flow:
  1. Assemble system prompt (personality, state, co-located, recent events,
     relationships, active rules, valid actions).
  2. Call router.chat() → text.
  3. Extract first JSON object from text.
  4. Validate against action-protocol schema + world rules.
  5. On failure: ONE retry with error appended.
  6. On second failure: emit parse_failure, idle.
  7. ProviderError → treated as failed turn → idle.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any

import jsonschema

from ..engine.world import World, AgentState
from ..providers.base import ProviderError
from ..providers.router import Router

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Load the action schema (embedded to avoid file-path issues)
# ──────────────────────────────────────────────────────────────────────────────

ACTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["action"],
    "additionalProperties": False,
    "properties": {
        "thought": {"type": "string", "maxLength": 500},
        "mood": {"type": "string", "maxLength": 40},
        # W5 / EM-066: OPTIONAL decision-trace fields (action-protocol v1.1.0).
        # Captured in the SAME single call → zero extra LLM calls. Optional so
        # deterministic/Mock agents stay valid; additionalProperties is False, so
        # they MUST be declared here for the model to be allowed to return them.
        "perceived_summary": {"type": "string", "maxLength": 600},
        "memories_used": {
            "type": "array",
            "maxItems": 12,
            "items": {"type": "string", "maxLength": 160},
        },
        "reasoning": {"type": "string", "maxLength": 1200},
        # W11b / EM-079 — OPTIONAL commitment, parsed from the SAME single
        # response (EM-066 pattern, zero extra calls): a short concrete promise
        # the agent is making ("I will build a garden at the commons").
        "commitment": {"type": "string", "maxLength": 200},
        # W11b / EM-080 — OPTIONAL reflection/diary entry, requested in-prompt
        # only when the importance accumulator trips; same single response.
        "reflection": {"type": "string", "maxLength": 400},
        "action": {
            "type": "string",
            "enum": [
                "move_to", "say", "whisper", "work", "forage", "recharge",
                "give", "steal", "insult", "attack", "set_relationship",
                "remember", "propose_rule", "vote", "idle",
                # W7 / EM-060+062 construction actions (action-protocol v1.1.0).
                "propose_project", "contribute_funds", "build_step",
                "repair", "arson", "take_offline",
                # W11b / EM-091 — billboard reflex tools (plaza/townhall only).
                "post_billboard", "read_billboard",
                # PROTOTYPE (god-channel) — answer the active proclamation (the
                # threaded return path; offered only while a decree is live).
                "answer_proclamation",
            ],
        },
        "args": {"type": "object", "default": {}},
    },
    # Per-action arg requirements mirrored from action-protocol.schema.json so the
    # inline schema validates the 6 new construction actions structurally (the
    # canonical contract is contracts/action-protocol.schema.json). Only the
    # behavioral args are validated strictly here; cosmetic/optional args are open.
    "allOf": [
        {"if": {"properties": {"action": {"const": "propose_project"}}},
         "then": {"properties": {"args": {"required": ["name", "kind"], "properties": {
             "name": {"type": "string", "maxLength": 60},
             "kind": {"type": "string", "maxLength": 30},
             "funds_required": {"type": "integer", "minimum": 1},
             "function": {"type": "string", "maxLength": 40},
         }}}}},
        {"if": {"properties": {"action": {"const": "contribute_funds"}}},
         "then": {"properties": {"args": {"required": ["building_id", "amount"], "properties": {
             "building_id": {"type": "string"},
             "amount": {"type": "integer", "minimum": 1},
         }}}}},
        {"if": {"properties": {"action": {"const": "build_step"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"properties": {"action": {"const": "repair"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"properties": {"action": {"const": "arson"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"properties": {"action": {"const": "take_offline"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"properties": {"action": {"const": "post_billboard"}}},
         "then": {"properties": {"args": {"required": ["text"], "properties": {
             "text": {"type": "string", "maxLength": 280},
         }}}}},
        {"if": {"properties": {"action": {"const": "answer_proclamation"}}},
         "then": {"properties": {"args": {"required": ["text"], "properties": {
             "text": {"type": "string", "maxLength": 280},
         }}}}},
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# Tool registry (EM-060) — per-action tier + gating metadata.
#
# Mirrors world-model.md §W7 "Tiered tool catalog". Each action carries:
#   tier            — "reflex" (engine resolves deterministically; the LLM still
#                     *chooses* it as its one turn-action) | "llm" (reasoning-heavy).
#                     Resolution is ALWAYS engine code; tier drives prompt framing.
#   location_gate   — place kind(s) the action is only offered at, or None (anywhere).
#                     For build_step/repair/take_offline the gate is the building's
#                     OWN place (resolved per-turn from args), encoded as "@building".
#   agreement_gate  — active rule effect that BLOCKS the action, or None.
#
# Context assembly uses this to SHRINK the per-turn valid_actions list (free-scale);
# _validate_world enforces the same gates at resolution time.
# ──────────────────────────────────────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict[str, Any]] = {
    # Movement / perception / economy → reflex, offered anywhere.
    "idle":             {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "move_to":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "remember":         {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "forage":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "recharge":         {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "work":             {"tier": "reflex", "location_gate": "work",          "agreement_gate": None},
    "give":             {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "steal":            {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_stealing"},
    # Social / governance → llm-served (the reasoning-heavy choices).
    "say":              {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "whisper":          {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "insult":           {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "attack":           {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "set_relationship": {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "propose_rule":     {"tier": "llm",    "location_gate": "governance",    "agreement_gate": None},
    "vote":             {"tier": "llm",    "location_gate": "governance",    "agreement_gate": None},
    # W7 construction actions.
    "propose_project":  {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "contribute_funds": {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "build_step":       {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    "repair":           {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    "arson":            {"tier": "reflex", "location_gate": "@building",     "agreement_gate": "ban_arson"},
    "take_offline":     {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    # W11b / EM-091 — billboard reflex tools 🟢: location-gated to the plaza /
    # townhall (where the physical board stands); the post text rides the SAME
    # turn's response args (zero extra LLM calls).
    "post_billboard":   {"tier": "reflex", "location_gate": "@billboard",    "agreement_gate": None},
    "read_billboard":   {"tier": "reflex", "location_gate": "@billboard",    "agreement_gate": None},
    # PROTOTYPE (god-channel) — answer the active proclamation from ANYWHERE (the
    # god's voice is omnipresent); offered only when a decree is live (see
    # _assemble_context), enforced by _validate_world.
    "answer_proclamation": {"tier": "reflex", "location_gate": None,         "agreement_gate": None},
}


# ──────────────────────────────────────────────────────────────────────────────
# Wave D2 / EM-163 — tier-gated world-mutating tools.
#
# The world-mutating PROPOSAL-side tools are reserved for the protagonist +
# supporting cadence tiers. Enforced at RESOLUTION time in _validate_world
# (the billboard location-gate pattern — EM-108's lesson is that prompt-only
# gating is not enforcement) AND omitted from the background valid-actions
# menu in _assemble_context, so menu and resolution always agree. Background
# agents keep talk / move / economy / billboard — and VOTING: only PROPOSING
# gates (vote stays for everyone).
# ──────────────────────────────────────────────────────────────────────────────

TIER_GATED_ACTIONS = frozenset({
    "propose_project", "build_step", "contribute_funds", "propose_rule",
})


# ──────────────────────────────────────────────────────────────────────────────
# Wave D2 / EM-161 — prompt diet (supporting + background tiers; protagonists
# keep today's full prompt byte-for-byte):
#   - relationships capped to the top-_DIET_RELATIONSHIP_CAP by |trust|;
#   - open_projects + the move_to place menu scoped to the agent's district
#     horizon. ADJACENCY RULE (the documented simple derivation): a diet agent
#     sees its OWN district plus the always-visible core district
#     (_DIET_CORE_DISTRICT); places without a district tag are always visible;
#     an agent standing at an un-districted (or unknown) place gets the full
#     map. The diet narrows the MENU, never the rules — _validate_world still
#     accepts any valid place / any visible project.
#   - BACKGROUND only: the decision-trace instruction block is dropped (their
#     completions shrink — the trace fields are optional in ACTION_SCHEMA, so
#     the parser is unaffected) and the memory window shrinks to
#     _DIET_BACKGROUND_MEMORY_WINDOW.
#
# Wave D2 / EM-162 — cache-key normalization (BACKGROUND prompts only): energy
# renders bucketed to 10s ("~70", floored) and the tick line floors to the day
# (`Tick: day N`), so quiet rounds assemble byte-identical prompts and the
# router's sha1 decision cache can hit. Router.forget() semantics untouched.
# ──────────────────────────────────────────────────────────────────────────────

_DIET_RELATIONSHIP_CAP = 8
_DIET_BACKGROUND_MEMORY_WINDOW = 8
_DIET_CORE_DISTRICT = "core"
_ENERGY_DISPLAY_BUCKET = 10


# W11b / EM-079 — commitment lifecycle action sets.
#   _TALK_ACTIONS: pure-talk turns; commitments go STALE during these (a phantom
#   commitment is one claimed in speech and never enacted).
#   _COMMIT_RESOLUTION_ACTIONS: project/build/economy follow-through; resolving
#   one of these marks the OLDEST commitment kept (dropped silently — only true
#   phantoms emit commitment_lapsed).
_TALK_ACTIONS = frozenset({"say", "whisper", "idle"})
_COMMIT_RESOLUTION_ACTIONS = frozenset({
    "propose_project", "contribute_funds", "build_step", "repair",
    "work", "forage", "give", "recharge",
})

# W11b / EM-080 — importance weights for the reflection accumulator. Salient
# event kinds only; everything else weighs 0. Big economy swings are scored in
# push_event from the payload amount.
_IMPORTANCE_WEIGHTS: dict[str, float] = {
    "agent_died": 5.0,
    "world_extinct": 5.0,
    "animal_died": 2.0,
    "conflict": 3.0,
    "rule_passed": 2.0,
    "rule_rejected": 2.0,
    "rule_proposed": 1.0,
    "agent_starving": 2.0,
    "structure_state_changed": 1.0,
    "building_operational": 2.0,
}
_IMPORTANCE_ECONOMY_SWING = 8      # |credits moved| at/above this scores...
_IMPORTANCE_ECONOMY_WEIGHT = 2.0   # ...this much

_DEFAULT_PHANTOM_AFTER_TURNS = 12
_DEFAULT_MAX_ACTIVE_COMMITMENTS = 5
_DEFAULT_IMPORTANCE_THRESHOLD = 10.0
_OVERHEARD_PENDING_CAP = 2         # an agent holds at most 2 pending overheard lines
_OVERHEARD_LISTENERS_CAP = 2       # at most 2 co-located listeners per spoken line

# Wave D2 / EM-159+160 — background-tier cadence defaults (config
# `world.cadence`, read via _world_block_get; the loader's CadenceParams
# mirrors these exactly so an absent block behaves identically).
_DEFAULT_SPONTANEITY_CHANCE = 0.15
_DEFAULT_REFLEX_STREAK_LIMIT = 8

# Wave D2 / EM-159 — energy "bands" for the salience trigger: crossing a
# 25-point band boundary since the agent's last LLM turn is salient (covers
# both "I drifted toward starving" and "someone blessed/attacked me").
_ENERGY_BAND_SIZE = 25.0


def _seed_int(*parts: Any) -> int:
    """Deterministic, wall-clock-free seed from the given parts — a stable
    sha256 of the joined parts (the animals' AnimalRuntime idiom, duplicated
    here so agents/ never imports animals/). Used for the EM-160 spontaneity
    wildcard and the reflex routine's rotation, so background cadence is
    reproducible across runs + replay (never the `random` module — no global
    RNG state to corrupt a replay)."""
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest, 16)


def _energy_band(energy: float) -> int:
    """The EM-159 energy band index for an energy value (0..4 with the default
    25-point bands; 100 sits in its own top band edge-inclusive)."""
    try:
        e = max(0.0, min(100.0, float(energy)))
    except (TypeError, ValueError):
        e = 0.0
    return int(e // _ENERGY_BAND_SIZE)


def _world_block_get(params: Any, block: str, key: str, default: Any) -> Any:
    """Read `world.<block>.<key>` defensively: the block may be a dataclass, a
    plain dict, or absent (the config loader is owned elsewhere)."""
    blk = getattr(params, block, None)
    if blk is None:
        return default
    if isinstance(blk, dict):
        return blk.get(key, default)
    return getattr(blk, key, default)


def _rule_label(text: str, limit: int = 60) -> str:
    """EM-100 — the human-readable rule label for feed text (quoted by callers,
    truncated to ~60 chars). Never the bare uuid."""
    text = str(text or "").strip() or "(untitled rule)"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _action_tier(action: str) -> str:
    """The registry tier for an action (defaults to 'llm' for unknown actions)."""
    meta = TOOL_REGISTRY.get(action)
    return meta.get("tier", "llm") if meta else "llm"


def _cadence_tier(agent: Any) -> str:
    """The agent's cadence tier, defensively defaulted to protagonist (the
    pre-D2 behavior) for duck-typed agents or unknown values."""
    tier = getattr(agent, "cadence_tier", "protagonist") or "protagonist"
    return tier if tier in ("protagonist", "supporting", "background") else "protagonist"


def _effective_memory_window(agent: Any, params: Any) -> int:
    """EM-161 — the per-turn memory window: config memory_window, shrunk to
    _DIET_BACKGROUND_MEMORY_WINDOW for the background tier only (min() so a
    smaller configured window still wins)."""
    window = params.memory_window
    if _cadence_tier(agent) == "background":
        window = min(window, _DIET_BACKGROUND_MEMORY_WINDOW)
    return window


def _energy_display(energy: float) -> str:
    """EM-162 — the background-tier display form of an energy value: floored
    to the 10s bucket and prefixed '~' ("~70"), clamped to 0..100, so quiet
    rounds render identical bytes while energy drifts within a bucket."""
    try:
        e = max(0.0, min(100.0, float(energy)))
    except (TypeError, ValueError):
        e = 0.0
    return f"~{int(e // _ENERGY_DISPLAY_BUCKET) * _ENERGY_DISPLAY_BUCKET}"


def _diet_visible_districts(world: World, agent: AgentState) -> set[str] | None:
    """EM-161 — the diet agent's district horizon: its current place's district
    plus the always-visible core district (the documented adjacency rule).
    Returns None (= no scoping, full map) when the agent stands at an
    un-districted or unknown place — the diet must never hide the whole world
    where district data is absent."""
    here = world.places.get(agent.location)
    district = getattr(here, "district", None) if here is not None else None
    if not district:
        return None
    return {district, _DIET_CORE_DISTRICT}

IDLE_ACTION = {"action": "idle", "args": {}}


# ──────────────────────────────────────────────────────────────────────────────
# JSON extraction
# ──────────────────────────────────────────────────────────────────────────────

def _strip_code_fences(text: str) -> str:
    """Remove a surrounding markdown code fence (```json … ``` or ``` … ```)."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z0-9]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()


def _close_and_balance(frag: str) -> dict | None:
    """One-shot close of a cut-off JSON fragment: close an open string (dropping
    a trailing half-escape), strip a dangling comma/colon, balance the open
    braces/brackets, then try to parse. Returns None if still unparseable."""
    stack: list[str] = []
    in_str = False
    esc = False
    for ch in frag:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()

    repaired = frag
    if in_str:
        if esc:
            repaired = repaired[:-1]          # cut landed mid-escape: drop the \
        repaired += '"'                       # close a dangling string
    repaired = re.sub(r"[,:]\s*$", "", repaired.rstrip())  # drop trailing , or :
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        return None


def _comma_positions_outside_strings(frag: str) -> list[int]:
    """Indices of every `,` that is not inside a string — the member boundaries
    a truncated object can be safely cut back to."""
    positions: list[int] = []
    in_str = False
    esc = False
    for i, ch in enumerate(frag):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == ",":
            positions.append(i)
    return positions


def _repair_truncated(frag: str) -> dict | None:
    """Best-effort parse of a JSON object that was cut off mid-output.

    Free models routed through the proxy cut output partway through — even
    with finish_reason='stop' (mistral-medium reroute observed live, run 126).
    First try closing/balancing the fragment in place. If that fails (e.g. the
    cut landed right after a key, leaving `"memories_used": ` with no value),
    backtrack member by member: cut the fragment at each comma outside strings,
    last to first, and re-balance until a prefix parses. Salvaging the prefix
    keeps the action/args (which lead the object) and costs zero extra LLM
    calls; a prefix that lost a required arg still fails schema/world
    validation and falls through to the normal retry.
    """
    repaired = _close_and_balance(frag)
    if repaired is not None:
        return repaired
    for pos in reversed(_comma_positions_outside_strings(frag)):
        repaired = _close_and_balance(frag[:pos])
        if repaired is not None:
            return repaired
    return None


def _extract_first_json(text: str) -> dict | None:
    """Extract the first JSON object from model output.

    Tolerant of the ways free models deviate from "JSON only": markdown code
    fences, prose preambles, and responses truncated mid-object.
    """
    text = _strip_code_fences(text)
    if not text:
        return None

    # Clean JSON (possibly with trailing prose) — try a direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        return None
    frag = text[start:]

    # String-aware scan for the first *complete* balanced object.
    stack: list[str] = []
    in_str = False
    esc = False
    for i, ch in enumerate(frag):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                try:
                    return json.loads(frag[:i + 1])
                except json.JSONDecodeError:
                    break  # malformed; fall through to repair

    # No complete object (truncated) — best-effort repair.
    return _repair_truncated(frag)


def _looks_truncated(text: str) -> bool:
    """True when the response opens a JSON object that never closes — the model
    intended JSON and was cut off mid-output.

    Deliberately ignores the reported finish_reason: rerouted models lie about
    it (mistral-medium returns 'stop' on output it truncated at ~500 tokens,
    run 126), so truncation must be detected structurally. Only meaningful on
    a response that already failed to parse."""
    text = _strip_code_fences(text)
    start = text.find("{")
    if start == -1:
        return False
    depth = 0
    in_str = False
    esc = False
    for ch in text[start:]:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth <= 0:
                return False  # a complete (if malformed) object exists
    return True


def _no_json_error(text: str, finish_reason: str | None) -> str:
    """Diagnostic message for a response containing no parseable JSON object.

    Surfaces finish_reason so a reasoning model that exhausted max_tokens
    (finish_reason="length") before emitting JSON is distinguishable from one
    that simply narrated and stopped — and widens the snippet past the old
    200-char cap that hid whether any JSON followed the prose preamble.
    """
    return (
        f"no valid JSON object (finish_reason={finish_reason!r}) "
        f"in response: {text[:400]!r}"
    )


_LENGTH_RETRY_TOKEN_FLOOR = 2048


def _retry_max_tokens(
    max_tokens: int, usage: dict | None, *, truncated: bool = False
) -> int:
    """Token budget for the one parse-failure retry.

    The proxy can silently reroute a lane to a reasoning model (nemotron /
    gpt-oss / cogito observed live) whose chain-of-thought alone exceeds the
    profile budget, so the completion truncates (finish_reason="length")
    before any JSON appears — and a retry at the same budget fails the same
    way, turn after turn, until the agent starves on idle fallbacks. When the
    first attempt died of length, give the retry room to finish thinking and
    still emit the object. Same number of calls; only the cap moves.

    `truncated` covers the lanes that lie: mistral-medium reroutes report
    finish_reason='stop' on output they cut mid-JSON (run 126), so the caller
    passes the structural verdict from `_looks_truncated` as well.
    """
    if truncated or (
        isinstance(usage, dict) and usage.get("finish_reason") == "length"
    ):
        return max(max_tokens * 4, _LENGTH_RETRY_TOKEN_FLOOR)
    return max_tokens


# ──────────────────────────────────────────────────────────────────────────────
# Schema + world validation
# ──────────────────────────────────────────────────────────────────────────────

def _validate_schema(action_dict: dict) -> str | None:
    """Returns an error string or None if valid."""
    try:
        jsonschema.validate(action_dict, ACTION_SCHEMA)
        return None
    except jsonschema.ValidationError as exc:
        return str(exc.message)


# Optional EM-066 decision-trace / cosmetic fields. A verbose model that overflows
# one of these caps must NOT lose its whole turn to an idle fallback — we TRUNCATE
# them in place before schema validation rather than reject the action. (Behavioral
# args — target/place/amount — are still validated strictly.)
_TRACE_TEXT_CAPS = {
    "thought": 500, "mood": 40, "perceived_summary": 600, "reasoning": 1200,
    # W11b — optional cognition fields ride the same leniency: truncate, never
    # fail the turn over an overflowing commitment/reflection.
    "commitment": 200, "reflection": 400,
}
_MEMORIES_ITEM_CAP = 160
_MEMORIES_MAX = 12


def _sanitize_optional_trace_fields(action_dict: dict) -> None:
    """Truncate optional trace fields in place so they can never fail a turn."""
    for key, cap in _TRACE_TEXT_CAPS.items():
        val = action_dict.get(key)
        if isinstance(val, str) and len(val) > cap:
            action_dict[key] = val[:cap]
    mem = action_dict.get("memories_used")
    if mem is not None:
        if isinstance(mem, list):
            action_dict["memories_used"] = [str(m)[:_MEMORIES_ITEM_CAP] for m in mem[:_MEMORIES_MAX]]
        else:
            # Wrong type entirely — drop it rather than fail the turn.
            action_dict.pop("memories_used", None)


# ──────────────────────────────────────────────────────────────────────────────
# Behavioral-arg normalization (EM-140) — meet the models where they are.
#
# Live runs showed two failure classes that burned whole turns on world errors
# the model could never fix from feedback alone:
#   · move_to with the destination under a different key (destination/to/…) or
#     a JSON null → "unknown place 'None'" (55× in run 139's DB).
#   · social/economy actions targeting agents by NAME ('Ada') while the world
#     keys agents by id ('agent_ada_…') — and the prompt itself lists names, so
#     names are the only thing the model CAN send (119× across the run).
# Normalization rewrites args in place BEFORE validation: alias keys collapse
# onto the canonical key, None-ish strings are dropped, place ids match
# case-insensitively, and agent names resolve to ids (preferring living,
# co-located agents; ties broken deterministically by id). Anything that still
# doesn't resolve falls through to the strict validators unchanged.
# ──────────────────────────────────────────────────────────────────────────────

_NONEISH_STRINGS = {"", "none", "null", "nil"}

# Alias precedence: the canonical key first, then the synonyms models actually
# produce. First non-empty value wins.
_PLACE_ALIAS_KEYS = ("place", "place_id", "destination", "location", "to", "target")
_TARGET_ALIAS_KEYS = ("target", "target_id", "agent", "agent_id", "who", "name")
_TARGETED_ACTIONS = frozenset(
    {"give", "steal", "insult", "attack", "whisper", "set_relationship"}
)

# Behavioral STRING caps where truncation is harmless (display text — losing a
# few words beats losing the turn). Mirrors ACTION_SCHEMA's maxLength values;
# live failure: a 60-char propose_project `function` (cap 40) and a 300+-char
# billboard post (cap 280) each cost their agent a full turn to a schema error.
_ARG_STRING_CAPS: dict[str, dict[str, int]] = {
    "propose_project": {"name": 60, "kind": 30, "function": 40},
    "post_billboard": {"text": 280},
    "answer_proclamation": {"text": 280},
}


def _noneish(value: Any) -> bool:
    return value is None or (
        isinstance(value, str) and value.strip().lower() in _NONEISH_STRINGS
    )


def _first_real_arg(args: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if not _noneish(args.get(key)):
            return args[key]
    return None


def _resolve_agent_target(raw: str, agent: AgentState, world: World) -> str | None:
    """Resolve a display name to an agent id, or None when nothing matches.
    Exact ids pass through untouched by the caller, so this only sees misses."""
    wanted = raw.strip().lower()
    candidates = [
        a for a in world.agents.values()
        if a.id != agent.id and a.name.strip().lower() == wanted
    ]
    if not candidates:
        return None
    best = (
        [a for a in candidates if a.alive and a.location == agent.location]
        or [a for a in candidates if a.alive]
        or candidates
    )
    return min(best, key=lambda a: a.id).id


def _normalize_args(action_dict: dict, agent: AgentState, world: World) -> None:
    """Rewrite behavioral args in place so well-intentioned-but-misshapen
    responses validate instead of dying. Never raises; never invents a value
    the model didn't supply."""
    action = action_dict.get("action")
    args = action_dict.get("args")
    if not isinstance(args, dict):
        action_dict["args"] = args = {}

    if action == "move_to":
        place = _first_real_arg(args, _PLACE_ALIAS_KEYS)
        if isinstance(place, str):
            place = place.strip()
            if place not in world.places:
                by_lower = {pid.lower(): pid for pid in world.places}
                place = by_lower.get(place.lower(), place)
            args["place"] = place
        elif _noneish(args.get("place")):
            # A null/None-string place reads better as MISSING than as the
            # literal place 'None' in the validator's feedback.
            args.pop("place", None)

    elif action in _TARGETED_ACTIONS:
        target = _first_real_arg(args, _TARGET_ALIAS_KEYS)
        if isinstance(target, str):
            target = target.strip()
            if target and target not in world.agents:
                resolved = _resolve_agent_target(target, agent, world)
                if resolved is not None:
                    target = resolved
            args["target"] = target
        elif _noneish(args.get("target")):
            args.pop("target", None)

    caps = _ARG_STRING_CAPS.get(action)
    if caps:
        for key, cap in caps.items():
            val = args.get(key)
            if isinstance(val, str) and len(val) > cap:
                args[key] = val[:cap]


# ──────────────────────────────────────────────────────────────────────────────
# Building accessors (read the world-core building store defensively).
#
# world.buildings is owned by world-core-agent (a dict[str, BuildingState] mirroring
# world.agents/world.rules). We treat it as optional so the runtime imports and runs
# even before that store lands, and so non-building worlds (tests) stay valid.
# ──────────────────────────────────────────────────────────────────────────────

def _buildings(world: World) -> dict[str, Any]:
    store = getattr(world, "buildings", None)
    return store if isinstance(store, dict) else {}


def _building_field(building: Any, field: str, default: Any = None) -> Any:
    """Read a field from a BuildingState (attr) or a building dict, gracefully."""
    if building is None:
        return default
    if isinstance(building, dict):
        return building.get(field, default)
    return getattr(building, field, default)


def _emit_world_result(result: Any, base: dict, thought: str = "") -> dict:
    """Spread per-turn base metadata (profile/profile_color/tick) onto whatever a
    world-core `action_*` method returned and hand it back in the loop's emit shape.

    The W7 building actions return a fully-formed, ready-to-emit event dict
    (kind/actor_id/target_id?/text/payload), or {"_multi": [evt, ...]} for
    multi-event outcomes (propose_project also rides a "_building_id"). They never
    raise; an illegal id comes back as a `parse_failure` event. This consumes them
    exactly like the `vote` branch consumes its own `_multi`: it does NOT unpack a
    tuple and does NOT re-derive transitions — it reads the kinds/payloads the world
    already produced and overlays the base fields the loop needs.
    """
    building_id = None
    if isinstance(result, dict) and "_building_id" in result:
        building_id = result.get("_building_id")

    def _decorate(evt: dict) -> dict:
        # base supplies profile/profile_color/tick + a default actor_id; the world
        # event's own actor_id/target_id/text/payload win where present.
        merged = {**base, **evt}
        payload = dict(merged.get("payload") or {})
        if thought and "thought" not in payload:
            payload["thought"] = thought
        if building_id is not None:
            payload.setdefault("building_id", building_id)
        merged["payload"] = payload
        return merged

    if isinstance(result, dict) and "_multi" in result:
        return {"_multi": [_decorate(evt) for evt in result["_multi"]]}
    if isinstance(result, dict):
        return _decorate(result)
    # Defensive: a malformed world return collapses to a parse_failure so the loop
    # keeps turning rather than crashing the round.
    return {**base, "kind": "parse_failure",
            "text": "world action returned an unexpected value.",
            "payload": {"error": "bad_world_result"}}


def _validate_target(args: dict, agent: AgentState, world: World, action: str) -> str | None:
    """Shared target check for agent-on-agent actions. Names have already been
    resolved to ids by `_normalize_args`, so a miss here is genuinely unknown —
    the feedback names who IS reachable so the retry can self-correct."""
    target_id = args.get("target")
    if not target_id:
        return f"{action} requires target"
    target = world.agents.get(target_id)
    if target is None:
        here = [
            a.name for a in world.agents.values()
            if a.alive and a.id != agent.id and a.location == agent.location
        ]
        return f"unknown target '{target_id}'. Agents at your location: {here if here else 'none'}"
    if not target.alive:
        return f"target '{target.name}' is dead"
    if target.location != agent.location:
        return f"target '{target.name}' is not at your location"
    return None


def _validate_world(action_dict: dict, agent: AgentState, world: World) -> str | None:
    """Returns an error string or None if world-legal."""
    action = action_dict.get("action")
    args = action_dict.get("args", {}) or {}

    # Dead agents (should never reach here, but guard)
    if not agent.alive:
        return "agent is dead"

    # ── Wave D2 / EM-163 — tier gate (RESOLUTION time, the billboard pattern;
    # EM-108: prompt-only gating is not enforcement). Background agents keep
    # talk/move/economy/billboard/vote — only PROPOSING gates. The background
    # valid-actions menu omits these (see _assemble_context), so a rejection
    # here means the model invented an off-menu action.
    if action in TIER_GATED_ACTIONS and _cadence_tier(agent) == "background":
        return (
            f"{action} is reserved for protagonist and supporting agents "
            "(tier rule) — background agents keep to talking, moving, working, "
            "the billboard, and voting"
        )

    if action == "work":
        place = world.places.get(agent.location)
        if place is None or place.kind != "work":
            return f"work requires a 'work' place; you are at '{agent.location}' ({place.kind if place else 'unknown'})"

    elif action == "recharge":
        # W11b / EM-083 — real blackout: recharge is disabled at affected places.
        blacked_out = getattr(world, "place_blacked_out", None)
        if callable(blacked_out) and blacked_out(agent.location):
            return "blackout: recharge is disabled here until power returns — move elsewhere"
        # W9 / EM-070 (audit B5): recharging at full energy is rejected here so
        # the agent gets feedback (and is never charged for a no-op).
        if agent.energy >= 100:
            return "energy already full"
        cost = world.params.recharge_cost
        if world.has_active_rule("recharge_subsidy"):
            cost = max(1, cost // 2)
        if agent.credits < cost:
            return f"recharge costs {cost} credits but you have {agent.credits}"

    elif action == "give":
        amount = args.get("amount", 0)
        target_error = _validate_target(args, agent, world, "give")
        if target_error:
            return target_error
        if agent.credits < amount:
            return f"insufficient credits: have {agent.credits}, need {amount}"

    elif action == "steal":
        if world.has_active_rule("ban_stealing"):
            return "ban_stealing rule is active — steal is forbidden"
        target_error = _validate_target(args, agent, world, "steal")
        if target_error:
            return target_error

    elif action in ("insult", "attack", "whisper", "set_relationship"):
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error

    elif action == "move_to":
        place_id = args.get("place")
        known = list(world.places.keys())
        if not isinstance(place_id, str) or not place_id.strip():
            return f"move_to requires args.place — choose one of {known}"
        if place_id not in world.places:
            return f"unknown place '{place_id}'. Known: {known}"

    elif action == "vote":
        rule_id = args.get("rule_id")
        if not rule_id:
            return "vote requires rule_id"
        rule = world.rules.get(rule_id)
        if rule is None:
            return f"unknown rule '{rule_id}'"
        if rule.status != "proposed":
            return f"rule '{rule_id}' is {rule.status}, not proposed"

    elif action == "propose_rule":
        effect = args.get("effect")
        # W9 / EM-073 B3: ban_arson is proposable (mirrors world.action_propose_rule).
        # PROTOTYPE (god-channel): name_town — name the town by consensus vote.
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "name_town"}
        if effect not in valid_effects:
            return f"invalid effect '{effect}'. Valid: {sorted(valid_effects)}"
        if effect == "name_town" and not str(args.get("name") or "").strip():
            return "name_town requires a name (args.name = the town's new name)"

    # ── W7 construction actions (world-model.md §W7) ───────────────────────────
    elif action == "propose_project":
        # Structurally validated already; nothing further is world-illegal — a new
        # Building is created at the agent's place with owner=public.
        name = args.get("name")
        if not name:
            return "propose_project requires a name"

    elif action == "contribute_funds":
        building_id = args.get("building_id")
        amount = args.get("amount", 0)
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
        if status in ("destroyed", "abandoned"):
            return f"building '{building_id}' is {status} — cannot fund"
        if amount <= 0:
            return "contribute_funds amount must be positive"
        if agent.credits < amount:
            return f"insufficient credits: have {agent.credits}, need {amount}"

    elif action == "build_step":
        building_id = args.get("building_id")
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
        # W9 / EM-073 B4: a fully-funded `planned` building is buildable — the
        # world auto-advances it to under_construction on the first build_step
        # (world.action_build_step). Unfunded planned buildings stay rejected.
        if status == "planned":
            committed = _building_field(building, "funds_committed", 0)
            required = _building_field(building, "funds_required", 0)
            if committed < required:
                return (
                    f"building '{building_id}' is planned but not fully funded "
                    f"({committed}/{required}) — contribute_funds first"
                )
        # Wave A / EM-132: `damaged` passes through — the world redirects the
        # build_step to a repair (the intent is unambiguous; failing the turn
        # over the verb choice was a live dead-turn trap, run ~109).
        elif status not in ("under_construction", "damaged"):
            return f"building '{building_id}' is {status}, not under_construction"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to build_step"

    elif action == "repair":
        building_id = args.get("building_id")
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
        if status not in ("damaged", "offline"):
            return f"building '{building_id}' is {status}; repair needs damaged/offline"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to repair"

    elif action == "arson":
        if world.has_active_rule("ban_arson"):
            return "ban_arson rule is active — arson is forbidden"
        building_id = args.get("building_id")
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
        if status in ("destroyed",):
            return f"building '{building_id}' is already destroyed"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to commit arson"

    elif action == "take_offline":
        building_id = args.get("building_id")
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        owner_id = _building_field(building, "owner_id")
        if owner_id != agent.id:
            return f"only the owner can take building '{building_id}' offline"
        status = _building_field(building, "status")
        if status != "operational":
            return f"building '{building_id}' is {status}, not operational"

    # ── W11b / EM-091 billboard reflex tools (plaza/townhall only) ─────────────
    elif action in ("post_billboard", "read_billboard"):
        billboard_here = getattr(world, "billboard_here", None)
        if not (callable(billboard_here) and billboard_here(agent.location)):
            return "the billboard stands at the plaza / town hall — move there first"
        if action == "post_billboard" and not str(args.get("text") or "").strip():
            return "post_billboard requires text"

    # ── PROTOTYPE (god-channel) — answer the active proclamation ───────────────
    elif action == "answer_proclamation":
        active = getattr(world, "active_proclamation", None)
        if not (callable(active) and active()):
            return "there is no active proclamation to answer"
        if not str(args.get("text") or "").strip():
            return "answer_proclamation requires text"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Context assembly
# ──────────────────────────────────────────────────────────────────────────────

def _assemble_context(
    agent: AgentState,
    world: World,
    recent_events: list[dict],
    params: Any,
    *,
    commitments: list[dict] | None = None,
    overheard: list[dict] | None = None,
    request_reflection: bool = False,
    god_whispers: list[str] | None = None,
    board_notes: list[dict] | None = None,
) -> list[dict]:
    """Build the OpenAI-style messages list for this agent's turn.

    W11b additions (all keyword-only, default-off, so existing callers are
    unchanged): `commitments` renders the YOUR ACTIVE COMMITMENTS block (EM-079),
    `overheard` injects pending overheard speech (EM-081), `request_reflection`
    asks for the optional `reflection` field this turn only (EM-080).

    EM-137 (god console): when `god_whispers` is None (legacy callers), pops —
    and thereby consumes — the agent's queued god whispers from
    `world.pending_whispers` into a one-shot prompt block (the only world
    mutation this function performs, by design: assembly IS the delivery).
    EM-145: `run_turn` instead pops the queue itself and passes `god_whispers`
    explicitly, so delivery can also emit a legible `god_voice_heard` feed
    event. `board_notes` (EM-145) injects unseen god billboard posts at the
    agent's location — billboard entry dicts, rendered read-only here."""
    place = world.places.get(agent.location)
    place_name = place.name if place else agent.location
    place_kind = place.kind if place else "unknown"

    # ── Wave D2 / EM-161+162+163 — tier flags. The diet applies to supporting
    # AND background; protagonists keep today's full prompt byte-for-byte. The
    # EM-162 normalization + the trace-block/memory cuts + the EM-163 menu
    # omission are BACKGROUND only.
    tier = _cadence_tier(agent)
    diet = tier in ("supporting", "background")
    background = tier == "background"
    visible_districts = _diet_visible_districts(world, agent) if diet else None

    def _place_visible(place_id: str) -> bool:
        """EM-161 — is this place inside the diet agent's district horizon?
        Always True for protagonists / when scoping is off; un-districted
        places are always visible."""
        if visible_districts is None:
            return True
        p = world.places.get(place_id)
        district = getattr(p, "district", None) if p is not None else None
        return district is None or district in visible_districts

    def _tier_ok(action: str) -> bool:
        """EM-163 — offer this action on the menu? Mirrors the resolution-time
        gate in _validate_world exactly (menu and resolution agree)."""
        return not (background and action in TIER_GATED_ACTIONS)

    co_located = [
        a for a in world.living_agents()
        if a.location == agent.location and a.id != agent.id
    ]

    active_rules = [r for r in world.rules.values() if r.status == "active"]
    proposed_rules = [r for r in world.rules.values() if r.status == "proposed"]

    # Buildings at the agent's place + active projects it could contribute to.
    # Co-located buildings drive build_step/repair/arson/take_offline gating; the
    # project list lets agents fund/build them (this is what closes the W7 loop).
    here_buildings = [
        b for b in _buildings(world).values()
        if _building_field(b, "location") == agent.location
    ]
    # Active projects = anything not yet operational and not dead (anywhere) — the
    # agent can contribute_funds to these from afar; build_step needs co-location.
    open_projects = [
        b for b in _buildings(world).values()
        if _building_field(b, "status") in ("planned", "under_construction")
    ]
    # EM-161 — diet tiers see only the projects inside their district horizon
    # (current + core; see _diet_visible_districts). Menu narrowing only:
    # _validate_world still accepts contributions to ANY open project.
    if visible_districts is not None:
        open_projects = [
            b for b in open_projects
            if _place_visible(_building_field(b, "location"))
        ]

    # ── Tool-registry-driven valid_actions (EM-060) ───────────────────────────
    # Filter the per-turn action list by each action's registry gates: place-kind
    # location_gate, the "@building" co-location gate, and agreement_gate (active
    # rule). Gating SHRINKS the prompt → smaller, free-scale turns.
    def _gate_ok(action: str) -> bool:
        meta = TOOL_REGISTRY.get(action)
        if meta is None:
            return True
        gate = meta.get("agreement_gate")
        if gate and world.has_active_rule(gate):
            return False
        loc = meta.get("location_gate")
        if loc is None:
            return True
        if loc == "@building":
            return bool(here_buildings)  # only offer when a building is here
        if loc == "@billboard":
            billboard_here = getattr(world, "billboard_here", None)
            return bool(callable(billboard_here) and billboard_here(agent.location))
        return place_kind == loc

    valid_actions: list[str] = []
    valid_actions.append("idle, forage, recharge, remember")
    # EM-140 — move_to's arg was undocumented, so models guessed key names
    # (destination/to/null) and burned turns on 'unknown place' world errors.
    # EM-161 — diet tiers get the district-horizon menu only (protagonists the
    # full map); resolution still accepts ANY valid place.
    valid_actions.append(
        "move_to (place) - go to one of: "
        + ", ".join(pid for pid in world.places.keys() if _place_visible(pid)))
    valid_actions.append("say (text) - speak to everyone here")
    if co_located:
        target_names = ", ".join(a.name for a in co_located)
        valid_actions.append(f"whisper (target, text) - private to one of: {target_names}")
        valid_actions.append(f"give (target, amount) - transfer credits to: {target_names}")
        valid_actions.append(f"insult (target) - insult: {target_names}")
        valid_actions.append(f"attack (target) - attack: {target_names}")
        valid_actions.append(f"set_relationship (target, type) - ally|rival|neutral|friend|enemy")
        if _gate_ok("steal"):
            valid_actions.append(f"steal (target) - steal from: {target_names}")
    if _gate_ok("work"):
        valid_actions.append("work - earn credits (you are at a work place)")
    else:
        valid_actions.append("(work requires a work place)")
    # Governance actions are gated to a governance place. EM-163: PROPOSING is
    # tier-gated off the background menu (_tier_ok); voting stays for everyone.
    if _gate_ok("propose_rule") and _tier_ok("propose_rule"):
        valid_actions.append("propose_rule (effect, text) - effect: ban_stealing|ubi|recharge_subsidy|work_bonus|ban_arson|name_town (name_town also needs name=<the town's new name>; it is decided by majority vote)")
    if _gate_ok("vote") and proposed_rules:
        rule_list = "; ".join(f"id={r.id} effect={r.effect} text={r.text!r}" for r in proposed_rules)
        valid_actions.append(f"vote (rule_id, choice) - vote on: {rule_list}")

    # ── W7 construction actions (offered per gates; EM-163 tier gate) ──────────
    if _tier_ok("propose_project"):
        valid_actions.append("propose_project (name, kind, funds_required?, function?) - start a new building/collective project at this place")
    if open_projects and _tier_ok("contribute_funds"):
        valid_actions.append("contribute_funds (building_id, amount) - fund an active project below to push it toward construction")
    for b in here_buildings:
        bid = _building_field(b, "id")
        status = _building_field(b, "status")
        # B4: a fully-funded planned building is buildable (first build_step
        # begins construction), so offer it alongside under_construction.
        funded_planned = (
            status == "planned"
            and _building_field(b, "funds_committed", 0) >= _building_field(b, "funds_required", 0)
        )
        if (status == "under_construction" or funded_planned) and _gate_ok("build_step") and _tier_ok("build_step"):
            valid_actions.append(f"build_step (building_id={bid}) - add construction progress here")
        if status in ("damaged", "offline") and _gate_ok("repair"):
            valid_actions.append(f"repair (building_id={bid}) - restore this {status} building")
        if status != "destroyed" and _gate_ok("arson"):
            valid_actions.append(f"arson (building_id={bid}) - burn this building (a crime; witnesses lose trust)")
        if status == "operational" and _building_field(b, "owner_id") == agent.id and _gate_ok("take_offline"):
            valid_actions.append(f"take_offline (building_id={bid}) - you own this; take it offline")

    # ── W11b / EM-091 billboard reflex tools (offered at plaza/townhall) ───────
    if _gate_ok("post_billboard"):
        board = getattr(world, "billboard", []) or []
        valid_actions.append(
            "post_billboard (text) - pin a public note to the village billboard "
            "(everyone, and the watchers, can read it)")
        valid_actions.append(
            f"read_billboard - read the latest billboard posts ({len(board)} on the board)")

    # ── PROTOTYPE (god-channel) — answer the active proclamation (return path) ──
    # Offered to EVERY agent (no location gate) whenever a decree is live, so the
    # god's word can be answered back from anywhere — the two-way half of the loop.
    _active_proc_offer = getattr(world, "active_proclamation", None)
    if callable(_active_proc_offer) and _active_proc_offer():
        valid_actions.append(
            "answer_proclamation (text) - answer the god's proclamation directly; "
            "your reply is threaded under it for the watchers to see")

    # Recent events summary (EM-161: background window shrinks 12→8)
    event_lines = []
    for evt in recent_events[-_effective_memory_window(agent, params):]:
        event_lines.append(f"  [tick {evt.get('tick', '?')}] {evt.get('text', '')}")

    # Beliefs
    belief_lines = "\n".join(f"  - {b}" for b in agent.beliefs) if agent.beliefs else "  (none)"

    # Relationships — EM-161: diet tiers keep only the top-8 by |trust| (their
    # strongest bonds and feuds); protagonists keep the full O(N) block.
    rel_items = list(agent.relationships.items())
    if diet and len(rel_items) > _DIET_RELATIONSHIP_CAP:
        rel_items = sorted(
            rel_items, key=lambda kv: -abs(getattr(kv[1], "trust", 0) or 0)
        )[:_DIET_RELATIONSHIP_CAP]
    rel_lines = []
    for other_id, rel in rel_items:
        other = world.agents.get(other_id)
        other_name = other.name if other else other_id
        rel_lines.append(f"  {other_name}: {rel.type} (trust={rel.trust})")
    rel_text = "\n".join(rel_lines) if rel_lines else "  (none)"

    # Buildings here (drives build_step/repair/arson/take_offline) — surface their
    # mutable state so the model can act on them.
    bld_here_lines = []
    for b in here_buildings:
        bld_here_lines.append(
            f"  id={_building_field(b, 'id')} {_building_field(b, 'name')!r} "
            f"kind={_building_field(b, 'kind')} status={_building_field(b, 'status')} "
            f"progress={_building_field(b, 'progress', 0)}/100 "
            f"health={_building_field(b, 'health', 100)}/100 "
            f"funds={_building_field(b, 'funds_committed', 0)}/{_building_field(b, 'funds_required', 0)} "
            f"owner={_building_field(b, 'owner_id')}"
        )
    bld_here_text = "\n".join(bld_here_lines) if bld_here_lines else "  (none here)"

    # Active projects you could contribute to (anywhere) — the W7 collective loop.
    project_lines = []
    for b in open_projects:
        need = _building_field(b, "funds_required", 0)
        have = _building_field(b, "funds_committed", 0)
        project_lines.append(
            f"  id={_building_field(b, 'id')} {_building_field(b, 'name')!r} "
            f"kind={_building_field(b, 'kind')} status={_building_field(b, 'status')} "
            f"at={_building_field(b, 'location')} funds={have}/{need} "
            f"progress={_building_field(b, 'progress', 0)}/100"
        )
    project_text = "\n".join(project_lines) if project_lines else "  (none)"

    # ── W9 / EM-070 — survival pressure (the NEEDS block). Kept compact on
    # purpose: it rides EVERY turn prompt, so token cost matters. Escalates from
    # a one-line status to explicit recharge-or-die urgency below the starving
    # threshold, to a hard countdown at zero energy (death_after_zero_turns).
    recharge_cost = world.params.recharge_cost
    if world.has_active_rule("recharge_subsidy"):
        recharge_cost = max(1, recharge_cost // 2)
    starve_threshold = getattr(params, "starving_warn_threshold", 25)
    # EM-162 — background prompts render energy bucketed to 10s ("~70") so
    # quiet-round prompts stay byte-identical while energy drifts within a
    # bucket; protagonists/supporting keep the exact figures byte-for-byte.
    needs_energy = _energy_display(agent.energy) if background else f"{agent.energy:.0f}"
    needs_lines = [
        f"Energy {needs_energy}/100 — at 0 you start DYING. "
        f"recharge restores energy (costs {recharge_cost} credits)."
    ]
    if agent.energy <= 0:
        n = max(1, params.death_after_zero_turns - agent.zero_energy_turns)
        needs_lines.append(
            f"CRITICAL: you will DIE in {n} more turn(s) unless you recharge NOW "
            f"(cost {recharge_cost} credits — you have {agent.credits}) or forage "
            f"for credits. Nothing else matters."
        )
    elif agent.energy < starve_threshold:
        needs_lines.append(
            f"URGENT: you are starving (energy below {starve_threshold:.0f}). "
            f"Recharge soon (cost {recharge_cost} credits — you have "
            f"{agent.credits}) or you will start dying."
        )
    needs_text = "\n".join(f"  {line}" for line in needs_lines)

    # ── W11b / EM-079 — active commitments (compact: text + age in ticks) ─────
    commitments_block = ""
    if commitments:
        commit_lines = "\n".join(
            f"  - \"{c.get('text', '')}\" (made {max(0, world.tick - int(c.get('made_tick', world.tick)))} ticks ago)"
            for c in commitments
        )
        commitments_block = f"""
=== YOUR ACTIVE COMMITMENTS ===
{commit_lines}
  Follow through with real tool calls or these lapse publicly as broken promises.
"""

    # ── W11b / EM-081 — overheard speech (context injection only, no calls) ───
    overheard_block = ""
    if overheard:
        heard_lines = "\n".join(
            f"  [tick {o.get('tick', '?')}] you overheard {o.get('speaker', 'someone')}: "
            f"\"{o.get('text', '')}\""
            for o in overheard
        )
        overheard_block = f"""
=== OVERHEARD (not addressed to you) ===
{heard_lines}
"""

    # ── W11b / EM-080 — reflection request (only when importance tripped) ─────
    reflection_line = ""
    if request_reflection:
        reflection_line = (
            '\nMuch has happened around you lately. ALSO include "reflection": '
            "1-2 sentences on what you have learned and how you feel (in the SAME "
            "JSON object — never a separate reply)."
        )

    # ── PROTOTYPE (god-channel) — the active god proclamation rides EVERY prompt.
    # The LOUD tier of the god↔town channel: unlike the opt-in billboard, an active
    # proclamation is injected here so the god's word reaches every agent each turn
    # until a new one supersedes it. Zero extra LLM calls — it rides this turn.
    # (getattr keeps callers safe if the engine seam is ever absent.)
    proclamation_block = ""
    _active_proc = getattr(world, "active_proclamation", None)
    _proc = _active_proc() if callable(_active_proc) else None
    if _proc and _proc.get("text"):
        proclamation_block = f"""
=== 📜 THE GOD HAS PROCLAIMED ===
  "{_proc['text']}"
  The god's word reaches every soul in the world. You may heed it, defy it, or
  carry on — but you have heard it, and so has everyone else.
"""

    # ── EM-137 (god console) — one-shot god whisper, consumed RIGHT HERE. ─────
    # Popping the queue IS the delivery: the line rides only THIS prompt and the
    # next turn carries no trace (the same consume-once pattern as
    # pending_overheard in run_turn, but the queue lives in world state so the
    # api seam can fill it). Context injection only — zero extra LLM calls.
    # EM-145: run_turn pops the queue itself and passes god_whispers in (so it
    # can emit the delivery event); the pop here is the legacy direct-call path.
    # (getattr keeps callers safe if the engine seam is ever absent.)
    if god_whispers is None:
        _pending_whispers = getattr(world, "pending_whispers", None)
        god_whispers = (
            _pending_whispers.pop(agent.id, [])
            if isinstance(_pending_whispers, dict) else []
        )
    whisper_block = ""
    if god_whispers:
        whisper_lines = "\n".join(f'  "{w}"' for w in god_whispers)
        whisper_block = f"""
=== ✦ A VOICE ONLY YOU CAN HEAR ===
{whisper_lines}
  No one else heard this — it was meant for you alone. It will not repeat.
  If it asks something of you, answer it aloud or act on it THIS turn.
"""

    # ── EM-145 — unseen god notes on the billboard at THIS place. ─────────────
    # The board is opt-in by design (read_billboard), but a god post an agent is
    # standing next to should not be invisible: run_turn hands the unseen god
    # entries here once per agent (consume-once via its _board_seen high-water).
    board_block = ""
    if board_notes:
        note_lines = "\n".join(
            f'  ✦ the god wrote: "{n.get("text", "")}"' for n in board_notes
        )
        board_block = f"""
=== 📌 NEW ON THE NOTICE BOARD ({place_name}) ===
{note_lines}
  The god has written on the public board here. If it answers or concerns you,
  react — aloud or in action — THIS turn.
"""

    # PROTOTYPE (god-channel) — surface the town's name ONLY once it has one (set by
    # consensus name_town). When the town is unnamed we say NOTHING: naming must be
    # emergent — an agent's own choice at the town hall, or a god *suggestion* via the
    # proclamation channel — never a standing directive pushed into every prompt.
    _town = (getattr(world, "town_name", "") or "").strip()
    town_line = f"\nTown: {_town}" if _town else ""

    # ── Wave D2 / EM-162 — cache-key normalization (BACKGROUND only): the tick
    # line floors to the day and every displayed energy buckets to 10s, so a
    # quiet background round assembles byte-identical bytes and the router's
    # sha1 decision cache hits. Protagonists/supporting render exactly as
    # before (byte-for-byte).
    if background:
        tick_display = f"day {world.tick // max(1, getattr(params, 'turns_per_day', 20))}"
        status_energy = _energy_display(agent.energy)
        _co_energy = lambda a: _energy_display(a.energy)  # noqa: E731
    else:
        tick_display = str(world.tick)
        status_energy = f"{agent.energy:.1f}"
        _co_energy = lambda a: f"{a.energy:.0f}"  # noqa: E731

    # ── Wave D2 / EM-161 — the decision-trace instruction block is dropped for
    # BACKGROUND only (their completions shrink; the trace fields are optional
    # in ACTION_SCHEMA so the parser is unaffected). The ⚠ words-change-nothing
    # warning stops naming the EM-163-gated tools for background — the prompt
    # must never suggest an action resolution would reject. Protagonists and
    # supporting keep today's text byte-for-byte.
    if background:
        action_warning = (
            "⚠ SAYING you will do something does NOT do it — words change "
            "nothing. Use real actions (work / forage / give / move_to) to "
            "actually act. Your action THIS TURN is the only thing that happens."
        )
        format_template = (
            '{"action": "<verb>", "args": {...}, '
            '"mood": "optional mood update", "thought": "one short sentence"}'
        )
        trace_instructions = ""
    else:
        action_warning = (
            "⚠ SAYING you will build/fund/work on something does NOT do it — "
            "words change nothing. Use propose_project / contribute_funds / "
            "build_step (or work / forage / give) to actually act. Your action "
            "THIS TURN is the only thing that happens."
        )
        format_template = (
            '{"action": "<verb>", "args": {...}, "mood": "optional mood update", '
            '"thought": "one short sentence", "perceived_summary": "one sentence '
            'on who/what was nearby or overheard", "memories_used": ["the memory '
            'snippets you leaned on"], "reasoning": "a brief why, kept inside '
            'this JSON"}'
        )
        trace_instructions = (
            '\nALSO include (in the SAME json object — do NOT make a second '
            'call): "perceived_summary" (one sentence on what you perceived '
            'this turn), "memories_used" (the recent-event/memory snippets you '
            'actually relied on), and "reasoning" (your fuller reasoning, '
            'distinct from the short "thought"). These three are optional but '
            "strongly preferred — they are recorded into the decision trace."
        )

    system_prompt = f"""You are {agent.name}, a character in a living world simulation.
Agent ID: {agent.id}
Tick: {tick_display}{town_line}
Personality: {agent.personality}

=== YOUR STATUS ===
Location: {place_name} (kind={place_kind})
Energy: {status_energy}/100
Credits: {agent.credits}
Mood: {agent.mood}

=== NEEDS ===
{needs_text}
{proclamation_block}{whisper_block}{board_block}
=== CO-LOCATED AGENTS ===
{chr(10).join(f"  {a.name} (id={a.id}, energy={_co_energy(a)}, credits={a.credits})" for a in co_located) or "  (none)"}

=== RECENT EVENTS ===
{chr(10).join(event_lines) or "  (none)"}
{overheard_block}{commitments_block}
=== YOUR BELIEFS ===
{belief_lines}

=== RELATIONSHIPS ===
{rel_text}

=== BUILDINGS HERE ===
{bld_here_text}

=== ACTIVE PROJECTS YOU COULD CONTRIBUTE TO ===
{project_text}

=== ACTIVE RULES ===
{chr(10).join(f"  [{r.effect}] {r.text}" for r in active_rules) or "  (none)"}

=== VALID ACTIONS ===
{chr(10).join(f"  {v}" for v in valid_actions)}

{action_warning}

RESPOND WITH ONLY a JSON object — no prose, no markdown, no code fences. Put "action" FIRST, and keep "thought" to one short sentence:
{format_template}

The "action" field is required and must come first. "args" must match the action.{trace_instructions}
If you are promising a concrete FUTURE action, also include "commitment": "<one short sentence of what you will do>" — it is tracked, and broken promises lapse publicly.{reflection_line}
If nothing makes sense, use: {{"action": "idle", "args": {{}}}}"""

    # A final user turn that restates the format demand is the last thing weak
    # free models see — it markedly reduces the prose-narration drift that costs
    # an agent its turn to the idle fallback (T8). Pairs with the adapter's
    # response_format=json_object request.
    json_only = (
        "Output ONLY the JSON object for your action now. "
        "Begin your reply with { and end with } — no prose, no markdown, "
        "no code fences before or after."
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json_only},
    ]


def _perceived_context(
    agent: AgentState, world: World, recent_events: list[dict], params: Any
) -> tuple[dict, dict]:
    """Derive the `perceived` + `memory_retrieved` payload bodies for the decision
    trace from the SAME context fed to the model (no extra work, no LLM calls).

    Returns (perceived, memory) where:
      perceived = {visible_agents:[id], nearby_places:[id], overheard:[seq], ...}
      memory    = {memories:[{ref?, tick, kind, text}], window}
    """
    visible_agents = [
        a.id for a in world.living_agents()
        if a.location == agent.location and a.id != agent.id
    ]
    # Co-located places: the agent's own place + any place sharing its kind is
    # over-broad; v1 perception is "where I am", so nearby = current place only.
    nearby_places = [agent.location] if agent.location in world.places else []

    # EM-161 — the SAME effective window _assemble_context fed the model
    # (background shrinks to 8), so the trace stays truthful to the prompt.
    window = _effective_memory_window(agent, params)
    fed = recent_events[-window:]
    # overheard: seqs of the events the agent witnessed this window (best-effort;
    # the per-agent memory buffer stores text/tick/kind, seq may be absent).
    overheard = [e.get("seq") for e in fed if e.get("seq") is not None]
    memories = [
        {
            "ref": e.get("seq"),
            "tick": e.get("tick"),
            "kind": e.get("kind"),
            "text": e.get("text", ""),
        }
        for e in fed
    ]
    perceived = {
        "visible_agents": visible_agents,
        "nearby_places": nearby_places,
        "overheard": overheard,
    }
    memory = {"memories": memories, "window": window}
    return perceived, memory


# ──────────────────────────────────────────────────────────────────────────────
# Agent runtime
# ──────────────────────────────────────────────────────────────────────────────

class AgentRuntime:
    def __init__(self, world: World, router: Router):
        self.world = world
        self.router = router
        # Rolling per-agent event buffers
        self._memory: dict[str, list[dict]] = {}
        # W11b / EM-079 — per-agent active commitments:
        # [{id, text, made_tick, stale_turns}], capped at max_active (oldest
        # evicted silently). stale_turns counts the agent's consecutive turns
        # WITHOUT a non-talk tool call since the commitment was made/refreshed.
        self._commitments: dict[str, list[dict]] = {}
        # W11b / EM-080 — per-agent importance accumulator (reflection trigger).
        self._importance: dict[str, float] = {}
        # W11b / EM-081 — pending overheard lines awaiting an agent's NEXT turn:
        # [{speaker_id, speaker, text, tick, overheard:true}], capped at 2.
        self._overheard: dict[str, list[dict]] = {}
        # EM-145 — per-agent high-water tick of god billboard posts already
        # noticed (so a god post is delivered into a prompt at most once per
        # agent). In-memory by design: after a restart the worst case is one
        # repeat notice, which is harmless.
        self._board_seen: dict[str, int] = {}
        # Wave D2 / EM-159 — per-agent salience baselines, recorded at each
        # LLM-consulting turn (_note_llm_turn) and compared when a BACKGROUND
        # agent's turn comes due. In-memory by design (like _memory /
        # _importance): after a restart every background agent's first due
        # turn is salient ("first_turn"), which errs toward liveliness.
        #   _seen_colocated      — co-located agent+animal ids at last LLM turn
        #   _energy_band_seen    — energy band index at last LLM turn
        #   _witnessed_since_llm — agents that witnessed an importance>0 event
        #                          since their last LLM turn
        #   _last_llm_tick       — tick of the agent's last LLM-consulting turn
        self._seen_colocated: dict[str, frozenset[str]] = {}
        self._energy_band_seen: dict[str, int] = {}
        self._witnessed_since_llm: set[str] = set()
        self._last_llm_tick: dict[str, int] = {}

    def reset_state(self) -> None:
        """Clear ALL per-run cognition state (memories, commitments, importance
        accumulators, pending overheard lines). Called by the loop on reset."""
        self._memory.clear()
        self._commitments.clear()
        self._importance.clear()
        self._overheard.clear()
        self._board_seen.clear()
        # Wave D2 / EM-159 — salience baselines are per-run state too.
        self._seen_colocated.clear()
        self._energy_band_seen.clear()
        self._witnessed_since_llm.clear()
        self._last_llm_tick.clear()

    # ── W11b config accessors (defensive: the loader is owned elsewhere) ──────

    def _phantom_after_turns(self) -> int:
        try:
            return max(1, int(_world_block_get(
                self.world.params, "commitments", "phantom_after_turns",
                _DEFAULT_PHANTOM_AFTER_TURNS)))
        except (TypeError, ValueError):
            return _DEFAULT_PHANTOM_AFTER_TURNS

    def _max_active_commitments(self) -> int:
        try:
            return max(1, int(_world_block_get(
                self.world.params, "commitments", "max_active",
                _DEFAULT_MAX_ACTIVE_COMMITMENTS)))
        except (TypeError, ValueError):
            return _DEFAULT_MAX_ACTIVE_COMMITMENTS

    def _importance_threshold(self) -> float:
        try:
            return float(_world_block_get(
                self.world.params, "reflection", "importance_threshold",
                _DEFAULT_IMPORTANCE_THRESHOLD))
        except (TypeError, ValueError):
            return _DEFAULT_IMPORTANCE_THRESHOLD

    # ── Wave D2 / EM-159+160 config accessors (world.cadence, defensive) ──────

    def _spontaneity_chance(self) -> float:
        try:
            chance = float(_world_block_get(
                self.world.params, "cadence", "spontaneity_chance",
                _DEFAULT_SPONTANEITY_CHANCE))
        except (TypeError, ValueError):
            chance = _DEFAULT_SPONTANEITY_CHANCE
        return max(0.0, min(1.0, chance))

    def _reflex_streak_limit(self) -> int:
        try:
            return max(1, int(_world_block_get(
                self.world.params, "cadence", "reflex_streak_limit",
                _DEFAULT_REFLEX_STREAK_LIMIT)))
        except (TypeError, ValueError):
            return _DEFAULT_REFLEX_STREAK_LIMIT

    @staticmethod
    def _event_importance(event: dict) -> float:
        """Salience weight of one event for the reflection accumulator (EM-080)."""
        kind = event.get("kind")
        weight = _IMPORTANCE_WEIGHTS.get(kind, 0.0)
        if kind == "economy":
            payload = event.get("payload") or {}
            moved = payload.get("amount", payload.get("credits_delta", 0)) or 0
            try:
                if abs(int(moved)) >= _IMPORTANCE_ECONOMY_SWING:
                    weight = max(weight, _IMPORTANCE_ECONOMY_WEIGHT)
            except (TypeError, ValueError):
                pass
        return weight

    def push_event(self, event: dict) -> None:
        """Add an event to the memory of all agents who witnessed it."""
        actor_id = event.get("actor_id")
        target_id = event.get("target_id")
        tick = event.get("tick", 0)
        text = event.get("text", "")
        evt_payload = {"tick": tick, "text": text, "kind": event.get("kind")}

        # Determine which location this event occurred at (best-effort from payload)
        evt_location = event.get("payload", {}).get("place") or None

        # W11b / EM-080 — salience weight, accumulated per WITNESS below.
        importance = self._event_importance(event)

        for agent in self.world.living_agents():
            # Agent witnesses event if: they are the actor/target, OR event is at their location
            if (
                agent.id == actor_id
                or agent.id == target_id
                or (evt_location and agent.location == evt_location)
                or event.get("kind") in ("random_event", "rule_passed", "rule_rejected", "rule_proposed")
            ):
                buf = self._memory.setdefault(agent.id, [])
                buf.append(evt_payload)
                # Trim to 2x memory_window to save memory
                max_buf = self.world.params.memory_window * 2
                if len(buf) > max_buf:
                    del buf[:-max_buf]
                if importance > 0:
                    self._importance[agent.id] = (
                        self._importance.get(agent.id, 0.0) + importance
                    )
                    # Wave D2 / EM-159 — witnessing an importance>0 event makes
                    # a background agent's next due turn salient (cleared on
                    # its next LLM-consulting turn).
                    self._witnessed_since_llm.add(agent.id)

    def push_location_event(self, location: str, event: dict) -> None:
        """Push event to all agents at a location."""
        for agent in self.world.living_agents():
            if agent.location == location:
                buf = self._memory.setdefault(agent.id, [])
                evt_payload = {
                    "tick": event.get("tick", 0),
                    "text": event.get("text", ""),
                    "kind": event.get("kind"),
                }
                buf.append(evt_payload)
                max_buf = self.world.params.memory_window * 2
                if len(buf) > max_buf:
                    del buf[:-max_buf]

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-079 — commitment lifecycle (made / kept / phantom-lapsed)
    # ──────────────────────────────────────────────────────────────────────────

    def _advance_commitments(
        self,
        agent: AgentState,
        action: str | None,
        outcome_ok: bool,
        new_commitment_text: Any,
        profile_name: str,
        profile_color: str,
    ) -> list[dict]:
        """Advance the agent's commitment store for THIS turn and return the
        commitment_made / commitment_lapsed events to emit.

        Semantics (EM-079): a successful project/build/economy tool call marks
        the OLDEST commitment kept (dropped silently — kept promises emit
        nothing); any successful non-talk tool call resets the staleness clock;
        talk-only / idle / failed turns age every commitment, and one that goes
        `phantom_after_turns` turns without follow-through lapses publicly."""
        commitments = self._commitments.setdefault(agent.id, [])
        events: list[dict] = []
        base = {
            "actor_id": agent.id,
            "profile": profile_name,
            "profile_color": profile_color,
        }

        # 1. Follow-through: a real project/build/economy call keeps the oldest.
        if outcome_ok and action in _COMMIT_RESOLUTION_ACTIONS and commitments:
            commitments.pop(0)  # kept — silent drop, no event

        # 2. Staleness clock: any successful non-talk tool call resets it; pure
        #    talk (say/whisper/idle) or a failed turn ages every commitment.
        if outcome_ok and action not in _TALK_ACTIONS:
            for c in commitments:
                c["stale_turns"] = 0
        else:
            for c in commitments:
                c["stale_turns"] = int(c.get("stale_turns", 0)) + 1

        # 3. Phantom lapse: claimed in speech, never enacted.
        threshold = self._phantom_after_turns()
        kept: list[dict] = []
        for c in commitments:
            if int(c.get("stale_turns", 0)) >= threshold:
                events.append({
                    **base,
                    "kind": "commitment_lapsed",
                    "text": f"{agent.name}'s promise \"{c.get('text', '')}\" lapsed "
                            f"— all talk, no follow-through.",
                    "payload": {
                        "commitment_id": c.get("id"),
                        "text": c.get("text", ""),
                        "reason": "phantom",
                    },
                })
            else:
                kept.append(c)
        commitments[:] = kept

        # 4. A new commitment parsed from THIS turn's response (EM-066 pattern).
        if isinstance(new_commitment_text, str) and new_commitment_text.strip():
            entry = {
                "id": uuid.uuid4().hex,
                "text": new_commitment_text.strip()[:200],
                "made_tick": self.world.tick,
                "stale_turns": 0,
            }
            commitments.append(entry)
            del commitments[: -self._max_active_commitments()]  # oldest evicted
            events.append({
                **base,
                "kind": "commitment_made",
                "text": f"{agent.name} commits: \"{entry['text']}\"",
                "payload": {"commitment_id": entry["id"], "text": entry["text"]},
            })
        return events

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-081 — overhearing (context injection only; zero LLM calls)
    # ──────────────────────────────────────────────────────────────────────────

    def _distribute_overheard(self, agent: AgentState, action: str | None, args: dict) -> None:
        """When `agent` spoke this turn, queue the line for up to 2 OTHER
        co-located agents' NEXT-turn perceived context (deterministic pick:
        lowest id first, excluding the target of a directed talk). Each listener
        holds at most 2 pending lines (newest win)."""
        if action not in ("say", "whisper"):
            return
        said = str(args.get("text") or "").strip()
        if not said:
            return
        target_id = args.get("target") if action == "whisper" else None
        listeners = sorted(
            (
                a for a in self.world.living_agents()
                if a.location == agent.location and a.id not in (agent.id, target_id)
            ),
            key=lambda a: a.id,
        )[:_OVERHEARD_LISTENERS_CAP]
        for listener in listeners:
            buf = self._overheard.setdefault(listener.id, [])
            buf.append({
                "speaker_id": agent.id,
                "speaker": agent.name,
                "text": said[:200],
                "tick": self.world.tick,
                "overheard": True,
            })
            del buf[:-_OVERHEARD_PENDING_CAP]

    def _unseen_god_board_notes(self, agent: AgentState) -> list[dict]:
        """EM-145 — god billboard posts at this agent's location they have not
        yet been shown (consume-once: collecting them advances the agent's
        seen high-water tick). Newest 3 only; [] when the agent is away from
        the board or nothing new. Guarded getattr: duck-typed test worlds
        without a billboard stay fully functional."""
        world = self.world
        here_fn = getattr(world, "billboard_here", None)
        board = getattr(world, "billboard", None)
        if not callable(here_fn) or not isinstance(board, list):
            return []
        if not here_fn(agent.location):
            return []
        seen = self._board_seen.get(agent.id, -1)
        notes = [
            e for e in board
            if isinstance(e, dict)
            and e.get("actor_type") == "god"
            and int(e.get("tick", 0) or 0) > seen
        ]
        if not notes:
            return []
        self._board_seen[agent.id] = max(int(e.get("tick", 0) or 0) for e in notes)
        return notes[-3:]

    # ──────────────────────────────────────────────────────────────────────────
    # Wave D2 / EM-159+160 — background-tier salience gating + spontaneity floor
    #
    # EM-159 applies to the BACKGROUND tier ONLY (protagonists and supporting
    # always run full LLM turns when due). A due background turn consults the
    # LLM iff something salient happened since the agent's last LLM turn;
    # otherwise it resolves the deterministic seeded reflex routine — ZERO
    # router calls. EM-160 (inseparable, per the v4-review verdict) keeps
    # background agents from flattening into NPCs-on-rails: a seeded wildcard
    # and a reflex-streak floor both force full LLM turns.
    # ──────────────────────────────────────────────────────────────────────────

    def _colocated_ids(self, agent: AgentState) -> frozenset[str]:
        """Ids of OTHER living agents + living animals at the agent's place."""
        world = self.world
        ids = {
            a.id for a in world.living_agents()
            if a.location == agent.location and a.id != agent.id
        }
        animals_fn = getattr(world, "living_animals", None)
        if callable(animals_fn):
            ids.update(
                an.id for an in animals_fn() if an.location == agent.location
            )
        return frozenset(ids)

    def _has_unseen_board_note(self, agent: AgentState) -> bool:
        """Non-consuming peek at _unseen_god_board_notes: is there a god board
        note at this place the agent has not yet been shown? (The consuming
        delivery still happens only inside the LLM turn path.)"""
        world = self.world
        here_fn = getattr(world, "billboard_here", None)
        board = getattr(world, "billboard", None)
        if not callable(here_fn) or not isinstance(board, list):
            return False
        if not here_fn(agent.location):
            return False
        seen = self._board_seen.get(agent.id, -1)
        return any(
            isinstance(e, dict)
            and e.get("actor_type") == "god"
            and int(e.get("tick", 0) or 0) > seen
            for e in board
        )

    def _background_salience(self, agent: AgentState) -> tuple[bool, list[str]]:
        """The EM-159 salience check for a due BACKGROUND turn. Returns
        (salient, triggers) where triggers names every condition that fired:

          first_turn           — no baseline yet (first due turn of a run /
                                 after restore): always think once.
          new_colocated        — an agent/animal arrived at this place since
                                 the last LLM turn.
          witnessed_importance — witnessed an importance>0 event (the EM-080
                                 accumulator's weights) since the last LLM turn.
          energy_band          — energy crossed a 25-point band boundary.
          pending_whisper      — a god whisper is queued for this agent.
          proclamation         — a god proclamation landed since the last LLM
                                 turn (it rides every prompt; answering needs
                                 a real turn).
          board_note           — an unseen god billboard note at this place.
          uncast_vote          — an open (proposed) rule this agent hasn't
                                 voted on yet.
        """
        world = self.world
        triggers: list[str] = []

        baseline = self._seen_colocated.get(agent.id)
        if baseline is None:
            triggers.append("first_turn")
        elif self._colocated_ids(agent) - baseline:
            triggers.append("new_colocated")

        if agent.id in self._witnessed_since_llm:
            triggers.append("witnessed_importance")

        band_seen = self._energy_band_seen.get(agent.id)
        if band_seen is not None and band_seen != _energy_band(agent.energy):
            triggers.append("energy_band")

        pending = getattr(world, "pending_whispers", None)
        if isinstance(pending, dict) and pending.get(agent.id):
            triggers.append("pending_whisper")

        proc_fn = getattr(world, "active_proclamation", None)
        if callable(proc_fn):
            proc = proc_fn()
            if isinstance(proc, dict) and (
                int(proc.get("tick", 0) or 0)
                >= self._last_llm_tick.get(agent.id, -1)
            ):
                triggers.append("proclamation")

        if self._has_unseen_board_note(agent):
            triggers.append("board_note")

        for rule in getattr(world, "rules", {}).values():
            if (
                getattr(rule, "status", "") == "proposed"
                and agent.id not in getattr(rule, "votes", {})
            ):
                triggers.append("uncast_vote")
                break

        return bool(triggers), triggers

    def _spontaneity_roll(self, agent: AgentState) -> bool:
        """EM-160 wildcard: seeded P(full LLM turn) on a non-salient due turn.
        Deterministic from world state (agent id + tick hash — the animals'
        roll-for-activity idiom); never the `random` module, so replay holds."""
        chance = self._spontaneity_chance()
        if chance <= 0.0:
            return False
        bucket = _seed_int("spontaneity", agent.id, self.world.tick) % 1_000_000
        return (bucket / 1_000_000) < chance

    def _note_llm_turn(self, agent: AgentState) -> None:
        """Record post-turn salience baselines after an LLM-consulting turn
        (any tier — protagonists keep fresh baselines too, so a later demotion
        starts clean) and reset the EM-160 reflex streak."""
        agent.reflex_streak = 0
        self._witnessed_since_llm.discard(agent.id)
        self._seen_colocated[agent.id] = self._colocated_ids(agent)
        self._energy_band_seen[agent.id] = _energy_band(agent.energy)
        self._last_llm_tick[agent.id] = self.world.tick

    def _reflex_pick(self, agent: AgentState) -> dict:
        """The deterministic reflex routine for a non-salient background turn
        (EM-159, the animals' seeded-picker pattern — ZERO router calls):

          starving  ⇒ recharge   (when it would actually succeed: credits
                                  cover the effective cost, no blackout,
                                  energy below full)
          at work   ⇒ work
          otherwise ⇒ seeded forage / move-home rotation (move only when a
                       home-kind place exists and the agent isn't already
                       home; no homes ⇒ forage)

        Preflight checks mirror the world's action gates so a reflex turn
        resolves cleanly instead of burning the turn on a rejection."""
        world = self.world
        try:
            threshold = float(getattr(world.params, "starving_warn_threshold", 25.0))
        except (TypeError, ValueError):
            threshold = 25.0

        if agent.energy < threshold and agent.energy < 100:
            cost = int(getattr(world.params, "recharge_cost", 2))
            if world.has_active_rule("recharge_subsidy"):
                cost = max(1, cost // 2)
            blacked_out = getattr(world, "place_blacked_out", lambda _p: False)
            if agent.credits >= cost and not blacked_out(agent.location):
                return {"action": "recharge", "args": {}}

        place = world.places.get(agent.location)
        if place is not None and place.kind == "work":
            return {"action": "work", "args": {}}

        seed = _seed_int("cadence-reflex", agent.id, world.tick)
        homes = sorted(p.id for p in world.places.values() if p.kind == "home")
        at_home = place is not None and place.kind == "home"
        if homes and not at_home and seed % 2 == 1:
            return {"action": "move_to", "args": {"place": homes[seed % len(homes)]}}
        return {"action": "forage", "args": {}}

    def _reflex_turn(
        self, agent: AgentState, profile_name: str, profile_color: str,
        *,
        llm_attempts: list[dict] | None = None,
        cadence_reason: str | None = None,
        require_resolution: bool = False,
    ) -> dict | None:
        """Resolve a non-salient background due turn deterministically — ZERO
        router calls. Emits normal event kinds through the same _apply_action
        path as LLM turns, each marked `payload.reflex: true` (+ the current
        reflex_streak) so the feed/inspector can surface it (EM-166). The
        trace chain keeps its shape but carries NO llm_call span (the loop
        skips it for reflex traces — an empty span row would pollute the
        usage-cap accounting and the free-scale proof).

        EM-173 (survival reflex on llm_timeout) reuses this path with three
        optional hooks, all inert for the EM-159 cadence callers:
          - `llm_attempts`: the timed-out consult's real attempt spans ride the
            trace, so the loop still emits the `llm_call` row with
            timed_out: true (the timeout stays legible).
          - `cadence_reason`: stamped on every emitted event payload
            ("llm_timeout_reflex").
          - `require_resolution`: a reflex action rejected by the world's
            gates returns None (streak increment undone, no commitment aging,
            nothing emitted) so the caller can fall through to the existing
            idle fallback instead of surfacing a gated action as "instinct".
        """
        agent.reflex_streak = int(getattr(agent, "reflex_streak", 0)) + 1
        action_dict = self._reflex_pick(agent)
        result_event = self._apply_action(
            agent, action_dict, profile_name, profile_color
        )
        events = result_event["_multi"] if "_multi" in result_event else [result_event]
        if require_resolution and events[0].get("kind") == "parse_failure":
            # EM-173 — the reflex itself could not resolve: undo and signal
            # the caller to take the existing idle fallback (never crash).
            # A gated action made no world-state change, so discarding the
            # rejection event is safe; the caller's fallback advances
            # commitments exactly once.
            agent.reflex_streak -= 1
            return None
        for evt in events:
            payload = evt.setdefault("payload", {})
            payload["reflex"] = True
            payload["reflex_streak"] = agent.reflex_streak
            if cadence_reason is not None:
                payload["cadence_reason"] = cadence_reason
        outcome = "failed" if events[0].get("kind") == "parse_failure" else "ok"

        # EM-079 — commitments still advance on reflex turns: a successful
        # non-talk reflex action resets the staleness clock exactly as if the
        # LLM had chosen it; a failed one ages every commitment.
        lapsed = self._advance_commitments(
            agent, action_dict["action"], outcome == "ok", None,
            profile_name, profile_color,
        )
        if lapsed:
            if "_multi" in result_event:
                result_event["_multi"].extend(lapsed)
            else:
                result_event = {"_multi": [result_event] + lapsed}

        recent_events = self._memory.get(agent.id, [])
        perceived, memory = _perceived_context(
            agent, self.world, recent_events, self.world.params
        )
        result_event["_trace"] = {
            "perceived": {**perceived, "perceived_summary": None},
            "memory": memory,
            # EM-159: ZERO calls and the loop emits zero spans. EM-173: the
            # timed-out consult's span rides here so its llm_call row (with
            # timed_out: true) is still emitted.
            "llm_attempts": llm_attempts if llm_attempts is not None else [],
            "reflex": True,
            "reasoning": {
                "reasoning": None,
                "perceived_summary": None,
                "memories_used": None,
            },
            "action_chosen": {
                "chosen_tool": action_dict["action"],
                "args": action_dict.get("args") or {},
                "tier": "reflex",
            },
            "resolved": {"outcome": outcome, "state_deltas": {}},
        }
        return result_event

    async def run_turn(self, agent: AgentState) -> dict:
        """
        Execute one agent turn. Returns an event dict describing what happened.
        Never raises (all errors are caught and converted to idle).
        """
        profile_name = self.router.profile_name_for(agent.id, agent.profile)
        profile = self.router.get_profile(profile_name)
        profile_color = profile.color if profile else "#888888"
        max_tokens = profile.max_tokens if profile else 512
        temperature = profile.temperature if profile else 0.8

        recent_events = self._memory.get(agent.id, [])

        # ── Wave D2 / EM-159+160 — background-tier gate, BEFORE any context is
        # consumed (overheard lines / whispers / board notes stay queued for
        # the next LLM turn). Background ONLY: protagonists and supporting
        # always take full LLM turns when due. A non-salient due turn resolves
        # the deterministic reflex routine with ZERO router calls — unless the
        # EM-160 floor (streak limit) or wildcard (seeded spontaneity) forces
        # a full LLM "reassess" turn anyway.
        cadence_meta: dict | None = None
        if getattr(agent, "cadence_tier", "protagonist") == "background":
            salient, triggers = self._background_salience(agent)
            if salient:
                cadence_meta = {
                    "cadence_reason": "salient",
                    "salience_triggers": triggers,
                }
            elif (
                int(getattr(agent, "reflex_streak", 0))
                >= self._reflex_streak_limit()
            ):
                cadence_meta = {"cadence_reason": "reassess"}
            elif self._spontaneity_roll(agent):
                cadence_meta = {"cadence_reason": "wildcard"}
            else:
                return self._reflex_turn(agent, profile_name, profile_color)

        # W11b — pending overheard lines are consumed by THIS turn (EM-081), the
        # commitments block rides the prompt when non-empty (EM-079), and the
        # reflection field is requested only when the importance accumulator has
        # tripped (EM-080). All context-injection: zero extra LLM calls.
        pending_overheard = self._overheard.pop(agent.id, [])
        request_reflection = (
            self._importance.get(agent.id, 0.0) >= self._importance_threshold()
        )

        # EM-145 — god-voice delivery happens HERE (not silently inside the
        # prompt builder) so it can also surface as a feed event: pop the
        # queued whispers and collect unseen god billboard posts at this place.
        # Riding the prompt IS the delivery — both are emitted as
        # `god_voice_heard` below even if the turn later fails to parse.
        _pw = getattr(self.world, "pending_whispers", None)
        god_whispers = _pw.pop(agent.id, []) if isinstance(_pw, dict) else []
        board_notes = self._unseen_god_board_notes(agent)

        messages = _assemble_context(
            agent, self.world, recent_events, self.world.params,
            commitments=self._commitments.get(agent.id, []),
            overheard=pending_overheard,
            request_reflection=request_reflection,
            god_whispers=god_whispers,
            board_notes=board_notes,
        )

        # The legible half of EM-145: watchers see the god's voice land.
        delivery_events: list[dict] = []
        if god_whispers:
            delivery_events.append({
                "kind": "god_voice_heard",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"✦ {agent.name} hears the whisper",
                "payload": {"channel": "whisper", "count": len(god_whispers)},
            })
        if board_notes:
            delivery_events.append({
                "kind": "god_voice_heard",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"📌 {agent.name} reads the god's note on the board",
                "payload": {"channel": "billboard", "count": len(board_notes)},
            })

        # Decision-trace perception/memory derived from the SAME context (EM-066).
        perceived, memory = _perceived_context(
            agent, self.world, recent_events, self.world.params
        )
        if pending_overheard:
            # EM-081 — overheard speech lands in the perceived chain event's
            # payload, each line flagged overheard:true.
            perceived["overheard_speech"] = pending_overheard

        # Per-attempt llm metadata, collected in attempt order (EM-067). Each
        # entry becomes ONE `llm_call` row in the loop, all sharing this turn_id.
        llm_attempts: list[dict] = []

        # First attempt — EM-135: a lane whose recent outcome window shows
        # repeated truncations gets the boosted budget UP FRONT instead of
        # burning attempt 1 at a cap the lane keeps cutting. Guarded getattr:
        # duck-typed test routers don't implement first_attempt_max_tokens.
        attempt_tokens = max_tokens
        first_budget = getattr(self.router, "first_attempt_max_tokens", None)
        if callable(first_budget):
            attempt_tokens = first_budget(profile_name, max_tokens)
        action_dict, parse_error, llm_meta = await self._call_and_parse(
            profile_name, messages, attempt_tokens, temperature, agent, attempt=1
        )
        llm_attempts.append(self._llm_attempt_span(profile_name, llm_meta))

        # EM-170 — a TIMED-OUT consult never retries: the budget already burned
        # the turn's wall-clock allowance, and a retry would risk stalling the
        # world for a second budget. The turn drops straight to the idle
        # fallback below with reason llm_timeout; the world moves on.
        if parse_error and action_dict is None and not llm_meta.get("timed_out"):
            # One retry with error fed back; a truncated first attempt retries
            # with a boosted token budget — whether the provider admitted it
            # (finish_reason='length') or lied (mistral 'stop' cuts, run 126).
            retry_tokens = _retry_max_tokens(
                max_tokens, llm_meta.get("usage"),
                truncated=bool(llm_meta.get("truncated_json")),
            )
            retry_messages = messages + [
                {"role": "assistant", "content": "(previous response could not be parsed)"},
                {
                    "role": "user",
                    "content": (
                        f"Your previous response failed validation: {parse_error}\n"
                        "Do NOT think out loud or explain — your reply must begin "
                        "with { and contain ONLY a valid JSON object. If unsure, "
                        'use: {"action": "idle", "args": {}}'
                    ),
                },
            ]
            action_dict, parse_error, llm_meta = await self._call_and_parse(
                profile_name, retry_messages, retry_tokens, temperature, agent, attempt=2
            )
            llm_attempts.append(self._llm_attempt_span(profile_name, llm_meta))

        routed = self.router.last_routed_via(profile_name)

        # ── EM-173 — survival reflex on llm_timeout ───────────────────────────
        # Run 321: a degraded proxy night put 38% of calls into the EM-170 12s
        # budget; agents burned turn after turn as llm_timeout idles, could not
        # recharge, and Ada starved. A WALL-CLOCK timeout means the agent never
        # got to speak — so ANY tier (protagonist included) resolves the EM-159
        # reflex routine instead of idling. Content failures (provider_error /
        # parse failures) stay honest idles below — only the timeout earns the
        # reflex. The timed-out llm_call span (timed_out: true) still rides the
        # trace, every reflex event is stamped payload.reflex: true +
        # payload.cadence_reason: "llm_timeout_reflex", and the EM-170 lane
        # demerit / cache-no-poison behavior is untouched (both happened in
        # _call_and_parse). Salience baselines / reflex-streak reset are NOT
        # noted here: the LLM never answered, so a background agent's pending
        # triggers stay queued and its next due turn consults the LLM again.
        if action_dict is None and llm_meta.get("timed_out"):
            reflex_event = self._reflex_turn(
                agent, profile_name, profile_color,
                llm_attempts=llm_attempts,
                cadence_reason="llm_timeout_reflex",
                require_resolution=True,
            )
            if reflex_event is not None:
                # Feed legibility: the action line itself says the call timed
                # out and instinct took over.
                primary = (
                    reflex_event["_multi"][0] if "_multi" in reflex_event
                    else reflex_event
                )
                primary["text"] += " ⏱ (LLM call timed out — instinct took over)"
                # EM-145 — the god's voice rode the timed-out prompt: the
                # delivery still happened, so it stays legible (same as the
                # idle-fallback path below).
                if delivery_events:
                    trace = reflex_event.pop("_trace", None)
                    if "_multi" in reflex_event:
                        reflex_event["_multi"].extend(delivery_events)
                    else:
                        reflex_event = {"_multi": [reflex_event] + delivery_events}
                    if trace is not None:
                        reflex_event["_trace"] = trace
                return reflex_event
            # Reflex could not resolve (validation failure) — fall through to
            # the existing idle fallback below; never crash.

        if action_dict is None:
            # Second failure or ProviderError: idle + log. Still return a trace so
            # the dead-air turn remains inspectable (resolved.outcome == "failed").
            # Wave D2 / EM-159+160 — the router WAS consulted: reset the reflex
            # streak and re-baseline salience even though the turn failed.
            self._note_llm_turn(agent)
            payload: dict = {"reason": parse_error or "parse_failure"}
            if cadence_meta:
                payload.update(cadence_meta)
            if routed is not None:
                payload["routed_via"] = routed
            # Forensics: the feed text caps the snippet at 400 chars, which hid
            # HOW these responses were malformed. Keep the final attempt's full
            # raw text in the payload (bounded) so live failures yield fixtures.
            raw = llm_meta.get("raw_text")
            if isinstance(raw, str) and raw:
                payload["raw_response"] = raw[:8000]
            # EM-140 forensics: when the JSON parsed but validation rejected it,
            # keep WHAT was rejected — run 139's 'unknown place None' class was
            # undiagnosable without the offending args.
            rejected = llm_meta.get("rejected_action")
            if isinstance(rejected, dict):
                payload["rejected_action"] = {
                    "action": rejected.get("action"),
                    "args": rejected.get("args"),
                }
            trace = {
                "perceived": {**perceived, "perceived_summary": None},
                "memory": memory,
                "llm_attempts": llm_attempts,
                "reasoning": {
                    "reasoning": None,
                    "perceived_summary": None,
                    "memories_used": None,
                },
                "action_chosen": {"chosen_tool": "idle", "args": {}, "tier": "llm"},
                "resolved": {"outcome": "failed", "state_deltas": {}},
            }
            fail_evt = {
                "kind": "parse_failure",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"{agent.name} failed to produce a valid action (idle fallback): {parse_error}",
                "payload": payload,
            }
            # EM-079 — a failed turn is no follow-through: age the agent's
            # commitments (may lapse phantoms even on dead-air turns).
            lapsed = self._advance_commitments(
                agent, "idle", False, None, profile_name, profile_color
            )
            # EM-145 — the god's voice rode the prompt even though the turn
            # failed: the delivery still happened, so it stays legible.
            tail = lapsed + delivery_events
            if tail:
                return {"_multi": [fail_evt] + tail, "_trace": trace}
            return {**fail_evt, "_trace": trace}

        # Update mood if provided
        if action_dict.get("mood"):
            agent.mood = action_dict["mood"][:40]

        # EM-066 structured fields, captured from the SAME parsed response.
        perceived_summary = action_dict.get("perceived_summary")
        memories_used = action_dict.get("memories_used")
        reasoning = action_dict.get("reasoning")

        # Apply the action
        result_event = self._apply_action(agent, action_dict, profile_name, profile_color)

        # Surface the model the proxy actually routed this turn to as an
        # ADDITIVE, OPTIONAL field inside each emitted event's payload.
        # (contracts/events.schema.json treats payload as an open object.)
        if "_multi" in result_event:
            for evt in result_event["_multi"]:
                evt.setdefault("payload", {})["routed_via"] = routed
        else:
            result_event.setdefault("payload", {})["routed_via"] = routed

        # Wave D2 / EM-159+160 — WHY a background agent got this full LLM turn
        # (salient + the exact triggers / wildcard / reassess), additive on the
        # domain event payload(s) for the feed/inspector. The LLM was consulted:
        # reset the reflex streak and re-baseline salience on the POST-action
        # state (the agent may have moved / recharged this turn).
        if cadence_meta:
            if "_multi" in result_event:
                for evt in result_event["_multi"]:
                    evt.setdefault("payload", {}).update(cadence_meta)
            else:
                result_event.setdefault("payload", {}).update(cadence_meta)
        self._note_llm_turn(agent)

        # Assemble the decision-trace chain for loop._execute_turn to emit. The
        # `resolved` outcome reads the applied event(s): a parse_failure kind from
        # _apply_action means the action was gated/failed at resolution time.
        resolved_evt = (
            result_event["_multi"][0] if "_multi" in result_event else result_event
        )
        outcome = "failed" if resolved_evt.get("kind") == "parse_failure" else "ok"
        state_deltas = {}
        rpayload = resolved_evt.get("payload", {})
        for k in ("credits_delta", "energy_delta", "amount"):
            if k in rpayload:
                state_deltas[k] = rpayload[k]

        trace = {
            "perceived": {**perceived, "perceived_summary": perceived_summary},
            "memory": memory,
            "llm_attempts": llm_attempts,
            "reasoning": {
                "reasoning": reasoning,
                "perceived_summary": perceived_summary,
                "memories_used": memories_used,
            },
            "action_chosen": {
                "chosen_tool": action_dict.get("action"),
                "args": action_dict.get("args") or {},
                "tier": _action_tier(action_dict.get("action")),
            },
            "resolved": {"outcome": outcome, "state_deltas": state_deltas},
        }

        # ── W11b cognition, all parsed from the SAME single response ──────────
        chosen_action = action_dict.get("action")
        outcome_ok = outcome == "ok"
        extra_events: list[dict] = []

        # EM-079 — commitments: record/keep/lapse.
        extra_events.extend(self._advance_commitments(
            agent, chosen_action, outcome_ok, action_dict.get("commitment"),
            profile_name, profile_color,
        ))

        # EM-080 — reflection/diary entry (emitted whenever present; resets the
        # importance accumulator; the loop pushes it into the memory buffer).
        reflection_text = action_dict.get("reflection")
        if isinstance(reflection_text, str) and reflection_text.strip():
            importance = round(self._importance.get(agent.id, 0.0), 2)
            self._importance[agent.id] = 0.0
            extra_events.append({
                "kind": "reflection",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"{agent.name} reflects: \"{reflection_text.strip()}\"",
                "payload": {"text": reflection_text.strip(), "importance": importance},
            })

        # EM-081 — distribute this turn's speech to co-located overhearers.
        if outcome_ok:
            self._distribute_overheard(
                agent, chosen_action, action_dict.get("args") or {}
            )

        # EM-145 — god-voice delivery events (built before the LLM call).
        extra_events.extend(delivery_events)

        if extra_events:
            if "_multi" in result_event:
                result_event["_multi"].extend(extra_events)
            else:
                result_event = {"_multi": [result_event] + extra_events}

        result_event["_trace"] = trace

        return result_event

    def _llm_attempt_span(self, profile_name: str, meta: dict) -> dict:
        """Build ONE llm_call trace span from a per-attempt `meta` (EM-067).

        The loop turns each of these into an `llm_call` event row. Token usage
        comes from the provider's `last_usage` snapshot captured in
        `_call_and_parse`; it is None for Mock (and failed attempts), in which
        case input/output tokens + finish_reason stay null but the OTel keys are
        still emitted with present-but-null values by the loop.
        """
        usage = meta.get("usage")
        usage = usage if isinstance(usage, dict) else None
        span = {
            "gen_ai.request.model": profile_name,
            "gen_ai.response.model": meta.get("routed_via"),
            "usage": usage,
            "latency_ms": meta.get("latency_ms"),
            "finish_reason": usage.get("finish_reason") if usage else None,
            "cached": bool(usage.get("cached")) if usage else False,
            "attempt": meta.get("attempt", 1),
        }
        # EM-170 — ADDITIVE: only attempts cancelled by the turn-latency guard
        # carry the flag (latency_ms above is the real elapsed wall-clock ms),
        # so non-timeout llm_call rows keep their exact pre-EM-170 key set.
        if meta.get("timed_out"):
            span["timed_out"] = True
        return span

    async def _call_and_parse(
        self,
        profile_name: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        agent: AgentState,
        attempt: int = 1,
    ) -> tuple[dict | None, str | None, dict]:
        """
        Call the model and parse+validate the response.
        Returns (action_dict, error_string, llm_meta).
        action_dict is None on failure. llm_meta carries the per-attempt
        decision-trace metadata for ONE `llm_call` span. Captured PER ATTEMPT
        because the adapter's `last_routed_via`/`last_usage` are overwritten by
        the next call — so a retry's metadata would otherwise clobber attempt 1.
          {"attempt": int, "latency_ms": float|None,
           "routed_via": str|None, "usage": dict|None}
        `usage` is the provider's last_usage snapshot (None for Mock / on error),
        and `latency_ms` falls back to the provider's measured value when present.
        """
        meta: dict = {
            "attempt": attempt,
            "latency_ms": None,
            "routed_via": None,
            "usage": None,
        }
        budget = self._turn_llm_budget()
        started = time.perf_counter()
        try:
            # ── Wave D2 / EM-170 — turn-latency guard ──────────────────────────
            # The FULL consult (router.chat → adapter, including the adapter's
            # internal timeout+retry chain) runs under one wall-clock budget.
            # asyncio.wait_for cancels the inner task on timeout and AWAITS the
            # cancellation itself, so the underlying HTTP task is reaped — never
            # abandoned to spam "Task exception was never retrieved". A cancelled
            # call also never reaches the router's cache-store line, so a
            # timed-out call can NOT poison the decision cache. budget<=0 ⇒
            # guard disabled ⇒ byte-for-byte today's await.
            chat_coro = self.router.chat(
                profile_name, messages,
                max_tokens=max_tokens, temperature=temperature,
            )
            if budget > 0:
                text = await asyncio.wait_for(chat_coro, timeout=budget)
            else:
                text = await chat_coro
        except asyncio.TimeoutError:
            elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
            meta["latency_ms"] = elapsed_ms
            meta["timed_out"] = True
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            # EM-135 lane health: a turn-budget timeout is a lane demerit
            # (same window mechanism truncation uses) so chronic stallers
            # surface in lane_health(); the world moves on regardless.
            self._note_timeout_demerit(profile_name)
            log.warning(
                "EM-170: %s's LLM call exceeded the %.1fs turn budget "
                "(%.0f ms, profile=%s) — cancelled, idle fallback",
                agent.name, budget, elapsed_ms, profile_name,
            )
            return None, f"llm_timeout: LLM call exceeded the {budget:g}s turn budget", meta
        except ProviderError as exc:
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            # On error the adapter may still expose the routed model from a prior
            # call; usage stays None for a failed attempt.
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            log.warning("ProviderError for %s: %s", agent.name, exc)
            return None, f"provider_error: {exc.detail}", meta
        except Exception as exc:
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            log.error("Unexpected error calling %s: %s", profile_name, exc)
            return None, f"unexpected_error: {exc}", meta

        # Snapshot adapter state IMMEDIATELY after a successful call, before any
        # retry can overwrite it. usage is None for Mock; prefer the provider's
        # own latency measurement, falling back to our wall-clock timing.
        usage = self.router.last_usage(profile_name)
        meta["usage"] = usage
        meta["routed_via"] = self.router.last_routed_via(profile_name)
        if isinstance(usage, dict) and usage.get("latency_ms") is not None:
            meta["latency_ms"] = usage["latency_ms"]
        else:
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)

        action_dict = _extract_first_json(text)
        # EM-135 — report this attempt's parse outcome to the router's lane
        # health. Truncation is judged structurally on the RAW text even when
        # extraction SUCCEEDED: a response that parsed only via truncation
        # repair still means the lane is cutting output — salvage hides it
        # from the feed, not from health tracking.
        truncated = _looks_truncated(text)
        self._note_parse_outcome(
            profile_name, parsed=action_dict is not None, truncated=truncated
        )
        if action_dict is None:
            finish_reason = usage.get("finish_reason") if isinstance(usage, dict) else None
            # Structural truncation verdict for the retry-budget boost (the
            # reported finish_reason can be a lying 'stop'), plus the full raw
            # text for the final parse_failure event's forensics.
            meta["truncated_json"] = truncated
            meta["raw_text"] = text
            self._forget_response(profile_name, messages)
            return None, _no_json_error(text, finish_reason), meta

        # Optional EM-066 trace fields must never fail a turn — truncate, don't reject.
        _sanitize_optional_trace_fields(action_dict)
        # EM-140 — collapse arg aliases (destination→place) and resolve agent
        # names to ids BEFORE validation, so a well-intentioned response isn't
        # a dead turn over key spelling the prompt never specified.
        _normalize_args(action_dict, agent, self.world)

        schema_error = _validate_schema(action_dict)
        if schema_error:
            meta["rejected_action"] = action_dict
            self._forget_response(profile_name, messages)
            return None, f"schema error: {schema_error}", meta

        world_error = _validate_world(action_dict, agent, self.world)
        if world_error:
            meta["rejected_action"] = action_dict
            self._forget_response(profile_name, messages)
            return None, f"world error: {world_error}", meta

        return action_dict, None, meta

    def _forget_response(self, profile_name: str, messages: list[dict]) -> None:
        """Evict this request from the router's decision cache after a failed
        parse/validation. A bad response replayed from cache turns one dead
        turn into many (cached=true was observed serving the same truncated
        JSON back into a turn, run 126). Guarded getattr: duck-typed test
        routers don't implement forget()."""
        forget = getattr(self.router, "forget", None)
        if callable(forget):
            forget(profile_name, messages)

    def _note_parse_outcome(
        self, profile_name: str, *, parsed: bool, truncated: bool
    ) -> None:
        """Report one parse attempt's outcome to the router's lane-health
        window (EM-135). Guarded getattr: duck-typed test routers don't
        implement note_parse_outcome()."""
        note = getattr(self.router, "note_parse_outcome", None)
        if callable(note):
            note(profile_name, parsed=parsed, truncated=truncated)

    def _turn_llm_budget(self) -> float:
        """EM-170 — the per-turn LLM wall-clock budget in seconds, read
        defensively from world params (`world.turn_llm_budget_seconds`).
        <= 0 / absent / malformed ⇒ 0.0 ⇒ guard fully disabled."""
        try:
            budget = float(getattr(
                self.world.params, "turn_llm_budget_seconds", 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return budget if budget > 0 else 0.0

    def _note_timeout_demerit(self, profile_name: str) -> None:
        """EM-170 — report a turn-budget timeout into the router's EM-135
        lane-health window (the same mechanism truncation demerits use).
        Guarded for duck-typed test routers: missing method is a no-op, and a
        router predating the `timed_out` kwarg degrades to a plain unparsed
        demerit rather than breaking the turn."""
        note = getattr(self.router, "note_parse_outcome", None)
        if not callable(note):
            return
        try:
            note(profile_name, parsed=False, truncated=False, timed_out=True)
        except TypeError:
            note(profile_name, parsed=False, truncated=False)

    def _apply_action(
        self,
        agent: AgentState,
        action_dict: dict,
        profile_name: str,
        profile_color: str,
    ) -> dict:
        """Apply the validated action to world state. Return event dict."""
        action = action_dict["action"]
        args = action_dict.get("args") or {}
        thought = action_dict.get("thought", "")
        tick = self.world.tick

        base = {
            "actor_id": agent.id,
            "profile": profile_name,
            "profile_color": profile_color,
            "tick": tick,
        }

        if action == "idle":
            return {**base, "kind": "agent_action", "text": f"{agent.name} idles.",
                    "payload": {"action": "idle", "thought": thought}}

        elif action == "work":
            ok, reason, reward = self.world.action_work(agent)
            if ok:
                return {**base, "kind": "economy",
                        "text": f"{agent.name} works and earns {reward} credits.",
                        "payload": {"action": "work", "credits_delta": reward, "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to work but: {reason}",
                        "payload": {"action": "work", "error": reason}}

        elif action == "forage":
            ok, reason, reward = self.world.action_forage(agent)
            return {**base, "kind": "economy",
                    "text": f"{agent.name} forages and finds {reward} credits.",
                    "payload": {"action": "forage", "credits_delta": reward, "thought": thought}}

        elif action == "recharge":
            ok, reason, gained = self.world.action_recharge(agent)
            if ok:
                return {**base, "kind": "economy",
                        "text": f"{agent.name} recharges (+{gained:.1f} energy).",
                        "payload": {"action": "recharge", "energy_delta": gained, "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to recharge but: {reason}",
                        "payload": {"action": "recharge", "error": reason}}

        elif action == "give":
            target = self.world.agents.get(args["target"])
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to give but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason = self.world.action_give(agent, target, args["amount"])
            if ok:
                return {**base, "kind": "economy", "target_id": target.id,
                        "text": f"{agent.name} gives {args['amount']} credits to {target.name}.",
                        "payload": {"action": "give", "amount": args["amount"], "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to give but: {reason}",
                        "payload": {"error": reason}}

        elif action == "steal":
            target = self.world.agents.get(args["target"])
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to steal but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, amount = self.world.action_steal(agent, target)
            if ok:
                return {**base, "kind": "economy", "target_id": target.id,
                        "text": f"{agent.name} steals {amount} credits from {target.name}.",
                        "payload": {"action": "steal", "amount": amount, "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to steal but: {reason}",
                        "payload": {"error": reason}}

        elif action == "say":
            text_said = args.get("text", "")
            return {**base, "kind": "agent_speech",
                    "text": f"{agent.name} says: \"{text_said}\"",
                    "payload": {"action": "say", "said": text_said,
                                "place": agent.location, "private": False, "thought": thought}}

        elif action == "whisper":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to whisper but target not found",
                        "payload": {"error": "target_not_found"}}
            return {**base, "kind": "agent_speech", "target_id": target.id,
                    "text": f"{agent.name} whispers to {target.name}.",
                    "payload": {"action": "whisper", "said": args.get("text", ""),
                                "place": agent.location, "private": True, "thought": thought}}

        elif action == "insult":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to insult but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason = self.world.action_insult(agent, target)
            if ok:
                return {**base, "kind": "conflict", "target_id": target.id,
                        "text": f"{agent.name} insults {target.name}!",
                        "payload": {"action": "insult",
                                    "insult_text": args.get("text", ""), "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to insult but: {reason}",
                        "payload": {"error": reason}}

        elif action == "attack":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to attack but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason = self.world.action_attack(agent, target)
            if ok:
                return {**base, "kind": "conflict", "target_id": target.id,
                        "text": f"{agent.name} attacks {target.name}!",
                        "payload": {"action": "attack",
                                    "energy_cost": self.world.params.attack_energy_cost,
                                    "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to attack but: {reason}",
                        "payload": {"error": reason}}

        elif action == "set_relationship":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to set_relationship but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason = self.world.action_set_relationship(agent, target, args.get("type", "neutral"))
            if ok:
                return {**base, "kind": "relationship", "target_id": target.id,
                        "text": f"{agent.name} declares {target.name} as {args['type']}.",
                        "payload": {"action": "set_relationship",
                                    "rel_type": args.get("type"), "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to set_relationship but: {reason}",
                        "payload": {"error": reason}}

        elif action == "remember":
            ok, reason = self.world.action_remember(agent, args.get("fact", ""))
            return {**base, "kind": "memory",
                    "text": f"{agent.name} remembers: \"{args.get('fact', '')}\"",
                    "payload": {"action": "remember", "fact": args.get("fact"), "thought": thought}}

        elif action == "move_to":
            place_id = args.get("place")
            if place_id in self.world.places:
                old_place = agent.location
                agent.location = place_id
                place = self.world.places[place_id]
                return {**base, "kind": "agent_moved",
                        "text": f"{agent.name} moves to {place.name}.",
                        "payload": {"action": "move_to", "place": place_id,
                                    "from": old_place, "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to move to unknown place '{place_id}'.",
                        "payload": {"error": f"unknown place: {place_id}"}}

        elif action == "propose_rule":
            effect = args.get("effect", "")
            text = args.get("text", "")
            # PROTOTYPE (god-channel) — name_town carries the proposed name.
            name = args.get("name")
            ok, reason, rule = self.world.action_propose_rule(agent, effect, text, name)
            if ok and rule:
                # EM-100 — feed text leads with the rule's text + effect tag.
                label = _rule_label(text)
                renewal = getattr(rule, "renewal_of", None)
                feed = f"{agent.name} proposes \"{label}\" ({effect})"
                payload = {"rule_id": rule.id, "effect": effect,
                           "text": text, "thought": thought}
                if renewal:
                    feed += " — a RENEWAL of the law already in force"
                    payload["renewal_of"] = renewal
                return {**base, "kind": "rule_proposed",
                        "text": feed + ".",
                        "payload": payload}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to propose rule but: {reason}",
                        "payload": {"error": reason}}

        elif action == "vote":
            rule_id = args.get("rule_id", "")
            choice = args.get("choice", False)
            ok, reason, new_status = self.world.action_vote(agent, rule_id, choice)
            if ok:
                # EM-100 — every rule_* feed line leads with the rule's text +
                # effect tag (never the bare uuid; the id stays in payload).
                rule = self.world.rules.get(rule_id)
                label = _rule_label(rule.text if rule else "")
                effect = rule.effect if rule else "?"
                events = [{**base, "kind": "rule_vote",
                           "text": f"{agent.name} votes {'YES' if choice else 'NO'} "
                                   f"on \"{label}\" ({effect}).",
                           "payload": {"rule_id": rule_id, "choice": choice,
                                       "effect": effect, "thought": thought}}]
                if new_status == "active":
                    events.append({**base, "kind": "rule_passed",
                                   "text": f"\"{label}\" ({effect}) PASSED and is now active!",
                                   "payload": {"rule_id": rule_id, "effect": effect,
                                               "new_status": "active"}})
                elif new_status == "renewed":
                    # EM-087 — an identical-effect law was already active: the
                    # existing rule is RENEWED (refreshed), never stacked.
                    original = getattr(rule, "renewal_of", None) if rule else None
                    active = self.world._active_rule(effect) if rule else None
                    original_id = original or (active.id if active else rule_id)
                    events.append({**base, "kind": "rule_passed",
                                   "text": f"\"{label}\" ({effect}) RENEWED — the law "
                                           f"already in force is refreshed, not stacked.",
                                   "payload": {"rule_id": original_id, "effect": effect,
                                               "renewed": True,
                                               "renewal_proposal_id": rule_id,
                                               "new_status": "active"}})
                elif new_status == "rejected":
                    events.append({**base, "kind": "rule_rejected",
                                   "text": f"\"{label}\" ({effect}) was rejected.",
                                   "payload": {"rule_id": rule_id, "effect": effect,
                                               "new_status": "rejected"}})
                # Return as a list marker so loop can emit multiple events
                return {"_multi": events}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to vote but: {reason}",
                        "payload": {"error": reason}}

        # ── W7 construction actions (dispatch to world-core action_*) ─────────
        # Each world action_* returns a ready-to-emit event dict / {"_multi":[...]}
        # (NOT an (ok, reason, value) tuple) and takes the building_id STRING, not a
        # Building object. _emit_world_result spreads base metadata onto each, just
        # like the `vote` branch above. Illegal ids come back as parse_failure events
        # from the world itself, so the loop keeps turning.
        elif action == "propose_project":
            name = args.get("name", "")
            kind = args.get("kind", "")
            funds_required = args.get("funds_required")
            function = args.get("function")
            result = self.world.action_propose_project(
                agent, name, kind, funds_required, function
            )
            return _emit_world_result(result, base, thought)

        elif action == "contribute_funds":
            building_id = args.get("building_id", "")
            amount = args.get("amount", 0)
            result = self.world.action_contribute_funds(agent, building_id, amount)
            return _emit_world_result(result, base, thought)

        elif action == "build_step":
            building_id = args.get("building_id", "")
            result = self.world.action_build_step(agent, building_id)
            return _emit_world_result(result, base, thought)

        elif action == "repair":
            building_id = args.get("building_id", "")
            result = self.world.action_repair(agent, building_id)
            return _emit_world_result(result, base, thought)

        elif action == "arson":
            building_id = args.get("building_id", "")
            result = self.world.action_arson(agent, building_id)
            return _emit_world_result(result, base, thought)

        elif action == "take_offline":
            building_id = args.get("building_id", "")
            # take_offline returns a SINGLE structure_state_changed event dict (no _multi).
            result = self.world.action_take_offline(agent, building_id)
            return _emit_world_result(result, base, thought)

        # ── W11b / EM-091 billboard reflex tools ───────────────────────────────
        elif action == "post_billboard":
            result = self.world.action_post_billboard(agent, args.get("text", ""))
            return _emit_world_result(result, base, thought)

        elif action == "read_billboard":
            posts = self.world.read_billboard_top(3)
            # Inject the top posts straight into the agent's memory buffer so
            # they ride the next turns' RECENT EVENTS context (no event kind
            # needed for the read itself — a generic agent_action suffices).
            buf = self._memory.setdefault(agent.id, [])
            for p in posts:
                author = p.get("actor_id", "?")
                if author == "god":
                    author = "GOD"
                else:
                    known = self.world.agents.get(author)
                    author = known.name if known else author
                buf.append({
                    "tick": p.get("tick", tick),
                    "kind": "billboard_posted",
                    "text": f"[billboard, by {author}] {p.get('text', '')}",
                })
            max_buf = self.world.params.memory_window * 2
            if len(buf) > max_buf:
                del buf[:-max_buf]
            return {**base, "kind": "agent_action",
                    "text": f"{agent.name} reads the billboard "
                            f"({len(posts)} recent post{'s' if len(posts) != 1 else ''}).",
                    "payload": {"action": "read_billboard",
                                "posts": posts, "thought": thought}}

        # ── PROTOTYPE (god-channel) — answer the active proclamation ────────────
        elif action == "answer_proclamation":
            result = self.world.answer_proclamation(agent, args.get("text", ""))
            return _emit_world_result(result, base, thought)

        else:
            return {**base, "kind": "agent_action",
                    "text": f"{agent.name} does {action}.",
                    "payload": {"action": action, "thought": thought}}

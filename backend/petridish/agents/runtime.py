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

import json
import logging
import re
import time
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
        "action": {
            "type": "string",
            "enum": [
                "move_to", "say", "whisper", "work", "forage", "recharge",
                "give", "steal", "insult", "attack", "set_relationship",
                "remember", "propose_rule", "vote", "idle",
                # W7 / EM-060+062 construction actions (action-protocol v1.1.0).
                "propose_project", "contribute_funds", "build_step",
                "repair", "arson", "take_offline",
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
}


def _action_tier(action: str) -> str:
    """The registry tier for an action (defaults to 'llm' for unknown actions)."""
    meta = TOOL_REGISTRY.get(action)
    return meta.get("tier", "llm") if meta else "llm"

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


def _repair_truncated(frag: str) -> dict | None:
    """Best-effort parse of a JSON object that was cut off mid-output.

    Free models routed through the proxy often run out of tokens partway
    through (typically inside a trailing string value). We close any open
    string, drop a dangling trailing comma/colon, and balance the open
    braces/brackets, then try to parse. Returns None if still unparseable.
    """
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
        repaired += '"'                       # close a dangling string
    repaired = re.sub(r"[,:]\s*$", "", repaired.rstrip())  # drop trailing , or :
    for opener in reversed(stack):
        repaired += "}" if opener == "{" else "]"
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
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
_TRACE_TEXT_CAPS = {"thought": 500, "mood": 40, "perceived_summary": 600, "reasoning": 1200}
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


def _validate_world(action_dict: dict, agent: AgentState, world: World) -> str | None:
    """Returns an error string or None if world-legal."""
    action = action_dict.get("action")
    args = action_dict.get("args", {}) or {}

    # Dead agents (should never reach here, but guard)
    if not agent.alive:
        return "agent is dead"

    if action == "work":
        place = world.places.get(agent.location)
        if place is None or place.kind != "work":
            return f"work requires a 'work' place; you are at '{agent.location}' ({place.kind if place else 'unknown'})"

    elif action == "recharge":
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
        target_id = args.get("target")
        amount = args.get("amount", 0)
        if not target_id:
            return "give requires target"
        target = world.agents.get(target_id)
        if target is None or not target.alive:
            return f"target '{target_id}' not found or dead"
        if target.location != agent.location:
            return f"target '{target_id}' is not at your location"
        if agent.credits < amount:
            return f"insufficient credits: have {agent.credits}, need {amount}"

    elif action == "steal":
        if world.has_active_rule("ban_stealing"):
            return "ban_stealing rule is active — steal is forbidden"
        target_id = args.get("target")
        if not target_id:
            return "steal requires target"
        target = world.agents.get(target_id)
        if target is None or not target.alive:
            return f"target '{target_id}' not found or dead"
        if target.location != agent.location:
            return f"target '{target_id}' is not at your location"

    elif action in ("insult", "attack", "whisper", "set_relationship"):
        target_id = args.get("target")
        if not target_id:
            return f"{action} requires target"
        target = world.agents.get(target_id)
        if target is None or not target.alive:
            return f"target '{target_id}' not found or dead"
        if target.location != agent.location:
            return f"target '{target_id}' is not at your location"

    elif action == "move_to":
        place_id = args.get("place")
        if place_id not in world.places:
            known = list(world.places.keys())
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
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus", "ban_arson"}
        if effect not in valid_effects:
            return f"invalid effect '{effect}'. Valid: {sorted(valid_effects)}"

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
        elif status != "under_construction":
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

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Context assembly
# ──────────────────────────────────────────────────────────────────────────────

def _assemble_context(
    agent: AgentState,
    world: World,
    recent_events: list[dict],
    params: Any,
) -> list[dict]:
    """Build the OpenAI-style messages list for this agent's turn."""
    place = world.places.get(agent.location)
    place_name = place.name if place else agent.location
    place_kind = place.kind if place else "unknown"

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
        return place_kind == loc

    valid_actions: list[str] = []
    valid_actions.append("idle, forage, recharge, move_to, remember")
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
    # Governance actions are gated to a governance place.
    if _gate_ok("propose_rule"):
        valid_actions.append("propose_rule (effect, text) - effect: ban_stealing|ubi|recharge_subsidy|work_bonus|ban_arson")
    if _gate_ok("vote") and proposed_rules:
        rule_list = "; ".join(f"id={r.id} effect={r.effect} text={r.text!r}" for r in proposed_rules)
        valid_actions.append(f"vote (rule_id, choice) - vote on: {rule_list}")

    # ── W7 construction actions (offered per gates) ───────────────────────────
    valid_actions.append("propose_project (name, kind, funds_required?, function?) - start a new building/collective project at this place")
    if open_projects:
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
        if (status == "under_construction" or funded_planned) and _gate_ok("build_step"):
            valid_actions.append(f"build_step (building_id={bid}) - add construction progress here")
        if status in ("damaged", "offline") and _gate_ok("repair"):
            valid_actions.append(f"repair (building_id={bid}) - restore this {status} building")
        if status != "destroyed" and _gate_ok("arson"):
            valid_actions.append(f"arson (building_id={bid}) - burn this building (a crime; witnesses lose trust)")
        if status == "operational" and _building_field(b, "owner_id") == agent.id and _gate_ok("take_offline"):
            valid_actions.append(f"take_offline (building_id={bid}) - you own this; take it offline")

    # Recent events summary
    event_lines = []
    for evt in recent_events[-params.memory_window:]:
        event_lines.append(f"  [tick {evt.get('tick', '?')}] {evt.get('text', '')}")

    # Beliefs
    belief_lines = "\n".join(f"  - {b}" for b in agent.beliefs) if agent.beliefs else "  (none)"

    # Relationships
    rel_lines = []
    for other_id, rel in agent.relationships.items():
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
    needs_lines = [
        f"Energy {agent.energy:.0f}/100 — at 0 you start DYING. "
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

    system_prompt = f"""You are {agent.name}, a character in a living world simulation.
Agent ID: {agent.id}
Tick: {world.tick}
Personality: {agent.personality}

=== YOUR STATUS ===
Location: {place_name} (kind={place_kind})
Energy: {agent.energy:.1f}/100
Credits: {agent.credits}
Mood: {agent.mood}

=== NEEDS ===
{needs_text}

=== CO-LOCATED AGENTS ===
{chr(10).join(f"  {a.name} (id={a.id}, energy={a.energy:.0f}, credits={a.credits})" for a in co_located) or "  (none)"}

=== RECENT EVENTS ===
{chr(10).join(event_lines) or "  (none)"}

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

RESPOND WITH ONLY a JSON object — no prose, no markdown, no code fences. Put "action" FIRST, and keep "thought" to one short sentence:
{{"action": "<verb>", "args": {{...}}, "mood": "optional mood update", "thought": "one short sentence", "perceived_summary": "one sentence on who/what was nearby or overheard", "memories_used": ["the memory snippets you leaned on"], "reasoning": "a brief why, kept inside this JSON"}}

The "action" field is required and must come first. "args" must match the action.
ALSO include (in the SAME json object — do NOT make a second call): "perceived_summary" (one sentence on what you perceived this turn), "memories_used" (the recent-event/memory snippets you actually relied on), and "reasoning" (your fuller reasoning, distinct from the short "thought"). These three are optional but strongly preferred — they are recorded into the decision trace.
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

    window = params.memory_window
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

    def push_event(self, event: dict) -> None:
        """Add an event to the memory of all agents who witnessed it."""
        actor_id = event.get("actor_id")
        target_id = event.get("target_id")
        tick = event.get("tick", 0)
        text = event.get("text", "")
        evt_payload = {"tick": tick, "text": text, "kind": event.get("kind")}

        # Determine which location this event occurred at (best-effort from payload)
        evt_location = event.get("payload", {}).get("place") or None

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
        messages = _assemble_context(agent, self.world, recent_events, self.world.params)

        # Decision-trace perception/memory derived from the SAME context (EM-066).
        perceived, memory = _perceived_context(
            agent, self.world, recent_events, self.world.params
        )

        # Per-attempt llm metadata, collected in attempt order (EM-067). Each
        # entry becomes ONE `llm_call` row in the loop, all sharing this turn_id.
        llm_attempts: list[dict] = []

        # First attempt
        action_dict, parse_error, llm_meta = await self._call_and_parse(
            profile_name, messages, max_tokens, temperature, agent, attempt=1
        )
        llm_attempts.append(self._llm_attempt_span(profile_name, llm_meta))

        if parse_error and action_dict is None:
            # One retry with error fed back
            retry_messages = messages + [
                {"role": "assistant", "content": "(previous response could not be parsed)"},
                {
                    "role": "user",
                    "content": (
                        f"Your previous response failed validation: {parse_error}\n"
                        "Reply with ONLY a valid JSON object. If unsure, use: "
                        '{"action": "idle", "args": {}}'
                    ),
                },
            ]
            action_dict, parse_error, llm_meta = await self._call_and_parse(
                profile_name, retry_messages, max_tokens, temperature, agent, attempt=2
            )
            llm_attempts.append(self._llm_attempt_span(profile_name, llm_meta))

        routed = self.router.last_routed_via(profile_name)

        if action_dict is None:
            # Second failure or ProviderError: idle + log. Still return a trace so
            # the dead-air turn remains inspectable (resolved.outcome == "failed").
            payload: dict = {"reason": parse_error or "parse_failure"}
            if routed is not None:
                payload["routed_via"] = routed
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
            return {
                "kind": "parse_failure",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"{agent.name} failed to produce a valid action (idle fallback): {parse_error}",
                "payload": payload,
                "_trace": trace,
            }

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
        return {
            "gen_ai.request.model": profile_name,
            "gen_ai.response.model": meta.get("routed_via"),
            "usage": usage,
            "latency_ms": meta.get("latency_ms"),
            "finish_reason": usage.get("finish_reason") if usage else None,
            "cached": bool(usage.get("cached")) if usage else False,
            "attempt": meta.get("attempt", 1),
        }

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
        started = time.perf_counter()
        try:
            text = await self.router.chat(
                profile_name, messages,
                max_tokens=max_tokens, temperature=temperature,
            )
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
        if action_dict is None:
            finish_reason = usage.get("finish_reason") if isinstance(usage, dict) else None
            return None, _no_json_error(text, finish_reason), meta

        # Optional EM-066 trace fields must never fail a turn — truncate, don't reject.
        _sanitize_optional_trace_fields(action_dict)

        schema_error = _validate_schema(action_dict)
        if schema_error:
            return None, f"schema error: {schema_error}", meta

        world_error = _validate_world(action_dict, agent, self.world)
        if world_error:
            return None, f"world error: {world_error}", meta

        return action_dict, None, meta

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
            ok, reason, rule = self.world.action_propose_rule(agent, effect, text)
            if ok and rule:
                return {**base, "kind": "rule_proposed",
                        "text": f"{agent.name} proposes rule: {text} (effect={effect})",
                        "payload": {"rule_id": rule.id, "effect": effect,
                                    "text": text, "thought": thought}}
            else:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to propose rule but: {reason}",
                        "payload": {"error": reason}}

        elif action == "vote":
            rule_id = args.get("rule_id", "")
            choice = args.get("choice", False)
            ok, reason, new_status = self.world.action_vote(agent, rule_id, choice)
            if ok:
                events = [{**base, "kind": "rule_vote",
                           "text": f"{agent.name} votes {'YES' if choice else 'NO'} on rule {rule_id}.",
                           "payload": {"rule_id": rule_id, "choice": choice, "thought": thought}}]
                if new_status == "active":
                    events.append({**base, "kind": "rule_passed",
                                   "text": f"Rule {rule_id} PASSED and is now active!",
                                   "payload": {"rule_id": rule_id, "new_status": "active"}})
                elif new_status == "rejected":
                    events.append({**base, "kind": "rule_rejected",
                                   "text": f"Rule {rule_id} was rejected.",
                                   "payload": {"rule_id": rule_id, "new_status": "rejected"}})
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

        else:
            return {**base, "kind": "agent_action",
                    "text": f"{agent.name} does {action}.",
                    "payload": {"action": action, "thought": thought}}

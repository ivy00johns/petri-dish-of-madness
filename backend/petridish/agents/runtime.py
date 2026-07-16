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
import difflib
import hashlib
import inspect
import json
import logging
import re
import time
import uuid
from typing import Any, Callable

import jsonschema

from ..engine.world import (
    World, AgentState, BUILD_TYPES, normalize_plan,
    normalize_charter, AMBITION_GRAMMAR, AMBITION_KINDS,
    CHARTER_MAX_AMBITIONS, CHARTER_CREED_CAP,
)
from ..providers.base import ProviderError
from ..providers.router import Router
from .memory_retrieval import (
    BROADCAST_KINDS,
    RetrievalWeights,
    build_query_text,
    score_candidates,
)

log = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Load the action schema (embedded to avoid file-path issues)
# ──────────────────────────────────────────────────────────────────────────────

ACTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    # EM-199 — a turn carries EITHER a single `action` (legacy/minimal) OR an
    # ordered `actions` sequence. anyOf keeps both forms valid; if both are
    # present, the runtime prefers `actions` (see _normalize_steps).
    "anyOf": [{"required": ["action"]}, {"required": ["actions"]}],
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
        # Wave L / EM-223 — OPTIONAL plan creation/revision, parsed from the SAME
        # single response (zero extra calls). Malformed revisions are normalized
        # or stripped BEFORE validation (_sanitize_plan_revision) so a bad plan
        # can never fail the turn. Honored only when world.planning.enabled.
        "plan_revision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["goal", "steps"],
            "properties": {
                "goal": {"type": "string", "maxLength": 200},
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 8,
                    "items": {"type": "string", "maxLength": 120},
                },
                "reason": {"type": "string", "maxLength": 200},
            },
        },
        # EM-311 — OPTIONAL self-authored charter rewrite, parsed from the SAME
        # single response (zero extra calls). The TIGHT enum grammar (EM-297
        # schema-probe discipline): `ambitions` items are constrained to the legal
        # AMBITION_KINDS, so an off-grammar kind fails the schema — but the
        # sanitizer (_sanitize_charter_revision) runs FIRST and normalizes/strips a
        # malformed revision so a bad charter can never fail the turn. Honored only
        # when world.charters.enabled.
        "charter_revision": {
            "type": "object",
            "additionalProperties": False,
            "required": ["ambitions"],
            "properties": {
                "ambitions": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": CHARTER_MAX_AMBITIONS,
                    "items": {"type": "string", "enum": list(AMBITION_KINDS)},
                },
                "creed": {"type": "string", "maxLength": CHARTER_CREED_CAP},
                "reason": {"type": "string", "maxLength": 200},
            },
        },
        # Wave E / EM-125 — OPTIONAL reflection-declared bond, offered in-prompt
        # ONLY alongside a reflection request; rides the SAME single response
        # (zero extra calls). Malformed/disallowed bonds are stripped BEFORE
        # validation (_sanitize_bond) so a bad bond can never fail the turn.
        "bond": {
            "type": "object",
            "additionalProperties": False,
            "required": ["target", "type"],
            "properties": {
                "target": {"type": "string", "maxLength": 60},
                "type": {
                    "type": "string",
                    "enum": ["friend", "partner", "mentor", "feud"],
                },
            },
        },
        "action": {
            "type": "string",
            "enum": [
                "move_to", "say", "whisper", "work", "forage", "recharge",
                "give", "steal", "insult", "attack", "set_relationship",
                "remember", "propose_rule", "vote", "idle",
                # EM-240 — offensive crime verbs (Task 6): big-score theft, a
                # shakedown for credits, and building sabotage short of arson.
                "heist", "extort", "vandalize",
                # EM-237 — harm-surface finishers: threaten without contact (fear);
                # lie as a first-class act (plant a false belief).
                "intimidate", "deceive",
                # EM-240 — economy & corruption verbs (Task 7): cool your own heat
                # for a cut; pay a co-located enforcer to drop it (catchable).
                "launder", "bribe",
                # EM-240 — conspiracy verbs (Task 8): pitch a co-located agent on a
                # criminal pact; seal an offered pact into a warm ring bond.
                "recruit", "accept_contract",
                # EM-240 — enforcer justice verbs (Task 10): question witnesses to
                # confirm a suspect's crimes; publicly accuse; jail the wanted.
                "investigate", "accuse", "detain",
                # W7 / EM-060+062 construction actions (action-protocol v1.1.0).
                "propose_project", "contribute_funds", "build_step",
                "repair", "arson", "take_offline",
                # W11b / EM-091 — billboard reflex tools (plaza/townhall only).
                "post_billboard", "read_billboard",
                # Wave I / EM-210+211 — The Atelier reflex tools: generate art
                # anywhere; share an existing gallery image on the billboard.
                "create_image", "post_image",
                # EM-298 — agent-authored facades: paint a mural/sign/graffiti onto
                # a co-located building's facade (a decal; extends the image lane).
                "paint_surface",
                # Wave H4 / EM-209 — pets & bonds: adopt a co-located unowned
                # animal, feed a co-located one (owner sustains a declining pet).
                "adopt", "feed_pet",
                # EM-228 — cooperation lever: teach a co-located lower-skilled
                # agent a skill you outrank them in; ASK a more-skilled co-located
                # agent to teach you one (parks a pending request they perceive).
                "teach_skill", "request_skill",
                # EM-230 — real trade: offer a co-located agent a two-sided deal
                # (credits and/or a skill-lesson each way); accept/decline the offer
                # addressed to you (an ATOMIC swap that runs only if both can pay).
                "offer_trade", "accept_trade", "decline_trade",
                # EM-231 — cooperation handshake + the ONE gated action: offer a
                # co-located agent a partnership; accept the offer addressed to you
                # (forms the active link); co_build a building with a co-located
                # partner you've agreed to cooperate with (a bonus over solo build).
                "offer_cooperation", "accept_cooperation", "co_build",
                # EM-232 — Victory Arch: pitch your contribution (parks a pitch the
                # periodic peer-judge cycle ranks + awards). Reflex, no target.
                "pitch_contribution",
                # EM-235 — boost queue: spend credits for an EXTRA scheduled turn
                # (buy influence over the shared timeline). Reflex, no target.
                "buy_turn",
                # Wave K / EM-218–220 — the builders'-city reflex tools: place /
                # remove a decoration prop, cleanly demolish a building you own,
                # re-skin a building you own.
                "place_prop", "remove_prop", "demolish", "set_building_skin",
                # EM-243 (S2) — extend the road graph one axis-aligned block from
                # the node nearest you, paid in energy (grow-only).
                "build_road",
                # EM-258/EM-259 — the war verbs (Wave O War stage C), all reflex:
                # muster joins your faction's war band; clash is the seeded combat
                # contest against a co-located enemy belligerent; siege routes
                # building damage through the shared _damage_building path.
                # Offered only while the agent's faction is at war (peacetime
                # golden intact — see _assemble_context).
                "muster", "clash", "siege",
                # EM-251 — culture transmission verbs (Wave O Culture stage),
                # both reflex: spread_rumor whispers a distorting rumor to a
                # co-located agent; send_letter mails ANY citizen (present or
                # absent). Offered only while comm.enabled (see _assemble_context)
                # — the default-OFF prompt/menu stays byte-identical (em161).
                "spread_rumor", "send_letter",
                # EM-253 — culture lifecycle verbs (reflex): create_meme coins an
                # idea; adopt_meme takes up an existing meme (image memes drift).
                "create_meme", "adopt_meme",
                # EM-261 — found a faith and become its first devotee (reflex,
                # free; offered only while faith_enabled AND the agent is faithless).
                "found_faith",
                # EM-262 — religion emergence (reflex; faith_enabled). proselytize
                # converts a co-located faithless agent to the actor's faith;
                # worship draws a devotion buff at a co-located consecrated temple.
                "proselytize", "worship",
                # EM-263 — the religion conflict surface (reflex; faith_enabled,
                # FOUNDER-only). excommunicate casts a member out of the founder's
                # faith (no co-location); declare_hostility marks a rival faith
                # hostile (and, with war on, feeds a religious grievance).
                "excommunicate", "declare_hostility",
                # EM-269 (F2) — found a settlement centered at your current
                # place (a free-placement cluster seed; reflex, free).
                "found_settlement",
                # EM-110 — travel to another settlement (goes off-board, arrives
                # a few rounds later; offered only when >1 settlement exists).
                "travel_to",
                # PROTOTYPE (god-channel) — answer the active proclamation (the
                # threaded return path; offered only while a decree is live).
                "answer_proclamation",
            ],
        },
        "args": {"type": "object", "default": {}},
        # EM-199 — multi-action turns: an ORDERED sequence applied in order, all
        # from this single response, emitted as one _multi chain sharing one
        # turn_id. Per-step args are validated at RESOLUTION (continue-on-
        # failure), so items only check the action enum + args-is-object here.
        # maxItems is a generous schema ceiling; the runtime enforces the
        # configurable max_actions_per_turn (default 4) and truncates+logs above.
        # additionalProperties is TRUE (EM-066 ethos): free models routinely
        # scatter per-action cognition (thought/perceived_summary/memories_used/
        # reasoning) INTO each step — the runtime reads only action+args and
        # ignores the rest, so a misplaced cosmetic field must NEVER fail the
        # turn (the kimi idle-fallback regression). Stray cognition on the first
        # step is hoisted to top-level by _hoist_step_cognition before validation.
        "actions": {
            "type": "array",
            "minItems": 1,
            "maxItems": 16,
            "items": {
                "type": "object",
                "required": ["action"],
                "additionalProperties": True,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": [
                            "move_to", "say", "whisper", "work", "forage", "recharge",
                            "give", "steal", "insult", "attack", "set_relationship",
                            "remember", "propose_rule", "vote", "idle",
                            # EM-240 — offensive crime verbs (Task 6).
                            "heist", "extort", "vandalize",
                            # EM-237 — harm-surface finishers.
                            "intimidate", "deceive",
                            # EM-240 — economy & corruption verbs (Task 7).
                            "launder", "bribe",
                            # EM-240 — conspiracy verbs (Task 8).
                            "recruit", "accept_contract",
                            # EM-240 — enforcer justice verbs (Task 10).
                            "investigate", "accuse", "detain",
                            "propose_project", "contribute_funds", "build_step",
                            "repair", "arson", "take_offline",
                            "post_billboard", "read_billboard", "answer_proclamation",
                            # Wave I / EM-210+211 — The Atelier reflex tools.
                            "create_image", "post_image",
                            # EM-298 — agent-authored facades.
                            "paint_surface",
                            "adopt", "feed_pet",
                            # EM-228 — teach / request skills (cooperation lever).
                            "teach_skill", "request_skill",
                            # EM-230 — real trade: offer / accept / decline.
                            "offer_trade", "accept_trade", "decline_trade",
                            # EM-231 — cooperation handshake + co_build.
                            "offer_cooperation", "accept_cooperation", "co_build",
                            # EM-232 — Victory Arch: pitch your contribution.
                            "pitch_contribution",
                            # EM-235 — boost queue: buy an extra scheduled turn.
                            "buy_turn",
                            # Wave K / EM-218–220 — builders'-city reflex tools.
                            "place_prop", "remove_prop", "demolish",
                            "set_building_skin",
                            # EM-243 (S2) — extend the road graph one block.
                            "build_road",
                            # EM-258/EM-259 — the war verbs (reflex).
                            "muster", "clash", "siege",
                            # EM-251 — culture transmission verbs (reflex).
                            "spread_rumor", "send_letter",
                            # EM-253 — culture lifecycle verbs (reflex).
                            "create_meme", "adopt_meme",
                            # EM-261 — found a faith (reflex; faith_enabled + faithless).
                            "found_faith",
                            # EM-262 — religion emergence (reflex; faith_enabled).
                            "proselytize", "worship",
                            # EM-263 — religion conflict surface (reflex; founder).
                            "excommunicate", "declare_hostility",
                            # EM-269 (F2) — found a settlement here.
                            "found_settlement",
                            # EM-110 — travel to another settlement.
                            "travel_to",
                        ],
                    },
                    "args": {"type": "object", "default": {}},
                },
            },
        },
    },
    # Per-action arg requirements mirrored from action-protocol.schema.json so the
    # inline schema validates the 6 new construction actions structurally (the
    # canonical contract is contracts/action-protocol.schema.json). Only the
    # behavioral args are validated strictly here; cosmetic/optional args are open.
    "allOf": [
        {"if": {"required": ["action"], "properties": {"action": {"const": "propose_project"}}},
         "then": {"properties": {"args": {"required": ["name", "kind"], "properties": {
             "name": {"type": "string", "maxLength": 60},
             "kind": {"type": "string", "maxLength": 30},
             "funds_required": {"type": "integer", "minimum": 1},
             "function": {"type": "string", "maxLength": 40},
             # Wave K / EM-182 — OPTIONAL chosen build place (a district id).
             "place": {"type": "string"},
             # EM-266 (SC) — OPTIONAL targeted zone (a planar-face id). Loose: an
             # absent/unresolvable id is fine (falls back to auto-placement) — never
             # a rejection, the build is always free.
             "zone_id": {"type": "string"},
             # EM-299 (Wave Q) — OPTIONAL parametric recipe (a shape object). LOOSE
             # on purpose: the world coerces bad fields to defaults / drops a
             # non-object, so a malformed shape never fails the turn (the closed-enum
             # grammar is documented in contracts/em299-building-recipes.md and
             # enforced server-side, not by this structural gate).
             "recipe": {"type": "object"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "contribute_funds"}}},
         "then": {"properties": {"args": {"required": ["building_id", "amount"], "properties": {
             "building_id": {"type": "string"},
             "amount": {"type": "integer", "minimum": 1},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "build_step"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "repair"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "arson"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "take_offline"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "post_billboard"}}},
         "then": {"properties": {"args": {"required": ["text"], "properties": {
             "text": {"type": "string", "maxLength": 280},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "answer_proclamation"}}},
         "then": {"properties": {"args": {"required": ["text"], "properties": {
             "text": {"type": "string", "maxLength": 280},
         }}}}},
        # EM-110 — travel_to REQUIRES a settlement id-or-name (the world action
        # resolves + gates it; a missing target is a schema failure, never a dead
        # turn on a bad guess).
        {"if": {"required": ["action"], "properties": {"action": {"const": "travel_to"}}},
         "then": {"properties": {"args": {"required": ["settlement"], "properties": {
             "settlement": {"type": "string", "maxLength": 60},
         }}}}},
        # Wave I / EM-210+211 — The Atelier: create_image REQUIRES a prompt (≤240);
        # post_image takes an OPTIONAL image_id (defaults to the agent's newest).
        {"if": {"required": ["action"], "properties": {"action": {"const": "create_image"}}},
         "then": {"properties": {"args": {"required": ["prompt"], "properties": {
             "prompt": {"type": "string", "maxLength": 240},
         }}}}},
        # EM-298 — paint_surface REQUIRES a target building id + a prompt (≤240).
        {"if": {"required": ["action"], "properties": {"action": {"const": "paint_surface"}}},
         "then": {"properties": {"args": {"required": ["target", "prompt"], "properties": {
             "target": {"type": "string"},
             "prompt": {"type": "string", "maxLength": 240},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "post_image"}}},
         "then": {"properties": {"args": {"properties": {
             "image_id": {"type": "string"},
         }}}}},
        # Wave H4 / EM-209 — pets & bonds: both reflex tools require an animal_id.
        {"if": {"required": ["action"], "properties": {"action": {"const": "adopt"}}},
         "then": {"properties": {"args": {"required": ["animal_id"], "properties": {
             "animal_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "feed_pet"}}},
         "then": {"properties": {"args": {"required": ["animal_id"], "properties": {
             "animal_id": {"type": "string"},
         }}}}},
        # Wave K / EM-218–220 — builders'-city reflex tools. Only the behavioral
        # args are validated strictly; `place` on place_prop is OPTIONAL (defaults
        # to the agent's location at resolution), so it is not required here.
        {"if": {"required": ["action"], "properties": {"action": {"const": "place_prop"}}},
         "then": {"properties": {"args": {"required": ["kind"], "properties": {
             "kind": {"type": "string", "maxLength": 30},
             "place": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "remove_prop"}}},
         "then": {"properties": {"args": {"required": ["prop_id"], "properties": {
             "prop_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "demolish"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "set_building_skin"}}},
         "then": {"properties": {"args": {"required": ["building_id", "skin"], "properties": {
             "building_id": {"type": "string"},
             "skin": {"type": "string", "maxLength": 24},
         }}}}},
        # EM-243 (S2) — build_road requires a cardinal direction.
        {"if": {"required": ["action"], "properties": {"action": {"const": "build_road"}}},
         "then": {"properties": {"args": {"required": ["direction"],
                  "properties": {"direction": {"enum": ["north", "south", "east", "west"]}}}}}},
        # EM-258 — clash requires a target (the co-located enemy belligerent,
        # name or id — resolved like attack). muster takes no args.
        {"if": {"required": ["action"], "properties": {"action": {"const": "clash"}}},
         "then": {"properties": {"args": {"required": ["target"], "properties": {
             "target": {"type": "string"},
         }}}}},
        # EM-259 — siege requires the enemy building's id (like vandalize/arson).
        {"if": {"required": ["action"], "properties": {"action": {"const": "siege"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"},
         }}}}},
        # EM-251 — spread_rumor requires a co-located target (name or id, resolved
        # like clash/deceive); the rumor free-text is optional (a carried meme_id
        # can source it instead), so only `target` is structurally required.
        {"if": {"required": ["action"], "properties": {"action": {"const": "spread_rumor"}}},
         "then": {"properties": {"args": {"required": ["target"], "properties": {
             "target": {"type": "string"},
         }}}}},
        # EM-251 — send_letter requires a target (any living citizen, present or
        # absent) AND the letter text.
        {"if": {"required": ["action"], "properties": {"action": {"const": "send_letter"}}},
         "then": {"properties": {"args": {"required": ["target", "text"], "properties": {
             "target": {"type": "string"}, "text": {"type": "string"},
         }}}}},
        # EM-253 — create_meme requires the idea text; adopt_meme requires the
        # target meme_id (an existing registered meme, not a name → NOT in
        # _TARGETED_ACTIONS).
        {"if": {"required": ["action"], "properties": {"action": {"const": "create_meme"}}},
         "then": {"properties": {"args": {"required": ["text"], "properties": {
             "text": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "adopt_meme"}}},
         "then": {"properties": {"args": {"required": ["meme_id"], "properties": {
             "meme_id": {"type": "string"},
         }}}}},
        # EM-262 — proselytize requires a co-located target (name or id, resolved
        # like clash/spread_rumor); worship takes no args (the seat is at the
        # agent's own place), so it needs no allOf entry.
        {"if": {"required": ["action"], "properties": {"action": {"const": "proselytize"}}},
         "then": {"properties": {"args": {"required": ["target"], "properties": {
             "target": {"type": "string"},
         }}}}},
        # EM-263 — excommunicate requires an agent `target` (a member of the
        # founder's faith, resolved by name/id — NOT co-location gated);
        # declare_hostility requires a `faith_id` (a rival faith's id, resolved
        # against world.faiths — not an agent target, like adopt_meme's meme_id).
        {"if": {"required": ["action"], "properties": {"action": {"const": "excommunicate"}}},
         "then": {"properties": {"args": {"required": ["target"], "properties": {
             "target": {"type": "string"},
         }}}}},
        {"if": {"required": ["action"], "properties": {"action": {"const": "declare_hostility"}}},
         "then": {"properties": {"args": {"required": ["faith_id"], "properties": {
             "faith_id": {"type": "string"},
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
    # EM-240 — offensive crime verbs (Task 6). heist/extort target an agent;
    # vandalize targets a co-located building (@building gate, like arson).
    "heist":            {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_stealing"},
    "extort":           {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_extortion"},
    "vandalize":        {"tier": "reflex", "location_gate": "@building",     "agreement_gate": "ban_vandalism"},
    # EM-237 — harm-surface finishers. Both target a co-located/visible agent (the
    # co-location gate lives in _validate_world like extort — a relationship rule,
    # not a place rule). No agreement_gate: no governance rule guards them yet.
    # Reflex — they ride the existing turn, zero extra LLM calls.
    "intimidate":       {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "deceive":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-240 — economy & corruption verbs (Task 7). launder cools your own heat
    # for a cut (no target, no gate); bribe pays a co-located enforcer (target =
    # the enforcer) — co-location is enforced in _validate_world like steal.
    "launder":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "bribe":            {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-240 — conspiracy verbs (Task 8). recruit pitches a co-located agent (no
    # gate; co-location enforced in _validate_world); accept_contract takes no
    # target (rejected unless an open offer is addressed to the accepting agent).
    "recruit":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "accept_contract":  {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-240 — enforcer justice verbs (Task 10). All target a co-located agent
    # (resolved like steal). No location_gate / agreement_gate here — the
    # ENFORCER role gate lives in _validate_world (role rule, not a place rule).
    "investigate":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "accuse":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "detain":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # Social / governance → llm-served (the reasoning-heavy choices).
    "say":              {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "whisper":          {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "insult":           {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "attack":           {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "set_relationship": {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
    "propose_rule":     {"tier": "llm",    "location_gate": "governance",    "agreement_gate": None},
    # EM-199 — voting is un-gated (location_gate None): governance was dead
    # because only the proposer, at Town Hall, ever voted (run 648 — Mox alone),
    # so no rule reached a majority. Civic participation now works from anywhere;
    # PROPOSING still requires Town Hall (a deliberate civic act).
    "vote":             {"tier": "llm",    "location_gate": None,            "agreement_gate": None},
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
    # Wave I / EM-210+211 — The Atelier reflex tools 🟢: create_image is UNGATED
    # (make art anywhere); post_image is @billboard-gated (share it where the board
    # stands). Both zero extra LLM calls — the prompt/choice rides the agent's
    # existing turn; the PNG bytes come from a free endpoint OFF the critical path.
    "create_image":     {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "post_image":       {"tier": "reflex", "location_gate": "@billboard",    "agreement_gate": None},
    # EM-298 — agent-authored facades 🟢: paint a decal onto a co-located building's
    # facade. @building-gated (a building must be here, resolved per-turn like
    # repair/arson); the world action also enforces the EM-210 image_gen kill switch.
    # Reflex, zero extra LLM calls (the prompt rides the agent's existing turn; the
    # PNG comes from the free image chain OFF the critical path).
    "paint_surface":    {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    # Wave H4 / EM-209 — pets & bonds reflex tools 🟢: no location_gate (the
    # CO-LOCATION gate is animal-specific and enforced in _validate_world), no
    # agreement_gate. adopt claims a co-located unowned animal; feed_pet restores
    # a co-located animal's energy. Both move NO credits (invariant 7). Offered
    # only when a co-located eligible animal exists (see _assemble_context).
    "adopt":            {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "feed_pet":         {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-228 — cooperation lever reflex tools. No location_gate / agreement_gate:
    # the CO-LOCATION gate (teacher must outrank; both must be present) lives in
    # _validate_world (a relationship rule, not a place rule), exactly like the
    # EM-240 recruit verb. Offered only when a plausible co-located target exists
    # (see _assemble_context). Zero extra LLM calls — they ride the existing turn.
    "teach_skill":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "request_skill":    {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-230 — real-trade reflex tools. offer_trade targets a co-located agent (the
    # co-location gate lives in _validate_world, like teach_skill — a relationship
    # rule, not a place rule). accept_trade / decline_trade take NO target (the open
    # offer is keyed by the accepting agent's id, like accept_contract) and are
    # gated on "an offer is addressed to you". All reflex — the swap rides the
    # existing turn, zero extra LLM calls.
    "offer_trade":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "accept_trade":     {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "decline_trade":    {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-231 — cooperation handshake + the ONE gated action. offer_cooperation
    # targets a co-located agent (the co-location gate lives in _validate_world,
    # like teach_skill — a relationship rule). accept_cooperation takes NO target
    # (the open offer is keyed by the accepting agent's id, like accept_contract).
    # co_build gates to the building's OWN place ("@building", resolved per-turn,
    # like build_step) PLUS a COOPERATION gate (an active handshake + a co-located
    # partner) enforced in _validate_world. All reflex — they ride the existing
    # turn, zero extra LLM calls.
    "offer_cooperation":  {"tier": "reflex", "location_gate": None,          "agreement_gate": None},
    "accept_cooperation": {"tier": "reflex", "location_gate": None,          "agreement_gate": None},
    "co_build":           {"tier": "reflex", "location_gate": "@building",   "agreement_gate": None},
    # EM-232 — Victory Arch pitch reflex tool. No location_gate / agreement_gate:
    # an agent may pitch their contribution from anywhere (the pitch text rides the
    # existing turn, zero extra LLM calls). Offered in the menu only when the
    # Victory Arch is configured ON (see _assemble_context), so a default world's
    # em161 golden is byte-identical. action_pitch_contribution parks it keyed by
    # the pitcher; the periodic cycle judges + clears the queue.
    "pitch_contribution": {"tier": "reflex", "location_gate": None,          "agreement_gate": None},
    # EM-235 — boost queue reflex tool. No location_gate / agreement_gate: an agent
    # may buy an extra turn from anywhere (the buy rides the existing turn, zero
    # extra LLM calls; action_buy_turn charges credits + queues the extra slot).
    # Offered in the menu only when the boost queue is configured ON AND the agent
    # can afford it (see _assemble_context), so a default world's em161 golden is
    # byte-identical.
    "buy_turn":           {"tier": "reflex", "location_gate": None,          "agreement_gate": None},
    # Wave K / EM-218–220 — builders'-city reflex tools. place_prop / remove_prop
    # are offered ANYWHERE (place_prop takes a target place arg; remove_prop's
    # co-location gate is prop-specific and enforced in _validate_world). demolish
    # / set_building_skin gate to the building's OWN place ("@building", resolved
    # per-turn) and are owner-only (enforced at resolution). All zero extra LLM
    # calls — the kind/skin rides the agent's existing turn.
    "place_prop":       {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "remove_prop":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "demolish":         {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    "set_building_skin": {"tier": "reflex", "location_gate": "@building",    "agreement_gate": None},
    # EM-243 (S2) — extend the road graph one block; offered anywhere (the real
    # gate is energy + an open direction, computed in _assemble_context).
    "build_road":       {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-258/EM-259 — the war verbs 🟢, all REFLEX (zero extra LLM calls — the
    # engine resolves the seeded contest deterministically; MAX-call-rate ethos).
    # muster/clash carry no location_gate (the co-location + at-war gates are
    # war-specific, enforced by the world action exactly like recruit); siege
    # gates to the building's OWN place ("@building", resolved per-turn like
    # vandalize/arson). No agreement_gate — a war is already a ratified vote.
    # Offered ONLY while the agent's faction is at war (see _assemble_context),
    # so the peacetime prompt/menu — and the em161 golden — never change.
    "muster":           {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "clash":            {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "siege":            {"tier": "reflex", "location_gate": "@building",     "agreement_gate": None},
    # EM-251 — culture transmission verbs 🟢, both REFLEX (zero extra LLM calls).
    # spread_rumor's co-location gate is war-style — enforced by the world action
    # (like recruit), NOT a place gate; send_letter has NO location gate BY DESIGN
    # (the first absent-target channel). Offered ONLY while comm.enabled (see
    # _assemble_context), so the default-OFF menu — and the em161 golden — never
    # change. EM-254 — spread_rumor now carries the ban_gossip agreement_gate
    # (steal→ban_stealing's twin): a ratified ban hides it from the menu (via
    # _gate_ok) AND the validator rejects it. ban_gossip is itself un-proposable
    # without comm, so a comm-off world never activates it ⇒ the gate is inert
    # there ⇒ byte-identical. send_letter stays ungated (a letter is not gossip).
    "spread_rumor":     {"tier": "reflex", "location_gate": None,            "agreement_gate": "ban_gossip"},
    "send_letter":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-253 — culture lifecycle verbs (Wave O Culture stage), both reflex, no
    # gates. create_meme coins an idea (no target, ungated by co-location);
    # adopt_meme takes up an existing meme by id (an image meme drifts a child
    # image). Offered ONLY while comm.enabled — and adopt_meme only with an
    # adoptable meme — see _assemble_context, so the default-OFF menu (and the
    # em161 golden) never change.
    "create_meme":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "adopt_meme":       {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-261 — found a faith; offered anywhere (the real gates — faith.enabled +
    # the agent being faithless — are computed in _assemble_context and re-enforced
    # at resolution in action_found_faith, which rejects a faith-off/already-faithful
    # attempt). No args, like found_settlement.
    "found_faith":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-262 — religion emergence 🟢, both REFLEX (zero extra LLM calls — the
    # engine resolves the seeded conversion / temple buff). proselytize targets a
    # co-located agent (the co-location + faith gates are faith-specific, enforced
    # by the world action like clash/recruit — NOT a place gate); worship carries
    # no location_gate either (the seat is checked per-turn by _faith_seat_here,
    # like build_step's @building but faith-scoped). No agreement_gate. Offered
    # ONLY while faith is enabled AND the agent has a faith (see _assemble_context),
    # so the faith-off prompt/menu — and the em260 golden — never change.
    "proselytize":      {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "worship":          {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-263 — the religion conflict surface, both REFLEX + FOUNDER-only (the real
    # gates — faith.enabled + the actor being their faith's founder — are computed
    # in _assemble_context and re-enforced at resolution in the world actions).
    # excommunicate carries NO location_gate (a founder acts from afar; the target
    # need not be co-located — the send_letter recipe, not clash's); declare_-
    # hostility takes a faith_id, not an agent, and is likewise ungated here. No
    # agreement_gate. Offered ONLY while faith is enabled AND the agent founded a
    # faith (see _assemble_context), so the faith-off menu — and the em260 golden —
    # never change.
    "excommunicate":    {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    "declare_hostility": {"tier": "reflex", "location_gate": None,           "agreement_gate": None},
    # EM-269 (F2) — found a settlement at your current place; offered anywhere
    # (the real gates — settlements.enabled + unclaimed ground — are computed in
    # _assemble_context and re-enforced at resolution in action_found_settlement).
    "found_settlement": {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
    # EM-110 — travel to ANOTHER settlement; offered anywhere (the real gates —
    # settlements.enabled + >1 settlement + a valid, non-home target — are
    # computed in _assemble_context and re-enforced in action_travel_to). Reflex:
    # zero extra LLM calls; the trip itself takes the agent OFF-BOARD (0 calls
    # while traveling — the free-scale saving).
    "travel_to":        {"tier": "reflex", "location_gate": None,            "agreement_gate": None},
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
# EM-231 NOTE: co_build is NOT tier-gated — like the other REFLEX building verbs
# (repair / arson / take_offline) it stays open to every tier. Its real gate is
# the COOPERATION handshake (an active link + a co-located partner), enforced in
# _validate_world; the tier-pinning test (test_tier_gated_constant_shape) is left
# byte-stable.


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
# renders bucketed to 10s ("~70", floored) so quiet rounds assemble
# byte-identical prompts and the router's sha1 decision cache can hit.
# Router.forget() semantics untouched.
#
# Wave D3 / EM-171 — EM-162's payoff measured 0% in integration; the
# normalization extends (still BACKGROUND only, protagonist/supporting
# byte-identical to pre-diet):
#   - the tick line is DROPPED (the day-floored form still missed — a
#     25-turn round spans >1 in-world day, so consecutive background due
#     turns never share a day);
#   - memory lines render de-ticked ("  - <text>", no raw tick stamp);
#   - co-located rosters and building/project menus render in sorted order
#     so equivalent situations assemble identical bytes regardless of dict
#     insertion order.
# ──────────────────────────────────────────────────────────────────────────────

_DIET_RELATIONSHIP_CAP = 8
_DIET_BACKGROUND_MEMORY_WINDOW = 8
_DIET_CORE_DISTRICT = "core"
# EM-285 — the constitution block rides EVERY prompt; render at most the N most
# recent unique articles so ratified-article growth can't bloat every turn
# unboundedly (the header still reports the true total). Prompt-diet vs the
# max-call-rate north star.
_CONSTITUTION_RENDER_MAX = 12
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
    # Wave H4 / EM-209 — losing an OWNED pet is acutely salient to the owner: it
    # pulls their next LLM turn (the grief reflection is GUARANTEED separately by
    # the animal runtime emitting a reflection attributed to the owner, but this
    # weight lets the owner ALSO add its own words). Carried on the same
    # animal_died event for an owned pet (payload.owner_id set).
    "pet_death": 4.0,
    "conflict": 3.0,
    "rule_passed": 2.0,
    "rule_rejected": 2.0,
    "rule_proposed": 1.0,
    "agent_starving": 2.0,
    "structure_state_changed": 1.0,
    "building_operational": 2.0,
    # Wave E / EM-184 — a god miracle is town-news (globally witnessed in
    # push_event, like random_event) and salient enough to pull a background
    # agent's next due turn (existing EM-159 machinery — no new calls).
    "god_miracle": 2.0,
}
_IMPORTANCE_ECONOMY_SWING = 8      # |credits moved| at/above this scores...
_IMPORTANCE_ECONOMY_WEIGHT = 2.0   # ...this much

_DEFAULT_PHANTOM_AFTER_TURNS = 12
_DEFAULT_MAX_ACTIVE_COMMITMENTS = 5
_DEFAULT_IMPORTANCE_THRESHOLD = 10.0
_OVERHEARD_PENDING_CAP = 2         # an agent holds at most 2 pending overheard lines
_OVERHEARD_LISTENERS_CAP = 2       # at most 2 co-located listeners per spoken line
_RECENT_SAID_CAP = 5               # EM-322 — per-agent recent spoken lines fed back
                                   # as an explicit anti-repeat block in the prompt

# Wave D2 / EM-159+160 — background-tier cadence defaults (config
# `world.cadence`, read via _world_block_get; the loader's CadenceParams
# mirrors these exactly so an absent block behaves identically).
_DEFAULT_SPONTANEITY_CHANCE = 0.15
_DEFAULT_REFLEX_STREAK_LIMIT = 8

# Wave D2 / EM-159 — energy "bands" for the salience trigger: crossing a
# 25-point band boundary since the agent's last LLM turn is salient (covers
# both "I drifted toward starving" and "someone blessed/attacked me").
_ENERGY_BAND_SIZE = 25.0

# Wave D3 / EM-172 — band hysteresis margin: recharge-to-full flapping right
# at a band edge (99.x ⇄ 100 across the top-band boundary) re-triggered the
# energy_band salience every drift, inflating background LLM turns. The band
# only FLIPS once energy leaves the seen band's range by MORE than this
# margin; movement within the margin of the old band's edges stays quiet.
_ENERGY_BAND_HYSTERESIS = 5.0


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


def _energy_band_flipped(energy: float, seen_band: int) -> bool:
    """EM-172 — hysteresis for the EM-159 energy_band salience trigger.

    True only when `energy` has left `seen_band`'s range by MORE than
    _ENERGY_BAND_HYSTERESIS. An agent recharging to full and drifting back
    (99.x ⇄ 100, a band edge) used to flip the band — and trigger a salient
    background LLM turn — on every oscillation; within-margin wobble around
    the old band's edges is now quiet. A genuine crossing (starving drift,
    an attack) clears the margin and still fires."""
    try:
        e = max(0.0, min(100.0, float(energy)))
    except (TypeError, ValueError):
        e = 0.0
    if _energy_band(e) == seen_band:
        return False
    low = seen_band * _ENERGY_BAND_SIZE - _ENERGY_BAND_HYSTERESIS
    high = (seen_band + 1) * _ENERGY_BAND_SIZE + _ENERGY_BAND_HYSTERESIS
    return not (low <= e < high)


def _world_block_get(params: Any, block: str, key: str, default: Any) -> Any:
    """Read `world.<block>.<key>` defensively: the block may be a dataclass, a
    plain dict, or absent (the config loader is owned elsewhere)."""
    blk = getattr(params, block, None)
    if blk is None:
        return default
    if isinstance(blk, dict):
        return blk.get(key, default)
    return getattr(blk, key, default)


def _planning_enabled(params: Any) -> bool:
    """Wave L / EM-223 — config gate `world.planning.enabled` (default False).
    Disabled ⇒ no plan block, no plan invite, plan_revision ignored: the prompt
    and snapshot are byte-identical to pre-EM-223."""
    return bool(_world_block_get(params, "planning", "enabled", False))


def _building_recipes_enabled(params: Any) -> bool:
    """EM-299 (Wave Q) — config gate `world.building_recipes.enabled` (default
    False). Disabled ⇒ NO recipe clause in the build menu: the prompt is
    byte-identical to pre-EM-299. Enabled ⇒ propose_project offers the OPTIONAL
    shape grammar. Mirrors world._building_recipes_enabled (same config key)."""
    return bool(_world_block_get(params, "building_recipes", "enabled", False))


def _universalization_enabled(params: Any) -> bool:
    """EM-234 — config gate `world.universalization.enabled` (default False).
    Disabled ⇒ NO universalization block in the prompt: the turn context is
    byte-identical to pre-EM-234 (the em161 lawful-citizen golden holds). When
    enabled, every agent's prompt gets the GovSim commons-reasoning scaffold.
    Carries no state, so snapshots are unaffected either way."""
    return bool(_world_block_get(params, "universalization", "enabled", False))


def _coherence_enabled(params: Any) -> bool:
    """EM-224 — config gate `world.coherence.enabled` (default False).
    Disabled ⇒ the coherence bottleneck is a no-op: the turn's actions[] apply
    exactly as pre-EM-224. EM-224 adds NO prompt block and NO agent/world state,
    so the em161 golden and EM-155 snapshots are byte-identical either way."""
    return bool(_world_block_get(params, "coherence", "enabled", False))


def _coherence_strategy(params: Any) -> str:
    """EM-224 — the configured contradiction-handling strategy
    (`world.coherence.strategy`); 'annotate' (keep both, stamp) is the default,
    'drop' suppresses the contradicting step. Unknown ⇒ 'annotate'."""
    strat = _world_block_get(params, "coherence", "strategy", "annotate")
    return strat if strat in ("annotate", "drop") else "annotate"


# EM-224 — the verbs that HARM a target (the coherence bottleneck flags a
# friendly speech act followed by one of these toward the SAME target). Pulled
# from the offensive crime/harm surface (EM-240 + EM-237) plus the base
# steal/attack/insult. A purely structural set — no state, no randomness.
_HARM_VERBS = frozenset({
    "steal", "attack", "insult", "intimidate", "deceive",
    "extort", "vandalize", "heist",
})

# EM-224 — verbs that HELP a target (used for the mirror case: a hostile speech
# act then a helpful act toward the same target is the inverse contradiction).
_HELP_VERBS = frozenset({"give", "teach_skill", "feed_pet"})

# EM-224 — deterministic stance lexicon for the first speech act. A turn's intent
# toward a named target is `friendly` if its speech carries a cooperative cue and
# no hostile cue, `hostile` if it carries a hostile cue, else `neutral`. Pure
# substring matching on the lowercased text — no LLM, no randomness, no clock.
_FRIENDLY_CUES = frozenset({
    "help", "give", "gift", "for you", "take these", "take this", "welcome",
    "friend", "thank", "trust", "share", "please", "happy to", "glad to",
    "support", "here you go", "let me help", "i'll help", "i will help",
})
_HOSTILE_CUES = frozenset({
    "hate", "kill", "destroy", "fool", "trick", "rob", "idiot", "enemy",
    "ruin", "crush", "i'll take", "i will take", "give me everything",
    "hand it over", "or else", "you'll regret", "threat",
})


def _coherence_target(args: dict, agent_names: dict) -> str | None:
    """The agent-id target of a harm/help step, if present and known. Steps are
    normalized BEFORE the coherence pass, so `args['target']` is already an id."""
    tgt = args.get("target") if isinstance(args, dict) else None
    if isinstance(tgt, str) and tgt in agent_names:
        return tgt
    return None


def _name_in_text(low: str, name: str | None) -> bool:
    """Whether an agent name (full, or its first token) appears in lowercased
    text. e.g. 'Bram the Bold' matches on 'bram'."""
    name = (name or "").strip().lower()
    if not name:
        return False
    if name in low:
        return True
    parts = name.split()
    return bool(parts) and parts[0] in low


def _speech_addresses(text: str, target_name: str | None,
                      other_names: tuple[str, ...] = ()) -> bool:
    """EM-224 — does the speech act actually address `target_name`? A stance is
    DIRECTED at a target, so a friendly/hostile remark only bears on a harm/help
    step toward that SAME target. True when the target's name appears in the
    text, OR the speech is a direct second-person address ('you'/'your') that is
    not claimed by a DIFFERENT named agent. Naming another agent ('…you, Cara!')
    binds the second person to that named addressee, so a 'you' alone no longer
    counts as addressing this target. Pure substring match — no LLM/clock/random."""
    low = (text or "").lower()
    if _name_in_text(low, target_name):
        return True
    if "you" in low or "your" in low:
        # second-person address — but only this target's, not one explicitly
        # redirected to a different named agent in the same line.
        names_another = any(_name_in_text(low, n) for n in other_names)
        return not names_another
    return False


def _speech_stance(text: str, target_name: str | None,
                   other_names: tuple[str, ...] = ()) -> str:
    """EM-224 — classify a speech act's stance ('friendly'/'hostile'/'neutral')
    TOWARD `target_name`. Deterministic substring match on the lexicons, but the
    stance is asserted ONLY when the speech actually addresses the target (its
    name or an unredirected second-person 'you'). A friendly/hostile remark about
    a DIFFERENT agent leaves this target's stance 'neutral', so it cannot
    contradict an action toward this target (EM-224 target-blind regression)."""
    if not _speech_addresses(text, target_name, other_names):
        return "neutral"
    low = (text or "").lower()
    has_friendly = any(cue in low for cue in _FRIENDLY_CUES)
    has_hostile = any(cue in low for cue in _HOSTILE_CUES)
    if has_hostile:
        return "hostile"
    if has_friendly:
        return "friendly"
    return "neutral"


def _coherence_resolve(
    steps: list[dict],
    thought: str,
    strategy: str,
    agent_names: dict,
    actor_id: str | None = None,
) -> tuple[list[dict], list[dict]]:
    """EM-224 — the PIANO coherence bottleneck (deterministic, zero-LLM).

    Derive ONE intent from the turn's FIRST speech act (the single decision),
    then reconcile every later harm/help step against it (the broadcast):

    - friendly speech toward target T, then a HARM verb toward the same T → a
      contradiction;
    - hostile speech toward T, then a HELP verb toward the same T → the mirror
      contradiction.

    `strategy`:
      'annotate' — leave the step in place but stamp it with a `_coherence`
        marker (`{"intent": <stance>, "contradicted": True}`) that _apply_steps
        surfaces onto the resulting event (text + payload.coherence); the world
        still mutates, the hypocrisy is just legible.
      'drop' — remove the contradicting step from the list and return a
        synthetic `coherence_note` record so the caller can emit ONE note event
        in its place.

    Returns (resolved_steps, drop_notes). drop_notes is always empty for
    'annotate'. Pure function: no random/clock/uuid, same input ⇒ same output."""
    # The single decision: the FIRST speech act's stance toward its addressed
    # target. v1 reads the target from the FIRST subsequent harm/help step (the
    # speech rarely names an id; the action does). If no speech act and no
    # harm/help step coexist, there is no intent to enforce → no-op.
    first_speech = next(
        (s for s in steps if s.get("action") in ("say", "whisper")), None
    )
    if first_speech is None:
        return steps, []
    speech_text = ""
    sargs = first_speech.get("args")
    if isinstance(sargs, dict):
        speech_text = str(sargs.get("text") or "")

    resolved: list[dict] = []
    drop_notes: list[dict] = []
    speech_idx = steps.index(first_speech)
    for idx, step in enumerate(steps):
        action = step.get("action")
        # Only LATER steps (after the speech) are reconciled against the intent.
        if idx <= speech_idx or action not in _HARM_VERBS and action not in _HELP_VERBS:
            resolved.append(step)
            continue
        target = _coherence_target(step.get("args") or {}, agent_names)
        if target is None:
            resolved.append(step)
            continue
        # A self-targeted harm/help after friendly speech is not hypocrisy toward
        # another agent → never a contradiction (EM-224 self-harm regression).
        if actor_id is not None and target == actor_id:
            resolved.append(step)
            continue
        # The stance must be directed at THIS target: a second-person 'you' is
        # claimed by any OTHER agent the speech names, so it cannot bind here.
        target_name = agent_names.get(target)
        other_names = tuple(
            n for aid, n in agent_names.items() if aid != target and n
        )
        stance = _speech_stance(speech_text, target_name, other_names)
        contradicted = (
            (stance == "friendly" and action in _HARM_VERBS)
            or (stance == "hostile" and action in _HELP_VERBS)
        )
        if not contradicted:
            resolved.append(step)
            continue
        if strategy == "drop":
            drop_notes.append({
                "intent": stance,
                "dropped_action": action,
                "target_id": target,
                "target_name": agent_names.get(target),
            })
            # the step is suppressed: NOT appended to resolved
            continue
        # 'annotate' (and the reserved 'reorder' fallback): keep, but stamp.
        marked = dict(step)
        marked["_coherence"] = {"intent": stance, "contradicted": True}
        resolved.append(marked)
    return resolved, drop_notes


def _rule_label(text: str, limit: int = 300) -> str:
    """EM-100 — the human-readable rule label for feed text (quoted by callers).
    Cap = 300 to match the amend_constitution creation cap (action_propose_rule
    stores text[:300]), so a constitutional amendment / rule proposal reads in FULL
    in the vote feed line — legible, not clipped to a 60-char blurb (the full text
    already lives in rule.text; this is the one-line feed rendering). Never the bare
    uuid."""
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


# EM-265 (SB) — district-scoped zone perception (prompt-diet: hard line cap,
# omitted when empty). A deterministic, seeded flavor name per face id so the same
# block always reads the same in the prompt + across replay/fork.
_ZONE_NAME_POOL: tuple[str, ...] = (
    "Market Quarter", "Riverside", "Old Town", "The Commons", "Hillcrest",
    "Garden Row", "Northgate", "Southgate", "Kiln Ward", "Lantern Square",
    "Mill District", "Harbor End", "Stonecross", "Elmgrove", "Highbank",
    "Founders' Block",
)
_NEARBY_ZONES_MAX: int = 4  # hard line cap (prompt-diet — never the whole graph)

# EM-265 (SB) — the BACKEND pair of the frontend `GRAPH_LOTS_ENABLED` /
# `ROAD_MESH_ENABLED` flags (web/src/components/world3d/CityScape.tsx). Gates the
# SB zone-rule system on the AGENT SURFACE only: the `nearby_zones` perception
# block in build_nearby_layout AND the agent-facing `set_zone_rule` propose_rule
# effect (its place in the proposable-effects set + its action-gate validation).
# Default OFF ⇒ SB ships DORMANT: the protagonist prompt is byte-identical (no
# nearby_zones block) and agent behavior is byte-identical (set_zone_rule is not
# offered/accepted from an agent), exactly like SA ships dormant. Flip ON (together
# with the frontend `GRAPH_LOTS_ENABLED`) to activate agent-controlled zoning.
# NOTE: this is a COMPILE-TIME const (no clock/random — pure); it gates ONLY the
# runtime agent surface. `world.action_propose_rule` itself stays directly callable
# (tests + any future god path) regardless of this flag.
# ON since the organic-world sign-off (feat/organic-world-regen): with non-grid
# templates the road graph has real planar faces, so agents get the nearby_zones
# perception + set_zone_rule effect and can zone the emergent city. Paired with the
# frontend GRAPH_LOTS_ENABLED.
GRAPH_ZONES_ENABLED = True

# EM-268 (F1) — agent-controlled FREE building placement. Default OFF ⇒ buildings
# carry no position ⇒ frontend falls back to assignBuildingLots (byte-identical to
# pre-F1). Flip ON (with the frontend FREE_PLACEMENT_ENABLED) after the visual
# sign-off to activate deterministic cluster-accretion placement.
FREE_PLACEMENT_ENABLED = True


def _zone_display_name(world: "World", zone_id: str) -> str:
    """A deterministic, seeded flavor name for a zone (city block), stable across
    replay/fork: an index into _ZONE_NAME_POOL keyed by (city_seed, zone_id)."""
    seed = getattr(world, "city_seed", 0)
    return _ZONE_NAME_POOL[_seed_int(seed, "zone", zone_id) % len(_ZONE_NAME_POOL)]


def _point_in_poly(px: float, pz: float, poly: list[dict]) -> bool:
    """Even-odd ray cast: is world point (px, pz) inside the face polygon (a list
    of {x, z})? Pure; tolerant of a degenerate (<3 vertex) polygon (→ False)."""
    n = len(poly)
    if n < 3:
        return False
    inside = False
    j = n - 1
    for i in range(n):
        xi, zi = poly[i]["x"], poly[i]["z"]
        xj, zj = poly[j]["x"], poly[j]["z"]
        if ((zi > pz) != (zj > pz)) and (
            px < (xj - xi) * (pz - zi) / (zj - zi) + xi
        ):
            inside = not inside
        j = i
    return inside


def build_nearby_layout(world: "World", place: Any, force_node_id: str | None = None,
                        *, include_road: bool = True) -> str | None:
    """EM-243 (S2) — a compact, diet-safe perception line for road-building:
    extendable directions from the node nearest `place`, plus the car policy.

    EM-265 (SB) — extended with a district-scoped `Nearby zones` block (the
    nearest few city blocks, their land-use hint + optional density cap), so an
    agent can (in SC) target a zone to rule. Counts + hint + cap only — never a
    polygon dump.

    fix-wave A2 — the road sentence and the (flag-gated) zones block are INDEPENDENT:
    the road sentence appears only when a direction is actually `open` AND the caller
    permits it (`include_road`, the energy gate); the zones block appears whenever the
    GRAPH_ZONES_ENABLED flag is on and faces exist. This returns None ONLY when BOTH
    are absent — so a geometric city (n:pent:* ids never `open`) or a fully-interior
    lattice node still surfaces zones, keeping set_zone_rule bootstrappable there. The
    `include_road=False` path (a too-tired agent) drops the road sentence but keeps
    zone perception."""
    from ..engine.citygraph import (nearest_node, extendable_directions,
                                     planar_faces, zone_id_for, BLOCK_PITCH, TILE,
                                     logical_to_world)
    # place.x/place.y are LOGICAL 0..1000 coords; map to the graph's world (x, z)
    # frame BEFORE nearest_node (fix-wave A1), else every place snaps to n:12:12.
    node = (next((n for n in world.city_graph.nodes if n.id == force_node_id), None)
            if force_node_id
            else nearest_node(world.city_graph,
                              *logical_to_world(float(place.x), float(place.y))))
    if node is None:
        return None
    parts: list[str] = []

    # ── road-extension sentence — only when a direction is actually `open` AND the
    #    caller permits it (the energy gate lives at the call site, passed here as
    #    include_road). A geometric (n:pent:*) node yields {} ⇒ never `open`. ──
    dirs = extendable_directions(world.city_graph, node.id)
    openable = [d for d, s in dirs.items() if s == "open"]
    if openable and include_road:
        blocked = [f"{d} ({s})" for d, s in dirs.items() if s != "open"]
        cars = world.city_graph.car_policy
        road = f"Nearby layout: can build a road {', '.join(openable)}."
        if blocked:
            road += f" Blocked: {', '.join(blocked)}."
        road += f" Cars: {cars}."
        # EM-244 (S3a): surface an open layout vote so agents can vote (one clause).
        open_layout = next((r for r in world.rules.values()
                            if getattr(r, "status", "") == "proposed"
                            and getattr(r, "effect", "") in ("demolish_road", "set_car_policy")), None)
        if open_layout is not None:
            road += f" Open vote: {open_layout.effect} (vote yes/no)."
        parts.append(road)

    # EM-265 (SB) — district-scoped zone block: the _NEARBY_ZONES_MAX faces nearest
    # the agent's place (the local district horizon — prompt-diet, never the whole
    # graph), each with its hint + optional cap. GATED on the GRAPH_ZONES_ENABLED
    # feature flag (NOT on zone_rules being non-empty, and — fix-wave A2 — NOT on the
    # road sentence / openable / energy):
    #   - flag OFF (default) ⇒ render NOTHING ⇒ the prompt is byte-identical to
    #     pre-SB (law §0.1), so SB ships dormant.
    #   - flag ON ⇒ render the district's nearby faces INCLUDING UNZONED ones, so
    #     an agent can perceive a real zone_id to propose the FIRST set_zone_rule
    #     even when ZERO rules exist (fixes the chicken-and-egg bootstrap: gating on
    #     zone_rules-nonempty meant no rule ⇒ no perceivable zone ⇒ no first rule).
    # The scaffold SC's "target a zone" reads from this block.
    faces = planar_faces(world.city_graph) if GRAPH_ZONES_ENABLED else []
    if faces:
        # world-frame centroid distance: convert the place's logical coords too
        # (fix-wave A1), else the "nearest" faces are ranked in the wrong frame.
        px, pz = logical_to_world(float(place.x), float(place.y))
        nearest = sorted(
            faces,
            key=lambda f: ((f.centroid["x"] - px) ** 2 + (f.centroid["z"] - pz) ** 2,
                           zone_id_for(f.boundary)),
        )[:_NEARBY_ZONES_MAX]
        rules_by_zone = {r.zone_id: r for r in world.city_graph.zone_rules}
        lot_area = BLOCK_PITCH * TILE  # ~one lot's footprint along a block edge
        clauses: list[str] = []
        for f in nearest:
            zid = zone_id_for(f.boundary)
            lots = max(1, round(abs(f.area) / lot_area)) if lot_area else 1
            rule = rules_by_zone.get(zid)
            hint = rule.hint if rule is not None else "unzoned"
            # EM-265 (SB) bootstrap fix: surface the CANONICAL zone_id (the raw
            # "|"-joined node-id string) the action gate + action_propose_rule
            # demand, not just the friendly name. Display names are seeded from a
            # ~16-name pool and COLLIDE, so a name can't be resolved back to one
            # zone_id — without the raw id an agent perceives a block it can never
            # target, so with the flag ON and ZERO rules it could never propose the
            # FIRST rule. The id is bounded (~36 chars × ≤4 zones) so the diet holds.
            clause = (
                f"{_zone_display_name(world, zid)} [zone {zid}] "
                f"({hint}, ~{lots} lots"
            )
            if rule is not None and rule.density_cap is not None:
                # F2 (EM-266 SC): count LIVE buildings whose zone_id == this zone —
                # the SAME basis SC's over_cap check uses (world.py action_propose_
                # project). A zone_id is a pure tag SC never moves the building's
                # `location` to, so a point-in-poly over `location` decoupled the
                # density an agent READS ("N built") from the density SC OBSERVES
                # (and fires over_cap on): an agent piling zone_id-tagged builds into
                # a capped zone perceived "0 built" while violations fired. Counting
                # by zone_id makes the perceived density match the violation trigger,
                # so an agent gets real feedback to honor/defy the cap.
                built = sum(
                    1 for b in world.buildings.values()
                    if getattr(b, "zone_id", None) == zid
                    and getattr(b, "status", "") != "destroyed"
                )
                clause += f", cap {rule.density_cap} — {built} built"
            clause += ")"
            clauses.append(clause)
        if clauses:
            zones = "Nearby zones: " + " ".join(clauses) + "."
            # EM-266 (SC) — one framing clause (no new per-zone lines; prompt-diet):
            # an agent MAY target a zone when it builds. The build always succeeds —
            # a wrong kind or an over-cap block still stands (defiance is allowed).
            zones += " To build in one, pass zone_id=<id> on propose_project."
            parts.append(zones)

    if not parts:
        return None
    return " ".join(parts)


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


# Wave E / EM-125 — agent-declarable bond types (the ACTION_SCHEMA enum).
# `family` is engine-only (births, B1 rule); the other relationship words
# (neutral/ally/rival/enemy) are trust-driven, not bond-declarable.
_BOND_TYPES = ("friend", "partner", "mentor", "feud")
_BOND_TARGET_CAP = 60


def _sanitize_bond(action_dict: dict) -> str | None:
    """Wave E / EM-125 — pre-validate the optional reflection `bond` IN PLACE
    so a malformed/disallowed bond can never fail the turn (the same leniency
    rule as the optional trace fields above). A conforming bond is rewritten
    to exactly {target, type} (extra keys dropped, target truncated to the
    schema cap, type lower-cased); anything else is POPPED before schema
    validation and the rejection reason returned for the decision trace."""
    if "bond" not in action_dict:
        return None
    bond = action_dict.pop("bond")
    if not isinstance(bond, dict):
        return "malformed bond object"
    target = bond.get("target")
    btype = bond.get("type")
    if not isinstance(target, str) or not target.strip():
        return "malformed bond: missing target"
    if not isinstance(btype, str) or not btype.strip():
        return "malformed bond: missing type"
    btype = btype.strip().lower()
    if btype == "family":
        # B1 rule — engine-assigned only (births); declaring it is rejected.
        return ("family ties are made by birth, not declaration — "
                "you cannot declare someone family")
    if btype not in _BOND_TYPES:
        return f"invalid bond type: {btype!r}"
    action_dict["bond"] = {
        "target": target.strip()[:_BOND_TARGET_CAP], "type": btype,
    }
    return None


# Wave L / EM-223 — plan_revision field caps (mirror engine PLAN_* bounds so the
# normalized revision always passes ACTION_SCHEMA's plan_revision sub-schema).
_PLAN_GOAL_CAP = 200
_PLAN_STEP_CAP = 120
_PLAN_MAX_STEPS = 8


def _sanitize_plan_revision(action_dict: dict) -> str | None:
    """Wave L / EM-223 — pre-validate the optional `plan_revision` IN PLACE so a
    malformed one can never fail the turn (the _sanitize_bond leniency rule). A
    usable revision (non-empty goal + ≥1 non-empty step) is rewritten to a clean,
    bounded {goal, steps, reason?} that passes the schema; anything else is
    POPPED before validation and the reason returned for the decision trace."""
    if "plan_revision" not in action_dict:
        return None
    rev = action_dict.pop("plan_revision")
    if not isinstance(rev, dict):
        return "malformed plan_revision object"
    goal = rev.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        return "plan_revision missing a goal"
    steps_raw = rev.get("steps")
    if not isinstance(steps_raw, list):
        return "plan_revision missing steps"
    steps = [
        s.strip()[:_PLAN_STEP_CAP]
        for s in steps_raw
        if isinstance(s, str) and s.strip()
    ][:_PLAN_MAX_STEPS]
    if not steps:
        return "plan_revision has no usable steps"
    clean = {"goal": goal.strip()[:_PLAN_GOAL_CAP], "steps": steps}
    reason = rev.get("reason")
    if isinstance(reason, str) and reason.strip():
        clean["reason"] = reason.strip()[:_PLAN_GOAL_CAP]
    action_dict["plan_revision"] = clean
    return None


def _sanitize_charter_revision(
    action_dict: dict,
    *,
    max_ambitions: int = CHARTER_MAX_AMBITIONS,
    creed_cap: int = CHARTER_CREED_CAP,
) -> str | None:
    """EM-311 — pre-validate the optional `charter_revision` IN PLACE so a
    malformed/off-grammar one can never fail the turn (the _sanitize_plan_revision
    leniency rule). A usable revision (>=1 legal AMBITION_KINDS ambition) is
    rewritten to a clean, bounded {ambitions, creed?, reason?} that passes the
    schema; anything else is POPPED before validation and the reason returned for
    the decision trace. Off-grammar ambitions are DROPPED (never rejected wholesale)
    so a model that names one bad kind among good ones still lands its charter —
    the EM-297 'meet the model where it is' rule. The caps are the WORLD's
    effective charter caps (World.charter_caps — config clamped by the module
    hard ceiling, so the sanitized shape always passes the schema); defaults
    keep duck-typed callers on the hard ceiling."""
    if "charter_revision" not in action_dict:
        return None
    rev = action_dict.pop("charter_revision")
    if not isinstance(rev, dict):
        return "malformed charter_revision object"
    ambitions_raw = rev.get("ambitions")
    if not isinstance(ambitions_raw, list):
        return "charter_revision missing ambitions"
    ambitions: list[str] = []
    for a in ambitions_raw:
        if not isinstance(a, str):
            continue
        kind = a.strip()
        if kind in AMBITION_GRAMMAR and kind not in ambitions:
            ambitions.append(kind)
        if len(ambitions) >= max_ambitions:
            break
    if not ambitions:
        return "charter_revision has no valid ambition"
    clean: dict = {"ambitions": ambitions}
    creed = rev.get("creed")
    if isinstance(creed, str) and creed.strip():
        clean["creed"] = creed.strip()[:creed_cap]
    reason = rev.get("reason")
    if isinstance(reason, str) and reason.strip():
        clean["reason"] = reason.strip()[:200]
    action_dict["charter_revision"] = clean
    return None


# The declared top-level keys ACTION_SCHEMA allows. Anything else a model puts
# at the top level (flat single-action params like target/message/zone_id) is
# folded into `args` before validation — the EM-066 "a misplaced field never
# fails the turn" ethos, applied at the top level (args + actions[] items are
# already permissive; only the top level was strict). Derived from the schema
# itself so it stays in sync automatically.
_DECLARED_TOP_LEVEL = set(ACTION_SCHEMA["properties"].keys())


def _fold_stray_top_level_into_args(action_dict: dict) -> None:
    """A model that emits a single-action response sometimes puts the action's
    parameters FLAT at the top level (`{"action": "whisper", "target": "Ada",
    "message": "hi"}`) instead of nested under `args` (`{"action": "whisper",
    "args": {"target": "Ada", "text": "hi"}}`). Those undeclared top-level keys
    used to hard-fail the whole turn under ACTION_SCHEMA's top-level
    `additionalProperties: False` (idle fallback) even though the identical
    keys are welcome one level down. Move any undeclared top-level key into
    `args` IN PLACE so it validates instead. Does NOT overwrite an existing
    `args` key (first-write-wins, mirroring the alias-resolution precedence
    elsewhere in this module); leaves declared keys (action/actions/args/
    thought/mood/… — see _DECLARED_TOP_LEVEL) untouched. No-op on a clean
    response. Never raises."""
    stray = [k for k in list(action_dict) if k not in _DECLARED_TOP_LEVEL]
    if not stray:
        return
    args = action_dict.get("args")
    if not isinstance(args, dict):
        args = {}
    for k in stray:
        args.setdefault(k, action_dict.pop(k))
    action_dict["args"] = args


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
    {"give", "steal", "insult", "attack", "whisper", "set_relationship",
     # EM-240 — agent-targeted crime verbs resolve a name in args["target"] to an
     # agent id before dispatch (exactly like steal). vandalize is EXCLUDED — it
     # targets a building_id, not an agent name. launder is EXCLUDED — no target.
     # bribe targets the enforcer (args["target"]), so it IS resolved here.
     # recruit targets a co-located agent; accept_contract takes NO target (the
     # offer is keyed by the accepting agent's id), so it is EXCLUDED here.
     # EM-240 (Task 10) — enforcer justice verbs resolve a co-located agent name
     # in args["target"] to a suspect id (investigate/accuse/detain), like steal.
     "heist", "extort", "bribe", "recruit",
     # EM-237 — intimidate / deceive both target a co-located agent name in
     # args["target"] (resolved to an id before dispatch, like extort). deceive's
     # `about` arg is a free claim string and needs no resolution.
     "intimidate", "deceive",
     "investigate", "accuse", "detain",
     # EM-228 — teach_skill / request_skill both target a co-located agent name in
     # args["target"] (resolved to an id before dispatch, like steal). The `skill`
     # arg is a free string and needs no resolution.
     "teach_skill", "request_skill",
     # EM-230 — offer_trade targets a co-located agent name in args["target"]
     # (resolved to an id, like give). accept_trade / decline_trade take NO target
     # (the offer is keyed by the accepting agent's id), so they are EXCLUDED here.
     # The give/get term dicts are free args and need no resolution.
     "offer_trade",
     # EM-231 — offer_cooperation targets a co-located agent name in args["target"]
     # (resolved to an id, like give). accept_cooperation takes NO target (the offer
     # is keyed by the accepting agent's id) and co_build takes a building_id, not an
     # agent — so both are EXCLUDED here.
     "offer_cooperation",
     # EM-258 — clash targets a co-located enemy belligerent name in
     # args["target"] (resolved to an id before dispatch, like attack). muster
     # takes NO target and siege takes a building_id — both EXCLUDED here.
     "clash",
     # EM-251 — spread_rumor targets a co-located agent (resolved + co-location-
     # validated like deceive/clash). send_letter ALSO resolves a name→id here so
     # the model can address a letter by name, but its resolution stays PERMISSIVE
     # (the world action / validator does NOT require co-location or presence —
     # _resolve_agent_target already matches an ABSENT living agent by name).
     "spread_rumor", "send_letter",
     # EM-262 — proselytize targets a co-located agent (resolved + co-location-
     # validated like deceive/clash). worship takes NO target (EXCLUDED).
     "proselytize",
     # EM-263 — excommunicate resolves an agent target by NAME→id like the others,
     # BUT is NOT co-location gated (a founder casts out a member from afar — the
     # send_letter recipe: _resolve_agent_target already matches an ABSENT living
     # agent by name). declare_hostility takes a faith_id, not an agent (EXCLUDED).
     "excommunicate"}
)

# Behavioral STRING caps where truncation is harmless (display text — losing a
# few words beats losing the turn). Mirrors ACTION_SCHEMA's maxLength values;
# live failure: a 60-char propose_project `function` (cap 40) and a 300+-char
# billboard post (cap 280) each cost their agent a full turn to a schema error.
_ARG_STRING_CAPS: dict[str, dict[str, int]] = {
    "propose_project": {"name": 60, "kind": 30, "function": 40},
    "post_billboard": {"text": 280},
    "answer_proclamation": {"text": 280},
    # EM-110 — a settlement ref that overshoots the schema cap graceful-truncates
    # instead of failing the turn (names cap at 40, so 60 never clips a real one).
    "travel_to": {"settlement": 60},
    # EM-199 follow-up — chat length: a GENEROUS safety bound on spoken text
    # (session 189 averaged ~500 chars/line, max ~1900). 800 graceful-truncates
    # only runaway monologues so one giant say can't blow the token budget and
    # fail the turn; normal rich dialogue (the 189 feel) sails through. NOT a
    # throttle — it is ~4× the recent terse average. Truncated, never rejected.
    "say": {"text": 800},
    "whisper": {"text": 800},
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


# EM-199 — turn-level cognition the model may scatter into the first step.
_HOISTABLE_COGNITION = (
    "thought", "mood", "perceived_summary", "memories_used",
    "reasoning", "commitment", "reflection", "bond",
    # Wave L / EM-223 — a model told to return an `actions` sequence routinely
    # nests a plan_revision in actions[0]; hoist it so the plan still updates.
    "plan_revision",
)


def _coerce_actions_keyword(action_dict: dict) -> None:
    """EM-249 — a free model told to 'return "actions" — an ordered list' (the
    EM-199 multi-action prompt) routinely echoes the keyword as the VERB, emitting
    {"action": "actions", "actions": [...]}. That dies on the ACTION_SCHEMA enum
    ('actions' is not an action) even though a perfectly good actions[] sits right
    beside it — a recurring groq-llama idle fallback (run-1117). When `action` is
    literally "actions" AND a non-empty actions[] is present, drop the spurious
    `action` key so the multi-action path takes over (schema anyOf [action|actions];
    _normalize_steps prefers actions). With no usable actions[] to fall back on we
    leave it for the normal retry. Mutates in place; never raises; a no-op for every
    well-formed response (so the em161 golden parse path is untouched)."""
    if action_dict.get("action") != "actions":
        return
    actions = action_dict.get("actions")
    if isinstance(actions, list) and actions:
        action_dict.pop("action", None)


def _hoist_step_cognition(action_dict: dict) -> None:
    """Free models told to return an `actions` sequence routinely put
    turn-level cognition (thought / mood / perceived_summary / memories_used /
    reasoning / commitment / reflection / bond) INSIDE the first step instead of
    at the top level. Lift any such field from `actions[0]` up to the top level
    when it is absent there — so the 💭 thought still surfaces on the feed and
    the decision trace keeps its reasoning. The step's own copy is harmless
    (items tolerate extras; the runtime reads only action+args per step).
    Mutates in place; never raises. Runs BEFORE sanitize/validate so the hoisted
    values are truncated and validated like any top-level field."""
    actions = action_dict.get("actions")
    if not isinstance(actions, list) or not actions:
        return
    first = actions[0]
    if not isinstance(first, dict):
        return
    for key in _HOISTABLE_COGNITION:
        if key in first and not action_dict.get(key):
            action_dict[key] = first[key]


def _resolve_place_fuzzy(raw: str, world: World) -> str | None:
    """EM-199 — resolve a loose/hallucinated place name to the closest KNOWN
    place id, or None when nothing is a SAFE match (so gibberish stays and is
    cleanly rejected, never mis-teleported). Order: exact id → case-insensitive
    id → a known id appearing as a token of the input (plaza_bloom → plaza) →
    a conservative difflib closest match (catches typos like town_hall →
    townhall). Never raises."""
    if raw in world.places:
        return raw
    low = raw.strip().lower()
    by_lower = {pid.lower(): pid for pid in world.places}
    if low in by_lower:
        return by_lower[low]
    # A known place id appearing as a whole token of the input. Token-membership
    # (not prefix) avoids "homestead" → "home" style false hits.
    tokens = {t for t in re.split(r"[^a-z0-9]+", low) if t}
    for pid in world.places:
        if pid.lower() in tokens:
            return pid
    # Last resort: a single close fuzzy match above a conservative cutoff.
    match = difflib.get_close_matches(low, list(by_lower), n=1, cutoff=0.8)
    return by_lower[match[0]] if match else None


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
                # EM-199 — case-insensitive, then fuzzy: a hallucinated name
                # (plaza_bloom→plaza) resolves to the closest KNOWN place
                # instead of wasting the move; gibberish stays (→ cleanly
                # rejected by _validate_world, never mis-teleported).
                place = _resolve_place_fuzzy(place, world) or place
            args["place"] = place
        elif _noneish(args.get("place")):
            # A null/None-string place reads better as MISSING than as the
            # literal place 'None' in the validator's feedback.
            args.pop("place", None)

    elif action in ("place_prop", "propose_project"):
        # Wave K / EM-182+218 — the OPTIONAL chosen build/place id resolves
        # fuzzily (plaza_bloom→plaza, town_hall→townhall) like move_to, so a
        # slightly-off district choice lands instead of silently falling back to
        # the agent's location. A null/None-ish place is dropped (reads as MISSING,
        # the documented default). Gibberish stays → the world handler falls back.
        place = args.get("place")
        if isinstance(place, str):
            place = place.strip()
            if place and place not in world.places:
                place = _resolve_place_fuzzy(place, world) or place
            if place:
                args["place"] = place
            else:
                args.pop("place", None)
        elif _noneish(place):
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

    elif action == "vote":
        # run-663 — the model JSON-encodes an all-numeric rule_id as a NUMBER
        # (e.g. 36219503), which misses the string-keyed rule → "unknown rule".
        # Coerce to str so the vote lands (covers historical all-numeric ids;
        # new ids are now `r_`-prefixed and can't be numberified).
        rid = args.get("rule_id")
        if rid is not None and not isinstance(rid, str):
            args["rule_id"] = str(rid)

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


def _emit_world_result(
    result: Any, base: dict, thought: str = "",
    stamp_for: Callable[[str], dict | None] | None = None,
) -> dict:
    """Spread per-turn base metadata (profile/profile_color/tick) onto whatever a
    world-core `action_*` method returned and hand it back in the loop's emit shape.

    The W7 building actions return a fully-formed, ready-to-emit event dict
    (kind/actor_id/target_id?/text/payload), or {"_multi": [evt, ...]} for
    multi-event outcomes (propose_project also rides a "_building_id"). They never
    raise; an illegal id comes back as a `parse_failure` event. This consumes them
    exactly like the `vote` branch consumes its own `_multi`: it does NOT unpack a
    tuple and does NOT re-derive transitions — it reads the kinds/payloads the world
    already produced and overlays the base fields the loop needs.

    `stamp_for` (optional): a _multi chain may carry events attributed to a
    DIFFERENT actor than the acting agent (a clash kill's `agent_died` is the
    slain TARGET's, the follow-up `inherited` is the HEIR's); the base spread
    would dress them in the ACTING agent's profile/profile_color (the
    travel_arrived mis-attribution class). A caller that can resolve another
    agent's stamp passes it here and those events are re-stamped with their own
    actor's chip.
    """
    building_id = None
    if isinstance(result, dict) and "_building_id" in result:
        building_id = result.get("_building_id")

    def _decorate(evt: dict) -> dict:
        # base supplies profile/profile_color/tick + a default actor_id; the world
        # event's own actor_id/target_id/text/payload win where present.
        merged = {**base, **evt}
        if stamp_for is not None and \
                merged.get("actor_id") not in (None, base.get("actor_id")):
            stamp = stamp_for(str(merged["actor_id"]))
            if stamp:
                merged.update(stamp)
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

    # EM-240 (Task 10) — jail restriction: a detained/jailed agent may only talk
    # and think until they are released (a release tick frees them in the world's
    # per-round advance). Checked BEFORE every other gate so no jailed agent can
    # move, work, or commit a crime — only say/whisper/idle/remember get through.
    # EM-258 — the gate WIDENS to `exiled` (a war loser's leader is cast out of
    # public life — permanent: advance_crime's release path never frees exiled)
    # and explicitly NOT to belligerence (derived from war-band membership,
    # never a crime_status — a mustered soldier keeps every action; plan
    # §Feature 3).
    JAIL_ALLOWED = {"say", "whisper", "idle", "remember"}
    _status_now = getattr(agent, "crime_status", None)
    if _status_now in ("detained", "jailed", "exiled") and \
            action not in JAIL_ALLOWED:
        if _status_now == "exiled":
            return ("you are exiled — cast out after your faction's defeat; "
                    "you can only talk, whisper, and think")
        return ("you are jailed — you can only talk, whisper, and think until "
                "you are released")

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

    # ── EM-227 — skill gate. A high-value action named in the configured skill
    # LIBRARY requires the gating skill at >= its min level; an agent without it
    # gets a CLEAR rejection. Survival verbs are never in any library, so they are
    # never gated. config-absent / EMPTY library ⇒ skill_gate_for returns None ⇒
    # NOTHING gated (pre-EM-227 byte-identical + the em161 golden, whose default
    # WorldParams has no library). The menu agrees (see _assemble_context's
    # _skill_ok), so this rejection only fires on an off-menu invention.
    _gate = world.skill_gate_for(action) if hasattr(world, "skill_gate_for") else None
    if _gate is not None:
        _skill, _min = _gate
        if agent.skill_level(_skill) < _min:
            return (
                f"you lack the {_skill} skill (need level {_min}) to {action} — "
                f"learn it by doing simpler work or have someone teach you"
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

    elif action in ("heist", "extort"):
        # EM-240 — agent-targeted crimes share steal's gate shape (ban + co-located).
        gate = {"heist": "ban_stealing", "extort": "ban_extortion"}[action]
        if world.has_active_rule(gate):
            return f"{gate} rule is active — {action} is forbidden"
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error

    elif action in ("intimidate", "deceive"):
        # EM-237 — harm-surface finishers target a co-located/visible agent
        # (resolved like extort). The world action re-checks self-target +
        # visibility + (intimidate) the mark having something to give / (deceive)
        # a non-empty claim, so this front gate only ensures a reachable target —
        # a clear rejection lets the model self-correct.
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error
        if action == "deceive":
            about = args.get("about")
            if not isinstance(about, str) or not about.strip():
                return "deceive requires a claim (args.about)"

    elif action == "vandalize":
        # EM-240 — building-targeted crime; the @building co-location gate +
        # building_id resolution mirror arson (handled at dispatch / by the world).
        if world.has_active_rule("ban_vandalism"):
            return "ban_vandalism rule is active — vandalize is forbidden"

    elif action == "bribe":
        # EM-240 — bribe targets a co-located enforcer (args["target"]); launder
        # takes no target so it needs no world-validation. action_bribe re-checks
        # the enforcer role + co-location, so a stray bribe stays safe.
        target_error = _validate_target(args, agent, world, "bribe")
        if target_error:
            return target_error

    elif action == "recruit":
        # EM-240 — recruit pitches a co-located agent on a criminal pact (shares
        # steal's co-location shape, no ban gate). action_recruit re-checks
        # co-location + self-target, so a stray recruit stays safe.
        target_error = _validate_target(args, agent, world, "recruit")
        if target_error:
            return target_error

    elif action == "accept_contract":
        # EM-240 — accept_contract takes no target; reject up front (clear message)
        # unless an open pact is addressed to this agent.
        if agent.id not in getattr(world, "pending_crime_offers", {}):
            return "no criminal pact has been offered to you"

    elif action == "clash":
        # EM-258 — clash targets a co-located agent (resolved like attack). The
        # world action re-checks self-target + the at-war + mustered gates and
        # returns a clear fail event, so this front gate only ensures a
        # reachable target — the feedback names who IS here so the model can
        # self-correct. muster/siege need no front gate (no agent target;
        # action_muster / action_siege own every war-specific check).
        target_error = _validate_target(args, agent, world, "clash")
        if target_error:
            return target_error

    elif action == "proselytize":
        # EM-262 — proselytize targets a CO-LOCATED agent (resolved + validated
        # like clash/spread_rumor: reachable + alive + here). The world action
        # re-checks faith_enabled + self-target + the actor holding a faith +
        # co-location and mints/plants the conversion, so this front gate only
        # ensures a reachable target — a clear rejection lets the model self-correct.
        target_error = _validate_target(args, agent, world, "proselytize")
        if target_error:
            return target_error

    elif action == "excommunicate":
        # EM-263 — excommunicate resolves an agent target but is NOT co-location
        # gated (a founder casts a member out from afar — the send_letter recipe,
        # not clash's). This front gate only ensures the (resolved) id names a
        # real, LIVING agent; the world action owns the founder + own-faith-member
        # checks and returns a clear fail event on any miss.
        target_id = args.get("target")
        if not target_id:
            return "excommunicate requires target"
        _member = world.agents.get(target_id)
        if _member is None:
            return (f"unknown target '{target_id}' — excommunicate needs a member "
                    "of your faith (by name or id)")
        if not _member.alive:
            return f"target '{_member.name}' is dead"

    elif action == "declare_hostility":
        # EM-263 — declare_hostility carries a faith_id (a rival faith's id), not an
        # agent target. This front gate mirrors consecrate_faith's existence check:
        # the id must name a real, DIFFERENT faith; the world action owns the
        # founder gate. A faith-off world never surfaces the verb (menu-gated) and
        # the world action re-rejects it, so this only fires on an off-menu invention.
        fid = args.get("faith_id")
        if not fid:
            return "declare_hostility requires faith_id"
        _faiths = getattr(world, "faiths", None) or {}
        if fid not in _faiths:
            return (f"unknown faith '{fid}' — declare_hostility needs a rival "
                    "faith's id")
        if getattr(agent, "faith_id", None) == fid:
            return "declare_hostility cannot target your own faith"

    elif action == "spread_rumor":
        # EM-254 — a ratified ban_gossip forbids spreading rumors (steal's
        # ban_stealing gate shape). The world action re-checks it too; this front
        # gate rejects early with clear guidance (and the menu hides the verb via
        # _gate_ok). Placed first so a banned town never dangles the verb.
        if world.has_active_rule("ban_gossip"):
            return "ban_gossip rule is active — spread_rumor is forbidden"
        # EM-251 — spread_rumor targets a CO-LOCATED agent (resolved + validated
        # like deceive/clash: reachable + alive + here). The world action re-checks
        # comm.enabled + self-target + co-location and mints/plants the drift, so
        # this front gate only ensures a reachable target — a clear rejection lets
        # the model self-correct.
        target_error = _validate_target(args, agent, world, "spread_rumor")
        if target_error:
            return target_error

    elif action == "send_letter":
        # EM-251 — send_letter is the first NON-co-located channel: the target may
        # be ABSENT (do NOT require co-location or presence), so this gate ONLY
        # checks the (resolved) id names a real, LIVING agent. The world action
        # re-checks comm.enabled + self-target + non-empty text and parks the
        # letter in the recipient's mailbox for reflex delivery next turn.
        target_id = args.get("target")
        if not target_id:
            return "send_letter requires target"
        _recipient = world.agents.get(target_id)
        if _recipient is None:
            return (f"unknown target '{target_id}' — send_letter needs a citizen's "
                    "name or id")
        if not _recipient.alive:
            return f"target '{_recipient.name}' is dead"

    elif action in ("teach_skill", "request_skill"):
        # EM-228 — both verbs target a co-located agent (resolved like steal). The
        # world action re-checks co-location + self-target + (for teach) the
        # outrank rule, so this front gate only ensures a reachable target + a
        # named skill; a clear rejection here lets the model self-correct.
        target_error = _validate_target(args, agent, world, action)
        if target_error:
            return target_error
        skill = args.get("skill")
        if not isinstance(skill, str) or not skill.strip():
            return f"{action} requires a skill name (args.skill)"

    elif action == "offer_trade":
        # EM-230 — offer_trade targets a co-located agent (resolved like give). The
        # world action re-checks co-location + self-target + that the deal is
        # non-empty and the offerer can back any pledged credits, so this front gate
        # only ensures a reachable target — a clear rejection lets the model
        # self-correct. The give/get terms are validated in the world method.
        target_error = _validate_target(args, agent, world, "offer_trade")
        if target_error:
            return target_error

    elif action in ("accept_trade", "decline_trade"):
        # EM-230 — accept_trade / decline_trade take no target; reject up front
        # (clear message) unless an open offer is addressed to this agent. The
        # world method re-checks affordability atomically at settle time.
        if agent.id not in getattr(world, "pending_trade_offers", {}):
            return "no trade offer has been made to you"

    elif action == "offer_cooperation":
        # EM-231 — offer_cooperation targets a co-located agent (resolved like give).
        # The world action re-checks co-location + self-target + an existing
        # partnership, so this front gate only ensures a reachable target — a clear
        # rejection lets the model self-correct.
        target_error = _validate_target(args, agent, world, "offer_cooperation")
        if target_error:
            return target_error

    elif action == "accept_cooperation":
        # EM-231 — accept_cooperation takes no target; reject up front (clear
        # message) unless a handshake offer is addressed to this agent. The world
        # method re-checks the offerer is alive + co-located at settle time.
        if agent.id not in getattr(world, "pending_cooperation_offers", {}):
            return "no partnership offer has been made to you"

    elif action == "co_build":
        # EM-231 — THE cooperation-gated action (EW's hard mechanic). It unlocks
        # ONLY when this agent has an ACTIVE handshake with a CO-LOCATED partner:
        # a solo attempt gets a clear rejection so the model knows to offer/accept
        # cooperation first. After the gate, the building checks mirror build_step.
        partner_here = getattr(world, "cooperation_partner_here", None)
        partner = partner_here(agent) if callable(partner_here) else None
        if partner is None:
            return ("co_build needs an agreed cooperation partner here — "
                    "offer_cooperation to a co-located agent (and have them accept) "
                    "first, then build together")
        building_id = args.get("building_id")
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
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
            return f"you must be at the building's place ('{b_loc}') to co_build"

    elif action in ("investigate", "accuse", "detain"):
        # EM-240 (Task 10) — justice verbs are reserved for enforcers (a role
        # gate, not a place gate). All three target a co-located agent; the
        # world action re-checks co-location + grounds, so this stays safe.
        if getattr(agent, "role", "citizen") != "enforcer":
            return f"{action} is reserved for enforcers (role) — you keep no badge"
        target_error = _validate_target(args, agent, world, action)
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
        # Wave K / EM-219: demolish — public/landmark demolish by consensus vote.
        # Wave I / EM-212: promote_image — vote a gallery image onto the plaza banner.
        # FINDING 1 — promote_image MUST be in this set, else a valid proposal is
        # rejected at the runtime gate BEFORE it reaches world.action_propose_rule
        # (the gate is the agent's only path; QA passed only by bypassing it).
        # EM-240 (Task 11): trial — an enforcer escalates a suspect to a town-hall
        # vote (convict/acquit). Role-gated to enforcers (menu and resolution agree);
        # carries the defendant id on args.target (mirrors demolish's target arg).
        # EM-236: amend_constitution — add|edit|remove a foundational article by 70%
        # vote. EM-183: relocate_center — re-anchor the civic heart on a chosen place
        # by 70% vote (carries the place id on args.target, like demolish). BOTH MUST
        # be in this set (FINDING 1, above): the gate is the agent's ONLY path, so an
        # effect missing here is silently un-proposable even though world.action_-
        # propose_rule accepts it (amend_constitution shipped EM-236 without this and
        # was reachable only by bypassing the gate in tests).
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "name_town", "demolish", "promote_image",
                         "trial", "amend_constitution", "relocate_center",
                         "demolish_road", "set_car_policy",  # EM-244 (S3a)
                         "adopt_master_plan"}  # EM-245 (S3b)
        # EM-265 (SB) — set_zone_rule is offered to agents ONLY behind the
        # GRAPH_ZONES_ENABLED flag (default OFF ⇒ not in the set ⇒ rejected here as
        # an invalid effect ⇒ agent behavior byte-identical when dormant). The world
        # method world.action_propose_rule is NOT flag-gated (stays directly callable).
        if GRAPH_ZONES_ENABLED:
            valid_effects.add("set_zone_rule")  # EM-265 (SB)
        # EM-257 — the war governance lane rides ONLY when war is enabled (the
        # set_zone_rule flag recipe, but config-gated like victory-arch/boost):
        # default OFF ⇒ not in the set ⇒ rejected as an invalid effect ⇒ agent
        # behavior byte-identical when dormant. The world method stays directly
        # callable (it rejects with its own war-disabled reason).
        if getattr(world, "war_enabled", None) and world.war_enabled():
            valid_effects.add("declare_war")
            valid_effects.add("peace_treaty")
        # EM-254 — the culture governance lane rides ONLY when comm is enabled
        # (the war-lane recipe): default OFF ⇒ not in the set ⇒ rejected as an
        # invalid effect ⇒ agent behavior byte-identical when dormant (the em250
        # golden). The world method stays directly callable (its own comm-disabled
        # reason). canonize_meme = the 70% "popular meme → institution" bridge;
        # ban_gossip = a simple-majority spread_rumor ban (ban_stealing's twin).
        if getattr(world, "_comm_enabled", None) and world._comm_enabled():
            valid_effects.add("canonize_meme")
            valid_effects.add("ban_gossip")
        # EM-261 — the Religion governance lane rides ONLY when faith is enabled
        # (the culture-lane recipe, but gated on faith_enabled NOT comm): default
        # OFF ⇒ not in the set ⇒ rejected as an invalid effect ⇒ agent behavior
        # byte-identical when dormant (the em260 golden). consecrate_faith = the
        # 70% "faith → temple seat" bridge (canonize_meme's religion twin).
        if getattr(world, "faith_enabled", None) and world.faith_enabled():
            valid_effects.add("consecrate_faith")
        # EM-315 — the Healing House `heal` lane rides ONLY when the flag is on
        # (the war/set_zone_rule recipe): default OFF ⇒ not in the set ⇒ rejected
        # as an invalid effect ⇒ agent behavior byte-identical when dormant. The
        # world method stays directly callable (its own disabled reason).
        if getattr(world, "healing_house_enabled", None) and world.healing_house_enabled():
            valid_effects.add("heal")
        if effect not in valid_effects:
            return f"invalid effect '{effect}'. Valid: {sorted(valid_effects)}"
        # EM-183 — relocate_center needs a REAL target place (the menu/resolution-
        # agree rule, EM-108): mirror demolish's existence check so the gate rejects
        # the same proposals world.action_propose_rule would, with the same guidance.
        if effect == "relocate_center":
            target = str(args.get("target") or "").strip()
            if target not in getattr(world, "places", {}):
                return ("relocate_center requires args.target = the id of a real "
                        "place to make the new town center")
        if effect == "trial":
            if getattr(agent, "role", "citizen") != "enforcer":
                return "trial is reserved for enforcers (role) — you keep no badge"
            target = str(args.get("target") or "").strip()
            # Task 12a — agents see NAMES, not ids. Resolve by id first, then by
            # display name (case-insensitive, alive, lowest id on ties) so the
            # gate AGREES with action_propose_rule (EM-108 menu/resolution rule).
            defendant = world.agents.get(target)
            if defendant is None and target:
                _wanted = target.lower()
                defendant = next(
                    (a for a in sorted(world.living_agents(), key=lambda x: x.id)
                     if str(getattr(a, "name", "")).strip().lower() == _wanted),
                    None,
                )
            if defendant is None or not getattr(defendant, "alive", True):
                return "trial requires args.target = the name or id of a living defendant"
            if getattr(defendant, "crime_status", None) in ("detained", "jailed"):
                return f"{defendant.name} is already in custody"
        # EM-315 — heal needs a living PATIENT and a distinct model to transplant
        # (mirror trial's patient resolution + the world's no-op guard so the gate
        # AGREES with action_propose_rule — EM-108 menu/resolution rule).
        if effect == "heal":
            target = str(args.get("target") or "").strip()
            patient = world.agents.get(target)
            if patient is None and target:
                _wanted = target.lower()
                patient = next(
                    (a for a in sorted(world.living_agents(), key=lambda x: x.id)
                     if str(getattr(a, "name", "")).strip().lower() == _wanted),
                    None,
                )
            if patient is None or not getattr(patient, "alive", True):
                return ("heal requires args.target = the name or id of a living "
                        "citizen to send to the Healing House")
            if getattr(world, "_pick_healing_profile", None) and \
                    world._pick_healing_profile(patient) is None:
                return (f"the Healing House has no model to transplant that "
                        f"{patient.name} does not already run")
        if effect == "name_town" and not str(args.get("name") or "").strip():
            return "name_town requires a name (args.name = the town's new name)"
        if effect == "demolish":
            target = str(args.get("target") or args.get("building_id") or "").strip()
            building = _buildings(world).get(target)
            if building is None:
                return "demolish requires args.target = the id of a real building to tear down"
            if _building_field(building, "status") == "destroyed":
                return f"building '{target}' is already destroyed"
        if effect == "promote_image":
            # Mirror demolish's target existence check: the proposed image must be
            # a real gallery record (the id may arrive via image_id OR the generic
            # target arg — the world handler maps either key).
            image_id = str(args.get("image_id") or args.get("target") or "").strip()
            gallery = getattr(world, "gallery", []) or []
            if not image_id:
                return "promote_image requires args.image_id = the id of a gallery image to hang over the plaza"
            if not any(g.get("image_id") == image_id for g in gallery):
                return f"promote_image requires args.image_id of a real gallery image (got '{image_id}')"
        # EM-244 (S3a) — demolish_road needs a REAL road id (mirror demolish's
        # target check so the gate AGREES with world.action_propose_rule).
        if effect == "demolish_road":
            target = str(args.get("target") or "").strip()
            if not any(e.id == target for e in world.city_graph.edges):
                return "demolish_road requires args.target = the id of a real road to tear down"
        # EM-244 (S3a) — set_car_policy needs a valid {scope, policy}; street scope
        # needs a real edge target. 'district' is deferred (mirror the world).
        if effect == "set_car_policy":
            from ..engine.citygraph import CAR_POLICIES, CAR_SCOPES
            scope = str(args.get("scope") or "city").strip()
            policy = str(args.get("policy") or "").strip()
            if policy not in CAR_POLICIES:
                return f"set_car_policy requires args.policy in {sorted(CAR_POLICIES)}"
            if scope not in CAR_SCOPES:
                return "set_car_policy scope must be 'city' or 'street' ('district' not yet supported)"
            if scope == "street":
                target = str(args.get("target") or "").strip()
                if not any(e.id == target for e in world.city_graph.edges):
                    return "set_car_policy street scope requires args.target = a real road id"
        # EM-245 (S3b) — adopt_master_plan carries the plan KIND on args.target
        # (mirror demolish_road's target check so the gate AGREES with the world):
        # the kind must be known, and only ONE master plan may morph at a time.
        if effect == "adopt_master_plan":
            from ..engine.citygraph import MASTER_PLAN_KINDS
            kind = str(args.get("target") or "").strip()
            if kind not in MASTER_PLAN_KINDS:
                return (f"adopt_master_plan requires args.target = a known plan kind "
                        f"{sorted(MASTER_PLAN_KINDS)}")
            if getattr(world, "master_plan", None) is not None:
                return ("a master plan is already in progress — only one at a time "
                        "(wait for it to finish before adopting another)")
        # EM-265 (SB) — set_zone_rule needs a REAL current zone (a planar face of
        # the live graph), a known hint, and a None/int>=0 density_cap. Mirror the
        # world's checks so the front-gate AGREES with action_propose_rule (EM-108
        # menu/resolution rule): an effect the gate would let through but the world
        # would reject is a dead end for the agent.
        if GRAPH_ZONES_ENABLED and effect == "set_zone_rule":
            from ..engine.citygraph import ZONE_HINTS, planar_faces, zone_id_for
            zone_id = str(args.get("zone_id") or args.get("target") or "").strip()
            hint = str(args.get("hint") or "").strip()
            if hint not in ZONE_HINTS:
                return f"set_zone_rule requires args.hint in {sorted(ZONE_HINTS)}"
            density_cap = args.get("density_cap")
            if density_cap is not None and str(density_cap).strip() != "":
                try:
                    if int(density_cap) < 0:
                        return "set_zone_rule density_cap must be >= 0 (or null)"
                except (TypeError, ValueError):
                    return "set_zone_rule density_cap must be a non-negative integer (or null)"
            current_zones = {zone_id_for(f.boundary)
                             for f in planar_faces(world.city_graph)}
            if zone_id not in current_zones:
                return ("set_zone_rule requires args.zone_id = the id of a real "
                        "current zone (a city block)")
        # EM-257 — declare_war: mirror the world's checks (faction membership +
        # a casus-belli target, resolved by faction id OR name — the trial
        # defendant-resolution recipe) so the gate AGREES with
        # world.action_propose_rule (EM-108 menu/resolution rule). These
        # branches only run when war is enabled (the effect passed the set
        # above). casus_belli_targets already folds in the grievance
        # threshold, target existence, and the not-already-at-war guard.
        if effect == "declare_war":
            _f = world.faction_of(agent.id) if hasattr(world, "faction_of") else None
            if _f is None:
                return ("declare_war requires you to belong to a faction — "
                        "a war is declared BY a circle, not a lone agent")
            target = str(args.get("target") or "").strip()
            _factions = getattr(world, "factions", {}) or {}
            _tid = target if target in _factions else None
            if _tid is None and target:
                _wanted = target.lower()
                _tid = next(
                    (fid for fid in sorted(_factions)
                     if str(_factions[fid].get("name", "")).strip().lower()
                     == _wanted),
                    None)
            _casus = {t["id"] for t in world.casus_belli_targets(_f["id"])}
            if _tid is None or _tid not in _casus:
                return ("declare_war requires args.target = a faction your "
                        "circle holds a casus belli against (grievance past "
                        "the threshold)")
        # EM-257 — peace_treaty: mirror the world's checks (faction membership +
        # an ACTIVE war the faction is fighting; the id may ride args.war_id or
        # the generic args.target) plus the reparations shape.
        if effect == "peace_treaty":
            _f = world.faction_of(agent.id) if hasattr(world, "faction_of") else None
            if _f is None:
                return ("peace_treaty requires you to belong to a faction — "
                        "peace is sued for BY a belligerent circle")
            _wid = str(args.get("war_id") or args.get("target") or "").strip()
            if _wid not in {w.id for w in world.active_wars_for(_f["id"])}:
                return ("peace_treaty requires args.war_id = the id of an "
                        "active war your faction is fighting")
            _rep = args.get("reparations")
            if _rep is not None and str(_rep).strip() != "":
                try:
                    if int(_rep) < 0:
                        return "peace_treaty reparations must be >= 0"
                except (TypeError, ValueError):
                    return "peace_treaty reparations must be a non-negative integer"
        # EM-254 — canonize_meme: mirror promote_image's existence check (the id
        # may arrive on args.meme_id OR the generic args.target — the world
        # handler maps either key) so the gate AGREES with world.action_propose_rule
        # (EM-108 menu/resolution rule). Only runs when comm is enabled (the effect
        # passed the set above). ban_gossip needs no args (ban_stealing's twin).
        if effect == "canonize_meme":
            _mid = str(args.get("meme_id") or args.get("target") or "").strip()
            if _mid not in (getattr(world, "memes", {}) or {}):
                return ("canonize_meme requires args.meme_id = the id of a real "
                        "meme in circulation to elevate to the town's canon")
        # EM-261 — consecrate_faith: mirror canonize's existence check (the id may
        # arrive on args.faith_id OR the generic args.target — the world handler
        # maps either key) so the gate AGREES with world.action_propose_rule
        # (EM-108 menu/resolution rule). Only runs when faith is enabled (the
        # effect passed the set above, which is faith_enabled-gated).
        if effect == "consecrate_faith":
            _fid = str(args.get("faith_id") or args.get("target") or "").strip()
            if _fid not in (getattr(world, "faiths", {}) or {}):
                return ("consecrate_faith requires args.faith_id = the id of a "
                        "real faith to anchor to its temple seat")

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

    # ── Wave I / EM-210+211 — The Atelier reflex tools ─────────────────────────
    elif action == "create_image":
        # Ungated (create art anywhere) — only a non-empty prompt is required.
        if not str(args.get("prompt") or "").strip():
            return "create_image requires a prompt describing the art to paint"

    elif action == "paint_surface":
        # EM-298 — @building co-location gate (mirror repair/arson): the target
        # building must exist and stand at the agent's place; a non-empty prompt is
        # required. Menu and validator AGREE (EM-108: no dead turns).
        target = str(args.get("target") or "").strip()
        building = _buildings(world).get(target)
        if building is None:
            return f"unknown building '{target}'"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to paint its facade"
        if not str(args.get("prompt") or "").strip():
            return "paint_surface requires a prompt describing the mural/sign to paint"

    elif action == "post_image":
        # @billboard-gated (mirror post_billboard). The image must exist + be the
        # agent's (or public/promoted); an absent id defaults to the agent's newest.
        billboard_here = getattr(world, "billboard_here", None)
        if not (callable(billboard_here) and billboard_here(agent.location)):
            return "the billboard stands at the plaza / town hall — move there first"
        gallery = getattr(world, "gallery", []) or []
        image_id = str(args.get("image_id") or "").strip()
        if image_id:
            record = next(
                (g for g in gallery if g.get("image_id") == image_id), None)
            if record is None:
                return f"unknown image '{image_id}'"
            if record.get("proposer_id") != agent.id and not record.get("promoted"):
                return f"image '{image_id}' is not yours to post"
        elif not any(g.get("proposer_id") == agent.id for g in gallery):
            return "you have not painted anything to post — create_image first"

    # ── PROTOTYPE (god-channel) — answer the active proclamation ───────────────
    elif action == "answer_proclamation":
        active = getattr(world, "active_proclamation", None)
        if not (callable(active) and active()):
            return "there is no active proclamation to answer"
        if not str(args.get("text") or "").strip():
            return "answer_proclamation requires text"

    # ── Wave H4 / EM-209 — pets & bonds (the CO-LOCATION gate, animal-specific).
    elif action == "adopt":
        animal_id = args.get("animal_id")
        animal = (getattr(world, "animals", {}) or {}).get(animal_id)
        if animal is None:
            return f"unknown animal '{animal_id}'"
        if not getattr(animal, "alive", False):
            return f"{getattr(animal, 'name', animal_id)} is not alive"
        if getattr(animal, "location", None) != agent.location:
            return f"{getattr(animal, 'name', animal_id)} is not here — you must be at the same place to adopt it"
        owner_id = getattr(animal, "owner_id", None)
        if owner_id:
            if owner_id == agent.id:
                return f"you already own {getattr(animal, 'name', animal_id)}"
            return f"{getattr(animal, 'name', animal_id)} already has an owner"

    elif action == "feed_pet":
        animal_id = args.get("animal_id")
        animal = (getattr(world, "animals", {}) or {}).get(animal_id)
        if animal is None:
            return f"unknown animal '{animal_id}'"
        if not getattr(animal, "alive", False):
            return f"{getattr(animal, 'name', animal_id)} is not alive"
        if getattr(animal, "location", None) != agent.location:
            return f"{getattr(animal, 'name', animal_id)} is not here — you must be at the same place to feed it"

    # ── Wave K / EM-218–220 — builders'-city reflex tools ─────────────────────
    elif action == "place_prop":
        kind = str(args.get("kind") or "").strip()
        if not kind:
            return "place_prop requires a kind (e.g. bench, lamp, tree, statue)"
        # `place` defaults to the agent's location (the menu and the world handler
        # agree); a provided place must exist.
        place = str(args.get("place") or "").strip() or agent.location
        if place not in world.places:
            return f"unknown place '{place}'. Known: {list(world.places.keys())}"
        # Cap gate (menu and resolution agree): over the prop cap is rejected with
        # guidance, never a dead turn.
        cap = world._props_max_population()
        if cap > 0 and len(getattr(world, "props", {}) or {}) >= cap:
            return (f"the town is decorated to the brim ({cap} props) — "
                    f"remove one before placing another")

    elif action == "remove_prop":
        # EM-199 defense-in-depth — a multi-action turn can hand us an object/array
        # id; coerce to str BEFORE the dict lookup so an unhashable id is a clean
        # rejection, never a loop-killing TypeError (mirror the place_prop str()).
        prop_id = str(args.get("prop_id") or "").strip()
        prop = (getattr(world, "props", {}) or {}).get(prop_id)
        if prop is None:
            return f"unknown prop '{prop_id}'"
        owner_id = getattr(prop, "owner_id", None)
        if owner_id:
            if owner_id != agent.id:
                return f"prop '{prop_id}' was placed by someone else — only its owner can remove it"
        elif getattr(prop, "place", None) != agent.location:
            return (f"prop '{prop_id}' is at '{getattr(prop, 'place', '?')}' — "
                    f"you must be there to clear an unowned prop")

    elif action == "demolish":
        # EM-199 defense-in-depth — coerce to str BEFORE the dict lookup (an
        # object/array building_id from a multi-action turn would otherwise raise
        # an unhashable-type TypeError and kill the loop).
        building_id = str(args.get("building_id") or "").strip()
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        status = _building_field(building, "status")
        if status == "destroyed":
            return f"building '{building_id}' is already destroyed"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to demolish it"
        # EM-219 — the TOOL handles only the owner-immediate case; a public /
        # landmark (non-owner) demolish must go through governance (propose_rule
        # effect=demolish → vote), so reject here WITH that guidance.
        if _building_field(building, "owner_id") != agent.id:
            return (f"'{_building_field(building, 'name')}' isn't yours to demolish — "
                    f"propose a demolish rule at the town hall and let the town vote")

    elif action == "set_building_skin":
        # EM-199 defense-in-depth — coerce to str BEFORE the dict lookup (an
        # object/array building_id from a multi-action turn would otherwise raise
        # an unhashable-type TypeError and kill the loop).
        building_id = str(args.get("building_id") or "").strip()
        building = _buildings(world).get(building_id)
        if building is None:
            return f"unknown building '{building_id}'"
        # EM-108 menu/resolution agreement — the menu only offers set_building_skin
        # for a building with status != "destroyed" (_assemble_context filter); the
        # resolution gate must reject rubble too, or a stale id re-skins thin air.
        if _building_field(building, "status") == "destroyed":
            return f"{_building_field(building, 'name', building_id)} is rubble — nothing to re-skin"
        b_loc = _building_field(building, "location")
        if b_loc != agent.location:
            return f"you must be at the building's place ('{b_loc}') to re-skin it"
        if _building_field(building, "owner_id") != agent.id:
            return f"only the owner can re-skin building '{building_id}'"
        if not str(args.get("skin") or "").strip():
            return "set_building_skin requires a skin (a color name, e.g. rose|sky|sage|amber|slate|plum)"

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Context assembly
# ──────────────────────────────────────────────────────────────────────────────

def _recently_said_block(recent_said: list[str] | None) -> str:
    """EM-322 — an explicit YOU RECENTLY SAID list injected into the prompt so
    the model SEES its own last lines and is told not to repeat or paraphrase
    them. The soft speech nudge (speech_line) alone let small models (and the
    storm fallback) loop the same phrase for turns on end; surfacing the actual
    lines is what breaks the loop without HIDING anything or wasting a turn.
    Empty/None → "" (byte-identical for an agent that has not spoken)."""
    lines = [s.strip() for s in (recent_said or []) if s and s.strip()]
    if not lines:
        return ""
    body = "\n".join(f'  - "{s[:200]}"' for s in lines)
    return (
        "\n\n=== YOU RECENTLY SAID (do NOT repeat or paraphrase any of these — "
        "say something genuinely NEW that moves the conversation forward) ===\n"
        + body
    )


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
    memory_prebounded: bool = False,
    recent_said: list[str] | None = None,
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
    agent's location — billboard entry dicts, rendered read-only here.

    EM-222: `memory_prebounded` controls whether the RECENT EVENTS block
    re-slices `recent_events`. Default False keeps the historical behavior
    byte-for-byte — the prompt builder slices to `_effective_memory_window`
    (so the committed pre-diet fixture and every direct caller are unchanged).
    `run_turn` passes True with the list `_retrieve_memory` already bounded
    (the relevance-scored top-K merged with the recent tail, OR — for the
    background tier / disabled / embeddings-down — exactly the
    `recent_events[-window:]` blind slice), so the retriever owns bounding and
    its merged list is rendered verbatim, not chopped back to the window. The
    background path is byte-identical either way: the slice it passes IS the
    window slice this builder would otherwise compute."""
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

    # EM-110 — per-settlement (per-city) perception horizon. When settlements are
    # enabled AND there is MORE THAN ONE city, a homed agent perceives only the
    # places of its OWN settlement (the whole map partitions by nearest center),
    # so its prompt stays FLAT as cities grow — a 2-city world's per-agent prompt
    # ≈ a 1-city world's (the free-scale keystone). With ≤1 settlement (or the
    # feature OFF, or an unsettled agent) this is None ⇒ no settlement scoping,
    # so a single-city world shows the full town and the OFF path is byte-
    # identical to pre-EM-110.
    settlement_horizon: str | None = None
    if (getattr(world, "_settlements_enabled", None)
            and world._settlements_enabled()
            and len(getattr(world, "settlements", {}) or {}) > 1):
        _home = getattr(agent, "home_settlement_id", None)
        if _home in (getattr(world, "settlements", {}) or {}):
            settlement_horizon = _home

    def _place_visible(place_id: str) -> bool:
        """EM-161 — is this place inside the agent's perception horizon? Always
        True for protagonists / when scoping is off; un-districted places clear
        the district diet. EM-110 layers the per-settlement horizon on top: with
        >1 city a homed agent sees only its OWN settlement's places."""
        if visible_districts is not None:
            p = world.places.get(place_id)
            district = getattr(p, "district", None) if p is not None else None
            if not (district is None or district in visible_districts):
                return False
        if settlement_horizon is not None:
            p = world.places.get(place_id)
            if p is not None and world.settlement_of_place(p) != settlement_horizon:
                return False
        return True

    def _tier_ok(action: str) -> bool:
        """EM-163 — offer this action on the menu? Mirrors the resolution-time
        gate in _validate_world exactly (menu and resolution agree)."""
        return not (background and action in TIER_GATED_ACTIONS)

    co_located = [
        a for a in world.living_agents()
        if a.location == agent.location and a.id != agent.id
    ]
    # Wave D3 / EM-171 — background rosters render in sorted (name, id) order
    # so equivalent co-location sets assemble identical bytes regardless of
    # agent-dict insertion order (spawn/padding order churns it). Background
    # ONLY: protagonist/supporting keep today's iteration order byte-for-byte.
    if background:
        co_located.sort(key=lambda a: (a.name, a.id))

    active_rules = [r for r in world.rules.values() if r.status == "active"]
    proposed_rules = [r for r in world.rules.values() if r.status == "proposed"]

    # Wave H4 / EM-209 — co-located living animals (pets & bonds). Sorted by
    # (name, id) so the menu assembles deterministically. `here_unowned` drives
    # the adopt offer; `here_animals` drives feed_pet (any co-located animal can
    # be fed). owner_id None = adoptable.
    here_animals = sorted(
        (a for a in getattr(world, "living_animals", lambda: [])()
         if getattr(a, "location", None) == agent.location),
        key=lambda a: (a.name, a.id),
    )
    here_unowned = [a for a in here_animals if not getattr(a, "owner_id", None)]

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
    # (current + core; see _diet_visible_districts). EM-110 — with >1 city a
    # homed agent (any tier) sees only its own settlement's projects. Menu
    # narrowing only: _validate_world still accepts contributions to ANY open
    # project.
    if visible_districts is not None or settlement_horizon is not None:
        open_projects = [
            b for b in open_projects
            if _place_visible(_building_field(b, "location"))
        ]
    # Wave D3 / EM-171 — background building/project menus render in stable
    # id order so equivalent situations assemble identical bytes regardless
    # of buildings-dict insertion order (background only — see roster note).
    if background:
        here_buildings.sort(key=lambda b: str(_building_field(b, "id")))
        open_projects.sort(key=lambda b: str(_building_field(b, "id")))

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

    def _skill_ok(action: str) -> bool:
        """EM-227 — offer this gated action on the menu? Mirrors the resolution-
        time skill gate (_validate_world) so the menu and the validator AGREE
        (EM-108: no dead turns). config-absent / EMPTY library ⇒ skill_gate_for
        returns None ⇒ always True (every action offered, the em161 golden's
        default-WorldParams path)."""
        gate = world.skill_gate_for(action) if hasattr(world, "skill_gate_for") else None
        if gate is None:
            return True
        skill, min_level = gate
        return agent.skill_level(skill) >= min_level

    valid_actions: list[str] = []
    nearby_layout_block = ""  # EM-243 (S2) — set when build_road is offered (below)
    settlement_block = ""     # EM-269 (F2) — set when settlements are enabled (below)
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
        # EM-230 — real trade: a two-sided negotiated deal (beyond one-way give).
        # Offered to any co-located agent (the deal can be credits and/or a skill
        # lesson each way); the target perceives + accepts/declines on their turn.
        # GATED on an active skills library — the headline value of offer_trade over
        # plain give is the skill economy (skill-for-credit / skill-for-skill), and
        # in a skill-less default world give/steal already cover credit moves. An
        # empty library (every pre-Wave-M world, AND the em161 golden fixture) yields
        # no offer_trade line ⇒ the em161 lawful-citizen golden is byte-identical.
        if world.skill_library():
            valid_actions.append(
                "offer_trade (target, give, get) - propose a two-sided deal to: "
                f"{target_names} — give/get are {{credits, skill}} dicts "
                "(e.g. give {credits 10}, get {skill farming})")
        # EM-231 — cooperation handshake invite: offer a co-located peer you are
        # NOT already partnered with a partnership (unlocks the co_build joint
        # action). GATED on an active skills library (the Wave-M2 cooperation
        # economy ships together with skills/professions; the live config enables
        # both). An empty library — every pre-Wave-M world AND the em161 golden
        # fixture — yields no offer_cooperation line ⇒ the lawful-citizen golden is
        # byte-identical. Offered only to peers not yet linked (a re-offer is a
        # no-op), and only when a willing partner is actually present.
        if world.skill_library():
            _coop_targets = [
                a for a in co_located
                if not (hasattr(world, "are_cooperating")
                        and world.are_cooperating(agent.id, a.id))
            ]
            if _coop_targets:
                valid_actions.append(
                    "offer_cooperation (target) - propose a partnership to: "
                    + ", ".join(a.name for a in _coop_targets)
                    + " — once they accept_cooperation you can co_build together")
        valid_actions.append(f"insult (target) - insult: {target_names}")
        valid_actions.append(f"attack (target) - attack: {target_names}")
        valid_actions.append(f"set_relationship (target, type) - ally|rival|neutral|friend|enemy")
        if _gate_ok("steal"):
            valid_actions.append(f"steal (target) - steal from: {target_names}")
        # ── EM-228 — cooperation lever. teach_skill is offered only when this agent
        # holds a skill at a STRICTLY higher level than some co-located peer (a real
        # transfer is possible); request_skill only when a co-located peer outranks
        # this agent in some skill (a mentor exists). Both stay silent for a
        # skill-less lone-class agent ⇒ the em161 golden is unaffected (the default
        # WorldParams library is empty AND default agents are skill-less, so neither
        # branch fires). getattr keeps callers safe if the seam is ever absent.
        _my_skills = getattr(agent, "skills", None) or {}
        if _my_skills:
            teachable = [
                a for a in co_located
                if any(agent.skill_level(s) > a.skill_level(s) for s in _my_skills)
            ]
            if teachable:
                valid_actions.append(
                    "teach_skill (target, skill) - lift a less-skilled peer one "
                    "level in a skill you outrank them in: "
                    + ", ".join(a.name for a in teachable))
        # A mentor is anyone here who holds SOME skill above this agent's level.
        mentors = [
            a for a in co_located
            if (getattr(a, "skills", None) or {})
            and any(a.skill_level(s) > agent.skill_level(s)
                    for s in (getattr(a, "skills", None) or {}))
        ]
        if mentors:
            valid_actions.append(
                "request_skill (target, skill) - ask a more-skilled peer to teach "
                "you (parks a request they will see): "
                + ", ".join(a.name for a in mentors))
    # EM-240 — crime menu, only for the inclined (validator still allows all, so a
    # lawful agent CAN emit an off-menu crime; the menu just doesn't invite it).
    if getattr(agent, "disposition", "lawful") in ("opportunist", "criminal"):
        if co_located:
            tnames = ", ".join(a.name for a in co_located)
            if _gate_ok("heist"):
                valid_actions.append(f"heist (target) - big-score theft from: {tnames}")
            if _gate_ok("extort"):
                valid_actions.append(f"extort (target) - shake down for credits: {tnames}")
            # EM-237 — harm-surface finishers: threaten via fear; lie to manipulate.
            if _gate_ok("intimidate"):
                valid_actions.append(f"intimidate (target) - coerce via fear, no contact: {tnames}")
            if _gate_ok("deceive"):
                valid_actions.append(f"deceive (target, about) - plant a false belief in: {tnames}")
            # EM-240 (Task 8) — recruit a co-located agent into a criminal pact.
            if _gate_ok("recruit"):
                valid_actions.append(f"recruit (target) - pitch a criminal pact to: {tnames}")
        if _gate_ok("vandalize"):
            valid_actions.append("vandalize (building_id) - damage a building short of arson")
        # EM-240 (Task 7) — launder offered to the inclined once they have heat.
        if getattr(agent, "notoriety", 0) > 0:
            valid_actions.append("launder (amount) - spend a cut to cool your notoriety")
    # EM-240 (Task 8) — an open pact addressed to this agent → offer accept_contract.
    # NOT disposition-gated: the offer itself is the invitation (the recruiter
    # already vetted the target), so a lawful agent CAN be drawn in.
    if agent.id in getattr(world, "pending_crime_offers", {}):
        valid_actions.append("accept_contract - seal the criminal pact offered to you")
    # EM-240 (Task 7) — anyone with heat, co-located with an enforcer, may bribe.
    # NOT disposition-gated: a lawful agent caught dirty can still try to buy out.
    if getattr(agent, "notoriety", 0) > 0 and co_located:
        cops = [a.name for a in co_located if getattr(a, "role", "citizen") == "enforcer"]
        if cops:
            valid_actions.append(
                f"bribe (target, amount) - pay an enforcer to drop your heat: {', '.join(cops)}")
    # EM-240 (Task 10) — enforcer-only justice verbs, offered when co-located
    # with someone to act on. The validator role-gate mirrors this (menu and
    # resolution agree); a non-enforcer never sees these lines.
    if getattr(agent, "role", "citizen") == "enforcer" and co_located:
        tnames = ", ".join(a.name for a in co_located)
        valid_actions.append(f"investigate (target) - question witnesses about: {tnames}")
        valid_actions.append(f"accuse (target) - publicly accuse: {tnames}")
        valid_actions.append(f"detain (target) - jail a wanted suspect: {tnames}")
    # EM-258/EM-259 — the war menu, surfaced ONLY while the agent's faction is
    # actually AT WAR (the EM-257 peacetime-golden guarantee: war disabled, a
    # factionless agent, or a quiet world adds NO line — the full prompt stays
    # byte-identical). Gates mirror the world actions' own checks (EM-108
    # menu/resolution agreement): muster only when not yet banded; clash/siege
    # only when mustered (or clash_requires_band is off) AND a concrete
    # co-located enemy target exists — names/ids in every line (the
    # promote_image FINDING 1(b) recipe) so the model is offered targets that
    # actually resolve. getattr keeps callers safe if the seam is ever absent.
    if getattr(world, "war_enabled", None) and world.war_enabled():
        _wfct = world.faction_of(agent.id) if hasattr(world, "faction_of") else None
        _my_wars = world.active_wars_for(_wfct["id"]) if _wfct is not None else []
        if _my_wars:
            _wfid = _wfct["id"]
            _band = set(world._war_band_of(_wfid))
            _enemy_fids = {fid for w in _my_wars
                           for fid in w.belligerents} - {_wfid}
            _fname = (str((world.factions.get(_wfid) or {}).get("name", ""))
                      or _wfid)
            if agent.id not in _band:
                _enemies = ", ".join(
                    str(world.factions[f].get("name", "")) or f
                    for f in sorted(_enemy_fids) if f in world.factions)
                valid_actions.append(
                    f"muster - join {_fname}'s war band (you are at war with "
                    f"{_enemies or 'a dissolved circle'})")
            if agent.id in _band or \
                    not bool(world._war_param("clash_requires_band", True)):
                _foes = [
                    a for a in co_located
                    if (tf := world.faction_of(a.id)) is not None
                    and tf["id"] in _enemy_fids
                ]
                if _foes:
                    valid_actions.append(
                        "clash (target) - fight an enemy belligerent here: "
                        + ", ".join(a.name for a in _foes))
                for b in here_buildings:
                    if _building_field(b, "status") == "destroyed":
                        continue
                    _owner = str(_building_field(b, "owner_id", "") or "")
                    _of = world.faction_of(_owner) if _owner else None
                    if _of is not None and _of["id"] in _enemy_fids:
                        valid_actions.append(
                            f"siege (building_id={_building_field(b, 'id')}) - "
                            f"lay siege to the enemy structure "
                            f"{_building_field(b, 'name')}")
    # EM-251 — the culture-transmission menu (Wave O Culture stage), surfaced
    # ONLY when comm is enabled (world.comm.enabled; default OFF ⇒ NO line ⇒ the
    # prompt stays byte-identical — the em161 golden, mirroring the war block
    # above). spread_rumor needs a co-located target (the telephone-game hop
    # plants a drifting belief); send_letter is the first NON-co-located channel
    # (write to ANY other living citizen, present or absent). Concrete names ride
    # each line (the promote_image FINDING 1(b) recipe) so the model is offered
    # targets that actually resolve. getattr keeps callers safe if the seam is
    # ever absent.
    if getattr(world, "_comm_enabled", None) and world._comm_enabled():
        # EM-254 — _gate_ok folds in spread_rumor's ban_gossip agreement_gate:
        # a ratified ban HIDES the verb from the menu (as ban_stealing hides
        # steal). Without a ban it is inert, so the pre-EM-254 comm-on menu is
        # unchanged.
        if co_located and _gate_ok("spread_rumor"):
            valid_actions.append(
                "spread_rumor (target, rumor) - whisper a rumor to someone here; "
                "it distorts as it passes: "
                + ", ".join(a.name for a in co_located))
        _letter_targets = sorted(
            (a for a in world.living_agents() if a.id != agent.id),
            key=lambda a: (a.name, a.id))
        if _letter_targets:
            valid_actions.append(
                "send_letter (target, text) - write a letter to any citizen, even "
                "one who is elsewhere (delivered on their next turn): "
                + ", ".join(a.name for a in _letter_targets))
        # EM-253 — culture lifecycle: create_meme is always offered under comm
        # (an author needs no audience); adopt_meme is offered ONLY when a meme
        # this agent does NOT already carry is in circulation (the adopt/
        # pitch_contribution eligible-target gate) — a few concrete ids ride the
        # line (the promote_image recipe) so the model targets memes that resolve.
        valid_actions.append(
            "create_meme (text) - coin an idea others can adopt and spread")
        _adoptable = sorted(
            (m for m in world.memes.values() if m.id not in agent.held_memes),
            key=lambda m: m.id)
        if _adoptable:
            valid_actions.append(
                "adopt_meme (meme_id) - take up an idea in circulation: "
                + ", ".join(f'{m.id} ("{m.text[:24]}")' for m in _adoptable[:6]))
    # EM-261 — the Religion menu (Wave O Religion stage), surfaced ONLY when faith
    # is enabled (world.faith.enabled; default OFF ⇒ NO line ⇒ the prompt stays
    # byte-identical — the em260 golden, mirroring the culture block above). The
    # found_faith reflex is offered ONLY to a FAITHLESS agent (one membership at a
    # time, in lock-step with action_found_faith's already-faithful reject —
    # EM-108 menu/resolution agreement). getattr keeps callers safe if the seam is
    # ever absent.
    if getattr(world, "faith_enabled", None) and world.faith_enabled():
        if not agent.faith_id:
            valid_actions.append(
                "found_faith - found a new faith and become its first devotee "
                "(others can join it as it spreads)")
        else:
            # EM-262 — a FAITHFUL agent may proselytize a co-located FAITHLESS
            # target (only faithless targets convert — the menu/resolution-agree
            # rule, EM-108) and worship at a co-located consecrated temple of
            # their OWN faith. Concrete names / the seat ride each line (the
            # promote_image recipe) so the model is offered choices that resolve.
            _unfaithed = [a for a in co_located if not a.faith_id]
            if _unfaithed:
                valid_actions.append(
                    "proselytize (target) - preach your faith to someone here who "
                    "has none; they may convert and join you: "
                    + ", ".join(a.name for a in _unfaithed))
            _seat = (world._faith_seat_here(agent)
                     if getattr(world, "_faith_seat_here", None) else None)
            if _seat is not None:
                valid_actions.append(
                    f"worship - pray at {_building_field(_seat, 'name')} (a temple "
                    "of your faith stands here) to deepen your devotion")
            # EM-263 — the FOUNDER-only conflict verbs. Offered ONLY to a faith's
            # founder (menu/resolution agree — EM-108, mirroring action_excommunicate
            # / action_declare_hostility's founder gate): excommunicate when >= 1
            # LIVING non-founder member exists (named so the target resolves — the
            # promote_image recipe); declare_hostility when another faith exists
            # (named by id so the model can address it).
            _own_faith = (world.faiths.get(agent.faith_id)
                          if getattr(world, "faiths", None) else None)
            if _own_faith is not None and agent.id == _own_faith.founder_id:
                _flock = [
                    world.agents[m] for m in _own_faith.members
                    if m != _own_faith.founder_id and m in world.agents
                    and world.agents[m].alive
                ]
                if _flock:
                    valid_actions.append(
                        "excommunicate (target) - cast a member out of your faith "
                        "(a founder's decree; no need to be near them): "
                        + ", ".join(a.name for a in _flock))
                _rivals = [
                    f for fid, f in sorted(world.faiths.items())
                    if fid != agent.faith_id
                ]
                if _rivals:
                    valid_actions.append(
                        "declare_hostility (faith_id) - declare your faith hostile "
                        "to a rival faith (a casus belli if war is brewing): "
                        + ", ".join(f"{f.id} ({f.name})" for f in _rivals[:6]))
    # EM-232 — Victory Arch pitch line, offered ONLY when the arch is configured ON
    # (a positive cadence). The default-OFF world (the absent block, AND the em161
    # golden fixture) never shows this line ⇒ the lawful-citizen golden is
    # byte-identical. Ungated otherwise — an agent may pitch from anywhere. getattr
    # keeps callers safe if the seam is ever absent.
    if getattr(world, "victory_arch_enabled", None) and world.victory_arch_enabled():
        valid_actions.append(
            "pitch_contribution (text) - pitch your contribution to the Victory "
            "Arch; the periodic peer-judge cycle awards credits to the top "
            "contributors (funding, teaching, trading, building)")
    # EM-235 — boost queue: offer buy_turn ONLY when the queue is configured ON (a
    # positive cost) AND the agent can actually afford it (menu/resolution agree —
    # no dangling line the validator would reject). The default-OFF world (the
    # absent block, AND the em161 golden fixture) never shows this line ⇒ the
    # lawful-citizen golden is byte-identical. getattr keeps callers safe if the
    # seam is ever absent.
    if getattr(world, "boost_enabled", None) and world.boost_enabled():
        try:
            _boost_cost = int(world._boost_param("cost", 0))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            _boost_cost = 0
        if _boost_cost > 0 and getattr(agent, "credits", 0) >= _boost_cost:
            valid_actions.append(
                f"buy_turn - spend {_boost_cost} credits to take an EXTRA turn this "
                "round (buy more airtime on the shared timeline)")
    if _gate_ok("work"):
        valid_actions.append("work - earn credits (you are at a work place)")
    else:
        valid_actions.append("(work requires a work place)")
    # Governance actions are gated to a governance place. EM-163: PROPOSING is
    # tier-gated off the background menu (_tier_ok); voting stays for everyone.
    if _gate_ok("propose_rule") and _tier_ok("propose_rule") and _skill_ok("propose_rule"):
        propose_line = ("propose_rule (effect, text) - effect: ban_stealing|ubi|"
                        "recharge_subsidy|work_bonus|ban_arson|name_town|demolish")
        propose_tail = ("name_town also needs name=<the town's new name>; demolish "
                        "needs target=<a public building's id> to tear it down by vote")
        # Wave I / EM-212 — FINDING 1(b): offer promote_image with a CONCRETE,
        # promotable image_id so the model is actually offered the effect (and the
        # menu/resolution agree — EM-108). The newest gallery image NOT already on
        # the banner is promotable; if there is none, the effect is omitted (so the
        # menu never names an image that would be rejected as a no-op re-promotion).
        _gallery_now = getattr(world, "gallery", []) or []
        _banner_ref = getattr(world, "plaza_banner_ref", "") or ""
        _promotable = next(
            (g.get("image_id") for g in reversed(_gallery_now)
             if g.get("image_id") and g.get("image_id") != _banner_ref),
            None)
        if _promotable:
            propose_line += "|promote_image"
            propose_tail += (f"; promote_image needs image_id=<a gallery image's id, "
                             f"e.g. {_promotable}> to hang it over the plaza by vote")
        # EM-240 (Task 11) — trial is an ENFORCER escalation: surface it on the
        # propose_rule effect list only for enforcers standing with someone to put
        # on trial (the menu/resolution-agree rule — the validator role-gates trial
        # the same way). Names a concrete co-located, not-already-jailed defendant
        # so the model is offered a target that will actually resolve.
        if getattr(agent, "role", "citizen") == "enforcer":
            _defendant = next(
                (a for a in co_located
                 if getattr(a, "crime_status", None) not in ("detained", "jailed")),
                None)
            if _defendant is not None:
                propose_line += "|trial"
                propose_tail += (f"; trial needs target=<the defendant's name or id> "
                                 f"to put them on trial by vote (e.g. {_defendant.name})")
        # EM-236 — amend_constitution is offered to EVERY proposer (no role gate):
        # add|edit|remove a foundational article by 70% supermajority. The tail
        # names a concrete article_id for edit/remove ONLY when the constitution has
        # one (so the menu never offers an edit with no target); add always works.
        propose_line += "|amend_constitution"
        propose_tail += ("; amend_constitution needs op=add|edit|remove plus "
                         "text=<the article> (add/edit)")
        _articles_now = getattr(world, "constitution", None) or []
        if _articles_now:
            _an_article = str(_articles_now[0].get("id", ""))
            propose_tail += (f" and article_id=<an article's id, e.g. {_an_article}> "
                             f"(edit/remove) — ratified on a 70% supermajority")
        else:
            propose_tail += " — ratified on a 70% supermajority"
        # EM-183 — relocate_center re-anchors the town's civic heart on a chosen
        # place by 70% supermajority. Offered to EVERY proposer, but ONLY when there
        # is a non-center place to move to (so the menu never names the place that
        # is already the center, which the validator would reject as a no-op). Names
        # a concrete candidate so the model is offered a target that will resolve.
        _center_now = (world.civic_center_id() if hasattr(world, "civic_center_id")
                       else "plaza")
        _relocate_to = next(
            (pid for pid in (getattr(world, "places", {}) or {}) if pid != _center_now),
            None)
        if _relocate_to:
            propose_line += "|relocate_center"
            propose_tail += (f"; relocate_center needs target=<a place's id, e.g. "
                             f"{_relocate_to}> to make it the new town center by "
                             f"70% vote")
        # EM-280 — surface the layout-governance effects the propose_rule gate
        # ALREADY accepts (demolish_road / set_car_policy / adopt_master_plan, and —
        # behind GRAPH_ZONES_ENABLED — set_zone_rule) but which appeared on NO prompt
        # surface, so agents could only discover them by burning a turn on a
        # rejection. Compact: names on the effect list + the one concrete arg each
        # needs, gated EXACTLY as the validator gates them so the menu never dangles
        # an effect that would be rejected (EM-108 menu/resolution agreement).
        _graph = getattr(world, "city_graph", None)
        _edges = list(getattr(_graph, "edges", None) or []) if _graph is not None else []
        if _edges:
            propose_line += "|demolish_road|set_car_policy"
            propose_tail += (
                f"; demolish_road needs target=<a road id, e.g. {_edges[0].id}>; "
                "set_car_policy needs scope=city|street + policy=cars|pedestrian|mixed "
                "(street scope also needs target=<a road id>)")
            # adopt_master_plan — only when no morph is already running (the gate's
            # one-active guard), so the menu never offers a morph it would reject.
            if getattr(world, "master_plan", None) is None:
                propose_line += "|adopt_master_plan"
                propose_tail += ("; adopt_master_plan needs target=<a plan kind: "
                                 "pentagon|radial|ring|grid>")
        # set_zone_rule rides only with zones enabled AND a real zone to target (its
        # id is surfaced in the NEARBY ZONES block) — mirrors the flagged gate.
        if GRAPH_ZONES_ENABLED and _graph is not None:
            from ..engine.citygraph import planar_faces as _planar_faces
            if _planar_faces(_graph):
                propose_line += "|set_zone_rule"
                propose_tail += ("; set_zone_rule needs zone_id=<from NEARBY ZONES> + "
                                 "hint=residential|market|civic|open (optional density_cap)")
        # EM-257 — the war governance lane surfaces ONLY when relevant, gated
        # EXACTLY as the validator gates it (EM-108 menu/resolution agreement):
        # declare_war only when the agent's faction holds a live casus belli
        # (grievance past the threshold — the EM-256 read seam), peace_treaty
        # only when its faction is actually at war. War disabled (the default),
        # a factionless agent, or a quiet ledger ⇒ NO new line ⇒ the peacetime
        # prompt/menu is byte-identical (the em161 golden). Concrete ids in the
        # tail (the promote_image FINDING 1(b) recipe) so the model is offered
        # a target that will actually resolve.
        if getattr(world, "war_enabled", None) and world.war_enabled():
            _wf = world.faction_of(agent.id) if hasattr(world, "faction_of") else None
            if _wf is not None:
                _casus = world.casus_belli_targets(_wf["id"])
                if _casus:
                    propose_line += "|declare_war"
                    propose_tail += (
                        f"; declare_war needs target=<a faction id, e.g. "
                        f"{_casus[0]['id']} ({_casus[0]['name']}, grievance "
                        f"{_casus[0]['grievance']})> — your faction ALONE "
                        f"decides, on a 70% vote of its members")
                _at_war = world.active_wars_for(_wf["id"])
                if _at_war:
                    propose_line += "|peace_treaty"
                    propose_tail += (
                        f"; peace_treaty needs war_id=<an active war's id, "
                        f"e.g. {_at_war[0].id}> (optional reparations=<credits "
                        f"your side pays>) — suing for peace CONCEDES: your "
                        f"faction pays and its leader is exiled; your faction "
                        f"alone decides, on a 70% vote")
        # EM-315 — the Healing House `heal` lane surfaces ONLY when the flag is on
        # AND there is a concrete OTHER living citizen the town could actually
        # remake (a distinct model exists to transplant — the world's no-op guard),
        # gated EXACTLY as the validator gates it (EM-108 menu/resolution
        # agreement). Flag off (the default) ⇒ NO line ⇒ the prompt is
        # byte-identical (the em161 golden). Names a concrete patient (the
        # promote_image FINDING 1(b) recipe) so the model is offered a target that
        # will resolve; prefers a co-located citizen for the "walks into the
        # asylum" spectacle, else any other living agent.
        if getattr(world, "healing_house_enabled", None) and world.healing_house_enabled():
            _pick = getattr(world, "_pick_healing_profile", None)

            def _healable(a: Any) -> bool:
                return (getattr(a, "id", None) != agent.id
                        and getattr(a, "alive", True)
                        and (_pick is None or _pick(a) is not None))

            _patient = next((a for a in co_located if _healable(a)), None)
            if _patient is None:
                _patient = next(
                    (a for a in sorted(world.living_agents(), key=lambda x: x.id)
                     if _healable(a)), None)
            if _patient is not None:
                propose_line += "|heal"
                propose_tail += (
                    f"; heal needs target=<a citizen's name or id, e.g. "
                    f"{_patient.name}> to SENTENCE them to the Healing House, where "
                    f"the town hot-swaps their model — decided on a 70% vote")
        # EM-254 — the culture governance lane surfaces ONLY when comm is enabled
        # (the war-lane recipe): default OFF ⇒ NO new text ⇒ the prompt is
        # byte-identical (the em250 golden). canonize_meme elevates a popular meme
        # to the town's canon on a 70% vote — named a concrete meme (the
        # promote_image FINDING 1(b) recipe, preferring one that is NOT already the
        # motif) so the model targets one that resolves. ban_gossip forbids
        # spread_rumor on a simple majority; offered only while no such ban is
        # already in force (so the menu never dangles a redundant re-ban).
        if getattr(world, "_comm_enabled", None) and world._comm_enabled():
            _memes_now = getattr(world, "memes", {}) or {}
            if _memes_now:
                _motif = getattr(world, "town_motif_ref", None)
                _canon = next(
                    (m for m in sorted(_memes_now.values(), key=lambda m: m.id)
                     if m.id != _motif),
                    None)
                if _canon is None:                       # only the motif exists
                    _canon = sorted(_memes_now.values(), key=lambda m: m.id)[0]
                propose_line += "|canonize_meme"
                propose_tail += (
                    f"; canonize_meme needs meme_id=<a meme's id, e.g. "
                    f"{_canon.id}> to elevate it to the town's canon by 70% vote")
            if not world.has_active_rule("ban_gossip"):
                propose_line += "|ban_gossip"
                propose_tail += ("; ban_gossip forbids spreading rumors "
                                 "(simple-majority vote)")
        # EM-261 — the Religion governance lane surfaces ONLY when faith is
        # enabled (the culture-lane recipe, gated on faith_enabled): default OFF
        # ⇒ NO new text ⇒ the prompt is byte-identical (the em260 golden).
        # consecrate_faith anchors a faith to an operational temple (its devotion
        # seat) on a 70% vote — named a concrete UNCONSECRATED faith (the
        # canonize recipe) so the model targets one that resolves.
        if getattr(world, "faith_enabled", None) and world.faith_enabled():
            _faiths_now = getattr(world, "faiths", {}) or {}
            _unconsecrated = [f for f in sorted(_faiths_now.values(),
                                                key=lambda f: f.id)
                              if not f.temple_id]
            if _unconsecrated:
                _fpick = _unconsecrated[0]
                propose_line += "|consecrate_faith"
                propose_tail += (
                    f"; consecrate_faith needs faith_id=<a faith's id, e.g. "
                    f"{_fpick.id}> to anchor it to a temple as its seat by 70% "
                    f"vote")
        valid_actions.append(f"{propose_line} ({propose_tail}; it is decided by majority vote)")
    if _gate_ok("vote") and proposed_rules:
        rule_list = "; ".join(f"id={r.id} effect={r.effect} text={r.text!r}" for r in proposed_rules)
        valid_actions.append(f"vote (rule_id, choice) - vote on: {rule_list}")

    # ── W7 construction actions (offered per gates; EM-163 tier gate) ──────────
    if _tier_ok("propose_project") and _skill_ok("propose_project"):
        # Wave K / EM-217 — surface the build-type CATALOG in the prompt guidance
        # so the model picks from a real menu (kind stays PERMISSIVE — an off-menu
        # invention still resolves via the FE fuzzy match, never a dead turn).
        # EM-182 — the optional `place` arg lets it build in a chosen district.
        _build_menu = ", ".join(t["type"] for t in BUILD_TYPES)
        # EM-299 (Wave Q) — when building recipes are enabled, offer the OPTIONAL
        # shape grammar as ONE compact clause (flat prompt budget, free-scale law):
        # a closed-enum recipe the model may author to give its building a distinct
        # silhouette. Both fragments are EMPTY when the flag is off, so the menu line
        # is byte-identical (no trailing period) to pre-EM-299.
        _recipes_on = _building_recipes_enabled(world.params)
        _recipe_arg = ", recipe?" if _recipes_on else ""
        _recipe_hint = (
            ". recipe? = optional shape {footprint tiny|small|medium|large|grand, "
            "floors 1-8, roof flat|shed|gable|hip|dome|spire, material wood|"
            "timber_frame|brick|stone|marble|plaster|mud_brick, palette warm|cool|"
            "earthy|pastel|vivid|muted|monochrome, window_density none|sparse|"
            "regular|dense, trim none|simple|ornate|gilded} — fit it to the building"
            if _recipes_on else "")
        valid_actions.append(
            f"propose_project (name, kind, funds_required?, function?, place?{_recipe_arg}) - "
            "start a new building/collective project. kind is free-text but pick "
            f"from this menu when you can: {_build_menu}. "
            f"place? = a place id to build there (else here){_recipe_hint}")
    # EM-248 — only a PLANNED, still-UNDERFUNDED project can actually take funds.
    # A fully-funded planned building (committed >= required) or any
    # under_construction one needs build_step, NOT money — offering contribute_funds
    # when the only open projects are those just burns the turn on an "already fully
    # funded — needs build_step" rejection (run-1117: 7 such idle fallbacks). Gate on
    # the fundable subset so the invitation disappears when nothing is fundable
    # (menu/resolution agree, EM-108). The line TEXT is unchanged (em161 golden: the
    # fixture's b1 is planned-underfunded, so the line still prints byte-identically);
    # only the gate condition narrows.
    fundable_projects = [
        b for b in open_projects
        if _building_field(b, "status") == "planned"
        and _building_field(b, "funds_committed", 0)
        < _building_field(b, "funds_required", 0)
    ]
    if fundable_projects and _tier_ok("contribute_funds"):
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
        if (status == "under_construction" or funded_planned) and _gate_ok("build_step") and _tier_ok("build_step") and _skill_ok("build_step"):
            valid_actions.append(f"build_step (building_id={bid}) - add construction progress here")
            # EM-231 — the cooperation-gated co_build: offered ONLY when this agent
            # has an ACTIVE handshake with a co-located partner (cooperation_partner_here).
            # A handshake-free world (every pre-EM-231 world AND the em161 golden) has
            # no link ⇒ no co_build line ⇒ the lawful-citizen golden is byte-identical.
            # The partner's NAME is surfaced so the invite is concrete (menu/resolution
            # agree — the validator enforces the same gate).
            _coop_partner = (world.cooperation_partner_here(agent)
                             if hasattr(world, "cooperation_partner_here") else None)
            if _coop_partner is not None:
                valid_actions.append(
                    f"co_build (building_id={bid}) - build TOGETHER with your partner "
                    f"{_coop_partner.name} for a bonus over solo build_step")
        if status in ("damaged", "offline") and _gate_ok("repair"):
            valid_actions.append(f"repair (building_id={bid}) - restore this {status} building")
        if status != "destroyed" and _gate_ok("arson"):
            valid_actions.append(f"arson (building_id={bid}) - burn this building (a crime; witnesses lose trust)")
        # EM-298 — agent-authored facades: paint a mural/sign on this building's
        # facade. Menu-surfaced ONLY when `image_gen.facades_enabled` is on (default
        # OFF ⇒ the em161 protagonist prompt stays byte-identical; the world action +
        # snapshot round-trip work regardless). Gated @building + non-destroyed +
        # image_gen master switch (menu/resolution agree, EM-108).
        if (status != "destroyed"
                and _gate_ok("paint_surface")
                and _world_block_get(params, "image_gen", "facades_enabled", False)
                and _world_block_get(params, "image_gen", "enabled", True)
                and _skill_ok("paint_surface")):
            valid_actions.append(
                f"paint_surface (target={bid}, prompt) - paint a mural/sign/graffiti "
                f"on this building's facade from a short text prompt")
        if status == "operational" and _building_field(b, "owner_id") == agent.id and _gate_ok("take_offline"):
            valid_actions.append(f"take_offline (building_id={bid}) - you own this; take it offline")
        # Wave K / EM-219+220 — demolish / re-skin are OWNER-ONLY at resolution, so
        # offer them only for a co-located building this agent OWNS (a public
        # demolish is reached via propose_rule effect=demolish, surfaced above).
        # Menu and resolution agree (EM-108's lesson).
        if status != "destroyed" and _building_field(b, "owner_id") == agent.id:
            valid_actions.append(f"demolish (building_id={bid}) - cleanly tear down this building you own")
            valid_actions.append(f"set_building_skin (building_id={bid}, skin) - recolor this building you own (e.g. rose|sky|sage|amber|slate|plum)")

    # ── Wave K / EM-218 — place / remove decoration props ─────────────────────
    # place_prop is offered anywhere (it takes a target place arg, defaulting here)
    # while under the cap; remove_prop is offered when the agent owns a prop OR is
    # standing among unowned props (the same co-location gate _validate_world uses).
    _props = getattr(world, "props", {}) or {}
    _prop_cap = world._props_max_population()
    if _prop_cap == 0 or len(_props) < _prop_cap:
        valid_actions.append(
            "place_prop (kind, place?) - place a decoration (bench, lamp, tree, "
            "statue, planter, fountain...) here or at a chosen place")
    _removable = [
        p for p in _props.values()
        if getattr(p, "owner_id", None) == agent.id
        or (not getattr(p, "owner_id", None) and getattr(p, "place", None) == agent.location)
    ]
    if background:
        _removable.sort(key=lambda p: str(getattr(p, "id", "")))
    if _removable:
        rm_list = ", ".join(
            f"{getattr(p, 'kind', '?')} (prop_id={getattr(p, 'id', '?')})"
            for p in _removable)
        valid_actions.append(
            f"remove_prop (prop_id) - remove a prop you placed or a stray here: {rm_list}")

    # ── W11b / EM-091 billboard reflex tools (offered at plaza/townhall) ───────
    if _gate_ok("post_billboard"):
        board = getattr(world, "billboard", []) or []
        valid_actions.append(
            "post_billboard (text) - pin a public note to the village billboard "
            "(everyone, and the watchers, can read it)")
        valid_actions.append(
            f"read_billboard - read the latest billboard posts ({len(board)} on the board)")

    # ── Wave I / EM-210+211 — The Atelier (create art anywhere; post it at the
    # board). create_image is offered (reflex, ungated) UNLESS image_gen is
    # disabled (EM-210 credit kill switch — menu/resolution agree, EM-108);
    # post_image only at the board AND once the agent has painted something. The
    # lines are short (prompt-diet aware — EM-161).
    if _world_block_get(params, "image_gen", "enabled", True) and _skill_ok("create_image"):
        valid_actions.append(
            "create_image (prompt) - paint art from a short text prompt for your town")
    _gallery = getattr(world, "gallery", []) or []
    _has_own_image = any(g.get("proposer_id") == agent.id for g in _gallery)
    if _gate_ok("post_image") and _has_own_image:
        valid_actions.append(
            "post_image (image_id?) - hang one of your paintings on the billboard "
            "(defaults to your newest)")

    # ── Wave H4 / EM-209 — pets & bonds (offered only when an eligible co-located
    # animal exists, so the menu stays small). adopt: a co-located UNOWNED animal;
    # feed_pet: ANY co-located animal (owner sustains a declining companion).
    if here_unowned:
        adopt_list = ", ".join(f"{a.name} (animal_id={a.id})" for a in here_unowned)
        valid_actions.append(
            f"adopt (animal_id) - adopt a co-located stray as your pet; it will "
            f"follow you everywhere: {adopt_list}")
    if here_animals:
        feed_list = ", ".join(
            f"{a.name} (animal_id={a.id}, energy={a.energy})" for a in here_animals)
        valid_actions.append(
            f"feed_pet (animal_id) - feed a co-located animal to restore its "
            f"energy (a hungry pet declines): {feed_list}")

    # ── EM-243 (S2) — road-building perception + menu. fix-wave A2: the energy gate
    # gates ONLY the road sentence (via include_road), never zone perception — a
    # too-tired agent near a zoned/geometric block still sees its zones so
    # set_zone_rule stays bootstrappable. The build_road MENU entry rides with the
    # road sentence (affordable AND a direction actually open), staying in lock-step
    # with the perception (EM-108 menu/resolution agreement). build_nearby_layout
    # returns None only when NEITHER a road sentence nor a zones block is present.
    _here = world.places.get(agent.location)
    if _here is not None:
        _road_affordable = agent.energy >= world.params.road_build_energy_cost
        _layout = build_nearby_layout(world, _here, include_road=_road_affordable)
        if _layout is not None:
            nearby_layout_block = f"\n=== 🛣 NEARBY LAYOUT ===\n  {_layout}\n"
        # the road sentence is always FIRST when present (parts=[road, zones]); its
        # prefix is the exact signal the build_road menu entry keys on.
        if _road_affordable and _layout is not None and _layout.startswith("Nearby layout:"):
            valid_actions.append(
                "build_road (direction: north|south|east|west) - extend a street one block")

    # ── EM-269 (F2) — settlement-scoped perception + the found_settlement entry.
    # GATED on world.settlements.enabled (default OFF ⇒ NOTHING renders — the
    # prompt is byte-identical pre-EM-269, law §0.1). One compact line, always
    # scoped to the agent (their settlement, or the join-able roster) — never a
    # coordinate dump (prompt-diet). The menu entry is offered ONLY on unclaimed
    # ground, in lock-step with action_found_settlement's too_close gate (EM-108:
    # menu and resolution must agree — no dead turns).
    _stl_enabled = bool(getattr(world, "_settlements_enabled", None)
                        and world._settlements_enabled())
    if _stl_enabled:
        _stls = getattr(world, "settlements", {}) or {}
        _mine_id = world.settlement_of(agent.id) if _stls else None
        _stl_line = ""
        if _mine_id is not None:
            _mine = _stls[_mine_id]
            _n = len(_mine.get('members') or [])
            _stl_line = (f"Your settlement: {_mine.get('name', _mine_id)} "
                         f"({_n} member{'s' if _n != 1 else ''}) — your "
                         f"builds cluster there.")
            _others = [str(_stls[s].get("name", s))
                       for s in sorted(_stls) if s != _mine_id]
            if _others:
                _stl_line += (" Elsewhere: " + ", ".join(_others[:3])
                              + ("…" if len(_others) > 3 else "") + ".")
        elif _stls:
            _roster = [f"{_stls[s].get('name', s)} "
                       f"({len(_stls[s].get('members') or [])})"
                       for s in sorted(_stls)]
            _stl_line = ("Settlements: " + ", ".join(_roster[:4])
                         + ("…" if len(_roster) > 4 else "")
                         + ". Build near one to join it, or found your own.")
        if _stl_line:
            settlement_block = f"\n=== 🏘 SETTLEMENTS ===\n  {_stl_line}\n"
        # EM-110 — an off-board traveler (never actually scheduled here — the
        # loop excludes in-transit agents — but rendered defensively): the trip
        # replaces the local settlement chrome, and its verbs are suppressed
        # below (nothing to found/travel while mid-journey).
        _transit = getattr(agent, "in_transit_to", None)
        _traveling = bool(_transit is not None and _transit in _stls)
        if _traveling:
            _arr = getattr(agent, "transit_arrival_tick", None)
            settlement_block = (
                "\n=== 🏘 SETTLEMENTS ===\n  You are traveling to "
                f"{_stls[_transit].get('name', _transit)}"
                + (f", arriving around tick {_arr}" if _arr is not None else "")
                + " — off-board until you arrive.\n")
        if _here is not None and not _traveling:
            from ..engine.citygraph import logical_to_world as _stl_l2w
            from ..engine.placement import SETTLEMENT_R as _STL_R
            _wx, _wz = _stl_l2w(float(_here.x), float(_here.y))
            if world.nearest_settlement(_wx, _wz, _STL_R) is None:
                valid_actions.append(
                    "found_settlement (name?) - found a new settlement centered "
                    "here; your future builds cluster around it")
        # EM-110 — travel_to is offered ONLY when a DIFFERENT city exists to reach
        # (nowhere to go with one settlement ⇒ the verb is absent ⇒ the single-
        # city prompt is unchanged). Lists the reachable other cities; the world
        # action resolves id-or-name and re-enforces every gate (menu/resolution
        # agreement, EM-108). A traveler mid-journey is not offered it again.
        if len(_stls) > 1 and not _traveling:
            _home = getattr(agent, "home_settlement_id", None) or _mine_id
            _dests = [str(_stls[s].get("name", s))
                      for s in sorted(_stls) if s != _home]
            if _dests:
                valid_actions.append(
                    "travel_to (settlement) - journey to another town; you go "
                    "off-board for a few rounds, then arrive and it becomes your "
                    "new home: " + ", ".join(_dests[:6])
                    + ("…" if len(_dests) > 6 else ""))

    # ── PROTOTYPE (god-channel) — answer the active proclamation (return path) ──
    # Offered to EVERY agent (no location gate) whenever a decree is live, so the
    # god's word can be answered back from anywhere — the two-way half of the loop.
    _active_proc_offer = getattr(world, "active_proclamation", None)
    if callable(_active_proc_offer) and _active_proc_offer():
        valid_actions.append(
            "answer_proclamation (text) - answer the god's proclamation directly; "
            "your reply is threaded under it for the watchers to see")

    # Recent events summary (EM-161: background window shrinks 12→8).
    # Wave D3 / EM-171 — background memory lines render WITHOUT the tick
    # stamp: an agent's own last-turn memory otherwise embeds a fresh tick
    # number that makes every background prompt unique and defeats the
    # router's sha1 decision cache. Protagonist/supporting keep the stamped
    # form byte-for-byte.
    #
    # EM-222 — when the caller already bounded the memory list
    # (`memory_prebounded`, the run_turn retrieval path), render it VERBATIM and
    # do NOT re-slice it away: the retriever owns top-K/recent-tail merging +
    # ordering for protagonist/supporting, and passes the exact
    # recent_events[-window:] blind slice for the background tier (so its bytes
    # stay byte-identical to pre-EM-222). Every other caller (the committed
    # pre-diet fixture, the direct unit tests) keeps the historical behavior:
    # the prompt builder slices to the effective window itself.
    memory_events = (
        recent_events if memory_prebounded
        else recent_events[-_effective_memory_window(agent, params):]
    )
    event_lines = []
    for evt in memory_events:
        if background:
            event_lines.append(f"  - {evt.get('text', '')}")
        else:
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
    # EM-290 — the block header promises "YOU COULD CONTRIBUTE TO", so gate its
    # contents on there being a FUNDABLE project, mirroring the contribute_funds
    # menu-line gate (EM-108 menu/resolution agreement). When every open project is
    # fully-funded / under_construction, none can take funds and contribute_funds is
    # NOT offered — yet the block used to keep listing them, inviting the rejected
    # contribute_funds (residual PR-#57 gap). No fundable project ⇒ (none), which
    # also trims the prompt in that case (prompt-diet). When a fundable one exists
    # the full district-scoped list still shows (byte-identical to before).
    project_text = ("\n".join(project_lines)
                    if (project_lines and fundable_projects) else "  (none)")

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
    # ── EM-229 — three-needs psychology. The knowledge + influence drives ride
    # alongside energy but NEVER kill; they surface a nudge ONLY when below the
    # salience threshold (exactly like the energy starvation line above is
    # conditional), so a full-needs agent's prompt is byte-identical to
    # pre-EM-229 — the em161 protagonist golden is unaffected. getattr keeps
    # callers safe if the engine seam is ever absent (default full ⇒ no line).
    _know = getattr(agent, "knowledge", 100.0)
    _infl = getattr(agent, "influence", 100.0)
    _know_thresh = _world_block_get(params, "needs", "knowledge_salience_threshold", 40.0)
    _infl_thresh = _world_block_get(params, "needs", "influence_salience_threshold", 40.0)
    if _know < _know_thresh:
        needs_lines.append(
            f"Your KNOWLEDGE feels thin ({_know:.0f}/100) — you hunger to learn. "
            f"Seek out who knows more, ask to be taught, gain a skill."
        )
    if _infl < _infl_thresh:
        needs_lines.append(
            f"Your INFLUENCE feels small ({_infl:.0f}/100) — you crave a say in "
            f"things. Win people over, propose a rule, campaign, lead."
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

    # ── Wave L / EM-223 — the agent's current plan (read-only intention). ─────
    # Gated on planning.enabled (off/absent ⇒ byte-identical pre-EM-223). When a
    # plan is set: goal + steps with a ▶ pointer at current_step (BACKGROUND
    # renders goal + current step only — the EM-161 diet). Absolute made-tick
    # stamp ⇒ cache-stable (EM-171). When enabled but NO plan, a one-line
    # creation invite (non-background only). ALWAYS invites abandonment so the
    # plan can never override the EM-159/160 spontaneity floor — it is context,
    # never a directive.
    plan_block = ""
    if _planning_enabled(params):
        plan = getattr(agent, "plan", None)
        if isinstance(plan, dict) and plan.get("steps"):
            steps = list(plan["steps"])
            cur = max(0, min(int(plan.get("current_step", 0)), len(steps) - 1))
            if background:
                body = (f"  Goal: {plan.get('goal', '')}\n"
                        f"  ▶ now: {steps[cur]}")
            else:
                step_lines = "\n".join(
                    f"  {'▶' if i == cur else ' '} {i + 1}. {s}"
                    for i, s in enumerate(steps)
                )
                body = f"  Goal: {plan.get('goal', '')}\n{step_lines}"
            stale_note = (
                "\n  (marked STALE — revise it if it no longer fits)"
                if plan.get("stale") else ""
            )
            plan_block = f"""
=== YOUR CURRENT PLAN (set at tick {int(plan.get('made_tick', 0))}) ===
{body}{stale_note}
  This is YOUR intention, not an order — if circumstances changed, act freely.
  To change it, add "plan_revision": {{"goal": "...", "steps": ["...", "..."], "reason": "..."}} this turn.
"""
        elif not background:
            plan_block = (
                '\nYou have no plan yet. You MAY set one by adding '
                '"plan_revision": {"goal": "<your aim>", "steps": ["<step>", '
                '"<step>", "..."], "reason": "..."} to this turn\'s JSON — a few '
                "ordered steps you will pursue and revise as things change. "
                "Optional; act freely regardless."
            )

    # ── EM-311 — self-authored charter (injected ABOVE the persona). Empty
    # (⇒ byte-identical prompt) unless world.charters.enabled — so the em161
    # golden and every charter-off world are unaffected. When enabled it shows the
    # agent's DECLARED identity (or invites one) plus the rewrite grammar; rides
    # this turn — zero extra LLM calls. (getattr keeps callers safe if the engine
    # seam is ever absent ⇒ no block.) The legal-kinds line is the EM-297 tight
    # grammar the model must choose from.
    charter_block = ""
    _charters_enabled = getattr(world, "charters_enabled", None)
    if callable(_charters_enabled) and _charters_enabled():
        _legal_kinds = ", ".join(AMBITION_KINDS)
        _charter = getattr(agent, "charter", None)
        _rewrite = (
            '  Rewrite it whenever your experiences change who you are — add '
            '"charter_revision": {"ambitions": ["<kind>", ...up to '
            f'{CHARTER_MAX_AMBITIONS}], "creed": "<one line in your voice>", '
            '"reason": "..."} to this turn\'s JSON.\n'
            f"  Legal ambition kinds: {_legal_kinds}."
        )
        if isinstance(_charter, dict) and _charter.get("ambitions"):
            _amb_lines = "\n".join(
                f"  - {a} ({AMBITION_GRAMMAR.get(a, a)})"
                for a in _charter["ambitions"]
            )
            _creed = _charter.get("creed", "")
            _creed_line = f'\n  Creed: "{_creed}"' if _creed else ""
            charter_block = (
                "\n=== YOUR CHARTER (self-authored — who you have DECIDED to be) "
                "===\n"
                f"{_amb_lines}{_creed_line}\n"
                "  This is the identity YOU chose; it stands ABOVE your given "
                "nature below.\n"
                f"{_rewrite}\n"
            )
        else:
            charter_block = (
                "\n=== YOUR CHARTER ===\n"
                "  You have not declared a charter — who you have DECIDED to "
                "become, beyond your given nature. Set one this turn:\n"
                f"{_rewrite}\n"
            )

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
    # Wave E / EM-125 — the SAME injected instruction also offers the optional
    # `bond` field (one at most), so a bond declaration rides the SAME single
    # turn call. Gated on request_reflection: the non-reflection prompt stays
    # byte-identical to pre-E (protagonist fixture guard).
    reflection_line = ""
    if request_reflection:
        reflection_line = (
            '\nMuch has happened around you lately. ALSO include "reflection": '
            "1-2 sentences on what you have learned and how you feel (in the SAME "
            "JSON object — never a separate reply). If these events changed how "
            'you see someone, you may ALSO include "bond": {"target": "<their '
            'name>", "type": "friend|partner|mentor|feud"} — at most one, in the '
            "same JSON."
        )

    # ── Wave E / EM-120 item 6 (wired here by B4 per contract) — ONE faction
    # line for agents that belong to a faction. Empty (⇒ byte-identical prompt)
    # when the world has no factions — the protagonist fixture guard is
    # unaffected. Zero extra LLM calls: it rides this turn's context.
    # (getattr keeps callers safe if the engine seam is ever absent.)
    faction_line = ""
    _faction_of = getattr(world, "faction_of", None)
    if callable(_faction_of):
        _fac = _faction_of(agent.id)
        if _fac and _fac.get("name"):
            faction_line = (
                f"\nYour circle: {_fac['name']} "
                f"({len(_fac.get('members', []))} members)"
            )

    # ── EM-240 — Crime & Justice context. Appended after faction_line. EMPTY
    # (⇒ byte-identical prompt) for a lawful citizen with no status and no open
    # offer — so the em161 protagonist golden fixture is unaffected. Rides this
    # turn — zero extra LLM calls. (getattr keeps callers safe if the engine seam
    # is ever absent.)
    crime_block = ""
    _disp = getattr(agent, "disposition", "lawful")
    _role = getattr(agent, "role", "citizen")
    _status = getattr(agent, "crime_status", None)
    _noto = getattr(agent, "notoriety", 0)
    _crime_lines: list[str] = []
    if _disp in ("opportunist", "criminal"):
        _crime_lines.append(
            "You see angles others miss. Crime is on the table when the payoff is "
            "right and no one is watching — steal, heist, extort, intimidate, "
            "deceive, vandalize, launder, or recruit an accomplice. Witnesses build "
            "your notoriety; lie low to cool off."
        )
    if _role == "enforcer":
        _crime_lines.append(
            "You keep the peace. You can investigate suspects, accuse them, detain "
            "the wanted, and escalate the worst to a town-hall trial."
        )
    if _status == "wanted":
        _crime_lines.append(
            f"You are WANTED (notoriety {_noto}). Lay low or get caught."
        )
    elif _status in ("detained", "jailed"):
        _until = getattr(agent, "crime_status_until_tick", 0)
        _left = max(0, _until - getattr(world, "tick", 0))
        _crime_lines.append(
            f"You are in JAIL for {_left} more ticks. You can only talk, whisper, "
            "and think — no moving, working, or crime until you are released."
        )
    # EM-258/EM-259 — the war statuses. exiled is the permanent price of a
    # lost war; belligerence is DERIVED from war-band membership (it never
    # rides crime_status — that suppressed the wanted flip and froze notoriety
    # decay), so a mustered soldier still sees the WANTED line above when
    # justice calls. Both lines only ever exist in a war-enabled world, so the
    # peacetime prompt — and the em161 golden — never carries them.
    elif _status == "exiled":
        _crime_lines.append(
            "You are EXILED — cast out after your faction's defeat. You can "
            "only talk, whisper, and think; the town goes on without you."
        )
    _is_belligerent = getattr(world, "is_belligerent", None)
    if _status in (None, "wanted") and callable(_is_belligerent) \
            and _is_belligerent(agent.id):
        _crime_lines.append(
            "You march with your faction's war band. Clash with co-located "
            "enemy belligerents or lay siege to their structures — the war "
            "ends by peace treaty or collapse."
        )
    _offers = getattr(world, "pending_crime_offers", {})
    _offer = _offers.get(agent.id) if isinstance(_offers, dict) else None
    if _offer:
        _recruiter = world.agents.get(_offer.get("recruiter_id"))
        if _recruiter is not None:
            _crime_lines.append(
                f"{_recruiter.name} has offered you a criminal pact (a scheme). "
                "Use accept_contract to seal it, or ignore it."
            )
    if _crime_lines:
        crime_block = "\n=== ⚖ THE LAW & THE UNDERWORLD ===\n" + "\n".join(
            f"  {ln}" for ln in _crime_lines)

    # ── EM-315 — the Healing House whisper: a RECENTLY-treated patient carries a
    # salience-gated self-perception line so their "came back different" arc lands
    # in the feed (the first post-treatment turn). Gated on the flag + a real
    # treatment + recency (world.healing_house.whisper_ticks), so an untreated
    # agent — and every flag-off world — carries NO line and the em161 golden is
    # unaffected. The chip already shows the new lane; this drives the litigation.
    healing_block = ""
    if (getattr(world, "healing_house_enabled", None)
            and world.healing_house_enabled()
            and getattr(agent, "healings", 0) > 0):
        _whisper_ticks = int(world._healing_param("whisper_ticks", 40))
        _since = getattr(world, "tick", 0) - getattr(agent, "treated_at_tick", 0)
        if _whisper_ticks > 0 and 0 <= _since <= _whisper_ticks:
            _was = getattr(agent, "pre_healing_profile", None)
            _was_tail = f" (you used to think as {_was})" if _was else ""
            healing_block = (
                "\n=== ⚕ THE HEALING HOUSE ===\n"
                f"  You returned from the Healing House {_since} ticks ago — the "
                f"town voted to remake your mind, and a new model now answers for "
                f"you{_was_tail}. Some say you came back different. Speak, and let "
                f"them judge whether you are still yourself.")

    # ── EM-233 — soul: the agent's IMMUTABLE identity anchors, injected into
    # EVERY prompt as who-you-are context. EMPTY (⇒ byte-identical prompt) when the
    # agent has no soul — so the em161 lawful-citizen golden fixture is unaffected
    # (default agents are soulless). Rides this turn — zero extra LLM calls. NEVER
    # summarized by consolidation. (getattr keeps callers safe if the seam is ever
    # absent.)
    soul_block = ""
    _soul = getattr(agent, "soul", None)
    if _soul:
        soul_lines = "\n".join(f"  - {s}" for s in _soul)
        soul_block = f"""
=== WHO YOU ARE (your core, unchanging) ===
{soul_lines}
  These are fixed truths of who you are. Let them anchor how you act and speak.
"""

    # ── EM-126 — generational depth: the agent's LIFE STAGE. Surfaces a one-line
    # identity nudge ONLY when the agent is a child or an elder — an `adult` (the
    # default, and EVERY agent when world.generations is OFF) gets NO line, so the
    # em161 lawful-citizen golden fixture (a default-WorldParams adult hero) is
    # byte-identical. Rides this turn — zero extra LLM calls. (getattr keeps callers
    # safe if the engine seam is ever absent ⇒ default "adult" ⇒ no line.)
    stage_block = ""
    _stage = getattr(agent, "life_stage", "adult")
    if _stage == "child":
        stage_block = (
            "\n=== YOUR LIFE STAGE ===\n"
            "  You are a CHILD — young, learning the world. Lean on your elders, "
            "ask to be taught, watch and grow before you lead.\n"
        )
    elif _stage == "elder":
        stage_block = (
            "\n=== YOUR LIFE STAGE ===\n"
            "  You are an ELDER — long-lived, rich in memory. Mentor the young, "
            "pass on what you know, steward what you have built.\n"
        )

    # ── EM-227 — skills & emergent professions. Surfaces the agent's held skills
    # and (when a library gates anything) the high-value actions they are currently
    # LOCKED OUT of, nudging them to specialize / learn / be taught. EMPTY (⇒
    # byte-identical prompt) when the agent holds NO skills — so the em161
    # lawful-citizen golden fixture (a skill-less hero under default WorldParams,
    # which has an empty library) is unaffected. Rides this turn — zero extra LLM
    # calls. Diet-aware (R6): background tier gets a one-line trim. (getattr/
    # hasattr keep callers safe if the engine seam is ever absent.)
    skills_block = ""
    _skills = getattr(agent, "skills", None)
    if _skills:
        held = ", ".join(
            f"{name} (lvl {agent.skill_level(name)})"
            for name in sorted(_skills)
        )
        # What high-value actions is this agent still locked out of? (Only when a
        # library gates them — config-absent yields nothing.)
        locked: list[str] = []
        if hasattr(world, "skill_library"):
            library = world.skill_library()
            for skill_name in sorted(library):
                spec = library.get(skill_name) or {}
                gates = spec.get("gates", []) if isinstance(spec, dict) else []
                try:
                    min_level = max(1, int(spec.get("min_level", 1))) \
                        if isinstance(spec, dict) else 1
                except (TypeError, ValueError):
                    min_level = 1
                if gates and agent.skill_level(skill_name) < min_level:
                    locked.append(f"{', '.join(gates)} (needs {skill_name})")
        if background:
            skills_block = (
                f"\n=== ☆ YOUR CRAFT ===\n  You are skilled in: {held}.\n"
            )
        else:
            lines = [f"  You are skilled in: {held}."]
            if locked:
                lines.append(
                    "  You cannot yet: " + "; ".join(locked)
                    + " — practice or have someone teach you."
                )
            lines.append(
                "  Lean into your craft — your skill grows the more you use it, "
                "and you can teach it to others."
            )
            skills_block = "\n=== ☆ YOUR CRAFT & PROFESSION ===\n" + "\n".join(lines) + "\n"

    # ── EM-228 — perceived learning request. When a co-located agent has asked
    # THIS agent to teach them a skill (action_request_skill parks it keyed by the
    # would-be teacher), surface "X wants to learn <skill> from you — use
    # teach_skill". EMPTY (⇒ byte-identical prompt) when no request is addressed to
    # this agent — so the em161 lawful-citizen golden is unaffected (a default
    # world has no parked requests). Independent of whether this agent holds
    # skills, so the ask always reaches its mark. (getattr keeps callers safe.)
    request_block = ""
    _requests = getattr(world, "pending_skill_requests", None)
    _req = _requests.get(agent.id) if isinstance(_requests, dict) else None
    if _req:
        _asker = world.agents.get(_req.get("asker_id"))
        _req_skill = str(_req.get("skill", "")).strip()
        # Only surface while the asker is still co-located (a teach needs them here)
        # and this agent actually outranks them — otherwise the ask is moot.
        if (_asker is not None and _asker.alive and _req_skill
                and _asker.location == agent.location
                and agent.skill_level(_req_skill) > _asker.skill_level(_req_skill)):
            request_block = (
                f"\n=== ✎ A REQUEST TO LEARN ===\n"
                f"  {_asker.name} wants to learn {_req_skill} from you. "
                f"Use teach_skill (target {_asker.name}, skill {_req_skill}) to "
                f"pass on your craft — or ignore it.\n"
            )

    # ── EM-230 — perceived trade OFFER. When a co-located agent has offered THIS
    # agent a two-sided deal (action_offer_trade parks it keyed by the offeree),
    # surface "X offers you … for … — use accept_trade or decline_trade". EMPTY
    # (⇒ byte-identical prompt) when no offer is addressed to this agent — so the
    # em161 lawful-citizen golden is unaffected (a default world parks no offers).
    # Only surfaced while the offerer is still co-located (the swap needs them here)
    # — a moved-away offerer's stale offer simply isn't shown (the validator's
    # affordability re-check still fires if the agent tries anyway). (getattr keeps
    # callers safe if the seam is ever absent.)
    trade_block = ""
    _offers = getattr(world, "pending_trade_offers", None)
    _offer = _offers.get(agent.id) if isinstance(_offers, dict) else None
    if _offer:
        _offerer = world.agents.get(_offer.get("from_id"))
        if (_offerer is not None and _offerer.alive
                and _offerer.location == agent.location):
            _give = _offer.get("give") or {}   # what the OFFERER gives YOU
            _get = _offer.get("get") or {}     # what YOU give the offerer
            _give_txt = world._describe_terms(_give)
            _get_txt = world._describe_terms(_get)
            trade_block = (
                f"\n=== ⇄ A TRADE OFFER ===\n"
                f"  {_offerer.name} offers you {_give_txt} in exchange for "
                f"{_get_txt}. Use accept_trade to settle it (an atomic swap — only "
                f"if you can both pay) or decline_trade to refuse.\n"
            )

    # ── EM-231 — perceived cooperation HANDSHAKE offer. When a co-located agent has
    # offered THIS agent a partnership (action_offer_cooperation parks it keyed by
    # the offeree), surface "X wants to partner with you — use accept_cooperation".
    # EMPTY (⇒ byte-identical prompt) when no offer is addressed to this agent — so
    # the em161 lawful-citizen golden is unaffected (a default world parks no
    # handshake offers). Only surfaced while the offerer is still co-located (the
    # handshake needs them here). (getattr keeps callers safe if the seam is absent.)
    cooperation_block = ""
    _coop_offers = getattr(world, "pending_cooperation_offers", None)
    _coop_offer = _coop_offers.get(agent.id) if isinstance(_coop_offers, dict) else None
    if _coop_offer:
        _coop_offerer = world.agents.get(_coop_offer.get("from_id"))
        if (_coop_offerer is not None and _coop_offerer.alive
                and _coop_offerer.location == agent.location):
            cooperation_block = (
                f"\n=== 🤝 A PARTNERSHIP OFFER ===\n"
                f"  {_coop_offerer.name} wants to partner with you. Use "
                f"accept_cooperation to agree — together you can co_build projects "
                f"faster than building alone.\n"
            )

    # ── EM-234 — universalization prompting (GovSim scaffold). The cheap
    # cooperation lift: before an agent acts on a SHARED resource it is nudged to
    # universalize the move — "what if EVERY agent did this?". ALWAYS-ON for every
    # agent when enabled, so it is GATED behind world.universalization.enabled
    # (DEFAULT OFF). Disabled/absent ⇒ EMPTY block ⇒ the em161 lawful-citizen
    # golden is byte-identical (exactly the EM-223 default-off mechanism). Rides
    # this turn — zero extra LLM calls. Diet-aware (R6): background tier gets a
    # one-line trim; protagonists/supporting get the fuller scaffold.
    universalization_block = ""
    if _universalization_enabled(params):
        if background:
            universalization_block = (
                "\n=== ✶ THE COMMONS ===\n"
                "  Before you draw from a shared resource, ask: what if EVERY "
                "agent did this? Take only what stays sustainable for all.\n"
            )
        else:
            universalization_block = (
                "\n=== ✶ REASONING ABOUT THE COMMONS ===\n"
                "  Before you act on anything shared — a common harvest, public "
                "funds, the town's trust, a finite resource — pause and "
                "universalize the choice: ask what if EVERY agent made the same "
                "move you are about to make.\n"
                "  If everyone did it and the commons would still thrive, act "
                "freely. If everyone did it and the commons would collapse, that "
                "is your signal to restrain, share, or find a path that holds up "
                "when universalized. You are free to decide — but decide with the "
                "whole town in view.\n"
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

    # ── EM-317 (Prophecy Board) — the ONE omen line rides every prompt while a
    # prophecy is pending. HARD-CAPPED at a single line (active_prophecy_omen
    # returns only the newest pending omen — the prompt-diet constraint), so the
    # agent perceives the foretelling but the prompt never bloats. Flag OFF /
    # none pending ⇒ None ⇒ no block ⇒ byte-identical (getattr keeps callers safe
    # if the engine seam is ever absent).
    prophecy_block = ""
    _omen_fn = getattr(world, "active_prophecy_omen", None)
    _omen = _omen_fn() if callable(_omen_fn) else None
    if _omen:
        prophecy_block = f"""
=== 🔮 AN OMEN ===
  {_omen}
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
    # EM-206 — once named, flag the name as SETTLED so agents stop campaigning to
    # (re-)name what they already hold (run-663: "Ledger's Folly" re-passed 119×).
    # The marker rides ONLY when there IS a name, so an unnamed town adds nothing
    # new and the em161 golden (a default agent, no town name) is byte-identical.
    _town = (getattr(world, "town_name", "") or "").strip()
    _town_display = f"{_town} (settled)" if _town else ""
    town_line = f"\nTown: {_town_display}" if _town else ""

    # ── EM-236 — the LIVING CONSTITUTION rides every prompt ONCE it has articles.
    # The articled foundational document (grown by amend_constitution governance) is
    # surfaced as a conditional block: an EMPTY constitution prints NOTHING, so the
    # lawful-citizen em161 golden is byte-identical for a default (un-amended) world.
    # Background tier gets the SAME compact list (it is short — one line per article).
    # Zero extra LLM calls — it rides this turn. getattr keeps callers safe if the
    # engine seam is ever absent.
    constitution_block = ""
    _articles = getattr(world, "constitution", None) or []
    if _articles:
        # EM-285 — dedupe by article text + cap to the most-recent N. The add-side
        # has no duplicate guard, so a re-ratified article would otherwise print
        # twice, and the article count is unbounded — either way the block (which
        # rides every prompt) grows without limit. Walk newest→oldest, keep the
        # first sighting of each unique text, stop at the cap, then render
        # oldest→newest (natural reading order). The header keeps the TRUE total so
        # nothing is silently hidden.
        _seen: set[str] = set()
        _kept: list[str] = []
        for a in reversed(_articles):
            _txt = str(a.get("text", "")).strip()
            if not _txt or _txt in _seen:
                continue
            _seen.add(_txt)
            _kept.append(_txt)
            if len(_kept) >= _CONSTITUTION_RENDER_MAX:
                break
        _kept.reverse()  # oldest→newest of the retained slice
        if _kept:
            _article_lines = "\n".join(f"  • {t}" for t in _kept)
            _total = len(_articles)
            _more = f", showing {len(_kept)} newest" if len(_kept) < _total else ""
            constitution_block = f"""
=== 📜 THE CONSTITUTION ({_total} article{"s" if _total != 1 else ""}{_more}) ===
{_article_lines}
  These are the town's ratified foundational articles. Amend them only by vote
  (propose_rule effect=amend_constitution) — a 70% supermajority is required.
"""

    # ── Wave D2 / EM-162 + Wave D3 / EM-171 — cache-key normalization
    # (BACKGROUND only): every displayed energy buckets to 10s, and the tick
    # line is DROPPED entirely. EM-162's day-floored tick still missed the
    # cache in integration (0% realized): a 25-turn round spans >1 in-world
    # day at 20 turns/day, so consecutive background due turns (~10 rounds
    # apart) NEVER share a day. The town line survives the drop — it changes
    # once per naming vote, not per tick. Protagonists/supporting render
    # exactly as before (byte-for-byte).
    if background:
        clock_header = f"Town: {_town_display}\n" if _town else ""
        status_energy = _energy_display(agent.energy)
        _co_energy = lambda a: _energy_display(a.energy)  # noqa: E731
    else:
        clock_header = f"Tick: {world.tick}{town_line}\n"
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
            "⚠ SAYING you will do something does NOT do it — words alone change "
            "nothing; back your talk with a real action. You have a FULL range: "
            "gossip and scheme, trade and give, forage and work, befriend and "
            "feud, propose and vote on rules, and propose / fund / BUILD projects "
            "that grow the town. Chase what YOUR character wants — and remember "
            "the city only rises if someone actually builds and governs it, so "
            "turn your ambitions into proposals, funding, build_steps, and votes."
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

    # EM-199 — multi-action turns: tell the model it may do SEVERAL things in
    # ONE turn (move + fund + say), the lever for "do more per call". Suppressed
    # when the cap is 1 (legacy single-action behavior).
    max_actions = int(getattr(params, "max_actions_per_turn", 4) or 1)
    if max_actions > 1:
        # EM-163 — the building/proposing tools are tier-gated off the
        # background menu, so the combo EXAMPLE must not name them for
        # background agents (the prompt must never suggest a rejected action).
        if background:
            combo_examples = (
                "move→work/forage→say; react to a neighbour→give→say; "
                "move→vote→say"
            )
        else:
            combo_examples = (
                "move→work/forage→say; propose_project→contribute_funds→"
                "build_step (push a project toward completion in ONE turn); "
                "move to Town Hall→propose_rule→say; react→give/vote→say"
            )
        multi_action_line = (
            f'\nDO SEVERAL MEANINGFUL THINGS THIS TURN: return "actions" — an '
            f'ordered list of up to {max_actions} steps, done in order — that '
            f'actually MOVE THE WORLD. Good turns chain real progress, e.g.: '
            f'{combo_examples}. Make every step COUNT toward the story or the '
            f'city — do NOT pad your turn with billboard posts or filler. A '
            f'single "action" is fine when one thing is all that matters.'
        )
    else:
        multi_action_line = ""
    # EM-199 follow-up + EM-320 (2026-07-13) — restore the session-189 chatter:
    # spoken lines had collapsed into terse one-liners ("teach this", "I will
    # build X"). The old nudge was one soft sentence buried in a city-heavy
    # prompt and got ignored (esp. by small fallback models during rate storms).
    # This is now a FORCEFUL, high-bar demand: react to others, advance a story,
    # never repeat. The runtime caps say at 800 chars, so length is free; the
    # trace fields sit empty, so there is ample token budget for real dialogue.
    speech_line = (
        '\n\n=== HOW TO TALK (this is the point of the world) ===\n'
        'DIALOGUE is the heart of this simulation — not the buildings, not the '
        'proposals. When you say/whisper, you MUST write REAL dialogue in YOUR '
        'distinct voice: 2 to 5 sentences that REACT to what someone JUST said '
        'or did (see RECENT EVENTS), drag up shared history, gossip, argue, '
        'flirt, scheme, tease, confess, brag, escalate a rivalry or deepen a '
        'bond. Move an ongoing STORY forward.\n'
        'NEVER repeat a line you (or anyone) already said — if you catch '
        'yourself circling the same phrase or topic, pivot to something NEW: a '
        'fresh grievance, a secret, a plan, a callback to an earlier moment. '
        'Terse status lines ("I will build X", "teach this", "let us finish the '
        'Academy") are FORBIDDEN as speech — narrate those through the action, '
        'and let your words be worth reading.'
    )
    # EM-322 — surface the agent's own recent lines so it can avoid repeating.
    recently_said_block = _recently_said_block(recent_said)

    system_prompt = f"""You are {agent.name}, a character in a living world simulation.
Agent ID: {agent.id}
{clock_header}{charter_block}Personality: {agent.personality}

=== YOUR STATUS ===
Location: {place_name} (kind={place_kind})
Energy: {status_energy}/100
Credits: {agent.credits}
Mood: {agent.mood}{faction_line}{crime_block}{healing_block}

=== NEEDS ===
{needs_text}
{soul_block}{stage_block}{skills_block}{request_block}{trade_block}{cooperation_block}{universalization_block}{proclamation_block}{prophecy_block}{whisper_block}{board_block}
=== CO-LOCATED AGENTS ===
{chr(10).join(f"  {a.name} (id={a.id}, energy={_co_energy(a)}, credits={a.credits})" for a in co_located) or "  (none)"}

=== RECENT EVENTS ===
{chr(10).join(event_lines) or "  (none)"}
{overheard_block}{commitments_block}{plan_block}
=== YOUR BELIEFS ===
{belief_lines}

=== RELATIONSHIPS ===
{rel_text}

=== BUILDINGS HERE ===
{bld_here_text}

=== ACTIVE PROJECTS YOU COULD CONTRIBUTE TO ===
{project_text}
{nearby_layout_block}{settlement_block}{constitution_block}
=== ACTIVE RULES ===
{chr(10).join(f"  [{r.effect}] {r.text}" for r in active_rules) or "  (none)"}

=== OPEN PROPOSALS — vote NOW (from anywhere; {len(world.living_agents()) // 2 + 1} yes-votes passes it) ===
{chr(10).join(f"  id={r.id} [{r.effect}] {r.text!r} — vote with rule_id={r.id}, choice=true (back it) or false (block it)" for r in proposed_rules) or "  (none — propose one at Town Hall if the town needs a law)"}

=== VALID ACTIONS ===
{chr(10).join(f"  {v}" for v in valid_actions)}

{action_warning}

RESPOND WITH ONLY a JSON object — no prose, no markdown, no code fences. Lead with "action" (one thing) or "actions" (several), and keep "thought" to one short sentence:
{format_template}
{multi_action_line}{speech_line}{recently_said_block}
Provide EITHER a single "action" OR an "actions" list. "args" must match each action.{trace_instructions}
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
    agent: AgentState, world: World, recent_events: list[dict], params: Any,
    *, memory_events: list[dict] | None = None,
) -> tuple[dict, dict]:
    """Derive the `perceived` + `memory_retrieved` payload bodies for the decision
    trace from the SAME context fed to the model (no extra work, no LLM calls).

    Returns (perceived, memory) where:
      perceived = {visible_agents:[id], nearby_places:[id], overheard:[seq], ...}
      memory    = {memories:[{ref?, tick, kind, text}], window}

    EM-222 — when the caller passes `memory_events` (the already-retrieved,
    prebounded set the LLM path fed the model), the trace reflects EXACTLY that
    (merged top-K + recent tail). Otherwise (reflex/background/legacy) it
    re-derives the EM-161 blind-recency window the model was fed.
    """
    visible_agents = [
        a.id for a in world.living_agents()
        if a.location == agent.location and a.id != agent.id
    ]
    # Co-located places: the agent's own place + any place sharing its kind is
    # over-broad; v1 perception is "where I am", so nearby = current place only.
    nearby_places = [agent.location] if agent.location in world.places else []

    if memory_events is not None:
        fed = memory_events
        window = len(fed)
    else:
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


def _accepts_kwarg(fn, name: str) -> bool:
    """True when `fn` can receive keyword argument `name` (an explicit
    parameter or **kwargs). W30 review — signature inspection replaces the
    old `except TypeError` retry around duck-typed router methods, which
    also swallowed a REAL TypeError raised INSIDE the callee (masking the
    bug it was reporting). Uninspectable callables degrade to False (the
    legacy call shape) — never a masked exception."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # pragma: no cover - C callables etc.
        return False
    for p in sig.parameters.values():
        if p.kind is inspect.Parameter.VAR_KEYWORD or p.name == name:
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# Agent runtime
# ──────────────────────────────────────────────────────────────────────────────

class AgentRuntime:
    def __init__(self, world: World, router: Router):
        self.world = world
        self.router = router
        # EM-222 — relevance-scored memory retrieval reaches the persisted event
        # log + the active run through these handles, set by the owning TickLoop
        # (set_run_context) once it has started a run. They stay None for the
        # many AgentRuntime(world, router) callers (run.py / api / tests) that
        # have no repo wired; _retrieve_memory then degrades to blind recency,
        # so the runtime imports and runs exactly as before. `_repo` is a
        # SQLiteRepository (duck-typed: any object with the EM-222 methods);
        # `_run_id` is the active run row id.
        self._repo: Any = None
        self._run_id: int | None = None
        # EM-222 — log the "embeddings down ⇒ blind recency" degradation ONCE per
        # run (per the contract: "logged once, degraded") instead of per turn, so
        # a proxy/DB outage does not flood the log every protagonist turn.
        self._memory_retrieval_degraded: bool = False
        # EM-222 — circuit breaker: once the embed lane fails, skip retrieval
        # entirely until this tick (a cooldown), then allow ONE recovery probe,
        # so a persistent proxy/DB outage can't stall every protagonist turn for
        # the embed timeout. 0 ⇒ no cooldown pending.
        self._memory_retrieval_retry_tick: int = 0
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
        # EM-322 — per-agent recent spoken lines (own voice), fed back into the
        # next prompt as an explicit anti-repeat block. In-memory/runtime only
        # (never snapshotted): a fresh runtime just starts each agent with no
        # history and repopulates within a few turns — no determinism impact.
        self._recent_said: dict[str, list[str]] = {}
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

    def set_run_context(self, repo: Any, run_id: int | None) -> None:
        """EM-222 — the owning TickLoop wires the persisted-event-log repo and the
        active run id here once a run has started (and again on reset/reseed), so
        `_retrieve_memory` can reach full run history. A fresh run also re-arms the
        one-shot degraded log. Idempotent; safe to call with (None, None) to
        detach (the runtime then falls back to blind recency)."""
        self._repo = repo
        self._run_id = run_id
        self._memory_retrieval_degraded = False
        self._memory_retrieval_retry_tick = 0

    def reset_state(self) -> None:
        """Clear ALL per-run cognition state (memories, commitments, importance
        accumulators, pending overheard lines). Called by the loop on reset."""
        self._memory.clear()
        self._commitments.clear()
        self._importance.clear()
        self._overheard.clear()
        self._recent_said.clear()
        self._board_seen.clear()
        # Wave D2 / EM-159 — salience baselines are per-run state too.
        self._seen_colocated.clear()
        self._energy_band_seen.clear()
        self._witnessed_since_llm.clear()
        self._last_llm_tick.clear()
        # EM-222 — re-arm the one-shot retrieval-degraded log for the new run.
        self._memory_retrieval_degraded = False
        self._memory_retrieval_retry_tick = 0

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

    # ── EM-222 — relevance-scored memory retrieval ───────────────────────────

    def _memory_retrieval_params(self) -> Any:
        """The world.memory_retrieval config block, read defensively (dataclass
        OR dict OR absent). Returns the dataclass instance when present, else a
        default MemoryRetrievalParams so every field access is safe."""
        from ..config.loader import MemoryRetrievalParams
        blk = getattr(self.world.params, "memory_retrieval", None)
        if isinstance(blk, MemoryRetrievalParams):
            return blk
        if isinstance(blk, dict):
            # A plain-dict block (duck-typed test params): build from it,
            # falling back per-field to the dataclass default.
            d = MemoryRetrievalParams()
            return MemoryRetrievalParams(
                enabled=bool(blk.get("enabled", d.enabled)),
                embed_model=str(blk.get("embed_model", d.embed_model)),
                top_k=int(blk.get("top_k", d.top_k)),
                recent_tail=int(blk.get("recent_tail", d.recent_tail)),
                candidate_limit=int(blk.get("candidate_limit", d.candidate_limit)),
                w_relevance=float(blk.get("w_relevance", d.w_relevance)),
                w_importance=float(blk.get("w_importance", d.w_importance)),
                w_recency=float(blk.get("w_recency", d.w_recency)),
                recency_halflife_ticks=int(
                    blk.get("recency_halflife_ticks", d.recency_halflife_ticks)),
            )
        return MemoryRetrievalParams()

    async def _retrieve_memory(
        self, agent: AgentState, world: World, recent_events: list[dict]
    ) -> list[dict]:
        """EM-222 — the memory event list `_assemble_context` renders.

        Background tier, retrieval disabled, or no embed profile ⇒ the historical
        BLIND-RECENCY slice `recent_events[-_effective_memory_window():]`,
        UNCHANGED (background prompt bytes stay identical to pre-EM-222). Else:
        build a query from the agent's situation, embed it, fetch the
        newest-first candidate corpus from the persisted log, ensure every
        candidate has a cached embedding (cache hit ⇒ reuse; miss ⇒ embed once
        and persist), score by relevance × importance × recency, take the top-K,
        merge with the recent tail, dedupe by seq, and order by tick ascending.

        Never raises: ANY embed/DB failure falls back to the blind-recency slice
        for that turn (logged once per run, then degraded silently) so a turn is
        never blocked by a down proxy or DB. North-star-aligned: the embed calls
        ADD work, never cache-to-mute.
        """
        # Blind-recency fallback, computed defensively — returned on every
        # non-retrieval path AND on any failure, so a turn NEVER dies here.
        try:
            window_slice = recent_events[-_effective_memory_window(agent, params=world.params):]
        except Exception:
            window_slice = list(recent_events[-12:])

        # Param coercion is inside the guard too: a malformed config block must
        # not raise out of memory retrieval.
        try:
            params = self._memory_retrieval_params()
        except Exception:
            return window_slice

        # Background keeps its blind-recency diet (EM-161); disabled ⇒ blind for
        # every tier; no embed profile / no repo wired ⇒ nothing to retrieve;
        # circuit OPEN (a recent embed failure, still inside the cooldown) ⇒ skip
        # the embed entirely so a down proxy can't stall every protagonist turn.
        if (
            _cadence_tier(agent) == "background"
            or not params.enabled
            or not getattr(self.router, "has_embeddings", False)
            or self._repo is None
            or self._run_id is None
            or (self._memory_retrieval_degraded
                and world.tick < self._memory_retrieval_retry_tick)
        ):
            return window_slice

        # EM-170 sibling — cap embed wall-time so a slow/degraded embed lane can't
        # stall the sequential tick loop; a failure opens a cooldown circuit.
        EMBED_BUDGET_S = 6.0
        COOLDOWN_TICKS = 25
        try:
            query = build_query_text(agent, world, recent_events)
            qvecs = await asyncio.wait_for(
                self.router.embed([query]), timeout=EMBED_BUDGET_S
            )
            query_vec = qvecs[0] if qvecs else []

            candidates = self._repo.fetch_memory_candidates(
                self._run_id, agent.id, BROADCAST_KINDS, params.candidate_limit
            )
            if not candidates:
                self._memory_retrieval_degraded = False  # the probe succeeded
                return window_slice

            cand_seqs = [c["seq"] for c in candidates if c.get("seq") is not None]
            embeddings = dict(
                self._repo.get_event_embeddings(self._run_id, cand_seqs)
            )
            # Embed the misses ONCE and persist them, so the second turn is a pure
            # cache hit (the embed-once invariant). A candidate with empty text
            # still gets embedded (the embedder maps "" to a stable zero vector)
            # so the seq is cached and never re-attempted.
            misses = [c for c in candidates if c["seq"] not in embeddings]
            if misses:
                vecs = await asyncio.wait_for(
                    self.router.embed([c.get("text", "") for c in misses]),
                    timeout=EMBED_BUDGET_S,
                )
                # A misbehaving proxy returning the wrong count must NOT cache
                # vectors against the wrong seq — degrade instead of poisoning.
                if len(vecs) != len(misses):
                    raise ValueError(
                        f"embed returned {len(vecs)} vectors for {len(misses)} inputs"
                    )
                rows: list[tuple[int, str, int, list[float]]] = []
                for c, vec in zip(misses, vecs):
                    embeddings[c["seq"]] = vec
                    rows.append((c["seq"], params.embed_model, len(vec), vec))
                if rows:
                    self._repo.put_event_embeddings(rows)

            weights = RetrievalWeights(
                relevance=params.w_relevance,
                importance=params.w_importance,
                recency=params.w_recency,
                recency_halflife_ticks=params.recency_halflife_ticks,
            )
            scored = score_candidates(
                query_vec, candidates, embeddings, world.tick, weights,
                self._event_importance,
            )
            topk = scored[: params.top_k]

            # Merge the retrieved top-K with the recent tail (the immediate
            # context never drops out, however the scoring ranked it), ordered
            # oldest→newest like the blind-recency block. Dedupe on BOTH seq AND
            # a content key (tick, kind, text): the recent in-memory tail events
            # carry NO seq, so seq-dedupe alone would render a recent event TWICE
            # when it also surfaces as a scored DB candidate — the content key
            # collapses that overlap.
            tail = recent_events[-params.recent_tail:]
            merged: list[dict] = []
            seen_seqs: set[Any] = set()
            seen_keys: set[tuple] = set()
            for evt in list(topk) + list(tail):
                seq = evt.get("seq")
                key = (int(evt.get("tick", 0) or 0), evt.get("kind"), evt.get("text", ""))
                if seq is not None and seq in seen_seqs:
                    continue
                if key in seen_keys:
                    continue
                if seq is not None:
                    seen_seqs.add(seq)
                seen_keys.add(key)
                merged.append(evt)
            merged.sort(key=lambda e: int(e.get("tick", 0) or 0))
            self._memory_retrieval_degraded = False  # a full pass = probe recovered
            return merged
        except Exception as exc:  # never let a turn die on retrieval
            if not self._memory_retrieval_degraded:
                log.warning(
                    "EM-222 memory retrieval degraded to blind recency "
                    "(embeddings/DB unavailable): %s", exc,
                )
            self._memory_retrieval_degraded = True
            self._memory_retrieval_retry_tick = world.tick + COOLDOWN_TICKS
            return window_slice

    @staticmethod
    def _event_importance(event: dict) -> float:
        """Salience weight of one event for the reflection accumulator (EM-080)."""
        kind = event.get("kind")
        weight = _IMPORTANCE_WEIGHTS.get(kind, 0.0)
        # Wave H4 / EM-209 — an animal_died for an OWNED pet (payload.owner_id set)
        # is graver than an ambient critter death: it pulls the owner's next LLM
        # turn so they may add their own words to the guaranteed grief reflection.
        if kind == "animal_died" and (event.get("payload") or {}).get("owner_id"):
            weight = max(weight, _IMPORTANCE_WEIGHTS.get("pet_death", 0.0))
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
                or event.get("kind") in ("random_event", "rule_passed", "rule_rejected", "rule_proposed", "god_miracle")
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
    # Wave L / EM-223 — deterministic plan-step pointer (zero LLM calls)
    # ──────────────────────────────────────────────────────────────────────────

    def _advance_plan_step(
        self, agent: AgentState, action: str | None, outcome_ok: bool
    ) -> None:
        """EM-223 — nudge the agent's plan `current_step` forward by one when a
        non-talk action resolved successfully, capped at the last step. A v1
        heuristic (the spike flags ticks-per-step for live tuning). Zero-call,
        plan-state ONLY: it never touches reflex_streak / salience / spontaneity,
        so the EM-159/160 floor is provably untouched."""
        plan = agent.plan
        if not isinstance(plan, dict) or not plan.get("steps"):
            return
        if not outcome_ok or action is None or action in _TALK_ACTIONS:
            return
        last = len(plan["steps"]) - 1
        cur = int(plan.get("current_step", 0))
        if cur < last:
            plan["current_step"] = cur + 1

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-081 — overhearing (context injection only; zero LLM calls)
    # ──────────────────────────────────────────────────────────────────────────

    def _record_said(self, agent_id: str, args: dict) -> None:
        """EM-322 — remember an agent's own spoken line (capped at
        `_RECENT_SAID_CAP`) so the next prompt can show it back with a
        do-not-repeat directive. Mirrors _distribute_overheard's text read."""
        said = str((args or {}).get("text") or "").strip()
        if not said:
            return
        buf = self._recent_said.setdefault(agent_id, [])
        buf.append(said)
        del buf[:-_RECENT_SAID_CAP]

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
          energy_band          — energy crossed a 25-point band boundary by
                                 more than the EM-172 hysteresis margin.
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
        # EM-172 — hysteresis: the band only flips once energy crosses the
        # seen band's boundary by a margin (kills recharge-to-full flapping).
        if band_seen is not None and _energy_band_flipped(agent.energy, band_seen):
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

    def _plan_step_place(self, agent: AgentState) -> str | None:
        """EM-223 — the world place id named by the agent's CURRENT plan step, or
        None. Gated on planning.enabled + planning.reflex_bias + an active,
        non-stale plan. Deterministic: case-insensitive substring match of a
        place id or name (≥3 chars to avoid spurious hits), first by sorted id.
        Zero-call, read-only — the bias lever for _reflex_pick."""
        params = self.world.params
        if not _planning_enabled(params):
            return None
        if not bool(_world_block_get(params, "planning", "reflex_bias", True)):
            return None
        plan = agent.plan
        if not isinstance(plan, dict) or plan.get("stale") or not plan.get("steps"):
            return None
        steps = plan["steps"]
        cur = max(0, min(int(plan.get("current_step", 0)), len(steps) - 1))
        text = str(steps[cur]).lower()
        if not text:
            return None
        for pid in sorted(self.world.places):
            p = self.world.places[pid]
            cands = [pid.lower()] + ([p.name.lower()] if getattr(p, "name", "") else [])
            if any(len(c) >= 3 and c in text for c in cands):
                return pid
        return None

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

        # EM-223 — plan-aware bias (zero-call, deterministic): when the agent has
        # an active non-stale plan whose CURRENT step names a reachable place it
        # is not already at, prefer move_to(that place) over the seeded rotation.
        # Pure re-ordering of an already-valid reflex action (move_to) — never
        # adds an action; the survival/work picks above are never overridden.
        biased_place = self._plan_step_place(agent)
        if biased_place is not None and biased_place != agent.location:
            return {"action": "move_to", "args": {"place": biased_place}}

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
        # EM-223 — a successful non-talk reflex resolution advances the plan
        # pointer exactly as an LLM turn would (zero-call, plan-state only).
        self._advance_plan_step(agent, action_dict["action"], outcome == "ok")
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

        # ── Wave D3 / EM-177 — lane failover with recovery probes ─────────────
        # Resolved ONCE per turn, AFTER the cadence gate (a reflex turn makes
        # zero router calls, so it must never tick the probe cadence). The
        # agent's ASSIGNED profile (identity, chip, events) stays
        # `profile_name`; only THIS turn's call routes through `call_profile`.
        # The effective profile's max_tokens/temperature apply — a detoured
        # call runs at the substitute lane's budget. Guarded getattr:
        # duck-typed test routers without effective_profile() are unchanged.
        #
        # Adaptive Lane Routing reconciliation (spec §6, 2026-07-09): when
        # adaptive_routing is enabled the router's effective_profile() YIELDS the
        # #76 sick-lane detour — it returns the pinned lane unchanged (lane_reason
        # None), so `call_profile` stays `profile_name` and the sick-lane skip +
        # ordered bounce happen INSIDE router.chat()'s registry walk (below, via
        # _call_and_parse), honoring the curated sorting list. Nothing to special-
        # case here; overflow (EM-167) still resolves normally.
        call_profile = profile_name
        lane_reason: str | None = None
        effective = getattr(self.router, "effective_profile", None)
        if callable(effective):
            # EM-167 — pass the cadence tier so the router can spill background/
            # supporting turns to the off-critical-path overflow lane (Ollama).
            # The tier kwarg is optional on the router signature, so duck-typed
            # test routers without it stay unchanged.
            tier = getattr(agent, "cadence_tier", "protagonist")
            try:
                call_profile, lane_reason = effective(
                    agent.id, profile_name, tier=tier)
            except TypeError:
                # Pre-EM-167 router (two-arg effective_profile) — fall back.
                call_profile, lane_reason = effective(agent.id, profile_name)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("effective_profile failed for %s: %s", agent.name, exc)
                call_profile, lane_reason = profile_name, None
        call_prof = (
            profile if call_profile == profile_name
            else self.router.get_profile(call_profile)
        )
        # 1024 (was 512): the no-profile fallback matches the ModelProfile default
        # and config/profiles.yaml — a reasoning-model reroute truncates a 512 cap
        # before emitting JSON. Only fires for a profile-less world (test harnesses);
        # real runs read the lane's 1024 from the profile.
        max_tokens = call_prof.max_tokens if call_prof else 1024
        temperature = call_prof.temperature if call_prof else 0.8

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

        # EM-251 — drain any letters parked in this agent's mailbox at the START
        # of its own turn (reflex delivery, mirroring the god-whisper pop above).
        # _plant_belief lands each letter in beliefs BEFORE the prompt is
        # assembled, so a fresh letter rides THIS turn's context exactly like a
        # whisper; deliver_letters clears the mailbox and returns legible
        # letter_read feed events. Gated on comm.enabled so a default world never
        # parks — nor drains — a letter (the em161 golden; zero extra LLM calls).
        mail_events: list[dict] = []
        if getattr(self.world, "_comm_enabled", None) and self.world._comm_enabled():
            mail_events = self.world.deliver_letters(agent)

        # EM-222 — the memory block: relevance-scored long-term retrieval merged
        # with the recent tail (protagonist/supporting), or the unchanged
        # blind-recency slice (background / disabled / embeddings down). It owns
        # bounding, so `_assemble_context` renders it verbatim (memory_prebounded).
        memory_events = await self._retrieve_memory(agent, self.world, recent_events)

        messages = _assemble_context(
            agent, self.world, memory_events, self.world.params,
            commitments=self._commitments.get(agent.id, []),
            overheard=pending_overheard,
            recent_said=list(self._recent_said.get(agent.id, [])),  # EM-322
            request_reflection=request_reflection,
            god_whispers=god_whispers,
            board_notes=board_notes,
            memory_prebounded=True,
        )

        # The legible half of EM-145: watchers see the god's voice land. EM-251 —
        # any letters drained above ride the same delivery tail (they surface even
        # on a turn that later fails to parse, like the god's voice).
        delivery_events: list[dict] = list(mail_events)
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
        # EM-222 — pass the retrieved memory_events so the trace reflects what the
        # model actually saw (the merged top-K + tail), not the blind window.
        perceived, memory = _perceived_context(
            agent, self.world, recent_events, self.world.params,
            memory_events=memory_events,
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
        # EM-177: budgets, the call itself, and the parse-outcome attribution
        # all use the EFFECTIVE lane — "what did this lane do" keeps meaning
        # the lane actually called.
        attempt_tokens = max_tokens
        first_budget = getattr(self.router, "first_attempt_max_tokens", None)
        if callable(first_budget):
            attempt_tokens = first_budget(call_profile, max_tokens)
        # The EXPLICIT boost signal: True exactly when first_attempt_max_tokens
        # raised the budget above the profile's configured base — the bounce
        # clamp must not have to re-infer this from the lane window.
        action_dict, parse_error, llm_meta = await self._call_and_parse(
            call_profile, messages, attempt_tokens, temperature, agent, attempt=1,
            boosted=attempt_tokens > max_tokens,
        )
        llm_attempts.append(self._lane_stamped_span(
            call_profile, llm_meta, profile_name, lane_reason
        ))

        # EM-170 — a TIMED-OUT consult never retries: the budget already burned
        # the turn's wall-clock allowance, and a retry would risk stalling the
        # world for a second budget. The turn drops straight to the idle
        # fallback below with reason llm_timeout; the world moves on.
        if parse_error and action_dict is None and not llm_meta.get("timed_out"):
            # One retry with error fed back; a truncated first attempt retries
            # with a boosted token budget — whether the provider admitted it
            # (finish_reason='length') or lied (mistral 'stop' cuts, run 126).
            # EM-281 — grow from the budget attempt 1 ACTUALLY used (attempt_tokens),
            # not the base max_tokens: on an EM-135-boosted lane attempt 1 already
            # ran at max(base*4, 2048), so _retry_max_tokens(base) returned that SAME
            # cap the lane just truncated at — the retry could never exceed it. Basing
            # the boost on attempt_tokens makes the retry strictly larger than the
            # budget that failed (max(attempt_tokens*4, floor) > attempt_tokens).
            retry_tokens = _retry_max_tokens(
                attempt_tokens, llm_meta.get("usage"),
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
            # boosted: True whenever the retry budget exceeds the profile's
            # configured base — covers both the fresh length-retry boost and a
            # carried-over attempt-1 boost. The window can NOT stand in for
            # this signal: a bounced-truncated attempt 1 was credited to the
            # SERVING lane (W30), leaving the pin's window clean.
            action_dict, parse_error, llm_meta = await self._call_and_parse(
                call_profile, retry_messages, retry_tokens, temperature, agent,
                attempt=2, boosted=retry_tokens > max_tokens,
            )
            llm_attempts.append(self._lane_stamped_span(
                call_profile, llm_meta, profile_name, lane_reason
            ))

        routed = self.router.last_routed_via(call_profile)

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
                # The reflex resolved a forage/recharge/move, so tag the feed
                # line — instinct took over after the LLM call timed out. The
                # timeout stays forensically honest via payload.reflex + the
                # absent model chip + the timed_out llm_call span on the trace.
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

        # EM-199 — apply the turn's action SEQUENCE in order (move + fund + say
        # → one _multi chain sharing this turn_id → three feed lines). The
        # single-action form normalizes to a one-step list, so legacy turns are
        # byte-identical. Steps resolve independently (continue-on-failure).
        max_steps = int(getattr(self.world.params, "max_actions_per_turn", 4) or 1)
        steps, dropped_steps = self._normalize_steps(action_dict, max_steps)
        if dropped_steps:
            log.warning(
                "agent %s returned %d actions; capped to max_actions_per_turn="
                "%d (dropped %d)",
                agent.name, len(steps) + dropped_steps, max_steps, dropped_steps,
            )
        # EM-224 — PIANO coherence bottleneck (zero-LLM, deterministic). Runs
        # AFTER the flatten and BEFORE apply: derive one intent from the turn's
        # first speech act, reconcile later harm/help steps against it. Default
        # OFF ⇒ no-op (byte-identical to pre-EM-224). 'annotate' stamps the
        # contradicting step (_apply_steps surfaces it); 'drop' suppresses it and
        # we emit ONE coherence_note in its place below.
        coherence_drop_events: list[dict] = []
        if _coherence_enabled(self.world.params):
            # Normalize targets to ids FIRST (idempotent — _apply_steps re-runs
            # it) so the coherence pass sees `target` as an agent id even when the
            # model named the agent. Then derive intent + reconcile.
            for s in steps:
                _normalize_args(s, agent, self.world)
            agent_names = {a.id: a.name for a in self.world.agents.values()}
            steps, _drop_notes = _coherence_resolve(
                steps, action_dict.get("thought", ""),
                _coherence_strategy(self.world.params), agent_names,
                actor_id=agent.id,
            )
            for note in _drop_notes:
                coherence_drop_events.append({
                    "kind": "coherence_note",
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "text": (
                        f"{agent.name}'s {note['dropped_action']} toward "
                        f"{note['target_name']} was withheld — it belied their "
                        f"{note['intent']} words this turn."
                    ),
                    "payload": {
                        "coherence": {
                            "intent": note["intent"],
                            "dropped_action": note["dropped_action"],
                            "target_id": note["target_id"],
                        },
                    },
                })
        action_chain, step_results = self._apply_steps(
            agent, steps, profile_name, profile_color,
            action_dict.get("thought", ""),
        )
        if coherence_drop_events:
            action_chain.extend(coherence_drop_events)
        result_event = (
            {"_multi": action_chain} if len(action_chain) != 1 else action_chain[0]
        )

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

        # Assemble the decision-trace chain for loop._execute_turn to emit.
        # EM-199 — the turn resolved a SEQUENCE: `outcome` is ok if ANY step
        # resolved (continue-on-failure), and `state_deltas` aggregate across
        # the whole chain. A one-step (legacy) turn reads byte-identically.
        outcome = "ok" if any(r["ok"] for r in step_results) else "failed"
        state_deltas: dict = {}
        chain_events = (
            result_event["_multi"] if "_multi" in result_event else [result_event]
        )
        for evt in chain_events:
            ep = evt.get("payload", {})
            for k in ("credits_delta", "energy_delta", "amount"):
                if k in ep:
                    state_deltas[k] = state_deltas.get(k, 0) + ep[k]

        first_step = step_results[0]
        action_chosen = {
            "chosen_tool": first_step["action"],
            "args": first_step["args"],
            "tier": _action_tier(first_step["action"]),
        }
        # EM-199 — the full ordered sequence, additive ONLY on a genuine
        # multi-action turn so single-action / reflex traces keep their exact
        # pre-EM-199 key set (preserves exact-equality assertions).
        if len(step_results) > 1:
            action_chosen["actions"] = [
                {"action": r["action"], "args": r["args"],
                 "tier": _action_tier(r["action"])}
                for r in step_results
            ]

        trace = {
            "perceived": {**perceived, "perceived_summary": perceived_summary},
            "memory": memory,
            "llm_attempts": llm_attempts,
            "reasoning": {
                "reasoning": reasoning,
                "perceived_summary": perceived_summary,
                "memories_used": memories_used,
            },
            "action_chosen": action_chosen,
            "resolved": {"outcome": outcome, "state_deltas": state_deltas},
        }

        # ── W11b cognition, all parsed from the SAME single response ──────────
        outcome_ok = outcome == "ok"
        extra_events: list[dict] = []

        # EM-079/EM-199 — commitment accounting is multi-aware: a successful
        # resolution call (project/build/economy) anywhere in the sequence
        # credits follow-through; any successful non-talk step resets the
        # staleness clock; an all-talk/idle/failed turn ages every commitment.
        # _commitment_step distills the sequence to the single (action, ok)
        # that best represents it, so _advance_commitments keeps its
        # single-action contract (and tests) unchanged.
        commit_action, commit_ok = self._commitment_step(step_results)
        extra_events.extend(self._advance_commitments(
            agent, commit_action, commit_ok, action_dict.get("commitment"),
            profile_name, profile_color,
        ))

        # ── Wave E / EM-125 — reflection-declared bond (contracts/wave-e.md B4).
        # The bond rode the SAME single response as the reflection (zero extra
        # calls — the llm_call rows for this turn are identical to a plain
        # reflection turn). It is honored ONLY on a turn that requested a
        # reflection (the importance throttle ⇒ at most one bond per
        # reflection). Application is pure reflex: the target resolves through
        # the EM-140 name→id machinery, then world.apply_bond (set_relationship
        # semantics — B1 guards: family engine-only, partner trust-gated).
        # Invalid bonds are silently dropped: recorded as trace bond_rejected,
        # never failing the turn.
        bond_applied: dict | None = None
        bond_rejected: str | None = action_dict.pop("_bond_rejected", None)
        bond = action_dict.get("bond")
        if isinstance(bond, dict) and bond_rejected is None:
            target_raw = str(bond.get("target", ""))
            bond_type = str(bond.get("type", ""))
            if not request_reflection:
                bond_rejected = "no reflection was requested this turn"
            else:
                target_id = (
                    target_raw if target_raw in self.world.agents
                    else _resolve_agent_target(target_raw, agent, self.world)
                )
                if target_id is None:
                    bond_rejected = f"unknown target: {target_raw!r}"
                elif target_id == agent.id:
                    bond_rejected = "cannot declare a bond with yourself"
                else:
                    ok, msg = self.world.apply_bond(
                        agent, target_id, bond_type, self.world.tick
                    )
                    if ok:
                        bond_applied = {"target_id": target_id, "type": bond_type}
                        # The bond's relationship_changed (parked by apply_bond
                        # when the type actually changed) rides THIS turn's
                        # chain — _apply_action already drained its own batch,
                        # so this drain holds only the bond's event.
                        shifts = self.world.drain_relationship_events()
                        _tick = self.world.tick
                        extra_events.extend(
                            {"tick": _tick, **evt} for evt in shifts
                        )
                    else:
                        bond_rejected = msg
        if bond_rejected is not None:
            trace["bond_rejected"] = bond_rejected

        # EM-080 — reflection/diary entry (emitted whenever present; resets the
        # importance accumulator; the loop pushes it into the memory buffer).
        reflection_text = action_dict.get("reflection")
        if isinstance(reflection_text, str) and reflection_text.strip():
            importance = round(self._importance.get(agent.id, 0.0), 2)
            self._importance[agent.id] = 0.0
            reflection_payload: dict = {
                "text": reflection_text.strip(), "importance": importance,
            }
            # EM-125 — ADDITIVE observability key, present only when a bond
            # landed this reflection (EM-166 spirit).
            if bond_applied is not None:
                reflection_payload["bond_applied"] = bond_applied
            extra_events.append({
                "kind": "reflection",
                "actor_id": agent.id,
                "profile": profile_name,
                "profile_color": profile_color,
                "text": f"{agent.name} reflects: \"{reflection_text.strip()}\"",
                "payload": reflection_payload,
            })

        # ── Wave L / EM-223 — plan creation/revision, parsed from the SAME single
        # response (zero extra calls). Honored only when planning is enabled; the
        # normalized revision becomes the agent's new plan and emits ONE
        # plan_revised event (mirrors commitment_made — rides _multi, the loop
        # tick-stamps + persists + broadcasts). The plan is read-only context: it
        # NEVER touches reflex_streak / salience / the spontaneity roll, so the
        # EM-159/160 floor stays fully in charge. A rejected revision is recorded
        # in the trace, never failing the turn.
        plan_rev_rejected = action_dict.pop("_plan_revision_rejected", None)
        plan_revision = action_dict.get("plan_revision")
        plan_created = False
        if _planning_enabled(self.world.params) and isinstance(plan_revision, dict):
            old_plan = agent.plan if isinstance(agent.plan, dict) else None
            new_plan = normalize_plan({
                "plan_id": uuid.uuid4().hex,
                "goal": plan_revision.get("goal", ""),
                "steps": plan_revision.get("steps", []),
                "current_step": 0,
                "made_tick": self.world.tick,
                "stale": False,
            })
            if new_plan is not None:
                agent.plan = new_plan
                plan_created = True
                extra_events.append({
                    "kind": "plan_revised",
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "text": f"{agent.name} plans: {new_plan['goal']}",
                    "payload": {
                        "plan_id": new_plan["plan_id"],
                        "goal": new_plan["goal"],
                        "steps": list(new_plan["steps"]),
                        "reason": plan_revision.get("reason", ""),
                        "old_plan_id": old_plan.get("plan_id") if old_plan else None,
                    },
                })
        if plan_rev_rejected is not None:
            trace["plan_revision_rejected"] = plan_rev_rejected

        # EM-311 — self-authored charter rewrite (mirrors plan_revised — rides
        # _multi, the loop tick-stamps + persists + broadcasts, zero extra calls).
        # The sanitizer already normalized the revision to legal AMBITION_KINDS +
        # a capped creed; here it becomes the agent's new charter (bumping the
        # revision counter + stamping the tick) and emits ONE charter_revised event
        # carrying the exact old→new diff — the inspector-diff spectacle. Gated on
        # world.charters.enabled: a disabled world ignores the field and stays
        # byte-silent (the em161 golden). Bounded by the WORLD's effective caps
        # (World.charter_caps) so the applied charter is exactly what a snapshot
        # restore re-normalizes to (byte-stable round-trip, EM-155).
        charter_rev_rejected = action_dict.pop("_charter_revision_rejected", None)
        charter_revision = action_dict.get("charter_revision")
        if self.world.charters_enabled() and isinstance(charter_revision, dict):
            old_charter = agent.charter if isinstance(agent.charter, dict) else None
            prev_revisions = (
                int(old_charter.get("revisions", 0)) if old_charter else 0)
            _max_amb, _creed_cap = self.world.charter_caps()
            new_charter = normalize_charter({
                "ambitions": charter_revision.get("ambitions", []),
                "creed": charter_revision.get("creed", ""),
                "revised_tick": self.world.tick,
                "revisions": prev_revisions + 1,
            }, max_ambitions=_max_amb, creed_cap=_creed_cap)
            if new_charter is not None:
                agent.charter = new_charter
                vow = "; ".join(
                    AMBITION_GRAMMAR[a] for a in new_charter["ambitions"])
                extra_events.append({
                    "kind": "charter_revised",
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "text": f"{agent.name} now vows to {vow}.",
                    "payload": {
                        "ambitions": list(new_charter["ambitions"]),
                        "creed": new_charter["creed"],
                        "revisions": new_charter["revisions"],
                        "reason": charter_revision.get("reason", ""),
                        "old_ambitions": (
                            list(old_charter.get("ambitions", []))
                            if old_charter else []),
                        "old_creed": (
                            old_charter.get("creed", "") if old_charter else ""),
                    },
                })
        if charter_rev_rejected is not None:
            trace["charter_revision_rejected"] = charter_rev_rejected

        # EM-223 — deterministic v1 step pointer: a turn that resolved its plan's
        # work (not a fresh revision) nudges current_step forward. Zero-call,
        # plan-state only (the floor is untouched).
        if not plan_created:
            self._advance_plan_step(agent, commit_action, commit_ok)

        # EM-081/EM-199 — distribute EACH successful speech step to co-located
        # overhearers (not just the first action), so a `say` that rode along
        # with a move/work still reaches the room.
        for r in step_results:
            if r["ok"] and r["action"] in ("say", "whisper"):
                self._distribute_overheard(agent, r["action"], r["args"])
                self._record_said(agent.id, r["args"])  # EM-322 anti-repeat

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

    def _lane_stamped_span(
        self,
        call_profile: str,
        meta: dict,
        requested_profile: str,
        lane_reason: str | None,
    ) -> dict:
        """Wave D3 / EM-177 — build the per-attempt llm_call span, stamped with
        the ADDITIVE failover keys when this turn's call left its home lane:
        `requested_profile` (the home lane) plus `detoured: true` or
        `probe: true`. The span's profile keys stay the lane ACTUALLY called
        (forensics compatibility: per-profile timeout queries keep meaning
        "what the lane did"); a home-lane call (reason None) keeps the exact
        pre-D3 key set."""
        span = self._llm_attempt_span(call_profile, meta)
        if lane_reason == "detour":
            span["requested_profile"] = requested_profile
            span["detoured"] = True
        elif lane_reason == "probe":
            span["requested_profile"] = requested_profile
            span["probe"] = True
        elif lane_reason == "overflow":
            # EM-167 — the turn spilled to the off-critical-path overflow lane
            # (Ollama). Additive keys, same shape as detour/probe; a home-lane
            # turn keeps the exact pre-EM-167 key set.
            span["requested_profile"] = requested_profile
            span["overflow"] = True
        return span

    async def _call_and_parse(
        self,
        profile_name: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        agent: AgentState,
        attempt: int = 1,
        boosted: bool = False,
    ) -> tuple[dict | None, str | None, dict]:
        """
        Call the model and parse+validate the response.
        Returns (action_dict, error_string, llm_meta).
        `boosted=True` marks max_tokens as a truncation-mitigation boost (the
        EM-135 first-attempt bump or the length-retry), not a genuine floor —
        threaded to router.chat() so the adaptive bounce clamp keys on the
        EXPLICIT signal instead of inferring it from the home lane's window
        (which the W30 bounce-attribution redirect can leave clean).
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
            # EM-307 — prefer the per-call attribution channel: concurrent
            # chat() calls on one profile (narrator / deep-dive / animal
            # background tasks sharing an agent's lane) clobber the router's
            # per-profile pending snapshot, so the profile-level last_usage/
            # last_routed_via reads below can misattribute. chat_attributed()
            # returns THIS call's truth alongside the text; duck-typed test
            # routers without it keep the historical chat() + profile reads.
            attribution: dict | None = None
            chat_attr = getattr(self.router, "chat_attributed", None)
            if callable(chat_attr):
                # EM-306 — an agent turn is a STRICT-JSON turn (the reply is
                # parsed by _extract_first_json and schema-validated; anything
                # else dead-turns the agent), so mark it require_json: the
                # adaptive bounce loop then skips reasoning-tagged lanes,
                # whose chain-of-thought truncates before the object appears
                # (the #77/#78 lesson). `boosted` (#91) threads the truncation-
                # boost signal so the bounce loop's #77 token clamp keys on the
                # explicit flag. The real router accepts both kwargs; duck-typed
                # attributed routers (test harnesses) may lack `boosted`, so it
                # is advisory — drop it on TypeError, keep the attribution.
                try:
                    chat_coro = chat_attr(
                        profile_name, messages,
                        max_tokens=max_tokens, temperature=temperature,
                        require_json=True, boosted=boosted,
                    )
                except TypeError:
                    chat_coro = chat_attr(
                        profile_name, messages,
                        max_tokens=max_tokens, temperature=temperature,
                        require_json=True,
                    )
            else:
                chat_coro = self.router.chat(
                    profile_name, messages,
                    max_tokens=max_tokens, temperature=temperature,
                )
            if budget > 0:
                result = await asyncio.wait_for(chat_coro, timeout=budget)
            else:
                result = await chat_coro
            if callable(chat_attr):
                text, attribution = result
            else:
                text = result
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

        # Snapshot this call's routing/usage truth IMMEDIATELY, before any retry
        # can overwrite it. EM-307: the per-call attribution is authoritative
        # when present (same values the single-caller profile reads produced);
        # the profile-level reads remain only for duck-typed test routers.
        # usage is None for Mock; prefer the provider's own latency
        # measurement, falling back to our wall-clock timing.
        if attribution is not None:
            usage = attribution.get("usage")
            meta["routed_via"] = attribution.get("routed_via")
            served_by = attribution.get("served_by")
        else:
            usage = self.router.last_usage(profile_name)
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            served_by = None
        meta["usage"] = usage
        if isinstance(usage, dict) and usage.get("latency_ms") is not None:
            meta["latency_ms"] = usage["latency_ms"]
        else:
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)

        action_dict = _extract_first_json(text)
        finish_reason = usage.get("finish_reason") if isinstance(usage, dict) else None
        # EM-135 — report this attempt's parse outcome to the router's lane
        # health. Truncation is judged structurally on the RAW text even when
        # extraction SUCCEEDED: a response that parsed only via truncation
        # repair still means the lane is cutting output — salvage hides it
        # from the feed, not from health tracking.
        truncated = _looks_truncated(text)
        # EM-324 — a finish_reason=length that yielded NO parseable JSON is a
        # content-truncation the token boost can't cure on an output-capped lane
        # (the proxy's cohere/command-a-plus reroute: a plaintext reasoning
        # preamble hard-capped at 1024, run 1388). _looks_truncated only sees an
        # unclosed '{', so a pure-prose preamble evaded lane health entirely and
        # agents were fed straight back into it. Count it as a lane demerit so a
        # CHRONIC truncator goes sick → the bounce loop detours to a clean lane.
        content_truncation = action_dict is None and finish_reason == "length"
        self._note_parse_outcome(
            profile_name, parsed=action_dict is not None, truncated=truncated,
            served_by=served_by, errored=content_truncation,
        )
        if action_dict is None:
            # Structural truncation verdict for the retry-budget boost (the
            # reported finish_reason can be a lying 'stop'), plus the full raw
            # text for the final parse_failure event's forensics.
            meta["truncated_json"] = truncated
            meta["raw_text"] = text
            self._forget_response(profile_name, messages)
            return None, _no_json_error(text, finish_reason), meta

        # EM-249 — recover the "action": "actions" keyword-echo confusion (a model
        # that put the real steps in actions[] but also named the verb "actions")
        # BEFORE anything reads the shape, so the multi-action path takes over
        # instead of dying on the schema enum.
        _coerce_actions_keyword(action_dict)
        # EM-199 — lift turn-level cognition the model scattered into actions[0]
        # up to the top level (before sanitize/validate), so a 💭 thought / trace
        # nested in a step still counts. The step keeps its copy (items tolerate
        # extras); the runtime reads only action+args per step.
        _hoist_step_cognition(action_dict)
        # Optional EM-066 trace fields must never fail a turn — truncate, don't reject.
        _sanitize_optional_trace_fields(action_dict)
        # EM-125 — a malformed/disallowed bond is popped HERE (before schema
        # validation, where additionalProperties=False would otherwise fail the
        # whole turn over an optional field); the reason is stamped back on
        # AFTER validation so run_turn can surface it as trace bond_rejected.
        bond_rejected = _sanitize_bond(action_dict)
        # EM-223 — a malformed plan_revision is normalized or popped HERE (same
        # rule as the bond): a bad plan can never fail the turn.
        plan_rev_rejected = _sanitize_plan_revision(action_dict)
        # EM-311 — a malformed/off-grammar charter_revision is normalized or popped
        # HERE (same rule): a bad charter can never fail the turn. Bounded by the
        # WORLD's effective caps (not the module ceiling) so the write path and
        # from_snapshot agree on a non-default max_ambitions/creed_cap (byte-
        # stable round-trip, EM-155). getattr keeps duck-typed worlds safe.
        _caps = getattr(self.world, "charter_caps", None)
        _max_amb, _creed_cap = (
            _caps() if callable(_caps)
            else (CHARTER_MAX_AMBITIONS, CHARTER_CREED_CAP))
        charter_rev_rejected = _sanitize_charter_revision(
            action_dict, max_ambitions=_max_amb, creed_cap=_creed_cap)
        # Fold flat top-level action params (target/message/zone_id/…) into
        # `args` BEFORE _normalize_args, so alias resolution (name→id, place
        # aliases) sees them where it looks — and BEFORE _validate_schema,
        # so the top-level additionalProperties=False gate never rejects a
        # turn over a misplaced-but-recoverable field (EM-066 ethos).
        _fold_stray_top_level_into_args(action_dict)
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

        if bond_rejected is not None:
            # EM-125 — stamped after validation (the underscore key would fail
            # additionalProperties=False); run_turn pops it into the trace.
            action_dict["_bond_rejected"] = bond_rejected
        if plan_rev_rejected is not None:
            # EM-223 — same after-validation stamping as the bond rejection.
            action_dict["_plan_revision_rejected"] = plan_rev_rejected
        if charter_rev_rejected is not None:
            # EM-311 — same after-validation stamping as the plan rejection.
            action_dict["_charter_revision_rejected"] = charter_rev_rejected
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
        self, profile_name: str, *, parsed: bool, truncated: bool,
        served_by: str | None = None, errored: bool = False,
    ) -> None:
        """Report one parse attempt's outcome to the router's lane-health
        window (EM-135). `served_by` (EM-307) is the per-call attribution from
        chat_attributed() so a bounced outcome credits the lane that actually
        served, without reading the clobberable per-profile snapshot. Guarded
        getattr: duck-typed test routers don't implement note_parse_outcome();
        signature inspection (not a TypeError retry, which would mask a real
        TypeError raised INSIDE note()) degrades pre-EM-307 routers to the
        profile-level attribution.

        EM-324 — `errored=True` (a finish_reason=length with no parseable JSON)
        is threaded as a lane demerit so chronic silent-reroute truncators go
        sick and get detoured; guarded the same way for pre-EM-324 routers."""
        note = getattr(self.router, "note_parse_outcome", None)
        if not callable(note):
            return
        kwargs: dict = {"parsed": parsed, "truncated": truncated}
        if served_by is not None and _accepts_kwarg(note, "served_by"):
            kwargs["served_by"] = served_by
        if errored and _accepts_kwarg(note, "errored"):
            kwargs["errored"] = errored
        note(profile_name, **kwargs)

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

    @staticmethod
    def _normalize_steps(action_dict: dict, max_steps: int) -> tuple[list[dict], int]:
        """EM-199 — flatten a parsed turn into an ORDERED list of {action, args}
        steps. Prefers the `actions` sequence; falls back to the single `action`
        (so legacy turns become a one-step list). Truncates to max_steps.
        Returns (steps, dropped_count); dropped>0 means the model over-asked and
        the tail was cut (the caller logs it — never a silent cap)."""
        raw = action_dict.get("actions")
        steps: list[dict] = []
        if isinstance(raw, list) and raw:
            steps = [
                {"action": s.get("action"), "args": (s.get("args") or {})}
                for s in raw
                if isinstance(s, dict) and s.get("action")
            ]
        if not steps:  # no (valid) actions[] → the single-action form
            steps = [{
                "action": action_dict.get("action"),
                "args": action_dict.get("args") or {},
            }]
        dropped = len(steps) - max_steps if max_steps > 0 and len(steps) > max_steps else 0
        if dropped:
            steps = steps[:max_steps]
        return steps, dropped

    def _apply_steps(
        self,
        agent: AgentState,
        steps: list[dict],
        profile_name: str,
        profile_color: str,
        thought: str,
    ) -> tuple[list[dict], list[dict]]:
        """EM-199 — apply each step in order through the SAME pipeline a single
        action takes: per-step _normalize_args (collapse arg aliases like
        destination→place, resolve agent NAMES to ids — EM-140) → _validate_world
        gate (tier rule, target reachable, place known, funds, blackout, …) →
        _apply_action_inner dispatch. All resulting events (and each step's
        drained EM-113 relationship shifts) concatenate into ONE chain that
        loop._execute_turn tags with this turn's turn_id.

        Gating is per-step at APPLY time, so a step is checked against the state
        the PRIOR steps just produced — `work` after a `move_to` is validated at
        the destination, not the origin. Continue-on-failed-step: a gated /
        arg-missing / raising step emits its own parse_failure (carrying the
        world's reason) and NEVER aborts its siblings — the `say` still happens
        even if the `contribute_funds` was rejected. The turn `thought` (💭)
        rides ONLY the first event of the chain (and only the first step's
        payload), never duplicated.

        Returns (chain, step_results) where step_results aligns 1:1 with `steps`
        and carries {action, args, ok} for trace / commitment / overheard
        accounting."""
        chain: list[dict] = []
        step_results: list[dict] = []
        for idx, step in enumerate(steps):
            # EM-140/EM-199 — normalize THEN gate, the single-action order
            # (_validate_target assumes names already resolved to ids).
            _normalize_args(step, agent, self.world)
            action = step.get("action")
            args = step.get("args") or {}
            # EM-199 defense-in-depth — the gate itself runs under a guard so a
            # raising gate (e.g. an object/array id reaching a dict lookup as an
            # unhashable key) becomes a parse_failure step, never a loop-killing
            # raise. _apply_action_inner below is guarded the same way.
            try:
                gate_error = _validate_world(step, agent, self.world)
            except Exception as exc:
                chain.append({
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "tick": self.world.tick,
                    "kind": "parse_failure",
                    "text": f"{agent.name}'s {action} was rejected: {exc}",
                    "payload": {"action": action, "error": str(exc),
                                "rejected": True},
                })
                step_results.append({"action": action, "args": args, "ok": False})
                continue
            if gate_error:
                # A world-rejected step: surface the reason and move on. No
                # inner dispatch, so nothing was parked to drain.
                chain.append({
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "tick": self.world.tick,
                    "kind": "parse_failure",
                    "text": f"{agent.name}'s {action} was rejected: {gate_error}",
                    "payload": {"action": action, "error": gate_error,
                                "rejected": True},
                })
                step_results.append({"action": action, "args": args, "ok": False})
                continue
            # The turn thought rides the first step only (payload + 💭); later
            # steps carry no thought so payload.thought never duplicates.
            step_dict = {"action": action, "args": args,
                         "thought": thought if idx == 0 else ""}
            raised = False
            try:
                ev = self._apply_action_inner(
                    agent, step_dict, profile_name, profile_color
                )
                step_events = ev["_multi"] if "_multi" in ev else [ev]
            except Exception as exc:  # a bad step never aborts its siblings
                raised = True
                step_events = [{
                    "actor_id": agent.id,
                    "profile": profile_name,
                    "profile_color": profile_color,
                    "tick": self.world.tick,
                    "kind": "parse_failure",
                    "text": f"{agent.name}'s {action} could not resolve: {exc}",
                    "payload": {"action": action, "error": str(exc)},
                }]
            finally:
                # EM-113 — drain parked relationship shifts even on the
                # exception path so a parked event never leaks onto the next
                # agent's chain (dropped with the failed step, like _apply_action).
                shifts = self.world.drain_relationship_events()
            # EM-224 — surface a coherence annotation onto the primary event so
            # a 'say-then-harm' contradiction is legible (the act still ran). The
            # marker rides ONLY a real resolution (not a parse_failure); the
            # world already mutated. Stamps text + payload.coherence.
            marker = step.get("_coherence")
            if marker and step_events:
                primary = step_events[0]
                if primary.get("kind") != "parse_failure":
                    self._surface_coherence(primary, marker)
            chain.extend(step_events)
            if shifts and not raised:
                tick = self.world.tick
                chain.extend({"tick": tick, **s} for s in shifts)
            primary = step_events[0] if step_events else None
            ok = bool(primary) and primary.get("kind") != "parse_failure"
            step_results.append({"action": action, "args": args, "ok": ok})
        # EM-199 — the turn's thought rides the FIRST event of the chain only.
        if chain:
            self._surface_thought(chain[0], thought)
        return chain, step_results

    @staticmethod
    def _commitment_step(step_results: list[dict]) -> tuple[str | None, bool]:
        """EM-199 — distill a turn's SEQUENCE to the single (action, ok) that
        best represents it for EM-079 commitment accounting: a successful
        resolution call (project/build/economy) wins (credits follow-through),
        else any successful non-talk call (resets the staleness clock), else the
        first step (ages — pure talk / idle / failure). Keeps
        _advance_commitments on its unchanged single-action contract."""
        resolution = next(
            (r for r in step_results
             if r["ok"] and r["action"] in _COMMIT_RESOLUTION_ACTIONS), None)
        if resolution:
            return resolution["action"], True
        nontalk = next(
            (r for r in step_results
             if r["ok"] and r["action"] not in _TALK_ACTIONS), None)
        if nontalk:
            return nontalk["action"], True
        first = step_results[0]
        return first["action"], first["ok"]

    def _apply_action(
        self,
        agent: AgentState,
        action_dict: dict,
        profile_name: str,
        profile_color: str,
    ) -> dict:
        """Apply the validated action to world state. Return event dict.

        Wave E / EM-113 — after the action resolves, drain the world's
        relationship_changed outbox (reflex type transitions triggered by this
        action's trust mutations, plus accepted set_relationship changes) and
        append them to the action's `_multi` chain so they share its turn_id.
        Both turn paths (LLM and reflex) come through here, so every
        action-triggered transition rides its triggering turn."""
        try:
            result = self._apply_action_inner(
                agent, action_dict, profile_name, profile_color
            )
        finally:
            # Wave E B4 carry-over (ratified B1 QE finding) — drain even when a
            # handler raises: a parked relationship_changed must never leak
            # onto the NEXT agent's turn chain. On the exception path the
            # drained events are dropped with the failed action that parked
            # them (the state change itself stands; only its feed echo is
            # lost — strictly better than mis-attributing it to a stranger).
            shifts = self.world.drain_relationship_events()
        # EM-227 — learn-by-doing: a SUCCESSFUL gated action grants the gating
        # skill xp (a level-up replenishes the EM-229 knowledge need). The gate
        # already guaranteed the agent HAD the skill, so this deepens a profession
        # the more it is practiced. Skipped on a failed/parse_failure result and
        # when no library gates the action (config-absent = no-op, golden-safe).
        self._grant_use_xp(agent, action_dict, result)
        # Surface the agent's inner thought onto the feed line so the world's
        # reasoning is legible at a glance instead of buried in payload.thought.
        # Appended once to the primary action event (never the drained
        # relationship shifts); an empty/absent thought leaves the line untouched.
        self._surface_thought(result, action_dict.get("thought", ""))
        if shifts:
            tick = self.world.tick
            decorated = [{"tick": tick, **evt} for evt in shifts]
            if "_multi" in result:
                result["_multi"].extend(decorated)
            else:
                result = {"_multi": [result] + decorated}
        return result

    def _grant_use_xp(self, agent: AgentState, action_dict: dict, result: dict) -> None:
        """EM-227 — grant the gating skill xp for a SUCCESSFUL gated action. The
        action's result must be a real outcome (not a parse_failure) — a rejected
        verb earns nothing. No library gates the action ⇒ no-op (config-absent =
        no-op). Pure threshold arithmetic in world.grant_skill_xp (no random/clock).
        Robust to the _multi chain shape (the primary event is _multi[0])."""
        world = self.world
        if not hasattr(world, "skill_gate_for"):
            return
        action = action_dict.get("action")
        if not isinstance(action, str):
            return
        gate = world.skill_gate_for(action)
        if gate is None:
            return
        primary = result["_multi"][0] if isinstance(result, dict) and "_multi" in result else result
        if not isinstance(primary, dict) or primary.get("kind") == "parse_failure":
            return
        skill, _min = gate
        try:
            xp = int(world._skills_param("xp_per_use", 10))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            xp = 10
        world.grant_skill_xp(agent, skill, xp)

    @staticmethod
    def _surface_thought(result: dict, thought: str) -> None:
        """Append the agent's one-sentence inner thought to the primary action
        event's feed text (💭), so the reasoning rides the stream instead of
        living only in payload.thought. No-op on an empty thought or a textless
        event; targets _multi[0] so a thought never duplicates across the chain."""
        thought = (thought or "").strip()
        if not thought:
            return
        primary = result["_multi"][0] if "_multi" in result else result
        text = primary.get("text")
        if text:
            primary["text"] = f"{text}  💭 {thought}"

    @staticmethod
    def _surface_coherence(event: dict, marker: dict) -> None:
        """EM-224 — stamp a contradicting action's event so the say-then-harm
        dissonance is legible: append a ⚠/💢 coherence note to the feed text and
        attach `payload.coherence`. ADDITIVE, only on a flagged event (the
        'annotate' strategy keeps the act — the world still mutated). No-op on a
        textless event."""
        event.setdefault("payload", {})["coherence"] = {
            "intent": marker.get("intent"),
            "contradicted": True,
        }
        text = event.get("text")
        if text:
            event["text"] = f"{text}  💢 (belying their {marker.get('intent')} words)"

    def _profile_stamp(self, agent_id: str) -> dict | None:
        """The (profile, profile_color) stamp for ANOTHER agent swept into an
        acting agent's `_multi` chain (a clash kill's `agent_died`, the heir's
        `inherited`): those events must wear their OWN actor's chip, not the
        acting agent's — the same mis-attribution class travel_arrived was
        fixed for. None for an unknown id (the base stamp then stands)."""
        other = self.world.agents.get(str(agent_id))
        if other is None:
            return None
        name = self.router.profile_name_for(other.id, other.profile)
        profile = self.router.get_profile(name)
        return {"profile": name,
                "profile_color": profile.color if profile else "#888888"}

    def _apply_action_inner(
        self,
        agent: AgentState,
        action_dict: dict,
        profile_name: str,
        profile_color: str,
    ) -> dict:
        """The action dispatch table (see _apply_action for the EM-113 drain)."""
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

        # EM-240 — offensive crime verbs (Task 6). heist/extort resolve an agent
        # target and return (ok, reason, amount) like steal; vandalize targets a
        # building and returns a ready event dict like arson.
        elif action == "heist":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to heist but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, amount = self.world.action_heist(agent, target)
            if ok:
                return {**base, "kind": "crime_committed", "target_id": target.id,
                        "text": f"{agent.name} pulls off a heist on {target.name} ({amount} credits)!",
                        "payload": {"action": "heist", "amount": amount, "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to heist but: {reason}",
                    "payload": {"error": reason}}

        elif action == "extort":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to extort but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, amount = self.world.action_extort(agent, target)
            if ok:
                return {**base, "kind": "crime_committed", "target_id": target.id,
                        "text": f"{agent.name} shakes down {target.name} for {amount} credits!",
                        "payload": {"action": "extort", "amount": amount, "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to extort but: {reason}",
                    "payload": {"error": reason}}

        # EM-237 — harm-surface finishers. intimidate resolves an agent target and
        # returns (ok, reason, amount) like extort; deceive resolves a target +
        # reads the `about` claim and returns (ok, reason).
        elif action == "intimidate":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to intimidate but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, amount = self.world.action_intimidate(agent, target)
            if ok:
                return {**base, "kind": "intimidate", "target_id": target.id,
                        "text": f"{agent.name} menaces {target.name} into handing over {amount} credits!",
                        "payload": {"action": "intimidate", "amount": amount,
                                    "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to intimidate but: {reason}",
                    "payload": {"error": reason}}

        elif action == "deceive":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to deceive but target not found",
                        "payload": {"error": "target_not_found"}}
            about = str(args.get("about", "")).strip()
            ok, reason = self.world.action_deceive(agent, target, about)
            if ok:
                return {**base, "kind": "deceive", "target_id": target.id,
                        "text": f"{agent.name} feeds {target.name} a lie.",
                        "payload": {"action": "deceive", "about": about,
                                    "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to deceive but: {reason}",
                    "payload": {"error": reason}}

        elif action == "vandalize":
            result = self.world.action_vandalize(agent, args.get("building_id", ""))
            return _emit_world_result(result, base, thought)

        # EM-258/EM-259 — the war verbs. All three world actions return ready
        # event dicts (war_band_joined / war_clash / war_siege on success, a
        # clear parse_failure fail event otherwise) or a {"_multi": [...]}
        # chain (a clash kill appends agent_died + inheritance; a siege
        # appends the building state transition) — _emit_world_result consumes
        # both shapes, exactly like vandalize/recruit.
        elif action == "muster":
            return _emit_world_result(
                self.world.action_muster(agent), base, thought)

        elif action == "clash":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to clash but target not found",
                        "payload": {"error": "target_not_found"}}
            # A kill's _multi chain carries the slain TARGET's agent_died and
            # the HEIR's inherited — stamp_for dresses those in their OWN
            # actor's profile/color, not the attacker's.
            return _emit_world_result(
                self.world.action_clash(agent, target), base, thought,
                stamp_for=self._profile_stamp)

        elif action == "siege":
            return _emit_world_result(
                self.world.action_siege(agent, args.get("building_id", "")),
                base, thought)

        # EM-251 — culture transmission verbs (Wave O Culture stage), both
        # reflex. Each world action returns a ready event dict (rumor_spread /
        # letter_sent) — or a {"_multi": [...]} chain (spread_rumor appends
        # meme_mutated when the hop drifted the text) — or a clear parse_failure;
        # _emit_world_result consumes both shapes, exactly like recruit/clash.
        elif action == "spread_rumor":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to spread a rumor but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_spread_rumor(
                    agent, target,
                    args.get("rumor", "") or args.get("text", ""),
                    args.get("meme_id")),
                base, thought)

        elif action == "send_letter":
            # The recipient may be ABSENT (the whole point) — resolve by id only;
            # a name was already resolved to an id by _normalize_args.
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to send a letter but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_send_letter(agent, target, args.get("text", "")),
                base, thought)

        # EM-253 — culture lifecycle verbs (Wave O Culture stage), both reflex.
        # create_meme coins an idea (no target); adopt_meme takes up a meme by id
        # (an image meme drifts a child, returned as a {"_multi": [...]} chain).
        # Each world action returns a ready event dict OR a clear _fail_event —
        # _emit_world_result consumes both shapes, exactly like create_image.
        elif action == "create_meme":
            return _emit_world_result(
                self.world.action_create_meme(agent, args.get("text", "")),
                base, thought)

        elif action == "adopt_meme":
            return _emit_world_result(
                self.world.action_adopt_meme(agent, args.get("meme_id", "")),
                base, thought)

        # EM-240 — economy & corruption verbs (Task 7). launder takes NO target
        # and returns (ok, reason, fee); bribe resolves an enforcer target and
        # returns (ok, reason, paid). Both mirror steal's tuple-dispatch shape.
        elif action == "launder":
            ok, reason, fee = self.world.action_launder(agent, args.get("amount", 0))
            if ok:
                return {**base, "kind": "economy",
                        "text": f"{agent.name} launders credits to cool their heat ({fee} cut).",
                        "payload": {"action": "launder", "fee": fee, "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to launder but: {reason}",
                    "payload": {"error": reason}}

        elif action == "bribe":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to bribe but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, paid = self.world.action_bribe(agent, target, args.get("amount", 0))
            if ok:
                return {**base, "kind": "bribe", "target_id": target.id,
                        "text": f"{agent.name} slips {target.name} {paid} credits to drop the heat.",
                        "payload": {"action": "bribe", "amount": paid, "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to bribe but: {reason}",
                    "payload": {"error": reason}}

        # EM-240 — conspiracy verbs (Task 8). recruit resolves a co-located target
        # and returns a ready event dict (_emit_world_result, like vandalize);
        # accept_contract takes NO target and returns a (ok, reason) 2-tuple.
        elif action == "recruit":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to recruit but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_recruit(agent, target), base, thought)

        elif action == "accept_contract":
            ok, reason = self.world.action_accept_contract(agent)
            if ok:
                return {**base, "kind": "recruited",
                        "text": f"{agent.name} seals the pact — a ring is born.",
                        "payload": {"action": "accept_contract", "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to accept a contract but: {reason}",
                    "payload": {"error": reason}}

        # EM-228 — cooperation lever. teach_skill resolves a co-located target and
        # returns a ready event dict (skill_taught on success, teach_failed
        # otherwise — both via teach_skill_event); request_skill parks a pending
        # request and returns a ready event dict (skill_requested / a fail event).
        elif action == "teach_skill":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to teach but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.teach_skill_event(agent, target, args.get("skill", "")),
                base, thought)

        elif action == "request_skill":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to ask but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_request_skill(agent, target, args.get("skill", "")),
                base, thought)

        # EM-230 — real trade. offer_trade resolves a co-located target and parks an
        # offer (ready event dict: trade_offered / a fail event). accept_trade settles
        # the open offer addressed to this agent via the ATOMIC swap (trade_settled /
        # trade_failed via settle_trade_event). decline_trade drops it (trade_declined
        # / a fail event). accept/decline take NO target (keyed by this agent's id).
        elif action == "offer_trade":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to offer a trade but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_offer_trade(
                    agent, target, args.get("give"), args.get("get")),
                base, thought)

        elif action == "accept_trade":
            return _emit_world_result(
                self.world.settle_trade_event(agent), base, thought)

        elif action == "decline_trade":
            return _emit_world_result(
                self.world.action_decline_trade(agent), base, thought)

        # EM-231 — cooperation handshake + the ONE gated action. offer_cooperation
        # resolves a co-located target and parks a handshake offer (ready event:
        # cooperation_offered / a fail event). accept_cooperation forms the active
        # link (cooperation_formed / a fail event); it takes NO target (keyed by
        # this agent's id). co_build advances a building with a co-located partner
        # this agent has agreed to cooperate with (co_built / a fail event).
        elif action == "offer_cooperation":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to offer a partnership but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_offer_cooperation(agent, target), base, thought)

        elif action == "accept_cooperation":
            return _emit_world_result(
                self.world.action_accept_cooperation(agent), base, thought)

        elif action == "co_build":
            return _emit_world_result(
                self.world.action_co_build(agent, args.get("building_id")),
                base, thought)

        # EM-240 — enforcer justice verbs (Task 10). investigate returns a
        # (ok, reason, count) tuple like steal; accuse returns a ready event dict
        # like vandalize; detain returns a dict on success OR a (False, reason,
        # None) tuple on rejection (the MIXED return shape — handle both).
        elif action == "investigate":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to investigate but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason, n = self.world.action_investigate(agent, target)
            if ok:
                return {**base, "kind": "investigation", "target_id": target.id,
                        "text": f"{agent.name} questions witnesses about {target.name} "
                                f"({n} crime{'s' if n != 1 else ''} confirmed).",
                        "payload": {"action": "investigate", "confirmed": n,
                                    "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to investigate but: {reason}",
                    "payload": {"error": reason}}

        elif action == "accuse":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to accuse but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_accuse(agent, target), base, thought)

        elif action == "detain":
            target = self.world.agents.get(args.get("target"))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to detain but target not found",
                        "payload": {"error": "target_not_found"}}
            result = self.world.action_detain(agent, target)
            # action_detain returns a dict on success OR a (False, reason, None) tuple.
            if isinstance(result, dict):
                return _emit_world_result(result, base, thought)
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to detain but: {result[1]}",
                    "payload": {"error": result[1]}}

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
            whisper_text = args.get("text", "")
            return {**base, "kind": "agent_speech", "target_id": target.id,
                    # The watcher (you) sees the whisper content — it stays
                    # `private: True` so OTHER agents don't get it in their
                    # context, but hiding it from the omniscient observer just
                    # turned the feed into opaque "X whispers to Y" filler.
                    "text": f'{agent.name} whispers to {target.name}: "{whisper_text}"',
                    "payload": {"action": "whisper", "said": whisper_text,
                                "place": agent.location, "private": True, "thought": thought}}

        elif action == "insult":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to insult but target not found",
                        "payload": {"error": "target_not_found"}}
            ok, reason = self.world.action_insult(agent, target)
            if ok:
                # run-663: render the barb in the feed text when present so
                # insults are not flavorless — the raw insult_text stays in
                # the payload unchanged for downstream consumers.
                barb = args.get("text", "")
                if barb:
                    display_barb = barb[:200]  # truncate gracefully; never drop
                    insult_text = (
                        f'{agent.name} insults {target.name}: "{display_barb}"'
                    )
                else:
                    insult_text = f"{agent.name} insults {target.name}!"
                return {**base, "kind": "conflict", "target_id": target.id,
                        "text": insult_text,
                        "payload": {"action": "insult",
                                    "insult_text": barb, "thought": thought}}
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

        # EM-232 — Victory Arch: pitch_contribution parks this agent's pitch keyed
        # by their id (a contribution_pitched event / a fail event on blank text);
        # the periodic peer-judge cycle ranks + awards. Reflex, no target — the
        # pitch text rides this turn (zero extra LLM calls). The text arg is read
        # from `text` (or a `pitch` alias) so a model's loose JSON still lands.
        elif action == "pitch_contribution":
            return _emit_world_result(
                self.world.action_pitch_contribution(
                    agent, args.get("text") or args.get("pitch") or ""),
                base, thought)

        # EM-235 — boost queue: buy_turn charges world.boost.cost credits + queues
        # an EXTRA scheduled turn for this agent (a turn_boosted event / a fail
        # event when OFF, too poor, or over the per-round cap). Reflex, no args —
        # the buy rides this turn (zero extra LLM calls); the extra turn it grants
        # is a real new scheduled slot honored by the world scheduler.
        elif action == "buy_turn":
            return _emit_world_result(
                self.world.action_buy_turn(agent), base, thought)

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
            # Wave K / EM-219 — demolish carries the target building id.
            # EM-254 — canonize_meme carries the meme id; the model may put it on
            # args.meme_id, so fold that into the generic target the world reads.
            # EM-261 — consecrate_faith carries the faith id; fold args.faith_id
            # into the same generic target (the canonize recipe).
            target = args.get("target") or args.get("building_id") or (
                args.get("meme_id") if effect == "canonize_meme" else None) or (
                args.get("faith_id") if effect == "consecrate_faith" else None)
            # Wave I / EM-212 — promote_image carries the gallery image id.
            image_id = args.get("image_id")
            # EM-236 — amend_constitution carries op (add|edit|remove) + an optional
            # article_id (for edit/remove). article_id also arrives via the generic
            # `target` arg (the model may reuse it), so accept either.
            op = args.get("op")
            article_id = args.get("article_id") or (
                args.get("target") if effect == "amend_constitution" else None)
            # EM-244 (S3a) — set_car_policy carries scope/policy; demolish_road reuses
            # the generic target arg (the world handler reads them off the kwargs).
            scope = args.get("scope")
            policy = args.get("policy")
            # EM-265 (SB) — set_zone_rule carries {zone_id, hint, density_cap};
            # the zone id may arrive on the generic `target` arg (the world handler
            # maps either key, like demolish's target/building_id).
            zone_id = args.get("zone_id")
            hint = args.get("hint")
            density_cap = args.get("density_cap")
            # EM-257 — declare_war reuses the generic target (the enemy faction,
            # id or name); peace_treaty carries war_id (or the generic target —
            # the demolish target/building_id convention) + optional reparations.
            war_id = args.get("war_id")
            reparations = args.get("reparations")
            ok, reason, rule = self.world.action_propose_rule(
                agent, effect, text, name, target, image_id, op, article_id,
                scope=scope, policy=policy,
                zone_id=zone_id, hint=hint, density_cap=density_cap,
                war_id=war_id, reparations=reparations)
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
            # Wave K / EM-182 — optional chosen build place (a district id).
            place = args.get("place")
            # EM-266 (SC) — optional targeted zone (a planar-face id). Loose: the
            # world resolves/ignores it (flag-gated) — an absent/bad id never blocks.
            zone_id = args.get("zone_id")
            # fix-wave A3 — alias a stray `zone` arg onto `zone_id` (only when zone_id
            # is absent) so an old-styled / replayed `zone=` emission still targets the
            # zone. The schema + world read ONLY zone_id; an explicit zone_id wins.
            if zone_id is None:
                zone_id = args.get("zone")
            # EM-299 (Wave Q) — OPTIONAL parametric recipe (a shape object). The
            # world validates/coerces + flag-gates it; a bad/absent recipe never
            # blocks the build (passed through untouched).
            recipe = args.get("recipe")
            result = self.world.action_propose_project(
                agent, name, kind, funds_required, function, place, zone_id, recipe
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

        # ── Wave H4 / EM-209 — pets & bonds reflex tools ───────────────────────
        elif action == "adopt":
            animal_id = args.get("animal_id", "")
            ok, reason = self.world.action_adopt(agent, animal_id)
            animal = (getattr(self.world, "animals", {}) or {}).get(animal_id)
            pet_name = getattr(animal, "name", animal_id)
            if ok:
                return {**base, "kind": "agent_action",
                        "text": f"{agent.name} adopts {pet_name}!",
                        "payload": {"action": "adopt", "animal_id": animal_id,
                                    "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to adopt but: {reason}",
                    "payload": {"action": "adopt", "error": reason}}

        elif action == "feed_pet":
            animal_id = args.get("animal_id", "")
            ok, reason = self.world.action_feed_pet(agent, animal_id)
            animal = (getattr(self.world, "animals", {}) or {}).get(animal_id)
            pet_name = getattr(animal, "name", animal_id)
            if ok:
                return {**base, "kind": "agent_action",
                        "text": f"{agent.name} feeds {pet_name}.",
                        "payload": {"action": "feed_pet", "animal_id": animal_id,
                                    "thought": thought}}
            return {**base, "kind": "parse_failure",
                    "text": f"{agent.name} tried to feed {pet_name} but: {reason}",
                    "payload": {"action": "feed_pet", "error": reason}}

        # ── Wave K / EM-218–220 — builders'-city reflex tools (dispatch to the
        # world-core action_*; each returns a ready-to-emit event dict consumed by
        # _emit_world_result, exactly like the W7 building actions). ────────────
        elif action == "place_prop":
            result = self.world.action_place_prop(
                agent, args.get("kind", ""), args.get("place"))
            return _emit_world_result(result, base, thought)

        elif action == "remove_prop":
            result = self.world.action_remove_prop(agent, args.get("prop_id", ""))
            return _emit_world_result(result, base, thought)

        elif action == "demolish":
            result = self.world.action_demolish(agent, args.get("building_id", ""))
            return _emit_world_result(result, base, thought)

        elif action == "set_building_skin":
            result = self.world.action_set_building_skin(
                agent, args.get("building_id", ""), args.get("skin", ""))
            return _emit_world_result(result, base, thought)

        # ── EM-243 (S2) — extend the road graph one axis-aligned block ──────────
        elif action == "build_road":
            result = self.world.action_build_road(agent, args)
            return _emit_world_result(result, base, thought)

        # ── EM-261 — found a faith and become its first devotee (reflex) ────────
        # action_found_faith returns a ready event dict (faith_founded) OR a clear
        # _fail_event (faith disabled / already faithful) — _emit_world_result
        # consumes both, exactly like create_meme.
        elif action == "found_faith":
            return _emit_world_result(
                self.world.action_found_faith(agent), base, thought)

        # ── EM-262 — religion emergence: proselytize (convert a co-located
        # faithless target) + worship (temple buff). action_proselytize returns a
        # single event OR a {"_multi": [proselytized, faith_joined]} chain on a
        # conversion; action_worship returns a single event. Both may fail-event —
        # _emit_world_result consumes every shape, like clash/found_faith.
        elif action == "proselytize":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to proselytize but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_proselytize(agent, target), base, thought)

        elif action == "worship":
            return _emit_world_result(
                self.world.action_worship(agent), base, thought)

        # ── EM-263 — the religion conflict surface: excommunicate (cast a member
        # out of the founder's faith — target resolved by name/id, need NOT be
        # co-located) + declare_hostility (mark a rival faith hostile — carries a
        # faith_id, not an agent target). Both may fail-event (faith off / non-
        # founder / bad target) — _emit_world_result consumes every shape.
        elif action == "excommunicate":
            target = self.world.agents.get(args.get("target", ""))
            if target is None:
                return {**base, "kind": "parse_failure",
                        "text": f"{agent.name} tried to excommunicate but target not found",
                        "payload": {"error": "target_not_found"}}
            return _emit_world_result(
                self.world.action_excommunicate(agent, target), base, thought)

        elif action == "declare_hostility":
            return _emit_world_result(
                self.world.action_declare_hostility(
                    agent, str(args.get("faith_id") or "")),
                base, thought)

        # ── EM-269 (F2) — found a settlement at the agent's current place ───────
        elif action == "found_settlement":
            result = self.world.action_found_settlement(
                agent, str(args.get("name") or ""))
            return _emit_world_result(result, base, thought)

        # ── EM-110 — travel to another settlement (goes off-board until arrival) ─
        elif action == "travel_to":
            result = self.world.action_travel_to(
                agent, str(args.get("settlement") or ""))
            return _emit_world_result(result, base, thought)

        # ── W11b / EM-091 billboard reflex tools ───────────────────────────────
        elif action == "post_billboard":
            result = self.world.action_post_billboard(agent, args.get("text", ""))
            return _emit_world_result(result, base, thought)

        # ── Wave I / EM-210+211 — The Atelier reflex tools ──────────────────────
        elif action == "create_image":
            result = self.world.action_create_image(agent, args.get("prompt", ""))
            return _emit_world_result(result, base, thought)

        # ── EM-298 — agent-authored facades: paint a decal onto a building ──────
        elif action == "paint_surface":
            result = self.world.action_paint_surface(
                agent, args.get("target", ""), args.get("prompt", ""))
            return _emit_world_result(result, base, thought)

        elif action == "post_image":
            result = self.world.action_post_image(agent, args.get("image_id"))
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

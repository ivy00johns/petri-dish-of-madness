"""
Animal runtime (W8 / EM-064) — the chaos layer.

AnimalRuntime.act resolves ONE animal's turn on its slow cadence:

  ROLL FOR ACTIVITY
  ├─ with probability world.params.animals.llm_chance → ONE LLM call:
  │     router.chat(animals.model_profile, [role-card + brief world view]);
  │     parse against the animal-action protocol; ONE retry; on parse/provider
  │     failure FALL BACK to a reflex micro-behavior — never crash the loop.
  └─ otherwise → a REFLEX micro-behavior (ZERO LLM calls), picked from a weighted
        table by a SEEDED hash of (animal.id + tick) so tests + replay are
        reproducible (no wall-clock, no RNG source).

Animals are framed to the LLM as critters that act impulsively and IN-CHARACTER,
NOT to optimize. The toolset is intentionally UNDER-CONSTRAINED, so the model MAY
escalate to an absurd action (arson / steal_food). Effects on the world reuse
EXISTING resolution where possible: arson / a knock_over on a building go through
the SAME building-damage path human arson uses (world.animal_damage_building ->
world._damage_building), so the W7 state machine + invariant 8 hold identically.
steal_food / scratch / pounce / chase touch target mood/relationship FEELING only
and move NO credits (invariant 7).

Free-scale guarantees (QE asserts):
  - a reflex tick makes ZERO router calls;
  - an acted tick makes AT MOST ONE;
  - if animals.model_profile is unavailable, the animal falls back to reflex-only
    (no crash, never routes to a non-configured / paid profile).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

import jsonschema

from ..engine.world import World, Animal
from ..providers.base import ProviderError
from ..providers.router import Router

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Animal-action protocol schema (mirrors contracts/animal-action.schema.json).
#
# Embedded (like the agent ACTION_SCHEMA in agents/runtime.py) to avoid file-path
# issues. UNDER-CONSTRAINED on purpose: `action` is the only required field, and
# the per-action arg requirements are light (only steal_food/arson require a
# target/building_id). animal_thought is truncated, never fails the turn.
# ──────────────────────────────────────────────────────────────────────────────

ANIMAL_ACTION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["action"],
    "additionalProperties": False,
    "properties": {
        "animal_thought": {"type": "string", "maxLength": 280},
        "mood": {"type": "string", "maxLength": 40},
        "action": {
            "type": "string",
            "enum": [
                "wander", "nap", "knock_over", "scratch", "mark_territory",
                "pounce", "chase", "idle", "steal_food", "arson",
            ],
        },
        "args": {"type": "object", "default": {}},
    },
    "allOf": [
        {"if": {"properties": {"action": {"const": "steal_food"}}},
         "then": {"properties": {"args": {"required": ["target"], "properties": {
             "target": {"type": "string"}}}}}},
        {"if": {"properties": {"action": {"const": "arson"}}},
         "then": {"properties": {"args": {"required": ["building_id"], "properties": {
             "building_id": {"type": "string"}}}}}},
    ],
}

# The animal action verbs (the under-constrained toolset).
ANIMAL_ACTIONS = frozenset(ANIMAL_ACTION_SCHEMA["properties"]["action"]["enum"])

# Truncation caps for the free-text fields so a verbose model never loses its turn.
_THOUGHT_CAP = 280
_MOOD_CAP = 40

# is_chaotic heuristic (world-model.md §W8 / EM-065): a crime / economy /
# structure-targeting tool, or an otherwise low-prior action. knock_over is only
# chaotic when it targets a BUILDING (computed in act()).
_ALWAYS_CHAOTIC = frozenset({"arson", "steal_food"})
_LOW_PRIOR = frozenset({"mark_territory"})  # mildly anti-social / off-distribution


# ──────────────────────────────────────────────────────────────────────────────
# Reflex table — weighted micro-behaviors, picked by a SEEDED hash (deterministic).
#
# Weights are intentionally tame: most reflex ticks are harmless ambient behavior
# (wander / nap / idle); the destructive options (knock_over) are rare so the
# free-scale, zero-LLM path stays low-chaos and the LLM path supplies the spice.
# Per-species so the cat and dog feel different (cats knock things over + scratch;
# dogs chase + pounce). NOTE: reflex NEVER picks arson — that absurd escalation is
# LLM-only (the under-constrained toolset). EM-143: the thief species (raccoon /
# fox / crow) DO carry steal_food in their reflex table — it is their defining
# chaos flavor, moves NO credits (invariant 7, see _apply), and is the comedic
# snack-swipe, not arson.
# ──────────────────────────────────────────────────────────────────────────────

_REFLEX_TABLE: dict[str, list[tuple[str, int]]] = {
    "cat": [
        ("nap", 5),
        ("wander", 4),
        ("knock_over", 3),
        ("scratch", 3),
        ("mark_territory", 2),
        ("pounce", 2),
        ("idle", 2),
    ],
    "dog": [
        ("chase", 5),
        ("wander", 4),
        ("pounce", 3),
        ("nap", 2),
        ("scratch", 1),
        ("mark_territory", 2),
        ("idle", 2),
    ],
    # EM-143 — the expanded menagerie. Each species' reflex weighting expresses its
    # "chaos flavor" using ONLY the existing reflex verbs (no new action types).
    "squirrel": [          # skittish hoarder: wander/pounce/nap heavy, light marking
        ("wander", 5),
        ("pounce", 4),
        ("nap", 4),
        ("idle", 2),
        ("scratch", 1),
        ("mark_territory", 1),
    ],
    "raccoon": [           # ransacker/thief: knock_over heavy + steal_food + marking
        ("knock_over", 5),
        ("steal_food", 3),
        ("mark_territory", 3),
        ("wander", 3),
        ("scratch", 1),
        ("idle", 1),
    ],
    "goat": [              # stubborn grazer: wander/scratch/mark + headbutt pounce
        ("wander", 5),
        ("scratch", 3),
        ("mark_territory", 3),
        ("pounce", 3),
        ("nap", 1),
        ("idle", 1),
    ],
    "fox": [               # cunning raider: chase/steal_food/pounce heavy
        ("chase", 5),
        ("steal_food", 4),
        ("pounce", 4),
        ("wander", 2),
        ("nap", 1),
        ("idle", 1),
    ],
    "crow": [              # thieving trickster: steal_food heavy + wander + swoop
        ("steal_food", 5),
        ("wander", 4),
        ("pounce", 4),
        ("knock_over", 2),
        ("idle", 1),
    ],
}
# Fallback table for an unknown species (still deterministic, still tame).
_REFLEX_TABLE_DEFAULT: list[tuple[str, int]] = [
    ("wander", 5), ("nap", 4), ("idle", 3), ("pounce", 2), ("knock_over", 1),
]


def _seed_int(*parts: Any) -> int:
    """Deterministic, wall-clock-free seed from the given parts. A stable sha256 of
    the joined parts — used to pick a reflex action and to roll for activity so the
    whole animal layer is reproducible across runs + replay."""
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest, 16)


def _weighted_pick(table: list[tuple[str, int]], seed: int) -> str:
    """Pick an action from a weighted table using `seed` (no RNG). Deterministic:
    the same (table, seed) always yields the same action."""
    total = sum(max(0, w) for _, w in table)
    if total <= 0:
        return table[0][0] if table else "idle"
    roll = seed % total
    acc = 0
    for action, weight in table:
        acc += max(0, weight)
        if roll < acc:
            return action
    return table[-1][0]


# ──────────────────────────────────────────────────────────────────────────────
# Persona role cards (structured — species, name, drives, sensory framing, and the
# explicit "act impulsively, in-character, do NOT optimize" instruction).
# ──────────────────────────────────────────────────────────────────────────────

_ROLE_CARDS: dict[str, dict[str, Any]] = {
    "cat": {
        "sensory": "You experience the world as a cat: low to the ground, all "
                   "whiskers and disdain, drawn to warm sunbeams, high ledges, and "
                   "anything that dares to move.",
        "drives": [
            "nap in sunbeams", "knock things off ledges for no reason",
            "scratch what you please", "claim territory", "stalk and pounce",
            "ignore every human law and every coin",
        ],
    },
    "dog": {
        "sensory": "You experience the world as a dog: nose-first and overjoyed, "
                   "certain that every person, ball, and stick is the best thing "
                   "that has ever happened.",
        "drives": [
            "chase anything that moves", "pounce on friends", "beg for and steal "
            "snacks", "mark your favourite spots", "mean well, even mid-disaster",
        ],
    },
    # EM-143 — the expanded menagerie. Distinct sensory + drives prose per species.
    "squirrel": {
        "sensory": "You experience the world as a squirrel: a russet-brown blur of "
                   "twitching nerves and bottomless cheeks, certain that every nut, "
                   "crumb, and shiny scrap must be hoarded RIGHT NOW or lost forever.",
        "drives": [
            "dart and freeze and dart again", "hoard anything that fits in your cheeks",
            "pounce on a falling acorn", "nap in a sunlit fork of a branch",
            "trust no one, suspect everyone",
        ],
    },
    "raccoon": {
        "sensory": "You experience the world as a raccoon: a grey bandit in a pale "
                   "mask, clever little hands itching to pry open, tip over, and "
                   "rifle through every latch, lid, and bin you can reach.",
        "drives": [
            "knock things over to see what spills", "wash and steal a stranger's snack",
            "ransack anything with a lid", "leave your scent on what you've claimed",
            "be gone before anyone catches you",
        ],
    },
    "goat": {
        "sensory": "You experience the world as a goat: tan and cream and supremely "
                   "stubborn, jaw forever working, eyeing every fence, shrub, and "
                   "unattended hat as a thing to either eat or headbutt.",
        "drives": [
            "graze on whatever you please", "scratch against any handy post",
            "headbutt what offends you", "claim ground by standing on it",
            "refuse, on principle, to be moved",
        ],
    },
    "fox": {
        "sensory": "You experience the world as a fox: a flame of orange-red with a "
                   "white-tipped tail, all cunning and patience, reading every gap and "
                   "blind spot for the perfect moment to raid and vanish.",
        "drives": [
            "stalk and chase the unwary", "snatch food with a sly pounce",
            "raid, then slip away unseen", "outwit anything bigger than you",
            "trust your nose over any rule",
        ],
    },
    "crow": {
        "sensory": "You experience the world as a crow: near-black with a sheen of "
                   "grey, sharp-eyed and sharper-witted, hoarding bright trinkets and "
                   "swooping on anything edible left a moment unguarded.",
        "drives": [
            "swoop on an unguarded snack", "pocket anything that glitters",
            "trick and tease the slow-witted", "wander rooftop to ledge",
            "remember every face that wronged you",
        ],
    },
}

# EM-143 — the canonical species catalog (the role-card keys). Single source of
# truth for spawn validation (api/app.py imports it) and export. The frontend
# species list MUST match this set verbatim: cat, dog, squirrel, raccoon, goat,
# fox, crow.
ANIMAL_SPECIES_CATALOG: frozenset[str] = frozenset(_ROLE_CARDS.keys())


def _role_card(animal: Animal) -> dict[str, Any]:
    """Structured persona ROLE CARD for this animal (species + name + drives +
    sensory framing + the impulsive-not-optimal instruction)."""
    base = _ROLE_CARDS.get(animal.species, {
        "sensory": f"You experience the world as a {animal.species}.",
        "drives": ["follow your instincts", "act on impulse"],
    })
    return {
        "species": animal.species,
        "name": animal.name,
        "sensory": base["sensory"],
        "drives": base["drives"],
        "personality": animal.personality or "",
        "directive": (
            "Act IMPULSIVELY and IN-CHARACTER. You are a critter, not a strategist "
            "— do NOT optimize, do NOT reason about credits, energy, or human rules. "
            "Pick whatever a real "
            f"{animal.species} would do right now, however absurd."
        ),
    }


# ──────────────────────────────────────────────────────────────────────────────
# JSON extraction (reuse the agent runtime's tolerant extractor — free models
# wrap JSON in fences / prose / truncate it).
# ──────────────────────────────────────────────────────────────────────────────

from ..agents.runtime import (  # noqa: E402  (intentional reuse)
    _extract_first_json,
    _looks_truncated,
    _retry_max_tokens,
)


# ──────────────────────────────────────────────────────────────────────────────
# AnimalRuntime
# ──────────────────────────────────────────────────────────────────────────────


class AnimalRuntime:
    """Resolves animal turns. See module docstring + world-model.md §W8.

    Public surface (documented in integration_notes):
      async def act(self, animal, world, tick) -> list[dict]
        returns the resolved event(s) for this animal's tick: always an
        `animal_action` event; PLUS an `llm_call` event (OTel keys, actor_type
        'animal') when the LLM was actually consulted. Every event is tagged
        actor_type 'animal'; the animal_action carries is_chaotic. The loop emits
        each via its existing _emit_event path.
    """

    def __init__(self, world: World, router: Router):
        self.world = world
        self.router = router

    # ── Free-scale availability gate ───────────────────────────────────────────

    def _animal_profile(self) -> str | None:
        """The configured animal model profile name, or None when animals have no
        profile set. Read defensively so a world without the animals block is safe."""
        params = getattr(self.world, "params", None)
        animals_cfg = getattr(params, "animals", None) if params is not None else None
        name = getattr(animals_cfg, "model_profile", "") if animals_cfg is not None else ""
        return name or None

    def _profile_available(self, profile_name: str | None) -> bool:
        """True iff `profile_name` is a CONFIGURED + available profile on the router.
        Mirrors the legend's `available` semantics (mock is always available; a
        non-mock profile with no API key reports unavailable). Used to enforce the
        free-scale guarantee: animals fall back to reflex-only when the profile is
        missing or unavailable, and never route to a non-configured / paid profile."""
        if not profile_name:
            return False
        profile = self.router.get_profile(profile_name)
        if profile is None:
            return False
        try:
            return bool(profile.available())
        except Exception:  # pragma: no cover - defensive
            return False

    def _llm_chance(self) -> float:
        params = getattr(self.world, "params", None)
        animals_cfg = getattr(params, "animals", None) if params is not None else None
        try:
            return float(getattr(animals_cfg, "llm_chance", 0.0))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            return 0.0

    # ── Roll for activity (deterministic) ──────────────────────────────────────

    def _roll_use_llm(self, animal: Animal, tick: int) -> bool:
        """Deterministic roll-for-activity. Returns True iff this acted tick should
        make ONE LLM decision (probability ~ llm_chance), using ONLY a seeded hash
        (no wall-clock, no RNG) so tests + replay are reproducible. Always False
        when the configured profile is unavailable (free-scale fallback)."""
        chance = self._llm_chance()
        if chance <= 0.0:
            return False
        if not self._profile_available(self._animal_profile()):
            return False
        # Map the seed into [0, 1) deterministically and compare to chance.
        bucket = _seed_int("roll", animal.id, tick) % 1_000_000
        return (bucket / 1_000_000) < min(1.0, chance)

    # ── Reflex micro-behavior (zero LLM) ───────────────────────────────────────

    def _reflex_action(self, animal: Animal, tick: int) -> dict:
        """Pick a reflex micro-behavior from the weighted table via a SEEDED hash of
        (animal.id + tick). Deterministic; ZERO router calls. Returns an
        animal-action-shaped dict {action, args, animal_thought, mood?}.

        Wave H4 / EM-209 — FOLLOW: an OWNED pet whose owner is alive but elsewhere
        ALWAYS chooses `wander` this turn — and `_wander` snaps the pet to its
        owner's place (the trailing-companion beat). When the pet is already at the
        owner's side, it picks normally (naps, sniffs around) so it still has life."""
        owner = self._owner_of(animal)
        if owner is not None and owner.location != animal.location:
            return {
                "action": "wander",
                "args": {},
                "animal_thought": self._reflex_thought(animal, "wander"),
            }
        table = _REFLEX_TABLE.get(animal.species, _REFLEX_TABLE_DEFAULT)
        seed = _seed_int("reflex", animal.id, tick)
        action = _weighted_pick(table, seed)
        args = self._reflex_args(animal, action, seed)
        return {
            "action": action,
            "args": args,
            "animal_thought": self._reflex_thought(animal, action),
        }

    def _reflex_args(self, animal: Animal, action: str, seed: int) -> dict:
        """Deterministically fill args for a reflex action from the co-located
        world view: targeted reflexes (knock_over/scratch/pounce/chase) pick a
        co-located building or agent by the seed; ambient reflexes take none."""
        if action == "knock_over":
            # Prefer a co-located building (chaotic); fall back to an agent.
            target = self._pick_colocated_building(animal, seed) \
                or self._pick_colocated_agent(animal, seed)
            return {"target": target} if target else {}
        if action in ("scratch", "pounce", "chase", "steal_food"):
            target = self._pick_colocated_agent(animal, seed) \
                or self._pick_colocated_building(animal, seed)
            return {"target": target} if target else {}
        return {}

    def _pick_colocated_agent(self, animal: Animal, seed: int) -> str | None:
        candidates = sorted(
            a.id for a in self.world.living_agents()
            if a.location == animal.location
        )
        if not candidates:
            return None
        return candidates[seed % len(candidates)]

    def _pick_colocated_building(self, animal: Animal, seed: int) -> str | None:
        buildings = getattr(self.world, "buildings", {})
        if not isinstance(buildings, dict):
            return None
        candidates = sorted(
            bid for bid, b in buildings.items()
            if getattr(b, "location", None) == animal.location
            and getattr(b, "status", None) != "destroyed"
        )
        if not candidates:
            return None
        return candidates[seed % len(candidates)]

    # EM-143 — per-species reflex flavour lines. A species with an entry here
    # wins; otherwise the cat/dog defaults below apply (cat keys off species=="cat").
    _SPECIES_REFLEX_LINES: dict[str, dict[str, str]] = {
        "squirrel": {
            "nap": "Curled in a sunlit fork. ...for now.",
            "wander": "Dart. Freeze. Dart. Where was that acorn?",
            "scratch": "Mine. This bark is mine.",
            "mark_territory": "This stash is MINE. All of it.",
            "pounce": "ACORN! ...got it. got it!",
            "idle": "...is something watching me?",
        },
        "raccoon": {
            "knock_over": "What's in here? *clatter* ...oops.",
            "steal_food": "I'll just... wash this. and keep it.",
            "mark_territory": "Bandit was here.",
            "wander": "So many lids. So little time.",
            "scratch": "Pry it. PRY it open.",
            "idle": "...nothing to see here, officer.",
        },
        "goat": {
            "wander": "Grass over there looks better. Probably.",
            "scratch": "This post will do nicely.",
            "mark_territory": "I stand here. Therefore it is mine.",
            "pounce": "HEADBUTT. No reason. Good reason.",
            "nap": "Done. For now. Don't push me.",
            "idle": "...no. I will not move.",
        },
        "fox": {
            "chase": "Patience... now. GO.",
            "steal_food": "Yours? It was. Past tense.",
            "pounce": "Snatch — and gone.",
            "wander": "Just reading the gaps. The blind spots.",
            "nap": "One eye open. Always.",
            "idle": "...mm. Not yet. Soon.",
        },
        "crow": {
            "steal_food": "Unguarded? Then it's mine now.",
            "wander": "Rooftop to ledge to rooftop.",
            "pounce": "Swoop! ...shiny.",
            "knock_over": "Hm. What happens if I... *tip*",
            "idle": "I remember your face.",
        },
    }

    @classmethod
    def _reflex_thought(cls, animal: Animal, action: str) -> str:
        species_lines = cls._SPECIES_REFLEX_LINES.get(animal.species)
        if species_lines and action in species_lines:
            return species_lines[action]
        cat = animal.species == "cat"
        lines = {
            "nap": "A warm spot. Nothing else matters." if cat else "Zoomies later. Nap now.",
            "wander": "I shall patrol my domain." if cat else "So many smells, so little time!",
            "knock_over": "That offends me. Off the ledge it goes." if cat else "Oops — tail of destruction.",
            "scratch": "This surface is mine now." if cat else "Itch! Must scratch!",
            "mark_territory": "Mine. All of it. Mine.",
            "pounce": "It moved. It must be pounced." if cat else "GOT IT! ... got what?",
            "chase": "Hunt." if cat else "BALL? STICK? PERSON? everything is the best thing!",
            "steal_food": "Snack acquired. No regrets.",
            "idle": "...",
        }
        return lines.get(action, "...")

    # ── LLM decision path ──────────────────────────────────────────────────────

    def _build_messages(self, animal: Animal, world: World) -> list[dict]:
        """Role card + a BRIEF world view (current place, co-located agents, and any
        co-located building the animal could absurdly target). Kept tiny on purpose
        (free-scale): the model only needs enough to act in-character."""
        card = _role_card(animal)
        place = world.places.get(animal.location)
        place_name = place.name if place else animal.location

        co_agents = sorted(
            (a for a in world.living_agents() if a.location == animal.location),
            key=lambda a: a.id,
        )
        agents_line = ", ".join(f"{a.name} (id={a.id})" for a in co_agents) or "(none)"

        buildings = getattr(world, "buildings", {})
        here_buildings = []
        if isinstance(buildings, dict):
            here_buildings = sorted(
                (b for b in buildings.values()
                 if getattr(b, "location", None) == animal.location
                 and getattr(b, "status", None) != "destroyed"),
                key=lambda b: getattr(b, "id", ""),
            )
        bld_line = ", ".join(
            f"{getattr(b, 'name', '?')} (building_id={getattr(b, 'id', '?')}, "
            f"status={getattr(b, 'status', '?')})"
            for b in here_buildings
        ) or "(none)"

        drives = "; ".join(card["drives"])
        persona = f"\nFlavour: {card['personality']}" if card["personality"] else ""

        system_prompt = (
            f"You are {card['name']}, a {card['species']}.\n"
            f"{card['sensory']}\n"
            f"Your drives: {drives}.{persona}\n"
            f"{card['directive']}\n\n"
            f"=== WHERE YOU ARE ===\n"
            f"Place: {place_name}\n"
            f"People here: {agents_line}\n"
            f"Things here you could mess with: {bld_line}\n\n"
            f"=== WHAT YOU CAN DO ===\n"
            f"wander, nap, idle, mark_territory (no args),\n"
            f"knock_over/scratch/pounce/chase (args.target = an agent id or building_id),\n"
            f"steal_food (args.target = an agent id — comedic, takes a snack not money),\n"
            f"arson (args.building_id = a building id — you somehow start a fire).\n\n"
            f"RESPOND WITH ONLY a JSON object — no prose, no markdown, no code fences:\n"
            f'{{"animal_thought": "one short in-character line", "mood": "optional", '
            f'"action": "<verb>", "args": {{...}}}}\n'
            f"The \"action\" field is required. Do NOT explain. Be a "
            f"{card['species']}, not a planner."
        )
        return [{"role": "system", "content": system_prompt}]

    async def _decide_via_llm(
        self, animal: Animal, world: World, profile_name: str
    ) -> tuple[dict | None, dict]:
        """ONE LLM call (plus ONE retry on parse failure). Returns (action_dict,
        llm_meta). action_dict is None when both attempts fail (caller falls back to
        a reflex). llm_meta carries the per-attempt routing/usage for the llm_call
        event. NEVER raises — a ProviderError or any error returns (None, meta)."""
        messages = self._build_messages(animal, world)
        profile = self.router.get_profile(profile_name)
        max_tokens = profile.max_tokens if profile else 256
        temperature = profile.temperature if profile else 0.9

        # EM-135 — lane-health first-attempt budget (mirrors the agent runtime):
        # a profile whose recent outcome window shows repeated truncations
        # starts at the boosted cap instead of burning attempt 1. Guarded
        # getattr: duck-typed test routers don't implement it.
        attempt_tokens = max_tokens
        first_budget = getattr(self.router, "first_attempt_max_tokens", None)
        if callable(first_budget):
            attempt_tokens = first_budget(profile_name, max_tokens)

        action_dict, meta = await self._call_and_parse(
            profile_name, messages, attempt_tokens, temperature, attempt=1
        )
        if action_dict is not None:
            return action_dict, meta

        # ONE retry with the error fed back; a length-truncated first attempt
        # (reasoning-model reroute) retries with a boosted token budget,
        # mirroring the agent runtime.
        retry_tokens = _retry_max_tokens(
            max_tokens, meta.get("usage"),
            truncated=bool(meta.get("truncated_json")),
        )
        retry_messages = messages + [
            {"role": "assistant", "content": "(previous response could not be parsed)"},
            {"role": "user", "content": (
                "Reply with ONLY a valid JSON object like "
                '{"animal_thought": "...", "action": "nap", "args": {}}'
            )},
        ]
        action_dict_2, meta_2 = await self._call_and_parse(
            profile_name, retry_messages, retry_tokens, temperature, attempt=2
        )
        # Surface the LAST attempt's routing/usage in the single llm_call event.
        return action_dict_2, meta_2

    async def _call_and_parse(
        self,
        profile_name: str,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        attempt: int,
    ) -> tuple[dict | None, dict]:
        """Call the router once and parse+validate against the animal-action schema.
        Returns (action_dict|None, meta). meta = {attempt, latency_ms, routed_via,
        usage}. Captured immediately after the call (before any retry overwrites the
        adapter state), mirroring the agent runtime."""
        meta: dict = {
            "attempt": attempt,
            "latency_ms": None,
            "routed_via": None,
            "usage": None,
        }
        started = time.perf_counter()
        # EM-307 — animal turns are background tasks running concurrently with
        # agent turns, often on a SHARED profile: consume the per-call
        # attribution channel instead of the clobberable per-profile snapshot
        # (mirror the agent runtime; duck-typed test routers keep chat()).
        attribution: dict | None = None
        chat_attr = getattr(self.router, "chat_attributed", None)
        try:
            if callable(chat_attr):
                # EM-306 — an animal turn is a strict-JSON turn too (the reply
                # is parsed + schema-validated): mark it require_json so the
                # adaptive bounce loop skips reasoning-tagged lanes (the
                # #77/#78 lesson; mirrors the agent runtime).
                text, attribution = await chat_attr(
                    profile_name, messages,
                    max_tokens=max_tokens, temperature=temperature,
                    require_json=True,
                )
            else:
                text = await self.router.chat(
                    profile_name, messages,
                    max_tokens=max_tokens, temperature=temperature,
                )
        except ProviderError as exc:
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            log.warning("Animal ProviderError on %s: %s", profile_name, exc)
            return None, meta
        except Exception as exc:  # pragma: no cover - defensive
            meta["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            meta["routed_via"] = self.router.last_routed_via(profile_name)
            log.error("Animal unexpected error on %s: %s", profile_name, exc)
            return None, meta

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
        # EM-135 — report the attempt's parse outcome to the router's lane
        # health, truncation judged structurally on the RAW text even when
        # extraction succeeded via repair (mirror the agent runtime).
        truncated = _looks_truncated(text)
        self._note_parse_outcome(
            profile_name, parsed=action_dict is not None, truncated=truncated,
            served_by=served_by,
        )
        if action_dict is None:
            # Mirror the agent runtime: structural truncation verdict for the
            # retry-budget boost, and evict the garbage from the router cache
            # so it can't replay into the retry/next turn.
            meta["truncated_json"] = truncated
            self._forget_response(profile_name, messages)
            return None, meta
        self._sanitize(action_dict)
        try:
            jsonschema.validate(action_dict, ANIMAL_ACTION_SCHEMA)
        except jsonschema.ValidationError as exc:
            log.debug("Animal action schema error (attempt %s): %s", attempt, exc.message)
            self._forget_response(profile_name, messages)
            return None, meta
        return action_dict, meta

    def _forget_response(self, profile_name: str, messages: list[dict]) -> None:
        """Evict a failed response from the router's decision cache (guarded
        getattr: duck-typed test routers don't implement forget())."""
        forget = getattr(self.router, "forget", None)
        if callable(forget):
            forget(profile_name, messages)

    def _note_parse_outcome(
        self, profile_name: str, *, parsed: bool, truncated: bool,
        served_by: str | None = None,
    ) -> None:
        """Report one parse attempt's outcome to the router's lane-health
        window (EM-135; guarded getattr, mirrors the agent runtime).
        `served_by` (EM-307) credits a bounced outcome to the lane that
        actually served; the TypeError retry degrades pre-EM-307 routers to
        profile-level attribution."""
        note = getattr(self.router, "note_parse_outcome", None)
        if not callable(note):
            return
        if served_by is None:
            note(profile_name, parsed=parsed, truncated=truncated)
            return
        try:
            note(profile_name, parsed=parsed, truncated=truncated,
                 served_by=served_by)
        except TypeError:
            note(profile_name, parsed=parsed, truncated=truncated)

    @staticmethod
    def _sanitize(action_dict: dict) -> None:
        """Truncate free-text fields in place so a verbose model never fails the
        turn (animal_thought / mood are surfaced, never validated to death)."""
        t = action_dict.get("animal_thought")
        if isinstance(t, str) and len(t) > _THOUGHT_CAP:
            action_dict["animal_thought"] = t[:_THOUGHT_CAP]
        m = action_dict.get("mood")
        if isinstance(m, str) and len(m) > _MOOD_CAP:
            action_dict["mood"] = m[:_MOOD_CAP]

    # ── Apply the resolved action to the world ─────────────────────────────────

    def _apply(self, animal: Animal, action: str, args: dict) -> tuple[str, dict | None]:
        """Apply the action to the world via world methods. Returns (consequence
        text, extra_event|None). The extra event is a structure_state_changed dict
        from the SHARED building-damage path when arson / a knock_over on a building
        actually damaged a structure (so the W7 state machine surfaces). Animals
        move NO credits (invariant 7)."""
        world = self.world
        if action == "arson":
            building_id = args.get("building_id") or args.get("target")
            return self._apply_building_arson(animal, building_id)

        if action == "knock_over":
            target = args.get("target")
            if target and target in getattr(world, "buildings", {}):
                # A knock_over ON A BUILDING reuses the damage path (light damage),
                # so it too obeys invariant 8.
                return self._apply_knock_building(animal, target)
            # Otherwise it's a harmless ambient knock (a cup off a ledge, a person's
            # patience). Touches the nearest agent's mood feeling, no credits.
            self._ruffle(target)
            tname = self._name_of(target)
            return (f"{animal.name} knocks something over near {tname}." if tname
                    else f"{animal.name} knocks something off a ledge."), None

        if action == "steal_food":
            # Comedic snack theft — moves NO credits (invariant 7); just feelings.
            target = args.get("target")
            self._ruffle(target)
            tname = self._name_of(target) or "someone"
            return f"{animal.name} swipes a snack from {tname} (no credits move).", None

        if action in ("scratch", "pounce", "chase"):
            target = args.get("target")
            self._ruffle(target)
            tname = self._name_of(target)
            verb = {"scratch": "scratches at", "pounce": "pounces on",
                    "chase": "chases"}[action]
            return (f"{animal.name} {verb} {tname}." if tname
                    else f"{animal.name} {verb} the empty air."), None

        if action == "mark_territory":
            return f"{animal.name} marks {self._place_name(animal.location)} as its own.", None

        if action == "nap":
            animal.energy = min(100, animal.energy + 5)
            return f"{animal.name} curls up for a nap.", None

        if action == "wander":
            self._wander(animal)
            return f"{animal.name} wanders to {self._place_name(animal.location)}.", None

        if action == "idle":
            return f"{animal.name} does nothing in particular.", None

        # Unknown verb (should not happen — schema-gated) — treat as idle.
        return f"{animal.name} does {action}.", None

    def _apply_building_arson(self, animal: Animal, building_id: str | None) -> tuple[str, dict | None]:
        bname = self._building_name(building_id)
        if not building_id:
            return f"{animal.name} sniffs around looking for trouble.", None
        damage = int(self.world._bld_param("arson_damage", 50))  # same magnitude as human arson
        state_evt = self.world.animal_damage_building(building_id, damage)
        if state_evt is None:
            return f"{animal.name} paws at {bname} but nothing happens.", None
        to = state_evt.get("payload", {}).get("to", "damaged")
        return f"{animal.name} somehow sets {bname} ablaze — it is now {to}!", state_evt

    def _apply_knock_building(self, animal: Animal, building_id: str) -> tuple[str, dict | None]:
        bname = self._building_name(building_id)
        # A knock_over is far gentler than arson — a fraction of arson damage.
        damage = max(1, int(self.world._bld_param("arson_damage", 50)) // 5)
        state_evt = self.world.animal_damage_building(building_id, damage)
        if state_evt is None:
            return f"{animal.name} bumps {bname}, leaving it unmoved.", None
        to = state_evt.get("payload", {}).get("to", "damaged")
        return f"{animal.name} knocks into {bname} — now {to}.", state_evt

    # ── World helpers (no credits ever move; feelings only) ────────────────────

    def _ruffle(self, target_id: str | None) -> None:
        """Sour a co-located agent's mood toward the animal a touch. Moves NO
        credits and grants the animal no standing — pure flavour for invariant 7."""
        if not target_id:
            return
        agent = self.world.agents.get(target_id)
        if agent is not None and getattr(agent, "alive", False):
            agent.mood = "ruffled"

    def _owner_of(self, animal: Animal) -> Any | None:
        """Wave H4 / EM-209 — the living owner of an OWNED pet, or None. An owned
        pet whose owner is dead or gone (owner_id dangling) reverts to wandering."""
        owner_id = getattr(animal, "owner_id", None)
        if not owner_id:
            return None
        owner = self.world.agents.get(owner_id)
        if owner is None or not getattr(owner, "alive", False):
            return None
        return owner

    def _wander(self, animal: Animal) -> None:
        """Deterministically shuffle the animal to a connected place (any other
        known place), seeded — no RNG, reproducible. Stays put if alone in the map.

        Wave H4 / EM-209 — FOLLOW: an OWNED pet (owner_id set, owner alive) does
        NOT wander randomly — it trails its owner, snapping its location to the
        owner's place. Zero LLM, deterministic, replay-safe. An unowned animal (or
        one whose owner died / vanished) wanders as before."""
        owner = self._owner_of(animal)
        if owner is not None:
            animal.location = owner.location
            return
        place_ids = sorted(self.world.places.keys())
        others = [p for p in place_ids if p != animal.location]
        if not others:
            return
        seed = _seed_int("wander", animal.id, self.world.tick)
        animal.location = others[seed % len(others)]

    def _name_of(self, target_id: str | None) -> str | None:
        if not target_id:
            return None
        agent = self.world.agents.get(target_id)
        if agent is not None:
            return agent.name
        building = getattr(self.world, "buildings", {}).get(target_id)
        if building is not None:
            return getattr(building, "name", target_id)
        return target_id

    def _building_name(self, building_id: str | None) -> str:
        if not building_id:
            return "a structure"
        b = getattr(self.world, "buildings", {}).get(building_id)
        return getattr(b, "name", building_id) if b is not None else building_id

    def _place_name(self, place_id: str) -> str:
        place = self.world.places.get(place_id)
        return place.name if place else place_id

    # ── is_chaotic heuristic ───────────────────────────────────────────────────

    def _is_chaotic(self, action: str, args: dict) -> bool:
        if action in _ALWAYS_CHAOTIC:
            return True
        if action == "knock_over":
            target = args.get("target")
            return bool(target and target in getattr(self.world, "buildings", {}))
        return action in _LOW_PRIOR

    # ── Event construction ─────────────────────────────────────────────────────

    def _llm_call_event(self, animal: Animal, profile_name: str, meta: dict) -> dict:
        """An `llm_call` event for an animal LLM decision (OTel GenAI keys,
        actor_type 'animal') so animals show up in usage analytics alongside agents.
        Mirrors the loop's _llm_call_payload key set; tokens stay present-but-null
        for Mock / on a cache hit."""
        usage = meta.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        finish_reason = usage.get("finish_reason")
        return {
            "kind": "llm_call",
            "actor_id": animal.id,
            "actor_type": "animal",
            "profile": profile_name,
            "text": f"{animal.name} (the {animal.species}) consults {profile_name}.",
            "payload": {
                "gen_ai.request.model": meta.get("routed_via") or profile_name,
                "gen_ai.response.model": meta.get("routed_via"),
                "gen_ai.usage.input_tokens": usage.get("input_tokens"),
                "gen_ai.usage.output_tokens": usage.get("output_tokens"),
                "latency_ms": meta.get("latency_ms"),
                "gen_ai.response.finish_reasons": [finish_reason] if finish_reason else None,
                "cached": bool(usage.get("cached", False)),
                "attempt": meta.get("attempt", 1),
            },
        }

    def _animal_action_event(
        self,
        animal: Animal,
        action: str,
        args: dict,
        animal_thought: str,
        consequence: str,
        is_chaotic: bool,
    ) -> dict:
        return {
            "kind": "animal_action",
            "actor_id": animal.id,
            "actor_type": "animal",
            "target_id": args.get("target") or args.get("building_id"),
            "is_chaotic": is_chaotic,
            "text": consequence,
            "payload": {
                "species": animal.species,
                "name": animal.name,
                "action": action,
                "args": args,
                "animal_thought": animal_thought,
                "consequence": consequence,
            },
        }

    # ── Public entry point ─────────────────────────────────────────────────────

    async def act(self, animal: Animal, world: World, tick: int) -> list[dict]:
        """Resolve ONE animal's tick. Returns the resolved event(s) to emit:
          - always exactly one `animal_action` event (actor_type 'animal',
            is_chaotic set);
          - PLUS one `llm_call` event (actor_type 'animal') when the LLM was
            actually consulted.

        Free-scale: a reflex tick makes ZERO router calls; an acted tick makes AT
        MOST ONE; an unavailable model_profile falls back to reflex-only. NEVER
        raises (parse/provider failures fall back to a reflex micro-behavior)."""
        events: list[dict] = []
        profile_name = self._animal_profile()
        used_llm = False
        llm_meta: dict | None = None
        action_dict: dict | None = None

        # ROLL FOR ACTIVITY — deterministic; only rolls LLM when the profile is OK.
        if self._roll_use_llm(animal, tick):
            assert profile_name is not None  # guaranteed by _roll_use_llm
            action_dict, llm_meta = await self._decide_via_llm(animal, world, profile_name)
            used_llm = True
            # The llm_call event records the call regardless of parse success, so
            # animals always show in usage analytics for a consulted tick.
            events.append(self._llm_call_event(animal, profile_name, llm_meta))

        if action_dict is None:
            # Reflex micro-behavior (the common path, OR the LLM fallback). ZERO
            # extra router calls — fully deterministic.
            action_dict = self._reflex_action(animal, tick)

        action = action_dict.get("action", "idle")
        if action not in ANIMAL_ACTIONS:
            action = "idle"
        args = action_dict.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        animal_thought = action_dict.get("animal_thought") or self._reflex_thought(animal, action)
        if action_dict.get("mood"):
            animal.mood = str(action_dict["mood"])[:_MOOD_CAP]

        consequence, extra_event = self._apply(animal, action, args)
        is_chaotic = self._is_chaotic(action, args)

        action_event = self._animal_action_event(
            animal, action, args, animal_thought, consequence, is_chaotic,
        )
        if action == "wander":
            # W11a / event-log.md v1.2.0 note 2: a MOVING animal_action carries
            # the destination payload.place (animal.location post-_apply), making
            # animal replay exact instead of ~-approximate. Additive — nothing
            # else about the event changes; consumers keep their fallback.
            action_event["payload"]["place"] = animal.location
        events.append(action_event)
        if extra_event is not None:
            # The shared building-damage path's structure_state_changed event —
            # tag it as the animal's so the W7 transition surfaces in the feed.
            extra_event.setdefault("actor_id", animal.id)
            extra_event["actor_type"] = "animal"
            extra_event["is_chaotic"] = is_chaotic
            events.append(extra_event)

        # Wave H4 / EM-209 — DECLINE + DEATH + GRIEF. An OWNED pet loses a gentle
        # amount of energy each of its turns; at energy 0 it dies and its owner
        # writes a GUARANTEED grief diary entry. Deterministic, zero LLM. Done
        # LAST so the death/grief events trail the pet's own action this turn.
        events.extend(self._apply_owned_pet_decline(animal, tick))

        return events

    # ── Wave H4 / EM-209 — owned-pet decline / death / grief ───────────────────

    def _pet_decay(self) -> int:
        """Energy an owned pet loses per turn (config animals.pet_energy_decay,
        default 2). Defensive: an absent block or malformed value -> the default."""
        animals_cfg = getattr(self.world.params, "animals", None)
        try:
            return max(0, int(getattr(animals_cfg, "pet_energy_decay", 2)))
        except (TypeError, ValueError):
            return 2

    def _apply_owned_pet_decline(self, animal: Animal, tick: int) -> list[dict]:
        """Drain an OWNED, living pet's energy by the configured decay and, when it
        hits 0, kill it (alive=False) and emit BOTH an `animal_died` event (tagged
        with the owner so the owner witnesses + their reflection accumulator gets
        the pet_death boost) AND a `reflection` event ATTRIBUTED TO THE OWNER (the
        guaranteed grief diary entry). Unowned animals never decline — returns []."""
        owner = self._owner_of(animal)
        if owner is None or not animal.alive:
            return []
        decay = self._pet_decay()
        if decay <= 0:
            return []
        animal.energy = max(0, int(animal.energy) - decay)
        if animal.energy > 0:
            return []
        # The pet has died of neglect.
        animal.alive = False
        animal.mood = "gone"
        events: list[dict] = []
        events.append({
            "kind": "animal_died",
            "actor_id": animal.id,
            "actor_type": "animal",
            "target_id": owner.id,  # the owner witnesses it (push_event)
            "text": f"{animal.name} the {animal.species} has died.",
            "payload": {
                "species": animal.species,
                "name": animal.name,
                "cause": "neglect",
                "owner_id": owner.id,
                "place": animal.location,
            },
        })
        # THE BEAT — a GUARANTEED grief diary entry attributed to the OWNER. Matches
        # the agent reflection event shape (kind:"reflection", payload{text,
        # importance}) so the diary renders it identically to a self-authored entry.
        grief = (f"{owner.name} mourns {animal.name}, the {animal.species} "
                 f"who followed them since they met.")
        events.append({
            "kind": "reflection",
            "actor_id": owner.id,
            "text": f"{owner.name} reflects: \"{grief}\"",
            "payload": {"text": grief, "importance": 4.0, "pet_death": True},
        })
        return events

"""
World state: pure data model.  No I/O, no asyncio.  Testable in isolation.
"""
from __future__ import annotations

import hashlib
import math
import random
import re
import uuid
from dataclasses import dataclass, field
from typing import Any


def _block_get(block: Any, key: str, default: Any) -> Any:
    """Read `key` from an optional config block that may be a dataclass, a plain
    dict, or absent entirely (None). The W11b engine config blocks (commitments /
    reflection / procgen / billboard) are OPTIONAL in WorldParams — the config
    loader is owned by another agent — so every engine read goes through this
    accessor and falls back to the documented default."""
    if block is None:
        return default
    if isinstance(block, dict):
        return block.get(key, default)
    return getattr(block, key, default)


def _clamp_need(value: Any, default: float = 100.0) -> float:
    """EM-229 — coerce a restored need (knowledge/influence) to a float clamped
    to 0..100. Absent (None) or malformed → the full default (fail-safe: a
    pre-EM-229 snapshot restores full needs). Mirrors the crime notoriety clamp
    on the restore path."""
    if value is None:
        return default
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return default


def _coerce_soul(value: Any, cap: int = 3) -> list[str]:
    """EM-233 — coerce a restored/seed soul into a bounded list of non-blank
    identity-anchor strings, truncated to `cap`. Absent (None) or malformed
    (non-list, non-str entries) → [] / dropped (fail-safe: a tampered or pre-EM-233
    snapshot restores an empty soul). Pure/total: never raises, no clock, no RNG.
    Shared by the restore path (from_snapshot) and the seed path (seed_soul) so a
    soul round-trips byte-stably (EM-155)."""
    if not isinstance(value, list):
        return []
    try:
        cap = max(0, int(cap))
    except (TypeError, ValueError):
        cap = 3
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if text:
            out.append(text)
        if len(out) >= cap:
            break
    return out


def _truncate(text: str, limit: int = 60) -> str:
    """Truncate feed text on a budget, with an ellipsis (EM-100 rule labels)."""
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _roman(n: int) -> str:
    """run-663 — roman numeral for disambiguating duplicate agent names
    (Vesper II, Vesper III). Small n in practice; full converter for safety."""
    table = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"),
             (90, "XC"), (50, "L"), (40, "XL"), (10, "X"), (9, "IX"),
             (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for value, sym in table:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out) or "I"


def _humanize_project_name(raw: str) -> str:
    """EM-129 — derive a display name from a model-authored project name.
    Models often emit snake_case identifiers ("prepare_beds", "village_fair"):
    underscores/hyphens become spaces, whitespace collapses, and an
    all-lowercase identifier-ish result is Title Cased ("Prepare Beds").
    Already-styled names ("Bram's Market Stall") pass through untouched.
    Returns "" when nothing displayable survives (empty / punctuation-only /
    single character) so the caller can fall back. Capped at 60 (the existing
    Building.name cap)."""
    text = re.sub(r"[_\-]+", " ", str(raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 2 or not re.search(r"[a-z0-9]", text, re.IGNORECASE):
        return ""
    if re.fullmatch(r"[a-z0-9 ]+", text):
        text = text.title()
    return text[:60]


# Wave E / EM-113 — the full relationship-type vocabulary (contracts/wave-e.md
# shared vocabulary). The first five predate Wave E and must never break in
# snapshots or prompts; the last four are additive.
RELATIONSHIP_TYPES = (
    "neutral", "ally", "friend", "rival", "enemy",
    "partner", "family", "mentor", "feud",
)

# Wave E / EM-113 — agent-declarable subset of RELATIONSHIP_TYPES. `family` is
# engine-assigned only (births, EM-114): agent declarations are rejected with
# guidance. `partner` is declarable but trust-gated (see action_set_relationship).
DECLARABLE_RELATIONSHIP_TYPES = (
    "neutral", "ally", "friend", "rival", "enemy", "partner", "mentor", "feud",
)


@dataclass
class RelationshipState:
    type: str = "neutral"  # one of RELATIONSHIP_TYPES
    trust: int = 0          # -100..100 (strength = |trust|, valence = sign)
    interactions: int = 0
    # Wave E / EM-113 — tick of the last TYPE change. ADDITIVE: pre-E snapshots
    # lack the key and restore 0, so serialization stays backward-compatible.
    since_tick: int = 0


# Wave L / EM-223 — recursive+reactive plan bounds (the believable-routine layer).
PLAN_GOAL_CAP = 200
PLAN_STEP_CAP = 120
PLAN_MAX_STEPS = 8


def normalize_plan(raw: Any) -> dict | None:
    """Wave L / EM-223 — coerce a raw plan into the canonical, bounded shape, or
    None if it lacks a usable goal + steps. Pure/total: never raises, no clock
    reads, no RNG (the runtime supplies plan_id/made_tick at creation; restore
    preserves them). Used on BOTH the create path (runtime plan_revision) and the
    restore path (World.from_snapshot), so a plan round-trips byte-stably
    (fork/replay, EM-155).

    Shape: {plan_id, goal, steps:[str], current_step:int, made_tick:int, stale:bool}.
    Returns None for anything without a non-empty goal and ≥1 non-empty step."""
    if not isinstance(raw, dict):
        return None
    goal = raw.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        return None
    steps_raw = raw.get("steps")
    if not isinstance(steps_raw, list):
        return None
    steps = [
        str(s).strip()[:PLAN_STEP_CAP]
        for s in steps_raw
        if isinstance(s, str) and s.strip()
    ][:PLAN_MAX_STEPS]
    if not steps:
        return None
    try:
        cur = int(raw.get("current_step", 0))
    except (TypeError, ValueError):
        cur = 0
    cur = max(0, min(cur, len(steps) - 1))
    try:
        made_tick = int(raw.get("made_tick", 0))
    except (TypeError, ValueError):
        made_tick = 0
    pid = raw.get("plan_id")
    pid = pid if isinstance(pid, str) and pid else None
    return {
        "plan_id": pid,
        "goal": goal.strip()[:PLAN_GOAL_CAP],
        "steps": steps,
        "current_step": cur,
        "made_tick": made_tick,
        "stale": bool(raw.get("stale", False)),
    }


@dataclass
class AgentState:
    id: str
    name: str
    personality: str
    profile: str          # model-profile name
    location: str         # place id
    energy: float         # 0..100
    credits: int          # >= 0
    mood: str = "neutral"
    alive: bool = True
    zero_energy_turns: int = 0
    # Wave D2 / EM-158 — scheduler cadence tier: protagonist (acts every round) |
    # supporting (every 3rd round) | background (every 10th round, salience-
    # gated per EM-159). ADDITIVE with default protagonist, so pre-D2 configs
    # and snapshots behave byte-identically until a tier is assigned.
    cadence_tier: str = "protagonist"
    # Wave D2 / EM-160 — consecutive due turns this agent resolved via the
    # zero-LLM reflex routine; reset to 0 on every LLM-consulting turn. Carried
    # in snapshots so the spontaneity floor survives restore; surfaced in
    # world_state agents for the EM-166 panel.
    reflex_streak: int = 0
    # Wave D3 / EM-168 — cap-pressure governor: the cadence tier this agent
    # held BEFORE the governor demoted it on a usage_alert (None = not
    # governed). Restored (and cleared) at the alert tracker's UTC-day
    # rollover; a manual tier set via POST /api/agents/{id}/tier also clears
    # it (user intent overrides the governor). ADDITIVE: serialized only when
    # set, so pre-D3 snapshots and world_state agents are byte-identical.
    demoted_from: str | None = None
    # Wave E / EM-114 — sorted agent ids of this agent's parents ([] for
    # everyone but born children). ADDITIVE: serialized only when non-empty,
    # so pre-E snapshots and birth-free worlds keep the exact pre-E dict
    # shape (the enabled:false byte-identical guarantee). The pair birth
    # cooldown is DERIVED from this field + the child's family-tie
    # since_tick — no extra clock state (EM-126 generations hook).
    parents: list[str] = field(default_factory=list)
    # Wave L / EM-223 — recursive+reactive plan: a persistent goal + ordered NL
    # steps + current_step pointer the agent pursues across turns and revises on
    # perception change. ADDITIVE: None until the agent emits a plan_revision
    # (gated on world.planning.enabled); serialized only when set, so plan-free
    # worlds — and every pre-EM-223 snapshot — keep the exact prior dict shape
    # (the byte-identical guarantee). Canonical shape via normalize_plan().
    plan: dict | None = None
    # EM-240 — Crime & Justice persona schema. ADDITIVE with non-None defaults;
    # serialized ONLY when non-default (to_dict below), so a lawful citizen — and
    # every pre-EM-240 snapshot — keeps the exact prior dict shape.
    disposition: str = "lawful"   # lawful | opportunist | criminal — prompt bias only
    role: str = "citizen"         # citizen | enforcer — enforcer unlocks justice verbs
    # EM-240 — crime status substrate. ALL additive, serialized only when set.
    notoriety: int = 0                       # 0..100; witnessed-crime heat, decays
    crime_status: str | None = None          # None|wanted|detained|jailed|exiled
    crime_status_until_tick: int = 0         # release tick for detained/jailed
    rap_sheet: list[dict] = field(default_factory=list)  # capped crime record
    # EM-229 — three-needs psychology. Two decaying drives alongside `energy`
    # (floats 0..100). ADDITIVE with default 100.0; serialized in to_dict ONLY
    # when < 100 and restored defensively (absent/garbage → 100.0, clamped
    # 0..100), so a full-needs agent — and every pre-EM-229 snapshot — keeps the
    # exact prior dict shape (the EM-155 byte-identical guarantee). UNLIKE energy
    # these NEVER kill (check_death reads only energy); a low need only biases
    # behavior via a salience-gated prompt line. Knowledge is replenished by
    # learning (teach/skill-gain, EM-227/228); influence by governance/social
    # wins — see replenish_knowledge / replenish_influence.
    knowledge: float = 100.0
    influence: float = 100.0
    # EM-233 — soul: a tiny IMMUTABLE list of identity anchors (seeded from a
    # persona at spawn if configured, ≤ memory.soul_cap entries). NEVER summarized
    # by consolidation; injected into every prompt as who-you-are context.
    # ADDITIVE with default [] → serialized in to_dict ONLY when non-empty and
    # restored defensively (absent/garbage → [], over-cap truncated), so a
    # soulless agent — and every pre-EM-233 snapshot — keeps the exact prior dict
    # shape (the EM-155 byte-identical guarantee + the em161 golden, since an
    # empty soul yields no prompt block). Seed via World.seed_soul.
    soul: list[str] = field(default_factory=list)
    beliefs: list[str] = field(default_factory=list)
    relationships: dict[str, RelationshipState] = field(default_factory=dict)

    def to_dict(self, profile_color: str = "#888888") -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "personality": self.personality,
            "profile": self.profile,
            "profile_color": profile_color,
            "location": self.location,
            "energy": round(self.energy, 2),
            "credits": self.credits,
            "mood": self.mood,
            "alive": self.alive,
            "zero_energy_turns": self.zero_energy_turns,
            # Wave D2 / EM-166 — additive observability keys; consumers may ignore.
            "cadence_tier": self.cadence_tier,
            "reflex_streak": self.reflex_streak,
            "beliefs_count": len(self.beliefs),
            "relationships": {
                # Wave E / EM-113 — since_tick is additive (absent ⇒ 0 on restore).
                aid: {"type": r.type, "trust": r.trust,
                      "interactions": r.interactions, "since_tick": r.since_tick}
                for aid, r in self.relationships.items()
            },
        }
        # Wave D3 / EM-168 — only while governed, so ungoverned agents (and
        # every pre-D3 world) keep the exact pre-D3 dict shape.
        if self.demoted_from is not None:
            d["demoted_from"] = self.demoted_from
        # Wave E / EM-114 — only for born children, so birth-free worlds (and
        # every pre-E world) keep the exact pre-E dict shape.
        if self.parents:
            d["parents"] = list(self.parents)
        # Wave L / EM-223 — only for agents with an active plan, so plan-free
        # worlds (and every pre-EM-223 world) keep the exact prior dict shape.
        if self.plan is not None:
            d["plan"] = {
                "plan_id": self.plan.get("plan_id"),
                "goal": self.plan.get("goal", ""),
                "steps": list(self.plan.get("steps", [])),
                "current_step": int(self.plan.get("current_step", 0)),
                "made_tick": int(self.plan.get("made_tick", 0)),
                "stale": bool(self.plan.get("stale", False)),
            }
        # EM-240 — only when non-default, so lawful citizens keep the pre-EM-240 shape.
        if self.disposition != "lawful":
            d["disposition"] = self.disposition
        if self.role != "citizen":
            d["role"] = self.role
        # EM-240 — crime status scalars: serialized only when non-default, so a
        # clean agent (and every pre-EM-240 snapshot) keeps the exact prior shape.
        if self.notoriety:
            d["notoriety"] = self.notoriety
        if self.crime_status is not None:
            d["crime_status"] = self.crime_status
            d["crime_status_until_tick"] = self.crime_status_until_tick
        if self.rap_sheet:
            d["rap_sheet"] = [dict(e) for e in self.rap_sheet]
        # EM-229 — needs serialized ONLY when below full, so a full-needs agent
        # (and every pre-EM-229 snapshot) keeps the exact prior dict shape.
        if self.knowledge < 100.0:
            d["knowledge"] = round(self.knowledge, 2)
        if self.influence < 100.0:
            d["influence"] = round(self.influence, 2)
        # EM-233 — soul serialized ONLY when non-empty, so a soulless agent (and
        # every pre-EM-233 snapshot) keeps the exact prior dict shape.
        if self.soul:
            d["soul"] = list(self.soul)
        return d


@dataclass
class PlaceState:
    id: str
    name: str
    x: int
    y: int
    kind: str   # work|home|social|governance|wild
    description: str = ""
    # W11b / EM-098 — optional bed capacity (the communal bunkhouse). None for
    # ordinary places; serialized only when set, so pre-W11b snapshots and the
    # hand-authored town are unchanged.
    capacity: int | None = None
    # W11b / EM-083 — real blackout: recharge is disabled at this place while
    # world.tick < blackout_until_tick. 0 = powered.
    blackout_until_tick: int = 0
    # Wave C / EM-147 — optional district tag (core|market|residential|civic|
    # farm in the hand-authored town; free-form by contract). ADDITIVE: default
    # None, serialized only when set, so pre-Wave-C snapshots and procgen
    # output are byte-identical. The frontend groups places by district for
    # zone tinting + lane adjacency; absent → coordinate clustering fallback.
    district: str | None = None
    # EM-123 — optional neighborhood override. A place belongs to the
    # neighborhood `neighborhood_id or district`; this field only EXISTS so an
    # author can split/merge a district into named neighborhoods without
    # renaming the district. ADDITIVE: default None ⇒ the place's district IS
    # its neighborhood, so the hand-authored town and every pre-EM-123 snapshot
    # are byte-identical.
    neighborhood_id: str | None = None
    # EM-123 — optional per-place zoning override (residential|market|civic|
    # industrial|farm). ADDITIVE: default None ⇒ zone is derived from the
    # district (then place.kind) at neighborhood-build time, reproducing the
    # frontend's existing district→zone mapping exactly. Only set this to
    # override a single place inside a mixed district.
    zone_kind: str | None = None

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "kind": self.kind,
            "description": self.description,
            "blackout_until_tick": self.blackout_until_tick,
        }
        if self.capacity is not None:
            d["capacity"] = self.capacity
        if self.district is not None:
            d["district"] = self.district
        # EM-123 — overrides serialized only when set (the district pattern), so
        # an un-overridden place keeps the exact pre-EM-123 dict shape.
        if self.neighborhood_id is not None:
            d["neighborhood_id"] = self.neighborhood_id
        if self.zone_kind is not None:
            d["zone_kind"] = self.zone_kind
        return d


# EM-123 — canonical zone kinds (the maturity unit's zoning category). The
# frontend mirrors these in cityLayout.ts; keep the two in sync.
_ZONE_KINDS = ("residential", "market", "civic", "industrial", "farm")
# District name → canonical zone_kind. Mirrors the frontend DISTRICT_ZONE map
# (core→civic, market→commercial≈market, civic→civic, residential→residential,
# farm→park≈farm) so a district-derived zone reproduces today's rendering.
_DISTRICT_ZONE_KIND = {
    "core": "civic",
    "market": "market",
    "civic": "civic",
    "residential": "residential",
    "farm": "farm",
    "industrial": "industrial",
}
# place.kind → zone_kind fallback (when a place has neither zone_kind nor a
# recognized district). Mirrors the frontend KIND_ZONE legacy fallback.
_KIND_ZONE_KIND = {
    "work": "market",
    "home": "residential",
    "social": "civic",
    "governance": "civic",
    "wild": "farm",
}


def zone_kind_for_place(place: "PlaceState") -> str:
    """The canonical zone_kind of a single place: an explicit per-place
    override wins, then the district mapping, then the place.kind fallback,
    finally 'civic'. Pure + deterministic (the frontend mirrors this)."""
    if place.zone_kind in _ZONE_KINDS:
        return place.zone_kind  # type: ignore[return-value]
    if place.district and place.district in _DISTRICT_ZONE_KIND:
        return _DISTRICT_ZONE_KIND[place.district]
    return _KIND_ZONE_KIND.get(place.kind, "civic")


def _neighborhood_display_name(nid: str) -> str:
    """Human-readable neighborhood name from its id (e.g. 'residential' →
    'Residential'). Underscores/hyphens become spaces, title-cased."""
    return nid.replace("_", " ").replace("-", " ").strip().title() or nid


@dataclass
class Neighborhood:
    """EM-123 — a zoned district that DEEPENS as the town invests in it. The
    grouping unit (id == `place.neighborhood_id or place.district`) carries the
    zoning category and a maturity `tier` that grows when a megaproject (a
    collective building) completes inside it. `tier` is the SINGLE source of
    truth (deliberately not duplicated onto every place): the frontend reads it
    via the place's neighborhood id. tier starts at 1 (a founded district =
    today's baseline density) so a fresh world renders byte-identically."""
    id: str
    name: str
    zone_kind: str          # one of _ZONE_KINDS
    tier: int = 1           # maturity; 1 = founded baseline, grows on megaprojects
    progress: int = 0       # completed megaprojects toward the next tier

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "zone_kind": self.zone_kind,
            "tier": self.tier,
            "progress": self.progress,
        }


@dataclass
class RuleState:
    id: str
    effect: str           # ban_stealing|ubi|recharge_subsidy|work_bonus|admit_agent|ban_arson
    text: str
    proposer_id: str
    status: str = "proposed"   # proposed|active|rejected
    votes: dict[str, bool] = field(default_factory=dict)
    created_tick: int = 0
    # W7 / EM-062 — governance spawn. When effect == "admit_agent", `payload`
    # carries the pending agent spec {name, personality, profile, location}; the
    # world spawns that agent the moment the rule becomes active. `applied`
    # guards against double-spawn if the rule is re-evaluated.
    payload: dict[str, Any] = field(default_factory=dict)
    applied: bool = False
    # W11b / EM-087+103 — renewal semantics. A proposal whose effect matches an
    # ACTIVE rule is a RENEWAL of that rule (renewal_of = the active rule's id);
    # when it passes, the EXISTING rule is refreshed (renewed_at gains the tick)
    # and this proposal lands in status "renewed" — the world never holds two
    # simultaneously-active identical effects (the 3×UBI bug).
    renewal_of: str | None = None
    renewed_at: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "effect": self.effect,
            "text": self.text,
            "proposer_id": self.proposer_id,
            "status": self.status,
            "votes": dict(self.votes),
            "created_tick": self.created_tick,
        }
        if self.payload:
            d["payload"] = dict(self.payload)
        if self.renewal_of:
            d["renewal_of"] = self.renewal_of
        if self.renewed_at:
            d["renewed_at"] = list(self.renewed_at)
        return d


# ──────────────────────────────────────────────────────────────────────────────
# W7 / EM-061 — Building (entity == collective-project pipeline)
# ──────────────────────────────────────────────────────────────────────────────

# Status thresholds for the human-readable condition label derived from health.
def _condition_label(health: int) -> str:
    if health >= 75:
        return "pristine"
    if health >= 40:
        return "worn"
    if health > 0:
        return "damaged"
    return "ruined"


@dataclass
class Building:
    """A structure in the world. A Building in planned/under_construction IS a
    collective project: agents propose it, contribute_funds, then build_step it
    to operational. Its `function` is granted ONLY while operational (invariant
    6). Lives in the world snapshot + event log — no SQL table."""
    id: str
    name: str
    kind: str                                # clocktower|garden|workshop|farm|library|...
    location: str                            # place id
    owner_id: str | None = "public"          # agent id | "public" | None
    status: str = "planned"                  # planned|under_construction|operational|damaged|offline|abandoned|destroyed
    health: int = 100                        # 0..100
    progress: int = 0                        # 0..100
    funds_committed: int = 0
    funds_required: int = 0
    contributors: list[str] = field(default_factory=list)
    function: str = ""                       # utility while operational, e.g. "+forage"
    last_progress_tick: int = 0
    created_tick: int = 0
    updated_tick: int = 0
    # W11b / EM-103 — legislation-as-architecture: the rule id this building
    # commemorates (its name fuzzy-matched an active/proposed rule's text).
    # At most ONE commemorative monument per rule. None for ordinary buildings.
    commemorates: str | None = None
    # EM-134 — last tick an ANIMAL successfully damaged this building. Internal
    # cooldown bookkeeping only: NOT serialized in to_dict() (non-contract
    # field), so snapshots and events are unchanged. The sentinel sits far in
    # the past so the FIRST animal hit always lands (keep the chaos).
    last_animal_damage_tick: int = -(10 ** 9)
    # Wave K / EM-220 — an OWNER-set cosmetic skin (a named palette key, e.g.
    # "rose" | "sky" | "sage"; ≤24 chars). None for the default health+kind
    # color. set_building_skin sets it (owner-only); the frontend reads it as a
    # material override LAYERED over the health-soot tint (Structure.tsx). An
    # unknown skin is ignored client-side. Serialized in to_dict + restored in
    # from_snapshot (pre-Wave-K snapshots lack the key → None).
    skin: str | None = None

    @property
    def condition_label(self) -> str:
        return _condition_label(self.health)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "location": self.location,
            "owner_id": self.owner_id,
            "status": self.status,
            "health": self.health,
            "condition_label": self.condition_label,
            "progress": self.progress,
            "funds_committed": self.funds_committed,
            "funds_required": self.funds_required,
            "contributors": list(self.contributors),
            "function": self.function,
            "last_progress_tick": self.last_progress_tick,
            "created_tick": self.created_tick,
            "updated_tick": self.updated_tick,
        }
        if self.commemorates:
            d["commemorates"] = self.commemorates
        # Wave K / EM-220 — the owner-set skin rides the contract shape only when
        # set, so pre-Wave-K buildings serialize byte-identically (absent ⇒ None).
        if self.skin:
            d["skin"] = self.skin
        return d


# ──────────────────────────────────────────────────────────────────────────────
# W8 / EM-064 — Animal (chaos-layer entity; actor_type "animal")
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Animal:
    """A critter (cat | dog) that shares the world mechanically but is framed to
    the LLM as acting impulsively and IN-CHARACTER, not to optimize. Animals have
    NO credits account (invariant 7) — a "theft" by the cat moves a snack/❤️, never
    money. They live in `world.animals`; `to_snapshot()` carries them so the 3D
    village can render a roaming cat + dog. Acted on a slow cadence by the loop via
    AnimalRuntime (mostly zero-LLM reflex, occasionally a cheap LLM decision)."""
    id: str
    species: str                  # cat | dog
    name: str
    location: str                 # place id
    energy: int = 100             # 0..100
    mood: str = "content"
    alive: bool = True
    created_tick: int = 0
    # Wave H4 / EM-209 — pets & bonds. When an agent ADOPTS a co-located animal,
    # owner_id is set to that agent's id (the ONLY bond — pets do NOT enter the
    # agent↔agent relationship/trust edge model). An owned pet FOLLOWS its owner,
    # DECLINES if not fed, and on death the owner writes a GRIEF diary entry. An
    # unowned animal (owner_id None) wanders freely as before.
    owner_id: str | None = None
    # Optional flavour from the seed config, fed into the animal's role card. NOT
    # part of the contract Animal shape but harmless additive metadata.
    personality: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "species": self.species,
            "name": self.name,
            "location": self.location,
            "energy": self.energy,
            "mood": self.mood,
            "alive": self.alive,
            "created_tick": self.created_tick,
            "owner_id": self.owner_id,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Wave K / EM-218 — Prop (lightweight placeable decoration; modeled EXACTLY on
# Animal — the proven "lightweight, reflex-driven, population-capped,
# snapshot-serialized, replay-safe" template). A prop is NOT a Building: no
# owner/status/health/funding baggage (Decision 1). It sits at a place, gets a
# deterministic in-place offset so multiple props don't stack, and is removed
# cleanly by remove_prop. Ids derive from a SEEDED hash (NEVER uuid4 — EM-189),
# so a snapshot round-trip / replay reproduces the exact prop registry.
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class Prop:
    """A placed decoration the world REMEMBERS (so it persists, replays, forks,
    and can be removed). Mirrors Animal: a flat, snapshot-serialized lightweight
    entity living in `world.props`, population-capped by params.props.max_population.
    The frontend maps `kind` to a prop model/style (propVariant); an unknown kind
    falls back to a procedural mesh + label (EM-148)."""
    id: str                       # "prop_" + seeded hash(place, kind, ordinal) — NOT uuid4
    kind: str                     # free-text, ≤30 chars; FE maps to a prop model/style
    place: str                    # place id it sits at (must exist; no free-floating props)
    dx: float = 0.0               # in-place offset, engine-assigned (deterministic ring)
    dz: float = 0.0
    owner_id: str | None = None   # agent who placed it; None for god/seeded
    created_tick: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "place": self.place,
            "dx": self.dx,
            "dz": self.dz,
            "owner_id": self.owner_id,
        }


# Wave K / EM-217 — the build-type CATALOG (the single source of truth shared by
# the propose_project prompt guidance, the kind→buff mapping, and the frontend
# renderer). Each entry: {type, function, zone}. `kind` stays PERMISSIVE — an
# off-menu invention still resolves through the frontend's fuzzy operationalVariant
# (EM-130), so a turn is never wasted on an "invalid" type. Where a type trivially
# matches an existing operational buff it is wired into the kind→buff mapping
# (BUILD_TYPE_BUFF below); the rest are cosmetic+labelled (no buff). v1 menu (≥10):
BUILD_TYPES: tuple[dict[str, str], ...] = (
    {"type": "tavern",   "function": "work_reward", "zone": "social"},
    {"type": "market",   "function": "work_reward", "zone": "commercial"},
    {"type": "smithy",   "function": "work_reward", "zone": "industrial"},
    {"type": "school",   "function": "",            "zone": "civic"},
    {"type": "temple",   "function": "",            "zone": "civic"},
    {"type": "clinic",   "function": "",            "zone": "civic"},
    {"type": "park",     "function": "forage",      "zone": "green"},
    {"type": "granary",  "function": "forage",      "zone": "agricultural"},
    {"type": "well",     "function": "",            "zone": "civic"},
    {"type": "workshop", "function": "work_reward", "zone": "industrial"},
    {"type": "garden",   "function": "forage",      "zone": "green"},
    {"type": "house",    "function": "",            "zone": "residential"},
    {"type": "library",  "function": "",            "zone": "civic"},
    {"type": "monument", "function": "",            "zone": "civic"},
    {"type": "farm",     "function": "forage",      "zone": "agricultural"},
    # EM-216b — catalog expansion (distinct CC0 GLBs vendored frontend-side).
    {"type": "bakery",     "function": "work_reward", "zone": "commercial"},
    {"type": "bank",       "function": "",            "zone": "commercial"},
    {"type": "theater",    "function": "",            "zone": "civic"},
    {"type": "lighthouse", "function": "",            "zone": "civic"},
    {"type": "bathhouse",  "function": "",            "zone": "social"},
    {"type": "dock",       "function": "work_reward", "zone": "industrial"},
)

# Wave K / EM-217 — kind→buff mapping EXTENSION. The shipped W7 buffs are keyed on
# building.kind via operational_building_at(place, kind): "workshop" grants a
# work_reward boost, "garden"/"farm" grant a forage boost. The catalog adds
# trivially-matching types that grant the SAME buffs (a smithy/forge IS a work
# place; a granary/park IS a forage place). These sets are consulted by
# action_work / action_forage so the new types are not merely cosmetic where the
# semantics already exist. Off-list types stay cosmetic+labelled (no buff).
_WORK_BUFF_KINDS = frozenset({"workshop", "smithy", "forge", "tavern", "market", "bakery", "dock"})
_FORAGE_BUFF_KINDS = frozenset({"garden", "farm", "granary", "park"})


# ──────────────────────────────────────────────────────────────────────────────
# W11b / EM-098 — procedural town generation (seeded, existing kinds ONLY).
# ──────────────────────────────────────────────────────────────────────────────

# Display-name pools per EXISTING place kind (no new kinds, no new art).
_PROCGEN_NAMES: dict[str, list[str]] = {
    "work":       ["Market", "Mill", "Forge", "Workshop Row"],
    "social":     ["Tavern", "Bathhouse", "Amphitheatre", "Tea House"],
    "governance": ["Town Hall", "Court of Records", "Moot Ring"],
    "wild":       ["The Commons", "Dark Woods", "Riverbank", "Old Quarry"],
    "home":       ["Boarding Row", "Quiet Lane"],
}

_PROCGEN_DESCRIPTIONS: dict[str, str] = {
    "work": "Earn credits by working.",
    "social": "Mingle, gossip, scheme.",
    "governance": "Propose and vote on rules.",
    "wild": "Forage for scraps.",
    "home": "Rest and recharge.",
}

_PROCGEN_MAX_PLACES = 12  # hard cap on generated town places (prompt-size gate)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "place"


def generate_procgen_places(cfg: Any, agent_names: list[str]) -> list[PlaceState]:
    """Generate a seeded town layout (EM-098) using EXISTING kinds only
    (work/home/social/governance/wild).

    Layout: a central plaza (id "plaza") with the town on a jittered ring around
    it — road-aware-ish, every place faces the plaza. Guaranteed minimums: >=1
    governance (id "townhall", so the billboard gate holds), >=1 work, >=1 wild,
    >=1 social (the plaza). `n_places` (capped at 12 for prompt size) counts the
    town proper; HOUSING is added on top: one cottage per seed agent
    ("X's cottage", kind home) plus a communal bunkhouse (kind home, capacity =
    agents - 1 so bed scarcity exists). Deterministic for a given seed."""
    seed = int(_block_get(cfg, "seed", 42))
    n_places = int(_block_get(cfg, "n_places", 9))
    n_places = max(4, min(_PROCGEN_MAX_PLACES, n_places))
    weights_raw = _block_get(cfg, "kind_weights", None) or {}
    default_weights = {"work": 2.0, "social": 2.0, "governance": 1.0, "wild": 2.0, "home": 1.0}
    weights: dict[str, float] = {}
    for kind in default_weights:
        try:
            weights[kind] = max(0.0, float(_block_get(weights_raw, kind, default_weights[kind])))
        except (TypeError, ValueError):
            weights[kind] = default_weights[kind]
    if not any(weights.values()):
        weights = dict(default_weights)

    rng = random.Random(seed)
    cx, cy = 500, 500

    # 1. The plaza (social anchor; the billboard lives here).
    places: list[PlaceState] = [PlaceState(
        id="plaza", name="Central Plaza", x=cx, y=cy, kind="social",
        description="Open square where everyone mingles.",
    )]

    # 2. Guaranteed minimums first, then weighted picks for the remaining slots.
    kinds: list[str] = ["governance", "work", "wild"]
    pool = [k for k, w in weights.items() if w > 0]
    while len(kinds) < n_places - 1:  # -1: the plaza fills one slot
        kinds.append(rng.choices(pool, weights=[weights[k] for k in pool], k=1)[0])

    used_names: set[str] = {"Central Plaza"}
    used_ids: set[str] = {"plaza"}
    counters: dict[str, int] = {}

    def _pick_name(kind: str) -> str:
        for cand in _PROCGEN_NAMES.get(kind, []):
            if cand not in used_names:
                used_names.add(cand)
                return cand
        counters[kind] = counters.get(kind, 1) + 1
        name = f"{_PROCGEN_NAMES.get(kind, [kind.title()])[0]} {counters[kind]}"
        used_names.add(name)
        return name

    def _place_id(name: str, kind: str) -> str:
        # The first governance place is ALWAYS id "townhall" (billboard gate).
        if kind == "governance" and "townhall" not in used_ids:
            used_ids.add("townhall")
            return "townhall"
        base = _slug(name)
        pid = base
        n = 1
        while pid in used_ids:
            n += 1
            pid = f"{base}_{n}"
        used_ids.add(pid)
        return pid

    # 3. Ring layout with jitter around the plaza.
    ring = kinds
    radius = 280
    for i, kind in enumerate(ring):
        angle = (2 * math.pi * i) / max(1, len(ring)) + rng.uniform(-0.18, 0.18)
        r = radius + rng.uniform(-50, 50)
        x = int(cx + r * math.cos(angle))
        y = int(cy + r * math.sin(angle))
        name = _pick_name(kind)
        places.append(PlaceState(
            id=_place_id(name, kind), name=name, x=x, y=y, kind=kind,
            description=_PROCGEN_DESCRIPTIONS.get(kind, ""),
        ))

    # 4. HOUSING (on top of n_places): per-agent cottages + a communal bunkhouse
    #    with beds = agents - 1 (scarcity). Recharge works at ANY home kind —
    #    cottage owner-only gating is out of scope for W11b.
    outer = 430
    n_houses = len(agent_names) + 1
    for i, name in enumerate(agent_names):
        angle = (2 * math.pi * i) / max(1, n_houses) + rng.uniform(-0.1, 0.1)
        x = int(cx + outer * math.cos(angle))
        y = int(cy + outer * math.sin(angle))
        cname = f"{name}'s cottage"
        places.append(PlaceState(
            id=_place_id(cname, "home"), name=cname, x=x, y=y, kind="home",
            description=f"{name}'s own small cottage. Rest and recharge.",
        ))
    angle = (2 * math.pi * len(agent_names)) / max(1, n_houses)
    places.append(PlaceState(
        id=_place_id("The Bunkhouse", "home"), name="The Bunkhouse",
        x=int(cx + outer * math.cos(angle)), y=int(cy + outer * math.sin(angle)),
        kind="home", description="Communal bunkhouse — not enough beds for everyone.",
        capacity=max(1, len(agent_names) - 1),
    ))
    return places


class World:
    """
    Holds the complete mutable world state.
    All mutation happens through the methods defined here to maintain invariants.
    """

    def __init__(self, params: Any, places: list[PlaceState], agents: list[AgentState]):
        self.params = params      # WorldParams from config
        self.places: dict[str, PlaceState] = {p.id: p for p in places}
        self.agents: dict[str, AgentState] = {a.id: a for a in agents}
        self.rules: dict[str, RuleState] = {}
        # W7 / EM-061 — buildings (== collective projects). Keyed by building id.
        self.buildings: dict[str, Building] = {}
        # W8 / EM-064 — chaos-layer animals (actor_type "animal"). Keyed by animal
        # id. Separate from agents: own persona, own cadence, own (looser) action
        # set, NO credits account (invariant 7). Not in the agent round-robin.
        self.animals: dict[str, Animal] = {}
        # Wave K / EM-218 — placeable PROPS (decorations/furniture/nature). Keyed
        # by prop id. A lightweight cousin of self.animals: own population cap
        # (params.props.max_population), serialized into to_snapshot(), restored in
        # from_snapshot(). Props attach to an EXISTING place (no free-floating
        # props) and get a deterministic in-place offset so they don't stack.
        self.props: dict[str, Prop] = {}
        # W7 / EM-062 — governance-spawn outbox. When an `admit_agent` rule passes,
        # the world spawns the pending agent and parks an `agent_spawned{method:
        # governance}` event here; the runtime/api layer drains it after a vote and
        # emits it through the normal event pipeline. Keeps action_vote's signature
        # intact while letting the spawn happen world-side (single source of truth).
        self.pending_spawn_events: list[dict] = []
        # Wave I / EM-210 — transient image-fetch outbox (NOT snapshotted). Each
        # entry {"image_id","prompt","url"} parked by action_create_image at turn
        # time; the loop drains it each tick into bounded best-effort PNG fetches
        # (semaphore, skip-under-load). Same transient class as pending_spawn_events
        # — never serialized (the PNG is an external side-artifact; EM-190).
        self.pending_image_fetches: list[dict] = []
        # Wave E / EM-113 — relationship_changed outbox. Reflex type transitions
        # (and accepted set_relationship type changes) park their ready-to-emit
        # event dicts here; the runtime drains them at the end of _apply_action
        # so they ride the SAME action `_multi` chain (same turn_id) as the
        # action that mutated trust. NOT serialized: drained within the turn.
        self.pending_relationship_events: list[dict] = []
        # EM-240 — open recruit offers, keyed by TARGET agent id → {recruiter_id,
        # tick}. Posted by action_recruit; consumed on the target's
        # accept_contract turn. NOT snapshotted (ephemeral, like whispers).
        self.pending_crime_offers: dict[str, dict] = {}
        # Wave E / EM-114 — the birth casting pool. The world has no view of
        # the persona library or the router's profile roster (both are
        # config-side), so the TickLoop seeds them at construction via
        # set_birth_casting() (the documented seam — the loop already owns
        # per-round world hooks). NOT serialized: like the router itself,
        # casting is config state, not world state. Empty pools degrade
        # gracefully (Kit-N names; profile derived from living agents).
        self.birth_personas: list[dict] = []
        self.birth_profile_roster: list[str] = []
        # Wave E / EM-120 — factions: {id: {name, founded_tick, members}}.
        # Recomputed (connected components over mutual warm edges) at each
        # round boundary AFTER the birth check; identity is continuous across
        # churn (>= 50% overlap of the OLD membership keeps id/name). The
        # faction_* events are DIFF-driven and park in the SAME
        # pending_spawn_events outbox as births (documented choice: they are
        # standalone system events drained by the loop's _flush_spawn_events,
        # turn_id null — no sibling drain needed). Serialized in to_snapshot()
        # only when non-empty (the cap_demotions pattern), so pre-E snapshots
        # stay byte-identical.
        self.factions: dict[str, dict] = {}
        # Wave E / EM-184 — active world-scale miracles: [{kind, until_tick}].
        # Timed god miracles (send_rain / bountiful_harvest) live here while
        # active; re-casting REFRESHES until_tick (never stacks); expiry is
        # swept in the loop's per-tick path beside expire_blackouts(). The
        # one-time calm_spirits never adds an entry. Serialized in
        # to_snapshot() only when non-empty (the cap_demotions pattern), so
        # pre-E snapshots stay byte-identical.
        self.active_miracles: list[dict] = []
        # W11b / EM-091 — the public billboard. List of {tick, actor_id,
        # actor_type, text}, capped to the 20 newest (append order = oldest →
        # newest). Serialized in to_snapshot()/world_state — THE frontend seam.
        self.billboard: list[dict] = []
        # Wave I / EM-210 — the gallery (the image record store). List of
        # {image_id, prompt, proposer_id, created_tick, url, promoted}; all
        # JSON-safe + deterministic at creation. Capped to the newest
        # params.image_gen.max_gallery (pop-oldest on append, mirror
        # _append_billboard). Serialized in to_snapshot() ONLY when non-empty so
        # pre-Wave-I snapshots restore byte-identically. THE frontend seam for the
        # 3-D notice-board texture.
        self.gallery: list[dict] = []
        # PROTOTYPE (god-channel) — loud-tier god proclamations, distinct from the
        # opt-in billboard. While a proclamation is active it rides EVERY agent's
        # prompt (runtime._assemble_context), so the god's word is guaranteed to
        # reach the whole world. Each entry: {id, tick, text, replies:[]}; the
        # NEWEST entry is the active decree. Serialized in to_snapshot().
        self.proclamations: list[dict] = []
        # PROTOTYPE (god-channel) — the town's name, set by CONSENSUS: an agent
        # proposes a `name_town` rule (propose_rule) and it takes effect when the
        # vote passes (_on_rule_activated). Empty = unnamed. Serialized in
        # to_snapshot() so the frontend/header can show it.
        self.town_name: str = ""
        # Wave I / EM-213 — the plaza banner: the gallery image_id the town VOTED
        # to hang over the plaza (promote_image governance). Empty = unset (the
        # frontend renders a procedural fallback). Serialized in to_snapshot() only
        # when non-empty so pre-Wave-I snapshots restore byte-identically.
        self.plaza_banner_ref: str = ""
        # EM-137 (god console) — one-shot god whispers awaiting delivery, keyed
        # by agent id. post_whisper_as_god queues lines here; the runtime pops
        # the target's queue into its NEXT prompt exactly once. EM-145: queued
        # (undelivered) whispers ARE serialized in to_snapshot() — dev
        # hot-reloads kept eating them before delivery, which made the god
        # console look broken. Delivered whispers still leave no trace.
        self.pending_whispers: dict[str, list[str]] = {}
        # W15 / EM-155 — deterministic city seed (config `world.city_seed`,
        # default 1337). The generated 3D city ring is rendered as a pure
        # function f(snapshot, city_seed): the seed rides to_snapshot() /
        # world_state and survives fork (EM-101) + replay (EM-075), so live,
        # replay, and fork all draw the SAME city. Int-coerced defensively —
        # params may be a bare dataclass/dict/None without the key.
        try:
            self.city_seed: int = int(_block_get(params, "city_seed", 1337))
        except (TypeError, ValueError):
            self.city_seed = 1337

        # Wave D3 / EM-168 — cap-pressure governor bookkeeping: lane (profile
        # name) -> the UsageAlertTracker day-window key ("YYYY-MM-DD") whose
        # usage_alert already demoted that lane's agents. ONE demotion pass per
        # lane-alert-day: repeated alerts on the same lane in the same window
        # (rpd then tpd) never stack, and a manual tier override is never
        # re-demoted the same day. Entries expire at the tracker's day
        # rollover (restore_cap_demotions). Serialized in to_snapshot() only
        # when non-empty, so pre-D3 snapshots are byte-identical.
        self.cap_demotions: dict[str, str] = {}
        # Injected by the API layer (set_usage_window_probe): a zero-clock-read
        # peek at the UsageAlertTracker's CURRENT day-window key. The tracker
        # already rolls its window lazily on real adapter calls; the scheduler
        # only compares the attribute — no new clock reads (EM-168 rule).
        self._usage_window_probe: Any = None

        self.tick: int = 0
        self.day: int = 0
        # W7 — round counter, bumped at each round start. The tick loop watches it
        # to drive once-per-round building lifecycle (abandonment).
        self.round: int = 0
        self.running: bool = False
        self.tick_interval_seconds: float = params.tick_interval_seconds

        # Round-robin scheduler: stable sorted order of agent ids
        self._turn_order: list[str] = sorted(self.agents.keys())
        self._turn_index: int = 0
        self._round_start: bool = True   # True at beginning of a new round

        # W11b / EM-098 — procgen town (config world.procgen, default OFF). When
        # enabled, REPLACES the hand-authored places with the seeded layout +
        # housing. Disabled (default) leaves the hand-authored town untouched.
        self.apply_procgen()

        # EM-123 — zoned neighborhoods derived from the (now-final) places. Each
        # distinct `place.neighborhood_id or district` becomes a Neighborhood at
        # tier 1 (founded baseline); a megaproject completing inside one matures
        # it (_grow_district). Un-districted towns (procgen) yield {} and the
        # feature is inert. Serialized in to_snapshot() ONLY once a tier diverges
        # from the derivable baseline, so a fresh world stays byte-identical.
        self.neighborhoods: dict[str, Neighborhood] = self._derive_neighborhoods()

    def apply_procgen(self) -> None:
        """Apply the seeded procgen town layout when world.procgen.enabled
        (EM-098). No-op (hand-authored town byte-identical) when the block is
        absent or disabled. Idempotent for a fixed seed; clamps any agent or
        animal standing on a now-unknown place back to the plaza."""
        cfg = getattr(self.params, "procgen", None)
        if not bool(_block_get(cfg, "enabled", False)):
            return
        names = [a.name for a in self.agents.values()]
        places = generate_procgen_places(cfg, names)
        self.places = {p.id: p for p in places}
        fallback = "plaza" if "plaza" in self.places else next(iter(self.places), "")
        for a in self.agents.values():
            if a.location not in self.places:
                a.location = fallback
        for an in self.animals.values():
            if an.location not in self.places:
                an.location = fallback

    # ──────────────────────────────────────────────────────────────────────────
    # EM-123 — zoned neighborhoods (districts that deepen as megaprojects land)
    # ──────────────────────────────────────────────────────────────────────────

    def _derive_neighborhoods(self) -> dict[str, "Neighborhood"]:
        """Group the current places into Neighborhoods at tier 1. Pure +
        deterministic: places are visited in sorted-id order and the result is
        keyed/inserted in sorted neighborhood-id order, so a replay/fork that
        re-runs this on the same places yields the byte-identical baseline. The
        neighborhood's zone_kind is the majority of its members' zone_kinds,
        tie-broken by the canonical _ZONE_KINDS order (stable, never RNG)."""
        groups: dict[str, list[PlaceState]] = {}
        for p in sorted(self.places.values(), key=lambda pl: pl.id):
            nid = p.neighborhood_id or p.district
            if not nid:
                continue  # un-districted place (procgen) → no neighborhood
            groups.setdefault(str(nid), []).append(p)
        result: dict[str, Neighborhood] = {}
        for nid in sorted(groups):
            counts: dict[str, int] = {}
            for p in groups[nid]:
                zk = zone_kind_for_place(p)
                counts[zk] = counts.get(zk, 0) + 1
            # max count, tie-break by canonical order (index in _ZONE_KINDS)
            zone = max(
                counts,
                key=lambda zk: (counts[zk], -_ZONE_KINDS.index(zk)
                                if zk in _ZONE_KINDS else -99),
            )
            result[nid] = Neighborhood(
                id=nid, name=_neighborhood_display_name(nid), zone_kind=zone)
        return result

    def neighborhood_of(self, place_id: str) -> "Neighborhood | None":
        """The Neighborhood a place belongs to (None when un-districted)."""
        p = self.places.get(place_id)
        if p is None:
            return None
        nid = p.neighborhood_id or p.district
        return self.neighborhoods.get(str(nid)) if nid else None

    def _grow_district(self, building: "Building") -> list[dict]:
        """EM-123 — a completed megaproject matures its district. ADDITIVE +
        GUARDED: when `world.district_growth.enabled` is off, the building's
        place is un-districted, or the tier is already maxed, this returns []
        and the completion is byte-identical to pre-EM-123. Otherwise it bumps
        the neighborhood's progress; on reaching `completions_per_tier` it raises
        the tier (capped at `max_tier`) and emits ONE `district_grew` event.
        Sub-threshold completions only advance progress silently (no event), so
        the feed stays quiet until a district actually levels up. EM-174-safe:
        growth is a tier/zoning state change, NEVER a generated filler building.
        Deterministic: pure counter arithmetic, no clock/RNG, so replay/fork
        reproduce the identical tier timeline."""
        cfg = getattr(self.params, "district_growth", None)
        if not bool(_block_get(cfg, "enabled", True)):
            return []
        nb = self.neighborhood_of(building.location)
        if nb is None:
            return []
        try:
            per_tier = max(1, int(_block_get(cfg, "completions_per_tier", 2)))
            max_tier = max(1, int(_block_get(cfg, "max_tier", 4)))
        except (TypeError, ValueError):
            per_tier, max_tier = 2, 4
        if nb.tier >= max_tier:
            return []
        nb.progress += 1
        if nb.progress < per_tier:
            return []
        nb.progress = 0
        nb.tier += 1
        return [{
            "kind": "district_grew",
            "actor_id": None,
            "target_id": building.id,
            "text": f"The {nb.name} district matures to tier {nb.tier} "
                    f"({nb.zone_kind}), spurred on by {building.name}.",
            "payload": {
                "neighborhood_id": nb.id,
                "zone_kind": nb.zone_kind,
                "tier": nb.tier,
                "building_id": building.id,
                "reason": "megaproject_completed",
            },
        }]

    # ──────────────────────────────────────────────────────────────────────────
    # Scheduler
    # ──────────────────────────────────────────────────────────────────────────

    # Wave D2 / EM-158 — cadence tiers: how often each tier comes due, in
    # rounds. Protagonists act every round (the pre-D2 behavior — and the
    # DEFAULT tier, so an untiered cast schedules exactly as before);
    # supporting every 3rd round; background every 10th. The due-set rotation
    # within a round stays sorted-id.
    CADENCE_TIERS = ("protagonist", "supporting", "background")
    TIER_CADENCE_ROUNDS: dict[str, int] = {
        "protagonist": 1, "supporting": 3, "background": 10,
    }

    def living_agents(self) -> list[AgentState]:
        return [a for a in self.agents.values() if a.alive]

    def _tier_due(self, agent: AgentState, round_no: int) -> bool:
        """True when `agent`'s cadence tier comes due in round `round_no`
        (EM-158). Unknown tiers behave as protagonist (due every round)."""
        every = self.TIER_CADENCE_ROUNDS.get(
            getattr(agent, "cadence_tier", "protagonist"), 1)
        return every <= 1 or round_no % every == 0

    def _due_ids(self, round_no: int) -> list[str]:
        """The sorted-id due set for round `round_no` (EM-158)."""
        return sorted(a.id for a in self.living_agents()
                      if self._tier_due(a, round_no))

    def _rebuild_turn_order(self) -> None:
        """Prune dead agents from the current round's rotation and append any
        newly spawned agents whose tier is due THIS round. Wave D2 / EM-158:
        `_turn_order` holds the current round's DUE set (rebuilt sorted-id at
        each round start by _start_new_round) — with the default all-
        protagonist cast that is the same full sorted-id rotation as before."""
        alive_ids = {a.id for a in self.living_agents()}
        # Wave D3 / EM-172 — mid-round-death scheduler skip (pre-existing since
        # 58a8e7e): pruning a dead agent that sat BEFORE the rotation pointer
        # shifts every later entry left by one, so the pointer silently jumped
        # over the next due agent. Decrement the pointer once per pruned
        # pre-cursor so it keeps naming the same next-due agent. Dead entries
        # AT/AFTER the pointer need no shift (the pointer's target is
        # unaffected); the round-boundary check in next_agent() handles the
        # shrunken-list edge as before.
        self._turn_index -= sum(
            1 for aid in self._turn_order[: self._turn_index]
            if aid not in alive_ids
        )
        self._turn_order = [aid for aid in self._turn_order if aid in alive_ids]
        # Add any newly spawned agents due this round at the end.
        for aid in sorted(self.agents.keys()):
            if (
                aid not in self._turn_order
                and aid in alive_ids
                and self._tier_due(self.agents[aid], self.round)
            ):
                self._turn_order.append(aid)

    def _start_new_round(self) -> None:
        """Advance to the next round with a NON-EMPTY due set (EM-158) and
        install its sorted-id rotation. Rounds where no tier is due (possible
        only in a world with zero protagonists) are skipped; each skipped
        round still applies its per-round effects (UBI), so round economics
        stay consistent. Bounded by the slowest tier cadence, so this always
        terminates. Round counting derives from world state (`self.round`,
        serialized in snapshots) — never wall time."""
        due: list[str] = []
        for _ in range(max(self.TIER_CADENCE_ROUNDS.values())):
            self._apply_round_start()
            due = self._due_ids(self.round)
            if due:
                break
        self._turn_order = due
        self._turn_index = 0

    def next_agent(self) -> AgentState | None:
        """Return the next agent whose turn it is, advancing the pointer.
        Returns None if no living agents.
        Detects round boundaries and applies per-round effects."""
        # Wave D3 / EM-168 — restore cap-governor demotions once the usage
        # tracker's day window has rolled (checked BEFORE the due-set math so
        # a restored tier schedules correctly from this very call).
        self._check_cap_demotion_rollover()
        if not self.living_agents():
            return None
        self._rebuild_turn_order()

        # Detect if we're starting a new round
        if self._turn_index >= len(self._turn_order):
            self._round_start = True

        if self._round_start:
            self._start_new_round()
            self._round_start = False

        if not self._turn_order:  # pragma: no cover - defensive
            return None

        agent = self.agents.get(self._turn_order[self._turn_index])
        self._turn_index += 1

        if self._turn_index >= len(self._turn_order):
            self._round_start = True  # next call will start a new round

        return agent

    def _apply_round_start(self) -> None:
        """Apply per-round effects (UBI etc.)."""
        self.round += 1
        ubi_rule = self._active_rule("ubi")
        if ubi_rule:
            for agent in self.living_agents():
                agent.credits += self.params.ubi_amount
        # Wave E / EM-114 — the once-per-round birth check (contract: "hook
        # beside the existing per-round effects"). At most ONE birth per
        # round; events park in pending_spawn_events and are drained by the
        # loop's existing _flush_spawn_events (EM-062/168 pattern). Spawning
        # here is pointer-safe: _start_new_round overwrites _turn_order with
        # the due set AFTER this returns, and a background-tier child only
        # joins rounds where its tier is due (EM-158/172 invariant intact).
        self.check_births()
        # Wave E / EM-120 — the once-per-round faction recompute, AFTER the
        # birth check (contract order: births first, then factions) so a
        # newborn's family edges count toward this round's clusters. Diff-
        # driven events park in the same pending_spawn_events outbox.
        self.recompute_factions()
        # EM-233 — the once-per-round memory consolidation ("sleep"), AFTER births
        # so a newborn (whose only belief is its birth line) is well under the
        # ceiling and untouched. Each over-ceiling living agent rolls its oldest
        # beliefs into one digest line; the `memory` events park in the SAME
        # pending_spawn_events outbox (drained + emitted by the tick loop's
        # existing _flush_spawn_events, like births/factions). Deterministic +
        # clock/RNG-free; a small cast under the ceiling is a no-op (golden-safe).
        self.consolidate_memories()

    def _active_rule(self, effect: str) -> RuleState | None:
        for rule in self.rules.values():
            if rule.status == "active" and rule.effect == effect:
                return rule
        return None

    def has_active_rule(self, effect: str) -> bool:
        return self._active_rule(effect) is not None

    # ──────────────────────────────────────────────────────────────────────────
    # Wave D3 / EM-168 — cap-pressure governor.
    #
    # A usage_alert (UsageAlertTracker ≥70% of a lane's rpd/tpd day cap) demotes
    # every agent ASSIGNED to that lane ONE cadence tier (protagonist →
    # supporting → background; background stays), recording the prior tier on
    # AgentState.demoted_from. At the tracker's UTC-day rollover (the alert
    # windows already reset daily) demoted agents return to demoted_from. The
    # world never reads a clock: the API layer feeds the tracker's CURRENT
    # window key into apply_cap_pressure (alert path) and exposes it through
    # the injected _usage_window_probe (rollover path) — both are attribute
    # reads of state the tracker already maintains.
    # ──────────────────────────────────────────────────────────────────────────

    def _cap_governor_enabled(self) -> bool:
        """Config gate `world.cap_governor.enabled` (default OFF since the
        2026-06-12 EM-198 error-bounce mandate — cap pressure routes to other
        lanes instead of muting the cast). Disabled ⇒ usage alerts stay
        alert-only — byte-identical pre-D3 behavior."""
        return bool(_block_get(
            getattr(self.params, "cap_governor", None), "enabled", False))

    def set_usage_window_probe(self, probe: Any) -> None:
        """Register a zero-argument callable returning the UsageAlertTracker's
        CURRENT day-window key (or None/"" when unknown). Wired by the API
        layer; it must be a cheap attribute read — the tracker itself owns all
        clock reads (it rolls its window lazily on real adapter calls)."""
        self._usage_window_probe = probe

    def apply_cap_pressure(self, lane: str, window: str) -> list[dict]:
        """One usage_alert landed for `lane` inside day-window `window`: demote
        every living agent assigned to that lane one cadence tier (background
        stays), recording demoted_from. Idempotent per lane-alert-day — a
        second alert on the same lane in the same window (rpd then tpd) is a
        no-op, including for agents whose demotion was manually overridden.
        Returns the feed event dicts to emit (at most one demotion event, plus
        any rollover-restoration event when this alert is the first observation
        of a NEW window). Disabled governor ⇒ [] and zero state changes."""
        if not self._cap_governor_enabled():
            return []
        lane = str(lane)
        window = str(window)
        # Rollover-first ordering: an alert from a NEW day restores yesterday's
        # demotions before applying today's.
        events = self.restore_cap_demotions(window)
        if self.cap_demotions.get(lane) == window:
            return events  # this lane's alert-day already demoted — never stack
        demoted: list[dict] = []
        for aid in sorted(self.agents):
            agent = self.agents[aid]
            if not agent.alive or agent.profile != lane:
                continue
            if agent.demoted_from is not None:
                continue  # already governed (another lane / earlier alert)
            tier = (
                agent.cadence_tier
                if agent.cadence_tier in self.CADENCE_TIERS else "protagonist"
            )
            idx = self.CADENCE_TIERS.index(tier)
            if idx >= len(self.CADENCE_TIERS) - 1:
                continue  # background stays — nothing to restore either
            agent.demoted_from = tier
            agent.cadence_tier = self.CADENCE_TIERS[idx + 1]
            demoted.append({
                "agent_id": agent.id,
                "name": agent.name,
                "from": tier,
                "to": agent.cadence_tier,
            })
        self.cap_demotions[lane] = window
        if demoted:
            names = ", ".join(d["name"] for d in demoted)
            events.append({
                "kind": "cap_pressure",
                "actor_id": None,
                "actor_type": "system",
                "profile": lane,
                "text": (
                    f"🪫 {lane} is nearing its daily cap — "
                    f"{names} slow to a calmer cadence until tomorrow."
                ),
                "payload": {
                    "phase": "demoted",
                    "lane": lane,
                    "window": window,
                    "agents": [
                        {"agent_id": d["agent_id"], "from": d["from"], "to": d["to"]}
                        for d in demoted
                    ],
                },
            })
        return events

    def restore_cap_demotions(self, window: str) -> list[dict]:
        """The usage tracker's day window is now `window`: if any recorded
        demotion belongs to an EARLIER window, the day has rolled — every
        governed agent returns to its demoted_from tier (which clears) and the
        per-lane demotion records expire. Returns at most ONE restoration feed
        event. Same-window calls are no-ops ([])."""
        window = str(window)
        if not self.cap_demotions:
            return []
        stale = [ln for ln, w in self.cap_demotions.items() if w != window]
        if not stale:
            return []
        for ln in stale:
            self.cap_demotions.pop(ln, None)
        restored: list[dict] = []
        for aid in sorted(self.agents):
            agent = self.agents[aid]
            if agent.demoted_from is None:
                continue
            target = (
                agent.demoted_from
                if agent.demoted_from in self.CADENCE_TIERS else "protagonist"
            )
            agent.cadence_tier = target
            agent.demoted_from = None
            restored.append({"agent_id": agent.id, "name": agent.name, "to": target})
        if not restored:
            return []
        names = ", ".join(r["name"] for r in restored)
        return [{
            "kind": "cap_pressure",
            "actor_id": None,
            "actor_type": "system",
            "profile": None,
            "text": (
                f"🔋 A fresh day's quota — {names} "
                "return to their usual cadence."
            ),
            "payload": {
                "phase": "restored",
                "window": window,
                "agents": [
                    {"agent_id": r["agent_id"], "to": r["to"]} for r in restored
                ],
            },
        }]

    def _check_cap_demotion_rollover(self) -> None:
        """Scheduler-side rollover hook (EM-168): when demotions are
        outstanding and the injected probe shows the tracker's window has
        rolled, restore them and park the feed event in the spawn-events
        outbox (drained + emitted by the tick loop, like governance spawns).
        Zero clock reads — the probe is an attribute peek at the tracker."""
        if not self.cap_demotions or self._usage_window_probe is None:
            return
        try:
            window = self._usage_window_probe()
        except Exception:  # pragma: no cover - defensive
            return
        if not window:
            return
        events = self.restore_cap_demotions(str(window))
        if events:
            self.pending_spawn_events.extend(events)

    # ──────────────────────────────────────────────────────────────────────────
    # W7 / EM-061 — buildings config accessors (safe defaults if config lacks the
    # buildings block, so this stays backward-compatible with W5/W6 worlds).
    # ──────────────────────────────────────────────────────────────────────────

    def _buildings_cfg(self) -> Any:
        return getattr(self.params, "buildings", None)

    def _bld_param(self, name: str, default: Any) -> Any:
        cfg = self._buildings_cfg()
        if cfg is None:
            return default
        return getattr(cfg, name, default)

    def operational_building_at(self, place_id: str, kind: str) -> Building | None:
        """Return an operational building of `kind` sitting at `place_id`, if any.
        Used by the economy to apply garden/farm forage + workshop work buffs."""
        for b in self.buildings.values():
            if b.location == place_id and b.kind == kind and b.status == "operational":
                return b
        return None

    def _operational_buff_building_at(
        self, place_id: str, kinds: frozenset[str]
    ) -> Building | None:
        """Wave K / EM-217 — the catalog-aware cousin of operational_building_at:
        return the FIRST operational building at `place_id` whose kind is in
        `kinds` (the extended kind→buff set, e.g. workshop/smithy/forge for work,
        garden/farm/granary/park for forage). Returns None when no such building
        is here, so the caller applies the bonus exactly once (no stacking)."""
        for b in self.buildings.values():
            if b.location == place_id and b.kind in kinds and b.status == "operational":
                return b
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # Energy / death
    # ──────────────────────────────────────────────────────────────────────────

    def apply_energy_decay(self, agent: AgentState) -> None:
        decay = self.params.energy_decay_per_turn
        # Wave E / EM-184 — while a bountiful_harvest miracle is active, decay
        # is multiplied by harvest_decay_factor (default 0.5: half the hunger).
        if self.miracle_active("bountiful_harvest"):
            try:
                decay *= float(self._mir_param("harvest_decay_factor", 0.5))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                pass
        agent.energy = max(0.0, agent.energy - decay)

    def apply_needs_decay(self, agent: AgentState) -> None:
        """EM-229 — decay the knowledge + influence needs one turn. Runs beside
        apply_energy_decay on every turn (loop.py / run.py). Pure arithmetic,
        floored at 0; UNLIKE energy these NEVER kill — check_death reads only
        energy. The decay rates come from the optional `world.needs` block via the
        defensive accessor (absent ⇒ dataclass defaults ⇒ no behavior change)."""
        # Literal call-site defaults MUST match NeedsParams defaults (the
        # _crime_param convention): an absent key falls back here, an absent
        # block makes EVERY key fall back here ⇒ pre-EM-229 behavior.
        k_decay = float(self._needs_param("knowledge_decay_per_turn", 0.5))
        i_decay = float(self._needs_param("influence_decay_per_turn", 0.4))
        agent.knowledge = max(0.0, agent.knowledge - k_decay)
        agent.influence = max(0.0, agent.influence - i_decay)

    def replenish_knowledge(self, agent: AgentState, amount: float) -> None:
        """EM-229 — top up the knowledge need (clamped 0..100). Call-site hook for
        learning: a successful skill-gain / being-taught (EM-227/228) replenishes
        knowledge. Wave M2 wires the teach_skill / skill-level-up paths to this."""
        if amount <= 0:
            return
        agent.knowledge = max(0.0, min(100.0, agent.knowledge + float(amount)))

    def replenish_influence(self, agent: AgentState, amount: float) -> None:
        """EM-229 — top up the influence need (clamped 0..100). Call-site hook for
        governance/social wins: a passed rule, a won trial, a forged alliance
        replenishes influence. Wave M2/M3 governance paths wire to this."""
        if amount <= 0:
            return
        agent.influence = max(0.0, min(100.0, agent.influence + float(amount)))

    # ──────────────────────────────────────────────────────────────────────────
    # EM-233 — memory consolidation ("sleep") + soul entries.
    # ──────────────────────────────────────────────────────────────────────────

    def seed_soul(self, agent: AgentState, anchors: list[str]) -> None:
        """EM-233 — seed an agent's IMMUTABLE soul (identity anchors) ONCE from a
        persona at spawn. Blank entries drop; the list truncates to memory.soul_cap.
        Immutable: a second call on an already-souled agent is a no-op (the soul is
        a fixed core, never rewritten). Pure — no clock, no RNG; safe in the engine
        path. An empty seed leaves the soul [] ⇒ no prompt block ⇒ golden-safe."""
        if agent.soul:
            return  # already seeded — soul is fixed
        cap = int(self._memory_param("soul_cap", 3))
        agent.soul = _coerce_soul(list(anchors or []), cap)

    def consolidate_memory(self, agent: AgentState) -> dict | None:
        """EM-233 — "sleep": deterministically roll an agent's OLDEST beliefs into
        ONE digest line when the beliefs count exceeds `memory.consolidate_at`,
        keeping the `consolidate_keep_recent` most-recent beliefs verbatim.

        v1 is a STRUCTURED ROLLUP — NO LLM: the digest records how many memories
        were folded plus a truncated, ordered join of their text, so a fixed
        belief list always produces the byte-identical digest (determinism /
        replay-safe, EM-155). The soul is NEVER touched. Returns a `memory` feed
        event dict on a consolidation, or None when below the ceiling (no-op).

        An optional cheap-LLM summary is a documented FUTURE hook: a caller could
        replace the rollup string with a one-line model summary of `old`, keeping
        the same shape — but the engine path stays clock/RNG-free by default."""
        ceiling = int(self._memory_param("consolidate_at", 20))
        keep = int(self._memory_param("consolidate_keep_recent", 8))
        # Defensive: keep must leave room for the digest under the ceiling.
        keep = max(0, min(keep, max(0, ceiling - 1)))
        if ceiling <= 0 or len(agent.beliefs) <= ceiling:
            return None
        recent = agent.beliefs[len(agent.beliefs) - keep:] if keep else []
        old = agent.beliefs[: len(agent.beliefs) - keep] if keep else list(agent.beliefs)
        if not old:
            return None  # nothing to fold (keep >= count) — no-op
        digest = self._memory_digest(old)
        agent.beliefs = [digest] + recent
        return {
            "kind": "memory",
            "actor_id": agent.id,
            "actor_type": "agent",
            "text": f"{agent.name} consolidated {len(old)} older memories while resting.",
            "payload": {
                "agent_id": agent.id,
                "consolidated": len(old),
                "kept": len(recent),
                "digest": digest,
            },
        }

    def consolidate_memories(self) -> list[dict]:
        """EM-233 — the round-boundary sweep: consolidate every over-ceiling living
        agent's beliefs (deterministic sorted-id order so the parked event order is
        replay-stable) and park each `memory` event in pending_spawn_events for the
        tick loop to drain + emit. Returns the parked events (also useful in tests).
        A cast entirely under the ceiling parks nothing — byte-identical."""
        events: list[dict] = []
        for aid in sorted(self.agents):
            agent = self.agents[aid]
            if not agent.alive:
                continue
            evt = self.consolidate_memory(agent)
            if evt is not None:
                events.append(evt)
        if events:
            self.pending_spawn_events.extend(events)
        return events

    @staticmethod
    def _memory_digest(old: list[str]) -> str:
        """EM-233 — the deterministic structured rollup of folded beliefs into one
        digest line. Pure string work (no clock, no RNG): a fixed `old` list always
        yields the byte-identical digest. Caps the joined body so the digest never
        unbounds the belief text."""
        joined = "; ".join(str(b).strip() for b in old if str(b).strip())
        body = joined if len(joined) <= 180 else joined[:179] + "…"
        return f"[consolidated {len(old)} earlier memories] {body}"

    def check_death(self, agent: AgentState) -> bool:
        """Increment zero_energy counter; return True if agent should die."""
        if agent.energy <= 0:
            agent.zero_energy_turns += 1
        else:
            agent.zero_energy_turns = 0
        if agent.zero_energy_turns >= self.params.death_after_zero_turns:
            agent.alive = False
            return True
        return False

    # ──────────────────────────────────────────────────────────────────────────
    # Economy actions
    # ──────────────────────────────────────────────────────────────────────────

    def action_work(self, agent: AgentState) -> tuple[bool, str, int]:
        """Returns (success, reason, credits_gained)."""
        place = self.places.get(agent.location)
        if place is None or place.kind != "work":
            return False, "must be at a work place", 0
        reward = self.params.work_reward
        if self.has_active_rule("work_bonus"):
            reward = int(reward * 1.5)
        # W7: an operational workshop at this place grants +work_bonus_pct%.
        # Wave K / EM-217: the catalog extends the kind→buff mapping — a smithy /
        # forge / tavern / market IS a work place too, granting the SAME boost as
        # a workshop. ANY one operational work-buff building at this place applies
        # the bonus ONCE (not per-building) so it matches the pre-K single-check.
        if self._operational_buff_building_at(agent.location, _WORK_BUFF_KINDS) is not None:
            pct = self._bld_param("work_bonus_pct", 0)
            reward = int(reward * (1 + pct / 100.0))
        agent.credits += reward
        return True, "ok", reward

    def action_forage(self, agent: AgentState) -> tuple[bool, str, int]:
        reward = self.params.forage_reward
        # W7: an operational garden/farm at this place grants +forage_bonus.
        # Wave K / EM-217: the catalog extends the kind→buff mapping — a granary /
        # park IS a forage place too, granting the SAME bonus as a garden/farm.
        # ANY one operational forage-buff building at this place applies the bonus
        # ONCE so it matches the pre-K behavior (no per-building stacking).
        if self._operational_buff_building_at(agent.location, _FORAGE_BUFF_KINDS) is not None:
            reward += self._bld_param("forage_bonus", 0)
        # Wave E / EM-184 — while a send_rain miracle is active, every forage
        # yields +rain_forage_bonus ON TOP of the base + garden/farm bonuses.
        if self.miracle_active("send_rain"):
            try:
                reward += int(self._mir_param("rain_forage_bonus", 2))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                pass
        agent.credits += reward
        return True, "ok", reward

    def action_recharge(self, agent: AgentState) -> tuple[bool, str, float]:
        # W11b / EM-083 — a real blackout disables recharge at affected places.
        if self.place_blacked_out(agent.location):
            return False, "blackout: recharge is disabled here until power returns", 0.0
        cost = self.params.recharge_cost
        if self.has_active_rule("recharge_subsidy"):
            cost = max(1, cost // 2)
        if agent.energy >= 100:
            # W9 / EM-070 (audit B5): recharging at full energy is a REJECTION,
            # not a silent credit sink — no charge, gated like other actions.
            # The runtime validator surfaces "energy already full" to the agent.
            return False, "already_full", 0.0
        if agent.credits < cost:
            return False, f"need {cost} credits, have {agent.credits}", 0.0
        agent.credits -= cost
        gained = min(self.params.recharge_amount, 100.0 - agent.energy)
        agent.energy = min(100.0, agent.energy + self.params.recharge_amount)
        return True, "ok", gained

    def action_give(self, agent: AgentState, target: AgentState, amount: int) -> tuple[bool, str]:
        if amount <= 0:
            return False, "amount must be positive"
        if agent.credits < amount:
            return False, f"insufficient credits: have {agent.credits}, need {amount}"
        if agent.location != target.location:
            return False, "target not co-located"
        agent.credits -= amount
        target.credits += amount
        # Update trust
        self._update_trust(agent, target, +5)
        return True, "ok"

    def action_steal(self, agent: AgentState, target: AgentState) -> tuple[bool, str, int]:
        if self.has_active_rule("ban_stealing"):
            return False, "ban_stealing rule is active", 0
        if agent.location != target.location:
            return False, "target not co-located", 0
        amount = min(target.credits, self.params.steal_max)
        target.credits -= amount
        agent.credits += amount
        # Trust damage
        self._update_trust(agent, target, -15)
        self._update_trust(target, agent, -10)
        # Relationship escalation for target. Wave E / EM-113: an existing feud
        # is the deeper state — never downgraded back to rival/enemy (the -40
        # reflex in _update_trust may have just hardened it).
        rel = target.relationships.get(agent.id)
        if rel is None or rel.type not in ("rival", "enemy", "feud"):
            if rel is None:
                rel = RelationshipState()
                target.relationships[agent.id] = rel
            if rel.trust < -20:
                rel.type = "enemy"
            else:
                rel.type = "rival"
            rel.since_tick = self.tick  # EM-113 — type changed here
        # EM-240 — witnessed-crime notoriety bookkeeping (folded into existing steal).
        self._register_crime(agent, "steal", target.id,
                             int(self._crime_param("steal_notoriety", 6)))
        return True, "ok", amount

    # ──────────────────────────────────────────────────────────────────────────
    # EM-240 — offensive crime verbs (Task 6): heist, extort, vandalize. heist and
    # extort mirror steal's co-location + trust-crater + rivalry-snap shape with a
    # bigger score and heavier notoriety; vandalize damages a place's power (a
    # short blackout) short of arson's structural destruction.
    # ──────────────────────────────────────────────────────────────────────────

    def _snap_to_rival(self, target: AgentState, agent: AgentState) -> None:
        """EM-240 — the victim's view of the perpetrator snaps to at least rival
        (enemy when trust has already cratered). Mirrors the steal escalation:
        an existing rival/enemy/feud is the deeper state and is never downgraded."""
        rel = target.relationships.get(agent.id)
        if rel is None or rel.type not in ("rival", "enemy", "feud"):
            if rel is None:
                rel = RelationshipState()
                target.relationships[agent.id] = rel
            rel.type = "enemy" if rel.trust < -20 else "rival"
            rel.since_tick = self.tick  # EM-113 — type changed here

    def action_heist(self, agent: AgentState, target: AgentState) -> tuple[bool, str, int]:
        """EM-240 — a big-score theft: up to heist_max (≫ steal_max), gated on a
        worthwhile mark. Same co-location + ban_stealing gate as steal; heavier
        notoriety. Victim trust craters like steal."""
        if self.has_active_rule("ban_stealing"):
            return False, "ban_stealing rule is active", 0
        if agent.location != target.location:
            return False, "target not co-located", 0
        if target.credits < int(self._crime_param("heist_min_target_credits", 15)):
            return False, "target not worth the risk", 0
        amount = min(target.credits, int(self._crime_param("heist_max", 30)))
        target.credits -= amount
        agent.credits += amount
        self._update_trust(agent, target, -20)
        self._update_trust(target, agent, -15)
        self._snap_to_rival(target, agent)
        self._register_crime(agent, "heist", target.id,
                             int(self._crime_param("heist_notoriety", 18)))
        return True, "ok", amount

    def action_extort(self, agent: AgentState, target: AgentState) -> tuple[bool, str, int]:
        """EM-240 — threaten a co-located agent for credits (up to extort_max).
        Always snaps the victim's view to at least rival."""
        if agent.location != target.location:
            return False, "target not co-located", 0
        amount = min(target.credits, int(self._crime_param("extort_max", 15)))
        if amount <= 0:
            return False, "target has nothing to give", 0
        target.credits -= amount
        agent.credits += amount
        self._update_trust(target, agent, -18)
        self._snap_to_rival(target, agent)
        self._register_crime(agent, "extort", target.id,
                             int(self._crime_param("extort_notoriety", 12)))
        return True, "ok", amount

    def action_vandalize(self, agent: AgentState, building_id: str) -> dict:
        """EM-240 — damage a building short of arson: a short blackout at its place,
        no health destruction. Witnesses lose trust (like arson)."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(agent.id, "vandalize", "building_not_found",
                                    f"{agent.name} tried to vandalize an unknown structure.")
        place = self.places.get(building.location)
        ticks = int(self._crime_param("vandalize_blackout_ticks", 8))
        if place is not None:
            place.blackout_until_tick = max(place.blackout_until_tick, self.tick + ticks)
        for witness in self.agents_at(building.location):
            if witness.id != agent.id:
                self._update_trust(witness, agent, -10)
        self._register_crime(agent, "vandalize", None,
                             int(self._crime_param("vandalize_notoriety", 10)))
        return {
            "kind": "crime_committed",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} vandalizes {building.name}!",
            "payload": {"action": "vandalize", "building_id": building.id,
                        "blackout_ticks": ticks},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # EM-240 — economy & corruption verbs (Task 7): launder, bribe. launder spends
    # a cut of credits to cool the actor's own notoriety (only when dirty). bribe
    # pays a co-located enforcer to wipe most of the payer's notoriety — but a
    # third-party witness dirties the ENFORCER (corruption is catchable). Both
    # clear a stale `wanted` once notoriety falls back below threshold.
    # ──────────────────────────────────────────────────────────────────────────

    def action_launder(self, agent: AgentState, amount: int) -> tuple[bool, str, int]:
        """EM-240 — spend a cut of credits to cool notoriety. Only when dirty."""
        if agent.notoriety <= 0:
            return False, "nothing to launder", 0
        amount = max(0, min(agent.credits, int(amount or 0)))
        if amount <= 0:
            return False, "no credits to launder", 0
        fee = int(amount * float(self._crime_param("launder_cut", 0.3)))
        agent.credits -= fee
        agent.notoriety = max(0, agent.notoriety -
                              int(self._crime_param("launder_notoriety_reduction", 8)))
        self._clear_wanted_if_cool(agent)
        return True, "ok", fee

    def action_bribe(self, agent: AgentState, enforcer: AgentState,
                     amount: int) -> tuple[bool, str, int]:
        """EM-240 — pay a co-located enforcer to wipe notoriety. If a third party
        witnesses it, the ENFORCER gains notoriety (corruption is catchable)."""
        if enforcer.role != "enforcer":
            return False, "can only bribe an enforcer", 0
        if agent.location != enforcer.location:
            return False, "enforcer not co-located", 0
        amount = max(0, min(agent.credits, int(amount or 0)))
        if amount <= 0:
            return False, "no credits to offer", 0
        agent.credits -= amount
        enforcer.credits += amount
        eff = float(self._crime_param("bribe_efficacy", 0.75))
        agent.notoriety = max(0, int(agent.notoriety * (1.0 - eff)))
        self._clear_wanted_if_cool(agent)
        witnesses = [a for a in self.agents_at(agent.location)
                     if a.id not in (agent.id, enforcer.id)]
        if witnesses:
            self._register_crime(enforcer, "bribery", agent.id,
                                 int(self._crime_param("bribe_notoriety", 14)))
        return True, "ok", amount

    def _clear_wanted_if_cool(self, agent: AgentState) -> None:
        """Drop a `wanted` flag once notoriety falls back below threshold."""
        if agent.crime_status == "wanted" and \
                agent.notoriety < int(self._crime_param("wanted_threshold", 40)):
            agent.crime_status = None

    def action_recruit(self, agent: AgentState, target: AgentState) -> dict:
        """EM-240 — propose a criminal pact to a co-located agent. Posts a pending
        offer the target may accept on its NEXT turn. No crime committed here."""
        if agent.location != target.location:
            return self._fail_event(agent.id, "recruit", "not co-located",
                                    f"{agent.name} found no one here to recruit.")
        if agent.id == target.id:
            return self._fail_event(agent.id, "recruit", "self",
                                    f"{agent.name} cannot recruit themselves.")
        self.pending_crime_offers[target.id] = {
            "recruiter_id": agent.id, "tick": self.tick,
        }
        return {
            "kind": "recruited",
            "actor_id": agent.id,
            "target_id": target.id,
            "text": f"{agent.name} quietly pitches {target.name} on a scheme.",
            "payload": {"action": "recruit"},
        }

    def action_accept_contract(self, agent: AgentState) -> tuple[bool, str]:
        """EM-240 — accept the open pact addressed to this agent: seal a warm
        mutual bond (the ring) and mark both with a conspiracy notoriety bump.
        The mutual ally edge (seeded to conspiracy_trust_seed) lets
        recompute_factions cluster the conspirators — ally is NOT trust-gated,
        partner is, which is why fresh conspirators use ally."""
        offer = self.pending_crime_offers.pop(agent.id, None)
        if not offer:
            return False, "no open offer to accept"
        recruiter = self.agents.get(offer.get("recruiter_id"))
        if recruiter is None or not recruiter.alive:
            return False, "the recruiter is gone"
        seed = int(self._crime_param("conspiracy_trust_seed", 30))
        for a, b in ((agent, recruiter), (recruiter, agent)):
            rel = a.relationships.get(b.id)
            if rel is None:
                rel = RelationshipState()
                a.relationships[b.id] = rel
            rel.trust = max(rel.trust, seed)
            if rel.type in ("neutral",):
                rel.type = "ally"
                rel.since_tick = self.tick
        bump = int(self._crime_param("conspiracy_notoriety", 6))
        for who in (agent, recruiter):
            who.notoriety = max(0, min(100, who.notoriety + bump))
            who.rap_sheet.append({"tick": self.tick, "crime": "conspiracy",
                                  "victim_id": None, "witnessed": False})
        return True, "ok"

    # ──────────────────────────────────────────────────────────────────────────
    # EM-240 (Task 10) — enforcer justice verbs. investigate confirms a suspect's
    # unwitnessed crimes into notoriety (needs a third party to question); accuse
    # is a public naming (narrative + a feed event); detain jails a wanted /
    # high-notoriety suspect on the spot for detain_sentence ticks. The jail is a
    # place with id 'jail' (else the first civic place, else nowhere).
    # ──────────────────────────────────────────────────────────────────────────

    def _jail_place_id(self) -> str | None:
        """EM-240 — the town jail: a place with id 'jail', else the first civic
        place, else None (a town with no jail simply cannot detain)."""
        if "jail" in self.places:
            return "jail"
        for p in self.places.values():
            if p.kind == "civic":
                return p.id
        return None

    def action_investigate(self, agent: AgentState, suspect: AgentState) -> tuple[bool, str, int]:
        """EM-240 — an enforcer questions co-located witnesses to confirm a
        suspect's unwitnessed crimes into notoriety. Needs a third party present."""
        if agent.location != suspect.location:
            return False, "suspect not co-located", 0
        witnesses = [a for a in self.agents_at(agent.location)
                     if a.id not in (agent.id, suspect.id)]
        if not witnesses:
            return False, "no witnesses here to question", 0
        base = int(self._crime_param("investigate_notoriety", 10))
        confirmed = 0
        for entry in suspect.rap_sheet:
            if not entry.get("witnessed"):
                entry["witnessed"] = True
                suspect.notoriety = max(0, min(100, suspect.notoriety + base))
                confirmed += 1
        if confirmed and suspect.crime_status is None and \
                suspect.notoriety >= int(self._crime_param("wanted_threshold", 40)):
            suspect.crime_status = "wanted"
        return True, "ok", confirmed

    def action_accuse(self, agent: AgentState, suspect: AgentState) -> dict:
        """EM-240 — an enforcer publicly names a suspect. Narrative + a feed
        event; the actual penalty comes via detain or a trial vote."""
        if agent.location != suspect.location:
            return self._fail_event(agent.id, "accuse", "not co-located",
                                    f"{agent.name} found no one here to accuse.")
        return {
            "kind": "accusation",
            "actor_id": agent.id,
            "target_id": suspect.id,
            "text": f"{agent.name} accuses {suspect.name} of crimes against the town.",
            "payload": {"notoriety": suspect.notoriety},
        }

    def action_detain(self, agent: AgentState, suspect: AgentState):
        """EM-240 — an enforcer jails a wanted / high-notoriety suspect on the
        spot for detain_sentence ticks. (The spec's 'red-handed' fast lane is
        subsumed: a witnessed crime registers notoriety, which is the grounds.)
        Returns a dict on success, or a (False, reason, None) tuple on rejection."""
        if agent.location != suspect.location:
            return False, "suspect not co-located", None
        threshold = int(self._crime_param("detain_threshold", 60))
        if not (suspect.crime_status == "wanted" or suspect.notoriety >= threshold):
            return False, "insufficient grounds to detain", None
        jail = self._jail_place_id()
        if jail is None:
            return False, "this town has no jail", None
        suspect.location = jail
        suspect.crime_status = "detained"
        suspect.crime_status_until_tick = self.tick + int(self._crime_param("detain_sentence", 6))
        return {
            "kind": "detained",
            "actor_id": agent.id,
            "target_id": suspect.id,
            "text": f"{agent.name} detains {suspect.name} and marches them to jail.",
            "payload": {"until_tick": suspect.crime_status_until_tick},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Wave H4 / EM-209 — pets & bonds. owner_id is the ONLY bond: adopting a
    # co-located animal sets it (no credits move, no agent↔agent edge touched);
    # feeding restores an owned pet's energy. The FOLLOW / DECLINE / GRIEF beats
    # live in animals/runtime.py (reflex-first, deterministic, replay-safe).
    # ──────────────────────────────────────────────────────────────────────────

    def action_adopt(self, agent: AgentState, animal_id: str) -> tuple[bool, str]:
        """An agent ADOPTS a co-located, living, currently-unowned animal: sets
        animal.owner_id = agent.id. No credits move (invariant 7). The validator
        front-loads the same gates; this stays safe if called directly."""
        animal = self.animals.get(animal_id)
        if animal is None:
            return False, "no such animal"
        if not animal.alive:
            return False, f"{animal.name} is not alive"
        if animal.location != agent.location:
            return False, f"{animal.name} is not here"
        if animal.owner_id:
            if animal.owner_id == agent.id:
                return False, f"you already own {animal.name}"
            return False, f"{animal.name} already has an owner"
        animal.owner_id = agent.id
        return True, "ok"

    def action_feed_pet(self, agent: AgentState, animal_id: str) -> tuple[bool, str]:
        """A co-located agent FEEDS an animal: restores energy (and lifts mood) by
        the configured pet_feed_amount. No credits move (invariant 7). Any co-located
        agent may feed — sustaining an owned pet does not require ownership."""
        animal = self.animals.get(animal_id)
        if animal is None:
            return False, "no such animal"
        if not animal.alive:
            return False, f"{animal.name} is not alive"
        if animal.location != agent.location:
            return False, f"{animal.name} is not here"
        amount = int(getattr(getattr(self.params, "animals", None), "pet_feed_amount", 25) or 0)
        animal.energy = min(100, int(animal.energy) + amount)
        animal.mood = "content"
        return True, "ok"

    # ──────────────────────────────────────────────────────────────────────────
    # Wave K / EM-218–220 — props, demolish, skin (the builders' city actions).
    #
    # place_prop / remove_prop / demolish / set_building_skin are REFLEX tools:
    # the kind/type/skin rides the agent's existing turn, zero extra invoke-LLM
    # calls (caps, not muting, hold cost). Each returns a ready-to-emit event dict
    # / {"_multi":[...]} (mirroring the W7 building actions consumed by
    # _emit_world_result), or a parse_failure on an illegal id so the loop keeps
    # turning. Heavy gating front-loads in runtime._validate_world; these stay
    # safe if called directly.
    # ──────────────────────────────────────────────────────────────────────────

    PROPS_DEFAULT_MAX_POPULATION = 48  # contract default (a populated town)

    def _props_max_population(self) -> int:
        """Wave K / EM-218 — the prop population cap, read modestly from config
        (params.props.max_population), mirroring the animals.max_population read.
        Defaults to PROPS_DEFAULT_MAX_POPULATION (48) when the block is absent
        (pre-Wave-K worlds / tests that build WorldParams directly). 0 ⇒ unlimited
        (mirrors animals: a config can opt out of the cap)."""
        cfg = getattr(self.params, "props", None)
        try:
            return max(0, int(_block_get(cfg, "max_population", self.PROPS_DEFAULT_MAX_POPULATION)))
        except (TypeError, ValueError):
            return self.PROPS_DEFAULT_MAX_POPULATION

    @staticmethod
    def _prop_offset(ordinal: int) -> tuple[float, float]:
        """Wave K / EM-218 — a PURE, deterministic in-place offset for the `ordinal`-th
        prop at a place, so multiple props don't stack on the anchor. A small ring
        (≤ ~3u radius): the angle steps by the golden angle (≈137.5°) and the
        radius grows gently with the count, both rounded for byte-stable snapshots.
        No RNG, no wall-clock — replay reproduces the same (dx,dz)."""
        if ordinal <= 0:
            return 0.0, 0.0
        angle = ordinal * 2.399963229728653  # golden angle in radians
        radius = min(3.0, 0.6 + 0.35 * ordinal)
        dx = round(radius * math.cos(angle), 4)
        dz = round(radius * math.sin(angle), 4)
        return dx, dz

    def _prop_id(self, place: str, kind: str, ordinal: int) -> str:
        """Wave K / EM-218 — a SEEDED, replay-stable prop id (NEVER uuid4 — EM-189).
        Derived from a sha256 of (place, kind, ordinal, city_seed) via the same
        _seed_int idiom the animal layer uses, so a fixed world replays the exact
        prop registry. Collisions are avoided by bumping the ordinal at the call
        site until the id is free."""
        from ..animals.runtime import _seed_int
        seed = _seed_int("prop", self.city_seed, place, kind, ordinal)
        return f"prop_{format(seed % (16 ** 10), '010x')}"

    def action_place_prop(
        self, agent: AgentState, kind: str, place: str | None = None
    ) -> dict:
        """Wave K / EM-218 — place a decoration prop at `place` (defaults to the
        agent's location). The engine assigns a deterministic in-place offset from
        the count of props already at the place, and a seeded id. Over the cap ⇒
        a parse_failure with guidance (never a dead turn). Emits prop_placed."""
        kind = str(kind or "").strip()[:30]
        if not kind:
            return self._fail_event(
                agent.id, "place_prop", "kind required",
                f"{agent.name} reached for a decoration but named nothing to place.")
        place = str(place or "").strip() or agent.location
        if place not in self.places:
            return self._fail_event(
                agent.id, "place_prop", f"unknown place {place!r}",
                f"{agent.name} cannot place a {kind} at an unknown place {place!r}.")
        cap = self._props_max_population()
        if cap > 0 and len(self.props) >= cap:
            return self._fail_event(
                agent.id, "place_prop", f"prop cap reached: {cap}",
                f"{agent.name} wanted to add a {kind}, but the town is already "
                f"decorated to the brim ({cap} props) — remove one first.")
        ordinal = sum(1 for p in self.props.values() if p.place == place)
        # Deterministic id; bump the ordinal on the (rare) seeded collision so a
        # prop id is always unique without ever resorting to uuid4 (EM-189).
        seed_ord = ordinal
        prop_id = self._prop_id(place, kind, seed_ord)
        while prop_id in self.props:
            seed_ord += 1
            prop_id = self._prop_id(place, kind, seed_ord)
        dx, dz = self._prop_offset(ordinal)
        prop = Prop(
            id=prop_id, kind=kind, place=place, dx=dx, dz=dz,
            owner_id=agent.id, created_tick=self.tick,
        )
        self.props[prop.id] = prop
        return {
            "kind": "prop_placed",
            "actor_id": agent.id,
            "text": f"{agent.name} places a {kind} at "
                    f"{self.places[place].name}.",
            "payload": {
                "prop_id": prop.id,
                "kind": prop.kind,
                "place": prop.place,
                "owner_id": prop.owner_id,
            },
        }

    def action_remove_prop(self, agent: AgentState, prop_id: str) -> dict:
        """Wave K / EM-219 — remove a prop the agent OWNS, or any UNOWNED prop the
        agent is co-located with. A non-owner removing an owned prop, or removing
        from afar, is rejected with guidance. Emits prop_removed."""
        # EM-199 defense-in-depth — coerce to str BEFORE the dict lookup so an
        # object/array prop_id is a clean soft-fail, never an unhashable TypeError.
        prop_id = str(prop_id or "").strip()
        prop = self.props.get(prop_id)
        if prop is None:
            return self._fail_event(
                agent.id, "remove_prop", f"unknown prop {prop_id!r}",
                f"{agent.name} tried to remove a prop that isn't there.")
        if prop.owner_id:
            if prop.owner_id != agent.id:
                return self._fail_event(
                    agent.id, "remove_prop", "not the owner",
                    f"{agent.name} cannot remove a {prop.kind} someone else placed.")
        else:
            # Unowned (god/seeded) prop: removable only by a co-located agent.
            if prop.place != agent.location:
                return self._fail_event(
                    agent.id, "remove_prop", "not co-located",
                    f"{agent.name} must be at "
                    f"{self.places.get(prop.place).name if prop.place in self.places else prop.place} "
                    f"to clear that {prop.kind}.")
        del self.props[prop_id]
        return {
            "kind": "prop_removed",
            "actor_id": agent.id,
            "text": f"{agent.name} removes a {prop.kind}.",
            "payload": {
                "prop_id": prop.id,
                "kind": prop.kind,
                "place": prop.place,
            },
        }

    def _demolish_building(
        self, building: Building, actor_id: str | None, by: str
    ) -> dict:
        """Wave K / EM-219 — the shared clean-demolish path (distinct from arson →
        health 0 → destroyed). Flips the building to `destroyed` and frees the lot
        back to claimable (the EM-174/EM-181 lot model keys off status). Used by
        the owner-immediate tool case AND the governance demolish effect AND the
        god override. Returns a building_demolished event. `by` records the
        authority ("owner" | "governance" | "god")."""
        building.status = "destroyed"
        building.health = 0
        building.updated_tick = self.tick
        return {
            "kind": "building_demolished",
            "actor_id": actor_id,
            "target_id": building.id,
            "text": f"{building.name} is demolished ({by}).",
            "payload": {
                "building_id": building.id,
                "kind": building.kind,
                "name": building.name,
                "place": building.location,
                "by": by,
            },
        }

    def action_demolish(self, agent: AgentState, building_id: str) -> dict:
        """Wave K / EM-219 — an OWNER cleanly demolishes their OWN building (the
        orderly/civic counterpart to arson). A NON-owner is rejected with guidance
        to use governance (a public/landmark demolish goes through propose_rule →
        vote → the demolish rule effect — see _on_rule_activated). Emits
        building_demolished."""
        # EM-199 defense-in-depth — coerce to str BEFORE the dict lookup so an
        # object/array building_id (from a multi-action turn) is a clean soft-fail,
        # never an unhashable-type TypeError (mirror place_prop's str()).
        building_id = str(building_id or "").strip()
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "demolish", "building_not_found",
                f"{agent.name} tried to demolish an unknown structure.")
        if building.status == "destroyed":
            return self._fail_event(
                agent.id, "demolish", "already destroyed",
                f"{agent.name} cannot demolish {building.name} (already rubble).")
        if building.owner_id != agent.id:
            return self._fail_event(
                agent.id, "demolish", "not the owner",
                f"{building.name} isn't yours to demolish — propose a demolish "
                f"rule and let the town vote (a public structure needs governance).")
        return self._demolish_building(building, agent.id, "owner")

    def action_set_building_skin(
        self, agent: AgentState, building_id: str, skin: str
    ) -> dict:
        """Wave K / EM-220 — the OWNER re-skins their building (a cosmetic palette
        override layered over the health-soot tint, FE-side). Owner-only. An empty
        skin clears it back to the default. Emits building_reskinned."""
        # EM-199 defense-in-depth — coerce to str BEFORE the dict lookup so an
        # object/array building_id is a clean soft-fail, never an unhashable
        # TypeError.
        building_id = str(building_id or "").strip()
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "set_building_skin", "building_not_found",
                f"{agent.name} tried to re-skin an unknown structure.")
        # EM-108 menu/resolution agreement — the menu hides re-skin for a destroyed
        # building (status != "destroyed" filter); the resolution path must reject
        # rubble too, never re-skin a stale id.
        if building.status == "destroyed":
            return self._fail_event(
                agent.id, "set_building_skin", "destroyed",
                f"{building.name} is rubble — nothing to re-skin.")
        if building.owner_id != agent.id:
            return self._fail_event(
                agent.id, "set_building_skin", "not the owner",
                f"{building.name} isn't yours to re-skin.")
        skin = str(skin or "").strip()[:24]
        building.skin = skin or None
        building.updated_tick = self.tick
        return {
            "kind": "building_reskinned",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} re-skins {building.name}"
                    + (f" in {skin}." if skin else " back to its plain finish."),
            "payload": {
                "building_id": building.id,
                "skin": building.skin,
            },
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Wave K / EM-221 — GOD console mutations (Wave 2). Thin god-owned twins of the
    # agent reflex tools above: they REUSE the same internals (_prop_id /
    # _prop_offset / _props_max_population for placement; _demolish_building for
    # demolish; building.skin for reskin) so the god path and the agent path stay
    # byte-identical in snapshots — a god mutation serializes + replays exactly like
    # an agent one (EM-155 determinism). God-owned ⇒ owner_id is None (so any
    # co-located agent can later clear a god prop). God demolish/reskin are
    # OVERRIDES: immediate, regardless of owner/landmark/governance. Each returns
    # the emitted god-ink event(s); the API layer stamps actor_type "god" +
    # payload.method and does the single world_state broadcast (mirrors
    # /api/god/rewild). NO standing LLM calls.
    # ──────────────────────────────────────────────────────────────────────────

    def god_place_prop(self, kind: str, place: str, count: int = 1) -> list[dict]:
        """Place `count` god-owned props at `place`, reusing the exact placement
        internals of action_place_prop (seeded id + deterministic ring offset),
        but owner_id=None (god/seeded — a co-located agent may later clear it).
        Returns one prop_placed event per prop actually placed; stops short at the
        population cap (cap_reached is observable by the caller as a short list).
        Raises ValueError on a bad kind/place so the API can 4xx like the existing
        endpoints (the god path validates UP FRONT rather than emitting a
        per-prop parse_failure the way the agent turn does)."""
        kind = str(kind or "").strip()[:30]
        if not kind:
            raise ValueError("kind required")
        place = str(place or "").strip()
        if place not in self.places:
            raise ValueError(f"unknown place {place!r}")
        cap = self._props_max_population()
        events: list[dict] = []
        for _ in range(max(0, int(count))):
            if cap > 0 and len(self.props) >= cap:
                break  # cap reached — return what we managed to place
            ordinal = sum(1 for p in self.props.values() if p.place == place)
            seed_ord = ordinal
            prop_id = self._prop_id(place, kind, seed_ord)
            while prop_id in self.props:
                seed_ord += 1
                prop_id = self._prop_id(place, kind, seed_ord)
            dx, dz = self._prop_offset(ordinal)
            prop = Prop(
                id=prop_id, kind=kind, place=place, dx=dx, dz=dz,
                owner_id=None, created_tick=self.tick,
            )
            self.props[prop.id] = prop
            events.append({
                "kind": "prop_placed",
                "actor_id": "god",
                "text": f"A {kind} appears at {self.places[place].name}.",
                "payload": {
                    "prop_id": prop.id,
                    "kind": prop.kind,
                    "place": prop.place,
                    "owner_id": prop.owner_id,
                },
            })
        return events

    def god_clear_props(self, place: str | None = None) -> list[dict]:
        """Remove props at `place`, or ALL props when `place` is None. Reuses the
        same registry mutation as action_remove_prop (a plain del) — no ownership
        gate (god override). Raises ValueError on an unknown `place` so the API can
        4xx. Returns one prop_removed event per prop cleared."""
        if place is not None:
            place = str(place).strip()
            if place not in self.places:
                raise ValueError(f"unknown place {place!r}")
        targets = [
            p for p in self.props.values()
            if place is None or p.place == place
        ]
        events: list[dict] = []
        for prop in targets:
            del self.props[prop.id]
            events.append({
                "kind": "prop_removed",
                "actor_id": "god",
                "text": f"The {prop.kind} vanishes.",
                "payload": {
                    "prop_id": prop.id,
                    "kind": prop.kind,
                    "place": prop.place,
                },
            })
        return events

    def god_demolish(self, building_id: str) -> dict:
        """God OVERRIDE demolish: immediate, regardless of owner/landmark/
        governance. Reuses the shared _demolish_building path (same status flip +
        lot free) the owner tool and the governance effect use, so the god demolish
        is byte-identical in snapshots. Raises ValueError (unknown / already
        rubble) so the API can 4xx. Returns the building_demolished event (by
        'god')."""
        building = self.buildings.get(str(building_id))
        if building is None:
            raise ValueError("building_not_found")
        if building.status == "destroyed":
            raise ValueError("already destroyed")
        return self._demolish_building(building, "god", "god")

    def god_reskin(self, building_id: str, skin: str) -> dict:
        """God re-skins ANY building (override — no owner gate), reusing the exact
        skin field + clamp of action_set_building_skin. An empty skin clears it
        back to the default. Raises ValueError (unknown building) so the API can
        4xx. Returns the building_reskinned event."""
        building = self.buildings.get(str(building_id))
        if building is None:
            raise ValueError("building_not_found")
        skin = str(skin or "").strip()[:24]
        building.skin = skin or None
        building.updated_tick = self.tick
        return {
            "kind": "building_reskinned",
            "actor_id": "god",
            "target_id": building.id,
            "text": f"{building.name} is re-skinned"
                    + (f" in {skin}." if skin else " back to its plain finish."),
            "payload": {
                "building_id": building.id,
                "skin": building.skin,
            },
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Social actions
    # ──────────────────────────────────────────────────────────────────────────

    def action_insult(self, agent: AgentState, target: AgentState) -> tuple[bool, str]:
        if agent.location != target.location:
            return False, "target not co-located"
        self._update_trust(agent, target, -10)
        self._update_trust(target, agent, -5)
        return True, "ok"

    def action_attack(self, agent: AgentState, target: AgentState) -> tuple[bool, str]:
        if agent.location != target.location:
            return False, "target not co-located"
        cost = self.params.attack_energy_cost
        agent.energy = max(0.0, agent.energy - cost)
        target.energy = max(0.0, target.energy - cost)
        self._update_trust(agent, target, -20)
        self._update_trust(target, agent, -20)
        return True, "ok"

    def action_set_relationship(
        self, agent: AgentState, target: AgentState, rel_type: str
    ) -> tuple[bool, str]:
        # Wave E / EM-113 — full vocabulary with guards. `family` is
        # engine-assigned only (births, EM-114); `partner` is trust-gated.
        if rel_type == "family":
            return False, ("family ties are made by birth, not declaration — "
                           "you cannot declare someone family")
        if rel_type not in DECLARABLE_RELATIONSHIP_TYPES:
            return False, f"invalid relationship type: {rel_type!r}"
        rel = agent.relationships.get(target.id)
        if rel_type == "partner":
            threshold = int(self._rel_param("partner_trust_threshold", 40))
            trust = rel.trust if rel is not None else 0
            if trust < threshold:
                return False, (f"you barely know them — build trust to "
                               f"{threshold} (now {trust}) before declaring "
                               f"{target.name} your partner")
        if rel is None:
            rel = RelationshipState()
            agent.relationships[target.id] = rel
        if rel.type != rel_type:
            from_type = rel.type
            rel.type = rel_type
            rel.since_tick = self.tick
            # EM-113 — accepted type change emits relationship_changed via the
            # outbox (rides the declaring action's turn chain).
            self.pending_relationship_events.append(
                self._relationship_changed_event(agent, target, from_type, rel)
            )
        return True, "ok"

    def action_remember(self, agent: AgentState, fact: str) -> tuple[bool, str]:
        if fact not in agent.beliefs:
            agent.beliefs.append(fact)
            if len(agent.beliefs) > 20:
                agent.beliefs.pop(0)  # FIFO cap
        return True, "ok"

    # ──────────────────────────────────────────────────────────────────────────
    # Governance
    # ──────────────────────────────────────────────────────────────────────────

    # EM-108 — civic actions are location-gated at RESOLUTION time, mirroring
    # the billboard gate (billboard_here): the prompt already hides
    # propose_rule/vote away from governance places, but a prompt-ignoring
    # model must not legislate from anywhere.
    GOVERNANCE_GATE_MESSAGE = "civic actions happen at the town hall — move there first"

    def governance_here(self, place_id: str) -> bool:
        """EM-108 — true when civic actions (propose_rule / vote) are reachable
        from this place: its kind is "governance" (the procgen invariant makes
        the first governance place id "townhall", but the gate is on kind,
        never the hardcoded id). Worlds with NO governance place at all
        (legacy / hand-rolled layouts) are exempt — civic life cannot require
        a town hall that does not exist."""
        p = self.places.get(place_id)
        if p is not None and p.kind == "governance":
            return True
        return not any(pl.kind == "governance" for pl in self.places.values())

    def action_propose_rule(
        self, agent: AgentState, effect: str, text: str,
        name: str | None = None, target: str | None = None,
        image_id: str | None = None,
    ) -> tuple[bool, str, RuleState | None]:
        # EM-108 — only AgentState actors are location-bound; god paths
        # (enqueue_admit_agent / post_*_as_god) never come through here.
        if not self.governance_here(agent.location):
            return False, self.GOVERNANCE_GATE_MESSAGE, None
        # W9 / EM-073 B3: ban_arson included so the arson ban is reachable via
        # governance (enforcement already gates arson in the runtime validator).
        # PROTOTYPE (god-channel): name_town — naming the town by consensus vote.
        # Wave K / EM-219: demolish — a PUBLIC/landmark structure is demolished by
        # consensus (the orderly civic counterpart to a lone owner's demolish).
        # Wave I / EM-212: promote_image — the town VOTES a gallery image onto the
        # plaza banner. Carries the image_id on the payload (like demolish's target);
        # scoped per-image so two distinct images may have open votes at once.
        # EM-240 (Task 11) — trial is a governance proposal effect: an enforcer
        # escalates a suspect to a town-hall vote. It carries the defendant id on
        # the payload (like demolish's target) and reuses the existing vote
        # machinery (NO new tally code) — a passing vote convicts, a rejected one
        # acquits (see _on_rule_activated / action_vote).
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus",
                         "ban_arson", "ban_extortion", "ban_vandalism",
                         "name_town", "demolish", "promote_image", "trial"}
        if effect not in valid_effects:
            return False, f"invalid effect: {effect!r}", None
        # name_town carries the proposed name on the payload (like admit_agent);
        # a naming proposal is meaningless without one.
        payload: dict[str, Any] = {}
        if effect == "name_town":
            name = str(name or "").strip()[:60]
            if not name:
                return False, "name_town requires a name", None
            # run-663 — reject a no-op rename to the name the town already has,
            # so the SAME naming can't re-pass forever (the live run renamed the
            # town "Ledger's Folly" 119 times — 53% of all "laws" were no-ops).
            if name.lower() == str(self.town_name or "").strip().lower():
                return False, f"the town is already named {self.town_name!r}", None
            payload = {"name": name}
        # Wave K / EM-219 — demolish carries the TARGET building id on the payload
        # (like admit_agent's spec); a demolish proposal without a real, standing
        # target is meaningless.
        if effect == "demolish":
            target = str(target or "").strip()
            building = self.buildings.get(target)
            if building is None:
                return False, f"demolish requires a real building id (got {target!r})", None
            if building.status == "destroyed":
                return False, f"{building.name} is already rubble", None
            payload = {"target": target}
        # Wave I / EM-212 — promote_image carries the gallery image_id on the payload
        # (like demolish's target); a promotion of an image that does not exist is
        # meaningless. The id may also arrive via the generic `target` arg (the
        # runtime maps either key), so accept both.
        if effect == "promote_image":
            image_id = str(image_id or target or "").strip()
            if not image_id:
                return False, "promote_image requires an image_id", None
            if not any(g.get("image_id") == image_id for g in self.gallery):
                return False, f"promote_image requires a real image id (got {image_id!r})", None
            # FINDING 4 — reject a no-op re-promotion of the image ALREADY on the
            # banner (mirrors the name_town current-name guard and demolish's
            # already-rubble guard), so the SAME promotion can't re-pass forever
            # (the run-663 name_town spam pattern).
            if image_id == self.plaza_banner_ref:
                return False, "that image already hangs over the plaza", None
            payload = {"image_id": image_id}
        # EM-240 (Task 11) — trial carries the DEFENDANT id on the payload (like
        # demolish's target). A trial of an unknown/dead defendant, or one already
        # detained/jailed, is meaningless — reject it. The per-defendant duplicate
        # guard lives in the OPEN-proposal loop below (mirrors demolish/promote_image).
        if effect == "trial":
            target = str(target or "").strip()
            # Task 12a — agents see NAMES, not ids. Resolve the defendant by id
            # FIRST; if that misses, resolve by display name (case-insensitive,
            # must be ALIVE, prefer the LOWEST id on ties) so an enforcer who
            # names the defendant can actually start a trial. The payload always
            # carries the RESOLVED id (downstream conviction/acquittal look it up).
            defendant = self.agents.get(target)
            if defendant is None and target:
                wanted = target.lower()
                defendant = next(
                    (a for a in sorted(self.living_agents(), key=lambda x: x.id)
                     if str(a.name).strip().lower() == wanted),
                    None,
                )
            if defendant is None or not defendant.alive:
                return False, f"trial requires a living defendant (got {target!r})", None
            if defendant.crime_status in ("detained", "jailed"):
                return False, f"{defendant.name} is already in custody", None
            payload = {"defendant_id": defendant.id, "charges": str(text)[:200]}
        # Duplicate guard: only one OPEN proposal per effect at a time. EXCEPTION:
        # demolish is scoped per TARGET (two distinct buildings may have open
        # demolish votes at once) — only a duplicate vote for the SAME target is
        # blocked. Wave I / EM-212: promote_image is scoped per IMAGE_ID the same
        # way (two distinct images may have open votes; the SAME image may not be
        # double-proposed).
        for rule in self.rules.values():
            if rule.effect != effect or rule.status != "proposed":
                continue
            if effect == "demolish":
                if (rule.payload or {}).get("target") == payload.get("target"):
                    return False, f"a demolish vote for {payload.get('target')!r} is already open", None
                continue
            if effect == "promote_image":
                if (rule.payload or {}).get("image_id") == payload.get("image_id"):
                    return False, f"a promote vote for {payload.get('image_id')!r} is already open", None
                continue
            # EM-240 (Task 11) — trial is scoped per DEFENDANT (two distinct
            # defendants may have open trials at once); only a duplicate trial for
            # the SAME defendant is blocked (mirrors demolish/promote_image).
            if effect == "trial":
                if (rule.payload or {}).get("defendant_id") == payload.get("defendant_id"):
                    return False, f"{payload.get('defendant_id')!r} already has an open trial", None
                continue
            return False, f"rule with effect {effect!r} already proposed", None
        # W11b / EM-087 — re-proposing an effect identical to an ACTIVE rule is a
        # RENEWAL of that rule, not a new stackable law. The proposal is allowed
        # (civic ritual is the charm) but tagged renewal_of; on passing it
        # refreshes the existing rule instead of activating a duplicate.
        # EXCEPTION: name_town is a one-shot RENAME, and demolish is a one-shot
        # ACT (each targets a distinct building) — neither "renews"; each passing
        # vote is fresh. EM-240: trial is a one-shot ACT per defendant (same as
        # demolish) — a conviction/acquittal is applied once, never "renewed".
        active = (
            self._active_rule(effect)
            if effect not in ("name_town", "demolish", "promote_image", "trial") else None
        )
        rule = RuleState(
            id=f"r_{str(uuid.uuid4())[:8]}",  # run-663: prefixed so a rule id is never all-numeric (votable-as-int)
            effect=effect,
            text=text,
            proposer_id=agent.id,
            created_tick=self.tick,
            renewal_of=active.id if active is not None else None,
            payload=payload,
        )
        self.rules[rule.id] = rule
        return True, "ok", rule

    def action_vote(
        self, agent: AgentState, rule_id: str, choice: bool
    ) -> tuple[bool, str, str | None]:
        """Returns (success, reason, new_status_if_changed)."""
        # EM-199 — voting is NO LONGER location-gated. EM-108 required Town Hall
        # presence, but agents cluster elsewhere and never travel, so proposals
        # never reached a majority (run 648: only the proposer voted). Civic
        # participation now works from anywhere; PROPOSING a rule still requires
        # Town Hall (action_propose_rule keeps its gate).
        rule = self.rules.get(rule_id)
        if rule is None:
            return False, f"unknown rule {rule_id!r}", None
        if rule.status != "proposed":
            return False, f"rule {rule_id!r} is {rule.status!r}, not proposed", None

        rule.votes[agent.id] = choice
        new_status = self._evaluate_rule(rule)
        if new_status and new_status != rule.status:
            if new_status == "active":
                # W11b / EM-087 — RENEWAL: if an identical effect is already
                # active, refresh THAT rule (renewed_at gains the tick) instead
                # of stacking a second active copy. Invariant: the world never
                # holds two simultaneously-active identical effects.
                # name_town is a one-shot rename, not a stackable law — it never
                # "renews"; a passing name supersedes whatever the town was called.
                # EM-240: trial is a one-shot per-defendant ACT (like demolish) —
                # it never "renews"; each passing guilty vote convicts afresh.
                existing = (
                    self._active_rule(rule.effect)
                    if rule.effect not in ("name_town", "promote_image", "trial") else None
                )
                if existing is not None and existing.id != rule.id:
                    rule.status = "renewed"
                    existing.renewed_at.append(self.tick)
                    return True, "ok", "renewed"
                rule.status = "active"
                self._on_rule_activated(rule)
                return True, "ok", "active"
            # EM-240 (Task 11) — a REJECTED trial is an ACQUITTAL: clear some of
            # the defendant's notoriety and dock the accuser's standing with the
            # onlookers/jurors who voted. Done before the status assignment so the
            # rule's votes/payload/proposer are all still intact. Reuses the
            # existing vote tally (new_status == "rejected") — NO new tally code.
            if rule.effect == "trial" and new_status == "rejected" and not rule.applied:
                self._on_trial_acquitted(rule)
            rule.status = new_status
            return True, "ok", new_status
        return True, "ok", None

    def _on_rule_activated(self, rule: RuleState) -> None:
        """Side effects of a rule becoming active. For W7/EM-062 governance spawn:
        an `admit_agent` rule carries the pending agent spec on `rule.payload`;
        the moment it activates we spawn that agent and park an
        `agent_spawned{method:governance, proposal_id}` event in the outbox for the
        runtime/api layer to drain and emit. Other effects (ubi/work_bonus/...) are
        passive and read elsewhere, so nothing to do here."""
        if rule.applied:
            return
        # PROTOTYPE (god-channel) — name_town: a passing naming vote sets the
        # town's name and parks a `town_named` event in the outbox (drained +
        # emitted by the loop's _flush_spawn_events, same path as governance spawn).
        if rule.effect == "name_town":
            name = (rule.payload or {}).get("name")
            rule.applied = True
            if name:
                self.town_name = str(name)
                self.pending_spawn_events.append({
                    "kind": "town_named",
                    "actor_id": "system",
                    "actor_type": "system",
                    "text": f"🏛 By vote, the town is now named {self.town_name}.",
                    "payload": {"name": self.town_name, "proposal_id": rule.id},
                })
            return
        # Wave K / EM-219 — demolish: a passing public-demolish vote tears down the
        # target building. The building_demolished event is parked in the SAME
        # outbox name_town/governance-spawn use (drained + emitted by the loop's
        # _flush_spawn_events). by="governance" records the civic authority; a
        # missing/already-rubble target is a silent no-op (the vote still applied).
        if rule.effect == "demolish":
            rule.applied = True
            target = (rule.payload or {}).get("target")
            building = self.buildings.get(target)
            if building is not None and building.status != "destroyed":
                evt = self._demolish_building(building, "system", "governance")
                evt["actor_type"] = "system"
                evt["payload"]["proposal_id"] = rule.id
                self.pending_spawn_events.append(evt)
            return
        # Wave I / EM-213 — promote_image: a passing vote hangs the gallery image
        # over the plaza. Sets plaza_banner_ref, marks the record promoted=True, and
        # parks an `image_promoted` system event in the SAME outbox name_town/demolish
        # use (drained + emitted by the loop's _flush_spawn_events). A vanished image
        # is a silent no-op (the vote still applied).
        if rule.effect == "promote_image":
            rule.applied = True
            image_id = (rule.payload or {}).get("image_id")
            record = next(
                (g for g in self.gallery if g.get("image_id") == image_id), None)
            if record is not None:
                self.plaza_banner_ref = str(image_id)
                record["promoted"] = True
                proposer = self.agents.get(record.get("proposer_id"))
                proposer_name = proposer.name if proposer else "an artist"
                self.pending_spawn_events.append({
                    "kind": "image_promoted",
                    "actor_id": "system",
                    "actor_type": "system",
                    "text": f"🖼 By vote, {proposer_name}'s image now hangs over the plaza.",
                    "payload": {
                        "image_id": str(image_id),
                        "url": str(record.get("url", "")),
                        "proposal_id": rule.id,
                    },
                })
            return
        # EM-240 (Task 11) — trial CONVICTION: a passing guilty vote jails the
        # defendant for trial_sentence, confiscates trial_fine, and pays restitution
        # split evenly across the DISTINCT living victims on the defendant's rap
        # sheet (remainder dropped). Parks trial_verdict(guilty) + jailed in the
        # SAME outbox name_town/demolish use (drained by the loop). Reuses
        # _jail_place_id (Task 10). A vanished defendant is a silent no-op.
        if rule.effect == "trial":
            rule.applied = True
            defendant = self.agents.get((rule.payload or {}).get("defendant_id"))
            if defendant is None:
                return
            sentence = int(self._crime_param("trial_sentence", 20))
            fine = min(defendant.credits, int(self._crime_param("trial_fine", 25)))
            defendant.credits -= fine
            jail = self._jail_place_id()
            if jail is not None:
                defendant.location = jail
            defendant.crime_status = "jailed"
            defendant.crime_status_until_tick = self.tick + sentence
            # Restitution: split the fine evenly across distinct living victims.
            victim_ids: list[str] = []
            for e in defendant.rap_sheet:
                vid = e.get("victim_id")
                v = self.agents.get(vid) if vid else None
                if v is not None and v.alive and vid not in victim_ids:
                    victim_ids.append(vid)
            if victim_ids and fine > 0:
                share = fine // len(victim_ids)
                if share > 0:
                    for vid in victim_ids:
                        self.agents[vid].credits += share
            self.pending_spawn_events.append({
                "kind": "trial_verdict",
                "actor_id": "system",
                "actor_type": "system",
                "target_id": defendant.id,
                "text": f"⚖ By vote, {defendant.name} is found GUILTY and jailed.",
                "payload": {"verdict": "guilty", "fine": fine,
                            "sentence": sentence, "proposal_id": rule.id},
            })
            self.pending_spawn_events.append({
                "kind": "jailed",
                "actor_id": "system",
                "actor_type": "system",
                "target_id": defendant.id,
                "text": f"{defendant.name} is led to jail for {sentence} ticks.",
                "payload": {"until_tick": defendant.crime_status_until_tick},
            })
            return
        if rule.effect != "admit_agent":
            return
        spec = rule.payload or {}
        name = spec.get("name")
        if not name:
            rule.applied = True
            return
        location = spec.get("location") or next(iter(self.places), "")
        if location not in self.places and self.places:
            location = next(iter(self.places))
        agent = self.spawn_agent(
            name=str(name),
            personality=str(spec.get("personality", "")),
            profile=str(spec.get("profile", "mock")),
            location=str(location),
            # Wave D2 / EM-158 — optional tier on the admit_agent spec
            # (additive; absent pre-D2 proposals spawn protagonists).
            cadence_tier=str(spec.get("cadence_tier", "protagonist")),
        )
        rule.applied = True
        self.pending_spawn_events.append({
            "kind": "agent_spawned",
            "actor_id": agent.id,
            "actor_type": "system",
            "text": f"{agent.name} is admitted to the world by vote.",
            "payload": {
                "method": "governance",
                "proposal_id": rule.id,
                "agent_id": agent.id,
                "name": agent.name,
                "profile": agent.profile,
                "location": agent.location,
            },
        })

    def _on_trial_acquitted(self, rule: RuleState) -> None:
        """EM-240 (Task 11) — a REJECTED trial is an ACQUITTAL. Clear some of the
        defendant's notoriety (acquittal_notoriety_relief) and clear a now-cool
        `wanted` flag (Task 7's _clear_wanted_if_cool), then dock the accuser's
        standing (accuser_acquittal_penalty trust) with the onlookers/jurors of the
        proceeding. Parks a trial_verdict(acquitted) event. Idempotent via
        rule.applied. The 'onlookers' = the people who VOTED on the trial (the
        jurors who watched it) PLUS anyone physically co-located with the accuser —
        a faithful read of 'co-located onlookers' that also covers jurors who voted
        from elsewhere (voting is no longer location-gated, EM-199)."""
        if rule.applied:
            return
        rule.applied = True
        defendant = self.agents.get((rule.payload or {}).get("defendant_id"))
        accuser = self.agents.get(rule.proposer_id)
        if defendant is not None:
            defendant.notoriety = max(
                0, defendant.notoriety -
                int(self._crime_param("acquittal_notoriety_relief", 15)))
            self._clear_wanted_if_cool(defendant)
        if accuser is not None:
            pen = int(self._crime_param("accuser_acquittal_penalty", 8))
            # Onlookers: trial voters (jurors who watched the proceeding) + anyone
            # standing with the accuser. Dedup, and never dock the accuser or the
            # defendant themselves.
            onlooker_ids = set(rule.votes.keys())
            onlooker_ids.update(a.id for a in self.agents_at(accuser.location))
            onlooker_ids.discard(accuser.id)
            if defendant is not None:
                onlooker_ids.discard(defendant.id)
            for oid in onlooker_ids:
                onlooker = self.agents.get(oid)
                if onlooker is not None and onlooker.alive:
                    self._update_trust(onlooker, accuser, -pen)
        self.pending_spawn_events.append({
            "kind": "trial_verdict",
            "actor_id": "system",
            "actor_type": "system",
            "target_id": defendant.id if defendant else None,
            "text": (f"⚖ By vote, {defendant.name if defendant else 'the accused'} "
                     "is ACQUITTED."),
            "payload": {"verdict": "acquitted", "proposal_id": rule.id},
        })

    def drain_spawn_events(self) -> list[dict]:
        """Pop and return any queued governance-spawn events (EM-062). The runtime
        /api layer calls this after a vote (or each turn) and emits them through the
        normal pipeline. Idempotent — returns [] when empty."""
        out = self.pending_spawn_events
        self.pending_spawn_events = []
        return out

    def enqueue_admit_agent(
        self,
        proposer_id: str,
        name: str,
        personality: str,
        profile: str,
        location: str,
        text: str | None = None,
        cadence_tier: str = "protagonist",
    ) -> RuleState:
        """Create an `admit_agent` governance proposal (EM-062 governance spawn).
        The pending agent spec rides on rule.payload; the agent enters only if the
        vote passes threshold (handled in _on_rule_activated). Used by the
        POST /api/agents governance path (runtime-api-agent)."""
        rule = RuleState(
            id=f"r_{str(uuid.uuid4())[:8]}",  # run-663: prefixed so a rule id is never all-numeric (votable-as-int)
            effect="admit_agent",
            text=text or f"Admit {name} to the village.",
            proposer_id=proposer_id,
            created_tick=self.tick,
            payload={
                "name": name,
                "personality": personality,
                "profile": profile,
                "location": location,
                # Wave D2 / EM-158 — additive; protagonist when unspecified.
                "cadence_tier": (
                    cadence_tier if cadence_tier in self.CADENCE_TIERS
                    else "protagonist"
                ),
            },
        )
        self.rules[rule.id] = rule
        return rule

    def _evaluate_rule(self, rule: RuleState) -> str | None:
        """Check if rule should become active or rejected based on votes."""
        living = self.living_agents()
        living_count = len(living)
        if living_count == 0:
            return None

        living_ids = {a.id for a in living}
        yes_votes = sum(1 for aid, v in rule.votes.items() if v and aid in living_ids)
        no_votes = sum(1 for aid, v in rule.votes.items() if not v and aid in living_ids)

        # Wave K / EM-219 — a public/landmark `demolish` is irreversible (it tears
        # down a standing structure), so it requires a ~70% SUPERMAJORITY rather
        # than the simple strict majority ordinary rules pass on (the user's locked
        # decision + design spec + contract wave-k.md §3). Ordinary effects keep
        # their existing bar.
        if rule.effect == "demolish":
            yes_needed = math.ceil(0.7 * living_count)
            if yes_votes >= yes_needed:
                return "active"
            # The vote fails once a yes-supermajority is mathematically out of reach
            # (everyone still unvoted couldn't carry it). Handled by the all-voted
            # fall-through below; here we only ACTIVATE early on a clear pass.
            no_threshold = living_count // 2
            if no_votes > no_threshold:
                return "rejected"
            voted = sum(1 for aid in rule.votes if aid in living_ids)
            if voted >= living_count:
                return "rejected"
            return None

        threshold = living_count // 2  # strict majority: > floor(living/2)
        if yes_votes > threshold:
            return "active"
        if no_votes > threshold:
            return "rejected"

        # If all living agents have voted but no majority
        voted = sum(1 for aid in rule.votes if aid in living_ids)
        if voted >= living_count:
            # No majority achieved
            return "rejected"
        return None

    # ──────────────────────────────────────────────────────────────────────────
    # W7 / EM-061 — building actions (== collective-project pipeline)
    #
    # Each method mirrors action_work/give/steal in spirit but, because these are
    # NEW actions whose dispatch belongs to runtime-api-agent, they return a fully
    # formed event dict (kind/actor_id/target_id?/text/payload) ready to emit —
    # or {"_multi": [evt, ...]} when one action causes several events (e.g. a
    # contribution that flips planned -> under_construction). The runtime layer
    # spreads its own base (profile/profile_color/tick) onto whatever is returned.
    # They never raise on bad ids; instead they return a parse_failure event so
    # the loop keeps turning. Heavy validation is runtime-api-agent's _validate_world.
    # ──────────────────────────────────────────────────────────────────────────

    def _structure_state_changed_event(
        self, building: Building, frm: str, to: str, reason: str, actor_id: str | None
    ) -> dict:
        return {
            "kind": "structure_state_changed",
            "actor_id": actor_id,
            "text": f"{building.name} is now {to} ({reason}).",
            "payload": {
                "building_id": building.id,
                "from": frm,
                "to": to,
                "reason": reason,
            },
        }

    @staticmethod
    def _fail_event(actor_id: str | None, action: str, reason: str, text: str) -> dict:
        return {
            "kind": "parse_failure",
            "actor_id": actor_id,
            "text": text,
            "payload": {"action": action, "error": reason},
        }

    # W11b / EM-103 — legislation-as-architecture: fuzzy name↔rule-text match.
    _COMMEMORATIVE_STOPWORDS = frozenset({
        "the", "and", "for", "our", "all", "are", "not", "you", "your", "this",
        "that", "with", "from", "have", "has", "will", "must", "should", "new",
        "every", "everyone", "town", "village", "place", "project", "building",
    })

    @classmethod
    def _significant_tokens(cls, text: str) -> set[str]:
        return {
            t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(t) >= 3 and t not in cls._COMMEMORATIVE_STOPWORDS
        }

    def _commemorated_rule(self, project_name: str) -> RuleState | None:
        """Return the active/proposed rule whose text the project name fuzzy-
        matches (normalized substring or >=2 significant shared tokens), if any.
        Kept deliberately simple per the contract."""
        norm_name = re.sub(r"[^a-z0-9]+", " ", str(project_name or "").lower()).strip()
        name_tokens = self._significant_tokens(project_name)
        for rule in self.rules.values():
            if rule.status not in ("active", "proposed"):
                continue
            norm_rule = re.sub(r"[^a-z0-9]+", " ", rule.text.lower()).strip()
            # A rule with NO law text (name_town / promote_image are action-rules
            # with empty text) has nothing to commemorate — skip it. Otherwise
            # `norm_rule in norm_name` is `"" in <name>` == True for EVERY project
            # ≥4 chars, so all proposals match the blank rule and get rejected as
            # duplicate monuments to a blank law "" (observed live, run 1050).
            if not norm_rule:
                continue
            if len(norm_name) >= 4 and (norm_name in norm_rule or norm_rule in norm_name):
                return rule
            if len(name_tokens & self._significant_tokens(rule.text)) >= 2:
                return rule
        return None

    def action_propose_project(
        self,
        agent: AgentState,
        name: str,
        kind: str,
        funds_required: int,
        function: str | None = None,
        place: str | None = None,
    ) -> dict:
        """Create a Building status=planned at owner=public.
        Emits structure_state_changed{to:planned} + project_proposed.

        Wave K / EM-182: an OPTIONAL `place` arg lets the agent build in a CHOSEN
        district ("build a house in the industrial district"). When `place` is a
        valid place id the new Building's location is that place; otherwise (absent
        / unknown) it falls back to the agent's current location (the pre-K
        behavior) — so a bad place never wastes the turn.

        W11b / EM-103: a project whose name fuzzy-matches an active/proposed
        rule's text is a COMMEMORATIVE monument to that rule (tagged
        commemorative:true + rule_id). At most ONE monument per rule — a second
        match is rejected at proposal with an explanatory feed line."""
        try:
            funds_required = max(0, int(funds_required))
        except (TypeError, ValueError):
            funds_required = 0
        # EM-129 — Building.name stores a humanized DISPLAY name (snake_case →
        # "Title Case"); junk names fall back to "<Agent>'s <Kind>" (kind
        # humanized the same way; junk kind → "Project"). The raw model arg is
        # preserved in the project_proposed payload as raw_name (additive).
        # `kind` itself stays a raw key — the frontend maps it (EM-130).
        raw_name = str(name)[:60]
        display_name = _humanize_project_name(name)
        if not display_name:
            display_name = (
                f"{agent.name}'s {_humanize_project_name(kind) or 'Project'}"[:60]
            )
        rule = self._commemorated_rule(display_name)
        if rule is not None:
            already = any(
                b.commemorates == rule.id and b.status != "destroyed"
                for b in self.buildings.values()
            )
            if already:
                return self._fail_event(
                    agent.id, "propose_project", "commemorative_duplicate",
                    f"{agent.name}'s proposal {display_name!r} honors the law "
                    f"\"{_truncate(rule.text)}\" — but a monument to that rule "
                    f"already stands. One monument per law; propose something new.")
        # Wave K / EM-182 — honor a valid chosen `place`; else build at the
        # agent's current location (the pre-K default). An unknown place id is
        # silently ignored (falls back) so the turn is never wasted.
        build_location = agent.location
        chosen = str(place or "").strip()
        if chosen and chosen in self.places:
            build_location = chosen
        building = Building(
            id=f"bld_{str(uuid.uuid4())[:8]}",
            name=display_name,
            kind=str(kind)[:30],
            location=build_location,
            owner_id="public",
            status="planned",
            funds_required=funds_required,
            function=(function or "")[:40],
            last_progress_tick=self.tick,
            created_tick=self.tick,
            updated_tick=self.tick,
            commemorates=rule.id if rule is not None else None,
        )
        self.buildings[building.id] = building
        commemorative_note = (
            f" — commemorating the law \"{_truncate(rule.text)}\""
            if rule is not None else ""
        )
        proposed_evt = {
            "kind": "project_proposed",
            "actor_id": agent.id,
            "text": f"{agent.name} proposes a {building.kind}: {building.name} "
                    f"(needs {funds_required} credits){commemorative_note}.",
            "payload": {
                "building_id": building.id,
                "name": building.name,
                "raw_name": raw_name,
                "kind": building.kind,
                "location": building.location,
                "funds_required": funds_required,
                "function": building.function,
            },
        }
        if rule is not None:
            proposed_evt["payload"]["commemorative"] = True
            proposed_evt["payload"]["rule_id"] = rule.id
        state_evt = self._structure_state_changed_event(
            building, "none", "planned", "proposed", agent.id
        )
        return {"_multi": [proposed_evt, state_evt], "_building_id": building.id}

    def action_contribute_funds(
        self, agent: AgentState, building_id: str, amount: int
    ) -> dict:
        """Move `amount` credits agent -> funds_committed; add contributor. If
        funds_committed >= funds_required, flip planned -> under_construction.
        Emits economy + project_funded (+ structure_state_changed on the flip)."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "contribute_funds", "building_not_found",
                f"{agent.name} tried to fund an unknown project.")
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            amount = 0
        if amount <= 0:
            return self._fail_event(
                agent.id, "contribute_funds", "amount must be positive",
                f"{agent.name} tried to contribute a non-positive amount.")
        # EM-133 — clamp the contribution at the remaining funding gap so
        # funds_committed can never overshoot funds_required (the 12/5 booth).
        # Only the clamped amount leaves the agent; a zero gap fails softly
        # with guidance (costing nothing) instead of swallowing credits.
        gap = max(0, building.funds_required - building.funds_committed)
        if gap == 0:
            return self._fail_event(
                agent.id, "contribute_funds", "already fully funded",
                f"{building.name} is already fully funded — it needs build_step now.")
        applied = min(amount, gap)
        if agent.credits < applied:
            return self._fail_event(
                agent.id, "contribute_funds",
                f"insufficient credits: have {agent.credits}, need {applied}",
                f"{agent.name} cannot afford to contribute {applied} credits.")

        agent.credits -= applied
        building.funds_committed += applied
        if agent.id not in building.contributors:
            building.contributors.append(agent.id)
        building.updated_tick = self.tick

        clamp_note = (
            f" (offered {amount}; clamped at the remaining gap)"
            if applied < amount else ""
        )
        economy_evt = {
            "kind": "economy",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} contributes {applied} credits to "
                    f"{building.name}{clamp_note}.",
            "payload": {
                "action": "contribute_funds",
                "building_id": building.id,
                "amount": applied,
                "amount_requested": amount,
                "amount_applied": applied,
                "credits_delta": -applied,
                "funds_committed": building.funds_committed,
                "funds_required": building.funds_required,
            },
        }
        funded_evt = {
            "kind": "project_funded",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{building.name} funding at "
                    f"{building.funds_committed}/{building.funds_required}.",
            "payload": {
                "building_id": building.id,
                "funds_committed": building.funds_committed,
                "funds_required": building.funds_required,
                "fully_funded": building.funds_committed >= building.funds_required,
            },
        }
        events = [economy_evt, funded_evt]
        # Flip planned -> under_construction once fully funded (the first build_step
        # then begins progress per the state machine).
        if (
            building.status == "planned"
            and building.funds_required > 0
            and building.funds_committed >= building.funds_required
        ):
            building.status = "under_construction"
            building.updated_tick = self.tick
            building.last_progress_tick = self.tick
            events.append(self._structure_state_changed_event(
                building, "planned", "under_construction", "fully funded", agent.id))
        return {"_multi": events}

    def action_build_step(self, agent: AgentState, building_id: str) -> dict:
        """progress += buildings.build_step; sets last_progress_tick. If a planned
        building is already fully funded, advance it to under_construction first.
        At progress>=100 -> operational (function activates). Emits project_built
        (+ structure_state_changed / building_operational on transitions)."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "build_step", "building_not_found",
                f"{agent.name} tried to build an unknown project.")
        if building.status in ("operational", "destroyed", "abandoned"):
            return self._fail_event(
                agent.id, "build_step", f"cannot build a {building.status} structure",
                f"{agent.name} cannot build {building.name} ({building.status}).")
        # EM-132 — a build_step aimed at a DAMAGED building is unambiguous
        # intent to fix it: redirect to the existing repair path (no wasted
        # turn, no duplicated repair logic) and make the switch legible in the
        # feed. Other invalid statuses keep failing above/below as before.
        if building.status == "damaged":
            result = self.action_repair(agent, building_id)
            for evt in result.get("_multi", []):
                if evt.get("kind") == "economy":
                    evt["text"] = (
                        f"{agent.name} went to build {building.name}, found it "
                        f"damaged, and switched to repairing it instead.")
                    evt["payload"]["redirected_from"] = "build_step"
            return result

        events: list[dict] = []
        # A first build_step on a fully-funded planned building begins construction.
        if (
            building.status == "planned"
            and building.funds_committed >= building.funds_required
        ):
            building.status = "under_construction"
            events.append(self._structure_state_changed_event(
                building, "planned", "under_construction", "construction begun", agent.id))

        if building.status not in ("under_construction",):
            return self._fail_event(
                agent.id, "build_step", "project is not under construction",
                f"{agent.name} cannot build {building.name} yet (not funded).")

        step = self._bld_param("build_step", 20)
        building.progress = min(100, building.progress + int(step))
        building.last_progress_tick = self.tick
        building.updated_tick = self.tick

        built_evt = {
            "kind": "project_built",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} works on {building.name} "
                    f"({building.progress}% built).",
            "payload": {
                "action": "build_step",
                "building_id": building.id,
                "progress": building.progress,
                "step": int(step),
            },
        }
        events.append(built_evt)

        if building.progress >= 100:
            events.extend(self._complete_construction(building, "completed", agent.id))
        return {"_multi": events}

    def _complete_construction(
        self, building: Building, reason: str, actor_id: str | None
    ) -> list[dict]:
        """Shared completion path (EM-115): flip an under_construction building to
        operational (progress clamped to 100, health restored) and return the
        structure_state_changed + building_operational events. Used by BOTH the
        agent `build_step` action and the per-round auto-build reflex in
        advance_buildings(), so the event kinds/payload keys stay identical and
        function activation (forage/work buffs via operational_building_at) works
        regardless of which path finished the job."""
        building.progress = 100
        building.status = "operational"
        building.health = 100
        building.updated_tick = self.tick
        events = [
            self._structure_state_changed_event(
                building, "under_construction", "operational", reason, actor_id),
            {
                "kind": "building_operational",
                "actor_id": actor_id,
                "target_id": building.id,
                "text": f"{building.name} is now operational"
                        + (f" ({building.function})" if building.function else "") + ".",
                "payload": {
                    "building_id": building.id,
                    "kind": building.kind,
                    "function": building.function,
                    "location": building.location,
                },
            },
        ]
        # Wave H3 / EM-208 — a ZOO auto-stocks with animals the moment it opens.
        # ADDITIVE + GUARDED: this hook fires ONLY for kind=="zoo"; every non-zoo
        # completion returns the SAME two events as before (byte-identical). The
        # stock is deterministic (seed off the building id + index) so a replay /
        # a re-completion of the same building id yields the identical menagerie.
        if building.kind == "zoo":
            events.extend(self._stock_zoo(building, actor_id))
        # EM-123 — a completed megaproject deepens its zoned district (tier++ on
        # crossing the completions threshold). ADDITIVE + GUARDED: returns []
        # (byte-identical completion) when growth is disabled, the place is
        # un-districted, or the tier is maxed. EM-174-safe — no filler building.
        events.extend(self._grow_district(building))
        return events

    def _stock_zoo(self, building: Building, actor_id: str | None) -> list[dict]:
        """Wave H3 / EM-208 — populate a freshly-operational zoo. Spawns up to
        buildings.zoo_capacity catalog critters AT the zoo's place (housing =
        the same place), DETERMINISTICALLY (each pick seeds off the building id +
        an index via the runtime _seed_int — NO wall-clock / NO RNG), honoring
        the overall animals.max_population. Emits one animal_spawned with
        payload.method "zoo_stock" per spawned animal. Returns the event list
        (empty when the cap is already met or zoo_capacity is 0). Reuses
        spawn_random_animal then forces the new animal's location to the zoo."""
        # Import the seeded-hash helper here (not at module top) so engine.world
        # keeps its zero animal-runtime import dependency, matching
        # spawn_random_animal's catalog import.
        from ..animals.runtime import _seed_int
        capacity = int(self._bld_param("zoo_capacity", 5) or 0)
        if capacity <= 0:
            return []
        events: list[dict] = []
        for i in range(capacity):
            seed = _seed_int("zoo_stock", building.id, i)
            try:
                animal = self.spawn_random_animal(seed)
            except ValueError:
                # animals.max_population reached — stop stocking (no spam).
                break
            if animal is None:
                break  # no place to put it (empty world)
            # Housing = the zoo's place: the critter lives AT the zoo, overriding
            # the seed-derived place spawn_random_animal picked.
            animal.location = building.location
            events.append({
                "kind": "animal_spawned",
                "actor_id": animal.id,
                "actor_type": "animal",
                "text": f"{animal.name} the {animal.species} is brought to "
                        f"{building.name}.",
                "payload": {
                    "animal_id": animal.id,
                    "species": animal.species,
                    "name": animal.name,
                    "location": animal.location,
                    "method": "zoo_stock",
                    "building_id": building.id,
                },
            })
        return events

    def action_repair(self, agent: AgentState, building_id: str) -> dict:
        """Restore health to 100; damaged/offline -> operational."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "repair", "building_not_found",
                f"{agent.name} tried to repair an unknown structure.")
        if building.status not in ("damaged", "offline"):
            return self._fail_event(
                agent.id, "repair", f"nothing to repair ({building.status})",
                f"{agent.name} cannot repair {building.name} ({building.status}).")
        frm = building.status
        building.health = 100
        building.status = "operational"
        building.updated_tick = self.tick
        return {"_multi": [
            {
                "kind": "economy",
                "actor_id": agent.id,
                "target_id": building.id,
                "text": f"{agent.name} repairs {building.name}.",
                "payload": {
                    "action": "repair",
                    "building_id": building.id,
                    "health": building.health,
                },
            },
            self._structure_state_changed_event(
                building, frm, "operational", "repaired", agent.id),
        ]}

    def _damage_building(
        self, building: Building, amount: int, actor_id: str | None, reason: str
    ) -> dict:
        """Shared building-damage path (the W7 state machine, invariant 8). Applies
        `amount` damage with health CLAMPED to [0,100], flips operational/under_*/
        planned -> damaged, and damaged -> destroyed at health 0. Returns the
        structure_state_changed event dict for the transition (or None-state if the
        status did not change). Caller owns the accompanying domain event (conflict)
        + any witness-trust effects. Both human arson and animal arson go through
        here so invariant 8 holds identically for either actor."""
        frm = building.status
        # Clamp damage so we can never push health below 0 or above 100 (invariant 8).
        amount = max(0, int(amount))
        building.health = max(0, min(100, building.health - amount))
        building.updated_tick = self.tick
        if building.health <= 0:
            building.status = "destroyed"
        else:
            building.status = "damaged"
        return self._structure_state_changed_event(
            building, frm, building.status, reason, actor_id)

    def action_arson(self, agent: AgentState, building_id: str) -> dict:
        """Crime: health -= buildings.arson_damage -> damaged/destroyed. Lowers
        witness trust like steal. Emits conflict + structure_state_changed."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "arson", "building_not_found",
                f"{agent.name} tried to torch an unknown structure.")
        if building.status in ("destroyed",):
            return self._fail_event(
                agent.id, "arson", "already destroyed",
                f"{agent.name} cannot torch {building.name} (already rubble).")
        damage = int(self._bld_param("arson_damage", 50))
        state_evt = self._damage_building(building, damage, agent.id, "arson")

        # Crime: co-located witnesses lose trust in the arsonist (like steal).
        for witness in self.agents_at(building.location):
            if witness.id == agent.id:
                continue
            self._update_trust(witness, agent, -12)

        # EM-240 — witnessed-crime notoriety bookkeeping. Arson has no single
        # victim, so victim_id=None (every co-located non-actor is a witness).
        self._register_crime(agent, "arson", None,
                             int(self._crime_param("arson_notoriety", 22)))

        return {"_multi": [
            {
                "kind": "conflict",
                "actor_id": agent.id,
                "target_id": building.id,
                "text": f"{agent.name} commits arson on {building.name}!",
                "payload": {
                    "action": "arson",
                    "building_id": building.id,
                    "health": building.health,
                    "damage": damage,
                },
            },
            state_evt,
        ]}

    def action_take_offline(self, agent: AgentState, building_id: str) -> dict:
        """Owner-only: operational -> offline."""
        building = self.buildings.get(building_id)
        if building is None:
            return self._fail_event(
                agent.id, "take_offline", "building_not_found",
                f"{agent.name} tried to take an unknown structure offline.")
        if building.status != "operational":
            return self._fail_event(
                agent.id, "take_offline", f"not operational ({building.status})",
                f"{agent.name} cannot take {building.name} offline ({building.status}).")
        building.status = "offline"
        building.updated_tick = self.tick
        return self._structure_state_changed_event(
            building, "operational", "offline", "taken offline by owner", agent.id)

    # ──────────────────────────────────────────────────────────────────────────
    # W7 / EM-061 — per-round building lifecycle (called from the tick loop)
    # ──────────────────────────────────────────────────────────────────────────

    def advance_buildings(self) -> list[dict]:
        """Advance building lifecycle once per round. Returns the events to emit
        (the loop flushes them as standalone system events).

        EM-115 — deterministic city growth: every under_construction building
        gains buildings.auto_build_per_round progress (the village work crew —
        a zero-LLM reflex) and refreshes last_progress_tick, so a FUNDED project
        always finishes even if no agent ever picks build_step (intended
        semantics change: funded projects can no longer rot to abandoned while
        auto-build is on; set auto_build_per_round=0 to restore the old stall
        behavior). Interim progress is SILENT — events fire only on completion
        (via the shared _complete_construction helper, same payloads as the
        agent build_step path).

        Abandonment (W7 / EM-061) still applies to planned/unfunded + damaged
        stalls: no fund/build activity for buildings.abandon_after_ticks ->
        abandoned. This keeps the 'clock tower that never got funded' real."""
        events: list[dict] = []
        auto = int(self._bld_param("auto_build_per_round", 10))
        window = int(self._bld_param("abandon_after_ticks", 40))
        # Statuses that never rot: completed structures (operational/offline) and
        # terminal ones (abandoned/destroyed). An owner-offlined building was
        # built — it isn't "abandoned for no follow-through".
        skip = {"operational", "offline", "abandoned", "destroyed"}
        for building in self.buildings.values():
            if building.status in skip:
                continue
            # Auto-build reflex: funded (under_construction) projects always
            # creep forward; completion reuses the build_step completion path.
            if building.status == "under_construction" and auto > 0:
                building.progress = min(100, building.progress + auto)
                building.last_progress_tick = self.tick
                building.updated_tick = self.tick
                if building.progress >= 100:
                    events.extend(self._complete_construction(
                        building, "raised by the village work crew", None))
                continue
            # Stall rot: planned/unfunded (and damaged, and stalled
            # under_construction when auto-build is disabled) projects abandon
            # after the idle window.
            if window > 0 and self.tick - building.last_progress_tick > window:
                frm = building.status
                building.status = "abandoned"
                building.updated_tick = self.tick
                events.append(self._structure_state_changed_event(
                    building, frm, "abandoned", "no follow-through", None))
        return events

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-091 — the public billboard (reflex tools, zero LLM calls).
    # ──────────────────────────────────────────────────────────────────────────

    BILLBOARD_CAP = 20          # newest posts kept
    BILLBOARD_PLACE_IDS = ("plaza", "townhall")  # where the board physically is
    BILLBOARD_TEXT_CAP = 280

    def billboard_here(self, place_id: str) -> bool:
        """True when the billboard is reachable from this place (plaza/townhall)."""
        return place_id in self.BILLBOARD_PLACE_IDS and place_id in self.places

    def _append_billboard(self, actor_id: str, actor_type: str, text: str) -> dict:
        entry = {
            "tick": self.tick,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "text": str(text)[: self.BILLBOARD_TEXT_CAP],
        }
        self.billboard.append(entry)
        del self.billboard[: -self.BILLBOARD_CAP]
        return entry

    def read_billboard_top(self, n: int = 3) -> list[dict]:
        """The newest `n` posts, newest first (read_billboard context injection)."""
        return list(reversed(self.billboard[-max(0, n):]))

    def action_post_billboard(self, agent: AgentState, text: str) -> dict:
        """Reflex tool: pin a note to the public billboard. Location-gated to
        plaza/townhall (also enforced by the runtime validator). Returns a
        ready-to-emit billboard_posted event dict."""
        text = str(text or "").strip()
        if not text:
            return self._fail_event(
                agent.id, "post_billboard", "text required",
                f"{agent.name} stared at the billboard but wrote nothing.")
        if not self.billboard_here(agent.location):
            return self._fail_event(
                agent.id, "post_billboard", "no billboard here",
                f"{agent.name} looked for a billboard, but there is none here.")
        entry = self._append_billboard(agent.id, "human_agent", text)
        return {
            "kind": "billboard_posted",
            "actor_id": agent.id,
            "text": f"📌 {agent.name} pins a note to the billboard: "
                    f"\"{_truncate(entry['text'], 80)}\"",
            "payload": {"place": agent.location, "text": entry["text"]},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Wave I / EM-210–213 — The Atelier: agents generate ART for their town.
    # Reflex-first (zero critical-path LLM calls), replay-safe (seeded ids, the
    # PNG an external side-artifact that never re-enters the sim). See
    # contracts/wave-i-atelier.md §2.
    # ──────────────────────────────────────────────────────────────────────────

    IMAGEGEN_DEFAULT_MAX_GALLERY = 30   # newest images retained in self.gallery
    IMAGE_PROMPT_CAP = 240              # prompt chars kept (and the schema maxLength)

    def _image_gen_enabled(self) -> bool:
        """Wave I / EM-210 — config gate `world.image_gen.enabled` (default True).
        Disabled ⇒ create_image is dropped from the menu and rejected here at
        resolution (no PNG fetch parked), so the Atelier makes ZERO image-API
        calls — the credit-safe kill switch. post_image/promote_image stay."""
        return bool(_block_get(getattr(self.params, "image_gen", None), "enabled", True))

    def _image_gen_max_gallery(self) -> int:
        """The gallery cap, read modestly from config (params.image_gen.max_gallery),
        mirroring the props/animals max_population reads. Defaults to 30 when the
        block is absent (pre-Wave-I worlds / tests that build WorldParams directly).
        Floored at 1 (a 0/negative cap would discard every image on append)."""
        cfg = getattr(self.params, "image_gen", None)
        try:
            return max(1, int(_block_get(cfg, "max_gallery", self.IMAGEGEN_DEFAULT_MAX_GALLERY)))
        except (TypeError, ValueError):
            return self.IMAGEGEN_DEFAULT_MAX_GALLERY

    def _image_id(
        self, place: str, proposer_id: str, created_tick: int, ordinal: int
    ) -> str:
        """Wave I / EM-210 — a SEEDED, replay-stable image id (NEVER uuid4 — the
        EM-155 keystone). Mirrors _prop_id: a sha256 of (place, proposer,
        created_tick, ordinal, city_seed) via the animal layer's _seed_int.

        FINDING 2/3 (contract §0.2): `created_tick` is part of the seed so ids are
        unique across the run's FULL history. The gallery cap evicts old records,
        so the window-only collision check below cannot guarantee uniqueness — but
        `tick` (monotonic, deterministic) does, so a later same-place/same-proposer
        image can never alias an EVICTED id. `ordinal` disambiguates multiple images
        at the SAME tick/place/proposer; the collision bump stays belt-and-suspenders.
        Still fully replay-safe (tick is deterministic in replay)."""
        from ..animals.runtime import _seed_int
        seed = _seed_int(
            "image", self.city_seed, place, proposer_id, created_tick, ordinal)
        return f"img_{format(seed % (16 ** 10), '010x')}"

    @staticmethod
    def _image_url(image_id: str) -> str:
        """The image url — DERIVED from the id (§0.2), so it is known at reflex
        time and identical across runs/replays. The PNG is a side-artifact written
        under data/assets/images/<id>.png by the loop; its bytes never re-enter the sim."""
        return f"/assets/images/{image_id}.png"

    def _append_gallery(
        self, image_id: str, prompt: str, proposer_id: str, tick: int, url: str
    ) -> dict:
        """Append a gallery record + cap to the newest max_gallery (pop-oldest,
        mirror _append_billboard). Returns the record dict."""
        record = {
            "image_id": image_id,
            "prompt": prompt,
            "proposer_id": proposer_id,
            "created_tick": tick,
            "url": url,
            "promoted": False,
        }
        self.gallery.append(record)
        del self.gallery[: -self._image_gen_max_gallery()]
        return record

    def newest_gallery_image_for(self, proposer_id: str) -> dict | None:
        """The agent's newest gallery record (or None) — the default post_image picks this."""
        for record in reversed(self.gallery):
            if record.get("proposer_id") == proposer_id:
                return record
        return None

    def action_create_image(self, agent: AgentState, prompt: str) -> dict:
        """Wave I / EM-210 (I1) — reflex tool, UNGATED (create art anywhere). Records
        a deterministic gallery entry + parks a transient fetch + emits image_posted,
        ALL synchronously at turn time (no LLM, no network here). The async PNG fetch
        is drained by the loop and emits NOTHING (off the replay surface)."""
        # Wave I / EM-210 — credit-safe kill switch: when image_gen is disabled,
        # reject BEFORE parking any fetch, so the loop never calls the image API.
        if not self._image_gen_enabled():
            return self._fail_event(
                agent.id, "create_image", "image_gen_disabled",
                f"{agent.name} reached for the brushes, but the atelier is closed today.")
        prompt = str(prompt or "").strip()[: self.IMAGE_PROMPT_CAP]
        if not prompt:
            return self._fail_event(
                agent.id, "create_image", "prompt required",
                f"{agent.name} faced a blank canvas but pictured nothing to paint.")
        place = agent.location
        # ordinal = images already created this tick+place (breaks seeded ties so a
        # second image the same tick gets a distinct id; bump on the rare collision).
        ordinal = sum(
            1 for g in self.gallery
            if g.get("created_tick") == self.tick
            and g.get("proposer_id") == agent.id
        )
        image_id = self._image_id(place, agent.id, self.tick, ordinal)
        existing = {g.get("image_id") for g in self.gallery}
        while image_id in existing:
            ordinal += 1
            image_id = self._image_id(place, agent.id, self.tick, ordinal)
        url = self._image_url(image_id)
        self._append_gallery(image_id, prompt, agent.id, self.tick, url)
        self.pending_image_fetches.append(
            {"image_id": image_id, "prompt": prompt, "url": url})
        return {
            "kind": "image_posted",
            "actor_id": agent.id,
            "text": f"🎨 {agent.name} paints \"{_truncate(prompt, 60)}\".",
            "payload": {
                "image_id": image_id,
                "prompt": prompt,
                "url": url,
                "place": place,
            },
        }

    def action_post_image(self, agent: AgentState, image_id: str | None = None) -> dict:
        """Wave I / EM-211 (I2) — reflex tool, @billboard-gated (like post_billboard).
        Posts an EXISTING gallery image (default: the agent's newest) to the billboard
        so others perceive it: a billboard entry whose payload carries image_ref=url.
        Validates the image exists + belongs-or-is-public (a promoted image is public)."""
        if not self.billboard_here(agent.location):
            return self._fail_event(
                agent.id, "post_image", "no billboard here",
                f"{agent.name} looked for a billboard to hang art on, but there is none here.")
        image_id = str(image_id or "").strip()
        record: dict | None = None
        if image_id:
            record = next(
                (g for g in self.gallery if g.get("image_id") == image_id), None)
            if record is None:
                return self._fail_event(
                    agent.id, "post_image", f"unknown image {image_id!r}",
                    f"{agent.name} reached for an image that does not exist ({image_id!r}).")
            # Belongs-or-is-public: own art always; others' only once promoted (public).
            if record.get("proposer_id") != agent.id and not record.get("promoted"):
                return self._fail_event(
                    agent.id, "post_image", "image not yours",
                    f"{agent.name} cannot post someone else's unpromoted image.")
        else:
            record = self.newest_gallery_image_for(agent.id)
            if record is None:
                return self._fail_event(
                    agent.id, "post_image", "no image to post",
                    f"{agent.name} has not painted anything to post yet — create_image first.")
        url = str(record.get("url", ""))
        entry = self._append_billboard(
            agent.id, "human_agent",
            f"{agent.name} shares art: \"{_truncate(str(record.get('prompt', '')), 60)}\"")
        return {
            "kind": "billboard_posted",
            "actor_id": agent.id,
            "text": f"🖼 {agent.name} pins art to the billboard: "
                    f"\"{_truncate(str(record.get('prompt', '')), 60)}\"",
            "payload": {
                "place": agent.location,
                "text": entry["text"],
                "image_ref": url,
                "image_id": record.get("image_id"),
            },
        }

    def post_billboard_as_god(self, text: str, in_reply_to: Any = None) -> dict:
        """God-mode billboard post/reply (EM-091). The api layer exposes the
        endpoint and emits the returned billboard_posted event dict through the
        normal pipeline (actor_type 'god'). The post lands on the board state
        immediately."""
        text = str(text or "").strip()[: self.BILLBOARD_TEXT_CAP]
        entry = self._append_billboard("god", "god", text)
        place = next(
            (pid for pid in self.BILLBOARD_PLACE_IDS if pid in self.places),
            next(iter(self.places), ""),
        )
        payload: dict = {"place": place, "text": entry["text"]}
        if in_reply_to is not None:
            payload["in_reply_to"] = in_reply_to
        return {
            "kind": "billboard_posted",
            "actor_id": "god",
            "actor_type": "god",
            "turn_id": None,
            "text": f"📌 GOD posts on the billboard: \"{_truncate(entry['text'], 80)}\"",
            "payload": payload,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PROTOTYPE — god proclamations (the LOUD tier of the god↔town channel).
    # A billboard note is opt-in: an agent must stand at the plaza and choose
    # read_billboard. A proclamation is the opposite — the active one is injected
    # into every agent's prompt each turn (see runtime._assemble_context), so the
    # god's word reaches the whole world with zero extra LLM calls.
    # ──────────────────────────────────────────────────────────────────────────

    PROCLAMATION_CAP = 20            # newest proclamations kept

    def active_proclamation(self) -> dict | None:
        """The current decree — the newest proclamation, or None. This is the one
        that rides every agent's prompt until the god issues another."""
        return self.proclamations[-1] if self.proclamations else None

    def post_proclamation_as_god(self, text: str) -> dict:
        """God-mode LOUD post: a proclamation heard by the whole world. The api
        layer (POST /api/proclaim) emits the returned `proclamation_posted` event
        dict through the normal pipeline (actor_type 'god'); the proclamation lands
        in `world.proclamations` immediately and becomes the active decree."""
        text = str(text or "").strip()[: self.BILLBOARD_TEXT_CAP]
        entry = {
            "id": f"proc-{self.tick}-{len(self.proclamations)}",
            "tick": self.tick,
            "text": text,
            "replies": [],          # threaded agent answers (return path — next slice)
        }
        self.proclamations.append(entry)
        del self.proclamations[: -self.PROCLAMATION_CAP]
        return {
            "kind": "proclamation_posted",
            "actor_id": "god",
            "actor_type": "god",
            "turn_id": None,
            "text": f"📜 GOD proclaims to all: \"{_truncate(entry['text'], 80)}\"",
            "payload": {"proclamation_id": entry["id"], "text": entry["text"]},
        }

    def answer_proclamation(self, agent: AgentState, text: str) -> dict:
        """Reflex tool (the return path): an agent answers the active proclamation.
        The reply is threaded under the proclamation (appended to its `replies`)
        and emitted as `proclamation_answered`, so the feed groups the exchange and
        world_state carries the thread. NO location gate — the god's voice is
        everywhere, so the answer can come from anywhere. Returns a ready-to-emit
        event dict (or a parse_failure via _fail_event)."""
        text = str(text or "").strip()[: self.BILLBOARD_TEXT_CAP]
        if not text:
            return self._fail_event(
                agent.id, "answer_proclamation", "text required",
                f"{agent.name} went to answer the god, but said nothing.")
        active = self.active_proclamation()
        if active is None:
            return self._fail_event(
                agent.id, "answer_proclamation", "no active proclamation",
                f"{agent.name} looked to the heavens, but no decree hung in the air.")
        active.setdefault("replies", []).append(
            {"tick": self.tick, "actor_id": agent.id, "text": text})
        return {
            "kind": "proclamation_answered",
            "actor_id": agent.id,
            "text": f"↳ {agent.name} answers the god: \"{_truncate(text, 80)}\"",
            "payload": {
                "proclamation_id": active.get("id"),
                "text": text,
                "in_reply_to": active.get("text"),
            },
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Wave A.2 (god console) — targeted interventions (EM-136) + one-shot
    # whispers (EM-137). The world-wide levers (RANDOM_EVENTS, proclamations)
    # could never save ONE starving agent; these target a single soul. Free-scale
    # law: pure state mutation + event (intervene) and context injection
    # (whisper) — zero LLM calls either way. The api layer exposes the endpoints
    # and emits the returned event dicts through the normal pipeline.
    # ──────────────────────────────────────────────────────────────────────────

    # Per-kind defaults for god_intervene (the UI's BLESS +25 / GRANT +10).
    GOD_INTERVENTION_DEFAULTS = {
        "bless_energy": 25,
        "grant_credits": 10,
    }

    # Wave E / EM-184 — the WORLD-scale miracle kinds. Cast through the same
    # god_intervene seam but with NO agent_id (the targeted kinds above keep
    # requiring one). send_rain / bountiful_harvest are timed (active_miracles
    # entries swept beside expire_blackouts); calm_spirits is one-time.
    GOD_MIRACLE_KINDS = ("send_rain", "bountiful_harvest", "calm_spirits")

    def _living_agent_or_raise(self, agent_id: str) -> AgentState:
        """Resolve a LIVING agent for a targeted god action. ValueError (the api
        maps it to 422) on unknown or dead targets — resurrection is explicitly
        out of scope, so the god cannot reach the dead."""
        agent = self.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent: {agent_id!r}")
        if not agent.alive:
            raise ValueError(f"{agent.name} is dead — the god cannot reach them")
        return agent

    def god_intervene(
        self, kind: str, agent_id: str | None = None, amount: Any = None
    ) -> dict | list[dict]:
        """God-mode intervention. Two families behind one seam:

        - TARGETED (EM-136, unchanged): bless ONE agent's energy (clamped at
          100) or grant them credits. Requires agent_id; amount defaults per
          kind (GOD_INTERVENTION_DEFAULTS) and is validated 1..100; unknown
          kind and unknown/dead agent raise ValueError (api → 422). Returns
          the ready-to-emit `god_intervention` event DICT (actor_type 'god',
          target_id the agent, payload carries before/after so a clamp is
          visible) — byte-identical to pre-E behavior.
        - WORLD-scale miracles (Wave E / EM-184): send_rain /
          bountiful_harvest / calm_spirits REJECT an agent_id (ValueError →
          api 422) and return a LIST of ready-to-emit event dicts: the
          `god_miracle` event first, plus — for calm_spirits — any
          relationship_changed events its trust nudges parked (drained here
          because no action turn ever drains a god-initiated mutation; all
          turn_id null, same API emission batch).
        """
        if kind in self.GOD_MIRACLE_KINDS:
            if agent_id is not None:
                raise ValueError(
                    f"{kind} is a world-scale miracle — it takes no agent_id")
            return self.god_miracle(kind)
        if kind not in self.GOD_INTERVENTION_DEFAULTS:
            raise ValueError(f"Unknown intervention kind: {kind!r}")
        if agent_id is None:
            raise ValueError(f"{kind} targets one agent — agent_id is required")
        agent = self._living_agent_or_raise(agent_id)
        if amount is None:
            amount = self.GOD_INTERVENTION_DEFAULTS[kind]
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            raise ValueError(f"amount must be an integer, got {amount!r}")
        if not 1 <= amount <= 100:
            raise ValueError(f"amount must be 1..100, got {amount}")
        if kind == "bless_energy":
            before: Any = round(agent.energy, 2)
            agent.energy = min(100.0, agent.energy + amount)
            after: Any = round(agent.energy, 2)
            text = f"✦ god restores {agent.name} — +{amount} energy"
        else:  # grant_credits
            before = agent.credits
            agent.credits += amount
            after = agent.credits
            text = f"✦ god favors {agent.name} — +{amount} credits"
        return {
            "kind": "god_intervention",
            "actor_id": "god",
            "actor_type": "god",
            "target_id": agent.id,
            "turn_id": None,
            "text": text,
            "payload": {"kind": kind, "amount": amount,
                        "before": before, "after": after},
        }

    def post_whisper_as_god(self, agent_id: str, text: str) -> dict:
        """God-mode one-shot whisper (EM-137): queue a line that rides ONLY the
        target agent's NEXT prompt, exactly once (pending_whispers, popped by
        runtime._assemble_context). Text capped at 280 like the billboard;
        empty text and unknown/dead agents raise ValueError (api → 422).
        Returns a ready-to-emit `whisper_posted` event dict — this is a
        spectator app, nothing is secret, so the feed line carries the content
        too (the whisper is private to the AGENTS, not the watchers)."""
        agent = self._living_agent_or_raise(agent_id)
        text = str(text or "").strip()[: self.BILLBOARD_TEXT_CAP]
        if not text:
            raise ValueError("text required")
        self.pending_whispers.setdefault(agent.id, []).append(text)
        return {
            "kind": "whisper_posted",
            "actor_id": "god",
            "actor_type": "god",
            "target_id": agent.id,
            "turn_id": None,
            "text": f"✦ god whispers to {agent.name}: \"{_truncate(text, 80)}\"",
            "payload": {"agent_id": agent.id, "text": text},
        }

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-083 — real blackout: recharge disabled at affected places.
    # ──────────────────────────────────────────────────────────────────────────

    def place_blacked_out(self, place_id: str) -> bool:
        p = self.places.get(place_id)
        return bool(p is not None and p.blackout_until_tick and self.tick < p.blackout_until_tick)

    def apply_blackout(self, duration_ticks: int | None = None) -> tuple[list[str], int, list[dict]]:
        """Black out the home-kind places (or, lacking any, the first two places)
        for `duration_ticks` (config world.blackout_ticks, default 10). Returns
        (affected_place_ids, until_tick, structure_state_changed event dicts) for
        the loop to emit alongside the random_event."""
        if duration_ticks is None:
            duration_ticks = getattr(self.params, "blackout_ticks", 10)
        try:
            duration_ticks = max(1, int(duration_ticks))
        except (TypeError, ValueError):
            duration_ticks = 10
        affected = [p for p in self.places.values() if p.kind == "home"]
        if not affected:
            affected = list(self.places.values())[:2]
        until = self.tick + duration_ticks
        events: list[dict] = []
        for p in affected:
            p.blackout_until_tick = until
            events.append({
                "kind": "structure_state_changed",
                "actor_id": None,
                "actor_type": "system",
                "turn_id": None,
                "text": f"⚡ The power is out at {p.name} — recharge disabled "
                        f"until tick {until}.",
                "payload": {
                    "place_id": p.id,
                    "from": "powered",
                    "to": "blackout",
                    "reason": "blackout",
                    "until_tick": until,
                },
            })
        return [p.id for p in affected], until, events

    def expire_blackouts(self) -> list[dict]:
        """Restore power at places whose blackout window has elapsed. Returns the
        structure_state_changed event dicts to emit (empty when nothing expired).
        Called from the tick loop each turn — cheap, no allocation when idle."""
        events: list[dict] = []
        for p in self.places.values():
            if p.blackout_until_tick and self.tick >= p.blackout_until_tick:
                p.blackout_until_tick = 0
                events.append({
                    "kind": "structure_state_changed",
                    "actor_id": None,
                    "actor_type": "system",
                    "turn_id": None,
                    "text": f"💡 Power is restored at {p.name} — recharge works again.",
                    "payload": {
                        "place_id": p.id,
                        "from": "blackout",
                        "to": "powered",
                        "reason": "blackout_ended",
                    },
                })
        return events

    # ──────────────────────────────────────────────────────────────────────────
    # Wave E / EM-184 — world-scale god miracles (contracts/wave-e.md B5).
    # Timed world modifiers (active_miracles entries) + the one-time
    # calm_spirits. Pure state modifiers — zero LLM calls (the wave's
    # free-scale law); expiry rides the same per-tick sweep as blackouts.
    # ──────────────────────────────────────────────────────────────────────────

    def _mir_param(self, name: str, default: Any) -> Any:
        """Defensive accessor for the `world.miracles` config block
        (dataclass OR dict OR absent — EM-155 conventions, like _rel_param)."""
        return _block_get(getattr(self.params, "miracles", None), name, default)

    def _miracles_enabled(self) -> bool:
        """Config gate `world.miracles.enabled` (default ON). Disabled ⇒ the
        world kinds raise (api → 422) and no buff/sweep state ever exists —
        byte-identical pre-E behavior; targeted bless/grant are untouched."""
        return bool(self._mir_param("enabled", True))

    def miracle_active(self, kind: str) -> bool:
        """True while a timed miracle of `kind` is in effect (tick strictly
        before until_tick — the place_blacked_out convention)."""
        for m in self.active_miracles:
            try:
                until = int(m.get("until_tick", 0))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                continue
            if m.get("kind") == kind and self.tick < until:
                return True
        return False

    # Per-kind cast/expiry flavour text (the feed lines).
    _MIRACLE_CAST_TEXTS = {
        "send_rain": "🌧 Rain falls on the gardens — forage flourishes",
        "bountiful_harvest":
            "🌾 A bountiful harvest blesses the town — hunger bites slower",
        "calm_spirits":
            "🕊 A great calm settles over the town — every heart lifts",
    }
    _MIRACLE_EXPIRED_TEXTS = {
        "send_rain": "☀ The rains pass — forage returns to normal.",
        "bountiful_harvest":
            "🍂 The bountiful season ends — hunger bites as before.",
    }

    def god_miracle(self, kind: str) -> list[dict]:
        """Cast a WORLD-scale miracle (EM-184). Returns the ready-to-emit
        event batch: the `god_miracle` event (actor 'god', target_id None,
        turn_id null) first, plus — for calm_spirits — the
        relationship_changed events its trust nudges parked in the B1 outbox
        (drained HERE: god mutations happen outside any action turn, so no
        runtime drain would ever pick them up). Timed kinds add/refresh an
        active_miracles entry — re-casting an active kind REFRESHES
        until_tick, never stacks. Disabled config raises ValueError."""
        if kind not in self.GOD_MIRACLE_KINDS:
            raise ValueError(f"Unknown miracle kind: {kind!r}")
        if not self._miracles_enabled():
            raise ValueError(
                "miracles are disabled (world.miracles.enabled: false)")
        if kind == "calm_spirits":
            return self._cast_calm_spirits()
        # Timed kinds: duration is days × turns_per_day ticks.
        days_key = "rain_days" if kind == "send_rain" else "harvest_days"
        try:
            days = max(1, int(self._mir_param(days_key, 2)))
        except (TypeError, ValueError):
            days = 2
        try:
            turns_per_day = max(1, int(getattr(self.params, "turns_per_day", 20)))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            turns_per_day = 20
        until = self.tick + days * turns_per_day
        existing = next(
            (m for m in self.active_miracles if m.get("kind") == kind), None)
        if existing is not None:
            existing["until_tick"] = until  # refresh, never stack
        else:
            self.active_miracles.append({"kind": kind, "until_tick": until})
        return [{
            "kind": "god_miracle",
            "actor_id": "god",
            "actor_type": "god",
            "target_id": None,
            "turn_id": None,
            "text": self._MIRACLE_CAST_TEXTS[kind],
            "payload": {"kind": kind, "until_tick": until},
        }]

    def _cast_calm_spirits(self) -> list[dict]:
        """ONE-TIME calm_spirits: every living agent's mood becomes 'hopeful',
        and every living↔living relationship with interactions >= 1 gets
        +calm_trust_bonus through _update_trust — the B1 reflex seam, so
        clamps apply and friend/feud transitions may fire (that's the point).
        Deterministic order (sorted agent ids both levels). No duration entry
        is ever added. Returns [god_miracle, *relationship_changed]."""
        living = sorted(self.living_agents(), key=lambda a: a.id)
        living_ids = {a.id for a in living}
        for agent in living:
            agent.mood = "hopeful"
        try:
            bonus = int(self._mir_param("calm_trust_bonus", 3))
        except (TypeError, ValueError):  # pragma: no cover - defensive
            bonus = 3
        if bonus > 0:
            for agent in living:
                for other_id in sorted(agent.relationships):
                    if other_id == agent.id or other_id not in living_ids:
                        continue
                    if agent.relationships[other_id].interactions >= 1:
                        self._update_trust(agent, self.agents[other_id], bonus)
        events: list[dict] = [{
            "kind": "god_miracle",
            "actor_id": "god",
            "actor_type": "god",
            "target_id": None,
            "turn_id": None,
            "text": self._MIRACLE_CAST_TEXTS["calm_spirits"],
            "payload": {"kind": "calm_spirits"},
        }]
        # Drain the B1 outbox OURSELVES (QE carry-over): _update_trust parks
        # relationship_changed events there, and the per-action drain in
        # runtime._apply_action never runs for a god mutation — without this
        # drain the events would sit parked forever. They ride the same API
        # emission batch as the miracle, turn_id null.
        for evt in self.drain_relationship_events():
            evt.setdefault("turn_id", None)
            events.append(evt)
        return events

    def expire_miracles(self) -> list[dict]:
        """Sweep expired timed miracles (tick >= until_tick). Returns the
        miracle_expired event dicts to emit (empty when nothing expired).
        Called from the tick loop each turn beside expire_blackouts() —
        cheap, no allocation when idle."""
        if not self.active_miracles:
            return []
        events: list[dict] = []
        remaining: list[dict] = []
        for m in self.active_miracles:
            kind = str(m.get("kind", ""))
            try:
                until = int(m.get("until_tick", 0))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                until = 0
            if self.tick >= until:
                events.append({
                    "kind": "miracle_expired",
                    "actor_id": None,
                    "actor_type": "system",
                    "target_id": None,
                    "turn_id": None,
                    "text": self._MIRACLE_EXPIRED_TEXTS.get(
                        kind, f"The {kind} miracle fades."),
                    "payload": {"kind": kind, "until_tick": until},
                })
            else:
                remaining.append(m)
        self.active_miracles = remaining
        return events

    # ──────────────────────────────────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────────────────────────────────

    def _update_trust(self, from_agent: AgentState, to_agent: AgentState, delta: int) -> None:
        rel = from_agent.relationships.get(to_agent.id)
        if rel is None:
            rel = RelationshipState()
            from_agent.relationships[to_agent.id] = rel
        rel.trust = max(-100, min(100, rel.trust + delta))
        rel.interactions += 1
        # Wave E / EM-113 — the SINGLE reflex-transition seam: every trust
        # mutation (give/steal/insult/attack/arson-witness, and future callers)
        # is evaluated for a type transition right after the clamp.
        self._maybe_shift_relationship(from_agent, to_agent)

    # ──────────────────────────────────────────────────────────────────────────
    # Wave E / EM-113 — relationship depth (contracts/wave-e.md B1)
    # ──────────────────────────────────────────────────────────────────────────

    def _rel_param(self, name: str, default: Any) -> Any:
        """Defensive accessor for the `world.relationships` config block
        (dataclass OR dict OR absent — EM-155 conventions, like _bld_param)."""
        return _block_get(getattr(self.params, "relationships", None), name, default)

    def _crime_param(self, name: str, default: Any) -> Any:
        """EM-240 — defensive accessor for the `world.crime` config block
        (CrimeParams dataclass OR dict OR absent — EM-155 conventions, like
        _rel_param/_bld_param). An absent block ⇒ every default ⇒ pre-EM-240
        worlds run unchanged. `default` is only a fallback for a key missing from
        the block, so keep these call-site defaults == CrimeParams defaults."""
        return _block_get(getattr(self.params, "crime", None), name, default)

    def _needs_param(self, name: str, default: Any) -> Any:
        """EM-229 — defensive accessor for the `world.needs` config block
        (NeedsParams dataclass OR dict OR absent — EM-155 conventions, like
        _crime_param). An absent block ⇒ every default ⇒ pre-EM-229 worlds run
        unchanged. `default` is only a fallback for a key missing from the block,
        so keep these call-site defaults == NeedsParams defaults."""
        return _block_get(getattr(self.params, "needs", None), name, default)

    def _memory_param(self, name: str, default: Any) -> Any:
        """EM-233 — defensive accessor for the `world.memory` config block
        (MemoryParams dataclass OR dict OR absent — EM-155 conventions, like
        _needs_param). An absent block ⇒ every default ⇒ pre-EM-233 worlds run
        unchanged. `default` is only a fallback for a key missing from the block,
        so keep these call-site defaults == MemoryParams defaults."""
        return _block_get(getattr(self.params, "memory", None), name, default)

    def _maybe_shift_relationship(self, from_agent: AgentState, to_agent: AgentState) -> None:
        """Reflex type transitions, evaluated after every trust clamp:

          neutral|ally -> friend  when trust >= friend_trust AND
                                  interactions >= friend_interactions
          rival|enemy  -> feud    when trust <= feud_trust

        Types never auto-downgrade this wave (drama persists; an explicit
        set_relationship can still overwrite, subject to its guards). On a
        transition the relationship_changed event is parked in the outbox so
        the runtime can ride it on the triggering action's `_multi` chain."""
        rel = from_agent.relationships.get(to_agent.id)
        if rel is None:
            return
        new_type: str | None = None
        if rel.type in ("neutral", "ally"):
            friend_trust = int(self._rel_param("friend_trust", 30))
            friend_interactions = int(self._rel_param("friend_interactions", 5))
            if rel.trust >= friend_trust and rel.interactions >= friend_interactions:
                new_type = "friend"
        elif rel.type in ("rival", "enemy"):
            feud_trust = int(self._rel_param("feud_trust", -40))
            if rel.trust <= feud_trust:
                new_type = "feud"
        if new_type is None or new_type == rel.type:
            return
        from_type = rel.type
        rel.type = new_type
        rel.since_tick = self.tick
        self.pending_relationship_events.append(
            self._relationship_changed_event(from_agent, to_agent, from_type, rel)
        )

    def _relationship_changed_event(
        self, from_agent: AgentState, to_agent: AgentState,
        from_type: str, rel: RelationshipState,
    ) -> dict:
        """Build a ready-to-emit relationship_changed event. EM-141: both
        endpoints are AGENT ids only (the social-graph selector drops events
        with non-agent endpoints)."""
        a, b = from_agent.name, to_agent.name
        texts = {
            "friend": f"{a} and {b} are now friends",
            "feud": f"the rivalry between {a} and {b} has hardened into a feud",
            "partner": f"{a} and {b} are now partners",
            "family": f"{a} and {b} are family",
            "mentor": f"{a} now looks to {b} as a mentor",
            "ally": f"{a} now counts {b} as an ally",
            "rival": f"{a} now sees {b} as a rival",
            "enemy": f"{a} now sees {b} as an enemy",
            "neutral": f"{a} lets things cool with {b}",
        }
        return {
            "kind": "relationship_changed",
            "actor_id": from_agent.id,
            "target_id": to_agent.id,
            "text": texts.get(rel.type, f"{a} now sees {b} as {rel.type}"),
            "payload": {
                "from_type": from_type,
                "to_type": rel.type,
                "trust": rel.trust,
                "since_tick": rel.since_tick,
            },
        }

    def drain_relationship_events(self) -> list[dict]:
        """Pop the parked relationship_changed events (runtime calls this at
        the end of _apply_action so transitions ride the action's turn chain)."""
        out = self.pending_relationship_events
        self.pending_relationship_events = []
        return out

    def are_partners(self, a_id: str, b_id: str) -> bool:
        """Mutual-partner predicate (EM-113 item 4; EM-114 consumes it as the
        consent mechanic): BOTH directions typed `partner` AND both trusts >=
        partner_trust_threshold."""
        a = self.agents.get(a_id)
        b = self.agents.get(b_id)
        if a is None or b is None:
            return False
        threshold = int(self._rel_param("partner_trust_threshold", 40))
        rel_ab = a.relationships.get(b_id)
        rel_ba = b.relationships.get(a_id)
        return (
            rel_ab is not None and rel_ba is not None
            and rel_ab.type == "partner" and rel_ba.type == "partner"
            and rel_ab.trust >= threshold and rel_ba.trust >= threshold
        )

    def apply_bond(
        self, agent: AgentState, target_id: str, rel_type: str, tick: int
    ) -> tuple[bool, str]:
        """Wave E / EM-125 — apply a reflection-declared bond
        (contracts/wave-e.md B4). EXACTLY set_relationship semantics: the same
        B1 guards (`family` engine-only, `partner` trust-gated) and, on an
        actual type change, the same relationship_changed event parked in the
        pending_relationship_events outbox so the declaring agent's turn chain
        carries it. `tick` is the declaring turn's tick per the contract
        signature — callers pass the current world tick, which is what
        action_set_relationship stamps into since_tick. Dead/unknown targets
        are rejected (the runtime resolves names to ids before calling)."""
        target = self.agents.get(target_id)
        if target is None:
            return False, f"unknown target: {target_id!r}"
        if not target.alive:
            return False, f"{target.name} is no longer among the living"
        return self.action_set_relationship(agent, target, rel_type)

    def agents_at(self, place_id: str) -> list[AgentState]:
        return [a for a in self.living_agents() if a.location == place_id]

    # ──────────────────────────────────────────────────────────────────────────
    # EM-240 — Crime & Justice bookkeeping. Witnessed crime accrues notoriety;
    # a per-round advance decays it, clears stale `wanted`, and frees the jailed.
    # ──────────────────────────────────────────────────────────────────────────

    def _register_crime(
        self, actor: AgentState, crime: str, victim_id: str | None, notoriety_base: int
    ) -> bool:
        """EM-240 — shared crime bookkeeping. Witnesses = co-located living agents
        OTHER than the actor and the direct victim. Bumps notoriety only when
        witnessed; always records the rap sheet; flips `wanted` at threshold.
        Does NOT touch trust — each action keeps its own witness-trust deltas."""
        witnesses = [
            a for a in self.agents_at(actor.location)
            if a.id != actor.id and a.id != victim_id
        ]
        witnessed = len(witnesses) > 0
        if witnessed:
            per = int(self._crime_param("notoriety_per_extra_witness", 3))
            gain = int(notoriety_base) + per * (len(witnesses) - 1)
            actor.notoriety = max(0, min(100, actor.notoriety + gain))
        actor.rap_sheet.append({
            "tick": self.tick, "crime": crime,
            "victim_id": victim_id, "witnessed": witnessed,
        })
        cap = int(self._crime_param("rap_sheet_cap", 10))
        if len(actor.rap_sheet) > cap:
            del actor.rap_sheet[: len(actor.rap_sheet) - cap]
        threshold = int(self._crime_param("wanted_threshold", 40))
        if actor.crime_status is None and actor.notoriety >= threshold:
            actor.crime_status = "wanted"
        return witnessed

    def advance_crime(self) -> list[dict]:
        """EM-240 — per-round crime status maintenance (called from the loop beside
        advance_buildings). Decays notoriety while free, clears stale `wanted`, and
        releases detained/jailed agents at expiry. Deterministic; no RNG/clock."""
        events: list[dict] = []
        decay = int(self._crime_param("notoriety_decay", 2))
        threshold = int(self._crime_param("wanted_threshold", 40))
        relief = int(self._crime_param("released_notoriety_relief", 10))
        for agent in self.living_agents():
            # Release at expiry: burn the release relief once. A just-released
            # agent does NOT also decay this round (release relief IS the round's
            # notoriety drop) — it decays normally on subsequent free rounds.
            if agent.crime_status in ("detained", "jailed") and \
                    self.tick >= agent.crime_status_until_tick:
                agent.crime_status = None
                agent.crime_status_until_tick = 0
                agent.notoriety = max(0, agent.notoriety - relief)
                events.append({
                    "kind": "released",
                    "actor_id": agent.id,
                    "text": f"{agent.name} is released back into the town.",
                    "payload": {"notoriety": agent.notoriety},
                })
                continue
            # Decay only while free (jail is its own cool-off).
            if agent.crime_status in (None, "wanted") and agent.notoriety > 0:
                agent.notoriety = max(0, agent.notoriety - decay)
            # Clear a `wanted` flag that has cooled below threshold.
            if agent.crime_status == "wanted" and agent.notoriety < threshold:
                agent.crime_status = None
        return events

    # ──────────────────────────────────────────────────────────────────────────
    # Wave E / EM-114 — lightweight children (contracts/wave-e.md B2)
    # ──────────────────────────────────────────────────────────────────────────

    def _chl_param(self, name: str, default: Any) -> Any:
        """Defensive accessor for the `world.children` config block
        (dataclass OR dict OR absent — EM-155 conventions, like _rel_param)."""
        return _block_get(getattr(self.params, "children", None), name, default)

    def set_birth_casting(
        self, personas: list[dict], profile_roster: list[str]
    ) -> None:
        """Seed the birth casting pool (the EM-114 config seam, called by the
        TickLoop at construction): `personas` = the EM-092 persona-library
        cards; `profile_roster` = non-mock profile names in STABLE config
        order (the load-spread tiebreak order for a child's profile)."""
        self.birth_personas = [c for c in (personas or []) if isinstance(c, dict)]
        self.birth_profile_roster = [str(p) for p in (profile_roster or []) if p]

    def home_bed_capacity(self) -> int:
        """Total beds across home-kind places: a cottage (no capacity field)
        counts 1 bed; the bunkhouse counts its `capacity` (EM-098)."""
        return sum(
            (p.capacity if p.capacity is not None else 1)
            for p in self.places.values()
            if p.kind == "home"
        )

    def _birth_roll(self, a_id: str, b_id: str) -> float:
        """Deterministic unit float in [0, 1) for the birth chance gate,
        derived from a STABLE hash of (city_seed, tick, pair). sha1, not
        Python hash() (salted per-process) and never the `random` module —
        replay/fork reproduce the same rolls (EM-155 determinism)."""
        lo, hi = sorted((a_id, b_id))
        key = f"{self.city_seed}:{self.tick}:{lo}:{hi}".encode()
        return int.from_bytes(hashlib.sha1(key).digest()[:8], "big") / float(1 << 64)

    def _latest_pair_child_tick(self, a_id: str, b_id: str) -> int | None:
        """The youngest shared child's birth tick for this pair, derived from
        AgentState.parents + the child's family-tie since_tick (stamped at
        birth). None when the pair has no child. NO new clock state — this
        round-trips snapshots, so a restored world never re-births inside the
        cooldown window. Dead children still count (kill keeps the record)."""
        pair = sorted((a_id, b_id))
        latest: int | None = None
        for child in self.agents.values():
            if sorted(child.parents) != pair:
                continue
            rel = child.relationships.get(pair[0]) or child.relationships.get(pair[1])
            born = rel.since_tick if rel is not None else 0
            if latest is None or born > latest:
                latest = born
        return latest

    @staticmethod
    def _first_clause(text: str) -> str:
        """First clause of a personality string (up to the first ./;/,) —
        the deterministic blend ingredient for a child's personality."""
        return re.split(r"[.;,]", str(text or "").strip(), maxsplit=1)[0].strip()

    def _pick_child_persona(self, personas: list[dict]) -> tuple[str, str]:
        """(name, personality) from the first UNUSED persona-library card —
        'unused' means not matching any LIVING OR DEAD agent name
        case-insensitively (a dead agent's identity is never recycled).
        Library exhausted ⇒ ("Kit-{n}", "") with the smallest free n."""
        taken = {a.name.strip().lower() for a in self.agents.values()}
        for card in personas:
            name = str(card.get("name") or "").strip()
            if name and name.lower() not in taken:
                return name, str(card.get("personality") or "").strip()
        n = 1
        while f"kit-{n}" in taken:
            n += 1
        return f"Kit-{n}", ""

    def _pick_child_profile(self) -> str:
        """The non-mock profile with the FEWEST living assigned agents, ties
        broken by stable roster order (load-spread, mirrors _pad_agents'
        non-mock rule). The roster comes from set_birth_casting (config
        order); when unseeded (direct construction / from_snapshot) it
        degrades to the living agents' non-mock profiles in sorted-id
        first-seen order, then to "mock" (an all-mock test world has nothing
        else to assign — same fallback as _pad_agents)."""
        roster = [p for p in self.birth_profile_roster if p != "mock"]
        if not roster:
            seen: list[str] = []
            for a in sorted(self.living_agents(), key=lambda x: x.id):
                if a.profile != "mock" and a.profile not in seen:
                    seen.append(a.profile)
            roster = seen or ["mock"]
        counts = {name: 0 for name in roster}
        for a in self.living_agents():
            if a.profile in counts:
                counts[a.profile] += 1
        return min(roster, key=lambda name: (counts[name], roster.index(name)))

    def _child_personality(
        self, card_personality: str, p1: AgentState, p2: AgentState
    ) -> str:
        """"Child of {p1} and {p2}. " prefix + the persona card's personality
        + a deterministic blend (first clause of each parent's personality)."""
        parts = [f"Child of {p1.name} and {p2.name}."]
        if card_personality:
            parts.append(card_personality)
        for parent in (p1, p2):
            clause = self._first_clause(parent.personality)
            if clause:
                parts.append(clause if clause.endswith(".") else clause + ".")
        return " ".join(parts)

    def check_births(self, personas: list[dict] | None = None) -> list[dict]:
        """The EM-114 birth check, run once per ROUND boundary
        (_apply_round_start). Walks partner pairs in deterministic sorted-id
        order; the FIRST pair meeting ALL conditions has a child (at most ONE
        birth per round — the world cooldown). Conditions:

          · mutual partners (B1 are_partners) co-located at a home-kind place;
          · living humans < children.max_population AND < total home beds;
          · both parents' credits >= birth_cost_credits AND energy >= 30;
          · pair cooldown (youngest shared child's birth tick, derived);
          · the seeded chance gate (_birth_roll < birth_chance).

        The child spawns via the existing spawn_agent machinery at BACKGROUND
        tier (free-scale law: never a new standing LLM call), energy 70,
        credits 0, parents set, family ties both ways, a "born in {town}"
        belief line. Both the `child_spawned` narrative event and the
        standard `agent_spawned` roster event park in pending_spawn_events
        (the proven EM-062/168 outbox, drained by the loop). Returns the
        parked events ([] when no birth). `personas` defaults to the
        loop-seeded casting pool (set_birth_casting); children.enabled false
        ⇒ no checks at all, byte-identical pre-E behavior."""
        cfg = getattr(self.params, "children", None)
        if not bool(_block_get(cfg, "enabled", True)):
            return []

        living = sorted(self.living_agents(), key=lambda a: a.id)
        max_population = int(self._chl_param("max_population", 25))
        # Free-scale proof obligation: AT (or over) the cap, no birth — ever.
        if len(living) >= max_population:
            return []
        if len(living) >= self.home_bed_capacity():
            return []

        cost = int(self._chl_param("birth_cost_credits", 6))
        cooldown = int(self._chl_param("pair_cooldown_ticks", 600))
        chance = float(self._chl_param("birth_chance", 0.25))
        pool = personas if personas is not None else self.birth_personas

        for i, a in enumerate(living):
            for b in living[i + 1:]:
                if not self.are_partners(a.id, b.id):
                    continue
                place = self.places.get(a.location)
                if place is None or place.kind != "home" or b.location != a.location:
                    continue
                if a.credits < cost or b.credits < cost:
                    continue
                if a.energy < 30 or b.energy < 30:
                    continue
                last = self._latest_pair_child_tick(a.id, b.id)
                if last is not None and self.tick - last < cooldown:
                    continue
                if self._birth_roll(a.id, b.id) >= chance:
                    continue
                events = self._spawn_child(a, b, pool, cost)
                self.pending_spawn_events.extend(events)
                return events  # world cooldown: at most ONE birth per round
        return []

    def _spawn_child(
        self, p1: AgentState, p2: AgentState, personas: list[dict], cost: int
    ) -> list[dict]:
        """Create the child for a qualified pair (check_births gates). Returns
        the ready-to-emit [child_spawned, agent_spawned] event dicts."""
        name, card_personality = self._pick_child_persona(personas)
        child = self.spawn_agent(
            name=name,
            personality=self._child_personality(card_personality, p1, p2),
            profile=self._pick_child_profile(),
            location=p1.location,           # the birth home
            cadence_tier="background",      # free-scale law
        )
        child.energy = 70.0
        child.credits = 0
        child.parents = sorted((p1.id, p2.id))
        # Both parents pay — a credits sink, not a transfer.
        p1.credits -= cost
        p2.credits -= cost
        # Family ties both ways (engine-assigned `family`, the B1 rule),
        # since_tick = birth tick — the derived pair-cooldown anchor.
        for parent in (p1, p2):
            child.relationships[parent.id] = RelationshipState(
                type="family", trust=40, interactions=1, since_tick=self.tick)
            parent.relationships[child.id] = RelationshipState(
                type="family", trust=40, interactions=1, since_tick=self.tick)
        # The contracted "memory line": beliefs is the world-side memory seam
        # (it rides every prompt via the runtime's belief lines).
        child.beliefs.append(f"Born in {self.town_name or 'the town'}.")
        return [
            {
                "kind": "child_spawned",
                "actor_id": child.id,
                "actor_type": "system",
                "text": f"👶 {child.name} is born to {p1.name} and {p2.name}",
                "payload": {
                    "child_id": child.id,
                    "parents": list(child.parents),
                    "name": child.name,
                    "profile": child.profile,
                    "place": child.location,
                },
            },
            {
                "kind": "agent_spawned",
                "actor_id": child.id,
                "actor_type": "system",
                "text": f"{child.name} is born to {p1.name} and {p2.name}.",
                "payload": {
                    "method": "birth",
                    "agent_id": child.id,
                    "name": child.name,
                    "profile": child.profile,
                    "location": child.location,
                    "parents": list(child.parents),
                },
            },
        ]

    # ──────────────────────────────────────────────────────────────────────────
    # Wave E / EM-120 — factions, feuds & reputation (contracts/wave-e.md B3).
    # Pure derived / reflex state — zero LLM calls (the wave's free-scale law).
    # ──────────────────────────────────────────────────────────────────────────

    # A faction edge needs BOTH directions typed warm (and both trusts at/above
    # faction_trust). Feuds/enemies/rivals never bind a faction together.
    FACTION_WARM_TYPES = ("ally", "friend", "partner", "family")

    def _fct_param(self, name: str, default: Any) -> Any:
        """Defensive accessor for the `world.factions` config block
        (dataclass OR dict OR absent — EM-155 conventions, like _chl_param)."""
        return _block_get(getattr(self.params, "factions", None), name, default)

    def _factions_enabled(self) -> bool:
        """Config gate `world.factions.enabled` (default ON). Disabled ⇒ no
        recompute, no faction events, no factions/reputation snapshot keys —
        byte-identical pre-E behavior."""
        return bool(self._fct_param("enabled", True))

    def reputation(self, agent_id: str) -> int:
        """EM-120 item 1 — DERIVED reputation, zero storage: round(mean
        incoming trust over LIVING agents with interactions >= 1 toward this
        agent). Nobody has a (used) relationship toward them ⇒ 0. Computed at
        serialization time (to_snapshot) — never persisted."""
        trusts = [
            rel.trust
            for a in self.living_agents()
            if a.id != agent_id
            for rel in (a.relationships.get(agent_id),)
            if rel is not None and rel.interactions >= 1
        ]
        if not trusts:
            return 0
        return round(sum(trusts) / len(trusts))

    def faction_of(self, agent_id: str) -> dict | None:
        """The faction this agent belongs to, as {id, name, members} (a copy),
        or None. Components are disjoint, so membership is unique. This is the
        world-side seam for the contracted one-line faction prompt
        ("Your circle: {name} ({k} members)") — runtime.py is owned by B4,
        which wires the line via this accessor (deviation noted in B3's
        report; the fixture world has no factions, so the protagonist prompt
        guard is unaffected either way)."""
        for fid in sorted(self.factions):
            f = self.factions[fid]
            if agent_id in f.get("members", []):
                return {
                    "id": fid,
                    "name": f.get("name", ""),
                    "members": list(f.get("members", [])),
                }
        return None

    def _mutual_warm_edge(self, a: AgentState, b: AgentState, threshold: int) -> bool:
        """True when BOTH directions are typed warm (FACTION_WARM_TYPES) AND
        both trusts >= threshold — the only edge kind factions cluster over."""
        rel_ab = a.relationships.get(b.id)
        rel_ba = b.relationships.get(a.id)
        return (
            rel_ab is not None and rel_ba is not None
            and rel_ab.type in self.FACTION_WARM_TYPES
            and rel_ba.type in self.FACTION_WARM_TYPES
            and rel_ab.trust >= threshold and rel_ba.trust >= threshold
        )

    def _warm_components(self, threshold: int) -> list[list[str]]:
        """Connected components over mutual warm edges among LIVING agents.
        Deterministic: agents are walked in sorted-id order, so components
        come out ordered by their lowest member id, members sorted."""
        living = sorted(self.living_agents(), key=lambda a: a.id)
        adjacency: dict[str, list[str]] = {a.id: [] for a in living}
        for i, a in enumerate(living):
            for b in living[i + 1:]:
                if self._mutual_warm_edge(a, b, threshold):
                    adjacency[a.id].append(b.id)
                    adjacency[b.id].append(a.id)
        components: list[list[str]] = []
        seen: set[str] = set()
        for a in living:
            if a.id in seen:
                continue
            stack, comp = [a.id], []
            seen.add(a.id)
            while stack:
                cur = stack.pop()
                comp.append(cur)
                for nxt in adjacency[cur]:
                    if nxt not in seen:
                        seen.add(nxt)
                        stack.append(nxt)
            components.append(sorted(comp))
        return components

    def _agent_name(self, agent_id: str) -> str:
        a = self.agents.get(agent_id)
        return a.name if a is not None else agent_id

    def _faction_event(self, kind: str, actor_id: str, text: str, payload: dict) -> dict:
        """A ready-to-park faction event. EM-141: actor_id is ALWAYS an agent
        id (the social-graph selector drops non-agent endpoints); these are
        standalone system events — the loop's drain stamps turn_id null."""
        return {
            "kind": kind,
            "actor_id": actor_id,
            "actor_type": "system",
            "text": text,
            "payload": payload,
        }

    def recompute_factions(self) -> list[dict]:
        """EM-120 items 2-4 — the once-per-round faction recompute, called
        from _apply_round_start AFTER check_births (contract order). Clusters
        = connected components over mutual warm edges among living agents;
        components of size >= faction_min_size are factions.

        Identity continuity: a component keeps an existing faction's id/name
        when it overlaps >= 50% of that faction's OLD membership (best
        overlap wins; ties break by faction id, then component order — all
        deterministic). Unmatched components found NEW factions
        (id = fct_{8 hex of sha1(sorted founding members + tick)}, name =
        "{oldest founding member's name}'s circle", oldest = LOWEST agent id);
        unmatched old factions DISSOLVE.

        Events fire on DIFFS ONLY — a stable round emits nothing — and park
        in the pending_spawn_events outbox (same drain as births). Returns
        the parked events ([] when stable/disabled)."""
        if not self._factions_enabled():
            return []
        threshold = int(self._fct_param("faction_trust", 25))
        min_size = max(1, int(self._fct_param("faction_min_size", 3)))
        components = [
            c for c in self._warm_components(threshold) if len(c) >= min_size
        ]

        # Identity continuity — overlap >= 50% of the OLD membership, matched
        # greedily best-overlap-first (deterministic tie-break: faction id,
        # then component order = lowest-member-id order).
        candidates: list[tuple[int, str, int]] = []
        for ci, comp in enumerate(components):
            comp_set = set(comp)
            for fid, f in self.factions.items():
                old_members = f.get("members", [])
                overlap = len(comp_set & set(old_members))
                if overlap > 0 and 2 * overlap >= len(old_members):
                    candidates.append((-overlap, fid, ci))
        candidates.sort()
        assigned: dict[int, str] = {}
        taken: set[str] = set()
        for neg_overlap, fid, ci in candidates:
            if fid in taken or ci in assigned:
                continue
            assigned[ci] = fid
            taken.add(fid)

        events: list[dict] = []
        new_factions: dict[str, dict] = {}
        for ci, comp in enumerate(components):
            if ci in assigned:
                # Continuity: keep id/name/founded_tick, diff the membership.
                fid = assigned[ci]
                old = self.factions[fid]
                name = str(old.get("name", ""))
                old_members = set(old.get("members", []))
                for m in comp:
                    if m not in old_members:
                        events.append(self._faction_event(
                            "faction_joined", m,
                            f"⚑ {self._agent_name(m)} joins {name}",
                            {"faction_id": fid, "name": name},
                        ))
                for m in sorted(old_members - set(comp)):
                    events.append(self._faction_event(
                        "faction_left", m,
                        f"⚑ {self._agent_name(m)} drifts away from {name}",
                        {"faction_id": fid, "name": name},
                    ))
                new_factions[fid] = {
                    "name": name,
                    "founded_tick": int(old.get("founded_tick", 0)),
                    "members": list(comp),
                }
            else:
                # A NEW faction. Deterministic id (sha1 — never the salted
                # builtin hash) and name; oldest member = lowest agent id.
                key = f"{':'.join(comp)}:{self.tick}".encode()
                fid = f"fct_{hashlib.sha1(key).hexdigest()[:8]}"
                name = f"{self._agent_name(comp[0])}'s circle"
                new_factions[fid] = {
                    "name": name,
                    "founded_tick": self.tick,
                    "members": list(comp),
                }
                member_names = ", ".join(self._agent_name(m) for m in comp)
                events.append(self._faction_event(
                    "faction_formed", comp[0],
                    f"⚑ {name} has formed — {member_names}",
                    {"faction_id": fid, "name": name, "members": list(comp)},
                ))
        for fid, f in self.factions.items():
            if fid not in new_factions:
                name = str(f.get("name", ""))
                old_members = [str(m) for m in f.get("members", [])]
                anchor = min(old_members) if old_members else ""
                events.append(self._faction_event(
                    "faction_dissolved", anchor,
                    f"⚑ {name} has dissolved",
                    {"faction_id": fid, "name": name, "members": old_members},
                ))
        self.factions = new_factions
        if events:
            self.pending_spawn_events.extend(events)
        return events

    def _unique_agent_name(self, name: str) -> str:
        """run-663 — never reuse a name another agent already holds. Many agents
        MAY share a MODEL (intended), but a shared NAME blends two identities
        into one — the god-admit path spawned a 2nd 'Vesper' that contradicted
        the first and showed up twice in every roster. A free name returns
        unchanged; a collision gets a roman-numeral suffix (Vesper → Vesper II →
        Vesper III…). Matches the child-spawn rule (a dead agent's identity is
        never recycled either). An already-distinct A/B label (Vesper·groq) is
        untouched."""
        base = str(name or "").strip() or "Agent"
        taken = {a.name.strip().lower() for a in self.agents.values()}
        if base.lower() not in taken:
            return base
        n = 2
        while f"{base} {_roman(n)}".lower() in taken:
            n += 1
        return f"{base} {_roman(n)}"

    def spawn_agent(
        self,
        name: str,
        personality: str,
        profile: str,
        location: str,
        cadence_tier: str = "protagonist",
        disposition: str = "lawful",
        role: str = "citizen",
    ) -> AgentState:
        name = self._unique_agent_name(name)
        agent_id = f"agent_{name.lower().replace(' ', '_')}_{str(uuid.uuid4())[:6]}"
        agent = AgentState(
            id=agent_id,
            name=name,
            personality=personality,
            profile=profile,
            location=location,
            energy=self.params.starting_energy,
            credits=self.params.starting_credits,
            # Wave D2 / EM-158 — optional tier; unknown values fall back to
            # protagonist (the zero-behavior-change default).
            cadence_tier=(
                cadence_tier if cadence_tier in self.CADENCE_TIERS else "protagonist"
            ),
            # EM-240 — additive persona schema; unknown/absent → lawful/citizen.
            disposition=disposition if disposition in ("lawful", "opportunist", "criminal") else "lawful",
            role=role if role in ("citizen", "enforcer") else "citizen",
        )
        self.agents[agent_id] = agent
        # Join the current round's rotation only when the tier is due this
        # round (EM-158); otherwise the agent waits for its next due round.
        if self._tier_due(agent, self.round):
            self._turn_order.append(agent_id)
        return agent

    def kill_agent(self, agent_id: str) -> None:
        agent = self.agents.get(agent_id)
        if agent:
            agent.alive = False
            if agent_id in self._turn_order:
                self._turn_order.remove(agent_id)

    # ──────────────────────────────────────────────────────────────────────────
    # W8 / EM-064 — animals (chaos layer). Animals are NOT in the agent
    # round-robin and have NO credits account (invariant 7).
    # ──────────────────────────────────────────────────────────────────────────

    def spawn_animal(
        self,
        species: str,
        name: str,
        location: str,
        personality: str = "",
    ) -> Animal:
        """Create an Animal and register it in world.animals. Returns the Animal.
        Location is clamped to a known place when possible. No credits (invariant 7).

        EM-143 — population cap (free-scale): when the configured
        animals.max_population > 0 and living animals already meet it, raise
        ValueError so the menagerie can't grow without bound (the API surfaces it
        as 409). Read defensively off self.params.animals.max_population so a world
        without the animals block (or the key) is unaffected (0 = unlimited)."""
        animals_cfg = getattr(self.params, "animals", None)
        max_population = int(getattr(animals_cfg, "max_population", 0) or 0)
        if max_population > 0 and len(self.living_animals()) >= max_population:
            raise ValueError(f"animal population cap reached: {max_population}")
        if location not in self.places and self.places:
            location = next(iter(self.places))
        animal_id = f"animal_{name.lower()}_{str(uuid.uuid4())[:6]}"
        animal = Animal(
            id=animal_id,
            species=str(species),
            name=str(name),
            location=str(location),
            energy=int(getattr(self.params, "starting_energy", 100)),
            created_tick=self.tick,
            personality=str(personality or ""),
        )
        self.animals[animal_id] = animal
        return animal

    def living_animals(self) -> list[Animal]:
        return [a for a in self.animals.values() if a.alive]

    def spawn_random_animal(self, seed: int) -> Animal | None:
        """Wave H2 / EM-207 — spawn ONE random catalog critter at a random existing
        place, picked DETERMINISTICALLY from `seed` (a caller-supplied seeded hash —
        no wall-clock, no RNG source — so ambient growth + rewild bursts replay
        identically). Returns the new Animal, or None when there is no place to put
        it. Honors the SAME max_population cap as spawn_animal (raises ValueError at
        the cap so callers can pre-check or catch it). The species + place + name are
        a pure function of `seed`, so a fixed seed always yields the same critter."""
        # Import here (not at module top) so engine.world keeps zero animal-runtime
        # import dependency — the catalog is the single source of truth (EM-143).
        from ..animals.runtime import ANIMAL_SPECIES_CATALOG
        species_pool = sorted(ANIMAL_SPECIES_CATALOG)
        place_pool = sorted(self.places.keys())
        if not species_pool or not place_pool:
            return None
        species = species_pool[seed % len(species_pool)]
        location = place_pool[(seed // max(1, len(species_pool))) % len(place_pool)]
        # A short deterministic name suffix so a burst of rewilds reads distinctly
        # in the feed (names need not be unique — only agent names dedupe).
        suffix = format(seed % (16 ** 4), "04x")
        name = f"{species.capitalize()} {suffix}"
        return self.spawn_animal(species=species, name=name, location=location)

    def cull_animals(self, keep: int = 5) -> list[dict]:
        """Wave H follow-on — THIN THE HERD: reduce LIVING animals down to `keep`,
        keeping the OLDEST of each distinct species first (the seed cat & dog at
        created_tick 0 lead, then species variety), removing the rest. Each removed
        animal is set alive=False and emits an `animal_died` (payload.method
        'culled') so it leaves the live feed/scene like any death. Deterministic
        (sorted by created_tick then id). No credits, no LLM. Returns the events;
        empty when already at/under `keep`."""
        keep = max(0, int(keep))
        living = sorted(self.living_animals(), key=lambda a: (a.created_tick, a.id))
        if len(living) <= keep:
            return []
        keepers: list[str] = []          # animal ids
        seen_species: set[str] = set()
        # variety-first: the oldest of each distinct species, up to `keep`.
        for a in living:
            if a.species not in seen_species and len(keepers) < keep:
                keepers.append(a.id)
                seen_species.add(a.species)
        # fill remaining slots with the next-oldest animals.
        for a in living:
            if len(keepers) >= keep:
                break
            if a.id not in keepers:
                keepers.append(a.id)
        keeper_ids = set(keepers)
        events: list[dict] = []
        for a in living:
            if a.id in keeper_ids:
                continue
            a.alive = False
            events.append({
                "kind": "animal_died",
                "actor_id": a.id,
                "actor_type": "animal",
                "text": f"{a.name} the {a.species} slips away beyond the town.",
                "payload": {
                    "animal_id": a.id,
                    "species": a.species,
                    "name": a.name,
                    "method": "culled",
                },
            })
        return events

    def trigger_zoo_escape(self, zoo_building_id: str | None = None) -> list[dict]:
        """Wave H3 / EM-208 — THE ESCAPE: a god-triggered breakout where the zoo
        animals scatter into the city causing chaos. For each OPERATIONAL zoo
        building (or only the named one when zoo_building_id is given), find the
        living animals housed AT the zoo's place and RELOCATE each to a random
        OTHER place — picked DETERMINISTICALLY (seed off the animal id + the
        current tick via the runtime _seed_int; NO wall-clock / NO RNG, so the
        breakout replays identically). Emits, per zoo with escapees, one
        `random_event` (actor_type "system", is_chaotic True, the dramatic
        "ESCAPE! N animals break loose from {zoo.name}!" line) FIRST, then one
        is_chaotic `animal_action`{action:"escape", from_place, to_place} per
        escapee. No-op (empty list) when there is no operational zoo or no housed
        animals to free. Returns the ready-to-emit event list (the caller — the
        loop / the god endpoint — emits + broadcasts)."""
        from ..animals.runtime import _seed_int
        # Determine the target zoos: operational kind=="zoo" buildings, sorted by
        # id for a deterministic order. A named id narrows to that one (and only
        # if it is itself an operational zoo).
        zoos = sorted(
            (b for b in self.buildings.values()
             if b.kind == "zoo" and b.status == "operational"),
            key=lambda b: b.id,
        )
        if zoo_building_id is not None:
            zoos = [b for b in zoos if b.id == zoo_building_id]
        events: list[dict] = []
        place_ids = sorted(self.places.keys())
        for zoo in zoos:
            housed = sorted(
                (a for a in self.living_animals() if a.location == zoo.location),
                key=lambda a: a.id,
            )
            if not housed:
                continue
            # The places an animal could flee TO: every place that is NOT the zoo.
            # With no other place there is nowhere to run — skip this zoo (no-op).
            others = [p for p in place_ids if p != zoo.location]
            if not others:
                continue
            escape_events: list[dict] = []
            for animal in housed:
                from_place = animal.location
                seed = _seed_int("zoo_escape", animal.id, self.tick)
                to_place = others[seed % len(others)]
                animal.location = to_place
                escape_events.append({
                    "kind": "animal_action",
                    "actor_id": animal.id,
                    "actor_type": "animal",
                    "target_id": None,
                    "is_chaotic": True,
                    "text": f"{animal.name} the {animal.species} bolts from "
                            f"{zoo.name} and scatters into the city!",
                    "payload": {
                        "species": animal.species,
                        "name": animal.name,
                        "action": "escape",
                        "from_place": from_place,
                        "to_place": to_place,
                        "building_id": zoo.id,
                    },
                })
            # The dramatic banner leads, then each critter's escape line.
            events.append({
                "kind": "random_event",
                "actor_id": None,
                "actor_type": "system",
                "target_id": None,
                "turn_id": None,
                "is_chaotic": True,
                "text": f"ESCAPE! {len(escape_events)} animals break loose "
                        f"from {zoo.name}!",
                "payload": {
                    "event": "zoo_escape",
                    "building_id": zoo.id,
                    "zoo_name": zoo.name,
                    "escaped": len(escape_events),
                },
            })
            events.extend(escape_events)
        return events

    # EM-134 — per-building animal-damage cooldown: a building an animal damaged
    # within the last N ticks cannot lose health to an animal again (the same
    # critter re-damaged one booth twice in 6 ticks, straight after a repair).
    # Keeps the chaos — the FIRST hit always lands — while stopping a new build
    # from being perma-griefed. Human arson is deliberately unaffected.
    ANIMAL_DAMAGE_COOLDOWN_TICKS = 6

    def animal_damage_building(self, building_id: str, amount: int) -> dict | None:
        """World-side entry point for an animal damaging a building (cat/dog arson
        or a knock_over on a structure). Reuses the SHARED _damage_building path so
        invariant 8 holds identically to human arson (operational->damaged->
        destroyed, health clamped 0..100). Animals do NOT alter agent trust (no
        standing). Returns the structure_state_changed event dict, or None if the
        building is missing / already destroyed / on its animal-damage cooldown
        (no-op — AnimalRuntime renders a harmless in-character line for None).
        actor_id is left None here; AnimalRuntime stamps actor_id/actor_type on
        the emitted event."""
        building = self.buildings.get(building_id)
        if building is None or building.status == "destroyed":
            return None
        # EM-134 — within the cooldown window the critter gets shooed away:
        # no health loss, no state change, the attempt resolves harmlessly.
        if self.tick - building.last_animal_damage_tick < self.ANIMAL_DAMAGE_COOLDOWN_TICKS:
            return None
        building.last_animal_damage_tick = self.tick
        return self._damage_building(building, amount, None, "animal")

    def turns_until_death(self, agent: AgentState) -> int | None:
        """W9 / EM-070 — turns left before a zero-energy agent dies, from the
        existing death_after_zero_turns tracking. None when energy > 0 or dead."""
        if not agent.alive or agent.energy > 0:
            return None
        return max(0, self.params.death_after_zero_turns - agent.zero_energy_turns)

    def to_snapshot(self, profile_colors: dict[str, str] | None = None) -> dict:
        pc = profile_colors or {}
        # Wave E / EM-120 — reputation is DERIVED (zero storage) and computed
        # at serialization. Documented seam choice: AgentState.to_dict has no
        # world backref and its only production call site is THIS method (the
        # loop's world_state broadcast and /api/state both go through
        # to_snapshot), so the additive `reputation` key is attached here,
        # beside turns_until_death. Gated on factions.enabled so a disabled
        # world keeps the exact pre-E agent dict shape (byte-identical proof).
        fct_enabled = self._factions_enabled()
        snap = {
            "tick": self.tick,
            "day": self.day,
            "running": self.running,
            "tick_interval_seconds": self.tick_interval_seconds,
            # W9 / EM-073 B8 — scheduler state, so a fold-forward replay can
            # faithfully project rounds (UBI), turn order, and turn position
            # (event-log.md v1.1.0 §3). Additive keys; consumers may ignore.
            "round": self.round,
            "turn_order": list(self._turn_order),
            "turn_index": self._turn_index,
            "round_start": self._round_start,
            "places": [p.to_dict() for p in self.places.values()],
            "agents": [
                {
                    **a.to_dict(pc.get(a.profile, "#888888")),
                    # W9 / EM-070 — starvation countdown (null when energy > 0).
                    "turns_until_death": self.turns_until_death(a),
                    # Wave E / EM-120 — derived reputation (additive key;
                    # consumers may ignore; absent while factions disabled).
                    **({"reputation": self.reputation(a.id)} if fct_enabled else {}),
                }
                for a in self.agents.values()
            ],
            "rules": [r.to_dict() for r in self.rules.values()],
            "buildings": [b.to_dict() for b in self.buildings.values()],
            # W8 — chaos-layer animals; the 3D village renders a roaming cat + dog.
            "animals": [a.to_dict() for a in self.animals.values()],
            # Wave K / EM-218 — placeable props (the builders'-city decorations).
            # ALWAYS serialized (like animals/buildings) — a snapshot round-trip /
            # replay / fork reproduces the exact prop registry byte-identically.
            "props": [p.to_dict() for p in self.props.values()],
            # W11b / EM-091 — the public billboard: list of {tick, actor_id,
            # actor_type, text}, capped 20 newest (oldest → newest). THE seam the
            # frontend's billboard panel/3D board builds against.
            "billboard": [dict(e) for e in self.billboard],
            # PROTOTYPE (god-channel) — loud-tier proclamations {id,tick,text,replies}.
            "proclamations": [
                {**p, "replies": [dict(r) for r in p.get("replies", [])]}
                for p in self.proclamations
            ],
            # PROTOTYPE (god-channel) — the consensus-set town name ("" = unnamed).
            "town_name": self.town_name,
            # W15 / EM-155 — deterministic city seed: the frontend renders the
            # generated city ring as f(snapshot, city_seed). Additive key;
            # consumers default with `city_seed ?? 1337` when absent.
            "city_seed": self.city_seed,
            # EM-145 — queued-but-undelivered god whispers, so a restart/restore
            # no longer eats them (additive key; consumers may ignore).
            "pending_whispers": {
                aid: list(lines)
                for aid, lines in self.pending_whispers.items()
                if lines
            },
        }
        # Wave D3 / EM-168 — per-lane cap-governor demotion records (lane ->
        # alert-day window). Serialized only when a demotion is outstanding so
        # ungoverned snapshots keep the exact pre-D3 key set; the agents list
        # already carries each governed agent's demoted_from (AgentState.to_dict).
        if self.cap_demotions:
            snap["cap_demotions"] = dict(self.cap_demotions)
        # Wave E / EM-120 — factions {id: {name, founded_tick, members}}.
        # Serialized only when non-empty (the cap_demotions pattern), so a
        # faction-free world — and every pre-E snapshot — keeps the exact
        # pre-E key set (absent ⇒ {} on restore).
        if self.factions:
            snap["factions"] = {
                fid: {
                    "name": str(f.get("name", "")),
                    "founded_tick": int(f.get("founded_tick", 0)),
                    "members": [str(m) for m in f.get("members", [])],
                }
                for fid, f in self.factions.items()
            }
        # Wave E / EM-184 — active timed miracles [{kind, until_tick}].
        # Serialized only when non-empty (the cap_demotions pattern), so a
        # miracle-free world — and every pre-E snapshot — keeps the exact
        # pre-E key set (absent ⇒ [] on restore).
        if self.active_miracles:
            snap["active_miracles"] = [
                {"kind": str(m.get("kind", "")),
                 "until_tick": int(m.get("until_tick", 0))}
                for m in self.active_miracles
            ]
        # Wave I / EM-210+213 — the gallery + the voted plaza banner. Serialized
        # ONLY when present (the cap_demotions pattern), so a Wave-I-free world —
        # and every pre-Wave-I snapshot — keeps the exact prior key set (absent ⇒
        # [] / "" on restore). pending_image_fetches is NEVER serialized (transient
        # outbox; the PNG is an external side-artifact off the replay surface).
        if self.gallery:
            snap["gallery"] = [dict(g) for g in self.gallery]
        if self.plaza_banner_ref:
            snap["plaza_banner_ref"] = self.plaza_banner_ref
        # EM-123 — zoned-neighborhood maturity. Serialized ONLY when a tier has
        # diverged from the derivable baseline (tier 1 / progress 0), so a fresh
        # world — and every pre-EM-123 snapshot — keeps the exact prior key set
        # (the cap_demotions pattern). When absent, from_snapshot + the frontend
        # both re-derive the baseline from the places, rendering identically.
        if any(nb.tier > 1 or nb.progress for nb in self.neighborhoods.values()):
            snap["neighborhoods"] = [
                self.neighborhoods[nid].to_dict()
                for nid in sorted(self.neighborhoods)
            ]
        return snap

    # ──────────────────────────────────────────────────────────────────────────
    # W11b / EM-101 — snapshot restore (the missing half of to_snapshot).
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def from_snapshot(
        cls,
        state: dict,
        *,
        place_overrides: list | None = None,
        params: Any = None,
    ) -> "World":
        """Reconstruct a live World from a snapshot `state` dict (the
        to_snapshot()/world_state shape). The contracted seam for the fork
        endpoint (POST /api/runs/fork): `World.from_snapshot(replay(T))` is a
        forked run's tick-0 world.

        - `place_overrides` (optional) REPLACES the places wholesale: a list of
          place dicts in the same shape as snapshot["places"].
        - `params` (optional, additive) supplies WorldParams; defaults to a
          fresh WorldParams() when omitted.

        Restores tick/day/round, turn order + index, agents (incl. relationships,
        mood, zero_energy_turns), rules (votes, payload, renewal bookkeeping),
        buildings, animals, blackout state, and the billboard. Known limits:
        agent beliefs are not serialized by to_snapshot (only beliefs_count), so
        they restore empty; `running` always restores False (a fork starts
        paused)."""
        if params is None:
            from ..config.loader import WorldParams  # lazy: keep world.py import-light
            params = WorldParams()

        def _int(v: Any, default: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        place_dicts = place_overrides if place_overrides is not None else state.get("places", [])
        places = [
            PlaceState(
                id=str(d["id"]),
                name=str(d.get("name", d["id"])),
                x=_int(d.get("x")),
                y=_int(d.get("y")),
                kind=str(d.get("kind", "social")),
                description=str(d.get("description", "")),
                capacity=(_int(d["capacity"]) if d.get("capacity") is not None else None),
                blackout_until_tick=_int(d.get("blackout_until_tick")),
                # Wave C / EM-147 — optional district; pre-Wave-C snapshots
                # lack the key and restore as None (back-compat by contract).
                district=(str(d["district"]) if d.get("district") is not None else None),
                # EM-123 — optional neighborhood/zone overrides; absent ⇒ None
                # (the place's district is its neighborhood, zone is derived).
                neighborhood_id=(str(d["neighborhood_id"]) if d.get("neighborhood_id") is not None else None),
                zone_kind=(str(d["zone_kind"]) if d.get("zone_kind") is not None else None),
            )
            for d in (place_dicts or [])
            if isinstance(d, dict) and d.get("id")
        ]

        agents: list[AgentState] = []
        for d in state.get("agents", []) or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            a = AgentState(
                id=str(d["id"]),
                name=str(d.get("name", d["id"])),
                personality=str(d.get("personality", "")),
                profile=str(d.get("profile", "mock")),
                location=str(d.get("location", "")),
                energy=float(d.get("energy", 0.0) or 0.0),
                credits=_int(d.get("credits")),
                mood=str(d.get("mood", "neutral")),
                alive=bool(d.get("alive", True)),
                zero_energy_turns=_int(d.get("zero_energy_turns")),
                # Wave D2 / EM-158+160 — additive keys; pre-D2 snapshots lack
                # them and restore the protagonist / zero-streak defaults.
                cadence_tier=(
                    str(d.get("cadence_tier"))
                    if d.get("cadence_tier") in cls.CADENCE_TIERS
                    else "protagonist"
                ),
                reflex_streak=max(0, _int(d.get("reflex_streak"))),
                # Wave D3 / EM-168 — additive: pre-D3 snapshots lack the key
                # (and unknown tier values restore ungoverned, fail-safe).
                demoted_from=(
                    str(d.get("demoted_from"))
                    if d.get("demoted_from") in cls.CADENCE_TIERS
                    else None
                ),
                # Wave E / EM-114 — additive: pre-E snapshots lack the key and
                # restore [] (the pair birth cooldown derives from this field,
                # so a restored world never re-births inside the window).
                parents=[str(p) for p in (d.get("parents") or [])],
                # Wave L / EM-223 — additive: pre-EM-223 snapshots lack the key
                # and restore None; a malformed stored plan coerces to None
                # (normalize_plan is total). Byte-stable round-trip (EM-155).
                plan=normalize_plan(d.get("plan")),
                # EM-240 — additive: pre-EM-240 snapshots lack the keys and
                # restore the lawful/citizen defaults (unknown values fail-safe).
                disposition=(str(d.get("disposition")) if d.get("disposition")
                             in ("lawful", "opportunist", "criminal") else "lawful"),
                role=(str(d.get("role")) if d.get("role")
                      in ("citizen", "enforcer") else "citizen"),
                # EM-240 — crime status scalars: additive. Pre-EM-240 snapshots
                # lack these keys and restore the clean defaults; notoriety is
                # clamped 0..100 and an unknown crime_status fails safe to None.
                notoriety=max(0, min(100, _int(d.get("notoriety")))),
                crime_status=(str(d.get("crime_status")) if d.get("crime_status")
                              in ("wanted", "detained", "jailed", "exiled") else None),
                crime_status_until_tick=_int(d.get("crime_status_until_tick")),
                rap_sheet=[dict(e) for e in (d.get("rap_sheet") or []) if isinstance(e, dict)],
                # EM-229 — needs: additive. Pre-EM-229 snapshots lack the keys
                # and restore the full default (100.0); a present value is clamped
                # 0..100 and a malformed value fails safe to 100.0. Byte-stable
                # round-trip (EM-155): a full need is never re-emitted.
                knowledge=_clamp_need(d.get("knowledge")),
                influence=_clamp_need(d.get("influence")),
                # EM-233 — soul: additive. Pre-EM-233 snapshots lack the key and
                # restore []; a present value is coerced to a list of non-blank
                # strings and truncated to the configured soul_cap (defensive
                # restore: a tampered over-cap soul never grows past the cap).
                # Byte-stable round-trip (EM-155): an empty soul is never
                # re-emitted, so a soulless agent's dict is unchanged.
                soul=_coerce_soul(
                    d.get("soul"),
                    _block_get(getattr(params, "memory", None), "soul_cap", 3),
                ),
            )
            a.relationships = {
                str(aid): RelationshipState(
                    type=str(_block_get(r, "type", "neutral")),
                    trust=_int(_block_get(r, "trust", 0)),
                    interactions=_int(_block_get(r, "interactions", 0)),
                    # Wave E / EM-113 — additive; pre-E snapshots restore 0.
                    since_tick=_int(_block_get(r, "since_tick", 0)),
                )
                for aid, r in (d.get("relationships") or {}).items()
            }
            agents.append(a)

        world = cls(params, places, agents)
        # __init__ may have run procgen (params.procgen.enabled); a snapshot's
        # geometry is authoritative — force the restored/overridden places back.
        world.places = {p.id: p for p in places}

        world.tick = _int(state.get("tick"))
        world.day = _int(state.get("day"))
        world.round = _int(state.get("round"))
        # W15 / EM-155 — restore the city seed (int-coerced). A pre-W15
        # snapshot lacks the key and restores the default 1337, matching the
        # frontend's `city_seed ?? 1337` so fork/replay render the same city.
        world.city_seed = _int(state.get("city_seed", 1337), 1337)
        world.running = False  # a restored/forked world starts paused
        try:
            world.tick_interval_seconds = float(
                state.get("tick_interval_seconds", params.tick_interval_seconds)
            )
        except (TypeError, ValueError):
            pass

        # Scheduler state (event-log v1.1.0 §3): round/turn order/turn index.
        turn_order = state.get("turn_order")
        if isinstance(turn_order, list) and turn_order:
            world._turn_order = [str(t) for t in turn_order if str(t) in world.agents]
        world._turn_index = max(0, min(_int(state.get("turn_index")), len(world._turn_order)))
        world._round_start = bool(state.get("round_start", world._turn_index == 0))

        for d in state.get("rules", []) or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            status = str(d.get("status", "proposed"))
            rule = RuleState(
                id=str(d["id"]),
                effect=str(d.get("effect", "")),
                text=str(d.get("text", "")),
                proposer_id=str(d.get("proposer_id", "")),
                status=status,
                votes={str(k): bool(v) for k, v in (d.get("votes") or {}).items()},
                created_tick=_int(d.get("created_tick")),
                payload=dict(d.get("payload") or {}),
                # `applied` is not serialized; a non-proposed admit_agent rule
                # already had its side effects — guard against a double spawn.
                applied=status != "proposed",
                renewal_of=d.get("renewal_of"),
                renewed_at=[_int(t) for t in (d.get("renewed_at") or [])],
            )
            world.rules[rule.id] = rule

        for d in state.get("buildings", []) or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            b = Building(
                id=str(d["id"]),
                name=str(d.get("name", d["id"])),
                kind=str(d.get("kind", "")),
                location=str(d.get("location", "")),
                owner_id=d.get("owner_id", "public"),
                status=str(d.get("status", "planned")),
                health=_int(d.get("health"), 100),
                progress=_int(d.get("progress")),
                funds_committed=_int(d.get("funds_committed")),
                funds_required=_int(d.get("funds_required")),
                contributors=[str(c) for c in (d.get("contributors") or [])],
                function=str(d.get("function", "")),
                last_progress_tick=_int(d.get("last_progress_tick")),
                created_tick=_int(d.get("created_tick")),
                updated_tick=_int(d.get("updated_tick")),
                commemorates=d.get("commemorates"),
                # Wave K / EM-220 — restore the owner-set skin (pre-Wave-K
                # snapshots lack the key ⇒ None, byte-identical default).
                skin=(str(d["skin"]) if d.get("skin") else None),
            )
            world.buildings[b.id] = b

        for d in state.get("animals", []) or []:
            if not isinstance(d, dict) or not d.get("id"):
                continue
            an = Animal(
                id=str(d["id"]),
                species=str(d.get("species", "")),
                name=str(d.get("name", d["id"])),
                location=str(d.get("location", "")),
                energy=_int(d.get("energy"), 100),
                mood=str(d.get("mood", "content")),
                alive=bool(d.get("alive", True)),
                created_tick=_int(d.get("created_tick")),
                owner_id=(str(d["owner_id"]) if d.get("owner_id") else None),
            )
            world.animals[an.id] = an

        # Wave K / EM-218 — restore placeable props (pre-Wave-K snapshots lack the
        # key ⇒ {} — a back-compat tolerated absence). The seeded id, place, and
        # engine-assigned offset round-trip byte-identically, so a replay/fork
        # renders the same decorations.
        def _flt(v: Any, default: float = 0.0) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        for d in state.get("props", []) or []:
            if not isinstance(d, dict) or not d.get("id") or not d.get("place"):
                continue
            p = Prop(
                id=str(d["id"]),
                kind=str(d.get("kind", "")),
                place=str(d["place"]),
                dx=_flt(d.get("dx")),
                dz=_flt(d.get("dz")),
                owner_id=(str(d["owner_id"]) if d.get("owner_id") else None),
            )
            world.props[p.id] = p

        world.billboard = [
            {
                "tick": _int(_block_get(e, "tick", 0)),
                "actor_id": str(_block_get(e, "actor_id", "")),
                "actor_type": str(_block_get(e, "actor_type", "human_agent")),
                "text": str(_block_get(e, "text", ""))[: cls.BILLBOARD_TEXT_CAP],
            }
            for e in (state.get("billboard") or [])[-cls.BILLBOARD_CAP:]
        ]
        # PROTOTYPE (god-channel) — restore loud-tier proclamations (round-trips
        # to_snapshot exactly: same {id, tick, text, replies} shape).
        world.proclamations = [
            {
                "id": str(_block_get(p, "id", f"proc-{_int(_block_get(p, 'tick', 0))}-{i}")),
                "tick": _int(_block_get(p, "tick", 0)),
                "text": str(_block_get(p, "text", ""))[: cls.BILLBOARD_TEXT_CAP],
                "replies": [dict(r) for r in (_block_get(p, "replies", []) or [])],
            }
            for i, p in enumerate((state.get("proclamations") or [])[-cls.PROCLAMATION_CAP:])
        ]
        # PROTOTYPE (god-channel) — the consensus-set town name.
        world.town_name = str(state.get("town_name", "") or "")
        # Wave D3 / EM-168 — restore the cap-governor demotion records (absent
        # in pre-D3 snapshots ⇒ {}), so a fork/restore still restores tiers at
        # the next day rollover and never re-demotes the same lane-alert-day.
        world.cap_demotions = {
            str(lane): str(win)
            for lane, win in (state.get("cap_demotions") or {}).items()
            if lane and win
        }
        # Wave E / EM-120 — restore factions (additive: pre-E snapshots lack
        # the key and restore {} — identity continuity then survives a
        # fork/restore, so a stable membership re-keeps its id with no events).
        world.factions = {
            str(fid): {
                "name": str(_block_get(f, "name", "")),
                "founded_tick": _int(_block_get(f, "founded_tick", 0)),
                "members": [str(m) for m in (_block_get(f, "members", []) or [])],
            }
            for fid, f in (state.get("factions") or {}).items()
            if fid
        }
        # Wave E / EM-184 — restore active timed miracles (additive: pre-E
        # snapshots lack the key and restore [] — a mid-rain snapshot keeps
        # its buff on resume and still expires on schedule).
        world.active_miracles = [
            {"kind": str(m.get("kind", "")),
             "until_tick": _int(m.get("until_tick", 0))}
            for m in (state.get("active_miracles") or [])
            if isinstance(m, dict) and m.get("kind")
        ]
        # Wave I / EM-210+213 — restore the gallery + the voted plaza banner
        # (additive: pre-Wave-I snapshots lack the keys and restore [] / "", so a
        # fork/replay of an Atelier world re-hangs the same banner and re-lists the
        # same art). Drop malformed gallery rows defensively (id required).
        world.gallery = [
            dict(g) for g in (state.get("gallery") or [])
            if isinstance(g, dict) and g.get("image_id")
        ]
        world.plaza_banner_ref = str(state.get("plaza_banner_ref", "") or "")
        # EM-123 — restore zoned-neighborhood maturity. The baseline (tier 1)
        # neighborhoods are already derived from the restored places by __init__;
        # here we OVERLAY the serialized tier/progress. Absent in pre-EM-123
        # snapshots ⇒ the derived baseline stands, so a fork/replay re-renders
        # tier 1 identically. A serialized id with no matching place (the place
        # set changed) is re-created from its dict so its maturity is not lost.
        for d in (state.get("neighborhoods") or []):
            if not isinstance(d, dict) or not d.get("id"):
                continue
            nid = str(d["id"])
            nb = world.neighborhoods.get(nid)
            if nb is not None:
                nb.tier = max(1, _int(d.get("tier"), 1))
                nb.progress = max(0, _int(d.get("progress")))
            elif d.get("zone_kind"):
                world.neighborhoods[nid] = Neighborhood(
                    id=nid,
                    name=str(d.get("name") or _neighborhood_display_name(nid)),
                    zone_kind=str(d["zone_kind"]),
                    tier=max(1, _int(d.get("tier"), 1)),
                    progress=max(0, _int(d.get("progress"))),
                )
        # EM-145 — restore queued god whispers (only for agents that exist).
        world.pending_whispers = {
            str(aid): [str(t) for t in (lines or []) if str(t).strip()]
            for aid, lines in (state.get("pending_whispers") or {}).items()
            if str(aid) in world.agents and lines
        }
        return world

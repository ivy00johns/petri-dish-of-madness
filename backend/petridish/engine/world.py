"""
World state: pure data model.  No I/O, no asyncio.  Testable in isolation.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RelationshipState:
    type: str = "neutral"  # ally|rival|neutral|friend|enemy
    trust: int = 0          # -100..100
    interactions: int = 0


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
    beliefs: list[str] = field(default_factory=list)
    relationships: dict[str, RelationshipState] = field(default_factory=dict)

    def to_dict(self, profile_color: str = "#888888") -> dict:
        return {
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
            "beliefs_count": len(self.beliefs),
            "relationships": {
                aid: {"type": r.type, "trust": r.trust, "interactions": r.interactions}
                for aid, r in self.relationships.items()
            },
        }


@dataclass
class PlaceState:
    id: str
    name: str
    x: int
    y: int
    kind: str   # work|home|social|governance|wild
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "kind": self.kind,
            "description": self.description,
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

    @property
    def condition_label(self) -> str:
        return _condition_label(self.health)

    def to_dict(self) -> dict:
        return {
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
        }


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
        # W7 / EM-062 — governance-spawn outbox. When an `admit_agent` rule passes,
        # the world spawns the pending agent and parks an `agent_spawned{method:
        # governance}` event here; the runtime/api layer drains it after a vote and
        # emits it through the normal event pipeline. Keeps action_vote's signature
        # intact while letting the spawn happen world-side (single source of truth).
        self.pending_spawn_events: list[dict] = []

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

    # ──────────────────────────────────────────────────────────────────────────
    # Scheduler
    # ──────────────────────────────────────────────────────────────────────────

    def living_agents(self) -> list[AgentState]:
        return [a for a in self.agents.values() if a.alive]

    def _rebuild_turn_order(self) -> None:
        """Rebuild turn order preserving relative position of existing agents."""
        alive_ids = {a.id for a in self.living_agents()}
        self._turn_order = [aid for aid in self._turn_order if aid in alive_ids]
        # Add any newly spawned agents at the end
        for aid in sorted(self.agents.keys()):
            if aid not in self._turn_order and aid in alive_ids:
                self._turn_order.append(aid)

    def next_agent(self) -> AgentState | None:
        """Return the next agent whose turn it is, advancing the pointer.
        Returns None if no living agents.
        Detects round boundaries and applies per-round effects."""
        self._rebuild_turn_order()
        if not self._turn_order:
            return None

        # Detect if we're starting a new round
        if self._turn_index >= len(self._turn_order):
            self._turn_index = 0
            self._round_start = True

        if self._round_start:
            self._apply_round_start()
            self._round_start = False

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

    def _active_rule(self, effect: str) -> RuleState | None:
        for rule in self.rules.values():
            if rule.status == "active" and rule.effect == effect:
                return rule
        return None

    def has_active_rule(self, effect: str) -> bool:
        return self._active_rule(effect) is not None

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

    # ──────────────────────────────────────────────────────────────────────────
    # Energy / death
    # ──────────────────────────────────────────────────────────────────────────

    def apply_energy_decay(self, agent: AgentState) -> None:
        agent.energy = max(0.0, agent.energy - self.params.energy_decay_per_turn)

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
        if self.operational_building_at(agent.location, "workshop") is not None:
            pct = self._bld_param("work_bonus_pct", 0)
            reward = int(reward * (1 + pct / 100.0))
        agent.credits += reward
        return True, "ok", reward

    def action_forage(self, agent: AgentState) -> tuple[bool, str, int]:
        reward = self.params.forage_reward
        # W7: an operational garden/farm at this place grants +forage_bonus.
        if (
            self.operational_building_at(agent.location, "garden") is not None
            or self.operational_building_at(agent.location, "farm") is not None
        ):
            reward += self._bld_param("forage_bonus", 0)
        agent.credits += reward
        return True, "ok", reward

    def action_recharge(self, agent: AgentState) -> tuple[bool, str, float]:
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
        # Relationship escalation for target
        rel = target.relationships.get(agent.id)
        if rel is None or rel.type not in ("rival", "enemy"):
            if rel is None:
                rel = RelationshipState()
                target.relationships[agent.id] = rel
            if rel.trust < -20:
                rel.type = "enemy"
            else:
                rel.type = "rival"
        return True, "ok", amount

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
        valid = {"ally", "rival", "neutral", "friend", "enemy"}
        if rel_type not in valid:
            return False, f"invalid relationship type: {rel_type!r}"
        if agent.id not in agent.relationships:
            agent.relationships[target.id] = RelationshipState()
        agent.relationships[target.id].type = rel_type
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

    def action_propose_rule(
        self, agent: AgentState, effect: str, text: str
    ) -> tuple[bool, str, RuleState | None]:
        # W9 / EM-073 B3: ban_arson included so the arson ban is reachable via
        # governance (enforcement already gates arson in the runtime validator).
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus", "ban_arson"}
        if effect not in valid_effects:
            return False, f"invalid effect: {effect!r}", None
        # Check for duplicate active or proposed rule with same effect
        for rule in self.rules.values():
            if rule.effect == effect and rule.status == "proposed":
                return False, f"rule with effect {effect!r} already proposed", None
        rule = RuleState(
            id=str(uuid.uuid4())[:8],
            effect=effect,
            text=text,
            proposer_id=agent.id,
            created_tick=self.tick,
        )
        self.rules[rule.id] = rule
        return True, "ok", rule

    def action_vote(
        self, agent: AgentState, rule_id: str, choice: bool
    ) -> tuple[bool, str, str | None]:
        """Returns (success, reason, new_status_if_changed)."""
        rule = self.rules.get(rule_id)
        if rule is None:
            return False, f"unknown rule {rule_id!r}", None
        if rule.status != "proposed":
            return False, f"rule {rule_id!r} is {rule.status!r}, not proposed", None

        rule.votes[agent.id] = choice
        new_status = self._evaluate_rule(rule)
        if new_status and new_status != rule.status:
            rule.status = new_status
            if new_status == "active":
                self._on_rule_activated(rule)
            return True, "ok", new_status
        return True, "ok", None

    def _on_rule_activated(self, rule: RuleState) -> None:
        """Side effects of a rule becoming active. For W7/EM-062 governance spawn:
        an `admit_agent` rule carries the pending agent spec on `rule.payload`;
        the moment it activates we spawn that agent and park an
        `agent_spawned{method:governance, proposal_id}` event in the outbox for the
        runtime/api layer to drain and emit. Other effects (ubi/work_bonus/...) are
        passive and read elsewhere, so nothing to do here."""
        if rule.effect != "admit_agent" or rule.applied:
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
    ) -> RuleState:
        """Create an `admit_agent` governance proposal (EM-062 governance spawn).
        The pending agent spec rides on rule.payload; the agent enters only if the
        vote passes threshold (handled in _on_rule_activated). Used by the
        POST /api/agents governance path (runtime-api-agent)."""
        rule = RuleState(
            id=str(uuid.uuid4())[:8],
            effect="admit_agent",
            text=text or f"Admit {name} to the village.",
            proposer_id=proposer_id,
            created_tick=self.tick,
            payload={
                "name": name,
                "personality": personality,
                "profile": profile,
                "location": location,
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

    def action_propose_project(
        self,
        agent: AgentState,
        name: str,
        kind: str,
        funds_required: int,
        function: str | None = None,
    ) -> dict:
        """Create a Building status=planned at the agent's place, owner=public.
        Emits structure_state_changed{to:planned} + project_proposed."""
        try:
            funds_required = max(0, int(funds_required))
        except (TypeError, ValueError):
            funds_required = 0
        building = Building(
            id=f"bld_{str(uuid.uuid4())[:8]}",
            name=str(name)[:60],
            kind=str(kind)[:30],
            location=agent.location,
            owner_id="public",
            status="planned",
            funds_required=funds_required,
            function=(function or "")[:40],
            last_progress_tick=self.tick,
            created_tick=self.tick,
            updated_tick=self.tick,
        )
        self.buildings[building.id] = building
        proposed_evt = {
            "kind": "project_proposed",
            "actor_id": agent.id,
            "text": f"{agent.name} proposes a {building.kind}: {building.name} "
                    f"(needs {funds_required} credits).",
            "payload": {
                "building_id": building.id,
                "name": building.name,
                "kind": building.kind,
                "location": building.location,
                "funds_required": funds_required,
                "function": building.function,
            },
        }
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
        if agent.credits < amount:
            return self._fail_event(
                agent.id, "contribute_funds",
                f"insufficient credits: have {agent.credits}, need {amount}",
                f"{agent.name} cannot afford to contribute {amount} credits.")

        agent.credits -= amount
        building.funds_committed += amount
        if agent.id not in building.contributors:
            building.contributors.append(agent.id)
        building.updated_tick = self.tick

        economy_evt = {
            "kind": "economy",
            "actor_id": agent.id,
            "target_id": building.id,
            "text": f"{agent.name} contributes {amount} credits to {building.name}.",
            "payload": {
                "action": "contribute_funds",
                "building_id": building.id,
                "amount": amount,
                "credits_delta": -amount,
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
            building.progress = 100
            building.status = "operational"
            building.health = 100
            building.updated_tick = self.tick
            events.append(self._structure_state_changed_event(
                building, "under_construction", "operational", "completed", agent.id))
            events.append({
                "kind": "building_operational",
                "actor_id": agent.id,
                "target_id": building.id,
                "text": f"{building.name} is now operational"
                        + (f" ({building.function})" if building.function else "") + ".",
                "payload": {
                    "building_id": building.id,
                    "kind": building.kind,
                    "function": building.function,
                    "location": building.location,
                },
            })
        return {"_multi": events}

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
        """Advance building lifecycle once per round. Any non-operational building
        that has had no fund/build activity for buildings.abandon_after_ticks (and
        is not already in a terminal state) becomes abandoned. Returns the list of
        structure_state_changed events to emit. This makes the 'clock tower that
        never got built' real."""
        window = int(self._bld_param("abandon_after_ticks", 40))
        if window <= 0:
            return []
        events: list[dict] = []
        # Skip statuses that represent a *completed* structure (operational/offline)
        # or a terminal one (abandoned/destroyed). Only planned/under_construction/
        # damaged structures can rot from lack of follow-through. An owner-offlined
        # building was built — it isn't "abandoned for no follow-through".
        skip = {"operational", "offline", "abandoned", "destroyed"}
        for building in self.buildings.values():
            if building.status in skip:
                continue
            if self.tick - building.last_progress_tick > window:
                frm = building.status
                building.status = "abandoned"
                building.updated_tick = self.tick
                events.append(self._structure_state_changed_event(
                    building, frm, "abandoned", "no follow-through", None))
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

    def agents_at(self, place_id: str) -> list[AgentState]:
        return [a for a in self.living_agents() if a.location == place_id]

    def spawn_agent(self, name: str, personality: str, profile: str, location: str) -> AgentState:
        agent_id = f"agent_{name.lower()}_{str(uuid.uuid4())[:6]}"
        agent = AgentState(
            id=agent_id,
            name=name,
            personality=personality,
            profile=profile,
            location=location,
            energy=self.params.starting_energy,
            credits=self.params.starting_credits,
        )
        self.agents[agent_id] = agent
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
        Location is clamped to a known place when possible. No credits (invariant 7)."""
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

    def animal_damage_building(self, building_id: str, amount: int) -> dict | None:
        """World-side entry point for an animal damaging a building (cat/dog arson
        or a knock_over on a structure). Reuses the SHARED _damage_building path so
        invariant 8 holds identically to human arson (operational->damaged->
        destroyed, health clamped 0..100). Animals do NOT alter agent trust (no
        standing). Returns the structure_state_changed event dict, or None if the
        building is missing / already destroyed (no-op). actor_id is left None here;
        AnimalRuntime stamps actor_id/actor_type on the emitted event."""
        building = self.buildings.get(building_id)
        if building is None or building.status == "destroyed":
            return None
        return self._damage_building(building, amount, None, "animal")

    def turns_until_death(self, agent: AgentState) -> int | None:
        """W9 / EM-070 — turns left before a zero-energy agent dies, from the
        existing death_after_zero_turns tracking. None when energy > 0 or dead."""
        if not agent.alive or agent.energy > 0:
            return None
        return max(0, self.params.death_after_zero_turns - agent.zero_energy_turns)

    def to_snapshot(self, profile_colors: dict[str, str] | None = None) -> dict:
        pc = profile_colors or {}
        return {
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
                }
                for a in self.agents.values()
            ],
            "rules": [r.to_dict() for r in self.rules.values()],
            "buildings": [b.to_dict() for b in self.buildings.values()],
            # W8 — chaos-layer animals; the 3D village renders a roaming cat + dog.
            "animals": [a.to_dict() for a in self.animals.values()],
        }

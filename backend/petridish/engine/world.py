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
    effect: str           # ban_stealing|ubi|recharge_subsidy|work_bonus
    text: str
    proposer_id: str
    status: str = "proposed"   # proposed|active|rejected
    votes: dict[str, bool] = field(default_factory=dict)
    created_tick: int = 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "effect": self.effect,
            "text": self.text,
            "proposer_id": self.proposer_id,
            "status": self.status,
            "votes": dict(self.votes),
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

        self.tick: int = 0
        self.day: int = 0
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
        agent.credits += reward
        return True, "ok", reward

    def action_forage(self, agent: AgentState) -> tuple[bool, str, int]:
        reward = self.params.forage_reward
        agent.credits += reward
        return True, "ok", reward

    def action_recharge(self, agent: AgentState) -> tuple[bool, str, float]:
        cost = self.params.recharge_cost
        if self.has_active_rule("recharge_subsidy"):
            cost = max(1, cost // 2)
        if agent.credits < cost:
            return False, f"need {cost} credits, have {agent.credits}", 0.0
        if agent.energy >= 100:
            # No-op but succeed (idempotent)
            agent.credits -= cost
            return True, "already_full", 0.0
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
        valid_effects = {"ban_stealing", "ubi", "recharge_subsidy", "work_bonus"}
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
            return True, "ok", new_status
        return True, "ok", None

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

    def to_snapshot(self, profile_colors: dict[str, str] | None = None) -> dict:
        pc = profile_colors or {}
        return {
            "tick": self.tick,
            "day": self.day,
            "running": self.running,
            "tick_interval_seconds": self.tick_interval_seconds,
            "places": [p.to_dict() for p in self.places.values()],
            "agents": [
                a.to_dict(pc.get(a.profile, "#888888"))
                for a in self.agents.values()
            ],
            "rules": [r.to_dict() for r in self.rules.values()],
        }

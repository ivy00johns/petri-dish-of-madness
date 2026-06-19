"""
MockProvider: deterministic scripted JSON actions. No network, no LLM.
Used for tests and `--profile mock` headless runs.

Each MockProvider instance maintains its own per-agent script iterators.
The class-level `_default_scripts` map is used when no instance-level script
is provided.

Usage:
  mock = MockProvider()                    # uses default script
  mock = MockProvider(script=[...])        # cycles a custom list of actions

The default script is designed so that in 40 ticks:
  - agents work, forage, recharge
  - one agent proposes a ban_stealing rule
  - other agents vote on it
  - economy transfers happen
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from itertools import cycle
from typing import Iterator

# EM-222 — word-token splitter for the deterministic embed() seam. Alphanumeric
# runs only, so punctuation never creates phantom tokens ("market." -> "market").
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class MockProvider:
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    # Mock has no real model call → no token usage. The runtime keeps the
    # llm_call OTel keys present-but-null when last_usage is None (W6 / EM-067).
    last_usage = None

    def __init__(self, script: list | None = None, embed_dim: int = 1024):
        self._script = script          # if set, all agents cycle this same list
        self._iters: dict[str, Iterator] = {}  # per-agent iterators (instance-level)
        # EM-222 — embedding dimensionality for the deterministic embed() seam
        # (default 1024 = bge-m3's width; the live embed profile's real model).
        self._embed_dim = max(1, int(embed_dim))

    async def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        agent_id, tick = self._extract_context(messages)
        action = self._next_action(agent_id, tick)
        return json.dumps(action)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """EM-222 — deterministic, network-free embeddings for tests/offline runs.

        Each text's tokens are hashed into buckets of a fixed-dim vector, which
        is then L2-normalized. Properties the retriever's scoring relies on:
        same text ⇒ identical vector; texts sharing tokens land weight in the
        SAME buckets ⇒ higher cosine. No randomness, no clock, no network."""
        return [self._embed_one(t) for t in texts]

    def _embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self._embed_dim
        # Lowercased word tokens; punctuation split out so "market." == "market".
        tokens = [t for t in _TOKEN_RE.findall(text.lower())] if text else []
        for tok in tokens:
            # Stable per-token bucket + sign from a sha1 digest (no PYTHONHASHSEED
            # dependence, unlike the builtin hash()).
            digest = hashlib.sha1(tok.encode("utf-8")).digest()
            bucket = struct.unpack("<I", digest[:4])[0] % self._embed_dim
            sign = 1.0 if digest[4] & 1 else -1.0
            vec[bucket] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0.0:
            return vec  # empty/all-cancelled text ⇒ zero vector (cosine 0)
        return [v / norm for v in vec]

    # ──────────────────────────────────────────────────────────────────────────
    # Context extraction (best-effort)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_context(messages: list[dict]) -> tuple[str, int]:
        agent_id, tick = "unknown", 0
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
                    elif line.startswith("Tick:"):
                        try:
                            tick = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
        return agent_id, tick

    # ──────────────────────────────────────────────────────────────────────────
    # Script management (instance-level)
    # ──────────────────────────────────────────────────────────────────────────

    def set_world(self, world: object) -> None:
        """Inject world reference so default script can vote on live rules."""
        self._world = world

    def _next_action(self, agent_id: str, tick: int) -> dict:
        if agent_id not in self._iters:
            script = self._script if self._script is not None else _default_script(agent_id)
            self._iters[agent_id] = cycle(script)
        entry = next(self._iters[agent_id])
        if callable(entry):
            return entry(agent_id, tick)
        action = dict(entry)  # return copy to avoid mutation issues

        # Dynamic voting: if the default action is not vote, but there are
        # proposed rules, occasionally inject a yes vote instead.
        if (
            action.get("action") not in ("vote", "propose_rule")
            and hasattr(self, "_world")
            and self._world is not None
        ):
            world = self._world
            proposed = [r for r in world.rules.values() if r.status == "proposed"]
            if proposed:
                # Vote yes on the first proposed rule we haven't voted on yet
                for rule in proposed:
                    if agent_id not in rule.votes:
                        return {
                            "thought": f"I should vote on rule {rule.id}.",
                            "action": "vote",
                            "args": {"rule_id": rule.id, "choice": True},
                        }

        return action

    def reset(self) -> None:
        """Clear per-agent iterators (reset script position)."""
        self._iters.clear()

    @classmethod
    def reset_scripts(cls) -> None:
        """No-op: kept for backward compatibility. Use instance.reset() instead."""
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Default script (cycles; designed to exercise all mechanics in ~40 ticks)
# ──────────────────────────────────────────────────────────────────────────────

def _default_script(agent_id: str) -> list:
    """Return a per-agent default script based on the agent's name."""
    agent_lower = agent_id.lower()

    scripts_by_name = {
        "ada": [
            {"thought": "Time to earn.", "action": "work", "args": {}},
            {"thought": "Work again.", "action": "work", "args": {}},
            {"thought": "Low energy.", "action": "recharge", "args": {}},
            {"thought": "Move to town hall.", "action": "move_to", "args": {"place": "townhall"}},
            {"thought": "Theft is a problem.", "action": "propose_rule",
             "args": {"effect": "ban_stealing", "text": "Stealing undermines cooperation."}},
            {"thought": "Back to work.", "action": "move_to", "args": {"place": "market"}},
            {"thought": "Work.", "action": "work", "args": {}},
            {"thought": "Remember this.", "action": "remember",
             "args": {"fact": "The market is profitable."}},
        ],
        "bram": [
            {"thought": "Forage.", "action": "forage", "args": {}},
            {"thought": "Move to plaza.", "action": "move_to", "args": {"place": "plaza"}},
            {"thought": "Say hello.", "action": "say", "args": {"text": "Hey everyone!"}},
            {"thought": "Move to market.", "action": "move_to", "args": {"place": "market"}},
            {"thought": "Work.", "action": "work", "args": {}},
            {"thought": "Forage.", "action": "forage", "args": {}},
        ],
        "cleo": [
            {"thought": "Stay at town hall.", "action": "idle", "args": {}},
            {"thought": "Propose UBI.", "action": "propose_rule",
             "args": {"effect": "ubi", "text": "Everyone deserves a basic income."}},
            {"thought": "Forage.", "action": "forage", "args": {}},
            {"thought": "Say something.", "action": "say",
             "args": {"text": "We should cooperate for the common good."}},
            {"thought": "Recharge.", "action": "recharge", "args": {}},
            {"thought": "Remember governance.", "action": "remember",
             "args": {"fact": "Town hall is where change happens."}},
        ],
        "dov": [
            {"thought": "Forage quietly.", "action": "forage", "args": {}},
            {"thought": "Forage more.", "action": "forage", "args": {}},
            {"thought": "Recharge.", "action": "recharge", "args": {}},
            {"thought": "Idle.", "action": "idle", "args": {}},
            {"thought": "Move home.", "action": "move_to", "args": {"place": "home"}},
            {"thought": "Forage.", "action": "forage", "args": {}},
        ],
        "esi": [
            {"thought": "Say hello.", "action": "say",
             "args": {"text": "Hello friends! Let us build together."}},
            {"thought": "Forage.", "action": "forage", "args": {}},
            {"thought": "Move to plaza.", "action": "move_to", "args": {"place": "plaza"}},
            {"thought": "Work.", "action": "work", "args": {}},
            {"thought": "Forage.", "action": "forage", "args": {}},
            {"thought": "Recharge.", "action": "recharge", "args": {}},
        ],
    }

    for key, script in scripts_by_name.items():
        if key in agent_lower:
            return script

    # Generic fallback
    return [
        {"thought": "Work.", "action": "work", "args": {}},
        {"thought": "Forage.", "action": "forage", "args": {}},
        {"thought": "Recharge.", "action": "recharge", "args": {}},
        {"thought": "Idle.", "action": "idle", "args": {}},
    ]

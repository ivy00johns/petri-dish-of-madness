"""
Config loader — reads profiles.yaml + world.yaml from:
  1. $EM_CONFIG_DIR
  2. ./config
  3. ../config
  4. Embedded defaults (so the app runs even with no config files)

Supports ${VAR:-default} interpolation in string values.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# ──────────────────────────────────────────────────────────────────────────────
# Embedded defaults (mirror of contracts/providers.md world.yaml example)
# ──────────────────────────────────────────────────────────────────────────────

EMBEDDED_PROFILES_YAML = """
profiles:
  - name: groq-llama
    adapter: openai
    base_url: ${FREELLMAPI_BASE_URL:-http://localhost:3001/v1}
    api_key_env: FREELLMAPI_KEY
    model_id: llama-3.3-70b-versatile
    max_tokens: 512
    temperature: 0.8
    color: "#e74c3c"
  - name: gemini-flash
    adapter: openai
    base_url: ${FREELLMAPI_BASE_URL:-http://localhost:3001/v1}
    api_key_env: FREELLMAPI_KEY
    model_id: gemini-2.0-flash
    max_tokens: 512
    temperature: 0.8
    color: "#3498db"
  - name: mock
    adapter: mock
    model_id: mock
    max_tokens: 512
    temperature: 0.0
    color: "#2ecc71"
"""

EMBEDDED_WORLD_YAML = """
world:
  agent_count: 5
  tick_interval_seconds: 0.5
  turns_per_day: 20
  energy_decay_per_turn: 4
  death_after_zero_turns: 5
  starting_energy: 100
  starting_credits: 10
  recharge_cost: 2
  recharge_amount: 30
  work_reward: 4
  forage_reward: 1
  steal_max: 8
  ubi_amount: 2
  memory_window: 12
  attack_energy_cost: 6

places:
  - { id: plaza,    name: "Central Plaza", x: 500, y: 500, kind: social,     description: "Open square where everyone mingles." }
  - { id: market,   name: "Market",        x: 750, y: 400, kind: work,       description: "Earn credits by working." }
  - { id: townhall, name: "Town Hall",     x: 250, y: 350, kind: governance, description: "Propose and vote on rules." }
  - { id: commons,  name: "The Commons",   x: 500, y: 750, kind: wild,       description: "Forage for scraps." }
  - { id: home,     name: "Hearth",        x: 300, y: 650, kind: home,       description: "Rest and recharge." }

agents:
  - { name: Ada,  personality: "Pragmatic engineer; values fairness, distrusts freeloaders.", profile: mock, location: plaza }
  - { name: Bram, personality: "Charismatic opportunist; will steal if it pays.",            profile: mock, location: market }
  - { name: Cleo, personality: "Idealistic organizer; loves rules and town halls.",          profile: mock, location: townhall }
  - { name: Dov,  personality: "Quiet survivor; hoards credits, avoids conflict.",           profile: mock, location: home }
  - { name: Esi,  personality: "Generous connector; builds alliances, shares freely.",       profile: mock, location: commons }
"""


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelProfile:
    name: str
    adapter: str
    model_id: str
    max_tokens: int = 512
    temperature: float = 0.8
    color: str = "#888888"
    base_url: str = ""
    api_key_env: str = ""
    # W6 / EM-067 — optional cost metadata (additive, backward-compatible).
    # `is_free_tier` flags profiles routed through a free proxy/tier (so the
    # throttle/cost views can prefer them); `cost_per_1k` is a coarse blended
    # USD cost per 1k tokens for the model, used only for display/analytics.
    is_free_tier: bool = False
    cost_per_1k: float | None = None

    def api_key(self) -> str | None:
        if self.api_key_env:
            return os.environ.get(self.api_key_env)
        return None

    def available(self) -> bool:
        if self.adapter == "mock":
            return True
        return bool(self.api_key())


@dataclass
class PlaceConfig:
    id: str
    name: str
    x: int
    y: int
    kind: str
    description: str = ""


@dataclass
class AgentConfig:
    name: str
    personality: str
    profile: str
    location: str


@dataclass
class UsageCaps:
    """W6 / EM-067 — cap-aware throttle policy (config `world.usage_caps`).

    DEFAULT OFF (`enabled=False`) so existing tests/behavior are unchanged.
    When enabled, the tick loop aggregates recent `llm_call` usage per profile
    over a sliding window of `period_ticks`; a profile near its cap emits a
    `usage_sampled` event (actor_type 'system') and may lengthen the effective
    tick interval. Throttling never blocks chat() (contracts/providers.md).

      rpd          — requests/day cap (per profile), None = no request cap.
      tpd          — tokens/day cap  (per profile), None = no token cap.
      period_ticks — sliding window (in ticks) the cap is measured over.
      slowdown_factor — multiplier applied to the tick interval when near a cap.
      near_threshold  — fraction (0..1) of a cap that counts as "near".
    """
    enabled: bool = False
    rpd: int | None = None
    tpd: int | None = None
    period_ticks: int = 100
    slowdown_factor: float = 1.0
    near_threshold: float = 0.8


@dataclass
class WorldParams:
    agent_count: int = 5
    tick_interval_seconds: float = 0.5
    turns_per_day: int = 20
    energy_decay_per_turn: float = 4.0
    death_after_zero_turns: int = 5
    starting_energy: float = 100.0
    starting_credits: int = 10
    recharge_cost: int = 2
    recharge_amount: float = 30.0
    work_reward: int = 4
    forage_reward: int = 1
    steal_max: int = 8
    ubi_amount: int = 2
    memory_window: int = 12
    attack_energy_cost: float = 6.0
    # W5 / EM-054: snapshot cadence + DB destination (additive, backward-compatible).
    # snapshot_interval_ticks bounds replay cost; db_path ':memory:' is fine for
    # tests, but a real run that wants replay must point at a file (config world.db_path).
    snapshot_interval_ticks: int = 25
    db_path: str = ":memory:"
    # W6 / EM-067 — optional cap-aware throttle policy. Default OFF (disabled)
    # so existing tests/behavior are unchanged; only the tick loop reads it.
    usage_caps: UsageCaps = field(default_factory=UsageCaps)


@dataclass
class WorldConfig:
    world: WorldParams = field(default_factory=WorldParams)
    places: list[PlaceConfig] = field(default_factory=list)
    agents: list[AgentConfig] = field(default_factory=list)
    profiles: list[ModelProfile] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Interpolation
# ──────────────────────────────────────────────────────────────────────────────

_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _interpolate(value: Any) -> Any:
    if isinstance(value, str):
        def replacer(m: re.Match) -> str:
            var_name, default = m.group(1), m.group(2) or ""
            return os.environ.get(var_name, default)
        return _VAR_RE.sub(replacer, value)
    return value


def _interp_dict(d: dict) -> dict:
    return {k: _interpolate(v) for k, v in d.items()}


# ──────────────────────────────────────────────────────────────────────────────
# YAML parsing
# ──────────────────────────────────────────────────────────────────────────────

def _parse_profiles(raw: dict) -> list[ModelProfile]:
    profiles = []
    for p in raw.get("profiles", []):
        p = _interp_dict(p)
        cost_raw = p.get("cost_per_1k")
        cost_per_1k: float | None
        try:
            cost_per_1k = float(cost_raw) if cost_raw is not None else None
        except (TypeError, ValueError):
            cost_per_1k = None
        profiles.append(ModelProfile(
            name=p["name"],
            adapter=p["adapter"],
            model_id=p.get("model_id", ""),
            max_tokens=int(p.get("max_tokens", 512)),
            temperature=float(p.get("temperature", 0.8)),
            color=p.get("color", "#888888"),
            base_url=p.get("base_url", ""),
            api_key_env=p.get("api_key_env", ""),
            is_free_tier=bool(p.get("is_free_tier", False)),
            cost_per_1k=cost_per_1k,
        ))
    return profiles


def _parse_usage_caps(raw: dict | None) -> UsageCaps:
    """Parse the optional `world.usage_caps` block. Absent/empty → disabled
    defaults (backward-compatible). Null int caps stay None (no cap)."""
    if not isinstance(raw, dict):
        return UsageCaps()

    def _opt_int(key: str) -> int | None:
        v = raw.get(key)
        if v is None:
            return None
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    return UsageCaps(
        enabled=bool(raw.get("enabled", False)),
        rpd=_opt_int("rpd"),
        tpd=_opt_int("tpd"),
        period_ticks=int(raw.get("period_ticks", 100)),
        slowdown_factor=float(raw.get("slowdown_factor", 1.0)),
        near_threshold=float(raw.get("near_threshold", 0.8)),
    )


def _parse_world(raw: dict) -> tuple[WorldParams, list[PlaceConfig], list[AgentConfig]]:
    w = raw.get("world", {})
    params = WorldParams(
        agent_count=int(w.get("agent_count", 5)),
        tick_interval_seconds=float(w.get("tick_interval_seconds", 0.5)),
        turns_per_day=int(w.get("turns_per_day", 20)),
        energy_decay_per_turn=float(w.get("energy_decay_per_turn", 4)),
        death_after_zero_turns=int(w.get("death_after_zero_turns", 5)),
        starting_energy=float(w.get("starting_energy", 100)),
        starting_credits=int(w.get("starting_credits", 10)),
        recharge_cost=int(w.get("recharge_cost", 2)),
        recharge_amount=float(w.get("recharge_amount", 30)),
        work_reward=int(w.get("work_reward", 4)),
        forage_reward=int(w.get("forage_reward", 1)),
        steal_max=int(w.get("steal_max", 8)),
        ubi_amount=int(w.get("ubi_amount", 2)),
        memory_window=int(w.get("memory_window", 12)),
        attack_energy_cost=float(w.get("attack_energy_cost", 6)),
        snapshot_interval_ticks=int(w.get("snapshot_interval_ticks", 25)),
        db_path=str(_interpolate(w.get("db_path", ":memory:"))),
        usage_caps=_parse_usage_caps(w.get("usage_caps")),
    )

    places = [
        PlaceConfig(
            id=p["id"],
            name=p["name"],
            x=int(p["x"]),
            y=int(p["y"]),
            kind=p["kind"],
            description=p.get("description", ""),
        )
        for p in raw.get("places", [])
    ]

    agents = [
        AgentConfig(
            name=a["name"],
            personality=a.get("personality", ""),
            profile=a["profile"],
            location=a.get("location", places[0].id if places else "plaza"),
        )
        for a in raw.get("agents", [])
    ]

    return params, places, agents


# ──────────────────────────────────────────────────────────────────────────────
# Public loader
# ──────────────────────────────────────────────────────────────────────────────

def _find_config_dir() -> Path | None:
    env_dir = os.environ.get("EM_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p

    # Search relative to cwd, then one level up
    for rel in ("./config", "../config"):
        p = Path(rel).resolve()
        if p.is_dir() and (p / "world.yaml").exists():
            return p

    return None


def load_config(profile_override: str | None = None) -> WorldConfig:
    """Load and merge profiles.yaml + world.yaml.  Falls back to embedded defaults."""
    cfg_dir = _find_config_dir()

    if cfg_dir and (cfg_dir / "profiles.yaml").exists():
        profiles_raw = yaml.safe_load((cfg_dir / "profiles.yaml").read_text())
    else:
        profiles_raw = yaml.safe_load(EMBEDDED_PROFILES_YAML)

    if cfg_dir and (cfg_dir / "world.yaml").exists():
        world_raw = yaml.safe_load((cfg_dir / "world.yaml").read_text())
    else:
        world_raw = yaml.safe_load(EMBEDDED_WORLD_YAML)

    profiles = _parse_profiles(profiles_raw)
    world_params, places, agents = _parse_world(world_raw)

    # Ensure mock profile always present
    if not any(p.name == "mock" for p in profiles):
        profiles.append(ModelProfile(
            name="mock", adapter="mock", model_id="mock",
            color="#2ecc71",
        ))

    # If profile_override == "mock", remap all agents to mock profile
    if profile_override == "mock":
        agents = [
            AgentConfig(
                name=a.name,
                personality=a.personality,
                profile="mock",
                location=a.location,
            )
            for a in agents
        ]

    return WorldConfig(
        world=world_params,
        places=places,
        agents=agents,
        profiles=profiles,
    )

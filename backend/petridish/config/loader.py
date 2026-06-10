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
    # W11b / EM-083 (platform half) — optional per-provider day caps for the
    # usage_alert channel (providers/usage.py). rpd = requests/day, tpd =
    # tokens/day; None = no cap = no alerts for that metric (today's behavior).
    # ALERTS ONLY — these never throttle or block (EM-067 owns throttling).
    rpd: int | None = None
    tpd: int | None = None

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
class BuildingParams:
    """W7 / EM-061+062 — buildings & the collective-project pipeline
    (config `world.buildings`). Additive, backward-compatible defaults; the world
    engine reads these for build_step size, the abandonment window, arson damage,
    and the operational garden/farm + workshop economy buffs.

      enabled            — master toggle for the buildings subsystem.
      build_step         — progress added per `build_step` action (5 steps = 100%).
      abandon_after_ticks— no fund/build activity while not operational -> abandoned.
      arson_damage       — health removed per `arson`.
      forage_bonus       — extra forage_reward at an operational garden/farm's place.
      work_bonus_pct     — extra work_reward % at an operational workshop's place.
      auto_build_per_round — EM-115: progress % the village work crew adds to every
                          under_construction building each round (zero LLM calls),
                          so funded projects always finish. 0 disables auto-build
                          and restores the pre-EM-115 stall->abandon behavior.
    """
    enabled: bool = True
    build_step: int = 20
    abandon_after_ticks: int = 40
    arson_damage: int = 50
    forage_bonus: int = 1
    work_bonus_pct: int = 50
    auto_build_per_round: int = 10


@dataclass
class SpawnParams:
    """W7 / EM-063 — ad-hoc spawn policy (config `world.spawn`).
    `god` = immediate spawn (default, best for tinkering); `governance` = a spawn
    enqueues an admit_agent proposal, admitted iff the vote passes threshold."""
    mode: str = "god"   # god | governance


@dataclass
class CacheParams:
    """W7 / EM-068 — router decision cache (config `world.cache`). Keyed on
    profile + messages; a hit reuses the prior completion (free-scale win)."""
    enabled: bool = True
    max_entries: int = 512


@dataclass
class AnimalParams:
    """W8 / EM-064 — LLM-driven chaos animals (config `world.animals`).

    Free-scale is the whole point: animals act on a SLOW cadence and only
    SOMETIMES use the LLM. Additive, backward-compatible defaults so W5-W7
    worlds (which lack the block) are unchanged.

      enabled            — master toggle for the animal subsystem.
      act_every_n_ticks  — an animal gets a turn every Nth tick (slower than agents).
      llm_chance         — P(LLM decision) on an acted tick; else a zero-LLM reflex.
      model_profile      — cheapest/fastest free profile for the LLM decision; the
                           runtime falls back to reflex-only if it is unavailable.
    """
    enabled: bool = False
    act_every_n_ticks: int = 3
    llm_chance: float = 0.25
    model_profile: str = ""


@dataclass
class NarratorParams:
    """W11a / EM-094 — Narrator mode (config `world.narrator`).

    DEFAULT OFF (`enabled=False`): zero cost, zero LLM calls. When enabled, the
    tick loop makes at most ONE LLM call per `every_n_ticks` window (off the
    agents' critical path, same pattern as the animal cadence) asking
    `model_profile` for a 2–3 sentence recap of the window, emitted as ONE
    `narrator_summary` event (event-log.md v1.2.0 note 1). A failed/timed-out
    call emits nothing and is never retried.

      enabled       — master toggle (default False = zero calls).
      every_n_ticks — window size; at most one narrator call per window.
      model_profile — the (cheap/free) profile the recap routes to; the loop
                      skips the call entirely when it is unavailable.
    """
    enabled: bool = False
    every_n_ticks: int = 50
    model_profile: str = ""


@dataclass
class CommitmentParams:
    """W11b / EM-079 — commitments (config `world.commitments`). Parsed here so
    user edits to the yaml take effect; the engine reads via its defensive
    _block_get accessors (agents/runtime.py) with IDENTICAL defaults, so an
    absent block behaves exactly the same.

      phantom_after_turns — talk-only turns before a promise lapses as phantom
                            (`commitment_lapsed{reason:"phantom"}`).
      max_active          — active commitments per agent (oldest evicted).
    """
    phantom_after_turns: int = 12
    max_active: int = 5


@dataclass
class ReflectionParams:
    """W11b / EM-080 — reflection/diary (config `world.reflection`). Same
    defensive-accessor contract as CommitmentParams; engine default matches.

      importance_threshold — accumulated importance that triggers an in-prompt
                             reflection request on the agent's NEXT turn
                             (same single response — never a separate call).
    """
    importance_threshold: float = 10.0


@dataclass
class ProcgenParams:
    """W11b / EM-098 — procedural town generation (config `world.procgen`).
    DEFAULT OFF: the hand-authored town stays byte-identical. When enabled, the
    engine (world.apply_procgen) replaces the `places:` list with a seeded
    layout: a central plaza, a ring of n_places using EXISTING kinds only, plus
    housing (per-agent cottages + a communal bunkhouse) on top.

      enabled      — master toggle (default False = hand-authored town).
      seed         — RNG seed for the layout.
      n_places     — town places incl. the plaza (the engine clamps to 4..12;
                     housing is on top of this count).
      kind_weights — weighted picks for the non-guaranteed slots; kept a plain
                     dict (the engine's _block_get reads keys off it directly).
                     Defaults mirror engine/world.py generate_procgen_places.
    """
    enabled: bool = False
    seed: int = 42
    n_places: int = 9
    kind_weights: dict = field(default_factory=lambda: {
        "work": 2.0, "social": 2.0, "governance": 1.0, "wild": 2.0, "home": 1.0,
    })


@dataclass
class AnimalSeed:
    """W8 / EM-064 — a seed critter from the top-level `animals:` list. Spawned at
    world init when `world.animals.enabled`. `personality` is optional flavour fed
    into the animal's role card (the persona's drives stay species-driven)."""
    species: str            # cat | dog
    name: str
    location: str
    personality: str = ""


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
    # W9 / EM-070 — survival pressure: energy below this threshold marks an agent
    # as starving (one-shot `agent_starving` warning + prompt urgency).
    starving_warn_threshold: float = 25.0
    # W9 / EM-071 — pause the tick loop when the last living human agent dies
    # (after emitting + broadcasting `world_extinct`). Animals alone do not keep
    # the run "alive".
    auto_pause_on_extinction: bool = True
    # W5 / EM-054: snapshot cadence + DB destination (additive, backward-compatible).
    # snapshot_interval_ticks bounds replay cost. The DATACLASS default for
    # db_path stays ':memory:' (tests build WorldParams directly), but the
    # shipped config/world.yaml sets a file path (W10 / EM-085) so real runs
    # persist across restarts. Relative yaml paths resolve against the parent
    # of the config/ dir — see _resolve_db_path.
    snapshot_interval_ticks: int = 25
    db_path: str = ":memory:"
    # W6 / EM-067 — optional cap-aware throttle policy. Default OFF (disabled)
    # so existing tests/behavior are unchanged; only the tick loop reads it.
    usage_caps: UsageCaps = field(default_factory=UsageCaps)
    # W7 — buildings/project pipeline, ad-hoc spawn mode, and the decision cache.
    # All additive with backward-compatible defaults so W5/W6 worlds are unchanged.
    buildings: BuildingParams = field(default_factory=BuildingParams)
    spawn: SpawnParams = field(default_factory=SpawnParams)
    cache: CacheParams = field(default_factory=CacheParams)
    # W8 — LLM-driven chaos animals. Additive; default-disabled so a world.yaml
    # without an `animals` block behaves exactly as before.
    animals: AnimalParams = field(default_factory=AnimalParams)
    # W11a / EM-094 — Narrator mode. Additive; default-disabled (zero LLM calls)
    # so a world.yaml without a `narrator` block behaves exactly as before.
    narrator: NarratorParams = field(default_factory=NarratorParams)
    # W11b — engine config blocks (EM-079/080/083/098), parsed so yaml edits
    # take effect. The engine reads all four via defensive accessors (dataclass
    # OR dict OR absent) with defaults identical to these, so behavior without
    # the yaml blocks is unchanged.
    blackout_ticks: int = 10
    commitments: CommitmentParams = field(default_factory=CommitmentParams)
    reflection: ReflectionParams = field(default_factory=ReflectionParams)
    procgen: ProcgenParams = field(default_factory=ProcgenParams)


@dataclass
class WorldConfig:
    world: WorldParams = field(default_factory=WorldParams)
    places: list[PlaceConfig] = field(default_factory=list)
    agents: list[AgentConfig] = field(default_factory=list)
    profiles: list[ModelProfile] = field(default_factory=list)
    # W8 — seed critters (the cat & dog) from the top-level `animals:` list.
    # Empty for W5-W7 configs; the loop spawns these at init when animals.enabled.
    animals: list[AnimalSeed] = field(default_factory=list)


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


def _resolve_db_path(value: Any, config_dir: Path | None) -> str:
    """Resolution rule for world.db_path (W10 / EM-085).

    ':memory:' (and sqlite 'file:' URIs) and ABSOLUTE paths pass through
    untouched. A RELATIVE path resolves against the PARENT of the config/
    directory — i.e. the repo root — so 'data/run.sqlite' lands in ONE
    predictable place regardless of the launch cwd (./dev runs uvicorn from
    backend/, ad-hoc launches often run from the repo root). When no config
    dir exists (embedded defaults / EM_CONFIG_DIR unset and none found), the
    path is returned as-is and resolves against cwd, unchanged from pre-W10.
    """
    path = str(value or ":memory:")
    if path == ":memory:" or path.startswith("file:"):
        return path
    p = Path(path).expanduser()
    if p.is_absolute():
        return str(p)
    if config_dir is not None:
        return str(Path(config_dir).resolve().parent / p)
    return path


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

        def _opt_cap(key: str) -> int | None:
            # W11b / EM-083 — optional rpd/tpd day caps; malformed/absent → None.
            v = p.get(key)
            if v is None:
                return None
            try:
                iv = int(v)
            except (TypeError, ValueError):
                return None
            return iv if iv > 0 else None

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
            rpd=_opt_cap("rpd"),
            tpd=_opt_cap("tpd"),
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


def _parse_buildings(raw: dict | None) -> BuildingParams:
    """Parse the optional `world.buildings` block. Absent/empty -> defaults
    (backward-compatible)."""
    if not isinstance(raw, dict):
        return BuildingParams()
    d = BuildingParams()
    return BuildingParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        build_step=int(raw.get("build_step", d.build_step)),
        abandon_after_ticks=int(raw.get("abandon_after_ticks", d.abandon_after_ticks)),
        arson_damage=int(raw.get("arson_damage", d.arson_damage)),
        forage_bonus=int(raw.get("forage_bonus", d.forage_bonus)),
        work_bonus_pct=int(raw.get("work_bonus_pct", d.work_bonus_pct)),
    )


def _parse_spawn(raw: dict | None) -> SpawnParams:
    """Parse the optional `world.spawn` block. Absent/empty -> god (default)."""
    if not isinstance(raw, dict):
        return SpawnParams()
    mode = str(raw.get("mode", "god"))
    if mode not in ("god", "governance"):
        mode = "god"
    return SpawnParams(mode=mode)


def _parse_cache(raw: dict | None) -> CacheParams:
    """Parse the optional `world.cache` block. Absent/empty -> enabled defaults."""
    if not isinstance(raw, dict):
        return CacheParams()
    d = CacheParams()
    return CacheParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        max_entries=int(raw.get("max_entries", d.max_entries)),
    )


def _parse_animals(raw: dict | None) -> AnimalParams:
    """Parse the optional `world.animals` block. Absent/empty -> disabled defaults
    (backward-compatible). `model_profile` stays "" when unset; the runtime then
    falls back to reflex-only (free-scale guarantee)."""
    if not isinstance(raw, dict):
        return AnimalParams()
    d = AnimalParams()
    return AnimalParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        act_every_n_ticks=max(1, int(raw.get("act_every_n_ticks", d.act_every_n_ticks))),
        llm_chance=float(raw.get("llm_chance", d.llm_chance)),
        model_profile=str(raw.get("model_profile", d.model_profile) or ""),
    )


def _parse_narrator(raw: dict | None) -> NarratorParams:
    """Parse the optional `world.narrator` block (W11a / EM-094). Absent/empty ->
    disabled defaults (backward-compatible, zero LLM calls). `model_profile`
    stays "" when unset; the loop then skips the narrator call entirely."""
    if not isinstance(raw, dict):
        return NarratorParams()
    d = NarratorParams()
    return NarratorParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        every_n_ticks=max(1, int(raw.get("every_n_ticks", d.every_n_ticks))),
        model_profile=str(raw.get("model_profile", d.model_profile) or ""),
    )


def _parse_commitments(raw: dict | None) -> CommitmentParams:
    """Parse the optional `world.commitments` block (W11b / EM-079).
    Absent/empty/malformed values -> engine-matching defaults; the engine
    clamps both to >=1, mirrored here."""
    if not isinstance(raw, dict):
        return CommitmentParams()
    d = CommitmentParams()

    def _pos_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return CommitmentParams(
        phantom_after_turns=_pos_int("phantom_after_turns", d.phantom_after_turns),
        max_active=_pos_int("max_active", d.max_active),
    )


def _parse_reflection(raw: dict | None) -> ReflectionParams:
    """Parse the optional `world.reflection` block (W11b / EM-080).
    Absent/empty/malformed -> engine-matching default threshold."""
    if not isinstance(raw, dict):
        return ReflectionParams()
    d = ReflectionParams()
    try:
        threshold = float(raw.get("importance_threshold", d.importance_threshold))
    except (TypeError, ValueError):
        threshold = d.importance_threshold
    return ReflectionParams(importance_threshold=threshold)


def _parse_procgen(raw: dict | None) -> ProcgenParams:
    """Parse the optional `world.procgen` block (W11b / EM-098). Absent/empty ->
    disabled defaults (the hand-authored town stays). `kind_weights` merges the
    yaml's entries over the engine-matching defaults; non-numeric weights fall
    back per-key (the engine re-validates with the same defaults anyway)."""
    if not isinstance(raw, dict):
        return ProcgenParams()
    d = ProcgenParams()

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    weights = dict(d.kind_weights)
    raw_weights = raw.get("kind_weights")
    if isinstance(raw_weights, dict):
        for kind, default in list(weights.items()):
            try:
                weights[kind] = max(0.0, float(raw_weights.get(kind, default)))
            except (TypeError, ValueError):
                weights[kind] = default

    return ProcgenParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        seed=_int("seed", d.seed),
        n_places=_int("n_places", d.n_places),
        kind_weights=weights,
    )


def _parse_animal_seeds(raw: dict) -> list[AnimalSeed]:
    """Parse the top-level `animals:` seed list (the cat & dog). Absent -> [].
    Each entry needs species + name; location defaults to the first place."""
    out: list[AnimalSeed] = []
    places = raw.get("places", []) or []
    default_loc = places[0]["id"] if places and isinstance(places[0], dict) else "plaza"
    for a in raw.get("animals", []) or []:
        if not isinstance(a, dict):
            continue
        species = str(a.get("species", "")).strip()
        name = str(a.get("name", "")).strip()
        if not species or not name:
            continue
        out.append(AnimalSeed(
            species=species,
            name=name,
            location=str(a.get("location", default_loc) or default_loc),
            personality=str(a.get("personality", "")),
        ))
    return out


def _parse_world(
    raw: dict, config_dir: Path | None = None
) -> tuple[WorldParams, list[PlaceConfig], list[AgentConfig]]:
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
        starving_warn_threshold=float(w.get("starving_warn_threshold", 25)),
        auto_pause_on_extinction=bool(w.get("auto_pause_on_extinction", True)),
        snapshot_interval_ticks=int(w.get("snapshot_interval_ticks", 25)),
        db_path=_resolve_db_path(_interpolate(w.get("db_path", ":memory:")), config_dir),
        usage_caps=_parse_usage_caps(w.get("usage_caps")),
        buildings=_parse_buildings(w.get("buildings")),
        spawn=_parse_spawn(w.get("spawn")),
        cache=_parse_cache(w.get("cache")),
        animals=_parse_animals(w.get("animals")),
        narrator=_parse_narrator(w.get("narrator")),
        blackout_ticks=int(w.get("blackout_ticks", 10)),
        commitments=_parse_commitments(w.get("commitments")),
        reflection=_parse_reflection(w.get("reflection")),
        procgen=_parse_procgen(w.get("procgen")),
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
    world_params, places, agents = _parse_world(world_raw, cfg_dir)
    # W8 — top-level `animals:` seed list (separate from world.animals params).
    animal_seeds = _parse_animal_seeds(world_raw)

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
        animals=animal_seeds,
    )


# ──────────────────────────────────────────────────────────────────────────────
# W11b / EM-092 — persona library (config/personas.yaml)
# ──────────────────────────────────────────────────────────────────────────────

def load_personas() -> list[dict]:
    """Load the persona cards from config/personas.yaml (api.openapi.yaml 1.4.0
    GET /api/personas). Each card: {name, archetype, personality,
    suggested_profile}.

    FAIL-SOFT BY CONTRACT: a missing file, unreadable file, malformed YAML, or
    a wrong top-level shape all return [] — the endpoint must never 500. Cards
    missing a `name` are dropped; the other fields degrade to ''."""
    cfg_dir = _find_config_dir()
    if cfg_dir is None:
        return []
    path = cfg_dir / "personas.yaml"
    if not path.exists():
        return []
    try:
        raw = yaml.safe_load(path.read_text())
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    cards = raw.get("personas")
    if not isinstance(cards, list):
        return []
    out: list[dict] = []
    for c in cards:
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "archetype": str(c.get("archetype") or ""),
            "personality": str(c.get("personality") or ""),
            "suggested_profile": str(c.get("suggested_profile") or ""),
        })
    return out

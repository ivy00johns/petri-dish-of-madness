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
    max_tokens: 1024
    temperature: 0.8
    color: "#e74c3c"
  - name: gemini-flash
    adapter: openai
    base_url: ${FREELLMAPI_BASE_URL:-http://localhost:3001/v1}
    api_key_env: FREELLMAPI_KEY
    model_id: gemini-2.0-flash
    max_tokens: 1024
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
  # EM-175 — target roster size: pads from the persona library when `agents:`
  # lists fewer; never truncates (a longer list always wins). Padded extras
  # join at cadence_tier "supporting"; the hand-listed cast keeps whatever it
  # declares (default protagonist). Citizen-N extras fill if the library runs
  # short. MUST stay in sync with config/world.yaml.
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
  road_build_energy_cost: 8
  # Wave D2 / EM-170 — per-turn LLM budget (seconds). MUST stay in sync with
  # config/world.yaml. 0/absent disables the guard entirely.
  turn_llm_budget_seconds: 0
  # Wave D3 / EM-187 — resume-on-boot: at startup, resume the most recent run
  # whose latest snapshot tick is > 0 as a NEW run row with fork lineage,
  # provided the world-defining config (roster/places/city_seed) still
  # matches; tunable params always adopt the current config. Boot behavior
  # only — it never rides snapshots. MUST stay in sync with
  # config/world.yaml. false = byte-identical pre-D3 boot (always fresh).
  resume_on_boot: true
  # Wave D3 / EM-177 — lane failover with recovery probes. MUST stay in sync
  # with config/world.yaml. enabled:false = byte-identical pre-D3 routing.
  lane_failover:
    enabled: true
    sick_threshold: 3
    probe_every: 4
  # EM-167 — Ollama overflow lane: background/supporting cadence-tier turns
  # spill OFF FreeLLMAPI onto a local Ollama lane as an off-critical-path
  # overflow (the animal-task pattern) — ~40% of background calls move off the
  # free proxy. DEFAULT OFF: routing to Ollama changes behavior, and live-verify
  # pends a running `ollama serve`. A missing/unavailable/sick `ollama` profile
  # self-suppresses, so a turn never hard-fails if Ollama is down (it falls back
  # to the home/EM-205-auto/EM-173-idle path). MUST stay in sync with
  # config/world.yaml. enabled:false = byte-identical pre-EM-167 routing.
  overflow_lane:
    enabled: false
    profile: ollama
    tiers: [background, supporting]
  # Wave D3 / EM-168 — cap-pressure governor: a lane's usage_alert demotes its
  # agents one cadence tier until the alert tracker's UTC-day rollover. MUST
  # stay in sync with config/world.yaml. OFF since the 2026-06-12 EM-198
  # error-bounce mandate — cap pressure bounces calls to other lanes instead
  # of muting the cast; alerts stay alert-only.
  cap_governor:
    enabled: false
  # Wave E / EM-113 — relationship-depth thresholds (reflex friend/feud
  # transitions + the partner declaration gate). MUST stay in sync with
  # config/world.yaml. No `enabled` flag by design: thresholds only fire on
  # NEW trust mutations, so pre-E snapshots restore byte-identical.
  relationships:
    friend_trust: 30
    friend_interactions: 5
    feud_trust: -40
    partner_trust_threshold: 40
  # EM-229 — three-needs psychology: decaying `knowledge` + `influence` drives
  # ride alongside `energy` on every agent. They decay every turn at these small
  # non-zero rates but NEVER kill (only energy does) — a need below its salience
  # threshold only adds a conditional prompt nudge (so a full-needs agent's
  # prompt is byte-identical to pre-EM-229). Replenished by learning (knowledge)
  # and governance/social wins (influence). MUST stay in sync with
  # config/world.yaml. Absent ⇒ these exact defaults (no behavior change).
  needs:
    knowledge_decay_per_turn: 0.5
    influence_decay_per_turn: 0.4
    knowledge_salience_threshold: 40
    influence_salience_threshold: 40
  # EM-233 — memory consolidation ("sleep") + soul entries. At each round
  # boundary an agent whose `beliefs` count exceeds consolidate_at has its OLDEST
  # beliefs deterministically rolled into ONE digest line (a structured rollup,
  # NO LLM), keeping consolidate_keep_recent most-recent beliefs verbatim; emits a
  # `memory` event. `soul` is a tiny immutable list of identity anchors (≤ soul_cap,
  # seeded from a persona at spawn if configured) injected into every prompt and
  # NEVER summarized. Soulless agents + a small belief list are byte-identical to
  # pre-EM-233. MUST stay in sync with config/world.yaml. Absent ⇒ these exact
  # defaults (no behavior change).
  memory:
    consolidate_at: 20
    consolidate_keep_recent: 8
    soul_cap: 3
  # EM-227 — skills & emergent professions. The skill LIBRARY: each named skill
  # GATES a list of high-value actions on a min level, so specialists emerge
  # (only a builder proposes/builds; only an artist paints; only an orator
  # legislates). Skills are GAINED by doing (xp_per_use per successful gated
  # action; xp_per_level per level, capped at max_level) and by teaching (EM-228).
  # SURVIVAL verbs (move/work/forage/say/whisper/recharge/idle/remember) are NEVER
  # gated. `archetypes` seeds a deterministic starting spread per persona so
  # identical agents diverge. An EMPTY library gates NOTHING (byte-identical
  # pre-EM-227 + the em161 golden). MUST stay in sync with config/world.yaml.
  skills:
    xp_per_use: 10
    xp_per_level: 30
    max_level: 5
    library:
      building:
        gates: [propose_project, build_step]
        min_level: 1
      art:
        gates: [create_image]
        min_level: 1
      rhetoric:
        gates: [propose_rule]
        min_level: 1
    archetypes:
      builder: {building: 2}
      artist: {art: 2}
      orator: {rhetoric: 2}
      farmer: {building: 1}
      healer: {art: 1}
  # EM-231 — cooperation-gated tools. A co-located pair forms a HANDSHAKE
  # (offer_cooperation → accept_cooperation); the gated `co_build` action then
  # advances a building by co_build_bonus_step (set ABOVE buildings.build_step
  # so a joint build outpaces solo work — the cooperation payoff). Purely
  # additive: a world that never forms a handshake has no cooperation state
  # (golden + snapshot byte-identical). MUST stay in sync with config/world.yaml.
  cooperation:
    co_build_bonus_step: 35
  # EM-232 — peer-judged credit economy / Victory Arch. A periodic
  # pitch -> peer-judge -> award cycle: agents pitch_contribution(text) to park a
  # pitch; every `every_n_ticks` ticks the parked pitches are ranked by a
  # DETERMINISTIC contribution score (buildings funded, skills taught, trades
  # settled, projects built; tie-broken by id — no random), and the top_n pitchers
  # each win `award` credits + a renown bump + an influence replenish (EM-229). An
  # `arch_award` event fires per winner; the queue clears. DEFAULT-OFF here
  # (every_n_ticks 0 = no cycle, no pitch line) so this embedded mirror stays
  # byte-identical to pre-EM-232 — the live config/world.yaml sets a positive
  # cadence. MUST stay in sync with config/world.yaml.
  victory_arch:
    every_n_ticks: 0
    award: 50
    top_n: 1
    reputation_bonus: 5
    influence_replenish: 25
  # EM-235 — boost queue. Agents spend credits (buy_turn) for EXTRA scheduled
  # turns/airtime (EW's ComputeCredits) — they buy influence over the shared
  # timeline (the north-star: MORE turns/LLM calls). cost credits are deducted per
  # buy (rejected if too poor); the scheduler grants the agent an extra slot,
  # bounded by max_per_round per round. DEFAULT-OFF here (cost 0 = every buy
  # rejected, no buy_turn line, scheduler untouched) so this embedded mirror stays
  # byte-identical to pre-EM-235 — the live config/world.yaml sets a positive cost.
  # MUST stay in sync with config/world.yaml.
  boost:
    cost: 0
    max_per_round: 2
  # EM-236 — living constitution. Agents amend an ARTICLED foundational document
  # via propose_rule(effect=amend_constitution, op=add|edit|remove); it ratifies
  # on a 70% supermajority (the demolish bar) and replenishes the proposer's
  # influence need. The constitution is empty until an amendment ratifies, so this
  # block only TUNES the bar + reward — an un-amended world is byte-identical to
  # pre-EM-236. MUST stay in sync with config/world.yaml.
  constitution:
    ratify_threshold: 0.7
    influence_replenish: 15
  # EM-203 — governance renewal cooldown. When > 0, re-proposing an effect
  # identical to an ACTIVE rule whose last activation is within the window is
  # rejected as 'already active (settled)' so agents legislate something NEW
  # (run-663: work_bonus re-passed 35×, ubi 27×, recharge_subsidy 19×). DEFAULT 0
  # here = no cooldown = byte-identical to pre-EM-203 (the W11b renewal ritual is
  # untouched); the live config/world.yaml sets a positive window. MUST stay in
  # sync with config/world.yaml.
  governance:
    renewal_cooldown_ticks: 0
  # EM-234 — universalization prompting (GovSim scaffold). When enabled, every
  # agent's turn gets a "before acting on the commons, ask: what if EVERY agent
  # did this?" block (zero extra LLM calls — rides the turn). DEFAULT OFF here so
  # this embedded mirror stays byte-identical to pre-EM-234 (the live
  # config/world.yaml flips enabled:true). MUST stay in sync with config/world.yaml.
  universalization:
    enabled: false
  # EM-224 — PIANO coherence for multi-action turns. When enabled, a
  # deterministic zero-LLM bottleneck reconciles a turn's actions[] against the
  # intent of its first speech act (catches "Sure, friend!" then steal). DEFAULT
  # OFF here so this embedded mirror stays byte-identical to pre-EM-224 (no
  # prompt block, no agent/world state). MUST stay in sync with config/world.yaml.
  #   strategy: annotate  → keep both, stamp the contradiction (hypocrisy legible)
  #             drop       → suppress the contradicting act (the speech wins)
  coherence:
    enabled: false
    strategy: annotate
  # Wave E / EM-114 — lightweight children: once per round boundary, mutual
  # partners (are_partners) co-located at a home may have a child — a NEW
  # agent at background tier, only into vacancies under max_population AND
  # home-bed capacity (the free-scale law: births never grow the call
  # budget). Both parents pay birth_cost_credits and need energy >= 30; the
  # chance gate is seeded from (city_seed, tick, pair). MUST stay in sync
  # with config/world.yaml. enabled:false = no birth checks (byte-identical
  # pre-E behavior).
  children:
    enabled: true
    max_population: 25
    birth_cost_credits: 6
    birth_chance: 0.25
    pair_cooldown_ticks: 600
  # EM-126 — generational depth: life stages (child→adult→elder, aged once per
  # round) + inheritance of credits (and optionally relationships) to an EM-114
  # lineage heir on death. DEFAULT OFF here so this embedded mirror stays byte-
  # identical to pre-EM-126 (no aging, no estate, EM-114 children untouched). The
  # live config/world.yaml flips enabled:true. MUST stay in sync with
  # config/world.yaml. Thresholds are in ROUNDS (= age_ticks).
  generations:
    enabled: false
    child_until: 6
    elder_after: 60
    inherit_credits: true
    inherit_relationships: false
  # Wave E / EM-120 — factions, feuds & reputation: at each round boundary
  # (after the birth check) connected components over MUTUAL warm edges
  # (both directions ally|friend|partner|family AND both trusts >=
  # faction_trust) of size >= faction_min_size form factions. Derived state,
  # zero LLM calls; events fire on diffs only. MUST stay in sync with
  # config/world.yaml. enabled:false = no recompute, no factions/reputation
  # snapshot keys (byte-identical pre-E behavior).
  factions:
    enabled: true
    faction_trust: 25
    faction_min_size: 3
  # Wave E / EM-184 — world-scale god miracles: timed world modifiers cast
  # from the god console (POST /api/god/intervene with NO agent_id).
  # send_rain buffs forage by rain_forage_bonus for rain_days in-world days;
  # bountiful_harvest multiplies energy decay by harvest_decay_factor for
  # harvest_days; calm_spirits is one-time (mood 'hopeful' + a trust nudge
  # through the B1 reflex seam). Re-casting an active kind REFRESHES its
  # until_tick (never stacks). MUST stay in sync with config/world.yaml.
  # enabled:false = world kinds rejected; targeted bless/grant untouched
  # (byte-identical pre-E behavior).
  miracles:
    enabled: true
    rain_forage_bonus: 2
    rain_days: 2
    harvest_decay_factor: 0.5
    harvest_days: 2
    calm_trust_bonus: 3
  # Wave D2 / EM-159+160 — background-tier salience gating + spontaneity floor.
  # MUST stay in sync with config/world.yaml. Agent entries may also carry an
  # optional `cadence_tier: protagonist|supporting|background` (EM-158).
  cadence:
    spontaneity_chance: 0.15
    reflex_streak_limit: 8
  # EM-222 — relevance-scored long-term memory retrieval (protagonist +
  # supporting tiers; background keeps blind recency). MUST stay in sync with
  # config/world.yaml. enabled:false = byte-identical pre-EM-222 (blind
  # recency for every tier).
  memory_retrieval:
    enabled: true
    embed_model: bge-m3
    top_k: 12
    recent_tail: 6
    candidate_limit: 400
    w_relevance: 0.5
    w_importance: 0.3
    w_recency: 0.2
    recency_halflife_ticks: 200
  # W15 / EM-155 — deterministic seed for the generated 3D city ring.
  # MUST stay in sync with config/world.yaml.
  city_seed: 1337
  # EM-246 (S4) — the run-start city profile. Seeds the initial CityGraph via
  # citygraph.template() (seed reuses city_seed). Absent/grid ⇒ byte-identical
  # pre-EM-246 (classic_grid). MUST stay in sync with config/world.yaml.
  city:
    template: grid          # grid | greenfield | village (pentagon/radial/ring → grid until EM-245)
    size: 5
    density: medium
    car_policy: cars

places:
  # Wave D1.5 / contracts/wave-d1.5.md — the city grid (~15 places over the
  # existing five kinds). MUST stay in sync with config/world.yaml's places
  # block. The five original ids (plaza/market/townhall/commons/home) survive
  # with their kinds so old snapshots and agent locations stay valid;
  # `district` is the one additive optional key
  # (core/market/residential/civic/farm). Coordinates sit on the 5x5
  # city-block centers (106/303/500/697/894 on each axis).
  # core — the plaza blocks at the heart of the grid
  - { id: plaza,           name: "Central Plaza",     x: 500, y: 500, kind: social,     district: core,        description: "Open square at the heart of the grid where everyone mingles." }
  - { id: well,            name: "Fountain Court",    x: 500, y: 303, kind: social,     district: core,        description: "Plaza fountain where the day's gossip circles with the spray." }
  # market — the working east blocks
  - { id: market,          name: "Market Hall",       x: 697, y: 303, kind: work,       district: market,      description: "Earn credits by working." }
  - { id: forge,           name: "The Steelworks",    x: 894, y: 303, kind: work,       district: market,      description: "Sparks and rolling steel; the mill pays good coin for steady hands." }
  - { id: workshop,        name: "Tinker's Workshop", x: 894, y: 500, kind: work,       district: market,      description: "Cluttered benches of half-finished marvels; there is always paid work." }
  # civic — the records corner, north-west
  - { id: townhall,        name: "City Hall",         x: 106, y: 106, kind: governance, district: civic,       description: "Propose and vote on rules." }
  - { id: archive,         name: "The Records Office", x: 303, y: 106, kind: governance, district: civic,      description: "Filing rows of city ledgers, old permits, and older grievances." }
  # EM-240 — the town jail (kind: civic). Enforcers march detained / convicted
  # lawbreakers here; a jailed agent may only talk and think until released.
  - { id: jail,            name: "The Lockup",        x: 106, y: 303, kind: civic,      district: civic,       description: "A spare stone cell where the town holds its lawbreakers." }
  # residential — lamplit blocks to the south-west
  - { id: home,            name: "Hearth House",      x: 106, y: 697, kind: home,       district: residential, description: "Rest and recharge." }
  - { id: rosehip_cottage, name: "Rosehip Walk-up",   x: 106, y: 894, kind: home,       district: residential, description: "A snug walk-up over a flower shop. Rest and recharge." }
  - { id: mossy_row,       name: "Mossy Row Flats",   x: 303, y: 894, kind: home,       district: residential, description: "A crooked row of ivy-clad flats. Rest and recharge." }
  - { id: lantern_loft,    name: "Lantern Lofts",     x: 303, y: 697, kind: home,       district: residential, description: "Top-floor lofts above the avenue, warm with lamplight. Rest and recharge." }
  # farm — the greenbelt park blocks of the south-east
  - { id: commons,         name: "The Commons Park",  x: 697, y: 697, kind: wild,       district: farm,        description: "Forage for scraps." }
  - { id: willow_pond,     name: "Willow Pond Park",  x: 697, y: 894, kind: wild,       district: farm,        description: "Still water under trailing willows; ducks, reeds, and easy foraging." }
  - { id: orchard,         name: "Orchard Green",     x: 894, y: 894, kind: wild,       district: farm,        description: "Crab apples and brambles in a pocket park; sweet pickings in season." }
  - { id: farmstead,       name: "Sunfall Depot",     x: 894, y: 697, kind: work,       district: farm,        description: "Loading docks and pallet rows; honest work from dawn to dusk." }

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
    # 1024 (was 512): the proxy can reroute any lane onto a REASONING model whose
    # chain-of-thought eats the budget before the JSON appears, so a 512 default
    # truncates and forces a retry. The live config/profiles.yaml already pins
    # 1024 per lane; this default keeps a profile that OMITS max_tokens on the same
    # truncation-resistant floor (EM-135 still boosts to 4096 on a flagged lane).
    max_tokens: int = 1024
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
    # Wave C / EM-147 — optional district tag (core|market|residential|civic|
    # farm in the hand-authored town). ADDITIVE: default None so pre-Wave-C
    # configs parse unchanged. Kinds stay the existing five
    # (social/work/governance/home/wild) — district only groups them.
    district: str | None = None
    # EM-123 — optional neighborhood/zone overrides (both default None ⇒
    # neighborhood == district, zone derived from district/kind). Authors only
    # set these to split a district into named neighborhoods or to override one
    # place's zoning inside a mixed district. ADDITIVE: pre-EM-123 configs parse
    # unchanged.
    neighborhood_id: str | None = None
    zone_kind: str | None = None


@dataclass
class AgentConfig:
    name: str
    personality: str
    profile: str
    location: str
    # Wave D2 / EM-158 — optional scheduler cadence tier for the seed agent
    # (protagonist | supporting | background). ADDITIVE: default protagonist,
    # so pre-D2 configs parse and behave identically.
    cadence_tier: str = "protagonist"


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
      zoo_capacity       — Wave H3 / EM-208: how many animals a zoo (building
                          kind=="zoo") auto-stocks AT its place when it opens
                          (capped by animals.max_population). 0 = stock nothing.
    """
    enabled: bool = True
    build_step: int = 20
    abandon_after_ticks: int = 40
    arson_damage: int = 50
    forage_bonus: int = 1
    work_bonus_pct: int = 50
    auto_build_per_round: int = 10
    zoo_capacity: int = 5


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
      max_population     — EM-143: cap on LIVING animals (0 = unlimited; the
                           backward-compatible default). world.spawn_animal raises
                           ValueError once living animals >= this, surfaced as 409.
      ambient_spawn_every — Wave H2 / EM-207: every Nth tick the menagerie may grow
                           on its own — ONE random catalog critter at a random place,
                           only while living animals < max_population (0 = OFF, the
                           backward-compatible default; ambient spawning disabled).
      ambient_spawn_chance — Wave H2 / EM-207: P(an ambient spawn lands) on an
                           ambient-aligned tick, rolled by a DETERMINISTIC seeded
                           hash (replay-safe; no wall-clock). 0.0 = never.
      pet_energy_decay   — Wave H4 / EM-209: energy an OWNED pet loses each of its
                           own turns (gentle, so a pet lasts a while). At energy 0 an
                           owned pet dies and its owner writes a grief diary entry.
                           Unowned animals never decline. Default 2.
      pet_feed_amount    — Wave H4 / EM-209: energy restored when a co-located agent
                           feeds an owned pet (feed_pet action; no credits move).
                           Default 25.
    """
    enabled: bool = False
    act_every_n_ticks: int = 3
    llm_chance: float = 0.25
    model_profile: str = ""
    max_population: int = 0
    ambient_spawn_every: int = 0
    ambient_spawn_chance: float = 0.0
    pet_energy_decay: int = 2
    pet_feed_amount: int = 25


@dataclass
class PropsParams:
    """Wave K / EM-218 — placeable PROPS (decorations/furniture/nature) the agents
    and god can add, move, and remove (config `world.props`). Mirrors the
    animals.max_population shape exactly: a SINGLE population cap that protects
    free-scale — more props = more chronicle texture, never more LLM calls.

      max_population — cap on tracked props (the engine rejects place_prop over
                       this, with guidance; 0 = unlimited). Default 48: a
                       populated town, not overwhelming; tunable UP from a live
                       25-agent run (per the brainstorm's resolved decision 1).
    """
    max_population: int = 48


@dataclass
class ImageGenParams:
    """Wave I / EM-210 — image generation (config `world.image_gen`, The Atelier).
    Additive with engine-matching defaults: the engine reads both via defensive
    _block_get accessors (World._image_gen_max_gallery + the loop's semaphore),
    so an absent `image_gen` block behaves exactly as these values.

      enabled        — master toggle (default True). False ⇒ create_image is
                       dropped from the menu and rejected at resolution (no PNG
                       fetch is parked), so the Atelier makes ZERO image-API
                       calls — the credit-safe kill switch. post_image /
                       promote_image (free, no network) stay available.
      max_concurrent — in-flight PNG fetches; the loop SKIPS a fetch above this
                       (skip-under-load, never an unbounded queue). Default 2.
      max_gallery    — newest images retained in world.gallery (pop-oldest on
                       append, mirror the billboard cap). Default 30.
      max_decals_per_district
                     — EM-298: agent-painted facade decals retained PER DISTRICT
                       (insertion-order LRU eviction, browser-perf bound). Default 6.
      facades_enabled
                     — EM-298: surface paint_surface on the agent action MENU
                       (default False ⇒ the em161 protagonist prompt stays
                       byte-identical; the world action + snapshot round-trip are
                       always available regardless). Flip true to let agents paint.
    """
    enabled: bool = True
    max_concurrent: int = 2
    max_gallery: int = 30
    max_decals_per_district: int = 6
    facades_enabled: bool = False


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
class PlanningParams:
    """Wave L / EM-223 — recursive+reactive planning (config `world.planning`).

    DEFAULT OFF (`enabled=False`): byte-identical to pre-EM-223 — no plan block,
    no plan invite, `plan_revision` ignored, `AgentState.plan` never set, so the
    protagonist prompt golden file and snapshot key set are unchanged. Flip on
    for the live tuning run the spike calls for. Engine reads via defensive
    accessors with IDENTICAL defaults, so an absent block behaves the same.

      enabled     — master toggle (default False = zero behavioral change).
      max_steps   — soft prompt hint for steps-per-plan (the spike's 3–5); the
                    hard schema cap is engine PLAN_MAX_STEPS (8).
      reflex_bias — plan-aware reflex bias (unit 4): bias a background agent's
                    deterministic reflex toward its current step's place. Only
                    re-orders already-valid reflex actions; zero extra calls.
    """
    enabled: bool = False
    max_steps: int = 5
    reflex_bias: bool = True


@dataclass
class UniversalizationParams:
    """EM-234 — Universalization prompting (config `world.universalization`).

    The GovSim "universalization" scaffold — before acting on the commons, ask:
    what if EVERY agent did this? — is a single ALWAYS-ON prompt block injected
    into every agent's turn context. Because it changes the prompt for ALL agents
    unconditionally, it would break the em161 lawful-citizen golden, so it is

    DEFAULT OFF (`enabled=False`): byte-identical to pre-EM-234 — no block at all,
    no per-agent state, so the protagonist prompt golden file and the snapshot key
    set are unchanged (EM-234 carries NO AgentState/World state — it is a pure
    config-read prompt block). The engine reads via the defensive
    `_universalization_enabled` accessor with the IDENTICAL default, so an absent
    block behaves the same (config-absent = OFF). Flip `enabled: true` for the
    live runs to get the cheap cooperation lift (zero extra LLM calls — it rides
    the existing turn).

      enabled — master toggle (default False = zero behavioral change).
    """
    enabled: bool = False


@dataclass
class CoherenceParams:
    """EM-224 — PIANO coherence for multi-action turns (config `world.coherence`).

    A deterministic, zero-LLM coherence bottleneck that runs AFTER the turn's
    `actions[]` are flattened (EM-199 `_normalize_steps`) and BEFORE they apply:
    it derives a single intent from the turn's first speech act, then reconciles
    later hostile/helpful steps against it — catching "Sure, friend!" then steal
    from the same agent. Takes ONLY PIANO's coherence idea (NOT its
    parallelize-to-cut-latency motive — we want MORE calls). Zero extra LLM calls.

    DEFAULT OFF (`enabled=False`): byte-identical to pre-EM-224. EM-224 adds NO
    prompt block (so the em161 golden is unchanged either way) and NO
    AgentState/World state (so EM-155 snapshots are unchanged) — it is a pure
    per-turn structural pass. The engine reads via the defensive
    `_coherence_enabled` accessor with the IDENTICAL default, so an absent block
    behaves the same (config-absent = OFF). Flip `enabled: true` for live runs.

      enabled  — master toggle (default False = zero behavioral change).
      strategy — how a flagged contradiction is handled:
                 'annotate' (default) keeps both steps but stamps the
                 contradicting action's event with a coherence note (the
                 hypocrisy becomes legible, the world still mutates);
                 'drop' suppresses the contradicting step (the speech wins) and
                 emits a coherence_note in its place. ('reorder' is reserved →
                 falls back to 'annotate'.)
    """
    enabled: bool = False
    strategy: str = "annotate"


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
class LaneFailoverParams:
    """Wave D3 / EM-177 — lane failover with recovery probes (config
    `world.lane_failover`). The router (providers/router.py) reads this block
    via its defensive _lf_value accessor with IDENTICAL defaults, so an absent
    block behaves exactly like these values. `enabled: false` restores the
    byte-identical pre-D3 routing (effective_profile always returns the home
    lane, zero lane_detour events).

      enabled        — master toggle (default ON).
      sick_threshold — timed_out entries in the EM-135 6-window that mark a
                       lane SICK (mock lanes are never sick; provider_error
                       turns never count).
      probe_every    — every Nth would-be-detour goes through the home lane
                       instead (a recovery probe), so a clean outcome ages the
                       demerits out of the window. Counters only — no clocks.
    """
    enabled: bool = True
    sick_threshold: int = 3
    probe_every: int = 4


@dataclass
class OverflowLaneParams:
    """EM-167 — Ollama overflow lane (config `world.overflow_lane`). Routes
    background/supporting cadence-tier turns OFF FreeLLMAPI onto a local Ollama
    lane as an off-critical-path overflow (the animal-task pattern): a slow,
    non-survival lane that, if it stalls or is unreachable, falls back to the
    existing routing WITHOUT ever hard-failing a turn. The router
    (providers/router.py) reads this block via its defensive _ol_value accessor
    with IDENTICAL defaults, so an absent block behaves exactly like these
    values (byte-identical pre-EM-167 routing).

      enabled — master toggle (default OFF). Routing to Ollama CHANGES behavior
                for existing worlds, so `false`/absent ⇒ effective_profile never
                considers the overflow path (no new spans, no detours). Flip
                `true` once a real `ollama serve` is reachable. Live-verify of
                the overflow lane pends a running Ollama.
      profile — the overflow target profile name (must exist in profiles.yaml).
                Default `ollama`; a missing / unavailable / sick target
                self-suppresses (the turn falls back to home/failover routing).
      tiers   — the cadence tiers whose turns spill to the overflow lane
                (protagonist NEVER overflows — its traffic stays on the pinned
                lane). Default background + supporting (~40% of background
                calls move off FreeLLMAPI).
    """
    enabled: bool = False
    profile: str = "ollama"
    tiers: tuple[str, ...] = ("background", "supporting")


@dataclass(frozen=True)
class LaneOrderEntry:
    """One entry in the adaptive-routing sorting list (spec §3.3
    `config/lanes.yaml` `order:`). `source` + `model` glob select which lanes
    the entry ranks; `model: "*"` sweeps every remaining lane of that source.
    `free: false` marks a PAID entry (excluded unless allow_paid). `out_hint`/
    `ctx_hint`/`tags` are optional lane-shaping hints (absent in the shipped
    order; used by P1 tests + the P2 discovery merge)."""
    source: str
    model: str = "*"
    free: bool = True
    out_hint: int | None = None
    ctx_hint: int | None = None
    tags: tuple[str, ...] = ()


@dataclass
class AdaptiveRoutingParams:
    """Adaptive Lane Routing — the custom sorting list + bounce loop (spec
    2026-07-07, config `config/lanes.yaml` `adaptive_routing:` block). The
    router (providers/router.py) reads this block via its defensive _ar_value
    accessor with IDENTICAL defaults, so an ABSENT block (no lanes.yaml) behaves
    exactly like these values — `enabled: false` ⇒ the byte-identical pre-spec
    routing (pinned lane → EM-205 `auto` backup), the determinism contract.

      enabled              — master toggle (default OFF ⇒ byte-identical). When
                             ON, a pinned lane's failure walks the registry in
                             priority order instead of the single `auto` retry.
      max_attempts         — curated healthy lanes tried per turn before the
                             runtime's EM-173 idle fallback. Clamped >= 1.
      per_attempt_timeout_s— per-lane wall-clock bound (no 86s doomed cascades).
      allow_paid           — opt-in for `free: false` lanes ($0-first default).
      order                — the priority order (top-to-bottom = ascending),
                             a tuple of LaneOrderEntry (spec §3.3).
    """
    enabled: bool = False
    max_attempts: int = 3
    per_attempt_timeout_s: float = 12.0
    allow_paid: bool = False
    order: tuple[LaneOrderEntry, ...] = ()


@dataclass
class CapGovernorParams:
    """Wave D3 / EM-168 — cap-pressure governor (config `world.cap_governor`).
    When a usage_alert fires for a lane (UsageAlertTracker ≥70% of its rpd/tpd
    day cap), every agent ASSIGNED to that lane is demoted ONE cadence tier
    (protagonist→supporting→background; background stays) with the prior tier
    recorded on AgentState.demoted_from; demoted agents are restored at the
    tracker's UTC-day rollover. The engine reads the block via its defensive
    _block_get accessor with an IDENTICAL default, so an absent block behaves
    exactly like these values.

      enabled — master toggle (default OFF since the 2026-06-12 EM-198
                error-bounce mandate: cap pressure routes to other lanes
                instead of muting the cast). `false` ⇒ usage alerts stay
                alert-only: byte-identical pre-D3 behavior (no demotions, no
                cap_pressure events, no new snapshot keys).
    """
    enabled: bool = False


@dataclass
class DistrictGrowthParams:
    """EM-123 — zoned districts that DEEPEN as megaprojects complete (config
    `world.district_growth`). A completed collective building advances its
    district's growth progress; every `completions_per_tier` completions raise
    the district one `tier` (capped at `max_tier`), emitting a `district_grew`
    event. The frontend reads the tier (via the place's neighborhood) and adds
    deterministic street life — NEVER filler buildings (EM-174). The engine
    reads the block via its defensive _block_get accessor with IDENTICAL
    defaults, so an absent block behaves exactly like these values.

      enabled              — master toggle (default ON). `false` ⇒ completions
                             never grow a district: byte-identical pre-EM-123
                             behavior (all districts stay tier 1, no new events,
                             no new snapshot keys).
      completions_per_tier — megaprojects that must finish in a district to
                             raise it one tier (default 2). Clamped >= 1.
      max_tier             — the maturity ceiling (default 4). Clamped >= 1.
    """
    enabled: bool = True
    completions_per_tier: int = 2
    max_tier: int = 4


@dataclass
class CityProfileParams:
    """EM-246 (S4) — the run-start city profile (config `world.city`). Seeds the
    initial CityGraph via citygraph.template(). Absent/empty ⇒ grid (byte-identical
    pre-EM-246). seed reuses world.city_seed."""
    template: str = "grid"      # grid|greenfield|village (pentagon|radial|ring → grid until EM-245)
    size: int = 5               # RESERVED extent hint — parsed but NOT yet honored (follow-up)
    density: str = "medium"     # low|medium|high — village sparsity
    car_policy: str = "cars"    # starting global graph car policy (S3a can change it)


@dataclass
class RelationshipParams:
    """Wave E / EM-113 — relationship-depth thresholds (config
    `world.relationships`). The engine reads this block via its defensive
    _rel_param accessor with IDENTICAL defaults, so an absent block behaves
    exactly like these values. NO `enabled` flag by design: the thresholds
    only fire on NEW trust mutations, so pre-E snapshots restore
    byte-identical without one.

      friend_trust            — neutral|ally flips to friend at trust >= this
                                (AND interactions >= friend_interactions).
      friend_interactions     — minimum interaction count for the friend flip.
      feud_trust              — rival|enemy hardens into feud at trust <= this.
      partner_trust_threshold — set_relationship `partner` requires the
                                declarer's trust toward the target >= this;
                                are_partners() requires BOTH directions >= it.
    """
    friend_trust: int = 30
    friend_interactions: int = 5
    feud_trust: int = -40
    partner_trust_threshold: int = 40


@dataclass
class CrimeParams:
    """EM-240 — Crime & Justice tunables (config `world.crime`). The engine reads
    this block via its defensive `_crime_param` accessor with IDENTICAL defaults
    (the RelationshipParams/_rel_param convention), so a world.yaml WITHOUT the
    `crime` block behaves exactly like these values — i.e. byte-identical to
    pre-EM-240. NO `enabled` flag by design: crime/justice verbs only fire on a
    deliberate agent turn, so pre-EM-240 snapshots restore unchanged without one.
    """
    wanted_threshold: int = 40
    detain_threshold: int = 60
    notoriety_decay: int = 2
    notoriety_per_extra_witness: int = 3
    rap_sheet_cap: int = 10
    heist_max: int = 30
    heist_min_target_credits: int = 15
    extort_max: int = 15
    vandalize_blackout_ticks: int = 8
    vandalize_notoriety: int = 10
    heist_notoriety: int = 18
    extort_notoriety: int = 12
    # EM-237 — harm-surface finishers (intimidate / deceive). Two reflex verbs
    # atop the EM-240 crime path; their witnessed-notoriety bases live here so an
    # absent `crime` block (city25 / the embedded mirror) still scores them at
    # these exact defaults via _crime_param (config-absent = no-op). intimidate
    # coerces a fraction of the mark's purse (lighter take than extort_max=15,
    # heavier fear); deceive moves no credits (it plants a lie + sours trust).
    intimidate_notoriety: int = 14
    deceive_notoriety: int = 8
    intimidate_take_fraction: float = 0.25
    intimidate_max: int = 10
    steal_notoriety: int = 6
    arson_notoriety: int = 22
    bribe_efficacy: float = 0.75
    bribe_notoriety: int = 14
    launder_cut: float = 0.3
    launder_notoriety_reduction: int = 8
    investigate_notoriety: int = 10
    conspiracy_notoriety: int = 6
    conspiracy_trust_seed: int = 30
    detain_sentence: int = 6
    trial_sentence: int = 20
    trial_fine: int = 25
    acquittal_notoriety_relief: int = 15
    accuser_acquittal_penalty: int = 8
    released_notoriety_relief: int = 10


@dataclass
class CommunicationParams:
    """EM-250 — Communication & Culture tunables (config `world.comm`, Wave O
    keystone). The engine reads this block via its defensive `_comm_param`
    accessor with IDENTICAL defaults (the CrimeParams/_crime_param convention),
    so a world.yaml WITHOUT the `comm` block behaves exactly like these values.
    UNLIKE crime this block HAS an `enabled` flag, defaulting FALSE: the Wave-O
    transmission verbs and the diffuse_culture round boundary (EM-251/EM-252)
    gate on it, so a default world mints no memes, emits no new prompt line /
    menu entry / event, and stays byte-identical (the em161 golden + EM-155).

      enabled             — master gate for the Wave-O comm verbs + diffusion.
      diffusion_chance    — per-carrier co-located passive-hop chance (seeded,
                            EM-252; never random).
      max_diffusions      — per-round ceiling on passive hops.
      half_life_ticks     — ticks without a spread before virality halves.
      decay_ticks         — ticks without a spread before a zero-carrier meme dies.
      letter_cap          — undelivered letters parked per mailbox (FIFO, EM-251).
      held_meme_cap       — memes an agent carries (FIFO, oldest dropped).
      distortion_strength — _distort_text mutation passes per transmission hop.
      meme_images         — create_image auto-registers an image meme (EM-253).
      dominance_threshold — carriers needed for a meme_dominant event.
      camp_min_shared     — shared memes that bind a culture-camp edge.
      camp_min_size       — minimum members for a culture camp.
    """
    enabled: bool = False
    diffusion_chance: float = 0.20
    max_diffusions: int = 12
    half_life_ticks: int = 30
    decay_ticks: int = 80
    letter_cap: int = 8
    held_meme_cap: int = 12
    distortion_strength: int = 1
    meme_images: bool = True
    dominance_threshold: int = 6
    camp_min_shared: int = 2
    camp_min_size: int = 3


@dataclass
class NeedsParams:
    """EM-229 — Three-needs psychology (config `world.needs`). Two decaying drives
    — `knowledge` and `influence` — ride alongside `energy` on every AgentState.

    UNLIKE energy these NEVER kill; they only bias behavior via a conditional
    prompt line that surfaces ONLY when a need drops below its salience threshold
    (so a full-needs agent's prompt is byte-identical to pre-EM-229 — the em161
    golden). The engine reads this block via the defensive `_needs_param`
    accessor with IDENTICAL defaults, so a world.yaml WITHOUT a `needs` block
    decays at exactly these rates (no KeyError, no crash).

    EW drives map energy ~30h / influence ~24h / knowledge ~36h → scaled to our
    tick cadence as SLOWER decay than energy (energy_decay_per_turn defaults 4):
    small non-zero per-turn defaults so the needs drift over many turns. NO
    `enabled` flag — the decay is always-on (additive, additive-default fields),
    and the always-on PROMPT change is kept golden-safe by the salience gate.

      knowledge_decay_per_turn     — knowledge lost each turn (curiosity drive)
      influence_decay_per_turn     — influence lost each turn (politics drive)
      knowledge_salience_threshold — below this, the prompt nudges toward
                                     learning/teaching (curiosity)
      influence_salience_threshold — below this, the prompt nudges toward
                                     politics/campaigning/social wins

    Replenishment (engine `replenish_knowledge` / `replenish_influence`): learning
    (teach/skill-gain, EM-227/228) tops up knowledge; governance/social wins top
    up influence. Wave M2 wires those call-sites; the hooks clamp to 100.
    """
    knowledge_decay_per_turn: float = 0.5
    influence_decay_per_turn: float = 0.4
    knowledge_salience_threshold: float = 40.0
    influence_salience_threshold: float = 40.0


@dataclass
class MemoryParams:
    """EM-233 — Memory consolidation ("sleep") + soul entries (config
    `world.memory`). Two cognition pieces ride on AgentState:

      * SOUL — a tiny IMMUTABLE list of identity anchors (`soul`), seeded from a
        persona at spawn if configured, capped at `soul_cap`. NEVER summarized;
        injected into every prompt. An empty soul (the default) ⇒ no prompt block
        ⇒ the em161 lawful-citizen golden is byte-identical.
      * CONSOLIDATION — at the round boundary, an agent whose `beliefs` count
        exceeds `consolidate_at` has its OLDEST beliefs deterministically rolled
        into ONE digest line (a structured rollup, NO LLM in v1), keeping the
        `consolidate_keep_recent` most-recent beliefs verbatim. Emits a `memory`
        event. Pure arithmetic/string work — no random, no clock (EM-155).

    The engine reads this block via the defensive `_memory_param` accessor with
    IDENTICAL defaults, so a world.yaml WITHOUT a `memory` block consolidates at
    exactly these values (no KeyError, no crash) and a soulless agent stays
    byte-identical to pre-EM-233. NO `enabled` flag by design: consolidation only
    fires above the count ceiling (a small cast under it is untouched), and the
    soul block is empty by default — both additive, both golden-safe.

      consolidate_at          — beliefs count above which the round-boundary
                                consolidation rolls up the oldest beliefs. The
                                belief list is bounded at this ceiling.
      consolidate_keep_recent — how many of the most-recent beliefs survive a
                                consolidation verbatim (the rest fold into the
                                single digest line). MUST be < consolidate_at.
      soul_cap                — max identity anchors per agent (seed + restore
                                both truncate to this).
    """
    consolidate_at: int = 20
    consolidate_keep_recent: int = 8
    soul_cap: int = 3


@dataclass
class SkillsParams:
    """EM-227 — Skills & emergent professions (config `world.skills`). A
    per-agent `skills: dict[str, int]` (skill name → level) rides on every
    AgentState; THIS block is the world's skill LIBRARY plus the xp/level math
    and the per-archetype seed table.

      library    — {skill_name: {gates: [action, ...], min_level: int}}. Each
                   named skill GATES a list of high-value actions: an agent
                   attempting a gated action whose level < min_level is rejected
                   ("you lack the <skill> skill"). An EMPTY library (the default,
                   and any world.yaml without the block) gates NOTHING — every
                   existing action stays open, so a pre-EM-227 world (and the
                   em161 golden) behaves byte-identically. Survival verbs
                   (move/work/forage/say/whisper/recharge/idle/remember) are
                   NEVER listed here — they are always open by contract.
      archetypes — {archetype_name: {skill: starting_level}}. The deterministic
                   seed table: World.seed_skills(agent, archetype) grants these
                   starting levels so identical agents diverge by archetype. No
                   archetype / no library ⇒ a no-op seed (skill-less, golden-safe).
      xp_per_use   — xp granted for ONE successful gated action (learn-by-doing).
      xp_per_level — xp needed per level (a level is gained each time the
                     accumulated xp crosses a multiple of this). Deterministic
                     arithmetic — no random, no clock (EM-155).
      max_level    — the level ceiling (xp past it grants no further levels).

    The engine reads this block via the defensive `_skills_param` accessor with
    IDENTICAL defaults, so a world.yaml WITHOUT a `skills` block is a complete
    no-op (no KeyError, no gating, no prompt block). NO `enabled` flag by design:
    an empty library IS the off state (additive, golden-safe)."""
    library: dict = field(default_factory=dict)
    archetypes: dict = field(default_factory=dict)
    xp_per_use: int = 10
    xp_per_level: int = 30
    max_level: int = 5


@dataclass
class CooperationParams:
    """EM-231 — Cooperation-gated tools (config `world.cooperation`). EW's hard
    mechanic: a class of high-value action is unlocked ONLY when both partners
    have AGREED to cooperate.

    A co-located pair forms a HANDSHAKE — one agent `offer_cooperation(target)`,
    the other `accept_cooperation` — creating a SYMMETRIC active link on the
    World. The ONE cooperation-gated action `co_build(building_id)` then requires
    an active handshake with a CO-LOCATED partner: it advances a building like
    `build_step` but by `co_build_bonus_step` (the cooperation payoff over a solo
    build_step). A solo agent attempting co_build is cleanly rejected.

    The engine reads this block via the defensive `_coop_param` accessor with
    IDENTICAL defaults, so a world.yaml WITHOUT a `cooperation` block behaves at
    exactly these values (no KeyError). NO `enabled` flag by design — the
    handshake + the gated verb are PURELY ADDITIVE affordances: a world that
    never forms a handshake has no cooperation state (golden + snapshot
    byte-identical), and co_build is simply unavailable until a pair agrees.

      co_build_bonus_step — progress a single co_build adds to a building (set
                            ABOVE buildings.build_step — default 20 — so a joint
                            build genuinely outpaces solo work; the cooperation
                            payoff). Clamped to >= 1.
    """
    co_build_bonus_step: int = 35


@dataclass
class VictoryArchParams:
    """EM-232 — Peer-judged credit economy / Victory Arch (config
    `world.victory_arch`). A periodic pitch -> peer-judge -> award cycle (EW's
    ~2-day Victory Arch cadence).

    Agents `pitch_contribution(text)` (a reflex verb) to park a pitch. At a cycle
    boundary — `every_n_ticks` ticks — the parked pitches are ranked by a
    DETERMINISTIC contribution score (each pitcher's durable `contributions`
    ledger: buildings funded, skills taught, trades settled, projects built; NO
    random, tie-broken by agent id). The top_n pitchers each get `award` credits +
    a `reputation_bonus` renown bump + an `influence_replenish` (the EM-229 hook).
    An `arch_award` event fires per winner; the pitch queue clears each cycle.
    Adds reputation-through-contribution + the inequality story (a Gini/AWI read).

    The engine reads this block via the defensive `_arch_param` accessor with
    IDENTICAL defaults, so a world.yaml WITHOUT a `victory_arch` block is a
    complete NO-OP: `every_n_ticks` defaults to 0, the cycle gate is never true,
    no pitch line is offered, and pitches simply accumulate without an award
    (byte-identical pre-EM-232 + the em161 golden). The DEFAULT-OFF (every_n_ticks
    0) IS the off state by design — no separate `enabled` flag (the EM-227 empty-
    library convention). The live config sets a positive cadence to turn it on.

      every_n_ticks      — the cycle cadence: a cycle fires when
                           `tick > 0 and tick % every_n_ticks == 0`. <= 0 ⇒ OFF
                           (no cycle ever, pitches accumulate, no prompt line).
      award              — credits granted to each winning pitcher (the prize).
      top_n              — how many top-ranked pitchers win each cycle (>= 1).
      reputation_bonus   — renown points added to each winner (the durable
                           reputation-through-contribution signal; clamped >= 0).
      influence_replenish — influence (EM-229 need) topped up on each winner,
                           clamped 0..100 by replenish_influence (>= 0).
    """
    every_n_ticks: int = 0
    award: int = 50
    top_n: int = 1
    reputation_bonus: int = 5
    influence_replenish: float = 25.0


@dataclass
class BoostParams:
    """EM-235 — Boost queue (config `world.boost`). Agents spend credits to buy
    EXTRA scheduled turns/airtime (EW's ComputeCredits) — they literally purchase
    influence over the shared timeline (the north-star: MORE turns/LLM calls).

    A reflex verb `buy_turn` deducts `cost` credits (rejected when the agent is too
    poor) and bumps a durable per-agent counter `boosted_turns`. The scheduler
    honors the counter: when a round's due rotation is exhausted, every agent with
    a parked boost gets ONE extra slot (sorted by id for determinism), the counter
    decrementing as that slot is consumed — BEFORE the round rolls over. A per-agent
    per-round cap (`max_per_round`) bounds how many extra turns one agent buys in a
    single round.

    The engine reads this block via the defensive `_boost_param` accessor with
    IDENTICAL defaults, so a world.yaml WITHOUT a `boost` block is a complete
    NO-OP: `cost` defaults to 0, every buy is rejected (no credits move, no boost
    granted), no `buy_turn` line is offered, and the scheduler is untouched
    (byte-identical pre-EM-235 + the em161 golden). The DEFAULT-OFF (cost 0) IS the
    off state by design — no separate `enabled` flag (the EM-232 cadence-0
    convention). The live config sets a positive cost to turn it on.

      cost           — credits a single `buy_turn` deducts (the price of one extra
                       turn). <= 0 ⇒ OFF (every buy rejected, no prompt line).
      max_per_round  — how many extra turns ONE agent may buy in a single round
                       (>= 1; the per-round cap resets at each round boundary).
    """
    cost: int = 0
    max_per_round: int = 2


@dataclass
class ConstitutionParams:
    """EM-236 — Living constitution (config `world.constitution`). An amendable,
    ARTICLED foundational document layered over today's flat rule list.

    Articles are added/edited/removed ONLY through governance: an agent proposes a
    `propose_rule(effect="amend_constitution", op=..., text=..., article_id?=...)`
    and it RATIFIES on a 70% SUPERMAJORITY — the same bar as `demolish`. A ratified
    amendment mutates `World.constitution` and replenishes the proposer's influence
    need (EM-229). The constitution is surfaced in the prompt ONLY when non-empty.

    The engine reads this block via the defensive `_constitution_param` accessor
    with IDENTICAL defaults, so a world.yaml WITHOUT a `constitution` block behaves
    exactly like these values — i.e. byte-identical to pre-EM-236. NO `enabled`
    flag: the constitution is empty until an amendment is RATIFIED (a deliberate
    governance act), so an un-amended world (and every pre-EM-236 snapshot) stays
    byte-identical without one — the constitution simply never grows.

      ratify_threshold    — the YES-vote supermajority fraction an amendment needs
                            to ratify (0.7 == 70%, the `demolish` bar). Clamped to
                            (0, 1]; the engine accessor falls back to 0.7.
      influence_replenish — influence (EM-229 need) topped up on the PROPOSER when
                            an amendment ratifies (a governance win), clamped
                            0..100 by replenish_influence (>= 0).
    """
    ratify_threshold: float = 0.7
    influence_replenish: float = 15.0


@dataclass
class GovernanceParams:
    """EM-203 — governance renewal cooldown (config `world.governance`). A
    settled-signal guard over the W11b/EM-087 RENEWAL ritual: re-proposing an
    effect identical to an ACTIVE rule is normally allowed (it tags renewal_of
    and refreshes the law on passing — civic charm). But run-663 showed agents
    re-passing the SAME unchanged law endlessly (work_bonus ×35, ubi ×27,
    recharge_subsidy ×19) instead of legislating anything NEW.

    When `renewal_cooldown_ticks` > 0, a renewal of an active rule whose LAST
    activation (max of created_tick / renewed_at) is within the cooldown is
    rejected as 'already active (settled)', nudging agents to author new work.

    The engine reads this via the defensive `_governance_param` accessor with an
    IDENTICAL default, so a world.yaml WITHOUT a `governance` block behaves
    exactly like pre-EM-203 — i.e. byte-identical. NO `enabled` flag: the DEFAULT
    of 0 disables the cooldown (every renewal still allowed, the W11b ritual
    intact), so an absent block and every pre-EM-203 snapshot stay byte-identical
    without one — the live config sets a positive window.

      renewal_cooldown_ticks — ticks an unchanged ACTIVE effect-rule cannot be
                               renewed for, measured from its last activation.
                               0 (default) = no cooldown (pre-EM-203 behavior).
                               Clamped to >= 0 (a malformed value falls back to 0).
    """
    renewal_cooldown_ticks: int = 0


@dataclass
class ChildrenParams:
    """Wave E / EM-114 — lightweight children (config `world.children`).
    Once per round boundary the world checks every mutual-partner pair
    (B1 `are_partners`) co-located at a home for a birth. Children are NEW
    agents and spawn at `background` tier, only into VACANCIES under
    max_population AND total home-bed capacity — births never grow the LLM
    call budget past today's (the free-scale law). The engine reads this
    block via its defensive _chl_param accessor with IDENTICAL defaults.

      enabled            — master toggle (default ON). `false` ⇒ no birth
                           checks at all: byte-identical pre-E behavior.
      max_population     — births only while living humans < this (default 25,
                           the measured v4 free-tier budget).
      birth_cost_credits — BOTH parents pay this (credits sink); both must
                           also hold energy >= 30.
      birth_chance       — seeded unit-float gate per eligible pair, derived
                           from sha1(city_seed, tick, a_id, b_id) — never the
                           `random` module (EM-155 determinism).
      pair_cooldown_ticks — no second child of the SAME pair within this many
                           ticks; derived from the youngest shared child's
                           family-relationship since_tick (no new clock state).
    """
    enabled: bool = True
    max_population: int = 25
    birth_cost_credits: int = 6
    birth_chance: float = 0.25
    pair_cooldown_ticks: int = 600


@dataclass
class GenerationsParams:
    """EM-126 — generational depth (config `world.generations`). Builds on the
    EM-114 children mechanic: agents pass through LIFE STAGES (child → adult →
    elder) as they age, and on death pass their estate (credits, optionally
    relationships/grudges) down the EM-114 parents/children lineage to an heir.

    DEFAULT OFF (`enabled=False`): byte-identical to pre-EM-126 — no agent ages
    (age_ticks stays 0), every agent stays `adult`, and death drops no estate
    (the EM-114 children mechanic is untouched). So the protagonist prompt golden
    file and the snapshot key set are unchanged, and EM-114 children keep working
    exactly as before. The engine reads this block via the defensive
    `_generations_param` accessor with IDENTICAL defaults, so a world.yaml WITHOUT
    a `generations` block — and an absent block — behaves the same (config-absent
    = OFF). Flip `enabled: true` for the live runs to get life stages + inheritance.

    Aging cadence (when enabled): `age_ticks` increments ONCE per round in
    World.age_agents (hooked at the round boundary). The thresholds are measured in
    ROUNDS (= age_ticks): an agent with age_ticks < child_until is a `child`, with
    age_ticks >= elder_after an `elder`, otherwise an `adult`. Promotion is PURE
    arithmetic over age_ticks (no random, no clock — EM-155 / replay-safe).

    Inheritance (when enabled): on death, the estate passes to the deceased's HEIR
    — selected deterministically from the EM-114 lineage (living children first,
    then living parents; the lowest-id heir among the closest tier wins, a pure
    sorted-id pick). `inherit_credits` (default ON) transfers all the deceased's
    credits to the heir; `inherit_relationships` (default OFF) additionally copies
    the deceased's relationships/grudges the heir does not already hold. Emits an
    `inherited` event. No heir ⇒ a no-op (credits simply vanish, as today).

      enabled               — master toggle (default False = zero behavioral
                              change; EM-114 children unaffected).
      child_until           — age_ticks (rounds) below which an agent is a child.
                              Clamped >= 0; default 6.
      elder_after           — age_ticks (rounds) at/above which an agent is an
                              elder. Clamped >= child_until; default 60.
      inherit_credits       — pass the deceased's credits to the heir (default ON).
      inherit_relationships — also copy the deceased's relationships/grudges the
                              heir lacks (default OFF — a smaller, safer estate).
    """
    enabled: bool = False
    child_until: int = 6
    elder_after: int = 60
    inherit_credits: bool = True
    inherit_relationships: bool = False


@dataclass
class FactionParams:
    """Wave E / EM-120 — factions, feuds & reputation (config `world.factions`).
    At each ROUND boundary (after the EM-114 birth check — contract order:
    births first, then factions) the world recomputes candidate clusters:
    connected components over MUTUAL warm edges — both directions typed
    ally|friend|partner|family AND both trusts >= faction_trust — among living
    agents; components of size >= faction_min_size are factions. Pure derived
    state, zero LLM calls (the wave's free-scale law); events fire on DIFFS
    only, never on stable rounds. The engine reads this block via its
    defensive _fct_param accessor with IDENTICAL defaults.

      enabled          — master toggle (default ON). `false` ⇒ no recompute,
                         no faction events, no `factions`/`reputation`
                         snapshot keys: byte-identical pre-E behavior.
      faction_trust    — a warm edge needs BOTH directions' trust >= this.
      faction_min_size — components below this size never form (and an
                         existing faction shrinking under it dissolves).
    """
    enabled: bool = True
    faction_trust: int = 25
    faction_min_size: int = 3


@dataclass
class MiracleParams:
    """Wave E / EM-184 — world-scale god miracles (config `world.miracles`).
    The god console's `POST /api/god/intervene` grows three WORLD kinds (no
    agent_id): timed `send_rain` / `bountiful_harvest` buffs swept beside the
    blackout expiry each tick, and one-time `calm_spirits`. Pure state
    modifiers — zero LLM calls (the wave's free-scale law). The engine reads
    this block via its defensive _mir_param accessor with IDENTICAL defaults.

      enabled              — master toggle (default ON). `false` ⇒ world kinds
                             are rejected (ValueError → API 422); the targeted
                             bless_energy/grant_credits kinds are untouched:
                             byte-identical pre-E behavior.
      rain_forage_bonus    — send_rain: extra forage credits while active, on
                             top of base + garden/farm bonuses.
      rain_days            — send_rain duration in IN-WORLD days
                             (days × turns_per_day ticks).
      harvest_decay_factor — bountiful_harvest: energy decay is multiplied by
                             this while active (0.5 = half decay).
      harvest_days         — bountiful_harvest duration in in-world days.
      calm_trust_bonus     — calm_spirits: one-time `_update_trust` delta for
                             every living↔living relationship with
                             interactions >= 1 (clamped as usual; B1 reflex
                             transitions may fire — that's the point).
    """
    enabled: bool = True
    rain_forage_bonus: int = 2
    rain_days: int = 2
    harvest_decay_factor: float = 0.5
    harvest_days: int = 2
    calm_trust_bonus: int = 3


@dataclass
class MemoryRetrievalParams:
    """EM-222 — relevance-scored long-term memory retrieval (config
    `world.memory_retrieval`). Protagonist/supporting agents recall RELEVANT old
    events (Smallville recency × importance × relevance over the persisted event
    log + cached embeddings), not just the last ~12. The runtime reads this block
    via its defensive _world_block_get accessor with IDENTICAL defaults, so an
    absent block behaves exactly like these values. The BACKGROUND tier keeps its
    blind-recency prompt diet (EM-161) regardless of this block.

      enabled                — master toggle (default ON). `false` ⇒ every tier
                               keeps blind recency: byte-identical pre-EM-222.
      embed_model            — the dedicated embedding model id (the `embed`
                               profile, bge-m3); embeddings use this fixed model,
                               not the agent's chat profile.
      top_k                  — how many scored memories to surface per turn.
      recent_tail            — recent events always merged in alongside the
                               retrieved top-K (the immediate context never
                               drops out, however the scoring ranks it).
      candidate_limit        — newest-first candidate corpus cap pulled from the
                               DB before scoring (bounds the per-turn embed cost).
      w_relevance/w_importance/w_recency — blend weights for the three
                               (each-normalized-to-[0,1]) signals.
      recency_halflife_ticks — age (ticks) at which the recency signal decays to
                               0.5.
    """
    enabled: bool = True
    embed_model: str = "bge-m3"
    top_k: int = 12
    recent_tail: int = 6
    candidate_limit: int = 400
    w_relevance: float = 0.5
    w_importance: float = 0.3
    w_recency: float = 0.2
    recency_halflife_ticks: int = 200


@dataclass
class CadenceParams:
    """Wave D2 / EM-159+160 — background-tier salience gating + the spontaneity
    floor (config `world.cadence`). ADDITIVE: an absent block behaves exactly
    like these defaults; the runtime reads it via the defensive _world_block_get
    accessor with IDENTICAL defaults. EM-159 (salience gating) never ships
    without EM-160 (this floor) — background agents must never flatten into
    NPCs-on-rails.

      spontaneity_chance  — seeded probability (0..1) that a due-but-NON-salient
                            background turn takes a full LLM turn anyway (the
                            wildcard half of the floor). Seeded from world
                            state (agent id + tick hash) — deterministic,
                            replay-safe. 0 disables the wildcard.
      reflex_streak_limit — consecutive reflex-only due turns before a forced
                            LLM "reassess" turn (the floor-timer half).
    """
    spontaneity_chance: float = 0.15
    reflex_streak_limit: int = 8


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
    road_build_energy_cost: float = 8.0  # EM-243 (S2) — meaningful but not rare (cf. attack 6).
    # NOTE: the build_road growth envelope (9x9) is NOT a config param — it lives as the
    # citygraph.MAX_CITY_BLOCKS/MIN_IDX/MAX_IDX constants (mirrored by cityLayout ENV_*),
    # the single source of truth that keeps backend bounds + frontend clip in lockstep.
    # EM-199 — multi-action turns: the max number of actions one LLM turn may
    # resolve from a single `actions` sequence (move + fund + say → 3 feed lines
    # from one call). A generous guardrail (4× the old single-action limit), NOT
    # a throttle. Steps beyond this are dropped (logged). 1 ⇒ legacy single-action.
    max_actions_per_turn: int = 4
    # Wave D2 / EM-170 — turn-latency guard: hard wall-clock budget (seconds)
    # for ONE agent-turn LLM consult (router.chat, including the adapter's
    # internal retry). On timeout the call is cancelled and the turn resolves
    # via the existing idle-fallback path (reason `llm_timeout`) so a single
    # slow call can never freeze the world (run 248: 14-32s stalls). The
    # DATACLASS default is 0.0 = guard fully disabled = exactly today's
    # behavior (tests build WorldParams directly); the shipped yamls set 12.
    turn_llm_budget_seconds: float = 0.0
    # Wave D3 / EM-187 — resume-on-boot (config `world.resume_on_boot`). When
    # true (default), startup resumes the most recent run whose latest
    # snapshot tick is > 0 as a NEW run row with fork lineage — provided the
    # world-defining config (agent roster, places set, city_seed) still
    # matches the parent run's; tunable params always adopt the current
    # config. BOOT behavior only — it does not ride snapshots. False ⇒
    # byte-identical pre-D3 boot (always a fresh run).
    resume_on_boot: bool = True
    # W15 / EM-155 — deterministic seed for the generated 3D city ring (config
    # `world.city_seed`). The engine copies it onto World and persists it in
    # to_snapshot()/world_state, so live/replay/fork render the SAME city.
    # Additive with a safe default — configs without the key are unchanged.
    city_seed: int = 1337
    # W9 / EM-070 — survival pressure: energy below this threshold marks an agent
    # as starving (one-shot `agent_starving` warning + prompt urgency).
    starving_warn_threshold: float = 25.0
    # W9 / EM-071 — pause the tick loop when the last living human agent dies
    # (after emitting + broadcasting `world_extinct`). Animals alone do not keep
    # the run "alive".
    auto_pause_on_extinction: bool = True
    # EM-226 — pause the tick loop when EVERY agent turn fails to reach a model
    # for `provider_error_pause_threshold` turns in a row (connection down, or all
    # lanes rate-limited/exhausted) instead of burning ticks on idle fallbacks.
    # The streak resets on any turn that DOES reach a model (success or a content
    # parse failure), so a transient blip never trips it.
    auto_pause_on_provider_errors: bool = True
    provider_error_pause_threshold: int = 8
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
    # Wave K / EM-218 — placeable props cap. Additive; an absent `props` block
    # uses the default max_population (48), mirroring the animals cap pattern.
    props: PropsParams = field(default_factory=PropsParams)
    # Wave I / EM-210 — image generation (The Atelier). Additive; an absent
    # `image_gen` block uses the engine-matching defaults (max_concurrent 2,
    # max_gallery 30), so a pre-Wave-I world.yaml behaves exactly as before.
    image_gen: ImageGenParams = field(default_factory=ImageGenParams)
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
    # Wave D2 / EM-159+160 — background-tier salience gating + spontaneity
    # floor. Additive with engine-matching defaults, so a world.yaml without
    # the `cadence` block behaves exactly as the shipped defaults.
    cadence: CadenceParams = field(default_factory=CadenceParams)
    # EM-222 — relevance-scored long-term memory retrieval. Additive with
    # runtime-matching defaults (default ON); an absent `memory_retrieval`
    # block behaves exactly as these values. Background tier is untouched
    # either way (it keeps its blind-recency diet).
    memory_retrieval: MemoryRetrievalParams = field(
        default_factory=MemoryRetrievalParams)
    # Wave D3 / EM-177 — lane failover with recovery probes. Additive with
    # router-matching defaults (default ON); `enabled: false` restores the
    # byte-identical pre-D3 routing.
    lane_failover: LaneFailoverParams = field(default_factory=LaneFailoverParams)
    # EM-167 — Ollama overflow lane. Additive with router-matching defaults
    # (default OFF); an absent block / `enabled: false` keeps the byte-identical
    # pre-EM-167 routing (no overflow detours, no new spans).
    overflow_lane: OverflowLaneParams = field(default_factory=OverflowLaneParams)
    # Adaptive Lane Routing (spec 2026-07-07) — the custom sorting list + bounce
    # loop. Sourced from config/lanes.yaml (not world.yaml); additive with
    # router-matching defaults (default OFF). `enabled: false` / no lanes.yaml ⇒
    # byte-identical pre-spec routing (pinned lane → EM-205 `auto` backup). The
    # parsed block rides config_json so a fork/replay pins the routing config.
    adaptive_routing: AdaptiveRoutingParams = field(
        default_factory=AdaptiveRoutingParams)
    # Wave D3 / EM-168 — cap-pressure governor. Additive with engine-matching
    # defaults (default ON); `enabled: false` keeps usage alerts alert-only
    # (byte-identical pre-D3 behavior).
    cap_governor: CapGovernorParams = field(default_factory=CapGovernorParams)
    # Wave E / EM-113 — relationship-depth thresholds. Additive with
    # engine-matching defaults; thresholds only fire on NEW trust mutations,
    # so a world.yaml without the block restores pre-E snapshots byte-identical.
    relationships: RelationshipParams = field(default_factory=RelationshipParams)
    # EM-240 — Crime & Justice tunables. Additive with engine-matching defaults;
    # crime/justice verbs only fire on a deliberate agent turn, so a world.yaml
    # without the `crime` block restores pre-EM-240 snapshots byte-identical.
    crime: CrimeParams = field(default_factory=CrimeParams)
    # EM-250 — Communication & Culture (Wave O keystone). Additive with a
    # DEFAULT-OFF `enabled`, so a world.yaml without the `comm` block mints no
    # memes, spreads nothing, and keeps the em161 golden + every pre-EM-250
    # snapshot byte-identical. The caps (held_meme_cap / letter_cap) also bound
    # the defensive snapshot-restore path, mirroring memory.soul_cap.
    comm: CommunicationParams = field(default_factory=CommunicationParams)
    # EM-229 — three-needs psychology tunables. Additive with engine-matching
    # defaults; the decay is always-on but the prompt surfacing is salience-gated
    # so a world.yaml without the `needs` block keeps the em161 golden + restores
    # pre-EM-229 snapshots byte-identical (needs default 100.0, omitted at 100).
    needs: NeedsParams = field(default_factory=NeedsParams)
    # EM-233 — memory consolidation + soul entries. Additive with engine-matching
    # defaults; consolidation only fires above the count ceiling and the soul
    # block is empty by default, so a world.yaml without the `memory` block keeps
    # the em161 golden + restores pre-EM-233 snapshots byte-identical.
    memory: MemoryParams = field(default_factory=MemoryParams)
    # EM-227 — skills & emergent professions. Additive with an EMPTY library by
    # default, so a world.yaml without the `skills` block gates NOTHING (every
    # existing action open) — byte-identical pre-EM-227 + the em161 golden. A
    # populated `library` gates its listed high-value actions on a min skill
    # level; `archetypes` seeds a deterministic starting spread per persona.
    skills: SkillsParams = field(default_factory=SkillsParams)
    # EM-231 — cooperation-gated tools. Additive: the handshake + the gated
    # co_build verb are pure affordances with no `enabled` flag — a world that
    # never forms a handshake has no cooperation state (golden + snapshot
    # byte-identical), and co_build is simply unavailable until a pair agrees.
    cooperation: CooperationParams = field(default_factory=CooperationParams)
    # EM-232 — peer-judged credit economy / Victory Arch. Additive with a DEFAULT-
    # OFF cadence (every_n_ticks 0), so a world.yaml without the `victory_arch`
    # block never fires a cycle and never offers the pitch line — byte-identical
    # pre-EM-232 + the em161 golden. A positive cadence turns the pitch->judge->
    # award cycle on (the live config sets one).
    victory_arch: VictoryArchParams = field(default_factory=VictoryArchParams)
    # EM-235 — boost queue. Additive with a DEFAULT-OFF cost (0), so a world.yaml
    # without the `boost` block rejects every buy_turn and never offers the line —
    # byte-identical pre-EM-235 + the em161 golden + an untouched scheduler. A
    # positive cost turns the buy-an-extra-turn economy on (the live config sets one).
    boost: BoostParams = field(default_factory=BoostParams)
    # EM-236 — living constitution. Additive with engine-matching defaults; the
    # constitution is empty until an amendment RATIFIES (a governance act), so a
    # world.yaml without the `constitution` block — and every pre-EM-236 snapshot —
    # is byte-identical (no `enabled` flag: the document simply never grows). The
    # block only tunes the ratify supermajority + the proposer's influence reward.
    constitution: ConstitutionParams = field(default_factory=ConstitutionParams)
    # EM-203 — governance renewal cooldown. Additive with an engine-matching
    # default of 0 (no cooldown), so a world.yaml without the `governance` block —
    # and every pre-EM-203 snapshot — is byte-identical (no `enabled` flag: 0
    # leaves the W11b renewal ritual untouched). A positive value blocks re-passing
    # an unchanged active rule within the window (the run-663 work_bonus/ubi spam).
    governance: GovernanceParams = field(default_factory=GovernanceParams)
    # Wave E / EM-114 — lightweight children. Additive with engine-matching
    # defaults (default ON); births require a mutual-partner pair, so a world
    # without partners (every pre-E world) behaves byte-identically.
    # `enabled: false` skips the birth check entirely.
    children: ChildrenParams = field(default_factory=ChildrenParams)
    # EM-126 — generational depth. Additive with an engine-matching default;
    # DEFAULT OFF, so a world.yaml without the `generations` block is byte-identical
    # to pre-EM-126 (prompt golden + snapshot key set) — no agent ages, every agent
    # stays adult, and death drops no estate, so the EM-114 children mechanic is
    # untouched. `enabled: true` turns on life stages (child→adult→elder aging
    # cadence) + inheritance of credits (and optionally relationships) to a lineage
    # heir on death (emits an `inherited` event).
    generations: GenerationsParams = field(default_factory=GenerationsParams)
    # Wave E / EM-184 — world-scale god miracles. Additive with
    # engine-matching defaults (default ON); `enabled: false` rejects the
    # world kinds only — targeted bless/grant stay byte-identical.
    miracles: MiracleParams = field(default_factory=MiracleParams)
    # Wave E / EM-120 — factions, feuds & reputation. Additive with
    # engine-matching defaults (default ON); `enabled: false` skips the
    # round-boundary recompute entirely (byte-identical pre-E behavior).
    factions: FactionParams = field(default_factory=FactionParams)
    # Wave L / EM-223 — recursive+reactive planning. Additive with
    # engine-matching defaults; DEFAULT OFF, so a world.yaml without the
    # `planning` block is byte-identical to pre-EM-223 (prompt golden +
    # snapshot key set). `enabled: true` activates the plan layer.
    planning: PlanningParams = field(default_factory=PlanningParams)
    # EM-234 — universalization prompting (GovSim scaffold). Additive with an
    # engine-matching default; DEFAULT OFF, so a world.yaml without the
    # `universalization` block is byte-identical to pre-EM-234 (prompt golden +
    # snapshot key set — EM-234 carries NO per-agent/world state). `enabled: true`
    # injects the always-on "what if EVERY agent did this?" commons-reasoning
    # block into every turn (zero extra LLM calls — rides the existing turn).
    universalization: UniversalizationParams = field(
        default_factory=UniversalizationParams)
    # EM-224 — PIANO coherence for multi-action turns. Additive with an
    # engine-matching default; DEFAULT OFF, so a world.yaml without the
    # `coherence` block is byte-identical to pre-EM-224 (prompt golden +
    # snapshot key set — EM-224 carries NO prompt block and NO agent/world
    # state). `enabled: true` runs the deterministic coherence bottleneck over
    # each turn's resolved actions[] (zero extra LLM calls — rides the turn).
    coherence: CoherenceParams = field(default_factory=CoherenceParams)
    # EM-123 — zoned districts that deepen as megaprojects complete. Additive
    # with engine-matching defaults (default ON); `enabled: false` keeps every
    # district at tier 1 (byte-identical pre-EM-123: no district_grew events,
    # no new snapshot keys). Inert for un-districted (procgen) towns.
    district_growth: DistrictGrowthParams = field(
        default_factory=DistrictGrowthParams)
    # EM-246 (S4) — the run-start city profile (config `world.city`). Seeds the
    # initial CityGraph via citygraph.template() at World.__init__. Absent/empty
    # ⇒ grid (byte-identical pre-EM-246: classic_grid(city_seed)).
    city: CityProfileParams = field(default_factory=CityProfileParams)


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
            max_tokens=int(p.get("max_tokens", 1024)),
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
        zoo_capacity=max(0, int(raw.get("zoo_capacity", d.zoo_capacity))),
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

    def _ambient_every() -> int:
        # Wave H2 / EM-207 — 0 = OFF (the backward-compatible default); clamp >= 0.
        try:
            return max(0, int(raw.get("ambient_spawn_every", d.ambient_spawn_every)))
        except (TypeError, ValueError):
            return d.ambient_spawn_every

    def _ambient_chance() -> float:
        try:
            return min(1.0, max(0.0, float(
                raw.get("ambient_spawn_chance", d.ambient_spawn_chance))))
        except (TypeError, ValueError):
            return d.ambient_spawn_chance

    def _nonneg_int(key: str, default: int) -> int:
        # Wave H4 / EM-209 — clamp >= 0 (a malformed value never breaks the block).
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return AnimalParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        act_every_n_ticks=max(1, int(raw.get("act_every_n_ticks", d.act_every_n_ticks))),
        llm_chance=float(raw.get("llm_chance", d.llm_chance)),
        model_profile=str(raw.get("model_profile", d.model_profile) or ""),
        max_population=max(0, int(raw.get("max_population", d.max_population))),
        ambient_spawn_every=_ambient_every(),
        ambient_spawn_chance=_ambient_chance(),
        pet_energy_decay=_nonneg_int("pet_energy_decay", d.pet_energy_decay),
        pet_feed_amount=_nonneg_int("pet_feed_amount", d.pet_feed_amount),
    )


def _parse_props(raw: dict | None) -> PropsParams:
    """Parse the optional `world.props` block (Wave K / EM-218). Absent/empty ->
    the default cap (48), mirroring _parse_animals' max_population handling."""
    if not isinstance(raw, dict):
        return PropsParams()
    d = PropsParams()
    try:
        max_population = max(0, int(raw.get("max_population", d.max_population)))
    except (TypeError, ValueError):
        max_population = d.max_population
    return PropsParams(max_population=max_population)


def _parse_image_gen(raw: dict | None) -> ImageGenParams:
    """Parse the optional `world.image_gen` block (Wave I / EM-210). Absent/empty
    -> engine-matching defaults (max_concurrent 2, max_gallery 30), mirroring
    _parse_props' guarded-int handling. max_concurrent floors at 1 (a 0 would
    deadlock the semaphore); max_gallery floors at 1 (a 0 cap would drop every image)."""
    if not isinstance(raw, dict):
        return ImageGenParams()
    d = ImageGenParams()
    try:
        max_concurrent = max(1, int(raw.get("max_concurrent", d.max_concurrent)))
    except (TypeError, ValueError):
        max_concurrent = d.max_concurrent
    try:
        max_gallery = max(1, int(raw.get("max_gallery", d.max_gallery)))
    except (TypeError, ValueError):
        max_gallery = d.max_gallery
    # EM-298 — floor the per-district decal cap at 1 (a 0 would evict every fresh
    # decal), mirroring max_gallery's guard.
    try:
        max_decals_per_district = max(
            1, int(raw.get("max_decals_per_district", d.max_decals_per_district)))
    except (TypeError, ValueError):
        max_decals_per_district = d.max_decals_per_district
    return ImageGenParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        max_concurrent=max_concurrent,
        max_gallery=max_gallery,
        max_decals_per_district=max_decals_per_district,
        facades_enabled=bool(raw.get("facades_enabled", d.facades_enabled)),
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


def _parse_planning(raw: dict | None) -> PlanningParams:
    """Parse the optional `world.planning` block (Wave L / EM-223).
    Absent/empty/malformed -> engine-matching defaults (DEFAULT OFF), so a
    world.yaml without the block is byte-identical to pre-EM-223."""
    if not isinstance(raw, dict):
        return PlanningParams()
    d = PlanningParams()
    try:
        max_steps = max(1, int(raw.get("max_steps", d.max_steps)))
    except (TypeError, ValueError):
        max_steps = d.max_steps
    return PlanningParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        max_steps=max_steps,
        reflex_bias=bool(raw.get("reflex_bias", d.reflex_bias)),
    )


def _parse_universalization(raw: dict | None) -> UniversalizationParams:
    """Parse the optional `world.universalization` block (EM-234).
    Absent/empty/malformed -> engine-matching DEFAULT-OFF defaults, so a
    world.yaml without the block is byte-identical to pre-EM-234 (prompt golden +
    snapshot key set)."""
    if not isinstance(raw, dict):
        return UniversalizationParams()
    d = UniversalizationParams()
    return UniversalizationParams(
        enabled=bool(raw.get("enabled", d.enabled)),
    )


_COHERENCE_STRATEGIES = ("annotate", "drop")


def _parse_coherence(raw: dict | None) -> CoherenceParams:
    """Parse the optional `world.coherence` block (EM-224).
    Absent/empty/malformed -> engine-matching DEFAULT-OFF defaults, so a
    world.yaml without the block is byte-identical to pre-EM-224 (prompt golden +
    snapshot key set — EM-224 carries NO prompt block and NO agent/world state).
    An unknown strategy falls back to the default ('annotate')."""
    if not isinstance(raw, dict):
        return CoherenceParams()
    d = CoherenceParams()
    strategy = raw.get("strategy", d.strategy)
    if strategy not in _COHERENCE_STRATEGIES:
        strategy = d.strategy
    return CoherenceParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        strategy=strategy,
    )


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


def _parse_cadence(raw: dict | None) -> CadenceParams:
    """Parse the optional `world.cadence` block (Wave D2 / EM-159+160).
    Absent/empty/malformed -> engine-matching defaults. spontaneity_chance is
    clamped to 0..1; reflex_streak_limit to >= 1 (a 0/negative floor timer
    would mean perpetual forced reassessment)."""
    if not isinstance(raw, dict):
        return CadenceParams()
    d = CadenceParams()
    try:
        chance = float(raw.get("spontaneity_chance", d.spontaneity_chance))
    except (TypeError, ValueError):
        chance = d.spontaneity_chance
    try:
        limit = max(1, int(raw.get("reflex_streak_limit", d.reflex_streak_limit)))
    except (TypeError, ValueError):
        limit = d.reflex_streak_limit
    return CadenceParams(
        spontaneity_chance=max(0.0, min(1.0, chance)),
        reflex_streak_limit=limit,
    )


def _parse_memory_retrieval(raw: dict | None) -> MemoryRetrievalParams:
    """Parse the optional `world.memory_retrieval` block (EM-222).
    Absent/empty/malformed -> runtime-matching defaults (retrieval ON). Each key
    falls back to its default individually; counts clamp to >= 1 (a 0 candidate
    limit / top_k would starve the retriever), weights to >= 0, and the recency
    half-life to >= 1 tick (a 0/negative half-life would divide by zero) — a
    malformed value never breaks the block."""
    if not isinstance(raw, dict):
        return MemoryRetrievalParams()
    d = MemoryRetrievalParams()

    def _pos_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _nonneg_float(key: str, default: float) -> float:
        try:
            return max(0.0, float(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return MemoryRetrievalParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        embed_model=str(raw.get("embed_model", d.embed_model) or d.embed_model),
        top_k=_pos_int("top_k", d.top_k),
        recent_tail=_pos_int("recent_tail", d.recent_tail),
        candidate_limit=_pos_int("candidate_limit", d.candidate_limit),
        w_relevance=_nonneg_float("w_relevance", d.w_relevance),
        w_importance=_nonneg_float("w_importance", d.w_importance),
        w_recency=_nonneg_float("w_recency", d.w_recency),
        recency_halflife_ticks=_pos_int(
            "recency_halflife_ticks", d.recency_halflife_ticks),
    )


def _parse_lane_failover(raw: dict | None) -> LaneFailoverParams:
    """Parse the optional `world.lane_failover` block (Wave D3 / EM-177).
    Absent/empty/malformed -> router-matching defaults (failover ON).
    sick_threshold and probe_every are clamped to >= 1 (a 0/negative
    threshold would mark every lane sick; probe_every 0 would never probe)."""
    if not isinstance(raw, dict):
        return LaneFailoverParams()
    d = LaneFailoverParams()

    def _pos_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return LaneFailoverParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        sick_threshold=_pos_int("sick_threshold", d.sick_threshold),
        probe_every=_pos_int("probe_every", d.probe_every),
    )


def _parse_overflow_lane(raw: dict | None) -> OverflowLaneParams:
    """Parse the optional `world.overflow_lane` block (EM-167). Absent/empty/
    malformed -> router-matching defaults (overflow OFF). `profile` falls back
    to the default when not a non-empty string; `tiers` falls back to the
    default when not a list of strings (and is normalized to a tuple so the
    config_json fork seam round-trips: asdict serializes a tuple to a list,
    this reparses it to a tuple)."""
    if not isinstance(raw, dict):
        return OverflowLaneParams()
    d = OverflowLaneParams()

    profile = raw.get("profile", d.profile)
    if not isinstance(profile, str) or not profile:
        profile = d.profile

    tiers_raw = raw.get("tiers", d.tiers)
    if isinstance(tiers_raw, (list, tuple)) and all(
        isinstance(t, str) for t in tiers_raw
    ):
        tiers = tuple(tiers_raw)
    else:
        tiers = d.tiers

    return OverflowLaneParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        profile=profile,
        tiers=tiers,
    )


def _parse_lane_order(raw: Any) -> tuple[LaneOrderEntry, ...]:
    """Parse an adaptive-routing `order:` list into LaneOrderEntry tuple.

    Accepts BOTH the yaml shape ({source, model, free}) and the config_json
    asdict shape (same keys + out_hint/ctx_hint/tags[list]) so the fork/replay
    round-trip normalizes a serialized list of dicts back to entries. Malformed
    entries (no `source`) are skipped rather than crashing the load."""
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[LaneOrderEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        if not isinstance(source, str) or not source:
            continue
        model = item.get("model", "*")
        model = model if isinstance(model, str) and model else "*"
        tags_raw = item.get("tags") or ()
        tags = tuple(str(t) for t in tags_raw) if isinstance(
            tags_raw, (list, tuple)) else ()

        def _opt_int(key: str) -> int | None:
            v = item.get(key)
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        out.append(LaneOrderEntry(
            source=source,
            model=model,
            free=bool(item.get("free", True)),
            out_hint=_opt_int("out_hint"),
            ctx_hint=_opt_int("ctx_hint"),
            tags=tags,
        ))
    return tuple(out)


def _parse_adaptive_routing(raw: dict | None) -> AdaptiveRoutingParams:
    """Parse the optional `adaptive_routing` block (spec 2026-07-07 §3.3).
    Absent/empty/malformed -> router-matching defaults (routing OFF ⇒
    byte-identical). max_attempts clamped >= 1; per_attempt_timeout_s coerced to
    a float (a 0/negative disables the per-attempt bound in the router)."""
    if not isinstance(raw, dict):
        return AdaptiveRoutingParams()
    d = AdaptiveRoutingParams()

    def _pos_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return AdaptiveRoutingParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        max_attempts=_pos_int("max_attempts", d.max_attempts),
        per_attempt_timeout_s=_float("per_attempt_timeout_s", d.per_attempt_timeout_s),
        allow_paid=bool(raw.get("allow_paid", d.allow_paid)),
        order=_parse_lane_order(raw.get("order")),
    )


def _load_lanes_yaml_adaptive_routing(config_dir: Path | None) -> dict | None:
    """Read the `adaptive_routing:` block from `config/lanes.yaml` (spec §3.3 —
    the ONE place the user controls the sorting list). Returns the raw dict, or
    None when there is no config dir / no lanes.yaml / it is unreadable (⇒ the
    parser falls back to the OFF defaults, byte-identical)."""
    if config_dir is None:
        return None
    path = config_dir / "lanes.yaml"
    if not path.exists():
        return None
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:  # pragma: no cover - defensive (malformed yaml)
        return None
    if isinstance(data, dict):
        block = data.get("adaptive_routing")
        return block if isinstance(block, dict) else None
    return None


def _parse_cap_governor(raw: dict | None) -> CapGovernorParams:
    """Parse the optional `world.cap_governor` block (Wave D3 / EM-168).
    Absent/empty/malformed -> engine-matching defaults (governor ON)."""
    if not isinstance(raw, dict):
        return CapGovernorParams()
    d = CapGovernorParams()
    return CapGovernorParams(enabled=bool(raw.get("enabled", d.enabled)))


def _parse_district_growth(raw: dict | None) -> "DistrictGrowthParams":
    """Parse the optional `world.district_growth` block (EM-123). Absent/empty/
    malformed -> engine-matching defaults (growth ON). completions_per_tier and
    max_tier clamp to >= 1 (a 0 would either max a district on the first build
    or never let it grow). The engine reads the block via its defensive
    _block_get accessor with IDENTICAL defaults, so an absent block behaves
    exactly like these values."""
    if not isinstance(raw, dict):
        return DistrictGrowthParams()
    d = DistrictGrowthParams()

    def _pos_int(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return DistrictGrowthParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        completions_per_tier=_pos_int("completions_per_tier", d.completions_per_tier),
        max_tier=_pos_int("max_tier", d.max_tier),
    )


def _parse_city_profile(raw: dict | None) -> "CityProfileParams":
    """Parse `world.city` (EM-246). Absent/malformed ⇒ grid defaults. template/
    density/car_policy clamp to known values (unknown template is KEPT — template()
    falls back to grid + warns, so a future preset name doesn't break the loader)."""
    if not isinstance(raw, dict):
        return CityProfileParams()
    d = CityProfileParams()
    # `raw.get("template")` (no default) is None for BOTH a missing key and an
    # explicit `template:` / `template: null` — `or d.template` coerces either to
    # the grid default, so a null scalar doesn't become the literal string "none"
    # (which would route through the geometric-fallback + emit a spurious warning).
    template = str(raw.get("template") or d.template).strip().lower() or d.template
    density = str(raw.get("density", d.density)).strip().lower()
    if density not in ("low", "medium", "high"):
        density = d.density
    car_policy = str(raw.get("car_policy", d.car_policy)).strip().lower()
    if car_policy not in ("cars", "pedestrian", "mixed"):
        car_policy = d.car_policy
    try:
        size = max(1, int(raw.get("size", d.size)))
    except (TypeError, ValueError):
        size = d.size
    return CityProfileParams(template=template, size=size, density=density, car_policy=car_policy)


def _parse_relationships(raw: dict | None) -> RelationshipParams:
    """Parse the optional `world.relationships` block (Wave E / EM-113).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back
    to its default individually (a malformed value never breaks the block)."""
    if not isinstance(raw, dict):
        return RelationshipParams()
    d = RelationshipParams()

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return RelationshipParams(
        friend_trust=_int("friend_trust", d.friend_trust),
        friend_interactions=_int("friend_interactions", d.friend_interactions),
        feud_trust=_int("feud_trust", d.feud_trust),
        partner_trust_threshold=_int(
            "partner_trust_threshold", d.partner_trust_threshold),
    )


def _parse_crime(raw: dict | None) -> CrimeParams:
    """Parse the optional `world.crime` block (EM-240).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back to
    its default individually (a malformed value never breaks the block). Mirrors
    `_parse_relationships`; int fields parse as int, float fields as float."""
    if not isinstance(raw, dict):
        return CrimeParams()
    d = CrimeParams()

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return CrimeParams(
        wanted_threshold=_int("wanted_threshold", d.wanted_threshold),
        detain_threshold=_int("detain_threshold", d.detain_threshold),
        notoriety_decay=_int("notoriety_decay", d.notoriety_decay),
        notoriety_per_extra_witness=_int(
            "notoriety_per_extra_witness", d.notoriety_per_extra_witness),
        rap_sheet_cap=_int("rap_sheet_cap", d.rap_sheet_cap),
        heist_max=_int("heist_max", d.heist_max),
        heist_min_target_credits=_int(
            "heist_min_target_credits", d.heist_min_target_credits),
        extort_max=_int("extort_max", d.extort_max),
        vandalize_blackout_ticks=_int(
            "vandalize_blackout_ticks", d.vandalize_blackout_ticks),
        vandalize_notoriety=_int("vandalize_notoriety", d.vandalize_notoriety),
        heist_notoriety=_int("heist_notoriety", d.heist_notoriety),
        extort_notoriety=_int("extort_notoriety", d.extort_notoriety),
        intimidate_notoriety=_int("intimidate_notoriety", d.intimidate_notoriety),
        deceive_notoriety=_int("deceive_notoriety", d.deceive_notoriety),
        intimidate_take_fraction=_float(
            "intimidate_take_fraction", d.intimidate_take_fraction),
        intimidate_max=_int("intimidate_max", d.intimidate_max),
        steal_notoriety=_int("steal_notoriety", d.steal_notoriety),
        arson_notoriety=_int("arson_notoriety", d.arson_notoriety),
        bribe_efficacy=_float("bribe_efficacy", d.bribe_efficacy),
        bribe_notoriety=_int("bribe_notoriety", d.bribe_notoriety),
        launder_cut=_float("launder_cut", d.launder_cut),
        launder_notoriety_reduction=_int(
            "launder_notoriety_reduction", d.launder_notoriety_reduction),
        investigate_notoriety=_int(
            "investigate_notoriety", d.investigate_notoriety),
        conspiracy_notoriety=_int("conspiracy_notoriety", d.conspiracy_notoriety),
        conspiracy_trust_seed=_int(
            "conspiracy_trust_seed", d.conspiracy_trust_seed),
        detain_sentence=_int("detain_sentence", d.detain_sentence),
        trial_sentence=_int("trial_sentence", d.trial_sentence),
        trial_fine=_int("trial_fine", d.trial_fine),
        acquittal_notoriety_relief=_int(
            "acquittal_notoriety_relief", d.acquittal_notoriety_relief),
        accuser_acquittal_penalty=_int(
            "accuser_acquittal_penalty", d.accuser_acquittal_penalty),
        released_notoriety_relief=_int(
            "released_notoriety_relief", d.released_notoriety_relief),
    )


def _parse_comm(raw: dict | None) -> CommunicationParams:
    """Parse the optional `world.comm` block (EM-250).
    Absent/empty/malformed -> engine-matching defaults (enabled stays FALSE, the
    inert Wave-O default). Each key falls back to its default individually (a
    malformed value never breaks the block). Mirrors `_parse_crime`; int fields
    parse as int, float fields as float, bool fields coerce with bool()."""
    if not isinstance(raw, dict):
        return CommunicationParams()
    d = CommunicationParams()

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return CommunicationParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        diffusion_chance=_float("diffusion_chance", d.diffusion_chance),
        max_diffusions=_int("max_diffusions", d.max_diffusions),
        half_life_ticks=_int("half_life_ticks", d.half_life_ticks),
        decay_ticks=_int("decay_ticks", d.decay_ticks),
        letter_cap=_int("letter_cap", d.letter_cap),
        held_meme_cap=_int("held_meme_cap", d.held_meme_cap),
        distortion_strength=_int("distortion_strength", d.distortion_strength),
        meme_images=bool(raw.get("meme_images", d.meme_images)),
        dominance_threshold=_int("dominance_threshold", d.dominance_threshold),
        camp_min_shared=_int("camp_min_shared", d.camp_min_shared),
        camp_min_size=_int("camp_min_size", d.camp_min_size),
    )


def _parse_needs(raw: dict | None) -> NeedsParams:
    """Parse the optional `world.needs` block (EM-229).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back to
    its default individually (a malformed value never breaks the block). Mirrors
    `_parse_crime`; all fields are floats. Decay rates clamp to >= 0 (a negative
    decay would REPLENISH a need each turn — never intended)."""
    if not isinstance(raw, dict):
        return NeedsParams()
    d = NeedsParams()

    def _float(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return NeedsParams(
        knowledge_decay_per_turn=max(0.0, _float(
            "knowledge_decay_per_turn", d.knowledge_decay_per_turn)),
        influence_decay_per_turn=max(0.0, _float(
            "influence_decay_per_turn", d.influence_decay_per_turn)),
        knowledge_salience_threshold=_float(
            "knowledge_salience_threshold", d.knowledge_salience_threshold),
        influence_salience_threshold=_float(
            "influence_salience_threshold", d.influence_salience_threshold),
    )


def _parse_memory(raw: dict | None) -> MemoryParams:
    """Parse the optional `world.memory` block (EM-233).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back to
    its default individually (a malformed value never breaks the block). Mirrors
    `_parse_needs`; all fields are ints clamped to >= 0 (a negative ceiling would
    consolidate every turn — never intended)."""
    if not isinstance(raw, dict):
        return MemoryParams()
    d = MemoryParams()

    def _int(key: str, default: int) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    return MemoryParams(
        consolidate_at=_int("consolidate_at", d.consolidate_at),
        consolidate_keep_recent=_int(
            "consolidate_keep_recent", d.consolidate_keep_recent),
        soul_cap=_int("soul_cap", d.soul_cap),
    )


def _parse_skills(raw: dict | None) -> SkillsParams:
    """Parse the optional `world.skills` block (EM-227).
    Absent/empty/malformed -> a SkillsParams with an EMPTY library (gates
    nothing — byte-identical pre-EM-227 + the em161 golden). Each key falls back
    to its default individually; the library/archetypes are deep-coerced so a
    malformed skill/archetype entry is dropped rather than breaking the block."""
    if not isinstance(raw, dict):
        return SkillsParams()
    d = SkillsParams()

    def _int(key: str, default: int) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    library: dict = {}
    raw_lib = raw.get("library")
    if isinstance(raw_lib, dict):
        for name, spec in raw_lib.items():
            if not isinstance(name, str) or not isinstance(spec, dict):
                continue
            gates = spec.get("gates")
            gate_list = [str(g) for g in gates if isinstance(g, str)] \
                if isinstance(gates, list) else []
            try:
                min_level = max(1, int(spec.get("min_level", 1)))
            except (TypeError, ValueError):
                min_level = 1
            library[name] = {"gates": gate_list, "min_level": min_level}

    archetypes: dict = {}
    raw_arch = raw.get("archetypes")
    if isinstance(raw_arch, dict):
        for arch, table in raw_arch.items():
            if not isinstance(arch, str) or not isinstance(table, dict):
                continue
            seeded: dict = {}
            for skill, level in table.items():
                if not isinstance(skill, str):
                    continue
                try:
                    lvl = max(0, int(level))
                except (TypeError, ValueError):
                    continue
                if lvl > 0:
                    seeded[skill] = lvl
            if seeded:
                archetypes[arch] = seeded

    return SkillsParams(
        library=library,
        archetypes=archetypes,
        xp_per_use=_int("xp_per_use", d.xp_per_use),
        xp_per_level=max(1, _int("xp_per_level", d.xp_per_level)),
        max_level=_int("max_level", d.max_level),
    )


def _parse_cooperation(raw: dict | None) -> CooperationParams:
    """Parse the optional `world.cooperation` block (EM-231).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back to
    its default individually (a malformed value never breaks the block). Mirrors
    `_parse_memory`; the bonus step clamps to >= 1 (a non-positive joint build
    would never advance — never intended)."""
    if not isinstance(raw, dict):
        return CooperationParams()
    d = CooperationParams()
    try:
        bonus = max(1, int(raw.get("co_build_bonus_step", d.co_build_bonus_step)))
    except (TypeError, ValueError):
        bonus = d.co_build_bonus_step
    return CooperationParams(co_build_bonus_step=bonus)


def _parse_victory_arch(raw: dict | None) -> VictoryArchParams:
    """Parse the optional `world.victory_arch` block (EM-232).
    Absent/empty/malformed -> engine-matching defaults (every_n_ticks 0 ⇒ OFF, a
    complete no-op). Each key falls back to its default individually (a malformed
    value never breaks the block). Mirrors `_parse_cooperation`; cadence/award/
    bonus clamp to >= 0 and top_n to >= 1 (a non-positive top_n would award
    nobody — never intended), so a tampered value can never crash a cycle."""
    if not isinstance(raw, dict):
        return VictoryArchParams()
    d = VictoryArchParams()

    def _int_nonneg(key, fallback):
        try:
            return max(0, int(raw.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    try:
        top_n = max(1, int(raw.get("top_n", d.top_n)))
    except (TypeError, ValueError):
        top_n = d.top_n
    try:
        influence = max(0.0, float(raw.get("influence_replenish", d.influence_replenish)))
    except (TypeError, ValueError):
        influence = d.influence_replenish
    return VictoryArchParams(
        every_n_ticks=_int_nonneg("every_n_ticks", d.every_n_ticks),
        award=_int_nonneg("award", d.award),
        top_n=top_n,
        reputation_bonus=_int_nonneg("reputation_bonus", d.reputation_bonus),
        influence_replenish=influence,
    )


def _parse_boost(raw: dict | None) -> BoostParams:
    """Parse the optional `world.boost` block (EM-235).
    Absent/empty/malformed -> engine-matching defaults (cost 0 ⇒ OFF, a complete
    no-op). Each key falls back to its default individually (a malformed value
    never breaks the block). Mirrors `_parse_victory_arch`; cost clamps to >= 0
    and max_per_round to >= 1 (a non-positive cap would forbid every buy — never
    intended), so a tampered value can never crash a buy or the scheduler."""
    if not isinstance(raw, dict):
        return BoostParams()
    d = BoostParams()

    def _int_nonneg(key, fallback):
        try:
            return max(0, int(raw.get(key, fallback)))
        except (TypeError, ValueError):
            return fallback

    try:
        max_per_round = max(1, int(raw.get("max_per_round", d.max_per_round)))
    except (TypeError, ValueError):
        max_per_round = d.max_per_round
    return BoostParams(
        cost=_int_nonneg("cost", d.cost),
        max_per_round=max_per_round,
    )


def _parse_constitution(raw: dict | None) -> ConstitutionParams:
    """Parse the optional `world.constitution` block (EM-236).
    Absent/empty/malformed -> engine-matching defaults (the un-amended world is a
    complete no-op). Each key falls back to its default individually (a malformed
    value never breaks the block). ratify_threshold clamps to (0, 1] (a value <= 0
    would ratify on the first vote; > 1 would be impossible to pass — never
    intended), influence_replenish clamps to >= 0."""
    if not isinstance(raw, dict):
        return ConstitutionParams()
    d = ConstitutionParams()
    try:
        thr = float(raw.get("ratify_threshold", d.ratify_threshold))
        if not (0.0 < thr <= 1.0):
            thr = d.ratify_threshold
    except (TypeError, ValueError):
        thr = d.ratify_threshold
    try:
        infl = max(0.0, float(raw.get("influence_replenish", d.influence_replenish)))
    except (TypeError, ValueError):
        infl = d.influence_replenish
    return ConstitutionParams(ratify_threshold=thr, influence_replenish=infl)


def _parse_governance(raw: dict | None) -> GovernanceParams:
    """Parse the optional `world.governance` block (EM-203).
    Absent/empty/malformed -> engine-matching defaults (renewal_cooldown_ticks 0
    == no cooldown == pre-EM-203 behavior). The single key falls back to its
    default individually and clamps to >= 0 (a negative/malformed value never
    breaks the block)."""
    if not isinstance(raw, dict):
        return GovernanceParams()
    d = GovernanceParams()
    try:
        cooldown = max(0, int(raw.get("renewal_cooldown_ticks",
                                      d.renewal_cooldown_ticks)))
    except (TypeError, ValueError):
        cooldown = d.renewal_cooldown_ticks
    return GovernanceParams(renewal_cooldown_ticks=cooldown)


def _parse_children(raw: dict | None) -> ChildrenParams:
    """Parse the optional `world.children` block (Wave E / EM-114).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back
    to its default individually; counts/costs clamp to >= 0 and birth_chance
    clamps to [0, 1] (a malformed value never breaks the block)."""
    if not isinstance(raw, dict):
        return ChildrenParams()
    d = ChildrenParams()

    def _nonneg_int(key: str, default: int) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _unit_float(key: str, default: float) -> float:
        try:
            return min(1.0, max(0.0, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    return ChildrenParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        max_population=_nonneg_int("max_population", d.max_population),
        birth_cost_credits=_nonneg_int("birth_cost_credits", d.birth_cost_credits),
        birth_chance=_unit_float("birth_chance", d.birth_chance),
        pair_cooldown_ticks=_nonneg_int("pair_cooldown_ticks", d.pair_cooldown_ticks),
    )


def _parse_generations(raw: dict | None) -> GenerationsParams:
    """Parse the optional `world.generations` block (EM-126).
    Absent/empty/malformed -> engine-matching defaults (enabled=False == zero
    behavioral change == pre-EM-126: no aging, no inheritance, EM-114 children
    untouched). Each key falls back to its default individually; the round
    thresholds clamp to >= 0 and elder_after is held >= child_until (a malformed/
    inverted pair never produces an impossible 'never adult' band)."""
    if not isinstance(raw, dict):
        return GenerationsParams()
    d = GenerationsParams()

    def _nonneg_int(key: str, default: int) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    child_until = _nonneg_int("child_until", d.child_until)
    elder_after = max(child_until, _nonneg_int("elder_after", d.elder_after))
    return GenerationsParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        child_until=child_until,
        elder_after=elder_after,
        inherit_credits=bool(raw.get("inherit_credits", d.inherit_credits)),
        inherit_relationships=bool(
            raw.get("inherit_relationships", d.inherit_relationships)),
    )


def _parse_factions(raw: dict | None) -> FactionParams:
    """Parse the optional `world.factions` block (Wave E / EM-120).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back
    to its default individually; faction_min_size clamps to >= 1 (a malformed
    value never breaks the block)."""
    if not isinstance(raw, dict):
        return FactionParams()
    d = FactionParams()

    def _int(key: str, default: int) -> int:
        try:
            return int(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return FactionParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        faction_trust=_int("faction_trust", d.faction_trust),
        faction_min_size=max(1, _int("faction_min_size", d.faction_min_size)),
    )


def _parse_miracles(raw: dict | None) -> MiracleParams:
    """Parse the optional `world.miracles` block (Wave E / EM-184).
    Absent/empty/malformed -> engine-matching defaults. Each key falls back
    to its default individually; bonuses clamp to >= 0, durations to >= 1
    day, and the decay factor to [0, 1] (a malformed value never breaks
    the block)."""
    if not isinstance(raw, dict):
        return MiracleParams()
    d = MiracleParams()

    def _nonneg_int(key: str, default: int) -> int:
        try:
            return max(0, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _days(key: str, default: int) -> int:
        try:
            return max(1, int(raw.get(key, default)))
        except (TypeError, ValueError):
            return default

    def _unit_float(key: str, default: float) -> float:
        try:
            return min(1.0, max(0.0, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    return MiracleParams(
        enabled=bool(raw.get("enabled", d.enabled)),
        rain_forage_bonus=_nonneg_int("rain_forage_bonus", d.rain_forage_bonus),
        rain_days=_days("rain_days", d.rain_days),
        harvest_decay_factor=_unit_float(
            "harvest_decay_factor", d.harvest_decay_factor),
        harvest_days=_days("harvest_days", d.harvest_days),
        calm_trust_bonus=_nonneg_int("calm_trust_bonus", d.calm_trust_bonus),
    )


# Wave D2 / EM-158 — valid agent cadence tiers (mirrors World.CADENCE_TIERS;
# kept literal here so the loader stays engine-import-free).
_VALID_CADENCE_TIERS = ("protagonist", "supporting", "background")


def _norm_cadence_tier(value: Any) -> str:
    """Normalize an agent entry's optional cadence_tier; anything unknown or
    absent falls back to protagonist (the zero-behavior-change default)."""
    tier = str(value or "").strip().lower()
    return tier if tier in _VALID_CADENCE_TIERS else "protagonist"


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
    # Adaptive Lane Routing (spec 2026-07-07): the sorting list lives in
    # config/lanes.yaml, NOT world.yaml. On a FRESH load `w` has no
    # `adaptive_routing` key, so we read lanes.yaml from the config dir. On a
    # fork/replay REPARSE, app.py feeds the parent's config_json `world` block
    # (which DID carry the serialized `adaptive_routing`) with config_dir=None —
    # so the in-block value takes precedence and the routing config round-trips.
    ar_raw = w.get("adaptive_routing")
    if ar_raw is None:
        ar_raw = _load_lanes_yaml_adaptive_routing(config_dir)
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
        road_build_energy_cost=float(w.get("road_build_energy_cost", 8)),
        # EM-199 — multi-action turns cap; absent ⇒ 4 (move+fund+say+one more).
        max_actions_per_turn=int(w.get("max_actions_per_turn", 4)),
        # Wave D2 / EM-170 — absent/0 ⇒ guard disabled (today's behavior).
        turn_llm_budget_seconds=float(w.get("turn_llm_budget_seconds", 0) or 0),
        # Wave D3 / EM-187 — absent ⇒ resume-on-boot ON (the shipped default).
        resume_on_boot=bool(w.get("resume_on_boot", True)),
        # W15 / EM-155 — optional deterministic city seed; absent → 1337.
        city_seed=int(w.get("city_seed", 1337)),
        starving_warn_threshold=float(w.get("starving_warn_threshold", 25)),
        auto_pause_on_extinction=bool(w.get("auto_pause_on_extinction", True)),
        auto_pause_on_provider_errors=bool(w.get("auto_pause_on_provider_errors", True)),
        provider_error_pause_threshold=int(w.get("provider_error_pause_threshold", 8)),
        snapshot_interval_ticks=int(w.get("snapshot_interval_ticks", 25)),
        db_path=_resolve_db_path(_interpolate(w.get("db_path", ":memory:")), config_dir),
        usage_caps=_parse_usage_caps(w.get("usage_caps")),
        buildings=_parse_buildings(w.get("buildings")),
        spawn=_parse_spawn(w.get("spawn")),
        cache=_parse_cache(w.get("cache")),
        animals=_parse_animals(w.get("animals")),
        props=_parse_props(w.get("props")),
        image_gen=_parse_image_gen(w.get("image_gen")),
        narrator=_parse_narrator(w.get("narrator")),
        blackout_ticks=int(w.get("blackout_ticks", 10)),
        commitments=_parse_commitments(w.get("commitments")),
        reflection=_parse_reflection(w.get("reflection")),
        procgen=_parse_procgen(w.get("procgen")),
        cadence=_parse_cadence(w.get("cadence")),
        memory_retrieval=_parse_memory_retrieval(w.get("memory_retrieval")),
        lane_failover=_parse_lane_failover(w.get("lane_failover")),
        overflow_lane=_parse_overflow_lane(w.get("overflow_lane")),
        adaptive_routing=_parse_adaptive_routing(ar_raw),
        cap_governor=_parse_cap_governor(w.get("cap_governor")),
        relationships=_parse_relationships(w.get("relationships")),
        crime=_parse_crime(w.get("crime")),
        comm=_parse_comm(w.get("comm")),
        needs=_parse_needs(w.get("needs")),
        memory=_parse_memory(w.get("memory")),
        skills=_parse_skills(w.get("skills")),
        cooperation=_parse_cooperation(w.get("cooperation")),
        victory_arch=_parse_victory_arch(w.get("victory_arch")),
        boost=_parse_boost(w.get("boost")),
        constitution=_parse_constitution(w.get("constitution")),
        governance=_parse_governance(w.get("governance")),
        children=_parse_children(w.get("children")),
        generations=_parse_generations(w.get("generations")),
        factions=_parse_factions(w.get("factions")),
        planning=_parse_planning(w.get("planning")),
        universalization=_parse_universalization(w.get("universalization")),
        coherence=_parse_coherence(w.get("coherence")),
        miracles=_parse_miracles(w.get("miracles")),
        district_growth=_parse_district_growth(w.get("district_growth")),
        city=_parse_city_profile(w.get("city")),
    )

    places = [
        PlaceConfig(
            id=p["id"],
            name=p["name"],
            x=int(p["x"]),
            y=int(p["y"]),
            kind=p["kind"],
            description=p.get("description", ""),
            # Wave C / EM-147 — optional district tag; absent → None.
            district=(str(p["district"]) if p.get("district") is not None else None),
            # EM-123 — optional neighborhood/zone overrides; absent → None.
            neighborhood_id=(str(p["neighborhood_id"]) if p.get("neighborhood_id") is not None else None),
            zone_kind=(str(p["zone_kind"]) if p.get("zone_kind") is not None else None),
        )
        for p in raw.get("places", [])
    ]

    agents = [
        AgentConfig(
            name=a["name"],
            personality=a.get("personality", ""),
            profile=a["profile"],
            location=a.get("location", places[0].id if places else "plaza"),
            # Wave D2 / EM-158 — optional per-agent tier; absent → protagonist.
            cadence_tier=_norm_cadence_tier(a.get("cadence_tier")),
        )
        for a in raw.get("agents", [])
    ]

    return params, places, agents


# ──────────────────────────────────────────────────────────────────────────────
# EM-175 — agent_count roster padding
# ──────────────────────────────────────────────────────────────────────────────

_CITIZEN_PERSONALITY = (
    "An ordinary citizen of the town; even-keeled and adaptable, works a bit, "
    "chats a bit, and mostly just gets by."
)


def _pad_agents(
    agents: list[AgentConfig],
    agent_count: int,
    places: list[PlaceConfig],
    profiles: list[ModelProfile],
    personas: list[dict],
) -> list[AgentConfig]:
    """EM-175 — make `world.agent_count` real: pad, never truncate.

    config/world.yaml has always promised agent_count is "used if `agents:`
    not fully specified", but the padding was never implemented — the world
    booted exactly the hand-listed cast. Rules, as shipped:

      - len(agents) >= agent_count  ⇒  the list is returned UNCHANGED. The
        hand-authored `agents:` list always wins; agent_count never truncates.
      - Otherwise the roster pads from the persona library
        (config/personas.yaml, EM-092). Cards whose name collides
        (case-insensitively) with a listed agent are skipped. Each padded
        agent takes the card's name + personality, the card's
        suggested_profile when it names a registered profile (else a
        round-robin pick across the non-mock profiles), the default place
        (plaza when it exists, else the first place), and
        cadence_tier "supporting" — extras at supporting keeps the free-tier
        turn economics sane, while the hand-listed cast keeps whatever tier
        it declares (default protagonist).
      - If the library runs short, numbered citizens (Citizen-N, neutral
        personality, round-robin across non-mock profiles) fill the rest, so
        agent_count is ALWAYS honored.

    Called by load_config() BEFORE the mock profile_override remap, so the
    test suite's forced-mock path applies to padded agents too.
    """
    if agent_count <= len(agents):
        return agents

    place_ids = [p.id for p in places]
    default_loc = (
        "plaza" if "plaza" in place_ids
        else (place_ids[0] if place_ids else "plaza")
    )

    profile_names = {p.name for p in profiles}
    # Round-robin lanes for cards without a usable suggestion + Citizen-N fill.
    # EM-222 — the dedicated `embed` profile is an embeddings model (bge-m3), NOT
    # a chat lane; never round-robin/assign an agent onto it.
    rr_lanes = [
        p.name for p in profiles if p.adapter != "mock" and p.name != "embed"
    ] or ["mock"]
    rr_cursor = 0

    def _pick_profile(suggested: str = "") -> str:
        nonlocal rr_cursor
        if suggested and suggested in profile_names:
            return suggested
        lane = rr_lanes[rr_cursor % len(rr_lanes)]
        rr_cursor += 1
        return lane

    used_names = {a.name.strip().lower() for a in agents}
    out = list(agents)

    for card in personas:
        if len(out) >= agent_count:
            break
        name = str(card.get("name") or "").strip()
        if not name or name.lower() in used_names:
            continue
        used_names.add(name.lower())
        out.append(AgentConfig(
            name=name,
            personality=str(card.get("personality") or ""),
            profile=_pick_profile(str(card.get("suggested_profile") or "")),
            location=default_loc,
            cadence_tier="supporting",
        ))

    n = 1
    while len(out) < agent_count:
        name = f"Citizen-{n}"
        n += 1
        if name.lower() in used_names:
            continue
        used_names.add(name.lower())
        out.append(AgentConfig(
            name=name,
            personality=_CITIZEN_PERSONALITY,
            profile=_pick_profile(),
            location=default_loc,
            cadence_tier="supporting",
        ))

    return out


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

    # EM-175 — honor world.agent_count: pad the roster from the persona
    # library (then Citizen-N) when `agents:` lists fewer; never truncate.
    # Runs BEFORE the mock override below so padded agents are remapped too.
    agents = _pad_agents(
        agents, world_params.agent_count, places, profiles, load_personas(),
    )

    # If profile_override == "mock", remap all agents to mock profile
    if profile_override == "mock":
        agents = [
            AgentConfig(
                name=a.name,
                personality=a.personality,
                profile="mock",
                location=a.location,
                cadence_tier=a.cadence_tier,  # Wave D2 / EM-158 — preserved
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
            # EM-240 — additive persona schema; unknown/absent → lawful/citizen.
            "disposition": (str(c.get("disposition") or "").strip().lower()
                            if str(c.get("disposition") or "").strip().lower()
                            in ("lawful", "opportunist", "criminal") else "lawful"),
            "role": (str(c.get("role") or "").strip().lower()
                     if str(c.get("role") or "").strip().lower()
                     in ("citizen", "enforcer") else "citizen"),
        })
    return out

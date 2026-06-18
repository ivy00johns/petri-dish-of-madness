"""
Wave D2 / B3 gate tests — prompt diet (EM-161), cache-key normalization
(EM-162), and tier-gated world-mutating tools (EM-163).

Contract under test: contracts/wave-d2.md §B3.
  - EM-161 (supporting + background; protagonists keep today's full prompt
    BYTE-FOR-BYTE — proven against the pre-diet capture fixture):
    relationships capped to the top-8 by |trust|; open_projects + the move_to
    place menu scoped to the agent's current district + adjacent (ADJACENCY
    RULE: own district + the always-visible "core" district; un-districted
    places always visible; an agent at an un-districted place gets the full
    map). Background only: the decision-trace instruction block is dropped
    and memory_window shrinks 12→8. The diet narrows the MENU, never the
    rules — _validate_world still accepts any valid place.
  - EM-162 (background only): energy renders bucketed to 10s ("~70") and the
    tick line floors to the day, so quiet rounds assemble byte-identical
    prompts and the router's sha1 decision cache hits. forget() untouched.
    (Wave D3 / EM-171 supersedes the day-floored tick: background prompts now
    carry no tick line at all — see test_wave_d3_cache.py.)
  - EM-163: propose_project / build_step / contribute_funds / propose_rule
    gate to protagonist+supporting at RESOLUTION time (the billboard
    location-gate pattern; EM-108 = prompt-only gating is not enforcement);
    the background menu omits them so menu and resolution agree. Vote stays
    for everyone — only PROPOSING gates.

PROMPT-SIZE GUARD (documented bound): a background prompt in the 25-agent
fixture must stay under 5_000 chars (~1_250 tokens by the char/4 heuristic) —
comfortable headroom inside the 8K-token cerebras lane even with the
completion budget on top. Measured on this fixture: pre-diet background
5_120 chars; post-diet ~3_263 chars (supporting ~4_256; protagonist 5_158,
byte-identical to pre-diet).

Wave K / EM-217+218 NOTE: the protagonist (full) prompt gained two lines — the
propose_project guidance now surfaces the BUILD_TYPES menu + the optional `place`
arg (EM-182/217), and a `place_prop` offering (EM-218). Both ride only the
protagonist/supporting menus (place_prop is reflex/un-tier-gated; propose_project
stays tier-gated off background), so BACKGROUND prompts are unchanged and the
size guard below is unaffected. The em161_protagonist_prompt_pre_diet.txt capture
was regenerated for this intended change (protagonist ~6_862 chars); it still
guards against UNINTENDED protagonist-prompt drift.

Deterministic and offline (scripted fakes, ':memory:' DBs, no network).
House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from petridish.engine.world import (
    World, AgentState, PlaceState, RelationshipState, RuleState, Building,
)
from petridish.config.loader import ModelProfile, WorldConfig, WorldParams
from petridish.agents.runtime import (
    AgentRuntime, _assemble_context, _validate_schema,
)
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


FIXTURE_DIR = Path(__file__).parent / "fixtures"
PRE_DIET_CAPTURE = FIXTURE_DIR / "em161_protagonist_prompt_pre_diet.txt"

IDLE = {"action": "idle", "args": {}}


# ──────────────────────────────────────────────────────────────────────────────
# Deterministic 25-agent city fixture (the EM-161/162/163 proof surface).
# Mirrors the config/world.yaml city grid: 15 places over 5 districts.
# ──────────────────────────────────────────────────────────────────────────────

_CITY_PLACES: list[tuple[str, str, int, int, str, str]] = [
    ("plaza", "Central Plaza", 500, 500, "social", "core"),
    ("well", "Fountain Court", 500, 303, "social", "core"),
    ("market", "Market Hall", 697, 303, "work", "market"),
    ("forge", "The Steelworks", 894, 303, "work", "market"),
    ("workshop", "Tinker's Workshop", 894, 500, "work", "market"),
    ("townhall", "City Hall", 106, 106, "governance", "civic"),
    ("archive", "The Records Office", 303, 106, "governance", "civic"),
    ("home", "Hearth House", 106, 697, "home", "residential"),
    ("rosehip_cottage", "Rosehip Walk-up", 106, 894, "home", "residential"),
    ("mossy_row", "Mossy Row Flats", 303, 894, "home", "residential"),
    ("lantern_loft", "Lantern Lofts", 303, 697, "home", "residential"),
    ("commons", "The Commons Park", 697, 697, "wild", "farm"),
    ("willow_pond", "Willow Pond Park", 697, 894, "wild", "farm"),
    ("orchard", "Orchard Green", 894, 894, "wild", "farm"),
    ("farmstead", "Sunfall Depot", 894, 697, "work", "farm"),
]

# The market-district agent's EM-161 horizon: own district + core.
_MARKET_VISIBLE_PLACES = ["plaza", "well", "market", "forge", "workshop"]


def _city_places() -> list[PlaceState]:
    return [
        PlaceState(id=i, name=n, x=x, y=y, kind=k, district=d)
        for (i, n, x, y, k, d) in _CITY_PLACES
    ]


def _city_params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        memory_window=12,
        snapshot_interval_ticks=100,
    )
    base.update(overrides)
    return WorldParams(**base)


def _build_city_world(n_agents: int = 25) -> World:
    """A deterministic 25-agent world at the city grid: hero (protagonist),
    sup_01 (supporting) and bg_01 (background) all stand at the MARKET (a
    non-core district, so district scoping is observable); 22 fillers spread
    across all 15 places. hero/sup_01/bg_01 each hold relationships to ALL 24
    others with pairwise-distinct |trust| values; 6 open projects span 5
    districts; one active + one proposed rule exist."""
    place_ids = [p[0] for p in _CITY_PLACES]
    agents = [
        AgentState(id="hero", name="Hero", personality="Bold, curious, tireless.",
                   profile="mock", location="market", energy=63.7, credits=34,
                   cadence_tier="protagonist"),
        AgentState(id="sup_01", name="Supporter", personality="Steady and patient.",
                   profile="mock", location="market", energy=71.3, credits=18,
                   cadence_tier="supporting"),
        AgentState(id="bg_01", name="Bystander", personality="Quiet, watchful.",
                   profile="mock", location="market", energy=78.0, credits=12,
                   cadence_tier="background"),
    ]
    for i in range(n_agents - 3):
        agents.append(AgentState(
            id=f"filler_{i:02d}", name=f"Filler{i:02d}", personality="",
            profile="mock", location=place_ids[i % len(place_ids)],
            energy=40.0 + (i % 5) * 10, credits=10 + i,
            cadence_tier="background"))

    world = World(params=_city_params(), places=_city_places(), agents=agents)
    world.tick = 47  # day 2 with turns_per_day=20

    # Relationships: each named agent → all 24 others; trust = ((i*13) % 201)
    # - 100 yields 24 pairwise-distinct |trust| values (top-8 is unambiguous).
    rel_types = ("ally", "rival", "neutral", "friend", "enemy")
    for holder in ("hero", "sup_01", "bg_01"):
        h = world.agents[holder]
        others = [a for a in world.agents.values() if a.id != holder]
        for i, other in enumerate(others):
            h.relationships[other.id] = RelationshipState(
                type=rel_types[i % 5], trust=((i * 13) % 201) - 100,
                interactions=i)

    # Six open projects across five districts. From the market the EM-161
    # horizon (market + core) sees b1/b2/b6 and NOT b3/b4/b5.
    specs = [
        ("b1", "Spice Stall", "market", "planned", 10, 50),
        ("b2", "Plaza Clocktower", "plaza", "under_construction", 60, 60),
        ("b3", "Commons Garden", "commons", "planned", 0, 40),
        ("b4", "Hall Annex", "townhall", "under_construction", 30, 30),
        ("b5", "Hearth Library", "home", "planned", 5, 80),
        ("b6", "Market Awning", "market", "under_construction", 20, 20),
    ]
    for bid, name, loc, status, have, need in specs:
        world.buildings[bid] = Building(
            id=bid, name=name, kind="workshop", location=loc, status=status,
            funds_committed=have, funds_required=need)

    world.rules["rule_active_1"] = RuleState(
        id="rule_active_1", effect="ubi", text="Daily bread for all",
        proposer_id="hero", status="active")
    world.rules["rule_prop_1"] = RuleState(
        id="rule_prop_1", effect="ban_stealing", text="No taking what is not yours",
        proposer_id="hero", status="proposed")
    return world


def _events(n: int = 15) -> list[dict]:
    return [
        {"tick": t, "text": f"event {t} happened", "kind": "agent_action", "seq": t}
        for t in range(1, n + 1)
    ]


def _system_prompt(world: World, agent: AgentState,
                   events: list[dict] | None = None) -> str:
    msgs = _assemble_context(
        agent, world, _events() if events is None else events, world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _capture_fixture() -> dict:
    """Regenerate the pre-diet capture (run ONCE against pre-diet code; the
    committed fixture is the regression surface). Returns sizes for reports."""
    world = _build_city_world()
    hero_prompt = _system_prompt(world, world.agents["hero"])
    bg_prompt = _system_prompt(world, world.agents["bg_01"])
    FIXTURE_DIR.mkdir(exist_ok=True)
    PRE_DIET_CAPTURE.write_text(hero_prompt, encoding="utf-8")
    return {"hero_chars": len(hero_prompt), "bg_chars": len(bg_prompt)}


# ──────────────────────────────────────────────────────────────────────────────
# Loop harness for the resolution-time rejection proof (the test_wave_d2_cadence
# ByAgentProvider idiom: per-agent scripts + prompt capture).
# ──────────────────────────────────────────────────────────────────────────────

class ByAgentProvider:
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list] | None = None):
        self._scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []

    def set_world(self, world: object) -> None:
        self._world = world

    @staticmethod
    def _extract(messages: list[dict]) -> tuple[str, str]:
        agent_id, system = "unknown", ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                for line in system.split("\n"):
                    line = line.strip()
                    if line.startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
        return agent_id, system

    async def chat(self, messages, *, max_tokens, temperature):
        agent_id, system = self._extract(messages)
        self.prompts.append((agent_id, system))
        script = None
        for key, entries in self._scripts.items():
            if key in agent_id:
                script = entries
                break
        if script is None:
            script = [IDLE]
        i = min(self._pos.get(agent_id, 0), len(script) - 1)
        self._pos[agent_id] = i + 1
        return json.dumps(script[i])


def _make_loop(agents: list[AgentState], scripts: dict[str, list] | None = None,
               places: list[PlaceState] | None = None):
    params = _city_params()
    world = World(params=params, places=places or _city_places(), agents=agents)
    provider = ByAgentProvider(scripts)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": provider},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: None)
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    return loop, world, repo, runtime, provider


# ──────────────────────────────────────────────────────────────────────────────
# 1. EM-161 — protagonists keep today's full prompt BYTE-FOR-BYTE
# ──────────────────────────────────────────────────────────────────────────────

def test_protagonist_prompt_byte_identical_to_pre_diet_capture():
    """THE regression proof: the protagonist prompt in the 25-agent fixture is
    byte-identical to the capture taken from pre-diet code (same fixture)."""
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["hero"])
    expected = PRE_DIET_CAPTURE.read_text(encoding="utf-8")
    assert prompt == expected


def test_protagonist_keeps_full_relationships_window_and_map():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["hero"])
    # All 24 relationship lines survive (Filler21 holds the smallest |trust|).
    assert prompt.count("trust=") == 24
    assert "Filler21" in prompt
    # Full 15-place move_to menu.
    all_places = ", ".join(p[0] for p in _CITY_PLACES)
    assert f"move_to (place) - go to one of: {all_places}" in prompt
    # All 6 open projects listed.
    for bid in ("b1", "b2", "b3", "b4", "b5", "b6"):
        assert f"id={bid} " in prompt
    # Full 12-event memory window (events 4..15 of the 15 fed).
    assert "event 4 happened" in prompt
    assert "event 3 happened" not in prompt
    # Trace instruction block intact; exact energy + tick.
    assert "ALSO include (in the SAME json object" in prompt
    assert "Energy: 63.7/100" in prompt
    assert "Tick: 47" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# 2. EM-161 — the background diet cuts (each one provable in the prompt text)
# ──────────────────────────────────────────────────────────────────────────────

def test_background_relationships_capped_to_top8_by_abs_trust():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    assert prompt.count("trust=") == 8
    # bg_01's others list = [hero, sup_01, filler_00..filler_21]; the top-8 by
    # |trust| are i in {0,15,16,1,14,17,2,13}.
    for kept in ("Hero", "Supporter", "Filler13", "Filler14", "Filler12",
                 "Filler15", "Filler00", "Filler11"):
        assert f"  {kept}: " in prompt, f"expected top-8 relationship {kept}"
    assert "Filler21:" not in prompt  # |trust|=2 — dieted away


def test_background_move_to_menu_scoped_to_current_plus_core_district():
    """ADJACENCY RULE: own district + the always-visible core district."""
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    menu = ", ".join(_MARKET_VISIBLE_PLACES)
    assert f"move_to (place) - go to one of: {menu}" in prompt
    assert "townhall" not in prompt.split("VALID ACTIONS")[1].split("\n")[2]


def test_background_open_projects_scoped_to_district_horizon():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    projects = prompt.split("ACTIVE PROJECTS")[1].split("=== ACTIVE RULES")[0]
    for visible in ("b1", "b2", "b6"):
        assert f"id={visible} " in projects
    for hidden in ("b3", "b4", "b5"):
        assert f"id={hidden} " not in projects


def test_background_trace_block_dropped_and_parser_tolerates_it():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    assert "ALSO include (in the SAME json object" not in prompt
    assert "perceived_summary" not in prompt
    assert "memories_used" not in prompt
    assert '"reasoning"' not in prompt
    # Commitment tracking (EM-079) is NOT the trace block — it stays.
    assert '"commitment"' in prompt
    # The parser tolerates absent trace fields (they are optional in
    # ACTION_SCHEMA) — a minimal trace-less response validates clean.
    assert _validate_schema({"action": "idle", "args": {}}) is None
    assert _validate_schema(
        {"action": "say", "args": {"text": "hi"}, "thought": "x"}) is None


def test_background_memory_window_shrinks_to_8():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    assert "event 8 happened" in prompt    # newest 8 of 15: events 8..15
    assert "event 7 happened" not in prompt


def test_diet_disabled_at_undistricted_place():
    """An agent standing at an un-districted place gets the FULL map — the
    diet must never hide the whole world when district data is absent."""
    places = _city_places() + [PlaceState(id="outpost", name="Outpost",
                                          x=0, y=0, kind="wild")]
    world = _build_city_world()
    world.places["outpost"] = places[-1]
    bg = world.agents["bg_01"]
    bg.location = "outpost"
    prompt = _system_prompt(world, bg)
    menu_line = next(l for l in prompt.split("\n") if "move_to (place)" in l)
    for pid in [p[0] for p in _CITY_PLACES] + ["outpost"]:
        assert pid in menu_line


# ──────────────────────────────────────────────────────────────────────────────
# 3. EM-161 — supporting tier: capped/scoped, but keeps trace + window + exact
#    energy/tick (the EM-162 normalization is background-only)
# ──────────────────────────────────────────────────────────────────────────────

def test_supporting_diet_caps_and_scopes_but_keeps_trace_and_window():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["sup_01"])
    # Capped relationships + scoped move_to/projects (the shared diet).
    assert prompt.count("trust=") == 8
    menu = ", ".join(_MARKET_VISIBLE_PLACES)
    assert f"move_to (place) - go to one of: {menu}" in prompt
    projects = prompt.split("ACTIVE PROJECTS")[1].split("=== ACTIVE RULES")[0]
    assert "id=b3 " not in projects and "id=b2 " in projects
    # Background-only cuts do NOT apply.
    assert "ALSO include (in the SAME json object" in prompt
    assert "event 4 happened" in prompt          # full 12-event window
    assert "Energy: 71.3/100" in prompt           # exact, not bucketed
    assert "Tick: 47" in prompt                   # exact, not day-floored
    # Supporting KEEPS the gated proposal tools (gate is background-only).
    assert "propose_project (" in prompt


# ──────────────────────────────────────────────────────────────────────────────
# 4. EM-161 — prompt-size guard (documented bound: < 5000 chars ≈ 1250 tokens)
# ──────────────────────────────────────────────────────────────────────────────

def test_background_prompt_size_guard_25_agents():
    """The 8K cerebras lane backstop: a background prompt in the 25-agent city
    fixture stays under 5_000 chars (~1_250 tokens via the char/4 heuristic —
    generous headroom for the completion budget). Pre-diet this fixture
    assembled 5_120 chars; post-diet ~3_263."""
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    assert len(prompt) < 5_000, f"background prompt too fat: {len(prompt)} chars"


# ──────────────────────────────────────────────────────────────────────────────
# 5. EM-162 — quiet background rounds assemble BYTE-IDENTICAL prompts and the
#    router decision cache hits
# ──────────────────────────────────────────────────────────────────────────────

def _quiet_world() -> World:
    """A lone background agent — nothing co-located, fixed memory buffer."""
    agents = [AgentState(id="bg_solo", name="Solo", personality="",
                         profile="lane", location="home", energy=78.0,
                         credits=12, cadence_tier="background")]
    world = World(params=_city_params(), places=_city_places(), agents=agents)
    world.tick = 41  # day 2
    return world


def test_background_energy_bucketed_and_tick_floored():
    world = _quiet_world()
    prompt = _system_prompt(world, world.agents["bg_solo"], events=[])
    assert "Energy: ~70/100" in prompt
    assert "Energy ~70/100 — at 0 you start DYING." in prompt
    # Wave D3 / EM-171 — STRICTER than the EM-162 day-floored render this
    # test originally guarded ("Tick: day 2"): the day line still missed the
    # cache (a 25-turn round spans >1 in-world day, so consecutive background
    # due turns never share a day), so background prompts now carry NO tick
    # line at all. See tests/test_wave_d3_cache.py for the full EM-171 suite.
    assert "Tick:" not in prompt
    assert "Tick: 41" not in prompt


def test_background_colocated_energy_bucketed():
    world = _build_city_world()
    prompt = _system_prompt(world, world.agents["bg_01"])
    # hero (63.7) and sup_01 (71.3) render bucketed in bg_01's co-located block.
    assert "Hero (id=hero, energy=~60," in prompt
    assert "Supporter (id=sup_01, energy=~70," in prompt
    # ...and exactly in the protagonist's own prompt.
    hero_prompt = _system_prompt(world, world.agents["hero"])
    assert "Supporter (id=sup_01, energy=71," in hero_prompt


def test_quiet_background_prompts_byte_identical_across_ticks():
    """Two quiet assemblies across ticks WITHIN the same day (and an energy
    drift inside one 10-bucket) produce byte-identical message lists."""
    world = _quiet_world()
    events = _events(5)
    bg = world.agents["bg_solo"]
    msgs_a = _assemble_context(bg, world, events, world.params)
    world.tick = 43           # still day 2
    bg.energy = 77.5          # still bucket ~70
    msgs_b = _assemble_context(bg, world, events, world.params)
    assert json.dumps(msgs_a, sort_keys=True) == json.dumps(msgs_b, sort_keys=True)

    # The protagonist control: the SAME drift changes a protagonist prompt
    # (tick + exact energy render exactly) — normalization is background-only.
    bg.cadence_tier = "protagonist"
    world.tick = 41
    bg.energy = 78.0
    pro_a = _assemble_context(bg, world, events, world.params)
    world.tick = 43
    bg.energy = 77.5
    pro_b = _assemble_context(bg, world, events, world.params)
    assert pro_a != pro_b


def test_quiet_background_round_scores_router_cache_hit():
    """The EM-162 payoff, proven on the router's own bookkeeping: the second
    quiet-round prompt is a sha1 cache HIT (1 adapter call, hits=1, misses=1)."""
    calls = []

    class StubAdapter:
        name = "lane"
        color = "#fff"
        last_routed_via = "stub-model"
        last_usage = {"input_tokens": 10, "output_tokens": 5,
                      "latency_ms": 1.0, "finish_reason": "stop"}

        async def chat(self, messages, *, max_tokens, temperature):
            calls.append(messages)
            return json.dumps(IDLE)

    profiles = [ModelProfile(name="lane", adapter="openai", model_id="m",
                             color="#fff")]
    router = Router(profiles, adapter_overrides={"lane": StubAdapter()})
    assert router.cache_stats() == {"hits": 0, "misses": 0, "entries": 0}

    world = _quiet_world()
    events = _events(5)
    bg = world.agents["bg_solo"]
    msgs_a = _assemble_context(bg, world, events, world.params)
    world.tick = 43
    bg.energy = 77.5
    msgs_b = _assemble_context(bg, world, events, world.params)

    asyncio.run(router.chat("lane", msgs_a, max_tokens=256, temperature=0.8))
    asyncio.run(router.chat("lane", msgs_b, max_tokens=256, temperature=0.8))
    assert len(calls) == 1, "second quiet round must be served from cache"
    assert router.cache_stats() == {"hits": 1, "misses": 1, "entries": 1}

    # clear_cache resets the additive bookkeeping with the entries.
    router.clear_cache()
    assert router.cache_stats() == {"hits": 0, "misses": 0, "entries": 0}


# ──────────────────────────────────────────────────────────────────────────────
# 6. EM-163 — tier-gated world-mutating tools (menu + resolution agree)
# ──────────────────────────────────────────────────────────────────────────────

def test_tier_gated_constant_shape():
    from petridish.agents.runtime import TIER_GATED_ACTIONS
    assert TIER_GATED_ACTIONS == frozenset(
        {"propose_project", "build_step", "contribute_funds", "propose_rule"})


def test_background_menu_omits_gated_tools_vote_stays():
    world = _build_city_world()
    # At the market: propose_project/contribute_funds/build_step all on offer
    # to the protagonist (b6 is under construction here)...
    hero_prompt = _system_prompt(world, world.agents["hero"])
    assert "propose_project (" in hero_prompt
    assert "contribute_funds (" in hero_prompt
    assert "build_step (building_id=b6)" in hero_prompt
    # ...and ALL omitted from the background menu.
    bg_prompt = _system_prompt(world, world.agents["bg_01"])
    assert "propose_project" not in bg_prompt
    assert "contribute_funds" not in bg_prompt
    assert "build_step" not in bg_prompt
    # Ungated reflex building tools survive the diet (arson is not gated).
    assert "arson (building_id=" in bg_prompt

    # At the townhall: propose_rule offered to the protagonist, omitted for
    # background — but VOTE stays for everyone.
    world.agents["hero"].location = "townhall"
    world.agents["bg_01"].location = "townhall"
    hero_hall = _system_prompt(world, world.agents["hero"])
    bg_hall = _system_prompt(world, world.agents["bg_01"])
    assert "propose_rule (" in hero_hall
    assert "propose_rule" not in bg_hall
    assert "vote (rule_id, choice)" in hero_hall
    assert "vote (rule_id, choice)" in bg_hall
    assert "rule_prop_1" in bg_hall


def test_resolution_time_tier_gate_matches_billboard_pattern():
    from petridish.agents.runtime import _validate_world
    world = _build_city_world()
    bg = world.agents["bg_01"]
    sup = world.agents["sup_01"]
    hero = world.agents["hero"]

    gated = [
        {"action": "propose_project", "args": {"name": "Shed", "kind": "workshop"}},
        {"action": "build_step", "args": {"building_id": "b6"}},
        {"action": "contribute_funds", "args": {"building_id": "b1", "amount": 2}},
        {"action": "propose_rule", "args": {"effect": "ubi", "text": "bread"}},
    ]
    for action in gated:
        err = _validate_world(action, bg, world)
        assert err is not None and "tier rule" in err, (
            f"{action['action']} must reject for background: {err!r}")
        assert action["action"] in err  # the message names the action
    # Protagonist + supporting pass the tier gate (other world checks may
    # still apply — none do for these args at the market).
    for agent in (hero, sup):
        for action in gated[:3]:
            assert _validate_world(action, agent, world) is None
    # Voting is NOT gated for background.
    vote = {"action": "vote", "args": {"rule_id": "rule_prop_1", "choice": True}}
    assert _validate_world(vote, bg, world) is None


def test_background_propose_project_rejects_cleanly_in_full_loop():
    """Resolution-time enforcement end-to-end: a background agent scripted to
    propose_project gets a clean parse_failure rejection event naming the tier
    rule — never a crash, and no building is created."""
    propose = {"action": "propose_project",
               "args": {"name": "Rogue Tower", "kind": "workshop"}}
    bg = AgentState(id="agent_bg", name="Bg", personality="", profile="mock",
                    location="market", energy=80.0, credits=20,
                    cadence_tier="background")
    loop, world, repo, runtime, provider = _make_loop(
        [bg], scripts={"agent_bg": [propose, propose]})

    asyncio.run(loop._execute_turn(bg))  # first turn = salient (no baseline)

    assert world.buildings == {}, "the gated proposal must not create a building"
    rows = repo.get_events(loop._run_id or 1, kinds=["parse_failure"], order="asc")
    assert rows, "expected the clean rejection event"
    payload = rows[-1]["payload"]
    assert "tier rule" in payload["reason"]
    assert payload["rejected_action"]["action"] == "propose_project"

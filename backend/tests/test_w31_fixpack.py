# backend/tests/test_w31_fixpack.py
"""W31 fix-pack regressions (Wave O #92 / W31 #102/#103 review findings).

C8  — the Healing House can only swap a patient onto a lane the ROUTER knows:
      the TickLoop seeds the router's profile names as the world's healing
      allow-list at construction, so a typo'd config lane is never chosen
      (it would flow onto the replay-surface agent.profile, fail the live
      reassign, and degrade the agent to mock on a fork/resume — the
      never-swap-toward-silence law).
C9  — the charters WRITE path (sanitize + apply-time normalize) uses the
      WORLD's effective caps (config clamped by the module hard ceiling),
      the same caps from_snapshot restores with, so a non-default creed_cap
      round-trips byte-identically instead of re-truncating on restore.
C13 — a clash kill's `agent_died` (and the heir's `inherited`) events wear
      their OWN actor's profile/profile_color, not the attacker's (the
      travel_arrived mis-attribution class).
C14 — siege is not free: the besieger burns siege_energy_cost energy and
      grinds their OWN faction by exhaustion_per_siege_own.

C3/C4 regressions live beside the behavior they fix (test_em258_combat /
test_em258_schema / test_em259_* / test_em257_*).
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy
import json
import logging

from petridish.engine.world import (
    World, AgentState, PlaceState, Building, normalize_charter,
    charter_caps_for,
)
from petridish.config.loader import WorldParams, ModelProfile, _parse_war
from petridish.agents.runtime import (
    AgentRuntime, _sanitize_charter_revision,
)
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider

FA, FB = "fct_aaa11111", "fct_bbb22222"


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, profile: str = "mock") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile=profile,
                      location="townhall", energy=80.0, credits=20)


def _war_world(profiles: dict[str, str] | None = None) -> World:
    """ada/bram (faction A) + dot/eli (faction B), all at the townhall."""
    profiles = profiles or {}
    ids = ["ada", "bram", "dot", "eli"]
    places = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                         kind="governance")]
    w = World(params=_params(), places=places,
              agents=[_a(i, profiles.get(i, "mock")) for i in ids])
    w.params.war = {"enabled": True}
    w.factions = {
        FA: {"name": "Ada's circle", "founded_tick": 0,
             "members": ["ada", "bram"]},
        FB: {"name": "Dot's circle", "founded_tick": 0,
             "members": ["dot", "eli"]},
    }
    return w


# ══ C8 — Healing House known-profile allow-list ═══════════════════════════════

def _healing_world(targets, known=None) -> World:
    p = _params()
    p.healing_house = {"enabled": True, "target_profiles": tuple(targets)}
    w = World(
        params=p,
        places=[PlaceState(id="townhall", name="City Hall", x=0, y=0,
                           kind="governance")],
        agents=[_a("a", profile="groq"), _a("b", profile="groq")])
    if known is not None:
        w.set_healing_known_profiles(known)
    return w


def test_unknown_lane_is_dropped_from_the_healing_pool():
    """A typo'd config lane never reaches _pick_healing_profile once the
    allow-list is seeded — the swap toward it simply cannot happen."""
    w = _healing_world(("groq", "typo_lane"), known=["groq", "cerebras"])
    assert w.healing_target_profiles() == ["groq"]
    # The patient already runs groq and the typo'd lane is filtered ⇒ no
    # eligible target: the sentence would be a no-op and (below) the propose
    # gate rejects before a vote can open.
    assert w._pick_healing_profile(w.agents["b"]) is None
    ok, reason, rule = w.action_propose_rule(w.agents["a"], "heal", "please",
                                             None, "B")
    assert not ok and rule is None
    assert "no healer available" in reason


def test_known_lanes_still_swap():
    w = _healing_world(("groq", "cerebras"), known=["groq", "cerebras"])
    assert w.healing_target_profiles() == ["groq", "cerebras"]
    assert w._pick_healing_profile(w.agents["b"]) == "cerebras"


def test_no_allow_list_means_no_filtering():
    """Direct-World callers (tests, headless runs without a loop) keep the
    pre-fix behavior: the configured pool passes through un-filtered."""
    w = _healing_world(("groq", "unvetted_lane"))
    assert w.healing_target_profiles() == ["groq", "unvetted_lane"]
    assert w._pick_healing_profile(w.agents["b"]) in ("unvetted_lane",)


def test_loop_seeds_the_allow_list_from_the_router_and_warns(caplog):
    """TickLoop construction installs the router's profile names as the
    world's healing allow-list and warns ONCE about unroutable config
    entries (the operator's boot-time signal)."""
    p = _params()
    p.healing_house = {"enabled": True,
                       "target_profiles": ("lane_b", "ghost_lane")}
    world = World(
        params=p,
        places=[PlaceState(id="townhall", name="City Hall", x=0, y=0,
                           kind="governance")],
        agents=[_a("a"), _a("b")])
    mock = MockProvider(script=[{"action": "idle", "args": {}}])
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock",
                      color="#2ecc71"),
         ModelProfile(name="lane_b", adapter="mock", model_id="mock",
                      color="#3498db")],
        adapter_overrides={"mock": mock, "lane_b": mock},
    )
    for a in world.agents.values():
        router.reassign(a.id, "mock")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    repo = SQLiteRepository(":memory:")
    with caplog.at_level(logging.WARNING, logger="petridish.engine.loop"):
        loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    assert loop is not None
    assert world.healing_known_profiles == ["mock", "lane_b"]
    assert world.healing_target_profiles() == ["lane_b"]
    assert "ghost_lane" in caplog.text
    assert "unknown to the router" in caplog.text


# ══ C9 — charter caps: write path == restore path ═════════════════════════════

def _charter_params(**block) -> WorldParams:
    p = _params()
    p.charters = {"enabled": True, **block}
    return p


def _charter_world(params: WorldParams) -> World:
    return World(params=params,
                 places=[PlaceState(id="townhall", name="City Hall", x=0, y=0,
                                    kind="governance")],
                 agents=[_a("a")])


def test_charter_caps_clamp_config_by_the_hard_ceiling():
    assert _charter_world(_charter_params()).charter_caps() == (3, 140)
    assert _charter_world(
        _charter_params(creed_cap=60)).charter_caps() == (3, 60)
    # Config above the module ceiling clamps DOWN (the schema bound).
    assert _charter_world(
        _charter_params(creed_cap=500, max_ambitions=9)).charter_caps() == (3, 140)
    assert _charter_world(
        _charter_params(max_ambitions=2)).charter_caps() == (2, 140)
    # charter_caps_for is the same read from bare params (from_snapshot's seam).
    assert charter_caps_for(_charter_params(creed_cap=60)) == (3, 60)


def test_sanitizer_respects_the_world_creed_cap():
    """The finding's failure: the sanitizer capped at the module 140 while
    the restore path re-capped at the configured 60 — the write path must
    bound with the world's caps."""
    w = _charter_world(_charter_params(creed_cap=60))
    max_amb, creed_cap = w.charter_caps()
    action = {"action": "idle", "args": {},
              "charter_revision": {"ambitions": ["keep_the_peace"],
                                   "creed": "x" * 200}}
    assert _sanitize_charter_revision(
        action, max_ambitions=max_amb, creed_cap=creed_cap) is None
    assert len(action["charter_revision"]["creed"]) == 60


def test_non_default_creed_cap_round_trips_byte_identical():
    """Live world with creed_cap 60: a charter written through the world-cap
    seams survives to_snapshot → from_snapshot → to_snapshot byte-identically
    (the finding: a 140-char creed restored to 60 chars and diverged)."""
    params = _charter_params(creed_cap=60)
    w = _charter_world(params)
    max_amb, creed_cap = w.charter_caps()
    # The apply-time write (runtime's normalize_charter call) with world caps.
    w.agents["a"].charter = normalize_charter(
        {"ambitions": ["keep_the_peace"], "creed": "y" * 200,
         "revised_tick": 4, "revisions": 1},
        max_ambitions=max_amb, creed_cap=creed_cap)
    assert len(w.agents["a"].charter["creed"]) == 60
    snap = w.to_snapshot()
    hop1 = World.from_snapshot(copy.deepcopy(snap), params=params)
    assert json.dumps(hop1.to_snapshot(), sort_keys=True) == \
        json.dumps(snap, sort_keys=True)
    hop2 = World.from_snapshot(copy.deepcopy(hop1.to_snapshot()), params=params)
    assert json.dumps(hop2.to_snapshot(), sort_keys=True) == \
        json.dumps(snap, sort_keys=True)


def test_seed_charter_uses_the_effective_caps():
    w = _charter_world(_charter_params(creed_cap=10,
                                       seed_creed="a creed far past ten chars"))
    w.seed_charter(w.agents["a"])
    assert len(w.agents["a"].charter["creed"]) == 10


# ══ C13 — clash-kill events wear their OWN actor's colors ═════════════════════

def test_clash_kill_agent_died_wears_the_targets_color():
    w = _war_world(profiles={"ada": "lane_a", "dot": "lane_b"})
    w.params.death_after_zero_turns = 1                 # die on first zero
    w.open_war(FA, FB, "avenge the market")
    w.factions[FA]["war_band"] = ["ada"]
    w.factions[FB]["war_band"] = ["dot"]
    w.agents["dot"].energy = 5.0
    mock = MockProvider(script=[{"action": "idle", "args": {}}])
    router = Router(
        [ModelProfile(name="lane_a", adapter="mock", model_id="mock",
                      color="#aa0000"),
         ModelProfile(name="lane_b", adapter="mock", model_id="mock",
                      color="#00bb00")],
        adapter_overrides={"lane_a": mock, "lane_b": mock},
    )
    router.reassign("ada", "lane_a")
    router.reassign("dot", "lane_b")
    runtime = AgentRuntime(w, router)
    evt = runtime._apply_action_inner(
        w.agents["ada"], {"action": "clash", "args": {"target": "dot"},
                          "thought": ""},
        "lane_a", "#aa0000")
    assert "_multi" in evt
    clash = next(e for e in evt["_multi"] if e["kind"] == "war_clash")
    died = next(e for e in evt["_multi"] if e["kind"] == "agent_died")
    # The clash card is the ATTACKER's; the death card is the TARGET's.
    assert clash["actor_id"] == "ada"
    assert clash["profile"] == "lane_a" and clash["profile_color"] == "#aa0000"
    assert died["actor_id"] == "dot"
    assert died["profile"] == "lane_b" and died["profile_color"] == "#00bb00"


def test_clash_kill_inherited_wears_the_heirs_color():
    w = _war_world(profiles={"ada": "lane_a", "dot": "lane_b",
                             "eli": "lane_c"})
    w.params.death_after_zero_turns = 1
    w.params.generations = {"enabled": True}            # inheritance ON
    w.agents["eli"].parents = ["bram", "dot"]           # eli = dot's heir
    w.open_war(FA, FB, "avenge the market")
    w.factions[FA]["war_band"] = ["ada"]
    w.factions[FB]["war_band"] = ["dot"]
    w.agents["dot"].energy = 5.0
    mock = MockProvider(script=[{"action": "idle", "args": {}}])
    router = Router(
        [ModelProfile(name="lane_a", adapter="mock", model_id="mock",
                      color="#aa0000"),
         ModelProfile(name="lane_b", adapter="mock", model_id="mock",
                      color="#00bb00"),
         ModelProfile(name="lane_c", adapter="mock", model_id="mock",
                      color="#0000cc")],
        adapter_overrides={"lane_a": mock, "lane_b": mock, "lane_c": mock},
    )
    for aid, lane in (("ada", "lane_a"), ("dot", "lane_b"), ("eli", "lane_c")):
        router.reassign(aid, lane)
    runtime = AgentRuntime(w, router)
    evt = runtime._apply_action_inner(
        w.agents["ada"], {"action": "clash", "args": {"target": "dot"},
                          "thought": ""},
        "lane_a", "#aa0000")
    inherited = next(e for e in evt["_multi"] if e["kind"] == "inherited")
    assert inherited["actor_id"] == "eli"
    assert inherited["profile"] == "lane_c"
    assert inherited["profile_color"] == "#0000cc"


# ══ C14 — siege costs energy and grinds the besieger's own side ═══════════════

def _besieged_world(war_block: dict | None = None) -> tuple[World, Building]:
    w = _war_world()
    if war_block is not None:
        w.params.war = {"enabled": True, **war_block}
    w.open_war(FA, FB, "avenge the market")
    w.factions[FA]["war_band"] = ["ada"]
    w.factions[FB]["war_band"] = ["dot"]
    b = Building(id="bld_keep", name="Dot's Keep", kind="generic",
                 location="townhall", owner_id="dot", status="operational",
                 health=100)
    w.buildings[b.id] = b
    return w, b


def test_siege_burns_energy_and_grinds_own_faction():
    w, _ = _besieged_world()
    war = next(iter(w.wars.values()))
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["_multi"][0]["kind"] == "war_siege"
    assert w.agents["ada"].energy == 76.0               # 80 - siege_energy_cost
    assert war.exhaustion == {FB: 4, FA: 2}             # per_siege / _own


def test_siege_costs_are_config_tunable_and_zeroable():
    w, _ = _besieged_world({"siege_energy_cost": 0,
                            "exhaustion_per_siege_own": 0})
    war = next(iter(w.wars.values()))
    w.action_siege(w.agents["ada"], "bld_keep")
    assert w.agents["ada"].energy == 80.0               # cost zeroed
    assert war.exhaustion == {FB: 4}                    # no own-side key


def test_siege_energy_clamps_at_zero():
    w, _ = _besieged_world({"siege_energy_cost": 500})
    w.action_siege(w.agents["ada"], "bld_keep")
    assert w.agents["ada"].energy == 0.0


def test_war_params_parse_the_new_siege_knobs():
    d = _parse_war(None)
    assert d.siege_energy_cost == 4.0
    assert d.exhaustion_per_siege_own == 2
    p = _parse_war({"siege_energy_cost": 2, "exhaustion_per_siege_own": 5})
    assert p.siege_energy_cost == 2.0
    assert p.exhaustion_per_siege_own == 5


def test_disabled_war_siege_still_leaves_no_trace():
    """War OFF stays byte-identical — the C14 costs live behind the same
    fail-closed gate as the rest of the verb."""
    w = _war_world()
    w.params.war = {"enabled": False}
    before = json.dumps(w.to_snapshot(), sort_keys=True)
    evt = w.action_siege(w.agents["ada"], "bld_keep")
    assert evt["kind"] == "parse_failure"
    assert json.dumps(w.to_snapshot(), sort_keys=True) == before

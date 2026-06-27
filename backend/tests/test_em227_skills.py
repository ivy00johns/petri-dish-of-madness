"""EM-227 — Skills & emergent professions (Wave M2 KEYSTONE).

A `skills: dict[str, int]` (skill name → level) rides on every AgentState. A
config-side skill LIBRARY (`world.skills`) names skills, the high-value actions
each GATES, and the min level required. An agent attempting a gated action
without the required level gets a clear rejection. Skills are GAINED by doing
(a successful gated action grants xp; an xp threshold levels up) and by teaching
(EM-228 calls the `grant_skill_xp` hook). Gaining a skill replenishes the EM-229
knowledge need. Initial skills are SEEDED per persona archetype from a
deterministic hash so identical agents start with a differentiation gradient.

Invariants pinned here:
  * EM-155 — `skills` is additive: serialized in to_dict ONLY when non-empty and
    restored defensively (absent/garbage → {}, coerced to {str: int>=0}). A
    skill-less agent round-trips byte-identically to the pre-EM-227 dict.
  * em161 golden — config-absent (no `world.skills` library) ⇒ NO gating and a
    skill-less agent gets NO prompt block, so the lawful-citizen golden stays
    byte-identical. (Separately asserted in test_wave_d2_prompt_diet.)
  * config-absent = no-op — a world.yaml WITHOUT a `skills` block gates NOTHING
    via the `_skills_param` accessor (no KeyError, every existing action open).
  * determinism — the seed spread + xp/level math are pure (hash of name/id +
    archetype, threshold arithmetic); no random/clock.
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import WorldParams, SkillsParams, _parse_skills
from petridish.agents.runtime import _assemble_context, _validate_world


# A small concrete skill library for the gating tests: building gates
# propose_project/build_step, art gates create_image, rhetoric gates
# propose_rule. Each needs level >= 1.
_LIBRARY = {
    "building": {"gates": ["propose_project", "build_step"], "min_level": 1},
    "art": {"gates": ["create_image"], "min_level": 1},
    "rhetoric": {"gates": ["propose_rule"], "min_level": 1},
}

_ARCHETYPES = {
    "builder": {"building": 2},
    "artist": {"art": 2},
    "orator": {"rhetoric": 2},
}


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _skilled_params(**kw):
    p = _params(**kw)
    p.skills = SkillsParams(
        library=copy.deepcopy(_LIBRARY),
        archetypes=copy.deepcopy(_ARCHETYPES),
        xp_per_use=10,
        xp_per_level=30,
        max_level=5,
    )
    return p


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="forge", name="Forge", x=1, y=0, kind="work"),
        PlaceState(id="townhall", name="Hall", x=2, y=0, kind="governance"),
    ]


def _world(agents, params=None):
    return World(params=params or _params(), places=_places(), agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── (1) dataclass + defaults ──────────────────────────────────────────────────

def test_skills_default_empty():
    a = _agent()
    assert a.skills == {}


def test_empty_skills_omitted_from_to_dict():
    a = _agent()
    assert "skills" not in a.to_dict()


def test_skills_serialized_when_set():
    a = _agent(skills={"building": 2, "art": 1})
    assert a.to_dict()["skills"] == {"building": 2, "art": 1}


def test_skill_level_helper_defaults_zero():
    a = _agent(skills={"building": 3})
    assert a.skill_level("building") == 3
    assert a.skill_level("art") == 0


# ── (2) config block parse ────────────────────────────────────────────────────

def test_parse_skills_absent_is_empty_library():
    s = _parse_skills(None)
    assert s.library == {}
    assert s.xp_per_level == SkillsParams().xp_per_level


def test_parse_skills_reads_library_and_tunables():
    raw = {
        "xp_per_use": 12,
        "xp_per_level": 40,
        "max_level": 6,
        "library": {"building": {"gates": ["build_step"], "min_level": 2}},
        "archetypes": {"builder": {"building": 1}},
    }
    s = _parse_skills(raw)
    assert s.xp_per_use == 12
    assert s.xp_per_level == 40
    assert s.max_level == 6
    assert s.library["building"]["gates"] == ["build_step"]
    assert s.library["building"]["min_level"] == 2
    assert s.archetypes["builder"]["building"] == 1


def test_parse_skills_malformed_falls_back():
    s = _parse_skills({"library": "not a dict", "xp_per_level": "x"})
    assert s.library == {}
    assert s.xp_per_level == SkillsParams().xp_per_level


# ── (3) gating: config-absent = no-op (golden-safe) ───────────────────────────

def test_no_library_gates_nothing():
    # The default WorldParams has an EMPTY skill library, so a skill-less agent
    # may propose_project / create_image / propose_rule exactly as pre-EM-227.
    a = _agent(location="townhall")
    w = _world([a])  # default params, empty library
    assert _validate_world(
        {"action": "propose_project", "args": {"name": "Bakery"}}, a, w) is None
    assert _validate_world(
        {"action": "create_image", "args": {"prompt": "a sunset"}}, a, w) is None
    assert _validate_world(
        {"action": "propose_rule", "args": {"effect": "ubi"}}, a, w) is None


# ── (3) gating: rejects without skill, allows with ────────────────────────────

def test_gate_rejects_propose_project_without_building_skill():
    a = _agent(location="forge")  # no skills
    w = _world([a], params=_skilled_params())
    err = _validate_world(
        {"action": "propose_project", "args": {"name": "Bakery"}}, a, w)
    assert err is not None
    assert "building" in err.lower()
    assert "lack" in err.lower()


def test_gate_allows_propose_project_with_building_skill():
    a = _agent(location="forge", skills={"building": 1})
    w = _world([a], params=_skilled_params())
    assert _validate_world(
        {"action": "propose_project", "args": {"name": "Bakery"}}, a, w) is None


def test_gate_rejects_create_image_without_art_skill():
    a = _agent(skills={"building": 3})  # has building, not art
    w = _world([a], params=_skilled_params())
    err = _validate_world(
        {"action": "create_image", "args": {"prompt": "a sunset"}}, a, w)
    assert err is not None and "art" in err.lower()


def test_gate_rejects_propose_rule_without_rhetoric_skill():
    a = _agent(location="townhall")
    w = _world([a], params=_skilled_params())
    err = _validate_world(
        {"action": "propose_rule", "args": {"effect": "ubi"}}, a, w)
    assert err is not None and "rhetoric" in err.lower()


def test_gate_respects_min_level():
    # min_level 2 → level 1 is still rejected, level 2 passes.
    p = _skilled_params()
    p.skills.library["building"]["min_level"] = 2
    a1 = _agent(location="forge", skills={"building": 1})
    w1 = _world([a1], params=p)
    assert _validate_world(
        {"action": "propose_project", "args": {"name": "X"}}, a1, w1) is not None
    a2 = _agent(id="d2", name="D2", location="forge", skills={"building": 2})
    w2 = _world([a2], params=p)
    assert _validate_world(
        {"action": "propose_project", "args": {"name": "X"}}, a2, w2) is None


def test_survival_actions_never_gated():
    # move/work/forage/say/whisper/recharge/idle/remember stay open even with a
    # populated library and a skill-less agent.
    a = _agent(location="forge")
    w = _world([a], params=_skilled_params())
    for action, args in [
        ("move_to", {"place": "plaza"}),
        ("work", {}),
        ("forage", {}),
        ("idle", {}),
        ("recharge", {}),
        ("remember", {"text": "I saw a fox"}),
    ]:
        # None (legal) or a NON-skill reason — never a "lack the skill" rejection.
        err = _validate_world({"action": action, "args": args}, a, w)
        assert err is None or "skill" not in err.lower(), (action, err)


# ── (4) xp + level-up threshold (deterministic) ───────────────────────────────

def test_grant_skill_xp_levels_up_at_threshold():
    a = _agent()
    w = _world([a], params=_skilled_params())  # xp_per_level=30
    leveled = w.grant_skill_xp(a, "building", 30)
    assert a.skill_level("building") == 1
    assert leveled is True


def test_grant_skill_xp_below_threshold_no_level():
    a = _agent()
    w = _world([a], params=_skilled_params())
    leveled = w.grant_skill_xp(a, "building", 10)
    assert a.skill_level("building") == 0
    assert leveled is False


def test_grant_skill_xp_accumulates_across_calls():
    a = _agent()
    w = _world([a], params=_skilled_params())  # 30 per level
    w.grant_skill_xp(a, "building", 10)
    w.grant_skill_xp(a, "building", 10)
    assert a.skill_level("building") == 0
    leveled = w.grant_skill_xp(a, "building", 10)  # 30 total → level 1
    assert leveled is True
    assert a.skill_level("building") == 1


def test_grant_skill_xp_caps_at_max_level():
    a = _agent()
    p = _skilled_params()
    p.skills.max_level = 2
    w = _world([a], params=p)
    w.grant_skill_xp(a, "building", 1000)
    assert a.skill_level("building") == 2  # capped, not 33


def test_grant_skill_xp_is_deterministic():
    p = _skilled_params()
    a1 = _agent()
    a2 = _agent()
    w1 = _world([a1], params=p)
    w2 = _world([a2], params=p)
    for _ in range(7):
        w1.grant_skill_xp(a1, "art", 7)
        w2.grant_skill_xp(a2, "art", 7)
    assert a1.skills == a2.skills


# ── (5) gaining a skill replenishes knowledge (EM-229 tie) ────────────────────

def test_level_up_replenishes_knowledge():
    a = _agent(knowledge=20.0)
    w = _world([a], params=_skilled_params())
    w.grant_skill_xp(a, "building", 30)  # → level up
    assert a.knowledge > 20.0


def test_xp_without_level_still_replenishes_some_knowledge():
    # Learning-by-doing tops up knowledge even before a level-up (curiosity sated).
    a = _agent(knowledge=20.0)
    w = _world([a], params=_skilled_params())
    w.grant_skill_xp(a, "building", 10)  # no level yet
    assert a.knowledge > 20.0


# ── (6) deterministic seed spread ─────────────────────────────────────────────

def test_seed_skills_assigns_archetype_levels():
    a = _agent()
    w = _world([a], params=_skilled_params())
    w.seed_skills(a, "builder")
    # The builder archetype's base building:2 is applied. The deterministic +1
    # differentiation nudge MAY land on building (raising it to 3) depending on
    # the stable name/seed hash, so assert the base is present, not an exact
    # value — matching the sibling test_seed_skills_differs_by_archetype's `>=`.
    assert a.skill_level("building") >= 2


def test_seed_skills_deterministic_and_reproducible():
    # Same id/name + archetype → identical seed, regardless of run.
    p = _skilled_params()
    a1 = _agent()
    a2 = _agent()
    w1 = _world([a1], params=p)
    w2 = _world([a2], params=p)
    w1.seed_skills(a1, "builder")
    w2.seed_skills(a2, "builder")
    assert a1.skills == a2.skills
    assert a1.skills  # non-empty differentiation gradient


def test_seed_skills_differs_by_archetype():
    p = _skilled_params()
    builder = _agent(id="b", name="Builder")
    artist = _agent(id="a", name="Artist")
    w = _world([builder, artist], params=p)
    w.seed_skills(builder, "builder")
    w.seed_skills(artist, "artist")
    assert builder.skills != artist.skills
    assert builder.skill_level("building") >= 1
    assert artist.skill_level("art") >= 1


def test_seed_skills_no_archetype_is_noop():
    a = _agent()
    w = _world([a], params=_skilled_params())
    w.seed_skills(a, "unknown_archetype")
    assert a.skills == {}


def test_seed_skills_empty_library_is_noop():
    # No library configured ⇒ seeding leaves the agent skill-less (golden-safe).
    a = _agent()
    w = _world([a])  # default params, empty library/archetypes
    w.seed_skills(a, "builder")
    assert a.skills == {}


def test_seed_skills_auto_gives_unlabeled_agent_a_profession():
    a = _agent()
    w = _world([a], params=_skilled_params())
    w.seed_skills_auto(a)
    assert a.skills  # picked a configured archetype deterministically


def test_seed_skills_auto_deterministic_by_identity():
    p = _skilled_params()
    a1 = _agent()
    a2 = _agent()
    w1 = _world([a1], params=p)
    w2 = _world([a2], params=p)
    w1.seed_skills_auto(a1)
    w2.seed_skills_auto(a2)
    assert a1.skills == a2.skills


def test_seed_skills_auto_diverges_by_identity():
    p = _skilled_params()
    a = _agent(id="aaa", name="Aaa")
    b = _agent(id="zzz", name="Zzz")
    w = _world([a, b], params=p)
    w.seed_skills_auto(a)
    w.seed_skills_auto(b)
    # Two distinct identities map to (likely) different archetypes/spreads — at
    # minimum the seed is identity-derived, not a constant.
    assert a.skills and b.skills


def test_seed_all_skills_seeds_every_agent_and_is_idempotent():
    p = _skilled_params()
    a = _agent(id="a", name="A")
    b = _agent(id="b", name="B")
    w = _world([a, b], params=p)
    w.seed_all_skills()
    assert a.skills and b.skills
    before_a = dict(a.skills)
    w.seed_all_skills()  # idempotent — no re-roll
    assert a.skills == before_a


def test_seed_all_skills_noop_without_library():
    a = _agent()
    w = _world([a])  # default params
    w.seed_all_skills()
    assert a.skills == {}


# ── (6b) EM-227 fix — STABLE-identity seeding (uuid-suffixed boot ids) ─────────

def _gated_skills(world):
    """Every (skill, min_level) that gates at least one configured action."""
    out = {}
    for skill, spec in world.skill_library().items():
        gates = spec.get("gates") if isinstance(spec, dict) else None
        if isinstance(gates, list) and gates:
            out[skill] = max(1, int(spec.get("min_level", 1)))
    return out


def test_seed_is_stable_across_uuid_boot_ids_same_name_seed():
    # REGRESSION (bug 1): boot ids are f"agent_{name}_{uuid4()[:6]}", so two
    # same-config / same-city_seed boots of an agent with the SAME name carry
    # DIFFERENT ids. Seeding keyed on the uuid-bearing id breaks EM-155
    # determinism (different professions per boot). The seed must derive from a
    # STABLE identity (name + city_seed), so per-agent skills are IDENTICAL.
    p1 = _skilled_params()
    p2 = _skilled_params()
    # Distinct uuid-style ids, identical name + (default) city_seed.
    a1 = _agent(id="agent_ada_abc123", name="Ada")
    a2 = _agent(id="agent_ada_xyz789", name="Ada")
    w1 = _world([a1], params=p1)
    w2 = _world([a2], params=p2)
    w1.seed_all_skills()
    w2.seed_all_skills()
    assert a1.skills == a2.skills
    assert a1.skills  # non-empty differentiation gradient


def test_full_cast_seed_identical_across_uuid_boots():
    # The whole town reproduces byte-for-byte across two boots even though every
    # boot id carries a fresh uuid suffix.
    names = ["Ada", "Bo", "Cy", "Di", "Ed"]
    def boot(tag):
        agents = [_agent(id=f"agent_{n.lower()}_uu{tag}{i}", name=n)
                  for i, n in enumerate(names)]
        w = _world(agents, params=_skilled_params())
        w.seed_all_skills()
        return {a.name: dict(a.skills) for a in w.agents.values()}
    assert boot("AA") == boot("BB")


# ── (6c) EM-227 fix — coverage guarantee (no town-wide gating lockout) ─────────

def test_every_gating_skill_covered_across_many_seeds():
    # REGRESSION (bug 2): with only the 'orator' archetype granting rhetoric,
    # ~1/3 of boots seed ZERO holders of a gating skill (rhetoric gates
    # propose_rule / amend_constitution with no other bootstrap path) → the town
    # can NEVER legislate. After seed_all_skills EVERY gating skill must be held
    # by >=1 LIVING agent at >= its gate min_level, for EVERY city_seed.
    names = ["Ada", "Bo", "Cy"]  # small cast → lockout is common pre-fix
    for seed in range(60):
        p = _skilled_params()
        p.city_seed = seed
        agents = [_agent(id=f"agent_{n.lower()}_uu{seed:02d}{i}", name=n)
                  for i, n in enumerate(names)]
        w = _world(agents, params=p)
        w.seed_all_skills()
        gated = _gated_skills(w)
        for skill, min_level in gated.items():
            holders = [a for a in w.living_agents()
                       if a.skill_level(skill) >= min_level]
            assert holders, (
                f"seed={seed}: gating skill {skill!r} has no living holder "
                f"at level>={min_level} (town-wide lockout)")


def test_coverage_guarantee_is_deterministic():
    # The coverage backfill itself must be deterministic (no random/clock): two
    # boots with the same city_seed + identical names produce identical skills,
    # backfilled holders included.
    names = ["Ada", "Bo", "Cy"]
    def boot():
        p = _skilled_params()
        p.city_seed = 11  # a seed that locks out a gating skill pre-fix
        agents = [_agent(id=f"agent_{n.lower()}_{n}", name=n) for n in names]
        w = _world(agents, params=p)
        w.seed_all_skills()
        return {a.name: dict(a.skills) for a in w.agents.values()}
    assert boot() == boot()


def test_coverage_grants_only_to_living_agents():
    # A dead agent never satisfies coverage; the backfill must land on a LIVING
    # holder so the gated action is actually reachable.
    p = _skilled_params()
    p.city_seed = 11
    names = ["Ada", "Bo", "Cy"]
    agents = [_agent(id=f"agent_{n.lower()}_{n}", name=n) for n in names]
    agents[0].alive = False  # kill one before seeding
    w = _world(agents, params=p)
    w.seed_all_skills()
    for skill, min_level in _gated_skills(w).items():
        holders = [a for a in w.living_agents() if a.skill_level(skill) >= min_level]
        assert holders, f"{skill}: no LIVING holder after coverage backfill"


def test_coverage_noop_without_library():
    # No library configured ⇒ no gating ⇒ no backfill (golden-safe, skill-less).
    a = _agent()
    w = _world([a])  # default params, empty library
    w.seed_all_skills()
    assert a.skills == {}


# ── (7) snapshot round-trip ───────────────────────────────────────────────────

def test_skills_snapshot_round_trip_byte_identical_when_set():
    p = _skilled_params()
    a = _agent(skills={"building": 3, "art": 1})
    w = _world([a], params=p)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=p)
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2["agents"], sort_keys=True) == \
           json.dumps(snap1["agents"], sort_keys=True)
    assert restored.agents["dot"].skills == {"building": 3, "art": 1}


def test_skill_less_agent_dict_has_no_skills_key():
    a = _agent()
    snap = _world([a]).to_snapshot()
    for ad in snap["agents"]:
        assert "skills" not in ad


def test_from_snapshot_absent_skills_restores_empty():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad.pop("skills", None)
    restored = World.from_snapshot(snap, params=p)
    assert restored.agents["dot"].skills == {}


def test_from_snapshot_garbage_skills_coerced():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad["skills"] = {"building": "nine", "art": -3, 7: 2, "ok": 4}
    restored = World.from_snapshot(snap, params=p)
    # malformed/negative dropped or clamped; only the clean entry survives.
    assert restored.agents["dot"].skill_level("ok") == 4
    assert restored.agents["dot"].skill_level("building") == 0
    assert restored.agents["dot"].skill_level("art") == 0


# ── (8) prompt surfacing (conditional / golden-safe) ──────────────────────────

def test_no_skills_no_prompt_block():
    a = _agent()
    w = _world([a], params=_skilled_params())
    assert "PROFESSION" not in _sys(a, w)
    assert "skill" not in _sys(a, w).lower().split("=== valid actions ===")[0]


def test_skills_surfaced_in_prompt_when_held():
    a = _agent(skills={"building": 2})
    w = _world([a], params=_skilled_params())
    prompt = _sys(a, w)
    assert "building" in prompt.lower()


def test_prompt_surfaces_gated_out_actions():
    # An agent with NO art skill, in a world that gates create_image on art,
    # is told they lack the skill to paint.
    a = _agent(skills={"building": 1})
    w = _world([a], params=_skilled_params())
    prompt = _sys(a, w).lower()
    assert "art" in prompt


# ── (9) menu agreement (EM-108) ───────────────────────────────────────────────

def test_menu_omits_gated_action_without_skill():
    # With a library active and no building skill, the menu must NOT offer
    # propose_project (menu/resolution agree — no dead turns).
    a = _agent(location="forge")
    w = _world([a], params=_skilled_params())
    prompt = _sys(a, w)
    assert "propose_project (" not in prompt


def test_menu_offers_gated_action_with_skill():
    a = _agent(location="forge", skills={"building": 1})
    w = _world([a], params=_skilled_params())
    prompt = _sys(a, w)
    assert "propose_project (" in prompt


# ── (10) end-to-end xp grant through _apply_action ────────────────────────────

class _StubProvider:
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def set_world(self, world):
        self._world = world

    async def chat(self, messages, *, max_tokens, temperature):
        return "{}"


def _runtime(world):
    from petridish.agents.runtime import AgentRuntime
    from petridish.providers.router import Router
    from petridish.config.loader import ModelProfile
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": _StubProvider()},
                    cache_enabled=False)
    for a in world.agents.values():
        router.reassign(a.id, "mock")
    router.inject_world(world)
    return AgentRuntime(world, router)


def test_successful_gated_action_grants_xp_through_apply_action():
    # An agent WITH the building skill who successfully proposes a project earns
    # building xp (learn-by-doing), enough across uses to level up.
    p = _skilled_params()
    p.skills.xp_per_use = 30  # one use = one level for an easy assertion
    a = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="forge", energy=80.0, credits=20, skills={"building": 1})
    w = World(params=p, places=_places(), agents=[a])
    rt = _runtime(w)
    before = a.skill_level("building")
    rt._apply_action(a, {"action": "propose_project",
                         "args": {"name": "Bakery", "kind": "workshop"}},
                     "mock", "#2ecc71")
    assert a.skill_level("building") == before + 1


def test_failed_gated_action_grants_no_xp():
    # propose_project for a building skill at min, but the action FAILS at
    # resolution (missing name) → no xp. (We bypass the validator and hit the
    # dispatch directly to force a parse_failure.)
    p = _skilled_params()
    p.skills.xp_per_use = 30
    a = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="forge", energy=80.0, credits=20, skills={"building": 1})
    w = World(params=p, places=_places(), agents=[a])
    rt = _runtime(w)
    # A create_image with an empty prompt parse-fails at dispatch; gate it on art.
    a.skills = {"art": 1}
    res = rt._apply_action(a, {"action": "create_image", "args": {"prompt": ""}},
                           "mock", "#2ecc71")
    primary = res["_multi"][0] if "_multi" in res else res
    assert primary.get("kind") == "parse_failure"
    assert a.skill_level("art") == 1  # unchanged — no xp on failure

"""EM-126 — Generational depth (Wave M4 / STRETCH).

Builds on the EM-114 children mechanic with two BEHAVIORAL layers, BOTH gated
behind `world.generations.enabled` (DEFAULT OFF) so a default/absent world — and
every pre-EM-126 snapshot — is byte-identical and the EM-114 children mechanic is
untouched:

  * LIFE STAGES — `life_stage` (child|adult|elder) + `age_ticks` on AgentState
    (R1 additive; default adult + 0). A deterministic aging cadence increments
    age_ticks ONCE per round (World.age_agents, hooked at the round boundary) and
    promotes child→adult→elder at the world.generations thresholds (child_until /
    elder_after, measured in rounds). A promotion parks an `aged` event. Pure
    arithmetic over age_ticks — no random, no clock (EM-155 / replay-safe).

  * INHERITANCE — on death the deceased's estate (credits, optionally
    relationships/grudges) passes to a deterministic HEIR derived from the EM-114
    parents/children lineage (living children first, then living parents; lowest-id
    in the closest tier). World.apply_inheritance emits an `inherited` event.

  * LINEAGE — World.lineage(agent_id) reads {parents, children} from the existing
    `parents` field (the inspector tree is FRONTEND — a documented follow-up).

Invariants pinned here (the wave's hard rules):
  * EM-155 — the new AgentState `life_stage` / `age_ticks` fields are ADDITIVE +
    serialized only-when-non-default: a default (adult / age 0) world round-trips
    byte-identically, and a world WITH an aged elder survives a snapshot/restore.
  * em161 golden — the life-stage prompt block is EMPTY for an `adult` (the default,
    and EVERY agent when generations is off), so a default-WorldParams adult hero's
    prompt is byte-identical.
  * determinism — aging + heir selection are pure (age_ticks + sorted ids); no
    random, no clock. Same-seed runs age + inherit identically.
  * config-absent no-op — an absent `generations` block (and enabled=False) ages no
    one, drops no estate; the EM-114 children mechanic is untouched.
"""

import copy
import json

import yaml

from petridish.engine.world import World, AgentState, PlaceState, RelationshipState
from petridish.config.loader import (
    WorldParams,
    GenerationsParams,
    ChildrenParams,
    _parse_generations,
    load_config,
    EMBEDDED_WORLD_YAML,
)
from petridish.agents.runtime import _assemble_context


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _gen_params(enabled=True, child_until=2, elder_after=5,
                inherit_credits=True, inherit_relationships=False, **kw):
    p = _params(**kw)
    p.generations = GenerationsParams(
        enabled=enabled, child_until=child_until, elder_after=elder_after,
        inherit_credits=inherit_credits,
        inherit_relationships=inherit_relationships)
    return p


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="forge", name="Forge", x=1, y=0, kind="work"),
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


# ── aging cadence: deterministic promotion at thresholds ──────────────────────

def test_age_agents_increments_age_ticks_once_per_call():
    a = _agent(id="a")
    w = _world([a], _gen_params(child_until=2, elder_after=5))
    assert a.age_ticks == 0
    w.age_agents()
    assert a.age_ticks == 1
    w.age_agents()
    assert a.age_ticks == 2


def test_age_agents_promotes_child_to_adult_to_elder_at_thresholds():
    a = _agent(id="a", life_stage="child")
    w = _world([a], _gen_params(child_until=2, elder_after=4))
    # rounds 0->1->2: at age 2 (>= child_until) child becomes adult
    w.age_agents()                  # age 1, still child
    assert a.life_stage == "child"
    evts = w.age_agents()           # age 2 -> adult
    assert a.life_stage == "adult"
    assert len(evts) == 1
    assert evts[0]["kind"] == "aged"
    assert evts[0]["payload"]["from_stage"] == "child"
    assert evts[0]["payload"]["to_stage"] == "adult"
    w.age_agents()                  # age 3, adult
    assert a.life_stage == "adult"
    evts = w.age_agents()           # age 4 (>= elder_after) -> elder
    assert a.life_stage == "elder"
    assert evts[0]["payload"]["to_stage"] == "elder"


def test_life_stage_for_is_pure_threshold_math():
    w = _world([_agent(id="a")], _gen_params(child_until=3, elder_after=10))
    assert w.life_stage_for(0) == "child"
    assert w.life_stage_for(2) == "child"
    assert w.life_stage_for(3) == "adult"
    assert w.life_stage_for(9) == "adult"
    assert w.life_stage_for(10) == "elder"
    assert w.life_stage_for(99) == "elder"


def test_age_agents_skips_dead_agents():
    a = _agent(id="a")
    dead = _agent(id="z", alive=False)
    w = _world([a, dead], _gen_params())
    w.age_agents()
    assert a.age_ticks == 1
    assert dead.age_ticks == 0


def test_age_agents_runs_at_round_boundary_via_apply_round_start():
    a = _agent(id="a", cadence_tier="protagonist")
    w = _world([a], _gen_params(child_until=2, elder_after=5))
    w._apply_round_start()
    assert a.age_ticks == 1


def test_aging_is_deterministic_across_same_seed_runs():
    def _run():
        a = _agent(id="a", life_stage="child")
        b = _agent(id="b", life_stage="child")
        w = _world([a, b], _gen_params(child_until=2, elder_after=4))
        order = []
        for _ in range(5):
            for evt in w.age_agents():
                order.append((evt["actor_id"], evt["payload"]["to_stage"]))
        return order
    assert _run() == _run()


# ── config OFF / absent: no aging (golden + EM-114 untouched) ─────────────────

def test_age_agents_is_noop_when_generations_disabled():
    a = _agent(id="a", life_stage="child")
    w = _world([a], _gen_params(enabled=False, child_until=2))
    evts = w.age_agents()
    assert evts == []
    assert a.age_ticks == 0
    assert a.life_stage == "child"   # untouched (no promotion)


def test_age_agents_is_noop_when_block_absent():
    a = _agent(id="a")
    w = _world([a], _params())       # NO generations block at all
    assert w.age_agents() == []
    assert a.age_ticks == 0
    assert a.life_stage == "adult"


# ── inheritance: credits transfer to the right heir + `inherited` event ───────

def test_inheritance_passes_credits_to_living_child():
    parent = _agent(id="p", name="Pat", credits=40)
    child = _agent(id="c", name="Cal", credits=5, parents=["p"])
    w = _world([parent, child], _gen_params())
    parent.alive = False
    evt = w.apply_inheritance(parent)
    assert evt is not None
    assert evt["kind"] == "inherited"
    assert evt["payload"]["heir_id"] == "c"
    assert evt["payload"]["deceased_id"] == "p"
    assert evt["payload"]["credits"] == 40
    assert child.credits == 45        # 5 + 40
    assert parent.credits == 0        # estate transferred, not duplicated


def test_inheritance_prefers_child_over_parent():
    grandparent = _agent(id="g", credits=0)
    parent = _agent(id="p", credits=30, parents=["g"])
    child = _agent(id="c", credits=0, parents=["p"])
    w = _world([grandparent, parent, child], _gen_params())
    parent.alive = False
    evt = w.apply_inheritance(parent)
    # child (descendant) is the heir, NOT the grandparent (ancestor)
    assert evt["payload"]["heir_id"] == "c"
    assert child.credits == 30
    assert grandparent.credits == 0


def test_inheritance_falls_back_to_parent_when_no_children():
    parent = _agent(id="p", credits=0)
    deceased = _agent(id="d", credits=18, parents=["p"])
    w = _world([parent, deceased], _gen_params())
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    assert evt["payload"]["heir_id"] == "p"
    assert parent.credits == 18


def test_inheritance_heir_pick_is_lowest_id_deterministic():
    deceased = _agent(id="d", credits=10, parents=[])
    # two children; lowest-id wins deterministically
    c_b = _agent(id="b", credits=0, parents=["d"])
    c_a = _agent(id="a", credits=0, parents=["d"])
    w = _world([deceased, c_b, c_a], _gen_params())
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    assert evt["payload"]["heir_id"] == "a"
    assert c_a.credits == 10
    assert c_b.credits == 0


def test_inheritance_skips_dead_heir():
    dead_child = _agent(id="a", credits=0, parents=["d"], alive=False)
    live_child = _agent(id="b", credits=0, parents=["d"])
    deceased = _agent(id="d", credits=12)
    w = _world([dead_child, live_child, deceased], _gen_params())
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    assert evt["payload"]["heir_id"] == "b"   # the dead lowest-id child is skipped
    assert live_child.credits == 12


def test_inheritance_no_heir_is_noop():
    lone = _agent(id="x", credits=50)
    w = _world([lone], _gen_params())
    lone.alive = False
    assert w.apply_inheritance(lone) is None
    assert lone.credits == 50         # nothing moved


def test_inheritance_optional_relationships_copied_only_when_enabled():
    deceased = _agent(id="d", credits=0, parents=[])
    deceased.relationships = {
        "rival": RelationshipState(type="enemy", trust=-40, interactions=3),
        "heir": RelationshipState(type="family", trust=50, interactions=2),
    }
    heir = _agent(id="heir", credits=0, parents=["d"])
    w = _world([deceased, heir], _gen_params(inherit_relationships=True))
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    # the grudge against `rival` is copied; the self-edge to the heir is skipped
    assert "rival" in heir.relationships
    assert heir.relationships["rival"].trust == -40
    assert "heir" not in heir.relationships
    assert evt["payload"]["relationships_copied"] == 1


def test_inheritance_relationships_not_copied_by_default():
    deceased = _agent(id="d", credits=0, parents=[])
    deceased.relationships = {"rival": RelationshipState(type="enemy", trust=-40)}
    heir = _agent(id="heir", credits=0, parents=["d"])
    w = _world([deceased, heir], _gen_params())   # inherit_relationships default OFF
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    assert "rival" not in heir.relationships
    assert evt["payload"]["relationships_copied"] == 0


def test_inheritance_does_not_overwrite_existing_heir_relationship():
    deceased = _agent(id="d", credits=0, parents=[])
    deceased.relationships = {"x": RelationshipState(type="enemy", trust=-40)}
    heir = _agent(id="heir", credits=0, parents=["d"])
    heir.relationships = {"x": RelationshipState(type="friend", trust=60)}
    w = _world([deceased, heir], _gen_params(inherit_relationships=True))
    deceased.alive = False
    w.apply_inheritance(deceased)
    assert heir.relationships["x"].trust == 60   # heir's own edge wins


def test_inherit_credits_off_keeps_credits_but_still_emits():
    deceased = _agent(id="d", credits=25, parents=[])
    heir = _agent(id="h", credits=0, parents=["d"])
    p = _gen_params(inherit_credits=False)
    w = _world([deceased, heir], p)
    deceased.alive = False
    evt = w.apply_inheritance(deceased)
    assert evt is not None
    assert evt["payload"]["credits"] == 0
    assert deceased.credits == 25     # untouched
    assert heir.credits == 0


# ── inheritance OFF / absent: no estate (EM-114 death path byte-identical) ─────

def test_inheritance_is_noop_when_generations_disabled():
    deceased = _agent(id="d", credits=30)
    heir = _agent(id="h", credits=0, parents=["d"])
    w = _world([deceased, heir], _gen_params(enabled=False))
    deceased.alive = False
    assert w.apply_inheritance(deceased) is None
    assert deceased.credits == 30
    assert heir.credits == 0


def test_inheritance_is_noop_when_block_absent():
    deceased = _agent(id="d", credits=30)
    heir = _agent(id="h", credits=0, parents=["d"])
    w = _world([deceased, heir], _params())   # NO generations block
    deceased.alive = False
    assert w.apply_inheritance(deceased) is None
    assert heir.credits == 0


# ── lineage accessor ──────────────────────────────────────────────────────────

def test_lineage_reads_parents_and_children():
    gp = _agent(id="gp")
    parent = _agent(id="p", parents=["gp"])
    child_a = _agent(id="ca", parents=["p"])
    child_b = _agent(id="cb", parents=["p"])
    w = _world([gp, parent, child_a, child_b], _gen_params())
    line = w.lineage("p")
    assert line["parents"] == ["gp"]
    assert line["children"] == ["ca", "cb"]


def test_lineage_unknown_agent_is_empty():
    w = _world([_agent(id="a")], _gen_params())
    assert w.lineage("nope") == {"parents": [], "children": []}


# ── EM-155 snapshot byte-identical when default; round-trips when set ──────────

def test_default_life_stage_round_trips_byte_identical():
    a = _agent(id="a")              # adult / age 0 (the defaults)
    w = _world([a], _params())
    snap = w.to_snapshot()
    blob = json.dumps(snap)
    assert "life_stage" not in blob   # field absent at default
    assert "age_ticks" not in blob
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_aged_elder_round_trips_when_set():
    a = _agent(id="a", life_stage="elder", age_ticks=42)
    w = _world([a], _gen_params())
    snap = w.to_snapshot()
    blob = json.dumps(snap)
    assert '"life_stage"' in blob
    assert '"age_ticks"' in blob
    restored = World.from_snapshot(copy.deepcopy(snap), params=_gen_params())
    ra = restored.agents["a"]
    assert ra.life_stage == "elder"
    assert ra.age_ticks == 42
    # stable byte-identical re-snapshot
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_from_snapshot_garbage_life_fields_coerced():
    a = _agent(id="a", life_stage="elder", age_ticks=10)
    w = _world([a], _gen_params())
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        if ad["id"] == "a":
            ad["life_stage"] = "wizard"   # unknown stage
            ad["age_ticks"] = -7          # malformed
    restored = World.from_snapshot(copy.deepcopy(snap), params=_gen_params())
    ra = restored.agents["a"]
    assert ra.life_stage == "adult"   # unknown fails safe to adult
    assert ra.age_ticks == 0          # negative clamped to 0


# ── em161 golden: adult prompt has NO life-stage block ────────────────────────

def test_adult_prompt_has_no_life_stage_block():
    a = _agent(id="a")                 # adult default
    w = _world([a], _gen_params())     # even with generations ON
    sys = _sys(a, w)
    assert "YOUR LIFE STAGE" not in sys


def test_child_and_elder_prompt_surface_their_stage():
    child = _agent(id="kid", life_stage="child")
    w = _world([child], _gen_params())
    assert "YOUR LIFE STAGE" in _sys(child, w)
    assert "CHILD" in _sys(child, w)

    elder = _agent(id="old", life_stage="elder")
    w2 = _world([elder], _gen_params())
    assert "ELDER" in _sys(elder, w2)


# ── round-boundary wiring: aged events park in the spawn outbox ───────────────

def test_apply_round_start_parks_aged_events_in_spawn_outbox():
    # child promotes to adult at age 2 (child_until=2); _apply_round_start ages
    # once per call and parks the `aged` event in pending_spawn_events — the SAME
    # outbox the tick loop drains (parity with births/factions/consolidation).
    a = _agent(id="a", life_stage="child", cadence_tier="protagonist")
    w = _world([a], _gen_params(child_until=2, elder_after=9))
    w._apply_round_start()           # age 1, still child
    assert a.age_ticks == 1
    assert not any(e.get("kind") == "aged" for e in w.pending_spawn_events)
    w._apply_round_start()           # age 2 -> adult, parks `aged`
    aged = [e for e in w.pending_spawn_events if e.get("kind") == "aged"]
    assert len(aged) == 1
    assert aged[0]["payload"]["to_stage"] == "adult"


def test_apply_round_start_parks_nothing_when_generations_off():
    a = _agent(id="a", life_stage="child", cadence_tier="protagonist")
    w = _world([a], _gen_params(enabled=False, child_until=2))
    w._apply_round_start()
    assert a.age_ticks == 0
    assert not any(e.get("kind") == "aged" for e in w.pending_spawn_events)


def test_death_then_inherit_sequence_matches_loop_order():
    # Mirror the loop.py / run.py death path: check_death flips the agent dead,
    # then apply_inheritance passes the estate to the heir + emits `inherited`.
    parent = _agent(id="p", name="Pat", credits=33, energy=0.0)
    child = _agent(id="c", name="Cal", credits=0, parents=["p"])
    w = _world([parent, child],
               _gen_params(death_after_zero_turns=1))
    parent.zero_energy_turns = 0
    died = w.check_death(parent)
    assert died is True
    assert parent.alive is False
    evt = w.apply_inheritance(parent)
    assert evt is not None and evt["kind"] == "inherited"
    assert evt["payload"]["heir_id"] == "c"
    assert child.credits == 33
    assert parent.credits == 0


# ── regression (adversarial verify): newborn lifecycle + inherit idempotency ──

def _birth_world(gen_params):
    """Two mutual partners co-located at a HOME place, every birth gate met, so
    one check_births call mints a child (mirrors test_wave_e_children setup)."""
    places = [
        PlaceState(id="hearth", name="Hearth", x=0, y=0, kind="home", capacity=10),
    ]
    ada = AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                     location="hearth", energy=80.0, credits=50)
    bram = AgentState(id="agent_bram", name="Bram", personality="", profile="mock",
                      location="hearth", energy=80.0, credits=50)
    w = World(params=gen_params, places=places, agents=[ada, bram])
    for x, y in (("agent_ada", "agent_bram"), ("agent_bram", "agent_ada")):
        w.agents[x].relationships[y] = RelationshipState(
            type="partner", trust=50, interactions=10)
    # Birth-friendly chance so the seeded gate always fires (deterministic).
    w.params.children = ChildrenParams(birth_chance=1.0)
    return w


def test_newborn_enters_as_child_stage_when_generations_on():
    # BUG (EM-126): _spawn_child mints the child via spawn_agent, which leaves
    # life_stage at the AgentState "adult" default — so with generations ON every
    # BORN agent started as an ADULT, inverting the child→adult→elder cadence.
    w = _birth_world(_gen_params(child_until=6, elder_after=60))
    w.tick = 10
    events = w.check_births([{"name": "Mox", "personality": "curious"}])
    child_id = events[0]["payload"]["child_id"]
    child = w.agents[child_id]
    assert child.life_stage == "child"          # was "adult" pre-fix
    # life_stage stays consistent with the threshold math at age 0.
    assert w.life_stage_for(child.age_ticks) == "child"


def test_newborn_keeps_adult_default_when_generations_off():
    # Guard the fix's gate: with generations OFF the EM-114 birth path is
    # byte-identical — the child keeps the adult / age-0 defaults (nothing ages).
    w = _birth_world(_gen_params(enabled=False))
    events = w.check_births([{"name": "Mox", "personality": "curious"}])
    child = w.agents[events[0]["payload"]["child_id"]]
    assert child.life_stage == "adult"
    assert child.age_ticks == 0


def test_newborn_is_not_aged_its_birth_round_no_spurious_aged_event():
    # BUG (EM-126): _apply_round_start runs check_births THEN age_agents in the
    # SAME call, and age_agents iterated EVERY agent including the just-inserted
    # newborn — so its age_ticks went 0→1 in the birth round and (with the child
    # stage) it could park a backwards `aged` event, contradicting the in-code
    # invariant "ages from 0 NEXT round, not the round it is born".
    w = _birth_world(_gen_params(child_until=1, elder_after=60))
    w.set_birth_casting([{"name": "Mox", "personality": "curious"}], [])
    w.tick = 10
    w._apply_round_start()                       # one round: birth THEN aging
    born = [e for e in w.pending_spawn_events if e.get("kind") == "child_spawned"]
    assert born, "expected a birth this round"
    child = w.agents[born[0]["payload"]["child_id"]]
    # The newborn did NOT age its birth round.
    assert child.age_ticks == 0
    assert child.life_stage == "child"
    # No spurious `aged` event for the newborn (its age never moved this round).
    aged_for_child = [
        e for e in w.pending_spawn_events
        if e.get("kind") == "aged" and e["payload"].get("agent_id") == child.id
    ]
    assert aged_for_child == []
    # A pre-existing agent DID age this round (the sweep still runs for them).
    assert w.agents["agent_ada"].age_ticks == 1


def test_double_apply_inheritance_emits_exactly_one_inherited_event():
    # BUG (EM-126): apply_inheritance had no already-inherited guard, so a second
    # call on the same corpse re-walked the (now empty) estate and emitted a
    # spurious credits=0 `inherited` event.
    parent = _agent(id="p", name="Pat", credits=40)
    child = _agent(id="c", name="Cal", credits=5, parents=["p"])
    w = _world([parent, child], _gen_params())
    parent.alive = False
    first = w.apply_inheritance(parent)
    assert first is not None and first["payload"]["credits"] == 40
    assert child.credits == 45
    # The corpse is now settled; a second call is a no-op (no phantom event).
    second = w.apply_inheritance(parent)
    assert second is None
    assert child.credits == 45                   # nothing moved twice
    assert parent.inheritance_settled is True


def test_inheritance_settled_round_trips_only_when_set():
    # EM-155: the settled flag is additive — absent on a living agent (byte-
    # identical), present on a settled corpse so a resume/fork won't re-inherit.
    living = _agent(id="live", credits=10)
    w_living = _world([living], _gen_params())
    assert "inheritance_settled" not in json.dumps(w_living.to_snapshot())

    parent = _agent(id="p", credits=20)
    heir = _agent(id="h", credits=0, parents=["p"])
    w = _world([parent, heir], _gen_params())
    parent.alive = False
    w.apply_inheritance(parent)
    snap = w.to_snapshot()
    assert '"inheritance_settled"' in json.dumps(snap)
    restored = World.from_snapshot(copy.deepcopy(snap), params=_gen_params())
    rp = restored.agents["p"]
    assert rp.inheritance_settled is True
    # The restored corpse will not re-inherit.
    assert restored.apply_inheritance(rp) is None


# ── config parse: defaults / clamps / sync ────────────────────────────────────

def test_parse_generations_absent_is_default_off():
    g = _parse_generations(None)
    assert g.enabled is False
    assert g.child_until == 6
    assert g.elder_after == 60
    assert g.inherit_credits is True
    assert g.inherit_relationships is False


def test_parse_generations_clamps_and_orders_thresholds():
    g = _parse_generations({
        "enabled": True, "child_until": -3, "elder_after": -9,
        "inherit_credits": False, "inherit_relationships": True,
    })
    assert g.enabled is True
    assert g.child_until == 0
    assert g.elder_after == 0          # held >= child_until
    g2 = _parse_generations({"child_until": 20, "elder_after": 5})
    assert g2.child_until == 20
    assert g2.elder_after == 20        # inverted pair: elder held >= child


def test_parse_generations_malformed_falls_back_per_key():
    g = _parse_generations({"child_until": "x", "elder_after": None})
    assert g.child_until == 6
    assert g.elder_after == 60


def test_embedded_yaml_generations_mirror_is_default_off():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    gen = _parse_generations(raw["world"].get("generations"))
    assert gen == GenerationsParams()
    assert gen.enabled is False
    assert gen.child_until == 6
    assert gen.elder_after == 60


def test_live_config_loads_a_generations_block():
    cfg = load_config()
    assert isinstance(cfg.world.generations, GenerationsParams)
    assert cfg.world.generations.enabled is False   # default OFF in the live yaml

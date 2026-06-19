"""Wave K · The Builders' City — END-TO-END integration + cross-cutting
determinism (contracts/wave-k.md §§1-4, EM-216–221 + EM-182 + EM-155).

The Wave-K *unit* suites (test_wave_k_builders.py / test_wave_k_god.py) call the
`world.action_*` / `world.god_*` methods directly. THIS suite is the missing
integration proof: it drives a short MockProvider-scripted run through the REAL
agent action protocol — the same `TickLoop._execute_turn → AgentRuntime.run_turn
→ _normalize_args → _validate_world → _apply_action_inner` pipeline the live loop
uses — so a builders'-city mutation is exercised exactly as a model-authored turn
would trigger it, not by reaching past the protocol into world internals.

What it proves end to end:
  - an agent, THROUGH a scripted JSON turn, place_prop's a decoration → a tracked
    Prop appears with a SEEDED id + deterministic offset, owner set, and a
    persisted prop_placed event (the loop's DB row, not just the return value);
  - propose_project with the EM-182 optional `place` builds the new Building in a
    CHOSEN district (building.location == the chosen place);
  - set_building_skin (owner) re-skins a building the agent owns → building.skin
    persists and a building_reskinned event fires;
  - demolish (OWNER case) tears the owner's building down immediately; the
    governance/PUBLIC case runs the shipped propose_rule(effect=demolish) → vote →
    _on_rule_activated → spawn-outbox → loop _flush_spawn_events path and the
    building_demolished{by:governance} event reaches the persisted stream;
  - the prop CAP holds under load: scripted place_prop turns past the cap resolve
    as idle/parse_failure (never a dead turn) and the registry stops at the cap;
  - events fire IN ORDER on the persisted event stream (prop_placed → reskin →
    project_proposed → owner demolish → governance demolish);
  - EM-155 replay/fork determinism: a FULL to_snapshot → from_snapshot →
    re-serialize round-trip is BYTE-IDENTICAL after all these mutations, and a
    FORK from a MID-RUN snapshot reproduces the exact props + skin.

CRITICAL suite rule (mirrors the W8 / menagerie / Wave-K family): import
petridish.engine.world BEFORE the runtime modules so the world module binds first
(avoids the engine↔agents circular-import order trap).
"""
from __future__ import annotations

import asyncio
import copy
import json

# Suite rule: world FIRST.
from petridish.engine.world import World, AgentState, PlaceState, Building, Prop
from petridish.config.loader import (
    WorldParams, BuildingParams, PropsParams, WorldConfig, ModelProfile,
)

# Runtime imports AFTER world.
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Harness — a real TickLoop wired to a MockProvider so each agent turn flows
# through the production action protocol. Mirrors the test_w11a `_make_loop` /
# `_drive` idiom (offline, deterministic, no network).
# ──────────────────────────────────────────────────────────────────────────────

def _places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceState(id="forge", name="The Forge", x=600, y=500, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=400, y=500, kind="governance"),
    ]


def _profiles() -> list[ModelProfile]:
    return [ModelProfile(name="mock", adapter="mock", model_id="mock",
                         color="#2ecc71")]


def _make_loop(*, scripts: dict[str, list] | None = None, props_max: int = 48):
    """Build a TickLoop whose single MockProvider is driven by PER-AGENT scripts.

    `scripts` maps agent_id → a list of action dicts (cycled). The provider is the
    same object the real router calls during `run_turn`, so the agents place props
    / propose projects / reskin / demolish *through the protocol*, never by calling
    world methods directly.
    """
    params = WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=100.0,
        starting_credits=200,
        snapshot_interval_ticks=100,
        buildings=BuildingParams(enabled=True),
        props=PropsParams(max_population=props_max),
    )
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=200),
        AgentState(id="agent_bram", name="Bram", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=200),
    ]
    world = World(params=params, places=_places(), agents=agents)

    # ScriptedMock: routes the right per-agent script through the ONE provider the
    # router holds for the "mock" profile (MockProvider keys scripts by agent_id
    # extracted from the prompt's "Agent ID:" line).
    provider = _ScriptedMock(scripts or {})
    router = Router(_profiles(), adapter_overrides={"mock": provider},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    provider.set_world(world)

    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    events: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: events.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    # Stash the scripted provider for tests that re-point scripts at live ids.
    loop._test_provider = provider  # type: ignore[attr-defined]
    return loop, world, repo, events


class _ScriptedMock(MockProvider):
    """A MockProvider whose script is chosen per-agent from a dict. Entries may be
    plain action dicts OR callables `(agent_id, tick) -> dict` (so a turn can read
    live world ids — e.g. a freshly-minted rule id — at resolution time). Falls
    back to a single idle so an unscripted agent never crashes the loop."""

    def __init__(self, scripts: dict[str, list]):
        super().__init__(script=None)
        self._scripts = scripts

    def _next_action(self, agent_id: str, tick: int) -> dict:
        if agent_id not in self._iters:
            from itertools import cycle
            script = self._scripts.get(agent_id) or [{"action": "idle", "args": {}}]
            self._iters[agent_id] = cycle(script)
        entry = next(self._iters[agent_id])
        if callable(entry):
            entry = entry(agent_id, tick)
        return dict(entry)


async def _drive(loop: TickLoop, world: World, n: int) -> None:
    """Run n agent turns through the REAL turn executor (round-robins agents)."""
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)


def _persisted(repo: SQLiteRepository, run_id: int, *kinds: str) -> list[dict]:
    return repo.get_events(run_id, kinds=list(kinds), order="asc")


# ──────────────────────────────────────────────────────────────────────────────
# 1. The happy-path arc THROUGH the protocol: place_prop → reskin → propose at a
#    chosen place → owner demolish. Events fire, in order, on the persisted stream;
#    world state reflects every action.
# ──────────────────────────────────────────────────────────────────────────────

def test_builders_arc_through_action_protocol_emits_ordered_events_and_mutates_state():
    # Ada owns a workshop at the forge BEFORE the run (seeded like the unit tests):
    # she will reskin it then demolish it through scripted turns.
    scripts = {
        "agent_ada": [
            {"action": "place_prop", "args": {"kind": "bench", "place": "plaza"}},
            {"action": "set_building_skin",
             "args": {"building_id": "bld_ada", "skin": "rose"}},
            {"action": "propose_project",
             "args": {"name": "Foundry", "kind": "smithy", "funds_required": 10,
                      "place": "forge"}},
            {"action": "demolish", "args": {"building_id": "bld_ada"}},
            {"action": "idle", "args": {}},
        ],
        "agent_bram": [{"action": "idle", "args": {}}],
    }
    loop, world, repo, events = _make_loop(scripts=scripts)
    run_id = loop._run_id

    ada = world.agents["agent_ada"]
    ada.location = "forge"  # @building gate: demolish/reskin require co-location
    world.buildings["bld_ada"] = Building(
        id="bld_ada", name="Ada's Workshop", kind="workshop", location="forge",
        owner_id="agent_ada", status="operational", health=100, progress=100)

    # Turn order round-robins Ada, Bram, Ada, Bram, ... — drive enough turns that
    # Ada takes her first four scripted actions (turns 0,2,4,6).
    asyncio.run(_drive(loop, world, 8))

    # ── prop placed (turn 0) ────────────────────────────────────────────────
    assert len(world.props) == 1
    prop = next(iter(world.props.values()))
    assert prop.kind == "bench" and prop.place == "plaza"
    assert prop.owner_id == "agent_ada"
    assert prop.id.startswith("prop_") and "-" not in prop.id  # seeded, not uuid4

    # ── reskin (turn 2) ─────────────────────────────────────────────────────
    assert world.buildings["bld_ada"].skin == "rose"

    # ── propose_project at the CHOSEN place (turn 4) — EM-182 ────────────────
    proposed = _persisted(repo, run_id, "project_proposed")
    assert proposed, "propose_project must have emitted project_proposed"
    foundry_id = proposed[-1]["payload"]["building_id"]
    assert world.buildings[foundry_id].location == "forge", \
        "EM-182: the new building must sit at the chosen place, not Ada's location"
    assert world.buildings[foundry_id].kind == "smithy"

    # ── owner demolish (turn 6) ─────────────────────────────────────────────
    assert world.buildings["bld_ada"].status == "destroyed"

    # ── events fire IN ORDER on the PERSISTED stream (the loop's DB rows, which
    #    replay reads — not just the return values) ──────────────────────────
    arc = _persisted(repo, run_id, "prop_placed", "building_reskinned",
                     "project_proposed", "building_demolished")
    kinds = [e["kind"] for e in arc]
    assert kinds == ["prop_placed", "building_reskinned",
                     "project_proposed", "building_demolished"], kinds
    # The placed prop's id matches the registry; the demolish records the owner.
    assert arc[0]["payload"]["prop_id"] == prop.id
    assert arc[0]["actor_type"] == "human_agent"
    dem = arc[-1]
    assert dem["payload"]["building_id"] == "bld_ada"
    assert dem["payload"]["by"] == "owner"

    # The whole arc is byte-stable across a snapshot round-trip (see §4), proving
    # nothing here depends on wall-clock / uuid for the prop + skin state.


# ──────────────────────────────────────────────────────────────────────────────
# 2. PUBLIC demolish through GOVERNANCE — the shipped propose_rule → vote →
#    _on_rule_activated → spawn-outbox → loop _flush_spawn_events path (EM-219),
#    driven entirely through scripted agent turns (no direct world.action_* call).
# ──────────────────────────────────────────────────────────────────────────────

def test_public_demolish_runs_through_governance_pipeline_via_scripted_turns():
    # A PUBLIC eyesore neither agent owns: only governance can remove it.
    def _propose_demolish(agent_id, tick):
        return {"action": "propose_rule",
                "args": {"effect": "demolish", "text": "Tear down the eyesore",
                         "target": "bld_public"}}

    def _vote_yes_on_open_demolish(world):
        def _fn(agent_id, tick):
            for r in world.rules.values():
                if (r.effect == "demolish" and r.status == "proposed"
                        and agent_id not in r.votes):
                    return {"action": "vote",
                            "args": {"rule_id": r.id, "choice": True}}
            return {"action": "idle", "args": {}}
        return _fn

    loop, world, repo, events = _make_loop()
    run_id = loop._run_id
    world.buildings["bld_public"] = Building(
        id="bld_public", name="The Eyesore", kind="monument", location="plaza",
        owner_id="public", status="operational", health=100, progress=100)

    ada, bram = world.agents["agent_ada"], world.agents["agent_bram"]
    ada.location = "townhall"  # proposing a rule is governance-gated
    # Re-point the live provider's scripts now that the rule-id is resolved lazily.
    provider = loop._test_provider  # type: ignore[attr-defined]
    provider._scripts = {
        "agent_ada": [_propose_demolish,
                      _vote_yes_on_open_demolish(world),
                      {"action": "idle", "args": {}}],
        "agent_bram": [_vote_yes_on_open_demolish(world),
                       {"action": "idle", "args": {}}],
    }

    # Turn 0: Ada proposes the demolish rule.
    asyncio.run(_drive(loop, world, 1))
    rules = [r for r in world.rules.values() if r.effect == "demolish"]
    assert len(rules) == 1, "a demolish rule must have been proposed"
    rule = rules[0]
    assert rule.payload["target"] == "bld_public"
    assert world.buildings["bld_public"].status == "operational", "not yet voted"

    # Turn 1: Bram votes yes. Turn 2: Ada votes yes → strict majority (2 of 2) →
    # the rule activates and parks building_demolished{by:governance} in the
    # spawn-event outbox.
    asyncio.run(_drive(loop, world, 2))
    assert world.rules[rule.id].status == "active", "two yes votes must pass it"
    assert world.buildings["bld_public"].status == "destroyed", \
        "an activated demolish rule must tear the target down"

    # The outbox event is flushed by the loop on the NEXT turn's _advance_round
    # (the same path governance spawns ride). Drive one more turn to flush it.
    asyncio.run(_drive(loop, world, 1))
    gov = [e for e in _persisted(repo, run_id, "building_demolished")
           if e["payload"]["building_id"] == "bld_public"]
    assert gov, "the governance demolish must reach the persisted event stream"
    assert gov[-1]["payload"]["by"] == "governance"
    assert gov[-1]["actor_type"] == "system"


# ──────────────────────────────────────────────────────────────────────────────
# 3. The prop CAP holds UNDER LOAD when driven through the protocol — over-cap
#    place_prop turns resolve cleanly (never a dead turn) and the registry stops
#    exactly at the cap.
# ──────────────────────────────────────────────────────────────────────────────

def test_prop_cap_holds_under_scripted_load_and_never_dead_turns():
    cap = 3
    scripts = {
        # Ada hammers place_prop every one of her turns; Bram idles.
        "agent_ada": [{"action": "place_prop",
                       "args": {"kind": "lamp", "place": "plaza"}}],
        "agent_bram": [{"action": "idle", "args": {}}],
    }
    loop, world, repo, events = _make_loop(scripts=scripts, props_max=cap)
    run_id = loop._run_id

    # Drive far more Ada-turns than the cap allows (12 turns → 6 Ada placements).
    asyncio.run(_drive(loop, world, 12))

    # The registry never exceeds the cap.
    assert len(world.props) == cap, "place_prop must stop at the configured cap"

    # Exactly `cap` props were placed; the surplus turns resolved without crashing
    # the loop (the over-cap attempts are rejected with guidance → idle, NOT a
    # dead/hung turn). Every Ada turn still produced an action_resolved span.
    placed = _persisted(repo, run_id, "prop_placed")
    assert len(placed) == cap
    # The loop kept ticking through the rejections (6 Ada turns all resolved).
    resolved = repo.get_events(run_id, kinds=["action_resolved"],
                               actor_id="agent_ada", order="asc")
    assert len(resolved) == 6, "every Ada turn resolved — no dead turn under cap"


# ──────────────────────────────────────────────────────────────────────────────
# 4. EM-155 replay/fork DETERMINISM — a FULL to_snapshot → from_snapshot →
#    re-serialize is BYTE-IDENTICAL after the builders'-city mutations, and a
#    FORK from a mid-run snapshot reproduces the exact props + skin.
# ──────────────────────────────────────────────────────────────────────────────

def _arc_loop():
    """Run the full builders' arc through the protocol; return (loop, world, repo,
    run_id, foundry_id) at the end of the run for the determinism assertions."""
    scripts = {
        "agent_ada": [
            {"action": "place_prop", "args": {"kind": "bench", "place": "plaza"}},
            {"action": "place_prop", "args": {"kind": "lamp", "place": "plaza"}},
            {"action": "set_building_skin",
             "args": {"building_id": "bld_ada", "skin": "plum"}},
            {"action": "propose_project",
             "args": {"name": "Foundry", "kind": "smithy", "funds_required": 10,
                      "place": "forge"}},
            {"action": "idle", "args": {}},
        ],
        # Bram places exactly ONE tree, then idles for the rest of the run (a long
        # idle tail so his cycling script never places a second tree across his
        # four turns 1,3,5,7).
        "agent_bram": (
            [{"action": "place_prop", "args": {"kind": "tree", "place": "forge"}}]
            + [{"action": "idle", "args": {}}] * 10
        ),
    }
    loop, world, repo, _ = _make_loop(scripts=scripts)
    ada = world.agents["agent_ada"]
    ada.location = "forge"
    world.buildings["bld_ada"] = Building(
        id="bld_ada", name="Ada's Workshop", kind="workshop", location="forge",
        owner_id="agent_ada", status="operational", health=100, progress=100)
    # A god/seeded UNOWNED prop, to prove owner_id None also round-trips.
    world.props["prop_seed"] = Prop(id="prop_seed", kind="fountain",
                                    place="plaza", owner_id=None)
    asyncio.run(_drive(loop, world, 8))
    proposed = _persisted(repo, loop._run_id, "project_proposed")
    foundry_id = proposed[-1]["payload"]["building_id"] if proposed else None
    return loop, world, repo, loop._run_id, foundry_id


def test_full_snapshot_round_trip_is_byte_identical_after_protocol_mutations():
    loop, world, repo, run_id, foundry_id = _arc_loop()

    # Mix of owned + unowned props across two places + a skinned building exists.
    assert len(world.props) == 4  # bench, lamp (Ada) + tree (Bram) + seed
    assert world.buildings["bld_ada"].skin == "plum"

    snap1 = world.to_snapshot()
    assert "props" in snap1 and len(snap1["props"]) == 4

    # FULL world reconstruction → re-serialize. Deep-copy the snapshot first so a
    # mutable-restore bug can't accidentally make the two dicts share structure.
    restored = World.from_snapshot(copy.deepcopy(snap1), params=world.params)
    snap2 = restored.to_snapshot()

    # BYTE-identical: serialize both to canonical JSON and compare the bytes. This
    # is the strongest determinism statement — every prop field, the skin, the
    # building location chosen via EM-182, and ordering survive the round-trip.
    assert json.dumps(snap2["props"], sort_keys=True) == \
           json.dumps(snap1["props"], sort_keys=True), \
        "the props payload must round-trip byte-identically (EM-155)"
    assert json.dumps(snap2["buildings"], sort_keys=True) == \
           json.dumps(snap1["buildings"], sort_keys=True), \
        "buildings (incl. owner-set skin + EM-182 location) must be byte-identical"

    # And the registry itself restored intact (ids, places, offsets, ownership).
    assert {p.id for p in restored.props.values()} == {p.id for p in world.props.values()}
    for pid, p in world.props.items():
        rp = restored.props[pid]
        assert (rp.kind, rp.place, rp.dx, rp.dz, rp.owner_id) == \
               (p.kind, p.place, p.dx, p.dz, p.owner_id)
    assert restored.buildings["bld_ada"].skin == "plum"
    if foundry_id:
        assert restored.buildings[foundry_id].location == "forge"


def test_fork_from_mid_run_snapshot_reproduces_props_and_skin():
    """A fork (World.from_snapshot of a MID-run snapshot) is a fresh tick-0 world
    that must carry the exact props + skin — the contracted fork seam (EM-155)."""
    scripts = {
        "agent_ada": [
            {"action": "place_prop", "args": {"kind": "bench", "place": "plaza"}},
            {"action": "set_building_skin",
             "args": {"building_id": "bld_ada", "skin": "sage"}},
            # AFTER the fork point Ada keeps mutating — the fork must NOT see these.
            {"action": "place_prop", "args": {"kind": "lamp", "place": "plaza"}},
            {"action": "idle", "args": {}},
        ],
        "agent_bram": [{"action": "idle", "args": {}}],
    }
    loop, world, repo, _ = _make_loop(scripts=scripts)
    ada = world.agents["agent_ada"]
    ada.location = "forge"
    world.buildings["bld_ada"] = Building(
        id="bld_ada", name="Ada's Workshop", kind="workshop", location="forge",
        owner_id="agent_ada", status="operational", health=100, progress=100)

    # Drive to the FORK point: Ada's turns 0 (bench) + 2 (skin) have landed; her
    # turn 4 (the second lamp) has NOT.
    asyncio.run(_drive(loop, world, 3))  # Ada turn0, Bram turn1, Ada turn2
    assert len(world.props) == 1 and world.buildings["bld_ada"].skin == "sage"
    mid_snap = copy.deepcopy(world.to_snapshot())

    # Keep mutating the LIVE world past the fork point.
    asyncio.run(_drive(loop, world, 2))  # Bram turn3, Ada turn4 (second lamp)
    assert len(world.props) == 2, "the live world advanced past the fork"

    # The FORK is f(mid_snap) — a fresh paused tick-0 world frozen at the fork.
    fork = World.from_snapshot(mid_snap, params=world.params)
    assert fork.running is False, "a fork starts paused (from_snapshot contract)"
    assert len(fork.props) == 1, "the fork sees only the one prop placed pre-fork"
    forked_prop = next(iter(fork.props.values()))
    assert forked_prop.kind == "bench" and forked_prop.owner_id == "agent_ada"
    assert fork.buildings["bld_ada"].skin == "sage"

    # Determinism of the fork itself: re-forking the same snapshot is identical.
    fork2 = World.from_snapshot(copy.deepcopy(mid_snap), params=world.params)
    assert json.dumps(fork.to_snapshot()["props"], sort_keys=True) == \
           json.dumps(fork2.to_snapshot()["props"], sort_keys=True)

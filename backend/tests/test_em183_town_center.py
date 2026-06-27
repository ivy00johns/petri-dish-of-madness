"""EM-183 — Vote to move the town center (W17).

A governance proposal that re-anchors the town's CIVIC HEART on a place the agents
choose — "they grow the city as they see fit". Modelled on EM-219 `demolish` /
EM-236 `amend_constitution`:

  * A `World.town_center_id: str` — empty == the conventional center (the "plaza",
    at the layout origin). Additive + serialized in to_snapshot ONLY when set
    (the plaza_banner_ref only-when-non-empty pattern), restored defensively in
    from_snapshot, so a town that never relocates round-trips byte-identically
    (EM-155).

  * A governance effect `relocate_center` (R5): the proposal carries the target
    place id on its payload (like demolish's target). It RATIFIES on a 70%
    SUPERMAJORITY — the same bar as `demolish` — and applies in
    `_on_rule_activated`, emitting a `center_relocated` event. EXCLUDED from EM-087
    renewal tagging (each relocation is a one-shot ACT). The proposer's influence
    need (EM-229) is replenished on a ratified relocation.

  * Surfaced in the prompt (R6, CONDITIONAL): offered on the propose_rule menu only
    at a governance place AND only when a non-center place exists to move to (the
    promote_image/trial menu/resolution-agree pattern) — so the default protagonist
    em161 golden is byte-identical.

  * Reachable through the AGENT GATE: relocate_center is in runtime
    `_validate_world`'s valid_effects (FINDING 1 — the gate is the agent's only
    path). This file also pins the EM-236 amend_constitution gate gap closed.

Invariants pinned here:
  * EM-155 — town_center_id is additive + serialized only-when-set: an
    un-relocated world round-trips byte-identically; a relocated world survives a
    snapshot/restore (and a dangling id is tolerated).
  * em161 golden — relocate_center is absent from the default protagonist prompt
    (the protagonist isn't at a governance place) → byte-identical.
  * determinism — civic_center_id()'s fallback chain is a pure function of the
    places (no clock/RNG); the same relocation sequence yields the same center.
  * governance no-op — a world that never proposes relocate_center keeps an empty
    town_center_id forever (no config block needed; the effect is proposal-driven).
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.agents.runtime import (
    AgentRuntime, _assemble_context, _validate_world,
)
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _places():
    return [
        PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance"),
        PlaceState(id="plaza", name="Central Plaza", x=1, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=2, y=0, kind="work"),
    ]


def _world(agents, params=None, places=None):
    return World(params=params or _params(),
                 places=places if places is not None else _places(),
                 agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="civic", profile="mock",
                location="townhall", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _ratify(world, rule, voter_ids):
    """Drive a proposal to ratification by casting YES votes from voter_ids."""
    status = None
    for vid in voter_ids:
        ok, _reason, status = world.action_vote(world.agents[vid], rule.id, True)
    return status


# ── default world: the center is the plaza + inert ───────────────────────────

def test_town_center_starts_empty_and_resolves_to_plaza():
    a = _agent()
    w = _world([a])
    assert w.town_center_id == ""
    assert w.civic_center_id() == "plaza"


def test_civic_center_fallback_chain():
    a = _agent(location="hall")
    # No plaza → first social; no social → first place; no place → "".
    social_only = [PlaceState(id="hall", name="Hall", x=0, y=0, kind="governance"),
                   PlaceState(id="green", name="Green", x=1, y=0, kind="social")]
    w = _world([a], places=social_only)
    assert w.civic_center_id() == "green"            # first social, no plaza
    w2 = _world([_agent(location="hall")],
                places=[PlaceState(id="hall", name="Hall", x=0, y=0,
                                   kind="governance")])
    assert w2.civic_center_id() == "hall"            # no plaza/social → first place


def test_relocate_center_is_a_valid_propose_effect():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "relocate_center", "Make the market our heart.", target="market")
    assert ok, reason
    assert rule is not None
    assert rule.effect == "relocate_center"
    assert rule.payload["target"] == "market"


# ── propose-time validation ──────────────────────────────────────────────────

def test_relocate_unknown_place_rejected_at_propose():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "relocate_center", "x", target="nowhere")
    assert not ok
    assert rule is None
    assert "real place" in reason.lower()


def test_relocate_to_current_center_is_a_noop_rejected_at_propose():
    a = _agent()
    w = _world([a])                                   # center is the plaza
    ok, reason, rule = w.action_propose_rule(
        a, "relocate_center", "x", target="plaza")
    assert not ok
    assert rule is None
    assert "already" in reason.lower()


# ── ratification: the 70% supermajority bar ──────────────────────────────────

def test_relocate_ratifies_on_supermajority():
    # 10 living agents → 70% = ceil(7.0) = 7 yes-votes ratifies.
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "Market is our heart.", target="market")
    assert ok
    # 6 yes-votes is NOT enough (6 < 7) — still proposed, center unchanged.
    _ratify(w, rule, [f"a{i}" for i in range(6)])
    assert rule.status == "proposed"
    assert w.town_center_id == ""
    assert w.civic_center_id() == "plaza"
    # The 7th yes-vote crosses the supermajority → ratified + center moves.
    status = _ratify(w, rule, ["a6"])
    assert status == "active"
    assert w.town_center_id == "market"
    assert w.civic_center_id() == "market"


def test_relocate_below_supermajority_is_rejected_center_unchanged():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "Market.", target="market")
    assert ok
    # All 10 vote, only 5 yes (< 7 needed) → rejected, center unchanged.
    for i in range(5):
        w.action_vote(agents[i], rule.id, True)
    for i in range(5, 10):
        w.action_vote(agents[i], rule.id, False)
    assert rule.status == "rejected"
    assert w.town_center_id == ""


# ── side effects: event + influence ──────────────────────────────────────────

def test_relocate_emits_center_relocated_event_and_replenishes_influence():
    agents = [_agent(id=f"a{i}", name=f"A{i}", influence=10.0) for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "Market.", target="market")
    assert ok
    _ratify(w, rule, voters)
    evs = w.drain_spawn_events()
    relocated = [e for e in evs if e["kind"] == "center_relocated"]
    assert len(relocated) == 1
    payload = relocated[0]["payload"]
    assert payload["place_id"] == "market"
    assert payload["place_name"] == "Market"
    assert payload["proposal_id"] == rule.id
    # Proposer's influence need topped up (EM-229 hook): 10 + 15 = 25.
    assert w.agents["a0"].influence == 25.0


# ── one-shot ACT (no renewal tagging) ────────────────────────────────────────

def test_relocate_excluded_from_renewal_tagging():
    # Two successive relocations must BOTH apply (each is a one-shot ACT) — the
    # second is NOT tagged a renewal of the first.
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    ok1, _r1, rule1 = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    assert ok1 and rule1.renewal_of is None
    _ratify(w, rule1, voters)
    assert w.town_center_id == "market"
    # Now move it again, to the townhall.
    ok2, _r2, rule2 = w.action_propose_rule(
        agents[0], "relocate_center", "to townhall", target="townhall")
    assert ok2
    assert rule2.renewal_of is None                   # NOT a renewal
    _ratify(w, rule2, voters)
    assert rule2.status == "active"
    assert w.town_center_id == "townhall"


# ── duplicate guard (per-target, like demolish) ──────────────────────────────

def test_two_distinct_relocate_targets_may_be_open_at_once():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok1, _r1, r1 = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    ok2, _r2, r2 = w.action_propose_rule(
        agents[1], "relocate_center", "to townhall", target="townhall")
    assert ok1 and ok2
    assert r1.id != r2.id


def test_duplicate_relocate_for_same_target_is_blocked():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok1, _r1, r1 = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    ok2, reason2, r2 = w.action_propose_rule(
        agents[1], "relocate_center", "market again", target="market")
    assert ok1
    assert not ok2
    assert r2 is None
    assert "already open" in reason2.lower()


# ── vanished target → silent no-op ───────────────────────────────────────────

def test_relocate_to_vanished_place_is_silent_noop():
    # The target place is removed AFTER the proposal opens but BEFORE it ratifies
    # (the demolish/promote_image vanished-target pattern). The vote still applies;
    # _on_rule_activated finds no place and is a silent no-op (no event, no crash).
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    assert ok
    del w.places["market"]                            # the place vanishes
    _ratify(w, rule, voters)
    assert rule.status == "active"                    # the vote still passed
    assert w.town_center_id == ""                     # but the center did NOT move
    evs = w.drain_spawn_events()
    assert [e for e in evs if e["kind"] == "center_relocated"] == []


# ── snapshot round-trip (EM-155) ─────────────────────────────────────────────

def test_no_relocation_round_trips_byte_identical():
    a = _agent()
    w = _world([a])
    snap = w.to_snapshot()
    assert "town_center_id" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_relocation_survives_snapshot_restore():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    assert ok
    _ratify(w, rule, voters)
    snap = w.to_snapshot()
    assert snap["town_center_id"] == "market"
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.town_center_id == "market"
    assert restored.civic_center_id() == "market"


def test_relocation_snapshot_is_stable_byte_identical():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    ok, _r, rule = w.action_propose_rule(
        agents[0], "relocate_center", "to market", target="market")
    _ratify(w, rule, voters)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_dangling_center_id_tolerated():
    # A serialized center pointing at a place that no longer exists restores
    # verbatim (byte-identical round-trip) but resolves back to the plaza chain.
    a = _agent()
    w = _world([a])
    snap = w.to_snapshot()
    snap["town_center_id"] = "ghost-place"
    restored = World.from_snapshot(snap, params=_params())
    assert restored.town_center_id == "ghost-place"   # kept verbatim
    assert restored.civic_center_id() == "plaza"      # resolves to the default


# ── prompt menu (em161 golden-safe) ──────────────────────────────────────────

def test_relocate_offered_in_propose_menu_when_a_target_exists():
    a = _agent()                                      # at townhall (governance)
    w = _world([a])
    sys = _sys(a, w)
    assert "relocate_center" in sys


def test_relocate_omitted_when_only_the_center_place_exists():
    # A single-place world where the only place IS the center: the proposer is at a
    # governance place (the propose block shows) but relocate_center is omitted —
    # the menu never names the place that is already the center.
    only = [PlaceState(id="townhall", name="Town Hall", x=0, y=0,
                       kind="governance")]
    a = _agent(location="townhall")
    w = _world([a], places=only)
    assert w.civic_center_id() == "townhall"
    sys = _sys(a, w)
    assert "propose_rule" in sys                      # the propose block IS present
    assert "relocate_center" not in sys               # but the effect is omitted


# ── agent gate (runtime _validate_world) ─────────────────────────────────────

def test_relocate_passes_the_agent_gate_with_a_real_target():
    a = _agent()
    w = _world([a])
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "relocate_center", "text": "to market",
                  "target": "market"}}, a, w)
    assert err is None


def test_relocate_rejected_at_the_agent_gate_without_a_real_target():
    a = _agent()
    w = _world([a])
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "relocate_center", "text": "x",
                  "target": "nowhere"}}, a, w)
    assert err is not None
    assert "real place" in err.lower()


def test_amend_constitution_passes_the_agent_gate():
    # Regression (drive-by): EM-236 added amend_constitution to world.action_-
    # propose_rule + the prompt menu but NOT to the runtime gate's valid_effects,
    # so an agent proposing it was rejected as "invalid effect" before the world
    # ever saw it (FINDING 1, the promote_image bug class). Pin it closed.
    a = _agent()
    w = _world([a])
    err = _validate_world(
        {"action": "propose_rule",
         "args": {"effect": "amend_constitution", "text": "All are equal.",
                  "op": "add"}}, a, w)
    assert err is None


# ── full agent turn (perceive → choose → parse → gate → resolve) ──────────────

def _runtime_with_script(world, agent_id, script):
    """Wire a real AgentRuntime whose `agent_id` is driven by a scripted
    MockProvider, so run_turn rides the genuine perceive → choose → parse →
    _validate_world → _apply_action_inner path (the atelier FINDING-1 pattern)."""
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles,
                    adapter_overrides={"mock": MockProvider(script=script)},
                    cache_enabled=False)
    router.reassign(agent_id, "mock")
    router.inject_world(world)
    return AgentRuntime(world, router)


async def test_FULL_AGENT_TURN_relocate_center_passes_the_gate_and_activates():
    # FINDING 1 — a relocate_center proposal must survive the RUNTIME gate
    # (_validate_world) on a real agent turn, not just a direct world call. Drive a
    # full run_turn whose scripted action is propose_rule relocate_center; it must
    # be ACCEPTED (a rule exists), then a 70% vote re-anchors the center.
    agents = [AgentState(id="agent_a", name="Ada", personality="", profile="mock",
                         location="townhall", energy=100, credits=100),
              AgentState(id="agent_b", name="Bram", personality="", profile="mock",
                         location="plaza", energy=100, credits=100)]
    w = _world(agents)
    script = [{"thought": "the market is our true heart", "action": "propose_rule",
               "args": {"effect": "relocate_center", "target": "market",
                        "text": "Make the market our town center"}}]
    runtime = _runtime_with_script(w, "agent_a", script)

    result = await runtime.run_turn(agents[0])
    evts = result["_multi"] if "_multi" in result else [result]
    kinds = [e.get("kind") for e in evts]
    # ACCEPTED through the gate (NOT a parse_failure / dead turn).
    assert "parse_failure" not in kinds, f"gate rejected relocate_center: {evts}"
    rule = next((r for r in w.rules.values()
                 if r.effect == "relocate_center"
                 and (r.payload or {}).get("target") == "market"), None)
    assert rule is not None, "no relocate_center rule created via the full turn"
    assert rule.status == "proposed"
    assert w.town_center_id == ""                      # not moved until the vote

    # 70% of 2 living agents = ceil(1.4) = 2 → both must vote yes.
    w.action_vote(agents[0], rule.id, True)
    assert w.rules[rule.id].status == "proposed"       # 1/2 is not enough
    w.action_vote(agents[1], rule.id, True)
    assert w.rules[rule.id].status == "active"
    assert w.town_center_id == "market"
    assert w.civic_center_id() == "market"

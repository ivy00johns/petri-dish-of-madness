"""EM-232 — Peer-judged credit economy / Victory Arch (Wave M3).

A periodic pitch -> peer-judge -> award cycle:

  * A reflex verb `pitch_contribution(text)` parks a pitch keyed by the pitcher's
    id on the World (a snapshot-safe pending outbox, the M2 pattern). Zero extra
    LLM calls — the pitch text rides the agent's existing turn.

  * At a CYCLE BOUNDARY (config `world.victory_arch`: `every_n_ticks`, `award`,
    `top_n`, ...), checked in the round-start hook, the parked pitches are ranked
    by a DETERMINISTIC contribution score derived from each pitcher's durable
    contribution ledger (buildings funded, skills taught, trades settled, projects
    built) — NO random. Ties break by agent id. The top_n pitchers each get a
    credit award + a renown (reputation) bump + an influence replenish (EM-229).
    An `arch_award` event is emitted per winner; the pitch queue is cleared.

Invariants pinned here (the wave's hard rules):
  * EM-155 — the new AgentState `contributions`/`renown` fields AND the World
    `pending_pitches` outbox are ADDITIVE + serialized only-when-non-default /
    only-when-non-empty: a world with NONE of them round-trips byte-identically,
    and a world WITH parked pitches / a tallied contributor survives a
    snapshot/restore (EM-190 — the new outbox is NOT dropped on fork/resume).
  * em161 golden — `pitch_contribution` surfaces in the prompt menu ONLY when the
    victory arch is configured (every_n_ticks > 0). A default world (the absent
    block) never fires a cycle and never shows the line → byte-identical.
  * determinism — the ranking is pure tally arithmetic + an id tie-break; no
    random, no clock. The cycle gate is `tick % every_n_ticks == 0`, derived from
    world.tick (serialized) — never wall time.
  * config-absent no-op — every_n_ticks <= 0 (the default, and any world.yaml
    without the block) never runs a cycle: pitches simply accumulate, no award.
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, VictoryArchParams
from petridish.agents.runtime import _assemble_context


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _arch_params(every_n_ticks=10, award=50, top_n=1, **kw):
    p = _params(**kw)
    p.victory_arch = VictoryArchParams(
        every_n_ticks=every_n_ticks, award=award, top_n=top_n,
        reputation_bonus=5, influence_replenish=25.0,
    )
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


# ── pitch_contribution: parks a pitch keyed by the PITCHER ────────────────────

def test_pitch_parks_pending_keyed_by_pitcher():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    evt = w.action_pitch_contribution(a, "I funded the bakery and the bridge.")
    assert evt["kind"] == "contribution_pitched"
    parked = w.pending_pitches.get("a")
    assert parked is not None
    assert "bakery" in parked["text"]
    assert parked["tick"] == w.tick


def test_pitch_overwrites_prior_for_same_agent():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.action_pitch_contribution(a, "first")
    w.action_pitch_contribution(a, "second")
    assert w.pending_pitches["a"]["text"] == "second"
    assert len(w.pending_pitches) == 1


def test_pitch_rejects_blank_text():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    evt = w.action_pitch_contribution(a, "   ")
    assert evt["kind"] != "contribution_pitched"
    assert "a" not in w.pending_pitches


# ── contribution ledger: bumped by the four contribution events ───────────────

def test_contributions_bumped_by_teach_trade_fund_build():
    a = _agent(id="a", name="Ann")
    # The durable ledger starts empty; the bump helper increments per kind.
    assert a.contributions == {}
    w = _world([a])
    w.record_contribution(a, "skill_taught")
    w.record_contribution(a, "skill_taught")
    w.record_contribution(a, "trade_settled")
    assert a.contributions == {"skill_taught": 2, "trade_settled": 1}
    assert w.contribution_score(a) == 3


# ── the cycle: fires EXACTLY on cadence ───────────────────────────────────────

def test_cycle_does_not_fire_off_cadence():
    a = _agent(id="a", name="Ann", credits=20)
    w = _world([a], _arch_params(every_n_ticks=10, award=50))
    w.action_pitch_contribution(a, "did things")
    w.record_contribution(a, "project_built")
    # tick 7 is not a multiple of 10 → no award, pitch stays parked.
    w.tick = 7
    events = w.run_victory_arch_cycle()
    assert events == []
    assert a.credits == 20
    assert "a" in w.pending_pitches


def test_cycle_fires_on_cadence_and_awards_top_pitcher():
    a = _agent(id="a", name="Ann", credits=20)
    b = _agent(id="b", name="Bea", credits=20)
    w = _world([a, b], _arch_params(every_n_ticks=10, award=50, top_n=1))
    # Ann is the bigger contributor → she wins the single award.
    w.record_contribution(a, "project_built")
    w.record_contribution(a, "skill_taught")
    w.record_contribution(b, "trade_settled")
    w.action_pitch_contribution(a, "I built and taught")
    w.action_pitch_contribution(b, "I traded once")
    w.tick = 20
    events = w.run_victory_arch_cycle()
    kinds = [e["kind"] for e in events]
    assert "arch_award" in kinds
    award_evt = next(e for e in events if e["kind"] == "arch_award")
    assert award_evt["actor_id"] == "a"
    assert a.credits == 70                 # 20 + 50 award
    assert b.credits == 20                 # Bea did not place in top_n
    assert a.renown == 5                   # reputation bump applied
    # The pitch queue is cleared after a cycle.
    assert w.pending_pitches == {}


def test_cycle_replenishes_winner_influence():
    a = _agent(id="a", name="Ann", credits=20, influence=10.0)
    w = _world([a], _arch_params(every_n_ticks=5, award=30, top_n=1))
    w.record_contribution(a, "project_built")
    w.action_pitch_contribution(a, "I built the hall")
    w.tick = 10
    w.run_victory_arch_cycle()
    # influence_replenish=25 → 10 + 25 = 35 (clamped 0..100, EM-229 hook).
    assert a.influence == 35.0


def test_cycle_is_noop_with_no_pitches():
    a = _agent(id="a", name="Ann", credits=20)
    w = _world([a], _arch_params(every_n_ticks=10, award=50))
    w.tick = 10
    events = w.run_victory_arch_cycle()
    assert events == []
    assert a.credits == 20


# ── deterministic ranking + id tie-break ──────────────────────────────────────

def test_ranking_tie_breaks_by_agent_id():
    # Two pitchers with the EXACT same contribution score → the LOWER id wins the
    # single award, deterministically (no random, replay-stable).
    a = _agent(id="zeta", name="Zeta", credits=0)
    b = _agent(id="alpha", name="Alpha", credits=0)
    w = _world([a, b], _arch_params(every_n_ticks=10, award=40, top_n=1))
    w.record_contribution(a, "trade_settled")
    w.record_contribution(b, "trade_settled")
    w.action_pitch_contribution(a, "zeta pitch")
    w.action_pitch_contribution(b, "alpha pitch")
    w.tick = 10
    events = w.run_victory_arch_cycle()
    winners = [e["actor_id"] for e in events if e["kind"] == "arch_award"]
    assert winners == ["alpha"]            # tie broken by id (alpha < zeta)


def test_ranking_is_deterministic_across_repeats():
    def _run():
        a = _agent(id="a", name="Ann", credits=0)
        b = _agent(id="b", name="Bea", credits=0)
        c = _agent(id="c", name="Cy", credits=0)
        w = _world([a, b, c], _arch_params(every_n_ticks=10, award=40, top_n=2))
        w.record_contribution(a, "project_built")   # score 1
        w.record_contribution(b, "skill_taught")    # score 1
        w.record_contribution(b, "trade_settled")   # score 2 (top)
        w.record_contribution(c, "skill_taught")    # score 1
        for ag, txt in ((a, "a"), (b, "b"), (c, "c")):
            w.action_pitch_contribution(ag, txt)
        w.tick = 10
        ev = w.run_victory_arch_cycle()
        return [e["actor_id"] for e in ev if e["kind"] == "arch_award"]
    first = _run()
    # Bea (score 2) wins outright; a and c tie at 1 → id tie-break gives 'a'.
    assert first == ["b", "a"]
    assert _run() == first                 # byte-identical across runs


def test_top_n_caps_winners():
    a = _agent(id="a", name="Ann", credits=0)
    b = _agent(id="b", name="Bea", credits=0)
    c = _agent(id="c", name="Cy", credits=0)
    w = _world([a, b, c], _arch_params(every_n_ticks=10, award=10, top_n=2))
    for ag in (a, b, c):
        w.record_contribution(ag, "trade_settled")
        w.action_pitch_contribution(ag, "pitch")
    w.tick = 10
    events = w.run_victory_arch_cycle()
    winners = [e["actor_id"] for e in events if e["kind"] == "arch_award"]
    assert len(winners) == 2               # only top_n awarded


# ── snapshot round-trip (EM-155 / EM-190) ─────────────────────────────────────

def test_no_arch_state_round_trips_byte_identical():
    a = _agent(credits=20)
    w = _world([a])
    snap = w.to_snapshot()
    assert "pending_pitches" not in snap
    assert "contributions" not in json.dumps(snap)     # field absent when empty
    assert "renown" not in json.dumps(snap)
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_pending_pitches_survive_snapshot_restore():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.action_pitch_contribution(a, "I built the bridge")
    snap = w.to_snapshot()
    assert "pending_pitches" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    parked = restored.pending_pitches.get("a")
    assert parked is not None and "bridge" in parked["text"]


def test_contributions_and_renown_survive_snapshot_restore():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.record_contribution(a, "project_built")
    a.renown = 7
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    ra = restored.agents["a"]
    assert ra.contributions == {"project_built": 1}
    assert ra.renown == 7


def test_arch_snapshot_is_stable_byte_identical():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    w.action_pitch_contribution(a, "pitch text")
    w.record_contribution(a, "skill_taught")
    a.renown = 3
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_pitches_ignored():
    a = _agent(id="a", name="Ann")
    w = _world([a])
    snap = w.to_snapshot()
    snap["pending_pitches"] = {
        "a": {"text": "ok", "tick": 1},     # well-formed → kept
        "ghost": {"text": "x", "tick": 1},  # unknown agent → dropped
        "b": "bad",                          # non-dict → dropped
        "c": {"text": "   ", "tick": 1},    # blank text → dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert set(restored.pending_pitches) == {"a"}


# ── prompt menu: conditional (em161 golden) ───────────────────────────────────

def test_pitch_line_absent_without_arch_config():
    a = _agent(id="a", name="Ann")
    w = _world([a])                          # default params: no victory_arch
    sys = _sys(a, w)
    assert "pitch_contribution" not in sys


def test_pitch_line_present_when_arch_enabled():
    a = _agent(id="a", name="Ann")
    w = _world([a], _arch_params(every_n_ticks=10, award=50))
    sys = _sys(a, w)
    assert "pitch_contribution" in sys


# ── config-absent default ─────────────────────────────────────────────────────

def test_victory_arch_params_default_is_off():
    p = WorldParams()
    assert isinstance(p.victory_arch, VictoryArchParams)
    assert p.victory_arch.every_n_ticks == 0     # default OFF (no-op)


def test_default_world_never_fires_a_cycle():
    a = _agent(id="a", name="Ann", credits=20)
    w = _world([a])                          # default params
    w.action_pitch_contribution(a, "pitch")
    w.record_contribution(a, "project_built")
    w.tick = 100
    events = w.run_victory_arch_cycle()
    assert events == []
    assert a.credits == 20
    assert "a" in w.pending_pitches          # pitches accumulate, never awarded

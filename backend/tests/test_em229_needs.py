"""EM-229 — Three-needs psychology (Wave M1).

Decaying `knowledge` + `influence` needs (floats 0..100, default 100.0) ride
alongside `energy`. They decay every turn at small non-zero rates (config block
`world.needs`), but UNLIKE energy they NEVER kill — a starved knowledge/influence
need only biases behavior via a conditional prompt line that appears ONLY when
the need drops below its salience threshold.

Invariants pinned here:
  * EM-155 — the fields are additive: serialized in to_dict ONLY when < 100, and
    restored defensively (absent/garbage → 100.0, clamped 0..100). A full-needs
    agent round-trips byte-identically to the pre-EM-229 dict.
  * em161 golden — the prompt gets NO new line while both needs are full, so the
    lawful-citizen golden stays byte-identical. The line appears only below the
    salience threshold (exactly like the energy starvation line is conditional).
  * config-absent = default — a world.yaml WITHOUT a `needs` block decays at the
    dataclass defaults via the `_needs_param` accessor (no KeyError).
  * determinism — decay is pure arithmetic; no random/clock.
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, NeedsParams, _parse_needs
from petridish.agents.runtime import _assemble_context


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _world(agents, params=None):
    return World(params=params or _params(),
                 places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
                 agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── defaults & dataclass ─────────────────────────────────────────────────────

def test_needs_default_full():
    a = _agent()
    assert a.knowledge == 100.0
    assert a.influence == 100.0


# ── decay math ───────────────────────────────────────────────────────────────

def test_apply_needs_decay_subtracts_configured_rates():
    p = _params()
    p.needs = NeedsParams(knowledge_decay_per_turn=0.5, influence_decay_per_turn=0.75)
    w = _world([_agent()], params=p)
    a = w.agents["dot"]
    w.apply_needs_decay(a)
    assert a.knowledge == 100.0 - 0.5
    assert a.influence == 100.0 - 0.75
    # second turn compounds
    w.apply_needs_decay(a)
    assert round(a.knowledge, 4) == 99.0
    assert round(a.influence, 4) == 98.5


def test_needs_decay_floors_at_zero_and_never_kills():
    p = _params()
    p.needs = NeedsParams(knowledge_decay_per_turn=40.0, influence_decay_per_turn=40.0)
    w = _world([_agent(energy=80.0)], params=p)
    a = w.agents["dot"]
    for _ in range(5):
        w.apply_needs_decay(a)
    assert a.knowledge == 0.0
    assert a.influence == 0.0
    # needs do NOT kill — only energy does
    assert a.alive is True
    assert w.check_death(a) is False


def test_needs_param_accessor_absent_block_is_noop_defaults():
    # A WorldParams whose `needs` is missing/None must still decay at the
    # engine's literal call-site defaults (which match NeedsParams) via the
    # defensive accessor — no KeyError, no crash. The accessor returns the
    # caller's provided default when the block is absent (that's its contract).
    p = _params()
    p.needs = None  # simulate an absent block
    w = _world([_agent()], params=p)
    # absent block ⇒ the accessor hands back whatever default the caller passes
    assert w._needs_param("knowledge_decay_per_turn", 0.5) == 0.5
    a = w.agents["dot"]
    w.apply_needs_decay(a)  # must not raise; uses the engine literal defaults
    assert a.knowledge == 100.0 - NeedsParams().knowledge_decay_per_turn
    assert a.influence == 100.0 - NeedsParams().influence_decay_per_turn


# ── replenishment hooks (EM-227/228 wiring) ──────────────────────────────────

def test_replenish_clamps_to_100():
    w = _world([_agent(knowledge=40.0, influence=30.0)])
    a = w.agents["dot"]
    w.replenish_knowledge(a, 80.0)
    assert a.knowledge == 100.0  # clamped, never overshoots
    w.replenish_influence(a, 10.0)
    assert a.influence == 40.0


# ── conditional prompt line ──────────────────────────────────────────────────

def test_prompt_has_no_needs_line_when_full():
    a = _agent()  # both needs full
    s = _sys(a, _world([a]))
    assert "knowledge" not in s.lower()
    assert "influence" not in s.lower()


def test_prompt_shows_knowledge_line_when_below_threshold():
    p = _params()
    p.needs = NeedsParams(knowledge_salience_threshold=40.0)
    a = _agent(knowledge=20.0)
    s = _sys(a, _world([a], params=p))
    assert "knowledge" in s.lower()
    # influence still full → no influence prompt
    assert "influence" not in s.lower()


def test_prompt_shows_influence_line_when_below_threshold():
    p = _params()
    p.needs = NeedsParams(influence_salience_threshold=40.0)
    a = _agent(influence=15.0)
    s = _sys(a, _world([a], params=p))
    assert "influence" in s.lower()
    assert "knowledge" not in s.lower()


# ── snapshot round-trip (EM-155) ─────────────────────────────────────────────

def test_full_needs_omitted_from_to_dict():
    a = _agent()  # both 100.0
    d = a.to_dict()
    assert "knowledge" not in d
    assert "influence" not in d


def test_low_needs_serialized_and_restore_round_trips():
    a = _agent(knowledge=42.5, influence=10.0)
    d = a.to_dict()
    assert d["knowledge"] == 42.5
    assert d["influence"] == 10.0


def test_snapshot_round_trip_byte_identical_with_low_needs():
    p = _params()
    a = _agent(knowledge=33.0, influence=7.5)
    w = _world([a], params=p)
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=p)
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2["agents"], sort_keys=True) == \
           json.dumps(snap1["agents"], sort_keys=True)
    ra = restored.agents["dot"]
    assert ra.knowledge == 33.0
    assert ra.influence == 7.5


def test_from_snapshot_defaults_when_absent_or_garbage():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    # a pre-EM-229 snapshot lacks the keys → restore 100.0
    for ad in snap["agents"]:
        ad.pop("knowledge", None)
        ad.pop("influence", None)
        ad["knowledge_garbage_only"] = True  # ignored
    restored = World.from_snapshot(snap, params=p)
    ra = restored.agents["dot"]
    assert ra.knowledge == 100.0
    assert ra.influence == 100.0


def test_from_snapshot_clamps_out_of_range():
    p = _params()
    a = _agent()
    w = _world([a], params=p)
    snap = w.to_snapshot()
    for ad in snap["agents"]:
        ad["knowledge"] = 250.0   # clamps down to 100
        ad["influence"] = -5.0    # clamps up to 0
    restored = World.from_snapshot(snap, params=p)
    ra = restored.agents["dot"]
    assert ra.knowledge == 100.0
    assert ra.influence == 0.0


# ── config parse ─────────────────────────────────────────────────────────────

def test_parse_needs_absent_returns_defaults():
    d = _parse_needs(None)
    assert isinstance(d, NeedsParams)
    assert d.knowledge_decay_per_turn == NeedsParams().knowledge_decay_per_turn


def test_parse_needs_reads_overrides_and_falls_back_per_key():
    d = _parse_needs({"knowledge_decay_per_turn": 1.25,
                      "influence_salience_threshold": "garbage"})
    assert d.knowledge_decay_per_turn == 1.25
    # malformed value falls back to default, never breaks the block
    assert d.influence_salience_threshold == NeedsParams().influence_salience_threshold

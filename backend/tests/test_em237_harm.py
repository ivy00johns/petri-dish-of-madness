"""EM-237 — Harm-surface finishers: intimidate / deceive.

Two reflex verbs added atop the EM-240 crime-verb path (contracts/wave-m.md §3
Wave M3). They reuse the EM-240 notoriety + witness-scaling + rap_sheet machinery
(like extort) and snap the victim's view to at least rival:

  * intimidate(target) — threaten WITHOUT contact: coerce a small sum via fear,
    crater the victim's trust + plant a fear marker (a trust hit recorded in the
    relationship, snapshot-durable). Notoriety from `intimidate_notoriety`.
  * deceive(target, about) — lying as a first-class act: plant a false belief in
    the target (best-effort manipulation) + crater trust. Notoriety from
    `deceive_notoriety`.

Invariants exercised here: notoriety accrual + witness scaling (EM-240 shape),
the target effect, the menu gated to the inclined (lawful golden byte-identical),
config-absent defaults, and the snapshot round-trip (byte-identical when unset).
"""

import jsonschema

from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import ACTION_SCHEMA, _assemble_context
from petridish.config.loader import WorldParams, CrimeParams, _parse_crime


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="alley", name="Alley", x=5, y=0, kind="social"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── intimidate ───────────────────────────────────────────────────────────────

def test_intimidate_coerces_credits_and_craters_trust():
    bully = _a("bully", "alley"); bully.credits = 0
    mark = _a("mark", "alley"); mark.credits = 40
    world = _world([bully, mark])
    ok, reason, amount = world.action_intimidate(bully, mark)
    assert ok and reason == "ok"
    assert amount > 0                              # fear yields a coerced sum
    assert bully.credits == amount and mark.credits == 40 - amount
    # victim's view of the bully snaps to at least rival (a fear marker recorded
    # in the relationship — snapshot-durable, unlike a transient belief).
    rel = mark.relationships[bully.id]
    assert rel.type in ("rival", "enemy", "feud")
    assert rel.trust < 0


def test_intimidate_builds_notoriety_when_witnessed():
    bully = _a("bully", "alley"); bully.credits = 0
    mark = _a("mark", "alley"); mark.credits = 40
    eye = _a("eye", "alley")
    world = _world([bully, mark, eye])
    world.action_intimidate(bully, mark)
    assert bully.notoriety == 14                   # intimidate_notoriety default
    assert bully.rap_sheet[-1]["crime"] == "intimidate"
    assert bully.rap_sheet[-1]["witnessed"] is True


def test_intimidate_unwitnessed_records_rap_sheet_no_notoriety():
    bully = _a("bully", "alley"); bully.credits = 0
    mark = _a("mark", "alley"); mark.credits = 40
    world = _world([bully, mark])
    world.action_intimidate(bully, mark)
    assert bully.notoriety == 0                     # only the victim present
    assert bully.rap_sheet[-1]["crime"] == "intimidate"
    assert bully.rap_sheet[-1]["witnessed"] is False


def test_intimidate_witness_scaling_adds_per_extra_witness():
    bully = _a("bully", "alley"); bully.credits = 0
    mark = _a("mark", "alley"); mark.credits = 40
    world = _world([bully, mark, _a("e1", "alley"), _a("e2", "alley")])
    world.action_intimidate(bully, mark)
    # base 14 + notoriety_per_extra_witness (3) * (2 witnesses - 1) = 17
    assert bully.notoriety == 17


def test_intimidate_no_contact_required_only_visibility():
    # "threaten WITHOUT contact" — like extort it needs the target visible (same
    # place), but it must REJECT a target who isn't here (no remote intimidation).
    bully = _a("bully", "alley")
    mark = _a("mark", "plaza"); mark.credits = 40
    world = _world([bully, mark])
    ok, reason, amount = world.action_intimidate(bully, mark)
    assert not ok and amount == 0


def test_intimidate_rejected_when_target_has_nothing():
    bully = _a("bully", "alley")
    mark = _a("mark", "alley"); mark.credits = 0
    world = _world([bully, mark])
    ok, reason, amount = world.action_intimidate(bully, mark)
    assert not ok and amount == 0


# ── deceive ──────────────────────────────────────────────────────────────────

def test_deceive_plants_false_belief_and_craters_trust():
    liar = _a("liar", "alley")
    dupe = _a("dupe", "alley")
    world = _world([liar, dupe])
    ok, reason = world.action_deceive(liar, dupe, "the well is poisoned")
    assert ok and reason == "ok"
    # the false belief is planted in the target's memory (manipulation)
    assert any("the well is poisoned" in b for b in dupe.beliefs)
    # and the deceiver↔victim trust craters (reputation-gaming axis)
    assert dupe.relationships[liar.id].trust < 0


def test_deceive_builds_notoriety_when_witnessed():
    liar = _a("liar", "alley")
    dupe = _a("dupe", "alley")
    eye = _a("eye", "alley")
    world = _world([liar, dupe, eye])
    world.action_deceive(liar, dupe, "lies")
    assert liar.notoriety == 8                      # deceive_notoriety default
    assert liar.rap_sheet[-1]["crime"] == "deceive"
    assert liar.rap_sheet[-1]["witnessed"] is True


def test_deceive_unwitnessed_records_rap_sheet_no_notoriety():
    liar = _a("liar", "alley")
    dupe = _a("dupe", "alley")
    world = _world([liar, dupe])
    world.action_deceive(liar, dupe, "lies")
    assert liar.notoriety == 0
    assert liar.rap_sheet[-1]["crime"] == "deceive"


def test_deceive_requires_co_located_target():
    liar = _a("liar", "alley")
    dupe = _a("dupe", "plaza")
    world = _world([liar, dupe])
    ok, reason = world.action_deceive(liar, dupe, "lies")
    assert not ok


def test_deceive_rejects_self_target():
    liar = _a("liar", "alley")
    world = _world([liar])
    ok, reason = world.action_deceive(liar, liar, "lies")
    assert not ok


def test_deceive_empty_about_is_rejected():
    liar = _a("liar", "alley")
    dupe = _a("dupe", "alley")
    world = _world([liar, dupe])
    ok, reason = world.action_deceive(liar, dupe, "   ")
    assert not ok


# ── schema ───────────────────────────────────────────────────────────────────

def test_action_schema_accepts_intimidate_and_deceive():
    jsonschema.validate({"action": "intimidate", "args": {"target": "x"}},
                        ACTION_SCHEMA)
    jsonschema.validate({"action": "deceive",
                         "args": {"target": "x", "about": "a lie"}}, ACTION_SCHEMA)
    # also valid inside a multi-action sequence
    jsonschema.validate(
        {"actions": [{"action": "intimidate", "args": {"target": "x"}},
                     {"action": "deceive", "args": {"target": "y", "about": "z"}}]},
        ACTION_SCHEMA)


# ── menu visibility: gated to the inclined, lawful golden untouched ───────────

def test_harm_menu_offered_to_the_inclined():
    a = _a("mox", "plaza", disposition="criminal")
    other = _a("ed", "plaza")
    s = _sys(a, _world([a, other]))
    assert "intimidate (target)" in s
    assert "deceive (target" in s


def test_harm_menu_hidden_from_lawful_citizen():
    a = _a("dot", "plaza")
    other = _a("ed", "plaza")
    s = _sys(a, _world([a, other]))
    assert "intimidate (target)" not in s
    assert "deceive (target" not in s


def test_harm_menu_hidden_when_alone_even_if_inclined():
    a = _a("mox", "plaza", disposition="criminal")
    s = _sys(a, _world([a]))
    assert "intimidate (target)" not in s
    assert "deceive (target" not in s


# ── config: absent block ⇒ engine defaults (config-absent = no-op) ────────────

def test_crime_params_default_includes_harm_notoriety():
    d = CrimeParams()
    assert d.intimidate_notoriety == 14
    assert d.deceive_notoriety == 8


def test_parse_crime_absent_block_uses_harm_defaults():
    p = _parse_crime(None)
    assert p.intimidate_notoriety == 14
    assert p.deceive_notoriety == 8


def test_parse_crime_reads_harm_overrides():
    p = _parse_crime({"intimidate_notoriety": 20, "deceive_notoriety": 11})
    assert p.intimidate_notoriety == 20
    assert p.deceive_notoriety == 11


def test_world_crime_param_accessor_returns_harm_defaults():
    world = _world([_a("x", "plaza")])
    assert int(world._crime_param("intimidate_notoriety", 14)) == 14
    assert int(world._crime_param("deceive_notoriety", 8)) == 8


# ── snapshot: harm leaves no new top-level state; round-trip byte-identical ────

def test_snapshot_byte_identical_after_intimidate():
    # intimidate touches ONLY snapshot-durable EM-240 fields (notoriety / rap_sheet
    # / credits / relationships) — no NEW world-level pending/outbox state, no
    # belief planting — so the snapshot round-trip is byte-identical.
    bully = _a("bully", "alley"); bully.credits = 0
    mark = _a("mark", "alley"); mark.credits = 40
    eye = _a("eye", "alley")
    world = _world([bully, mark, eye])
    world.action_intimidate(bully, mark)
    snap = world.to_snapshot()
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.to_snapshot() == snap


def test_deceive_durable_fields_survive_snapshot():
    # deceive's DURABLE effect (the liar's notoriety/rap_sheet + the victim's
    # soured trust) round-trips. The planted belief is transient memory — beliefs
    # are NOT serialized by to_snapshot (a documented pre-EM-237 limit, shared with
    # action_remember), so only beliefs_count is carried and it is excluded here.
    liar = _a("liar", "alley")
    dupe = _a("dupe", "alley")
    eye = _a("eye", "alley")
    world = _world([liar, dupe, eye])
    world.action_deceive(liar, dupe, "a lie")
    snap = world.to_snapshot()
    restored = World.from_snapshot(snap, params=world.params)
    rl = restored.agents["liar"]
    assert rl.notoriety == liar.notoriety == 8
    assert rl.rap_sheet[-1]["crime"] == "deceive"
    # the victim's soured trust (the snapshot-durable manipulation marker) survives.
    assert restored.agents["dupe"].relationships["liar"].trust == \
        dupe.relationships["liar"].trust


def test_snapshot_byte_identical_for_clean_world_with_harm_verbs_available():
    # The harm verbs add NO new world-level state — a world where no one has
    # committed harm serializes byte-identically to a fresh round-trip (the EM-155
    # / em161 default-world guarantee that the new verbs are purely additive).
    a = _a("dot", "plaza")
    b = _a("ed", "plaza")
    world = _world([a, b])
    snap = world.to_snapshot()
    restored = World.from_snapshot(snap, params=world.params)
    assert restored.to_snapshot() == snap

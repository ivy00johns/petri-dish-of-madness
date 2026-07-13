"""EM-315 — The Healing House: config discipline, the flag-off byte-identical
surface, the runtime propose gate, and the flag-on menu + patient whisper.

healing_house.enabled defaults OFF with an EMPTY target pool ⇒ complete no-op:
default params keep the flag off, the snapshot gains no key, the prompt gains no
line or menu entry, and the verb rejects cleanly (byte-identical pre-EM-315).
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import (WorldParams, HealingHouseParams,
                                     _parse_healing_house)
from petridish.agents.runtime import _assemble_context, _validate_world


def _params(healing_house=None):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    if healing_house is not None:
        p.healing_house = healing_house
    return p


def _world(params=None):
    # propose_rule is governance-location-gated, so the proposer + patient stand
    # at a governance place (the townhall) — the menu/gate only offer heal there.
    return World(
        params=params or _params(),
        places=[
            PlaceState(id="townhall", name="City Hall", x=500, y=500,
                       kind="governance"),
            PlaceState(id="plaza", name="Plaza", x=510, y=510, kind="social"),
        ],
        agents=[
            AgentState(id="a", name="Ann", personality="", profile="groq",
                       location="townhall", energy=80.0, credits=20),
            AgentState(id="b", name="Bo", personality="", profile="groq",
                       location="townhall", energy=80.0, credits=20),
        ])


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _on():
    return HealingHouseParams(enabled=True,
                              target_profiles=("groq", "cerebras", "mistral"))


# ── config: the flag defaults OFF and parses defensively ──────────────────────

def test_default_params_ship_disabled():
    assert HealingHouseParams().enabled is False
    assert HealingHouseParams().target_profiles == ()
    assert _world().healing_house_enabled() is False


def test_parse_healing_house_defensive():
    assert _parse_healing_house(None) == HealingHouseParams()
    assert _parse_healing_house({}) == HealingHouseParams()
    assert _parse_healing_house("junk") == HealingHouseParams()
    assert _parse_healing_house({"enabled": True}).enabled is True
    assert _parse_healing_house({"enabled": 0}).enabled is False
    # `mock` (silence) + blanks + garbage are stripped from the target pool.
    p = _parse_healing_house(
        {"target_profiles": ["groq", "mock", "", "cerebras", 7]})
    assert p.target_profiles == ("groq", "cerebras", "7")
    assert "mock" not in p.target_profiles
    # whisper_ticks clamps >= 0.
    assert _parse_healing_house({"whisper_ticks": -3}).whisper_ticks == 0


def test_never_swap_toward_silence():
    # Even if an operator mis-lists `mock`, the engine refuses it as a target.
    hh = HealingHouseParams(enabled=True, target_profiles=("mock",))
    w = _world(_params(hh))
    assert w.healing_target_profiles() == []
    assert w._pick_healing_profile(w.agents["b"]) is None


# ── flag OFF ⇒ byte-identical world surface ───────────────────────────────────

def test_flag_off_snapshot_is_byte_identical():
    w = _world()
    baseline = json.dumps(w.to_snapshot({}), sort_keys=True, default=str)
    ok, reason, rule = w.action_propose_rule(
        w.agents["a"], "heal", "nope", None, "Bo")
    assert ok is False and rule is None                # rejected with guidance
    assert "disabled" in reason
    after = json.dumps(w.to_snapshot({}), sort_keys=True, default=str)
    assert baseline == after
    assert "healings" not in w.to_snapshot({})["agents"][0]


def test_flag_off_prompt_is_byte_identical():
    w = _world()
    sys = _sys(w.agents["a"], w)
    assert "HEALING HOUSE" not in sys                  # no perception block
    assert "|heal" not in sys                          # no menu entry


def test_flag_off_runtime_gate_rejects_heal():
    w = _world()
    err = _validate_world({"action": "propose_rule",
                           "args": {"effect": "heal", "target": "Bo"}},
                          w.agents["a"], w)
    assert err is not None and "invalid effect" in err


# ── flag ON ⇒ the surface appears (the same world, one flag away) ─────────────

def test_flag_on_offers_the_heal_verb_with_a_concrete_patient():
    w = _world(_params(_on()))
    sys = _sys(w.agents["a"], w)
    assert "|heal" in sys
    assert "Healing House" in sys
    assert "Bo" in sys                                 # a concrete, resolvable target


def test_flag_on_runtime_gate_accepts_a_real_patient():
    w = _world(_params(_on()))
    assert _validate_world({"action": "propose_rule",
                            "args": {"effect": "heal", "target": "Bo"}},
                           w.agents["a"], w) is None
    # A vanished patient is rejected at the gate (menu/resolution agree).
    err = _validate_world({"action": "propose_rule",
                           "args": {"effect": "heal", "target": "ghost"}},
                          w.agents["a"], w)
    assert err is not None and "living" in err


def test_flag_on_but_no_distinct_model_rejects():
    # The pool holds ONLY the patient's current model ⇒ no distinct transplant ⇒
    # the propose is rejected (no guaranteed-no-op sentence).
    hh = HealingHouseParams(enabled=True, target_profiles=("groq",))
    w = _world(_params(hh))                             # everyone runs groq
    ok, reason, rule = w.action_propose_rule(
        w.agents["a"], "heal", "x", None, "Bo")
    assert ok is False and rule is None
    assert "no healer" in reason


def test_heal_is_a_70pct_supermajority_not_a_simple_majority():
    # 3 living ⇒ ceil(0.7*3)=3 yes needed; 2 yes must NOT pass (unlike an
    # ordinary majority rule, which would carry on 2/3).
    hh = _on()
    w = World(params=_params(hh),
              places=[PlaceState(id="plaza", name="Plaza", x=0, y=0,
                                 kind="social")],
              agents=[AgentState(id=i, name=i.upper(), personality="",
                                 profile="groq", location="plaza", energy=80.0,
                                 credits=20) for i in ("a", "b", "c")])
    ok, _, rule = w.action_propose_rule(w.agents["a"], "heal", "x", None, "B")
    assert ok is True
    w.action_vote(w.agents["a"], rule.id, True)
    w.action_vote(w.agents["b"], rule.id, True)
    w.action_vote(w.agents["c"], rule.id, False)       # 2 yes / 1 no — short of 3
    assert w.agents["b"].healings == 0                 # NOT healed on 2/3
    assert w.rules[rule.id].status == "rejected"


# ── the patient whisper drives the "came back different" arc ──────────────────

def test_recently_treated_patient_gets_the_whisper():
    hh = _on()
    w = _world(_params(hh))
    w.tick = 20
    patient = w.agents["b"]
    patient.healings = 1
    patient.pre_healing_profile = "groq"
    patient.treated_at_tick = 18                        # 2 ticks ago, within window
    sys = _sys(patient, w)
    assert "THE HEALING HOUSE" in sys
    assert "came back different" in sys
    assert "groq" in sys                                # the pre-treatment lane
    # A never-treated peer carries NO whisper (salience-gated).
    assert "THE HEALING HOUSE" not in _sys(w.agents["a"], w)


def test_whisper_expires_past_the_recency_window():
    hh = HealingHouseParams(enabled=True,
                            target_profiles=("groq", "cerebras"),
                            whisper_ticks=5)
    w = _world(_params(hh))
    w.tick = 100
    patient = w.agents["b"]
    patient.healings = 1
    patient.pre_healing_profile = "groq"
    patient.treated_at_tick = 10                        # 90 ticks ago — stale
    assert "HEALING HOUSE" not in _sys(patient, w)

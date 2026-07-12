"""EM-269 (F2) — found_settlement: deterministic founding, seeded ids/names,
the too_close gate, and len(settlements) > 1 as emergent multi-city."""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
from petridish.engine.world import World, AgentState, PlaceState, _SETTLEMENT_NAMES
from petridish.engine.citygraph import logical_to_world
from petridish.config.loader import WorldParams, SettlementParams


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


def _world(enabled=True):
    return World(
        params=_params(enabled),
        places=[
            PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
            PlaceState(id="ridge", name="Ridge", x=900, y=900, kind="social"),
        ],
        agents=[
            AgentState(id="a", name="Ann", personality="", profile="mock",
                       location="ridge", energy=80.0, credits=20),
            AgentState(id="b", name="Bob", personality="", profile="mock",
                       location="plaza", energy=80.0, credits=20),
        ])


# ── founding: event shape, seeded id, world-frame center, founder membership ──

def test_found_settlement_event_and_state():
    w = _world()
    evt = w.action_found_settlement(w.agents["a"], "river_camp")
    assert evt["kind"] == "settlement_founded"
    sid = evt["payload"]["settlement_id"]
    assert sid.startswith("stl_")                    # seeded id, never uuid4
    s = w.settlements[sid]
    assert s["name"] == "River Camp"                 # EM-129 humanization
    # center = the founder's place mapped logical→world ONCE at founding
    wx, wz = logical_to_world(900.0, 900.0)
    assert s["center"] == (round(wx, 4), round(wz, 4))
    assert evt["payload"]["center"] == [s["center"][0], s["center"][1]]
    assert s["founder_id"] == "a"
    assert s["members"] == ["a"]                     # founding IS joining
    assert w.settlement_of("a") == sid


def test_founding_is_deterministic_across_runs():
    def run():
        w = _world()
        evt = w.action_found_settlement(w.agents["a"], "river_camp")
        return (evt["payload"]["settlement_id"], evt["payload"]["name"],
                tuple(evt["payload"]["center"]))
    assert run() == run()                            # same seed ⇒ byte-identical


# ── names: junk falls back to the seeded pool; duplicates never collide ───────

def test_junk_name_falls_back_to_seeded_pool():
    w = _world()
    evt = w.action_found_settlement(w.agents["a"], "??!")
    assert evt["payload"]["name"] in _SETTLEMENT_NAMES


def test_duplicate_name_falls_back_to_unused_pool_name():
    w = _world()
    w.action_found_settlement(w.agents["a"], "Harborview")
    evt = w.action_found_settlement(w.agents["b"], "Harborview")
    assert evt["kind"] == "settlement_founded"
    name = evt["payload"]["name"]
    assert name != "Harborview" and name in _SETTLEMENT_NAMES


def test_exhausted_pool_numbers_the_town_never_crashes():
    w = _world()
    used = {"harborview"} | {n.casefold() for n in _SETTLEMENT_NAMES}
    w.settlements = {
        f"stl_{i:010x}": {"name": n, "center": (100.0 + 20.0 * i, 100.0),
                          "founded_tick": 0, "founder_id": "x", "members": []}
        for i, n in enumerate(sorted(used))
    }
    got = w._settlement_name("Harborview", "a")
    assert got and got.casefold() not in used        # numbered, still unique


# ── the too_close gate + emergent multi-city ──────────────────────────────────

def test_second_settlement_on_claimed_ground_is_rejected():
    w = _world()
    w.action_found_settlement(w.agents["a"], "First")
    w.agents["b"].location = "ridge"                 # same ground as First
    evt = w.action_found_settlement(w.agents["b"], "Second")
    assert evt["kind"] == "parse_failure"
    assert "First" in evt["text"]                    # guidance names the claimant
    assert len(w.settlements) == 1


def test_two_settlements_on_distinct_ground_is_emergent_multi_city():
    w = _world()
    w.action_found_settlement(w.agents["a"], "Ridge Town")   # at ridge
    w.action_found_settlement(w.agents["b"], "Plaza Town")   # at plaza (far)
    assert len(w.settlements) > 1                    # multi-city, no new model


def test_refounding_reassociates_the_founder():
    w = _world()
    e1 = w.action_found_settlement(w.agents["a"], "Old Home")
    w.agents["a"].location = "plaza"
    e2 = w.action_found_settlement(w.agents["a"], "New Home")
    old = w.settlements[e1["payload"]["settlement_id"]]
    assert old["members"] == []                      # loose membership moved
    assert w.settlement_of("a") == e2["payload"]["settlement_id"]


# ── guards: disabled flag + no location ───────────────────────────────────────

def test_disabled_flag_rejects_cleanly():
    w = _world(enabled=False)
    evt = w.action_found_settlement(w.agents["a"], "Nope")
    assert evt["kind"] == "parse_failure"
    assert w.settlements == {}


def test_nowhere_agent_rejects_cleanly():
    w = _world()
    w.agents["a"].location = "the-void"
    evt = w.action_found_settlement(w.agents["a"], "Nope")
    assert evt["kind"] == "parse_failure"
    assert w.settlements == {}

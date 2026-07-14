"""EM-110 — per-settlement perception scoping (the free-scale keystone): with
>1 city a homed agent perceives ONLY its own settlement's places, so its prompt
stays FLAT as cities grow. Single-city shows the full town; settlements OFF is
byte-identical to pre-EM-110.
"""
# CRITICAL: petridish.engine.world must be imported BEFORE
# petridish.agents.runtime to avoid the engine↔agents circular import.
import copy

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, SettlementParams
from petridish.agents.runtime import _assemble_context


def _params(enabled=True):
    p = WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                    energy_decay_per_turn=0.0, starting_energy=80.0,
                    starting_credits=20, snapshot_interval_ticks=100)
    p.settlements = SettlementParams(enabled=enabled)
    return p


_PLACES = [
    PlaceState(id="plaza",   name="Plaza",   x=500, y=500, kind="social"),
    PlaceState(id="well",    name="Well",    x=520, y=460, kind="social"),
    PlaceState(id="market",  name="Market",  x=560, y=520, kind="work"),
    PlaceState(id="ridge",   name="Ridge",   x=900, y=900, kind="social"),
    PlaceState(id="orchard", name="Orchard", x=860, y=880, kind="wild"),
    PlaceState(id="farm",    name="Farm",    x=900, y=820, kind="work"),
]
_GENESIS_CLUSTER = {"plaza", "well", "market"}
_RIDGE_CLUSTER = {"ridge", "orchard", "farm"}
_NAMES = ["Ann", "Bob", "Cleo", "Dex", "Eve"]


def _world(enabled=True, seed_genesis=True, n=5, at="plaza"):
    w = World(params=_params(enabled),
              places=[copy.copy(p) for p in _PLACES],
              agents=[AgentState(id=chr(ord("a") + i), name=_NAMES[i],
                                 personality="", profile="mock", location=at,
                                 energy=80.0, credits=20) for i in range(n)])
    if seed_genesis:
        w.seed_genesis_settlement()
    return w


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _move_to_places(sys_text):
    """The place ids offered on the move_to menu line."""
    for line in sys_text.splitlines():
        if "move_to (place)" in line:
            tail = line.split("go to one of:", 1)[1]
            return {p.strip() for p in tail.split(",") if p.strip()}
    return set()


def _found_ridge(w, agent_id="a"):
    w.agents[agent_id].location = "ridge"
    evt = w.action_found_settlement(w.agents[agent_id], "Ridgehold")
    return evt["payload"]["settlement_id"]


# ── settlement_of_place partitions the WHOLE map (no radius cap) ───────────────

def test_single_settlement_owns_every_place():
    w = _world()
    sid = next(iter(w.settlements))
    for p in w.places.values():
        assert w.settlement_of_place(p) == sid       # 1 city ⇒ whole town is it


def test_two_settlements_partition_by_nearest_center():
    w = _world()
    genesis = w.agents["b"].home_settlement_id
    ridge = _found_ridge(w)
    for pid in _GENESIS_CLUSTER:
        assert w.settlement_of_place(w.places[pid]) == genesis
    for pid in _RIDGE_CLUSTER:
        assert w.settlement_of_place(w.places[pid]) == ridge


def test_no_settlements_means_no_owner():
    w = _world(enabled=False, seed_genesis=True)     # OFF ⇒ no settlements
    assert w.settlement_of_place(w.places["plaza"]) is None


# ── single-city perception shows the FULL town (no scoping at len==1) ─────────

def test_single_city_move_to_shows_all_places():
    w = _world()
    places = _move_to_places(_sys(w.agents["b"], w))
    assert places == set(w.places)                   # every place visible


# ── two-city perception scopes each agent to its OWN settlement ───────────────

def test_two_cities_scope_home_places_only():
    w = _world()
    _found_ridge(w, agent_id="a")                    # 'a' now homes to Ridgehold
    # 'b' stays in genesis ⇒ sees only the genesis cluster
    genesis_agent_places = _move_to_places(_sys(w.agents["b"], w))
    assert genesis_agent_places == _GENESIS_CLUSTER
    assert not (genesis_agent_places & _RIDGE_CLUSTER)   # other city HIDDEN
    # 'a' homes to Ridgehold ⇒ sees only the ridge cluster
    ridge_agent_places = _move_to_places(_sys(w.agents["a"], w))
    assert ridge_agent_places == _RIDGE_CLUSTER


def test_second_city_keeps_prompt_flat():
    """The free-scale guarantee: adding a 2nd city does NOT inflate an agent's
    prompt — its visible-place set shrinks to its own city and the total prompt
    does not balloon (a non-scoped 2-city would append the whole other town)."""
    w = _world()
    before = _sys(w.agents["b"], w)
    before_places = _move_to_places(before)
    _found_ridge(w, agent_id="a")
    after = _sys(w.agents["b"], w)
    after_places = _move_to_places(after)
    # visible places SHRANK (per-city scoping kicked in)
    assert len(after_places) < len(before_places)
    assert after_places == _GENESIS_CLUSTER
    # total prompt stays flat: the roster/travel lines are bounded and offset by
    # the hidden city's places (never a per-city multiplication).
    assert len(after) <= len(before) + 300


# ── the 🏘 roster line gives flat cross-city awareness ─────────────────────────

def test_roster_line_summarizes_other_cities_compactly():
    w = _world()
    _found_ridge(w, agent_id="a")
    sys = _sys(w.agents["b"], w)
    assert "=== 🏘 SETTLEMENTS ===" in sys
    assert "Elsewhere:" in sys and "Ridgehold" in sys   # one-line awareness


# ── travel_to is offered ONLY when there is somewhere to go ───────────────────

def test_travel_menu_absent_with_one_city():
    w = _world()
    assert "travel_to (settlement)" not in _sys(w.agents["b"], w)


def test_travel_menu_present_with_two_cities():
    w = _world()
    ridge = _found_ridge(w, agent_id="a")
    sys = _sys(w.agents["b"], w)
    assert "travel_to (settlement)" in sys
    assert "Ridgehold" in sys                         # the reachable destination
    # a traveler mid-journey is not re-offered the verb (off-board)
    w.action_travel_to(w.agents["b"], ridge)
    sys2 = _sys(w.agents["b"], w)
    assert "travel_to (settlement)" not in sys2
    assert "You are traveling to Ridgehold" in sys2


# ── settlements OFF ⇒ byte-identical prompt (no block, no scoping, no verb) ────

def test_off_prompt_has_no_settlement_surface():
    w = _world(enabled=False, seed_genesis=True)
    sys = _sys(w.agents["b"], w)
    assert "SETTLEMENTS" not in sys
    assert "travel_to" not in sys
    assert _move_to_places(sys) == set(w.places)      # nothing scoped away

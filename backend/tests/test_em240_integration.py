"""
EM-240 capstone — the Crime & Justice engine proven end-to-end (Task 12).

These tests stitch the whole subsystem together: the seed persona cards carry
the new disposition/role schema; a witnessed crime accrues notoriety, an
enforcer escalates it to a town-hall trial, the town convicts, the defendant
serves the sentence and is released; and a criminal pact derives a faction.

Hermetic and offline (conftest pins EM_DB_PATH=':memory:'); worlds are built
via the World(params=..., places=[...], agents=[...]) idiom.
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, load_personas


def _params() -> WorldParams:
    return WorldParams(tick_interval_seconds=0.5, turns_per_day=999,
                       energy_decay_per_turn=0.0, starting_energy=80.0,
                       starting_credits=20, snapshot_interval_ticks=100)


def _world(agents):
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="gov", name="Hall", x=1, y=1, kind="governance"),
        PlaceState(id="jail", name="Jail", x=9, y=9, kind="civic"),
    ]
    return World(params=_params(), places=places, agents=agents)


def _a(id, loc, **kw):
    return AgentState(id=id, name=id.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def test_seed_personas_include_criminals_and_enforcers():
    cards = {c["name"]: c for c in load_personas()}
    # The new criminal cast carries disposition: criminal.
    assert cards["Roop"]["disposition"] == "criminal"
    assert cards["Sledge"]["disposition"] == "criminal"
    assert cards["Wisp"]["disposition"] == "criminal"
    # The opportunists.
    assert cards["Pip"]["disposition"] == "opportunist"
    assert cards["Reyes"]["disposition"] == "opportunist"
    # The enforcer beat — including Brick, promoted from a plain card.
    assert cards["Sheriff Cobb"]["role"] == "enforcer"
    assert cards["Reyes"]["role"] == "enforcer"
    assert cards["Brick"]["role"] == "enforcer"
    # The pre-EM-240 cast keeps the lawful/citizen defaults (additive schema).
    assert cards["Mox"]["disposition"] == "lawful"
    assert cards["Mox"]["role"] == "citizen"
    # Every seed card's suggested_profile names a real lane.
    real_lanes = {"groq-llama", "cerebras-glm", "kimi", "deepseek-pro",
                  "qwen-next", "gemini-flash"}
    for who in ("Roop", "Sledge", "Wisp", "Sheriff Cobb", "Reyes", "Pip"):
        assert cards[who]["suggested_profile"] in real_lanes, who


def test_crime_to_conviction_end_to_end():
    cop = _a("cop", "plaza", role="enforcer")
    crook = _a("crook", "plaza", disposition="criminal"); crook.credits = 50
    mark = _a("mark", "plaza"); mark.credits = 40
    eye = _a("eye", "plaza")
    world = _world([cop, crook, mark, eye])

    # 1. A witnessed heist builds notoriety (cop + eye are third-party witnesses).
    ok, _, amt = world.action_heist(crook, mark)
    assert ok and crook.notoriety > 0

    # 2. The cop escalates to a trial and the town convicts.
    cop.location = "gov"
    ok, _, rule = world.action_propose_rule(cop, "trial", "the heist", target="crook")
    assert ok
    for v in (cop, mark, eye):
        world.action_vote(v, rule.id, True)
    assert crook.crime_status == "jailed" and crook.location == "jail"

    # 3. Jailed crook serves the sentence and is released by advance_crime.
    world.tick = crook.crime_status_until_tick
    events = world.advance_crime()
    assert crook.crime_status is None
    assert any(e["kind"] == "released" for e in events)


def test_conspiracy_forms_a_faction():
    # faction_min_size defaults to 3, so a 2-member pact never clusters. The
    # boss recruits TWO accomplices; both accept, seeding mutual warm `ally`
    # edges to the boss (the hub). The connected component {boss, crew, lieu}
    # is size 3 → a real ring derives.
    boss = _a("boss", "plaza", disposition="criminal")
    crew = _a("crew", "plaza", disposition="criminal")
    lieu = _a("lieu", "plaza", disposition="criminal")
    other = _a("other", "plaza")
    world = _world([boss, crew, lieu, other])

    world.action_recruit(boss, crew)
    ok, _ = world.action_accept_contract(crew)
    assert ok
    world.action_recruit(boss, lieu)
    ok, _ = world.action_accept_contract(lieu)
    assert ok

    # Mutual warm ally edges above faction_trust (25) tie the ring together.
    assert boss.relationships["crew"].type == "ally"
    assert crew.relationships["boss"].type == "ally"
    assert boss.relationships["lieu"].type == "ally"
    assert lieu.relationships["boss"].type == "ally"

    # recompute_factions returns the DIFF events; the derived faction state
    # lives in world.factions (and the public faction_of accessor). Adapt the
    # plan's snippet — it assumed the return value was faction dicts.
    events = world.recompute_factions()
    assert events, "forming a 3-member ring must emit a faction event"
    member_sets = [set(f["members"]) for f in world.factions.values()]
    assert any({"boss", "crew", "lieu"} <= m for m in member_sets), member_sets
    # The uninvolved citizen is in no ring.
    assert all("other" not in m for m in member_sets)
    # The ring is reachable through the public per-agent accessor too.
    ring = world.faction_of("boss")
    assert ring is not None and {"boss", "crew", "lieu"} <= set(ring["members"])
    assert world.faction_of("other") is None

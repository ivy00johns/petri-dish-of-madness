import jsonschema

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.agents.runtime import ACTION_SCHEMA, _assemble_context
from petridish.config.loader import WorldParams


def _prompt_text(ctx) -> str:
    """_assemble_context returns a list of {role, content} messages; join the
    contents so substring assertions read the whole rendered prompt."""
    if isinstance(ctx, list):
        return "\n".join(str(m.get("content", "")) for m in ctx)
    if isinstance(ctx, dict):
        return str(ctx.get("system") or ctx.get("user") or ctx)
    return str(ctx)


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


def test_unwitnessed_crime_adds_no_notoriety_but_records_rap_sheet():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    world = _world([thief, victim])
    witnessed = world._register_crime(thief, "steal", victim.id, 6)
    assert witnessed is False               # only the victim present → not witnessed
    assert thief.notoriety == 0
    assert thief.rap_sheet[-1] == {"tick": 0, "crime": "steal",
                                   "victim_id": "victim", "witnessed": False}


def test_witnessed_crime_adds_notoriety_and_can_flip_wanted():
    thief, victim = _a("thief", "alley"), _a("victim", "alley")
    bystander = _a("nosy", "alley")
    world = _world([thief, victim, bystander])
    world._register_crime(thief, "heist", victim.id, 45)
    assert thief.notoriety == 45
    assert thief.crime_status == "wanted"   # 45 >= wanted_threshold (40)


def test_advance_crime_decays_notoriety_and_clears_wanted():
    thief = _a("thief", "alley")
    thief.notoriety = 41
    thief.crime_status = "wanted"
    world = _world([thief])
    world.tick = 1
    world.advance_crime()                   # decay 2 → 39, below threshold
    assert thief.notoriety == 39
    assert thief.crime_status is None


def test_advance_crime_releases_jailed_at_expiry():
    con = _a("con", "jail")
    con.crime_status = "jailed"
    con.crime_status_until_tick = 5
    con.notoriety = 50
    world = _world([con])
    world.tick = 5
    events = world.advance_crime()
    assert con.crime_status is None
    assert con.notoriety == 40              # released_notoriety_relief (10) burned
    assert any(e["kind"] == "released" for e in events)


# ── Task 6 — offensive crime verbs: heist, extort, vandalize ──────────────────

def test_heist_takes_more_than_steal_and_builds_notoriety_when_witnessed():
    robber = _a("robber", "alley"); robber.credits = 0
    mark = _a("mark", "alley"); mark.credits = 50
    eye = _a("eye", "alley")
    world = _world([robber, mark, eye])
    ok, reason, amount = world.action_heist(robber, mark)
    assert ok and reason == "ok"
    assert amount == 30                      # heist_max
    assert robber.credits == 30 and mark.credits == 20
    assert robber.notoriety == 18           # heist_notoriety, witnessed by `eye`


def test_heist_rejected_when_target_too_poor():
    robber = _a("robber", "alley")
    mark = _a("mark", "alley"); mark.credits = 5   # below heist_min_target_credits (15)
    world = _world([robber, mark])
    ok, reason, amount = world.action_heist(robber, mark)
    assert not ok and amount == 0


def test_extort_transfers_credits_and_snaps_rivalry():
    thug = _a("thug", "alley"); thug.credits = 0
    shop = _a("shop", "alley"); shop.credits = 40
    world = _world([thug, shop])
    ok, reason, amount = world.action_extort(thug, shop)
    assert ok and amount == 15              # extort_max
    assert thug.credits == 15 and shop.credits == 25
    # victim now sees the extorter as at least a rival
    assert shop.relationships[thug.id].type in ("rival", "enemy", "feud")


def test_vandalize_blacks_out_building_and_records_crime():
    vandal = _a("vandal", "plaza")
    world = _world([vandal])
    world.buildings["b1"] = Building(id="b1", name="Stall", kind="workshop",
                                     location="plaza", status="operational", health=100)
    evt = world.action_vandalize(vandal, "b1")
    assert isinstance(evt, dict) and evt["kind"] == "crime_committed"
    assert world.places["plaza"].blackout_until_tick > world.tick
    assert vandal.rap_sheet[-1]["crime"] == "vandalize"


def test_vandalize_unknown_building_is_parse_failure():
    vandal = _a("vandal", "plaza")
    world = _world([vandal])
    evt = world.action_vandalize(vandal, "nope")
    assert isinstance(evt, dict) and evt["kind"] == "parse_failure"
    assert vandal.rap_sheet == []           # no crime recorded for a phantom target


# ── Task 6 — CONTRACT C: crime menu is offered only to the inclined ───────────

def test_crime_menu_offered_to_inclined_only():
    inclined = _a("inclined", "alley", disposition="opportunist")
    mark = _a("mark", "alley")
    world = _world([inclined, mark])
    world.buildings["b1"] = Building(id="b1", name="Stall", kind="workshop",
                                     location="alley", status="operational", health=100)
    prompt = _prompt_text(_assemble_context(inclined, world, [], world.params))
    assert "heist (target)" in prompt
    assert "extort (target)" in prompt
    assert "vandalize (building_id)" in prompt


def test_crime_menu_hidden_from_lawful():
    lawful = _a("lawful", "alley")             # disposition defaults to "lawful"
    mark = _a("mark", "alley")
    world = _world([lawful, mark])
    world.buildings["b1"] = Building(id="b1", name="Stall", kind="workshop",
                                     location="alley", status="operational", health=100)
    prompt = _prompt_text(_assemble_context(lawful, world, [], world.params))
    assert "heist (target)" not in prompt
    assert "extort (target)" not in prompt
    assert "vandalize (building_id)" not in prompt


def test_action_schema_accepts_new_crime_verbs():
    # A verb the LLM cannot emit (schema-rejected) is legal-but-unreachable; the
    # new crime verbs must validate as both a single action and an actions step.
    for verb in ("heist", "extort", "vandalize"):
        jsonschema.validate({"action": verb, "args": {}}, ACTION_SCHEMA)
        jsonschema.validate({"actions": [{"action": verb, "args": {}}]}, ACTION_SCHEMA)


# ── Task 7 — economy & corruption verbs: launder, bribe ───────────────────────

def test_launder_reduces_notoriety_for_a_cut():
    crook = _a("crook", "alley"); crook.credits = 100; crook.notoriety = 30
    world = _world([crook])
    ok, reason, fee = world.action_launder(crook, 50)
    assert ok and fee == 15                  # launder_cut 0.3 * 50
    assert crook.credits == 85
    assert crook.notoriety == 22             # launder_notoriety_reduction (8)


def test_launder_rejected_when_clean():
    crook = _a("crook", "alley"); crook.notoriety = 0
    world = _world([crook])
    ok, reason, fee = world.action_launder(crook, 10)
    assert not ok and fee == 0


def test_bribe_wipes_payer_notoriety_and_pays_enforcer():
    crook = _a("crook", "alley"); crook.credits = 40; crook.notoriety = 40
    crook.crime_status = "wanted"
    cop = _a("cop", "alley", role="enforcer")
    world = _world([crook, cop])
    ok, reason, paid = world.action_bribe(crook, cop, 20)
    assert ok and paid == 20
    assert cop.credits == 40
    assert crook.notoriety == 10             # 40 * (1 - 0.75)
    assert crook.crime_status is None        # dropped below wanted_threshold


def test_witnessed_bribe_dirties_the_enforcer():
    crook = _a("crook", "alley"); crook.credits = 40; crook.notoriety = 40
    cop = _a("cop", "alley", role="enforcer")
    snitch = _a("snitch", "alley")
    world = _world([crook, cop, snitch])
    world.action_bribe(crook, cop, 20)
    assert cop.notoriety == 14               # bribe_notoriety, witnessed by snitch
    assert cop.rap_sheet[-1]["crime"] == "bribery"


# ── Task 7 — CONTRACT C: launder/bribe menu lines, gated by the design ────────

def test_launder_menu_offered_to_inclined_with_notoriety():
    crook = _a("crook", "alley", disposition="opportunist")
    crook.notoriety = 20                       # something to cool
    world = _world([crook])
    prompt = _prompt_text(_assemble_context(crook, world, [], world.params))
    assert "launder (amount)" in prompt


def test_launder_menu_hidden_when_clean():
    crook = _a("crook", "alley", disposition="opportunist")  # notoriety defaults 0
    world = _world([crook])
    prompt = _prompt_text(_assemble_context(crook, world, [], world.params))
    assert "launder (amount)" not in prompt


def test_bribe_menu_offered_when_wanted_and_cop_present():
    crook = _a("crook", "alley", disposition="opportunist")
    crook.notoriety = 40
    cop = _a("cop", "alley", role="enforcer")
    world = _world([crook, cop])
    prompt = _prompt_text(_assemble_context(crook, world, [], world.params))
    assert "bribe (target, amount)" in prompt
    assert "Cop" in prompt                     # the enforcer is named as a target


def test_bribe_menu_hidden_without_co_located_enforcer():
    crook = _a("crook", "alley", disposition="opportunist")
    crook.notoriety = 40
    plain = _a("plain", "alley")               # co-located but not an enforcer
    world = _world([crook, plain])
    prompt = _prompt_text(_assemble_context(crook, world, [], world.params))
    assert "bribe (target, amount)" not in prompt


def test_bribe_menu_hidden_when_clean():
    crook = _a("crook", "alley", disposition="opportunist")  # notoriety 0
    cop = _a("cop", "alley", role="enforcer")
    world = _world([crook, cop])
    prompt = _prompt_text(_assemble_context(crook, world, [], world.params))
    assert "bribe (target, amount)" not in prompt


def test_action_schema_accepts_launder_and_bribe():
    for verb in ("launder", "bribe"):
        jsonschema.validate({"action": verb, "args": {}}, ACTION_SCHEMA)
        jsonschema.validate({"actions": [{"action": verb, "args": {}}]}, ACTION_SCHEMA)


# ── Task 8 — conspiracy verbs: recruit, accept_contract ───────────────────────

def test_recruit_posts_offer_without_committing_crime():
    boss = _a("boss", "alley"); crew = _a("crew", "alley")
    world = _world([boss, crew])
    evt = world.action_recruit(boss, crew)
    assert evt["kind"] == "recruited"
    assert world.pending_crime_offers.get("crew", {}).get("recruiter_id") == "boss"
    assert crew.notoriety == 0               # no crime yet


def test_accept_contract_forms_a_warm_pact():
    boss = _a("boss", "alley"); crew = _a("crew", "alley")
    world = _world([boss, crew])
    world.action_recruit(boss, crew)
    ok, reason = world.action_accept_contract(crew)
    assert ok
    # Mutual warm edges (ally) above faction_trust → a ring can derive.
    assert boss.relationships["crew"].type == "ally"
    assert crew.relationships["boss"].type == "ally"
    assert boss.relationships["crew"].trust >= 25
    assert crew.notoriety == 6 and boss.notoriety == 6   # conspiracy_notoriety
    assert "crew" not in world.pending_crime_offers       # consumed


def test_accept_contract_without_offer_is_rejected():
    lone = _a("lone", "alley")
    world = _world([lone])
    ok, reason = world.action_accept_contract(lone)
    assert not ok


def test_recruit_menu_offered_to_inclined_only():
    inclined = _a("inclined", "alley", disposition="opportunist")
    mark = _a("mark", "alley")
    world = _world([inclined, mark])
    prompt = _prompt_text(_assemble_context(inclined, world, [], world.params))
    assert "recruit (target)" in prompt


def test_recruit_menu_hidden_from_lawful():
    lawful = _a("lawful", "alley")             # disposition defaults to "lawful"
    mark = _a("mark", "alley")
    world = _world([lawful, mark])
    prompt = _prompt_text(_assemble_context(lawful, world, [], world.params))
    assert "recruit (target)" not in prompt


def test_accept_contract_menu_only_when_offer_pending():
    boss = _a("boss", "alley"); crew = _a("crew", "alley")
    world = _world([boss, crew])
    # No offer yet → no accept_contract line for the would-be recruit.
    prompt = _prompt_text(_assemble_context(crew, world, [], world.params))
    assert "accept_contract" not in prompt
    # Post an offer → accept_contract is now offered to the addressed agent only.
    world.action_recruit(boss, crew)
    prompt_crew = _prompt_text(_assemble_context(crew, world, [], world.params))
    assert "accept_contract" in prompt_crew
    prompt_boss = _prompt_text(_assemble_context(boss, world, [], world.params))
    assert "accept_contract" not in prompt_boss


def test_action_schema_accepts_conspiracy_verbs():
    for verb in ("recruit", "accept_contract"):
        jsonschema.validate({"action": verb, "args": {}}, ACTION_SCHEMA)
        jsonschema.validate({"actions": [{"action": verb, "args": {}}]}, ACTION_SCHEMA)

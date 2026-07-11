# backend/tests/test_em250_extraction.py
"""EM-250 — extraction behavior-identity + the new shared seams.

Two spec-approved extractions must be BEHAVIOR-IDENTICAL:
  * _plant_belief from action_deceive's FIFO block (deceive still craters
    trust + registers a crime — its EM-237 tests pass unchanged; here we pin
    the seam itself);
  * _recompute_groups from recompute_factions (same fct_ ids, "'s circle"
    names, faction_* diff events, pending_spawn_events parking — the Wave-E
    faction tests pass unchanged; here we pin the generic clusterer).

Plus the new seams: _attach_meme carrier bookkeeping and the deterministic
_distort_text mutation table (zero random — EM-155).
"""
from petridish.engine.world import World, AgentState, PlaceState, RelationshipState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _agent(aid: str, name: str) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location="plaza", energy=80.0, credits=20)


def _world(agents: list[AgentState]) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    return World(params=_params(), places=places, agents=agents)


def _bond(a: AgentState, b: AgentState, trust: int = 40) -> None:
    a.relationships[b.id] = RelationshipState(type="ally", trust=trust,
                                              interactions=3)
    b.relationships[a.id] = RelationshipState(type="ally", trust=trust,
                                              interactions=3)


# ── _plant_belief (extracted from deceive) ───────────────────────────────────

def test_plant_belief_plants_prefixed_and_dedupes():
    ada, bram = _agent("ada", "Ada"), _agent("bram", "Bram")
    w = _world([ada, bram])
    w._plant_belief(bram, "Ada", "the well is cursed")
    assert bram.beliefs == ["Ada told me: the well is cursed"]
    w._plant_belief(bram, "Ada", "the well is cursed")   # dedupe — no double
    assert len(bram.beliefs) == 1


def test_plant_belief_fifo_caps_like_remember():
    ada, bram = _agent("ada", "Ada"), _agent("bram", "Bram")
    w = _world([ada, bram])
    w.params.memory = {"consolidate_at": 2}              # EM-279: cap = 2 + 1
    bram.beliefs = ["b1", "b2", "b3"]
    w._plant_belief(bram, "Ada", "newest")
    assert bram.beliefs == ["b2", "b3", "Ada told me: newest"]


def test_deceive_is_a_plant_belief_caller_behavior_identical():
    liar, dupe = _agent("liar", "Liar"), _agent("dupe", "Dupe")
    w = _world([liar, dupe])
    ok, reason = w.action_deceive(liar, dupe, "the well is poisoned")
    assert ok is True
    # The planted belief is byte-identical to the pre-extraction format …
    assert dupe.beliefs[-1] == "Liar told me: the well is poisoned"
    # … and deceive's diverging side-effects stayed at the call site:
    assert dupe.relationships["liar"].trust == -12       # trust crater
    assert liar.rap_sheet[-1]["crime"] == "deceive"      # crime registered


# ── _recompute_groups (extracted from recompute_factions) ────────────────────

def test_recompute_factions_thin_caller_keeps_wave_e_vocabulary():
    agents = [_agent(f"a{i}", f"A{i}") for i in range(3)]
    w = _world(agents)
    for i in range(3):
        for j in range(i + 1, 3):
            _bond(agents[i], agents[j])
    events = w.recompute_factions()
    assert [e["kind"] for e in events] == ["faction_formed"]
    fid = events[0]["payload"]["faction_id"]
    assert fid.startswith("fct_") and len(fid) == len("fct_") + 8
    assert w.factions[fid]["name"].endswith("'s circle")
    assert w.factions[fid]["members"] == ["a0", "a1", "a2"]
    # Events still park in the pending_spawn_events outbox (same drain).
    assert events[0] in w.pending_spawn_events


def test_recompute_groups_generic_kind_forms_and_labels():
    agents = [_agent(f"a{i}", f"A{i}") for i in range(4)]
    w = _world(agents)
    camp = {"a0", "a1", "a2"}
    edge_fn = lambda a, b: {a.id, b.id} <= camp
    store, events = w._recompute_groups(edge_fn, {}, 2, "culture_camp")
    assert len(store) == 1
    gid = next(iter(store))
    assert gid.startswith("cmp_")
    assert store[gid]["members"] == ["a0", "a1", "a2"]
    assert store[gid]["name"] == "A0's camp"
    assert [e["kind"] for e in events] == ["culture_camp_formed"]
    assert events[0]["payload"]["culture_camp_id"] == gid
    # The caller owns the store + outbox: nothing was written to the world.
    assert w.culture_camps == {} and w.pending_spawn_events == []


def test_recompute_groups_identity_continuity_and_dissolve():
    agents = [_agent(f"a{i}", f"A{i}") for i in range(3)]
    w = _world(agents)
    camp = {"a0", "a1", "a2"}
    edge_fn = lambda a, b: {a.id, b.id} <= camp
    store, _ = w._recompute_groups(edge_fn, {}, 2, "culture_camp")
    gid = next(iter(store))
    # A stable membership keeps its id and emits NO events (diff-only).
    store2, events2 = w._recompute_groups(edge_fn, store, 2, "culture_camp")
    assert list(store2) == [gid] and events2 == []
    # Edges gone ⇒ the group dissolves.
    store3, events3 = w._recompute_groups(lambda a, b: False, store2, 2,
                                          "culture_camp")
    assert store3 == {}
    assert [e["kind"] for e in events3] == ["culture_camp_dissolved"]
    assert events3[0]["payload"]["culture_camp_id"] == gid


def test_recompute_groups_min_size_gate():
    agents = [_agent(f"a{i}", f"A{i}") for i in range(2)]
    w = _world(agents)
    edge_fn = lambda a, b: True
    store, events = w._recompute_groups(edge_fn, {}, 3, "culture_camp")
    assert store == {} and events == []                  # size 2 < min_size 3


# ── _attach_meme ─────────────────────────────────────────────────────────────

def test_attach_meme_adds_holder_and_carrier():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    w.tick = 4
    m = w.mint_meme("rumor", "the bakery is haunted", "ada")
    assert w._attach_meme(ada, m) is True
    assert ada.held_memes == [m.id]
    assert m.carriers == ["ada"]
    assert m.last_spread_tick == 4


def test_attach_meme_is_idempotent():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    m = w.mint_meme("rumor", "t", "ada")
    assert w._attach_meme(ada, m) is True
    assert w._attach_meme(ada, m) is False
    assert ada.held_memes == [m.id] and m.carriers == ["ada"]


def test_attach_meme_fifo_evicts_oldest_and_drops_carrier():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    w.params.comm = {"held_meme_cap": 2}
    m1 = w.mint_meme("rumor", "one", "ada")
    m2 = w.mint_meme("rumor", "two", "ada")
    m3 = w.mint_meme("rumor", "three", "ada")
    for m in (m1, m2, m3):
        w._attach_meme(ada, m)
    assert ada.held_memes == [m2.id, m3.id]              # oldest evicted
    assert m1.carriers == []                             # …and left its carriers
    assert m2.carriers == ["ada"] and m3.carriers == ["ada"]


# ── _distort_text (deterministic mutation table) ─────────────────────────────

def test_distort_text_substitutes_table_word_deterministically():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    out = w._distort_text("Ada borrowed bread from the stall", 7, "bram")
    assert out == "Ada stole bread from the stall"
    # Zero random: the same (text, seed parts) always mutates identically.
    assert out == w._distort_text("Ada borrowed bread from the stall", 7, "bram")


def test_distort_text_appends_suffix_when_nothing_matches():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    text = "A quiet evening at the plaza"
    out = w._distort_text(text, 3, "bram")
    assert out.startswith(text) and out != text
    assert out == w._distort_text(text, 3, "bram")       # deterministic


def test_distort_text_strength_zero_is_identity():
    ada = _agent("ada", "Ada")
    w = _world([ada])
    w.params.comm = {"distortion_strength": 0}
    assert w._distort_text("Ada borrowed bread", 1) == "Ada borrowed bread"

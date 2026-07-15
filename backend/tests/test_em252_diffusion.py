# backend/tests/test_em252_diffusion.py
"""EM-252 — the once-per-round PASSIVE culture-diffusion sweep (diffuse_culture).

Three PURE-COMPUTE mechanics — zero LLM, no clock, no RNG (EM-155):
  * passive seeded diffusion — a co-located non-carrier catches a DRIFTED CHILD
    meme (parent_id + generation+1 + _distort_text), gated by the seeded roll;
    the sweep is capped at comm.max_diffusions and emits `meme_mutated`;
  * half-life virality decay — an idle meme halves virality with `//` floor;
  * decay-prune ("death of an idea") — a zero-carrier aged-out meme is deleted
    with a `meme_died` event; a meme that still has carriers is NEVER pruned.

Also pins the hard laws: determinism (byte-identical registries + stable
infection set), the _apply_round_start order invariant (recompute_factions →
diffuse_culture → advance_war → age_agents), the flag-OFF golden (comm disabled
⇒ [] that parks nothing / mutates nothing), and the free-image cost rule (TEXT
ONLY — never a gallery entry, never an image_id on a child).

Mirrors test_em250_extraction (meme seams) + test_em256_grievance (order test).
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, loc: str = "plaza", **kw) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def _world(agents: list[AgentState], comm: dict | None = None) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
              PlaceState(id="field", name="Field", x=5, y=5, kind="nature")]
    w = World(params=_params(), places=places, agents=agents)
    if comm is not None:
        w.params.comm = comm
    return w


def _on(**over) -> dict:
    """comm block with the master gate ON (plus overrides)."""
    return {"enabled": True, **over}


# ── 1) Passive seeded diffusion ──────────────────────────────────────────────

def test_carrier_infects_colocated_noncarrier_with_drifted_child():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    w.tick = 5
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, source)

    events = w.diffuse_culture()

    # Bram caught a DRIFTED CHILD (not the source itself).
    assert len(bram.held_memes) == 1
    child = w.memes[bram.held_memes[0]]
    assert child.id != source.id
    assert child.parent_id == source.id
    assert child.generation == source.generation + 1 == 1
    assert child.text == "Ada stole bread"        # deterministic distortion
    assert child.text != source.text
    assert bram.id in child.carriers
    # …and a meme_mutated event carries the lineage.
    muts = [e for e in events if e["kind"] == "meme_mutated"]
    assert len(muts) == 1
    assert muts[0]["target_id"] == "bram"
    assert muts[0]["actor_id"] == "ada"
    assert muts[0]["actor_type"] == "system"
    assert muts[0]["payload"] == {"meme_id": child.id, "parent_id": source.id,
                                  "generation": 1}


def test_no_infection_when_diffusion_chance_zero():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=0.0))
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, source)

    events = w.diffuse_culture()

    assert events == []
    assert bram.held_memes == []
    assert list(w.memes) == [source.id]           # no child minted


def test_only_colocated_agents_catch_the_meme():
    ada, far = _a("ada"), _a("far", loc="field")
    w = _world([ada, far], _on(diffusion_chance=1.0))
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, source)

    events = w.diffuse_culture()

    assert events == []                            # not co-located
    assert far.held_memes == []


def test_infection_count_never_exceeds_max_diffusions():
    ada = _a("ada")
    others = [_a(n) for n in ("bram", "cal", "dot", "eli", "fin")]
    w = _world([ada, *others], _on(diffusion_chance=1.0, max_diffusions=2))
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, source)

    events = w.diffuse_culture()

    muts = [e for e in events if e["kind"] == "meme_mutated"]
    assert len(muts) == 2                          # capped
    infected = [o for o in others if o.held_memes]
    assert len(infected) == 2
    # The sorted walk takes the two LOWEST-id candidates first (deterministic).
    assert [o.id for o in infected] == ["bram", "cal"]


def test_existing_carrier_is_not_reinfected():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, source)
    w._attach_meme(bram, source)                   # bram already carries it

    events = w.diffuse_culture()

    assert events == []                            # no candidate to infect
    assert bram.held_memes == [source.id]


# ── 2) Determinism (EM-155) ──────────────────────────────────────────────────

def _det_world() -> World:
    ada = _a("ada")
    crowd = [_a(f"z{i:02d}") for i in range(6)]
    w = _world([ada, *crowd], _on(diffusion_chance=0.5))
    w.tick = 9
    src = w.mint_meme("rumor", "Ada borrowed bread from the stall", "ada")
    w._attach_meme(ada, src)
    return w


def _registry(w: World) -> dict:
    return {mid: w.memes[mid].to_dict() for mid in sorted(w.memes)}


def test_two_identical_worlds_diffuse_byte_identically():
    a, b = _det_world(), _det_world()
    a.diffuse_culture()
    b.diffuse_culture()
    assert _registry(a) == _registry(b)            # byte-identical registries
    # …and the infection SET (who caught something) is stable across runs.
    inf_a = sorted(ag.id for ag in a.agents.values() if len(ag.held_memes) and
                   ag.id != "ada")
    inf_b = sorted(ag.id for ag in b.agents.values() if len(ag.held_memes) and
                   ag.id != "ada")
    assert inf_a == inf_b
    # The 0.5 gate actually GATED — a mix, not all-or-nothing.
    assert 0 < len(inf_a) < 6


# ── 3) Half-life virality decay ──────────────────────────────────────────────

def test_half_life_halves_virality_with_floor():
    ada = _a("ada")
    w = _world([ada], _on(half_life_ticks=30))
    m = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, m)                          # keep a carrier (no prune)
    m.virality = 7
    m.last_spread_tick = 0
    w.tick = 30                                     # exactly one half-life idle

    w.diffuse_culture()

    assert m.virality == 3                          # 7 // 2 — floor, not 3.5
    assert m.id in w.memes


def test_half_life_leaves_fresh_meme_untouched():
    ada = _a("ada")
    w = _world([ada], _on(half_life_ticks=30))
    m = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, m)
    m.virality = 8
    m.last_spread_tick = 10
    w.tick = 20                                     # 10 idle < 30

    w.diffuse_culture()

    assert m.virality == 8                          # untouched


# ── 4) Decay-prune ("death of an idea") ──────────────────────────────────────

def test_zero_carrier_aged_meme_is_pruned_and_emits_meme_died():
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80))
    dead = w.mint_meme("rumor", "a forgotten idea", "ada")   # zero carriers
    dead.last_spread_tick = 0
    w.tick = 80

    events = w.diffuse_culture()

    assert dead.id not in w.memes                   # deleted
    died = [e for e in events if e["kind"] == "meme_died"]
    assert len(died) == 1
    assert died[0]["payload"]["meme_id"] == dead.id
    assert died[0]["actor_type"] == "system"


def test_meme_with_carriers_is_never_pruned():
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80))
    kept = w.mint_meme("rumor", "a living idea", "ada")
    w._attach_meme(ada, kept)                        # has a carrier
    kept.last_spread_tick = 0
    w.tick = 200                                     # well past decay_ticks

    events = w.diffuse_culture()

    assert kept.id in w.memes                        # NEVER pruned
    assert not [e for e in events if e["kind"] == "meme_died"]


def test_young_zero_carrier_meme_survives():
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80))
    young = w.mint_meme("rumor", "a fresh idea", "ada")
    young.last_spread_tick = 0
    w.tick = 79                                      # 79 < 80

    events = w.diffuse_culture()

    assert young.id in w.memes
    assert not [e for e in events if e["kind"] == "meme_died"]


# ── 5) The round-start chain order invariant ─────────────────────────────────

def test_round_start_chain_order_factions_diffuse_war_aging():
    """The canonical Wave-O chain: recompute_factions → diffuse_culture →
    recompute_congregations (EM-262, now LIVE) → advance_war → age_agents. Mirrors
    test_em256_grievance's order test, pinning the now-LIVE diffuse_culture +
    recompute_congregations slots between recompute_factions and advance_war."""
    w = _world([_a("ada")])
    calls: list[str] = []
    orig_rf, orig_dc, orig_rc, orig_aw, orig_age = (
        w.recompute_factions, w.diffuse_culture, w.recompute_congregations,
        w.advance_war, w.age_agents)
    w.recompute_factions = (
        lambda: (calls.append("recompute_factions"), orig_rf())[1])
    w.diffuse_culture = (
        lambda: (calls.append("diffuse_culture"), orig_dc())[1])
    w.recompute_congregations = (
        lambda: (calls.append("recompute_congregations"), orig_rc())[1])
    w.advance_war = lambda: (calls.append("advance_war"), orig_aw())[1]
    w.age_agents = (
        lambda pre: (calls.append("age_agents"), orig_age(pre))[1])

    w._apply_round_start()

    for name in ("recompute_factions", "diffuse_culture",
                 "recompute_congregations", "advance_war", "age_agents"):
        assert name in calls
    assert (calls.index("recompute_factions")
            < calls.index("diffuse_culture")
            < calls.index("recompute_congregations")
            < calls.index("advance_war")
            < calls.index("age_agents"))


# ── 6) Flag-OFF golden ───────────────────────────────────────────────────────

def test_diffuse_culture_is_a_no_op_when_comm_disabled():
    """comm.enabled defaults FALSE ⇒ diffuse_culture returns [] and mutates
    NOTHING — even against state that WOULD otherwise diffuse / decay / prune."""
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram])                          # no comm block ⇒ default OFF
    # Plant state that a live sweep would touch: a carried meme with a
    # co-located non-carrier, plus a zero-carrier aged-out meme.
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, src)
    src.virality = 8
    stale = w.mint_meme("rumor", "an old idea", "ada")
    stale.last_spread_tick = 0
    w.tick = 500
    before = _registry(w)

    events = w.diffuse_culture()

    assert events == []                              # parks nothing
    assert w.pending_spawn_events == []
    assert _registry(w) == before                    # byte-identical: no mutation
    assert bram.held_memes == []
    assert src.virality == 8                          # no half-life decay
    assert stale.id in w.memes                        # no prune


def test_diffuse_culture_self_parks_events_like_factions():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, src)

    events = w.diffuse_culture()

    assert events                                    # non-empty
    # Events land in the pending_spawn_events outbox (same drain as factions).
    for e in events:
        assert e in w.pending_spawn_events


# ── 7) Free-image cost rule (TEXT ONLY) ──────────────────────────────────────

def test_diffusion_never_touches_the_gallery_or_sets_an_image_id():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, src)
    assert w.gallery == []

    w.diffuse_culture()

    assert w.gallery == []                            # never an image
    child = w.memes[bram.held_memes[0]]
    assert child.image_id is None                     # TEXT ONLY
    for m in w.memes.values():
        assert m.image_id is None

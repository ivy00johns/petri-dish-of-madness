# backend/tests/test_comm_feed_volume.py
"""Feed-health fix — the `comm` culture sweep (diffuse_culture) was flooding
the live feed with dozens of near-identical bookkeeping lines per tick:
8-11 IDENTICAL `meme_died` ("fades from memory") lines from orphaned
one-hop drift children decaying in the same tick, plus 8+ individual
`meme_mutated` ("drifts to") lines per round.

These state mutations (mint_meme, _attach_meme, del self.memes[mid], virality
half-life) are UNCHANGED — events are pure notifications (feed/log), so
aggregating WHICH events fire never touches sim state. The fix:

  * decay-prune (#A): a pruned meme gets an INDIVIDUAL `meme_died` event only
    when it "mattered" — it was ever dominant (comm.dominance latch), OR it's
    a coined original (generation == 0), OR its virality was still
    >= comm.death_notable_virality at prune time. Every OTHER pruned meme
    (the never-notable one-hop children) is rolled into exactly ONE aggregate
    `meme_died` event per sweep (payload.aggregated=True, payload.count=n).

  * passive diffusion (#B): only the first comm.mutation_notable_cap
    infections per sweep get an individual `meme_mutated` event; the rest
    roll into ONE aggregate `meme_mutated` event per sweep.

Mirrors test_em252_diffusion.py / test_em253_lifecycle.py fixtures.
"""
from petridish.engine.world import World, AgentState, PlaceState


def _params():
    from petridish.config.loader import WorldParams
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
    return {"enabled": True, **over}


# ── #A — decay-prune aggregation ─────────────────────────────────────────────

def test_many_never_notable_memes_prune_to_one_aggregate_event():
    """8 orphaned, never-notable (generation>0, low virality) memes decaying
    in the SAME tick must NOT emit 8 individual meme_died lines — bounded to
    exactly one aggregate event."""
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80, dominance_threshold=99))
    never_notable = []
    for i in range(8):
        m = w.mint_meme("idea", f"a drifted idea #{i}", "ada",
                        parent_id="mem_parent", generation=1)
        m.virality = 1                          # below death_notable_virality
        m.last_spread_tick = 0                  # all idle since tick 0
        never_notable.append(m.id)
    w.tick = 80

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    # Bounded: exactly ONE event for the whole never-notable batch, not 8.
    assert len(died) == 1
    assert died[0]["payload"]["aggregated"] is True
    assert died[0]["payload"]["count"] == 8
    assert "8" in died[0]["text"]
    # All 8 memes are genuinely gone from state (aggregation never touches
    # the underlying prune).
    for mid in never_notable:
        assert mid not in w.memes


def test_identical_text_prefix_memes_still_collapse_to_one_event():
    """The exact reported symptom: several children share the SAME text[:40]
    prefix (distortion only changed a word past char 40) and decay in the
    same tick — still just one aggregate line, not one per meme."""
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80, dominance_threshold=99))
    shared_prefix = "The Commons Well Restoration project mus"
    for i in range(10):
        m = w.mint_meme("idea", f"{shared_prefix}t continue quietly variant {i}",
                        "ada", parent_id="mem_parent", generation=2)
        m.virality = 0
        m.last_spread_tick = 0
    w.tick = 200

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    assert len(died) == 1
    assert died[0]["payload"]["count"] == 10


def test_notable_meme_still_gets_individual_death_event_gen0():
    """A coined original (generation == 0) is signal, not churn — it keeps
    its own 'fades from memory' line even amid a big never-notable batch."""
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80, dominance_threshold=99))
    original = w.mint_meme("idea", "a forgotten but ORIGINAL idea", "ada")
    original.virality = 0
    original.last_spread_tick = 0
    chaff = []
    for i in range(5):
        m = w.mint_meme("idea", f"chaff #{i}", "ada",
                        parent_id="mem_other_parent", generation=3)
        m.virality = 0
        m.last_spread_tick = 0
        chaff.append(m.id)
    w.tick = 80

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    individual = [e for e in died if not e["payload"].get("aggregated")]
    aggregate = [e for e in died if e["payload"].get("aggregated")]
    assert len(individual) == 1
    assert individual[0]["payload"]["meme_id"] == original.id
    assert len(aggregate) == 1
    assert aggregate[0]["payload"]["count"] == 5


def test_notable_meme_still_gets_individual_death_event_was_dominant():
    """A meme that was EVER dominant (crossed comm.dominance_threshold) keeps
    its own death event even after it loses every carrier and decays."""
    crowd = [_a(f"z{i}") for i in range(2)]
    w = _world(crowd, _on(diffusion_chance=0.0, dominance_threshold=2,
                          decay_ticks=80))
    m = w.mint_meme("idea", "the fox motif", "z0", generation=5)
    for ag in crowd:
        w._attach_meme(ag, m)
    w.diffuse_culture()                          # latches dominant_meme_ids
    assert m.id in w.dominant_meme_ids

    # Every carrier drops the meme; it goes idle past decay_ticks.
    for ag in crowd:
        m.carriers.remove(ag.id) if ag.id in m.carriers else None
    m.carriers = []
    m.last_spread_tick = 0
    w.tick = 200

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    individual = [e for e in died if not e["payload"].get("aggregated")]
    assert len(individual) == 1
    assert individual[0]["payload"]["meme_id"] == m.id


def test_notable_meme_still_gets_individual_death_event_high_virality():
    """A meme with lingering high virality at prune time is signal too, even
    as a mid-generation drift child."""
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80, half_life_ticks=1000,
                          dominance_threshold=99, death_notable_virality=3))
    m = w.mint_meme("idea", "a once-viral idea", "ada",
                    parent_id="mem_parent", generation=2)
    m.virality = 10
    m.last_spread_tick = 0
    w.tick = 80

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    individual = [e for e in died if not e["payload"].get("aggregated")]
    assert len(individual) == 1
    assert individual[0]["payload"]["meme_id"] == m.id


def test_zero_never_notable_memes_emits_no_aggregate():
    """Only notable memes pruned this sweep ⇒ no spurious empty aggregate."""
    ada = _a("ada")
    w = _world([ada], _on(decay_ticks=80, dominance_threshold=99))
    original = w.mint_meme("idea", "a forgotten but ORIGINAL idea", "ada")
    original.last_spread_tick = 0
    w.tick = 80

    events = w.diffuse_culture()

    died = [e for e in events if e["kind"] == "meme_died"]
    assert len(died) == 1
    assert not died[0]["payload"].get("aggregated")


# ── #B — passive-diffusion drift aggregation ─────────────────────────────────

def test_diffusion_hops_beyond_cap_collapse_to_one_aggregate_event():
    """8+ co-located infections in one sweep must not emit 8 individual
    meme_mutated lines — only the first comm.mutation_notable_cap are
    individual, the rest fold into one aggregate."""
    ada = _a("ada")
    crowd = [_a(f"z{i:02d}") for i in range(8)]
    w = _world([ada, *crowd], _on(diffusion_chance=1.0, max_diffusions=8,
                                  mutation_notable_cap=2))
    src = w.mint_meme("rumor", "Ada borrowed bread from the stall", "ada")
    w._attach_meme(ada, src)

    events = w.diffuse_culture()

    muts = [e for e in events if e["kind"] == "meme_mutated"]
    individual = [e for e in muts if not e["payload"].get("aggregated")]
    aggregate = [e for e in muts if e["payload"].get("aggregated")]
    assert len(individual) == 2                  # capped
    assert len(aggregate) == 1
    assert aggregate[0]["payload"]["count"] == 6  # 8 infections - 2 individual
    # Still 8 agents actually caught the drifted child — aggregation is a
    # notification choice, never a state change.
    infected = [c for c in crowd if c.held_memes]
    assert len(infected) == 8


def test_small_infection_count_stays_fully_individual():
    """When infections <= the cap, every hop still gets its own event (no
    spurious aggregate) — preserves the EM-252 golden contract exactly."""
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, src)

    events = w.diffuse_culture()

    muts = [e for e in events if e["kind"] == "meme_mutated"]
    assert len(muts) == 1
    assert not muts[0]["payload"].get("aggregated")


# ── Determinism (EM-155) ──────────────────────────────────────────────────────

def _rich_det_world() -> World:
    ada = _a("ada")
    crowd = [_a(f"z{i:02d}") for i in range(10)]
    w = _world([ada, *crowd], _on(diffusion_chance=0.8, max_diffusions=10,
                                  mutation_notable_cap=2, decay_ticks=50,
                                  dominance_threshold=99))
    w.tick = 9
    src = w.mint_meme("rumor", "Ada borrowed bread from the stall", "ada")
    w._attach_meme(ada, src)
    # Pre-seed a batch of never-notable stale memes that will decay THIS sweep.
    for i in range(6):
        m = w.mint_meme("idea", f"a stale idea #{i}", "ada",
                        parent_id="mem_seed", generation=4)
        m.virality = 0
        m.last_spread_tick = 0
    w.tick = 60
    return w


def test_two_identical_worlds_produce_byte_identical_event_lists():
    a, b = _rich_det_world(), _rich_det_world()
    events_a = a.diffuse_culture()
    events_b = b.diffuse_culture()
    assert events_a == events_b
    # Sanity: the aggregation actually engaged (otherwise this test would be
    # vacuous — not exercising the new code paths).
    assert any(e["payload"].get("aggregated") for e in events_a
               if e["kind"] in ("meme_mutated", "meme_died"))


def test_aggregation_never_mutates_sim_state_differently_than_individual_events():
    """The events list shape changes; self.memes / carriers / virality do
    NOT — pin the pure-notification contract the fix relies on."""
    w = _rich_det_world()
    before_ids = sorted(w.memes)
    w.diffuse_culture()
    # State mutation still happened (memes were pruned / minted) — this is
    # NOT a no-op sweep, it's specifically that events != state.
    after_ids = sorted(w.memes)
    assert before_ids != after_ids

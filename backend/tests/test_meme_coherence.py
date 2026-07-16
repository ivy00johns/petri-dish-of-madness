# backend/tests/test_meme_coherence.py
"""Meme-coherence fix (fix/feed-health) — spreading ideas via `comm` must stay
LEGIBLE instead of degrading into rambling nonsense over many drift
generations. Two mechanisms, both deterministic (EM-155 — seeded, sorted, no
random/clock):

  * _distort_text (world.py) no longer piles up DISTORTION_SUFFIXES without
    bound — it prefers a table word-swap when one is available, and once a
    text already carries DISTORTION_SUFFIX_CAP (1) rumor-suffixes, further
    unmatchable hops are a deterministic no-op instead of appending another
    embellishment.
  * diffuse_culture (world.py) gates the mint-site _distort_text call on
    comm.max_drift_generations (default 3): once a SOURCE meme's own
    generation reaches the cap, the child still mints/attaches/increments
    generation as usual (lineage is untouched) but its TEXT passes through
    VERBATIM — the idea keeps spreading, it just stops getting more garbled.

Mirrors test_em250_extraction.py (_distort_text seams) + test_em252_diffusion
(diffuse_culture fixtures).
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


# ── 1) _distort_text prefers the table SWAP over a suffix ───────────────────

def test_distort_text_prefers_word_swap_over_suffix_when_both_possible():
    ada = _a("ada")
    w = _world([ada])
    text = "Ada borrowed bread from the stall"
    out = w._distort_text(text, 7, "bram")
    assert out == "Ada stole bread from the stall"
    # No rumor-suffix rode along — the swap branch never touches suffixes.
    assert not any(s in out for s in w.DISTORTION_SUFFIXES)
    # Deterministic — same (text, seed parts) always mutates identically.
    assert out == w._distort_text(text, 7, "bram")


# ── 2) Repeated _distort_text never accretes more than 1 rumor-suffix ───────

def test_repeated_distortion_never_accretes_more_than_one_suffix():
    ada = _a("ada")
    w = _world([ada])
    text = "A quiet evening at the plaza"          # no DISTORTION_TABLE word
    out = text
    # Simulate many drift generations by feeding each hop's output back in as
    # the next hop's input (mirrors diffuse_culture chaining child.text).
    for hop in range(30):
        out = w._distort_text(out, hop, "bram")
    suffix_count = sum(1 for s in w.DISTORTION_SUFFIXES if s in out)
    assert suffix_count <= 1
    assert len(out) <= 200                          # the existing char cap holds


# ── 3) diffuse_culture: past the generation cap, the child TEXT is verbatim ──

def test_diffuse_culture_child_text_is_verbatim_past_generation_cap():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    assert w._comm_param("max_drift_generations", 3) == 3
    # Source meme is ALREADY at the cap — one more hop must not distort it.
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada",
                         generation=3)
    w._attach_meme(ada, source)

    events = w.diffuse_culture()

    assert len(bram.held_memes) == 1
    child = w.memes[bram.held_memes[0]]
    # Lineage/generation mechanic is UNTOUCHED — it still mints and increments.
    assert child.parent_id == source.id
    assert child.generation == source.generation + 1 == 4
    # …but the TEXT stopped degrading: verbatim passthrough, no distortion.
    assert child.text == source.text == "Ada borrowed bread"
    muts = [e for e in events if e["kind"] == "meme_mutated"]
    assert len(muts) == 1                            # still spreads, still notifies


def test_diffuse_culture_child_text_still_drifts_below_generation_cap():
    """Sanity control: BELOW the cap, distortion still applies as before —
    proves the cap gate is generation-scoped, not a global kill switch."""
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    source = w.mint_meme("rumor", "Ada borrowed bread", "ada")   # generation 0
    w._attach_meme(ada, source)

    w.diffuse_culture()

    child = w.memes[bram.held_memes[0]]
    assert child.generation == 1
    assert child.text != source.text                 # still drifts below the cap


# ── 4) Determinism (EM-155) ──────────────────────────────────────────────────

def test_distort_text_determinism_identical_seed_identical_output():
    w1 = _world([_a("ada")])
    w2 = _world([_a("ada")])
    text = "Ada borrowed bread from the stall"
    assert w1._distort_text(text, 7, "bram") == w2._distort_text(text, 7, "bram")

    unmatchable = "A quiet evening at the plaza"
    assert (w1._distort_text(unmatchable, 3, "bram")
            == w2._distort_text(unmatchable, 3, "bram"))


def _det_capped_world() -> World:
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    w.tick = 9
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada", generation=3)
    w._attach_meme(ada, src)
    return w


def test_diffuse_culture_determinism_identical_world_identical_child_text():
    a, b = _det_capped_world(), _det_capped_world()
    a.diffuse_culture()
    b.diffuse_culture()
    a_bram, b_bram = a.agents["bram"], b.agents["bram"]
    a_child = a.memes[a_bram.held_memes[0]]
    b_child = b.memes[b_bram.held_memes[0]]
    assert a_child.text == b_child.text == "Ada borrowed bread"

# backend/tests/test_em253_lifecycle.py
"""EM-253 — Culture lifecycle (the deterministic state core, Wave O Culture stage).

Four reflex mechanics, ZERO extra LLM calls, all gated on comm.enabled:
  * create_meme — coin a fresh idea meme (author is sole carrier, virality 1);
  * adopt_meme  — take up an existing meme (+1 virality); an IMAGE meme drifts a
    CHILD image (distorted prompt, new seeded image_id, parent_id/generation+1)
    through the FREE gallery seam — "the meme mutates as it spreads";
  * create_image extension — when comm + meme_images, a posted image is ALSO
    registered as a spreadable image meme; with either OFF it is byte-identical;
  * diffuse_culture extension — virality on passive infection, a ONCE
    `meme_dominant` transition at comm.dominance_threshold carriers, and culture
    camps (agents who share >= comm.camp_min_shared memes cluster).

Pins the hard laws: determinism (seeded ids, no clock/RNG), the flag-OFF golden
(comm disabled ⇒ zero meme_* events, create_image byte-identical, no new snapshot
key), and the free-image cost rule (a NEW image only on an explicit create_image
or adopt_meme of an image meme — never in the passive sweep).

Mirrors test_em252_diffusion (fixtures) + test_wave_i_atelier (image seam).
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ImageGenParams


def _params(**kw) -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        city_seed=1337, **kw)


def _a(aid: str, loc: str = "plaza", **kw) -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=loc, energy=80.0, credits=20, **kw)


def _world(agents: list[AgentState], comm: dict | None = None,
           image: bool = False) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
              PlaceState(id="field", name="Field", x=5, y=5, kind="nature")]
    params = (_params(image_gen=ImageGenParams(max_gallery=30)) if image
              else _params())
    w = World(params=params, places=places, agents=agents)
    if comm is not None:
        w.params.comm = comm
    return w


def _on(**over) -> dict:
    return {"enabled": True, **over}


# ── 1) create_meme ───────────────────────────────────────────────────────────

def test_create_meme_mints_idea_author_carries_virality_one():
    ada = _a("ada")
    w = _world([ada], _on())
    w.tick = 4

    evt = w.action_create_meme(ada, "plant a garden")

    assert evt["kind"] == "meme_created"
    assert evt["actor_id"] == "ada"
    mid = evt["payload"]["meme_id"]
    meme = w.memes[mid]
    assert meme.kind == "idea"
    assert meme.text == "plant a garden"
    assert meme.origin_agent_id == "ada"
    assert meme.virality == 1
    # The author is the SOLE carrier.
    assert meme.carriers == ["ada"]
    assert ada.held_memes == [mid]
    assert evt["payload"] == {"action": "create_meme", "meme_id": mid,
                              "kind": "idea"}


def test_create_meme_ungated_by_co_location():
    # An author needs no audience — alone at a place still mints.
    ada = _a("ada")
    w = _world([ada], _on())
    evt = w.action_create_meme(ada, "a lonely idea")
    assert evt["kind"] == "meme_created"


def test_create_meme_empty_text_fails_and_mints_nothing():
    ada = _a("ada")
    w = _world([ada], _on())
    for bad in ("", "   "):
        evt = w.action_create_meme(ada, bad)
        assert evt["kind"] == "parse_failure"
        assert evt["payload"]["action"] == "create_meme"
    assert w.memes == {}
    assert ada.held_memes == []


def test_create_meme_disabled_when_comm_off():
    ada = _a("ada")
    w = _world([ada])                                    # no comm block ⇒ OFF
    evt = w.action_create_meme(ada, "an idea")
    assert evt["kind"] == "parse_failure"
    assert w.memes == {}


def test_create_meme_id_deterministic_across_worlds():
    a = _world([_a("ada")], _on())
    b = _world([_a("ada")], _on())
    ea = a.action_create_meme(a.agents["ada"], "shared idea")
    eb = b.action_create_meme(b.agents["ada"], "shared idea")
    assert ea["payload"]["meme_id"] == eb["payload"]["meme_id"]


# ── 2) adopt_meme ────────────────────────────────────────────────────────────

def test_adopt_meme_joins_carriers_bumps_virality_emits_event():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on())
    src = w.mint_meme("idea", "share the well", "ada")
    w._attach_meme(ada, src)
    src.virality = 1

    evt = w.action_adopt_meme(bram, src.id)

    assert evt["kind"] == "meme_adopted"
    assert evt["actor_id"] == "bram"
    assert src.id in bram.held_memes
    assert "bram" in src.carriers
    assert src.virality == 2                             # +1
    assert evt["payload"] == {"action": "adopt_meme", "meme_id": src.id,
                              "kind": "idea"}


def test_adopt_unknown_meme_fails():
    ada = _a("ada")
    w = _world([ada], _on())
    evt = w.action_adopt_meme(ada, "mem_doesnotexist")
    assert evt["kind"] == "parse_failure"
    assert evt["payload"]["action"] == "adopt_meme"


def test_re_adopt_is_a_no_op_fail():
    ada = _a("ada")
    w = _world([ada], _on())
    m = w.mint_meme("idea", "already mine", "ada")
    w._attach_meme(ada, m)
    m.virality = 1

    evt = w.action_adopt_meme(ada, m.id)                 # already a carrier

    assert evt["kind"] == "parse_failure"
    assert m.virality == 1                               # NOT bumped
    assert ada.held_memes == [m.id]                      # unchanged


def test_adopt_disabled_when_comm_off():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram])                              # comm OFF
    m = w.mint_meme("idea", "x", "ada")
    w._attach_meme(ada, m)
    evt = w.action_adopt_meme(bram, m.id)
    assert evt["kind"] == "parse_failure"
    assert bram.held_memes == []


# ── 2b) adopt_meme IMAGE drift (the marquee "meme mutates as it spreads") ─────

def _image_parent(w: World, author: AgentState, prompt: str):
    """Post an image (mints the parent image meme) and return it."""
    evt = w.action_create_image(author, prompt)
    return w.memes[evt["payload"]["meme_id"]]


def test_adopt_image_meme_drifts_a_child_with_meme_images_on():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(meme_images=True), image=True)
    w.tick = 3
    parent = _image_parent(w, ada, "a fox in a crown")
    assert parent.kind == "image" and parent.image_id is not None
    gallery_before = len(w.gallery)

    evt = w.action_adopt_meme(bram, parent.id)

    # A _multi chain: meme_adopted THEN the child's meme_created.
    assert "_multi" in evt
    kinds = [e["kind"] for e in evt["_multi"]]
    assert kinds == ["meme_adopted", "meme_created"]
    child_id = evt["_multi"][1]["payload"]["meme_id"]
    child = w.memes[child_id]
    # A DRIFTED CHILD image meme: parent lineage, new seeded image_id, distorted.
    assert child.kind == "image"
    assert child.parent_id == parent.id
    assert child.generation == parent.generation + 1 == 1
    assert child.image_id is not None
    assert child.image_id != parent.image_id            # a NEW gallery image
    assert child.text != parent.text                    # the prompt drifted
    assert bram.held_memes[-1] == child_id              # bram carries the child
    assert parent.id in bram.held_memes                 # …and the parent
    # A single NEW gallery entry was minted through the FREE lane.
    assert len(w.gallery) == gallery_before + 1
    assert any(g["image_id"] == child.image_id for g in w.gallery)


def test_adopt_image_meme_attaches_only_with_meme_images_off():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(meme_images=False), image=True)
    # meme_images OFF ⇒ create_image mints no meme; hand-mint an image meme.
    parent = w.mint_meme("image", "a fox in a crown", "ada", image_id="img_seed")
    w._attach_meme(ada, parent)
    parent.virality = 1
    gallery_before = len(w.gallery)

    evt = w.action_adopt_meme(bram, parent.id)

    assert evt["kind"] == "meme_adopted"                 # a plain adopt, NO chain
    assert "_multi" not in evt
    assert parent.virality == 2
    assert bram.held_memes == [parent.id]                # only the parent
    assert len(w.gallery) == gallery_before              # NO new image
    # No child minted — the only image meme is the parent.
    assert [m.id for m in w.memes.values() if m.parent_id] == []


# ── 3) create_image extension (golden-critical) ──────────────────────────────

def test_create_image_registers_image_meme_when_comm_and_meme_images_on():
    ada = _a("ada")
    w = _world([ada], _on(meme_images=True), image=True)
    w.tick = 6

    evt = w.action_create_image(ada, "a sunset over the plaza")

    assert evt["kind"] == "image_posted"
    mid = evt["payload"]["meme_id"]                       # rides the payload
    meme = w.memes[mid]
    assert meme.kind == "image"
    assert meme.image_id == evt["payload"]["image_id"]    # SAME seeded id
    assert meme.virality == 1
    assert ada.held_memes == [mid]                        # creator carries it


def test_create_image_no_meme_when_meme_images_off():
    ada = _a("ada")
    w = _world([ada], _on(meme_images=False), image=True)
    evt = w.action_create_image(ada, "a quiet mural")
    assert "meme_id" not in evt["payload"]                # payload unchanged
    assert w.memes == {}                                  # NO meme registered
    assert ada.held_memes == []


def test_create_image_byte_identical_when_comm_off():
    ada = _a("ada")
    w = _world([ada], image=True)                         # comm OFF (no block)
    w.tick = 6
    evt = w.action_create_image(ada, "a sunset over the plaza")
    # The image_posted payload keeps EXACTLY the pre-EM-253 key set.
    assert set(evt["payload"]) == {"image_id", "prompt", "url", "place"}
    assert "meme_id" not in evt["payload"]
    assert w.memes == {}                                  # comm off ⇒ no meme
    # No new snapshot key when the culture layer never ran.
    assert "memes" not in w.to_snapshot()
    assert "dominant_meme_ids" not in w.to_snapshot()


# ── 4a) diffuse_culture: virality on passive infection ───────────────────────

def test_passive_infection_opens_child_at_virality_one():
    ada, bram = _a("ada"), _a("bram")
    w = _world([ada, bram], _on(diffusion_chance=1.0))
    src = w.mint_meme("rumor", "Ada borrowed bread", "ada")
    w._attach_meme(ada, src)

    w.diffuse_culture()

    child = w.memes[bram.held_memes[0]]
    assert child.virality == 1                            # a caught meme spreads


# ── 4b) diffuse_culture: dominance (the ONCE meme_dominant transition) ────────

def _dominant_world(threshold: int = 6):
    crowd = [_a(f"z{i}") for i in range(threshold)]
    w = _world(crowd, _on(diffusion_chance=0.0, dominance_threshold=threshold))
    m = w.mint_meme("idea", "the fox motif", "z0")
    for ag in crowd:
        w._attach_meme(ag, m)                             # every agent carries it
    return w, m


def test_meme_reaching_threshold_emits_meme_dominant_once():
    w, m = _dominant_world(6)

    events = w.diffuse_culture()
    doms = [e for e in events if e["kind"] == "meme_dominant"]
    assert len(doms) == 1
    assert doms[0]["payload"]["meme_id"] == m.id
    assert doms[0]["payload"]["carriers"] == 6
    assert doms[0]["actor_type"] == "system"
    assert m.id in w.dominant_meme_ids

    # Still dominant next round ⇒ does NOT re-fire (the latch holds).
    again = w.diffuse_culture()
    assert [e for e in again if e["kind"] == "meme_dominant"] == []


def test_dominance_drops_below_and_re_crosses_re_fires():
    w, m = _dominant_world(6)
    w.diffuse_culture()                                   # fires once
    assert m.id in w.dominant_meme_ids

    # Drop a LIVE carrier below threshold (kill z0) ⇒ quiet fall, no event.
    w.agents["z0"].alive = False
    dropped = w.diffuse_culture()
    assert [e for e in dropped if e["kind"] == "meme_dominant"] == []
    assert m.id not in w.dominant_meme_ids               # latch cleared

    # Re-cross ⇒ re-fires.
    w.agents["z0"].alive = True
    recross = w.diffuse_culture()
    assert len([e for e in recross if e["kind"] == "meme_dominant"]) == 1
    assert m.id in w.dominant_meme_ids


def test_below_threshold_never_dominant():
    # Five carriers, threshold six ⇒ no dominance.
    crowd = [_a(f"z{i}") for i in range(5)]
    w = _world(crowd, _on(diffusion_chance=0.0, dominance_threshold=6))
    m = w.mint_meme("idea", "the fox motif", "z0")
    for ag in crowd:
        w._attach_meme(ag, m)

    events = w.diffuse_culture()

    assert [e for e in events if e["kind"] == "meme_dominant"] == []
    assert m.id not in w.dominant_meme_ids


# ── 4c) diffuse_culture: culture camps ───────────────────────────────────────

def _camp_world():
    agents = [_a(n) for n in ("n1", "n2", "n3", "n4")]
    w = _world(agents, _on(diffusion_chance=0.0, camp_min_shared=2,
                           camp_min_size=3))
    m1 = w.mint_meme("idea", "shared one", "n1")
    m2 = w.mint_meme("idea", "shared two", "n1")
    return w, m1, m2


def test_agents_sharing_memes_form_a_culture_camp():
    w, m1, m2 = _camp_world()
    for n in ("n1", "n2", "n3"):
        w._attach_meme(w.agents[n], m1)
        w._attach_meme(w.agents[n], m2)

    events = w.recompute_culture_camps()

    formed = [e for e in events if e["kind"] == "culture_camp_formed"]
    assert len(formed) == 1
    cid = formed[0]["payload"]["culture_camp_id"]
    assert cid.startswith("cmp_")
    assert set(w.culture_camps[cid]["members"]) == {"n1", "n2", "n3"}


def test_camp_membership_diffs_join_leave_and_dissolve():
    w, m1, m2 = _camp_world()
    for n in ("n1", "n2", "n3"):
        w._attach_meme(w.agents[n], m1)
        w._attach_meme(w.agents[n], m2)
    w.recompute_culture_camps()
    cid = next(iter(w.culture_camps))

    # n4 shares both memes ⇒ JOINS the (same) camp.
    w._attach_meme(w.agents["n4"], m1)
    w._attach_meme(w.agents["n4"], m2)
    joined = w.recompute_culture_camps()
    assert any(e["kind"] == "culture_camp_joined" and e["actor_id"] == "n4"
               for e in joined)
    assert cid in w.culture_camps
    assert set(w.culture_camps[cid]["members"]) == {"n1", "n2", "n3", "n4"}

    # n4 loses its memes ⇒ LEAVES (the camp survives by 50% continuity).
    w.agents["n4"].held_memes = []
    left = w.recompute_culture_camps()
    assert any(e["kind"] == "culture_camp_left" and e["actor_id"] == "n4"
               for e in left)
    assert set(w.culture_camps[cid]["members"]) == {"n1", "n2", "n3"}

    # The whole camp loses its shared memes ⇒ DISSOLVES.
    for n in ("n1", "n2", "n3"):
        w.agents[n].held_memes = []
    dissolved = w.recompute_culture_camps()
    assert any(e["kind"] == "culture_camp_dissolved" for e in dissolved)
    assert w.culture_camps == {}


def test_culture_camps_disabled_when_comm_off():
    agents = [_a(n) for n in ("n1", "n2", "n3")]
    w = _world(agents)                                   # comm OFF
    m1 = w.mint_meme("idea", "a", "n1")
    m2 = w.mint_meme("idea", "b", "n1")
    for n in ("n1", "n2", "n3"):
        w._attach_meme(w.agents[n], m1)
        w._attach_meme(w.agents[n], m2)
    assert w.recompute_culture_camps() == []
    assert w.culture_camps == {}


def test_culture_camps_deterministic_across_worlds():
    def _build():
        w, m1, m2 = _camp_world()
        for n in ("n1", "n2", "n3"):
            w._attach_meme(w.agents[n], m1)
            w._attach_meme(w.agents[n], m2)
        w.recompute_culture_camps()
        return w

    a, b = _build(), _build()
    assert a.culture_camps == b.culture_camps            # byte-identical store


# ── 5) determinism golden + snapshot round-trip ──────────────────────────────

def test_comm_off_create_image_is_deterministic_control():
    def _evt():
        w = _world([_a("ada")], image=True)
        w.tick = 6
        return w.action_create_image(w.agents["ada"], "a sunset")
    assert _evt() == _evt()                              # byte-identical


def _rich_world() -> World:
    """A world carrying memes + a camp + a dominant meme + a mid-drift image
    lineage — everything EM-253 touches, for the round-trip golden."""
    agents = [_a(n) for n in ("n1", "n2", "n3", "n4", "n5", "n6")]
    w = _world(agents, _on(diffusion_chance=0.0, dominance_threshold=6,
                           camp_min_shared=2, camp_min_size=3, meme_images=True),
               image=True)
    w.tick = 8
    # A dominant idea carried by all six.
    dom = w.mint_meme("idea", "the fox motif", "n1")
    for ag in agents:
        w._attach_meme(ag, dom)
    # A second shared idea so n1..n3 also share >= 2 memes ⇒ a culture camp.
    extra = w.mint_meme("idea", "share the harvest", "n1")
    for n in ("n1", "n2", "n3"):
        w._attach_meme(w.agents[n], extra)
    # A mid-drift image lineage: n1 posts, n4 adopts (drifts a child).
    parent = _image_parent(w, w.agents["n1"], "a fox in a crown")
    w.action_adopt_meme(w.agents["n4"], parent.id)
    # Latch the dominance + camps via the round sweep.
    w.diffuse_culture()
    assert dom.id in w.dominant_meme_ids
    assert w.culture_camps                                # a camp formed
    return w


def test_rich_culture_world_round_trips_byte_identical():
    w = _rich_world()
    snap1 = w.to_snapshot()
    # The new keys are present and shaped as documented.
    assert isinstance(snap1["dominant_meme_ids"], list)
    assert snap1["dominant_meme_ids"] == sorted(snap1["dominant_meme_ids"])
    assert "culture_camps" in snap1 and "memes" in snap1

    restored = World.from_snapshot(snap1, params=_params())
    assert restored.dominant_meme_ids == w.dominant_meme_ids
    assert restored.culture_camps == w.culture_camps

    snap2 = restored.to_snapshot()
    assert snap1 == snap2                                 # byte-identical

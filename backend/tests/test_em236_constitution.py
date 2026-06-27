"""EM-236 — Living constitution (Wave M3).

An amendable, ARTICLED foundational document layered over today's flat rule list.

  * A `World.constitution: list[dict]` — articles {id, text, ratified_tick} —
    grown ONLY through governance. Additive + serialized in to_snapshot ONLY when
    non-empty, restored defensively in from_snapshot (the factions/active_miracles
    only-when-non-empty pattern), so a world that never amends round-trips
    byte-identically (EM-155).

  * A governance effect `amend_constitution` (R5, modelled on EM-240 `trial` /
    EM-212 `promote_image`): the proposal carries {op, article_id?, text} on its
    payload (op ∈ add|edit|remove). It RATIFIES on a 70% SUPERMAJORITY — the same
    bar as `demolish` — and applies in `_on_rule_activated`, emitting a
    `constitution_amended` event. EXCLUDED from EM-087 renewal tagging (each
    amendment is a one-shot ACT, like demolish). The proposer's influence need
    (EM-229) is replenished on a ratified amendment.

  * Surfaced in the prompt (R6, CONDITIONAL): a non-empty constitution prints a
    `=== THE CONSTITUTION ===` block; an EMPTY constitution prints NOTHING, so the
    lawful-citizen em161 golden is byte-identical (the default-empty world).

Invariants pinned here (the wave's hard rules):
  * EM-155 — the new World `constitution` list is additive + serialized
    only-when-non-empty: an un-amended world round-trips byte-identically, and a
    world WITH ratified articles survives a snapshot/restore.
  * em161 golden — the constitution block is absent for a default (empty) world →
    byte-identical; it appears only once an article is ratified.
  * determinism — article ids derive from `ratified_tick` + an ordinal (NO uuid,
    NO clock); the same amendment sequence yields identical article ids on replay.
  * governance no-op — a world that never proposes amend_constitution keeps an
    empty constitution forever (no config block needed to be "on"; the effect is
    purely proposal-driven).
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ConstitutionParams
from petridish.agents.runtime import _assemble_context


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _places():
    return [
        PlaceState(id="townhall", name="Town Hall", x=0, y=0, kind="governance"),
        PlaceState(id="plaza", name="Plaza", x=1, y=0, kind="social"),
    ]


def _world(agents, params=None):
    return World(params=params or _params(), places=_places(), agents=agents)


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="civic", profile="mock",
                location="townhall", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _sys(agent, world):
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


def _ratify(world, rule, voter_ids):
    """Drive a proposal to ratification by casting YES votes from voter_ids."""
    status = None
    for vid in voter_ids:
        ok, _reason, status = world.action_vote(world.agents[vid], rule.id, True)
    return status


# ── default world: constitution is empty + inert ─────────────────────────────

def test_constitution_starts_empty():
    a = _agent()
    w = _world([a])
    assert w.constitution == []


def test_amend_constitution_is_a_valid_propose_effect():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "amend_constitution", "All are equal under the law.", op="add")
    assert ok, reason
    assert rule is not None
    assert rule.effect == "amend_constitution"
    assert rule.payload["op"] == "add"
    assert rule.payload["text"] == "All are equal under the law."


# ── add: a ratified amendment APPENDS an article (70% bar) ────────────────────

def test_amend_add_ratifies_on_supermajority():
    # 10 living agents → 70% = ceil(7.0) = 7 yes-votes ratifies.
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok, _r, rule = w.action_propose_rule(
        agents[0], "amend_constitution", "Article I: free assembly.", op="add")
    assert ok
    # 6 yes-votes is NOT enough (6 < 7) — still proposed.
    _ratify(w, rule, [f"a{i}" for i in range(6)])
    assert rule.status == "proposed"
    assert w.constitution == []
    # The 7th yes-vote crosses the supermajority → ratified + article appended.
    status = _ratify(w, rule, ["a6"])
    assert status == "active"
    assert len(w.constitution) == 1
    art = w.constitution[0]
    assert art["text"] == "Article I: free assembly."
    assert "id" in art and "ratified_tick" in art


def test_amend_add_below_supermajority_is_rejected_not_ratified():
    # 10 agents; 4 NO votes is a blocking minority for a 70% bar? No — rejection
    # happens when a yes-supermajority is mathematically out of reach OR all voted.
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok, _r, rule = w.action_propose_rule(
        agents[0], "amend_constitution", "Article X.", op="add")
    assert ok
    # All 10 vote, only 5 yes (< 7 needed) → rejected, no article.
    for i in range(5):
        w.action_vote(agents[i], rule.id, True)
    for i in range(5, 10):
        w.action_vote(agents[i], rule.id, False)
    assert rule.status == "rejected"
    assert w.constitution == []


# ── edit: a ratified amendment REWRITES an existing article ───────────────────

def _seed_article(world, voters, text="Article I: original.", proposer=None):
    proposer = proposer or world.agents[voters[0]]
    ok, _r, rule = world.action_propose_rule(
        proposer, "amend_constitution", text, op="add")
    assert ok
    _ratify(world, rule, voters)
    assert rule.status == "active"
    return world.constitution[-1]["id"]


def test_amend_edit_rewrites_article_text():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    art_id = _seed_article(w, voters)
    # Now EDIT it.
    ok, _r, rule = w.action_propose_rule(
        agents[0], "amend_constitution", "Article I: revised.",
        op="edit", article_id=art_id)
    assert ok
    _ratify(w, rule, voters)
    assert rule.status == "active"
    assert len(w.constitution) == 1                       # still one article
    assert w.constitution[0]["id"] == art_id              # id preserved
    assert w.constitution[0]["text"] == "Article I: revised."


def test_amend_edit_unknown_article_is_rejected_at_propose():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "amend_constitution", "x", op="edit", article_id="art-nope")
    assert not ok
    assert rule is None
    assert "article" in reason.lower()


# ── remove: a ratified amendment DELETES an article ──────────────────────────

def test_amend_remove_deletes_article():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    art_id = _seed_article(w, voters)
    ok, _r, rule = w.action_propose_rule(
        agents[0], "amend_constitution", "", op="remove", article_id=art_id)
    assert ok
    _ratify(w, rule, voters)
    assert rule.status == "active"
    assert w.constitution == []


def test_amend_remove_unknown_article_is_rejected_at_propose():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "amend_constitution", "", op="remove", article_id="art-nope")
    assert not ok
    assert rule is None


def test_amend_add_requires_text():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "amend_constitution", "   ", op="add")
    assert not ok
    assert rule is None


def test_amend_invalid_op_rejected():
    a = _agent()
    w = _world([a])
    ok, reason, rule = w.action_propose_rule(
        a, "amend_constitution", "x", op="frobnicate")
    assert not ok
    assert rule is None


# ── the ratification emits constitution_amended + replenishes influence ──────

def test_ratified_amendment_emits_event_and_replenishes_influence():
    agents = [_agent(id=f"a{i}", name=f"A{i}", influence=10.0) for i in range(10)]
    w = _world(agents, _params())
    w.params.constitution = ConstitutionParams(influence_replenish=20.0)
    voters = [f"a{i}" for i in range(7)]
    ok, _r, rule = w.action_propose_rule(
        agents[0], "amend_constitution", "Article I.", op="add")
    assert ok
    _ratify(w, rule, voters)
    evs = w.drain_spawn_events()
    kinds = [e["kind"] for e in evs]
    assert "constitution_amended" in kinds
    amend_evt = next(e for e in evs if e["kind"] == "constitution_amended")
    assert amend_evt["payload"]["op"] == "add"
    # Proposer's influence need topped up (EM-229 hook): 10 + 20 = 30.
    assert w.agents["a0"].influence == 30.0


def test_amend_constitution_excluded_from_renewal_tagging():
    # Two successive add amendments must BOTH apply (each is a one-shot ACT, like
    # demolish) — the second is NOT tagged a renewal of the first.
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    a1 = _seed_article(w, voters, text="Article I.")
    ok, _r, rule2 = w.action_propose_rule(
        agents[0], "amend_constitution", "Article II.", op="add")
    assert ok
    assert rule2.renewal_of is None                       # NOT a renewal
    _ratify(w, rule2, voters)
    assert rule2.status == "active"                       # ratified afresh
    assert len(w.constitution) == 2


def test_two_distinct_amendments_may_be_open_at_once():
    # The duplicate guard is scoped per (op, article_id) — two distinct add
    # proposals can have open votes simultaneously (mirrors demolish per-target).
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    ok1, _r1, r1 = w.action_propose_rule(
        agents[0], "amend_constitution", "Article I.", op="add")
    ok2, _r2, r2 = w.action_propose_rule(
        agents[1], "amend_constitution", "Article II.", op="add")
    assert ok1 and ok2
    assert r1.id != r2.id


def test_duplicate_edit_for_same_article_is_blocked():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    art_id = _seed_article(w, voters)
    ok1, _r1, r1 = w.action_propose_rule(
        agents[0], "amend_constitution", "v2", op="edit", article_id=art_id)
    ok2, reason2, r2 = w.action_propose_rule(
        agents[1], "amend_constitution", "v3", op="edit", article_id=art_id)
    assert ok1
    assert not ok2
    assert r2 is None


# ── determinism: article ids are seeded (no uuid / clock) ────────────────────

def test_article_ids_are_deterministic_across_runs():
    def _run():
        agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
        w = _world(agents)
        voters = [f"a{i}" for i in range(7)]
        w.tick = 5
        a1 = _seed_article(w, voters, text="Article I.")
        w.tick = 9
        a2 = _seed_article(w, voters, text="Article II.")
        return [art["id"] for art in w.constitution]
    first = _run()
    assert _run() == first                               # byte-identical ids


# ── snapshot round-trip (EM-155 / EM-190) ────────────────────────────────────

def test_no_constitution_round_trips_byte_identical():
    a = _agent()
    w = _world([a])
    snap = w.to_snapshot()
    assert "constitution" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
           json.dumps(snap, sort_keys=True)


def test_constitution_survives_snapshot_restore():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    _seed_article(w, voters, text="Article I: liberty.")
    snap = w.to_snapshot()
    assert "constitution" in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert len(restored.constitution) == 1
    assert restored.constitution[0]["text"] == "Article I: liberty."


def test_constitution_snapshot_is_stable_byte_identical():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    _seed_article(w, voters, text="Article I.")
    w.tick = 12
    _seed_article(w, voters, text="Article II.")
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


def test_from_snapshot_garbage_articles_ignored():
    a = _agent()
    w = _world([a])
    snap = w.to_snapshot()
    snap["constitution"] = [
        {"id": "art-1", "text": "ok", "ratified_tick": 1},   # well-formed → kept
        {"text": "no id", "ratified_tick": 1},               # missing id → dropped
        "bad",                                                # non-dict → dropped
        {"id": "art-2", "text": "   ", "ratified_tick": 1},  # blank text → dropped
    ]
    restored = World.from_snapshot(snap, params=_params())
    assert [art["id"] for art in restored.constitution] == ["art-1"]


# ── prompt: conditional block (em161 golden) ─────────────────────────────────

def test_constitution_block_absent_when_empty():
    a = _agent()
    w = _world([a])                                       # empty constitution
    sys = _sys(a, w)
    assert "THE CONSTITUTION" not in sys


def test_constitution_block_present_when_articles_exist():
    agents = [_agent(id=f"a{i}", name=f"A{i}") for i in range(10)]
    w = _world(agents)
    voters = [f"a{i}" for i in range(7)]
    _seed_article(w, voters, text="Article I: all are free.")
    sys = _sys(agents[0], w)
    assert "THE CONSTITUTION" in sys
    assert "Article I: all are free." in sys


def test_amend_constitution_offered_in_propose_menu():
    a = _agent()                                          # at townhall (governance)
    w = _world([a])
    sys = _sys(a, w)
    assert "amend_constitution" in sys


# ── config: ConstitutionParams default is inert ──────────────────────────────

def test_constitution_params_default():
    p = WorldParams()
    assert isinstance(p.constitution, ConstitutionParams)
    assert p.constitution.ratify_threshold == 0.7
    assert p.constitution.influence_replenish >= 0.0

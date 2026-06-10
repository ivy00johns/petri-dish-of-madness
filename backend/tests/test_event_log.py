"""
W5 gate invariants — the append-only event-log spine + replay + read API.

Contract: contracts/event-log.md (v1.0.0), contracts/db-schema.sql (v1.1.0),
contracts/action-protocol.schema.json (v1.1.0). Items EM-054 + EM-066.

Everything here is deterministic and offline: a MockProvider scripts each agent's
action, and turns are driven one at a time through TickLoop._execute_turn (the same
path the asyncio loop uses, minus the scheduler sleeps). No network, no real LLM.

The eight test groups mirror the eight gate invariants in the QE brief:

  1. APPEND-ONLY      — events.seq strictly increasing, no UPDATE/DELETE path on events.
  2. TURN CHAIN       — one turn = one ordered turn_id chain (get_turn_trace), seq-ordered.
  3. STAMPING         — sim_time == round(tick*interval,3); actor_type non-null + correct.
  4. OTel llm_call    — payload carries the exact GenAI attribute key set.
  5. DECISION TRACE   — EM-066 fields surface; absent fields still yield a valid chain.
  6. SNAPSHOTS+REPLAY — snapshots at tick 0 + every interval; replay(T) == live world(T).
  7. READ API         — get_events filters, get_rule_history, get_analytics per contract.
  8. REGRESSION       — (the existing suite, run alongside this file.)
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams, ModelProfile
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Harness — build a fully wired loop driven by a scripted MockProvider.
# ──────────────────────────────────────────────────────────────────────────────

# The chain kinds emitted (in order) for every agent turn, per event-log.md §3.
TRACE_KINDS = [
    "turn_start",
    "perceived",
    "memory_retrieved",
    "llm_call",
    "reasoning",
    "action_chosen",
]


def _make_params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=2.0,
        starting_energy=80.0,
        starting_credits=20,
        recharge_cost=2,
        recharge_amount=20.0,
        work_reward=4,
        forage_reward=1,
        steal_max=5,
        death_after_zero_turns=20,
        memory_window=5,
        snapshot_interval_ticks=5,
    )
    base.update(overrides)
    return WorldParams(**base)


def _make_loop(
    *,
    script: list | None = None,
    params: WorldParams | None = None,
    agent_count: int = 3,
    db_path: str = ":memory:",
    do_init: bool = True,
) -> tuple[TickLoop, World, SQLiteRepository, Router]:
    """Wire World + Router(mock) + Runtime + repo + loop.

    `script` cycles the same scripted actions for every agent. When None the
    MockProvider's per-agent default script runs (used for the full multi-tick
    mock run). `do_init` calls init_run so a real run_id + tick-0 snapshot exist.
    """
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=20, y=0, kind="governance"),
        PlaceState(id="home", name="Hearth", x=30, y=0, kind="home"),
        PlaceState(id="commons", name="Commons", x=40, y=0, kind="wild"),
    ]
    # Names chosen so the MockProvider default scripts (ada/bram/cleo/...) bind,
    # keeping the no-script multi-tick run exercising proposals + votes + economy.
    names = ["Ada", "Bram", "Cleo", "Dov", "Esi"][:agent_count]
    agents = [
        AgentState(
            id=f"agent_{name.lower()}",
            name=name,
            personality="Test agent.",
            profile="mock",
            location="market",
            energy=params.starting_energy,
            credits=params.starting_credits,
        )
        for name in names
    ]
    world = World(params=params, places=places, agents=agents)

    mock = MockProvider(script=script)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": mock},
    )
    for a in agents:
        router.reassign(a.id, "mock")

    repo = SQLiteRepository(db_path)
    runtime = AgentRuntime(world, router)
    router.inject_world(world)

    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router)
    if do_init:
        from petridish.config.loader import WorldConfig
        loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    else:
        loop._run_id = 1
    return loop, world, repo, router


async def _run_ticks(loop: TickLoop, world: World, n: int) -> None:
    """Advance exactly n agent turns through the real _execute_turn path."""
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        if not agent.alive:
            continue
        await loop._execute_turn(agent)


def _all_events(repo: SQLiteRepository, run_id: int) -> list[dict]:
    return repo.get_events(run_id, order="asc")


# ──────────────────────────────────────────────────────────────────────────────
# 1. APPEND-ONLY
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_append_only_seq_strictly_increasing_no_gaps_reused():
    """After a multi-tick mock run, events.seq is strictly increasing and dense
    (one contiguous block per run: AUTOINCREMENT never reuses an id)."""
    loop, world, repo, _ = _make_loop()
    run_id = loop._run_id
    await _run_ticks(loop, world, 24)

    events = _all_events(repo, run_id)
    assert len(events) > 0
    seqs = [e["seq"] for e in events]

    # strictly increasing
    assert all(b > a for a, b in zip(seqs, seqs[1:])), "seq is not strictly increasing"
    # contiguous within this run (no holes => no row was deleted out of the middle)
    assert seqs == list(range(seqs[0], seqs[0] + len(seqs))), "gap in seq sequence"
    # AUTOINCREMENT never goes backwards
    assert seqs == sorted(seqs)


@pytest.mark.asyncio
async def test_append_only_reread_returns_identical_rows():
    """Append-only => re-reading the log returns byte-identical rows. Nothing in
    the engine path mutates an already-written event."""
    loop, world, repo, _ = _make_loop()
    run_id = loop._run_id
    await _run_ticks(loop, world, 12)

    first = _all_events(repo, run_id)
    # Drive more turns, then re-read the SAME (earlier) seq range.
    high_water = first[-1]["seq"]
    await _run_ticks(loop, world, 12)
    reread = [e for e in _all_events(repo, run_id) if e["seq"] <= high_water]

    assert reread == first, "previously written rows changed after more turns"


def test_append_only_no_update_or_delete_on_events_in_source():
    """Behavioral assertions can't see a dormant UPDATE/DELETE path, so also assert
    statically: the repository source has no UPDATE/DELETE targeting `events`."""
    src = Path(inspect.getsourcefile(SQLiteRepository)).read_text()
    lowered = src.lower()
    # No DELETE of events at all.
    assert "delete from events" not in lowered, "found a DELETE on events"
    # The only UPDATE in the repo is on runs(status); none should touch events.
    for line in lowered.splitlines():
        if "update events" in line:
            raise AssertionError(f"found an UPDATE on events: {line.strip()!r}")
    # And the only INSERT into events is the append in save_event (sanity: exactly one).
    assert lowered.count("insert into events") == 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. TURN CHAIN
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_turn_chain_ordered_and_single_turn_id():
    """One agent turn emits the ordered chain under exactly ONE turn_id, seq-asc:
    turn_start -> perceived -> memory_retrieved -> llm_call -> reasoning ->
    action_chosen -> (domain event[s]) -> action_resolved."""
    # 'give' produces a domain `economy` event between action_chosen and action_resolved.
    loop, world, repo, _ = _make_loop(
        script=[{"action": "forage", "args": {}}]
    )
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    # All rows of the first turn share one turn_id; find it from turn_start.
    events = _all_events(repo, run_id)
    starts = [e for e in events if e["kind"] == "turn_start"]
    assert len(starts) == 1
    turn_id = starts[0]["turn_id"]
    assert turn_id is not None

    trace = repo.get_turn_trace(run_id, turn_id)
    kinds = [e["kind"] for e in trace]

    # Exactly one turn_id across the whole chain.
    assert {e["turn_id"] for e in trace} == {turn_id}

    # seq is strictly ascending within the chain (get_turn_trace orders by seq).
    seqs = [e["seq"] for e in trace]
    assert seqs == sorted(seqs)

    # Ordered prefix is exactly the six trace spans, in order.
    assert kinds[: len(TRACE_KINDS)] == TRACE_KINDS
    # A domain event (economy for forage) sits between action_chosen and action_resolved.
    assert "action_resolved" in kinds
    assert kinds[-1] == "action_resolved"
    domain = kinds[len(TRACE_KINDS):-1]
    assert "economy" in domain, f"expected a domain event, chain was {kinds}"


@pytest.mark.asyncio
async def test_turn_chain_domain_events_inherit_turn_id():
    """A multi-event action (vote that passes a rule) tags every emitted row —
    including rule_vote/rule_passed — with the turn's turn_id."""
    # Single agent so one YES vote is a strict majority and the rule passes.
    loop, world, repo, _ = _make_loop(agent_count=1, script=[
        {"action": "propose_rule",
         "args": {"effect": "ban_stealing", "text": "no theft"}},
        {"action": "idle", "args": {}},  # placeholder; replaced by dynamic vote
    ])
    # Civic actions are gated to the governance place — stand at the town hall.
    next(iter(world.agents.values())).location = "townhall"
    run_id = loop._run_id

    # Turn 1: propose. Turn 2: MockProvider auto-votes YES on the open proposal.
    await _run_ticks(loop, world, 2)

    events = _all_events(repo, run_id)
    passed = [e for e in events if e["kind"] == "rule_passed"]
    assert passed, "expected the proposed rule to pass with a sole YES vote"
    vote_turn = passed[0]["turn_id"]
    assert vote_turn is not None

    trace = repo.get_turn_trace(run_id, vote_turn)
    kinds = {e["kind"] for e in trace}
    # rule_vote + rule_passed both carried the turn_id of the voting turn.
    assert {"rule_vote", "rule_passed"} <= kinds
    assert {"turn_start", "action_resolved"} <= kinds


# ──────────────────────────────────────────────────────────────────────────────
# 3. STAMPING
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stamping_sim_time_and_actor_type():
    """Every row: sim_time == round(tick*tick_interval_seconds,3) and actor_type is
    non-null. Agent-turn rows are human_agent; engine random injections are system."""
    interval = 0.5
    loop, world, repo, _ = _make_loop(params=_make_params(tick_interval_seconds=interval))
    run_id = loop._run_id

    await _run_ticks(loop, world, 9)
    # An engine-level random injection has no actor -> actor_type 'system'.
    loop.inject_random_event("windfall")

    events = _all_events(repo, run_id)
    assert events

    for e in events:
        # sim_time formula.
        assert e["sim_time"] == round(e["tick"] * interval, 3), (
            f"sim_time {e['sim_time']} != round({e['tick']}*{interval},3) "
            f"for kind={e['kind']}"
        )
        # actor_type non-null.
        assert e["actor_type"] is not None and e["actor_type"] != ""
        # correct actor_type by provenance.
        if e["actor_id"]:
            assert e["actor_type"] == "human_agent", (
                f"agent row {e['kind']} stamped {e['actor_type']}"
            )
        else:
            assert e["actor_type"] == "system", (
                f"actor-less row {e['kind']} stamped {e['actor_type']}"
            )

    # The injected event specifically is a system event.
    windfalls = [e for e in events if e["kind"] == "random_event"]
    assert windfalls and windfalls[-1]["actor_type"] == "system"


# ──────────────────────────────────────────────────────────────────────────────
# 4. OTel llm_call
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_llm_call_payload_has_exact_otel_keys():
    """The llm_call payload carries the exact OTel GenAI attribute key set
    (event-log.md §3.4). One llm_call per turn."""
    expected_keys = {
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "latency_ms",
        "gen_ai.response.finish_reasons",
        "cached",
        "attempt",
    }
    loop, world, repo, _ = _make_loop(script=[{"action": "forage", "args": {}}])
    run_id = loop._run_id
    await _run_ticks(loop, world, 6)

    llm_rows = repo.get_events(run_id, kinds=["llm_call"], order="asc")
    assert llm_rows, "no llm_call rows emitted"
    # One llm_call per turn (6 turns, no retries on the mock => 6 rows).
    assert len(llm_rows) == 6

    for row in llm_rows:
        payload = row["payload"]
        assert set(payload.keys()) == expected_keys, (
            f"llm_call payload keys {set(payload.keys())} != {expected_keys}"
        )
        # Type sanity on the keys the contract pins down.
        assert payload["gen_ai.request.model"] == "mock"
        assert isinstance(payload["cached"], bool)
        assert isinstance(payload["attempt"], int)
        # usage is null in W5 (providers don't capture tokens until W6) — but the
        # KEYS must exist regardless.
        assert "gen_ai.usage.input_tokens" in payload
        assert "gen_ai.usage.output_tokens" in payload


# ──────────────────────────────────────────────────────────────────────────────
# 5. DECISION TRACE (EM-066)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_decision_trace_fields_surface_in_chain():
    """When the action JSON carries perceived_summary / memories_used / reasoning,
    they surface in the perceived / memory_retrieved / reasoning rows."""
    action = {
        "action": "forage",
        "args": {},
        "perceived_summary": "Bram is beside me in the market, low on energy.",
        "memories_used": ["Bram gave me 3 credits last round", "the market pays best"],
        "reasoning": "Foraging is safe and I want to keep my credits to repay Bram.",
    }
    loop, world, repo, _ = _make_loop(script=[action])
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    events = _all_events(repo, run_id)
    by_kind = {e["kind"]: e for e in events}

    # perceived row carries perceived_summary.
    assert by_kind["perceived"]["payload"]["perceived_summary"] == action["perceived_summary"]
    # reasoning row carries reasoning + memories_used + perceived_summary.
    rp = by_kind["reasoning"]["payload"]
    assert rp["reasoning"] == action["reasoning"]
    assert rp["memories_used"] == action["memories_used"]
    assert rp["perceived_summary"] == action["perceived_summary"]


@pytest.mark.asyncio
async def test_decision_trace_optional_safe_without_fields():
    """A mock action WITHOUT the EM-066 fields still produces a valid, complete
    chain — the optional fields are simply null, nothing crashes."""
    loop, world, repo, _ = _make_loop(script=[{"action": "forage", "args": {}}])
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)

    events = _all_events(repo, run_id)
    turn_id = events[0]["turn_id"]
    trace = repo.get_turn_trace(run_id, turn_id)
    kinds = [e["kind"] for e in trace]

    # Full ordered chain still present.
    assert kinds[: len(TRACE_KINDS)] == TRACE_KINDS
    assert kinds[-1] == "action_resolved"

    by_kind = {e["kind"]: e for e in trace}
    # Optional fields are present-but-null, not missing keys (consumers rely on shape).
    assert by_kind["perceived"]["payload"]["perceived_summary"] is None
    rp = by_kind["reasoning"]["payload"]
    assert rp["reasoning"] is None
    assert rp["memories_used"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 6. SNAPSHOTS + REPLAY DETERMINISM (the headline guarantee)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_snapshots_written_at_tick0_and_every_interval():
    """Snapshots exist at tick 0 and at every snapshot_interval_ticks."""
    interval = 5
    loop, world, repo, _ = _make_loop(
        params=_make_params(snapshot_interval_ticks=interval),
        script=[{"action": "forage", "args": {}}],
    )
    run_id = loop._run_id

    await _run_ticks(loop, world, 17)  # crosses ticks 5, 10, 15

    snap_ticks = [s["tick"] for s in repo.get_snapshots(run_id)]
    assert 0 in snap_ticks, "no tick-0 snapshot"
    for t in (5, 10, 15):
        assert t in snap_ticks, f"missing snapshot at tick {t}: {snap_ticks}"
    # And only at cadence ticks (no stray off-cadence snapshots).
    assert all(t == 0 or t % interval == 0 for t in snap_ticks), snap_ticks


def _agents_state_map(snapshot_agents: list[dict]) -> dict[str, tuple]:
    """Reduce a snapshot's agents list to {id: (location, energy, credits)} for
    position/energy/credits comparison (the replay guarantee's payload)."""
    return {
        a["id"]: (a["location"], round(float(a["energy"]), 2), int(a["credits"]))
        for a in snapshot_agents
    }


@pytest.mark.asyncio
async def test_replay_nearest_snapshot_matches_live_projection_at_T():
    """HEADLINE: replay(T) reconstructs the SAME agent positions/energy/credits as
    the live world projection at T.

    Strategy: snapshot_interval_ticks=1 so a snapshot is written at every tick.
    Drive the loop to T, capture the live world projection (world.to_snapshot at
    that exact tick), and assert nearest_snapshot(T).state — which the engine wrote
    independently during the run — reproduces the same agents state. This is a real
    equality on positions/energy/credits, not a smoke test."""
    loop, world, repo, _ = _make_loop(
        params=_make_params(snapshot_interval_ticks=1, starting_energy=100.0),
        # Movement + economy so positions, energy AND credits all diverge across agents.
        script=[
            {"action": "work", "args": {}},
            {"action": "move_to", "args": {"place": "plaza"}},
            {"action": "forage", "args": {}},
            {"action": "move_to", "args": {"place": "market"}},
            {"action": "recharge", "args": {}},
        ],
    )
    run_id = loop._run_id

    captured: dict[int, dict] = {}
    # Drive turn by turn. W9 / event-log v1.1.0 §3: the snapshot at tick S is the
    # state AFTER all tick-S events — i.e. the turn that just ran (stamped tick
    # world.tick - 1) wrote a snapshot at that tick reflecting the post-turn
    # state. Capture the live projection NOW and key it by that completed tick.
    for _ in range(20):
        agent = world.next_agent()
        await loop._execute_turn(agent)
        T = world.tick - 1  # the tick the completed turn's events were stamped with
        captured[T] = _agents_state_map(world.to_snapshot()["agents"])

    assert captured, "no ticks captured"

    # For a representative spread of T values, the independently-written snapshot at
    # tick T must reproduce the live projection captured at T.
    checked = 0
    for T, live in captured.items():
        snap = repo.nearest_snapshot(run_id, T)
        assert snap is not None, f"no snapshot at or before tick {T}"
        assert snap["tick"] == T, (
            f"with interval=1 the nearest snapshot for {T} should be exactly {T}, "
            f"got {snap['tick']}"
        )
        replayed = _agents_state_map(snap["state"]["agents"])
        assert replayed == live, (
            f"replay(T={T}) diverged from live projection.\n"
            f"  replayed={replayed}\n  live    ={live}"
        )
        checked += 1
    assert checked >= 15, f"expected to verify many ticks, only checked {checked}"


@pytest.mark.asyncio
async def test_replay_fold_forward_from_earlier_snapshot_matches_live():
    """Fold-forward variant: with a coarser snapshot cadence, nearest_snapshot(T)
    lands on an EARLIER tick; folding the credit-changing events (work/forage/give)
    from that snapshot forward over get_events up to T reconstructs the same
    per-agent credits the live world holds at T."""
    interval = 5
    loop, world, repo, _ = _make_loop(
        agent_count=3,
        params=_make_params(snapshot_interval_ticks=interval, starting_credits=20),
        script=[{"action": "work", "args": {}}],  # +work_reward credits every turn
    )
    run_id = loop._run_id

    T = 13  # between snapshots at 10 and 15 -> nearest is tick 10, must fold 11..13
    await _run_ticks(loop, world, T)
    live_credits = {a.id: a.credits for a in world.agents.values()}

    snap = repo.nearest_snapshot(run_id, T)
    assert snap is not None
    assert snap["tick"] <= T and snap["tick"] < 15
    base_tick = snap["tick"]

    # W9 / event-log v1.1.0 §3 (normative): a snapshot at tick K is the state
    # AFTER all tick-K events. So the fold window is STRICT on the left:
    # (base_tick, T] — i.e. events stamped base_tick+1 .. T-1 here (the last
    # completed turn stamped tick T-1). 'work' emits economy{credits_delta} rows.
    folded = {
        a["id"]: int(a["credits"]) for a in snap["state"]["agents"]
    }
    fold_events = repo.get_events(
        run_id, from_tick=base_tick + 1, to_tick=T - 1, kinds=["economy"], order="asc"
    )
    assert fold_events, "expected economy rows to fold forward"
    for ev in fold_events:
        actor = ev["actor_id"]
        delta = ev["payload"].get("credits_delta")
        if actor in folded and isinstance(delta, (int, float)):
            folded[actor] += int(delta)

    assert folded == live_credits, (
        f"fold-forward from snapshot@{base_tick} to T={T} != live.\n"
        f"  folded={folded}\n  live  ={live_credits}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 7. READ API
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_events_filters_per_contract():
    """get_events honors kinds, actor_id, turn_id, from/to_tick, after_seq, order."""
    loop, world, repo, _ = _make_loop(
        agent_count=2, script=[{"action": "forage", "args": {}}]
    )
    run_id = loop._run_id
    await _run_ticks(loop, world, 10)

    all_events = repo.get_events(run_id, order="asc")
    assert all_events

    # kinds filter.
    only_llm = repo.get_events(run_id, kinds=["llm_call"], order="asc")
    assert only_llm and all(e["kind"] == "llm_call" for e in only_llm)

    # actor_id filter.
    some_actor = next(e["actor_id"] for e in all_events if e["actor_id"])
    by_actor = repo.get_events(run_id, actor_id=some_actor)
    assert by_actor and all(e["actor_id"] == some_actor for e in by_actor)

    # turn_id filter == get_turn_trace membership.
    a_turn = next(e["turn_id"] for e in all_events if e["turn_id"])
    by_turn = repo.get_events(run_id, turn_id=a_turn)
    assert by_turn and all(e["turn_id"] == a_turn for e in by_turn)

    # from_tick / to_tick window.
    windowed = repo.get_events(run_id, from_tick=2, to_tick=4)
    assert windowed and all(2 <= e["tick"] <= 4 for e in windowed)

    # after_seq keyset pagination.
    pivot = all_events[len(all_events) // 2]["seq"]
    tail = repo.get_events(run_id, after_seq=pivot, order="asc")
    assert tail and all(e["seq"] > pivot for e in tail)

    # order asc vs desc.
    asc = repo.get_events(run_id, order="asc")
    desc = repo.get_events(run_id, order="desc")
    assert [e["seq"] for e in asc] == sorted(e["seq"] for e in asc)
    assert [e["seq"] for e in desc] == sorted((e["seq"] for e in desc), reverse=True)

    # limit.
    limited = repo.get_events(run_id, limit=3, order="asc")
    assert len(limited) == 3


@pytest.mark.asyncio
async def test_get_rule_history_reflects_proposed_to_passed():
    """get_rule_history surfaces a rule's proposed -> passed lifecycle with votes."""
    loop, world, repo, _ = _make_loop(agent_count=1, script=[
        {"action": "propose_rule",
         "args": {"effect": "ubi", "text": "everyone gets a basic income"}},
        {"action": "idle", "args": {}},  # replaced by the dynamic YES vote
    ])
    # Civic actions are gated to the governance place — stand at the town hall.
    next(iter(world.agents.values())).location = "townhall"
    run_id = loop._run_id
    await _run_ticks(loop, world, 2)

    history = repo.get_rule_history(run_id)
    assert history, "no rule history"
    entry = history[0]
    # Documented top-level keys present.
    for key in ("rule_id", "effect", "text", "proposer_id", "status",
                "created_tick", "votes", "resolved_tick", "outcome", "downstream"):
        assert key in entry, f"rule history missing key {key}"
    assert entry["effect"] == "ubi"
    assert entry["status"] == "active"
    assert entry["outcome"] == "passed"
    assert entry["votes"], "expected at least one recorded vote"
    assert any(v["choice"] for v in entry["votes"]), "expected a YES vote"


@pytest.mark.asyncio
async def test_get_analytics_returns_documented_top_level_keys():
    """get_analytics returns the documented 9-AWI + by_model + usage spine."""
    loop, world, repo, _ = _make_loop()  # default scripts: work/forage/propose/vote/...
    run_id = loop._run_id
    await _run_ticks(loop, world, 30)

    analytics = repo.get_analytics(run_id)
    documented = {
        "population", "crime", "tool_exploration", "space_exploration",
        "governance", "public_expression", "social_fabric", "economy",
        "constitution", "by_model", "usage",
    }
    assert documented <= set(analytics.keys()), (
        f"missing analytics keys: {documented - set(analytics.keys())}"
    )
    # A few nested shapes the dashboard depends on.
    assert "by_kind" in analytics["crime"]
    assert "by_agent" in analytics["economy"]
    assert {"participation", "proposed", "passed", "rejected"} <= set(
        analytics["governance"].keys()
    )
    assert "by_profile" in analytics["usage"]
    # llm_call rows were emitted under the 'mock' request model => usage tracked.
    assert "mock" in analytics["usage"]["by_profile"]
    assert analytics["usage"]["by_profile"]["mock"]["requests"] > 0


@pytest.mark.asyncio
async def test_get_events_default_order_is_asc():
    """Contract default order == 'asc'."""
    loop, world, repo, _ = _make_loop(script=[{"action": "forage", "args": {}}])
    run_id = loop._run_id
    await _run_ticks(loop, world, 4)
    default = repo.get_events(run_id)
    assert [e["seq"] for e in default] == sorted(e["seq"] for e in default)

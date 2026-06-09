"""
W9 gate tests — "Make v2 true" (EM-069–074, backend side).

Contracts under test:
  - contracts/event-log.md v1.1.0 §1 — llm_call exactly once per attempt (B6)
  - contracts/event-log.md v1.1.0 §2 — animal turns own their turn_id (B1)
  - contracts/event-log.md v1.1.0 §3 — snapshot-after-tick boundary, strict-left
    fold, scheduler state in snapshots (B7/B8/C4)
  - contracts/event-log.md v1.1.0 §4 — agent_starving + world_extinct (EM-070/071)
  - contracts/api.openapi.yaml v1.2.0 — /api/replay returns the delta only (B7)
  - audit 2026-06-09 §B2/B3/B4/B5/B12 — reset race + cache flush, ban_arson
    proposable, build_step on funded planned, recharge-at-full rejection.

Everything is deterministic and offline (MockProvider / scripted local
providers; no network, no real LLM), following the tests/test_event_log.py and
tests/test_w8.py idioms. Turns are driven one at a time through
TickLoop._execute_turn — the same path the asyncio loop uses.

NOTE (W9-QA-1, RESOLVED 2026-06-09): the replay fold-forward property test
originally exposed a destination-key mismatch (backend agent_moved emits
payload.place; the frontend fold read to/location/target_id only). The
frontend fix landed in selectors.ts (place-first chain at both sites) and the
property test now mirrors the shipped chain. The backend half of the same
mismatch (W9-QA-1b, repository.py get_analytics space-exploration) is still
open — pinned by the one remaining strict xfail below, W10/EM-076 scope.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from petridish.engine.world import World, AgentState, PlaceState, Building
from petridish.config.loader import (
    WorldParams, ModelProfile, WorldConfig, AgentConfig, PlaceConfig,
    AnimalParams, AnimalSeed,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.mock import MockProvider


# ──────────────────────────────────────────────────────────────────────────────
# Harness (test_event_log.py idiom, plus a provider override for retry/race tests)
# ──────────────────────────────────────────────────────────────────────────────

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
    provider: object | None = None,
):
    """Wire World + Router(mock) + Runtime + repo + loop, init a real run.

    `provider` overrides the 'mock' profile's adapter (for retry / blocking
    providers); otherwise a scripted MockProvider drives every agent.
    Returns (loop, world, repo, router, events) — `events` is the broadcast
    sink (both event rows and world_state messages).
    """
    params = params or _make_params()
    places = [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=20, y=0, kind="governance"),
        PlaceState(id="home", name="Hearth", x=30, y=0, kind="home"),
    ]
    names = ["Ada", "Bram", "Cleo", "Dov", "Esi"][:agent_count]
    agents = [
        AgentState(
            id=f"agent_{n.lower()}", name=n, personality="Test agent.",
            profile="mock", location="market",
            energy=params.starting_energy, credits=params.starting_credits,
        )
        for n in names
    ]
    world = World(params=params, places=places, agents=agents)

    adapter = provider if provider is not None else MockProvider(script=script)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71")],
        adapter_overrides={"mock": adapter},
    )
    for a in agents:
        router.reassign(a.id, "mock")

    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)

    events: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: events.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[]))
    return loop, world, repo, router, events


async def _run_ticks(loop: TickLoop, world: World, n: int) -> None:
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        if not agent.alive:
            continue
        await loop._execute_turn(agent)


# ──────────────────────────────────────────────────────────────────────────────
# 1. B6 — llm_call exactly once per attempt (event-log v1.1.0 §1)
# ──────────────────────────────────────────────────────────────────────────────

class FlakyThenValidProvider:
    """First chat() returns unparseable text (forcing the ONE retry), the second
    returns a valid action — so a single turn carries attempts 1 and 2."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = None
    last_usage = None

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        if self.calls == 1:
            return "sorry, I cannot answer in the requested format"
        return json.dumps({"action": "forage", "args": {}})


@pytest.mark.asyncio
async def test_llm_call_exactly_one_row_per_turn_without_retry():
    """A clean (no-retry) turn emits EXACTLY one llm_call row, attempt=1."""
    loop, world, repo, _, _ = _make_loop(script=[{"action": "forage", "args": {}}])
    run_id = loop._run_id
    await _run_ticks(loop, world, 6)

    starts = repo.get_events(run_id, kinds=["turn_start"], order="asc")
    assert len(starts) == 6
    for s in starts:
        rows = [e for e in repo.get_turn_trace(run_id, s["turn_id"])
                if e["kind"] == "llm_call"]
        assert len(rows) == 1, (
            f"turn {s['turn_id']} emitted {len(rows)} llm_call rows (must be 1)"
        )
        assert rows[0]["payload"]["attempt"] == 1


@pytest.mark.asyncio
async def test_retry_turn_emits_attempts_1_and_2_never_duplicates():
    """A parse-failure-then-success turn emits llm_call rows attempt=1 and
    attempt=2 under one turn_id — two rows total, no duplicates (the live bug
    was identical duplicate spans, audit B6)."""
    provider = FlakyThenValidProvider()
    loop, world, repo, _, _ = _make_loop(provider=provider, agent_count=1)
    run_id = loop._run_id

    agent = world.next_agent()
    await loop._execute_turn(agent)
    assert provider.calls == 2, "expected exactly one retry"

    rows = repo.get_events(run_id, kinds=["llm_call"], order="asc")
    assert [r["payload"]["attempt"] for r in rows] == [1, 2], (
        f"expected attempts [1, 2], got {[r['payload']['attempt'] for r in rows]}"
    )
    # Both under the same turn_id; the turn resolved ok after the retry.
    assert len({r["turn_id"] for r in rows}) == 1
    resolved = repo.get_events(run_id, kinds=["action_resolved"])[-1]
    assert resolved["payload"]["outcome"] == "ok"


@pytest.mark.asyncio
async def test_duplicated_attempt_spans_and_legacy_llm_key_dedupe():
    """A trace carrying a DUPLICATED attempt-1 span AND the legacy W5 `llm` key
    still yields exactly one llm_call row per unique attempt (v1.1.0 §1)."""
    loop, world, repo, _, _ = _make_loop()
    run_id = loop._run_id
    agent = next(iter(world.agents.values()))

    loop._current_turn_id = "w9-dup-turn"
    try:
        loop._emit_trace_chain(agent, "mock", "#2ecc71", {
            "perceived": {}, "memory": {},
            "llm_attempts": [
                {"attempt": 1, "latency_ms": 1.0},
                {"attempt": 1, "latency_ms": 1.01},   # the duplicate span (B6)
                {"attempt": 2, "latency_ms": 2.0},
            ],
            "llm": {"attempt": 1, "latency_ms": 1.0},  # legacy W5 final-attempt key
            "reasoning": {}, "action_chosen": {},
        })
    finally:
        loop._current_turn_id = None

    rows = repo.get_events(run_id, kinds=["llm_call"], turn_id="w9-dup-turn",
                           order="asc")
    assert [r["payload"]["attempt"] for r in rows] == [1, 2], (
        "duplicated spans / legacy llm key produced duplicate llm_call rows"
    )


@pytest.mark.asyncio
async def test_legacy_llm_key_alone_yields_single_empty_span():
    """A trace with ONLY the legacy `llm` key (no llm_attempts) emits exactly
    one llm_call row — the uniform empty span with present-but-null OTel keys."""
    loop, world, repo, _, _ = _make_loop()
    run_id = loop._run_id
    agent = next(iter(world.agents.values()))

    loop._current_turn_id = "w9-legacy-turn"
    try:
        loop._emit_trace_chain(agent, "mock", "#2ecc71", {
            "perceived": {}, "memory": {},
            "llm": {"attempt": 1, "latency_ms": 9.9},
            "reasoning": {}, "action_chosen": {},
        })
    finally:
        loop._current_turn_id = None

    rows = repo.get_events(run_id, kinds=["llm_call"], turn_id="w9-legacy-turn")
    assert len(rows) == 1
    assert rows[0]["payload"]["attempt"] == 1
    # OTel keys are present-but-null on the empty span.
    assert rows[0]["payload"]["gen_ai.usage.input_tokens"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 2. B1 — animal turn_id isolation (event-log v1.1.0 §2)
# ──────────────────────────────────────────────────────────────────────────────

class CountingAnimalMock:
    name = "gemini-flash"
    color = "#3498db"
    last_routed_via = "gemini-flash"
    last_usage = {"input_tokens": 11, "output_tokens": 7, "latency_ms": 1.0,
                  "finish_reason": "stop", "cached": False}

    def __init__(self, response):
        self.calls = 0
        self._response = response

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        return self._response


def _build_animal_world(llm_chance: float, animal_response: str | None = None):
    """test_w8-style world: 2 agents (mock) + animals on a 1-tick cadence."""
    params = WorldParams(
        energy_decay_per_turn=0.0, death_after_zero_turns=99, turns_per_day=999,
        animals=AnimalParams(enabled=True, act_every_n_ticks=1,
                             llm_chance=llm_chance, model_profile="gemini-flash"),
    )
    places = [PlaceState(id="plaza", name="Plaza", x=500, y=500, kind="social"),
              PlaceState(id="commons", name="Commons", x=500, y=750, kind="wild")]
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=10),
        AgentState(id="agent_bram", name="Bram", personality="", profile="mock",
                   location="plaza", energy=100.0, credits=10),
    ]
    world = World(params=params, places=places, agents=agents)
    overrides = {}
    if animal_response is not None:
        overrides["gemini-flash"] = CountingAnimalMock(animal_response)
    router = Router(
        [ModelProfile(name="mock", adapter="mock", model_id="mock", color="#2ecc71"),
         ModelProfile(name="gemini-flash", adapter="mock",
                      model_id="gemini-2.0-flash", color="#3498db")],
        adapter_overrides=overrides or None, cache_enabled=False,
    )
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    events: list[dict] = []
    loop = TickLoop(world, runtime, repo, router,
                    broadcaster=lambda m: events.append(m))
    cfg = WorldConfig(world=params, places=[], agents=[],
                      animals=[AnimalSeed("cat", "Mochi", "plaza"),
                               AnimalSeed("dog", "Biscuit", "plaza")])
    loop.init_run(cfg)
    return loop, world, repo, events


@pytest.mark.asyncio
async def test_animal_events_never_inherit_agent_turn_id():
    """Integration: with animals on every tick alongside agent turns, NO animal
    event carries any agent turn_id; each animal's turn shares ONE fresh
    turn_id, distinct per animal; agent turn traces stay animal-free."""
    arson = json.dumps({"animal_thought": "burn", "action": "arson",
                        "args": {"building_id": "bld_x"}})
    loop, world, repo, events = _build_animal_world(1.0, animal_response=arson)
    world.buildings["bld_x"] = Building(id="bld_x", name="Clocktower",
                                        kind="clocktower", location="plaza",
                                        status="operational", health=100)
    run_id = loop._run_id
    events.clear()

    for _ in range(4):
        agent = world.next_agent()
        await loop._execute_turn(agent)
        if loop._animal_task is not None:
            await loop._animal_task

    rows = [e for e in events if e.get("type") == "event"]
    agent_turn_ids = {e["turn_id"] for e in rows if e["kind"] == "turn_start"}
    assert agent_turn_ids

    animal_rows = [e for e in rows if e.get("actor_type") == "animal"]
    assert animal_rows, "expected animal events"
    for e in animal_rows:
        assert e["turn_id"] is not None, f"animal event {e['kind']} missing turn_id"
        assert e["turn_id"] not in agent_turn_ids, (
            f"animal event {e['kind']} inherited an AGENT turn_id (audit B1)"
        )

    # One fresh turn_id per animal turn: a turn_id never spans two ANIMALS.
    # (An animal's structure_state_changed side-effect row legitimately carries
    # actor_id None while sharing its animal's turn_id — ignore those.)
    by_turn: dict[str, set] = {}
    for e in animal_rows:
        by_turn.setdefault(e["turn_id"], set()).add(e["actor_id"])
    for turn_id, actors in by_turn.items():
        named = actors - {None}
        assert len(named) == 1, (
            f"animal turn_id {turn_id} shared across actors {named}"
        )
    # Distinct animals in the same batch got DISTINCT (fresh) turn_ids.
    turn_ids_by_actor: dict[str, set] = {}
    for e in animal_rows:
        if e["actor_id"]:
            turn_ids_by_actor.setdefault(e["actor_id"], set()).add(e["turn_id"])
    assert len(turn_ids_by_actor) == 2, "expected both animals to act"
    ids_a, ids_b = turn_ids_by_actor.values()
    assert not (ids_a & ids_b), "two animals shared a turn_id"

    # get_turn_trace(agent_turn_id) returns ONLY that agent's chain.
    for tid in agent_turn_ids:
        trace = repo.get_turn_trace(run_id, tid)
        assert trace
        actor_ids = {e["actor_id"] for e in trace}
        assert len(actor_ids) == 1
        assert all(e["actor_type"] != "animal" for e in trace), (
            f"agent turn {tid} trace polluted by animal events"
        )


@pytest.mark.asyncio
async def test_animal_turns_ignore_inflight_agent_turn_id_sentinel():
    """White-box B1: run the animal batch while an agent turn_id is 'in flight'
    (_current_turn_id set) — the exact contamination path from the audit. No
    animal event may carry the sentinel."""
    loop, world, repo, events = _build_animal_world(0.0)  # reflex-only, no LLM
    events.clear()

    loop._current_turn_id = "AGENT-INFLIGHT-SENTINEL"
    try:
        await loop._run_animal_turns(world.tick)
    finally:
        loop._current_turn_id = None

    animal_rows = [e for e in events
                   if e.get("type") == "event" and e.get("actor_type") == "animal"]
    assert animal_rows, "reflex animal turns should still emit animal_action"
    for e in animal_rows:
        assert e["turn_id"] != "AGENT-INFLIGHT-SENTINEL", (
            "animal event stamped with the in-flight agent turn_id (audit B1)"
        )
        assert e["turn_id"], "animal event must carry its OWN uuid turn_id"


# ──────────────────────────────────────────────────────────────────────────────
# 3. B7/B8/C4 — replay delta + fold-forward property
# ──────────────────────────────────────────────────────────────────────────────

def _replay_materials(repo: SQLiteRepository, run_id: int, tick: int) -> dict:
    """Repository-equivalent of GET /api/replay (api.openapi.yaml v1.2.0)."""
    base = repo.nearest_snapshot(run_id, tick)
    from_tick = (base["tick"] + 1) if base is not None else 0
    return {"base": base,
            "events": repo.get_events(run_id, from_tick=from_tick,
                                      to_tick=tick, order="asc")}


def _fold_agent_state(
    roster: dict[str, str],
    known_places: set[str],
    base: dict | None,
    delta: list[dict],
    *,
    dest_keys: tuple[str, ...],
    use_target_id: bool,
) -> dict[str, tuple[str, bool]]:
    """Replicates the frontend replayStateAt fold (selectors.ts) for agent
    location + alive: base snapshot state, then agent_moved / agent_died from
    the strict-left delta. `dest_keys`/`use_target_id` parameterize how the
    agent_moved destination is extracted (see the xfail test below)."""
    loc = dict(roster)
    alive = {aid: True for aid in roster}
    if base:
        for a in base["state"]["agents"]:
            loc[a["id"]] = a["location"]
            if "alive" in a:
                alive[a["id"]] = a["alive"]
    for e in sorted(delta, key=lambda r: r["seq"]):
        payload = e.get("payload") or {}
        if e["kind"] == "agent_moved" and e.get("actor_id"):
            to = None
            for k in dest_keys:
                v = payload.get(k)
                if isinstance(v, str) and v:
                    to = v
                    break
            if to is None and use_target_id:
                to = e.get("target_id")
            if to and to in known_places:
                loc[e["actor_id"]] = to
        elif e["kind"] == "agent_died" and e.get("actor_id"):
            alive[e["actor_id"]] = False
    return {aid: (loc[aid], alive[aid]) for aid in roster}


async def _drive_replay_run(loop, world, repo):
    """Drive 18 turns of alternating moves (snapshots every 5 ticks), god-kill
    one agent at tick 10, capturing ground-truth {id: (location, alive)} keyed
    by the completed tick. Returns (captured, roster, known_places)."""
    roster = {a.id: a.location for a in world.agents.values()}
    known_places = set(world.places.keys())
    captured: dict[int, dict] = {}
    for i in range(18):
        if i == 10:
            # God-kill path between turns (mirrors DELETE /api/agents/{id}).
            victim = world.agents["agent_cleo"]
            world.kill_agent(victim.id)
            loop._emit_event({
                "kind": "agent_died", "actor_id": victim.id,
                "text": f"{victim.name} was removed.",
                "payload": {"reason": "killed_via_api"},
            })
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)
        T = world.tick - 1  # the tick the completed turn's events were stamped with
        captured[T] = {a.id: (a.location, a.alive) for a in world.agents.values()}
    return captured, roster, known_places


@pytest.mark.asyncio
async def test_api_replay_returns_strict_left_delta(monkeypatch):
    """GET /api/replay (the real handler): base.tick <= T and `events` is ONLY
    the fold delta — every row strictly base.tick < e.tick <= T (audit B7)."""
    loop, world, repo, _, _ = _make_loop(
        script=[{"action": "move_to", "args": {"place": "plaza"}},
                {"action": "move_to", "args": {"place": "market"}}],
    )
    run_id = loop._run_id
    await _run_ticks(loop, world, 17)

    import petridish.api.app  # noqa: F401 — ensure module is loaded
    appmod = sys.modules["petridish.api.app"]
    monkeypatch.setattr(appmod, "_repo", repo)
    monkeypatch.setattr(appmod, "_loop", loop)

    for T in (0, 3, 7, 10, 13, 16):
        out = await appmod.get_replay(tick=T)
        base, events = out["base"], out["events"]
        assert base is not None, f"no snapshot base for T={T}"
        assert base["tick"] <= T
        for e in events:
            assert base["tick"] < e["tick"] <= T, (
                f"T={T}: event tick {e['tick']} outside strict-left window "
                f"({base['tick']}, {T}] (audit B7)"
            )
        # Handler output == the documented repository materials.
        assert out == _replay_materials(repo, run_id, T)
        # Mid-window Ts genuinely fold (the delta is non-empty when T > base).
        if T not in (0, 10):
            assert events, f"expected a non-empty delta at T={T}"


@pytest.mark.asyncio
async def test_snapshots_carry_scheduler_state_keys():
    """B8: snapshots serialize round / turn_order / turn_index (v1.1.0 §3)."""
    loop, world, repo, _, _ = _make_loop(script=[{"action": "forage", "args": {}}])
    run_id = loop._run_id
    await _run_ticks(loop, world, 7)

    for T in (0, 5):
        snap = repo.nearest_snapshot(run_id, T)
        assert snap is not None and snap["tick"] == T
        state = snap["state"]
        for key in ("round", "turn_order", "turn_index"):
            assert key in state, f"snapshot@{T} missing scheduler key {key!r} (B8)"
        assert isinstance(state["round"], int)
        assert isinstance(state["turn_index"], int)
        assert set(state["turn_order"]) <= set(world.agents.keys())


@pytest.mark.asyncio
async def test_replay_fold_forward_property_matches_ground_truth():
    """PROPERTY: for many T, folding the /api/replay delta onto base.state
    (replayStateAt-style fold for agent location/alive) reproduces the ground
    truth captured live at T — including a mid-run god-kill.

    The destination extraction mirrors the SHIPPED frontend chain exactly
    (selectors.ts replayStateAt, post-W9-QA-1 fix): payload.place first (the
    key the backend actually emits), then to / location / target_id fallbacks.
    History: this test's former strict-xfail twin pinned W9-QA-1 (the frontend
    read only to/location/target_id, so the delta never moved anyone); the
    frontend fix landed 2026-06-09 and the twin is folded in here. If the
    frontend chain ever changes, change `dest_keys` with it."""
    loop, world, repo, _, _ = _make_loop(
        script=[{"action": "move_to", "args": {"place": "plaza"}},
                {"action": "move_to", "args": {"place": "market"}}],
    )
    run_id = loop._run_id
    captured, roster, known_places = await _drive_replay_run(loop, world, repo)

    checked = 0
    for T, truth in captured.items():
        m = _replay_materials(repo, run_id, T)
        folded = _fold_agent_state(
            roster, known_places, m["base"], m["events"],
            dest_keys=("place", "to", "location"), use_target_id=True,
        )
        assert folded == truth, (
            f"fold-forward at T={T} diverged from ground truth.\n"
            f"  base   ={m['base']['tick'] if m['base'] else None}\n"
            f"  folded ={folded}\n  truth  ={truth}"
        )
        checked += 1
    assert checked >= 15


@pytest.mark.xfail(
    strict=True,
    reason=(
        "W9-QA-1b (REAL BUG, W10/EM-076 scope): the backend's own "
        "get_analytics space-exploration aggregation (repository.py:593) reads "
        "payload['to'] / payload['location'] / target_id from agent_moved rows, "
        "while the emitter writes payload['place'] — so the AWI "
        "space_exploration indicator is ALWAYS empty on real runs. Pre-existing "
        "(W6-era), surfaced by the W9 fold-forward property work. The FRONTEND "
        "half of this mismatch (W9-QA-1, selectors.ts) was fixed 2026-06-09; "
        "this backend half remains. strict=True: fixing repository.py flips "
        "this test loudly — then drop the marker."
    ),
)
@pytest.mark.asyncio
async def test_analytics_space_exploration_counts_moves_xfail():
    loop, world, repo, _, _ = _make_loop(
        script=[{"action": "move_to", "args": {"place": "plaza"}},
                {"action": "move_to", "args": {"place": "market"}}],
    )
    await _run_ticks(loop, world, 8)
    assert repo.get_events(loop._run_id, kinds=["agent_moved"]), "moves happened"
    by_agent = repo.get_analytics(loop._run_id)["space_exploration"]["by_agent"]
    assert by_agent, (
        "space_exploration.by_agent empty despite agent_moved events"
    )


# ──────────────────────────────────────────────────────────────────────────────
# 4. EM-070 / B5 — recharge at full energy is a rejection, never a charge
# ──────────────────────────────────────────────────────────────────────────────

def test_world_action_recharge_at_full_rejects_without_charge():
    """World core: recharge at energy>=100 returns (False, 'already_full', 0.0)
    and moves NO credits; a non-full agent still pays and gains."""
    loop, world, _, _, _ = _make_loop(
        params=_make_params(starting_energy=100.0, energy_decay_per_turn=0.0))
    agent = next(iter(world.agents.values()))
    before = agent.credits

    ok, reason, gained = world.action_recharge(agent)
    assert (ok, reason, gained) == (False, "already_full", 0.0)
    assert agent.credits == before, "recharge-at-full charged credits (audit B5)"

    # Sanity guard against over-rejection: a hungry agent still recharges.
    agent.energy = 50.0
    ok, reason, gained = world.action_recharge(agent)
    assert ok and gained > 0
    assert agent.credits == before - world.params.recharge_cost


@pytest.mark.asyncio
async def test_recharge_at_full_turn_rejected_with_reason_no_charge():
    """Full pipeline: an agent at 100 energy choosing recharge gets a validator
    rejection ('energy already full'), outcome=failed, credits unchanged."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1,
        params=_make_params(starting_energy=100.0, energy_decay_per_turn=0.0),
        script=[{"action": "recharge", "args": {}}],
    )
    run_id = loop._run_id
    agent = world.next_agent()
    before = agent.credits
    await loop._execute_turn(agent)

    assert agent.credits == before, "rejected recharge still charged credits"
    failures = repo.get_events(run_id, kinds=["parse_failure"])
    assert failures, "recharge-at-full should surface as a rejected action"
    assert "already full" in failures[-1]["payload"]["reason"], failures[-1]["payload"]
    resolved = repo.get_events(run_id, kinds=["action_resolved"])[-1]
    assert resolved["payload"]["outcome"] == "failed"


# ──────────────────────────────────────────────────────────────────────────────
# 5. EM-070 — agent_starving events + turns_until_death surfacing
# ──────────────────────────────────────────────────────────────────────────────

def _starving_params(**overrides) -> WorldParams:
    base = dict(starting_energy=30.0, energy_decay_per_turn=10.0,
                starving_warn_threshold=25.0, death_after_zero_turns=3,
                starting_credits=0, recharge_cost=2)
    base.update(overrides)
    return _make_params(**base)


@pytest.mark.asyncio
async def test_starving_threshold_cross_emits_exactly_once():
    """Crossing the threshold downward emits ONE agent_starving with
    {energy, turns_until_death, threshold}; staying below emits no more."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1, params=_starving_params(),
        script=[{"action": "idle", "args": {}}],
    )
    run_id = loop._run_id

    await _run_ticks(loop, world, 1)  # 30 -> 20 (< 25): the cross
    rows = repo.get_events(run_id, kinds=["agent_starving"])
    assert len(rows) == 1, f"expected one threshold-cross warning, got {len(rows)}"
    payload = rows[0]["payload"]
    assert payload["threshold"] == 25.0
    assert payload["energy"] == 20.0
    assert payload["turns_until_death"] is None  # energy > 0: no countdown yet
    assert rows[0]["actor_type"] == "human_agent"

    await _run_ticks(loop, world, 1)  # 20 -> 10: still below, already warned
    rows = repo.get_events(run_id, kinds=["agent_starving"])
    assert len(rows) == 1, "one-shot warning re-fired without recovery"


@pytest.mark.asyncio
async def test_starving_warning_rearms_after_recovery():
    """Recovering past the threshold re-arms the one-shot warning."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1, params=_starving_params(),
        script=[{"action": "idle", "args": {}}],
    )
    run_id = loop._run_id
    agent = next(iter(world.agents.values()))

    await _run_ticks(loop, world, 1)            # 30 -> 20: warn #1
    agent.energy = 100.0                        # recovery (e.g. recharge/festival)
    await _run_ticks(loop, world, 1)            # 100 -> 90: re-arms, no event
    assert len(repo.get_events(run_id, kinds=["agent_starving"])) == 1
    agent.energy = 30.0
    await _run_ticks(loop, world, 1)            # 30 -> 20: warn #2
    assert len(repo.get_events(run_id, kinds=["agent_starving"])) == 2, (
        "warning did not re-arm after the agent recovered past the threshold"
    )


@pytest.mark.asyncio
async def test_zero_energy_countdown_decrements_until_death():
    """At 0 energy: one agent_starving per turn carrying a DECREMENTING
    turns_until_death, then agent_died; world_state carries the countdown."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1, params=_starving_params(),
        script=[{"action": "idle", "args": {}}],
    )
    run_id = loop._run_id
    agent = next(iter(world.agents.values()))

    # t1: 30->20 (cross warn) · t2: 20->10 · t3: 10->0 (countdown 2)
    await _run_ticks(loop, world, 3)
    rows = repo.get_events(run_id, kinds=["agent_starving"], order="asc")
    assert rows[-1]["payload"]["turns_until_death"] == 2

    # world_state agent carries turns_until_death (EM-070).
    snap_agent = world.to_snapshot()["agents"][0]
    assert snap_agent["turns_until_death"] == 2

    await _run_ticks(loop, world, 1)  # t4: countdown 1
    rows = repo.get_events(run_id, kinds=["agent_starving"], order="asc")
    countdowns = [r["payload"]["turns_until_death"] for r in rows
                  if r["payload"]["turns_until_death"] is not None]
    assert countdowns == [2, 1], f"countdown not decrementing: {countdowns}"

    await _run_ticks(loop, world, 1)  # t5: dies — agent_died, no extra countdown
    assert not agent.alive
    died = repo.get_events(run_id, kinds=["agent_died"])
    assert len(died) == 1
    rows = repo.get_events(run_id, kinds=["agent_starving"])
    assert len(rows) == 3, "death turn must emit agent_died, not another countdown"

    # Healthy agents surface turns_until_death = null.
    healthy_loop, healthy_world, *_ = _make_loop(agent_count=1)
    assert healthy_world.to_snapshot()["agents"][0]["turns_until_death"] is None


# ──────────────────────────────────────────────────────────────────────────────
# 6. EM-071 — extinction: world_extinct one-shot + auto-pause + god-kill + reset
# ──────────────────────────────────────────────────────────────────────────────

def _death_params(**overrides) -> WorldParams:
    base = dict(starting_energy=5.0, energy_decay_per_turn=10.0,
                death_after_zero_turns=1)
    base.update(overrides)
    return _make_params(**base)


@pytest.mark.asyncio
async def test_extinction_emits_once_with_payload_and_auto_pauses():
    loop, world, repo, _, _ = _make_loop(
        agent_count=1, params=_death_params(),
        script=[{"action": "idle", "args": {}}],
    )
    run_id = loop._run_id
    agent = next(iter(world.agents.values()))
    # Simulate a running loop so the pause is observable.
    loop._paused = False
    world.running = True

    await _run_ticks(loop, world, 1)  # energy -> 0, countdown 1 turn -> dead

    assert not world.living_agents()
    rows = repo.get_events(run_id, kinds=["world_extinct"])
    assert len(rows) == 1, f"expected exactly one world_extinct, got {len(rows)}"
    evt = rows[0]
    assert evt["actor_type"] == "system"
    assert evt["payload"] == {"tick": 0, "last_agent_id": agent.id,
                              "auto_paused": True}
    # Auto-pause (default true): the loop paused AFTER emitting + broadcasting.
    assert loop.is_running() is False
    assert world.running is False

    # One-shot: a later non-turn trigger must not re-emit.
    loop.handle_extinction(agent)
    assert len(repo.get_events(run_id, kinds=["world_extinct"])) == 1


@pytest.mark.asyncio
async def test_extinction_with_auto_pause_disabled_keeps_running():
    loop, world, repo, _, _ = _make_loop(
        agent_count=1,
        params=_death_params(auto_pause_on_extinction=False),
        script=[{"action": "idle", "args": {}}],
    )
    run_id = loop._run_id
    loop._paused = False
    world.running = True

    await _run_ticks(loop, world, 1)

    rows = repo.get_events(run_id, kinds=["world_extinct"])
    assert len(rows) == 1
    assert rows[0]["payload"]["auto_paused"] is False
    assert loop.is_running() is True, (
        "auto_pause_on_extinction=false must keep the loop running"
    )


@pytest.mark.asyncio
async def test_god_kill_last_agent_triggers_extinction_and_reset_rearms():
    """The DELETE /api/agents path (world.kill_agent + handle_extinction):
    killing the LAST agent emits world_extinct + pauses; killing a non-last
    agent does not; reset re-arms the one-shot for the new run."""
    loop, world, repo, router, _ = _make_loop(
        agent_count=2, script=[{"action": "idle", "args": {}}])
    run_id = loop._run_id
    ada, bram = world.agents["agent_ada"], world.agents["agent_bram"]
    loop._paused = False
    world.running = True

    # Kill #1 (one agent still alive): NOT extinction.
    world.kill_agent(ada.id)
    loop.handle_extinction(ada)
    assert repo.get_events(run_id, kinds=["world_extinct"]) == []
    assert loop.is_running() is True

    # Kill #2 (the last agent): extinction, with the god-killed agent's id.
    world.kill_agent(bram.id)
    loop.handle_extinction(bram)
    rows = repo.get_events(run_id, kinds=["world_extinct"])
    assert len(rows) == 1
    assert rows[0]["payload"]["last_agent_id"] == bram.id
    assert rows[0]["payload"]["auto_paused"] is True
    assert loop.is_running() is False

    # Idempotent on repeat triggers.
    loop.handle_extinction(bram)
    assert len(repo.get_events(run_id, kinds=["world_extinct"])) == 1

    # Reset re-arms the one-shot: a fresh run can go extinct again.
    cfg = WorldConfig(
        world=_make_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentConfig(name="Zed", personality="", profile="mock",
                            location="plaza")],
    )
    await loop.reset(cfg)
    assert loop._extinct_emitted is False, "reset must re-arm world_extinct"
    new_run = loop._run_id
    assert new_run != run_id
    zed = next(iter(world.agents.values()))
    world.kill_agent(zed.id)
    loop.handle_extinction(zed)
    rows = repo.get_events(new_run, kinds=["world_extinct"])
    assert len(rows) == 1 and rows[0]["payload"]["last_agent_id"] == zed.id


# ──────────────────────────────────────────────────────────────────────────────
# 7. B3 — ban_arson proposable, passes via votes, then enforced
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ban_arson_proposable_passes_and_blocks_arson():
    loop, world, repo, _, _ = _make_loop(agent_count=1, script=[
        {"action": "propose_rule",
         "args": {"effect": "ban_arson", "text": "no more fires"}},
        {"action": "idle", "args": {}},   # consumed by the dynamic YES vote
        {"action": "arson", "args": {"building_id": "bld_hall"}},
        {"action": "arson", "args": {"building_id": "bld_hall"}},  # the retry
    ])
    run_id = loop._run_id
    world.buildings["bld_hall"] = Building(
        id="bld_hall", name="Town Hall", kind="clocktower", location="market",
        status="operational", health=100)

    # Turn 1: propose (validator accepts the effect). Turn 2: sole YES vote.
    await _run_ticks(loop, world, 2)
    assert repo.get_events(run_id, kinds=["rule_passed"]), (
        "ban_arson proposal did not pass via votes (audit B3)"
    )
    assert world.has_active_rule("ban_arson")
    history = repo.get_rule_history(run_id)
    assert history[0]["effect"] == "ban_arson" and history[0]["status"] == "active"

    # Turn 3: arson is now rejected by the validator; building untouched.
    await _run_ticks(loop, world, 1)
    failures = repo.get_events(run_id, kinds=["parse_failure"])
    assert failures and "ban_arson" in failures[-1]["payload"]["reason"], (
        f"arson not gated by the active ban_arson rule: {failures}"
    )
    b = world.buildings["bld_hall"]
    assert b.health == 100 and b.status == "operational"


def test_world_propose_rule_accepts_ban_arson_effect():
    """World core: ban_arson is in valid_effects (was unreachable pre-W9)."""
    loop, world, _, _, _ = _make_loop(agent_count=1)
    agent = next(iter(world.agents.values()))
    ok, reason, rule = world.action_propose_rule(agent, "ban_arson", "no fires")
    assert ok and rule is not None and rule.effect == "ban_arson", reason


# ──────────────────────────────────────────────────────────────────────────────
# 8. B4 — build_step on a funded planned building
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_step_accepts_funded_planned_building():
    """A fully-funded `planned` building accepts build_step and auto-advances
    to under_construction with progress (audit B4)."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1,
        script=[{"action": "build_step", "args": {"building_id": "bld_fund"}}],
    )
    run_id = loop._run_id
    world.buildings["bld_fund"] = Building(
        id="bld_fund", name="Garden", kind="garden", location="market",
        status="planned", funds_committed=10, funds_required=10)

    await _run_ticks(loop, world, 1)

    b = world.buildings["bld_fund"]
    assert b.status == "under_construction", (
        f"funded planned building rejected by build_step: {b.status}"
    )
    assert b.progress > 0
    built = repo.get_events(run_id, kinds=["project_built"])
    assert built and built[0]["payload"]["building_id"] == "bld_fund"
    flips = repo.get_events(run_id, kinds=["structure_state_changed"])
    assert any(e["payload"]["to"] == "under_construction" for e in flips)
    assert repo.get_events(run_id, kinds=["parse_failure"]) == []


@pytest.mark.asyncio
async def test_build_step_rejects_unfunded_planned_building():
    """An UNFUNDED planned building stays rejected, with a funding reason."""
    loop, world, repo, _, _ = _make_loop(
        agent_count=1,
        script=[{"action": "build_step", "args": {"building_id": "bld_poor"}}],
    )
    run_id = loop._run_id
    world.buildings["bld_poor"] = Building(
        id="bld_poor", name="Library", kind="library", location="market",
        status="planned", funds_committed=3, funds_required=10)

    await _run_ticks(loop, world, 1)

    b = world.buildings["bld_poor"]
    assert b.status == "planned" and b.progress == 0
    failures = repo.get_events(run_id, kinds=["parse_failure"])
    assert failures, "unfunded planned build_step must be rejected"
    reason = failures[-1]["payload"]["reason"]
    assert "funded" in reason or "contribute_funds" in reason, reason


# ──────────────────────────────────────────────────────────────────────────────
# 9. B2/B12 — reset() awaits the in-flight turn + flushes the decision cache
# ──────────────────────────────────────────────────────────────────────────────

class GatedAgentProvider:
    """chat() blocks on an asyncio.Event — a stand-in for a hung 30s LLM call,
    so reset() can be exercised against a genuinely in-flight turn."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, gate: asyncio.Event):
        self._gate = gate
        self.calls = 0

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls += 1
        await self._gate.wait()
        return json.dumps({"action": "forage", "args": {}})


@pytest.mark.asyncio
async def test_reset_awaits_inflight_turn_and_flushes_cache():
    """reset() during a turn hung mid-LLM-call: the old tick task is awaited to
    completion (cancelled, not left running), the router decision cache is
    flushed (B12), and the released old turn never mutates the new world or
    writes into the new run (B2)."""
    gate = asyncio.Event()
    provider = GatedAgentProvider(gate)
    loop, world, repo, router, _ = _make_loop(provider=provider, agent_count=2)
    old_run = loop._run_id
    old_agent_ids = set(world.agents)

    loop.start()
    for _ in range(200):  # let the background task enter the hung chat()
        await asyncio.sleep(0.005)
        if provider.calls >= 1:
            break
    assert provider.calls == 1, "turn never reached the (gated) LLM call"
    old_task = loop._task
    assert old_task is not None and not old_task.done()

    # Stale cache entries from the "previous run" (B12).
    router._cache["stale-key"] = "stale-decision"

    cfg = WorldConfig(
        world=_make_params(),
        places=[PlaceConfig(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentConfig(name="Zed", personality="", profile="mock",
                            location="plaza")],
    )
    await loop.reset(cfg)

    # B2: the cancelled tick task was AWAITED — fully finished by now.
    assert old_task.done(), "reset returned while the old tick task still ran"
    assert loop._task is None
    # B12: decision cache flushed.
    assert len(router._cache) == 0, "router cache survived reset (audit B12)"
    # Fresh world.
    assert world.tick == 0
    assert set(world.agents) != old_agent_ids
    new_run = loop._run_id
    assert new_run != old_run

    # Release the hung call: the dead turn must not touch the new world/run.
    baseline_rows = len(repo.get_events(new_run))
    gate.set()
    await asyncio.sleep(0.05)
    assert world.tick == 0, "old in-flight turn advanced the NEW world's tick"
    assert len(repo.get_events(new_run)) == baseline_rows, (
        "old in-flight turn wrote events into the new run"
    )
    assert provider.calls == 1, "cancelled turn retried after reset"


# ──────────────────────────────────────────────────────────────────────────────
# 10. EM-071 end-to-end — DELETE /api/agents god-kill through the real app
# ──────────────────────────────────────────────────────────────────────────────

def test_delete_last_agent_via_api_emits_world_extinct_and_pauses():
    """End-to-end on the real FastAPI app: god-killing every agent through
    DELETE /api/agents/{id} emits exactly one world_extinct and pauses."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # Determinism: kill the chaos layer (test_api_routes.py idiom).
        if appmod._world is not None:
            appmod._world.params.animals.enabled = False
            appmod._world.animals.clear()

        state = client.get("/api/state").json()
        agent_ids = [a["id"] for a in state["agents"] if a.get("alive", True)]
        assert agent_ids

        for aid in agent_ids:
            resp = client.delete(f"/api/agents/{aid}")
            assert resp.status_code == 200, resp.text

        run_id = appmod._loop._run_id
        rows = appmod._repo.get_events(run_id, kinds=["world_extinct"])
        assert len(rows) == 1, f"expected one world_extinct, got {len(rows)}"
        assert rows[0]["payload"]["last_agent_id"] == agent_ids[-1]
        assert rows[0]["payload"]["auto_paused"] is True
        assert appmod._loop.is_running() is False
        assert client.get("/api/state").json()["running"] is False

        # Deleting an (already dead) agent again never re-emits.
        client.delete(f"/api/agents/{agent_ids[-1]}")
        assert len(appmod._repo.get_events(run_id, kinds=["world_extinct"])) == 1

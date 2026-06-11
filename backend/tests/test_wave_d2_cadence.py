"""
Wave D2 / B2 gate tests — cadence tiers (EM-158), salience-gated background
turns (EM-159), the spontaneity floor (EM-160), and observability (EM-166).

Contract under test: contracts/wave-d2.md §B2.
  - AgentState.cadence_tier (additive, default protagonist — ZERO behavior
    change until assigned), settable via world.yaml agent entries, the spawn
    body, and POST /api/agents/{id}/tier; serialized in snapshots.
  - Scheduler: protagonists every round, supporting every 3rd, background
    every 10th; due-set rotation stays sorted-id within a round; round counter
    derives from world state and survives snapshot/restore.
  - EM-159 (BACKGROUND ONLY): a due turn consults the LLM iff salient since
    the agent's last LLM turn — new co-located agent/animal, witnessed
    importance>0, energy band crossing, pending whisper/proclamation/board
    note, an uncast open vote. Non-salient ⇒ the deterministic seeded reflex
    routine (starving⇒recharge, at-work⇒work, else forage/move-home) with
    ZERO router calls and payload.reflex: true.
  - EM-160 (inseparable): seeded spontaneity_chance wildcard (default 0.15) +
    reflex_streak_limit forced reassess (default 8), under world.cadence.
  - EM-166: turn events carry cadence_tier; world_state agents gain
    cadence_tier + reflex_streak; reflex turns emit NO llm_call rows.

FREE-SCALE PROOF (the W11b prompt-capture/call-count idiom): the scripted
provider records every chat() call, so "zero router calls" is asserted as
len(provider.prompts) not growing across a non-salient background turn.

Deterministic and offline (scripted fakes, ':memory:' DBs, no network).
House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

import asyncio
import json

import pytest
import yaml

from petridish.engine.world import World, AgentState, PlaceState, RuleState
from petridish.config.loader import (
    AgentConfig, CadenceParams, EMBEDDED_WORLD_YAML, ModelProfile, WorldConfig,
    WorldParams, _parse_world,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


# ──────────────────────────────────────────────────────────────────────────────
# Harness (the test_w11b ByAgentProvider idiom: per-agent scripts + prompt
# capture — provider.prompts IS the router call count for the free-scale proof)
# ──────────────────────────────────────────────────────────────────────────────

IDLE = {"action": "idle", "args": {}}


class ByAgentProvider:
    """Scripted provider with PER-AGENT action lists and prompt capture.
    Every chat() call records (agent_id, system_prompt); the call count is the
    zero-router-calls proof surface."""
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list] | None = None):
        self._scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []  # (agent_id, system content)

    def set_world(self, world: object) -> None:  # router.inject_world seam
        self._world = world

    @staticmethod
    def _extract(messages: list[dict]) -> tuple[str, str]:
        agent_id, system = "unknown", ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                for line in system.split("\n"):
                    line = line.strip()
                    if line.startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
        return agent_id, system

    async def chat(self, messages, *, max_tokens, temperature):
        agent_id, system = self._extract(messages)
        self.prompts.append((agent_id, system))
        script = None
        for key, entries in self._scripts.items():
            if key in agent_id:
                script = entries
                break
        if script is None:
            script = [IDLE]
        i = min(self._pos.get(agent_id, 0), len(script) - 1)
        self._pos[agent_id] = i + 1
        entry = script[i]
        if callable(entry):
            entry = entry(agent_id, 0)
        return json.dumps(entry)


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
        # Default the wildcard OFF in tests that need exact reflex counts;
        # individual tests re-enable it explicitly.
        cadence=CadenceParams(spontaneity_chance=0.0, reflex_streak_limit=999),
    )
    base.update(overrides)
    return WorldParams(**base)


def _default_places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="townhall", name="Town Hall", x=0, y=10, kind="governance"),
        PlaceState(id="shack", name="The Shack", x=10, y=10, kind="home"),
    ]


def _agent(aid: str, name: str, location: str = "plaza", tier: str = "protagonist",
           energy: float = 80.0, credits: int = 20) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=energy, credits=credits,
                      cadence_tier=tier)


def _make(agents: list[AgentState], params: WorldParams | None = None,
          scripts: dict[str, list] | None = None,
          places: list[PlaceState] | None = None):
    params = params or _params()
    world = World(params=params, places=places or _default_places(), agents=agents)
    provider = ByAgentProvider(scripts)
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    router = Router(profiles, adapter_overrides={"mock": provider},
                    cache_enabled=False)
    for a in agents:
        router.reassign(a.id, a.profile)
    repo = SQLiteRepository(":memory:")
    runtime = AgentRuntime(world, router)
    router.inject_world(world)
    broadcast: list[dict] = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: broadcast.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    return loop, world, repo, runtime, provider, broadcast


def _turn(loop: TickLoop, world: World, agent: AgentState) -> None:
    """Execute ONE turn for `agent` through the real loop path (the agent is
    treated as due — scheduling itself is tested separately)."""
    asyncio.run(loop._execute_turn(agent))


# ──────────────────────────────────────────────────────────────────────────────
# 1. EM-158 — tier scheduling cadence math (due sets across 30 rounds)
# ──────────────────────────────────────────────────────────────────────────────

def test_tier_cadence_due_sets_across_30_rounds():
    agents = [
        _agent("agent_a", "A"),                          # protagonist
        _agent("agent_b", "B", tier="supporting"),
        _agent("agent_c", "C", tier="background"),
    ]
    world = World(params=_params(), places=_default_places(), agents=agents)
    by_round: dict[int, list[str]] = {}
    while world.round < 31:
        a = world.next_agent()
        assert a is not None
        if world.round > 30:
            break
        by_round.setdefault(world.round, []).append(a.id)

    for r in range(1, 31):
        due = by_round[r]
        expected = ["agent_a"]
        if r % 3 == 0:
            expected.append("agent_b")
        if r % 10 == 0:
            expected.append("agent_c")
        assert due == sorted(expected), f"round {r}: {due} != {sorted(expected)}"

    # Cadence ratios over 30 rounds: 30 / 10 / 3 turns.
    flat = [aid for r in range(1, 31) for aid in by_round[r]]
    assert flat.count("agent_a") == 30
    assert flat.count("agent_b") == 10
    assert flat.count("agent_c") == 3


def test_default_protagonist_scheduling_unchanged():
    """Untiered (default) agents schedule EXACTLY as the pre-D2 round-robin:
    full sorted-id rotation, one round per cycle."""
    agents = [_agent("agent_b", "B"), _agent("agent_a", "A"), _agent("agent_c", "C")]
    world = World(params=_params(), places=_default_places(), agents=agents)
    seq = [world.next_agent().id for _ in range(9)]
    assert seq == ["agent_a", "agent_b", "agent_c"] * 3
    assert world.round == 3


def test_all_background_world_never_stalls():
    """A world with zero protagonists skips empty rounds (applying per-round
    effects for each) instead of looping forever."""
    agents = [_agent("agent_z", "Z", tier="background")]
    world = World(params=_params(), places=_default_places(), agents=agents)
    a = world.next_agent()
    assert a is not None and a.id == "agent_z"
    assert world.round == 10  # rounds 1-9 had no due tier and were skipped
    a = world.next_agent()
    assert a.id == "agent_z" and world.round == 20


def test_spawned_background_agent_waits_for_its_due_round():
    agents = [_agent("agent_a", "A")]
    world = World(params=_params(), places=_default_places(), agents=agents)
    world.next_agent()  # round 1: agent_a
    spawned = world.spawn_agent("Newbie", "", "mock", "plaza",
                                cadence_tier="background")
    assert spawned.cadence_tier == "background"
    by_round: dict[int, list[str]] = {1: ["agent_a"]}
    while world.round < 11:
        a = world.next_agent()
        if world.round > 10:
            break
        by_round.setdefault(world.round, []).append(a.id)
    for r in range(2, 10):
        assert spawned.id not in by_round[r]  # not due in rounds 2-9
    # Round 10: both due, sorted-id.
    assert by_round[10] == sorted(["agent_a", spawned.id])


def test_spawn_agent_unknown_tier_falls_back_to_protagonist():
    world = World(params=_params(), places=_default_places(),
                  agents=[_agent("agent_a", "A")])
    spawned = world.spawn_agent("Odd", "", "mock", "plaza", cadence_tier="bogus")
    assert spawned.cadence_tier == "protagonist"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Snapshot round-trip — tier / streak / round counters (EM-158/160)
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_round_trip_tier_streak_and_round_counters():
    agents = [
        _agent("agent_a", "A"),
        _agent("agent_b", "B", tier="supporting"),
        _agent("agent_c", "C", tier="background"),
    ]
    world = World(params=_params(), places=_default_places(), agents=agents)
    for _ in range(7):  # advance mid-schedule
        world.next_agent()
    world.agents["agent_c"].reflex_streak = 5

    snap = world.to_snapshot()
    # EM-166 — world_state agents carry the additive observability keys.
    by_id = {a["id"]: a for a in snap["agents"]}
    assert by_id["agent_b"]["cadence_tier"] == "supporting"
    assert by_id["agent_c"]["cadence_tier"] == "background"
    assert by_id["agent_c"]["reflex_streak"] == 5
    assert by_id["agent_a"]["cadence_tier"] == "protagonist"

    restored = World.from_snapshot(snap, params=_params())
    assert restored.round == world.round
    assert restored.agents["agent_b"].cadence_tier == "supporting"
    assert restored.agents["agent_c"].cadence_tier == "background"
    assert restored.agents["agent_c"].reflex_streak == 5

    # The restored world continues the SAME schedule as the original.
    original_seq = [world.next_agent().id for _ in range(40)]
    restored_seq = [restored.next_agent().id for _ in range(40)]
    assert original_seq == restored_seq


def test_pre_d2_snapshot_restores_protagonist_defaults():
    """A snapshot WITHOUT the additive keys (pre-D2) restores protagonist /
    zero-streak — old snapshots stay valid by contract."""
    world = World(params=_params(), places=_default_places(),
                  agents=[_agent("agent_a", "A")])
    snap = world.to_snapshot()
    for a in snap["agents"]:
        a.pop("cadence_tier", None)
        a.pop("reflex_streak", None)
    restored = World.from_snapshot(snap, params=_params())
    assert restored.agents["agent_a"].cadence_tier == "protagonist"
    assert restored.agents["agent_a"].reflex_streak == 0


# ──────────────────────────────────────────────────────────────────────────────
# 3. EM-159 — the salience triggers, each one
# ──────────────────────────────────────────────────────────────────────────────

def _baselined_bg(location: str = "shack"):
    """A background agent with recorded salience baselines (its 'first_turn'
    LLM turn already happened) plus a co-located-elsewhere protagonist."""
    bg = _agent("agent_bg", "Bg", location=location, tier="background")
    other = _agent("agent_other", "Other", location="market")
    loop, world, repo, runtime, provider, _ = _make([bg, other])
    runtime._note_llm_turn(bg)
    salient, triggers = runtime._background_salience(bg)
    assert not salient, f"expected a quiet baseline, got {triggers}"
    return loop, world, runtime, provider, bg, other


def test_salience_first_turn_no_baseline():
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    loop, world, repo, runtime, provider, _ = _make([bg])
    salient, triggers = runtime._background_salience(bg)
    assert salient and triggers == ["first_turn"]


def test_salience_new_colocated_agent():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    other.location = bg.location  # someone walked in
    salient, triggers = runtime._background_salience(bg)
    assert salient and "new_colocated" in triggers


def test_salience_new_colocated_animal():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    world.spawn_animal("cat", "Mochi", bg.location)
    salient, triggers = runtime._background_salience(bg)
    assert salient and "new_colocated" in triggers


def test_salience_witnessed_importance():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    runtime.push_event({
        "kind": "conflict", "actor_id": bg.id, "tick": world.tick,
        "text": "someone attacks Bg!", "payload": {},
    })
    salient, triggers = runtime._background_salience(bg)
    assert salient and "witnessed_importance" in triggers
    # ...and a fresh LLM turn clears it.
    runtime._note_llm_turn(bg)
    salient, _ = runtime._background_salience(bg)
    assert not salient


def test_salience_energy_band_crossing():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    bg.energy = 30.0  # band 3 (80) -> band 1 (30)
    salient, triggers = runtime._background_salience(bg)
    assert salient and "energy_band" in triggers
    # Movement WITHIN the band is NOT salient.
    runtime._note_llm_turn(bg)
    bg.energy = 28.0
    salient, _ = runtime._background_salience(bg)
    assert not salient


def test_salience_pending_whisper():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    world.post_whisper_as_god(bg.id, "psst — the market hides a secret")
    salient, triggers = runtime._background_salience(bg)
    assert salient and "pending_whisper" in triggers


def test_salience_proclamation():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    world.tick += 1
    world.post_proclamation_as_god("Hear ye: taxes are doubled")
    salient, triggers = runtime._background_salience(bg)
    assert salient and "proclamation" in triggers


def test_salience_unseen_god_board_note():
    # The agent must stand at a billboard place (plaza) — baselined there alone.
    bg = _agent("agent_bg", "Bg", location="plaza", tier="background")
    loop, world, repo, runtime, provider, _ = _make([bg])
    runtime._note_llm_turn(bg)
    assert not runtime._background_salience(bg)[0]
    world.tick += 1
    world.post_billboard_as_god("the watchers demand a clocktower")
    salient, triggers = runtime._background_salience(bg)
    assert salient and "board_note" in triggers


def test_salience_uncast_active_vote():
    loop, world, runtime, provider, bg, other = _baselined_bg()
    world.rules["r1"] = RuleState(id="r1", effect="ubi", text="UBI for all",
                                  proposer_id=other.id)
    salient, triggers = runtime._background_salience(bg)
    assert salient and "uncast_vote" in triggers
    # Once the agent HAS voted, the trigger clears.
    world.rules["r1"].votes[bg.id] = True
    salient, triggers = runtime._background_salience(bg)
    assert "uncast_vote" not in triggers


def test_salient_background_turn_consults_llm_with_trigger_payload():
    """Integration: a salient due turn takes a FULL LLM turn and the domain
    event payload names the triggers (EM-166)."""
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    loop, world, repo, runtime, provider, _ = _make(
        [bg], scripts={"agent_bg": [{"action": "say", "args": {"text": "hello"}}]})
    runtime._note_llm_turn(bg)
    world.post_whisper_as_god(bg.id, "wake up")
    calls_before = len(provider.prompts)
    _turn(loop, world, bg)
    assert len(provider.prompts) == calls_before + 1  # the LLM ran
    rows = repo.get_events(loop._run_id or 1, kinds=["agent_speech"], order="asc")
    assert rows, "expected the speech event"
    payload = rows[-1]["payload"]
    assert payload["cadence_reason"] == "salient"
    assert "pending_whisper" in payload["salience_triggers"]
    assert payload["cadence_tier"] == "background"
    assert bg.reflex_streak == 0


# ──────────────────────────────────────────────────────────────────────────────
# 4. EM-159 — non-salient due turn ⇒ reflex, ZERO router calls (free-scale proof)
# ──────────────────────────────────────────────────────────────────────────────

def test_non_salient_background_turn_makes_zero_router_calls():
    """THE free-scale proof (W11b call-count idiom): after the first_turn
    baseline, a quiet background agent's due turns consult the router ZERO
    times, resolve the reflex routine, mark payload.reflex, and emit NO
    llm_call rows."""
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    loop, world, repo, runtime, provider, _ = _make([bg])

    _turn(loop, world, bg)                       # first_turn ⇒ one LLM call
    assert len(provider.prompts) == 1

    for _ in range(3):                           # quiet due turns ⇒ reflex
        _turn(loop, world, bg)
    assert len(provider.prompts) == 1, "reflex turns must make ZERO router calls"
    assert bg.reflex_streak == 3

    run_id = loop._run_id or 1
    # Reflex domain events: normal kinds, payload.reflex true, tier stamped.
    rows = repo.get_events(run_id, kinds=["economy"], order="asc")
    reflex_rows = [r for r in rows if r["payload"].get("reflex") is True]
    assert len(reflex_rows) == 3
    for r in reflex_rows:
        assert r["payload"]["cadence_tier"] == "background"
        assert r["payload"]["reflex_streak"] >= 1
    # ZERO llm_call rows after the baseline turn's tick (EM-166: an empty span
    # would pollute usage accounting and the call-count proof).
    llm_rows = repo.get_events(run_id, kinds=["llm_call"], from_tick=1, order="asc")
    assert llm_rows == []
    # The rest of the trace chain keeps its shape on reflex turns.
    chosen = repo.get_events(run_id, kinds=["action_chosen"], from_tick=1, order="asc")
    assert len(chosen) == 3
    assert all(c["payload"]["tier"] == "reflex" for c in chosen)


def test_protagonist_and_supporting_are_never_salience_gated():
    """EM-159 is BACKGROUND ONLY: quiet protagonists/supporting agents still
    take full LLM turns every due turn."""
    pro = _agent("agent_pro", "Pro", location="shack")
    sup = _agent("agent_sup", "Sup", location="market", tier="supporting")
    loop, world, repo, runtime, provider, _ = _make([pro, sup])
    for _ in range(2):
        _turn(loop, world, pro)
        _turn(loop, world, sup)
    assert len(provider.prompts) == 4  # every turn consulted the router
    assert pro.reflex_streak == 0 and sup.reflex_streak == 0


# ──────────────────────────────────────────────────────────────────────────────
# 5. The reflex routine — deterministic, seeded
# ──────────────────────────────────────────────────────────────────────────────

def test_reflex_starving_picks_recharge():
    bg = _agent("agent_bg", "Bg", location="plaza", tier="background",
                energy=10.0, credits=20)
    _, world, _, runtime, _, _ = _make([bg])
    assert runtime._reflex_pick(bg) == {"action": "recharge", "args": {}}


def test_reflex_starving_without_credits_falls_through():
    bg = _agent("agent_bg", "Bg", location="market", tier="background",
                energy=10.0, credits=0)
    _, world, _, runtime, _, _ = _make([bg])
    # Can't afford the recharge ⇒ the at-work branch wins instead.
    assert runtime._reflex_pick(bg) == {"action": "work", "args": {}}


def test_reflex_at_work_place_picks_work():
    bg = _agent("agent_bg", "Bg", location="market", tier="background")
    _, world, _, runtime, _, _ = _make([bg])
    assert runtime._reflex_pick(bg) == {"action": "work", "args": {}}


def test_reflex_rotation_forage_and_move_home_seeded():
    bg = _agent("agent_bg", "Bg", location="plaza", tier="background")
    _, world, _, runtime, _, _ = _make([bg])
    picks = []
    for tick in range(20):
        world.tick = tick
        picks.append(runtime._reflex_pick(bg))
    actions = {p["action"] for p in picks}
    assert actions == {"forage", "move_to"}, "the rotation must mix both"
    for p in picks:
        if p["action"] == "move_to":
            assert world.places[p["args"]["place"]].kind == "home"
    # Deterministic: the same world state always picks the same action.
    world.tick = 7
    assert runtime._reflex_pick(bg) == runtime._reflex_pick(bg)


def test_reflex_at_home_never_moves_home():
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    _, world, _, runtime, _, _ = _make([bg])
    for tick in range(10):
        world.tick = tick
        assert runtime._reflex_pick(bg) == {"action": "forage", "args": {}}


# ──────────────────────────────────────────────────────────────────────────────
# 6. EM-160 — the spontaneity floor (wildcard + streak limit), seeded
# ──────────────────────────────────────────────────────────────────────────────

def test_wildcard_forces_full_llm_turn():
    """spontaneity_chance=1.0 ⇒ EVERY non-salient due turn is a full LLM turn
    tagged cadence_reason: wildcard."""
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    params = _params(cadence=CadenceParams(spontaneity_chance=1.0,
                                           reflex_streak_limit=999))
    loop, world, repo, runtime, provider, _ = _make([bg], params=params)
    _turn(loop, world, bg)                       # first_turn (salient)
    _turn(loop, world, bg)                       # wildcard fires
    assert len(provider.prompts) == 2
    rows = repo.get_events(loop._run_id or 1, kinds=["agent_action"], order="asc")
    wildcards = [r for r in rows if r["payload"].get("cadence_reason") == "wildcard"]
    assert wildcards, "the wildcard turn must be tagged in the payload"
    assert bg.reflex_streak == 0


def test_reflex_streak_limit_forces_reassess_turn():
    """reflex_streak_limit=2 ⇒ after two consecutive reflex turns the third
    due turn is a forced LLM reassess; the streak resets."""
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    params = _params(cadence=CadenceParams(spontaneity_chance=0.0,
                                           reflex_streak_limit=2))
    loop, world, repo, runtime, provider, _ = _make([bg], params=params)
    _turn(loop, world, bg)                       # first_turn ⇒ LLM (streak 0)
    _turn(loop, world, bg)                       # reflex (streak 1)
    _turn(loop, world, bg)                       # reflex (streak 2)
    assert len(provider.prompts) == 1 and bg.reflex_streak == 2
    _turn(loop, world, bg)                       # streak hit the limit ⇒ LLM
    assert len(provider.prompts) == 2, "the floor must force a reassess turn"
    assert bg.reflex_streak == 0
    rows = repo.get_events(loop._run_id or 1, kinds=["agent_action"], order="asc")
    assert any(r["payload"].get("cadence_reason") == "reassess" for r in rows)


def test_spontaneity_roll_is_seeded_and_deterministic():
    """The wildcard derives from world state (agent id + tick hash) — never
    the random module — so identical states roll identically."""
    bg = _agent("agent_bg", "Bg", location="shack", tier="background")
    params = _params(cadence=CadenceParams(spontaneity_chance=0.15,
                                           reflex_streak_limit=999))
    _, world1, _, runtime1, _, _ = _make([bg], params=params)
    bg2 = _agent("agent_bg", "Bg", location="shack", tier="background")
    _, world2, _, runtime2, _, _ = _make([bg2], params=params)
    rolls1 = []
    rolls2 = []
    for tick in range(60):
        world1.tick = tick
        world2.tick = tick
        rolls1.append(runtime1._spontaneity_roll(bg))
        rolls2.append(runtime2._spontaneity_roll(bg2))
    assert rolls1 == rolls2, "seeded rolls must be reproducible across runs"
    assert any(rolls1) and not all(rolls1), \
        "chance 0.15 over 60 ticks should fire sometimes, not always"


# ──────────────────────────────────────────────────────────────────────────────
# 7. EM-166 — observability: events carry cadence_tier; turn_start carries
#    tier + streak; protagonists unchanged
# ──────────────────────────────────────────────────────────────────────────────

def test_turn_events_carry_cadence_tier():
    pro = _agent("agent_pro", "Pro", location="plaza")
    loop, world, repo, runtime, provider, _ = _make(
        [pro], scripts={"agent_pro": [{"action": "forage", "args": {}}]})
    _turn(loop, world, pro)
    run_id = loop._run_id or 1
    starts = repo.get_events(run_id, kinds=["turn_start"], order="asc")
    assert starts[-1]["payload"]["cadence_tier"] == "protagonist"
    assert starts[-1]["payload"]["reflex_streak"] == 0
    domain = repo.get_events(run_id, kinds=["economy"], order="asc")
    assert domain[-1]["payload"]["cadence_tier"] == "protagonist"
    assert "reflex" not in domain[-1]["payload"]
    resolved = repo.get_events(run_id, kinds=["action_resolved"], order="asc")
    assert resolved[-1]["payload"]["cadence_tier"] == "protagonist"
    # And the LLM ran exactly once — protagonists keep full turns.
    llm = repo.get_events(run_id, kinds=["llm_call"], order="asc")
    assert len(llm) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 8. Config plumbing — world.yaml agent entries + the world.cadence block
# ──────────────────────────────────────────────────────────────────────────────

def test_parse_world_agent_cadence_tier_and_cadence_block():
    raw = {
        "world": {"cadence": {"spontaneity_chance": 0.5, "reflex_streak_limit": 3}},
        "places": [{"id": "plaza", "name": "Plaza", "x": 0, "y": 0, "kind": "social"}],
        "agents": [
            {"name": "Zed", "profile": "mock", "cadence_tier": "background"},
            {"name": "Sue", "profile": "mock", "cadence_tier": "supporting"},
            {"name": "Pat", "profile": "mock"},
            {"name": "Bad", "profile": "mock", "cadence_tier": "bogus"},
        ],
    }
    params, places, agents = _parse_world(raw)
    assert params.cadence.spontaneity_chance == 0.5
    assert params.cadence.reflex_streak_limit == 3
    tiers = {a.name: a.cadence_tier for a in agents}
    assert tiers == {"Zed": "background", "Sue": "supporting",
                     "Pat": "protagonist", "Bad": "protagonist"}


def test_cadence_block_defaults_and_clamps():
    params, _, _ = _parse_world({"world": {}, "places": [], "agents": []})
    assert params.cadence.spontaneity_chance == pytest.approx(0.15)
    assert params.cadence.reflex_streak_limit == 8
    params, _, _ = _parse_world({
        "world": {"cadence": {"spontaneity_chance": 7, "reflex_streak_limit": 0}},
        "places": [], "agents": [],
    })
    assert params.cadence.spontaneity_chance == 1.0   # clamped to 0..1
    assert params.cadence.reflex_streak_limit == 1    # clamped to >= 1


def test_embedded_world_yaml_mirror_carries_the_cadence_block():
    raw = yaml.safe_load(EMBEDDED_WORLD_YAML)
    params, _, _ = _parse_world(raw)
    assert params.cadence.spontaneity_chance == pytest.approx(0.15)
    assert params.cadence.reflex_streak_limit == 8


# ──────────────────────────────────────────────────────────────────────────────
# 9. API — POST /api/agents/{id}/tier + the spawn body field
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """TestClient over the real app (the test_api_routes idiom); the chaos
    animal layer is disabled for determinism."""
    import sys
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    _appmod = sys.modules["petridish.api.app"]
    with TestClient(app, raise_server_exceptions=True) as c:
        if _appmod._world is not None:
            _appmod._world.params.animals.enabled = False
            _appmod._world.animals.clear()
        yield c


def _state_agents(client) -> dict:
    return {a["id"]: a for a in client.get("/api/state").json()["agents"]}


def test_api_tier_endpoint_sets_tier_and_broadcasts(client):
    agent_id = next(iter(_state_agents(client)))
    resp = client.post(f"/api/agents/{agent_id}/tier", json={"tier": "background"})
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "agent_id": agent_id,
                           "cadence_tier": "background"}
    assert _state_agents(client)[agent_id]["cadence_tier"] == "background"
    # Back to protagonist so other tests see the default cast.
    resp = client.post(f"/api/agents/{agent_id}/tier", json={"tier": "protagonist"})
    assert resp.status_code == 200
    assert _state_agents(client)[agent_id]["cadence_tier"] == "protagonist"


def test_api_tier_endpoint_rejects_unknown_tier_and_agent(client):
    agent_id = next(iter(_state_agents(client)))
    assert client.post(f"/api/agents/{agent_id}/tier",
                       json={"tier": "narrator"}).status_code == 400
    assert client.post("/api/agents/agent_nobody/tier",
                       json={"tier": "background"}).status_code == 404


def test_api_spawn_accepts_cadence_tier(client):
    resp = client.post("/api/agents", json={
        "name": "Drift", "profile": "mock", "personality": "quiet",
        "location": "plaza", "mode": "god", "cadence_tier": "background",
    })
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]
    assert _state_agents(client)[agent_id]["cadence_tier"] == "background"
    # world_state also surfaces the EM-166 streak key.
    assert _state_agents(client)[agent_id]["reflex_streak"] == 0


def test_api_spawn_rejects_unknown_cadence_tier(client):
    resp = client.post("/api/agents", json={
        "name": "Nope", "profile": "mock", "personality": "x",
        "location": "plaza", "mode": "god", "cadence_tier": "headliner",
    })
    assert resp.status_code == 400


def test_api_spawn_without_tier_defaults_to_protagonist(client):
    resp = client.post("/api/agents", json={
        "name": "Plain", "profile": "mock", "personality": "x",
        "location": "plaza", "mode": "god",
    })
    assert resp.status_code == 201
    agent_id = resp.json()["agent_id"]
    assert _state_agents(client)[agent_id]["cadence_tier"] == "protagonist"

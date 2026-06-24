"""
W11b gate tests — "sim texture": commitments (EM-079), reflection (EM-080),
overhearing (EM-081), law renewal (EM-087) + commemorative monuments (EM-103),
EM-100 readable rule text, the billboard (EM-091), procgen town (EM-098),
real blackout (EM-083 engine half) + usage alerts (EM-083 platform half),
World.from_snapshot + POST /api/runs/fork (EM-101), and personas (EM-092).

Contracts under test:
  - event-log.md v1.3.0 — new kinds billboard_posted / reflection /
    commitment_made / commitment_lapsed{reason:"phantom"} / usage_alert; rule_*
    feed text leads with the rule's quoted text + effect (never the bare uuid);
    overhearing adds NO kinds and NO calls (perceived payload only); blackout
    is real (recharge disabled, structure_state_changed); fork lineage.
  - api.openapi.yaml v1.4.0 — POST /api/runs/fork (snapshot-grain with the
    honest forked_at_tick + note; 404/400 paths), GET /api/personas, POST
    /api/agents persona prefill (explicit wins; missing name/profile → 400,
    the accepted W11b deviation), POST /api/billboard (201/422), RunRow
    forked_from/forked_at_tick.
  - coordination/W11B_BUILD.md — free-scale law: none of these adds a standing
    LLM call (everything rides the single turn response / context injection).

Deterministic and offline (MockProvider-style scripted fakes, ':memory:' DBs,
no network, no real API keys); conftest pins EM_DB_PATH=':memory:'. Harness
idioms follow test_w9 / test_w10 / test_w11a.
"""
from __future__ import annotations

import asyncio
import json
import sys

import pytest

from petridish.engine.world import (
    World, AgentState, Building, PlaceState, RelationshipState, RuleState,
    generate_procgen_places,
)
from petridish.config.loader import (
    CommitmentParams, ModelProfile, ProcgenParams, ReflectionParams,
    WorldConfig, WorldParams, load_personas,
)
from petridish.agents.runtime import AgentRuntime
from petridish.engine.loop import TickLoop
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router
from petridish.providers.usage import UsageAlertTracker


# ──────────────────────────────────────────────────────────────────────────────
# Harness (test_w11a idiom, extended with per-agent scripts + prompt capture)
# ──────────────────────────────────────────────────────────────────────────────

class ByAgentProvider:
    """Scripted provider with PER-AGENT action lists and prompt capture.

    Script entries are action dicts or callables `(agent_id, tick) -> dict`
    (the MockProvider idiom — lets a vote read the live rule id). Each agent
    consumes its list sequentially; the last entry repeats once exhausted.
    Every chat() call records (agent_id, system_prompt) so tests can assert
    what context the model actually saw (commitment block, overheard block,
    reflection request) — the EM-079/080/081 prompt seams.
    """
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list]):
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []  # (agent_id, system content)

    def set_world(self, world: object) -> None:  # router.inject_world seam
        self._world = world

    @staticmethod
    def _extract(messages: list[dict]) -> tuple[str, int, str]:
        agent_id, tick, system = "unknown", 0, ""
        for m in messages:
            if m.get("role") == "system":
                system = m.get("content", "")
                for line in system.split("\n"):
                    line = line.strip()
                    if line.startswith("Agent ID:"):
                        agent_id = line.split(":", 1)[1].strip()
                    elif line.startswith("Tick:"):
                        try:
                            tick = int(line.split(":", 1)[1].strip())
                        except ValueError:
                            pass
        return agent_id, tick, system

    async def chat(self, messages, *, max_tokens, temperature):
        agent_id, tick, system = self._extract(messages)
        self.prompts.append((agent_id, system))
        script = None
        for key, entries in self._scripts.items():
            if key in agent_id:
                script = entries
                break
        if script is None:
            script = [{"action": "idle", "args": {}}]
        i = min(self._pos.get(agent_id, 0), len(script) - 1)
        self._pos[agent_id] = i + 1
        entry = script[i]
        if callable(entry):
            entry = entry(agent_id, tick)
        return json.dumps(entry)


def _params(**overrides) -> WorldParams:
    base = dict(
        tick_interval_seconds=0.5,
        turns_per_day=999,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
        snapshot_interval_ticks=100,
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


def _agent(aid: str, name: str, location: str = "plaza",
           energy: float = 80.0, credits: int = 20) -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=energy, credits=credits)


def _make_loop(params: WorldParams, agents: list[AgentState],
               scripts: dict[str, list],
               places: list[PlaceState] | None = None):
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
    return loop, world, repo, runtime, provider


async def _drive(loop: TickLoop, world: World, n: int) -> None:
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)
        if loop._animal_task is not None:
            await loop._animal_task
        if getattr(loop, "_narrator_task", None) is not None:
            await loop._narrator_task


IDLE = {"action": "idle", "args": {}}


def _vote_yes(world: World):
    """Callable script entry: vote YES on the first proposed rule (else idle)."""
    def entry(agent_id: str, tick: int) -> dict:
        proposed = [r for r in world.rules.values() if r.status == "proposed"]
        if proposed:
            return {"action": "vote",
                    "args": {"rule_id": proposed[0].id, "choice": True}}
        return dict(IDLE)
    return entry


def _vote_no(world: World):
    def entry(agent_id: str, tick: int) -> dict:
        proposed = [r for r in world.rules.values() if r.status == "proposed"]
        if proposed:
            return {"action": "vote",
                    "args": {"rule_id": proposed[0].id, "choice": False}}
        return dict(IDLE)
    return entry


# ──────────────────────────────────────────────────────────────────────────────
# 1. Commitments (EM-079) — made → event + prompt block; phantom lapse; kept;
#    cap 5 (oldest evicted silently).
# ──────────────────────────────────────────────────────────────────────────────

def test_commitment_made_emits_event_and_rides_the_next_prompt():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider = _make_loop(
        _params(), [ada],
        {"ada": [
            {"action": "say", "args": {"text": "Soon!"},
             "commitment": "I will build a garden at the commons"},
            dict(IDLE),
        ]},
    )
    asyncio.run(_drive(loop, world, 2))

    made = repo.get_events(loop._run_id, kinds=["commitment_made"])
    assert len(made) == 1
    assert made[0]["actor_id"] == "agent_ada"
    assert made[0]["payload"]["text"] == "I will build a garden at the commons"
    assert made[0]["payload"]["commitment_id"], "commitment_id must be stamped"
    assert "I will build a garden" in made[0]["text"]

    # The SECOND turn's prompt carries the active-commitments block (EM-079).
    turn2_prompt = provider.prompts[1][1]
    assert "YOUR ACTIVE COMMITMENTS" in turn2_prompt
    assert "I will build a garden at the commons" in turn2_prompt
    # And the first turn's prompt did NOT (nothing was committed yet).
    assert "YOUR ACTIVE COMMITMENTS" not in provider.prompts[0][1]


def test_phantom_lapse_after_n_talk_only_turns():
    ada = _agent("agent_ada", "Ada")
    params = _params(commitments=CommitmentParams(phantom_after_turns=3))
    loop, world, repo, runtime, _ = _make_loop(
        _params(commitments=CommitmentParams(phantom_after_turns=3)), [ada],
        {"ada": [
            {"action": "say", "args": {"text": "I promise."},
             "commitment": "I will repair the mill"},
            dict(IDLE),  # talk-only turns age the promise: 1, 2, 3 → lapse
        ]},
    )
    del params
    asyncio.run(_drive(loop, world, 4))

    lapsed = repo.get_events(loop._run_id, kinds=["commitment_lapsed"])
    assert len(lapsed) == 1, "exactly one phantom lapse"
    assert lapsed[0]["payload"]["reason"] == "phantom"
    assert lapsed[0]["payload"]["text"] == "I will repair the mill"
    made = repo.get_events(loop._run_id, kinds=["commitment_made"])
    assert lapsed[0]["payload"]["commitment_id"] == made[0]["payload"]["commitment_id"]
    assert runtime._commitments.get("agent_ada") == [], "lapsed promise is dropped"
    # Lapsed on the 4th turn (3 talk-only turns after the promise), not before.
    assert lapsed[0]["seq"] > made[0]["seq"]


def test_real_tool_call_keeps_the_commitment_silently():
    """A project/economy follow-through KEEPS the oldest commitment — silent
    drop, no commitment_lapsed ever (the kept-promise path emits nothing)."""
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, _ = _make_loop(
        _params(commitments=CommitmentParams(phantom_after_turns=2)), [ada],
        {"ada": [
            {"action": "say", "args": {"text": "watch me"},
             "commitment": "I will forage for the village"},
            {"action": "forage", "args": {}},   # follow-through → kept
            dict(IDLE),                          # then talk-only forever
        ]},
    )
    asyncio.run(_drive(loop, world, 8))

    assert repo.get_events(loop._run_id, kinds=["commitment_lapsed"]) == [], \
        "a kept commitment must never lapse"
    assert runtime._commitments.get("agent_ada") == [], \
        "the kept commitment is dropped silently from the store"


def test_commitments_capped_at_five_oldest_evicted():
    ada = _agent("agent_ada", "Ada")
    script = [
        {"action": "say", "args": {"text": f"promise {i}"},
         "commitment": f"commitment number {i}"}
        for i in range(1, 7)
    ]
    loop, world, repo, runtime, _ = _make_loop(_params(), [ada], {"ada": script})
    asyncio.run(_drive(loop, world, 6))

    made = repo.get_events(loop._run_id, kinds=["commitment_made"])
    assert len(made) == 6, "every commitment is announced"
    active = runtime._commitments["agent_ada"]
    assert len(active) == 5, "cap 5 — the store never grows past max_active"
    assert [c["text"] for c in active] == [
        f"commitment number {i}" for i in range(2, 7)
    ], "the OLDEST commitment is evicted (silently — no lapse event)"
    assert repo.get_events(loop._run_id, kinds=["commitment_lapsed"]) == []


# ──────────────────────────────────────────────────────────────────────────────
# 2. Reflection (EM-080) — importance accumulator trip → same-call reflection
#    field → event + memory + reset; below threshold → no request, no event.
# ──────────────────────────────────────────────────────────────────────────────

def test_reflection_accumulator_trip_emits_event_and_resets():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider = _make_loop(
        _params(reflection=ReflectionParams(importance_threshold=3.0)), [ada],
        {"ada": [
            {"action": "idle", "args": {},
             "reflection": "I have learned to fear the plaza."},
            dict(IDLE),
        ]},
    )
    # A conflict the agent witnessed (actor match) weighs 3.0 → trips 3.0.
    runtime.push_event({"kind": "conflict", "actor_id": "agent_ada",
                        "tick": 0, "text": "Ada is attacked!", "payload": {}})
    assert runtime._importance["agent_ada"] == pytest.approx(3.0)

    asyncio.run(_drive(loop, world, 1))

    # The tripped turn's prompt asked for the reflection IN the same response.
    assert 'ALSO include "reflection"' in provider.prompts[0][1]

    rows = repo.get_events(loop._run_id, kinds=["reflection"])
    assert len(rows) == 1
    assert rows[0]["payload"]["text"] == "I have learned to fear the plaza."
    assert rows[0]["payload"]["importance"] == pytest.approx(3.0)
    assert runtime._importance["agent_ada"] == 0.0, "accumulator resets on emit"
    # The diary entry enters the agent's own memory buffer (loop push_event).
    assert any("I have learned to fear the plaza." in m.get("text", "")
               for m in runtime._memory.get("agent_ada", []))


def test_below_threshold_no_reflection_request_and_no_event():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider = _make_loop(
        _params(reflection=ReflectionParams(importance_threshold=10.0)), [ada],
        {"ada": [dict(IDLE)]},
    )
    asyncio.run(_drive(loop, world, 3))

    assert all('ALSO include "reflection"' not in p for _, p in provider.prompts), \
        "no importance → the prompt must not request a reflection"
    assert repo.get_events(loop._run_id, kinds=["reflection"]) == []


# ──────────────────────────────────────────────────────────────────────────────
# 3. Overhearing (EM-081) — ≤2 lowest-id co-located listeners get the line in
#    their NEXT perceived payload; speaker/whisper-target excluded; pending cap 2.
# ──────────────────────────────────────────────────────────────────────────────

def test_overheard_speech_reaches_two_lowest_id_listeners_only():
    # ids sort aa < ab < ac < zz; aa speaks first (sorted round-robin).
    agents = [_agent("agent_aa", "Aa"), _agent("agent_ab", "Ab"),
              _agent("agent_ac", "Ac"), _agent("agent_zz", "Zz")]
    loop, world, repo, runtime, provider = _make_loop(
        _params(), agents,
        {"aa": [{"action": "say", "args": {"text": "the mill is haunted"}},
                dict(IDLE)],
         "ab": [dict(IDLE)], "ac": [dict(IDLE)], "zz": [dict(IDLE)]},
    )
    asyncio.run(_drive(loop, world, 4))  # aa speaks; ab, ac, zz take turns

    def perceived_of(aid: str) -> dict:
        rows = repo.get_events(loop._run_id, kinds=["perceived"], actor_id=aid)
        assert rows, f"no perceived row for {aid}"
        return rows[0]["payload"]

    for listener in ("agent_ab", "agent_ac"):
        heard = perceived_of(listener).get("overheard_speech")
        assert heard, f"{listener} (a 2-lowest-id listener) must overhear"
        assert heard[0]["speaker_id"] == "agent_aa"
        assert heard[0]["text"] == "the mill is haunted"
        assert heard[0]["overheard"] is True

    # zz is the THIRD co-located listener — over the cap, hears nothing.
    assert "overheard_speech" not in perceived_of("agent_zz")
    # The speaker never overhears itself (next turn's perceived is clean).
    aa_rows = repo.get_events(loop._run_id, kinds=["perceived"],
                              actor_id="agent_aa")
    assert all("overheard_speech" not in r["payload"] for r in aa_rows)

    # The listener's prompt carried the overheard block (context injection).
    ab_prompts = [p for aid, p in provider.prompts if aid == "agent_ab"]
    assert any("OVERHEARD" in p and "the mill is haunted" in p for p in ab_prompts)


def test_whisper_target_is_excluded_from_overhearing():
    agents = [_agent("agent_aa", "Aa"), _agent("agent_ab", "Ab"),
              _agent("agent_ac", "Ac"), _agent("agent_zz", "Zz")]
    loop, world, repo, runtime, _ = _make_loop(
        _params(), agents,
        {"aa": [{"action": "whisper",
                 "args": {"target": "agent_ab", "text": "psst, secret"}},
                dict(IDLE)],
         "ab": [dict(IDLE)], "ac": [dict(IDLE)], "zz": [dict(IDLE)]},
    )
    asyncio.run(_drive(loop, world, 4))

    def perceived_of(aid: str) -> dict:
        rows = repo.get_events(loop._run_id, kinds=["perceived"], actor_id=aid)
        return rows[0]["payload"] if rows else {}

    # The ADDRESSEE heard it directly — not an overhearing.
    assert "overheard_speech" not in perceived_of("agent_ab")
    # The two lowest-id bystanders (ac, zz) overhear the whisper.
    for listener in ("agent_ac", "agent_zz"):
        heard = perceived_of(listener).get("overheard_speech")
        assert heard and heard[0]["text"] == "psst, secret", listener


def test_pending_overheard_lines_cap_at_two_newest():
    agents = [_agent("agent_aa", "Aa"), _agent("agent_zz", "Zz")]
    loop, world, repo, runtime, _ = _make_loop(
        _params(), agents, {"aa": [dict(IDLE)], "zz": [dict(IDLE)]},
    )
    aa = world.agents["agent_aa"]
    for text in ("line one", "line two", "line three"):
        runtime._distribute_overheard(aa, "say", {"text": text})

    pending = runtime._overheard["agent_zz"]
    assert len(pending) == 2, "a listener holds at most 2 pending lines"
    assert [p["text"] for p in pending] == ["line two", "line three"], \
        "newest lines win"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Renewal (EM-087) — identical-active re-propose+pass → renewed:true and
#    exactly ONE active instance ever (the 3×UBI invariant); different effects
#    still stack normally. Plus EM-100 readable rule text.
# ──────────────────────────────────────────────────────────────────────────────

def _gov_agents() -> list[AgentState]:
    return [_agent("agent_ada", "Ada", "townhall"),
            _agent("agent_bob", "Bob", "townhall")]


def test_identical_active_effect_renews_never_stacks():
    agents = _gov_agents()
    propose_ubi = {"action": "propose_rule",
                   "args": {"effect": "ubi",
                            "text": "Everyone deserves a basic income"}}
    world_holder: list[World] = []

    def vote_yes(agent_id, tick):
        w = world_holder[0]
        proposed = [r for r in w.rules.values() if r.status == "proposed"]
        if proposed:
            return {"action": "vote",
                    "args": {"rule_id": proposed[0].id, "choice": True}}
        return dict(IDLE)

    loop, world, repo, _, _ = _make_loop(
        _params(), agents,
        {"ada": [propose_ubi, vote_yes, dict(propose_ubi), vote_yes, dict(IDLE)],
         "bob": [vote_yes, dict(IDLE), vote_yes, dict(IDLE)]},
    )
    world_holder.append(world)
    # T0 ada proposes; T1 bob YES; T2 ada YES → ACTIVE. T3 bob idle.
    # T4 ada re-proposes the identical effect; T5 bob YES; T6 ada YES → RENEWED.
    asyncio.run(_drive(loop, world, 7))

    # THE invariant: never two simultaneously-active identical effects.
    active_ubi = [r for r in world.rules.values()
                  if r.effect == "ubi" and r.status == "active"]
    assert len(active_ubi) == 1, "the 3×UBI bug: identical effects must not stack"
    original = active_ubi[0]
    renewal = next(r for r in world.rules.values() if r.id != original.id)
    assert renewal.status == "renewed", "the renewal proposal lands in 'renewed'"
    assert renewal.renewal_of == original.id
    assert len(original.renewed_at) == 1, "the active law was refreshed once"

    passed = repo.get_events(loop._run_id, kinds=["rule_passed"], order="asc")
    assert len(passed) == 2
    first, second = passed
    assert "renewed" not in first["payload"]
    assert second["payload"]["renewed"] is True
    assert second["payload"]["rule_id"] == original.id, \
        "the renewal rule_passed points at the law in force"
    assert second["payload"]["renewal_proposal_id"] == renewal.id
    assert "RENEWED" in second["text"]

    # The re-proposal itself was flagged as a renewal.
    proposed = repo.get_events(loop._run_id, kinds=["rule_proposed"], order="asc")
    assert len(proposed) == 2
    assert "renewal_of" not in proposed[0]["payload"]
    assert proposed[1]["payload"]["renewal_of"] == original.id
    assert "RENEWAL" in proposed[1]["text"]


def test_different_effect_still_stacks_normally():
    agents = _gov_agents()
    world_holder: list[World] = []

    def vote_yes(agent_id, tick):
        w = world_holder[0]
        proposed = [r for r in w.rules.values() if r.status == "proposed"]
        if proposed:
            return {"action": "vote",
                    "args": {"rule_id": proposed[0].id, "choice": True}}
        return dict(IDLE)

    loop, world, repo, _, _ = _make_loop(
        _params(), agents,
        {"ada": [
            {"action": "propose_rule",
             "args": {"effect": "ubi", "text": "Everyone deserves a basic income"}},
            vote_yes,
            {"action": "propose_rule",
             "args": {"effect": "work_bonus", "text": "Honest work pays extra"}},
            vote_yes, dict(IDLE)],
         "bob": [vote_yes, dict(IDLE), vote_yes, dict(IDLE)]},
    )
    world_holder.append(world)
    asyncio.run(_drive(loop, world, 7))

    active = [r for r in world.rules.values() if r.status == "active"]
    assert {r.effect for r in active} == {"ubi", "work_bonus"}
    assert len(active) == 2, "different effects coexist (no renewal involved)"
    passed = repo.get_events(loop._run_id, kinds=["rule_passed"])
    assert len(passed) == 2
    assert all("renewed" not in p["payload"] for p in passed)


def test_em100_rule_feed_text_is_readable_never_the_bare_uuid():
    agents = _gov_agents()
    world_holder: list[World] = []

    def vote_no(agent_id, tick):
        w = world_holder[0]
        proposed = [r for r in w.rules.values() if r.status == "proposed"]
        if proposed:
            return {"action": "vote",
                    "args": {"rule_id": proposed[0].id, "choice": False}}
        return dict(IDLE)

    loop, world, repo, _, _ = _make_loop(
        _params(), agents,
        {"ada": [
            {"action": "propose_rule",
             "args": {"effect": "ban_stealing",
                      "text": "No stealing in our village"}},
            vote_no, dict(IDLE)],
         "bob": [vote_no, dict(IDLE)]},
    )
    world_holder.append(world)
    asyncio.run(_drive(loop, world, 3))  # propose, NO, NO → rejected

    rule = next(iter(world.rules.values()))
    assert rule.status == "rejected"
    rows = repo.get_events(
        loop._run_id, kinds=["rule_proposed", "rule_vote", "rule_rejected"],
        order="asc")
    assert {r["kind"] for r in rows} == {"rule_proposed", "rule_vote",
                                         "rule_rejected"}
    for row in rows:
        assert '"No stealing in our village"' in row["text"], \
            f'{row["kind"]} must lead with the quoted rule text'
        assert "(ban_stealing)" in row["text"], "effect tag in the feed line"
        assert rule.id not in row["text"], "the uuid stays OUT of the feed text"
        assert row["payload"]["rule_id"] == rule.id, "…and IN the payload"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Commemorative monuments (EM-103) — project named after an active rule is
#    tagged commemorative + rule_id; the second monument is rejected.
# ──────────────────────────────────────────────────────────────────────────────

def _world_with_active_ubi() -> tuple[World, AgentState, str]:
    params = _params()
    ada = _agent("agent_ada", "Ada", "townhall")
    world = World(params=params, places=_default_places(), agents=[ada])
    ok, _, rule = world.action_propose_rule(
        ada, "ubi", "Everyone deserves a basic income")
    assert ok and rule is not None
    rule.status = "active"
    return world, ada, rule.id


def test_commemorative_project_tagged_with_rule_id():
    world, ada, rule_id = _world_with_active_ubi()
    result = world.action_propose_project(ada, "Basic Income Monument",
                                          "monument", 10)
    assert "_multi" in result
    proposed = next(e for e in result["_multi"]
                    if e["kind"] == "project_proposed")
    assert proposed["payload"]["commemorative"] is True
    assert proposed["payload"]["rule_id"] == rule_id
    assert "commemorating the law" in proposed["text"]
    building = world.buildings[result["_building_id"]]
    assert building.commemorates == rule_id
    # The building snapshot carries the link (frontend seam).
    assert building.to_dict()["commemorates"] == rule_id


def test_second_commemorative_monument_is_rejected():
    world, ada, rule_id = _world_with_active_ubi()
    first = world.action_propose_project(ada, "Basic Income Monument",
                                         "monument", 10)
    assert "_multi" in first
    second = world.action_propose_project(ada, "Hall of Basic Income",
                                          "hall", 10)
    assert second["kind"] == "parse_failure", "one monument per law"
    assert second["payload"]["error"] == "commemorative_duplicate"
    assert "already stands" in second["text"]
    monuments = [b for b in world.buildings.values()
                 if b.commemorates == rule_id]
    assert len(monuments) == 1


def test_unrelated_project_is_not_commemorative():
    world, ada, _ = _world_with_active_ubi()
    result = world.action_propose_project(ada, "Mushroom Cellar", "cellar", 5)
    proposed = next(e for e in result["_multi"]
                    if e["kind"] == "project_proposed")
    assert "commemorative" not in proposed["payload"]
    assert world.buildings[result["_building_id"]].commemorates is None


def test_blank_text_rule_is_never_commemorable():
    """Regression (observed live, run 1050): a name_town / promote_image rule is
    an ACTION rule with EMPTY text by design. _commemorated_rule must skip it —
    otherwise `"" in <project name>` is always True, so EVERY project proposal
    matches the blank rule and (once one monument stands) is rejected as a
    duplicate monument to a blank law "". This silently broke ALL proposals."""
    params = _params()
    ada = _agent("agent_ada", "Ada", "townhall")
    world = World(params=params, places=_default_places(), agents=[ada])
    # a consensus town-naming rule: an action-rule with NO law text.
    world.rules["r_blank"] = RuleState(
        id="r_blank", effect="name_town", text="", proposer_id=ada.id,
        status="active")
    # the matcher must NOT match an unrelated project to the blank rule
    assert world._commemorated_rule("Flash Market") is None
    # and the proposal proceeds normally — not a phantom commemorative duplicate
    result = world.action_propose_project(ada, "Flash Market", "market", 10)
    assert "_multi" in result, "proposal must not reject against a blank law"
    proposed = next(e for e in result["_multi"]
                    if e["kind"] == "project_proposed")
    assert "commemorative" not in proposed["payload"]
    # a REAL text rule alongside the blank one still commemorates correctly
    ok, _, real = world.action_propose_rule(ada, "ubi", "basic income for all")
    real.status = "active"
    assert world._commemorated_rule("Basic Income Monument") is real


# ──────────────────────────────────────────────────────────────────────────────
# 6. Billboard (EM-091) — location gate, cap 20, snapshot shape, god post,
#    read injects memory.
# ──────────────────────────────────────────────────────────────────────────────

def test_post_billboard_gated_then_succeeds_at_plaza():
    ada = _agent("agent_ada", "Ada", "market")  # no board at a work place
    post = {"action": "post_billboard", "args": {"text": "BEWARE THE CAT"}}
    loop, world, repo, _, _ = _make_loop(
        _params(), [ada], {"ada": [post, post, post]},
    )
    asyncio.run(_drive(loop, world, 1))
    assert repo.get_events(loop._run_id, kinds=["billboard_posted"]) == [], \
        "posting away from plaza/townhall must be rejected"
    fails = repo.get_events(loop._run_id, kinds=["parse_failure"])
    assert fails and any("billboard" in (f["payload"].get("reason") or "")
                         for f in fails)
    assert world.billboard == []

    # Walk to the plaza: the same tool now lands on the board.
    world.agents["agent_ada"].location = "plaza"
    asyncio.run(_drive(loop, world, 1))
    posted = repo.get_events(loop._run_id, kinds=["billboard_posted"])
    assert len(posted) == 1
    assert posted[0]["payload"]["text"] == "BEWARE THE CAT"
    assert posted[0]["payload"]["place"] == "plaza"
    assert "📌" in posted[0]["text"]
    assert len(world.billboard) == 1
    assert world.billboard[0]["actor_type"] == "human_agent"


def test_billboard_caps_at_twenty_newest():
    world, ada, _ = _world_with_active_ubi()
    ada.location = "plaza"
    for i in range(1, 26):
        evt = world.action_post_billboard(ada, f"note {i}")
        assert evt["kind"] == "billboard_posted"
    assert len(world.billboard) == 20
    assert [e["text"] for e in world.billboard] == \
        [f"note {i}" for i in range(6, 26)], "cap keeps the 20 NEWEST"
    # read_billboard_top is newest-first.
    assert [e["text"] for e in world.read_billboard_top(3)] == \
        ["note 25", "note 24", "note 23"]


def test_billboard_shape_in_snapshot_and_world_state():
    ada = _agent("agent_ada", "Ada", "plaza")
    loop, world, repo, _, _ = _make_loop(
        _params(), [ada],
        {"ada": [{"action": "post_billboard", "args": {"text": "hello"}},
                 dict(IDLE)]},
    )
    asyncio.run(_drive(loop, world, 1))

    snap = world.to_snapshot()
    assert snap["billboard"] == [{"tick": 0, "actor_id": "agent_ada",
                                  "actor_type": "human_agent", "text": "hello"}]
    # The live world_state message carries the same list (THE frontend seam).
    ws = loop.current_snapshot()
    assert ws["billboard"] == snap["billboard"]


def test_god_billboard_api_201_event_and_422s():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/billboard",
                           json={"text": "Behold, mortals", "in_reply_to": "x1"})
        assert resp.status_code == 201

        repo = appmod._repo
        run_id = appmod._loop._run_id
        rows = repo.get_events(run_id, kinds=["billboard_posted"])
        assert len(rows) == 1
        assert rows[0]["actor_type"] == "god"
        assert rows[0]["actor_id"] == "god"
        assert rows[0]["payload"]["text"] == "Behold, mortals"
        assert rows[0]["payload"]["in_reply_to"] == "x1"
        board = appmod._world.billboard
        assert board and board[-1]["actor_type"] == "god"

        # 422s: empty, whitespace-only, oversized.
        assert client.post("/api/billboard", json={"text": ""}).status_code == 422
        assert client.post("/api/billboard", json={"text": "   "}).status_code == 422
        assert client.post("/api/billboard",
                           json={"text": "x" * 281}).status_code == 422
        assert len(repo.get_events(run_id, kinds=["billboard_posted"])) == 1, \
            "rejected posts must not emit"


def test_read_billboard_injects_posts_into_memory():
    ada = _agent("agent_ada", "Ada", "plaza")
    loop, world, repo, runtime, _ = _make_loop(
        _params(), [ada],
        {"ada": [{"action": "read_billboard", "args": {}}, dict(IDLE)]},
    )
    world.post_billboard_as_god("Sweep the plaza")  # board state only is fine

    asyncio.run(_drive(loop, world, 1))

    rows = repo.get_events(loop._run_id, kinds=["agent_action"])
    read = next(r for r in rows
                if r["payload"].get("action") == "read_billboard")
    assert read["payload"]["posts"][0]["text"] == "Sweep the plaza"
    memory = runtime._memory["agent_ada"]
    assert any(m.get("kind") == "billboard_posted"
               and "[billboard, by GOD] Sweep the plaza" in m.get("text", "")
               for m in memory), "read posts must enter the memory buffer"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Procgen (EM-098) — disabled = hand-authored byte-identical; enabled =
#    deterministic per seed, minimums, cottages + bunkhouse, ≤12 town places.
# ──────────────────────────────────────────────────────────────────────────────

def test_procgen_disabled_leaves_hand_authored_town_byte_identical():
    params = _params()  # ProcgenParams() default: enabled=False
    assert params.procgen.enabled is False, "procgen must default OFF"
    world = World(params=params, places=_default_places(),
                  agents=[_agent("agent_ada", "Ada")])
    expected = [p.to_dict() for p in _default_places()]
    assert json.dumps([p.to_dict() for p in world.places.values()],
                      sort_keys=True) == \
        json.dumps(expected, sort_keys=True), \
        "disabled procgen must not touch the hand-authored town"


def test_procgen_enabled_is_deterministic_with_minimums_and_housing():
    def build(seed: int) -> World:
        params = _params(procgen=ProcgenParams(enabled=True, seed=seed,
                                               n_places=9))
        agents = [_agent("agent_ada", "Ada", "plaza"),
                  _agent("agent_bram", "Bram", "old_market")]
        return World(params=params, places=_default_places(), agents=agents)

    w1, w2 = build(7), build(7)
    layout = lambda w: json.dumps([p.to_dict() for p in w.places.values()],
                                  sort_keys=True)
    assert layout(w1) == layout(w2), "same seed ⇒ identical town"
    assert layout(w1) != layout(build(8)), "different seed ⇒ different town"

    places = w1.places
    kinds = {p.kind for p in places.values()}
    assert {"governance", "work", "wild", "social"} <= kinds, \
        "guaranteed minimums: ≥1 gov/work/wild/social"
    assert places["plaza"].kind == "social"
    assert "townhall" in places and places["townhall"].kind == "governance", \
        "the first governance place is ALWAYS id 'townhall' (billboard gate)"

    # Housing: one cottage per agent + the capacity-limited bunkhouse.
    names = {p.name: p for p in places.values()}
    for who in ("Ada", "Bram"):
        cottage = names[f"{who}'s cottage"]
        assert cottage.kind == "home"
    bunk = names["The Bunkhouse"]
    assert bunk.kind == "home"
    assert bunk.capacity == 1, "beds = agents - 1 (scarcity)"

    # Agents standing on a now-unknown place are clamped back to the plaza.
    assert w1.agents["agent_bram"].location == "plaza"
    assert w1.agents["agent_ada"].location == "plaza"


def test_procgen_town_capped_at_twelve_places():
    params = _params(procgen=ProcgenParams(enabled=True, seed=3, n_places=999))
    agents = [_agent("agent_ada", "Ada"), _agent("agent_bram", "Bram"),
              _agent("agent_cleo", "Cleo")]
    world = World(params=params, places=_default_places(), agents=agents)
    housing = len(agents) + 1  # cottages + the bunkhouse, ON TOP of the town
    town = len(world.places) - housing
    assert town <= 12, f"town proper must cap at 12 places (got {town})"
    # And the pure generator honors the same cap.
    gen = generate_procgen_places(
        ProcgenParams(enabled=True, seed=3, n_places=999), ["Ada"])
    assert len(gen) - 2 <= 12  # minus 1 cottage + 1 bunkhouse


# ──────────────────────────────────────────────────────────────────────────────
# 8. Blackout (EM-083 engine half) — recharge rejected during, restored after;
#    events emitted on inject + expiry.
# ──────────────────────────────────────────────────────────────────────────────

def test_blackout_disables_recharge_until_it_expires():
    params = _params(blackout_ticks=4)
    ada = _agent("agent_ada", "Ada", "shack", energy=50.0, credits=20)
    world = World(params=params, places=_default_places(), agents=[ada])
    world.tick = 5

    place_ids, until, events = world.apply_blackout()
    assert place_ids == ["shack"], "home-kind places go dark"
    assert until == 9
    assert len(events) == 1 and events[0]["payload"]["to"] == "blackout"
    assert world.place_blacked_out("shack") is True

    ok, reason, gained = world.action_recharge(ada)
    assert ok is False and "blackout" in reason and gained == 0.0
    assert ada.credits == 20, "a rejected recharge must not charge credits"

    # The runtime validator mirrors the gate (agents get feedback, not idle).
    from petridish.agents.runtime import _validate_world
    err = _validate_world({"action": "recharge", "args": {}}, ada, world)
    assert err is not None and "blackout" in err

    # Power returns at until_tick: recharge works again.
    world.tick = 9
    expiry = world.expire_blackouts()
    assert len(expiry) == 1 and expiry[0]["payload"]["to"] == "powered"
    assert world.places["shack"].blackout_until_tick == 0
    ok, reason, gained = world.action_recharge(ada)
    assert ok is True and gained > 0


def test_blackout_inject_emits_events_and_loop_expiry_restores():
    ada = _agent("agent_ada", "Ada", "plaza")
    loop, world, repo, _, _ = _make_loop(
        _params(blackout_ticks=2), [ada], {"ada": [dict(IDLE)]},
    )
    result = loop.inject_random_event("blackout")
    assert result["kind"] == "blackout"

    rnd = repo.get_events(loop._run_id, kinds=["random_event"])
    assert len(rnd) == 1
    assert rnd[0]["payload"]["places"] == ["shack"]
    assert rnd[0]["payload"]["until_tick"] == 2
    changed = repo.get_events(loop._run_id, kinds=["structure_state_changed"])
    assert [c["payload"]["to"] for c in changed] == ["blackout"]
    assert changed[0]["actor_type"] == "system"

    # Drive past the window: the loop emits the restoration event.
    asyncio.run(_drive(loop, world, 3))  # ticks 0,1,2 — expiry fires at tick 2
    changed = repo.get_events(loop._run_id, kinds=["structure_state_changed"])
    assert [c["payload"]["to"] for c in changed] == ["blackout", "powered"]
    assert world.places["shack"].blackout_until_tick == 0


# ──────────────────────────────────────────────────────────────────────────────
# 9. World.from_snapshot (EM-101 engine half) — to→from→to round trip equality
#    (modulo the documented beliefs limit); place_overrides replace wholesale.
# ──────────────────────────────────────────────────────────────────────────────

def _textured_world(params: WorldParams) -> World:
    ada = _agent("agent_ada", "Ada", "plaza", energy=42.5, credits=17)
    bob = _agent("agent_bob", "Bob", "shack", energy=0.0, credits=3)
    world = World(params=params, places=_default_places(), agents=[ada, bob])
    world.next_agent()  # advance the scheduler so turn state is non-trivial
    world.tick, world.day, world.round = 37, 1, 3
    world.running = False
    ada.mood = "wary"
    bob.zero_energy_turns = 2
    ada.relationships["agent_bob"] = RelationshipState("ally", 40, 3)

    # Civic actions are gated to the governance place — propose from the town
    # hall, then return to the textured home locations.
    ada.location = bob.location = "townhall"
    ok, _, rule = world.action_propose_rule(
        ada, "ubi", "Everyone deserves a basic income")
    assert ok and rule
    rule.status = "active"
    rule.votes = {"agent_ada": True, "agent_bob": True}
    rule.renewed_at = [30]
    ok, _, renewal = world.action_propose_rule(
        bob, "ubi", "Everyone deserves a basic income")
    assert ok and renewal and renewal.renewal_of == rule.id
    renewal.status = "renewed"
    ada.location, bob.location = "plaza", "shack"

    world.buildings["bld_x"] = Building(
        id="bld_x", name="Basic Income Monument", kind="monument",
        location="plaza", status="under_construction", progress=40,
        funds_committed=5, funds_required=10, contributors=["agent_ada"],
        created_tick=20, updated_tick=30, last_progress_tick=30,
        commemorates=rule.id,
    )
    world.spawn_animal("cat", "Mochi", "plaza", personality="feral")
    world._append_billboard("agent_ada", "human_agent", "meet at the mill")
    world._append_billboard("god", "god", "behave")
    world.places["shack"].blackout_until_tick = 50
    return world


def test_from_snapshot_round_trips_to_snapshot():
    params = _params()
    world = _textured_world(params)
    snap = world.to_snapshot()

    restored = World.from_snapshot(snap, params=params)
    assert restored.to_snapshot() == snap, \
        "to → from → to must round-trip exactly (no beliefs were set)"
    # The contract details worth naming even though the dict equality covers
    # them: scheduler, lineage bookkeeping, blackout, billboard, running=False.
    assert restored.tick == 37 and restored.round == 3
    assert restored._turn_order == world._turn_order
    assert restored._turn_index == world._turn_index
    assert restored.running is False, "a restored/forked world starts paused"
    assert restored.place_blacked_out("shack") is True
    rule = next(r for r in restored.rules.values() if r.status == "active")
    assert rule.renewed_at == [30]
    renewal = next(r for r in restored.rules.values() if r.status == "renewed")
    assert renewal.renewal_of == rule.id
    assert restored.buildings["bld_x"].commemorates == rule.id
    assert [e["text"] for e in restored.billboard] == \
        ["meet at the mill", "behave"]


def test_from_snapshot_beliefs_restore_empty_documented_limit():
    """to_snapshot serializes only beliefs_count, so beliefs restore empty —
    the DOCUMENTED from_snapshot limit (this pins it so a silent fix or a
    silent regression both surface)."""
    params = _params()
    world = _textured_world(params)
    world.agents["agent_ada"].beliefs = ["the market is profitable"]
    snap = world.to_snapshot()
    ada_snap = next(a for a in snap["agents"] if a["id"] == "agent_ada")
    assert ada_snap["beliefs_count"] == 1

    restored = World.from_snapshot(snap, params=params)
    assert restored.agents["agent_ada"].beliefs == []
    restored_snap = restored.to_snapshot()
    ada_restored = next(a for a in restored_snap["agents"]
                        if a["id"] == "agent_ada")
    assert ada_restored["beliefs_count"] == 0


def test_from_snapshot_place_overrides_replace_wholesale():
    params = _params()
    world = _textured_world(params)
    snap = world.to_snapshot()

    restored = World.from_snapshot(
        snap,
        place_overrides=[{"id": "void", "name": "The Void", "x": 1, "y": 2,
                          "kind": "wild", "description": "nothing here",
                          "capacity": 3}],
        params=params,
    )
    assert set(restored.places.keys()) == {"void"}, \
        "place_overrides REPLACE the snapshot geometry wholesale"
    void = restored.places["void"]
    assert (void.name, void.kind, void.capacity) == ("The Void", "wild", 3)


# ──────────────────────────────────────────────────────────────────────────────
# 10. POST /api/runs/fork (EM-101 platform half)
# ──────────────────────────────────────────────────────────────────────────────

def _seed_forkable_run(repo: SQLiteRepository) -> tuple[int, dict]:
    """A finished run with a tick-5 snapshot and events through tick 9."""
    params = WorldParams()
    world = World(
        params=params,
        places=[PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")],
        agents=[AgentState(id="agent_old", name="Old", personality="",
                           profile="mock", location="plaza",
                           energy=50.0, credits=9)],
    )
    world.tick = 5
    world._append_billboard("agent_old", "human_agent", "from the past")
    snap = world.to_snapshot()
    run_id = repo.start_run(json.dumps(
        {"world": {}, "agents": [{"name": "Old", "profile": "mock"}]}))
    repo.save_world_snapshot(run_id, 5, json.dumps(snap))
    repo.save_event(run_id, {"kind": "agent_speech", "actor_id": "agent_old",
                             "text": "echo", "payload": {}}, 9)
    repo.end_run(run_id)
    return run_id, snap


def test_fork_201_lineage_paused_and_run_forked_event():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        past, snap = _seed_forkable_run(appmod._repo)
        old_live = appmod._loop._run_id

        resp = client.post("/api/runs/fork", json={"run_id": past, "tick": 9})
        assert resp.status_code == 201
        body = resp.json()
        new_id = body["run_id"]
        assert new_id != past and new_id != old_live
        # HONEST snapshot-grain semantics: the nearest snapshot ≤ 9 is tick 5,
        # the response says so, and a note explains the unfolded delta.
        assert body["forked_at_tick"] == 5
        assert "note" in body and "nearest snapshot" in body["note"]

        # The forked run is now the live (paused) world.
        assert appmod._loop._run_id == new_id
        state = client.get("/api/state").json()
        assert state["running"] is False, "a fork starts PAUSED"
        assert state["tick"] == 5
        assert [a["id"] for a in state["agents"]] == ["agent_old"]
        assert state["billboard"] == snap["billboard"], \
            "billboard state survives the fork"

        # Lineage on the RunRow + is_active moves to the fork.
        runs = {r["id"]: r for r in client.get("/api/runs").json()}
        assert runs[new_id]["forked_from"] == past
        assert runs[new_id]["forked_at_tick"] == 5
        assert runs[new_id]["is_active"] is True
        assert runs[old_live]["is_active"] is False
        assert runs[past]["forked_from"] is None

        # First event of the forked run records the lineage.
        events = client.get(f"/api/events?run_id={new_id}").json()
        assert events and events[0]["kind"] == "run_forked"
        assert events[0]["payload"] == {"parent_run_id": past, "tick": 5}
        assert events[0]["actor_type"] == "system"


def test_fork_at_exact_snapshot_tick_has_no_note():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        past, _ = _seed_forkable_run(appmod._repo)
        resp = client.post("/api/runs/fork", json={"run_id": past, "tick": 5})
        assert resp.status_code == 201
        body = resp.json()
        assert body["forked_at_tick"] == 5
        assert "note" not in body, "requested == actual ⇒ nothing to confess"


def test_fork_unknown_run_404():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/runs/fork",
                           json={"run_id": 999999, "tick": 0})
        assert resp.status_code == 404


def test_fork_bad_tick_and_bad_overrides_400():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        past, _ = _seed_forkable_run(appmod._repo)
        # Out-of-range ticks.
        assert client.post("/api/runs/fork",
                           json={"run_id": past, "tick": -1}).status_code == 400
        assert client.post("/api/runs/fork",
                           json={"run_id": past, "tick": 99}).status_code == 400
        # Malformed place_overrides (contract 400, not pydantic 422).
        for bad in ("nope", [1, 2], {"id": "x"}):
            resp = client.post("/api/runs/fork",
                               json={"run_id": past, "tick": 9,
                                     "place_overrides": bad})
            assert resp.status_code == 400, f"overrides={bad!r}"


def test_fork_run_without_snapshot_400():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        repo = appmod._repo
        bare = repo.start_run("{}")
        repo.save_event(bare, {"kind": "agent_speech", "actor_id": "x",
                               "payload": {}}, 3)
        repo.end_run(bare)
        resp = client.post("/api/runs/fork", json={"run_id": bare, "tick": 3})
        assert resp.status_code == 400
        assert "snapshot" in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 11. Personas (EM-092) — GET shape; spawn prefill; explicit wins; 400s.
# ──────────────────────────────────────────────────────────────────────────────

PERSONA_KEYS = {"name", "archetype", "personality", "suggested_profile",
                "disposition", "role"}  # EM-240 — additive persona schema


def test_get_personas_serves_the_card_library():
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        cards = client.get("/api/personas").json()
        assert len(cards) == 10, "the shipped library has 10 cards"
        for c in cards:
            assert set(c.keys()) == PERSONA_KEYS
            assert c["name"], "cards without a name are dropped by the loader"
            assert all(isinstance(c[k], str) for k in PERSONA_KEYS)
        names = [c["name"] for c in cards]
        assert len(set(names)) == len(names), "card names are unique"
        assert "Mox" in names


def test_load_personas_missing_or_malformed_yaml_is_empty(tmp_path, monkeypatch):
    # Missing file → [] (never 500).
    monkeypatch.setenv("EM_CONFIG_DIR", str(tmp_path))
    assert load_personas() == []
    # Malformed YAML → [].
    (tmp_path / "personas.yaml").write_text("personas: [unclosed")
    assert load_personas() == []
    # Wrong top-level shape → [].
    (tmp_path / "personas.yaml").write_text("personas: not-a-list")
    assert load_personas() == []
    # Cards without a name are dropped; valid ones survive.
    (tmp_path / "personas.yaml").write_text(
        "personas:\n"
        "  - archetype: Ghost\n"
        "  - name: Real\n    archetype: Farmer\n"
    )
    cards = load_personas()
    assert [c["name"] for c in cards] == ["Real"]
    assert cards[0] == {"name": "Real", "archetype": "Farmer",
                        "personality": "", "suggested_profile": "",
                        # EM-240 — additive persona schema; defaults when absent.
                        "disposition": "lawful", "role": "citizen"}


def test_spawn_with_persona_prefills_from_the_card():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        card = next(c for c in client.get("/api/personas").json()
                    if c["name"] == "Mox")
        resp = client.post("/api/agents",
                           json={"persona": "Mox", "mode": "god"})
        assert resp.status_code == 201
        agent_id = resp.json()["agent_id"]
        agent = appmod._world.agents[agent_id]
        # run-663 — the default roster already holds a "Mox", so a 2nd one is
        # auto-disambiguated (Mox → Mox II); persona prefill is unaffected.
        assert agent.name == "Mox II"
        assert agent.personality == card["personality"]
        assert agent.profile == card["suggested_profile"]


def test_spawn_explicit_fields_win_over_the_persona():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/agents", json={
            "persona": "Mox", "name": "Override", "profile": "mock",
            "personality": "entirely custom", "mode": "god",
        })
        assert resp.status_code == 201
        agent = appmod._world.agents[resp.json()["agent_id"]]
        assert agent.name == "Override"
        assert agent.profile == "mock"
        assert agent.personality == "entirely custom"


@pytest.mark.parametrize("body,fragment", [
    ({"persona": "NoSuchCard", "mode": "god"}, "Unknown persona"),
    ({"mode": "god"}, "name is required"),
    ({"name": "Solo", "mode": "god"}, "profile is required"),
    ({"name": "Solo", "profile": "no-such-profile", "mode": "god"},
     "Unknown profile"),
])
def test_spawn_validation_400s(body, fragment):
    """W11B_BUILD.md gate-log deviation: missing name/profile are 400 (not
    422) now that the schema is persona-optional."""
    from fastapi.testclient import TestClient
    from petridish.api.app import app

    with TestClient(app, raise_server_exceptions=True) as client:
        resp = client.post("/api/agents", json=body)
        assert resp.status_code == 400
        assert fragment in resp.json()["detail"]


# ──────────────────────────────────────────────────────────────────────────────
# 12. Usage alerts (EM-083 platform half) — 70% crossing once per
#     provider/metric/UTC-day; rollover re-arms; no caps = no alerts.
# ──────────────────────────────────────────────────────────────────────────────

def test_usage_alert_fires_once_on_crossing_seventy_percent():
    tracker = UsageAlertTracker({"groq-llama": {"rpd": 10}})
    for _ in range(6):
        assert tracker.note("groq-llama") == [], "below 70% — silent"
    alerts = tracker.note("groq-llama")  # 7/10 = 70% — the crossing
    assert alerts == [{"provider": "groq-llama", "metric": "rpd",
                       "pct": 70.0, "limit": 10}]
    for _ in range(5):
        assert tracker.note("groq-llama") == [], \
            "same provider/metric/window must never alert twice"


def test_usage_alert_tpd_tracks_tokens():
    tracker = UsageAlertTracker({"cerebras-glm": {"tpd": 1000}})
    assert tracker.note("cerebras-glm", tokens=699) == []
    alerts = tracker.note("cerebras-glm", tokens=1)  # 700/1000
    assert alerts == [{"provider": "cerebras-glm", "metric": "tpd",
                       "pct": 70.0, "limit": 1000}]


def test_usage_alert_day_rollover_resets_and_rearms():
    day = ["2026-06-09"]
    tracker = UsageAlertTracker({"prov": {"rpd": 10}}, clock=lambda: day[0])
    for _ in range(7):
        tracker.note("prov")
    assert tracker.note("prov") == [], "latched for today"

    day[0] = "2026-06-10"  # UTC date rollover: fresh quota, re-armed alert
    for _ in range(6):
        assert tracker.note("prov") == []
    assert tracker.note("prov") == [{"provider": "prov", "metric": "rpd",
                                     "pct": 70.0, "limit": 10}]


def test_no_caps_means_no_alerts_and_no_state():
    tracker = UsageAlertTracker({})
    assert tracker.has_caps is False
    assert tracker.note("anything", tokens=10**9) == []
    # Malformed / non-positive caps are dropped at construction.
    tracker = UsageAlertTracker({"p1": {"rpd": "garbage"}, "p2": {"tpd": 0},
                                 "p3": "not-a-dict"})
    assert tracker.has_caps is False
    assert tracker.note("p1") == []


def test_usage_alert_sink_lands_in_the_event_log():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:  # noqa: F841
        appmod._emit_usage_alert({"provider": "groq-llama", "metric": "rpd",
                                  "pct": 70.0, "limit": 1000})
        rows = appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["usage_alert"])
        assert len(rows) == 1
        assert rows[0]["actor_type"] == "system"
        assert rows[0]["payload"] == {"provider": "groq-llama", "metric": "rpd",
                                      "pct": 70.0, "limit": 1000}
        assert "70" in rows[0]["text"] and "groq-llama" in rows[0]["text"]

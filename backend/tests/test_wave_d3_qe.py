"""
Wave D3 QE gate — adversarial verification tests (contracts/wave-d3.md §Gates).

The wave's shipped tests are strong (test_lane_failover.py §F already asserts
on adapter CALL RECORDS, not return values), but two scenario shapes from the
QE mandate had no permanent in-repo proof:

  1. THE 2026-06-11 INCIDENT SHAPE (EM-177): every lane sick except ONE
     (mistral-small was the only survivor). Multiple agents on DIFFERENT sick
     home lanes must all converge their real calls on the single healthy
     substitute (at ITS budget), while every probe_every-th would-be-detour
     still tests each agent's own HOME adapter — and the mock adapter receives
     ZERO calls no matter how starved the lane pool gets. Proof surface is the
     recording adapters' call logs ("a green gate is a proxy — verify the
     SUBSTITUTE adapter object actually receives the chat() call").

  2. DEMOTION REALITY (EM-168): a cap-governed demotion must change actual
     SCHEDULING, not just the cadence_tier label. test_cap_governor.py checks
     the _tier_due predicate; this file drives the real next_agent() rotation
     across rounds and counts who acted — protagonist cadence (every round)
     before the alert, supporting cadence (every 3rd round) after, protagonist
     again after the day-window restore.

Deterministic and offline (recording fakes, no network, no real keys, zero
LLM calls beyond the scripted fakes — free-scale law upheld).
CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import json

import pytest

from petridish.config.loader import CapGovernorParams, ModelProfile, WorldParams
from petridish.engine.world import World, AgentState, PlaceState
from petridish.agents.runtime import AgentRuntime
from petridish.providers.router import Router


_VALID_ACTION_JSON = json.dumps({"action": "idle", "args": {}, "thought": "ok"})

# Env var the test profiles use for availability; set in the autouse fixture.
_KEY_ENV = "EM_WAVE_D3_QE_TEST_KEY"

D1 = "2026-06-11"
D2 = "2026-06-12"


@pytest.fixture(autouse=True)
def _lane_key(monkeypatch):
    monkeypatch.setenv(_KEY_ENV, "test-key")


class RecordingAdapter:
    """Recording fake adapter: every chat() call is the proof surface."""

    def __init__(self, name: str, text: str = _VALID_ACTION_JSON):
        self.name = name
        self.text = text
        self.calls: list[tuple[int, float]] = []  # (max_tokens, temperature)
        self.last_routed_via = f"real/{name}"
        self.last_usage = None

    async def chat(self, messages, *, max_tokens, temperature):
        self.calls.append((max_tokens, temperature))
        return self.text


def _profile(name: str, *, adapter: str = "openai", max_tokens: int = 512,
             temperature: float = 0.8) -> ModelProfile:
    return ModelProfile(
        name=name, adapter=adapter, model_id=f"model/{name}",
        max_tokens=max_tokens, temperature=temperature,
        base_url="http://localhost:9",
        api_key_env=_KEY_ENV if adapter != "mock" else "",
    )


def _sicken(r: Router, lane: str, n: int = 3) -> None:
    for _ in range(n):
        r.note_parse_outcome(lane, parsed=False, truncated=False, timed_out=True)


# ──────────────────────────────────────────────────────────────────────────────
# 1. EM-177 — the 2026-06-11 incident shape: all lanes sick except one
# ──────────────────────────────────────────────────────────────────────────────

# The incident's lane pool, modeled: five sick FreeLLMAPI lanes, one healthy
# survivor (distinctive budget so a detoured call is provably AT its budget),
# and the mock lane that must never absorb a detour.
_SICK_LANES = ("cerebras-glm", "qwen-next", "gemini-flash", "groq-llama",
               "deepseek-pro")
_HEALTHY_LANE = "mistral-small"
_HOME_BUDGET = (512, 0.8)
_HEALTHY_BUDGET = (640, 0.4)


def _incident_setup():
    adapters = {name: RecordingAdapter(name) for name in _SICK_LANES}
    adapters[_HEALTHY_LANE] = RecordingAdapter(_HEALTHY_LANE)
    adapters["mock"] = RecordingAdapter("mock")
    profiles = (
        [_profile(n) for n in _SICK_LANES]
        + [_profile(_HEALTHY_LANE, max_tokens=640, temperature=0.4),
           _profile("mock", adapter="mock")]
    )
    router = Router(profiles, adapter_overrides=dict(adapters),
                    cache_enabled=False)
    events: list[dict] = []
    router.set_lane_event_sink(events.append)

    homes = ("cerebras-glm", "qwen-next", "gemini-flash")
    params = WorldParams(energy_decay_per_turn=0.0, starting_energy=88.0,
                         starting_credits=10, memory_window=5)
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0,
                         kind="social")]
    agents = [
        AgentState(id=f"agent_{i}", name=f"Agent{i}", personality="curious",
                   profile=home, location="plaza", energy=88.0, credits=10)
        for i, home in enumerate(homes)
    ]
    world = World(params=params, places=places, agents=agents)
    runtime = AgentRuntime(world, router)
    for agent in agents:
        router.reassign(agent.id, agent.profile)
    for lane in _SICK_LANES:
        _sicken(router, lane, 3)
    return router, runtime, world, adapters, events, agents


@pytest.mark.asyncio
async def test_incident_shape_all_agents_converge_on_the_only_healthy_lane():
    """8 interleaved turns per agent (3 agents, 3 different sick homes):
    every real call lands on the healthy survivor at ITS budget — except each
    home lane's 4th/8th would-be-detour, which probes HOME at the home
    budget. Mock and the non-home sick lanes receive ZERO calls."""
    router, runtime, world, adapters, events, agents = _incident_setup()

    spans: dict[str, list[dict]] = {a.id: [] for a in agents}
    for _turn in range(8):
        for agent in agents:
            event = await runtime.run_turn(agent)
            assert event["kind"] != "parse_failure"
            spans[agent.id].append(event["_trace"]["llm_attempts"][0])

    # Convergence: the healthy adapter REALLY served 6 of each agent's 8
    # calls (turns 1-3, 5-7 of each per-home-lane probe cadence) ...
    healthy = adapters[_HEALTHY_LANE]
    assert len(healthy.calls) == 18
    assert set(healthy.calls) == {_HEALTHY_BUDGET}  # substitute's OWN budget

    # ... while each HOME adapter received exactly its two probes (calls 4
    # and 8 of that lane's would-be-detour counter) at the HOME budget.
    for home in ("cerebras-glm", "qwen-next", "gemini-flash"):
        assert adapters[home].calls == [_HOME_BUDGET, _HOME_BUDGET], home

    # Never to mock, never to a sick non-home lane.
    assert adapters["mock"].calls == []
    assert adapters["groq-llama"].calls == []
    assert adapters["deepseek-pro"].calls == []

    # Per-agent span truth: 6 detours + 2 probes, all stamped with the home
    # lane; identity (assigned profile) untouched throughout.
    for agent in agents:
        reasons = [
            "probe" if s.get("probe") else
            "detour" if s.get("detoured") else None
            for s in spans[agent.id]
        ]
        assert reasons == ["detour", "detour", "detour", "probe"] * 2
        assert all(s["requested_profile"] == agent.profile
                   for s in spans[agent.id])
        detour_models = {s["gen_ai.request.model"]
                         for s in spans[agent.id] if s.get("detoured")}
        assert detour_models == {_HEALTHY_LANE}
        assert router.profile_name_for(agent.id, agent.profile) == agent.profile

    # Feed transparency without spam: ONE degraded edge per home lane, no
    # recovery (the homes stay sick across these 8 turns).
    assert sorted(e["home"] for e in events) == [
        "cerebras-glm", "gemini-flash", "qwen-next"]
    assert {e["phase"] for e in events} == {"degraded"}
    assert {e["substitute"] for e in events} == {_HEALTHY_LANE}


@pytest.mark.asyncio
async def test_incident_shape_probe_outcomes_age_a_home_lane_back_home():
    """Drive ONE agent until its home lane recovers purely through clean
    probe outcomes (deque maxlen 6 ages the 3 timeouts out after 4 clean
    entries): the agent must end up back on its HOME adapter, with the
    recovery edge event emitted exactly once."""
    router, runtime, world, adapters, events, agents = _incident_setup()
    agent = agents[0]                      # home: cerebras-glm
    home = adapters["cerebras-glm"]

    for _turn in range(40):
        event = await runtime.run_turn(agent)
        assert event["kind"] != "parse_failure"
        span = event["_trace"]["llm_attempts"][0]
        if not (span.get("detoured") or span.get("probe")):
            break                          # recovered: a plain home call
    else:                                  # pragma: no cover - failure path
        pytest.fail("home lane never recovered through probe outcomes")

    assert not router.lane_sick("cerebras-glm")
    # Probes 4/8/12/16 each appended a clean outcome; the 4th flushed the
    # last timeout out of the 6-window. The final call above ran at home.
    assert home.calls[-1] == _HOME_BUDGET
    phases = [e["phase"] for e in events if e["home"] == "cerebras-glm"]
    assert phases == ["degraded", "recovered"]


# ──────────────────────────────────────────────────────────────────────────────
# 2. EM-168 — demotion changes REAL scheduling, not just the tier label
# ──────────────────────────────────────────────────────────────────────────────

def _scheduler_world() -> World:
    # These tests exercise the demotion machinery itself; the governor is
    # explicitly enabled (shipped default went OFF with EM-198, 2026-06-12).
    params = WorldParams(energy_decay_per_turn=0.0,
                         cap_governor=CapGovernorParams(enabled=True))
    places = [PlaceState(id="plaza", name="Central Plaza", x=0, y=0,
                         kind="social")]
    agents = [
        AgentState(id="agent_ada", name="Ada", personality="", profile="alpha",
                   location="plaza", energy=80.0, credits=10,
                   cadence_tier="protagonist"),
        AgentState(id="agent_bob", name="Bob", personality="", profile="beta",
                   location="plaza", energy=80.0, credits=10,
                   cadence_tier="protagonist"),
    ]
    return World(params=params, places=places, agents=agents)


def _drive_rounds(world: World, n_rounds: int) -> dict[int, list[str]]:
    """Pull next_agent() through `n_rounds` complete rounds, returning
    {round: [actor ids in order]} — the real scheduler, no shortcuts."""
    acted: dict[int, list[str]] = {}
    start = world.round
    while world.round < start + n_rounds or not world._round_start:
        agent = world.next_agent()
        assert agent is not None
        acted.setdefault(world.round, []).append(agent.id)
        if world.round >= start + n_rounds and world._round_start:
            break
    return acted


def test_demoted_protagonist_actually_takes_fewer_scheduled_turns():
    world = _scheduler_world()

    # Baseline: both protagonists act EVERY round.
    before = _drive_rounds(world, 3)            # rounds 1-3
    assert before == {1: ["agent_ada", "agent_bob"],
                      2: ["agent_ada", "agent_bob"],
                      3: ["agent_ada", "agent_bob"]}

    # Ada's lane crosses its day cap: demoted protagonist → supporting.
    world.apply_cap_pressure("alpha", D1)
    assert world.agents["agent_ada"].cadence_tier == "supporting"

    # Rounds 4-12: Ada is scheduled ONLY on supporting cadence (round % 3 ==
    # 0), Bob still every round — the demotion changed the real rotation.
    during = _drive_rounds(world, 9)            # rounds 4-12
    ada_rounds = sorted(r for r, ids in during.items() if "agent_ada" in ids)
    bob_rounds = sorted(r for r, ids in during.items() if "agent_bob" in ids)
    assert ada_rounds == [6, 9, 12]
    assert bob_rounds == list(range(4, 13))
    # 3 vs 9 turns: the LLM-consulting turn count really dropped to a third.
    ada_turns = sum(ids.count("agent_ada") for ids in during.values())
    bob_turns = sum(ids.count("agent_bob") for ids in during.values())
    assert (ada_turns, bob_turns) == (3, 9)

    # Day rollover restores the tier — and the very next rounds schedule it.
    world.restore_cap_demotions(D2)
    assert world.agents["agent_ada"].cadence_tier == "protagonist"
    after = _drive_rounds(world, 2)             # rounds 13-14
    assert all(ids == ["agent_ada", "agent_bob"] for ids in after.values())


def test_scheduler_side_rollover_probe_restores_mid_run_scheduling():
    """The same proof through the zero-clock probe path next_agent() itself
    consults: the tracker's window rolls, and Ada is back in the rotation
    without any alert arriving."""
    world = _scheduler_world()
    cell = {"window": D1}
    world.set_usage_window_probe(lambda: cell["window"])
    world.apply_cap_pressure("alpha", D1)

    during = _drive_rounds(world, 2)            # rounds 1-2: Ada not due
    assert all(ids == ["agent_bob"] for ids in during.values())

    cell["window"] = D2                         # the tracker's day rolls
    after = _drive_rounds(world, 2)             # rounds 3-4
    assert all(ids == ["agent_ada", "agent_bob"] for ids in after.values())
    assert world.agents["agent_ada"].cadence_tier == "protagonist"
    assert world.cap_demotions == {}

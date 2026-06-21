"""
EM-223 — recursive + reactive planning (Wave L). Build units 1–5a.

Proves the spike's Definition of Done:
  · world.planning.enabled default False ⇒ prompt golden + snapshot key set
    byte-identical (the protagonist fixture guard owns the full-prompt check;
    here we assert the snapshot key set is unchanged + plan never set).
  · AgentState.plan is additive: snapshot round-trips with AND without a plan;
    normalize_plan is total (malformed → None, never raises).
  · plan_revision folds into a turn with ZERO extra LLM calls; sets agent.plan;
    emits one plan_revised event that persists + broadcasts.
  · the plan block rides the NEXT prompt (after commitments, before beliefs) and
    invites abandonment; absent when disabled.
  · plan-biased reflex stays zero-call and only re-orders valid reflex actions.
  · gate/floor state (reflex_streak / salience / spontaneity) is provably
    untouched by plan mutation.

Deterministic and offline (the test_w11b ByAgentProvider idiom, ':memory:' DBs).
"""
import asyncio
import json

from petridish.config.loader import (
    CadenceParams, ModelProfile, PlanningParams, WorldConfig, WorldParams,
)
from petridish.engine.world import (
    AgentState, PlaceState, World, normalize_plan,
)
from petridish.engine.loop import TickLoop
from petridish.agents.runtime import AgentRuntime, _assemble_context
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


# ── Harness (test_w11b idiom) ────────────────────────────────────────────────

class ByAgentProvider:
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts: dict[str, list]):
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._pos: dict[str, int] = {}
        self.prompts: list[tuple[str, str]] = []
        self.calls = 0

    def set_world(self, world: object) -> None:
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
        self.calls += 1
        agent_id, system = self._extract(messages)
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
        planning=PlanningParams(enabled=True),
    )
    base.update(overrides)
    return WorldParams(**base)


def _default_places() -> list[PlaceState]:
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="commons", name="Commons", x=5, y=5, kind="wild"),
        PlaceState(id="shack", name="The Shack", x=10, y=10, kind="home"),
    ]


def _agent(aid: str, name: str, location: str = "plaza",
           energy: float = 80.0, credits: int = 20,
           tier: str = "protagonist") -> AgentState:
    return AgentState(id=aid, name=name, personality="", profile="mock",
                      location=location, energy=energy, credits=credits,
                      cadence_tier=tier)


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
    return loop, world, repo, runtime, provider, broadcast


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
PLAN_REV = {
    "goal": "Open a bakery at the market",
    "steps": ["gather flour at the commons", "work at the market", "sell bread"],
    "reason": "I am hungry and broke",
}


# ── 1. Plan state — normalize_plan totality + additive snapshot round-trip ────

def test_normalize_plan_is_total_and_bounds():
    assert normalize_plan(None) is None
    assert normalize_plan("nope") is None
    assert normalize_plan({}) is None
    assert normalize_plan({"goal": "x"}) is None              # no steps
    assert normalize_plan({"goal": "  ", "steps": ["a"]}) is None  # empty goal
    assert normalize_plan({"goal": "g", "steps": []}) is None     # no steps
    assert normalize_plan({"goal": "g", "steps": [""]}) is None   # all blank
    p = normalize_plan({"goal": "g", "steps": ["a", "", "b"], "current_step": 9})
    assert p["steps"] == ["a", "b"]               # blanks dropped
    assert p["current_step"] == 1                  # clamped to len-1
    assert p["stale"] is False and p["made_tick"] == 0
    # caps
    big = normalize_plan({"goal": "G" * 500, "steps": ["S" * 500] + ["s"] * 20})
    assert len(big["goal"]) == 200
    assert len(big["steps"]) == 8 and len(big["steps"][0]) == 120


def test_snapshot_round_trip_without_plan_is_byte_identical():
    """A plan-free world keeps the exact prior agent dict shape (no `plan` key)."""
    ada = _agent("agent_ada", "Ada")
    world = World(params=_params(), places=_default_places(), agents=[ada])
    snap = world.to_snapshot()
    assert "plan" not in snap["agents"][0], "plan-free agent must omit the key"
    restored = World.from_snapshot(snap)
    assert restored.agents["agent_ada"].plan is None
    assert restored.to_snapshot()["agents"][0] == snap["agents"][0]


def test_snapshot_round_trip_with_plan_preserves_it():
    ada = _agent("agent_ada", "Ada")
    ada.plan = normalize_plan({**PLAN_REV, "plan_id": "p1", "made_tick": 7})
    world = World(params=_params(), places=_default_places(), agents=[ada])
    snap = world.to_snapshot()
    assert snap["agents"][0]["plan"]["goal"] == "Open a bakery at the market"
    assert snap["agents"][0]["plan"]["plan_id"] == "p1"
    # to → from → to is byte-stable (EM-155 fork/replay guarantee).
    once = world.to_snapshot()
    twice = World.from_snapshot(once).to_snapshot()
    assert twice["agents"][0]["plan"] == once["agents"][0]["plan"]


def test_pre_em223_snapshot_restores_plan_none():
    """An agent dict lacking `plan` (every pre-EM-223 snapshot) restores None."""
    legacy = {
        "agents": [{"id": "agent_ada", "name": "Ada", "personality": "",
                    "profile": "mock", "location": "plaza", "energy": 80.0,
                    "credits": 20}],
        "places": [{"id": "plaza", "name": "Plaza", "x": 0, "y": 0,
                    "kind": "social"}],
        "tick": 5, "day": 0, "round": 0,
    }
    restored = World.from_snapshot(legacy)
    assert restored.agents["agent_ada"].plan is None


# ── 2. Plan block in context — rides the next prompt; gated on enabled ────────

def test_plan_revision_creates_plan_and_block_rides_next_prompt():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [ada],
        {"ada": [{"action": "idle", "args": {}, "plan_revision": PLAN_REV}, IDLE]},
    )
    asyncio.run(_drive(loop, world, 2))
    assert world.agents["agent_ada"].plan["goal"] == "Open a bakery at the market"
    p2 = provider.prompts[1][1]
    assert "YOUR CURRENT PLAN" in p2
    assert "Open a bakery at the market" in p2
    assert "not an order" in p2                       # invites abandonment
    # slotted AFTER commitments, BEFORE beliefs
    assert p2.index("YOUR CURRENT PLAN") < p2.index("YOUR BELIEFS")
    # the FIRST prompt had no plan block yet (just the creation invite)
    assert "YOUR CURRENT PLAN" not in provider.prompts[0][1]
    assert "no plan yet" in provider.prompts[0][1]


def test_planning_disabled_ignores_plan_revision_and_is_byte_silent():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(planning=PlanningParams(enabled=False)), [ada],
        {"ada": [{"action": "idle", "args": {}, "plan_revision": PLAN_REV}, IDLE]},
    )
    asyncio.run(_drive(loop, world, 2))
    assert world.agents["agent_ada"].plan is None
    assert repo.get_events(loop._run_id, kinds=["plan_revised"]) == []
    assert all(
        "CURRENT PLAN" not in p and "no plan yet" not in p
        for _, p in provider.prompts
    )


# ── 3. plan_revised event — persists + broadcasts, zero extra calls (5a) ──────

def test_plan_revised_persists_broadcasts_with_zero_extra_calls():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [ada],
        {"ada": [{"action": "say", "args": {"text": "a plan!"},
                  "plan_revision": PLAN_REV}]},
    )
    asyncio.run(_drive(loop, world, 1))
    # ONE chat() call for the turn — the plan rode the SAME single response.
    assert provider.calls == 1
    made = repo.get_events(loop._run_id, kinds=["plan_revised"])
    assert len(made) == 1
    ev = made[0]
    assert ev["actor_id"] == "agent_ada"
    assert ev["payload"]["goal"] == "Open a bakery at the market"
    assert ev["payload"]["steps"][0] == "gather flour at the commons"
    assert ev["payload"]["reason"] == "I am hungry and broke"
    assert ev["payload"]["old_plan_id"] is None
    assert ev["payload"]["plan_id"]
    assert "Ada plans:" in ev["text"]
    assert any(
        isinstance(m, dict) and m.get("kind") == "plan_revised" for m in broadcast
    ), "plan_revised must broadcast"


def test_revising_an_existing_plan_chains_old_plan_id():
    ada = _agent("agent_ada", "Ada")
    rev2 = {"goal": "Become mayor", "steps": ["campaign", "win"], "reason": "ambition"}
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [ada],
        {"ada": [
            {"action": "idle", "args": {}, "plan_revision": PLAN_REV},
            {"action": "idle", "args": {}, "plan_revision": rev2},
        ]},
    )
    asyncio.run(_drive(loop, world, 2))
    made = repo.get_events(loop._run_id, kinds=["plan_revised"])
    assert len(made) == 2
    assert made[1]["payload"]["old_plan_id"] == made[0]["payload"]["plan_id"]
    assert world.agents["agent_ada"].plan["goal"] == "Become mayor"


def test_malformed_plan_revision_never_fails_the_turn():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [ada],
        {"ada": [{"action": "forage", "args": {}, "plan_revision": {"goal": "x"}}]},
    )
    asyncio.run(_drive(loop, world, 1))
    assert world.agents["agent_ada"].plan is None       # popped — no plan
    assert repo.get_events(loop._run_id, kinds=["plan_revised"]) == []
    assert repo.get_events(loop._run_id, kinds=["parse_failure"]) == []
    # the forage still resolved (emits `economy`) — the malformed plan never
    # cost the turn.
    assert repo.get_events(loop._run_id, kinds=["economy"]), "forage resolved"


def test_step_pointer_advances_on_successful_nontalk_resolution():
    ada = _agent("agent_ada", "Ada", location="market")  # market is a work place
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [ada],
        {"ada": [
            {"action": "idle", "args": {}, "plan_revision":
                {"goal": "earn", "steps": ["work hard", "rest", "celebrate"]}},
            {"action": "work", "args": {}},     # non-talk success → advance to 1
        ]},
    )
    asyncio.run(_drive(loop, world, 2))
    assert world.agents["agent_ada"].plan["current_step"] == 1


# ── 4. Plan-aware reflex bias — zero-call, re-orders only (Unit 4) ────────────

def _bg_with_plan(steps, current_step=0, **planning):
    bg = _agent("agent_bo", "Bo", location="plaza", tier="background")
    p = dict(enabled=True)
    p.update(planning)
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(planning=PlanningParams(**p),
                cadence=CadenceParams(spontaneity_chance=0.0)),
        [bg], {"bo": [IDLE]},
    )
    world.agents["agent_bo"].plan = normalize_plan(
        {"goal": "g", "plan_id": "p", "made_tick": 0,
         "steps": steps, "current_step": current_step})
    return loop, world, repo, runtime, provider


def test_reflex_biases_toward_current_plan_step_place():
    loop, world, repo, runtime, provider = _bg_with_plan(
        ["head to the commons", "forage"])
    pick = runtime._reflex_pick(world.agents["agent_bo"])
    assert pick == {"action": "move_to", "args": {"place": "commons"}}


def test_reflex_no_plan_uses_seeded_rotation_unchanged():
    bg = _agent("agent_bo", "Bo", location="plaza", tier="background")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(), [bg], {"bo": [IDLE]},
    )
    pick = runtime._reflex_pick(world.agents["agent_bo"])
    assert pick["action"] in ("forage", "move_to")
    if pick["action"] == "move_to":
        assert pick["args"]["place"] != "commons"     # only home places rotate


def test_reflex_bias_off_when_flag_disabled():
    loop, world, repo, runtime, provider = _bg_with_plan(
        ["head to the commons"], reflex_bias=False)
    pick = runtime._reflex_pick(world.agents["agent_bo"])
    assert not (pick["action"] == "move_to"
                and pick["args"].get("place") == "commons")


# ── 5. The spontaneity floor is provably untouched by plan state ─────────────

def test_plan_mutation_leaves_reflex_streak_and_floor_untouched():
    loop, world, repo, runtime, provider = _bg_with_plan(
        ["go to the commons", "forage"])
    # Turn 1 is always salient (first_turn baseline) → one LLM turn, streak reset
    # to 0. Turn 2 has nothing new → the reflex path (zero calls); the plan biases
    # the pick but must NOT touch the streak / salience / spontaneity floor.
    asyncio.run(_drive(loop, world, 2))
    assert provider.calls == 1, \
        "only the first (first_turn-salient) turn calls the LLM — the plan adds none"
    assert world.agents["agent_bo"].reflex_streak == 1, \
        "the reflex turn incremented the streak normally — the plan never altered it"

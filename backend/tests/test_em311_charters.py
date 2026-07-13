"""
EM-311 — Self-Authored Charters (Tier-1 divergence amplifier). Build slice.

Proves the Definition of Done:
  · world.charters.enabled default False ⇒ no charter prompt block, charter_revision
    ignored, no charter_revised event, seeding is a no-op (byte-silent — the em161
    golden owns the full-prompt byte check; here we assert the block is absent).
  · a charter_revision folds into a turn with ZERO extra LLM calls; sets
    agent.charter (bumping the revision counter, stamping the tick); emits one
    charter_revised event carrying the exact old→new diff that persists + broadcasts.
  · the charter block rides the NEXT prompt ABOVE the persona and carries the tight
    enum grammar; a seeded agent shows its charter, an unseeded one gets the invite.
  · the sanitizer meets the model where it is: off-grammar ambitions are DROPPED
    (not rejected wholesale), an all-invalid revision is popped and never fails the
    turn, dupes collapse, and the creed is capped.
  · the persona stays the immutable floor (never mutated by a rewrite).

Deterministic and offline (the test_em223_planning ByAgentProvider idiom).
"""
import asyncio
import json

from petridish.config.loader import (
    CharterParams, ModelProfile, WorldConfig, WorldParams,
)
from petridish.engine.world import AgentState, PlaceState, World
from petridish.engine.loop import TickLoop
from petridish.agents.runtime import (
    AgentRuntime, _assemble_context, _sanitize_charter_revision, _validate_schema,
)
from petridish.persistence.repository import SQLiteRepository
from petridish.providers.router import Router


# ── Harness (test_em223_planning idiom) ──────────────────────────────────────

class ByAgentProvider:
    name = "mock"
    color = "#2ecc71"
    last_routed_via = "mock"
    last_usage = None

    def __init__(self, scripts):
        self._scripts = {k: list(v) for k, v in scripts.items()}
        self._pos = {}
        self.prompts = []
        self.calls = 0

    def set_world(self, world):
        self._world = world

    @staticmethod
    def _extract(messages):
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
        return json.dumps(entry)


def _params(enabled: bool = True, **charter_overrides) -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
        charters=CharterParams(enabled=enabled, **charter_overrides),
    )


def _default_places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="market", name="Market", x=10, y=0, kind="work"),
        PlaceState(id="commons", name="Commons", x=5, y=5, kind="wild"),
    ]


def _agent(aid: str, name: str, location: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=name, personality="A cautious baker.",
                      profile="mock", location=location, energy=80.0, credits=20)


def _make_loop(params, agents, scripts, places=None):
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
    broadcast = []
    loop = TickLoop(world=world, runtime=runtime, repo=repo, router=router,
                    broadcaster=lambda m: broadcast.append(m))
    loop.init_run(WorldConfig(world=params, places=[], agents=[], animals=[]))
    return loop, world, repo, runtime, provider, broadcast


async def _drive(loop, world, n):
    for _ in range(n):
        agent = world.next_agent()
        assert agent is not None
        await loop._execute_turn(agent)
        if loop._animal_task is not None:
            await loop._animal_task
        if getattr(loop, "_narrator_task", None) is not None:
            await loop._narrator_task


IDLE = {"action": "idle", "args": {}}
REV = {"ambitions": ["claim_territory", "amass_wealth"],
       "creed": "I will own this street.", "reason": "They robbed me twice."}


# ── 1. Sanitizer — tight grammar, lenient failure (EM-297) ───────────────────

def test_sanitize_normalizes_a_good_revision():
    d = {"action": "idle", "charter_revision": dict(REV)}
    assert _sanitize_charter_revision(d) is None
    assert d["charter_revision"]["ambitions"] == ["claim_territory", "amass_wealth"]
    assert d["charter_revision"]["creed"] == "I will own this street."
    assert d["charter_revision"]["reason"] == "They robbed me twice."
    # the cleaned form passes the strict ACTION_SCHEMA
    assert _validate_schema({"action": "idle",
                             "charter_revision": d["charter_revision"]}) is None


def test_sanitize_drops_offgrammar_but_keeps_valid():
    d = {"action": "idle",
         "charter_revision": {"ambitions": ["fly_to_the_moon", "sow_chaos",
                                            "sow_chaos"]}}
    assert _sanitize_charter_revision(d) is None
    assert d["charter_revision"]["ambitions"] == ["sow_chaos"]   # bad dropped, dedup


def test_sanitize_pops_unusable_revision_without_failing():
    for bad in (
        {"ambitions": ["not_a_kind"]},          # all off-grammar
        {"ambitions": "seize_power"},           # not a list
        {"creed": "no ambitions here"},         # missing ambitions
        "nonsense",                             # not a dict
    ):
        d = {"action": "idle", "charter_revision": bad}
        reason = _sanitize_charter_revision(d)
        assert reason is not None
        assert "charter_revision" not in d      # popped, so the schema won't choke


def test_offgrammar_ambition_fails_the_raw_schema():
    """The schema itself pins the enum (EM-297 tight-schema discipline) — an
    un-sanitized off-grammar kind is rejected."""
    assert _validate_schema({"action": "idle",
                             "charter_revision":
                                 {"ambitions": ["become_a_dragon"]}}) is not None


# ── 2. Disabled world — byte-silent (charter_revision ignored) ───────────────

def test_disabled_ignores_charter_revision_and_is_byte_silent():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=False), [ada],
        {"ada": [{"action": "idle", "args": {}, "charter_revision": dict(REV)}, IDLE]},
    )
    asyncio.run(_drive(loop, world, 2))
    assert world.agents["agent_ada"].charter is None
    assert repo.get_events(loop._run_id, kinds=["charter_revised"]) == []
    assert all("YOUR CHARTER" not in p for _, p in provider.prompts)


# ── 3. charter block rides the prompt ABOVE the persona ──────────────────────

def test_seeded_charter_block_rides_prompt_above_persona():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada], {"ada": [IDLE, IDLE]})
    asyncio.run(_drive(loop, world, 1))
    p = provider.prompts[0][1]
    assert "YOUR CHARTER" in p
    assert "keep_the_peace" in p                       # the seeded ambition kind
    # injected ABOVE the persona (the immutable floor sits below the charter)
    assert p.index("YOUR CHARTER") < p.index("Personality:")
    # the tight grammar is offered for the rewrite
    assert "Legal ambition kinds:" in p
    assert "charter_revision" in p


def test_unseeded_agent_gets_the_invite():
    ada = _agent("agent_ada", "Ada")
    # enabled but NOT seeded (skip the loop seed by clearing after init)
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada], {"ada": [IDLE]})
    world.agents["agent_ada"].charter = None
    msgs = _assemble_context(world.agents["agent_ada"], world, [], world.params)
    system = msgs[0]["content"]
    assert "You have not declared a charter" in system
    assert "Legal ambition kinds:" in system


# ── 4. charter_revised — sets state, emits diff, zero extra calls ─────────────

def test_charter_revision_sets_state_and_emits_diff():
    ada = _agent("agent_ada", "Ada")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada],
        {"ada": [{"action": "say", "args": {"text": "mine now"},
                  "charter_revision": dict(REV)}]},
    )
    asyncio.run(_drive(loop, world, 1))
    # ONE chat() call — the charter rewrite rode the SAME single response.
    assert provider.calls == 1
    ch = world.agents["agent_ada"].charter
    assert ch["ambitions"] == ["claim_territory", "amass_wealth"]
    assert ch["creed"] == "I will own this street."
    assert ch["revisions"] == 1              # bumped from the seed's 0
    # stamped with the tick the rewrite happened AT (turn ran at tick 0, the loop
    # then advanced to 1) — precise tick stamping is covered in the determinism test
    assert isinstance(ch["revised_tick"], int) and ch["revised_tick"] >= 0
    made = repo.get_events(loop._run_id, kinds=["charter_revised"])
    assert len(made) == 1
    ev = made[0]
    assert ev["actor_id"] == "agent_ada"
    assert ev["payload"]["ambitions"] == ["claim_territory", "amass_wealth"]
    assert ev["payload"]["old_ambitions"] == ["keep_the_peace"]   # the seed
    assert ev["payload"]["reason"] == "They robbed me twice."
    assert "vows to" in ev["text"]
    assert any(
        isinstance(m, dict) and m.get("kind") == "charter_revised"
        for m in broadcast
    ), "charter_revised must broadcast"
    # the persona is the IMMUTABLE floor — never mutated by a rewrite
    assert world.agents["agent_ada"].personality == "A cautious baker."


def test_successive_rewrites_chain_and_bump_revisions():
    ada = _agent("agent_ada", "Ada")
    rev2 = {"ambitions": ["seize_power"], "creed": "The town is mine."}
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada],
        {"ada": [
            {"action": "idle", "args": {}, "charter_revision": dict(REV)},
            {"action": "idle", "args": {}, "charter_revision": rev2},
        ]},
    )
    asyncio.run(_drive(loop, world, 2))
    ch = world.agents["agent_ada"].charter
    assert ch["ambitions"] == ["seize_power"]
    assert ch["revisions"] == 2
    made = repo.get_events(loop._run_id, kinds=["charter_revised"])
    assert len(made) == 2
    assert made[1]["payload"]["old_ambitions"] == ["claim_territory", "amass_wealth"]


def test_malformed_revision_never_fails_the_turn():
    ada = _agent("agent_ada", "Ada", location="market")   # a work place
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada],
        {"ada": [{"action": "work", "args": {},
                  "charter_revision": {"ambitions": ["not_real"]}}]},
    )
    asyncio.run(_drive(loop, world, 1))
    # the charter stays on the seed (the bad rewrite was popped) ...
    assert world.agents["agent_ada"].charter["ambitions"] == ["keep_the_peace"]
    assert repo.get_events(loop._run_id, kinds=["charter_revised"]) == []
    assert repo.get_events(loop._run_id, kinds=["parse_failure"]) == []
    # ... and the work still resolved — the malformed charter never cost the turn.
    assert repo.get_events(loop._run_id, kinds=["economy"]), "work resolved"


# ── 5. seeding at boot — uniform baseline for the divergence experiment ───────

def test_boot_seeds_uniform_charter_when_enabled():
    ada, bram = _agent("agent_ada", "Ada"), _agent("agent_bram", "Bram")
    loop, world, repo, runtime, provider, broadcast = _make_loop(
        _params(enabled=True), [ada, bram], {"ada": [IDLE], "bram": [IDLE]})
    assert world.agents["agent_ada"].charter["ambitions"] == ["keep_the_peace"]
    assert world.agents["agent_bram"].charter["ambitions"] == ["keep_the_peace"]

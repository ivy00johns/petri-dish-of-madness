# backend/tests/test_em251_schema.py
"""EM-251 — Culture transmission verb prompt/registry surface (the EM-108
menu/resolution-agreement rule, mirroring test_em258_schema).

The two culture verbs (spread_rumor / send_letter) surface on the menu ONLY
when comm is enabled (world.comm.enabled; default OFF). A default-OFF world
adds NO line — the FULL system prompt stays byte-identical (the em161-golden
guarantee; the static ACTION_SCHEMA/TOOL_REGISTRY entries are identical on
both sides so they cancel). spread_rumor is offered only with a co-located
target; send_letter is the first NON-co-located channel (any other living
citizen, present or absent).
"""
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import (
    _assemble_context, ACTION_SCHEMA, TOOL_REGISTRY, _TARGETED_ACTIONS,
)


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _a(aid: str, place: str = "plaza") -> AgentState:
    return AgentState(id=aid, name=aid.title(), personality="", profile="mock",
                      location=place, energy=80.0, credits=20)


def _world(comm: bool = True, agents: list[AgentState] | None = None) -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
              PlaceState(id="market", name="Market", x=1, y=0, kind="work")]
    w = World(params=_params(), places=places,
              agents=agents if agents is not None
              else [_a("ada"), _a("bram"), _a("cyn")])
    if comm:
        w.params.comm = {"enabled": True}
    return w


def _sys(agent, world) -> str:
    msgs = _assemble_context(agent, world, [], world.params)
    return next(m["content"] for m in msgs if m["role"] == "system")


# ── static contract: registry + schema entries exist (they cancel in golden) ──

def test_both_verbs_registered_reflex_no_gates():
    for verb in ("spread_rumor", "send_letter"):
        meta = TOOL_REGISTRY[verb]
        assert meta["tier"] == "reflex"
        assert meta["location_gate"] is None       # co-location is world-enforced
        assert meta["agreement_gate"] is None


def test_both_verbs_in_the_action_enum():
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    assert "spread_rumor" in enum and "send_letter" in enum


def test_schema_requires_target_and_text():
    subs = ACTION_SCHEMA["allOf"]

    def _required(verb: str) -> list[str]:
        for clause in subs:
            if clause["if"]["properties"]["action"].get("const") == verb:
                return clause["then"]["properties"]["args"]["required"]
        raise AssertionError(f"no sub-schema for {verb}")

    assert _required("spread_rumor") == ["target"]
    assert _required("send_letter") == ["target", "text"]


def test_both_verbs_resolve_targets_by_name():
    # Both are name→id resolvable (send_letter permissively — it may address an
    # ABSENT agent), so the model can target by display name.
    assert "spread_rumor" in _TARGETED_ACTIONS
    assert "send_letter" in _TARGETED_ACTIONS


# ── the flag-OFF golden: the verbs leave no trace ────────────────────────────

def test_comm_off_prompt_never_names_the_verbs():
    w = _world(comm=False)
    sys = _sys(w.agents["ada"], w)
    for verb in ("spread_rumor", "send_letter"):
        assert f"{verb} " not in sys and f"{verb}(" not in sys


def test_comm_off_world_prompt_is_deterministic_control():
    # Two independent default (comm-OFF) worlds assemble the byte-identical
    # prompt — the additions introduce no nondeterminism when disabled.
    a = _sys(_world(comm=False).agents["ada"], _world(comm=False))
    b = _sys(_world(comm=False).agents["ada"], _world(comm=False))
    assert a == b


# ── the culture menu surfaces only when comm is enabled ──────────────────────

def _menu_lines(agent, world, prefix) -> list[str]:
    return [l.strip() for l in _sys(agent, world).split("\n")
            if l.strip().startswith(prefix)]


def test_spread_rumor_surfaces_only_with_a_co_located_target():
    w = _world()                                   # ada/bram/cyn all at plaza
    lines = _menu_lines(w.agents["ada"], w, "spread_rumor")
    assert len(lines) == 1
    assert "Bram" in lines[0] and "Cyn" in lines[0]
    # Alone at a place ⇒ no rumor line (nobody to whisper to).
    w.agents["bram"].location = "market"
    w.agents["cyn"].location = "market"
    assert _menu_lines(w.agents["ada"], w, "spread_rumor") == []


def test_send_letter_surfaces_for_absent_recipients_too():
    w = _world()
    w.agents["bram"].location = "market"           # elsewhere
    w.agents["cyn"].location = "market"
    lines = _menu_lines(w.agents["ada"], w, "send_letter")
    assert len(lines) == 1
    # Names citizens who are NOT co-located (the first absent-target channel).
    assert "Bram" in lines[0] and "Cyn" in lines[0]


def test_send_letter_absent_when_alone_in_the_world():
    w = _world(agents=[_a("ada")])
    assert _menu_lines(w.agents["ada"], w, "send_letter") == []

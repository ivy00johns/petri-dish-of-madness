# backend/tests/test_em253_schema.py
"""EM-253 — Culture lifecycle verb prompt/registry surface (the EM-108
menu/resolution-agreement rule, mirroring test_em251_schema).

create_meme / adopt_meme surface on the menu ONLY when comm is enabled
(world.comm.enabled; default OFF). A default-OFF world adds NO line — the FULL
system prompt stays byte-identical (the em161-golden guarantee; the static
ACTION_SCHEMA/TOOL_REGISTRY entries are identical on both sides so they cancel).
create_meme is always offered under comm (an author needs no audience);
adopt_meme is offered ONLY when a meme this agent does not already carry is in
circulation (the eligible-target gate).
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


def _menu_lines(agent, world, prefix) -> list[str]:
    return [l.strip() for l in _sys(agent, world).split("\n")
            if l.strip().startswith(prefix)]


# ── static contract: registry + schema entries exist (they cancel in golden) ──

def test_both_verbs_registered_reflex_no_gates():
    for verb in ("create_meme", "adopt_meme"):
        meta = TOOL_REGISTRY[verb]
        assert meta["tier"] == "reflex"
        assert meta["location_gate"] is None
        assert meta["agreement_gate"] is None


def test_both_verbs_in_the_action_enums():
    enum = ACTION_SCHEMA["properties"]["action"]["enum"]
    item_enum = (ACTION_SCHEMA["properties"]["actions"]["items"]
                 ["properties"]["action"]["enum"])
    for verb in ("create_meme", "adopt_meme"):
        assert verb in enum
        assert verb in item_enum


def test_schema_requires_text_and_meme_id():
    subs = ACTION_SCHEMA["allOf"]

    def _required(verb: str) -> list[str]:
        for clause in subs:
            if clause["if"]["properties"]["action"].get("const") == verb:
                return clause["then"]["properties"]["args"]["required"]
        raise AssertionError(f"no sub-schema for {verb}")

    assert _required("create_meme") == ["text"]
    assert _required("adopt_meme") == ["meme_id"]


def test_verbs_are_not_name_resolved_targets():
    # adopt_meme takes a meme_id (not an agent name); create_meme takes no
    # target — neither goes through the name→id agent resolver.
    assert "create_meme" not in _TARGETED_ACTIONS
    assert "adopt_meme" not in _TARGETED_ACTIONS


# ── the flag-OFF golden: the verbs leave no trace ────────────────────────────

def test_comm_off_prompt_never_names_the_verbs():
    w = _world(comm=False)
    sys = _sys(w.agents["ada"], w)
    for verb in ("create_meme", "adopt_meme"):
        assert f"{verb} " not in sys and f"{verb}(" not in sys


def test_comm_off_world_prompt_is_deterministic_control():
    a = _sys(_world(comm=False).agents["ada"], _world(comm=False))
    b = _sys(_world(comm=False).agents["ada"], _world(comm=False))
    assert a == b


# ── the culture-lifecycle menu surfaces only when comm is enabled ────────────

def test_create_meme_surfaces_whenever_comm_is_on():
    w = _world()
    lines = _menu_lines(w.agents["ada"], w, "create_meme")
    assert len(lines) == 1


def test_adopt_meme_surfaces_only_with_an_adoptable_meme():
    w = _world()
    # No memes yet ⇒ no adopt line.
    assert _menu_lines(w.agents["ada"], w, "adopt_meme") == []
    # A meme in circulation that ada does NOT carry ⇒ the line appears + names it.
    m = w.mint_meme("idea", "share the well", "bram")
    w._attach_meme(w.agents["bram"], m)
    lines = _menu_lines(w.agents["ada"], w, "adopt_meme")
    assert len(lines) == 1
    assert m.id in lines[0]


def test_adopt_meme_absent_when_agent_already_carries_every_meme():
    w = _world()
    m = w.mint_meme("idea", "already mine", "ada")
    w._attach_meme(w.agents["ada"], m)                    # ada carries the only meme
    assert _menu_lines(w.agents["ada"], w, "adopt_meme") == []

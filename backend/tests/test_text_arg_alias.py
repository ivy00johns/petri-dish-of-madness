"""
Text-arg aliasing (fix/feed-health) — models frequently emit spoken/written
content under `message`/`msg`/`content`/`body`/`speech`/`utterance`/`saying`
instead of the schema's `text`. `_fold_stray_top_level_into_args` already
folds a stray TOP-LEVEL `message` into `args`, so the turn VALIDATES — but
nothing mapped `args["message"]` -> `args["text"]`, so say/whisper/etc. read
an empty `text` and the agent spoke NOTHING (the `says: ""` symptom).

These are direct unit tests of `_normalize_args` (the test_arg_normalization
idiom: a bare World + AgentState, no loop/router/provider needed since
normalization is a pure in-place dict rewrite).
"""
from __future__ import annotations

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams
from petridish.agents.runtime import _normalize_args


def _make_params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5,
        turns_per_day=20,
        energy_decay_per_turn=0.0,
        starting_energy=80.0,
        starting_credits=20,
    )


def _bare_world() -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [
        AgentState(id="agent_ada_1", name="Ada", personality="", profile="mock",
                   location="plaza", energy=50, credits=5),
        AgentState(id="agent_bram_1", name="Bram", personality="", profile="mock",
                   location="plaza", energy=50, credits=5),
    ]
    return World(params=_make_params(), places=places, agents=agents)


def _actor(world: World) -> AgentState:
    return world.agents["agent_bram_1"]


# ══════════════════════════════════════════════════════════════════════════════
# The core bug: message/content/msg/body alias into args["text"]
# ══════════════════════════════════════════════════════════════════════════════

def test_whisper_message_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "whisper", "args": {"target": "Ada", "message": "hello"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "hello"
    # whisper is ALSO a targeted action — the target resolution must still run
    # alongside the new text alias (they used to share one elif branch).
    assert action["args"]["target"] == "agent_ada_1"


def test_say_content_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"content": "hi all"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "hi all"


def test_say_msg_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"msg": "greetings"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "greetings"


def test_say_body_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"body": "letter body text"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "letter body text"


def test_say_speech_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"speech": "a speech"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "a speech"


def test_say_utterance_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"utterance": "an utterance"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "an utterance"


def test_say_saying_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "say", "args": {"saying": "an old saying"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "an old saying"


# ══════════════════════════════════════════════════════════════════════════════
# First-write-wins: a real existing text is never clobbered
# ══════════════════════════════════════════════════════════════════════════════

def test_existing_nonempty_text_not_overwritten_by_stray_message():
    world = _bare_world()
    action = {"action": "say", "args": {"text": "real text", "message": "decoy"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "real text"


# ══════════════════════════════════════════════════════════════════════════════
# Non-text actions are left alone — no spurious text arg invented
# ══════════════════════════════════════════════════════════════════════════════

def test_move_to_stray_message_is_not_promoted_to_text():
    world = _bare_world()
    action = {"action": "move_to", "args": {"place": "plaza", "message": "irrelevant"}}
    _normalize_args(action, _actor(world), world)
    assert "text" not in action["args"]
    assert action["args"]["message"] == "irrelevant"


# ══════════════════════════════════════════════════════════════════════════════
# The other text-taking actions named in the bug report
# ══════════════════════════════════════════════════════════════════════════════

def test_post_billboard_message_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "post_billboard", "args": {"message": "notice: market opens at dawn"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "notice: market opens at dawn"


def test_send_letter_content_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "send_letter", "args": {"target": "Ada", "content": "dear Ada,"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "dear Ada,"
    assert action["args"]["target"] == "agent_ada_1"


def test_create_meme_msg_alias_resolves_to_text():
    world = _bare_world()
    action = {"action": "create_meme", "args": {"msg": "the sky is falling"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "the sky is falling"


def test_spread_rumor_message_alias_resolves_to_text():
    """spread_rumor's handler reads `rumor` OR `text`
    (args.get("rumor","") or args.get("text","")) — aliasing a stray
    `message` into `text` satisfies that fallback without touching `rumor`."""
    world = _bare_world()
    action = {"action": "spread_rumor", "args": {"target": "Ada", "message": "a wild rumor"}}
    _normalize_args(action, _actor(world), world)
    assert action["args"]["text"] == "a wild rumor"


def test_spread_rumor_existing_rumor_not_clobbered_by_stray_message():
    world = _bare_world()
    action = {"action": "spread_rumor",
              "args": {"target": "Ada", "rumor": "the real rumor", "message": "decoy"}}
    _normalize_args(action, _actor(world), world)
    # rumor wins in the handler's `rumor or text` fallback either way, but the
    # alias must not silently override a rumor the model deliberately sent.
    assert action["args"].get("rumor") == "the real rumor"
    assert action["args"].get("text") != "decoy"

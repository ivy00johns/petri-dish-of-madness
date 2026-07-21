"""
Schema-reject idle-fallback fix — fold stray top-level action params into args.

The chat feed showed repeated:
  ⚠ X failed to produce a valid action (idle fallback): schema error:
    Additional properties are not allowed ('zone_id' was unexpected)
(also 'message', 'target'). ACTION_SCHEMA's top-level `additionalProperties`
is False (by design — decision-trace fields must be declared), but models
sometimes emit a single-action response with the action's parameters FLAT at
the top level (`{"action": "whisper", "target": "Ada", "message": "hi"}`)
instead of nested under `args`. Those undeclared top-level keys hard-rejected
the WHOLE turn, violating the EM-066 ethos ("a misplaced field must NEVER
fail the turn") that the `args` object and `actions[]` items already honor.

`_fold_stray_top_level_into_args` moves any undeclared top-level key into
`args` IN PLACE, before `_validate_schema` runs, so a flat single-action
response validates instead of dying.
"""
from petridish.engine.world import World  # noqa: F401 — import order: engine before
# agents.runtime breaks a circular-import fragility (petridish.agents.runtime <->
# petridish.engine.loop) that bites when runtime is the FIRST module touched
# (see test_em311_charters.py for the same idiom).
from petridish.agents.runtime import (
    _DECLARED_TOP_LEVEL, _fold_stray_top_level_into_args, _validate_schema,
)


def test_flat_whisper_params_fold_into_args_and_validate():
    action_dict = {"action": "whisper", "target": "Ada", "message": "hi"}
    _fold_stray_top_level_into_args(action_dict)
    assert action_dict["args"] == {"target": "Ada", "message": "hi"}
    assert "target" not in action_dict
    assert "message" not in action_dict
    assert _validate_schema(action_dict) is None


def test_stray_zone_id_folds_into_args_and_validates():
    action_dict = {"action": "propose_project", "zone_id": "zone_7",
                   "args": {"name": "Well", "kind": "well"}}
    _fold_stray_top_level_into_args(action_dict)
    # zone_id lands in args alongside the existing (declared) args.
    assert action_dict["args"]["zone_id"] == "zone_7"
    assert action_dict["args"]["name"] == "Well"
    assert "zone_id" not in action_dict
    assert _validate_schema(action_dict) is None


def test_existing_args_key_not_clobbered():
    action_dict = {"action": "give", "amount": 5, "args": {"target": "Bo"}}
    _fold_stray_top_level_into_args(action_dict)
    assert action_dict["args"] == {"target": "Bo", "amount": 5}
    assert "amount" not in action_dict
    assert _validate_schema(action_dict) is None


def test_existing_args_key_wins_over_stray_duplicate():
    # If the stray top-level key collides with an existing args key, the
    # existing args value wins (setdefault semantics) — the model's more
    # deliberate nested value is trusted over the flat duplicate.
    action_dict = {"action": "give", "target": "Zed", "args": {"target": "Bo"}}
    _fold_stray_top_level_into_args(action_dict)
    assert action_dict["args"]["target"] == "Bo"
    assert _validate_schema(action_dict) is None


def test_clean_response_is_unchanged_by_fold():
    action_dict = {"action": "whisper", "args": {"target": "Ada", "text": "hi"},
                   "thought": "let's talk"}
    before = dict(action_dict)
    _fold_stray_top_level_into_args(action_dict)
    assert action_dict == before
    assert _validate_schema(action_dict) is None


def test_declared_trace_fields_stay_top_level_not_folded():
    action_dict = {
        "action": "idle",
        "thought": "watching",
        "mood": "calm",
        "reasoning": "nothing to do right now",
    }
    _fold_stray_top_level_into_args(action_dict)
    assert action_dict["thought"] == "watching"
    assert action_dict["mood"] == "calm"
    assert action_dict["reasoning"] == "nothing to do right now"
    assert "args" not in action_dict
    assert _validate_schema(action_dict) is None


def test_declared_top_level_set_matches_schema_properties():
    # Sanity: the derivation from ACTION_SCHEMA stays in sync — a declared key
    # like 'bond' must never be treated as stray.
    assert "action" in _DECLARED_TOP_LEVEL
    assert "actions" in _DECLARED_TOP_LEVEL
    assert "args" in _DECLARED_TOP_LEVEL
    assert "bond" in _DECLARED_TOP_LEVEL
    action_dict = {"action": "idle", "bond": {"target": "Ada", "type": "friend"}}
    _fold_stray_top_level_into_args(action_dict)
    assert "bond" in action_dict
    assert "args" not in action_dict

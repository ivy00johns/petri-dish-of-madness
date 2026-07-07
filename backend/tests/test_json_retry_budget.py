"""The parse-failure length-retry must give rerouted reasoning models real room
to finish the JSON (they truncate at the old 4096). Both mirrored floors -> 8192."""
import petridish.engine.world  # noqa: F401 — import-order guard (runtime circular import)
from petridish.agents.runtime import _LENGTH_RETRY_TOKEN_FLOOR, _retry_max_tokens
from petridish.providers.router import _LANE_BOOST_FLOOR


def test_length_retry_floor_is_8192():
    assert _LENGTH_RETRY_TOKEN_FLOOR == 8192


def test_floors_stay_mirrored():
    assert _LENGTH_RETRY_TOKEN_FLOOR == _LANE_BOOST_FLOOR


def test_truncated_retry_reaches_8192_from_base_1024():
    # base 1024*4 = 4096 (the old cap the reasoners truncated at); the 8192 floor
    # lifts the length-truncated retry to real room. A non-truncated turn unchanged.
    assert _retry_max_tokens(1024, {"finish_reason": "length"}) == 8192
    assert _retry_max_tokens(1024, {"finish_reason": "stop"}) == 1024

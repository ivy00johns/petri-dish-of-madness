"""Feed-health regression: the comm notification/coherence knobs must be PARSED
from the world.yaml comm block, not silently stuck at their dataclass defaults.

The aggregation knobs (mutation_notable_cap / death_notable_virality) were added
to CommunicationParams + world.yaml but initially NOT wired into `_parse_comm`,
so a user changing them in the yaml (or the Lab Setup panel) would have had the
change silently ignored — the exact "why isn't my config taking effect?" bug the
whole feed-health pass exists to kill. This pins every feed-health knob to its
yaml value.
"""
from petridish.config.loader import _parse_comm, CommunicationParams


def test_feed_health_knobs_honor_yaml_over_dataclass_defaults():
    # Deliberately non-default values so a stripped parser (returning defaults)
    # would fail this assertion.
    p = _parse_comm({
        "enabled": True,
        "mutation_notable_cap": 5,
        "death_notable_virality": 9,
        "max_drift_generations": 7,
        "decay_ticks": 24,
    })
    assert p.mutation_notable_cap == 5
    assert p.death_notable_virality == 9
    assert p.max_drift_generations == 7
    assert p.decay_ticks == 24


def test_absent_comm_knobs_fall_back_to_defaults():
    d = CommunicationParams()
    p = _parse_comm({"enabled": True})  # knobs absent -> dataclass defaults
    assert p.mutation_notable_cap == d.mutation_notable_cap
    assert p.death_notable_virality == d.death_notable_virality
    assert p.max_drift_generations == d.max_drift_generations


def test_malformed_knob_falls_back_not_raises():
    p = _parse_comm({"enabled": True, "mutation_notable_cap": "not-an-int"})
    assert p.mutation_notable_cap == CommunicationParams().mutation_notable_cap

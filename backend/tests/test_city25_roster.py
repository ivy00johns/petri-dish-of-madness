"""
Wave D2 / B4 — EM-165 city25 roster pins (config/world.city25.yaml).

The 25-agent city cast ships as a documented VARIANT config (the orchestrator
decision at gate time): config/world.yaml keeps the 3-agent day-to-day cast,
and config/world.city25.yaml carries the full city roster. These tests pin
the variant's contract so a future edit can't silently break it:

  - parses through the REAL loader (`_parse_world`) into exactly 25 distinct
    agents with the contracted tier split (5 protagonist / 8 supporting /
    12 background);
  - every seat references a real (non-mock) lane from config/profiles.yaml,
    all 7 real lanes are used, and the fast/high-rpd lanes carry the most
    background seats (the free-scale casting rule);
  - every agent stands on a place that exists;
  - the `world:` block (physics, pacing, cadence, budget guard) is IDENTICAL
    to config/world.yaml except agent_count — the variant changes the CAST,
    never the world (additive-only law);
  - the protagonist five are the named cast (Ada/Bram/Cleo + the run-248
    spawn archetypes Vesper/Marrow) and they all wake in the plaza.

House import idiom: engine.world before agents.runtime (no runtime needed
here, but the engine import asserts the fixture loads under it).
"""
from __future__ import annotations

import collections
import dataclasses
from pathlib import Path

import yaml

from petridish.engine.world import World  # noqa: F401  (house import idiom)
from petridish.config.loader import _parse_world, _parse_profiles, _parse_animal_seeds

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

REAL_LANES = {
    "gemini-flash", "qwen-next", "deepseek-pro", "groq-llama",
    "cerebras-glm", "mistral-small", "kimi",
}
# the high-cap / fast lanes that must carry most background seats
FAST_LANES = {"cerebras-glm", "gemini-flash", "groq-llama"}


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG_DIR / name).read_text())


def _city25():
    return _parse_world(_load("world.city25.yaml"))


def test_city25_parses_to_25_distinct_tiered_agents():
    params, places, agents = _city25()
    assert params.agent_count == 25
    assert len(agents) == 25
    names = [a.name for a in agents]
    assert len(set(names)) == 25, f"duplicate names: {names}"
    tiers = collections.Counter(a.cadence_tier for a in agents)
    assert tiers == {"protagonist": 5, "supporting": 8, "background": 12}


def test_city25_lanes_real_complete_and_background_weighted_fast():
    params, places, agents = _city25()
    profile_names = {p.name for p in _parse_profiles(_load("profiles.yaml"))}
    lanes = collections.Counter(a.profile for a in agents)
    # every seat on a registered, REAL (non-mock) lane; all 7 lanes cast
    assert set(lanes) == REAL_LANES
    assert set(lanes) <= profile_names
    assert "mock" not in lanes
    # free-scale casting rule: fast/high-rpd lanes carry most background seats
    bg = collections.Counter(
        a.profile for a in agents if a.cadence_tier == "background")
    fast_share = sum(bg[l] for l in FAST_LANES) / sum(bg.values())
    assert fast_share >= 2 / 3, f"background fast-lane share {fast_share:.2f}"
    # the scarcest lane (qwen-next, ~50 rpd) carries exactly one seat
    assert lanes["qwen-next"] == 1


def test_city25_locations_all_exist():
    params, places, agents = _city25()
    place_ids = {p.id for p in places}
    bad = [(a.name, a.location) for a in agents if a.location not in place_ids]
    assert not bad, f"agents on unknown places: {bad}"


def test_city25_protagonists_are_the_named_cast_in_the_plaza():
    params, places, agents = _city25()
    protagonists = {a.name: a for a in agents if a.cadence_tier == "protagonist"}
    assert set(protagonists) == {"Ada", "Bram", "Cleo", "Vesper", "Marrow"}
    assert all(a.location == "plaza" for a in protagonists.values())
    # five protagonists on five DISTINCT lanes (one slow lane can't stall the
    # whole every-round tier)
    assert len({a.profile for a in protagonists.values()}) == 5


def test_city25_world_block_identical_to_default_except_agent_count():
    p25, places25, _ = _city25()
    p5, places5, _ = _parse_world(_load("world.yaml"))
    assert p5.agent_count == 5 and p25.agent_count == 25
    assert dataclasses.replace(p25, agent_count=p5.agent_count) == p5, (
        "world.city25.yaml must only change the cast — physics/pacing/"
        "cadence/guard settings must stay byte-equal to world.yaml")
    assert places25 == places5, "the city grid must be identical"
    assert (_parse_animal_seeds(_load("world.city25.yaml"))
            == _parse_animal_seeds(_load("world.yaml"))), (
        "the seed critters must be identical")

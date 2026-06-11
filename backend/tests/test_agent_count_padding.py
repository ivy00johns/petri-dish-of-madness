"""
EM-175 — `world.agent_count` roster padding (config/world.yaml promised
"used if `agents:` not fully specified" but the padding was never built; the
world booted exactly the `agents:` list).

Pins the loader-seam contract (load_config in petridish/config/loader.py):

  - agent_count > len(agents)  ⇒ pad from the persona library
    (config/personas.yaml): card name/personality, the card's
    suggested_profile when registered, default place (plaza), and
    cadence_tier "supporting" (hand-listed cast keeps its declared tier);
  - persona-name collisions with listed agents are skipped (case-insensitive);
  - library exhausted ⇒ numbered Citizen-N fill (neutral personality,
    round-robin across non-mock profiles) so agent_count is ALWAYS honored;
  - agent_count <= len(agents) ⇒ the list is returned UNCHANGED (never
    truncates — the hand-authored list wins);
  - the mock profile_override (the test-suite path) applies to padded agents;
  - the shipped config (agent_count 5, 3 listed) boots 5 agents;
  - the city25 variant (25 listed == 25) is a no-op through the same seam.

House import idiom: engine.world before agents.runtime.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from petridish.engine.world import World  # noqa: F401  (house import idiom)
from petridish.config.loader import load_config, load_personas

REPO_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

# Minimal fixture profiles: two real (non-mock) lanes + the mock lane.
TMP_PROFILES = """
profiles:
  - { name: alpha, adapter: openai, model_id: m-alpha }
  - { name: beta,  adapter: openai, model_id: m-beta }
  - { name: mock,  adapter: mock,   model_id: mock }
"""

TMP_PERSONAS = """
personas:
  - { name: Mox,    archetype: Conspiracist, personality: "Sees cabals.",  suggested_profile: beta }
  - { name: Vesper, archetype: Founder,      personality: "Pitches schemes.", suggested_profile: nope-not-a-profile }
  - { name: Hazel,  archetype: Prepper,      personality: "Hoards cans.",  suggested_profile: alpha }
"""

TMP_PLACES = """
places:
  - { id: townhall, name: Hall,  x: 100, y: 100, kind: governance }
  - { id: plaza,    name: Plaza, x: 500, y: 500, kind: social }
"""

TMP_AGENTS_3 = """
agents:
  - { name: Ada,  personality: "engineer",  profile: alpha, location: plaza }
  - { name: Bram, personality: "trader",    profile: beta,  location: plaza, cadence_tier: supporting }
  - { name: Cleo, personality: "organizer", profile: alpha, location: townhall }
"""


def _write_cfg(tmp_path: Path, agent_count: int,
               agents_yaml: str = TMP_AGENTS_3,
               personas_yaml: str | None = TMP_PERSONAS) -> Path:
    (tmp_path / "world.yaml").write_text(
        f"world:\n  agent_count: {agent_count}\n" + TMP_PLACES + agents_yaml
    )
    (tmp_path / "profiles.yaml").write_text(TMP_PROFILES)
    if personas_yaml is not None:
        (tmp_path / "personas.yaml").write_text(personas_yaml)
    return tmp_path


# ──────────────────────────────────────────────────────────────────────────────
# The user's report: shipped config (agent_count 5, 3 listed) must boot 5
# ──────────────────────────────────────────────────────────────────────────────

def test_shipped_world_yaml_boots_five_agents(monkeypatch):
    monkeypatch.setenv("EM_CONFIG_DIR", str(REPO_CONFIG_DIR))
    cfg = load_config()
    assert cfg.world.agent_count == 5
    assert len(cfg.agents) == 5

    # The hand-listed cast survives byte-identical, in order, at its tier.
    listed = cfg.agents[:3]
    assert [a.name for a in listed] == ["Ada", "Bram", "Cleo"]
    assert all(a.cadence_tier == "protagonist" for a in listed)

    # The two padded seats come from the persona library, in card order,
    # at supporting tier, on their suggested (registered) profiles, in plaza.
    cards = load_personas()
    profile_names = {p.name for p in cfg.profiles}
    padded = cfg.agents[3:]
    assert [a.name for a in padded] == [c["name"] for c in cards[:2]]
    for agent, card in zip(padded, cards[:2]):
        assert agent.cadence_tier == "supporting"
        assert agent.location == "plaza"
        assert agent.personality == card["personality"]
        assert card["suggested_profile"] in profile_names
        assert agent.profile == card["suggested_profile"]


# ──────────────────────────────────────────────────────────────────────────────
# Equal / longer lists: never modified, never truncated
# ──────────────────────────────────────────────────────────────────────────────

def test_count_equal_to_list_changes_nothing(monkeypatch, tmp_path):
    monkeypatch.setenv("EM_CONFIG_DIR", str(_write_cfg(tmp_path, agent_count=3)))
    cfg = load_config()
    assert [a.name for a in cfg.agents] == ["Ada", "Bram", "Cleo"]
    assert [a.profile for a in cfg.agents] == ["alpha", "beta", "alpha"]
    # declared tiers preserved exactly (Bram opted into supporting)
    assert [a.cadence_tier for a in cfg.agents] == [
        "protagonist", "supporting", "protagonist"]


def test_count_smaller_than_list_never_truncates(monkeypatch, tmp_path):
    monkeypatch.setenv("EM_CONFIG_DIR", str(_write_cfg(tmp_path, agent_count=1)))
    cfg = load_config()
    assert [a.name for a in cfg.agents] == ["Ada", "Bram", "Cleo"]


# ──────────────────────────────────────────────────────────────────────────────
# Persona padding details: suggestion fallback + Citizen-N fill
# ──────────────────────────────────────────────────────────────────────────────

def test_padding_exhausts_personas_then_fills_citizens(monkeypatch, tmp_path):
    monkeypatch.setenv("EM_CONFIG_DIR", str(_write_cfg(tmp_path, agent_count=8)))
    cfg = load_config()
    names = [a.name for a in cfg.agents]
    assert names == ["Ada", "Bram", "Cleo",
                     "Mox", "Vesper", "Hazel",
                     "Citizen-1", "Citizen-2"]

    by_name = {a.name: a for a in cfg.agents}
    # every padded seat: supporting tier, default place (plaza exists)
    for n in names[3:]:
        assert by_name[n].cadence_tier == "supporting"
        assert by_name[n].location == "plaza"

    # registered suggested_profile honored; unknown suggestion ("Vesper")
    # falls back to the non-mock round-robin (alpha first), as do citizens.
    assert by_name["Mox"].profile == "beta"
    assert by_name["Hazel"].profile == "alpha"
    assert by_name["Vesper"].profile == "alpha"   # rr pick 1
    assert by_name["Citizen-1"].profile == "beta"  # rr pick 2
    assert by_name["Citizen-2"].profile == "alpha"  # rr pick 3
    assert "mock" not in {a.profile for a in cfg.agents}
    assert by_name["Citizen-1"].personality  # neutral but non-empty


def test_padding_without_persona_library_is_all_citizens(monkeypatch, tmp_path):
    monkeypatch.setenv("EM_CONFIG_DIR", str(
        _write_cfg(tmp_path, agent_count=5, personas_yaml=None)))
    cfg = load_config()
    assert [a.name for a in cfg.agents][3:] == ["Citizen-1", "Citizen-2"]


# ──────────────────────────────────────────────────────────────────────────────
# Name collisions: a listed agent shadows its persona card
# ──────────────────────────────────────────────────────────────────────────────

def test_persona_name_collision_skips_the_card(monkeypatch, tmp_path):
    agents_yaml = """
agents:
  - { name: Ada, personality: "engineer", profile: alpha, location: plaza }
  - { name: MOX, personality: "the real Mox", profile: beta, location: plaza }
"""
    monkeypatch.setenv("EM_CONFIG_DIR", str(
        _write_cfg(tmp_path, agent_count=4, agents_yaml=agents_yaml)))
    cfg = load_config()
    assert [a.name for a in cfg.agents] == ["Ada", "MOX", "Vesper", "Hazel"]
    # the listed MOX is untouched; the Mox card was skipped case-insensitively
    assert cfg.agents[1].personality == "the real Mox"
    assert cfg.agents[1].cadence_tier == "protagonist"


# ──────────────────────────────────────────────────────────────────────────────
# Mock override (the test-suite path) must cover padded agents too
# ──────────────────────────────────────────────────────────────────────────────

def test_mock_override_applies_to_padded_agents(monkeypatch, tmp_path):
    monkeypatch.setenv("EM_CONFIG_DIR", str(_write_cfg(tmp_path, agent_count=6)))
    cfg = load_config(profile_override="mock")
    assert len(cfg.agents) == 6
    assert all(a.profile == "mock" for a in cfg.agents)
    # padding metadata survives the remap
    assert [a.cadence_tier for a in cfg.agents[3:]] == ["supporting"] * 3
    assert [a.name for a in cfg.agents[3:]] == ["Mox", "Vesper", "Hazel"]


# ──────────────────────────────────────────────────────────────────────────────
# city25 variant: 25 listed == agent_count 25 ⇒ padding is a no-op
# ──────────────────────────────────────────────────────────────────────────────

def test_city25_variant_is_unaffected(monkeypatch, tmp_path):
    shutil.copy(REPO_CONFIG_DIR / "world.city25.yaml", tmp_path / "world.yaml")
    shutil.copy(REPO_CONFIG_DIR / "profiles.yaml", tmp_path / "profiles.yaml")
    shutil.copy(REPO_CONFIG_DIR / "personas.yaml", tmp_path / "personas.yaml")
    monkeypatch.setenv("EM_CONFIG_DIR", str(tmp_path))
    cfg = load_config()
    assert cfg.world.agent_count == 25
    assert len(cfg.agents) == 25
    assert len({a.name for a in cfg.agents}) == 25
    assert not [a for a in cfg.agents if a.name.startswith("Citizen-")]

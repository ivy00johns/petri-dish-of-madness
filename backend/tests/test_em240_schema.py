# backend/tests/test_em240_schema.py
from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params() -> WorldParams:
    return WorldParams(
        tick_interval_seconds=0.5, turns_per_day=999, energy_decay_per_turn=0.0,
        starting_energy=80.0, starting_credits=20, snapshot_interval_ticks=100,
    )


def _world() -> World:
    places = [PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social")]
    agents = [AgentState(id="ada", name="Ada", personality="", profile="mock",
                         location="plaza", energy=80.0, credits=20)]
    return World(params=_params(), places=places, agents=agents)


def test_disposition_role_default_and_omitted_from_to_dict():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20)
    assert a.disposition == "lawful"
    assert a.role == "citizen"
    d = a.to_dict()
    # Byte-stability: defaults must NOT appear in the serialized dict.
    assert "disposition" not in d
    assert "role" not in d


def test_disposition_role_serialized_only_when_set():
    a = AgentState(id="x", name="X", personality="", profile="mock",
                   location="plaza", energy=80.0, credits=20,
                   disposition="criminal", role="enforcer")
    d = a.to_dict()
    assert d["disposition"] == "criminal"
    assert d["role"] == "enforcer"


def test_spawn_agent_threads_disposition_and_role():
    world = _world()
    a = world.spawn_agent("Mona", "a fixer", "mock", "plaza",
                          disposition="criminal", role="citizen")
    assert a.disposition == "criminal"
    assert a.role == "citizen"
    # Round-trips through to_dict
    assert a.to_dict()["disposition"] == "criminal"


def test_load_personas_defaults_disposition_role(tmp_path, monkeypatch):
    import petridish.config.loader as loader
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "personas.yaml").write_text(
        "personas:\n"
        "  - name: Crank\n"
        "    archetype: Racketeer\n"
        "    personality: shakes down stalls\n"
        "    suggested_profile: groq-llama\n"
        "    disposition: criminal\n"
        "  - name: Dot\n"
        "    archetype: Baker\n"
        "    personality: bakes bread\n"
    )
    monkeypatch.setattr(loader, "_find_config_dir", lambda: cfg)
    cards = {c["name"]: c for c in loader.load_personas()}
    assert cards["Crank"]["disposition"] == "criminal"
    assert cards["Crank"]["role"] == "citizen"          # defaulted
    assert cards["Dot"]["disposition"] == "lawful"      # defaulted
    assert cards["Dot"]["role"] == "citizen"

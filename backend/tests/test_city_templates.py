from petridish.config.loader import load_config, CityProfileParams


def test_default_config_city_profile_is_grid():
    cfg = load_config()
    assert isinstance(cfg.world.city, CityProfileParams)
    assert cfg.world.city.template == "grid"        # back-compat default
    assert cfg.world.city.car_policy == "cars"


def test_city_profile_parses_fields(tmp_path):
    # mirror how other loader tests build a config dict (grep test_*loader* / conftest);
    # assert a world.city block parses template/size/density/car_policy.
    from petridish.config.loader import _parse_city_profile
    p = _parse_city_profile({"template": "greenfield", "size": 7,
                             "density": "low", "car_policy": "pedestrian"})
    assert (p.template, p.size, p.density, p.car_policy) == ("greenfield", 7, "low", "pedestrian")


def test_city_profile_absent_block_defaults(tmp_path):
    from petridish.config.loader import _parse_city_profile
    p = _parse_city_profile(None)
    assert p.template == "grid" and p.density == "medium" and p.car_policy == "cars"


# ── EM-246 (S4): World.__init__ seeds city_graph from the profile ──────────────
from petridish.engine.world import World
from petridish.engine.world import AgentState, PlaceState


def _world_with_profile(template_kind, density="medium", car_policy="cars"):
    cfg = load_config()
    cfg.world.city.template = template_kind
    cfg.world.city.density = density
    cfg.world.city.car_policy = car_policy
    places = [PlaceState(id=p.id, name=p.name, x=p.x, y=p.y, kind=p.kind,
                         description=p.description, district=p.district,
                         neighborhood_id=p.neighborhood_id, zone_kind=p.zone_kind)
              for p in cfg.places]
    agents = [AgentState(id=f"agent_{a.name.lower()}", name=a.name,
                         personality=a.personality, profile=a.profile, location=a.location,
                         energy=cfg.world.starting_energy, credits=cfg.world.starting_credits)
              for a in cfg.agents]
    return World(params=cfg.world, places=places, agents=agents)


def test_world_seeds_greenfield_graph():
    w = _world_with_profile("greenfield")
    assert w.city_graph.template == "greenfield"
    from petridish.engine.citygraph import classic_grid
    assert len(w.city_graph.edges) < len(classic_grid(w.city_seed).edges)


def test_world_default_is_classic_grid_byte_identical():
    from petridish.engine.citygraph import classic_grid
    w = _world_with_profile("grid")
    assert w.city_graph.to_dict()["edges"] == classic_grid(w.city_seed).to_dict()["edges"]


def test_world_sets_initial_car_policy_from_profile():
    w = _world_with_profile("grid", car_policy="pedestrian")
    assert w.city_graph.car_policy == "pedestrian"


def test_world_geometric_template_falls_back_to_grid():
    w = _world_with_profile("pentagon")
    from petridish.engine.citygraph import classic_grid
    assert [e.id for e in w.city_graph.edges] == [e.id for e in classic_grid(w.city_seed).edges]
    assert w.city_graph.template == "pentagon"  # intent recorded


def test_seeded_graph_survives_snapshot_round_trip():
    w = _world_with_profile("village")
    w2 = World.from_snapshot(w.to_snapshot())
    assert w2.city_graph.to_dict() == w.city_graph.to_dict()


# ── EM-246 (S4): determinism / acceptance ─────────────────────────────────────
def test_same_profile_two_worlds_identical_graph():
    a = _world_with_profile("village", density="low")
    b = _world_with_profile("village", density="low")
    assert a.city_graph.to_dict() == b.city_graph.to_dict()


def test_greenfield_perception_does_not_crash():
    from petridish.agents.runtime import build_nearby_layout
    w = _world_with_profile("greenfield")
    place = next(iter(w.places.values()))
    # near-empty graph: perception returns a string or None, never raises
    line = build_nearby_layout(w, place)
    assert line is None or isinstance(line, str)

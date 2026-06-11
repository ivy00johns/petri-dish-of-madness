"""
Wave D3 / EM-187 — resume-on-boot (contracts/wave-d3.md §B4).

On startup, when `world.resume_on_boot` (default true) and the most recent run
with a >tick-0 snapshot is config-compatible, the backend rebuilds the world
from that snapshot via the shared EM-101 fork machinery and starts a NEW run
row with fork lineage. This file gates the contract's minimum list:

  (A) Happy path — world-state continuity across a simulated boot (tick,
      energy, credits, relationships, buildings, animals; no duplicate seed
      critters; resumes paused).
  (B) Lineage — the new run row carries forked_from/forked_at_tick; the run
      browser's RunRow shape is unchanged.
  (C) run_resumed — exactly once, system actor, right payload, into the NEW
      run only.
  (D) Skips — tick-0-only runs are not resume sources (hot-reload streaks
      don't chain); no snapshots at all ⇒ fresh; resume targets the newest
      run with a >0 snapshot even past newer tick-0-only runs.
  (E) resume_on_boot=false — byte-identical fresh boot (proved against a
      pristine-DB control boot).
  (F) Config guard — changed roster / places / city_seed ⇒ fresh + ONE
      log.info reason; a changed tunable (lane_failover.sick_threshold) still
      resumes and ADOPTS the new value.
  (G) Reset — POST /api/control/reset stays the explicit fresh start, and a
      reset-created run is itself resumable on the next boot.
  (H) Seed critters — a resume spawns ONLY critters the snapshot lacks.
  (I) Config conventions (EM-155) — loader field default ON, yaml override,
      runs.config_json round-trip, EMBEDDED_WORLD_YAML mirror + shipped
      config/world.yaml in sync.

Boots are simulated with TestClient lifespan enters/exits over a tmp sqlite
file, with `petridish.api.app.load_config` patched to a MockProvider config —
no real keys, no LLM calls, no network.

CRITICAL suite rule: petridish.engine.world is imported BEFORE
petridish.agents.runtime (collection breaks otherwise).
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest
import yaml

from petridish.config.loader import (
    EMBEDDED_WORLD_YAML, AgentConfig, AnimalParams, AnimalSeed,
    LaneFailoverParams, ModelProfile, PlaceConfig, WorldConfig, WorldParams,
    _parse_world,
)
from petridish.engine.world import Building, RelationshipState, World  # noqa: F401  (import-order guard)
from petridish.engine.loop import _world_params_json
from petridish.persistence.repository import SQLiteRepository


# ──────────────────────────────────────────────────────────────────────────────
# Helpers — a MockProvider config + bootable app over a tmp sqlite file
# ──────────────────────────────────────────────────────────────────────────────

_SEEDS = (AnimalSeed(species="cat", name="Mochi", location="plaza"),
          AnimalSeed(species="dog", name="Biscuit", location="plaza"))


def _cfg(
    db_path,
    *,
    names: tuple[str, ...] = ("Ada", "Bram"),
    extra_place: bool = False,
    city_seed: int = 1337,
    resume: bool = True,
    sick_threshold: int = 3,
    seeds: tuple[AnimalSeed, ...] = _SEEDS,
) -> WorldConfig:
    """A minimal all-mock WorldConfig persisted to `db_path`. Animals are
    enabled (seed critters spawn) but llm_chance=0 and an astronomically large
    cadence keep every animal path zero-LLM."""
    params = WorldParams(
        db_path=str(db_path),
        resume_on_boot=resume,
        city_seed=city_seed,
        animals=AnimalParams(enabled=True, act_every_n_ticks=10**6,
                             llm_chance=0.0, model_profile=""),
        lane_failover=LaneFailoverParams(sick_threshold=sick_threshold),
    )
    places = [
        PlaceConfig(id="plaza", name="Central Plaza", x=500, y=500, kind="social"),
        PlaceConfig(id="home", name="Hearth House", x=100, y=700, kind="home"),
    ]
    if extra_place:
        places.append(PlaceConfig(id="docks", name="The Docks", x=900, y=100,
                                  kind="work"))
    agents = [
        AgentConfig(name=n, personality="", profile="mock", location="plaza")
        for n in names
    ]
    profiles = [ModelProfile(name="mock", adapter="mock", model_id="mock",
                             color="#2ecc71")]
    return WorldConfig(world=params, places=places, agents=agents,
                       profiles=profiles, animals=list(seeds))


def _appmod():
    import petridish.api.app  # noqa: F401  (ensure imported)
    return sys.modules["petridish.api.app"]


@pytest.fixture()
def boot(monkeypatch):
    """boot(cfg) -> TestClient context manager whose lifespan loads `cfg`."""
    from fastapi.testclient import TestClient

    appmod = _appmod()
    holder: dict = {}
    monkeypatch.setattr(
        appmod, "load_config", lambda profile_override=None: holder["cfg"]
    )

    def _boot(cfg: WorldConfig) -> TestClient:
        holder["cfg"] = cfg
        return TestClient(appmod.app, raise_server_exceptions=True)

    return _boot


def _mutate_and_snapshot(appmod, tick: int = 7) -> dict:
    """Drive the live world to a distinctive state and persist a snapshot at
    `tick` (the loop's own _save_snapshot path). Returns a probe of the ids."""
    world = appmod._world
    agents = {a.name: a for a in world.agents.values()}
    ada, bram = agents["Ada"], agents["Bram"]
    world.tick = tick
    world.day = tick // world.params.turns_per_day
    world.round = 3
    ada.energy = 41.5
    ada.credits = 23
    ada.location = "home"
    ada.relationships[bram.id] = RelationshipState(
        type="rival", trust=-20, interactions=4
    )
    world.buildings["b1"] = Building(
        id="b1", name="Clock Tower", kind="clocktower", location="plaza",
        status="under_construction", progress=40, funds_committed=12,
        funds_required=30, contributors=[ada.id], created_tick=2,
        updated_tick=tick,
    )
    appmod._loop._save_snapshot(tick)
    return {"ada_id": ada.id, "bram_id": bram.id,
            "parent_run_id": appmod._loop._run_id}


# ──────────────────────────────────────────────────────────────────────────────
# (A) Happy path — state continuity, no duplicate critters, resumes paused
# ──────────────────────────────────────────────────────────────────────────────

def test_resume_restores_world_state_without_duplicate_critters(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        appmod = _appmod()
        probe = _mutate_and_snapshot(appmod, tick=7)
        assert sorted((a.species, a.name) for a in appmod._world.animals.values()) \
            == [("cat", "Mochi"), ("dog", "Biscuit")]

    with boot(_cfg(db)):
        appmod = _appmod()
        world = appmod._world
        assert world.tick == 7
        assert world.round == 3
        assert world.running is False, "a resumed boot starts paused, like a fresh one"

        ada = world.agents[probe["ada_id"]]
        assert ada.energy == pytest.approx(41.5)
        assert ada.credits == 23
        assert ada.location == "home"
        rel = ada.relationships[probe["bram_id"]]
        assert (rel.type, rel.trust, rel.interactions) == ("rival", -20, 4)

        b = world.buildings["b1"]
        assert (b.status, b.progress, b.funds_committed, b.funds_required) == \
            ("under_construction", 40, 12, 30)
        assert b.contributors == [probe["ada_id"]]

        # §B4.4 — the snapshot already carries the seed critters: no duplicates.
        assert sorted((a.species, a.name) for a in world.animals.values()) == \
            [("cat", "Mochi"), ("dog", "Biscuit")]


def test_resume_spawns_only_missing_seed_critters(boot, tmp_path):
    """A snapshot that carries only the cat (dog seed added since) gets the
    dog spawned on resume — and never a second cat."""
    db = tmp_path / "resume.sqlite"
    cat_only = (AnimalSeed(species="cat", name="Mochi", location="plaza"),)
    with boot(_cfg(db, seeds=cat_only)):
        appmod = _appmod()
        assert sorted(a.name for a in appmod._world.animals.values()) == ["Mochi"]
        _mutate_and_snapshot(appmod, tick=7)

    with boot(_cfg(db)):  # seeds are cat + dog now (a tunable change)
        appmod = _appmod()
        assert appmod._world.tick == 7, "seed-list change is tunable — still resumes"
        assert sorted((a.species, a.name) for a in appmod._world.animals.values()) \
            == [("cat", "Mochi"), ("dog", "Biscuit")]
        spawned = appmod._repo.get_events(appmod._loop._run_id,
                                          kinds=["animal_spawned"])
        assert [e["payload"]["name"] for e in spawned] == ["Biscuit"], \
            "only the critter the snapshot lacks is spawned (and announced)"


# ──────────────────────────────────────────────────────────────────────────────
# (B) Lineage — forked_from/forked_at_tick on the new run; RunRow shape intact
# ──────────────────────────────────────────────────────────────────────────────

def test_resume_creates_lineage_run_row_and_run_browser_shape(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        appmod = _appmod()
        parent = _mutate_and_snapshot(appmod, tick=7)["parent_run_id"]

    with boot(_cfg(db)) as client:
        appmod = _appmod()
        new_id = appmod._loop._run_id
        assert new_id != parent

        runs = {r["id"]: r for r in client.get("/api/runs").json()}
        child = runs[new_id]
        assert child["forked_from"] == parent
        assert child["forked_at_tick"] == 7
        assert child["is_active"] is True
        assert runs[parent]["forked_from"] is None
        # The run-browser seam: RunRow keys unchanged (lineage chip just works).
        assert set(child) == {
            "id", "started_at", "ended_at", "status", "is_active", "max_tick",
            "event_count", "forked_from", "forked_at_tick", "config_summary",
        }


# ──────────────────────────────────────────────────────────────────────────────
# (C) run_resumed — exactly once, right payload, into the NEW run only
# ──────────────────────────────────────────────────────────────────────────────

def test_run_resumed_event_exactly_once_with_payload(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        appmod = _appmod()
        parent = _mutate_and_snapshot(appmod, tick=7)["parent_run_id"]

    with boot(_cfg(db)):
        appmod = _appmod()
        new_id = appmod._loop._run_id
        rows = appmod._repo.get_events(new_id, kinds=["run_resumed"])
        assert len(rows) == 1, "run_resumed must be emitted exactly once"
        evt = rows[0]
        assert evt["actor_type"] == "system"
        assert evt["text"] == f"▶ resumed run {parent} from tick 7"
        assert evt["payload"] == {"parent_run_id": parent, "snapshot_tick": 7}
        assert appmod._repo.get_events(parent, kinds=["run_resumed"]) == [], \
            "the event lands in the NEW run, never the parent"


# ──────────────────────────────────────────────────────────────────────────────
# (D) Skips — tick-0-only runs, no snapshots at all, hot-reload streaks
# ──────────────────────────────────────────────────────────────────────────────

def test_tick0_only_runs_are_not_resume_sources(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        pass  # boot 1: only the init tick-0 snapshot exists

    with boot(_cfg(db)):
        appmod = _appmod()
        assert appmod._world.tick == 0
        run = appmod._repo.get_run(appmod._loop._run_id)
        assert (run["forked_from"], run["forked_at_tick"]) == (None, None)
        assert appmod._repo.get_events(appmod._loop._run_id,
                                       kinds=["run_resumed"]) == []


def test_no_snapshots_at_all_boots_fresh(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    repo = SQLiteRepository(db)
    rid = repo.start_run(json.dumps({"world": {}, "agents": []}))
    repo.save_event(rid, {"kind": "agent_speech", "actor_id": "x",
                          "payload": {}}, 9)
    repo.close()

    with boot(_cfg(db)):
        appmod = _appmod()
        assert appmod._world.tick == 0
        assert appmod._repo.get_run(appmod._loop._run_id)["forked_from"] is None


def test_resume_targets_newest_resumable_run_past_tick0_reloads(boot, tmp_path):
    """A newer tick-0-only run (a reload that never ticked) must not shadow
    the older resumable run — reload streaks don't chain empty lineage."""
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        appmod = _appmod()
        resumable = _mutate_and_snapshot(appmod, tick=5)["parent_run_id"]

    with boot(_cfg(db, resume=False)):  # a fresh run that never advances
        appmod = _appmod()
        tick0_only = appmod._loop._run_id
        assert tick0_only != resumable

    with boot(_cfg(db)):
        appmod = _appmod()
        assert appmod._world.tick == 5
        run = appmod._repo.get_run(appmod._loop._run_id)
        assert run["forked_from"] == resumable, \
            "the tick-0-only reload run must be skipped as a resume source"


# ──────────────────────────────────────────────────────────────────────────────
# (E) resume_on_boot=false — byte-identical fresh boot
# ──────────────────────────────────────────────────────────────────────────────

def _fresh_boot_probe(boot, cfg) -> dict:
    """Boot once and capture everything a fresh start observable surface has:
    world state, lineage, the run's full event-kind sequence, snapshots."""
    with boot(cfg):
        appmod = _appmod()
        world = appmod._world
        run_id = appmod._loop._run_id
        run = appmod._repo.get_run(run_id)
        return {
            "tick": world.tick,
            "running": world.running,
            "agents": sorted(
                (a.name, a.energy, a.credits, a.location, a.cadence_tier)
                for a in world.agents.values()
            ),
            "animals": sorted(
                (a.species, a.name) for a in world.animals.values()
            ),
            "buildings": sorted(world.buildings),
            "lineage": (run["forked_from"], run["forked_at_tick"]),
            "event_kinds": [
                e["kind"] for e in appmod._repo.get_events(run_id)
            ],
            "snapshots": appmod._repo.get_snapshots(run_id),
        }


def test_resume_disabled_boots_byte_identical_fresh(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    control_db = tmp_path / "control.sqlite"

    # Make `db` resumable, then boot it with the flag OFF.
    with boot(_cfg(db)):
        _mutate_and_snapshot(_appmod(), tick=7)

    disabled = _fresh_boot_probe(boot, _cfg(db, resume=False))
    control = _fresh_boot_probe(boot, _cfg(control_db, resume=False))

    assert disabled == control, \
        "resume_on_boot=false must boot exactly like a pristine fresh start"
    assert disabled["tick"] == 0
    assert disabled["lineage"] == (None, None)
    assert "run_resumed" not in disabled["event_kinds"]


# ──────────────────────────────────────────────────────────────────────────────
# (F) Config guard — world-defining mismatches block (one logged reason);
#     tunable changes resume and adopt
# ──────────────────────────────────────────────────────────────────────────────

def _assert_fresh_with_logged_reason(appmod, caplog, needle: str) -> None:
    assert appmod._world.tick == 0
    assert appmod._repo.get_run(appmod._loop._run_id)["forked_from"] is None
    msgs = [r.getMessage() for r in caplog.records
            if "resume-on-boot" in r.getMessage()]
    assert len(msgs) == 1, f"expected ONE logged reason, got: {msgs}"
    assert "config mismatch" in msgs[0] and needle in msgs[0]


def test_roster_mismatch_boots_fresh_with_logged_reason(boot, tmp_path, caplog):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        _mutate_and_snapshot(_appmod(), tick=7)

    caplog.set_level(logging.INFO, logger="petridish.api.app")
    with boot(_cfg(db, names=("Ada", "Bram", "Cleo"))):
        _assert_fresh_with_logged_reason(_appmod(), caplog, "roster")


def test_places_mismatch_boots_fresh_with_logged_reason(boot, tmp_path, caplog):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        _mutate_and_snapshot(_appmod(), tick=7)

    caplog.set_level(logging.INFO, logger="petridish.api.app")
    with boot(_cfg(db, extra_place=True)):
        _assert_fresh_with_logged_reason(_appmod(), caplog, "places")


def test_city_seed_mismatch_boots_fresh_with_logged_reason(boot, tmp_path, caplog):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)):
        _mutate_and_snapshot(_appmod(), tick=7)

    caplog.set_level(logging.INFO, logger="petridish.api.app")
    with boot(_cfg(db, city_seed=4242)):
        _assert_fresh_with_logged_reason(_appmod(), caplog, "city_seed")


def test_tunable_param_change_still_resumes_and_adopts_new_value(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db, sick_threshold=3)):
        appmod = _appmod()
        parent = _mutate_and_snapshot(appmod, tick=7)["parent_run_id"]

    with boot(_cfg(db, sick_threshold=5)):
        appmod = _appmod()
        assert appmod._world.tick == 7, "a tunable change never blocks a resume"
        run = appmod._repo.get_run(appmod._loop._run_id)
        assert run["forked_from"] == parent
        # The resumed world + run row ADOPT the current config's tunables.
        assert appmod._world.params.lane_failover.sick_threshold == 5
        cfg_json = json.loads(run["config_json"])
        assert cfg_json["world"]["lane_failover"]["sick_threshold"] == 5


# ──────────────────────────────────────────────────────────────────────────────
# (G) Reset — unchanged, and a reset-created run is resumable later
# ──────────────────────────────────────────────────────────────────────────────

def test_reset_stays_fresh_and_a_reset_run_is_resumable(boot, tmp_path):
    db = tmp_path / "resume.sqlite"
    with boot(_cfg(db)) as client:
        appmod = _appmod()
        pre_reset = _mutate_and_snapshot(appmod, tick=7)["parent_run_id"]

        resp = client.post("/api/control/reset")
        assert resp.status_code == 200 and resp.json() == {"status": "ok"}
        reset_run = appmod._loop._run_id
        assert reset_run != pre_reset
        assert appmod._world.tick == 0, "reset stays the explicit fresh start"
        run = appmod._repo.get_run(reset_run)
        assert (run["forked_from"], run["forked_at_tick"]) == (None, None)

        # Advance the reset-created run so it becomes a resume source.
        _mutate_and_snapshot(appmod, tick=4)

    with boot(_cfg(db)):
        appmod = _appmod()
        assert appmod._world.tick == 4
        assert appmod._repo.get_run(appmod._loop._run_id)["forked_from"] == \
            reset_run, "a reset-created run is itself resumable later"


# ──────────────────────────────────────────────────────────────────────────────
# (I) Config conventions (EM-155) — loader, round-trip, mirrors
# ──────────────────────────────────────────────────────────────────────────────

def test_loader_field_defaults_on_and_yaml_override():
    assert WorldParams().resume_on_boot is True, "dataclass default must be ON"
    params, _, _ = _parse_world({"world": {}})
    assert params.resume_on_boot is True, "absent yaml key ⇒ ON"
    params, _, _ = _parse_world({"world": {"resume_on_boot": False}})
    assert params.resume_on_boot is False


def test_config_round_trips_through_runs_config_json():
    # The fork/replay seam: WorldParams → runs.config_json → _parse_world.
    blob = _world_params_json(WorldParams(resume_on_boot=False))
    params, _, _ = _parse_world({"world": blob})
    assert params.resume_on_boot is False
    blob = _world_params_json(WorldParams())
    params, _, _ = _parse_world({"world": blob})
    assert params.resume_on_boot is True


def test_embedded_mirror_and_shipped_world_yaml_in_sync():
    embedded = yaml.safe_load(EMBEDDED_WORLD_YAML)
    assert embedded["world"]["resume_on_boot"] is True
    shipped_path = Path(__file__).resolve().parents[2] / "config" / "world.yaml"
    shipped = yaml.safe_load(shipped_path.read_text())
    assert shipped["world"]["resume_on_boot"] is True

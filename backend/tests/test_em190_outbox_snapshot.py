"""EM-190 — serialize the PRE-EXISTING transient outboxes.

`pending_spawn_events` (W7/EM-062 governance-spawn + EM-114 births + EM-211
memory events + name_town/demolish/promote_image vote effects) and
`pending_relationship_events` (EM-113 reflex relationship_changed transitions)
are parked on the World between the action that mints them and the loop's drain.
A snapshot taken between the park and the drain MUST NOT silently drop them on
fork/resume — so they serialize ADDITIVELY, only-when-non-empty, restored
defensively, exactly like the Wave-M outboxes (pending_skill_requests /
pending_trade_offers / pending_cooperation_offers / pending_pitches).

Invariants pinned here:
  - a world that never parks either outbox round-trips BYTE-IDENTICALLY (the
    snapshot key set is unchanged — both keys ABSENT under default conditions),
  - a parked spawn / relationship event survives snapshot -> restore,
  - the restore is defensive (non-dict / garbage entries dropped),
  - re-snapshot of a restored world is byte-stable.

The image-fetch outbox (pending_image_fetches) stays deliberately NOT serialized
(a documented transient side-artifact); this file pins that it never leaks into
the snapshot. (The within-round boost budget `_boosts_this_round` IS serialized
snapshot-safe as of the EM-235 cap-bypass fix — its round-trip is pinned in
test_em235_boost.py, not here.)
"""

import copy
import json

from petridish.engine.world import World, AgentState, PlaceState
from petridish.config.loader import WorldParams


def _params(**kw):
    base = dict(tick_interval_seconds=0.5, turns_per_day=999,
                energy_decay_per_turn=0.0, starting_energy=80.0,
                starting_credits=20, snapshot_interval_ticks=100)
    base.update(kw)
    return WorldParams(**base)


def _places():
    return [
        PlaceState(id="plaza", name="Plaza", x=0, y=0, kind="social"),
        PlaceState(id="forge", name="Forge", x=1, y=0, kind="work"),
    ]


def _agent(**kw):
    base = dict(id="dot", name="Dot", personality="bakes", profile="mock",
                location="plaza", energy=80.0, credits=20)
    base.update(kw)
    return AgentState(**base)


def _world(agents=None, params=None):
    return World(params=params or _params(), places=_places(),
                 agents=agents or [_agent()])


# ── default world: neither outbox key present, byte-identical round-trip ───────

def test_no_outbox_state_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    # The new keys are ABSENT under default conditions (the only-when-non-empty
    # rule), so a pre-EM-190 snapshot key set is preserved exactly.
    assert "pending_spawn_events" not in snap
    assert "pending_relationship_events" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
        json.dumps(snap, sort_keys=True)


def test_image_fetches_never_serialize():
    w = _world()
    # This transient side-artifact (the PNG fetch queue) must never reach the
    # snapshot. (The per-round boost budget _boosts_this_round, by contrast, IS
    # serialized snapshot-safe — see test_em235_boost.py — to hold the
    # world.boost.max_per_round cap across a mid-round fork/resume.)
    w.pending_image_fetches.append({"image_id": "x", "prompt": "p", "url": "u"})
    snap = w.to_snapshot()
    assert "pending_image_fetches" not in snap


# ── pending_spawn_events: parked -> snapshot -> restore preserves ──────────────

def test_pending_spawn_event_survives_snapshot_restore():
    w = _world()
    w.pending_spawn_events.append({
        "kind": "town_named",
        "actor_id": "system",
        "actor_type": "system",
        "text": "the town is now named Hopeville.",
        "payload": {"name": "Hopeville", "proposal_id": "p1"},
    })
    snap = w.to_snapshot()
    assert snap["pending_spawn_events"][0]["kind"] == "town_named"
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert len(restored.pending_spawn_events) == 1
    evt = restored.pending_spawn_events[0]
    assert evt["kind"] == "town_named"
    assert evt["payload"]["name"] == "Hopeville"
    # A drain on the restored world yields exactly the parked event.
    drained = restored.drain_spawn_events()
    assert drained[0]["payload"]["proposal_id"] == "p1"
    assert restored.pending_spawn_events == []


def test_pending_relationship_event_survives_snapshot_restore():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    w.pending_relationship_events.append({
        "kind": "relationship_changed",
        "actor_id": "dot",
        "target_id": "rho",
        "text": "Dot and Rho are now friends",
        "payload": {"from_type": "neutral", "to_type": "friend",
                    "trust": 55, "since_tick": 4},
    })
    snap = w.to_snapshot()
    assert snap["pending_relationship_events"][0]["target_id"] == "rho"
    restored = World.from_snapshot(
        copy.deepcopy(snap),
        params=_params())
    assert len(restored.pending_relationship_events) == 1
    evt = restored.pending_relationship_events[0]
    assert evt["kind"] == "relationship_changed"
    assert evt["payload"]["to_type"] == "friend"
    drained = restored.drain_relationship_events()
    assert drained[0]["actor_id"] == "dot"
    assert restored.pending_relationship_events == []


def test_both_outboxes_survive_together():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    w.pending_spawn_events.append({
        "kind": "agent_spawned", "actor_id": "kid", "actor_type": "system",
        "text": "A child is born.", "payload": {"agent_id": "kid"},
    })
    w.pending_relationship_events.append({
        "kind": "relationship_changed", "actor_id": "dot", "target_id": "rho",
        "text": "Dot and Rho are now friends",
        "payload": {"to_type": "friend"},
    })
    snap = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert len(restored.pending_spawn_events) == 1
    assert len(restored.pending_relationship_events) == 1


# ── byte-stable re-snapshot of a restored world ───────────────────────────────

def test_outbox_snapshot_is_stable_byte_identical():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    w.pending_spawn_events.append({
        "kind": "town_named", "actor_id": "system", "actor_type": "system",
        "text": "named", "payload": {"name": "Hopeville"},
    })
    w.pending_relationship_events.append({
        "kind": "relationship_changed", "actor_id": "dot", "target_id": "rho",
        "text": "friends", "payload": {"to_type": "friend", "trust": 51},
    })
    snap1 = w.to_snapshot()
    restored = World.from_snapshot(copy.deepcopy(snap1), params=_params())
    snap2 = restored.to_snapshot()
    assert json.dumps(snap2, sort_keys=True) == json.dumps(snap1, sort_keys=True)


# ── defensive restore: garbage / non-dict entries dropped ─────────────────────

def test_from_snapshot_garbage_spawn_events_ignored():
    w = _world()
    w.pending_spawn_events.append({
        "kind": "town_named", "payload": {"name": "OK"},
    })
    snap = w.to_snapshot()
    # Inject garbage that a hand-edited / corrupted snapshot might carry.
    snap["pending_spawn_events"] = [
        {"kind": "town_named", "payload": {"name": "OK"}},
        "not-a-dict",
        None,
        123,
    ]
    restored = World.from_snapshot(snap, params=_params())
    assert len(restored.pending_spawn_events) == 1
    assert restored.pending_spawn_events[0]["kind"] == "town_named"


def test_from_snapshot_garbage_relationship_events_ignored():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    snap = w.to_snapshot()
    snap["pending_relationship_events"] = [
        {"kind": "relationship_changed", "actor_id": "dot", "target_id": "rho",
         "payload": {"to_type": "friend"}},
        ["nope"],
        None,
    ]
    restored = World.from_snapshot(snap, params=_params())
    assert len(restored.pending_relationship_events) == 1
    assert restored.pending_relationship_events[0]["kind"] == "relationship_changed"


def test_from_snapshot_absent_outboxes_default_empty():
    # A pre-EM-190 snapshot has neither key; both restore to [].
    w = _world()
    snap = w.to_snapshot()
    snap.pop("pending_spawn_events", None)
    snap.pop("pending_relationship_events", None)
    restored = World.from_snapshot(snap, params=_params())
    assert restored.pending_spawn_events == []
    assert restored.pending_relationship_events == []


# ── EM-240 recruit offers (audit-surfaced pre-Wave-M outbox) ──────────────────
# The recruit -> accept_contract pact is a two-turn negotiated offer that can be
# parked across a snapshot boundary (the target accepts on a LATER turn), so it
# falls in the same EM-190 class as the trade/cooperation offers: serialize it
# only-when-non-empty, restored defensively, default world byte-identical.

def test_no_crime_offer_round_trips_byte_identical():
    w = _world()
    snap = w.to_snapshot()
    assert "pending_crime_offers" not in snap
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert json.dumps(restored.to_snapshot(), sort_keys=True) == \
        json.dumps(snap, sort_keys=True)


def test_pending_crime_offer_survives_snapshot_restore():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    w.pending_crime_offers["rho"] = {"recruiter_id": "dot", "tick": 7}
    snap = w.to_snapshot()
    assert snap["pending_crime_offers"]["rho"]["recruiter_id"] == "dot"
    restored = World.from_snapshot(copy.deepcopy(snap), params=_params())
    assert restored.pending_crime_offers == {
        "rho": {"recruiter_id": "dot", "tick": 7}
    }


def test_from_snapshot_garbage_crime_offers_ignored():
    w = _world(agents=[_agent(), _agent(id="rho", name="Rho")])
    snap = w.to_snapshot()
    snap["pending_crime_offers"] = {
        "rho": {"recruiter_id": "dot", "tick": 2},   # kept
        "ghost": {"recruiter_id": "dot", "tick": 3},  # offeree gone -> dropped
        "rho2": {"recruiter_id": "ghost", "tick": 4},  # recruiter gone -> dropped
        "dot": {"recruiter_id": "dot", "tick": 5},    # self-offer -> dropped
        "bad": "not-a-dict",                           # non-dict -> dropped
    }
    restored = World.from_snapshot(snap, params=_params())
    assert restored.pending_crime_offers == {
        "rho": {"recruiter_id": "dot", "tick": 2}
    }

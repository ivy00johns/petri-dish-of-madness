"""
EM-187 / EM-101 — lineage-aware event reads.

A run forked from a parent (resume-on-boot, or an interactive W11b fork) must be
able to surface its ancestors' PRE-FORK events so its feed shows the FULL
timeline, not just events written after the fork point — which was the
resume-on-boot regression (the feed started at the resume banner, dropping the
parent run's history). events.seq is a global monotonic PK, so a lineage query
keyset-pages cleanly across the run boundary (newest→oldest), exactly as the
frontend tail-first backfill needs.

NOTE (suite convention): import petridish.engine.world BEFORE any runtime.
"""
from __future__ import annotations

import petridish.engine.world  # noqa: F401  (import-order guard)
from petridish.persistence.repository import SQLiteRepository


def _evt(text: str) -> dict:
    return {"kind": "agent_action", "actor_id": None, "actor_type": "system",
            "text": text, "payload": {}}


def _seed_lineage() -> tuple[SQLiteRepository, int, int]:
    """parent: ticks 0,1,2 (p0,p1,p2). child forks parent at tick 2 and runs
    ticks 2,3 (c2,c3). The child's full timeline is the parent's pre-fork slice
    (tick < 2 ⇒ p0,p1) plus its own events (c2,c3); p2 is excluded (>= fork)."""
    repo = SQLiteRepository(":memory:")
    parent = repo.start_run("{}")
    for t in range(3):
        repo.save_event(parent, _evt(f"p{t}"), t)
    child = repo.start_run("{}", forked_from=parent, forked_at_tick=2)
    for t in range(2, 4):
        repo.save_event(child, _evt(f"c{t}"), t)
    return repo, parent, child


def test_lineage_false_stays_run_scoped():
    repo, _parent, child = _seed_lineage()
    rows = repo.get_events(child, order="asc")
    assert [r["text"] for r in rows] == ["c2", "c3"]


def test_lineage_true_includes_ancestor_prefork_events():
    repo, _parent, child = _seed_lineage()
    rows = repo.get_events(child, order="asc", lineage=True)
    assert [r["text"] for r in rows] == ["p0", "p1", "c2", "c3"]


def test_lineage_keyset_pages_across_the_run_boundary():
    """The frontend backfill idiom: order=desc + before_seq, newest→oldest, no
    gaps/repeats across the parent⇄child boundary."""
    repo, _parent, child = _seed_lineage()
    page1 = repo.get_events(child, order="desc", limit=2, lineage=True)
    assert [r["text"] for r in page1] == ["c3", "c2"]
    before = page1[-1]["seq"]
    page2 = repo.get_events(child, order="desc", limit=2, before_seq=before, lineage=True)
    assert [r["text"] for r in page2] == ["p1", "p0"]


def test_lineage_stats_size_the_full_timeline():
    repo, _parent, child = _seed_lineage()
    assert repo.get_event_stats(child)["total"] == 2                 # run-scoped
    full = repo.get_event_stats(child, lineage=True)
    assert full["total"] == 4
    assert full["max_tick"] == 3


def test_root_run_lineage_is_identity():
    """A root run (no fork) is byte-identical with/without lineage."""
    repo, parent, _child = _seed_lineage()
    assert repo.get_run_lineage(parent) == [(parent, None)]
    assert repo.get_events(parent, order="asc", lineage=True) == \
        repo.get_events(parent, order="asc")


def test_multi_generation_lineage_walks_to_the_root():
    """grandparent ← parent (fork@1) ← child (fork@3): the child sees gp tick<1,
    parent tick<3, and all its own — decreasing ceilings up the chain."""
    repo = SQLiteRepository(":memory:")
    gp = repo.start_run("{}")
    for t in range(3):
        repo.save_event(gp, _evt(f"g{t}"), t)            # g0,g1,g2
    parent = repo.start_run("{}", forked_from=gp, forked_at_tick=1)
    for t in range(1, 4):
        repo.save_event(parent, _evt(f"p{t}"), t)         # p1,p2,p3
    child = repo.start_run("{}", forked_from=parent, forked_at_tick=3)
    for t in range(3, 5):
        repo.save_event(child, _evt(f"c{t}"), t)          # c3,c4

    rows = repo.get_events(child, order="asc", lineage=True)
    # gp: tick<1 ⇒ g0 ; parent: tick<3 ⇒ p1,p2 ; child: c3,c4
    assert [r["text"] for r in rows] == ["g0", "p1", "p2", "c3", "c4"]
    assert repo.get_run_lineage(child) == [(child, None), (parent, 3), (gp, 1)]

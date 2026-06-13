"""Wave F / F1 — events API tail + stats (contracts/wave-f.md §F1, EM-194).

Covers the full F1 acceptance list:
  · GET /api/events/stats → {total, max_seq, max_tick, min_seq}, run-scoped
    via ?run_id exactly like GET /api/events (omitted → active run; unknown
    id → 404); empty run → all zeros
  · GET /api/events gains an honest TAIL mode: order=desc + before_seq
    keyset (strict mirror of after_seq) — rows newest-first, pages
    overlap-free and exhaustive
  · the existing asc path is byte-identical (regression-pin: full fetch,
    after_seq keyset pagination, filters)

Repository halves are pure SQLiteRepository(':memory:') unit tests; the API
halves pin the routes with the TestClient (the test_w11b idiom), seeding an
ISOLATED run row so the live loop's boot events never skew assertions.

NOTE (suite convention): import petridish.engine.world BEFORE
petridish.agents.runtime.
"""
from __future__ import annotations

import sys

import petridish.engine.world  # noqa: F401  (import-order convention)
from petridish.persistence.repository import SQLiteRepository


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _seed_run(repo: SQLiteRepository, n: int = 20) -> int:
    """Start a run and persist n events across ticks/kinds; returns run_id."""
    run_id = repo.start_run("{}")
    for i in range(n):
        repo.save_event(
            run_id,
            {
                "kind": "speech" if i % 3 else "move",
                "actor_id": f"agent_{i % 4}",
                "actor_type": "human_agent",
                "text": f"event {i}",
                "payload": {"i": i},
            },
            tick=i // 2,  # two events per tick
        )
    return run_id


def _seqs(rows: list[dict]) -> list[int]:
    return [r["seq"] for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Repository — get_event_stats (count/bounds, scoping, empty run).
# ──────────────────────────────────────────────────────────────────────────────

def test_stats_empty_run_is_all_zeros():
    repo = SQLiteRepository(":memory:")
    run_id = repo.start_run("{}")
    assert repo.get_event_stats(run_id) == {
        "total": 0, "max_seq": 0, "max_tick": 0, "min_seq": 0,
    }


def test_stats_counts_and_bounds():
    repo = SQLiteRepository(":memory:")
    run_id = _seed_run(repo, n=20)
    rows = repo.get_events(run_id)
    stats = repo.get_event_stats(run_id)
    assert stats == {
        "total": 20,
        "max_seq": max(_seqs(rows)),
        "max_tick": max(r["tick"] for r in rows),
        "min_seq": min(_seqs(rows)),
    }
    assert stats["max_tick"] == 9  # 20 events, two per tick → ticks 0..9


def test_stats_are_run_scoped():
    repo = SQLiteRepository(":memory:")
    run_a = _seed_run(repo, n=6)
    run_b = _seed_run(repo, n=4)
    a, b = repo.get_event_stats(run_a), repo.get_event_stats(run_b)
    assert a["total"] == 6 and b["total"] == 4
    # run_b's seqs come after run_a's in the shared autoincrement space.
    assert b["min_seq"] > a["max_seq"]
    assert a["min_seq"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# 2. Repository — desc tail with before_seq keyset.
# ──────────────────────────────────────────────────────────────────────────────

def test_before_seq_desc_returns_strictly_older_rows_newest_first():
    repo = SQLiteRepository(":memory:")
    run_id = _seed_run(repo, n=10)
    all_desc = repo.get_events(run_id, order="desc")
    pivot = all_desc[3]["seq"]
    rows = repo.get_events(run_id, before_seq=pivot, order="desc")
    assert _seqs(rows) == sorted(
        (s for s in _seqs(all_desc) if s < pivot), reverse=True
    )
    assert all(r["seq"] < pivot for r in rows)  # strict: pivot row excluded


def test_desc_keyset_pages_are_overlap_free_and_exhaustive():
    repo = SQLiteRepository(":memory:")
    run_id = _seed_run(repo, n=23)  # deliberately not a multiple of the page size
    asc = repo.get_events(run_id)

    pages, cursor = [], None
    while True:
        page = repo.get_events(run_id, before_seq=cursor, limit=5, order="desc")
        if not page:
            break
        assert _seqs(page) == sorted(_seqs(page), reverse=True)  # newest-first
        pages.append(page)
        cursor = page[-1]["seq"]

    paged = [r for page in pages for r in page]
    assert len(paged) == len(asc) == 23  # exhaustive, no duplicates
    assert len(set(_seqs(paged))) == 23  # overlap-free
    assert list(reversed(paged)) == asc  # exact same rows as the asc contract


def test_before_seq_composes_with_existing_filters():
    repo = SQLiteRepository(":memory:")
    run_id = _seed_run(repo, n=20)
    all_speech_desc = repo.get_events(run_id, kinds=["speech"], order="desc")
    pivot = all_speech_desc[2]["seq"]
    rows = repo.get_events(run_id, kinds=["speech"], before_seq=pivot,
                           order="desc", limit=4)
    assert len(rows) == 4
    assert all(r["kind"] == "speech" and r["seq"] < pivot for r in rows)
    assert _seqs(rows) == _seqs(all_speech_desc)[3:7]


# ──────────────────────────────────────────────────────────────────────────────
# 3. Repository — asc path regression-pin (byte-identical to pre-F behavior).
# ──────────────────────────────────────────────────────────────────────────────

def test_asc_path_unchanged_full_and_after_seq_keyset():
    repo = SQLiteRepository(":memory:")
    run_id = _seed_run(repo, n=12)
    asc = repo.get_events(run_id)
    assert _seqs(asc) == sorted(_seqs(asc))  # ascending, seq-ordered

    pivot = asc[4]["seq"]
    page = repo.get_events(run_id, after_seq=pivot, limit=3)
    assert page == asc[5:8]  # seq > pivot, asc, limit honored — the old contract

    # before_seq=None is inert: the asc fetch is identical with and without it.
    assert repo.get_events(run_id, before_seq=None) == asc

    # default order stays asc even when before_seq is supplied.
    older = repo.get_events(run_id, before_seq=pivot)
    assert older == asc[:4]


# ──────────────────────────────────────────────────────────────────────────────
# 4. API — GET /api/events/stats + desc tail through the route
#    (the test_w11b idiom; isolated run row so boot events don't skew counts).
# ──────────────────────────────────────────────────────────────────────────────

def test_stats_endpoint_shape_and_values():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        run_id = _seed_run(appmod._repo, n=15)
        resp = client.get("/api/events/stats", params={"run_id": run_id})
        assert resp.status_code == 200
        stats = resp.json()
        assert set(stats) == {"total", "max_seq", "max_tick", "min_seq"}
        assert all(isinstance(v, int) for v in stats.values())
        assert stats == appmod._repo.get_event_stats(run_id)
        assert stats["total"] == 15 and stats["max_tick"] == 7


def test_stats_endpoint_defaults_to_active_run_and_404s_unknown():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        # Omitted run_id → the active run, same scoping as GET /api/events.
        resp = client.get("/api/events/stats")
        assert resp.status_code == 200
        assert resp.json() == appmod._repo.get_event_stats(appmod._loop._run_id)

        # Unknown run → 404 via _resolve_run_id, like every scoped read.
        assert client.get("/api/events/stats",
                          params={"run_id": 999999}).status_code == 404


def test_stats_endpoint_zeros_when_uninitialized():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        saved_loop = appmod._loop
        try:
            appmod._loop = None  # no active run resolvable
            resp = client.get("/api/events/stats")
            assert resp.status_code == 200
            assert resp.json() == {"total": 0, "max_seq": 0,
                                   "max_tick": 0, "min_seq": 0}
        finally:
            appmod._loop = saved_loop


def test_events_endpoint_desc_tail_pages_via_http():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        run_id = _seed_run(appmod._repo, n=13)
        asc = client.get("/api/events", params={"run_id": run_id}).json()

        pages, cursor = [], None
        while True:
            params = {"run_id": run_id, "order": "desc", "limit": 4}
            if cursor is not None:
                params["before_seq"] = cursor
            page = client.get("/api/events", params=params).json()
            if not page:
                break
            assert _seqs(page) == sorted(_seqs(page), reverse=True)
            pages.append(page)
            cursor = page[-1]["seq"]

        paged = [r for page in pages for r in page]
        assert len(paged) == 13 and len(set(_seqs(paged))) == 13
        assert list(reversed(paged)) == asc  # tail mode is the asc set, reversed


def test_events_endpoint_asc_byte_identical_regression_pin():
    from fastapi.testclient import TestClient
    from petridish.api.app import app
    appmod = sys.modules["petridish.api.app"]

    with TestClient(app, raise_server_exceptions=True) as client:
        run_id = _seed_run(appmod._repo, n=10)

        # Full asc fetch through the route == the repository contract, byte-
        # identical (the route adds nothing and reorders nothing).
        resp = client.get("/api/events", params={"run_id": run_id})
        assert resp.status_code == 200
        asc = resp.json()
        assert asc == appmod._repo.get_events(run_id)

        # after_seq keyset + limit + kind filter: the pre-F param surface.
        pivot = asc[3]["seq"]
        page = client.get("/api/events", params={
            "run_id": run_id, "after_seq": pivot, "limit": 3,
        }).json()
        assert page == asc[4:7]
        speech = client.get("/api/events", params={
            "run_id": run_id, "kinds": "speech",
        }).json()
        assert speech == [r for r in asc if r["kind"] == "speech"]

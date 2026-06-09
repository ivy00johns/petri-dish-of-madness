"""Pytest bootstrap for the backend suite.

W10 / EM-085 made the shipped config persist runs to <repo>/data/run.sqlite
(world.yaml: `db_path: ${EM_DB_PATH:-data/run.sqlite}`). The suite must NEVER
write test runs into — or take WAL locks on — that live run-history file, so
EM_DB_PATH is pinned to ':memory:' here, before any test imports the app or
calls load_config(). Tests that need a file-backed DB pass an explicit
tmp_path to SQLiteRepository (see test_w10.py / test_event_log.py).

Plain assignment (not setdefault) on purpose: even an exported EM_DB_PATH in
the developer's shell must not route pytest writes at a real DB.
"""
import os

os.environ["EM_DB_PATH"] = ":memory:"

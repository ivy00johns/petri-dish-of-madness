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

# EM-222 — the shipped `embed` profile points at the FreeLLMAPI proxy (:3001).
# The suite must be hermetic: never make real embedding network calls (they add
# non-deterministic per-turn latency that races the synchronous step endpoint).
# This forces the embed lane to a deterministic MockProvider for ALL tests, so
# the relevance-retrieval path is still exercised end-to-end, just offline.
# Set before any test imports the app / builds a Router.
os.environ["EM_EMBED_MOCK"] = "1"

# Wave I / EM-210 — The Atelier image provider must be hermetic: never hit a
# free image endpoint from the suite (non-deterministic latency, and the loop's
# best-effort fetch would otherwise write real PNGs into data/). EM_IMAGEGEN_MOCK
# forces build_provider() to the MockImageProvider (a fixed tiny PNG, no network),
# mirroring the EM_EMBED_MOCK pattern above. Set before any app/loop import.
os.environ["EM_IMAGEGEN_MOCK"] = "1"

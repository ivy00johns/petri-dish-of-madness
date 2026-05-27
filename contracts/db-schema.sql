-- Contract: SQLite schema v1.0.0
-- Persistence for replay + restart. Backend owns the repository implementation;
-- the engine depends on a repository INTERFACE, not this SQL directly.
-- All JSON columns store UTF-8 JSON text.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL,
  config_json   TEXT NOT NULL,         -- effective world.yaml at start
  status        TEXT NOT NULL DEFAULT 'running'  -- running|paused|ended
);

CREATE TABLE IF NOT EXISTS agents (
  id            TEXT PRIMARY KEY,
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  name          TEXT NOT NULL,
  personality   TEXT NOT NULL,
  profile       TEXT NOT NULL,         -- model-profile name
  location      TEXT NOT NULL,         -- place id
  energy        REAL NOT NULL,
  credits       INTEGER NOT NULL,
  mood          TEXT,
  alive         INTEGER NOT NULL DEFAULT 1,
  zero_energy_turns INTEGER NOT NULL DEFAULT 0,
  beliefs_json  TEXT NOT NULL DEFAULT '[]',
  relationships_json TEXT NOT NULL DEFAULT '{}',
  updated_tick  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS places (
  id            TEXT PRIMARY KEY,
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  name          TEXT NOT NULL,
  x             INTEGER NOT NULL,
  y             INTEGER NOT NULL,
  kind          TEXT NOT NULL,
  description   TEXT
);

CREATE TABLE IF NOT EXISTS rules (
  id            TEXT PRIMARY KEY,
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  effect        TEXT NOT NULL,
  text          TEXT NOT NULL,
  proposer_id   TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'proposed',  -- proposed|active|rejected
  votes_json    TEXT NOT NULL DEFAULT '{}',
  created_tick  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  tick          INTEGER NOT NULL,
  kind          TEXT NOT NULL,
  actor_id      TEXT,
  target_id     TEXT,
  profile       TEXT,
  text          TEXT,
  payload_json  TEXT NOT NULL DEFAULT '{}',
  ts            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_run_tick ON events(run_id, tick);

-- Optional per-turn snapshot for replay scrubbing (v1 may skip writing these).
CREATE TABLE IF NOT EXISTS snapshots (
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  tick          INTEGER NOT NULL,
  state_json    TEXT NOT NULL,
  PRIMARY KEY (run_id, tick)
);

-- Contract: SQLite schema v1.1.0
-- Persistence for replay + restart. Backend owns the repository implementation;
-- the engine depends on a repository INTERFACE, not this SQL directly.
-- All JSON columns store UTF-8 JSON text.
--
-- v1.1.0 (W5 / EM-054): the `events` table is the append-only event-log spine
-- (event sourcing). Added actor_type, turn_id, sim_time so one agent turn is a
-- linked, replayable trace. The `snapshots` table is now POPULATED to bound
-- replay cost. Full spec: contracts/event-log.md.

-- Durability + concurrency pragmas. WAL lets the /inspector read while the sim
-- writes; synchronous=NORMAL is the safe-fast pairing with WAL; busy_timeout
-- avoids spurious "database is locked"; wal_autocheckpoint bounds -wal growth.
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
PRAGMA wal_autocheckpoint = 1000;

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

-- The append-only event-log spine. `seq` is the monotonic event_id; rows are
-- never updated or deleted. One agent turn emits a linked chain of rows that
-- all share a `turn_id` (an OTel-style trace; each row is a span).
-- NOTE for file-backed DBs upgrading from v1.0.0: repository adds the three new
-- columns via `ALTER TABLE events ADD COLUMN ...` when missing (idempotent guard).
-- Fresh (:memory: / new file) runs get them from this CREATE directly.
CREATE TABLE IF NOT EXISTS events (
  seq           INTEGER PRIMARY KEY AUTOINCREMENT,   -- event_id, monotonic
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  tick          INTEGER NOT NULL,
  sim_time      REAL,                  -- tick * tick_interval_seconds (sim seconds)
  kind          TEXT NOT NULL,         -- event_type (extensible; see event-log.md)
  actor_id      TEXT,
  actor_type    TEXT NOT NULL DEFAULT 'human_agent',  -- human_agent|system|god|animal
  target_id     TEXT,
  profile       TEXT,
  turn_id       TEXT,                  -- correlation id: groups one turn's chain
  text          TEXT,
  payload_json  TEXT NOT NULL DEFAULT '{}',
  ts            TEXT NOT NULL          -- wall_time, ISO8601
);
CREATE INDEX IF NOT EXISTS idx_events_run_seq  ON events(run_id, seq);
CREATE INDEX IF NOT EXISTS idx_events_run_tick ON events(run_id, tick);
CREATE INDEX IF NOT EXISTS idx_events_run_turn ON events(run_id, turn_id);
CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events(run_id, kind);
CREATE INDEX IF NOT EXISTS idx_events_run_actor ON events(run_id, actor_id);

-- Periodic world snapshots that bound replay cost: replay(T) = load the nearest
-- snapshot with tick <= T, then fold events forward in `seq` order up to T.
-- W5 (EM-054) POPULATES these: at run init (tick 0), on structural change
-- (spawn/kill/reset), and every world.snapshot_interval_ticks thereafter.
CREATE TABLE IF NOT EXISTS snapshots (
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  tick          INTEGER NOT NULL,
  state_json    TEXT NOT NULL,
  PRIMARY KEY (run_id, tick)
);

"""
Repository interface + SQLiteRepository.
The engine depends on the interface; SQL is here.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


# ──────────────────────────────────────────────────────────────────────────────
# Interface
# ──────────────────────────────────────────────────────────────────────────────

class Repository(Protocol):
    def start_run(self, config_json: str) -> int: ...
    def end_run(self, run_id: int) -> None: ...
    def save_agent(self, run_id: int, agent: object, tick: int) -> None: ...
    def save_event(self, run_id: int, event: dict, tick: int) -> int: ...
    def save_rule(self, run_id: int, rule: object) -> None: ...
    def save_places(self, run_id: int, places: list) -> None: ...


# ──────────────────────────────────────────────────────────────────────────────
# SQLite implementation
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL,
  config_json   TEXT NOT NULL,
  status        TEXT NOT NULL DEFAULT 'running'
);

CREATE TABLE IF NOT EXISTS agents (
  id            TEXT PRIMARY KEY,
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  name          TEXT NOT NULL,
  personality   TEXT NOT NULL,
  profile       TEXT NOT NULL,
  location      TEXT NOT NULL,
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
  status        TEXT NOT NULL DEFAULT 'proposed',
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

CREATE TABLE IF NOT EXISTS snapshots (
  run_id        INTEGER NOT NULL REFERENCES runs(id),
  tick          INTEGER NOT NULL,
  state_json    TEXT NOT NULL,
  PRIMARY KEY (run_id, tick)
);
"""


class SQLiteRepository:
    def __init__(self, db_path: str | Path = ":memory:"):
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def start_run(self, config_json: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (started_at, config_json) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), config_json),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def end_run(self, run_id: int) -> None:
        self._conn.execute(
            "UPDATE runs SET status='ended' WHERE id=?", (run_id,)
        )
        self._conn.commit()

    def save_agent(self, run_id: int, agent: object, tick: int) -> None:
        from ..engine.world import AgentState
        a: AgentState = agent  # type: ignore[assignment]
        self._conn.execute(
            """INSERT OR REPLACE INTO agents
               (id, run_id, name, personality, profile, location, energy, credits,
                mood, alive, zero_energy_turns, beliefs_json, relationships_json, updated_tick)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                a.id, run_id, a.name, a.personality, a.profile, a.location,
                a.energy, a.credits, a.mood, int(a.alive), a.zero_energy_turns,
                json.dumps(a.beliefs),
                json.dumps({
                    aid: {"type": r.type, "trust": r.trust, "interactions": r.interactions}
                    for aid, r in a.relationships.items()
                }),
                tick,
            ),
        )
        self._conn.commit()

    def save_event(self, run_id: int, event: dict, tick: int) -> int:
        cur = self._conn.execute(
            """INSERT INTO events
               (run_id, tick, kind, actor_id, target_id, profile, text, payload_json, ts)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                run_id, tick,
                event.get("kind", ""),
                event.get("actor_id"),
                event.get("target_id"),
                event.get("profile"),
                event.get("text"),
                json.dumps(event.get("payload", {})),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def save_rule(self, run_id: int, rule: object) -> None:
        from ..engine.world import RuleState
        r: RuleState = rule  # type: ignore[assignment]
        self._conn.execute(
            """INSERT OR REPLACE INTO rules
               (id, run_id, effect, text, proposer_id, status, votes_json, created_tick)
               VALUES (?,?,?,?,?,?,?,?)""",
            (r.id, run_id, r.effect, r.text, r.proposer_id,
             r.status, json.dumps(r.votes), r.created_tick),
        )
        self._conn.commit()

    def save_places(self, run_id: int, places: list) -> None:
        for p in places:
            self._conn.execute(
                """INSERT OR REPLACE INTO places (id, run_id, name, x, y, kind, description)
                   VALUES (?,?,?,?,?,?,?)""",
                (p.id, run_id, p.name, p.x, p.y, p.kind, p.description),
            )
        self._conn.commit()

    def recent_events(self, run_id: int, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT seq, tick, kind, actor_id, target_id, profile, text, payload_json, ts "
            "FROM events WHERE run_id=? ORDER BY seq DESC LIMIT ?",
            (run_id, limit),
        )
        rows = cur.fetchall()
        result = []
        for row in reversed(rows):
            seq, tick, kind, actor_id, target_id, profile, text, payload_json, ts = row
            result.append({
                "seq": seq, "tick": tick, "kind": kind,
                "actor_id": actor_id, "target_id": target_id,
                "profile": profile, "text": text,
                "payload": json.loads(payload_json or "{}"),
                "ts": ts,
            })
        return result

    def close(self) -> None:
        self._conn.close()

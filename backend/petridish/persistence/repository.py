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
    def save_world_snapshot(self, run_id: int, tick: int, state_json: str) -> None: ...


# ──────────────────────────────────────────────────────────────────────────────
# SQLite implementation
# ──────────────────────────────────────────────────────────────────────────────

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at    TEXT NOT NULL,
  ended_at      TEXT,                                -- W11a EM-086: null while running
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
        # W10 / EM-085: file-backed DBs may target a not-yet-existing directory
        # (the default config now points at <repo>/data/run.sqlite); create the
        # parent so sqlite3.connect never fails on a fresh checkout.
        if self._db_path != ":memory:" and not self._db_path.startswith("file:"):
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        # Durability + concurrency pragmas (contracts/event-log.md §6). journal_mode=WAL
        # is already set in SCHEMA; the rest are set here at connection open.
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self._conn.execute("PRAGMA wal_autocheckpoint = 1000")
        self._migrate_events_v1_1_0()
        self._migrate_runs_v1_3_0()
        self._conn.commit()

    def _migrate_events_v1_1_0(self) -> None:
        """Idempotent v1.0.0 -> v1.1.0 upgrade for file-backed DBs.

        Fresh DBs already get sim_time/actor_type/turn_id from SCHEMA's CREATE, so
        the guard skips them. Pre-v1.1.0 file DBs are missing those columns and get
        them added via ALTER TABLE (SQLite has no idempotent ADD COLUMN of its own).
        """
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(events)")}
        if "sim_time" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN sim_time REAL")
        if "actor_type" not in cols:
            self._conn.execute(
                "ALTER TABLE events ADD COLUMN actor_type TEXT NOT NULL "
                "DEFAULT 'human_agent'"
            )
        if "turn_id" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN turn_id TEXT")
        # Indices on the v1.1.0 columns are created AFTER the migration so a legacy
        # (v1.0.0) file DB — whose `events` table predates these columns — doesn't
        # fail `CREATE INDEX ... ON events(turn_id)` during schema bootstrap. These
        # mirror idx_events_run_turn/kind/actor in contracts/db-schema.sql.
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_turn ON events(run_id, turn_id)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_kind ON events(run_id, kind)"
        )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_run_actor ON events(run_id, actor_id)"
        )

    def _migrate_runs_v1_3_0(self) -> None:
        """Idempotent runs-table upgrade for pre-W11a file DBs (EM-086): add
        `ended_at` (null while running / for runs that crashed). Fresh DBs get
        it from SCHEMA's CREATE; the guard skips them."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
        if "ended_at" not in cols:
            self._conn.execute("ALTER TABLE runs ADD COLUMN ended_at TEXT")

    def start_run(self, config_json: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO runs (started_at, config_json) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), config_json),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def end_run(self, run_id: int) -> None:
        self._conn.execute(
            "UPDATE runs SET status='ended', ended_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), run_id),
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
        actor_type = event.get("actor_type") or "human_agent"
        cur = self._conn.execute(
            """INSERT INTO events
               (run_id, tick, sim_time, kind, actor_id, actor_type, target_id,
                profile, turn_id, text, payload_json, ts)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id, tick,
                event.get("sim_time"),
                event.get("kind", ""),
                event.get("actor_id"),
                actor_type,
                event.get("target_id"),
                event.get("profile"),
                event.get("turn_id"),
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

    def save_world_snapshot(self, run_id: int, tick: int, state_json: str) -> None:
        """Persist a world snapshot to bound replay cost (event-log.md §5).

        `state_json` is already a JSON string (engine serializes world.to_snapshot()).
        INSERT OR REPLACE keeps (run_id, tick) unique so re-snapshotting a tick is idempotent.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots (run_id, tick, state_json) VALUES (?,?,?)",
            (run_id, tick, state_json),
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

    # ──────────────────────────────────────────────────────────────────────────
    # Read interface (contracts/event-log.md §7). Run-scoped, read-only, JSON-ready.
    # EventRow = {seq, run_id, tick, sim_time, kind, actor_id, actor_type,
    #             target_id, profile, turn_id, text, payload, ts}.
    # ──────────────────────────────────────────────────────────────────────────

    _EVENT_COLS = (
        "seq, run_id, tick, sim_time, kind, actor_id, actor_type, target_id, "
        "profile, turn_id, text, payload_json, ts"
    )

    @staticmethod
    def _row_to_eventrow(row: tuple) -> dict:
        (seq, run_id, tick, sim_time, kind, actor_id, actor_type, target_id,
         profile, turn_id, text, payload_json, ts) = row
        return {
            "seq": seq,
            "run_id": run_id,
            "tick": tick,
            "sim_time": sim_time,
            "kind": kind,
            "actor_id": actor_id,
            "actor_type": actor_type,
            "target_id": target_id,
            "profile": profile,
            "turn_id": turn_id,
            "text": text,
            "payload": json.loads(payload_json or "{}"),
            "ts": ts,
        }

    def run_exists(self, run_id: int) -> bool:
        """True iff a run row with this id exists (W11a EM-086 — the REST layer
        validates an explicit ?run_id before scoping any read to it)."""
        row = self._conn.execute(
            "SELECT 1 FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        return row is not None

    @staticmethod
    def _config_summary(config_json: str | None) -> dict:
        """Small projection of runs.config_json for RunRow.config_summary
        (api.openapi.yaml v1.3.0): {agents: [{name, profile}], seed?} — NEVER
        the full blob. Tolerant of legacy blobs (pre-W11a runs stored only
        {"world": ...} with no agents key) and of malformed JSON."""
        try:
            cfg = json.loads(config_json or "{}")
        except (TypeError, ValueError):
            cfg = {}
        if not isinstance(cfg, dict):
            cfg = {}
        agents = []
        for a in cfg.get("agents") or []:
            if isinstance(a, dict):
                agents.append({"name": a.get("name"), "profile": a.get("profile")})
        summary: dict = {"agents": agents}
        world = cfg.get("world")
        seed = cfg.get("seed")
        if seed is None and isinstance(world, dict):
            seed = world.get("seed")
        if seed is not None:
            summary["seed"] = seed
        return summary

    def list_runs(self, active_run_id: int | None = None) -> list[dict]:
        """All persisted runs, newest first, as RunRow dicts (W11a EM-086).

        ONE query with LEFT JOIN aggregates (no N+1): max_tick = MAX(events.tick)
        (0 when the run has no events), event_count = COUNT(*). `is_active` is
        True ONLY for the run the live loop currently holds (`active_run_id`) —
        NEVER inferred from the `status` column, which crashes/hot-reloads leave
        'running' forever."""
        cur = self._conn.execute(
            """SELECT r.id, r.started_at, r.ended_at, r.status, r.config_json,
                      COALESCE(MAX(e.tick), 0) AS max_tick,
                      COUNT(e.seq)             AS event_count
               FROM runs r
               LEFT JOIN events e ON e.run_id = r.id
               GROUP BY r.id
               ORDER BY r.id DESC"""
        )
        out: list[dict] = []
        for rid, started_at, ended_at, status, config_json, max_tick, count in cur.fetchall():
            out.append({
                "id": rid,
                "started_at": started_at,
                "ended_at": ended_at,
                "status": status,
                "is_active": active_run_id is not None and rid == active_run_id,
                "max_tick": int(max_tick or 0),
                "event_count": int(count or 0),
                "config_summary": self._config_summary(config_json),
            })
        return out

    def get_events(
        self,
        run_id: int,
        *,
        from_tick: int | None = None,
        to_tick: int | None = None,
        kinds: list[str] | None = None,
        actor_id: str | None = None,
        turn_id: str | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
        order: str = "asc",
    ) -> list[dict]:
        clauses = ["run_id = ?"]
        params: list = [run_id]
        if from_tick is not None:
            clauses.append("tick >= ?")
            params.append(from_tick)
        if to_tick is not None:
            clauses.append("tick <= ?")
            params.append(to_tick)
        if kinds:
            clauses.append("kind IN (%s)" % ",".join("?" for _ in kinds))
            params.extend(kinds)
        if actor_id is not None:
            clauses.append("actor_id = ?")
            params.append(actor_id)
        if turn_id is not None:
            clauses.append("turn_id = ?")
            params.append(turn_id)
        if after_seq is not None:
            clauses.append("seq > ?")
            params.append(after_seq)
        direction = "DESC" if str(order).lower() == "desc" else "ASC"
        sql = (
            f"SELECT {self._EVENT_COLS} FROM events WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY seq {direction}"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        cur = self._conn.execute(sql, params)
        return [self._row_to_eventrow(r) for r in cur.fetchall()]

    def get_turn_trace(self, run_id: int, turn_id: str) -> list[dict]:
        """The full ordered chain for one turn (seq asc)."""
        cur = self._conn.execute(
            f"SELECT {self._EVENT_COLS} FROM events "
            "WHERE run_id = ? AND turn_id = ? ORDER BY seq ASC",
            (run_id, turn_id),
        )
        return [self._row_to_eventrow(r) for r in cur.fetchall()]

    def get_rule_history(self, run_id: int) -> list[dict]:
        """Per rule_id: lifecycle + votes + downstream events it caused (EM-057).

        Built from the rule_* event stream: rule_proposed seeds the entry; rule_vote
        appends votes; rule_passed/rule_rejected resolves it. `downstream` links later
        events that carry the same turn_id as the resolving event (e.g. an economy/ubi
        distribution, an agent_died) — best-effort, tolerant of missing turn_ids.
        """
        cur = self._conn.execute(
            f"SELECT {self._EVENT_COLS} FROM events "
            "WHERE run_id = ? AND kind LIKE 'rule_%' ORDER BY seq ASC",
            (run_id,),
        )
        rows = [self._row_to_eventrow(r) for r in cur.fetchall()]
        history: dict[str, dict] = {}
        order: list[str] = []

        def _rule_id_of(ev: dict) -> str | None:
            p = ev.get("payload") or {}
            return p.get("rule_id") or ev.get("target_id") or p.get("id")

        for ev in rows:
            rid = _rule_id_of(ev)
            if rid is None:
                continue
            entry = history.get(rid)
            if entry is None:
                entry = {
                    "rule_id": rid,
                    "effect": None,
                    "text": None,
                    "proposer_id": None,
                    "status": "proposed",
                    "created_tick": None,
                    "votes": [],
                    "resolved_tick": None,
                    "outcome": None,
                    "downstream": [],
                }
                history[rid] = entry
                order.append(rid)
            payload = ev.get("payload") or {}
            kind = ev.get("kind")
            if kind == "rule_proposed":
                entry["effect"] = payload.get("effect", entry["effect"])
                entry["text"] = payload.get("text") or ev.get("text") or entry["text"]
                entry["proposer_id"] = (
                    payload.get("proposer_id") or ev.get("actor_id") or entry["proposer_id"]
                )
                entry["created_tick"] = ev.get("tick")
            elif kind == "rule_vote":
                entry["votes"].append({
                    "voter_id": payload.get("voter_id") or ev.get("actor_id"),
                    "choice": payload.get("choice") or payload.get("vote"),
                    "tick": ev.get("tick"),
                })
            elif kind == "rule_passed":
                entry["status"] = "active"
                entry["resolved_tick"] = ev.get("tick")
                entry["outcome"] = "passed"
            elif kind == "rule_rejected":
                entry["status"] = "rejected"
                entry["resolved_tick"] = ev.get("tick")
                entry["outcome"] = "rejected"

        # downstream: events sharing the resolving turn_id that aren't rule_* themselves.
        resolving_turns: dict[str, str] = {}
        for ev in rows:
            rid = _rule_id_of(ev)
            if rid and ev.get("kind") in ("rule_passed", "rule_rejected") and ev.get("turn_id"):
                resolving_turns[ev["turn_id"]] = rid
        if resolving_turns:
            placeholders = ",".join("?" for _ in resolving_turns)
            cur = self._conn.execute(
                "SELECT seq, turn_id, kind FROM events "
                f"WHERE run_id = ? AND turn_id IN ({placeholders}) "
                "AND kind NOT LIKE 'rule_%' ORDER BY seq ASC",
                (run_id, *resolving_turns.keys()),
            )
            for seq, tid, _kind in cur.fetchall():
                rid = resolving_turns.get(tid)
                if rid and rid in history:
                    history[rid]["downstream"].append(seq)

        return [history[rid] for rid in order]

    def get_relationship_timeline(
        self,
        run_id: int,
        *,
        agent_id: str | None = None,
        from_tick: int | None = None,
        to_tick: int | None = None,
    ) -> list[dict]:
        """relationship + conflict + give events for the social graph (EM-058).

        `give` is modeled as an economy event whose payload action == 'give'.
        When agent_id is set, match it as either actor or target.
        """
        clauses = ["run_id = ?", "(kind IN ('relationship','conflict') OR kind = 'economy')"]
        params: list = [run_id]
        if from_tick is not None:
            clauses.append("tick >= ?")
            params.append(from_tick)
        if to_tick is not None:
            clauses.append("tick <= ?")
            params.append(to_tick)
        if agent_id is not None:
            clauses.append("(actor_id = ? OR target_id = ?)")
            params.extend([agent_id, agent_id])
        sql = (
            f"SELECT {self._EVENT_COLS} FROM events WHERE "
            + " AND ".join(clauses)
            + " ORDER BY seq ASC"
        )
        cur = self._conn.execute(sql, params)
        out: list[dict] = []
        for r in cur.fetchall():
            ev = self._row_to_eventrow(r)
            if ev["kind"] == "economy":
                # keep only the social-meaningful economy events (gifts).
                if (ev.get("payload") or {}).get("action") != "give":
                    continue
            out.append(ev)
        return out

    def get_snapshots(self, run_id: int) -> list[dict]:
        """[{tick}] ascending."""
        cur = self._conn.execute(
            "SELECT tick FROM snapshots WHERE run_id = ? ORDER BY tick ASC",
            (run_id,),
        )
        return [{"tick": row[0]} for row in cur.fetchall()]

    def nearest_snapshot(self, run_id: int, tick: int) -> dict | None:
        """Nearest snapshot with snapshot_tick <= tick: {tick, state} | None."""
        cur = self._conn.execute(
            "SELECT tick, state_json FROM snapshots "
            "WHERE run_id = ? AND tick <= ? ORDER BY tick DESC LIMIT 1",
            (run_id, tick),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {"tick": row[0], "state": json.loads(row[1] or "{}")}

    def get_analytics(
        self,
        run_id: int,
        *,
        from_tick: int | None = None,
        to_tick: int | None = None,
    ) -> dict:
        """The 9-AWI + model-vs-model spine (EM-059), computed from event rows.

        Returns the dict shape in event-log.md §7. by_model groups on events.profile;
        usage reads llm_call payloads (gen_ai.usage.*). Tolerant of nulls throughout.
        constitution.active_rules reads the rules table (true rule state) for the
        full-range view, with a rule_* event projection for tick-windowed queries.
        """
        events = self.get_events(run_id, from_tick=from_tick, to_tick=to_tick, order="asc")

        # population: alive count over time, derived from spawn/death events.
        population: list[dict] = []
        alive = 0
        crime_by_kind: dict[str, int] = {}
        crime_kinds = {"steal", "attack", "insult", "arson"}
        tools_by_agent: dict[str, set] = {}
        places_by_agent: dict[str, set] = {}
        proposed = passed = rejected = 0
        votes_cast = 0
        say_count = propose_rule_count = 0
        edges: set = set()
        edge_by_type: dict[str, int] = {}
        credits_by_agent: dict[str, int] = {}
        gives = 0
        amendments = 0
        # B9: per-rule status projection (last lifecycle event wins) so
        # active_rules can derive from rule STATE, not event arithmetic.
        rule_status: dict[str, str] = {}
        # by_model accumulators keyed on profile.
        by_model: dict[str, dict] = {}
        # usage accumulators keyed on profile.
        usage_by_profile: dict[str, dict] = {}

        def _model(profile: str | None) -> dict:
            key = profile or "unknown"
            m = by_model.get(key)
            if m is None:
                m = {
                    "alive": 0, "dead": 0, "crimes": 0, "gives": 0,
                    "proposals": 0, "passed": 0, "credit_share": 0.0,
                }
                by_model[key] = m
            return m

        # Track which profile each agent belongs to (for credit_share by model).
        agent_profile: dict[str, str | None] = {}
        agent_alive: dict[str, bool] = {}

        for ev in events:
            kind = ev.get("kind")
            payload = ev.get("payload") or {}
            actor = ev.get("actor_id")
            profile = ev.get("profile")
            if actor is not None and profile is not None:
                agent_profile.setdefault(actor, profile)

            if kind in ("agent_spawned", "agent_hot_spawned"):
                alive += 1
                if actor is not None:
                    agent_alive[actor] = True
                _model(profile)["alive"] += 1
                population.append({"tick": ev.get("tick"), "alive": alive})
            elif kind in ("agent_died", "animal_died"):
                alive = max(0, alive - 1)
                if actor is not None:
                    agent_alive[actor] = False
                m = _model(profile)
                m["dead"] += 1
                if m["alive"] > 0:
                    m["alive"] -= 1
                population.append({"tick": ev.get("tick"), "alive": alive})

            action = payload.get("action")
            if kind == "economy":
                if action == "give":
                    gives += 1
                    _model(profile)["gives"] += 1
                # latest per-agent credit balances if present in payloads.
                for who_key, bal_key in (("actor_id", "actor_credits"), ("target_id", "target_credits")):
                    who = ev.get(who_key) if who_key != "actor_id" else actor
                    bal = payload.get(bal_key)
                    if who is not None and isinstance(bal, (int, float)):
                        credits_by_agent[who] = int(bal)
                # generic credits snapshot in payload.
                bal = payload.get("credits")
                if actor is not None and isinstance(bal, (int, float)):
                    credits_by_agent[actor] = int(bal)

            if action in crime_kinds or kind in crime_kinds:
                ck = action if action in crime_kinds else kind
                crime_by_kind[ck] = crime_by_kind.get(ck, 0) + 1
                _model(profile)["crimes"] += 1

            # tool / space exploration from action_chosen + movement.
            if kind == "action_chosen":
                tool = payload.get("chosen_tool")
                if actor is not None and tool:
                    tools_by_agent.setdefault(actor, set()).add(tool)
            if kind == "agent_moved":
                # W9-QA-1b: the emitter writes the destination to payload.place;
                # keep to/location/target_id as fallbacks, mirroring the frontend
                # chain (selectors.ts replayStateAt, post-W9-QA-1).
                dest = (
                    payload.get("place")
                    or payload.get("to")
                    or payload.get("location")
                    or ev.get("target_id")
                )
                if actor is not None and dest:
                    places_by_agent.setdefault(actor, set()).add(dest)

            if kind in ("rule_proposed", "rule_passed", "rule_rejected", "rule_repealed"):
                # rule identity mirrors get_rule_history's extraction; a missing
                # id degrades to a per-event key so the row still projects.
                rid = (
                    payload.get("rule_id")
                    or ev.get("target_id")
                    or payload.get("id")
                    or f"__rule_seq_{ev.get('seq')}"
                )
            if kind == "rule_proposed":
                proposed += 1
                propose_rule_count += 1
                _model(profile)["proposals"] += 1
                rule_status.setdefault(rid, "proposed")
            elif kind == "rule_vote":
                votes_cast += 1
            elif kind == "rule_passed":
                passed += 1
                _model(profile)["passed"] += 1
                rule_status[rid] = "active"
            elif kind == "rule_rejected":
                rejected += 1
                rule_status[rid] = "rejected"
            elif kind == "rule_repealed":
                rule_status[rid] = "repealed"
            elif kind == "rule_amended":
                amendments += 1

            if kind == "agent_speech" or action == "say":
                say_count += 1

            if kind == "relationship":
                a, b = ev.get("actor_id"), ev.get("target_id")
                if a is not None and b is not None:
                    edges.add(tuple(sorted((a, b))))
                rtype = payload.get("type") or payload.get("relationship")
                if rtype:
                    edge_by_type[rtype] = edge_by_type.get(rtype, 0) + 1

            # usage: from llm_call OTel GenAI payloads.
            if kind == "llm_call":
                key = (payload.get("gen_ai.request.model") or profile or "unknown")
                u = usage_by_profile.get(key)
                if u is None:
                    u = {"requests": 0, "input_tokens": 0, "output_tokens": 0}
                    usage_by_profile[key] = u
                u["requests"] += 1
                it = payload.get("gen_ai.usage.input_tokens")
                ot = payload.get("gen_ai.usage.output_tokens")
                if isinstance(it, (int, float)):
                    u["input_tokens"] += int(it)
                if isinstance(ot, (int, float)):
                    u["output_tokens"] += int(ot)

        # Prefer snapshot-derived credits if event stream gave us nothing.
        if not credits_by_agent:
            snap = self.nearest_snapshot(run_id, to_tick if to_tick is not None else 10**12)
            if snap is not None:
                for a in (snap.get("state") or {}).get("agents", []) or []:
                    aid = a.get("id")
                    cr = a.get("credits")
                    if aid is not None and isinstance(cr, (int, float)):
                        credits_by_agent[aid] = int(cr)
                        agent_profile.setdefault(aid, a.get("profile"))

        # economy: gini + throughput + by_agent.
        throughput = sum(
            1 for ev in events if ev.get("kind") == "economy"
        )
        gini = _gini(list(credits_by_agent.values())) if credits_by_agent else None

        # credit_share by model.
        total_credits = sum(credits_by_agent.values())
        if total_credits > 0:
            model_credits: dict[str, int] = {}
            for aid, cr in credits_by_agent.items():
                key = agent_profile.get(aid) or "unknown"
                model_credits[key] = model_credits.get(key, 0) + cr
            for key, m in by_model.items():
                m["credit_share"] = round(model_credits.get(key, 0) / total_credits, 4)

        # governance participation: votes cast over (proposals * voters) is not cheaply
        # known; use votes / max(proposals,1) as a tolerant participation proxy.
        participation = round(votes_cast / proposed, 4) if proposed else 0.0

        # B9: active_rules derives from actual rules STATE, never from
        # `passed - rejected` arithmetic (a rejected PROPOSAL never deactivates a
        # passed rule). For the full-range view the rules table is the source of
        # truth (status='active'); the event projection covers tick-windowed
        # queries and event-only ingestion where the table has no rows.
        projected_active = sum(1 for s in rule_status.values() if s == "active")
        if from_tick is None and to_tick is None:
            row = self._conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) "
                "FROM rules WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            total_rule_rows = row[0] or 0
            active_rules = int(row[1] or 0) if total_rule_rows else projected_active
        else:
            active_rules = projected_active

        return {
            "population": population,
            "crime": {"by_kind": crime_by_kind},
            "tool_exploration": {
                "by_agent": {a: len(t) for a, t in tools_by_agent.items()}
            },
            "space_exploration": {
                "by_agent": {a: len(p) for a, p in places_by_agent.items()}
            },
            "governance": {
                "participation": participation,
                "proposed": proposed,
                "passed": passed,
                "rejected": rejected,
            },
            "public_expression": {
                "say": say_count,
                "propose_rule": propose_rule_count,
            },
            "social_fabric": {"edges": len(edges), "by_type": edge_by_type},
            "economy": {
                "gini": gini,
                "throughput": throughput,
                "by_agent": dict(credits_by_agent),
            },
            "constitution": {"active_rules": active_rules, "amendments": amendments},
            "by_model": by_model,
            "usage": {"by_profile": usage_by_profile},
        }

    def close(self) -> None:
        self._conn.close()


def _gini(values: list) -> float | None:
    """Gini coefficient over non-negative credit balances. None if undefined."""
    nums = [float(v) for v in values if v is not None]
    n = len(nums)
    if n == 0:
        return None
    total = sum(nums)
    if total <= 0:
        return 0.0
    nums.sort()
    cum = 0.0
    for i, v in enumerate(nums, start=1):
        cum += i * v
    # gini = (2*sum(i*x_i)/(n*sum)) - (n+1)/n
    return round((2.0 * cum) / (n * total) - (n + 1.0) / n, 4)

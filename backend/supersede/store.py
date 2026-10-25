"""Storage interface and the SQLite implementation.

Everything Supersede records goes through :class:`Store`, so SQLite can be
swapped for Postgres or Databricks Delta later by writing another class with
the same methods.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    workflow TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,              -- running | paused | completed | rejected
    run_time TEXT NOT NULL,            -- the business date the run acts on
    parent_run_id TEXT,
    forked_at INTEGER,                 -- step the fork restarted from
    fork_reason TEXT,
    paused_at INTEGER,
    pause_reason TEXT,
    options_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spans (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,
    agent TEXT NOT NULL,
    kind TEXT NOT NULL,                -- invoke_agent | chat | retrieval | execute_tool
    name TEXT NOT NULL,
    input_json TEXT,
    output_json TEXT,
    chunk_ids TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    started REAL NOT NULL,
    ended REAL NOT NULL,
    error TEXT,
    cached INTEGER NOT NULL DEFAULT 0  -- 1 = copied from the parent run by a fork
);
CREATE INDEX IF NOT EXISTS spans_run ON spans(run_id, step);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id TEXT NOT NULL,
    step INTEGER NOT NULL,             -- state AFTER this step (0 = initial state)
    state_json TEXT NOT NULL,
    PRIMARY KEY (run_id, step)
);
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    verdict TEXT NOT NULL,             -- correct | wrong | needs_review
    note TEXT,
    author TEXT,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    step INTEGER,
    kind TEXT NOT NULL,                -- breakpoint | resumed | forked | blocked | rejected
    detail_json TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analyses (
    run_id TEXT PRIMARY KEY,
    report_json TEXT NOT NULL,
    at TEXT NOT NULL
);
"""


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


class Store:
    """Interface. Implementations must provide every method below."""

    def create_run(self, run: dict) -> None: ...
    def update_run(self, run_id: str, **fields: Any) -> None: ...
    def get_run(self, run_id: str) -> dict | None: ...
    def list_runs(self) -> list[dict]: ...
    def add_span(self, span: dict) -> None: ...
    def spans(self, run_id: str) -> list[dict]: ...
    def save_checkpoint(self, run_id: str, step: int, state: dict) -> None: ...
    def checkpoint(self, run_id: str, step: int) -> dict | None: ...
    def checkpoints(self, run_id: str) -> list[tuple[int, dict]]: ...
    def add_feedback(self, item: dict) -> None: ...
    def feedback(self, run_id: str) -> list[dict]: ...
    def add_event(self, item: dict) -> None: ...
    def events(self, run_id: str) -> list[dict]: ...
    def save_analysis(self, run_id: str, report: dict, at: str) -> None: ...
    def analysis(self, run_id: str) -> dict | None: ...
    def children(self, run_id: str) -> list[dict]: ...
    def clear(self) -> None: ...


class SQLiteStore(Store):
    """SQLite store. ``path=':memory:'`` keeps everything in memory (tests)."""

    def __init__(self, path: str = "supersede.db") -> None:
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    # -- helpers -----------------------------------------------------------
    def _exec(self, sql: str, params: Iterable[Any] = ()) -> None:
        with self._lock:
            self._db.execute(sql, tuple(params))
            self._db.commit()

    def _all(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute(sql, tuple(params)).fetchall()]

    # -- runs --------------------------------------------------------------
    def create_run(self, run: dict) -> None:
        row = dict(run)
        row["options_json"] = _dumps(row.pop("options", {}))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self._exec(f"INSERT INTO runs ({cols}) VALUES ({marks})", row.values())

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        if "options" in fields:
            fields["options_json"] = _dumps(fields.pop("options"))
        sets = ", ".join(f"{k} = ?" for k in fields)
        self._exec(f"UPDATE runs SET {sets} WHERE id = ?", [*fields.values(), run_id])

    @staticmethod
    def _run_row(row: dict) -> dict:
        row["options"] = json.loads(row.pop("options_json") or "{}")
        return row

    def get_run(self, run_id: str) -> dict | None:
        rows = self._all("SELECT * FROM runs WHERE id = ?", [run_id])
        return self._run_row(rows[0]) if rows else None

    def list_runs(self) -> list[dict]:
        return [self._run_row(r) for r in self._all("SELECT * FROM runs ORDER BY created_at DESC, id")]

    def children(self, run_id: str) -> list[dict]:
        rows = self._all("SELECT * FROM runs WHERE parent_run_id = ? ORDER BY created_at", [run_id])
        return [self._run_row(r) for r in rows]

    # -- spans -------------------------------------------------------------
    def add_span(self, span: dict) -> None:
        row = dict(span)
        row["input_json"] = _dumps(row.pop("input", None))
        row["output_json"] = _dumps(row.pop("output", None))
        row["chunk_ids"] = _dumps(row.pop("chunk_ids", []))
        cols = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        self._exec(f"INSERT INTO spans ({cols}) VALUES ({marks})", row.values())

    def spans(self, run_id: str) -> list[dict]:
        out = []
        for r in self._all("SELECT * FROM spans WHERE run_id = ? ORDER BY step, started", [run_id]):
            r["input"] = json.loads(r.pop("input_json") or "null")
            r["output"] = json.loads(r.pop("output_json") or "null")
            r["chunk_ids"] = json.loads(r["chunk_ids"] or "[]")
            out.append(r)
        return out

    # -- checkpoints -------------------------------------------------------
    def save_checkpoint(self, run_id: str, step: int, state: dict) -> None:
        self._exec(
            "INSERT OR REPLACE INTO checkpoints (run_id, step, state_json) VALUES (?, ?, ?)",
            [run_id, step, _dumps(state)],
        )

    def checkpoint(self, run_id: str, step: int) -> dict | None:
        rows = self._all("SELECT state_json FROM checkpoints WHERE run_id = ? AND step = ?", [run_id, step])
        return json.loads(rows[0]["state_json"]) if rows else None

    def checkpoints(self, run_id: str) -> list[tuple[int, dict]]:
        rows = self._all("SELECT step, state_json FROM checkpoints WHERE run_id = ? ORDER BY step", [run_id])
        return [(r["step"], json.loads(r["state_json"])) for r in rows]

    # -- feedback, events, analyses ---------------------------------------
    def add_feedback(self, item: dict) -> None:
        cols = ", ".join(item)
        self._exec(f"INSERT INTO feedback ({cols}) VALUES ({', '.join('?' for _ in item)})", item.values())

    def feedback(self, run_id: str) -> list[dict]:
        return self._all("SELECT * FROM feedback WHERE run_id = ? ORDER BY at", [run_id])

    def add_event(self, item: dict) -> None:
        row = dict(item)
        row["detail_json"] = _dumps(row.pop("detail", {}))
        cols = ", ".join(row)
        self._exec(f"INSERT INTO events ({cols}) VALUES ({', '.join('?' for _ in row)})", row.values())

    def events(self, run_id: str) -> list[dict]:
        out = []
        for r in self._all("SELECT * FROM events WHERE run_id = ? ORDER BY at, id", [run_id]):
            r["detail"] = json.loads(r.pop("detail_json"))
            out.append(r)
        return out

    def save_analysis(self, run_id: str, report: dict, at: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO analyses (run_id, report_json, at) VALUES (?, ?, ?)",
            [run_id, _dumps(report), at],
        )

    def analysis(self, run_id: str) -> dict | None:
        rows = self._all("SELECT report_json FROM analyses WHERE run_id = ?", [run_id])
        return json.loads(rows[0]["report_json"]) if rows else None

    def clear(self) -> None:
        """Delete everything (used by the demo reset button)."""
        with self._lock:
            for table in ("runs", "spans", "checkpoints", "feedback", "events", "analyses"):
                self._db.execute(f"DELETE FROM {table}")
            self._db.commit()

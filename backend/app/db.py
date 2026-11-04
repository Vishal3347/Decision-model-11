"""SQLite persistence: schema, connection helper and small query utilities."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    sender_name TEXT NOT NULL,
    sender_email TEXT NOT NULL,
    sender_type TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    category TEXT NOT NULL,
    priority TEXT NOT NULL,
    priority_score REAL,
    status TEXT NOT NULL DEFAULT 'new',
    selected_action TEXT,
    decision_id INTEGER,
    sender_importance TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT NOT NULL,
    run_id TEXT,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    provider TEXT,
    final_decision TEXT NOT NULL,
    execution_status TEXT NOT NULL,
    priority_score REAL,
    priority_label TEXT,
    risk_score REAL,
    risk_label TEXT,
    intent TEXT,
    chosen_action TEXT,
    requires_human INTEGER DEFAULT 0,
    duration_ms REAL,
    summary TEXT,
    record_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER NOT NULL,
    email_id TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    gate_kind TEXT,
    rule_ids_json TEXT,
    proposed_steps_json TEXT NOT NULL,
    final_steps_json TEXT,
    feedback TEXT,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT,
    decision_id INTEGER,
    title TEXT NOT NULL,
    description TEXT,
    task_type TEXT NOT NULL DEFAULT 'task',
    ticket_ref TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    priority TEXT NOT NULL DEFAULT 'Medium',
    due_at TEXT,
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id INTEGER,
    email_id TEXT,
    approval_id INTEGER,
    step_id TEXT,
    tool TEXT NOT NULL,
    params_json TEXT,
    result_json TEXT,
    success INTEGER NOT NULL,
    simulated INTEGER NOT NULL DEFAULT 1,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT,
    kind TEXT NOT NULL,
    channel TEXT,
    recipients TEXT,
    subject TEXT,
    message TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'meeting',
    attendees TEXT,
    external INTEGER NOT NULL DEFAULT 0,
    email_id TEXT,
    created_by TEXT NOT NULL DEFAULT 'seed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sim_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    reference TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    email_id TEXT,
    decision_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT,
    email_id TEXT,
    decision_id INTEGER,
    stage TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'info',
    message TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_activity_email ON activity(email_id);
CREATE INDEX IF NOT EXISTS idx_activity_run ON activity(run_id);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    current_email_id TEXT,
    current_stage TEXT,
    email_ids_json TEXT NOT NULL,
    total INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS preferences (
    intent TEXT NOT NULL,
    action TEXT NOT NULL,
    approvals INTEGER NOT NULL DEFAULT 0,
    rejections INTEGER NOT NULL DEFAULT 0,
    modifications INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (intent, action)
);

CREATE TABLE IF NOT EXISTS feedback_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    approval_id INTEGER,
    email_id TEXT,
    intent TEXT,
    action TEXT,
    kind TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS briefings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generated_at TEXT NOT NULL,
    content_json TEXT NOT NULL
);
"""

DERIVED_TABLES = [
    "decisions", "approvals", "tasks", "executions", "notifications", "outbox",
    "sim_records", "activity", "runs", "briefings", "feedback_events",
]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


class Database:
    """Thin wrapper that hands out autocommit SQLite connections (WAL mode)."""

    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._lock = threading.Lock()
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit atomic section on an autocommit connection."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def q(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def q1(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> dict | None:
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def ex(conn: sqlite3.Connection, sql: str, params: tuple | list = ()) -> int:
    cur = conn.execute(sql, params)
    return cur.lastrowid or 0


def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    row = q1(conn, "SELECT value FROM settings WHERE key=?", (key,))
    return loads(row["value"], default) if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, dumps(value)),
    )

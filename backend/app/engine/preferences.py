"""Learned preferences from human feedback.

This is NOT model training. Approvals / rejections / modifications simply adjust counters that
(a) nudge the expected-utility score of an action for a given intent, and
(b) after repeated rejections, add a soft "ask first" gate. Mandatory policies are never relaxed.
"""
from __future__ import annotations

import sqlite3

from ..constants import (PREF_APPROVAL_BONUS, PREF_CLAMP, PREF_MODIFICATION_PENALTY, PREF_REJECTION_PENALTY,
                         PREF_SOFT_GATE_REJECTIONS)
from ..db import ex, q, q1
from ..clock import iso, now
from ..schemas import ActionType


def load_preferences(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    return {(r["intent"], r["action"]): r for r in q(conn, "SELECT * FROM preferences")}


def adjustment(prefs: dict, intent: str, action: ActionType) -> float:
    r = prefs.get((intent, action.value))
    if not r:
        return 0.0
    raw = r["approvals"] * PREF_APPROVAL_BONUS - r["rejections"] * PREF_REJECTION_PENALTY - r["modifications"] * PREF_MODIFICATION_PENALTY
    return max(PREF_CLAMP[0], min(PREF_CLAMP[1], raw))


def soft_gate_tools(prefs: dict, intent: str, action: ActionType, tools: list[str]) -> set[str]:
    """If the human rejected this action twice or more, ask first for its (otherwise automatic) tools."""
    r = prefs.get((intent, action.value))
    return set(tools) if r and r["rejections"] >= PREF_SOFT_GATE_REJECTIONS else set()


def record_feedback(conn: sqlite3.Connection, *, approval_id: int | None, email_id: str, intent: str, action: str,
                    kind: str, note: str | None) -> None:
    """kind ∈ approved | rejected | modified"""
    col = {"approved": "approvals", "rejected": "rejections", "modified": "modifications"}[kind]
    if not q1(conn, "SELECT 1 FROM preferences WHERE intent=? AND action=?", (intent, action)):
        ex(conn, "INSERT INTO preferences(intent, action) VALUES(?,?)", (intent, action))
    conn.execute(f"UPDATE preferences SET {col}={col}+1 WHERE intent=? AND action=?", (intent, action))
    ex(conn, "INSERT INTO feedback_events(approval_id, email_id, intent, action, kind, note, created_at) VALUES(?,?,?,?,?,?,?)",
       (approval_id, email_id, intent, action, kind, note, iso(now())))


def summary(conn: sqlite3.Connection) -> list[dict]:
    rows = q(conn, "SELECT * FROM preferences ORDER BY intent, action")
    for r in rows:
        r["adjustment"] = adjustment({(r["intent"], r["action"]): r}, r["intent"], ActionType(r["action"]))
        r["ask_first"] = r["rejections"] >= PREF_SOFT_GATE_REJECTIONS
    return rows

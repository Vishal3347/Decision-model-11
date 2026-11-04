"""Simulated tool execution. Every tool only writes rows to the local SQLite database."""
from __future__ import annotations

import sqlite3
from typing import Any

from pydantic import ValidationError

from .. import clock
from ..db import dumps, ex, get_setting, loads, q1, set_setting
from ..engine.policy import revalidate_for_execution
from ..schemas import PlanStep, ToolName as T
from .catalog import validate_params


def _ticket_ref(conn: sqlite3.Connection, prefix: str) -> str:
    n = int(get_setting(conn, "ticket_seq", 1000)) + 1
    set_setting(conn, "ticket_seq", n)
    return f"{prefix}-{n}"


def _record(conn, kind, ref, detail, email_id, decision_id) -> None:
    ex(conn, "INSERT INTO sim_records(kind, reference, detail_json, email_id, decision_id, created_at) VALUES(?,?,?,?,?,?)",
       (kind, ref, dumps(detail), email_id, decision_id, clock.iso(clock.now())))


def run_tool(conn: sqlite3.Connection, step: PlanStep, *, email_id: str, decision_id: int | None) -> dict[str, Any]:
    """Execute one already-authorised step. Raises ValueError for refused/invalid steps."""
    refusal = revalidate_for_execution(step)
    if refusal:
        raise ValueError(refusal)
    try:
        p = validate_params(step.tool, step.params)
    except ValidationError as e:
        raise ValueError("Invalid parameters: " + "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:3])) from None
    now = clock.iso(clock.now())
    t = step.tool

    if t == T.create_task:
        tid = ex(conn, "INSERT INTO tasks(email_id, decision_id, title, description, task_type, status, priority, due_at, created_at, completed_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                 (email_id, decision_id, p["title"], p["description"], p["task_type"], p["status"], p["priority"], p["due_at"], now,
                  now if p["status"] == "completed" else None))
        return {"task_id": tid, "message": f"Task #{tid} created: {p['title']}"}
    if t == T.create_ticket:
        ref = _ticket_ref(conn, "INC")
        ex(conn, "INSERT INTO tasks(email_id, decision_id, title, description, task_type, ticket_ref, status, priority, created_at) VALUES(?,?,?,?,?,?,?,?,?)",
           (email_id, decision_id, p["title"], p["description"], "incident", ref, "open", "Critical" if p["severity"] == "P1" else "High", now))
        _record(conn, "ticket", ref, p, email_id, decision_id)
        return {"ticket": ref, "message": f"Incident ticket {ref} ({p['severity']}) opened for {p['owner_team']}"}
    if t == T.send_notification:
        ex(conn, "INSERT INTO notifications(email_id, kind, channel, recipients, subject, message, created_at) VALUES(?,?,?,?,?,?,?)",
           (email_id, "notification", p["channel"], ", ".join(p["recipients"]), p["subject"], p["message"], now))
        return {"message": f"Notification posted to {p['channel']} for {', '.join(p['recipients'])}"}
    if t == T.escalate_to_manager:
        ex(conn, "INSERT INTO notifications(email_id, kind, channel, recipients, subject, message, created_at) VALUES(?,?,?,?,?,?,?)",
           (email_id, "escalation", "escalation", p["manager"], "Escalation", p["message"], now))
        return {"message": f"Escalated to {p['manager']}"}
    if t == T.send_email:
        ex(conn, "INSERT INTO outbox(email_id, to_addr, subject, body, status, created_at) VALUES(?,?,?,?, 'simulated_sent', ?)",
           (email_id, p["to"], p["subject"], p["body"], now))
        return {"message": f"Email to {p['to']} recorded in simulated outbox (nothing was sent)"}
    if t == T.create_calendar_event:
        eid = ex(conn, "INSERT INTO calendar_events(title, start_at, end_at, kind, attendees, external, email_id, created_by, created_at) VALUES(?,?,?,?,?,?,?, 'agent', ?)",
                 (p["title"], p["start_at"], p["end_at"], p["kind"], ", ".join(p["attendees"]), int(step.external), email_id, now))
        return {"event_id": eid, "message": f"Calendar {p['kind']} created: {p['title']}"}
    if t == T.reschedule_meeting:
        existing = None
        if p["from_start"]:
            existing = q1(conn, "SELECT id FROM calendar_events WHERE title LIKE ? AND date(start_at)=date(?) ORDER BY id LIMIT 1",
                          (f"%{p['title'].split(' ')[0]} {p['title'].split(' ')[1] if ' ' in p['title'] else ''}%".strip(), p["from_start"]))
        if existing:
            conn.execute("UPDATE calendar_events SET start_at=?, end_at=?, created_by='agent' WHERE id=?", (p["to_start"], p["to_end"], existing["id"]))
            return {"event_id": existing["id"], "message": f"Moved '{p['title']}' to {p['to_start'][:16].replace('T', ' ')}"}
        eid = ex(conn, "INSERT INTO calendar_events(title, start_at, end_at, kind, attendees, external, email_id, created_by, created_at) VALUES(?,?,?, 'meeting', ?,0,?, 'agent', ?)",
                 (p["title"], p["to_start"], p["to_end"], ", ".join(p["attendees"]), email_id, now))
        return {"event_id": eid, "message": f"Scheduled '{p['title']}' for {p['to_start'][:16].replace('T', ' ')}"}
    if t == T.complete_task:
        tid = ex(conn, "INSERT INTO tasks(email_id, decision_id, title, task_type, status, priority, created_at, completed_at) VALUES(?,?,?, 'task', 'completed', 'Low', ?, ?)",
                 (email_id, decision_id, p["title"], now, now))
        return {"task_id": tid, "message": f"Task completed: {p['title']}"}
    if t == T.archive_email:
        conn.execute("UPDATE emails SET status=CASE WHEN status IN ('new','processing') THEN 'archived' ELSE status END WHERE id=?", (email_id,))
        return {"message": "Email archived"}
    if t == T.process_payment:
        ref = _ticket_ref(conn, "PAY")
        _record(conn, "payment", ref, p, email_id, decision_id)
        return {"reference": ref, "message": f"SIMULATED payment {ref}: ₹{p['amount']:,.0f} to {p['vendor']} — no money moved"}
    if t == T.sign_contract:
        ref = _ticket_ref(conn, "SIG")
        _record(conn, "signature", ref, p, email_id, decision_id)
        return {"reference": ref, "message": f"SIMULATED signature {ref} on '{p['document']}' — no real contract signed"}
    if t == T.delete_records:
        ref = _ticket_ref(conn, "DEL")
        _record(conn, "deletion", ref, p, email_id, decision_id)
        return {"reference": ref, "message": f"SIMULATED purge {ref}: {p['record_count']:,} records — nothing was actually deleted"}
    if t == T.approve_leave:
        ref = _ticket_ref(conn, "HR")
        _record(conn, "leave", ref, p, email_id, decision_id)
        return {"reference": ref, "message": f"Leave recorded in simulated HR system for {p['employee']} ({p['days']} days)"}
    raise ValueError(f"Unknown tool {t}")

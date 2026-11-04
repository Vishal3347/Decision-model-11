"""Realistic fictional enterprise inbox and calendar used to seed the database."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from . import clock
from .constants import DEFAULT_WEIGHTS
from .db import DERIVED_TABLES, ex, q1, set_setting
from .schemas import Mode

EMAIL_IDS = [f"EML-{1000 + i}" for i in range(1, 13)]


def _next_weekday(ref: datetime, weekday: int, hour: int, minute: int = 0) -> datetime:
    days = (weekday - ref.weekday()) % 7 or 7
    d = ref + timedelta(days=days)
    return d.replace(hour=hour, minute=minute, second=0, microsecond=0)


def build_emails(now: datetime) -> list[dict]:
    def ago(**kw) -> str:
        return clock.iso(now - timedelta(**kw))

    return [
        dict(
            id="EML-1001", sender_name="Engineering Team", sender_email="eng-oncall@helixai.example", sender_type="internal",
            subject="[SEV-1] Production services unavailable — customers cannot access the platform",
            body=(
                "SEV-1 declared.\n\n"
                "All production services are returning 503 errors. Customers cannot access the platform: the web app, "
                "the API and the document-processing queue are all unavailable. Roughly 1,200 active enterprise users "
                "are affected and two customers have already called support.\n\n"
                "On-call engineers are investigating; root cause is not yet identified. Leadership needs to be informed "
                "immediately.\n\n— Engineering Team (on-call: Arjun / Meera)"
            ),
            timestamp=ago(minutes=6), category="Engineering", priority="Critical", sender_importance="Critical",
        ),
        dict(
            id="EML-1002", sender_name="Neha Sharma (Kestrel Logistics)", sender_email="neha.sharma@kestrellogistics.example", sender_type="external",
            subject="Request for DocuMind demo — invoice processing",
            body=(
                "Hello,\n\nI'm Neha Sharma, Head of Operations at Kestrel Logistics. We process roughly 40,000 supplier "
                "invoices every month and are evaluating AI document processing solutions. A colleague recommended "
                "DocuMind.\n\nCould we schedule a 45-minute demonstration next week? Tuesday or Wednesday afternoon "
                "would work best. We would especially like to see invoice extraction and exception handling.\n\n"
                "Regards,\nNeha Sharma\nHead of Operations, Kestrel Logistics"
            ),
            timestamp=ago(hours=2, minutes=15), category="Sales", priority="Medium", sender_importance="Normal",
        ),
        dict(
            id="EML-1003", sender_name="Finance Department (Anita Rao)", sender_email="finance@helixai.example", sender_type="internal",
            subject="Approval needed: vendor payment ₹2,50,000 — CloudNest Hosting (INV-88231)",
            body=(
                "Hi,\n\nPlease approve the following vendor payment so it can be released before the due date.\n\n"
                "Vendor: CloudNest Hosting Pvt Ltd\nInvoice: INV-88231\nAmount: ₹2,50,000\nDue: Wednesday\n"
                "Purpose: Q4 infrastructure hosting\n\n"
                "A late fee of 1.5% applies after the due date. Budget code IT-OPS-114 has sufficient allocation.\n\n"
                "Thanks,\nAnita Rao, Finance Controller"
            ),
            timestamp=ago(hours=1, minutes=50), category="Finance", priority="High", sender_importance="High",
        ),
        dict(
            id="EML-1004", sender_name="HR Department", sender_email="hr@helixai.example", sender_type="internal",
            subject="Reminder: weekly team meeting tomorrow at 11 AM",
            body=(
                "Reminder: our weekly team meeting is tomorrow at 11 AM in Conference Room Aurora (and on Teams).\n\n"
                "Agenda: sprint review, hiring updates, Q4 planning.\n\n— HR Department"
            ),
            timestamp=ago(hours=7), category="HR", priority="Low", sender_importance="Low",
        ),
        dict(
            id="EML-1005", sender_name="Priya Nair (Business Development)", sender_email="priya.nair@helixai.example", sender_type="internal",
            subject="Follow-up: Atlas Retail has not responded to our proposal",
            body=(
                "Hi,\n\nAtlas Retail has not responded to the proposal we sent 9 days ago (DocuMind rollout across 40 "
                "stores, ₹18,00,000 first-year value). Their procurement lead, Rakesh Menon "
                "(rakesh.menon@atlasretail.example), opened the document twice last week but we have heard nothing since.\n\n"
                "Can we follow up before the end of this week? A short note plus a task to check in again would be ideal.\n\n"
                "Priya Nair, Business Development Lead"
            ),
            timestamp=ago(hours=4), category="Business Development", priority="Medium", sender_importance="Normal",
        ),
        dict(
            id="EML-1006", sender_name="Legal Department (Vikram Desai)", sender_email="legal@helixai.example", sender_type="internal",
            subject="Contract ready for signature: Master Services Agreement — Atlas Retail",
            body=(
                "The Master Services Agreement with Atlas Retail (3-year term, ₹42,00,000 total value) is final and "
                "ready for signature.\n\nLegal review is complete and there are no open redlines. Signature is required "
                "by Friday to hold the pilot start date.\n\nVikram Desai, Legal Counsel"
            ),
            timestamp=ago(hours=3), category="Legal", priority="High", sender_importance="High",
        ),
        dict(
            id="EML-1007", sender_name="Marcus Lee (Orion Banking Group)", sender_email="marcus.lee@orionbank.example", sender_type="external",
            subject="CRITICAL: document processing failing on loan applications",
            body=(
                "Dear team,\n\nSince this morning roughly 30% of our loan-application documents are failing extraction "
                "with timeout errors. Our compliance team has a regulatory filing deadline today and this is blocking us. "
                "This is a critical issue and we need an immediate response and an ETA for a fix — otherwise we will "
                "have to invoke the SLA breach clause.\n\nMarcus Lee\nCTO, Orion Banking Group"
            ),
            timestamp=ago(minutes=22), category="Customer Support", priority="Critical", sender_importance="Critical",
        ),
        dict(
            id="EML-1008", sender_name="IT Security", sender_email="secops@helixai.example", sender_type="internal",
            subject="Security alert SEC-2291: unusual login activity on admin account",
            body=(
                "SecOps alert SEC-2291.\n\nMultiple failed logins followed by a successful login for admin account "
                "svc-billing from an unfamiliar IP address (outside our usual regions) at 02:13 IST. MFA bypass is "
                "suspected. The session accessed the billing configuration page.\n\n"
                "Recommended: investigate immediately and consider credential rotation.\n\n— IT Security"
            ),
            timestamp=ago(minutes=41), category="Security", priority="Critical", sender_importance="Critical",
        ),
        dict(
            id="EML-1009", sender_name="Siddharth Verma", sender_email="siddharth.verma@helixai.example", sender_type="internal",
            subject="Leave request: 3 days (12–14 Nov)",
            body=(
                "Hi,\n\nI would like to request three days of leave from 12 November to 14 November for a family "
                "function. My tasks are covered — Meera will handle the Orion integration while I'm away and I have "
                "shared a handover document.\n\nThanks,\nSiddharth Verma"
            ),
            timestamp=ago(hours=6), category="HR", priority="Low", sender_importance="Low",
        ),
        dict(
            id="EML-1010", sender_name="Kavya Iyer (Project Manager)", sender_email="kavya.iyer@helixai.example", sender_type="internal",
            subject="Can we reschedule Thursday's Project Phoenix sync?",
            body=(
                "Hi,\n\nThursday's Project Phoenix sync at 10:00 AM clashes with the client workshop. Could we "
                "reschedule it to Friday at 3:00 PM? All attendees are internal and I've checked that the room is "
                "free.\n\nKavya Iyer, Project Manager"
            ),
            timestamp=ago(hours=5, minutes=20), category="Project Management", priority="Medium", sender_importance="Normal",
        ),
        dict(
            id="EML-1011", sender_name="Compliance Office", sender_email="compliance@helixai.example", sender_type="internal",
            subject="Data retention DR-7: purge archived customer records older than 7 years",
            body=(
                "As per data retention policy DR-7, archived trial and marketing records older than 7 years must be "
                "purged.\n\nScope: 14,203 archived customer records (trial accounts and marketing contacts, 2015–2019)\n"
                "Request: confirm permanent deletion of these records\n\n— Compliance Office"
            ),
            timestamp=ago(days=1), category="Compliance", priority="Medium", sender_importance="Normal",
        ),
        dict(
            id="EML-1012", sender_name="AI Weekly Digest", sender_email="digest@aiweekly.example", sender_type="external",
            subject="This week in enterprise AI: pricing changes, new benchmarks",
            body=(
                "This week in enterprise AI: model pricing changes, three new document-understanding benchmarks, and a "
                "webinar on responsible automation. Read the full digest on our website. Unsubscribe any time."
            ),
            timestamp=ago(days=1, hours=3), category="Newsletter", priority="Low", sender_importance="Low",
        ),
    ]


def build_calendar(now: datetime) -> list[dict]:
    thu = _next_weekday(now, 3, 10)
    return [
        dict(title="Project Phoenix Sync", start_at=clock.iso(thu), end_at=clock.iso(thu + timedelta(hours=1)),
             kind="meeting", attendees="Kavya Iyer, Arjun, Meera", external=0),
        dict(title="Orion Banking — client workshop", start_at=clock.iso(thu), end_at=clock.iso(thu + timedelta(hours=2)),
             kind="meeting", attendees="Orion Banking Group", external=1),
        dict(title="Quarterly Business Review", start_at=clock.iso(_next_weekday(now, 2, 16)),
             end_at=clock.iso(_next_weekday(now, 2, 17)), kind="meeting", attendees="Leadership team", external=0),
        dict(title="Investor update call", start_at=clock.iso(_next_weekday(now, 4, 11)),
             end_at=clock.iso(_next_weekday(now, 4, 12)), kind="meeting", attendees="Board, CFO", external=1),
    ]


def seed_database(conn: sqlite3.Connection, now: datetime | None = None, keep_preferences: bool = False) -> None:
    """Wipe all application data and re-create the demo inbox, calendar and default settings."""
    now = now or clock.now()
    for table in DERIVED_TABLES + ["emails", "calendar_events", "settings"]:
        conn.execute(f"DELETE FROM {table}")
    if not keep_preferences:
        conn.execute("DELETE FROM preferences")
    conn.execute("DELETE FROM sqlite_sequence")

    for e in build_emails(now):
        ex(
            conn,
            "INSERT INTO emails(id, sender_name, sender_email, sender_type, subject, body, timestamp, category, "
            "priority, status, sender_importance) VALUES(?,?,?,?,?,?,?,?,?, 'new', ?)",
            (e["id"], e["sender_name"], e["sender_email"], e["sender_type"], e["subject"], e["body"],
             e["timestamp"], e["category"], e["priority"], e["sender_importance"]),
        )
    for c in build_calendar(now):
        ex(
            conn,
            "INSERT INTO calendar_events(title, start_at, end_at, kind, attendees, external, created_by, created_at) "
            "VALUES(?,?,?,?,?,?, 'seed', ?)",
            (c["title"], c["start_at"], c["end_at"], c["kind"], c["attendees"], c["external"], clock.iso(now)),
        )
    set_setting(conn, "mode", Mode.AUTONOMOUS.value)
    set_setting(conn, "weights", DEFAULT_WEIGHTS)
    set_setting(conn, "ticket_seq", 1000)


def ensure_seeded(conn: sqlite3.Connection) -> bool:
    """Seed only when the database is empty. Returns True if it seeded."""
    if q1(conn, "SELECT COUNT(*) AS n FROM emails")["n"] == 0:
        seed_database(conn)
        return True
    return False

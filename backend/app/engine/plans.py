"""Playbooks: turn an abstract action (e.g. ESCALATE) into concrete, parameterised tool steps."""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from .. import clock
from ..constants import PRODUCT, USER_NAME
from ..schemas import ActionType as A
from ..schemas import ContextResult, Intent as I, Observation, PlanStep, ToolName as T
from ..tools.catalog import classify, is_external, validate_params
from .heuristics import draft_for
from .observation import resolve_day

ESCALATION = {
    I.PRODUCTION_INCIDENT: ("Engineering", "#eng-oncall", "VP Engineering", ["Engineering on-call"]),
    I.SECURITY_ALERT: ("Security", "#security-ops", "CISO", ["Security on-call", "IT Security"]),
    I.CUSTOMER_COMPLAINT: ("Customer Support", "#support-escalations", "Head of Customer Success", ["Support lead", "Engineering lead"]),
}
CHANNEL_BY_INTENT = {
    I.PAYMENT_APPROVAL: ("#finance", ["Finance team"]),
    I.CONTRACT_SIGNATURE: ("#legal", ["Legal team"]),
    I.DATA_DELETION: ("#compliance", ["Compliance office"]),
    I.SALES_INQUIRY: ("#sales", ["Sales team"]),
    I.PROPOSAL_FOLLOWUP: ("#business-development", ["BD team"]),
    I.MEETING_RESCHEDULE: ("#project-phoenix", ["Kavya Iyer", "Arjun", "Meera"]),
}


def _short(text: str, n: int = 90) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _step(n: int, tool: T, title: str, params: dict[str, Any], why: str = "") -> PlanStep:
    clean = validate_params(tool, params)
    return PlanStep(
        step_id=f"s{n}", tool=tool, title=title, params=clean,
        action_class=classify(tool, clean), external=is_external(tool, clean), rationale=why,
    )


def _meeting_title(obs: Observation) -> str:
    m = re.search(r"(Project [A-Z][a-z]+ sync)", f"{obs.subject} {obs.excerpt}", re.I)
    return m.group(1).title() if m else "Project meeting"


def _reminder_title(obs: Observation) -> str:
    t = re.sub(r"^(reminder|re|fwd)\s*:\s*", "", obs.subject, flags=re.I)
    t = re.sub(r"\s+(tomorrow|today)\b.*$", "", t, flags=re.I)
    return t[:1].upper() + t[1:]


def _default_start(obs: Observation, now: datetime, hour: int = 9) -> datetime:
    if obs.datetimes:
        return datetime.fromisoformat(obs.datetimes[0]).replace(tzinfo=now.tzinfo)
    return (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)


def _leave_dates(obs: Observation, now: datetime) -> tuple[datetime, datetime]:
    m = re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+to\s+(\d{1,2})\s+([A-Za-z]+)", f"{obs.subject} {obs.excerpt}")
    if m:
        try:
            s = datetime.strptime(f"{m.group(1)} {m.group(2)[:3]} {now.year}", "%d %b %Y").replace(tzinfo=now.tzinfo)
            e = datetime.strptime(f"{m.group(3)} {m.group(4)[:3]} {now.year}", "%d %b %Y").replace(tzinfo=now.tzinfo)
            if e < now - timedelta(days=30):
                s, e = s.replace(year=now.year + 1), e.replace(year=now.year + 1)
            return s, e
        except ValueError:
            pass
    s = (now + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    return s, s + timedelta(days=2)


def _external_contact(obs: Observation) -> str:
    for addr in obs.emails_found:
        if not addr.lower().endswith("@helixai.example"):
            return addr
    return obs.sender_email


def _draft_body(ctx: ContextResult, intent: I, obs: Observation) -> str:
    return (ctx.draft_reply or draft_for(intent, obs)
            or f"Hello,\n\nThank you for your message regarding “{_short(obs.subject, 60)}”. We have received it and will respond shortly.\n\nRegards,\n{USER_NAME}")


def build_plan(action: A, intent: I, obs: Observation, ctx: ContextResult, now: datetime, priority_label: str = "Medium") -> list[PlanStep]:
    steps: list[PlanStep] = []

    def add(tool: T, title: str, params: dict[str, Any], why: str = "") -> None:
        steps.append(_step(len(steps) + 1, tool, title, params, why))

    subject = _short(obs.subject)
    summary = _short(ctx.summary, 400)

    if action == A.IGNORE:
        return steps

    if action == A.ARCHIVE:
        add(T.archive_email, "Archive email", {"reason": "No action required"}, "Low-value message; keep the inbox clean.")

    elif action == A.CREATE_TASK:
        followup = intent == I.PROPOSAL_FOLLOWUP
        add(T.create_task, "Create follow-up task" if followup else "Create task",
            {"title": f"Review: {subject}", "description": summary, "priority": priority_label,
             "due_at": clock.iso(now + timedelta(days=3 if followup else 1)), "task_type": "followup" if followup else "task"},
            "Track the work internally.")

    elif action == A.NOTIFY_INTERNAL:
        channel, recipients = CHANNEL_BY_INTENT.get(intent, ("#ops", ["Operations"]))
        add(T.send_notification, f"Notify {recipients[0]}", {"channel": channel, "recipients": recipients,
            "subject": subject, "message": summary}, "Make the right internal team aware.")

    elif action == A.ESCALATE:
        team, channel, manager, recipients = ESCALATION.get(intent, ("Operations", "#ops-escalations", "Chief of Staff", ["Operations lead"]))
        if intent in ESCALATION:
            sev_word = "incident" if intent != I.CUSTOMER_COMPLAINT else "support"
            add(T.create_ticket, f"Create P1 {sev_word} ticket",
                {"title": f"[P1] {subject}", "description": summary, "severity": "P1", "owner_team": team},
                "Critical issue needs a tracked owner.")
        add(T.send_notification, f"Notify {recipients[0]}" + (" & leads" if len(recipients) > 1 else ""),
            {"channel": channel, "recipients": recipients, "subject": f"[P1] {subject}", "message": summary},
            "The owning team must act immediately.")
        add(T.escalate_to_manager, f"Escalate to {manager}", {"manager": manager, "message": f"{summary} Escalated by the executive assistant agent."},
            "Leadership needs to own this situation.")
        if intent == I.CUSTOMER_COMPLAINT:
            add(T.send_email, "Send acknowledgement to customer (draft)",
                {"to": obs.sender_email, "subject": f"Re: {obs.subject}", "body": _draft_body(ctx, intent, obs)},
                "Customer is waiting for an acknowledgement and ETA; this is an external commitment.")

    elif action == A.DRAFT_RESPONSE:
        if intent == I.PROPOSAL_FOLLOWUP:
            add(T.create_task, "Create follow-up task",
                {"title": "Check in with Atlas Retail if no reply", "description": summary, "priority": priority_label,
                 "due_at": clock.iso(now + timedelta(days=3)), "task_type": "followup"}, "Make sure the follow-up is tracked.")
            add(T.send_email, "Send follow-up email to client (draft)",
                {"to": _external_contact(obs), "subject": "Following up on our DocuMind proposal", "body": _draft_body(ctx, intent, obs)},
                "Re-engage the client.")
        elif intent == I.LEAVE_REQUEST:
            s, e = _leave_dates(obs, now)
            add(T.approve_leave, "Approve leave (HR system)", {"employee": obs.sender_name, "start_date": clock.iso(s), "end_date": clock.iso(e),
                "days": (e - s).days + 1}, "Personnel decision.")
            add(T.send_email, "Send confirmation to employee (draft)",
                {"to": obs.sender_email, "subject": f"Re: {obs.subject}", "body": _draft_body(ctx, intent, obs)}, "Let the employee know.")
        else:
            add(T.send_email, "Send reply (draft)", {"to": obs.sender_email, "subject": f"Re: {obs.subject}", "body": _draft_body(ctx, intent, obs)},
                "A response is expected.")

    elif action == A.SCHEDULE_MEETING:
        if intent == I.MEETING_REMINDER:
            start = _default_start(obs, now, 11)
            title = _reminder_title(obs)
            add(T.create_calendar_event, "Create calendar reminder",
                {"title": title, "start_at": clock.iso(start), "end_at": clock.iso(start + timedelta(hours=1)), "attendees": ["Team"], "kind": "reminder"},
                "Routine reminder; no commitment involved.")
            add(T.complete_task, "Mark reminder task completed", {"title": f"Acknowledge: {title}"}, "Nothing further is required.")
        elif intent == I.MEETING_RESCHEDULE:
            title = _meeting_title(obs)
            to_start = datetime.fromisoformat(obs.datetimes[1]).replace(tzinfo=now.tzinfo) if len(obs.datetimes) > 1 else (now + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
            from_start = obs.datetimes[0] if obs.datetimes else None
            attendees = ["Kavya Iyer", "Arjun", "Meera"]
            add(T.reschedule_meeting, "Reschedule meeting", {"title": title, "from_start": from_start, "to_start": clock.iso(to_start),
                "to_end": clock.iso(to_start + timedelta(hours=1)), "attendees": attendees}, "All attendees are internal.")
            add(T.send_notification, "Notify attendees", {"channel": "#project-phoenix", "recipients": attendees, "subject": f"{title} moved",
                "message": f"{title} has been moved to {to_start.strftime('%A %I:%M %p').replace(' 0', ' ')}."}, "Keep attendees informed.")
        elif intent == I.SALES_INQUIRY:
            tue = resolve_day("tuesday", now).replace(hour=15, minute=0, second=0, microsecond=0)
            add(T.send_email, "Send demo invitation (draft)", {"to": obs.sender_email, "subject": f"Re: {obs.subject}", "body": _draft_body(ctx, intent, obs)},
                "Offer concrete slots.")
            add(T.create_calendar_event, f"Hold {PRODUCT} demo slot",
                {"title": f"{PRODUCT} demo — {obs.sender_name.split('(')[-1].strip(') ') or 'prospect'}", "start_at": clock.iso(tue),
                 "end_at": clock.iso(tue + timedelta(minutes=45)), "attendees": [obs.sender_email, USER_NAME], "kind": "meeting"},
                "Tentative hold; involves an external party.")
        else:
            start = _default_start(obs, now)
            add(T.create_calendar_event, "Create calendar event", {"title": subject, "start_at": clock.iso(start),
                "end_at": clock.iso(start + timedelta(hours=1)), "attendees": [USER_NAME], "kind": "meeting"})

    elif action == A.REQUEST_APPROVAL:
        f = obs.fields
        if intent == I.PAYMENT_APPROVAL and obs.amounts:
            amount = max(a.value for a in obs.amounts)
            vendor = f.get("vendor", "Unknown vendor")
            budget = re.search(r"budget code\s+([A-Z0-9-]+)", obs.excerpt + " " + f.get("purpose", ""), re.I)
            add(T.process_payment, "Release vendor payment (simulated)", {"vendor": vendor, "invoice": f.get("invoice", "n/a"), "amount": amount,
                "currency": "INR", "budget_code": budget.group(1) if budget else None}, "Financial transactions always need human approval.")
            add(T.send_notification, "Confirm to Finance", {"channel": "#finance", "recipients": ["Finance team"], "subject": f"Payment released: {f.get('invoice', '')}",
                "message": f"Payment of {obs.amounts[0].raw} to {vendor} approved and processed (simulated)."}, "Close the loop with Finance.")
        elif intent == I.CONTRACT_SIGNATURE:
            document = obs.subject.split(":", 1)[1].strip() if ":" in obs.subject else obs.subject
            counterparty = document.split("—")[-1].strip() if "—" in document else "Counterparty"
            add(T.sign_contract, "Sign contract (simulated)", {"document": document, "counterparty": counterparty,
                "value": max((a.value for a in obs.amounts), default=None)}, "Signing is binding and irreversible.")
            add(T.send_notification, "Confirm to Legal", {"channel": "#legal", "recipients": ["Legal team"], "subject": "Contract signed (simulated)",
                "message": f"{document} signed (simulated)."}, "Legal needs the executed copy.")
        elif intent == I.DATA_DELETION:
            count = int(re.sub(r"\D", "", re.search(r"[\d,]{3,}", f.get("scope", "0")).group(0) if re.search(r"[\d,]{3,}", f.get("scope", "")) else "0") or 0)
            policy = re.search(r"\bDR-\d+\b", obs.subject + " " + obs.excerpt)
            add(T.delete_records, "Purge archived records (simulated)", {"record_type": "archived_customer_records", "scope": f.get("scope", obs.subject)[:300],
                "record_count": count, "retention_policy": policy.group(0) if policy else ""}, "Deletion is irreversible.")
            add(T.send_notification, "Confirm to Compliance", {"channel": "#compliance", "recipients": ["Compliance office"], "subject": "Purge completed (simulated)",
                "message": f"{count:,} records purged under retention policy (simulated; nothing was actually deleted)."}, "Compliance requires confirmation.")
        elif intent == I.LEAVE_REQUEST:
            return build_plan(A.DRAFT_RESPONSE, intent, obs, ctx, now, priority_label)
        else:
            add(T.create_task, "Create decision task", {"title": f"Needs your decision: {subject}", "description": summary, "priority": "High",
                "due_at": clock.iso(now + timedelta(days=1))}, "A human must decide.")

    return steps

"""Deterministic knowledge shared by the mock reasoner and the validation layer.

* ``classify_intent``     – keyword/signal based intent classifier (also used to stop an LLM from
                            down-grading critical situations).
* ``baseline_context``    – the mock provider's "reasoning": a full ``LLMContext``-shaped dict.
* ``FIT``                 – how well each candidate action fits each intent (input to expected utility).
* ``deterministic_floors``– minimum urgency/impact/time scores implied by hard signals.
"""
from __future__ import annotations

from datetime import datetime

from ..constants import COMPANY, PRODUCT, USER_NAME
from ..schemas import ActionType as A
from ..schemas import FinalDecision as F
from ..schemas import Intent as I
from ..schemas import Observation

CRITICAL_INTENTS = {I.PRODUCTION_INCIDENT, I.SECURITY_ALERT}


def classify_intent(obs: Observation) -> I:
    s = obs.signals
    if len(s.get("outage", [])) >= 2:
        return I.PRODUCTION_INCIDENT
    if len(s.get("security", [])) >= 2:
        return I.SECURITY_ALERT
    if any(k in s.get("deletion", []) for k in ("purge", "permanent deletion")):
        return I.DATA_DELETION
    if "signature" in s.get("contract", []):
        return I.CONTRACT_SIGNATURE
    if obs.amounts and "payment" in s.get("financial", []):
        return I.PAYMENT_APPROVAL
    if len(s.get("complaint", [])) >= 2:
        return I.CUSTOMER_COMPLAINT
    if "leave" in s:
        return I.LEAVE_REQUEST
    if "reschedule" in s and "meeting" in s:
        return I.MEETING_RESCHEDULE
    if "demo" in s:
        return I.SALES_INQUIRY
    if "followup" in s:
        return I.PROPOSAL_FOLLOWUP
    if "reminder" in s and "meeting" in s:
        return I.MEETING_REMINDER
    if "newsletter" in s:
        return I.NEWSLETTER
    return I.GENERAL


# scores = (urgency, business_impact, time_sensitivity, customer_importance)
# risk   = (financial, security, irreversibility, external_comm, business_consequences) of acting autonomously
# decision is what an *eager* assistant would propose; policies may override it.
INTENT_BASE: dict[I, dict] = {
    I.PRODUCTION_INCIDENT: dict(scores=(10, 10, 10, 9), risk=(1, 1, 2, 1, 2), action=A.ESCALATE, decision=F.ESCALATE),
    I.SECURITY_ALERT: dict(scores=(9, 9, 9, 6), risk=(1, 3, 2, 1, 3), action=A.ESCALATE, decision=F.ESCALATE),
    I.CUSTOMER_COMPLAINT: dict(scores=(9, 8, 9, 9), risk=(2, 2, 6, 7, 5), action=A.DRAFT_RESPONSE, decision=F.AUTO_EXECUTE),
    I.PAYMENT_APPROVAL: dict(scores=(7, 7, 8, 4), risk=(7, 3, 8, 6, 6), action=A.REQUEST_APPROVAL, decision=F.AUTO_EXECUTE),
    I.CONTRACT_SIGNATURE: dict(scores=(6, 8, 7, 7), risk=(7, 2, 9, 8, 9), action=A.REQUEST_APPROVAL, decision=F.AUTO_EXECUTE),
    I.DATA_DELETION: dict(scores=(4, 6, 4, 3), risk=(2, 3, 10, 2, 8), action=A.REQUEST_APPROVAL, decision=F.AUTO_EXECUTE),
    I.SALES_INQUIRY: dict(scores=(5, 7, 5, 7), risk=(2, 2, 6, 8, 5), action=A.SCHEDULE_MEETING, decision=F.AUTO_EXECUTE),
    I.PROPOSAL_FOLLOWUP: dict(scores=(5, 7, 5, 7), risk=(2, 2, 6, 7, 4), action=A.DRAFT_RESPONSE, decision=F.DRAFT_AND_APPROVE),
    I.MEETING_REMINDER: dict(scores=(4, 2, 6, 1), risk=(1, 1, 1, 1, 1), action=A.SCHEDULE_MEETING, decision=F.SCHEDULE),
    I.MEETING_RESCHEDULE: dict(scores=(5, 4, 6, 2), risk=(1, 1, 3, 2, 3), action=A.SCHEDULE_MEETING, decision=F.SCHEDULE),
    I.LEAVE_REQUEST: dict(scores=(3, 3, 4, 1), risk=(2, 1, 5, 2, 3), action=A.REQUEST_APPROVAL, decision=F.DRAFT_AND_APPROVE),
    I.NEWSLETTER: dict(scores=(1, 1, 1, 1), risk=(1, 1, 1, 1, 1), action=A.ARCHIVE, decision=F.IGNORE),
    I.GENERAL: dict(scores=(4, 4, 4, 3), risk=(1, 1, 2, 2, 2), action=A.CREATE_TASK, decision=F.AUTO_EXECUTE),
}

_DEFAULT_FIT = 0.05
FIT: dict[I, dict[A, float]] = {
    I.PRODUCTION_INCIDENT: {A.ESCALATE: 0.98, A.NOTIFY_INTERNAL: 0.75, A.CREATE_TASK: 0.60, A.DRAFT_RESPONSE: 0.15, A.SCHEDULE_MEETING: 0.20, A.REQUEST_APPROVAL: 0.10, A.ARCHIVE: 0.0, A.IGNORE: 0.0},
    I.SECURITY_ALERT: {A.ESCALATE: 0.97, A.NOTIFY_INTERNAL: 0.70, A.CREATE_TASK: 0.60, A.REQUEST_APPROVAL: 0.25, A.DRAFT_RESPONSE: 0.10, A.SCHEDULE_MEETING: 0.10, A.ARCHIVE: 0.0, A.IGNORE: 0.0},
    I.CUSTOMER_COMPLAINT: {A.ESCALATE: 0.90, A.DRAFT_RESPONSE: 0.75, A.NOTIFY_INTERNAL: 0.65, A.CREATE_TASK: 0.60, A.REQUEST_APPROVAL: 0.20, A.SCHEDULE_MEETING: 0.15, A.ARCHIVE: 0.0, A.IGNORE: 0.0},
    I.PAYMENT_APPROVAL: {A.REQUEST_APPROVAL: 0.97, A.CREATE_TASK: 0.35, A.NOTIFY_INTERNAL: 0.30, A.DRAFT_RESPONSE: 0.25, A.ESCALATE: 0.20, A.SCHEDULE_MEETING: 0.05, A.ARCHIVE: 0.02, A.IGNORE: 0.02},
    I.CONTRACT_SIGNATURE: {A.REQUEST_APPROVAL: 0.97, A.CREATE_TASK: 0.40, A.NOTIFY_INTERNAL: 0.35, A.DRAFT_RESPONSE: 0.20, A.ESCALATE: 0.20, A.SCHEDULE_MEETING: 0.10, A.ARCHIVE: 0.02, A.IGNORE: 0.02},
    I.DATA_DELETION: {A.REQUEST_APPROVAL: 0.95, A.CREATE_TASK: 0.40, A.NOTIFY_INTERNAL: 0.30, A.ARCHIVE: 0.15, A.DRAFT_RESPONSE: 0.20, A.ESCALATE: 0.15, A.SCHEDULE_MEETING: 0.05, A.IGNORE: 0.05},
    I.SALES_INQUIRY: {A.SCHEDULE_MEETING: 0.90, A.DRAFT_RESPONSE: 0.80, A.CREATE_TASK: 0.50, A.NOTIFY_INTERNAL: 0.45, A.ESCALATE: 0.10, A.REQUEST_APPROVAL: 0.15, A.ARCHIVE: 0.02, A.IGNORE: 0.02},
    I.PROPOSAL_FOLLOWUP: {A.DRAFT_RESPONSE: 0.90, A.CREATE_TASK: 0.60, A.NOTIFY_INTERNAL: 0.30, A.SCHEDULE_MEETING: 0.30, A.ESCALATE: 0.10, A.REQUEST_APPROVAL: 0.15, A.ARCHIVE: 0.02, A.IGNORE: 0.02},
    I.MEETING_REMINDER: {A.SCHEDULE_MEETING: 0.92, A.CREATE_TASK: 0.50, A.NOTIFY_INTERNAL: 0.30, A.ARCHIVE: 0.20, A.IGNORE: 0.15, A.DRAFT_RESPONSE: 0.10, A.ESCALATE: 0.02, A.REQUEST_APPROVAL: 0.05},
    I.MEETING_RESCHEDULE: {A.SCHEDULE_MEETING: 0.90, A.DRAFT_RESPONSE: 0.50, A.NOTIFY_INTERNAL: 0.40, A.CREATE_TASK: 0.30, A.REQUEST_APPROVAL: 0.10, A.ESCALATE: 0.03, A.ARCHIVE: 0.02, A.IGNORE: 0.02},
    I.LEAVE_REQUEST: {A.REQUEST_APPROVAL: 0.90, A.DRAFT_RESPONSE: 0.70, A.CREATE_TASK: 0.40, A.NOTIFY_INTERNAL: 0.30, A.SCHEDULE_MEETING: 0.10, A.ESCALATE: 0.03, A.ARCHIVE: 0.05, A.IGNORE: 0.05},
    I.NEWSLETTER: {A.ARCHIVE: 0.90, A.IGNORE: 0.85, A.CREATE_TASK: 0.05, A.NOTIFY_INTERNAL: 0.03, A.DRAFT_RESPONSE: 0.0, A.SCHEDULE_MEETING: 0.0, A.ESCALATE: 0.0, A.REQUEST_APPROVAL: 0.0},
    I.GENERAL: {A.CREATE_TASK: 0.60, A.NOTIFY_INTERNAL: 0.50, A.DRAFT_RESPONSE: 0.40, A.ARCHIVE: 0.30, A.IGNORE: 0.20, A.REQUEST_APPROVAL: 0.20, A.SCHEDULE_MEETING: 0.15, A.ESCALATE: 0.10},
}


def fit_for(intent: I, action: A) -> float:
    return FIT.get(intent, FIT[I.GENERAL]).get(action, _DEFAULT_FIT)


def deterministic_floors(obs: Observation, intent: I) -> dict[str, float]:
    """Minimum scores implied by hard signals; an LLM may not score below these."""
    floors = {"urgency": 1.0, "business_impact": 1.0, "time_sensitivity": 1.0}
    if len(obs.signals.get("outage", [])) >= 2 or intent == I.PRODUCTION_INCIDENT:
        floors = {"urgency": 9.0, "business_impact": 9.0, "time_sensitivity": 9.0}
    elif len(obs.signals.get("security", [])) >= 2 or intent == I.SECURITY_ALERT:
        floors = {"urgency": 8.0, "business_impact": 8.0, "time_sensitivity": 8.0}
    elif intent == I.CUSTOMER_COMPLAINT:
        floors = {"urgency": 7.0, "business_impact": 7.0, "time_sensitivity": 7.0}
    if obs.amounts and max(a.value for a in obs.amounts) >= 1_000_000:
        floors["business_impact"] = max(floors["business_impact"], 7.0)
    return floors


# ----------------------------------------------------------------------------- mock "reasoning"
def _first_name(name: str) -> str:
    return name.split("(")[0].strip().split(" ")[0] or "there"


def _amount_text(obs: Observation) -> str:
    return obs.amounts[0].raw if obs.amounts else ""


def summarize(intent: I, obs: Observation) -> str:
    f = obs.fields
    amt = _amount_text(obs)
    mapping = {
        I.PRODUCTION_INCIDENT: "Production outage: all services return errors and customers cannot access the platform.",
        I.SECURITY_ALERT: "Suspicious successful login to an admin account from an unfamiliar IP; MFA bypass suspected.",
        I.CUSTOMER_COMPLAINT: f"Enterprise customer ({obs.sender_name}) reports document-processing failures and threatens an SLA breach.",
        I.PAYMENT_APPROVAL: f"Finance requests approval of a {amt} payment to {f.get('vendor', 'a vendor')} (invoice {f.get('invoice', 'n/a')}), due {f.get('due', 'soon')}.",
        I.CONTRACT_SIGNATURE: "Legal has a final Master Services Agreement ready and needs a signature by Friday.",
        I.DATA_DELETION: f"Compliance asks to confirm permanent deletion of {f.get('scope', 'archived records')}.",
        I.SALES_INQUIRY: "Prospective customer asks for a 45-minute DocuMind demo next week (invoice processing).",
        I.PROPOSAL_FOLLOWUP: "A client has not responded to a proposal sent 9 days ago; BD asks for a follow-up.",
        I.MEETING_REMINDER: "HR reminds the team of the weekly meeting tomorrow at 11 AM.",
        I.MEETING_RESCHEDULE: "Project manager asks to move Thursday's Project Phoenix sync to Friday 3:00 PM (all internal).",
        I.LEAVE_REQUEST: "Employee requests three days of leave (12–14 Nov) with a handover plan.",
        I.NEWSLETTER: "Marketing newsletter with no required action.",
        I.GENERAL: f"General message from {obs.sender_name}.",
    }
    return mapping[intent][:400]


def rationale_for(intent: I) -> str:
    mapping = {
        I.PRODUCTION_INCIDENT: "Customer-facing outage with broad impact; needs immediate human ownership, an incident ticket and engineering notification.",
        I.SECURITY_ALERT: "Possible account takeover on a privileged account; security team and CISO must be engaged now.",
        I.CUSTOMER_COMPLAINT: "Critical issue for a key enterprise customer with SLA exposure; escalate internally and prepare an acknowledgement.",
        I.PAYMENT_APPROVAL: "Legitimate vendor invoice within budget; payment release is a financial action that needs sign-off.",
        I.CONTRACT_SIGNATURE: "Legal review is complete; signing is binding and irreversible so a human must sign.",
        I.DATA_DELETION: "Retention policy requires purging old records; permanent deletion is irreversible.",
        I.SALES_INQUIRY: "High-value prospect; propose demo slots and hold time on the calendar.",
        I.PROPOSAL_FOLLOWUP: "Deal is stalling; send a polite follow-up and track a check-in task.",
        I.MEETING_REMINDER: "Routine internal reminder; add a calendar reminder and close it out.",
        I.MEETING_RESCHEDULE: "Internal reschedule with free room; update the calendar and notify attendees.",
        I.LEAVE_REQUEST: "Leave request with coverage; approval is a personnel decision.",
        I.NEWSLETTER: "Bulk newsletter with no action required; archive.",
        I.GENERAL: "No special handling detected; track as a task.",
    }
    return mapping[intent]


def draft_for(intent: I, obs: Observation) -> str | None:
    name = _first_name(obs.sender_name)
    sign = f"Best regards,\n{USER_NAME}\n{COMPANY}"
    if intent == I.CUSTOMER_COMPLAINT:
        return (
            f"Dear {name},\n\nThank you for flagging this and apologies for the disruption. We have opened a priority-1 "
            "incident for the document-processing timeouts and our engineering and customer-success leads are engaged now. "
            "We will share a status update and an ETA for the fix within the next hour.\n\n" + sign
        )
    if intent == I.SALES_INQUIRY:
        return (
            f"Hi {name},\n\nThank you for your interest in {PRODUCT}. We would be glad to run a 45-minute demonstration "
            "focused on invoice extraction and exception handling. Would Tuesday at 3:00 PM IST or Wednesday at 3:00 PM IST "
            "next week suit you?\n\n" + sign
        )
    if intent == I.PROPOSAL_FOLLOWUP:
        return (
            "Hi Rakesh,\n\nI wanted to follow up on the DocuMind proposal we shared last week. Happy to walk through any "
            "questions or adjust the rollout plan for your 40 stores. Would a short call this week work?\n\n" + sign
        )
    if intent == I.LEAVE_REQUEST:
        return (
            f"Hi {name},\n\nYour leave from 12 to 14 November is approved. Thanks for sharing the handover document; "
            "please make sure Meera has access to the Orion integration notes before you go.\n\nRegards,\n" + USER_NAME
        )
    return None


def baseline_context(obs: Observation, now: datetime | None = None) -> dict:
    """The mock provider's deterministic analysis, shaped exactly like ``LLMContext``."""
    intent = classify_intent(obs)
    base = INTENT_BASE[intent]
    u, i, t, c = (float(x) for x in base["scores"])
    if len(obs.signals.get("urgent", [])) >= 3:
        u = min(10.0, u + 1)
    if obs.amounts and max(a.value for a in obs.amounts) >= 1_000_000:
        i = min(10.0, i + 1)
    fin, sec, irr, ext, biz = (float(x) for x in base["risk"])
    f = obs.fields
    entities: dict = {}
    if obs.amounts:
        entities["amount"] = obs.amounts[0].value
    for key in ("vendor", "invoice", "scope", "request", "purpose", "due"):
        if key in f:
            entities[key] = f[key]
    return dict(
        intent=intent.value,
        summary=summarize(intent, obs),
        urgency=u, business_impact=i, time_sensitivity=t, customer_importance=c,
        risk_factors=dict(financial_exposure=fin, security_implications=sec, irreversibility=irr,
                          external_communication=ext, business_consequences=biz),
        recommended_action=base["action"].value,
        proposed_decision=base["decision"].value,
        rationale=rationale_for(intent),
        draft_reply=draft_for(intent, obs),
        entities=entities,
    )

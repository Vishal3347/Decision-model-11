"""Tunable defaults and thresholds shared across the engine."""
from __future__ import annotations

from .schemas import ActionType

USER_NAME = "Rohan Kapoor"
USER_TITLE = "VP Operations"
COMPANY = "Helix AI"
PRODUCT = "DocuMind"

# Priority score = weighted sum (1-10 scale). Weights are configurable at runtime and must sum to 1.
DEFAULT_WEIGHTS = {
    "urgency": 0.35,
    "business_impact": 0.30,
    "time_sensitivity": 0.20,
    "customer_importance": 0.15,
}

PRIORITY_THRESHOLDS = [("Critical", 8.0), ("High", 6.5), ("Medium", 4.0)]  # else "Low"
RISK_THRESHOLDS = [("High", 6.5), ("Medium", 3.5)]  # else "Low"
RISK_GATE = 6.5  # a step at or above this risk always needs approval (POL-RISK-006)

# Risk = 0.6 * weighted average of factors + 0.4 * worst factor.
RISK_FACTOR_WEIGHTS = {
    "financial_exposure": 0.25,
    "security_implications": 0.15,
    "irreversibility": 0.20,
    "external_communication": 0.20,
    "business_consequences": 0.20,
}
RISK_AVG_SHARE = 0.6

# Hard ceiling for any simulated payment (blocked even with approval).
PAYMENT_HARD_CAP = 1_000_000.0
PROTECTED_RECORD_TYPES = {"audit_logs", "financial_records", "legal_contracts"}

MAX_LOOP_ITERATIONS = 8

# --- Expected-utility model parameters (see engine/options.py) ---
BASE_RELIABILITY = {
    ActionType.IGNORE: 0.99,
    ActionType.ARCHIVE: 0.99,
    ActionType.CREATE_TASK: 0.97,
    ActionType.DRAFT_RESPONSE: 0.85,
    ActionType.NOTIFY_INTERNAL: 0.97,
    ActionType.SCHEDULE_MEETING: 0.88,
    ActionType.ESCALATE: 0.92,
    ActionType.REQUEST_APPROVAL: 0.90,
}
EFFORT_COST = {
    ActionType.IGNORE: 0.0,
    ActionType.ARCHIVE: 1.0,
    ActionType.CREATE_TASK: 3.0,
    ActionType.NOTIFY_INTERNAL: 3.0,
    ActionType.SCHEDULE_MEETING: 5.0,
    ActionType.ESCALATE: 6.0,
    ActionType.DRAFT_RESPONSE: 7.0,
    ActionType.REQUEST_APPROVAL: 7.0,
}
# How badly a failed/misapplied action hurts, as a share of its plan risk.
EXPOSURE = {
    ActionType.CREATE_TASK: 0.2,
    ActionType.NOTIFY_INTERNAL: 0.2,
    ActionType.SCHEDULE_MEETING: 0.5,
    ActionType.ESCALATE: 0.4,
    ActionType.DRAFT_RESPONSE: 0.5,
    ActionType.REQUEST_APPROVAL: 0.3,
}
LLM_SUGGESTION_BONUS = 4.0

# Satisficing (bounded rationality) criteria
SATISFICE_MIN_FIT = 0.6
SATISFICE_MAX_RISK = 6.5
SATISFICE_ASPIRATION_SHARE = 0.35
# Cheapest-effort-first evaluation order for the satisficer
SATISFICE_ORDER = [
    ActionType.IGNORE, ActionType.ARCHIVE, ActionType.NOTIFY_INTERNAL, ActionType.CREATE_TASK,
    ActionType.SCHEDULE_MEETING, ActionType.ESCALATE, ActionType.DRAFT_RESPONSE, ActionType.REQUEST_APPROVAL,
]

# Learned preferences (feedback) – counters only; the LLM is never retrained.
PREF_APPROVAL_BONUS = 2.0
PREF_REJECTION_PENALTY = 6.0
PREF_MODIFICATION_PENALTY = 1.5
PREF_CLAMP = (-25.0, 8.0)
PREF_SOFT_GATE_REJECTIONS = 2

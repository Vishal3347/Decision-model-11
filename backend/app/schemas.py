"""Pydantic models shared by the decision engine, LLM layer, orchestrator and API."""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- enums
class Mode(str, Enum):
    AUTONOMOUS = "AUTONOMOUS"
    HUMAN_CONTROLLED = "HUMAN_CONTROLLED"


class FinalDecision(str, Enum):
    AUTO_EXECUTE = "AUTO_EXECUTE"
    DRAFT_AND_APPROVE = "DRAFT_AND_APPROVE"
    ESCALATE = "ESCALATE"
    SCHEDULE = "SCHEDULE"
    IGNORE = "IGNORE"


class ActionType(str, Enum):
    IGNORE = "IGNORE"
    ARCHIVE = "ARCHIVE"
    CREATE_TASK = "CREATE_TASK"
    DRAFT_RESPONSE = "DRAFT_RESPONSE"
    NOTIFY_INTERNAL = "NOTIFY_INTERNAL"
    SCHEDULE_MEETING = "SCHEDULE_MEETING"
    ESCALATE = "ESCALATE"
    REQUEST_APPROVAL = "REQUEST_APPROVAL"


class Intent(str, Enum):
    PRODUCTION_INCIDENT = "PRODUCTION_INCIDENT"
    SECURITY_ALERT = "SECURITY_ALERT"
    CUSTOMER_COMPLAINT = "CUSTOMER_COMPLAINT"
    PAYMENT_APPROVAL = "PAYMENT_APPROVAL"
    CONTRACT_SIGNATURE = "CONTRACT_SIGNATURE"
    DATA_DELETION = "DATA_DELETION"
    SALES_INQUIRY = "SALES_INQUIRY"
    PROPOSAL_FOLLOWUP = "PROPOSAL_FOLLOWUP"
    MEETING_REMINDER = "MEETING_REMINDER"
    MEETING_RESCHEDULE = "MEETING_RESCHEDULE"
    LEAVE_REQUEST = "LEAVE_REQUEST"
    NEWSLETTER = "NEWSLETTER"
    GENERAL = "GENERAL"


class ToolName(str, Enum):
    create_task = "create_task"
    create_ticket = "create_ticket"
    send_notification = "send_notification"
    escalate_to_manager = "escalate_to_manager"
    send_email = "send_email"
    create_calendar_event = "create_calendar_event"
    reschedule_meeting = "reschedule_meeting"
    complete_task = "complete_task"
    archive_email = "archive_email"
    process_payment = "process_payment"
    sign_contract = "sign_contract"
    delete_records = "delete_records"
    approve_leave = "approve_leave"


class ActionClass(str, Enum):
    INTERNAL_TASK = "INTERNAL_TASK"
    INTERNAL_NOTIFICATION = "INTERNAL_NOTIFICATION"
    INTERNAL_COMMUNICATION = "INTERNAL_COMMUNICATION"
    ROUTINE_REMINDER = "ROUTINE_REMINDER"
    INTERNAL_SCHEDULING = "INTERNAL_SCHEDULING"
    ARCHIVE = "ARCHIVE"
    EXTERNAL_COMMUNICATION = "EXTERNAL_COMMUNICATION"
    EXTERNAL_COMMITMENT = "EXTERNAL_COMMITMENT"
    FINANCIAL = "FINANCIAL"
    CONTRACT = "CONTRACT"
    DELETION = "DELETION"
    PERSONNEL = "PERSONNEL"


# --------------------------------------------------------------------------- observation
class Amount(BaseModel):
    value: float
    raw: str
    currency: str = "INR"


class Observation(BaseModel):
    email_id: str
    sender_name: str
    sender_email: str
    sender_type: Literal["internal", "external"]
    subject: str
    category: str
    word_count: int
    amounts: list[Amount] = Field(default_factory=list)
    fields: dict[str, str] = Field(default_factory=dict)
    emails_found: list[str] = Field(default_factory=list)
    day_mentions: list[str] = Field(default_factory=list)
    datetimes: list[str] = Field(default_factory=list)
    signals: dict[str, list[str]] = Field(default_factory=dict)
    has_deadline: bool = False
    excerpt: str = ""


# --------------------------------------------------------------------------- LLM structured output
class LLMRiskFactors(BaseModel):
    model_config = ConfigDict(extra="ignore")
    financial_exposure: float = Field(ge=1, le=10)
    security_implications: float = Field(ge=1, le=10)
    irreversibility: float = Field(ge=1, le=10)
    external_communication: float = Field(ge=1, le=10)
    business_consequences: float = Field(ge=1, le=10)


class LLMContext(BaseModel):
    """The structured object every provider must return. Anything else is rejected."""

    model_config = ConfigDict(extra="ignore")
    intent: Intent
    summary: str = Field(min_length=1, max_length=400)
    urgency: float = Field(ge=1, le=10)
    business_impact: float = Field(ge=1, le=10)
    time_sensitivity: float = Field(ge=1, le=10)
    customer_importance: float = Field(ge=1, le=10)
    risk_factors: LLMRiskFactors
    recommended_action: ActionType
    proposed_decision: FinalDecision
    rationale: str = Field(min_length=1, max_length=500)
    draft_reply: Optional[str] = Field(default=None, max_length=1800)
    entities: dict[str, Any] = Field(default_factory=dict)


class BriefingNarrative(BaseModel):
    model_config = ConfigDict(extra="ignore")
    headline: str = Field(min_length=1, max_length=140)
    summary: str = Field(min_length=1, max_length=900)


class ContextResult(BaseModel):
    """LLM output after backend validation (clamping, deterministic floors, intent guard)."""

    intent: Intent
    summary: str
    scores: dict[str, float]
    llm_scores: dict[str, float]
    llm_risk_factors: dict[str, float]
    recommended_action: ActionType
    proposed_decision: FinalDecision
    rationale: str
    draft_reply: Optional[str] = None
    entities: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    fallback_reason: Optional[str] = None
    validation_notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- plan / policy / decision
class PlanStep(BaseModel):
    step_id: str
    tool: ToolName
    title: str
    params: dict[str, Any] = Field(default_factory=dict)
    action_class: ActionClass
    external: bool = False
    risk_score: float = 1.0
    requires_approval: bool = False
    gate_kind: Optional[Literal["mandatory", "learned", "mode", "dependent"]] = None
    gate_rules: list[str] = Field(default_factory=list)
    blocked_reason: Optional[str] = None
    status: Literal["planned", "executed", "awaiting_approval", "failed", "rejected", "skipped"] = "planned"
    result: Optional[dict[str, Any]] = None
    rationale: str = ""


class PriorityBreakdown(BaseModel):
    urgency: float
    business_impact: float
    time_sensitivity: float
    customer_importance: float
    weights: dict[str, float]
    contributions: dict[str, float]
    score: float
    label: str


class RiskBreakdown(BaseModel):
    factors: dict[str, float]
    deterministic: dict[str, float]
    llm: dict[str, float]
    weights: dict[str, float]
    score: float
    label: str
    step_risks: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class OptionEval(BaseModel):
    action: ActionType
    label: str
    fit: float
    p_success: float
    benefit: float
    loss: float
    effort: float
    preference_adjustment: float = 0.0
    llm_bonus: float = 0.0
    expected_utility: float
    risk_score: float
    needs_human: bool = False
    llm_suggested: bool = False
    steps_preview: list[str] = Field(default_factory=list)
    rank: int = 0


class PolicyCheck(BaseModel):
    rule_id: str
    name: str
    kind: Literal["mandatory", "allow", "force", "soft", "mode", "block"]
    description: str
    triggered: bool
    effect: str
    detail: str = ""
    step_ids: list[str] = Field(default_factory=list)


class RoutingNode(BaseModel):
    node_id: str
    question: str
    answer: bool
    evidence: str
    on_yes: str
    on_no: str


class LoopEntry(BaseModel):
    iteration: int
    observe: str
    reason: str
    tool: str
    gate: Literal["auto", "approval", "blocked"]
    result: str = ""
    decide_again: str = ""


class DecisionRecord(BaseModel):
    email_id: str
    mode: Mode
    provider: str
    created_at: str
    preview: bool = False
    observation: Observation
    context: ContextResult
    priority: PriorityBreakdown
    risk: RiskBreakdown
    options: list[OptionEval]
    chosen_action: ActionType
    chosen_by: str = "expected_utility"
    llm_proposed_action: ActionType
    llm_proposed_decision: FinalDecision
    policy_override: bool = False
    override_reasons: list[str] = Field(default_factory=list)
    policy_checks: list[PolicyCheck]
    plan: list[PlanStep]
    routing: list[RoutingNode]
    final_decision: FinalDecision
    requires_human: bool = False
    human_reasons: list[str] = Field(default_factory=list)
    explanation: str
    factors: list[str] = Field(default_factory=list)
    duration_ms: float = 0.0
    stage_timings_ms: dict[str, float] = Field(default_factory=dict)
    loop_trace: list[LoopEntry] = Field(default_factory=list)
    execution_status: str = "NOT_EXECUTED"


# --------------------------------------------------------------------------- API request bodies
class WeightsUpdate(BaseModel):
    urgency: float = Field(ge=0, le=1)
    business_impact: float = Field(ge=0, le=1)
    time_sensitivity: float = Field(ge=0, le=1)
    customer_importance: float = Field(ge=0, le=1)


class ModeUpdate(BaseModel):
    mode: Mode


class ProcessRequest(BaseModel):
    mode: Optional[Mode] = None
    pace_ms: Optional[int] = Field(default=None, ge=0, le=2000)


class StepEdit(BaseModel):
    step_id: str
    tool: ToolName
    params: dict[str, Any] = Field(default_factory=dict)


class ApprovalAction(BaseModel):
    feedback: Optional[str] = Field(default=None, max_length=500)


class ModifyRequest(BaseModel):
    steps: list[StepEdit]
    feedback: Optional[str] = Field(default=None, max_length=500)


class TaskUpdate(BaseModel):
    status: Literal["open", "completed"]

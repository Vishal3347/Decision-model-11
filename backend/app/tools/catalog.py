"""Tool catalog: parameter schemas, action classification and the internal/external test.

This module is pure (no database) so the planner, policy engine and executor all share one source
of truth. ``external`` is *derived* from the parameters (recipient domain, attendees) rather than
supplied by the caller, so an edited plan cannot hide an external action from policy.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..schemas import ActionClass, ToolName

INTERNAL_DOMAIN = "@helixai.example"
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")


def _iso(value: Optional[str]) -> Optional[str]:
    if value is None:
        return value
    datetime.fromisoformat(value)  # raises ValueError -> validation error
    return value


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateTaskParams(_P):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    due_at: Optional[str] = None
    priority: Literal["Critical", "High", "Medium", "Low"] = "Medium"
    task_type: Literal["task", "followup"] = "task"
    status: Literal["open", "completed"] = "open"

    _v = field_validator("due_at")(_iso)


class CreateTicketParams(_P):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    severity: Literal["P1", "P2", "P3"] = "P1"
    owner_team: str = Field(min_length=1, max_length=80)


class SendNotificationParams(_P):
    channel: str = Field(min_length=1, max_length=80)
    recipients: list[str] = Field(min_length=1, max_length=12)
    subject: str = Field(default="", max_length=200)
    message: str = Field(min_length=1, max_length=1000)


class EscalateParams(_P):
    manager: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=1000)


class SendEmailParams(_P):
    to: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=3000)

    @field_validator("to")
    @classmethod
    def _valid_address(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("must be a valid email address")
        return v.lower()


class CalendarEventParams(_P):
    title: str = Field(min_length=1, max_length=200)
    start_at: str
    end_at: str
    attendees: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal["reminder", "meeting"] = "meeting"

    _v = field_validator("start_at", "end_at")(_iso)


class RescheduleParams(_P):
    title: str = Field(min_length=1, max_length=200)
    from_start: Optional[str] = None
    to_start: str
    to_end: str
    attendees: list[str] = Field(default_factory=list, max_length=20)

    _v = field_validator("from_start", "to_start", "to_end")(_iso)


class CompleteTaskParams(_P):
    title: str = Field(min_length=1, max_length=200)


class ArchiveParams(_P):
    reason: str = Field(default="", max_length=200)


class PaymentParams(_P):
    vendor: str = Field(min_length=1, max_length=120)
    invoice: str = Field(default="n/a", max_length=60)
    amount: float = Field(gt=0)
    currency: Literal["INR"] = "INR"
    budget_code: Optional[str] = Field(default=None, max_length=40)


class ContractParams(_P):
    document: str = Field(min_length=1, max_length=200)
    counterparty: str = Field(min_length=1, max_length=120)
    value: Optional[float] = Field(default=None, ge=0)


class DeleteRecordsParams(_P):
    record_type: str = Field(min_length=1, max_length=80)
    scope: str = Field(min_length=1, max_length=300)
    record_count: int = Field(ge=0)
    retention_policy: str = Field(default="", max_length=40)


class ApproveLeaveParams(_P):
    employee: str = Field(min_length=1, max_length=120)
    start_date: str
    end_date: str
    days: int = Field(ge=1, le=60)

    _v = field_validator("start_date", "end_date")(_iso)


PARAM_MODELS: dict[ToolName, type[BaseModel]] = {
    ToolName.create_task: CreateTaskParams,
    ToolName.create_ticket: CreateTicketParams,
    ToolName.send_notification: SendNotificationParams,
    ToolName.escalate_to_manager: EscalateParams,
    ToolName.send_email: SendEmailParams,
    ToolName.create_calendar_event: CalendarEventParams,
    ToolName.reschedule_meeting: RescheduleParams,
    ToolName.complete_task: CompleteTaskParams,
    ToolName.archive_email: ArchiveParams,
    ToolName.process_payment: PaymentParams,
    ToolName.sign_contract: ContractParams,
    ToolName.delete_records: DeleteRecordsParams,
    ToolName.approve_leave: ApproveLeaveParams,
}

TOOL_LABELS: dict[ToolName, str] = {
    ToolName.create_task: "Create task",
    ToolName.create_ticket: "Create incident ticket",
    ToolName.send_notification: "Send internal notification",
    ToolName.escalate_to_manager: "Escalate to manager",
    ToolName.send_email: "Send email (simulated)",
    ToolName.create_calendar_event: "Create calendar event",
    ToolName.reschedule_meeting: "Reschedule meeting",
    ToolName.complete_task: "Mark task completed",
    ToolName.archive_email: "Archive email",
    ToolName.process_payment: "Process payment (simulated)",
    ToolName.sign_contract: "Sign contract (simulated)",
    ToolName.delete_records: "Delete records (simulated)",
    ToolName.approve_leave: "Approve leave (simulated HR)",
}


def validate_params(tool: ToolName, params: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalise parameters; raises ``pydantic.ValidationError`` when invalid."""
    return PARAM_MODELS[tool].model_validate(params).model_dump()


def _is_external_address(value: str) -> bool:
    return "@" in value and not value.lower().endswith(INTERNAL_DOMAIN)


def is_external(tool: ToolName, params: dict[str, Any]) -> bool:
    if tool == ToolName.send_email:
        return _is_external_address(str(params.get("to", "")))
    if tool in (ToolName.create_calendar_event, ToolName.reschedule_meeting):
        return any(_is_external_address(str(a)) for a in params.get("attendees", []))
    return False


def classify(tool: ToolName, params: dict[str, Any]) -> ActionClass:
    ext = is_external(tool, params)
    if tool in (ToolName.create_task, ToolName.create_ticket, ToolName.complete_task):
        return ActionClass.INTERNAL_TASK
    if tool in (ToolName.send_notification, ToolName.escalate_to_manager):
        return ActionClass.INTERNAL_NOTIFICATION
    if tool == ToolName.send_email:
        return ActionClass.EXTERNAL_COMMUNICATION if ext else ActionClass.INTERNAL_COMMUNICATION
    if tool == ToolName.create_calendar_event:
        if ext:
            return ActionClass.EXTERNAL_COMMITMENT
        return ActionClass.ROUTINE_REMINDER if params.get("kind") == "reminder" else ActionClass.INTERNAL_SCHEDULING
    if tool == ToolName.reschedule_meeting:
        return ActionClass.EXTERNAL_COMMITMENT if ext else ActionClass.INTERNAL_SCHEDULING
    if tool == ToolName.archive_email:
        return ActionClass.ARCHIVE
    if tool == ToolName.process_payment:
        return ActionClass.FINANCIAL
    if tool == ToolName.sign_contract:
        return ActionClass.CONTRACT
    if tool == ToolName.delete_records:
        return ActionClass.DELETION
    return ActionClass.PERSONNEL  # approve_leave

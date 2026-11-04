"""Deterministic policy validation. Policies run on the backend and always beat the LLM and the mode.

Rule kinds
  mandatory – step needs human approval; cannot be waived by mode, preference or LLM.
  allow     – step may run automatically (internal task / notification / routine reminder ...).
  block     – step is refused outright (even with approval).
  soft      – learned preference (repeated human rejections) adds an approval gate.
  mode      – HUMAN_CONTROLLED mode holds every step for confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..constants import PAYMENT_HARD_CAP, PROTECTED_RECORD_TYPES, RISK_GATE
from ..schemas import ActionClass as C
from ..schemas import Mode, PlanStep, PolicyCheck, ToolName as T

RULES: dict[str, dict] = {
    "POL-FIN-001": dict(name="Financial transactions require approval", kind="mandatory",
                        description="Any payment or transfer of funds always requires explicit human approval."),
    "POL-CON-002": dict(name="Contract signing requires approval", kind="mandatory",
                        description="The agent never signs a contract on its own; a human must approve."),
    "POL-DEL-003": dict(name="Deleting records requires approval", kind="mandatory",
                        description="Deleting records is irreversible and always requires human approval."),
    "POL-EXT-004": dict(name="External commitments require approval", kind="mandatory",
                        description="Anything sent to, or promised to, an external party (email, invitation, meeting) needs approval."),
    "POL-HR-005": dict(name="Personnel decisions require approval", kind="mandatory",
                       description="Leave approvals and other personnel decisions are made by a human."),
    "POL-RISK-006": dict(name="High-risk steps require approval", kind="mandatory",
                         description=f"Any step with a risk score of {RISK_GATE:g} or higher requires approval."),
    "POL-INT-101": dict(name="Internal tasks may run automatically", kind="allow",
                        description="Creating internal tasks and incident tickets is low-risk and reversible."),
    "POL-INT-102": dict(name="Internal notifications may run automatically", kind="allow",
                        description="Notifying internal teams or managers can be automatic."),
    "POL-INT-103": dict(name="Routine reminders may run automatically", kind="allow",
                        description="Calendar reminders and internal rescheduling with no external party can be automatic."),
    "POL-INT-104": dict(name="Archiving may run automatically", kind="allow",
                        description="Archiving is reversible and may run automatically."),
    "POL-BLK-201": dict(name="Payment hard limit", kind="block",
                        description=f"Payments above ₹{PAYMENT_HARD_CAP:,.0f} are refused, even with approval."),
    "POL-BLK-202": dict(name="Protected records cannot be deleted", kind="block",
                        description="Audit logs, financial records and legal contracts can never be deleted by the agent."),
    "POL-PREF-301": dict(name="Learned preference: ask first", kind="soft",
                         description="After repeated human rejections of an action for this type of email, the agent asks before acting."),
    "POL-SEQ-007": dict(name="Dependent steps wait for approval", kind="mandatory",
                        description="A step that follows an approval-gated step in the plan waits for that approval; nothing 'confirms' an action that has not happened."),
    "POL-MODE-401": dict(name="Human-controlled mode", kind="mode",
                         description="In human-controlled mode the agent only recommends; every step waits for confirmation."),
}

_MANDATORY_BY_CLASS = {
    C.FINANCIAL: "POL-FIN-001",
    C.CONTRACT: "POL-CON-002",
    C.DELETION: "POL-DEL-003",
    C.EXTERNAL_COMMUNICATION: "POL-EXT-004",
    C.EXTERNAL_COMMITMENT: "POL-EXT-004",
    C.PERSONNEL: "POL-HR-005",
}
_ALLOW_BY_CLASS = {
    C.INTERNAL_TASK: "POL-INT-101",
    C.INTERNAL_NOTIFICATION: "POL-INT-102",
    C.INTERNAL_COMMUNICATION: "POL-INT-102",
    C.ROUTINE_REMINDER: "POL-INT-103",
    C.INTERNAL_SCHEDULING: "POL-INT-103",
    C.ARCHIVE: "POL-INT-104",
}


@dataclass
class PolicyResult:
    checks: list[PolicyCheck] = field(default_factory=list)
    triggering: dict[str, list[str]] = field(default_factory=dict)  # rule -> step ids that triggered it

    @property
    def blocked(self) -> bool:
        return any(s for s in [c for c in self.checks if c.kind == "block" and c.triggered])


def block_reason(step: PlanStep) -> tuple[str, str] | None:
    """Return (rule_id, reason) if the step must be refused outright."""
    p = step.params
    if step.tool == T.process_payment and float(p.get("amount", 0)) > PAYMENT_HARD_CAP:
        return "POL-BLK-201", f"Payment of ₹{float(p['amount']):,.0f} exceeds the hard limit of ₹{PAYMENT_HARD_CAP:,.0f}."
    if step.tool == T.delete_records and str(p.get("record_type", "")).lower() in PROTECTED_RECORD_TYPES:
        return "POL-BLK-202", f"'{p['record_type']}' is a protected record type and cannot be deleted by the agent."
    return None


def evaluate_policies(steps: list[PlanStep], mode: Mode, soft_gates: set[str] | None = None) -> PolicyResult:
    """Annotate each step (requires_approval / gate_kind / gate_rules / blocked_reason) and report every rule checked.

    ``soft_gates`` holds tool names that learned preferences say to ask about first.
    """
    soft_gates = soft_gates or set()
    triggered: dict[str, list[str]] = {rid: [] for rid in RULES}
    detail: dict[str, list[str]] = {rid: [] for rid in RULES}

    for s in steps:
        s.requires_approval, s.gate_kind, s.gate_rules, s.blocked_reason = False, None, [], None

        blk = block_reason(s)
        if blk:
            s.blocked_reason = blk[1]
            s.gate_rules.append(blk[0])
            triggered[blk[0]].append(s.step_id)
            detail[blk[0]].append(blk[1])

        mand = _MANDATORY_BY_CLASS.get(s.action_class)
        if mand:
            s.requires_approval, s.gate_kind = True, "mandatory"
            s.gate_rules.append(mand)
            triggered[mand].append(s.step_id)
            detail[mand].append(f"{s.title}")
        if s.risk_score >= RISK_GATE:
            s.requires_approval, s.gate_kind = True, "mandatory"
            if "POL-RISK-006" not in s.gate_rules:
                s.gate_rules.append("POL-RISK-006")
            triggered["POL-RISK-006"].append(s.step_id)
            detail["POL-RISK-006"].append(f"{s.title} (risk {s.risk_score:g})")

        if not s.requires_approval:
            allow = _ALLOW_BY_CLASS.get(s.action_class)
            if allow:
                triggered[allow].append(s.step_id)
                detail[allow].append(s.title)
                s.gate_rules.append(allow)

        if not s.requires_approval and s.tool.value in soft_gates:
            s.requires_approval, s.gate_kind = True, "learned"
            s.gate_rules.append("POL-PREF-301")
            triggered["POL-PREF-301"].append(s.step_id)
            detail["POL-PREF-301"].append(f"{s.title}: previously rejected by a human")

        if not s.requires_approval and mode == Mode.HUMAN_CONTROLLED:
            s.requires_approval, s.gate_kind = True, "mode"
            s.gate_rules.append("POL-MODE-401")
            triggered["POL-MODE-401"].append(s.step_id)
            detail["POL-MODE-401"].append(s.title)

    gated_seen = False
    for s in steps:
        if gated_seen and not s.requires_approval and not s.blocked_reason:
            s.requires_approval, s.gate_kind = True, "dependent"
            s.gate_rules.append("POL-SEQ-007")
            triggered["POL-SEQ-007"].append(s.step_id)
            detail["POL-SEQ-007"].append(s.title)
        if s.requires_approval and s.gate_kind in ("mandatory", "learned"):
            gated_seen = True

    result = PolicyResult()
    for rid, meta in RULES.items():
        ids = sorted(set(triggered[rid]))
        fired = bool(ids)
        if meta["kind"] == "mandatory":
            effect = "Approval required — cannot be bypassed" if fired else "Not triggered"
        elif meta["kind"] == "allow":
            effect = "Automatic execution permitted" if fired else "Not applicable"
        elif meta["kind"] == "block":
            effect = "Step refused" if fired else "Not triggered"
        elif meta["kind"] == "soft":
            effect = "Approval added from learned feedback" if fired else "Not triggered"
        else:
            effect = "Step held for confirmation" if fired else "Not active"
        result.checks.append(PolicyCheck(
            rule_id=rid, name=meta["name"], kind=meta["kind"], description=meta["description"],
            triggered=fired, effect=effect, detail="; ".join(dict.fromkeys(detail[rid]))[:300], step_ids=ids,
        ))
    return result


def revalidate_for_execution(step: PlanStep) -> str | None:
    """Final guard run immediately before any tool executes. Returns a refusal reason or None."""
    blk = block_reason(step)
    return blk[1] if blk else None

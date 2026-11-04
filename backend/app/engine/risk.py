"""Risk assessment (separate from priority).

Risk measures how dangerous it is for the *agent to act autonomously* on the planned steps, across five
factors. Each tool has a deterministic risk profile; the LLM's own estimate is accepted only as a
validated input: it may raise a factor but can never lower the deterministic floor.
"""
from __future__ import annotations

from ..constants import RISK_AVG_SHARE, RISK_FACTOR_WEIGHTS, RISK_THRESHOLDS
from ..schemas import PlanStep, RiskBreakdown, ToolName
from ..tools.catalog import is_external

FACTORS = list(RISK_FACTOR_WEIGHTS)

# (financial, security, irreversibility, external_communication, business_consequences)
_PROFILE: dict[ToolName, tuple[int, int, int, int, int]] = {
    ToolName.create_task: (1, 1, 1, 1, 1),
    ToolName.create_ticket: (1, 1, 1, 1, 2),
    ToolName.send_notification: (1, 1, 2, 1, 2),
    ToolName.escalate_to_manager: (1, 1, 2, 1, 2),
    ToolName.complete_task: (1, 1, 1, 1, 1),
    ToolName.archive_email: (1, 1, 2, 1, 1),
    ToolName.reschedule_meeting: (1, 1, 3, 2, 3),
    ToolName.approve_leave: (2, 1, 5, 2, 3),
    ToolName.delete_records: (2, 3, 10, 2, 8),
}


def _amount_bracket(amount: float) -> int:
    for limit, score in ((10_000, 2), (50_000, 3), (100_000, 4), (500_000, 7), (1_000_000, 8)):
        if amount <= limit:
            return score
    return 10


def step_factors(step: PlanStep) -> dict[str, float]:
    tool, p = step.tool, step.params
    ext = is_external(tool, p)
    if tool == ToolName.send_email:
        prof = (2, 2, 7, 8, 5) if ext else (1, 1, 5, 1, 2)
    elif tool == ToolName.create_calendar_event:
        prof = (1, 1, 4, 7, 4) if ext else ((1, 1, 1, 1, 1) if p.get("kind") == "reminder" else (1, 1, 2, 1, 1))
    elif tool == ToolName.reschedule_meeting:
        prof = (1, 1, 5, 7, 5) if ext else _PROFILE[tool]
    elif tool == ToolName.process_payment:
        prof = (_amount_bracket(float(p.get("amount", 0))), 3, 8, 6, 6)
    elif tool == ToolName.sign_contract:
        prof = (min(_amount_bracket(float(p.get("value") or 0)), 8), 2, 9, 8, 9)
    else:
        prof = _PROFILE[tool]
    return {f: float(v) for f, v in zip(FACTORS, prof)}


def combine(factors: dict[str, float]) -> float:
    avg = sum(RISK_FACTOR_WEIGHTS[f] * factors[f] for f in FACTORS)
    worst = max(factors[f] for f in FACTORS)
    return round(max(1.0, min(10.0, RISK_AVG_SHARE * avg + (1 - RISK_AVG_SHARE) * worst)), 1)


def risk_label(score: float) -> str:
    for label, threshold in RISK_THRESHOLDS:
        if score >= threshold:
            return label
    return "Low"


def plan_risk(steps: list[PlanStep], llm_factors: dict[str, float] | None = None) -> RiskBreakdown:
    """Score every step, then the plan (per-factor worst case), optionally blended with LLM estimates."""
    det = {f: 1.0 for f in FACTORS}
    step_risks: dict[str, float] = {}
    for s in steps:
        sf = step_factors(s)
        s.risk_score = combine(sf)
        step_risks[s.step_id] = s.risk_score
        for f in FACTORS:
            det[f] = max(det[f], sf[f])

    notes: list[str] = []
    final = dict(det)
    llm_clean: dict[str, float] = {}
    if llm_factors:
        for f in FACTORS:
            raw = llm_factors.get(f)
            if raw is None:
                continue
            v = max(1.0, min(10.0, float(raw)))
            llm_clean[f] = v
            if v < det[f]:
                notes.append(f"LLM rated {f.replace('_', ' ')} {v:g}, below the deterministic floor {det[f]:g}; floor applied.")
            final[f] = max(det[f], v)
    score = combine(final)
    return RiskBreakdown(
        factors=final,
        deterministic=det,
        llm=llm_clean,
        weights=dict(RISK_FACTOR_WEIGHTS),
        score=score,
        label=risk_label(score),
        step_risks=step_risks,
        notes=notes,
    )

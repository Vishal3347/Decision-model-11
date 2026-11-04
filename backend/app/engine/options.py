"""Option generation and decision evaluation.

For every candidate action we build its concrete plan, score its risk, and compute

    EU(a) = P(success) × Benefit  −  (1 − P(success)) × Loss  −  Effort  [+ learned preference] [+ LLM suggestion bonus]

    Benefit = fit(intent, a) × priority_score × 10
    Loss    = plan_risk(a) × exposure(a) × 10
    P       = base_reliability(a) × (1 − 0.03 × plan_risk(a)/10 × ...)   (see ``p_success``)

These are transparent, educational heuristics, not learned probabilities.
"""
from __future__ import annotations

from datetime import datetime

from ..constants import (BASE_RELIABILITY, EFFORT_COST, EXPOSURE, LLM_SUGGESTION_BONUS, RISK_GATE)
from ..schemas import ActionType as A
from ..schemas import ContextResult, Intent, Observation, OptionEval, PlanStep, PriorityBreakdown
from .heuristics import fit_for
from .plans import build_plan
from .preferences import adjustment
from .risk import plan_risk

LABELS = {
    A.IGNORE: "Ignore", A.ARCHIVE: "Archive", A.CREATE_TASK: "Create task", A.DRAFT_RESPONSE: "Draft response",
    A.NOTIFY_INTERNAL: "Send internal notification", A.SCHEDULE_MEETING: "Schedule meeting",
    A.ESCALATE: "Escalate", A.REQUEST_APPROVAL: "Request human approval",
}


def p_success(action: A, risk: float) -> float:
    return round(max(0.3, BASE_RELIABILITY[action] - 0.012 * risk), 3)


def generate_options(
    obs: Observation, ctx: ContextResult, priority: PriorityBreakdown, now: datetime, prefs: dict,
) -> tuple[list[OptionEval], dict[A, list[PlanStep]]]:
    plans: dict[A, list[PlanStep]] = {}
    options: list[OptionEval] = []
    intent = ctx.intent
    for action in A:
        steps = build_plan(action, intent, obs, ctx, now, priority.label)
        plans[action] = steps
        risk = plan_risk([s.model_copy(deep=True) for s in steps]).score if steps else 1.0
        fit = fit_for(intent, action)
        # IGNORE / ARCHIVE on something important is a *missed* opportunity -> loss is the priority itself.
        benefit = fit * priority.score * 10
        if action in (A.IGNORE, A.ARCHIVE):
            loss = (1 - fit) * priority.score * 10 * 0.5
        else:
            loss = risk * EXPOSURE[action] * 10 if action in EXPOSURE else 0.0
        p = p_success(action, risk if steps else 1.0)
        effort = EFFORT_COST[action]
        pref = adjustment(prefs, intent.value, action)
        bonus = LLM_SUGGESTION_BONUS if action == ctx.recommended_action else 0.0
        eu = p * benefit - (1 - p) * loss - effort + pref + bonus
        needs_human = any(s.action_class.value in {"FINANCIAL", "CONTRACT", "DELETION", "EXTERNAL_COMMUNICATION", "EXTERNAL_COMMITMENT", "PERSONNEL"} for s in steps) or risk >= RISK_GATE
        options.append(OptionEval(
            action=action, label=LABELS[action], fit=round(fit, 2), p_success=p, benefit=round(benefit, 1), loss=round(loss, 1),
            effort=effort, preference_adjustment=round(pref, 1), llm_bonus=bonus, expected_utility=round(eu, 1),
            risk_score=risk, needs_human=needs_human, llm_suggested=action == ctx.recommended_action,
            steps_preview=[s.title for s in steps],
        ))
    options.sort(key=lambda o: o.expected_utility, reverse=True)
    for i, o in enumerate(options, 1):
        o.rank = i
    return options, plans


def satisfice(options: list[OptionEval], priority_score: float) -> dict:
    """Bounded rationality: walk actions cheapest-first and stop at the first that is 'good enough'."""
    from ..constants import SATISFICE_ASPIRATION_SHARE, SATISFICE_MAX_RISK, SATISFICE_MIN_FIT, SATISFICE_ORDER
    by_action = {o.action: o for o in options}
    best_eu = max(o.expected_utility for o in options)
    aspiration = round(SATISFICE_ASPIRATION_SHARE * priority_score * 10, 1)
    trace = []
    chosen = None
    for a in SATISFICE_ORDER:
        o = by_action[a]
        reasons = []
        if o.fit < SATISFICE_MIN_FIT:
            reasons.append(f"fit {o.fit:.2f} < {SATISFICE_MIN_FIT}")
        if o.risk_score > SATISFICE_MAX_RISK:
            reasons.append(f"risk {o.risk_score:g} > {SATISFICE_MAX_RISK:g}")
        if o.expected_utility < aspiration:
            reasons.append(f"EU {o.expected_utility:g} < aspiration {aspiration:g}")
        ok = not reasons
        trace.append(dict(action=a.value, label=o.label, fit=o.fit, risk=o.risk_score, eu=o.expected_utility,
                          accepted=ok and chosen is None, evaluated=chosen is None, reasons=reasons))
        if ok and chosen is None:
            chosen = a
    return dict(order=[a.value for a in SATISFICE_ORDER], criteria=dict(min_fit=SATISFICE_MIN_FIT, max_risk=SATISFICE_MAX_RISK, aspiration_eu=aspiration),
                trace=trace, chosen=chosen.value if chosen else None, optimal=options[0].action.value,
                options_examined=sum(1 for t in trace if t["evaluated"]), options_total=len(trace),
                matches_optimal=bool(chosen and chosen == options[0].action), best_eu=best_eu)

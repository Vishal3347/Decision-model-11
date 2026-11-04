"""The decision pipeline: Observation → Context → Options → Evaluation → Policy → Final decision.

``analyze_email`` is pure with respect to the world: it never executes tools, so it can also be
used for previews (e.g. comparing the two operating modes on the same email).
"""
from __future__ import annotations

import time
from datetime import datetime

from ..constants import RISK_GATE
from ..schemas import (ActionType as A, ContextResult, DecisionRecord, FinalDecision as F, Intent as I, LoopEntry, Mode,
                       RoutingNode)
from .heuristics import CRITICAL_INTENTS, classify_intent, deterministic_floors
from .observation import observe
from .options import generate_options
from .policy import evaluate_policies
from .preferences import soft_gate_tools
from .risk import plan_risk
from .scoring import compute_priority

SENSITIVE_INTENTS = CRITICAL_INTENTS | {I.PAYMENT_APPROVAL, I.CONTRACT_SIGNATURE, I.DATA_DELETION}


def validate_context(llm, obs, provider: str, model: str, fallback_reason: str | None) -> ContextResult:
    """Never trust the model blindly: guard the intent, apply deterministic score floors, clamp ranges."""
    notes: list[str] = []
    det_intent = classify_intent(obs)
    intent = llm.intent
    if intent != det_intent and det_intent in SENSITIVE_INTENTS:
        notes.append(f"Intent {intent.value} replaced by deterministic classification {det_intent.value} (sensitive pattern detected).")
        intent = det_intent
    floors = deterministic_floors(obs, intent)
    raw = {"urgency": llm.urgency, "business_impact": llm.business_impact, "time_sensitivity": llm.time_sensitivity,
           "customer_importance": llm.customer_importance}
    scores = dict(raw)
    for k, floor in floors.items():
        if scores[k] < floor:
            notes.append(f"{k.replace('_', ' ')} raised from {scores[k]:g} to deterministic floor {floor:g}.")
            scores[k] = floor
    scores = {k: max(1.0, min(10.0, float(v))) for k, v in scores.items()}
    return ContextResult(
        intent=intent, summary=llm.summary, scores=scores, llm_scores=raw, llm_risk_factors=llm.risk_factors.model_dump(),
        recommended_action=llm.recommended_action, proposed_decision=llm.proposed_decision, rationale=llm.rationale,
        draft_reply=llm.draft_reply, entities=llm.entities, provider=provider, model=model,
        fallback_reason=fallback_reason, validation_notes=notes,
    )


def _routing(plan, risk, policy, mode: Mode, soft: set[str]) -> list[RoutingNode]:
    blocked = [s for s in plan if s.blocked_reason]
    mand = [s for s in plan if s.gate_kind == "mandatory"]
    high = [s for s in plan if s.risk_score >= RISK_GATE]
    learned = [s for s in plan if s.gate_kind == "learned"]
    return [
        RoutingNode(node_id="n1", question="Is any step refused by a hard block rule?", answer=bool(blocked),
                    evidence=blocked[0].blocked_reason if blocked else "No step violates a block rule.", on_yes="Refuse step and escalate to a human", on_no="Continue"),
        RoutingNode(node_id="n2", question="Does a step involve money, contracts, deletion, personnel or an external party?", answer=bool(mand and not high or any(s.gate_rules and s.gate_rules[0] != "POL-RISK-006" for s in mand)),
                    evidence=", ".join(sorted({r for s in mand for r in s.gate_rules if r.startswith("POL-") and r not in ("POL-RISK-006",)})) or "All steps are internal and routine.",
                    on_yes="Mandatory approval gate", on_no="Continue"),
        RoutingNode(node_id="n3", question=f"Is any step's risk ≥ {RISK_GATE:g}?", answer=bool(high), evidence=f"Highest step risk: {max([s.risk_score for s in plan], default=0):g}",
                    on_yes="Mandatory approval gate", on_no="Continue"),
        RoutingNode(node_id="n4", question="Have humans repeatedly rejected this action for this type of email?", answer=bool(learned), evidence="Learned preference counters" if learned else "No learned objection.",
                    on_yes="Ask first (soft gate)", on_no="Continue"),
        RoutingNode(node_id="n5", question="Is the agent in human-controlled mode?", answer=mode == Mode.HUMAN_CONTROLLED, evidence=f"Mode: {mode.value}",
                    on_yes="Hold remaining steps for confirmation", on_no="Execute permitted steps automatically"),
    ]


def decide_final(chosen: A, plan, mode: Mode) -> F:
    if not plan:
        return F.IGNORE
    if chosen == A.ARCHIVE:
        return F.IGNORE
    if any(s.blocked_reason for s in plan):
        return F.ESCALATE
    if chosen == A.ESCALATE:
        return F.ESCALATE
    policy_gate = any(s.requires_approval and s.gate_kind in ("mandatory", "learned", "dependent") for s in plan)
    if policy_gate:
        return F.DRAFT_AND_APPROVE
    base = F.SCHEDULE if chosen == A.SCHEDULE_MEETING else F.AUTO_EXECUTE
    return F.DRAFT_AND_APPROVE if mode == Mode.HUMAN_CONTROLLED else base


def analyze_email(email: dict, *, provider, mode: Mode, weights: dict, prefs: dict, now: datetime, preview: bool = False) -> DecisionRecord:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, start: float) -> float:
        timings[name] = round((time.perf_counter() - start) * 1000, 2)
        return time.perf_counter()

    s = time.perf_counter()
    obs = observe(email, now)
    s = lap("observation", s)
    llm, pname, model, fallback = provider.analyze(obs, email)
    ctx = validate_context(llm, obs, pname, model, fallback)
    s = lap("context", s)
    priority = compute_priority(ctx.scores, weights)
    options, plans = generate_options(obs, ctx, priority, now, prefs)
    s = lap("options", s)

    chosen = options[0].action
    plan = plans[chosen]
    risk = plan_risk(plan, ctx.llm_risk_factors)
    s = lap("evaluation", s)

    soft = soft_gate_tools(prefs, ctx.intent.value, chosen, [st.tool.value for st in plan])
    policy = evaluate_policies(plan, mode, soft)
    final = decide_final(chosen, plan, mode)
    s = lap("policy", s)

    triggered_mand = [c for c in policy.checks if c.triggered and c.kind in ("mandatory", "block")]
    override_reasons: list[str] = []
    if ctx.proposed_decision != final:
        override_reasons.append(f"LLM proposed {ctx.proposed_decision.value}; final decision is {final.value}.")
    if ctx.recommended_action != chosen:
        override_reasons.append(f"LLM recommended {ctx.recommended_action.value}; expected-utility ranking selected {chosen.value}.")
    for c in triggered_mand:
        override_reasons.append(f"{c.rule_id}: {c.name}")
    policy_override = bool(triggered_mand) and (ctx.proposed_decision != final or any(st.requires_approval for st in plan))

    human_reasons = []
    for st in plan:
        if st.blocked_reason:
            human_reasons.append(f"{st.title}: {st.blocked_reason}")
        elif st.requires_approval:
            why = {"mandatory": "policy " + ", ".join(r for r in st.gate_rules if r not in ("POL-INT-101", "POL-INT-102", "POL-INT-103", "POL-INT-104")),
                   "learned": "learned preference (previously rejected)", "mode": "human-controlled mode", "dependent": "waits for an earlier approval"}[st.gate_kind or "mode"]
            human_reasons.append(f"{st.title}: {why}")
    requires_human = bool(human_reasons) or final == F.ESCALATE

    factors = [f"Priority {priority.score:.1f} ({priority.label}) from urgency {priority.urgency:g}, impact {priority.business_impact:g}, "
               f"time {priority.time_sensitivity:g}, customer {priority.customer_importance:g}.",
               f"Risk {risk.score:.1f} ({risk.label}).", f"Intent: {ctx.intent.value.replace('_', ' ').title()}."]
    if triggered_mand:
        factors.append("Policies applied: " + ", ".join(c.rule_id for c in triggered_mand) + ".")
    gated = [st for st in plan if st.requires_approval]
    auto = [st for st in plan if not st.requires_approval and not st.blocked_reason]
    explanation = f"{ctx.summary} Selected {chosen.value.replace('_', ' ').lower()} (highest expected utility). "
    if auto and gated:
        explanation += f"{len(auto)} step(s) can run automatically; {len(gated)} need human approval."
    elif gated:
        explanation += f"All {len(gated)} step(s) need human approval before anything runs."
    elif auto:
        explanation += f"All {len(auto)} step(s) are permitted to run automatically."
    else:
        explanation += "No action is required."

    loop = []
    for i, st in enumerate(plan[:8], 1):
        loop.append(LoopEntry(iteration=i, observe=ctx.summary if i == 1 else f"Result of step {i - 1} received", reason=st.rationale or st.title,
                              tool=st.tool.value, gate="blocked" if st.blocked_reason else "approval" if st.requires_approval else "auto",
                              decide_again="Continue with next step" if i < len(plan) else "Plan complete"))
    total = round((time.perf_counter() - t0) * 1000, 2)
    return DecisionRecord(
        email_id=email["id"], mode=mode, provider=pname, created_at=now.isoformat(timespec="seconds"), preview=preview, observation=obs, context=ctx,
        priority=priority, risk=risk, options=options, chosen_action=chosen, llm_proposed_action=ctx.recommended_action,
        llm_proposed_decision=ctx.proposed_decision, policy_override=policy_override, override_reasons=override_reasons,
        policy_checks=policy.checks, plan=plan, routing=_routing(plan, risk, policy, mode, soft), final_decision=final,
        requires_human=requires_human, human_reasons=human_reasons, explanation=explanation, factors=factors,
        duration_ms=total, stage_timings_ms=timings, loop_trace=loop,
    )

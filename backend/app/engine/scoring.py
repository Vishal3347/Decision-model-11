"""Weighted priority scoring: Priority = Σ weight × score (all on a 1-10 scale)."""
from __future__ import annotations

from ..constants import DEFAULT_WEIGHTS, PRIORITY_THRESHOLDS
from ..schemas import PriorityBreakdown

DIMENSIONS = ["urgency", "business_impact", "time_sensitivity", "customer_importance"]


def validate_weights(weights: dict[str, float]) -> dict[str, float]:
    missing = [d for d in DIMENSIONS if d not in weights]
    if missing:
        raise ValueError(f"missing weights: {', '.join(missing)}")
    cleaned = {d: float(weights[d]) for d in DIMENSIONS}
    if any(v < 0 or v > 1 for v in cleaned.values()):
        raise ValueError("each weight must be between 0 and 1")
    if abs(sum(cleaned.values()) - 1.0) > 0.011:
        raise ValueError(f"weights must sum to 1.0 (currently {sum(cleaned.values()):.2f})")
    return cleaned


def priority_label(score: float) -> str:
    for label, threshold in PRIORITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "Low"


def compute_priority(scores: dict[str, float], weights: dict[str, float] | None = None) -> PriorityBreakdown:
    w = validate_weights(weights or DEFAULT_WEIGHTS)
    contributions = {d: round(scores[d] * w[d], 3) for d in DIMENSIONS}
    total = round(sum(contributions.values()), 2)
    return PriorityBreakdown(
        urgency=scores["urgency"],
        business_impact=scores["business_impact"],
        time_sensitivity=scores["time_sensitivity"],
        customer_importance=scores["customer_importance"],
        weights=w,
        contributions=contributions,
        score=total,
        label=priority_label(total),
    )

"""Deterministic mock reasoning – used when no API key is configured or a live provider fails.

The mock is intentionally a little *optimistic* on sensitive intents (it proposes AUTO_EXECUTE for
payments, contracts, deletions and external scheduling) so the demo can show deterministic policies
overriding an over-eager model.
"""
from __future__ import annotations

from typing import Any

from ..engine.heuristics import baseline_context
from ..schemas import Observation
from .base import LLMProvider


class MockProvider(LLMProvider):
    name = "mock"
    model = "deterministic-mock"
    live = False

    def complete_json(self, system: str, user: str) -> str:  # pragma: no cover - never used
        raise NotImplementedError("MockProvider does not call a model")

    def analyze_email(self, obs: Observation, email: dict) -> dict[str, Any]:
        return baseline_context(obs)

    def write_briefing(self, facts: dict[str, Any]) -> dict[str, Any]:
        c = facts["counts"]
        parts = []
        if c["critical"]:
            top = facts.get("top_critical", [])[:2]
            parts.append(f"{c['critical']} critical issue(s) need attention" + (f", led by “{top[0]}”" if top else "") + ".")
        else:
            parts.append("No critical issues are open.")
        parts.append(f"{c['pending_approvals']} approval(s) are waiting for you and {c['completed_actions']} action(s) were completed by the agent.")
        if c["new_emails"]:
            parts.append(f"{c['new_emails']} email(s) have not been processed yet.")
        parts.append(f"{c['open_tasks']} open task(s) and {c['upcoming_meetings']} upcoming meeting(s) are on the calendar.")
        headline = (
            f"{c['critical']} critical, {c['pending_approvals']} awaiting your approval"
            if c["critical"] or c["pending_approvals"]
            else "All clear: nothing urgent right now"
        )
        return {"headline": headline, "summary": " ".join(parts)}

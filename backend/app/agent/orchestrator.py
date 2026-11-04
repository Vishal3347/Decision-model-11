"""Agent orchestrator: runs the pipeline, logs user-facing activity, executes permitted steps,
manages approvals (approve / reject / modify) and records feedback."""
from __future__ import annotations

import sqlite3
import threading
import time
import uuid
from typing import Any

from .. import clock
from ..constants import DEFAULT_WEIGHTS
from ..db import Database, dumps, ex, get_setting, loads, q, q1, set_setting, transaction
from ..engine import preferences as prefs_mod
from ..engine.pipeline import analyze_email
from ..engine.policy import evaluate_policies
from ..engine.risk import plan_risk
from ..engine.plans import ESCALATION
from ..engine.scoring import validate_weights
from ..schemas import DecisionRecord, FinalDecision as F, Mode, PlanStep, StepEdit, ToolName
from ..tools.catalog import TOOL_LABELS, classify, is_external, validate_params
from ..tools.executor import run_tool

STAGE_NAMES = ["Observe", "Understand", "Generate options", "Evaluate", "Validate policy", "Decide", "Execute"]


class Orchestrator:
    def __init__(self, db: Database, provider, settings):
        self.db, self.provider, self.settings = db, provider, settings
        self._run_lock = threading.Lock()

    # ------------------------------------------------------------------ settings helpers
    def mode(self, conn) -> Mode:
        return Mode(get_setting(conn, "mode", Mode.AUTONOMOUS.value))

    def weights(self, conn) -> dict:
        return get_setting(conn, "weights", DEFAULT_WEIGHTS)

    # ------------------------------------------------------------------ activity log
    def log(self, conn, stage: str, message: str, *, run_id=None, email_id=None, decision_id=None, level="info") -> None:
        ex(conn, "INSERT INTO activity(ts, run_id, email_id, decision_id, stage, level, message) VALUES(?,?,?,?,?,?,?)",
           (clock.iso(clock.now()), run_id, email_id, decision_id, stage, level, message))

    def _set_stage(self, conn, run_id, email_id, stage) -> None:
        if run_id:
            conn.execute("UPDATE runs SET current_email_id=?, current_stage=? WHERE id=?", (email_id, stage, run_id))

    # ------------------------------------------------------------------ preview (no side effects)
    def preview(self, email_id: str, mode: Mode | None = None) -> DecisionRecord:
        with self.db.connect() as conn:
            email = q1(conn, "SELECT * FROM emails WHERE id=?", (email_id,))
            if not email:
                raise KeyError(email_id)
            return analyze_email(email, provider=self.provider, mode=mode or self.mode(conn), weights=self.weights(conn),
                                 prefs=prefs_mod.load_preferences(conn), now=clock.now(), preview=True)

    # ------------------------------------------------------------------ process one email
    def process_email(self, email_id: str, *, mode: Mode | None = None, run_id: str | None = None, pace_ms: int | None = None) -> dict[str, Any]:
        pace = (self.settings.stage_delay_ms if pace_ms is None else pace_ms) / 1000.0
        with self.db.connect() as conn:
            email = q1(conn, "SELECT * FROM emails WHERE id=?", (email_id,))
            if not email:
                raise KeyError(email_id)
            mode = mode or self.mode(conn)
            weights, prefs = self.weights(conn), prefs_mod.load_preferences(conn)
            conn.execute("UPDATE emails SET status='processing' WHERE id=?", (email_id,))

            def step(stage: str, msg: str, level: str = "info") -> None:
                self._set_stage(conn, run_id, email_id, stage)
                self.log(conn, stage, msg, run_id=run_id, email_id=email_id, level=level)
                if pace:
                    time.sleep(pace)

            short = email["subject"][:70]
            step("Observe", f"New email detected: “{short}” from {email['sender_name']}.")
            rec = analyze_email(email, provider=self.provider, mode=mode, weights=weights, prefs=prefs, now=clock.now())
            obs, ctx = rec.observation, rec.context
            extra = f" Amount {obs.amounts[0].raw} detected." if obs.amounts else ""
            step("Observe", f"Email context extracted ({obs.word_count} words, {len(obs.signals)} signal group(s)).{extra}")
            if ctx.fallback_reason:
                step("Understand", ctx.fallback_reason, "warn")
            step("Understand", f"Intent identified: {ctx.intent.value.replace('_', ' ').title()}. {ctx.summary}")
            for n in ctx.validation_notes:
                step("Understand", f"Validation: {n}", "warn")
            step("Understand", f"{rec.priority.label} priority identified (score {rec.priority.score:.1f}/10).")
            step("Generate options", f"{len(rec.options)} candidate actions generated.")
            top = rec.options[0]
            step("Evaluate", f"Expected utility ranked “{top.label}” first ({top.expected_utility:g}).")
            step("Evaluate", f"Risk assessment completed: {rec.risk.label} ({rec.risk.score:.1f}/10).")
            triggered = [c for c in rec.policy_checks if c.triggered and c.kind in ("mandatory", "block", "soft")]
            if triggered:
                step("Validate policy", "Policy validation: " + "; ".join(f"{c.rule_id} {c.name}" for c in triggered[:3]) + ".", "warn")
            else:
                step("Validate policy", "Policy validation passed: all steps are internal and permitted.")
            if rec.policy_override:
                step("Validate policy", "Policy rules overrode the model's proposal.", "warn")
            step("Decide", f"Decision selected: {rec.final_decision.value}.")

            # persist the decision before executing so executions can reference it
            decision_id = ex(conn, "INSERT INTO decisions(email_id, run_id, mode, created_at, provider, final_decision, execution_status, priority_score, "
                                   "priority_label, risk_score, risk_label, intent, chosen_action, requires_human, duration_ms, summary, record_json) "
                                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (email_id, run_id, mode.value, clock.iso(clock.now()), rec.provider, rec.final_decision.value, "PENDING", rec.priority.score,
                              rec.priority.label, rec.risk.score, rec.risk.label, ctx.intent.value, rec.chosen_action.value, int(rec.requires_human), 0.0,
                              rec.explanation, "{}"))
            self._set_stage(conn, run_id, email_id, "Execute")

            awaiting: list[PlanStep] = []
            executed = failed = 0
            for i, st in enumerate(rec.plan):
                if st.blocked_reason:
                    st.status = "failed"
                    st.result = {"message": st.blocked_reason}
                    failed += 1
                    self.log(conn, "Execute", f"Refused by policy: {st.title}. {st.blocked_reason}", run_id=run_id, email_id=email_id, decision_id=decision_id, level="error")
                    self._loop_result(rec, i, "refused by policy")
                    continue
                if st.requires_approval:
                    st.status = "awaiting_approval"
                    awaiting.append(st)
                    self.log(conn, "Execute", f"Held for approval: {st.title}.", run_id=run_id, email_id=email_id, decision_id=decision_id, level="warn")
                    self._loop_result(rec, i, "waiting for human approval")
                    continue
                self._exec_step(conn, st, rec, email_id, decision_id, run_id, actor="agent", approval_id=None)
                if st.status == "executed":
                    executed += 1
                else:
                    failed += 1
                self._loop_result(rec, i, (st.result or {}).get("message", ""))
                if pace:
                    time.sleep(pace / 2)

            approval_id = None
            if awaiting:
                approval_id = self._create_approval(conn, decision_id, email_id, rec, awaiting)
                self.log(conn, "Execute", f"Approval request #{approval_id} prepared for {Mode(rec.mode).value.lower().replace('_', ' ')} review.", run_id=run_id, email_id=email_id, decision_id=decision_id)

            if awaiting:
                exec_status, email_status = "AWAITING_APPROVAL", "awaiting_approval"
            elif failed and not executed:
                exec_status, email_status = "FAILED", "failed"
            elif not rec.plan:
                exec_status, email_status = "NO_ACTION", "processed"
            else:
                exec_status, email_status = "COMPLETED", "processed"
            if failed and exec_status == "COMPLETED":
                exec_status = "PARTIAL"
            if rec.final_decision == F.ESCALATE and any(s.blocked_reason for s in rec.plan):
                email_status = "awaiting_approval" if awaiting else "failed"
            rec.execution_status = exec_status
            conn.execute("UPDATE decisions SET execution_status=?, duration_ms=?, record_json=? WHERE id=?",
                         (exec_status, rec.duration_ms, rec.model_dump_json(), decision_id))
            conn.execute("UPDATE emails SET status=?, priority=?, priority_score=?, selected_action=?, decision_id=? WHERE id=?",
                         (email_status, rec.priority.label, rec.priority.score, rec.final_decision.value, decision_id, email_id))
            step("Execute", f"Execution result: {exec_status.replace('_', ' ').title()} — {executed} step(s) done, {len(awaiting)} awaiting approval, {failed} refused. "
                            f"Decision time {rec.duration_ms:.0f} ms.")
            return {"decision_id": decision_id, "approval_id": approval_id, "email_id": email_id, "final_decision": rec.final_decision.value,
                    "execution_status": exec_status, "executed": executed, "awaiting": len(awaiting), "failed": failed}

    @staticmethod
    def _loop_result(rec: DecisionRecord, idx: int, text: str) -> None:
        if idx < len(rec.loop_trace):
            rec.loop_trace[idx].result = text

    def _exec_step(self, conn, st: PlanStep, rec_or_none, email_id, decision_id, run_id, *, actor: str, approval_id: int | None) -> None:
        try:
            with transaction(conn):
                result = run_tool(conn, st, email_id=email_id, decision_id=decision_id)
                ex(conn, "INSERT INTO executions(decision_id, email_id, approval_id, step_id, tool, params_json, result_json, success, simulated, actor, created_at) "
                         "VALUES(?,?,?,?,?,?,?,1,1,?,?)",
                   (decision_id, email_id, approval_id, st.step_id, st.tool.value, dumps(st.params), dumps(result), actor, clock.iso(clock.now())))
            st.status, st.result = "executed", result
            self.log(conn, "Execute", result["message"], run_id=run_id, email_id=email_id, decision_id=decision_id)
        except Exception as e:  # noqa: BLE001
            st.status, st.result = "failed", {"message": str(e)}
            ex(conn, "INSERT INTO executions(decision_id, email_id, approval_id, step_id, tool, params_json, result_json, success, simulated, actor, created_at) "
                     "VALUES(?,?,?,?,?,?,?,0,1,?,?)",
               (decision_id, email_id, approval_id, st.step_id, st.tool.value, dumps(st.params), dumps({"error": str(e)}), actor, clock.iso(clock.now())))
            self.log(conn, "Execute", f"{st.title} failed: {e}", run_id=run_id, email_id=email_id, decision_id=decision_id, level="error")

    # ------------------------------------------------------------------ approvals
    def _create_approval(self, conn, decision_id, email_id, rec: DecisionRecord, awaiting: list[PlanStep]) -> int:
        kinds = {s.gate_kind for s in awaiting}
        gate = "mandatory" if "mandatory" in kinds else "learned" if "learned" in kinds else "dependent" if "dependent" in kinds else "mode"
        rules = sorted({r for s in awaiting for r in s.gate_rules if r.startswith("POL-") and not r.startswith("POL-INT")})
        reason = "; ".join(rec.human_reasons)[:480] or "Human confirmation required."
        return ex(conn, "INSERT INTO approvals(decision_id, email_id, status, reason, gate_kind, rule_ids_json, proposed_steps_json, created_at) VALUES(?,?, 'pending', ?,?,?,?,?)",
                  (decision_id, email_id, reason, gate, dumps(rules), dumps([s.model_dump(mode="json") for s in awaiting]), clock.iso(clock.now())))

    def _load_pending(self, conn, approval_id: int) -> tuple[dict, dict]:
        ap = q1(conn, "SELECT * FROM approvals WHERE id=?", (approval_id,))
        if not ap:
            raise KeyError(approval_id)
        if ap["status"] != "pending":
            raise ValueError(f"Approval #{approval_id} was already {ap['status']}")
        dec = q1(conn, "SELECT * FROM decisions WHERE id=?", (ap["decision_id"],))
        return ap, dec

    def _finalize_email(self, conn, email_id: str, decision_id: int, status: str) -> None:
        conn.execute("UPDATE decisions SET execution_status=? WHERE id=?", (status.upper(), decision_id))
        conn.execute("UPDATE emails SET status=? WHERE id=?", ("processed" if status in ("completed", "partial") else status, email_id))

    def approve(self, approval_id: int, feedback: str | None = None) -> dict:
        return self._resolve(approval_id, "approved", feedback, None)

    def reject(self, approval_id: int, feedback: str | None = None) -> dict:
        return self._resolve(approval_id, "rejected", feedback, None)

    def modify(self, approval_id: int, edits: list[StepEdit], feedback: str | None = None) -> dict:
        return self._resolve(approval_id, "modified", feedback, edits)

    def _resolve(self, approval_id: int, kind: str, feedback: str | None, edits: list[StepEdit] | None) -> dict:
        with self.db.connect() as conn:
            ap, dec = self._load_pending(conn, approval_id)
            email_id, decision_id = ap["email_id"], ap["decision_id"]
            steps = [PlanStep.model_validate(s) for s in loads(ap["proposed_steps_json"], [])]
            intent, action = dec["intent"], dec["chosen_action"]
            now_iso = clock.iso(clock.now())

            if kind == "rejected":
                for s in steps:
                    s.status = "rejected"
                conn.execute("UPDATE approvals SET status='rejected', feedback=?, resolved_at=?, final_steps_json=? WHERE id=?",
                             (feedback, now_iso, dumps([s.model_dump(mode="json") for s in steps]), approval_id))
                prefs_mod.record_feedback(conn, approval_id=approval_id, email_id=email_id, intent=intent, action=action, kind="rejected", note=feedback)
                self.log(conn, "Feedback", f"Approval #{approval_id} rejected by human. Preference recorded for {intent.replace('_', ' ').title()}.", email_id=email_id, decision_id=decision_id, level="warn")
                self._finalize_email(conn, email_id, decision_id, "rejected")
                return {"approval_id": approval_id, "status": "rejected", "executed": 0}

            final = steps
            if kind == "modified":
                final = self._apply_edits(steps, edits or [], dec)
                self.log(conn, "Feedback", f"Approval #{approval_id}: human modified the proposed action; re-validating against policy.", email_id=email_id, decision_id=decision_id)

            executed = failed = 0
            for st in final:
                if st.blocked_reason:
                    st.status = "failed"; st.result = {"message": st.blocked_reason}; failed += 1
                    self.log(conn, "Execute", f"Refused by policy even with approval: {st.title}. {st.blocked_reason}", email_id=email_id, decision_id=decision_id, level="error")
                    continue
                self._exec_step(conn, st, None, email_id, decision_id, None, actor="human_approved", approval_id=approval_id)
                executed += st.status == "executed"
                failed += st.status == "failed"
            status = "approved" if kind == "approved" else "modified"
            conn.execute("UPDATE approvals SET status=?, feedback=?, resolved_at=?, final_steps_json=? WHERE id=?",
                         (status, feedback, now_iso, dumps([s.model_dump(mode="json") for s in final]), approval_id))
            prefs_mod.record_feedback(conn, approval_id=approval_id, email_id=email_id, intent=intent, action=action, kind=kind, note=feedback)
            self.log(conn, "Feedback", f"Approval #{approval_id} {status}: {executed} simulated step(s) executed, {failed} refused.", email_id=email_id, decision_id=decision_id)
            self._finalize_email(conn, email_id, decision_id, "completed" if not failed else "partial" if executed else "failed")
            return {"approval_id": approval_id, "status": status, "executed": executed, "failed": failed,
                    "results": [{"step_id": s.step_id, "tool": s.tool.value, "status": s.status, "message": (s.result or {}).get("message")} for s in final]}

    def _apply_edits(self, original: list[PlanStep], edits: list[StepEdit], dec: dict) -> list[PlanStep]:
        """Rebuild the plan from the human's edits and push it back through risk + policy (mode=AUTONOMOUS so
        mandatory policies are evaluated; the human's confirmation covers gates, never blocks)."""
        by_id = {s.step_id: s for s in original}
        rebuilt: list[PlanStep] = []
        for e in edits:
            if e.step_id not in by_id:
                raise ValueError(f"Unknown step {e.step_id}")
            params = validate_params(e.tool, e.params)  # raises pydantic ValidationError -> 422 at API
            rebuilt.append(PlanStep(step_id=e.step_id, tool=e.tool, title=TOOL_LABELS[e.tool], params=params, action_class=classify(e.tool, params),
                                    external=is_external(e.tool, params), rationale="Edited by human"))
        if not rebuilt:
            raise ValueError("A modification must keep at least one step")
        plan_risk(rebuilt)
        evaluate_policies(rebuilt, Mode.AUTONOMOUS)  # recompute blocked_reason / classes; approval is given by the human
        return rebuilt

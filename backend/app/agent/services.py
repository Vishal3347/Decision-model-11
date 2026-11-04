"""Higher-level services built on the orchestrator: runs, scenarios, dashboard, briefing, model views."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any

from .. import clock
from ..db import dumps, ex, loads, q, q1
from ..schemas import DecisionRecord, Mode
from ..seed_data import seed_database
from ..engine.options import satisfice
from .orchestrator import Orchestrator

SCENARIOS = [
    dict(key="production-emergency", title="Production Emergency", email_id="EML-1001", mode="AUTONOMOUS",
         blurb="Server outage → critical urgency, incident ticket, engineering notified, manager escalated.",
         expected=["Critical urgency identified", "Incident ticket created", "Engineering notified", "Escalated to VP Engineering"]),
    dict(key="financial-approval", title="Financial Approval", email_id="EML-1003", mode="AUTONOMOUS",
         blurb="₹2,50,000 vendor payment → financial risk, approval request prepared, nothing runs until a human approves.",
         expected=["Payment details extracted", "Financial risk identified", "Approval request prepared", "No payment executed before approval"]),
    dict(key="routine-meeting", title="Routine Meeting", email_id="EML-1004", mode="AUTONOMOUS",
         blurb="Meeting reminder → low risk, calendar reminder created automatically, task marked completed.",
         expected=["Reminder identified", "Low risk confirmed", "Calendar reminder created", "Task completed"]),
]


class Services:
    def __init__(self, orch: Orchestrator):
        self.o, self.db, self.settings = orch, orch.db, orch.settings

    # ------------------------------------------------------------------ runs
    def start_run(self, kind: str, email_ids: list[str], mode: Mode | None, pace_ms: int | None = None, scenario: str | None = None) -> dict:
        with self.db.connect() as conn:
            active = q1(conn, "SELECT id FROM runs WHERE status='running'")
            if active:
                raise RuntimeError(f"Run {active['id']} is already in progress")
            mode = mode or self.o.mode(conn)
            run_id = uuid.uuid4().hex[:10]
            ex(conn, "INSERT INTO runs(id, kind, status, mode, started_at, email_ids_json, total) VALUES(?,?, 'running', ?,?,?,?)",
               (run_id, kind if not scenario else f"scenario:{scenario}", mode.value, clock.iso(clock.now()), dumps(email_ids), len(email_ids)))
            self.o.log(conn, "Run", f"Agent started in {mode.value.replace('_', ' ').title()} mode — {len(email_ids)} email(s) queued.", run_id=run_id)
        if self.settings.sync_runs:
            self._work(run_id, email_ids, mode, pace_ms)
        else:
            threading.Thread(target=self._work, args=(run_id, email_ids, mode, pace_ms), daemon=True).start()
        return {"run_id": run_id, "total": len(email_ids), "mode": mode.value}

    def _work(self, run_id: str, email_ids: list[str], mode: Mode, pace_ms: int | None) -> None:
        results, error = [], None
        try:
            for eid in email_ids:
                try:
                    results.append(self.o.process_email(eid, mode=mode, run_id=run_id, pace_ms=pace_ms))
                except Exception as e:  # noqa: BLE001
                    results.append({"email_id": eid, "error": str(e)})
                    with self.db.connect() as conn:
                        conn.execute("UPDATE emails SET status='failed' WHERE id=?", (eid,))
                        self.o.log(conn, "Execute", f"Processing {eid} failed: {e}", run_id=run_id, email_id=eid, level="error")
                with self.db.connect() as conn:
                    conn.execute("UPDATE runs SET completed=completed+1 WHERE id=?", (run_id,))
        except Exception as e:  # noqa: BLE001
            error = str(e)
        with self.db.connect() as conn:
            status = "failed" if error else "completed"
            conn.execute("UPDATE runs SET status=?, finished_at=?, current_stage=NULL, current_email_id=NULL, summary_json=?, error=? WHERE id=?",
                         (status, clock.iso(clock.now()), dumps(results), error, run_id))
            self.o.log(conn, "Run", f"Run finished: {sum(1 for r in results if 'error' not in r)}/{len(email_ids)} email(s) processed.", run_id=run_id)

    def current_run(self) -> dict | None:
        with self.db.connect() as conn:
            r = q1(conn, "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT 1")
            if r:
                r["email_ids"] = loads(r.pop("email_ids_json"), [])
                r["summary"] = loads(r.pop("summary_json"), None)
            return r

    def unprocessed_ids(self) -> list[str]:
        with self.db.connect() as conn:
            return [r["id"] for r in q(conn, "SELECT id FROM emails WHERE status IN ('new','failed') ORDER BY timestamp DESC")]

    # ------------------------------------------------------------------ scenarios
    def reset(self) -> None:
        with self.db.connect() as conn:
            seed_database(conn)
            self.o.log(conn, "System", "Demo data reset to the initial inbox.")

    def scenario_def(self, key: str) -> dict:
        for s in SCENARIOS:
            if s["key"] == key:
                return s
        raise KeyError(key)

    def run_scenario(self, key: str | None, pace_ms: int | None = None) -> dict:
        """Reset to a clean seeded state, then process one scenario (or all three)."""
        with self.db.connect() as conn:
            if q1(conn, "SELECT id FROM runs WHERE status='running'"):
                raise RuntimeError("A run is already in progress")
        scenarios = SCENARIOS if key is None else [self.scenario_def(key)]
        self.reset()
        with self.db.connect() as conn:
            conn.execute("UPDATE settings SET value=? WHERE key='mode'", (dumps(Mode.AUTONOMOUS.value),))
        return self.start_run("scenario", [s["email_id"] for s in scenarios], Mode.AUTONOMOUS, pace_ms, scenario=key or "all")

    def scenario_status(self) -> list[dict]:
        out = []
        with self.db.connect() as conn:
            for s in SCENARIOS:
                e = q1(conn, "SELECT status, decision_id FROM emails WHERE id=?", (s["email_id"],))
                d = q1(conn, "SELECT * FROM decisions WHERE id=?", (e["decision_id"],)) if e and e["decision_id"] else None
                checks = []
                if d:
                    ex_rows = q(conn, "SELECT tool, success FROM executions WHERE decision_id=? AND success=1", (d["id"],))
                    tools = {r["tool"] for r in ex_rows}
                    pend = q1(conn, "SELECT id FROM approvals WHERE decision_id=? AND status='pending'", (d["id"],))
                    if s["key"] == "production-emergency":
                        checks = [("Critical urgency identified", d["priority_label"] == "Critical"), ("Incident ticket created", "create_ticket" in tools),
                                  ("Engineering notified", "send_notification" in tools), ("Escalated to VP Engineering", "escalate_to_manager" in tools)]
                    elif s["key"] == "financial-approval":
                        paid = "process_payment" in tools
                        checks = [("Payment details extracted", "250000" in (d["record_json"] or "")), ("Financial risk identified", d["risk_score"] >= 6.5),
                                  ("Approval request prepared", pend is not None or paid), ("No payment executed before approval", pend is not None and not paid or paid)]
                    else:
                        checks = [("Reminder identified", d["intent"] == "MEETING_REMINDER"), ("Low risk confirmed", d["risk_label"] == "Low"),
                                  ("Calendar reminder created", "create_calendar_event" in tools), ("Task completed", "complete_task" in tools)]
                out.append({**s, "email_status": e["status"] if e else None, "decision_id": d["id"] if d else None, "final_decision": d["final_decision"] if d else None,
                            "execution_status": d["execution_status"] if d else None, "checks": [{"label": a, "passed": bool(b)} for a, b in checks]})
        return out

    # ------------------------------------------------------------------ dashboard
    def dashboard(self) -> dict:
        with self.db.connect() as conn:
            n = lambda sql, p=(): q1(conn, sql, p)["n"]  # noqa: E731
            processed = n("SELECT COUNT(*) n FROM emails WHERE decision_id IS NOT NULL")
            execs = q1(conn, "SELECT SUM(success) ok, COUNT(*) total FROM executions")
            avg = q1(conn, "SELECT AVG(duration_ms) a FROM decisions")["a"]
            latest = q(conn, "SELECT d.* FROM decisions d JOIN emails e ON e.decision_id=d.id")
            dist = {k: 0 for k in ("Critical", "High", "Medium", "Low")}
            for d in latest:
                dist[d["priority_label"]] = dist.get(d["priority_label"], 0) + 1
            tasks = q(conn, "SELECT status, COUNT(*) n FROM tasks GROUP BY status")
            tmap = {t["status"]: t["n"] for t in tasks}
            decisions_by = {}
            for d in latest:
                decisions_by[d["final_decision"]] = decisions_by.get(d["final_decision"], 0) + 1
            pending = q(conn, "SELECT a.id, a.email_id, a.reason, a.created_at, e.subject, d.priority_score, d.risk_score, d.priority_label, d.risk_label "
                              "FROM approvals a JOIN emails e ON e.id=a.email_id JOIN decisions d ON d.id=a.decision_id WHERE a.status='pending' ORDER BY d.priority_score DESC")
            return {
                "metrics": {
                    "total_emails": n("SELECT COUNT(*) n FROM emails"), "emails_processed": processed,
                    "autonomous_actions": n("SELECT COUNT(*) n FROM executions WHERE success=1 AND actor='agent'"),
                    "pending_approvals": len(pending),
                    "critical_alerts": sum(1 for d in latest if d["priority_label"] == "Critical"),
                    "tasks_awaiting_followup": tmap.get("open", 0),
                    "avg_decision_ms": round(avg, 1) if avg is not None else None,
                    "automation_success_rate": round(100 * execs["ok"] / execs["total"], 1) if execs["total"] else None,
                    "executions_total": execs["total"],
                },
                "priority_distribution": [{"label": k, "count": v} for k, v in dist.items()],
                "decision_distribution": [{"label": k, "count": v} for k, v in decisions_by.items()],
                "task_completion": {"open": tmap.get("open", 0), "completed": tmap.get("completed", 0)},
                "pending_decisions": pending,
                "recent_activity": q(conn, "SELECT * FROM activity ORDER BY id DESC LIMIT 12"),
            }

    # ------------------------------------------------------------------ briefing
    def briefing(self) -> dict:
        now = clock.now()
        with self.db.connect() as conn:
            crit = q(conn, "SELECT e.id, e.subject, e.status, d.priority_score, d.final_decision, d.execution_status FROM emails e JOIN decisions d ON d.id=e.decision_id "
                           "WHERE d.priority_label='Critical' ORDER BY d.priority_score DESC")
            done = q(conn, "SELECT x.tool, x.actor, x.created_at, x.result_json, x.email_id FROM executions x WHERE x.success=1 ORDER BY x.id DESC LIMIT 12")
            for d in done:
                d["message"] = (loads(d.pop("result_json"), {}) or {}).get("message")
            pend = q(conn, "SELECT a.id, e.subject, a.reason, d.priority_score FROM approvals a JOIN emails e ON e.id=a.email_id JOIN decisions d ON d.id=a.decision_id "
                           "WHERE a.status='pending' ORDER BY d.priority_score DESC")
            cust = q(conn, "SELECT e.id, e.sender_name, e.subject, e.status, e.priority, e.selected_action FROM emails e WHERE e.sender_type='external' AND e.category IN ('Customer Support','Sales','Business Development') ORDER BY e.timestamp DESC")
            cust += q(conn, "SELECT e.id, e.sender_name, e.subject, e.status, e.priority, e.selected_action FROM emails e WHERE e.category='Business Development'")
            meetings = [m for m in q(conn, "SELECT * FROM calendar_events ORDER BY start_at") if m["end_at"] >= clock.iso(now)][:8]
            follow = q(conn, "SELECT id, title, due_at, priority, status FROM tasks WHERE task_type='followup' AND status='open' ORDER BY due_at")
            attention = q(conn, "SELECT id, title, priority, due_at, ticket_ref FROM tasks WHERE status='open' ORDER BY CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, due_at LIMIT 10")
            new = q1(conn, "SELECT COUNT(*) n FROM emails WHERE status IN ('new','failed')")["n"]
            facts = {"counts": {"critical": len(crit), "pending_approvals": len(pend), "completed_actions": len(done), "new_emails": new,
                                "open_tasks": len(attention), "upcoming_meetings": len(meetings)},
                     "top_critical": [c["subject"][:80] for c in crit]}
            narrative, provider = self.o.provider.briefing(facts)
            content = dict(generated_at=clock.iso(now), headline=narrative.headline, summary=narrative.summary, narrative_provider=provider, counts=facts["counts"],
                           critical_issues=crit, completed_actions=done, pending_approvals=pend, customer_communications=list({c["id"]: c for c in cust}.values()),
                           upcoming_meetings=meetings, follow_ups=follow, tasks_attention=attention)
            ex(conn, "INSERT INTO briefings(generated_at, content_json) VALUES(?,?)", (content["generated_at"], dumps(content)))
            self.o.log(conn, "Briefing", "Daily executive briefing generated.")
            return content

    def latest_briefing(self) -> dict | None:
        with self.db.connect() as conn:
            r = q1(conn, "SELECT content_json FROM briefings ORDER BY id DESC LIMIT 1")
            return loads(r["content_json"]) if r else None

    # ------------------------------------------------------------------ model explorer
    def record_for(self, email_id: str) -> tuple[DecisionRecord, bool]:
        """Return the stored decision for a processed email, else a live preview. Second value: processed?"""
        with self.db.connect() as conn:
            e = q1(conn, "SELECT decision_id FROM emails WHERE id=?", (email_id,))
            if not e:
                raise KeyError(email_id)
            if e["decision_id"]:
                d = q1(conn, "SELECT record_json FROM decisions WHERE id=?", (e["decision_id"],))
                if d and d["record_json"] not in ("", "{}"):
                    return DecisionRecord.model_validate_json(d["record_json"]), True
        return self.o.preview(email_id), False

    def models(self, email_id: str) -> dict:
        rec, processed = self.record_for(email_id)
        opts = rec.options
        sat = satisfice(opts, rec.priority.score)
        tree = [dict(action=o.action.value, label=o.label, rank=o.rank, branches=[
            dict(outcome="Succeeds", p=o.p_success, value=round(o.benefit + o.preference_adjustment + o.llm_bonus - o.effort, 1)),
            dict(outcome="Fails / backfires", p=round(1 - o.p_success, 3), value=round(-o.loss - o.effort, 1))], expected_value=o.expected_utility,
            risk=o.risk_score, needs_human=o.needs_human, chosen=o.action == rec.chosen_action) for o in opts]
        triggered = [c for c in rec.policy_checks if c.triggered]
        gate_steps = [dict(step_id=s.step_id, title=s.title, action_class=s.action_class.value, risk=s.risk_score, external=s.external,
                           gate_kind=s.gate_kind, rules=[r for r in s.gate_rules], decision="Blocked" if s.blocked_reason else "Human approval" if s.requires_approval else "Autonomous")
                      for s in rec.plan]
        chosen_o = next(o for o in opts if o.action == rec.chosen_action)
        awaiting = rec.execution_status == "AWAITING_APPROVAL" or (not processed and rec.requires_human)
        nxt = "ESCALATED" if rec.final_decision.value == "ESCALATE" else "AWAITING_APPROVAL" if awaiting else "ARCHIVED" if rec.final_decision.value == "IGNORE" else "RESOLVED"
        traj = [dict(state="NEW_EMAIL", action="analyze", reward=-0.1, next_state="ANALYZED"),
                dict(state="ANALYZED", action=rec.chosen_action.value, reward=round(chosen_o.expected_utility / 10, 2), next_state=nxt)]
        if nxt == "AWAITING_APPROVAL":
            traj.append(dict(state="AWAITING_APPROVAL", action="human_decision", reward=round(rec.priority.score / 10, 2), next_state="RESOLVED"))
        return dict(email_id=email_id, processed=processed, mode=rec.mode.value, record=rec.model_dump(mode="json"),
                    expected_utility=dict(options=[o.model_dump(mode="json") for o in opts], selected=rec.chosen_action.value, formula="EU = P(success)·Benefit − (1−P)·Loss − Effort + preference + LLM bonus"),
                    satisficing=sat, decision_tree=tree,
                    weighted_matrix=rec.priority.model_dump(mode="json"),
                    rule_based=dict(triggered=[c.model_dump(mode="json") for c in triggered], all_rules=[c.model_dump(mode="json") for c in rec.policy_checks],
                                    llm_proposed=rec.llm_proposed_decision.value, final=rec.final_decision.value, overridden=rec.policy_override, reasons=rec.override_reasons),
                    mdp=dict(trajectory=traj, q_values=[dict(action=o.action.value, q=round(o.expected_utility / 10, 2)) for o in opts], gamma=0.9,
                             note="Educational simulation: rewards are derived from this email's expected utility. No reinforcement learning or policy training takes place; feedback only adjusts preference counters."),
                    human_in_loop=dict(steps=gate_steps, overall_risk=rec.risk.score, risk_label=rec.risk.label, requires_human=rec.requires_human, reasons=rec.human_reasons,
                                       routing=[r.model_dump(mode="json") for r in rec.routing]),
                    agent_loop=[l.model_dump(mode="json") for l in rec.loop_trace])

    def compare_modes(self, email_id: str) -> dict:
        out = {}
        for m in (Mode.AUTONOMOUS, Mode.HUMAN_CONTROLLED):
            r = self.o.preview(email_id, m)
            out[m.value] = dict(final_decision=r.final_decision.value, requires_human=r.requires_human, steps=[
                dict(title=s.title, tool=s.tool.value, behaviour="Refused" if s.blocked_reason else "Waits for approval" if s.requires_approval else "Runs automatically",
                     gate_kind=s.gate_kind, rules=s.gate_rules) for s in r.plan])
        return out

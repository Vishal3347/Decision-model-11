"""FastAPI application: thin HTTP layer over the orchestrator and services."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import clock
from .agent.orchestrator import Orchestrator
from .agent.services import SCENARIOS, Services
from .config import Settings, get_settings
from .db import Database, dumps, loads, q, q1, set_setting
from .engine import preferences as prefs_mod
from .engine.scoring import validate_weights
from .llm.factory import build_provider
from .schemas import (ApprovalAction, DecisionRecord, ModeUpdate, ModifyRequest, ProcessRequest, TaskUpdate, WeightsUpdate)
from .seed_data import ensure_seeded


class AppState:
    def __init__(self, settings: Settings, provider=None):
        self.settings = settings
        self.db = Database(settings.database_path)
        self.provider = provider or build_provider(settings)
        self.orch = Orchestrator(self.db, self.provider, settings)
        self.svc = Services(self.orch)
        with self.db.connect() as conn:
            ensure_seeded(conn)
            # a restart interrupts any in-flight run; mark it so the UI never shows a ghost run
            conn.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (clock.iso(clock.now()),))
            conn.execute("UPDATE emails SET status='new' WHERE status='processing'")


def create_app(settings: Settings | None = None, provider=None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.s = AppState(settings, provider)
        yield

    app = FastAPI(title="Decision Intelligence Simulator", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def S(request: Request) -> AppState:
        return request.app.state.s

    @app.exception_handler(KeyError)
    async def _nf(_: Request, exc: KeyError):
        return JSONResponse(status_code=404, content={"detail": f"Not found: {exc.args[0]}"})

    @app.exception_handler(ValidationError)
    async def _ve(_: Request, exc: ValidationError):
        msgs = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return JSONResponse(status_code=422, content={"detail": "Invalid action parameters — " + "; ".join(msgs)})

    @app.exception_handler(ValueError)
    async def _val(_: Request, exc: ValueError):
        return JSONResponse(status_code=409 if "already" in str(exc) else 422, content={"detail": str(exc)})

    @app.exception_handler(RuntimeError)
    async def _rt(_: Request, exc: RuntimeError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    # ---------------------------------------------------------------- system
    @app.get("/api/health")
    def health(s: AppState = Depends(S)):
        return {"status": "ok", "llm": s.provider.public_info, "time": clock.iso(clock.now())}

    @app.get("/api/state")
    def state(s: AppState = Depends(S)):
        with s.db.connect() as conn:
            return {"mode": s.orch.mode(conn).value, "weights": s.orch.weights(conn), "llm": s.provider.public_info,
                    "run": s.svc.current_run(), "pending_approvals": q1(conn, "SELECT COUNT(*) n FROM approvals WHERE status='pending'")["n"]}

    @app.put("/api/mode")
    def set_mode(body: ModeUpdate, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            set_setting(conn, "mode", body.mode.value)
            s.orch.log(conn, "Mode", f"Operating mode switched to {body.mode.value.replace('_', ' ').title()}.")
        return {"mode": body.mode.value}

    @app.put("/api/weights")
    def set_weights(body: WeightsUpdate, s: AppState = Depends(S)):
        try:
            w = validate_weights(body.model_dump())
        except ValueError as e:
            raise HTTPException(422, str(e))
        with s.db.connect() as conn:
            set_setting(conn, "weights", w)
            s.orch.log(conn, "Config", "Priority weights updated.")
        return {"weights": w}

    @app.post("/api/reset")
    def reset(s: AppState = Depends(S)):
        if (s.svc.current_run() or {}).get("status") == "running":
            raise HTTPException(409, "A run is in progress")
        s.svc.reset()
        return {"status": "reset"}

    # ---------------------------------------------------------------- inbox
    @app.get("/api/emails")
    def emails(q_: Optional[str] = Query(None, alias="q"), category: Optional[str] = None, priority: Optional[str] = None, status: Optional[str] = None,
               sort: Literal["newest", "oldest", "priority", "sender"] = "newest", s: AppState = Depends(S)):
        sql, p = "SELECT * FROM emails WHERE 1=1", []
        if q_:
            sql += " AND (subject LIKE ? OR body LIKE ? OR sender_name LIKE ?)"
            p += [f"%{q_}%"] * 3
        for col, val in (("category", category), ("priority", priority), ("status", status)):
            if val:
                sql += f" AND {col}=?"
                p.append(val)
        order = {"newest": "timestamp DESC", "oldest": "timestamp ASC", "sender": "sender_name ASC",
                 "priority": "CASE priority WHEN 'Critical' THEN 0 WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END, timestamp DESC"}[sort]
        with s.db.connect() as conn:
            rows = q(conn, sql + f" ORDER BY {order}", p)
            cats = [r["category"] for r in q(conn, "SELECT DISTINCT category FROM emails ORDER BY category")]
        return {"emails": [{k: v for k, v in r.items() if k != "body"} | {"preview": " ".join(r["body"].split())[:140]} for r in rows], "categories": cats}

    @app.get("/api/emails/{email_id}")
    def email_detail(email_id: str, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            e = q1(conn, "SELECT * FROM emails WHERE id=?", (email_id,))
            if not e:
                raise KeyError(email_id)
            dec = q1(conn, "SELECT record_json FROM decisions WHERE id=?", (e["decision_id"],)) if e["decision_id"] else None
            record = loads(dec["record_json"]) if dec and dec["record_json"] != "{}" else None
            ap = q1(conn, "SELECT * FROM approvals WHERE email_id=? ORDER BY id DESC LIMIT 1", (email_id,))
            if ap:
                ap["proposed_steps"] = loads(ap.pop("proposed_steps_json"), [])
                ap["final_steps"] = loads(ap.pop("final_steps_json"), None)
                ap["rule_ids"] = loads(ap.pop("rule_ids_json"), [])
            return {"email": e, "decision": record, "approval": ap,
                    "activity": q(conn, "SELECT * FROM activity WHERE email_id=? ORDER BY id", (email_id,)),
                    "executions": q(conn, "SELECT tool, result_json, success, actor, created_at FROM executions WHERE email_id=? ORDER BY id", (email_id,))}

    @app.post("/api/emails/{email_id}/process")
    def process_one(email_id: str, body: ProcessRequest | None = None, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            if not q1(conn, "SELECT 1 FROM emails WHERE id=?", (email_id,)):
                raise KeyError(email_id)
            if q1(conn, "SELECT status FROM emails WHERE id=?", (email_id,))["status"] not in ("new", "failed"):
                raise ValueError("Email was already processed — reset the demo data to process it again")
        b = body or ProcessRequest()
        return s.svc.start_run("single", [email_id], b.mode, b.pace_ms)

    @app.post("/api/process-inbox")
    def process_inbox(body: ProcessRequest | None = None, s: AppState = Depends(S)):
        ids = s.svc.unprocessed_ids()
        if not ids:
            raise ValueError("No unprocessed emails — reset the demo data to start over")
        b = body or ProcessRequest()
        return s.svc.start_run("inbox", ids, b.mode, b.pace_ms)

    @app.get("/api/runs/current")
    def run_current(s: AppState = Depends(S)):
        return s.svc.current_run()

    @app.get("/api/emails/{email_id}/compare")
    def compare(email_id: str, s: AppState = Depends(S)):
        return s.svc.compare_modes(email_id)

    @app.get("/api/models/{email_id}")
    def models(email_id: str, s: AppState = Depends(S)):
        return s.svc.models(email_id)

    # ---------------------------------------------------------------- activity / dashboard
    @app.get("/api/activity")
    def activity(after_id: int = 0, limit: int = Query(100, le=500), email_id: Optional[str] = None, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            sql, p = "SELECT * FROM activity WHERE id>?", [after_id]
            if email_id:
                sql += " AND email_id=?"
                p.append(email_id)
            rows = q(conn, sql + " ORDER BY id DESC LIMIT ?", p + [limit])
        return {"events": list(reversed(rows)), "run": s.svc.current_run()}

    @app.get("/api/dashboard")
    def dashboard(s: AppState = Depends(S)):
        return s.svc.dashboard()

    # ---------------------------------------------------------------- approvals
    @app.get("/api/approvals")
    def approvals(status: Optional[str] = None, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            sql = ("SELECT a.*, e.subject, e.sender_name, e.sender_email, e.body, e.category, d.priority_score, d.priority_label, d.risk_score, d.risk_label, "
                   "d.final_decision, d.intent, d.summary, d.mode FROM approvals a JOIN emails e ON e.id=a.email_id JOIN decisions d ON d.id=a.decision_id")
            rows = q(conn, sql + (" WHERE a.status=?" if status else "") + " ORDER BY (a.status='pending') DESC, d.priority_score DESC, a.id DESC", [status] if status else [])
            for r in rows:
                r["proposed_steps"] = loads(r.pop("proposed_steps_json"), [])
                r["final_steps"] = loads(r.pop("final_steps_json"), None)
                r["rule_ids"] = loads(r.pop("rule_ids_json"), [])
        return {"approvals": rows}

    @app.post("/api/approvals/{approval_id}/approve")
    def approve(approval_id: int, body: ApprovalAction | None = None, s: AppState = Depends(S)):
        return s.orch.approve(approval_id, body.feedback if body else None)

    @app.post("/api/approvals/{approval_id}/reject")
    def reject(approval_id: int, body: ApprovalAction | None = None, s: AppState = Depends(S)):
        return s.orch.reject(approval_id, body.feedback if body else None)

    @app.post("/api/approvals/{approval_id}/modify")
    def modify(approval_id: int, body: ModifyRequest, s: AppState = Depends(S)):
        return s.orch.modify(approval_id, body.steps, body.feedback)

    @app.get("/api/preferences")
    def preferences(s: AppState = Depends(S)):
        with s.db.connect() as conn:
            return {"preferences": prefs_mod.summary(conn), "events": q(conn, "SELECT * FROM feedback_events ORDER BY id DESC LIMIT 20"),
                    "note": "Feedback adjusts preference counters used by the decision engine. The underlying language model is not retrained."}

    # ---------------------------------------------------------------- work products
    @app.get("/api/workspace")
    def workspace(s: AppState = Depends(S)):
        with s.db.connect() as conn:
            return {"tasks": q(conn, "SELECT * FROM tasks ORDER BY (status='open') DESC, id DESC"), "calendar": q(conn, "SELECT * FROM calendar_events ORDER BY start_at"),
                    "notifications": q(conn, "SELECT * FROM notifications ORDER BY id DESC LIMIT 30"), "outbox": q(conn, "SELECT * FROM outbox ORDER BY id DESC LIMIT 20"),
                    "records": [r | {"detail": loads(r.pop("detail_json"))} for r in q(conn, "SELECT * FROM sim_records ORDER BY id DESC LIMIT 20")]}

    @app.patch("/api/tasks/{task_id}")
    def patch_task(task_id: int, body: TaskUpdate, s: AppState = Depends(S)):
        with s.db.connect() as conn:
            if not q1(conn, "SELECT 1 FROM tasks WHERE id=?", (task_id,)):
                raise KeyError(task_id)
            conn.execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?", (body.status, clock.iso(clock.now()) if body.status == "completed" else None, task_id))
        return {"id": task_id, "status": body.status}

    # ---------------------------------------------------------------- briefing / scenarios
    @app.post("/api/briefing/generate")
    def gen_briefing(s: AppState = Depends(S)):
        return s.svc.briefing()

    @app.get("/api/briefing/latest")
    def latest_briefing(s: AppState = Depends(S)):
        return s.svc.latest_briefing()

    @app.get("/api/scenarios")
    def scenarios(s: AppState = Depends(S)):
        return {"scenarios": s.svc.scenario_status(), "run": s.svc.current_run()}

    @app.post("/api/scenarios/run-all")
    def run_all(body: ProcessRequest | None = None, s: AppState = Depends(S)):
        return s.svc.run_scenario(None, body.pace_ms if body else None)

    @app.post("/api/scenarios/{key}/run")
    def run_scenario(key: str, body: ProcessRequest | None = None, s: AppState = Depends(S)):
        return s.svc.run_scenario(key, body.pace_ms if body else None)

    return app


app = create_app()

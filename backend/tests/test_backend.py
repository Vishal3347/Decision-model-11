import httpx, pytest
from app import clock
from app.config import get_settings
from app.engine.pipeline import analyze_email
from app.engine.scoring import compute_priority, validate_weights
from app.llm.factory import build_provider
from app.main import create_app
from app.schemas import Mode
from app.seed_data import build_emails
from fastapi.testclient import TestClient

def rec(eid, mode=Mode.AUTONOMOUS, prefs=None):
    e = next(x for x in build_emails(clock.now()) if x["id"] == eid)
    from app.constants import DEFAULT_WEIGHTS
    return analyze_email(e, provider=build_provider(get_settings()), mode=mode, weights=DEFAULT_WEIGHTS, prefs=prefs or {}, now=clock.now())

def approvals(c, status="pending"):
    return c.get(f"/api/approvals?status={status}").json()["approvals"]

def by_subject(c, word):
    return next(a for a in approvals(c) if word in a["subject"])

# ---- scoring
def test_priority_formula():
    p = compute_priority(dict(urgency=10, business_impact=10, time_sensitivity=10, customer_importance=10))
    assert p.score == 10.0
    p = compute_priority(dict(urgency=8, business_impact=6, time_sensitivity=4, customer_importance=2))
    assert p.score == round(8*.35 + 6*.30 + 4*.20 + 2*.15, 2)

def test_weights_must_sum_to_one():
    with pytest.raises(ValueError): validate_weights(dict(urgency=.5, business_impact=.5, time_sensitivity=.5, customer_importance=.5))

# ---- policies override LLM
@pytest.mark.parametrize("eid,tool", [("EML-1003", "process_payment"), ("EML-1006", "sign_contract"), ("EML-1011", "delete_records")])
@pytest.mark.parametrize("mode", [Mode.AUTONOMOUS, Mode.HUMAN_CONTROLLED])
def test_mandatory_approval_in_both_modes(eid, tool, mode):
    r = rec(eid, mode)
    step = next(s for s in r.plan if s.tool.value == tool)
    assert step.requires_approval and step.gate_kind == "mandatory"
    assert r.llm_proposed_decision.value == "AUTO_EXECUTE" and r.final_decision.value == "DRAFT_AND_APPROVE" and r.policy_override

def test_external_email_needs_approval_and_dependents_wait():
    r = rec("EML-1007")
    assert next(s for s in r.plan if s.tool.value == "send_email").requires_approval
    assert not next(s for s in r.plan if s.tool.value == "create_ticket").requires_approval
    p = rec("EML-1003")
    assert all(s.requires_approval for s in p.plan)  # notification must not run before payment approval

def test_modes_differ_and_routine_is_auto():
    a, h = rec("EML-1004"), rec("EML-1004", Mode.HUMAN_CONTROLLED)
    assert not any(s.requires_approval for s in a.plan) and all(s.requires_approval for s in h.plan)
    assert a.risk.label == "Low"

def test_llm_cannot_lower_risk_or_score(env):
    from app.engine.risk import plan_risk
    r = rec("EML-1003")
    low = plan_risk(r.plan, {k: 1 for k in r.risk.factors})
    assert low.score == r.risk.score or low.score >= 6.5

# ---- LLM validation / fallback
def test_invalid_llm_output_falls_back_to_mock(env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq"); monkeypatch.setenv("GROQ_API_KEY", "k")
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"choices": [{"message": {"content": '{"intent": "NOPE"}'}}]}))
    prov = build_provider(get_settings(), transport)
    e = build_emails(clock.now())[0]
    from app.engine.observation import observe
    ctx, name, model, reason = prov.analyze(observe(e, clock.now()), e)
    assert name == "mock" and "invalid structured output" in reason

def test_missing_key_uses_mock(env, monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini"); monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert not build_provider(get_settings()).public_info["live"]

def test_underscored_llm_scores_are_floored():
    from app.engine.pipeline import validate_context
    from app.engine.observation import observe
    from app.schemas import LLMContext
    from app.engine.heuristics import baseline_context
    e = build_emails(clock.now())[0]; obs = observe(e, clock.now())
    d = baseline_context(obs); d.update(urgency=1, business_impact=1, time_sensitivity=1, intent="GENERAL")
    ctx = validate_context(LLMContext.model_validate(d), obs, "x", "y", None)
    assert ctx.intent.value == "PRODUCTION_INCIDENT" and ctx.scores["urgency"] >= 9

# ---- API flows
def test_process_inbox_and_dashboard(client):
    assert client.post("/api/process-inbox").status_code == 200
    m = client.get("/api/dashboard").json()["metrics"]
    assert m["emails_processed"] == 12 and m["pending_approvals"] == len(approvals(client))
    assert m["autonomous_actions"] > 0 and m["automation_success_rate"] == 100.0
    assert client.post("/api/process-inbox").status_code == 422  # nothing left

def test_no_payment_before_approval_then_simulated_after(client):
    client.post("/api/emails/EML-1003/process")
    assert client.get("/api/workspace").json()["records"] == []
    ap = approvals(client)[0]
    r = client.post(f"/api/approvals/{ap['id']}/approve", json={"feedback": "ok"}).json()
    assert r["executed"] == 2
    rec_ = client.get("/api/workspace").json()["records"][0]
    assert rec_["kind"] == "payment" and rec_["detail"]["amount"] == 250000
    assert client.post(f"/api/approvals/{ap['id']}/approve").status_code == 409

def test_reject_records_feedback_and_executes_nothing(client):
    client.post("/api/emails/EML-1006/process")
    ap = approvals(client)[0]
    assert client.post(f"/api/approvals/{ap['id']}/reject", json={"feedback": "no"}).json()["status"] == "rejected"
    assert client.get("/api/workspace").json()["records"] == []
    assert client.get("/api/preferences").json()["preferences"][0]["rejections"] == 1

def test_modify_is_revalidated(client):
    client.post("/api/emails/EML-1003/process")
    ap = approvals(client)[0]
    bad = {"steps": [{"step_id": "s1", "tool": "process_payment", "params": {"vendor": "X", "amount": 5_000_000}}]}
    r = client.post(f"/api/approvals/{ap['id']}/modify", json=bad).json()
    assert r["executed"] == 0 and r["failed"] == 1  # hard cap refuses even with approval
    assert client.get("/api/workspace").json()["records"] == []

def test_modify_ok_and_invalid_params(client):
    client.post("/api/emails/EML-1003/process")
    ap = approvals(client)[0]
    assert client.post(f"/api/approvals/{ap['id']}/modify", json={"steps": [{"step_id": "s1", "tool": "process_payment", "params": {"vendor": "X", "amount": -1}}]}).status_code == 422
    ok = {"steps": [{"step_id": "s1", "tool": "process_payment", "params": {"vendor": "CloudNest", "invoice": "INV-1", "amount": 200000}}]}
    r = client.post(f"/api/approvals/{ap['id']}/modify", json=ok).json()
    assert r["status"] == "modified" and r["executed"] == 1
    assert client.get("/api/workspace").json()["records"][0]["detail"]["amount"] == 200000

def test_modify_cannot_hide_external_recipient(client):
    client.post("/api/emails/EML-1007/process")
    ap = approvals(client)[0]
    r = client.post(f"/api/approvals/{ap['id']}/modify", json={"steps": [{"step_id": "s4", "tool": "send_email", "params": {"to": "x@evil.example", "subject": "s", "body": "b"}}]}).json()
    assert r["status"] == "modified"  # still only executed because a human explicitly confirmed it
    assert client.get("/api/workspace").json()["outbox"][0]["status"] == "simulated_sent"

def test_modes_via_api(client):
    client.put("/api/mode", json={"mode": "HUMAN_CONTROLLED"})
    client.post("/api/emails/EML-1004/process")
    assert len(approvals(client)) == 1 and client.get("/api/workspace").json()["calendar"][-1]["created_by"] == "seed"
    client.post(f"/api/approvals/{approvals(client)[0]['id']}/approve")
    assert any(e["created_by"] == "agent" for e in client.get("/api/workspace").json()["calendar"])

def test_scenarios_repeatable(client):
    for _ in range(2):
        client.post("/api/scenarios/run-all")
        sc = client.get("/api/scenarios").json()["scenarios"]
        assert all(c["passed"] for s in sc for c in s["checks"]), sc
        assert client.get("/api/dashboard").json()["metrics"]["emails_processed"] == 3

def test_models_and_compare_and_briefing(client):
    client.post("/api/process-inbox")
    m = client.get("/api/models/EML-1003").json()
    for k in ("expected_utility", "satisficing", "decision_tree", "weighted_matrix", "rule_based", "mdp", "human_in_loop", "agent_loop"):
        assert k in m
    assert m["rule_based"]["overridden"] and "no reinforcement learning" in m["mdp"]["note"].lower()
    cmp_ = client.get("/api/emails/EML-1004/compare").json()
    assert cmp_["AUTONOMOUS"]["steps"][0]["behaviour"] == "Runs automatically" and cmp_["HUMAN_CONTROLLED"]["steps"][0]["behaviour"] == "Waits for approval"
    b = client.post("/api/briefing/generate").json()
    assert b["counts"]["pending_approvals"] == len(approvals(client)) and b["critical_issues"]

def test_inbox_search_filter_sort(client):
    assert len(client.get("/api/emails").json()["emails"]) == 12
    assert len(client.get("/api/emails?q=payment").json()["emails"]) >= 1
    assert all(e["category"] == "HR" for e in client.get("/api/emails?category=HR").json()["emails"])
    assert client.get("/api/emails?sort=priority").json()["emails"][0]["priority"] == "Critical"

def test_persistence_across_restart(env):
    with TestClient(create_app(get_settings())) as c:
        c.post("/api/emails/EML-1003/process")
    with TestClient(create_app(get_settings())) as c:
        assert len(approvals(c)) == 1 and c.get("/api/dashboard").json()["metrics"]["emails_processed"] == 1
        assert c.get("/api/emails/EML-1003").json()["decision"]["final_decision"] == "DRAFT_AND_APPROVE"

def test_weights_configurable(client):
    assert client.put("/api/weights", json=dict(urgency=.25, business_impact=.25, time_sensitivity=.25, customer_importance=.25)).status_code == 200
    assert client.put("/api/weights", json=dict(urgency=.9, business_impact=.9, time_sensitivity=.9, customer_importance=.9)).status_code == 422

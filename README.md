# Decision Intelligence Simulator

An interactive executive-assistant agent that processes a simulated enterprise inbox and shows **how it decides**: observe → understand → generate options → evaluate (priority + risk) → validate against deterministic policy → decide → execute simulated tools → learn from feedback.

**Everything is simulated.** No money moves, no real email is sent, no contract is signed, nothing is deleted. Tools only write rows to a local SQLite file.

## Stack
Next.js 14 + TypeScript + Tailwind + Recharts + lucide · FastAPI + Pydantic + SQLite · Gemini / Groq / deterministic mock behind one provider interface.

## Run locally
Requires Python 3.11+ and Node 18+.

```bash
# 1) Backend (terminal 1)
cd backend
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000

# 2) Frontend (terminal 2)
cd frontend
npm install
npm run dev            # or: npm run build && npm start
# open http://localhost:3000
```

It works with **no API key** (deterministic mock reasoning). For a live model: `cp .env.example backend/.env`, set `LLM_PROVIDER=gemini` (or `groq`) and the matching key. If the provider fails or returns invalid JSON, the app falls back to mock mode and says so in the activity timeline.

## Tests
```bash
cd backend && source .venv/bin/activate && python -m pytest -q     # 26 tests
cd frontend && npx tsc --noEmit && npm run build
```

## 3-minute demo script
1. **Scenarios** → *Run All Scenarios*: the outage escalates automatically, the payment waits, the reminder is handled automatically. Watch the right-hand activity panel.
2. **Approval Centre** → approve the ₹2,50,000 payment (executes a *simulated* payment). Try **Modify** with an amount above ₹10,00,000: refused even after approval.
3. **Decision Models** → pick EML-1003: the LLM proposed AUTO_EXECUTE and policy POL-FIN-001 overrode it.
4. **Smart Inbox** → open EML-1004: *Same email, two modes* shows Autonomous vs Human-controlled behaviour. Switch mode in the header (Reset demo first) and process again.
5. **Briefing** → *Generate Briefing* from real state. All **Dashboard** metrics are computed from the database.

## Architecture (backend/app)
| Module | Role |
|---|---|
| `engine/observation.py` | deterministic extraction (amounts, fields, dates, signals) |
| `llm/*` | provider interface; Pydantic-validated JSON; mock fallback |
| `engine/pipeline.py` | context validation (intent guard, score floors) → options → risk → policy → final decision |
| `engine/options.py` | candidate actions, expected-utility model, satisficing view |
| `engine/scoring.py`, `risk.py` | Priority = 0.35·Urgency + 0.30·Impact + 0.20·Time + 0.15·Customer (configurable, must sum to 1); separate 5-factor risk where the LLM may raise but never lower the deterministic floor |
| `engine/policy.py` | deterministic rules that override the LLM **and** the mode |
| `tools/*` | simulated tools; params re-validated and hard blocks re-checked at execution time |
| `agent/orchestrator.py` | runs the pipeline, logs activity, executes permitted steps, approvals (approve/reject/modify), feedback |
| `agent/services.py` | runs, scenarios, dashboard, briefing, model-explorer data |

Final decisions: `AUTO_EXECUTE · DRAFT_AND_APPROVE · ESCALATE · SCHEDULE · IGNORE`.

**Key policies:** payments, contract signing, deletion, personnel decisions, any external email/invitation, and any step with risk ≥ 6.5 always require approval in both modes. Steps that follow a gated step wait for it. Payments above ₹10,00,000 and protected record types are refused outright.

**Modes:** *Autonomous* runs permitted low-risk steps and escalates sensitive ones. *Human-controlled* holds every step for confirmation. Neither bypasses mandatory policy.

## What is real vs. educational
- **Implemented and used for decisions:** weighted scoring, risk model, expected utility, rule/policy engine, human-in-the-loop gating, tool-calling loop, persisted feedback.
- **Educational simulation:** the Markov Decision Process view. Rewards and Q-values are derived from each email's expected utility. **No reinforcement learning takes place.**
- **Feedback:** approvals, rejections and modifications adjust preference counters (small score nudges; after 2 rejections the agent asks first). **The LLM is not retrained.**
- Expected-utility probabilities are transparent heuristics, not learned estimates. The mock "LLM" is deterministic and deliberately over-eager on sensitive intents so policy overrides are visible.

## Limitations
- The live timeline polls every 1–2 s instead of using websockets.
- Single user, no authentication; intended for local demos.
- Live Gemini/Groq calls are covered by tests with a mocked HTTP transport but were **not** exercised against the real APIs (no keys available).
- Seed email timestamps are generated relative to first start; "Reset demo" re-seeds them.

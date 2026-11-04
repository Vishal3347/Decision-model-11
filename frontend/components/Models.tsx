"use client";
import { useState } from "react";
import { usePoll } from "@/lib/api";
import { Badge, Bar, ErrorBox, Loading, Section } from "./ui";

const TABS = [
  ["eu", "Expected Utility", "REAL"], ["sat", "Satisficing", "REAL"], ["tree", "Decision Tree", "REAL"], ["matrix", "Weighted Matrix", "REAL"],
  ["rules", "Rule-Based", "REAL"], ["mdp", "Markov (MDP)", "EDUCATIONAL"], ["hitl", "Human-in-the-Loop", "REAL"], ["loop", "LLM Agent Loop", "REAL"],
] as const;

const Tag = ({ k }: { k: string }) => <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold ${k === "REAL" ? "bg-emerald-500/15 text-emerald-600" : "bg-amber-500/15 text-amber-700"}`}>{k === "REAL" ? "IMPLEMENTED" : "EDUCATIONAL SIMULATION"}</span>;

export default function Models({ emailId, setEmailId, tick }: { emailId: string; setEmailId: (s: string) => void; tick: number }) {
  const [tab, setTab] = useState<string>("eu");
  const list = usePoll("/emails?sort=priority", 5000, tick);
  const { data: m, error, loading } = usePoll(`/models/${emailId}`, 3000, tick);
  const cur = TABS.find(t => t[0] === tab)!;
  return (
    <div className="space-y-4 fade">
      <div className="card flex flex-wrap items-center gap-3 p-3">
        <span className="text-sm font-semibold">Email</span>
        <select className="input max-w-md" value={emailId} onChange={e => setEmailId(e.target.value)}>{list.data?.emails.map((e: any) => <option key={e.id} value={e.id}>{e.id} · {e.subject.slice(0, 60)}</option>)}</select>
        {m && <span className="mut text-xs">{m.processed ? "Showing the stored decision for this processed email" : "Not processed yet — live preview from the same engine (nothing executed)"} · mode {m.mode.replace("_", " ")}</span>}
      </div>
      <div className="flex flex-wrap gap-1">{TABS.map(([k, l]) => <button key={k} onClick={() => setTab(k)} className={`btn ${tab === k ? "btn-pri" : ""}`}>{l}</button>)}</div>
      {loading && !m ? <Loading /> : error && !m ? <ErrorBox msg={error} /> : m && (
        <Section title={cur[1]} right={<Tag k={cur[2]} />}>
          {tab === "eu" && <div className="space-y-3"><p className="mut text-xs">{m.expected_utility.formula}. Probabilities and values are transparent heuristics, not learned estimates.</p>
            <table className="w-full text-sm"><thead className="mut text-left text-xs"><tr><th>#</th><th>Action</th><th>P(success)</th><th>Benefit</th><th>Loss</th><th>Effort</th><th>Pref</th><th>LLM</th><th>Expected utility</th></tr></thead>
              <tbody>{m.expected_utility.options.map((o: any) => <tr key={o.action} className={`border-t line ${o.action === m.expected_utility.selected ? "font-semibold bg-[var(--accsoft)]" : ""}`}><td>{o.rank}</td><td>{o.label}{o.action === m.expected_utility.selected && " ✓"}</td><td>{o.p_success}</td><td>{o.benefit}</td><td>{o.loss}</td><td>{o.effort}</td><td>{o.preference_adjustment}</td><td>{o.llm_bonus}</td><td>{o.expected_utility}</td></tr>)}</tbody></table></div>}
          {tab === "sat" && <div className="space-y-3"><p className="text-sm">Cheapest actions are examined first; the agent stops at the first one meeting: fit ≥ {m.satisficing.criteria.min_fit}, risk ≤ {m.satisficing.criteria.max_risk}, expected utility ≥ {m.satisficing.criteria.aspiration_eu}.</p>
            <ul className="space-y-1 text-sm">{m.satisficing.trace.map((t: any) => <li key={t.action} className={`flex items-center justify-between gap-2 rounded p-2 ${!t.evaluated ? "opacity-40" : ""} ${t.accepted ? "bg-emerald-500/15" : ""}`}><span>{t.label}</span><span className="mut text-xs">{!t.evaluated ? "not examined (already satisfied)" : t.accepted ? "ACCEPTED — good enough" : "rejected: " + t.reasons.join(", ")}</span></li>)}</ul>
            <p className="text-sm">Satisficer chose <b>{m.satisficing.chosen ?? "nothing acceptable"}</b> after examining {m.satisficing.options_examined}/{m.satisficing.options_total}; the optimiser (expected utility) chose <b>{m.satisficing.optimal}</b> — {m.satisficing.matches_optimal ? "they agree." : "they differ: speed versus optimality."} <span className="mut">(Production decisions use expected utility.)</span></p></div>}
          {tab === "tree" && <div className="grid gap-2 md:grid-cols-2">{m.decision_tree.map((n: any) => <div key={n.action} className={`rounded-lg border p-3 text-sm ${n.chosen ? "border-[var(--acc)] bg-[var(--accsoft)]" : "line"}`}>
            <div className="flex justify-between font-semibold"><span>{n.label}{n.chosen && " ✓"}</span><span>EV {n.expected_value}</span></div>
            {n.branches.map((b: any) => <div key={b.outcome} className="mt-1 flex justify-between pl-3 border-l-2 line text-xs"><span>{b.outcome} · p={b.p}</span><span>{b.value}</span></div>)}
            <div className="mt-1 flex gap-1"><Badge v={n.risk >= 6.5 ? "High" : n.risk >= 3.5 ? "Medium" : "Low"} label={`risk ${n.risk}`} />{n.needs_human && <Badge v="pending" label="needs human" />}</div></div>)}</div>}
          {tab === "matrix" && <div className="space-y-3"><table className="w-full text-sm"><thead className="mut text-left text-xs"><tr><th>Dimension</th><th>Score (1–10)</th><th>Weight</th><th>Contribution</th><th></th></tr></thead>
            <tbody>{["urgency", "business_impact", "time_sensitivity", "customer_importance"].map(k => <tr key={k} className="border-t line"><td>{k.replace("_", " ")}</td><td>{m.weighted_matrix[k]}</td><td>{m.weighted_matrix.weights[k]}</td><td>{m.weighted_matrix.contributions[k]}</td><td className="w-40"><Bar value={m.weighted_matrix.contributions[k]} max={3.5} /></td></tr>)}</tbody></table>
            <div className="text-lg font-semibold">Priority score {m.weighted_matrix.score} <Badge v={m.weighted_matrix.label} /></div>
            {m.record.context.validation_notes.length > 0 && <p className="mut text-xs">Validation: {m.record.context.validation_notes.join(" ")}</p>}
            <Weights /></div>}
          {tab === "rules" && <div className="space-y-3"><p className="text-sm">LLM proposed <Badge v={m.rule_based.llm_proposed} /> → final decision <Badge v={m.rule_based.final} />{m.rule_based.overridden ? " — policy overrode the model." : " — no override needed."}</p>
            {m.rule_based.triggered.map((c: any) => <div key={c.rule_id} className="rounded-lg border line p-2 text-sm"><div className="flex justify-between"><b>{c.rule_id} · {c.name}</b><Badge v={c.kind === "mandatory" || c.kind === "block" ? "failed" : "processed"} label={c.kind} /></div><div className="mut text-xs">{c.description}</div><div className="text-xs mt-1">→ {c.effect}{c.detail && `: ${c.detail}`}</div></div>)}
            <details><summary className="mut text-xs cursor-pointer">All {m.rule_based.all_rules.length} rules</summary><ul className="text-xs mt-1">{m.rule_based.all_rules.map((c: any) => <li key={c.rule_id}>{c.triggered ? "●" : "○"} {c.rule_id} {c.name}</li>)}</ul></details></div>}
          {tab === "mdp" && <div className="space-y-3"><p className="rounded-lg bg-amber-500/10 p-2 text-xs text-amber-700">{m.mdp.note}</p>
            <div className="flex flex-wrap items-center gap-2 text-sm">{m.mdp.trajectory.map((t: any, i: number) => <div key={i} className="flex items-center gap-2"><div className="rounded-lg border line p-2"><div className="font-semibold">{t.state}</div><div className="mut text-xs">action: {t.action}</div><div className="text-xs">reward {t.reward}</div></div><span>→</span>{i === m.mdp.trajectory.length - 1 && <div className="rounded-lg border-2 border-[var(--acc)] p-2 font-semibold">{t.next_state}</div>}</div>)}</div>
            <div className="text-xs font-semibold">Q-values in state ANALYZED (γ = {m.mdp.gamma}; derived from expected utility, not learned)</div>
            {m.mdp.q_values.map((q: any) => <div key={q.action} className="flex items-center gap-2 text-xs"><span className="w-36">{q.action}</span><div className="flex-1"><Bar value={Math.max(0, q.q)} max={Math.max(1, ...m.mdp.q_values.map((x: any) => x.q))} /></div><span>{q.q}</span></div>)}</div>}
          {tab === "hitl" && <div className="space-y-3"><p className="text-sm">Overall risk <b>{m.human_in_loop.overall_risk}</b> <Badge v={m.human_in_loop.risk_label} /> · human required: <b>{m.human_in_loop.requires_human ? "yes" : "no"}</b></p>
            <table className="w-full text-sm"><thead className="mut text-left text-xs"><tr><th>Step</th><th>Action class</th><th>Risk</th><th>Rules</th><th>Who acts</th></tr></thead>
              <tbody>{m.human_in_loop.steps.map((s: any) => <tr key={s.step_id} className="border-t line"><td>{s.title}</td><td>{s.action_class}</td><td>{s.risk}</td><td className="text-xs">{s.rules.join(", ")}</td><td><Badge v={s.decision === "Autonomous" ? "processed" : s.decision === "Blocked" ? "failed" : "pending"} label={s.decision} /></td></tr>)}</tbody></table>
            <div className="text-xs font-semibold">Routing questions</div>
            {m.human_in_loop.routing.map((r: any) => <div key={r.node_id} className="flex items-start gap-2 text-sm"><Badge v={r.answer ? "pending" : "processed"} label={r.answer ? "YES" : "NO"} /><div>{r.question}<div className="mut text-xs">{r.evidence} → {r.answer ? r.on_yes : r.on_no}</div></div></div>)}</div>}
          {tab === "loop" && <ol className="space-y-2">{m.agent_loop.map((l: any) => <li key={l.iteration} className="rounded-lg border line p-3 text-sm"><div className="font-semibold">Iteration {l.iteration}</div>
            <div className="mt-1 grid gap-1 text-xs md:grid-cols-5">{[["Observe", l.observe], ["Reason", l.reason], ["Select tool", l.tool], ["Execute", l.gate === "auto" ? "automatic" : l.gate === "approval" ? "held for approval" : "refused"], ["Result", l.result || "(not executed yet)"]].map(([a, b]) => <div key={a} className="rounded p-2" style={{ background: "var(--bg)" }}><div className="mut font-semibold">{a}</div>{b}</div>)}</div>
            <div className="mut mt-1 text-xs">Decide again: {l.decide_again}</div></li>)}{m.agent_loop.length === 0 && <li className="mut text-sm">No tool calls — nothing to do for this email.</li>}</ol>}
        </Section>)}
    </div>);
}

function Weights() {
  const { data, reload } = usePoll("/state", 60000);
  const [w, setW] = useState<any>(null); const [msg, setMsg] = useState("");
  const cur = w ?? data?.weights; if (!cur) return null;
  const sum = Object.values(cur).reduce((a: number, b: any) => a + Number(b), 0);
  const save = async () => { const { api } = await import("@/lib/api"); try { await api("/weights", { method: "PUT", body: cur }); setMsg("Saved — applies to the next decisions."); reload(); } catch (e: any) { setMsg(e.message); } };
  return <div className="rounded-lg border line p-3"><div className="text-xs font-semibold mb-2">Configurable weights (must sum to 1.0 — currently {sum.toFixed(2)})</div>
    <div className="grid grid-cols-4 gap-2">{Object.keys(cur).map(k => <label key={k} className="text-xs">{k.replace("_", " ")}<input className="input" type="number" step="0.05" min="0" max="1" value={cur[k]} onChange={e => setW({ ...cur, [k]: Number(e.target.value) })} /></label>)}</div>
    <div className="mt-2 flex items-center gap-2"><button className="btn" onClick={save}>Save weights</button><span className="mut text-xs">{msg}</span></div></div>;
}

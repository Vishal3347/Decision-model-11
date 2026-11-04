"use client";
import { useState } from "react";
import { Check, Pencil, X } from "lucide-react";
import { api, fmtDate, usePoll } from "@/lib/api";
import { Badge, Empty, ErrorBox, Loading, Section } from "./ui";

function Card({ a, bump }: { a: any; bump: () => void }) {
  const [editing, setEditing] = useState(false); const [steps, setSteps] = useState<any[]>(a.proposed_steps.map((s: any) => ({ ...s, text: JSON.stringify(s.params, null, 2) })));
  const [fb, setFb] = useState(""); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false); const [res, setRes] = useState<any>(null);
  const act = async (kind: string) => {
    setBusy(true); setErr(null);
    try {
      let body: any = { feedback: fb || undefined };
      if (kind === "modify") body = { feedback: fb || undefined, steps: steps.map(s => ({ step_id: s.step_id, tool: s.tool, params: JSON.parse(s.text) })) };
      setRes(await api(`/approvals/${a.id}/${kind}`, { method: "POST", body })); setEditing(false); bump();
    } catch (e: any) { setErr(e instanceof SyntaxError ? "Parameters must be valid JSON" : e.message); } finally { setBusy(false); }
  };
  const pending = a.status === "pending";
  return (
    <Section title={a.subject} right={<div className="flex gap-1"><Badge v={a.status} /><Badge v={a.priority_label} label={`Priority ${a.priority_score}`} /><Badge v={a.risk_label} label={`Risk ${a.risk_score}`} /></div>}>
      <div className="mut text-xs mb-2">From {a.sender_name} · {a.email_id} · requested {fmtDate(a.created_at)} · mode {a.mode.replace("_", " ")}</div>
      <div className="grid gap-3 md:grid-cols-2">
        <div><div className="text-xs font-semibold mb-1">Original email</div><pre className="whitespace-pre-wrap font-sans text-xs max-h-40 overflow-auto rounded-lg p-2" style={{ background: "var(--bg)" }}>{a.body}</pre></div>
        <div className="space-y-2 text-sm"><div><div className="text-xs font-semibold">Decision summary</div>{a.summary}</div>
          <div><div className="text-xs font-semibold">Why approval is needed</div>{a.reason}{a.rule_ids.length > 0 && <div className="mt-1 flex flex-wrap gap-1">{a.rule_ids.map((r: string) => <Badge key={r} v="new" label={r} />)}</div>}</div></div>
      </div>
      <div className="mt-3 text-xs font-semibold">Proposed action{a.proposed_steps.length > 1 ? "s" : ""} (simulated)</div>
      <ul className="mt-1 space-y-2">{(editing ? steps : a.proposed_steps).map((s: any, i: number) => (
        <li key={s.step_id} className="rounded-lg border line p-2 text-sm"><div className="flex justify-between"><b>{s.title}</b><span className="mut text-xs">{s.tool} · risk {s.risk_score}</span></div>
          {editing ? <textarea className="input mt-1 font-mono text-xs" rows={6} value={steps[i].text} onChange={e => setSteps(steps.map((x, j) => j === i ? { ...x, text: e.target.value } : x))} />
            : <pre className="mt-1 whitespace-pre-wrap text-xs mut">{Object.entries(s.params).filter(([, v]) => v != null && v !== "").map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("\n")}</pre>}
        </li>))}</ul>
      {pending ? <div className="mt-3 space-y-2">
        <input className="input" placeholder="Optional feedback (recorded as a preference signal, does not retrain the model)" value={fb} onChange={e => setFb(e.target.value)} />
        {err && <div className="text-sm text-red-500">{err}</div>}
        <div className="flex gap-2"><button className="btn btn-pri" disabled={busy} onClick={() => act(editing ? "modify" : "approve")}><Check className="h-4 w-4" />{editing ? "Apply edits & execute" : "Approve"}</button>
          <button className="btn" disabled={busy} onClick={() => setEditing(!editing)}><Pencil className="h-4 w-4" />{editing ? "Cancel edit" : "Modify"}</button>
          <button className="btn btn-danger" disabled={busy} onClick={() => act("reject")}><X className="h-4 w-4" />Reject</button></div>
        <div className="mut text-xs">Edited actions are re-validated by the backend; hard limits (e.g. payments above ₹10,00,000) are refused even after approval.</div></div>
        : <div className="mt-3 text-sm mut">Resolved {fmtDate(a.resolved_at)}{a.feedback ? ` · “${a.feedback}”` : ""}</div>}
      {res?.results && <ul className="mt-2 text-sm space-y-1">{res.results.map((r: any) => <li key={r.step_id}><Badge v={r.status === "executed" ? "processed" : "failed"} label={r.status} /> {r.message}</li>)}</ul>}
    </Section>);
}

export default function Approvals({ tick, bump }: { tick: number; bump: () => void }) {
  const { data, error, loading } = usePoll("/approvals", 2000, tick);
  const prefs = usePoll("/preferences", 4000, tick);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox msg={error} />;
  const all = data.approvals; const pend = all.filter((a: any) => a.status === "pending"); const done = all.filter((a: any) => a.status !== "pending");
  return (
    <div className="space-y-4 fade">
      <h2 className="text-lg font-semibold">Pending approvals ({pend.length})</h2>
      {pend.length === 0 ? <div className="card"><Empty title="No pending approvals" hint="Process the inbox or run a scenario to generate requests." /></div> : pend.map((a: any) => <Card key={a.id} a={a} bump={bump} />)}
      {prefs.data && prefs.data.preferences.length > 0 && <Section title="Learned preferences (feedback counters)">
        <p className="mut text-xs mb-2">{prefs.data.note}</p>
        <table className="w-full text-sm"><thead className="mut text-left text-xs"><tr><th>Email type</th><th>Action</th><th>Approved</th><th>Rejected</th><th>Modified</th><th>Score adj.</th><th>Ask first</th></tr></thead>
          <tbody>{prefs.data.preferences.map((p: any) => <tr key={p.intent + p.action} className="border-t line"><td>{p.intent}</td><td>{p.action}</td><td>{p.approvals}</td><td>{p.rejections}</td><td>{p.modifications}</td><td>{p.adjustment}</td><td>{p.ask_first ? "yes" : "no"}</td></tr>)}</tbody></table></Section>}
      {done.length > 0 && <><h2 className="text-lg font-semibold">History</h2>{done.map((a: any) => <Card key={a.id} a={a} bump={bump} />)}</>}
    </div>);
}

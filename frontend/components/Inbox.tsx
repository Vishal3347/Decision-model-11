"use client";
import { useState } from "react";
import { Search, Play } from "lucide-react";
import { api, fmtDate, usePoll } from "@/lib/api";
import { Badge, Empty, ErrorBox, Loading, Section } from "./ui";

export default function Inbox({ tick, bump, onModels }: { tick: number; bump: () => void; onModels: (id: string) => void }) {
  const [q, setQ] = useState(""); const [category, setCategory] = useState(""); const [priority, setPriority] = useState(""); const [status, setStatus] = useState(""); const [sort, setSort] = useState("newest");
  const [sel, setSel] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const qs = new URLSearchParams({ sort, ...(q && { q }), ...(category && { category }), ...(priority && { priority }), ...(status && { status }) }).toString();
  const { data, error, loading } = usePoll(`/emails?${qs}`, 2000, tick);
  const detail = usePoll(sel ? `/emails/${sel}` : null, 2000, tick);
  const cmp = usePoll(sel ? `/emails/${sel}/compare` : null, 5000, tick);
  const run = async (fn: () => Promise<any>) => { setBusy(true); setErr(null); try { await fn(); bump(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); } };
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox msg={error} />;
  const emails = data.emails;
  const d = detail.data;
  return (
    <div className="grid gap-4 lg:grid-cols-5 fade">
      <div className="lg:col-span-2 space-y-3">
        <div className="card p-3 space-y-2">
          <div className="flex gap-2">
            <div className="relative flex-1"><Search className="absolute left-2 top-2.5 h-4 w-4 mut" /><input className="input pl-8" placeholder="Search emails…" value={q} onChange={e => setQ(e.target.value)} /></div>
            <button className="btn btn-pri" disabled={busy} onClick={() => run(() => api("/process-inbox", { method: "POST", body: {} }))}><Play className="h-4 w-4" />Process Inbox</button>
          </div>
          <div className="grid grid-cols-4 gap-2">
            <select className="input" value={category} onChange={e => setCategory(e.target.value)}><option value="">Category</option>{data.categories.map((c: string) => <option key={c}>{c}</option>)}</select>
            <select className="input" value={priority} onChange={e => setPriority(e.target.value)}><option value="">Priority</option>{["Critical", "High", "Medium", "Low"].map(c => <option key={c}>{c}</option>)}</select>
            <select className="input" value={status} onChange={e => setStatus(e.target.value)}><option value="">Status</option>{["new", "processing", "processed", "awaiting_approval", "failed", "archived"].map(c => <option key={c} value={c}>{c.replace("_", " ")}</option>)}</select>
            <select className="input" value={sort} onChange={e => setSort(e.target.value)}><option value="newest">Newest</option><option value="oldest">Oldest</option><option value="priority">Priority</option><option value="sender">Sender</option></select>
          </div>
          {err && <div className="text-sm text-red-500">{err}</div>}
        </div>
        <div className="card divide-y line max-h-[70vh] overflow-auto">
          {emails.length === 0 ? <Empty title="No emails match" hint="Clear the filters." /> : emails.map((e: any) => (
            <button key={e.id} onClick={() => setSel(e.id)} className={`block w-full p-3 text-left hover:bg-[var(--accsoft)] ${sel === e.id ? "bg-[var(--accsoft)]" : ""}`}>
              <div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-semibold">{e.sender_name}</span><span className="mut text-xs shrink-0">{fmtDate(e.timestamp)}</span></div>
              <div className="truncate text-sm">{e.subject}</div>
              <div className="mt-1 flex flex-wrap items-center gap-1"><Badge v={e.priority} /><Badge v={e.status} />{e.selected_action && <Badge v={e.selected_action} />}<span className="mut text-xs">{e.category} · {e.id}</span></div>
            </button>))}
        </div>
      </div>
      <div className="lg:col-span-3 space-y-3">
        {!sel ? <div className="card"><Empty title="Select an email" hint="See its content, the agent's decision and how each mode would behave." /></div> : !d ? <Loading /> : (
          <>
            <Section title={d.email.subject} right={<div className="flex gap-2">
              {d.email.status === "new" || d.email.status === "failed" ? <button className="btn btn-pri" disabled={busy} onClick={() => run(() => api(`/emails/${sel}/process`, { method: "POST", body: {} }))}>Process this email</button> : null}
              <button className="btn" onClick={() => onModels(sel)}>Explore models</button></div>}>
              <div className="mut text-xs mb-2">{d.email.sender_name} &lt;{d.email.sender_email}&gt; · {fmtDate(d.email.timestamp)} · {d.email.category} · {d.email.id}</div>
              <pre className="whitespace-pre-wrap font-sans text-sm">{d.email.body}</pre>
            </Section>
            {d.decision ? (
              <Section title="Agent decision" right={<div className="flex gap-1"><Badge v={d.decision.final_decision} /><Badge v={d.email.status} /></div>}>
                <p className="text-sm mb-2">{d.decision.explanation}</p>
                <div className="grid grid-cols-3 gap-2 text-sm"><div><div className="mut text-xs">Priority</div><b>{d.decision.priority.score}</b> <Badge v={d.decision.priority.label} /></div><div><div className="mut text-xs">Risk</div><b>{d.decision.risk.score}</b> <Badge v={d.decision.risk.label} /></div><div><div className="mut text-xs">Decision time</div><b>{d.decision.duration_ms} ms</b></div></div>
                <ul className="mt-3 space-y-1 text-sm">{d.decision.plan.map((s: any) => <li key={s.step_id} className="flex items-center justify-between gap-2"><span>{s.title}</span><span className="flex gap-1">{s.blocked_reason ? <Badge v="failed" label="refused" /> : s.requires_approval ? <Badge v="pending" label="needs approval" /> : <Badge v="processed" label="automatic" />}<Badge v={s.status === "planned" ? "new" : s.status} label={s.status.replace("_", " ")} /></span></li>)}</ul>
                {d.decision.override_reasons.length > 0 && <div className="mt-3 rounded-lg p-2 text-xs" style={{ background: "var(--accsoft)" }}><b>Policy / validation:</b> {d.decision.override_reasons.join(" · ")}</div>}
              </Section>) : <div className="card p-4 text-sm mut">Not processed yet. Press “Process this email” or “Process Inbox”.</div>}
            {cmp.data && <Section title="Same email, two modes">
              <div className="grid gap-3 md:grid-cols-2">{Object.entries(cmp.data).map(([mode, v]: any) => <div key={mode}><div className="mb-1 text-xs font-semibold">{mode.replace("_", " ")} <Badge v={v.final_decision} /></div>
                <ul className="space-y-1 text-sm">{v.steps.length === 0 ? <li className="mut">No steps</li> : v.steps.map((s: any, i: number) => <li key={i} className="flex justify-between gap-2"><span>{s.title}</span><Badge v={s.behaviour === "Runs automatically" ? "processed" : s.behaviour === "Refused" ? "failed" : "pending"} label={s.behaviour} /></li>)}</ul></div>)}</div></Section>}
          </>)}
      </div>
    </div>
  );
}

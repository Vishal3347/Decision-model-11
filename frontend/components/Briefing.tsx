"use client";
import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { api, fmtDate } from "@/lib/api";
import { Badge, Empty, Section } from "./ui";

export default function Briefing({ bump }: { bump: () => void }) {
  const [b, setB] = useState<any>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api("/briefing/latest").then(setB).catch(() => {}); }, []);
  const gen = async () => { setBusy(true); setErr(null); try { setB(await api("/briefing/generate", { method: "POST" })); bump(); } catch (e: any) { setErr(e.message); } finally { setBusy(false); } };
  const List = ({ title, items, render }: any) => <Section title={`${title} (${items.length})`}>{items.length === 0 ? <div className="mut text-sm">None</div> : <ul className="space-y-1.5 text-sm">{items.map(render)}</ul>}</Section>;
  return (
    <div className="space-y-4 fade">
      <div className="flex items-center justify-between"><h2 className="text-lg font-semibold">Daily Executive Briefing</h2><button className="btn btn-pri" disabled={busy} onClick={gen}><FileText className="h-4 w-4" />{busy ? "Generating…" : "Generate Briefing"}</button></div>
      {err && <div className="text-sm text-red-500">{err}</div>}
      {!b ? <div className="card"><Empty title="No briefing yet" hint="Generate one from the current inbox, tasks and approvals." /></div> : (<>
        <div className="card p-4"><div className="mut text-xs">Generated {fmtDate(b.generated_at)} · narrative by {b.narrative_provider}</div><div className="mt-1 text-xl font-semibold">{b.headline}</div><p className="mt-1 text-sm">{b.summary}</p></div>
        <div className="grid gap-4 md:grid-cols-2">
          <List title="Critical issues" items={b.critical_issues} render={(c: any) => <li key={c.id} className="flex justify-between gap-2"><span>{c.subject}</span><Badge v={c.execution_status === "AWAITING_APPROVAL" ? "pending" : "processed"} label={c.execution_status.replace("_", " ").toLowerCase()} /></li>} />
          <List title="Pending approvals" items={b.pending_approvals} render={(c: any) => <li key={c.id}><b>{c.subject}</b><div className="mut text-xs">{c.reason}</div></li>} />
          <List title="Completed actions" items={b.completed_actions} render={(c: any, i: number) => <li key={i}>{c.message} <span className="mut text-xs">({c.actor === "agent" ? "agent" : "after approval"})</span></li>} />
          <List title="Important customer communications" items={b.customer_communications} render={(c: any) => <li key={c.id} className="flex justify-between gap-2"><span>{c.sender_name}: {c.subject}</span><Badge v={c.status} /></li>} />
          <List title="Upcoming meetings" items={b.upcoming_meetings} render={(c: any) => <li key={c.id}>{fmtDate(c.start_at)} — {c.title}{c.created_by === "agent" && <span className="mut text-xs"> (agent)</span>}</li>} />
          <List title="Follow-ups" items={b.follow_ups} render={(c: any) => <li key={c.id}>{c.title} <span className="mut text-xs">due {fmtDate(c.due_at)}</span></li>} />
          <List title="Tasks requiring attention" items={b.tasks_attention} render={(c: any) => <li key={c.id} className="flex justify-between gap-2"><span>{c.ticket_ref ? `[${c.ticket_ref}] ` : ""}{c.title}</span><Badge v={c.priority} /></li>} />
        </div></>)}
    </div>);
}

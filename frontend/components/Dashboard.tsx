"use client";
import { Bar as RBar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis, PieChart, Pie } from "recharts";
import { usePoll, fmtTime } from "@/lib/api";
import { Badge, Empty, ErrorBox, Loading, Section } from "./ui";

const PCOL: Record<string, string> = { Critical: "#dc2626", High: "#f97316", Medium: "#eab308", Low: "#22c55e" };

export default function Dashboard({ tick, go }: { tick: number; go: (t: string) => void }) {
  const { data, error, loading } = usePoll("/dashboard", 2000, tick);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox msg={error} />;
  const m = data.metrics;
  const kpis = [
    ["Emails processed", `${m.emails_processed} / ${m.total_emails}`], ["Autonomous actions", m.autonomous_actions], ["Pending approvals", m.pending_approvals],
    ["Critical alerts", m.critical_alerts], ["Follow-up tasks", m.tasks_awaiting_followup],
    ["Avg decision time", m.avg_decision_ms == null ? "—" : `${m.avg_decision_ms} ms`], ["Automation success", m.automation_success_rate == null ? "—" : `${m.automation_success_rate}%`],
  ];
  const tasks = [{ name: "Open", value: data.task_completion.open, c: "#f97316" }, { name: "Completed", value: data.task_completion.completed, c: "#22c55e" }];
  const hasPrio = data.priority_distribution.some((p: any) => p.count);
  return (
    <div className="space-y-4 fade">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-7">
        {kpis.map(([k, v]) => <div key={k as string} className="card p-3"><div className="mut text-xs">{k}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{v as any}</div></div>)}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="Priority distribution">
          {!hasPrio ? <Empty title="No processed emails yet" hint="Process the inbox to see the distribution." /> :
            <ResponsiveContainer width="100%" height={200}><BarChart data={data.priority_distribution}><CartesianGrid vertical={false} strokeOpacity={.2} /><XAxis dataKey="label" fontSize={12} /><YAxis allowDecimals={false} fontSize={12} width={24} /><Tooltip />
              <RBar dataKey="count" radius={[4, 4, 0, 0]}>{data.priority_distribution.map((p: any) => <Cell key={p.label} fill={PCOL[p.label]} />)}</RBar></BarChart></ResponsiveContainer>}
        </Section>
        <Section title="Task completion">
          {tasks[0].value + tasks[1].value === 0 ? <Empty title="No tasks yet" /> :
            <ResponsiveContainer width="100%" height={200}><PieChart><Pie data={tasks} dataKey="value" nameKey="name" innerRadius={50} outerRadius={80} label={(e: any) => `${e.name} ${e.value}`}>{tasks.map(t => <Cell key={t.name} fill={t.c} />)}</Pie><Tooltip /></PieChart></ResponsiveContainer>}
        </Section>
        <Section title="Decisions made">
          {data.decision_distribution.length === 0 ? <Empty title="No decisions yet" /> :
            <div className="space-y-2">{data.decision_distribution.map((d: any) => <div key={d.label} className="flex items-center justify-between text-sm"><Badge v={d.label} /><span className="font-semibold tabular-nums">{d.count}</span></div>)}</div>}
        </Section>
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Pending decisions" right={<button className="btn" onClick={() => go("approvals")}>Open Approval Centre</button>}>
          {data.pending_decisions.length === 0 ? <Empty title="Nothing waiting for you" /> :
            <ul className="divide-y line">{data.pending_decisions.map((p: any) => <li key={p.id} className="flex items-center justify-between gap-3 py-2 text-sm">
              <div className="min-w-0"><div className="truncate font-medium">{p.subject}</div><div className="mut truncate text-xs">{p.reason}</div></div>
              <div className="flex shrink-0 gap-1"><Badge v={p.priority_label} label={`P ${p.priority_score}`} /><Badge v={p.risk_label} label={`Risk ${p.risk_score}`} /></div></li>)}</ul>}
        </Section>
        <Section title="Recent agent activity">
          {data.recent_activity.length === 0 ? <Empty title="No activity yet" /> :
            <ul className="space-y-1.5 text-sm">{data.recent_activity.map((a: any) => <li key={a.id} className="flex gap-2"><span className="mut tabular-nums text-xs pt-0.5">{fmtTime(a.ts)}</span><span className={a.level === "error" ? "text-red-500" : a.level === "warn" ? "text-amber-600" : ""}>{a.message}</span></li>)}</ul>}
        </Section>
      </div>
    </div>
  );
}

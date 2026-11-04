"use client";
import { useState } from "react";
import { CheckCircle2, Circle, Play } from "lucide-react";
import { api, usePoll } from "@/lib/api";
import { Badge, ErrorBox, Loading, Section } from "./ui";

export default function Scenarios({ tick, bump, go }: { tick: number; bump: () => void; go: (t: string) => void }) {
  const { data, error, loading } = usePoll("/scenarios", 1500, tick);
  const [err, setErr] = useState<string | null>(null);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorBox msg={error} />;
  const running = data.run?.status === "running";
  const start = async (key: string) => { setErr(null); try { await api(key === "all" ? "/scenarios/run-all" : `/scenarios/${key}/run`, { method: "POST", body: {} }); bump(); } catch (e: any) { setErr(e.message); } };
  return (
    <div className="space-y-4 fade">
      <div className="flex items-center justify-between"><div><h2 className="text-lg font-semibold">Demo scenarios</h2><p className="mut text-sm">Each run resets the demo data to a clean inbox, so scenarios are repeatable and isolated.</p></div>
        <button className="btn btn-pri" disabled={running} onClick={() => start("all")}><Play className="h-4 w-4" />Run All Scenarios</button></div>
      {err && <div className="text-sm text-red-500">{err}</div>}
      <div className="grid gap-4 lg:grid-cols-3">{data.scenarios.map((s: any) => (
        <Section key={s.key} title={s.title} right={s.final_decision ? <Badge v={s.final_decision} /> : undefined}>
          <p className="text-sm mb-3">{s.blurb}</p>
          <ul className="space-y-1.5 text-sm mb-3">{(s.checks.length ? s.checks : s.expected.map((e: string) => ({ label: e, passed: null }))).map((c: any) => <li key={c.label} className="flex items-center gap-2">{c.passed ? <CheckCircle2 className="h-4 w-4 text-emerald-500" /> : <Circle className="h-4 w-4 mut" />}{c.label}</li>)}</ul>
          <div className="flex gap-2"><button className="btn" disabled={running} onClick={() => start(s.key)}><Play className="h-4 w-4" />Run</button>
            {s.key === "financial-approval" && s.execution_status === "AWAITING_APPROVAL" && <button className="btn btn-pri" onClick={() => go("approvals")}>Review approval</button>}</div>
        </Section>))}</div>
      {running && <div className="card p-3 text-sm">Running… {data.run.completed}/{data.run.total} · stage: {data.run.current_stage ?? "—"}</div>}
    </div>);
}

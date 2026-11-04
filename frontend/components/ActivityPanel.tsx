"use client";
import { Activity } from "lucide-react";
import { fmtTime, usePoll } from "@/lib/api";

const STAGES = ["Observe", "Understand", "Generate options", "Evaluate", "Validate policy", "Decide", "Execute"];
export default function ActivityPanel({ tick }: { tick: number }) {
  const { data } = usePoll("/activity?limit=40", 1000, tick);
  const run = data?.run; const running = run?.status === "running"; const idx = STAGES.indexOf(run?.current_stage);
  return (
    <aside className="card flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b line p-3 text-sm font-semibold"><Activity className="h-4 w-4" />Agent activity{running && <span className="ml-auto flex items-center gap-1 text-xs text-emerald-500"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />live</span>}</div>
      <div className="border-b line p-3">
        <div className="mut mb-1 text-xs">{running ? `Processing ${run.completed + 1}/${run.total} · ${run.current_email_id ?? ""}` : run ? `Last run ${run.status} (${run.completed}/${run.total})` : "Idle"}</div>
        <div className="flex gap-1">{STAGES.map((s, i) => <div key={s} title={s} className="h-1.5 flex-1 rounded-full" style={{ background: running && i <= idx ? "var(--acc)" : !running && run ? "var(--acc)" : "var(--line)", opacity: running && i === idx ? 1 : .75 }} />)}</div>
        {running && <div className="mt-1 text-xs font-semibold">{run.current_stage}</div>}
      </div>
      <ul className="flex-1 space-y-2 overflow-auto p-3 text-xs">
        {!data || data.events.length === 0 ? <li className="mut">No activity yet. Process the inbox to watch the agent work.</li> :
          [...data.events].reverse().map((e: any) => <li key={e.id} className="fade flex gap-2"><span className="mut tabular-nums">{fmtTime(e.ts)}</span><span className={e.level === "error" ? "text-red-500" : e.level === "warn" ? "text-amber-600" : ""}>{e.message}</span></li>)}
      </ul>
    </aside>);
}

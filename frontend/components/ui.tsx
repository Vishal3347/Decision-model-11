"use client";
import { Loader2, AlertTriangle, Inbox } from "lucide-react";

const TONES: Record<string, string> = {
  Critical: "bg-red-500/15 text-red-600 dark:text-red-400", High: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
  Medium: "bg-amber-500/15 text-amber-700 dark:text-amber-400", Low: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  AUTO_EXECUTE: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400", DRAFT_AND_APPROVE: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
  ESCALATE: "bg-red-500/15 text-red-600 dark:text-red-400", SCHEDULE: "bg-sky-500/15 text-sky-600 dark:text-sky-400", IGNORE: "bg-slate-500/15 text-slate-500",
  new: "bg-slate-500/15 text-slate-500", processing: "bg-indigo-500/15 text-indigo-500", processed: "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
  awaiting_approval: "bg-amber-500/15 text-amber-700 dark:text-amber-400", failed: "bg-red-500/15 text-red-600", archived: "bg-slate-500/15 text-slate-500",
  rejected: "bg-red-500/15 text-red-600", approved: "bg-emerald-500/15 text-emerald-700", modified: "bg-sky-500/15 text-sky-600", pending: "bg-amber-500/15 text-amber-700",
};
export function Badge({ v, label }: { v: string; label?: string }) {
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${TONES[v] ?? "bg-slate-500/15 text-slate-500"}`}>{(label ?? v).replace(/_/g, " ")}</span>;
}
export function Loading({ text = "Loading…" }: { text?: string }) {
  return <div className="flex items-center gap-2 p-6 mut text-sm"><Loader2 className="h-4 w-4 animate-spin" />{text}</div>;
}
export function ErrorBox({ msg }: { msg: string }) {
  return <div className="m-4 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-600 dark:text-red-400"><AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />{msg}</div>;
}
export function Empty({ title, hint }: { title: string; hint?: string }) {
  return <div className="flex flex-col items-center gap-1 p-10 text-center"><Inbox className="h-8 w-8 mut" /><div className="font-semibold">{title}</div>{hint && <div className="mut text-sm">{hint}</div>}</div>;
}
export function Section({ title, children, right }: { title: string; children: React.ReactNode; right?: React.ReactNode }) {
  return <div className="card p-4"><div className="mb-3 flex items-center justify-between"><h3 className="text-sm font-semibold">{title}</h3>{right}</div>{children}</div>;
}
export function Bar({ value, max = 10, color = "var(--acc)" }: { value: number; max?: number; color?: string }) {
  return <div className="h-2 w-full rounded-full" style={{ background: "var(--line)" }}><div className="h-2 rounded-full" style={{ width: `${Math.max(2, Math.min(100, (value / max) * 100))}%`, background: color }} /></div>;
}

"use client";
import { useState } from "react";
import { Brain, ClipboardCheck, FileText, Gauge, Inbox as InboxIcon, Layers, PlayCircle, RotateCcw } from "lucide-react";
import { api, usePoll } from "@/lib/api";
import ActivityPanel from "@/components/ActivityPanel";
import Approvals from "@/components/Approvals";
import Briefing from "@/components/Briefing";
import Dashboard from "@/components/Dashboard";
import Inbox from "@/components/Inbox";
import Models from "@/components/Models";
import Scenarios from "@/components/Scenarios";

const NAV = [["dashboard", "Dashboard", Gauge], ["inbox", "Smart Inbox", InboxIcon], ["models", "Decision Models", Brain], ["approvals", "Approval Centre", ClipboardCheck], ["briefing", "Briefing", FileText], ["scenarios", "Scenarios", PlayCircle]] as const;

export default function Page() {
  const [tab, setTab] = useState("dashboard"); const [tick, setTick] = useState(0); const [modelEmail, setModelEmail] = useState("EML-1003"); const [err, setErr] = useState<string | null>(null);
  const bump = () => setTick(t => t + 1);
  const { data: st } = usePoll("/state", 2000, tick);
  const setMode = async (mode: string) => { setErr(null); try { await api("/mode", { method: "PUT", body: { mode } }); bump(); } catch (e: any) { setErr(e.message); } };
  const reset = async () => { if (!confirm("Reset all demo data to the initial inbox?")) return; setErr(null); try { await api("/reset", { method: "POST" }); bump(); } catch (e: any) { setErr(e.message); } };
  const mode = st?.mode;
  return (
    <div className="mx-auto flex min-h-screen max-w-[1600px] flex-col gap-4 p-4">
      <header className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2"><Layers className="h-6 w-6" style={{ color: "var(--acc)" }} /><div><h1 className="text-lg font-semibold leading-tight">Decision Intelligence Simulator</h1><div className="mut text-xs">Executive assistant agent · all integrations simulated</div></div></div>
        <nav className="flex flex-wrap gap-1 md:ml-6">{NAV.map(([k, l, I]) => <button key={k} onClick={() => setTab(k)} className={`btn ${tab === k ? "btn-pri" : ""}`}><I className="h-4 w-4" />{l}{k === "approvals" && st?.pending_approvals ? <span className="rounded-full bg-red-500 px-1.5 text-[10px] text-white">{st.pending_approvals}</span> : null}</button>)}</nav>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {st && <span className="mut text-xs" title={st.llm.notice ?? ""}>LLM: {st.llm.live ? `${st.llm.provider} (${st.llm.model})` : "deterministic mock"}</span>}
          <div className="flex overflow-hidden rounded-lg border line">{["AUTONOMOUS", "HUMAN_CONTROLLED"].map(m => <button key={m} onClick={() => setMode(m)} className={`px-3 py-1.5 text-xs font-semibold ${mode === m ? "bg-[var(--acc)] text-white" : ""}`}>{m === "AUTONOMOUS" ? "Autonomous" : "Human-controlled"}</button>)}</div>
          <button className="btn" onClick={reset}><RotateCcw className="h-4 w-4" />Reset demo</button></div>
      </header>
      {err && <div className="text-sm text-red-500">{err}</div>}
      <div className="grid flex-1 gap-4 xl:grid-cols-[1fr_340px]">
        <main className="min-w-0">
          {tab === "dashboard" && <Dashboard tick={tick} go={setTab} />}
          {tab === "inbox" && <Inbox tick={tick} bump={bump} onModels={id => { setModelEmail(id); setTab("models"); }} />}
          {tab === "models" && <Models emailId={modelEmail} setEmailId={setModelEmail} tick={tick} />}
          {tab === "approvals" && <Approvals tick={tick} bump={bump} />}
          {tab === "briefing" && <Briefing bump={bump} />}
          {tab === "scenarios" && <Scenarios tick={tick} bump={bump} go={setTab} />}
        </main>
        <div className="xl:sticky xl:top-4 xl:h-[calc(100vh-2rem)] h-96"><ActivityPanel tick={tick} /></div>
      </div>
    </div>);
}

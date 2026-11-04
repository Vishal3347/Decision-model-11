"use client";
import { useCallback, useEffect, useRef, useState } from "react";

export async function api<T = any>(path: string, opts?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: opts?.method ?? "GET",
    headers: opts?.body ? { "Content-Type": "application/json" } : undefined,
    body: opts?.body ? JSON.stringify(opts.body) : undefined,
    cache: "no-store",
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error(typeof data?.detail === "string" ? data.detail : `Request failed (${res.status})`);
  return data as T;
}

/** Poll an endpoint. `tick` changes force a refetch (e.g. after an action). */
export function usePoll<T = any>(path: string | null, ms = 2000, tick = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const alive = useRef(true);
  const load = useCallback(async () => {
    if (!path) return;
    try { const d = await api<T>(path); if (alive.current) { setData(d); setError(null); } }
    catch (e: any) { if (alive.current) setError(e.message); }
    finally { if (alive.current) setLoading(false); }
  }, [path]);
  useEffect(() => {
    alive.current = true; load();
    const t = setInterval(load, ms);
    return () => { alive.current = false; clearInterval(t); };
  }, [load, ms, tick]);
  return { data, error, loading, reload: load };
}

export const fmtTime = (iso?: string) => (iso ? new Date(iso).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "");
export const fmtDate = (iso?: string) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }) : "");
export const inr = (n: number) => "₹" + Number(n).toLocaleString("en-IN");

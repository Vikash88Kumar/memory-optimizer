import { Archive, CheckCircle2, Eye, GitMerge, Hourglass, PencilLine, PlusCircle, Replace, ShieldAlert, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Empty, ErrorBanner, Loading } from "../components/Feedback";
import { day, typeLabel } from "../lib/format";
import { api } from "../services/api";
import type { MemoryEvent } from "../types";

const ACTIONS: Record<string, { label: string; icon: typeof PlusCircle; color: string }> = {
  created: { label: "Memory created", icon: PlusCircle, color: "#3C7A55" },
  pending_confirmation: { label: "Needs confirmation", icon: Eye, color: "#8A6D00" },
  updated: { label: "Memory updated", icon: PencilLine, color: "#2F6FDE" },
  merged: { label: "Memory merged", icon: GitMerge, color: "#2F6FDE" },
  superseded: { label: "Memory replaced", icon: Replace, color: "#5B6675" },
  expired: { label: "Memory expired", icon: Hourglass, color: "#5B6675" },
  deleted: { label: "Memory forgotten", icon: Trash2, color: "#C2412D" },
  retrieved: { label: "Memories retrieved", icon: Eye, color: "#1B2430" },
  confirmed: { label: "Memory confirmed", icon: CheckCircle2, color: "#3C7A55" },
  rejected: { label: "Memory rejected", icon: XCircle, color: "#C2412D" },
  blocked: { label: "Not stored", icon: ShieldAlert, color: "#C2412D" },
  episode_closed: { label: "Episode summarised", icon: Archive, color: "#5B6675" },
  extraction_failed: { label: "Extraction failed", icon: ShieldAlert, color: "#C2412D" },
};

export function groupByDay(events: MemoryEvent[]): [string, MemoryEvent[]][] {
  const groups = new Map<string, MemoryEvent[]>();
  for (const e of events) {
    const k = day(e.created_at);
    groups.set(k, [...(groups.get(k) ?? []), e]);
  }
  return [...groups.entries()];
}

export function ActivityTimeline({ events }: { events: MemoryEvent[] }) {
  return (
    <div className="space-y-6">
      {groupByDay(events).map(([label, items]) => (
        <section key={label}>
          <h2 className="mb-2 text-base">{label}</h2>
          <ol className="space-y-3 border-l border-rule pl-5">
            {items.map((e) => {
              const meta = ACTIONS[e.action] ?? { label: e.action, icon: Eye, color: "#5B6675" };
              const Icon = meta.icon;
              return (
                <li key={e.id} className="relative">
                  <span className="absolute -left-[29px] top-0.5 rounded-full bg-paper p-0.5" style={{ color: meta.color }}>
                    <Icon size={15} aria-hidden />
                  </span>
                  <div className="flex flex-wrap items-baseline gap-x-2">
                    <span className="text-sm font-bold" style={{ color: meta.color }}>{meta.label}</span>
                    {e.memory_type && <span className="text-xs text-graphite">{typeLabel(e.memory_type)}</span>}
                    <time className="text-xs text-graphite" dateTime={e.created_at}>
                      {new Date(e.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                    </time>
                  </div>
                  {e.content_preview && <p className="text-sm text-ink">{e.content_preview}</p>}
                  <p className="text-xs text-graphite">{e.reason}</p>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}

export function ActivityPage() {
  const [events, setEvents] = useState<MemoryEvent[] | null>(null);
  const [filter, setFilter] = useState("");
  const [mode, setMode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setEvents(await api.activity(filter || undefined));
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [filter]);
  useEffect(() => void load(), [load]);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const es = new EventSource(api.activityStreamUrl());
    es.addEventListener("ready", (m) => setMode(JSON.parse((m as MessageEvent).data).mode));
    es.onmessage = (m) => {
      const ev = JSON.parse(m.data) as MemoryEvent;
      if (filter && ev.action !== filter) return;
      setEvents((cur) => (cur && !cur.some((x) => x.id === ev.id) ? [ev, ...cur] : cur));
    };
    es.onerror = () => setMode(null);
    return () => es.close();
  }, [filter]);

  return (
    <div className="mx-auto max-w-3xl px-5 py-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-3xl">Activity</h1>
          <p className="mt-1 text-graphite">Every change to memory, with the reason it happened.</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-graphite">{mode ? `Live (${mode === "change_stream" ? "change stream" : "polling"})` : "Not live"}</span>
          <label className="text-sm"><span className="sr-only">Filter</span>
            <select className="field" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All activity</option>
              {Object.entries(ACTIONS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </label>
        </div>
      </div>
      <div className="mt-6">
        {error && <ErrorBanner message={error} onRetry={load} />}
        {!events && !error && <Loading label="Loading activity" />}
        {events && events.length === 0 && <Empty title="No memory activity yet">Activity appears as soon as Memora learns, updates or forgets something.</Empty>}
        {events && events.length > 0 && <ActivityTimeline events={events} />}
      </div>
    </div>
  );
}

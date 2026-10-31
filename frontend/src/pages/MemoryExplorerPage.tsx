import { Check, History, Pencil, Quote, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { EvidenceList } from "../components/EvidenceList";
import { Empty, ErrorBanner, Loading } from "../components/Feedback";
import { Tag, statusTone } from "../components/Tag";
import { TYPE_LABEL, pct, scopeLabel, typeLabel, when } from "../lib/format";
import { api } from "../services/api";
import type { Memory } from "../types";

const STATUSES = [
  { value: "active", label: "Active" },
  { value: "superseded", label: "Replaced" },
  { value: "expired", label: "Expired" },
  { value: "deleted", label: "Forgotten" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

export function MemoryExplorerPage() {
  const [items, setItems] = useState<Memory[] | null>(null);
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [status, setStatus] = useState("active");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setItems(await api.memories({ q, type, status }));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [q, type, status]);

  useEffect(() => {
    const t = window.setTimeout(load, 200);
    return () => window.clearTimeout(t);
  }, [load]);
  useEffect(() => {
    const h = () => void load();
    window.addEventListener("memora:refresh", h);
    return () => window.removeEventListener("memora:refresh", h);
  }, [load]);

  const pending = items?.filter((m) => m.confirmation === "pending" && m.status === "active").length ?? 0;

  return (
    <div className="mx-auto max-w-5xl px-5 py-6">
      <h1 className="text-3xl">Memories</h1>
      <p className="mt-1 max-w-[70ch] text-graphite">
        Everything Memora has learned about you, where it came from, and what replaced it. Edit, confirm or forget anything.
      </p>
      <div className="mt-5 flex flex-wrap items-end gap-3">
        <label className="relative min-w-[220px] flex-1">
          <span className="sr-only">Search memories</span>
          <Search size={15} className="absolute left-2.5 top-2.5 text-graphite" aria-hidden />
          <input className="field pl-8" placeholder="Search memories" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="text-sm"><span className="sr-only">Category</span>
          <select className="field" value={type} onChange={(e) => setType(e.target.value)}>
            <option value="">All categories</option>
            {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </label>
      </div>
      <div className="mt-3 flex flex-wrap gap-1" role="tablist" aria-label="Status">
        {STATUSES.map((s) => (
          <button key={s.value} role="tab" aria-selected={status === s.value}
            className={`rounded-md px-3 py-1 text-sm ${status === s.value ? "bg-ink text-paper" : "hover:bg-sheet"}`}
            onClick={() => setStatus(s.value)}>{s.label}</button>
        ))}
      </div>
      {pending > 0 && status === "active" && (
        <p className="mt-3 text-sm"><span className="marker">{pending} inferred memory(ies) need your confirmation.</span></p>
      )}
      <div className="mt-4">
        {error && <ErrorBanner message={error} onRetry={load} />}
        {!items && !error && <Loading label="Loading memories" />}
        {items && items.length === 0 && (
          <Empty title={q || type ? "No memories match these filters" : "Nothing remembered yet"}>
            {q || type ? "Clear the search or pick another category." : "Tell the assistant about your preferences, goals or difficulties in Chat."}
          </Empty>
        )}
        <ul className="divide-y divide-rule border-y border-rule">
          {items?.map((m) => <MemoryRow key={m.id} memory={m} onChanged={load} />)}
        </ul>
      </div>
    </div>
  );
}

export function MemoryRow({ memory: m, onChanged }: { memory: Memory; onChanged: () => void }) {
  const [panel, setPanel] = useState<"evidence" | "history" | null>(null);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(m.content);
  const [error, setError] = useState<string | null>(null);
  const active = m.status === "active";

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const forget = () => {
    if (window.confirm(`Forget "${m.content}"? It will be removed from retrieval and the knowledge graph.`)) {
      void act(() => api.forgetMemory(m.id));
    }
  };

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0 flex-1">
          {editing ? (
            <div className="flex gap-2">
              <label className="sr-only" htmlFor={`edit-${m.id}`}>Memory text</label>
              <input id={`edit-${m.id}`} className="field" value={text} onChange={(e) => setText(e.target.value)} maxLength={300} />
              <button className="btn-primary" onClick={() => act(async () => { await api.editMemory(m.id, { content: text }); setEditing(false); })}
                disabled={text.trim().length < 3}>Save</button>
              <button className="btn-quiet" onClick={() => { setEditing(false); setText(m.content); }}>Cancel</button>
            </div>
          ) : (
            <p className={`text-[15px] ${active ? "text-ink" : "text-graphite"}`}>{m.content}</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-graphite">
            <Tag>{typeLabel(m.type)}</Tag>
            <Tag tone={statusTone(m.status)}>{m.status === "superseded" ? "replaced" : m.status === "deleted" ? "forgotten" : m.status}</Tag>
            {scopeLabel(m.scope) && <Tag tone="cobalt">{scopeLabel(m.scope)}</Tag>}
            {m.confirmation === "pending" && <Tag tone="highlight">Needs confirmation</Tag>}
            {m.origin !== "explicit" && <Tag title="Not stated directly by you">{m.origin}</Tag>}
            {m.seed && <Tag>Sample data</Tag>}
            <span>confidence {pct(m.confidence)}</span>
            <span>importance {pct(m.importance)}</span>
            {m.strength_now != null && <span>strength {pct(m.strength_now)}</span>}
            <span>created {when(m.created_at)}</span>
            <span>updated {when(m.updated_at)}</span>
            {m.expires_at && <span>expires {when(m.expires_at)}</span>}
            {m.source?.conversation_id && <span>from conversation {m.source.conversation_id.slice(-6)}</span>}
          </div>
        </div>
        <div className="flex flex-wrap gap-1">
          {active && m.confirmation === "pending" && (
            <>
              <button className="btn-quiet" onClick={() => act(() => api.confirmMemory(m.id, true))}><Check size={14} aria-hidden />Confirm</button>
              <button className="btn-quiet" onClick={() => act(() => api.confirmMemory(m.id, false))}><X size={14} aria-hidden />Reject</button>
            </>
          )}
          {active && !editing && <button className="btn-quiet" onClick={() => setEditing(true)}><Pencil size={14} aria-hidden />Edit</button>}
          <button className="btn-quiet" aria-expanded={panel === "evidence"} onClick={() => setPanel(panel === "evidence" ? null : "evidence")}>
            <Quote size={14} aria-hidden />Evidence</button>
          <button className="btn-quiet" aria-expanded={panel === "history"} onClick={() => setPanel(panel === "history" ? null : "history")}>
            <History size={14} aria-hidden />History</button>
          {m.status !== "deleted" && <button className="btn-danger" onClick={forget}><Trash2 size={14} aria-hidden />Forget</button>}
        </div>
      </div>
      {error && <div className="mt-2"><ErrorBanner message={error} /></div>}
      {panel === "evidence" && <div className="mt-3 pl-1"><EvidenceList memoryId={m.id} /></div>}
      {panel === "history" && <div className="mt-3 pl-1"><HistoryPanel memoryId={m.id} /></div>}
    </li>
  );
}

function HistoryPanel({ memoryId }: { memoryId: string }) {
  const [data, setData] = useState<Awaited<ReturnType<typeof api.history>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.history(memoryId).then(setData).catch((e: Error) => setError(e.message));
  }, [memoryId]);
  if (error) return <ErrorBanner message={error} />;
  if (!data) return <Loading label="Loading history" />;
  return (
    <div className="space-y-2 text-sm">
      {data.related.map((r) => (
        <p key={r.id} className="text-graphite">{r.relation === "replaced" ? "Replaced" : "Replaced by"}: <span className="text-ink">{r.content}</span></p>
      ))}
      <ol className="space-y-1 border-l-2 border-rule pl-3">
        {data.history.map((h, i) => (
          <li key={i}><span className="font-bold">{h.action}</span> <span className="text-graphite">{when(h.at)}</span>: {h.reason}</li>
        ))}
        {data.history.length === 0 && <li className="text-graphite">No history kept (forgotten memories keep none).</li>}
      </ol>
    </div>
  );
}

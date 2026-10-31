import { Activity, BookMarked, Clock, LogOut, MessageSquare, RotateCcw, Share2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../hooks/useAuth";
import { api } from "../services/api";
import type { SystemStatus } from "../types";

const NAV = [
  { to: "/", label: "Chat", icon: MessageSquare },
  { to: "/memories", label: "Memories", icon: BookMarked },
  { to: "/graph", label: "Knowledge graph", icon: Share2 },
  { to: "/activity", label: "Activity", icon: Activity },
];

export function Layout() {
  const { user, signOut } = useAuth();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const loadStatus = useCallback(() => {
    api.status().then(setStatus).catch(() => setStatus(null));
  }, []);
  useEffect(() => {
    loadStatus();
  }, [loadStatus]);

  useEffect(() => {
    if (typeof EventSource === "undefined" || !user) return;
    const es = new EventSource(api.activityStreamUrl());
    es.onmessage = () => {
      loadStatus();
      window.dispatchEvent(new Event("memora:refresh"));
    };
    return () => es.close();
  }, [user, loadStatus]);

  const changeClock = async (days: number | null) => {
    const r = days === null ? await api.resetClock() : await api.advanceClock(days);
    setNote(r.expired ? `${r.expired} temporary memory expired` : null);
    loadStatus();
    window.dispatchEvent(new Event("memora:refresh"));
  };

  const resetDemo = async () => {
    if (!window.confirm("Reset the demo account to its sample data? Your demo conversations will be removed.")) return;
    await api.resetDemo();
    window.dispatchEvent(new Event("memora:refresh"));
    window.location.assign("/");
  };

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-rule bg-sheet md:w-60 md:border-b-0 md:border-r">
        <div className="px-4 pb-2 pt-4">
          <div className="font-serif text-2xl font-semibold tracking-tight">Memora</div>
          <p className="text-xs text-graphite">Remembers how you learn</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 md:flex-col" aria-label="Main">
          {NAV.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} end={to === "/"}
              className={({ isActive }) =>
                `flex items-center gap-2 whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-ink font-bold text-paper" : "text-ink hover:bg-paper"}`}>
              <Icon size={16} aria-hidden /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden space-y-4 px-4 py-4 text-xs md:block">
          {status && (
            <section aria-label="System status" className="space-y-1">
              <Row k="Model" v={status.llm_offline ? "Offline demo model" : status.chat_model ?? status.llm_provider} warn={status.llm_offline} />
              <Row k="Embeddings" v={status.embedding_offline ? "Offline hashing" : status.embedding_provider} warn={status.embedding_offline} />
              <Row k="Retrieval" v={status.retrieval_backend === "mongodb_vector_search" ? "MongoDB Vector Search" : "Local fallback (dev only)"}
                warn={status.retrieval_backend !== "mongodb_vector_search"} />
              <Row k="Live updates" v={status.change_streams ? "Change streams" : "Polling"} />
            </section>
          )}
          {status?.demo_tools && (
            <section aria-label="Demo clock" className="space-y-1.5">
              <div className="flex items-center gap-1.5 text-graphite"><Clock size={13} aria-hidden />
                Clock: {new Date(status.user_clock).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
              </div>
              <div className="flex flex-wrap gap-1">
                <button className="rounded border border-rule px-2 py-0.5 hover:bg-paper" onClick={() => changeClock(1)}>+1 day</button>
                <button className="rounded border border-rule px-2 py-0.5 hover:bg-paper" onClick={() => changeClock(7)}>+7 days</button>
                <button className="rounded border border-rule px-2 py-0.5 hover:bg-paper" onClick={() => changeClock(null)}>Today</button>
              </div>
              {note && <p className="text-moss">{note}</p>}
            </section>
          )}
          <div className="flex items-center justify-between border-t border-rule pt-3">
            <span className="truncate text-graphite">{user?.display_name ?? user?.username}</span>
            <div className="flex gap-1">
              {user?.is_demo && (
                <button className="rounded p-1 hover:bg-paper" onClick={resetDemo} title="Reset demo data" aria-label="Reset demo data">
                  <RotateCcw size={14} />
                </button>
              )}
              <button className="rounded p-1 hover:bg-paper" onClick={signOut} title="Sign out" aria-label="Sign out">
                <LogOut size={14} />
              </button>
            </div>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1">
        <Outlet />
      </main>
    </div>
  );
}

function Row({ k, v, warn }: { k: string; v: string; warn?: boolean }) {
  return (
    <div className="flex justify-between gap-2">
      <span className="text-graphite">{k}</span>
      <span className={`truncate text-right ${warn ? "text-forget" : "text-ink"}`}>{v}</span>
    </div>
  );
}

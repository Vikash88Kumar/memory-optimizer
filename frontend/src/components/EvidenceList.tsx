import { useEffect, useState } from "react";
import { api } from "../services/api";
import type { EvidenceItem } from "../types";
import { when } from "../lib/format";
import { ErrorBanner, Loading } from "./Feedback";

export function EvidenceList({ memoryId }: { memoryId: string }) {
  const [items, setItems] = useState<EvidenceItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api.evidence(memoryId).then((r) => live && setItems(r.evidence)).catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [memoryId]);

  if (error) return <ErrorBanner message={error} />;
  if (!items) return <Loading label="Loading evidence" />;
  if (items.length === 0) return <p className="text-sm text-graphite">No source messages recorded for this memory.</p>;
  return (
    <ul className="space-y-2" aria-label="Evidence">
      {items.map((ev) => (
        <li key={ev.message_id} className="border-l-2 border-rule pl-3 text-sm">
          {ev.missing ? (
            <span className="text-graphite">{ev.note}</span>
          ) : (
            <>
              <q className={ev.redacted ? "text-graphite" : "text-ink"}>{ev.content}</q>
              <div className="text-xs text-graphite">
                {ev.role === "user" ? "You said" : "Assistant said"}, {when(ev.created_at)}
              </div>
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

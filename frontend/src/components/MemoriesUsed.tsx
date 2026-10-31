import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import type { TurnContextInfo } from "../types";
import { pct, scopeLabel, typeLabel } from "../lib/format";
import { EvidenceList } from "./EvidenceList";
import { Tag } from "./Tag";

/** The signature element: memories that shaped an answer, shown as highlighted index cards. */
export function MemoriesUsed({ context }: { context: TurnContextInfo }) {
  const [open, setOpen] = useState(false);
  const [evidenceFor, setEvidenceFor] = useState<string | null>(null);
  const used = context.memories_used ?? [];
  const n = used.length;
  return (
    <div className="mt-2">
      <button
        className="inline-flex items-center gap-1 rounded px-1 text-sm font-bold text-ink hover:bg-highlight-soft"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {open ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />}
        <span className={n ? "marker" : ""}>Memories used: {n}</span>
        {context.overridden?.length ? <span className="font-normal text-graphite">, {context.overridden.length} overridden</span> : null}
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {n === 0 && <p className="text-sm text-graphite">No stored memory was relevant to this message.</p>}
          {used.map((m) => (
            <article key={m.id} className="rounded-md border border-[#e3cf6b] bg-highlight-soft/60 px-3 py-2">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-bold text-[#5c4b00]">{m.ref}</span>
                <Tag tone="highlight">{typeLabel(m.type)}</Tag>
                {m.tier === "core" && <Tag>Core profile</Tag>}
                {scopeLabel(m.scope) && <Tag tone="cobalt">{scopeLabel(m.scope)}</Tag>}
                <span className="ml-auto text-xs text-graphite">confidence {pct(m.confidence)}</span>
              </div>
              <p className="mt-1 text-sm text-ink">{m.content}</p>
              <ul className="mt-1 list-disc pl-5 text-xs text-graphite">
                {m.reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
              <button className="mt-1 text-xs font-bold text-cobalt underline-offset-2 hover:underline"
                onClick={() => setEvidenceFor(evidenceFor === m.id ? null : m.id)}>
                {evidenceFor === m.id ? "Hide original messages" : "Show original messages"}
              </button>
              {evidenceFor === m.id && <div className="mt-2"><EvidenceList memoryId={m.id} /></div>}
            </article>
          ))}
          {context.overridden?.map((o) => (
            <p key={o.id} className="text-xs text-graphite">
              Not applied: <s>{o.content}</s> ({o.reason.toLowerCase()})
            </p>
          ))}
          {context.evidence_reason && (
            <p className="text-xs text-graphite">Original conversation excerpts included: {context.evidence_reason.toLowerCase()}.</p>
          )}
        </div>
      )}
    </div>
  );
}

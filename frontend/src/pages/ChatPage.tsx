import { Loader2, Plus, Send, Trash2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ContextBudget } from "../components/ContextBudget";
import { Empty, ErrorBanner, Loading } from "../components/Feedback";
import { MemoriesUsed } from "../components/MemoriesUsed";
import { Tag } from "../components/Tag";
import { useJobWatcher } from "../hooks/useJobs";
import { scopeLabel, typeLabel } from "../lib/format";
import { api } from "../services/api";
import type { Conversation, Message, TurnContextInfo } from "../types";

const STARTERS = [
  "I prefer learning algorithms with visual examples.",
  "Explain binary search.",
  "I no longer want visual explanations. Give me code-first explanations.",
  "For mathematics, I want detailed explanations.",
  "I have an exam next Monday.",
  "Forget that I struggle with recursion.",
];

export function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatedNote, setUpdatedNote] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  const onSettled = useCallback(() => {
    setUpdatedNote(true);
    window.dispatchEvent(new Event("memora:refresh"));
    window.setTimeout(() => setUpdatedNote(false), 4000);
  }, []);
  const jobs = useJobWatcher(onSettled);

  const loadConversations = useCallback(async () => {
    try {
      const list = await api.conversations();
      setConversations(list);
      setActiveId((cur) => cur ?? list.find((c) => !c.seed)?.id ?? list[0]?.id ?? null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void loadConversations();
    const h = () => void loadConversations();
    window.addEventListener("memora:refresh", h);
    return () => window.removeEventListener("memora:refresh", h);
  }, [loadConversations]);

  useEffect(() => {
    if (!activeId) {
      setMessages([]);
      return;
    }
    api.messages(activeId).then(setMessages).catch((e: Error) => setError(e.message));
  }, [activeId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messages, sending]);

  const newConversation = async () => {
    const c = await api.createConversation();
    setConversations((list) => [c, ...(list ?? [])]);
    setActiveId(c.id);
    setMessages([]);
  };

  const removeConversation = async (id: string) => {
    if (!window.confirm("Delete this conversation? Memories extracted from it stay in the Memory Explorer.")) return;
    await api.deleteConversation(id);
    setActiveId(null);
    await loadConversations();
  };

  const send = async (text: string) => {
    const content = text.trim();
    if (!content || sending) return;
    let cid = activeId;
    if (!cid) {
      const c = await api.createConversation();
      cid = c.id;
      setActiveId(c.id);
    }
    setSending(true);
    setError(null);
    const optimistic: Message = { id: `tmp-${Date.now()}`, conversation_id: cid, role: "user", content, created_at: new Date().toISOString() };
    setMessages((m) => [...m, optimistic]);
    setDraft("");
    try {
      const res = await api.send(cid, content);
      setMessages((m) => [...m.filter((x) => x.id !== optimistic.id), res.user_message, res.assistant_message]);
      if (res.context.extraction_scheduled) jobs.watch();
      void loadConversations();
    } catch (e) {
      setMessages((m) => m.filter((x) => x.id !== optimistic.id));
      setDraft(content);
      setError((e as Error).message);
    } finally {
      setSending(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void send(draft);
  };
  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send(draft);
    }
  };

  const lastContext = [...messages].reverse().find((m) => m.role === "assistant" && m.context)?.context ?? null;

  return (
    <div className="grid h-[calc(100vh-0px)] grid-cols-1 lg:grid-cols-[220px_minmax(0,1fr)_320px]">
      <section className="hidden flex-col border-r border-rule lg:flex" aria-label="Conversations">
        <div className="p-3">
          <button className="btn-primary w-full justify-center" onClick={newConversation}><Plus size={15} aria-hidden /> New conversation</button>
        </div>
        <ul className="flex-1 overflow-y-auto px-2 pb-3">
          {conversations === null && <Loading />}
          {conversations?.map((c) => (
            <li key={c.id} className="group flex items-center">
              <button onClick={() => setActiveId(c.id)}
                className={`flex-1 truncate rounded-md px-3 py-2 text-left text-sm ${c.id === activeId ? "bg-sheet font-bold" : "hover:bg-sheet/70"}`}>
                {c.title}
              </button>
              <button className="invisible rounded p-1 text-graphite hover:text-forget group-hover:visible" aria-label={`Delete ${c.title}`}
                onClick={() => removeConversation(c.id)}><Trash2 size={14} /></button>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex min-h-0 flex-col" aria-label="Chat">
        <header className="flex items-center justify-between border-b border-rule px-5 py-3">
          <h1 className="truncate text-xl">{conversations?.find((c) => c.id === activeId)?.title ?? "New conversation"}</h1>
          <div className="flex items-center gap-2 text-xs">
            {jobs.pending && <span className="flex items-center gap-1 text-graphite"><Loader2 size={13} className="animate-spin" aria-hidden />Updating memory</span>}
            {updatedNote && !jobs.pending && <span className="text-moss">Memory updated</span>}
            <button className="btn-quiet lg:hidden" onClick={newConversation}><Plus size={14} aria-hidden />New</button>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto px-5 py-4">
          <div className="mx-auto max-w-[68ch] space-y-5">
            {messages.length === 0 && !sending && (
              <Empty title="Tell Memora something about how you learn">
                <p>Then open a new conversation and ask a question: the answer will use what it remembered.</p>
                <div className="mt-4 flex flex-wrap justify-center gap-2">
                  {STARTERS.map((s) => (
                    <button key={s} className="rounded-full border border-rule bg-sheet px-3 py-1 text-left text-xs text-ink hover:border-cobalt"
                      onClick={() => setDraft(s)}>{s}</button>
                  ))}
                </div>
              </Empty>
            )}
            {messages.map((m, i) => (
              <MessageView key={m.id} message={m} previous={messages[i - 1]} />
            ))}
            {sending && <p className="flex items-center gap-2 text-sm text-graphite"><Loader2 size={14} className="animate-spin" aria-hidden />Recalling memories and writing an answer</p>}
            <div ref={endRef} />
          </div>
        </div>
        <form onSubmit={onSubmit} className="border-t border-rule px-5 py-3">
          {error && <div className="mx-auto mb-2 max-w-[68ch]"><ErrorBanner message={error} /></div>}
          <div className="mx-auto flex max-w-[68ch] items-end gap-2">
            <label htmlFor="composer" className="sr-only">Message</label>
            <textarea id="composer" rows={2} className="field resize-none" placeholder="Ask a question or tell Memora about yourself"
              value={draft} onChange={(e) => setDraft(e.target.value)} onKeyDown={onKey} maxLength={4000} />
            <button className="btn-primary h-10" disabled={sending || !draft.trim()} aria-label="Send">
              <Send size={15} aria-hidden />
            </button>
          </div>
        </form>
      </section>

      <WorkingMemoryPanel context={lastContext} />
    </div>
  );
}

function MessageView({ message, previous }: { message: Message; previous?: Message }) {
  const ctx = message.context;
  const switched = ctx?.episode?.switched && previous;
  return (
    <>
      {switched && (
        <div className="flex items-center gap-3 text-xs text-graphite" role="separator">
          <span className="h-px flex-1 bg-rule" />New episode started; the previous one is being summarised<span className="h-px flex-1 bg-rule" />
        </div>
      )}
      {message.role === "user" ? (
        <div className="ml-auto max-w-[85%] rounded-lg bg-ink px-4 py-2.5 text-paper">
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{message.content}</p>
        </div>
      ) : (
        <div className="max-w-full">
          {ctx?.offline_model && <p className="mb-1 text-xs text-forget">Offline demo model: configure an LLM provider for real answers</p>}
          <p className="whitespace-pre-wrap text-[15px] leading-relaxed">{message.content}</p>
          {ctx && <MemoriesUsed context={ctx} />}
        </div>
      )}
    </>
  );
}

function WorkingMemoryPanel({ context }: { context: TurnContextInfo | null }) {
  return (
    <aside className="hidden overflow-y-auto border-l border-rule bg-sheet px-4 py-4 lg:block" aria-label="Working memory">
      <h2 className="text-lg">Working memory</h2>
      <p className="mt-1 text-xs text-graphite">What the assistant was given for the last answer, instead of the full chat history.</p>
      {!context ? (
        <p className="mt-6 text-sm text-graphite">Send a message to see which memories are loaded.</p>
      ) : (
        <div className="mt-4 space-y-5">
          <ContextBudget tokens={context.tokens} />
          <section>
            <h3 className="text-sm font-bold font-sans">Episode</h3>
            <p className="text-sm">{context.episode.title}</p>
            <p className="text-xs text-graphite">{context.episode.turns} turn(s){context.episode.switched ? ", just started" : ""}</p>
            {context.episode.bridge && <p className="mt-1 text-xs text-graphite">Carried over: {context.episode.bridge}</p>}
          </section>
          {(["core", "retrieved"] as const).map((tier) => {
            const items = context.memories_used.filter((m) => m.tier === tier);
            return (
              <section key={tier}>
                <h3 className="text-sm font-bold font-sans">{tier === "core" ? "Core profile" : "Retrieved for this message"}</h3>
                {items.length === 0 ? <p className="text-xs text-graphite">None</p> : (
                  <ul className="mt-1 space-y-1.5">
                    {items.map((m) => (
                      <li key={m.id} className="text-sm">
                        <span className="marker">{m.content}</span>
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          <Tag>{typeLabel(m.type)}</Tag>
                          {scopeLabel(m.scope) && <Tag tone="cobalt">{scopeLabel(m.scope)}</Tag>}
                          {m.activation != null && <Tag title="Working-memory activation; fades each turn the memory is not relevant">activation {m.activation.toFixed(2)}</Tag>}
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}
          <section className="text-xs text-graphite">
            Retrieval: {context.retrieval_backend === "mongodb_vector_search" ? "MongoDB Vector Search" : "local fallback (development only)"}
          </section>
        </div>
      )}
    </aside>
  );
}

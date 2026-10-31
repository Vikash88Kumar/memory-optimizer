import type { TokenUsage } from "../types";

const TIERS: { key: keyof TokenUsage; label: string; color: string }[] = [
  { key: "core", label: "Core profile", color: "#1B2430" },
  { key: "bridge", label: "Bridge", color: "#5B6675" },
  { key: "episode", label: "This episode", color: "#2F6FDE" },
  { key: "memories", label: "Memories", color: "#F2D64B" },
  { key: "evidence", label: "Evidence", color: "#3C7A55" },
];

export function ContextBudget({ tokens }: { tokens: TokenUsage }) {
  const total = Math.max(tokens.total, 1);
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-sm bg-rule" role="img"
        aria-label={`Context of ${tokens.total} tokens`}>
        {TIERS.map((t) => tokens[t.key] > 0 && (
          <div key={t.key} style={{ width: `${(tokens[t.key] / total) * 100}%`, background: t.color }} />
        ))}
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        {TIERS.map((t) => (
          <div key={t.key} className="flex justify-between">
            <dt className="flex items-center gap-1.5 text-graphite">
              <span className="inline-block h-2 w-2 rounded-sm" style={{ background: t.color }} aria-hidden />{t.label}
            </dt>
            <dd>{tokens[t.key]}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-graphite">
        {tokens.total} tokens of memory context. This conversation so far: {tokens.full_history} tokens, which a
        history-replay approach would resend in full every turn.
      </p>
    </div>
  );
}

import type { ReactNode } from "react";

const TONES = {
  neutral: "border-rule text-graphite",
  cobalt: "border-cobalt/30 bg-cobalt-soft text-cobalt",
  highlight: "border-[#d9bc2d] bg-highlight-soft text-[#5c4b00]",
  forget: "border-forget/30 bg-forget-soft text-forget",
  moss: "border-moss/30 bg-[#e3f0e8] text-moss",
} as const;

export function Tag({ children, tone = "neutral", title }: { children: ReactNode; tone?: keyof typeof TONES; title?: string }) {
  return (
    <span title={title} className={`inline-flex items-center gap-1 rounded border px-1.5 py-px text-xs ${TONES[tone]}`}>
      {children}
    </span>
  );
}

export function statusTone(status: string): keyof typeof TONES {
  if (status === "active") return "moss";
  if (status === "deleted" || status === "rejected") return "forget";
  if (status === "superseded" || status === "expired") return "neutral";
  return "cobalt";
}

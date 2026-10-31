import type { MemoryType } from "../types";

export const TYPE_LABEL: Record<MemoryType, string> = {
  preference: "Preference", interest: "Interest", knowledge: "Knowledge", learning_difficulty: "Difficulty",
  goal: "Goal", decision: "Decision", constraint: "Constraint", experience: "Experience", feedback: "Feedback",
  strategy: "Strategy", fact: "Fact",
};

export function typeLabel(t: string): string {
  return TYPE_LABEL[t as MemoryType] ?? t;
}

export function scopeLabel(scope: string): string | null {
  return scope?.startsWith("topic:") ? `Only for ${scope.slice(6)}` : null;
}

export function pct(v: number | null | undefined): string {
  return v == null ? "–" : `${Math.round(v * 100)}%`;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
}

import { AlertTriangle, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

export function ErrorBanner({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex items-start gap-2 rounded-md border border-forget/40 bg-forget-soft px-3 py-2 text-sm text-forget">
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <span className="flex-1">{message}</span>
      {onRetry && <button className="font-bold underline" onClick={onRetry}>Try again</button>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 text-sm text-graphite" role="status">
      <Loader2 size={16} className="animate-spin" aria-hidden /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mx-auto max-w-md py-12 text-center">
      <h3 className="text-lg text-ink">{title}</h3>
      {children && <div className="mt-2 text-sm text-graphite">{children}</div>}
    </div>
  );
}

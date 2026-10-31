import { useCallback, useRef, useState } from "react";
import { api } from "../services/api";

/** Polls the background-job counter after a message so the UI can show when memory has been updated. */
export function useJobWatcher(onSettled: () => void) {
  const [pending, setPending] = useState(false);
  const timer = useRef<number | null>(null);

  const watch = useCallback(() => {
    setPending(true);
    let tries = 0;
    const tick = async () => {
      tries += 1;
      try {
        const { pending: n } = await api.jobs();
        if (n === 0 || tries > 40) {
          setPending(false);
          onSettled();
          return;
        }
      } catch {
        setPending(false);
        return;
      }
      timer.current = window.setTimeout(tick, 700);
    };
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(tick, 400);
  }, [onSettled]);

  return { pending, watch };
}

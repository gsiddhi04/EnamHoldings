import { useCallback, useEffect, useRef, useState } from "react";

/** Fetch on mount / when deps change. Stale responses (an older request finishing late) are ignored. */
export function useAsync(fn, deps) {
  const [state, set] = useState({ data: null, error: null, loading: true });
  const tick = useRef(0);
  const run = useCallback(() => {
    const id = ++tick.current;
    set((s) => ({ ...s, loading: true, error: null }));
    fn().then(
      (data) => id === tick.current && set({ data, error: null, loading: false }),
      (e) => id === tick.current && set({ data: null, error: e.message || String(e), loading: false }),
    );
  }, deps); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(run, [run]);
  return { ...state, reload: run };
}

/** Rotating status text while a slow request runs; honest copy supplied by the caller. */
export function useTicker(lines, active, ms = 4500) {
  const [i, setI] = useState(0);
  useEffect(() => {
    if (!active) return undefined;
    setI(0);
    const t = setInterval(() => setI((x) => Math.min(x + 1, lines.length - 1)), ms);
    return () => clearInterval(t);
  }, [active]); // eslint-disable-line react-hooks/exhaustive-deps
  return lines[i];
}

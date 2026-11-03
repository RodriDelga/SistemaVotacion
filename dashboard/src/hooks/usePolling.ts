import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

export interface Polled<T> {
  data: T | null;
  error: string | null;
  /** true solo en la primera carga (o al cambiar los parametros sin datos previos) */
  loading: boolean;
  updatedAt: number | null;
  refresh: () => void;
}

/**
 * Consulta periodica. Conserva los ultimos datos buenos si una consulta falla (se muestra "datos desactualizados"),
 * se pausa con la pestana oculta y descarta respuestas de peticiones anteriores a un cambio de parametros.
 */
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, intervalMs: number, deps: unknown[] = []): Polled<T> {
  const [state, setState] = useState<{ data: T | null; error: string | null; loading: boolean; updatedAt: number | null }>(
    { data: null, error: null, loading: true, updatedAt: null });
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const tickRef = useRef<() => void>(() => {});

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    setState((prev) => ({ ...prev, loading: prev.data === null, error: null }));

    const run = async () => {
      controller?.abort();
      controller = new AbortController();
      try {
        const data = await fetcherRef.current(controller.signal);
        if (!cancelled) setState({ data, error: null, loading: false, updatedAt: Date.now() });
      } catch (error) {
        if (cancelled || (error as Error).name === "AbortError") return;
        const message = error instanceof ApiError ? error.message : "No se pudo actualizar";
        setState((prev) => ({ ...prev, error: message, loading: false }));
      } finally {
        if (!cancelled) schedule();
      }
    };
    const schedule = () => {
      clearTimeout(timer);
      timer = setTimeout(() => { if (document.visibilityState === "visible") void run(); else schedule(); }, intervalMs);
    };
    const onVisible = () => { if (document.visibilityState === "visible") { clearTimeout(timer); void run(); } };
    tickRef.current = () => { clearTimeout(timer); void run(); };
    document.addEventListener("visibilitychange", onVisible);
    void run();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisible);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs, ...deps]);

  const refresh = useCallback(() => tickRef.current(), []);
  return { ...state, refresh };
}

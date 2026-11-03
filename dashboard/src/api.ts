import type {
  Analytics, AuthState, EventsResponse, Meta, Participation, Results, SystemStatus, Timeline,
} from "./types";

const BASE = "/api/v1/admin";

export class ApiError extends Error {
  constructor(public status: number, message: string, public retryAfter?: number) {
    super(message);
  }
}

let onUnauthorized: (() => void) | null = null;
/** App registra aqui como volver al login cuando la cookie expira. */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "dashboard", Accept: "application/json" };
  let body: BodyInit | undefined;
  if (init.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(init.json);
  }
  let response: Response;
  try {
    response = await fetch(BASE + path, {
      method: init.method ?? "GET", headers, body, credentials: "same-origin", signal: init.signal,
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError(0, "Sin conexión con el servidor");
  }
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const data = await response.json();
      if (typeof data?.detail === "string") detail = data.detail;
    } catch { /* respuesta sin JSON */ }
    if (response.status === 401 && !path.startsWith("/login") && !path.startsWith("/me")) onUnauthorized?.();
    const retry = Number(response.headers.get("Retry-After"));
    throw new ApiError(response.status, detail, Number.isFinite(retry) && retry > 0 ? retry : undefined);
  }
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export interface Range { from?: string; to?: string }

export const api = {
  me: (signal?: AbortSignal) => request<AuthState>("/me", { signal }),
  login: (password: string) => request<AuthState>("/login", { method: "POST", json: { password } }),
  logout: () => request<AuthState>("/logout", { method: "POST" }),
  meta: (signal?: AbortSignal) => request<Meta>("/meta", { signal }),
  results: (office?: string, state?: string, signal?: AbortSignal) =>
    request<Results>(`/results${qs({ office, state })}`, { signal }),
  participation: (signal?: AbortSignal) => request<Participation>("/participation", { signal }),
  timeline: (range: Range, signal?: AbortSignal) => request<Timeline>(`/timeline${qs({ ...range })}`, { signal }),
  system: (signal?: AbortSignal) => request<SystemStatus>("/system", { signal }),
  events: (limit: number, range: Range = {}, signal?: AbortSignal) =>
    request<EventsResponse>(`/events${qs({ limit, ...range })}`, { signal }),
  analytics: (range: Range, signal?: AbortSignal) => request<Analytics>(`/analytics${qs({ ...range })}`, { signal }),
  exportUrl: (dataset: "results" | "participation" | "events", range: Range = {}) =>
    `${BASE}/export/${dataset}.csv${qs({ ...range })}`,
};

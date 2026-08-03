import type {
  ActionView,
  ActiveDeckView,
  JudgmentRequest,
  ProjectDashboardView,
  SessionCompletionView,
  WorkspaceCatalogView,
} from "./generated";

export type Action = ActionView;
export type Deck = ActiveDeckView;
export type Judgment = JudgmentRequest;
export type Project = ProjectDashboardView;
export type SessionCompletion = SessionCompletionView;
export type WorkspaceCatalog = WorkspaceCatalogView;

export class ApiError extends Error {
  readonly code: string;

  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

let startupToken = "";

export function initializeToken(): void {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const token = fragment.get("token");
  if (!token) return;
  startupToken = token;
  window.history.replaceState(null, "", window.location.pathname);
  // 以後は素のURLで開けるよう、サーバーにCookieを発行してもらう。
  void api("/api/browser-sessions", { method: "POST" }).catch(() => undefined);
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (startupToken) headers.set("Authorization", `Bearer ${startupToken}`);
  if (options.body !== undefined && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.method && options.method !== "GET" && !headers.has("Idempotency-Key")) {
    headers.set("Idempotency-Key", crypto.randomUUID());
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error?: { code?: string; message?: string };
    } | null;
    throw new ApiError(
      body?.error?.message ?? `Request failed (${response.status})`,
      body?.error?.code ?? "request_failed",
    );
  }
  return (await response.json()) as T;
}

export type ItemStatus = "ACTIVE" | "PROCESSING" | "FAILED" | "ARCHIVED";
export type SourceType = "note" | "url";

export type Item = {
  id: string;
  title: string;
  content: string;
  source_type: SourceType;
  source_url: string | null;
  source_metadata: Record<string, unknown>;
  external_id: string | null;
  status: ItemStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  effective_at: string | null;
};

export type SourceReference = {
  item_id: string;
  title: string;
  source_url: string | null;
  chunk_id: string;
  excerpt: string;
  effective_at: string | null;
  created_at: string;
};

export type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: SourceReference[] | null;
  created_at: string;
};

export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = Conversation & { messages: Message[] };

export type Revision = {
  id: string;
  item_id: string;
  revision_number: number;
  title_snapshot: string;
  content_snapshot: string;
  source_type_snapshot: SourceType;
  source_url_snapshot: string | null;
  source_metadata_snapshot: Record<string, unknown>;
  effective_at_snapshot: string | null;
  status_snapshot: ItemStatus;
  change_type: string;
  changed_at: string;
  change_summary: string | null;
};

export type Account = { id: string; email: string; display_name: string | null; created_at: string };
export type ItemUpdate = Partial<Pick<Item, "title" | "content" | "effective_at" | "source_url" | "source_metadata" | "status">>;

const API_BASE_URL = (import.meta.env["VITE_API_BASE_URL"] ?? "http://localhost:8000").replace(/\/$/, "");
const API_PREFIX = "/api/v1";
const TOKEN_KEY = "aki_access_token";

export class ApiError extends Error {
  status: number;
  code: string | undefined;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export function passwordIssue(password: string) {
  if (password.length < 12) return "Use at least 12 characters.";
  if (password.length > 128) return "Use no more than 128 characters.";
  return null;
}

export function readToken() {
  return typeof window === "undefined" ? null : window.sessionStorage.getItem(TOKEN_KEY);
}

export function saveToken(token: string) {
  window.sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  if (typeof window !== "undefined") window.sessionStorage.removeItem(TOKEN_KEY);
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const token = readToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    throw new ApiError("Can’t reach the inbox service. Check the service address and try again.", 0);
  }

  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const message = body?.error?.message ?? `The request couldn’t be completed (${response.status}).`;
    const code = body?.error?.code;
    if (response.status === 401) {
      clearToken();
      window.dispatchEvent(new CustomEvent("aki:unauthorized"));
    }
    throw new ApiError(message, response.status, code);
  }
  return body as T;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method,
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export const authApi = {
  login: (email: string, password: string) => api<{ access_token: string; token_type: "bearer"; expires_in: number }>(`${API_PREFIX}/auth/login`, json("POST", { email, password })),
  register: (email: string, password: string) => api<{ access_token: string; token_type: "bearer"; expires_in: number }>(`${API_PREFIX}/auth/register`, json("POST", { email, password })),
  me: () => api<Account>(`${API_PREFIX}/auth/me`),
  updateProfile: (displayName: string | null) => api<Account>(`${API_PREFIX}/auth/me`, json("PATCH", { display_name: displayName })),
};

export const itemsApi = {
  list: (offset = 0, limit = 50) => api<{ items: Item[]; total: number }>(`${API_PREFIX}/items?offset=${offset}&limit=${limit}`),
  get: (id: string) => api<Item>(`${API_PREFIX}/items/${encodeURIComponent(id)}`),
  createNote: (title: string, content: string, effectiveAt: string | null, metadata: Record<string, unknown> = {}) => api<{ id: string; title: string; status: ItemStatus; chunk_count: number }>(`${API_PREFIX}/ingest`, json("POST", { source_type: "note", title, content, effective_at: effectiveAt, source_metadata: metadata })),
  createUrl: (url: string, effectiveAt: string | null, title?: string, metadata: Record<string, unknown> = {}) => api<{ id: string; title: string; status: ItemStatus; chunk_count: number }>(`${API_PREFIX}/ingest`, json("POST", { source_type: "url", url, effective_at: effectiveAt, source_metadata: metadata, ...(title ? { title } : {}) })),
  update: (id: string, patch: ItemUpdate) => api<Item>(`${API_PREFIX}/items/${encodeURIComponent(id)}`, json("PATCH", patch)),
  delete: (id: string) => api<void>(`${API_PREFIX}/items/${encodeURIComponent(id)}`, json("DELETE")),
  history: (id: string) => api<Revision[]>(`${API_PREFIX}/items/${encodeURIComponent(id)}/history`),
  revision: (id: string, revisionId: string) => api<Revision>(`${API_PREFIX}/items/${encodeURIComponent(id)}/history/${encodeURIComponent(revisionId)}`),
  restore: (id: string, revisionId: string) => api<Item>(`${API_PREFIX}/items/${encodeURIComponent(id)}/restore/${encodeURIComponent(revisionId)}`, json("POST")),
};

export const conversationsApi = {
  list: () => api<Conversation[]>(`${API_PREFIX}/conversations`),
  get: (id: string) => api<ConversationDetail>(`${API_PREFIX}/conversations/${encodeURIComponent(id)}`),
  create: (title?: string) => api<Conversation>(`${API_PREFIX}/conversations`, json("POST", title ? { title } : {})),
  rename: (id: string, title: string) => api<Conversation>(`${API_PREFIX}/conversations/${encodeURIComponent(id)}`, json("PATCH", { title })),
  delete: (id: string) => api<void>(`${API_PREFIX}/conversations/${encodeURIComponent(id)}`, json("DELETE")),
  send: (id: string, content: string) => api<{ conversation_id: string; user_message: Message; assistant_message: Message }>(`${API_PREFIX}/conversations/${encodeURIComponent(id)}/messages`, json("POST", { content })),
};

export const queryApi = {
  ask: (question: string, topK = 5) => api<{ answer: string; sources: SourceReference[] }>(`${API_PREFIX}/query`, json("POST", { question, top_k: topK })),
};

export function formatIst(value: string | null | undefined, dateOnly = false) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "—";
  return new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(dateOnly ? {} : { hour: "2-digit", minute: "2-digit", hour12: true }),
  }).format(parsed) + (dateOnly ? "" : " IST");
}

export function accountName(account: Pick<Account, "email" | "display_name">) {
  return account.display_name?.trim() || account.email.split("@")[0] || account.email;
}

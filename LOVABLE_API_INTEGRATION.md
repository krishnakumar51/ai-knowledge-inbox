# Lovable API integration: AI Knowledge Inbox

This is the API contract for a Lovable-generated React frontend. It describes the routes and schemas implemented in the FastAPI application. The local OpenAPI document is the source of truth for enum definitions and validation details:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

Do not put OpenRouter, database, or JWT signing secrets in Lovable or browser code.

## 1. Architecture

- **Frontend:** Lovable-generated React application, hosted separately.
- **Backend:** FastAPI, Python 3.12.
- **Database:** Neon PostgreSQL with pgvector; item vectors are 2048-dimensional.
- **Chat:** OpenRouter chat completions using the verified `openrouter/free` dynamic route. The underlying model can vary.
- **Embeddings:** OpenRouter `nvidia/nemotron-3-embed-1b:free`, 2048 dimensions. The chat and embedding model settings are separate.
- **Authentication:** email/password registration and login; bearer JWTs are signed by the backend.
- **API timezone:** response timestamps are ISO 8601 strings rendered in `Asia/Kolkata` with an offset such as `+05:30`.

The backend performs ingestion, URL fetching, extraction, chunking, embedding, retrieval, and answer generation. The browser sends source text and questions to the API; it must never call OpenRouter directly.

The selected route was tested with real completion requests: configured `openai/gpt-oss-120b:free` returned 404 as unavailable for free; `nvidia/nemotron-3-ultra-550b-a55b:free` and `nvidia/nemotron-3.5-super-vl:free` returned HTTP 200 but empty assistant text; `openrouter/free` returned usable assistant text and was selected. Its actual backing model is dynamic.

## 2. API configuration

```ts
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
export const API_PREFIX = "/api/v1";
```

`http://localhost:8000` is the local base URL. **Production base URL: `<BACKEND_DEPLOYMENT_URL_NOT_CONFIGURED>`**. Replace that placeholder with the deployed HTTPS origin after deployment; no production domain is configured yet.

Send JSON requests with `Content-Type: application/json`. Authenticated requests also send:

```http
Authorization: Bearer <access_token>
```

The API prefix is `/api/v1` for application routes. Health routes are at the origin root. CORS currently allows `http://localhost:3000`; set backend `CORS_ORIGINS` to the exact deployed Lovable origin before connecting a hosted frontend.

## 3. Authentication and errors

### Token schemas

Registration and login return:

```ts
type TokenResponse = {
  access_token: string;
  token_type: "bearer";
  expires_in: number; // seconds; configured default is 3600
};
```

Credentials use `{ "email": string, "password": string }`. Password length is 12–128 characters. Registration returns 201; login returns 200. Duplicate registration returns 409. Invalid credentials return 401. Auth configuration errors return 503.

There is no refresh-token endpoint. When a protected request returns 401, clear the token and send the user to login. Keep the token in memory or `sessionStorage` according to the frontend's threat model; avoid long-lived browser storage where practical. Never log or display the token.

Application errors generally use this envelope:

```ts
type ApiError = { error: { code: string; message: string; details?: unknown } };
```

Request validation errors return 422 with `error.code = "validation_error"` and field details. Database outages return 503 with a safe generic message. Provider rate limits and unavailable service return 503; other provider failures may return 502. A URL ingestion/extraction failure can return an error while leaving an item with `FAILED` status in the user's library.

## 4. Data types

```ts
type ItemStatus = "ACTIVE" | "PROCESSING" | "FAILED" | "ARCHIVED";
type SourceType = "note" | "url";

type Item = {
  id: string;
  title: string;
  content: string;
  source_type: SourceType;
  source_url: string | null;
  source_metadata: Record<string, unknown>;
  external_id: string | null;
  status: ItemStatus;
  error_message: string | null;
  created_at: string; // saved time, Asia/Kolkata offset
  updated_at: string; // Asia/Kolkata offset
  effective_at: string | null; // applicability time, Asia/Kolkata offset
};

type SourceReference = {
  item_id: string;
  title: string;
  source_url: string | null;
  chunk_id: string;
  excerpt: string;
  effective_at: string | null;
  created_at: string;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: SourceReference[] | null;
  created_at: string;
};

type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type ConversationDetail = Conversation & { messages: Message[] };
```

`ACTIVE` items are eligible for retrieval. `PROCESSING` means ingestion is underway; `FAILED` includes an `error_message`; `ARCHIVED` remains visible in item lists but is excluded from retrieval. `created_at` is when the backend saved the item. `effective_at` is when the source fact applies. Revision `changed_at` is when an edit snapshot was created; do not treat these timestamps as interchangeable.

## 5. Endpoint catalogue

All `/api/v1` paths below are exact. Every endpoint marked **Bearer** requires the authorization header. The backend scopes items, conversations, messages, revisions, and retrieval to that authenticated user.

### Health and AI diagnostics

| Method and path | Auth | Request / response | Purpose and errors |
|---|---|---|---|
| `GET /health` | No | Response `{ "status": "ok" }` | Process liveness only; does not test dependencies. |
| `GET /health/db` | No | `status`, `database_version`, `checks`; 503 when not ready | Checks database, pgvector, expected schema, 2048 vector dimension, and cascade relationship. |
| `GET /health/ai` | No | `provider`, `configuration_present`, `chat_model_configured`, `embedding_model_configured`, `provider_connectivity`, `chat_generation_test`, `chat_model`, `embedding_model`, `embedding_dimensions` | Read-only configuration view. Connectivity and generation show `not_tested`; a configured key alone is not a connectivity check. |
| `POST /health/ai/test` | Bearer | No body. Response includes `provider_connectivity`, `chat_generation_test`, `chat_model` | Explicitly sends a short diagnostic prompt to the configured model. May consume provider quota. Provider errors use the application error envelope. |

### Authentication

| Method and path | Auth | Request | Response |
|---|---|---|---|
| `POST /api/v1/auth/register` | No | `Credentials` | 201 `TokenResponse`; 409 duplicate; 422 invalid credentials; 503 auth setup missing. |
| `POST /api/v1/auth/login` | No | `Credentials` | 200 `TokenResponse`; 401 invalid email/password. |
| `GET /api/v1/auth/me` | Bearer | None | 200 `{ id, email, created_at }`; 401 missing/expired token. |

### Knowledge items

| Method and path | Auth | Request | Response |
|---|---|---|---|
| `POST /api/v1/ingest` | Bearer | `IngestRequest` below | 201 `{ id, title, status, chunk_count }`. URL fetch/extraction/provider errors return an application error; failed extraction may leave a `FAILED` item. |
| `GET /api/v1/items?offset=0&limit=50` | Bearer | Query: `offset >= 0`, `limit` 1–200 | 200 `{ items: Item[], total: number }`, including archived/failed items. |
| `GET /api/v1/items/{item_id}` | Bearer | UUID path | 200 `Item`; 404 missing or not owned. |
| `PATCH /api/v1/items/{item_id}` | Bearer | `ItemUpdate` below | 200 `Item`; 404 missing/not owned; 422 invalid update; 502/503 provider or extraction failure. Failed reprocessing preserves existing content/chunks. |
| `DELETE /api/v1/items/{item_id}` | Bearer | UUID path | 204 empty body; 404 missing/not owned. Chunks and revisions cascade-delete. |
| `GET /api/v1/items/{item_id}/history` | Bearer | UUID path | 200 `ItemRevision[]`; 404 missing/not owned. |
| `GET /api/v1/items/{item_id}/history/{revision_id}` | Bearer | UUID paths | 200 `ItemRevision`; 404 missing/not owned. |
| `POST /api/v1/items/{item_id}/restore/{revision_id}` | Bearer | UUID paths; no body | 200 restored `Item`; 404 missing; 422 invalid restore; 502/503 if fresh embeddings cannot be generated. Restore creates a new revision. |

`IngestRequest` fields:

```ts
type IngestRequest = {
  source_type: "note" | "url";
  title?: string | null;             // up to 500 chars
  content?: string | null;           // required for notes
  source_url?: string | null;        // required for URLs; `url` is also accepted
  effective_at?: string | null;      // ISO date-time with explicit offset
  source_metadata?: Record<string, unknown>;
};
```

`ItemUpdate` accepts any subset of `title`, `content`, `effective_at`, `source_url`, `source_metadata`, and `status`. Effective timestamps must include an offset. `status` can be set to `ACTIVE` or `ARCHIVED`; clients cannot set `PROCESSING` or `FAILED`. Changing URL re-fetches and extracts it. Changing content re-chunks and re-embeds it. Metadata/title/date-only edits do not need a new embedding.

`ItemRevision` fields are `id`, `item_id`, `revision_number`, `title_snapshot`, `content_snapshot`, `source_type_snapshot`, `source_url_snapshot`, `source_metadata_snapshot`, `effective_at_snapshot`, `status_snapshot`, `change_type`, `changed_at`, and `change_summary`.

### Search and RAG chat

| Method and path | Auth | Request | Response |
|---|---|---|---|
| `POST /api/v1/query` | Bearer | `{ question: string, top_k?: number }`; question 1–4000 chars, top_k 1–20 | 200 `{ answer: string, sources: SourceReference[] }`; provider errors use safe application errors. |

There is no separate temporal-search endpoint. Ask temporal questions through `/api/v1/query` or conversation messages. The backend filters/ranks retrieved active items according to the question's current, historical, future, or timeline intent. If no relevant saved context is retrieved, the API returns an insufficient-knowledge response with `sources: []`.

The assistant answer converts valid `[1]` citation labels to `[<item UUID>]` and removes labels that do not refer to retrieved sources. Render the corresponding `sources` array alongside the answer. `SourceReference.created_at` is save time; `effective_at` is applicability time; both are returned in IST. `source_url` can be null.

### Persistent conversations

| Method and path | Auth | Request | Response |
|---|---|---|---|
| `POST /api/v1/conversations` | Bearer | `{ title?: string }`, default `New conversation`, 1–300 chars | 201 `Conversation`. |
| `GET /api/v1/conversations` | Bearer | None | 200 `Conversation[]`, most recently updated first. |
| `GET /api/v1/conversations/{conversation_id}` | Bearer | UUID path | 200 `ConversationDetail`; 404 missing/not owned. |
| `DELETE /api/v1/conversations/{conversation_id}` | Bearer | UUID path | 204 empty body; messages cascade-delete; 404 missing/not owned. |
| `POST /api/v1/conversations/{conversation_id}/messages` | Bearer | `{ content: string }`, 1–4000 chars | 200 `{ conversation_id, user_message: Message, assistant_message: Message }`; 404 missing/not owned; 502/503 provider errors. |

The user message is saved before provider work begins. If embedding or generation fails, the API returns an error and keeps the submitted user message; it does not create a fabricated assistant response. A retry is a new message, so the UI should make that behavior clear.

## 6. TypeScript API client examples

```ts
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const API_PREFIX = "/api/v1";

function token(): string | null {
  return sessionStorage.getItem("aki_access_token");
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body) headers.set("Content-Type", "application/json");
  const accessToken = token();
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) sessionStorage.removeItem("aki_access_token");
    const message = body?.error?.message ?? `Request failed (${response.status})`;
    throw Object.assign(new Error(message), { status: response.status, body });
  }
  return body as T;
}

type TokenResponse = { access_token: string; token_type: "bearer"; expires_in: number };
type SourceReference = {
  item_id: string; title: string; source_url: string | null; chunk_id: string;
  excerpt: string; effective_at: string | null; created_at: string;
};
type Message = {
  id: string; role: "user" | "assistant"; content: string;
  citations: SourceReference[] | null; created_at: string;
};
type Item = {
  id: string; title: string; content: string; source_type: "note" | "url";
  source_url: string | null; source_metadata: Record<string, unknown>;
  external_id: string | null; status: "ACTIVE" | "PROCESSING" | "FAILED" | "ARCHIVED";
  error_message: string | null; created_at: string; updated_at: string; effective_at: string | null;
};

async function register(email: string, password: string) {
  const auth = await api<TokenResponse>(`${API_PREFIX}/auth/register`, {
    method: "POST", body: JSON.stringify({ email, password }),
  });
  sessionStorage.setItem("aki_access_token", auth.access_token);
  return auth;
}

async function login(email: string, password: string) {
  const auth = await api<TokenResponse>(`${API_PREFIX}/auth/login`, {
    method: "POST", body: JSON.stringify({ email, password }),
  });
  sessionStorage.setItem("aki_access_token", auth.access_token);
  return auth;
}

const me = () => api<{ id: string; email: string; created_at: string }>(`${API_PREFIX}/auth/me`);
const items = () => api<{ items: Item[]; total: number }>(`${API_PREFIX}/items?offset=0&limit=50`);

const createNote = (title: string, content: string) => api<{ id: string; title: string; status: string; chunk_count: number }>(
  `${API_PREFIX}/ingest`, { method: "POST", body: JSON.stringify({ source_type: "note", title, content }) },
);

const ingestUrl = (url: string) => api<{ id: string; title: string; status: string; chunk_count: number }>(
  `${API_PREFIX}/ingest`, { method: "POST", body: JSON.stringify({ source_type: "url", url }) },
);

const updateItem = (id: string, update: Partial<Pick<Item, "title" | "content" | "source_url" | "source_metadata" | "effective_at" | "status">>) =>
  api<Item>(`${API_PREFIX}/items/${id}`, { method: "PATCH", body: JSON.stringify(update) });

const deleteItem = (id: string) => api<void>(`${API_PREFIX}/items/${id}`, { method: "DELETE" });

const createConversation = (title = "New conversation") =>
  api<{ id: string; title: string; created_at: string; updated_at: string }>(
    `${API_PREFIX}/conversations`, { method: "POST", body: JSON.stringify({ title }) },
  );

const listConversations = () => api<Array<{ id: string; title: string; created_at: string; updated_at: string }>>(
  `${API_PREFIX}/conversations`,
);

const loadConversation = (id: string) => api<{
  id: string; title: string; created_at: string; updated_at: string; messages: Message[];
}>(`${API_PREFIX}/conversations/${id}`);

const sendMessage = (conversationId: string, content: string) => api<{
  conversation_id: string; user_message: Message; assistant_message: Message;
}>(`${API_PREFIX}/conversations/${conversationId}/messages`, {
  method: "POST", body: JSON.stringify({ content }),
});
```

For a stateless RAG query, call `POST /api/v1/query` with `{ "question": "...", "top_k": 5 }`; `top_k` is optional. The response is `{ "answer": string, "sources": SourceReference[] }`.

## 7. UI behavior guidance

- Use the bearer token for every protected route. On 401, clear it and return to login. There is no refresh route.
- Display request-level loading states. Ingestion and chat make upstream/provider calls and can take several seconds.
- After a URL-ingest error, refresh the item list. A failed fetch may have persisted an item with status `FAILED` and a useful `error_message`; ingestion errors do not return the failed item's ID.
- Render item status badges. `ACTIVE` is searchable, `ARCHIVED` is retained but not searchable, and `FAILED` should expose the item's `error_message`. Poll `GET /api/v1/items/{id}` only when the returned state is `PROCESSING`.
- Show archived items in the library with an explicit reactivation action (`PATCH` status `ACTIVE`).
- Display answer sources from the returned `sources`, and message sources from `assistant_message.citations`. The backend's answer text uses `[item UUID]`; map that ID to the supplied citation cards. Show title, excerpt, URL when present, applicability (`effective_at`), and saved time (`created_at`).
- Render server timestamps as returned, or parse them as offset-aware values and format in `Asia/Kolkata`. Do not append a second timezone conversion to an already-local wall-clock string.
- Display messages from `GET /api/v1/conversations/{id}` in order. If sending returns a provider error, the user message remains saved; reload conversation history and offer a retry as a new message.
- If a query returns `sources: []`, show the answer as an insufficient-saved-context result. An empty library should offer note creation and URL ingestion instead of showing a blank chat error.
- Handle 409 duplicate registration, 422 validation, 404 missing/foreign resources, 503 rate limits/provider unavailability, and 502 provider failures with clear recoverable UI. Do not expose raw backend traces.

## 8. Example workflows

### Register → login → dashboard

1. `POST /api/v1/auth/register` with email/password; save `access_token` in session state.
2. Existing accounts use `POST /api/v1/auth/login`.
3. Call `GET /api/v1/auth/me`, then `GET /api/v1/items` and `GET /api/v1/conversations`.

### Create and view a note

1. `POST /api/v1/ingest` with `{ "source_type":"note", "title":"Rust", "content":"Rust uses ownership and borrowing to enforce memory safety." }`.
2. Read the returned `id`, `status`, and `chunk_count`.
3. Call `GET /api/v1/items/{id}` to view the saved note.

### Ingest a URL and inspect status

1. `POST /api/v1/ingest` with `{ "source_type":"url", "url":"https://example.com/article" }`.
2. On success, use returned `id` with `GET /api/v1/items/{id}` to inspect extracted title/content.
3. If the request returns an extraction error, refresh `GET /api/v1/items` and locate the matching `source_url` with `status: "FAILED"`.

### Edit and inspect revisions

1. `PATCH /api/v1/items/{id}` with `{ "content":"Updated saved fact." }` or metadata fields.
2. `GET /api/v1/items/{id}/history` to list snapshots.
3. `GET /api/v1/items/{id}/history/{revision_id}` to inspect a snapshot.

### Start conversation and ask with citations

1. `POST /api/v1/conversations` with `{ "title":"Research" }`.
2. `POST /api/v1/conversations/{conversation_id}/messages` with `{ "content":"What did I save about Rust?" }`.
3. Render `assistant_message.content` and citation cards from `assistant_message.citations`.
4. Reload with `GET /api/v1/conversations/{conversation_id}`.

### Ask a historical question

Use the same messages endpoint with a question such as `What was the earlier decision on November 10, 2026?`. The backend applies its temporal retrieval behavior and returns citations with both `effective_at` and `created_at`.

### Restore an older revision

1. Load history using `GET /api/v1/items/{id}/history`.
2. Ask the user which snapshot to restore.
3. `POST /api/v1/items/{id}/restore/{revision_id}` with no body; refresh the item and history afterward.

## 9. CORS and deployment

Current CORS origin is `http://localhost:3000` (from the local backend configuration). Before deployment, set `CORS_ORIGINS` to the exact Lovable-hosted frontend origin and redeploy the API. Configure at least:

- `DATABASE_URL` (Neon PostgreSQL URL)
- `JWT_SECRET_KEY` (random secret, 32+ characters)
- `OPENROUTER_API_KEY`
- `OPENROUTER_CHAT_MODEL` (currently `openrouter/free`)
- `OPENROUTER_EMBEDDING_MODEL` (currently `nvidia/nemotron-3-embed-1b:free`)
- `OPENROUTER_BASE_URL`
- `EMBEDDING_DIMENSIONS=2048`
- `APP_TIMEZONE=Asia/Kolkata`
- `CORS_ORIGINS`

Do not place `OPENROUTER_API_KEY`, `DATABASE_URL`, or `JWT_SECRET_KEY` in Lovable environment variables exposed to browser code. The frontend only needs the deployed API origin. No production backend domain has been assigned yet.

## 10. Features not exposed as dedicated routes

- Temporal search is part of `/api/v1/query` and conversation message generation; there is no separate temporal-search endpoint.
- Historical JSON dataset import is a backend script, not an HTTP endpoint.
- Chunk/embedding administration is internal; source excerpts are returned as citations.
- There is no JWT refresh route and no dedicated item-status route; use item GET/list responses.

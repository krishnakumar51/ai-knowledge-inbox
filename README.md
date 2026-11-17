# AI Knowledge Inbox

A multi-user RAG backend using FastAPI, SQLAlchemy 2, PostgreSQL/pgvector, and OpenRouter for embeddings and answer generation. Docker files remain available for future use; local Python development does not require Docker.

## Windows Python setup

Open PowerShell in the repository root:

```powershell
cd D:\ai-knowledge-inbox\backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip

# Only needed if Windows Application Control blocks SQLAlchemy's optional .pyd files:
$env:DISABLE_SQLALCHEMY_CEXT = "1"
python -m pip install --no-binary=sqlalchemy "SQLAlchemy>=2.0,<2.1"
Remove-Item Env:DISABLE_SQLALCHEMY_CEXT

python -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set `DATABASE_URL` in `backend/.env` using one of the database scenarios below. If no database is configured, FastAPI, docs, health, and unit tests still run; database routes and `/health/db` report that the database is unavailable.

## Scenario A: hosted PostgreSQL + pgvector

Use the direct PostgreSQL connection URL from your database provider. It must allow network access from this machine and have pgvector installed. Set the value in `backend/.env`, for example:

```dotenv
DATABASE_URL=postgresql+asyncpg://DB_USER:URL_ENCODED_PASSWORD@DB_HOST:5432/DB_NAME?ssl=require
```

Use the provider's required TLS mode and URL-encode reserved characters in the username or password. A standard `postgresql://...` URL is also accepted and converted to the asyncpg driver. Run migrations and start the server from `backend/`:

For Alembic, use Neon's **direct** endpoint (hostname without `-pooler`) and select/generate a URL compatible with asyncpg. This project uses asyncpg; asyncpg currently disables SCRAM channel binding, so `channel_binding=require` is rejected explicitly rather than silently ignored. Keep TLS enabled with `sslmode=require` (normalized to asyncpg's `ssl=require`). See [asyncpg's connection API](https://magicstack.github.io/asyncpg/current/api/index.html) and [SCRAM implementation notes](https://github.com/MagicStack/asyncpg/blob/master/asyncpg/protocol/scram.pyx).

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://DB_USER:URL_ENCODED_PASSWORD@DB_HOST:5432/DB_NAME?ssl=require"
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

## Scenario B: PostgreSQL installed on Windows

Install PostgreSQL 16 and the Visual Studio C++ tools first. pgvector's upstream Windows instructions build against the matching PostgreSQL installation. In an **x64 Native Tools Command Prompt for Visual Studio**, run as administrator:

```bat
set "PGROOT=C:\Program Files\PostgreSQL\16"
cd %TEMP%
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
nmake /F Makefile.win
nmake /F Makefile.win install
```

The upstream instructions require the C++ workload and a matching `PGROOT`; see [pgvector's Windows installation notes](https://github.com/pgvector/pgvector#installation). Start the PostgreSQL service installed on your machine (the common service name for this release is shown below), then create the development database:

```powershell
Start-Service postgresql-x64-16
psql -U postgres -c "CREATE DATABASE knowledge_inbox OWNER postgres;"
psql -U postgres -d knowledge_inbox -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

If your PostgreSQL installer uses another service name, find it with `Get-Service *postgres*`. Set `DATABASE_URL` in `backend/.env` to match the password configured for the local `postgres` role:

```dotenv
DATABASE_URL=postgresql+asyncpg://postgres:URL_ENCODED_PASSWORD@localhost:5432/knowledge_inbox
```

Then, from `backend/`:

```powershell
python -m alembic upgrade head
python -m uvicorn app.main:app --reload
```

The migrations create the vector extension if needed, the item, chunk, user, conversation, and revision tables, and the indexes. The current embedding column uses 2048-dimensional vectors. It requires a database role allowed to create extensions and tables.

## Diagnostics and local checks

With the venv active and current directory `backend/`:

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/health/db
ruff check app tests alembic scripts
python -m compileall -q app alembic tests scripts
pytest
```

`/health` is a lightweight process check and does not connect to PostgreSQL or OpenRouter. `/health/db` checks connection, PostgreSQL version, pgvector, expected tables, the vector dimension, and item-to-chunk cascade. Its response never includes the connection URL or password. Neither provider client nor model is contacted during FastAPI startup.

## Windows SQLAlchemy compatibility

SQLAlchemy's C extensions are optional. If an installed wheel's `.pyd` files are blocked, the setup commands above build SQLAlchemy from source with `DISABLE_SQLALCHEMY_CEXT=1`; the variable is only for installation and does not weaken Windows security. See [SQLAlchemy 2.0's Cython extension instructions](https://docs.sqlalchemy.org/en/20/intro.html#building-the-cython-extensions).

## API

- `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `POST /api/v1/ingest`: requires a bearer token. Note body `{ "source_type": "note", "title": "...", "content": "...", "effective_at": "2026-11-10T00:00:00Z" }`; URL body `{ "source_type": "url", "url": "https://..." }`. `effective_at` is optional and is never inferred from the edit date. `source_url` is accepted as an alias for `url`.
- `GET /api/v1/items`, `GET /api/v1/items/{item_id}`, `PATCH /api/v1/items/{item_id}`, `DELETE /api/v1/items/{item_id}` all require a bearer token and are scoped to its owner. Changed content is rechunked and re-embedded; replacement is transactional.
- `POST /api/v1/query`: requires a bearer token; vector and keyword retrieval both filter by owner in SQL.
- `GET /api/v1/items/{item_id}/history`, `GET /api/v1/items/{item_id}/history/{revision_id}`, and `POST /api/v1/items/{item_id}/restore/{revision_id}` provide owner-scoped edit history and restore. Item status is `ACTIVE`, `PROCESSING`, `FAILED`, or `ARCHIVED`; only `ACTIVE` items are retrieved.
- `POST /api/v1/conversations`, `GET /api/v1/conversations`, `GET /api/v1/conversations/{id}`, `DELETE /api/v1/conversations/{id}`
- `POST /api/v1/conversations/{id}/messages`: stores user and assistant messages separately from knowledge items. Prior turns can clarify follow-ups but are not treated as evidence.
- `GET /health`, `GET /health/db`, `GET /health/ai`, `POST /health/ai/test`

Set `JWT_SECRET_KEY` in `backend/.env` to a random value of at least 32 characters before using auth. To generate one locally, run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and put the result in the ignored `.env` file. Passwords use Python's built-in scrypt implementation; passwords must be at least 12 characters. The app can still start and health/docs remain available when this key is absent, while auth requests return a configuration error. Set `OPENROUTER_API_KEY` locally. Chat and embeddings have separate model settings:

```dotenv
OPENROUTER_CHAT_MODEL=openrouter/free
OPENROUTER_EMBEDDING_MODEL=nvidia/nemotron-3-embed-1b:free
EMBEDDING_DIMENSIONS=2048
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
```

`openrouter/free` returned usable assistant text in a real request with the configured key. It is a dynamic router and the underlying model can change. The requested `openai/gpt-oss-120b:free` returned 404 as unavailable for free. The suggested NVIDIA chat slugs returned HTTP 200 with empty assistant text during checks, so they were not selected. The Nemotron embedding setting remains unchanged.

Phase 6 migration `0002_users_temporal_chat` adds users, ownership, optional applicability dates, conversations, and messages without dropping existing items or chunks. The Neon migration was run after confirming there were no existing items/chunks. If another database has ownerless items, the migration stops unless `MIGRATION_OWNER_EMAIL` and `MIGRATION_OWNER_PASSWORD_HASH` are explicitly configured. Generate the initial hash without echoing the password using `python -c "from getpass import getpass; from app.core.security import hash_password; print(hash_password(getpass('Initial owner password: ')))"`, set those two variables, then retry the migration. Do not set an owner implicitly.

Temporal ordering follows relevance first. Current questions prefer newer items only among near-equal relevance candidates; explicit dates filter to information applicable/saved by that date, while timeline questions list retrieved items in chronological order. A missing `effective_at` remains labeled as unsupplied; `created_at` is shown separately as the saved date.

OpenAPI docs are at <http://localhost:8000/docs>. To submit the reusable six-note dataset through the HTTP API, run `python scripts/ingest_sample_notes.py` from `backend/`; set `$env:API_BASE_URL` if the server uses another address.

### Timestamped imports and temporal evaluation

All timestamps returned by the API are rendered in `APP_TIMEZONE` (default `Asia/Kolkata`). API-supplied `effective_at` values must carry an explicit timezone offset. Historical dataset imports may contain naive `created_at` or `effective_at` values; those are interpreted in the configured application timezone and stored as UTC. The historical importer uses the normal ingestion service, embeddings, chunking, ownership, and revision logic. It only imports records for an existing user and skips duplicate `(user, dataset_id, external_id)` records.

From `backend/`, preview the included historical dataset, then import it:

```powershell
python scripts/ingest_json_dataset.py --file testdata/temporal_rag_dataset.json --dry-run
python scripts/ingest_json_dataset.py --file testdata/temporal_rag_dataset.json
```

The import file contains sample data for `test-user@example.com`; register that account first or change `user_email` to an existing account. Run the API and evaluate against the authenticated user's imported items:

```powershell
python scripts/evaluate_temporal_queries.py --email test-user@example.com
```

The evaluation prompts for the account password without echoing it and reports retrieved expected source recall plus expected answer facts. It does not print the bearer token. Example note ingestion request:

```powershell
$token = (Invoke-RestMethod -Method Post http://localhost:8000/api/v1/auth/login -ContentType 'application/json' -Body '{"email":"you@example.com","password":"your-long-password"}').access_token
Invoke-RestMethod -Method Post http://localhost:8000/api/v1/ingest -Headers @{ Authorization = "Bearer $token" } -ContentType 'application/json' -Body '{"source_type":"note","title":"Rust and AI Infrastructure","content":"Rust provides memory safety without requiring a garbage collector. It is useful for building high-performance infrastructure where predictable memory management is important."}'
```

Migration `0003_models_history_status_ist` updates the vector dimension and adds metadata, statuses, and revision snapshots. It stops before changing the vector column if chunks already exist because old 384-dimensional embeddings cannot be cast into 2048 dimensions; in that case re-embed into a staged column before a forward migration. The HNSW index uses a `halfvec(2048)` expression because pgvector HNSW limits `vector` indexes to 2000 dimensions; retrieval ranks candidates with that index and computes returned similarity from full precision vectors.

The embedding endpoint and live chat flow have both been verified. Chat tests use the free `openrouter/free` route; its backing model can vary, availability and rate limits are controlled by OpenRouter, and rate limits are returned by this API as HTTP 503. `GET /health/ai` reports configuration and explicitly marks connectivity and generation as `not_tested`; it does not infer connectivity from the presence of a key. An authenticated `POST /health/ai/test` makes a real short provider request and may consume provider quota. Use it only when an explicit diagnostic is desired.

Run an authenticated chat smoke test after registering and logging in, using the returned access token:

```powershell
$token = (Invoke-RestMethod -Method Post http://localhost:8000/api/v1/auth/login -ContentType 'application/json' -Body '{"email":"you@example.com","password":"your-long-password"}').access_token
Invoke-RestMethod -Method Post http://localhost:8000/health/ai/test -Headers @{ Authorization = "Bearer $token" }
```

For Lovable frontend implementation, use [`LOVABLE_API_INTEGRATION.md`](LOVABLE_API_INTEGRATION.md). It is derived from the actual FastAPI routes and OpenAPI schema and does not contain credentials.

## Docker files (optional)

The Dockerfile and Compose file are retained for later use. Compose now requires database values through environment variables instead of embedding credentials. To run it, copy `backend/.env.example` to both `backend/.env` and the repository-root `.env`, set the Compose variables in the root copy, and then use `docker compose up --build`. Docker is not part of the direct Windows setup above.

## Configuration

See [`backend/.env.example`](backend/.env.example). `DATABASE_URL` has no application default. `LLM_PROVIDER` accepts only `openrouter`. `OPENROUTER_CHAT_MODEL` and `OPENROUTER_EMBEDDING_MODEL` are independent settings; the browser must never receive `OPENROUTER_API_KEY`.

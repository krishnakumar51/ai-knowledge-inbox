# AI Knowledge Inbox — frontend

React 19 + TanStack Start (Vite, Nitro) + Tailwind CSS. See the [root README](../README.md) for setup, environment variables and deployment.

```bash
bun install            # uses bun.lock
cp .env.example .env.local
bun run dev            # http://localhost:5173
bun run build
```

The only variable is `VITE_API_BASE_URL` (public; the backend URL). It is read at build time.

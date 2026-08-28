# Deploy MCP Brain to Railway

## Context
MCP Brain runs locally on `localhost:8080` (Python FastMCP server) and `localhost:3000` (Vite frontend). We need to deploy to a real URL so MCP clients (Claude Desktop, Cursor, etc.) can connect remotely. Railway was chosen for its simplicity (git push deploy), SSE/WebSocket support (needed for MCP streamable-http), and $5/mo free credits.

## Pre-requisites
- Railway account (https://railway.app)
- Railway CLI installed (`npm i -g @railway/cli` or `brew install railway`)

---

## Step 1: Install Railway CLI & Login
```bash
npm i -g @railway/cli
railway login
```

## Step 2: Create Railway Project & Deploy Backend
```bash
railway init          # Create project, link to repo
railway up            # Deploy using existing Dockerfile
```
Railway auto-detects the `Dockerfile`, builds, and deploys. The server exposes port 8080 — Railway maps this to a public `*.up.railway.app` URL.

## Step 3: Configure Environment Variables on Railway

Set these via `railway variables set` or the Railway dashboard:

| Variable | Value | Notes |
|----------|-------|-------|
| `SUPABASE_URL` | `https://hrcogpdvxmpczsyeofnm.supabase.co` | |
| `SUPABASE_ANON_KEY` | (from .env) | |
| `SUPABASE_DB_URL` | `postgresql://postgres:...@db.hrcogpdvxmpczsyeofnm.supabase.co:5432/postgres?sslmode=require` | Add `?sslmode=require` |
| `OPENAI_API_KEY` | (from .env) | |
| `PORT` | `8080` | Railway injects `PORT` automatically, but we set it explicitly |
| `HOST` | `0.0.0.0` | |
| `ENVIRONMENT` | `production` | |
| `BASE_URL` | `https://<app>.up.railway.app` | Set AFTER first deploy to get the URL |

## Step 4: Update BASE_URL After First Deploy
After the first deploy, Railway assigns a public URL. Update:
1. `railway variables set BASE_URL=https://<app>.up.railway.app`
2. This triggers a redeploy automatically

## Step 5: Update Supabase OAuth Configuration
In Supabase Dashboard → Authentication → URL Configuration:
- **Site URL**: `https://<frontend-url>` (wherever frontend is hosted)
- **Redirect URLs**: Add `https://<app>.up.railway.app/callback`

In Supabase Dashboard → Authentication → OAuth 2.1 Server:
- Verify Authorization Path is set to `/oauth/consent`
- The SupabaseProvider in FastMCP will use the Railway BASE_URL for OAuth metadata

## Step 6: Deploy Frontend
Two options:

**Option A: Vercel/Netlify (simplest for SPA)**
```bash
cd frontend
npx vercel --prod    # or netlify deploy --prod
```
Set env vars: `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`

**Option B: Railway (same project, second service)**
Add a second service in Railway pointing to `frontend/` with Dockerfile:
```dockerfile
FROM node:20-slim AS build
WORKDIR /app
COPY package.json bun.lockb ./
RUN npm i -g bun && bun install
COPY . .
RUN bun run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

## Step 7: Update MCP Client Configs
After deploy, clients connect to the production URL:
```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "https://<app>.up.railway.app/mcp"
    }
  }
}
```

## Step 8: Verify End-to-End
1. `curl https://<app>.up.railway.app/mcp` → should return auth challenge (401)
2. Check Railway logs: `railway logs`
3. Test MCP connection from Claude Code with production URL
4. Verify OAuth flow works (login → consent → token → tool call)

---

## Files Modified
- None needed for basic deploy (Dockerfile + env vars handle everything)
- Optional: Add `railway.json` for explicit config (port, build settings)

## Risks
- **Cold starts**: Railway keeps services running on paid plans, not an issue
- **DB connection pooling**: asyncpg pool (min=2, max=10) works fine for single instance
- **Rate limiting**: In-memory rate limiter resets on deploy — acceptable for now, Redis-backed later if needed
- **SSL**: Adding `?sslmode=require` to DB URL secures the Postgres connection

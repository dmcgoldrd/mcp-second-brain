# Architecture

MCP Brain is a personal AI memory service that provides persistent memory across all AI platforms via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). Users store, search, and manage memories through any MCP-compatible client (Claude Code, Claude Desktop, Cursor, etc.).

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                       MCP Clients                           │
│   Claude Code  /  Claude Desktop  /  Cursor  /  any MCP     │
└──────────────────────────┬──────────────────────────────────┘
                           │  POST /mcp/
                           │  Authorization: Bearer <supabase-jwt>
                           │  x-bank-slug: <slug>  (optional)
                           ▼
┌─────────────────────────────────────────────────────────────┐
│            FastMCP Server  (uvicorn + Starlette)            │
│                                                             │
│  OAuth Metadata:                                            │
│    GET /.well-known/oauth-authorization-server               │
│    GET /.well-known/oauth-protected-resource                 │
│                                                             │
│  MCP Endpoint:                                              │
│    POST /mcp/  (Streamable HTTP transport)                   │
│                                                             │
│  Auth: MCPBrainAuthProvider (SupabaseProvider subclass)      │
│    → JWT validation via Supabase JWKS                       │
│    → _resolve_auth(token) → {user_id, bank_id}             │
│                                                             │
│  7 MCP Tools:                                               │
│    create_memory  search_memories  list_memories             │
│    delete_memory  brain_stats  list_banks  create_bank       │
│                                                             │
│  Rate Limiting:                                             │
│    tool_limiter    (60/min burst, 1/sec sustained)          │
│    embedding_limiter (30/min burst, 0.5/sec sustained)      │
└───────────┬──────────────────────────┬──────────────────────┘
            │                          │
            ▼                          ▼
  ┌──────────────────┐   ┌──────────────────────────────────┐
  │   OpenAI API     │   │   Supabase Postgres  (asyncpg)   │
  │                  │   │                                  │
  │  text-embedding  │   │  Tables:                         │
  │  -3-small        │   │    memories  (pgvector HNSW)     │
  │  1536 dims       │   │    banks     (per-user)          │
  │                  │   │    profiles  (memory_count)      │
  │                  │   │    subscriptions (Stripe)        │
  │                  │   │                                  │
  │                  │   │  Function:                       │
  │                  │   │    hybrid_search()  (RRF)        │
  └──────────────────┘   └──────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────┐
  │              Frontend  (Vite + TypeScript)               │
  │   Hash SPA: #/login  #/signup  #/dashboard              │
  │   Supabase JS client for auth + direct DB queries       │
  │   Dashboard: profile, connect instructions, banks       │
  └─────────────────────────────────────────────────────────┘
```

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| MCP Server | [FastMCP](https://github.com/jlowin/fastmcp) 2.x | MCP protocol, HTTP transport, auth framework |
| Database | Supabase Postgres + asyncpg | User data, memories, banks, subscriptions |
| Vector Search | pgvector 0.8.0 (HNSW) | Semantic similarity search |
| Embeddings | OpenAI `text-embedding-3-small` | 1536-dimensional vectors |
| Auth | Supabase Auth + FastMCP SupabaseProvider | JWT validation, JWKS |
| HTTP Client | httpx | OIDC metadata fetching |
| Frontend | Vite 6.2 + TypeScript 5.7 | Dashboard SPA |
| Package Manager | uv (Python), bun (frontend) | Dependency management |

## Component Overview

### `src/main.py` — Entry Point
Starts the FastMCP server with Streamable HTTP transport on the configured host/port.

### `src/server.py` — MCP Server
Core module. Creates the `FastMCP` instance with auth, defines all 7 MCP tools, and houses `_resolve_auth()` which extracts `user_id` from the JWT and resolves `bank_id` from headers.

### `src/auth/provider.py` — Auth Provider
`MCPBrainAuthProvider` subclasses FastMCP's `SupabaseProvider` to fix the `/.well-known/oauth-authorization-server` endpoint. Supabase returns 404 for this URL, so the provider constructs RFC 8414 metadata from Supabase's OIDC discovery endpoint instead.

### `src/tools/memory_tools.py` — Business Logic
Orchestrates the pipeline for each tool: subscription limit checks, embedding rate limiting, OpenAI embedding generation, metadata extraction, type classification, and database operations.

### `src/db/` — Database Layer
- **`connection.py`** — asyncpg connection pool (min=2, max=10) with pgvector codec registration
- **`memories.py`** — CRUD for the `memories` table (create, search, list, delete, stats)
- **`banks.py`** — CRUD for the `banks` table (list, get by slug, get default, create)
- **`profiles.py`** — Profile and subscription queries

### `src/embeddings.py` — Vector Embeddings
Singleton `AsyncOpenAI` client that generates 1536-dimensional embeddings via `text-embedding-3-small`.

### `src/metadata.py` — Metadata Enrichment
Heuristic extraction (URLs, @mentions, dates, word count) and keyword-based memory type classification. No LLM calls — fast and deterministic. AI clients provide richer metadata via the `metadata` tool parameter.

### `src/ratelimit.py` — Rate Limiting
In-memory token bucket algorithm. Per-user isolation. Two global instances: `tool_limiter` (60/min) and `embedding_limiter` (30/min).

### `src/config.py` — Configuration
Loads all environment variables from `.env` via `python-dotenv`. Fails fast with `KeyError` if required vars are missing.

## Request Lifecycle

```
1. MCP client sends POST /mcp/ with Bearer JWT and optional x-bank-slug header
2. FastMCP routes to MCPBrainAuthProvider (SupabaseProvider)
3. SupabaseProvider validates JWT against Supabase JWKS (ES256)
4. AccessToken injected into tool function via CurrentAccessToken()
5. _resolve_auth(token):
   a. Extract user_id from token.claims["sub"]
   b. Check tool_limiter.check(user_id)
   c. Resolve bank_id from x-bank-slug header or default bank
6. Tool function executes business logic via memory_tools
7. memory_tools orchestrates: limit checks → embedding → metadata → DB
8. JSON result returned to MCP client
```

## Source File Map

```
src/
├── main.py                 # Entry point
├── server.py               # FastMCP server + 7 tools + _resolve_auth
├── config.py               # Environment variables
├── embeddings.py           # OpenAI embedding generation
├── metadata.py             # Heuristic metadata extraction + type classification
├── ratelimit.py            # Token bucket rate limiter
├── auth/
│   ├── provider.py         # MCPBrainAuthProvider (SupabaseProvider subclass)
│   ├── jwt.py              # Standalone JWT validation (PyJWKClient)
│   └── middleware.py        # Legacy JWTAuthMiddleware (not currently used)
├── db/
│   ├── connection.py       # asyncpg pool with pgvector
│   ├── memories.py         # Memory CRUD
│   ├── banks.py            # Bank CRUD
│   └── profiles.py         # Profile/subscription queries
└── tools/
    └── memory_tools.py     # Business logic layer
```

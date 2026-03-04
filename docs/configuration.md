# Configuration

MCP Brain uses environment variables loaded from a `.env` file via `python-dotenv`. Configuration is defined in `src/config.py`.

## Required Environment Variables

These variables must be present. The server will crash with `KeyError` at startup if any are missing.

| Variable | Description | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Supabase project URL | `https://xxxx.supabase.co` |
| `SUPABASE_ANON_KEY` | Supabase anonymous/public key | `eyJhbGciOiJIUzI1Ni...` |
| `SUPABASE_DB_URL` | Direct Postgres connection string | `postgresql://postgres:pass@db.xxxx.supabase.co:5432/postgres` |
| `OPENAI_API_KEY` | OpenAI API key for embeddings | `sk-proj-...` |

## Optional Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SUPABASE_SERVICE_ROLE_KEY` | `""` | Supabase service role key (for admin operations) |
| `SUPABASE_JWKS_URL` | `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` | JWKS endpoint for JWT validation |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Embedding vector dimensions |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8080` | Server bind port |
| `ENVIRONMENT` | `development` | Environment name |
| `FREE_MEMORY_LIMIT` | `1000` | Max memories for free users |
| `FREE_RETRIEVAL_LIMIT` | `500` | Max retrievals for free users |
| `PAID_MEMORY_LIMIT` | `50000` | Max memories for paid users |
| `MAX_CONTENT_LENGTH` | `50000` | Max memory content length in characters (~50KB) |

## `.env` Template

```env
# Required
SUPABASE_URL=https://xxxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_DB_URL=postgresql://postgres:your-password@db.xxxx.supabase.co:5432/postgres
OPENAI_API_KEY=sk-proj-...

# Optional
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
HOST=0.0.0.0
PORT=8080
ENVIRONMENT=development
FREE_MEMORY_LIMIT=1000
PAID_MEMORY_LIMIT=50000
MAX_CONTENT_LENGTH=50000
```

## Frontend Environment Variables

The frontend (Vite) uses its own env vars prefixed with `VITE_`:

| Variable | Description | Example |
|----------|-------------|---------|
| `VITE_SUPABASE_URL` | Supabase project URL | `https://xxxx.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Supabase anonymous key | `eyJhbGciOiJIUzI1Ni...` |
| `VITE_MCP_URL` | MCP server URL (optional, defaults to `http://localhost:8080/mcp/`) | `http://localhost:8080/mcp/` |

Create a `frontend/.env` file with these values.

## MCP Client Configuration

### `.mcp.json`

For Claude Code and similar MCP clients, configure the server in `.mcp.json`:

```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "http://localhost:8080/mcp/"
    }
  }
}
```

### Claude Code CLI

```bash
claude mcp add mcp-brain --transport http http://localhost:8080/mcp/
```

### Claude Desktop

Add as a Connector in Settings > Connectors with URL: `http://localhost:8080/mcp/`

### Cursor

Add to MCP settings:

```json
{
  "mcpServers": {
    "mcp-brain": {
      "url": "http://localhost:8080/mcp/"
    }
  }
}
```

## Auth Provider Configuration

The auth provider is configured in `src/server.py`:

```python
auth_provider = MCPBrainAuthProvider(
    project_url=SUPABASE_URL,       # From env
    base_url="http://localhost:8080", # Hardcoded — needs env var for production
    algorithm="ES256",               # Supabase JWT signing algorithm
)
```

**Note:** `base_url` is currently hardcoded to `http://localhost:8080`. For production deployment, this should be made configurable via an environment variable.

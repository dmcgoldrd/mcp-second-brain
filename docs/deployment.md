# Deployment

## Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — Python package manager
- **Supabase project** with pgvector extension enabled
- **OpenAI API key** for embedding generation
- **bun** (optional, for frontend)

## Local Development

### Backend

1. Clone the repository and install dependencies:

```bash
cd mcp-brain
uv sync --all-extras
```

2. Create a `.env` file with required environment variables (see [configuration.md](configuration.md)):

```bash
cp .env.example .env  # if template exists
# Edit .env with your Supabase and OpenAI credentials
```

3. Start the server:

```bash
uv run python -m src.main
```

The server starts on `http://0.0.0.0:8080` by default (configurable via `HOST` and `PORT` env vars).

4. Verify it's running:

```bash
# Check OAuth metadata
curl http://localhost:8080/.well-known/oauth-authorization-server

# Check protected resource metadata
curl http://localhost:8080/.well-known/oauth-protected-resource

# Check 401 response
curl -X POST http://localhost:8080/mcp/
# Should return 401 with WWW-Authenticate header
```

### Frontend

1. Install dependencies:

```bash
cd frontend
bun install
```

2. Create `frontend/.env`:

```env
VITE_SUPABASE_URL=https://xxxx.supabase.co
VITE_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1Ni...
```

3. Start the dev server:

```bash
bun run dev
```

Frontend runs on `http://localhost:3000`.

### Connect an MCP Client

```bash
# Claude Code
claude mcp add mcp-brain --transport http http://localhost:8080/mcp/
```

## Testing

### Run Tests

```bash
uv run pytest
```

Tests run with auto-mocked environment variables (no real `.env` needed). Current coverage: **148 tests, 97% coverage**.

### Test Configuration

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` decorators needed. The `conftest.py` provides shared fixtures:

- `_patch_env` (autouse) — injects test environment variables
- `mock_pool` — asyncpg pool mock with `fetchrow`, `fetch`, `execute`
- `mock_openai_embedding` — OpenAI embedding mock returning 1536-dim vectors
- `mock_jwt_payload` — valid JWT claims for test user

### Coverage Report

```bash
uv run pytest --cov=src --cov-report=term-missing --cov-report=html
# HTML report generated at htmlcov/index.html
```

## Linting

```bash
# Check
uv run ruff check src/ tests/

# Fix auto-fixable issues
uv run ruff check --fix src/ tests/

# Format
uv run ruff format src/ tests/
```

Pre-commit hooks run `ruff check --fix` and `ruff format` automatically on every commit.

## Dependencies

### Runtime

| Package | Version | Purpose |
|---------|---------|---------|
| `fastmcp` | >=2.0.0 | MCP server framework (Starlette + uvicorn) |
| `asyncpg` | >=0.30.0 | Async PostgreSQL driver |
| `pgvector` | >=0.3.0 | pgvector type codec for asyncpg |
| `openai` | >=1.60.0 | OpenAI Python SDK (embedding generation) |
| `pyjwt[crypto]` | >=2.9.0 | JWT decoding + PyJWKClient |
| `httpx` | >=0.28.0 | Async HTTP client (OIDC metadata fetch) |
| `python-dotenv` | >=1.0.0 | `.env` file loading |

### Dev

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=8.0.0 | Test framework |
| `pytest-asyncio` | >=0.24.0 | Async test support |
| `pytest-cov` | >=6.0.0 | Coverage reporting |
| `ruff` | >=0.8.0 | Linter + formatter |
| `pre-commit` | >=4.0.0 | Git hooks |

## Production Considerations

### `base_url` Configuration

The `MCPBrainAuthProvider` currently has `base_url` hardcoded to `http://localhost:8080`. For production, this needs to be configurable via environment variable to match your public URL:

```python
auth_provider = MCPBrainAuthProvider(
    project_url=SUPABASE_URL,
    base_url=os.environ.get("BASE_URL", "http://localhost:8080"),
    algorithm="ES256",
)
```

### CORS

FastMCP handles CORS via Starlette. For production with a separate frontend domain, you may need to configure allowed origins.

### Reverse Proxy

If running behind nginx or similar, ensure:
- WebSocket/SSE connections are proxied correctly for Streamable HTTP transport
- `x-bank-slug` and `Authorization` headers are forwarded
- The `Host` header is preserved or `x-forwarded-host` is set

### Database Connection

The asyncpg pool connects directly to Supabase Postgres. For production:
- Ensure `SUPABASE_DB_URL` uses SSL (`?sslmode=require`)
- Consider connection pooling via Supabase's built-in pgBouncer (port 6543)
- Pool is lazily initialized — server starts even if DB is temporarily unavailable

### Rate Limiting

The current rate limiter is in-memory and per-process. For multi-process deployments, consider:
- Redis-backed rate limiting
- Or accept per-process limits as a simpler approach

# Connecting to MCP Brain

MCP Brain uses **Streamable HTTP** transport and authenticates via **Supabase JWT**.

## Server Details

| Setting | Value |
|---------|-------|
| Transport | Streamable HTTP |
| Local URL | `http://localhost:8080/mcp/` |
| Auth | Bearer token (Supabase JWT) |
| Bank selection | `x-bank-slug` header or `?bank=<slug>` query param |

## Getting a JWT

Sign in to your Supabase project and obtain an access token:

```bash
# Via curl
curl -X POST 'https://hrcogpdvxmpczsyeofnm.supabase.co/auth/v1/token?grant_type=password' \
  -H 'apikey: YOUR_SUPABASE_ANON_KEY' \
  -H 'Content-Type: application/json' \
  -d '{"email": "you@example.com", "password": "your-password"}'
```

The response contains `access_token` — use that as your Bearer token.

> **Note:** Supabase JWTs expire (default 1 hour). For long-lived connections, you'll need to refresh tokens or increase the JWT expiry in your Supabase project settings (Authentication → JWT expiry).

## Starting the Server

```bash
cd /path/to/mcp-brain
uv run python -m src.main
```

Server starts on `http://0.0.0.0:8080` by default. Override with `HOST` and `PORT` env vars.

---

## Client Configurations

### Claude Code

Add to `.mcp.json` in your project root (or `~/.claude/.mcp.json` for global):

```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>"
      }
    }
  }
}
```

**With a specific bank:**

```json
{
  "mcpServers": {
    "mcp-brain-work": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>",
        "x-bank-slug": "work"
      }
    }
  }
}
```

### Claude Desktop

Edit `claude_desktop_config.json`:

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>"
      }
    }
  }
}
```

**Multiple banks as separate entries:**

```json
{
  "mcpServers": {
    "brain-default": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>"
      }
    },
    "brain-work": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>",
        "x-bank-slug": "work"
      }
    }
  }
}
```

### Cursor

Add in Cursor Settings → MCP Servers, or edit `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>"
      }
    }
  }
}
```

---

## Minimal JSON Blob

Copy-paste starter config (replace the JWT):

```json
{
  "mcpServers": {
    "mcp-brain": {
      "type": "http",
      "url": "http://localhost:8080/mcp/",
      "headers": {
        "Authorization": "Bearer <YOUR_SUPABASE_JWT>"
      }
    }
  }
}
```

## Bank Selection

Banks scope your memories into separate collections. Two ways to select:

1. **Header** (preferred): Add `"x-bank-slug": "work"` to your `headers` config
2. **Query param**: Not supported in static config since Streamable HTTP URL is fixed

If no bank is specified, the server uses your default bank.

## Available Tools

Once connected, these MCP tools are available:

| Tool | Description |
|------|-------------|
| `create_memory` | Store a new memory with type, tags, and metadata |
| `search_memories` | Hybrid semantic + full-text search across memories |
| `list_memories` | List recent memories with optional type filter |
| `delete_memory` | Delete a specific memory by UUID |
| `brain_stats` | Get memory count, type breakdown, and date range |
| `list_banks` | List all memory banks for the user |
| `create_bank` | Create a new memory bank (e.g., "work", "personal") |

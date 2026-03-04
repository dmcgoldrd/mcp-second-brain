# HTTP Endpoints

MCP Brain serves three categories of HTTP endpoints: OAuth/OIDC metadata discovery, the MCP protocol endpoint, and protected resource metadata.

## Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/.well-known/oauth-authorization-server` | OAuth Authorization Server metadata (RFC 8414) |
| `GET` | `/.well-known/oauth-protected-resource` | Protected Resource metadata (RFC 9728) |
| `POST` | `/mcp/` | MCP protocol endpoint (Streamable HTTP) |

---

## `GET /.well-known/oauth-authorization-server`

Returns OAuth 2.1 Authorization Server metadata per [RFC 8414](https://datatracker.ietf.org/doc/html/rfc8414). MCP clients use this endpoint to discover how to authenticate.

### Implementation

Handled by `MCPBrainAuthProvider` (`src/auth/provider.py`). Supabase does not serve this endpoint natively (returns 404), so the provider:

1. Fetches Supabase's OIDC discovery at `{SUPABASE_URL}/auth/v1/.well-known/openid-configuration`
2. Transforms the OIDC config into OAuth AS metadata format

### Response — 200 OK

```json
{
  "issuer": "https://xxxx.supabase.co/auth/v1",
  "authorization_endpoint": "https://xxxx.supabase.co/auth/v1/authorize",
  "token_endpoint": "https://xxxx.supabase.co/auth/v1/token",
  "jwks_uri": "https://xxxx.supabase.co/auth/v1/.well-known/jwks.json",
  "scopes_supported": ["openid", "email", "profile"],
  "response_types_supported": ["code"],
  "grant_types_supported": ["authorization_code", "refresh_token"],
  "token_endpoint_auth_methods_supported": ["none"],
  "code_challenge_methods_supported": ["S256"]
}
```

### Response — 500 (OIDC fetch failure)

```json
{
  "error": "server_error",
  "error_description": "Failed to fetch OIDC metadata: <error details>"
}
```

---

## `GET /.well-known/oauth-protected-resource`

Returns Protected Resource metadata per [RFC 9728](https://datatracker.ietf.org/doc/html/rfc9728). Tells MCP clients which authorization server to use for this resource.

### Implementation

Served by FastMCP's built-in `SupabaseProvider` (inherited by `MCPBrainAuthProvider`).

### Response — 200 OK

```json
{
  "resource": "http://localhost:8080/mcp/",
  "authorization_servers": ["https://xxxx.supabase.co/auth/v1"]
}
```

---

## `POST /mcp/`

The main MCP protocol endpoint using Streamable HTTP transport. Accepts JSON-RPC messages for tool calls, initialization, and other MCP operations.

### Headers

| Header | Required | Description |
|--------|----------|-------------|
| `Authorization` | Yes | `Bearer <supabase-jwt>` |
| `Accept` | Yes | `application/json, text/event-stream` |
| `Content-Type` | Yes | `application/json` |
| `x-bank-slug` | No | Bank slug to scope operations (e.g., `work`). Falls back to default bank. |

### Response — 401 Unauthorized (No Token)

When no `Authorization` header is provided:

```
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer resource_metadata="http://localhost:8080/.well-known/oauth-protected-resource"
Content-Type: application/json

{
  "error": "invalid_token",
  "error_description": "Missing or invalid authorization header"
}
```

The `WWW-Authenticate` header includes a `resource_metadata` URL that MCP clients follow to discover the authorization server.

### Response — 401 Unauthorized (Invalid Token)

```json
{
  "error": "invalid_token",
  "error_description": "Token validation failed"
}
```

### Response — 200 OK (MCP)

Successful requests return MCP JSON-RPC responses. For tool calls, the response contains the tool's return value as a JSON string.

### Transport Details

- **Transport:** Streamable HTTP (FastMCP's modern transport)
- **Protocol:** JSON-RPC over HTTP POST with SSE streaming for responses
- **Single endpoint:** All MCP operations go through `/mcp/`
- **Compatible with:** Claude Code (`--transport http`), Claude Desktop (Connectors), Cursor

---

## Error Response Format

All auth-related error responses are proper JSON (never plain text). This was a deliberate design choice — MCP clients crash when they receive non-JSON responses from auth endpoints.

```json
{
  "error": "<error_code>",
  "error_description": "<human-readable message>"
}
```

| Error Code | HTTP Status | Cause |
|-----------|-------------|-------|
| `invalid_token` | 401 | Missing, expired, or malformed JWT |
| `server_error` | 500 | OIDC metadata fetch failure |

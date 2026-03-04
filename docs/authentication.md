# Authentication

MCP Brain uses Supabase JWTs for authentication, validated via FastMCP's `SupabaseProvider` with a custom subclass that fixes OAuth metadata discovery.

## Current State: Phase 1

Phase 1 implements MCP Brain as an **OAuth Resource Server**. MCP clients must obtain a Supabase JWT independently and pass it as a Bearer token. The server validates the JWT and serves OAuth metadata endpoints so clients can discover the authorization server.

**Phase 2** (future) will implement full OAuth 2.1 with browser-based authentication, DCR, and authorization code flow with PKCE. This requires enabling Supabase's OAuth 2.1 Server beta feature.

## Auth Flow

```
MCP Client
  │
  │  1. GET /.well-known/oauth-authorization-server
  │     → Discovers Supabase as the authorization server
  │
  │  2. Obtains JWT from Supabase (login, token exchange, etc.)
  │
  │  3. POST /mcp/
  │     Authorization: Bearer <supabase-jwt>
  │     x-bank-slug: work                    (optional)
  │
  ▼
MCPBrainAuthProvider (extends SupabaseProvider)
  │
  │  4. Validates JWT against Supabase JWKS
  │     Algorithm: ES256
  │     Audience: "authenticated"
  │     Issuer: "{SUPABASE_URL}/auth/v1"
  │
  │  5. Creates AccessToken with claims from JWT
  │
  ▼
Tool Handler (server.py)
  │
  │  6. _resolve_auth(token: AccessToken)
  │     a. user_id = token.claims["sub"]
  │     b. tool_limiter.check(user_id)           → ValueError if rate limited
  │     c. Read x-bank-slug from HTTP headers
  │     d. Resolve bank_id:
  │        - If x-bank-slug present → get_bank_by_slug(user_id, slug)
  │        - Otherwise → get_default_bank(user_id)
  │     e. Return {"user_id": "...", "bank_id": "..."}
  │
  ▼
Database operations scoped to (user_id, bank_id)
```

## JWT Details

| Field | Value |
|-------|-------|
| Algorithm | ES256 (ECDSA) |
| Audience | `authenticated` |
| Issuer | `{SUPABASE_URL}/auth/v1` |
| JWKS URL | `{SUPABASE_URL}/auth/v1/.well-known/jwks.json` |
| User ID claim | `sub` |

### Decoded JWT Payload

```json
{
  "sub": "b0dd4306-0d56-4ea8-bad5-27d637dd6757",
  "aud": "authenticated",
  "iss": "https://xxxx.supabase.co/auth/v1",
  "exp": 1709308800,
  "email": "user@example.com",
  "role": "authenticated"
}
```

## MCPBrainAuthProvider

**File:** `src/auth/provider.py`

Subclasses FastMCP's `SupabaseProvider` to fix a specific problem: Supabase returns 404 for `/.well-known/oauth-authorization-server` when the OAuth 2.1 Server beta is not enabled. The built-in `SupabaseProvider` tries to proxy this endpoint from Supabase, which fails.

The fix:
1. Skip `SupabaseProvider.get_routes()` and call `RemoteAuthProvider.get_routes()` directly (avoids the broken forwarding)
2. Add a custom `/.well-known/oauth-authorization-server` route that fetches Supabase's OIDC discovery endpoint and transforms it to RFC 8414 format

```python
auth_provider = MCPBrainAuthProvider(
    project_url=SUPABASE_URL,
    base_url="http://localhost:8080",
    algorithm="ES256",
)

mcp = FastMCP(name="MCP Brain", auth=auth_provider)
```

## Bank Selection

Every MCP request is scoped to a single memory bank. The bank is resolved during `_resolve_auth()`:

| Priority | Method | Description |
|----------|--------|-------------|
| 1 | `x-bank-slug` header | Direct header on the HTTP request |
| 2 | Default bank | User's bank with `is_default = true` |

If the `x-bank-slug` header specifies a slug that doesn't exist for the user, the request fails with `ValueError("Bank 'xxx' not found for this user")`.

If the user has no default bank, the request fails with `ValueError("No default bank found. Please create a bank first.")`.

## `_resolve_auth()` Implementation

**File:** `src/server.py:53-82`

```python
async def _resolve_auth(token: AccessToken) -> dict[str, str]:
    user_id = token.claims.get("sub", "")
    if not user_id:
        raise ValueError("No user ID (sub claim) in access token")

    if not tool_limiter.check(user_id):
        raise ValueError("Rate limit exceeded. Please slow down.")

    headers = get_http_headers() or {}
    bank_slug = headers.get("x-bank-slug", "").strip() or None

    if bank_slug:
        bank = await banks_db.get_bank_by_slug(user_id, bank_slug)
        if not bank:
            raise ValueError(f"Bank '{bank_slug}' not found for this user")
        bank_id = str(bank["id"])
    else:
        default_bank = await banks_db.get_default_bank(user_id)
        if not default_bank:
            raise ValueError("No default bank found. Please create a bank first.")
        bank_id = str(default_bank["id"])

    return {"user_id": user_id, "bank_id": bank_id}
```

## Legacy Auth Components

### `src/auth/jwt.py` — Standalone JWT Validation

Contains `validate_token()` and `extract_user_id()` using `PyJWKClient`. This module uses `RS256` algorithm and is **not currently used by the server** — it was part of the legacy `JWTAuthMiddleware`. Kept for reference and potential direct JWT validation use cases.

### `src/auth/middleware.py` — JWTAuthMiddleware

A FastMCP `Middleware` subclass that handled auth before Phase 1. **Not currently registered on the server.** Kept for Phase 2 reference. It had additional bank resolution logic via URL query parameters (`?bank=` from `x-forwarded-url`, `referer`, or `x-original-url` headers).

## Phase 2: Full OAuth 2.1 (Future)

Phase 2 requires:

1. **Enable Supabase OAuth 2.1 Server** — beta feature in Supabase dashboard (Authentication > OAuth Server)
2. **Register OAuth App** — get `client_id` and `client_secret` from Supabase
3. **Build consent page** — frontend page for user authorization
4. **Swap to OIDCProxy** — replace `MCPBrainAuthProvider` with FastMCP's `OIDCProxy` for full OAuth flow (DCR, authorization code, PKCE)

This enables browser-based authentication where MCP clients redirect users to sign in, eliminating the need for manually-obtained JWTs.
